"""Streckenmodell und Dateiformat (Game-Design-Dokument, Abschnitte 3.4–3.6).

Eine Route ist eine reine Datei – die Simulation braucht zur Laufzeit
weder Routing-Dienst noch Kartendaten noch Netz.

Speicherformat (gzip-JSON), bewusst schlank gehalten:

* ``dist`` wird nicht gespeichert, sondern ergibt sich aus
  ``raster_m * index``
* Höhen als Dezimeter-Integer statt Fließkomma
* ``grade`` wird nicht gespeichert, sondern beim Laden gerechnet
* ``lat``/``lon`` nur alle ``coord_step_m`` Meter – sie werden für
  Sonnenstand, Windrichtung und Segmentpeilung gebraucht, nicht für die
  Physik
"""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import signals

SCHEMA_VERSION = 1

#: Halbe Basislänge der zentralen Differenz für die Steigungsberechnung,
#: in Rasterschritten. Bei 10-m-Raster entspricht 5 einer Basis von 100 m.
#:
#: Das ist keine Kosmetik: Höhen liegen als Dezimeter-Integer vor. Über
#: einen einzelnen 10-m-Schritt beträgt die Quantisierung 0,1 m / 10 m =
#: 1 % Steigung – das wäre gröber als der gesamte Effekt, den wir messen
#: wollen. Über 100 m Basis sinkt sie auf 0,1 %. Die Höhenreihe ist beim
#: Import ohnehin mit ~210 m Fenster geglättet, es geht also nichts verloren.
GRADE_HALFWIDTH_STEPS = 5

#: Steigungen jenseits davon sind in der Praxis Datenfehler.
GRADE_CLIP = 0.25

DISTANCE_CLASSES = ("kurz", "mittel", "ultra")


@dataclass(slots=True)
class Segment:
    """Simulationseinheit der Strecke (Abschnitt 3.4)."""

    idx: int
    dist_start_m: float
    length_m: float
    delta_ele_m: float
    grade: float
    ele_mid_m: float
    bearing_deg: float
    curviness: float  # Summe der Richtungsänderungen in Grad pro km
    surface: str = "asphalt_good"
    road_class: str = "unclassified"
    in_town: bool = False
    traffic_signals: int = 0
    kind: str = "flach"

    @property
    def dist_end_m(self) -> float:
        return self.dist_start_m + self.length_m


@dataclass(slots=True)
class Climb:
    """Zusammenhängender Anstieg mit abgeleiteter Kategorie (Abschnitt 3.4)."""

    idx: int
    dist_start_m: float
    dist_end_m: float
    length_m: float
    ascent_m: float
    grade_avg: float
    grade_max: float
    category: str  # "HC", "1".."4"
    score: float

    @property
    def summit_dist_m(self) -> float:
        return self.dist_end_m


@dataclass(slots=True)
class Split:
    """Zeitmesspunkt – die Telemetrie hängt vollständig an diesen Objekten."""

    idx: int
    dist_m: float
    name: str
    kind: str = "interval"  # interval | summit | control | finish


@dataclass(slots=True)
class ServicePoint:
    """Treffpunkt mit dem Begleitfahrzeug (supported, Abschnitt 6.3)."""

    idx: int
    dist_m: float
    name: str


