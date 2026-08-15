"""Ein Rennen live rechnen statt vorab.

Die tragende Zusicherung steht ganz unten: **Live und Stapel liefern
dasselbe Rennen.** Wäre das nicht so, hinge das Ergebnis daran, ob
jemand zugeschaut hat — und damit wäre der Seed keine Reproduzierbarkeit
mehr, sondern eine Behauptung.
"""

from __future__ import annotations

import pytest

from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.live import LiveRace
from ultrasim.core.rider import generate_pool


@pytest.fixture(scope="module")
def field():
    return generate_pool(8, n_teams=2, seed=31)


def _live(route, field, seed: int = 2024) -> LiveRace:
    teams, riders = field
    return LiveRace(route, list(riders), list(teams), RaceConfig(seed=seed))


def test_the_clock_only_moves_forward(route, field):
    live = _live(route, field)
    assert live.sim_t == 0.0
    first = live.advance_to(600.0)
    assert first >= 600.0
    # Ein Rückgriff rechnet nichts nach und bewegt nichts.
    assert live.advance_to(300.0) == first


def test_advancing_by_wall_time_scales_with_the_speed(route, field):
    slow = _live(route, field)
    fast = _live(route, field)
    slow.advance_by_wall(1.0, speed=1)
    fast.advance_by_wall(1.0, speed=600)
    assert fast.sim_t > slow.sim_t


def test_nothing_is_computed_before_it_is_asked_for(route, field):
    """Wer zusieht, soll nur zahlen, was er sieht."""
    live = _live(route, field)
    assert not live.finished
    live.advance_to(60.0)
    assert live.sim_t < 3600.0, "es wurde weit über das Verlangte hinaus gerechnet"


def test_the_race_finishes_and_then_holds_still(route, field):
    live = _live(route, field)
    live.advance_to(1e9)
    assert live.finished
    at_finish = live.sim_t
    assert live.advance_to(1e9 + 1) == at_finish
    assert live.result is not None
    assert all(e.status in ("FIN", "DNF", "OTL") for e in live.result.entries)


def test_live_and_batch_produce_the_same_race(route, field):
    """Die tragende Zusicherung.

    Dasselbe Rennen, einmal in einem Zug gerechnet und einmal in
    Häppchen, wie eine Wiedergabe es zieht. Jede Zielzeit muss auf die
    Hundertstelsekunde übereinstimmen — der Generator hält an, er
    rechnet nicht anders.
    """
    teams, riders = field
    batch = simulate_race(route, riders, teams, RaceConfig(seed=2024))

    live = _live(route, field)
    for _ in range(400):  # in kleinen Schritten, wie bei 60x Zeitraffer
        live.advance_by_wall(1.0, speed=60)
        if live.finished:
            break
    assert live.finished, "das Rennen hätte in dieser Zeit durch sein müssen"

    a = {e.bib: e.finish_time_s for e in batch.entries}
    b = {e.bib: e.finish_time_s for e in live.result.entries}
    assert a.keys() == b.keys()
    for bib, t in a.items():
        if t is None:
            assert b[bib] is None
        else:
            assert b[bib] == pytest.approx(t, abs=0.01), f"Startnummer {bib} weicht ab"


def test_live_and_batch_agree_on_the_event_stream(route, field):
    """Nicht nur die Zeiten — auch was unterwegs passiert ist."""
    teams, riders = field
    batch = simulate_race(route, riders, teams, RaceConfig(seed=2024))
    live = _live(route, field)
    live.advance_to(1e9)
    assert [(e.type, e.entry_id) for e in batch.events] == [
        (e.type, e.entry_id) for e in live.result.events
    ]
