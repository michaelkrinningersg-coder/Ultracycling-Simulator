"""Tests des Zustandssystems (Abschnitt 6.5) und der Fehlplanung."""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core import conditions as cond
from ultrasim.core import strategy as st
from ultrasim.core.engine import RaceConfig, RiderStreams, simulate_race
from ultrasim.core.events import CONDITION_END, CONDITION_START
from ultrasim.core.rider import Rider, generate_pool, generate_rider


def _store(n: int = 4) -> cond.ConditionStore:
    return cond.ConditionStore(n)


def _dist(n: int = 4, value: float = 0.0) -> np.ndarray:
    return np.full(n, value)


# ----------------------------------------------------------------------
# Katalog
# ----------------------------------------------------------------------
def test_catalog_entries_are_wellformed():
    for key, spec in cond.CATALOG.items():
        assert spec.typ == key
        assert spec.label
        assert spec.effects, "Ein Zustand ohne Wirkung ist keiner"
        assert spec.anchor in (cond.ANCHOR_TIME, cond.ANCHOR_DIST)
        assert spec.decay in (cond.DECAY_STEP, cond.DECAY_LINEAR)
        row = spec.effect_row()
        assert row.shape == (len(cond.CHANNELS),)
        assert np.all(row > 0.0)


def test_unknown_channel_is_rejected():
    spec = cond.ConditionSpec("x", "X", {"gibtsnicht": 0.5})
    with pytest.raises(KeyError):
        spec.effect_row()


# ----------------------------------------------------------------------
# Wirkung
# ----------------------------------------------------------------------
def test_no_conditions_means_no_effect():
    store = _store()
    mods = store.update(0.0, _dist())
    assert np.all(mods == 1.0)


def test_time_anchored_condition_applies_and_expires():
    store = _store()
    store.add(1, cond.CATALOG["hitze"], t_s=100.0, dist_m=0.0, duration=600.0)

    assert cond.channel(store.update(200.0, _dist()), "ftp")[1] == pytest.approx(0.90)
    # andere Fahrer bleiben unberührt
    assert cond.channel(store.update(200.0, _dist()), "ftp")[0] == 1.0
    # nach Ablauf wieder neutral
    store.expire(701.0, _dist())
    assert np.all(store.update(701.0, _dist()) == 1.0)


def test_distance_anchored_condition_follows_the_rider():
    store = _store()
    store.add(2, cond.CATALOG["ersatzrad"], t_s=0.0, dist_m=1000.0, duration=5000.0)
    dist = _dist()
    dist[2] = 3000.0
    assert cond.channel(store.update(0.0, dist), "crr")[2] == pytest.approx(1.12)
    dist[2] = 6001.0
    store.expire(0.0, dist)
    assert cond.channel(store.update(0.0, dist), "crr")[2] == pytest.approx(1.0)


def test_linear_decay_fades_back_to_neutral():
    store = _store()
    store.add(0, cond.CATALOG["fehlplanung"], t_s=0.0, dist_m=0.0, duration=1000.0)
    dist = _dist()

    start = cond.channel(store.update(0.0, dist), "ftp")[0]
    dist[0] = 500.0
    middle = cond.channel(store.update(0.0, dist), "ftp")[0]
    dist[0] = 900.0
    late = cond.channel(store.update(0.0, dist), "ftp")[0]

    assert start == pytest.approx(0.92)
    assert middle == pytest.approx(0.96, abs=0.005)
    assert late > middle > start


def test_step_decay_stays_constant_while_active():
    store = _store()
    store.add(0, cond.CATALOG["hitze"], t_s=0.0, dist_m=0.0, duration=1000.0)
    early = cond.channel(store.update(10.0, _dist()), "ftp")[0]
    late = cond.channel(store.update(950.0, _dist()), "ftp")[0]
    assert early == pytest.approx(late) == pytest.approx(0.90)


def test_conditions_multiply():
    """Alle aktiven Zustände eines Fahrers werden multipliziert."""
    store = _store()
    store.add(0, cond.CATALOG["hitze"], t_s=0.0, dist_m=0.0, duration=1000.0)  # 0.90
    store.add(0, cond.CATALOG["magen"], t_s=0.0, dist_m=0.0, duration=1000.0)  # 0.97
    ftp = cond.channel(store.update(0.0, _dist()), "ftp")[0]
    assert ftp == pytest.approx(0.90 * 0.97, rel=1e-6)


