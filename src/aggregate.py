"""Aggregate a run matrix into per-cell tables with K-repeat spread.

Reads every ``outputs/<subdir>/*/metrics.json`` produced by ``run_matrix.py``,
groups the cells by (constellation, horizon), and reports, across the K repeats
of each cell: validity, formal-error rate, weighted content score per day,
day-to-day variation (Jaccard), actions/day, the PASS/WARN/FAIL verdict mix,
and the quality breakpoint. It also averages the per-day quality curve over the
repeats (drift over days).

Writes ``aggregate.json`` (machine-readable), ``aggregate.csv`` (one row per
cell), ``SUMMARY.md`` (Markdown tables) and -- when judge layers are present --
``JUDGE_SUMMARY.md`` (the separate LLM-judge layer: env/drift rates by day
number; deliberately NOT part of the rule-based scores/verdicts).

Usage:
    python -m src.aggregate --subdir matrix
"""
from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

from .io_utils import load_config, read_json, write_json, write_text


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 3) if xs else None


def _stdev(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.pstdev(xs), 3) if len(xs) > 1 else 0.0


def _rng(xs):
    xs = [x for x in xs if x is not None]
    return (min(xs), max(xs)) if xs else (None, None)


def collect(matrix_dir: Path) -> list[dict]:
    """One record per cell run (metrics.json with a matrix tag)."""
    records = []
    for mpath in sorted(matrix_dir.glob('*/metrics.json')):
        report = read_json(mpath)
        m = report.get('matrix')
        if not m:
            continue  # not a matrix-tagged run
        es = report.get('error_score', {})
        records.append({
            'constellation': m['constellation'],
            'horizon': m['horizon_days'],
            'pct_valid': report.get('validity', {}).get('pct_valid'),
            'formal_total': es.get('formal_total'),
            'high_total': es.get('high_severity_total'),
            'mean_content_per_day': es.get('mean_content_per_day'),
            'verdict': es.get('acceptance', {}).get('verdict'),
            'mean_jaccard': report.get('variation', {}).get('mean_jaccard'),
            'actions_per_day': report.get('actions_per_day', {}).get('mean'),
            'coverage': report.get('realism_rulebased', {}).get('device_action_coverage'),
            'breaks_at_day': (report.get('breakpoint') or {}).get('breaks_at_day'),
            'quality_curve': report.get('quality_curve', []),
            'judge': report.get('judge_layer'),
        })
    return records


def group_key(r: dict) -> tuple:
    return (r['constellation'], r['horizon'])


