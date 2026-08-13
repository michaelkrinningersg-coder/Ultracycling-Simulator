# Game Design Document — Ultracycling Live Telemetry Simulator

**Arbeitstitel:** UltraSim
**Version:** 0.7 — GPX-Import, Höhenprofil statt Karte
**Zweck:** Grundlage für die Umsetzung mit Claude Code
**Status:** Grundsatzentscheidungen getroffen (siehe Abschnitt 15)

> Dieses Dokument ist die Vorgabe, nicht der Umsetzungsstand. Was davon
> gebaut ist, steht im [README](../README.md); Abweichungen sind dort
> benannt und begründet.

---

## 1. Vision

Ein Simulator, in dem definierte Fahrer eine reale Strecke
(OpenStreetMap-Routing zwischen frei gewähltem Start und Ziel) im
Einzelzeitfahren absolvieren. Der Reiz liegt nicht im aktiven Steuern,
sondern im Zuschauen und Auswerten: Eine Live-Telemetrie im Stil von
Wintersport-Übertragungen (Biathlon, Ski Alpin, Skispringen) zeigt, wie
sich der beobachtete Fahrer an jedem Split gegen das Feld einordnet.

### Kernschleife

1. Strecke im Editor definieren (Start, Ziel, ggf. Zwischenpunkte)
2. Startliste zusammenstellen, Startintervalle festlegen
3. Rennen starten → Live-Telemetrie beobachten, Fahrer und Splits frei wählen
4. Zielergebnis, Punktevergabe, Gesamtrangliste
5. Nächstes Rennen der Saison → Form und Ermüdung wirken fort

### Design-Leitsätze

- **Plausibilität vor Genauigkeit.** Das Physikmodell muss sich richtig anfühlen, nicht promillegenau sein.
- **Deterministisch reproduzierbar.** Jedes Rennen hat einen Seed; gleicher Seed = gleiches Ergebnis. Unverzichtbar für Debugging und Balancing.
- **Simulation und Darstellung sind getrennt.** Die Simulation läuft schnell durch oder in Echtzeit; die UI konsumiert nur einen Event-Strom.
- **Dramaturgie ist Feature.** Die Telemetrie ist die eigentliche Spielerfahrung, nicht Beiwerk.

---

## 2. Scope

### Festgelegter Rahmen

- Distanzen 150–2500 km, in drei Klassen (siehe unten)
- **Supported** — Begleitfahrzeug, Servicepunkte, geplante Verpflegung
- **Reine Simulation ohne Spieler.** Es gibt keine Eingriffsmöglichkeit; alle Entscheidungen trifft das Strategiemodul aus den Fahrerattributen (Abschnitt 7). Der Nutzer ist Beobachter und Kurator: Er baut Strecken, Fahrer und Kalender, dann schaut er zu.
- Fiktive Fahrer, erzeugt durch Generator, nachbearbeitbar im Editor
- Feldgröße 250 Starter je Rennen, gezogen aus einem gemeinsamen Fahrerpool; das Telemetrie-Board zeigt davon ein Fenster von 41 Zeilen um den Fokusfahrer
- Ziel-DNF-Quote 5–10 % — Dramatik entsteht durch Zeitverlust, nicht durch Ausfälle

### Distanzklassen

| Klasse | Distanz | Dauer | Prägende Mechanik |
|---|---|---|---|
| Kurz | 150–400 km | 5–15 h | Pacing und Verpflegung; höchstens eine Nacht, kein Schlaf |
| Mittel | 400–1200 km | 15–50 h | Erste Schlafentscheidung, Nachttief, Ermüdungskurve |
| Ultra | 1200–2500 km | 50–110 h | Mehrere Schlafzyklen, kumulative Ermüdung, Materialverschleiß, Magenprobleme |

Die Klasse steuert Split-Dichte, Schlafplanung, Servicepunkt-Abstände und
den Rennkoeffizienten in der Wertung. Sie wird aus Distanz und
Höhenmetern automatisch abgeleitet.

### MVP (Meilenstein 1–4)

GPX-Import mit Segmentierung, Physikmodell, Fahrerattribute, Form,
Splits, Einzelstart, Live-Telemetrie-Board, Höhenprofil-Anzeige,
Ergebnisliste.

### Ausbaustufe

Verpflegung/Glykogen, Schlafstrategie, Wetter und Wind, Tag-Nacht-Zyklus,
Pannen, Radwechsel-Feintuning, Saisonkalender, Fahrerentwicklung über
Jahre, Replay-Export.

### Ausdrücklich nicht im Scope

Windschatten und Gruppendynamik (Einzelstart → physikalisch nicht nötig),
Steuerung einzelner Fahrer während des Rennens, Mehrspielerbetrieb.

Windschatten ist die größte bewusst weggelassene Mechanik. Falls später
Massenstart-Rennen dazukommen sollen, muss das Physikmodell dafür einen
Hook bekommen (`draft_factor` auf CdA) — der Platz dafür ist im Modell
unten schon vorgesehen.

---

## 3. Streckenerzeugung

### 3.1 Routing

**Entschieden:** Strecken kommen als GPX-Datei herein. Der Import erzeugt
daraus alles, was die Simulation braucht (Abschnitt 3.6). Ein
Routing-Dienst wird für den Betrieb nicht benötigt — die Strecke wird
außerhalb geplant (komoot, BRouter-Web, Strava, GPS-Aufzeichnung) und
dann importiert.

Falls später doch automatisch geroutet werden soll (Streckeneditor mit
Start-/Zielklick), bleibt GraphHopper die erste Wahl:

| Option | Bewertung |
|---|---|
| GraphHopper self-hosted | Bestes Paket: Routing plus integrierte Höhendaten (SRTM/Copernicus wird beim Import in den Graph gebacken), liefert 3D-Geometrie direkt, kein Rate-Limit, Java-Docker-Container, Deutschland-Extrakt (Geofabrik) ca. 1 GB RAM. Erste Wahl. |
| Valhalla self-hosted | Ebenfalls sehr gut, liefert Elevation und edge-Attribute (Oberfläche, Straßenklasse) sehr detailliert, aber aufwendigerer Setup. Zweite Wahl. |
| BRouter | Von Radfahrern für Radfahrer, hervorragende Profile, aber Ökosystem sperriger. |
| OpenRouteService (API) | Bequem, aber Rate-Limits und Online-Abhängigkeit. Gut für einen schnellen Prototypen. |
| OSRM | Schnellstes Routing, aber keine Höhendaten. Nur mit separater DEM-Abfrage sinnvoll. |

Ergebnis des Routings: Polyline aus (lat, lon, ele)-Punkten, plus
Way-Attribute pro Kante — die brauchen wir später für Oberfläche und
Straßenklasse.

### 3.2 Höhendaten — die entscheidende Frage

| Quelle | Auflösung | Abdeckung | Anmerkung |
|---|---|---|---|
| Copernicus DEM GLO-30 | 30 m | global | Aktuell bestes freies globales DEM, ESA, deutlich sauberer als SRTM. **Empfehlung.** |
| SRTM v3 | 30 m (USA/EU), 90 m Rest | 60°N–56°S | Der Klassiker, Standard in GraphHopper. Ausreichend, aber rauschiger. |
| DGM1 / DGM5 (Landesämter) | 1 m / 5 m | Bundesländer, Open Data | Extrem genau, aber riesig und nur regional. Für ein globales Spiel unpraktisch, für eine „Heimatstrecke" ein Leckerbissen. |
| Mapbox Terrain-RGB | variabel | global | Kacheln, praktisch fürs Frontend-Rendering, kommerziell limitiert. |

