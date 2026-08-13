"""Rennsimulation (Game-Design-Dokument, Abschnitt 8).

Die Simulation ist eine reine Bibliothek ohne Web-Abhängigkeit: aus
einer Renn-Konfiguration entsteht ein Ergebnis samt Event-Strom und
Telemetriearray. Web-App und CLI sind nur zwei Konsumenten davon.

Zwei Bauentscheidungen prägen den Code:

**Vektorisierung über die Fahrer.** Die Schleifenlänge ist die
Tick-Anzahl, nicht die Fahrerzahl. Ein Array mit 250 Elementen zu
verrechnen kostet praktisch dasselbe wie eines mit 41 – der
NumPy-Overhead pro Operation dominiert.

**Fahrer-Eigenzeit.** Jeder Fahrer wird ab seinem eigenen ``t = 0``
gerechnet. Bei einem Einzelzeitfahren ohne Windschatten hängt kein
Fahrer vom Zustand eines anderen ab, also ist das exakt äquivalent zu
einer gemeinsamen Wanduhr – nur einfacher, schneller und frei von der
Tageszeit-Lotterie, die ein 125-Stunden-Startfenster sonst erzeugt.
Die absolute Startzeit kommt erst beim Playback dazu.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from ..geo.route import Route
from . import conditions as cond
from . import fatigue as fat
from . import form as fm
from . import physics as ph
from . import strategy as st
from .events import (
    BIKE_CHANGE,
    CONDITION_END,
    CONDITION_START,
    DNF,
    FINISH,
    PLAN,
    SPLIT_PASSED,
    START,
    STOP_END,
    STOP_START,
    RaceEvent,
)
from .rider import Rider, Team, season_form

#: Telemetrie-Abtastung nach Distanzklasse (Abschnitt 12).
SAMPLE_DT_S: dict[str, int] = {"kurz": 5, "mittel": 15, "ultra": 30}

#: Startintervall nach Distanzklasse (Abschnitt 8.1.1).
START_INTERVAL_S: dict[str, int] = {"kurz": 300, "mittel": 900, "ultra": 1800}

STATE_RIDING = 0
STATE_STOPPED = 1
STATE_FINISHED = 2
STATE_DNF = 3


@dataclass
class RaceConfig:
    """Alles, was ein Rennen reproduzierbar festlegt."""

    seed: int = 1
    #: Fahrer-Eigenzeit des Starts als Sekunden nach Mitternacht. Jeder
    #: Fahrer startet in seinem persönlichen "08:00" (Entscheidung 13).
    start_time_of_day_s: int = 8 * 3600
    start_interval_s: int | None = None
    start_order: str = "seeded"  # seeded | random | list
    dt_s: float = 1.0
    sample_dt_s: int | None = None
    #: Harte Obergrenze der Simulationsdauer je Fahrer.
    max_hours: float | None = None
    #: Zeitlimit als Vielfaches der Siegerzeit (Abschnitt 15, offener Punkt).
    time_limit_factor: float = 1.4
    #: Zeitfahrrad überhaupt zulassen.
    allow_tt_bike: bool = True
    race_date: date | None = None
    name: str = "Rennen"

    def resolved_sample_dt(self, distance_class: str) -> int:
        return self.sample_dt_s or SAMPLE_DT_S.get(distance_class, 15)

    def resolved_start_interval(self, distance_class: str) -> int:
        if self.start_interval_s is not None:
            return self.start_interval_s
        return START_INTERVAL_S.get(distance_class, 900)


@dataclass
class RaceEntry:
    """Ein Starter."""

    entry_id: int
    rider_id: int
    bib: int
    start_offset_s: float
    season_form: float
    day_form: float
    target_if: float
    finish_time_s: float | None = None
    rank: int | None = None
    status: str = "RUN"  # RUN | FIN | DNF | OTL
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "rider_id": self.rider_id,
            "bib": self.bib,
            "start_offset_s": self.start_offset_s,
            "season_form": round(self.season_form, 4),
            "day_form": round(self.day_form, 4),
            "target_if": round(self.target_if, 4),
            "finish_time_s": None if self.finish_time_s is None else round(self.finish_time_s, 2),
            "rank": self.rank,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class Telemetry:
    """Quantisierte Verlaufsdaten, Form ``(n_entries, n_samples)``.

    Nicht gespeichert wird lat/lon/ele – die Position ist eindeutig durch
    ``dist`` und die Routengeometrie bestimmt und wird bei der Anzeige
    interpoliert. Das spart drei von zehn Kanälen.
    """

    sample_dt_s: int
    dist_m: np.ndarray  # int32
    v_cms: np.ndarray  # int16 (cm/s)
    power_w: np.ndarray  # int16
    form_pct: np.ndarray  # uint8, FTP_eff / FTP_basis in Prozent
    wprime_pct: np.ndarray  # uint8
    bike: np.ndarray  # uint8
    state: np.ndarray  # uint8

    @property
    def n_entries(self) -> int:
        return int(self.dist_m.shape[0])

    @property
    def n_samples(self) -> int:
        return int(self.dist_m.shape[1])

    def nbytes(self) -> int:
        return sum(
            getattr(self, name).nbytes
            for name in ("dist_m", "v_cms", "power_w", "form_pct", "wprime_pct", "bike", "state")
        )

    def save(self, path) -> None:
        np.savez_compressed(
            path,
            sample_dt_s=np.int32(self.sample_dt_s),
            dist_m=self.dist_m,
            v_cms=self.v_cms,
            power_w=self.power_w,
            form_pct=self.form_pct,
            wprime_pct=self.wprime_pct,
            bike=self.bike,
            state=self.state,
        )

    @classmethod
    def load(cls, path) -> Telemetry:
        with np.load(path) as data:
            return cls(
                sample_dt_s=int(data["sample_dt_s"]),
                dist_m=data["dist_m"],
                v_cms=data["v_cms"],
                power_w=data["power_w"],
                form_pct=data["form_pct"],
                wprime_pct=data["wprime_pct"],
                bike=data["bike"],
                state=data["state"],
            )


@dataclass
class RaceResult:
    """Vollständiges Rennergebnis."""

    config: RaceConfig
    route_name: str
    entries: list[RaceEntry]
    riders: list[Rider]
    teams: list[Team]
    split_times_s: np.ndarray  # (n_entries, n_splits), NaN = nicht erreicht
    split_ranks: np.ndarray  # (n_entries, n_splits), 0 = nicht erreicht
    telemetry: Telemetry
    events: list[RaceEvent]
    plans: list[st.RacePlan]
    conditions: list[cond.ConditionRecord] = field(default_factory=list)
    compute_seconds: float = 0.0

    def conditions_for(self, entry_id: int) -> list[cond.ConditionRecord]:
        return [c for c in self.conditions if c.entry_id == entry_id]

    @property
    def winner_time_s(self) -> float | None:
        times = [e.finish_time_s for e in self.entries if e.finish_time_s is not None]
        return min(times) if times else None

    def entry_by_rider(self, rider_id: int) -> RaceEntry | None:
        for entry in self.entries:
            if entry.rider_id == rider_id:
                return entry
        return None

    def events_for(self, entry_id: int) -> list[RaceEvent]:
        return [e for e in self.events if e.entry_id == entry_id]

    @property
    def last_finish_wallclock_s(self) -> float:
        """Wanduhrzeit, zu der der letzte Fahrer im Ziel ist."""
        out = 0.0
        for entry in self.entries:
            end = entry.finish_time_s if entry.finish_time_s is not None else 0.0
            out = max(out, entry.start_offset_s + end)
        return out


# ----------------------------------------------------------------------
# Startaufstellung
# ----------------------------------------------------------------------
def build_start_list(
    riders: Sequence[Rider], config: RaceConfig, interval_s: float, rng: np.random.Generator
) -> list[tuple[Rider, int, float]]:
    """Startreihenfolge und Startzeit-Offsets.

    Beim Einzelzeitfahren startet der Favorit zuletzt – so wächst die
    Spannung mit der Startliste statt sie zu verbrauchen.
    """
    order = list(riders)
    if config.start_order == "seeded":
        order.sort(key=lambda r: r.potential)  # stärkster Fahrer zuletzt
    elif config.start_order == "random":
        idx = rng.permutation(len(order))
        order = [order[i] for i in idx]
    return [(rider, i + 1, i * interval_s) for i, rider in enumerate(order)]


class RiderStreams:
    """Unabhängige Zufallsströme je Fahrer und Zweck.

    Über ``SeedSequence`` mit ``spawn_key`` hängt ein Strom nur an Seed,
    Fahrer-ID und Zweck – nicht an der Position in der Startliste und
    nicht daran, wie viele Zufallszahlen ein *anderer* Zweck vorher
    gezogen hat.

    Warum das zweite so wichtig ist: Mit einem gemeinsamen Strom je
    Fahrer verschiebt jede neue Mechanik, die irgendwo würfelt, sämtliche
    Ziehungen dahinter. Beim Einbau der Fehlplanung wurde dadurch ein
    Fahrer *schneller*, obwohl nur ein Malus dazukam – die Tagesform war
    verrutscht. Mit getrennten Strömen ändert eine neue Mechanik nur das,
    was sie selbst betrifft, und der Golden-Master bleibt aussagekräftig.

    ``NAMES`` darf hinten wachsen; bestehende Einträge dürfen weder ihre
    Position noch ihren Namen ändern.
    """

    NAMES: tuple[str, ...] = (
        "plan",
        "misjudge",
        "day_form",
        "section_form",
        "stops",
        # ab M5 reserviert – die Namen jetzt festzulegen kostet nichts
        # und macht spätere Ergänzungen rückwirkungsfrei
        "nutrition",
        "sleep",
        "incident",
        "weather",
    )

    def __init__(self, seed: int, rider_id: int) -> None:
        self.seed = seed
        self.rider_id = rider_id
        self._cache: dict[str, np.random.Generator] = {}

    def get(self, name: str) -> np.random.Generator:
        if name not in self._cache:
            try:
                stream = self.NAMES.index(name)
            except ValueError:  # pragma: no cover - Programmierfehler
                raise KeyError(f"Unbekannter Zufallsstrom: {name}") from None
            self._cache[name] = np.random.default_rng(
                np.random.SeedSequence(self.seed, spawn_key=(self.rider_id, stream))
            )
        return self._cache[name]


# ----------------------------------------------------------------------
# Simulation
# ----------------------------------------------------------------------
def simulate_race(
    route: Route,
    riders: Sequence[Rider],
    teams: Iterable[Team],
    config: RaceConfig | None = None,
    progress: Any = None,
) -> RaceResult:
    """Rechnet ein komplettes Rennen durch."""
    t_start = time.perf_counter()
    config = config or RaceConfig()
    riders = list(riders)
    team_map = {t.id: t for t in teams}
    if not riders:
        raise ValueError("Startfeld ist leer")

    dist_class = route.distance_class
    interval = config.resolved_start_interval(dist_class)
    sample_dt = config.resolved_sample_dt(dist_class)
    dt = float(config.dt_s)
    rng_global = np.random.default_rng(config.seed)

    start_list = build_start_list(riders, config, interval, rng_global)
    n = len(start_list)
    field_riders = [r for r, _, _ in start_list]
    streams = [RiderStreams(config.seed, r.id) for r in field_riders]

    day_of_year = (config.race_date or date(2026, 6, 21)).timetuple().tm_yday

    # ---------------- Rennpläne (Strategiemodul, Stufe 1) ------------
    plans: list[st.RacePlan] = []
    events: list[RaceEvent] = []
    for entry_id, (rider, _, _) in enumerate(start_list):
        team = team_map.get(rider.team_id)
        service_factor = team.service_factor if team else 1.0
        plan = st.build_plan(
            rider,
            route,
            streams[entry_id].get("plan"),
            streams[entry_id].get("misjudge"),
            service_factor,
            config.allow_tt_bike,
        )
        plans.append(plan)
        for _, note in plan.notes:
            events.append(RaceEvent(entry_id, 0.0, PLAN, {"note": note}))
        events.append(RaceEvent(entry_id, 0.0, START, {"bib": start_list[entry_id][1]}))

    # ---------------- Feldarrays -------------------------------------
    weight = np.array([r.weight_kg for r in field_riders])
    ftp = np.array([r.ftp_w for r in field_riders])
    frontal = np.array([r.frontal_area_m2 for r in field_riders])
    flat_norm = np.array([r.attr_norm("flach") for r in field_riders])
    boost = np.array([p.climb_boost for p in plans])
    target_if = np.array([p.target_if for p in plans])
    skill_norm = np.array([r.attr_norm("abfahrtstechnik") for r in field_riders])
    risk_norm = np.array([r.attr_norm("risikobereitschaft") for r in field_riders])
    service_factor = np.array(
        [
            team_map[r.team_id].service_factor if r.team_id in team_map else 1.0
            for r in field_riders
        ]
    )

    f_season = np.array([season_form(r, day_of_year) for r in field_riders])
    f_day = fm.draw_day_form(field_riders, [s.get("day_form") for s in streams])
    section_track, section_grid = fm.build_section_form(
        n, route.distance_m, [s.get("section_form") for s in streams]
    )

    wprime_cap = fat.w_prime_capacity(
        np.array([r.attr("spritzigkeit") for r in field_riders]), weight
    )
    work_cap_kj = fat.work_capacity_kj(
        np.array([r.attr("ausdauer") for r in field_riders]),
        np.array([r.attr("regeneration") for r in field_riders]),
        weight,
    )

    # ---------------- Streckenarrays (einmal, nicht pro Tick) --------
    grade_pt = route.grade
    seg_idx_pt = route.segment_index_array()
    crr_seg = np.array([ph.CRR.get(s.surface, ph.CRR["asphalt_good"]) for s in route.segments])
    curv_seg = np.array([max(s.curviness, 1.0) for s in route.segments])
    crr_pt = crr_seg[seg_idx_pt] if len(crr_seg) else np.full(route.n_points, ph.CRR["asphalt_good"])
    curv_pt = curv_seg[seg_idx_pt] if len(curv_seg) else np.full(route.n_points, 1.0)
    # Kurvenlimit ohne Fahreranteil vorrechnen: sqrt(µ·g·r) hängt nur an
    # der Strecke, der Fahreranteil ist ein Faktor.
    radius_pt = np.clip(57296.0 / curv_pt, 8.0, 4000.0)
    vcorner_pt = np.sqrt(ph.MU_DRY * ph.G * radius_pt)
    corner_skill = 1.0 + 0.12 * skill_norm + 0.08 * risk_norm
    rho_pt = ph.air_density(route.ele_m)
    # Steigungstrigonometrie und Rampenanteil hängen nur an der Strecke.
    cos_pt, sin_pt = ph.slope_trig(grade_pt)
    ramp_pt = np.clip(grade_pt, 0.0, st.CLIMB_BOOST_REF_GRADE) / st.CLIMB_BOOST_REF_GRADE
    steep_pt = grade_pt > 0.06

    # ---------------- Splits und Servicepunkte -----------------------
    split_dist = np.array([s.dist_m for s in route.splits], dtype=np.float64)
    n_splits = split_dist.size
    split_guard = np.append(split_dist, np.inf)
    sp_dist = np.array([s.dist_m for s in route.service_points], dtype=np.float64)
    sp_guard = np.append(sp_dist, np.inf)

    n_sections = max(len(sp_dist) + 1, 1)
    planned_bike = np.zeros((n, n_sections), dtype=np.int8)
    for i, plan in enumerate(plans):
        for section in plan.sections:
            if section.idx < n_sections:
                planned_bike[i, section.idx] = section.bike

    # ---------------- Zustände (Abschnitt 6.5) -----------------------
    conditions = cond.ConditionStore(n)
    cond_mods = np.ones((n, len(cond.CHANNELS)))
    # Distanzmarke, an der eine Fehlplanung zuschlägt; inf = geht auf.
    misjudge_at = np.array(
        [p.misjudgement.dist_m if p.misjudgement else np.inf for p in plans]
    )

    # ---------------- Zustand ----------------------------------------
    dist = np.zeros(n)
    v = np.full(n, 4.0)
    work_j = np.zeros(n)
    wprime = wprime_cap.copy()
    bike = planned_bike[:, 0].astype(np.int64)
    stop_left = np.zeros(n)
    state = np.zeros(n, dtype=np.uint8)
    finish_t = np.full(n, np.nan)
    next_split = np.zeros(n, dtype=np.int64)
    next_sp = np.zeros(n, dtype=np.int64)

    bike_mass = np.array([ph.BIKES[name]["mass_kg"] for name in ph.BIKE_NAMES])
    bike_cda_f = np.array([ph.BIKES[name]["cda_factor"] for name in ph.BIKE_NAMES])
    bike_steep = np.array([ph.BIKES[name]["steep_penalty"] for name in ph.BIKE_NAMES])

    split_times = np.full((n, n_splits), np.nan)

    max_hours = config.max_hours or max(3.0, route.distance_km / 11.0)
    max_ticks = int(max_hours * 3600.0 / dt)
    sample_steps = max(1, int(round(sample_dt / dt)))

    # Telemetriepuffer wächst bei Bedarf – eine harte Vorabreservierung
    # nach ``max_hours`` wäre bei 2500 km und 250 Fahrern reine
    # Speicherverschwendung, weil das Feld weit vorher im Ziel ist.
    cap = min(max_ticks // sample_steps + 2, 4096)
    buf_dist = np.zeros((n, cap), dtype=np.int32)
    buf_v = np.zeros((n, cap), dtype=np.int16)
    buf_p = np.zeros((n, cap), dtype=np.int16)
    buf_form = np.zeros((n, cap), dtype=np.uint8)
    buf_wp = np.zeros((n, cap), dtype=np.uint8)
    buf_bike = np.zeros((n, cap), dtype=np.uint8)
    buf_state = np.zeros((n, cap), dtype=np.uint8)
    n_samples = 0

    def _grow() -> None:
        # Bewusst nicht np.resize: das tilt die Daten in flacher
        # Reihenfolge und würde die Zeilen gegeneinander verschieben.
        nonlocal cap, buf_dist, buf_v, buf_p, buf_form, buf_wp, buf_bike, buf_state
        new_cap = cap * 2
        grown = []
        for buf in (buf_dist, buf_v, buf_p, buf_form, buf_wp, buf_bike, buf_state):
            bigger = np.zeros((n, new_cap), dtype=buf.dtype)
            bigger[:, :cap] = buf
            grown.append(bigger)
        buf_dist, buf_v, buf_p, buf_form, buf_wp, buf_bike, buf_state = grown
        cap = new_cap

    def _record() -> None:
        nonlocal n_samples
        if n_samples >= cap:
            _grow()
        buf_dist[:, n_samples] = np.minimum(dist, total_distance).astype(np.int32)
        buf_v[:, n_samples] = np.clip(v * 100.0, 0, 32000).astype(np.int16)
        buf_p[:, n_samples] = np.clip(power_now, 0, 32000).astype(np.int16)
        buf_form[:, n_samples] = np.clip(form_now * 100.0, 0, 255).astype(np.uint8)
        buf_wp[:, n_samples] = np.clip(wprime / wprime_cap * 100.0, 0, 255).astype(np.uint8)
        buf_bike[:, n_samples] = bike.astype(np.uint8)
        buf_state[:, n_samples] = state
        n_samples += 1

    total_distance = route.distance_m
    power_now = np.zeros(n)
    form_now = np.ones(n)
    ftp_eff = ftp.copy()
    ftp_eff_if = ftp * target_if
    descent_mod = np.ones(n)
    crr_mod = np.ones(n)
    #: Takt der langsam veränderlichen Größen (Form, Ermüdung) in Ticks.
    slow_steps = max(1, int(round(10.0 / dt)))

    t = 0.0
    for tick in range(max_ticks + 1):
        running = state == STATE_RIDING
        stopped = state == STATE_STOPPED

        # --- Stopps abarbeiten ---------------------------------------
        if stopped.any():
            stop_left[stopped] -= dt
            done = stopped & (stop_left <= 0.0)
            if done.any():
                state[done] = STATE_RIDING
                stop_left[done] = 0.0
                v[done] = 0.5
                for i in np.flatnonzero(done):
                    events.append(
                        RaceEvent(int(i), t, STOP_END, {"dist_km": round(dist[i] / 1000.0, 2)})
                    )
            power_now[stopped] = 0.0
            v[stopped] = 0.0

        if not running.any() and not stopped.any():
            break

        # --- Telemetrie ----------------------------------------------
        if tick % sample_steps == 0:
            _record()

        if running.any():
            idx = np.clip((dist / route.raster_m).astype(np.int64), 0, route.n_points - 1)
            grade = grade_pt[idx]

            # --- Form und haltbare Leistung --------------------------
            # Abschnittsform und Langzeitermüdung ändern sich über
            # Stunden, nicht über Sekunden. Sie jeden Tick neu zu rechnen
            # (inklusive einer Potenz mit gebrochenem Exponenten) kostet
            # spürbar Rechenzeit und ändert am Ergebnis nichts – deshalb
            # laufen sie im langsamen Takt.
            if tick % slow_steps == 0:
                for record in conditions.expire(t, dist):
                    events.append(
                        RaceEvent(
                            record.entry_id,
                            t,
                            CONDITION_END,
                            {
                                "typ": record.typ,
                                "label": record.label,
                                "dist_km": round(dist[record.entry_id] / 1000.0, 2),
                            },
                        )
                    )
                cond_mods = conditions.update(t, dist)
                f_section = fm.section_form_at(section_track, dist, section_grid)
                f_fat = fat.fatigue_factor(work_j / 1000.0, work_cap_kj)
                # f_umwelt ist das Produkt aller aktiven Zustände
                # (Abschnitt 6.5); Wetter kommt mit M6 in denselben Kanal.
                f_umwelt = cond.channel(cond_mods, "ftp")
                form_now = f_season * f_day * f_section * f_fat * f_umwelt
                ftp_eff = ftp * form_now
                ftp_eff_if = ftp_eff * target_if
                descent_mod = cond.channel(cond_mods, "abfahrtstempo")
                crr_mod = cond.channel(cond_mods, "crr")

            p_target = ftp_eff_if * (1.0 + ramp_pt[idx] * boost)
            p_target = p_target * (1.0 - bike_steep[bike] * steep_pt[idx])

            # W'-Wächter: bei leerem Tank wird an Rampen nicht mehr
            # überzogen (Regelkreis aus Abschnitt 7.2).
            guard = wprime < fat.W_PRIME_GUARD * wprime_cap
            p_target = np.where(guard, np.minimum(p_target, ftp_eff), p_target)
            p_eff = p_target * ph.downhill_power_taper(v)

            # --- Physik ----------------------------------------------
            mass = weight + bike_mass[bike] + ph.SUPPORTED_LUGGAGE_KG
            cda = ph.cda_for(frontal, ph.position_k(grade, flat_norm), bike_cda_f[bike])
            v_limit = np.minimum(vcorner_pt[idx] * corner_skill * descent_mod, ph.MAX_SPEED)

            v_new = ph.integrate_step(
                v,
                p_eff,
                grade,
                mass,
                cda,
                crr_pt[idx] * crr_mod,
                rho_pt[idx],
                dt,
                v_limit=v_limit,
                cos_slope=cos_pt[idx],
                sin_slope=sin_pt[idx],
            )
            dist_new = dist + v_new * dt

            wprime_new = fat.w_prime_step(wprime, wprime_cap, p_eff, ftp_eff, dt)

            dist_prev = dist.copy()
            v = np.where(running, v_new, v)
            dist = np.where(running, dist_new, dist)
            wprime = np.where(running, wprime_new, wprime)
            work_j = np.where(running, work_j + p_eff * dt, work_j)
            power_now = np.where(running, p_eff, 0.0)

            t_next = t + dt

            # --- Splits ----------------------------------------------
            # Mehrfachdurchgänge in einem Tick sind bei 1 s und >= 10 km
            # Abstand unmöglich, die Schleife ist reine Absicherung für
            # exotische Konfigurationen.
            for _ in range(4):
                crossing = running & (dist >= split_guard[next_split])
                if not crossing.any():
                    break
                for i in np.flatnonzero(crossing):
                    s = int(next_split[i])
                    moved = dist[i] - dist_prev[i]
                    frac = (split_dist[s] - dist_prev[i]) / moved if moved > 1e-9 else 0.0
                    t_cross = t + frac * dt
                    split_times[i, s] = t_cross
                    events.append(
                        RaceEvent(
                            int(i),
                            t_cross,
                            SPLIT_PASSED,
                            {
                                "split_idx": s,
                                "split_name": route.splits[s].name,
                                "split_kind": route.splits[s].kind,
                                "dist_m": route.splits[s].dist_m,
                            },
                        )
                    )
                next_split[crossing] += 1

            # --- Fehlplanung schlaegt durch --------------------------
            # Der Wuerfel ist beim Planen gefallen; hier wird die Rechnung
            # nur noch praesentiert. Deshalb reicht ein Distanzvergleich.
            hit = running & (dist >= misjudge_at)
            if hit.any():
                for i in np.flatnonzero(hit):
                    misjudge = plans[i].misjudgement
                    record = conditions.add(
                        int(i),
                        cond.CATALOG["fehlplanung"],
                        t_s=t_next,
                        dist_m=float(dist[i]),
                        duration=misjudge.length_m,
                        strength=misjudge.strength,
                        reason=misjudge.reason,
                    )
                    events.append(
                        RaceEvent(
                            int(i),
                            t_next,
                            CONDITION_START,
                            {
                                "typ": record.typ,
                                "label": record.label,
                                "dist_km": round(dist[i] / 1000.0, 2),
                                "reason": misjudge.reason,
                            },
                        )
                    )
                misjudge_at[hit] = np.inf

            # --- Servicepunkte: geplanter Radwechsel -----------------
            at_sp = running & (dist >= sp_guard[next_sp])
            if at_sp.any():
                for i in np.flatnonzero(at_sp):
                    section = int(next_sp[i]) + 1
                    want = int(planned_bike[i, min(section, n_sections - 1)])
                    if want != int(bike[i]):
                        duration = st.bike_change_duration(
                            streams[i].get("stops"), float(service_factor[i])
                        )
                        stop_left[i] = duration
                        state[i] = STATE_STOPPED
                        bike[i] = want
                        events.append(
                            RaceEvent(
                                int(i),
                                t_next,
                                BIKE_CHANGE,
                                {
                                    "bike": ph.BIKE_NAMES[want],
                                    "duration_s": round(duration, 1),
                                    "dist_km": round(dist[i] / 1000.0, 2),
                                },
                            )
                        )
                        events.append(
                            RaceEvent(
                                int(i),
                                t_next,
                                STOP_START,
                                {"reason": "Radwechsel", "duration_s": round(duration, 1)},
                            )
                        )
                next_sp[at_sp] += 1

            # --- Ziel ------------------------------------------------
            arrived = running & (dist >= total_distance)
            if arrived.any():
                for i in np.flatnonzero(arrived):
                    moved = dist[i] - dist_prev[i]
                    frac = (total_distance - dist_prev[i]) / moved if moved > 1e-9 else 0.0
                    finish_t[i] = t + frac * dt
                    events.append(
                        RaceEvent(int(i), finish_t[i], FINISH, {"dist_km": total_distance / 1000.0})
                    )
                state[arrived] = STATE_FINISHED
                dist[arrived] = total_distance
                v[arrived] = 0.0
                power_now[arrived] = 0.0

            t = t_next

        if progress is not None and tick % 20000 == 0:
            progress(tick, max_ticks, int((state == STATE_FINISHED).sum()), n)

    # Wer nach max_hours noch fährt, gilt als Ausfall.
    unfinished = np.flatnonzero(state < STATE_FINISHED)
    for i in unfinished:
        state[i] = STATE_DNF
        events.append(
            RaceEvent(
                int(i),
                t,
                DNF,
                {"dist_km": round(dist[i] / 1000.0, 2), "reason": "Zeitrahmen überschritten"},
            )
        )

    conditions.close_all(t, dist)

    # Abschlussbild festhalten. Die Schleife bricht ab, sobald niemand
    # mehr fährt – der letzte reguläre Abtastpunkt liegt dann vor der
    # Zieldurchfahrt des letzten Fahrers, und ohne diesen Nachtrag stünde
    # er in der Telemetrie für immer als "fährt" auf der Strecke.
    v[:] = 0.0
    power_now[:] = 0.0
    _record()

    telemetry = Telemetry(
        sample_dt_s=sample_dt,
        dist_m=buf_dist[:, :n_samples].copy(),
        v_cms=buf_v[:, :n_samples].copy(),
        power_w=buf_p[:, :n_samples].copy(),
        form_pct=buf_form[:, :n_samples].copy(),
        wprime_pct=buf_wp[:, :n_samples].copy(),
        bike=buf_bike[:, :n_samples].copy(),
        state=buf_state[:, :n_samples].copy(),
    )

    entries = [
        RaceEntry(
            entry_id=i,
            rider_id=rider.id,
            bib=bib,
            start_offset_s=offset,
            season_form=float(f_season[i]),
            day_form=float(f_day[i]),
            target_if=float(target_if[i]),
            finish_time_s=None if np.isnan(finish_t[i]) else float(finish_t[i]),
            status="FIN" if state[i] == STATE_FINISHED else "DNF",
            notes=[note for _, note in plans[i].notes],
        )
        for i, (rider, bib, offset) in enumerate(start_list)
    ]
    _assign_ranks(entries, config.time_limit_factor)
    split_ranks = _split_ranks(split_times)

    events.sort(key=lambda e: (e.t_s, e.entry_id))
    return RaceResult(
        config=config,
        route_name=route.name,
        entries=entries,
        riders=field_riders,
        teams=list(team_map.values()),
        split_times_s=split_times,
        split_ranks=split_ranks,
        telemetry=telemetry,
        events=events,
        plans=plans,
        conditions=conditions.records,
        compute_seconds=time.perf_counter() - t_start,
    )


def _assign_ranks(entries: list[RaceEntry], time_limit_factor: float) -> None:
    """Platzierung über die gefahrene Zeit, nicht über die Wanduhr.

    Ein Zeitfahren wird über die eigene Fahrzeit verglichen – die
    absolute Startzeit spielt für die Wertung keine Rolle.
    """
    finished = [e for e in entries if e.finish_time_s is not None]
    if not finished:
        return
    winner = min(e.finish_time_s for e in finished)  # type: ignore[type-var]
    limit = winner * time_limit_factor
    finished.sort(key=lambda e: e.finish_time_s)  # type: ignore[arg-type,return-value]
    rank = 0
    for entry in finished:
        if entry.finish_time_s > limit:  # type: ignore[operator]
            entry.status = "OTL"
            entry.rank = None
            continue
        rank += 1
        entry.rank = rank
        entry.status = "FIN"


def _split_ranks(split_times: np.ndarray) -> np.ndarray:
    """Rang je Split; 0 bedeutet "nicht erreicht"."""
    ranks = np.zeros(split_times.shape, dtype=np.int16)
    for s in range(split_times.shape[1]):
        column = split_times[:, s]
        valid = np.flatnonzero(np.isfinite(column))
        if valid.size == 0:
            continue
        order = valid[np.argsort(column[valid], kind="stable")]
        ranks[order, s] = np.arange(1, order.size + 1, dtype=np.int16)
    return ranks
