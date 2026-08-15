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
import textwrap

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
        "Der Abgleich mit den beiden Ankern des Design-Dokuments: der",
        "erwarteten Dauer (Abschnitt 2) und dem DNF-Korridor (6.5).",
        "",
        "Das Dauerband hing bis vor kurzem an der Distanzklasse. Das ging",
        "an den Rändern zwangsläufig schief, denn „mittel\" reicht von 400",
        "bis 1200 Äquivalentkilometern und umfasst Rennen von zwölf bis",
        "fünfundvierzig Stunden — ein einziges Band dafür muss an beiden",
        "Enden danebenliegen. Jetzt wird es stetig aus Distanz und",
        "Höhenmetern gerechnet. Die Klassen bleiben, wofür sie da sind:",
        "Split-Dichte, Schlafplanung und Rennkoeffizient.",
        "",
        "| Strecke | Klasse | Sieger | Median | Letzter | Erwartet | Feld im Band | DNF+OTL | Ziel | Rangkorrelation |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lo, hi = s.dnf_target
        band_lo, band_hi = s.band
        mark = "" if s.dnf_in_target else " ⚠"
        band_mark = "" if band_lo <= s.winner_h <= band_hi else " ⚠"
        out.append(
            f"| {s.name} ({_fmt(s.distance_km, 0)} km) | {s.distance_class} | "
            f"{_fmt(s.winner_h, 1, ' h')}{band_mark} | {_fmt(s.median_h, 1, ' h')} | "
            f"{_fmt(s.last_h, 1, ' h')} | {band_lo:.1f}–{band_hi:.1f} h | "
            f"{_fmt(s.inside_band_pct, 0, ' %')} | "
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
        "",
        "Angegeben ist die mittlere Platzierung ± Standardfehler und in",
        "Klammern der Anteil der Starts im besten Zehntel des Feldes.",
        "",
        "**Zwei Zahlen, die früher hier standen, stehen bewusst nicht mehr",
        "da.** Die Siegzahl ist die eine: Sechs Rennen ergeben sechs Sieger,",
        "verteilt auf acht Archetypen — daraus lässt sich nichts ablesen,",
        "egal wie groß das Feld ist. Der Standardfehler ist die andere, und",
        "er hat gefehlt: Mit vier Fahrern je Typ lag er bei knapp zwei",
        "Plätzen, und es wurde abgelesen, was Rauschen war. Zwei Befunde,",
        "die auf diesem Weg entstanden sind, hat die größere Stichprobe",
        "hinterher umgedreht. Zwei Archetypen unterscheiden sich erst dann,",
        "wenn ihre Intervalle sich nicht überlappen.",
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
            cells.append(
                f"{_fmt(st.mean_rank, 1)} ±{_fmt(st.rank_se, 1)} ({_fmt(st.top_decile_pct, 0, ' %')})"
            )
        out.append(f"| {rows[0][1][i].label} | " + " | ".join(cells) + " |")
    field = sum(a.starts for a in rows[0][1]) // max(rows[0][0].runs, 1)
    out += [
        "",
        f"Feldgröße je Rennen: {field} Fahrer, {rows[0][0].runs} Rennen je Strecke. "
        f"Neutral wäre Platz {(field + 1) / 2:.1f}".replace(".", ",") + ".",
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
        "Warum die **kürzeste** Strecke und nicht die tiefste, obwohl der",
        "Höhengradient 6,5 K je 1000 m abzieht: Über 40 Stunden nimmt ein",
        "Fahrer, der zwei Minuten anders unterwegs ist, andere Pannen an und",
        "schläft in einer anderen Nacht. Die Hitzewirkung war dort mit knapp",
        "acht Minuten die größte im ganzen Lauf — und trotzdem gingen zwölf",
        "von 42 Paaren in die falsche Richtung. Auf 300 km sind es eins von",
        "47. Wirkung, die man messen kann, ist mehr wert als Wirkung, die im",
        "Chaos verschwindet.",
        "",
        "| Attribut | " + " | ".join(cal.WEATHER_PRESETS) + " |",
        "|---" * (len(cal.WEATHER_PRESETS) + 1) + "|",
    ]
    for attr in cal.WEATHER_ATTRIBUTES:
        cells = []
        for preset in cal.WEATHER_PRESETS:
            e = _effect(effects, preset, attr)
            mark = "†" if e.measurable and abs(e.seconds) < cal.SIGMA * e.stderr else ""
            cells.append(f"{_fmt(e.seconds, 0, ' s')}{mark}" if e.measurable else "·")
        out.append(f"| {attr} | " + " | ".join(cells) + " |")
    out += [
        "",
        "Ein † markiert Zahlen, die nicht über den Standardfehler, sondern",
        "über den **Vorzeichentest** nachgewiesen sind: Das Mittel ist klein",
        "oder von Ausreißern verzogen, aber die Paardifferenz zeigt bei fast",
        "allen Fahrern in dieselbe Richtung.",
        "",
    ]
    out += _sign_test_example(effects)
    out += _two_edged_note(effects)
    return out


def _sign_test_example(effects: dict[str, list[cal.AttributeEffect]]) -> list[str]:
    """Ein konkreter Fall für das †, mit den Zahlen dieses Laufs.

    Ohne Beispiel bleibt die Fußnote eine Behauptung. Ausgesucht wird
    die Zelle mit den meisten Paaren, damit die Zahlen tragen.
    """
    candidates = [
        (preset, e)
        for preset in cal.WEATHER_PRESETS
        for e in [_effect(effects, preset, attr) for attr in cal.WEATHER_ATTRIBUTES]
        if e.measurable and abs(e.seconds) < cal.SIGMA * e.stderr
    ]
    if not candidates:
        return []
    preset, e = max(candidates, key=lambda c: c[1].wins + c[1].losses)
    return _para(
        f"In dieser Tabelle ist `{e.attr}` bei „{preset}\" der Fall, für den es "
        f"die zweite Nachweisform gibt: {e.wins} von {e.wins + e.losses} Fahrern "
        f"gewinnen Zeit, im Mittel stehen davon {e.seconds:.0f} Sekunden und im "
        f"Median {e.seconds_median:.0f}. Der Standardfehler ist mit "
        f"{e.stderr:.0f} Sekunden größer als das Mittel selbst — die Differenz "
        "sind einzelne Fahrer, denen das Attribut nicht geholfen hat."
    )


def _two_edged_note(effects: dict[str, list[cal.AttributeEffect]]) -> list[str]:
    """Warum ein gerichtetes Ergebnis trotzdem nicht in der Tabelle steht.

    Der Vorzeichentest allein würde Risikobereitschaft durchwinken. Der
    Richtungsabgleich zwischen Mittel und Median hält sie draußen, und
    das ist keine Willkür, sondern die Aussage des Attributs.
    """
    worst = None
    for preset in cal.WEATHER_PRESETS:
        e = _effect(effects, preset, "risikobereitschaft")
        if e.pairs and e.seconds * e.seconds_median < 0.0:
            if worst is None or abs(e.seconds) > abs(worst[1].seconds):
                worst = (preset, e)
    if worst is None:
        return []
    preset, e = worst
    return _para(
        f"`risikobereitschaft` zeigt bei „{preset}\" ein Mittel von "
        f"{e.seconds:.0f} Sekunden und einen Median von {e.seconds_median:+.0f}: "
        f"{e.wins} von {e.wins + e.losses} Fahrern kommen schneller durch, und die "
        "übrigen verlieren mehr, als jene gewinnen. Beides ist wahr, und deshalb "
        "steht keine der beiden Zahlen als „die Wirkung\" in der Zeile — das "
        "Attribut ist eine Entscheidung, kein Bonus."
    )


def _para(text: str) -> list[str]:
    """Absatz auf Berichtsbreite umbrechen, mit Leerzeile dahinter."""
    return textwrap.fill(" ".join(text.split()), width=70).splitlines() + [""]


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
    partial: bool = False,
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
    if partial:
        # Hinter den ganzen Absatz, nicht mitten hinein.
        head[5:5] = [
            "",
            "> ⚠ **Teillauf.** Es wurden nur die unten stehenden Abschnitte",
            "> gerechnet; die übrigen fehlen. Diese Datei ist zum Hinsehen",
            "> während einer Balancing-Runde gedacht und **nicht** als Ersatz",
            "> für den vollständigen Bericht.",
            "",
        ]
    body: list[str] = []
    if summaries:
        body += section_routes(summaries)
    if archetypes:
        body += section_archetypes(archetypes)
    if effects:
        body += section_sensitivity(routes, effects, weather[1] if weather else None)
    if weather is not None:
        body += section_weather(*weather)
    return "\n".join(head + body).rstrip() + "\n"
