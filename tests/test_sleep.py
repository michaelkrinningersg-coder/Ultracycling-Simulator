"""Tests von Schlafdruck und Zirkadianik (M5 Schritt 3).

Der wichtigste Test hier prüft eine **Nicht**-Wirkung: 34 Stunden ohne
Schlaf sind im Ultracycling normal. Ein Modell, das dafür schon straft,
macht genau die Distanzklasse kaputt, um die es geht.
"""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core import sleep as slp
from ultrasim.core import strategy as st
from ultrasim.core.engine import RaceConfig, RiderStreams, simulate_race
from ultrasim.core.events import SLEEP
from ultrasim.core.rider import generate_pool


def _pressure(wake_h: float, hour: float, horizon: float = 40.0) -> float:
    base = slp.pressure(np.array([wake_h]), np.array([horizon]))[0]
    return float(base * slp.circadian_factor(hour))


def _perf(wake_h: float, hour: float, horizon: float = 40.0) -> float:
    return float(slp.performance_factor(np.array([_pressure(wake_h, hour, horizon)]))[0])


# ----------------------------------------------------------------------
# Die zentrale Kalibrierung
# ----------------------------------------------------------------------
def test_a_full_day_awake_costs_essentially_nothing():
    """Die erste Nacht durchfahren ist Standard, keine Ausnahme."""
    assert _perf(12.0, 20.0) == 1.0  # Abend des ersten Tages
    assert _perf(20.0, 3.5) > 0.97  # mitten in der ersten Nacht
    assert _perf(24.0, 8.0) > 0.98  # Morgen danach


def test_thirtyfour_hours_awake_is_still_a_minor_penalty():
    """Genau der Fall, an dem die erste Kalibrierung falsch lag."""
    assert _perf(34.0, 18.0) > 0.95


def test_the_second_night_is_where_it_breaks():
    """Dramatik entsteht im zweiten Nachttief, nicht im ersten."""
    first_night = _perf(20.0, 3.5)
    second_night = _perf(40.0, 3.5)
    assert second_night < 0.80
    assert first_night - second_night > 0.15


def test_daylight_softens_the_same_sleep_debt():
    """Der zirkadiane Faktor ist der halbe Effekt."""
    assert _perf(40.0, 12.0) > _perf(40.0, 3.5) + 0.15


def test_penalty_is_exactly_zero_below_the_deadband():
    for wake in (0.0, 5.0, 10.0, 15.0):
        assert _perf(wake, 12.0) == 1.0


def test_penalty_is_monotonic_and_floored():
    values = [_perf(w, 3.5) for w in range(0, 80, 4)]
    assert all(a >= b - 1e-12 for a, b in zip(values, values[1:], strict=False))
    assert min(values) >= slp.SLEEP_FLOOR


def test_sleep_tolerance_buys_hours():
    tolerant = _perf(36.0, 3.5, horizon=float(slp.wake_horizon_h(np.array([95.0]))[0]))
    fragile = _perf(36.0, 3.5, horizon=float(slp.wake_horizon_h(np.array([5.0]))[0]))
    assert tolerant > fragile + 0.10


# ----------------------------------------------------------------------
# Zirkadianik
# ----------------------------------------------------------------------
def test_circadian_low_sits_between_two_and_five():
    values = {h: slp.circadian_factor(h) for h in range(24)}
    worst = max(values, key=values.get)
    assert 2 <= worst <= 5
    assert values[worst] == pytest.approx(1.0 + slp.CIRCADIAN_AMPLITUDE, abs=0.05)


def test_circadian_is_flat_during_the_day():
    for hour in (10, 12, 14, 16, 18):
        assert slp.circadian_factor(hour) == pytest.approx(1.0, abs=0.01)


def test_circadian_wraps_around_midnight():
    """Ohne zyklische Rechnung reißt die Glocke um Mitternacht auf."""
    assert slp.circadian_factor(23.5) > 1.01
    assert slp.circadian_factor(0.5) > slp.circadian_factor(23.5)


def test_own_hour_starts_at_the_configured_time():
    """Jeder Fahrer startet in seinem persönlichen 08:00 (Entscheidung 13)."""
    assert slp.own_hour(8 * 3600, 0.0) == pytest.approx(8.0)
    assert slp.own_hour(8 * 3600, 20 * 3600) == pytest.approx(4.0)
    assert slp.own_hour(8 * 3600, 48 * 3600) == pytest.approx(8.0)


def test_descent_penalty_tracks_the_same_deadband():
    assert slp.descent_factor(np.array([0.5]))[0] == 1.0
    tired = slp.descent_factor(np.array([1.5]))[0]
    assert 0.72 <= tired < 1.0


