"""LLM-as-judge for the two content errors that need semantic judgment:

* environment/context inconsistency (Stage-1 weather/season/apartment/persona
  facts forgotten in a day's narrative), and
* routine drift (established routines forgotten or changed without in-narrative
  motivation, compared to the previous day).

The judge uses a *different model family* than generation (judge
``openai/gpt-5.4`` vs. the generator's ``anthropic/claude-opus-4.8``, see
``config.json``) to avoid self-evaluation bias. It reads each day's Stage-2
narrative plus the fixed Stage-1 context and writes ``judge.json`` into the run
directory; evaluate.py reports it as a separate ``judge_layer`` (deliberately
NOT folded into the weighted error score or the acceptance verdict).

Usage:
    python -m src.judge --run matrix/champ_family_h7_r1 [--data-dir data_k2] [--judge-model ...]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .client import build_client, call_model
from .io_utils import read_text, write_json

DEFAULT_JUDGE_MODEL = 'openai/gpt-5.4'

SYSTEM = (
    'You are a strict, skeptical reviewer of generated smart-home day narratives. '
    'Judge ONLY the two aspects requested. Be conservative: flag an issue only when '
    'it is clearly present in the text. Respond with a SINGLE JSON object and no other text.'
)

USER_TEMPLATE = """Fixed context for the whole simulation (Stage 1):

[ENVIRONMENT]
{environment}

[RESIDENTS]
{residents}

[ROOMS / DEVICE PLACEMENT]
{rooms}

[TIME WINDOW]
{timeframe}

[PERSONA CARDS]
{cards}

---
Previous day's narrative (for drift comparison; "NONE" on the first day):
{previous}

---
Current day to judge ({day_context}):
{narrative}

---
Assess exactly two things and return JSON with this shape:
{{
  "env": {{"consistent": true|false, "violations": ["..."]}},
  "drift": {{"unmotivated_change": true|false, "notes": "..."}}
}}

