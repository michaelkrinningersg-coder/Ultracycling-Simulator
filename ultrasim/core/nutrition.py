"""Energiehaushalt (Game-Design-Dokument, Abschnitt 6.1).

Der eigentliche Kern eines Ultra-Simulators. Alle drei Zähler des
Dokuments stehen hier:

* **Glykogen** – begrenzt, nur über Zufuhr nachfüllbar, und die Zufuhr
  ist ihrerseits durch KH-Verbrennung und Magenverträglichkeit gedeckelt
* **Fett** – praktisch unbegrenzt, trägt den Rest
* **Hydration** – Schweißrate aus Intensität, Temperatur und Luftfeuchte,
  Nachfüllung wieder durch den Magen begrenzt

Hydration kam bewusst erst mit dem Wettermodell dazu: Ohne Temperatur
wäre die Schweißrate eine Konstante und damit nichts als ein linearer
Zeitabzug für alle.

Die interessante Eigenschaft dieses Modells ist, dass die Zufuhr eine
**absolute** Obergrenze hat, der Verbrauch aber mit der Leistung
skaliert. Ein starker Fahrer kann nicht proportional mehr essen. Auf
langen Distanzen bremst die Energie deshalb die Starken härter als die
Schwachen – und Fettverbrennung wird genau dort zur Waffe.
"""

from __future__ import annotations

import numpy as np

#: Wirkungsgrad des Menschen auf dem Rad: rund ein Viertel der
#: aufgewendeten Energie landet in der Kurbel.
GROSS_EFFICIENCY = 0.24
KCAL_PER_KJ = 1.0 / 4.184
CARB_KCAL_PER_G = 4.0

#: Substratverteilung nach Abschnitt 6.1. Der KH-Anteil steigt linear mit
#: der relativen Intensität; die drei Stützpunkte des Dokuments
#: (55 % -> 40 %, 75 % -> 65 %, 90 % -> 85 %) liegen exakt auf dieser
#: Geraden.
CARB_FRACTION_A = -0.307
CARB_FRACTION_B = 1.2857
#: Verschiebung durch das Attribut Fettverbrennung (±10 Prozentpunkte).
CARB_FRACTION_FAT_SHIFT = 0.10
CARB_FRACTION_CLIP = (0.05, 0.98)

#: Glykogenspeicher in kcal je kg Körpergewicht, plus Anteil aus Ausdauer.
#: Ergibt bei 70 kg rund 1700–1950 kcal (Dokument: 1600–2200).
GLYCOGEN_KCAL_PER_KG = 20.0
GLYCOGEN_KCAL_PER_KG_ENDURANCE = 8.0

#: Maximale KH-Oxidationsrate in g/h, aus dem Attribut
#: Kohlenhydratverbrennung (Dokument: real 60–120 g/h).
OXIDATION_G_H = (60.0, 120.0)
#: Was der Magen tatsächlich durchlässt, aus Magenverträglichkeit.
GUT_G_H = (45.0, 115.0)

#: Unter diesem Füllstand beginnt der Hungerast …
BONK_THRESHOLD = 0.15
#: … und bei leerem Speicher bleibt nur noch dieser Anteil der Leistung.
BONK_FLOOR = 0.70

#: So viel vom Speicher darf der Rennplan über die Distanz einplanen.
#: Der Rest ist Reserve für Anstiege und Fehleinschätzungen.
PLANNED_DRAWDOWN = 0.75


def metabolic_kcal(work_kj: np.ndarray) -> np.ndarray:
    """Stoffwechselenergie zu einer geleisteten Arbeit.

    200 W über eine Stunde sind 720 kJ an der Kurbel und damit rund
    717 kcal Stoffwechselleistung – der Wert, den man aus jedem
    Trainingsgerät kennt.
    """
    return np.asarray(work_kj) * KCAL_PER_KJ / GROSS_EFFICIENCY


def carb_fraction(intensity: np.ndarray, fat_norm: np.ndarray) -> np.ndarray:
    """Anteil der Kohlenhydrate an der Energiebereitstellung."""
    base = CARB_FRACTION_A + CARB_FRACTION_B * np.asarray(intensity)
    return np.clip(base - CARB_FRACTION_FAT_SHIFT * np.asarray(fat_norm), *CARB_FRACTION_CLIP)


