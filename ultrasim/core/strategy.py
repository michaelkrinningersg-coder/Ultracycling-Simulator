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
from . import nutrition as nut
from . import physics as ph
from . import sleep as slp
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
#: Anteil der Radwechsel, bei denen etwas schiefgeht …
BIKE_CHANGE_TAIL_P = 0.05
#: … und wie lange es dann dauert.
BIKE_CHANGE_TAIL_S = (180.0, 480.0)


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
    #: Zielwert der Zufuhr in Gramm Kohlenhydrate je Stunde.
    intake_g_h: float = 0.0
    #: Was der Magen maximal durchließe. Der Regelkreis darf im
    #: Sparmodus bis hierher hochgehen (Abschnitt 7.2).
    intake_ceiling_g_h: float = 0.0
    #: Geplante Halte am Servicepunkt.
    stops: list[StopPlan] = field(default_factory=list)
    #: Geschätzte Fahrzeit ohne Stopps, in Sekunden.
    est_ride_time_s: float = 0.0


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
    rng_stops: np.random.Generator | None = None,
    service_factor: float = 1.0,
    allow_tt: bool = True,
) -> RacePlan:
    """Kompletter Rennplan eines Fahrers.

    ``rng_misjudge`` ist bewusst ein eigener Strom: Ob dieser Fahrer
    seinen Planungsfehler ausbaden muss, darf nicht davon abhängen, wie
    viele Zufallszahlen die Radwahl vorher verbraucht hat.
    """
    wish_if, overreach, note = target_intensity(rider, route.distance_km, rng)
    boost = climb_boost(rider)
    change_cost = BIKE_CHANGE_BASE_S * service_factor
    sections, notes = build_bike_plan(rider, route, wish_if, boost, change_cost, allow_tt)

    # --- Energiedeckel (Abschnitt 6.1) -------------------------------
    # Zwei Durchgänge: Die tragbare Intensität hängt an der Dauer, die
    # Dauer an der Intensität. Ein einziger Nachschlag reicht, weil der
    # Zusammenhang flach ist – die dritte Runde ändert nichts mehr.
    intake = float(
        nut.intake_ceiling_g_h(
            rider.attr("kohlenhydratverbrennung"), rider.attr("magenvertraeglichkeit")
        )
    )
    glycogen = float(nut.glycogen_capacity_kcal(rider.weight_kg, rider.attr("ausdauer")))
    fat_norm = rider.attr_norm("fettverbrennung")

    target_if = wish_if
    ride_time = _estimate_ride_time(sections, wish_if, wish_if)
    energy_if = wish_if
    for _ in range(2):
        energy_if = nut.sustainable_intensity(
            rider.ftp_w, intake, glycogen, ride_time / 3600.0, fat_norm
        )
        target_if = float(np.clip(min(wish_if, energy_if), *IF_CLIP))
        ride_time = _estimate_ride_time(sections, target_if, wish_if)

    if target_if < wish_if - 1e-6:
        limit_note = (
            f"Energiedeckel bindet: {intake:.0f} g KH/h tragen nur "
            f"{target_if * 100:.0f} % FTP statt der gewünschten {wish_if * 100:.0f} % "
            f"(Speicher {glycogen:.0f} kcal über {ride_time / 3600.0:.1f} h)"
        )
    else:
        limit_note = (
            f"Energiedeckel greift nicht: {intake:.0f} g KH/h reichen für "
            f"{energy_if * 100:.0f} % FTP, geplant sind {wish_if * 100:.0f} %"
        )

    # --- Geplante Zufuhr, mit Luft nach oben (Abschnitt 7.2) ---------
    # Der Plan isst nicht am Anschlag, sondern so viel, wie die
    # Zielintensität braucht. Zwei Gründe: Wer den Magen von Anfang an
    # ausreizt, riskiert ihn (der Ereigniskatalog rechnet die Zufuhrrate
    # in die Magenwahrscheinlichkeit ein), und der Regelkreis hätte sonst
    # gar keinen Spielraum, wenn er "Zufuhr erhöhen" beschließt.
    planned_intake = planned_intake_g_h(
        rider.ftp_w, target_if, glycogen, ride_time / 3600.0, fat_norm, intake
    )

    misjudgement = plan_misjudgement(route, overreach, rng_misjudge or rng)
    horizon_h = float(slp.wake_horizon_h(rider.attr("schlaftoleranz")))
    # Wer viel Schlaf verträgt und schlecht regeneriert, nimmt lieber
    # kurze Nickerchen; wer gut regeneriert, holt sich einen echten Block.
    prefers_short = rider.attr("schlaftoleranz") > rider.attr("regeneration")
    stops = plan_service_stops(
        route,
        _section_times(sections, target_if, wish_if),
        rng_stops or rng,
        wake_horizon_h=horizon_h,
        prefers_short_sleep=prefers_short,
    )

    plan = RacePlan(
        rider_id=rider.id,
        target_if=target_if,
        climb_boost=boost,
        sections=sections,
        misjudgement=misjudgement,
        intake_g_h=planned_intake,
        intake_ceiling_g_h=intake,
        stops=stops,
        est_ride_time_s=ride_time,
    )
    plan.notes.append((0.0, note))
    plan.notes.append((0.0, limit_note))
    if stops:
        full = sum(1 for s in stops if s.kind == "voll")
        naps = sum(1 for s in stops if s.kind == "schlaf")
        planned_total = sum(s.planned_s for s in stops) * service_factor
        sleep_note = (
            f", {naps} Schlafstopp{'s' if naps != 1 else ''}"
            if naps
            else f", kein Schlaf geplant (Wachhorizont {horizon_h:.0f} h reicht)"
        )
        plan.notes.append(
            (
                0.0,
                f"Stoppplan: {len(stops)} Halte ({full} Vollservice{sleep_note}), "
                f"zusammen rund {planned_total / 60.0:.0f} min geplante Standzeit",
            )
        )
    plan.notes.extend(notes)
    return plan