def test_strength_scales_the_deviation_not_the_value():
    store = _store()
    store.add(0, cond.CATALOG["hitze"], t_s=0.0, dist_m=0.0, duration=100.0, strength=0.5)
    assert cond.channel(store.update(0.0, _dist()), "ftp")[0] == pytest.approx(0.95)
    store2 = _store()
    store2.add(0, cond.CATALOG["hitze"], t_s=0.0, dist_m=0.0, duration=100.0, strength=0.0)
    assert cond.channel(store2.update(0.0, _dist()), "ftp")[0] == pytest.approx(1.0)


def test_expiring_the_last_condition_resets_the_modifiers():
    """Sonst friert der letzte Stand für den Rest des Rennens ein.

    Und zwar unterschiedlich, je nachdem wie viele andere Fahrer gerade
    Zustände haben – womit das Ergebnis eines Fahrers plötzlich von der
    Startliste abhinge.
    """
    store = _store()
    store.add(0, cond.CATALOG["hitze"], t_s=0.0, dist_m=0.0, duration=100.0)
    assert cond.channel(store.update(50.0, _dist()), "ftp")[0] < 1.0
    store.expire(200.0, _dist())
    assert store.active_count == 0
    assert np.all(store.update(200.0, _dist()) == 1.0)


def test_records_carry_both_axes():
    """Der Balken über dem Profil braucht km, der Ticker braucht die Zeit."""
    store = _store()
    store.add(0, cond.CATALOG["fehlplanung"], t_s=3600.0, dist_m=50_000.0, duration=20_000.0)
    dist = _dist()
    dist[0] = 71_000.0
    finished = store.expire(9000.0, dist)
    assert len(finished) == 1
    record = finished[0]
    assert record.start_t_s == 3600.0
    assert record.start_dist_m == 50_000.0
    assert record.end_dist_m == pytest.approx(70_000.0)
    assert record.end_t_s == 9000.0  # aus der Zeitachse nachgetragen


def test_close_all_cuts_records_off_at_the_end_of_the_race():
    """Ein Zustand endet spätestens mit dem Rennen des Fahrers.

    Sein geplantes Ende darf weit dahinter liegen – ein Magenproblem mit
    vier Stunden Nachwirkung, das jemanden auf den letzten zwanzig
    Kilometern erwischt, ist so ein Fall. Der Datensatz muss trotzdem im
    Rennen enden, sonst zeigt jede Auswertung Zustände nach dem Ziel.
    """
    store = _store()
    store.add(0, cond.CATALOG["magen"], t_s=100.0, dist_m=1000.0, duration=1e9)
    store.close_all(500.0, _dist(4, 2000.0))
    assert store.active_count == 0
    record = store.records[0]
    assert record.end_t_s == pytest.approx(500.0)
    assert record.end_dist_m == pytest.approx(2000.0)


def test_close_all_takes_a_finish_time_per_rider():
    """Ein Zustand endet, wenn *dieser* Fahrer fertig ist."""
    store = _store()
    store.add(0, cond.CATALOG["magen"], t_s=0.0, dist_m=0.0, duration=1e9)
    store.add(1, cond.CATALOG["magen"], t_s=0.0, dist_m=0.0, duration=1e9)
    store.close_all(np.array([300.0, 900.0, 900.0, 900.0]), _dist(4, 2000.0))
    assert store.records[0].end_t_s == pytest.approx(300.0)
    assert store.records[1].end_t_s == pytest.approx(900.0)


def test_store_scales_to_a_full_field():
    """Der Kostenpunkt ist die Zahl der Zustände, nicht die der Fahrer."""
    store = cond.ConditionStore(250)
    for i in range(250):
        store.add(i, cond.CATALOG["fehlplanung"], t_s=0.0, dist_m=0.0, duration=100_000.0)
    mods = store.update(0.0, np.zeros(250))
    assert mods.shape == (250, len(cond.CHANNELS))
    assert np.allclose(cond.channel(mods, "ftp"), 0.92)


# ----------------------------------------------------------------------
# Zufallsströme
# ----------------------------------------------------------------------
def test_streams_are_independent_per_purpose():
    """Eine neue Mechanik darf bestehende Ziehungen nicht verschieben."""
    a = RiderStreams(seed=7, rider_id=3)
    b = RiderStreams(seed=7, rider_id=3)
    # b zieht erst aus einem anderen Strom – das darf 'plan' nicht ändern
    b.get("misjudge").random(50)
    assert a.get("plan").random() == b.get("plan").random()


def test_streams_differ_between_riders_and_seeds():
    assert RiderStreams(1, 1).get("plan").random() != RiderStreams(1, 2).get("plan").random()
    assert RiderStreams(1, 1).get("plan").random() != RiderStreams(2, 1).get("plan").random()


def test_unknown_stream_is_rejected():
    with pytest.raises(KeyError):
        RiderStreams(1, 1).get("telepathie")


