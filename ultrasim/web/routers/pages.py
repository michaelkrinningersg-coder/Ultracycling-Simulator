"""HTML-Seiten. Jinja2 liefert den Seitenrahmen, Alpine.js die Interaktion."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ... import season_runner as runner
from ...core import narrative
from ...core import season as sn
from ...core.engine import RaceConfig
from ...core.rider import ACTIVE_ATTRIBUTES, ATTRIBUTE_LABELS, ATTRIBUTES
from ..livesim import LiveRoom

router = APIRouter()


def _tpl(request: Request):
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    state = request.app.state.ultrasim
    races = state.store.list_races()
    # Ein laufendes Rennen sticht seine Datei: Auf der Platte steht der
    # Stand der letzten Sicherung, im Speicher der von jetzt.
    rooms = {race_id: state.live.get(race_id) for race_id in state.live.ids()}
    races = [r for r in races if r["race_id"] not in rooms]
    races = [room.summary() for room in rooms.values() if room] + races
    return _tpl(request).TemplateResponse(
        request,
        "index.html",
        {
            "routes": state.store.list_routes(),
            "races": races,
            "seasons": state.store.list_seasons(),
            "pool_exists": state.store.pool_exists(),
        },
    )


@router.post("/race/live")
def race_live_start(
    request: Request,
    route_id: str = Form(...),
    riders: int = Form(40),
    seed: int = Form(42),
) -> RedirectResponse:
    """Ein Rennen starten, das erst beim Zusehen entsteht (Abschnitt 8.2).

    Der Unterschied zum Kalenderrennen ist nicht das Ergebnis — dasselbe
    Feld auf derselben Strecke mit demselben Seed fährt dasselbe Rennen,
    das ist die tragende Zusicherung von ``core.live``. Der Unterschied
    ist, wann gerechnet wird: hier gar nicht. Der erste Tick fällt,
    wenn jemand hinschaut.
    """
    state = request.app.state.ultrasim
    if not state.store.pool_exists():
        raise HTTPException(400, "Kein Fahrerpool vorhanden — bitte zuerst Fahrer anlegen.")
    route = state.store.load_route(route_id)
    teams, pool = state.store.load_pool()
    n = int(np.clip(riders, 2, len(pool)))
    field = sorted(pool, key=lambda r: -r.potential)[:n]

    race_id = _free_race_id(state, f"{route_id}-live-{int(seed)}")
    room = LiveRoom.start(
        race_id=race_id,
        route_id=route_id,
        route=route,
        riders=field,
        teams=teams,
        config=RaceConfig(seed=int(seed), name=f"{route.name} – live"),
        store=state.store,
    )
    state.live.add(room)
    return RedirectResponse(f"/race/{race_id}", status_code=303)


def _free_race_id(state, base: str) -> str:
    """Einen noch unbelegten Schlüssel finden.

    Zweimal dasselbe live zu starten ist keine Wiederholung, sondern
    eine zweite Übertragung — die erste darf davon nichts merken.
    Belegt ist ein Schlüssel deshalb auch dann, wenn dazu noch keine
    Datei existiert: Ein laufendes Rennen, dessen erste Sicherung noch
    aussteht, würde sonst stillschweigend ersetzt.
    """

    def taken(key: str) -> bool:
        return (state.store.race_dir(key) / "race.json").exists() or state.live.get(
            key
        ) is not None

    if not taken(base):
        return base
    for i in range(2, 100):
        if not taken(f"{base}-{i}"):
            return f"{base}-{i}"
    return f"{base}-x"


@router.get("/race/{race_id}", response_class=HTMLResponse)
def race_live(request: Request, race_id: str) -> HTMLResponse:
    state = request.app.state.ultrasim
    result, route, _ = state.view(race_id)
    room = state.live.get(race_id)
    return _tpl(request).TemplateResponse(
        request,
        "race.html",
        {
            "race_id": race_id,
            "race_name": result.config.name,
            "route": route,
            "n_entries": len(result.entries),
            "weather": result.weather,
            "start_interval_s": result.config.resolved_start_interval(route.distance_class),
            #: Wird das Rennen gerade gerechnet? Die Oberfläche sagt das
            #: an, weil es zwei Dinge ändert, die der Zuschauer merkt:
            #: Ein Sprung nach vorn kostet Rechenzeit, und der
            #: Zeitstrahl ist bis zum Ziel nur geschätzt.
            "is_live": room is not None and not room.finished,
        },
    )


#: So viele Zeilen zeigt die Splitmatrix ohne Aufforderung. Bei 250
#: Startern und 30 Splits sind das sonst 7500 Zellen — die Seite lädt
#: zwar, aber niemand liest sie.
MATRIX_ROWS = 25


def _split_matrix(result, route, view, finished: list) -> dict:
    """Splitzeiten als Fahrer × Split, mit Rang je Zelle.

    Die Ergebnisliste beantwortet „wer war schneller". Die Matrix
    beantwortet „**wo** war er schneller" — wer gleichmäßig gefahren ist,
    wer eingebrochen ist, wer erst spät kam. Die Zahlen liegen seit M3
    fertig herum; gelesen hat sie bisher niemand.
    """
    order = finished[:MATRIX_ROWS]
    times = result.split_times_s
    ranks = result.split_ranks
    n_ranked = max(int(ranks.max()), 1)
    rows = []
    for entry in order:
        cells = []
        for split_idx in range(len(route.splits)):
            value = float(times[entry.entry_id, split_idx])
            rank = int(ranks[entry.entry_id, split_idx])
            cells.append(
                {
                    "t_s": None if value != value else value,  # NaN = nicht erreicht
                    "rank": rank or None,
                    # 0 = führend, 1 = Feldende. Daraus macht die Vorlage
                    # einen Farbverlauf, ohne Ränge zu vergleichen.
                    "shade": None if not rank else round((rank - 1) / n_ranked, 3),
                }
            )
        rows.append(
            {"entry": entry, "name": view.riders[entry.rider_id].name, "cells": cells}
        )
    return {"splits": route.splits, "rows": rows, "shown": len(order), "total": len(finished)}


@router.get("/race/{race_id}/results", response_class=HTMLResponse)
def race_results(request: Request, race_id: str) -> HTMLResponse:
    state = request.app.state.ultrasim
    result, route, view = state.view(race_id)

    # Gehört das Rennen zu einem Kalendertermin? Dann steht neben jeder
    # Zeit auch, was sie in der Saison wert war. Ohne das ist die
    # Ergebnisliste ein Endpunkt; mit ihr ist sie eine Zwischenstation,
    # und genau das ist ein Saisonrennen.
    season_points: dict[int, float] = {}
    season_link = None
    found = runner.season_of_race(state.store, race_id)
    if found is not None:
        season, calendar_race = found
        coefficient = runner.coefficients(state.store, season).get(calendar_race.id, 1.0)
        season_points = sn.score_race(
            result.entries, coefficient, season.points_head or sn.POINTS_HEAD
        )
        season_link = {
            "id": season.id,
            "name": season.name,
            "year": season.year,
            "race_name": calendar_race.name,
            "coefficient": coefficient,
        }

    finished = sorted(
        (e for e in result.entries if e.finish_time_s is not None),
        key=lambda e: e.finish_time_s,  # type: ignore[arg-type,return-value]
    )
    best = finished[0].finish_time_s if finished else None
    reports = narrative.build_reports(
        result.entries, result.events, result.split_ranks, route.splits
    )
    rows = []
    for entry in finished:
        rider = view.riders[entry.rider_id]
        team = view.teams.get(rider.team_id)
        rows.append(
            {
                "entry": entry,
                "rider": rider,
                "team": team,
                "gap": None if best is None else entry.finish_time_s - best,
                "report": reports[entry.entry_id].text,
                "points": season_points.get(entry.rider_id),
            }
        )
    # Wer am weitesten kam, steht oben – so liest sich die Liste als
    # Chronik des Abbröckelns statt als Startnummernfolge.
    dnf = sorted(
        (
            {
                "entry": e,
                "rider": view.riders[e.rider_id],
                "report": reports[e.entry_id].text,
            }
            for e in result.entries
            if e.finish_time_s is None
        ),
        key=lambda row: -(row["entry"].dnf_dist_m or 0.0),
    )
    return _tpl(request).TemplateResponse(
        request,
        "results.html",
        {
            "race_id": race_id,
            "race_name": result.config.name,
            "route": route,
            "rows": rows,
            "dnf": dnf,
            "season_link": season_link,
            "compute_seconds": result.compute_seconds,
            "matrix": _split_matrix(result, route, view, finished),
            "avg_speed": (
                None
                if not best
                else round(route.distance_km / (best / 3600.0), 1)
            ),
        },
    )


@router.get("/race/{race_id}/rider/{entry_id}", response_class=HTMLResponse)
def rider_detail(request: Request, race_id: str, entry_id: int) -> HTMLResponse:
    result, route, view = request.app.state.ultrasim.view(race_id)
    if not 0 <= entry_id < len(result.entries):
        raise HTTPException(404, "Kein solcher Starter")
    entry = result.entries[entry_id]
    rider = view.riders[entry.rider_id]
    team = view.teams.get(rider.team_id)

    times = result.split_times_s[entry_id]
    ranks = result.split_ranks[entry_id]
    splits = []
    prev = 0.0
    for split, t_s, rank in zip(route.splits, times, ranks, strict=True):
        if not np.isfinite(t_s):
            continue
        splits.append(
            {
                "split": split,
                "t_s": float(t_s),
                "rank": int(rank),
                "section_s": float(t_s) - prev,
                "speed": round((split.dist_m - prev * 0) / 1000.0, 1),
            }
        )
        prev = float(t_s)

    attributes = [
        {
            "key": key,
            "label": ATTRIBUTE_LABELS.get(key, key),
            "value": rider.attr(key),
            "active": key in ACTIVE_ATTRIBUTES,
        }
        for key in ATTRIBUTES
    ]
    return _tpl(request).TemplateResponse(
        request,
        "rider.html",
        {
            "race_id": race_id,
            "race_name": result.config.name,
            "entry": entry,
            "rider": rider,
            "team": team,
            "route": route,
            "splits": splits,
            "attributes": attributes,
            "events": [e for e in result.events_for(entry_id) if e.type not in ("PLAN",)],
            "plan_notes": entry.notes,
        },
    )
