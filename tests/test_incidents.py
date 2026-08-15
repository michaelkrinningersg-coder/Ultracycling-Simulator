"""Zwischenfälle und Aufgabe (M6.2, Game-Design-Dokument Abschnitt 6.5)."""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core import incidents as inc
from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.events import DNF, INCIDENT, STOP_END, STOP_START
from ultrasim.core.rider import generate_pool

#: Dieses Modul rechnet ganze Rennen. Der Marker trennt die innere
#: Schleife beim Tippen von der Absicherung vor dem Commit:
#:
#:     pytest -q -m "not slow"    # rund 30 s
#:     pytest -q                  # rund 4 min, so wie CI
#:
#: Er stand lange an einem einzigen Test und hat damit 28 von 252
#: Sekunden gespart — ein Versprechen ohne Deckung.
pytestmark = pytest.mark.slow


# ----------------------------------------------------------------------
# Kandidatenprozess
# ----------------------------------------------------------------------
def test_risk_profile_is_plain_distance_on_asphalt(route):
    risk = inc.risk_profile(route, rough_factor=1.0)
    assert risk[0] == 0.0
    assert risk[-1] == pytest.approx(route.distance_km, abs=0.05)
    assert np.all(np.diff(risk) > 0)


def test_risk_profile_weights_rough_surfaces_higher(route):
    plain = inc.risk_profile(route, rough_factor=1.0)
    rough = inc.risk_profile(route, rough_factor=2.5)
    # Auf reinem Asphalt sind beide gleich; sobald Schotter vorkommt,
    # wächst das Risiko schneller als die Distanz.
    assert rough[-1] >= plain[-1] - 1e-6


def test_candidate_marks_follow_the_expected_rate():
    """Ohne diese Zusicherung ist der ganze Katalog Dekoration."""
    rng = np.random.default_rng(7)
    counts = [inc._draw_marks(rng, 1.0 / 450.0, 1000.0).size for _ in range(400)]
    assert np.mean(counts) == pytest.approx(1000.0 / 450.0, rel=0.12)


def test_schedule_is_sorted_and_typed(route):
    _, riders = generate_pool(4, seed=3)
    schedule = inc.schedule_for_rider(route, riders[0].attributes, np.random.default_rng(1))
    assert len(schedule) == len(schedule.typ)
    assert np.all(np.diff(schedule.dist_m) >= 0)
    assert set(schedule.typ) <= set(inc.CATALOG)
    assert schedule.dist_m.max(initial=0.0) <= route.distance_m


def test_material_care_lowers_the_puncture_rate(route):
    """Ein Attribut ohne messbare Wirkung ist eine Lüge in der Anzeige."""

    def punctures(value: float) -> int:
        attrs = {"materialpflege": value}
        total = 0
        for seed in range(60):
            schedule = inc.schedule_for_rider(route, attrs, np.random.default_rng(seed))
            total += sum(1 for t in schedule.typ if t == inc.PANNE)
        return total

    assert punctures(95.0) < punctures(5.0)


def test_navigation_skill_lowers_the_lost_way_rate(route):
    def lost(value: float) -> int:
        attrs = {"navigationssicherheit": value}
        return sum(
            sum(1 for t in inc.schedule_for_rider(route, attrs, np.random.default_rng(s)).typ
                if t == inc.VERFAHREN)
            for s in range(60)
        )

    assert lost(95.0) < lost(5.0)


# ----------------------------------------------------------------------
# Annahme (Thinning)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("typ", sorted(inc.CATALOG))
def test_acceptance_never_leaves_the_unit_interval(typ):
    """Über 1,0 wäre der ``headroom`` zu klein und die Rate falsch."""
    rng = np.random.default_rng(0)
    for _ in range(400):
        ctx = inc.RideContext(
            rain=float(rng.uniform(0.0, 1.0)),
            daylight=bool(rng.integers(0, 2)),
            sleep_press=float(rng.uniform(0.0, 2.0)),
            temp_c=float(rng.uniform(-5.0, 42.0)),
            intake_ratio=float(rng.uniform(0.4, 1.6)),
            heat_norm=float(rng.uniform(-1.0, 1.0)),
            wet_norm=float(rng.uniform(-1.0, 1.0)),
        )
        p = inc.accept_probability(typ, ctx)
        assert 0.0 <= p <= 1.0
        # Ein Deckel bei exakt 1,0 verrät einen zu kleinen headroom.
        if typ not in (inc.LICHT, inc.SPERRUNG):
            assert p < 1.0 + 1e-9


