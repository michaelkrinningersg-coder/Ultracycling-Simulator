"""Rennen, die erst entstehen, während man zusieht (Abschnitt 8.2).

Bis hierher war die Reihenfolge: rechnen, speichern, abspielen. Der
Playback-Server aus ``playback.py`` bekommt ein fertiges Rennen und
schneidet es an seiner Wanduhr ab — die Selbstbeschränkung „nie Daten
aus der Zukunft" ist dort eine *Zusage*, weil die Zukunft physisch
vorliegt.

Hier liegt sie nicht vor. Ein ``LiveRoom`` hält statt eines Ergebnisses
einen angehaltenen Generator und zieht ihn genau so weit, wie die Uhr
des Zuschauers steht. Damit ist die Zusage keine Zusage mehr, sondern
eine Tatsache: Was nicht gerechnet ist, kann auch nicht verraten werden.

Drei Dinge muss dieses Modul dafür leisten:

**Übersetzen.** Alles über dem Playback-Server — Board, Rangliste,
Ereignisticker, Höhenprofil — arbeitet mit ``RaceResult`` und
``RaceView``. Ein laufendes Rennen muss deshalb genauso aussehen. Das
tut es: ``LiveSnapshot.result()`` baut aus den Arbeitsdaten der Engine
ein ``RaceResult`` mit dem Stand von jetzt, und daraus wird eine ganz
gewöhnliche ``RaceView``.

**Serialisieren.** Ein Generator verträgt keine zwei gleichzeitigen
``next``-Aufrufe, und ein Webserver liefert genau das: Der SSE-Strom
zieht Bilder, während ein Klick auf „Sprung zum nächsten Ereignis"
hereinkommt. Ein Schloss je Rennen genügt — mehr wäre falsch, weniger
wäre ein ``ValueError: generator already executing``.

**Sichern.** Ein Rennen, das nur im Speicher entsteht, ist beim
Neustart weg. Deshalb wird der Zwischenstand regelmäßig unter derselben
Renn-ID abgelegt, unter der ein gerechnetes Rennen läge — mit
Platzierungen, Splitzeiten und Telemetrie bis zu diesem Punkt. Wer die
Seite später wieder aufruft, bekommt das gespeicherte Rennen und merkt
den Unterschied nicht.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..core.engine import RaceConfig, RaceResult
from ..core.live import LiveRace
from ..core.rider import Rider, Team
from ..geo.route import Route
from .playback import RaceView

#: So oft wird der Zwischenstand auf die Platte geschrieben, in Sekunden
#: Serverwanduhr. Bei 250 Fahrern kostet ein Schreibvorgang gut eine
#: Sekunde (die Telemetrie wird komprimiert), bei vierzig Bruchteile
#: davon. Zwanzig Sekunden sind der Kompromiss: selten genug, um die
#: Wiedergabe nicht zu stören, oft genug, dass ein Absturz höchstens
#: zwanzig Sekunden Zuschauen kostet — nicht zwanzig Stunden Rennen.
SAVE_INTERVAL_S = 20.0

#: Sicherheitsaufschlag auf die geschätzte Renndauer, solange die echte
#: nicht feststeht. Der Zeitstrahl braucht ein Ende, auch wenn es noch
#: keins gibt.
HORIZON_MARGIN = 1.15


@dataclass
class LiveRoom:
    """Ein laufendes Rennen und alles, was daran hängt."""

    race_id: str
    route_id: str
    route: Route
    live: LiveRace
    store: Any = None

    #: Zuletzt gebaute Leseschicht und die Rennzeit, aus der sie stammt.
    _view: tuple[RaceResult, Route, RaceView] | None = None
    _view_t: float = -1.0
    _saved_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ------------------------------------------------------------------
    @classmethod
    def start(
        cls,
        race_id: str,
        route_id: str,
        route: Route,
        riders: list[Rider],
        teams: list[Team],
        config: RaceConfig,
        store: Any = None,
    ) -> LiveRoom:
        return cls(
            race_id=race_id,
            route_id=route_id,
            route=route,
            live=LiveRace(route, list(riders), list(teams), config),
            store=store,
        )

    # ------------------------------------------------------------------
    @property
    def finished(self) -> bool:
        return self.live.finished

    @property
    def horizon_s(self) -> float:
        """Das rechte Ende des Zeitstrahls, in Renn-Wanduhrzeit.

        Nach dem Ziel die Wahrheit. Davor eine Schätzung aus dem
        Zeitrahmen des Rennens plus dem Start des letzten Fahrers —
        großzügig, weil ein zu kurzer Zeitstrahl die Wiedergabe vor dem
        Ende anhalten würde, ein zu langer aber nur einen Balken
        verzieht.
        """
        result = self.live.result
        if result is not None:
            return result.last_finish_wallclock_s
        config = self.live.config
        max_hours = config.max_hours or max(3.0, self.route.distance_km / 11.0)
        last_start = 0.0
        snapshot = self.live.snapshot
        if snapshot is not None and snapshot.starters:
            last_start = max(offset for _, _, _, offset in snapshot.starters)
        return last_start + max_hours * 3600.0 * HORIZON_MARGIN

    # ------------------------------------------------------------------
    def advance(self, t_wall: float) -> None:
        """Bis zur Wanduhrzeit ``t_wall`` rechnen.

        Die Engine zählt in Fahrer-Eigenzeit ab dem eigenen Start, die
        Wiedergabe in Wanduhrzeit ab dem ersten Starter. Weil kein
        Startversatz negativ ist, ist die Eigenzeit nie größer als die
        Wanduhrzeit — bis ``t_wall`` zu rechnen deckt also jeden Fahrer
        ab, den es bis dahin zu zeigen gibt.
        """
        with self._lock:
            if self.live.finished:
                return
            self.live.advance_to(t_wall)
            self._maybe_save()

    def bundle(self) -> tuple[RaceResult, Route, RaceView]:
        """Ergebnis, Strecke und Leseschicht zum aktuellen Stand.

        Neu gebaut wird nur, wenn seit dem letzten Mal gerechnet wurde.
        Die Telemetrie kommt dabei als Sicht auf die Puffer der Engine
        ins Ergebnis, nicht als Kopie; teuer sind die Ereignisliste und
        die Splitränge, und die sind es erst bei einem vollen Feld.
        """
        with self._lock:
            if self._view is None or self.live.sim_t > self._view_t:
                result = self.live.current()
                if result is None:  # noch kein einziger Tick gerechnet
                    result = self._empty_result()
                self._view = (result, self.route, RaceView(result, self.route))
                self._view_t = self.live.sim_t
            return self._view

    # ------------------------------------------------------------------
    def _empty_result(self) -> RaceResult:
        """Der Stand vor dem ersten Tick.

        Der Generator läuft bis zum ersten ``yield`` nicht an, und bis
        dahin gibt es keine Startliste. Statt hier einen Sonderfall in
        die Oberfläche zu tragen, wird ein einzelner Halt vorgezogen —
        das sind zehn Minuten Rennzeit und kostet nichts.
        """
        self.live.advance_to(1.0)
        result = self.live.current()
        assert result is not None  # nach einem Halt steht der Schnappschuss
        return result

    def _maybe_save(self, force: bool = False) -> None:
        if self.store is None:
            return
        now = time.monotonic()
        if not force and not self.live.finished and now - self._saved_at < SAVE_INTERVAL_S:
            return
        result = self.live.current()
        if result is None:
            # Noch kein Tick gerechnet. Statt nichts zu speichern, einen
            # Halt vorziehen: Ein Rennen, von dem noch keine Datei
            # existiert, taucht in keiner Übersicht auf — und wäre damit
            # für den Nutzer verschwunden, sobald er zurückgeht.
            result = self._empty_result()
        self.store.save_race(self.race_id, self.route_id, result, route=self.route)
        self._saved_at = now

    def save(self) -> None:
        """Zwischenstand sofort sichern, ohne auf den Takt zu warten."""
        with self._lock:
            self._maybe_save(force=True)

    def summary(self) -> dict[str, Any]:
        """Eine Zeile für die Übersicht, in der Form von ``list_races``."""
        result = self.live.current()
        finish = [
            e.finish_time_s for e in (result.entries if result else []) if e.finish_time_s
        ]
        return {
            "race_id": self.race_id,
            "route_id": self.route_id,
            "route_name": self.route.name,
            "name": self.live.config.name or self.race_id,
            "seed": self.live.config.seed,
            "n_entries": len(self.live.riders),
            "winner_time_s": min(finish) if finish else None,
            "live": not self.finished,
        }


class LiveRegistry:
    """Alle laufenden Rennen des Prozesses."""

    def __init__(self, max_rooms: int = 3) -> None:
        self._rooms: dict[str, LiveRoom] = {}
        self._max = max_rooms

    def add(self, room: LiveRoom) -> LiveRoom:
        self._rooms[room.race_id] = room
        # Sofort einmal sichern. Damit existiert die Renndatei, bevor
        # der erste Zuschauer da ist — und der Schlüssel ist belegt,
        # auch für einen Prozess, der diese Registry nicht kennt.
        room.save()
        # Ein laufendes Rennen hält das ganze Feld samt Telemetriepuffer
        # im Speicher. Wer ein viertes aufmacht, verliert das älteste —
        # aber erst, nachdem sein Stand auf der Platte liegt.
        while len(self._rooms) > self._max:
            _, oldest = next(iter(self._rooms.items()))
            self.close(oldest.race_id)
        return room

    def get(self, race_id: str) -> LiveRoom | None:
        return self._rooms.get(race_id)

    def close(self, race_id: str) -> None:
        room = self._rooms.pop(race_id, None)
        if room is not None:
            room.save()

    def ids(self) -> list[str]:
        return list(self._rooms)
