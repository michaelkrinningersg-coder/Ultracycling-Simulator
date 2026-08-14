"""Streckenverwaltung, GPX-Import und Streckeneditor (Abschnitt 10.3).

Bis M5b konnte man Strecken nur auf der Kommandozeile anlegen. Für die
ausgelieferte EXE hieß das: Wer sie doppelklickt, hat für immer die drei
mitgelieferten Strecken. Das Dokument sagt in Abschnitt 10.3 aber
ausdrücklich, dass das Bauen die Interaktion *ist* — der Nutzer fährt
nicht, er kuratiert.

Zwei Wege enden hier auf derselben Seite:

* **Import** — GPX hochladen, die Kette aus ``geo.gpx_import`` läuft
  durch, das Ergebnis liegt als Entwurf im Speicher und wird im Editor
  gezeigt, *bevor* etwas auf die Platte geht
* **Bearbeiten** — eine vorhandene Strecke im selben Editor öffnen

Der Editor ist damit auch die Vorschau, die das Dokument verlangt. Eine
getrennte Vorschauseite hätte dieselben Daten, dieselbe Zeichnung und
dieselben Knöpfe — nur ohne die Möglichkeit, das Gesehene gleich zu
korrigieren.

Warum Marker per JSON und nicht als Formular gespeichert werden: Splits
und Servicepunkte sind eine Liste veränderlicher Länge. Als Formular
bräuchte sie durchnummerierte Feldnamen, die der Client beim Einfügen in
der Mitte neu vergeben müsste. Die Kalenderformulare bleiben Formulare,
weil sie feste Felder haben; hier ist JSON die ehrlichere Form.
"""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from ...geo.gpx_import import GpxImportError, ImportReport, import_gpx
from ...geo.route import Route
from ...geo.splits import (
    MIN_MARKER_GAP_M,
    normalise_service_points,
    normalise_splits,
)
from ...season_runner import slugify

router = APIRouter()

#: Stützstellen des Profils in der Editor-Vorschau. Mehr als das kann ein
#: Canvas von 1200 px Breite ohnehin nicht auflösen.
PROFILE_POINTS = 1400

#: Obergrenze für hochgeladene GPX-Dateien. Eine 2500-km-Aufzeichnung mit
#: einem Punkt je Sekunde liegt bei rund 20 MB; darüber ist es keine
#: Radstrecke mehr, sondern ein Versehen.
MAX_UPLOAD_BYTES = 40 * 1024 * 1024

# FastAPIs Marker gehören als Vorgabewert in die Signatur; als
# Modulkonstante bleiben sie ruff-konform (B008).
_GPX_FILE = File(...)
_NAME_FIELD = Form("")


def _tpl(request: Request):
    return request.app.state.templates


def _state(request: Request):
    return request.app.state.ultrasim


