"""Evaluation matrix runner: C constellations x H horizons x K repeats.

This automates the experiment grid the paper reports. Each cell runs the
four-stage pipeline (src/pipeline.py), then the deterministic evaluation
(src/evaluate.py) and -- optionally -- the LLM-as-judge (src/judge.py), and writes
a metrics.json tagged with its matrix coordinates. src/aggregate.py turns the cell
metrics into per-(constellation, horizon) tables with K-repeat spread.

Axes
----
* constellations: family (data/), single (data_k2/), wg (data_k3/) -- three
                fundamentally different morning households -- plus fullday
                (data_day/, 00:00-24:00, 10 devices) as the full-day flagship.
* horizons    : 1, 3, 7 days (24 h / 3 days / 1 week), chained via Stage 4.
* repeats     : K independent samples per cell (provider sampling temperature),
                so the aggregate can report spread, not just a point estimate.

Runs are idempotent: a cell whose metrics.json already exists is skipped unless
--force is given, so a long matrix can be resumed after an interruption.

Usage
-----
    python run_matrix.py --plan smoke                 # 1 cheap end-to-end cell
    python run_matrix.py --plan full --repeats 3 --dry-run   # show the grid + cost
    python run_matrix.py --plan full --repeats 3 --judge --judge-votes 1
    python run_matrix.py --plan champion --repeats 3  # morning C x H matrix only
"""
from __future__ import annotations

import argparse
import time
import traceback
from pathlib import Path

from src.client import USAGE, build_client, reset_usage
from src.context import load_context
from src.evaluate import evaluate_run
from src.io_utils import load_config, write_json
from src.judge import judge_run
from src.pipeline import run_pipeline

# label -> data dir name
CONSTELLATIONS = {
    'family': 'data',
    'single': 'data_k2',
    'wg': 'data_k3',
    'fullday': 'data_day',
}


def score_run(run_dir: Path, const: dict, spec: dict, judged: bool, thresholds: dict | None) -> dict:
    """Evaluate a generated cell and write its matrix-tagged metrics.json."""
    report = evaluate_run(
        run_dir, const['devices'], window=const['window'], access=const['access'],
        resident_names=const['resident_names'], thresholds=thresholds)
    report['matrix'] = {
        'constellation': spec['constellation'], 'horizon_days': spec['horizon'],
        'repeat': spec['repeat'], 'judged': judged,
    }
    write_json(run_dir / 'metrics.json', report)
    return report


def make_blocks(plan: str, k: int) -> list[dict]:
    """A plan is a list of blocks; each block is a fully-crossed sub-grid."""
    main = {'constellations': ['family', 'single', 'wg'], 'horizons': [1, 3, 7],
            'repeats': k}
    fullday = {'constellations': ['fullday'], 'horizons': [7], 'repeats': k}
    plans = {
        'smoke': [{'constellations': ['family'], 'horizons': [1], 'repeats': 1}],
        'champion': [main],
        'fullday': [fullday],
        'full': [main, fullday],
    }
    if plan not in plans:
        raise SystemExit(f'Unknown plan {plan!r}. Choose from: {", ".join(plans)}')
    return plans[plan]


def expand(blocks: list[dict]) -> list[dict]:
    """Expand blocks into a flat list of run specs (block grids are disjoint)."""
    runs: list[dict] = []
    for b in blocks:
        for const in b['constellations']:
            for h in b['horizons']:
                for r in range(1, b['repeats'] + 1):
                    # 'champ_' prefix kept for continuity with the existing run dirs.
                    runs.append({'name': f'champ_{const}_h{h}_r{r}',
                                 'constellation': const, 'horizon': h, 'repeat': r})
    return runs


def estimate_calls(run: dict, judge: bool, judge_votes: int) -> int:
    days = run['horizon']
    gen = 1 + days * 3.5  # stage1 once + (stage2 + stage3 + ~0.5 repair + stage4) per day
    jud = judge_votes * days if judge else 0
    return int(round(gen + jud))


