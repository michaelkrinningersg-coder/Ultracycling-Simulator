"""Karriere über mehrere Jahre.

Der Kern dieses Modus ist eine Reihenfolge: **Erst die Wertung
einfrieren, dann altern lassen.** Umgekehrt stünde in der ewigen
Bestenliste das Feld des Folgejahres — mit den Punkten des Vorjahres,
aber ohne die Zurückgetretenen und mit einem Nachwuchs, der noch kein
Rennen gefahren ist. Der Fehler wäre still: Die Tabelle sähe plausibel
aus und wäre falsch.
"""

from __future__ import annotations

from datetime import date

import pytest

from ultrasim import career_runner as runner
from ultrasim.core import career as cr
from ultrasim.core import season as sn
from ultrasim.core.rider import generate_pool
from ultrasim.data.store import Store


@pytest.fixture
def store(tmp_path, route):
    store = Store(tmp_path)
    store.routes_dir.mkdir(parents=True, exist_ok=True)
    route.save(store.routes_dir / "teststrecke.json.gz")
    teams, riders = generate_pool(10, n_teams=2, seed=5)
    store.save_pool(teams, riders)
    return store


def _career(store, years: int = 1) -> tuple[cr.Career, sn.Season]:
    return runner.create_career(store, "Weltserie", 2030, n_races=2)


# ----------------------------------------------------------------------
# Anlegen
# ----------------------------------------------------------------------
def test_a_new_career_starts_with_one_season(store):
    career, season = _career(store)
    assert career.id == "weltserie"
    assert career.season_ids == [season.id]
    assert career.current_year == 2030
    assert career.years_closed == 0
    assert season.year == 2030
    assert season.races, "Der erste Kalender wird vorgeschlagen"
    assert store.load_career(career.id).name == "Weltserie"


def test_the_calendar_carries_over_to_the_next_year(store):
    _, season = _career(store)
    nxt = runner.next_calendar(season, 2031)
    assert [r.id for r in nxt] == [r.id for r in season.sorted_races()]
    assert [r.day.month for r in nxt] == [r.day.month for r in season.sorted_races()]
    assert all(r.day.year == 2031 for r in nxt)
    assert all(r.race_id is None for r in nxt), "Ein neues Jahr ist ungerechnet"
    # Gleicher Kalender, anderes Wetter: sonst wäre die Karriere eine
    # Wiederholung desselben Jahres.
    assert all(
        new.seed != old.seed for new, old in zip(nxt, season.sorted_races(), strict=True)
    )


def test_the_29th_of_february_survives_a_normal_year():
    assert runner._same_day_next_year(date(2032, 2, 29), 2033) == date(2033, 3, 1)
    assert runner._same_day_next_year(date(2032, 2, 28), 2033) == date(2033, 2, 28)


# ----------------------------------------------------------------------
# Jahreswechsel
# ----------------------------------------------------------------------
def test_closing_a_year_ages_the_field_and_opens_the_next(store):
    career, season = _career(store)
    _, before = store.load_pool()
    ages_before = {r.id: r.age for r in before}

    report = runner.close_year(store, career, season, seed=7)

    _, after = store.load_pool()
    survivors = [r for r in after if r.id in ages_before]
    assert survivors, "Es kann nicht das ganze Feld zurücktreten"
    assert all(r.age == ages_before[r.id] + 1 for r in survivors)

    assert report["next_year"] == 2031
    assert career.current_year == 2031
    assert career.years_closed == 1
    assert store.load_season(report["next_season_id"]).year == 2031


def test_the_standings_are_frozen_before_the_field_changes(store):
    """Die eigentliche Zusicherung dieses Moduls.

    Zurückgetretene Fahrer müssen in der Wertung ihres letzten Jahres
    stehen bleiben — sie haben sie ja gefahren.
    """
    career, season = _career(store)
    runner.close_year(store, career, season, seed=7)
    chapter = career.chapters[0]

    _, after = store.load_pool()
    still_there = {r.id for r in after}
    retired = [d.rider_id for d in chapter.development if d.retired]
    for rider_id in retired:
        assert rider_id not in still_there
    # Und der Nachwuchs, der noch kein Rennen gefahren hat, taucht in der
    # Wertung des abgeschlossenen Jahres *nicht* auf.
    newcomers = {d.rider_id for d in chapter.development if d.newcomer}
    assert not newcomers & {s.rider_id for s in chapter.standings}


