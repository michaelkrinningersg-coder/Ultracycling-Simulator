"""Tests der Streckenaufbereitung (M1)."""

from __future__ import annotations

import gzip
import json

import numpy as np
import pytest

from ultrasim.geo.gpx_import import GpxImportError, import_gpx, parse_gpx, smooth_elevation
from ultrasim.geo.route import (
    Route,
    accumulate_ascent,
    classify_distance,
    compute_grade,
    haversine_m,
)
from ultrasim.geo.segmentation import climb_category
from ultrasim.geo.smoothing import savgol_coeffs, savgol_filter
from ultrasim.geo.splits import build_splits, split_spacing_m


# ----------------------------------------------------------------------
# Glättung
# ----------------------------------------------------------------------
def test_savgol_preserves_polynomial_of_its_order():
    """Ein Filter der Ordnung 2 muss eine Parabel unverändert lassen."""
    x = np.arange(200, dtype=float)
    y = 3.0 + 0.5 * x - 0.002 * x**2
    smoothed = savgol_filter(y, 21, 2)
    assert np.allclose(smoothed, y, atol=1e-6)


def test_savgol_coefficients_sum_to_one():
    """Sonst würde der Filter das Höhenniveau verschieben."""
    for window in (9, 21, 41):
        assert savgol_coeffs(window, 2).sum() == pytest.approx(1.0)


def test_savgol_rejects_even_window():
    with pytest.raises(ValueError):
        savgol_coeffs(20, 2)


def test_smoothing_removes_dem_noise():
    rng = np.random.default_rng(0)
    x = np.arange(0, 6000, 10.0)
    truth = 200.0 + 0.03 * x
    noisy = truth + rng.normal(0.0, 1.2, x.size)
    smoothed = smooth_elevation(noisy, 10.0)
    assert np.abs(smoothed - truth).mean() < 0.4
    assert np.abs(noisy - truth).mean() > 0.8


# ----------------------------------------------------------------------
# Der Kernpunkt aus Abschnitt 3.3
# ----------------------------------------------------------------------
def test_smoothing_is_not_optional(report):
    """Ohne Glättung wäre jede Zeitberechnung wertlos.

    Das Dokument beziffert den Effekt an einer Teststrecke: die
    Höhenmeter werden um rund 70 % überzeichnet und im Flachen tritt das
    Feld dauerhaft gegen eine scheinbare 4,5-%-Steigung. Genau diese
    beiden Aussagen hält dieser Test fest.
    """
    assert report.ascent_raw_m > report.ascent_smoothed_m * 1.25
    assert report.mean_abs_grade_raw > 0.03
    assert report.mean_abs_grade_smoothed < 0.015


def test_ascent_threshold_prevents_summation_blowup():
    """Ohne Mindestschwelle summiert sich jedes Restzittern auf."""
    rng = np.random.default_rng(1)
    flat = np.zeros(5000) + rng.normal(0, 0.05, 5000)
    assert accumulate_ascent(flat, threshold_m=2.0) == 0.0
    assert accumulate_ascent(flat, threshold_m=0.0) > 100.0


# ----------------------------------------------------------------------
# Route und Dateiformat
# ----------------------------------------------------------------------
def test_grade_is_clipped_and_finite(route):
    assert np.isfinite(route.grade).all()
    assert route.grade.max() <= 0.25
    assert route.grade.min() >= -0.25


def test_grade_baseline_survives_decimetre_quantisation():
    """Höhen liegen als Dezimeter-Integer vor.

    Über einen einzelnen 10-m-Schritt wäre die Quantisierung 1 %
    Steigung – gröber als der Effekt, den wir messen wollen. Die breitere
    Basis der zentralen Differenz muss das auf deutlich unter 0,2 %
    drücken.
    """
    ele = np.zeros(400)  # exakt eben
    ele_dm = np.rint(ele * 10).astype(np.int32)
    grade = compute_grade(ele_dm / 10.0, 10.0)
    assert np.abs(grade).max() < 0.002


def test_route_roundtrip_is_lossless(route, tmp_path):
    path = tmp_path / "r.json.gz"
    route.save(path)
    again = Route.load(path)
    assert again.n_points == route.n_points
    assert np.array_equal(again.ele_dm, route.ele_dm)
    assert np.allclose(again.grade, route.grade)
    assert again.distance_m == route.distance_m
    assert len(again.segments) == len(route.segments)
    assert len(again.climbs) == len(route.climbs)
    assert [s.dist_m for s in again.splits] == [s.dist_m for s in route.splits]


def test_route_file_is_byte_stable(route, tmp_path):
    """Gleiche Eingabe, gleiche Datei – sonst rauscht jeder Commit."""
    a = route.save(tmp_path / "a.json.gz").read_bytes()
    b = route.save(tmp_path / "b.json.gz").read_bytes()
    assert a == b


def test_route_file_stays_small(route, tmp_path):
    """Hochgerechnet muss eine 2500-km-Strecke unter 2 MB bleiben."""
    path = route.save(tmp_path / "r.json.gz")
    per_km = path.stat().st_size / route.distance_km
    assert per_km * 2500 < 2_000_000


def test_route_rejects_foreign_schema(route, tmp_path):
    data = route.to_dict()
    data["schema"] = 99
    path = tmp_path / "bad.json.gz"
    with gzip.open(path, "wb") as fh:
        fh.write(json.dumps(data).encode())
    with pytest.raises(ValueError, match="Schema"):
        Route.load(path)


def test_coordinates_are_coarse_but_present(route):
    """lat/lon werden für Peilung und Sonnenstand gebraucht, nicht für die Physik."""
    expected = route.distance_m / route.coord_step_m
    assert len(route.coords) <= expected + 2
    latlon = route.latlon_at(np.array([0.0, route.distance_m / 2]))
    assert latlon.shape == (2, 2)
    assert np.isfinite(latlon).all()


