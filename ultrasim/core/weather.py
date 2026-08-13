"""Wetter, Wind und Tag-Nacht (Game-Design-Dokument, Abschnitte 6.6 und 8.1.1).

Das Wettermodell ist **zweischichtig**, und das ist keine Kosmetik,
sondern die direkte Folge von Entscheidung 13:

* Die **Ortsschicht** hängt an der Position auf der Strecke — Temperatur
  nach Höhe über NN, Windexposition nach Geländeform. Sie ist für alle
  Fahrer identisch und liefert das ortsgebundene Kolorit: Der Pass ist
  immer kühler als die Ebene.
* Die **Zeitschicht** hängt an der Fahrer-Eigenzeit — Tagesgang der
  Temperatur, Regenphasen, Windverlauf. Jeder Fahrer erlebt denselben
  Ablauf, nur zu seiner eigenen Uhr.

Ohne diese Trennung hätte man die Wahl zwischen zwei schlechten
Varianten: Wetter an der Wanduhr (dann entscheidet die Startnummer über
mehrere Stunden Vorteil) oder gar kein ortsgebundenes Wetter (dann sind
alle Strecken beim Wetter austauschbar).

Stärke der Ortsschicht
----------------------
Bewusst ein Mittelweg (offener Punkt aus Abschnitt 15): Der
Höhengradient wirkt voll — 6,5 °C je 1000 m sind Physik, keine
Stellschraube. Dazu kommt eine moderate Exposition: Kuppen und Pässe
sind windiger, Talböden nachts kühler. Ein Pass wird damit spürbar rauer
als die Ebene, ohne dass allein das Wetter über die Strecke entscheidet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# --- Ortsschicht -------------------------------------------------------
#: Temperaturabnahme mit der Höhe. Standardatmosphäre, keine Stellschraube.
LAPSE_RATE_C_PER_M = 0.0065
#: Wieviel windiger eine exponierte Kuppe gegenüber dem Mittel ist.
EXPOSURE_WIND_GAIN = 0.30
#: Wieviel kälter ein Talboden nachts wird (Kaltluftsee).
VALLEY_NIGHT_COOLING_C = 2.0
#: Fenster, über das „Kuppe oder Talboden" bestimmt wird.
EXPOSURE_WINDOW_M = 5000.0

# --- Zeitschicht -------------------------------------------------------
#: Uhrzeit des Temperaturmaximums (Eigenzeit).
TEMP_PEAK_HOUR = 15.0
#: Der Wind frischt nachmittags auf und schläft nachts ein.
WIND_DIURNAL_GAIN = 0.35
WIND_PEAK_HOUR = 15.0

# --- Wirkung -----------------------------------------------------------
#: Oberhalb dieser Temperatur beginnt der Hitzemalus …
HEAT_THRESHOLD_C = 25.0
#: … mit diesem Verlust je Grad, gedämpft durch Hitzetoleranz.
HEAT_LOSS_PER_C = 0.012
#: Unterhalb dieser Temperatur beginnt der Kältemalus.
COLD_THRESHOLD_C = 8.0
COLD_LOSS_PER_C = 0.008
#: Kein Wetter darf die Leistung unter diesen Anteil drücken.
CLIMATE_FLOOR = 0.72

#: Rollwiderstand bei Nässe.
WET_CRR_GAIN = 0.18
#: Haftbeiwert trocken bzw. nass (Abschnitt 4.3).
MU_DRY = 0.75
MU_WET = 0.52
#: Sichtbedingtes Abfahrtstempo bei Nacht.
NIGHT_DESCENT_FACTOR = 0.88

#: Seitenwind erhöht den Luftwiderstand: Bei schrägem Anströmwinkel wird
#: aus der schlanken Silhouette eine Fläche. Der Wert gilt je m/s
#: Seitenwind und wird mit der Frontalfläche skaliert.
CROSSWIND_CDA_GAIN = 0.016


@dataclass
class WeatherProfile:
    """Das Wetter eines Rennens, gezogen aus dem Seed.

    Alle Zeitangaben sind Stunden der Fahrer-Eigenzeit.
    """

    #: Temperatur auf der **Bezugshöhe der Strecke**, nicht auf
    #: Meeresniveau. Wer "Hitze" einstellt, meint heiß auf dem Kurs –
    #: nicht 29 °C am Meer, aus denen auf 1200 m dann 21 °C werden.
    base_temp_c: float = 16.0
    temp_amplitude_c: float = 7.0
    wind_speed_ms: float = 3.5
    wind_from_deg: float = 250.0
    #: Langsame Drehung der Windrichtung über den Tag.
    wind_turn_deg_per_h: float = 3.0
    humidity: float = 0.6
    #: Regenphasen als (Beginn, Ende, Stärke 0–1) in Eigenzeit-Stunden.
    rain_phases: list[tuple[float, float, float]] = field(default_factory=list)
    label: str = "wechselhaft"

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "base_temp_c": round(self.base_temp_c, 1),
            "temp_amplitude_c": round(self.temp_amplitude_c, 1),
            "wind_speed_ms": round(self.wind_speed_ms, 2),
            "wind_from_deg": round(self.wind_from_deg, 1),
            "wind_turn_deg_per_h": round(self.wind_turn_deg_per_h, 2),
            "humidity": round(self.humidity, 2),
            "rain_phases": [[round(a, 2), round(b, 2), round(c, 2)] for a, b, c in self.rain_phases],
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WeatherProfile:
        data = dict(data)
        data["rain_phases"] = [tuple(p) for p in data.get("rain_phases", [])]
        return cls(**data)

    # ------------------------------------------------------------------
    def temperature_at(self, own_hour: float) -> float:
        """Tagesgang der Temperatur auf der Bezugshöhe der Strecke."""
        phase = 2.0 * math.pi * (own_hour - TEMP_PEAK_HOUR) / 24.0
        return self.base_temp_c + self.temp_amplitude_c * math.cos(phase)

    def wind_at(self, own_hour: float, elapsed_h: float) -> tuple[float, float]:
        """(Geschwindigkeit in m/s, Richtung woher in Grad) zur Eigenzeit."""
        phase = 2.0 * math.pi * (own_hour - WIND_PEAK_HOUR) / 24.0
        speed = self.wind_speed_ms * (1.0 + WIND_DIURNAL_GAIN * math.cos(phase))
        direction = (self.wind_from_deg + self.wind_turn_deg_per_h * elapsed_h) % 360.0
        return max(speed, 0.0), direction

    def rain_at(self, own_hour_total: float) -> float:
        """Regenstärke 0–1. Die Phasen laufen über die gesamte Eigenzeit."""
        for start, end, strength in self.rain_phases:
            if start <= own_hour_total < end:
                # Weiche Flanken, damit der Regen nicht schlagartig einsetzt.
                ramp = min(own_hour_total - start, end - own_hour_total, 0.5) / 0.5
                return float(strength * np.clip(ramp, 0.0, 1.0))
        return 0.0


#: Vorlagen für den Kalender-Editor. Ohne Angabe wird aus dem Seed gezogen.
PRESETS: dict[str, dict[str, Any]] = {
    "mild": {"base_temp_c": 16.0, "temp_amplitude_c": 6.0, "wind_speed_ms": 2.5, "label": "mild"},
    "hitze": {
        "base_temp_c": 29.0,
        "temp_amplitude_c": 6.0,
        "wind_speed_ms": 2.0,
        "humidity": 0.45,
        "label": "Hitze",
    },
    "kalt": {
        "base_temp_c": 5.0,
        "temp_amplitude_c": 5.0,
        "wind_speed_ms": 4.0,
        "humidity": 0.8,
        "label": "kalt",
    },
    "sturm": {
        "base_temp_c": 12.0,
        "temp_amplitude_c": 4.0,
        "wind_speed_ms": 11.0,
        "wind_turn_deg_per_h": 6.0,
        "label": "stürmisch",
    },
    "regen": {
        "base_temp_c": 11.0,
        "temp_amplitude_c": 4.0,
        "wind_speed_ms": 5.0,
        "humidity": 0.92,
        "label": "Dauerregen",
    },
}

#: Presets, bei denen es durchgehend regnet. Ohne das würde ein
#: "Dauerregen" auf einer kurzen Strecke oft gar keinen Regen ziehen –
#: die Phasenziehung ist auf lange Rennen ausgelegt.
ALWAYS_RAIN = {"regen": 0.7}


def draw_profile(
    rng: np.random.Generator,
    day_of_year: int = 172,
    duration_h: float = 12.0,
    preset: str | None = None,
    ref_elevation_m: float = 0.0,
) -> WeatherProfile:
    """Wetter eines Rennens ziehen.

    Die Jahreszeit verschiebt das Temperaturniveau; alles andere ist
    Zufall aus dem Renn-Seed. ``preset`` überschreibt die Ziehung — dafür
    ist der Kalender-Editor später der richtige Ort.

    **Preset und Ziehung meinen Verschiedenes.** Ein Preset beschreibt das
    *Rennen*: "Hitze" heißt heiß auf dem Kurs, egal ob der auf Meereshöhe
    oder auf 1800 m liegt — sonst wäre die Einstellung im Gebirge
    wirkungslos. Die Ziehung dagegen beschreibt die *Gegend* auf
    Meeresniveau und wird mit dem Standardgradienten auf die Bezugshöhe
    der Strecke heruntergerechnet. Ohne diese Umrechnung bekäme eine
    Alpenetappe auf 1874 m dieselben 22 °C wie eine Flachlandrunde, was
    einem Hitzetag am Meer entspräche — und das Feld würde auf einer als
    "mild" beschrifteten Strecke reihenweise dehydrieren.
    """
    if preset:
        if preset not in PRESETS:
            raise KeyError(f"Unbekanntes Wetter-Preset: {preset}")
        profile = WeatherProfile(**PRESETS[preset])
    else:
        # Jahresgang: Maximum um den 200. Tag.
        season = math.cos(2.0 * math.pi * (day_of_year - 200) / 365.0)
        sea_level = float(rng.normal(14.0 + 9.0 * season, 3.5))
        profile = WeatherProfile(
            base_temp_c=sea_level - LAPSE_RATE_C_PER_M * max(ref_elevation_m, 0.0),
            # Halbe Tagesschwankung. 6 K bedeutet 12 K zwischen
            # Nacht- und Nachmittagswert; 9 K ist der wolkenlose
            # Hochsommertag. Darüber wird es unglaubwürdig, und die
            # Schweißrate am Nachmittag ist zu empfindlich dafür, um
            # das durchgehen zu lassen.
            temp_amplitude_c=float(np.clip(rng.normal(6.0, 1.6), 2.0, 9.0)),
            wind_speed_ms=float(np.clip(rng.gamma(2.0, 2.0), 0.3, 14.0)),
            wind_from_deg=float(rng.uniform(0.0, 360.0)),
            wind_turn_deg_per_h=float(rng.normal(0.0, 3.0)),
            humidity=float(np.clip(rng.normal(0.65, 0.15), 0.25, 0.98)),
        )

    if preset in ALWAYS_RAIN:
        profile.rain_phases = [(0.0, duration_h * 1.2 + 1.0, ALWAYS_RAIN[preset])]
    elif not profile.rain_phases:
        profile.rain_phases = _draw_rain(rng, duration_h, profile.humidity)
    if not preset:
        profile.label = _describe(profile)
    return profile


def _draw_rain(
    rng: np.random.Generator, duration_h: float, humidity: float
) -> list[tuple[float, float, float]]:
    """Regenphasen über die Renndauer.

    Die Zahl der Phasen wächst mit der Dauer: Ein 8-Stunden-Rennen hat
    meist Glück, ein 80-Stunden-Rennen praktisch nie.
    """
    rate = max(humidity - 0.45, 0.0) * duration_h / 14.0
    n = int(rng.poisson(max(rate, 0.0)))
    phases: list[tuple[float, float, float]] = []
    for _ in range(min(n, 8)):
        start = float(rng.uniform(0.0, max(duration_h - 1.0, 1.0)))
        length = float(np.clip(rng.gamma(2.0, 1.4), 0.4, 9.0))
        strength = float(np.clip(rng.beta(2.0, 2.5), 0.1, 1.0))
        phases.append((start, start + length, strength))
    return sorted(phases)


def _describe(profile: WeatherProfile) -> str:
    parts = []
    if profile.base_temp_c >= 26:
        parts.append("heiß")
    elif profile.base_temp_c <= 7:
        parts.append("kalt")
    else:
        parts.append("mild")
    if profile.wind_speed_ms >= 9:
        parts.append("stürmisch")
    elif profile.wind_speed_ms >= 5:
        parts.append("windig")
    if profile.rain_phases:
        parts.append("mit Regen")
    return ", ".join(parts)


# ----------------------------------------------------------------------
# Ortsschicht
# ----------------------------------------------------------------------
def exposure_profile(ele_m: np.ndarray, raster_m: float) -> np.ndarray:
    """Geländeexposition je Rasterpunkt: +1 Kuppe, −1 Talboden.

    Bestimmt aus der Lage der Höhe innerhalb ihres eigenen Umfelds. Ein
    Punkt, der in einem 10-km-Fenster der höchste ist, steht exponiert;
    der tiefste liegt im Kaltluftsee.
    """
    n = ele_m.size
    if n < 3:
        return np.zeros(n)
    half = max(1, int(EXPOSURE_WINDOW_M / raster_m / 2))
    # Gleitendes Minimum und Maximum über ein Fenster, günstig über eine
    # ausgedünnte Stützstellenreihe – auf Zehntelgrade kommt es hier nicht an.
    step = max(1, half // 8)
    idx = np.arange(0, n, step)
    coarse = ele_m[idx]
    pad = max(1, half // step)
    padded = np.pad(coarse, pad, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * pad + 1)
    lo = windows.min(axis=-1)
    hi = windows.max(axis=-1)
    span = np.maximum(hi - lo, 1.0)
    rel = 2.0 * (coarse - lo) / span - 1.0
    return np.interp(np.arange(n), idx, rel)


def local_temperature(
    reference_temp_c: float,
    elevation_m: np.ndarray,
    reference_elevation_m: float,
    exposure: np.ndarray,
    is_night: bool,
) -> np.ndarray:
    """Temperatur an der Position: Höhengradient plus Talboden-Effekt.

    Bezugspunkt ist die **mittlere Höhe der Strecke**, nicht Meeresniveau.
    Der Gradient erzeugt dadurch den Kontrast *innerhalb* einer Strecke —
    Passhöhe kühler als Tal — ohne das eingestellte Wetter als Ganzes zu
    verschieben.
    """
    temp = reference_temp_c - LAPSE_RATE_C_PER_M * (
        np.asarray(elevation_m) - reference_elevation_m
    )
    if is_night:
        temp = temp - VALLEY_NIGHT_COOLING_C * np.clip(-np.asarray(exposure), 0.0, 1.0)
    return temp


def local_wind_factor(exposure: np.ndarray) -> np.ndarray:
    """Windverstärkung an exponierten Stellen."""
    return 1.0 + EXPOSURE_WIND_GAIN * np.clip(np.asarray(exposure), 0.0, 1.0)


# ----------------------------------------------------------------------
# Windzerlegung
# ----------------------------------------------------------------------
def wind_components(
    speed_ms: np.ndarray, wind_from_deg: float, bearing_deg: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Gegenwind- und Seitenwindanteil.

    ``wind_from_deg`` ist die Richtung, aus der es weht. Fährt der Fahrer
    genau dorthin, hat er vollen Gegenwind; der zurückgegebene Wert ist
    dann positiv.
    """
    angle = np.radians(wind_from_deg - np.asarray(bearing_deg))
    head = np.asarray(speed_ms) * np.cos(angle)
    cross = np.abs(np.asarray(speed_ms) * np.sin(angle))
    return head, cross


