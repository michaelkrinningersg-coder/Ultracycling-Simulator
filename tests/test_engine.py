"""Tests der Rennsimulation (M3) samt Determinismus-Zusicherung."""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core.engine import (
    STATE_FINISHED,
    RaceConfig,
    Telemetry,
    build_start_list,
    simulate_race,
)
from ultrasim.core.events import FINISH, SPLIT_PASSED, START
from ultrasim.core.rider import generate_pool


@pytest.fixture(scope="module")
def race(route):
    teams, riders = generate_pool(20, n_teams=4, seed=5)
    return simulate_race(route, riders, teams, RaceConfig(seed=123)), teams, riders


# ----------------------------------------------------------------------
# Determinismus – laut Dokument unverzichtbar
# ----------------------------------------------------------------------
def test_same_seed_gives_identical_results(route):
    """Gleicher Seed = gleiches Ergebnis. Ohne das ist Balancing unmöglich."""
    teams, riders = generate_pool(12, n_teams=3, seed=2)
    a = simulate_race(route, riders, teams, RaceConfig(seed=99))
    b = simulate_race(route, riders, teams, RaceConfig(seed=99))
    assert [e.finish_time_s for e in a.entries] == [e.finish_time_s for e in b.entries]
    assert np.array_equal(a.split_times_s, b.split_times_s, equal_nan=True)
    assert np.array_equal(a.telemetry.dist_m, b.telemetry.dist_m)


def test_different_seed_gives_different_results(route):
    teams, riders = generate_pool(12, n_teams=3, seed=2)
    a = simulate_race(route, riders, teams, RaceConfig(seed=1))
    b = simulate_race(route, riders, teams, RaceConfig(seed=2))
    assert [e.finish_time_s for e in a.entries] != [e.finish_time_s for e in b.entries]


def test_a_riders_race_does_not_depend_on_the_rest_of_the_field(route):
    """Der Zufallsstrom hängt an Seed und Fahrer-ID, nicht an der Startliste.

    Sonst würde sich das Rennen eines Fahrers ändern, nur weil jemand
    anderes gemeldet hat – und kein Golden-Master-Test wäre haltbar.
    """
    teams, riders = generate_pool(20, n_teams=4, seed=3)
    small = simulate_race(route, riders[:8], teams, RaceConfig(seed=42))
    large = simulate_race(route, riders, teams, RaceConfig(seed=42))

    for entry in small.entries:
        twin = large.entry_by_rider(entry.rider_id)
        assert twin is not None
        assert entry.day_form == pytest.approx(twin.day_form)
        assert entry.target_if == pytest.approx(twin.target_if)
        assert entry.finish_time_s == pytest.approx(twin.finish_time_s, abs=1e-6)


# ----------------------------------------------------------------------
# Ergebnis-Plausibilität
# ----------------------------------------------------------------------
def test_everyone_finishes_a_short_race(race):
    result, _, _ = race
    assert all(e.status in ("FIN", "OTL") for e in result.entries)
    assert all(e.finish_time_s is not None for e in result.entries)


def test_average_speed_is_in_a_believable_band(race, route):
    result, _, _ = race
    for entry in result.entries:
        kmh = route.distance_km / (entry.finish_time_s / 3600.0)
        assert 18.0 < kmh < 48.0


def test_ranks_are_dense_and_ordered(race):
    result, _, _ = race
    ranked = sorted((e for e in result.entries if e.rank), key=lambda e: e.rank)
    assert [e.rank for e in ranked] == list(range(1, len(ranked) + 1))
    times = [e.finish_time_s for e in ranked]
    assert times == sorted(times)


def test_split_times_are_monotonic_per_rider(race):
    result, _, _ = race
    for row in result.split_times_s:
        valid = row[np.isfinite(row)]
        assert np.all(np.diff(valid) > 0)


def test_split_times_are_complete_for_finishers(race):
    result, _, _ = race
    for entry in result.entries:
        if entry.finish_time_s is None:
            continue
        row = result.split_times_s[entry.entry_id]
        assert np.isfinite(row).all()
        assert row[-1] == pytest.approx(entry.finish_time_s, abs=1.5)


def test_split_ranks_are_a_permutation(race):
    result, _, _ = race
    n = len(result.entries)
    for s in range(result.split_ranks.shape[1]):
        column = result.split_ranks[:, s]
        assert sorted(column.tolist()) == list(range(1, n + 1))


