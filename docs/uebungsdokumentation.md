# Übungsdokumentation — Persona & TTDAS

Praktikum IT-Sicherheit (Universität Leipzig), Track **Prompting/Personas** ·
Göran Hegenberg. Diese Datei dokumentiert die Bearbeitung der Aufgaben 1–3
strukturiert; die detaillierten empirischen Befunde (F1–F25) stehen im internen
Lab-Notebook des begleitenden Paper-Projekts, die wissenschaftliche Ausarbeitung
im zugehörigen Short Paper.

---

## Aufgabe 1 — Smart-Home-Dimensionen

Vollständige Bearbeitung der vier Teilaufgaben in **`docs/aufgabe1_smart-home-dimensionen.md`**:
- **1.1** vier maximal gestreute Konstellationen (`data/`, `data_day/`, `data_k2/`, `data_k3/`).
- **1.2** fundamental verschiedene Optionen je Dimension + grobe Mächtigkeit (≈ 1 152, als illustrativ gekennzeichnet).
- **1.3** notwendiges deckendes Set entlang der Verhaltens-Extrempunkte (≈ 4–6).
- **1.4** realistisch umsetzbar: 3–4 (genau die implementierten).

## Aufgabe 2 — Aktivitätsabläufe erstellen

### 2.1 Entwicklungsumgebung
- Repo geklont, `requirements.txt` installiert.
- **Statt OpenAI-Key: OpenRouter** (`OPENROUTER_API_KEY` in `.env`), da der Folien-Key ungültig war und eine System-Env-Var die `.env` überschrieb (BEFUNDE F8). Client: `base_url=https://openrouter.ai/api/v1`, Chat-Completions.
- Testanfrage erfolgreich; Modelle `openai/gpt-5.4` und `anthropic/claude-opus-4.8` verfügbar.

### 2.2 Eine Konstellation, Stages 1–3, Prüfung, Prompt-Verbesserung
- Konstellation (Morgen 06:00–09:00) implementiert; Stages 1–3 laufen (`main.py`).
- **Prüf-Methodik:** deterministischer Validator (`src/validator.py`) + gewichtete
  Fehlerbepunktung (`src/errors.py`) + Eval-Harness (`src/evaluate.py`), zusätzlich
  ein **LLM-as-Judge** (`src/judge.py`, andere Modellfamilie). Strukturierter Output
  (JSON-Schema mit Enums) sichert die formale Ebene; Validator + Self-Repair die
  semantische.
- **Probleme/Fehler/Lösungen** (Auszug, Details BEFUNDE F1–F17): Verbalisierungs-
  Artefakt im Narrativ (F2); Kontinuitäts-Events trotz Prompt-Regeln → Self-Repair-
  Loop ergänzt (F3/F4); stiller Zustandsverlust durch Carry × Dedup (F6); fehlende
  Variation als reales, messbares Defizit (F15/F17).
- **Prompt-Templates** iterativ verbessert (Baseline → Champion). Im finalen
  Repo-Stand liegt nur der Champion-Satz (`prompts/`) vor; der A/B-Baseline-Satz
  wurde mit der Fokussierung des Papers auf den Champion entfernt.

### 2.3 Stage 4 (Erinnerungsupdate) + beliebige Länge + 1 Tag / 3 Tage / 1 Woche
- **Stage-4-Prompt** erstellt (`prompts/stage4_*.txt`): schreibt Memory-Cards fort,
  trägt Weltzustand + aktive Ereignisse über Tage (Regel „keine Aktion = unverändert").
- **Beliebig lange Aufnahme** über festes Zeitfenster via `main.py --days N`
  (Stage 4 verkettet die Tage).
- **Läufe 1/3/7 Tage** durchgeführt; Unterschiede/Probleme/Lösungen in BEFUNDE
  (F9 Weltzustand über 7 Tage stabil, F15 Variations-Befund, F6 Drift-Mechanismus).
- **Ganztags-Flagship (00:00–24:00, 1 Woche, claude-opus-4.8, 10 Geräte):** 21/21
  valide (K=3), Weltzustand-Churn 0, Coverage 16/16, Judge 18/21 Tage
  umwelt-konsistent bei 0 Routine-Drift-Flags (BEFUNDE F24/F25).

## Aufgabe 3 — Aktivitätsabläufe für TTDAS implementieren

- **`src/ttdas_export.py`** erzeugt aus einem Stage-3-JSON ein **ausführbares
  TTDAS-Skript** nach Folie 16 (`schedule_at` + `launchApp → replay_recording →
  clear_cache → stopApp`).
- **`ttdas.py`** ist ein rekonstruierter Laufzeit-Stub (loggt statt Gerät zu
  steuern), da die Lab-Vorlage `ttdas.py`/`ttdas_actions/`/`ttdas_devices.json`
  **nicht im erhaltenen GitLab-Clone** lag. **`data/ttdas_device_map.json`** mappt
  Gerät→App+Recording (shelly/tuya aus Folie 16, übrige als markierte Schätzung —
  bitte gegen die echte `ttdas_devices.json` abgleichen).
- **5-Minuten-Ablauf:** `examples/ttdas_5min.py` (+ `examples/ttdas_run1d_day01.py`
  aus echtem Pipeline-Output), beide gegen den Stub lauffähig.
- **Policy:** `status` on/off → ein Toggle-Recording je Gerät; Helligkeit/
  Farbtemperatur ohne Klick-Recording (Folie 15) → übersprungen + geloggt; gleiche
  Minute → aufsteigende `:SS`.

```bash
python -m src.ttdas_export --in examples/sample_5min_actions.json --out examples/ttdas_5min.py
python examples/ttdas_5min.py
```

## Evaluation (Querschnitt)

Zweistufiges Fehlermodell (`src/errors.py`): **formal** (hart, Self-Repair → 0) vs.
**inhaltlich** (gewichtet, hoch=3/mittel=2). Gewichtete Fehlerbepunktung mit
PASS/WARN/FAIL gegen Schranken (`config.json`). Der **LLM-as-Judge** (Umwelt-/
Kontext-Konsistenz, Routine-Drift; andere Modellfamilie) wird als separate,
unkalibrierte Ebene berichtet und nicht in die Verdikte eingerechnet. Eine
zwischenzeitlich erprobte externe Realismus-Verankerung gegen CASAS
(Jensen-Shannon über Timing-Verteilungen) wurde im finalen Stand bewusst
entfernt: Der Verteilungsabstand vermengt die Domänen-Differenz (Ambient-
Sensorik vs. bewusste Geräteaktionen) mit der Qualitätsfrage (siehe Paper,
Methodik). Der gesamte Eval-Code wurde zusätzlich adversarial (Multi-Agent)
reviewt und gehärtet (BEFUNDE F19–F23).

## Verweise
- Wissenschaftliche Ausarbeitung: begleitendes Short Paper (IEEE-Format); die
  F-Nummern in diesem Dokument verweisen auf das interne Lab-Notebook (F1–F25)
  des Paper-Projekts.
