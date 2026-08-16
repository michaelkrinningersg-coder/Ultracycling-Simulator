# Kalibrierung

Erzeugt von `python -m ultrasim.cli.calibrate`. Nicht von Hand
bearbeiten — die Datei ist eingecheckt, damit man Balancing-
Änderungen im Diff sieht.

Stand: 2026-08-16 · 6 Rennen je Strecke · Feld 40 Fahrer · Archetypen 20 je Typ mit gleichem Potenzial · Sensitivität 2 × 16 Grundfahrer, ±10 Punkte · Wetter 48 Grundfahrer

## 1 · Strecken, Dauerbänder und Ausfälle

Der Abgleich mit den beiden Ankern des Design-Dokuments: der
erwarteten Dauer (Abschnitt 2) und dem DNF-Korridor (6.5).

Das Dauerband hing bis vor kurzem an der Distanzklasse. Das ging
an den Rändern zwangsläufig schief, denn „mittel" reicht von 400
bis 1200 Äquivalentkilometern und umfasst Rennen von zwölf bis
fünfundvierzig Stunden — ein einziges Band dafür muss an beiden
Enden danebenliegen. Jetzt wird es stetig aus Distanz und
Höhenmetern gerechnet. Die Klassen bleiben, wofür sie da sind:
Split-Dichte, Schlafplanung und Rennkoeffizient.

| Strecke | Klasse | Sieger | Median | Letzter | Erwartet | Feld im Band | DNF+OTL | Ziel | Rangkorrelation |
|---|---|---|---|---|---|---|---|---|---|
| Voralpen-Runde (300 km) | kurz | 9,3 h | 9,9 h | 14,6 h | 8.4–17.2 h | 83 % | 1,2 % | 1–2 % | 0,51 |
| Hochgebirgs-Marathon (506 km) | mittel | 17,5 h | 19,3 h | 26,8 h | 15.3–31.5 h | 91 % | 4,6 % | 4–7 % | 0,58 |
| Flachetappe Nordsee (466 km) | mittel | 13,1 h | 13,4 h | 20,6 h | 11.3–23.4 h | 83 % | 4,2 % | 4–7 % | 0,47 |
| Nordroute Langstrecke (1230 km) | ultra | 39,3 h | 42,1 h | 65,0 h | 31.7–65.2 h | 85 % | 10,0 % | 8–12 % | 0,51 |

Die Rangkorrelation zwischen Potenzial und Ergebnis sagt, wie stark
sich die Attribute durchsetzen. Bei 1,0 wäre das Rennen eine
Tabellenabfrage, bei 0,0 ein Würfelspiel; dazwischen liegt der
Bereich, in dem Zuschauen lohnt.

## 2 · Archetypen

Gleich viele Fahrer je Archetyp, **identisches Potenzial-Budget** —
es unterscheidet sich nur, wie das Budget verteilt ist, und was der
Archetyp an Körperbau mitbringt. Damit misst die Tabelle nicht, wer
die besseren Fahrer bekommen hat, sondern wer zur Strecke passt.

Angegeben ist die mittlere Platzierung ± Standardfehler und in
Klammern der Anteil der Starts im besten Zehntel des Feldes.

**Zwei Zahlen, die früher hier standen, stehen bewusst nicht mehr
da.** Die Siegzahl ist die eine: Sechs Rennen ergeben sechs Sieger,
verteilt auf acht Archetypen — daraus lässt sich nichts ablesen,
egal wie groß das Feld ist. Der Standardfehler ist die andere, und
er hat gefehlt: Mit vier Fahrern je Typ lag er bei knapp zwei
Plätzen, und es wurde abgelesen, was Rauschen war. Zwei Befunde,
die auf diesem Weg entstanden sind, hat die größere Stichprobe
hinterher umgedreht. Zwei Archetypen unterscheiden sich erst dann,
wenn ihre Intervalle sich nicht überlappen.

| Archetyp | Voralpen-Runde | Hochgebirgs-Marathon | Flachetappe Nordsee | Nordroute Langstrecke |
|---|---|---|---|---|
| Zeitfahr-Spezialist | 84,9 ±3,8 (5 %) | 86,6 ±3,6 (7 %) | 74,5 ±3,9 (8 %) | 76,1 ±3,7 (9 %) |
| Kletterer | 53,2 ±3,9 (23 %) | 46,6 ±3,5 (28 %) | 65,5 ±3,8 (16 %) | 56,7 ±3,8 (20 %) |
| Diesel / Ultra-Maschine | 84,5 ±4,0 (6 %) | 88,3 ±4,1 (5 %) | 82,5 ±4,2 (8 %) | 77,6 ±4,1 (11 %) |
| Schlafgeiziger | 90,5 ±4,2 (9 %) | 89,2 ±4,2 (8 %) | 92,1 ±4,2 (8 %) | 77,3 ±4,1 (12 %) |
| Fettverbrenner | 59,5 ±3,5 (13 %) | 63,0 ±3,3 (10 %) | 63,9 ±3,9 (15 %) | 57,0 ±3,6 (13 %) |
| Draufgänger | 91,4 ±4,3 (8 %) | 87,0 ±4,3 (10 %) | 87,6 ±4,3 (10 %) | 82,4 ±4,1 (11 %) |
| Allrounder | 81,8 ±4,0 (8 %) | 75,5 ±4,1 (7 %) | 76,4 ±3,9 (7 %) | 68,5 ±3,9 (8 %) |
| Rohdiamant | 84,9 ±4,1 (9 %) | 82,7 ±4,2 (9 %) | 79,7 ±4,3 (12 %) | 80,6 ±3,8 (6 %) |