# ----------------------------------------------------------------------
# Schlafqualität
# ----------------------------------------------------------------------
def test_sleep_quality_follows_regeneration():
    good = np.mean([slp.sleep_quality(95.0, np.random.default_rng(i)) for i in range(300)])
    poor = np.mean([slp.sleep_quality(5.0, np.random.default_rng(i)) for i in range(300)])
    assert good > poor
    assert 0.3 <= poor <= 1.0 and 0.3 <= good <= 1.0


def test_sleep_is_never_as_good_as_a_bed_at_home():
    values = [slp.sleep_quality(100.0, np.random.default_rng(i)) for i in range(200)]
    assert np.mean(values) < 1.0


# ----------------------------------------------------------------------
# Schlafplanung
# ----------------------------------------------------------------------
def test_no_sleep_is_planned_for_a_short_race(route_medium):
    rng = np.random.default_rng(0)
    times = [1800.0] * len(route_medium.service_points)  # halbe Stunde je Abschnitt
    stops = st.plan_service_stops(route_medium, times, rng, wake_horizon_h=40.0)
    assert all(s.kind != "schlaf" for s in stops)


def test_sleep_is_planned_once_the_horizon_is_reached(route_medium):
    rng = np.random.default_rng(0)
    # Sechs Stunden je Abschnitt: Der Trigger bei 0,72 × 40 h ist nach
    # fünf Abschnitten überschritten, und danach bleibt noch reichlich.
    n = max(len(route_medium.service_points), 1)
    times = [6 * 3600.0] * n
    stops = st.plan_service_stops(route_medium, times, rng, wake_horizon_h=40.0)
    if n * 6 < 29:
        pytest.skip("Testroute zu kurz für einen Schlafstopp")
    assert any(s.kind == "schlaf" for s in stops)


def test_no_long_sleep_shortly_before_the_finish(route_medium):
    """Ein Vier-Stunden-Block sieben Stunden vor dem Ziel wäre Unsinn."""
    rng = np.random.default_rng(0)
    n = max(len(route_medium.service_points), 1)
    times = [6 * 3600.0] * n
    stops = st.plan_service_stops(route_medium, times, rng, wake_horizon_h=40.0)
    for idx, stop in enumerate(stops):
        if stop.kind != "schlaf":
            continue
        remaining_h = sum(times[idx + 1 :]) / 3600.0
        assert remaining_h > st.SLEEP_SKIP_REMAINING_H
        if remaining_h < st.SLEEP_LONG_MIN_REMAINING_H:
            assert stop.planned_s <= st.SLEEP_SHORT_S[1]


def test_short_sleepers_choose_naps(route_medium):
    rng = np.random.default_rng(0)
    n = max(len(route_medium.service_points), 1)
    times = [10 * 3600.0] * n
    naps = st.plan_service_stops(
        route_medium, times, rng, wake_horizon_h=40.0, prefers_short_sleep=True
    )
    for stop in naps:
        if stop.kind == "schlaf":
            assert stop.planned_s <= st.SLEEP_SHORT_S[1]


# ----------------------------------------------------------------------
# Im Rennen
# ----------------------------------------------------------------------
def test_sleep_pressure_is_tracked(route):
    teams, riders = generate_pool(12, n_teams=3, seed=7)
    result = simulate_race(route, riders, teams, RaceConfig(seed=3))
    tel = result.telemetry
    assert tel.sleep_pct.dtype == np.uint8
    # Auf einer kurzen Strecke bleibt der Druck weit unter der Totzone.
    assert tel.sleep_pct.max() < slp.PRESSURE_DEADBAND * 100


def test_a_short_race_is_unaffected_by_sleep(route):
    """Die Mechanik darf eine Kurzdistanz nicht stillschweigend bremsen."""
    teams, riders = generate_pool(12, n_teams=3, seed=7)
    result = simulate_race(route, riders, teams, RaceConfig(seed=3))
    assert not [e for e in result.events if e.type == SLEEP]


def test_sleep_events_carry_quality_and_recovery(route_medium):
    teams, riders = generate_pool(16, n_teams=4, seed=7)
    # Startzeit so legen, dass die Fahrer in die Nacht hineinfahren.
    result = simulate_race(
        route_medium, riders, teams, RaceConfig(seed=3, start_time_of_day_s=18 * 3600)
    )
    for event in result.events:
        if event.type != SLEEP:
            continue
        assert 0.3 <= event.payload["quality"] <= 1.0
        assert event.payload["duration_s"] > 0
        assert event.payload["wake_h_after"] >= 0.0


def test_streams_include_a_sleep_channel():
    assert "sleep" in RiderStreams.NAMES
    a = RiderStreams(1, 1)
    assert a.get("sleep").random() != a.get("stops").random()
