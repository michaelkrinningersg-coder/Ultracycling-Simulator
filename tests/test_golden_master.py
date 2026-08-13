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
#:
#: Historie der bewussten Verschiebungen:
#: * M5.1 – Fehlplanung als Zustand (Abschnitt 6.5) und getrennte
#:   Zufallsströme je Zweck. Drei der zwölf Fahrer brechen jetzt spät
#:   ein, die Reihenfolge dahinter ändert sich entsprechend.
#: * M6.1 – Wetter, Wind und Tag-Nacht. Das Feld wird rund 12 % langsamer;
#:   der Seed zieht für diese Strecke einen milden, aber windigen Tag.
#:   Wind kostet Zeit, weil man in den Gegenwindabschnitten länger
#:   unterwegs ist als in den Rückenwindabschnitten – der Effekt hebt
#:   sich über eine Runde eben *nicht* auf.
GOLDEN_RESULT = [
    (8, 6151.26),
    (12, 6206.73),
    (6, 6213.62),
    (11, 6328.11),
    (5, 6429.78),
    (9, 6464.33),
    (7, 6473.78),
    (10, 6502.05),
    (3, 6506.74),
    (2, 6586.24),
    (4, 6874.38),
    (1, 7026.88),
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
