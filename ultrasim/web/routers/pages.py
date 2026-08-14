"""HTML-Seiten. Jinja2 liefert den Seitenrahmen, Alpine.js die Interaktion."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ...core import narrative
from ...core.rider import ACTIVE_ATTRIBUTES, ATTRIBUTE_LABELS, ATTRIBUTES

router = APIRouter()


def _tpl(request: Request):
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    state = request.app.state.ultrasim
    return _tpl(request).TemplateResponse(
        request,
        "index.html",
        {
            "routes": state.store.list_routes(),
            "races": state.store.list_races(),
            "seasons": state.store.list_seasons(),
            "pool_exists": state.store.pool_exists(),
        },
    )


@router.get("/race/{race_id}", response_class=HTMLResponse)
def race_live(request: Request, race_id: str) -> HTMLResponse:
    result, route, _ = request.app.state.ultrasim.view(race_id)
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
    result, route, view = request.app.state.ultrasim.view(race_id)
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
