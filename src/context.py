"""Shared constellation context: one place for the load-and-derive recipe.

Every consumer of a constellation (pipeline runner, evaluator, judge, exporter)
needs the same bundle -- device schema, evaluation window, accessibility map and
resident names, all derived from the constellation's data directory. Loading it
here keeps the derivation identical across the CLIs and the matrix runner.
"""
from __future__ import annotations

from pathlib import Path

from .io_utils import read_json, read_text
from .rooms import build_access
from .validator import extract_resident_names, parse_window


def resolve_data_dir(root: Path, config: dict, override: str | None) -> Path:
    """Resolve a --data-dir override (or the config default) against the repo root."""
    data_dir = Path(override) if override else root / config['paths']['data_dir']
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    return data_dir


def load_context(data_dir: Path, files: dict) -> dict:
    """Read a constellation's inputs and derive the evaluation context."""
    devices = read_json(data_dir / files['devices'])
    residents = read_text(data_dir / files['residents'])
    rooms = read_text(data_dir / files['rooms'])
    timeframe = read_text(data_dir / files['timeframe'])
    resident_names = extract_resident_names(residents)
    return {
        'data_dir': data_dir,
        'devices': devices,
        'window': parse_window(timeframe),
        'access': build_access(rooms, residents, resident_names),
        'resident_names': resident_names,
    }