def glycogen_capacity_kcal(weight_kg: np.ndarray, ausdauer: np.ndarray) -> np.ndarray:
    per_kg = GLYCOGEN_KCAL_PER_KG + GLYCOGEN_KCAL_PER_KG_ENDURANCE * (np.asarray(ausdauer) / 100.0)
    return per_kg * np.asarray(weight_kg)


def oxidation_ceiling_g_h(kohlenhydratverbrennung: np.ndarray) -> np.ndarray:
    lo, hi = OXIDATION_G_H
    return lo + (hi - lo) * (np.asarray(kohlenhydratverbrennung) / 100.0)


def gut_ceiling_g_h(magenvertraeglichkeit: np.ndarray) -> np.ndarray:
    lo, hi = GUT_G_H
    return lo + (hi - lo) * (np.asarray(magenvertraeglichkeit) / 100.0)


def intake_ceiling_g_h(
    kohlenhydratverbrennung: np.ndarray, magenvertraeglichkeit: np.ndarray
) -> np.ndarray:
    """Was tatsächlich ankommt: das Minimum aus Verwertung und Aufnahme.

    Verpflegungsmenge ist im supported-Betrieb planbar, die
    Aufnahmefähigkeit bleibt die Grenze – deshalb ist die
    Magenverträglichkeit das wichtigste Ernährungsattribut.
    """
    return np.minimum(
        oxidation_ceiling_g_h(kohlenhydratverbrennung), gut_ceiling_g_h(magenvertraeglichkeit)
    )


def carb_burn_g_h(power_w: np.ndarray, intensity: np.ndarray, fat_norm: np.ndarray) -> np.ndarray:
    """Kohlenhydratverbrauch in Gramm pro Stunde bei gegebener Leistung."""
    kcal_h = metabolic_kcal(np.asarray(power_w) * 3.6)  # W -> kJ/h -> kcal/h
    return kcal_h * carb_fraction(intensity, fat_norm) / CARB_KCAL_PER_G


def sustainable_intensity(
    ftp_w: float,
    intake_g_h: float,
    glycogen_kcal: float,
    duration_h: float,
    fat_norm: float,
) -> float:
    """Intensität, die der Energiehaushalt über die Distanz trägt.

    Gesucht ist das IF, bei dem der KH-Verbrauch gerade noch von Zufuhr
    plus geplanter Speicherentnahme gedeckt wird:

        c · IF · (a + b · IF) = Zufuhr + Entnahme

    Weil der KH-Anteil linear im IF ist, wird daraus eine quadratische
    Gleichung mit geschlossener Lösung – kein Löser, kein Iterieren, und
    im Rennplan beliebig oft aufrufbar.
    """
    duration_h = max(duration_h, 0.1)
    drawdown_g_h = PLANNED_DRAWDOWN * glycogen_kcal / CARB_KCAL_PER_G / duration_h
    supply = intake_g_h + drawdown_g_h

    c = metabolic_kcal(ftp_w * 3.6) / CARB_KCAL_PER_G  # g/h je Einheit IF
    if c <= 0:
        return 1.0
    a = CARB_FRACTION_A - CARB_FRACTION_FAT_SHIFT * fat_norm
    b = CARB_FRACTION_B

    # b·IF² + a·IF − supply/c = 0
    disc = a * a + 4.0 * b * (supply / c)
    if disc <= 0:
        return 0.0
    return float((-a + np.sqrt(disc)) / (2.0 * b))


def bonk_factor(glycogen_fraction: np.ndarray) -> np.ndarray:
    """Leistungseinbruch bei leerem Speicher (der „Hungerast").

    Fällt Glykogen unter 15 %, sinkt die haltbare Leistung hart – bei
    ganz leerem Speicher bleibt nur noch der Fettstoffwechsel. Der
    Übergang ist linear statt schlagartig, sonst springt die
    Geschwindigkeit in einem einzigen Tick.
    """
    frac = np.clip(np.asarray(glycogen_fraction), 0.0, 1.0)
    ramp = np.clip(frac / BONK_THRESHOLD, 0.0, 1.0)
    return BONK_FLOOR + (1.0 - BONK_FLOOR) * ramp


# ----------------------------------------------------------------------
# Hydration (Abschnitt 6.1, dritter Zähler)
# ----------------------------------------------------------------------
# Erst mit dem Wettermodell sinnvoll: Ohne Temperatur wäre die Schweißrate
# eine Konstante und damit nichts als ein linearer Zeitabzug für alle.

