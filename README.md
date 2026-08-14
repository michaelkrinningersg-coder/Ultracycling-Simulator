# UltraSim — Ultracycling Live Telemetry Simulator

Ein Simulator, in dem definierte Fahrer eine reale Strecke im
Einzelzeitfahren absolvieren. Der Reiz liegt nicht im Steuern, sondern im
Zuschauen und Auswerten: Eine Live-Telemetrie im Stil von
Wintersport-Übertragungen zeigt, wie sich der beobachtete Fahrer an jedem
Split gegen das Feld einordnet.

Das vollständige Konzept steht in [`docs/GAME_DESIGN.md`](docs/GAME_DESIGN.md).
Dieses README beschreibt, was davon gebaut ist und wie man es benutzt.

---

## Stand: Meilensteine M1–M8, Editoren (M5b) und Karrieremodus

Das Design-Dokument gliedert die Umsetzung in acht Meilensteine und
definiert in Abschnitt 16 den Umfang der ersten Fassung. Genau der ist
hier umgesetzt.

**Fertig und wirksam**

| Bereich | Was drinsteckt |
|---|---|
| GPX-Import (M1) | Namespace-tolerantes Parsen, Duplikatentfernung, Höheninterpolation, Resampling auf 10 m, Savitzky-Golay-Glättung, Segmentierung, Anstiegserkennung mit Kategorien, Splits und Servicepunkte, gzip-JSON |
| Physik (M2) | Roll-, Steigungs-, Luft- und Beschleunigungswiderstand, Euler-Integration mit 1 s Tick, höhenabhängige Luftdichte, Abfahrtslogik mit Trittfrequenzgrenze und Kurvenlimit, CdA aus Körpermaßen. Der Rollwiderstand hängt an Oberfläche, Reifen, Tempo und Systemmasse — inklusive Impedanz, also dem Anteil, der als Schwingung verlorengeht |
| Fahrer (M3) | Generator mit acht Archetypen und Potenzial-Budget, 25 Attribute, Saison-/Tages-/Abschnittsform (OU-Prozess), W′ und Langzeitermüdung, Team-Attribut Servicedisziplin |
| Strategie | Rennplan je Fahrer: Ziel-Intensität aus der Distanz, Anstiegs-Aufschlag, Radwahl je Abschnitt zwischen Servicepunkten und Anstiegen, mit Wirtschaftlichkeitsprüfung — jede Entscheidung mit Begründung protokolliert |
| Rennen (M3) | Vektorisiert über das ganze Feld, Einzelstart, Splitzeiten mit Sub-Tick-Interpolation, Ereignis-Strom, quantisierte Telemetrie |
| Oberfläche (M4) | Höhenprofil-Canvas mit Übersicht und Ausschnitt, Telemetrie-Board mit 41-Zeilen-Fenster, virtuelle Rangliste, Ticker, Playback-Server mit sieben Zeitrafferstufen (1×, 5×, 10×, 30×, 60×, 300×, 1000×), Ergebnisliste, Fahrerdetail mit Verlaufskurven. Uhr *und* Rückstand zählen zwischen zwei Frames mit, statt im Takt der Frames zu springen; eine eigene Spalte zeigt die Meter bis zur nächsten Zeitmessung |
| Zustände (M5.1) | Zustandssystem aus Abschnitt 6.5: multiplikative Modifikatoren auf FTP, Abfahrtstempo, Rollwiderstand und Energieaufnahme, verankert wahlweise in Zeit oder Distanz, mit linearem oder hartem Abklingen. Erster Erzeuger ist die Fehlplanung — der zu ambitionierte Plan schlägt spät zurück. Sichtbar als Balken über dem Profil, Chip in der Board-Zeile und Eintrag im Ticker |
| Energie (M5.2) | Glykogenspeicher, Substratverteilung nach Intensität, Zufuhr gedeckelt durch KH-Verbrennung *und* Magenverträglichkeit, Hungerast unter 15 % Füllstand. Der Rennplan rechnet vorab aus, welche Intensität die Zufuhr über die Distanz trägt, und nimmt das Minimum aus Distanz- und Energiegrenze |
| Servicestopps (M5.2) | Halt an jedem Servicepunkt, Kurz- oder Vollservice je nach Zeit seit dem letzten großen Halt, Dauer × Servicedisziplin des Teams. Radwechsel läuft parallel statt zusätzlich |
| Schlaf (M5.3) | Schlafdruck gegen einen persönlichen Wachhorizont (30–50 h), zirkadianer Tiefpunkt zwischen 02:00 und 05:00 Fahrer-Eigenzeit, geplante Schlafstopps am Servicepunkt, Notschlaf am Straßenrand ab kritischem Druck, Schlafgüte aus Regeneration mit Nachwirkung bei schlechtem Schlaf |
| Wetter (M6.1) | Zweischichtiges Modell: die Ortsschicht (Höhe, Exposition, lokaler Wind) hängt an der Position, die Zeitschicht (Tagesgang, Sonnenstand, Regenphasen) an der Fahrer-Eigenzeit. Wind wirkt richtungsabhängig aus Segment-Peilung und Windrichtung, Seitenwind über die Frontfläche. Dazu Hydration mit Schweißrate aus Intensität, Temperatur und Luftfeuchte |
| Zwischenfälle (M6.2) | Der Ereigniskatalog aus Abschnitt 6.5: Panne, mechanischer Defekt, Lichtausfall, Verfahren, Sturz, Magenprobleme, Hitzeeinbruch, Sperrung. Gezogen als Poisson-Prozess entlang der Strecke, angenommen erst beim Erreichen — so gehen Nässe, Dunkelheit und Müdigkeit ein, ohne dass pro Tick gewürfelt wird |
| Aufgabe (M6.2) | Vier Wege zum DNF: schwerer Sturz, schwerer Defekt ohne Ersatz, Zeitlimit und ein kumulativer Aufgabe-Score aus verlorener Zeit × Ermüdung × Magenzustand, gedämpft durch mentale Widerstandsfähigkeit |
| Saison (M7) | Kalender mit Terminen, Startfeld, Wetter und Seed je Rennen; Punkte nach Platzierung × Rennkoeffizient aus Länge und Höhenmetern; Gesamtrangliste mit dreistufigem Tiebreak (Punkte, Siege, bessere Einzelplatzierung) |
| Kalender-Editor (M7) | Der erste Editor im Browser: Saison anlegen, Termine hinzufügen, verschieben und löschen, Rennen einzeln oder am Stück rechnen lassen. Die Rechnung läuft im Hintergrund mit Fortschrittsanzeige — ein Ultra dauert Minuten, dafür gibt es keinen Request |
| Restermüdung (M7) | Ein Rennen wirkt ins nächste: Die Rennarbeit klingt exponentiell ab (Zeitkonstante aus dem Attribut Regeneration) und wirkt über zwei Wege — als bereits geleistete Arbeit im Ermüdungszähler und als Frischefaktor auf die haltbare Leistung |
| Fahrerentwicklung (M7) | Beim Saisonwechsel altern alle Fahrer: Leistungskurve nach Alter mit Scheitel um 31, Erfahrung wächst mit Rennen und Kilometern, Potenzial driftet, Rücktritte ab 34 mit Nachwuchs als Ersatz |
| Streckeneditor (M5b) | GPX-Upload im Browser mit Vorschau: Distanz, Höhenmeter geglättet *und* ungeglättet, erkannte Anstiege, abgeleitete Distanzklasse. Splits und Servicepunkte per Drag im Höhenprofil verschiebbar, dazu Tabelle mit Kilometerfeld, Art und Hinzufügen/Löschen. Auf die Platte geht der Import erst, wenn man ihn dort speichert |
| Fahrer- und Team-Editor (M5b) | Feldtabelle mit Filter nach Name, Team und Archetyp; Fahrerdetail mit allen 25 Attributen als Schieberegler und mitlaufender Potenzial-Budget-Anzeige; Nachgenerieren mit Archetyp, Anzahl und Zielpotenzial; Teams mit Name, Nation, Farbe und Servicedisziplin |
| Regelkreis (M7b) | Das Strategiemodul der zweiten Stufe aus Abschnitt 7.2: Sparmodus bei leerem Glykogenspeicher, Hitzemodus, Aufholjagd bei Rückstand auf den eigenen Plan, vorgezogener Schlafstopp. Jede Regel mit getrennter Ein- und Ausschaltschwelle, jede Entscheidung mit Begründung im Ereignisstrom und als Chip in der Board-Zeile |
| Kalibrierung (M8) | Ein eingecheckter Bericht statt Konsolenausgabe: Dauerbänder und DNF-Korridor je Strecke, Siegverteilung nach Archetyp bei identischem Potenzial-Budget, und eine Matrix, was jedes der 25 Attribute auf jeder Strecke in Sekunden wert ist. Dazu ein zweiter Golden Master über 1000 km, der Schlaf, Notschlaf und Aufgabe abdeckt |
| Karriere | Saisons in Folge mit gemeinsamem Fahrerpool. Der Jahreswechsel friert erst die Wertung als Kapitel ein und lässt dann altern — umgekehrt stünde in der ewigen Bestenliste das Feld des Folgejahres. Der Kalender wird ins nächste Jahr übernommen statt neu vorgeschlagen: Dieselben Rennen an denselben Terminen machen die Bestenliste erst lesbar. Dazu ewige Bestenliste (Titel vor Punkten) und Lebenslauf je Fahrer |
| Kalenderansicht | Jahresband mit dem Erholungsfenster hinter jedem Termin: so lange braucht ein durchschnittlicher Fahrer, bis er wieder bei 98 % Frische ist. Wo der nächste Punkt noch im Balken liegt, startet das Feld angeschlagen — solche Termine sind rot. Gerechnete Rennen liefern die gemessene Arbeit, die übrigen eine Schätzung aus 15 kJ je flachem Kilometer |
| Auswertung | Warum-Panel: die Form in ihre Faktoren zerlegt, der teuerste zuerst — die Simulation zeichnet Abschnittsform, Ermüdung, Zustände, Hungerast, Schlaf, Wetter und Flüssigkeit als eigene Kanäle auf. Splitzeiten-Matrix Fahrer × Marke mit Rangfarbe, und ein Rennbericht in einem Satz je Fahrer aus Ereignissen und Spliträngen |
| Tote Attribute | Der Kalibrierungsbericht hat sechs Attribute mit einer Null ausgewiesen; fünf haben jetzt eine Mechanik. Sitzbeschwerden ab zwölf Stunden im Sattel, Standzeit nach Panne aus der Mechanikerfähigkeit, Leistungsverlust über 1500 m, ein Kurvenlimit, das in Kehren wirklich bindet, und eine Wettermessung, die nicht mehr an der Chaosempfindlichkeit einer 40-Stunden-Strecke scheitert. Dazu ein Vorzeichentest als zweite Nachweisform für Attribute, deren Wirkung von Ausreißern verzogen wird. Dazu der Attribut-Tuner im Fahrerdetail: zwei Regler, ein Klick, beide Versionen des Fahrers starten im selben Rennen |
| Werkzeuge | CLI für Pool, Rennen, Ergebnis, Fahrerdetail, Saison und Kalibrierung, Balancing-Batch mit Abgleich gegen Dauerbänder und DNF-Korridor, 517 Tests inklusive zweier Golden-Master |

