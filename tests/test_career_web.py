"""Karrieremodus über die Web-Schicht.

Wie bei den Saisontests wird der Modus so gefahren, wie ein Nutzer ihn
bedient: Formular abschicken, Weiterleitung folgen, Ergebnis auf der
Seite nachlesen. Der Jahreswechsel läuft dabei als echter
Hintergrundauftrag durch — mit derselben Warteschlange, die auch die
Rennen rechnet.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from ultrasim.core.rider import generate_pool
from ultrasim.data.store import Store
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


def _wait(client: TestClient, key: str, timeout: float = 120.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = client.get(f"/api/season/{key}/jobs").json()
        if jobs and all(job["done"] for job in jobs):
            return jobs
        time.sleep(0.2)
    raise AssertionError("Jahreswechsel wurde nicht fertig")


def _start(client: TestClient) -> str:
    page = client.post(
        "/careers", data={"name": "Weltserie", "year": "2030", "n_races": "2"}
    )
    assert page.status_code == 200
    return "weltserie"


# ----------------------------------------------------------------------
def test_the_career_page_works_without_any_career(client):
    page = client.get("/careers")
    assert page.status_code == 200
    assert "Neue Karriere" in page.text


def test_creating_a_career_lands_on_its_page(client):
    _start(client)
    page = client.get("/career/weltserie")
    assert page.status_code == 200
    assert "2030" in page.text
    assert "Jahreswechsel" in page.text


def test_an_unknown_career_is_a_404(client):
    assert client.get("/career/gibt-es-nicht").status_code == 404


def test_a_career_without_routes_is_refused(tmp_path, route):
    store = Store(tmp_path)
    teams, riders = generate_pool(4, n_teams=1, seed=3)
    store.save_pool(teams, riders)
    client = TestClient(create_app(store.root))
    page = client.post("/careers", data={"name": "X", "year": "2030", "n_races": "2"})
    assert page.status_code == 400


def test_closing_a_year_opens_the_next_one(client):
    career_id = _start(client)
    page = client.post(f"/career/{career_id}/close", data={"seed": "7"})
    assert page.status_code == 200
    jobs = _wait(client, career_id)
    assert all(job["state"] != "fehler" for job in jobs), jobs

    page = client.get(f"/career/{career_id}")
    assert "2031" in page.text
    assert "Wechsel 2030" in page.text


def test_the_rider_page_shows_the_years(client):
    career_id = _start(client)
    client.post(f"/career/{career_id}/close", data={"seed": "7"})
    _wait(client, career_id)

    store = Store(client.app.state.ultrasim.store.root)
    career = store.load_career(career_id)
    rider_id = career.chapters[0].development[0].rider_id

    page = client.get(f"/career/{career_id}/rider/{rider_id}")
    assert page.status_code == 200
    assert "Lebenslauf" in page.text
    assert "2030" in page.text
    assert client.get(f"/career/{career_id}/rider/99999").status_code == 404


def test_deleting_the_career_keeps_the_seasons(client):
    career_id = _start(client)
    store = Store(client.app.state.ultrasim.store.root)
    season_id = store.load_career(career_id).season_ids[0]

    page = client.post(f"/career/{career_id}/delete")
    assert page.status_code == 200
    assert not store.career_path(career_id).exists()
    # Die Saison enthält gerechnete Rennen — sie mit einem Klick
    # mitzulöschen wäre eine Falle.
    assert store.load_season(season_id).id == season_id
