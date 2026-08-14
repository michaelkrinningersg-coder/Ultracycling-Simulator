"""Kalibrierungsbericht erzeugen (Meilenstein M8).

    python -m ultrasim.cli.calibrate --out docs/KALIBRIERUNG.md

``balance.py`` ist das Werkzeug zum Hinsehen: eine Strecke, viele
Zahlen, alles auf der Konsole. Dieses hier ist das Werkzeug zum
Vergleichen: Es misst alle Strecken auf einmal und schreibt das
Ergebnis in eine eingecheckte Datei.

Der Unterschied ist der Diff. Wer am Balancing dreht, sieht in der
Änderungsansicht schwarz auf weiß, dass die Ultraklasse um zwei Punkte
gewandert ist und die Hitzetoleranz plötzlich das Doppelte wert ist —
statt es in einer Konsolenausgabe zu suchen, die nach dem Schließen des
Fensters weg ist.

Gesetzt wird der Bericht in ``ultrasim.calibration_report``, gemessen in
``ultrasim.calibration``; hier steht nur der Ablauf.

Der Lauf dauert je nach Umfang zwanzig bis dreißig Minuten. Das ist kein
Werkzeug für zwischendurch, sondern eines für „vor dem Commit, der das
Balancing anfasst".
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .. import calibration as cal
from ..calibration_report import build_report
from ..core.rider import ATTRIBUTES, generate_pool
from ..data.store import Store
from ..geo.route import Route
from . import use_safe_console

#: Reihenfolge der Strecken im Bericht: kurz, mittel, lang.
DEFAULT_ROUTES = ("voralpen-runde", "hochgebirgs-marathon", "nordroute-langstrecke")


def run(args: argparse.Namespace) -> int:
    store = Store(args.data)
    routes = [store.load_route(name) for name in args.routes]
    seeds = list(range(args.seed, args.seed + args.runs))
    sens_seeds = list(range(args.seed + 500, args.seed + 500 + args.sensitivity_runs))

    teams, pool = generate_pool(args.riders, seed=args.pool_seed)
    arch_teams, arch_riders = cal.balanced_field(args.per_archetype, seed=args.pool_seed)

    summaries: list[cal.RouteSummary] = []
    archetypes: list[tuple[cal.RouteSummary, list[cal.ArchetypeStat]]] = []
    effects: dict[str, list[cal.AttributeEffect]] = {}

    for route in routes:
        print(f"{route.name}: {args.runs} Rennen à {args.riders} Fahrer …", flush=True)
        summary = cal.route_summary(route, pool, teams, seeds)
        summaries.append(summary)

        print(f"{route.name}: Archetypen, {args.runs} Rennen à {len(arch_riders)} Fahrer …", flush=True)
        archetypes.append((summary, cal.archetype_stats(route, arch_riders, arch_teams, seeds)))

        base = pool[: args.base_riders]
        print(
            f"{route.name}: Sensitivität, {len(sens_seeds)} × "
            f"{len(base) * (2 * len(ATTRIBUTES) + 1)} Starter …",
            flush=True,
        )
        effects[route.name] = cal.attribute_sensitivity(route, base, teams, sens_seeds)

    # Die Wetterläufe brauchen nur eine Strecke: Gemessen wird, ob ein
    # Attribut unter *seiner* Wetterlage anspringt, nicht wie es mit der
    # Streckenform zusammenspielt. Dafür reicht die mittlere Distanz —
    # lang genug für einen Tagesgang, kurz genug für vier Läufe.
    weather: tuple[Route, dict[str, list[cal.AttributeEffect]]] | None = None
    if args.weather and len(routes) > 1:
        wx_route = routes[len(routes) // 2]
        wx_effects: dict[str, list[cal.AttributeEffect]] = {}
        base = pool[: args.base_riders]
        for preset in cal.WEATHER_PRESETS:
            print(f"{wx_route.name}: Sensitivität bei Wetter '{preset}' …", flush=True)
            wx_effects[preset] = cal.attribute_sensitivity(
                wx_route,
                base,
                teams,
                sens_seeds[:1],
                attributes=cal.WEATHER_ATTRIBUTES,
                preset=preset,
            )
        weather = (wx_route, wx_effects)

    parameters = (
        f"{args.runs} Rennen je Strecke · Feld {args.riders} Fahrer · "
        f"Archetypen {args.per_archetype} je Typ mit gleichem Potenzial · "
        f"Sensitivität {len(sens_seeds)} × {args.base_riders} Grundfahrer, "
        f"±{cal.DEFAULT_DELTA:.0f} Punkte"
    )
    report = build_report(
        summaries,
        archetypes,
        routes,
        effects,
        args.stamp or date.today().isoformat(),
        parameters,
        weather,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"\n{args.out} geschrieben ({len(report.splitlines())} Zeilen)")
    return 0


def main(argv: list[str] | None = None) -> int:
    use_safe_console()
    parser = argparse.ArgumentParser(prog="python -m ultrasim.cli.calibrate", description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("docs/KALIBRIERUNG.md"))
    parser.add_argument("--routes", nargs="+", default=list(DEFAULT_ROUTES))
    parser.add_argument("--runs", type=int, default=6, help="Rennen je Strecke")
    parser.add_argument("--riders", type=int, default=40)
    parser.add_argument("--per-archetype", type=int, default=4)
    parser.add_argument("--base-riders", type=int, default=16, help="Grundfahrer der Sensitivität")
    parser.add_argument("--sensitivity-runs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=3000)
    parser.add_argument("--pool-seed", type=int, default=11)
    parser.add_argument("--stamp", default=None, help="Datumszeile im Bericht")
    parser.add_argument(
        "--no-weather",
        dest="weather",
        action="store_false",
        help="Wetterläufe überspringen",
    )
    args = parser.parse_args(argv)
    try:
        return run(args)
    except FileNotFoundError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
