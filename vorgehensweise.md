# Vorgehensweise

Dieses Dokument beschreibt, wie ich das Projekt „Persona & TTDAS" bearbeitet habe — vom bereitgestellten Python-Skelett bis zum finalen Artefakt samt Evaluations-Harness. Ausgangspunkt war eine dreistufige LLM-Pipeline (Persona-Cards → Narrative → JSON-Aktionen) mit einer leeren vierten Stufe. Das erste Ziel war, die Ausgabe so anzupassen, dass ein möglichst realistisches Haushaltsszenario entsteht und Stage 4 tatsächlich genutzt wird; daraus ist schrittweise die Mess-Infrastruktur geworden, mit der das begleitende Paper arbeitet.

## Erweiterung der Bewohner

Als Erstes ist mir aufgefallen, dass zwei symmetrische Erwachsene (Alice: Homeoffice, Bob: Büro) ein recht künstliches Szenario ergeben. Ich habe daher **Charlie** ergänzt, ein 8-jähriges Schulkind. In der Beschreibung habe ich explizit festgehalten, dass Charlie Geräte **nicht selbstständig bedient**, sondern Aktionen der Eltern auslöst (z. B. Lampe anschalten, weil Charlie aufstehen muss).

Das hat sofort zwei Dinge verbessert: Der Morgen bekam eine natürliche Reihenfolge (Bob weckt Charlie, Frühstück gemeinsam, Schulweg um 08:30 zusammen mit Bob), und das `intent`-Feld in Stage 3 hatte endlich etwas Sinnvolles zu tragen — nämlich den Unterschied zwischen "wer bedient" und "für wen".

## Gerätebeschreibungen und Raumzuordnung

In den ersten Durchläufen hat das Modell Geräte teilweise willkürlich kombiniert — z. B. ein Shelly-Relais wie eine dimmbare Lampe behandelt oder Interaktionen in Räumen stattfinden lassen, in denen sich die Person gar nicht aufhielt. Die Geräteschema-Datei allein reicht dafür nicht aus, weil sie nur Wertebereiche, aber keine physische Bedeutung liefert.

Ich habe deshalb zwei neue Eingabedateien angelegt:

- `data/available-smart-devices-description.md` — beschreibt pro Gerät, was es physisch ist und wie die zulässigen Werte auf reales Verhalten abgebildet werden (z. B. `brightness=high` als Arbeitslicht, `warm` vs. `cool` bei der Farbtemperatur).
- `data/rooms.md` — eine Wohnungskarte mit fünf Bereichen (Schlafzimmer, Charlies Zimmer, Wohnbereich, Küche, Flur) und der Zuordnung, welches Gerät in welchem Raum steht.

Beide Dateien werden über `config.json` geladen und wurden zunächst als `{{DEVICE_DESCRIPTIONS}}` / `{{ROOMS}}` in die Prompts von Stage 1 und 2 eingesetzt; seit der Umstellung auf Prompt-Caching (siehe unten) stehen sie stattdessen im gecachten Fixkontext-Block, auf den sich die Templates beziehen. Dadurch haben die Persona-Cards und das Narrativ eine gemeinsame Grundlage, und Handlungen sind an Anwesenheit im Raum gebunden.

Zusätzlich habe ich den Stage-2-System-Prompt um den Satz erweitert: *"Only emit a state-change event when the device's state actually changes."* — als erste Gegenmaßnahme gegen Kontinuitätsereignisse (siehe weiter unten).

## Realistische Zeitstempel

Die generierten Uhrzeiten lagen anfangs fast ausnahmslos auf `:00`, `:15`, `:30` oder `:45`. Das ist ein bekannter LLM-Bias, sieht aber überhaupt nicht wie Sensordaten aus einem echten Haushalt aus. Ich habe den Stage-2-User-Prompt um eine ausführliche Zeitstempel-Regel ergänzt: keine Häufung auf runden Fünf-Minuten-Marken, Minutenwerte sollen an der tatsächlichen Dauer der Handlung orientiert sein (Schalter umlegen dauert Sekunden, Kaffee kochen ca. 3 Minuten, Anziehen 8–12 Minuten). Zusätzlich habe ich Beispiel-Zeitstempel wie `06:03, 06:17, 06:42` angegeben, damit das Modell das Muster übernimmt.

Nach dieser Änderung waren die Zeitstempel im Narrativ deutlich gestreuter und wirkten nachvollziehbar. Hundertprozentig konsistent ist das Modell nicht, aber das Gesamtbild ist klar besser.

