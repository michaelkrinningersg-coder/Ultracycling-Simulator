# Änderungen

Das Format folgt lose [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung [SemVer](https://semver.org/lang/de/).

## v0.1.0 — 2026-08-14

Die erste veröffentlichte Fassung. Sie deckt den Umfang ab, den
Abschnitt 16 des [Design-Dokuments](docs/GAME_DESIGN.md) für die erste
Version festlegt: Meilensteine M1 bis M8, die Editoren aus M5b und den
Karrieremodus.

UltraSim ist ein **Zuschauer**-Simulator. Es gibt nichts zu steuern —
fiktive Fahrer fahren eine GPX-Strecke im Einzelzeitfahren, und man sieht
ihnen über eine Live-Telemetrie im Stil einer Wintersport-Übertragung
dabei zu.

### Simulation

- **Streckenimport** aus beliebigen GPX-Dateien: Resampling auf 10 m,
  Savitzky-Golay-Glättung, Segmentierung, Anstiegserkennung mit
  Kategorien, Splits und Servicepunkte.
- **Physik** mit Roll-, Steigungs-, Luft- und Beschleunigungswiderstand,
  1-s-Euler-Integration, höhenabhängiger Luftdichte, Kurvenlimit und
  CdA aus Körpermaßen. Der Rollwiderstand hängt an Oberfläche, Reifen,
  Tempo und Systemmasse, inklusive der Impedanz — dem Anteil, der als
  Schwingung verlorengeht.
- **Fahrer** aus acht Archetypen mit gemeinsamem Potenzial-Budget, 25
  Attributen, Saison-/Tages-/Abschnittsform, W′ und Langzeitermüdung.
- **Energiehaushalt** mit Glykogenspeicher, Substratverteilung,
  Zufuhrgrenze aus Magen und Verwertung, Hungerast.
- **Schlaf** mit persönlichem Wachhorizont, zirkadianem Tiefpunkt,
  geplanten Schlafstopps und Notschlaf am Straßenrand.
- **Wetter** zweischichtig: die Ortsschicht hängt an der Position, die
  Zeitschicht an der Eigenzeit des Fahrers. Dazu Hydration.
- **Zwischenfälle** als Poisson-Prozess entlang der Strecke — Panne,
  Defekt, Sturz, Magenprobleme, Verfahren, Sperrung — und vier Wege zum
  Aufgeben.
- **Strategiemodul** in zwei Stufen: der Rennplan vor dem Start
  (Zielintensität, Anstiegsaufschlag, Radwahl je Abschnitt) und der
  Regelkreis während des Rennens (Sparmodus, Hitzemodus, Aufholjagd,
  vorgezogener Schlaf). Jede Entscheidung mit Begründung im
  Ereignisstrom.

### Oberfläche

- **Live-Telemetrie** mit Höhenprofil, Board, virtueller Rangliste,
  Ereignis-Ticker und sieben Zeitrafferstufen von 1× bis 1000×. Uhr und
  Rückstand zählen zwischen zwei Frames mit, statt im Takt der Frames
  zu springen; eine eigene Spalte zeigt die Meter bis zur nächsten
  Zeitmessung.
- **Auswertung**: Warum-Panel, das die Form in ihre Faktoren zerlegt,
  Splitzeiten-Matrix und ein Rennbericht in einem Satz je Fahrer.
- **Editoren** für Strecken, Fahrer, Teams, Saisonkalender und Karriere.
- **Attribut-Tuner** im Fahrerdetail: zwei Regler, ein Klick, und beide
  Versionen desselben Fahrers starten im selben Rennen.

### Saison und Karriere

- Kalender mit Terminen, Wertung und Restermüdung von Rennen zu Rennen.
- Mehrjahres-Karriere mit eingefrorenen Jahreswertungen, Alterung,
  Rücktritten, ewiger Bestenliste und Lebenslauf je Fahrer.

### Werkzeuge

- Kommandozeile für Pool, Rennen, Ergebnis, Saison und Kalibrierung.
- **Kalibrierungsbericht** ([`docs/KALIBRIERUNG.md`](docs/KALIBRIERUNG.md)):
  Erwartete Dauer, DNF-Korridore, Platzierung nach Archetyp mit
  Standardfehler und eine Matrix, was jedes Attribut auf jeder Strecke
  in Sekunden wert ist.
- 525 Tests, darunter zwei Golden Master (90 Minuten und 40 Stunden).

### Vier Strecken liegen bei

Alle synthetisch erzeugt, damit das Programm ohne Netz und ohne fremde
Kartendaten läuft:

| Strecke | Distanz | Höhenmeter | je km | Oberfläche |
|---|---|---|---|---|
| Voralpen-Runde | 300 km | 2674 m | 8,9 m | 37 % Schotter, rauer Belag, Pflaster |
| Hochgebirgs-Marathon | 507 km | 6790 m | 13,4 m | Asphalt |
| Flachetappe Nordsee | 466 km | 1075 m | 2,3 m | Asphalt |
| Nordroute Langstrecke | 1230 km | 6120 m | 5,0 m | Asphalt |

### Bekannte Einschränkungen

Diese Punkte sind gemessen, nicht vermutet — sie stehen so im
Kalibrierungsbericht:

- Die **Archetypen sind nicht ausbalanciert**, und zwar deutlicher als
  die frühere Fassung dieser Liste behauptet hat. Gemessen mit 160
  Fahrern über zwölf Rennen je Strecke (mittlere Platzierung, neutral
  wäre 80,5):

  | Archetyp | Flachetappe | Hochgebirge |
  |---|---|---|
  | Fettverbrenner | 46,7 | 44,0 |
  | Kletterer | 66,9 | 49,2 |
  | Zeitfahr-Spezialist | 75,2 | 85,9 |
  | Diesel / Ultra-Maschine | 102,5 | 103,6 |

  Der **Fettverbrenner** ist zu stark, weil die Ernährungsattribute die
  Sensitivitätsmatrix anführen: `magenvertraeglichkeit` ist mit
  413–969 s der größte Einzelwert der ganzen Tabelle. Der **Diesel**
  ist mit Abstand zu schwach, der **Zeitfahr-Spezialist** liegt überall
  unter dem Schnitt.

- Vier Attribute sind **in keinem Lauf messbar**: `spritzigkeit`,
  `mentale_widerstandsfaehigkeit`, `navigationssicherheit`,
  `materialpflege`. Bei `risikobereitschaft` ist die Null Absicht — sie
  ist zweischneidig angelegt, und der Bericht weist beide Seiten
  getrennt aus.

Zwei Punkte, die in einer früheren Fassung dieser Liste standen, sind
inzwischen erledigt oder waren falsch:

- „Der Draufgänger holt überproportional viele Siege" war ein
  **Messfehler**. Er stammte aus einer Archetyp-Tabelle mit vier
  Fahrern je Typ und sechs Rennen je Strecke — 24 Stichproben bei einer
  Streuung von rund einem Viertel der Feldgröße. Mit ausreichender
  Stichprobe liegt der Draufgänger bei 88,9 und 87,5, also klar
  unterdurchschnittlich. Der Bericht weist seitdem Standardfehler aus
  und hat die Siegspalte durch den Anteil im besten Zehntel ersetzt.
- Die **Dauerbänder** hingen an der Distanzklasse, und ein Eimer von
  400 bis 1200 Äquivalentkilometern umfasst Rennen von zwölf bis
  fünfundvierzig Stunden. Das Band kommt jetzt stetig aus Distanz und
  Höhenmetern.
