from __future__ import annotations

import json
import re
from pathlib import Path

from .client import call_model
from .errors import make_error
from .io_utils import read_json, read_text, write_json, write_text
from .prompt_loader import fill_template, load_prompt
from .rooms import build_access
from .validator import error_messages, extract_resident_names, parse_window, validate_actions


WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MAX_REPAIRS = 3


def _dedup_continuity(actions: list[dict]) -> list[dict]:
    """Deterministically drop continuity re-assertions: an action that sets a
    (device, action) to the value it already holds is a no-op, not a real state
    change, so removing it leaves the physical log unchanged. Used only as a final
    safety net after the LLM self-repair, so a run never fails on continuity alone."""
    last: dict[tuple, object] = {}
    out: list[dict] = []
    for a in actions:
        key = (a.get('device'), a.get('action'))
        val = a.get('action_value')
        if key in last and last[key] == val:
            continue
        last[key] = val
        out.append(a)
    return out


def _call_structured(client, model, system_prompt, user_prompt, schema, cache_prefix=None):
    """Stage-3 call with structured output; fall back to plain text if the provider
    rejects the json_schema response_format (the validator + self-repair then
    recover from any non-conformance). Keeps the pipeline model-agnostic."""
    try:
        return call_model(client, model, system_prompt, user_prompt, response_format=schema,
                          cache_prefix=cache_prefix)
    except Exception:
        return call_model(client, model, system_prompt, user_prompt, cache_prefix=cache_prefix)


def build_shared_reference(residents, environment, devices_text, device_descriptions, rooms) -> str:
    """The run-fixed context (residents, environment, device schema, descriptions,
    rooms) sent once as a cached system prefix on every stage call. Byte-identical
    across all stages and days of a run, so Stage 1 writes the cache and every later
    call reads it at ~0.1x. Keep this deterministic -- any change invalidates the cache."""
    return (
        '=== FIXED REFERENCE CONTEXT (identical for every step of this simulation) ===\n'
        'Use ONLY the residents, devices, actions, device descriptions and rooms below. '
        'Do not repeat this context back in your output.\n\n'
        f'Residents:\n{residents}\n\n'
        f'Global context:\n{environment}\n\n'
        f'Devices and allowed actions (schema):\n{devices_text}\n\n'
        'Device descriptions (what each device physically is and how its values map to real '
        f'behavior):\n{device_descriptions}\n\n'
        f'Rooms and device placement:\n{rooms}\n'
    )


def _strip_fences(text: str) -> str:
    """Remove a leading ```json / ``` fence and trailing ``` if the model added one."""
    t = text.strip()
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
        t = re.sub(r'\s*```$', '', t)
    return t.strip()


def _parse_and_validate(raw, devices, resident_names, window=None, access=None):
    """Return (actions_or_None, errors). actions is None if the text is not valid JSON."""
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        return None, [make_error('INVALID_JSON', f'Invalid JSON: {exc}')]
    # Structured output wraps the list as {"actions": [...]}; accept a bare list too.
    actions = data['actions'] if isinstance(data, dict) and 'actions' in data else data
    return actions, validate_actions(actions, devices, resident_names, window=window, access=access)


def build_stage3_schema(devices, resident_names):
    """Strict JSON schema for Stage 3 structured output: an object with an 'actions' array.

    Device and resident names are enumerated so unknown-device and
    non-singular/unknown-resident errors are prevented at generation time.
    Device-specific action/value validity and continuity remain the validator's job.
    """
    device_names = [d['device'] for d in devices if isinstance(d.get('device'), str)]
    resident_prop = {'type': 'string', 'enum': resident_names} if resident_names else {'type': 'string'}
    item = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'timestamp': {'type': 'string'},
            'resident': resident_prop,
            'device': {'type': 'string', 'enum': device_names},
            'action': {'type': 'string'},
            'action_value': {'type': ['string', 'null']},
            'intent': {'type': 'string'},
        },
        'required': ['timestamp', 'resident', 'device', 'action', 'action_value', 'intent'],
    }
    schema = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {'actions': {'type': 'array', 'items': item}},
        'required': ['actions'],
    }
    return {
        'type': 'json_schema',
        'json_schema': {'name': 'smart_home_actions', 'strict': True, 'schema': schema},
    }


