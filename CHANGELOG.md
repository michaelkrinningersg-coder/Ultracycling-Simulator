# Änderungen

Das Format folgt lose [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung [SemVer](https://semver.org/lang/de/).

## Unveröffentlicht

### Geprüft

- **Die Feldunabhängigkeit gilt nicht ausnahmslos.** Zwei Tests sichern
  zu, dass das Rennen eines Fahrers nicht davon abhängt, wie groß das
  Feld ist. Mit dem neuen Feld findet sich ein Gegenbeispiel: Von acht
  Fahrern sind sieben bitgleich, einer weicht über 7,5 Stunden um 213 s
  ab. Sein Plan, sein Ereignisstrom und die gezogene Reparaturdauer sind
  identisch; die erste messbare Abweichung ist **ein Meter** Distanz und
  ein Prozentpunkt Glykogen, danach verstärkt das Modell sie.

  Ausgeschlossen sind der Startabstand (der Versatz geht nicht in die
  Simulation ein), ``np.bincount`` in der Zustandsverwaltung
  (längenstabil geprüft) und NumPys elementweise Funktionen
  (power/exp/log/sqrt, bitgleich über Arraylängen von 8 bis 300). **Die
  Ursache ist offen**; beide Tests stehen als ``xfail(strict=True)``, der
  Befund steht in ihrer Begründung.

  Nicht betroffen ist die Attributmatrix der Kalibrierung: Sie misst
  beide Varianten eines Fahrers in *einem* Rennen, also im selben Feld.
- **Kalibrierungsbericht neu erhoben** (`docs/KALIBRIERUNG.md`, 45 min).
  Alle vier Strecken liegen jetzt im DNF-Korridor — die Flachetappe war
  mit 3,8 % als einzige markiert und steht bei 4,2 %:

  | Strecke | vorher | jetzt | Ziel |
  |---|---|---|---|
  | Voralpen-Runde 300 km | 1,7 % | 1,2 % | 1–2 % |
  | Hochgebirgs-Marathon 506 km | 5,0 % | 4,6 % | 4–7 % |
  | Flachetappe Nordsee 466 km | 3,8 % ⚠ | 4,2 % | 4–7 % |
  | Nordroute Langstrecke 1230 km | 9,6 % | 10,0 % | 8–12 % |

  Die Archetyp-Tabelle steht erstmals mit zwanzig Fahrern je Typ im
  eingecheckten Bericht — und dreht die bisherige Aussage: Nicht der
  Fettverbrenner führt, sondern der **Kletterer**, und zwar auf allen
  vier Strecken. `spritzigkeit` ist seit dem Trittfrequenzmodell
  messbar; ohne Nachweis bleiben drei Attribute
  (`mentale_widerstandsfaehigkeit`, `navigationssicherheit`,
  `materialpflege`).

  **Was der Bericht nicht sehen kann:** Seine längste Strecke ist
  1230 km. Sämtliche Fehler dieser Fassung lagen oberhalb von 1500 km —
  der abgeschnittene Simulationshorizont, der Notschlaf im
  Aufgabe-Term, die gekappten Rennkoeffizienten. Keiner davon wäre hier
  aufgetaucht.

### Hinzugefügt

- **Fünfundzwanzig benannte Teams à zwölf Fahrer, 300 Starter.** Die
  Mannschaften hießen bisher aus zufällig kombinierten Bausteinen und
  wechselten mit jedem Seed; jetzt sind es feste Paare aus Ausrüster und
  Radmarke nach dem Muster des echten Radsports — `Vaude–Canyon`,
  `Ortlieb–Cube`, `Deuter–Rose`. Ein Team bleibt damit über Saisons
  hinweg dasselbe Team.

  Die **Marken sind echt, die Teams sind es nicht** — der Hinweis steht
  im README und im Quelltext.

  Auch die Teamfarbe kommt jetzt aus der Listenposition statt aus dem
  Zufall: fünfundzwanzig Farbtöne über den Kreis, jeder zweite versetzt,
  damit Nachbarn in der Startliste nicht dieselbe Farbfamilie tragen.
  Vorher konnten zwei Teams fast identische Farben ziehen — und der
  Farbkeil ist im Board das Einzige, was ein Team auf einen Blick
  unterscheidet.
- **Startabstand 15 statt 30 Minuten.** Mit 300 Startern wäre das
  Startfenster sonst auf 149 Stunden gewachsen; so bleibt es bei 75. Die
  räumliche Entzerrung, um die es bei dem Abstand geht, trägt weiter:
  Bei 25 km/h liegen zwei aufeinanderfolgende Starter gut sechs
  Kilometer auseinander.
- **Die Ultra-Weltserie**: zehn neue Strecken von 396 bis 2469 km und
  ein Standardkalender darüber. Zehn verschiedene Anforderungen, nicht
  zehn Längen — flaches Zeitfahren, Rampenrennen, Kehrenpässe, Schotter,
  Pflasterhügel, Nachtfahrt, Bergultra, Monotonie auf der Hochebene,
  Alpenquerung, und am Ende alles zusammen.
  - Die Termine stehen dort, wo das **Erholungsfenster** des vorherigen
    Rennens endet, nicht auf runden Abständen. Das füllt die Saison vom
    1. Februar bis zum 2. November; zehn Rennen dieser Größe passen
    gerade so in ein Jahr. Dieselbe Regel gilt jetzt auch für den
    allgemeinen Kalendervorschlag — vorher kam die Pause aus der
    Distanzklasse, und der Eimer „ultra" reicht von 1000 bis 2500 km.
  - Der Kalender liegt beim ersten Start fertig da, **ungerechnet**. Ihn
    vorzurechnen hieße, den Nutzer eine Viertelstunde vor einem
    Ladebalken warten zu lassen, bevor er das Programm gesehen hat.
  - Die Profile entstehen aus **Motiven** statt aus handgeschriebenen
    Tabellen: ein flaches Zwischenstück, eine Welle, ein Kehrenpass,
    jeweils in mehreren Ausprägungen im Wechsel. Eine 2500-km-Strecke
    als Zahlentabelle wäre nicht mehr überprüfbar.
- **Ultrameister**: Wer nach dem letzten Termin die Gesamtwertung
  anführt, bekommt den Titel — und zwar erst dann. Ein verworfenes
  Ergebnis nimmt ihn wieder weg; ein Titel über einem Kalender mit einem
  offenen Termin bezöge sich auf nichts.

- **Live gerechnete Rennen** — eine bewusste Abweichung von Abschnitt
  8.2, der Vorberechnung mit anschließender Wiedergabe vorsieht. Bisher
  war die Reihenfolge rechnen → speichern → abspielen; ein Ultra mit 250
  Fahrern rechnete knapp eine Minute, bevor das erste Bild stand.
  `simulate_race` ist jetzt ein Generator, und die Wiedergabeuhr zieht
  ihn hinter sich her. „Übertragung starten“ auf der Übersicht legt ein
  Rennen an, das noch gar nicht existiert. Die Wiedergabe bleibt, was
  sie war — der alte Weg über ein fertiges Rennen funktioniert
  unverändert.
  - Alle sieben Zeitrafferstufen bleiben. Die Rechenzeit war nie das
    Problem: gemessen 1900- bis 5400-fache Echtzeit gegen höchstens
    1000-fachen Zeitraffer.
  - Der Zwischenstand wird laufend gesichert — Platzierungen,
    Splitzeiten und Telemetrie bis zu diesem Punkt, unter derselben
    Renn-ID und im selben Format wie ein fertig gerechnetes Rennen. Es
    gibt kein zweites Dateiformat für halbe Rennen.
  - Dass Live und Stapel dasselbe Rennen liefern, prüft
    `tests/test_live.py` auf die Hundertstelsekunde. Hinge das Ergebnis
    daran, ob jemand zugeschaut hat, wäre der Seed keine
    Reproduzierbarkeit mehr, sondern eine Behauptung.

### Behoben

- **`generate_pool` koppelte Teams und Fahrer an einen Zufallsstrom.**
  Aufgefallen beim Umbau auf feste Teamnamen: Ein Team zieht seitdem
  drei Zufallszahlen weniger (Präfix, Suffix, Farbton), und damit
  verschob sich jede Ziehung dahinter — derselbe Seed lieferte ein
  komplett anderes Fahrerfeld, obwohl an den Fahrern nichts geändert
  war. Beide Golden Master wurden rot.

  Dieselbe Lehre steht eine Ebene tiefer schon bei ``RiderStreams``.
  Teams und Fahrer haben jetzt getrennte Ströme über ``spawn_key``, und
  ``test_the_team_list_does_not_move_the_riders`` hält fest, dass eine
  Änderung an der Teamliste kein Fahrerattribut mehr bewegt. Die Golden
  Master mussten dafür einmalig neu gesetzt werden — mit der Begründung
  im Test, und es war der letzte Neusatz dieser Art.
- **Notschlaf zählte als Grund aufzugeben.** Der Aufgabe-Term heißt
  „kein Anschluss mehr an den eigenen Plan" und meint laut seinem
  eigenen Kommentar den Satz eines Aussteigers — *drei Pannen und
  zweimal verfahren, das hole ich nicht mehr auf.* Gerechnet hat er mit
  der gesamten verlorenen Zeit, und darin steckt der Notschlaf am
  Straßenrand.

  Bis 1463 km fällt das nicht auf, weil dort **überhaupt kein**
  Notschlaf vorkommt. Ab 1924 km sind **85 % der verlorenen Zeit**
  Notschlaf (12,4 von 14,6 Stunden; auf 2469 km 17,9 von 20,9). Auf
  einer Strecke mit fünf Nächten ist Schlaf nicht das Scheitern des
  Plans, sondern der Plan — und er zählte doppelt, weil er über den
  Schlafdruck bereits im Ermüdungsterm derselben Formel steckt.

  Gemessen (80 Fahrer, ohne Restermüdung), Ziel 8–12 %:

  | Strecke | vorher | nachher |
  |---|---|---|
  | Pyrenäen-Traverse 1212 km | 7,5 % | 7,5 % |
  | Steppenroute 1463 km | 12,5 % | 13,8 % |
  | Alpenüberquerung 1924 km | **42,5 %** | **12,5 %** |
  | Transkontinental 2469 km | **40,0 %** | **13,8 %** |

  Die zwei kürzeren ändern sich nicht — dort gibt es keinen Notschlaf,
  die Korrektur greift also genau dort, wo die Ursache liegt.

  Die Ergebnisliste sieht weiterhin beides: ``RaceEntry.lost_s`` ist die
  ganze verlorene Zeit, ``lost_incident_s`` der Zwischenfallanteil.
- Der **Simulationshorizont** war auf bergigen Strecken eine sportliche
  Regel statt einer Rechengrenze. Er kam aus der Distanz allein
  (`km / 11`), die Wertungsgrenze aus der Siegerzeit (`× 1,4`) — auf den
  Dolomiten-Vierpässen lag der Horizont damit bei 52 Stunden und die
  Zeitgrenze erst bei 54. Die Simulation hörte vor der Wertung auf:
  **116 von 250 Fahrern** schieden mit „Zeitrahmen überschritten" aus,
  die Hälfte davon jenseits Kilometer 455 von 573. Sie waren nicht zu
  langsam für das Rennen, sondern für die Uhr des Programms. Der
  Horizont rechnet jetzt mit der Äquivalentdistanz; im selben Rennen
  bleiben 12 Ausfälle und 3 OTL. Auf flachen Strecken ändert sich fast
  nichts, die Golden Master stehen unverändert.

### Geändert

- **Der Fokusfahrer im Seitenstreifen steht jetzt im Raster.** Die zwölf
  Kennzahlen lagen in einer umbrechenden Flexbox: Jede Zelle so breit
  wie ihr Inhalt, also in jeder Zeile andere Spaltenpositionen, und der
  Umbruch kam von der Fensterbreite statt von der Bedeutung — „Hydration
  und Glykogen" landeten zusammen, „Rad" allein darunter.

  Jetzt drei gleich breite Spalten, vier Zeilen, drei Gruppen mit einer
  Linie dazwischen: **wo er ist** (gefahren, Rest, Fahrerzeit), **was er
  gerade tut** (Tempo, Steigung, Leistung), **wie es ihm geht** (Form,
  W′, Schlaf, Wasser, Glykogen, Rad). Die Einheit steht in der
  Beschriftung, im Wert nur die Zahl — damit stehen die Ziffern
  untereinander statt hinter unterschiedlich langen Einheiten.

  Nebenbei: Einheiten in Kleinschreibung trotz Versalbeschriftung.
  „KM/H" ist keine Einheit, „km/h" ist eine.
- **Zeitlimit von 1,4 auf 2,0 × Siegerzeit.** Abschnitt 15 führt den
  Wert als offenen Punkt und schlägt 1,4 vor; gemessen war das zu eng.
  Auf den Dolomiten-Vierpässen fielen damit 32 % des Feldes aus der
  Wertung, auf der Alpenüberquerung 20 %, auf der Transkontinental 16 %
  — nicht weil sie nicht angekommen wären, sondern weil die Grenze
  knapp hinter dem Mittelfeld lag. 2,0 ist der Wert aus der Praxis:
  Paris–Brest–Paris gibt 90 Stunden auf eine Siegerzeit von gut 44,
  London–Edinburgh–London 128 auf rund 52. Über den gemessenen Kalender
  steht damit **kein einziger Fahrer mehr auf OTL**; die Regel bleibt
  als Netz für wirklich gebrochene Fahrten.
- Der **Simulationshorizont** rechnet mit 8 statt 11 km/h
  Äquivalenttempo. Mit dem angehobenen Zeitlimit wäre die Schwelle sonst
  auf 22 km/h gestiegen — über dem langsamsten gemessenen Sieger
  (20,7 km/h) —, und die Simulation hätte wieder vor der Wertung
  aufgehört.
- **Punkte bis Rang 150** statt bis Rang 23. Der alte Schwanz lief mit
  −2 je Rang aus und war nach dreizehn Plätzen bei null; bei 250
  Startern fuhren damit 91 % des Feldes um nichts, und ein Vierzigster
  im Ziel stand in der Saisonbilanz da wie einer, der nach zwanzig
  Kilometern aufgegeben hat. Für einen Simulator, dessen halbes Modell
  vom Ankommen handelt, war das die falsche Aussage.

  Der Kopf bleibt unverändert (100, 80, 65 … 28); dahinter läuft der
  Schwanz **exponentiell** aus — 27 auf Rang 11, 22 auf Rang 20, 11 auf
  Rang 50, 3 auf Rang 100, 1 auf Rang 150. Eine Gerade wäre in
  Fünftelpunkten gefallen und hätte zwanzig aufeinanderfolgende Ränge
  auf denselben Wert gelegt.

  Gemessen an der gerechneten Weltserie: **232 von 250 Fahrern** haben
  jetzt Punkte statt gut dreißig. Der Titel wandert dadurch nicht — ein
  Sieg bleibt mit 100 Punkten mehr wert als sieben vierzigste Plätze —,
  aber die Rangliste dahinter sortiert sich neu: Ein Fahrer mit zehn
  Zielankünften ohne Podium steht jetzt auf Rang 3.
- Die **Arbeitsschätzung** für die Kalenderplanung hat zwei Terme statt
  einem. Der alte Wert (15,0 kJ je Äquivalentkilometer) war an drei
  Strecken mit höchstens 13,4 hm/km erhoben und lag über die zehn neuen
  zwischen 15,6 und 27,7 — bis zu 85 % daneben. Neu: 15,1 kJ je
  Kilometer plus 0,76 kJ je Höhenmeter. Der zweite Term ist keine
  Kurvenanpassung: Die potenzielle Energie eines 78-kg-Systems ist
  m·g/1000 = 0,765 kJ je Meter. Dazu 15 % Planungsmarge, weil die
  Schätzung auf der steilsten Strecke weiterhin ein Drittel zu niedrig
  liegt — Trittfrequenz, anaerobe Rampen und Höhe stehen in keiner
  Formel aus Kilometern und Höhenmetern.
- Die Obergrenze des **Rennkoeffizienten** steigt von 2,2 auf 2,9. Sie
  war als Notnagel gegen absurde Eingaben gedacht, hat mit der Weltserie
  aber angefangen zu werten: Alpenüberquerung (1924 km) und
  Transkontinental (2469 km) lagen beide darüber und waren damit exakt
  gleich viel wert. Das längste Rennen des Kalenders war das erste, dem
  die Wertung seine Länge nicht mehr angerechnet hat. Die Spanne reicht
  jetzt von 1,02 bis 2,72 — ein Sieg auf der längsten Strecke wiegt
  zweieinhalb auf der kürzesten.
- Alle JSON-Stammdaten werden **unteilbar** geschrieben (erst daneben,
  dann umbenannt) — Rennen, Pool, Saison und Karriere. Seit ein Rennen
  auch während des Laufens gespeichert wird, überschneidet sich das
  Schreiben mit dem Lesen; bei Pool und Karriere tat es das schon
  vorher, weil der Arbeiterthread schreibt, während der Anfragethread
  liest. Genau daran ist im CI einmal ein Test gescheitert.

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
