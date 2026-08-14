"""Karriere führen: Jahre anlegen, abschließen, verketten.

Dieselbe Zwischenschicht-Begründung wie bei ``season_runner``: Eine
Karriere fortzuschreiben braucht ``core`` **und** ``data`` — Kalender
bauen, Wertung einfrieren, Fahrer altern lassen, Pool überschreiben. In
``core`` gehörte das nicht (dann liefe die Simulation nicht mehr ohne
Datenverzeichnis), und in Browser oder Kommandozeile auch nicht (dann
gäbe es den Ablauf zweimal).

Der Jahreswechsel ist die einzige Stelle im ganzen Programm, die
bestehende Daten überschreibt statt neue anzulegen: Der Fahrerpool
danach ist ein anderer als davor. Deshalb friert er vorher die Wertung
als Kapitel ein — sie wäre sonst unwiederbringlich, weil sich die
Wertung von 2031 aus dem Feld von 2035 nicht mehr rekonstruieren lässt.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .core import career as cr
from .core import season as sn
from .data.store import Store
from .season_runner import close_season, slugify, standings, suggest_calendar

__all__ = [
    "close_year",
    "create_career",
    "career_of_season",
    "next_calendar",
    "season_name_for",
]

#: Verschiebung des Renn-Seeds von Jahr zu Jahr. Ohne sie hätte
#: dieselbe Strecke in jedem Jahr dasselbe Wetter, dieselben Pannen und
#: dieselben Ausfälle — der Kalender bliebe gleich, die Karriere wäre
#: eine Wiederholung.
SEED_STEP_PER_YEAR = 1000


def season_name_for(career_name: str, year: int) -> str:
    return f"{career_name} {year}"


def season_id_for(career_id: str, year: int) -> str:
    return f"{career_id}-{year}"


def next_calendar(previous: sn.Season, year: int) -> list[sn.CalendarRace]:
    """Den Kalender des Vorjahres ins nächste Jahr übertragen.

    Ein Rennkalender ist im Radsport eine Konstante: Dieselben Rennen an
    ungefähr denselben Terminen, Jahr für Jahr. Genau das macht die
    ewige Bestenliste lesbar — wer den Hochgebirgs-Marathon dreimal
    gewonnen hat, hat dreimal dasselbe gewonnen. Deshalb wird der
    Kalender übertragen und nicht neu vorgeschlagen; verschieben kann
    man ihn danach im Editor.
    """
    out: list[sn.CalendarRace] = []
    for race in previous.sorted_races():
        out.append(
            sn.CalendarRace(
                id=race.id,
                name=race.name,
                route_id=race.route_id,
                day=_same_day_next_year(race.day, year),
                n_riders=race.n_riders,
                seed=race.seed + SEED_STEP_PER_YEAR,
                weather_preset=race.weather_preset,
                coefficient=race.coefficient,
                race_id=None,
            )
        )
    return out


def _same_day_next_year(day: date, year: int) -> date:
    """Gleicher Kalendertag im Zieljahr — mit Rücksicht auf den 29. Februar."""
    try:
        return day.replace(year=year)
    except ValueError:  # 29. Februar in einem Nicht-Schaltjahr
        return date(year, 3, 1)


def create_career(
    store: Store, name: str, first_year: int, n_races: int = 10
) -> tuple[cr.Career, sn.Season]:
    """Karriere mit ihrer ersten Saison anlegen."""
    career_id = slugify(name, fallback="karriere")
    season = sn.Season(
        id=season_id_for(career_id, first_year),
        name=season_name_for(name, first_year),
        year=first_year,
        races=suggest_calendar(store, first_year, n_races=n_races),
    )
    career = cr.Career(
        id=career_id,
        name=name,
        first_year=first_year,
        season_ids=[season.id],
    )
    store.save_season(season)
    store.save_career(career)
    return career, season


def career_of_season(store: Store, season_id: str) -> cr.Career | None:
    """Zu welcher Karriere gehört diese Saison — falls überhaupt einer."""
    for entry in store.list_careers():
        career = store.load_career(entry["id"])
        if season_id in career.season_ids:
            return career
    return None


def snapshot_standings(store: Store, season: sn.Season) -> list[cr.StandingSnapshot]:
    """Endstand der Wertung als Momentaufnahme."""
    return [
        cr.StandingSnapshot(
            rank=row.rank or index + 1,
            rider_id=row.rider_id,
            name=row.name,
            team_name=row.team_name,
            points=round(row.points, 1),
            wins=row.wins,
            podiums=row.podiums,
            starts=row.starts,
        )
        for index, row in enumerate(standings(store, season))
    ]


def close_year(
    store: Store,
    career: cr.Career,
    season: sn.Season,
    seed: int,
    replace_retired: bool = True,
    open_next: bool = True,
) -> dict[str, Any]:
    """Ein Jahr abschließen und das nächste eröffnen.

    Reihenfolge ist hier alles: Erst die Wertung einfrieren, dann altern
    lassen. Umgekehrt stünde in der Bestenliste das Feld des Folgejahres.
    """
    chapter = cr.SeasonChapter(
        year=season.year,
        season_id=season.id,
        season_name=season.name,
        standings=snapshot_standings(store, season),
    )

    report = close_season(store, season, seed=seed, replace_retired=replace_retired)
    _, pool = store.load_pool()
    by_id = {r.id: r for r in pool}
    retired_ids = {int(r["id"]) for r in report["retired"]}

    notes: list[cr.DevelopmentNote] = []
    for entry in report["log"]:
        rider = by_id.get(int(entry["rider_id"]))
        notes.append(
            cr.DevelopmentNote(
                rider_id=int(entry["rider_id"]),
                name=entry["name"],
                age=int(entry["age"]),
                potential=float(entry["potential_after"]),
                # Zurückgetretene stehen nicht mehr im Pool; ihre letzte
                # bekannte Leistung ist trotzdem Teil des Lebenslaufs.
                ftp_w=float(rider.ftp_w) if rider else 0.0,
                note=entry.get("note", ""),
                retired=int(entry["rider_id"]) in retired_ids,
            )
        )
    for newcomer in report["newcomers"]:
        rider = by_id.get(int(newcomer["id"]))
        notes.append(
            cr.DevelopmentNote(
                rider_id=int(newcomer["id"]),
                name=newcomer["name"],
                age=int(newcomer["age"]),
                potential=float(rider.potential) if rider else 0.0,
                ftp_w=float(rider.ftp_w) if rider else 0.0,
                note="Neu im Feld",
                newcomer=True,
            )
        )
    chapter.development = notes
    career.chapters = [c for c in career.chapters if c.year != chapter.year] + [chapter]
    career.chapters.sort(key=lambda c: c.year)

    next_season: sn.Season | None = None
    if open_next:
        year = season.year + 1
        next_season = sn.Season(
            id=season_id_for(career.id, year),
            name=season_name_for(career.name, year),
            year=year,
            races=next_calendar(season, year),
            points_head=list(season.points_head),
        )
        store.save_season(next_season)
        if next_season.id not in career.season_ids:
            career.season_ids.append(next_season.id)

    store.save_career(career)
    return {
        "career_id": career.id,
        "year": season.year,
        "champion": chapter.champion.to_dict() if chapter.champion else None,
        "retired": report["retired"],
        "newcomers": report["newcomers"],
        "next_season_id": next_season.id if next_season else None,
        "next_year": next_season.year if next_season else None,
        "n_races": len(next_season.races) if next_season else 0,
    }
