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
| Voralpen-Runde (300 km) | kurz | 8,9 h | 9,4 h | 14,1 h | 100 % | 2,1 % ⚠ | 1–2 % | 0,49 |
| Hochgebirgs-Marathon (507 km) | mittel | 17,7 h | 19,4 h | 26,8 h | 97 % | 5,0 % | 4–7 % | 0,53 |
| Flachetappe Nordsee (466 km) | mittel | 13,1 h | 13,4 h | 20,5 h | 26 % | 3,8 % ⚠ | 4–7 % | 0,42 |
| Nordroute Langstrecke (1230 km) | ultra | 39,2 h | 42,2 h | 64,6 h | 17 % | 9,2 % | 8–12 % | 0,48 |

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
| Zeitfahr-Spezialist | 17,8 (0) | 21,1 (0) | 17,8 (0) | 17,4 (0) |
| Kletterer | 15,4 (0) | 11,7 (0) | 16,0 (1) | 11,2 (0) |
| Diesel / Ultra-Maschine | 16,2 (0) | 19,7 (0) | 16,3 (1) | 19,2 (1) |
| Schlafgeiziger | 17,4 (0) | 16,2 (0) | 17,2 (0) | 14,0 (0) |
| Fettverbrenner | 15,4 (0) | 15,1 (0) | 16,7 (0) | 14,7 (0) |
| Draufgänger | 16,5 (4) | 13,6 (4) | 14,7 (3) | 13,1 (4) |
| Allrounder | 15,6 (0) | 18,5 (0) | 16,0 (0) | 16,9 (0) |
| Rohdiamant | 13,8 (2) | 13,2 (2) | 12,9 (1) | 12,2 (1) |

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
| magenvertraeglichkeit | 413 s | 907 s | 389 s | 936 s | ja | -2 |
| fettverbrennung | 166 s | 503 s | 134 s | 431 s | ja | +0 |
| ausdauer | 79 s | 218 s | 62 s | 423 s | ja | +0 |
| flach | 70 s | 106 s | 118 s | 343 s | ja | +0 |
| abfahrtstechnik | 31 s | 238 s° | · | · | ja | +1 |
| navigationssicherheit | · | · | · | · | ja | +0 |
| materialpflege | · | · | · | · | ja | -1 |
| pacing_disziplin | 62 s | 172 s | 43 s | 142 s | ja | +0 |
| hitzetoleranz | · | · | 38 s° | · | ja | -1 |
| berg | 47 s | 160 s | 3 s | 80 s | ja | +0 |
| schlaftoleranz | · | · | · | 109 s | ja | +0 |
| seitenwindfestigkeit | 22 s | 31 s | 42 s | 100 s | ja | +0 |
| erfahrung | · | · | · | 98 s° | ja | +0 |
| risikobereitschaft | · | · | · | · | ja | +0 |
| sitzkomfort | · | · | · | 83 s | ja | +0 |
| hoehenanpassung | · | 60 s | · | · | ja | +0 |
| kohlenhydratverbrennung | 19 s° | 59 s° | · | · | ja | +0 |
| mechanikerfaehigkeit | 18 s | 29 s | 29 s | 51 s | ja | +0 |
| regeneration | 6 s | 27 s | 7 s | 51 s | ja | +0 |
| konstanz | · | · | · | · | ja | +0 |
| kaeltetoleranz | · | 4 s | · | · | ja | +0 |
| mentale_widerstandsfaehigkeit | · | · | · | · | ja | +0 |
| naesseresistenz | · | · | · | · | ja | +0 |
| spritzigkeit | · | · | · | · | ja | +0 |
| oberflaechenkompetenz | · | · | · | · | — | +0 |

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
| hitzetoleranz | 185 s | · | · | · |
| kaeltetoleranz | · | 14 s | · | · |
| naesseresistenz | · | · | 23 s | · |
| seitenwindfestigkeit | 21 s | 40 s | 51 s | 193 s |
| abfahrtstechnik | · | 27 s† | 20 s† | 12 s† |
| risikobereitschaft | · | · | · | · |

Ein † markiert Zahlen, die nicht über den Standardfehler, sondern
über den **Vorzeichentest** nachgewiesen sind: Das Mittel ist klein
oder von Ausreißern verzogen, aber die Paardifferenz zeigt bei fast
allen Fahrern in dieselbe Richtung.

In dieser Tabelle ist `abfahrtstechnik` bei „kalt" der Fall, für den
es die zweite Nachweisform gibt: 38 von 47 Fahrern gewinnen Zeit, im
Mittel stehen davon 27 Sekunden und im Median 15. Der Standardfehler
ist mit 41 Sekunden größer als das Mittel selbst — die Differenz sind
einzelne Fahrer, denen das Attribut nicht geholfen hat.

`risikobereitschaft` zeigt bei „kalt" ein Mittel von -66 Sekunden und
einen Median von +9: 36 von 48 Fahrern kommen schneller durch, und die
übrigen verlieren mehr, als jene gewinnen. Beides ist wahr, und
deshalb steht keine der beiden Zahlen als „die Wirkung" in der Zeile —
das Attribut ist eine Entscheidung, kein Bonus.