#: Wie stark die Fahrzeit auf eine geänderte Leistung reagiert. Im
#: Flachen dominiert der Luftwiderstand (t ~ P^(-1/3)), am Berg die
#: Schwerkraft (t ~ P^(-1)); 0,5 liegt dazwischen und reicht für eine
#: Planungsgröße allemal.
TIME_POWER_EXPONENT = 0.5


def _section_times(
    sections: list[SectionPlan], target_if: float, ref_if: float
) -> list[float]:
    """Fahrzeit je Abschnitt, auf eine andere Intensität umgerechnet.

    Die Schätzungen in ``SectionPlan`` entstanden bei der
    Wunschintensität. Fällt die Zielintensität durch den Energiedeckel,
    dauert alles länger – und zwar spürbar genug, dass man es beim
    Stoppplan nicht ignorieren darf.
    """
    scale = (ref_if / target_if) ** TIME_POWER_EXPONENT if target_if > 0 else 1.0
    out = []
    for section in sections:
        base = section.est_time_tt_s if section.bike == ph.BIKE_TT else section.est_time_road_s
        if base <= 0:
            base = section.est_time_road_s
        out.append(base * scale)
    return out


def _estimate_ride_time(sections: list[SectionPlan], target_if: float, ref_if: float) -> float:
    return float(sum(_section_times(sections, target_if, ref_if)))


#: Sicherheitsaufschlag auf die rechnerisch nötige Zufuhr. Ein Plan, der
#: auf das Gramm genau aufgeht, geht nie auf.
INTAKE_HEADROOM = 1.06
#: Und so viel wird mindestens gegessen, auch wenn die Rechnung weniger
#: verlangt – unter zwei Dritteln des Möglichen isst kein Ultrafahrer.
INTAKE_FLOOR_FRACTION = 0.66


def planned_intake_g_h(
    ftp_w: float,
    target_if: float,
    glycogen_kcal: float,
    duration_h: float,
    fat_norm: float,
    ceiling_g_h: float,
) -> float:
    """Wie viel ein Fahrer bei seiner Zielintensität einplant.

    Der Verbrauch bei Zielintensität minus dem, was er sich aus dem
    Speicher zu nehmen traut — mit Aufschlag, gedeckelt durch den Magen.

    Auf langen Distanzen kommt dabei fast immer der Magendeckel heraus,
    und das ist kein Fehler: Dort *ist* die Zufuhr der Engpass, deshalb
    wählt der Energiedeckel die Intensität ja gerade so, dass beides
    aufgeht. Spielraum bleibt auf kurzen und leichten Strecken — und dort
    ist er auch der einzige Ort, an dem "Zufuhr erhöhen" überhaupt etwas
    bewirken kann. Wo er fehlt, bleibt dem Regelkreis nur das Tempo.
    """
    burn = float(nut.carb_burn_g_h(ftp_w * target_if, target_if, fat_norm))
    drawdown = (
        nut.PLANNED_DRAWDOWN * glycogen_kcal / nut.CARB_KCAL_PER_G / max(duration_h, 0.1)
    )
    needed = max(burn - drawdown, 0.0) * INTAKE_HEADROOM
    return float(np.clip(needed, INTAKE_FLOOR_FRACTION * ceiling_g_h, ceiling_g_h))


# ----------------------------------------------------------------------
# Verpflegungs- und Stoppplan (Abschnitte 6.3 und 7.1)
# ----------------------------------------------------------------------
#: Basisdauer eines Kurzservice (Flaschen, Riegel) – oft rollend.
SHORT_SERVICE_S = (40.0, 90.0)
#: Vollservice: Essen, Kleidung, Wäsche.
FULL_SERVICE_S = (300.0, 900.0)
#: Nach so vielen Stunden ohne Vollservice wird der nächste Halt einer.
FULL_SERVICE_INTERVAL_H = 8.0
#: Streuung der tatsächlichen Stoppdauer um die geplante.
SERVICE_JITTER = 0.18