# ----------------------------------------------------------------------
# Übersicht
# ----------------------------------------------------------------------
@router.get("/routes", response_class=HTMLResponse)
def routes_index(request: Request) -> HTMLResponse:
    state = _state(request)
    usage = _route_usage(state.store)
    rows = [
        {**route, "races": usage.get(route["id"], [])} for route in state.store.list_routes()
    ]
    return _tpl(request).TemplateResponse(
        request, "routes.html", {"routes": rows, "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024)}
    )


def _route_usage(store) -> dict[str, list[str]]:
    """Welches Rennen auf welcher Strecke gefahren wurde.

    Nur zur Information: Seit jedes Rennen seine Strecke als Kopie trägt,
    hindert eine Benutzung niemanden mehr am Bearbeiten. Wissen will man
    es trotzdem.
    """
    out: dict[str, list[str]] = {}
    for race in store.list_races():
        out.setdefault(race["route_id"], []).append(race["name"])
    return out


# ----------------------------------------------------------------------
# Import
# ----------------------------------------------------------------------
@router.post("/routes/import")
async def route_import(
    request: Request,
    gpx: UploadFile = _GPX_FILE,
    name: str = _NAME_FIELD,
) -> RedirectResponse:
    state = _state(request)
    payload = await gpx.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Die Datei ist größer als {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    # Der Importer liest von der Platte. Die Datei landet deshalb im
    # Datenverzeichnis unter data/gpx/ – dort gehört sie auch hin, und
    # ein späterer Neuimport mit anderen Einstellungen braucht sie nicht
    # noch einmal hochzuladen.
    gpx_dir = state.store.root / "gpx"
    gpx_dir.mkdir(parents=True, exist_ok=True)
    target = gpx_dir / f"{slugify(gpx.filename or 'strecke', 'strecke')}.gpx"
    target.write_bytes(payload)

    try:
        route, report = import_gpx(target, name=name.strip() or None)
    except GpxImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - kaputte GPX sind Nutzereingabe
        raise HTTPException(
            status_code=400, detail=f"GPX konnte nicht gelesen werden: {exc}"
        ) from exc

    token = uuid.uuid4().hex[:12]
    state.add_draft(token, route, report)
    return RedirectResponse(f"/routes/draft/{token}", status_code=303)


# ----------------------------------------------------------------------
# Editor
# ----------------------------------------------------------------------
@router.get("/routes/draft/{token}", response_class=HTMLResponse)
def route_draft(request: Request, token: str) -> HTMLResponse:
    state = _state(request)
    draft = state.drafts.get(token)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail="Der Import ist abgelaufen. Bitte die GPX-Datei erneut hochladen.",
        )
    route, report = draft
    return _editor(request, route, report=report, draft_token=token)


@router.get("/route/{route_id}", response_class=HTMLResponse)
def route_edit(request: Request, route_id: str) -> HTMLResponse:
    route = _state(request).store.load_route(route_id)
    return _editor(request, route, route_id=route_id)


def _editor(
    request: Request,
    route: Route,
    route_id: str | None = None,
    report: ImportReport | None = None,
    draft_token: str | None = None,
) -> HTMLResponse:
    usage = _route_usage(_state(request).store).get(route_id or "", [])
    return _tpl(request).TemplateResponse(
        request,
        "route_editor.html",
        {
            "route": route,
            "route_id": route_id,
            "draft_token": draft_token,
            "report": report,
            "usage": usage,
            "suggested_id": slugify(route.name, "strecke"),
            "route_json": route_payload(route),
            "min_gap_m": MIN_MARKER_GAP_M,
        },
    )


def route_payload(route: Route) -> dict[str, Any]:
    """Profil, Anstiege und Marker für die Zeichnung im Browser."""
    n = min(PROFILE_POINTS, route.n_points)
    idx = np.linspace(0, route.n_points - 1, n).astype(np.int64)
    return {
        "name": route.name,
        "distance_m": route.distance_m,
        "ascent_m": round(route.ascent_m),
        "distance_class": route.distance_class,
        "profile": {
            "dist_m": [int(i * route.raster_m) for i in idx],
            "ele_m": [round(float(route.ele_m[i]), 1) for i in idx],
            "grade": [round(float(route.grade[i]), 4) for i in idx],
        },
        "climbs": [
            {
                "dist_start_m": c.dist_start_m,
                "dist_end_m": c.dist_end_m,
                "category": c.category,
                "ascent_m": c.ascent_m,
                "grade_avg": c.grade_avg,
                "length_m": c.length_m,
            }
            for c in route.climbs
        ],
        "splits": [
            {"idx": s.idx, "dist_m": s.dist_m, "name": s.name, "kind": s.kind}
            for s in route.splits
        ],
        "service_points": [
            {"idx": p.idx, "dist_m": p.dist_m, "name": p.name} for p in route.service_points
        ],
    }


# ----------------------------------------------------------------------
# Speichern
# ----------------------------------------------------------------------
@router.post("/api/route/save")
async def route_save(request: Request) -> dict[str, Any]:
    """Marker und Name einer Strecke festschreiben.

    Nimmt sowohl einen Entwurf aus dem Import als auch eine vorhandene
    Strecke entgegen — der einzige Unterschied ist, woher die Geometrie
    kommt. Die Geometrie selbst ist unveränderlich: Der Editor bewegt
    Marker, keine Höhenpunkte.
    """
    state = _state(request)
    body = await request.json()

    token = body.get("draft_token")
    route_id = body.get("route_id")
    if token:
        draft = state.drafts.get(token)
        if draft is None:
            raise HTTPException(status_code=404, detail="Der Import ist abgelaufen.")
        route = draft[0]
    elif route_id:
        route = state.store.load_route(route_id)
    else:
        raise HTTPException(status_code=400, detail="Weder Entwurf noch Strecke angegeben.")

    name = str(body.get("name") or route.name).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Die Strecke braucht einen Namen.")
    route.name = name

    route.splits = normalise_splits(
        [
            (row.get("dist_m", 0.0), str(row.get("name", "")), str(row.get("kind", "interval")))
            for row in body.get("splits", [])
        ],
        route.distance_m,
    )
    route.service_points = normalise_service_points(
        [(row.get("dist_m", 0.0), str(row.get("name", ""))) for row in body.get("service_points", [])],
        route.distance_m,
    )

    target_id = str(body.get("id") or route_id or slugify(name, "strecke"))
    if not route_id and state.store.routes_dir.joinpath(f"{target_id}.json.gz").exists():
        raise HTTPException(
            status_code=409, detail=f"Eine Strecke mit der Kennung '{target_id}' gibt es schon."
        )

    state.store.routes_dir.mkdir(parents=True, exist_ok=True)
    route.save(state.store.routes_dir / f"{target_id}.json.gz")
    if token:
        state.drafts.pop(token, None)
    return {"route_id": target_id, "n_splits": len(route.splits), "url": f"/route/{target_id}"}


@router.post("/routes/draft/{token}/discard")
def route_discard(request: Request, token: str) -> RedirectResponse:
    _state(request).drafts.pop(token, None)
    return RedirectResponse("/routes", status_code=303)


@router.post("/route/{route_id}/delete")
def route_delete(request: Request, route_id: str) -> RedirectResponse:
    """Streckendatei löschen.

    Gerechnete Rennen überleben das: Sie tragen ihre Strecke als Kopie im
    eigenen Verzeichnis. Kalendertermine, die auf sie zeigen, nicht — die
    zeigen danach ins Leere und melden das auf der Saisonseite.
    """
    state = _state(request)
    path = state.store.routes_dir / f"{route_id}.json.gz"
    if path.exists():
        path.unlink()
    return RedirectResponse("/routes", status_code=303)
