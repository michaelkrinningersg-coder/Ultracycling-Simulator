"""Karriere über mehrere Jahre (Abschnitt 14, Ausbaustufe).

Eine Saison für sich ist eine Momentaufnahme: zehn Rennen, eine
Rangliste, fertig. Interessant wird es erst über die Jahre — wenn der
Rohdiamant von Platz 40 auf Platz 3 klettert, wenn der zweifache Sieger
mit 36 nicht mehr mithält, wenn ein Name in der ewigen Bestenliste
auftaucht, den man als 20-Jährigen im Feld übersehen hat. Genau das
hält dieses Modul fest.

Was gespeichert wird und was nicht
----------------------------------
Die Karriere speichert **Momentaufnahmen abgeschlossener Jahre**:
Endstand der Wertung und was die Fahrerentwicklung getan hat. Das ist
kein zweiter Wahrheitsträger neben den Rennergebnissen, sondern die
einzige Stelle, an der diese Zahlen überhaupt noch stehen: Nach dem
Saisonwechsel ist der Fahrerpool ein anderer — die Fahrer sind ein Jahr
älter, einige zurückgetreten —, und die Wertung von 2031 lässt sich aus
dem Pool von 2035 nicht mehr rekonstruieren.

Die laufende Saison dagegen speichert hier gar nichts. Ihre Wertung
wird bei jedem Aufruf aus den gerechneten Rennen gebildet, und die sind
unveränderlich. Erst beim Abschluss wandert sie als Kapitel hierher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Career",
    "DevelopmentNote",
    "HallOfFameRow",
    "SeasonChapter",
    "StandingSnapshot",
    "hall_of_fame",
    "rider_history",
]


# ----------------------------------------------------------------------
# Momentaufnahmen
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class StandingSnapshot:
    """Eine Zeile der Endwertung eines abgeschlossenen Jahres."""

    rank: int
    rider_id: int
    name: str
    team_name: str
    points: float
    wins: int
    podiums: int
    starts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "rider_id": self.rider_id,
            "name": self.name,
            "team_name": self.team_name,
            "points": round(self.points, 1),
            "wins": self.wins,
            "podiums": self.podiums,
            "starts": self.starts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StandingSnapshot:
        return cls(
            rank=int(data["rank"]),
            rider_id=int(data["rider_id"]),
            name=data["name"],
            team_name=data.get("team_name", ""),
            points=float(data.get("points", 0.0)),
            wins=int(data.get("wins", 0)),
            podiums=int(data.get("podiums", 0)),
            starts=int(data.get("starts", 0)),
        )


@dataclass(frozen=True)
class DevelopmentNote:
    """Was der Saisonwechsel mit einem Fahrer gemacht hat."""

    rider_id: int
    name: str
    age: int
    #: Alter, Potenzial und FTP **nach** dem Wechsel.
    potential: float
    ftp_w: float
    note: str = ""
    retired: bool = False
    newcomer: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rider_id": self.rider_id,
            "name": self.name,
            "age": self.age,
            "potential": round(self.potential, 1),
            "ftp_w": round(self.ftp_w, 1),
            "note": self.note,
            "retired": self.retired,
            "newcomer": self.newcomer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DevelopmentNote:
        return cls(
            rider_id=int(data["rider_id"]),
            name=data["name"],
            age=int(data.get("age", 0)),
            potential=float(data.get("potential", 0.0)),
            ftp_w=float(data.get("ftp_w", 0.0)),
            note=data.get("note", ""),
            retired=bool(data.get("retired", False)),
            newcomer=bool(data.get("newcomer", False)),
        )


@dataclass
class SeasonChapter:
    """Ein abgeschlossenes Jahr der Karriere."""

    year: int
    season_id: str
    season_name: str
    standings: list[StandingSnapshot] = field(default_factory=list)
    development: list[DevelopmentNote] = field(default_factory=list)

    @property
    def champion(self) -> StandingSnapshot | None:
        return self.standings[0] if self.standings else None

    @property
    def retired(self) -> list[DevelopmentNote]:
        return [d for d in self.development if d.retired]

    @property
    def newcomers(self) -> list[DevelopmentNote]:
        return [d for d in self.development if d.newcomer]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "season_id": self.season_id,
            "season_name": self.season_name,
            "standings": [s.to_dict() for s in self.standings],
            "development": [d.to_dict() for d in self.development],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeasonChapter:
        return cls(
            year=int(data["year"]),
            season_id=data["season_id"],
            season_name=data.get("season_name", ""),
            standings=[StandingSnapshot.from_dict(s) for s in data.get("standings", [])],
            development=[DevelopmentNote.from_dict(d) for d in data.get("development", [])],
        )


@dataclass
class Career:
    """Mehrere Saisons in Folge, mit gemeinsamem Fahrerpool."""

    id: str
    name: str
    first_year: int
    #: Alle Saisons in Jahresreihenfolge — die letzte ist die laufende.
    season_ids: list[str] = field(default_factory=list)
    #: Abgeschlossene Jahre.
    chapters: list[SeasonChapter] = field(default_factory=list)

    @property
    def current_season_id(self) -> str | None:
        return self.season_ids[-1] if self.season_ids else None

    @property
    def current_year(self) -> int:
        return self.first_year + max(len(self.season_ids) - 1, 0)

    @property
    def years_closed(self) -> int:
        return len(self.chapters)

    def chapter(self, year: int) -> SeasonChapter | None:
        for chapter in self.chapters:
            if chapter.year == year:
                return chapter
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "first_year": self.first_year,
            "season_ids": list(self.season_ids),
            "chapters": [c.to_dict() for c in self.chapters],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Career:
        return cls(
            id=data["id"],
            name=data["name"],
            first_year=int(data["first_year"]),
            season_ids=list(data.get("season_ids", [])),
            chapters=[SeasonChapter.from_dict(c) for c in data.get("chapters", [])],
        )


# ----------------------------------------------------------------------
# Auswertung über die Jahre
# ----------------------------------------------------------------------
@dataclass
class HallOfFameRow:
    """Eine Zeile der ewigen Bestenliste."""

    rider_id: int
    name: str
    team_name: str
    titles: int = 0
    podium_years: int = 0
    wins: int = 0
    podiums: int = 0
    points: float = 0.0
    starts: int = 0
    seasons: int = 0
    best_rank: int = 10**6
    first_year: int = 0
    last_year: int = 0
    #: Steht der Fahrer noch im Feld, oder ist er zurückgetreten?
    retired_year: int | None = None

    def sort_key(self) -> tuple:
        """Titel zuerst, dann Podestjahre, Siege, Punkte.

        Punkte allein wären ungerecht gegenüber kurzen Karrieren: Wer
        zehn Jahre im Mittelfeld fährt, sammelt mehr als der Fahrer mit
        zwei Titeln und einem frühen Rücktritt. In einer Bestenliste
        zählt, was man gewonnen hat.
        """
        return (-self.titles, -self.podium_years, -self.wins, -self.points, self.name)


def hall_of_fame(career: Career) -> list[HallOfFameRow]:
    """Ewige Bestenliste über alle abgeschlossenen Jahre."""
    rows: dict[int, HallOfFameRow] = {}
    for chapter in sorted(career.chapters, key=lambda c: c.year):
        for standing in chapter.standings:
            row = rows.get(standing.rider_id)
            if row is None:
                row = HallOfFameRow(
                    rider_id=standing.rider_id,
                    name=standing.name,
                    team_name=standing.team_name,
                    first_year=chapter.year,
                )
                rows[standing.rider_id] = row
            row.name = standing.name
            row.team_name = standing.team_name
            row.last_year = chapter.year
            row.seasons += 1
            row.titles += 1 if standing.rank == 1 else 0
            row.podium_years += 1 if standing.rank <= 3 else 0
            row.wins += standing.wins
            row.podiums += standing.podiums
            row.points += standing.points
            row.starts += standing.starts
            row.best_rank = min(row.best_rank, standing.rank)
        for note in chapter.development:
            if note.retired and note.rider_id in rows:
                rows[note.rider_id].retired_year = chapter.year
    return sorted(rows.values(), key=lambda r: r.sort_key())


@dataclass
class RiderYear:
    """Ein Jahr im Lebenslauf eines Fahrers."""

    year: int
    standing: StandingSnapshot | None
    development: DevelopmentNote | None

    @property
    def rank(self) -> int | None:
        return self.standing.rank if self.standing else None

    @property
    def points(self) -> float:
        return self.standing.points if self.standing else 0.0


def rider_history(career: Career, rider_id: int) -> list[RiderYear]:
    """Jahr für Jahr, was ein Fahrer erreicht hat und was aus ihm wurde.

    Auch Jahre ohne Wertung erscheinen, solange der Fahrer im Feld war —
    eine Lücke ist eine Aussage: Er ist kein einziges Rennen gefahren.
    """
    out: list[RiderYear] = []
    for chapter in sorted(career.chapters, key=lambda c: c.year):
        standing = next((s for s in chapter.standings if s.rider_id == rider_id), None)
        note = next((d for d in chapter.development if d.rider_id == rider_id), None)
        if standing is None and note is None:
            continue
        out.append(RiderYear(year=chapter.year, standing=standing, development=note))
    return out
