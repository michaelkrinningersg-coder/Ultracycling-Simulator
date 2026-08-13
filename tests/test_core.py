"""Tests von Physik, Fahrermodell, Form und Ermüdung (M2/M3)."""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core import fatigue as fat
from ultrasim.core import form as fm
from ultrasim.core import physics as ph
from ultrasim.core import strategy as st
from ultrasim.core.rider import (
    ARCHETYPES,
    ATTRIBUTES,
    Rider,
    Team,
    generate_pool,
    generate_rider,
    season_form,
)


# ----------------------------------------------------------------------
# Physik
# ----------------------------------------------------------------------
def _reference_rider() -> dict:
    """180 cm, 70 kg, Straßenrad im Unterlenker."""
    area = 0.0276 * 1.80**0.725 * 70.0**0.425
    return {
        "mass": np.array([70.0 + 7.5 + ph.SUPPORTED_LUGGAGE_KG]),
        "cda": np.array([area * ph.K_POSITION["drops"] + ph.SUPPORTED_LUGGAGE_CDA]),
        "crr": np.array([ph.CRR["asphalt_good"]]),
        "rho": np.array([1.225]),
    }


def test_frontal_area_matches_reference_values():
    area = 0.0276 * 1.80**0.725 * 70.0**0.425
    assert 0.24 < area * ph.K_POSITION["tt"] + 0.01 < 0.27
    assert 0.28 < area * ph.K_POSITION["drops"] + 0.01 < 0.33
    assert 0.36 < area * ph.K_POSITION["climbing"] + 0.01 < 0.40


@pytest.mark.parametrize(
    "power,grade,lo_kmh,hi_kmh",
    [
        (280, 0.00, 36.0, 42.0),  # solide Zeitfahrleistung im Flachen
        (200, 0.00, 31.0, 37.0),
        (280, 0.06, 15.0, 20.0),  # 6 % am Berg
        (280, 0.10, 10.0, 14.0),
        (0, -0.06, 45.0, 60.0),  # rollen lassen bergab
    ],
)
def test_steady_state_speed_is_plausible(power, grade, lo_kmh, hi_kmh):
    """Plausibilität vor Genauigkeit – aber die Größenordnung muss stimmen."""
    r = _reference_rider()
    v = ph.steady_state_speed(np.array([float(power)]), np.array([grade]), r["mass"], r["cda"], r["crr"], r["rho"])
    assert lo_kmh < float(v[0]) * 3.6 < hi_kmh


def test_air_density_falls_with_altitude():
    """Auf 2000 m fährt man im Flachen bei gleicher Leistung schneller."""
    low = float(ph.air_density(0.0))
    high = float(ph.air_density(2000.0))
    assert 1.20 < low < 1.26
    assert high < low * 0.87
    r = _reference_rider()
    v_low = ph.steady_state_speed(np.array([280.0]), np.array([0.0]), r["mass"], r["cda"], r["crr"], np.array([low]))
    v_high = ph.steady_state_speed(np.array([280.0]), np.array([0.0]), r["mass"], r["cda"], r["crr"], np.array([high]))
    assert v_high[0] > v_low[0]


def test_slope_trig_matches_arctan():
    grade = np.linspace(-0.25, 0.25, 51)
    cos, sin = ph.slope_trig(grade)
    assert np.allclose(cos, np.cos(np.arctan(grade)))
    assert np.allclose(sin, np.sin(np.arctan(grade)))


def test_downhill_taper_kills_power_at_high_speed():
    assert ph.downhill_power_taper(np.array([10.0]))[0] == 1.0
    assert ph.downhill_power_taper(np.array([20.0]))[0] == 0.0
    mid = ph.downhill_power_taper(np.array([16.0]))[0]
    assert 0.0 < mid < 1.0


def test_speed_never_exceeds_safety_cap():
    """Ein globaler Deckel verhindert Ausreißer in steilen Abfahrten."""
    v = np.array([20.0])
    for _ in range(200):
        v = ph.integrate_step(
            v, np.array([400.0]), np.array([-0.20]), np.array([80.0]),
            np.array([0.30]), np.array([0.004]), np.array([1.225]), 1.0,
        )
    assert float(v[0]) <= ph.MAX_SPEED


