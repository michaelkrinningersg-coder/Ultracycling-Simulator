"""Tests von Wetter, Wind, Tag-Nacht und Hydration (M6.1).

Zwei Fehler aus dem ersten Entwurf sind hier als Test festgehalten, weil
sie beide dieselbe Form hatten — eine Mechanik, die im Code steht, aber
nirgends ankommt:

* Seitenwind wirkte auf das Kurvenlimit, das im Flachen nie greift.
* Der Höhengradient verschob das eingestellte Wetter als Ganzes, statt
  Kontrast innerhalb der Strecke zu erzeugen.
"""

from __future__ import annotations

import numpy as np
import pytest

from ultrasim.core import nutrition as nut
from ultrasim.core import weather as wx
from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.rider import Rider, generate_pool, generate_rider


# ----------------------------------------------------------------------
# Profil
# ----------------------------------------------------------------------
def test_profile_roundtrip():
    rng = np.random.default_rng(3)
    profile = wx.draw_profile(rng, day_of_year=172, duration_h=20.0)
    again = wx.WeatherProfile.from_dict(profile.to_dict())
    assert again.base_temp_c == pytest.approx(profile.base_temp_c, abs=0.05)
    assert again.wind_from_deg == pytest.approx(profile.wind_from_deg, abs=0.05)
    assert len(again.rain_phases) == len(profile.rain_phases)


def test_season_shifts_the_temperature_level():
    summer = np.mean(
        [wx.draw_profile(np.random.default_rng(i), 200, 10.0).base_temp_c for i in range(200)]
    )
    winter = np.mean(
        [wx.draw_profile(np.random.default_rng(i), 20, 10.0).base_temp_c for i in range(200)]
    )
    assert summer > winter + 10.0


def test_presets_are_wellformed_and_deliver_what_they_promise():
    for key in wx.PRESETS:
        profile = wx.draw_profile(np.random.default_rng(0), 172, 8.0, preset=key)
        assert profile.label
        assert -30.0 < profile.base_temp_c < 50.0
        assert profile.wind_speed_ms >= 0.0
    hot = wx.draw_profile(np.random.default_rng(0), 172, 8.0, preset="hitze")
    cold = wx.draw_profile(np.random.default_rng(0), 172, 8.0, preset="kalt")
    storm = wx.draw_profile(np.random.default_rng(0), 172, 8.0, preset="sturm")
    assert hot.base_temp_c > cold.base_temp_c + 15
    assert storm.wind_speed_ms > 8.0


def test_rain_preset_actually_rains_even_on_a_short_race():
    """Die Phasenziehung ist auf lange Rennen ausgelegt.

    Ohne Sonderbehandlung zöge ein "Dauerregen" über 2 Stunden meist gar
    keine Phase – ein Preset, das nicht hält, was es verspricht.
    """
    profile = wx.draw_profile(np.random.default_rng(0), 172, duration_h=2.0, preset="regen")
    assert profile.rain_phases
    assert profile.rain_at(0.5) > 0.3
    assert profile.rain_at(1.5) > 0.3


def test_unknown_preset_is_rejected():
    with pytest.raises(KeyError):
        wx.draw_profile(np.random.default_rng(0), preset="schneesturm")


def test_temperature_peaks_in_the_afternoon():
    profile = wx.WeatherProfile(base_temp_c=15.0, temp_amplitude_c=8.0)
    hours = np.arange(0, 24, 0.5)
    temps = [profile.temperature_at(h) for h in hours]
    assert 13.0 <= hours[int(np.argmax(temps))] <= 17.0
    assert 1.0 <= hours[int(np.argmin(temps))] <= 5.0


# ----------------------------------------------------------------------
# Ortsschicht
# ----------------------------------------------------------------------
def test_lapse_rate_creates_contrast_inside_the_route_not_a_global_shift():
    """Bezugspunkt ist die mittlere Streckenhöhe, nicht Meeresniveau.

    Sonst würde aus einem eingestellten „29 °C, Hitze" auf einer Strecke
    um 1200 m stillschweigend ein 21-°C-Tag – das Preset hielte nicht,
    was es sagt.
    """
    ele = np.array([600.0, 1200.0, 1800.0])
    ref = float(ele.mean())
    temp = wx.local_temperature(25.0, ele, ref, np.zeros(3), is_night=False)
    assert temp[1] == pytest.approx(25.0)  # auf Bezugshöhe genau der Sollwert
    assert temp[0] > temp[1] > temp[2]  # unten wärmer, oben kühler
    assert temp[0] - temp[2] == pytest.approx(1200 * wx.LAPSE_RATE_C_PER_M, abs=0.1)


def test_valleys_are_colder_at_night_only():
    ele = np.full(2, 500.0)
    exposure = np.array([-1.0, 1.0])  # Talboden und Kuppe
    day = wx.local_temperature(12.0, ele, 500.0, exposure, is_night=False)
    night = wx.local_temperature(12.0, ele, 500.0, exposure, is_night=True)
    assert day[0] == pytest.approx(day[1])
    assert night[0] < night[1]
    assert night[1] == pytest.approx(day[1])


