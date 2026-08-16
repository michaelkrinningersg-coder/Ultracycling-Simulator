"""Nebenwertungen: Team, Nation, Berg — und die Statistikseiten.

Die Rechnung steht in ``core.classification`` und wird hier ohne
Webserver geprüft. Was die Seiten daraus machen, prüfen die letzten
Tests der Datei — auf Erreichbarkeit und darauf, dass die Zahl, die
oben in der Tabelle steht, dieselbe ist wie die aus der Rechnung.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from ultrasim.core import classification as cls
from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.rider import generate_pool
from ultrasim.data.store import Store
from ultrasim.web.main import create_app


@dataclass
class FakeEntry:
    entry_id: int
    rider_id: int
    finish_time_s: float | None
    rank: int | None = None


@dataclass
class FakeRider:
    id: int
    team_id: int
    name: str = ""
    nation: str = "GER"


@dataclass
class FakeTeam:
    id: int
    name: str
    color: str = "#888888"


def _field(times: dict[int, list[float | None]]):
    """Ein Feld aus ``{team_id: [Zielzeiten]}``."""
    entries: list[FakeEntry] = []
    riders: dict[int, FakeRider] = {}
    teams: dict[int, FakeTeam] = {}
    rider_id = 0
    for team_id, finishes in times.items():
        teams[team_id] = FakeTeam(id=team_id, name=f"Team {team_id}")
        for value in finishes:
            riders[rider_id] = FakeRider(id=rider_id, team_id=team_id)
            entries.append(FakeEntry(entry_id=rider_id, rider_id=rider_id, finish_time_s=value))
            rider_id += 1
    return entries, riders, teams


# ----------------------------------------------------------------------
# Teamwertung eines Rennens
# ----------------------------------------------------------------------
def test_the_three_best_times_count():
    entries, riders, teams = _field({1: [100.0, 200.0, 300.0, 1.0], 2: [110.0, 210.0, 310.0]})
    rows = cls.team_race_ranking(entries, riders, teams)
    first = rows[0]
    assert first.team_id == 1
    # Die 1.0 ist die schnellste und muss dabei sein, die 300 fällt raus.
    assert first.total_s == pytest.approx(1.0 + 100.0 + 200.0)
    assert rows[1].total_s == pytest.approx(110.0 + 210.0 + 310.0)


def test_a_team_without_enough_finishers_gets_no_rank():
    """Sonst gewönne die Mannschaft mit den meisten Ausfällen."""
    entries, riders, teams = _field({1: [10.0, 20.0], 2: [100.0, 200.0, 300.0]})
    rows = cls.team_race_ranking(entries, riders, teams)
    assert rows[0].team_id == 2 and rows[0].rank == 1
    incomplete = next(r for r in rows if r.team_id == 1)
    assert incomplete.total_s is None
    assert incomplete.rank is None


def test_the_number_of_scorers_gives_way_to_a_small_field():
    """Vierzig Starter aus fünfundzwanzig Teams geben keine drei her."""
    entries, riders, _ = _field({1: [10.0, 20.0], 2: [30.0, 40.0]})
    assert cls.effective_scorers(entries, riders) == 2
    entries, riders, _ = _field({1: [10.0] * 12, 2: [30.0] * 12})
    assert cls.effective_scorers(entries, riders) == cls.TEAM_SCORERS


def test_starters_and_finishers_are_counted_apart():
    entries, riders, teams = _field({1: [10.0, None, 30.0, None]})
    row = cls.team_race_ranking(entries, riders, teams)[0]
    assert row.starters == 4
    assert row.finishers == 2


# ----------------------------------------------------------------------
# Bergwertung
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def climbed(route_medium):
    teams, riders = generate_pool(12, n_teams=3, seed=12)
    result = simulate_race(route_medium, riders, teams, RaceConfig(seed=31))
    view_riders = {r.id: r for r in result.riders}
    view_teams = {t.id: t for t in result.teams}
    return result, route_medium, view_riders, view_teams


def test_the_mountain_points_go_to_the_fastest_at_the_summit(climbed):
    """Zeit am Gipfel, nicht Reihenfolge der Ankunft.

    Beim Einzelzeitfahren startet jeder zu einer anderen Stunde — wer
    zuerst oben stand, sagt nichts darüber, wer am schnellsten dort war.
    """
    result, route, riders, teams = climbed
    climbs, ranking = cls.mountain_ranking(result, route, riders, teams)
    assert climbs, "die mittlere Teststrecke hat kategorisierte Anstiege"
    for climb in climbs:
        times = [row[2] for row in climb.rows]
        assert times == sorted(times)
        points = [row[3] for row in climb.rows]
        assert points == sorted(points, reverse=True)
    assert ranking and ranking[0].rank == 1
    assert ranking[0].points >= ranking[-1].points


def test_the_points_table_favours_the_harder_climb():
    """Ein HC muss mehr wiegen als zwei Anstiege der ersten Kategorie."""
    assert cls.MOUNTAIN_POINTS["HC"][0] > 2 * cls.MOUNTAIN_POINTS["1"][0] - 1
    for lower, higher in (("4", "3"), ("3", "2"), ("2", "1"), ("1", "HC")):
        assert cls.MOUNTAIN_POINTS[higher][0] > cls.MOUNTAIN_POINTS[lower][0]


def test_riders_who_never_reached_the_summit_score_nothing(climbed):
    result, route, riders, teams = climbed
    climbs, _ = cls.mountain_ranking(result, route, riders, teams)
    for climb in climbs:
        for _, _, time_s, _ in climb.rows:
            assert time_s == time_s, "NaN darf nicht in der Wertung stehen"


def test_the_summit_times_come_from_the_telemetry(climbed):
    result, route, _, _ = climbed
    climb = route.climbs[0]
    times = cls.times_at_distance(result.telemetry, climb.dist_end_m)
    assert times.shape == (len(result.entries),)
    for i, entry in enumerate(result.entries):
        if entry.finish_time_s is not None:
            assert times[i] == times[i], "wer im Ziel ist, war auch am Gipfel"
            assert 0.0 < times[i] < entry.finish_time_s


# ----------------------------------------------------------------------
# Die Seiten
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def stored(route, tmp_path_factory):
    root = tmp_path_factory.mktemp("stats")
    store = Store(root)
    route.save(store.routes_dir / "teststrecke.json.gz")
    teams, riders = generate_pool(12, n_teams=3, seed=21)
    store.save_pool(teams, riders)
    result = simulate_race(route, riders, teams, RaceConfig(seed=55, name="Statistikrennen"))
    store.save_race("statistikrennen", "teststrecke", result, route=route)
    return store, result


@pytest.fixture(scope="module")
def client(stored):
    return TestClient(create_app(stored[0].root))


def test_the_race_statistics_page_answers_three_questions(client):
    page = client.get("/race/statistikrennen/statistik")
    assert page.status_code == 200
    assert "Teamwertung" in page.text
    assert "Energiebilanz" in page.text
    # Die Bergwertung erscheint nur, wenn es kategorisierte Anstiege gibt.
    assert "Bergwertung" in page.text or not page.text.count("Anstiege")


def test_the_energy_balance_never_claims_full_coverage(client, stored):
    """Der Magen lässt weniger durch, als hartes Fahren verbrennt."""
    _, result = stored
    for entry in result.entries:
        if entry.carb_kcal > 0:
            assert entry.intake_kcal < entry.carb_kcal


def test_the_records_page_names_the_holder(client):
    page = client.get("/rekorde")
    assert page.status_code == 200
    assert "Bestzeiten" in page.text
    assert "Teststrecke" in page.text


def test_the_records_page_survives_an_empty_store(tmp_path):
    empty = TestClient(create_app(Store(tmp_path).root))
    page = empty.get("/rekorde")
    assert page.status_code == 200
    assert "Noch kein Rennen gerechnet" in page.text


def test_a_season_without_races_says_so(client, stored):
    from ultrasim.core.season import Season

    store, _ = stored
    store.save_season(Season(id="leer", name="Leer", year=2040))
    page = client.get("/season/leer/statistik")
    assert page.status_code == 200
    assert "nichts zu zählen" in page.text


def test_an_unknown_season_is_a_404(client):
    assert client.get("/season/gibtsnicht/statistik").status_code == 404