**Empfohlenes Vorgehen:** GraphHopper mit Copernicus GLO-30 oder SRTM
konfigurieren → Höhen kommen fertig aus dem Routing. Alternativ
OpenTopoData als Docker-Container mit lokalen GLO-30-Kacheln und
Batch-Abfrage (bis 100 Punkte pro Request).

### 3.3 Glättung — bitte nicht überspringen

Rohe DEM-Höhen liefern unbrauchbare Momentansteigungen: ±1 m
Höhenrauschen auf 20 m Punktabstand ergibt scheinbare 5 % Steigung im
ebenen Gelände. Ohne Glättung fährt das Feld dauernd Achterbahn.

Pipeline:

1. Resampling der Route auf feste Distanzschritte (10 m).
2. Glättung der Höhenreihe mit Savitzky-Golay (window ≈ 21 Punkte, Ordnung 2) oder gleitendem Median. Das erhält Passhöhen und Senken, entfernt aber das Rauschen.
3. Steigung aus der geglätteten Reihe: `grade = Δele / Δdist`, geclippt auf ±25 %.
4. Höhenmeter-Summe erst nach der Glättung berechnen und mit einer Mindestschwelle (z. B. 2 m) akkumulieren, sonst explodiert die Summe.

### 3.4 Segmentierung

Die Route wird in Segmente zerlegt, die die Simulationseinheit bilden:

- Ein Segment endet, wenn sich die mittlere Steigung um mehr als ~1,5 % ändert oder nach spätestens 500 m.
- Jedes Segment trägt: Länge, Δ Höhe, mittlere Steigung, Oberfläche, Straßenklasse, Kurvigkeit (Summe der Richtungsänderungen pro km), Exposition (für Wind), Höhe ü. NN, Anzahl Ampeln und Ortslage-Flag.

Ampeln und Kreuzungen werden beim Streckenbau aus OSM extrahiert
(`highway=traffic_signals`, `highway=stop`, `crossing`) und den
Segmenten zugeordnet. Sie sind der Grund, warum die gleiche Distanz
durch eine Stadt Minuten mehr kostet als über Land — ein Effekt, der ohne
diese Daten fehlen würde und den man sofort vermisst.

**Klassifikation:** flach (< 2 %), welliger Anstieg, Anstieg (≥ 3 % über
≥ 1 km), Steilrampe (> 10 %), Abfahrt, Steilabfahrt.

Segmente werden zu **Anstiegen** gruppiert (zusammenhängende Kette mit
≥ 3 % Mittelwert). Ein Anstieg bekommt Länge, Höhenmeter,
mittlere/maximale Steigung und eine abgeleitete Kategorie (HC/1–4 nach
dem üblichen Höhenmeter × Steigung-Schema). Diese Objekte steuern den
Radwechsel.

### 3.5 Splits

Automatische Splits mit distanzabhängigem Abstand:

| Streckenlänge | Split-Abstand | Anzahl |
|---|---|---|
| < 400 km | 10 km | 15–40 |
| 400–1200 km | 25 km | 16–48 |
| > 1200 km | 50 km | 24–50 |

Ziel ist stets ein Feld von 30–50 Splits — genug für Dramaturgie, wenig
genug für ein lesbares Board und eine kompakte SplitTime-Tabelle.

Zusätzlich automatische Splits an markanten Punkten: Gipfel jedes
kategorisierten Anstiegs, Kontrollpunkte, Ziel. Splits sind vom Nutzer im
Editor nachträglich verschiebbar/ergänzbar.

Datenmodell: `Split(id, route_id, dist_m, name, type)` — die Telemetrie
hängt vollständig an diesen Objekten.

### 3.6 GPX-Import

Der Importer ist das Nadelöhr zwischen realer Welt und Simulation. Er
läuft als CLI auf dem Entwicklungsrechner, nicht in der Anwendung.

```
python -m ultrasim.geo.gpx_import strecke.gpx -o data/routes/strecke.json
```

Verarbeitungskette:

1. **Parsen** — `trkpt`, ersatzweise `rtept`/`wpt`; Namespace wird aus der Datei bestimmt, nicht angenommen (nicht jedes Werkzeug schreibt GPX 1.1)
2. **Distanz** kumulativ über Haversine
3. **Duplikate entfernen** — GPS-Pausen erzeugen Punkte ohne Ortsveränderung; die würden später Division durch null auslösen
4. **Fehlende Höhen** linear interpolieren; fehlt die Höhe durchgängig, bricht der Import mit klarer Meldung ab
5. **Resampling** auf 10-m-Raster — ab hier ist alles gleichmäßig und vektorisierbar
6. **Glättung** mit Savitzky-Golay (210 m Fenster, Ordnung 2)
7. **Steigung** aus der geglätteten Höhe, geclippt auf ±25 %
8. **Segmentierung**, Anstiegserkennung, Kategorisierung
9. **Splits und Servicepunkte** nach Distanzklasse
10. **Speichern** als gzip-komprimiertes JSON

**Warum Schritt 6 nicht verhandelbar ist** — gemessen an einer
60-km-Teststrecke mit typischem DEM-Rauschen (σ = 1,2 m):

| | ungeglättet | geglättet |
|---|---|---|
| Höhenmeter | 1465 m | 859 m |
| Ø Betrag der Steigung im flachen Abschnitt | 4,48 % | 0,94 % |

Ohne Glättung würde das Feld im Flachen dauerhaft gegen eine scheinbare
4,5-%-Steigung treten und die Höhenmeter um 70 % überzeichnet. Jede
Zeitberechnung wäre wertlos.

**Speicherformat.** Naiv geschrieben wiegt eine 2500-km-Strecke mit
10-m-Raster ~18 MB JSON — zu viel, um mehrere davon in eine EXE zu
bündeln. Drei Maßnahmen drücken das unter 2 MB:

- `dist` wird nicht gespeichert, sondern ergibt sich aus `raster_m × Index`
- Höhen als Dezimeter-Integer statt Fließkomma (10 cm Auflösung genügt vollauf)
- `grade` wird nicht gespeichert, sondern beim Laden aus der Höhe gerechnet
- lat/lon nur alle 1000 m — sie werden für Sonnenstand, Windrichtung und Segmentpeilung gebraucht, nicht für die Physik
- das Ganze gzip-komprimiert

**Koordinaten bleiben nötig, auch ohne Karte.** Ohne lat/lon gäbe es
keine Segmentpeilung (Windrichtung), keinen Sonnenauf- und -untergang und
keine Möglichkeit, später Ampelpositionen per Overpass-Abfrage
nachzurüsten. Die grobe Auflösung von 1 km reicht dafür vollständig.

---

## 4. Physikmodell

### 4.1 Grundgleichung

Leistung an der Kurbel, die zum Vortrieb nötig ist:

```
P_ges = ( F_roll + F_grav + F_air + F_beschl ) · v / η

F_roll   = Crr · m_ges · g · cos(atan(grade))
F_grav   = m_ges · g · sin(atan(grade))
F_air    = ½ · ρ · CdA · (v + v_wind_gegen)²
F_beschl = m_ges · a          (nur bei Tempoänderung)
η        ≈ 0,975 (Antriebsstrangverluste)
```

`m_ges` = Fahrer + Rad + Gepäck/Ausrüstung. ρ aus
Luftdruck/Temperatur/Höhe: `ρ = p / (R_spez · T)`. Höhe wirkt real
spürbar — auf 2000 m fährt man bei gleicher Leistung im Flachen messbar
schneller, verliert aber Aerobleistung (siehe 6.6).

### 4.2 Von Leistung zu Geschwindigkeit

Die Gleichung ist kubisch in v. Pro Tick: Newton-Raphson (3–5
Iterationen) oder direkt eine Euler-Integration über die Beschleunigung:

