"""Rennbericht in einem Satz je Fahrer.

Die Tests bauen Ereignisse und Splitränge von Hand — der Bericht ist
eine reine Funktion, und für „wurde Zweiter" muss niemand ein Rennen
rechnen. Geprüft wird vor allem, dass er **nichts erfindet**: Jeder
Baustein muss auf eine Zahl zurückgehen, die vorher da war.
"""

from __future__ import annotations

import pytest

from ultrasim.core.engine import RaceEntry
from ultrasim.core.events import BONK, DECISION, INCIDENT, SLEEP, RaceEvent
from ultrasim.core.incidents import CATALOG
from ultrasim.core.narrative import build_report, build_reports
from ultrasim.geo.route import Split


def _entry(entry_id=0, rank=None, finish=None, dnf_reason="", dnf_dist_m=None):
    return RaceEntry(
        entry_id=entry_id,
        rider_id=entry_id,
        bib=entry_id + 1,
        start_offset_s=0.0,
        season_form=1.0,
        day_form=1.0,
        target_if=0.7,
        finish_time_s=finish,
        rank=rank,
        status="FIN" if finish else "DNF",
        dnf_reason=dnf_reason,
        dnf_dist_m=dnf_dist_m,
    )


SPLITS = [Split(idx=i, dist_m=i * 10_000.0, name=f"km {i * 10}", kind="interval") for i in range(8)]


# ----------------------------------------------------------------------
# Ausgang
# ----------------------------------------------------------------------
def test_the_winner_gets_his_margin():
    report = build_report(_entry(rank=1, finish=3600.0), [], [], SPLITS, winner_margin_s=420.0)
    assert report.text == "Gewann mit 7 min Vorsprung."


def test_a_placing_reads_as_a_word_up_front_and_a_number_behind():
    assert build_report(_entry(rank=2, finish=1.0), [], [], SPLITS).text == "Wurde Zweiter."
    assert build_report(_entry(rank=12, finish=1.0), [], [], SPLITS).text == "Kam als 12. ins Ziel."


def test_a_retirement_says_where_and_why():
    entry = _entry(rank=None, dnf_reason="Aufgabe: Schwerer Sturz", dnf_dist_m=93_400.0)
    assert build_report(entry, [], [], SPLITS).text == "Gab bei km 93 auf (Schwerer Sturz)."


def test_a_report_always_ends_with_exactly_one_full_stop():
    for rank in (1, 2, 4, 7, 12, 99):
        text = build_report(_entry(rank=rank, finish=1.0), [], [], SPLITS).text
        assert text.endswith(".")
        assert not text.endswith("..")


# ----------------------------------------------------------------------
# Zwischenfälle
# ----------------------------------------------------------------------
def _incident(typ: str, stop_s: float, km: float, t_s: float = 100.0) -> RaceEvent:
    return RaceEvent(
        0, t_s, INCIDENT,
        {"typ": typ, "label": CATALOG[typ].label, "stop_s": stop_s, "dist_km": km},
    )


def test_the_costliest_incident_is_the_one_that_gets_told():
    events = [
        _incident("panne", 300.0, 40.0, t_s=100.0),
        _incident("defekt", 1500.0, 93.0, t_s=200.0),
        _incident("verfahren", 400.0, 150.0, t_s=300.0),
    ]
    report = build_report(_entry(rank=4, finish=1.0), events, [], SPLITS)
    assert "25 min durch einen mechanischen Defekt bei km 93" in report.text
    assert "Reifenpanne" not in report.text


def test_a_short_stop_is_not_worth_a_sentence():
    """Drei Minuten gehen im Rauschen der Servicestopps unter."""
    report = build_report(_entry(rank=4, finish=1.0), [_incident("panne", 120.0, 40.0)], [], SPLITS)
    assert report.text == "Wurde Vierter."


@pytest.mark.parametrize("typ", sorted(CATALOG))
def test_every_incident_has_a_grammatical_form(typ):
    """Jeder Katalogeintrag muss sich in „durch …" einsetzen lassen.

    Ohne Akkusativform stünde dort „durch Mechanischer Defekt". Der Test
    schlägt an, sobald jemand einen Eintrag hinzufügt und die Form
    vergisst — sichtbar wird das sonst erst im fertigen Satz.
    """
    cause = CATALOG[typ].as_cause()
    assert cause and cause == cause.strip()
    with_article = cause.split()[0] in {"ein", "eine", "einen"}
    # Entweder mit unbestimmtem Artikel im Akkusativ („durch **einen**
    # mechanischen Defekt") oder artikellos und dann großgeschrieben
    # („durch **Magenprobleme**"). Alles andere ergibt keinen Satz.
    assert with_article or cause[0].isupper(), f"{typ}: 'durch {cause}' ist kein Deutsch"


