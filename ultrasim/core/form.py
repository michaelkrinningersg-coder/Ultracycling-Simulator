"""Formmodell (Game-Design-Dokument, Abschnitt 5.4).

    FTP_eff = FTP_basis · f_saison · f_tag · f_abschnitt · f_ermüdung · f_umwelt

Drei stochastische Ebenen mit sehr unterschiedlicher Zeitkonstante. Die
mittlere davon – die Abschnittsform – ist der Grund, warum ein Rennen
Phasen hat statt Rauschen.
"""

from __future__ import annotations

import numpy as np

from .rider import Rider

#: Streuung der Tagesform (Abschnitt 5.4: Band 0,93–1,07).
DAY_FORM_SD_MIN = 0.007
DAY_FORM_SD_MAX = 0.028
DAY_FORM_CLIP = (0.93, 1.07)

#: Stationäre Streuung der Abschnittsform und ihr Band.
SECTION_FORM_SD = 0.013
SECTION_FORM_CLIP = (0.96, 1.04)
#: Stützstellenabstand des OU-Prozesses.
SECTION_GRID_M = 500.0


def correlation_length_m(route_distance_m: float) -> float:
    """Korrelationslänge der Abschnittsform.

    Sie muss mit der Streckenlänge skalieren, sonst mittelt sie sich weg:
    Ein Prozess mit 5 km Korrelationslänge verschwindet über 500
    Abschnitte statistisch zu null und hat auf die Endzeit keinen
    Einfluss mehr. Bei 0,06 × Streckenlänge bleiben pro Rennen rund 17
    unabhängige Phasen übrig – dann macht es einen sichtbaren
    Unterschied, ob ein Fahrer seine schlechte Phase im Flachen oder im
    Schlussanstieg hat.
    """
    return float(np.clip(0.06 * route_distance_m, 40_000.0, 200_000.0))


def day_form_sd(konstanz: float) -> float:
    """Streuung der Tagesform, invers zum Attribut Konstanz."""
    return DAY_FORM_SD_MAX + (DAY_FORM_SD_MIN - DAY_FORM_SD_MAX) * (konstanz / 100.0)


def draw_day_form(riders: list[Rider], rngs: list[np.random.Generator]) -> np.ndarray:
    """Tagesform je Fahrer – eine Ziehung am Renntag."""
    out = np.empty(len(riders), dtype=np.float64)
    for i, (rider, rng) in enumerate(zip(riders, rngs, strict=True)):
        sd = day_form_sd(rider.attr("konstanz"))
        out[i] = np.clip(rng.normal(1.0, sd), *DAY_FORM_CLIP)
    return out


def build_section_form(
    n_riders: int,
    route_distance_m: float,
    rngs: list[np.random.Generator],
    grid_m: float = SECTION_GRID_M,
) -> tuple[np.ndarray, float]:
    """Abschnittsform als Ornstein-Uhlenbeck-Prozess über die Distanz.

    Rückgabe: Array ``(n_riders, n_grid)`` und die Rasterweite.

    Die exakte Diskretisierung des OU-Prozesses,

        x_{k+1} = x_k · e^(−Δ/L) + σ · sqrt(1 − e^(−2Δ/L)) · z ,

    ist stationär – die Streuung hängt also nicht von der Rasterweite ab.
    Das ist wichtig, weil sonst eine feinere Auflösung stillschweigend
    das Balancing verschieben würde.
    """
    length = correlation_length_m(route_distance_m)
    n_grid = int(route_distance_m // grid_m) + 2
    decay = float(np.exp(-grid_m / length))
    kick = SECTION_FORM_SD * float(np.sqrt(1.0 - decay**2))

    out = np.empty((n_riders, n_grid), dtype=np.float64)
    for i, rng in enumerate(rngs):
        noise = rng.normal(0.0, 1.0, n_grid)
        x = np.empty(n_grid)
        x[0] = SECTION_FORM_SD * noise[0]  # stationärer Startwert
        for k in range(1, n_grid):
            x[k] = x[k - 1] * decay + kick * noise[k]
        out[i] = x
    return np.clip(1.0 + out, *SECTION_FORM_CLIP), grid_m


def section_form_at(track: np.ndarray, dist_m: np.ndarray, grid_m: float) -> np.ndarray:
    """Abschnittsform an der aktuellen Position, je Fahrer."""
    idx = np.clip((dist_m / grid_m).astype(np.int64), 0, track.shape[1] - 1)
    return track[np.arange(track.shape[0]), idx]