```
a     = (P·η/v − F_roll − F_grav − F_air) / m_ges
v_neu = v + a · Δt
```

Die Integration ist robuster (kein Löser nötig, Trägheit ist gratis mit
dabei) und macht Antritte und Anstiegsübergänge automatisch plausibel.
**Empfehlung: Euler mit Δt = 1 s.**

### 4.3 Abfahrten

Bergab greift eine eigene Logik, sonst werden Abfahrten unrealistisch schnell:

- Fahrer tritt nur bis zu einer Trittfrequenzgrenze mit (ab ~65 km/h effektiv keine Leistung mehr).
- Kurvenlimit: `v_max = sqrt(µ · g · r)` mit Radius r aus der Kurvigkeit des Segments; skaliert mit dem Attribut Abfahrtstechnik und dem Risikobereitschafts-Wert.
- Nässe senkt µ deutlich.
- Ein globaler Sicherheitsdeckel (z. B. 85 km/h) verhindert Ausreißer.

### 4.4 Richtwerte

| Größe | Wert |
|---|---|
| Crr Asphalt gut, 28 mm Rennreifen | 0,0040 |
| Crr Asphalt rau | 0,0055 |
| Crr Schotter | 0,0090 |
| CdA Zeitfahrposition | 0,21–0,26 |
| CdA Straßenrad Unterlenker | 0,28–0,32 |
| CdA Straßenrad Oberlenker/Anstieg | 0,36–0,40 |
| CdA mit Ultra-Gepäck (Aufbauten, Taschen) | +0,02 bis +0,05 |
| Rad TT inkl. Zubehör | 9,0 kg |
| Rad Straße | 7,5 kg |
| Ultra-Gepäck | 3–8 kg |

CdA wird aus Körpergröße/Gewicht skaliert
(`CdA ≈ k · A_frontal`, `A_frontal ≈ 0,0276 · h^0,725 · m^0,425`) und dann
mit Rad- und Positionsfaktoren multipliziert. So bekommen kleine leichte
Fahrer automatisch den aerodynamischen Vorteil und die Kletterstärke,
große schwere den Flach- und Abfahrtsvorteil.

---

## 5. Fahrermodell

### 5.1 Stammdaten

Name, Team, Nationalität, Geburtsdatum/Alter, Größe (cm), Gewicht (kg),
FTP (W), Geschlecht. Abgeleitet: W/kg, Frontalfläche, CdA-Basis.

### 5.2 Attribute

Skala 0–100, Mittelwert 50, wirken als Modifikatoren — nie als harte
Multiplikatoren auf die Endzeit, sondern immer auf physikalische
Zwischengrößen.

| Attribut | Wirkung |
|---|---|
| Flach | Leistungshaltefähigkeit auf < 2 %, CdA-Bonus (Positionsdisziplin) |
| Berg | Leistung relativ zum Gewicht am Anstieg, geringerer Wirkungsgradverlust bei niedriger Trittfrequenz |
| Ausdauer | Flachheit der Ermüdungskurve über Stunden; Skalierung der Kurve P_haltbar(t) |
| Spritzigkeit | Höhe und Regenerationsrate von W′ (anaerobe Kapazität), zählt an Steilrampen und Antritten |
| Fettverbrennung | Anteil Fett an der Energiebereitstellung bei gegebener Intensität → schont Glykogen |
| Kohlenhydratverbrennung | Maximale KH-Oxidationsrate (g/h) → wie viel Verpflegung überhaupt verwertbar ist |
| Schlaftoleranz | Wie stark Schlafdefizit auf Leistung und Fehlerrate schlägt |

Ergänzungen (die Ultracycling-spezifischen zuerst):

| Attribut | Wirkung | Priorität |
|---|---|---|
| Magenverträglichkeit / GI-Robustheit | Obergrenze der tatsächlich aufgenommenen kcal/h, Risiko von Magenproblemen mit Leistungseinbruch. Das häufigste reale DNF-Motiv nach Schlaf. | ★★★ |
| Mentale Widerstandsfähigkeit | Reduziert Leistungsverlust in der Nacht und in den „Tiefpunkt"-Phasen; senkt Aufgabewahrscheinlichkeit | ★★★ |
| Pacing-Disziplin | Wie gut hält sich der Fahrer an sein Zielprofil. Niedrig = überzieht früh, zahlt spät | ★★★ |
| Hitzetoleranz | Leistungsabfall pro °C über ~25 °C, Schweißrate | ★★★ |
| Kältetoleranz | Leistungsabfall unter ~8 °C, betrifft besonders Nachtabfahrten | ★★ |
| Nässe-/Wetterresistenz | Kombiniert Kälte, Sicht, Kurventempo bei Regen | ★★ |
| Sitzkomfort / Saddle-Sore-Resistenz | Ab Stunde ~10 wachsende Positions- und Leistungseinbußen | ★★ |
| Regeneration | Erholungsrate im Schlaf und in Pausen, Wirkung zwischen Rennen | ★★★ |
| Servicedisziplin / Boxenstopp-Effizienz | Dauer und Streuung aller Stopps | ★★★ |
| Abfahrtstechnik | Kurvengeschwindigkeit (µ- und Radius-Faktor) | ★★★ |
| Risikobereitschaft | Skaliert Abfahrtstempo und Sturz-/Fehlerwahrscheinlichkeit | ★★ |
| Navigationssicherheit | Wahrscheinlichkeit und Länge von Verfahrern | ★★ |
| Mechanikerfähigkeit | Dauer einer Pannenbehebung | ★ |
| Materialpflege | Wahrscheinlichkeit technischer Defekte | ★ |
| Seitenwindfestigkeit | Tempoverlust bei starkem Cross-Wind, koppelt mit Körpergröße | ★ |
| Oberflächenkompetenz | Tempo und Crr-Malus auf schlechten Belägen | ★ |
| Höhenanpassung | Aerobverlust pro 1000 Höhenmeter ü. NN | ★ |
| Erfahrung | Globaler kleiner Bonus auf Entscheidungen; wächst über Saisons | ★★ |
| Konstanz | Streuung der Tagesform — der berechenbare vs. der launische Fahrer | ★★★ |

**Empfehlung:** Für den MVP die sieben bestehenden plus die
★★★-Attribute. Der Rest lässt sich später ergänzen, ohne das Modell
umzubauen, wenn alle Attribute konsequent als Modifikatoren auf
physikalische Größen wirken.

### 5.3 Fahrergenerator

Alle Fahrer sind fiktiv und werden erzeugt, nicht getippt. Der Generator
arbeitet mit Archetypen, die Attributverteilungen vorgeben; anschließend
ist jeder Wert im Editor überschreibbar.

| Archetyp | Prägung |
|---|---|
| Zeitfahr-Spezialist | Flach ↑↑, Aero ↑, Berg ↓, gut auf 150–400 km |
| Kletterer | Berg ↑↑, leicht, Flach ↓ |
| Diesel / Ultra-Maschine | Ausdauer ↑↑, Konstanz ↑↑, Pacing-Disziplin ↑↑, Spitzenleistung ↓ |
| Schlafgeiziger | Schlaftoleranz ↑↑, mentale Widerstandsfähigkeit ↑, Regeneration ↓ |
| Fettverbrenner | Fettverbrennung ↑↑, niedrige Intensität sehr effizient, Spritzigkeit ↓ |
| Draufgänger | Risikobereitschaft ↑↑, Abfahrtstechnik ↑, Pacing-Disziplin ↓ — gewinnt oder scheitert |
| Allrounder | alles nahe 50, wenige Ausreißer |
| Rohdiamant | jung, hohes Potenzial, niedrige Erfahrung und Konstanz |