# ----------------------------------------------------------------------
# Segmentierung, Anstiege, Splits
# ----------------------------------------------------------------------
def test_segments_tile_the_route_without_gaps(route):
    assert route.segments
    assert route.segments[0].dist_start_m == 0.0
    for a, b in zip(route.segments[:-1], route.segments[1:], strict=False):
        assert a.dist_end_m == pytest.approx(b.dist_start_m)
    assert route.segments[-1].dist_end_m == pytest.approx(route.distance_m, abs=route.raster_m)


def test_segments_respect_max_length(route):
    assert max(s.length_m for s in route.segments) <= 500.0


def test_climbs_are_ordered_and_categorised(route):
    for climb in route.climbs:
        assert climb.dist_end_m > climb.dist_start_m
        assert climb.category in ("HC", "1", "2", "3", "4")
        assert climb.grade_avg >= 0.03
        assert climb.length_m >= 1000.0


def test_climb_categories_match_reference_climbs():
    """Zwei bekannte Anstiege als Prüfstein der Kategorisierung."""
    assert climb_category(1120, 0.081)[0] == "HC"  # Alpe d'Huez
    assert climb_category(250, 0.05)[0] == "3"  # 5 km mit 5 %
    assert climb_category(60, 0.03)[0] == ""  # zu klein für eine Kategorie


@pytest.mark.parametrize(
    "distance_m,expected",
    [(150_000, 10_000), (399_000, 10_000), (400_000, 25_000), (1_200_000, 50_000)],
)
def test_split_spacing_follows_distance(distance_m, expected):
    assert split_spacing_m(distance_m) == expected


@pytest.mark.parametrize("distance_km", [150, 300, 600, 1200, 2500])
def test_split_count_stays_readable(distance_km):
    """Ziel ist stets ein Feld von rund 30–50 Splits."""
    splits = build_splits(distance_km * 1000.0)
    assert 14 <= len(splits) <= 52
    assert splits[-1].kind == "finish"
    assert splits[-1].dist_m == pytest.approx(distance_km * 1000.0)


def test_summit_splits_replace_nearby_interval_splits(route):
    kinds = [s.kind for s in route.splits]
    assert "finish" in kinds
    dists = [s.dist_m for s in route.splits]
    assert dists == sorted(dists)
    # Keine zwei Splits dürfen sich auf die Füße treten.
    spacing = split_spacing_m(route.distance_m)
    for a, b in zip(dists[:-2], dists[1:-1], strict=False):
        assert b - a >= spacing * 0.5


@pytest.mark.parametrize(
    "km,hm,expected",
    [
        (150, 1000, "kurz"),
        (300, 3000, "kurz"),
        (500, 4000, "mittel"),
        (1000, 10000, "mittel"),
        (1300, 8000, "ultra"),
        (2500, 20000, "ultra"),
    ],
)
def test_distance_class(km, hm, expected):
    assert classify_distance(km, hm) == expected


# ----------------------------------------------------------------------
# Importfehler
# ----------------------------------------------------------------------
def test_import_reports_missing_elevation(tmp_path):
    path = tmp_path / "flat.gpx"
    points = "\n".join(
        f'<trkpt lat="47.{i:04d}" lon="11.0"/>' for i in range(50)
    )
    path.write_text(
        f'<?xml version="1.0"?><gpx version="1.1" '
        f'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{points}'
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    with pytest.raises(GpxImportError, match="Höhenangaben"):
        import_gpx(path)


def test_import_accepts_gpx_without_namespace(tmp_path):
    """Nicht jedes Werkzeug schreibt GPX 1.1 – der Namespace wird gelesen, nicht angenommen."""
    points = "\n".join(
        f'<trkpt lat="47.{i:04d}" lon="11.0"><ele>{500 + i}</ele></trkpt>' for i in range(60)
    )
    path = tmp_path / "plain.gpx"
    path.write_text(f"<gpx><trk><trkseg>{points}</trkseg></trk></gpx>", encoding="utf-8")
    lat, lon, ele = parse_gpx(path)
    assert lat.size == 60
    assert np.isfinite(ele).all()


def test_import_falls_back_to_route_points(tmp_path):
    points = "\n".join(
        f'<rtept lat="47.{i:04d}" lon="11.0"><ele>{500 + i}</ele></rtept>' for i in range(60)
    )
    path = tmp_path / "rte.gpx"
    path.write_text(f"<gpx><rte>{points}</rte></gpx>", encoding="utf-8")
    lat, _, _ = parse_gpx(path)
    assert lat.size == 60


def test_duplicate_points_are_dropped(tmp_path):
    """GPS-Pausen erzeugen Punkte ohne Ortsveränderung."""
    rows = []
    for i in range(40):
        rows.append(f'<trkpt lat="47.{i:04d}" lon="11.0"><ele>{500 + i}</ele></trkpt>')
        rows.append(f'<trkpt lat="47.{i:04d}" lon="11.0"><ele>{500 + i}</ele></trkpt>')
    path = tmp_path / "dup.gpx"
    path.write_text(f"<gpx><trk><trkseg>{''.join(rows)}</trkseg></trk></gpx>", encoding="utf-8")
    _, report = import_gpx(path)
    assert report.n_dropped_duplicates == 40
    assert np.isfinite(report.distance_m)


def test_haversine_matches_known_distance():
    """München–Hamburg, rund 612 km Luftlinie."""
    d = haversine_m(np.array(48.1372), np.array(11.5755), np.array(53.5511), np.array(9.9937))
    assert 605_000 < float(d) < 620_000
