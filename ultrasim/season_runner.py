"""Saisonbetrieb: Kalender rechnen, werten, weiterentwickeln.

Die Schichten des Projekts sind bisher: ``core`` rechnet und weiß nichts
von Dateien, ``data`` speichert und weiß nichts vom Rechnen, ``cli`` und
``web`` sind zwei Oberflächen darüber. Mit der Saison entsteht zum ersten
Mal ein Ablauf, der *beide* braucht — ein Kalenderrennen zu rechnen heißt
Feld laden, Restermüdung aus früheren Rennen holen, simulieren, ablegen
und den Kalender fortschreiben.

Dieser Ablauf gehört weder in ``core`` (das dürfte dann nicht mehr ohne
Datenverzeichnis laufen) noch in ``cli`` oder ``web`` (dann gäbe es ihn
zweimal). Deshalb liegt er hier: eine dünne Dienstschicht, die core und
data verbindet und von beiden Oberflächen benutzt wird.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from .core import season as sn
from .core.development import SeasonRecord, advance_season
from .core.engine import RaceConfig, simulate_race
from .core.rider import Rider, Team
from .data.store import RaceSummary, Store

#: Wie viele Kilojoule ein Fahrer mit ins nächste Rennen nimmt, wird über
#: alle vorherigen Rennen der Saison aufsummiert — jedes mit seinem
#: eigenen Abstand zum Renntag.
MAX_CARRY_LOOKBACK_DAYS = 120


def slugify(text: str, fallback: str = "rennen") -> str:
    """Aus einem Namen einen dateisystemtauglichen Schlüssel machen."""
    table = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e", "á": "a"}
    lowered = "".join(table.get(c, c) for c in text.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or fallback


# ----------------------------------------------------------------------
# Lesende Auswertung
# ----------------------------------------------------------------------
def race_summaries(store: Store, season: sn.Season) -> dict[str, RaceSummary]:
    """Ergebnisse aller gerechneten Termine, ohne Telemetrie.

    Ein Termin, dessen Rennen inzwischen gelöscht wurde, fällt still
    heraus statt die ganze Saisonseite mit einem Fehler zu quittieren.
    """
    out: dict[str, RaceSummary] = {}
    for calendar_race in season.sorted_races():
        if not calendar_race.race_id:
            continue
        try:
            out[calendar_race.id] = store.load_race_summary(calendar_race.race_id)
        except (FileNotFoundError, KeyError):
            continue
    return out


#: Rennarbeit je flachem Kilometer und je Höhenmeter, gemessen an
#: gerechneten Rennen.
#:
#: Vorher stand hier ein einziger Wert je „Äquivalentkilometer" (15,0
#: kJ), erhoben an drei Strecken mit höchstens 13,4 hm/km. Über die zehn
#: Strecken der Weltserie hält er nicht mehr: gemessen zwischen 15,6 und
#: 27,7 kJ je Äquivalentkilometer, also bis zu 85 % daneben.
#:
#: Zwei Terme statt einem — und der Höhenmeter-Term ist keine
#: Kurvenanpassung, sondern eine Wiedererkennung: Aus den Messwerten
#: kommen **0,76 kJ je Höhenmeter**, und die potenzielle Energie eines
#: 78-kg-Systems ist m·g/1000 = 0,765 kJ je Meter. Der Fit findet die
#: Physik, die dahintersteckt.
WORK_PER_KM_KJ = 15.1
WORK_PER_ASCENT_M_KJ = 0.76

#: Arbeitskapazität eines Fahrers mit Durchschnittswerten (Ausdauer und
#: Regeneration 50, 70 kg). Bezugsgröße für das Erholungsfenster im
#: Kalender — dort geht es um den Kalender, nicht um einen bestimmten
#: Fahrer.
NOMINAL_CAPACITY_KJ = 42_000.0


def estimated_work_kj(distance_km: float, ascent_m: float) -> float:
    """Was ein Rennen einen durchschnittlichen Fahrer an Arbeit kostet.

    Auf acht der zehn Weltserien-Strecken trifft das auf rund zehn
    Prozent. Die Ausnahme sind die Dolomiten-Vierpässe: gemessen 23,1
    MJ gegen 14,9 MJ geschätzt. Der Rest steckt in Mechaniken, die eine
    Formel aus Kilometern und Höhenmetern nicht sehen kann — die
    Trittfrequenz fällt auf den Steilstücken unter den günstigen
    Bereich, die Rampen über 12 % gehen anaerob, und ein Fünftel der
    Strecke liegt über 1500 m. Deshalb plant der Kalender mit Marge
    statt mit der nackten Schätzung.
    """
    return distance_km * WORK_PER_KM_KJ + ascent_m * WORK_PER_ASCENT_M_KJ


@dataclass
class PlanRow:
    """Ein Termin, wie ihn die Kalenderansicht braucht."""

    race: sn.CalendarRace
    route: dict[str, Any] | None
    #: Position im Jahr, 0…1 — für das Jahresband.
    position: float
    gap_days: int | None
    #: Wie lange ein durchschnittlicher Fahrer nach *diesem* Rennen
    #: braucht, bis er wieder auf 98 % Frische ist.
    recovery_days: float
    #: Wie viel Erholung der *vorherige* Termin verlangt hätte. Das ist
    #: die Zahl, gegen die sich die Pause messen lassen muss.
    rest_needed: float
    work_kj: float
    #: Stammt ``work_kj`` aus einem gerechneten Rennen oder aus der Schätzung?
    measured: bool

    @property
    def crowded(self) -> bool:
        """Startet dieses Rennen, bevor das vorherige verdaut ist?"""
        return self.gap_days is not None and self.gap_days < self.rest_needed


def calendar_plan(store: Store, season: sn.Season) -> list[PlanRow]:
    """Der Kalender als Planungsansicht: Termine, Pausen, Erholungsfenster.

    Die Tabelle beantwortet „was steht wann an", diese Ansicht die
    eigentliche Frage: **Ist der Kalender fahrbar?** Nach einem Ultra
    braucht ein Durchschnittsfahrer gut drei Wochen, bis die Frische
    wieder bei 98 % liegt; steht das nächste Rennen vorher, startet das
    ganze Feld angeschlagen. Das sieht man einer Datumsliste nicht an.

    Wo ein Rennen schon gerechnet ist, steht die *gemessene* Arbeit
    seiner Fahrer; sonst eine Schätzung aus Länge und Höhenmetern.
    """
    routes = {r["id"]: r for r in store.list_routes()}
    summaries = race_summaries(store, season)
    rows: list[PlanRow] = []
    previous: date | None = None

    for calendar_race in season.sorted_races():
        route = routes.get(calendar_race.route_id)
        summary = summaries.get(calendar_race.id)
        work = 0.0
        measured = False
        if summary is not None:
            done = sorted(e.work_kj for e in summary.entries if e.work_kj > 0.0)
            if done:
                work = done[len(done) // 2]
                measured = True
        if not measured and route is not None:
            work = estimated_work_kj(route["distance_km"], route["ascent_m"])

        day = calendar_race.day
        start = date(day.year, 1, 1)
        span = (date(day.year, 12, 31) - start).days or 1
        rows.append(
            PlanRow(
                race=calendar_race,
                route=route,
                position=min(max((day - start).days / span, 0.0), 1.0),
                gap_days=(day - previous).days if previous else None,
                recovery_days=sn.recovery_days(work, NOMINAL_CAPACITY_KJ),
                rest_needed=rows[-1].recovery_days if rows else 0.0,
                work_kj=work,
                measured=measured,
            )
        )
        previous = day
    return rows


def coefficients(store: Store, season: sn.Season) -> dict[str, float]:
    """Rennkoeffizient je Termin, aus der Strecke oder von Hand gesetzt."""
    cache: dict[str, float] = {}
    out: dict[str, float] = {}
    for calendar_race in season.races:
        if calendar_race.coefficient is not None:
            out[calendar_race.id] = float(calendar_race.coefficient)
            continue
        if calendar_race.route_id not in cache:
            try:
                route = store.load_route(calendar_race.route_id)
            except FileNotFoundError:
                cache[calendar_race.route_id] = 1.0
            else:
                cache[calendar_race.route_id] = sn.race_coefficient(
                    route.distance_km, route.ascent_m
                )
        out[calendar_race.id] = cache[calendar_race.route_id]
    return out


def standings(store: Store, season: sn.Season) -> list[sn.Standing]:
    """Gesamtrangliste der Saison."""
    summaries = race_summaries(store, season)
    riders: dict[int, Rider] = {}
    teams: dict[int, Team] = {}
    for summary in summaries.values():
        for rider in summary.riders:
            riders.setdefault(rider.id, rider)
        for team in summary.teams:
            teams.setdefault(team.id, team)
    return sn.build_standings(season, summaries, riders, teams, coefficients(store, season))


def season_records(store: Store, season: sn.Season) -> dict[int, SeasonRecord]:
    """Saisonbilanz je Fahrer — Grundlage der Fahrerentwicklung."""
    summaries = race_summaries(store, season)
    coeff = coefficients(store, season)
    routes: dict[str, float] = {}
    out: dict[int, SeasonRecord] = {}

    for calendar_race in season.sorted_races():
        summary = summaries.get(calendar_race.id)
        if summary is None:
            continue
        if calendar_race.route_id not in routes:
            try:
                routes[calendar_race.route_id] = store.load_route(
                    calendar_race.route_id
                ).distance_km
            except FileNotFoundError:
                routes[calendar_race.route_id] = 0.0
        distance_km = routes[calendar_race.route_id]

        for entry in summary.entries:
            record = out.setdefault(entry.rider_id, SeasonRecord())
            record.starts += 1
            record.points += sn.points_for_rank(
                entry.rank, tuple(season.points_head)
            ) * coeff.get(calendar_race.id, 1.0)
            if entry.rank == 1:
                record.wins += 1
            if entry.status in ("FIN", "OTL"):
                record.finishes += 1
                record.distance_km += distance_km
            elif entry.dnf_dist_m:
                record.distance_km += entry.dnf_dist_m / 1000.0
    return out


# ----------------------------------------------------------------------
# Restermüdung
# ----------------------------------------------------------------------
def carry_work_kj(
    store: Store, season: sn.Season, target: sn.CalendarRace, riders: list[Rider]
) -> dict[int, float]:
    """Was jeder Starter aus früheren Rennen der Saison mitschleppt.

    Aufsummiert über alle vorherigen Termine, jeder mit seinem eigenen
    Abstand zum Renntag und der Regeneration des Fahrers. Ein Fahrer, der
    zwei Ultras hintereinander gefahren ist, schleppt beide — abgeklungen
    nach ihrem jeweiligen Alter.
    """
    summaries = race_summaries(store, season)
    by_id = {r.id: r for r in riders}
    out: dict[int, float] = {}

    for calendar_race in season.sorted_races():
        if calendar_race.id == target.id or calendar_race.day >= target.day:
            continue
        summary = summaries.get(calendar_race.id)
        if summary is None:
            continue
        days = (target.day - calendar_race.day).days
        if days > MAX_CARRY_LOOKBACK_DAYS:
            continue
        for entry in summary.entries:
            rider = by_id.get(entry.rider_id)
            if rider is None or entry.work_kj <= 0.0:
                continue
            out[entry.rider_id] = out.get(entry.rider_id, 0.0) + sn.residual_work_kj(
                entry.work_kj, days, rider.attr("regeneration")
            )
    return out


# ----------------------------------------------------------------------
# Rechnen
# ----------------------------------------------------------------------
@dataclass
class RunOutcome:
    race_id: str
    winner_time_s: float | None
    n_entries: int
    compute_seconds: float


def race_id_for(season: sn.Season, calendar_race: sn.CalendarRace) -> str:
    return f"{season.id}-{calendar_race.id}"


def season_of_race(store: Store, race_id: str) -> tuple[sn.Season, sn.CalendarRace] | None:
    """Zu welchem Kalendertermin gehört dieses Rennen?

    Gesucht wird über ``race_id``, nicht über den Namen: Ein Rennen kann
    umbenannt werden, der Verweis im Kalender bleibt. Ein Rennen, das
    außerhalb einer Saison gerechnet wurde, hat keinen Termin — dann
    ``None``, und die Ergebnisseite zeigt eben keine Punkte.
    """
    for entry in store.list_seasons():
        try:
            season = store.load_season(entry["id"])
        except (FileNotFoundError, KeyError, ValueError):
            continue
        for calendar_race in season.races:
            if calendar_race.race_id == race_id:
                return season, calendar_race
    return None


def run_calendar_race(
    store: Store,
    season: sn.Season,
    race_key: str,
    progress: Any = None,
    save_season: bool = True,
) -> RunOutcome:
    """Einen Kalendertermin rechnen, ablegen und den Kalender fortschreiben.

    Die Saison wird erst *nach* dem erfolgreichen Speichern des Rennens
    fortgeschrieben. Bricht die Rechnung ab, steht im Kalender weiterhin
    „geplant" und kein Verweis auf ein halbes Rennen.
    """
    calendar_race = season.race(race_key)
    if calendar_race is None:
        raise KeyError(f"Kein Termin '{race_key}' in Saison '{season.id}'")

    route = store.load_route(calendar_race.route_id)
    teams, pool = store.load_pool()
    riders = pool[: max(calendar_race.n_riders, 2)]

    config = RaceConfig(
        seed=calendar_race.seed,
        weather_preset=calendar_race.weather_preset,
        race_date=calendar_race.day,
        name=calendar_race.name,
        carry_work_kj=carry_work_kj(store, season, calendar_race, riders),
    )
    result = simulate_race(route, riders, teams, config, progress=progress)

    race_id = race_id_for(season, calendar_race)
    store.save_race(race_id, calendar_race.route_id, result, route=route)
    calendar_race.race_id = race_id
    if save_season:
        store.save_season(season)

    return RunOutcome(
        race_id=race_id,
        winner_time_s=result.winner_time_s,
        n_entries=len(result.entries),
        compute_seconds=result.compute_seconds,
    )


def pending_races(season: sn.Season) -> list[sn.CalendarRace]:
    """Noch nicht gerechnete Termine, in Terminreihenfolge.

    Die Reihenfolge ist nicht kosmetisch: Die Restermüdung eines Rennens
    steht erst fest, wenn das vorherige gerechnet ist.
    """
    return [r for r in season.sorted_races() if not r.computed]


# ----------------------------------------------------------------------
# Saisonwechsel
# ----------------------------------------------------------------------
def close_season(
    store: Store, season: sn.Season, seed: int, replace_retired: bool = True
) -> dict[str, Any]:
    """Saison abschließen: Fahrer altern lassen, Pool fortschreiben.

    Der Pool wird direkt überschrieben — es gibt genau einen. Wer die
    alte Fassung behalten will, muss sie vorher sichern; das ist eine
    bewusste Vereinfachung, solange es keine Mehrfachwelten gibt.
    """
    from .core.rider import generate_rider

    teams, riders = store.load_pool()
    records = season_records(store, season)
    active, retired, log = advance_season(riders, records, seed=seed)

    newcomers: list[Rider] = []
    if replace_retired and retired:
        import numpy as np

        rng = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(99, 1)))
        next_id = max((r.id for r in riders), default=0) + 1
        for gone in retired:
            newcomer = generate_rider(
                rng,
                next_id,
                gone.team_id,
                archetype="rohdiamant" if rng.random() < 0.45 else None,
                potential_mean=46.0,
            )
            # Nachwuchs ist jung: Der Generator zieht sonst auch 35-Jährige.
            newcomer.age = int(rng.integers(19, 24))
            newcomers.append(newcomer)
            next_id += 1

    store.save_pool(teams, active + newcomers)
    return {
        "season_id": season.id,
        "active": len(active),
        "retired": [{"id": r.id, "name": r.name, "age": r.age} for r in retired],
        "newcomers": [{"id": r.id, "name": r.name, "age": r.age} for r in newcomers],
        "log": log,
    }


# ----------------------------------------------------------------------
# Kalender erzeugen
# ----------------------------------------------------------------------
#: Die **Ultra-Weltserie**: zehn Rennen von 400 bis 2500 km, in der
#: Reihenfolge, in der sie gefahren werden.
#:
#: Die Reihenfolge ist steigende Distanz, und das ist eine Entscheidung.
#: Sie könnte auch gemischt sein — dann wären die Termine austauschbar
#: und die Saison eine Liste. So ist sie ein Verlauf: Der Auftakt ist
#: ein Zeitfahren, das an einem Tag entschieden ist, das Finale hat 2469
#: Kilometer und vier Nächte. Wer im März führt, hat noch nichts
#: gewonnen; wer im Oktober führt, ist Ultrameister.
#:
#: Zehn verschiedene Anforderungen, nicht zehn Längen: flaches
#: Zeitfahren, Rampenrennen, Kehrenpässe, Schotter, Pflasterhügel,
#: Nachtfahrt, Bergultra, Monotonie auf der Hochebene, Alpenquerung,
#: und am Ende alles zusammen.
WELTSERIE: tuple[tuple[str, str], ...] = (
    ("atlantik-zeitfahren", "Atlantik-Zeitfahren"),
    ("ardennen-wellenritt", "Ardennen-Wellenritt"),
    ("dolomiten-vierpaesse", "Dolomiten-Vierpässe"),
    ("karpaten-schotterrunde", "Karpaten-Schotterrunde"),
    ("toskana-huegelmarathon", "Toskana-Hügelmarathon"),
    ("ostsee-nachtfahrt", "Ostsee-Nachtfahrt"),
    ("pyrenaeen-traverse", "Pyrenäen-Traverse"),
    ("steppenroute-anatolien", "Steppenroute Anatolien"),
    ("alpenueberquerung", "Alpenüberquerung"),
    ("transkontinental", "Transkontinental"),
)

#: Erster Termin der Weltserie. Sie braucht fast das ganze Jahr: Die
#: Erholungsfenster der zehn Rennen summieren sich mit Marge auf rund
#: 290 Tage, und das ist keine Vorgabe, sondern das Ergebnis — 2469
#: Kilometer kosten einen Durchschnittsfahrer gut fünf Wochen. Ab dem
#: 1. Februar endet die Serie Anfang November und lässt acht Wochen
#: Winter; mehr als zehn Rennen dieser Größe passen nicht ins Jahr.
WELTSERIE_START = (2, 1)

#: Puffer über das Erholungsfenster hinaus, in Tagen. Ohne ihn läge
#: jeder Termin exakt auf der 98-%-Grenze und der Kalender wäre
#: rechnerisch fahrbar, praktisch aber auf Kante genäht.
CALENDAR_BUFFER_DAYS = 2

#: Sicherheitsmarge auf das geschätzte Erholungsfenster.
#:
#: Sie steht hier, weil die Schätzung nachweislich zu niedrig liegen
#: kann: Auf den Dolomiten-Vierpässen sind 23,1 MJ gemessen worden, wo
#: 14,9 geschätzt waren. Ohne Marge geplant, war genau der Termin
#: danach als „zu eng" markiert — und zwar zu Recht, denn die Messung
#: hatte recht und der Plan nicht. Fünfzehn Prozent decken die
#: gemessene Abweichung auf allen zehn Strecken ab.
CALENDAR_MARGIN = 1.15


def _gap_after(route: dict[str, Any]) -> int:
    """Wie viele Tage nach diesem Rennen der nächste Termin liegen darf.

    Nicht aus der Distanzklasse, sondern aus dem Erholungsfenster: Der
    Eimer „ultra" reicht von 1000 bis 2500 km, und das ist der
    Unterschied zwischen drei und viereinhalb Wochen Pause.
    """
    work = estimated_work_kj(route["distance_km"], route["ascent_m"])
    needed = sn.recovery_days(work, NOMINAL_CAPACITY_KJ) * CALENDAR_MARGIN
    return int(math.ceil(needed)) + CALENDAR_BUFFER_DAYS


def weltserie_calendar(
    store: Store, year: int, n_riders: int = 300, first_day: date | None = None
) -> list[sn.CalendarRace]:
    """Der Standardkalender: zehn Rennen von 400 bis 2500 km.

    Fehlt eine der zehn Strecken, fällt sie still heraus statt den
    ganzen Kalender zu verweigern — wer eine gelöscht hat, bekommt neun
    Termine und sieht selbst, welcher fehlt.
    """
    routes = {r["id"]: r for r in store.list_routes()}
    day = first_day or date(year, *WELTSERIE_START)
    out: list[sn.CalendarRace] = []
    for i, (route_id, name) in enumerate(WELTSERIE):
        route = routes.get(route_id)
        if route is None:
            continue
        out.append(
            sn.CalendarRace(
                id=f"{len(out) + 1:02d}-{slugify(name)}",
                name=name,
                route_id=route_id,
                day=day,
                n_riders=n_riders,
                seed=2000 + i,
            )
        )
        day = _plus_days(day, _gap_after(route))
    return out


def suggest_calendar(
    store: Store, year: int, n_races: int = 10, first_day: date | None = None
) -> list[sn.CalendarRace]:
    """Vorschlag für einen Kalender aus den vorhandenen Strecken.

    Gedacht als Startpunkt für den Editor, nicht als letztes Wort: Die
    Termine sind gleichmäßig über die Saison verteilt, und lange Rennen
    bekommen mehr Luft danach — genau das, was der Nutzer danach von Hand
    verschiebt.
    """
    routes = store.list_routes()
    if not routes:
        return []
    start = first_day or date(year, 4, 1)
    out: list[sn.CalendarRace] = []
    day = start
    for i in range(n_races):
        route = routes[i % len(routes)]
        key = f"{i + 1:02d}-{slugify(route['name'])}"
        out.append(
            sn.CalendarRace(
                id=key,
                name=route["name"],
                route_id=route["id"],
                day=day,
                n_riders=300,
                seed=1000 + i,
            )
        )
        # Nach einem langen Rennen mehr Abstand: sonst ist der Kalender
        # von vornherein unfahrbar und jeder Vorschlag muss korrigiert
        # werden, bevor er benutzbar ist. Das Erholungsfenster ist dafür
        # die richtige Größe — die Distanzklasse ist zu grob.
        day = _plus_days(day, _gap_after(route))
    return out


def _plus_days(day: date, days: int) -> date:
    from datetime import timedelta

    return day + timedelta(days=days)


__all__ = [
    "RunOutcome",
    "carry_work_kj",
    "close_season",
    "coefficients",
    "pending_races",
    "race_id_for",
    "race_summaries",
    "run_calendar_race",
    "season_of_race",
    "season_records",
    "slugify",
    "standings",
    "suggest_calendar",
    "weltserie_calendar",
]