def aggregate(records: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in records:
        groups.setdefault(group_key(r), []).append(r)

    out = []
    for key, rs in sorted(groups.items()):
        const, horizon = key
        verdicts = [r['verdict'] for r in rs]
        breaks = [r['breaks_at_day'] for r in rs if r['breaks_at_day'] is not None]

        # average per-day quality curve across repeats
        per_day: dict[int, dict[str, list]] = {}
        for r in rs:
            for q in r['quality_curve']:
                d = per_day.setdefault(q['day_num'], {'content': [], 'formal': [], 'actions': [], 'jacc': []})
                d['content'].append(q.get('content_weight'))
                d['formal'].append(q.get('formal_errors'))
                d['actions'].append(q.get('n_actions'))
                d['jacc'].append(q.get('jaccard_to_prev'))
        drift_curve = [{
            'day_num': dn,
            'mean_content_weight': _mean(v['content']),
            'mean_formal_errors': _mean(v['formal']),
            'mean_actions': _mean(v['actions']),
            'mean_jaccard_to_prev': _mean(v['jacc']),
        } for dn, v in sorted(per_day.items())]

        pv_min, pv_max = _rng([r['pct_valid'] for r in rs])
        out.append({
            'constellation': const, 'horizon': horizon,
            'n_repeats': len(rs),
            'pct_valid_mean': _mean([r['pct_valid'] for r in rs]),
            'pct_valid_stdev': _stdev([r['pct_valid'] for r in rs]),
            'pct_valid_min': pv_min, 'pct_valid_max': pv_max,
            'formal_total_mean': _mean([r['formal_total'] for r in rs]),
            'high_total_mean': _mean([r['high_total'] for r in rs]),
            'content_per_day_mean': _mean([r['mean_content_per_day'] for r in rs]),
            'content_per_day_stdev': _stdev([r['mean_content_per_day'] for r in rs]),
            'mean_jaccard': _mean([r['mean_jaccard'] for r in rs]),
            'actions_per_day': _mean([r['actions_per_day'] for r in rs]),
            'coverage': _mean([r['coverage'] for r in rs]),
            'verdict_pass': verdicts.count('PASS'),
            'verdict_warn': verdicts.count('WARN'),
            'verdict_fail': verdicts.count('FAIL'),
            'breaks_runs': len(breaks),
            'breaks_earliest': min(breaks) if breaks else None,
            'drift_curve': drift_curve,
        })
    return out


def _fmt(x, nd=1):
    if x is None:
        return '-'
    if isinstance(x, float):
        return f'{x:.{nd}f}'
    return str(x)


def _verdict_cell(g):
    return f"{g['verdict_pass']}P/{g['verdict_warn']}W/{g['verdict_fail']}F"


def render_markdown(agg: list[dict]) -> str:
    lines = ['# Matrix-Auswertung (Aggregat über K Wiederholungen)', '']

    def table(rows, header, fmt_row):
        out = ['| ' + ' | '.join(header) + ' |',
               '|' + '|'.join(['---'] * len(header)) + '|']
        out += ['| ' + ' | '.join(fmt_row(g)) + ' |' for g in rows]
        return out

    main = [g for g in agg if g['constellation'] != 'fullday']
    if main:
        lines += ['## Haupt-Matrix (Champion) - Konstellation x Zeithorizont', '']
        lines += table(
            sorted(main, key=lambda g: (g['constellation'], g['horizon'])),
            ['Konst.', 'Tage', 'K', 'valide% (min-max)', 'formal', 'Inhalt/Tag', 'Jaccard',
             'Akt./Tag', 'Verdict', 'Bruch@'],
            lambda g: [g['constellation'], str(g['horizon']), str(g['n_repeats']),
                       f"{_fmt(g['pct_valid_mean'])} ({_fmt(g['pct_valid_min'])}-{_fmt(g['pct_valid_max'])})",
                       _fmt(g['formal_total_mean'], 2), _fmt(g['content_per_day_mean'], 2),
                       _fmt(g['mean_jaccard'], 2),
                       _fmt(g['actions_per_day'], 1), _verdict_cell(g),
                       _fmt(g['breaks_earliest'], 0)])
        lines += ['']

    fullday = [g for g in agg if g['constellation'] == 'fullday']
    if fullday:
        lines += ['## Ganztags-Flagship (00:00-24:00)', '']
        lines += table(
            sorted(fullday, key=lambda g: g['horizon']),
            ['Tage', 'K', 'valide% (min-max)', 'formal', 'Inhalt/Tag', 'Jaccard', 'Akt./Tag', 'Verdict'],
            lambda g: [str(g['horizon']), str(g['n_repeats']),
                       f"{_fmt(g['pct_valid_mean'])} ({_fmt(g['pct_valid_min'])}-{_fmt(g['pct_valid_max'])})",
                       _fmt(g['formal_total_mean'], 2), _fmt(g['content_per_day_mean'], 2),
                       _fmt(g['mean_jaccard'], 2),
                       _fmt(g['actions_per_day'], 1), _verdict_cell(g)])
        lines += ['']

    # Drift curves (D3) for the multi-day cells
    drift_cells = [g for g in agg if g['horizon'] >= 3]
    if drift_cells:
        lines += ['## Drift-Kurven (D3): mittl. Inhalts-Score + formale Fehler pro Tag', '']
        for g in sorted(drift_cells, key=lambda g: (g['constellation'], g['horizon'])):
            series = '; '.join(
                f"T{c['day_num']}={_fmt(c['mean_content_weight'],1)}"
                f"(f{_fmt(c['mean_formal_errors'],1)})" for c in g['drift_curve'])
            lines.append(f"- **{g['constellation']} {g['horizon']}d** (K={g['n_repeats']}): {series}")
        lines += ['']
    return '\n'.join(lines)


def render_judge_markdown(records: list[dict]) -> str | None:
    """Render the separate LLM-judge layer across all judged runs.

    Mirrors the paper's judge table: per day number, how many judged days were
    flagged env-inconsistent / routine-drift. These findings are deliberately
    NOT part of the rule-based scores or PASS/WARN/FAIL verdicts.
    """
    judged = [r for r in records if r.get('judge')]
    if not judged:
        return None

    total = env_bad = drift_bad = unparseable = 0
    by_day: dict[int, dict[str, int]] = {}
    for r in judged:
        jl = r['judge']
        total += jl.get('days_judged', 0)
        env_bad += jl.get('env_inconsistent_days', 0)
        drift_bad += jl.get('routine_drift_days', 0)
        unparseable += jl.get('unparseable_days', 0)
        for e in jl.get('per_day', []):
            slot = by_day.setdefault(e.get('day') or 0, {'n': 0, 'env': 0, 'drift': 0})
            slot['n'] += 1
            if e.get('env_consistent') is False:
                slot['env'] += 1
            if e.get('routine_drift') is True:
                slot['drift'] += 1

    model = next((r['judge'].get('judge_model') for r in judged if r['judge'].get('judge_model')), '?')
    votes = next((r['judge'].get('votes_per_day') for r in judged if r['judge'].get('votes_per_day')), '?')

    def pct(part, whole):
        return f'{part} ({100 * part / whole:.1f}%)' if whole else '0'

    lines = [
        '# LLM-Judge-Auswertung (separate semantische Ebene)',
        '',
        f'Cross-family Judge `{model}` (Temperatur 0, JSON-Schema, {votes} Votum/Tag) '
        f'über {len(judged)} Läufe. Prüft, was die deterministischen Checks nicht können: '
        'Umwelt-/Kontext-Inkonsistenz (Widerspruch zum Stage-1-Fixkontext) und unmotivierten '
        'Routine-Drift (Tag-zu-Tag). Diese Befunde sind bewusst NICHT in die regelbasierten '
        'Score-Tabellen und Verdikte eingerechnet (unkalibriert, Einzelvotum).',
        '',
        f'- Beurteilte Tage gesamt: **{total}**',
        f'- Umwelt-/Kontext-konsistent: **{total - env_bad} ({100 * (total - env_bad) / total:.1f}%)**' if total else '- (keine Tage)',
        f'- Umwelt-/Kontext-INKONSISTENT: **{pct(env_bad, total)}**',
        f'- Routine-Drift geflaggt: **{pct(drift_bad, total)}**',
    ]
    if unparseable:
        lines.append(f'- Nicht auswertbare Judge-Antworten: {unparseable}')
    lines += ['', '## Nach Tag-Nummer (Horizont-Drift)', '',
              '| Tag | beurteilt | env-inkons. | Routine-Drift |', '|---|---|---|---|']
    for dn, slot in sorted(by_day.items()):
        lines.append(f"| T{dn} | {slot['n']} | {pct(slot['env'], slot['n'])} "
                     f"| {pct(slot['drift'], slot['n'])} |")

    fullday = [r for r in judged if r['constellation'] == 'fullday']
    if fullday:
        fd_total = sum(r['judge'].get('days_judged', 0) for r in fullday)
        fd_env = sum(r['judge'].get('env_inconsistent_days', 0) for r in fullday)
        fd_drift = sum(r['judge'].get('routine_drift_days', 0) for r in fullday)
        lines += ['', '## Ganztags-Flagship',
                  '',
                  f'- Beurteilte Tage: {fd_total}; env-konsistent: '
                  f'{fd_total - fd_env}/{fd_total} ({100 * (fd_total - fd_env) / fd_total:.0f}%); '
                  f'Routine-Drift: {fd_drift}.']

    lines += ['', '## Methodische Vorbehalte', '',
              '- Einzelvotum je Tag (kein Mehrheitsentscheid bei votes=1).',
              '- Nicht gegen eine menschliche Stichprobe kalibriert.',
              '- Teils streng (minutengenaue Zeit-Abweichungen werden geflaggt).', '']
    return '\n'.join(lines)


CSV_FIELDS = ['constellation', 'horizon', 'n_repeats',
              'pct_valid_mean', 'pct_valid_min', 'pct_valid_max', 'formal_total_mean',
              'high_total_mean', 'content_per_day_mean', 'content_per_day_stdev',
              'mean_jaccard', 'actions_per_day', 'coverage',
              'verdict_pass', 'verdict_warn', 'verdict_fail',
              'breaks_runs', 'breaks_earliest']


def main() -> None:
    ap = argparse.ArgumentParser(description='Aggregate a run matrix.')
    ap.add_argument('--subdir', default='matrix', help='Output subfolder under outputs/.')
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = load_config(root)
    matrix_dir = root / config['paths']['outputs_dir'] / args.subdir
    if not matrix_dir.exists():
        raise SystemExit(f'Matrix dir not found: {matrix_dir}')

    records = collect(matrix_dir)
    if not records:
        raise SystemExit(f'No matrix-tagged metrics.json found under {matrix_dir}')
    agg = aggregate(records)

    write_json(matrix_dir / 'aggregate.json', {'n_cells': len(agg), 'n_runs': len(records), 'cells': agg})
    with open(matrix_dir / 'aggregate.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction='ignore')
        w.writeheader()
        for g in agg:
            w.writerow(g)
    md = render_markdown(agg)
    write_text(matrix_dir / 'SUMMARY.md', md)
    print(f'{len(records)} runs -> {len(agg)} cells.')
    print(f'Wrote: {matrix_dir / "aggregate.json"}')
    print(f'       {matrix_dir / "aggregate.csv"}')
    print(f'       {matrix_dir / "SUMMARY.md"}')

    judge_md = render_judge_markdown(records)
    if judge_md:
        write_text(matrix_dir / 'JUDGE_SUMMARY.md', judge_md)
        print(f'       {matrix_dir / "JUDGE_SUMMARY.md"}')

    print()
    print(md)


if __name__ == '__main__':
    main()