def test_exposure_finds_ridges_and_valleys():
    x = np.linspace(0, 4 * np.pi, 2000)
    ele = 500.0 + 300.0 * np.sin(x)
    exposure = wx.exposure_profile(ele, raster_m=10.0)
    assert exposure.shape == ele.shape
    assert -1.01 <= exposure.min() and exposure.max() <= 1.01
    # Auf dem Kamm exponierter als in der Senke.
    assert exposure[int(np.argmax(ele))] > exposure[int(np.argmin(ele))]


def test_ridges_are_windier():
    assert wx.local_wind_factor(np.array([1.0]))[0] > wx.local_wind_factor(np.array([-1.0]))[0]
    assert wx.local_wind_factor(np.array([0.0]))[0] == pytest.approx(1.0)


# ----------------------------------------------------------------------
# Wind
# ----------------------------------------------------------------------
def test_wind_decomposition():
    speed = np.full(4, 8.0)
    head, cross = wx.wind_components(speed, 270.0, np.array([270.0, 90.0, 0.0, 180.0]))
    assert head[0] == pytest.approx(8.0)  # direkt hinein
    assert head[1] == pytest.approx(-8.0)  # direkt im Rücken
    assert abs(head[2]) < 1e-9 and abs(head[3]) < 1e-9
    assert cross[2] == pytest.approx(8.0)
    assert cross[0] < 1e-9


def test_crosswind_raises_drag_and_scales_with_body_size():
    small = wx.crosswind_cda_factor(np.array([8.0]), np.array([0.22]), np.array([0.0]))[0]
    large = wx.crosswind_cda_factor(np.array([8.0]), np.array([0.31]), np.array([0.0]))[0]
    assert 1.0 < small < large
    resistant = wx.crosswind_cda_factor(np.array([8.0]), np.array([0.31]), np.array([1.0]))[0]
    assert resistant < large
    assert wx.crosswind_cda_factor(np.array([0.0]), np.array([0.26]), np.array([0.0]))[0] == 1.0


# ----------------------------------------------------------------------
# Wirkung
# ----------------------------------------------------------------------
def test_climate_is_neutral_in_the_comfort_band():
    zero = np.array([0.0])
    for temp in (10.0, 15.0, 20.0, 24.9):
        assert wx.climate_factor(np.array([temp]), zero, zero)[0] == 1.0


def test_heat_and_cold_both_cost_and_tolerance_helps():
    zero, strong = np.array([0.0]), np.array([1.0])
    hot = wx.climate_factor(np.array([35.0]), zero, zero)[0]
    cold = wx.climate_factor(np.array([-3.0]), zero, zero)[0]
    assert hot < 1.0 and cold < 1.0
    assert wx.climate_factor(np.array([35.0]), strong, zero)[0] > hot
    assert wx.climate_factor(np.array([-3.0]), zero, strong)[0] > cold
    assert wx.climate_factor(np.array([60.0]), zero, zero)[0] >= wx.CLIMATE_FLOOR


def test_rain_costs_grip_and_rolling_resistance():
    zero = np.array([0.0])
    assert wx.wet_crr_factor(0.0, zero)[0] == 1.0
    assert wx.wet_crr_factor(1.0, zero)[0] > 1.1
    assert wx.surface_mu(1.0, zero)[0] < wx.surface_mu(0.0, zero)[0]
    assert wx.surface_mu(0.0, zero)[0] == pytest.approx(wx.MU_DRY)


def test_night_slows_descents():
    assert wx.night_descent_factor(True) == 1.0
    assert wx.night_descent_factor(False) < 1.0


# ----------------------------------------------------------------------
# Sonnenstand
# ----------------------------------------------------------------------
def test_daylight_length_matches_reality():
    """München, 21. Juni: knapp 16 Stunden. 21. Dezember: gut 8."""
    summer = wx.sun_times(48.1, 172)
    winter = wx.sun_times(48.1, 355)
    assert 15.5 < summer[1] - summer[0] < 16.5
    assert 8.0 < winter[1] - winter[0] < 8.8


def test_equator_is_always_twelve_hours():
    for day in (1, 90, 180, 270):
        rise, set_ = wx.sun_times(0.0, day)
        assert set_ - rise == pytest.approx(12.0, abs=0.3)


def test_polar_day_and_night_do_not_crash():
    assert wx.sun_times(80.0, 172) == (0.0, 24.0)
    assert wx.sun_times(80.0, 355) == (12.0, 12.0)


def test_is_daylight():
    assert wx.is_daylight(12.0, 5.0, 21.0)
    assert not wx.is_daylight(3.0, 5.0, 21.0)
    assert not wx.is_daylight(22.0, 5.0, 21.0)


# ----------------------------------------------------------------------
# Hydration
# ----------------------------------------------------------------------
def test_sweating_falls_in_the_cold():
    """Der auffälligste Modellfehler wäre ein Fahrer, der bei 3 °C
    literweise Wasser verliert."""
    warm = nut.sweat_rate_l_h(np.array([0.7]), np.array([30.0]), 0.5, np.array([0.0]))[0]
    mild = nut.sweat_rate_l_h(np.array([0.7]), np.array([20.0]), 0.5, np.array([0.0]))[0]
    cold = nut.sweat_rate_l_h(np.array([0.7]), np.array([3.0]), 0.5, np.array([0.0]))[0]
    assert warm > mild > cold
    assert cold < 0.8
    assert 0.9 < mild < 1.4