def run_pipeline(
    client,
    project_root: str | Path,
    config: dict,
    days: int = 1,
    run_name: str = 'run',
    data_dir: str | Path | None = None,
) -> None:
    root = Path(project_root)
    prompts_dir = root / config['paths']['prompts_dir']
    data_dir = Path(data_dir) if data_dir else root / config['paths']['data_dir']
    outputs_dir = root / config['paths']['outputs_dir'] / run_name
    files = config['files']
    model = config['model']

    residents = read_text(data_dir / files['residents'])
    environment = read_text(data_dir / files['environment'])
    timeframe = read_text(data_dir / files['timeframe'])
    devices = read_json(data_dir / files['devices'])
    devices_text = json.dumps(devices, indent=2, ensure_ascii=False)
    device_descriptions = read_text(data_dir / files['device_descriptions'])
    rooms = read_text(data_dir / files['rooms'])
    resident_names = extract_resident_names(residents)
    window = parse_window(timeframe)
    access = build_access(rooms, residents, resident_names)

    # Run-fixed context, sent once as a cached system prefix on every call.
    shared_reference = build_shared_reference(residents, environment, devices_text, device_descriptions, rooms)
    max_repairs = int(config.get('max_repairs', MAX_REPAIRS))

    s1_system = load_prompt(prompts_dir / files['stage1_system'])
    s1_user_template = load_prompt(prompts_dir / files['stage1_user'])
    s1_user = fill_template(
        s1_user_template,
        {
            'RESIDENTS': residents,
            'ENVIRONMENT': environment,
            'DEVICES': devices_text,
            'DEVICE_DESCRIPTIONS': device_descriptions,
            'ROOMS': rooms,
        },
    )
    current_cards = call_model(client, model, s1_system, s1_user, cache_prefix=shared_reference)
    write_text(outputs_dir / 'stage1_persona_cards.txt', current_cards)

    s2_system = load_prompt(prompts_dir / files['stage2_system'])
    s2_user_template = load_prompt(prompts_dir / files['stage2_user'])
    s3_system = load_prompt(prompts_dir / files['stage3_system'])
    s3_user_template = load_prompt(prompts_dir / files['stage3_user'])
    s3_repair_template = load_prompt(prompts_dir / files['stage3_repair_user'])
    s4_system = load_prompt(prompts_dir / files['stage4_system'])
    s4_user_template = load_prompt(prompts_dir / files['stage4_user'])

    s3_schema = build_stage3_schema(devices, resident_names)

    for day in range(1, days + 1):
        weekday = WEEKDAYS[(day - 1) % 7]
        day_context = f'Day {day} of {days} ({weekday})'
        day_dir = outputs_dir / f'day_{day:02d}'

        s2_user = fill_template(
            s2_user_template,
            {
                'TIMEFRAME': timeframe,
                'PERSONA_CARDS': current_cards,
                'DEVICES': devices_text,
                'DEVICE_DESCRIPTIONS': device_descriptions,
                'ROOMS': rooms,
                'DAY_CONTEXT': day_context,
            },
        )
        stage2_text = call_model(client, model, s2_system, s2_user, cache_prefix=shared_reference)
        write_text(day_dir / 'stage2_narrative.txt', stage2_text)

        # Stage 3 (structured output) + self-repair loop: re-prompt with the
        # validation errors until clean or until MAX_REPAIRS is reached.
        s3_user = fill_template(
            s3_user_template,
            {'DEVICES': devices_text, 'NARRATIVE': stage2_text},
        )
        stage3_raw = _call_structured(client, model, s3_system, s3_user, s3_schema, cache_prefix=shared_reference)
        write_text(day_dir / 'stage3_raw.json', stage3_raw)
        actions, errors = _parse_and_validate(stage3_raw, devices, resident_names, window, access)

        repairs = 0
        while (actions is None or errors) and repairs < max_repairs:
            repairs += 1
            repair_user = fill_template(
                s3_repair_template,
                {
                    'DEVICES': devices_text,
                    'NARRATIVE': stage2_text,
                    'PREVIOUS_JSON': stage3_raw,
                    'ERRORS': '\n'.join(error_messages(errors)) if errors else 'Output was not valid JSON.',
                },
            )
            stage3_raw = _call_structured(client, model, s3_system, repair_user, s3_schema, cache_prefix=shared_reference)
            write_text(day_dir / f'stage3_repair_{repairs}.json', stage3_raw)
            actions, errors = _parse_and_validate(stage3_raw, devices, resident_names, window, access)

        suffix = f' (after {repairs} repair attempt(s))' if repairs else ''
        if actions is None:
            write_text(day_dir / 'stage3_validation.txt', f'Invalid JSON{suffix}.')
            continue

        # Final safety net: if continuity re-assertions survived repair, drop the
        # provably-redundant rows deterministically and re-validate.
        if errors and any(e['code'] == 'CONTINUITY' for e in errors):
            actions = _dedup_continuity(actions)
            errors = validate_actions(actions, devices, resident_names, window=window, access=access)
            suffix += ' [continuity auto-deduped]'

        write_json(day_dir / 'stage3_actions.json', actions)
        write_text(
            day_dir / 'stage3_validation.txt',
            ('\n'.join(error_messages(errors)) if errors else 'Validation passed.') + suffix,
        )

        s4_user = fill_template(
            s4_user_template,
            {
                'TIMEFRAME': timeframe,
                'DAY_CONTEXT': day_context,
                'CURRENT_CARDS': current_cards,
                'ACTIONS': json.dumps(actions, indent=2, ensure_ascii=False),
            },
        )
        current_cards = call_model(client, model, s4_system, s4_user, cache_prefix=shared_reference)
        write_text(day_dir / 'stage4_persona_cards.txt', current_cards)

    write_text(outputs_dir / 'final_persona_cards.txt', current_cards)
