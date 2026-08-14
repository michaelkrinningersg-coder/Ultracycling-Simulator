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
| Voralpen-Runde (300 km) | kurz | 8,9 h | 9,3 h | 13,8 h | 100 % | 2,1 % ⚠ | 1–2 % | 0,43 |
| Hochgebirgs-Marathon (507 km) | mittel | 17,5 h | 18,9 h | 26,0 h | 94 % | 5,0 % | 4–7 % | 0,51 |
| Nordroute Langstrecke (1230 km) | ultra | 39,1 h | 41,9 h | 62,6 h | 17 % | 9,2 % | 8–12 % | 0,44 |

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
| Zeitfahr-Spezialist | 19,9 (0) | 23,7 (0) | 21,2 (0) |
| Kletterer | 14,2 (1) | 10,3 (0) | 10,2 (2) |
| Diesel / Ultra-Maschine | 17,4 (0) | 20,7 (0) | 19,0 (1) |
| Schlafgeiziger | 16,4 (0) | 17,3 (0) | 14,1 (0) |
| Fettverbrenner | 15,4 (0) | 15,1 (0) | 14,2 (0) |
| Draufgänger | 15,5 (5) | 12,4 (5) | 11,4 (3) |
| Allrounder | 15,1 (0) | 17,4 (0) | 16,0 (0) |
| Rohdiamant | 14,2 (0) | 13,0 (1) | 12,2 (0) |

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
| magenvertraeglichkeit | 404 s | 865 s | 886 s | ja | -2 |
| fettverbrennung | 160 s | 467 s | 394 s | ja | +0 |
| ausdauer | 85 s | 208 s | 421 s | ja | +0 |
| berg | 92 s | 312 s | 161 s | ja | +0 |
| abfahrtstechnik | 33 s | 249 s° | · | ja | +1 |
| navigationssicherheit | · | · | · | ja | +0 |
| hitzetoleranz | · | · | · | ja | -1 |
| materialpflege | · | · | · | ja | -1 |
| flach | 28 s | 41 s | 119 s | ja | +0 |
| schlaftoleranz | · | · | 109 s | ja | +0 |
| seitenwindfestigkeit | 22 s | 32 s | 100 s | ja | +0 |
| erfahrung | · | · | 94 s° | ja | +0 |
| sitzkomfort | · | · | 87 s | ja | +0 |
| pacing_disziplin | · | · | -83 s° | ja | +0 |
| risikobereitschaft | · | · | · | ja | -1 |
| hoehenanpassung | · | 58 s | · | ja | +0 |
| kohlenhydratverbrennung | · | 56 s° | · | ja | +0 |
| regeneration | 6 s | 26 s | 52 s | ja | +0 |
| mechanikerfaehigkeit | 19 s | 29 s | 50 s | ja | +0 |
| konstanz | · | · | · | ja | +0 |
| kaeltetoleranz | · | · | · | ja | +0 |
| mentale_widerstandsfaehigkeit | · | · | · | ja | +0 |
| naesseresistenz | · | · | · | ja | +0 |
| spritzigkeit | · | · | · | ja | +0 |
| oberflaechenkompetenz | · | · | · | — | +0 |

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
| hitzetoleranz | 175 s | · | · | · |
| kaeltetoleranz | · | 13 s | · | · |
| naesseresistenz | · | · | 22 s | · |
| seitenwindfestigkeit | 20 s | 40 s | 51 s | 220 s |
| abfahrtstechnik | · | 24 s† | 22 s† | · |
| risikobereitschaft | · | · | · | · |

Ein † markiert Zahlen, die nicht über den Standardfehler, sondern
über den **Vorzeichentest** nachgewiesen sind: Das Mittel ist klein
oder von Ausreißern verzogen, aber die Paardifferenz zeigt bei fast
allen Fahrern in dieselbe Richtung.

In dieser Tabelle ist `abfahrtstechnik` bei „kalt" der Fall, für den
es die zweite Nachweisform gibt: 38 von 47 Fahrern gewinnen Zeit, im
Mittel stehen davon 24 Sekunden und im Median 15. Der Standardfehler
ist mit 40 Sekunden größer als das Mittel selbst — die Differenz sind
einzelne Fahrer, denen das Attribut nicht geholfen hat.

`risikobereitschaft` zeigt bei „sturm" ein Mittel von -86 Sekunden und
einen Median von +10: 33 von 48 Fahrern kommen schneller durch, und
die übrigen verlieren mehr, als jene gewinnen. Beides ist wahr, und
deshalb steht keine der beiden Zahlen als „die Wirkung" in der Zeile —
das Attribut ist eine Entscheidung, kein Bonus.
