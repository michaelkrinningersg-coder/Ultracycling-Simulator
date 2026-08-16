"""Tests von Physik, Fahrermodell, Form und Ermüdung (M2/M3)."""

from __future__ import annotations

from dataclasses import replace

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
    # Geprüft wird der **Planungsfehler**, nicht die Zielintensität.
    # Seit Pacing-Disziplin zweiseitig wirkt, plant der disziplinierte
    # Fahrer durchaus höher als der schlampige — nur eben zu Recht:
    # Gleichmäßiges Fahren trägt bei gleichem Aufwand mehr Leistung.
    # Die Zielintensität zu vergleichen prüfte damit die falsche Größe.
    good = np.mean([st.target_intensity(disciplined, 500, np.random.default_rng(i))[1] for i in range(200)])
    bad = np.mean([st.target_intensity(reckless, 500, np.random.default_rng(i))[1] for i in range(200)])
    assert bad > good
    assert good < st.MISJUDGE_THRESHOLD, "Wer sauber pact, hat keinen nennenswerten Überzug"


def test_pacing_discipline_pays_in_both_directions():
    """Oberhalb 50 muss Disziplin etwas *kaufen*, nicht nur nichts kosten.

    Vorher hing die Größe allein an ``max(0, (50 − pd) / 50)``: Ein
    Fahrer mit 80 plante Punkt für Punkt wie einer mit 50, und jeder
    Punkt darüber war verschenktes Potenzial-Budget. Die
    Sensitivitätsmatrix hat das Attribut folgerichtig mit −83 Sekunden
    ausgewiesen — Disziplin *kostete* Zeit.
    """
    rng = np.random.default_rng(0)
    base = generate_rider(rng, 0, 0, archetype="allrounder")

    def plan(pd: float) -> tuple[float, float]:
        r = Rider(**{**base.to_dict(), "attributes": {**base.attributes, "pacing_disziplin": pd}})
        runs = [st.target_intensity(r, 500, np.random.default_rng(i)) for i in range(200)]
        return float(np.mean([v for v, _, _ in runs])), float(np.mean([o for _, o, _ in runs]))

    if_50, over_50 = plan(50.0)
    if_100, over_100 = plan(100.0)
    if_0, over_0 = plan(0.0)

    # Oberseite: mehr Intensität, kein zusätzlicher Fehler.
    assert if_100 > if_50 + 0.01
    assert over_100 == pytest.approx(over_50, abs=1e-9)
    # Unterseite: noch mehr Intensität, aber als Wette bezahlt.
    assert if_0 > if_100
    assert over_0 > over_100 + 0.02


def test_terrain_factor_adds_power_uphill_only():
    grade = np.array([-0.05, 0.0, 0.05, 0.12])
    factor = st.terrain_power_factor(grade, np.full(4, 0.2))
    assert factor[0] == 1.0 and factor[1] == 1.0
    assert factor[2] > 1.0
    assert factor[3] == pytest.approx(1.2)


def test_the_climb_surcharge_is_paid_for_in_the_flat(route):
    """Die tragende Zusicherung der Budgetneutralität.

    Nach der Normierung muss die zeitgewichtete mittlere Intensität dem
    geplanten Wert entsprechen — sonst ist der Aufschlag wieder
    geschenkt, und ``berg`` schlägt ``flach`` allein deshalb, weil es
    eine andere Größe bewegt.
    """
    rng = np.random.default_rng(0)
    rider = generate_rider(rng, 0, 0, archetype="kletterer")
    boost = st.climb_boost(rider)
    norm = st.boost_normalisation(rider, route, 0.75, boost)
    assert norm < 1.0, "Auf einer Strecke mit Anstiegen muss etwas abzubezahlen sein"

    grades, dists, mean_ele = st._grade_histogram(route, 0.0, route.distance_m, n_bins=65)
    factor = norm * st.terrain_power_factor(grades, np.full_like(grades, boost))
    # Grob mit der Distanz gewichtet liegt das Mittel nahe eins; exakt
    # trifft es die Zeitgewichtung, die die Funktion selbst benutzt.
    assert 0.9 < float(np.average(factor, weights=dists)) < 1.1
    assert factor.max() > 1.0, "Am Anstieg wird weiterhin zugelegt"
    assert factor.min() < 1.0, "…und im Flachen weiterhin gespart"


