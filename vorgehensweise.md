# Vorgehensweise

Dieses Dokument beschreibt, wie wir das Projekt "Persona & TTDAS" bearbeitet haben. Ausgangspunkt war das bereitgestellte Python-Skelett mit einer dreistufigen LLM-Pipeline (Persona-Cards → Narrative → JSON-Aktionen) und einer leeren vierten Stufe. Unser Ziel war es, die Ausgabe so anzupassen, dass ein möglichst realistisches Haushaltsszenario entsteht und dass Stage 4 tatsächlich genutzt wird.

## Erweiterung der Bewohner

Als Erstes ist uns aufgefallen, dass zwei symmetrische Erwachsene (Alice: Homeoffice, Bob: Büro) ein recht künstliches Szenario ergeben. Wir haben daher **Charlie** ergänzt, ein 8-jähriges Schulkind. In der Beschreibung haben wir explizit festgehalten, dass Charlie Geräte **nicht selbstständig bedient**, sondern Aktionen der Eltern auslöst (z. B. Lampe anschalten, weil Charlie aufstehen muss).

Das hat sofort zwei Dinge verbessert: Der Morgen bekam eine natürliche Reihenfolge (Bob weckt Charlie, Frühstück gemeinsam, Schulweg um 08:30 zusammen mit Bob), und das `intent`-Feld in Stage 3 hatte endlich etwas Sinnvolles zu tragen — nämlich den Unterschied zwischen "wer bedient" und "für wen".

## Gerätebeschreibungen und Raumzuordnung

In der ersten Durchläufen hat das Modell Geräte teilweise willkürlich kombiniert — z. B. ein Shelly-Relais wie eine dimmbare Lampe behandelt oder Interaktionen in Räumen stattfinden lassen, in denen sich die Person gar nicht aufhielt. Die Geräteschema-Datei allein reicht dafür nicht aus, weil sie nur Wertebereiche, aber keine physische Bedeutung liefert.

Wir haben deshalb zwei neue Eingabedateien angelegt:

- `data/available-smart-devices-description.md` — beschreibt pro Gerät, was es physisch ist und wie die zulässigen Werte auf reales Verhalten abgebildet werden (z. B. `brightness=high` als Arbeitslicht, `warm` vs. `cool` bei der Farbtemperatur).
- `data/rooms.md` — eine Wohnungskarte mit fünf Bereichen (Schlafzimmer, Charlies Zimmer, Wohnbereich, Küche, Flur) und der Zuordnung, welches Gerät in welchem Raum steht.

Beide Dateien werden über `config.json` geladen und als `{{DEVICE_DESCRIPTIONS}}` / `{{ROOMS}}` in die Prompts von Stage 1 und 2 eingesetzt. Dadurch haben die Persona-Cards und das Narrativ eine gemeinsame Grundlage, und Handlungen sind an Anwesenheit im Raum gebunden.

Zusätzlich haben wir den Stage-2-System-Prompt um den Satz erweitert: *"Only emit a state-change event when the device's state actually changes."* — als erste Gegenmaßnahme gegen Kontinuitätsereignisse (siehe weiter unten).

## Realistische Zeitstempel

Die generierten Uhrzeiten lagen anfangs fast ausnahmslos auf `:00`, `:15`, `:30` oder `:45`. Das ist ein bekannter LLM-Bias, sieht aber überhaupt nicht wie Sensordaten aus einem echten Haushalt aus. Wir haben den Stage-2-User-Prompt um eine ausführliche Zeitstempel-Regel ergänzt: keine Häufung auf runden Fünf-Minuten-Marken, Minutenwerte sollen an der tatsächlichen Dauer der Handlung orientiert sein (Schalter umlegen dauert Sekunden, Kaffee kochen ca. 3 Minuten, Anziehen 8–12 Minuten). Zusätzlich haben wir Beispiel-Zeitstempel wie `06:03, 06:17, 06:42` angegeben, damit das Modell das Muster übernimmt.

Nach dieser Änderung waren die Zeitstempel im Narrativ deutlich gestreuter und wirkten nachvollziehbar. Hundertprozentig konsistent ist das Modell nicht, aber das Gesamtbild ist klar besser.

## Eindeutige Zurechnung pro Aktion

Ein weiteres Problem war, dass gemeinsame Handlungen ("Alice and Bob turn on the living room light") in Stage 3 als `resident: "Alice and Bob"` oder `"family"` landeten. Für eine spätere Angreifer-Analyse ist das unbrauchbar, weil sich Aktionen keiner Person zuordnen lassen.

Wir haben den Stage-3-User-Prompt so verschärft, dass `resident` **genau einen Namen** enthalten muss. Wenn mehrere Personen beteiligt sind, soll die Person gewählt werden, die das Gerät physisch bedient hat; die Motivation für eine andere Person gehört ins `intent`-Feld.