## Eindeutige Zurechnung pro Aktion

Ein weiteres Problem war, dass gemeinsame Handlungen ("Alice and Bob turn on the living room light") in Stage 3 als `resident: "Alice and Bob"` oder `"family"` landeten. Für eine spätere Angreifer-Analyse ist das unbrauchbar, weil sich Aktionen keiner Person zuordnen lassen.

Ich habe den Stage-3-User-Prompt so verschärft, dass `resident` **genau einen Namen** enthalten muss. Wenn mehrere Personen beteiligt sind, soll die Person gewählt werden, die das Gerät physisch bedient hat; die Motivation für eine andere Person gehört ins `intent`-Feld.

Parallel dazu habe ich den `validator.py` erweitert: Er liest jetzt die bekannten Namen aus `residents.txt` (`extract_resident_names`) und meldet sowohl zusammengesetzte Werte (` and `, `,`, `/`, "everyone", "family") als auch unbekannte Namen als Fehler. Dadurch fallen Rückfälle sofort auf und müssen nicht manuell in der JSON-Ausgabe gesucht werden.

## Keine doppelten Zustandsereignisse

Trotz der Regel in Stage 2 hat das Modell im Narrativ weiterhin Kontinuitätssätze produziert ("the lamp remains on", "heating is still running"), die Stage 3 naiv als neue Events geparst hat. Dadurch standen in der Aktionsliste mehrfach hintereinander identische `(device, action, action_value)`-Tripel — was im realen TTDAS-Kontext falsch wäre, weil ein Event-Log nur Zustandswechsel enthalten sollte.

Meine Lösung war zweigeteilt:

1. **Im Stage-3-System-Prompt:** Ich habe dem Parser aufgetragen, den laufenden Zustand jedes Geräts beim Durchgehen des Narrativs mitzuführen und Zeilen zu überspringen, deren Werte identisch zum letzten emittierten Ereignis desselben `(device, action)`-Paars sind. Kontinuitätsformulierungen ("stays", "remains", "keeps", "is still") wurden explizit als Nicht-Events gekennzeichnet.
2. **Im Validator:** Eine `last_value`-Map, die pro `(device, action)` den zuletzt gesehenen Wert speichert und bei Wiederholung einen Fehler ausgibt.

Zusätzlich habe ich an dieser Stelle das Modell von `gpt-5.4-mini` auf `gpt-5.4` umgestellt, weil die Mini-Variante die Zustandsverfolgung nicht zuverlässig genug beherrschte. (Für die finalen Läufe habe ich die Generierung später noch einmal auf `anthropic/claude-opus-4.8` umgestellt; `gpt-5.4` übernahm die Rolle des cross-family Judge — siehe unten.)

## Stage 4 und Mehrtages-Schleife

Danach habe ich Stage 4 implementiert. Die Stufe bekommt die aktuellen Persona-Cards plus die validierten Aktionen eines abgeschlossenen Zeitfensters und gibt aktualisierte Cards zurück. Wichtige Regeln im Prompt:

- Stabile Felder (Name, Rolle, Alter, fixe Ankerzeiten) bleiben unverändert.
- Gewohnheiten und Präferenzen werden nur angepasst, wenn die beobachteten Aktionen klare, wiederholte Evidenz liefern.
- Einzelaktionen werden **nicht** in die Karten aufgenommen — nur Muster.
- Die Kartenlänge darf sich pro Iteration um maximal ±20 % verändern.
- Gerätezustand am Fensterende und aktive mehrtägige Situationen werden in eigenen Abschnitten ("World state", "Active events") explizit fortgetragen — mit der Regel „keine Aktion = unverändert", damit ein nicht erwähntes Gerät nicht stillschweigend als „aus" gelesen wird.

Die Längenregel war besonders wichtig: In frühen Versuchen hat das Modell einfach alle beobachteten Events angehängt, sodass die Persona-Cards nach drei Tagen zu einem Logfile mutiert wären. Erst mit der expliziten Längenbeschränkung und dem Verbot, Einzelereignisse aufzulisten, bleibt die Zusammenfassung nutzbar.

