# UltraSim — Ultracycling Live Telemetry Simulator

Ein Simulator, in dem definierte Fahrer eine reale Strecke im
Einzelzeitfahren absolvieren. Der Reiz liegt nicht im Steuern, sondern im
Zuschauen und Auswerten: Eine Live-Telemetrie im Stil von
Wintersport-Übertragungen zeigt, wie sich der beobachtete Fahrer an jedem
Split gegen das Feld einordnet.

Das vollständige Konzept steht in [`docs/GAME_DESIGN.md`](docs/GAME_DESIGN.md).
Dieses README beschreibt, was davon gebaut ist und wie man es benutzt.

---

## Stand: Meilensteine M1–M4, dazu M5 Schritte 1–2

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
| Werkzeuge | CLI für Pool, Rennen, Ergebnis und Fahrerdetail, Balancing-Batch, 170 Tests inklusive Golden-Master |

**Noch nicht enthalten** (M5 Schritte 3–4, M6–M8): Schlaf und
Schlafdruck, Hydration, Wetter, Wind und Tag-Nacht-Zyklus, Pannen und
Zwischenfälle, Saison und Kalender, Editoren im Spiel.

Hydration fehlt bewusst noch: Ihre Eingangsgrößen sind Temperatur und
Luftfeuchte, und die entstehen erst mit dem Wettermodell. Ohne sie wäre
die Schweißrate eine Konstante und damit nichts als ein linearer
Zeitabzug für alle.

Für all das steht der Katalog in `ultrasim/core/conditions.py` schon
bereit: Magenprobleme, Hitzeeinbruch, Schlafdefizit, Sturzfolgen und
Ersatzrad sind als Datenzeilen hinterlegt und wirken, sobald es einen
Erzeuger dafür gibt. Der Physikcode muss dafür nicht mehr angefasst
werden — das war der Zweck von Abschnitt 6.5.

Was das praktisch bedeutet, steht offen in der Oberfläche: Das
Fahrerdetail zeigt alle 25 Attribute, aber die zehn, die derzeit wirklich
in die Simulation eingreifen, sind hell hervorgehoben — der Rest ist
gedämpft. Und weil es noch keine Zwischenfälle gibt, gibt es auch fast
keine Ausfälle; der DNF-Zielkorridor aus Abschnitt 6.5 wird erst mit
M5/M6 erreichbar. Das Balancing-Werkzeug sagt das ausdrücklich dazu.

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

Die Ergebnis- und Detailseiten sind Nachbetrachtungs-Screens und
verraten den Ausgang; sie sind entsprechend zurückhaltend verlinkt.

---

## Aufbau

```
ultrasim/
  core/     physics · rider · form · fatigue · nutrition · conditions · strategy · events · engine
  geo/      gpx_import · smoothing · segmentation · splits · route
  data/     store          (Dateiablage: JSON für Stammdaten, npz für Telemetrie)
  web/      main · playback · routers/ · templates/ · static/
  cli/      simulate · balance
  app.py    Startlogik der ausgelieferten Anwendung
tools/      make_demo_gpx.py
tests/      geo · core · engine · conditions · nutrition · playback · golden_master
data/
  gpx/      Quelldateien der mitgelieferten Strecken
  routes/   importierte Strecken (gzip-JSON, eingecheckt)
  races/    gerechnete Rennen (erzeugt, nicht eingecheckt)
```

Architekturprinzip aus Abschnitt 13: **Die Simulation ist eine reine
Bibliothek ohne Web-Abhängigkeit.** `ultrasim/core/` erzeugt aus einer
Renn-Konfiguration ein Ergebnis samt Event-Strom; Web-App und CLI sind
nur zwei Konsumenten davon. Deshalb laufen Balancing-Batches ohne
Browser.

### Zwei bewusste Abweichungen vom Design-Dokument

1. **Kein SQLAlchemy/SQLite.** Abschnitt 13 sieht für die Stammdaten
   SQLAlchemy vor. Solange es weder Saison noch Kalender noch
   Gesamtwertung gibt (M7), gibt es auch nichts zu joinen — eine Datei je
   Rennen ist einfacher und hält das PyInstaller-Bundle klein. Alle
   Zugriffe laufen schon jetzt über `ultrasim/data/store.py`, damit der
   Wechsel später ein einzelner Austausch ist und nicht eine Suche durch
   die halbe Anwendung.

2. **Der Radplan ist schon da.** Er gehört laut Roadmap zu M6, ist aber
   Teil des Rennplans aus Abschnitt 7.1 und mit der
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
Werte kopierfertig aus.

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
pytest -q          # 170 Tests, rund 36 s
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