def test_humidity_only_matters_in_the_warmth():
    cold_dry = nut.sweat_rate_l_h(np.array([0.7]), np.array([8.0]), 0.3, np.array([0.0]))[0]
    cold_damp = nut.sweat_rate_l_h(np.array([0.7]), np.array([8.0]), 0.95, np.array([0.0]))[0]
    assert cold_dry == pytest.approx(cold_damp)
    warm_dry = nut.sweat_rate_l_h(np.array([0.7]), np.array([32.0]), 0.3, np.array([0.0]))[0]
    warm_damp = nut.sweat_rate_l_h(np.array([0.7]), np.array([32.0]), 0.95, np.array([0.0]))[0]
    assert warm_damp > warm_dry


def test_dehydration_deadband_and_slope():
    assert nut.hydration_factor(np.array([1.5]))[0] == 1.0
    assert nut.hydration_factor(np.array([3.0]))[0] == pytest.approx(0.98)
    assert nut.hydration_factor(np.array([5.0]))[0] == pytest.approx(0.94)


def test_hydration_display_maps_to_the_documented_range():
    assert nut.hydration_display_pct(np.array([0.0]))[0] == 100.0
    assert nut.hydration_display_pct(np.array([3.0]))[0] == pytest.approx(50.0)
    assert nut.hydration_display_pct(np.array([6.0]))[0] == 0.0
    assert nut.hydration_display_pct(np.array([9.0]))[0] == 0.0


# ----------------------------------------------------------------------
# Im Rennen
# ----------------------------------------------------------------------
def _solo(route, preset, **attrs):
    """Ein einzelner Fahrer, damit der Effekt isoliert messbar ist."""
    teams, _ = generate_pool(4, n_teams=2, seed=31)
    base = generate_rider(np.random.default_rng(0), 0, 0, archetype="allrounder")
    rider = Rider(**{**base.to_dict(), "attributes": {**base.attributes, **attrs}})
    result = simulate_race(
        route, [rider], teams, RaceConfig(seed=2024, weather_preset=preset)
    )
    return result.entries[0].finish_time_s


@pytest.mark.parametrize(
    "preset,attribute",
    [
        ("hitze", "hitzetoleranz"),
        ("kalt", "kaeltetoleranz"),
        ("regen", "naesseresistenz"),
        ("sturm", "seitenwindfestigkeit"),
    ],
)
def test_every_weather_attribute_actually_changes_the_result(route, preset, attribute):
    """Die Lehre aus zwei Fehlern im ersten Entwurf.

    Beide hatten dieselbe Form: eine Mechanik, die im Code steht, aber
    nirgends ankommt. Für jede Wetterlage muss das zugehörige Attribut
    einen messbaren Unterschied machen.
    """
    strong = _solo(route, preset, **{attribute: 95.0})
    weak = _solo(route, preset, **{attribute: 5.0})
    assert weak > strong + 5.0, f"{attribute} wirkt bei '{preset}' nicht"


def test_weather_is_deterministic_and_stored(route):
    teams, riders = generate_pool(8, n_teams=2, seed=31)
    a = simulate_race(route, riders, teams, RaceConfig(seed=7))
    b = simulate_race(route, riders, teams, RaceConfig(seed=7))
    c = simulate_race(route, riders, teams, RaceConfig(seed=8))
    assert a.weather.to_dict() == b.weather.to_dict()
    assert a.weather.to_dict() != c.weather.to_dict()
    assert a.weather.label


def test_weather_does_not_depend_on_the_field(route):
    """Das Wetter hängt am Rennen, nicht daran, wer meldet."""
    teams, riders = generate_pool(20, n_teams=4, seed=31)
    small = simulate_race(route, riders[:5], teams, RaceConfig(seed=7))
    large = simulate_race(route, riders, teams, RaceConfig(seed=7))
    assert small.weather.to_dict() == large.weather.to_dict()


def test_hydration_is_tracked_and_bounded(route):
    teams, riders = generate_pool(8, n_teams=2, seed=31)
    result = simulate_race(route, riders, teams, RaceConfig(seed=7, weather_preset="hitze"))
    tel = result.telemetry
    assert tel.hydration_pct.dtype == np.uint8
    assert tel.hydration_pct.max() <= 100
    assert np.all(tel.hydration_pct[:, 0] == 100)
    assert tel.hydration_pct[tel.state < 2].min() < 100  # in der Hitze wird es eng


def test_cold_weather_does_not_dehydrate(route):
    teams, riders = generate_pool(8, n_teams=2, seed=31)
    result = simulate_race(route, riders, teams, RaceConfig(seed=7, weather_preset="kalt"))
    tel = result.telemetry
    # Bei 5 °C darf über eine kurze Distanz praktisch nichts verloren gehen.
    assert tel.hydration_pct[tel.state < 2].min() > 90
