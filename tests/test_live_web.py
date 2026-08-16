"""Die Weboberfläche an einem live gerechneten Rennen.

Bis hierher galt: Ein Rennen liegt fertig auf der Platte, der
Playback-Server schneidet es an seiner Uhr ab. Jetzt gibt es keine
Platte mehr, an der man schneiden könnte — das Rennen entsteht, während
jemand hinsieht.

Zwei Zusicherungen tragen das Ganze, und beide stehen hier:

* Die Oberfläche merkt den Unterschied nicht. Board, Rangliste und
  Ticker bekommen dieselbe Datenform wie bei einem gespeicherten
  Rennen — deshalb musste an ihnen nichts geändert werden.
* Es wird nichts vorberechnet. Wer zwei Minuten zusieht, bezahlt zwei
  Minuten Rennen und nicht vierzig Stunden.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ultrasim.core.engine import RaceConfig
from ultrasim.core.rider import generate_pool
from ultrasim.data.store import Store
from ultrasim.web.livesim import LiveRoom
from ultrasim.web.main import create_app


@pytest.fixture()
def app(route, tmp_path):
    """Eine App mit Strecke und Pool, aber ohne ein einziges Rennen."""
    store = Store(tmp_path)
    route.save(store.routes_dir / "teststrecke.json.gz")
    teams, riders = generate_pool(8, n_teams=2, seed=21)
    store.save_pool(teams, riders)
    return create_app(store.root), store, route


@pytest.fixture()
def client(app):
    return TestClient(app[0])


def _room(app, race_id: str = "live-test") -> LiveRoom:
    application, store, route = app
    teams, riders = store.load_pool()
    room = LiveRoom.start(
        race_id=race_id,
        route_id="teststrecke",
        route=route,
        riders=riders,
        teams=teams,
        config=RaceConfig(seed=2024, name="Livetest"),
        store=store,
    )
    return application.state.ultrasim.live.add(room)


# ----------------------------------------------------------------------
# Die Seite selbst
# ----------------------------------------------------------------------
def test_a_live_race_can_be_watched_without_having_been_computed(app, client):
    """Der Kern: Die Rennseite steht, bevor das Rennen gerechnet ist."""
    _room(app)
    page = client.get("/race/live-test")
    assert page.status_code == 200
    assert "live" in page.text


def test_the_page_says_that_it_is_live(app, client):
    _room(app)
    assert 'class="badge running"' in client.get("/race/live-test").text


def test_starting_a_broadcast_from_the_overview(app, client):
    """Der Knopf auf der Übersicht — bis zur laufenden Übertragung."""
    application, _, _ = app
    response = client.post(
        "/race/live", data={"route_id": "teststrecke", "riders": 6, "seed": 7}
    )
    assert response.status_code == 200  # TestClient folgt der Weiterleitung
    ids = application.state.ultrasim.live.ids()
    assert ids == ["teststrecke-live-7"]
    assert "Starter" in client.get("/race/teststrecke-live-7").text


def test_two_broadcasts_of_the_same_race_do_not_share_a_key(app, client):
    """Zweimal starten heißt zwei Übertragungen, nicht eine überschriebene."""
    application, _, _ = app
    data = {"route_id": "teststrecke", "riders": 6, "seed": 7}
    client.post("/race/live", data=data)
    # Ohne einen einzigen Speichervorgang dazwischen: Belegt ist der
    # Schlüssel schon, weil das Rennen läuft.
    client.post("/race/live", data=data)
    assert "teststrecke-live-7-2" in application.state.ultrasim.live.ids()


# ----------------------------------------------------------------------
# Wiedergabe
# ----------------------------------------------------------------------
def test_the_board_fills_up_as_the_clock_moves(app, client):
    """Ein Bild zur Rennsekunde 0 und eines eine Stunde später."""
    _room(app)
    token = client.post("/api/race/live-test/session").json()["token"]

    client.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 0})
    early = client.get(f"/api/playback/{token}/frame").json()

    client.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 3600})
    later = client.get(f"/api/playback/{token}/frame").json()

    assert later["t_wall"] > early["t_wall"]
    assert later["field"]["started"] >= early["field"]["started"]
    ahead = max(row["dist_km"] for row in later["board"]["rows"])
    assert ahead > 0.0, "nach einer Stunde ist niemand losgefahren"


def test_a_live_session_starts_at_the_beginning(app, client):
    """Beim Live-Rennen gibt es nichts zu überspringen.

    Bei einem gespeicherten Rennen setzt die Uhr auf den Start des
    Favoriten — der ist beim Zeitfahren der letzte, und alles vor ihm
    ist längst gefahren. Live wäre das eine Aufforderung, Stunden
    vorzurechnen, die noch niemand gesehen hat.
    """
    _room(app)
    payload = client.post("/api/race/live-test/session").json()
    assert payload["live"] is True
    assert payload["session"]["sim_t"] == 0.0


def test_nothing_beyond_the_clock_is_computed(app, client):
    """Wer eine Stunde zusieht, bezahlt eine Stunde."""
    room = _room(app)
    token = client.post("/api/race/live-test/session").json()["token"]
    client.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 3600})
    client.get(f"/api/playback/{token}/frame")
    assert not room.finished
    assert room.live.sim_t < 2 * 3600.0


def test_the_saved_state_is_a_readable_race(app, client):
    """Der Zwischenstand auf der Platte lädt wie ein fertiges Rennen.

    Das ist die Zusicherung hinter „live speichern": Es entsteht kein
    zweites Dateiformat für halbe Rennen. Wer den Server abschießt,
    findet beim nächsten Start ein Rennen vor, dem nur das Ende fehlt.
    """
    _, store, _ = app
    room = _room(app)
    token = client.post("/api/race/live-test/session").json()["token"]
    client.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 1800})
    client.get(f"/api/playback/{token}/frame")
    room.save()

    again, route_id = store.load_race("live-test")
    assert route_id == "teststrecke"
    assert len(again.entries) == 8
    assert any(e.status == "RUN" for e in again.entries)
    assert again.telemetry.n_samples > 0
    # Und die Übersicht kommt damit klar, obwohl es keinen Sieger gibt.
    listed = {r["race_id"]: r for r in store.list_races()}
    assert listed["live-test"]["winner_time_s"] is None


def test_the_finished_live_race_is_stored_like_any_other(app, client):
    """Und am Ende steht ein ganz gewöhnliches Rennen auf der Platte."""
    _, store, _ = app
    room = _room(app)
    room.advance(1e9)
    assert room.finished
    room.save()

    again, _ = store.load_race("live-test")
    assert all(e.status in ("FIN", "DNF", "OTL") for e in again.entries)
    assert again.winner_time_s is not None


def test_a_started_broadcast_shows_up_on_the_overview(app, client):
    """Zurückgehen darf die Übertragung nicht verschlucken.

    Bis zur ersten Sicherung existiert kein ``race.json`` — die
    Übersicht liest aber Dateien. Ein gerade gestartetes Rennen wäre
    damit unsichtbar, obwohl es läuft.
    """
    client.post("/race/live", data={"route_id": "teststrecke", "riders": 6, "seed": 3})
    page = client.get("/")
    assert "teststrecke-live-3" in page.text
    assert 'class="badge running"' in page.text


def test_the_overview_prefers_the_running_race_over_its_file(app, client):
    """Eine Zeile je Rennen, und zwar die aus dem Speicher."""
    _room(app)
    application, _, _ = app
    application.state.ultrasim.live.get("live-test").save()
    assert client.get("/").text.count(">live-test<") <= 1


# ----------------------------------------------------------------------
# Eine Übertragung beenden
# ----------------------------------------------------------------------
def test_a_broadcast_can_be_ended_from_the_page(client, app):
    """Beenden gibt den Platz frei, ohne das Rennen zu verlieren.

    Die Registry deckelt bei drei laufenden Rennen. Ohne diesen Weg
    wäre die Grenze eine Sackgasse, aus der nur ein Neustart führt.
    """
    _room(app, "zumbeenden")
    application, store, _ = app
    assert application.state.ultrasim.live.get("zumbeenden") is not None

    # Etwas rechnen lassen, damit es einen Stand gibt, der zu sichern ist.
    token = client.post("/api/race/zumbeenden/session").json()["token"]
    client.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 900.0})

    closed = client.post("/race/zumbeenden/close", follow_redirects=False)
    assert closed.status_code == 303
    assert application.state.ultrasim.live.get("zumbeenden") is None

    # Das Rennen ist danach ein ganz gewöhnliches gerechnetes Rennen.
    assert any(r["race_id"] == "zumbeenden" for r in store.list_races())
    assert client.get("/race/zumbeenden").status_code == 200
    assert client.get("/race/zumbeenden/results").status_code == 200


def test_ending_a_race_that_is_not_running_says_so(client, app):
    _room(app, "laeuft")
    assert client.post("/race/gibtsnicht/close").status_code == 404


def test_the_overview_offers_the_button_only_while_it_runs(client, app):
    _room(app, "sichtbar")
    page = client.get("/").text
    assert "Übertragung beenden" in page
    client.post("/race/sichtbar/close", follow_redirects=False)
    assert "Übertragung beenden" not in client.get("/").text