def test_a_closed_year_records_every_rider_of_the_field(store):
    career, season = _career(store)
    _, before = store.load_pool()
    runner.close_year(store, career, season, seed=7)
    chapter = career.chapters[0]
    logged = {d.rider_id for d in chapter.development if not d.newcomer}
    assert logged == {r.id for r in before}


def test_closing_twice_does_not_duplicate_the_year(store):
    career, season = _career(store)
    runner.close_year(store, career, season, seed=7)
    runner.close_year(store, career, season, seed=7)
    years = [c.year for c in career.chapters]
    assert years == sorted(set(years))


# ----------------------------------------------------------------------
# Auswertung über die Jahre
# ----------------------------------------------------------------------
def _chapter(year: int, order: list[tuple[int, str]], **kw) -> cr.SeasonChapter:
    return cr.SeasonChapter(
        year=year,
        season_id=f"s{year}",
        season_name=str(year),
        standings=[
            cr.StandingSnapshot(
                rank=i + 1,
                rider_id=rid,
                name=name,
                team_name="T",
                points=100 - 10 * i,
                wins=1 if i == 0 else 0,
                podiums=1 if i < 3 else 0,
                starts=8,
            )
            for i, (rid, name) in enumerate(order)
        ],
        development=kw.get("development", []),
    )


def test_the_hall_of_fame_ranks_titles_before_points():
    """Zwei Titel schlagen zehn Jahre Mittelfeld."""
    career = cr.Career(
        id="c",
        name="C",
        first_year=2030,
        chapters=[
            # Zwei Jahre gewinnt der Champion, danach ist er weg.
            _chapter(2030, [(1, "Champion"), (2, "Dauerläufer")]),
            _chapter(2031, [(1, "Champion"), (2, "Dauerläufer")]),
            # Der Dauerläufer fährt weiter — immer Zweiter hinter wechselnden
            # Namen, und sammelt dabei mehr Punkte als der Champion je hatte.
            _chapter(2032, [(3, "Neuer"), (2, "Dauerläufer")]),
            _chapter(2033, [(4, "Noch einer"), (2, "Dauerläufer")]),
            _chapter(2034, [(5, "Und noch einer"), (2, "Dauerläufer")]),
        ],
    )
    table = cr.hall_of_fame(career)
    champion = next(row for row in table if row.name == "Champion")
    steady = next(row for row in table if row.name == "Dauerläufer")

    assert table[0] is champion, "Titel stehen vor Punkten"
    assert steady.points > champion.points
    assert champion.titles == 2 and steady.titles == 0
    assert champion.seasons == 2 and steady.seasons == 5
    assert champion.first_year == 2030 and champion.last_year == 2031
    assert steady.best_rank == 2


def test_the_hall_of_fame_marks_a_retirement():
    career = cr.Career(
        id="c",
        name="C",
        first_year=2030,
        chapters=[
            _chapter(
                2030,
                [(1, "Alt")],
                development=[
                    cr.DevelopmentNote(1, "Alt", 38, 44.0, 300.0, "Rücktritt", retired=True)
                ],
            )
        ],
    )
    assert cr.hall_of_fame(career)[0].retired_year == 2030


def test_a_rider_history_reads_year_by_year():
    career = cr.Career(
        id="c",
        name="C",
        first_year=2030,
        chapters=[
            _chapter(2030, [(1, "A"), (2, "B")]),
            _chapter(2031, [(2, "B"), (1, "A")]),
        ],
    )
    history = cr.rider_history(career, 1)
    assert [y.year for y in history] == [2030, 2031]
    assert [y.rank for y in history] == [1, 2]
    assert cr.rider_history(career, 999) == []


def test_a_career_survives_the_round_trip(store):
    career, _ = _career(store)
    career.chapters.append(_chapter(2030, [(1, "A")]))
    store.save_career(career)
    again = store.load_career(career.id)
    assert again.to_dict() == career.to_dict()
    assert again.chapter(2030).champion.name == "A"


def test_the_career_of_a_season_can_be_found(store):
    career, season = _career(store)
    assert runner.career_of_season(store, season.id).id == career.id
    assert runner.career_of_season(store, "gibt-es-nicht") is None
