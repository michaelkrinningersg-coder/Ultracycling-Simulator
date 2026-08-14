"""Hintergrundrechnungen für den Kalender (M7).

Bisher war die Web-App ein reiner Betrachter: Gerechnet wurde auf der
Kommandozeile, angezeigt im Browser. Mit dem Kalender geht das nicht mehr
auf — wer eine Saison im Browser zusammenstellt, will sie dort auch
starten, und ein Ultra-Rennen dauert Minuten. Ein synchroner Request
würde in jedem Proxy und Browser ins Timeout laufen.

Deshalb ein Arbeiter im Hintergrund mit einer Warteschlange.

**Genau ein Arbeiter, nicht mehr.** Das ist keine Sparsamkeit, sondern
eine Anforderung: Die Restermüdung für ein Rennen steht erst fest, wenn
das vorherige gerechnet ist. Zwei Rennen derselben Saison gleichzeitig zu
rechnen würde das zweite mit einem veralteten Stand füttern und
gleichzeitig zwei Schreiber auf dieselbe Saisondatei setzen.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: So viele erledigte Aufträge bleiben sichtbar, bevor sie verfallen.
KEEP_FINISHED = 40

STATE_QUEUED = "wartet"
STATE_RUNNING = "läuft"
STATE_DONE = "fertig"
STATE_FAILED = "fehler"


@dataclass
class Job:
    """Ein Auftrag und sein Fortschritt."""

    id: str
    kind: str
    label: str
    season_id: str = ""
    race_key: str = ""
    state: str = STATE_QUEUED
    progress: float = 0.0
    detail: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Momentaufnahme für die Oberfläche.

        ``state`` wird **einmal** gelesen und dann für beide Felder
        benutzt. Wer ihn zweimal liest, baut sich eine Wette auf den
        Threadwechsel: Zwischen dem Feld ``state`` und dem daraus
        abgeleiteten ``done`` kann der Arbeiterthread den Auftrag
        beenden, und heraus kommt ``{"state": "wartet", "done": true}``.
        Genau das hat im CI einen Test umgeworfen — auf dem langsamsten
        Läufer, versteht sich.

        Zusammen mit der Reihenfolge im Arbeiterthread (erst Ergebnis
        bzw. Begründung, dann Zustand) ist die Momentaufnahme damit in
        sich stimmig: Steht ``done``, stehen auch die Felder dazu.
        """
        state = self.state
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "season_id": self.season_id,
            "race_key": self.race_key,
            "state": state,
            "progress": round(self.progress, 3),
            "detail": self.detail,
            "result": self.result,
            "error": self.error,
            "done": state in (STATE_DONE, STATE_FAILED),
        }


class JobRunner:
    """Warteschlange mit einem einzigen Arbeiterthread."""

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._work: dict[str, Callable[[Job], dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    def submit(
        self,
        kind: str,
        label: str,
        work: Callable[[Job], dict[str, Any]],
        season_id: str = "",
        race_key: str = "",
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            label=label,
            season_id=season_id,
            race_key=race_key,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._work[job.id] = work
            self._prune()
        self._queue.put(job.id)
        self._ensure_worker()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active_for(self, season_id: str, race_key: str = "") -> Job | None:
        """Laufender oder wartender Auftrag zu einem Termin.

        Damit blendet die Oberfläche den „Rechnen"-Knopf aus, statt
        denselben Termin zweimal in die Schlange zu hängen.
        """
        with self._lock:
            for job in self._jobs.values():
                if job.state in (STATE_QUEUED, STATE_RUNNING) and job.season_id == season_id:
                    if not race_key or job.race_key == race_key:
                        return job
        return None

    def list_jobs(self, season_id: str = "") -> list[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if not season_id or j.season_id == season_id]
        return sorted(jobs, key=lambda j: j.created, reverse=True)

    def busy(self) -> bool:
        with self._lock:
            return any(j.state in (STATE_QUEUED, STATE_RUNNING) for j in self._jobs.values())

    # ------------------------------------------------------------------
    def _prune(self) -> None:
        finished = sorted(
            (j for j in self._jobs.values() if j.state in (STATE_DONE, STATE_FAILED)),
            key=lambda j: j.finished or j.created,
        )
        while len(finished) > KEEP_FINISHED:
            gone = finished.pop(0)
            self._jobs.pop(gone.id, None)
            self._work.pop(gone.id, None)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, daemon=True, name="ultrasim-jobs")
            self._thread.start()

    def _loop(self) -> None:
        while True:
            try:
                job_id = self._queue.get(timeout=30.0)
            except queue.Empty:
                return  # nichts mehr zu tun, Thread darf enden
            with self._lock:
                job = self._jobs.get(job_id)
                work = self._work.get(job_id)
            if job is None or work is None:
                continue
            job.state = STATE_RUNNING
            try:
                job.result = work(job) or {}
                job.state = STATE_DONE
                job.progress = 1.0
            except Exception as exc:  # noqa: BLE001 - der Thread darf nie sterben
                # **Erst die Begründung, dann der Zustand.** ``done`` wird
                # aus dem Zustand abgeleitet, und die Oberfläche fragt im
                # Sekundentakt ab: Steht der Zustand zuerst, kann ein
                # Abruf genau dazwischen fallen und einen gescheiterten
                # Auftrag ohne Fehlertext sehen. Genau das ist im CI
                # passiert — auf dem langsamsten Läufer, weil der
                # Traceback-Ausdruck dazwischen lag und Zeit kostet.
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = STATE_FAILED
                # Der volle Traceback in die Konsole, die Kurzfassung in
                # die Oberfläche: Ein Rennen kann an fehlenden Strecken
                # scheitern, und dann will man den Grund lesen können.
                traceback.print_exc()
            finally:
                job.finished = time.time()
                self._queue.task_done()


def race_progress(job: Job) -> Callable[[int, int, int, int], None]:
    """Fortschritts-Callback für ``simulate_race``."""

    def report(tick: int, max_ticks: int, finished: int, total: int) -> None:
        job.progress = min(tick / max(max_ticks, 1), 0.99)
        job.detail = f"{finished} von {total} im Ziel"

    return report


__all__ = [
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_QUEUED",
    "STATE_RUNNING",
    "Job",
    "JobRunner",
    "race_progress",
]
