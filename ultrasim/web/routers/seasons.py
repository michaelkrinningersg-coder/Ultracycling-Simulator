"""Kalender-Editor und Saisonwertung (Abschnitte 10.3, 11 und 14).

Der erste echte Editor der Anwendung. Er ist bewusst als
Server-Formular gebaut — POST, dann Weiterleitung — und nicht als
Einseiten-App: Ein Kalender wird selten und in Ruhe bearbeitet, jede
Änderung soll sofort auf der Platte stehen, und ein neu geladener
Browser darf nie einen anderen Stand zeigen als die Datei. Alpine
kommt nur dort ins Spiel, wo es wirklich etwas zu beobachten gibt: beim
Fortschritt einer laufenden Rechnung.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ... import career_runner as careers
from ... import season_runner as runner
from ...core import season as sn
from ...core.season import CalendarRace, Season
from ...core.weather import PRESETS
from ..jobs import Job, race_progress

router = APIRouter()


def _tpl(request: Request):
    return request.app.state.templates


def _state(request: Request):
    return request.app.state.ultrasim


def _back(season_id: str, anchor: str = "") -> RedirectResponse:
    """Nach jeder Änderung zurück auf die Saisonseite.

    Post/Redirect/Get, damit ein Neuladen keine Änderung wiederholt.
    """
    return RedirectResponse(f"/season/{season_id}{anchor}", status_code=303)


# ----------------------------------------------------------------------
# Übersicht
# ----------------------------------------------------------------------
@router.get("/seasons", response_class=HTMLResponse)
def seasons_index(request: Request) -> HTMLResponse:
    state = _state(request)
    return _tpl(request).TemplateResponse(
        request,
        "seasons.html",
        {
            "seasons": state.store.list_seasons(),
            "routes": state.store.list_routes(),
            "pool_exists": state.store.pool_exists(),
            "this_year": date.today().year,
        },
    )


@router.post("/seasons")
def season_create(
    request: Request,
    name: str = Form(...),
    year: int = Form(...),
    n_races: int = Form(0),
) -> RedirectResponse:
    state = _state(request)
    season_id = runner.slugify(f"{year}-{name}", fallback=str(year))
    if state.store.season_path(season_id).exists():
        raise HTTPException(status_code=409, detail=f"Saison '{season_id}' gibt es schon")

    season = Season(id=season_id, name=name.strip() or f"Saison {year}", year=int(year))
    if n_races > 0:
        season.races = runner.suggest_calendar(state.store, int(year), int(n_races))
    state.store.save_season(season)
    return _back(season_id)


@router.post("/season/{season_id}/delete")
def season_delete(request: Request, season_id: str) -> RedirectResponse:
    _state(request).store.delete_season(season_id)
    return RedirectResponse("/seasons", status_code=303)


# ----------------------------------------------------------------------
# Saisonseite
# ----------------------------------------------------------------------
@router.get("/season/{season_id}", response_class=HTMLResponse)
def season_detail(request: Request, season_id: str) -> HTMLResponse:
    state = _state(request)
    season = state.store.load_season(season_id)
    store = state.store

    routes = {r["id"]: r for r in store.list_routes()}
    coefficients = runner.coefficients(store, season)
    summaries = runner.race_summaries(store, season)

    rows: list[dict[str, Any]] = []
    previous: date | None = None
    for calendar_race in season.sorted_races():
        summary = summaries.get(calendar_race.id)
        route = routes.get(calendar_race.route_id)
        gap = (calendar_race.day - previous).days if previous else None
        winner = None
        if summary is not None:
            best = min(
                (e for e in summary.entries if e.rank == 1),
                key=lambda e: e.finish_time_s or 0.0,
                default=None,
            )
            if best is not None:
                rider = next(
                    (r for r in summary.riders if r.id == best.rider_id), None
                )
                winner = {
                    "name": rider.name if rider else "",
                    "time_s": best.finish_time_s,
                }
        rows.append(
            {
                "race": calendar_race,
                "route": route,
                "coefficient": coefficients.get(calendar_race.id, 1.0),
                "summary": summary,
                "winner": winner,
                "gap_days": gap,
                "job": state.jobs.active_for(season_id, calendar_race.id),
            }
        )
        previous = calendar_race.day

    return _tpl(request).TemplateResponse(
        request,
        "season.html",
        {
            "season": season,
            "rows": rows,
            "routes": store.list_routes(),
            "presets": sorted(PRESETS),
            "standings": runner.standings(store, season),
            "pending": len(runner.pending_races(season)),
            "pool_exists": store.pool_exists(),
            "jobs": [j.to_dict() for j in state.jobs.list_jobs(season_id)[:8]],
            "busy": state.jobs.active_for(season_id) is not None,
            "points_head": season.points_head or list(sn.POINTS_HEAD),
            "plan": runner.calendar_plan(store, season),
            "career": careers.career_of_season(store, season_id),
        },
    )


# ----------------------------------------------------------------------
# Termine bearbeiten
# ----------------------------------------------------------------------
@router.post("/season/{season_id}/race")
def race_add(
    request: Request,
    season_id: str,
    name: str = Form(...),
    route_id: str = Form(...),
    day: str = Form(...),
    n_riders: int = Form(60),
    seed: int = Form(1),
    weather_preset: str = Form(""),
) -> RedirectResponse:
    state = _state(request)
    season = state.store.load_season(season_id)

    key = runner.slugify(name)
    # Zwei Rennen auf derselben Strecke sind erlaubt, zwei mit demselben
    # Schlüssel nicht – der Schlüssel wandert in die Renn-ID.
    if season.race(key):
        suffix = 2
        while season.race(f"{key}-{suffix}"):
            suffix += 1
        key = f"{key}-{suffix}"

    season.races.append(
        CalendarRace(
            id=key,
            name=name.strip(),
            route_id=route_id,
            day=date.fromisoformat(day),
            n_riders=max(int(n_riders), 2),
            seed=int(seed),
            weather_preset=weather_preset or None,
        )
    )
    state.store.save_season(season)
    return _back(season_id, "#kalender")


@router.post("/season/{season_id}/race/{race_key}")
def race_update(
    request: Request,
    season_id: str,
    race_key: str,
    name: str = Form(...),
    route_id: str = Form(...),
    day: str = Form(...),
    n_riders: int = Form(60),
    seed: int = Form(1),
    weather_preset: str = Form(""),
    coefficient: str = Form(""),
) -> RedirectResponse:
    state = _state(request)
    season = state.store.load_season(season_id)
    calendar_race = season.race(race_key)
    if calendar_race is None:
        raise HTTPException(status_code=404, detail=f"Kein Termin '{race_key}'")

    calendar_race.name = name.strip()
    calendar_race.route_id = route_id
    calendar_race.day = date.fromisoformat(day)
    calendar_race.n_riders = max(int(n_riders), 2)
    calendar_race.seed = int(seed)
    calendar_race.weather_preset = weather_preset or None
    calendar_race.coefficient = float(coefficient) if coefficient.strip() else None
    state.store.save_season(season)
    return _back(season_id, "#kalender")


@router.post("/season/{season_id}/race/{race_key}/delete")
def race_delete(request: Request, season_id: str, race_key: str) -> RedirectResponse:
    state = _state(request)
    season = state.store.load_season(season_id)
    calendar_race = season.race(race_key)
    if calendar_race is not None:
        # Das gerechnete Rennen bleibt stehen. Einen Termin aus dem
        # Kalender zu nehmen ist eine Planungsentscheidung und darf nicht
        # nebenbei Renndaten löschen.
        season.races = [r for r in season.races if r.id != race_key]
        state.store.save_season(season)
    return _back(season_id, "#kalender")


@router.post("/season/{season_id}/race/{race_key}/reset")
def race_reset(request: Request, season_id: str, race_key: str) -> RedirectResponse:
    """Ergebnis verwerfen, damit der Termin neu gerechnet werden kann."""
    state = _state(request)
    season = state.store.load_season(season_id)
    calendar_race = season.race(race_key)
    if calendar_race is not None and calendar_race.race_id:
        state.invalidate(calendar_race.race_id)
        state.store.delete_race(calendar_race.race_id)
        calendar_race.race_id = None
        state.store.save_season(season)
    return _back(season_id, "#kalender")


# ----------------------------------------------------------------------
# Rechnen
# ----------------------------------------------------------------------
@router.post("/season/{season_id}/race/{race_key}/run")
def race_run(request: Request, season_id: str, race_key: str) -> RedirectResponse:
    state = _state(request)
    season = state.store.load_season(season_id)
    calendar_race = season.race(race_key)
    if calendar_race is None:
        raise HTTPException(status_code=404, detail=f"Kein Termin '{race_key}'")
    if not state.store.pool_exists():
        raise HTTPException(status_code=400, detail="Kein Fahrerpool vorhanden")
    if state.jobs.active_for(season_id, race_key):
        return _back(season_id, "#kalender")

    _submit_race(state, season_id, calendar_race)
    return _back(season_id, "#kalender")


@router.post("/season/{season_id}/run-all")
def season_run_all(request: Request, season_id: str) -> RedirectResponse:
    """Alle offenen Termine in Terminreihenfolge in die Schlange hängen.

    Die Reihenfolge ist Pflicht, nicht Kosmetik: Die Restermüdung eines
    Rennens ergibt sich aus den vorherigen, und die stehen erst fest,
    wenn sie gerechnet sind. Der Arbeiter arbeitet die Schlange strikt
    nacheinander ab.
    """
    state = _state(request)
    season = state.store.load_season(season_id)
    if not state.store.pool_exists():
        raise HTTPException(status_code=400, detail="Kein Fahrerpool vorhanden")
    for calendar_race in runner.pending_races(season):
        if not state.jobs.active_for(season_id, calendar_race.id):
            _submit_race(state, season_id, calendar_race)
    return _back(season_id, "#kalender")


def _submit_race(state: Any, season_id: str, calendar_race: CalendarRace) -> Job:
    def work(job: Job) -> dict[str, Any]:
        # Die Saison wird *im Arbeiter* frisch geladen, nicht von außen
        # hereingereicht: Zwischen Einreihen und Ausführen kann der Nutzer
        # den Kalender geändert haben, und ein Rennen mit veraltetem
        # Termin würde die falsche Restermüdung bekommen.
        season = state.store.load_season(season_id)
        outcome = runner.run_calendar_race(
            state.store, season, calendar_race.id, progress=race_progress(job)
        )
        return {
            "race_id": outcome.race_id,
            "winner_time_s": outcome.winner_time_s,
            "n_entries": outcome.n_entries,
            "compute_seconds": round(outcome.compute_seconds, 1),
        }

    return state.jobs.submit(
        kind="race",
        label=f"{calendar_race.name} ({calendar_race.day.isoformat()})",
        work=work,
        season_id=season_id,
        race_key=calendar_race.id,
    )


# ----------------------------------------------------------------------
# Saisonwechsel
# ----------------------------------------------------------------------
@router.post("/season/{season_id}/close")
def season_close(
    request: Request, season_id: str, seed: int = Form(1)
) -> RedirectResponse:
    """Fahrerentwicklung anstoßen (Abschnitt 14).

    Das schreibt den Fahrerpool um und ist damit die einzige Aktion hier,
    die über die Saison hinaus wirkt — deshalb steht sie hinter einer
    eigenen Bestätigung und nicht neben den Kalenderknöpfen.
    """
    state = _state(request)
    season = state.store.load_season(season_id)

    def work(job: Job) -> dict[str, Any]:
        job.detail = "Fahrer altern"
        return runner.close_season(state.store, season, seed=int(seed))

    state.jobs.submit(
        kind="close",
        label=f"Saisonwechsel {season.name}",
        work=work,
        season_id=season_id,
    )
    return _back(season_id, "#entwicklung")


@router.get("/season/{season_id}/development", response_class=HTMLResponse)
def season_development(request: Request, season_id: str) -> HTMLResponse:
    state = _state(request)
    season = state.store.load_season(season_id)
    done = [
        j
        for j in state.jobs.list_jobs(season_id)
        if j.kind == "close" and j.result
    ]
    return _tpl(request).TemplateResponse(
        request,
        "development.html",
        {"season": season, "report": done[0].result if done else None},
    )
