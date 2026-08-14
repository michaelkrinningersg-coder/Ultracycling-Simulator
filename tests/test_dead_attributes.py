"""Die vier Attribute, die messbar nichts getan haben.

Der Kalibrierungsbericht aus M8 hat es nicht vermutet, sondern gemessen:
``sitzkomfort``, ``mechanikerfaehigkeit``, ``oberflaechenkompetenz`` und
``hoehenanpassung`` bewirkten auf keiner Strecke etwas — sie standen im
Fahrerdetail, kosteten Potenzial-Budget und wirkten nicht. Dazu kamen
``hitzetoleranz`` und ``abfahrtstechnik``, die zwar gelesen wurden, deren
Wirkung aber im Rauschen verschwand.

Diese Tests halten die Mechaniken fest, die daraus geworden sind. Sie
prüfen bewusst die *Funktionen*, nicht ganze Rennen: Ob sich am Ende
Sekunden bewegen, misst der Bericht — hier steht, dass die Größen
überhaupt in die richtige Richtung zeigen und an den richtigen Stellen
null sind.
"""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core import incidents as inc
from ultrasim.core import physics as ph


# ----------------------------------------------------------------------
# Sitzkomfort: Wundsein nach Stunden im Sattel
# ----------------------------------------------------------------------
def test_the_saddle_speaks_up_later_the_more_comfortable_the_rider():
    onset = inc.saddle_onset_h(np.array([10.0, 50.0, 90.0]))
    assert onset[0] < onset[1] < onset[2]
    # Der Mittelwert trifft die dokumentierte Schwelle.
    assert onset[1] == pytest.approx(inc.SADDLE_ONSET_H + inc.SADDLE_SCALE_H)


def test_nobody_gets_sore_on_a_short_race():
    """Unter zwölf Stunden ist Wundsein eine Frage der Hose."""
    assert inc.saddle_onset_h(np.array([99.0])).min() > 12.0


def test_the_saddle_condition_costs_power_and_descent_speed():
    from ultrasim.core.conditions import CATALOG

    spec = CATALOG["sitzbeschwerden"]
    assert spec.effects["ftp"] < 1.0
    assert spec.effects["abfahrtstempo"] < 1.0
    # Es heilt nicht im Sattel: Die Dauer überdauert jedes Rennen.
    assert inc.SADDLE_DURATION_S > 200.0 * 3600.0


# ----------------------------------------------------------------------
# Mechanikerfähigkeit: Standzeit nach einer Panne
# ----------------------------------------------------------------------
def test_a_better_mechanic_stands_shorter():
    ctx = inc.RideContext
    fast = inc._repair_factor(ctx(mechanic_norm=1.0))
    mid = inc._repair_factor(ctx(mechanic_norm=0.0))
    slow = inc._repair_factor(ctx(mechanic_norm=-1.0))
    assert fast < mid < slow
    assert mid == pytest.approx(1.0)
    assert slow / fast == pytest.approx((1 + inc.REPAIR_SKILL_SPAN) / (1 - inc.REPAIR_SKILL_SPAN))


def test_the_repair_factor_stays_in_a_sane_band():
    for norm in (-5.0, -1.0, 0.0, 1.0, 5.0):
        assert 0.5 <= inc._repair_factor(inc.RideContext(mechanic_norm=norm)) <= 1.6


def test_a_puncture_gets_shorter_with_skill():
    rng = np.random.default_rng(3)
    slow = inc.resolve("panne", np.random.default_rng(3), inc.RideContext(mechanic_norm=-1.0))
    fast = inc.resolve("panne", rng, inc.RideContext(mechanic_norm=1.0))
    assert fast.stop_s < slow.stop_s


# ----------------------------------------------------------------------
# Höhenanpassung: dünne Luft kostet Leistung
# ----------------------------------------------------------------------
def test_altitude_costs_nothing_below_the_threshold():
    assert ph.altitude_factor(0.0) == 1.0
    assert ph.altitude_factor(ph.ALTITUDE_THRESHOLD_M) == 1.0
    assert ph.altitude_factor(ph.ALTITUDE_THRESHOLD_M - 100.0) == 1.0


def test_altitude_costs_more_the_higher_it_gets():
    values = [ph.altitude_factor(ele) for ele in (1500.0, 2000.0, 2500.0, 3000.0)]
    assert values == sorted(values, reverse=True)
    # Rund 7 % je 1000 m über der Schwelle für einen Durchschnittsfahrer.
    assert ph.altitude_factor(2500.0) == pytest.approx(1.0 - 0.07, abs=0.005)


def test_the_adapted_rider_loses_less():
    high, low = ph.altitude_factor(2500.0, 1.0), ph.altitude_factor(2500.0, -1.0)
    assert high > low
    assert ph.altitude_factor(2500.0, 0.0) == pytest.approx((high + low) / 2, abs=1e-9)


def test_altitude_never_falls_through_the_floor():
    assert ph.altitude_factor(8000.0, -1.0) == pytest.approx(ph.ALTITUDE_FLOOR)


def test_thin_air_still_makes_you_faster_aerodynamically():
    """Höhe wirkt in beide Richtungen — sonst wäre sie nur ein Malus."""
    assert ph.air_density(2500.0) < ph.air_density(0.0)


# ----------------------------------------------------------------------
# Abfahrtstechnik: das Kurvenlimit muss überhaupt binden
# ----------------------------------------------------------------------
def test_the_braking_radius_is_tighter_than_the_average_bend():
    """Gebremst wird für die engste Kehre, nicht für den Mittelwert."""
    average = 57296.0 / 250.0
    assert ph.corner_radius_m(250.0) == pytest.approx(average / ph.CORNER_TIGHTNESS)


def test_a_switchback_section_binds_below_descent_speed():
    """Der Punkt der ganzen Übung.

    Vorher lag das Kurvenlimit auf jeder mitgelieferten Strecke über
    300 km/h und hat nie gebunden — Abfahrtstechnik war dadurch messbar
    wirkungslos, obwohl der Code sie gelesen hat.
    """
    limit = ph.corner_speed_limit(np.array([270.0]), np.array([0.0]), np.array([0.0]))
    assert 12.0 < float(limit[0]) < 20.0, "Kehren müssen zwischen 43 und 72 km/h binden"


def test_skill_and_risk_both_raise_the_limit():
    flat = ph.corner_speed_limit(np.array([270.0]), np.array([0.0]), np.array([0.0]))
    skilled = ph.corner_speed_limit(np.array([270.0]), np.array([1.0]), np.array([0.0]))
    bold = ph.corner_speed_limit(np.array([270.0]), np.array([0.0]), np.array([1.0]))
    assert skilled > flat and bold > flat
    # Können wiegt schwerer als Mut.
    assert skilled > bold


def test_a_straight_road_is_capped_by_the_safety_limit_not_by_corners():
    assert ph.corner_speed_limit(
        np.array([1.0]), np.array([0.0]), np.array([0.0])
    ) == pytest.approx(ph.MAX_SPEED)
