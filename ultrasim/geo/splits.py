"""Splits und Servicepunkte (Game-Design-Dokument, Abschnitte 3.5 und 6.3)."""

from __future__ import annotations

from .route import Climb, ServicePoint, Split

#: Abstand der Rastersplits als **Anteil der Strecke**: alle fünf
#: Prozent, also bei 5, 10, 15 … 95 % und dem Ziel bei 100 %. Das sind
#: höchstens zwanzig Zeitmessungen, unabhängig von der Länge.
#:
#: Vorher stand hier ein Abstand in Kilometern, gestaffelt nach
#: Streckenlänge — und der ergab auf den langen Strecken bis zu fünfzig
#: Marken. Die Splitmatrix wurde damit zur Tapete, das Splitmenü zur
#: Endlosliste, und eine Zwischenzeit alle fünfundzwanzig Kilometer sagt
#: über ein Rennen von zweitausend Kilometern nichts, was die vorige
#: nicht schon gesagt hätte.
#:
#: Relativ statt absolut hat einen zweiten Vorteil: Dieselbe Marke
#: bedeutet auf jeder Strecke dasselbe. „Bei 50 %" ist auf 400 km und auf
#: 2500 km die Rennmitte; „km 200" ist einmal das halbe Rennen und
#: einmal der Anfang.
SPLIT_FRACTION = 0.05

#: So viele Rastermarken höchstens — 5 % bis 95 %, das Ziel kommt dazu.
MAX_INTERVAL_SPLITS = int(round(1.0 / SPLIT_FRACTION)) - 1

#: Abstand der Treffpunkte mit dem Begleitfahrzeug, nach Distanzklasse.
SERVICE_SPACING_M = {"kurz": 60_000.0, "mittel": 90_000.0, "ultra": 120_000.0}


def split_spacing_m(distance_m: float) -> float:
    """Abstand zweier Rastersplits in Metern — fünf Prozent der Strecke."""
    return max(float(distance_m) * SPLIT_FRACTION, 1.0)


def build_splits(
    distance_m: float,
    climbs: list[Climb] | None = None,
    extra_dists_m: list[float] | None = None,
) -> list[Split]:
    """Automatische Splits: Fünfprozentraster plus markante Punkte.

    Das Raster steht bei 5, 10, 15 … 95 Prozent der Strecke, das Ziel bei
    100 — höchstens zwanzig Zeitmessungen, gleich viele auf jeder
    Strecke. Dazu kommen die Gipfel kategorisierter Anstiege, und die
    verdrängen einen nahen Rastersplit: Ein Zeitmesspunkt 800 m vor der
    Passhöhe erzählt nichts, was der Gipfelsplit nicht besser erzählen
    würde.

    **Gipfel sind nicht gedeckelt.** Die Zwanzig gilt für das Raster;
    eine Strecke mit acht kategorisierten Anstiegen bekommt sie alle.
    Ein Gipfel ohne Zeitnahme wäre in einem Radrennen das Weglassen der
    einen Stelle, an der etwas passiert.
    """
    spacing = split_spacing_m(distance_m)
    candidates: list[tuple[float, str, str]] = []

    for step in range(1, MAX_INTERVAL_SPLITS + 1):
        d = distance_m * SPLIT_FRACTION * step
        candidates.append((d, f"km {d / 1000:.0f}", "interval"))

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


#: Mindestabstand zwischen zwei Markern. Zwei Zeitmesspunkte 30 m
#: auseinander sind kein Zeitmesspunkt mehr, sondern ein Messfehler — und
#: im Board zwei Zeilen, die dasselbe sagen.
MIN_MARKER_GAP_M = 200.0


def normalise_splits(
    entries: list[tuple[float, str, str]], distance_m: float
) -> list[Split]:
    """Aus rohen (Distanz, Name, Art)-Tripeln eine saubere Splitliste.

    Sortiert, entdoppelt, neu durchnummeriert — und stellt sicher, dass
    genau ein Ziel-Split am Streckenende steht. Der Editor darf beliebig
    zerren; die Ordnung stellt diese Funktion her, nicht die Oberfläche.
    Das Ziel ist dabei nicht verhandelbar: Die Zielzeit *ist* das
    Ergebnis, und sie an km 940 einer 1000-km-Strecke zu legen wäre kein
    Editorentscheid, sondern ein kaputtes Rennen.
    """
    cleaned: list[tuple[float, str, str]] = []
    for dist_m, name, kind in entries:
        value = float(dist_m)
        if not 0.0 < value < distance_m - MIN_MARKER_GAP_M:
            continue  # das Ziel wird unten selbst gesetzt
        # Ein "Ziel" mitten auf der Strecke ist keins. Es hier stehen zu
        # lassen ergäbe zwei Zieldurchfahrten in einem Rennen — die
        # Auswertung nimmt den letzten, die Anzeige den ersten, und
        # niemand fände den Grund.
        if kind == "finish":
            kind = "control"
        cleaned.append((value, name.strip() or f"km {value / 1000:.0f}", kind or "interval"))

    cleaned.sort(key=lambda row: row[0])
    kept: list[tuple[float, str, str]] = []
    for row in cleaned:
        if kept and row[0] - kept[-1][0] < MIN_MARKER_GAP_M:
            continue
        kept.append(row)

    splits = [
        Split(idx=i, dist_m=round(dist, 1), name=name, kind=kind)
        for i, (dist, name, kind) in enumerate(kept)
    ]
    splits.append(Split(idx=len(splits), dist_m=round(distance_m, 1), name="Ziel", kind="finish"))
    return splits


def normalise_service_points(
    entries: list[tuple[float, str]], distance_m: float
) -> list[ServicePoint]:
    """Dasselbe für Servicepunkte.

    Anders als beim Ziel gibt es hier keinen Pflichteintrag: Eine Strecke
    ganz ohne Treffpunkt ist zulässig — dann fährt das Feld eben durch.
    """
    cleaned = [
        (float(dist_m), name.strip())
        for dist_m, name in entries
        if 0.0 < float(dist_m) < distance_m
    ]
    cleaned.sort(key=lambda row: row[0])
    kept: list[tuple[float, str]] = []
    for row in cleaned:
        if kept and row[0] - kept[-1][0] < MIN_MARKER_GAP_M:
            continue
        kept.append(row)
    return [
        ServicePoint(idx=i, dist_m=round(dist, 1), name=name or f"SP {i + 1}")
        for i, (dist, name) in enumerate(kept)
    ]
