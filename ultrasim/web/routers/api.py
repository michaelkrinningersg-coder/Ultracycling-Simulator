"""JSON- und SSE-Schnittstellen für das Telemetrie-Board."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse as _JSONResponse
from fastapi.responses import StreamingResponse

from ...core.events import format_event
from ...core.physics import BIKE_NAMES
from ..playback import SORT_FIELDS, SPEEDS, PlaybackSession, RaceView

router = APIRouter(prefix="/api")


class JSONResponse(_JSONResponse):
    """JSON-Antwort, die NumPy-Skalare mitnimmt.

    Frame-Daten stammen direkt aus Telemetriearrays. Jeden einzelnen Wert
    von Hand zu casten wäre eine Fehlerquelle, die genau dann zuschlägt,
    wenn ein selten betretener Zweig ein ``np.bool_`` durchreicht –
    deshalb einmal zentral hier.
    """

    def render(self, content: Any) -> bytes:
        return dumps(content).encode("utf-8")


def dumps(content: Any) -> str:
    """JSON-Serialisierung, die NumPy-Skalare kennt (auch für SSE)."""
    return json.dumps(content, separators=(",", ":"), ensure_ascii=False, default=_np_default)


def _np_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Nicht serialisierbar: {type(value).__name__}")

#: Anzahl Stützstellen des Höhenprofils, die an den Client gehen.
#: 1200 Punkte reichen für eine 2500-km-Strecke auf einem 1600-px-Canvas
#: völlig aus – der Bildschirm hat nicht mehr Pixel.
PROFILE_POINTS = 1200


def _state(request: Request):
    return request.app.state.ultrasim


def _session(request: Request, token: str) -> PlaybackSession:
    session = _state(request).playback.get(token)
    if session is None:
        raise HTTPException(status_code=404, detail="Playback-Sitzung unbekannt oder abgelaufen")
    return session


def _live_view(request: Request, session: PlaybackSession) -> tuple[Any, Any, RaceView]:
    """Sitzung auf den Stand bringen und die Leseschicht holen.

    Bei einem gespeicherten Rennen ist das ``state.view(...)`` und sonst
    nichts. Bei einem live gerechneten kommen zwei Schritte davor:

    1. Den Zeitstrahl auf die aktuelle Schätzung setzen, *bevor* die Uhr
       gelesen wird — sonst schneidet ``now()`` an einem Horizont ab,
       der noch von vorhin stammt.
    2. Bis zur so gelesenen Wanduhrzeit rechnen. Erst danach existieren
       die Daten, die das Bild gleich zeigt.

    Danach steht der Zeitstrahl gegebenenfalls fest (das Rennen ist im
    Ziel) und wird ein zweites Mal gesetzt, diesmal nach unten.
    """
    state = _state(request)
    room = state.live.get(session.race_id)
    if room is not None:
        session.set_horizon(room.horizon_s)
        room.advance(session.now())
        session.set_horizon(room.horizon_s)
    return state.view(session.race_id)


# ----------------------------------------------------------------------
# Statische Renn- und Streckendaten
# ----------------------------------------------------------------------
@router.get("/race/{race_id}/route")
def route_data(request: Request, race_id: str) -> JSONResponse:
    """Streckenprofil, Splits, Anstiege, Servicepunkte – einmal je Seite."""
    _, route, _ = _state(request).view(race_id)

    n = min(PROFILE_POINTS, route.n_points)
    idx = np.linspace(0, route.n_points - 1, n).astype(np.int64)
    return JSONResponse(
        {
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
    )


@router.get("/race/{race_id}/startlist")
def startlist(request: Request, race_id: str) -> JSONResponse:
    """Startliste – Stammdaten, die sich während des Rennens nicht ändern."""
    result, _, view = _state(request).view(race_id)
    rows = []
    for entry in result.entries:
        rider = view.riders[entry.rider_id]
        team = view.teams.get(rider.team_id)
        rows.append(
            {
                "entry_id": entry.entry_id,
                "bib": entry.bib,
                "name": rider.name,
                "nation": rider.nation,
                "team": team.name if team else "",
                "color": team.color if team else "#888888",
                "archetype": rider.archetype,
                "ftp_w": rider.ftp_w,
                "start_offset_s": entry.start_offset_s,
            }
        )
    return JSONResponse({"entries": rows, "n": len(rows)})


# ----------------------------------------------------------------------
# Playback-Sitzung
# ----------------------------------------------------------------------
@router.post("/race/{race_id}/session")
def create_session(request: Request, race_id: str) -> JSONResponse:
    state = _state(request)
    result, _, _ = state.view(race_id)
    room = state.live.get(race_id)
    state.playback.prune()
    horizon = room.horizon_s if room is not None else result.last_finish_wallclock_s
    token, session = state.playback.create(race_id, horizon)
    if room is not None and not room.finished:
        # Live gibt es nichts zu überspringen: Der erste Starter rollt
        # jetzt, und vor ihm ist niemand unterwegs. Der Fokus liegt
        # deshalb auf ihm statt auf dem Favoriten — der steht noch
        # stundenlang im Startbereich, und ihn zu zeigen hieße, die
        # Übertragung mit einem Standbild zu eröffnen.
        session.focus_entry = min(
            range(len(result.entries)), key=lambda i: result.entries[i].start_offset_s
        )
        session.sim_t = 0.0
        return JSONResponse({"token": token, "session": session.to_dict(), "live": True})
    # Der Fokus liegt anfangs auf dem Fahrer mit der höchsten Startnummer –
    # beim Zeitfahren also auf dem gesetzten Favoriten.
    session.focus_entry = max(range(len(result.entries)), key=lambda i: result.entries[i].bib)
    # …und die Uhr auf seinen Start. Bei halbstündigem Startabstand und
    # 250 Fahrern liegt der Favorit fünf Tage hinter dem ersten Starter;
    # bei null zu beginnen hieße, die Übertragung mit einem Fahrer zu
    # eröffnen, der noch tagelang nicht losfährt. So schaltet man dazu,
    # wenn er rollt — vor ihm ist das halbe Feld schon unterwegs, und
    # das Board hat Zeiten, in die er sich einordnen kann.
    session.sim_t = float(result.entries[session.focus_entry].start_offset_s)
    return JSONResponse({"token": token, "session": session.to_dict(), "live": False})


@router.post("/playback/{token}/control")
async def control(request: Request, token: str) -> JSONResponse:
    session = _session(request, token)
    _, _, view = _live_view(request, session)
    body: dict[str, Any] = await request.json()
    action = body.get("action")
    value = body.get("value")

    if action == "play":
        session.play()
    elif action == "pause":
        session.pause()
    elif action == "toggle":
        session.pause() if session.playing else session.play()
    elif action == "speed":
        if int(value) not in SPEEDS:
            raise HTTPException(400, f"Zeitraffer muss aus {SPEEDS} stammen")
        session.set_speed(int(value))
    elif action == "seek":
        session.seek(float(value))
    elif action == "focus":
        session.focus_entry = int(np.clip(int(value), 0, view.n - 1))
    elif action == "split":
        session.split_idx = int(np.clip(int(value), 0, len(view.route.splits) - 1))
        session.split_follow = False
    elif action == "split_follow":
        session.split_follow = bool(value)
    elif action == "mode":
        session.mode = "virtual" if value == "virtual" else "split"
    elif action == "sort":
        # Zweimal dieselbe Spalte dreht die Richtung um — die einzige
        # Geste, die eine Tabellenüberschrift überall sonst auch hat.
        key = str(value or "zeit")
        if key != "zeit" and key not in SORT_FIELDS:
            raise HTTPException(400, f"Unbekannte Sortierspalte: {key}")
        session.sort_desc = key == session.sort and not session.sort_desc
        session.sort = key
    elif action == "pin":
        session.toggle_pin(int(np.clip(int(value), 0, view.n - 1)))
    elif action == "next_split":
        target = view.next_split_time(session.now(), session.focus_entry)
        if target is not None:
            session.seek(target + 1.0)
    elif action == "next_event":
        target = view.next_event_time(session.now(), session.focus_entry)
        if target is not None:
            session.seek(target + 1.0)
    elif action == "distance":
        # Sprung zu einer Distanzmarke des Fokusfahrers.
        target = _wallclock_at_distance(view, session.focus_entry, float(value))
        if target is not None:
            session.seek(target)
    else:
        raise HTTPException(400, f"Unbekannte Aktion: {action}")
    # Ein Sprung nach vorn verlangt beim Live-Rennen Rechenzeit, bevor
    # dort etwas zu sehen ist. Sie hier zu bezahlen statt beim nächsten
    # Bild heißt: Der Knopf antwortet erst, wenn er auch etwas bewirkt
    # hat — und der Zeitstrahl in der Antwort stimmt schon.
    _live_view(request, session)
    return JSONResponse(session.to_dict())


def _wallclock_at_distance(view: RaceView, entry_id: int, dist_m: float) -> float | None:
    track = view.telemetry.dist_m[entry_id]
    i = int(np.searchsorted(track, dist_m, side="left"))
    if i >= track.size:
        return None
    return float(view.offsets[entry_id] + i * view.telemetry.sample_dt_s)


# ----------------------------------------------------------------------
# Frames
# ----------------------------------------------------------------------
def build_frame(view: RaceView, session: PlaybackSession, t_from: float | None = None) -> dict[str, Any]:
    """Ein vollständiger Zustand zur aktuellen Wanduhrzeit.

    Alles, was hier hineingeht, ist an ``session.now()`` abgeschnitten.
    Der Client bekommt nie einen Blick nach vorn.
    """
    t = session.now()
    snap = view.snapshot(t)
    focus = session.focus_entry
    result = view.result

    if session.split_follow and session.mode != "virtual":
        session.split_idx = view.last_split_index(t, focus)

    opts = {"sort": session.sort, "sort_desc": session.sort_desc, "pinned": session.pinned}
    board = (
        view.virtual_rows(t, focus, **opts)
        if session.mode == "virtual"
        else view.board_rows(t, session.split_idx, focus, **opts)
    )

    entry = result.entries[focus]
    rider = view.riders[entry.rider_id]
    grade = float(view.route.grade_at(np.array([snap["dist"][focus]]))[0])
    own_time = float(snap["elapsed"][focus])
    clock = (session_clock(result, own_time)) if own_time >= 0 else None

    # Positionen: ausgedünnt auf Ganzmeter, damit der Frame klein bleibt.
    positions = [
        [int(i), int(snap["dist"][i]), int(round(snap["v"][i] * 3.6)), int(snap["state"][i])]
        for i in range(view.n)
        if snap["started"][i]
    ]

    events = view.events_between(t_from if t_from is not None else t - 5.0, t, session.speed, focus)
    ticker = [
        {
            "entry_id": e.entry_id,
            "t_s": round(e.t_s, 1),
            "type": e.type,
            "text": format_event(e, view.riders[result.entries[e.entry_id].rider_id].name),
            "focus": e.entry_id == focus,
        }
        for e in events
    ]

    return {
        "t_wall": round(t, 2),
        "playing": session.playing,
        "speed": session.speed,
        "mode": session.mode,
        "split_follow": session.split_follow,
        "sort": session.sort,
        "sort_desc": session.sort_desc,
        "pinned": list(session.pinned),
        "horizon_s": round(session.horizon_s, 1),
        "positions": positions,
        "board": board,
        "ticker": ticker,
        "focus": {
            "entry_id": focus,
            "bib": entry.bib,
            "name": rider.name,
            "nation": rider.nation,
            "team": view.teams[rider.team_id].name if rider.team_id in view.teams else "",
            "color": view.teams[rider.team_id].color if rider.team_id in view.teams else "#888",
            "started": bool(snap["started"][focus]),
            "factors": view.factors_at(focus, t),
            "own_time_s": round(max(own_time, 0.0), 1),
            "own_clock": clock,
            "dist_m": int(snap["dist"][focus]),
            "remaining_m": int(max(view.route.distance_m - snap["dist"][focus], 0)),
            "v_kmh": round(float(snap["v"][focus]) * 3.6, 1),
            "power_w": int(snap["power"][focus]),
            "grade_pct": round(grade * 100.0, 1),
            "form_pct": int(snap["form"][focus]),
            "wprime_pct": int(snap["wprime"][focus]),
            "glyco_pct": int(snap["glyco"][focus]),
            "sleep_pct": int(snap["sleep"][focus]),
            "hydration_pct": int(snap["hydration"][focus]),
            "giveup_pct": (
                None if snap["giveup"] is None else int(snap["giveup"][focus])
            ),
            "bike": BIKE_NAMES[int(snap["bike"][focus])],
            "state": int(snap["state"][focus]),
            "conditions": view.conditions_at(focus, t),
            "tactics": view.tactics_at(focus, t),
            "finished": bool(
                entry.finish_time_s is not None
                and view.offsets[focus] + entry.finish_time_s <= t
            ),
        },
        "field": {
            "on_course": int(
                np.sum(snap["started"] & (snap["state"] < 2)),
            ),
            "finished": int(np.sum(snap["state"] == 2)),
            "started": int(np.sum(snap["started"])),
            "total": view.n,
        },
    }


def session_clock(result, own_time_s: float) -> str:
    """Persönliche Uhrzeit des Fahrers (Fahrer-Eigenzeit, Entscheidung 13).

    Eine absolute Wanduhrzeit taucht in der UI nirgends auf – sie hätte
    für den Zuschauer keine Bedeutung. Wohl aber die eigene: "km 1420,
    03:40 Fahrerzeit, zweite Nacht".
    """
    total = int(result.config.start_time_of_day_s + own_time_s)
    day = total // 86400
    rest = total % 86400
    label = f"{rest // 3600:02d}:{(rest % 3600) // 60:02d}"
    return f"{label}" if day == 0 else f"{label} (Tag {day + 1})"


@router.get("/playback/{token}/frame")
def frame(request: Request, token: str) -> JSONResponse:
    session = _session(request, token)
    _, _, view = _live_view(request, session)
    return JSONResponse(build_frame(view, session))


@router.get("/playback/{token}/stream")
async def stream(request: Request, token: str) -> StreamingResponse:
    """SSE-Strom – Einweg vom Server zum Client, genau unser Fall.

    Der Strom wird serverseitig an der Wanduhr abgeschnitten; er kann
    prinzipbedingt nichts aus der Zukunft enthalten.
    """
    session = _session(request, token)
    state = _state(request)

    async def generator():
        last_t = session.now()
        try:
            while True:
                if await request.is_disconnected():
                    break
                # Je Bild neu geholt statt einmal vorab: Bei einem live
                # gerechneten Rennen ist die Leseschicht von vorhin
                # buchstäblich von vorhin — sie kennt die letzten zehn
                # Minuten Rennen noch nicht.
                #
                # Und in einem Thread, nicht hier: Ein Zeitraffer von
                # 1000x bei vollem Feld sind rund eine halbe Sekunde
                # Rechenzeit je Bild. Die im Ereignis-Loop zu
                # verbringen hieße, den ganzen Server so lange
                # anzuhalten — samt aller anderen Zuschauer.
                _, _, view = await asyncio.to_thread(_live_view, request, session)
                payload = build_frame(view, session, t_from=last_t)
                last_t = payload["t_wall"]
                yield f"event: frame\ndata: {dumps(payload)}\n\n"
                await asyncio.sleep(session.frame_interval_s())
        except asyncio.CancelledError:  # pragma: no cover - Verbindungsabbruch
            raise
        finally:
            # Wer das Fenster schließt, soll kein Rennen weiterrechnen
            # lassen. Der Stand von jetzt geht dabei auf die Platte —
            # das nächste Aufrufen der Seite setzt dort wieder an.
            room = state.live.get(session.race_id)
            if room is not None:
                room.save()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ----------------------------------------------------------------------
# Nach dem Rennen
# ----------------------------------------------------------------------
@router.get("/race/{race_id}/rider/{entry_id}/curves")
def rider_curves(request: Request, race_id: str, entry_id: int) -> JSONResponse:
    """Verlaufskurven für das Fahrerdetail.

    Bewusst ohne Wanduhr-Beschränkung: Das Fahrerdetail ist ein
    Nachbetrachtungs-Screen und in der UI hinter einem Spoiler-Hinweis
    verlinkt.
    """
    result, route, view = _state(request).view(race_id)
    if not 0 <= entry_id < len(result.entries):
        raise HTTPException(404, "Kein solcher Starter")
    tel = result.telemetry
    state = tel.state[entry_id]
    active = np.flatnonzero(state < 2)
    end = int(active[-1]) + 1 if active.size else tel.n_samples
    step = max(1, end // 1500)
    sl = slice(0, end, step)
    t = (np.arange(0, end, step) * tel.sample_dt_s).astype(float)
    return JSONResponse(
        {
            "t_s": t.tolist(),
            "dist_km": (tel.dist_m[entry_id, sl] / 1000.0).round(3).tolist(),
            "v_kmh": (tel.v_cms[entry_id, sl] * 0.036).round(1).tolist(),
            "power_w": tel.power_w[entry_id, sl].astype(int).tolist(),
            "form_pct": tel.form_pct[entry_id, sl].astype(int).tolist(),
            "wprime_pct": tel.wprime_pct[entry_id, sl].astype(int).tolist(),
            "glyco_pct": tel.glyco_pct[entry_id, sl].astype(int).tolist(),
            "sleep_pct": tel.sleep_pct[entry_id, sl].astype(int).tolist(),
            "hydration_pct": tel.hydration_pct[entry_id, sl].astype(int).tolist(),
            "bike": tel.bike[entry_id, sl].astype(int).tolist(),
        }
    )


@router.get("/season/{season_id}/jobs")
def season_jobs(request: Request, season_id: str) -> JSONResponse:
    """Fortschritt der Rechenaufträge einer Saison.

    Die Kalenderseite fragt das im Sekundentakt ab, solange etwas läuft,
    und lädt sich neu, sobald die Schlange leer ist.
    """
    runner = _state(request).jobs
    return JSONResponse([job.to_dict() for job in runner.list_jobs(season_id)[:12]])