**Erzeugung:** Archetyp wählen → Attribute aus Normalverteilungen um die
Archetyp-Mittelwerte ziehen → physiologische Plausibilitätsprüfung
(Größe/Gewicht/FTP müssen zueinander passen; W/kg im Bereich 3,5–6,0) →
Name und Nationalität aus nationsspezifischen Namenslisten → Team
zuordnen.

**Wichtig fürs Balancing:** Ein Gesamtpotenzial-Budget verhindert
Überfahrer. Die Summe der gewichteten Attribute wird auf einen Zielwert
normiert, sodass jede Stärke irgendwo bezahlt wird. Ohne dieses Budget
bekommst du entweder graue Einheitsfahrer oder einen, der alles gewinnt.

### 5.4 Formmodell

Drei Ebenen, multiplikativ auf die effektive FTP:

```
FTP_eff = FTP_basis · f_saison · f_tag · f_abschnitt · f_ermüdung · f_umwelt
```

| Ebene | Bereich | Erzeugung |
|---|---|---|
| Saisonform | 0,90 – 1,08 | Kurve über den Kalender, mit Formhöhepunkten; verändert sich langsam |
| Tagesform | 0,93 – 1,07 | Zufallsziehung am Renntag, Streuung invers zum Attribut Konstanz |
| Abschnittsform | 0,96 – 1,04 | Ornstein-Uhlenbeck-Prozess über die Distanz mit langer Korrelationslänge (80–150 km), nicht unabhängige Ziehung pro Segment |

Der Abschnitts-Zufall als OU-Prozess ist der wichtigste Punkt hier: Er
erzeugt echte „gute Phasen" und „Tiefpunkte" von realistischer Länge
statt Rauschen.

**Warum die Korrelationslänge so groß sein muss:** Bei einem
2500-km-Rennen mitteln sich kurzfristige Schwankungen praktisch
vollständig weg — ein Prozess mit 5 km Korrelationslänge verschwindet
über 500 Abschnitte statistisch zu null. Erst bei 80–150 km bleiben pro
Rennen nur ~20 unabhängige Phasen übrig, und dann macht es einen
sichtbaren Unterschied, ob ein Fahrer seine schlechte Phase im Flachen
oder im Schlussanstieg hat. Die Korrelationslänge sollte mit der
Streckenlänge skalieren (Vorschlag: `L_korr ≈ 0,06 × Streckenlänge`,
gedeckelt auf 40–200 km).

### 5.5 Ermüdung

Zwei gekoppelte Systeme:

- **W′** (anaerobe Kapazität, ~20 kJ): entlädt sich über FTP, lädt darunter wieder auf. Regelt Steilrampen und Antritte. Skaliert mit Spritzigkeit.
- **Langzeitermüdung:** haltbare Leistung sinkt logarithmisch mit der kumulierten Belastung. Ansatz: `f_ermüdung = 1 − k · (kJ_kumuliert / kJ_kapazität)^p`, mit kJ_kapazität skaliert durch Ausdauer und Regeneration. Zusätzlicher Term aus Schlafdefizit und Sitzzeit.

---

## 6. Physiologie und Ultra-Mechaniken

### 6.1 Energiehaushalt

| Speicher | Startwert | Verbrauch | Nachfüllung |
|---|---|---|---|
| Glykogen | ~1600–2200 kcal, skaliert mit Gewicht/Muskelmasse | KH-Anteil der Leistung | Nur über Zufuhr, begrenzt durch KH-Verbrennung und Magenverträglichkeit (real 60–120 g/h) |
| Fett | praktisch unbegrenzt | Fettanteil, steigt mit Fettverbrennung, sinkt mit Intensität | — |
| Hydration | 0 bis −4 % Körpergewicht | Schweißrate aus Intensität, Temperatur, Luftfeuchte | Trinken, begrenzt durch Magenaufnahme |

**Substratverteilung:** Der KH-Anteil steigt mit der relativen Intensität
(P / FTP). Vorschlag: bei 55 % FTP ca. 40 % KH, bei 75 % ca. 65 %, bei
90 % ca. 85 %, jeweils verschoben durch das Attribut Fettverbrennung.

**Der „Hungerast":** Fällt Glykogen unter ~15 %, sinkt die haltbare
Leistung hart (bis −30 %). Das ist ein dramaturgisch wertvolles Ereignis
— es sollte in der Telemetrie sichtbar markiert werden.

**Dehydration:** ab −2 % Körpergewicht ca. −2 % Leistung je weiterem
Prozent, verschärft durch Hitze.

### 6.2 Schlaf

Jeder Fahrer hat eine Schlafstrategie: z. B. „4 h am Stück nach 20 h",
„90 min alle 18 h", „polyphasisch 20 min alle 6 h", „durchfahren bis
30 h".

Schlafdruck wächst mit der Wachzeit, wird durch Schlaf abgebaut
(Effizienz aus Regeneration). Wirkung: Leistungsmalus, erhöhte
Navigations- und Sturzfehlerrate, ab kritischem Wert erzwungener
Notschlaf am Straßenrand.

**Zirkadianer Faktor:** zwischen 02:00 und 05:00 Fahrer-Eigenzeit ist der
Malus deutlich stärker — das erzeugt die typische Nachtdramatik. Da alle
Fahrer in ihrer Eigenzeit zur selben Uhrzeit starten, erreichen sie ihre
erste Nacht nach derselben Fahrzeit; wer dann wo auf der Strecke ist,
hängt allein vom Tempo ab.

### 6.3 Stopps und Service (supported)

Die Versorgung ist nicht ortsabhängig, sondern teamgeplant. Das
verlagert die Spannung von „finde ich nachts eine Tankstelle?" zu „war
der Plan des Teams gut?".

**Servicepunkte:** Das Begleitfahrzeug trifft den Fahrer in geplanten
Abständen (alle 60–120 km, klassenabhängig).

| Typ | Basisdauer | Ort |
|---|---|---|
| Kurzservice (Flaschen, Riegel) | 40–90 s | Servicepunkt, oft rollend |
| Vollservice (Essen, Kleidung, Wäsche) | 5–15 min | Servicepunkt |
| Schlafstopp | 20 min – 4 h | Servicepunkt oder Fahrzeug |
| Radwechsel | 45 s ± | Servicepunkt |
| Reparatur | 2–20 min | überall, mit Crew schneller |
| Natur/Toilette | 1–4 min | überall |

Tatsächliche Dauer = `geplant · (1 + N(0, σ)) · f_servicedisziplin`

**Servicedisziplin** ist ein Team-Attribut (0–100) und wirkt auf alle
Fahrer des Teams. Ein starker Fahrer in einem schlampigen Team verliert
über 2500 km leicht 30–60 Minuten, die keine Beinarbeit zurückholt.
Faustformel: `f_service = 1,25 − 0,005 × Servicedisziplin`.

### 6.4 Material und Radwechsel

| | Zeitfahrrad | Straßenrad |
|---|---|---|
| CdA | 0,21–0,26 | 0,30–0,36 |
| Gewicht | 9,0 kg | 7,5 kg |
| Komfortmalus/h | höher | niedriger |
| Steigungsmalus | Wirkungsgradverlust > 6 % | keiner |

**Wechsellogik:** Der Wechsel wird vor einem Anstieg ausgelöst, wenn
Länge ≥ 2 km oder max. Steigung > 10 %. Zusätzlich muss geprüft werden,
ob sich der Wechsel lohnt:
`Zeitgewinn_Anstieg > 2 · Wechseldauer + Zeitverlust_Rückwechsel`. Sonst
wechseln Fahrer bei jedem 2,1-km-Hügel mit 3 % und verlieren netto Zeit.

