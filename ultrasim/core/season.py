"""Saison, Kalender und Wertung (Game-Design-Dokument, Abschnitte 11 und 14).

Ein Rennen für sich ist ein Ergebnis. Erst der Kalender macht daraus
eine Geschichte: Wer im Mai gewinnt, startet im Juni müde; wer sich ein
Rennen spart, kommt frisch, verschenkt aber Punkte.

Drei Dinge stehen hier:

* **Kalender** — welche Strecke wann mit welchem Feld gefahren wird
* **Wertung** — Punkte nach Platzierung, gewichtet mit einem
  Rennkoeffizienten, dazu die Gesamtrangliste mit Tiebreak
* **Restermüdung** — was ein Rennen im nächsten kostet

Der Kalender ist reine Datenhaltung: Er rechnet nichts und weiß nichts
von der Simulation. Das Rechnen bleibt bei ``engine.simulate_race``, und
die Saison merkt sich nur, welches gerechnete Rennen zu welchem Termin
gehört.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# ----------------------------------------------------------------------
# Punkte (Abschnitt 11)
# ----------------------------------------------------------------------
#: Punkte für die ersten zehn Ränge, danach −2 je Rang bis 0.
POINTS_HEAD: tuple[int, ...] = (100, 80, 65, 55, 48, 42, 37, 33, 30, 28)
POINTS_STEP = 2


def points_for_rank(rank: int | None, head: tuple[int, ...] = POINTS_HEAD) -> int:
    """Rohpunkte für eine Platzierung, ohne Rennkoeffizient.

    ``None`` bedeutet keine Wertung — Aufgabe oder Zeitlimit. Beides gibt
    null Punkte; die Ermüdung des Versuchs bleibt trotzdem (Abschnitt 11).
    """
    if rank is None or rank < 1:
        return 0
    if rank <= len(head):
        return head[rank - 1]
    return max(head[-1] - POINTS_STEP * (rank - len(head)), 0)


#: Bezugsgröße des Rennkoeffizienten: ein 400-km-Rennen mit moderatem
#: Profil ist 1,0 wert.
COEFFICIENT_REFERENCE_KM = 400.0
#: Umrechnung Höhenmeter in flache Kilometer. Bei rund 1100 m/h vertikal
#: und 30 km/h im Flachen kostet ein Kilometer Anstieg ungefähr so viel
#: Zeit wie 27 flache Kilometer.
ASCENT_TO_FLAT_KM = 0.027
#: Die Wurzel dämpft: Ein viermal so langes Rennen ist doppelt so viel
#: wert, nicht viermal. Sonst entscheidet ein einziger Ultra die Saison
#: und die kurzen Rennen sind Dekoration.
COEFFICIENT_EXPONENT = 0.5
COEFFICIENT_CLIP = (0.6, 2.2)


def effort_km(distance_km: float, ascent_m: float) -> float:
    """Streckenlänge in „flachen Kilometern", Höhenmeter eingerechnet."""
    return float(distance_km) + ASCENT_TO_FLAT_KM * float(ascent_m)


def race_coefficient(distance_km: float, ascent_m: float) -> float:
    """Rennkoeffizient aus Länge und Höhenmetern (Abschnitt 11)."""
    ratio = effort_km(distance_km, ascent_m) / COEFFICIENT_REFERENCE_KM
    value = math.pow(max(ratio, 1e-6), COEFFICIENT_EXPONENT)
    return round(min(max(value, COEFFICIENT_CLIP[0]), COEFFICIENT_CLIP[1]), 2)


# ----------------------------------------------------------------------
# Restermüdung zwischen zwei Rennen
# ----------------------------------------------------------------------
#: Zeitkonstante der Erholung in Tagen, aus dem Attribut Regeneration.
#: Bei τ = 7 sind nach vier Wochen noch 2 % der Rennarbeit übrig, nach
#: zwei Wochen 14 % — genug, dass zwei Ultras in vierzehn Tagen eine
#: schlechte Idee sind, und wenig genug, dass ein Monat Abstand reicht.
RECOVERY_TAU_DAYS = (9.0, 5.0)


def recovery_tau_days(regeneration: float) -> float:
    slow, fast = RECOVERY_TAU_DAYS
    return slow + (fast - slow) * (float(regeneration) / 100.0)


def residual_work_kj(work_kj: float, days: float, regeneration: float) -> float:
    """Wie viel Rennarbeit nach ``days`` Tagen noch in den Beinen steckt."""
    if work_kj <= 0.0 or days < 0.0:
        return 0.0
    return float(work_kj) * math.exp(-float(days) / recovery_tau_days(regeneration))


