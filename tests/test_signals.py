"""Ampeln auf der Strecke.

Die Ampel ist der erste Halt im Modell, den niemand plant und niemand
verschuldet. Zwei Dinge sichert diese Datei deshalb besonders ab:

* Sie darf den **Aufgabedruck** nicht anheben. Ein Fahrer, der aufgibt,
  weil zu viele Kreuzungen auf seiner Strecke lagen, wäre eine Aussage
  über den Streckenverlauf, nicht über ihn.
* Sie muss **deterministisch** stehen. Dieselbe Strecke hat in jedem
  Prozess dieselben Ampeln — sonst wären zwei Läufe desselben Rennens
  nicht mehr vergleichbar, und der Golden Master wäre wertlos.
"""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.events import TRAFFIC_LIGHT
from ultrasim.core.rider import generate_pool
from ultrasim.geo import signals as sig


# ----------------------------------------------------------------------
# Die Phase
# ----------------------------------------------------------------------
def test_red_and_green_are_equally_long():
    """Damit ein Fahrer die Ampel in der Hälfte der Fälle rot antrifft."""
    assert sig.RED_S == sig.GREEN_S
    assert sig.CYCLE_S == sig.RED_S + sig.GREEN_S


def test_the_wait_never_exceeds_the_red_phase():
    times = np.linspace(0.0, 3.0 * sig.CYCLE_S, 601)
    for offset in (0.0, 17.0, 88.5, 179.9):
        waits = [sig.wait_s(offset, float(t)) for t in times]
        assert min(waits) == 0.0, "irgendwann ist sie grün"
        assert max(waits) <= sig.RED_S


def test_half_the_arrivals_are_green():
    """Über eine volle Phase gemittelt: halb rot, halb grün."""
    times = np.linspace(0.0, sig.CYCLE_S, 1000, endpoint=False)
    green = sum(1 for t in times if sig.wait_s(0.0, float(t)) == 0.0)
    assert 0.48 <= green / len(times) <= 0.52


def test_the_average_wait_is_a_quarter_of_the_cycle():
    """Erwartungswert: eine halbe Rotphase, aber nur in der Hälfte der Fälle.

    22,5 s je Ampel — die Zahl, mit der sich abschätzen lässt, was die
    Mechanik ein Rennen kostet: auf 2469 km mit 42 Ampeln rund 16 min.
    """
    times = np.linspace(0.0, sig.CYCLE_S, 10_000, endpoint=False)
    mean = float(np.mean([sig.wait_s(0.0, float(t)) for t in times]))
    assert mean == pytest.approx(sig.RED_S / 4.0, rel=0.02)


def test_the_cycle_starts_red():
    """Eine bekannte Antwort für den Test: Ankunft zur Zeit 0 ist rot."""
    assert sig.wait_s(0.0, 0.0) == sig.RED_S
    assert sig.wait_s(0.0, sig.RED_S) == 0.0


# ----------------------------------------------------------------------
# Die Platzierung
# ----------------------------------------------------------------------
def test_the_lights_keep_their_distance(route_long):
    lights = route_long.traffic_lights
    assert lights, "eine 1000-km-Strecke ohne Ampel wäre keine Straße"
    gaps = [b.dist_m - a.dist_m for a, b in zip(lights, lights[1:], strict=False)]
    assert min(gaps) >= sig.MIN_GAP_M


def test_no_hundred_kilometres_carry_more_than_two(route_long):
    """Nicht im Mittel, sondern in **jedem** Fenster.

    Bei sortierten Positionen ist das genau dann erfüllt, wenn zwischen
    der i-ten und der (i+2)-ten Ampel mehr als hundert Kilometer liegen.
    """
    positions = [lt.dist_m for lt in route_long.traffic_lights]
    for i in range(len(positions) - sig.PER_100_KM):
        assert positions[i + sig.PER_100_KM] - positions[i] > 100_000.0


def test_the_density_stays_under_the_limit(route_long):
    per_100 = len(route_long.traffic_lights) / (route_long.distance_km / 100.0)
    assert per_100 <= sig.PER_100_KM


def test_no_light_stands_on_a_climb(route_medium):
    """Auf einer Rampe steht keine Kreuzung — und ein Halt dort würde
    die Anstiegsphysik mit einer Anfahrt aus dem Stand belasten."""
    for light in route_medium.traffic_lights:
        for climb in route_medium.climbs:
            assert not (climb.dist_start_m <= light.dist_m <= climb.dist_end_m)


def test_no_light_stands_high_up(route_medium):
    for light in route_medium.traffic_lights:
        height = float(route_medium.elevation_at(np.array([light.dist_m]))[0])
        assert height <= sig.MAX_ELEVATION_M


def test_start_and_finish_stay_clear(route_medium):
    end = route_medium.distance_m
    for light in route_medium.traffic_lights:
        assert light.dist_m >= sig.EDGE_CLEARANCE_M
        assert light.dist_m <= end - sig.EDGE_CLEARANCE_M


def test_the_same_route_gets_the_same_lights(route):
    """Deterministisch heißt: über Prozessgrenzen hinweg.

    ``hash()`` wäre dafür untauglich — es ist je Prozess gesalzen. Der
    Test kann das nicht direkt prüfen, aber er hält fest, dass zweimal
    Platzieren dasselbe ergibt.
    """
    again = sig.place(route)
    assert [(lt.dist_m, lt.offset_s) for lt in again] == [
        (lt.dist_m, lt.offset_s) for lt in route.traffic_lights
    ]


