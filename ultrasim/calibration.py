"""Kalibrierungsmessungen für das Balancing (Abschnitt 13, Meilenstein M8).

Bis hierher gab es zwei Anker: das Dauerband je Distanzklasse aus
Abschnitt 2 und den DNF-Korridor aus Abschnitt 6.5. Beide beantworten
dieselbe Frage — *ist das Rennen insgesamt plausibel?* — und keine der
beiden beantwortet die zwei Fragen, die beim Balancing eigentlich
anfallen:

1. **Was bewirkt ein einzelnes Attribut?** Die Oberfläche behauptet mit
   ``ACTIVE_ATTRIBUTES``, welche Attribute in die Simulation eingreifen.
   Ein Test hält diese Liste gegen den Code — aber „wird gelesen" und
   „wirkt spürbar" sind zwei verschiedene Dinge. Ein Attribut mit
   falschem Vorzeichen wird auch gelesen.
2. **Sind die Archetypen mehr als andere Zahlen im Fahrerdetail?**
   Gewinnt der Kletterer die Bergstrecke und der Zeitfahrer die flache,
   oder gewinnt überall derselbe Typ?

Beides misst dieses Modul. Es gehört bewusst nicht in ``core``: Dort
liegt die Simulation, hier liegt die Messung *an* der Simulation.

Der Trick bei der Attributmessung
---------------------------------
Naheliegend wäre, je Attribut zwei komplette Rennen zu rechnen. Das sind
bei 25 Attributen, zwei Richtungen und drei Strecken 150 Läufe — auf der
Ultrastrecke eine knappe Stunde, und jeder Lauf trägt die Streuung von
Wetter und Zwischenfällen mit sich.

Stattdessen laufen alle Varianten **in einem einzigen Rennen**. Die
Zufallsströme hängen an ``(Seed, Fahrer-ID, Zweck)`` und nicht an der
Position in der Startliste — zwei Kopien desselben Fahrers mit derselben
ID bekommen also denselben Wetterverlauf, dieselben Pannenkandidaten und
dieselbe Tagesform. Ein Rennen mit 300 Startern kostet kaum mehr als
eines mit 30, weil die Simulation über das Feld vektorisiert ist. Damit
wird die Messung nicht nur schnell, sondern auch **paarweise**: Was
zwischen zwei Kopien an Zeit übrig bleibt, ist das Attribut und sonst
nichts.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

import numpy as np

from .core.engine import RaceConfig, simulate_race
from .core.rider import ARCHETYPES, ATTRIBUTES, Rider, Team, generate_rider, generate_team
from .geo.route import Route

#: Ziel-DNF-Korridor je Distanzklasse (Abschnitt 6.5).
DNF_TARGET: dict[str, tuple[float, float]] = {
    "kurz": (0.01, 0.02),
    "mittel": (0.04, 0.07),
    "ultra": (0.08, 0.12),
}

#: Dauerband je Distanzklasse aus Abschnitt 2. Das ist der einzige
#: Kalibrierungsanker, den das Dokument selbst liefert.
DURATION_TARGET_H: dict[str, tuple[float, float]] = {
    "kurz": (5.0, 15.0),
    "mittel": (15.0, 50.0),
    "ultra": (50.0, 110.0),
}

#: Attributschritt der Sensitivitätsmessung. Die Archetypen streuen mit
#: rund 11 Punkten, zehn Punkte sind also ungefähr eine
#: Standardabweichung — ein Unterschied, den es im Feld wirklich gibt.
DEFAULT_DELTA = 10.0

#: Unterhalb dieser Wirkung gilt ein Attribut als nicht messbar. Die
#: Paarung ist bis auf die Annahme von Zwischenfällen deterministisch;
#: was übrig bleibt, sind einzelne Pannen, die in der einen Variante
#: angenommen werden und in der anderen nicht. Auf einem Rennen von
#: mehreren Stunden ist das die Größenordnung weniger Sekunden.
NOISE_FLOOR_S = 3.0

#: Wie viele Standardfehler eine Wirkung groß sein muss, um zu zählen.
#:
#: Drei statt der üblichen zwei, und zwar wegen der Menge: Der Bericht
#: prüft 25 Attribute auf drei Strecken, also 75 Hypothesen. Bei zwei
#: Standardfehlern sind darunter rein rechnerisch drei Fehltreffer zu
#: erwarten — und ein Fehltreffer in dieser Tabelle ist teuer, weil
#: jemand anfängt, ein Attribut zu „reparieren", das nie kaputt war.
SIGMA = 3.0

#: Attribute, deren Wirkung dieser Aufbau **grundsätzlich** nicht messen
#: kann. ``konstanz`` steuert allein die Streuung der Tagesform, und die
#: Tagesform ist ``1 + sd·z`` mit einem z, das beide Kopien eines Fahrers
#: aus demselben Strom ziehen. Die Differenz zwischen starker und
#: schwacher Variante ist damit proportional zu −z: Bei einem Fahrer mit
#: gutem Tag *schadet* Konstanz, bei einem mit schlechtem hilft sie, und
#: im Mittel steht dort der Stichprobenmittelwert der Zufallszahlen und
#: nicht die Wirkung des Attributs. Wer die messen will, braucht ein
#: anderes Werkzeug — den Vergleich zweier Verteilungen über viele
#: Rennen statt einer Paardifferenz.
VARIANCE_ATTRIBUTES = frozenset({"konstanz"})


# ----------------------------------------------------------------------
# Streckenübersicht: Dauerband und Ausfallquote
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class RouteSummary:
    """Kennzahlen einer Strecke über mehrere Rennen."""

    name: str
    distance_km: float
    ascent_m: float
    distance_class: str
    runs: int
    starters: int
    winner_h: float
    median_h: float
    last_h: float
    winner_kmh: float
    field_kmh: float
    inside_band_pct: float
    dnf_pct: float
    otl_pct: float
    rank_corr: float

    @property
    def band(self) -> tuple[float, float]:
        return DURATION_TARGET_H.get(self.distance_class, (0.0, math.inf))

    @property
    def dnf_target(self) -> tuple[float, float]:
        return DNF_TARGET.get(self.distance_class, (0.05, 0.10))

    @property
    def dnf_in_target(self) -> bool:
        lo, hi = self.dnf_target
        return lo <= (self.dnf_pct + self.otl_pct) / 100.0 <= hi


def route_summary(
    route: Route,
    riders: Sequence[Rider],
    teams: Sequence[Team],
    seeds: Sequence[int],
) -> RouteSummary:
    """Rechnet je Seed ein Rennen und fasst die Verteilungen zusammen."""
    by_id = {r.id: r for r in riders}
    winner: list[float] = []
    times: list[float] = []
    corr: list[float] = []
    starters = dnf = otl = 0

    for seed in seeds:
        result = simulate_race(route, riders, teams, RaceConfig(seed=seed))
        starters += len(result.entries)
        dnf += sum(1 for e in result.entries if e.status == "DNF")
        otl += sum(1 for e in result.entries if e.status == "OTL")
        finished = [e for e in result.entries if e.finish_time_s is not None]
        if not finished:
            continue
        t = np.array([e.finish_time_s for e in finished])
        winner.append(float(t.min()))
        times.extend(t.tolist())
        pot = np.array([by_id[e.rider_id].potential for e in finished])
        if pot.size > 2:
            corr.append(float(np.corrcoef(_ranks(-pot), _ranks(t))[0, 1]))

    field_h = np.array(times) / 3600.0
    lo_h, hi_h = DURATION_TARGET_H.get(route.distance_class, (0.0, math.inf))
    return RouteSummary(
        name=route.name,
        distance_km=route.distance_km,
        ascent_m=route.ascent_m,
        distance_class=route.distance_class,
        runs=len(seeds),
        starters=starters,
        winner_h=float(np.mean(winner)) / 3600.0 if winner else math.nan,
        median_h=float(np.median(field_h)) if field_h.size else math.nan,
        last_h=float(field_h.max()) if field_h.size else math.nan,
        winner_kmh=route.distance_km / (float(np.mean(winner)) / 3600.0) if winner else math.nan,
        field_kmh=route.distance_km / float(np.mean(field_h)) if field_h.size else math.nan,
        inside_band_pct=float(np.mean((field_h >= lo_h) & (field_h <= hi_h))) * 100.0
        if field_h.size
        else math.nan,
        dnf_pct=dnf / max(starters, 1) * 100.0,
        otl_pct=otl / max(starters, 1) * 100.0,
        rank_corr=float(np.mean(corr)) if corr else math.nan,
    )


# ----------------------------------------------------------------------
# Attribut-Sensitivität
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class AttributeEffect:
    """Wirkung eines Attributs auf einer Strecke."""

    attr: str
    #: Zeitgewinn in Sekunden je +10 Attributpunkte, gemittelt über alle
    #: Paare. Positiv = schneller.
    seconds: float
    #: Derselbe Wert als Median. Der Vergleich mit dem Mittel sagt, *wie*
    #: ein Attribut wirkt: Wer die Rollreibung senkt, wirkt bei jedem
    #: Fahrer ein bisschen — Mittel und Median liegen zusammen. Wer die
    #: Wahrscheinlichkeit einer Panne senkt, wirkt bei den meisten gar
    #: nicht und bei wenigen mit 20 Minuten; dann ist der Median null und
    #: das Mittel nicht.
    seconds_median: float
    #: Derselbe Wert in Prozent der Siegerzeit.
    percent: float
    #: Standardfehler des Mittels. Ohne ihn steht in der Tabelle irgendwann
    #: eine Zahl, die nur eine einzelne Panne in der einen Variante ist.
    stderr: float
    #: Wie viele Fahrerpaare in die Messung eingegangen sind.
    pairs: int
    #: Ausfälle in der starken minus Ausfälle in der schwachen Variante.
    #: Negativ heißt: Das Attribut verhindert Ausfälle.
    dnf_delta: int

    @property
    def measurable(self) -> bool:
        """Hebt sich die Wirkung vom Rauschen ab?

        Drei Hürden: Das Attribut muss von diesem Aufbau überhaupt
        messbar sein, die Wirkung muss groß genug sein, um zu zählen,
        und sie muss ein Vielfaches ihres eigenen Standardfehlers
        betragen. Die letzte ist die wichtigste — ohne sie liest man aus
        20 Fahrern, von denen einer eine Panne hatte, eine
        Attributwirkung von sieben Minuten heraus.
        """
        if self.attr in VARIANCE_ATTRIBUTES:
            return False
        return abs(self.seconds) >= NOISE_FLOOR_S and abs(self.seconds) >= SIGMA * self.stderr

    @property
    def rare_event_driven(self) -> bool:
        """Wirkt das Attribut über seltene Ereignisse statt stetig?"""
        return abs(self.seconds) > 2.0 * abs(self.seconds_median) + NOISE_FLOOR_S


def sensitivity_config(seed: int, preset: str | None = None) -> RaceConfig:
    """Rennkonfiguration der Sensitivitätsmessung.

    Zwei Abweichungen vom normalen Rennen, beide zugunsten der Paarung:
    ``start_order="list"`` hält die Startliste in der übergebenen
    Reihenfolge (sonst sortiert sie nach Potenzial, und die Zuordnung
    Variante → Ergebniszeile wäre nicht mehr trivial), und ein
    Startintervall von null lässt alle gleichzeitig los. Letzteres ist
    für das Ergebnis eigentlich egal — die Zeitschicht des Wetters hängt
    an der Eigenzeit des Fahrers, nicht an der Uhr —, aber es nimmt die
    Frage von vornherein aus der Messung heraus.

    ``preset`` erzwingt ein Wetter. Ohne das bliebe die halbe
    Wetterabteilung stumm: Hitzetoleranz ist an einem 16-Grad-Tag
    nichts wert, Nässeresistenz bei trockener Straße auch nicht — und
    „nicht messbar" hieße dann fälschlich „wirkungslos".
    """
    return RaceConfig(
        seed=seed, start_order="list", start_interval_s=0, weather_preset=preset
    )


def sensitivity_field(
    base: Sequence[Rider],
    attributes: Iterable[str] | None = None,
    delta: float = DEFAULT_DELTA,
) -> tuple[list[Rider], list[str]]:
    """Baut das Variantenfeld: je Attribut eine starke und eine schwache Kopie.

    Alle Kopien behalten die ID ihres Grundfahrers — daran hängen die
    Zufallsströme, und genau deshalb ist der Vergleich paarweise.
    """
    attrs = list(attributes if attributes is not None else ATTRIBUTES)
    field: list[Rider] = [replace(r, attributes=dict(r.attributes)) for r in base]
    for attr in attrs:
        for sign in (+1.0, -1.0):
            for rider in base:
                value = float(np.clip(rider.attr(attr) + sign * delta, 1.0, 99.0))
                field.append(replace(rider, attributes={**rider.attributes, attr: value}))
    return field, attrs


def attribute_sensitivity(
    route: Route,
    base: Sequence[Rider],
    teams: Sequence[Team],
    seeds: Sequence[int] = (4200,),
    attributes: Iterable[str] | None = None,
    delta: float = DEFAULT_DELTA,
    preset: str | None = None,
) -> list[AttributeEffect]:
    """Misst je Attribut den Zeitgewinn von +10 Punkten.

    Je Seed genau *ein* Rennen mit dem gesamten Variantenfeld. Mehrere
    Seeds sind trotz der Paarung nötig, weil Attribute, die auf die
    Ereignisrate wirken, den Ereignisplan neu ziehen: Wer seltener eine
    Panne bekommt, bekommt sie nicht nur seltener, sondern auch an
    anderen Stellen. Über wenige Fahrer gemittelt ist das Rauschen; über
    viele wird daraus die Rate.
    """
    field, attrs = sensitivity_field(base, attributes, delta)
    n = len(base)
    gains: list[list[float]] = [[] for _ in attrs]
    dnf_delta = [0 for _ in attrs]
    refs: list[float] = []

    for seed in seeds:
        result = simulate_race(route, field, teams, sensitivity_config(seed, preset))
        entries = sorted(result.entries, key=lambda e: e.entry_id)
        if len(entries) != len(field):  # pragma: no cover - Zusicherung der Engine
            raise RuntimeError("Startliste und Ergebnis passen nicht zusammen")
        baseline = [e.finish_time_s for e in entries[:n] if e.finish_time_s is not None]
        if baseline:
            refs.append(min(baseline))

        for a, attr in enumerate(attrs):
            strong = entries[n + 2 * a * n : n + (2 * a + 1) * n]
            weak = entries[n + (2 * a + 1) * n : n + (2 * a + 2) * n]
            dnf_delta[a] += sum(1 for e in strong if e.status != "FIN")
            dnf_delta[a] -= sum(1 for e in weak if e.status != "FIN")
            for k in range(n):
                t_strong, t_weak = strong[k].finish_time_s, weak[k].finish_time_s
                if t_strong is None or t_weak is None:
                    continue
                # Der tatsächliche Abstand kann kleiner als 2·delta sein:
                # Wer schon bei 96 liegt, kann nicht um zehn Punkte
                # besser werden. Deshalb wird auf den wirklich
                # gefahrenen Abstand normiert statt auf den gewünschten.
                span = float(
                    field[n + 2 * a * n + k].attr(attr) - field[n + (2 * a + 1) * n + k].attr(attr)
                )
                if span < 1.0:
                    continue
                gains[a].append((t_weak - t_strong) / span * DEFAULT_DELTA)

    ref = float(np.mean(refs)) if refs else math.nan
    effects: list[AttributeEffect] = []
    for a, attr in enumerate(attrs):
        g = np.array(gains[a], dtype=np.float64)
        mean = float(g.mean()) if g.size else 0.0
        effects.append(
            AttributeEffect(
                attr=attr,
                seconds=mean,
                seconds_median=float(np.median(g)) if g.size else 0.0,
                percent=mean / ref * 100.0 if g.size and ref and not math.isnan(ref) else 0.0,
                stderr=float(g.std(ddof=1) / math.sqrt(g.size)) if g.size > 1 else math.inf,
                pairs=int(g.size),
                dnf_delta=dnf_delta[a],
            )
        )
    effects.sort(key=lambda e: -abs(e.seconds))
    return effects


# ----------------------------------------------------------------------
# Archetypen
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class ArchetypeStat:
    key: str
    label: str
    starts: int
    wins: int
    podiums: int
    mean_rank: float
    mean_potential: float
    dnf_pct: float
    #: Körperbau bei gleichem Budget. Ohne diese drei Zahlen liest sich
    #: die Platzierungstabelle wie eine Aussage über Attribute, obwohl
    #: der Archetyp auch Größe, Gewicht und damit W/kg mitbringt.
    mean_wkg: float = 0.0
    mean_ftp_w: float = 0.0
    mean_area_m2: float = 0.0


def balanced_field(
    n_per_archetype: int = 4,
    seed: int = 77,
    n_teams: int = 4,
) -> tuple[list[Team], list[Rider]]:
    """Feld mit gleich vielen Fahrern je Archetyp und **gleichem Potenzial**.

    Die Streuung des Potenzial-Budgets steht hier auf null. Sonst misst
    man am Ende, welcher Archetyp die stärkeren Fahrer bekommen hat, und
    nicht, welcher Archetyp zur Strecke passt. Was bleibt, ist die
    Form des Fahrers: dieselbe Summe, anders verteilt — dazu der
    Körperbau-Vorteil, den ein Archetyp mitbringt (der Kletterer ist
    kleiner und leichter, und das *soll* er sein).
    """
    rng = np.random.default_rng(seed)
    used: set[str] = set()
    teams = [generate_team(rng, i, used) for i in range(n_teams)]
    riders: list[Rider] = []
    for key in ARCHETYPES:
        for _ in range(n_per_archetype):
            rider = generate_rider(
                rng,
                len(riders),
                teams[len(riders) % n_teams].id,
                archetype=key,
                potential_sd=0.0,
            )
            riders.append(rider)
    return teams, riders


def archetype_stats(
    route: Route,
    riders: Sequence[Rider],
    teams: Sequence[Team],
    seeds: Sequence[int],
) -> list[ArchetypeStat]:
    """Zählt Siege, Podien und mittlere Platzierung je Archetyp."""
    by_id = {r.id: r for r in riders}
    starts: dict[str, int] = {k: 0 for k in ARCHETYPES}
    wins = dict(starts)
    podiums = dict(starts)
    dnf = dict(starts)
    ranks: dict[str, list[float]] = {k: [] for k in ARCHETYPES}

    for seed in seeds:
        result = simulate_race(route, riders, teams, RaceConfig(seed=seed))
        order = sorted(
            (e for e in result.entries if e.finish_time_s is not None),
            key=lambda e: e.finish_time_s,
        )
        for entry in result.entries:
            key = by_id[entry.rider_id].archetype
            starts[key] += 1
            if entry.status != "FIN":
                dnf[key] += 1
        for pos, entry in enumerate(order, start=1):
            key = by_id[entry.rider_id].archetype
            ranks[key].append(float(pos))
            if pos == 1:
                wins[key] += 1
            if pos <= 3:
                podiums[key] += 1

    out: list[ArchetypeStat] = []
    for key in ARCHETYPES:
        group = [r for r in riders if r.archetype == key]
        out.append(
            ArchetypeStat(
                key=key,
                label=ARCHETYPES[key].label,
                starts=starts[key],
                wins=wins[key],
                podiums=podiums[key],
                mean_rank=float(np.mean(ranks[key])) if ranks[key] else math.nan,
                mean_potential=float(np.mean([r.potential for r in group] or [math.nan])),
                dnf_pct=dnf[key] / max(starts[key], 1) * 100.0,
                mean_wkg=float(np.mean([r.wkg for r in group] or [math.nan])),
                mean_ftp_w=float(np.mean([r.ftp_w for r in group] or [math.nan])),
                mean_area_m2=float(np.mean([r.frontal_area_m2 for r in group] or [math.nan])),
            )
        )
    return out


# ----------------------------------------------------------------------
def _ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    out = np.empty(values.size, dtype=np.float64)
    out[order] = np.arange(values.size, dtype=np.float64)
    return out


#: Attribute, die erst bei bestimmtem Wetter etwas tun, und die Presets,
#: unter denen der Bericht sie misst.
WEATHER_ATTRIBUTES = (
    "hitzetoleranz",
    "kaeltetoleranz",
    "naesseresistenz",
    "seitenwindfestigkeit",
    "abfahrtstechnik",
    "risikobereitschaft",
)
WEATHER_PRESETS = ("hitze", "kalt", "regen", "sturm")


__all__ = [
    "DEFAULT_DELTA",
    "DNF_TARGET",
    "DURATION_TARGET_H",
    "NOISE_FLOOR_S",
    "SIGMA",
    "VARIANCE_ATTRIBUTES",
    "WEATHER_ATTRIBUTES",
    "WEATHER_PRESETS",
    "ArchetypeStat",
    "AttributeEffect",
    "RouteSummary",
    "archetype_stats",
    "attribute_sensitivity",
    "balanced_field",
    "route_summary",
    "sensitivity_config",
    "sensitivity_field",
]
