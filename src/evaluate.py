"""Deterministic evaluation harness for generated runs.

Operates only on the files a run already produced (no API calls). Computes
validity, drift metrics and a weighted error score (Fehlerbepunktung): formal
errors via re-validation of each day's final actions, content errors via
run-level rules (state accumulation, missing variation). The result includes a
PASS/WARN/FAIL acceptance verdict against configurable thresholds.

If a judge.json from judge.py is present, its environment/context and
routine-drift findings are reported as a SEPARATE ``judge_layer`` section --
deliberately NOT folded into the error score or the verdict (uncalibrated,
cross-family LLM-judge; see the paper's error-catalog table).

Usage:
    python evaluate.py --run matrix/champ_family_h7_r1 [--data-dir data_k2]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

from .errors import SEVERITY_WEIGHT, make_error, summarize_errors
from .io_utils import read_json, read_text, write_json
from .rooms import build_access
from .validator import extract_resident_names, parse_window, validate_actions

VARIATION_JACCARD_THRESHOLD = 0.95  # >= this between consecutive days => "nearly identical"
ACCUMULATION_MIN_STREAK = 3         # a device on for >= this many consecutive days
# Accumulation is only meaningful when (most of) the day is simulated. On a partial
# window (e.g. 06:00-09:00) a device on at window-end is normally switched off later
# that day -- outside the observed window -- so carrying it to the next same-window day
# is expected, not a forgotten device. Only check accumulation at/above this span.
ACCUMULATION_FULL_DAY_MIN_SPAN = 18 * 60  # minutes

_ON_RE = re.compile(r'\bon\b', re.IGNORECASE)
_OFF_RE = re.compile(r'\boff\b', re.IGNORECASE)


def parse_sections(card_text: str) -> tuple[dict[str, str], list[str], int]:
    """Extract the world-state dict, active-events list, and resident-card length."""
    world: dict[str, str] = {}
    events: list[str] = []
    section = None
    body_len = 0
    for line in card_text.splitlines():
        stripped = line.strip()
        if stripped.startswith('## World state'):
            section = 'world'
            continue
        if stripped.startswith('## Active events'):
            section = 'events'
            continue
        if stripped.startswith('##'):
            section = None
            continue
        if section is None:
            body_len += len(line)
            continue
        if not stripped.startswith('-'):
            continue
        entry = stripped[1:].strip()
        if section == 'world':
            if entry.lower().startswith('(all devices'):
                continue
            name, _, state = entry.partition(':')
            world[name.strip()] = state.strip()
        elif section == 'events':
            if entry.lower() == 'none':
                continue
            events.append(entry)
    return world, events, body_len


def allowed_pairs(devices: list[dict]) -> tuple[set, set]:
    pairs, triples = set(), set()
    for d in devices:
        name = d.get('device')
        for action, values in (d.get('allowed_values') or {}).items():
            pairs.add((name, action))
            for v in values:
                triples.add((name, action, str(v)))
    return pairs, triples


def _day_number(name: str) -> int:
    m = re.search(r'(\d+)', name)
    return int(m.group(1)) if m else 0


def _is_on(state: str) -> bool:
    return bool(_ON_RE.search(state)) and not bool(_OFF_RE.search(state))


def _accumulation_errors(days: list[dict], devices: list[dict] | None = None,
                         window: tuple[int, int] | None = None) -> list[dict]:
    """Flag any device on for >= ACCUMULATION_MIN_STREAK consecutive days.

    Only meaningful on (near-)full-day windows: on a partial window (e.g. 06:00-09:00)
    a device left on at window-end is normally switched off later the same day, outside
    what we observe, so carrying it to the next morning is expected, not accumulation.
    For partial windows the check is skipped to avoid that false positive; full-day
    (00:00-24:00) runs keep it.

    Robustness fixes: device keys are canonicalized to the schema's casing (the
    LLM sometimes capitalizes, e.g. 'Tuya_lamp') so case drift does not reset a
    streak; an omitted device carries forward its last-known state ('no action =
    unchanged', per the Stage-4 rule) instead of being read as off. Each affected
    device yields ONE run-level error (day=None, so it is judged by the mean/total
    rather than dumped on a single day) whose weight scales with streak length.
    """
    if window is not None and (window[1] - window[0]) < ACCUMULATION_FULL_DAY_MIN_SPAN:
        return []
    canon = {d['device'].casefold(): d['device'] for d in (devices or []) if isinstance(d.get('device'), str)}

    def canonical(name: str) -> str:
        return canon.get(name.casefold(), name)

    all_devs = {canonical(name) for d in days for name in d['world_state']}
    errors: list[dict] = []
    for dev in sorted(all_devs):
        last_known = 'off'
        streak = 0
        streak_start = 0
        max_streak = 0
        max_start = 0
        for d in days:
            # canonical lookup; if the device is omitted this day, carry last state
            state = next((v for k, v in d['world_state'].items() if canonical(k) == dev), None)
            if state is None:
                state = last_known
            last_known = state
            if _is_on(state):
                if streak == 0:
                    streak_start = d['day_num']
                streak += 1
                if streak > max_streak:
                    max_streak, max_start = streak, streak_start
            else:
                streak = 0
        if max_streak >= ACCUMULATION_MIN_STREAK:
            # weight scales with how long the device stayed on (mittel base = 2)
            weight = SEVERITY_WEIGHT['mittel'] + (max_streak - ACCUMULATION_MIN_STREAK)
            errors.append(make_error(
                'STATE_ACCUMULATION',
                f"'{dev}' bleibt ab Tag {max_start} ueber {max_streak} Tage durchgehend "
                f'an (nie ausgeschaltet).',
                day=None,
                weight=weight,
            ))
    return errors


def _judge_layer(run_dir: Path) -> dict | None:
    """Summarize an optional judge.json (LLM-as-judge: env + drift) as a
    SEPARATE layer.

    The judge findings are deliberately NOT folded into the weighted error
    score or the acceptance verdict (uncalibrated, single cross-family vote);
    they are reported alongside it, mirroring the paper's error-catalog table.
    A None flag means that part of the judge response could not be parsed --
    counted as unparseable instead of silently as clean.
    """
    path = run_dir / 'judge.json'
    if not path.exists():
        return None
    data = read_json(path)
    per_day: list[dict] = []
    env_bad = drift_bad = unparseable = 0
    for entry in data.get('per_day', []):
        env = entry.get('env') or {}
        drift = entry.get('drift') or {}
        env_consistent = env.get('consistent')
        drift_flag = drift.get('unmotivated_change')
        if env_consistent is False:
            env_bad += 1
        if drift_flag is True:
            drift_bad += 1
        if env_consistent is None or drift_flag is None:
            unparseable += 1
        per_day.append({
            'day': entry.get('day'),
            'env_consistent': env_consistent,
            'routine_drift': drift_flag,
            'violations': env.get('violations') or [],
            'notes': drift.get('notes') or '',
        })
    return {
        'judge_model': data.get('judge_model'),
        'votes_per_day': data.get('votes'),
        'days_judged': len(per_day),
        'env_inconsistent_days': env_bad,
        'routine_drift_days': drift_bad,
        'unparseable_days': unparseable,
        'per_day': per_day,
        'note': 'Separate semantische Ebene (unkalibriert); nicht in error_score/acceptance eingerechnet.',
    }


def evaluate_run(
    run_dir: Path,
    devices: list[dict],
    window: tuple[int, int] | None = None,
    access: dict[str, set[str]] | None = None,
    resident_names: list[str] | None = None,
    thresholds: dict | None = None,
) -> dict:
    a_pairs, _ = allowed_pairs(devices)
    day_dirs = sorted((d for d in run_dir.glob('day_*') if d.is_dir()), key=lambda p: _day_number(p.name))

    days = []
    used_pairs_all: set = set()
    day_triple_sets: list[set] = []
    formal_errors: list[dict] = []

    for dd in day_dirs:
        actions_path = dd / 'stage3_actions.json'
        if not actions_path.exists():
            continue
        actions = read_json(actions_path)
        day_num = _day_number(dd.name)
        validation = read_text(dd / 'stage3_validation.txt') if (dd / 'stage3_validation.txt').exists() else ''
        cards = read_text(dd / 'stage4_persona_cards.txt') if (dd / 'stage4_persona_cards.txt').exists() else ''
        world, events, card_len = parse_sections(cards)

        repairs = 0
        m = re.search(r'after (\d+) repair', validation)
        if m:
            repairs = int(m.group(1))

        # Re-validation against the full (extended) rule set is the authoritative
        # pass/fail signal; the prose 'Validation passed' string is only advisory.
        day_errors = validate_actions(actions, devices, resident_names, window=window, access=access)
        for e in day_errors:
            e['day'] = day_num
            formal_errors.append(e)
        passed = len(day_errors) == 0

        triples = {(a.get('device'), a.get('action'), str(a.get('action_value'))) for a in actions}
        day_triple_sets.append(triples)
        used_pairs_all |= {(a.get('device'), a.get('action')) for a in actions}

        days.append({
            'day': dd.name,
            'day_num': day_num,
            'n_actions': len(actions),
            'passed': passed,
            'repairs': repairs,
            'world_state': world,
            'events': events,
            'n_active_events': len(events),
            'card_len': card_len,
        })

    n = len(days)
    churn = []
    for i in range(1, n):
        prev, cur = days[i - 1]['world_state'], days[i]['world_state']
        keys = set(prev) | set(cur)
        churn.append(sum(1 for k in keys if prev.get(k) != cur.get(k)))

    sims = []
    for i in range(1, n):
        a, b = day_triple_sets[i - 1], day_triple_sets[i]
        if a or b:
            sims.append(len(a & b) / len(a | b))

    counts = [d['n_actions'] for d in days]
    card_lens = [d['card_len'] for d in days if d['card_len'] > 0]

    # --- content errors (semantic, weighted) ---
    # Run-spanning content errors are classified run-level (day=None) so they are
    # judged by the mean/total content score rather than inflating one day's acute
    # gate (the affected day is still named in the detail text).
    content_errors: list[dict] = []
    for i, sim in enumerate(sims):
        if sim >= VARIATION_JACCARD_THRESHOLD:
            later = days[i + 1]['day_num']
            content_errors.append(make_error(
                'MISSING_VARIATION',
                f'Tag {days[i]["day_num"]}->{later}: Jaccard {sim:.2f} '
                f'(>= {VARIATION_JACCARD_THRESHOLD}, nahezu identische Tage).',
                day=None,
            ))
    content_errors += _accumulation_errors(days, devices, window)

    all_errors = formal_errors + content_errors
    if n == 0:
        all_errors.append(make_error(
            'EMPTY_RUN', 'Keine auswertbaren Tage (stage3_actions.json fehlt ueberall).'))
    error_score = summarize_errors(all_errors, n, thresholds)

    # --- per-day quality curve (D3: Fehler-/Drift-Entwicklung über die Tage) and
    # breakpoint (D5: ab welchem Tag bricht die Qualität ein) ---
    es_per_day = error_score.get('per_day', {})
    max_content_day_th = error_score.get('thresholds', {}).get('max_content_per_day', 2)
    sim_by_later = {days[i + 1]['day_num']: round(s, 3) for i, s in enumerate(sims)}
    quality_curve = []
    cum_content = 0
    for d in days:
        dnum = d['day_num']
        slot = es_per_day.get(str(dnum), {'formal': 0, 'content_weight': 0})
        cum_content += slot.get('content_weight', 0)
        quality_curve.append({
            'day_num': dnum,
            'n_actions': d['n_actions'],
            'passed': d['passed'],
            'repairs': d['repairs'],
            'formal_errors': slot.get('formal', 0),
            'content_weight': slot.get('content_weight', 0),
            'cumulative_content_weight': cum_content,
            'jaccard_to_prev': sim_by_later.get(dnum),
        })

    def _first(pred):
        return next((q['day_num'] for q in quality_curve if pred(q)), None)

    first_invalid = _first(lambda q: not q['passed'])
    first_content_exceed = _first(lambda q: q['content_weight'] > max_content_day_th)
    first_identical = next((dn for dn, s in sorted(sim_by_later.items())
                            if s >= VARIATION_JACCARD_THRESHOLD), None)
    candidates = [x for x in (first_invalid, first_content_exceed, first_identical) if x is not None]
    breakpoint_info = {
        'first_invalid_day': first_invalid,
        'first_content_exceed_day': first_content_exceed,
        'first_identical_day': first_identical,
        'breaks_at_day': min(candidates) if candidates else None,
        'note': 'breaks_at_day = erster Tag mit formalem Fehler, Überschreitung der '
                'Inhalts-Score-Schranke/Tag oder nahezu identischer Wiederholung; '
                'null = über den ganzen Lauf stabil.',
    }

    return {
        'run': run_dir.name,
        'n_days': n,
        'validity': {
            'days_passed': sum(1 for d in days if d['passed']),
            'days_with_repair': sum(1 for d in days if d['repairs'] > 0),
            'total_repairs': sum(d['repairs'] for d in days),
            'pct_valid': round(100 * sum(1 for d in days if d['passed']) / n, 1) if n else 0.0,
        },
        'actions_per_day': {
            'values': counts,
            'mean': round(statistics.mean(counts), 1) if counts else 0,
            'stdev': round(statistics.pstdev(counts), 2) if len(counts) > 1 else 0.0,
            'min': min(counts) if counts else 0,
            'max': max(counts) if counts else 0,
        },
        'drift': {
            'world_state_churn_per_transition': churn,
            'mean_churn': round(statistics.mean(churn), 2) if churn else 0.0,
            'card_len_first': card_lens[0] if card_lens else 0,
            'card_len_last': card_lens[-1] if card_lens else 0,
            'card_len_growth_pct': round(100 * (card_lens[-1] - card_lens[0]) / card_lens[0], 1) if len(card_lens) > 1 and card_lens[0] else 0.0,
        },
        'variation': {
            'consecutive_jaccard': [round(s, 3) for s in sims],
            'mean_jaccard': round(statistics.mean(sims), 3) if sims else 0.0,
        },
        'realism_rulebased': {
            'device_action_coverage': round(len(used_pairs_all) / len(a_pairs), 3) if a_pairs else 0.0,
            'used_device_action_pairs': len(used_pairs_all),
            'allowed_device_action_pairs': len(a_pairs),
        },
        'judge_layer': _judge_layer(run_dir),
        'error_score': error_score,
        'quality_curve': quality_curve,
        'breakpoint': breakpoint_info,
        'per_day': days,
    }


def _print_summary(r: dict) -> None:
    v, a, d = r['validity'], r['actions_per_day'], r['drift']
    print(f"== {r['run']} ({r['n_days']} days) ==")
    print(f"  valid days: {v['days_passed']}/{r['n_days']} ({v['pct_valid']}%), "
          f"repairs: {v['total_repairs']} on {v['days_with_repair']} day(s)")
    print(f"  actions/day: mean {a['mean']} (sd {a['stdev']}, range {a['min']}-{a['max']})")
    print(f"  world-state churn/transition: {d['world_state_churn_per_transition']} (mean {d['mean_churn']})")
    print(f"  card length growth: {d['card_len_growth_pct']}% ({d['card_len_first']} -> {d['card_len_last']})")
    print(f"  day-to-day Jaccard (variation): mean {r['variation']['mean_jaccard']} {r['variation']['consecutive_jaccard']}")
    rr = r['realism_rulebased']
    print(f"  device-action coverage: {rr['device_action_coverage']} ({rr['used_device_action_pairs']}/{rr['allowed_device_action_pairs']})")
    jl = r.get('judge_layer')
    if jl:
        print(f"  judge layer (separat, nicht im Verdikt): {jl['env_inconsistent_days']} env-inkonsistent, "
              f"{jl['routine_drift_days']} Routine-Drift von {jl['days_judged']} Tagen "
              f"({jl['judge_model']})")
    es = r['error_score']
    acc = es['acceptance']
    print(f"  error score: formal={es['formal_total']}, content_weight={es['content_weight_total']} "
          f"(hoch={es['high_severity_total']}), mean/day={es['mean_content_per_day']}")
    print(f"  by code: {es['by_code']}")
    print(f"  acceptance: {acc['verdict']} ({'; '.join(acc['reasons'])})")
    bp = r.get('breakpoint') or {}
    if bp.get('breaks_at_day') is not None:
        print(f"  breakpoint: Qualität bricht ab Tag {bp['breaks_at_day']} ein "
              f"(invalid={bp['first_invalid_day']}, content>{r['error_score']['thresholds']['max_content_per_day']}={bp['first_content_exceed_day']}, identisch={bp['first_identical_day']})")
    else:
        print("  breakpoint: über den ganzen Lauf stabil")


def main() -> None:
    parser = argparse.ArgumentParser(description='Evaluate a generated run.')
    parser.add_argument('--run', required=True, help='Run name under outputs/.')
    parser.add_argument('--data-dir', type=str, default=None,
                        help='Constellation data dir for window/rooms/residents (default: config data_dir).')
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    files = config['files']
    data_dir = Path(args.data_dir) if args.data_dir else root / config['paths']['data_dir']
    if not data_dir.is_absolute():
        data_dir = root / data_dir

    devices = read_json(data_dir / files['devices'])
    residents = read_text(data_dir / files['residents'])
    rooms = read_text(data_dir / files['rooms'])
    timeframe = read_text(data_dir / files['timeframe'])
    resident_names = extract_resident_names(residents)
    window = parse_window(timeframe)
    access = build_access(rooms, residents, resident_names)
    thresholds = config.get('acceptance')

    run_dir = root / config['paths']['outputs_dir'] / args.run
    if not run_dir.exists():
        raise SystemExit(f'Run not found: {run_dir}')

    report = evaluate_run(run_dir, devices, window=window, access=access,
                          resident_names=resident_names, thresholds=thresholds)
    write_json(run_dir / 'metrics.json', report)
    _print_summary(report)
    print(f'\nMetrics written to: {run_dir / "metrics.json"}')


if __name__ == '__main__':
    main()
