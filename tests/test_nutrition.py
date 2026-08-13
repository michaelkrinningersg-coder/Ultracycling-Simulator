"""Tests des Energiehaushalts und der Servicestopps (M5 Schritte 2 und 3)."""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core import nutrition as nut
from ultrasim.core import strategy as st
from ultrasim.core.engine import RaceConfig, RiderStreams, simulate_race
from ultrasim.core.events import BONK, STOP_END, STOP_START
from ultrasim.core.rider import Rider, generate_pool, generate_rider


# ----------------------------------------------------------------------
# Substrat und Speicher
# ----------------------------------------------------------------------
def test_metabolic_cost_matches_a_known_reference():
    """200 W über eine Stunde sind rund 700 kcal – der Wert vom Ergometer."""
    kcal = nut.metabolic_kcal(np.array([200.0 * 3.6]))  # 200 W -> kJ/h
    assert 680.0 < float(kcal[0]) < 760.0


def test_carb_fraction_hits_the_documented_anchors():
    """55 % -> 40 %, 75 % -> 65 %, 90 % -> 85 % (Abschnitt 6.1)."""
    zero = np.array([0.0])
    assert nut.carb_fraction(np.array([0.55]), zero)[0] == pytest.approx(0.40, abs=0.02)
    assert nut.carb_fraction(np.array([0.75]), zero)[0] == pytest.approx(0.65, abs=0.02)
    assert nut.carb_fraction(np.array([0.90]), zero)[0] == pytest.approx(0.85, abs=0.02)


def test_fat_burners_spare_carbohydrate():
    intensity = np.array([0.70])
    high = nut.carb_fraction(intensity, np.array([1.0]))[0]
    low = nut.carb_fraction(intensity, np.array([-1.0]))[0]
    assert high < low
    assert low - high == pytest.approx(0.20, abs=0.01)


def test_glycogen_capacity_is_in_the_documented_band():
    """1600–2200 kcal (Abschnitt 6.1)."""
    for ausdauer in (0.0, 50.0, 100.0):
        cap = nut.glycogen_capacity_kcal(np.array([72.0]), np.array([ausdauer]))[0]
        assert 1400.0 < cap < 2300.0
    weak = nut.glycogen_capacity_kcal(np.array([70.0]), np.array([10.0]))[0]
    strong = nut.glycogen_capacity_kcal(np.array([70.0]), np.array([90.0]))[0]
    assert strong > weak


def test_intake_ceiling_is_the_minimum_of_gut_and_oxidation():
    """Die Aufnahmefähigkeit bleibt die Grenze, nicht die Planung."""
    # Verwertung stark, Magen schwach -> der Magen entscheidet
    assert nut.intake_ceiling_g_h(np.array([100.0]), np.array([0.0]))[0] == pytest.approx(45.0)
    # umgekehrt ebenso
    assert nut.intake_ceiling_g_h(np.array([0.0]), np.array([100.0]))[0] == pytest.approx(60.0)
    mid = nut.intake_ceiling_g_h(np.array([50.0]), np.array([50.0]))[0]
    assert 60.0 <= mid <= 120.0


def test_carb_burn_grows_with_power():
    fat = np.array([0.0, 0.0])
    burn = nut.carb_burn_g_h(np.array([150.0, 300.0]), np.array([0.5, 1.0]), fat)
    assert burn[1] > 2 * burn[0]  # mehr Leistung *und* höherer KH-Anteil


# ----------------------------------------------------------------------
# Tragbare Intensität
# ----------------------------------------------------------------------
def test_sustainable_intensity_balances_the_energy_equation():
    """Rückrechnen: der gefundene Wert muss die Bilanz genau treffen."""
    ftp, intake, glyco, hours, fat = 300.0, 80.0, 1700.0, 10.0, 0.0
    value = nut.sustainable_intensity(ftp, intake, glyco, hours, fat)
    burn = nut.carb_burn_g_h(np.array([ftp * value]), np.array([value]), np.array([fat]))[0]
    supply = intake + nut.PLANNED_DRAWDOWN * glyco / nut.CARB_KCAL_PER_G / hours
    assert burn == pytest.approx(supply, rel=1e-3)


def test_longer_races_are_more_energy_limited():
    """Über die Dauer verdünnt sich der Speicher – die Zufuhr bleibt."""
    args = (320.0, 80.0, 1700.0)
    short = nut.sustainable_intensity(*args, 4.0, 0.0)
    medium = nut.sustainable_intensity(*args, 12.0, 0.0)
    long = nut.sustainable_intensity(*args, 40.0, 0.0)
    assert short > medium > long


