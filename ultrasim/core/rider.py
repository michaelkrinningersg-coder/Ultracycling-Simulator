"""Fahrer- und Teammodell samt Generator (Game-Design-Dokument, Abschnitt 5).

Attribute liegen auf einer Skala 0–100 mit Mittelwert 50 und wirken
grundsätzlich als Modifikatoren auf physikalische Zwischengrößen – nie
als harter Multiplikator auf die Endzeit.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .names import (
    FIRST_NAMES,
    LAST_NAMES,
    NATION_WEIGHTS,
    NATIONS,
    TEAM_PREFIXES,
    TEAM_SUFFIXES,
)

# ----------------------------------------------------------------------
# Attributkatalog
# ----------------------------------------------------------------------
#: Alle Attribute aus Abschnitt 5.2, mit Gewicht im Potenzial-Budget.
#: Das Gewicht sagt, wie teuer eine Stärke im Budget ist – nicht, wie
#: stark sie wirkt.
ATTRIBUTES: dict[str, float] = {
    # Grundattribute
    "flach": 1.0,
    "berg": 1.0,
    "ausdauer": 1.2,
    "spritzigkeit": 0.7,
    "fettverbrennung": 0.8,
    "kohlenhydratverbrennung": 0.8,
    "schlaftoleranz": 0.9,
    # Ultra-spezifisch (im Dokument mit *** priorisiert)
    "magenvertraeglichkeit": 1.0,
    "mentale_widerstandsfaehigkeit": 1.0,
    "pacing_disziplin": 1.0,
    "hitzetoleranz": 0.7,
    "regeneration": 0.9,
    "abfahrtstechnik": 0.7,
    "konstanz": 0.9,
    # zweite Reihe
    "kaeltetoleranz": 0.5,
    "naesseresistenz": 0.5,
    "sitzkomfort": 0.6,
    "risikobereitschaft": 0.3,
    "navigationssicherheit": 0.5,
    "erfahrung": 0.8,
    # dritte Reihe
    "mechanikerfaehigkeit": 0.3,
    "materialpflege": 0.3,
    "seitenwindfestigkeit": 0.4,
    "oberflaechenkompetenz": 0.4,
    "hoehenanpassung": 0.4,
}

#: Attribute, die in der aktuellen Ausbaustufe (M1–M4) tatsächlich in die
#: Simulation eingreifen. Die übrigen sind Teil des Datenmodells und
#: werden vom Generator befüllt, wirken aber erst mit den Mechaniken der
#: Meilensteine M5–M7 (Verpflegung, Schlaf, Wetter, Ereignisse).
#:
#: Diese Liste ist die ehrliche Antwort auf die Frage "was zählt gerade?"
#: und wird in der UI angezeigt.
ACTIVE_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "flach",
        "berg",
        "ausdauer",
        "spritzigkeit",
        "pacing_disziplin",
        "konstanz",
        "abfahrtstechnik",
        "risikobereitschaft",
        "erfahrung",
        "mentale_widerstandsfaehigkeit",
    }
)

#: Plausibilitätsband der Schwellenleistung. Wer hier heraus will, baut
#: keinen Fahrer mehr, sondern einen Motor.
WKG_RANGE = (3.5, 6.0)

ATTRIBUTE_LABELS: dict[str, str] = {
    "flach": "Flach",
    "berg": "Berg",
    "ausdauer": "Ausdauer",
    "spritzigkeit": "Spritzigkeit",
    "fettverbrennung": "Fettverbrennung",
    "kohlenhydratverbrennung": "KH-Verbrennung",
    "schlaftoleranz": "Schlaftoleranz",
    "magenvertraeglichkeit": "Magen",
    "mentale_widerstandsfaehigkeit": "Mental",
    "pacing_disziplin": "Pacing",
    "hitzetoleranz": "Hitze",
    "regeneration": "Regeneration",
    "abfahrtstechnik": "Abfahrt",
    "konstanz": "Konstanz",
    "kaeltetoleranz": "Kälte",
    "naesseresistenz": "Nässe",
    "sitzkomfort": "Sitzkomfort",
    "risikobereitschaft": "Risiko",
    "navigationssicherheit": "Navigation",
    "erfahrung": "Erfahrung",
    "mechanikerfaehigkeit": "Mechanik",
    "materialpflege": "Materialpflege",
    "seitenwindfestigkeit": "Seitenwind",
    "oberflaechenkompetenz": "Oberfläche",
    "hoehenanpassung": "Höhe",
}


# ----------------------------------------------------------------------
# Archetypen
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Archetype:
    """Prägung eines Fahrertyps (Abschnitt 5.3).

    ``offsets`` verschiebt einzelne Attributmittelwerte gegenüber 50,
    ``spread`` ist die Streuung der Ziehung.
    """

    key: str
    label: str
    offsets: dict[str, float]
    spread: float = 11.0
    height_bias_cm: float = 0.0
    wkg_bias: float = 0.0

    def mean_for(self, attr: str) -> float:
        return 50.0 + self.offsets.get(attr, 0.0)


ARCHETYPES: dict[str, Archetype] = {
    "zeitfahrer": Archetype(
        "zeitfahrer",
        "Zeitfahr-Spezialist",
        {"flach": 24, "berg": -16, "spritzigkeit": 8, "pacing_disziplin": 10,
         "ausdauer": -4, "konstanz": 6, "seitenwindfestigkeit": 8},
        height_bias_cm=3.0,
        wkg_bias=-0.10,
    ),
    "kletterer": Archetype(
        "kletterer",
        "Kletterer",
        {"berg": 25, "flach": -14, "spritzigkeit": 6, "hitzetoleranz": 6,
         "hoehenanpassung": 12, "seitenwindfestigkeit": -10},
        height_bias_cm=-6.0,
        wkg_bias=0.45,
    ),
    "diesel": Archetype(
        "diesel",
        "Diesel / Ultra-Maschine",
        {"ausdauer": 24, "konstanz": 20, "pacing_disziplin": 20, "spritzigkeit": -18,
         "fettverbrennung": 12, "sitzkomfort": 10, "risikobereitschaft": -8},
        spread=8.5,
        wkg_bias=-0.20,
    ),
    "schlafgeiziger": Archetype(
        "schlafgeiziger",
        "Schlafgeiziger",
        {"schlaftoleranz": 26, "mentale_widerstandsfaehigkeit": 14, "regeneration": -16,
         "navigationssicherheit": -6, "ausdauer": 6},
    ),
    "fettverbrenner": Archetype(
        "fettverbrenner",
        "Fettverbrenner",
        {"fettverbrennung": 26, "kohlenhydratverbrennung": -10, "spritzigkeit": -16,
         "magenvertraeglichkeit": 10, "ausdauer": 10},
    ),
    "draufgaenger": Archetype(
        "draufgaenger",
        "Draufgänger",
        {"risikobereitschaft": 28, "abfahrtstechnik": 20, "pacing_disziplin": -22,
         "spritzigkeit": 12, "konstanz": -14},
        spread=13.5,
    ),
    "allrounder": Archetype(
        "allrounder",
        "Allrounder",
        {},
        spread=7.5,
    ),
    "rohdiamant": Archetype(
        "rohdiamant",
        "Rohdiamant",
        {"erfahrung": -26, "konstanz": -16, "pacing_disziplin": -10, "spritzigkeit": 10,
         "regeneration": 12},
        spread=14.0,
    ),
}

#: Mischung, wenn der Generator "gemischt" erzeugen soll.
ARCHETYPE_MIX: dict[str, float] = {
    "zeitfahrer": 0.11,
    "kletterer": 0.12,
    "diesel": 0.20,
    "schlafgeiziger": 0.10,
    "fettverbrenner": 0.11,
    "draufgaenger": 0.10,
    "allrounder": 0.18,
    "rohdiamant": 0.08,
}


# ----------------------------------------------------------------------
# Datenklassen
# ----------------------------------------------------------------------
@dataclass
class Team:
    """Team mit dem einzigen Team-Attribut: Servicedisziplin (Entscheidung 9)."""

    id: int
    name: str
    nation: str
    color: str
    servicedisziplin: float = 50.0

    @property
    def service_factor(self) -> float:
        """Multiplikator auf jede Stoppdauer (Abschnitt 6.3).

        1,25 bei 0 · 1,00 bei 50 · 0,75 bei 100.
        """
        return 1.25 - 0.005 * self.servicedisziplin

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Team:
        return cls(**data)


@dataclass
class Rider:
    """Ein fiktiver Fahrer."""

    id: int
    name: str
    nation: str
    team_id: int
    age: int
    height_cm: float
    weight_kg: float
    ftp_w: float
    archetype: str
    attributes: dict[str, float] = field(default_factory=dict)
    #: Tag im Jahr, an dem die Saisonform ihren Höhepunkt hat.
    form_peak_day: int = 180
    gender: str = "m"

    # --- abgeleitete Größen ------------------------------------------
    @property
    def wkg(self) -> float:
        return self.ftp_w / self.weight_kg

    @property
    def frontal_area_m2(self) -> float:
        """Frontalfläche nach A = 0,0276 · h^0,725 · m^0,425 (h in m)."""
        return 0.0276 * (self.height_cm / 100.0) ** 0.725 * self.weight_kg**0.425

    def attr(self, key: str) -> float:
        return float(self.attributes.get(key, 50.0))

    def attr_norm(self, key: str) -> float:
        """Attribut auf −1 … +1 normiert (50 = 0)."""
        return (self.attr(key) - 50.0) / 50.0

    @property
    def potential(self) -> float:
        """Gewichtetes Mittel aller Attribute – das Potenzial-Budget."""
        total_w = sum(ATTRIBUTES.values())
        return sum(self.attr(k) * w for k, w in ATTRIBUTES.items()) / total_w

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rider:
        return cls(**data)


# ----------------------------------------------------------------------
# Generator
# ----------------------------------------------------------------------
def _pick_weighted(rng: np.random.Generator, options: dict[str, float]) -> str:
    keys = list(options)
    weights = np.array([options[k] for k in keys], dtype=np.float64)
    return keys[int(rng.choice(len(keys), p=weights / weights.sum()))]


def _apply_potential_budget(
    attributes: dict[str, float], target: float, lo: float = 5.0, hi: float = 97.0
) -> dict[str, float]:
    """Normiert das gewichtete Attributmittel auf ``target``.

    Ohne dieses Budget bekommt man entweder graue Einheitsfahrer oder
    einen, der alles gewinnt: Jede Stärke muss irgendwo bezahlt werden.

    Die Verschiebung ist additiv, damit die Archetyp-*Form* (wer ist wo
    stark) erhalten bleibt und nur das Niveau wandert. Nach dem Clippen
    an den Rändern verschiebt sich das Mittel wieder, deshalb ein paar
    Ausgleichsrunden.
    """
    total_w = sum(ATTRIBUTES.values())
    values = dict(attributes)
    for _ in range(8):
        current = sum(values[k] * w for k, w in ATTRIBUTES.items()) / total_w
        delta = target - current
        if abs(delta) < 0.05:
            break
        # Nur Attribute verschieben, die nicht schon am Anschlag kleben.
        movable = [k for k, v in values.items() if lo < v < hi]
        if not movable:
            break
        scale = total_w / sum(ATTRIBUTES[k] for k in movable)
        for k in movable:
            values[k] = min(hi, max(lo, values[k] + delta * scale))
    return {k: round(v, 1) for k, v in values.items()}


def generate_rider(
    rng: np.random.Generator,
    rider_id: int,
    team_id: int,
    archetype: str | Archetype | None = None,
    nation: str | None = None,
    potential_mean: float = 50.0,
    potential_sd: float = 4.0,
) -> Rider:
    """Erzeugt einen plausiblen fiktiven Fahrer."""
    if archetype is None:
        arch = ARCHETYPES[_pick_weighted(rng, ARCHETYPE_MIX)]
    elif isinstance(archetype, str):
        arch = ARCHETYPES[archetype]
    else:
        arch = archetype

    nat = nation or _pick_weighted(rng, NATION_WEIGHTS)
    first = str(rng.choice(FIRST_NAMES[nat]))
    last = str(rng.choice(LAST_NAMES[nat]))

    raw = {
        key: float(np.clip(rng.normal(arch.mean_for(key), arch.spread), 3.0, 99.0))
        for key in ATTRIBUTES
    }
    target = float(np.clip(rng.normal(potential_mean, potential_sd), 36.0, 64.0))
    attributes = _apply_potential_budget(raw, target)

    # --- Körperbau und FTP, physiologisch plausibel gehalten ---------
    age = int(np.clip(rng.normal(31.5, 5.5), 19, 47))
    height = float(np.clip(rng.normal(179.0 + arch.height_bias_cm, 6.0), 158.0, 198.0))
    # BMI-Zielband für Ausdauersportler: schlank, aber nicht unmenschlich.
    bmi = float(np.clip(rng.normal(21.4, 1.1), 18.5, 25.5))
    weight = bmi * (height / 100.0) ** 2

    # Leistungsniveau folgt dem Potenzial-Budget: ein Fahrer mit hohem
    # Budget ist auch physiologisch stärker, sonst wäre das Budget nur
    # Kosmetik.
    wkg_base = 4.35 + (target - 50.0) * 0.035 + arch.wkg_bias
    # Alterskurve mit Scheitel um 31 Jahre.
    wkg_base -= 0.020 * abs(age - 31) ** 1.25
    wkg = float(np.clip(rng.normal(wkg_base, 0.16), WKG_RANGE[0], WKG_RANGE[1]))
    # FTP in ganzen Watt – und danach noch einmal ins Band gezwungen:
    # Die Rundung allein kann W/kg um wenige Tausendstel aus dem
    # Plausibilitätsband schieben, und dann stimmt die Zusicherung des
    # Generators nicht mehr, auf die sich die Prüfung stützt.
    ftp = round(wkg * weight)
    ftp = float(min(max(ftp, math.ceil(WKG_RANGE[0] * weight)), math.floor(WKG_RANGE[1] * weight)))

    return Rider(
        id=rider_id,
        name=f"{first} {last}",
        nation=nat,
        team_id=team_id,
        age=age,
        height_cm=round(height, 1),
        weight_kg=round(weight, 1),
        ftp_w=ftp,
        archetype=arch.key,
        attributes=attributes,
        form_peak_day=int(rng.integers(120, 260)),
    )


def generate_team(rng: np.random.Generator, team_id: int, used: set[str]) -> Team:
    for _ in range(40):
        name = f"{rng.choice(TEAM_PREFIXES)} {rng.choice(TEAM_SUFFIXES)}"
        if name not in used:
            break
    else:  # pragma: no cover - praktisch unerreichbar
        name = f"Team {team_id}"
    used.add(name)
    hue = int(rng.integers(0, 360))
    return Team(
        id=team_id,
        name=name,
        nation=_pick_weighted(rng, NATION_WEIGHTS),
        color=_hsl_to_hex(hue, 0.62, 0.46),
        servicedisziplin=round(float(np.clip(rng.normal(50.0, 16.0), 8.0, 95.0)), 1),
    )


def generate_pool(
    n_riders: int,
    n_teams: int | None = None,
    seed: int = 1,
    archetype: str | None = None,
) -> tuple[list[Team], list[Rider]]:
    """Erzeugt einen kompletten Fahrerpool mit Teams.

    Bei 250 Fahrern sind 25–35 Teams à 7–10 Fahrer plausibel; zu wenige
    Teams machen die Servicedisziplin zum dominanten Faktor.
    """
    rng = np.random.default_rng(seed)
    if n_teams is None:
        n_teams = max(2, min(35, round(n_riders / 8)))
    used: set[str] = set()
    teams = [generate_team(rng, i, used) for i in range(n_teams)]

    riders: list[Rider] = []
    for i in range(n_riders):
        team = teams[i % n_teams]
        riders.append(generate_rider(rng, i, team.id, archetype=archetype))
    return teams, riders


def _hsl_to_hex(h: float, s: float, lightness: float) -> str:
    c = (1 - abs(2 * lightness - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = lightness - c / 2
    table = [(c, x, 0.0), (x, c, 0.0), (0.0, c, x), (0.0, x, c), (x, 0.0, c), (c, 0.0, x)]
    r, g, b = table[int(h // 60) % 6]
    return f"#{int(round((r + m) * 255)):02x}{int(round((g + m) * 255)):02x}{int(round((b + m) * 255)):02x}"


def season_form(rider: Rider, day_of_year: int) -> float:
    """Saisonform 0,90–1,08 (Abschnitt 5.4).

    Eine glatte Kurve mit einem Höhepunkt je Saison. Sie verändert sich
    langsam – deshalb ist die Distanz zum Formhöhepunkt der einzige
    Eingang.
    """
    delta = abs(((day_of_year - rider.form_peak_day + 182) % 365) - 182)
    # Gauß-Glocke: am Höhepunkt 1,08, rund 90 Tage daneben etwa 0,93.
    shape = math.exp(-((delta / 78.0) ** 2))
    return 0.90 + 0.18 * shape


def riders_by_team(riders: Iterable[Rider]) -> dict[int, list[Rider]]:
    out: dict[int, list[Rider]] = {}
    for rider in riders:
        out.setdefault(rider.team_id, []).append(rider)
    return out


__all__ = [
    "ATTRIBUTES",
    "ACTIVE_ATTRIBUTES",
    "ATTRIBUTE_LABELS",
    "ARCHETYPES",
    "ARCHETYPE_MIX",
    "Archetype",
    "NATIONS",
    "Rider",
    "Team",
    "generate_pool",
    "generate_rider",
    "generate_team",
    "season_form",
    "riders_by_team",
]
