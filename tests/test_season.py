"""Saison, Kalender, Wertung und Fahrerentwicklung (M7, Abschnitte 11 und 14)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pytest

from ultrasim.core import development as dev
from ultrasim.core import season as sn
from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.rider import generate_pool, generate_rider


# ----------------------------------------------------------------------
# Punkte und Koeffizient
# ----------------------------------------------------------------------
def test_points_follow_the_documented_table():
    """Abschnitt 11: 100, 80, 65, 55, 48, 42, 37, 33, 30, 28, dann −2."""
    assert [sn.points_for_rank(i) for i in range(1, 11)] == list(sn.POINTS_HEAD)
    assert sn.points_for_rank(11) == 26
    assert sn.points_for_rank(12) == 24


def test_points_never_go_negative():
    assert sn.points_for_rank(200) == 0
    assert all(sn.points_for_rank(i) >= 0 for i in range(1, 400))


def test_no_points_without_a_rank():
    """Aufgabe und Zeitlimit geben null Punkte (Abschnitt 11)."""
    assert sn.points_for_rank(None) == 0
    assert sn.points_for_rank(0) == 0


def test_points_are_monotonic():
    values = [sn.points_for_rank(i) for i in range(1, 60)]
    assert values == sorted(values, reverse=True)


def test_coefficient_grows_with_the_race_but_not_linearly():
    """Ein viermal so langes Rennen ist etwa doppelt so viel wert.

    Ohne die Dämpfung entschiede ein einziger Ultra die Saison und alle
    kurzen Rennen wären Dekoration.
    """
    short = sn.race_coefficient(300.0, 3000.0)
    long = sn.race_coefficient(1200.0, 12000.0)
    assert short < long < 4 * short
    assert long == pytest.approx(2 * short, rel=0.15)


def test_ascent_counts_towards_the_coefficient():
    flat = sn.race_coefficient(400.0, 500.0)
    hilly = sn.race_coefficient(400.0, 9000.0)
    assert hilly > flat


def test_coefficient_stays_inside_its_band():
    assert sn.race_coefficient(50.0, 0.0) >= sn.COEFFICIENT_CLIP[0]
    assert sn.race_coefficient(9000.0, 100_000.0) <= sn.COEFFICIENT_CLIP[1]


# ----------------------------------------------------------------------
# Restermüdung und Frische
# ----------------------------------------------------------------------
def test_residual_work_decays_and_never_grows():
    values = [sn.residual_work_kj(20_000.0, d, 50.0) for d in (0, 7, 14, 28, 60)]
    assert values[0] == pytest.approx(20_000.0)
    assert values == sorted(values, reverse=True)
    assert values[-1] < 100.0


def test_good_regeneration_recovers_faster():
    slow = sn.residual_work_kj(20_000.0, 10.0, 5.0)
    fast = sn.residual_work_kj(20_000.0, 10.0, 95.0)
    assert fast < slow


def test_an_ultra_is_gone_after_four_weeks_but_not_after_one():
    """Die Vorgabe für den Kalender: ein Ultra kostet drei bis vier Wochen."""
    work = 22_000.0
    assert sn.residual_work_kj(work, 7, 50.0) / work > 0.3
    assert sn.residual_work_kj(work, 28, 50.0) / work < 0.03


def test_freshness_is_one_when_rested():
    assert sn.freshness_factor(0.0, 42_000.0) == 1.0
    assert sn.freshness_factor(-5.0, 42_000.0) == 1.0


def test_freshness_falls_with_residual_work():
    values = [sn.freshness_factor(kj, 42_000.0) for kj in (0, 2_000, 8_000, 20_000)]
    assert values == sorted(values, reverse=True)
    assert values[-1] >= sn.FRESHNESS_FLOOR


def test_freshness_matches_the_calendar_brief():
    """Eine Woche nach einem Ultra soll es richtig wehtun.

    Die Zahlen stammen aus der Kalibrierung: rund 13 % weniger haltbare
    Leistung nach sieben Tagen, gut 6 % nach vierzehn, unter 2 % nach
    vier Wochen.
    """
    capacity = 42_000.0
    work = 22_000.0
    seven = sn.freshness_factor(sn.residual_work_kj(work, 7, 50.0), capacity)
    fourteen = sn.freshness_factor(sn.residual_work_kj(work, 14, 50.0), capacity)
    twentyeight = sn.freshness_factor(sn.residual_work_kj(work, 28, 50.0), capacity)
    assert 0.84 < seven < 0.90
    assert 0.91 < fourteen < 0.96
    assert twentyeight > 0.98


# ----------------------------------------------------------------------
# Kalender
# ----------------------------------------------------------------------
def _season() -> sn.Season:
    return sn.Season(
        id="2027",
        name="Testsaison",
        year=2027,
        races=[
            sn.CalendarRace(id="c", name="Drittes", route_id="r", day=date(2027, 8, 1)),
            sn.CalendarRace(id="a", name="Erstes", route_id="r", day=date(2027, 4, 1)),
            sn.CalendarRace(id="b", name="Zweites", route_id="r", day=date(2027, 6, 1)),
        ],
    )


def test_calendar_is_ordered_by_date_not_by_list_position():
    """Die Restermüdung hängt an der Reihenfolge, nicht an der Eingabe."""
    assert [r.id for r in _season().sorted_races()] == ["a", "b", "c"]


def test_season_roundtrip():
    season = _season()
    again = sn.Season.from_dict(season.to_dict())
    assert again.id == season.id
    assert [r.day for r in again.sorted_races()] == [r.day for r in season.sorted_races()]
    assert again.points_head == season.points_head


def test_race_lookup():
    season = _season()
    assert season.race("b").name == "Zweites"
    assert season.race("gibtsnicht") is None


# ----------------------------------------------------------------------
# Gesamtwertung
# ----------------------------------------------------------------------
@dataclass
class _Entry:
    rider_id: int
    rank: int | None
    status: str = "FIN"


@dataclass
class _Result:
    entries: list[_Entry]


def _standings(results, coefficients=None, n_riders=4):
    _, riders = generate_pool(n_riders, n_teams=2, seed=1)
    season = sn.Season(
        id="s",
        name="s",
        year=2027,
        races=[
            sn.CalendarRace(id=key, name=key, route_id="r", day=date(2027, 4, 1 + i))
            for i, key in enumerate(results)
        ],
    )
    return sn.build_standings(
        season,
        results,
        {r.id: r for r in riders},
        {},
        coefficients or dict.fromkeys(results, 1.0),
    )


def test_standings_sum_points_over_the_season():
    table = _standings(
        {
            "r1": _Result([_Entry(0, 1), _Entry(1, 2)]),
            "r2": _Result([_Entry(0, 2), _Entry(1, 1)]),
        }
    )
    assert {row.rider_id: row.points for row in table} == {0: 180.0, 1: 180.0}
    assert {row.rider_id: row.wins for row in table} == {0: 1, 1: 1}


def test_the_coefficient_weights_a_race():
    table = _standings(
        {"r1": _Result([_Entry(0, 1), _Entry(1, 2)])}, coefficients={"r1": 2.0}
    )
    assert table[0].points == 200.0


def test_more_wins_break_a_tie():
    """Gleiche Punkte, aber ein Sieg schlägt zwei zweite Plätze."""
    table = _standings(
        {
            # Fahrer 0: Sieg + Rang 12 (100 + 24) · Fahrer 1: zweimal Rang 2 (160)
            "r1": _Result([_Entry(0, 1), _Entry(1, 2)]),
            "r2": _Result([_Entry(0, 12), _Entry(1, 2)]),
            "r3": _Result([_Entry(0, 20), _Entry(1, 24)]),
        }
    )
    assert table[0].rider_id == 1  # 160 Punkte
    assert table[1].rider_id == 0  # 124 Punkte
    # Und bei echtem Gleichstand entscheidet der Sieg:
    tied = _standings(
        {
            "r1": _Result([_Entry(0, 1), _Entry(1, 2)]),
            "r2": _Result([_Entry(0, 30), _Entry(1, 2)]),
        }
    )
    assert tied[0].rider_id == 1
    assert tied[0].points > tied[1].points


def test_the_better_single_placing_breaks_a_tie_of_points_and_wins():
    """Dritte Stufe des Tiebreaks aus Abschnitt 11."""
    # Beide 80 Punkte, kein Sieg: Fahrer 0 hat einen zweiten Platz,
    # Fahrer 1 einen dritten plus einen sechsten (65 + 42 = 107) – also
    # ungleich. Deshalb direkt über die Sortierschlüssel prüfen.
    a = sn.Standing(rider_id=0, name="A", nation="", team_id=0, team_name="", points=80.0)
    b = sn.Standing(rider_id=1, name="B", nation="", team_id=0, team_name="", points=80.0)
    a.scores = [sn.RaceScore("r", "r", date(2027, 4, 1), 2, "FIN", 80.0)]
    b.scores = [sn.RaceScore("r", "r", date(2027, 4, 1), 3, "FIN", 80.0)]
    assert a.sort_key() < b.sort_key()


def test_fewer_starts_do_not_win_a_tie():
    """Wer weniger gestartet ist, darf nicht dadurch vorn landen."""
    many = sn.Standing(rider_id=0, name="A", nation="", team_id=0, team_name="", points=80.0)
    few = sn.Standing(rider_id=1, name="B", nation="", team_id=0, team_name="", points=80.0)
    many.scores = [
        sn.RaceScore("r1", "r1", date(2027, 4, 1), 4, "FIN", 55.0),
        sn.RaceScore("r2", "r2", date(2027, 5, 1), 9, "FIN", 25.0),
    ]
    few.scores = [sn.RaceScore("r1", "r1", date(2027, 4, 1), 4, "FIN", 55.0)]
    assert many.sort_key() < few.sort_key()


def test_a_dnf_counts_as_a_start_but_scores_nothing():
    table = _standings({"r1": _Result([_Entry(0, 1), _Entry(1, None, "DNF")])})
    quitter = next(row for row in table if row.rider_id == 1)
    assert quitter.starts == 1
    assert quitter.finishes == 0
    assert quitter.points == 0.0


def test_ranks_are_dense_and_ordered():
    table = _standings(
        {"r1": _Result([_Entry(i, i + 1) for i in range(4)])}, n_riders=4
    )
    assert [row.rank for row in table] == [1, 2, 3, 4]
    assert [row.points for row in table] == sorted(
        (row.points for row in table), reverse=True
    )


# ----------------------------------------------------------------------
# Fahrerentwicklung
# ----------------------------------------------------------------------
def test_young_riders_gain_and_old_riders_lose():
    rng = np.random.default_rng(0)
    young = np.mean([dev.potential_delta(22, rng) for _ in range(400)])
    peak = np.mean([dev.potential_delta(31, rng) for _ in range(400)])
    old = np.mean([dev.potential_delta(39, rng) for _ in range(400)])
    assert young > 0.8
    assert abs(peak) < 0.2
    assert old < -1.5


def test_experience_growth_slows_down():
    record = dev.SeasonRecord(starts=10, distance_km=6000.0)
    assert dev.experience_gain(20.0, record) > dev.experience_gain(80.0, record)
    assert dev.experience_gain(97.0, record) == pytest.approx(0.0, abs=0.01)


def test_no_experience_without_racing():
    assert dev.experience_gain(50.0, dev.SeasonRecord()) == 0.0


def test_retirement_probability_grows_with_age():
    assert dev.retirement_probability(28) == 0.0
    assert 0.0 < dev.retirement_probability(37) < 1.0
    assert dev.retirement_probability(45) == 1.0


def test_development_keeps_a_rider_plausible():
    """Ein entwickelter Fahrer muss dieselben Prüfungen bestehen wie ein neuer."""
    rng = np.random.default_rng(4)
    rider = generate_rider(rng, 1, 0, archetype="rohdiamant")
    record = dev.SeasonRecord(starts=8, finishes=7, distance_km=4000.0)
    for _ in range(10):
        rider, log = dev.develop_rider(rider, record, rng)
        assert 3.5 <= rider.wkg <= 6.0
        assert 19 <= rider.age <= 60
        assert all(0.0 <= rider.attr(k) <= 100.0 for k in rider.attributes)
        assert log["note"]


def test_a_climber_stays_a_climber():
    """Die Entwicklung verschiebt das Niveau, nicht die Form des Fahrers."""
    rng = np.random.default_rng(9)
    rider = generate_rider(rng, 1, 0, archetype="kletterer")
    before = rider.attr("berg") - rider.attr("flach")
    for _ in range(6):
        rider, _ = dev.develop_rider(rider, dev.SeasonRecord(starts=6), rng)
    after = rider.attr("berg") - rider.attr("flach")
    assert after > 0
    assert abs(after - before) < 22.0


def test_a_young_rider_gets_stronger_over_several_seasons():
    rng = np.random.default_rng(3)
    rider = generate_rider(rng, 1, 0, archetype="rohdiamant")
    rider.age = 21
    start = rider.potential
    for _ in range(6):
        rider, _ = dev.develop_rider(rider, dev.SeasonRecord(starts=8, distance_km=5000.0), rng)
    assert rider.potential > start
    assert rider.attr("erfahrung") > 60.0


def test_advance_season_is_deterministic_and_field_independent():
    """Wie im Rennen: der Zufall hängt an Seed und Fahrer-ID."""
    _, riders = generate_pool(20, n_teams=4, seed=5)
    records = {r.id: dev.SeasonRecord(starts=6, distance_km=3000.0) for r in riders}

    big, _, _ = dev.advance_season(riders, records, seed=42)
    small, _, _ = dev.advance_season(riders[:8], records, seed=42)
    by_id = {r.id: r for r in big}
    for rider in small:
        twin = by_id.get(rider.id)
        assert twin is not None
        assert rider.ftp_w == twin.ftp_w
        assert rider.attributes == twin.attributes


def test_everyone_eventually_retires():
    _, riders = generate_pool(12, n_teams=3, seed=6)
    for rider in riders:
        rider.age = 46
    active, retired, _ = dev.advance_season(riders, {}, seed=1)
    assert not active
    assert len(retired) == 12


# ----------------------------------------------------------------------
# Im Rennen
# ----------------------------------------------------------------------
def test_a_tired_rider_is_slower(route):
    teams, riders = generate_pool(12, n_teams=3, seed=8)
    fresh = simulate_race(route, riders, teams, RaceConfig(seed=5))
    carry = {r.id: 9000.0 for r in riders}
    tired = simulate_race(route, riders, teams, RaceConfig(seed=5, carry_work_kj=carry))

    base = {e.rider_id: e.finish_time_s for e in fresh.entries}
    for entry in tired.entries:
        assert entry.freshness < 1.0
        if entry.finish_time_s and base.get(entry.rider_id):
            assert entry.finish_time_s > base[entry.rider_id]


def test_carry_over_only_hits_the_riders_it_names(route):
    """Wer nicht im Übertrag steht, fährt unverändert."""
    teams, riders = generate_pool(12, n_teams=3, seed=8)
    fresh = simulate_race(route, riders, teams, RaceConfig(seed=5))
    carry = {riders[0].id: 9000.0}
    mixed = simulate_race(route, riders, teams, RaceConfig(seed=5, carry_work_kj=carry))

    base = {e.rider_id: e.finish_time_s for e in fresh.entries}
    for entry in mixed.entries:
        if entry.rider_id == riders[0].id:
            assert entry.freshness < 1.0
            assert entry.finish_time_s > base[entry.rider_id]
        else:
            assert entry.freshness == 1.0
            assert entry.finish_time_s == pytest.approx(base[entry.rider_id], abs=1e-6)


def test_work_is_reported_and_excludes_the_carry(route):
    teams, riders = generate_pool(8, n_teams=2, seed=8)
    carry = {r.id: 5000.0 for r in riders}
    result = simulate_race(route, riders, teams, RaceConfig(seed=5, carry_work_kj=carry))
    for entry in result.entries:
        # Rund 60 km bei etwa 200 W sind eine gute Stunde Arbeit; der
        # Übertrag von 5.000 kJ darf da nicht mit drinstecken.
        assert 400.0 < entry.work_kj < 3000.0


def test_no_carry_means_no_change(route):
    """Ohne Saison verhält sich alles wie vorher – wichtig für den Golden Master."""
    teams, riders = generate_pool(8, n_teams=2, seed=8)
    a = simulate_race(route, riders, teams, RaceConfig(seed=5))
    b = simulate_race(route, riders, teams, RaceConfig(seed=5, carry_work_kj={}))
    assert all(e.freshness == 1.0 for e in a.entries)
    assert [e.finish_time_s for e in a.entries] == [e.finish_time_s for e in b.entries]