#: Maximaler Verlust an haltbarer Leistung durch fehlende Frische …
FRESHNESS_LOSS = 0.42
#: … und die Krümmung dorthin. Wie bei der Langzeitermüdung liegt der
#: Exponent unter 1: Die ersten Reste kosten überproportional.
FRESHNESS_P = 0.70
FRESHNESS_FLOOR = 0.62


def freshness_factor(residual_kj: float, capacity_kj: float) -> float:
    """Multiplikator auf die haltbare Leistung, konstant über das Rennen.

    **Warum nicht einfach die Restermüdung in die Langzeitermüdung
    einsetzen?** Das war der erste Versuch, und er ist elegant: Wer mit
    5.000 kJ Rückstand startet, ist so müde, als lägen die ersten 5.000
    kJ schon hinter ihm — eine Größe, eine Kurve, keine zweite
    Kalibrierung. Gemessen taugt es nur nicht. Der Effekt wäscht sich
    über die Renndistanz aus: Bei einem Ultra stehen am Ende 30.000 statt
    22.000 kJ auf dem Zähler, und weil die Ermüdungskurve dort längst
    flach ist, kostet eine Woche nach einem Ultra ganze 3 % Zeit. Ein
    dichter Kalender wäre damit ein Schönheitsfehler statt einer
    Entscheidung.

    Physiologisch ist die Auswaschung auch falsch. Wer vor einer Woche
    1200 km gefahren ist, hat nicht „schon einen Teil des Rennens hinter
    sich" — er hat beschädigte Muskulatur, leere Speicher und einen
    gestörten Schlafrhythmus. Das begleitet ihn bis ins Ziel, statt sich
    im Verlauf zu verdünnen.

    Deshalb zwei Wege für eine Eingangsgröße: Die Restarbeit geht
    *zusätzlich* in den Ermüdungszähler (wer müde startet, erreicht die
    Wand früher), und dieser Faktor trägt den bleibenden Teil.
    """
    if residual_kj <= 0.0 or capacity_kj <= 0.0:
        return 1.0
    ratio = max(residual_kj, 0.0) / max(capacity_kj, 1.0)
    return max(1.0 - FRESHNESS_LOSS * math.pow(ratio, FRESHNESS_P), FRESHNESS_FLOOR)


# ----------------------------------------------------------------------
# Kalender
# ----------------------------------------------------------------------
@dataclass
class CalendarRace:
    """Ein Termin im Saisonkalender."""

    id: str
    name: str
    route_id: str
    day: date
    n_riders: int = 60
    seed: int = 1
    weather_preset: str | None = None
    #: None = aus der Strecke abgeleitet, sobald sie bekannt ist.
    coefficient: float | None = None
    #: ID des gerechneten Rennens, solange es noch keins gibt: None.
    race_id: str | None = None

    @property
    def computed(self) -> bool:
        return self.race_id is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "route_id": self.route_id,
            "day": self.day.isoformat(),
            "n_riders": self.n_riders,
            "seed": self.seed,
            "weather_preset": self.weather_preset,
            "coefficient": self.coefficient,
            "race_id": self.race_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalendarRace:
        data = dict(data)
        data["day"] = date.fromisoformat(data["day"])
        return cls(**data)


@dataclass
class Season:
    """Eine Saison: Name, Jahr und ein geordneter Kalender."""

    id: str
    name: str
    year: int
    races: list[CalendarRace] = field(default_factory=list)
    #: Punkteschema; leer bedeutet ``POINTS_HEAD``.
    points_head: list[int] = field(default_factory=lambda: list(POINTS_HEAD))

    def sorted_races(self) -> list[CalendarRace]:
        """Kalender in Terminreihenfolge.

        Die Reihenfolge entscheidet über die Restermüdung, deshalb wird
        sie überall aus dem Datum abgeleitet und nie aus der Listenfolge.
        """
        return sorted(self.races, key=lambda r: (r.day, r.id))

    def race(self, race_key: str) -> CalendarRace | None:
        for entry in self.races:
            if entry.id == race_key:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "year": self.year,
            "races": [r.to_dict() for r in self.sorted_races()],
            "points_head": self.points_head,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Season:
        return cls(
            id=data["id"],
            name=data["name"],
            year=int(data["year"]),
            races=[CalendarRace.from_dict(r) for r in data.get("races", [])],
            points_head=list(data.get("points_head") or POINTS_HEAD),
        )