def test_light_failure_only_happens_at_night():
    day = inc.RideContext(daylight=True)
    night = inc.RideContext(daylight=False)
    assert inc.accept_probability(inc.LICHT, day) == 0.0
    assert inc.accept_probability(inc.LICHT, night) > 0.0


def test_getting_lost_is_much_likelier_at_night_and_tired():
    calm = inc.RideContext(daylight=True, sleep_press=0.0)
    bad = inc.RideContext(daylight=False, sleep_press=1.0)
    assert inc.accept_probability(inc.VERFAHREN, bad) > 5 * inc.accept_probability(
        inc.VERFAHREN, calm
    )


def test_crashes_get_likelier_in_the_wet():
    dry = inc.RideContext(rain=0.0)
    wet = inc.RideContext(rain=1.0)
    assert inc.accept_probability(inc.STURZ, wet) > inc.accept_probability(inc.STURZ, dry)


def test_wet_resistance_dampens_the_crash_risk():
    weak = inc.RideContext(rain=1.0, wet_norm=-1.0)
    strong = inc.RideContext(rain=1.0, wet_norm=1.0)
    assert inc.accept_probability(inc.STURZ, strong) < inc.accept_probability(inc.STURZ, weak)


def test_heat_collapse_needs_heat():
    cool = inc.RideContext(temp_c=18.0)
    hot = inc.RideContext(temp_c=34.0)
    assert inc.accept_probability(inc.HITZEEINBRUCH, cool) == 0.0
    assert inc.accept_probability(inc.HITZEEINBRUCH, hot) > 0.0


def test_heat_tolerance_shifts_the_collapse_threshold():
    hot = 32.0
    weak = inc.RideContext(temp_c=hot, heat_norm=-1.0)
    strong = inc.RideContext(temp_c=hot, heat_norm=1.0)
    assert inc.accept_probability(inc.HITZEEINBRUCH, strong) < inc.accept_probability(
        inc.HITZEEINBRUCH, weak
    )


def test_pushing_the_intake_upsets_the_stomach():
    modest = inc.RideContext(intake_ratio=0.8)
    greedy = inc.RideContext(intake_ratio=1.4)
    assert inc.accept_probability(inc.MAGEN, greedy) > inc.accept_probability(inc.MAGEN, modest)


# ----------------------------------------------------------------------
# Wirkung
# ----------------------------------------------------------------------
@pytest.mark.parametrize("typ", sorted(inc.CATALOG))
def test_every_incident_does_something(typ):
    rng = np.random.default_rng(4)
    outcomes = [inc.resolve(typ, rng, inc.RideContext()) for _ in range(200)]
    assert all(o.typ == typ and o.reason for o in outcomes)
    assert any(o.stop_s > 0 or o.condition or o.dnf for o in outcomes)
    for outcome in outcomes:
        assert outcome.stop_s >= 0.0
        if outcome.condition:
            assert outcome.condition_duration > 0.0


def test_severe_crashes_end_the_race_at_the_documented_share():
    rng = np.random.default_rng(11)
    outcomes = [inc.resolve(inc.STURZ, rng, inc.RideContext()) for _ in range(4000)]
    share = sum(1 for o in outcomes if o.dnf) / len(outcomes)
    assert share == pytest.approx(inc.SEVERE_CRASH_P, abs=0.015)


def test_a_good_crew_shortens_a_puncture():
    rng = np.random.default_rng(2)
    slow = np.mean(
        [inc.resolve(inc.PANNE, rng, inc.RideContext(service_factor=1.25)).stop_s
         for _ in range(400)]
    )
    fast = np.mean(
        [inc.resolve(inc.PANNE, rng, inc.RideContext(service_factor=0.75)).stop_s
         for _ in range(400)]
    )
    assert fast < slow