Feldgröße je Rennen: 160 Fahrer, 6 Rennen je Strecke, Neutral wäre Platz 80,5.

Die Platzierung allein wäre irreführend, denn das gleiche Budget
heißt nicht gleicher Körperbau: Ein Archetyp bringt Größe, Gewicht
und damit W/kg mit. Was jeder tatsächlich auf die Straße bringt:

| Archetyp | W/kg | FTP | Frontfläche |
|---|---|---|---|
| Zeitfahr-Spezialist | 4,26 | 295 W | 0,2560 m² |
| Kletterer | 4,48 | 291 W | 0,2423 m² |
| Diesel / Ultra-Maschine | 4,17 | 297 W | 0,2613 m² |
| Schlafgeiziger | 4,20 | 283 W | 0,2501 m² |
| Fettverbrenner | 4,27 | 307 W | 0,2624 m² |
| Draufgänger | 4,27 | 294 W | 0,2562 m² |
| Allrounder | 4,26 | 285 W | 0,2503 m² |
| Rohdiamant | 4,21 | 288 W | 0,2534 m² |

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
| magenvertraeglichkeit | 370 s | 961 s | 425 s | 980 s | ja | -2 |
| fettverbrennung | 205 s | 482 s | 156 s | 508 s | ja | +0 |
| ausdauer | 98 s | 222 s | 69 s | 391 s | ja | +0 |
| flach | 65 s | 107 s | 128 s | 334 s | ja | +0 |
| materialpflege | · | · | · | · | ja | +0 |
| abfahrtstechnik | 104 s° | 302 s° | · | · | ja | +3 |
| hitzetoleranz | · | · | 42 s° | · | ja | -1 |
| navigationssicherheit | · | · | · | · | ja | +2 |
| berg | 72 s | 182 s | 3 s | 114 s | ja | +0 |
| pacing_disziplin | 76 s | 169 s | 48 s | 146 s | ja | +0 |
| schlaftoleranz | · | · | · | 158 s° | ja | +0 |
| risikobereitschaft | · | · | · | · | ja | -3 |
| seitenwindfestigkeit | 22 s | 31 s | 44 s | 113 s | ja | +0 |
| sitzkomfort | · | 48 s | · | 88 s | ja | +0 |
| oberflaechenkompetenz | 81 s | · | · | · | ja | +0 |
| erfahrung | · | 10 s | · | 67 s° | ja | +0 |
| hoehenanpassung | · | 60 s | · | · | ja | +0 |
| regeneration | 8 s | 28 s | 6 s | 56 s | ja | +0 |
| kohlenhydratverbrennung | 23 s° | 56 s° | · | · | ja | +0 |
| konstanz | · | · | · | · | ja | +0 |
| mechanikerfaehigkeit | 25 s° | 27 s | 27 s | 35 s | ja | +0 |
| spritzigkeit | · | 29 s | · | · | ja | +0 |
| kaeltetoleranz | · | 3 s | · | · | ja | +0 |
| mentale_widerstandsfaehigkeit | · | · | · | · | ja | +0 |
| naesseresistenz | · | · | · | · | ja | +0 |

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

**In keinem Lauf messbar, obwohl als aktiv geführt:** `mentale_widerstandsfaehigkeit`, `navigationssicherheit`, `materialpflege`.
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
| hitzetoleranz | 252 s | · | · | · |
| kaeltetoleranz | · | 17 s | · | · |
| naesseresistenz | · | · | 37 s | · |
| seitenwindfestigkeit | 31 s | 40 s | 51 s | 198 s |
| abfahrtstechnik | 8 s† | 16 s† | 29 s† | · |
| risikobereitschaft | 38 s† | · | · | · |

Ein † markiert Zahlen, die nicht über den Standardfehler, sondern
über den **Vorzeichentest** nachgewiesen sind: Das Mittel ist klein
oder von Ausreißern verzogen, aber die Paardifferenz zeigt bei fast
allen Fahrern in dieselbe Richtung.

In dieser Tabelle ist `abfahrtstechnik` bei „kalt" der Fall, für den
es die zweite Nachweisform gibt: 39 von 47 Fahrern gewinnen Zeit, im
Mittel stehen davon 16 Sekunden und im Median 16. Der Standardfehler
ist mit 50 Sekunden größer als das Mittel selbst — die Differenz sind
einzelne Fahrer, denen das Attribut nicht geholfen hat.

`risikobereitschaft` zeigt bei „regen" ein Mittel von -61 Sekunden und
einen Median von +15: 29 von 46 Fahrern kommen schneller durch, und
die übrigen verlieren mehr, als jene gewinnen. Beides ist wahr, und
deshalb steht keine der beiden Zahlen als „die Wirkung" in der Zeile —
das Attribut ist eine Entscheidung, kein Bonus.
