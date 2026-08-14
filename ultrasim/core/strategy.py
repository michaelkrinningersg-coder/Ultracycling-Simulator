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

#: Was gute Pacing-Disziplin oberhalb des Mittelwerts einbringt: bis zu
#: 2 pp Zielintensität bei Disziplin 100. Begründung siehe
#: ``target_intensity`` — gleichmäßiges Fahren trägt bei gleichem
#: inneren Aufwand eine höhere mittlere Leistung, also darf man näher an
#: die eigene Grenze planen.
PACING_SKILL_GAIN = 0.020

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
    #: Macht den Anstiegsaufschlag budgetneutral — siehe
    #: ``boost_normalisation``. Auf einer flachen Strecke steht hier
    #: praktisch 1,0, im Hochgebirge deutlich darunter.
    boost_norm: float = 1.0
    #: Reifenwahl für die ganze Strecke (``ph.TYRE_NARROW``/``TYRE_WIDE``).
    tyre: int = 0


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

    # Pacing-Disziplin wirkt in **beide** Richtungen, und das war sie
    # lange nicht. Die Größe hing allein an ``max(0, (50 − pd) / 50)``:
    # Unterhalb des Mittelwerts plante man zu heiß, oberhalb passierte
    # gar nichts — ein Fahrer mit 80 plante Punkt für Punkt wie einer
    # mit 50. Damit war jeder Punkt oberhalb 50 verschenktes
    # Potenzial-Budget, und die Sensitivitätsmatrix hat das Attribut
    # folgerichtig mit −83 Sekunden ausgewiesen: Disziplin *kostete*
    # Zeit, weil nur die Unterseite überhaupt etwas bewirkte und diese
    # Unterseite ein Glücksspiel mit positivem Erwartungswert war.
    #
    # Jetzt hat die Oberseite einen eigenen Kanal, und zwar einen
    # physiologisch belegten: Gleichmäßiges Fahren trägt bei gleichem
    # inneren Aufwand eine höhere mittlere Leistung als ruppiges. Wer
    # sauber pact, darf deshalb näher an die eigene Grenze planen.
    #
    # Die Größen sind bewusst ungleich: Die Unterseite bringt bis zu
    # 3,5 pp, die Oberseite 2,0. Wer zu heiß plant, gewinnt mehr — und
    # riskiert dafür den Einbruch. Wer diszipliniert plant, gewinnt
    # weniger, aber sicher. Genau das soll die Entscheidung sein.
    pacing = rider.attr_norm("pacing_disziplin")
    skill = (
        0.030 * rider.attr_norm("ausdauer")
        + 0.018 * rider.attr_norm("erfahrung")
        + PACING_SKILL_GAIN * max(0.0, pacing)
    )

    # Fehlplanung: wer schlecht pact und wenig Erfahrung hat, plant zu heiß.
    # Der Fehler ist systematisch (Vorzeichen immer nach oben) und hat
    # zusätzlich eine Zufallskomponente.
    exp_gap = max(0.0, (50.0 - rider.attr("erfahrung")) / 50.0)
    overreach = 0.035 * max(0.0, -pacing) * (1.0 + 0.5 * exp_gap)
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
#:
#: Stand bei 0,060 und war damit zu milde: Der typische Draufgänger
#: plant mit rund 1,5 pp über dem Haltbaren, und daraus wurden ganze
#: 19 % Wahrscheinlichkeit. Vier von fünf kamen ungestraft davon,
#: während der Aufschlag auf die Zielintensität über das gesamte Rennen
#: wirkte — zu heiß zu planen war schlicht profitabel. Der Archetyp lag
#: auf der Flachstrecke bei mittlerer Platzierung 15,8 von 32 und holte
#: trotzdem fünf von sechs Siegen: Nicht der Schnitt gewinnt, sondern
#: der obere Rand, und der bestand genau aus denen, die den Würfel
#: überstanden hatten. Bei 0,030 sind es 42 %, und der Rand dünnt aus.
#:
#: Bewusst an dieser Schraube und nicht an Dauer oder Stärke: Die stehen
#: als 100–300 km und −5 bis −12 % FTP im Ereigniskatalog des
#: Design-Dokuments. Die Wahrscheinlichkeit steht dort nicht — sie ist
#: unsere Balancing-Größe.
MISJUDGE_FULL = 0.030
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

    Der Aufschlag ist **nicht** gratis — was er am Anstieg draufpackt,
    zieht ``boost_normalisation`` im Flachen wieder ab.
    """
    ramp = np.clip(grade, 0.0, CLIMB_BOOST_REF_GRADE) / CLIMB_BOOST_REF_GRADE
    return 1.0 + ramp * boost


def boost_normalisation(rider: Rider, route: Route, target_if: float, boost: float) -> float:
    """Der Faktor, der den Anstiegsaufschlag zu einer Umverteilung macht.

    Bis hierher war ``berg`` geschenkte Leistung. ``target_intensity``
    zieht die Zielintensität aus Distanz, Ausdauer und Erfahrung — von
    ``berg`` steht dort nichts —, und der Anstiegsaufschlag kam
    *obendrauf*. Ein Kletterer fuhr im Flachen genauso hart wie alle
    anderen und am Anstieg 24 % härter, ohne das irgendwo abzubezahlen.
    Über ein realistisches Feld waren das 12,7 % Leistung am 10-%-Anstieg
    gegen 1,4 % Tempo, die das Gegenstück *Flach* über die
    Positionsdisziplin bewegte.

    Jetzt wird der Aufschlag finanziert: Dieser Faktor normiert das
    Leistungsprofil so, dass die **zeitgewichtete** mittlere Intensität
    wieder ``target_if`` ergibt. Wer am Berg zulegt, fährt im Flachen
    entsprechend darunter.

    Zwei Gründe, warum das die richtigere Rechnung ist und nicht nur die
    strengere. Erstens sagt ``target_if`` laut eigener Beschreibung „Ziel-
    Intensität als Anteil der FTP **über die Distanz**" — das war bisher
    schlicht nicht wahr, die tatsächliche mittlere Intensität lag
    darüber. Zweitens rechnet der Energiedeckel oben mit genau diesem
    Mittel; solange der Aufschlag daneben stand, hat er den Verbrauch
    systematisch unterschätzt, und zwar am stärksten bei den Fahrern mit
    dem größten Aufschlag.

    Der Kletterer verliert dadurch nicht seinen Vorteil. Ungleichmäßiges
    Fahren zahlt sich am Berg weiterhin aus, weil Zeit dort schwerer
    wiegt: Eine Minute Mehrleistung am Anstieg spart mehr, als dieselbe
    Minute Minderleistung im Flachen kostet. Nur ist der Gewinn jetzt ein
    physikalischer statt eines zugeteilten.

    Gewichtet wird mit den Zeitanteilen des *unnormierten* Plans. Das ist
    ein Durchgang statt einer Iteration, und der Fehler daraus liegt
    unter einem Promille — die Gewichte verschieben sich kaum, wenn sich
    die Leistung um wenige Prozent ändert.
    """
    grades, dists, mean_ele = _grade_histogram(route, 0.0, route.distance_m, n_bins=65)
    if dists.sum() <= 0:
        return 1.0
    factor = terrain_power_factor(grades, np.full_like(grades, boost))
    spec = ph.BIKES[ph.BIKE_NAMES[ph.BIKE_ROAD]]
    mass = rider.weight_kg + spec["mass_kg"] + ph.SUPPORTED_LUGGAGE_KG
    cda = ph.cda_for(
        np.full_like(grades, rider.frontal_area_m2),
        ph.position_k(grades, np.full_like(grades, rider.attr_norm("flach"))),
        np.full_like(grades, spec["cda_factor"]),
    )
    v = ph.steady_state_speed(
        rider.ftp_w * target_if * factor,
        grades,
        np.full_like(grades, mass),
        cda,
        np.full_like(grades, ph.CRR["asphalt_good"]),
        ph.air_density(mean_ele),
    )
    time = dists / np.clip(v, 1.0, ph.DOWNHILL_NO_POWER)
    mean_factor = float(np.sum(time * factor) / np.sum(time))
    return 1.0 / mean_factor if mean_factor > 0.0 else 1.0


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


def surface_mix(route: Route, lo_m: float = 0.0, hi_m: float | None = None) -> tuple[float, float]:
    """Distanzgewichtetes Mittel aus Rollwiderstand und Rauheit.

    Der Rennplan trifft die Reifenwahl einmal für die ganze Strecke, und
    dafür genügen zwei Zahlen: wie viel Widerstand die Oberfläche im
    Mittel kostet und wie rau sie im Mittel ist. Wo keine Segmente
    liegen, gilt guter Asphalt — das ist der Zustand jeder Strecke, die
    aus einer GPX-Datei ohne Oberflächenangabe kommt.
    """
    hi_m = route.distance_m if hi_m is None else hi_m
    total = 0.0
    crr_sum = 0.0
    rough_sum = 0.0
    for seg in route.segments:
        lo = max(seg.dist_start_m, lo_m)
        hi = min(seg.dist_end_m, hi_m)
        if hi <= lo:
            continue
        length = hi - lo
        total += length
        crr_sum += length * ph.CRR.get(seg.surface, ph.CRR["asphalt_good"])
        rough_sum += length * ph.SURFACE_ROUGHNESS.get(seg.surface, 0.0)
    if total <= 0.0:
        return ph.CRR["asphalt_good"], 0.0
    return crr_sum / total, rough_sum / total


def estimate_section_time(
    rider: Rider,
    power_w: float,
    boost: float,
    grades: np.ndarray,
    dists: np.ndarray,
    mean_ele: float,
    bike: int,
    boost_norm: float = 1.0,
    tyre: int = ph.TYRE_NARROW,
    base_crr: float = ph.CRR["asphalt_good"],
    roughness: float = 0.0,
) -> float:
    """Geschätzte Fahrzeit eines Abschnitts mit einem bestimmten Rad."""
    spec = ph.BIKES[ph.BIKE_NAMES[bike]]
    tspec = ph.TYRES[ph.TYRE_NAMES[tyre]]
    mass = rider.weight_kg + spec["mass_kg"] + tspec["mass_kg"] + ph.SUPPORTED_LUGGAGE_KG
    k = ph.position_k(grades, np.full_like(grades, rider.attr_norm("flach")))
    cda = ph.cda_for(
        np.full_like(grades, rider.frontal_area_m2),
        k,
        np.full_like(grades, spec["cda_factor"]),
    ) + tspec["cda"]
    rho = ph.air_density(mean_ele)
    power = power_w * boost_norm * terrain_power_factor(grades, np.full_like(grades, boost))
    # Zeitfahrrad: Wirkungsgradverlust an steilen Rampen (Abschnitt 6.4).
    power = power * (1.0 - spec["steep_penalty"] * (grades > 0.06))
    # Zwei Durchgänge, weil der Rollwiderstand jetzt vom Tempo abhängt
    # und das Tempo vom Rollwiderstand. Der Zusammenhang ist flach — der
    # Tempoterm bewegt den Beiwert um wenige Prozent —, also reicht ein
    # Nachschlag, genau wie beim Energiedeckel eine Ebene höher.
    v = np.full_like(grades, 8.5)
    for _ in range(2):
        crr = ph.rolling_crr(
            np.full_like(grades, base_crr),
            np.full_like(grades, roughness),
            tspec["crr_factor"],
            tspec["stiffness"],
            v,
            np.full_like(grades, mass),
            rider.attr_norm("oberflaechenkompetenz"),
        )
        v = ph.steady_state_speed(power, grades, np.full_like(grades, mass), cda, crr, rho)
        v = np.clip(v, 1.0, ph.DOWNHILL_NO_POWER)
    return float(np.sum(dists / v))


def choose_tyre(rider: Rider, route: Route, power_w: float, boost: float) -> tuple[int, str]:
    """Reifenwahl für die ganze Strecke.

    Anders als das Rad wird der Reifen **einmal** entschieden und nicht
    je Abschnitt: Ein Reifenwechsel ist ein Radwechsel, und den bildet
    schon die Radwahl ab. Real entscheidet man das am Morgen vor dem
    Start, nach dem Streckenprofil — genau das tut diese Funktion.

    Auf jeder Strecke ohne Oberflächenangabe fällt die Wahl auf schmal,
    und zwar nicht als Vorgabe, sondern als Ergebnis: Auf glattem
    Asphalt gewinnt der harte Schmalreifen um gut 13 % Rollwiderstand.
    """
    base_crr, roughness = surface_mix(route)
    grades, dists, mean_ele = _grade_histogram(route, 0.0, route.distance_m, n_bins=65)
    if dists.sum() <= 0:
        return ph.TYRE_NARROW, ""
    times = [
        estimate_section_time(
            rider, power_w, boost, grades, dists, mean_ele, ph.BIKE_ROAD,
            tyre=t, base_crr=base_crr, roughness=roughness,
        )
        for t in (ph.TYRE_NARROW, ph.TYRE_WIDE)
    ]
    best = ph.TYRE_NARROW if times[ph.TYRE_NARROW] <= times[ph.TYRE_WIDE] else ph.TYRE_WIDE
    gain = abs(times[0] - times[1])
    share = 100.0 * roughness / max(ph.SURFACE_ROUGHNESS["gravel"], 1e-9)
    note = (
        f"Reifenwahl {ph.TYRE_NAMES[best]}: mittlere Rauheit {share:.0f} % Schotterniveau, "
        f"geschätzter Vorsprung {gain / 60.0:.1f} min über {route.distance_km:.0f} km"
    )
    return best, note


#: Kürzester Abschnitt, für den sich eine eigene Radwahl lohnt. Darunter
#: trägt kein Gewinn die Wechselkosten, und der Plan würde nur unruhig.
MIN_SECTION_M = 3000.0

#: Ab dieser Länge und dieser mittleren Steigung stellt sich das
#: Begleitfahrzeug an den Fuß eines Anstiegs. Vier Kilometer mit 3 %
#: sind 120 Höhenmeter — darunter ist es eine Welle, und ein Radwechsel
#: dafür hat sich noch nie gelohnt.
BIKE_STOP_MIN_LENGTH_M = 4000.0
BIKE_STOP_MIN_GRADE = 0.03


def _section_bounds(route: Route) -> list[float]:
    """Wo ein Fahrer das Rad wechseln kann.

    Zwei Sorten Marken: die Servicepunkte der Strecke und Fuß und Kuppe
    jedes nennenswerten Anstiegs. Der Anstieg *erzeugt dabei keinen
    Servicepunkt* — ein solcher zöge einen Halt nach sich, und dann
    hielte das Feld an jedem Berg an, auch wenn es gar nichts zu wechseln
    gibt. Er eröffnet nur die Möglichkeit; ob gewechselt wird, entscheidet
    weiter unten die Rechnung, und die muss den Wechsel selbst mittragen.
    """
    marks = {0.0, route.distance_m}
    marks.update(sp.dist_m for sp in route.service_points)
    for climb in route.climbs:
        if climb.length_m >= BIKE_STOP_MIN_LENGTH_M and climb.grade_avg >= BIKE_STOP_MIN_GRADE:
            marks.add(climb.dist_start_m)
            marks.add(climb.dist_end_m)
    ordered = sorted(m for m in marks if 0.0 <= m <= route.distance_m)
    # Zu dicht beieinander liegende Marken zusammenfassen: Ein Anstieg,
    # der 500 m hinter einem Servicepunkt beginnt, ist derselbe Halt.
    out = [ordered[0]]
    for mark in ordered[1:]:
        if mark - out[-1] >= MIN_SECTION_M:
            out.append(mark)
    if out[-1] < route.distance_m:
        out[-1] = route.distance_m
    return out


def build_bike_plan(
    rider: Rider,
    route: Route,
    target_if: float,
    boost: float,
    change_cost_s: float,
    allow_tt: bool = True,
    boost_norm: float = 1.0,
    tyre: int = ph.TYRE_NARROW,
) -> tuple[list[SectionPlan], list[tuple[float, str]]]:
    """Radwahl je Abschnitt zwischen zwei Servicepunkten (Abschnitt 6.4).

    Entschieden wird abschnittsweise, nicht pro Einzelanstieg: Zeit für
    beide Varianten summieren, die kleinere nehmen – und den Wechsel nur
    ausführen, wenn er sich nach Abzug seiner Kosten überhaupt lohnt.
    Ohne diese Prüfung wechselt ein Fahrer bei jedem 2,1-km-Hügel mit
    3 % und verliert netto Zeit.

    **Wo ein Abschnitt endet, ist die eigentliche Frage.** Zuerst waren
    das nur die Servicepunkte — und damit lag der Fehler auf der Hand:
    Auf dem Hochgebirgs-Marathon liegen fünf Servicepunkte auf 507 km,
    ein Abschnitt ist also 90 km lang und enthält 15 bis 21 % Steilstück.
    Über die Summe gewinnt das Zeitfahrrad um zwei Minuten, und der
    Fahrer quält sich damit über jeden Pass, obwohl es dort vier Minuten
    kostet. Deshalb sind jetzt auch **Fuß und Kuppe kategorisierter
    Anstiege** Abschnittsgrenzen: Im unterstützten Rennen fährt das
    Begleitfahrzeug mit, und genau dort steht es. Die
    Wirtschaftlichkeitsprüfung bleibt — sie entscheidet weiter, ob sich
    der Wechsel lohnt.
    """
    bounds = _section_bounds(route)
    power = rider.ftp_w * target_if
    sections: list[SectionPlan] = []
    notes: list[tuple[float, str]] = []
    current = ph.BIKE_ROAD

    for i, (lo, hi) in enumerate(zip(bounds[:-1], bounds[1:], strict=False)):
        grades, dists, mean_ele = _grade_histogram(route, lo, hi)
        if dists.sum() <= 0:
            continue
        base_crr, roughness = surface_mix(route, lo, hi)
        t_road = estimate_section_time(
            rider, power, boost, grades, dists, mean_ele, ph.BIKE_ROAD, boost_norm,
            tyre, base_crr, roughness,
        )
        t_tt = (
            estimate_section_time(
                rider, power, boost, grades, dists, mean_ele, ph.BIKE_TT, boost_norm,
                tyre, base_crr, roughness,
            )
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
    boost_norm = boost_normalisation(rider, route, wish_if, boost)
    tyre, tyre_note = choose_tyre(rider, route, rider.ftp_w * wish_if * boost_norm, boost)
    change_cost = BIKE_CHANGE_BASE_S * service_factor
    sections, notes = build_bike_plan(
        rider, route, wish_if, boost, change_cost, allow_tt, boost_norm, tyre
    )

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
    pacing_norm = rider.attr_norm("pacing_disziplin")

    target_if = wish_if
    ride_time = _estimate_ride_time(sections, wish_if, wish_if)
    energy_if = wish_if
    for _ in range(2):
        energy_if = nut.sustainable_intensity(
            rider.ftp_w, intake, glycogen, ride_time / 3600.0, fat_norm, pacing_norm
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
        rider.ftp_w, target_if, glycogen, ride_time / 3600.0, fat_norm, intake, pacing_norm
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
        boost_norm=boost_norm,
        tyre=tyre,
    )
    plan.notes.append((0.0, note))
    plan.notes.append((0.0, limit_note))
    if tyre_note:
        plan.notes.append((0.0, tyre_note))
    if boost_norm < 0.999:
        plan.notes.append(
            (
                0.0,
                f"Anstiegsaufschlag +{boost * 100:.0f} % am 10-%-Stück wird im Flachen "
                f"finanziert: {(1.0 - boost_norm) * 100:.1f} % unter Ziel, damit das "
                f"Mittel bei {target_if * 100:.0f} % FTP bleibt",
            )
        )
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
    pacing_norm: float = 0.0,
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
    burn = float(nut.carb_burn_g_h(ftp_w * target_if, target_if, fat_norm, pacing_norm))
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
