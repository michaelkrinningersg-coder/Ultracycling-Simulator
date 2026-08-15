"""Kalender-Editor, Saisonbetrieb und Fahrerentwicklung über die Web-Schicht.

Die Tests fahren den Editor so, wie ein Nutzer ihn bedient: Formular
abschicken, Weiterleitung folgen, Ergebnis auf der Seite nachlesen. Das
prüft nebenbei die Verdrahtung von Route, Vorlage und Speicher in einem
Zug — genau die Stellen, an denen ein Editor gern auseinanderfällt.
"""

from __future__ import annotations

import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from ultrasim import season_runner as runner
from ultrasim.core.season import CalendarRace, Season
from ultrasim.data.store import Store
from ultrasim.web.main import create_app


@pytest.fixture
def app_store(route, tmp_path):
    """Frisches Datenverzeichnis mit einer Strecke und einem Pool."""
    from ultrasim.core.rider import generate_pool

    store = Store(tmp_path)
    store.routes_dir.mkdir(parents=True, exist_ok=True)
    route.save(store.routes_dir / "teststrecke.json.gz")
    teams, riders = generate_pool(12, n_teams=3, seed=21)
    store.save_pool(teams, riders)
    return store


@pytest.fixture
def client(app_store):
    return TestClient(create_app(app_store.root))


