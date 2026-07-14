# Aufgabe 1 — Smart-Home-Dimensionen

Bearbeitung der vier Teilaufgaben aus der Übung „Persona & TTDAS" (Folie 19) für
den Track Prompting/Personas. Bezug: die fünf Dimensionen zur Definition eines
Smart Homes (Beschäftigung, Zeitraum, Soziale Struktur, Geräte & Automatisierungs-
grad, Umwelt).

## 1.1 Weitere Konstellationen (≥ 2, möglichst verschieden)

Über die fünf Dimensionen wurden mehrere, bewusst maximal gestreute Konstellationen
entworfen und im Repo implementiert (`data*/`-Ordner):

| | K0 `data` (Referenz) | K1 `data_day` | K2 `data_k2` | K3 `data_k3` |
|---|---|---|---|---|
| **Soziale Struktur** | Familie, 3 Pers. (2 Erw. + Kind) | Familie, 3 Pers. | Single | WG, 2 Pers. |
| **Beschäftigung** | Homeoffice + Büro + Schule | **Rotierende Schicht** (Pflege) + Büro + Schule | Büro / Pendeln | Homeoffice (beide) |
| **Zeitraum** | Morgen (06:00–09:00) | **Ganzer Tag (00:00–24:00), 1 Woche** | Morgen | Morgen |
| **Geräte & Automatisierung** | 5 Geräte, manuell | **10 Geräte** (mehrere Räume), manuell | 5 Geräte, manuell | 5 Geräte, manuell |
| **Umwelt** | Wohnung, DE, Winter | Haus, DE, November | 2-Zi-Wohnung, DE, Januar | Altbau-WG, DE, Oktober |

K1 (`data_day`) ist die gerätereiche Ganztags-Konstellation mit Schicht-/Wochenend-
Variation; K2/K3 variieren Soziale Struktur und Beschäftigung gegenüber der Referenz.
Damit sind die verhaltensbestimmenden Achsen (Personenzahl/-verhältnis, Arbeits-
rhythmus, Horizont, Gerätedichte) jeweils deutlich anders belegt.

## 1.2 Fundamental verschiedene Optionen je Dimension + Mächtigkeit des Raums

Realistisch unterscheidbare (grobkörnige) Optionen je Dimension:

| Dimension | Fundamental verschiedene Optionen | Anzahl |
|---|---|---|
| **Beschäftigung** | auswärts/Pendeln · Homeoffice · Schicht-/Nachtdienst · nicht erwerbstätig (Rente/Elternzeit/arbeitslos) | 4 |
| **Zeitraum** | einzelne Arbeitstage · inkl. Wochenende · inkl. Urlaub/Sonderereignis · Langzeit-Routinen (Wochen) | 4 |
| **Soziale Struktur** | Single · Paar · Familie mit Kind(ern) · WG | 4 |
| **Geräte & Automatisierung** | wenige/manuell · mittel/teilautomatisiert · viele/vollautomatisiert | 3 |
| **Umwelt** | Klima/Saison {Winter · Sommer · Übergang} × Gebäude {Wohnung · Haus} | 3 × 2 = 6 |

Als grobes Produkt: **4 · 4 · 4 · 3 · 6 = 1 152** Konstellationen. Die Zahl ist
**illustrativ**, nicht absolut: die Kardinalität jeder Achse ist eine Modellierungs-
entscheidung (man kann feiner aufteilen — z. B. Personenzahl 1–5, Automatisierung
kontinuierlich, Geräteklassen einzeln — wodurch der Raum schnell in die
Zehntausende wächst, oder gröber, wodurch er kleiner wird). Entscheidend ist: der
Konstellationsraum ist **kombinatorisch groß und kann nicht erschöpfend** abgedeckt
werden.

## 1.3 Welche Konstellationen sind notwendig, um die Bandbreite abzudecken?

Eine vollständige Abdeckung (Kreuzprodukt) ist weder nötig noch leistbar. Sinnvoll
ist ein **deckendes Set entlang der verhaltensbestimmenden Extrempunkte** statt
aller Kombinationen, weil sich viele Dimensionen in ihrer Wirkung auf den Geräte-
gebrauch überlagern:

- **Soziale Struktur** und **Beschäftigung** treiben An-/Abwesenheit und damit den
  Aktivitätsverlauf am stärksten → hier braucht es die Extreme: **Single-Pendler**
  (Haus tagsüber leer), **Familie mit Kind** (Morgen-Rush, mehrere Akteure),
  **WG/Homeoffice** (ganztags belegt, lose gekoppelt) und **Schicht-/Nachtdienst**
  (atypische, stark tagesvariable Belegung).
- **Geräte & Automatisierung**: mindestens **manuell** vs. **hoch automatisiert**,
  weil Automatisierung die Aktions-Urheberschaft (Mensch vs. Regel) verschiebt.
- **Umwelt**: mindestens **Winter** vs. **Sommer** (Heizung/Licht-Bedarf kippt).
- **Zeitraum**: mindestens **Arbeitstag** und **Woche inkl. Wochenende** (Wochenende
  ändert die Routine grundlegend), plus ein **Sonderereignis** (Gast/Urlaub).

Minimal notwendiges Set zur Abdeckung der Bandbreite: **≈ 4–6 gezielt gewählte
Konstellationen**, die diese Extrempunkte abdecken — nicht die 1 000+ des Kreuz-
produkts.

## 1.4 Welche sind im Rahmen des Praktikums realistisch umsetzbar?

Realistisch (Zeit-/API-Budget, kontrollierter Vergleich): **3–4 Konstellationen**.
Umgesetzt sind genau diese als deckende Teilmenge:

- **K2 Single/Büro** — leerer Haushalt tagsüber, rigide Routine (Worst Case Variation).
- **K3 WG/Homeoffice** — ganztags belegt, flexible Kopplung (beste Variation/Realismus).
- **K0/K1 Familie** — Mehrpersonen-Morgen-Rush; K1 zusätzlich als **Ganztags-,
  gerätereiche Schicht-Konstellation** (deckt Beschäftigung=Schicht, Zeitraum=ganze
  Woche inkl. Wochenende, Geräte=hoch ab).

Damit sind die drei stärksten Verhaltenstreiber (Soziale Struktur, Beschäftigung,
Horizont) sowie Gerätedichte und Saison über vier reale, lauffähige Konstellationen
abgedeckt. Bewusst **konstant** gehalten wurde für den kontrollierten Vergleich das
Geräteschema innerhalb der Morgen-Konstellationen (K0/K2/K3); K1 variiert es gezielt.
