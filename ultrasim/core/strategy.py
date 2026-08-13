"""Strategiemodul, Stufe 1: der Rennplan (Game-Design-Dokument, Abschnitt 7.1).

Weil es keinen Spieler gibt, ersetzt dieses Modul alle Entscheidungen,
die sonst der Nutzer träfe. Es läuft einmal vor dem Start und legt fest:

* Ziel-Intensität als Anteil der FTP über die Distanz
* wie viel am Anstieg draufgelegt wird
* welches Rad je Abschnitt zwischen zwei Servicepunkten gefahren wird

Der Plan ist absichtlich unvollkommen: Ein Fahrer mit niedriger
Erfahrung oder niedriger Pacing-Disziplin plant zu ambitioniert. Genau
daraus entstehen die späteren Einbrüche.

Jede Entscheidung wird mit Begründung protokolliert – das ist fürs
Balancing unverzichtbar und lässt sich in der UI als Fahrer-Ticker
anzeigen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..geo.route import Route
from . import physics as ph
from .rider import Rider

#: Ziel-Intensität als Funktion der Distanz: IF = a − b · ln(km).
#: Verankert an den Vorgaben aus Abschnitt 7.1 – 200 km ≈ 0,82 FTP,
#: 2500 km ≈ 0,59 FTP.
IF_A = 1.2977
IF_B = 0.0911
IF_CLIP = (0.45, 0.92)

#: Aufschlag am Anstieg – bei gleicher Intensität wäre man dort zu
#: langsam, weil die Zeit pro Höhenmeter überproportional zählt.
CLIMB_BOOST_BASE = 0.16
CLIMB_BOOST_PER_BERG = 0.10
CLIMB_BOOST_REF_GRADE = 0.10

#: Basisdauer eines Radwechsels am Servicepunkt (Abschnitt 6.4).
BIKE_CHANGE_BASE_S = 45.0
BIKE_CHANGE_SD_S = 15.0
BIKE_CHANGE_MIN_S = 20.0


@dataclass
class SectionPlan:
    """Ein Abschnitt zwischen zwei Servicepunkten."""

    idx: int
    dist_start_m: float
    dist_end_m: float
    bike: int
    est_time_road_s: float
    est_time_tt_s: float


@dataclass
class RacePlan:
    """Rennplan eines Fahrers."""

    rider_id: int
    target_if: float
    climb_boost: float
    sections: list[SectionPlan] = field(default_factory=list)
    notes: list[tuple[float, str]] = field(default_factory=list)  # (dist_m, Begründung)
    #: Wo der zu ambitionierte Plan zurückschlägt (None = geht auf).
    misjudgement: Misjudgement | None = None


def base_target_if(distance_km: float) -> float:
    return float(np.clip(IF_A - IF_B * math.log(max(distance_km, 1.0)), *IF_CLIP))


def target_intensity(
    rider: Rider, distance_km: float, rng: np.random.Generator
) -> tuple[float, float, str]:
    """Ziel-Intensität eines Fahrers samt Planungsfehler und Begründung.

    Der zurückgegebene ``overreach`` ist der Betrag, um den der Plan zu
    ambitioniert ist. Er wird später gebraucht, um zu entscheiden, ob
    dieser Fahrer die Rechnung dafür präsentiert bekommt.
    """
    base = base_target_if(distance_km)
    skill = 0.030 * rider.attr_norm("ausdauer") + 0.018 * rider.attr_norm("erfahrung")

    # Fehlplanung: wer schlecht pact und wenig Erfahrung hat, plant zu heiß.
    # Der Fehler ist systematisch (Vorzeichen immer nach oben) und hat
    # zusätzlich eine Zufallskomponente.
    pacing_gap = max(0.0, (50.0 - rider.attr("pacing_disziplin")) / 50.0)
    exp_gap = max(0.0, (50.0 - rider.attr("erfahrung")) / 50.0)
    overreach = 0.035 * pacing_gap * (1.0 + 0.5 * exp_gap)
    overreach += float(rng.normal(0.0, 0.012))

    value = float(np.clip(base + skill + overreach, *IF_CLIP))
    note = (
        f"Rennplan: Ziel {value * 100:.0f} % FTP über {distance_km:.0f} km "
        f"(Basis {base * 100:.0f} %, Fahrerprofil {skill * 100:+.1f} pp, "
        f"Planungsfehler {overreach * 100:+.1f} pp)"
    )
    return value, overreach, note


# ----------------------------------------------------------------------
# Fehlplanung als Zustand
# ----------------------------------------------------------------------
#: Ab diesem Planungsfehler wird eine Fehlplanung überhaupt möglich …
MISJUDGE_THRESHOLD = 0.005
#: … und bei diesem Überschuss ist sie so gut wie sicher.
MISJUDGE_FULL = 0.060
MISJUDGE_MAX_P = 0.85
#: Der Einbruch kommt spät — vorher merkt niemand etwas.
MISJUDGE_ONSET = (0.45, 0.70)
#: Wirkungsdauer laut Katalog: 100–300 km, begrenzt auf die Reststrecke.
MISJUDGE_LENGTH_M = (100_000.0, 300_000.0)
#: Stärke skaliert den Katalogwert (−8 % FTP) auf −5 bis −12 %.
MISJUDGE_STRENGTH = (0.625, 1.5)


@dataclass
class Misjudgement:
    """Wo und wie hart ein zu ambitionierter Plan zurückschlägt."""

    dist_m: float
    length_m: float
    strength: float
    reason: str


def plan_misjudgement(
    route: Route, overreach: float, rng: np.random.Generator
) -> Misjudgement | None:
    """Entscheidet vor dem Start, ob die Rechnung präsentiert wird.

    Bewusst hier und nicht im Tick: Der Fahrer *hat* sich schon beim
    Planen vertan, sichtbar wird es nur später. Das macht die Sache auch
    reproduzierbar — der Würfel fällt einmal je Fahrer und Seed, nicht
    hunderttausendmal während des Rennens.
    """
    if overreach <= MISJUDGE_THRESHOLD:
        return None
    p = np.clip(
        (overreach - MISJUDGE_THRESHOLD) / (MISJUDGE_FULL - MISJUDGE_THRESHOLD),
        0.0,
        MISJUDGE_MAX_P,
    )
    if rng.random() >= p:
        return None

    onset = float(rng.uniform(*MISJUDGE_ONSET)) * route.distance_m
    remaining = route.distance_m - onset
    length = float(np.clip(rng.uniform(*MISJUDGE_LENGTH_M), 0.0, remaining * 0.95))
    strength = float(rng.uniform(*MISJUDGE_STRENGTH))
    drop = (1.0 - 0.92) * strength * 100.0
    return Misjudgement(
        dist_m=onset,
        length_m=length,
        strength=strength,
        reason=(
            f"Fehlplanung schlägt durch: Plan lag {overreach * 100:.1f} pp über dem "
            f"Haltbaren, −{drop:.0f} % FTP ab km {onset / 1000:.0f} über "
            f"{length / 1000:.0f} km"
        ),
    )


def climb_boost(rider: Rider) -> float:
    return CLIMB_BOOST_BASE + CLIMB_BOOST_PER_BERG * rider.attr_norm("berg")


def terrain_power_factor(grade: np.ndarray, boost: np.ndarray) -> np.ndarray:
    """Leistungsprofil über die Strecke.

    Anstiege bekommen einen Aufschlag, Flachpassagen bleiben auf Ziel,
    Abfahrten regelt die Trittfrequenzgrenze in der Physik.
    """
    ramp = np.clip(grade, 0.0, CLIMB_BOOST_REF_GRADE) / CLIMB_BOOST_REF_GRADE
    return 1.0 + ramp * boost


# ----------------------------------------------------------------------
# Radplan
# ----------------------------------------------------------------------
def _grade_histogram(route: Route, lo_m: float, hi_m: float, n_bins: int = 33) -> tuple[np.ndarray, np.ndarray, float]:
    """Steigungsverteilung eines Abschnitts als Histogramm.

    Für die Radwahl genügt die Verteilung – *wo* welche Steigung liegt,
    ist für die Zeitschätzung des Abschnitts egal. Das drückt die
    Schätzung von zehntausenden Rasterpunkten auf gut 30 Stützstellen.
    """
    lo = int(lo_m // route.raster_m)
    hi = min(int(math.ceil(hi_m / route.raster_m)), route.n_points - 1)
    if hi <= lo:
        return np.zeros(1), np.zeros(1), 0.0
    grades = route.grade[lo:hi]
    edges = np.linspace(-0.16, 0.16, n_bins + 1)
    counts, _ = np.histogram(np.clip(grades, -0.159, 0.159), bins=edges)
    centres = 0.5 * (edges[:-1] + edges[1:])
    dist_per_bin = counts.astype(np.float64) * route.raster_m
    mean_ele = float(route.ele_m[lo:hi].mean())
    keep = dist_per_bin > 0
    return centres[keep], dist_per_bin[keep], mean_ele


def estimate_section_time(
    rider: Rider,
    power_w: float,
    boost: float,
    grades: np.ndarray,
    dists: np.ndarray,
    mean_ele: float,
    bike: int,
) -> float:
    """Geschätzte Fahrzeit eines Abschnitts mit einem bestimmten Rad."""
    spec = ph.BIKES[ph.BIKE_NAMES[bike]]
    mass = rider.weight_kg + spec["mass_kg"] + ph.SUPPORTED_LUGGAGE_KG
    k = ph.position_k(grades, np.full_like(grades, rider.attr_norm("flach")))
    cda = ph.cda_for(
        np.full_like(grades, rider.frontal_area_m2),
        k,
        np.full_like(grades, spec["cda_factor"]),
    )
    rho = ph.air_density(mean_ele)
    power = power_w * terrain_power_factor(grades, np.full_like(grades, boost))
    # Zeitfahrrad: Wirkungsgradverlust an steilen Rampen (Abschnitt 6.4).
    power = power * (1.0 - spec["steep_penalty"] * (grades > 0.06))
    v = ph.steady_state_speed(
        power, grades, np.full_like(grades, mass), cda, np.full_like(grades, ph.CRR["asphalt_good"]), rho
    )
    v = np.clip(v, 1.0, ph.DOWNHILL_NO_POWER)
    return float(np.sum(dists / v))


def build_bike_plan(
    rider: Rider,
    route: Route,
    target_if: float,
    boost: float,
    change_cost_s: float,
    allow_tt: bool = True,
) -> tuple[list[SectionPlan], list[tuple[float, str]]]:
    """Radwahl je Abschnitt zwischen zwei Servicepunkten (Abschnitt 6.4).

    Der Radwechsel ist an einen Servicepunkt gebunden. Deshalb wird nicht
    pro Einzelanstieg entschieden, sondern für den ganzen kommenden
    Abschnitt: Zeit für beide Varianten summieren, die kleinere nehmen –
    und den Wechsel nur ausführen, wenn er sich nach Abzug seiner Kosten
    überhaupt lohnt. Ohne diese Prüfung wechselt ein Fahrer bei jedem
    2,1-km-Hügel mit 3 % und verliert netto Zeit.
    """
    bounds = [0.0] + [sp.dist_m for sp in route.service_points] + [route.distance_m]
    power = rider.ftp_w * target_if
    sections: list[SectionPlan] = []
    notes: list[tuple[float, str]] = []
    current = ph.BIKE_ROAD

    for i, (lo, hi) in enumerate(zip(bounds[:-1], bounds[1:], strict=False)):
        grades, dists, mean_ele = _grade_histogram(route, lo, hi)
        if dists.sum() <= 0:
            continue
        t_road = estimate_section_time(rider, power, boost, grades, dists, mean_ele, ph.BIKE_ROAD)
        t_tt = (
            estimate_section_time(rider, power, boost, grades, dists, mean_ele, ph.BIKE_TT)
            if allow_tt
            else float("inf")
        )
        best = ph.BIKE_TT if t_tt < t_road else ph.BIKE_ROAD
        gain = abs(t_road - t_tt)

        if best != current:
            # Der Wechsel kostet jetzt Zeit, und am Ende des Abschnitts
            # steht womöglich der Rückwechsel. Beides muss der Gewinn tragen.
            if gain > change_cost_s:
                notes.append(
                    (
                        lo,
                        f"Radwechsel auf {ph.BIKE_NAMES[best]} bei km {lo / 1000:.0f}: "
                        f"geschätzter Gewinn {gain:.0f} s > Kosten {change_cost_s:.0f} s",
                    )
                )
                current = best
            else:
                notes.append(
                    (
                        lo,
                        f"Radwechsel abgelehnt bei km {lo / 1000:.0f}: "
                        f"geschätzter Gewinn {gain:.0f} s < Kosten {change_cost_s:.0f} s",
                    )
                )

        sections.append(
            SectionPlan(
                idx=i,
                dist_start_m=lo,
                dist_end_m=hi,
                bike=current,
                est_time_road_s=t_road,
                est_time_tt_s=t_tt if math.isfinite(t_tt) else 0.0,
            )
        )
    return sections, notes


def build_plan(
    rider: Rider,
    route: Route,
    rng: np.random.Generator,
    rng_misjudge: np.random.Generator | None = None,
    service_factor: float = 1.0,
    allow_tt: bool = True,
) -> RacePlan:
    """Kompletter Rennplan eines Fahrers.

    ``rng_misjudge`` ist bewusst ein eigener Strom: Ob dieser Fahrer
    seinen Planungsfehler ausbaden muss, darf nicht davon abhängen, wie
    viele Zufallszahlen die Radwahl vorher verbraucht hat.
    """
    target_if, overreach, note = target_intensity(rider, route.distance_km, rng)
    boost = climb_boost(rider)
    change_cost = BIKE_CHANGE_BASE_S * service_factor
    sections, notes = build_bike_plan(rider, route, target_if, boost, change_cost, allow_tt)
    misjudgement = plan_misjudgement(route, overreach, rng_misjudge or rng)

    plan = RacePlan(
        rider_id=rider.id,
        target_if=target_if,
        climb_boost=boost,
        sections=sections,
        misjudgement=misjudgement,
    )
    plan.notes.append((0.0, note))
    plan.notes.extend(notes)
    return plan


def bike_change_duration(
    rng: np.random.Generator, service_factor: float, base_s: float = BIKE_CHANGE_BASE_S
) -> float:
    """Dauer eines Radwechsels: Basis × Servicedisziplin + Streuung."""
    value = base_s * service_factor + float(rng.normal(0.0, BIKE_CHANGE_SD_S))
    return max(BIKE_CHANGE_MIN_S, value)
