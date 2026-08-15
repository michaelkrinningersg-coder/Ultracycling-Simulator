"""Ein Rennen live rechnen statt vorab.

Die tragende Zusicherung steht ganz unten: **Live und Stapel liefern
dasselbe Rennen.** Wäre das nicht so, hinge das Ergebnis daran, ob
jemand zugeschaut hat — und damit wäre der Seed keine Reproduzierbarkeit
mehr, sondern eine Behauptung.
"""

from __future__ import annotations

import numpy as np
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


# ----------------------------------------------------------------------
# Der Zwischenstand
# ----------------------------------------------------------------------
def test_a_snapshot_looks_like_a_finished_race(route, field):
    """Der Zwischenstand hat die Form eines Ergebnisses.

    Darauf beruht die ganze Verdrahtung der Oberfläche: Board, Ticker
    und Rangliste lesen ein ``RaceResult`` und dürfen nicht wissen
    müssen, ob es fertig ist.
    """
    live = _live(route, field)
    live.advance_to(1800.0)
    mid = live.current()
    assert mid is not None
    assert len(mid.entries) == len(mid.riders)
    assert mid.telemetry.n_entries == len(mid.entries)
    assert mid.telemetry.n_samples > 0
    assert mid.split_ranks.shape == mid.split_times_s.shape
    # Wer noch unterwegs ist, steht auf RUN und hat keine Zielzeit.
    running = [e for e in mid.entries if e.status == "RUN"]
    assert running, "nach einer halben Stunde sollte noch jemand fahren"
    assert all(e.finish_time_s is None and e.rank is None for e in running)


def test_the_snapshot_only_shows_what_has_already_happened(route, field):
    """Kein Blick nach vorn — auch nicht versehentlich.

    Die Telemetrie ist eine Sicht auf die Puffer der Engine. Wäre sie
    einen Tick zu breit geschnitten, stünden dort Nullen aus dem noch
    unbeschriebenen Teil — und die Anzeige zeigte einen Fahrer, der auf
    Kilometer null steht.
    """
    live = _live(route, field)
    live.advance_to(1800.0)
    mid = live.current()
    tel = mid.telemetry
    reached = tel.dist_m[:, -1]
    assert (reached > 0).all(), "die letzte Spalte ist noch gar nicht beschrieben"
    # Und monoton: Wer weiter ist, war vorher näher am Start.
    assert (np.diff(tel.dist_m.astype(np.int64), axis=1) >= 0).all()


def test_the_snapshot_keeps_up_after_the_buffers_double(route, field):
    """Der Telemetriepuffer verdoppelt sich — und das Fenster zieht mit.

    ``_grow`` legt die Puffer neu an, statt sie zu erweitern; die alten
    Referenzen zeigen danach auf den Stand von vorhin. Ohne die
    Nachführung im Schnappschuss bliebe das Rennen für den Zuschauer
    genau an der Stelle stehen, an der die Verdopplung fällt.

    Der Sekundentakt ist hier kein Selbstzweck: Er ist der kürzeste Weg,
    die Verdopplung auf einer Teststrecke überhaupt auszulösen. Mit dem
    üblichen Fünf-Sekunden-Takt passt das ganze Rennen in die erste
    Reservierung, und der Zweig bliebe ungetestet.
    """
    teams, riders = field
    live = LiveRace(route, list(riders), list(teams), RaceConfig(seed=2024, sample_dt_s=1))
    live.advance_to(600.0)
    early = live.current().telemetry
    assert early.n_samples < 4096, "die Verdopplung soll noch nicht gefallen sein"
    assert (early.dist_m[:, -1] > 0).all()

    live.advance_to(1e9)
    assert live.finished
    late = live.current().telemetry
    assert late.n_samples > 4096, "der Puffer hätte sich verdoppeln müssen"
    # Und der Anfang steht noch da, wo er stand: Die Verdopplung kopiert
    # den alten Inhalt mit, sie beginnt nicht von vorn.
    assert np.array_equal(late.dist_m[:, : early.n_samples], early.dist_m)


def test_the_snapshot_agrees_with_the_finished_race(route, field):
    """Am Ziel sagen Zwischenstand und Ergebnis dasselbe."""
    live = _live(route, field)
    live.advance_to(1e9)
    assert live.snapshot is not None
    final = live.result
    mid = live.snapshot.result()
    assert [e.status for e in mid.entries] == [e.status for e in final.entries]
    assert [e.rank for e in mid.entries] == [e.rank for e in final.entries]
    for a, b in zip(mid.entries, final.entries, strict=True):
        assert a.finish_time_s == b.finish_time_s
    assert np.array_equal(mid.telemetry.dist_m, final.telemetry.dist_m)
