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


def test_no_attribute_is_without_a_consumer_any_more(effects):
    """Hier stand einmal das Gegenteil.

    Der Test hieß „ein Attribut ohne Abnehmer bewirkt nichts" und hatte
    nacheinander drei Kandidaten: erst ``sitzkomfort``, dann — als der
    einen Abnehmer bekam — ``oberflaechenkompetenz``. Mit dem
    Rollwiderstandsmodell aus Oberfläche, Reifen, Tempo und Last ist auch
    der letzte vergeben, und damit hat der alte Test keinen Kandidaten
    mehr. Statt ihn zu löschen, dreht er sich um: Jedes Attribut, das im
    Fahrerdetail steht, wird auch von irgendeiner Mechanik gelesen.

    Dass ein Attribut *gelesen* wird, heißt nicht, dass es auf jeder
    Strecke wirkt — ``oberflaechenkompetenz`` misst auf glattem Asphalt
    weiterhin exakt null, und das ist richtig so. Diese Zusicherung
    steht eine Zeile tiefer.
    """
    assert set(ACTIVE_ATTRIBUTES) == set(ATTRIBUTES), (
        "Alle 25 Attribute haben eine Mechanik — wer eines hinzufügt, "
        "muss ihm auch einen Abnehmer geben"
    )
    surface = next(e for e in effects if e.attr == "oberflaechenkompetenz")
    assert surface.seconds == 0.0, "auf einer reinen Asphaltstrecke gibt es nichts zu können"
    assert not surface.measurable


def test_noise_is_not_reported_as_an_effect():
    """Eine große Wirkung mit ebenso großem Standardfehler zählt nicht."""
    loud = cal.AttributeEffect("x", 400.0, 0.0, 1.0, stderr=300.0, pairs=20, dnf_delta=0)
    quiet = cal.AttributeEffect("x", 400.0, 380.0, 1.0, stderr=20.0, pairs=20, dnf_delta=0)
    assert not loud.measurable
    assert quiet.measurable


# ----------------------------------------------------------------------
# Die zweite Nachweisform: der Vorzeichentest
# ----------------------------------------------------------------------
def _effect(**kw) -> cal.AttributeEffect:
    base = dict(attr="x", seconds=10.0, seconds_median=10.0, percent=0.1, stderr=100.0, dnf_delta=0)
    base.update(kw)
    base.setdefault("pairs", int(base.get("wins", 0)) + int(base.get("losses", 0)))
    return cal.AttributeEffect(**base)  # type: ignore[arg-type]


def test_a_coin_toss_is_never_significant():
    assert _effect(wins=24, losses=24).sign_p == pytest.approx(1.0)
    assert not _effect(wins=24, losses=24).measurable


def test_a_one_sided_result_gets_very_small_very_fast():
    assert _effect(wins=48, losses=0).sign_p == pytest.approx(2 * 0.5**48)
    assert _effect(wins=40, losses=8).sign_p < 1e-5


def test_the_sign_test_admits_what_the_standard_error_cannot():
    """Der Fall, für den es die zweite Nachweisform überhaupt gibt.

    Abfahrtstechnik bei Nässe: 40 von 48 Fahrern gewinnen Zeit, aber ein
    paar stürzen trotz besserer Technik und ziehen das Mittel auf ein
    Achtel seines Standardfehlers. Nach der ersten Hürde allein stünde
    dort „nicht messbar" über einem Attribut, das dem typischen Fahrer
    eine halbe Minute wert ist.
    """
    skewed = _effect(seconds=13.9, seconds_median=26.7, stderr=46.7, wins=40, losses=8)
    assert abs(skewed.seconds) < cal.SIGMA * skewed.stderr, "die erste Hürde reißt er"
    assert skewed.measurable


