"""Kalibrierungsmessungen (Meilenstein M8).

Die Tests halten vor allem die eine Eigenschaft fest, auf der die ganze
Sensitivitätsmessung ruht: **Zwei Kopien desselben Fahrers im selben
Rennen fahren dieselbe Zeit.** Nur weil das gilt, darf man alle
Attributvarianten in ein einziges Rennen packen und die Differenz dem
Attribut zuschreiben. Ginge irgendwann ein Zufallsstrom an die Position
in der Startliste statt an die Fahrer-ID, wäre die Messung still kaputt
und die Zahlen im Bericht wären Rauschen.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from ultrasim import calibration as cal
from ultrasim import calibration_report as report
from ultrasim.cli import balance
from ultrasim.core import weather as wx
from ultrasim.core.engine import simulate_race
from ultrasim.core.form import day_form_sd
from ultrasim.core.rider import ACTIVE_ATTRIBUTES, ARCHETYPES, ATTRIBUTES, generate_pool

#: Wenige Attribute mit unterschiedlicher Wirkungsart: eines aus der
#: Physik, eines aus dem Energiehaushalt, eines ohne Anschluss.
SAMPLE_ATTRS = ["flach", "fettverbrennung", "oberflaechenkompetenz"]


@pytest.fixture(scope="module")
def small_pool():
    return generate_pool(8, n_teams=2, seed=404)


@pytest.fixture(scope="module")
def effects(route, small_pool):
    teams, riders = small_pool
    return cal.attribute_sensitivity(route, riders, teams, (17,), attributes=SAMPLE_ATTRS)


# ----------------------------------------------------------------------
# Die tragende Zusicherung
# ----------------------------------------------------------------------
def test_two_copies_of_the_same_rider_finish_at_the_same_time(route, small_pool):
    teams, riders = small_pool
    field = [replace(r, attributes=dict(r.attributes)) for r in riders] * 3
    result = simulate_race(route, field, teams, cal.sensitivity_config(7))

    by_rider: dict[int, set[float | None]] = {}
    for entry in result.entries:
        by_rider.setdefault(entry.rider_id, set()).add(entry.finish_time_s)
    assert all(len(times) == 1 for times in by_rider.values()), (
        "Kopien desselben Fahrers unterscheiden sich – die Zufallsströme "
        "hängen nicht mehr allein an der Fahrer-ID."
    )


def test_the_start_slot_does_not_change_the_race(route, small_pool):
    """Die Zeitschicht hängt an der Eigenzeit, nicht an der Uhr (Entscheidung 13)."""
    teams, riders = small_pool
    first = simulate_race(route, riders, teams, cal.sensitivity_config(7))
    later = simulate_race(route, list(reversed(riders)), teams, cal.sensitivity_config(7))
    a = {e.rider_id: e.finish_time_s for e in first.entries}
    b = {e.rider_id: e.finish_time_s for e in later.entries}
    assert a == b


# ----------------------------------------------------------------------
# Variantenfeld
# ----------------------------------------------------------------------
def test_the_variant_field_has_one_pair_per_attribute_and_rider(small_pool):
    _, riders = small_pool
    field, attrs = cal.sensitivity_field(riders, SAMPLE_ATTRS)
    assert attrs == SAMPLE_ATTRS
    assert len(field) == len(riders) * (1 + 2 * len(SAMPLE_ATTRS))
    assert [r.id for r in field[: len(riders)]] == [r.id for r in riders]


def test_variants_keep_the_rider_id_and_change_exactly_one_attribute(small_pool):
    _, riders = small_pool
    n = len(riders)
    field, _ = cal.sensitivity_field(riders, ["flach"])
    for k, base in enumerate(riders):
        strong, weak = field[n + k], field[2 * n + k]
        assert strong.id == weak.id == base.id
        assert strong.attr("flach") > weak.attr("flach")
        for other in ATTRIBUTES:
            if other != "flach":
                assert strong.attr(other) == weak.attr(other) == base.attr(other)


def test_the_step_is_clipped_to_the_scale(small_pool):
    _, riders = small_pool
    extreme = [replace(r, attributes={**r.attributes, "flach": 97.0}) for r in riders]
    field, _ = cal.sensitivity_field(extreme, ["flach"])
    assert all(r.attr("flach") <= 99.0 for r in field)
    # …und die Messung rechnet auf den wirklich gefahrenen Abstand um,
    # nicht auf den gewünschten – sonst wäre die Wirkung zu klein.
    assert field[len(riders)].attr("flach") == 99.0


# ----------------------------------------------------------------------
# Messung
# ----------------------------------------------------------------------
def test_sensitivity_returns_every_attribute_sorted_by_effect(effects):
    assert [e.attr for e in effects] != []
    assert {e.attr for e in effects} == set(SAMPLE_ATTRS)
    seconds = [abs(e.seconds) for e in effects]
    assert seconds == sorted(seconds, reverse=True)


def test_flat_power_makes_riders_faster(effects):
    flat = next(e for e in effects if e.attr == "flach")
    assert flat.measurable
    assert flat.seconds > 0.0, "Mehr Flachleistung muss Zeit bringen"
    assert flat.pairs == 8


def test_an_attribute_without_a_consumer_does_nothing(effects):
    """`oberflaechenkompetenz` wird von keiner Mechanik gelesen – exakt null.

    Der Platzhalter dieses Tests war ursprünglich ``sitzkomfort``. Der
    hat seit den Sitzbeschwerden einen Abnehmer, und damit wanderte die
    Rolle weiter an das letzte verbliebene tote Attribut: Ohne
    Schotterabschnitte im Streckeneditor liest niemand die Oberfläche.
    Wird auch das eingebaut, hat dieser Test keinen Kandidaten mehr —
    und genau dann darf er ersatzlos verschwinden.
    """
    assert "oberflaechenkompetenz" not in ACTIVE_ATTRIBUTES
    surface = next(e for e in effects if e.attr == "oberflaechenkompetenz")
    assert surface.seconds == 0.0
    assert not surface.measurable


def test_noise_is_not_reported_as_an_effect():
    """Eine große Wirkung mit ebenso großem Standardfehler zählt nicht."""
    loud = cal.AttributeEffect("x", 400.0, 0.0, 1.0, stderr=300.0, pairs=20, dnf_delta=0)
    quiet = cal.AttributeEffect("x", 400.0, 380.0, 1.0, stderr=20.0, pairs=20, dnf_delta=0)
    assert not loud.measurable
    assert quiet.measurable


def test_a_variance_attribute_is_never_reported():
    """`konstanz` ist mit diesem Aufbau grundsätzlich nicht messbar.

    Es steuert allein die Streuung der Tagesform, und beide Kopien eines
    Fahrers ziehen aus demselben Strom dasselbe z: Die Paardifferenz ist
    proportional zu −z und damit der Stichprobenmittelwert der
    Zufallszahlen, nicht die Wirkung des Attributs. Eine große Zahl in
    dieser Zeile wäre eine Falschaussage — also steht dort keine.
    """
    assert "konstanz" in cal.VARIANCE_ATTRIBUTES
    loud = cal.AttributeEffect("konstanz", -400.0, -390.0, -1.0, stderr=5.0, pairs=40, dnf_delta=0)
    assert not loud.measurable


def test_the_day_form_is_the_same_draw_scaled_by_konstanz():
    """Die Begründung für den Ausschluss – hier steht sie als Test."""
    z = float(np.random.default_rng(7).normal())
    drawn = [
        float(np.random.default_rng(7).normal(1.0, day_form_sd(k))) for k in (35.0, 75.0)
    ]
    assert drawn == pytest.approx([1.0 + day_form_sd(k) * z for k in (35.0, 75.0)])
    # Mehr Konstanz heißt weniger Streuung – nicht mehr Leistung.
    assert day_form_sd(75.0) < day_form_sd(35.0)


def test_rare_event_attributes_are_marked():
    """Mittel weit über Median heißt: wirkt über seltene Ereignisse."""
    rare = cal.AttributeEffect("x", 120.0, 0.0, 0.3, stderr=10.0, pairs=40, dnf_delta=-2)
    steady = cal.AttributeEffect("x", 120.0, 118.0, 0.3, stderr=10.0, pairs=40, dnf_delta=0)
    assert rare.rare_event_driven
    assert not steady.rare_event_driven


# ----------------------------------------------------------------------
# Archetypen
# ----------------------------------------------------------------------
def test_the_balanced_field_gives_every_archetype_the_same_budget():
    teams, riders = cal.balanced_field(2, seed=5)
    assert len(riders) == 2 * len(ARCHETYPES)
    assert {r.archetype for r in riders} == set(ARCHETYPES)
    assert len({r.id for r in riders}) == len(riders)
    assert len({t.id for t in teams}) == len(teams)
    budgets = [r.potential for r in riders]
    # Das Budget wird auf eine Nachkommastelle gerundet verteilt, deshalb
    # nicht exakt gleich – aber weit enger als die Streuung im Feld (4).
    assert max(budgets) - min(budgets) < 0.5


def test_archetype_stats_add_up(route):
    teams, riders = cal.balanced_field(1, seed=5)
    seeds = (11, 12)
    stats = cal.archetype_stats(route, riders, teams, seeds)
    assert sum(s.starts for s in stats) == len(riders) * len(seeds)
    assert sum(s.wins for s in stats) <= len(seeds)
    assert all(1.0 <= s.mean_rank <= len(riders) for s in stats if s.mean_rank == s.mean_rank)


# ----------------------------------------------------------------------
# Streckenübersicht
# ----------------------------------------------------------------------
def test_route_summary_is_ordered_and_plausible(route, small_pool):
    teams, riders = small_pool
    summary = cal.route_summary(route, riders, teams, (21, 22))
    assert summary.runs == 2
    assert summary.starters == 2 * len(riders)
    assert summary.winner_h <= summary.median_h <= summary.last_h
    assert 0.0 <= summary.dnf_pct + summary.otl_pct <= 100.0
    assert summary.winner_kmh > summary.field_kmh
    assert summary.band == cal.DURATION_TARGET_H[route.distance_class]
    assert summary.dnf_target == cal.DNF_TARGET[route.distance_class]


def test_the_corridors_live_in_one_place():
    """`balance` und der Bericht dürfen nicht auseinanderlaufen."""
    assert balance.DNF_TARGET is cal.DNF_TARGET
    assert balance.DURATION_TARGET_H is cal.DURATION_TARGET_H


# ----------------------------------------------------------------------
# Bericht
# ----------------------------------------------------------------------
def test_the_report_contains_all_three_sections(route, small_pool, effects):
    teams, riders = small_pool
    summary = cal.route_summary(route, riders, teams, (21,))
    arch_teams, arch_riders = cal.balanced_field(1, seed=5)
    stats = cal.archetype_stats(route, arch_riders, arch_teams, (11,))
    text = report.build_report(
        [summary], [(summary, stats)], [route], {route.name: effects}, "2026-01-01", "Testlauf"
    )
    assert "# Kalibrierung" in text
    assert "## 1 · Strecken" in text
    assert "## 2 · Archetypen" in text
    assert "## 3 · Was ein Attribut wert ist" in text
    assert route.name in text
    assert "Testlauf" in text
    # Nicht messbare Attribute stehen als Punkt in der Tabelle.
    assert "| sitzkomfort | · |" in text


def test_the_weather_run_forces_the_preset():
    assert cal.sensitivity_config(1).weather_preset is None
    assert cal.sensitivity_config(1, "hitze").weather_preset == "hitze"
    assert set(cal.WEATHER_PRESETS) <= set(wx.PRESETS)


def test_the_weather_section_lists_every_weather_attribute(route, small_pool):
    teams, riders = small_pool
    hot = cal.attribute_sensitivity(
        route, riders, teams, (17,), attributes=cal.WEATHER_ATTRIBUTES, preset="hitze"
    )
    text = "\n".join(report.section_weather(route, dict.fromkeys(cal.WEATHER_PRESETS, hot)))
    for attr in cal.WEATHER_ATTRIBUTES:
        assert f"| {attr} |" in text
    for preset in cal.WEATHER_PRESETS:
        assert preset in text


def test_an_attribute_that_only_works_in_bad_weather_is_not_called_dead(route, effects):
    """Was nur im Wetterlauf anspringt, darf nicht als tot gelten."""
    strong = cal.AttributeEffect("naesseresistenz", 200.0, 190.0, 0.5, 5.0, 40, 0)
    without = "\n".join(report.section_sensitivity([route], {route.name: effects}))
    with_rain = "\n".join(
        report.section_sensitivity([route], {route.name: effects}, {"regen": [strong]})
    )
    assert "`naesseresistenz`" in without
    assert "`naesseresistenz`" not in with_rain


def test_the_report_marks_a_missed_dnf_corridor(route, small_pool):
    teams, riders = small_pool
    summary = cal.route_summary(route, riders, teams, (21,))
    outside = replace(summary, dnf_pct=42.0, otl_pct=0.0)
    assert not outside.dnf_in_target
    assert "⚠" in "\n".join(report.section_routes([outside]))