# ----------------------------------------------------------------------
# Verlauf
# ----------------------------------------------------------------------
def test_a_collapse_names_where_it_started():
    ranks = [3, 3, 3, 4, 9, 14, 18, 20]
    report = build_report(_entry(rank=20, finish=1.0), [], ranks, SPLITS)
    assert "lag bei km 0 auf Rang 3 und verlor danach 17 Plätze" in report.clauses


def test_a_charge_through_the_field_is_told_as_one():
    ranks = [40, 35, 28, 20, 14, 9, 6, 5]
    report = build_report(_entry(rank=5, finish=1.0), [], ranks, SPLITS)
    assert "arbeitete sich von Rang 40 auf 5 vor" in report.clauses


def test_a_steady_ride_says_so():
    ranks = [7, 7, 7, 8, 7, 7, 7, 7]
    assert "hielt Rang 7 über die ganze Distanz" in build_report(
        _entry(rank=7, finish=1.0), [], ranks, SPLITS
    ).clauses


def test_unreached_splits_do_not_count_as_rank_zero():
    """0 heißt „nicht erreicht" und wäre als Platzierung eine Falschaussage."""
    ranks = [12, 11, 10, 0, 0, 0, 0, 0]
    report = build_report(_entry(rank=None, dnf_dist_m=25_000.0), [], ranks, SPLITS)
    assert "Rang 0" not in report.text
    assert "auf" in report.text  # der Ausgang steht trotzdem da


# ----------------------------------------------------------------------
# Weitere Bausteine
# ----------------------------------------------------------------------
def test_sleep_stops_are_summed():
    events = [
        RaceEvent(0, 100.0, SLEEP, {"duration_s": 5400.0, "dist_km": 400.0}),
        RaceEvent(0, 200.0, SLEEP, {"duration_s": 3600.0, "dist_km": 800.0}),
    ]
    assert "schlief 2-mal, zusammen 2:30 h" in build_report(
        _entry(rank=9, finish=1.0), events, [], SPLITS
    ).clauses


def test_a_bonk_is_mentioned():
    events = [RaceEvent(0, 100.0, BONK, {"dist_km": 210.0, "glyco_pct": 12.0})]
    assert "kam bei km 210 in den Hungerast" in build_report(
        _entry(rank=9, finish=1.0), events, [], SPLITS
    ).clauses


def test_a_chase_is_only_told_when_nothing_bigger_happened():
    chase = RaceEvent(0, 50.0, DECISION, {"rule": "aufholen", "dist_km": 30.0, "on": True})
    quiet = build_report(_entry(rank=6, finish=1.0), [chase], [], SPLITS)
    assert "Aufholjagd" in quiet.text

    loud = build_report(
        _entry(rank=6, finish=1.0), [chase, _incident("sturz", 1800.0, 60.0)], [], SPLITS
    )
    assert "Aufholjagd" not in loud.text, "Der Sturz ist die Geschichte, nicht die Reaktion darauf"


def test_a_report_never_runs_longer_than_three_clauses():
    events = [
        _incident("defekt", 1500.0, 93.0),
        RaceEvent(0, 150.0, BONK, {"dist_km": 210.0}),
        RaceEvent(0, 200.0, SLEEP, {"duration_s": 5400.0, "dist_km": 400.0}),
    ]
    report = build_report(_entry(rank=8, finish=1.0), events, [3, 3, 9, 14, 18, 20, 21, 22], SPLITS)
    assert len(report.clauses) <= 3
    assert report.text.count(",") <= 2


# ----------------------------------------------------------------------
# Ganzes Feld
# ----------------------------------------------------------------------
def test_the_field_report_derives_the_winner_margin_itself():
    entries = [
        _entry(0, rank=1, finish=3600.0),
        _entry(1, rank=2, finish=3900.0),
        _entry(2, rank=3, finish=4200.0),
    ]
    reports = build_reports(entries, [], [[], [], []], SPLITS)
    assert reports[0].text == "Gewann mit 5 min Vorsprung."
    assert reports[1].text == "Wurde Zweiter."


def test_every_starter_gets_a_report():
    entries = [_entry(i, rank=i + 1, finish=3600.0 + i) for i in range(5)]
    reports = build_reports(entries, [], [[] for _ in entries], SPLITS)
    assert set(reports) == {e.entry_id for e in entries}
    assert all(r.text for r in reports.values())
