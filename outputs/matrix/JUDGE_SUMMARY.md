# LLM-Judge-Auswertung (separate semantische Ebene)

Cross-family Judge `openai/gpt-5.4` (Temperatur 0, JSON-Schema, 1 Votum/Tag) über 30 Läufe. Prüft, was die deterministischen Checks nicht können: Umwelt-/Kontext-Inkonsistenz (Widerspruch zum Stage-1-Fixkontext) und unmotivierten Routine-Drift (Tag-zu-Tag). Diese Befunde sind bewusst NICHT in die regelbasierten Score-Tabellen und Verdikte eingerechnet (unkalibriert, Einzelvotum).

- Beurteilte Tage gesamt: **120**
- Umwelt-/Kontext-konsistent: **101 (84.2%)**
- Umwelt-/Kontext-INKONSISTENT: **19 (15.8%)**
- Routine-Drift geflaggt: **17 (14.2%)**

## Nach Tag-Nummer (Horizont-Drift)

| Tag | beurteilt | env-inkons. | Routine-Drift |
|---|---|---|---|
| T1 | 30 | 2 (6.7%) | 0 (0.0%) |
| T2 | 21 | 2 (9.5%) | 3 (14.3%) |
| T3 | 21 | 4 (19.0%) | 7 (33.3%) |
| T4 | 12 | 2 (16.7%) | 1 (8.3%) |
| T5 | 12 | 0 (0.0%) | 2 (16.7%) |
| T6 | 12 | 7 (58.3%) | 4 (33.3%) |
| T7 | 12 | 2 (16.7%) | 0 (0.0%) |

## Ganztags-Flagship

- Beurteilte Tage: 21; env-konsistent: 18/21 (86%); Routine-Drift: 0.

## Methodische Vorbehalte

- Einzelvotum je Tag (kein Mehrheitsentscheid bei votes=1).
- Nicht gegen eine menschliche Stichprobe kalibriert.
- Teils streng (minutengenaue Zeit-Abweichungen werden geflaggt).