def test_the_ceiling_bites_harder_for_stronger_riders():
    """Die entscheidende Eigenschaft des Modells.

    Die Zufuhr hat eine absolute Obergrenze, der Verbrauch skaliert mit
    der Leistung. Ein starker Fahrer kann nicht proportional mehr essen –
    also darf er relativ zu seiner FTP weniger fahren.
    """
    weak = nut.sustainable_intensity(220.0, 80.0, 1700.0, 12.0, 0.0)
    strong = nut.sustainable_intensity(400.0, 80.0, 1700.0, 12.0, 0.0)
    assert strong < weak


def test_fat_burning_and_gut_tolerance_buy_intensity():
    base = nut.sustainable_intensity(320.0, 80.0, 1700.0, 12.0, 0.0)
    fatty = nut.sustainable_intensity(320.0, 80.0, 1700.0, 12.0, 1.0)
    fed = nut.sustainable_intensity(320.0, 110.0, 1700.0, 12.0, 0.0)
    assert fatty > base
    assert fed > base


# ----------------------------------------------------------------------
# Hungerast
# ----------------------------------------------------------------------
def test_bonk_factor_is_neutral_until_the_threshold():
    assert nut.bonk_factor(np.array([1.0]))[0] == 1.0
    assert nut.bonk_factor(np.array([0.20]))[0] == 1.0
    assert nut.bonk_factor(np.array([nut.BONK_THRESHOLD]))[0] == pytest.approx(1.0)


def test_bonk_factor_falls_smoothly_to_the_floor():
    assert nut.bonk_factor(np.array([0.0]))[0] == pytest.approx(nut.BONK_FLOOR)
    mid = nut.bonk_factor(np.array([nut.BONK_THRESHOLD / 2]))[0]
    assert nut.BONK_FLOOR < mid < 1.0
    # monoton
    values = nut.bonk_factor(np.linspace(0.0, 0.3, 40))
    assert np.all(np.diff(values) >= -1e-12)


# ----------------------------------------------------------------------
# Rennplan
# ----------------------------------------------------------------------
def _plan(rider, route, seed: int = 0):
    streams = RiderStreams(seed, rider.id)
    return st.build_plan(
        rider, route, streams.get("plan"), streams.get("misjudge"), streams.get("stops")
    )


def test_plan_carries_intake_and_stops(route_medium):
    rng = np.random.default_rng(0)
    rider = generate_rider(rng, 0, 0)
    plan = _plan(rider, route_medium)
    assert plan.intake_g_h > 0
    assert plan.est_ride_time_s > 0
    assert len(plan.stops) == len(route_medium.service_points)
    assert any("Energiedeckel" in note for _, note in plan.notes)
    assert any("Stoppplan" in note for _, note in plan.notes)


def test_energy_cap_never_raises_the_target(route):
    """Der Deckel ist ein Minimum, kein Ersatz für die Distanzformel."""
    rng = np.random.default_rng(1)
    for i in range(40):
        rider = generate_rider(rng, i, 0)
        plan = _plan(rider, route, seed=i)
        wish, _, _ = st.target_intensity(
            rider, route.distance_km, RiderStreams(i, rider.id).get("plan")
        )
        assert plan.target_if <= wish + 1e-9


def test_gut_tolerance_shows_up_in_the_plan(route):
    rng = np.random.default_rng(2)
    base = generate_rider(rng, 0, 0, archetype="allrounder")

    def target(magen: float) -> float:
        attrs = {**base.attributes, "magenvertraeglichkeit": magen}
        rider = Rider(**{**base.to_dict(), "attributes": attrs})
        return _plan(rider, route).intake_g_h

    assert target(95.0) > target(15.0)


# ----------------------------------------------------------------------
# Stoppplan
# ----------------------------------------------------------------------
def test_full_service_appears_only_after_enough_hours(route_medium):
    rng = np.random.default_rng(0)
    # Jeder Abschnitt fünf Stunden: Nach spätestens zwei Halten ist die
    # Acht-Stunden-Schwelle überschritten.
    times = [5 * 3600.0] * len(route_medium.service_points)
    stops = st.plan_service_stops(route_medium, times, rng)
    kinds = [s.kind for s in stops]
    assert set(kinds) <= {"kurz", "voll"}
    assert "voll" in kinds
    assert all(st.FULL_SERVICE_S[0] <= s.planned_s <= st.FULL_SERVICE_S[1]
               for s in stops if s.kind == "voll")


