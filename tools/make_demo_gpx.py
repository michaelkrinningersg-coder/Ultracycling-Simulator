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

PRESETS: dict[str, tuple[str, list[tuple[float, float]], tuple[float, float, float]]] = {
    # Name -> (Anzeigename, Profil, (lat, lon, Starthöhe))
    "voralpen": ("Voralpen-Runde (Demo)", VORALPEN, (47.8214, 11.4526, 584.0)),
    "hochgebirge": ("Hochgebirgs-Marathon (Demo)", HOCHGEBIRGE, (46.5197, 9.8383, 812.0)),
    "langstrecke": ("Nordroute Langstrecke (Demo)", LANGSTRECKE, (52.3759, 9.7320, 58.0)),
    "flachetappe": ("Flachetappe Nordsee (Demo)", FLACHETAPPE, (53.5511, 8.5865, 6.0)),
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