def test_a_flat_route_has_nothing_to_pay_back(route_long):
    """Ohne Anstiege gibt es keinen Aufschlag und damit keine Rechnung."""
    rng = np.random.default_rng(0)
    rider = generate_rider(rng, 0, 0, archetype="allrounder")
    flat = replace(route_long, ele_dm=np.zeros_like(route_long.ele_dm))
    assert st.boost_normalisation(rider, flat, 0.75, st.climb_boost(rider)) == pytest.approx(1.0)


def test_the_stronger_climber_pays_the_larger_bill(route):
    """Wer mehr zulegt, muss mehr abtragen — sonst wäre es kein Budget."""
    rng = np.random.default_rng(0)
    rider = generate_rider(rng, 0, 0, archetype="allrounder")
    strong = st.boost_normalisation(rider, route, 0.75, 0.30)
    weak = st.boost_normalisation(rider, route, 0.75, 0.05)
    assert strong < weak < 1.0


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


# ----------------------------------------------------------------------
# Radwahl am Anstieg
# ----------------------------------------------------------------------
def test_the_road_bike_wins_on_a_steep_climb():
    """Die Grundlage der ganzen Radwahl — erst danach lohnt der Rest.

    Das Zeitfahrrad wiegt anderthalb Kilo mehr und verliert an Rampen
    über 6 % vier Prozent Wirkungsgrad; sein Windvorteil zählt bei
    12 km/h praktisch nicht. Über zehn Kilometer bei 8 % sind das
    Minuten.
    """
    rider = generate_rider(np.random.default_rng(3), 0, 0, archetype="allrounder")
    dists = np.array([10_000.0])
    for grade, expected in ((0.0, ph.BIKE_TT), (0.08, ph.BIKE_ROAD)):
        grades = np.array([grade])
        t_road = st.estimate_section_time(
            rider, rider.ftp_w * 0.7, 0.16, grades, dists, 800.0, ph.BIKE_ROAD
        )
        t_tt = st.estimate_section_time(
            rider, rider.ftp_w * 0.7, 0.16, grades, dists, 800.0, ph.BIKE_TT
        )
        faster = ph.BIKE_TT if t_tt < t_road else ph.BIKE_ROAD
        assert faster == expected, f"bei {grade:.0%} sollte {expected} schneller sein"


def test_a_long_climb_opens_a_bike_change(route_medium):
    """Fuß und Kuppe eines echten Anstiegs sind Abschnittsgrenzen.

    Ohne sie liegt ein Abschnitt zwischen zwei Servicepunkten, und auf
    507 km mit fünf Servicepunkten sind das 90 km. Weil darin 80 %
    Flachland stecken, gewinnt das Zeitfahrrad über die Summe — und der
    Fahrer quält sich damit über jeden Pass.
    """
    qualifying = [
        c
        for c in route_medium.climbs
        if c.length_m >= st.BIKE_STOP_MIN_LENGTH_M and c.grade_avg >= st.BIKE_STOP_MIN_GRADE
    ]
    assert qualifying, "Die Fixture soll einen richtigen Anstieg haben"
    bounds = st._section_bounds(route_medium)
    for climb in qualifying:
        assert any(abs(b - climb.dist_start_m) < st.MIN_SECTION_M for b in bounds), (
            f"Kein Abschnittswechsel am Fuß von km {climb.dist_start_m / 1000:.1f}"
        )


def test_a_mere_bump_does_not_open_a_bike_change(route_medium):
    """Unter 4 km oder unter 3 % bleibt es eine Welle."""
    bounds = set(st._section_bounds(route_medium))
    for climb in route_medium.climbs:
        if climb.length_m < st.BIKE_STOP_MIN_LENGTH_M or climb.grade_avg < st.BIKE_STOP_MIN_GRADE:
            assert climb.dist_start_m not in bounds


