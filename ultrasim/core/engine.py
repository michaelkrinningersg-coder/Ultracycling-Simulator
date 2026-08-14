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
from typing import Any, ClassVar

import numpy as np

from ..geo.route import Route
from . import conditions as cond
from . import fatigue as fat
from . import form as fm
from . import incidents as inc
from . import nutrition as nut
from . import physics as ph
from . import season as sn
from . import sleep as slp
from . import strategy as st
from . import tactics as tac
from . import weather as wx
from .events import (
    BIKE_CHANGE,
    BONK,
    CONDITION_END,
    CONDITION_START,
    DECISION,
    DNF,
    FINISH,
    INCIDENT,
    PLAN,
    SLEEP,
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
#: Startabstand je Distanzklasse. Halbe Stunde auf allen Distanzen: Im
#: Einzelzeitfahren ist der Abstand kein physikalischer Parameter — die
#: Zeitschicht des Wetters hängt an der Eigenzeit des Fahrers, nicht an
#: der Uhr —, sondern ein dramaturgischer. Er entscheidet, wie viele
#: Fahrer gleichzeitig auf der Strecke sind und wie lange die Übertragung
#: dauert. Bei 250 Startern spannt sich das Feld damit über fünf Tage
#: Wanduhr; im Zeitraffer sind das Minuten.
START_INTERVAL_S: dict[str, int] = {"kurz": 1800, "mittel": 1800, "ultra": 1800}

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
    #: Zwischenfälle und Aufgabe (Abschnitt 6.5). Abschaltbar, damit sich
    #: beim Balancing der reine Fahranteil isolieren lässt.
    enable_incidents: bool = True
    #: Wetter-Vorlage aus ultrasim.core.weather.PRESETS. None = aus dem
    #: Seed ziehen (Abschnitt 6.6).
    weather_preset: str | None = None
    race_date: date | None = None
    name: str = "Rennen"
    #: Restermüdung aus vorherigen Rennen der Saison, je ``rider_id`` in
    #: Kilojoule (Abschnitt 14, M7). Sie wird als bereits geleistete
    #: Arbeit in die Langzeitermüdung eingesetzt: Wer mit 5.000 kJ
    #: Rückstand startet, ist so müde, als lägen die ersten 5.000 kJ des
    #: Rennens schon hinter ihm. Leer = alle frisch.
    carry_work_kj: dict[int, float] = field(default_factory=dict)

    def resolved_sample_dt(self, distance_class: str) -> int:
        return self.sample_dt_s or SAMPLE_DT_S.get(distance_class, 15)

    def resolved_start_interval(self, distance_class: str) -> int:
        if self.start_interval_s is not None:
            return self.start_interval_s
        return START_INTERVAL_S.get(distance_class, 1800)


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
    #: Gefahrene Distanz bei der Aufgabe, für die Ergebnisliste.
    dnf_dist_m: float | None = None
    dnf_reason: str = ""
    #: An Zwischenfällen verlorene Zeit.
    lost_s: float = 0.0
    #: Im Rennen geleistete Arbeit. Grundlage der Restermüdung fürs
    #: nächste Rennen der Saison (Abschnitt 14).
    work_kj: float = 0.0
    #: Frische beim Start: 1,0 = ausgeruht, darunter steckt noch ein
    #: früheres Rennen der Saison in den Beinen.
    freshness: float = 1.0
    #: Kumulierter Aufgabedruck am Rennende. Wie nah war er dran? Der
    #: Kalibrierlauf in ``balance.py`` liest genau diesen Wert aus.
    give_up_score: float = 0.0

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
            "dnf_dist_m": None if self.dnf_dist_m is None else round(self.dnf_dist_m, 1),
            "dnf_reason": self.dnf_reason,
            "lost_s": round(self.lost_s, 1),
            "work_kj": round(self.work_kj, 1),
            "freshness": round(self.freshness, 4),
            "give_up_score": round(self.give_up_score, 4),
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
    glyco_pct: np.ndarray  # uint8, Glykogenfüllstand in Prozent
    sleep_pct: np.ndarray  # uint8, effektiver Schlafdruck in Prozent
    hydration_pct: np.ndarray  # uint8, 100 = frisch, 0 = 4 % Gewicht verloren
    bike: np.ndarray  # uint8
    state: np.ndarray  # uint8
    #: Die Faktoren, aus denen ``form_pct`` entsteht — je uint8 in
    #: Prozent. ``form_pct`` allein sagt *dass* einer schwach ist, nicht
    #: *warum*; die Simulation multipliziert dafür ein knappes Dutzend
    #: Faktoren, und ohne Aufzeichnung ist die Zerlegung hinterher nicht
    #: mehr rekonstruierbar. Saison-, Tagesform und Frische stehen nicht
    #: hier, sondern am Starter: Sie sind über das ganze Rennen konstant.
    #:
    #: ``None`` heißt: aus einem Rennen von vor dieser Aufzeichnung. Die
    #: Oberfläche sagt dann „nicht aufgezeichnet" statt zu raten.
    factors: dict[str, np.ndarray] | None = None

    #: Reihenfolge und Beschriftung der aufgezeichneten Faktoren.
    FACTOR_LABELS: ClassVar[dict[str, str]] = {
        "section": "Abschnittsform",
        "fatigue": "Langzeitermüdung",
        "conditions": "Zustände",
        "bonk": "Hungerast",
        "sleep": "Schlafmangel",
        "weather": "Wetter",
        "hydration": "Flüssigkeit",
        "altitude": "Höhe",
    }

    @property
    def n_entries(self) -> int:
        return int(self.dist_m.shape[0])

    @property
    def n_samples(self) -> int:
        return int(self.dist_m.shape[1])

    def nbytes(self) -> int:
        return sum(
            getattr(self, name).nbytes
            for name in (
                "dist_m",
                "v_cms",
                "power_w",
                "form_pct",
                "wprime_pct",
                "glyco_pct",
                "sleep_pct",
                "hydration_pct",
                "bike",
                "state",
            )
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
            glyco_pct=self.glyco_pct,
            sleep_pct=self.sleep_pct,
            hydration_pct=self.hydration_pct,
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
                glyco_pct=data["glyco_pct"],
                sleep_pct=data["sleep_pct"],
                hydration_pct=data["hydration_pct"],
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
    weather: wx.WeatherProfile = field(default_factory=wx.WeatherProfile)
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
        "give_up",
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
            streams[entry_id].get("stops"),
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
    boost_norm = np.array([p.boost_norm for p in plans])
    target_if = np.array([p.target_if for p in plans])
    skill_norm = np.array([r.attr_norm("abfahrtstechnik") for r in field_riders])
    risk_norm = np.array([r.attr_norm("risikobereitschaft") for r in field_riders])
    altitude_norm = np.array([r.attr_norm("hoehenanpassung") for r in field_riders])
    mechanic_norm = np.array([r.attr_norm("mechanikerfaehigkeit") for r in field_riders])
    saddle_onset_s = inc.saddle_onset_h(
        np.array([r.attr("sitzkomfort") for r in field_riders])
    ) * 3600.0
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

    fat_norm = np.array([r.attr_norm("fettverbrennung") for r in field_riders])
    pacing_norm = np.array([r.attr_norm("pacing_disziplin") for r in field_riders])
    glyco_cap = nut.glycogen_capacity_kcal(
        weight, np.array([r.attr("ausdauer") for r in field_riders])
    )
    intake_plan_g_h = np.array([p.intake_g_h for p in plans])
    intake_ceiling = np.array(
        [p.intake_ceiling_g_h or p.intake_g_h for p in plans]
    )
    intake_g_h = intake_plan_g_h.copy()
    wake_horizon = slp.wake_horizon_h(
        np.array([r.attr("schlaftoleranz") for r in field_riders])
    )
    regeneration = np.array([r.attr("regeneration") for r in field_riders])
    heat_norm = np.array([r.attr_norm("hitzetoleranz") for r in field_riders])
    cold_norm = np.array([r.attr_norm("kaeltetoleranz") for r in field_riders])
    wet_norm = np.array([r.attr_norm("naesseresistenz") for r in field_riders])
    crosswind_norm = np.array([r.attr_norm("seitenwindfestigkeit") for r in field_riders])
    drink_cap = nut.drink_ceiling_l_h(
        np.array([r.attr("magenvertraeglichkeit") for r in field_riders])
    )
    mental_norm = np.array(
        [r.attr_norm("mentale_widerstandsfaehigkeit") for r in field_riders]
    )

    # --- Strategiemodul Stufe 2 (Abschnitt 7.2) ----------------------
    tactics = tac.TacticsState.for_field(n)
    follow_protect = tac.follow_protective(
        np.array([r.attr("pacing_disziplin") for r in field_riders])
    )
    follow_risk = tac.follow_risky(
        np.array([r.attr("pacing_disziplin") for r in field_riders]),
        np.array([r.attr("mentale_widerstandsfaehigkeit") for r in field_riders]),
    )
    if_mod = np.ones(n)
    #: Bezugsgröße des Rückstands: die geplante Fahrzeit dieses Fahrers.
    plan_time_s = np.array([max(p.est_ride_time_s, 1800.0) for p in plans])

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
    radius_pt = ph.corner_radius_m(curv_pt)
    vcorner_pt = np.sqrt(ph.MU_DRY * ph.G * radius_pt)
    corner_skill = 1.0 + 0.12 * skill_norm + 0.08 * risk_norm
    rho_pt = ph.air_density(route.ele_m)

    # --- Wetter (Abschnitt 6.6) ---------------------------------------
    # Eigener Zufallsstrom auf Rennebene: Das Wetter haengt am Rennen,
    # nicht an einem Fahrer, und darf sich nicht verschieben, wenn ein
    # Fahrer mehr oder weniger wuerfelt.
    rng_weather = np.random.default_rng(np.random.SeedSequence(config.seed, spawn_key=(0, 99)))
    est_duration_h = max(route.distance_km / 25.0, 1.0)
    weather = wx.draw_profile(
        rng_weather,
        day_of_year,
        est_duration_h,
        preset=config.weather_preset,
        ref_elevation_m=float(route.ele_m.mean()),
    )
    exposure_pt = wx.exposure_profile(route.ele_m, route.raster_m)
    wind_local_pt = wx.local_wind_factor(exposure_pt)
    valley_pt = np.clip(-exposure_pt, 0.0, 1.0)
    # Peilung je Rasterpunkt, aufgeteilt in cos/sin: Damit wird die
    # Windzerlegung im Tick zu zwei Multiplikationen statt einem cos.
    bearing_seg = np.array([s.bearing_deg for s in route.segments])
    bearing_pt = (
        bearing_seg[seg_idx_pt] if len(bearing_seg) else np.zeros(route.n_points)
    )
    cos_bear_pt = np.cos(np.radians(bearing_pt))
    sin_bear_pt = np.sin(np.radians(bearing_pt))
    ref_ele_m = float(route.ele_m.mean())
    mean_lat = float(route.coords[:, 0].mean()) if len(route.coords) else 47.0
    sunrise_h, sunset_h = wx.sun_times(mean_lat, day_of_year)
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

    # Geplante Haltedauer je Servicepunkt, je Fahrer.
    n_sp = len(sp_dist)
    stop_planned = np.zeros((n, max(n_sp, 1)))
    stop_kind: list[list[str]] = [["kurz"] * max(n_sp, 1) for _ in range(n)]
    for i, plan in enumerate(plans):
        for stop in plan.stops:
            if stop.service_idx < n_sp:
                stop_planned[i, stop.service_idx] = stop.planned_s
                stop_kind[i][stop.service_idx] = stop.kind

    # ---------------- Zustände (Abschnitt 6.5) -----------------------
    conditions = cond.ConditionStore(n)
    cond_mods = np.ones((n, len(cond.CHANNELS)))
    # Distanzmarke, an der eine Fehlplanung zuschlägt; inf = geht auf.
    misjudge_at = np.array(
        [p.misjudgement.dist_m if p.misjudgement else np.inf for p in plans]
    )

    # ---------------- Zwischenfälle (Abschnitt 6.5) ------------------
    # Die Kandidaten stehen vor dem Start fest; im Tick bleibt ein
    # Distanzvergleich. Warum das so gebaut ist, steht in incidents.py.
    if config.enable_incidents:
        schedules = [
            inc.schedule_for_rider(route, r.attributes, streams[i].get("incident"))
            for i, r in enumerate(field_riders)
        ]
    else:
        schedules = [inc.IncidentSchedule() for _ in field_riders]
    inc_ptr = np.zeros(n, dtype=np.int64)
    inc_next = np.array(
        [s.dist_m[0] if len(s) else np.inf for s in schedules], dtype=np.float64
    )
    intake_ratio = intake_g_h / inc.REF_INTAKE_G_H
    #: Kalorienrückstand gegenüber dem eigenen Zufuhrplan.
    underfed_kcal = np.zeros(n)
    #: Kumulierter Aufgabedruck und die persönliche Schwelle, ab der es
    #: reicht. Die Schwelle wird einmal gezogen, nicht jeden Tick — sonst
    #: hinge das Ergebnis an der Schrittweite.
    give_up = np.zeros(n)
    give_up_limit = np.array(
        [float(s.get("give_up").exponential(1.0)) for s in streams]
    )
    dnf_reason: list[str] = [""] * n
    #: An Zwischenfällen und Notschlaf verlorene Zeit. Der geplante Halt
    #: zählt nicht — den hat der Fahrer selbst so gewollt.
    lost_s = np.zeros(n)

    # ---------------- Zustand ----------------------------------------
    dist = np.zeros(n)
    v = np.full(n, 4.0)
    # Restermüdung als bereits geleistete Arbeit. ``work_j_last`` startet
    # auf demselben Wert – sonst zählte der Übertrag beim ersten
    # Langsam-Tick als in zehn Sekunden verbrannte Energie und der Fahrer
    # wäre auf dem ersten Kilometer im Hungerast.
    carry_j = np.array(
        [config.carry_work_kj.get(r.id, 0.0) * 1000.0 for r in field_riders]
    )
    work_j = carry_j.copy()
    work_j_last = carry_j.copy()
    # Frische: der bleibende Teil der Restermüdung. Konstant über das
    # Rennen und deshalb einmal vorab, wie die Saisonform.
    f_fresh = np.array(
        [
            sn.freshness_factor(float(carry_j[i]) / 1000.0, float(work_cap_kj[i]))
            for i in range(n)
        ]
    )
    glyco_kcal = glyco_cap.copy()
    bonked = np.zeros(n, dtype=bool)
    wake_h = np.zeros(n)  # Stunden seit dem letzten Schlaf
    fluid_deficit_l = np.zeros(n)  # Fluessigkeitsdefizit in Litern
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
    buf_gly = np.zeros((n, cap), dtype=np.uint8)
    buf_slp = np.zeros((n, cap), dtype=np.uint8)
    buf_hyd = np.full((n, cap), 100, dtype=np.uint8)
    buf_bike = np.zeros((n, cap), dtype=np.uint8)
    buf_state = np.zeros((n, cap), dtype=np.uint8)
    # Die Zerlegung der Form. Sieben zusätzliche uint8-Kanäle kosten bei
    # 250 Fahrern rund 7 MB vor der Kompression — der Preis dafür, dass
    # die Oberfläche „warum ist der langsam?" beantworten kann, statt nur
    # „der ist langsam".
    buf_factors = {
        key: np.full((n, cap), 100, dtype=np.uint8) for key in Telemetry.FACTOR_LABELS
    }
    n_samples = 0

    def _grow() -> None:
        # Bewusst nicht np.resize: das tilt die Daten in flacher
        # Reihenfolge und würde die Zeilen gegeneinander verschieben.
        nonlocal cap, buf_dist, buf_v, buf_p, buf_form, buf_wp, buf_gly, buf_slp
        nonlocal buf_hyd, buf_bike, buf_state
        new_cap = cap * 2
        grown = []
        for buf in (buf_dist, buf_v, buf_p, buf_form, buf_wp, buf_gly, buf_slp, buf_hyd, buf_bike, buf_state):
            bigger = np.zeros((n, new_cap), dtype=buf.dtype)
            bigger[:, :cap] = buf
            grown.append(bigger)
        (buf_dist, buf_v, buf_p, buf_form, buf_wp, buf_gly, buf_slp, buf_hyd,
         buf_bike, buf_state) = grown
        for key, buf in buf_factors.items():
            bigger = np.full((n, new_cap), 100, dtype=np.uint8)
            bigger[:, :cap] = buf
            buf_factors[key] = bigger
        cap = new_cap

    def _record() -> None:
        nonlocal n_samples
        if n_samples >= cap:
            _grow()
        for key, value in (
            ("section", f_section),
            ("fatigue", f_fat),
            ("conditions", f_umwelt),
            ("bonk", bonk),
            ("sleep", sleep_perf),
            ("weather", weather_perf),
            ("hydration", hydration_perf),
            ("altitude", altitude_perf),
        ):
            # Runden statt abschneiden: Sieben Faktoren mit je einem
            # halben Prozent Abschneidefehler summieren sich sonst zu
            # einer Zerlegung, die spürbar unter der Form liegt, die sie
            # erklären soll.
            buf_factors[key][:, n_samples] = np.clip(
                np.round(np.asarray(value, dtype=np.float64) * 100.0), 0, 255
            ).astype(np.uint8)
        buf_dist[:, n_samples] = np.minimum(dist, total_distance).astype(np.int32)
        buf_v[:, n_samples] = np.clip(v * 100.0, 0, 32000).astype(np.int16)
        buf_p[:, n_samples] = np.clip(power_now, 0, 32000).astype(np.int16)
        buf_form[:, n_samples] = np.clip(form_now * 100.0, 0, 255).astype(np.uint8)
        buf_wp[:, n_samples] = np.clip(wprime / wprime_cap * 100.0, 0, 255).astype(np.uint8)
        buf_gly[:, n_samples] = np.clip(glyco_kcal / glyco_cap * 100.0, 0, 255).astype(np.uint8)
        buf_slp[:, n_samples] = np.clip(sleep_press * 100.0, 0, 255).astype(np.uint8)
        buf_hyd[:, n_samples] = nut.hydration_display_pct(dehyd_pct).astype(np.uint8)
        buf_bike[:, n_samples] = bike.astype(np.uint8)
        buf_state[:, n_samples] = state
        # Wer ausgestiegen ist, erholt sich nicht mehr im Rennen. Die
        # physiologischen Kanäle laufen im Modell weiter (der
        # Flüssigkeitshaushalt füllt sich auf, der Speicher auch), aber
        # angezeigt gehört der Stand von seinem letzten Kilometer –
        # sonst steht ein Aufgeber mit 100 % Glykogen im Fahrerdetail.
        out_of_race = state == STATE_DNF
        if n_samples > 0 and out_of_race.any():
            for buf in (buf_form, buf_wp, buf_gly, buf_slp, buf_hyd):
                buf[out_of_race, n_samples] = buf[out_of_race, n_samples - 1]
        n_samples += 1

    total_distance = route.distance_m
    power_now = np.zeros(n)
    form_now = np.ones(n)
    ftp_eff = ftp.copy()
    ftp_eff_if = ftp * target_if
    descent_mod = np.ones(n)
    crr_mod = np.ones(n)
    bonk = np.ones(n)
    sleep_perf = np.ones(n)
    # Die übrigen Formfaktoren setzt erst der Langsam-Tick; ohne
    # Vorbelegung stünde die erste Aufzeichnung vor einem leeren Namen.
    f_section = np.ones(n)
    f_fat = np.ones(n)
    f_umwelt = np.ones(n)
    hydration_perf = np.ones(n)
    altitude_perf = np.ones(n)
    saddle_sore = np.zeros(n, dtype=bool)
    sleep_press = np.zeros(n)
    headwind = np.zeros(n)
    weather_perf = np.ones(n)
    weather_crr = np.ones(n)
    mu_factor = np.ones(n)
    cross_cda = np.ones(n)
    dehyd_pct = np.zeros(n)
    # Wetterlage des letzten Langsam-Ticks: Die Zwischenfälle werten sie
    # bei jedem Tick aus, gerechnet wird sie nur alle zehn Sekunden.
    temp_local = np.full(n, 15.0)
    rain = 0.0
    daylight = True
    glyco_frac = np.ones(n)
    #: Takt der langsam veränderlichen Größen (Form, Ermüdung, Energie).
    slow_steps = max(1, int(round(10.0 / dt)))
    slow_dt = slow_steps * dt

    def _take_sleep(i: int, duration_s: float, t_s: float, rng: np.random.Generator) -> None:
        """Schlafstopp abrechnen: Wachzeit senken, Guete auswuerfeln.

        Schlaf am Strassenrand oder im Fahrzeug ist nicht das Bett zu
        Hause. Bleibt die Guete unter der Schwelle, wird der Druck nur
        teilweise abgebaut *und* es bleibt ein Zustand zurueck, der ueber
        die restliche Nacht nachwirkt (Abschnitt 6.5).
        """
        quality = slp.sleep_quality(float(regeneration[i]), rng)
        recovered_h = duration_s / 3600.0 * quality * 3.0
        wake_h[i] = max(0.0, wake_h[i] - recovered_h)
        events.append(
            RaceEvent(
                i,
                t_s,
                SLEEP,
                {
                    "duration_s": round(duration_s, 1),
                    "quality": round(quality, 2),
                    "dist_km": round(dist[i] / 1000.0, 2),
                    "wake_h_after": round(float(wake_h[i]), 1),
                },
            )
        )
        if quality < slp.POOR_SLEEP_QUALITY:
            record = conditions.add(
                i,
                cond.CATALOG["schlafdefizit"],
                t_s=t_s,
                dist_m=float(dist[i]),
                duration=4.0 * 3600.0,
                strength=float(np.clip((slp.POOR_SLEEP_QUALITY - quality) / 0.3, 0.3, 1.0)),
                reason=f"Schlecht geschlafen (Guete {quality:.0%})",
            )
            events.append(
                RaceEvent(
                    i,
                    t_s,
                    CONDITION_START,
                    {
                        "typ": record.typ,
                        "label": record.label,
                        "dist_km": round(dist[i] / 1000.0, 2),
                        "reason": record.reason,
                    },
                )
            )

    def _retire(i: int, t_s: float, reason: str) -> None:
        """Fahrer aus dem Rennen nehmen (Abschnitt 6.5)."""
        state[i] = STATE_DNF
        v[i] = 0.0
        power_now[i] = 0.0
        stop_left[i] = 0.0
        dnf_reason[i] = reason
        events.append(
            RaceEvent(
                i,
                t_s,
                DNF,
                {"dist_km": round(float(dist[i]) / 1000.0, 2), "reason": reason},
            )
        )

    def _apply_incident(i: int, t_s: float, outcome: inc.Outcome) -> None:
        """Sofortwirkung und Nachwirkung eines Zwischenfalls verbuchen."""
        events.append(
            RaceEvent(
                i,
                t_s,
                INCIDENT,
                {
                    "typ": outcome.typ,
                    "label": outcome.label,
                    "reason": outcome.reason,
                    "stop_s": round(outcome.stop_s, 1),
                    "dist_km": round(float(dist[i]) / 1000.0, 2),
                    "dnf": outcome.dnf,
                },
            )
        )
        if outcome.dnf:
            _retire(i, t_s, outcome.reason)
            return
        if outcome.stop_s > 0.0:
            # Kein zusätzliches STOP_START: Das INCIDENT-Ereignis nennt
            # Grund und Dauer bereits. Zwei Zeilen für denselben Halt
            # wären im Ticker nur Rauschen.
            stop_left[i] = outcome.stop_s
            lost_s[i] += outcome.stop_s
            state[i] = STATE_STOPPED
        if outcome.condition:
            record = conditions.add(
                i,
                cond.CATALOG[outcome.condition],
                t_s=t_s,
                dist_m=float(dist[i]),
                duration=outcome.condition_duration,
                strength=outcome.condition_strength,
                reason=outcome.reason,
            )
            events.append(
                RaceEvent(
                    i,
                    t_s,
                    CONDITION_START,
                    {
                        "typ": record.typ,
                        "label": record.label,
                        "dist_km": round(float(dist[i]) / 1000.0, 2),
                        "reason": record.reason,
                    },
                )
            )

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

                # --- Energiehaushalt (Abschnitt 6.1) -----------------
                # Der Verbrauch kommt aus dem Zuwachs der geleisteten
                # Arbeit seit dem letzten langsamen Takt, nicht aus der
                # Momentanleistung: So zählt eine Abfahrt ohne Tritt auch
                # wirklich als Pause und nicht als Stichprobe.
                d_work_kj = (work_j - work_j_last) / 1000.0
                work_j_last = work_j.copy()
                mean_power = d_work_kj * 1000.0 / max(slow_dt, 1e-9)
                intensity = mean_power / np.maximum(ftp_eff, 1.0)
                # Der Pacing-Faktor muss hier genauso stehen wie im Plan
                # — sonst rechnet der Fahrer mit einem Verbrauch, den er
                # unterwegs nicht hat, und der Energiedeckel wäre eine
                # Behauptung statt einer Bilanz.
                burned = (
                    nut.metabolic_kcal(d_work_kj)
                    * nut.carb_fraction(intensity, fat_norm)
                    * nut.pacing_carb_factor(pacing_norm)
                )
                taken = (
                    intake_g_h
                    * cond.channel(cond_mods, "kcal_aufnahme")
                    * (slow_dt / 3600.0)
                    * nut.CARB_KCAL_PER_G
                )
                glyco_kcal = np.clip(glyco_kcal - burned + taken, 0.0, glyco_cap)

                # --- Suboptimale Ernährung (Abschnitt 6.5) -----------
                # Nicht der Plan ist schuld, sondern was davon ankommt:
                # Wer mit Magenproblemen fährt, sammelt hier den
                # Rückstand, den der Magen ihm einbrockt.
                planned_kcal = intake_g_h * (slow_dt / 3600.0) * nut.CARB_KCAL_PER_G
                underfed_kcal = np.where(
                    state == STATE_RIDING,
                    underfed_kcal + (planned_kcal - taken),
                    underfed_kcal * 0.99,
                )
                starving = (underfed_kcal >= inc.UNDERFED_KCAL) & (state == STATE_RIDING)
                if starving.any():
                    for i in np.flatnonzero(starving):
                        record = conditions.add(
                            int(i),
                            cond.CATALOG["unterversorgt"],
                            t_s=t,
                            dist_m=float(dist[i]),
                            duration=inc.UNDERFED_DURATION_S,
                            reason="Zufuhr über Stunden unter Plan",
                        )
                        events.append(
                            RaceEvent(
                                int(i),
                                t,
                                CONDITION_START,
                                {
                                    "typ": record.typ,
                                    "label": record.label,
                                    "dist_km": round(dist[i] / 1000.0, 2),
                                    "reason": record.reason,
                                },
                            )
                        )
                    underfed_kcal[starving] = 0.0

                # --- Sitzbeschwerden (Abschnitt 6.5) -----------------
                # Wundsein kommt aus der Zeit im Sattel, nicht aus der
                # Distanz: Wer langsam fährt, sitzt länger und leidet
                # früher. Deshalb die Eigenzeit als Maß und nicht der
                # Kilometerstand.
                # ``t`` ist die Eigenzeit des Fahrers — die Simulation
                # rechnet jeden Fahrer in seiner eigenen Uhr, der
                # Startversatz kommt erst bei der Anzeige dazu.
                sore = (
                    (t >= saddle_onset_s)
                    & ~saddle_sore
                    & (state == STATE_RIDING)
                )
                if sore.any():
                    for i in np.flatnonzero(sore):
                        record = conditions.add(
                            int(i),
                            cond.CATALOG["sitzbeschwerden"],
                            t_s=t,
                            dist_m=float(dist[i]),
                            duration=inc.SADDLE_DURATION_S,
                            reason=f"{saddle_onset_s[i] / 3600.0:.0f} h im Sattel",
                        )
                        events.append(
                            RaceEvent(
                                int(i),
                                t,
                                CONDITION_START,
                                {
                                    "typ": record.typ,
                                    "label": record.label,
                                    "dist_km": round(dist[i] / 1000.0, 2),
                                    "reason": record.reason,
                                },
                            )
                        )
                    saddle_sore[sore] = True

                glyco_frac = glyco_kcal / glyco_cap
                bonk = nut.bonk_factor(glyco_frac)
                fresh_bonk = (glyco_frac < nut.BONK_THRESHOLD) & ~bonked & (state == STATE_RIDING)
                if fresh_bonk.any():
                    for i in np.flatnonzero(fresh_bonk):
                        events.append(
                            RaceEvent(
                                int(i),
                                t,
                                BONK,
                                {
                                    "dist_km": round(dist[i] / 1000.0, 2),
                                    "glyco_pct": round(float(glyco_frac[i]) * 100.0, 1),
                                },
                            )
                        )
                    bonked |= fresh_bonk
                # Wer sich wieder erholt, kann erneut einbrechen.
                bonked &= glyco_frac < nut.BONK_THRESHOLD * 1.6

                # --- Wetter (Abschnitte 6.6 und 8.1.1) ---------------
                # Zeitschicht: Skalare aus der Fahrer-Eigenzeit. Weil alle
                # Fahrer in Eigenzeit rechnen, erlebt jeder denselben
                # Ablauf – nur zu seiner eigenen Uhr.
                own_h = slp.own_hour(config.start_time_of_day_s, t)
                elapsed_h = t / 3600.0
                temp_sea = weather.temperature_at(own_h)
                wind_speed, wind_dir = weather.wind_at(own_h, elapsed_h)
                rain = weather.rain_at(elapsed_h)
                daylight = wx.is_daylight(own_h, sunrise_h, sunset_h)
                cos_wind = np.cos(np.radians(wind_dir))
                sin_wind = np.sin(np.radians(wind_dir))

                # Ortsschicht: haengt an der Position, fuer alle gleich.
                temp_local = temp_sea - wx.LAPSE_RATE_C_PER_M * (route.ele_m[idx] - ref_ele_m)
                if not daylight:
                    temp_local = temp_local - wx.VALLEY_NIGHT_COOLING_C * valley_pt[idx]
                wind_here = wind_speed * wind_local_pt[idx]

                # cos(Windrichtung - Peilung) ohne trigonometrischen Aufruf
                # je Fahrer: Die Peilung steckt vorgerechnet in der Strecke.
                cos_rel = cos_wind * cos_bear_pt[idx] + sin_wind * sin_bear_pt[idx]
                sin_rel = sin_wind * cos_bear_pt[idx] - cos_wind * sin_bear_pt[idx]
                headwind = wind_here * cos_rel
                crosswind = np.abs(wind_here * sin_rel)

                weather_perf = wx.climate_factor(temp_local, heat_norm, cold_norm)
                weather_crr = wx.wet_crr_factor(rain, wet_norm)
                mu_factor = np.sqrt(wx.surface_mu(rain, wet_norm) / wx.MU_DRY)
                cross_cda = wx.crosswind_cda_factor(crosswind, frontal, crosswind_norm)

                # --- Hydration (Abschnitt 6.1) -----------------------
                # Schwitzen folgt der *absoluten* Leistung, nicht der
                # relativen: Wer in der Hitze auf 60 % seiner Nennleistung
                # einbricht, produziert auch entsprechend weniger Wärme.
                # Mit der relativen Intensität bliebe die Schweißrate
                # dagegen hoch, obwohl der Fahrer kaum noch tritt – und
                # die Hitze würde sich selbst verstärken.
                intensity_abs = mean_power / np.maximum(ftp, 1.0)
                sweat = nut.sweat_rate_l_h(
                    intensity_abs, temp_local, weather.humidity, heat_norm
                )
                # Getrunken wird der Verbrauch *plus* der Rückstand, den
                # der Fahrer aufholen will – gedeckelt durch den Magen.
                want = sweat + fluid_deficit_l / nut.DRINK_CATCH_UP_H
                drunk = np.minimum(drink_cap, want)
                riding_now = state == STATE_RIDING
                fluid_deficit_l = np.maximum(
                    fluid_deficit_l
                    + np.where(riding_now, sweat - drunk, -nut.DRINK_AT_STOP_L_H)
                    * (slow_dt / 3600.0),
                    0.0,
                )
                dehyd_pct = fluid_deficit_l / weight * 100.0
                hydration_perf = nut.hydration_factor(dehyd_pct)

                # --- Schlafdruck (Abschnitt 6.2) ---------------------
                # Der zirkadiane Faktor ist ein Skalar, kein Vektor: Alle
                # Fahrer rechnen in Eigenzeit und starten in ihrem
                # persoenlichen "08:00" (Entscheidung 13).
                wake_h = np.where(state == STATE_RIDING, wake_h + slow_dt / 3600.0, wake_h)
                circadian = slp.circadian_factor(
                    slp.own_hour(config.start_time_of_day_s, t)
                )
                sleep_press = slp.pressure(wake_h, wake_horizon) * circadian
                sleep_perf = slp.performance_factor(sleep_press)

                # --- Regelkreis (Abschnitt 7.2) ----------------------
                # Erst hier, nach Glykogen, Wetter und Schlafdruck: Der
                # Regelkreis reagiert auf die Lage dieses Takts, nicht auf
                # die des vorigen.
                want = tac.desired(
                    glyco_frac,
                    temp_local,
                    heat_norm,
                    lost_s,
                    plan_time_s,
                    sleep_press,
                    tactics.active,
                )
                switched = want != tactics.active
                if switched.any():
                    for i, rule_idx in zip(*np.nonzero(switched), strict=True):
                        rule = tac.RULES[int(rule_idx)]
                        turned_on = bool(want[i, rule_idx])
                        events.append(
                            RaceEvent(
                                int(i),
                                t,
                                DECISION,
                                {
                                    "rule": rule.key,
                                    "label": rule.label,
                                    "on": turned_on,
                                    "dist_km": round(float(dist[i]) / 1000.0, 2),
                                    "reason": tac.reason(
                                        rule,
                                        turned_on,
                                        glyco=float(glyco_frac[i]) * 100.0,
                                        temp=float(temp_local[i]),
                                        lost=float(lost_s[i]) / 60.0,
                                        press=float(sleep_press[i]) * 100.0,
                                    ),
                                },
                            )
                        )
                    tactics.active = want
                    if_mod = tac.intensity_modifier(want, follow_protect, follow_risk)
                    # Im Sparmodus wird gegessen, was der Magen hergibt.
                    saving = want[:, tac.RULE_INDEX["sparmodus"]]
                    intake_g_h = np.where(
                        saving,
                        intake_plan_g_h
                        + (intake_ceiling - intake_plan_g_h) * follow_protect,
                        intake_plan_g_h,
                    )

                f_section = fm.section_form_at(section_track, dist, section_grid)
                f_fat = fat.fatigue_factor(work_j / 1000.0, work_cap_kj)
                # f_umwelt ist das Produkt aller aktiven Zustände
                # (Abschnitt 6.5); Wetter kommt mit M6 in denselben Kanal.
                f_umwelt = cond.channel(cond_mods, "ftp")
                altitude_perf = ph.altitude_factor(route.ele_m[idx], altitude_norm)
                form_now = (
                    f_season * f_day * f_fresh * f_section * f_fat * f_umwelt
                    * bonk * sleep_perf * weather_perf * hydration_perf * altitude_perf
                )
                ftp_eff = ftp * form_now
                ftp_eff_if = ftp_eff * target_if * if_mod
                # Abfahrtstempo: Zustaende, Muedigkeit, Sicht bei Nacht,
                # Haftung bei Naesse und Seitenwind multiplizieren sich –
                # unabhaengige Ursachen, unabhaengige Faktoren.
                descent_mod = (
                    cond.channel(cond_mods, "abfahrtstempo")
                    * slp.descent_factor(sleep_press)
                    * wx.night_descent_factor(daylight)
                    * mu_factor
                )
                crr_mod = cond.channel(cond_mods, "crr") * weather_crr

                # --- Aufgabe (Abschnitt 6.5) -------------------------
                # Rückstand auf den eigenen Plan × Ermüdung ×
                # Magenzustand, gedämpft durch mentale Widerstands-
                # fähigkeit. Als Produkt: Wer im Plan liegt, hört nicht
                # auf – egal wie mies es ihm geht.
                if config.enable_incidents:
                    behind = 1.0 + lost_s / np.maximum(t, 1800.0)
                    stomach = (
                        1.0
                        + 1.8 * np.clip(1.0 - cond.channel(cond_mods, "kcal_aufnahme"), 0.0, 1.0)
                        + 0.8 * (glyco_frac < nut.BONK_THRESHOLD)
                    )
                    rate = inc.give_up_rate(
                        behind, f_fat, sleep_press, stomach, mental_norm
                    )
                    give_up = np.where(
                        state == STATE_RIDING, give_up + rate * (slow_dt / 3600.0), give_up
                    )
                    quitting = (give_up >= give_up_limit) & (state == STATE_RIDING)
                    for i in np.flatnonzero(quitting):
                        _retire(int(i), t, "Aufgabe: kein Anschluss mehr an den eigenen Plan")
                    if quitting.any():
                        running = state == STATE_RIDING

            # ``boost_norm`` bezahlt den Anstiegsaufschlag im Flachen ab,
            # damit die mittlere Intensität die geplante bleibt.
            p_target = ftp_eff_if * boost_norm * (1.0 + ramp_pt[idx] * boost)
            p_target = p_target * (1.0 - bike_steep[bike] * steep_pt[idx])

            # W'-Wächter: bei leerem Tank wird an Rampen nicht mehr
            # überzogen (Regelkreis aus Abschnitt 7.2).
            guard = wprime < fat.W_PRIME_GUARD * wprime_cap
            p_target = np.where(guard, np.minimum(p_target, ftp_eff), p_target)
            p_eff = p_target * ph.downhill_power_taper(v)

            # --- Physik ----------------------------------------------
            mass = weight + bike_mass[bike] + ph.SUPPORTED_LUGGAGE_KG
            cda = ph.cda_for(frontal, ph.position_k(grade, flat_norm), bike_cda_f[bike]) * cross_cda
            # Der Faktor greift auf Kurvenlimit *und* Sicherheitsdeckel.
            # Nur auf das Kurvenlimit angewandt bliebe er auf gerader
            # Strecke wirkungslos – nachts bombt trotzdem niemand mit
            # 85 km/h eine unbeleuchtete Abfahrt hinunter.
            v_limit = np.minimum(vcorner_pt[idx] * corner_skill, ph.MAX_SPEED) * descent_mod

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
                headwind=headwind,
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

            # --- Notschlaf (Abschnitt 6.2) ---------------------------
            # Ab dem kritischen Druck geht nichts mehr. Anders als der
            # geplante Schlafstopp haengt der nicht am Servicepunkt: Wer
            # so muede ist, legt sich hin, wo er steht.
            if tick % slow_steps == 0:
                critical = running & (sleep_press >= slp.FORCED_SLEEP_PRESSURE)
                if critical.any():
                    for i in np.flatnonzero(critical):
                        rng_stop = streams[i].get("sleep")
                        duration = float(rng_stop.uniform(*slp.FORCED_SLEEP_S))
                        _take_sleep(int(i), duration, t_next, rng_stop)
                        stop_left[i] = duration
                        lost_s[i] += duration  # ungeplant, also verlorene Zeit
                        state[i] = STATE_STOPPED
                        events.append(
                            RaceEvent(
                                int(i),
                                t_next,
                                STOP_START,
                                {
                                    "reason": "Notschlaf am Strassenrand",
                                    "kind": "notschlaf",
                                    "duration_s": round(duration, 1),
                                    "dist_km": round(dist[i] / 1000.0, 2),
                                },
                            )
                        )
                    sleep_press[critical] = 0.0
                    # Wer schläft, fährt nicht mehr durch die folgenden
                    # Blöcke – sonst hielte er am Servicepunkt gleich
                    # noch einmal.
                    running = state == STATE_RIDING

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

            # --- Zwischenfälle (Abschnitt 6.5) -----------------------
            # Der Kandidat liegt fest, die Annahme entscheidet sich hier:
            # Nässe, Dunkelheit und Müdigkeit kennt man erst jetzt.
            reached = running & (dist >= inc_next)
            if reached.any():
                for i in np.flatnonzero(reached):
                    i = int(i)
                    schedule = schedules[i]
                    typ = schedule.typ[int(inc_ptr[i])]
                    rng_inc = streams[i].get("incident")
                    ctx = inc.RideContext(
                        rain=rain,
                        daylight=daylight,
                        sleep_press=float(sleep_press[i]),
                        temp_c=float(temp_local[i]),
                        speed_ms=float(v[i]),
                        intake_ratio=float(intake_ratio[i]),
                        heat_norm=float(heat_norm[i]),
                        wet_norm=float(wet_norm[i]),
                        service_factor=float(service_factor[i]),
                        mechanic_norm=float(mechanic_norm[i]),
                    )
                    if rng_inc.random() < inc.accept_probability(typ, ctx):
                        _apply_incident(i, t_next, inc.resolve(typ, rng_inc, ctx))
                    inc_ptr[i] += 1
                    inc_next[i] = (
                        schedule.dist_m[int(inc_ptr[i])]
                        if inc_ptr[i] < len(schedule)
                        else np.inf
                    )
                running = state == STATE_RIDING

            # --- Servicepunkte: geplanter Radwechsel -----------------
            at_sp = running & (dist >= sp_guard[next_sp])
            if at_sp.any():
                for i in np.flatnonzero(at_sp):
                    sp_i = int(next_sp[i])
                    section = sp_i + 1
                    rng_stop = streams[i].get("stops")

                    # Der geplante Halt am Servicepunkt …
                    kind = stop_kind[i][sp_i] if sp_i < n_sp else "kurz"
                    planned_s = float(stop_planned[i, sp_i]) if sp_i < n_sp else 0.0

                    # Regelkreis: Wer Schlafdruck angemeldet hat, macht aus
                    # diesem Halt einen Schlafstopp (Abschnitt 7.2). Das ist
                    # der Unterschied zwischen einer Entscheidung und dem
                    # Notschlaf am Straßenrand — der kommt erst, wenn hier
                    # niemand mehr rechtzeitig gehandelt hat.
                    if kind != "schlaf" and tactics.active[i, tac.RULE_INDEX["schlafplan"]]:
                        kind = "schlaf"
                        planned_s = max(
                            planned_s, float(rng_stop.uniform(*st.SLEEP_SHORT_S))
                        )
                        events.append(
                            RaceEvent(
                                int(i),
                                t_next,
                                DECISION,
                                {
                                    "rule": "schlafstopp",
                                    "label": "Schlafstopp",
                                    "on": True,
                                    "dist_km": round(float(dist[i]) / 1000.0, 2),
                                    "reason": (
                                        f"Halt zum Schlafstopp verlängert "
                                        f"({planned_s / 60:.0f} min statt "
                                        f"{max(float(stop_planned[i, sp_i]) if sp_i < n_sp else 0.0, 1.0) / 60:.0f} min)"
                                    ),
                                },
                            )
                        )

                    duration = st.stop_duration(
                        planned_s, float(service_factor[i]), rng_stop
                    )
                    reason = {"voll": "Vollservice", "schlaf": "Schlafstopp"}.get(
                        kind, "Kurzservice"
                    )

                    if kind == "schlaf":
                        _take_sleep(int(i), duration, t_next, rng_stop)

                    # … und der Radwechsel, falls einer ansteht. Beides
                    # passiert gleichzeitig, also zählt die längere Dauer,
                    # nicht die Summe.
                    want = int(planned_bike[i, min(section, n_sections - 1)])
                    if want != int(bike[i]):
                        change = st.bike_change_duration(rng_stop, float(service_factor[i]))
                        if change > duration:
                            duration = change
                            reason = f"{reason} mit Radwechsel"
                        else:
                            reason = f"{reason} (Radwechsel läuft mit)"
                        bike[i] = want
                        events.append(
                            RaceEvent(
                                int(i),
                                t_next,
                                BIKE_CHANGE,
                                {
                                    "bike": ph.BIKE_NAMES[want],
                                    "duration_s": round(change, 1),
                                    "dist_km": round(dist[i] / 1000.0, 2),
                                },
                            )
                        )

                    stop_left[i] = duration
                    state[i] = STATE_STOPPED
                    events.append(
                        RaceEvent(
                            int(i),
                            t_next,
                            STOP_START,
                            {
                                "reason": reason,
                                "kind": kind,
                                "duration_s": round(duration, 1),
                                "dist_km": round(dist[i] / 1000.0, 2),
                            },
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
        _retire(int(i), t, "Zeitrahmen überschritten")

    conditions.close_all(np.where(np.isnan(finish_t), t, finish_t), dist)

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
        glyco_pct=buf_gly[:, :n_samples].copy(),
        sleep_pct=buf_slp[:, :n_samples].copy(),
        hydration_pct=buf_hyd[:, :n_samples].copy(),
        bike=buf_bike[:, :n_samples].copy(),
        state=buf_state[:, :n_samples].copy(),
        factors={k: v[:, :n_samples].copy() for k, v in buf_factors.items()},
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
            dnf_dist_m=None if state[i] == STATE_FINISHED else float(dist[i]),
            dnf_reason="" if state[i] == STATE_FINISHED else dnf_reason[i],
            lost_s=float(lost_s[i]),
            give_up_score=float(give_up[i]),
            # Nur die *eigene* Arbeit, ohne den Übertrag – sonst würde
            # sich die Restermüdung über die Saison selbst aufschaukeln.
            work_kj=float(work_j[i] - carry_j[i]) / 1000.0,
            freshness=float(f_fresh[i]),
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
        weather=weather,
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
