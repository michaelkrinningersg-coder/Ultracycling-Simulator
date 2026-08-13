"""Golden-Master-Test auf festen Seeds (Game-Design-Dokument, Abschnitt 13).

Zweck ist nicht, "richtig" zu prüfen – dafür sind die anderen Tests da.
Zweck ist, **Balancing-Änderungen sichtbar zu machen**: Wer an Physik,
Form, Ermüdung oder Strategiemodul dreht, soll hier sofort sehen, wie
stark sich das Ergebnis verschiebt, statt es Wochen später zu bemerken.

**Wenn dieser Test rot wird, ist er nicht kaputt.** Prüfe, ob die
Verschiebung gewollt ist, und übernimm dann die neuen Werte – der Test
druckt sie im Fehlerfall in kopierfertiger Form aus.

Die Toleranz ist bewusst locker (eine halbe Sekunde auf anderthalb
Stunden): Die Höhenglättung nutzt ``np.linalg.pinv`` und damit LAPACK,
das auf verschiedenen Plattformen um wenige ULP abweichen darf. Jede
gewollte Balancing-Änderung bewegt die Zeiten dagegen um Minuten, nicht
um Millisekunden.
"""

from __future__ import annotations

import pytest

from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.rider import generate_pool

#: Streckenkennzahlen der Testroute (siehe conftest).
GOLDEN_ROUTE = {
    "distance_m": 60_070.0,
    "ascent_m": 543.1,
    "n_splits": 6,
    "n_segments": 187,
    "n_climbs": 1,
}

#: (Startnummer, Zielzeit in s) für Seed 2024, Fahrerpool-Seed 31.
GOLDEN_RESULT = [
    (8, 5448.48),
    (5, 5521.01),
    (11, 5550.27),
    (12, 5563.15),
    (6, 5593.58),
    (9, 5632.09),
    (7, 5648.11),
    (3, 5658.64),
    (10, 5765.86),
    (2, 5831.76),
    (4, 6023.87),
    (1, 6159.90),
]

TOLERANCE_S = 0.5


def test_route_pipeline_is_stable(route):
    assert route.distance_m == pytest.approx(GOLDEN_ROUTE["distance_m"])
    assert route.ascent_m == pytest.approx(GOLDEN_ROUTE["ascent_m"], abs=1.0)
    assert len(route.splits) == GOLDEN_ROUTE["n_splits"]
    assert len(route.segments) == GOLDEN_ROUTE["n_segments"]
    assert len(route.climbs) == GOLDEN_ROUTE["n_climbs"]


def test_race_result_is_stable(route):
    teams, riders = generate_pool(12, n_teams=3, seed=31)
    result = simulate_race(route, riders, teams, RaceConfig(seed=2024))
    finished = sorted(
        (e for e in result.entries if e.finish_time_s is not None),
        key=lambda e: e.finish_time_s,
    )
    actual = [(e.bib, round(e.finish_time_s, 2)) for e in finished]

    if [bib for bib, _ in actual] != [bib for bib, _ in GOLDEN_RESULT] or any(
        abs(a - b) > TOLERANCE_S
        for (_, a), (_, b) in zip(actual, GOLDEN_RESULT, strict=True)
    ):
        block = "\n".join(f"    ({bib}, {t:.2f})," for bib, t in actual)
        pytest.fail(
            "Das Rennergebnis hat sich verschoben.\n"
            "Wenn das gewollt ist, ersetze GOLDEN_RESULT durch:\n\n"
            f"GOLDEN_RESULT = [\n{block}\n]\n\n"
            f"alt: {GOLDEN_RESULT}\nneu: {actual}"
        )