def test_stronger_potential_wins_on_average(route):
    """Attribute müssen sich durchsetzen – sonst ist es ein Zufallsgenerator."""
    teams, riders = generate_pool(40, n_teams=5, seed=8)
    result = simulate_race(route, riders, teams, RaceConfig(seed=4))
    by_id = {r.id: r for r in riders}
    ranked = sorted((e for e in result.entries if e.rank), key=lambda e: e.rank)
    top = np.mean([by_id[e.rider_id].potential for e in ranked[:10]])
    bottom = np.mean([by_id[e.rider_id].potential for e in ranked[-10:]])
    assert top > bottom


# ----------------------------------------------------------------------
# Startaufstellung
# ----------------------------------------------------------------------
def test_seeded_start_order_puts_the_favourite_last(route):
    _, riders = generate_pool(20, n_teams=4, seed=6)
    order = build_start_list(riders, RaceConfig(start_order="seeded"), 300, np.random.default_rng(0))
    potentials = [rider.potential for rider, _, _ in order]
    assert potentials == sorted(potentials)
    assert order[0][2] == 0.0
    assert order[-1][2] == 300 * (len(order) - 1)


def test_start_interval_defaults_follow_distance_class(route):
    config = RaceConfig()
    assert config.resolved_start_interval("kurz") == 300
    assert config.resolved_start_interval("mittel") == 900
    assert config.resolved_start_interval("ultra") == 1800


def test_sample_rate_follows_distance_class():
    config = RaceConfig()
    assert config.resolved_sample_dt("kurz") == 5
    assert config.resolved_sample_dt("mittel") == 15
    assert config.resolved_sample_dt("ultra") == 30


# ----------------------------------------------------------------------
# Telemetrie
# ----------------------------------------------------------------------
def test_telemetry_distance_is_monotonic_and_quantised(race):
    result, _, _ = race
    tel = result.telemetry
    assert tel.dist_m.dtype == np.int32
    assert tel.v_cms.dtype == np.int16
    assert tel.state.dtype == np.uint8
    assert np.all(np.diff(tel.dist_m, axis=1) >= 0)


def test_telemetry_ends_in_the_finished_state(race):
    result, _, _ = race
    assert (result.telemetry.state[:, -1] == STATE_FINISHED).all()


def test_telemetry_roundtrip(race, tmp_path):
    result, _, _ = race
    path = tmp_path / "t.npz"
    result.telemetry.save(path)
    again = Telemetry.load(path)
    assert again.sample_dt_s == result.telemetry.sample_dt_s
    assert np.array_equal(again.dist_m, result.telemetry.dist_m)
    assert np.array_equal(again.state, result.telemetry.state)


def test_telemetry_stays_within_the_memory_budget(race):
    """Rund 45 MB je Ultra-Rennen mit 250 Fahrern (Abschnitt 12)."""
    result, _, _ = race
    per_rider_per_sample = result.telemetry.nbytes() / (
        result.telemetry.n_entries * result.telemetry.n_samples
    )
    # 7 Kanäle: int32 + int16 + int16 + 4x uint8 = 12 Byte
    assert per_rider_per_sample <= 12.0


# ----------------------------------------------------------------------
# Ereignisse
# ----------------------------------------------------------------------
def test_every_rider_gets_start_and_finish_events(race):
    result, _, _ = race
    for entry in result.entries:
        types = {e.type for e in result.events_for(entry.entry_id)}
        assert START in types
        assert FINISH in types


def test_events_are_sorted_by_own_time(race):
    result, _, _ = race
    times = [e.t_s for e in result.events]
    assert times == sorted(times)


def test_split_events_match_the_split_table(race, route):
    result, _, _ = race
    for entry in result.entries:
        events = [e for e in result.events_for(entry.entry_id) if e.type == SPLIT_PASSED]
        assert len(events) == len(route.splits)
        for event in events:
            recorded = result.split_times_s[entry.entry_id, event.payload["split_idx"]]
            assert event.t_s == pytest.approx(recorded)


def test_time_limit_marks_slow_riders(route):
    """Zeitlimit als Vielfaches der Siegerzeit (Abschnitt 15)."""
    teams, riders = generate_pool(16, n_teams=3, seed=12)
    result = simulate_race(route, riders, teams, RaceConfig(seed=1, time_limit_factor=1.0001))
    assert sum(1 for e in result.entries if e.status == "OTL") > 0
    assert sum(1 for e in result.entries if e.rank == 1) == 1
