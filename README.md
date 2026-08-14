# UltraSim — Ultracycling Live Telemetry Simulator

Ein Simulator, in dem definierte Fahrer eine reale Strecke im
Einzelzeitfahren absolvieren. Der Reiz liegt nicht im Steuern, sondern im
Zuschauen und Auswerten: Eine Live-Telemetrie im Stil von
Wintersport-Übertragungen zeigt, wie sich der beobachtete Fahrer an jedem
Split gegen das Feld einordnet.

Das vollständige Konzept steht in [`docs/GAME_DESIGN.md`](docs/GAME_DESIGN.md).
Dieses README beschreibt, was davon gebaut ist und wie man es benutzt.

---

## Stand: Meilensteine M1–M8 samt Editoren (M5b)

Das Design-Dokument gliedert die Umsetzung in acht Meilensteine und
definiert in Abschnitt 16 den Umfang der ersten Fassung. Genau der ist
hier umgesetzt.

**Fertig und wirksam**

| Bereich | Was drinsteckt |
|---|---|
| GPX-Import (M1) | Namespace-tolerantes Parsen, Duplikatentfernung, Höheninterpolation, Resampling auf 10 m, Savitzky-Golay-Glättung, Segmentierung, Anstiegserkennung mit Kategorien, Splits und Servicepunkte, gzip-JSON |
| Physik (M2) | Roll-, Steigungs-, Luft- und Beschleunigungswiderstand, Euler-Integration mit 1 s Tick, höhenabhängige Luftdichte, Abfahrtslogik mit Trittfrequenzgrenze und Kurvenlimit, CdA aus Körpermaßen |
| Fahrer (M3) | Generator mit acht Archetypen und Potenzial-Budget, 25 Attribute, Saison-/Tages-/Abschnittsform (OU-Prozess), W′ und Langzeitermüdung, Team-Attribut Servicedisziplin |
| Strategie | Rennplan je Fahrer: Ziel-Intensität aus der Distanz, Anstiegs-Aufschlag, Radwahl je Servicepunkt-Abschnitt mit Wirtschaftlichkeitsprüfung — jede Entscheidung mit Begründung protokolliert |
| Rennen (M3) | Vektorisiert über das ganze Feld, Einzelstart, Splitzeiten mit Sub-Tick-Interpolation, Ereignis-Strom, quantisierte Telemetrie |
| Oberfläche (M4) | Höhenprofil-Canvas mit Übersicht und Ausschnitt, Telemetrie-Board mit 41-Zeilen-Fenster, virtuelle Rangliste, Ticker, Playback-Server mit Zeitraffer 1×–1000×, Ergebnisliste, Fahrerdetail mit Verlaufskurven |
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
| Werkzeuge | CLI für Pool, Rennen, Ergebnis, Fahrerdetail, Saison und Kalibrierung, Balancing-Batch mit Abgleich gegen Dauerbänder und DNF-Korridor, 410 Tests inklusive zweier Golden-Master |

**Bewusst gestrichen**: die Highlight-Automatik aus M7b — der Ticker
meldet ohnehin jedes größere Ereignis, und eine automatische Auswahl
„sehenswerter“ Momente würde in einem Einzelzeitfahren ohne
Kameraführung nichts hinzufügen, was die Ereignisliste nicht schon
zeigt. Ebenso der Abgleich mit realen Ultra-Ergebnissen aus M8: Für die
großen Rennen liegen die Strecken nicht als GPX vor, und eine
Kalibrierung gegen nachgebaute Profile misst am Ende den
Profilgenerator.

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
alle 25 Attribute, aber nur die 21, die tatsächlich in die Simulation
eingreifen, sind hell hervorgehoben. Ein Test hält diese Liste ehrlich —
er vergleicht sie mit dem, was der Code liest, und schlägt in beide
Richtungen an.

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

Drei Strecken liegen bei, je eine pro Distanzklasse:

| ID | Distanz | Höhenmeter | Klasse |
|---|---|---|---|
| `voralpen-runde` | 300,5 km | 3114 m | kurz |
| `hochgebirgs-marathon` | 507,0 km | 7887 m | mittel |
| `nordroute-langstrecke` | 1230,0 km | 8044 m | ultra |

> Diese drei sind **synthetisch erzeugt**, nicht real: Sie entstehen aus
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

Auf dem Board bekommen Fahrer, die den gewählten Split noch nicht
erreicht haben, eine Prognosezeit aus aktuellem Tempo und Reststrecke —
und stehen damit **an der Position, die diese Prognose ergibt**, kursiv
und ohne Platzziffer. Genau daraus entsteht die Frage „kommt er noch
vorbei?“.

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
            events · engine
  geo/      gpx_import · smoothing · segmentation · splits · route
  data/     store          (Dateiablage: JSON für Stammdaten, npz für Telemetrie)
  calibration.py           Messungen *an* der Simulation: Dauerband, DNF,
                           Archetypen, Attribut-Sensitivität
  season_runner.py         Dienstschicht: Kalender rechnen, werten, altern
  web/      main · playback · jobs · routers/ · templates/ · static/
            routers: pages · routes (Streckeneditor) · pool (Fahrer, Teams)
                     seasons (Kalender) · api (Board, SSE)
  cli/      simulate · balance · calibrate · season
  app.py    Startlogik der ausgelieferten Anwendung
tools/      make_demo_gpx.py
docs/       GAME_DESIGN.md · KALIBRIERUNG.md (erzeugt, eingecheckt)
tests/      geo · core · engine · conditions · nutrition · sleep · weather
            incidents · season · season_web · editors · tactics
            calibration · playback · golden_master
data/
  gpx/      Quelldateien der mitgelieferten Strecken
  routes/   importierte Strecken (gzip-JSON, eingecheckt)
  races/    gerechnete Rennen (erzeugt, nicht eingecheckt)
  seasons/  Kalender und Wertung (erzeugt, nicht eingecheckt)
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
   Wirtschaftlichkeitsprüfung aus 6.4 in wenigen Zeilen zu haben. Der
   Effekt ist sichtbar: Auf der flachen Voralpen-Runde fährt das ganze
   Feld Zeitfahrrad, im Hochgebirge wechseln die Kletterer am
   Servicepunkt vor den Pässen aufs Straßenrad und danach zurück.

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
pytest -q                    # 410 Tests, rund 265 s
pytest -q -m "not slow"      # ohne den Ultra-Golden-Master, rund 230 s
ruff check ultrasim tools tests
```

Die Tests halten vor allem die Zusicherungen fest, auf denen alles
andere ruht: dass die Glättung wirkt, dass gleicher Seed gleiches
Ergebnis liefert, dass sich das Rennen eines Fahrers nicht ändert, nur
weil jemand anderes gemeldet hat, und dass der Client nichts aus der
Zukunft sieht.

---

## Auslieferung

Jeder Tag `v*` löst über GitHub Actions einen Windows-Build aus, der eine
`UltracyclingSimulator.exe` als Release-Asset veröffentlicht. Details und
Fallstricke: [`BUILD_UND_RELEASE.md`](BUILD_UND_RELEASE.md).

---

## Lizenz

MIT. Mitgelieferte Fremdbibliotheken (Alpine.js, uPlot) stehen ebenfalls
unter MIT — siehe `ultrasim/web/static/vendor/README.md`.