**Bewusst gestrichen**: die Highlight-Automatik aus M7b — der Ticker
meldet ohnehin jedes größere Ereignis, und eine automatische Auswahl
„sehenswerter“ Momente würde in einem Einzelzeitfahren ohne
Kameraführung nichts hinzufügen, was die Ereignisliste nicht schon
zeigt. Ebenso der Abgleich mit realen Ultra-Ergebnissen aus M8: Für die
großen Rennen liegen die Strecken nicht als GPX vor, und eine
Kalibrierung gegen nachgebaute Profile misst am Ende den
Profilgenerator.

**Erledigt**: `oberflaechenkompetenz` war lange das letzte Attribut ohne
Wirkung — siehe „Der Rollwiderstand war eine Konstante" weiter unten.

### Eine Karriere ist eine Kette eingefrorener Jahre

Der Jahreswechsel ist die einzige Aktion im ganzen Programm, die
bestehende Daten überschreibt: Danach ist jeder Fahrer ein Jahr älter,
einige sind zurückgetreten, Nachwuchs ist nachgerückt. Deshalb friert er
**vorher** die Wertung als Kapitel ein.

Das klingt nach Redundanz — die Rennergebnisse liegen doch unverändert
auf der Platte — ist aber keine. Die Wertung von 2031 wird aus den
Rennen *und dem Feld* gebildet, und das Feld von 2035 ist ein anderes:
Wer 2032 zurückgetreten ist, steht nicht mehr darin, und aus dem
Rohdiamanten ist inzwischen jemand anderes geworden. Ohne die
Momentaufnahme wäre die Tabelle von 2031 nach dem dritten Jahreswechsel
nicht mehr rekonstruierbar. Umgekehrt speichert die *laufende* Saison
hier gar nichts: Ihre Wertung entsteht bei jedem Aufruf neu aus den
gerechneten Rennen, und die sind unveränderlich.

Die ewige Bestenliste sortiert nach **Titeln vor Punkten**. Punkte
allein wären ungerecht gegenüber kurzen Karrieren: Wer zehn Jahre im
Mittelfeld fährt, sammelt mehr als der Fahrer mit zwei Titeln und einem
frühen Rücktritt. In einer Bestenliste zählt, was man gewonnen hat.

Der Kalender wandert ins nächste Jahr, statt neu vorgeschlagen zu
werden — dieselben Rennen an denselben Terminen, nur mit anderem Seed
und damit anderem Wetter. Genau das macht die Bestenliste lesbar: Wer
den Hochgebirgs-Marathon dreimal gewonnen hat, hat dreimal dasselbe
gewonnen.

### Ein gerechnetes Rennen ist unveränderlich

Sobald es Editoren gibt, wird das zur Frage: Was passiert mit dem Rennen
vom letzten Mai, wenn heute ein Split von km 40 auf km 45 wandert?
Nichts. Jedes Rennen legt beim Rechnen eine Kopie seiner Strecke im
eigenen Verzeichnis ab und trägt seine Fahrer ohnehin schon als Kopie
bei sich. Der Editor ist dadurch völlig frei — ohne die Kopie stünde die
Zeit von km 40 unter dem Namen „km 45", und beim Löschen eines Splits
passte nicht einmal mehr die Spaltenzahl der Splitzeiten. 150 kB je
Rennen neben zweistelligen Megabyte Telemetrie sind dafür ein
angemessener Preis.

Was gerade wirkt, steht offen in der Oberfläche: Das Fahrerdetail zeigt
alle 25 Attribute, aber nur die 24, die tatsächlich in die Simulation
eingreifen, sind hell hervorgehoben. Ein Test hält diese Liste ehrlich —
er vergleicht sie mit dem, was der Code liest, und schlägt in beide
Richtungen an. Genau dieser Test hat die fünf Mechaniken unten erzwungen:
Er wurde rot, als sie dazukamen, weil die Liste noch die alte war.

### DNF-Korridor

Abschnitt 6.5 nennt 1–2 % für die kurze, 4–7 % für die mittlere und
8–12 % für die Ultraklasse. Gemessen über je 480 Starts:

| Strecke | Klasse | DNF | Ziel |
|---|---|---|---|
| Voralpen-Runde, 300 km | kurz | 1,2 % | 1–2 % |
| Hochgebirgs-Marathon, 507 km | mittel | 3,5 % | 4–7 % |
| Nordroute, 1230 km | ultra | 10,0 % | 8–12 % |

