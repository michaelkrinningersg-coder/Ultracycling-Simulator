"""Statistik: Nebenwertungen, Bilanzen und Rekorde.

Die drei Seiten hier beantworten Fragen, die die Ergebnisliste und die
Gesamtwertung nicht stellen — und zwar aus denselben Zahlen:

* **je Rennen**: welche Mannschaft in der Breite die stärkste war, wer
  am Berg vorn lag, und wer sich verpflegt hat und wer nicht;
* **je Saison**: Team- und Nationenwertung;
* **über alles**: der Rekord je Strecke.

Alles Auswertung, nichts Simulation. Die Rechnung selbst steht in
``core.classification``, damit sie sich ohne Webserver prüfen lässt.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ... import season_runner as runner
from ...core import classification as cls
from ...core import nutrition as nut
from ...core import season as sn

router = APIRouter()

#: So viele Zeilen zeigt die Energiebilanz. Sie ist eine Stichprobe an
#: der Spitze, keine Volltabelle: Bei 300 Fahrern liest niemand 300
#: Zeilen Kohlenhydratdeckung.
ENERGY_ROWS = 25


def _tpl(request: Request):
    return request.app.state.templates


def _state(request: Request):
    return request.app.state.ultrasim


def _energy_rows(result, riders, teams) -> list[dict[str, Any]]:
    """Aufgenommen gegen verbrannt, je Fahrer.

    Die Deckung ist der Anteil der verbrannten Kohlenhydrate, den der
    Fahrer unterwegs nachgelegt hat. Hundert Prozent gibt es nicht: Der
    Magen lässt weniger durch, als hartes Fahren verbrennt — das ist
    die Grundgleichung des Ultracyclings, und hier steht sie als Zahl.
    """
    rows = []
    for entry in result.entries:
        rider = riders.get(entry.rider_id)
        if rider is None or entry.carb_kcal <= 0.0:
            continue
        team = teams.get(rider.team_id)
        rows.append(
            {
                "entry": entry,
                "name": rider.name,
                "team": team.name if team else "",
                "total_kcal": nut.metabolic_kcal(entry.work_kj),
                "carb_kcal": entry.carb_kcal,
                "intake_kcal": entry.intake_kcal,
                "coverage": entry.intake_kcal / entry.carb_kcal,
            }
        )
    rows.sort(key=lambda r: (r["entry"].rank or 10**6))
    return rows[:ENERGY_ROWS]


@router.get("/race/{race_id}/statistik", response_class=HTMLResponse)
def race_stats(request: Request, race_id: str) -> HTMLResponse:
    state = _state(request)
    result, route, view = state.view(race_id)
    climbs, mountain = cls.mountain_ranking(result, route, view.riders, view.teams)
    # Die Zahl der Werter richtet sich nach dem Feld: Bei vierzig
    # Startern aus fünfundzwanzig Teams gibt es keine drei je Mannschaft.
    scorers = cls.effective_scorers(result.entries, view.riders)
    return _tpl(request).TemplateResponse(
        request,
        "race_stats.html",
        {
            "race_id": race_id,
            "race_name": result.config.name,
            "route": route,
            "teams": cls.team_race_ranking(
                result.entries, view.riders, view.teams, scorers=scorers
            ),
            "scorers": scorers,
            "full_scorers": cls.TEAM_SCORERS,
            "climbs": climbs,
            "mountain": mountain,
            "energy": _energy_rows(result, view.riders, view.teams),
        },
    )


@router.get("/season/{season_id}/statistik", response_class=HTMLResponse)
def season_stats(request: Request, season_id: str) -> HTMLResponse:
    state = _state(request)
    try:
        season = state.store.load_season(season_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Saison nicht gefunden") from exc

    summaries = runner.race_summaries(state.store, season)
    coefficients = runner.coefficients(state.store, season)
    head = season.points_head or list(sn.POINTS_HEAD)

    teams = cls.group_season_points(
        summaries,
        key_of_rider=lambda r: r.team_id,
        name_of_key=lambda r: r.team_name if hasattr(r, "team_name") else "",
        coefficients=coefficients,
        points_head=head,
    )
    # Die Teamnamen stehen nicht am Fahrer, sondern in der Teamliste des
    # Rennens — nachtragen statt am Fahrerobjekt zu erfinden.
    names: dict[str, str] = {}
    for summary in summaries.values():
        for team in summary.teams:
            names[str(team.id)] = team.name
    for row in teams:
        row.name = names.get(row.key, row.key)

    nations = cls.group_season_points(
        summaries,
        key_of_rider=lambda r: r.nation,
        name_of_key=lambda r: r.nation,
        coefficients=coefficients,
        points_head=head,
        # Nationen sind verschieden groß; eine feste Zahl von Wertern
        # würde das kleine Land bevorzugen.
        scorers=None,
    )

    computed = [r for r in season.sorted_races() if r.computed and r.id in summaries]
    return _tpl(request).TemplateResponse(
        request,
        "season_stats.html",
        {
            "season": season,
            "races": computed,
            "teams": teams,
            "nations": nations,
            "scorers": cls.TEAM_SCORERS,
        },
    )


@router.get("/rekorde", response_class=HTMLResponse)
def records(request: Request) -> HTMLResponse:
    """Bestzeit je Strecke über alle gerechneten Rennen.

    Gelesen wird zuerst nur der Index — Streckenkennung und Siegerzeit
    stehen dort schon. Erst für den Rekordhalter selbst wird ein
    Ergebnis nachgeladen: einmal je Strecke statt einmal je Rennen.
    """
    state = _state(request)
    routes = {r["id"]: r for r in state.store.list_routes()}

    best: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for race in state.store.list_races():
        route_id = race["route_id"]
        counts[route_id] = counts.get(route_id, 0) + 1
        if race["winner_time_s"] is None:
            continue
        current = best.get(route_id)
        if current is None or race["winner_time_s"] < current["winner_time_s"]:
            best[route_id] = race

    rows = []
    for route_id, race in best.items():
        holder = ""
        team = ""
        try:
            summary = state.store.load_race_summary(race["race_id"])
        except (FileNotFoundError, KeyError, ValueError):
            summary = None
        if summary is not None:
            winner = min(
                (e for e in summary.entries if e.finish_time_s is not None),
                key=lambda e: e.finish_time_s,
                default=None,
            )
            if winner is not None:
                rider = next((r for r in summary.riders if r.id == winner.rider_id), None)
                holder = rider.name if rider else ""
                team_obj = next(
                    (t for t in summary.teams if rider and t.id == rider.team_id), None
                )
                team = team_obj.name if team_obj else ""
        meta = routes.get(route_id, {})
        distance_km = meta.get("distance_km") or 0.0
        rows.append(
            {
                "route_id": route_id,
                "route_name": race["route_name"],
                "distance_km": distance_km,
                "ascent_m": meta.get("ascent_m") or 0,
                "race_id": race["race_id"],
                "race_name": race["name"],
                "time_s": race["winner_time_s"],
                "kmh": (
                    distance_km / (race["winner_time_s"] / 3600.0)
                    if race["winner_time_s"]
                    else None
                ),
                "holder": holder,
                "team": team,
                "races": counts.get(route_id, 0),
            }
        )
    rows.sort(key=lambda r: -r["distance_km"])
    return _tpl(request).TemplateResponse(
        request, "records.html", {"rows": rows, "total": sum(counts.values())}
    )
