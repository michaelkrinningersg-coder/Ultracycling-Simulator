"""Persistenz (Game-Design-Dokument, Abschnitt 12).

Zwei Speicherformen, weil die Daten zwei sehr verschiedene Größen haben:

* **Stammdaten** (Teams, Fahrer, Rennen, Splitzeiten, Ereignisse) sind
  klein und werden als JSON abgelegt.
* **Telemetrie** ist die einzige Struktur, die groß wird. Sie liegt als
  ``.npz`` je Rennen: ein Array der Form ``(n_fahrer, n_samples,
  n_kanäle)``, aus dem der Playback-Server in Millisekunden ein
  Zeitfenster über alle Fahrer schneidet.

Abweichung vom Dokument, bewusst und benannt: Abschnitt 13 sieht für die
Stammdaten SQLAlchemy + SQLite vor. Solange es weder Saison noch
Kalender noch Gesamtwertung gibt (M7), gibt es auch nichts zu joinen –
eine Datei je Rennen ist einfacher, schneller und hält das
PyInstaller-Bundle klein. Die Zugriffe laufen deshalb schon jetzt über
dieses Repository-Modul und nicht verstreut über die Anwendung, damit
der Wechsel auf SQLAlchemy später ein einzelner Austausch ist.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from ..core.engine import RaceConfig, RaceEntry, RaceResult, Telemetry
from ..core.events import RaceEvent
from ..core.rider import Rider, Team
from ..core.strategy import RacePlan, SectionPlan
from ..geo.route import Route

DEFAULT_ROOT = Path("data")


class Store:
    """Dateibasierter Datenspeicher."""

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------
    # Pfade
    # ------------------------------------------------------------------
    @property
    def routes_dir(self) -> Path:
        return self.root / "routes"

    @property
    def races_dir(self) -> Path:
        return self.root / "races"

    @property
    def pool_path(self) -> Path:
        return self.root / "pool.json"

    def race_dir(self, race_id: str) -> Path:
        return self.races_dir / race_id

    # ------------------------------------------------------------------
    # Strecken
    # ------------------------------------------------------------------
    def list_routes(self) -> list[dict[str, Any]]:
        """Kurzinfo zu allen Streckendateien, ohne sie voll zu laden."""
        out = []
        for path in sorted(self.routes_dir.glob("*.json.gz")):
            try:
                route = Route.load(path)
            except (ValueError, OSError, KeyError):
                continue
            out.append(
                {
                    "id": path.name.removesuffix(".json.gz"),
                    "name": route.name,
                    "distance_km": round(route.distance_km, 1),
                    "ascent_m": round(route.ascent_m),
                    "distance_class": route.distance_class,
                    "n_climbs": len(route.climbs),
                    "n_splits": len(route.splits),
                }
            )
        return out

    def load_route(self, route_id: str) -> Route:
        path = self.routes_dir / f"{route_id}.json.gz"
        if not path.exists():
            raise FileNotFoundError(f"Strecke '{route_id}' nicht gefunden ({path})")
        return Route.load(path)

    # ------------------------------------------------------------------
    # Fahrerpool
    # ------------------------------------------------------------------
    def save_pool(self, teams: Iterable[Team], riders: Iterable[Rider]) -> Path:
        payload = {
            "teams": [t.to_dict() for t in teams],
            "riders": [r.to_dict() for r in riders],
        }
        self.pool_path.parent.mkdir(parents=True, exist_ok=True)
        self.pool_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), "utf-8")
        return self.pool_path

    def load_pool(self) -> tuple[list[Team], list[Rider]]:
        if not self.pool_path.exists():
            raise FileNotFoundError(
                f"Kein Fahrerpool unter {self.pool_path}. "
                "Erzeugen mit: python -m ultrasim.cli.simulate pool --riders 250"
            )
        data = json.loads(self.pool_path.read_text("utf-8"))
        return (
            [Team.from_dict(t) for t in data["teams"]],
            [Rider.from_dict(r) for r in data["riders"]],
        )

    def pool_exists(self) -> bool:
        return self.pool_path.exists()

    # ------------------------------------------------------------------
    # Rennen
    # ------------------------------------------------------------------
    def save_race(self, race_id: str, route_id: str, result: RaceResult) -> Path:
        target = self.race_dir(race_id)
        target.mkdir(parents=True, exist_ok=True)

        meta = {
            "race_id": race_id,
            "route_id": route_id,
            "route_name": result.route_name,
            "config": _config_to_dict(result.config),
            "compute_seconds": round(result.compute_seconds, 3),
            "entries": [e.to_dict() for e in result.entries],
            "riders": [r.to_dict() for r in result.riders],
            "teams": [t.to_dict() for t in result.teams],
            "events": [e.to_dict() for e in result.events],
            "plans": [_plan_to_dict(p) for p in result.plans],
        }
        (target / "race.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")

        np.savez_compressed(
            target / "telemetry.npz",
            sample_dt_s=np.int32(result.telemetry.sample_dt_s),
            dist_m=result.telemetry.dist_m,
            v_cms=result.telemetry.v_cms,
            power_w=result.telemetry.power_w,
            form_pct=result.telemetry.form_pct,
            wprime_pct=result.telemetry.wprime_pct,
            bike=result.telemetry.bike,
            state=result.telemetry.state,
            split_times_s=result.split_times_s.astype(np.float32),
            split_ranks=result.split_ranks,
        )
        return target

    def load_race(self, race_id: str) -> tuple[RaceResult, str]:
        target = self.race_dir(race_id)
        meta_path = target / "race.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Rennen '{race_id}' nicht gefunden ({meta_path})")
        meta = json.loads(meta_path.read_text("utf-8"))

        with np.load(target / "telemetry.npz") as data:
            telemetry = Telemetry(
                sample_dt_s=int(data["sample_dt_s"]),
                dist_m=data["dist_m"],
                v_cms=data["v_cms"],
                power_w=data["power_w"],
                form_pct=data["form_pct"],
                wprime_pct=data["wprime_pct"],
                bike=data["bike"],
                state=data["state"],
            )
            split_times = data["split_times_s"].astype(np.float64)
            split_ranks = data["split_ranks"]

        result = RaceResult(
            config=_config_from_dict(meta["config"]),
            route_name=meta["route_name"],
            entries=[RaceEntry(**e) for e in meta["entries"]],
            riders=[Rider.from_dict(r) for r in meta["riders"]],
            teams=[Team.from_dict(t) for t in meta["teams"]],
            split_times_s=split_times,
            split_ranks=split_ranks,
            telemetry=telemetry,
            events=[RaceEvent(**e) for e in meta["events"]],
            plans=[_plan_from_dict(p) for p in meta["plans"]],
            compute_seconds=meta.get("compute_seconds", 0.0),
        )
        return result, meta["route_id"]

    def list_races(self) -> list[dict[str, Any]]:
        out = []
        if not self.races_dir.exists():
            return out
        for path in sorted(self.races_dir.iterdir()):
            meta_path = path / "race.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            finish = [
                e["finish_time_s"] for e in meta["entries"] if e.get("finish_time_s") is not None
            ]
            out.append(
                {
                    "race_id": meta["race_id"],
                    "route_id": meta["route_id"],
                    "route_name": meta["route_name"],
                    "name": meta["config"].get("name", meta["race_id"]),
                    "seed": meta["config"].get("seed"),
                    "n_entries": len(meta["entries"]),
                    "winner_time_s": min(finish) if finish else None,
                }
            )
        return out

    def delete_race(self, race_id: str) -> None:
        target = self.race_dir(race_id)
        if target.exists():
            shutil.rmtree(target)


# ----------------------------------------------------------------------
# (De-)Serialisierung der Hilfsobjekte
# ----------------------------------------------------------------------
def _config_to_dict(config: RaceConfig) -> dict[str, Any]:
    data = asdict(config)
    data["race_date"] = config.race_date.isoformat() if config.race_date else None
    return data


def _config_from_dict(data: dict[str, Any]) -> RaceConfig:
    data = dict(data)
    raw_date = data.pop("race_date", None)
    config = RaceConfig(**data)
    config.race_date = date.fromisoformat(raw_date) if raw_date else None
    return config


def _plan_to_dict(plan: RacePlan) -> dict[str, Any]:
    return {
        "rider_id": plan.rider_id,
        "target_if": round(plan.target_if, 4),
        "climb_boost": round(plan.climb_boost, 4),
        "sections": [asdict(s) for s in plan.sections],
        "notes": [[round(d, 1), note] for d, note in plan.notes],
    }


def _plan_from_dict(data: dict[str, Any]) -> RacePlan:
    return RacePlan(
        rider_id=data["rider_id"],
        target_if=data["target_if"],
        climb_boost=data["climb_boost"],
        sections=[SectionPlan(**s) for s in data["sections"]],
        notes=[(d, note) for d, note in data["notes"]],
    )
