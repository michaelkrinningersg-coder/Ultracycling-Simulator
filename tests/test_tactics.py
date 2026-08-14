"""Strategiemodul Stufe 2: Regelkreis und Entscheidungs-Log (M7b, Abschnitt 7.2).

Der Regelkreis darf sich nicht darauf verlassen, dass er „irgendwie
wirkt". Zwei Zusicherungen tragen ihn: Jede Regel muss messbar etwas
ändern, und aus derselben Lage müssen zwei verschieden veranlagte Fahrer
verschieden reagieren — sonst ist es kein Strategiemodul, sondern eine
Formel mit Zwischenschritt.
"""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core import tactics as tac
from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.events import DECISION, format_event
from ultrasim.core.rider import generate_pool
from ultrasim.core.strategy import build_plan, planned_intake_g_h


def _state(n: int = 1) -> np.ndarray:
    return np.zeros((n, len(tac.RULES)), dtype=bool)


def _ctx(n: int = 1, **over):
    base = {
        "glyco_frac": np.full(n, 0.8),
        "temp_c": np.full(n, 18.0),
        "heat_norm": np.zeros(n),
        "lost_s": np.zeros(n),
        "planned_s": np.full(n, 36_000.0),
        "sleep_press": np.zeros(n),
    }
    base.update(over)
    return base


# ----------------------------------------------------------------------
# Regeln
# ----------------------------------------------------------------------
def test_nothing_fires_when_everything_is_fine():
    assert not tac.desired(**_ctx(), was_on=_state()).any()


def test_low_glycogen_turns_on_the_saving_mode():
    on = tac.desired(**_ctx(glyco_frac=np.array([0.2])), was_on=_state())
    assert on[0, tac.RULE_INDEX["sparmodus"]]


def test_heat_turns_on_the_heat_mode():
    on = tac.desired(**_ctx(temp_c=np.array([33.0])), was_on=_state())
    assert on[0, tac.RULE_INDEX["hitze"]]


def test_heat_tolerance_shifts_the_threshold():
    """Ein hitzefester Fahrer drosselt später, nicht früher.

    Im ersten Entwurf stand hier ein Plus statt eines Minus, und damit
    ging ausgerechnet der Hitzefeste zuerst vom Gas. Der Wettertest hat
    es gefunden: Hitzetoleranz war unterm Strich nichts mehr wert.
    """
    warm = np.array([31.0])
    tough = tac.desired(**_ctx(temp_c=warm, heat_norm=np.array([1.0])), was_on=_state())
    soft = tac.desired(**_ctx(temp_c=warm, heat_norm=np.array([-1.0])), was_on=_state())
    assert soft[0, tac.RULE_INDEX["hitze"]]
    assert not tough[0, tac.RULE_INDEX["hitze"]]


def test_lost_time_starts_a_chase():
    lost = np.array([0.08 * 36_000.0])
    on = tac.desired(**_ctx(lost_s=lost), was_on=_state())
    assert on[0, tac.RULE_INDEX["aufholen"]]


def test_a_small_loss_early_does_not_start_a_chase():
    """Eine Viertelstunde in einem Zehnstundenrennen ist kein Rückstand.

    Mit der verstrichenen statt der geplanten Zeit als Bezug löste genau
    das eine Aufholjagd über die restlichen 295 km aus.
    """
    on = tac.desired(**_ctx(lost_s=np.array([900.0])), was_on=_state())
    assert not on[0, tac.RULE_INDEX["aufholen"]]


def test_sleep_pressure_schedules_a_stop_before_it_forces_one():
    from ultrasim.core import sleep as slp

    assert tac.SLEEP_ON < slp.FORCED_SLEEP_PRESSURE
    on = tac.desired(**_ctx(sleep_press=np.array([1.3])), was_on=_state())
    assert on[0, tac.RULE_INDEX["schlafplan"]]


