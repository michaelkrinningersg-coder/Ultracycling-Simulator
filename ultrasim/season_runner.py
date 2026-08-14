"""Saisonbetrieb: Kalender rechnen, werten, weiterentwickeln.

Die Schichten des Projekts sind bisher: ``core`` rechnet und weiß nichts
von Dateien, ``data`` speichert und weiß nichts vom Rechnen, ``cli`` und
``web`` sind zwei Oberflächen darüber. Mit der Saison entsteht zum ersten
Mal ein Ablauf, der *beide* braucht — ein Kalenderrennen zu rechnen heißt
Feld laden, Restermüdung aus früheren Rennen holen, simulieren, ablegen
und den Kalender fortschreiben.

Dieser Ablauf gehört weder in ``core`` (das dürfte dann nicht mehr ohne
Datenverzeichnis laufen) noch in ``cli`` oder ``web`` (dann gäbe es ihn
zweimal). Deshalb liegt er hier: eine dünne Dienstschicht, die core und
data verbindet und von beiden Oberflächen benutzt wird.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from .core import season as sn
from .core.development import SeasonRecord, advance_season
from .core.engine import RaceConfig, simulate_race
from .core.rider import Rider, Team
from .data.store import RaceSummary, Store

#: Wie viele Kilojoule ein Fahrer mit ins nächste Rennen nimmt, wird über
#: alle vorherigen Rennen der Saison aufsummiert — jedes mit seinem
#: eigenen Abstand zum Renntag.
MAX_CARRY_LOOKBACK_DAYS = 120


def slugify(text: str, fallback: str = "rennen") -> str:
    """Aus einem Namen einen dateisystemtauglichen Schlüssel machen."""
    table = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e", "á": "a"}
    lowered = "".join(table.get(c, c) for c in text.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or fallback


# ----------------------------------------------------------------------
# Lesende Auswertung
# ----------------------------------------------------------------------
def race_summaries(store: Store, season: sn.Season) -> dict[str, RaceSummary]:
    """Ergebnisse aller gerechneten Termine, ohne Telemetrie.

    Ein Termin, dessen Rennen inzwischen gelöscht wurde, fällt still
    heraus statt die ganze Saisonseite mit einem Fehler zu quittieren.
    """
    out: dict[str, RaceSummary] = {}
    for calendar_race in season.sorted_races():
        if not calendar_race.race_id:
            continue
        try:
            out[calendar_race.id] = store.load_race_summary(calendar_race.race_id)
        except (FileNotFoundError, KeyError):
            continue
    return out


def coefficients(store: Store, season: sn.Season) -> dict[str, float]:
    """Rennkoeffizient je Termin, aus der Strecke oder von Hand gesetzt."""
    cache: dict[str, float] = {}
    out: dict[str, float] = {}
    for calendar_race in season.races:
        if calendar_race.coefficient is not None:
            out[calendar_race.id] = float(calendar_race.coefficient)
            continue
        if calendar_race.route_id not in cache:
            try:
                route = store.load_route(calendar_race.route_id)
            except FileNotFoundError:
                cache[calendar_race.route_id] = 1.0
            else:
                cache[calendar_race.route_id] = sn.race_coefficient(
                    route.distance_km, route.ascent_m
                )
        out[calendar_race.id] = cache[calendar_race.route_id]
    return out


def standings(store: Store, season: sn.Season) -> list[sn.Standing]:
    """Gesamtrangliste der Saison."""
    summaries = race_summaries(store, season)
    riders: dict[int, Rider] = {}
    teams: dict[int, Team] = {}
    for summary in summaries.values():
        for rider in summary.riders:
            riders.setdefault(rider.id, rider)
        for team in summary.teams:
            teams.setdefault(team.id, team)
    return sn.build_standings(season, summaries, riders, teams, coefficients(store, season))


def season_records(store: Store, season: sn.Season) -> dict[int, SeasonRecord]:
    """Saisonbilanz je Fahrer — Grundlage der Fahrerentwicklung."""
    summaries = race_summaries(store, season)
    coeff = coefficients(store, season)
    routes: dict[str, float] = {}
    out: dict[int, SeasonRecord] = {}

    for calendar_race in season.sorted_races():
        summary = summaries.get(calendar_race.id)
        if summary is None:
            continue
        if calendar_race.route_id not in routes:
            try:
                routes[calendar_race.route_id] = store.load_route(
                    calendar_race.route_id
                ).distance_km
            except FileNotFoundError:
                routes[calendar_race.route_id] = 0.0
        distance_km = routes[calendar_race.route_id]

        for entry in summary.entries:
            record = out.setdefault(entry.rider_id, SeasonRecord())
            record.starts += 1
            record.points += sn.points_for_rank(
                entry.rank, tuple(season.points_head)
            ) * coeff.get(calendar_race.id, 1.0)
            if entry.rank == 1:
                record.wins += 1
            if entry.status in ("FIN", "OTL"):
                record.finishes += 1
                record.distance_km += distance_km
            elif entry.dnf_dist_m:
                record.distance_km += entry.dnf_dist_m / 1000.0
    return out


# ----------------------------------------------------------------------
# Restermüdung
# ----------------------------------------------------------------------
def carry_work_kj(
    store: Store, season: sn.Season, target: sn.CalendarRace, riders: list[Rider]
) -> dict[int, float]:
    """Was jeder Starter aus früheren Rennen der Saison mitschleppt.

    Aufsummiert über alle vorherigen Termine, jeder mit seinem eigenen
    Abstand zum Renntag und der Regeneration des Fahrers. Ein Fahrer, der
    zwei Ultras hintereinander gefahren ist, schleppt beide — abgeklungen
    nach ihrem jeweiligen Alter.
    """
    summaries = race_summaries(store, season)
    by_id = {r.id: r for r in riders}
    out: dict[int, float] = {}

    for calendar_race in season.sorted_races():
        if calendar_race.id == target.id or calendar_race.day >= target.day:
            continue
        summary = summaries.get(calendar_race.id)
        if summary is None:
            continue
        days = (target.day - calendar_race.day).days
        if days > MAX_CARRY_LOOKBACK_DAYS:
            continue
        for entry in summary.entries:
            rider = by_id.get(entry.rider_id)
            if rider is None or entry.work_kj <= 0.0:
                continue
            out[entry.rider_id] = out.get(entry.rider_id, 0.0) + sn.residual_work_kj(
                entry.work_kj, days, rider.attr("regeneration")
            )
    return out


# ----------------------------------------------------------------------
# Rechnen
# ----------------------------------------------------------------------
@dataclass
class RunOutcome:
    race_id: str
    winner_time_s: float | None
    n_entries: int
    compute_seconds: float


def race_id_for(season: sn.Season, calendar_race: sn.CalendarRace) -> str:
    return f"{season.id}-{calendar_race.id}"


def run_calendar_race(
    store: Store,
    season: sn.Season,
    race_key: str,
    progress: Any = None,
    save_season: bool = True,
) -> RunOutcome:
    """Einen Kalendertermin rechnen, ablegen und den Kalender fortschreiben.

    Die Saison wird erst *nach* dem erfolgreichen Speichern des Rennens
    fortgeschrieben. Bricht die Rechnung ab, steht im Kalender weiterhin
    „geplant" und kein Verweis auf ein halbes Rennen.
    """
    calendar_race = season.race(race_key)
    if calendar_race is None:
        raise KeyError(f"Kein Termin '{race_key}' in Saison '{season.id}'")

    route = store.load_route(calendar_race.route_id)
    teams, pool = store.load_pool()
    riders = pool[: max(calendar_race.n_riders, 2)]

    config = RaceConfig(
        seed=calendar_race.seed,
        weather_preset=calendar_race.weather_preset,
        race_date=calendar_race.day,
        name=calendar_race.name,
        carry_work_kj=carry_work_kj(store, season, calendar_race, riders),
    )
    result = simulate_race(route, riders, teams, config, progress=progress)

    race_id = race_id_for(season, calendar_race)
    store.save_race(race_id, calendar_race.route_id, result, route=route)
    calendar_race.race_id = race_id
    if save_season:
        store.save_season(season)

    return RunOutcome(
        race_id=race_id,
        winner_time_s=result.winner_time_s,
        n_entries=len(result.entries),
        compute_seconds=result.compute_seconds,
    )


def pending_races(season: sn.Season) -> list[sn.CalendarRace]:
    """Noch nicht gerechnete Termine, in Terminreihenfolge.

    Die Reihenfolge ist nicht kosmetisch: Die Restermüdung eines Rennens
    steht erst fest, wenn das vorherige gerechnet ist.
    """
    return [r for r in season.sorted_races() if not r.computed]


# ----------------------------------------------------------------------
# Saisonwechsel
# ----------------------------------------------------------------------
def close_season(
    store: Store, season: sn.Season, seed: int, replace_retired: bool = True
) -> dict[str, Any]:
    """Saison abschließen: Fahrer altern lassen, Pool fortschreiben.

    Der Pool wird direkt überschrieben — es gibt genau einen. Wer die
    alte Fassung behalten will, muss sie vorher sichern; das ist eine
    bewusste Vereinfachung, solange es keine Mehrfachwelten gibt.
    """
    from .core.rider import generate_rider

    teams, riders = store.load_pool()
    records = season_records(store, season)
    active, retired, log = advance_season(riders, records, seed=seed)

    newcomers: list[Rider] = []
    if replace_retired and retired:
        import numpy as np

        rng = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(99, 1)))
        next_id = max((r.id for r in riders), default=0) + 1
        for gone in retired:
            newcomer = generate_rider(
                rng,
                next_id,
                gone.team_id,
                archetype="rohdiamant" if rng.random() < 0.45 else None,
                potential_mean=46.0,
            )
            # Nachwuchs ist jung: Der Generator zieht sonst auch 35-Jährige.
            newcomer.age = int(rng.integers(19, 24))
            newcomers.append(newcomer)
            next_id += 1

    store.save_pool(teams, active + newcomers)
    return {
        "season_id": season.id,
        "active": len(active),
        "retired": [{"id": r.id, "name": r.name, "age": r.age} for r in retired],
        "newcomers": [{"id": r.id, "name": r.name, "age": r.age} for r in newcomers],
        "log": log,
    }


# ----------------------------------------------------------------------
# Kalender erzeugen
# ----------------------------------------------------------------------
def suggest_calendar(
    store: Store, year: int, n_races: int = 10, first_day: date | None = None
) -> list[sn.CalendarRace]:
    """Vorschlag für einen Kalender aus den vorhandenen Strecken.

    Gedacht als Startpunkt für den Editor, nicht als letztes Wort: Die
    Termine sind gleichmäßig über die Saison verteilt, und lange Rennen
    bekommen mehr Luft danach — genau das, was der Nutzer danach von Hand
    verschiebt.
    """
    routes = store.list_routes()
    if not routes:
        return []
    start = first_day or date(year, 4, 1)
    out: list[sn.CalendarRace] = []
    day = start
    for i in range(n_races):
        route = routes[i % len(routes)]
        key = f"{i + 1:02d}-{slugify(route['name'])}"
        out.append(
            sn.CalendarRace(
                id=key,
                name=route["name"],
                route_id=route["id"],
                day=day,
                n_riders=60,
                seed=1000 + i,
            )
        )
        # Nach einem langen Rennen mehr Abstand: sonst ist der Kalender
        # von vornherein unfahrbar und jeder Vorschlag muss korrigiert
        # werden, bevor er benutzbar ist.
        gap = {"kurz": 14, "mittel": 21, "ultra": 35}.get(route["distance_class"], 21)
        day = _plus_days(day, gap)
    return out


def _plus_days(day: date, days: int) -> date:
    from datetime import timedelta

    return day + timedelta(days=days)


__all__ = [
    "RunOutcome",
    "carry_work_kj",
    "close_season",
    "coefficients",
    "pending_races",
    "race_id_for",
    "race_summaries",
    "run_calendar_race",
    "season_records",
    "slugify",
    "standings",
    "suggest_calendar",
]