**Supported-Regel:** Der Radwechsel ist an einen Servicepunkt gebunden.
Das Strategiemodul entscheidet am Servicepunkt, welches Rad für den
kommenden Abschnitt das schnellere ist — nicht pro Einzelanstieg.
Summiere die geschätzte Zeit für beide Radvarianten über den ganzen
Abschnitt und wähle die kleinere.

### 6.5 Ereignisse und Zustände

Zwei Wirkungsarten, strikt getrennt:

- **Sofortwirkung:** einmaliger Zeitverlust in Sekunden (Ampel, Panne, Radwechsel)
- **Zustand:** ein Modifikator, der über eine Strecke oder Zeit nachwirkt

```python
RiderCondition(
    typ,                # z. B. "magen", "sturzfolgen", "schlafdefizit"
    start_t, dauer,     # in Zeit ODER Distanz
    wirkung = {         # multiplikative Modifikatoren, 1.0 = neutral
        "ftp": 0.94,
        "kcal_aufnahme": 0.5,
        "abfahrtstempo": 0.85,
        "crr": 1.0,
    },
    abklingen = "linear" | "sofort",
)
```

Alle aktiven Zustände werden pro Tick multipliziert und fließen in
`f_umwelt` ein. Damit ist jedes Ereignis ohne Sonderfall im Physikcode
abbildbar — neue Ereignisarten sind reine Datenzeilen.

#### Ereigniskatalog

| Ereignis | Auslöser / Rate | Sofortwirkung | Nachwirkung |
|---|---|---|---|
| Rote Ampel | aus OSM, Trefferwahrscheinlichkeit ~45 % | 0–70 s | keine |
| Ortsdurchfahrt | Segmente in Ortslage | 2–8 % Zeitverlust | keine |
| Reifenpanne | 1 pro ~450 km, ×2,5 Schotter, ×1,6 Nässe | 3–12 min, mit Crew 1,5–4 min | keine |
| Mechanischer Defekt | 1 pro ~1500 km | 5–25 min | Ersatzrad ggf. schlechter |
| Lichtausfall | nur nachts, selten | 2–6 min | −15 % Abfahrtstempo |
| Verfahren | ×3 nachts, ×2 bei Schlafdruck | Umweg 0,5–5 km | −2 % FTP für 30 min |
| Sturz (leicht) | Risiko, Nässe, Schlafdruck | 2–10 min | −3…−8 % FTP, −20 % Abfahrt für 50–200 km |
| Sturz (schwer) | ~8 % aller Stürze | — | **DNF** |
| Magenprobleme | Magenverträglichkeit, Hitze, Zufuhrrate | 3–20 min Stopp | kcal-Aufnahme −40…−70 % für 2–6 h. **Der eigentliche Killer.** |
| Langer Radwechsel | Schwanz der Verteilung (5 %) | 3–8 min statt 45 s | keine |
| Fehlplanung | invers zu Pacing-Disziplin und Erfahrung | keine | −5…−12 % FTP ab km X, über 100–300 km |
| Suboptimaler Schlaf | Wurf bei jedem Schlafstopp | keine | Schlafdruck nur zu 40–80 % abgebaut |
| Suboptimale Ernährung | Zufuhr über 3 h unter Plan | keine | −4…−10 % FTP bis zum Ausgleich |
| Hitzeeinbruch | Temperatur über Schwelle | keine | −5…−15 % FTP für die Hitzephase |
| Sperrung / Umleitung | selten | 5–20 min | keine |

**Abschnittsweise Wirkung:** Die Nachwirkung wird in Distanz statt in
Zeit definiert, wo das sinnvoll ist (Sturzfolgen, Fehlplanung,
Ersatzrad). Für physiologische Zustände (Magen, Schlaf, Hitze) ist Zeit
die richtige Einheit.

#### DNF-Kalibrierung

| Klasse | Ziel-DNF |
|---|---|
| Kurz (150–400 km) | 1–2 % |
| Mittel (400–1200 km) | 4–7 % |
| Ultra (1200–2500 km) | 8–12 % |

Das liegt bewusst deutlich unter der Realität (echte 2500-km-Rennen:
30–50 %). **Die Dramatik muss aus Zeitverlust kommen, nicht aus
Ausfällen.** Nur diese Wege führen zum DNF: schwerer Sturz, schwerer
mechanischer Defekt ohne Ersatz, Zeitlimit überschritten, oder ein
kumulativer Aufgabe-Score aus (Rückstand × Ermüdung × Magenzustand) über
Schwelle, gedämpft durch mentale Widerstandsfähigkeit.

**Balancing-Test:** 200 Rennen im Batch, DNF-Quote je Klasse prüfen. Das
ist der erste Golden-Master-Test, der gebaut werden sollte.

### 6.6 Umwelt

Wetter pro Rennen: Temperaturtagesgang, Niederschlagswahrscheinlichkeit,
Wind (Richtung + Stärke). Wind wirkt richtungsabhängig: aus der
Segment-Peilung und der Windrichtung ergibt sich die
Gegenwind-/Seitenwindkomponente auf F_air.

Tag-Nacht: Sonnenauf-/-untergang aus Datum und Koordinate, ausgewertet in
Fahrer-Eigenzeit.

**Zweischichtiges Wettermodell:** ortsgebundene Schicht (Höhe, Region,
Exposition — für alle gleich) plus zeitgebundene Schicht in Eigenzeit
(Tagesgang, Regenphasen, Windverlauf — je Fahrer, aber identischer
Ablauf).

Höhe ü. NN: über ~1500 m sinkt die aerobe Leistung um ca. 6–8 % je
1000 m, gedämpft durch Höhenanpassung; gleichzeitig sinkt der
Luftwiderstand.

---

## 7. Renn-KI (Strategiemodul)

Weil es keinen Spieler gibt, ist dieses Modul das eigentliche Herz des
Spiels. Seine Qualität entscheidet darüber, ob das Rennen glaubwürdig
wirkt oder wie ein Zufallsgenerator.

### 7.1 Rennplan (vor dem Start, einmal je Fahrer)

- **Ziel-Intensität** als Anteil der FTP über die Distanz — bei 200 km ca. 78–85 %, bei 2500 km ca. 55–62 %, verschoben durch Ausdauer und Erfahrung
- **Leistungsprofil** über die Strecke: Anstiege bekommen einen Aufschlag, Flachpassagen einen Abschlag, Abfahrten null
- **Schlafplan:** Zeitpunkte und Dauer
- **Verpflegungsplan:** kcal/h Zielwert, gedeckelt durch KH-Verbrennung und Magenverträglichkeit
- **Radplan:** Vorauswahl je Abschnitt zwischen den Servicepunkten

Der Plan ist absichtlich unvollkommen: Ein Fahrer mit niedriger Erfahrung
oder niedriger Pacing-Disziplin plant zu ambitioniert. Genau daraus
entstehen die späteren Einbrüche.

### 7.2 Laufende Anpassung (jeden Tick bzw. alle 60 s)

```
if glykogen < 25 %:            Intensität senken, Zufuhr erhöhen
if schlafdruck > kritisch:     Notschlaf einplanen
if rückstand > toleranz:       Intensität erhöhen (riskant!)
if hitze > schwelle:           Intensität senken, Trinkmenge hoch
if w_prime < 20 %:             an Rampen nicht mehr überziehen
```

Wie diszipliniert dieser Regelkreis befolgt wird, hängt an
Pacing-Disziplin und mentaler Widerstandsfähigkeit.

### 7.3 Warum das reicht

Der Reiz einer spielerlosen Simulation liegt darin, dass
Persönlichkeiten sichtbar werden: Der Diesel, der stur seinen Plan fährt
und ab Stunde 30 alle einsammelt. Der Draufgänger, der die erste Nacht
durchfährt und in der zweiten kollabiert. Der Schlafgeizige, der 90
Minuten spart und sie über 400 km zurückholt.

