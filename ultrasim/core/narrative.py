"""Rennbericht in einem Satz je Fahrer.

Eine Ergebnisliste sagt, *wer* gewonnen hat. Sie sagt nicht, wie das
Rennen war — dass einer nach einer Panne bei km 93 elf Minuten verloren
hat, bis km 190 trotzdem Vierter war und dann eingebrochen ist. Genau
das steht im Ereignisstrom und in den Spliträngen, nur liest es dort
niemand: 250 Fahrer mal 30 Splits sind 7500 Zahlen.

Dieses Modul verdichtet beides zu einem Satz. Es erfindet nichts und
wertet nicht — jeder Baustein steht für eine Zahl, die vorher schon da
war.

**Warum reine Funktionen ohne Speicher und ohne Web:** Der Bericht ist
Auswertung, keine Simulation, aber er gehört trotzdem zur Sache und
nicht zur Oberfläche. So kann ihn die Ergebnisseite benutzen, das
Fahrerdetail, später ein Export — und ein Test kann ihn prüfen, ohne
ein Rennen zu rechnen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .events import BIKE_CHANGE, BONK, DECISION, INCIDENT, SLEEP, RaceEvent
from .incidents import CATALOG

__all__ = ["RaceReport", "build_report", "build_reports"]

#: Ab so vielen verlorenen Sekunden ist ein Zwischenfall der Rede wert.
#: Darunter erzählt man von einem Halt, der im Rauschen der Servicestopps
#: untergeht.
NOTABLE_LOSS_S = 240.0

#: Ab so vielen Plätzen zwischen bester und letzter Platzierung wird aus
#: „hielt sich" ein „brach ein" beziehungsweise ein „arbeitete sich vor".
MOVE_PLACES = 4

#: So viele Bausteine höchstens. Ein Satz mit fünf Nebensätzen ist kein
#: Bericht mehr, sondern ein Protokoll.
MAX_CLAUSES = 3

#: So viele Bausteine trägt der ausführliche Bericht.
#:
#: Er ist für die ersten drei gedacht, und dort gilt das Gegenteil der
#: Regel oben: Über den Sieger eines 2500-km-Rennens will man mehr
#: wissen als einen Satz — wo er verloren hat, wie oft er geschlafen
#: hat, wann er vorn war. Für Rang 87 wäre dieselbe Länge Protokoll.
MAX_CLAUSES_LONG = 9

#: So viele Bausteine stehen in einem Satz des ausführlichen Berichts.
CLAUSES_PER_SENTENCE = 2


@dataclass(frozen=True)
class RaceReport:
    """Was einem Fahrer in diesem Rennen widerfahren ist."""

    entry_id: int
    #: Die Bausteine in Erzählreihenfolge.
    clauses: list[str] = field(default_factory=list)
    #: Name des Fahrers — Subjekt der Folgesätze im langen Bericht.
    #: Ohne ihn müsste dort ein Pronomen stehen, und das hieße, den
    #: Fahrern ein Geschlecht anzudichten, das das Modell nicht kennt.
    name: str = ""

    @staticmethod
    def _sentence(parts: Sequence[str], subject: str = "") -> str:
        chain = ", ".join(parts)
        if subject:
            return f"{subject} {chain}." if not chain.endswith(".") else f"{subject} {chain}"
        chain = chain[0].upper() + chain[1:]
        # Endet der letzte Baustein schon auf einen Punkt — etwa bei
        # einer Ordnungszahl —, keinen zweiten anhängen.
        return chain if chain.endswith(".") else chain + "."

    @property
    def text(self) -> str:
        if not self.clauses:
            return ""
        return self._sentence(self.clauses[:MAX_CLAUSES])

    @property
    def paragraph(self) -> str:
        """Alle Bausteine als mehrere Sätze.

        Der erste Satz beginnt ohne Subjekt — er steht unter der
        Ergebniszeile, in der der Name schon fällt. Ab dem zweiten ist
        der Name das Subjekt: Ein Satz, der mit „verlor" anfängt, ist
        nach dem ersten kein Bericht mehr, sondern eine Stichwortliste.
        """
        if not self.clauses:
            return ""
        chunks = [
            self.clauses[i : i + CLAUSES_PER_SENTENCE]
            for i in range(0, len(self.clauses), CLAUSES_PER_SENTENCE)
        ]
        out = [self._sentence(chunks[0])]
        for chunk in chunks[1:]:
            out.append(self._sentence(chunk, subject=self.name))
        return " ".join(out)


def _km(value: Any) -> str:
    return f"km {float(value):.0f}"


def _minutes(seconds: float) -> str:
    minutes = seconds / 60.0
    if minutes >= 60.0:
        hours, rest = divmod(int(round(minutes)), 60)
        return f"{hours}:{rest:02d} h"
    return f"{minutes:.0f} min"


#: Für die vorderen Ränge liest sich das Wort besser als die Ziffer —
#: und es erspart den Punkt der Ordnungszahl mitten im Satz.
PLACING_WORDS = {2: "Zweiter", 3: "Dritter", 4: "Vierter", 5: "Fünfter"}


def _placing(rank: int) -> str:
    word = PLACING_WORDS.get(rank)
    return f"wurde {word}" if word else f"kam als {rank}. ins Ziel"


def _biggest_incident(events: Sequence[RaceEvent]) -> RaceEvent | None:
    """Der Zwischenfall, der am meisten gekostet hat.

    Nicht der erste und nicht der letzte: Wer von einem Rennen einen Satz
    erzählt, erzählt von dem Halt, der es entschieden hat.
    """
    incidents = [e for e in events if e.type == INCIDENT]
    if not incidents:
        return None
    worst = max(incidents, key=lambda e: float(e.payload.get("stop_s", 0.0)))
    if float(worst.payload.get("stop_s", 0.0)) < NOTABLE_LOSS_S:
        return None
    return worst


def _further_incidents(
    events: Sequence[RaceEvent], biggest: RaceEvent | None
) -> list[str]:
    """Die übrigen nennenswerten Zwischenfälle, in Reihenfolge.

    Zusammengefasst, sobald es mehr als einer ist: Drei Nebensätze über
    drei Platten hintereinander erzählen nichts, was „drei weitere
    Halte, zusammen 40 min" nicht besser sagt.
    """
    rest = [
        e
        for e in events
        if e.type == INCIDENT
        and e is not biggest
        and float(e.payload.get("stop_s", 0.0)) >= NOTABLE_LOSS_S
    ]
    if not rest:
        return []
    total = sum(float(e.payload.get("stop_s", 0.0)) for e in rest)
    if len(rest) == 1:
        spec = CATALOG.get(str(rest[0].payload.get("typ", "")))
        cause = spec.as_cause() if spec else "einen weiteren Zwischenfall"
        return [f"hielt bei {_km(rest[0].payload.get('dist_km', 0))} noch einmal {_minutes(total)} für {cause}"]
    return [f"verlor an {len(rest)} weiteren Halten zusammen {_minutes(total)}"]


def _trajectory(ranks: Sequence[int], splits: Sequence[Any]) -> str:
    """Wie sich die Platzierung über die Splits bewegt hat.

    ``ranks`` ist die Zeile aus ``split_ranks``; 0 heißt „nicht erreicht".
    """
    seen = [(i, int(r)) for i, r in enumerate(ranks) if int(r) > 0]
    if len(seen) < 3:
        return ""
    first_rank = seen[0][1]
    last_idx, last_rank = seen[-1]
    best_idx, best_rank = min(seen, key=lambda pair: pair[1])

    # Einbruch: Das beste Ergebnis lag vor dem Ende, danach ging es
    # deutlich zurück.
    if last_rank - best_rank >= MOVE_PLACES and best_idx < last_idx:
        where = splits[best_idx].name if best_idx < len(splits) else ""
        lost = last_rank - best_rank
        return f"lag bei {where} auf Rang {best_rank} und verlor danach {lost} Plätze"
    # Aufholjagd über die Distanz.
    if first_rank - last_rank >= MOVE_PLACES:
        return f"arbeitete sich von Rang {first_rank} auf {last_rank} vor"
    if abs(first_rank - last_rank) <= 1:
        return f"hielt Rang {last_rank} über die ganze Distanz"
    return ""


def _standing_time(entry: Any, biggest_stop_s: float = 0.0) -> str:
    """Standzeit, aufgeschlüsselt nach Zwischenfall und Notschlaf.

    „Vier Stunden verloren" ist eine ganz andere Geschichte als „vier
    Stunden verloren, davon dreieinhalb am Straßenrand geschlafen" — und
    beide Zahlen stehen seit der Trennung von ``lost_s`` und
    ``lost_incident_s`` in jedem Ergebnis.
    """
    total = float(getattr(entry, "lost_s", 0.0) or 0.0)
    if total < NOTABLE_LOSS_S:
        return ""
    incidents = float(getattr(entry, "lost_incident_s", 0.0) or 0.0)
    sleep = max(total - incidents, 0.0)
    if sleep < NOTABLE_LOSS_S:
        # War der größte Halt praktisch die ganze Standzeit, steht sie
        # schon im Satz davor. „Verlor 14 min durch eine Sperrung, stand
        # insgesamt 14 min" sagt dieselbe Zahl zweimal.
        if total - biggest_stop_s < NOTABLE_LOSS_S:
            return ""
        return f"stand insgesamt {_minutes(total)}"
    if incidents < NOTABLE_LOSS_S:
        return f"stand insgesamt {_minutes(total)}, fast alles Notschlaf"
    return (
        f"stand insgesamt {_minutes(total)}, davon {_minutes(sleep)} Notschlaf "
        f"und {_minutes(incidents)} an Zwischenfällen"
    )


def build_report(
    entry: Any,
    events: Sequence[RaceEvent],
    ranks: Sequence[int],
    splits: Sequence[Any],
    winner_margin_s: float | None = None,
    name: str = "",
    detail: bool = False,
) -> RaceReport:
    """Bericht für einen einzelnen Fahrer.

    ``events`` sind **seine** Ereignisse, ``ranks`` **seine** Zeile aus
    ``split_ranks``. ``detail`` schaltet die lange Fassung frei: mehr
    Bausteine, und die Dinge, für die im Einzeiler kein Platz ist —
    jeder nennenswerte Zwischenfall statt nur des größten, der
    Radwechsel, die aufgeschlüsselte Standzeit.
    """
    limit = MAX_CLAUSES_LONG if detail else MAX_CLAUSES
    clauses: list[str] = []

    incident = _biggest_incident(events)
    if incident is not None:
        spec = CATALOG.get(str(incident.payload.get("typ", "")))
        cause = spec.as_cause() if spec else incident.payload.get("label", "einen Zwischenfall")
        lost = _minutes(float(incident.payload.get("stop_s", 0.0)))
        clauses.append(f"verlor {lost} durch {cause} bei {_km(incident.payload.get('dist_km', 0))}")

    if detail:
        clauses.extend(_further_incidents(events, incident))

    bonk = next((e for e in events if e.type == BONK), None)
    if bonk is not None:
        clauses.append(f"kam bei {_km(bonk.payload.get('dist_km', 0))} in den Hungerast")

    sleeps = [e for e in events if e.type == SLEEP]
    if sleeps:
        total = sum(float(e.payload.get("duration_s", 0.0)) for e in sleeps)
        count = "einmal" if len(sleeps) == 1 else f"{len(sleeps)}-mal"
        clauses.append(f"schlief {count}, zusammen {_minutes(total)}")

    chase = next(
        (e for e in events if e.type == DECISION and e.payload.get("rule") == "aufholen"),
        None,
    )
    if chase is not None and incident is None:
        clauses.append(f"ging bei {_km(chase.payload.get('dist_km', 0))} in die Aufholjagd")

    if detail:
        bike = next((e for e in events if e.type == BIKE_CHANGE), None)
        if bike is not None:
            target = "aufs Zeitfahrrad" if bike.payload.get("bike") == "tt" else "aufs Straßenrad"
            clauses.append(f"wechselte bei {_km(bike.payload.get('dist_km', 0))} {target}")
        biggest_stop = (
            0.0 if incident is None else float(incident.payload.get("stop_s", 0.0))
        )
        standing = _standing_time(entry, biggest_stop)
        if standing:
            clauses.append(standing)

    trajectory = _trajectory(ranks, splits)
    if trajectory:
        clauses.append(trajectory)

    # Der Ausgang steht immer am Ende und zählt nicht gegen die Obergrenze:
    # Ein Bericht, der nicht sagt, wie es ausging, ist keiner.
    if entry.finish_time_s is None:
        reason = (entry.dnf_reason or "").split(":")[-1].strip()
        where = _km((entry.dnf_dist_m or 0.0) / 1000.0)
        tail = f"gab bei {where} auf" + (f" ({reason})" if reason else "")
        clauses = clauses[: limit - 1] + [tail]
    elif entry.rank == 1:
        margin = f" mit {_minutes(winner_margin_s)} Vorsprung" if winner_margin_s else ""
        clauses = clauses[: limit - 1] + [f"gewann{margin}"]
    elif entry.rank is not None:
        clauses = clauses[: limit - 1] + [_placing(int(entry.rank))]

    return RaceReport(entry_id=entry.entry_id, clauses=clauses, name=name)


def build_reports(
    entries: Sequence[Any],
    events: Sequence[RaceEvent],
    split_ranks: Any,
    splits: Sequence[Any],
    names: dict[int, str] | None = None,
    detail_ranks: int = 0,
) -> dict[int, RaceReport]:
    """Berichte für ein ganzes Feld, nach ``entry_id``.

    ``detail_ranks`` schaltet die lange Fassung für die vordersten Ränge
    frei — 3 heißt: Podium ausführlich, der Rest in einem Satz.
    """
    by_entry: dict[int, list[RaceEvent]] = {}
    for event in events:
        by_entry.setdefault(event.entry_id, []).append(event)

    times = sorted(e.finish_time_s for e in entries if e.finish_time_s is not None)
    margin = times[1] - times[0] if len(times) >= 2 else None

    out: dict[int, RaceReport] = {}
    for entry in entries:
        ranks = split_ranks[entry.entry_id] if entry.entry_id < len(split_ranks) else []
        out[entry.entry_id] = build_report(
            entry,
            sorted(by_entry.get(entry.entry_id, []), key=lambda e: e.t_s),
            ranks,
            splits,
            winner_margin_s=margin if entry.rank == 1 else None,
            name=(names or {}).get(entry.entry_id, ""),
            detail=bool(detail_ranks and entry.rank and entry.rank <= detail_ranks),
        )
    return out
