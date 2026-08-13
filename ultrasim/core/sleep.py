"""Schlafdruck und zirkadianer Rhythmus (Game-Design-Dokument, Abschnitt 6.2).

Die entscheidende Kalibrierung dieses Moduls ist eine **Nicht**-Wirkung:
34 Stunden am Stück ohne Schlaf sind im Ultracycling normal, nicht die
Ausnahme. Ein Modell, das den Fahrer schon nach einer Nacht einbrechen
lässt, ist falsch — und zwar auf eine Weise, die genau die Distanzklasse
kaputtmacht, um die es geht.

Der Malus setzt deshalb erst bei rund 60 % der persönlichen Wachhorizonts
ein und bleibt bis dahin exakt null. Wirklich weh tut nicht die erste
Nacht, sondern die zweite: Dann treffen ein hoher Grundwert und der
zirkadiane Tiefpunkt aufeinander, und ihr Produkt fällt in den steilen
Teil der Kurve.

**Alles hier rechnet in Fahrer-Eigenzeit** (Entscheidung 13). Weil jeder
Fahrer in seinem persönlichen „08:00" startet, ist der zirkadiane Faktor
ein einzelner Skalar je Tick statt eines Vektors über das Feld — die
Tageszeit-Lotterie eines 125-Stunden-Startfensters gibt es schlicht nicht.
"""

from __future__ import annotations

import numpy as np

#: Wachhorizont in Stunden bei Schlaftoleranz 0 bzw. 100. Ein Fahrer mit
#: mittlerer Toleranz kommt also 40 Stunden weit, bevor der Druck den
#: Wert 1 erreicht.
WAKE_HORIZON_H = (30.0, 50.0)

#: Unterhalb dieses Drucks gibt es keinerlei Malus. 0,6 × 40 h = 24 h –
#: eine durchfahrene Nacht kostet damit nichts.
PRESSURE_DEADBAND = 0.6
#: Steilheit und Exponent des Malus oberhalb der Totzone.
PRESSURE_K = 0.30
PRESSURE_EXP = 1.5
#: Tiefster Punkt, auf den der Schlafmangel die Leistung drücken kann.
SLEEP_FLOOR = 0.70

#: Zirkadianer Tiefpunkt: Mitte und Breite in Stunden der Eigenzeit.
CIRCADIAN_LOW_HOUR = 3.5
CIRCADIAN_WIDTH_H = 2.0
#: Um so viel verstärkt der Tiefpunkt den vorhandenen Schlafdruck.
CIRCADIAN_AMPLITUDE = 0.55

#: Ab diesem effektiven Druck geht nichts mehr: Notschlaf am Straßenrand.
FORCED_SLEEP_PRESSURE = 1.8
FORCED_SLEEP_S = (2400.0, 5400.0)  # 40–90 min

#: Schlafqualität: Mittelwert bei Regeneration 0 bzw. 100.
SLEEP_QUALITY = (0.55, 0.95)
SLEEP_QUALITY_SD = 0.14
#: Unter dieser Güte gilt der Schlaf als schlecht und hinterlässt einen
#: Zustand (Abschnitt 6.5, „Suboptimaler Schlaf").
POOR_SLEEP_QUALITY = 0.62


def wake_horizon_h(schlaftoleranz: np.ndarray) -> np.ndarray:
    lo, hi = WAKE_HORIZON_H
    return lo + (hi - lo) * (np.asarray(schlaftoleranz) / 100.0)


def circadian_factor(own_hour: float) -> float:
    """Verstärkung des Schlafdrucks nach der persönlichen Uhrzeit.

    1,0 tagsüber, bis zu 1,55 zwischen 02:00 und 05:00. Der Abstand wird
    zyklisch gerechnet, damit die Glocke über Mitternacht nicht zerreißt.
    """
    delta = abs(((own_hour - CIRCADIAN_LOW_HOUR + 12.0) % 24.0) - 12.0)
    return 1.0 + CIRCADIAN_AMPLITUDE * float(np.exp(-((delta / CIRCADIAN_WIDTH_H) ** 2)))


def own_hour(start_time_of_day_s: float, elapsed_s: float) -> float:
    """Persönliche Uhrzeit als Stundenbruch (0–24)."""
    return ((start_time_of_day_s + elapsed_s) / 3600.0) % 24.0


def pressure(wake_h: np.ndarray, horizon_h: np.ndarray) -> np.ndarray:
    """Schlafdruck als Vielfaches des persönlichen Wachhorizonts."""
    return np.asarray(wake_h) / np.maximum(horizon_h, 1.0)


def performance_factor(effective_pressure: np.ndarray) -> np.ndarray:
    """Leistungsfaktor aus dem effektiven Schlafdruck.

    Exakt 1,0 bis zur Totzone – kein schleichender Abzug, der eine
    Kurzdistanz stillschweigend verlangsamt.
    """
    over = np.maximum(np.asarray(effective_pressure) - PRESSURE_DEADBAND, 0.0)
    return np.maximum(1.0 - PRESSURE_K * np.power(over, PRESSURE_EXP), SLEEP_FLOOR)


def descent_factor(effective_pressure: np.ndarray) -> np.ndarray:
    """Müde Fahrer fahren Abfahrten langsamer.

    Der Effekt setzt an derselben Totzone an wie der Leistungsmalus, ist
    aber ausgeprägter: Nachlassende Aufmerksamkeit kostet in der Kurve
    mehr als am Berg.
    """
    over = np.maximum(np.asarray(effective_pressure) - PRESSURE_DEADBAND, 0.0)
    return np.clip(1.0 - 0.22 * over, 0.72, 1.0)


def sleep_quality(regeneration: float, rng: np.random.Generator) -> float:
    """Güte eines Schlafstopps.

    Schlaf am Straßenrand oder im Begleitfahrzeug ist nicht das Bett zu
    Hause: Selbst ein guter Regenerierer holt nicht die volle Zeit zurück.
    """
    lo, hi = SLEEP_QUALITY
    mean = lo + (hi - lo) * (regeneration / 100.0)
    return float(np.clip(rng.normal(mean, SLEEP_QUALITY_SD), 0.30, 1.0))