#: Schweißrate in Litern je Stunde: Grundumsatz plus Anteil aus der
#: Intensität. Bei 70 % FTP und 20 °C ergibt das rund 1,2 l/h – der
#: Bereich, den man aus Schweißtests kennt.
SWEAT_BASE_L_H = 0.35
SWEAT_PER_INTENSITY_L_H = 1.05
#: Zuschlag je Grad über 20 °C …
SWEAT_PER_C_WARM = 0.055
#: … und Abschlag je Grad darunter. Die Kurve ist bewusst unsymmetrisch:
#: Kühle senkt den Flüssigkeitsverlust, aber nicht auf null – der Körper
#: verliert auch bei 5 °C über Atmung und Grundumsatz Wasser.
SWEAT_PER_C_COOL = 0.030
SWEAT_TEMP_CLIP = (0.35, 2.5)
#: Feuchte Luft kühlt schlechter, also wird mehr geschwitzt. Das gilt nur
#: in der Wärme: Bei 8 °C und Regen ist Verdunstung nicht der Engpass,
#: und ein Fahrer, der im Kalten literweise Wasser verliert, wäre der
#: sichtbarste Modellfehler überhaupt.
SWEAT_HUMIDITY_GAIN = 0.30
SWEAT_HUMIDITY_FROM_C = 20.0

#: Was der Magen an Flüssigkeit durchlässt, aus Magenverträglichkeit.
DRINK_CEILING_L_H = (0.70, 1.50)

#: Bis zu diesem Verlust in Prozent des Körpergewichts passiert nichts …
DEHYDRATION_DEADBAND_PCT = 2.0
#: … danach kostet jedes weitere Prozent so viel Leistung.
DEHYDRATION_LOSS_PER_PCT = 0.02
#: Anzeigebereich: 100 % = frisch, 0 % = 4 % Körpergewicht verloren.
DEHYDRATION_DISPLAY_MAX_PCT = 4.0


def sweat_rate_l_h(
    intensity: np.ndarray, temp_c: np.ndarray, humidity: float, heat_norm: np.ndarray
) -> np.ndarray:
    """Schweißrate aus Intensität, Temperatur und Luftfeuchte.

    Das Attribut Hitzetoleranz wirkt hier zweischneidig, genau wie in der
    Realität: Wer gut hitzeangepasst ist, schwitzt *früher und mehr* –
    das ist der Kühlmechanismus – und verliert dafür weniger Leistung.
    Die Trinkmenge wird dadurch zum Engpass, nicht die Hitze selbst.
    """
    temp = np.asarray(temp_c)
    base = SWEAT_BASE_L_H + SWEAT_PER_INTENSITY_L_H * np.clip(intensity, 0.0, 1.5)
    delta = temp - 20.0
    slope = np.where(delta >= 0.0, SWEAT_PER_C_WARM, SWEAT_PER_C_COOL)
    heat = np.clip(1.0 + slope * delta, *SWEAT_TEMP_CLIP)
    damp = 1.0 + SWEAT_HUMIDITY_GAIN * max(humidity - 0.5, 0.0) * 2.0 * np.clip(
        (temp - SWEAT_HUMIDITY_FROM_C) / 10.0, 0.0, 1.0
    )
    return base * heat * damp * (1.0 + 0.15 * np.asarray(heat_norm))


def drink_ceiling_l_h(magenvertraeglichkeit: np.ndarray) -> np.ndarray:
    lo, hi = DRINK_CEILING_L_H
    return lo + (hi - lo) * (np.asarray(magenvertraeglichkeit) / 100.0)


def hydration_factor(deficit_pct: np.ndarray) -> np.ndarray:
    """Leistungsfaktor aus dem Flüssigkeitsdefizit.

    Ab −2 % Körpergewicht rund −2 % Leistung je weiterem Prozent.
    Darunter exakt 1,0 – ein bisschen Durst kostet nichts.
    """
    over = np.maximum(np.asarray(deficit_pct) - DEHYDRATION_DEADBAND_PCT, 0.0)
    return np.maximum(1.0 - DEHYDRATION_LOSS_PER_PCT * over, 0.80)


def hydration_display_pct(deficit_pct: np.ndarray) -> np.ndarray:
    """Anzeigewert 100 (frisch) bis 0 (4 % Körpergewicht verloren)."""
    ratio = np.clip(np.asarray(deficit_pct) / DEHYDRATION_DISPLAY_MAX_PCT, 0.0, 1.0)
    return (1.0 - ratio) * 100.0
