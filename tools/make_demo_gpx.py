"""Erzeugt eine synthetische GPX-Datei als Demo-Eingabe für den Importer.

Wichtig: Das ist *keine* reale Strecke. Es ist Testmaterial, damit die
Importkette (Abschnitt 3.6) und das Spiel ohne Netz und ohne fremde
Kartendaten lauffähig sind. Jede echte GPX-Datei aus komoot, BRouter,
Strava oder einer GPS-Aufzeichnung funktioniert genauso:

    python -m ultrasim.geo.gpx_import meine_strecke.gpx

Die Datei bekommt bewusst realistisches DEM-Rauschen (sigma = 1,2 m) und
eine typische Punktdichte von ~25 m, damit die Glättung etwas zu tun hat.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

#: (Länge in km, mittlere Steigung in Prozent) – das Gerüst des Profils.
VORALPEN: list[tuple[float, float]] = [
    (28.0, 0.3),  # flaches Voralpenland
    (14.0, 1.6),  # welliger Anstieg ins Tal hinein
    (10.0, -1.1),
    (16.0, 0.8),
    (12.0, -0.6),
    (9.0, 6.6),  # Anstieg 1 – rund 590 hm
    (7.0, -7.4),  # Abfahrt
    (18.0, 0.5),
    (11.0, 1.9),
    (8.0, -1.4),
    (13.5, 7.3),  # Anstieg 2 – rund 985 hm, das Rückgrat der Strecke
    (10.0, -8.2),
    (15.0, -0.9),
    (21.0, 0.6),
    (9.0, 2.2),
    (5.0, 5.1),  # Anstieg 3 – kurze Rampe
    (6.0, -5.0),
    (24.0, -0.4),
    (19.0, 0.9),
    (14.0, -1.2),
    (31.0, 0.2),  # flacher Schluss
]

#: Hochgebirge, rund 600 km mit vier großen Pässen – die Strecke, auf der
#: sich Kletterer und Zeitfahrer wirklich unterscheiden und auf der die
#: Radwahl je Abschnitt nicht mehr eindeutig ist.
#: Die Steilrampen in Pass 2 und 3 sind nicht Dekoration, sondern
#: nachgerüstet. Vorher lag die maximale Steigung des gesamten Bündels
#: bei 10,8 % und das 99,9-Perzentil unter 10 % — es gab schlicht kein
#: Gelände, auf dem ein Fahrer anaerob fährt. Entsprechend stand W′ in
#: jedem gemessenen Rennen bei 100 %, und ``spritzigkeit`` wirkte nicht.
#:
#: Echte Alpenpässe haben solche Stücke: Mortirolo und Zoncolan gehen
#: über 18 %, und auch ein gewöhnlicher Pass hat Kehren mit 12 bis 14 %.
#: Die Rampen hier sind mit 13 und 15 % am unteren Rand davon und
#: bewusst kurz — ein ganzer Pass in dieser Neigung wäre keine Strecke,
#: sondern eine Behauptung.
HOCHGEBIRGE: list[tuple[float, float]] = [
    (34.0, 0.4), (22.0, 1.8), (16.0, -1.0),
    (18.5, 7.1), (14.0, -8.0),          # Pass 1: ~1310 hm
    (26.0, 0.7), (14.0, 2.4), (12.0, -1.6),
    (17.0, 7.0), (2.2, 13.0), (1.8, 8.5), (17.0, -8.6),   # Pass 2 mit Steilstück
    (31.0, 0.3), (18.0, 1.5), (13.0, -1.1),
    (12.0, 7.4), (1.6, 15.0), (2.4, 9.0), (13.0, -9.4),   # Pass 3, die steilste Rampe
    (28.0, 0.6), (22.0, -0.5),
    (24.0, 6.2), (19.0, -7.2),          # Pass 4: ~1490 hm, lang und gleichmäßig
    (37.0, 0.4), (26.0, 1.1), (21.0, -1.3), (44.0, 0.2),
]

#: Langstrecke, rund 1300 km – welliges Flachland mit langen Zwischenstücken.
#: Hier entscheidet Ausdauer, nicht Kletterstärke.
LANGSTRECKE: list[tuple[float, float]] = [
    (62.0, 0.3), (38.0, 1.2), (30.0, -0.9), (55.0, 0.4), (26.0, 1.9), (24.0, -1.5),
    (12.0, 5.4), (10.0, -6.0),
    (74.0, 0.2), (41.0, 1.0), (33.0, -0.8), (58.0, 0.5), (29.0, 2.1), (25.0, -1.7),
    (15.0, 5.9), (13.0, -6.4),
    (81.0, 0.3), (44.0, 0.9), (36.0, -0.7), (63.0, 0.4), (31.0, 1.6), (27.0, -1.4),
    (11.0, 6.1), (9.0, -6.8),
    (88.0, 0.2), (47.0, 0.8), (39.0, -0.6), (71.0, 0.3), (34.0, 1.3), (28.0, -1.1),
    (76.0, 0.2),
]

#: Flachetappe, rund 470 km an der Küste – die einzige Strecke im
#: Bündel, auf der Kletterstärke schlicht nichts nützt.
#:
#: Sie ist entstanden, weil eine Messung eine Lücke aufgedeckt hat. Der
#: Zeitfahr-Spezialist gewann auf keiner der drei anderen Strecken, und
#: der erste Verdacht war, dass ihm schlicht das Heimterrain fehlt: Die
#: „flachste" hatte 5,0 m/km, das ist welliges Land und keine
#: Zeitfahrstrecke. Der Verdacht hat sich nicht bestätigt — die Ursache
#: lag woanders —, aber die Lücke war echt und ist geblieben.
#:
#: Unter 1,5 m/km. Zum Vergleich: Die Nordroute liegt bei 5,0, die
#: Voralpen-Runde bei 8,9 und der Hochgebirgs-Marathon bei 13,4. Die
#: einzige nennenswerte Erhebung ist eine Deichauffahrt in der Mitte,
#: damit die Anstiegserkennung und die Radwahl überhaupt etwas zu
#: entscheiden bekommen.
FLACHETAPPE: list[tuple[float, float]] = [
    (48.0, 0.2), (35.0, -0.3), (52.0, 0.15), (28.0, 0.6), (31.0, -0.5),
    (44.0, 0.25), (26.0, -0.4),
    (6.0, 2.4), (5.0, -2.6),          # die einzige Welle: rund 145 hm
    (57.0, 0.2), (33.0, -0.25), (41.0, 0.3), (24.0, -0.45), (36.0, 0.1),
]

# ----------------------------------------------------------------------
# Die Weltserie: zehn Strecken von 400 bis 2500 km
# ----------------------------------------------------------------------
# Die vier Strecken oben sind von Hand geschrieben, Zeile für Zeile. Für
# zehn weitere geht das nicht mehr: Eine 2500-km-Strecke bräuchte gut
# hundert Zeilen Zahlen, und niemand — ich eingeschlossen — könnte einer
# solchen Tabelle ansehen, ob sie das Gelände beschreibt, das sie
# beschreiben soll.
#
# Deshalb hier ein zweiter Weg: **Motive statt Tabellen.** Ein Motiv ist
# ein Geländestück von wenigen Kilometern — ein flaches Zwischenstück,
# eine Welle, ein Pass. Jedes gibt es in mehreren Ausprägungen, die im
# Wechsel eingesetzt werden; ohne das entstünde ein exakt periodisches
# Profil, auf dem jeder Anstieg der gleiche ist.
#
# Der Charakter einer Strecke steht damit in einer Zeile: „zwölfmal
# flach, dazwischen je zwei Wellen" liest man, „(28.0, 0.3), (16.0,
# -0.4), …" nicht.

Block = list[tuple[float, float]]

#: Flaches Zwischenstück, rund 65 km. Nicht wirklich flach — echtes
#: Flachland hat Senken und Kuppen, und ein Profil mit exakt 0 %
#: Steigung fährt sich in der Simulation anders als eines, das um die
#: Null pendelt.
FLAT: list[Block] = [
    [(28.0, 0.3), (16.0, -0.4), (22.0, 0.2)],
    [(34.0, -0.2), (19.0, 0.5), (18.0, -0.3)],
    [(25.0, 0.4), (21.0, -0.5), (30.0, 0.1)],
]

#: Küstenflach, rund 55 km. Noch eine Stufe glatter als ``FLAT`` — hier
#: nützt Kletterstärke wirklich nichts.
COAST: list[Block] = [
    [(31.0, 0.12), (24.0, -0.15)],
    [(27.0, -0.1), (29.0, 0.14)],
    [(22.0, 0.18), (33.0, -0.12)],
]

#: Welliges Hügelland, rund 30 km mit ~250 hm. Der Rhythmus, der über
#: Stunden zermürbt, ohne je ein Anstieg zu sein.
HILLS: list[Block] = [
    [(11.0, 1.6), (9.0, -1.9), (12.0, 0.7), (8.0, -0.9)],
    [(9.0, 2.1), (11.0, -1.7), (10.0, 0.5), (9.0, -0.6)],
    [(13.0, 1.4), (8.0, -2.2), (11.0, 0.8), (8.0, -0.7)],
]

#: Kurze steile Rampe mit Abfahrt, rund 9 km mit ~300 hm. Das
#: Ardennen-Motiv: zu kurz zum Einteilen, zu steil zum Durchfahren.
KICKER: list[Block] = [
    [(2.6, 8.4), (1.9, -9.6), (4.2, 0.4)],
    [(1.8, 11.2), (2.4, -8.1), (3.6, -0.3)],
    [(3.2, 7.1), (2.1, -10.4), (4.8, 0.5)],
    [(1.4, 13.5), (2.8, -6.9), (5.1, 0.2)],
]

#: Mittelgebirgsanstieg, rund 26 km mit ~700 hm.
CLIMB_MID: list[Block] = [
    [(9.5, 6.4), (8.0, -7.4), (8.0, 0.4)],
    [(11.0, 5.8), (9.0, -6.9), (7.0, -0.3)],
    [(8.0, 7.2), (10.0, -5.6), (9.0, 0.5)],
]

#: Hochgebirgspass, rund 38 km mit ~1300 hm — mit Steilstück in den
#: Kehren. Ohne das Stück über 12 % gibt es kein Gelände, auf dem ein
#: Fahrer anaerob fährt, und W′ steht das ganze Rennen bei 100 %.
PASS: list[Block] = [
    [(17.0, 7.1), (2.2, 13.0), (1.8, 8.5), (17.0, -8.4)],
    [(12.0, 7.4), (1.6, 15.0), (2.4, 9.0), (16.0, -9.1), (4.0, 0.3)],
    [(19.5, 6.6), (2.0, 12.2), (2.0, 8.8), (20.0, -7.6)],
    [(15.0, 7.8), (1.5, 14.2), (2.5, 8.2), (18.0, -8.0), (3.0, -0.4)],
]

#: Langgezogener Anstieg ohne Steilstück, rund 45 km mit ~1400 hm. Der
#: Pass, den man sitzend fährt — die Gegenprobe zum Kehrenpass.
PASS_LONG: list[Block] = [
    [(24.0, 6.2), (19.0, -7.2), (4.0, 0.2)],
    [(28.0, 5.4), (21.0, -6.6), (2.0, -0.3)],
    [(22.0, 6.8), (23.0, -6.1), (3.0, 0.4)],
]


def weave(motif: list[Block], times: int, offset: int = 0) -> Block:
    """Ein Motiv mehrfach einsetzen, die Ausprägungen im Wechsel."""
    out: Block = []
    for i in range(times):
        out.extend(motif[(offset + i) % len(motif)])
    return out


#: Die zehn Strecken der Weltserie. Ihre Länge steht **nicht** vorher
#: fest: Sie ergibt sich daraus, wie viele Motive aneinandergesetzt
#: werden. Ein Profil hinterher auf eine runde Zahl zu strecken wäre
#: bequem, würde aber genau das Gelände verbiegen, das die Motive
#: beschreiben — aus einer 2 km langen 15-%-Rampe würde auf der
#: 2500-km-Strecke eine 12 km lange, und die gibt es nirgends.

#: 396 km, 1,2 hm/km. Reines Zeitfahren am Meer: keine Steigung, die der
#: Rede wert wäre, dafür Wind aus jeder Richtung. Die eine kurze Rampe
#: ist Absicht — ohne sie hätten Anstiegserkennung und Radwahl auf der
#: ganzen Strecke nichts zu entscheiden.
ATLANTIK = weave(COAST, 4) + weave(KICKER, 1, 3) + weave(COAST, 3, 1)

#: 458 km, 12,9 hm/km. Zweiundzwanzig kurze Rampen, keine davon lang
#: genug für einen Rhythmus. Das Gegenstück zum Atlantik: Hier zählt
#: nicht, wie lange jemand an der Schwelle fährt, sondern wie oft er
#: darüber hinausgeht und wieder herunterkommt.
ARDENNEN = (
    weave(FLAT, 1) + weave(KICKER, 11) + weave(HILLS, 2) + weave(KICKER, 11, 2)
    + weave(HILLS, 1, 1) + weave(FLAT, 1, 2)
)

#: 573 km, 14,9 hm/km, Start auf 1050 m. Vier Kehrenpässe, Scheitel über
#: 2300 m — die einzige Strecke im Kalender, auf der die Höhe wirklich
#: Leistung kostet.
DOLOMITEN = (
    weave(FLAT, 2) + weave(PASS, 4) + weave(HILLS, 2) + weave(CLIMB_MID, 2)
    + weave(FLAT, 2, 1)
)

#: 641 km, 5,3 hm/km. Welliges Mittelgebirge, zur Hälfte Schotter — die
#: Strecke, auf der die Reifenwahl kein Detail ist, sondern *die*
#: Entscheidung. Steigung gibt es wenig, Untergrund umso mehr.
KARPATEN = (
    weave(HILLS, 3) + weave(CLIMB_MID, 1) + weave(HILLS, 3, 1)
    + weave(CLIMB_MID, 1, 2) + weave(FLAT, 5)
)

#: 864 km, 8,5 hm/km. Hügelland mit Pflaster und weißen Schotterstraßen:
#: ständig wellig, selten steil, und der Untergrund wechselt dauernd.
TOSKANA = (
    weave(HILLS, 6) + weave(KICKER, 6) + weave(HILLS, 5, 1)
    + weave(CLIMB_MID, 3) + weave(HILLS, 4, 2) + weave(FLAT, 2)
)

#: 980 km, 2,1 hm/km. Flach und lang genug für zwei volle Nächte auf dem
#: Rad. Hier entscheidet nicht die Steigung, sondern wer schläft.
OSTSEE = (
    weave(COAST, 6) + weave(HILLS, 3) + weave(FLAT, 4, 1) + weave(HILLS, 2, 1)
    + weave(COAST, 3, 2)
)

#: 1212 km, 12,9 hm/km. Bergultra: neun große Anstiege über zwölfhundert
#: Kilometer, mit Nächten dazwischen. Klettern *und* durchhalten — die
#: Strecke, die beides zugleich verlangt.
PYRENAEEN = (
    weave(FLAT, 4) + weave(PASS, 3) + weave(HILLS, 3) + weave(PASS_LONG, 2)
    + weave(FLAT, 3, 1) + weave(PASS, 3, 1) + weave(CLIMB_MID, 2)
    + weave(FLAT, 3, 2)
)

#: 1463 km, 2,1 hm/km, Start auf 1080 m. Hochebene: kaum Steigung, aber
#: durchgehend über tausend Meter und auf rauem Belag. Dieselbe
#: Steigungsdichte wie die Ostsee-Nachtfahrt, anderthalbmal so lang und
#: mit dem Untergrund als Dauerabgabe — die Strecke für Monotonie.
STEPPE = (
    weave(FLAT, 7) + weave(HILLS, 2) + weave(FLAT, 7, 1) + weave(HILLS, 1, 2)
    + weave(FLAT, 5, 2)
)

#: 1924 km, 10,0 hm/km. Alpenüberquerung: lange flache Anfahrt, dann
#: zehn Pässe am Stück, dann wieder flach. Die Strecke, die beide
#: Hälften eines Fahrers nacheinander abfragt.
ALPEN = (
    weave(FLAT, 8) + weave(HILLS, 3) + weave(PASS, 4) + weave(PASS_LONG, 2)
    + weave(PASS, 4, 2) + weave(HILLS, 3, 1) + weave(FLAT, 10, 1)
)

#: 2469 km, 7,4 hm/km. Die längste Strecke des Kalenders und die
#: einzige, die alles enthält: Flachland, Hügel, Kehrenpässe, lange
#: Anstiege. Über hundert Stunden im Sattel, drei bis vier Nächte.
TRANSKONTINENTAL = (
    weave(FLAT, 8) + weave(HILLS, 4) + weave(PASS, 3) + weave(FLAT, 7, 1)
    + weave(CLIMB_MID, 3) + weave(HILLS, 3, 2) + weave(PASS_LONG, 2)
    + weave(PASS, 2, 3) + weave(FLAT, 9, 2) + weave(HILLS, 3, 1)
)


PRESETS: dict[str, tuple[str, list[tuple[float, float]], tuple[float, float, float]]] = {
    # Name -> (Anzeigename, Profil, (lat, lon, Starthöhe))
    "voralpen": ("Voralpen-Runde (Demo)", VORALPEN, (47.8214, 11.4526, 584.0)),
    "hochgebirge": ("Hochgebirgs-Marathon (Demo)", HOCHGEBIRGE, (46.5197, 9.8383, 812.0)),
    "langstrecke": ("Nordroute Langstrecke (Demo)", LANGSTRECKE, (52.3759, 9.7320, 58.0)),
    "flachetappe": ("Flachetappe Nordsee (Demo)", FLACHETAPPE, (53.5511, 8.5865, 6.0)),
    # --- die Weltserie ------------------------------------------------
    "atlantik": ("Atlantik-Zeitfahren", ATLANTIK, (47.2184, -2.2100, 8.0)),
    "ardennen": ("Ardennen-Wellenritt", ARDENNEN, (50.3500, 5.8500, 224.0)),
    "dolomiten": ("Dolomiten-Vierpässe", DOLOMITEN, (46.5405, 11.8600, 1050.0)),
    "karpaten": ("Karpaten-Schotterrunde", KARPATEN, (45.6000, 25.4000, 620.0)),
    "toskana": ("Toskana-Hügelmarathon", TOSKANA, (43.3200, 11.3300, 290.0)),
    "ostsee": ("Ostsee-Nachtfahrt", OSTSEE, (54.4000, 12.5000, 4.0)),
    "pyrenaeen": ("Pyrenäen-Traverse", PYRENAEEN, (42.8000, 0.6000, 480.0)),
    "steppe": ("Steppenroute Anatolien", STEPPE, (39.0000, 33.5000, 1080.0)),
    "alpen": ("Alpenüberquerung", ALPEN, (47.2600, 11.3900, 570.0)),
    "transkontinental": ("Transkontinental", TRANSKONTINENTAL, (48.2000, 16.3700, 170.0)),
}

#: Kehren an steilen Stellen. Eine Peilungsschwingung von ±0,26 rad
#: (20°) alle 200 m ergibt rund 250 Grad Richtungsänderung je Kilometer —
#: die Größenordnung einer Passstraße mit Serpentinen. Zum Vergleich:
#: Die glatte Grundwelle des Kurses liefert unter 20 Grad je Kilometer.
SWITCHBACK_RAD = 0.34
SWITCHBACK_WAVELENGTH_M = 200.0

#: Überlagerte Wellen: (Amplitude in m, Wellenlänge in km, Phase)
ROLLING = [(4.5, 7.3, 0.0), (2.6, 3.9, 1.7), (1.4, 2.1, 0.6)]

EARTH_R = 6371008.8


def build_track(
    profile: list[tuple[float, float]],
    start_lat: float,
    start_lon: float,
    start_ele: float,
    point_spacing_m: float,
    dem_noise_m: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)

    total_km = sum(length for length, _ in profile)
    total_m = total_km * 1000.0
    # Runden statt abschneiden. Die Profillängen summieren sich je nach
    # Python-Version auf 60,1 oder auf 60,099999999999994 – seit 3.12
    # summiert ``sum()`` für Fließkommazahlen kompensiert und trifft den
    # Wert genauer. Mit ``int()`` kippt genau dort die Punktzahl um eins,
    # die Strecke wird 30 m länger, und der Golden Master ist auf der
    # einen Python-Version rot und auf der anderen grün. Das Runden nimmt
    # der Ganzzahlgrenze ihre Schärfe.
    n = round(total_m / point_spacing_m) + 1
    dist = np.arange(n, dtype=np.float64) * point_spacing_m

    # --- Höhe: Gerüst integrieren, Wellen und DEM-Rauschen darüberlegen
    marks = np.cumsum([0.0] + [length * 1000.0 for length, _ in profile])
    grades = np.array([g / 100.0 for _, g in profile])
    ele = np.full(n, float(start_ele))
    base = float(start_ele)
    for i, grade in enumerate(grades):
        lo, hi = marks[i], marks[i + 1]
        mask = (dist >= lo) & (dist <= hi)
        ele[mask] = base + (dist[mask] - lo) * grade
        base += (hi - lo) * grade
    ele[dist > marks[-1]] = base

    # --- Netto-Höhendrift herausnehmen ------------------------------
    # Die Steigungen der Profiltabelle summieren sich nicht auf null,
    # und ohne Korrektur steigt jede Strecke durchgehend an: Die
    # „Voralpen-Runde" endete 800 m über ihrem Start, die 1230-km-Route
    # durchs Flachland auf 3283 m. Eine Runde kommt dort an, wo sie
    # losgefahren ist.
    #
    # Abgezogen wird eine Gerade. Die Anstiege bleiben dadurch erhalten
    # — bei 800 m auf 300 km sind es 0,27 Prozentpunkte, die jede
    # Steigung gleichmäßig verliert.
    drift = ele[-1] - ele[0]
    if abs(drift) > 1.0:
        ele = ele - drift * (dist / max(dist[-1], 1.0))

    for amp, wl_km, phase in ROLLING:
        ele += amp * np.sin(2.0 * math.pi * dist / (wl_km * 1000.0) + phase)

    # Übergänge zwischen den Gerüstabschnitten weichzeichnen, damit keine
    # unphysikalischen Knicke im Profil stehen.
    kernel = np.ones(41) / 41.0
    ele = np.convolve(np.pad(ele, 20, mode="edge"), kernel, mode="valid")

    ele += rng.normal(0.0, dem_noise_m, n)

    # --- Verlauf: glatt mäandernder Kurs, damit Peilung und Kurvigkeit
    #     etwas Sinnvolles zu rechnen haben.
    heading = (
        0.9 * np.sin(2.0 * math.pi * dist / 41_000.0)
        + 0.55 * np.sin(2.0 * math.pi * dist / 12_500.0 + 2.1)
        + 0.25 * np.sin(2.0 * math.pi * dist / 3_100.0 + 0.4)
    )

    # --- Kehren, wo es steil ist ------------------------------------
    # Ohne sie war der Kurs auf jeder Distanz so glatt, dass das
    # Kurvenlimit der Physik bei 300 km/h lag und nie gebunden hat —
    # Abfahrtstechnik und Risikobereitschaft waren dadurch auf allen
    # mitgelieferten Strecken wirkungslos. Eine echte Passstraße dreht
    # sich auf einem Kilometer um mehrere hundert Grad; eine
    # Bundesstraße um zwanzig.
    #
    # Die Amplitude wächst mit der Steigung: Bis 4 % bleibt es eine
    # gestreckte Landstraße, ab 8 % sind es Serpentinen.
    grade_at_point = np.gradient(ele, dist, edge_order=1)
    steep = np.clip((np.abs(grade_at_point) - 0.04) / 0.04, 0.0, 1.0)
    # Weichzeichnen, damit die Kehren nicht an der Segmentgrenze
    # anspringen, sondern in den Anstieg hineinwachsen.
    span = 41
    steep = np.convolve(np.pad(steep, span // 2, mode="edge"), np.ones(span) / span, mode="valid")
    heading = heading + SWITCHBACK_RAD * steep * np.sin(
        2.0 * math.pi * dist / SWITCHBACK_WAVELENGTH_M
    )
    lat = np.empty(n)
    lon = np.empty(n)
    lat[0], lon[0] = start_lat, start_lon
    dlat = point_spacing_m * np.cos(heading) / EARTH_R
    dlon = point_spacing_m * np.sin(heading) / EARTH_R
    lat[1:] = start_lat + np.degrees(np.cumsum(dlat[:-1]))
    lon[1:] = start_lon + np.degrees(np.cumsum(dlon[:-1] / np.cos(np.radians(lat[:-1]))))
    return lat, lon, ele


def write_gpx(path: Path, name: str, lat, lon, ele) -> None:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="UltraSim demo generator" '
        'xmlns="http://www.topografix.com/GPX/1/1">',
        f"  <trk><name>{name}</name><trkseg>",
    ]
    parts.extend(
        f'    <trkpt lat="{a:.6f}" lon="{b:.6f}"><ele>{c:.1f}</ele></trkpt>'
        for a, b, c in zip(lat, lon, ele, strict=True)
    )
    parts.append("  </trkseg></trk>")
    parts.append("</gpx>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("preset", nargs="?", default="voralpen", choices=sorted(PRESETS))
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--ele", type=float, default=None)
    ap.add_argument("--spacing", type=float, default=25.0, help="Punktabstand in m")
    ap.add_argument("--noise", type=float, default=1.2, help="DEM-Rauschen sigma in m")
    ap.add_argument("--seed", type=int, default=20240613)
    ap.add_argument("--scale", type=float, default=1.0, help="Streckenlänge skalieren")
    ap.add_argument("--all", action="store_true", help="alle Presets erzeugen")
    args = ap.parse_args(argv)

    presets = sorted(PRESETS) if args.all else [args.preset]
    for i, key in enumerate(presets):
        label, base, (lat0, lon0, ele0) = PRESETS[key]
        profile = [(length * args.scale, grade) for length, grade in base]
        lat, lon, ele = build_track(
            profile,
            args.lat if args.lat is not None else lat0,
            args.lon if args.lon is not None else lon0,
            args.ele if args.ele is not None else ele0,
            args.spacing,
            args.noise,
            args.seed + i * 101,
        )
        out = args.out if (args.out and not args.all) else Path(f"data/gpx/demo-{key}.gpx")
        write_gpx(out, args.name or label, lat, lon, ele)
        print(f"{out}: {len(lat)} Punkte, {sum(length for length, _ in profile):.1f} km")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
