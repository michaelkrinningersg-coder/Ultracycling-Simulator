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
| Voralpen-Runde (300 km) | kurz | 9,4 h | 10,0 h | 14,7 h | 100 % | 1,7 % | 1–2 % | 0,48 |
| Hochgebirgs-Marathon (507 km) | mittel | 17,8 h | 19,5 h | 27,0 h | 97 % | 5,0 % | 4–7 % | 0,54 |
| Flachetappe Nordsee (466 km) | mittel | 13,2 h | 13,5 h | 20,6 h | 27 % | 3,8 % ⚠ | 4–7 % | 0,42 |
| Nordroute Langstrecke (1230 km) | ultra | 39,5 h | 42,4 h | 64,8 h | 17 % | 9,6 % | 8–12 % | 0,48 |

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

| Archetyp | Voralpen-Runde | Hochgebirgs-Marathon | Flachetappe Nordsee | Nordroute Langstrecke |
|---|---|---|---|---|
| Zeitfahr-Spezialist | 19,1 (0) | 21,1 (0) | 17,8 (0) | 17,9 (0) |
| Kletterer | 13,6 (0) | 11,7 (0) | 16,0 (1) | 11,2 (0) |
| Diesel / Ultra-Maschine | 18,1 (0) | 19,7 (0) | 16,4 (1) | 19,4 (1) |
| Schlafgeiziger | 18,2 (0) | 16,2 (0) | 17,1 (0) | 14,0 (0) |
| Fettverbrenner | 16,1 (0) | 15,1 (0) | 16,7 (0) | 15,0 (0) |
| Draufgänger | 13,1 (5) | 13,6 (4) | 14,6 (3) | 12,9 (4) |
| Allrounder | 18,3 (0) | 18,6 (0) | 16,0 (0) | 16,8 (0) |
| Rohdiamant | 12,7 (1) | 13,1 (2) | 12,9 (1) | 12,4 (1) |

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

| Attribut | Voralpen-Runde | Hochgebirgs-Marathon | Flachetappe Nordsee | Nordroute Langstrecke | wirkt | Ausfälle |
|---|---|---|---|---|---|---|
| magenvertraeglichkeit | 347 s | 928 s | 403 s | 975 s | ja | -1 |
| fettverbrennung | 187 s | 514 s | 142 s | 432 s | ja | +0 |
| ausdauer | 84 s | 222 s | 65 s | 430 s | ja | +0 |
| flach | 61 s | 107 s | 121 s | 329 s | ja | +0 |
| abfahrtstechnik | 118 s° | 238 s° | · | · | ja | +2 |
| hitzetoleranz | · | · | 39 s° | · | ja | -1 |
| materialpflege | · | · | · | · | ja | -2 |
| pacing_disziplin | 71 s | 175 s | 48 s | 146 s | ja | +0 |
| berg | 44 s | 161 s | · | 83 s | ja | +0 |
| schlaftoleranz | · | · | · | 116 s | ja | +0 |
| seitenwindfestigkeit | 21 s | 32 s | 41 s | 105 s | ja | +0 |
| erfahrung | · | 9 s | · | 98 s° | ja | +0 |
| risikobereitschaft | · | · | · | · | ja | -1 |
| sitzkomfort | · | 61 s | · | 84 s | ja | +0 |
| navigationssicherheit | · | · | · | · | ja | +0 |
| oberflaechenkompetenz | 76 s | · | · | · | ja | +0 |
| kohlenhydratverbrennung | 23 s° | 62 s° | · | · | ja | +0 |
| hoehenanpassung | · | 61 s | · | · | ja | +0 |
| regeneration | 8 s | 28 s | 6 s | 55 s | ja | +0 |
| mechanikerfaehigkeit | 20 s° | 30 s | 29 s | 55 s | ja | +0 |
| konstanz | · | · | · | · | ja | +0 |
| kaeltetoleranz | · | 5 s | · | · | ja | +0 |
| mentale_widerstandsfaehigkeit | · | · | · | · | ja | +0 |
| naesseresistenz | · | · | · | · | ja | +0 |
| spritzigkeit | · | · | · | · | ja | +0 |

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

**In keinem Lauf messbar, obwohl als aktiv geführt:** `spritzigkeit`, `mentale_widerstandsfaehigkeit`, `risikobereitschaft`, `navigationssicherheit`, `materialpflege`.
Entweder fehlt die Lage, in der das Attribut greift — dann gehört
eine Strecke oder ein Wetter in diesen Lauf —, oder es wirkt
nicht, und dann ist die Selbstauskunft der Oberfläche falsch.

## 4 · Attribute im Wetter

Dieselbe Messung auf Voralpen-Runde, aber mit erzwungenem Wetter statt
der Ziehung aus dem Seed. Ohne diesen Abschnitt bliebe die halbe
Wetterabteilung stumm: Hitzetoleranz ist an einem 16-Grad-Tag nichts
wert und Nässeresistenz auf trockener Straße auch nicht — „nicht
messbar" hieße dann fälschlich „wirkungslos".

Warum die **kürzeste** Strecke und nicht die tiefste, obwohl der
Höhengradient 6,5 K je 1000 m abzieht: Über 40 Stunden nimmt ein
Fahrer, der zwei Minuten anders unterwegs ist, andere Pannen an und
schläft in einer anderen Nacht. Die Hitzewirkung war dort mit knapp
acht Minuten die größte im ganzen Lauf — und trotzdem gingen zwölf
von 42 Paaren in die falsche Richtung. Auf 300 km sind es eins von
47. Wirkung, die man messen kann, ist mehr wert als Wirkung, die im
Chaos verschwindet.

| Attribut | hitze | kalt | regen | sturm |
|---|---|---|---|---|
| hitzetoleranz | 260 s | · | · | · |
| kaeltetoleranz | · | 15 s | · | · |
| naesseresistenz | · | · | 36 s | · |
| seitenwindfestigkeit | 20 s | 39 s | 52 s | 188 s |
| abfahrtstechnik | 37 s† | 45 s† | 58 s† | · |
| risikobereitschaft | · | · | · | · |

Ein † markiert Zahlen, die nicht über den Standardfehler, sondern
über den **Vorzeichentest** nachgewiesen sind: Das Mittel ist klein
oder von Ausreißern verzogen, aber die Paardifferenz zeigt bei fast
allen Fahrern in dieselbe Richtung.

In dieser Tabelle ist `abfahrtstechnik` bei „kalt" der Fall, für den
es die zweite Nachweisform gibt: 39 von 47 Fahrern gewinnen Zeit, im
Mittel stehen davon 45 Sekunden und im Median 14. Der Standardfehler
ist mit 45 Sekunden größer als das Mittel selbst — die Differenz sind
einzelne Fahrer, denen das Attribut nicht geholfen hat.

`risikobereitschaft` zeigt bei „regen" ein Mittel von -67 Sekunden und
einen Median von +12: 30 von 46 Fahrern kommen schneller durch, und
die übrigen verlieren mehr, als jene gewinnen. Beides ist wahr, und
deshalb steht keine der beiden Zahlen als „die Wirkung" in der Zeile —
das Attribut ist eine Entscheidung, kein Bonus.