def test_the_sign_test_does_not_rescue_a_two_edged_attribute():
    """Risikobereitschaft bei Sturm: Mittel negativ, Median positiv.

    Die Mehrheit fährt schneller, die Minderheit stürzt und verliert
    mehr, als die Mehrheit gewinnt. Beides ist wahr, und genau deshalb
    darf keine der beiden Zahlen als „die Wirkung" in der Tabelle
    stehen — der Richtungsabgleich hält sie draußen.
    """
    two_edged = _effect(seconds=-77.8, seconds_median=8.3, stderr=85.0, wins=32, losses=15)
    assert two_edged.sign_p < 0.05
    assert not two_edged.measurable


def test_a_consistent_direction_below_the_noise_floor_still_does_not_count():
    """Drei Sekunden bleiben drei Sekunden, auch wenn alle 48 sie gewinnen."""
    tiny = _effect(seconds=1.8, seconds_median=1.9, stderr=0.1, wins=48, losses=0)
    assert tiny.sign_p < 1e-10
    assert not tiny.measurable


def test_the_measurement_counts_the_directions_it_saw(effects):
    flat = next(e for e in effects if e.attr == "flach")
    assert flat.wins + flat.losses <= flat.pairs
    assert flat.wins > flat.losses, "Mehr Flachleistung muss bei den meisten Zeit bringen"
    dead = next(e for e in effects if e.attr == "oberflaechenkompetenz")
    assert dead.wins == dead.losses == 0, "Exakt gleiche Zeiten sind keine Richtung"


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
    assert summary.band == cal.duration_band(route.distance_km, route.ascent_m)
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


# ----------------------------------------------------------------------
# Dauerband: stetig statt in Eimern
# ----------------------------------------------------------------------
def test_the_duration_band_grows_with_distance_and_climbing():
    flat = cal.duration_band(400.0, 500.0)
    hilly = cal.duration_band(400.0, 6000.0)
    longer = cal.duration_band(800.0, 500.0)
    assert hilly[0] > flat[0] and hilly[1] > flat[1], "Höhenmeter kosten Zeit"
    assert longer[0] > flat[0], "Distanz auch"
    assert flat[0] < flat[1]


def test_climbing_counts_more_than_the_effort_rule():
    """Für die *Dauer* wiegen 100 hm mehr als einen Flachkilometer.

    ``classify_distance`` rechnet mit 100 hm ≈ 1 km — das ist die
    Faustregel für den Aufwand und bleibt dort richtig. Hier geht es um
    die Zeit, und die vier mitgelieferten Strecken zeigen, dass 1 km die
    Steigung um mehr als den Faktor zwei unterschätzt.
    """
    assert cal.ASCENT_KM_PER_100M > 1.5
    assert cal.equivalent_km(100.0, 1000.0) == pytest.approx(100.0 + 10.0 * cal.ASCENT_KM_PER_100M)


def test_a_flat_mid_distance_route_is_no_longer_flagged():
    """Der Fall, für den die Umstellung gebaut wurde.

    Die Flachetappe (466 km, 1075 hm) fällt als „mittel" in einen Eimer,
    dessen Band bei 15 h beginnt — und ist in 13,2 h gefahren. Das ⚠ galt
    der Klasseneinteilung, nicht der Strecke.
    """
    lo, hi = cal.duration_band(466.0, 1075.0)
    assert lo <= 13.2 <= hi
    # …und die bergige Strecke ähnlicher Länge trotzdem auch.
    lo2, hi2 = cal.duration_band(507.0, 6790.0)
    assert lo2 <= 17.8 <= hi2
    assert lo2 > hi / 2, "die beiden Bänder dürfen nicht dasselbe sein"


def test_the_archetype_table_reports_its_own_uncertainty(route, small_pool):
    teams, _ = small_pool
    arch_teams, arch_riders = cal.balanced_field(2, seed=5)
    stats = cal.archetype_stats(route, arch_riders, arch_teams, (11, 12))
    assert stats
    for st in stats:
        assert st.rank_se == st.rank_se, "ohne Standardfehler ist die Zeile nicht lesbar"
        assert 0.0 <= st.top_decile_pct <= 100.0
