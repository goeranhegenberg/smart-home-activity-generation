from __future__ import annotations

import re
from typing import Any

from .errors import make_error

TIME_RE = re.compile(r'^\d{2}:\d{2}$')
_CONJUNCTION_RE = re.compile(r'(\sand\s|\s&\s|\+|/| und )', re.IGNORECASE)


def build_device_index(devices: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    index: dict[str, dict[str, list[str]]] = {}
    for item in devices:
        device_name = item.get('device')
        allowed_values = item.get('allowed_values', {})
        if isinstance(device_name, str) and isinstance(allowed_values, dict):
            cleaned = {}
            for key, value in allowed_values.items():
                if isinstance(key, str) and isinstance(value, list):
                    cleaned[key] = [str(v) for v in value]
            index[device_name] = cleaned
    return index


def extract_resident_names(residents_text: str) -> list[str]:
    names: list[str] = []
    for line in residents_text.splitlines():
        line = line.strip().lstrip('-').strip()
        if not line:
            continue
        head, _, _ = line.partition(':')
        name = head.strip()
        if name:
            names.append(name)
    return names


def _to_minutes(ts: str) -> int | None:
    m = re.match(r'^(\d{2}):(\d{2})$', ts.strip()) if isinstance(ts, str) else None
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def parse_window(timeframe_text: str) -> tuple[int, int] | None:
    """Parse 'HH:MM-HH:MM' into (start_minute, end_minute)."""
    m = re.search(r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})', timeframe_text or '')
    if not m:
        return None
    start = int(m.group(1)) * 60 + int(m.group(2))
    end = int(m.group(3)) * 60 + int(m.group(4))
    return (start, end)


_MULTI_RESIDENT_TOKENS = (' and ', ' & ', ',', '/', ' + ')


def error_messages(errors: list[dict]) -> list[str]:
    """Render structured errors as plain strings for the repair prompt."""
    return [e['detail'] or f"{e['label']} ({e['code']})" for e in errors]


def validate_actions(
    actions: Any,
    devices: list[dict[str, Any]],
    resident_names: list[str] | None = None,
    window: tuple[int, int] | None = None,
    access: dict[str, set[str]] | None = None,
) -> list[dict]:
    """Validate a day's actions. Returns a list of structured error records.

    ``window`` enables timestamp monotonicity + within-window checks;
    ``access`` (device -> allowed residents) enables the device-accessibility
    (persona-consistency) check. Both are optional; when omitted those checks
    are skipped.
    """
    errors: list[dict] = []
    device_index = build_device_index(devices)

    if not isinstance(actions, list):
        return [make_error('NOT_LIST', 'Stage 3 output is not a JSON array.')]

    if len(actions) == 0:
        return [make_error('EMPTY_DAY', 'Stage 3 produced zero actions for this window.')]

    required = ['timestamp', 'resident', 'device', 'action', 'action_value', 'intent']

    last_value: dict[tuple[str, str], Any] = {}
    prev_minute: int | None = None

    for i, item in enumerate(actions):
        if not isinstance(item, dict):
            errors.append(make_error('NOT_OBJECT', f'Item {i} is not an object.'))
            continue

        for field in required:
            if field not in item:
                errors.append(make_error('MISSING_FIELD', f"Item {i} is missing field '{field}'."))

        timestamp = item.get('timestamp')
        device = item.get('device')
        action = item.get('action')
        action_value = item.get('action_value')
        resident = item.get('resident')

        if isinstance(resident, str):
            lowered = resident.lower()
            if any(tok in lowered for tok in _MULTI_RESIDENT_TOKENS) or lowered in {'everyone', 'family', 'all', 'both'}:
                errors.append(make_error(
                    'RESIDENT_NONSINGULAR',
                    f"Item {i} has non-singular resident '{resident}'. Must name exactly one person.",
                ))
            elif resident_names and resident not in resident_names:
                errors.append(make_error(
                    'RESIDENT_UNKNOWN',
                    f"Item {i} has unknown resident '{resident}'. Known: {resident_names}.",
                ))
        elif resident is not None:
            errors.append(make_error(
                'RESIDENT_TYPE',
                f"Item {i} resident must be a string, got {type(resident).__name__}.",
            ))

        # Timestamp: format, then (optionally) monotonicity + within-window.
        # A present-but-non-string timestamp (int/float/null) is also a format
        # error; the absent-key case is already covered by MISSING_FIELD above.
        minute = None
        if 'timestamp' in item:
            if not isinstance(timestamp, str) or not TIME_RE.match(timestamp):
                errors.append(make_error('TIMESTAMP_FORMAT', f"Item {i} has invalid timestamp {timestamp!r}."))
            else:
                minute = _to_minutes(timestamp)
        if minute is not None:
            if prev_minute is not None and minute < prev_minute:
                errors.append(make_error(
                    'TIMESTAMP_NONMONOTONIC',
                    f"Item {i} timestamp '{timestamp}' goes backwards (previous was later).",
                ))
            if window is not None and not (window[0] <= minute <= window[1]):
                hh, mm = divmod(window[0], 60)
                hh2, mm2 = divmod(window[1], 60)
                errors.append(make_error(
                    'TIMESTAMP_OUT_OF_WINDOW',
                    f"Item {i} timestamp '{timestamp}' is outside the window "
                    f"{hh:02d}:{mm:02d}-{hh2:02d}:{mm2:02d}.",
                ))
            prev_minute = max(prev_minute, minute) if prev_minute is not None else minute

        # Non-atomic: a single action that bundles two effects (e.g. "on and dim").
        if isinstance(action, str) and _CONJUNCTION_RE.search(action):
            errors.append(make_error(
                'NON_ATOMIC',
                f"Item {i} action '{action}' bundles multiple effects; split into atomic actions.",
            ))
        if isinstance(action_value, str) and _CONJUNCTION_RE.search(action_value):
            errors.append(make_error(
                'NON_ATOMIC',
                f"Item {i} action_value '{action_value}' bundles multiple values; use one per action.",
            ))

        if device not in device_index:
            errors.append(make_error('UNKNOWN_DEVICE', f"Item {i} uses unknown device '{device}'."))
            continue

        allowed_actions = device_index[device]
        if action not in allowed_actions:
            errors.append(make_error(
                'INVALID_ACTION', f"Item {i} uses invalid action '{action}' for device '{device}'."
            ))
            continue

        if action_value is not None:
            allowed = allowed_actions[action]
            if str(action_value) not in allowed:
                errors.append(make_error(
                    'INVALID_VALUE',
                    f"Item {i} uses invalid action_value '{action_value}' for action '{action}' on device '{device}'.",
                ))

        # Persona accessibility: resident must be able to reach the device's room.
        if access and isinstance(resident, str) and device in access:
            if resident not in access[device]:
                allowed_res = sorted(access[device])
                errors.append(make_error(
                    'PERSONA_INACCESSIBLE',
                    f"Item {i}: '{resident}' operates '{device}' but only {allowed_res} can access its room.",
                ))

        if isinstance(device, str) and isinstance(action, str):
            key = (device, action)
            if key in last_value and last_value[key] == action_value:
                errors.append(make_error(
                    'CONTINUITY',
                    f"Item {i} re-asserts unchanged state for {device}.{action}={action_value!r} "
                    f"(previous value was identical). Skip continuity events.",
                ))
            last_value[key] = action_value

    return errors
