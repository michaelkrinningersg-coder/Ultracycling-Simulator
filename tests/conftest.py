"""Gemeinsame Fixtures.

Die Tests sollen ohne vorher erzeugte Daten laufen: Strecken werden im
Test aus einer synthetischen GPX-Datei importiert, Fahrer erzeugt der
Generator. Damit hängt kein Test an einer eingecheckten Datei, die
jemand versehentlich neu erzeugt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.make_demo_gpx import PRESETS, build_track, write_gpx  # noqa: E402
from ultrasim.core.rider import generate_pool  # noqa: E402
from ultrasim.geo.gpx_import import import_gpx  # noqa: E402


@pytest.fixture(scope="session")
def demo_gpx(tmp_path_factory) -> Path:
    """Kurze synthetische Strecke mit realistischem DEM-Rauschen."""
    path = tmp_path_factory.mktemp("gpx") / "test.gpx"
    _, profile, (lat, lon, ele) = PRESETS["voralpen"]
    # Auf ein Fünftel gestaucht: schnell genug für die Testsuite, aber
    # immer noch mit Anstieg, Abfahrt und Flachstück.
    small = [(length / 5.0, grade) for length, grade in profile]
    tracks = build_track(small, lat, lon, ele, 25.0, 1.2, 4711)
    write_gpx(path, "Teststrecke", *tracks)
    return path


@pytest.fixture(scope="session")
def route(demo_gpx):
    route, _ = import_gpx(demo_gpx, name="Teststrecke")
    return route


@pytest.fixture(scope="session")
def report(demo_gpx):
    _, report = import_gpx(demo_gpx, name="Teststrecke")
    return report


@pytest.fixture(scope="session")
def pool():
    return generate_pool(24, n_teams=4, seed=99)
