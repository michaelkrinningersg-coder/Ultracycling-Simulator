"""Zwischenfälle und Aufgabe (Game-Design-Dokument, Abschnitt 6.5).

Der Ereigniskatalog aus Abschnitt 6.5 besteht aus seltenen Ereignissen
mit einer Rate je Kilometer, die von der Strecke, vom Wetter, von der
Tageszeit und von Fahrerattributen abhängt. Die Frage ist, *wie* man so
etwas würfelt.

Warum nicht pro Tick gewürfelt wird
-----------------------------------
Der naheliegende Weg — jeden Tick für jeden Fahrer eine Münze werfen —
hat drei Nachteile: Er kostet 250 Zufallszahlen je Sekunde Rennzeit, er
hängt an der Schrittweite (halbe Ticks, halbe Wahrscheinlichkeit, sonst
verschiebt sich die Rate), und er verschiebt sämtliche späteren
Ziehungen, sobald irgendwo ein Tick mehr oder weniger gerechnet wird.

Stattdessen wird der **Poisson-Prozess entlang der Strecke** direkt
gezogen: Vor dem Start steht für jeden Fahrer und jede Ereignisart fest,
bei welchen Kilometermarken ein *Kandidat* liegt. Im Rennen ist das dann
nur noch ein Distanzvergleich — dieselbe Bauform wie bei der
Fehlplanung.

Thinning: wie die Live-Faktoren trotzdem hineinkommen
-----------------------------------------------------
Nässe, Dunkelheit und Schlafdruck kennt man beim Planen noch nicht — sie
hängen davon ab, *wann* ein Fahrer an einer Stelle ankommt. Deshalb wird
der Kandidatenprozess mit dem größtmöglichen Faktor (``headroom``)
gezogen und beim Erreichen mit ``p = aktueller Faktor / headroom``
angenommen. Das ist die klassische Verdünnung eines Poisson-Prozesses
und liefert exakt die gewünschte inhomogene Rate — bei genau einer
Zufallszahl je Kandidat.

Was von der Strecke abhängt, steckt dagegen schon im Kandidatenprozess:
Schotter erhöht die Pannenrate ortsfest, also wird über ein kumuliertes
Risiko entlang der Strecke gezogen statt über die reine Distanz.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..geo.route import Route

# ----------------------------------------------------------------------
# Katalog
# ----------------------------------------------------------------------
PANNE = "panne"
DEFEKT = "defekt"
LICHT = "licht"
VERFAHREN = "verfahren"
STURZ = "sturz"
MAGEN = "magen"
HITZEEINBRUCH = "hitzeeinbruch"
SPERRUNG = "sperrung"


@dataclass(frozen=True)
class IncidentSpec:
    """Ein Ereignistyp mit seiner Basisrate.

    ``km_per_event`` ist die Strecke, nach der ein Fahrer mit
    Durchschnittsattributen unter Referenzbedingungen im Mittel einmal
    betroffen ist — genau die Zahlen aus der Tabelle in Abschnitt 6.5.

    ``headroom`` ist die Obergrenze aller Live-Faktoren zusammen. Sie
    darf großzügig sein (das kostet nur ein paar verworfene Kandidaten),
    aber niemals zu klein: Sonst wird die Annahmewahrscheinlichkeit auf
    1,0 gedeckelt und die Rate stimmt nicht mehr.

    ``rough_factor`` wirkt ortsfest auf Schotter und Kopfsteinpflaster
    und geht deshalb schon in den Kandidatenprozess ein.
    """

    typ: str
    label: str
    km_per_event: float
    headroom: float = 1.0
    rough_factor: float = 1.0


CATALOG: dict[str, IncidentSpec] = {
    # 1 pro ~450 km, ×2,5 Schotter, ×1,6 Nässe; Materialpflege ±35 %.
    PANNE: IncidentSpec(PANNE, "Reifenpanne", 450.0, headroom=1.6 * 1.35, rough_factor=2.5),
    # 1 pro ~1500 km.
    DEFEKT: IncidentSpec(DEFEKT, "Mechanischer Defekt", 1500.0, headroom=1.4, rough_factor=1.8),
    # "nur nachts, selten" – die Rate gilt für gefahrene Nachtkilometer.
    LICHT: IncidentSpec(LICHT, "Lichtausfall", 2500.0, headroom=1.0),
    # ×3 nachts, ×2 bei Schlafdruck; Navigationssicherheit ±50 %.
    VERFAHREN: IncidentSpec(VERFAHREN, "Verfahren", 1400.0, headroom=3.0 * 2.0 * 1.5),
    # Risiko, Nässe, Schlafdruck. Die Rate ist nicht dokumentiert; sie
    # ergibt sich rückwärts aus dem DNF-Korridor: Bei 8 % schweren
    # Stürzen darf ein 300er nicht schon an Stürzen sein DNF-Budget
    # verbrauchen.
    STURZ: IncidentSpec(STURZ, "Sturz", 6000.0, headroom=2.0 * 2.0 * 1.9),
    # Magenverträglichkeit, Hitze, Zufuhrrate. Der eigentliche Killer.
    MAGEN: IncidentSpec(MAGEN, "Magenprobleme", 1100.0, headroom=1.8 * 1.6 * 1.6),
    # Nur oberhalb der Hitzeschwelle, dann aber häufig.
    HITZEEINBRUCH: IncidentSpec(HITZEEINBRUCH, "Hitzeeinbruch", 900.0, headroom=2.5),
    SPERRUNG: IncidentSpec(SPERRUNG, "Sperrung", 1200.0, headroom=1.0),
}

#: Anteil der Stürze, die das Rennen beenden (Abschnitt 6.5).
SEVERE_CRASH_P = 0.08
#: Anteil der Defekte, die ohne brauchbaren Ersatz enden. Im supported
#: Betrieb steht ein Ersatzrad im Begleitfahrzeug — dass gar nichts mehr
#: geht, ist die Ausnahme und hängt an der Servicedisziplin.
SEVERE_MECH_P = 0.14
#: Anteil der schweren Defekte, bei denen auch das Begleitfahrzeug nicht
#: mehr helfen kann.
MECH_NO_SPARE_P = 0.15

#: Rauhe Beläge, auf denen ``rough_factor`` greift.
ROUGH_SURFACES = frozenset({"gravel", "cobbles"})

#: Bezugszufuhr, an der die Magenbelastung gemessen wird.
REF_INTAKE_G_H = 80.0

#: Kalorienrückstand gegenüber dem Plan, ab dem ein Fahrer als
#: unterversorgt gilt (Abschnitt 6.5: "Zufuhr über 3 h unter Plan").
UNDERFED_KCAL = 350.0
#: Wie lange die Unterversorgung nachwirkt.
UNDERFED_DURATION_S = 2.0 * 3600.0


# ----------------------------------------------------------------------
# Kandidatenprozess
# ----------------------------------------------------------------------
def risk_profile(route: Route, rough_factor: float) -> np.ndarray:
    """Kumuliertes Risiko in "Risikokilometern" je Rasterpunkt.

    Auf Asphalt zählt ein Kilometer als ein Risikokilometer, auf Schotter
    als ``rough_factor``. Der Kandidatenprozess wird über diese Achse
    gezogen; die Rückrechnung auf Meter ist eine Interpolation.
    """
    n = route.n_points
    if rough_factor == 1.0:
        return np.arange(n, dtype=np.float64) * (route.raster_m / 1000.0)
    seg_idx = route.segment_index_array()
    if not len(route.segments):
        return np.arange(n, dtype=np.float64) * (route.raster_m / 1000.0)
    seg_w = np.array(
        [rough_factor if s.surface in ROUGH_SURFACES else 1.0 for s in route.segments]
    )
    w = seg_w[seg_idx]
    step_km = route.raster_m / 1000.0
    out = np.empty(n, dtype=np.float64)
    out[0] = 0.0
    np.cumsum(w[:-1] * step_km, out=out[1:])
    return out


@dataclass
class IncidentSchedule:
    """Vorgezogene Kandidaten eines Fahrers, aufsteigend nach Distanz."""

    dist_m: np.ndarray = field(default_factory=lambda: np.zeros(0))
    typ: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return int(self.dist_m.size)


def _draw_marks(rng: np.random.Generator, rate_per_km: float, total_km: float) -> np.ndarray:
    """Marken eines homogenen Poisson-Prozesses auf ``[0, total_km)``.

    Die Anzahl der gezogenen Zufallszahlen hängt bewusst *nicht* am
    Ergebnis: Es wird ein fester Block Exponentialabstände gezogen und
    danach abgeschnitten. So bleibt der Strom auch dann stabil, wenn eine
    Rate später nachjustiert wird.
    """
    if rate_per_km <= 0.0 or total_km <= 0.0:
        return np.zeros(0)
    expected = rate_per_km * total_km
    block = int(max(8, np.ceil(expected * 3.0 + 8.0)))
    marks = np.cumsum(rng.exponential(1.0 / rate_per_km, size=block))
    return marks[marks < total_km]


def schedule_for_rider(
    route: Route,
    attributes: dict[str, float],
    rng: np.random.Generator,
) -> IncidentSchedule:
    """Kandidatenliste eines Fahrers über die ganze Strecke.

    Gezogen wird mit der maximal möglichen Rate (``headroom``); ob ein
    Kandidat wirklich zuschlägt, entscheidet sich erst im Rennen.
    """
    marks_m: list[np.ndarray] = []
    types: list[str] = []
    for spec in CATALOG.values():
        risk_km = risk_profile(route, spec.rough_factor)
        total = float(risk_km[-1])
        rate = spec.headroom * _static_rate_factor(spec.typ, attributes) / spec.km_per_event
        marks = _draw_marks(rng, rate, total)
        if marks.size == 0:
            continue
        # Risikokilometer zurück in Streckenmeter.
        dist = np.interp(marks, risk_km, np.arange(route.n_points) * route.raster_m)
        marks_m.append(dist)
        types.extend([spec.typ] * dist.size)

    if not marks_m:
        return IncidentSchedule()
    dist_all = np.concatenate(marks_m)
    order = np.argsort(dist_all, kind="stable")
    return IncidentSchedule(
        dist_m=dist_all[order], typ=[types[i] for i in order]
    )


def _norm(attributes: dict[str, float], key: str) -> float:
    return (float(attributes.get(key, 50.0)) - 50.0) / 50.0


def _static_rate_factor(typ: str, attributes: dict[str, float]) -> float:
    """Attributabhängiger Anteil der Rate — beim Planen schon bekannt."""
    if typ == PANNE:
        return 1.0 - 0.35 * _norm(attributes, "materialpflege")
    if typ == DEFEKT:
        return 1.0 - 0.40 * _norm(attributes, "materialpflege")
    if typ == VERFAHREN:
        return 1.0 - 0.50 * _norm(attributes, "navigationssicherheit")
    if typ == STURZ:
        # Risikobereitschaft erhöht, Abfahrtstechnik senkt.
        return float(
            np.clip(
                (1.0 + 0.60 * _norm(attributes, "risikobereitschaft"))
                * (1.0 - 0.35 * _norm(attributes, "abfahrtstechnik")),
                0.25,
                1.9,
            )
        )
    if typ == MAGEN:
        return float(np.clip(1.0 - 0.80 * _norm(attributes, "magenvertraeglichkeit"), 0.2, 1.8))
    if typ == HITZEEINBRUCH:
        return 1.0
    return 1.0


# ----------------------------------------------------------------------
# Annahme im Rennen
# ----------------------------------------------------------------------
@dataclass
class RideContext:
    """Momentaufnahme, aus der sich die Live-Faktoren ergeben."""

    rain: float = 0.0
    daylight: bool = True
    sleep_press: float = 0.0
    temp_c: float = 18.0
    speed_ms: float = 8.0
    #: Geplante Kohlenhydratzufuhr relativ zu ``REF_INTAKE_G_H``. Wer den
    #: Magen hart fährt, riskiert mehr — das ist die "Zufuhrrate" aus dem
    #: Ereigniskatalog.
    intake_ratio: float = 1.0
    heat_norm: float = 0.0
    wet_norm: float = 0.0
    on_rough: bool = False
    service_factor: float = 1.0


def accept_probability(typ: str, ctx: RideContext) -> float:
    """Anteil des ``headroom``, der gerade wirklich anliegt."""
    spec = CATALOG[typ]
    if typ == PANNE:
        live = 1.0 + 0.6 * min(ctx.rain, 1.0)
    elif typ == DEFEKT:
        live = 1.0 + 0.4 * min(ctx.rain, 1.0)
    elif typ == LICHT:
        live = 0.0 if ctx.daylight else 1.0
    elif typ == VERFAHREN:
        live = (1.0 if ctx.daylight else 3.0) * (1.0 + min(ctx.sleep_press, 1.0))
        live *= 1.0 + 0.5 * min(ctx.rain, 1.0)
    elif typ == STURZ:
        wet = 1.0 + (1.0 - 0.5 * ctx.wet_norm) * min(ctx.rain, 1.0)
        tired = 1.0 + min(ctx.sleep_press, 1.0)
        dark = 1.9 if not ctx.daylight else 1.0
        live = wet * tired * dark
    elif typ == MAGEN:
        # Hitze und eine hohe Zufuhrrate schlagen dem Magen zusammen auf
        # den Bauch – im Wortsinn.
        heat = 1.0 + 0.8 * max(0.0, (ctx.temp_c - 22.0) / 12.0) * (1.0 - 0.5 * ctx.heat_norm)
        push = 1.0 + 0.6 * min(1.0, max(0.0, ctx.intake_ratio - 0.85) / 0.40)
        live = min(heat, 1.8) * min(push, 1.6) * (1.0 + 0.6 * min(ctx.sleep_press, 1.0))
    elif typ == HITZEEINBRUCH:
        over = (ctx.temp_c - 26.0) / 8.0 - 0.7 * ctx.heat_norm
        live = 0.0 if over <= 0.0 else min(2.5, 2.5 * over)
    else:  # SPERRUNG
        live = 1.0
    return float(np.clip(live / spec.headroom, 0.0, 1.0))


@dataclass
class Outcome:
    """Was ein angenommener Kandidat konkret anrichtet."""

    typ: str
    label: str
    stop_s: float = 0.0
    condition: str | None = None
    #: Sekunden oder Meter, je nach Verankerung des Zustands.
    condition_duration: float = 0.0
    condition_strength: float = 1.0
    dnf: bool = False
    reason: str = ""


def resolve(typ: str, rng: np.random.Generator, ctx: RideContext) -> Outcome:
    """Wirkung eines angenommenen Kandidaten auswürfeln."""
    spec = CATALOG[typ]

    if typ == PANNE:
        # Supported: das Begleitfahrzeug wechselt das Rad, 1,5–4 min.
        stop = float(rng.uniform(90.0, 240.0)) * ctx.service_factor
        return Outcome(typ, spec.label, stop_s=stop, reason="Reifenpanne")

    if typ == DEFEKT:
        stop = float(rng.uniform(300.0, 1500.0)) * ctx.service_factor
        if rng.random() < SEVERE_MECH_P * ctx.service_factor:
            # Schwerer Defekt: entweder kommt der Fahrer auf einem
            # schlechteren Ersatzrad weiter oder gar nicht mehr. Im
            # supported Betrieb liegt das Ersatzrad im Begleitfahrzeug —
            # dass wirklich nichts mehr geht, ist die Ausnahme.
            if rng.random() < MECH_NO_SPARE_P:
                return Outcome(
                    typ, spec.label, dnf=True, reason="Schwerer Defekt ohne Ersatz"
                )
            return Outcome(
                typ,
                spec.label,
                stop_s=stop + 600.0,
                condition="ersatzrad",
                condition_duration=float("inf"),
                reason="Schwerer Defekt, weiter auf dem Ersatzrad",
            )
        return Outcome(typ, spec.label, stop_s=stop, reason="Mechanischer Defekt")

    if typ == LICHT:
        return Outcome(
            typ,
            spec.label,
            stop_s=float(rng.uniform(120.0, 360.0)),
            condition="lichtausfall",
            condition_duration=float(rng.uniform(40_000.0, 90_000.0)),
            reason="Lichtausfall",
        )

    if typ == VERFAHREN:
        # Der Umweg wird als Zeitverlust verbucht, nicht als negative
        # Streckendistanz: Ein Fahrer, dessen Kilometerstand zurückgeht,
        # zerlegt Splits, Rangliste und Höhenprofil-Anzeige gleichzeitig.
        detour_km = float(rng.uniform(0.5, 5.0))
        lost = detour_km * 1000.0 / max(ctx.speed_ms, 3.0)
        return Outcome(
            typ,
            spec.label,
            stop_s=lost,
            condition="verfahren",
            condition_duration=1800.0,
            reason=f"Verfahren, {detour_km:.1f} km Umweg",
        )

    if typ == STURZ:
        if rng.random() < SEVERE_CRASH_P:
            return Outcome(typ, "Schwerer Sturz", dnf=True, reason="Schwerer Sturz")
        strength = float(rng.uniform(0.5, 1.35))
        return Outcome(
            typ,
            spec.label,
            stop_s=float(rng.uniform(120.0, 600.0)),
            condition="sturzfolgen",
            condition_duration=float(rng.uniform(50_000.0, 200_000.0)),
            condition_strength=strength,
            reason="Sturz",
        )

    if typ == MAGEN:
        # 3–20 min Stopp, danach 2–6 h mit stark gedrosselter Aufnahme.
        strength = float(rng.uniform(0.73, 1.27))
        return Outcome(
            typ,
            spec.label,
            stop_s=float(rng.uniform(180.0, 1200.0)),
            condition="magen",
            condition_duration=float(rng.uniform(2.0, 6.0)) * 3600.0,
            condition_strength=strength,
            reason="Magenprobleme",
        )

    if typ == HITZEEINBRUCH:
        strength = float(rng.uniform(0.5, 1.5))
        return Outcome(
            typ,
            spec.label,
            condition="hitze",
            condition_duration=float(rng.uniform(1.0, 3.0)) * 3600.0,
            condition_strength=strength,
            reason="Hitzeeinbruch",
        )

    return Outcome(
        typ, spec.label, stop_s=float(rng.uniform(300.0, 1200.0)), reason="Sperrung, Umleitung"
    )


# ----------------------------------------------------------------------
# Aufgabe (Abschnitt 6.5, DNF-Kalibrierung)
# ----------------------------------------------------------------------
#: Was "Rückstand" hier misst: verlorene Zeit, nicht Terrain.
#:
#: Naheliegend wäre der Rückstand auf den eigenen Rennplan. Gemessen
#: taugt der aber nicht: Die Planschätzung rechnet mit ungestörtem Rollen
#: bei Zielintensität und liegt deshalb systematisch 25–30 % unter der
#: Wirklichkeit — und zwar *ungleichmäßig*. Im Gebirge irrt sie stärker
#: als im Flachen, weil Abfahrten am Tempolimit hängen. Ein Fahrer im
#: Hochgebirge sähe dadurch einen wachsenden "Rückstand", der nur von der
#: Strecke kommt, und würde reihenweise aufgeben.
#:
#: Der Zähler ist deshalb die Zeit, die ein Fahrer an Zwischenfällen und
#: Notschlaf tatsächlich *verloren* hat, gemessen an seiner Renndauer.
#: Das ist terrainneutral, es ist genau der Satz, den ein Aussteiger
#: sagt ("drei Pannen und zweimal verfahren, das hole ich nicht mehr
#: auf"), und es koppelt den Ereigniskatalog direkt an die Aufgabe.
#: Ab diesem Anteil verlorener Zeit fängt es an zu nagen …
GIVE_UP_DEFICIT_START = 1.010
#: … und hier ist der Verlust maximal demoralisierend (15 % der Renndauer).
GIVE_UP_DEFICIT_FULL = 1.150
#: Langzeitermüdung, ab der der Ermüdungsterm voll zählt (1 − f_fat).
GIVE_UP_FATIGUE_FULL = 0.22
#: Deckel des Ermüdungsterms. Ohne ihn wächst der Aufgabedruck über die
#: Renndauer *und* über die Ermüdung, also quadratisch in der Distanz —
#: und dann lässt sich der Korridor über drei Distanzklassen nicht mehr
#: mit einem Regler treffen.
GIVE_UP_FATIGUE_CAP = 0.60
#: Aufgabedruck je Stunde bei vollem Ausschlag aller drei Treiber.
#: Der einzige Regler für den DNF-Korridor aus Abschnitt 6.5.
#:
#: Der aufsummierte Druck ist die kumulierte Hazardrate: Jeder Fahrer
#: zieht vor dem Start eine Aufgabeschwelle aus ``Exp(1)`` und steigt
#: aus, sobald der Druck sie überschreitet. Das ist mehr als Kosmetik
#: gegenüber einer festen Schwelle bei 1,0 — mit fester Schwelle steigt
#: die Ausfallquote sprunghaft mit der Renndauer (alle überschreiten
#: ungefähr gleichzeitig), mit gezogener Schwelle wächst sie glatt als
#: ``1 − exp(−Druck)``. Erst damit lassen sich drei Distanzklassen mit
#: *einem* Regler treffen.
GIVE_UP_RATE_PER_H = 0.022
#: Dämpfung durch mentale Widerstandsfähigkeit: bei 100 hält ein Fahrer
#: gut doppelt so lange durch wie bei 50.
GIVE_UP_MENTAL_GAIN = 1.1


def give_up_rate(
    behind_ratio: np.ndarray,
    fatigue_factor: np.ndarray,
    sleep_press: np.ndarray,
    stomach_penalty: np.ndarray,
    mental_norm: np.ndarray,
) -> np.ndarray:
    """Aufgabedruck je Stunde (Abschnitt 6.5).

    Produkt aus Rückstand, Ermüdung und Magenzustand, gedämpft durch die
    mentale Widerstandsfähigkeit — genau die Formel aus dem Dokument.

    ``behind_ratio`` ist ``1 + verlorene Zeit / Renndauer`` (siehe die
    Kommentare bei ``GIVE_UP_DEFICIT_START``).

    Dass es ein *Produkt* ist, trägt die ganze Kalibrierung: Wer ohne
    Zwischenfälle durchkommt, gibt nicht auf, egal wie müde er ist. Und
    wer früh Zeit verliert, aber frisch ist, fährt sie hinterher.
    """
    deficit = np.clip(
        (behind_ratio - GIVE_UP_DEFICIT_START)
        / (GIVE_UP_DEFICIT_FULL - GIVE_UP_DEFICIT_START),
        0.0,
        1.4,
    )
    fatigue = np.clip(
        (1.0 - fatigue_factor) / GIVE_UP_FATIGUE_FULL + 0.6 * np.minimum(sleep_press, 1.5),
        0.0,
        GIVE_UP_FATIGUE_CAP,
    )
    mental = 1.0 + GIVE_UP_MENTAL_GAIN * mental_norm
    return GIVE_UP_RATE_PER_H * deficit * fatigue * stomach_penalty / np.maximum(mental, 0.2)


__all__ = [
    "CATALOG",
    "DEFEKT",
    "HITZEEINBRUCH",
    "IncidentSchedule",
    "IncidentSpec",
    "LICHT",
    "MAGEN",
    "Outcome",
    "PANNE",
    "RideContext",
    "SEVERE_CRASH_P",
    "SEVERE_MECH_P",
    "SPERRUNG",
    "STURZ",
    "VERFAHREN",
    "accept_probability",
    "give_up_rate",
    "resolve",
    "risk_profile",
    "schedule_for_rider",
]
