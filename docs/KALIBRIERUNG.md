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
| Voralpen-Runde (300 km) | kurz | 9,1 h | 9,6 h | 13,9 h | 100 % | 2,1 % ⚠ | 1–2 % | 0,44 |
| Hochgebirgs-Marathon (507 km) | mittel | 17,9 h | 19,5 h | 26,4 h | 96 % | 5,0 % | 4–7 % | 0,49 |
| Nordroute Langstrecke (1230 km) | ultra | 38,6 h | 41,6 h | 60,1 h | 16 % | 8,8 % | 8–12 % | 0,44 |

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
| Zeitfahr-Spezialist | 20,4 (0) | 22,8 (0) | 21,3 (0) |
| Kletterer | 14,0 (0) | 10,1 (1) | 11,0 (1) |
| Diesel / Ultra-Maschine | 17,4 (0) | 20,9 (0) | 19,6 (1) |
| Schlafgeiziger | 16,2 (0) | 16,5 (0) | 14,8 (0) |
| Fettverbrenner | 14,8 (0) | 14,2 (0) | 13,8 (0) |
| Draufgänger | 15,8 (5) | 12,8 (4) | 12,5 (4) |
| Allrounder | 15,2 (0) | 18,2 (0) | 17,3 (0) |
| Rohdiamant | 14,4 (1) | 14,4 (1) | 12,5 (0) |

Feldgröße je Rennen: 32 Fahrer, 6 Rennen je Strecke.

Die Platzierung allein wäre irreführend, denn das gleiche Budget
heißt nicht gleicher Körperbau: Ein Archetyp bringt Größe, Gewicht
und damit W/kg mit. Was jeder tatsächlich auf die Straße bringt:

| Archetyp | W/kg | FTP | Frontfläche |
|---|---|---|---|
| Zeitfahr-Spezialist | 4,12 | 268 W | 0,2455 m² |
| Kletterer | 4,51 | 292 W | 0,2413 m² |
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
| magenvertraeglichkeit | 457 s | 1017 s | 1123 s | ja | -2 |
| fettverbrennung | 176 s | 567 s | 485 s | ja | +0 |
| ausdauer | 86 s | 244 s | 483 s | ja | +0 |
| berg | 95 s | 354 s | 223 s | ja | +0 |
| materialpflege | · | · | · | ja | -1 |
| risikobereitschaft | · | · | · | ja | +1 |
| navigationssicherheit | · | · | · | ja | +0 |
| abfahrtstechnik | · | · | · | ja | +0 |
| erfahrung | · | · | 136 s° | ja | +0 |
| flach | 24 s | 41 s | 126 s | ja | +0 |
| kaeltetoleranz | · | 73 s | 113 s | ja | +0 |
| pacing_disziplin | · | · | · | ja | +0 |
| schlaftoleranz | · | · | 101 s | ja | +0 |
| seitenwindfestigkeit | 22 s | 31 s | 93 s | ja | +0 |
| kohlenhydratverbrennung | 22 s° | 65 s° | · | ja | +0 |
| regeneration | 7 s | 31 s | 58 s | ja | +0 |
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

**In keinem Lauf messbar, obwohl als aktiv geführt:** `spritzigkeit`, `mentale_widerstandsfaehigkeit`, `pacing_disziplin`, `hitzetoleranz`, `abfahrtstechnik`, `risikobereitschaft`, `navigationssicherheit`, `materialpflege`.
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
| kaeltetoleranz | · | 145 s | 39 s | · |
| naesseresistenz | · | · | 47 s | · |
| seitenwindfestigkeit | 24 s | 55 s | 71 s | 303 s |
| abfahrtstechnik | · | · | · | · |
| risikobereitschaft | · | · | · | · |
