"""Start der ausgelieferten Anwendung (Game-Design-Dokument, Abschnitt 16).

Die EXE braucht weder Java noch Kartendaten noch Netz. Strecken sind als
gzip-JSON mitgebündelt; Fahrerpool und gerechnete Rennen entstehen beim
ersten Start aus Seed und Strecke.

Zwei Verzeichnisse müssen dafür auseinandergehalten werden:

* das **Bündel** – schreibgeschützt, liegt bei PyInstaller in einem
  temporären Entpackverzeichnis und ist nach dem Beenden weg
* die **Nutzerdaten** – neben der EXE, überleben den Neustart

Beim ersten Start werden die mitgelieferten Strecken einmal aus dem
Bündel in die Nutzerdaten kopiert. Danach kann der Nutzer eigene
Strecken dazulegen, ohne dass ein Update sie überschreibt.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

DEFAULT_USER_DIR = "ultrasim-daten"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def bundle_dir() -> Path:
    """Verzeichnis der mitgelieferten Dateien."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def user_data_dir() -> Path:
    """Verzeichnis für alles, was geschrieben wird."""
    if override := os.environ.get("ULTRASIM_DATA"):
        return Path(override)
    if is_frozen():
        return Path(sys.executable).resolve().parent / DEFAULT_USER_DIR
    return Path("data")


def ensure_user_data(verbose: bool = True) -> Path:
    """Nutzerverzeichnis anlegen und mitgelieferte Strecken hineinkopieren."""
    root = user_data_dir()
    (root / "routes").mkdir(parents=True, exist_ok=True)
    (root / "races").mkdir(parents=True, exist_ok=True)
    (root / "seasons").mkdir(parents=True, exist_ok=True)
    # Hochgeladene GPX-Dateien bleiben liegen: Ein Neuimport mit anderen
    # Einstellungen soll die Datei nicht noch einmal verlangen.
    (root / "gpx").mkdir(parents=True, exist_ok=True)

    source = bundle_dir() / "data" / "routes"
    if source.is_dir() and source.resolve() != (root / "routes").resolve():
        for path in source.glob("*.json.gz"):
            target = root / "routes" / path.name
            if not target.exists():
                shutil.copy2(path, target)
                if verbose:
                    print(f"Strecke bereitgestellt: {target.name}")
    return root


def ensure_demo_race(root: Path, verbose: bool = True) -> str | None:
    """Beim ersten Start ein Rennen rechnen, damit es etwas zu sehen gibt.

    Ohne das stünde der Nutzer nach dem Doppelklick vor einer leeren
    Übersicht. Alles andere – eigene Strecken, Fahrerpool, Saison,
    Karriere – setzt eine Entscheidung voraus; dieses eine Rennen setzt
    keine voraus und beantwortet die erste Frage von selbst: Wie sieht
    das eigentlich aus?
    """
    from .core.engine import RaceConfig, simulate_race
    from .core.rider import generate_pool
    from .data.store import Store

    store = Store(root)
    if store.list_races():
        return None

    routes = store.list_routes()
    if not routes:
        if verbose:
            print("Keine Strecken gefunden – bitte zuerst eine GPX-Datei importieren.")
        return None

    # Die kürzeste Strecke ist die schnellste zum Vorzeigen.
    pick = min(routes, key=lambda r: r["distance_km"])
    if verbose:
        print(f"Erster Start: rechne ein Demo-Rennen auf '{pick['name']}' …")

    if store.pool_exists():
        teams, pool = store.load_pool()
    else:
        teams, pool = generate_pool(250, seed=1)
        store.save_pool(teams, pool)

    route = store.load_route(pick["id"])
    result = simulate_race(
        route, pool[:40], teams, RaceConfig(seed=42, name=f"{route.name} – Demo")
    )
    race_id = f"{pick['id']}-42"
    store.save_race(race_id, pick["id"], result, route=route)
    if verbose:
        print(f"Fertig in {result.compute_seconds:.1f} s.")
    return race_id


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - Startpfad
    import argparse
    import threading
    import webbrowser

    import uvicorn

    parser = argparse.ArgumentParser(description="UltraSim starten")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-demo", action="store_true", help="kein Demo-Rennen rechnen")
    args = parser.parse_args(argv)

    root = ensure_user_data()
    os.environ["ULTRASIM_DATA"] = str(root)
    if not args.no_demo:
        ensure_demo_race(root)

    from .web.main import create_app

    url = f"http://{args.host}:{args.port}/"
    print(f"UltraSim läuft auf {url}  (Beenden mit Strg+C)")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(create_app(root), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
