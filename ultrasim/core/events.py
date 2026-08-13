"""Ereignis-Strom der Simulation (Game-Design-Dokument, Abschnitt 8.3).

Die Simulation erzeugt aus einer Renn-Konfiguration einen Event-Strom.
Web-App und CLI sind nur zwei Konsumenten davon.

Alle Zeiten sind **Fahrer-Eigenzeit** in Sekunden seit dem eigenen Start
(Entscheidung 13). Die absolute Startzeit bestimmt nur die Reihenfolge,
nicht die Bedingungen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Ereignistypen. Die auskommentierten Zeilen sind im Datenmodell schon
# vorgesehen, werden aber erst mit den Mechaniken der Meilensteine M5–M6
# erzeugt (Verpflegung, Schlaf, Pannen).
START = "START"
SPLIT_PASSED = "SPLIT_PASSED"
BIKE_CHANGE = "BIKE_CHANGE"
STOP_START = "STOP_START"
STOP_END = "STOP_END"
PLAN = "PLAN"
FINISH = "FINISH"
DNF = "DNF"
SLEEP = "SLEEP"
MECHANICAL = "MECHANICAL"
BONK = "BONK"
CONDITION_START = "CONDITION_START"
CONDITION_END = "CONDITION_END"

#: Ereignisse, die auch bei starkem Zeitraffer noch gestreamt werden.
MAJOR_EVENTS = frozenset(
    {SPLIT_PASSED, FINISH, DNF, BIKE_CHANGE, MECHANICAL, BONK, CONDITION_START}
)


@dataclass(slots=True)
class RaceEvent:
    """Ein Ereignis im Rennen."""

    entry_id: int
    t_s: float  # Fahrer-Eigenzeit
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "t_s": round(self.t_s, 2),
            "type": self.type,
            "payload": self.payload,
        }


def format_event(event: RaceEvent, rider_name: str = "") -> str:
    """Einzeiler für den Fahrer-Ticker in der UI."""
    who = f"{rider_name}: " if rider_name else ""
    p = event.payload
    if event.type == SPLIT_PASSED:
        return f"{who}Split {p.get('split_name', '')} in {_hms(event.t_s)}"
    if event.type == BIKE_CHANGE:
        return (
            f"{who}Radwechsel auf {p.get('bike', '')} "
            f"({p.get('duration_s', 0):.0f} s) bei km {p.get('dist_km', 0):.0f}"
        )
    if event.type == PLAN:
        return f"{who}{p.get('note', '')}"
    if event.type == FINISH:
        return f"{who}Ziel in {_hms(event.t_s)}"
    if event.type == DNF:
        return f"{who}Aufgabe bei km {p.get('dist_km', 0):.0f} – {p.get('reason', '')}"
    if event.type == START:
        return f"{who}gestartet"
    if event.type == CONDITION_START:
        return f"{who}{p.get('label', 'Zustand')} ab km {p.get('dist_km', 0):.0f}"
    if event.type == CONDITION_END:
        return f"{who}{p.get('label', 'Zustand')} überstanden (km {p.get('dist_km', 0):.0f})"
    return f"{who}{event.type}"


def _hms(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}"
