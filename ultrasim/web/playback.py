"""Playback-Server (Game-Design-Dokument, Abschnitt 8.2).

Das Rennen ist beim Start komplett durchgerechnet. Ein Playback-Server
streamt daraus mit einer eigenen Wanduhr:

    sim_zeit = start + (jetzt − t0) · zeitraffer

Das fühlt sich nicht nur wie live an, es kann mehr als echtes Live:
Pause, Zeitraffer 1×–1000×, Rücksprung, Sprung zum nächsten Ereignis.

**Die zentrale Selbstbeschränkung:** Der Client darf nie Daten aus der
Zukunft erhalten, auch nicht im Puffer – sonst verrät ein Bug die
Endzeiten. Deshalb besitzt der *Server* die Uhr, nicht der Client. Alle
Abfragen werden serverseitig an ``now()`` abgeschnitten; ein Client, der
eine spätere Zeit anfragt, bekommt trotzdem nur die Gegenwart.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..core.engine import STATE_DNF, STATE_FINISHED, RaceResult, Telemetry
from ..core.events import (
    BEST_TIME,
    DECISION,
    DNF,
    DRAMATIC_EVENTS,
    MAJOR_EVENTS,
    RaceEvent,
)
from ..geo.route import Route

#: Angebotene Zeitrafferstufen.
SPEEDS = (1, 5, 10, 30, 60, 300, 1000)

#: Ab dieser Stufe werden nur noch die wichtigen Ereignisse gestreamt –
#: sonst erstickt der Client am Ereignisstrom (Abschnitt 8.2).
MAJOR_ONLY_ABOVE = 60

#: Fenstergröße des Telemetrie-Boards (Abschnitt 9.1).
BOARD_WINDOW = 41

#: Höchstens so viele Fahrer lassen sich gleichzeitig anheften. Zwei,
#: weil ein Duell aus zwei Fahrern besteht — bei dreien ist es ein
#: Klassement, und dafür gibt es das Board.
MAX_PINNED = 2

#: Sortierschlüssel des Boards: Anzeigename → Feld der Zeile.
#:
#: ``"zeit"`` fehlt bewusst — das ist die gewachsene Reihenfolge aus
#: gemessenen und laufenden Uhren, und die entsteht nicht durch
#: Sortieren nach einem Feld, sondern durch die Zeitnahme selbst.
SORT_FIELDS: dict[str, str] = {
    "nr": "bib",
    "name": "name",
    "team": "team",
    "km": "dist_km",
    "biscp": "to_next_m",
    "tempo": "v_kmh",
    "leistung": "power_w",
    "form": "form_pct",
    "wprime": "wprime_pct",
    "glyko": "glyco_pct",
    "schlaf": "sleep_pct",
    "wasser": "hydration_pct",
    "aufgabe": "giveup_pct",
    "trend": "trend",
    "rueckstand": "gap_s",
}


@dataclass
class PlaybackSession:
    """Zustand einer Betrachtung. Die Uhr gehört dem Server."""

    race_id: str
    sim_t: float = 0.0  # Wanduhr des Rennens in Sekunden seit dem ersten Start
    speed: int = 60
    playing: bool = False
    focus_entry: int = 0
    split_idx: int = 0
    #: Solange True, folgt das Board dem zuletzt passierten Split des
    #: Fokusfahrers. Eine Handauswahl im Splitmenü schaltet das ab –
    #: sonst würde die Auswahl beim nächsten Frame wieder wegspringen.
    split_follow: bool = True
    mode: str = "split"  # split | virtual
    #: Nach welcher Spalte das Board sortiert ist. ``"zeit"`` ist die
    #: Zeitnahme selbst — jede andere Wahl ordnet dieselben Zeilen um,
    #: ohne die Platzziffern anzutasten.
    sort: str = "zeit"
    sort_desc: bool = False
    #: Angeheftete Fahrer: stehen über dem Board, egal wo sie liegen.
    pinned: list[int] = field(default_factory=list)
    #: Automatischer Fokus: Der Server wählt den Fahrer, bei dem gerade
    #: etwas passiert ist. Aus wie ``split_follow``, sobald der Nutzer
    #: selbst jemanden anklickt — eine Regie, die sich nicht abschalten
    #: lässt, ist keine Hilfe, sondern eine Entmündigung.
    auto_focus: bool = False
    anchor: float = field(default_factory=time.monotonic)
    horizon_s: float = 0.0  # Ende des Rennens; darüber hinaus läuft nichts

    def toggle_pin(self, entry_id: int) -> None:
        """Anheften oder lösen; der älteste Pin weicht dem dritten Fahrer."""
        if entry_id in self.pinned:
            self.pinned.remove(entry_id)
            return
        self.pinned.append(entry_id)
        del self.pinned[:-MAX_PINNED]

    # ------------------------------------------------------------------
    def now(self) -> float:
        """Aktuelle Renn-Wanduhrzeit."""
        if self.playing:
            elapsed = time.monotonic() - self.anchor
            self.sim_t = min(self.sim_t + elapsed * self.speed, self.horizon_s)
            self.anchor = time.monotonic()
            if self.sim_t >= self.horizon_s:
                self.playing = False
        return self.sim_t

    def _sync(self) -> None:
        """Uhr einfrieren, bevor ein Parameter geändert wird."""
        self.now()
        self.anchor = time.monotonic()

    def play(self) -> None:
        self._sync()
        if self.sim_t < self.horizon_s:
            self.playing = True

    def pause(self) -> None:
        self._sync()
        self.playing = False

    def set_speed(self, speed: int) -> None:
        self._sync()
        self.speed = int(np.clip(speed, 1, 1000))

    def seek(self, sim_t: float) -> None:
        self._sync()
        self.sim_t = float(np.clip(sim_t, 0.0, self.horizon_s))

    def set_horizon(self, horizon_s: float) -> None:
        """Das Ende des Zeitstrahls verschieben.

        Bei einem live gerechneten Rennen steht es erst fest, wenn der
        letzte im Ziel ist; bis dahin läuft die Wiedergabe gegen eine
        großzügige Schätzung. Wird sie durch die Wahrheit ersetzt, muss
        die Uhr mit — sonst stünde sie hinter dem Rennende.
        """
        self.horizon_s = float(horizon_s)
        if self.sim_t > self.horizon_s:
            self.sim_t = self.horizon_s

    def frame_interval_s(self) -> float:
        """Realzeit zwischen zwei Frames.

        Bei hohem Zeitraffer wird nicht häufiger gesendet, sondern
        gröber: Die Aggregation passiert serverseitig, statt alles zu
        senden und den Client filtern zu lassen. Bei 250 Fahrern ist das
        der Unterschied zwischen flüssig und unbenutzbar.
        """
        if self.speed <= 10:
            return 0.25
        if self.speed <= 60:
            return 0.5
        return 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_t": round(self.now(), 2),
            "speed": self.speed,
            "playing": self.playing,
            "focus_entry": self.focus_entry,
            "split_idx": self.split_idx,
            "split_follow": self.split_follow,
            "mode": self.mode,
            "sort": self.sort,
            "sort_desc": self.sort_desc,
            "pinned": list(self.pinned),
            "auto_focus": self.auto_focus,
            "horizon_s": round(self.horizon_s, 1),
        }


class PlaybackRegistry:
    """Alle offenen Betrachtungen im Prozess."""

    def __init__(self) -> None:
        self._sessions: dict[str, PlaybackSession] = {}

    def create(self, race_id: str, horizon_s: float, split_idx: int = 0) -> tuple[str, PlaybackSession]:
        token = uuid.uuid4().hex[:16]
        session = PlaybackSession(race_id=race_id, horizon_s=horizon_s, split_idx=split_idx)
        self._sessions[token] = session
        return token, session

    def get(self, token: str) -> PlaybackSession | None:
        return self._sessions.get(token)

    def drop(self, token: str) -> None:
        self._sessions.pop(token, None)

    def prune(self, max_sessions: int = 64) -> None:
        while len(self._sessions) > max_sessions:
            self._sessions.pop(next(iter(self._sessions)))


# ----------------------------------------------------------------------
# Auswertung eines Zeitpunkts
# ----------------------------------------------------------------------
class RaceView:
    """Leseschicht über ein gerechnetes Rennen.

    Kapselt jeden Zugriff auf die Telemetrie so, dass er an der
    Wanduhrzeit abgeschnitten ist.
    """

    def __init__(self, result: RaceResult, route: Route) -> None:
        self.result = result
        self.route = route
        self.telemetry: Telemetry = result.telemetry
        self.offsets = np.array([e.start_offset_s for e in result.entries])
        self.n = len(result.entries)
        self.riders = {r.id: r for r in result.riders}
        self.teams = {t.id: t for t in result.teams}
        self.split_dist = np.array([s.dist_m for s in route.splits])
        # Ereignisse nach Wanduhrzeit sortiert – so lässt sich der
        # Ausschnitt "seit dem letzten Frame" mit zwei Bisektionen finden.
        self._events = sorted(
            list(result.events) + self._best_time_events(),
            key=lambda e: e.t_s + result.entries[e.entry_id].start_offset_s,
        )
        self._event_wall = np.array(
            [e.t_s + result.entries[e.entry_id].start_offset_s for e in self._events]
        )
        # Zustände je Fahrer vorsortieren: das Board fragt sie bei 250
        # Zeilen und mehreren Frames pro Sekunde ab, ein Listendurchlauf
        # über alle Zustände des Rennens wäre dafür die falsche Antwort.
        self._conditions: dict[int, list] = {}
        for record in result.conditions:
            self._conditions.setdefault(record.entry_id, []).append(record)
        # Entscheidungen je Fahrer, in Eigenzeit sortiert.
        self._decisions: dict[int, list[RaceEvent]] = {}
        for event in result.events:
            if event.type == DECISION:
                self._decisions.setdefault(event.entry_id, []).append(event)
        for records in self._decisions.values():
            records.sort(key=lambda e: e.t_s)
        # Wann für einen Fahrer Schluss war – Ziel oder Aufgabe. Danach
        # laufen weder Zustände noch Taktiken weiter: Ein Aufgeber, der
        # in der Anzeige immer noch "Aufholjagd" trägt, sagt das
        # Gegenteil dessen, was passiert ist.
        self._end_t: dict[int, float] = {
            i: e.finish_time_s
            for i, e in enumerate(result.entries)
            if e.finish_time_s is not None
        }
        for event in result.events:
            if event.type == DNF:
                self._end_t.setdefault(event.entry_id, event.t_s)

    # ------------------------------------------------------------------
    def factors_at(self, entry_id: int, t_wall: float) -> dict[str, Any] | None:
        """Woraus sich die Form eines Fahrers gerade zusammensetzt.

        Die Simulation multipliziert ein knappes Dutzend Faktoren zu
        einer Zahl. Die Zahl steht in der Anzeige, die Faktoren nicht —
        und damit beantwortet die Oberfläche „der ist langsam", aber
        nicht „warum". Hier kommen sie zurück, der teuerste zuerst.

        Drei davon sind über das ganze Rennen konstant und stehen
        deshalb am Starter statt in der Telemetrie: Saisonform, Tagesform
        und die Frische, mit der er ins Rennen gegangen ist.

        ``None`` für Rennen, die vor der Faktoraufzeichnung entstanden
        sind — dann sagt die Oberfläche das, statt zu raten.
        """
        factors = self.telemetry.factors
        if not factors:
            return None
        entry = self.result.entries[entry_id]
        elapsed = self._elapsed(entry_id, t_wall)
        if elapsed < 0.0:
            return None
        idx = int(self.sample_idx(np.array([elapsed]))[0])

        rows = [
            {"key": "season", "label": "Saisonform", "pct": round(entry.season_form * 100.0, 1)},
            {"key": "day", "label": "Tagesform", "pct": round(entry.day_form * 100.0, 1)},
            {"key": "fresh", "label": "Frische", "pct": round(entry.freshness * 100.0, 1)},
        ]
        for key, label in Telemetry.FACTOR_LABELS.items():
            channel = factors.get(key)
            if channel is None:
                continue
            rows.append({"key": key, "label": label, "pct": float(channel[entry_id, idx])})

        total = 1.0
        for row in rows:
            total *= float(row["pct"]) / 100.0
        # Nach Kosten sortiert: Was am meisten wegnimmt, steht oben. Wer
        # wissen will, warum einer einbricht, liest sonst zehn Zeilen, von
        # denen neun „100 %" sagen.
        rows.sort(key=lambda r: float(r["pct"]))
        return {"rows": rows, "total_pct": round(total * 100.0, 1)}

    def _best_time_events(self) -> list[RaceEvent]:
        """Bestzeiten als Ereignisse — erzeugt, nicht simuliert.

        Eine Bestzeit ist kein Vorgang auf der Straße, sondern einer in
        der Zeitnahme: Sie entsteht erst dadurch, dass die Zeiten in der
        Reihenfolge eintreffen, in der gestartet wurde. Genau deshalb
        steht das hier und nicht in der Engine — die kennt keine
        Startreihenfolge und keinen Zuschauer.

        Je Split werden die Ankünfte nach **Wanduhr** durchlaufen; wer
        die bis dahin beste Zeit unterbietet, bekommt ein Ereignis. Der
        erste an einer Marke ist immer dabei, sonst fehlte im Ticker
        genau der Moment, in dem eine Zeit überhaupt erst entsteht.
        """
        out: list[RaceEvent] = []
        times = self.result.split_times_s
        if times.size == 0:
            return out
        for split_idx, split in enumerate(self.route.splits):
            column = times[:, split_idx]
            arrival = self.offsets + column
            order = np.argsort(np.where(np.isfinite(arrival), arrival, np.inf), kind="stable")
            best = np.inf
            for entry_id in order:
                value = float(column[entry_id])
                if not np.isfinite(value):
                    break  # ab hier hat niemand mehr eine Zeit
                if value >= best:
                    continue
                out.append(
                    RaceEvent(
                        entry_id=int(entry_id),
                        t_s=value,
                        type=BEST_TIME,
                        payload={
                            "split_idx": split_idx,
                            "split_name": split.name,
                            "margin_s": None if best == np.inf else round(best - value, 1),
                            "first": best == np.inf,
                        },
                    )
                )
                best = value
        return out

    def _elapsed(self, entry_id: int, t_wall: float) -> float:
        """Eigenzeit eines Fahrers, abgeschnitten an seinem Rennende."""
        elapsed = t_wall - self.offsets[entry_id]
        end = self._end_t.get(entry_id)
        return min(elapsed, end) if end is not None else elapsed

    def conditions_at(self, entry_id: int, t_wall: float, only_active: bool = False) -> list[dict[str, Any]]:
        """Zustände eines Fahrers, abgeschnitten an der Wanduhr.

        Ein Zustand, der noch nicht begonnen hat, existiert für den
        Zuschauer nicht – und ein laufender endet für ihn *jetzt*, nicht
        an seinem späteren echten Ende. Sonst verriete der Balken über dem
        Profil, wie lange der Einbruch noch dauert.
        """
        # Wer im Ziel ist oder aufgegeben hat, trägt keine laufenden
        # Zustände mehr: Sonst schleppte ein Fahrer seine Magenprobleme
        # noch stundenlang als Chip durch die Ergebnisliste.
        elapsed = self._elapsed(entry_id, t_wall)
        out: list[dict[str, Any]] = []
        for record in self._conditions.get(entry_id, ()):
            if record.start_t_s > elapsed:
                continue
            end_t = record.end_t_s
            end_d = record.end_dist_m
            active = end_t is None or end_t > elapsed
            if only_active and not active:
                continue
            out.append(
                {
                    "typ": record.typ,
                    "label": record.label,
                    "start_t_s": record.start_t_s,
                    "start_dist_m": record.start_dist_m,
                    "end_t_s": min(end_t, elapsed) if end_t is not None else elapsed,
                    "end_dist_m": (
                        end_d
                        if end_d is not None and not active
                        else float(self._dist_now(entry_id, elapsed))
                    ),
                    "active": active,
                    "reason": record.reason,
                }
            )
        return out

    def tactics_at(self, entry_id: int, t_wall: float) -> list[str]:
        """Regeln des Strategiemoduls, die gerade greifen (Abschnitt 7.2).

        Abgeleitet aus dem Entscheidungsstrom statt aus einem eigenen
        Telemetriekanal: Entscheidungen sind selten — ein Dutzend je
        Rennen und Fahrer — und ein Kanal über 400.000 Ticks für ein
        Dutzend Umschaltungen wäre die falsche Rechnung. Der Strom ist
        ohnehin schon an der Wanduhr abgeschnitten.
        """
        elapsed = self._elapsed(entry_id, t_wall)
        active: dict[str, str] = {}
        for record in self._decisions.get(entry_id, ()):
            if record.t_s > elapsed:
                break
            key = record.payload.get("rule", "")
            if record.payload.get("on"):
                active[key] = record.payload.get("label", key)
            else:
                active.pop(key, None)
        return list(active.values())

    def condition_labels(self, entry_id: int, t_wall: float) -> list[str]:
        """Chips für die Board-Zeile: aktive Zustände, ohne Dopplung.

        Zwei überlappende Magenphasen sind im Modell zwei Zustände, in
        der Zeile aber ein Zustand — dreimal "Magenprobleme" nebeneinander
        sagt nicht mehr als einmal und sprengt die Spalte.
        """
        out: list[str] = []
        for record in self.conditions_at(entry_id, t_wall, only_active=True):
            if record["label"] not in out:
                out.append(record["label"])
        return out

    def _dist_now(self, entry_id: int, elapsed: float) -> float:
        idx = self.sample_idx(np.array([max(elapsed, 0.0)]))[0]
        return float(self.telemetry.dist_m[entry_id, idx])

    # ------------------------------------------------------------------
    def elapsed(self, t_wall: float) -> np.ndarray:
        """Eigenzeit je Fahrer; negativ bedeutet: noch nicht gestartet."""
        return t_wall - self.offsets

    def sample_idx(self, elapsed: np.ndarray) -> np.ndarray:
        return np.clip(
            (elapsed / self.telemetry.sample_dt_s).astype(np.int64),
            0,
            self.telemetry.n_samples - 1,
        )

    def snapshot(self, t_wall: float) -> dict[str, np.ndarray]:
        """Position und Zustand aller Fahrer zur Wanduhrzeit ``t_wall``."""
        elapsed = self.elapsed(t_wall)
        started = elapsed >= 0.0
        idx = self.sample_idx(elapsed)
        rows = np.arange(self.n)
        dist = self.telemetry.dist_m[rows, idx].astype(np.float64)
        v = self.telemetry.v_cms[rows, idx].astype(np.float64) / 100.0
        power = self.telemetry.power_w[rows, idx].astype(np.float64)
        state = self.telemetry.state[rows, idx].copy()
        bike = self.telemetry.bike[rows, idx]
        form = self.telemetry.form_pct[rows, idx]
        wprime = self.telemetry.wprime_pct[rows, idx]
        glyco = self.telemetry.glyco_pct[rows, idx]
        sleep = self.telemetry.sleep_pct[rows, idx]
        hydration = self.telemetry.hydration_pct[rows, idx]
        giveup = (
            self.telemetry.giveup_pct[rows, idx]
            if self.telemetry.giveup_pct is not None
            else None
        )
        dist[~started] = 0.0
        v[~started] = 0.0
        power[~started] = 0.0
        return {
            "giveup": giveup,
            "started": started,
            "elapsed": elapsed,
            "dist": dist,
            "v": v,
            "power": power,
            "state": state,
            "bike": bike,
            "form": form,
            "wprime": wprime,
            "glyco": glyco,
            "sleep": sleep,
            "hydration": hydration,
        }

    # ------------------------------------------------------------------
    def events_between(self, t_from: float, t_to: float, speed: int, focus: int | None) -> list[RaceEvent]:
        """Ereignisse im Wanduhr-Fenster, serverseitig gefiltert."""
        lo = int(np.searchsorted(self._event_wall, t_from, side="right"))
        hi = int(np.searchsorted(self._event_wall, t_to, side="right"))
        out = self._events[lo:hi]
        if speed > MAJOR_ONLY_ABOVE:
            out = [e for e in out if e.type in MAJOR_EVENTS]
        out = [e for e in out if e.type not in ("PLAN",)]
        if focus is not None:
            focused = [e for e in out if e.entry_id == focus]
            others = [e for e in out if e.entry_id != focus and e.type in MAJOR_EVENTS]
            # Der Ticker des Fokusfahrers ist vollständig, vom Rest nur
            # das Nennenswerte – sonst scrollt bei 250 Startern nichts
            # anderes mehr durch.
            out = focused + others[:20]
        return out[:60]

    def dramatic_focus(self, t_wall: float, window_s: float, current: int) -> int:
        """Wer gerade die Aufmerksamkeit verdient — der automatische Fokus.

        Gesucht wird das **letzte** dramatische Ereignis im Fenster
        hinter der Wanduhr: eine Aufgabe, ein Sturz, ein Defekt, ein
        Hungerast, eine Bestzeit, ein Zieleinlauf. Zurück kommt der
        Fahrer, dem es widerfahren ist.

        Ist nichts passiert, bleibt der Fokus, wo er ist. Das ist
        wichtiger, als es aussieht: Eine Regie, die in jeder ruhigen
        Minute auf den Führenden zurückspringt, macht das Verfolgen
        eines einzelnen Fahrers unmöglich — und ruhige Minuten sind
        beim Ultracycling die Regel.
        """
        lo = int(np.searchsorted(self._event_wall, t_wall - window_s, side="left"))
        hi = int(np.searchsorted(self._event_wall, t_wall, side="right"))
        for i in range(hi - 1, lo - 1, -1):
            if self._events[i].type in DRAMATIC_EVENTS:
                return int(self._events[i].entry_id)
        return current

    def next_event_time(self, t_wall: float, focus: int | None = None) -> float | None:
        """Wanduhrzeit des nächsten Ereignisses (für 'Sprung zum Ereignis')."""
        lo = int(np.searchsorted(self._event_wall, t_wall + 0.5, side="left"))
        for i in range(lo, len(self._events)):
            event = self._events[i]
            if event.type in ("PLAN", "START"):
                continue
            if focus is not None and event.entry_id != focus:
                continue
            return float(self._event_wall[i])
        return None

    def last_split_index(self, t_wall: float, focus: int) -> int:
        """Zuletzt passierter Split des Fokusfahrers.

        Das ist der Split, über den man gerade reden würde – deshalb
        folgt das Board ihm, solange der Nutzer nicht selbst wählt.
        Vor dem ersten Split steht der erste, damit nicht ins Leere
        gezeigt wird.
        """
        offset = self.offsets[focus]
        times = self.result.split_times_s[focus]
        last = 0
        for i, t_s in enumerate(times):
            if np.isfinite(t_s) and offset + t_s <= t_wall:
                last = i
            else:
                break
        return last

    def next_split_time(self, t_wall: float, focus: int) -> float | None:
        """Wanduhrzeit, zu der der Fokusfahrer den nächsten Split erreicht."""
        offset = self.offsets[focus]
        times = self.result.split_times_s[focus]
        for t_s in times:
            if np.isfinite(t_s) and offset + t_s > t_wall + 0.5:
                return float(offset + t_s)
        return None

    # ------------------------------------------------------------------
    def elapsed_at_distance(self, entry_id: int, target_m: float, t_wall: float) -> float | None:
        """Eigenzeit, zu der ein Fahrer eine Distanz erreicht hat.

        Gibt ``None`` zurück, wenn er dort zur Wanduhrzeit noch nicht
        war – die Zukunft bleibt unsichtbar.
        """
        elapsed_now = t_wall - self.offsets[entry_id]
        if elapsed_now < 0:
            return None
        upto = self.sample_idx(np.array([elapsed_now]))[0] + 1
        track = self.telemetry.dist_m[entry_id, :upto]
        if track.size == 0 or track[-1] < target_m:
            return None
        i = int(np.searchsorted(track, target_m, side="left"))
        if i == 0:
            return 0.0
        d0, d1 = float(track[i - 1]), float(track[i])
        frac = (target_m - d0) / (d1 - d0) if d1 > d0 else 0.0
        return (i - 1 + frac) * self.telemetry.sample_dt_s

    def board_rows(
        self,
        t_wall: float,
        split_idx: int,
        focus: int,
        sort: str = "zeit",
        sort_desc: bool = False,
        pinned: Sequence[int] = (),
    ) -> dict[str, Any]:
        """Rangliste eines Splits (Abschnitt 9.1).

        Fahrer, die den Split schon passiert haben, stehen mit ihrer
        Splitzeit und einem Rang. Wer noch unterwegs ist, steht mit
        seiner **laufenden Uhr** — der Zeit, die seit seinem Start
        vergangen ist — und rankt sich damit live zwischen die
        gemessenen Zeiten.

        Das ist die Zeitnahme aus dem Wintersport: Die Uhr des Fahrers
        auf der Strecke läuft weiter, und mit jeder Sekunde, die sie über
        eine bestehende Zeit hinauswandert, rutscht er einen Platz nach
        hinten. Vorher stand hier eine Prognose aus Tempo und
        Reststrecke; die war zwar treffsicherer, aber sie behauptete
        etwas über die Zukunft. Die laufende Uhr behauptet nichts — sie
        zeigt, was jetzt gilt, und die Spannung entsteht aus dem
        Zuschauen statt aus der Hochrechnung.
        """
        split = self.route.splits[split_idx]
        snap = self.snapshot(t_wall)
        times = self.result.split_times_s[:, split_idx]
        reached_wall = self.offsets + times
        trend = self.split_trend(t_wall, split_idx)

        rows: list[dict[str, Any]] = []
        for i, entry in enumerate(self.result.entries):
            base = {
                **self._row_base(i, entry, snap, t_wall),
                "trend": int(trend[i]),
            }
            if np.isfinite(times[i]) and reached_wall[i] <= t_wall:
                rows.append(
                    {**base, "t_s": float(times[i]), "provisional": False, "running": False}
                )
            elif snap["state"][i] == STATE_DNF:
                # Ausgeschieden vor dem Split: Seine Uhr steht. Sie
                # weiterlaufen zu lassen hieße, ihn langsam durch das
                # ganze Board nach unten zu schieben, obwohl er gar nicht
                # mehr fährt.
                rows.append({**base, "t_s": None, "provisional": True, "running": False})
            elif snap["started"][i]:
                rows.append(
                    {
                        **base,
                        "t_s": float(snap["elapsed"][i]),
                        "provisional": True,
                        # Für den Client: Diese Zeit läuft weiter und darf
                        # zwischen zwei Frames mitgezählt werden.
                        "running": True,
                    }
                )
            else:
                rows.append({**base, "t_s": None, "provisional": True, "running": False})

        # Nach Zeit sortieren, ohne die laufenden Uhren ans Ende zu
        # verbannen: Ein Fahrer, dessen Uhr gerade zwischen Rang 2 und 4
        # steht, gehört genau dorthin. Eine Platzziffer bekommt er
        # trotzdem nicht — die ist den gemessenen Zeiten vorbehalten.
        ordered = sorted((r for r in rows if r["t_s"] is not None), key=lambda r: r["t_s"])
        pending = [r for r in rows if r["t_s"] is None]  # noch nicht gestartet
        for row in pending:
            row["rank"] = None
        rank = 0
        for row in ordered:
            if row["provisional"]:
                row["rank"] = None
            else:
                rank += 1
                row["rank"] = rank
        ordered = ordered + pending

        best = next((r["t_s"] for r in ordered if not r["provisional"]), None)
        for row in ordered:
            row["gap_s"] = None if best is None or row["t_s"] is None else row["t_s"] - best

        return {
            "split": {
                "idx": split_idx,
                "name": split.name,
                "dist_m": split.dist_m,
                "kind": split.kind,
            },
            "rows": _window(sort_rows(ordered, sort, sort_desc), focus, BOARD_WINDOW),
            # Die fixierte Kopfzeile zeigt den tatsächlich Führenden, nicht
            # den bestplatzierten Prognosewert.
            "leader": next((r for r in ordered if not r["provisional"]), None),
            "pinned": _pinned_rows(ordered, pinned),
            "n_reached": sum(1 for r in ordered if not r["provisional"]),
            "n_total": len(ordered),
        }

    def _row_base(
        self, i: int, entry: Any, snap: dict[str, np.ndarray], t_wall: float
    ) -> dict[str, Any]:
        """Die Stammdaten einer Board-Zeile — für beide Ranglisten dieselben.

        Die physiologischen Werte stehen hier, obwohl das Board sie
        standardmäßig nicht zeigt: Sie sind die wählbaren Spalten, und
        sie je Umschaltung nachzuladen hieße, für acht Zahlen je Zeile
        eine zweite Abfragestrecke zu bauen.
        """
        rider = self.riders[entry.rider_id]
        team = self.teams.get(rider.team_id)
        giveup = snap["giveup"]
        return {
            "entry_id": i,
            "bib": entry.bib,
            "name": rider.name,
            "nation": rider.nation,
            "team": team.name if team else "",
            "color": team.color if team else "#888888",
            "bike": int(snap["bike"][i]),
            "state": int(snap["state"][i]),
            "dist_km": round(float(snap["dist"][i]) / 1000.0, 2),
            "v_kmh": round(float(snap["v"][i]) * 3.6, 1),
            "power_w": int(snap["power"][i]),
            "form_pct": int(snap["form"][i]),
            "wprime_pct": int(snap["wprime"][i]),
            "glyco_pct": int(snap["glyco"][i]),
            "sleep_pct": int(snap["sleep"][i]),
            "hydration_pct": int(snap["hydration"][i]),
            "giveup_pct": None if giveup is None else int(giveup[i]),
            "conditions": self.condition_labels(i, t_wall),
            **self.to_next_split(float(snap["dist"][i]), int(snap["state"][i])),
        }

    def measured_ranks(self, t_wall: float, split_idx: int) -> np.ndarray:
        """Platzziffern an einem Split, nur aus **gemessenen** Zeiten.

        0 heißt „hat den Split zur Wanduhrzeit noch nicht erreicht".

        Bewusst nicht aus ``result.split_ranks``: Die dort stehenden
        Ränge sind am Rennende vergeben und wüssten damit, wer später
        noch schneller war. Hier zählt nur, was zum Zeitpunkt der
        Betrachtung schon durch die Zeitnahme gelaufen ist.
        """
        ranks = np.zeros(self.n, dtype=np.int32)
        if not 0 <= split_idx < len(self.route.splits):
            return ranks
        times = self.result.split_times_s[:, split_idx]
        reached = np.isfinite(times) & (self.offsets + times <= t_wall)
        order = np.flatnonzero(reached)
        order = order[np.argsort(times[order], kind="stable")]
        ranks[order] = np.arange(1, order.size + 1)
        return ranks

    def split_trend(self, t_wall: float, split_idx: int) -> np.ndarray:
        """Plätze gewonnen (+) oder verloren (−) seit dem Split davor.

        0 steht für „keine Aussage": Wer an einem der beiden Splits noch
        keine gemessene Zeit hat, hat auch keinen Trend. Ein Pfeil, der
        aus einer halben Datenlage entsteht, wäre schlimmer als keiner.
        """
        if split_idx <= 0:
            return np.zeros(self.n, dtype=np.int32)
        now = self.measured_ranks(t_wall, split_idx)
        before = self.measured_ranks(t_wall, split_idx - 1)
        both = (now > 0) & (before > 0)
        return np.where(both, before - now, 0).astype(np.int32)

    def to_next_split(self, dist_m: float, state: int) -> dict[str, Any]:
        """Meter bis zur nächsten Zeitmessung und wie sie heißt.

        Gemeint ist die nächste Marke **vor dem Fahrer**, nicht die des
        gerade angezeigten Boards: Wer bei km 210 fährt, während das
        Board Split 3 bei km 180 zeigt, will wissen, wie weit es noch bis
        Split 4 ist — nicht, wie weit er an Split 3 vorbei ist.

        Nach dem Ziel und nach einer Aufgabe steht dort nichts. Eine 0
        wäre in beiden Fällen eine Behauptung: Der eine ist fertig, der
        andere kommt nirgends mehr an.
        """
        if state in (STATE_FINISHED, STATE_DNF) or not len(self.split_dist):
            return {"to_next_m": None, "next_split": None}
        idx = int(np.searchsorted(self.split_dist, dist_m, side="right"))
        if idx >= len(self.split_dist):
            return {"to_next_m": None, "next_split": None}
        return {
            "to_next_m": int(round(self.split_dist[idx] - dist_m)),
            "next_split": self.route.splits[idx].name,
        }

    def virtual_rows(
        self,
        t_wall: float,
        focus: int,
        sort: str = "zeit",
        sort_desc: bool = False,
        pinned: Sequence[int] = (),
    ) -> dict[str, Any]:
        """Virtuelle Rangliste: alle Fahrer auf dieselbe Distanz projiziert.

        Die echte "wer liegt vorn"-Sicht bei versetzten Startzeiten. Als
        Bezugsdistanz dient die Position des Fokusfahrers – wer sie schon
        passiert hat, wird mit seiner tatsächlichen Zeit dort verglichen;
        wer noch davor liegt, mit einer Prognose.
        """
        snap = self.snapshot(t_wall)
        ref_m = float(snap["dist"][focus])
        # Trend auch hier: gemeint ist der letzte Split, den der
        # Fokusfahrer hinter sich hat — die virtuelle Marke selbst hat
        # keine Zeitnahme und kann deshalb keinen Vergleich liefern.
        last_split = int(np.searchsorted(self.split_dist, ref_m, side="right")) - 1
        trend = self.split_trend(t_wall, last_split)
        rows: list[dict[str, Any]] = []
        for i, entry in enumerate(self.result.entries):
            if not snap["started"][i]:
                continue
            actual = self.elapsed_at_distance(i, ref_m, t_wall)
            if actual is not None:
                provisional = False
            elif snap["state"][i] == STATE_DNF:
                continue  # kommt an dieser Marke nicht mehr vorbei
            else:
                remaining = ref_m - float(snap["dist"][i])
                speed = max(float(snap["v"][i]), 2.0)
                actual = float(snap["elapsed"][i]) + remaining / speed
                provisional = True
            rows.append(
                {
                    **self._row_base(i, entry, snap, t_wall),
                    "trend": int(trend[i]),
                    "t_s": actual,
                    "provisional": provisional,
                    # Die virtuelle Rangliste projiziert auf eine
                    # gemeinsame Distanz; dort ist Mitzählen sinnlos.
                    "running": False,
                }
            )
        rows.sort(key=lambda r: r["t_s"])
        for n, row in enumerate(rows, start=1):
            row["rank"] = n
        best = rows[0]["t_s"] if rows else None
        for row in rows:
            row["gap_s"] = None if best is None else row["t_s"] - best
        return {
            "split": {
                "idx": -1,
                "name": f"Virtuell bei km {ref_m / 1000:.1f}",
                "dist_m": ref_m,
                "kind": "virtual",
            },
            "rows": _window(sort_rows(rows, sort, sort_desc), focus, BOARD_WINDOW),
            "leader": rows[0] if rows else None,
            "pinned": _pinned_rows(rows, pinned),
            "n_reached": len(rows),
            "n_total": len(rows),
        }


def _pinned_rows(rows: list[dict[str, Any]], pinned: Sequence[int]) -> list[dict[str, Any]]:
    """Die angehefteten Zeilen, in der Reihenfolge des Anheftens.

    Sie kommen aus derselben Liste wie das Board — angeheftet zu sein
    ändert an einer Zeile nichts außer der Frage, wo sie steht.
    """
    by_id = {r["entry_id"]: r for r in rows}
    return [by_id[i] for i in pinned if i in by_id]


def sort_rows(rows: list[dict[str, Any]], key: str, desc: bool) -> list[dict[str, Any]]:
    """Das Board nach einer anderen Größe ordnen.

    Zeilen ohne Wert stehen **immer** am Ende, in beiden Richtungen: Ein
    Fahrer ohne Glykogenwert gehört nicht an die Spitze der Liste „wem
    geht es am schlechtesten", nur weil ``None`` kleiner sortiert.

    Die Platzziffern werden dabei nicht neu vergeben. Rang 1 ist der
    Schnellste, auch wenn die Liste gerade nach Tempo sortiert ist —
    sonst wäre die Spalte „Rg" nur noch eine Zeilennummer.
    """
    field_name = SORT_FIELDS.get(key)
    if field_name is None:
        return rows
    with_value = [r for r in rows if r.get(field_name) is not None]
    without = [r for r in rows if r.get(field_name) is None]
    with_value.sort(key=lambda r: r[field_name], reverse=desc)
    return with_value + without


def _window(rows: list[dict[str, Any]], focus: int, size: int) -> list[dict[str, Any]]:
    """Fenster von ``size`` Zeilen, das dem Fokusfahrer folgt.

    Bei 250 Fahrern ist die Begrenzung kein Abschneiden mehr, sondern ein
    Ausschnitt: Ist der Fokus auf Rang 1, steht er oben; sonst liegt er
    mittig. An den Rändern klebt das Fenster an Anfang bzw. Ende.
    """
    if len(rows) <= size:
        return rows
    pos = next((i for i, r in enumerate(rows) if r["entry_id"] == focus), 0)
    half = size // 2
    lo = max(0, min(pos - half, len(rows) - size))
    return rows[lo : lo + size]
