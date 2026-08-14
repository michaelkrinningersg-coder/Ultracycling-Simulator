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

from collections import Counter

import pytest

from ultrasim.core.engine import RaceConfig, simulate_race
from ultrasim.core.rider import generate_pool

#: Streckenkennzahlen der Testroute (siehe conftest).
GOLDEN_ROUTE = {
    "distance_m": 60_100.0,
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
#: * M6.2 – Zwischenfälle. Genau zwei der zwölf Fahrer trifft auf diesen
#:   60 km etwas (Startnummer 7 und 1), die übrigen zehn Zeiten bleiben
#:   auf die Hundertstelsekunde gleich. Dass nur die Betroffenen sich
#:   bewegen, ist die eigentliche Aussage dieses Laufs: Der Ereignisstrom
#:   ist von allen anderen Zufallsströmen getrennt.
#: * M7b – Regelkreis des Strategiemoduls. Genau ein Fahrer bewegt sich:
#:   Startnummer 7 hatte auf diesen 60 km so viel Zeit verloren, dass er
#:   in die Aufholjagd geht, und holt davon 71 Sekunden zurück. Die elf
#:   anderen erleben keine Lage, in der eine Regel greift — auf einer
#:   Strecke von anderthalb Stunden ist das der Normalfall.
#: * M8 – **keine** Balancing-Änderung, sondern eine Reparatur am
#:   Streckengenerator. Er hat die Punktzahl mit ``int()`` abgeschnitten,
#:   und die Profillängen summieren sich exakt auf eine Ganzzahlgrenze:
#:   Seit Python 3.12 summiert ``sum()`` für Fließkommazahlen kompensiert
#:   und trifft 60,1 statt 60,099999999999994. Damit hatte die Teststrecke
#:   unter 3.11 einen Punkt weniger als unter 3.12 — dieser Test war auf
#:   der einen Version grün und auf der anderen rot, und niemand hat es
#:   gemerkt, weil der Entwicklungsrechner 3.11 fährt. Der Generator
#:   rundet jetzt; die Strecke ist auf allen Versionen 60 100 m lang und
#:   das Feld entsprechend 2,5 s langsamer.
#: * M8 – Archetyp-Balancing. Der Kletterer hatte bei gleichem Budget in
#:   *jeder* physischen Größe die Nase vorn: mehr W/kg, mehr absolute
#:   Watt und die kleinste Frontfläche. Sein ``wkg_bias`` sinkt von 0,45
#:   auf 0,20, der des Zeitfahrers steigt von −0,10 auf 0. Damit ändern
#:   sich Gewicht und FTP aller neu erzeugten Fahrer, und die Reihenfolge
#:   verschiebt sich entsprechend – Startnummer 6 und 3 gewinnen, 10
#:   verliert drei Minuten.
GOLDEN_RESULT = [
    (6, 6149.69),
    (8, 6153.77),
    (12, 6209.28),
    (11, 6330.70),
    (3, 6431.96),
    (5, 6432.69),
    (9, 6466.89),
    (2, 6589.41),
    (10, 6683.31),
    (4, 6877.14),
    (7, 7198.12),
    (1, 7238.15),
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

    _compare(actual, GOLDEN_RESULT, TOLERANCE_S, "GOLDEN_RESULT")


# ----------------------------------------------------------------------
# Zweiter Lauf: die lange Distanz
# ----------------------------------------------------------------------
#: Der kurze Lauf oben dauert anderthalb Stunden. Schlaf, zweite Nacht,
#: Notschlaf, Aufgabe – die halbe Simulation kommt dort nie an die
#: Reihe, und eine Änderung daran bliebe unbemerkt. Dieser Lauf holt das
#: nach: rund 1000 km, 40 Stunden, acht Fahrer.
#:
#: Die Toleranz ist mit zwei Sekunden auf 40 Stunden lockerer als oben –
#: dieselbe Begründung, nur über 25-mal so viele Rechenschritte.
GOLDEN_LONG_ROUTE = {"distance_m": 1_045_500.0, "ascent_m": 6847.0, "class": "mittel"}

#: * Radwechsel am Anstieg. Vorher konnte ein Fahrer nur am
#:   Servicepunkt wechseln; auf 507 km mit fünf Servicepunkten war ein
#:   Abschnitt 90 km lang, und weil darin 80 % Flachland stecken, gewann
#:   das Zeitfahrrad über die Summe — der Fahrer quälte sich damit über
#:   jeden Pass. Jetzt sind Fuß und Kuppe kategorisierter Anstiege
#:   ebenfalls Abschnittsgrenzen (im unterstützten Rennen steht das
#:   Begleitfahrzeug dort). Aus 0 werden 11 Radwechsel, und das Feld
#:   wird auf dieser welligen Strecke rund 10 Minuten langsamer: Die
#:   Wechsel kosten Zeit, die sich erst auf steileren Pässen auszahlt.
GOLDEN_LONG_RESULT: list[tuple[int, float]] = [
    (5, 143389.09),
    (7, 144156.60),
    (8, 147473.97),
    (3, 151516.47),
    (1, 158590.47),
    (4, 164359.10),
    (6, 167968.84),
]

#: Wie oft welches Ereignis fällt. Diese Zeile ist der eigentliche
#: Gewinn des langen Laufs: Wer am Schlafmodell dreht, sieht hier sofort,
#: dass aus zwei Schlafstopps plötzlich keiner mehr wird – auch wenn die
#: Zielzeiten in der Toleranz bleiben.
GOLDEN_LONG_EVENTS: dict[str, int] = {
    "BIKE_CHANGE": 11,
    "CONDITION_END": 32,
    "CONDITION_START": 32,
    "DECISION": 9,
    "DNF": 1,
    "FINISH": 7,
    "INCIDENT": 48,
    "PLAN": 75,
    "SLEEP": 2,
    "SPLIT_PASSED": 315,
    "START": 8,
    "STOP_END": 129,
    "STOP_START": 82,
}

TOLERANCE_LONG_S = 2.0


@pytest.mark.slow
def test_long_race_result_is_stable(route_long):
    assert route_long.distance_m == pytest.approx(GOLDEN_LONG_ROUTE["distance_m"], abs=50.0)
    assert route_long.ascent_m == pytest.approx(GOLDEN_LONG_ROUTE["ascent_m"], abs=5.0)
    assert route_long.distance_class == GOLDEN_LONG_ROUTE["class"]

    teams, riders = generate_pool(8, n_teams=2, seed=77)
    result = simulate_race(route_long, riders, teams, RaceConfig(seed=2024))
    finished = sorted(
        (e for e in result.entries if e.finish_time_s is not None),
        key=lambda e: e.finish_time_s,
    )
    actual = [(e.bib, round(e.finish_time_s, 2)) for e in finished]
    events = dict(sorted(Counter(e.type for e in result.events).items()))

    if events != GOLDEN_LONG_EVENTS:
        pytest.fail(
            "Der Ereignisstrom hat sich verschoben.\n"
            "Wenn das gewollt ist, ersetze GOLDEN_LONG_EVENTS durch:\n\n"
            f"GOLDEN_LONG_EVENTS = {events}\n\n"
            f"alt: {GOLDEN_LONG_EVENTS}"
        )
    _compare(actual, GOLDEN_LONG_RESULT, TOLERANCE_LONG_S, "GOLDEN_LONG_RESULT")


def _compare(
    actual: list[tuple[int, float]],
    golden: list[tuple[int, float]],
    tolerance: float,
    name: str,
) -> None:
    same_order = [bib for bib, _ in actual] == [bib for bib, _ in golden]
    if not same_order or any(
        abs(a - b) > tolerance for (_, a), (_, b) in zip(actual, golden, strict=True)
    ):
        block = "\n".join(f"    ({bib}, {t:.2f})," for bib, t in actual)
        pytest.fail(
            "Das Rennergebnis hat sich verschoben.\n"
            f"Wenn das gewollt ist, ersetze {name} durch:\n\n"
            f"{name} = [\n{block}\n]\n\n"
            f"alt: {golden}\nneu: {actual}"
        )