def test_corner_limit_tightens_with_curviness():
    straight = ph.corner_speed_limit(np.array([5.0]), np.array([0.0]), np.array([0.0]))[0]
    hairpins = ph.corner_speed_limit(np.array([900.0]), np.array([0.0]), np.array([0.0]))[0]
    assert hairpins < straight
    skilled = ph.corner_speed_limit(np.array([900.0]), np.array([1.0]), np.array([1.0]))[0]
    assert skilled > hairpins


def test_integration_converges_to_steady_state():
    """Euler-Integration und Gleichgewichtslösung müssen zusammenpassen."""
    r = _reference_rider()
    target = ph.steady_state_speed(np.array([250.0]), np.array([0.02]), r["mass"], r["cda"], r["crr"], r["rho"])
    v = np.array([1.0])
    for _ in range(600):
        v = ph.integrate_step(v, np.array([250.0]), np.array([0.02]), r["mass"], r["cda"], r["crr"], r["rho"], 1.0)
    assert float(v[0]) == pytest.approx(float(target[0]), rel=0.02)


# ----------------------------------------------------------------------
# Fahrergenerator
# ----------------------------------------------------------------------
def test_potential_budget_normalises_every_rider():
    """Jede Stärke muss irgendwo bezahlt werden."""
    rng = np.random.default_rng(3)
    values = [generate_rider(rng, i, 0).potential for i in range(300)]
    assert 44.0 < float(np.mean(values)) < 56.0
    assert float(np.std(values)) < 6.0
    assert max(values) - min(values) < 30.0


def test_archetypes_keep_their_shape_after_budgeting():
    """Der Kletterer muss Kletterer bleiben, auch nach der Normierung."""
    rng = np.random.default_rng(5)
    climbers = [generate_rider(rng, i, 0, archetype="kletterer") for i in range(120)]
    ttists = [generate_rider(rng, 500 + i, 0, archetype="zeitfahrer") for i in range(120)]
    assert np.mean([r.attr("berg") for r in climbers]) > np.mean([r.attr("berg") for r in ttists]) + 20
    assert np.mean([r.attr("flach") for r in ttists]) > np.mean([r.attr("flach") for r in climbers]) + 20
    # und physiologisch: leichter, mehr W/kg
    assert np.mean([r.weight_kg for r in climbers]) < np.mean([r.weight_kg for r in ttists])
    assert np.mean([r.wkg for r in climbers]) > np.mean([r.wkg for r in ttists])


def test_generated_riders_are_physiologically_plausible():
    _, riders = generate_pool(400, seed=11)
    for r in riders:
        assert 3.5 <= r.wkg <= 6.0
        assert 158 <= r.height_cm <= 198
        bmi = r.weight_kg / (r.height_cm / 100.0) ** 2
        assert 18.0 <= bmi <= 26.0
        assert 19 <= r.age <= 47
        assert set(r.attributes) == set(ATTRIBUTES)
        assert all(0 <= v <= 100 for v in r.attributes.values())


def test_pool_generation_is_deterministic():
    a = generate_pool(50, seed=17)
    b = generate_pool(50, seed=17)
    assert [r.name for r in a[1]] == [r.name for r in b[1]]
    assert [r.ftp_w for r in a[1]] == [r.ftp_w for r in b[1]]


def test_team_service_factor_follows_the_formula():
    """1,25 bei 0 · 1,00 bei 50 · 0,75 bei 100 (Abschnitt 6.3)."""
    assert Team(0, "x", "GER", "#fff", 0).service_factor == pytest.approx(1.25)
    assert Team(0, "x", "GER", "#fff", 50).service_factor == pytest.approx(1.00)
    assert Team(0, "x", "GER", "#fff", 100).service_factor == pytest.approx(0.75)


def test_all_archetypes_generate():
    rng = np.random.default_rng(2)
    for key in ARCHETYPES:
        rider = generate_rider(rng, 0, 0, archetype=key)
        assert rider.archetype == key
        assert rider.ftp_w > 0


# ----------------------------------------------------------------------
# Form
# ----------------------------------------------------------------------
def test_correlation_length_scales_with_route_and_stays_bounded():
    """Sonst mittelt sich die Abschnittsform über lange Rennen weg."""
    assert fm.correlation_length_m(150_000) == 40_000
    assert fm.correlation_length_m(1_000_000) == 60_000
    assert fm.correlation_length_m(2_500_000) == 150_000
    assert fm.correlation_length_m(9_000_000) == 200_000


