# Kalibrierung

Erzeugt von `python -m ultrasim.cli.calibrate`. Nicht von Hand
bearbeiten — die Datei ist eingecheckt, damit man Balancing-
Änderungen im Diff sieht.

Stand: 2026-08-14 · 6 Rennen je Strecke · Feld 40 Fahrer · Archetypen 4 je Typ mit gleichem Potenzial · Sensitivität 2 × 16 Grundfahrer, ±10 Punkte

## 1 · Strecken, Dauerbänder und Ausfälle

Der Abgleich mit den beiden Ankern, die das Design-Dokument selbst
setzt: dem Dauerband je Distanzklasse (Abschnitt 2) und dem
DNF-Korridor (Abschnitt 6.5).

| Strecke | Klasse | Sieger | Median | Letzter | Feld im Band | DNF+OTL | Ziel | Rangkorrelation |
|---|---|---|---|---|---|---|---|---|
| Voralpen-Runde (300 km) | kurz | 8,9 h | 9,6 h | 13,8 h | 100 % | 2,1 % ⚠ | 1–2 % | 0,45 |
| Hochgebirgs-Marathon (507 km) | mittel | 17,4 h | 19,3 h | 25,6 h | 97 % | 5,0 % | 4–7 % | 0,47 |
| Nordroute Langstrecke (1230 km) | ultra | 38,6 h | 42,2 h | 59,6 h | 15 % | 8,3 % | 8–12 % | 0,47 |

Die Rangkorrelation zwischen Potenzial und Ergebnis sagt, wie stark
sich die Attribute durchsetzen. Bei 1,0 wäre das Rennen eine
Tabellenabfrage, bei 0,0 ein Würfelspiel; dazwischen liegt der
Bereich, in dem Zuschauen lohnt.

## 2 · Archetypen

Gleich viele Fahrer je Archetyp, **identisches Potenzial-Budget** —
es unterscheidet sich nur, wie das Budget verteilt ist, und was der
Archetyp an Körperbau mitbringt. Damit misst die Tabelle nicht, wer
die besseren Fahrer bekommen hat, sondern wer zur Strecke passt.
Angegeben ist die mittlere Platzierung; in Klammern die Siege.

| Archetyp | Voralpen-Runde | Hochgebirgs-Marathon | Nordroute Langstrecke |
|---|---|---|---|
| Zeitfahr-Spezialist | 23,0 (0) | 25,2 (0) | 23,8 (0) |
| Kletterer | 11,0 (2) | 6,1 (4) | 7,2 (5) |
| Diesel / Ultra-Maschine | 17,4 (0) | 21,3 (0) | 19,6 (0) |
| Schlafgeiziger | 16,3 (0) | 16,8 (0) | 12,3 (0) |
| Fettverbrenner | 14,4 (0) | 14,2 (0) | 14,5 (1) |
| Draufgänger | 15,8 (4) | 13,5 (2) | 15,0 (0) |
| Allrounder | 15,6 (0) | 18,0 (0) | 17,7 (0) |
| Rohdiamant | 14,5 (0) | 14,5 (0) | 12,1 (0) |

Feldgröße je Rennen: 32 Fahrer, 6 Rennen je Strecke.

Die Platzierung allein wäre irreführend, denn das gleiche Budget
heißt nicht gleicher Körperbau: Ein Archetyp bringt Größe, Gewicht
und damit W/kg mit. Was jeder tatsächlich auf die Straße bringt:

| Archetyp | W/kg | FTP | Frontfläche |
|---|---|---|---|
| Zeitfahr-Spezialist | 4,02 | 262 W | 0,2455 m² |
| Kletterer | 4,76 | 308 W | 0,2413 m² |
| Diesel / Ultra-Maschine | 4,20 | 282 W | 0,2487 m² |
| Schlafgeiziger | 4,27 | 292 W | 0,2561 m² |
| Fettverbrenner | 4,21 | 280 W | 0,2480 m² |
| Draufgänger | 4,27 | 284 W | 0,2511 m² |
| Allrounder | 4,15 | 288 W | 0,2553 m² |
| Rohdiamant | 4,23 | 291 W | 0,2515 m² |

## 3 · Was ein Attribut wert ist

Zeitgewinn in Sekunden je **+10 Attributpunkte** — rund eine
Standardabweichung im Feld. Positiv heißt schneller. Gemessen
paarweise im selben Rennen: Jeder Grundfahrer startet zusätzlich mit
+10 und mit −10 Punkten auf genau einem Attribut, mit derselben
Fahrer-ID und damit denselben Zufallsströmen. Was an Zeit übrig
bleibt, ist das Attribut und sonst nichts.

Ein Punkt heißt **nicht messbar**: Die Wirkung liegt entweder unter
drei Sekunden oder unter dem dreifachen Standardfehler ihrer eigenen
Messung. Die zweite Hürde ist die wichtigere — ohne sie liest man
aus zwanzig Fahrern, von denen einer eine Panne hatte, eine
Attributwirkung von sieben Minuten heraus. Drei Standardfehler statt
der üblichen zwei, weil die Tabelle 75 Felder hat: Bei zwei wären
hier rechnerisch drei Fehltreffer zu erwarten, und ein Fehltreffer
ist teuer — jemand fängt an, ein Attribut zu reparieren, das nie
kaputt war.