# ----------------------------------------------------------------------
# Fehlplanung
# ----------------------------------------------------------------------
def test_no_misjudgement_without_overreach(route):
    assert st.plan_misjudgement(route, 0.0, np.random.default_rng(0)) is None
    assert st.plan_misjudgement(route, -0.02, np.random.default_rng(0)) is None


def test_misjudgement_probability_grows_with_overreach(route):
    def rate(overreach: float) -> float:
        hits = sum(
            st.plan_misjudgement(route, overreach, np.random.default_rng(i)) is not None
            for i in range(400)
        )
        return hits / 400.0

    assert rate(0.01) < rate(0.03) < rate(0.06)
    assert rate(0.06) <= st.MISJUDGE_MAX_P + 0.05


def test_misjudgement_stays_inside_the_route(route):
    for i in range(200):
        m = st.plan_misjudgement(route, 0.05, np.random.default_rng(i))
        if m is None:
            continue
        assert 0.0 < m.dist_m < route.distance_m
        assert m.dist_m + m.length_m <= route.distance_m
        assert 0.6 <= m.strength <= 1.6
        assert "Fehlplanung" in m.reason


def test_misjudgement_hits_late(route):
    """Sichtbar erst spät – genau das ist der Reiz."""
    onsets = [
        m.dist_m / route.distance_m
        for m in (st.plan_misjudgement(route, 0.05, np.random.default_rng(i)) for i in range(300))
        if m is not None
    ]
    assert onsets
    assert min(onsets) >= 0.45
    assert max(onsets) <= 0.70


def test_bad_pacers_collect_more_misjudgements():
    rng = np.random.default_rng(0)
    base = generate_rider(rng, 0, 0, archetype="allrounder")

    def rate(pacing: float, erfahrung: float) -> float:
        attrs = {**base.attributes, "pacing_disziplin": pacing, "erfahrung": erfahrung}
        rider = Rider(**{**base.to_dict(), "attributes": attrs})
        hits = 0
        for i in range(300):
            _, overreach, _ = st.target_intensity(rider, 600.0, np.random.default_rng(i))
            if overreach > st.MISJUDGE_THRESHOLD:
                hits += 1
        return hits / 300.0

    assert rate(10.0, 10.0) > rate(90.0, 90.0)


# ----------------------------------------------------------------------
# Im Rennen
# ----------------------------------------------------------------------
def test_race_produces_and_closes_conditions(route):
    teams, riders = generate_pool(30, n_teams=5, seed=4)
    result = simulate_race(
        route, riders, teams, RaceConfig(seed=2024, enable_incidents=False)
    )
    assert result.conditions, "Bei 30 Fahrern sollte mindestens einer sich vertun"
    for record in result.conditions:
        assert record.typ == "fehlplanung"
        assert record.end_t_s is not None and record.end_dist_m is not None
        assert record.end_t_s > record.start_t_s
        assert record.end_dist_m > record.start_dist_m
        assert record.reason


def test_condition_events_pair_up(route):
    teams, riders = generate_pool(30, n_teams=5, seed=4)
    result = simulate_race(
        route, riders, teams, RaceConfig(seed=2024, enable_incidents=False)
    )
    starts = [e for e in result.events if e.type == CONDITION_START]
    assert len(starts) == len(result.conditions)
    for event in starts:
        assert event.payload["typ"] == "fehlplanung"
        assert event.payload["reason"]
    # Zustände, die vor dem Ziel auslaufen, melden sich auch ab.
    ends = [e for e in result.events if e.type == CONDITION_END]
    assert len(ends) <= len(starts)


def test_misjudgement_actually_costs_time(route):
    """Ohne messbare Wirkung wäre der ganze Aufwand Kosmetik."""
    teams, riders = generate_pool(40, n_teams=5, seed=4)
    result = simulate_race(
        route, riders, teams, RaceConfig(seed=2024, enable_incidents=False)
    )
    affected = {c.entry_id for c in result.conditions}
    assert affected

    tel = result.telemetry
    for entry_id in list(affected)[:5]:
        record = next(c for c in result.conditions if c.entry_id == entry_id)
        row_dist = tel.dist_m[entry_id].astype(float)
        row_form = tel.form_pct[entry_id]
        before = row_form[row_dist < record.start_dist_m]
        during = row_form[
            (row_dist >= record.start_dist_m)
            & (row_dist < record.start_dist_m + 0.3 * (record.end_dist_m - record.start_dist_m))
        ]
        assert during.size and before.size
        assert during.mean() < before.mean(), "Der Einbruch muss in der Form sichtbar sein"
