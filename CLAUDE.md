# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project overview

Prompt artefact + tooling for the "Persona & TTDAS" project (Praktikum IT-Sicherheit,
Uni Leipzig, track Prompting/Personas). A **four-stage** LLM pipeline generates
schema-faithful smart-home activity logs over 24 h to 1 week, with a deterministic
evaluation harness and a JSON→TTDAS exporter. Framing: Design Science Research.

1. **Stage 1** — persona memory cards from residents / environment / device schema / rooms
2. **Stage 2** — time-windowed narrative with exact timestamps and explicit device state
3. **Stage 3** — structured-output extraction to an action JSON, validated, with a
   self-repair loop (`config.max_repairs`, default 1) that re-prompts with the validator's messages
4. **Stage 4** — memory update: rewrite cards from observed actions, carry the device
   world-state and active multi-day events into the next day

Multi-day horizons come from chaining Stage 4 (`main.py --days N`). Stage 4 **is
implemented** (`src/pipeline.py`, `prompts/stage4_*.txt`).

## Running

Requires `OPENROUTER_API_KEY` in `.env` (the client defaults to OpenRouter; falls
back to `OPENAI_API_KEY` / `OPENAI_BASE_URL`).

```bash
pip install -r requirements.txt
python main.py --days 3 --run-name demo            # single pipeline run
python evaluate.py --run demo                       # deterministic eval + error score
python -m src.judge --run demo --votes 3            # LLM-as-judge (env + drift)
python -m src.ttdas_export --in <stage3_actions.json> --out <out.py>   # Aufgabe 3

# Evaluation matrix: constellation x horizon x K repeats
python run_matrix.py --plan full --repeats 3 --dry-run    # show the grid + cost, no API
python run_matrix.py --plan full --repeats 3 --judge --judge-votes 1
python run_matrix.py --plan full --judge-only --judge-votes 1  # judge + re-eval EXISTING cells only (no regen)
python -m src.aggregate --subdir matrix        # SUMMARY.md + JUDGE_SUMMARY.md
```

No test suite or linter is configured; `python -m py_compile src/*.py` is the quick check.

## Architecture

Linear pipeline in `src/pipeline.py::run_pipeline`. Each stage loads a
`stageN_system.txt` + `stageN_user.txt` pair from `prompts/`, fills `{{PLACEHOLDER}}`
tokens via `prompt_loader.fill_template`, and calls `client.call_model`, which uses
the **Chat Completions API** (`client.chat.completions.create`, OpenRouter-compatible)
— Stage 3 passes a strict `response_format` json_schema for structured output.

**Prompt caching.** The run-fixed context (residents, environment, device schema,
descriptions, rooms — `pipeline.build_shared_reference`) is sent as a cached leading
system block (`call_model(..., cache_prefix=...)`, Anthropic `cache_control`). It is
byte-identical across every stage and day, so Stage 1 writes it and all later calls
read it at ~0.1x. Because of this the fixed-data blocks were removed from the
`stageN_user.txt` templates (they now reference "the fixed reference context above")
— do NOT re-add `{{DEVICES}}`/`{{ROOMS}}`/etc. to the user prompts, or the context is
sent twice. `client.USAGE` accumulates prompt/cached/output tokens + cost per process;
`run_matrix.py` prints the cache-hit rate at the end.

- `src/validator.py` — `validate_actions` returns structured error records (code,
  severity, detail). Formal checks: JSON/array/empty/object/fields, unknown device,
  invalid action/value, resident singular+known, timestamp format/monotonicity/window,
  non-atomic, persona accessibility, continuity. Feeds the self-repair loop.
- `src/errors.py` — error taxonomy + `summarize_errors` (weighted Fehlerbepunktung,
  PASS/WARN/FAIL against `config.json` `acceptance`). Two tiers: formal (must be 0)
  vs. content (weighted hoch=3/mittel=2).
- `src/rooms.py` — parse `rooms.md` into a device→accessible-residents map (caregiver
  rule: a dependent's room stays accessible to all).
- `src/evaluate.py` — metrics (validity, drift/churn, card growth, variation Jaccard,
  coverage), weighted error score, per-day `quality_curve` (D3 drift over days) and
  `breakpoint` (D5: first day quality breaks).
- `src/judge.py` — LLM-as-judge for env/context + routine drift, different model
  family (`judge_model`), temperature 0, json_schema, k-of-n majority voting.
- **Judge as a separate layer.** `evaluate.py` reports `judge.json` findings as a
  `judge_layer` section that is deliberately NOT folded into `error_score` or the
  PASS/WARN/FAIL verdict (uncalibrated, single cross-family vote) — this mirrors the
  paper's error-catalog table. `src/aggregate.py` renders the layer into
  `outputs/matrix/JUDGE_SUMMARY.md` (env/drift rates by day number). Key judge
  finding: env-inconsistency is horizon-dependent and spikes at day 6 (model invents
  a "weekend" vs. the fixed schedule).
- `run_matrix.py` — runs the grid: constellations (family/single/wg/fullday) x
  horizons (1/3/7) x K repeats; pipeline → judge → evaluate per cell, writes a
  matrix-tagged `metrics.json` + `manifest.json`. Idempotent (skips existing cells),
  `--dry-run`, preset plans (smoke/champion/fullday/full). `--judge-only` skips
  generation and only runs the judge + re-evaluates cells that already have a
  metrics.json (cheap, non-destructive; idempotent on `judge.json` unless `--force`).
- `src/aggregate.py` — groups `outputs/<subdir>/*/metrics.json` by (constellation,
  horizon), aggregates across K (mean/stdev/range, verdict mix, drift curves), writes
  `aggregate.json`, `aggregate.csv`, `SUMMARY.md`, `JUDGE_SUMMARY.md`.
- `src/ttdas_export.py` + `ttdas.py` — Stage-3 JSON → executable TTDAS script.

## Config & conventions

- All paths/filenames go through `config.json` (`paths`, `files`, plus `model`,
  `judge_model`, `max_repairs`, `acceptance`). Adding an input file means adding both a
  `files` entry and a reader in `pipeline.py`.
- Device schema (`data/available-smart-devices.json`): `{"device": ...,
  "allowed_values": {action: [values]}}`. Each `allowed_values` key (`status`,
  `brightness`, `light_temp`) is a valid Stage-3 `action`; its list entries are the
  valid `action_value`s.
- Constellations: `data/` (family, morning), `data_k2/` (single), `data_k3/` (WG),
  `data_day/` (shift-work family, full-day 00:00-24:00, 10 devices). Use `--data-dir`
  to switch. `run_matrix.py` maps the labels family/single/wg/fullday to these dirs.
- Edit prompts in `prompts/`, not the Python, when tuning model behavior, and
  document prompt changes (commit message or accompanying notes).