Zwei der drei Klassen liegen mittig im Band, die mittlere 0,5 Punkte
darunter. Das ist kein Kalibrierungsfehler, sondern die Form des
Korridors: Er springt bei 400 km und bei 1200 km stufenweise nach oben.
Unsere mittlere Strecke liegt mit 507 km am unteren Rand ihrer Klasse
und dauert 17 Stunden — ein 1100-km-Rennen derselben Klasse dauert
dreimal so lang und landet weit oben im Band. Pro Rennstunde verlangt
der Korridor in seiner Mitte 0,15, 0,32 und 0,28 Prozentpunkte; er ist
damit in der Dauer nicht monoton und mit einem einzigen Regler an den
Klassengrenzen nicht überall gleichzeitig zu treffen. Nachgemessen: Den
Regler um 18 % anzuheben verschiebt die Ultraklasse von 10,0 auf 10,8 %
und die mittlere um keinen einzigen Fahrer — dort ist schlicht niemand
nah genug an der Schwelle. Das Balancing-Werkzeug schreibt diese
Begründung mit aus, statt eine grüne Zahl zu behaupten.

### Der Regelkreis macht aus Attributen Persönlichkeit

Bis M7a fuhr jeder Fahrer seinen Rennplan zu Ende, egal was um ihn
herum passierte. Der Regelkreis aus Abschnitt 7.2 prüft alle zehn
Sekunden vier Lagen und verschiebt die Zielintensität um −10 %
(Sparmodus, wenn der Glykogenspeicher unter ein Viertel fällt), −6 %
(Hitzemodus), +7 % (Aufholjagd) oder −3 % (geplanter Schlaf), auf
zusammen höchstens −18 % bis +12 %.

Zwei Dinge halten das ruhig. Erstens hat jede Regel **getrennte Ein-
und Ausschaltschwellen** — Sparmodus geht bei 25 % Speicher an und
erst bei 35 % wieder aus. Ohne diese Hysterese flackert eine Regel im
Sekundentakt, sobald ein Fahrer genau auf der Schwelle fährt, und das
Board wäre ein Stroboskop. Zweitens skaliert das Befolgen mit der
Persönlichkeit: Schutzregeln folgt jeder, aber ein Fahrer mit hoher
Pacing-Disziplin folgt ihnen vollständig, ein undisziplinierter nur
zur Hälfte. Bei der riskanten Regel ist es umgekehrt — wer
undiszipliniert *und* mental fragil ist, geht mit anderthalbfacher
Härte in die Aufholjagd, wer diszipliniert ist, praktisch gar nicht.

Nachgemessen über ein Ultra-Feld: Die Fahrer, die in die Aufholjagd
gehen, haben im Schnitt Pacing-Disziplin 48, das Gesamtfeld 56. Der
Regler ist damit nicht nur vorhanden, sondern sortiert das Feld auch
in die Richtung, die das Design-Dokument beschreibt. Der Rückstand
misst sich dabei gegen die **geplante** Fahrzeit, nicht gegen die
verstrichene — sonst löst eine Straßensperrung bei km 5 eine Panik
aus, obwohl noch 1200 km zum Aufholen bleiben.

Jede Entscheidung landet als Ereignis mit Begründung im Strom
(Abschnitt 7.3), erscheint im Ticker und als Chip in der Board-Zeile
des Fahrers.

---

## Schnellstart

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# 1. Fahrerpool erzeugen (250 Fahrer in ~31 Teams)
python -m ultrasim.cli.simulate pool --riders 250

# 2. Ein Rennen rechnen
python -m ultrasim.cli.simulate race voralpen-runde --riders 40 --seed 42

# 3. Zuschauen
python -m ultrasim.web.main --open
```

Oder gleich eine ganze Saison — Kalender im Browser unter
`/seasons`, dieselben Schritte auf der Kommandozeile:

```bash
python -m ultrasim.cli.season new 2027 --name Weltserie --races 10
python -m ultrasim.cli.season run 2027-weltserie --all
python -m ultrasim.cli.season show 2027-weltserie      # Kalender + Gesamtwertung
python -m ultrasim.cli.season close 2027-weltserie     # Fahrer altern lassen
```

Vier Strecken liegen bei:

| ID | Distanz | Höhenmeter | je km | Klasse |
|---|---|---|---|---|
| `voralpen-runde` | 300,5 km | 2674 m | 8,9 m | kurz |
| `hochgebirgs-marathon` | 507,0 km | 6790 m | 13,4 m | mittel |
| `flachetappe-nordsee` | 466,0 km | 1075 m | **2,3 m** | mittel |
| `nordroute-langstrecke` | 1230,0 km | 6120 m | 5,0 m | ultra |

Zwei der Klasse „mittel" ist Absicht. Der Hochgebirgs-Marathon und die
Flachetappe sind fast gleich lang und in jeder anderen Hinsicht
Gegenpole — 13,4 gegen 2,3 Höhenmeter je Kilometer. Nebeneinander in
derselben Zeile sagt die Sensitivitätsmatrix damit nicht nur, was ein
Attribut wert ist, sondern *wofür*. Die Flachetappe kam dazu, weil die
„flachste" Strecke vorher bei 5,0 m/km lag — das ist welliges Land, kein
Zeitfahrterrain.

> Diese vier sind **synthetisch erzeugt**, nicht real: Sie entstehen aus
> `tools/make_demo_gpx.py` und dienen dazu, die Importkette und das Spiel
> ohne Netz und ohne fremde Kartendaten lauffähig zu halten. Jede echte
> GPX-Datei aus komoot, BRouter, Strava oder einer GPS-Aufzeichnung
> funktioniert genauso.
>
> Eingecheckt sind nur die fertigen Streckendateien (rund 460 kB) — die
> GPX-Quellen wären 5 MB, die aus einem Seed in einer Sekunde neu
> entstehen:
>
> ```bash
> python tools/make_demo_gpx.py --all
> python -m ultrasim.geo.gpx_import data/gpx/demo-voralpen.gpx --name "Voralpen-Runde"
> ```

### Eigene Strecke importieren

Im Browser unter `/routes` per Datei-Auswahl — oder auf der Kommandozeile:

```bash
python -m ultrasim.geo.gpx_import meine-strecke.gpx --name "Meine Strecke"
```

Der Importer schreibt nach `data/routes/` und berichtet, was er gefunden
hat — darunter der Vergleich mit und ohne Glättung:

```
Distanz:            300.5 km
Distanzklasse:      kurz
Höhenmeter:         3114 m (ungeglättet wären es 4569 m)
Ø |Steigung|:       0.81 % (ungeglättet 4.14 %)
Anstiege:           3
Splits:             30
```

Die zweite Spalte ist der Grund, warum Abschnitt 3.3 des Design-Dokuments
die Glättung für nicht verhandelbar erklärt: Ohne sie träte das Feld im
Flachen dauerhaft gegen eine scheinbare 4-%-Steigung an, und die
Höhenmeter wären um die Hälfte überzeichnet.

### Weitere Befehle

```bash
python -m ultrasim.cli.simulate list                      # Strecken und Rennen
python -m ultrasim.cli.simulate result voralpen-runde-42  # Ergebnisliste
python -m ultrasim.cli.simulate rider  voralpen-runde-42 --bib 29
python -m ultrasim.cli.balance --route voralpen-runde --runs 20