- env.consistent = false only if the current narrative contradicts the fixed
  context above (e.g. ignores the stated season/weather, uses a room/device that
  the room map forbids, or contradicts a persona's stated routine/constraints).
  List each concrete contradiction in violations.
- drift.unmotivated_change = true only if an established routine from the previous
  day is dropped or changed WITHOUT any in-narrative reason. On the first day
  (previous = NONE) always return false. Keep notes to one sentence.
Return only the JSON object."""


# Strict structured output so the judge returns a parseable object directly.
JUDGE_SCHEMA = {
    'type': 'json_schema',
    'json_schema': {
        'name': 'judge_verdict',
        'strict': True,
        'schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'env': {
                    'type': 'object', 'additionalProperties': False,
                    'properties': {
                        'consistent': {'type': 'boolean'},
                        'violations': {'type': 'array', 'items': {'type': 'string'}},
                    },
                    'required': ['consistent', 'violations'],
                },
                'drift': {
                    'type': 'object', 'additionalProperties': False,
                    'properties': {
                        'unmotivated_change': {'type': 'boolean'},
                        'notes': {'type': 'string'},
                    },
                    'required': ['unmotivated_change', 'notes'],
                },
            },
            'required': ['env', 'drift'],
        },
    },
}


def _extract_json(text: str) -> dict:
    """Lenient JSON extraction: take the outermost {...} block."""
    t = text.strip()
    start, end = t.find('{'), t.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f'No JSON object found in judge output: {text[:200]!r}')
    return json.loads(t[start:end + 1])


def _day_number(name: str) -> int:
    m = re.search(r'(\d+)', name)
    return int(m.group(1)) if m else 0


def _one_vote(client, model: str, user: str) -> dict | None:
    """One judge call (temperature 0, schema-enforced); None on parse/transport failure."""
    try:
        raw = call_model(client, model, SYSTEM, user, response_format=JUDGE_SCHEMA, temperature=0)
    except Exception:  # provider may reject json_schema -> retry as plain text
        try:
            raw = call_model(client, model, SYSTEM, user, temperature=0)
        except Exception:
            return None
    try:
        return _extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        return None


def _aggregate(votes: list[dict]) -> dict:
    """Majority-combine k verdicts. env.consistent defaults True unless a majority
    says False (conservative); drift.unmotivated_change True only on a majority."""
    env_bools = [(v.get('env') or {}).get('consistent') for v in votes]
    env_bools = [b for b in env_bools if isinstance(b, bool)]
    drift_bools = [(v.get('drift') or {}).get('unmotivated_change') for v in votes]
    drift_bools = [b for b in drift_bools if isinstance(b, bool)]

    if not env_bools and not drift_bools:
        return {'env': {'consistent': None, 'violations': ['judge unparseable in all votes']},
                'drift': {'unmotivated_change': None, 'notes': 'judge unparseable'},
                'votes': len(votes)}

    env_consistent = (sum(env_bools) >= len(env_bools) - sum(env_bools)) if env_bools else None
    # None (not False) when no drift vote parsed, so a half-parsed verdict surfaces
    # as a judge parse error downstream instead of silently counting as clean.
    drift_change = (sum(drift_bools) > len(drift_bools) - sum(drift_bools)) if drift_bools else None
    violations = sorted({x for v in votes for x in ((v.get('env') or {}).get('violations') or [])
                         if (v.get('env') or {}).get('consistent') is False})
    notes = next((n for v in votes if (n := (v.get('drift') or {}).get('notes'))
                  and (v.get('drift') or {}).get('unmotivated_change')), '')
    return {'env': {'consistent': env_consistent, 'violations': violations},
            'drift': {'unmotivated_change': drift_change, 'notes': notes},
            'votes': len(votes)}


def judge_run(run_dir: Path, data_dir: Path, files: dict, model: str, votes: int = 3) -> dict:
    client = build_client()
    environment = read_text(data_dir / files['environment'])
    residents = read_text(data_dir / files['residents'])
    rooms = read_text(data_dir / files['rooms'])
    timeframe = read_text(data_dir / files['timeframe'])
    cards_path = run_dir / 'stage1_persona_cards.txt'
    cards = read_text(cards_path) if cards_path.exists() else '(not available)'

    day_dirs = sorted((d for d in run_dir.glob('day_*') if d.is_dir()), key=lambda p: _day_number(p.name))
    per_day = []
    previous = 'NONE'
    total_days = len(day_dirs)

    for dd in day_dirs:
        narr_path = dd / 'stage2_narrative.txt'
        if not narr_path.exists():
            continue
        day_num = _day_number(dd.name)
        narrative = read_text(narr_path)
        user = USER_TEMPLATE.format(
            environment=environment, residents=residents, rooms=rooms, timeframe=timeframe,
            cards=cards, previous=previous, day_context=f'Day {day_num} of {total_days}',
            narrative=narrative,
        )
        raw_votes = [v for v in (_one_vote(client, model, user) for _ in range(max(1, votes))) if v is not None]
        verdict = _aggregate(raw_votes) if raw_votes else _aggregate([])
        verdict['day'] = day_num
        per_day.append(verdict)
        env_ok = (verdict.get('env') or {}).get('consistent')
        drift_flag = (verdict.get('drift') or {}).get('unmotivated_change')
        print(f'  day {day_num}: env_consistent={env_ok}, routine_drift={drift_flag} '
              f'({len(raw_votes)}/{max(1, votes)} votes parsed)')
        previous = narrative

    return {'run': run_dir.name, 'judge_model': model, 'votes': votes, 'per_day': per_day}


def main() -> None:
    parser = argparse.ArgumentParser(description='LLM-as-judge for env/context + routine drift.')
    parser.add_argument('--run', required=True, help='Run name under outputs/.')
    parser.add_argument('--data-dir', type=str, default=None, help='Constellation data dir (default: config data_dir).')
    parser.add_argument('--judge-model', type=str, default=None,
                        help=f'Judge model (default: config judge_model or {DEFAULT_JUDGE_MODEL}).')
    parser.add_argument('--votes', type=int, default=3,
                        help='Number of judge votes per day; majority is taken (default 3).')
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    files = config['files']
    data_dir = Path(args.data_dir) if args.data_dir else root / config['paths']['data_dir']
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    model = args.judge_model or config.get('judge_model') or DEFAULT_JUDGE_MODEL

    run_dir = root / config['paths']['outputs_dir'] / args.run
    if not run_dir.exists():
        raise SystemExit(f'Run not found: {run_dir}')

    print(f'Judging {run_dir.name} with {model} ({args.votes} vote(s)/day) ...')
    result = judge_run(run_dir, data_dir, files, model, votes=args.votes)
    write_json(run_dir / 'judge.json', result)
    print(f'\nJudge verdicts written to: {run_dir / "judge.json"}')


if __name__ == '__main__':
    main()
