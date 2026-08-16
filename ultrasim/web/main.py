"""FastAPI-Anwendung (Game-Design-Dokument, Abschnitt 13).

Start im Entwicklungsbetrieb:

    python -m ultrasim.web.main --reload

Die Web-App zeigt gerechnete Rennen. Seit dem Kalender (M7) kann sie
Rennen auch *anstoßen* — nicht selbst rechnen: Sie legt einen Auftrag in
die Warteschlange aus ``jobs.py``, der Arbeiterthread ruft dieselbe
Bibliotheksfunktion auf wie die Kommandozeile. Alles, was sie braucht,
liegt unter ``data/``.
"""

from __future__ import annotations

import argparse
import os
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core.engine import RaceResult
from ..data.store import Store
from ..geo.route import Route
from .jobs import JobRunner
from .livesim import LiveRegistry, LiveRoom
from .playback import PlaybackRegistry, RaceView

BASE_DIR = Path(__file__).parent


class AppState:
    """Gemeinsamer Zustand: Datenspeicher, Playback-Sitzungen, Cache."""

    def __init__(self, data_root: str | Path) -> None:
        self.store = Store(data_root)
        self.playback = PlaybackRegistry()
        self.jobs = JobRunner()
        #: Rennen, die gerade entstehen (Abschnitt 8.2). Sie liegen vor
        #: dem Plattencache: Solange ein Rennen live läuft, ist der
        #: Speicher der Wahrheitsstand und die Datei nur die Sicherung.
        self.live = LiveRegistry()
        #: Importierte, aber noch nicht gespeicherte Strecken (M5b).
        #: Bewusst nur im Speicher: Ein Entwurf ist eine Vorschau, keine
        #: Datenlage. Wer den Server neu startet, lädt die GPX-Datei neu –
        #: sie liegt ohnehin schon unter data/gpx/.
        self.drafts: OrderedDict[str, tuple[Route, object]] = OrderedDict()
        self._max_drafts = 8
        self._views: OrderedDict[str, tuple[RaceResult, Route, RaceView]] = OrderedDict()
        self._max_cached = 3

    def view(self, race_id: str) -> tuple[RaceResult, Route, RaceView]:
        """Rennen laden und im Speicher halten.

        Telemetrie eines Ultra-Rennens sind zweistellige Megabyte – die
        bei jedem Frame neu von der Platte zu lesen wäre grober Unfug,
        drei Rennen gleichzeitig im Speicher zu halten aber auch.

        Ein live laufendes Rennen sticht den Plattencache: Auf der Platte
        liegt bestenfalls der Stand der letzten Sicherung.
        """
        room = self.live.get(race_id)
        if room is not None:
            return room.bundle()
        if race_id in self._views:
            self._views.move_to_end(race_id)
            return self._views[race_id]
        result, route_id = self.store.load_race(race_id)
        route = self.store.race_route(race_id, route_id)
        bundle = (result, route, RaceView(result, route))
        self._views[race_id] = bundle
        while len(self._views) > self._max_cached:
            self._views.popitem(last=False)
        return bundle

    def invalidate(self, race_id: str) -> None:
        self._views.pop(race_id, None)

    def advance(self, race_id: str, t_wall: float) -> LiveRoom | None:
        """Ein laufendes Rennen bis zur Wanduhrzeit nachrechnen.

        Für ein gespeichertes Rennen ein No-op — die Aufrufer in
        ``api.py`` müssen deshalb nicht wissen, welche Art Rennen sie
        gerade bedienen.
        """
        room = self.live.get(race_id)
        if room is not None:
            room.advance(t_wall)
        return room

    def add_draft(self, token: str, route: Route, report: object) -> None:
        self.drafts[token] = (route, report)
        while len(self.drafts) > self._max_drafts:
            self.drafts.popitem(last=False)


def create_app(data_root: str | Path | None = None) -> FastAPI:
    root = data_root or os.environ.get("ULTRASIM_DATA", "data")
    app = FastAPI(title="UltraSim", docs_url=None, redoc_url=None)
    app.state.ultrasim = AppState(root)

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.filters["hms"] = _hms
    templates.env.filters["gap"] = _gap
    templates.env.filters["de_date"] = _de_date
    app.state.templates = templates

    from .routers import (  # zirkuläre Importe vermeiden
        api,
        careers,
        pages,
        pool,
        routes,
        seasons,
        stats,
    )

    app.include_router(pages.router)
    app.include_router(routes.router)
    app.include_router(pool.router)
    app.include_router(seasons.router)
    app.include_router(careers.router)
    app.include_router(stats.router)
    app.include_router(api.router)

    @app.exception_handler(FileNotFoundError)
    async def _not_found(request: Request, exc: FileNotFoundError) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "error.html", {"message": str(exc)}, status_code=404
        )

    return app


def _hms(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = int(round(float(seconds)))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _de_date(day) -> str:
    """Datum, wie man es in Deutschland liest."""
    if day is None:
        return "—"
    return day.strftime("%d.%m.%Y")


def _gap(seconds: float | None) -> str:
    if seconds is None:
        return ""
    sign = "+" if seconds >= 0 else "−"
    total = int(round(abs(float(seconds))))
    m, s = divmod(total, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{sign}{h}:{m:02d}:{s:02d}"
    return f"{sign}{m}:{s:02d}"


app = create_app()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - Startpfad
    import uvicorn

    parser = argparse.ArgumentParser(description="UltraSim-Weboberfläche starten")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", default=None, help="Datenverzeichnis")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--open", action="store_true", help="Browser öffnen")
    args = parser.parse_args(argv)

    if args.data:
        os.environ["ULTRASIM_DATA"] = args.data
    if args.open:
        import threading
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(f"http://{args.host}:{args.port}/")).start()

    uvicorn.run(
        "ultrasim.web.main:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
