from __future__ import annotations

from pathlib import Path


def load_prompt(path: str | Path) -> str:
    return Path(path).read_text(encoding='utf-8')


def fill_template(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace('{{' + key + '}}', value)
    return result
