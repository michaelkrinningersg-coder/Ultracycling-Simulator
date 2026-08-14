"""Physikmodell (Game-Design-Dokument, Abschnitt 4).

Alle Funktionen arbeiten vektorisiert über das gesamte Feld: die
Eingaben sind Arrays der Länge ``n_riders``. Bei 250 Fahrern ist die
Feldgröße praktisch gratis – die Schleifenlänge ist die Tick-Anzahl,
nicht die Fahrerzahl (Abschnitt 8.1).
"""

from __future__ import annotations

import numpy as np

G = 9.80665
#: Antriebsstrangverluste.
DRIVETRAIN_EFFICIENCY = 0.975
#: Spezifische Gaskonstante trockener Luft.
R_SPEC = 287.058

#: Rollwiderstandsbeiwerte nach Oberfläche (Abschnitt 4.4).
CRR: dict[str, float] = {
    "asphalt_good": 0.0040,
    "asphalt_rough": 0.0055,
    "gravel": 0.0090,
    "cobbles": 0.0110,
}

#: Positionsfaktoren auf die Frontalfläche. CdA = k · A_frontal.
#: Kalibriert an den Richtwerten aus Abschnitt 4.4: mit A ≈ 0,257 m²
#: (180 cm / 70 kg) ergibt k=0,90 -> 0,23 (Zeitfahrposition),
#: k=1,20 -> 0,31 (Unterlenker), k=1,45 -> 0,37 (Anstieg/Oberlenker).
K_POSITION: dict[str, float] = {
    "tt": 0.90,
    "drops": 1.20,
    "climbing": 1.45,
}

#: Rad-Kenngrößen (Abschnitt 6.4).
BIKES: dict[str, dict[str, float]] = {
    "road": {"mass_kg": 7.5, "cda_factor": 1.00, "steep_penalty": 0.0},
    "tt": {"mass_kg": 9.0, "cda_factor": 0.80, "steep_penalty": 0.04},
}
BIKE_ROAD = 0
BIKE_TT = 1
BIKE_NAMES = ("road", "tt")

#: Gepäck im supported-Betrieb: das Meiste liegt im Begleitfahrzeug.
SUPPORTED_LUGGAGE_KG = 2.0
SUPPORTED_LUGGAGE_CDA = 0.010

#: Ab dieser Geschwindigkeit beginnt die Trittfrequenzgrenze zu greifen …
DOWNHILL_TAPER_START = 13.9  # 50 km/h
#: … und darüber tritt niemand mehr sinnvoll mit.
DOWNHILL_NO_POWER = 18.1  # 65 km/h
#: Globaler Sicherheitsdeckel gegen Ausreißer.
MAX_SPEED = 23.6  # 85 km/h
#: Untergrenze für die Antriebsrechnung (P/v ist bei v -> 0 singulär).
MIN_SPEED = 1.5
#: Haftbeiwert trocken.
MU_DRY = 0.75


#: Ab dieser Höhe kostet die dünne Luft Leistung. Darunter ist der
#: Effekt kleiner als die Streuung der Tagesform, darüber wird er
#: schnell deutlich.
ALTITUDE_THRESHOLD_M = 1500.0
#: Verlust je 1000 m über der Schwelle, für einen Fahrer mit
#: durchschnittlicher Höhenanpassung. Die Literatur nennt für
#: Ausdauerleistung grob 6–8 % je 1000 m über 1500 m; 7 % liegt
#: dazwischen und trifft auf 2500 m die oft genannten 7 %.
ALTITUDE_LOSS_PER_KM = 0.07
#: Wie stark das Attribut Höhenanpassung den Verlust dämpft oder
#: verschärft. ±50 % zwischen den Enden der Skala.
ALTITUDE_SKILL_SPAN = 0.50
#: Tiefer sinkt die Leistung nicht — auf 4000 m fährt niemand mehr
#: Rennen, aber ein Modell, das ins Bodenlose läuft, ist auch keins.
ALTITUDE_FLOOR = 0.78


def altitude_factor(
    elevation_m: np.ndarray | float, altitude_norm: np.ndarray | float = 0.0
) -> np.ndarray:
    """Leistungsfaktor aus der Höhe (Attribut ``hoehenanpassung``).

    Getrennt von ``air_density``, weil es das Gegenteil bewirkt: Dünne
    Luft macht *schneller* (weniger Luftwiderstand) und gleichzeitig
    *schwächer* (weniger Sauerstoff). Bisher stand nur die erste Hälfte
    im Modell — auf 2500 m war Höhe damit ein reiner Vorteil, und das
    Attribut Höhenanpassung ohne Wirkung.
    """
    over_km = np.maximum(np.asarray(elevation_m, dtype=np.float64) - ALTITUDE_THRESHOLD_M, 0.0)
    over_km /= 1000.0
    loss = ALTITUDE_LOSS_PER_KM * over_km
    loss = loss * (1.0 - ALTITUDE_SKILL_SPAN * np.asarray(altitude_norm, dtype=np.float64))
    return np.maximum(1.0 - loss, ALTITUDE_FLOOR)


