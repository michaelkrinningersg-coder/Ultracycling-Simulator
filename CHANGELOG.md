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
  CdA aus Körpermaßen.
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
  Ereignis-Ticker und Zeitraffer von 1× bis 1000×.
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
  Dauerbänder, DNF-Korridore, Siegverteilung nach Archetyp und eine
  Matrix, was jedes Attribut auf jeder Strecke in Sekunden wert ist.
- 517 Tests, darunter zwei Golden Master (90 Minuten und 40 Stunden).

### Vier Strecken liegen bei

Alle synthetisch erzeugt, damit das Programm ohne Netz und ohne fremde
Kartendaten läuft:

| Strecke | Distanz | Höhenmeter | je km |
|---|---|---|---|
| Voralpen-Runde | 300 km | 2674 m | 8,9 m |
| Hochgebirgs-Marathon | 507 km | 6790 m | 13,4 m |
| Flachetappe Nordsee | 466 km | 1075 m | 2,3 m |
| Nordroute Langstrecke | 1230 km | 6120 m | 5,0 m |

### Bekannte Einschränkungen

Diese Punkte sind gemessen, nicht vermutet — sie stehen so im
Kalibrierungsbericht:

- Der **Zeitfahr-Spezialist** gewinnt auf keiner Strecke, auch nicht auf
  der flachen. Ein Teil seines Potenzial-Budgets steckt in Attributen,
  die messbar nichts bewirken.
- Der **Draufgänger** holt überproportional viele Siege. Das ist zum
  Teil gewollt (hohe Streuung gehört zum Archetyp), zum Teil noch nicht
  ausbalanciert.
- Fünf Attribute sind **in keinem Lauf messbar**:
  `spritzigkeit`, `mentale_widerstandsfaehigkeit`, `risikobereitschaft`,
  `navigationssicherheit`, `materialpflege`. Bei
  `risikobereitschaft` ist das Absicht — sie ist zweischneidig angelegt.
  `oberflaechenkompetenz` wirkt nicht, weil keine Strecke Schotter kennt.
- Die **Dauerbänder** hängen an der Distanzklasse. Eine flache
  466-km-Strecke ist in 13 h gefahren, eine bergige 507-km-Strecke
  braucht 18 h — beide gelten als „mittel", und das Band kann nicht
  beides abdecken.