Parallel dazu haben wir den `validator.py` erweitert: Er liest jetzt die bekannten Namen aus `residents.txt` (`extract_resident_names`) und meldet sowohl zusammengesetzte Werte (` and `, `,`, `/`, "everyone", "family") als auch unbekannte Namen als Fehler. Dadurch fallen Rückfälle sofort auf und müssen nicht manuell in der JSON-Ausgabe gesucht werden.

## Keine doppelten Zustandsereignisse

Trotz der Regel in Stage 2 hat das Modell im Narrativ weiterhin Kontinuitätssätze produziert ("the lamp remains on", "heating is still running"), die Stage 3 naiv als neue Events geparst hat. Dadurch standen in der Aktionsliste mehrfach hintereinander identische `(device, action, action_value)`-Tripel — was im realen TTDAS-Kontext falsch wäre, weil ein Event-Log nur Zustandswechsel enthalten sollte.

Unsere Lösung war zweigeteilt:

1. **Im Stage-3-System-Prompt:** Wir haben dem Parser aufgetragen, den laufenden Zustand jedes Geräts beim Durchgehen des Narrativs mitzuführen und Zeilen zu überspringen, deren Werte identisch zum letzten emittierten Ereignis desselben `(device, action)`-Paars sind. Kontinuitätsformulierungen ("stays", "remains", "keeps", "is still") wurden explizit als Nicht-Events gekennzeichnet.
2. **Im Validator:** Eine `last_value`-Map, die pro `(device, action)` den zuletzt gesehenen Wert speichert und bei Wiederholung einen Fehler ausgibt.

Zusätzlich haben wir an dieser Stelle das Modell von `gpt-5.4-mini` auf `gpt-5.4` umgestellt, weil die Mini-Variante die Zustandsverfolgung nicht zuverlässig genug beherrschte.

## Stage 4 und Mehrtages-Schleife

Zum Abschluss haben wir Stage 4 implementiert. Die Stufe bekommt die aktuellen Persona-Cards plus die validierten Aktionen eines abgeschlossenen Zeitfensters und gibt aktualisierte Cards zurück. Wichtige Regeln im Prompt:

- Stabile Felder (Name, Rolle, Alter, fixe Ankerzeiten) bleiben unverändert.
- Gewohnheiten und Präferenzen werden nur angepasst, wenn die beobachteten Aktionen klare, wiederholte Evidenz liefern.
- Einzelaktionen werden **nicht** in die Karten aufgenommen — nur Muster.
- Die Kartenlänge darf sich pro Iteration um maximal ±20 % verändern.

Die letzte Regel war besonders wichtig: In frühen Versuchen hat das Modell einfach alle beobachteten Events angehängt, sodass die Persona-Cards nach drei Tagen zu einem Logfile mutiert wären. Erst mit der expliziten Längenbeschränkung und dem Verbot, Einzelereignisse aufzulisten, bleibt die Zusammenfassung nutzbar.

`run_pipeline` haben wir in eine Schleife über `days` umgebaut. Jeder Tag bekommt ein eigenes Unterverzeichnis `outputs/<run>/day_NN/` mit allen vier Zwischenausgaben, und ein neu eingeführter `{{DAY_CONTEXT}}` (Wochentag plus Nummer) fließt in Stage 2 ein. So unterscheidet das Modell zwischen Werktagen (Büro, Schule) und Wochenende und wir können die Entwicklung der Persona-Cards über mehrere Tage nachvollziehen.

## Aufgetretene Probleme

- **JSON-Parse-Fehler:** Stage 3 hat gelegentlich Code-Fences (` ```json `) um die Ausgabe gelegt. Wir haben zwar keinen eigenen Pre-Parser ergänzt, aber im System-Prompt klargestellt, dass nur reines JSON erlaubt ist; damit trat das Problem praktisch nicht mehr auf.
- **Charlie als Akteur:** Trotz klarer Beschreibung hat das Modell Charlie anfangs mehrfach selbst Lampen schalten lassen. Nachdem wir die Information sowohl in `residents.txt` als auch implizit über die Raum-/Geräte-Dateien verankert haben, verschwand das Verhalten weitgehend.
- **Mini-Modell zu schwach:** Mit `gpt-5.4-mini` war die Zustandsverfolgung in Stage 3 unzuverlässig. Das war letztlich der Ausschlag für den Wechsel auf die volle Variante.

## Fazit

Jeder Schritt hat einen konkreten Defekt der Rohausgabe adressiert: fehlendes Familienmitglied → natürliche Asymmetrie; abstrakte Geräte → räumlich verankerte Handlungen; Uhrzeiten auf Viertelstunden → realistisch verteilte Zeitstempel; Gruppen-Akteure → eindeutige Zurechenbarkeit; Kontinuitäts-Events → saubere Zustandsübergänge; Ein-Tages-Schnappschuss → lernender Mehrtages-Verlauf. Die Ausgaben in `outputs/` spiegeln diese Entwicklung wider — aus einer generischen Aktionsliste ist ein zeitlich und sozial plausibles Haushaltsszenario geworden.
