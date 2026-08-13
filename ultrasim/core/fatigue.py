"""Ermüdung: W′ und Langzeitermüdung (Game-Design-Dokument, Abschnitt 5.5).

Zwei gekoppelte Systeme mit sehr unterschiedlicher Zeitkonstante:

* **W′** – anaerobe Kapazität im Bereich von Minuten. Regelt Steilrampen
  und Antritte.
* **Langzeitermüdung** – die haltbare Leistung sinkt mit der kumulierten
  Arbeit. Das ist der eigentliche Ultra-Effekt und wirkt über Stunden.
"""

from __future__ import annotations

import numpy as np

# --- W' ---------------------------------------------------------------
#: Grundwert der anaeroben Kapazität in Joule …
W_PRIME_BASE_J = 12_000.0
#: … plus dieser Anteil, skaliert mit Spritzigkeit.
W_PRIME_SPAN_J = 14_000.0
#: Zeitkonstante der Wiederauffüllung unterhalb der Schwelle.
W_PRIME_TAU_S = 400.0
#: Unterhalb dieses Füllstands wird nicht mehr über der Schwelle gefahren.
W_PRIME_GUARD = 0.20

# --- Langzeitermüdung -------------------------------------------------
#: Kalibriert auf: ~8.300 kJ (300 km) -> f ≈ 0,88 · ~70.000 kJ (2500 km)
#: -> f ≈ 0,55. Siehe tests/test_fatigue.py, das diese Eckpunkte festhält.
FATIGUE_K = 0.328
FATIGUE_P = 0.62
FATIGUE_FLOOR = 0.45

WORK_CAPACITY_BASE_KJ = 26_000.0
WORK_CAPACITY_ENDURANCE_KJ = 26_000.0
WORK_CAPACITY_REGEN_KJ = 6_000.0
REFERENCE_MASS_KG = 70.0


def w_prime_capacity(spritzigkeit: np.ndarray, weight_kg: np.ndarray) -> np.ndarray:
    """Anaerobe Kapazität in Joule."""
    base = W_PRIME_BASE_J + W_PRIME_SPAN_J * (np.asarray(spritzigkeit) / 100.0)
    return base * np.power(np.asarray(weight_kg) / REFERENCE_MASS_KG, 0.8)


def w_prime_step(
    balance_j: np.ndarray,
    capacity_j: np.ndarray,
    power_w: np.ndarray,
    threshold_w: np.ndarray,
    dt: float,
    tau_s: np.ndarray | float = W_PRIME_TAU_S,
) -> np.ndarray:
    """Ein Zeitschritt der W′-Bilanz.

    Über der Schwelle entlädt sich W′ mit der Überleistung, darunter füllt
    es sich exponentiell wieder auf.
    """
    over = power_w - threshold_w
    discharge = np.maximum(over, 0.0) * dt
    recharge = np.where(over < 0.0, (capacity_j - balance_j) / tau_s * dt, 0.0)
    return np.clip(balance_j - discharge + recharge, 0.0, capacity_j)


def work_capacity_kj(
    ausdauer: np.ndarray, regeneration: np.ndarray, weight_kg: np.ndarray
) -> np.ndarray:
    """Bezugsgröße der Langzeitermüdung in Kilojoule."""
    base = (
        WORK_CAPACITY_BASE_KJ
        + WORK_CAPACITY_ENDURANCE_KJ * (np.asarray(ausdauer) / 100.0)
        + WORK_CAPACITY_REGEN_KJ * (np.asarray(regeneration) / 100.0)
    )
    return base * (np.asarray(weight_kg) / REFERENCE_MASS_KG)


def fatigue_factor(work_done_kj: np.ndarray, capacity_kj: np.ndarray) -> np.ndarray:
    """f_ermüdung = 1 − k · (kJ_kumuliert / kJ_kapazität)^p.

    Der Exponent unter 1 sorgt dafür, dass die ersten Stunden
    überproportional zuschlagen und die Kurve danach abflacht – genau der
    Verlauf, den man aus Langstreckendaten kennt.
    """
    ratio = np.maximum(np.asarray(work_done_kj), 0.0) / np.maximum(capacity_kj, 1.0)
    return np.maximum(1.0 - FATIGUE_K * np.power(ratio, FATIGUE_P), FATIGUE_FLOOR)