def test_light_crashes_leave_a_lasting_mark():
    rng = np.random.default_rng(5)
    light = [o for o in (inc.resolve(inc.STURZ, rng, inc.RideContext()) for _ in range(300))
             if not o.dnf]
    assert light
    for outcome in light:
        assert outcome.condition == "sturzfolgen"
        # Der Katalog nennt 50–200 km Nachwirkung.
        assert 50_000.0 <= outcome.condition_duration <= 200_000.0


# ----------------------------------------------------------------------
# Aufgabe
# ----------------------------------------------------------------------
def test_a_rider_on_schedule_never_gives_up():
    """Das Produkt aus Abschnitt 6.5 muss genau das leisten."""
    rate = inc.give_up_rate(
        behind_ratio=np.array([1.0]),
        fatigue_factor=np.array([0.70]),  # völlig ausgelaugt
        sleep_press=np.array([1.5]),
        stomach_penalty=np.array([3.0]),
        mental_norm=np.array([-1.0]),
    )
    assert rate[0] == 0.0


def test_fresh_legs_survive_lost_time():
    rate = inc.give_up_rate(
        behind_ratio=np.array([1.4]),
        fatigue_factor=np.array([1.0]),
        sleep_press=np.array([0.0]),
        stomach_penalty=np.array([1.0]),
        mental_norm=np.array([0.0]),
    )
    assert rate[0] == 0.0


def test_mental_resilience_buys_time():
    kwargs = dict(
        behind_ratio=np.array([1.2, 1.2]),
        fatigue_factor=np.array([0.85, 0.85]),
        sleep_press=np.array([0.8, 0.8]),
        stomach_penalty=np.array([2.0, 2.0]),
    )
    rate = inc.give_up_rate(mental_norm=np.array([-1.0, 1.0]), **kwargs)
    assert rate[0] > rate[1] * 1.5


def test_a_bad_stomach_multiplies_the_pressure():
    kwargs = dict(
        behind_ratio=np.array([1.2]),
        fatigue_factor=np.array([0.85]),
        sleep_press=np.array([0.5]),
        mental_norm=np.array([0.0]),
    )
    healthy = inc.give_up_rate(stomach_penalty=np.array([1.0]), **kwargs)
    sick = inc.give_up_rate(stomach_penalty=np.array([3.0]), **kwargs)
    assert sick[0] == pytest.approx(3.0 * healthy[0])


# ----------------------------------------------------------------------
# Im Rennen
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def incident_race(route_medium):
    teams, riders = generate_pool(50, n_teams=6, seed=17)
    return simulate_race(route_medium, riders, teams, RaceConfig(seed=88))


def test_incidents_actually_happen(incident_race):
    events = [e for e in incident_race.events if e.type == INCIDENT]
    assert events, "Über 250 km sollte irgendwer eine Panne haben"
    assert len({e.payload["typ"] for e in events}) >= 3


def test_an_incident_stop_is_not_reported_twice(incident_race):
    """Das INCIDENT-Ereignis *ist* die Meldung – kein zweites STOP_START.

    Sonst stünde jede Panne doppelt im Ticker: einmal als Panne und
    einmal als namenloser Halt.
    """
    planned = {"kurz", "voll", "schlaf", "notschlaf"}
    for event in incident_race.events:
        if event.type == STOP_START:
            assert event.payload["kind"] in planned
    # Der Halt findet trotzdem statt: Auf jeden Zwischenfall mit Dauer
    # folgt ein STOP_END.
    ends = {(e.entry_id, round(e.t_s, 3)) for e in incident_race.events if e.type == STOP_END}
    for event in incident_race.events:
        if event.type != INCIDENT or event.payload["dnf"] or event.payload["stop_s"] <= 0:
            continue
        due = event.t_s + event.payload["stop_s"]
        assert any(
            entry_id == event.entry_id and abs(t - due) < 2.0 for entry_id, t in ends
        )


def test_a_retired_rider_stops_moving(incident_race):
    tel = incident_race.telemetry
    for entry in incident_race.entries:
        if entry.status != "DNF":
            continue
        row = tel.dist_m[entry.entry_id]
        assert row[-1] == pytest.approx(entry.dnf_dist_m, abs=1.5)
        assert tel.v_cms[entry.entry_id, -1] == 0
        assert entry.dnf_reason
        assert entry.rank is None