# ----------------------------------------------------------------------
# Gesamtwertung
# ----------------------------------------------------------------------
@dataclass
class RaceScore:
    """Was ein Fahrer bei einem einzelnen Termin geholt hat."""

    race_key: str
    race_name: str
    day: date
    rank: int | None
    status: str
    points: float


@dataclass
class Standing:
    """Eine Zeile der Gesamtrangliste."""

    rider_id: int
    name: str
    nation: str
    team_id: int
    team_name: str
    points: float = 0.0
    wins: int = 0
    podiums: int = 0
    starts: int = 0
    finishes: int = 0
    scores: list[RaceScore] = field(default_factory=list)
    rank: int | None = None

    @property
    def placings(self) -> list[int]:
        """Platzierungen aufsteigend — die dritte Stufe des Tiebreaks."""
        return sorted(s.rank for s in self.scores if s.rank)

    def sort_key(self) -> tuple:
        """Punkte, dann Siege, dann die bessere Einzelplatzierung.

        Der dritte Schlüssel vergleicht die sortierten Platzierungen
        elementweise: Wer einen zweiten Platz hat, steht vor dem, dessen
        bestes Ergebnis ein dritter ist — und bei Gleichstand entscheidet
        das nächstbeste Ergebnis. Kürzere Listen werden hinten mit einem
        Sentinel aufgefüllt, sonst gewönne, wer weniger gestartet ist.
        """
        padded = self.placings + [10**6] * (32 - len(self.placings))
        return (-self.points, -self.wins, tuple(padded[:32]), self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "rider_id": self.rider_id,
            "name": self.name,
            "nation": self.nation,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "points": round(self.points, 1),
            "wins": self.wins,
            "podiums": self.podiums,
            "starts": self.starts,
            "finishes": self.finishes,
        }


def score_race(
    entries: list[Any],
    coefficient: float,
    points_head: tuple[int, ...] | list[int] = POINTS_HEAD,
) -> dict[int, float]:
    """Punkte je ``rider_id`` für ein gerechnetes Rennen."""
    head = tuple(points_head) or POINTS_HEAD
    return {
        entry.rider_id: points_for_rank(entry.rank, head) * coefficient for entry in entries
    }


def build_standings(
    season: Season,
    results: dict[str, Any],
    riders: dict[int, Any],
    teams: dict[int, Any],
    coefficients: dict[str, float],
) -> list[Standing]:
    """Gesamtrangliste über alle gerechneten Termine der Saison.

    ``results`` bildet den Kalenderschlüssel auf ein ``RaceResult`` ab —
    nur gerechnete Termine sind enthalten. Ein noch nicht gefahrenes
    Rennen taucht in der Tabelle also gar nicht auf, statt als Nullzeile.
    """
    head = tuple(season.points_head) or POINTS_HEAD
    table: dict[int, Standing] = {}

    for calendar_race in season.sorted_races():
        result = results.get(calendar_race.id)
        if result is None:
            continue
        coefficient = coefficients.get(calendar_race.id, 1.0)
        for entry in result.entries:
            rider = riders.get(entry.rider_id)
            if rider is None:
                continue
            row = table.get(entry.rider_id)
            if row is None:
                team = teams.get(rider.team_id)
                row = Standing(
                    rider_id=rider.id,
                    name=rider.name,
                    nation=rider.nation,
                    team_id=rider.team_id,
                    team_name=team.name if team else "",
                )
                table[rider.id] = row
            points = points_for_rank(entry.rank, head) * coefficient
            row.points += points
            row.starts += 1
            if entry.rank == 1:
                row.wins += 1
            if entry.rank is not None and entry.rank <= 3:
                row.podiums += 1
            if entry.status in ("FIN", "OTL"):
                row.finishes += 1
            row.scores.append(
                RaceScore(
                    race_key=calendar_race.id,
                    race_name=calendar_race.name,
                    day=calendar_race.day,
                    rank=entry.rank,
                    status=entry.status,
                    points=points,
                )
            )

    standings = sorted(table.values(), key=lambda s: s.sort_key())
    for i, row in enumerate(standings, start=1):
        row.rank = i
    return standings


__all__ = [
    "ASCENT_TO_FLAT_KM",
    "CalendarRace",
    "POINTS_HEAD",
    "RECOVERY_TAU_DAYS",
    "RaceScore",
    "Season",
    "Standing",
    "build_standings",
    "effort_km",
    "freshness_factor",
    "points_for_rank",
    "race_coefficient",
    "recovery_tau_days",
    "residual_work_kj",
    "score_race",
]