def air_density(elevation_m: np.ndarray | float, temperature_c: np.ndarray | float = 15.0) -> np.ndarray:
    """Luftdichte aus Höhe und Temperatur.

    Höhe wirkt real spürbar: auf 2000 m fährt man bei gleicher Leistung
    im Flachen messbar schneller.
    """
    ele = np.asarray(elevation_m, dtype=np.float64)
    # Barometrische Höhenformel der Standardatmosphäre.
    pressure = 101325.0 * np.power(np.maximum(1.0 - 2.25577e-5 * ele, 1e-6), 5.25588)
    kelvin = np.asarray(temperature_c, dtype=np.float64) + 273.15
    return pressure / (R_SPEC * kelvin)


def cda_for(
    frontal_area: np.ndarray,
    position_k: np.ndarray,
    bike_cda_factor: np.ndarray,
    luggage_cda: float = SUPPORTED_LUGGAGE_CDA,
) -> np.ndarray:
    """CdA aus Körpermaßen, Position, Rad und Gepäck."""
    return frontal_area * position_k * bike_cda_factor + luggage_cda


def position_k(grade: np.ndarray, flat_attr_norm: np.ndarray) -> np.ndarray:
    """Sitzposition als weiche Funktion der Steigung.

    Im Flachen und bergab wird aerodynamisch gefahren, am Anstieg
    aufrecht. Der Übergang ist gleitend, sonst springt der CdA an jeder
    Segmentgrenze. Das Attribut *Flach* wirkt als Positionsdisziplin:
    ±3 % auf den aerodynamischen Anteil.
    """
    # 0 bei <= 1 % Steigung, 1 ab 6 %.
    blend = np.clip((grade - 0.01) / 0.05, 0.0, 1.0)
    k = K_POSITION["drops"] + blend * (K_POSITION["climbing"] - K_POSITION["drops"])
    return k * (1.0 - 0.03 * flat_attr_norm)