@dataclass
class Route:
    """Fertig aufbereitete Strecke."""

    name: str
    raster_m: int
    ele_dm: np.ndarray  # int32, Höhe in Dezimetern je Rasterpunkt
    coords: np.ndarray  # float64 (K, 2) – lat/lon alle coord_step_m
    coord_step_m: int
    segments: list[Segment] = field(default_factory=list)
    climbs: list[Climb] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)
    service_points: list[ServicePoint] = field(default_factory=list)
    source: str = ""

    # --- abgeleitet, wird in __post_init__ gefüllt -------------------
    ele_m: np.ndarray = field(init=False, repr=False)
    grade: np.ndarray = field(init=False, repr=False)
    _ascent_m: float = field(init=False, repr=False, default=0.0)
    _descent_m: float = field(init=False, repr=False, default=0.0)
    #: Ampeln auf der Strecke. Nicht gespeichert, sondern beim Aufbau
    #: aus Name und Länge abgeleitet — dieselbe Strecke bekommt so in
    #: jedem Prozess dieselben Ampeln, und Streckendateien von vor
    #: dieser Mechanik funktionieren unverändert weiter.
    traffic_lights: list = field(init=False, repr=False, default_factory=list)

    def __post_init__(self) -> None:
        self.ele_dm = np.asarray(self.ele_dm, dtype=np.int32)
        self.coords = np.asarray(self.coords, dtype=np.float64).reshape(-1, 2)
        self.ele_m = self.ele_dm.astype(np.float64) / 10.0
        self.grade = compute_grade(self.ele_m, self.raster_m)
        # Einmal rechnen: die Schwellwert-Akkumulation ist sequentiell und
        # würde als Property bei jedem Zugriff über alle Rasterpunkte laufen.
        self._ascent_m = accumulate_ascent(self.ele_m)
        self._descent_m = accumulate_ascent(-self.ele_m)
        # Nach den Anstiegen: Die Platzierung braucht sie, um keine Ampel
        # in eine Rampe zu setzen.
        self.traffic_lights = signals.place(self)

    # ------------------------------------------------------------------
    # Kennzahlen
    # ------------------------------------------------------------------
    @property
    def n_points(self) -> int:
        return int(self.ele_dm.size)

    @property
    def distance_m(self) -> float:
        return float((self.n_points - 1) * self.raster_m)

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000.0

    @property
    def ascent_m(self) -> float:
        return self._ascent_m

    @property
    def descent_m(self) -> float:
        return self._descent_m

    @property
    def distance_class(self) -> str:
        return classify_distance(self.distance_km, self.ascent_m)

    # ------------------------------------------------------------------
    # Zugriff entlang der Strecke (vektorisiert über Fahrer)
    # ------------------------------------------------------------------
    def index_at(self, dist_m: np.ndarray | float) -> np.ndarray:
        """Rasterindex zu einer Distanz, geclippt auf gültigen Bereich."""
        idx = np.asarray(dist_m, dtype=np.float64) / self.raster_m
        return np.clip(idx.astype(np.int64), 0, self.n_points - 1)

    def grade_at(self, dist_m: np.ndarray | float) -> np.ndarray:
        return self.grade[self.index_at(dist_m)]

    def elevation_at(self, dist_m: np.ndarray | float) -> np.ndarray:
        return self.ele_m[self.index_at(dist_m)]

    def latlon_at(self, dist_m: np.ndarray | float) -> np.ndarray:
        """Lineare Interpolation im groben Koordinatenraster."""
        d = np.atleast_1d(np.asarray(dist_m, dtype=np.float64))
        max_d = (len(self.coords) - 1) * self.coord_step_m
        pos = np.clip(d, 0.0, max_d) / self.coord_step_m
        lo = np.clip(pos.astype(np.int64), 0, len(self.coords) - 1)
        hi = np.clip(lo + 1, 0, len(self.coords) - 1)
        frac = (pos - lo)[:, None]
        return self.coords[lo] * (1.0 - frac) + self.coords[hi] * frac

    def segment_index_array(self) -> np.ndarray:
        """Rasterpunkt -> Segmentindex, für vektorisierten Zugriff im Tick."""
        out = np.zeros(self.n_points, dtype=np.int32)
        for seg in self.segments:
            lo = int(seg.dist_start_m // self.raster_m)
            hi = int(np.ceil(seg.dist_end_m / self.raster_m))
            out[lo:hi] = seg.idx
        return out

    # ------------------------------------------------------------------
    # Persistenz
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "source": self.source,
            "raster_m": self.raster_m,
            "coord_step_m": self.coord_step_m,
            "ele_dm": [int(v) for v in self.ele_dm],
            "coords": [[round(float(a), 6), round(float(b), 6)] for a, b in self.coords],
            "segments": [asdict(s) for s in self.segments],
            "climbs": [asdict(c) for c in self.climbs],
            "splits": [asdict(s) for s in self.splits],
            "service_points": [asdict(s) for s in self.service_points],
            "stats": {
                "distance_m": round(self.distance_m, 1),
                "ascent_m": round(self.ascent_m, 1),
                "descent_m": round(self.descent_m, 1),
                "distance_class": self.distance_class,
            },
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8")
        # Gleiche Eingabe -> bytegleiche Datei. Dafür müssen zwei Dinge
        # aus dem gzip-Kopf heraus: der Zeitstempel (mtime=0) und der
        # Dateiname, den GzipFile sonst aus dem Pfad übernimmt. Sonst
        # unterscheiden sich zwei Exporte derselben Strecke, und jeder
        # Re-Import erzeugt einen Diff im Repository.
        with open(path, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as fh:
                fh.write(payload)
        return path

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Route:
        schema = int(data.get("schema", 0))
        if schema != SCHEMA_VERSION:
            raise ValueError(
                f"Streckendatei hat Schema {schema}, erwartet {SCHEMA_VERSION}. "
                "Bitte GPX neu importieren."
            )
        return cls(
            name=data["name"],
            source=data.get("source", ""),
            raster_m=int(data["raster_m"]),
            coord_step_m=int(data["coord_step_m"]),
            ele_dm=np.asarray(data["ele_dm"], dtype=np.int32),
            coords=np.asarray(data["coords"], dtype=np.float64),
            segments=[Segment(**s) for s in data.get("segments", [])],
            climbs=[Climb(**c) for c in data.get("climbs", [])],
            splits=[Split(**s) for s in data.get("splits", [])],
            service_points=[ServicePoint(**s) for s in data.get("service_points", [])],
        )

    @classmethod
    def load(cls, path: str | Path) -> Route:
        path = Path(path)
        opener = gzip.open if path.suffix == ".gz" or _is_gzip(path) else open
        with opener(path, "rb") as fh:  # type: ignore[operator]
            data = json.loads(fh.read().decode("utf-8"))
        route = cls.from_dict(data)
        if not route.source:
            route.source = str(path)
        return route


def _is_gzip(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"\x1f\x8b"
    except OSError:
        return False


# ----------------------------------------------------------------------
# Freistehende Hilfsfunktionen
# ----------------------------------------------------------------------
def compute_grade(ele_m: np.ndarray, raster_m: float) -> np.ndarray:
    """Steigung aus der geglätteten Höhenreihe, zentrale Differenz.

    Ränder werden einseitig gerechnet, damit die Länge erhalten bleibt.
    """
    ele_m = np.asarray(ele_m, dtype=np.float64)
    n = ele_m.size
    if n < 2:
        return np.zeros(n, dtype=np.float64)
    h = min(GRADE_HALFWIDTH_STEPS, max(1, (n - 1) // 2))
    idx = np.arange(n)
    lo = np.clip(idx - h, 0, n - 1)
    hi = np.clip(idx + h, 0, n - 1)
    d_ele = ele_m[hi] - ele_m[lo]
    d_dist = (hi - lo) * raster_m
    grade = np.divide(d_ele, d_dist, out=np.zeros(n), where=d_dist > 0)
    return np.clip(grade, -GRADE_CLIP, GRADE_CLIP)


def accumulate_ascent(ele_m: np.ndarray, threshold_m: float = 2.0) -> float:
    """Höhenmeter mit Mindestschwelle.

    Ohne Schwelle summiert sich auch nach der Glättung noch jedes
    Restzittern auf und die Summe explodiert (Abschnitt 3.3).
    """
    ele_m = np.asarray(ele_m, dtype=np.float64)
    if ele_m.size < 2:
        return 0.0
    total = 0.0
    anchor = float(ele_m[0])
    for value in ele_m[1:]:
        delta = float(value) - anchor
        if delta >= threshold_m:
            total += delta
            anchor = float(value)
        elif delta <= -threshold_m:
            anchor = float(value)
    return total


def classify_distance(distance_km: float, ascent_m: float) -> str:
    """Distanzklasse aus Distanz und Höhenmetern (Abschnitt 2).

    Höhenmeter werden als Zuschlag auf die Distanz verrechnet
    (100 hm ~ 1 km), weil die Klasse die *Dauer* beschreibt, nicht die
    reine Streckenlänge: 400 km mit 6000 hm gehören nicht in dieselbe
    Schublade wie 400 km flach.
    """
    equiv = distance_km + ascent_m / 100.0
    if equiv < 400.0:
        return "kurz"
    if equiv < 1200.0:
        return "mittel"
    return "ultra"


def haversine_m(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Großkreisdistanz in Metern, vektorisiert."""
    r = 6371008.8  # mittlerer Erdradius (IUGG)
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Peilung von Punkt 1 nach Punkt 2 in Grad (0 = Nord)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return float((np.degrees(np.arctan2(y, x)) + 360.0) % 360.0)


def bearing_series(coords: np.ndarray) -> np.ndarray:
    """Peilung je Punkt einer lat/lon-Reihe (letzter Wert wiederholt)."""
    coords = np.asarray(coords, dtype=np.float64)
    if len(coords) < 2:
        return np.zeros(len(coords))
    p1 = np.radians(coords[:-1, 0])
    p2 = np.radians(coords[1:, 0])
    dl = np.radians(coords[1:, 1] - coords[:-1, 1])
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    brg = (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0
    return np.append(brg, brg[-1])


def angular_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Kleinste Winkeldifferenz in Grad, immer 0..180."""
    d = np.abs(np.asarray(a) - np.asarray(b)) % 360.0
    return np.where(d > 180.0, 360.0 - d, d)
