"""Segmentierung und Anstiegserkennung (Game-Design-Dokument, Abschnitt 3.4)."""

from __future__ import annotations

import numpy as np

from .route import Climb, Segment, angular_difference, bearing_series

#: Ein Segment endet, wenn sich die mittlere Steigung um mehr als das ändert …
GRADE_BREAK = 0.015
#: … oder spätestens nach dieser Länge.
MAX_SEGMENT_M = 500.0
#: Kürzer als das wird nicht getrennt – sonst zerfällt welliges Gelände
#: in Hunderte Mini-Segmente ohne Informationsgewinn.
MIN_SEGMENT_M = 100.0

# --- Anstiegserkennung -------------------------------------------------
CLIMB_ENTER_GRADE = 0.02
CLIMB_MIN_LENGTH_M = 1000.0
CLIMB_MIN_AVG_GRADE = 0.03
#: Kurze Verflachungen beenden einen Anstieg nicht (Kehren, Zwischenstücke).
CLIMB_GAP_M = 400.0

#: Kategoriegrenzen über score = Höhenmeter x mittlere Steigung in Prozent.
#: Zum Abgleich: Alpe d'Huez (1120 hm, 8,1 %) ergibt 9072 -> HC,
#: 5 km mit 5 % (250 hm) ergibt 1250 -> Kategorie 3.
CATEGORY_THRESHOLDS = (
    (8000.0, "HC"),
    (4800.0, "1"),
    (2400.0, "2"),
    (1200.0, "3"),
    (500.0, "4"),
)


def classify_segment(grade: float, length_m: float) -> str:
    """Geländeklasse eines Segments (Abschnitt 3.4)."""
    if grade > 0.10:
        return "steilrampe"
    if grade >= 0.03:
        return "anstieg"
    if grade >= 0.02:
        return "welliger_anstieg"
    if grade < -0.10:
        return "steilabfahrt"
    if grade <= -0.02:
        return "abfahrt"
    return "flach"


def climb_category(ascent_m: float, grade_avg: float) -> tuple[str, float]:
    score = ascent_m * grade_avg * 100.0
    for limit, name in CATEGORY_THRESHOLDS:
        if score >= limit:
            return name, score
    return "", score


def build_segments(
    ele_m: np.ndarray,
    grade: np.ndarray,
    raster_m: float,
    coords_fine: np.ndarray | None = None,
) -> list[Segment]:
    """Zerlegt die Route in Simulationssegmente.

    ``coords_fine`` sind die lat/lon je Rasterpunkt. Sie werden nur für
    Peilung und Kurvigkeit gebraucht und danach verworfen – in der
    Streckendatei stehen später nur noch grobe Koordinaten.
    """
    n = int(ele_m.size)
    if n < 2:
        return []

    bearings = bearing_series(coords_fine) if coords_fine is not None else None
    if bearings is not None:
        turn = np.zeros(n)
        turn[1:] = angular_difference(bearings[1:], bearings[:-1])
    else:
        turn = None

    max_steps = max(1, int(round(MAX_SEGMENT_M / raster_m)))
    min_steps = max(1, int(round(MIN_SEGMENT_M / raster_m)))

    boundaries: list[int] = [0]
    start = 0
    run_sum = 0.0
    for i in range(1, n):
        run_sum += float(grade[i])
        count = i - start
        mean = run_sum / count
        too_long = count >= max_steps
        drifted = count >= min_steps and abs(float(grade[i]) - mean) > GRADE_BREAK
        if too_long or drifted:
            boundaries.append(i)
            start = i
            run_sum = 0.0
    if boundaries[-1] != n - 1:
        boundaries.append(n - 1)

    segments: list[Segment] = []
    for idx, (lo, hi) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=False)):
        length = (hi - lo) * raster_m
        if length <= 0:
            continue
        delta = float(ele_m[hi] - ele_m[lo])
        seg_grade = float(np.clip(delta / length, -0.25, 0.25))
        if turn is not None:
            curviness = float(turn[lo + 1 : hi + 1].sum()) / max(length / 1000.0, 1e-6)
            brg = float(bearings[lo])  # type: ignore[index]
        else:
            curviness = 0.0
            brg = 0.0
        segments.append(
            Segment(
                idx=idx,
                dist_start_m=lo * raster_m,
                length_m=length,
                delta_ele_m=round(delta, 2),
                grade=round(seg_grade, 5),
                ele_mid_m=round(float(ele_m[(lo + hi) // 2]), 1),
                bearing_deg=round(brg, 1),
                curviness=round(curviness, 1),
                kind=classify_segment(seg_grade, length),
            )
        )
    return segments


def build_climbs(segments: list[Segment], ele_m: np.ndarray, raster_m: float) -> list[Climb]:
    """Fasst Segmente zu kategorisierten Anstiegen zusammen."""
    if not segments:
        return []

    runs: list[tuple[int, int]] = []  # (erstes Segment, letztes Segment)
    open_run: list[int] | None = None
    gap_m = 0.0
    for seg in segments:
        if seg.grade >= CLIMB_ENTER_GRADE:
            if open_run is None:
                open_run = [seg.idx, seg.idx]
            else:
                open_run[1] = seg.idx
            gap_m = 0.0
        elif open_run is not None:
            # Verflachung: kurz tolerieren, echte Abfahrt beendet den Anstieg.
            gap_m += seg.length_m
            if gap_m > CLIMB_GAP_M or seg.grade < -CLIMB_ENTER_GRADE:
                runs.append((open_run[0], open_run[1]))
                open_run = None
                gap_m = 0.0
    if open_run is not None:
        runs.append((open_run[0], open_run[1]))

    climbs: list[Climb] = []
    for first, last in runs:
        d_start = segments[first].dist_start_m
        d_end = segments[last].dist_end_m
        length = d_end - d_start
        if length < CLIMB_MIN_LENGTH_M:
            continue
        lo = int(d_start // raster_m)
        hi = min(int(round(d_end / raster_m)), ele_m.size - 1)
        ascent = float(ele_m[hi] - ele_m[lo])
        if ascent <= 0:
            continue
        grade_avg = ascent / length
        if grade_avg < CLIMB_MIN_AVG_GRADE:
            continue
        grade_max = max(s.grade for s in segments[first : last + 1])
        category, score = climb_category(ascent, grade_avg)
        if not category:
            continue
        climbs.append(
            Climb(
                idx=len(climbs),
                dist_start_m=d_start,
                dist_end_m=d_end,
                length_m=length,
                ascent_m=round(ascent, 1),
                grade_avg=round(grade_avg, 4),
                grade_max=round(grade_max, 4),
                category=category,
                score=round(score, 1),
            )
        )
    return climbs