def slope_trig(grade: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(cos, sin) des Steigungswinkels ohne Umweg über arctan.

    Mit ``grade = tan(α)`` gilt ``cos α = 1/sqrt(1+grade²)`` und
    ``sin α = grade · cos α``. Das ist nicht nur schneller, es erlaubt
    vor allem, beides einmal je Rasterpunkt vorzurechnen – die Steigung
    hängt an der Strecke, nicht am Fahrer.
    """
    cos = 1.0 / np.sqrt(1.0 + np.asarray(grade, dtype=np.float64) ** 2)
    return cos, grade * cos


def rolling_resistance(
    crr: np.ndarray, mass: np.ndarray, grade: np.ndarray, cos_slope: np.ndarray | None = None
) -> np.ndarray:
    if cos_slope is None:
        cos_slope, _ = slope_trig(grade)
    return crr * mass * G * cos_slope


def gravity_force(
    mass: np.ndarray, grade: np.ndarray, sin_slope: np.ndarray | None = None
) -> np.ndarray:
    if sin_slope is None:
        _, sin_slope = slope_trig(grade)
    return mass * G * sin_slope


def air_force(rho: np.ndarray, cda: np.ndarray, v: np.ndarray, headwind: np.ndarray | float = 0.0) -> np.ndarray:
    """Luftwiderstand. ``headwind`` ist positiv bei Gegenwind.

    Das Vorzeichen folgt der Anströmgeschwindigkeit: bei starkem
    Rückenwind, der schneller ist als der Fahrer, schiebt die Luft.
    """
    v_air = v + headwind
    return 0.5 * rho * cda * v_air * np.abs(v_air)


def downhill_power_taper(v: np.ndarray) -> np.ndarray:
    """Anteil der Zielleistung, der bei hohem Tempo noch ankommt.

    Ohne diese Begrenzung werden Abfahrten unrealistisch schnell, weil
    der Fahrer bei 70 km/h weiter 250 W in die Kurbel drückt.
    """
    return np.clip(
        (DOWNHILL_NO_POWER - v) / (DOWNHILL_NO_POWER - DOWNHILL_TAPER_START), 0.0, 1.0
    )


#: Wie viel enger die *engste* Kurve eines Abschnitts ist als der
#: Durchschnitt. Die Kurvigkeit ist ein Mittelwert über den Abschnitt,
#: gebremst wird aber für die engste Kehre darin: Ein Abschnitt mit
#: 250 Grad je Kilometer ist selten ein gleichmäßiger Bogen von 230 m
#: Radius, sondern meist eine Gerade und eine 180-Grad-Kehre mit 15 m.
#: Der Faktor 5 ist gegenüber diesem Extremfall noch zurückhaltend.
#:
#: Ohne ihn lag das Kurvenlimit auf allen mitgelieferten Strecken über
#: 150 km/h und hat nie gebunden — Abfahrtstechnik und
#: Risikobereitschaft waren damit messbar wirkungslos.
CORNER_TIGHTNESS = 5.0


def corner_radius_m(curviness: np.ndarray) -> np.ndarray:
    """Bremswirksamer Kurvenradius aus der Kurvigkeit in Grad je km.

    Wer sich auf 1000 m um C Grad dreht, fährt im Mittel einen Radius von
    360/(2π) · 1000/C ≈ 57296/C Metern. Maßgeblich ist aber die engste
    Kurve, nicht der Mittelwert — daher ``CORNER_TIGHTNESS``.
    """
    c = np.maximum(np.asarray(curviness, dtype=np.float64), 1.0)
    return np.clip(57296.0 / c / CORNER_TIGHTNESS, 8.0, 4000.0)


def corner_speed_limit(
    curviness: np.ndarray,
    skill_norm: np.ndarray,
    risk_norm: np.ndarray,
    mu: float = MU_DRY,
) -> np.ndarray:
    """Kurvenlimit v_max = sqrt(µ · g · r)."""
    radius = corner_radius_m(curviness)
    skill = 1.0 + 0.12 * skill_norm + 0.08 * risk_norm
    return np.minimum(np.sqrt(mu * G * radius) * skill, MAX_SPEED)


def integrate_step(
    v: np.ndarray,
    power_w: np.ndarray,
    grade: np.ndarray,
    mass: np.ndarray,
    cda: np.ndarray,
    crr: np.ndarray,
    rho: np.ndarray,
    dt: float,
    headwind: np.ndarray | float = 0.0,
    v_limit: np.ndarray | float = MAX_SPEED,
    cos_slope: np.ndarray | None = None,
    sin_slope: np.ndarray | None = None,
) -> np.ndarray:
    """Ein Euler-Schritt: neue Geschwindigkeit aus der Leistungsbilanz.

        a = (P·η/v − F_roll − F_grav − F_air) / m

    Euler statt Newton-Raphson auf die kubische Gleichung: robuster, kein
    Löser nötig, und die Trägheit ist gratis mit dabei – Antritte und
    Anstiegsübergänge werden dadurch von selbst plausibel.
    """
    v_eff = np.maximum(v, MIN_SPEED)
    f_prop = power_w * DRIVETRAIN_EFFICIENCY / v_eff
    f_resist = (
        rolling_resistance(crr, mass, grade, cos_slope)
        + gravity_force(mass, grade, sin_slope)
        + air_force(rho, cda, v, headwind)
    )
    a = (f_prop - f_resist) / mass
    # Bremsbeschleunigung begrenzen: ohne Deckel schießt ein 25-%-Segment
    # die Geschwindigkeit in einem Tick ins Negative.
    a = np.clip(a, -4.0, 4.0)
    v_new = v + a * dt

    # Geschwindigkeitsdeckel (Kurve, Sicherheit) als Bremsung, nicht als
    # harter Schnitt – sonst rollt der Fahrer nach der Kurve nicht aus.
    v_new = np.minimum(v_new, v_limit)
    return np.clip(v_new, 0.5, MAX_SPEED)


def steady_state_speed(
    power_w: np.ndarray | float,
    grade: np.ndarray | float,
    mass: np.ndarray | float,
    cda: np.ndarray | float,
    crr: np.ndarray | float,
    rho: np.ndarray | float = 1.225,
    iterations: int = 40,
) -> np.ndarray:
    """Gleichgewichtsgeschwindigkeit per Bisektion.

    Wird nicht im Tick benutzt, sondern für Abschätzungen: Rennplan,
    Radwahl und Tests. Bisektion statt Newton, weil sie garantiert
    konvergiert – die Genauigkeit reicht für eine Planungsgröße allemal.
    """
    power_w = np.asarray(power_w, dtype=np.float64)
    lo = np.full_like(power_w, 0.05, dtype=np.float64)
    hi = np.full_like(power_w, MAX_SPEED * 1.5, dtype=np.float64)
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        resist = (
            rolling_resistance(np.asarray(crr), np.asarray(mass), np.asarray(grade))
            + gravity_force(np.asarray(mass), np.asarray(grade))
            + air_force(np.asarray(rho), np.asarray(cda), mid)
        )
        need = resist * mid / DRIVETRAIN_EFFICIENCY
        too_slow = need < power_w
        lo = np.where(too_slow, mid, lo)
        hi = np.where(too_slow, hi, mid)
    return 0.5 * (lo + hi)