def _wait_for_jobs(client: TestClient, season_id: str, timeout: float = 120.0) -> list[dict]:
    """Warten, bis die Warteschlange leer ist.

    Die Rechnung läuft in einem Hintergrundthread; ohne dieses Warten
    prüfte der Test den Zustand vor dem Ergebnis.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = client.get(f"/api/season/{season_id}/jobs").json()
        if jobs and all(job["done"] for job in jobs):
            return jobs
        time.sleep(0.2)
    raise AssertionError("Rechenauftrag wurde nicht fertig")


# ----------------------------------------------------------------------
# Editor
# ----------------------------------------------------------------------
def test_seasons_page_works_without_any_season(client):
    page = client.get("/seasons")
    assert page.status_code == 200
    assert "Neue Saison" in page.text


def test_creating_a_season_lands_on_its_calendar(client):
    page = client.post(
        "/seasons", data={"name": "Weltserie", "year": "2030", "n_races": "3"}
    )
    assert page.status_code == 200  # nach der Weiterleitung
    assert "Kalender" in page.text
    assert "Weltserie" in page.text


def test_a_season_name_becomes_a_stable_key(client, app_store):
    client.post("/seasons", data={"name": "Große Tour", "year": "2030", "n_races": "0"})
    assert [s["id"] for s in app_store.list_seasons()] == ["2030-grosse-tour"]


def test_the_same_season_cannot_be_created_twice(client):
    data = {"name": "Weltserie", "year": "2030", "n_races": "0"}
    assert client.post("/seasons", data=data).status_code == 200
    assert client.post("/seasons", data=data, follow_redirects=False).status_code == 409


def test_adding_and_editing_a_race(client, app_store):
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    sid = "2030-s"

    client.post(
        f"/season/{sid}/race",
        data={
            "name": "Auftakt",
            "route_id": "teststrecke",
            "day": "2030-04-14",
            "n_riders": "8",
            "seed": "5",
            "weather_preset": "",
        },
    )
    season = app_store.load_season(sid)
    assert len(season.races) == 1
    entry = season.races[0]
    assert entry.name == "Auftakt" and entry.n_riders == 8 and entry.seed == 5

    client.post(
        f"/season/{sid}/race/{entry.id}",
        data={
            "name": "Auftakt neu",
            "route_id": "teststrecke",
            "day": "2030-05-02",
            "n_riders": "10",
            "seed": "6",
            "weather_preset": "hitze",
            "coefficient": "1.5",
        },
    )
    entry = app_store.load_season(sid).races[0]
    assert entry.name == "Auftakt neu"
    assert entry.day == date(2030, 5, 2)
    assert entry.weather_preset == "hitze"
    assert entry.coefficient == 1.5


def test_two_races_with_the_same_name_get_different_keys(client, app_store):
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    for day in ("2030-04-14", "2030-06-14"):
        client.post(
            "/season/2030-s/race",
            data={
                "name": "Rundfahrt",
                "route_id": "teststrecke",
                "day": day,
                "n_riders": "8",
                "seed": "1",
                "weather_preset": "",
            },
        )
    keys = [r.id for r in app_store.load_season("2030-s").races]
    assert len(set(keys)) == 2


def test_deleting_a_race_keeps_the_computed_result(client, app_store):
    """Einen Termin aus dem Kalender zu nehmen ist Planung, nicht Löschen."""
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    client.post(
        "/season/2030-s/race",
        data={
            "name": "Lauf",
            "route_id": "teststrecke",
            "day": "2030-04-14",
            "n_riders": "6",
            "seed": "1",
            "weather_preset": "",
        },
    )
    key = app_store.load_season("2030-s").races[0].id
    client.post(f"/season/2030-s/race/{key}/run")
    _wait_for_jobs(client, "2030-s")
    race_id = app_store.load_season("2030-s").race(key).race_id
    assert race_id

    client.post(f"/season/2030-s/race/{key}/delete")
    assert app_store.load_season("2030-s").races == []
    assert app_store.race_dir(race_id).exists()


def test_resetting_a_race_frees_the_slot_and_drops_the_result(client, app_store):
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    client.post(
        "/season/2030-s/race",
        data={
            "name": "Lauf",
            "route_id": "teststrecke",
            "day": "2030-04-14",
            "n_riders": "6",
            "seed": "1",
            "weather_preset": "",
        },
    )
    key = app_store.load_season("2030-s").races[0].id
    client.post(f"/season/2030-s/race/{key}/run")
    _wait_for_jobs(client, "2030-s")
    race_id = app_store.load_season("2030-s").race(key).race_id

    client.post(f"/season/2030-s/race/{key}/reset")
    assert app_store.load_season("2030-s").race(key).race_id is None
    assert not app_store.race_dir(race_id).exists()


# ----------------------------------------------------------------------
# Rechnen
# ----------------------------------------------------------------------
def test_running_a_race_fills_the_calendar_and_the_standings(client, app_store):
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    client.post(
        "/season/2030-s/race",
        data={
            "name": "Lauf",
            "route_id": "teststrecke",
            "day": "2030-04-14",
            "n_riders": "8",
            "seed": "3",
            "weather_preset": "",
        },
    )
    client.post("/season/2030-s/race/lauf/run")
    jobs = _wait_for_jobs(client, "2030-s")
    assert jobs[0]["state"] == "fertig", jobs[0]["error"]
    assert jobs[0]["result"]["n_entries"] == 8

    page = client.get("/season/2030-s")
    assert "Gesamtwertung" in page.text
    standings = runner.standings(app_store, app_store.load_season("2030-s"))
    assert standings and standings[0].rank == 1
    assert standings[0].points > 0


def test_a_race_is_not_queued_twice(client, app_store):
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    client.post(
        "/season/2030-s/race",
        data={
            "name": "Lauf",
            "route_id": "teststrecke",
            "day": "2030-04-14",
            "n_riders": "6",
            "seed": "1",
            "weather_preset": "",
        },
    )
    client.post("/season/2030-s/race/lauf/run")
    client.post("/season/2030-s/race/lauf/run")
    _wait_for_jobs(client, "2030-s")
    assert len(client.get("/api/season/2030-s/jobs").json()) == 1


def test_run_all_computes_every_open_date(client, app_store):
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    for i, day in enumerate(("2030-04-14", "2030-05-14")):
        client.post(
            "/season/2030-s/race",
            data={
                "name": f"Lauf {i + 1}",
                "route_id": "teststrecke",
                "day": day,
                "n_riders": "6",
                "seed": str(i + 1),
                "weather_preset": "",
            },
        )
    client.post("/season/2030-s/run-all")
    jobs = _wait_for_jobs(client, "2030-s")
    assert len(jobs) == 2
    assert all(job["state"] == "fertig" for job in jobs), jobs
    assert not runner.pending_races(app_store.load_season("2030-s"))


def test_the_second_race_of_a_season_starts_tired(client, app_store):
    """Der eigentliche Sinn des Kalenders: das Vorrennen wirkt nach."""
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    for i, day in enumerate(("2030-04-14", "2030-04-21")):
        client.post(
            "/season/2030-s/race",
            data={
                "name": f"Lauf {i + 1}",
                "route_id": "teststrecke",
                "day": day,
                "n_riders": "8",
                "seed": "4",
                "weather_preset": "",
            },
        )
    client.post("/season/2030-s/run-all")
    _wait_for_jobs(client, "2030-s")

    season = app_store.load_season("2030-s")
    first, second = season.sorted_races()
    a = app_store.load_race_summary(first.race_id)
    b = app_store.load_race_summary(second.race_id)
    assert all(e.freshness == 1.0 for e in a.entries)
    assert all(e.freshness < 1.0 for e in b.entries)
    # Gleiche Strecke, gleicher Seed, gleiches Feld: Der Unterschied kann
    # nur aus der Restermüdung kommen.
    by_id = {e.rider_id: e.finish_time_s for e in a.entries}
    slower = [
        e.finish_time_s - by_id[e.rider_id]
        for e in b.entries
        if e.finish_time_s and by_id.get(e.rider_id)
    ]
    assert slower and min(slower) > 0.0


def test_a_failing_race_is_reported_not_swallowed(client, app_store):
    """Ein Termin auf eine gelöschte Strecke darf nicht still verschwinden."""
    season = Season(id="kaputt", name="Kaputt", year=2030)
    season.races.append(
        CalendarRace(
            id="x", name="X", route_id="gibtsnicht", day=date(2030, 4, 1), n_riders=4
        )
    )
    app_store.save_season(season)
    client.post("/season/kaputt/race/x/run")
    jobs = _wait_for_jobs(client, "kaputt")
    assert jobs[0]["state"] == "fehler"
    assert "gibtsnicht" in jobs[0]["error"]


# ----------------------------------------------------------------------
# Saisonwechsel
# ----------------------------------------------------------------------
def test_closing_a_season_ages_the_pool(client, app_store):
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    before = {r.id: r.age for r in app_store.load_pool()[1]}

    client.post("/season/2030-s/close", data={"seed": "1"})
    _wait_for_jobs(client, "2030-s")

    _, after = app_store.load_pool()
    for rider in after:
        if rider.id in before:
            assert rider.age == before[rider.id] + 1

    page = client.get("/season/2030-s/development")
    assert page.status_code == 200
    assert "Entwicklung im Einzelnen" in page.text


def test_the_development_page_works_before_any_season_change(client):
    client.post("/seasons", data={"name": "S", "year": "2030", "n_races": "0"})
    page = client.get("/season/2030-s/development")
    assert page.status_code == 200
    assert "noch kein saisonwechsel gerechnet" in page.text.lower()


# ----------------------------------------------------------------------
# Dienstschicht
# ----------------------------------------------------------------------
def test_suggested_calendar_leaves_more_room_after_long_races(app_store):
    """Die Pause kommt aus dem Erholungsfenster, nicht aus der Klasse.

    Vorher stand hier eine feste Untergrenze von vierzehn Tagen. Die war
    nie eine Aussage über den Kalender, sondern über eine Tabelle mit
    drei Einträgen — und die Distanzklasse „ultra" reicht von 1000 bis
    2500 km, also von drei bis viereinhalb Wochen Erholung. Geprüft wird
    deshalb das, worauf es ankommt: dass ein längeres Rennen mehr Luft
    hinterlässt als ein kürzeres.
    """
    calendar = runner.suggest_calendar(app_store, 2030, n_races=4)
    assert len(calendar) == 4
    assert len({r.id for r in calendar}) == 4
    gaps = [(b.day - a.day).days for a, b in zip(calendar, calendar[1:], strict=False)]
    assert all(gap > 0 for gap in gaps), "Termine dürfen sich nicht überholen"

    kurz = {"distance_km": 200.0, "ascent_m": 1500.0}
    lang = {"distance_km": 1200.0, "ascent_m": 12000.0}
    sehr_lang = {"distance_km": 2500.0, "ascent_m": 18000.0}
    assert runner._gap_after(kurz) < runner._gap_after(lang) < runner._gap_after(sehr_lang)


def test_carry_only_looks_backwards(app_store):
    season = Season(id="s", name="s", year=2030)
    season.races = [
        CalendarRace(id="a", name="a", route_id="teststrecke", day=date(2030, 4, 1)),
        CalendarRace(id="b", name="b", route_id="teststrecke", day=date(2030, 5, 1)),
    ]
    _, riders = app_store.load_pool()
    # Ohne gerechnete Rennen gibt es nichts zu schleppen.
    assert runner.carry_work_kj(app_store, season, season.races[0], riders) == {}
    assert runner.carry_work_kj(app_store, season, season.races[1], riders) == {}


def test_missing_races_do_not_break_the_standings(app_store):
    """Ein gelöschtes Rennen darf die Saisonseite nicht sprengen."""
    season = Season(id="s", name="s", year=2030)
    season.races = [
        CalendarRace(
            id="a",
            name="a",
            route_id="teststrecke",
            day=date(2030, 4, 1),
            race_id="weg",
        )
    ]
    app_store.save_season(season)
    assert runner.standings(app_store, season) == []
    assert runner.race_summaries(app_store, season) == {}