def test_section_form_is_stationary_regardless_of_grid():
    """Eine feinere Auflösung darf das Balancing nicht verschieben."""
    rngs = [np.random.default_rng(i) for i in range(60)]
    coarse, _ = fm.build_section_form(60, 800_000.0, rngs, grid_m=1000.0)
    rngs = [np.random.default_rng(i) for i in range(60)]
    fine, _ = fm.build_section_form(60, 800_000.0, rngs, grid_m=250.0)
    assert float(coarse.std()) == pytest.approx(float(fine.std()), rel=0.25)
    assert 0.955 <= coarse.min() and coarse.max() <= 1.045


def test_section_form_creates_phases_not_noise():
    """Benachbarte Punkte müssen stark korreliert sein."""
    rngs = [np.random.default_rng(7)]
    track, grid = fm.build_section_form(1, 1_000_000.0, rngs)
    series = track[0]
    lag1 = np.corrcoef(series[:-1], series[1:])[0, 1]
    assert lag1 > 0.95
    # Über die Korrelationslänge hinaus löst sich der Zusammenhang.
    lag_far = int(fm.correlation_length_m(1_000_000.0) / grid) * 3
    assert abs(np.corrcoef(series[:-lag_far], series[lag_far:])[0, 1]) < 0.6


def test_day_form_spread_is_inverse_to_consistency():
    assert fm.day_form_sd(100) < fm.day_form_sd(50) < fm.day_form_sd(0)


def test_day_form_stays_in_band():
    rng = np.random.default_rng(1)
    riders = [generate_rider(rng, i, 0) for i in range(200)]
    values = fm.draw_day_form(riders, [np.random.default_rng(i) for i in range(200)])
    assert values.min() >= fm.DAY_FORM_CLIP[0]
    assert values.max() <= fm.DAY_FORM_CLIP[1]


def test_season_form_peaks_at_the_peak_day():
    rng = np.random.default_rng(1)
    rider = generate_rider(rng, 0, 0)
    rider.form_peak_day = 180
    assert season_form(rider, 180) > season_form(rider, 240) > season_form(rider, 330)
    assert 0.895 <= season_form(rider, 10) <= 1.085


# ----------------------------------------------------------------------
# Ermüdung
# ----------------------------------------------------------------------
def test_fatigue_matches_its_calibration_points():
    """Die Eckpunkte aus der Kalibrierung festhalten (Abschnitt 5.5).

    Rund 8.300 kJ entsprechen einem 300-km-Rennen, rund 70.000 kJ einem
    Rennen über 2500 km. Wenn hier jemand schraubt, soll er es merken.
    """
    cap = fat.work_capacity_kj(np.array([50.0]), np.array([50.0]), np.array([70.0]))
    assert float(cap[0]) == pytest.approx(42_000.0, rel=0.02)
    assert fat.fatigue_factor(np.array([8_300.0]), cap)[0] == pytest.approx(0.88, abs=0.03)
    assert fat.fatigue_factor(np.array([70_000.0]), cap)[0] == pytest.approx(0.55, abs=0.04)


def test_fatigue_is_monotonic_and_floored():
    work = np.array([0.0, 5_000.0, 20_000.0, 80_000.0, 500_000.0])
    values = fat.fatigue_factor(work, np.full(5, 42_000.0))
    assert values[0] == 1.0
    assert np.all(np.diff(values) < 0)
    assert values[-1] >= fat.FATIGUE_FLOOR


def test_endurance_attribute_buys_durability():
    weak = fat.work_capacity_kj(np.array([10.0]), np.array([50.0]), np.array([70.0]))
    strong = fat.work_capacity_kj(np.array([90.0]), np.array([50.0]), np.array([70.0]))
    work = np.array([30_000.0])
    assert fat.fatigue_factor(work, strong)[0] > fat.fatigue_factor(work, weak)[0]


def test_w_prime_discharges_above_threshold_and_recovers_below():
    cap = np.array([20_000.0])
    balance = cap.copy()
    balance = fat.w_prime_step(balance, cap, np.array([400.0]), np.array([250.0]), 60.0)
    assert float(balance[0]) == pytest.approx(20_000.0 - 150.0 * 60.0)
    recovered = fat.w_prime_step(balance, cap, np.array([150.0]), np.array([250.0]), 60.0)
    assert float(recovered[0]) > float(balance[0])
    assert float(recovered[0]) <= float(cap[0])


def test_w_prime_capacity_scales_with_punch():
    lively = fat.w_prime_capacity(np.array([90.0]), np.array([70.0]))
    dull = fat.w_prime_capacity(np.array([10.0]), np.array([70.0]))
    assert lively[0] > dull[0]
    assert 10_000 < dull[0] < 30_000