`run_pipeline` habe ich in eine Schleife über `days` umgebaut. Jeder Tag bekommt ein eigenes Unterverzeichnis `outputs/<run>/day_NN/` mit allen Zwischenausgaben, und ein neu eingeführter `{{DAY_CONTEXT}}` (Wochentag plus Nummer) fließt in Stage 2 ein. So unterscheidet das Modell zwischen Werktagen (Büro, Schule) und Wochenende, und die Entwicklung der Persona-Cards lässt sich über mehrere Tage nachvollziehen.

## Aufgetretene Probleme (frühe Phase)

- **JSON-Parse-Fehler:** Stage 3 hat gelegentlich Code-Fences (` ```json `) um die Ausgabe gelegt. Zunächst habe ich das nur im System-Prompt untersagt; im finalen Stand fängt zusätzlich ein kleiner Fence-Stripper in `pipeline.py` (`_strip_fences`) solche Ausgaben deterministisch ab, und der strukturierte Output (nächster Abschnitt) macht das Problem weitgehend gegenstandslos.
- **Charlie als Akteur:** Trotz klarer Beschreibung hat das Modell Charlie anfangs mehrfach selbst Lampen schalten lassen. Nachdem ich die Information sowohl in `residents.txt` als auch implizit über die Raum-/Geräte-Dateien verankert habe, verschwand das Verhalten weitgehend.
- **Mini-Modell zu schwach:** Mit `gpt-5.4-mini` war die Zustandsverfolgung in Stage 3 unzuverlässig. Das war letztlich der Ausschlag für den Wechsel auf die volle Variante.

## Strukturierter Output und Self-Repair

Formale Fehler (ungültiges JSON, unbekannte Geräte, falsche Wertebereiche) ließen sich per Prompt allein nicht vollständig eliminieren. Gelöst haben das zwei Mechanismen:

1. **Strukturierter Output in Stage 3:** Der Aufruf erzwingt per `response_format` ein striktes JSON-Schema, in dem Gerätenamen und Bewohner als Enums hinterlegt sind (`build_stage3_schema`). Ganze Fehlerklassen (unbekanntes Gerät, nicht-singulärer Bewohner, fehlende Pflichtfelder) sind damit per Konstruktion ausgeschlossen.
2. **Self-Repair-Schleife:** Meldet der Validator nach der Generierung noch Fehler, gehen das fehlerhafte JSON und die konkreten Fehlermeldungen zurück ans Modell — mit begrenzter Versuchszahl (`config.max_repairs`). Als letztes deterministisches Sicherheitsnetz entfernt `_dedup_continuity` überlebende Kontinuitäts-Duplikate, ohne den physischen Log zu verändern.

In den 30 finalen Läufen blieb damit über alle formalen Kategorien hinweg genau ein Restfehler (ein nicht-monotoner Zeitstempel in einem Morgen-Wochenlauf).

## Modellwahl und Prompt-Caching

Final erzeugt `anthropic/claude-opus-4.8` (über OpenRouter) alle vier Stufen; `openai/gpt-5.4` dient ausschließlich als Judge aus einer anderen Modellfamilie (kein Selbst-Evaluations-Bias). Der lauffixe Referenzkontext (Bewohner, Umwelt, Geräteschema, Gerätebeschreibungen, Räume) wird byte-identisch als gecachter System-Block vor jeden Call gestellt (Anthropic `cache_control`): Der erste Aufruf schreibt den Cache, alle folgenden lesen ihn zu einem Bruchteil der Kosten. Erst dadurch wurden Ganztags-Wochenläufe (viele lange Calls über denselben Fixkontext) bezahlbar.

## Evaluations-Harness: zweistufige Fehlerbepunktung

Damit „besser" nicht Bauchgefühl bleibt, bewertet `src/evaluate.py` jeden Tag auf zwei Ebenen (`src/errors.py`):

- **Formal (hart, muss null sein):** Re-Validierung der finalen Aktionsliste gegen den vollen Regelsatz (Schema, Zeitstempel-Format/-Monotonie/-Fenster, Atomarität, Personen-Zugänglichkeit aus der Raumkarte, Kontinuität, leere Tage).
- **Inhaltlich (gewichtet, hoch = 3 / mittel = 2):** *Zustands-Akkumulation* (Gerät bleibt ≥ 3 Folgetage durchgehend an, +1 Punkt je weiterem Streak-Tag; nur auf Ganztagsfenstern gewertet, weil auf einem Morgenfenster das spätere Ausschalten außerhalb des Fensters liegt) und *Fehlende Variation* (Tag-zu-Tag-Jaccard ≥ 0,95 über die (Gerät, Aktion, Wert)-Mengen).

Aus den Punkten folgt je Lauf ein PASS/WARN/FAIL-Verdikt gegen vorab fixierte Schranken (`config.json`), dazu eine Qualitätskurve pro Tag und ein Bruchpunkt („ab welchem Tag bricht die Qualität ein") für die Drift-Analyse des Papers.

## LLM-as-Judge als separate Ebene

Zwei Fehlerarten sind deterministisch nicht prüfbar: Widersprüche zum fixen Kontext (Wetter, Jahreszeit, Persona-Routinen) und unmotivierter Routine-Drift zwischen Folgetagen. Dafür liest ein Judge-Modell (`src/judge.py`, Temperatur 0, JSON-Schema) Tag für Tag das Narrativ plus den Stage-1-Fixkontext. Die Befunde werden bewusst als **separate, unkalibrierte Ebene** berichtet (`judge_layer` in `metrics.json`, aggregiert in `JUDGE_SUMMARY.md`) und **nicht** in die Verdikte eingerechnet. Auffälligster Befund: der Tag-6-Ausschlag auf den Morgen-Wochenläufen. Er ist kein spontaner Modell-Drift, sondern ein Spezifikations-Artefakt: Die Stage-2-Regeln fordern ausdrücklich eine Wochenend-Verschiebung der Routine, während die Morgen-Personas nur Werktagsroutinen kodieren — der Judge flaggt diesen einprogrammierten Konflikt als Kontext-Widerspruch. Im kalendrisch verankerten Ganztags-Flagship tritt er nicht auf.

## Evaluations-Matrix und Ganztags-Flagship

`run_matrix.py` automatisiert das Versuchsdesign des Papers: drei bewusst verschiedene Morgen-Konstellationen (Familie `data/`, Single `data_k2/`, WG `data_k3/`) × Horizonte 1/3/7 Tage × K = 3 Wiederholungen, plus das Ganztags-Flagship (`data_day/`: 00:00–24:00, 10 Geräte, Familie mit rotierendem Schichtdienst) über eine volle Woche mit K = 3. Das ergibt die 30 Läufe in `outputs/matrix/`; `src/aggregate.py` verdichtet sie zu `SUMMARY.md` und `JUDGE_SUMMARY.md`. Kernbefunde: Schema-Treue praktisch durchgängig, Geräte-Weltzustand über die Woche kohärent (Churn 0 im Flagship, ~64 Aktionen/Tag), während die zu geringe Tag-zu-Tag-Variation als messbare Schwäche bestehen bleibt. Zwischenzeitlich erprobte Erweiterungen (ein Baseline-Promptsatz für A/B-Vergleiche, ein CASAS-Realismus-Anker, Ereignis-Injektion) habe ich mit der Fokussierung des Papers auf den Champion-Prompt wieder aus dem Artefakt entfernt.

## TTDAS-Export

`src/ttdas_export.py` übersetzt ein Stage-3-JSON in ein ausführbares TTDAS-Skript (je Aktion `schedule_at` mit `launchApp → replay_recording → clear_cache → stopApp`). Policy: Jede `status`-Aktion (an **oder** aus) nutzt das eine Toggle-Recording des Geräts; `brightness`/`light_temp` haben im vereinfachten Klick-Setup kein Recording und werden übersprungen und geloggt; zeitgleiche Aktionen werden über aufsteigende Sekunden entzerrt. `ttdas.py` ist ein rekonstruierter Stub, der Aufrufe loggt statt echte Geräte zu steuern; gegen die Labor-Vorlage ist er austauschbar.

## Fazit

Jeder Schritt hat einen konkreten Defekt der Rohausgabe adressiert: fehlendes Familienmitglied → natürliche Asymmetrie; abstrakte Geräte → räumlich verankerte Handlungen; Uhrzeiten auf Viertelstunden → realistisch verteilte Zeitstempel; Gruppen-Akteure → eindeutige Zurechenbarkeit; Kontinuitäts-Events → saubere Zustandsübergänge; Ein-Tages-Schnappschuss → verketteter Mehrtages-Verlauf; formale Restfehler → strukturierter Output mit Self-Repair; gefühlte Qualität → zweistufige Bepunktung mit separatem LLM-Judge. Die 30 Läufe in `outputs/matrix/` dokumentieren das Ergebnis: schema-treue, über eine Woche inhaltlich kohärente Abläufe — und eine ehrlich vermessene Restschwäche bei der Tag-zu-Tag-Variation.