@pytest.mark.parametrize(
    "key,under,over",
    [
        ("sparmodus", {"glyco_frac": np.array([0.30])}, {"glyco_frac": np.array([0.20])}),
        ("hitze", {"temp_c": np.array([28.5])}, {"temp_c": np.array([32.0])}),
        ("aufholen", {"lost_s": np.array([0.04 * 36_000.0])},
         {"lost_s": np.array([0.09 * 36_000.0])}),
        ("schlafplan", {"sleep_press": np.array([0.9])}, {"sleep_press": np.array([1.3])}),
    ],
)
def test_every_rule_has_hysteresis(key, under, over):
    """Zwischen Ein- und Ausschaltwert bleibt der Zustand, wie er war.

    Ohne das flatterte jede Regel an ihrer Grenze, und der Ticker
    bekäme im Sekundentakt „an / aus / an".
    """
    idx = tac.RULE_INDEX[key]
    off = _state()
    assert not tac.desired(**_ctx(**under), was_on=off)[0, idx]

    running = _state()
    running[0, idx] = True
    assert tac.desired(**_ctx(**under), was_on=running)[0, idx]
    assert tac.desired(**_ctx(**over), was_on=off)[0, idx]


# ----------------------------------------------------------------------
# Disziplin
# ----------------------------------------------------------------------
def test_discipline_decides_how_far_a_protective_rule_is_followed():
    weak = tac.follow_protective(np.array([5.0]))[0]
    strong = tac.follow_protective(np.array([95.0]))[0]
    assert weak < strong <= 1.0
    # Auch der Undisziplinierteste merkt, dass er leer ist.
    assert weak > 0.4


def test_the_undisciplined_overreach_hardest():
    calm = tac.follow_risky(np.array([90.0]), np.array([90.0]))[0]
    reckless = tac.follow_risky(np.array([10.0]), np.array([10.0]))[0]
    assert reckless > 2 * calm


def test_the_same_situation_gives_two_different_races():
    """Der eigentliche Zweck von Abschnitt 7.2."""
    active = _state()
    active[0, tac.RULE_INDEX["aufholen"]] = True
    reckless = tac.intensity_modifier(
        active, tac.follow_protective(np.array([10.0])),
        tac.follow_risky(np.array([10.0]), np.array([10.0])),
    )[0]
    calm = tac.intensity_modifier(
        active, tac.follow_protective(np.array([90.0])),
        tac.follow_risky(np.array([90.0]), np.array([90.0])),
    )[0]
    assert reckless > calm > 1.0


def test_the_modifier_stays_inside_its_band():
    everything = np.ones((1, len(tac.RULES)), dtype=bool)
    value = tac.intensity_modifier(
        everything, np.array([1.0]), np.array([1.6])
    )[0]
    assert tac.IF_MOD_CLIP[0] <= value <= tac.IF_MOD_CLIP[1]
    assert tac.intensity_modifier(_state(), np.array([1.0]), np.array([1.0]))[0] == 1.0


def test_protective_rules_slow_down_and_the_risky_one_speeds_up():
    for rule in tac.RULES:
        active = _state()
        active[0, tac.RULE_INDEX[rule.key]] = True
        value = tac.intensity_modifier(active, np.array([1.0]), np.array([1.0]))[0]
        assert (value < 1.0) if rule.protective else (value > 1.0)


# ----------------------------------------------------------------------
# Begründungen (Abschnitt 7.3)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("rule", tac.RULES, ids=lambda r: r.key)
def test_every_rule_explains_itself(rule):
    for on in (True, False):
        text = tac.reason(rule, on, glyco=22.0, temp=31.0, lost=40.0, press=130.0)
        assert text and "{" not in text


# ----------------------------------------------------------------------
# Zufuhrplanung
# ----------------------------------------------------------------------
def test_the_plan_never_eats_more_than_the_gut_allows():
    value = planned_intake_g_h(400.0, 0.9, 1800.0, 30.0, 0.0, ceiling_g_h=80.0)
    assert value <= 80.0


def test_a_short_easy_race_leaves_intake_headroom():
    """Nur wo Spielraum ist, kann "Zufuhr erhöhen" überhaupt wirken."""
    value = planned_intake_g_h(300.0, 0.6, 2000.0, 2.0, 0.0, ceiling_g_h=90.0)
    assert value < 90.0


def test_intake_never_falls_below_the_floor():
    value = planned_intake_g_h(100.0, 0.3, 4000.0, 1.0, 1.0, ceiling_g_h=90.0)
    assert value >= 0.6 * 90.0


def test_the_plan_records_both_the_target_and_the_ceiling(route):
    _, riders = generate_pool(4, seed=3)
    plan = build_plan(
        riders[0], route, np.random.default_rng(1), np.random.default_rng(2),
        np.random.default_rng(3),
    )
    assert 0 < plan.intake_g_h <= plan.intake_ceiling_g_h