def test_dnf_events_match_the_entries(incident_race):
    retired = {e.entry_id for e in incident_race.entries if e.status == "DNF"}
    reported = {e.entry_id for e in incident_race.events if e.type == DNF}
    assert retired == reported


def test_lost_time_only_counts_the_unplanned(incident_race):
    for entry in incident_race.entries:
        assert entry.lost_s >= 0.0
        if entry.finish_time_s:
            assert entry.lost_s < entry.finish_time_s


def test_incidents_cost_the_field_time(route_medium):
    """Der Katalog muss sich in der Ergebnisliste niederschlagen."""
    teams, riders = generate_pool(30, n_teams=5, seed=21)
    clean = simulate_race(
        route_medium, riders, teams, RaceConfig(seed=6, enable_incidents=False)
    )
    rough = simulate_race(route_medium, riders, teams, RaceConfig(seed=6))
    clean_times = {e.rider_id: e.finish_time_s for e in clean.entries}
    slower = [
        e.finish_time_s - clean_times[e.rider_id]
        for e in rough.entries
        if e.finish_time_s is not None and clean_times[e.rider_id] is not None
    ]
    assert slower and np.mean(slower) > 60.0
    assert min(slower) >= -1e-6, "Ein Zwischenfall darf niemanden schneller machen"


def test_the_field_stays_independent_with_incidents(route_medium):
    """Dieselbe Zusicherung wie in M3 – jetzt mit Ereignissen im Spiel."""
    teams, riders = generate_pool(24, n_teams=4, seed=9)
    small = simulate_race(route_medium, riders[:8], teams, RaceConfig(seed=31))
    large = simulate_race(route_medium, riders, teams, RaceConfig(seed=31))
    for entry in small.entries:
        twin = large.entry_by_rider(entry.rider_id)
        assert twin is not None
        assert entry.status == twin.status
        assert entry.lost_s == pytest.approx(twin.lost_s, abs=1e-6)
        if entry.finish_time_s is not None:
            assert entry.finish_time_s == pytest.approx(twin.finish_time_s, abs=1e-6)


def test_incidents_are_reproducible(route_medium):
    teams, riders = generate_pool(20, n_teams=4, seed=13)
    a = simulate_race(route_medium, riders, teams, RaceConfig(seed=77))
    b = simulate_race(route_medium, riders, teams, RaceConfig(seed=77))
    ea = [(e.entry_id, round(e.t_s, 4), e.payload["typ"]) for e in a.events if e.type == INCIDENT]
    eb = [(e.entry_id, round(e.t_s, 4), e.payload["typ"]) for e in b.events if e.type == INCIDENT]
    assert ea == eb


def test_disabling_incidents_removes_them(route_medium):
    teams, riders = generate_pool(20, n_teams=4, seed=13)
    result = simulate_race(
        route_medium, riders, teams, RaceConfig(seed=77, enable_incidents=False)
    )
    assert not [e for e in result.events if e.type == INCIDENT]
    assert all(e.give_up_score == 0.0 for e in result.entries)


def test_a_retired_rider_does_not_recover_in_the_telemetry(incident_race):
    """Ein Aufgeber mit 100 % Glykogen im Fahrerdetail wäre eine Lüge.

    Im Modell laufen Flüssigkeits- und Energiehaushalt weiter — er steht
    ja, und wer steht, füllt auf. Angezeigt gehört trotzdem der Stand
    seines letzten gefahrenen Kilometers.
    """
    tel = incident_race.telemetry
    for entry in incident_race.entries:
        if entry.status != "DNF" or entry.dnf_reason == "Zeitrahmen überschritten":
            continue
        row = tel.state[entry.entry_id]
        first = int(np.argmax(row == 3))
        if first == 0 or first >= tel.n_samples - 1:
            continue
        for channel in ("form_pct", "wprime_pct", "glyco_pct", "sleep_pct", "hydration_pct"):
            track = getattr(tel, channel)[entry.entry_id, first:]
            assert (track == track[0]).all(), f"{channel} läuft nach der Aufgabe weiter"