def test_short_races_only_get_short_stops(route_medium):
    rng = np.random.default_rng(0)
    times = [900.0] * 10  # je 15 Minuten – nie genug für einen Vollservice
    stops = st.plan_service_stops(route_medium, times, rng)
    assert all(s.kind == "kurz" for s in stops)
    assert all(st.SHORT_SERVICE_S[0] <= s.planned_s <= st.SHORT_SERVICE_S[1] for s in stops)


def test_stop_duration_follows_service_discipline():
    """Ein schlampiges Team kostet Zeit, die keine Beinarbeit zurückholt."""
    sloppy = np.mean([st.stop_duration(120.0, 1.25, np.random.default_rng(i)) for i in range(400)])
    slick = np.mean([st.stop_duration(120.0, 0.75, np.random.default_rng(i)) for i in range(400)])
    assert sloppy > slick * 1.4
    assert st.stop_duration(120.0, 0.75, np.random.default_rng(0)) >= 15.0


# ----------------------------------------------------------------------
# Im Rennen
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def energy_race(route_medium):
    teams, riders = generate_pool(20, n_teams=4, seed=9)
    return simulate_race(route_medium, riders, teams, RaceConfig(seed=5))


def test_glycogen_is_tracked_and_bounded(energy_race):
    tel = energy_race.telemetry
    assert tel.glyco_pct.dtype == np.uint8
    assert tel.glyco_pct.max() <= 100
    # Zu Beginn voll, danach fällt es
    assert np.all(tel.glyco_pct[:, 0] >= 99)
    riding = tel.state < 2
    assert tel.glyco_pct[riding].min() < 100


def test_glycogen_only_falls_while_riding(energy_race):
    """Beim Stehen wird gegessen, nicht verbrannt."""
    tel = energy_race.telemetry
    for entry_id in range(min(5, tel.n_entries)):
        stopped = tel.state[entry_id] == 1
        if not stopped.any():
            continue
        idx = np.flatnonzero(stopped)
        # Über eine Standphase darf der Speicher nicht sinken. Der Kanal
        # ist uint8, deshalb hier in int rechnen: Bei leerem Speicher
        # wäre "0 − 1" sonst 255 und der Vergleich unsinnig.
        row = tel.glyco_pct[entry_id].astype(np.int16)
        for i in idx[:-1]:
            if stopped[i + 1]:
                assert row[i + 1] >= row[i] - 1


def test_service_stops_cost_time(route_medium):
    teams, riders = generate_pool(12, n_teams=3, seed=3)
    # Ohne Zwischenfälle: Hier geht es um den *geplanten* Halt, und ein
    # Pannenstopp dazwischen würde die Aussage nur verwischen.
    result = simulate_race(
        route_medium, riders, teams, RaceConfig(seed=1, enable_incidents=False)
    )
    starts = [e for e in result.events if e.type == STOP_START]
    ends = [e for e in result.events if e.type == STOP_END]
    assert starts
    assert len(ends) <= len(starts)
    for event in starts:
        assert event.payload["duration_s"] > 0
        assert event.payload["kind"] in ("kurz", "voll")


def test_bonk_events_are_reported_with_their_state(energy_race):
    for event in energy_race.events:
        if event.type != BONK:
            continue
        assert event.payload["glyco_pct"] < nut.BONK_THRESHOLD * 100 + 1
        assert event.payload["dist_km"] >= 0


def test_energy_model_slows_a_long_race_down(route_medium):
    """Die Wirkung muss messbar sein, sonst ist der Aufwand Kosmetik.

    Verglichen wird gegen dieselbe Konfiguration mit künstlich
    unbegrenzter Zufuhr – der einzige saubere Weg, den Effekt zu
    isolieren.
    """
    teams, riders = generate_pool(12, n_teams=3, seed=3)
    limited = simulate_race(route_medium, riders, teams, RaceConfig(seed=1))

    original = nut.GUT_G_H
    try:
        nut.GUT_G_H = (10_000.0, 10_000.0)  # Magen als Nadelöhr abschalten
        unlimited = simulate_race(route_medium, riders, teams, RaceConfig(seed=1))
    finally:
        nut.GUT_G_H = original

    a = min(e.finish_time_s for e in limited.entries if e.finish_time_s)
    b = min(e.finish_time_s for e in unlimited.entries if e.finish_time_s)
    assert a > b, "Auf dieser Distanz muss der Energiedeckel messbar bremsen"