**Debug-Anforderung:** Jede KI-Entscheidung wird als Event mit Begründung
geloggt („Radwechsel abgelehnt: geschätzter Gewinn 38 s < Kosten 95 s").

---

## 8. Rennsimulation

### 8.1 Ablauf

Tick: 1 s Simulationszeit. Ein 2500-km-Rennen dauert ~110 h; mit 250
Fahrern sind das ~99 Mio. Fahrer-Ticks.

**Der entscheidende Punkt bei 250 Fahrern:** Wenn über die Fahrer
vektorisiert wird, ist die Schleifenlänge die Tick-Anzahl (~400.000),
nicht die Fahrerzahl. Ein Array mit 250 Elementen zu verrechnen kostet
praktisch dasselbe wie eines mit 41 — der NumPy-Overhead pro Operation
dominiert. 250 Fahrer sind damit fast gratis, 41 Fahrer in einer
Python-Schleife dagegen unbezahlbar.

Realistische Größenordnung: ~400.000 Ticks × einige Dutzend
Array-Operationen ≈ 30–120 s pro Ultra-Rennen.

### 8.1.1 Startintervall: 30 Minuten

**Entschieden:** 30 min Einzelstart, 250 Starter.

```
Fahrer gleichzeitig auf der Strecke ≈ Renndauer / Startintervall
```

| Klasse | Renndauer | gleichzeitig unterwegs | mittlerer Abstand |
|---|---|---|---|
| Kurz | 5–15 h | 10–30 | ~13 km |
| Mittel | 15–50 h | 30–100 | ~13 km |
| Ultra | 50–110 h | 100–220 | ~13 km |

Was das Intervall wirklich bewirkt, ist die **räumliche Entzerrung**: Im
Höhenprofil gibt es keine Fahrerknäuel, jeder Punkt ist einzeln
anklickbar.

#### Die eigentliche Folge: Tageszeit-Lotterie

Über 125 Stunden Startfenster verteilen sich die Startzeiten über alle
Tageszeiten. Da der zirkadiane Malus und das Wetter an der absoluten
Uhrzeit hängen, entsteht daraus ein systematischer, unverdienter Vorteil
in der Größenordnung mehrerer Stunden.

#### Entschieden: Fahrer-Eigenzeit

Zirkadianer Rhythmus und Wetterverlauf werden relativ zur eigenen
Startzeit gerechnet. Jeder Fahrer startet in seinem persönlichen „08:00"
und erlebt denselben Tagesgang. Die absolute Startzeit bestimmt nur noch
die Reihenfolge, nicht mehr die Bedingungen.

**Umsetzung:** Alle Zeitfunktionen bekommen `t_eigen = t_sim −
startzeit_offset[fahrer]`. Wichtig ist, dass keine Umweltfunktion die
absolute Simulationszeit sieht; das gehört in die Signatur der Module
erzwungen (`circadian(t_eigen)`, `weather(t_eigen, …)`, nie
`weather(t_sim)`).

| Schicht | Bezug | Beispiel | gemeinsam? |
|---|---|---|---|
| Ortsschicht | Position auf der Strecke | Temperatur nach Höhe, Windrichtung je Region | ja |
| Zeitschicht | Fahrer-Eigenzeit | Tagesgang, Tag/Nacht, Regenphasen | nein — je Fahrer, aber identischer Ablauf |

#### Skalierung nach Klasse

| Klasse | Intervall | Startfenster | gleichzeitig |
|---|---|---|---|
| Kurz | 5 min | 21 h | 60–180 |
| Mittel | 15 min | 62 h | 60–200 |
| Ultra | 30 min | 125 h | 100–220 |

### 8.2 Precompute, live präsentiert

Da niemand eingreifen kann, ist der Rennverlauf ab dem Startschuss
determiniert. Ob die Zahlen eine Sekunde oder eine Minute vor der Anzeige
berechnet wurden, ist für den Zuschauer nicht unterscheidbar.

1. Rennen wird beim Start komplett durchgerechnet
2. Ergebnis liegt als Event-Stream plus Telemetriearray vor
3. Ein Playback-Server streamt daraus per SSE mit einer Wanduhr: `sim_zeit = start + (jetzt − t0) · zeitraffer`
4. Der Client kennt immer nur die Vergangenheit bis zur aktuellen Wanduhrposition

Damit bekommt man kostenlos, was echtes Live nicht kann: Pause,
Zeitraffer 1×–1000×, Rücksprung, Sprung zum nächsten Ereignis.

**Wichtige Selbstbeschränkung:** Der Client darf nie Daten aus der
Zukunft erhalten, auch nicht im Puffer, sonst verrät ein Bug die
Endzeiten.

| Stufe | 2500 km entsprechen | Was gestreamt wird | Board |
|---|---|---|---|
| 1×–10× | 110 h – 11 h | Positionen alle 1–5 s, alle Ereignisse | volle Animation |
| 60× | ~2 h | Positionen alle 30 s, alle Ereignisse | Animation gedämpft |
| 300× | ~22 min | nur Split-Ereignisse und größere Zwischenfälle | Board springt |
| 1000× | ~7 min | nur Split-Ereignisse | schnelle Ergebnisfolge |

Die Umschaltung erfolgt serverseitig: Der Playback-Server aggregiert vor
dem Versand, statt alles zu senden und den Client filtern zu lassen.

### 8.3 Erzeugte Daten

Pro Fahrer und Tick: `t, dist, v, power, glykogen, hydration,
schlafdruck, w_prime, bike, state`.

**Nicht gespeichert** wird lat/lon/ele — die Position ist eindeutig durch
`dist` und die Routengeometrie bestimmt. Das spart drei von zehn Kanälen
und ist bei 250 Fahrern der Unterschied zwischen 90 MB und 300 MB.

Ereignis-Stream: `SPLIT_PASSED`, `BIKE_CHANGE`, `STOP_START`,
`STOP_END`, `SLEEP`, `MECHANICAL`, `BONK`, `DNF`, `FINISH`.

---

## 9. Live-Telemetrie

### 9.1 Logik

- Der Nutzer wählt einen fokussierten Fahrer und einen Split.
- Für den fokussierten Fahrer läuft die Zeit sichtbar weiter.
- Sobald er einen Split erreicht, wird seine Splitzeit in die Rangliste dieses Splits einsortiert; alle anderen Zeilen zeigen den Rückstand/Vorsprung (+/− mm:ss).
- Das Board zeigt max. **41 Zeilen** als Fenster über das gesamte Feld. Ist der Fokusfahrer auf Rang 1, steht er oben; sonst liegt er mittig (Rang r zeigt r−20 bis r+20).
- Randfälle: Ränge 1–20 zeigen immer 1–41; die letzten 20 immer 210–250. Zusätzlich eine fixierte Kopfzeile mit dem aktuell Führenden — sonst weiß man bei Rang 180 nicht mehr, worauf sich der Rückstand bezieht.
- Fahrer, die den Split noch nicht erreicht haben, erscheinen ausgegraut mit Prognosezeit — genau die Spannung, die „kommt er noch vorbei?" erzeugt.
- **Virtuelle Rangliste:** zusätzlich eine Ansicht, die alle Fahrer auf die gleiche Distanz projiziert, also die echte „wer liegt vorn"-Sicht bei versetzten Startzeiten.

### 9.2 Darstellungselemente

**Zeile:** Rang · Startnummer · Flagge · Name · Team · Zeit/Rückstand ·
Δ zum Vorsplit (farbig) · Statusicon (Schlaf, Panne, TT/Straßenrad)

**Kopfbereich:** laufende Uhr des fokussierten Fahrers, aktueller Split,
Restdistanz, Momentangeschwindigkeit und -steigung

---

## 10. Benutzeroberfläche

**Keine Karte.** Die räumliche Darstellung erfolgt vollständig über das
Höhenprofil. Das ist keine Notlösung, sondern für ein Einzelzeitfahren
die bessere Anzeige: Auf einer Karte verteilen sich 250 Fahrer über eine
gewundene Linie, deren Verlauf nichts über den Rennstand aussagt. Im
Profil ist die x-Achse die Distanz — Reihenfolge, Abstände und das
kommende Gelände sind auf einen Blick lesbar.

```
┌───────────────┬────────────────────────────────────────┐
│  SIDEBAR      │  HÖHENPROFIL                           │
│               │  x = Distanz, y = Höhe                 │
│  Startliste   │  Steigungsfärbung, Anstiege schraffiert│
│  Nr · Name    │  Splits und Servicepunkte als Marken   │
│  Team · NAT   │  250 Fahrerpunkte, Fokus hervorgehoben │
│  Startzeit    ├────────────────────────────────────────┤
│  aktuelle Zeit│  LIVE-TELEMETRIE                       │
│               │  Splitwahl · Rangliste (Fenster 41)    │
│  Splitauswahl │  Uhr · Δ-Anzeige · Statusicons         │
└───────────────┴────────────────────────────────────────┘
```

### 10.1 Das Höhenprofil als Hauptanzeige

- Grundlinie: geglättetes Profil, eingefärbt nach Steigung (Grün flach → Rot über 10 %, Blau Abfahrt)
- Anstiege als schraffierte Bereiche mit Kategorie-Etikett
- Splits als senkrechte Marken, Servicepunkte mit eigenem Symbol
- Fahrer als Punkte: Fokusfahrer groß und in Teamfarbe, Nachbarn gedämpft, der Rest als kleine graue Punkte
- **Zwei Zoomstufen:** Gesamtstrecke als Übersichtsleiste, darunter ein Ausschnitt von ±20 km um den Fokusfahrer
- Zustände als farbige Balken unter der Profillinie
- Hover zeigt Name, Rang, Momentangeschwindigkeit und Steigung

**Technisch:** ein einzelnes Canvas-Element. Das Profil wird einmal als
Pfad vorgerendert, nur die Fahrerpunkte werden pro Frame neu gezeichnet.
250 Punkte auf Canvas sind unkritisch — als 250 DOM-Knoten in SVG
dagegen nicht.

### 10.2 Steuerung

Play/Pause, Zeitraffer (1×/10×/60×/300×), Sprung zum nächsten
Split-Ereignis, Sprung zum nächsten Ereignis des Fokusfahrers.

### 10.3 Editoren im Spiel

Da der Nutzer nicht fährt, ist das Bauen die Interaktion.

- **Strecken-Import statt Strecken-Editor:** GPX per Drag & Drop; Vorschau mit Höhenprofil, Distanz, Höhenmetern, erkannten Anstiegen und abgeleiteter Distanzklasse. Splits und Servicepunkte per Drag verschiebbar.
- **Fahrer-Editor:** Generator mit Archetyp-Auswahl und Anzahl, danach Tabellen- und Detailansicht, Radarchart, Potenzial-Budget-Anzeige.
- **Team-Editor:** Name, Land, Farben, Servicedisziplin, Fahrerkader.
- **Kalender-Editor:** Saison, Rennen, Termine, Startfeld, Punkteschema, Rennkoeffizienten.
- **Weitere Screens:** Rennergebnis, Gesamtrangliste, Fahrerdetail mit Verlaufskurven, Rennarchiv.

---

## 11. Wertung

- Rennpunkte nach Platzierung (Vorschlag: 100, 80, 65, 55, 48, 42, 37, 33, 30, 28, dann −2 je Rang bis 0)
- Rennkoeffizient nach Streckenlänge/Höhenmetern
- Optional: Bergwertung und Zwischensprintwertung
- DNF: 0 Punkte, aber Ermüdungs- und Formfolgen bleiben
- Gesamtrangliste über die Saison, Tiebreak: Anzahl Siege, dann bessere Einzelplatzierung

---

## 12. Datenmodell (Entwurf)

```
Team(id, name, land, farbe, servicedisziplin)
Rider(id, team_id, name, nat, geb, groesse_cm, gewicht_kg, ftp_w, attribute…, saisonform_kurve)
Route(id, name, start_latlon, ziel_latlon, geometrie(3D), distanz_m, hoehenmeter, erstellt_am)
RouteSegment(id, route_id, idx, dist_start, laenge, delta_ele, grade, oberflaeche, kurvigkeit, peilung)
Climb(id, route_id, dist_start, dist_end, laenge, hm, grade_avg, grade_max, kategorie)
Split(id, route_id, idx, dist_m, name, typ)
Race(id, route_id, datum, seed, wetterprofil, startintervall_s, status)
RaceEntry(id, race_id, rider_id, startnummer, startzeit_offset, tagesform, endzeit, rang, punkte, status)
Telemetry(entry_id, t_s, dist_m, lat, lon, ele, v, power, glykogen, hydration, schlafdruck, bike, state)
SplitTime(entry_id, split_id, t_s, rang_at_split)
RaceEvent(id, entry_id, t_s, typ, payload_json)
RiderCondition(entry_id, typ, start_t, dauer, wirkung_json, abklingen)
Season(id, jahr) / SeasonStanding(season_id, rider_id, punkte, siege)
```

**Telemetry** ist die einzige Struktur, die groß wird. Naiv relational
gespeichert wären es bei 15 s Abtastung 250 × 26.400 = 6,6 Mio. Zeilen
pro Rennen, bei 15 Saisonrennen ~100 Mio. Das gehört nicht in eine
Tabelle.

**Empfehlung:**

- **Relational** (SQLite → Postgres): Stammdaten, Rennen, SplitTime, RaceEvent, RiderCondition
- **Als Datei pro Rennen** (`races/<id>/telemetry.npz`): ein Array der Form `(n_fahrer, n_samples, n_kanäle)`, mmap-fähig
- **Quantisierung statt float64:** dist als int32 (Meter), v als int16 (cm/s), glykogen/schlafdruck als uint8, bike/state als uint8 → Faktor 6 gegenüber float64, auf ~45 MB pro Ultra-Rennen
- **Sampling distanzabhängig:** 5 s (Kurz), 15 s (Mittel), 30 s (Ultra)

---

## 13. Tech-Stack

| Schicht | Wahl | Begründung |
|---|---|---|
| Backend | FastAPI | async passt exakt zu Event-Streaming |
| ORM/DB | SQLAlchemy 2.0 + SQLite (Dev) / PostgreSQL | Migration über Alembic |
| Simulation | NumPy (vektorisiert über alle Fahrer), optional Numba | 6 Mio. Ticks brauchen Arrays, keine Objektschleifen |
| Geo | GPX-Import mit reinem NumPy; kein Routing-Dienst im Betrieb | Strecken sind Daten, keine Laufzeitabhängigkeit |
| Höhenglättung | eigene Savitzky-Golay-Implementierung | Spart SciPy komplett — im PyInstaller-Bundle rund 60 MB |
| Templates | Jinja2 | Seitenrahmen |
| Interaktivität | Alpine.js für das Board, HTMX für Formulare | HTMX allein ist für ein mehrmals pro Sekunde umsortierendes Board das falsche Werkzeug |
| Live-Transport | SSE | Einweg-Stream vom Server zum Client, deutlich einfacher als WebSockets |
| Profilanzeige | Canvas 2D, selbst gezeichnet | 250 bewegte Punkte über einem statischen Pfad |
| Verlaufskurven | uPlot | Leistung, Glykogen, Schlafdruck im Fahrerdetail |
| Tests | pytest, plus Golden-Master-Tests auf feste Seeds | Balancing-Änderungen sichtbar machen |

**Architekturprinzip:** Die Simulation ist eine reine Bibliothek ohne
Web-Abhängigkeit (`ultrasim/core/`), die aus einer Renn-Konfiguration
einen Event-Strom erzeugt. Web-App und CLI sind nur zwei Konsumenten. Das
erlaubt Batch-Läufe für Balancing ohne Browser.

```
ultrasim/
  core/         physics.py  rider.py  fatigue.py  nutrition.py  events.py  engine.py
  geo/          gpx_import.py  smoothing.py  segmentation.py  splits.py
  data/         models.py  repository.py
  web/          main.py  routers/  templates/  static/
  cli/          simulate.py  balance.py
```

---

## 14. Roadmap

| M | Inhalt | Ergebnis |
|---|---|---|
| M1 | GPX-Import: Parsen, Resampling, Glättung, Segmentierung, Anstiege, Splits, JSON-Ausgabe | Aus einer GPX-Datei wird eine saubere Streckendatei |
| M2 | Physikmodell + ein Fahrer, konstante Leistung, CLI-Zeitberechnung | Plausible Fahrzeit für eine echte Strecke |
| M3 | Fahrer-DB, Generator mit Archetypen, Attribute, Form, Ermüdung, Feld von 41, Splitzeiten | Vollständiges Rennergebnis als Tabelle |
| M4 | Web-UI: Höhenprofil-Canvas, Sidebar, Telemetrie-Board, Playback-Server mit Zeitraffer | Das eigentliche Spielerlebnis steht |
| M5 | Verpflegung, Glykogen, Schlaf, Stopps, Servicepunkte; Strategiemodul Stufe 1 | Aus Zeitfahren wird Ultracycling |
| M5b | Editoren: Strecke, Fahrer, Team | Der Nutzer kann eigene Welten bauen |
| M6 | Wetter, Wind, Tag/Nacht, Pannen, Radwechsel-Ökonomie | Tiefe und Variabilität |
| M7 | Saison, Kalender-Editor, Punkte, Gesamtrangliste, Fahrerentwicklung | Langzeitmotivation |
| M7b | Strategiemodul Stufe 2 (Regelkreis, Entscheidungs-Log), Highlight-Automatik | Fahrer bekommen sichtbare Persönlichkeit |
| M8 | Balancing-Tooling, Golden-Master-Tests, Kalibrierung an realen Ultra-Ergebnissen | Glaubwürdigkeit |

---

## 15. Getroffene Entscheidungen

| # | Frage | Entscheidung | Wichtigste Folge |
|---|---|---|---|
| 1 | Streckenlänge | 150–2500 km, drei Distanzklassen | Split-Dichte, Sampling und Schlafmodell müssen skalieren |
| 2 | Rennmodus | Supported | Versorgung ist teamgeplant; Teams bekommen ein eigenes Attribut |
| 3 | Spielerrolle | Reine Simulation, kein Spieler | Das Strategiemodul wird zum Kern; die Editoren zur Interaktion |
| 4 | Live oder Precompute | Precompute, live präsentiert | Playback-Server mit Wanduhr; Zeitraffer, Pause und Sprünge |
| 5 | Fahrer | Fiktiv | Generator mit Archetypen und Potenzial-Budget |
| 6 | Fahrererstellung | Generator plus In-Game-Editor | Editoren für Strecke, Fahrer, Team und Kalender |

### Zweite Entscheidungsrunde

| # | Frage | Entscheidung | Wichtigste Folge |
|---|---|---|---|
| 7 | Zufall über lange Distanzen | Lange Formabschnitte + Tagesform + diskrete Ereignisse | OU-Korrelationslänge skaliert mit Streckenlänge |
| 8 | Highlight-Automatik | Nein, stattdessen Zeitraffer bis 1000× | Playback-Server muss die Update-Granularität aggregieren |
| 9 | Servicedisziplin | Je Team gesetzt | Teams bekommen eine eigene, spürbare Rolle |
| 10 | DNF-Quote | 5–10 %, klassenabhängig gestaffelt | Ereignisse wirken überwiegend über Zeit und Zustände |
| 11 | Feldgröße | 250 Fahrer je Rennen | Vektorisierung wird zur Pflicht; Board wird zum Fenster |
| 12 | Startintervall | 30 min Einzelstart (~13 km zwischen Startern) | Startfenster 125 h; alle Umweltfunktionen in Fahrer-Eigenzeit |
| 13 | Zeitmodus | Fahrer-Eigenzeit | Wettermodell wird zweischichtig; Startzeit wird einzelner Rennparameter |
| 14 | Auslieferung | GitHub Actions, EXE je Tag `v*` | Streckenbau läuft vorab; kein Java, kein Netz in der EXE |

### Daraus neu entstandene offene Punkte

- **Wie stark darf die Ortsschicht des Wetters wirken?** Wenn ein Passabschnitt immer kalt und windig ist, trifft das alle gleich — aber es verschiebt das Kräfteverhältnis der Fahrertypen auf dieser Strecke dauerhaft.
- **Wie viele Teams?** Bei 250 Fahrern sind 25–35 Teams à 7–10 Fahrer plausibel. Bei zu wenigen Teams wird Servicedisziplin zum dominanten Faktor.
- **Zeitlimit je Rennen?** Vorschlag: 1,4 × Siegerzeit oder eine feste Vorgabe im Kalender-Editor.
- **Wie sichtbar sind Zustände in der UI?** Vorschlag: Statusicons in der Board-Zeile plus Zustandsbalken über dem Streckenprofil im Fahrerdetail.

---

## 16. Auslieferung

Jeder Tag `v*` löst über GitHub Actions einen Windows-Build aus, der eine
`UltracyclingSimulator.exe` als Release-Asset veröffentlicht. Details:
siehe [`BUILD_UND_RELEASE.md`](../BUILD_UND_RELEASE.md).

**Zentrale Entscheidung für die Auslieferbarkeit:** Der Streckenbau läuft
nicht in der EXE, sondern vorab über den GPX-Importer auf dem
Entwicklungsrechner. Strecken werden als gzip-JSON mit fertiger
Segmentierung, Anstiegen, Splits und Servicepunkten ins Repo eingecheckt
und mitgebündelt. Die EXE braucht damit weder Java noch Kartendaten noch
Netz.

**v0.1.0-Umfang:** eine Strecke (~300 km), 40 generierte Fahrer,
Physik/Form/Ermüdung, Precompute mit Playback bis 60×, Board,
Höhenprofil, Ergebnisliste. Keine Ereignisse, kein Schlaf, keine
Verpflegung. Zweck ist ausschließlich: einmal zuschauen können.

---

## 17. Was noch fehlte — Kurzliste

Verpflegung und Glykogenhaushalt · Hydration · Schlafstrategie und
Schlafdruck · zirkadianer Rhythmus · Wetter, Temperatur und Wind ·
Tag-Nacht-Zyklus mit Lichtthematik · Stopps und Servicezeiten · Pannen
und Zwischenfälle · Navigationsfehler · Abfahrtsphysik und Kurvenlimit ·
W′/anaerobe Kapazität · Langzeitermüdung über Stunden · Höhenglättung der
DEM-Daten · Wirtschaftlichkeitsprüfung beim Radwechsel · Gepäckgewicht
und dessen CdA-Wirkung · Startintervalle und Startreihenfolge-Regeln ·
virtuelle Rangliste bei versetzten Starts · Prognosezeiten für noch nicht
angekommene Fahrer · DNF-Regeln · Determinismus/Seeds · Saisonkalender
und Fahrerentwicklung · Balancing-Werkzeuge.
