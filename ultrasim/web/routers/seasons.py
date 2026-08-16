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
from ...core.rider import DEFAULT_FIELD, pool_mismatch
from ...core.season import CalendarRace, Season
from ...core.weather import PRESETS
from ..jobs import Job, race_progress
from ..livesim import LiveRoom

router = APIRouter()


def _tpl(request: Request):
    return request.app.state.templates


def _state(request: Request):
    return request.app.state.ultrasim


#: So viele Fahrer trägt der Verlauf der Gesamtwertung.
STANDINGS_CHART_ROWS = 8

#: Zeichenfläche in Nutzerkoordinaten.
CHART_W, CHART_H = 1000.0, 300.0

#: Linienfarben des Verlaufs. Nicht die Teamfarbe: In der Gesamtwertung
#: stehen oft zwei Fahrer desselben Teams vorn, und zwei identische
#: Linien sind schlimmer als acht willkürliche.
CHART_COLORS = (
    "#ffc247", "#4ade80", "#47b4ff", "#f8717a",
    "#a78bfa", "#f0883e", "#5eead4", "#e879f9",
)


def _standings_chart(season: Season, standings: list[sn.Standing]) -> dict | None:
    """Die Gesamtwertung als Verlauf über die gerechneten Termine.

    Die Tabelle sagt, wer am Ende vorn ist. Sie sagt nicht, wer wann
    geführt hat — und genau das ist an einer Saison das Erzählbare: dass
    einer nach dem dritten Rennen sechzig Punkte vorn lag und es auf dem
    langen Ultra verloren hat.

    Gezeichnet werden **kumulierte Punkte**, nicht Ränge: Bei zehn
    Rennen mit sehr verschiedenen Koeffizienten ist der Abstand die
    Aussage, nicht die Platzziffer.
    """
    computed = [r for r in season.sorted_races() if r.computed]
    if len(computed) < 2 or not standings:
        return None
    keys = [r.id for r in computed]
    top = standings[:STANDINGS_CHART_ROWS]

    series = []
    peak = 0.0
    for standing in top:
        by_race = {s.race_key: s.points for s in standing.scores}
        total = 0.0
        # Der Nullpunkt gehört dazu: Ohne ihn beginnt die Linie des
        # Auftaktsiegers am linken Rand schon auf hundert Punkten, und
        # der erste Termin — der mit dem größten Sprung — wäre der
        # einzige, den man nicht sieht.
        cumulative = [0.0]
        for key in keys:
            total += by_race.get(key, 0.0)
            cumulative.append(total)
        peak = max(peak, total)
        series.append((standing, cumulative))
    if peak <= 0.0:
        return None

    lines = []
    steps = len(keys)
    for i, (standing, cumulative) in enumerate(series):
        points = " ".join(
            f"{j / steps * CHART_W:.1f},{CHART_H - value / peak * CHART_H:.1f}"
            for j, value in enumerate(cumulative)
        )
        lines.append(
            {
                "name": standing.name,
                "rank": standing.rank,
                "team": standing.team_name,
                "color": CHART_COLORS[i % len(CHART_COLORS)],
                "points": points,
                "total": cumulative[-1],
            }
        )
    return {
        "w": CHART_W,
        "h": CHART_H,
        "lines": lines,
        "peak": peak,
        "ticks": [
            {"x": (i + 1) / steps * CHART_W, "label": race.name}
            for i, race in enumerate(computed)
        ],
    }


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
    calendar: str = Form("0"),
) -> RedirectResponse:
    """Saison anlegen, wahlweise mit fertigem Kalender.

    ``calendar`` ist entweder ``weltserie`` für den Standardkalender oder
    eine Zahl: so viele Termine aus den vorhandenen Strecken, ``0`` für
    einen leeren Kalender.
    """
    state = _state(request)
    season_id = runner.slugify(f"{year}-{name}", fallback=str(year))
    if state.store.season_path(season_id).exists():
        raise HTTPException(status_code=409, detail=f"Saison '{season_id}' gibt es schon")

    season = Season(id=season_id, name=name.strip() or f"Saison {year}", year=int(year))
    if calendar == "weltserie":
        season.races = runner.weltserie_calendar(state.store, int(year))
    elif calendar.isdigit() and int(calendar) > 0:
        season.races = runner.suggest_calendar(state.store, int(year), int(calendar))
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

    mismatch = None
    pool_size = 0
    if store.pool_exists():
        pool_teams, pool_riders = store.load_pool()
        pool_size = len(pool_riders)
        mismatch = pool_mismatch(pool_teams, pool_riders)

    # Ein Termin, dessen Rennen gerade live entsteht, ist nicht fertig —
    # auch wenn er schon eine ``race_id`` und eine Datei hat. Der Raum
    # weiß es, die Saisondatei nicht.
    live_now = {
        r.race_id
        for r in season.races
        if r.race_id and (room := state.live.get(r.race_id)) and not room.finished
    }

    standings = runner.standings(store, season)
    pending = runner.pending_races(season)
    # Der Titel steht erst, wenn der letzte Termin gefahren ist. Vorher
    # ist die Rangliste ein Zwischenstand, und den Führenden schon
    # „Ultrameister" zu nennen wäre genau die Vorwegnahme, die dieses
    # Programm sonst überall vermeidet.
    champion = (
        standings[0]
        if (season.races and not pending and not live_now and standings)
        else None
    )

    return _tpl(request).TemplateResponse(
        request,
        "season.html",
        {
            "season": season,
            "rows": rows,
            "routes": store.list_routes(),
            "presets": sorted(PRESETS),
            "standings": standings,
            "standings_chart": _standings_chart(season, standings),
            "champion": champion,
            "runner_up": standings[1] if champion and len(standings) > 1 else None,
            "pending": len(pending),
            "live_now": live_now,
            "pool_exists": store.pool_exists(),
            # Warum starten weniger Fahrer als geplant? Die Antwort ist
            # fast immer ein Pool aus einer älteren Fassung — und der
            # Ort, an dem die Frage aufkommt, ist diese Seite.
            "pool_size": pool_size,
            "pool_mismatch": mismatch,
            "planned_field": max((r.n_riders for r in season.races), default=0),
            "jobs": [j.to_dict() for j in state.jobs.list_jobs(season_id)[:8]],
            "busy": state.jobs.active_for(season_id) is not None,
            "points_head": season.points_head or list(sn.POINTS_HEAD),
            "points_last_rank": sn.POINTS_LAST_RANK,
            "default_field": DEFAULT_FIELD,
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


@router.post("/season/{season_id}/race/{race_key}/live")
def race_live(request: Request, season_id: str, race_key: str) -> RedirectResponse:
    """Einen Kalendertermin **live** fahren, statt ihn vorzurechnen.

    Dasselbe Rennen wie über ``/run`` — dieselbe Aufstellung, derselbe
    Seed, dieselbe Restermüdung; das sichert ``race_setup`` zu, aus dem
    beide Wege kommen. Der Unterschied ist, wann gerechnet wird: hier
    erst, wenn jemand hinsieht.

    Die ``race_id`` steht sofort im Kalender, obwohl das Rennen noch
    läuft. Das ist Absicht: Der Raum sichert von der ersten Sekunde an
    auf die Platte, und ohne den Verweis wäre das laufende Rennen vom
    Kalender aus nicht wiederzufinden. Dass es noch nicht fertig ist,
    weiß die Saisonseite vom Raum, nicht von der Datei — und solange es
    läuft, wird kein Ultrameister gekürt.
    """
    state = _state(request)
    if not state.store.pool_exists():
        raise HTTPException(status_code=400, detail="Kein Fahrerpool vorhanden")
    season = state.store.load_season(season_id)
    try:
        setup = runner.race_setup(state.store, season, race_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Kein Termin '{race_key}'") from exc

    existing = state.live.get(setup.race_id)
    if existing is not None and not existing.finished:
        return RedirectResponse(f"/race/{setup.race_id}", status_code=303)

    room = LiveRoom.start(
        race_id=setup.race_id,
        route_id=setup.calendar_race.route_id,
        route=setup.route,
        riders=setup.riders,
        teams=setup.teams,
        config=setup.config,
        store=state.store,
    )
    state.live.add(room)
    state.invalidate(setup.race_id)
    setup.calendar_race.race_id = setup.race_id
    state.store.save_season(season)
    return RedirectResponse(f"/race/{setup.race_id}", status_code=303)


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