def crosswind_cda_factor(
    cross_ms: np.ndarray, frontal_area: np.ndarray, resistance_norm: np.ndarray
) -> np.ndarray:
    """Aufschlag auf den CdA durch Seitenwind.

    Bewusst über den Luftwiderstand und nicht über ein Tempolimit: Ein
    Limit, das im Flachen ohnehin nie greift, wäre wirkungslos — der
    erste Entwurf hatte genau diesen Fehler, und das Attribut
    Seitenwindfestigkeit tat dadurch schlicht nichts.

    Ein großer Fahrer bietet mehr Angriffsfläche; das Attribut federt
    genau das ab.
    """
    scale = np.asarray(frontal_area) / 0.26
    gain = CROSSWIND_CDA_GAIN * np.asarray(cross_ms) * scale
    return 1.0 + np.clip(gain * (1.0 - 0.4 * np.asarray(resistance_norm)), 0.0, 0.45)


# ----------------------------------------------------------------------
# Wirkung auf den Fahrer
# ----------------------------------------------------------------------
def climate_factor(
    temp_c: np.ndarray, heat_norm: np.ndarray, cold_norm: np.ndarray
) -> np.ndarray:
    """Leistungsfaktor aus der Temperatur.

    Zwischen den beiden Schwellen exakt 1,0 – im Wohlfühlbereich soll
    das Wetter nichts kosten.
    """
    temp = np.asarray(temp_c)
    heat = np.maximum(temp - HEAT_THRESHOLD_C, 0.0) * HEAT_LOSS_PER_C
    heat = heat * (1.0 - 0.45 * np.asarray(heat_norm))
    cold = np.maximum(COLD_THRESHOLD_C - temp, 0.0) * COLD_LOSS_PER_C
    cold = cold * (1.0 - 0.45 * np.asarray(cold_norm))
    return np.maximum(1.0 - heat - cold, CLIMATE_FLOOR)


