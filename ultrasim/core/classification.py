"""Nebenwertungen: Team, Nation, Berg.

Eine Ergebnisliste beantwortet „wer war schneller". Ein Rundfahrtsport
beantwortet mehr Fragen als diese eine, und zwar aus denselben Zahlen:
Welche Mannschaft war in der Breite die stärkste? Welches Land? Wer war
am Berg vorn?

**Warum reine Funktionen ohne Speicher und ohne Web:** wie beim
Rennbericht in ``narrative``. Eine Wertung ist Auswertung, keine
Simulation, aber sie gehört zur Sache und nicht zur Oberfläche — so
kann sie die Ergebnisseite benutzen, die Saisonseite, später ein
Export, und ein Test kann sie prüfen, ohne ein Rennen zu rechnen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "TEAM_SCORERS",
    "MOUNTAIN_POINTS",
    "TeamResult",
    "GroupStanding",
    "ClimbRow",
    "ClimbResult",
    "effective_scorers",
    "team_race_ranking",
    "group_season_points",
    "mountain_ranking",
    "times_at_distance",
]

#: So viele Fahrer eines Teams werten je Rennen. Drei ist der Standard
#: im Radsport: Er belohnt Spitze *und* Tiefe, ohne dass bei Punkten bis
#: Rang 150 am Ende das Mittelfeld über den Titel entscheidet.
TEAM_SCORERS = 3

#: Bergpunkte je Kategorie und Platzierung am Gipfel. Die Staffelung
#: folgt dem Prinzip, dass ein „Hors Catégorie" mehr wiegt als zwei
#: Anstiege der ersten Kategorie — sonst wäre die Wertung nur eine
#: Zählung der Anstiege, die einer zufällig zuerst erreicht hat.
MOUNTAIN_POINTS: dict[str, tuple[int, ...]] = {
    "HC": (20, 16, 12, 8, 6, 4, 2, 1),
    "1": (10, 8, 6, 4, 2, 1),
    "2": (6, 4, 2, 1),
    "3": (4, 2, 1),
    "4": (2, 1),
}


@dataclass
class TeamResult:
    """Eine Zeile der Teamwertung eines Rennens."""

    team_id: int
    name: str
    color: str
    #: Die gewerteten Fahrer, in Zielreihenfolge.
    scorers: list[Any] = field(default_factory=list)
    #: Summe ihrer Zielzeiten. ``None``, wenn das Team nicht genug
    #: Fahrer ins Ziel gebracht hat — eine Teilsumme wäre schneller als
    #: eine vollständige und würde die Wertung auf den Kopf stellen.
    total_s: float | None = None
    finishers: int = 0
    starters: int = 0
    rank: int | None = None


@dataclass
class GroupStanding:
    """Eine Zeile der Team- oder Nationenwertung einer Saison."""

    key: str
    name: str
    points: float = 0.0
    wins: int = 0
    podiums: int = 0
    starters: int = 0
    #: Punkte je Termin, in Kalenderreihenfolge — für den Verlauf.
    per_race: dict[str, float] = field(default_factory=dict)
    rank: int | None = None


@dataclass
class ClimbRow:
    """Eine Zeile der Wertung eines einzelnen Anstiegs."""

    name: str
    team: str
    #: Reine **Anstiegszeit**: vom Fuß bis zum Gipfel.
    time_s: float
    #: Höhenmeter je Stunde — die Zahl, in der Kletterer sich messen.
    #: Sie macht Anstiege verschiedener Länge vergleichbar.
    vam_mh: float
    points: int


@dataclass
class ClimbResult:
    """Ein kategorisierter Anstieg mit seiner Wertung."""

    idx: int
    category: str
    foot_m: float
    summit_m: float
    length_m: float
    ascent_m: float
    rows: list[ClimbRow] = field(default_factory=list)


def times_at_distance(telemetry, dist_m: float) -> np.ndarray:
    """Eigenzeit je Fahrer beim Erreichen einer Distanzmarke.

    ``NaN`` für alle, die nie so weit gekommen sind.

    **Zwischen den Abtastpunkten wird interpoliert**, und das ist keine
    Verzierung: Auf einem Ultra liegt das Raster bei 30 Sekunden. Eine
    Bergzeit aus zwei gerundeten Marken hätte damit bis zu einer Minute
    Fehler — bei Anstiegen, die in fünf Sekunden entschieden werden, wäre
    die Wertung dann eine Aussage über das Abtastraster.
    """
    dist = telemetry.dist_m
    reached = dist >= dist_m
    ever = reached.any(axis=1)
    idx = reached.argmax(axis=1)
    prev = np.maximum(idx - 1, 0)
    rows = np.arange(dist.shape[0])

    d0 = dist[rows, prev].astype(np.float64)
    d1 = dist[rows, idx].astype(np.float64)
    span = d1 - d0
    frac = np.where(span > 0.0, (dist_m - d0) / np.where(span > 0.0, span, 1.0), 0.0)
    frac = np.clip(frac, 0.0, 1.0)
    return np.where(ever, (prev + frac) * telemetry.sample_dt_s, np.nan)


def effective_scorers(
    entries: Sequence[Any], riders: dict[int, Any], limit: int = TEAM_SCORERS
) -> int:
    """Wie viele Fahrer je Team dieses Feld hergibt.

    Bei vollem Startfeld sind das die drei aus ``TEAM_SCORERS``. Bei
    vierzig Startern aus fünfundzwanzig Teams sind höchstens zwei je
    Mannschaft am Start — eine Wertung, die drei verlangt, bestünde dann
    aus fünfundzwanzig Strichen. Die Regel gibt nach, statt die Seite
    leerzulassen.
    """
    counts: dict[int, int] = {}
    for entry in entries:
        rider = riders.get(entry.rider_id)
        if rider is not None:
            counts[rider.team_id] = counts.get(rider.team_id, 0) + 1
    return max(1, min(limit, max(counts.values(), default=1)))


def team_race_ranking(
    entries: Sequence[Any],
    riders: dict[int, Any],
    teams: dict[int, Any],
    scorers: int = TEAM_SCORERS,
) -> list[TeamResult]:
    """Teamwertung eines Rennens: Summe der ``scorers`` besten Zeiten.

    Ein Team ohne genug Zielankünfte steht am Ende der Liste, nicht
    an ihrer Spitze: Zwei Fahrer im Ziel ergeben eine kleinere Summe als
    drei, und ohne diese Regel gewönne die Mannschaft mit den meisten
    Ausfällen.
    """
    by_team: dict[int, list[Any]] = {}
    starters: dict[int, int] = {}
    for entry in entries:
        rider = riders.get(entry.rider_id)
        if rider is None:
            continue
        starters[rider.team_id] = starters.get(rider.team_id, 0) + 1
        if entry.finish_time_s is not None:
            by_team.setdefault(rider.team_id, []).append(entry)

    out: list[TeamResult] = []
    for team_id, count in starters.items():
        team = teams.get(team_id)
        finished = sorted(
            by_team.get(team_id, []), key=lambda e: e.finish_time_s  # type: ignore[arg-type,return-value]
        )
        best = finished[:scorers]
        out.append(
            TeamResult(
                team_id=team_id,
                name=team.name if team else str(team_id),
                color=team.color if team else "#888888",
                scorers=best,
                total_s=(
                    sum(e.finish_time_s for e in best) if len(best) == scorers else None
                ),
                finishers=len(finished),
                starters=count,
            )
        )

    out.sort(key=lambda r: (r.total_s is None, r.total_s or 0.0, -r.finishers))
    for i, row in enumerate(out, start=1):
        row.rank = i if row.total_s is not None else None
    return out


def group_season_points(
    summaries: dict[str, Any],
    key_of_rider: Any,
    name_of_key: Any,
    coefficients: dict[str, float],
    points_head: Sequence[int],
    scorers: int | None = TEAM_SCORERS,
) -> list[GroupStanding]:
    """Punkte einer Saison, gruppiert nach Team oder Nation.

    ``scorers`` begrenzt, wie viele Fahrer einer Gruppe je Rennen
    werten. ``None`` heißt: alle — das ist die richtige Antwort für die
    Nationenwertung, bei der die Gruppen ganz verschieden groß sind und
    eine feste Zahl das kleine Land bevorzugen würde.
    """
    from . import season as sn

    head = tuple(points_head) or sn.POINTS_HEAD
    out: dict[str, GroupStanding] = {}

    for race_key, summary in summaries.items():
        coefficient = coefficients.get(race_key, 1.0)
        riders = {r.id: r for r in summary.riders}
        scored: dict[str, list[tuple[int, float]]] = {}
        for entry in summary.entries:
            rider = riders.get(entry.rider_id)
            if rider is None:
                continue
            key = str(key_of_rider(rider))
            group = out.setdefault(key, GroupStanding(key=key, name=name_of_key(rider)))
            group.starters += 1
            if entry.rank == 1:
                group.wins += 1
            if entry.rank and entry.rank <= 3:
                group.podiums += 1
            if entry.rank:
                points = sn.points_for_rank(entry.rank, head) * coefficient
                scored.setdefault(key, []).append((entry.rank, points))

        for key, rows in scored.items():
            rows.sort(key=lambda pair: pair[0])
            taken = rows if scorers is None else rows[:scorers]
            gained = sum(points for _, points in taken)
            out[key].points += gained
            out[key].per_race[race_key] = gained

    ranked = sorted(out.values(), key=lambda g: (-g.points, -g.wins, g.name))
    for i, group in enumerate(ranked, start=1):
        group.rank = i
    return ranked


def mountain_ranking(
    result: Any, route: Any, riders: dict[int, Any], teams: dict[int, Any], top: int = 8
) -> tuple[list[ClimbResult], list[GroupStanding]]:
    """Bergwertung: Punkte an jedem kategorisierten Anstieg.

    Gewertet wird die **reine Anstiegszeit vom Fuß bis zum Gipfel**,
    jeder Anstieg für sich. Das ist der Unterschied zwischen einer
    Bergwertung und einer zweiten Gesamtwertung: Die Zeit *am* Gipfel
    trägt alles mit, was vorher passiert ist — eine Panne bei km 40
    entschiede dann über den Berg bei km 200. Die Zeit *im* Anstieg
    trägt nur den Anstieg.

    Die Uhr läuft dabei durch: Wer im Anstieg an einem Servicepunkt
    hält, verliert die Zeit. Das ist gewollt — sie ist genauso
    verloren wie die eines Fahrers, der langsam tritt.

    Zurück kommen die Anstiege einzeln und die Gesamtwertung — dieselben
    Zahlen, einmal als Chronik und einmal als Tabelle.
    """
    climbs: list[ClimbResult] = []
    totals: dict[str, GroupStanding] = {}

    for climb in route.climbs:
        table = MOUNTAIN_POINTS.get(climb.category)
        if not table:
            continue
        foot = times_at_distance(result.telemetry, climb.dist_start_m)
        summit = times_at_distance(result.telemetry, climb.dist_end_m)
        # Ohne Gipfelzeit keine Wertung: Wer den Anstieg nicht zu Ende
        # gefahren ist, hat ihn nicht gefahren.
        climbing = np.where(np.isfinite(summit), summit - foot, np.nan)
        order = [i for i in np.argsort(climbing) if np.isfinite(climbing[i])]
        rows: list[ClimbRow] = []
        for place, entry_id in enumerate(order[: max(len(table), top)]):
            entry = result.entries[int(entry_id)]
            rider = riders.get(entry.rider_id)
            if rider is None:
                continue
            team = teams.get(rider.team_id)
            points = table[place] if place < len(table) else 0
            seconds = float(climbing[entry_id])
            rows.append(
                ClimbRow(
                    name=rider.name,
                    team=team.name if team else "",
                    time_s=seconds,
                    vam_mh=climb.ascent_m / (seconds / 3600.0) if seconds > 0 else 0.0,
                    points=points,
                )
            )
            if points:
                key = str(rider.id)
                group = totals.setdefault(
                    key, GroupStanding(key=key, name=rider.name)
                )
                group.points += points
                group.per_race[str(climb.idx)] = float(points)
                if place == 0:
                    group.wins += 1
        climbs.append(
            ClimbResult(
                idx=climb.idx,
                category=climb.category,
                foot_m=climb.dist_start_m,
                summit_m=climb.dist_end_m,
                length_m=climb.length_m,
                ascent_m=climb.ascent_m,
                rows=rows,
            )
        )

    ranked = sorted(totals.values(), key=lambda g: (-g.points, -g.wins, g.name))
    for i, group in enumerate(ranked, start=1):
        group.rank = i
    return climbs, ranked
