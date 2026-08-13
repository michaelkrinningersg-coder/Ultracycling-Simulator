"""GPX-Import (Game-Design-Dokument, Abschnitt 3.6).

Der Importer ist das Nadelöhr zwischen realer Welt und Simulation. Er
läuft als CLI auf dem Entwicklungsrechner, nicht in der Anwendung:

    python -m ultrasim.geo.gpx_import strecke.gpx -o data/routes/strecke.json.gz

Verarbeitungskette: Parsen -> Distanz -> Duplikate -> fehlende Höhen ->
Resampling -> Glättung -> Steigung -> Segmentierung -> Anstiege ->
Splits/Servicepunkte -> gzip-JSON.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .route import Route, accumulate_ascent, classify_distance, compute_grade, haversine_m
from .segmentation import build_climbs, build_segments
from .smoothing import moving_median, savgol_filter
from .splits import build_service_points, build_splits

#: Feste Distanzschritte des Resamplings. Ab hier ist alles gleichmäßig
#: und vektorisierbar.
RASTER_M = 10
#: Glättungsfenster in Metern (Savitzky-Golay, Ordnung 2).
SMOOTH_WINDOW_M = 210
SMOOTH_ORDER = 2
#: Fenster des Median-Vorlaufs gegen Einzelausreißer (Brücken, Tunnel).
DESPIKE_WINDOW_M = 50
#: Koordinaten werden nur alle 1000 m gespeichert – sie werden für
#: Sonnenstand, Windrichtung und Peilung gebraucht, nicht für die Physik.
COORD_STEP_M = 1000
#: Punkte mit geringerem Abstand gelten als Duplikat (GPS-Pause).
MIN_POINT_DIST_M = 0.5


class GpxImportError(RuntimeError):
    """Fachlicher Fehler beim Import – mit einer Meldung für den Nutzer."""


@dataclass
class ImportReport:
    """Was der Import gefunden hat – wird vom CLI ausgegeben."""

    name: str
    n_raw_points: int
    n_dropped_duplicates: int
    n_interpolated_ele: int
    distance_m: float
    ascent_raw_m: float
    ascent_smoothed_m: float
    mean_abs_grade_raw: float
    mean_abs_grade_smoothed: float
    n_segments: int
    n_climbs: int
    n_splits: int
    n_service_points: int
    distance_class: str

    def as_text(self) -> str:
        lines = [
            f"Strecke:            {self.name}",
            f"Distanz:            {self.distance_m / 1000:.1f} km",
            f"Distanzklasse:      {self.distance_class}",
            f"Höhenmeter:         {self.ascent_smoothed_m:.0f} m "
            f"(ungeglättet wären es {self.ascent_raw_m:.0f} m)",
            f"Ø |Steigung|:       {self.mean_abs_grade_smoothed * 100:.2f} % "
            f"(ungeglättet {self.mean_abs_grade_raw * 100:.2f} %)",
            f"GPX-Punkte:         {self.n_raw_points} "
            f"({self.n_dropped_duplicates} Duplikate entfernt, "
            f"{self.n_interpolated_ele} Höhen interpoliert)",
            f"Segmente:           {self.n_segments}",
            f"Anstiege:           {self.n_climbs}",
            f"Splits:             {self.n_splits}",
            f"Servicepunkte:      {self.n_service_points}",
        ]
        return "\n".join(lines)


# ----------------------------------------------------------------------
# Schritt 1: Parsen
# ----------------------------------------------------------------------
def _local(tag: str) -> str:
    """Tag ohne Namespace.

    Der Namespace wird aus der Datei bestimmt, nicht angenommen – nicht
    jedes Werkzeug schreibt GPX 1.1, und manches schreibt gar keinen
    Namespace.
    """
    return tag.rsplit("}", 1)[-1]


def parse_gpx(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Liest lat/lon/ele aus einer GPX-Datei.

    Bevorzugt ``trkpt``; ersatzweise ``rtept``, ersatzweise ``wpt``.
    Fehlende Höhen kommen als NaN zurück.
    """
    path = Path(path)
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:  # pragma: no cover - Fehlerpfad
        raise GpxImportError(f"{path.name}: kein gültiges XML ({exc})") from exc

    root = tree.getroot()
    buckets: dict[str, list[tuple[float, float, float]]] = {"trkpt": [], "rtept": [], "wpt": []}
    for elem in root.iter():
        kind = _local(elem.tag)
        if kind not in buckets:
            continue
        try:
            lat = float(elem.attrib["lat"])
            lon = float(elem.attrib["lon"])
        except (KeyError, ValueError):
            continue
        ele = np.nan
        for child in elem:
            if _local(child.tag) == "ele" and child.text:
                try:
                    ele = float(child.text.strip())
                except ValueError:
                    ele = np.nan
                break
        buckets[kind].append((lat, lon, ele))

    for kind in ("trkpt", "rtept", "wpt"):
        if len(buckets[kind]) >= 2:
            pts = np.asarray(buckets[kind], dtype=np.float64)
            return pts[:, 0], pts[:, 1], pts[:, 2]

    raise GpxImportError(
        f"{path.name}: keine verwertbaren Punkte gefunden "
        "(weder trkpt noch rtept noch wpt mit mindestens 2 Einträgen)"
    )