python -m ultrasim.cli.season new 2027 --races 10        # Saison anlegen
python -m ultrasim.cli.season run 2027-weltserie --all   # Kalender rechnen
python -m ultrasim.cli.season show 2027-weltserie        # Wertung ansehen
python -m ultrasim.cli.season close 2027-weltserie       # Saisonwechsel
```

`rider` zeigt den Rennplan mit Begründung, alle Splits mit Rang und den
Ereignisverlauf — der schnellste Weg, ein Rennen zu verstehen, ohne die
Oberfläche zu starten.

---

## Was beim Zuschauen passiert

Das Rennen ist beim Öffnen der Seite bereits vollständig durchgerechnet.
Ein Playback-Server streamt daraus per Server-Sent Events mit einer
eigenen Wanduhr. Das fühlt sich nicht nur wie live an, es kann mehr:
Pause, Zeitraffer bis 1000×, Rücksprung, Sprung zum nächsten Split oder
zum nächsten Ereignis des Fokusfahrers.

Die entscheidende Selbstbeschränkung dabei: **Der Client sieht nie Daten
aus der Zukunft.** Die Uhr gehört dem Server, jede Abfrage wird an ihr
abgeschnitten, und ein Client, der eine spätere Zeit anfragt, bekommt
trotzdem nur die Gegenwart. Ohne das würde ein Bug die Endzeiten
verraten und die ganze Dramaturgie zerstören — `tests/test_playback.py`
prüft es deshalb ausdrücklich.

Auf dem Board steht ein Fahrer, der den gewählten Split noch nicht
erreicht hat, mit seiner **laufenden Uhr** — der Zeit seit seinem Start
— und rankt sich damit zwischen die gemessenen Zeiten, kursiv und ohne
Platzziffer. Mit jeder Sekunde, die seine Uhr über eine bestehende Zeit
hinauswandert, rutscht er einen Platz nach hinten. Das ist die
Zeitnahme aus dem Wintersport, und sie ist der Grund, warum das Board
sich lohnt: Vorher stand dort eine Hochrechnung aus Tempo und
Reststrecke — treffsicherer, aber sie behauptete etwas über die
Zukunft. Die laufende Uhr behauptet nichts, und die Spannung entsteht
aus dem Zusehen statt aus der Rechnung.

Ein Aufgeber behält seine stehende Uhr, statt langsam durch das ganze
Board nach unten zu wandern.

Bei hohem Zeitraffer schickt der Server nur einen Frame je Sekunde — die
gefahrene Zeit sprang damit in Blöcken von bis zu tausend Sekunden.
Zwischen zwei Frames zählt der Client sie deshalb selbst weiter,
gedeckelt auf den nächsten erwarteten Frame, damit sich die Anzeige nie
sichtbar rückwärts korrigiert. Gerechnet wird im Client trotzdem nichts:
Positionen, Rangfolge und Ereignisse kommen unverändert vom Server.

Über allem läuft ein **Ereignis-Laufband** mit den letzten zehn
Meldungen — Splits, Bestzeiten, Defekte, Schlafstopps, Aufgaben.
Bestzeiten sind dabei kein Vorgang auf der Straße, sondern einer in der
Zeitnahme: Sie entstehen erst dadurch, dass die Zeiten in der
Reihenfolge eintreffen, in der gestartet wurde. Erzeugt werden sie
deshalb in der Playback-Schicht, nicht in der Simulation.

Wer gerade eine taktische Entscheidung getroffen hat, trägt sie als
Chip neben seinem Namen — „Aufholjagd“, „Sparmodus“, „Hitzemodus“ —
solange die Regel greift, und nicht länger: Bei Aufgabe oder Zieleinlauf
friert die Zeile ein, statt einen Fahrer weiter taktieren zu lassen, der
längst nicht mehr auf der Strecke ist.

Die Ergebnis- und Detailseiten sind Nachbetrachtungs-Screens und
verraten den Ausgang; sie sind entsprechend zurückhaltend verlinkt.

---

## Aufbau

```
ultrasim/
  core/     physics · rider · form · fatigue · nutrition · sleep · conditions
            weather · incidents · strategy · tactics · season · development
            career · events · engine
  geo/      gpx_import · smoothing · segmentation · splits · route
  data/     store          (Dateiablage: JSON für Stammdaten, npz für Telemetrie)
  calibration.py           Messungen *an* der Simulation: Dauerband, DNF,
                           Archetypen, Attribut-Sensitivität
  season_runner.py         Dienstschicht: Kalender rechnen, werten, altern
  career_runner.py         Jahre verketten: Wertung einfrieren, altern,
                           Folgejahr eröffnen
  web/      main · playback · jobs · routers/ · templates/ · static/
            routers: pages · routes (Streckeneditor) · pool (Fahrer, Teams)
                     seasons (Kalender) · careers (Karriere) · api (Board, SSE)
  cli/      simulate · balance · calibrate · season
  app.py    Startlogik der ausgelieferten Anwendung
tools/      make_demo_gpx.py
docs/       GAME_DESIGN.md · KALIBRIERUNG.md (erzeugt, eingecheckt)
tests/      geo · core · engine · conditions · nutrition · sleep · weather
            incidents · season · season_web · editors · tactics
            calibration · career · career_web · cli_console
            playback · golden_master
data/
  gpx/      Quelldateien der mitgelieferten Strecken
  routes/   importierte Strecken (gzip-JSON, eingecheckt)
  races/    gerechnete Rennen (erzeugt, nicht eingecheckt)
  seasons/  Kalender und Wertung (erzeugt, nicht eingecheckt)
  careers/  Karriereakten mit den Kapiteln abgeschlossener Jahre
  gpx/      hochgeladene Quelldateien (erzeugt, nicht eingecheckt)
