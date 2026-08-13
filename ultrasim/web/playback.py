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
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..core.engine import RaceResult, Telemetry
from ..core.events import MAJOR_EVENTS, RaceEvent
from ..geo.route import Route

#: Angebotene Zeitrafferstufen.
SPEEDS = (1, 10, 60, 300, 1000)

#: Ab dieser Stufe werden nur noch die wichtigen Ereignisse gestreamt –
#: sonst erstickt der Client am Ereignisstrom (Abschnitt 8.2).
MAJOR_ONLY_ABOVE = 60

#: Fenstergröße des Telemetrie-Boards (Abschnitt 9.1).
BOARD_WINDOW = 41


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
    anchor: float = field(default_factory=time.monotonic)
    horizon_s: float = 0.0  # Ende des Rennens; darüber hinaus läuft nichts

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
            result.events, key=lambda e: e.t_s + result.entries[e.entry_id].start_offset_s
        )
        self._event_wall = np.array(
            [e.t_s + result.entries[e.entry_id].start_offset_s for e in self._events]
        )

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
        dist[~started] = 0.0
        v[~started] = 0.0
        power[~started] = 0.0
        return {
            "started": started,
            "elapsed": elapsed,
            "dist": dist,
            "v": v,
            "power": power,
            "state": state,
            "bike": bike,
            "form": form,
            "wprime": wprime,
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

    def board_rows(self, t_wall: float, split_idx: int, focus: int) -> dict[str, Any]:
        """Rangliste eines Splits (Abschnitt 9.1).

        Fahrer, die den Split schon passiert haben, stehen mit ihrer
        Splitzeit und einem Rang. Wer noch unterwegs ist, erscheint
        ausgegraut mit einer Prognosezeit aus aktuellem Tempo und
        Reststrecke – genau die Spannung, die "kommt er noch vorbei?"
        erzeugt.
        """
        split = self.route.splits[split_idx]
        snap = self.snapshot(t_wall)
        times = self.result.split_times_s[:, split_idx]
        reached_wall = self.offsets + times

        rows: list[dict[str, Any]] = []
        for i, entry in enumerate(self.result.entries):
            rider = self.riders[entry.rider_id]
            team = self.teams.get(rider.team_id)
            base = {
                "entry_id": i,
                "bib": entry.bib,
                "name": rider.name,
                "nation": rider.nation,
                "team": team.name if team else "",
                "color": team.color if team else "#888888",
                "bike": int(snap["bike"][i]),
                "state": int(snap["state"][i]),
                "dist_km": round(float(snap["dist"][i]) / 1000.0, 2),
            }
            if np.isfinite(times[i]) and reached_wall[i] <= t_wall:
                rows.append({**base, "t_s": float(times[i]), "provisional": False})
            elif snap["started"][i]:
                remaining = split.dist_m - float(snap["dist"][i])
                speed = max(float(snap["v"][i]), 2.0)
                projected = float(snap["elapsed"][i]) + remaining / speed
                rows.append({**base, "t_s": projected, "provisional": True})
            else:
                rows.append({**base, "t_s": None, "provisional": True})

        # Nach Zeit sortieren, ohne die Prognosen ans Ende zu verbannen:
        # Ein Fahrer, der laut Prognose auf Rang 3 einschlägt, gehört
        # zwischen Rang 2 und 4 – genau daraus entsteht die Frage "kommt
        # er noch vorbei?". Eine Platzziffer bekommt er trotzdem nicht,
        # die ist den gemessenen Zeiten vorbehalten.
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
            "rows": _window(ordered, focus, BOARD_WINDOW),
            # Die fixierte Kopfzeile zeigt den tatsächlich Führenden, nicht
            # den bestplatzierten Prognosewert.
            "leader": next((r for r in ordered if not r["provisional"]), None),
            "n_reached": sum(1 for r in ordered if not r["provisional"]),
            "n_total": len(ordered),
        }

    def virtual_rows(self, t_wall: float, focus: int) -> dict[str, Any]:
        """Virtuelle Rangliste: alle Fahrer auf dieselbe Distanz projiziert.

        Die echte "wer liegt vorn"-Sicht bei versetzten Startzeiten. Als
        Bezugsdistanz dient die Position des Fokusfahrers – wer sie schon
        passiert hat, wird mit seiner tatsächlichen Zeit dort verglichen;
        wer noch davor liegt, mit einer Prognose.
        """
        snap = self.snapshot(t_wall)
        ref_m = float(snap["dist"][focus])
        rows: list[dict[str, Any]] = []
        for i, entry in enumerate(self.result.entries):
            if not snap["started"][i]:
                continue
            rider = self.riders[entry.rider_id]
            team = self.teams.get(rider.team_id)
            actual = self.elapsed_at_distance(i, ref_m, t_wall)
            if actual is None:
                remaining = ref_m - float(snap["dist"][i])
                speed = max(float(snap["v"][i]), 2.0)
                actual = float(snap["elapsed"][i]) + remaining / speed
                provisional = True
            else:
                provisional = False
            rows.append(
                {
                    "entry_id": i,
                    "bib": entry.bib,
                    "name": rider.name,
                    "nation": rider.nation,
                    "team": team.name if team else "",
                    "color": team.color if team else "#888888",
                    "bike": int(snap["bike"][i]),
                    "state": int(snap["state"][i]),
                    "dist_km": round(float(snap["dist"][i]) / 1000.0, 2),
                    "t_s": actual,
                    "provisional": provisional,
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
            "rows": _window(rows, focus, BOARD_WINDOW),
            "leader": rows[0] if rows else None,
            "n_reached": len(rows),
            "n_total": len(rows),
        }


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
