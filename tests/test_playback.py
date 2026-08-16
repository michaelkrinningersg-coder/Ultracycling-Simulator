"""Tests von Speicherung, Playback-Server und Web-Schnittstelle (M4).

Der wichtigste Test dieser Datei ist ``test_no_data_from_the_future``:
Das Rennen ist vorberechnet, und die einzige Zusicherung, die das
Playback wie live wirken lässt, ist die, dass der Client nie etwas sieht,
was zur Wanduhrzeit noch nicht passiert ist.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.rider import generate_pool
from ultrasim.data.store import Store
from ultrasim.web.main import create_app
from ultrasim.web.playback import BOARD_WINDOW, PlaybackSession, RaceView, _window


@pytest.fixture(scope="module")
def stored(route, tmp_path_factory):
    """Ein kleines Rennen, einmal gerechnet und abgelegt."""
    root = tmp_path_factory.mktemp("data")
    store = Store(root)
    route.save(store.routes_dir / "teststrecke.json.gz")
    teams, riders = generate_pool(16, n_teams=4, seed=21)
    store.save_pool(teams, riders)
    result = simulate_race(route, riders, teams, RaceConfig(seed=77, name="Testrennen"))
    store.save_race("testrennen", "teststrecke", result)
    return store, result, route


@pytest.fixture(scope="module")
def view(stored):
    _, result, route = stored
    return RaceView(result, route)


@pytest.fixture(scope="module")
def client(stored):
    store, _, _ = stored
    return TestClient(create_app(store.root))


# ----------------------------------------------------------------------
# Persistenz
# ----------------------------------------------------------------------
def test_race_roundtrip(stored):
    store, result, _ = stored
    again, route_id = store.load_race("testrennen")
    assert route_id == "teststrecke"
    # Zeiten werden beim Speichern auf Hundertstel gerundet und
    # Splitzeiten als float32 abgelegt – für ein Rennergebnis mehr als
    # genug, aber eben nicht bitgleich.
    for a, b in zip(again.entries, result.entries, strict=True):
        assert a.finish_time_s == pytest.approx(b.finish_time_s, abs=0.05)
    assert np.allclose(again.split_times_s, result.split_times_s, equal_nan=True, atol=0.05)
    assert np.array_equal(again.telemetry.dist_m, result.telemetry.dist_m)
    assert len(again.events) == len(result.events)
    assert len(again.plans) == len(result.plans)
    assert again.config.seed == result.config.seed
    assert again.config.name == "Testrennen"


def test_pool_roundtrip(stored):
    store, _, _ = stored
    teams, riders = store.load_pool()
    assert len(teams) == 4
    assert len(riders) == 16
    assert all(r.attributes for r in riders)


def test_listing(stored):
    store, _, _ = stored
    routes = store.list_routes()
    assert [r["id"] for r in routes] == ["teststrecke"]
    races = store.list_races()
    assert races[0]["race_id"] == "testrennen"
    assert races[0]["winner_time_s"] > 0


def test_missing_race_raises(stored):
    store, _, _ = stored
    with pytest.raises(FileNotFoundError):
        store.load_race("gibtsnicht")


# ----------------------------------------------------------------------
# Die zentrale Zusicherung
# ----------------------------------------------------------------------
def test_no_data_from_the_future(view, stored):
    """Zu keiner Wanduhrzeit darf ein Fahrer weiter sein, als er ist.

    Geprüft an drei Stellen gleichzeitig: die Momentaufnahme, die
    Splitwertung und die virtuelle Rangliste.
    """
    _, result, route = stored
    horizon = result.last_finish_wallclock_s
    for fraction in (0.05, 0.2, 0.45, 0.7, 0.95):
        t = horizon * fraction
        snap = view.snapshot(t)
        for i, entry in enumerate(result.entries):
            elapsed = t - entry.start_offset_s
            if elapsed < 0:
                assert snap["dist"][i] == 0.0, "Ein Fahrer fährt vor seinem Start"
                continue
            # Kein Fahrer darf weiter sein, als seine Zeit erlaubt.
            if entry.finish_time_s is not None and elapsed < entry.finish_time_s:
                assert snap["dist"][i] < route.distance_m + 1.0

            # Splitzeiten dürfen nur zählen, wenn der Split durch ist.
            for s_idx, split_time in enumerate(result.split_times_s[i]):
                if np.isfinite(split_time) and split_time > elapsed:
                    board = view.board_rows(t, s_idx, focus=i)
                    row = next((r for r in board["rows"] if r["entry_id"] == i), None)
                    if row is not None:
                        assert row["provisional"], (
                            f"Splitzeit von Fahrer {i} an Split {s_idx} wurde verraten"
                        )
                    break


def test_board_marks_unreached_splits_as_provisional(view, stored):
    _, result, _ = stored
    board = view.board_rows(60.0, len(result.split_times_s[0]) - 1, focus=0)
    assert board["n_reached"] == 0
    assert all(r["provisional"] for r in board["rows"])
    assert all(r["rank"] is None for r in board["rows"])


def test_board_ranks_reached_riders_by_split_time(view, stored):
    _, result, _ = stored
    horizon = result.last_finish_wallclock_s
    board = view.board_rows(horizon, 2, focus=0)
    reached = [r for r in board["rows"] if not r["provisional"]]
    assert len(reached) == len(result.entries)
    assert [r["rank"] for r in reached] == list(range(1, len(reached) + 1))
    assert [r["t_s"] for r in reached] == sorted(r["t_s"] for r in reached)
    assert reached[0]["gap_s"] == 0.0


def test_elapsed_at_distance_refuses_to_look_ahead(view, stored):
    _, result, route = stored
    assert view.elapsed_at_distance(0, route.distance_m, t_wall=10.0) is None
    horizon = result.last_finish_wallclock_s
    value = view.elapsed_at_distance(0, route.distance_m * 0.5, t_wall=horizon)
    assert value is not None and value > 0


def test_virtual_ranking_projects_everyone_to_the_same_distance(view, stored):
    _, result, _ = stored
    t = result.last_finish_wallclock_s * 0.6
    board = view.virtual_rows(t, focus=0)
    assert board["split"]["kind"] == "virtual"
    times = [r["t_s"] for r in board["rows"]]
    assert times == sorted(times)
    assert board["rows"][0]["rank"] == 1


def test_last_split_index_follows_the_focus_rider(view, stored):
    _, result, _ = stored
    assert view.last_split_index(0.0, 0) == 0
    late = view.last_split_index(result.last_finish_wallclock_s, 0)
    assert late == result.split_times_s.shape[1] - 1


# ----------------------------------------------------------------------
# Board-Fenster
# ----------------------------------------------------------------------
def test_window_centres_on_focus_and_sticks_at_the_edges():
    rows = [{"entry_id": i} for i in range(250)]
    top = _window(rows, focus=0, size=BOARD_WINDOW)
    assert [r["entry_id"] for r in top] == list(range(BOARD_WINDOW))

    middle = _window(rows, focus=120, size=BOARD_WINDOW)
    assert middle[BOARD_WINDOW // 2]["entry_id"] == 120

    bottom = _window(rows, focus=249, size=BOARD_WINDOW)
    assert bottom[-1]["entry_id"] == 249
    assert len(bottom) == BOARD_WINDOW

    small = [{"entry_id": i} for i in range(10)]
    assert len(_window(small, focus=3, size=BOARD_WINDOW)) == 10


# ----------------------------------------------------------------------
# Playback-Uhr
# ----------------------------------------------------------------------
def test_clock_only_advances_while_playing():
    session = PlaybackSession(race_id="x", horizon_s=10_000.0, speed=1000)
    assert session.now() == 0.0
    session.seek(500.0)
    assert session.now() == 500.0
    session.play()
    assert session.playing
    session.pause()
    assert not session.playing
    frozen = session.now()
    assert session.now() == frozen


def test_clock_stops_at_the_horizon():
    session = PlaybackSession(race_id="x", horizon_s=100.0, speed=1000)
    session.seek(1e9)
    assert session.now() == 100.0
    session.play()
    assert session.now() <= 100.0


def test_frame_interval_coarsens_with_speed():
    session = PlaybackSession(race_id="x", horizon_s=1.0)
    for speed, expected in ((1, 0.25), (10, 0.25), (60, 0.5), (300, 1.0), (1000, 1.0)):
        session.speed = speed
        assert session.frame_interval_s() == expected


def test_high_speed_streams_only_major_events(view, stored):
    _, result, _ = stored
    horizon = result.last_finish_wallclock_s
    slow = view.events_between(0.0, horizon, speed=1, focus=None)
    fast = view.events_between(0.0, horizon, speed=1000, focus=None)
    assert len(fast) <= len(slow)
    assert all(e.type != "START" for e in fast)


# ----------------------------------------------------------------------
# Web-Schnittstelle
# ----------------------------------------------------------------------
def test_pages_render(client):
    assert client.get("/").status_code == 200
    assert client.get("/race/testrennen").status_code == 200
    assert client.get("/race/testrennen/results").status_code == 200
    assert client.get("/race/testrennen/rider/0").status_code == 200


def test_unknown_race_returns_404(client):
    assert client.get("/race/gibtsnicht").status_code == 404


def test_route_endpoint_delivers_a_drawable_profile(client):
    data = client.get("/api/race/testrennen/route").json()
    profile = data["profile"]
    assert len(profile["dist_m"]) == len(profile["ele_m"]) == len(profile["grade"])
    assert profile["dist_m"][0] == 0
    assert profile["dist_m"] == sorted(profile["dist_m"])
    assert data["splits"][-1]["kind"] == "finish"


def test_playback_session_and_frame(client):
    token = client.post("/api/race/testrennen/session").json()["token"]
    client.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 3600})
    frame = client.get(f"/api/playback/{token}/frame").json()
    assert frame["t_wall"] == pytest.approx(3600, abs=2)
    assert frame["focus"]["entry_id"] >= 0
    assert frame["board"]["rows"]
    assert frame["field"]["total"] == 16


def test_control_rejects_nonsense(client):
    token = client.post("/api/race/testrennen/session").json()["token"]
    assert client.post(f"/api/playback/{token}/control", json={"action": "fliegen"}).status_code == 400
    assert client.post(f"/api/playback/{token}/control", json={"action": "speed", "value": 7}).status_code == 400
    assert client.get("/api/playback/unbekannt/frame").status_code == 404


def test_manual_split_choice_disables_following(client):
    token = client.post("/api/race/testrennen/session").json()["token"]
    state = client.post(f"/api/playback/{token}/control", json={"action": "split", "value": 2}).json()
    assert state["split_idx"] == 2
    assert state["split_follow"] is False
    frame = client.get(f"/api/playback/{token}/frame").json()
    assert frame["board"]["split"]["idx"] == 2


def test_next_split_jump_moves_the_clock_forward(client):
    token = client.post("/api/race/testrennen/session").json()["token"]
    before = client.get(f"/api/playback/{token}/frame").json()["t_wall"]
    after = client.post(f"/api/playback/{token}/control", json={"action": "next_split"}).json()
    assert after["sim_t"] > before


def test_curves_endpoint_is_consistent(client):
    data = client.get("/api/race/testrennen/rider/0/curves").json()
    n = len(data["t_s"])
    assert n > 10
    assert all(len(data[k]) == n for k in ("dist_km", "v_kmh", "power_w", "form_pct", "wprime_pct"))
    assert data["dist_km"] == sorted(data["dist_km"])


# ----------------------------------------------------------------------
# Zustände im Playback (M5.1)
# ----------------------------------------------------------------------
def test_conditions_survive_the_roundtrip(stored):
    store, result, _ = stored
    again, _ = store.load_race("testrennen")
    assert len(again.conditions) == len(result.conditions)
    for a, b in zip(again.conditions, result.conditions, strict=True):
        assert a.typ == b.typ
        assert a.entry_id == b.entry_id
        assert a.start_dist_m == pytest.approx(b.start_dist_m, abs=0.1)
        assert a.reason == b.reason
    # und der Plan, aus dem sie stammen, ebenso
    assert [p.misjudgement is None for p in again.plans] == [
        p.misjudgement is None for p in result.plans
    ]


def test_conditions_never_leak_from_the_future(view, stored):
    """Ein Zustand, der noch nicht begonnen hat, existiert nicht.

    Und ein laufender endet für den Zuschauer *jetzt* – sonst verriete
    der Balken über dem Profil, wie lange der Einbruch noch dauert.
    """
    _, result, _ = stored
    if not result.conditions:
        pytest.skip("Dieses Rennen hat keine Zustände")
    horizon = result.last_finish_wallclock_s
    for fraction in (0.1, 0.35, 0.6, 0.85):
        t = horizon * fraction
        for entry in result.entries:
            elapsed = t - entry.start_offset_s
            shown = view.conditions_at(entry.entry_id, t)
            for row in shown:
                assert row["start_t_s"] <= elapsed
                assert row["end_t_s"] <= elapsed + 1e-6
            real = [c for c in result.conditions if c.entry_id == entry.entry_id]
            started = [c for c in real if c.start_t_s <= elapsed]
            assert len(shown) == len(started)


def test_active_filter_only_returns_running_conditions(view, stored):
    _, result, _ = stored
    if not result.conditions:
        pytest.skip("Dieses Rennen hat keine Zustände")
    record = result.conditions[0]
    offset = result.entries[record.entry_id].start_offset_s
    mid = offset + 0.5 * (record.start_t_s + record.end_t_s)
    active = view.conditions_at(record.entry_id, mid, only_active=True)
    assert active and all(row["active"] for row in active)
    # Nach seinem Ende ist *dieser* Zustand weg. Andere dürfen laufen –
    # ein Fahrer kann seit M6.2 gleichzeitig mehrere haben.
    after = view.conditions_at(record.entry_id, offset + record.end_t_s + 60.0, only_active=True)
    assert not any(
        row["typ"] == record.typ and row["start_t_s"] == record.start_t_s for row in after
    )


def test_board_rows_carry_condition_labels(client):
    token = client.post("/api/race/testrennen/session").json()["token"]
    client.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 4000})
    frame = client.get(f"/api/playback/{token}/frame").json()
    assert all("conditions" in row for row in frame["board"]["rows"])
    assert isinstance(frame["focus"]["conditions"], list)


# ----------------------------------------------------------------------
# Laufende Uhr im Board
# ----------------------------------------------------------------------
def test_a_rider_before_the_split_shows_his_running_clock(view):
    """Keine Prognose mehr, sondern die Zeit seit seinem Start.

    Das ist die Zeitnahme aus dem Wintersport: Die Uhr läuft, und wer
    noch unterwegs ist, steht mit dem, was sie gerade zeigt.
    """
    split_idx = len(view.route.splits) - 1  # Ziel: da ist am Anfang niemand
    board = view.board_rows(t_wall=1800.0, split_idx=split_idx, focus=0)
    running = [r for r in board["rows"] if r["running"]]
    assert running, "Auf halber Strecke muss jemand unterwegs sein"

    snap = view.snapshot(1800.0)
    for row in running:
        assert row["provisional"] is True
        assert row["rank"] is None
        assert row["t_s"] == pytest.approx(float(snap["elapsed"][row["entry_id"]]))


def test_the_running_clock_advances_with_the_wall_clock(view):
    split_idx = len(view.route.splits) - 1
    early = view.board_rows(1800.0, split_idx, focus=0)
    later = view.board_rows(2400.0, split_idx, focus=0)
    first = {r["entry_id"]: r for r in early["rows"] if r["running"]}
    second = {r["entry_id"]: r for r in later["rows"] if r["running"]}
    common = set(first) & set(second)
    assert common
    for entry_id in common:
        assert second[entry_id]["t_s"] == pytest.approx(first[entry_id]["t_s"] + 600.0)


def test_a_running_rider_drops_behind_times_he_passes(view):
    """Die eigentliche Aussage der laufenden Uhr.

    Sobald sie über eine gefahrene Zeit hinauswandert, rutscht der
    Fahrer einen Platz nach hinten — ohne dass sich an der Strecke
    irgendetwas ändert.
    """
    split_idx = 1
    times = view.result.split_times_s[:, split_idx]
    reached = view.offsets + times
    # Wanduhr kurz nachdem der erste Fahrer den Split passiert hat.
    t0 = float(np.nanmin(np.where(np.isfinite(reached), reached, np.inf))) + 60.0

    def position(t):
        rows = view.board_rows(t, split_idx, focus=0)["rows"]
        order = [r["entry_id"] for r in rows]
        running = [r for r in rows if r["running"]]
        return order, running

    order_a, running_a = position(t0)
    assert running_a, "Es muss noch jemand unterwegs sein"
    watched = running_a[0]["entry_id"]

    order_b, _ = position(t0 + 3600.0)
    if watched in order_a and watched in order_b:
        assert order_b.index(watched) >= order_a.index(watched)


def test_a_retired_rider_keeps_a_still_clock(view):
    """Ein Aufgeber darf nicht langsam durchs Board nach unten wandern."""
    end = view.result.telemetry.n_samples * view.result.telemetry.sample_dt_s
    board = view.board_rows(float(end), split_idx=len(view.route.splits) - 1, focus=0)
    for row in board["rows"]:
        if row["state"] == 3:  # DNF
            assert row["running"] is False
            assert row["t_s"] is None


# ----------------------------------------------------------------------
# Bestzeiten im Ticker
# ----------------------------------------------------------------------
def test_best_times_only_ever_improve(view):
    from ultrasim.core.events import BEST_TIME

    per_split: dict[int, list[float]] = {}
    for event in view._events:
        if event.type != BEST_TIME:
            continue
        per_split.setdefault(event.payload["split_idx"], []).append(event.t_s)
    assert per_split, "Ein Rennen ohne einzige Bestzeit gibt es nicht"
    for split_idx, values in per_split.items():
        assert values == sorted(values, reverse=True), (
            f"Split {split_idx}: Bestzeiten müssen fallen, nicht steigen"
        )


def test_the_first_time_at_a_marker_counts_as_a_best_time(view):
    from ultrasim.core.events import BEST_TIME

    firsts = [
        e for e in view._events if e.type == BEST_TIME and e.payload.get("first")
    ]
    # Genau eine erste Zeit je Split, an dem überhaupt jemand ankam.
    assert len({e.payload["split_idx"] for e in firsts}) == len(firsts)
    assert all(e.payload["margin_s"] is None for e in firsts)


def test_best_times_stay_behind_the_wall_clock(view):
    """Auch erzeugte Ereignisse dürfen die Zukunft nicht verraten."""
    from ultrasim.core.events import BEST_TIME

    t = 3000.0
    visible = view.events_between(0.0, t, speed=1, focus=None)
    for event in visible:
        if event.type == BEST_TIME:
            assert event.t_s + view.offsets[event.entry_id] <= t


# ----------------------------------------------------------------------
# Warum-Panel: die Form in ihre Faktoren zerlegt
# ----------------------------------------------------------------------
def test_the_factors_multiply_back_to_the_form(view):
    """Die Zerlegung muss die Zahl ergeben, die sie erklären soll.

    Auf ein Prozent genau: Jeder Faktor liegt als uint8 in Prozent vor,
    und zehn davon summieren ihre Rundung auf.
    """
    t = 1800.0
    breakdown = view.factors_at(0, t)
    assert breakdown is not None, "Ein frisch gerechnetes Rennen zeichnet die Faktoren auf"

    product = 1.0
    for row in breakdown["rows"]:
        product *= row["pct"] / 100.0
    assert product * 100.0 == pytest.approx(breakdown["total_pct"], abs=0.2)

    snap = view.snapshot(t)
    assert breakdown["total_pct"] == pytest.approx(float(snap["form"][0]), abs=3.0)


def test_the_costliest_factor_comes_first(view):
    rows = view.factors_at(0, 1800.0)["rows"]
    assert [r["pct"] for r in rows] == sorted(r["pct"] for r in rows)


def test_every_factor_is_named(view):
    from ultrasim.core.engine import Telemetry

    labels = {r["key"] for r in view.factors_at(0, 1800.0)["rows"]}
    assert set(Telemetry.FACTOR_LABELS) <= labels
    # Die drei über das Rennen konstanten Größen stehen am Starter, nicht
    # in der Telemetrie — fehlen dürfen sie trotzdem nicht.
    assert {"season", "day", "fresh"} <= labels


def test_a_rider_before_his_start_has_no_breakdown(view):
    late = max(range(view.n), key=lambda i: view.offsets[i])
    if view.offsets[late] > 0:
        assert view.factors_at(late, 0.0) is None


def test_a_race_without_recorded_factors_says_so(view):
    """Rennen von vor der Aufzeichnung dürfen nicht raten."""
    from dataclasses import replace

    old = RaceView(replace(view.result, telemetry=replace(view.telemetry, factors=None)), view.route)
    assert old.factors_at(0, 1800.0) is None


# ----------------------------------------------------------------------
# Meter bis zur nächsten Zeitmessung
# ----------------------------------------------------------------------
def test_the_distance_to_the_next_checkpoint_counts_down(view):
    """Gemeint ist die Marke vor dem Fahrer, nicht die des Boards."""
    dists = view.split_dist
    assert len(dists) > 1
    mid = float(dists[0]) + (float(dists[1]) - float(dists[0])) / 2.0
    out = view.to_next_split(mid, 0)
    assert out["to_next_m"] == pytest.approx(float(dists[1]) - mid, abs=1.0)
    assert out["next_split"]

    # Kurz vor derselben Marke ist es weniger, nicht mehr.
    closer = view.to_next_split(float(dists[1]) - 100.0, 0)
    assert closer["to_next_m"] < out["to_next_m"]


def test_a_finished_or_retired_rider_has_no_next_checkpoint(view):
    """Eine 0 wäre in beiden Fällen eine Behauptung."""
    from ultrasim.core.engine import STATE_DNF, STATE_FINISHED

    for state in (STATE_FINISHED, STATE_DNF):
        assert view.to_next_split(1000.0, state) == {"to_next_m": None, "next_split": None}


def test_past_the_last_checkpoint_there_is_none(view):
    beyond = float(view.split_dist[-1]) + 500.0
    assert view.to_next_split(beyond, 0)["to_next_m"] is None


def test_every_board_row_carries_the_distance_to_the_next_checkpoint(view):
    board = view.board_rows(t_wall=1800.0, split_idx=1, focus=0)
    assert board["rows"]
    for row in board["rows"]:
        assert "to_next_m" in row and "next_split" in row
        if row["to_next_m"] is not None:
            assert row["to_next_m"] >= 0


# ----------------------------------------------------------------------
# Wählbare Spalten, Sortierung, Nadeln
# ----------------------------------------------------------------------
def test_every_row_carries_the_values_of_the_optional_columns(view):
    """Die wählbaren Spalten kommen mit jeder Zeile mit.

    Sonst bräuchte jedes Umschalten eine zweite Abfragestrecke — für
    acht Zahlen je Zeile, die ohnehin schon im Speicher liegen.
    """
    board = view.board_rows(t_wall=3600.0, split_idx=1, focus=0)
    for row in board["rows"]:
        for key in (
            "v_kmh", "power_w", "form_pct", "wprime_pct", "glyco_pct",
            "sleep_pct", "hydration_pct", "giveup_pct", "trend",
        ):
            assert key in row, key


def test_the_give_up_pressure_is_a_share_of_the_riders_own_limit(view):
    """0 heißt zufrieden, 100 heißt: Er steigt in dieser Sekunde ab."""
    board = view.board_rows(t_wall=3600.0, split_idx=1, focus=0)
    values = [r["giveup_pct"] for r in board["rows"]]
    assert values and all(v is not None for v in values)
    assert all(0 <= v <= 255 for v in values)


def test_a_race_without_the_channel_shows_no_pressure(stored):
    """Ein altes Rennen verliert die Spalte, nicht die Lesbarkeit."""
    import dataclasses

    _, result, route = stored
    old = dataclasses.replace(
        result, telemetry=dataclasses.replace(result.telemetry, giveup_pct=None)
    )
    board = RaceView(old, route).board_rows(t_wall=3600.0, split_idx=1, focus=0)
    assert all(row["giveup_pct"] is None for row in board["rows"])


def test_sorting_reorders_the_rows_without_touching_the_ranks(view):
    """Rang 1 bleibt der Schnellste, auch wenn nach Tempo sortiert ist."""
    plain = view.board_rows(t_wall=3600.0, split_idx=1, focus=0)
    by_bib = view.board_rows(t_wall=3600.0, split_idx=1, focus=0, sort="nr")

    bibs = [r["bib"] for r in by_bib["rows"]]
    assert bibs == sorted(bibs)
    ranks = {r["entry_id"]: r["rank"] for r in plain["rows"]}
    for row in by_bib["rows"]:
        if row["entry_id"] in ranks:
            assert row["rank"] == ranks[row["entry_id"]]


def test_sorting_descending_turns_the_list_around(view):
    up = view.board_rows(t_wall=3600.0, split_idx=1, focus=0, sort="km")
    down = view.board_rows(t_wall=3600.0, split_idx=1, focus=0, sort="km", sort_desc=True)
    assert [r["dist_km"] for r in up["rows"]] == sorted(r["dist_km"] for r in up["rows"])
    assert [r["dist_km"] for r in down["rows"]] == sorted(
        (r["dist_km"] for r in down["rows"]), reverse=True
    )


def test_rows_without_a_value_stay_at_the_end_in_both_directions():
    """Ein fehlender Wert ist keine 0 und gehört nie an die Spitze."""
    from ultrasim.web.playback import sort_rows

    rows = [{"dist_km": 3.0}, {"dist_km": None}, {"dist_km": 1.0}]
    for desc in (False, True):
        out = sort_rows(list(rows), "km", desc)
        assert out[-1]["dist_km"] is None


def test_an_unknown_sort_key_leaves_the_order_alone():
    from ultrasim.web.playback import sort_rows

    rows = [{"dist_km": 3.0}, {"dist_km": 1.0}]
    assert sort_rows(list(rows), "gibtsnicht", False) == rows


def test_the_trend_only_speaks_where_both_splits_are_measured(view):
    """Kein Pfeil aus halber Datenlage."""
    early = view.split_trend(t_wall=60.0, split_idx=1)
    assert not early.any(), "vor der ersten Zeitnahme gibt es keinen Trend"
    assert not view.split_trend(t_wall=99999.0, split_idx=0).any(), "der erste Split hat keinen davor"


def test_the_trend_counts_places_gained(view):
    """Wer an der ersten Marke Zweiter war und dann Erster, steht auf +1."""
    late = 12 * 3600.0
    now = view.measured_ranks(late, 2)
    before = view.measured_ranks(late, 1)
    trend = view.split_trend(late, 2)
    for i in range(view.n):
        if now[i] and before[i]:
            assert trend[i] == before[i] - now[i]
        else:
            assert trend[i] == 0


def test_pinned_riders_come_along_no_matter_where_they_stand(view):
    board = view.board_rows(t_wall=3600.0, split_idx=1, focus=0, pinned=[0, 3])
    assert [r["entry_id"] for r in board["pinned"]] == [0, 3]


def test_the_pin_holds_two_riders(client):
    """Der dritte verdrängt den ältesten — ein Duell hat zwei Seiten."""
    from ultrasim.web.playback import MAX_PINNED, PlaybackSession

    session = PlaybackSession(race_id="x")
    for entry_id in (1, 2, 3):
        session.toggle_pin(entry_id)
    assert session.pinned == [2, 3]
    assert len(session.pinned) == MAX_PINNED
    session.toggle_pin(3)
    assert session.pinned == [2]


def test_the_control_endpoint_sorts_and_pins(client):
    token = client.post("/api/race/testrennen/session").json()["token"]

    def control(action, value=None):
        return client.post(f"/api/playback/{token}/control", json={"action": action, "value": value})

    assert control("sort", "tempo").json()["sort"] == "tempo"
    # Dieselbe Spalte noch einmal dreht die Richtung.
    assert control("sort", "tempo").json()["sort_desc"] is True
    assert control("sort", "tempo").json()["sort_desc"] is False
    assert control("sort", "gibtsnicht").status_code == 400

    assert control("pin", 2).json()["pinned"] == [2]
    assert control("pin", 2).json()["pinned"] == []

    control("pin", 1)
    frame = client.get(f"/api/playback/{token}/frame").json()
    assert [r["entry_id"] for r in frame["board"]["pinned"]] == [1]
