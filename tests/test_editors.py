"""Strecken-, Fahrer- und Team-Editor (M5b, Abschnitt 10.3).

Der wichtigste Test hier ist ``test_moving_a_split_leaves_computed_races
_alone``: Ein Editor, der rückwirkend die Ergebnisse früherer Rennen
verfälscht, wäre schlimmer als gar kein Editor.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.rider import ATTRIBUTES, WKG_RANGE, generate_pool
from ultrasim.data.store import Store
from ultrasim.geo.route import Route
from ultrasim.geo.splits import (
    MIN_MARKER_GAP_M,
    normalise_service_points,
    normalise_splits,
)
from ultrasim.web.main import create_app


@pytest.fixture
def app_store(route, tmp_path):
    store = Store(tmp_path)
    store.routes_dir.mkdir(parents=True, exist_ok=True)
    route.save(store.routes_dir / "teststrecke.json.gz")
    teams, riders = generate_pool(12, n_teams=3, seed=21)
    store.save_pool(teams, riders)
    return store


@pytest.fixture
def client(app_store):
    return TestClient(create_app(app_store.root))


# ----------------------------------------------------------------------
# Marker-Normalisierung
# ----------------------------------------------------------------------
def test_splits_are_sorted_and_renumbered():
    splits = normalise_splits(
        [(5000.0, "b", "interval"), (1000.0, "a", "summit")], 60_000.0
    )
    assert [s.idx for s in splits] == [0, 1, 2]
    assert [s.dist_m for s in splits] == [1000.0, 5000.0, 60_000.0]


def test_the_finish_is_always_last_and_at_the_end():
    """Die Zielzeit *ist* das Ergebnis — sie darf nicht verrutschen."""
    splits = normalise_splits([(59_000.0, "kurz vor Schluss", "finish")], 60_000.0)
    assert splits[-1].kind == "finish"
    assert splits[-1].dist_m == 60_000.0
    assert sum(1 for s in splits if s.kind == "finish") == 1


def test_a_finish_split_cannot_be_smuggled_in_twice():
    splits = normalise_splits(
        [(10_000.0, "A", "finish"), (20_000.0, "B", "finish")], 60_000.0
    )
    assert sum(1 for s in splits if s.kind == "finish") == 1


def test_markers_too_close_together_are_dropped():
    splits = normalise_splits(
        [(10_000.0, "A", "interval"), (10_000.0 + MIN_MARKER_GAP_M / 2, "B", "interval")],
        60_000.0,
    )
    assert len(splits) == 2  # A plus Ziel


def test_markers_outside_the_route_are_dropped():
    splits = normalise_splits(
        [(-500.0, "davor", "interval"), (99_000.0, "dahinter", "interval")], 60_000.0
    )
    assert [s.kind for s in splits] == ["finish"]


def test_nameless_markers_get_a_name():
    splits = normalise_splits([(12_345.0, "  ", "interval")], 60_000.0)
    assert splits[0].name == "km 12"
    points = normalise_service_points([(20_000.0, "")], 60_000.0)
    assert points[0].name == "SP 1"


def test_a_route_without_service_points_is_allowed():
    """Dann fährt das Feld eben durch — das ist eine Streckeneigenschaft."""
    assert normalise_service_points([], 60_000.0) == []


# ----------------------------------------------------------------------
# Streckenkopie je Rennen
# ----------------------------------------------------------------------
def test_a_race_keeps_the_route_it_was_run_on(app_store, route):
    result = simulate_race(
        route, *reversed(app_store.load_pool()), RaceConfig(seed=3, name="Testlauf")
    )
    app_store.save_race("lauf", "teststrecke", result, route=route)
    assert (app_store.race_dir("lauf") / "route.json.gz").exists()

    kept = app_store.race_route("lauf", "teststrecke")
    assert [s.dist_m for s in kept.splits] == [s.dist_m for s in route.splits]


def test_moving_a_split_leaves_computed_races_alone(client, app_store, route):
    """Der eigentliche Grund für die Kopie.

    Ohne sie stünde nach einer Streckenänderung die Zeit von km 40 unter
    dem Namen "km 45" — und beim Löschen eines Splits passte nicht einmal
    mehr die Spaltenzahl der Splitzeiten.
    """
    teams, riders = app_store.load_pool()
    result = simulate_race(route, riders, teams, RaceConfig(seed=3, name="Testlauf"))
    app_store.save_race("lauf", "teststrecke", result, route=route)
    before = [s.dist_m for s in route.splits]

    # Alle Zwischensplits um 500 m verschieben
    payload = {
        "route_id": "teststrecke",
        "name": route.name,
        "splits": [
            {"dist_m": s.dist_m + 500.0, "name": s.name, "kind": s.kind}
            for s in route.splits
            if s.kind != "finish"
        ],
        "service_points": [],
    }
    assert client.post("/api/route/save", json=payload).status_code == 200

    changed = app_store.load_route("teststrecke")
    assert [s.dist_m for s in changed.splits] != before
    # Das Rennen sieht davon nichts.
    assert [s.dist_m for s in app_store.race_route("lauf", "teststrecke").splits] == before
    assert client.get("/race/lauf/results").status_code == 200
    assert client.get("/race/lauf/rider/0").status_code == 200


def test_an_old_race_without_a_snapshot_falls_back(app_store, route):
    teams, riders = app_store.load_pool()
    result = simulate_race(route, riders, teams, RaceConfig(seed=3))
    app_store.save_race("alt", "teststrecke", result)  # ohne route=
    assert not (app_store.race_dir("alt") / "route.json.gz").exists()
    assert app_store.race_route("alt", "teststrecke").distance_m == route.distance_m


# ----------------------------------------------------------------------
# Streckeneditor über die Web-Schicht
# ----------------------------------------------------------------------
def test_routes_page_lists_and_links(client):
    page = client.get("/routes")
    assert page.status_code == 200
    assert "teststrecke" in page.text
    assert "GPX importieren" in page.text


def test_the_editor_shows_the_route(client):
    page = client.get("/route/teststrecke")
    assert page.status_code == 200
    assert "route-data" in page.text
    assert "Servicepunkte" in page.text


def test_importing_a_gpx_lands_in_the_editor_without_saving(client, app_store, demo_gpx):
    with open(demo_gpx, "rb") as fh:
        page = client.post(
            "/routes/import",
            files={"gpx": ("test.gpx", fh, "application/gpx+xml")},
            data={"name": "Importiert"},
        )
    assert page.status_code == 200
    assert "Import — noch nicht gespeichert" in page.text
    # Noch nichts auf der Platte: Der Entwurf ist eine Vorschau.
    assert [r["id"] for r in app_store.list_routes()] == ["teststrecke"]


def test_a_broken_gpx_is_reported(client):
    page = client.post(
        "/routes/import",
        files={"gpx": ("kaputt.gpx", b"<gpx>keine Punkte</gpx>", "application/gpx+xml")},
        data={"name": ""},
    )
    assert page.status_code == 400


def test_an_empty_upload_is_reported(client):
    page = client.post(
        "/routes/import", files={"gpx": ("leer.gpx", b"", "application/gpx+xml")}
    )
    assert page.status_code == 400


def test_saving_a_draft_writes_the_route(client, app_store, demo_gpx):
    with open(demo_gpx, "rb") as fh:
        page = client.post(
            "/routes/import",
            files={"gpx": ("test.gpx", fh, "application/gpx+xml")},
            data={"name": "Neue Strecke"},
        )
    token = page.url.path.rsplit("/", 1)[-1]

    res = client.post(
        "/api/route/save",
        json={
            "draft_token": token,
            "id": "neue-strecke",
            "name": "Neue Strecke",
            "splits": [{"dist_m": 5000.0, "name": "km 5", "kind": "interval"}],
            "service_points": [{"dist_m": 20000.0, "name": "SP 1"}],
        },
    )
    assert res.status_code == 200, res.text
    saved = app_store.load_route("neue-strecke")
    assert saved.name == "Neue Strecke"
    assert [s.kind for s in saved.splits] == ["interval", "finish"]
    assert len(saved.service_points) == 1
    # Der Entwurf ist verbraucht.
    assert client.get(f"/routes/draft/{token}").status_code == 404


def test_a_draft_can_be_discarded(client, app_store, demo_gpx):
    with open(demo_gpx, "rb") as fh:
        page = client.post(
            "/routes/import", files={"gpx": ("test.gpx", fh, "application/gpx+xml")}
        )
    token = page.url.path.rsplit("/", 1)[-1]
    client.post(f"/routes/draft/{token}/discard")
    assert client.get(f"/routes/draft/{token}").status_code == 404
    assert len(app_store.list_routes()) == 1


def test_an_expired_draft_says_so(client):
    assert client.get("/routes/draft/gibtsnicht").status_code == 404


def test_a_new_route_does_not_overwrite_an_existing_one(client, demo_gpx):
    with open(demo_gpx, "rb") as fh:
        page = client.post(
            "/routes/import", files={"gpx": ("test.gpx", fh, "application/gpx+xml")}
        )
    token = page.url.path.rsplit("/", 1)[-1]
    res = client.post(
        "/api/route/save",
        json={"draft_token": token, "id": "teststrecke", "name": "Kollision", "splits": []},
    )
    assert res.status_code == 409


def test_editing_keeps_the_geometry(client, app_store):
    """Der Editor bewegt Marker, keine Höhenpunkte."""
    before = app_store.load_route("teststrecke")
    client.post(
        "/api/route/save",
        json={
            "route_id": "teststrecke",
            "name": "Umbenannt",
            "splits": [{"dist_m": 1000.0, "name": "Start+1", "kind": "control"}],
            "service_points": [],
        },
    )
    after = app_store.load_route("teststrecke")
    assert after.name == "Umbenannt"
    assert after.distance_m == before.distance_m
    assert len(after.segments) == len(before.segments)
    assert len(after.climbs) == len(before.climbs)
    assert [s.name for s in after.splits] == ["Start+1", "Ziel"]


def test_a_route_needs_a_name(client):
    res = client.post(
        "/api/route/save", json={"route_id": "teststrecke", "name": "   ", "splits": []}
    )
    assert res.status_code == 400


def test_deleting_a_route(client, app_store):
    client.post("/route/teststrecke/delete")
    assert app_store.list_routes() == []


# ----------------------------------------------------------------------
# Fahrereditor
# ----------------------------------------------------------------------
def test_pool_page_shows_the_field(client):
    page = client.get("/pool")
    assert page.status_code == 200
    assert "Potenzial" in page.text
    assert "Teams" in page.text


def test_pool_page_offers_a_generator_when_empty(client, app_store):
    app_store.pool_path.unlink()
    page = client.get("/pool")
    assert "Noch kein Fahrerpool" in page.text


def test_editing_a_rider(client, app_store):
    res = client.post(
        "/pool/rider/0",
        json={
            "name": "Neuer Name",
            "nation": "ger",
            "team_id": 1,
            "age": 29,
            "height_cm": 180.0,
            "weight_kg": 70.0,
            "ftp_w": 320.0,
            "archetype": "kletterer",
            "attributes": {"berg": 88.0},
        },
    )
    assert res.status_code == 200
    _, riders = app_store.load_pool()
    rider = next(r for r in riders if r.id == 0)
    assert rider.name == "Neuer Name"
    assert rider.nation == "GER"
    assert rider.age == 29
    assert rider.archetype == "kletterer"
    assert rider.attr("berg") == 88.0


def test_a_rider_stays_physiologically_plausible(client, app_store):
    """Auch von Hand darf niemand ein Motor werden (Abschnitt 5.3)."""
    client.post(
        "/pool/rider/0",
        json={"weight_kg": 70.0, "ftp_w": 900.0, "attributes": {"berg": 500.0}},
    )
    _, riders = app_store.load_pool()
    rider = next(r for r in riders if r.id == 0)
    assert WKG_RANGE[0] <= rider.wkg <= WKG_RANGE[1]
    assert rider.attr("berg") <= 99.0


def test_unknown_attributes_are_ignored(client, app_store):
    client.post("/pool/rider/0", json={"attributes": {"fliegen": 99.0}})
    _, riders = app_store.load_pool()
    assert "fliegen" not in next(r for r in riders if r.id == 0).attributes
    assert set(next(r for r in riders if r.id == 0).attributes) == set(ATTRIBUTES)


def test_editing_a_rider_does_not_touch_a_computed_race(client, app_store, route):
    teams, riders = app_store.load_pool()
    result = simulate_race(route, riders, teams, RaceConfig(seed=3))
    app_store.save_race("lauf", "teststrecke", result, route=route)
    before = next(r for r in result.riders if r.id == 0).ftp_w

    client.post("/pool/rider/0", json={"ftp_w": 260.0, "weight_kg": 70.0})
    again, _ = app_store.load_race("lauf")
    assert next(r for r in again.riders if r.id == 0).ftp_w == before


def test_generating_riders_appends_to_the_pool(client, app_store):
    _, before = app_store.load_pool()
    client.post(
        "/pool/generate",
        data={"count": "5", "archetype": "kletterer", "team_id": "-1",
              "potential_mean": "50", "seed": "7"},
    )
    _, after = app_store.load_pool()
    assert len(after) == len(before) + 5
    assert all(r.archetype == "kletterer" for r in after[-5:])
    # IDs bleiben eindeutig – sonst kollidieren Fahrer im nächsten Rennen.
    assert len({r.id for r in after}) == len(after)


def test_generating_into_an_empty_store_creates_teams(client, app_store):
    app_store.pool_path.unlink()
    client.post("/pool/generate", data={"count": "8", "seed": "3"})
    teams, riders = app_store.load_pool()
    assert teams and len(riders) >= 8


def test_deleting_a_rider(client, app_store):
    client.post("/pool/rider/0/delete")
    _, riders = app_store.load_pool()
    assert all(r.id != 0 for r in riders)


def test_resetting_the_pool(client, app_store):
    client.post("/pool/reset", data={"riders": "20", "teams": "4", "seed": "9"})
    teams, riders = app_store.load_pool()
    assert len(riders) == 20
    assert len(teams) == 4


# ----------------------------------------------------------------------
# Teameditor
# ----------------------------------------------------------------------
def test_editing_a_team(client, app_store):
    client.post(
        "/pool/team/0",
        data={"name": "Neues Team", "nation": "ita", "color": "#ff0000",
              "servicedisziplin": "90"},
    )
    teams, _ = app_store.load_pool()
    team = next(t for t in teams if t.id == 0)
    assert team.name == "Neues Team"
    assert team.nation == "ITA"
    assert team.servicedisziplin == 90.0
    # Servicedisziplin 90 heißt kürzere Stopps – das ist ihr ganzer Zweck.
    assert team.service_factor < 1.0


def test_adding_a_team(client, app_store):
    before, _ = app_store.load_pool()
    client.post("/pool/team", data={"name": "Zusatzteam"})
    teams, _ = app_store.load_pool()
    assert len(teams) == len(before) + 1
    assert any(t.name == "Zusatzteam" for t in teams)


def test_dissolving_a_team_moves_its_riders(client, app_store):
    _, riders = app_store.load_pool()
    orphans = {r.id for r in riders if r.team_id == 0}
    assert orphans

    client.post("/pool/team/0/delete")
    teams, riders = app_store.load_pool()
    assert all(t.id != 0 for t in teams)
    # Kein Fahrer bleibt ohne Team zurück.
    known = {t.id for t in teams}
    assert all(r.team_id in known for r in riders)


def test_the_last_team_cannot_be_dissolved(client, app_store):
    teams, riders = app_store.load_pool()
    app_store.save_pool(teams[:1], riders)
    assert client.post(f"/pool/team/{teams[0].id}/delete").status_code == 400


def test_the_saved_route_still_simulates(client, app_store, route):
    """Nach dem Editor muss die Strecke noch ein Rennen tragen."""
    client.post(
        "/api/route/save",
        json={
            "route_id": "teststrecke",
            "name": "Editiert",
            "splits": [
                {"dist_m": 15_000.0, "name": "km 15", "kind": "interval"},
                {"dist_m": 40_000.0, "name": "Gipfel", "kind": "summit"},
            ],
            "service_points": [{"dist_m": 30_000.0, "name": "SP 1"}],
        },
    )
    edited = app_store.load_route("teststrecke")
    teams, riders = app_store.load_pool()
    result = simulate_race(edited, riders, teams, RaceConfig(seed=5))
    assert result.split_times_s.shape[1] == 3
    assert all(e.finish_time_s for e in result.entries)


def test_route_payload_survives_a_roundtrip(app_store):
    """Was der Editor zeichnet, muss zu dem passen, was gespeichert ist."""
    from ultrasim.web.routers.routes import route_payload

    route: Route = app_store.load_route("teststrecke")
    payload = route_payload(route)
    assert payload["distance_m"] == route.distance_m
    assert len(payload["splits"]) == len(route.splits)
    assert len(payload["profile"]["dist_m"]) == len(payload["profile"]["ele_m"])
    assert payload["profile"]["dist_m"][0] == 0
    assert payload["profile"]["dist_m"][-1] <= route.distance_m