def test_sections_stay_long_enough_to_be_worth_a_change(route_medium):
    bounds = st._section_bounds(route_medium)
    gaps = np.diff(np.array(bounds))
    assert (gaps >= st.MIN_SECTION_M).all(), "Zu dichte Marken müssen zusammenfallen"
    assert bounds[0] == 0.0
    assert bounds[-1] == pytest.approx(route_medium.distance_m)


def test_the_bike_follows_the_stopwatch_including_the_change(route_medium):
    """Die Regel, auf die es ankommt.

    Gewechselt wird genau dann, wenn das andere Rad **mehr** Zeit
    einspart, als der Wechsel kostet — und sonst nie. Ein Abschnitt mit
    halbem Steilanteil, auf dem das Straßenrad 53 Sekunden gutmacht, ist
    bei 60 Sekunden Wechselkosten kein Grund abzusteigen.
    """
    rng = np.random.default_rng(9)
    rider = generate_rider(rng, 0, 0, archetype="kletterer")
    cost = 60.0
    sections, _ = st.build_bike_plan(rider, route_medium, 0.72, 0.2, change_cost_s=cost)

    current = ph.BIKE_ROAD
    for section in sections:
        faster = ph.BIKE_TT if section.est_time_tt_s < section.est_time_road_s else ph.BIKE_ROAD
        gain = abs(section.est_time_road_s - section.est_time_tt_s)
        if faster != current and gain > cost:
            assert section.bike == faster, "Ein Wechsel, der sich rechnet, muss stattfinden"
            current = faster
        else:
            assert section.bike == current, "Ohne Gewinn bleibt das Rad, wie es ist"


def test_a_real_pass_is_ridden_on_the_road_bike(route_medium):
    """Der Befund, der das ausgelöst hat: Pässe im Zeitfahrrad.

    Auf einem Anstieg, der lang und steil genug ist, trägt der Gewinn
    die Wechselkosten mit Abstand — dort darf kein Zeitfahrrad stehen.

    Der Pass wird hier gebaut. Vorher stand er in der Fixture, und das
    ging so lange gut, wie das Zeitfahrrad an *jeder* Steigung über
    sechs Prozent pauschal vier Prozent Leistung verlor. Seit der
    Verlust aus der Entfaltung folgt, ist er an einem Siebenprozenter
    gleich null — dort tritt man auch mit 42×28 noch 79 Umdrehungen, und
    das ist kein Mahlen. Erst darüber wird es zäh. Ein Test, der das
    prüfen will, braucht also einen Anstieg, der wirklich steil ist.
    """
    rng = np.random.default_rng(9)
    rider = generate_rider(rng, 0, 0, archetype="kletterer")
    steep = _with_steep_ramps(route_medium)
    cost = 25.0
    sections, _ = st.build_bike_plan(rider, steep, 0.72, 0.2, change_cost_s=cost)

    # Die Schwelle hängt an der Entscheidungsregel und nicht an einer
    # geerbten Zahl: Gewechselt wird, wenn der Gewinn die Wechselkosten
    # trägt, also ist „klar" das Doppelte davon. Vorher standen hier
    # 100 Sekunden — kalibriert auf den pauschalen Vier-Prozent-Abzug,
    # der inzwischen weg ist.
    clear = [s for s in sections if s.est_time_tt_s - s.est_time_road_s > 2 * cost]
    assert clear, "Die Teststrecke soll einen richtigen Pass enthalten"
    assert all(s.bike == ph.BIKE_ROAD for s in clear)