# ----------------------------------------------------------------------
# Schritte 2–4: Distanz, Duplikate, fehlende Höhen
# ----------------------------------------------------------------------
def cumulative_distance(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    step = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])
    return np.concatenate([[0.0], np.cumsum(step)])


def drop_duplicates(
    lat: np.ndarray, lon: np.ndarray, ele: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Entfernt Punkte ohne Ortsveränderung.

    GPS-Pausen erzeugen Punkte, die sich nicht bewegen. Die würden im
    Resampling zu einer Division durch null führen.
    """
    dist = cumulative_distance(lat, lon)
    keep = np.ones(dist.size, dtype=bool)
    last = 0.0
    for i in range(1, dist.size):
        if dist[i] - last < MIN_POINT_DIST_M:
            keep[i] = False
        else:
            last = dist[i]
    keep[0] = True
    dropped = int((~keep).sum())
    lat, lon, ele = lat[keep], lon[keep], ele[keep]
    return lat, lon, ele, cumulative_distance(lat, lon), dropped


def interpolate_missing_elevation(dist: np.ndarray, ele: np.ndarray) -> tuple[np.ndarray, int]:
    """Füllt einzelne Höhenlücken linear.

    Fehlt die Höhe durchgängig, bricht der Import ab – dann muss ein
    Höhendienst vorgeschaltet werden.
    """
    missing = ~np.isfinite(ele)
    n_missing = int(missing.sum())
    if n_missing == 0:
        return ele, 0
    if missing.all():
        raise GpxImportError(
            "Die Datei enthält keinerlei Höhenangaben. Ohne Höhen ist keine "
            "sinnvolle Simulation möglich – bitte die GPX-Datei vorher durch "
            "einen Höhendienst (z. B. OpenTopoData mit Copernicus GLO-30) "
            "anreichern."
        )
    filled = ele.copy()
    filled[missing] = np.interp(dist[missing], dist[~missing], ele[~missing])
    return filled, n_missing


# ----------------------------------------------------------------------
# Schritte 5–7: Resampling, Glättung, Steigung
# ----------------------------------------------------------------------
def resample(
    dist: np.ndarray,
    values: np.ndarray,
    raster_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    total = float(dist[-1])
    n = int(total // raster_m) + 1
    if n < 2:
        raise GpxImportError(
            f"Strecke ist mit {total:.1f} m zu kurz für ein {raster_m:.0f}-m-Raster."
        )
    grid = np.arange(n, dtype=np.float64) * raster_m
    return grid, np.interp(grid, dist, values)


def smooth_elevation(
    ele: np.ndarray,
    raster_m: float,
    window_m: float = SMOOTH_WINDOW_M,
    order: int = SMOOTH_ORDER,
    despike: bool = True,
) -> np.ndarray:
    """Glättung der Höhenreihe – nicht verhandelbar (Abschnitt 3.3).

    Rohe DEM-Höhen liefern unbrauchbare Momentansteigungen: ±1 m
    Höhenrauschen auf 20 m Punktabstand ergibt scheinbare 5 % Steigung im
    ebenen Gelände. Ohne Glättung fährt das Feld dauernd Achterbahn.
    """
    out = np.asarray(ele, dtype=np.float64)
    if despike:
        out = moving_median(out, max(3, int(round(DESPIKE_WINDOW_M / raster_m)) | 1))
    window = max(order + 2, int(round(window_m / raster_m)))
    if window % 2 == 0:
        window += 1
    return savgol_filter(out, window, order)


# ----------------------------------------------------------------------
# Gesamtkette
# ----------------------------------------------------------------------
def import_gpx(
    path: str | Path,
    name: str | None = None,
    raster_m: int = RASTER_M,
    smooth_window_m: float = SMOOTH_WINDOW_M,
    despike: bool = True,
    control_points_m: list[float] | None = None,
) -> tuple[Route, ImportReport]:
    path = Path(path)
    lat, lon, ele = parse_gpx(path)
    n_raw = int(lat.size)

    lat, lon, ele, dist, dropped = drop_duplicates(lat, lon, ele)
    if lat.size < 2:
        raise GpxImportError(f"{path.name}: nach dem Entfernen von Duplikaten bleiben < 2 Punkte.")
    ele, n_interp = interpolate_missing_elevation(dist, ele)

    grid, ele_grid = resample(dist, ele, raster_m)
    _, lat_grid = resample(dist, lat, raster_m)
    _, lon_grid = resample(dist, lon, raster_m)

    ele_smooth = smooth_elevation(ele_grid, raster_m, smooth_window_m, despike=despike)

    # Ab hier wird ausschließlich mit der quantisierten Höhenreihe
    # gerechnet. Damit liefert eine frisch importierte Route exakt
    # dieselben Steigungen wie eine aus der Datei geladene.
    ele_dm = np.rint(ele_smooth * 10.0).astype(np.int32)
    ele_q = ele_dm.astype(np.float64) / 10.0
    grade = compute_grade(ele_q, raster_m)

    coords_fine = np.column_stack([lat_grid, lon_grid])
    segments = build_segments(ele_q, grade, raster_m, coords_fine)
    climbs = build_climbs(segments, ele_q, raster_m)

    distance_m = float(grid[-1])
    ascent = accumulate_ascent(ele_q)
    distance_class = classify_distance(distance_m / 1000.0, ascent)

    splits = build_splits(distance_m, climbs, control_points_m)
    service_points = build_service_points(distance_m, distance_class)

    step = max(1, int(round(COORD_STEP_M / raster_m)))
    coarse_idx = np.arange(0, coords_fine.shape[0], step)
    if coarse_idx[-1] != coords_fine.shape[0] - 1:
        coarse_idx = np.append(coarse_idx, coords_fine.shape[0] - 1)
    coords = coords_fine[coarse_idx]

    route = Route(
        name=name or path.stem,
        source=path.name,
        raster_m=raster_m,
        ele_dm=ele_dm,
        coords=coords,
        coord_step_m=COORD_STEP_M,
        segments=segments,
        climbs=climbs,
        splits=splits,
        service_points=service_points,
    )

    # Für den Vergleich im Bericht: so würde die Steigung ohne Schritt 6
    # aussehen – naive Differenz über einen einzelnen Rasterschritt auf der
    # ungeglätteten Höhenreihe. Genau das ist der Fehler, den die Glättung
    # verhindert.
    grade_raw = np.gradient(ele_grid, raster_m)
    flat = np.abs(grade) < 0.02  # "flacher Abschnitt" nach der Glättung
    report = ImportReport(
        name=route.name,
        n_raw_points=n_raw,
        n_dropped_duplicates=dropped,
        n_interpolated_ele=n_interp,
        distance_m=distance_m,
        ascent_raw_m=accumulate_ascent(ele_grid),
        ascent_smoothed_m=ascent,
        mean_abs_grade_raw=float(np.abs(grade_raw[flat]).mean()) if flat.any() else 0.0,
        mean_abs_grade_smoothed=float(np.abs(grade[flat]).mean()) if flat.any() else 0.0,
        n_segments=len(segments),
        n_climbs=len(climbs),
        n_splits=len(splits),
        n_service_points=len(service_points),
        distance_class=distance_class,
    )
    return route, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ultrasim.geo.gpx_import",
        description="GPX-Datei in eine fertige Streckendatei für UltraSim übersetzen.",
    )
    parser.add_argument("gpx", type=Path, help="Eingabedatei (.gpx)")
    parser.add_argument(
        "-o", "--out", type=Path, default=None, help="Ausgabedatei (.json.gz), Standard: data/routes/"
    )
    parser.add_argument("--name", default=None, help="Anzeigename der Strecke")
    parser.add_argument("--raster", type=int, default=RASTER_M, help="Rasterweite in m")
    parser.add_argument(
        "--smooth-window", type=float, default=SMOOTH_WINDOW_M, help="Glättungsfenster in m"
    )
    parser.add_argument(
        "--no-despike", action="store_true", help="Median-Vorlauf gegen Ausreißer abschalten"
    )
    parser.add_argument(
        "--control-point",
        type=float,
        action="append",
        default=None,
        metavar="KM",
        help="zusätzlicher Kontrollpunkt-Split (mehrfach angebbar)",
    )
    args = parser.parse_args(argv)

    try:
        route, report = import_gpx(
            args.gpx,
            name=args.name,
            raster_m=args.raster,
            smooth_window_m=args.smooth_window,
            despike=not args.no_despike,
            control_points_m=[km * 1000.0 for km in (args.control_point or [])],
        )
    except GpxImportError as exc:
        print(f"Import fehlgeschlagen: {exc}", file=sys.stderr)
        return 2

    out = args.out or Path("data/routes") / f"{_slug(route.name)}.json.gz"
    route.save(out)
    size_kb = out.stat().st_size / 1024.0
    print(report.as_text())
    print(f"Geschrieben:        {out} ({size_kb:.0f} kB)")
    return 0


def _slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "route"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
