"""Error taxonomy and weighted scoring (Fehlerbepunktung).

Splits the defined error catalog into two tiers (paper, Tab. "Zweistufiger
Fehlerkatalog"):

* **formal** -- hard constraints that must not occur. Detected by the validator
  and driven to zero by the Stage-3 self-repair loop. Acceptance fails if any
  remain.
* **content** (semantic) -- weighted by severity (``hoch`` = 3, ``mittel`` = 2).
  The deterministic checks (state accumulation, missing variation) feed the
  weighted score and the PASS/WARN/FAIL verdict. The LLM-as-judge categories
  (environment/context inconsistency, routine drift) share the same taxonomy
  but are reported as a SEPARATE, uncalibrated layer and are deliberately NOT
  folded into the score/verdict (see evaluate.py's ``judge_layer``).

``summarize_errors`` aggregates a flat list of error records into per-day and
per-run scores plus a PASS/WARN/FAIL acceptance verdict.
"""
from __future__ import annotations

SEVERITY_WEIGHT = {'hoch': 3, 'mittel': 2}

# code -> (severity, German label). severity 'formal' = hard, must be 0.
CODES: dict[str, tuple[str, str]] = {
    # --- formal (must not occur) ---
    'INVALID_JSON': ('formal', 'Ungültiges JSON'),
    'NOT_LIST': ('formal', 'Output ist kein JSON-Array'),
    'NOT_OBJECT': ('formal', 'Aktion ist kein Objekt'),
    'MISSING_FIELD': ('formal', 'Pflichtfeld fehlt'),
    'RESIDENT_TYPE': ('formal', 'Bewohner ist kein String'),
    'RESIDENT_NONSINGULAR': ('formal', 'Nicht-singulärer Bewohner'),
    'RESIDENT_UNKNOWN': ('formal', 'Unbekannter Bewohner'),
    'TIMESTAMP_FORMAT': ('formal', 'Zeitstempel-Format ungültig'),
    'TIMESTAMP_NONMONOTONIC': ('formal', 'Zeitstempel nicht monoton'),
    'TIMESTAMP_OUT_OF_WINDOW': ('formal', 'Zeitstempel außerhalb Zeitfenster'),
    'UNKNOWN_DEVICE': ('formal', 'Unbekanntes Gerät'),
    'INVALID_ACTION': ('formal', 'Unerlaubte Aktion'),
    'INVALID_VALUE': ('formal', 'Wertebereich verletzt'),
    'NON_ATOMIC': ('formal', 'Nicht-atomare Aktion'),
    'PERSONA_INACCESSIBLE': ('formal', 'Persona-Inkonsistenz (Gerät nicht zugänglich)'),
    'CONTINUITY': ('formal', 'Kontinuitäts-Event (unveränderter Zustand)'),
    'EMPTY_DAY': ('formal', 'Leerer Tag (keine Aktionen erzeugt)'),
    'EMPTY_RUN': ('formal', 'Leerer Lauf (keine auswertbaren Tage)'),
    # --- content (weighted, in den Verdikten) ---
    'STATE_ACCUMULATION': ('mittel', 'Zustands-Akkumulation'),
    'MISSING_VARIATION': ('mittel', 'Fehlende Variation'),
    # --- content, Judge-Ebene (separat berichtet, NICHT in den Verdikten) ---
    'ENV_INCONSISTENT': ('hoch', 'Umwelt-/Kontext-Inkonsistenz (LLM-Judge)'),
    'ROUTINE_DRIFT': ('mittel', 'Routine-Drift ohne Begründung (LLM-Judge)'),
}

DEFAULT_THRESHOLDS = {
    'max_formal': 0,                 # acceptance A1: no formal errors at all
    'max_high': 0,                   # no high-severity content error tolerated
    'max_content_per_day': 2,        # acute: at most one 'mittel' on the worst single day
    'max_mean_content_per_day': 1.0,  # sustained: mean content weight per day over the run
}


def severity_of(code: str) -> str:
    return CODES.get(code, ('mittel', code))[0]


def make_error(code: str, detail: str = '', day: int | None = None, weight: int | None = None) -> dict:
    """Build a normalized error record.

    ``weight`` overrides the default severity weight for content errors (e.g. to
    let state-accumulation scale with streak length); formal errors stay weight 0.
    """
    severity, label = CODES.get(code, ('mittel', code))
    base = 0 if severity == 'formal' else SEVERITY_WEIGHT.get(severity, 1)
    return {
        'code': code,
        'severity': severity,
        'label': label,
        'weight': base if weight is None else weight,
        'day': day,
        'detail': detail,
    }


def summarize_errors(errors: list[dict], n_days: int, thresholds: dict | None = None) -> dict:
    """Aggregate error records into a weighted score and acceptance verdict."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    by_code: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    per_day: dict[int, dict[str, int]] = {}
    formal_total = 0
    high_total = 0
    content_weight = 0

    for e in errors:
        code = e.get('code', '')
        sev = e.get('severity') or severity_of(code)
        day = e.get('day')
        by_code[code] = by_code.get(code, 0) + 1
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if day is not None:
            slot = per_day.setdefault(day, {'formal': 0, 'content_weight': 0})
        else:
            slot = None
        if sev == 'formal':
            formal_total += 1
            if slot is not None:
                slot['formal'] += 1
        else:
            w = e.get('weight') or SEVERITY_WEIGHT.get(sev, 1)
            content_weight += w
            if sev == 'hoch':
                high_total += 1
            if slot is not None:
                slot['content_weight'] += w

    max_content_day = max((d['content_weight'] for d in per_day.values()), default=0)
    mean_content = content_weight / n_days if n_days else 0.0

    formal_ok = formal_total <= th['max_formal']
    high_ok = high_total <= th['max_high']
    per_day_ok = max_content_day <= th['max_content_per_day']
    mean_ok = mean_content <= th['max_mean_content_per_day']

    reasons: list[str] = []
    if not formal_ok:
        reasons.append(f'{formal_total} formale Fehler (Schranke {th["max_formal"]})')
    if not high_ok:
        reasons.append(f'{high_total} schwere (hoch) Inhaltsfehler (Schranke {th["max_high"]})')
    if not per_day_ok:
        reasons.append(
            f'max. Inhalts-Score/Tag {max_content_day} (Schranke {th["max_content_per_day"]})'
        )
    if not mean_ok:
        reasons.append(
            f'mittl. Inhalts-Score/Tag {round(mean_content, 2)} (Schranke {th["max_mean_content_per_day"]})'
        )

    if not formal_ok:
        verdict = 'FAIL'
    elif not (high_ok and per_day_ok and mean_ok):
        verdict = 'WARN'
    else:
        verdict = 'PASS'
        reasons.append('alle Schranken eingehalten')

    return {
        'weights': SEVERITY_WEIGHT,
        'thresholds': th,
        'formal_total': formal_total,
        'content_weight_total': content_weight,
        'high_severity_total': high_total,
        'mean_content_per_day': round(content_weight / n_days, 2) if n_days else 0.0,
        'max_content_per_day': max_content_day,
        'by_code': dict(sorted(by_code.items())),
        'by_severity': by_severity,
        'per_day': {str(k): v for k, v in sorted(per_day.items())},
        'acceptance': {
            'formal_ok': formal_ok,
            'high_ok': high_ok,
            'per_day_ok': per_day_ok,
            'mean_ok': mean_ok,
            'verdict': verdict,
            'reasons': reasons,
        },
        'errors': errors,
    }