def test_the_time_trial_bike_only_suffers_where_the_gearing_runs_out():
    """Die Kehrseite: An mäßiger Steigung darf es keinen Abzug geben.

    Der alte ``steep_penalty`` war eine Stufe — vier Prozent ab sechs
    Prozent Steigung, gleich hoch bei sieben wie bei fünfzehn. Er hat
    damit zwei verschiedene Dinge vermischt: die zu lange Übersetzung
    und die unbequeme Position. Die Übersetzung ist jetzt hergeleitet,
    und sie kostet erst da, wo sie wirklich ausgeht.
    """
    tt = ph.BIKES["tt"]
    # 7 % bei rund 15 km/h: 79 rpm, also noch im Bereich.
    rpm_mild = float(ph.cadence_rpm(np.array([15 / 3.6]), tt["dev_min_m"], tt["dev_max_m"])[0])
    assert rpm_mild > ph.CADENCE_GRIND
    assert float(ph.grind_factor(rpm_mild)) == 1.0

    # 15 % bei rund 11 km/h: 58 rpm, und das kostet.
    rpm_steep = float(ph.cadence_rpm(np.array([11 / 3.6]), tt["dev_min_m"], tt["dev_max_m"])[0])
    assert rpm_steep < ph.CADENCE_GRIND
    assert float(ph.grind_factor(rpm_steep)) < 0.98

    # Das Straßenrad bleibt dort bequem — das ist der ganze Unterschied.
    road = ph.BIKES["road"]
    rpm_road = float(ph.cadence_rpm(np.array([11 / 3.6]), road["dev_min_m"], road["dev_max_m"])[0])
    assert rpm_road > ph.CADENCE_GRIND
    assert float(ph.grind_factor(rpm_road)) == 1.0


def test_a_longer_top_gear_lets_you_pedal_further_downhill():
    """Der Abfahrtsdeckel gilt jetzt je Rad statt global.

    Die alten Konstanten (13,9 und 18,1 m/s) waren im größten Gang des
    Straßenrads genau 87 und 114 rpm — sie *waren* schon ein
    Trittfrequenzmodell, nur eines für ein einziges Rad.
    """
    v = np.array([19.0])  # 68 km/h
    road = float(ph.downhill_power_taper(v, ph.BIKES["road"]["dev_max_m"])[0])
    tt = float(ph.downhill_power_taper(v, ph.BIKES["tt"]["dev_max_m"])[0])
    assert road == 0.0, "mit 50x11 ist bei 65 km/h Schluss"
    assert tt > 0.0, "mit 54x11 tritt man länger mit"

    # Und der Vorgabewert reproduziert die frühere Kurve.
    assert ph.DOWNHILL_TAPER_START == pytest.approx(13.9, abs=0.1)
    assert ph.DOWNHILL_NO_POWER == pytest.approx(18.1, abs=0.1)


# ----------------------------------------------------------------------
# Steilrampen: W' muss überhaupt binden
# ----------------------------------------------------------------------
def test_the_anaerobic_ramp_only_starts_where_it_is_steep():
    """Unterhalb von acht Prozent darf gar nichts passieren.

    Der Term wird additiv eingemischt und nicht per Maximum gegen die
    Schwelle gerechnet — sonst höbe er jeden Fahrer im Flachen auf FTP.
    Diese Null ist also keine Formalität, sondern die Zusicherung.
    """
    grades = np.array([0.0, 0.04, st.ANAEROBIC_ONSET_GRADE, 0.11, st.ANAEROBIC_FULL_GRADE, 0.20])
    ramp = st.anaerobic_ramp(grades)
    assert ramp[0] == 0.0 and ramp[1] == 0.0 and ramp[2] == 0.0
    assert 0.0 < ramp[3] < 1.0
    assert ramp[4] == 1.0 and ramp[5] == 1.0, "oben sättigt er, statt ins Absurde zu laufen"


def test_the_anaerobic_ramp_rises_monotonically():
    grades = np.linspace(0.0, 0.20, 40)
    ramp = st.anaerobic_ramp(grades)
    assert np.all(np.diff(ramp) >= 0.0)


