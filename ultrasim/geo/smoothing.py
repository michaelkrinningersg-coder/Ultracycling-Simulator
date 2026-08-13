"""Savitzky-Golay-Glättung in reinem NumPy.

Bewusst ohne SciPy: das spart im PyInstaller-Bundle rund 60 MB
(siehe Game-Design-Dokument, Abschnitt 13).
"""

from __future__ import annotations

import numpy as np

__all__ = ["savgol_coeffs", "savgol_filter", "moving_median"]


def savgol_coeffs(window: int, order: int) -> np.ndarray:
    """Faltungskoeffizienten eines Savitzky-Golay-Filters.

    Die Koeffizienten ergeben sich aus der Least-Squares-Lösung einer
    Polynomanpassung vom Grad ``order`` über ein Fenster von ``window``
    Punkten, ausgewertet in der Fenstermitte.
    """
    if window % 2 == 0:
        raise ValueError("window muss ungerade sein")
    if window <= order:
        raise ValueError("window muss groesser als order sein")
    half = window // 2
    positions = np.arange(-half, half + 1, dtype=np.float64)
    design = np.vander(positions, order + 1, increasing=True)
    # Zeile 0 der Pseudoinversen ist der gesuchte Faltungskern.
    return np.linalg.pinv(design)[0]


def savgol_filter(y: np.ndarray, window: int, order: int) -> np.ndarray:
    """Savitzky-Golay-Filter mit polynomialer Randbehandlung.

    Im Inneren die übliche Faltung. An den Rändern wird das Polynom an
    die äußersten ``window`` Punkte angepasst und an den Randpositionen
    ausgewertet, statt die Reihe künstlich zu verlängern.

    Warum nicht spiegeln: Eine Spiegelung erzwingt am Rand eine
    Symmetrie, die die Daten nicht haben, und verbiegt dort selbst eine
    saubere Parabel. Bei einer Route, die auf einer Passhöhe endet, wäre
    genau der letzte Kilometer betroffen – also der, auf den es ankommt.
    Die Polynomanpassung reproduziert dagegen jedes Polynom bis zur
    Filterordnung exakt, auch am Rand.
    """
    y = np.asarray(y, dtype=np.float64)
    if y.ndim != 1:
        raise ValueError("nur 1D-Reihen")
    if window % 2 == 0:
        window += 1
    if y.size < window:
        # Zu kurz zum Filtern – unverändert zurückgeben.
        return y.copy()

    half = window // 2
    # np.convolve mit umgedrehtem Kern == Korrelation mit dem Kern.
    out = np.convolve(y, savgol_coeffs(window, order)[::-1], mode="same")

    positions = np.arange(-half, half + 1, dtype=np.float64)
    design = np.vander(positions, order + 1, increasing=True)
    pinv = np.linalg.pinv(design)
    edge = np.arange(half, dtype=np.float64)
    out[:half] = np.vander(edge - half, order + 1, increasing=True) @ (pinv @ y[:window])
    out[-half:] = np.vander(edge + 1, order + 1, increasing=True) @ (pinv @ y[-window:])
    return out


def moving_median(y: np.ndarray, window: int) -> np.ndarray:
    """Gleitender Median – Vorstufe gegen einzelne Ausreißer.

    Entfernt DEM-Ausreißer (Brücken, Tunnel, GPS-Sprünge), bevor der
    SG-Filter das verbleibende Rauschen glättet. Ein Median ist dafür das
    richtige Werkzeug, weil er einen einzelnen Ausreißer vollständig
    verwirft, statt ihn wie ein Mittelwert über das Fenster zu verteilen.
    """
    y = np.asarray(y, dtype=np.float64)
    if window % 2 == 0:
        window += 1
    half = window // 2
    if y.size <= half:
        return y.copy()
    padded = np.pad(y, half, mode="edge")
    strides = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(strides, axis=-1)
