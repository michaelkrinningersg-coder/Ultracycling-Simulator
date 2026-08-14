"""Karrieremodus: mehrere Saisons in Folge (Abschnitt 14, Ausbaustufe).

Wie der Kalender-Editor als Server-Formular gebaut — POST, dann
Weiterleitung. Der Jahreswechsel ist die eine Ausnahme: Er lässt das
ganze Feld altern und läuft deshalb wie eine Rennrechnung als
Hintergrundauftrag mit Fortschrittsanzeige.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ... import career_runner as careers
from ...core import career as cr
from ..jobs import Job

router = APIRouter()


def _tpl(request: Request):
    return request.app.state.templates


def _state(request: Request):
    return request.app.state.ultrasim


def _back(career_id: str, anchor: str = "") -> RedirectResponse:
    return RedirectResponse(f"/career/{career_id}{anchor}", status_code=303)


def _load(request: Request, career_id: str) -> cr.Career:
    try:
        return _state(request).store.load_career(career_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ----------------------------------------------------------------------
# Übersicht
# ----------------------------------------------------------------------
@router.get("/careers", response_class=HTMLResponse)
def careers_index(request: Request) -> HTMLResponse:
    state = _state(request)
    return _tpl(request).TemplateResponse(
        request,
        "careers.html",
        {
            "careers": state.store.list_careers(),
            "routes": state.store.list_routes(),
            "pool_exists": state.store.pool_exists(),
            "this_year": date.today().year,
        },
    )


@router.post("/careers")
def career_create(
    request: Request,
    name: str = Form(...),
    year: int = Form(...),
    n_races: int = Form(10),
) -> RedirectResponse:
    state = _state(request)
    if not state.store.list_routes():
        raise HTTPException(status_code=400, detail="Ohne Strecken kein Kalender.")
    career, _ = careers.create_career(
        state.store, name.strip() or "Karriere", int(year), n_races=max(1, min(int(n_races), 40))
    )
    return _back(career.id)


@router.post("/career/{career_id}/delete")
def career_delete(request: Request, career_id: str) -> RedirectResponse:
    """Nur die Karriereakte löschen — die Saisons bleiben stehen.

    Die Saisons enthalten gerechnete Rennen; sie mit einem Klick
    mitzulöschen wäre eine Falle. Wer sie loswerden will, löscht sie
    einzeln in der Saisonübersicht.
    """
    _state(request).store.delete_career(career_id)
    return RedirectResponse("/careers", status_code=303)


# ----------------------------------------------------------------------
# Eine Karriere
# ----------------------------------------------------------------------
@router.get("/career/{career_id}", response_class=HTMLResponse)
def career_page(request: Request, career_id: str) -> HTMLResponse:
    state = _state(request)
    career = _load(request, career_id)

    seasons: list[dict[str, Any]] = []
    for season_id in career.season_ids:
        try:
            season = state.store.load_season(season_id)
        except FileNotFoundError:
            continue
        seasons.append(
            {
                "id": season.id,
                "name": season.name,
                "year": season.year,
                "n_races": len(season.races),
                "n_computed": sum(1 for r in season.races if r.computed),
                "closed": career.chapter(season.year) is not None,
            }
        )

    jobs = [j for j in state.jobs.list_jobs(career_id) if j.kind == "close-year"]
    return _tpl(request).TemplateResponse(
        request,
        "career.html",
        {
            "career": career,
            "seasons": seasons,
            "hall_of_fame": cr.hall_of_fame(career)[:25],
            "jobs": jobs,
            "current": seasons[-1] if seasons else None,
        },
    )


@router.post("/career/{career_id}/close")
def career_close_year(
    request: Request, career_id: str, seed: int = Form(1)
) -> RedirectResponse:
    """Das laufende Jahr abschließen und das nächste eröffnen.

    Die einzige Aktion der Anwendung, die bestehende Daten überschreibt:
    Danach ist der Fahrerpool ein anderer. Deshalb friert sie vorher die
    Wertung als Kapitel ein.
    """
    state = _state(request)
    career = _load(request, career_id)
    season_id = career.current_season_id
    if season_id is None:
        raise HTTPException(status_code=400, detail="Diese Karriere hat keine Saison.")
    season = state.store.load_season(season_id)

    def work(job: Job) -> dict[str, Any]:
        job.detail = "Wertung einfrieren"
        # Innerhalb des Auftrags neu laden: Zwischen Klick und Ausführung
        # kann der Kalender-Editor die Saison verändert haben.
        fresh_career = state.store.load_career(career_id)
        fresh_season = state.store.load_season(season_id)
        job.detail = "Fahrer altern"
        return careers.close_year(state.store, fresh_career, fresh_season, seed=int(seed))

    state.jobs.submit(
        kind="close-year",
        label=f"Jahreswechsel {season.name}",
        work=work,
        season_id=career_id,
    )
    return _back(career_id, "#jahreswechsel")


@router.get("/career/{career_id}/rider/{rider_id}", response_class=HTMLResponse)
def career_rider(request: Request, career_id: str, rider_id: int) -> HTMLResponse:
    career = _load(request, career_id)
    history = cr.rider_history(career, int(rider_id))
    if not history:
        raise HTTPException(status_code=404, detail="Zu diesem Fahrer gibt es keine Jahre.")
    name = next(
        (y.standing.name for y in reversed(history) if y.standing),
        next((y.development.name for y in reversed(history) if y.development), "Fahrer"),
    )
    return _tpl(request).TemplateResponse(
        request,
        "career_rider.html",
        {
            "career": career,
            "rider_id": int(rider_id),
            "rider_name": name,
            "history": history,
            "titles": sum(1 for y in history if y.rank == 1),
        },
    )