def _with_steep_ramps(base, pass_km: float = 20.0):
    """Dieselbe Strecke, aber mit echten Pässen statt Wellen.

    Je Pass sechs Kilometer an 8 %, dann anderthalb an 15 %, dann
    hinunter. Die Steilrampe allein genügt nicht: Ein Abschnitt reicht
    von Servicepunkt zu Servicepunkt beziehungsweise von Fuß zu Kuppe
    eines Anstiegs, und anderthalb Kilometer darin gehen im Rest unter.
    Auf der echten Bergstrecke ist der *Pass* der Abschnitt, und genau
    das muss die Testkulisse nachbauen.

    Gebaut wird sie hier und nicht aus ``data/`` geladen: Ein Test, der
    an einer mitgelieferten Streckendatei hängt, prüft am Ende die Datei
    und nicht die Mechanik.
    """
    step = base.raster_m
    ele = np.zeros(base.n_points, dtype=np.float64)
    legs = ((6000.0, 0.08), (1500.0, 0.15), (3000.0, -0.12), (4500.0, -0.09))
    stride = int(pass_km * 1000 / step)
    cursor = int(2000 / step)
    while cursor + sum(int(m / step) for m, _ in legs) < base.n_points:
        here = cursor
        for length_m, grade in legs:
            span = int(length_m / step)
            ele[here : here + span] = ele[max(here - 1, 0)] + np.arange(span) * step * grade
            here += span
        ele[here:] = ele[here - 1]
        cursor += stride
    return replace(base, ele_dm=(ele * 10.0).astype(np.int32))


def test_w_prime_actually_discharges_on_a_steep_route(route):
    """Die Mechanik war gemessen tot, und das darf sie nicht wieder werden.

    Vor diesem Test stand W′ in jedem Rennen, auf jeder Strecke und zu
    jedem Zeitpunkt bei 100 % — der Anteil der Zeit unter 95 % war exakt
    null. Zwei Ursachen: Die Zielleistung kam nie über die Schwelle, und
    keine mitgelieferte Strecke hatte eine Rampe über 10,8 %. Wer eine
    der beiden zurückdreht, macht ``spritzigkeit`` wieder wirkungslos,
    und dieser Test sagt es sofort.
    """
    from ultrasim.core.engine import RaceConfig, simulate_race

    steep = _with_steep_ramps(route)
    assert steep.grade.max() > st.ANAEROBIC_FULL_GRADE, "die Testrampe ist nicht steil genug"

    teams, riders = generate_pool(8, n_teams=2, seed=77)
    result = simulate_race(steep, riders, teams, RaceConfig(seed=2024))
    values = result.telemetry.wprime_pct.astype(np.float64)[result.telemetry.state == 0]
    assert values.size, "ohne fahrende Fahrer sagt der Test nichts"
    assert values.min() < 90.0, "W′ entlädt sich nirgends — der Rampenterm greift nicht"
    assert values.min() > 5.0, "W′ läuft leer, statt vom Wächter gebremst zu werden"


def test_a_route_without_ramps_leaves_w_prime_alone(route):
    """Die Kehrseite: Ohne Steilstück darf nichts anaerob werden.

    Sonst wäre der Rampenterm ein verkappter Grundbonus für alle.
    """
    from ultrasim.core.engine import RaceConfig, simulate_race

    assert route.grade.max() < st.ANAEROBIC_ONSET_GRADE + 0.02
    teams, riders = generate_pool(8, n_teams=2, seed=77)
    result = simulate_race(route, riders, teams, RaceConfig(seed=2024))
    values = result.telemetry.wprime_pct.astype(np.float64)[result.telemetry.state == 0]
    # Nicht 100 %: Ein Fahrer im Zeitfahrrad mahlt auch an einem
    # Neunprozenter, und das zieht über die abgesenkte Schwelle etwas
    # W′. Das ist der zweite, leisere Weg in den anaeroben Bereich und
    # gewollt. Verboten ist die *tiefe* Entladung ohne Steilrampe.
    # Die Grenze ist bewusst weit: Geprüft wird „keine tiefe Entladung",
    # nicht ein bestimmter Wert. Sie stand bei 85 und ist beim Wechsel auf
    # getrennte Zufallsströme exakt getroffen worden — eine Schranke, die
    # ein anderes Feld punktgenau berührt, misst die Feldzusammensetzung
    # und nicht die Mechanik.
    assert values.min() > 80.0