# ----------------------------------------------------------------------
# Strategiemodul
# ----------------------------------------------------------------------
def test_target_intensity_follows_the_documented_anchors():
    """200 km ≈ 78–85 % FTP, 2500 km ≈ 55–62 % (Abschnitt 7.1)."""
    assert 0.78 <= st.base_target_if(200) <= 0.85
    assert 0.55 <= st.base_target_if(2500) <= 0.62
    # und monoton fallend über die Distanz
    values = [st.base_target_if(d) for d in (150, 300, 600, 1200, 2500)]
    assert all(a > b for a, b in zip(values, values[1:], strict=False))


def test_weak_pacers_plan_too_hot():
    """Der Plan ist absichtlich unvollkommen – daraus entstehen die Einbrüche."""
    rng = np.random.default_rng(0)
    base = generate_rider(rng, 0, 0, archetype="allrounder")
    disciplined = Rider(**{**base.to_dict(), "attributes": {**base.attributes,
                                                            "pacing_disziplin": 95.0, "erfahrung": 95.0}})
    reckless = Rider(**{**base.to_dict(), "attributes": {**base.attributes,
                                                         "pacing_disziplin": 5.0, "erfahrung": 5.0}})
    good = np.mean([st.target_intensity(disciplined, 500, np.random.default_rng(i))[0] for i in range(200)])
    bad = np.mean([st.target_intensity(reckless, 500, np.random.default_rng(i))[0] for i in range(200)])
    assert bad > good


def test_terrain_factor_adds_power_uphill_only():
    grade = np.array([-0.05, 0.0, 0.05, 0.12])
    factor = st.terrain_power_factor(grade, np.full(4, 0.2))
    assert factor[0] == 1.0 and factor[1] == 1.0
    assert factor[2] > 1.0
    assert factor[3] == pytest.approx(1.2)


def test_bike_plan_rejects_uneconomic_changes(route):
    """Ohne Wirtschaftlichkeitsprüfung wechselt man bei jedem Hügel."""
    rng = np.random.default_rng(0)
    rider = generate_rider(rng, 0, 0, archetype="allrounder")
    sections, notes = st.build_bike_plan(rider, route, 0.75, 0.2, change_cost_s=1e9)
    # Bei absurd teurem Wechsel darf kein einziger stattfinden.
    assert {s.bike for s in sections} == {ph.BIKE_ROAD}
    assert any("abgelehnt" in note for _, note in notes)


def test_bike_plan_logs_a_reason_for_every_decision(route):
    rng = np.random.default_rng(0)
    rider = generate_rider(rng, 0, 0)
    plan = st.build_plan(rider, route, rng)
    assert plan.notes
    assert any("Rennplan" in note for _, note in plan.notes)
    assert plan.sections
    assert plan.sections[0].dist_start_m == 0.0
    assert plan.sections[-1].dist_end_m == pytest.approx(route.distance_m)


def test_bike_change_duration_respects_service_discipline():
    sloppy = np.mean([st.bike_change_duration(np.random.default_rng(i), 1.25) for i in range(500)])
    slick = np.mean([st.bike_change_duration(np.random.default_rng(i), 0.75) for i in range(500)])
    assert sloppy > slick
    assert st.bike_change_duration(np.random.default_rng(0), 0.75) >= st.BIKE_CHANGE_MIN_S


def test_active_attribute_list_matches_the_code():
    """Die Liste ist eine Zusicherung an den Nutzer, kein Kommentar.

    Das Fahrerdetail hebt genau diese Attribute hervor. Steht dort eines,
    das die Simulation gar nicht liest, ist die Anzeige eine Lüge – und
    umgekehrt bleibt eine echte Stärke unsichtbar.
    """
    from pathlib import Path

    from ultrasim.core.rider import ACTIVE_ATTRIBUTES, ATTRIBUTES

    root = Path(__file__).resolve().parents[1] / "ultrasim"
    sources = "\n".join(
        path.read_text("utf-8")
        for path in root.rglob("*.py")
        if path.name not in ("rider.py", "names.py")
    )
    for key in ATTRIBUTES:
        used = f'"{key}"' in sources
        assert used == (key in ACTIVE_ATTRIBUTES), (
            f"'{key}' wird {'benutzt' if used else 'nicht benutzt'}, steht aber "
            f"{'nicht ' if used else ''}in ACTIVE_ATTRIBUTES"
        )
