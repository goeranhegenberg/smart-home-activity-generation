# Smart-Home Activity Generation (Persona & TTDAS)

Project for the *Praktikum IT-Sicherheit* (Universität Leipzig), track
**Prompting/Personas**. A prompt artefact drives a **four-stage LLM pipeline**
that generates schema-faithful smart-home resident activity logs over horizons
from 24 h to one week, plus a deterministic evaluation harness and a JSON→TTDAS
exporter. Methodological frame: Design Science Research.

This repository is the research artifact for the short paper *"Mehrtägige
Generierung schema-treuer Smart-Home-Aktivitätsabläufe mit LLMs"* (Göran
Hegenberg, Universität Leipzig, 2026). `outputs/matrix/` contains the 30
evaluation runs the paper reports (27 morning-matrix runs + 3 full-day flagship
runs), including per-run `metrics.json`, `judge.json` and the aggregated
`SUMMARY.md` / `JUDGE_SUMMARY.md`.

## Pipeline stages

Following Park et al. (Generative Agents), orchestrated in `src/pipeline.py::run_pipeline`:

1. **Stage 1 — Persona & context init.** Build per-resident memory cards from
   resident, environment, device-schema and room descriptions.
2. **Stage 2 — Narrative day-plan.** Generate a definitive natural-language
   narrative for a fixed time window with exact timestamps and explicit device
   state handling.
3. **Stage 3 — Action extraction (JSON).** Extract atomic, schema-conform device
   actions (`timestamp`, `resident`, `device`, `action`, `action_value`, `intent`)
   via structured output, then validate. A self-repair loop (`config.max_repairs`)
   re-prompts with the validator's messages until clean.
4. **Stage 4 — Memory update.** Rewrite the memory cards from the observed actions,
   carrying the device world-state and active multi-day events into the next day.

Multi-day horizons (24 h / 3 days / 1 week) come from chaining Stage 4: the updated
cards of one day are the input of the next (`main.py --days N`).

## Project structure

```text
smart-home-activity-generation/
├── main.py                     # run the pipeline
├── evaluate.py                 # deterministic evaluation (wrapper around src/evaluate.py)
├── run_matrix.py               # evaluation matrix: constellations x horizons x K repeats
├── ttdas.py                    # TTDAS runtime stub (reconstructed from slide 16)
├── config.json                 # model, paths, file names, acceptance thresholds
├── prompts/                    # stage{1,2,3,4}_{system,user}.txt + stage3_repair_user.txt
├── data/                       # default constellation (family, morning) + ttdas_device_map.json
├── data_k2/                    # constellation K2 (single, office)
├── data_k3/                    # constellation K3 (shared flat / WG)
├── data_day/                   # full-day flagship (00:00-24:00, 10 devices, shift-work family)
├── examples/                   # generated TTDAS scripts (Aufgabe 3) + sample input
├── src/
│   ├── pipeline.py             # 4-stage orchestration + self-repair
│   ├── client.py               # OpenAI-compatible client (OpenRouter) + prompt caching
│   ├── validator.py            # structured per-action validation (formal checks)
│   ├── errors.py               # error taxonomy + weighted scoring (Fehlerbepunktung)
│   ├── rooms.py                # rooms.md -> device accessibility map
│   ├── evaluate.py             # metrics + drift + error score + separate judge layer
│   ├── judge.py                # LLM-as-judge (env/context + routine drift)
│   ├── aggregate.py            # matrix aggregation -> SUMMARY.md / JUDGE_SUMMARY.md
│   ├── ttdas_export.py         # Stage-3 JSON -> executable TTDAS script (Aufgabe 3)
│   ├── prompt_loader.py        # {{PLACEHOLDER}} templating
│   └── io_utils.py
└── outputs/matrix/             # the 30 paper runs (27 morning matrix + 3 full-day flagship)
```

## Setup

```bash
pip install -r requirements.txt
```

Set an API key in a `.env` file at the project root. The client defaults to
**OpenRouter**:

```env
OPENROUTER_API_KEY=sk-or-...
# optional: OPENAI_BASE_URL / OPENAI_API_KEY to use a different OpenAI-compatible endpoint
```

Model and acceptance thresholds live in `config.json` (`model`, `judge_model`,
`acceptance`).

