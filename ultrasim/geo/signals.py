"""Ampeln auf der Strecke.

Ein Ultrarennen führt über öffentliche Straßen, und öffentliche Straßen
haben Ampeln. Bisher endete die Strecke bei Höhenprofil, Oberfläche und
Servicepunkten — der Fahrer rollte durch jede Ortsdurchfahrt, als stünde
sie leer.

Die Ampel ist der erste Halt im Modell, den **niemand plant und niemand
verschuldet**. Panne, Notschlaf und Servicestopp hängen alle am Fahrer:
an seinem Material, seiner Müdigkeit, seinem Plan. Die Ampel hängt an
nichts davon. Sie ist reines Pech, gleichmäßig über das Feld verteilt,
und genau deshalb steht ihre Wartezeit weder im Aufgabedruck noch im
Zwischenfallkonto — sie ist keine Geschichte über den Fahrer.

**Die Phase läuft in Fahrer-Eigenzeit.** Das ist eine bewusste
Entscheidung und kein Versehen: Zwei Fahrer, die im Abstand von zwei
Stunden starten, treffen dieselbe Ampel bei derselben *eigenen*
Fahrzeit im selben Zustand an. Nach der Wanduhr wäre es anders — aber
die Wanduhr hängt am Startversatz, und der Startversatz geht in diesem
Simulator grundsätzlich nicht in die Simulation ein (Entscheidung 13).
Täte er es, hinge das Rennen eines Fahrers plötzlich daran, wie viele
vor ihm gestartet sind. Ein realistischeres Ampelmodell wäre den Preis
nicht wert.

Die Platzierung ist zufällig, aber an die Strecke gebunden statt an das
Rennen: Dieselbe Strecke hat in jedem Rennen dieselben Ampeln. Eine
Ampel ist eine Eigenschaft der Straße, nicht des Renntags.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

__all__ = [
    "TrafficLight",
    "RED_S",
    "GREEN_S",
    "CYCLE_S",
    "MIN_GAP_M",
    "PER_100_KM",
    "MAX_ELEVATION_M",
    "wait_s",
    "place",
]

#: Rot- und Grünphase in Sekunden. Gleich lang, also trifft ein Fahrer
#: die Ampel im Mittel in der Hälfte der Fälle rot an und wartet dann im
#: Mittel eine halbe Rotphase — 22,5 s je Ampel.
RED_S = 90.0
GREEN_S = 90.0
CYCLE_S = RED_S + GREEN_S

#: Mindestabstand zweier Ampeln.
MIN_GAP_M = 5_000.0

#: Höchstens so viele Ampeln in **jedem** Hundert-Kilometer-Fenster.
#: Nicht im Mittel: Bei sortierten Positionen ist die Bedingung genau
#: dann erfüllt, wenn zwischen der i-ten und der (i+2)-ten Ampel mehr
#: als hundert Kilometer liegen.
PER_100_KM = 2

#: Darüber steht keine Ampel mehr. Auf einem Pass in zweitausend Metern
#: gibt es keine Kreuzung, an der eine stehen könnte.
MAX_ELEVATION_M = 1200.0

#: Innerhalb eines kategorisierten Anstiegs steht auch keine — aus
#: demselben Grund, und weil ein Halt mitten in der Rampe die
#: Anstiegsphysik mit einer Anfahrt aus dem Stand belasten würde, die
#: nichts mit dem Anstieg zu tun hat.
#:
#: Start- und Zielbereich bleiben ebenfalls frei: Eine Ampel dreihundert
#: Meter nach dem Start wäre keine Streckeneigenschaft mehr, sondern eine
#: zweite Startaufstellung.
EDGE_CLEARANCE_M = 2_000.0


@dataclass(frozen=True, slots=True)
class TrafficLight:
    """Eine Ampel: wo sie steht und wo ihre Phase gerade steht."""

    idx: int
    dist_m: float
    #: Phasenversatz in Sekunden. Ohne ihn schalteten alle Ampeln einer
    #: Strecke im Gleichtakt, und ein Fahrer hätte entweder überall Rot
    #: oder nirgends.
    offset_s: float

    @property
    def dist_km(self) -> float:
        return self.dist_m / 1000.0


def wait_s(offset_s: float, t_s: float) -> float:
    """Wie lange ein Fahrer wartet, der zur Eigenzeit ``t_s`` ankommt.

    0,0 heißt Grün. Der Zyklus beginnt mit Rot, damit ``offset_s = 0``
    zur Zeit 0 die ungünstigste Ankunft ist und der Test dafür eine
    bekannte Antwort hat.
    """
    phase = (t_s + offset_s) % CYCLE_S
    return RED_S - phase if phase < RED_S else 0.0


def place(route, extra_seed: int = 0) -> list[TrafficLight]:
    """Ampeln auf einer Strecke verteilen — deterministisch aus ihrem Namen.

    Deterministisch heißt hier wirklich deterministisch: gleicher Name,
    gleiche Länge, gleiche Ampeln, in jedem Prozess und nach jedem
    Neustart. Pythons ``hash()`` wäre dafür untauglich — es ist je
    Prozess gesalzen —, deshalb CRC-32.

    Gezogen wird großzügig und dann gefiltert, statt zu versuchen, die
    Bedingungen beim Ziehen einzuhalten: Die Filter (Mindestabstand,
    Fenstergrenze, kein Anstieg, keine Höhe) sind einfach zu prüfen und
    schwer einzuhalten, und ein Kandidat, der durchfällt, kostet nichts.
    """
    distance_m = float(route.distance_m)
    usable = distance_m - 2.0 * EDGE_CLEARANCE_M
    if usable <= MIN_GAP_M:
        return []

    target = int(distance_m / 1000.0 / 100.0 * PER_100_KM)
    if target <= 0:
        return []

    key = zlib.crc32(route.name.encode("utf-8")) ^ (int(distance_m) & 0xFFFFFFFF)
    rng = np.random.default_rng(np.random.SeedSequence(key + extra_seed))

    # Vier Kandidaten je Ampel: Genug, damit die Filter nicht die halbe
    # Strecke leerräumen, und wenig genug, dass es eine Zeile bleibt.
    candidates = np.sort(
        rng.uniform(EDGE_CLEARANCE_M, distance_m - EDGE_CLEARANCE_M, size=target * 4)
    )
    climbs = [(c.dist_start_m, c.dist_end_m) for c in route.climbs]

    accepted: list[float] = []
    for pos in candidates:
        if len(accepted) >= target:
            break
        if accepted and pos - accepted[-1] < MIN_GAP_M:
            continue
        if len(accepted) >= PER_100_KM and pos - accepted[-PER_100_KM] <= 100_000.0:
            continue
        if float(route.elevation_at(np.array([pos]))[0]) > MAX_ELEVATION_M:
            continue
        if any(start <= pos <= end for start, end in climbs):
            continue
        accepted.append(float(pos))

    offsets = rng.uniform(0.0, CYCLE_S, size=len(accepted))
    return [
        TrafficLight(idx=i, dist_m=pos, offset_s=float(offsets[i]))
        for i, pos in enumerate(accepted)
    ]