Ein ° markiert Attribute, die über **seltene Ereignisse** wirken
statt stetig: Bei den meisten Fahrern ändert sich nichts, bei
wenigen zwanzig Minuten. Die Spalte ganz rechts zählt, wie viele
Ausfälle die starke Variante mehr hatte als die schwache — negativ
heißt, das Attribut hält Fahrer im Rennen.

| Attribut | Voralpen-Runde | Hochgebirgs-Marathon | Nordroute Langstrecke | wirkt | Ausfälle |
|---|---|---|---|---|---|
| magenvertraeglichkeit | 489 s | 1034 s | 1172 s | ja | -2 |
| fettverbrennung | 183 s | 560 s | 672 s | ja | +0 |
| ausdauer | 100 s | 248 s | 568 s | ja | +0 |
| berg | 113 s | 370 s | 318 s | ja | +0 |
| schlaftoleranz | · | · | · | ja | +0 |
| flach | 37 s | 39 s | · | ja | +0 |
| erfahrung | · | · | · | ja | +0 |
| navigationssicherheit | · | · | · | ja | +0 |
| abfahrtstechnik | · | · | · | ja | +0 |
| risikobereitschaft | · | · | · | ja | +2 |
| materialpflege | · | · | · | ja | -1 |
| kaeltetoleranz | · | 80 s | 114 s | ja | +0 |
| pacing_disziplin | · | · | · | ja | +0 |
| seitenwindfestigkeit | 21 s | 30 s | 93 s | ja | +0 |
| kohlenhydratverbrennung | 26 s° | 70 s° | · | ja | +0 |
| regeneration | 7 s | 32 s | 64 s | ja | +0 |
| konstanz | · | · | · | ja | +0 |
| mentale_widerstandsfaehigkeit | · | · | · | ja | +0 |
| naesseresistenz | · | · | · | ja | +0 |
| spritzigkeit | · | · | · | ja | +0 |
| hitzetoleranz | · | · | · | ja | +0 |
| sitzkomfort | · | · | · | — | +0 |
| mechanikerfaehigkeit | · | · | · | — | +0 |
| oberflaechenkompetenz | · | · | · | — | +0 |
| hoehenanpassung | · | · | · | — | +0 |

Die letzte Spalte ist die Selbstauskunft der Simulation:
`ACTIVE_ATTRIBUTES` sagt, welche Attribute der Code liest, und die
Oberfläche hebt genau diese im Fahrerdetail hervor. Ein Punkt in
einer Zeile mit „ja" ist deshalb kein Widerspruch, solange er nicht
in *allen* Spalten steht: Nässeresistenz wirkt an einem trockenen
Tag nicht, Schlaftoleranz nicht auf einem Rennen von acht Stunden.

Ein Attribut fehlt in dieser Tabelle grundsätzlich: **`konstanz`**
steuert allein die *Streuung* der Tagesform, und die Tagesform ist
`1 + sd·z` mit einem z, das beide Kopien eines Fahrers aus
demselben Zufallsstrom ziehen. Die Paardifferenz ist damit
proportional zu −z — bei einem Fahrer mit gutem Tag *schadet*
Konstanz, bei einem mit schlechtem hilft sie. Im Mittel stünde
dort der Stichprobenmittelwert der Zufallszahlen und nicht die
Wirkung des Attributs. Wer die messen will, braucht ein anderes
Werkzeug: den Vergleich zweier Verteilungen über viele Rennen
statt einer Paardifferenz.

**In keinem Lauf messbar, obwohl als aktiv geführt:** `spritzigkeit`, `schlaftoleranz`, `mentale_widerstandsfaehigkeit`, `pacing_disziplin`, `hitzetoleranz`, `abfahrtstechnik`, `risikobereitschaft`, `navigationssicherheit`, `erfahrung`, `materialpflege`.
Entweder fehlt die Lage, in der das Attribut greift — dann gehört
eine Strecke oder ein Wetter in diesen Lauf —, oder es wirkt
nicht, und dann ist die Selbstauskunft der Oberfläche falsch.

## 4 · Attribute im Wetter

Dieselbe Messung auf Hochgebirgs-Marathon, aber mit erzwungenem Wetter statt
der Ziehung aus dem Seed. Ohne diesen Abschnitt bliebe die halbe
Wetterabteilung stumm: Hitzetoleranz ist an einem 16-Grad-Tag nichts
wert und Nässeresistenz auf trockener Straße auch nicht — „nicht
messbar" hieße dann fälschlich „wirkungslos".

| Attribut | hitze | kalt | regen | sturm |
|---|---|---|---|---|
| hitzetoleranz | · | · | · | · |
| kaeltetoleranz | · | 153 s | 50 s | 45 s |
| naesseresistenz | · | · | 50 s | · |
| seitenwindfestigkeit | 24 s | 52 s | 63 s | 260 s |
| abfahrtstechnik | · | · | · | · |
| risikobereitschaft | · | · | · | · |
