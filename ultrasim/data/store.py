"""Persistenz (Game-Design-Dokument, Abschnitt 12).

Zwei Speicherformen, weil die Daten zwei sehr verschiedene Größen haben:

* **Stammdaten** (Teams, Fahrer, Rennen, Splitzeiten, Ereignisse) sind
  klein und werden als JSON abgelegt.
* **Telemetrie** ist die einzige Struktur, die groß wird. Sie liegt als
  ``.npz`` je Rennen: ein Array der Form ``(n_fahrer, n_samples,
  n_kanäle)``, aus dem der Playback-Server in Millisekunden ein
  Zeitfenster über alle Fahrer schneidet.

Abweichung vom Dokument, bewusst und benannt: Abschnitt 13 sieht für die
Stammdaten SQLAlchemy + SQLite vor. Auch mit Saison und Kalender bleibt
es bei Dateien: Eine Saison ist eine Liste von zwanzig Terminen, keine
Tabelle mit Millionen Zeilen, und die einzige Verknüpfung ist der
Rennschlüssel. Dafür eine Datenbank aufzumachen kostet Startzeit und
Bundle-Größe, ohne eine einzige Abfrage zu vereinfachen. Die Zugriffe
laufen deshalb über dieses Repository-Modul und nicht verstreut über die
Anwendung, damit der Wechsel auf SQLAlchemy ein einzelner Austausch
bleibt, falls er je nötig wird.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from ..core.career import Career
from ..core.conditions import ConditionRecord
from ..core.engine import RaceConfig, RaceEntry, RaceResult, Telemetry
from ..core.events import RaceEvent
from ..core.rider import Rider, Team
from ..core.season import Season
from ..core.strategy import Misjudgement, RacePlan, SectionPlan, StopPlan
from ..core.weather import WeatherProfile
from ..geo.route import Route

DEFAULT_ROOT = Path("data")


@dataclass
class RaceSummary:
    """Ein Rennergebnis ohne Telemetrie.

    Genug für Ergebnisliste, Punkte und Gesamtwertung — und um zwei
    Größenordnungen billiger zu laden als das volle Rennen.
    """

    race_id: str
    route_id: str
    route_name: str
    name: str
    entries: list[RaceEntry]
    riders: list[Rider]
    teams: list[Team]
    weather: WeatherProfile

    @property
    def winner_time_s(self) -> float | None:
        times = [e.finish_time_s for e in self.entries if e.finish_time_s is not None]
        return min(times) if times else None


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
    def save_race(
        self, race_id: str, route_id: str, result: RaceResult, route: Route | None = None
    ) -> Path:
        target = self.race_dir(race_id)
        target.mkdir(parents=True, exist_ok=True)

        # Momentaufnahme der Strecke ins Rennverzeichnis. Die Splitzeiten
        # gehören zu *diesen* Splits: Verschiebt der Streckeneditor später
        # einen Zeitmesspunkt von km 40 auf km 45, stünde sonst die Zeit
        # von km 40 unter dem Namen "km 45", und beim Hinzufügen oder
        # Löschen passte nicht einmal mehr die Spaltenzahl. 150 kB neben
        # zweistelligen Megabyte Telemetrie sind der Preis dafür, dass ein
        # gerechnetes Rennen unveränderlich bleibt.
        if route is not None:
            route.save(target / "route.json.gz")

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
            "conditions": [c.to_dict() for c in result.conditions],
            "weather": result.weather.to_dict(),
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
            glyco_pct=result.telemetry.glyco_pct,
            sleep_pct=result.telemetry.sleep_pct,
            hydration_pct=result.telemetry.hydration_pct,
            bike=result.telemetry.bike,
            state=result.telemetry.state,
            split_times_s=result.split_times_s.astype(np.float32),
            split_ranks=result.split_ranks,
        )
        return target

    def race_route(self, race_id: str, route_id: str) -> Route:
        """Die Strecke, auf der ein Rennen gefahren wurde.

        Bevorzugt die Momentaufnahme im Rennverzeichnis. Rennen aus der
        Zeit vor dem Streckeneditor haben keine und greifen auf die
        Streckendatei zurück — solange sie unverändert ist, macht das
        keinen Unterschied, und wenn nicht, ist es das Beste, was noch
        geht.
        """
        snapshot = self.race_dir(race_id) / "route.json.gz"
        if snapshot.exists():
            return Route.load(snapshot)
        return self.load_route(route_id)

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
                glyco_pct=data["glyco_pct"],
                sleep_pct=data["sleep_pct"],
                hydration_pct=data["hydration_pct"],
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
            conditions=[ConditionRecord(**c) for c in meta.get("conditions", [])],
            weather=WeatherProfile.from_dict(meta.get("weather", {})),
            compute_seconds=meta.get("compute_seconds", 0.0),
        )
        return result, meta["route_id"]

    def load_race_summary(self, race_id: str) -> RaceSummary:
        """Ergebnisdaten ohne Telemetrie.

        Die Gesamtwertung einer Saison braucht von zwanzig Rennen nur die
        Ergebnislisten. Sie über ``load_race`` zu holen hieße, zwanzigmal
        zweistellige Megabyte Telemetrie zu entpacken, um zweihundert
        Zeilen zu addieren.
        """
        meta_path = self.race_dir(race_id) / "race.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Rennen '{race_id}' nicht gefunden ({meta_path})")
        meta = json.loads(meta_path.read_text("utf-8"))
        return RaceSummary(
            race_id=meta["race_id"],
            route_id=meta["route_id"],
            route_name=meta["route_name"],
            name=meta["config"].get("name", meta["race_id"]),
            entries=[RaceEntry(**e) for e in meta["entries"]],
            riders=[Rider.from_dict(r) for r in meta["riders"]],
            teams=[Team.from_dict(t) for t in meta["teams"]],
            weather=WeatherProfile.from_dict(meta.get("weather", {})),
        )

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

    # ------------------------------------------------------------------
    # Saisons (Abschnitt 14, M7)
    # ------------------------------------------------------------------
    @property
    def seasons_dir(self) -> Path:
        return self.root / "seasons"

    def season_path(self, season_id: str) -> Path:
        return self.seasons_dir / f"{season_id}.json"

    def save_season(self, season: Season) -> Path:
        self.seasons_dir.mkdir(parents=True, exist_ok=True)
        path = self.season_path(season.id)
        path.write_text(json.dumps(season.to_dict(), ensure_ascii=False, indent=1), "utf-8")
        return path

    def load_season(self, season_id: str) -> Season:
        path = self.season_path(season_id)
        if not path.exists():
            raise FileNotFoundError(f"Saison '{season_id}' nicht gefunden ({path})")
        return Season.from_dict(json.loads(path.read_text("utf-8")))

    def list_seasons(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.seasons_dir.exists():
            return out
        for path in sorted(self.seasons_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            races = data.get("races", [])
            out.append(
                {
                    "id": data["id"],
                    "name": data["name"],
                    "year": data["year"],
                    "n_races": len(races),
                    "n_computed": sum(1 for r in races if r.get("race_id")),
                }
            )
        return sorted(out, key=lambda s: (-s["year"], s["name"]))

    def delete_season(self, season_id: str) -> None:
        path = self.season_path(season_id)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Karrieren (mehrere Saisons in Folge)
    # ------------------------------------------------------------------
    @property
    def careers_dir(self) -> Path:
        return self.root / "careers"

    def career_path(self, career_id: str) -> Path:
        return self.careers_dir / f"{career_id}.json"

    def save_career(self, career: Career) -> Path:
        self.careers_dir.mkdir(parents=True, exist_ok=True)
        path = self.career_path(career.id)
        path.write_text(json.dumps(career.to_dict(), ensure_ascii=False, indent=1), "utf-8")
        return path

    def load_career(self, career_id: str) -> Career:
        path = self.career_path(career_id)
        if not path.exists():
            raise FileNotFoundError(f"Karriere '{career_id}' nicht gefunden ({path})")
        return Career.from_dict(json.loads(path.read_text("utf-8")))

    def list_careers(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.careers_dir.exists():
            return out
        for path in sorted(self.careers_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            chapters = data.get("chapters", [])
            last = chapters[-1] if chapters else None
            champion = (last or {}).get("standings") or []
            out.append(
                {
                    "id": data["id"],
                    "name": data["name"],
                    "first_year": data["first_year"],
                    "n_seasons": len(data.get("season_ids", [])),
                    "years_closed": len(chapters),
                    "last_champion": champion[0]["name"] if champion else None,
                }
            )
        return sorted(out, key=lambda c: (-c["first_year"], c["name"]))

    def delete_career(self, career_id: str) -> None:
        path = self.career_path(career_id)
        if path.exists():
            path.unlink()


# ----------------------------------------------------------------------
# (De-)Serialisierung der Hilfsobjekte
# ----------------------------------------------------------------------
def _config_to_dict(config: RaceConfig) -> dict[str, Any]:
    data = asdict(config)
    data["race_date"] = config.race_date.isoformat() if config.race_date else None
    # JSON kennt nur Zeichenketten als Schlüssel; die Fahrer-IDs kommen
    # beim Laden wieder als int zurück.
    data["carry_work_kj"] = {
        str(k): round(v, 2) for k, v in (config.carry_work_kj or {}).items()
    }
    return data


def _config_from_dict(data: dict[str, Any]) -> RaceConfig:
    data = dict(data)
    raw_date = data.pop("race_date", None)
    carry = data.pop("carry_work_kj", None) or {}
    config = RaceConfig(**data)
    config.race_date = date.fromisoformat(raw_date) if raw_date else None
    config.carry_work_kj = {int(k): float(v) for k, v in carry.items()}
    return config


def _plan_to_dict(plan: RacePlan) -> dict[str, Any]:
    return {
        "rider_id": plan.rider_id,
        "target_if": round(plan.target_if, 4),
        "climb_boost": round(plan.climb_boost, 4),
        "sections": [asdict(s) for s in plan.sections],
        "notes": [[round(d, 1), note] for d, note in plan.notes],
        "misjudgement": asdict(plan.misjudgement) if plan.misjudgement else None,
        "intake_g_h": round(plan.intake_g_h, 2),
        "stops": [asdict(s) for s in plan.stops],
        "est_ride_time_s": round(plan.est_ride_time_s, 1),
    }


def _plan_from_dict(data: dict[str, Any]) -> RacePlan:
    return RacePlan(
        rider_id=data["rider_id"],
        target_if=data["target_if"],
        climb_boost=data["climb_boost"],
        sections=[SectionPlan(**s) for s in data["sections"]],
        notes=[(d, note) for d, note in data["notes"]],
        misjudgement=(
            Misjudgement(**data["misjudgement"]) if data.get("misjudgement") else None
        ),
        intake_g_h=data.get("intake_g_h", 0.0),
        stops=[StopPlan(**s) for s in data.get("stops", [])],
        est_ride_time_s=data.get("est_ride_time_s", 0.0),
    )