def wet_crr_factor(rain: float, wet_norm: np.ndarray) -> np.ndarray:
    """Rollwiderstand bei Nässe."""
    return 1.0 + WET_CRR_GAIN * rain * (1.0 - 0.3 * np.asarray(wet_norm))


def surface_mu(rain: float, wet_norm: np.ndarray) -> np.ndarray:
    """Haftbeiwert. Nässe senkt µ deutlich (Abschnitt 4.3)."""
    base = MU_DRY + (MU_WET - MU_DRY) * rain
    return base * (1.0 + 0.08 * rain * np.asarray(wet_norm))


# ----------------------------------------------------------------------
# Tag und Nacht
# ----------------------------------------------------------------------
def sun_times(latitude_deg: float, day_of_year: int) -> tuple[float, float]:
    """(Sonnenaufgang, Sonnenuntergang) als Stunden der Ortszeit.

    Vereinfachte Deklinationsformel — für ein Spiel, das wissen will, ob
    es hell ist, reicht das auf wenige Minuten genau. Polartag und
    Polarnacht werden abgefangen.
    """
    decl = math.radians(23.44) * math.sin(2.0 * math.pi * (day_of_year - 81) / 365.0)
    lat = math.radians(np.clip(latitude_deg, -89.0, 89.0))
    cos_h = -math.tan(lat) * math.tan(decl)
    if cos_h <= -1.0:
        return 0.0, 24.0  # Mitternachtssonne
    if cos_h >= 1.0:
        return 12.0, 12.0  # Polarnacht
    half_day_h = math.degrees(math.acos(cos_h)) / 15.0
    return 12.0 - half_day_h, 12.0 + half_day_h


def is_daylight(own_hour: float, sunrise: float, sunset: float) -> bool:
    return sunrise <= own_hour < sunset


def night_descent_factor(daylight: bool) -> float:
    """Nachts wird langsamer abgefahren – Sicht, nicht Müdigkeit.

    Der Müdigkeitsanteil steckt getrennt davon im Schlafmodell; beide
    multiplizieren sich, wie es sich für unabhängige Ursachen gehört.
    """
    return 1.0 if daylight else NIGHT_DESCENT_FACTOR
