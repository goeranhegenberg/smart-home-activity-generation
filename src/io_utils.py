from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding='utf-8').strip()


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_config(root: str | Path) -> dict:
    """Load the repo's config.json (single place for the entry-point preamble)."""
    return read_json(Path(root) / 'config.json')


def unwrap_actions(data: Any) -> Any:
    """Unwrap the structured-output form {"actions": [...]}; accept a bare list too."""
    return data['actions'] if isinstance(data, dict) and 'actions' in data else data


_DAY_NUM_RE = re.compile(r'(\d+)')


def day_number(name: str) -> int:
    m = _DAY_NUM_RE.search(name)
    return int(m.group(1)) if m else 0


def iter_day_dirs(run_dir: Path) -> list[Path]:
    """The run's day_NN directories (pipeline naming convention), in day order."""
    return sorted((d for d in run_dir.glob('day_*') if d.is_dir()),
                  key=lambda p: day_number(p.name))


def write_text(path: str | Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