def main() -> None:
    ap = argparse.ArgumentParser(description='Run the evaluation matrix.')
    ap.add_argument('--plan', default='smoke',
                    help='smoke | champion | fullday | full')
    ap.add_argument('--repeats', type=int, default=3, help='K repeats per cell (default 3).')
    ap.add_argument('--judge', action='store_true',
                    help='Also run the LLM-as-judge (env/drift) per run (extra cost).')
    ap.add_argument('--judge-only', action='store_true',
                    help='Skip generation entirely; only run the judge + re-evaluate over '
                         'cells that already have a metrics.json (cheap, non-destructive). '
                         'Idempotent on judge.json unless --force.')
    ap.add_argument('--judge-votes', type=int, default=1,
                    help='Judge votes per day when --judge / --judge-only (default 1).')
    ap.add_argument('--subdir', default='matrix', help='Output subfolder under outputs/.')
    ap.add_argument('--force', action='store_true', help='Re-run cells even if metrics.json exists.')
    ap.add_argument('--dry-run', action='store_true', help='Print the grid + cost estimate, no API calls.')
    ap.add_argument('--only', default=None,
                    help='Comma-separated substrings; keep only runs whose name matches one.')
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    config = load_config(root)
    files = config['files']
    model = config['model']
    judge_model = config.get('judge_model')
    thresholds = config.get('acceptance')
    out_base = root / config['paths']['outputs_dir'] / args.subdir

    blocks = make_blocks(args.plan, args.repeats)
    runs = expand(blocks)
    if args.only:
        keys = [s.strip() for s in args.only.split(',') if s.strip()]
        runs = [r for r in runs if any(k in r['name'] for k in keys)]

    if args.judge_only and not judge_model:
        raise SystemExit('--judge-only needs a judge_model in config.json.')
    if args.judge_only:
        jcalls = sum(args.judge_votes * r['horizon'] for r in runs)
        print(f'Plan {args.plan!r} (JUDGE-ONLY): {len(runs)} existing cells, '
              f'~{jcalls} judge calls (votes={args.judge_votes}, model={judge_model}); '
              f'no generation.')
    else:
        total_calls = sum(estimate_calls(r, args.judge, args.judge_votes) for r in runs)
        print(f'Plan {args.plan!r}: {len(runs)} cells, ~{total_calls} model calls '
              f'(judge={"on" if args.judge else "off"}).')
    by_h: dict[int, int] = {}
    for r in runs:
        by_h[r['horizon']] = by_h.get(r['horizon'], 0) + 1
    print('  cells by horizon (days): ' + ', '.join(f'{h}d={n}' for h, n in sorted(by_h.items())))
    print('  output dir: ' + str(out_base))
    if args.dry_run:
        for r in runs:
            print(f"  - {r['name']:<24} {r['constellation']} h{r['horizon']} "
                  f"(~{estimate_calls(r, args.judge, args.judge_votes)} calls)")
        print('\nDry run: nothing executed. Drop --dry-run to launch.')
        return

    client = build_client()
    reset_usage()
    const_cache: dict[str, dict] = {}
    manifest: list[dict] = []
    t0 = time.time()
    done = 0
    failed = 0

    for i, r in enumerate(runs, 1):
        run_name = f"{args.subdir}/{r['name']}"
        run_dir = out_base / r['name']
        metrics_path = run_dir / 'metrics.json'
        tag = f"[{i}/{len(runs)}] {r['name']}"

        if args.judge_only:
            # Judge + re-evaluate an already-generated cell; never regenerate.
            if not metrics_path.exists():
                print(f'{tag}: skip (not generated yet)')
                continue
            judge_path = run_dir / 'judge.json'
            if judge_path.exists() and not args.force:
                print(f'{tag}: skip (judge.json exists)')
                done += 1
                continue
            const = const_cache.setdefault(
                r['constellation'], load_context(root / CONSTELLATIONS[r['constellation']], files))
            rt0 = time.time()
            try:
                judge_result = judge_run(run_dir, const['data_dir'], files, judge_model,
                                         votes=args.judge_votes, client=client)
                write_json(judge_path, judge_result)
                report = score_run(run_dir, const, r, judged=True, thresholds=thresholds)
                acc = report['error_score']['acceptance']
                print(f"{tag}: judged ({time.time() - rt0:.0f}s) verdict {acc['verdict']}")
                done += 1
            except Exception as exc:
                failed += 1
                print(f'{tag}: ERROR {type(exc).__name__}: {exc}')
                traceback.print_exc()
            continue

        if metrics_path.exists() and not args.force:
            print(f'{tag}: skip (metrics.json exists)')
            done += 1
            continue

        const = const_cache.setdefault(
            r['constellation'], load_context(root / CONSTELLATIONS[r['constellation']], files))

        rt0 = time.time()
        status = 'ok'
        err_msg = ''
        try:
            run_pipeline(
                client=client, project_root=root, config=config,
                days=r['horizon'], run_name=run_name,
                data_dir=const['data_dir'],
            )
            if args.judge and judge_model:
                judge_result = judge_run(run_dir, const['data_dir'], files, judge_model,
                                         votes=args.judge_votes, client=client)
                write_json(run_dir / 'judge.json', judge_result)

            report = score_run(run_dir, const, r, judged=bool(args.judge), thresholds=thresholds)
            acc = report['error_score']['acceptance']
            v = report['validity']
            print(f"{tag}: {status} ({time.time() - rt0:.0f}s) "
                  f"valid {v['days_passed']}/{report['n_days']}, verdict {acc['verdict']}, "
                  f"breaks_at={report['breakpoint']['breaks_at_day']}")
            done += 1
        except Exception as exc:  # keep the matrix going; record the failure
            status = 'error'
            err_msg = f'{type(exc).__name__}: {exc}'
            failed += 1
            print(f'{tag}: ERROR {err_msg}')
            traceback.print_exc()

        manifest.append({
            'name': r['name'], 'run_name': run_name,
            **{k: r[k] for k in ('constellation', 'horizon', 'repeat')},
            'status': status, 'error': err_msg, 'seconds': round(time.time() - rt0, 1),
        })
        write_json(out_base / 'manifest.json', {
            'plan': args.plan, 'judge': args.judge, 'judge_votes': args.judge_votes,
            'total': len(runs), 'done': done, 'failed': failed,
            'elapsed_min': round((time.time() - t0) / 60, 1), 'runs': manifest,
        })

    pt, ct = USAGE['prompt_tokens'], USAGE['cached_tokens']
    hit = (100 * ct / pt) if pt else 0.0
    print(f'\nMatrix finished: {done} ok, {failed} failed, '
          f'{(time.time() - t0) / 60:.1f} min. Manifest: {out_base / "manifest.json"}')
    print(f'Usage: {USAGE["calls"]} model calls, {pt:,} prompt tokens '
          f'({ct:,} cached = {hit:.0f}% cache hit), {USAGE["completion_tokens"]:,} output tokens, '
          f'OpenRouter cost ${USAGE["cost"]:.2f}')
    print('Aggregate with:  python -m src.aggregate --subdir ' + args.subdir)


if __name__ == '__main__':
    main()
