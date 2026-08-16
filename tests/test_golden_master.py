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
#:
#: ``n_splits`` stand bei 6, solange das Raster in Kilometern gestaffelt
#: war (10 km auf einer 60-km-Strecke). Seit es bei jeweils fünf Prozent
#: steht, sind es zwanzig — auf jeder Strecke gleich viele, und das ist
#: der Zweck der Umstellung.
GOLDEN_ROUTE = {
    "distance_m": 60_100.0,
    "ascent_m": 457.2,
    "n_splits": 20,
    "n_segments": 189,
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
#: * Sechs tote Attribute (nach M8). Fünf Mechaniken kamen dazu —
#:   Sitzbeschwerden ab zwölf Stunden, Reparaturzeit aus der
#:   Mechanikerfähigkeit, Leistungsverlust über 1500 m, ein bindendes
#:   Kurvenlimit und Kehren im Streckengenerator. Dazu die Reparatur
#:   einer alten Datenschwäche: Die Profile stiegen netto durchgehend an,
#:   die „Runde" endete 800 m über ihrem Start. Seit der Entdriftung ist
#:   die Teststrecke flacher (457 statt 543 hm) und das Feld entsprechend
#:   zweieinhalb Minuten schneller.
#: * Der Anstiegsaufschlag wird bezahlt. Bis hierher hat ``berg`` Watt
#:   verschenkt: Die Zielintensität kam aus Distanz, Ausdauer und
#:   Erfahrung, der Aufschlag am Anstieg kam obendrauf, und niemand hat
#:   ihn abgetragen. Jetzt normiert der Plan die zeitgewichtete mittlere
#:   Intensität auf den geplanten Wert — wer am Berg zulegt, fährt im
#:   Flachen darunter. Dazu die Positionsdisziplin aus ``flach``, die
#:   von ±3 % auf ±8 % CdA aufgezogen wurde, und eine Fehlplanung, die
#:   früher greift. Auf diesen welligen 60 km verschiebt sich fast das
#:   ganze Feld: Startnummer 12 gewinnt zwei Plätze, 5 verliert einen,
#:   und die Zeiten wandern um bis zu anderthalb Minuten.
#: **Einmalig neu gesetzt beim Wechsel auf feste Teams.**
#:
#: ``generate_pool`` zog Teams und Fahrer aus *einem* Generator. Als die
#: Teamnamen von zufälligen Kombinationen auf eine feste Liste
#: umgestellt wurden, zog ein Team drei Zufallszahlen weniger (Präfix,
#: Suffix, Farbton) — und damit verschob sich jede Ziehung dahinter.
#: Derselbe Seed lieferte ein anderes Fahrerfeld, obwohl an den Fahrern
#: nichts geändert war.
#:
#: Die Zahlen unten neu zu setzen ist deshalb genau der Griff, den ein
#: Golden Master verhindern soll — und hier trotzdem richtig, weil die
#: Ursache verstanden ist und *behoben*: Teams und Fahrer haben seitdem
#: getrennte Ströme (``spawn_key``), und
#: ``test_the_team_list_does_not_move_the_riders`` hält das fest. Eine
#: Änderung an der Teamliste bewegt ab jetzt keinen Fahrer mehr, dieser
#: Neusatz war der letzte seiner Art.
#:
#: **Neu gesetzt mit den Ampeln.** Die Strecke hat seitdem Ampeln, und
#: eine rote hält den Fahrer bis zu 90 s auf. Von zwölf Fahrern sind
#: **neun bitgleich geblieben** — nur 12, 8 und 3 standen an einer roten
#: Ampel. Genau das erwartet man von der Mechanik: Sie greift dort ein,
#: wo jemand vor einer Ampel ankommt, und sonst nirgends. Wer die Ampeln
#: aus einer Strecke entfernt, bekommt die alten Zahlen zurück; das
#: sichert ``test_a_route_without_lights_races_exactly_as_before``.
GOLDEN_RESULT = [
    (12, 6147.30),
    (8, 6165.46),
    (4, 6251.66),
    (9, 6306.16),
    (11, 6335.41),
    (10, 6369.10),
    (5, 6497.97),
    (1, 6572.98),
    (2, 6593.59),
    (7, 6646.14),
    (6, 6736.09),
    (3, 7012.08),
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
GOLDEN_LONG_ROUTE = {"distance_m": 1_045_500.0, "ascent_m": 5217.7, "class": "mittel"}

#: * Radwechsel am Anstieg. Vorher konnte ein Fahrer nur am
#:   Servicepunkt wechseln; auf 507 km mit fünf Servicepunkten war ein
#:   Abschnitt 90 km lang, und weil darin 80 % Flachland stecken, gewann
#:   das Zeitfahrrad über die Summe — der Fahrer quälte sich damit über
#:   jeden Pass. Jetzt sind Fuß und Kuppe kategorisierter Anstiege
#:   ebenfalls Abschnittsgrenzen (im unterstützten Rennen steht das
#:   Begleitfahrzeug dort). Aus 0 werden 11 Radwechsel, und das Feld
#:   wird auf dieser welligen Strecke rund 10 Minuten langsamer: Die
#:   Wechsel kosten Zeit, die sich erst auf steileren Pässen auszahlt.
#: * Bezahlter Anstiegsaufschlag, weitere Aero-Spanne, frühere
#:   Fehlplanung. Der Führungswechsel an der Spitze (7 vor 5 statt
#:   umgekehrt) ist die Aussage dieses Laufs: Auf 1000 km mit 5200 hm
#:   entscheidet jetzt, wer seinen Aufschlag verkraftet, nicht wer ihn
#:   geschenkt bekommt. Die acht zusätzlichen PLAN-Ereignisse sind die
#:   neue Begründungszeile im Rennplan — je Fahrer eine.
#: * Pacing-Disziplin wirkt in beide Richtungen. Oberhalb des
#:   Mittelwerts kaufte das Attribut bis dahin nichts — ein Fahrer mit
#:   80 plante wie einer mit 50. Jetzt darf er näher an die eigene
#:   Grenze planen, und nur die Fahrer über 50 bewegen sich; die
#:   Ereigniszählung bleibt gleich.
#: * Pacing-Disziplin wirkt über den Kraftstoff. Der erste Anlauf hatte
#:   sie auf die Wunschintensität gelegt und damit ins Leere — der
#:   Rennplan nimmt ``min(wish_if, energy_if)``, und der Energiedeckel
#:   bindet bei praktisch jedem Fahrer. Jetzt senkt Disziplin den
#:   Kohlenhydratverbrauch (der ist quadratisch in der Intensität, also
#:   kostet ungleichmäßiges Fahren echtes Substrat), und das wirkt
#:   *innerhalb* des Deckels. Auf 40 Stunden ist das viel: Startnummer 6
#:   gewinnt eine halbe Stunde, 4 gut 25 Minuten.
#: * Rollwiderstand aus Oberfläche, Reifen, Tempo und Last. Der Beiwert
#:   war bis hierher eine Konstante je Segment; jetzt steigt er mit dem
#:   Tempo (Walkarbeit im Reifen) und mit der Systemmasse. Auf der
#:   Teststrecke ohne Schotter ist das der einzige wirksame Teil — das
#:   Feld wird rund 20 Sekunden langsamer, die Reihenfolge bleibt. Die
#:   acht zusätzlichen PLAN-Ereignisse sind die Begründung der
#:   Reifenwahl, je Fahrer eine.
#: * Fettverbrenner und Diesel ausbalanciert. Der eine gewann beide
#:   Seiten der Energiebilanz — weniger Verbrauch *und* mehr Nachschub —,
#:   der andere trug mit ``wkg_bias=-0.20`` eine Leistungsstrafe
#:   außerhalb des Potenzial-Budgets. Beides sind Eingriffe am Generator,
#:   also ändert sich jeder erzeugte Fahrer und damit das ganze Feld.
#: * W′ bindet endlich. Bis hierher stand die anaerobe Kapazität in
#:   jedem gemessenen Rennen auf 100 % — der Anteil der Zeit unter 95 %
#:   war exakt null, und ``spritzigkeit`` damit wirkungslos. Zwei
#:   Ursachen: Die Zielleistung kam nie über die Schwelle (0,86 · FTP
#:   auf der Mitteldistanz), und keine Strecke hatte eine Rampe über
#:   10,8 %. Jetzt gibt es einen zweiten, an der *Schwelle* aufgehängten
#:   Term ab acht Prozent Steigung, und der Hochgebirgs-Marathon hat
#:   Rampen mit 13 und 15 %. Auf der Teststrecke hier wirkt nur der
#:   erste Teil — sie bleibt unter zehn Prozent —, das Feld verschiebt
#:   sich trotzdem, weil der Streckenimport dieselbe Strecke neu
#:   segmentiert.
#: * Trittfrequenz und Entfaltung. Der pauschale Steilabzug des
#:   Zeitfahrrads (4 % ab sechs Prozent Steigung, gleich hoch bei
#:   sieben wie bei fünfzehn) ist weg; stattdessen hat jedes Rad eine
#:   Entfaltungsspanne, und der Verlust folgt daraus. An mäßiger
#:   Steigung ist er null — dort tritt man auch mit 42×28 noch 79
#:   Umdrehungen —, an einer 15-%-Rampe sind es 58 Umdrehungen und
#:   knapp vier Prozent. Deshalb die drei BIKE_CHANGE auf dieser
#:   welligen Strecke, wo vorher keiner stattfand: Das Zeitfahrrad
#:   lohnt sich an Wellen wieder, an Rampen nicht.
#:   Dazu die gemeinsame Ursache der beiden: Der **Preis** eines
#:   Attributs im Potenzial-Budget hatte nichts mit seiner gemessenen
#:   Wirkung zu tun. ``fettverbrennung`` kostete 0,8 und wirkt bis zu
#:   506 s, ``konstanz`` kostete 0,9 und wirkt nichts — der eine kaufte
#:   billig ein, der andere zahlte für nichts. Beide Preise sind
#:   nachgezogen, und weil das Budget alle Attribute gegeneinander
#:   normiert, verschiebt sich jeder Fahrer ein Stück. Die Umpreisung
#:   hat als Balancing-Hebel dann allerdings nur ein bis drei Plätze
#:   gebracht — weniger als einen Standardfehler. Gewirkt haben die
#:   Offsets und der Körperbau: ``fettverbrennung`` von 24 auf 15 und
#:   der Diesel von ``wkg_bias=-0.20`` auf 0 bei +4 cm Körpergröße.
GOLDEN_LONG_RESULT: list[tuple[int, float]] = [
    (5, 140703.10),
    (3, 151607.86),
    (7, 153295.03),
    (4, 154153.10),
    (2, 154464.27),
    (8, 157480.29),
    (1, 163278.80),
    (6, 168693.81),
]

#: Wie oft welches Ereignis fällt. Diese Zeile ist der eigentliche
#: Gewinn des langen Laufs: Wer am Schlafmodell dreht, sieht hier sofort,
#: dass aus zwei Schlafstopps plötzlich keiner mehr wird – auch wenn die
#: Zielzeiten in der Toleranz bleiben.
#:
#: Beim Einbau der Ampeln hat diese Zeile genau das getan, wofür sie da
#: ist. Der erste Lauf zeigte 69 ``TRAFFIC_LIGHT`` **und 69 zusätzliche
#: ``STOP_END``**: Der Ampelhalt lief über dieselbe Freigabe wie jeder
#: andere Halt und erzeugte damit ein „weiter" ohne zugehöriges „Stopp".
#: Das hat ``test_service_stops_cost_time`` sofort gemeldet — die Datei
#: sichert zu, dass zu jedem STOP_END ein STOP_START gehört.
#:
#: Jetzt schaltet der Ampelhalt seine Freigabe stumm, und die Zeile
#: sagt genau das Richtige: **eine** neue Zahl, alle anderen unverändert.
#:
#: Und ein zweites Mal beim Fünfprozentraster: 336 → 160 ``SPLIT_PASSED``,
#: **jede andere Zahl unverändert**. Genau das erwartet man, wenn die
#: Zahl der Zeitmessungen sinkt und sonst nichts — Splits zeichnen auf,
#: sie greifen nicht ein. Die Zielzeiten unten sind denn auch bitgleich
#: geblieben.
GOLDEN_LONG_EVENTS: dict[str, int] = {'CONDITION_END': 29, 'CONDITION_START': 40, 'DECISION': 11, 'FINISH': 8, 'INCIDENT': 50, 'PLAN': 66, 'SLEEP': 2, 'SPLIT_PASSED': 160, 'START': 8, 'STOP_END': 138, 'STOP_START': 88, 'TRAFFIC_LIGHT': 69}

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


def test_the_team_list_does_not_move_the_riders():
    """Die Teamliste darf das Fahrerfeld nicht verschieben.

    Der Grund, warum die Zahlen oben einmal neu gesetzt werden mussten:
    Teams und Fahrer zogen aus demselben Zufallsgenerator. Ein Team mit
    drei Ziehungen weniger — feste Namen statt zufälliger Kombinationen,
    berechnete Farbe statt gewürfelter — verschob damit jede Ziehung
    dahinter, und derselbe Seed lieferte ein anderes Feld.

    Seitdem sind es zwei Ströme über ``spawn_key``. Dieser Test ist die
    Zusicherung, dass es dabei bleibt: Wer einen Teamnamen ändert, eine
    Farbe anders rechnet oder ein Team hinzufügt, darf kein einziges
    Fahrerattribut bewegen.
    """
    import ultrasim.core.names as names
    from ultrasim.core.rider import generate_pool

    _, vorher = generate_pool(40, n_teams=4, seed=31)
    original = names.TEAM_NAMES
    try:
        names.TEAM_NAMES = tuple(f"Umbenannt {i}" for i in range(len(original)))
        _, nachher = generate_pool(40, n_teams=4, seed=31)
    finally:
        names.TEAM_NAMES = original

    assert [r.to_dict() for r in vorher] == [r.to_dict() for r in nachher]