def test_a_short_route_gets_none():
    """Unter hundert Kilometern rundet die Dichte auf null."""

    class Stub:
        name = "Kurzes Stück"
        distance_m = 40_000.0
        climbs: list = []

        def elevation_at(self, d):
            return np.zeros_like(np.asarray(d, dtype=float))

    assert sig.place(Stub()) == []


# ----------------------------------------------------------------------
# Im Rennen
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def raced(route_medium):
    teams, riders = generate_pool(10, n_teams=2, seed=4)
    return simulate_race(route_medium, riders, teams, RaceConfig(seed=88))


def test_riders_actually_stop_at_red(raced, route_medium):
    stops = [e for e in raced.events if e.type == TRAFFIC_LIGHT]
    assert stops, "bei zehn Fahrern und mehreren Ampeln muss jemand rot haben"
    for event in stops:
        assert 0.0 < event.payload["wait_s"] <= sig.RED_S


def test_about_half_the_crossings_are_red(raced, route_medium):
    """Die Phase ist zufällig gegen die Ankunft — also rund die Hälfte."""
    crossings = len(raced.entries) * len(route_medium.traffic_lights)
    stops = sum(1 for e in raced.events if e.type == TRAFFIC_LIGHT)
    assert 0.3 <= stops / crossings <= 0.7


def test_the_waiting_time_lands_in_its_own_column(raced):
    for entry in raced.entries:
        stopped = sum(
            e.payload["wait_s"]
            for e in raced.events
            if e.type == TRAFFIC_LIGHT and e.entry_id == entry.entry_id
        )
        assert entry.lost_signal_s == pytest.approx(stopped, abs=0.2)
        # Sie steckt in der Gesamtstandzeit …
        assert entry.lost_s >= entry.lost_signal_s - 0.2


def test_red_lights_never_raise_the_give_up_pressure(raced):
    """… aber nicht im Zwischenfallkonto, das den Aufgabedruck treibt.

    Das ist die tragende Zusicherung der ganzen Mechanik: Wer aufgibt,
    tut es wegen seines Rennens, nicht wegen der Kreuzungsdichte.
    """
    for entry in raced.entries:
        assert entry.lost_incident_s <= entry.lost_s - entry.lost_signal_s + 0.2


def test_a_route_without_lights_races_exactly_as_before(route):
    """Ohne Ampeln darf die Mechanik nichts kosten und nichts ändern.

    Die Strecke ist eine Sitzungs-Fixture, also wird sie hier geliehen
    und zurückgegeben — ein Test, der die Ampeln für alle folgenden
    entfernt, würde diese Datei zur Zeitbombe machen.
    """
    teams, riders = generate_pool(6, n_teams=2, seed=9)
    with_lights = simulate_race(route, riders, teams, RaceConfig(seed=3))

    borrowed = route.traffic_lights
    route.traffic_lights = []
    try:
        without = simulate_race(route, riders, teams, RaceConfig(seed=3))
    finally:
        route.traffic_lights = borrowed

    assert all(e.lost_signal_s == 0.0 for e in without.entries)
    # Und niemand ist ohne Ampeln langsamer als mit.
    for a, b in zip(with_lights.entries, without.entries, strict=True):
        if a.finish_time_s is None or b.finish_time_s is None:
            continue
        assert a.finish_time_s >= b.finish_time_s - 0.5


def test_the_focus_rider_gets_his_red_lights_in_the_ticker(route_medium, tmp_path):
    """Im Ticker steht die Ampel — aber nur die des Fokusfahrers.

    Bei dreihundert Startern wäre jede fremde rote Ampel eine Meldung
    über nichts. Der Ticker führt den Fokusfahrer vollständig und vom
    Rest nur das Nennenswerte; eine Ampel ist bewusst nicht nennenswert
    und steht deshalb auch nicht in ``MAJOR_EVENTS``.
    """
    from fastapi.testclient import TestClient

    from ultrasim.core.events import MAJOR_EVENTS
    from ultrasim.data.store import Store
    from ultrasim.web.main import create_app

    assert TRAFFIC_LIGHT not in MAJOR_EVENTS

    store = Store(tmp_path)
    route_medium.save(store.routes_dir / "teststrecke.json.gz")
    teams, riders = generate_pool(6, n_teams=2, seed=4)
    store.save_pool(teams, riders)
    result = simulate_race(route_medium, riders, teams, RaceConfig(seed=88))
    store.save_race("ampelrennen", "teststrecke", result, route=route_medium)

    client = TestClient(create_app(store.root))
    token = client.post("/api/race/ampelrennen/session").json()["token"]

    # Einen Fahrer wählen, der auch wirklich an einer Ampel stand.
    stops = [e for e in result.events if e.type == TRAFFIC_LIGHT]
    assert stops
    event = stops[0]
    offset = result.entries[event.entry_id].start_offset_s
    client.post(
        f"/api/playback/{token}/control", json={"action": "focus", "value": event.entry_id}
    )
    # Zwei Sekunden *hinter* den Halt: Das Fenster eines Einzelbildes
    # reicht fünf Sekunden zurück, und die untere Grenze zählt nicht mit.
    client.post(
        f"/api/playback/{token}/control",
        json={"action": "seek", "value": offset + event.t_s + 2.0},
    )
    frame = client.get(f"/api/playback/{token}/frame").json()
    assert any("Ampel" in item["text"] for item in frame["ticker"]), frame["ticker"]
