from __future__ import annotations

import argparse
import json
from pathlib import Path

from .client import build_client
from .pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description='Persona TTDAS pipeline')
    parser.add_argument('--days', type=int, default=1, help='Number of consecutive days to simulate over the fixed time window.')
    parser.add_argument('--run-name', type=str, default=None, help='Subfolder under outputs/ for this run. Defaults to run_{days}d.')
    parser.add_argument('--data-dir', type=str, default=None, help='Override the data directory (for different constellations).')
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    client = build_client()
    run_name = args.run_name or f'run_{args.days}d'
    run_pipeline(
        client=client,
        project_root=root,
        config=config,
        days=args.days,
        run_name=run_name,
        data_dir=args.data_dir,
    )
    print(f'Done. Outputs written to: {root / config["paths"]["outputs_dir"] / run_name}')
