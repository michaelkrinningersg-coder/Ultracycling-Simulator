"""Fahrer- und Team-Editor (Abschnitt 10.3).

Der Generator liefert das Feld; hier wird es kuratiert. Das Dokument
nennt für den Fahrer-Editor drei Dinge: Archetyp-Auswahl und Anzahl beim
Erzeugen, Tabellen- und Detailansicht, und eine Potenzial-Budget-Anzeige.

**Warum das Budget angezeigt und nicht erzwungen wird.** Der Generator
normiert jeden Fahrer auf ein gewichtetes Attributmittel — ohne dieses
Budget bekommt man entweder graue Einheitsfahrer oder einen, der alles
gewinnt (Abschnitt 5.3). Im Editor darf laut Dokument trotzdem *jeder
Wert überschrieben* werden. Beides zusammen geht nur so: Der Editor
rechnet das Budget bei jeder Änderung mit und zeigt an, wie weit der
Fahrer vom Feldmittel abweicht. Wer einen Übermenschen bauen will, kann
das — er sieht dabei nur genau, was er tut.

**Was Änderungen am Pool *nicht* tun.** Sie ändern kein gerechnetes
Rennen. Jedes Rennen legt seine Fahrer als Kopie ab, so wie es seine
Strecke ablegt. Ein nachträglich hochgezüchteter Fahrer gewinnt deshalb
nicht rückwirkend das Rennen vom letzten Mai.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...core.rider import (
    ACTIVE_ATTRIBUTES,
    ARCHETYPES,
    ATTRIBUTE_LABELS,
    ATTRIBUTES,
    WKG_RANGE,
    Rider,
    Team,
    generate_pool,
    generate_rider,
    generate_team,
)

router = APIRouter()

#: Grenzen, in denen ein von Hand gesetzter Wert bleiben muss. Dieselben
#: wie im Generator: darüber baut man keinen Fahrer mehr, sondern einen
#: Motor (Abschnitt 5.3).
ATTRIBUTE_RANGE = (1.0, 99.0)


def _tpl(request: Request):
    return request.app.state.templates


def _state(request: Request):
    return request.app.state.ultrasim


def _load(request: Request) -> tuple[list[Team], list[Rider]]:
    store = _state(request).store
    if not store.pool_exists():
        return [], []
    return store.load_pool()


# ----------------------------------------------------------------------
# Übersicht
# ----------------------------------------------------------------------
@router.get("/pool", response_class=HTMLResponse)
def pool_index(request: Request) -> HTMLResponse:
    teams, riders = _load(request)
    by_team: dict[int, int] = {}
    for rider in riders:
        by_team[rider.team_id] = by_team.get(rider.team_id, 0) + 1

    potentials = np.array([r.potential for r in riders]) if riders else np.zeros(0)
    return _tpl(request).TemplateResponse(
        request,
        "pool.html",
        {
            "teams": sorted(teams, key=lambda t: t.name),
            "riders": sorted(riders, key=lambda r: -r.potential),
            "team_names": {t.id: t.name for t in teams},
            "team_colors": {t.id: t.color for t in teams},
            "team_sizes": by_team,
            "archetypes": ARCHETYPES,
            "stats": {
                "n": len(riders),
                "mean": round(float(potentials.mean()), 1) if riders else 0.0,
                "sd": round(float(potentials.std()), 1) if riders else 0.0,
                "min": round(float(potentials.min()), 1) if riders else 0.0,
                "max": round(float(potentials.max()), 1) if riders else 0.0,
            },
        },
    )


# ----------------------------------------------------------------------
# Fahrerdetail
# ----------------------------------------------------------------------
@router.get("/pool/rider/{rider_id}", response_class=HTMLResponse)
def rider_edit(request: Request, rider_id: int) -> HTMLResponse:
    state = _state(request)
    teams, riders = _load(request)
    rider = next((r for r in riders if r.id == rider_id), None)
    if rider is None:
        raise HTTPException(status_code=404, detail=f"Kein Fahrer mit der ID {rider_id}")

    field_mean = float(np.mean([r.potential for r in riders])) if riders else 50.0
    return _tpl(request).TemplateResponse(
        request,
        "pool_rider.html",
        {
            "rider": rider,
            "teams": sorted(teams, key=lambda t: t.name),
            "team": next((t for t in teams if t.id == rider.team_id), None),
            "archetypes": ARCHETYPES,
            "weights": ATTRIBUTES,
            "labels": ATTRIBUTE_LABELS,
            "active": ACTIVE_ATTRIBUTES,
            "field_mean": round(field_mean, 1),
            "wkg_range": WKG_RANGE,
            "attr_range": ATTRIBUTE_RANGE,
            "routes": state.store.list_routes(),
        },
    )


@router.post("/pool/rider/{rider_id}")
async def rider_save(request: Request, rider_id: int) -> dict[str, Any]:
    """Fahrer speichern. Attribute kommen als JSON, weil es 25 sind."""
    state = _state(request)
    teams, riders = _load(request)
    rider = next((r for r in riders if r.id == rider_id), None)
    if rider is None:
        raise HTTPException(status_code=404, detail=f"Kein Fahrer mit der ID {rider_id}")

    body = await request.json()
    rider.name = str(body.get("name") or rider.name).strip() or rider.name
    rider.nation = str(body.get("nation") or rider.nation).strip()[:3].upper()
    rider.team_id = int(body.get("team_id", rider.team_id))
    rider.age = int(np.clip(int(body.get("age", rider.age)), 17, 60))
    rider.height_cm = float(np.clip(float(body.get("height_cm", rider.height_cm)), 150.0, 215.0))
    rider.weight_kg = float(np.clip(float(body.get("weight_kg", rider.weight_kg)), 45.0, 110.0))
    if body.get("archetype") in ARCHETYPES:
        rider.archetype = str(body["archetype"])

    # FTP bleibt im Plausibilitätsband des Generators. Ein Fahrer mit
    # 8 W/kg wäre kein Fahrer mehr, und die ganze Physikkalibrierung
    # hinge an einem einzigen Eingabefeld.
    ftp = float(body.get("ftp_w", rider.ftp_w))
    rider.ftp_w = float(
        np.clip(round(ftp), WKG_RANGE[0] * rider.weight_kg, WKG_RANGE[1] * rider.weight_kg)
    )

    for key, value in (body.get("attributes") or {}).items():
        if key in ATTRIBUTES:
            rider.attributes[key] = round(float(np.clip(float(value), *ATTRIBUTE_RANGE)), 1)

    state.store.save_pool(teams, riders)
    return {"rider_id": rider.id, "potential": round(rider.potential, 2), "wkg": round(rider.wkg, 3)}


#: Der Probelauf vergleicht zwei Fassungen desselben Fahrers in *einem*
#: Rennen. Dass das geht, ist keine Bequemlichkeit, sondern der Kern:
#: Die Zufallsströme hängen an der Fahrer-ID, also bekommen beide
#: Fassungen dasselbe Wetter, dieselben Pannenkandidaten und dieselbe
#: Tagesform. Was an Zeit übrig bleibt, sind die Änderungen und sonst
#: nichts — dieselbe Bauform wie die Attributmatrix in M8.
@router.post("/pool/rider/{rider_id}/probe")
async def rider_probe(request: Request, rider_id: int) -> dict[str, Any]:
    """Probelauf: Was bringen die Änderungen auf einer Strecke?"""
    from dataclasses import replace as dc_replace

    from ... import calibration as cal
    from ...core.engine import simulate_race
    from ..jobs import Job, race_progress

    state = _state(request)
    teams, riders = _load(request)
    original = next((r for r in riders if r.id == rider_id), None)
    if original is None:
        raise HTTPException(status_code=404, detail=f"Kein Fahrer mit der ID {rider_id}")

    body = await request.json()
    route_id = str(body.get("route_id") or "")
    try:
        route = state.store.load_route(route_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tuned = dc_replace(
        original,
        ftp_w=float(body.get("ftp_w", original.ftp_w)),
        weight_kg=float(body.get("weight_kg", original.weight_kg)),
        height_cm=float(body.get("height_cm", original.height_cm)),
        age=int(body.get("age", original.age)),
        attributes={
            key: round(float(np.clip(float(value), *ATTRIBUTE_RANGE)), 1)
            for key, value in (body.get("attributes") or original.attributes).items()
            if key in ATTRIBUTES
        },
    )
    key = f"tuner-{rider_id}"

    def work(job: Job) -> dict[str, Any]:
        job.detail = route.name
        result = simulate_race(
            route,
            [original, tuned],
            teams,
            cal.sensitivity_config(seed=int(body.get("seed", 4200))),
            progress=race_progress(job),
        )
        before, after = result.entries[0], result.entries[1]
        return {
            "route": route.name,
            "distance_km": round(route.distance_km, 1),
            "before_s": before.finish_time_s,
            "after_s": after.finish_time_s,
            "delta_s": (
                None
                if before.finish_time_s is None or after.finish_time_s is None
                else round(after.finish_time_s - before.finish_time_s, 1)
            ),
            "before_dnf": before.dnf_reason or None,
            "after_dnf": after.dnf_reason or None,
        }

    job = state.jobs.submit(kind="tuner", label=f"Probelauf {route.name}", work=work, season_id=key)
    return {"job_id": job.id, "poll": f"/api/season/{key}/jobs"}


@router.post("/pool/rider/{rider_id}/delete")
def rider_delete(request: Request, rider_id: int) -> RedirectResponse:
    state = _state(request)
    teams, riders = _load(request)
    state.store.save_pool(teams, [r for r in riders if r.id != rider_id])
    return RedirectResponse("/pool", status_code=303)


# ----------------------------------------------------------------------
# Erzeugen
# ----------------------------------------------------------------------
@router.post("/pool/generate")
def pool_generate(
    request: Request,
    count: int = Form(10),
    archetype: str = Form(""),
    team_id: int = Form(-1),
    potential_mean: float = Form(50.0),
    seed: int = Form(0),
) -> RedirectResponse:
    """Fahrer nachgenerieren und an den Pool anhängen.

    Ein leerer Pool bekommt zusätzlich Teams — ohne Team hat ein Fahrer
    keine Servicedisziplin, und die entscheidet über jede Stoppdauer.
    """
    state = _state(request)
    teams, riders = _load(request)
    if not teams:
        teams, riders = generate_pool(max(int(count), 2), seed=int(seed) or 1)
        state.store.save_pool(teams, riders)
        return RedirectResponse("/pool", status_code=303)

    rng = np.random.default_rng(int(seed) or None)
    next_id = max((r.id for r in riders), default=-1) + 1
    pick = archetype if archetype in ARCHETYPES else None
    targets = [t for t in teams if t.id == team_id] or teams

    for i in range(max(int(count), 1)):
        riders.append(
            generate_rider(
                rng,
                next_id + i,
                targets[i % len(targets)].id,
                archetype=pick,
                potential_mean=float(np.clip(potential_mean, 36.0, 64.0)),
            )
        )
    state.store.save_pool(teams, riders)
    return RedirectResponse("/pool", status_code=303)


@router.post("/pool/reset")
def pool_reset(
    request: Request, riders: int = Form(300), teams: int = Form(0), seed: int = Form(1)
) -> RedirectResponse:
    """Pool komplett neu würfeln.

    Das wirft alle Fahrer weg, auch die von Hand bearbeiteten — deshalb
    steht der Knopf hinter einer Bestätigung und in einem eigenen Feld.
    """
    state = _state(request)
    new_teams, new_riders = generate_pool(
        max(int(riders), 2), int(teams) or None, seed=int(seed)
    )
    state.store.save_pool(new_teams, new_riders)
    return RedirectResponse("/pool", status_code=303)


# ----------------------------------------------------------------------
# Teams
# ----------------------------------------------------------------------
@router.post("/pool/team/{team_id}")
def team_save(
    request: Request,
    team_id: int,
    name: str = Form(...),
    nation: str = Form(""),
    color: str = Form("#888888"),
    servicedisziplin: float = Form(50.0),
) -> RedirectResponse:
    state = _state(request)
    teams, riders = _load(request)
    team = next((t for t in teams if t.id == team_id), None)
    if team is None:
        raise HTTPException(status_code=404, detail=f"Kein Team mit der ID {team_id}")
    team.name = name.strip() or team.name
    team.nation = nation.strip()[:3].upper() or team.nation
    team.color = color if color.startswith("#") else team.color
    team.servicedisziplin = round(float(np.clip(servicedisziplin, 1.0, 99.0)), 1)
    state.store.save_pool(teams, riders)
    return RedirectResponse("/pool#teams", status_code=303)


@router.post("/pool/team")
def team_add(request: Request, name: str = Form("")) -> RedirectResponse:
    state = _state(request)
    teams, riders = _load(request)
    rng = np.random.default_rng(len(teams) + 1)
    team = generate_team(rng, max((t.id for t in teams), default=-1) + 1, {t.name for t in teams})
    if name.strip():
        team.name = name.strip()
    teams.append(team)
    state.store.save_pool(teams, riders)
    return RedirectResponse("/pool#teams", status_code=303)


@router.post("/pool/team/{team_id}/delete")
def team_delete(request: Request, team_id: int) -> RedirectResponse:
    """Team auflösen; seine Fahrer wandern ins erste verbleibende Team.

    Fahrer mitzulöschen wäre die andere Möglichkeit und die falsche: Ein
    Team ist ein Etikett, ein Fahrer ist der Inhalt.
    """
    state = _state(request)
    teams, riders = _load(request)
    remaining = [t for t in teams if t.id != team_id]
    if not remaining:
        raise HTTPException(status_code=400, detail="Das letzte Team lässt sich nicht löschen.")
    for rider in riders:
        if rider.team_id == team_id:
            rider.team_id = remaining[0].id
    state.store.save_pool(remaining, riders)
    return RedirectResponse("/pool#teams", status_code=303)
