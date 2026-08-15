"""Ein Rennen live rechnen statt vorab (Abschnitt 8.1).

Bis hierher lief jedes Rennen einmal komplett durch, wurde als
Telemetrie auf die Platte geschrieben und danach abgespielt. Das ist
für Saison, Karriere und Kalibrierung genau richtig — dort schaut
niemand zu, dort zählt der Durchsatz.

Beim Zuschauen ist es die falsche Reihenfolge: Ein Ultra mit 250
Fahrern rechnet knapp eine Minute, bevor das erste Bild steht.

Die Rechenzeit ist dabei nie das Problem gewesen. Gemessen schafft die
Engine zwischen 1900- und 5400-facher Echtzeit — die Oberfläche bietet
höchstens 1000-fachen Zeitraffer, es bleibt also mindestens die
doppelte Reserve, selbst mit vollem Feld auf der Ultradistanz:

    Voralpen 300 km    40 Fahrer  4262x     250 Fahrer  1907x
    Hochgebirge 507 km 40 Fahrer  5077x     250 Fahrer  2805x
    Nordroute 1230 km  40 Fahrer  5403x     250 Fahrer  3110x

Das Problem war, dass ``simulate_race`` nicht anhalten konnte. Seit sie
ein Generator ist, kann sie es — und dieses Modul ist der Treiber, der
sie an der Wiedergabeuhr zieht.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..geo.route import Route
from .engine import RaceConfig, RaceResult, run_race
from .rider import Rider, Team


@dataclass
class LiveRace:
    """Zieht ein Rennen so weit, wie die Uhr des Zuschauers steht.

    Der Vertrag ist bewusst schmal: ``advance_to(t)`` rechnet bis
    mindestens zur Rennsekunde ``t`` und sagt, wie weit es gekommen
    ist. Alles Weitere — Board, Rangliste, Telemetrie — liest danach
    aus denselben Arrays wie bei einem gespeicherten Rennen.

    Vorausgerechnet wird bewusst *nicht* auf Verdacht. Wer bei
    einfacher Geschwindigkeit zuschaut, soll nicht dieselbe Last
    erzeugen wie bei tausendfacher; und wer das Fenster schließt, soll
    keine Rechenzeit hinterlassen.
    """

    route: Route
    riders: list[Rider]
    teams: list[Team]
    config: RaceConfig

    #: Bis hierher ist gerechnet, in Rennsekunden.
    sim_t: float = 0.0
    #: Steht, sobald das Rennen durch ist — dann ist ``advance_to`` ein
    #: No-op und alles liegt vor wie bei einem gespeicherten Rennen.
    result: RaceResult | None = None

    _gen: Any = None

    def __post_init__(self) -> None:
        self._gen = run_race(self.route, self.riders, self.teams, self.config)

    @property
    def finished(self) -> bool:
        return self.result is not None

    def advance_to(self, t_s: float) -> float:
        """Bis mindestens zur Rennsekunde ``t_s`` rechnen.

        Gibt die erreichte Rennzeit zurück. Sie kann über ``t_s``
        liegen — der Generator hält nur an festen Tickgrenzen an —, und
        sie kann darunter liegen, wenn das Rennen vorher zu Ende ist.
        """
        if self._gen is None or self.sim_t >= t_s:
            return self.sim_t
        try:
            while self.sim_t < t_s:
                self.sim_t = float(next(self._gen))
        except StopIteration as stop:
            self.result = stop.value
            self._gen = None
            if self.result is not None:
                done = [e.finish_time_s for e in self.result.entries if e.finish_time_s]
                self.sim_t = max(done) if done else self.sim_t
        return self.sim_t

    def advance_by_wall(self, wall_dt_s: float, speed: int) -> float:
        """Einen Wiedergabeschritt nachrechnen.

        ``speed`` ist die Zeitrafferstufe: Bei 60x sind sechzig
        Rennsekunden je Sekunde Wanduhr zu rechnen.
        """
        if wall_dt_s <= 0.0 or speed <= 0:
            return self.sim_t
        return self.advance_to(self.sim_t + wall_dt_s * float(speed))
