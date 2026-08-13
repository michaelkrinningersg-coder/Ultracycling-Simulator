"""Splits und Servicepunkte (Game-Design-Dokument, Abschnitte 3.5 und 6.3)."""

from __future__ import annotations

from .route import Climb, ServicePoint, Split

#: Split-Abstand nach Streckenlänge. Ziel ist stets ein Feld von 30–50
#: Splits – genug für Dramaturgie, wenig genug für ein lesbares Board.
SPLIT_SPACING_M = ((400_000.0, 10_000.0), (1_200_000.0, 25_000.0), (float("inf"), 50_000.0))

#: Abstand der Treffpunkte mit dem Begleitfahrzeug, nach Distanzklasse.
SERVICE_SPACING_M = {"kurz": 60_000.0, "mittel": 90_000.0, "ultra": 120_000.0}


def split_spacing_m(distance_m: float) -> float:
    for limit, spacing in SPLIT_SPACING_M:
        if distance_m < limit:
            return spacing
    return SPLIT_SPACING_M[-1][1]


def build_splits(
    distance_m: float,
    climbs: list[Climb] | None = None,
    extra_dists_m: list[float] | None = None,
) -> list[Split]:
    """Automatische Splits: regelmäßiges Raster plus markante Punkte.

    Gipfel kategorisierter Anstiege verdrängen einen nahen Rastersplit –
    ein Zeitmesspunkt 800 m vor der Passhöhe erzählt nichts, was der
    Gipfelsplit nicht besser erzählen würde.
    """
    spacing = split_spacing_m(distance_m)
    candidates: list[tuple[float, str, str]] = []

    d = spacing
    while d < distance_m - spacing * 0.25:
        candidates.append((d, f"km {d / 1000:.0f}", "interval"))
        d += spacing

    for climb in climbs or []:
        if climb.summit_dist_m < distance_m:
            label = f"Gipfel {climb.category} (km {climb.summit_dist_m / 1000:.0f})"
            candidates.append((climb.summit_dist_m, label, "summit"))

    for extra in extra_dists_m or []:
        if 0.0 < extra < distance_m:
            candidates.append((extra, f"KP km {extra / 1000:.0f}", "control"))

    # Nach Distanz sortieren; bei Konflikten gewinnt der markante Punkt.
    priority = {"summit": 0, "control": 1, "interval": 2}
    candidates.sort(key=lambda c: (c[0], priority[c[2]]))

    merged: list[tuple[float, str, str]] = []
    min_gap = spacing * 0.5
    for dist, name, kind in candidates:
        if merged and dist - merged[-1][0] < min_gap:
            # Der wichtigere der beiden bleibt stehen.
            if priority[kind] < priority[merged[-1][2]]:
                merged[-1] = (dist, name, kind)
            continue
        merged.append((dist, name, kind))

    merged.append((distance_m, "Ziel", "finish"))
    return [
        Split(idx=i, dist_m=round(dist, 1), name=name, kind=kind)
        for i, (dist, name, kind) in enumerate(merged)
    ]


def build_service_points(distance_m: float, distance_class: str) -> list[ServicePoint]:
    """Servicepunkte im klassenabhängigen Abstand (supported-Modus)."""
    spacing = SERVICE_SPACING_M.get(distance_class, 90_000.0)
    points: list[ServicePoint] = []
    d = spacing
    while d < distance_m - spacing * 0.4:
        points.append(
            ServicePoint(idx=len(points), dist_m=round(d, 1), name=f"SP {len(points) + 1}")
        )
        d += spacing
    return points