#: Ab diesem Anteil des Wachhorizonts plant ein Fahrer einen Schlafstopp.
#: 0,72 × 40 h = knapp 29 h – wer die Strecke schneller schafft, faehrt
#: durch, und genau das ist bei einem 1200er auch die richtige Antwort.
SLEEP_PLAN_TRIGGER = 0.72
#: Geplante Schlafdauer, je nach Typ.
SLEEP_SHORT_S = (3600.0, 5400.0)  # 60–90 min, der Schlafgeizige
SLEEP_LONG_S = (10800.0, 14400.0)  # 3–4 h, der Vorsichtige
#: Bleibt weniger übrig, wird gar nicht mehr geschlafen …
SLEEP_SKIP_REMAINING_H = 4.0
#: … und unterhalb dieser Restzeit höchstens ein Nickerchen.
SLEEP_LONG_MIN_REMAINING_H = 14.0


@dataclass
class StopPlan:
    """Ein geplanter Halt am Servicepunkt."""

    service_idx: int
    dist_m: float
    kind: str  # "kurz" | "voll" | "schlaf"
    planned_s: float

    @property
    def label(self) -> str:
        return {"voll": "Vollservice", "schlaf": "Schlafstopp"}.get(self.kind, "Kurzservice")


def plan_service_stops(
    route: Route,
    section_times_s: list[float],
    rng: np.random.Generator,
    wake_horizon_h: float | None = None,
    prefers_short_sleep: bool = False,
) -> list[StopPlan]:
    """Legt fest, an welchem Servicepunkt wie lange gehalten wird.

    Gehalten wird an jedem Servicepunkt – das Begleitfahrzeug ist ja da.
    Der Unterschied liegt im Typ: normalerweise Kurzservice, nach genug
    Zeit ein Vollservice, und wenn der Wachhorizont zur Neige geht, ein
    Schlafstopp.

    ``section_times_s`` sind die geschätzten Fahrzeiten der Abschnitte
    zwischen den Servicepunkten; daraus ergibt sich, *wann* ein Fahrer
    einen Punkt erreicht, ohne dass das Rennen dafür laufen müsste.

    Ein Rennen, das vor dem Trigger zu Ende ist, bekommt gar keinen
    Schlafstopp – bei 1200 km ist Durchfahren die richtige Antwort, nicht
    ein Modellartefakt.
    """
    stops: list[StopPlan] = []
    since_full_h = 0.0
    since_sleep_h = 0.0
    trigger_h = (
        wake_horizon_h * SLEEP_PLAN_TRIGGER if wake_horizon_h else float("inf")
    )

    for idx, sp in enumerate(route.service_points):
        if idx < len(section_times_s):
            hours = section_times_s[idx] / 3600.0
            since_full_h += hours
            since_sleep_h += hours

        remaining_h = sum(section_times_s[idx + 1 :]) / 3600.0
        # Kurz vor dem Ziel legt sich niemand mehr hin.
        if since_sleep_h >= trigger_h and remaining_h > SLEEP_SKIP_REMAINING_H:
            since_sleep_h = 0.0
            since_full_h = 0.0
            # Ein Vier-Stunden-Block sieben Stunden vor dem Ziel wäre
            # Unsinn: Wer absehbar ankommt, bevor die Müdigkeit ihn
            # wirklich einholt, nimmt höchstens ein Nickerchen.
            short = prefers_short_sleep or remaining_h < SLEEP_LONG_MIN_REMAINING_H
            span = SLEEP_SHORT_S if short else SLEEP_LONG_S
            kind, planned = "schlaf", float(rng.uniform(*span))
        elif since_full_h >= FULL_SERVICE_INTERVAL_H:
            since_full_h = 0.0
            kind, planned = "voll", float(rng.uniform(*FULL_SERVICE_S))
        else:
            kind, planned = "kurz", float(rng.uniform(*SHORT_SERVICE_S))

        stops.append(
            StopPlan(service_idx=idx, dist_m=sp.dist_m, kind=kind, planned_s=planned)
        )
    return stops


def stop_duration(planned_s: float, service_factor: float, rng: np.random.Generator) -> float:
    """Tatsächliche Dauer = geplant · (1 + N(0, σ)) · f_servicedisziplin.

    Ein starker Fahrer in einem schlampigen Team verliert hier Zeit, die
    keine Beinarbeit zurückholt – das ist der ganze Zweck des
    Team-Attributs.
    """
    value = planned_s * (1.0 + float(rng.normal(0.0, SERVICE_JITTER))) * service_factor
    return max(15.0, value)


def bike_change_duration(
    rng: np.random.Generator, service_factor: float, base_s: float = BIKE_CHANGE_BASE_S
) -> float:
    """Dauer eines Radwechsels: Basis × Servicedisziplin + Streuung.

    Im Schwanz der Verteilung (5 %) geht etwas schief — Schaltung
    verstellt, Pedale falsch, Sattel rutscht — und aus 45 Sekunden werden
    3–8 Minuten (Abschnitt 6.5).
    """
    if rng.random() < BIKE_CHANGE_TAIL_P:
        return float(rng.uniform(*BIKE_CHANGE_TAIL_S)) * service_factor
    value = base_s * service_factor + float(rng.normal(0.0, BIKE_CHANGE_SD_S))
    return max(BIKE_CHANGE_MIN_S, value)