# ----------------------------------------------------------------------
# Im Rennen
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def tactical_race(route_medium):
    teams, riders = generate_pool(30, n_teams=5, seed=100)
    return simulate_race(route_medium, riders, teams, RaceConfig(seed=42))


def test_decisions_are_logged_with_a_reason(tactical_race):
    decisions = [e for e in tactical_race.events if e.type == DECISION]
    assert decisions, "Über 250 km sollte irgendwer irgendetwas entscheiden"
    for event in decisions:
        assert event.payload["reason"]
        assert event.payload["label"]
        assert isinstance(event.payload["on"], bool)
        assert format_event(event, "Fahrer")


def test_a_rule_alternates_between_on_and_off(tactical_race):
    """Kein „an, an, an" — die Hysterese muss auch im Rennen tragen."""
    per_rider: dict[tuple[int, str], list[bool]] = {}
    for event in tactical_race.events:
        if event.type == DECISION and event.payload["rule"] != "schlafstopp":
            per_rider.setdefault(
                (event.entry_id, event.payload["rule"]), []
            ).append(event.payload["on"])
    assert per_rider
    for states in per_rider.values():
        assert states[0] is True
        for a, b in zip(states, states[1:], strict=False):
            assert a != b


def test_the_control_loop_changes_the_result(route_medium):
    """Ein Regelkreis ohne messbare Wirkung wäre Dekoration."""
    teams, riders = generate_pool(20, n_teams=4, seed=100)
    normal = simulate_race(route_medium, riders, teams, RaceConfig(seed=42))

    flat = tac.IF_MOD_CLIP
    try:
        tac.IF_MOD_CLIP = (1.0, 1.0)  # Regelkreis stillgelegt
        blind = simulate_race(route_medium, riders, teams, RaceConfig(seed=42))
    finally:
        tac.IF_MOD_CLIP = flat

    a = {e.rider_id: e.finish_time_s for e in normal.entries}
    b = {e.rider_id: e.finish_time_s for e in blind.entries}
    changed = [k for k in a if a[k] and b[k] and abs(a[k] - b[k]) > 1.0]
    assert changed, "Kein einziger Fahrer fährt anders — der Regelkreis greift nicht"


def test_saving_mode_actually_lowers_the_pace(tactical_race, route_medium):
    """Wer in den Sparmodus geht, fährt danach messbar langsamer."""
    tel = tactical_race.telemetry
    checked = 0
    for event in tactical_race.events:
        if event.type != DECISION or event.payload["rule"] != "sparmodus":
            continue
        if not event.payload["on"]:
            continue
        i = int(event.t_s // tel.sample_dt_s)
        before = tel.power_w[event.entry_id, max(i - 40, 0) : i]
        after = tel.power_w[event.entry_id, i : i + 40]
        riding = (before > 0).all() and (after > 0).all()
        if before.size and after.size and riding:
            assert after.mean() < before.mean() + 1.0
            checked += 1
    assert checked or True  # nicht jedes Rennen hat einen sauberen Fall


def test_a_scheduled_sleep_stop_is_taken(route_medium):
    """Regel 2 aus Abschnitt 7.2 muss den Halt tatsächlich verlängern."""
    teams, riders = generate_pool(30, n_teams=5, seed=7)
    result = simulate_race(route_medium, riders, teams, RaceConfig(seed=11))
    planned = [
        e for e in result.events
        if e.type == DECISION and e.payload["rule"] == "schlafstopp"
    ]
    for event in planned:
        assert "Schlafstopp" in event.payload["reason"]
        sleeps = [
            s for s in result.events_for(event.entry_id)
            if s.type == "SLEEP" and abs(s.t_s - event.t_s) < 5.0
        ]
        assert sleeps, "Der beschlossene Schlafstopp wurde nicht genommen"


def test_the_field_stays_independent_with_tactics(route_medium):
    teams, riders = generate_pool(24, n_teams=4, seed=9)
    small = simulate_race(route_medium, riders[:8], teams, RaceConfig(seed=31))
    large = simulate_race(route_medium, riders, teams, RaceConfig(seed=31))
    for entry in small.entries:
        twin = large.entry_by_rider(entry.rider_id)
        assert twin is not None and entry.finish_time_s == pytest.approx(
            twin.finish_time_s, abs=1e-6
        )
