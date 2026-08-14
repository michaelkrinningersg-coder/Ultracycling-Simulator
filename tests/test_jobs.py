"""Hintergrundaufträge (M7).

Rennen rechnen dauert Minuten, deshalb läuft es in einem Arbeiterthread
und die Oberfläche fragt den Fortschritt ab. Damit ist die Reihenfolge,
in der ein Auftrag seine Felder setzt, Teil der Schnittstelle: Ein
Abruf kann zwischen zwei Zuweisungen fallen.
"""

from __future__ import annotations

import time

from ultrasim.web.jobs import Job, JobRunner


def _wait(runner: JobRunner, job: Job, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = job.to_dict()
        if data["done"]:
            return data
        time.sleep(0.01)
    raise AssertionError("Auftrag wurde nicht fertig")


def test_a_finished_job_carries_its_result():
    runner = JobRunner()
    job = runner.submit(kind="test", label="Rechnung", work=lambda j: {"wert": 42})
    data = _wait(runner, job)
    assert data["state"] == "fertig"
    assert data["result"] == {"wert": 42}
    assert data["error"] == ""
    assert data["progress"] == 1.0


def test_a_failed_job_is_never_done_without_a_reason():
    """Die Zusicherung, an der das CI hing.

    ``done`` wird aus dem Zustand abgeleitet. Stünde der Zustand vor der
    Begründung, könnte ein Abruf genau dazwischen fallen und einen
    gescheiterten Auftrag ohne Fehlertext anzeigen — auf einem langsamen
    Rechner regelmäßig, auf einem schnellen nie.
    """

    def boom(job: Job) -> dict:
        raise FileNotFoundError("Strecke 'gibtsnicht' nicht gefunden")

    runner = JobRunner()
    job = runner.submit(kind="test", label="Kaputt", work=boom)

    # Eng abfragen, wie es die Oberfläche tut, und **jede** Momentaufnahme
    # auf Widerspruchsfreiheit prüfen. Der Fehler war nicht, dass am Ende
    # etwas Falsches dastand, sondern dass zwischendurch etwas
    # Unmögliches dastehen konnte.
    deadline = time.time() + 10.0
    while time.time() < deadline:
        data = job.to_dict()
        assert not (data["done"] and data["state"] not in ("fertig", "fehler")), (
            f"fertig gemeldet, aber Zustand ist {data['state']!r} — "
            "``state`` wird in to_dict() zweimal gelesen"
        )
        assert not (data["state"] == "fehler" and not data["error"]), (
            "gescheitert gemeldet, aber ohne Begründung — im Arbeiterthread "
            "steht der Zustand vor dem Fehlertext"
        )
        if data["done"]:
            assert data["state"] == "fehler"
            assert "gibtsnicht" in data["error"]
            return
    raise AssertionError("Auftrag wurde nicht fertig")


def test_jobs_run_one_after_another():
    """Die Restermüdung verlangt Reihenfolge — zwei Rennen gleichzeitig
    zu rechnen würde sie unterschlagen."""
    order: list[str] = []

    def slow(job: Job) -> dict:
        order.append(f"start-{job.label}")
        time.sleep(0.05)
        order.append(f"ende-{job.label}")
        return {}

    runner = JobRunner()
    first = runner.submit(kind="test", label="A", work=slow)
    second = runner.submit(kind="test", label="B", work=slow)
    _wait(runner, first)
    _wait(runner, second)
    assert order == ["start-A", "ende-A", "start-B", "ende-B"]


def test_jobs_are_listed_per_season():
    runner = JobRunner()
    a = runner.submit(kind="test", label="A", work=lambda j: {}, season_id="s1")
    runner.submit(kind="test", label="B", work=lambda j: {}, season_id="s2")
    _wait(runner, a)
    assert [j.label for j in runner.list_jobs("s1")] == ["A"]
    assert [j.label for j in runner.list_jobs("s2")] == ["B"]
