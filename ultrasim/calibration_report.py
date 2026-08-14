"""Den Kalibrierungsbericht als Markdown setzen (Meilenstein M8).

Getrennt von ``ultrasim.cli.calibrate``, und zwar nicht aus Ordnungsliebe:
Der Bericht wird als UTF-8-Datei geschrieben und darf deshalb ⚠, − und °
enthalten. Die Konsolenausgabe der Kommandozeilenwerkzeuge darf das
nicht — auf einer Windows-Konsole beendet ein solches Zeichen das
Programm. Ein Test hält die CLI-Module frei davon, und solange das
Setzen der Tabellen dort läge, müsste er entweder Ausnahmen kennen oder
den Bericht verstümmeln.

Hier liegt also die Darstellung, in ``ultrasim.calibration`` die Messung
und in ``ultrasim.cli.calibrate`` nur noch der Ablauf.
"""

from __future__ import annotations

import math

from . import calibration as cal
from .core.rider import ACTIVE_ATTRIBUTES, ATTRIBUTES
from .geo.route import Route


def _fmt(value: float, digits: int = 1, unit: str = "") -> str:
    if value != value:  # NaN
        return "–"
    return f"{value:.{digits}f}{unit}".replace(".", ",")


def section_routes(summaries: list[cal.RouteSummary]) -> list[str]:
    out = [
        "## 1 · Strecken, Dauerbänder und Ausfälle",
        "",
        "Der Abgleich mit den beiden Ankern, die das Design-Dokument selbst",
        "setzt: dem Dauerband je Distanzklasse (Abschnitt 2) und dem",
        "DNF-Korridor (Abschnitt 6.5).",
        "",
        "| Strecke | Klasse | Sieger | Median | Letzter | Feld im Band | DNF+OTL | Ziel | Rangkorrelation |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lo, hi = s.dnf_target
        mark = "" if s.dnf_in_target else " ⚠"
        out.append(
            f"| {s.name} ({_fmt(s.distance_km, 0)} km) | {s.distance_class} | "
            f"{_fmt(s.winner_h, 1, ' h')} | {_fmt(s.median_h, 1, ' h')} | "
            f"{_fmt(s.last_h, 1, ' h')} | {_fmt(s.inside_band_pct, 0, ' %')} | "
            f"{_fmt(s.dnf_pct + s.otl_pct, 1, ' %')}{mark} | "
            f"{lo * 100:.0f}–{hi * 100:.0f} % | {_fmt(s.rank_corr, 2)} |"
        )
    out += [
        "",
        "Die Rangkorrelation zwischen Potenzial und Ergebnis sagt, wie stark",
        "sich die Attribute durchsetzen. Bei 1,0 wäre das Rennen eine",
        "Tabellenabfrage, bei 0,0 ein Würfelspiel; dazwischen liegt der",
        "Bereich, in dem Zuschauen lohnt.",
        "",
    ]
    return out


def section_archetypes(rows: list[tuple[cal.RouteSummary, list[cal.ArchetypeStat]]]) -> list[str]:
    out = [
        "## 2 · Archetypen",
        "",
        "Gleich viele Fahrer je Archetyp, **identisches Potenzial-Budget** —",
        "es unterscheidet sich nur, wie das Budget verteilt ist, und was der",
        "Archetyp an Körperbau mitbringt. Damit misst die Tabelle nicht, wer",
        "die besseren Fahrer bekommen hat, sondern wer zur Strecke passt.",
        "Angegeben ist die mittlere Platzierung; in Klammern die Siege.",
        "",
    ]
    if not rows:
        return out
    header = "| Archetyp | " + " | ".join(s.name for s, _ in rows) + " |"
    out += [header, "|---" * (len(rows) + 1) + "|"]
    for i in range(len(rows[0][1])):
        cells = []
        for _, stats in rows:
            st = stats[i]
            cells.append(f"{_fmt(st.mean_rank, 1)} ({st.wins})")
        out.append(f"| {rows[0][1][i].label} | " + " | ".join(cells) + " |")
    out += [
        "",
        f"Feldgröße je Rennen: {sum(a.starts for a in rows[0][1]) // max(rows[0][0].runs, 1)} Fahrer, "
        f"{rows[0][0].runs} Rennen je Strecke.",
        "",
        "Die Platzierung allein wäre irreführend, denn das gleiche Budget",
        "heißt nicht gleicher Körperbau: Ein Archetyp bringt Größe, Gewicht",
        "und damit W/kg mit. Was jeder tatsächlich auf die Straße bringt:",
        "",
        "| Archetyp | W/kg | FTP | Frontfläche |",
        "|---|---|---|---|",
    ]
    for stat in rows[0][1]:
        out.append(
            f"| {stat.label} | {_fmt(stat.mean_wkg, 2)} | "
            f"{_fmt(stat.mean_ftp_w, 0, ' W')} | {_fmt(stat.mean_area_m2, 4, ' m²')} |"
        )
    out.append("")
    return out


def section_sensitivity(
    routes: list[Route],
    effects: dict[str, list[cal.AttributeEffect]],
    weather_effects: dict[str, list[cal.AttributeEffect]] | None = None,
) -> list[str]:
    out = [
        "## 3 · Was ein Attribut wert ist",
        "",
        "Zeitgewinn in Sekunden je **+10 Attributpunkte** — rund eine",
        "Standardabweichung im Feld. Positiv heißt schneller. Gemessen",
        "paarweise im selben Rennen: Jeder Grundfahrer startet zusätzlich mit",
        "+10 und mit −10 Punkten auf genau einem Attribut, mit derselben",
        "Fahrer-ID und damit denselben Zufallsströmen. Was an Zeit übrig",
        "bleibt, ist das Attribut und sonst nichts.",
        "",
        "Ein Punkt heißt **nicht messbar**: Die Wirkung liegt entweder unter",
        "drei Sekunden oder unter dem dreifachen Standardfehler ihrer eigenen",
        "Messung. Die zweite Hürde ist die wichtigere — ohne sie liest man",
        "aus zwanzig Fahrern, von denen einer eine Panne hatte, eine",
        "Attributwirkung von sieben Minuten heraus. Drei Standardfehler statt",
        "der üblichen zwei, weil die Tabelle 75 Felder hat: Bei zwei wären",
        "hier rechnerisch drei Fehltreffer zu erwarten, und ein Fehltreffer",
        "ist teuer — jemand fängt an, ein Attribut zu reparieren, das nie",
        "kaputt war.",
        "",
        "Ein ° markiert Attribute, die über **seltene Ereignisse** wirken",
        "statt stetig: Bei den meisten Fahrern ändert sich nichts, bei",
        "wenigen zwanzig Minuten. Die Spalte ganz rechts zählt, wie viele",
        "Ausfälle die starke Variante mehr hatte als die schwache — negativ",
        "heißt, das Attribut hält Fahrer im Rennen.",
        "",
    ]
    out += [
        "| Attribut | " + " | ".join(r.name for r in routes) + " | wirkt | Ausfälle |",
        "|---" * (len(routes) + 3) + "|",
    ]

    order = sorted(
        ATTRIBUTES,
        key=lambda a: -max(abs(_effect(effects, r.name, a).seconds) for r in routes),
    )
    for attr in order:
        cells = []
        for route in routes:
            e = _effect(effects, route.name, attr)
            if not e.measurable:
                cells.append("·")
                continue
            mark = "°" if e.rare_event_driven else ""
            cells.append(f"{_fmt(e.seconds, 0, ' s')}{mark}")
        claim = "ja" if attr in ACTIVE_ATTRIBUTES else "—"
        dnf = sum(_effect(effects, r.name, attr).dnf_delta for r in routes)
        out.append(f"| {attr} | " + " | ".join(cells) + f" | {claim} | {dnf:+d} |")

    out += [
        "",
        "Die letzte Spalte ist die Selbstauskunft der Simulation:",
        "`ACTIVE_ATTRIBUTES` sagt, welche Attribute der Code liest, und die",
        "Oberfläche hebt genau diese im Fahrerdetail hervor. Ein Punkt in",
        "einer Zeile mit „ja\" ist deshalb kein Widerspruch, solange er nicht",
        "in *allen* Spalten steht: Nässeresistenz wirkt an einem trockenen",
        "Tag nicht, Schlaftoleranz nicht auf einem Rennen von acht Stunden.",
        "",
    ]
    if cal.VARIANCE_ATTRIBUTES:
        out += [
            "Ein Attribut fehlt in dieser Tabelle grundsätzlich: **`konstanz`**",
            "steuert allein die *Streuung* der Tagesform, und die Tagesform ist",
            "`1 + sd·z` mit einem z, das beide Kopien eines Fahrers aus",
            "demselben Zufallsstrom ziehen. Die Paardifferenz ist damit",
            "proportional zu −z — bei einem Fahrer mit gutem Tag *schadet*",
            "Konstanz, bei einem mit schlechtem hilft sie. Im Mittel stünde",
            "dort der Stichprobenmittelwert der Zufallszahlen und nicht die",
            "Wirkung des Attributs. Wer die messen will, braucht ein anderes",
            "Werkzeug: den Vergleich zweier Verteilungen über viele Rennen",
            "statt einer Paardifferenz.",
            "",
        ]
    seen = list(effects.values()) + list((weather_effects or {}).values())
    dead = [
        attr
        for attr in ATTRIBUTES
        if attr in ACTIVE_ATTRIBUTES
        and attr not in cal.VARIANCE_ATTRIBUTES
        and not any(e.attr == attr and e.measurable for group in seen for e in group)
    ]
    if dead:
        out += [
            "**In keinem Lauf messbar, obwohl als aktiv geführt:** "
            + ", ".join(f"`{a}`" for a in dead)
            + ".",
            "Entweder fehlt die Lage, in der das Attribut greift — dann gehört",
            "eine Strecke oder ein Wetter in diesen Lauf —, oder es wirkt",
            "nicht, und dann ist die Selbstauskunft der Oberfläche falsch.",
            "",
        ]
    else:
        out += [
            "Jedes als aktiv geführte Attribut ist auf mindestens einer",
            "Strecke messbar.",
            "",
        ]
    return out


def section_weather(
    route: Route, effects: dict[str, list[cal.AttributeEffect]]
) -> list[str]:
    out = [
        "## 4 · Attribute im Wetter",
        "",
        f"Dieselbe Messung auf {route.name}, aber mit erzwungenem Wetter statt",
        "der Ziehung aus dem Seed. Ohne diesen Abschnitt bliebe die halbe",
        "Wetterabteilung stumm: Hitzetoleranz ist an einem 16-Grad-Tag nichts",
        "wert und Nässeresistenz auf trockener Straße auch nicht — „nicht",
        "messbar\" hieße dann fälschlich „wirkungslos\".",
        "",
        "| Attribut | " + " | ".join(cal.WEATHER_PRESETS) + " |",
        "|---" * (len(cal.WEATHER_PRESETS) + 1) + "|",
    ]
    for attr in cal.WEATHER_ATTRIBUTES:
        cells = []
        for preset in cal.WEATHER_PRESETS:
            e = _effect(effects, preset, attr)
            cells.append(f"{_fmt(e.seconds, 0, ' s')}" if e.measurable else "·")
        out.append(f"| {attr} | " + " | ".join(cells) + " |")
    out.append("")
    return out


def _effect(
    effects: dict[str, list[cal.AttributeEffect]], route_name: str, attr: str
) -> cal.AttributeEffect:
    for e in effects.get(route_name, []):
        if e.attr == attr:
            return e
    return cal.AttributeEffect(attr, 0.0, 0.0, 0.0, math.inf, 0, 0)


def build_report(
    summaries: list[cal.RouteSummary],
    archetypes: list[tuple[cal.RouteSummary, list[cal.ArchetypeStat]]],
    routes: list[Route],
    effects: dict[str, list[cal.AttributeEffect]],
    stamp: str,
    parameters: str,
    weather: tuple[Route, dict[str, list[cal.AttributeEffect]]] | None = None,
) -> str:
    head = [
        "# Kalibrierung",
        "",
        "Erzeugt von `python -m ultrasim.cli.calibrate`. Nicht von Hand",
        "bearbeiten — die Datei ist eingecheckt, damit man Balancing-",
        "Änderungen im Diff sieht.",
        "",
        f"Stand: {stamp} · {parameters}",
        "",
    ]
    body = section_routes(summaries)
    body += section_archetypes(archetypes)
    body += section_sensitivity(routes, effects, weather[1] if weather else None)
    if weather is not None:
        body += section_weather(*weather)
    return "\n".join(head + body).rstrip() + "\n"