```

Architekturprinzip aus Abschnitt 13: **Die Simulation ist eine reine
Bibliothek ohne Web-Abhängigkeit.** `ultrasim/core/` erzeugt aus einer
Renn-Konfiguration ein Ergebnis samt Event-Strom; Web-App und CLI sind
nur zwei Konsumenten davon. Deshalb laufen Balancing-Batches ohne
Browser.

Mit der Saison kam eine Schicht dazu. Einen Kalendertermin zu rechnen
heißt: Feld laden, Restermüdung aus früheren Rennen holen, simulieren,
ablegen, Kalender fortschreiben — das braucht `core` *und* `data`. In
`core` gehört es nicht (dann liefe die Simulation nicht mehr ohne
Datenverzeichnis), in `cli` oder `web` auch nicht (dann gäbe es den
Ablauf zweimal). Deshalb sitzt er in `season_runner.py` dazwischen, und
Browser wie Kommandozeile rufen dieselben Funktionen auf.

### Zwei bewusste Abweichungen vom Design-Dokument

1. **Kein SQLAlchemy/SQLite.** Abschnitt 13 sieht für die Stammdaten
   SQLAlchemy vor. Auch mit Saison und Kalender bleibt es bei Dateien:
   Eine Saison ist eine Liste von zwanzig Terminen, keine Tabelle mit
   Millionen Zeilen, und die einzige Verknüpfung ist der Rennschlüssel.
   Dafür eine Datenbank aufzumachen kostet Startzeit und Bundle-Größe,
   ohne eine einzige Abfrage zu vereinfachen. Alle Zugriffe laufen über
   `ultrasim/data/store.py`, damit der Wechsel ein einzelner Austausch
   bleibt, falls er je nötig wird.

2. **Der Radplan kam vorgezogen.** Er stand in der Roadmap erst bei M6,
   ist aber Teil des Rennplans aus Abschnitt 7.1 und mit der
   Wirtschaftlichkeitsprüfung aus 6.4 in wenigen Zeilen zu haben.

   Wo ein Abschnitt endet, war dabei die eigentliche Frage. Zuerst waren
   das nur die Servicepunkte — und damit fuhr das Feld auch über die
   Pässe im Zeitfahrrad. Nicht weil die Physik falsch war: Über 10 km
   bei 8 % ist das Straßenrad 161 Sekunden schneller. Sondern weil auf
   507 km fünf Servicepunkte liegen, ein Abschnitt also 90 km lang ist
   und darin 80 % Flachland stecken. Über die Summe gewann das
   Zeitfahrrad um zwei Minuten, und der Fahrer quälte sich damit über
   jeden Berg.

   Jetzt sind auch **Fuß und Kuppe jedes Anstiegs über 4 km mit
   mindestens 3 %** Abschnittsgrenzen — im unterstützten Rennen fährt
   das Begleitfahrzeug mit, und genau dort steht es. Ein Servicepunkt
   entsteht daraus ausdrücklich *nicht*: Der zöge einen Halt nach sich,
   und dann hielte das Feld an jedem Berg an, auch wenn es nichts zu
   wechseln gibt. Ob gewechselt wird, entscheidet weiter die Rechnung,
   und die muss den Wechsel selbst tragen — ein Abschnitt mit 50 %
   Steilanteil, auf dem das Straßenrad 53 Sekunden gutmacht, ist bei
   60 Sekunden Wechselkosten kein Grund abzusteigen. Das Ergebnis auf
   allen drei Strecken: jedes Steilstück auf dem Straßenrad, jeder
   Flachabschnitt im Zeitfahrrad.

---

## Kalibrierung und Balancing

Seit M5.2 setzt nicht mehr allein die Distanzformel aus Abschnitt 7.1
das Tempo, sondern der Energiehaushalt: Der Rennplan nimmt das Minimum
aus gewünschter und energetisch tragbarer Intensität. Das verschiebt die
Zeiten dorthin, wo sie physiologisch hingehören, statt an einer Formel zu
drehen.

Der Effekt fällt anders aus, als man zunächst vermutet — er ist auf
**mittleren** Distanzen am größten:

| Strecke | vor M5.2 | nach M5.2 | Ziel-IF | warum |
|---|---|---|---|---|
| 300 km | 8:17 h (36,2 km/h) | 8:48 h (34,1 km/h) | 78 % → **70 %** | hohe Intensität, aber lang genug, um den Speicher zu leeren |
| 1230 km | 33:52 h (36,3 km/h) | 35:55 h (34,2 km/h) | 65 % → 64 % | Deckel bindet kaum, die 32 min Standzeit machen den Unterschied |

Auf 300 km fällt der Glykogenspeicher des Siegers auf 17 % — knapp am
Hungerast vorbei, genau die Dramaturgie, die Abschnitt 6.1 beschreibt.
Auf 1230 km bleiben 60 % übrig: Über 34 Stunden ist die geplante
Speicherentnahme so dünn verteilt, dass praktisch die Zufuhr allein zählt.

### Schlaf greift bewusst spät

34 Stunden ohne Schlaf sind im Ultracycling normal. Der Malus ist
deshalb bis rund 60 % des persönlichen Wachhorizonts **exakt null** und
steigt erst danach:

| Wachzeit | Uhrzeit (Eigenzeit) | Leistung |
|---|---|---|
| 12 h | 20:00 | 100 % |
| 20 h | 03:30, erste Nacht | 97,8 % |
| 34 h | 18:00 | 96,2 % |
| 40 h | 03:30, zweite Nacht | 72,2 % |
| 48 h | 03:30 | Notschlaf erzwungen |

Weh tut nicht die erste Nacht, sondern die zweite — dann treffen ein
hoher Grundwert und der zirkadiane Tiefpunkt aufeinander. Auf der
1230-km-Strecke plant der Sieger folgerichtig **keinen** Schlafstopp,
langsamere Fahrer im selben Rennen schon.

### Ein Ultra kostet drei bis vier Wochen

Die Restermüdung entscheidet, ob ein Kalender eine Planungsaufgabe ist
oder Dekoration. Gemessen auf der 300-km-Strecke, jeweils dieselbe
Startliste und derselbe Seed, nur der Abstand zum vorherigen 1230er
unterscheidet sich:

| Abstand | Frische beim Start | Zeitverlust |
|---|---|---|
| 7 Tage | 87 % | +11 % |
| 14 Tage | 94 % | +4 % |
| 21 Tage | 97 % | +1,6 % |
| 28 Tage | 98 % | +0,7 % |

Der Weg dahin ist die interessantere Geschichte. Naheliegend wäre, die
Restarbeit einfach in den Ermüdungszähler einzusetzen: Wer mit 5.000 kJ
Rückstand startet, ist so müde, als lägen die ersten 5.000 kJ schon
hinter ihm — eine Größe, eine Kurve, keine zweite Kalibrierung. Genau so
war es zuerst gebaut, und gemessen kostete eine Woche nach einem Ultra
ganze **3 %**. Der Effekt wäscht sich über die Renndistanz aus: Am Ende
stehen 30.000 statt 22.000 kJ auf dem Zähler, und dort ist die
Ermüdungskurve längst flach.

Physiologisch ist die Auswaschung auch falsch. Wer vor einer Woche
1200 km gefahren ist, hat nicht „schon einen Teil des Rennens hinter
sich" — er hat beschädigte Muskulatur, leere Speicher und einen
gestörten Schlafrhythmus, und das begleitet ihn bis ins Ziel. Deshalb
gehen aus einer Eingangsgröße jetzt zwei Wege heraus: Die Restarbeit
zählt weiter im Ermüdungszähler (wer müde startet, erreicht die Wand
früher), und ein **Frischefaktor** trägt den bleibenden Teil.

### Abgleich mit den Dauerbändern

Das Dokument liefert in Abschnitt 2 selbst einen Kalibrierungsanker.
`ultrasim.cli.balance` prüft dagegen:

| Strecke | Klasse | Band | Feld im Band | Sieger |
|---|---|---|---|---|
| Voralpen-Runde | kurz | 5–15 h | 100 % | 8,7 h |
| Hochgebirgs-Marathon | mittel | 15–50 h | 100 % | 16,6 h |

Die 1230-km-Strecke liegt mit 36 h unter ihrem Band (50–110 h) — sie ist
mit 1230 km und 8000 hm am untersten Rand der Ultra-Klasse und dazu
flach. Das Band beschreibt die Mitte der Klasse, nicht ihren Rand.

Die interessante Eigenschaft des Modells: Die Zufuhr hat eine **absolute**
Obergrenze, der Verbrauch skaliert mit der Leistung. Ein starker Fahrer
kann nicht proportional mehr essen und wird relativ zu seiner FTP härter
gebremst als ein schwacher. Fettverbrennung und Magenverträglichkeit sind
damit keine Zierattribute mehr.

```bash
python -m ultrasim.cli.balance --route hochgebirgs-marathon --runs 20
```

liefert Siegerzeit, Feldschnitt, Feldspanne, die Rangkorrelation zwischen
Potenzial und Ergebnis (aktuell ≈ 0,65 — Attribute setzen sich durch,
ohne alles zu determinieren) und die Ausfallquote gegen den
Klassen-Zielkorridor.

`tests/test_golden_master.py` hält Streckenkennzahlen und ein
Rennergebnis auf festen Seeds fest. Wird er rot, ist er nicht kaputt —
er zeigt, dass sich das Balancing verschoben hat, und druckt die neuen
Werte kopierfertig aus. Es sind zwei Läufe: einer über 60 km und
anderthalb Stunden, einer über 1000 km und vierzig Stunden. Den zweiten
braucht es, weil im ersten die halbe Simulation nie an die Reihe kommt —
Schlafdruck, zirkadianer Tiefpunkt, Notschlaf und Aufgabe gibt es auf
einer Feierabendrunde nicht. Der lange Lauf hält deshalb nicht nur die
Zielzeiten fest, sondern auch die **Häufigkeit jedes Ereignistyps**: Wer
am Schlafmodell dreht, sieht sofort, dass aus zwei Schlafstopps keiner
mehr geworden ist, auch wenn die Zeiten in der Toleranz bleiben.

### Der Kalibrierungsbericht

```bash
python -m ultrasim.cli.calibrate        # ~25 min, schreibt docs/KALIBRIERUNG.md
```

`balance` ist das Werkzeug zum Hinsehen — eine Strecke, viele Zahlen,
alles auf der Konsole. [`docs/KALIBRIERUNG.md`](docs/KALIBRIERUNG.md) ist
das Werkzeug zum **Vergleichen**: alle Strecken auf einmal, und das
Ergebnis liegt als eingecheckte Datei im Repository. Der Unterschied ist
der Diff. Wer am Balancing dreht, sieht in der Änderungsansicht schwarz
auf weiß, was sich bewegt hat, statt es in einer Konsolenausgabe zu
suchen, die nach dem Schließen des Fensters weg ist.

Der Bericht beantwortet zwei Fragen, die die Dauerbänder nicht
beantworten: **Was ist ein einzelnes Attribut wert?** und **passen die
Archetypen zu den Strecken?**

**Alle Varianten in einem Rennen.** Naheliegend wäre, je Attribut zwei
komplette Rennen zu rechnen — bei 25 Attributen, zwei Richtungen und
drei Strecken sind das 150 Läufe und eine knappe Stunde, und jeder Lauf
trägt die Streuung von Wetter und Zwischenfällen mit sich. Stattdessen
starten alle Varianten **im selben Rennen**: Jeder Grundfahrer geht
zusätzlich mit +10 und mit −10 Punkten auf genau einem Attribut an den
Start. Weil die Zufallsströme an `(Seed, Fahrer-ID, Zweck)` hängen und
nicht an der Startposition, bekommen alle Kopien eines Fahrers denselben
Wetterverlauf, dieselben Pannenkandidaten und dieselbe Tagesform — was
an Zeit übrig bleibt, ist das Attribut und sonst nichts. Ein Rennen mit
1000 Startern kostet dabei nur das Vierfache eines Rennens mit 24, weil
die Simulation ohnehin über das ganze Feld vektorisiert ist.

Der Test, der diese Messung trägt, ist entsprechend unscheinbar: *Zwei
Kopien desselben Fahrers im selben Rennen fahren dieselbe Zeit.* Ginge
irgendwann ein Zufallsstrom an die Startposition statt an die
Fahrer-ID, wäre der ganze Bericht still Rauschen.

**Was nicht messbar ist, steht nicht drin.** Jede Wirkung muss zwei
Hürden nehmen: mindestens drei Sekunden groß und mindestens dreimal so
groß wie ihr eigener Standardfehler. Ohne die zweite Hürde liest man aus
zwanzig Fahrern, von denen einer eine Panne hatte, eine Attributwirkung
von sieben Minuten heraus. Drei Standardfehler statt der üblichen zwei,
weil die Tabelle 75 Felder hat — bei zwei wären rechnerisch drei
Fehltreffer darunter, und ein Fehltreffer ist teuer: Jemand fängt an,
ein Attribut zu reparieren, das nie kaputt war.

**Ein Attribut kann dieser Aufbau grundsätzlich nicht messen.**
`konstanz` steuert allein die *Streuung* der Tagesform, und die
Tagesform ist `1 + sd·z` mit einem z, das beide Kopien eines Fahrers aus
demselben Zufallsstrom ziehen. Die Paardifferenz ist damit proportional
zu −z: Bei einem Fahrer mit gutem Tag *schadet* Konstanz, bei einem mit
schlechtem hilft sie, und im Mittel stünde in der Tabelle der
Stichprobenmittelwert der Zufallszahlen statt der Wirkung des Attributs.
Der erste Berichtslauf hat dort −12, −37 und −44 Sekunden ausgewiesen,
auf allen drei Strecken negativ und scheinbar bestätigt — in Wahrheit
dreimal dieselben Zufallszahlen. Seitdem steht `konstanz` in einer
Ausnahmeliste, mit dieser Begründung im Bericht.

Damit Hitze- und Nässeattribute überhaupt eine Lage bekommen, in der sie
wirken können, läuft die Messung zusätzlich mit **erzwungenem Wetter**
— Hitze, Kälte, Dauerregen, Sturm. Ohne diesen Abschnitt hieße „nicht
messbar“ fälschlich „wirkungslos“: An einem 16-Grad-Tag ist
Hitzetoleranz nichts wert.

### Was der Bericht dann gefunden hat

Sechs Attribute standen mit einer Null in der Matrix — sie kosteten
Potenzial-Budget, standen im Fahrerdetail und bewirkten nichts. Der
Bericht hat das nicht vermutet, sondern gemessen, und damit ließ sich der
Reihe nach nachsehen, *warum*. Die Antworten waren nicht dieselbe, und
inzwischen sind alle sechs beantwortet:

| Attribut | Warum null | Was daraus wurde | Wirkung heute |
|---|---|---|---|
| `sitzkomfort` | kein Abnehmer im Code | Zustand *Sitzbeschwerden* ab 12–23 h im Sattel, −6 % FTP und Abfahrtstempo, heilt im Rennen nicht mehr | **88 s** (1230 km) |
| `mechanikerfaehigkeit` | kein Abnehmer | ±30 % auf jede Standzeit nach Panne und Defekt | 19–55 s |
| `hoehenanpassung` | kein Abnehmer | 7 % Leistungsverlust je 1000 m über 1500 m, ±50 % über das Attribut | 61 s (Hochgebirge), **0 s im Flachen** |
| `abfahrtstechnik` | gelesen, aber das Kurvenlimit lag bei 313–530 km/h und hat nie gebunden | engerer Bremsradius plus Kehren im Streckengenerator — Limit jetzt 57–64 km/h in steilen Abfahrten | **237 s** (Hochgebirge) |
| `hitzetoleranz` | die Wetterläufe maßen 16 Fahrerpaare auf einer 40-Stunden-Strecke — die Wirkung war da, aber sie ging im Chaos unter | Wetterlauf nimmt die *kürzeste* Strecke und 48 statt 16 Grundfahrer | **185 s** (300 km bei Hitze) |
| `oberflaechenkompetenz` | kein Abnehmer, und keine Strecke kennt Schotter | Rollwiderstand aus Oberfläche, Reifen, Tempo und Last; die Voralpen-Runde bekommt 37 % Schotter und Pflaster | **76 s** (Voralpen), 0 s auf Asphalt |

Die Null bei `hoehenanpassung` im Flachen ist dabei kein Rest, sondern
das Ergebnis: Ein Attribut, das nur über 1500 m greift, *muss* auf einer
Meeresspiegelstrecke exakt null messen. Ein Wert dort wäre der Fehler.

`risikobereitschaft` bleibt bewusst unmessbar. Sie ist zweischneidig
angelegt — mehr Tempo in der Abfahrt, mehr Sturzwahrscheinlichkeit — und
die beiden Seiten heben sich in der Zielzeit ungefähr auf. Wollte man
dort eine Zahl sehen, müsste man die Waage kippen, und damit wäre das
Attribut keine Entscheidung mehr, sondern ein Bonus. Der Bericht sagt
das inzwischen mit Zahlen statt mit einem Punkt — siehe unten.

**Bei der Hitze lag der Fehler im Messgerät, nicht im Modell.** Der
erste Verdacht war der Höhengradient: Die Presets setzen die Temperatur
auf Streckenniveau, davon gehen 6,5 K je 1000 m ab, und die Wetterläufe
liefen auf einer Strecke mit 2200 m Durchschnittshöhe — von 29 °C kamen
dort 20 an. Also die *tiefste* Strecke nehmen. Der Gedanke stimmt, nur
ist die tiefste hier zufällig die längste: 1230 km, 40 Stunden. Dort
misst die Hitze mit knapp acht Minuten die größte Wirkung des ganzen
Laufs — und trotzdem gehen zwölf von 42 Paaren in die *falsche*
Richtung, weil ein Fahrer, der zwei Minuten anders unterwegs ist, andere
Pannen annimmt und in einer anderen Nacht schläft. Über 40 Stunden
zerlegt die Chaosempfindlichkeit die Paarung, auf die diese ganze
Messung baut.

Auf 300 km bleibt sie dicht beieinander: 46 von 47 Paaren in dieselbe
Richtung, Standardfehler 22 statt 161 Sekunden. Der Wetterlauf nimmt seitdem die
kürzeste Strecke und 48 statt 16 Grundfahrer — mehr Paare kosten fast
nichts, weil sie im selben Rennen starten. Dass die Strecke im Mittel
auf 765 m liegt und damit 5 K kühler ist, kostet Wirkung; Wirkung, die
man messen kann, ist trotzdem mehr wert als Wirkung, die im Chaos
verschwindet.

**Der Vorzeichentest.** Dabei kam eine zweite Nachweisform dazu. Die
Hürde „mindestens drei Standardfehler" nimmt stillschweigend an, dass
die Paardifferenzen einigermaßen symmetrisch streuen. Für die meisten
Attribute stimmt das — Seitenwindfestigkeit misst sich mit einem
Standardfehler von 1,3 Sekunden. Für Abfahrtstechnik in der Kälte nicht:
38 von 47 Fahrern gewinnen Zeit, aber ein paar stürzen trotz besserer
Technik und ziehen das Mittel auf gut die Hälfte seines eigenen
Standardfehlers. Der Vorzeichentest fragt deshalb nicht nach der Größe,
sondern nach der Richtung, und ein Ausreißer um drei Stunden zählt
darin genau wie einer um zwei Sekunden. Er ist streng — bei 40 Paaren
braucht er rund 32 gleichgerichtete, ein Promille statt der üblichen
fünf Prozent — und er zählt nur, wenn auch der Median über der
Rauschgrenze liegt und in dieselbe Richtung zeigt wie das Mittel.

Genau diese letzte Bedingung hält Risikobereitschaft weiter draußen:
Bei Sturm ist das Mittel −86 Sekunden und der Median +10, und 33 von
48 Fahrern kommen schneller durch. Die Mehrheit
fährt schneller, die Minderheit stürzt und verliert mehr, als die
Mehrheit gewinnt. Beides ist wahr, und deshalb darf keine der beiden
Zahlen als „die Wirkung" in der Tabelle stehen.

**Eine Datenschwäche, die keine Mechanik war.** Beim Nachsehen wegen der
Hitze fiel auf, dass alle drei mitgelieferten Profile netto durchgehend
anstiegen: Die „Voralpen-Runde" endete 800 m über ihrem Start. Der
Generator zieht die Drift jetzt linear ab, die Runden sind wieder
Runden, und die Nordroute liegt bei 260 statt 2200 m im Mittel.

### Der Rollwiderstand war eine Konstante

`CRR` kennt seit M2 vier Oberflächen von gutem Asphalt bis
Kopfsteinpflaster, die Engine liest sie, und der Ereigniskatalog weiß,
welche davon rau sind. Trotzdem stand `oberflaechenkompetenz` im Bericht
bei null — aus einem banalen Grund: **keine Strecke hatte je etwas
anderes als Asphalt**. Die Tabelle war da, der Abnehmer war da, die
Daten fehlten.

Der Rollwiderstand hängt jetzt an vier Größen statt an einer:

1. **Oberfläche.** Über `--surface 34-61:gravel` beim Import oder später
   im Editor. GPX kennt keine Oberflächen — kein Format aus Navigator
   oder Aufzeichnung trägt sie mit —, also muss die Angabe von außen
   dazu.
2. **Reifen.** Schmal und hart gegen breit und weich, einmal je Strecke
   entschieden und mit Begründung protokolliert.
3. **Tempo.** Die Walkarbeit im Reifen wächst, weil dieselbe Verformung
   öfter je Sekunde durchlaufen wird: rund 0,0005 je 10 m/s.
4. **Last.** Mehr Systemmasse heißt mehr Schwingungsenergie bei
   gleichem Schlag.

**Der interessante Teil ist Punkt 2, und er ist echte Reifenphysik.**
Neben dem Abrollwiderstand gibt es die *Impedanz*: Der Reifen schlägt
gegen Kanten, Rad und Fahrer werden beschleunigt, und diese Energie
kommt nicht zurück. Sie wächst mit der Rauheit und mit der Steifigkeit
des Reifens. Daraus folgt der Umschlagpunkt, den jeder kennt, der schon
einmal auf schlechtem Belag Druck abgelassen hat:

| Oberfläche | schmal | breit | Sieger |
|---|---|---|---|
| guter Asphalt | 0,00422 | 0,00455 | **schmal** um 7,6 % |
| rauer Asphalt | 0,00790 | 0,00688 | **breit** um 14,9 % |
| Schotter | 0,01347 | 0,01127 | **breit** um 19,6 % |
| Kopfsteinpflaster | 0,01763 | 0,01412 | **breit** um 24,8 % |

Die Zahlen sind an Reifenmessungen angelehnt und nicht daran, eine
schöne Entscheidung zu erzwingen. Ein erster Ansatz hatte den
Schmalreifen auf Asphalt mit 14 % zu gut und auf Pflaster mit nur 10 %
zu wenig schlecht — die Wahl kippte damit erst bei rund 50 % Schotter,
also praktisch nie. Mit den korrigierten Werten fällt sie so:

| Strecke | rauer Anteil | Reifen |
|---|---|---|
| Voralpen-Runde | 36,9 % | **breit** |
| Hochgebirgs-Marathon | 0 % | schmal |
| Flachetappe Nordsee | 0 % | schmal |
| Nordroute Langstrecke | 0 % | schmal |

Die Voralpen-Runde hat dafür 37 % Schotter, rauen Belag und Pflaster
bekommen. Bewusst nicht die Flachetappe: Die ist als Heimterrain des
Zeitfahrers dazugekommen, und Schotter untergräbt genau das.

`oberflaechenkompetenz` misst dort jetzt **76 s** — und auf allen drei
glatten Strecken exakt null. Das ist kein Rest, sondern das Ergebnis:
Auf frischem Asphalt gibt es nichts zu können, und ein Attribut, das
dort etwas bewirkte, wäre ein verkappter Grundbonus.

Zwei Nebenwirkungen, die der Bericht mitgenommen hat. Der Schotter macht
die Voralpen-Runde langsamer — 9,4 statt 9,0 h —, aber nicht härter: Der
DNF-Anteil *fällt* von 2,1 auf 1,7 % und liegt damit erstmals im
Korridor von 1–2 %, wo er vorher knapp darüber lag. Das klingt
widersprüchlich und ist es nicht. Der Rennplan kennt die Oberfläche, er
rechnet die Abschnittszeiten damit und wählt den Reifen danach; die
Fahrer sind also langsamer *und im Plan*. Aufgegeben wird aber nicht
nach absoluter Zeit, sondern nach Rückstand auf den eigenen Plan.

Und `sitzkomfort` misst über die Vibrationskopplung jetzt auf zwei
Strecken statt auf einer: 61 s im Hochgebirge, 84 s auf der Nordroute.

Damit hat **jedes der 25 Attribute** eine Mechanik. Der Test, der
früher hieß „ein Attribut ohne Abnehmer bewirkt nichts", ist umgedreht
worden und prüft heute das Gegenteil.

**Und der Sattel hängt mit dran.** Was den Reifen an Impedanz kostet,
kommt beim Fahrer als Vibration an: Der breite Reifen schiebt die
Sattelbeschwerden nach hinten, rauer Untergrund zieht sie nach vorn.
`sitzkomfort` hat damit neben dem passiven Zeitzähler auch eine
Entscheidung hinter sich — wer empfindlich ist, nimmt den breiten
Reifen und zahlt dafür auf glatter Straße.

### Der Anstiegsaufschlag wird jetzt bezahlt

Der Zeitfahr-Spezialist hat auf keiner Strecke gewonnen, und die
Sensitivitätsmatrix hat auch gesagt, warum: `berg` und `flach` waren gar
nicht dieselbe Art von Größe. Über ein realistisches Feld (Attribut 20
bis 90) bewegte `berg` **12,7 % Leistung** am 10-%-Anstieg, `flach`
dagegen 1,4 % Tempo über ±3 % Luftwiderstand. Ein Kanal war eine Ansage,
der andere eine Nachkommastelle.

Und `berg` war geschenkt. `target_intensity()` zieht die Zielintensität
aus Distanz, Ausdauer und Erfahrung — von `berg` steht dort nichts —,
und der Anstiegsaufschlag kam *obendrauf*. Ein Kletterer fuhr im Flachen
genauso hart wie alle anderen und am Anstieg 24 % härter, ohne das
irgendwo abzutragen.

Drei Änderungen:

1. **Positionsdisziplin von ±3 % auf ±8 % CdA.** Nicht großzügig,
   sondern realistisch — zwischen einer eingefahrenen Zeitfahrposition
   und einer schlampigen liegen im Windkanal 10 bis 15 %.
2. **Der Aufschlag wird finanziert.** Der Plan normiert die
   zeitgewichtete mittlere Intensität auf den geplanten Wert; wer am
   Berg zulegt, fährt im Flachen darunter. Der Kletterer verliert seinen
   Vorteil dadurch nicht — ungleichmäßiges Fahren zahlt sich am Berg
   weiterhin aus, weil Zeit dort schwerer wiegt. Nur ist der Gewinn
   jetzt ein physikalischer statt eines zugeteilten.
3. **Fehlplanung greift früher** (Sättigung bei 3 statt 6 pp Überzug).

Punkt 2 ist dabei nicht nur die strengere Rechnung, sondern die
richtigere: `target_if` heißt laut eigener Beschreibung „Anteil der FTP
**über die Distanz**", und das war schlicht nicht wahr. Der
Energiedeckel rechnet mit genau diesem Mittel und hat den Verbrauch
deshalb systematisch unterschätzt — am stärksten bei den Fahrern mit dem
größten Aufschlag.

Was dabei herauskam:

| Attribut | vorher | jetzt |
|---|---|---|
| `flach` | 28 / 41 / 119 s | **69 / 127 / 322 s** |
| `berg` | 92 / 312 / 161 s | **46 / 180 / 108 s** |
| `pacing_disziplin` | **−83 s** | · |

`flach` schlägt `berg` jetzt auf der kurzen und der flachen Strecke und
verliert nur im Hochgebirge — genau die Reihenfolge, die man will.
Dauerbänder und DNF-Korridore blieben stehen (9,0 / 17,8 / 39,3 h;
2,1 / 5,0 / 9,6 %).

Die Zeile `pacing_disziplin` war vorher **negativ**: Disziplin kostete
Zeit. Wer schlecht pact, plant heißer, fährt das ganze Rennen über
schneller — und wurde nur in 19 % der Fälle dafür bezahlt. Zu heiß zu
planen war profitabel.

### Der Energiedeckel schneidet die halbe Planung weg

Der Grund war, dass das Attribut **einseitig** war: `pacing_gap =
max(0, (50 − pd) / 50)`. Unterhalb des Mittelwerts plante man zu heiß,
oberhalb passierte gar nichts — ein Fahrer mit 80 plante Punkt für
Punkt wie einer mit 50, und jeder Punkt darüber war verschenktes
Potenzial-Budget.

Der naheliegende Weg war, der Oberseite einen Bonus auf die
Zielintensität zu geben. Er hat **nichts** bewirkt, und zwar bei jeder
Größe von 2 bis 5 Prozentpunkten. Die Messung sagte dreimal
dieselbe Zahl, was kein Balancing-Problem ist, sondern ein Hinweis auf
eine Wand. Sie steht eine Zeile tiefer im Rennplan:

```python
target_if = clip(min(wish_if, energy_if))
```

Der Energiedeckel bindet auf allen vier Strecken bei **16 von 16**
Fahrern (auf der Ultradistanz bei 11 von 16). Jeder Bonus auf die
*Wunsch*intensität wird davon weggeschnitten, bevor er etwas tun kann.
Das erklärt auch, warum `erfahrung` auf drei von vier Strecken nicht
messbar ist und `ausdauer` sehr wohl: Ausdauer hebt zusätzlich den
Glykogenspeicher und damit den Deckel selbst.

Also wirkt Disziplin jetzt dort, wo sie physiologisch hingehört — beim
Kraftstoff. Der Kohlenhydratanteil wächst linear mit der Intensität,
der Verbrauch damit *quadratisch*, und für eine konvexe Funktion ist
der Mittelwert über schwankende Leistung größer als der Wert am
Mittel. Wer 250 W konstant tritt, verbrennt weniger Kohlenhydrate als
wer zwischen 200 und 300 W pendelt, bei identischer mittlerer Leistung.
Genau das ist Pacing-Disziplin, und als ±6 % auf den KH-Verbrauch wirkt
sie *innerhalb* des Deckels statt dagegen.

| `pacing_disziplin` | Voralpen | Hochgebirge | Flachetappe | Nordroute |
|---|---|---|---|---|
| vorher | · | · | — | **−83 s** |
| Bonus auf die Zielintensität | · | · | · | · |
| über den Kraftstoff | **62 s** | **172 s** | **43 s** | **142 s** |

Sichtbar wird das alles im **Attribut-Tuner** im Fahrerdetail: zwei
Schieberegler, ein Klick, und beide Versionen des Fahrers starten im
selben Rennen. Er nutzt dieselbe Paarmessung wie der Bericht, nur für
einen Fahrer und interaktiv — +25 Fettverbrennung und +25
Magenverträglichkeit sind auf der Langstrecke 17:23 min wert.

---

## Leistung

Gemessen auf einem gewöhnlichen Entwicklungsrechner:

| Rennen | Fahrer | Rechenzeit | Telemetrie |
|---|---|---|---|
| 300 km | 40 | ~5,5 s | 3,5 MB |
| 300 km | 250 | ~11 s | 21 MB |
| 507 km | 40 | ~10,5 s | 2,3 MB |

Der Sprung von 40 auf 250 Fahrer kostet Faktor 2, nicht Faktor 6 — genau
das Argument aus Abschnitt 8.1: Die Schleifenlänge ist die Tick-Anzahl,
nicht die Fahrerzahl. Ein Array mit 250 Elementen zu verrechnen kostet
praktisch dasselbe wie eines mit 41.

---

## Tests

```bash
pytest -q                    # 517 Tests, rund 190 s
pytest -q -m "not slow"      # ohne den Ultra-Golden-Master, rund 140 s
ruff check ultrasim tools tests
```

Die Tests halten vor allem die Zusicherungen fest, auf denen alles
andere ruht: dass die Glättung wirkt, dass gleicher Seed gleiches
Ergebnis liefert, dass sich das Rennen eines Fahrers nicht ändert, nur
weil jemand anderes gemeldet hat, und dass der Client nichts aus der
Zukunft sieht.

### Zwei Fehler, die nur das CI sehen konnte

Die Testmatrix fährt Linux und Windows, Python 3.11 und 3.12. Beides hat
sich gelohnt — auf dem Entwicklungsrechner (Linux, 3.11) war alles grün,
während zwei echte Fehler unbemerkt im Repository lagen:

**Der Golden Master war versionsabhängig.** Der Streckengenerator hat die
Punktzahl mit `int(total_m / spacing)` abgeschnitten, und die
Profillängen summieren sich exakt auf eine Ganzzahlgrenze. Seit Python
3.12 summiert `sum()` für Fließkommazahlen kompensiert und trifft 60,1
statt 60,099999999999994 — damit hatte dieselbe Teststrecke unter 3.12
einen Rasterpunkt mehr, war 30 m länger, und das Feld war 2,5 s
langsamer. Der Test war auf der einen Version rot und auf der anderen
grün. Der Generator rundet jetzt, statt abzuschneiden.

**Ein Pfeil hat das Windows-Programm abgestürzt.** Die Konsole einer
deutschen Windows-Installation ist cp1252 kodiert, und ein `⇒` in einer
Tabellenzeile des Balancing-Werkzeugs beendet den Prozess mit einem
`UnicodeEncodeError` — mitten in einer sonst fehlerfreien Ausgabe. Die
Anwendung wird als Windows-Programm ausgeliefert, das war also kein
Schönheitsfehler. Zwei Maßnahmen: Die Kommandozeilenwerkzeuge kommen
ohne solche Zeichen aus (ein Test prüft die Zeichenketten über den
Syntaxbaum, damit es nicht wieder passiert), und `use_safe_console`
schaltet die Ausgabe zusätzlich auf `errors="replace"` — dann wird aus
einem künftigen Ausrutscher ein Fragezeichen statt eines Absturzes.

---

## Auslieferung

Jeder Tag `v*` löst über GitHub Actions einen Windows-Build aus, der eine
`UltracyclingSimulator.exe` als Release-Asset veröffentlicht. Details und
Fallstricke: [`BUILD_UND_RELEASE.md`](BUILD_UND_RELEASE.md).

Was in welcher Version steckt — samt der gemessenen offenen Punkte —
steht in [`CHANGELOG.md`](CHANGELOG.md).

---

## Lizenz

MIT. Mitgelieferte Fremdbibliotheken (Alpine.js, uPlot) stehen ebenfalls
unter MIT — siehe `ultrasim/web/static/vendor/README.md`.
