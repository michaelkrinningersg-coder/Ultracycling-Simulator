"""Der Standardkalender und der Weg bis zum Ultrameister.

Diese Datei prüft keinen einzelnen Baustein, sondern den **Ablauf**:
Saison anlegen, ersten Termin rechnen, Ergebnis mit Saisonpunkten,
Rangliste, nächster Termin, und am Ende ein Titel. Jeder Schritt ist
für sich getestet — dass sie in dieser Reihenfolge zusammenpassen, war
es bis hierher nicht.

Gefahren wird auf einer Teststrecke statt auf den zehn echten: Die
Weltserie summiert sich auf elftausend Kilometer und rechnet
zwölf Minuten. Was hier geprüft wird, ist die Mechanik des Ablaufs,
nicht die Strecke — und die ist dieselbe.
"""

from __future__ import annotations

import shutil
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from ultrasim import season_runner as runner
from ultrasim.core import season as sn
from ultrasim.core.rider import generate_pool
from ultrasim.data.store import Store
from ultrasim.web.main import create_app


@pytest.fixture(scope="module")
def store(route, tmp_path_factory):
    root = tmp_path_factory.mktemp("weltserie")
    store = Store(root)
    store.routes_dir.mkdir(parents=True, exist_ok=True)
    route.save(store.routes_dir / "teststrecke.json.gz")
    teams, riders = generate_pool(12, n_teams=3, seed=21)
    store.save_pool(teams, riders)
    return store


@pytest.fixture(scope="module")
def client(store):
    return TestClient(create_app(store.root))