## Running the pipeline

```bash
python main.py --days 7 --run-name week_run            # 1-week horizon, default constellation
python main.py --days 3 --data-dir data_k3 --run-name k3_3d
```

Outputs land in `outputs/<run-name>/day_NN/` (`stage2_narrative.txt`,
`stage3_actions.json`, `stage3_validation.txt`, `stage4_persona_cards.txt`).

The full experiment grid of the paper (constellations × horizons × K repeats)
runs via `run_matrix.py`; `src/aggregate.py` folds the per-run `metrics.json`
into `SUMMARY.md` / `JUDGE_SUMMARY.md`:

```bash
python run_matrix.py --plan full --repeats 3 --dry-run   # show the grid + cost, no API
python run_matrix.py --plan full --repeats 3 --judge --judge-votes 1
python -m src.aggregate --subdir matrix
```

## Validation and evaluation

The error catalog is split into two tiers (see `src/errors.py` for the full
taxonomy with codes, severities and German labels).

**Formal errors (must not occur — driven to zero by the Stage-3 self-repair loop, `src/validator.py`):**
invalid JSON / not a list / empty day / item not an object / missing field;
unknown device, invalid action, value out of range; non-singular or unknown
resident; invalid / non-monotonic / out-of-window timestamp; non-atomic action;
persona inaccessibility (a resident operating a device in a room they cannot
reach, derived from `rooms.md` with a caregiver rule so a child's room stays
accessible); continuity re-assertion.

**Content errors (weighted — `hoch`=3, `mittel`=2):**
state accumulation (`mittel`, weight scales with streak length, only scored on
full-day windows) and missing variation (`mittel`, consecutive-day Jaccard ≥ 0.95).

**Judge layer (separate, NOT in the verdicts):** environment/context
inconsistency (`hoch`) and routine drift (`mittel`) via the cross-family
LLM-as-judge (`src/judge.py`). Uncalibrated single vote per day; `evaluate.py`
reports it as `judge_layer` alongside — deliberately outside — the error score,
mirroring the paper's error-catalog table.

`evaluate.py` computes the rule-based metrics, re-validates each day's final
actions, derives the content errors, and emits a **weighted error score** with a
`PASS`/`WARN`/`FAIL` acceptance verdict against the `config.json` `acceptance`
thresholds (no formal errors; no `hoch` content error; per-day and mean content
score under bound).

```bash
python evaluate.py --run week_run [--data-dir data_k3]   # deterministic, no API
python -m src.judge --run week_run [--data-dir data_k3] [--votes 3]   # LLM-as-judge
```

## TTDAS export (Aufgabe 3)

`src/ttdas_export.py` turns a Stage-3 actions JSON into an executable TTDAS script
(slide 16: per device a `launchApp -> replay_recording('<device>_on_off') ->
replay_recording('clear_cache') -> stopApp`, scheduled with `schedule_at`).

```bash
python -m src.ttdas_export --in outputs/matrix/champ_family_h1_r1/day_01/stage3_actions.json \
    --out examples/ttdas_day01.py
python -m src.ttdas_export --in examples/sample_5min_actions.json \
    --out examples/ttdas_5min.py            # the Aufgabe-3.3 5-minute sequence
python examples/ttdas_5min.py               # runs against the ttdas.py stub (logs the calls)
```

Policy (documented in `src/ttdas_export.py`): each `status` action (on **or** off)
maps to the device's single toggle recording; `brightness`/`light_temp` have no
click recording in the simplified (warm/cool, click-only) TTDAS setup and are
skipped+logged; co-timed actions are de-collided with ascending `:SS`. The device
→ app/recording map is `data/ttdas_device_map.json` (shelly/tuya packages from
slide 16; the rest are best-guesses to confirm against the lab's `ttdas_devices.json`,
which was not in our clone). `ttdas.py` is a reconstructed stub that logs instead
of driving a real device; replace it with the lab's template to run for real.

## License

MIT (see `LICENSE`). This covers the code, prompts and the generated
evaluation data under `outputs/`.

## Notes

- Prompts live in `prompts/` — edit them there rather than the Python code.
  The prompt iterations, errors, problems and solutions are documented in the
  accompanying short paper and in `vorgehensweise.md`.
- All paths/filenames are indirected through `config.json`.