def _wait(client: TestClient, season_id: str, timeout: float = 180.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = client.get(f"/api/season/{season_id}/jobs").json()
        if jobs and all(job["done"] for job in jobs):
            assert all(job["state"] != "fehler" for job in jobs), jobs
            return
        time.sleep(0.2)
    raise AssertionError("Rechenauftrag wurde nicht fertig")


# ----------------------------------------------------------------------
# Der Kalender selbst
# ----------------------------------------------------------------------
def test_the_standard_calendar_spans_four_hundred_to_twentyfive_hundred(tmp_path):
    """Zehn Rennen, und zwar auf den zehn echten Strecken.

    Der einzige Test hier, der die ausgelieferten Streckendateien
    anfasst — er prüft genau das, was der Kalender verspricht: zehn
    verschiedene Strecken, keine unter 400 km, keine über 2500.
    """
    store = Store("data")
    calendar = runner.weltserie_calendar(store, 2031)
    assert len(calendar) == 10, "eine Strecke der Weltserie fehlt im Datenverzeichnis"
    assert len({r.route_id for r in calendar}) == 10

    routes = {r["id"]: r for r in store.list_routes()}
    km = [routes[r.route_id]["distance_km"] for r in calendar]
    assert 390.0 <= min(km) <= 410.0
    assert 2400.0 <= max(km) <= 2500.0
    # Steigende Distanz: Der Kalender ist ein Verlauf, keine Liste.
    assert km == sorted(km)


#: Die *gemessene* Arbeit eines Durchschnittsfahrers auf den acht
#: Strecken, für die ein gerechnetes Rennen vorliegt, in Megajoule.
#: Median über 250 Fahrer, Weltserie 2031, Seed 7.
#:
#: Sie steht hier als Zahlenreihe und nicht als Fixture, weil sie sonst
#: bei jedem Lauf zwölf Minuten kosten würde. Wer die Physik ändert,
#: muss sie neu erheben — und genau das soll dieser Test dann auch
#: verlangen.
GEMESSENE_ARBEIT_MJ = {
    "Atlantik-Zeitfahren": 6.5,
    "Ardennen-Wellenritt": 11.0,
    "Dolomiten-Vierpässe": 23.1,
    "Karpaten-Schotterrunde": 12.7,
    "Toskana-Hügelmarathon": 17.4,
    "Ostsee-Nachtfahrt": 17.7,
    "Pyrenäen-Traverse": 25.4,
    "Steppenroute Anatolien": 24.9,
}


def test_the_calendar_is_actually_rideable():
    """Kein Termin liegt im Erholungsfenster seines Vorgängers.

    Ein Kalender, der das verletzt, sieht auf der Seite gleich aus und
    lässt sich genauso rechnen — nur startet das ganze Feld angeschlagen,
    und niemand sieht, warum die Zeiten schlechter werden.

    Geprüft wird gegen die **gemessene** Arbeit, nicht gegen die
    Schätzung, mit der geplant wurde. Gegen die eigene Schätzung geht
    ein Plan immer auf; das wäre kein Test, sondern eine Tautologie —
    und genau daran ist die erste Fassung dieses Kalenders vorbeigelaufen.
    """
    store = Store("data")
    calendar = runner.weltserie_calendar(store, 2031)
    crowded = []
    for previous, current in zip(calendar, calendar[1:], strict=False):
        work_mj = GEMESSENE_ARBEIT_MJ.get(previous.name)
        if work_mj is None:
            continue
        needed = sn.recovery_days(work_mj * 1000.0, runner.NOMINAL_CAPACITY_KJ)
        gap = (current.day - previous.day).days
        if gap < needed:
            crowded.append(f"{current.name}: {gap} T Pause, nötig {needed:.1f} T")
    assert not crowded, crowded


def test_the_work_estimate_matches_the_measurements():
    """Die Schätzung, mit der geplant wird, gegen das, was herauskommt.

    Acht von zehn Strecken auf rund zehn Prozent. Die Dolomiten sind die
    Ausnahme und bleiben es: Trittfrequenz unter dem günstigen Bereich,
    anaerobe Rampen und ein Fünftel der Strecke über 1500 m stehen in
    keiner Formel aus Kilometern und Höhenmetern. Deshalb plant der
    Kalender mit ``CALENDAR_MARGIN``.
    """
    routes = {r["name"]: r for r in Store("data").list_routes()}
    errors = {}
    for name, measured_mj in GEMESSENE_ARBEIT_MJ.items():
        route = routes[name]
        estimate = runner.estimated_work_kj(route["distance_km"], route["ascent_m"])
        errors[name] = abs(estimate / 1000.0 - measured_mj) / measured_mj

    ohne_dolomiten = {k: v for k, v in errors.items() if "Dolomiten" not in k}
    assert max(ohne_dolomiten.values()) < 0.20, ohne_dolomiten
    # Und die Marge muss die verbleibende Lücke decken.
    assert runner.CALENDAR_MARGIN > 1.0


def test_the_calendar_fits_into_one_year():
    store = Store("data")
    calendar = runner.weltserie_calendar(store, 2031)
    assert calendar[0].day.year == calendar[-1].day.year == 2031
    assert (calendar[-1].day - calendar[0].day).days < 340


def test_the_longest_race_is_worth_the_most():
    """Der Ultra-Bonus, und warum er eine eigene Zusicherung braucht.

    Der Rennkoeffizient war bei 2,2 gekappt. Auf den bisherigen vier
    Strecken fiel das nicht auf — keine kam in die Nähe. Mit der
    Weltserie lagen die beiden längsten Rennen *beide* über der
    Kappung und waren damit exakt gleich viel wert: 1924 und 2469
    Kilometer, derselbe Koeffizient. Der Deckel hat gewertet, nicht die
    Formel.
    """
    store = Store("data")
    routes = {r["id"]: r for r in store.list_routes()}
    coefficient = {
        r.name: sn.race_coefficient(
            routes[r.route_id]["distance_km"], routes[r.route_id]["ascent_m"]
        )
        for r in runner.weltserie_calendar(store, 2031)
    }
    values = list(coefficient.values())
    assert values[-1] == max(values), "das Finale muss das wertvollste Rennen sein"
    assert values[-1] > values[-2], coefficient
    # Und die Spanne muss den Titel tragen: Ein Sieg auf der längsten
    # Strecke wiegt mehr als zwei auf der kürzesten.
    assert values[-1] / values[0] > 2.0


# ----------------------------------------------------------------------
# Der Ablauf
# ----------------------------------------------------------------------
def test_the_new_season_form_offers_the_standard_calendar(client):
    page = client.get("/seasons")
    assert 'value="weltserie"' in page.text
    assert "Ultrameister" in page.text


def test_race_by_race_to_the_title(client, store):
    """Der ganze Weg in einem Test.

    Drei Termine statt zehn — der Ablauf ist derselbe, und jedes weitere
    Rennen kostet nur Rechenzeit, ohne eine neue Aussage zu erzeugen.
    """
    season = sn.Season(id="2031-serie", name="Serie", year=2031)
    season.races = [
        sn.CalendarRace(
            id=f"{i:02d}-lauf",
            name=f"Lauf {i}",
            route_id="teststrecke",
            day=date(2031, 3 + i, 1),
            n_riders=12,
            seed=500 + i,
        )
        for i in (1, 2, 3)
    ]
    store.save_season(season)

    # --- vor dem ersten Rennen ---------------------------------------
    page = client.get("/season/2031-serie")
    assert page.status_code == 200
    assert "Noch kein Rennen der Saison gerechnet" in page.text
    assert "Ultrameister 2031" not in page.text, "der Titel steht noch nicht fest"

    seen: list[float] = []
    for i in (1, 2, 3):
        key = f"{i:02d}-lauf"
        # --- Termin auswählen und rechnen ----------------------------
        assert client.post(f"/season/2031-serie/race/{key}/run").status_code == 200
        _wait(client, "2031-serie")

        fresh = store.load_season("2031-serie")
        calendar_race = fresh.race(key)
        assert calendar_race.computed, f"Lauf {i} hat kein Rennen bekommen"

        # --- Ergebnis mit Saisonpunkten ------------------------------
        results = client.get(f"/race/{calendar_race.race_id}/results")
        assert results.status_code == 200

        # --- Rangliste nach diesem Rennen ----------------------------
        table = runner.standings(store, fresh)
        assert table, "nach einem gerechneten Rennen muss eine Wertung stehen"
        assert table[0].rank == 1
        assert table[0].starts == i, "jeder Lauf zählt als ein Start"
        assert table[0].points > 0.0
        seen.append(table[0].points)

        page = client.get("/season/2031-serie")
        assert table[0].name in page.text
        if i < 3:
            assert "Ultrameister 2031" not in page.text, "Titel zu früh vergeben"

    # Punkte können nur wachsen — jedes Rennen legt drauf.
    assert seen == sorted(seen)

    # --- der Titel ----------------------------------------------------
    page = client.get("/season/2031-serie")
    assert "Ultrameister 2031" in page.text
    final = runner.standings(store, store.load_season("2031-serie"))
    assert final[0].name in page.text
    assert f"{final[0].points:.0f}" in page.text


def test_the_title_disappears_again_when_a_result_is_discarded(client, store):
    """Wer ein Ergebnis verwirft, verliert den Titel wieder.

    Sonst stünde ein Ultrameister über einem Kalender mit einem offenen
    Termin — und niemand könnte sagen, worauf sich der Titel bezieht.
    """
    assert "Ultrameister 2031" in client.get("/season/2031-serie").text
    assert client.post("/season/2031-serie/race/03-lauf/reset").status_code == 200
    assert "Ultrameister 2031" not in client.get("/season/2031-serie").text


# ----------------------------------------------------------------------
# Erststart
# ----------------------------------------------------------------------
def test_the_first_start_lays_out_the_calendar_without_computing_it(tmp_path):
    """Der Kalender liegt bereit, gerechnet ist nichts.

    Beides ist wichtig. Ohne den Kalender steht der Nutzer vor einem
    leeren Editor; mit einem *gerechneten* Kalender stünde er eine
    Viertelstunde vor einem Ladebalken, bevor er das Programm zum ersten
    Mal gesehen hat.
    """
    from ultrasim.app import ensure_weltserie

    shutil.copytree("data/routes", tmp_path / "routes")
    season_id = ensure_weltserie(tmp_path, year=2031, verbose=False)
    assert season_id == "2031-weltserie"

    store = Store(tmp_path)
    season = store.load_season(season_id)
    assert len(season.races) == 10
    assert all(not r.computed for r in season.races)
    assert not (tmp_path / "races").exists() or not list((tmp_path / "races").iterdir())


def test_the_first_start_does_not_overwrite_an_existing_season(tmp_path):
    from ultrasim.app import ensure_weltserie

    shutil.copytree("data/routes", tmp_path / "routes")
    store = Store(tmp_path)
    store.save_season(sn.Season(id="meine", name="Meine", year=2030))
    assert ensure_weltserie(tmp_path, year=2031, verbose=False) is None
    assert [s["id"] for s in store.list_seasons()] == ["meine"]


def test_the_result_page_shows_what_the_race_was_worth(client, store):
    """Eine Ergebnisliste eines Saisonrennens ist keine Endstation.

    Ohne die Punktespalte beantwortet sie „wer war schneller" und hört
    dort auf. Mit ihr beantwortet sie die Frage, die im Kalender
    tatsächlich zählt: was hat dieses Rennen für die Saison verändert.
    """
    season = store.load_season("2031-serie")
    calendar_race = season.race("01-lauf")
    page = client.get(f"/race/{calendar_race.race_id}/results")
    assert page.status_code == 200
    assert "Punkte" in page.text
    assert "Rennkoeffizient" in page.text
    assert f'/season/{season.id}"' in page.text


def test_a_race_outside_a_season_shows_no_points(client, store):
    """Und ein Rennen ohne Termin bekommt keine erfundene Spalte."""
    from ultrasim.core.engine import RaceConfig, simulate_race

    teams, riders = store.load_pool()
    route = store.load_route("teststrecke")
    result = simulate_race(route, riders[:6], teams, RaceConfig(seed=99, name="Einzeln"))
    store.save_race("einzelrennen", "teststrecke", result, route=route)

    page = client.get("/race/einzelrennen/results")
    assert page.status_code == 200
    assert "Rennkoeffizient" not in page.text


# ----------------------------------------------------------------------
# Startreihenfolge
# ----------------------------------------------------------------------
def _start_order(store: Store, season: sn.Season, key: str) -> list[int]:
    """Fahrer-IDs eines gerechneten Termins, nach Startzeit."""
    summary = store.load_race_summary(season.race(key).race_id)
    return [e.rider_id for e in sorted(summary.entries, key=lambda e: e.start_offset_s)]


def test_the_first_race_starts_by_potential(client, store):
    """Am Auftakt gibt es keinen Saisonstand — es zählt die Einschätzung."""
    season = store.load_season("2031-serie")
    order = _start_order(store, season, "01-lauf")
    _, riders = store.load_pool()
    potential = {r.id: r.potential for r in riders}
    assert order == sorted(order, key=lambda rid: potential[rid])


def test_from_the_second_race_the_leader_starts_last(client, store):
    """Ab Rennen zwei startet der Saisonführende zuletzt.

    Geprüft wird an den gespeicherten Startzeiten, nicht an der Absicht:
    Die Rangliste nach dem Auftakt muss genau die umgekehrte Startliste
    des zweiten Laufs sein.
    """
    season = store.load_season("2031-serie")

    # Rangliste, wie sie vor dem zweiten Lauf stand: nur der Auftakt zählt.
    after_first = sn.Season(id=season.id, name=season.name, year=season.year)
    after_first.races = [season.race("01-lauf")]
    table = runner.standings(store, after_first)
    assert table, "der Auftakt muss eine Wertung ergeben haben"

    order = _start_order(store, season, "02-lauf")
    assert order[-1] == table[0].rider_id, "der Führende startet zuletzt"
    assert order == [s.rider_id for s in reversed(table)]

    # Und die Reihenfolge hat sich gegenüber dem Auftakt wirklich geändert.
    assert order != _start_order(store, season, "01-lauf")


def test_riders_without_points_start_first():
    """Wer noch keine Punkte hat, steht vor dem gewerteten Feld."""
    from ultrasim.core.rider import generate_pool

    _, riders = generate_pool(6, n_teams=2, seed=7)
    table = [
        sn.Standing(
            rider_id=r.id, name=r.name, nation=r.nation, team_id=r.team_id, team_name="T"
        )
        for r in riders[:3]
    ]
    order = runner.reverse_standings_order(riders, table)

    newcomers, ranked = order[:3], order[3:]
    assert {r.id for r in ranked} == {s.rider_id for s in table}
    assert [r.id for r in ranked] == [s.rider_id for s in reversed(table)]
    assert [r.potential for r in newcomers] == sorted(r.potential for r in newcomers)


# ----------------------------------------------------------------------
# Der Simulationshorizont
# ----------------------------------------------------------------------
def test_the_simulation_outlasts_the_time_limit():
    """Die Rechengrenze darf keine sportliche Regel sein.

    ``max_hours`` bestimmt, wie lange die Engine überhaupt rechnet; wer
    danach noch fährt, gilt als Ausfall. Die *sportliche* Grenze ist
    ``time_limit_factor`` — sie setzt zu langsame Fahrer auf OTL, und
    das ist ein Ergebnis, kein Abbruch.

    Ausgeschrieben ist die Bedingung eine zwischen zwei Zahlen. Der
    Horizont liegt bei ``äquivalent_km / 11``, die Zeitgrenze beim
    ``1,4``-fachen der Siegerzeit; er überlebt sie also genau dann, wenn
    der Sieger schneller als ``11 · 1,4 = 15,4`` km/h Äquivalenttempo
    fährt. Gemessen über den Weltserien-Kalender ist der langsamste
    Sieger die Dolomiten-Traverse mit 20,7 km/h — ein Drittel Luft.

    Solange der Horizont nur aus der **Distanz** kam, galt die Bedingung
    nicht: Auf den Dolomiten-Vierpässen lag er bei 52 Stunden, die
    Zeitgrenze aber erst bei 54. Die Folge waren 116 Fahrer mit dem
    Vermerk „Zeitrahmen überschritten", die Hälfte davon jenseits
    Kilometer 455 von 573 — sie waren nicht zu langsam für das Rennen,
    sondern für die Uhr des Programms.
    """
    from ultrasim.core.engine import HORIZON_KMH, RaceConfig

    #: Langsamster Sieger im Kalender, gemessen. Der Horizont muss ihn
    #: samt Zeitgrenze überdauern.
    slowest_winner_kmh = 20.7
    assert HORIZON_KMH * RaceConfig().time_limit_factor < slowest_winner_kmh

    # Und der Horizont muss die Höhenmeter überhaupt sehen: zwei
    # gleich lange Strecken, eine flach, eine bergig.
    flach = sn.effort_km(600.0, 1000.0) / HORIZON_KMH
    bergig = sn.effort_km(600.0, 12000.0) / HORIZON_KMH
    assert bergig > flach * 1.4


def test_a_mountain_race_is_not_cut_short(store):
    """Die Gegenprobe am gemessenen Rennen.

    Teuer, aber die einzige Form, die den Fehler wirklich ausschließt:
    Der Horizont lässt sich nur an einem gerechneten Rennen prüfen, weil
    genau die Fahrer betroffen waren, die es fast bis ins Ziel geschafft
    haben.
    """
    from collections import Counter

    from ultrasim.core.engine import RaceConfig, simulate_race
    from ultrasim.geo.route import Route

    route = Route.load("data/routes/dolomiten-vierpaesse.json.gz")
    teams, riders = generate_pool(24, n_teams=4, seed=21)
    result = simulate_race(route, riders, teams, RaceConfig(seed=2002))
    reasons = Counter(e.dnf_reason for e in result.entries if e.status == "DNF")
    n = len(result.entries)
    assert reasons["Zeitrahmen überschritten"] <= n // 10, dict(reasons)
    assert sum(1 for e in result.entries if e.status == "FIN") > n // 2


# ----------------------------------------------------------------------
# Aufgabe auf den Ultras
# ----------------------------------------------------------------------
def test_emergency_sleep_is_lost_time_but_not_a_deficit(store):
    """Notschlaf ist verlorene Zeit — aber kein Grund aufzugeben.

    Der Aufgabe-Term heißt „kein Anschluss mehr an den eigenen Plan" und
    meint laut seinem eigenen Kommentar den Satz eines Aussteigers:
    *drei Pannen und zweimal verfahren, das hole ich nicht mehr auf.*
    Gerechnet hat er mit ``lost_s`` — und darin steckt der Notschlaf.

    Gemessen über den Weltserien-Kalender: Bis 1463 km gibt es überhaupt
    keinen Notschlaf; ab 1924 km sind **85 % der verlorenen Zeit**
    Notschlaf (12,4 von 14,6 Stunden). Auf einer Strecke mit fünf
    Nächten ist Schlaf nicht das Scheitern des Plans, sondern der Plan —
    und er zählte doppelt, weil er über ``sleep_press`` bereits im
    Ermüdungsterm derselben Formel steckt.

    Geprüft wird die Trennung, nicht die Quote: Die Ergebnisliste sieht
    beides, die Aufgabe nur den Zwischenfallanteil.

    Seit den Ampeln hat ``lost_s`` einen dritten Anteil, der weder
    Zwischenfall noch Schlaf ist. Der Notschlafanteil ist deshalb, was
    nach Abzug beider anderen übrig bleibt — genau die Rechnung, die
    auch die Ergebnisliste anstellt.
    """
    from ultrasim.core.engine import RaceConfig, simulate_race
    from ultrasim.geo.route import Route

    teams, riders = generate_pool(10, n_teams=2, seed=21)

    def geschlafen_s(entry) -> float:
        return entry.lost_s - entry.lost_incident_s - entry.lost_signal_s

    kurz = store.load_route("teststrecke")
    ohne_nacht = simulate_race(kurz, riders, teams, RaceConfig(seed=4200))
    assert all(
        geschlafen_s(e) == pytest.approx(0.0, abs=0.01) for e in ohne_nacht.entries
    ), "ohne Nacht darf niemand am Straßenrand geschlafen haben"

    lang = Route.load("data/routes/alpenueberquerung.json.gz")
    mit_nacht = simulate_race(lang, riders, teams, RaceConfig(seed=4200))
    assert all(e.lost_incident_s <= e.lost_s + 0.01 for e in mit_nacht.entries)
    geschlafen = [e for e in mit_nacht.entries if geschlafen_s(e) > 3600.0]
    assert geschlafen, "auf 1924 km sollte jemand am Straßenrand geschlafen haben"


def test_the_time_limit_leaves_room_for_the_midfield():
    """Das Zeitlimit ist ein Netz, keine Sortierregel.

    Mit dem alten Faktor 1,4 fielen gemessen 32 % des Feldes auf den
    Dolomiten-Vierpässen aus der Wertung, 20 % auf der Alpenüberquerung
    und 16 % auf der Transkontinental — nicht weil sie das Rennen nicht
    zu Ende gefahren wären, sondern weil die Grenze knapp hinter dem
    Mittelfeld lag. 2,0 ist der Wert aus der Praxis: Paris–Brest–Paris
    gibt 90 Stunden auf eine Siegerzeit von gut 44.
    """
    from ultrasim.core.engine import HORIZON_KMH, RaceConfig

    faktor = RaceConfig().time_limit_factor
    assert faktor >= 2.0

    # Und der Simulationshorizont muss die angehobene Grenze überleben —
    # sonst ist der Fehler von vorhin zurück und die Rechnung hört vor
    # der Wertung auf. Langsamster gemessener Sieger: 20,7 km/h
    # Äquivalenttempo auf den Dolomiten-Vierpässen.
    assert HORIZON_KMH * faktor < 20.7


# ----------------------------------------------------------------------
# Verlauf der Gesamtwertung
# ----------------------------------------------------------------------
def test_the_standings_show_their_history(client, store):
    """Wer wann geführt hat — die Tabelle kennt nur den Schlussstand."""
    page = client.get("/season/2031-serie")
    assert page.status_code == 200
    assert "Verlauf der Gesamtwertung" in page.text
    assert "<polyline" in page.text


def test_a_single_race_is_no_history(tmp_path, route):
    """Mit einem Termin gibt es nichts zu verlaufen."""
    from ultrasim.web.routers.seasons import _standings_chart

    season = sn.Season(id="eins", name="Eins", year=2032)
    season.races = [
        sn.CalendarRace(
            id="01-lauf", name="Lauf", route_id="teststrecke",
            day=date(2032, 4, 1), race_id="irgendwas",
        )
    ]
    assert _standings_chart(season, []) is None


def test_the_history_starts_at_zero(store):
    """Die Linie beginnt beim Nullpunkt, nicht beim ersten Ergebnis.

    Sonst begänne der Auftaktsieger am linken Rand schon oben — und der
    Termin mit dem größten Sprung wäre der einzige, den man nicht sieht.
    """
    from ultrasim.web.routers.seasons import _standings_chart

    season = store.load_season("2031-serie")
    chart = _standings_chart(season, runner.standings(store, season))
    assert chart is not None
    for line in chart["lines"]:
        first = line["points"].split()[0]
        assert first.startswith("0.0,")
        # y = Höhe heißt: unten, also null Punkte.
        assert float(first.split(",")[1]) == chart["h"]


# ----------------------------------------------------------------------
# Live statt vorrechnen
# ----------------------------------------------------------------------
def test_a_calendar_race_can_be_ridden_live(client, store):
    """Der Weg, den das Programm anbietet: nichts vorrechnen, zusehen.

    Dasselbe Rennen wie über ``/run`` — dieselbe Aufstellung, derselbe
    Seed, dieselbe Restermüdung, weil beide Wege aus ``race_setup``
    kommen. Der Unterschied ist, wann gerechnet wird.
    """
    season = sn.Season(id="2033-live", name="Liveserie", year=2033)
    season.races = [
        sn.CalendarRace(
            id="01-lauf", name="Auftakt", route_id="teststrecke",
            day=date(2033, 4, 1), n_riders=8, seed=77,
        ),
        sn.CalendarRace(
            id="02-lauf", name="Zweiter", route_id="teststrecke",
            day=date(2033, 6, 1), n_riders=8, seed=78,
        ),
    ]
    store.save_season(season)

    started = client.post("/season/2033-live/race/01-lauf/live", follow_redirects=False)
    assert started.status_code == 303
    race_id = started.headers["location"].removeprefix("/race/")
    assert race_id == runner.race_id_for(season, season.race("01-lauf"))

    # Der Termin trägt den Verweis sofort — sonst wäre die laufende
    # Übertragung vom Kalender aus nicht wiederzufinden.
    assert store.load_season("2033-live").race("01-lauf").race_id == race_id
    assert client.get(f"/race/{race_id}").status_code == 200

    # … aber solange sie läuft, wird kein Titel vergeben.
    page = client.get("/season/2033-live")
    assert "Ultrameister" not in page.text
    assert "Zusehen" in page.text


def test_the_overview_offers_exactly_one_next_step(client, store):
    """Die Übersicht beantwortet eine Frage: Womit fängt man an?"""
    page = client.get("/")
    assert page.status_code == 200
    assert "Live starten" in page.text or "Zusehen" in page.text
    # Was früher alles hier stand, steht jetzt in der Kopfzeile.
    assert "Stand des Aufbaus" not in page.text


def test_starting_the_same_live_race_twice_does_not_restart_it(client, store):
    """Ein zweiter Klick führt zur laufenden Übertragung, nicht zu einer neuen."""
    first = client.post("/season/2033-live/race/01-lauf/live", follow_redirects=False)
    again = client.post("/season/2033-live/race/01-lauf/live", follow_redirects=False)
    assert first.headers["location"] == again.headers["location"]


def test_an_unknown_calendar_race_cannot_be_started(client):
    assert client.post("/season/2033-live/race/gibtsnicht/live").status_code == 404
