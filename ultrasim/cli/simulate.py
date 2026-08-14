"""Kommandozeile: Fahrerpool erzeugen, Rennen rechnen, Ergebnisse ansehen.

    python -m ultrasim.cli.simulate pool   --riders 250
    python -m ultrasim.cli.simulate race   voralpen-runde --riders 40 --seed 42
    python -m ultrasim.cli.simulate result <race_id> --top 20
    python -m ultrasim.cli.simulate rider  <race_id> --bib 38

Die Simulation ist eine reine Bibliothek – CLI und Web-App sind nur zwei
Konsumenten desselben Ergebnisses (Abschnitt 13).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np

from ..core.engine import RaceConfig, simulate_race
from ..core.events import format_event
from ..core.rider import generate_pool
from ..data.store import Store
from . import use_safe_console


def hms(seconds: float | None) -> str:
    if seconds is None:
        return "     —"
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}"


def delta(seconds: float) -> str:
    sign = "+" if seconds >= 0 else "-"
    seconds = int(round(abs(seconds)))
    m, s = divmod(seconds, 60)
    return f"{sign}{m}:{s:02d}"


# ----------------------------------------------------------------------
def cmd_pool(args: argparse.Namespace) -> int:
    store = Store(args.data)
    teams, riders = generate_pool(args.riders, args.teams, seed=args.seed)
    store.save_pool(teams, riders)
    pot = np.array([r.potential for r in riders])
    print(f"{len(riders)} Fahrer in {len(teams)} Teams erzeugt -> {store.pool_path}")
    print(f"Potenzial: Ø {pot.mean():.1f} · Streuung {pot.std():.1f} · {pot.min():.1f}–{pot.max():.1f}")
    print(
        f"FTP: Ø {np.mean([r.ftp_w for r in riders]):.0f} W · W/kg Ø {np.mean([r.wkg for r in riders]):.2f}"
    )
    return 0


def cmd_race(args: argparse.Namespace) -> int:
    store = Store(args.data)
    route = store.load_route(args.route)

    if store.pool_exists():
        teams, pool = store.load_pool()
    else:
        print("Kein Fahrerpool vorhanden – erzeuge einen temporären.", file=sys.stderr)
        teams, pool = generate_pool(max(args.riders, 40), seed=args.seed)

    riders = pool[: args.riders]
    if len(riders) < args.riders:
        print(
            f"Pool enthält nur {len(pool)} Fahrer, Feld wird entsprechend kleiner.",
            file=sys.stderr,
        )

    config = RaceConfig(
        seed=args.seed,
        name=args.name or f"{route.name} {args.seed}",
        start_interval_s=args.start_interval,
        start_order=args.start_order,
        allow_tt_bike=not args.no_tt,
        race_date=date.fromisoformat(args.date) if args.date else None,
    )

    def progress(tick: int, total: int, done: int, n: int) -> None:
        if tick:
            print(f"  … Tick {tick}/{total}, {done}/{n} im Ziel", file=sys.stderr)

    print(
        f"{route.name}: {route.distance_km:.1f} km · {route.ascent_m:.0f} hm · "
        f"Klasse {route.distance_class} · {len(route.splits)} Splits"
    )
    print(f"Feld: {len(riders)} Fahrer · Seed {args.seed}")
    result = simulate_race(route, riders, teams, config, progress=progress if args.verbose else None)

    race_id = args.id or f"{args.route}-{args.seed}"
    store.save_race(race_id, args.route, result, route=route)
    print(
        f"Gerechnet in {result.compute_seconds:.1f} s · "
        f"Telemetrie {result.telemetry.nbytes() / 1e6:.1f} MB "
        f"({result.telemetry.n_samples} Samples à {result.telemetry.sample_dt_s} s)"
    )
    print(f"Gespeichert unter {store.race_dir(race_id)}")
    print()
    _print_result(result, args.top)
    return 0


def _print_result(result, top: int) -> None:
    riders = {r.id: r for r in result.riders}
    teams = {t.id: t for t in result.teams}
    finished = sorted(
        (e for e in result.entries if e.finish_time_s is not None),
        key=lambda e: e.finish_time_s,
    )
    if not finished:
        print("Kein Fahrer im Ziel.")
        return
    best = finished[0].finish_time_s

    print(f"{'Rg':>3} {'Nr':>4}  {'Name':26s} {'Team':24s} {'Zeit':>9} {'Rückstand':>10} {'IF':>5}")
    print("-" * 88)
    for entry in finished[:top]:
        rider = riders[entry.rider_id]
        team = teams.get(rider.team_id)
        gap = entry.finish_time_s - best
        print(
            f"{entry.rank or '—':>3} {entry.bib:>4}  {rider.name:26s} "
            f"{(team.name if team else ''):24s} {hms(entry.finish_time_s):>9} "
            f"{(delta(gap) if gap else '       —'):>10} {entry.target_if:>5.2f}"
        )
    dnf = [e for e in result.entries if e.status == "DNF"]
    otl = [e for e in result.entries if e.status == "OTL"]
    print("-" * 88)
    print(
        f"Sieger: {hms(best)} · Ø {(_distance_of(result) / 1000.0) / (best / 3600.0):.1f} km/h · "
        f"Feld {len(finished)} im Ziel, {len(otl)} außerhalb Zeitlimit, {len(dnf)} DNF"
    )
    # Wer aufgegeben hat, gehört ins Protokoll – die Ausfälle sind der
    # halbe Reiz eines Ultrarennens (Abschnitt 6.5).
    for entry in sorted(dnf, key=lambda e: -(e.dnf_dist_m or 0.0)):
        rider = riders[entry.rider_id]
        print(
            f"  DNF {entry.bib:>4}  {rider.name:26s} "
            f"km {(entry.dnf_dist_m or 0.0) / 1000.0:>6.1f}  {entry.dnf_reason}"
        )


def _distance_of(result) -> float:
    # Die Zieldistanz steckt im letzten Split-Ereignis jedes Fahrers.
    for event in reversed(result.events):
        if event.type == "FINISH":
            return float(event.payload.get("dist_km", 0.0)) * 1000.0
    return 0.0


def cmd_result(args: argparse.Namespace) -> int:
    store = Store(args.data)
    result, _ = store.load_race(args.race_id)
    _print_result(result, args.top)
    return 0


def cmd_rider(args: argparse.Namespace) -> int:
    """Fahrerdetail: Plan, Ereignisse, Splitverlauf."""
    store = Store(args.data)
    result, route_id = store.load_race(args.race_id)
    # Die Strecke, auf der gefahren wurde – nicht die, die heute unter
    # dem Namen liegt. Der Streckeneditor darf sie inzwischen geändert
    # haben, und dann passten Splitnamen und Splitzeiten nicht mehr.
    route = store.race_route(args.race_id, route_id)

    entry = None
    for candidate in result.entries:
        rider = next(r for r in result.riders if r.id == candidate.rider_id)
        if candidate.bib == args.bib or (args.name and args.name.lower() in rider.name.lower()):
            entry = candidate
            break
    if entry is None:
        print(f"Kein Starter mit Nr. {args.bib} gefunden.", file=sys.stderr)
        return 2

    rider = next(r for r in result.riders if r.id == entry.rider_id)
    team = next((t for t in result.teams if t.id == rider.team_id), None)
    print(f"#{entry.bib} {rider.name} ({rider.nation}) · {team.name if team else '—'}")
    print(
        f"  {rider.age} J · {rider.height_cm:.0f} cm · {rider.weight_kg:.1f} kg · "
        f"FTP {rider.ftp_w:.0f} W ({rider.wkg:.2f} W/kg) · Archetyp {rider.archetype}"
    )
    print(
        f"  Saisonform {entry.season_form:.3f} · Tagesform {entry.day_form:.3f} · "
        f"Ziel-IF {entry.target_if:.2f} · Ergebnis {hms(entry.finish_time_s)} "
        f"(Rang {entry.rank or '—'})"
    )
    print("\n  Rennplan:")
    for note in entry.notes:
        print(f"    · {note}")

    print("\n  Splits:")
    times = result.split_times_s[entry.entry_id]
    ranks = result.split_ranks[entry.entry_id]
    prev = 0.0
    for split, t_s, rank in zip(route.splits, times, ranks, strict=True):
        if not np.isfinite(t_s):
            continue
        seg = t_s - prev
        prev = t_s
        print(
            f"    km {split.dist_m / 1000:7.1f}  {split.name:28s} {hms(t_s):>9}  "
            f"Rang {int(rank):>3}  (Teilstück {hms(seg)})"
        )

    print("\n  Ereignisse:")
    for event in result.events_for(entry.entry_id):
        if event.type in ("PLAN", "START"):
            continue
        print(f"    {hms(event.t_s):>9}  {format_event(event)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = Store(args.data)
    print("Strecken:")
    for route in store.list_routes():
        print(
            f"  {route['id']:28s} {route['name']:28s} {route['distance_km']:7.1f} km "
            f"{route['ascent_m']:6d} hm  {route['distance_class']:6s} "
            f"{route['n_climbs']} Anstiege"
        )
    races = store.list_races()
    print("\nRennen:" if races else "\nRennen: (keine)")
    for race in races:
        print(
            f"  {race['race_id']:32s} {race['route_name']:26s} "
            f"{race['n_entries']:4d} Starter  Sieger {hms(race['winner_time_s'])}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ultrasim.cli.simulate", description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"), help="Datenverzeichnis")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pool = sub.add_parser("pool", help="Fahrerpool erzeugen")
    p_pool.add_argument("--riders", type=int, default=250)
    p_pool.add_argument("--teams", type=int, default=None)
    p_pool.add_argument("--seed", type=int, default=1)
    p_pool.set_defaults(func=cmd_pool)

    p_race = sub.add_parser("race", help="Rennen rechnen")
    p_race.add_argument("route", help="Strecken-ID (siehe 'list')")
    p_race.add_argument("--riders", type=int, default=250)
    p_race.add_argument("--seed", type=int, default=42)
    p_race.add_argument("--id", default=None, help="Renn-ID (Standard: <route>-<seed>)")
    p_race.add_argument("--name", default=None)
    p_race.add_argument("--date", default=None, help="Renndatum ISO, wirkt auf die Saisonform")
    p_race.add_argument("--start-interval", type=int, default=None, help="Startintervall in s")
    p_race.add_argument("--start-order", choices=("seeded", "random", "list"), default="seeded")
    p_race.add_argument("--no-tt", action="store_true", help="Zeitfahrrad verbieten")
    p_race.add_argument("--top", type=int, default=15)
    p_race.add_argument("-v", "--verbose", action="store_true")
    p_race.set_defaults(func=cmd_race)

    p_res = sub.add_parser("result", help="Ergebnisliste eines gerechneten Rennens")
    p_res.add_argument("race_id")
    p_res.add_argument("--top", type=int, default=25)
    p_res.set_defaults(func=cmd_result)

    p_rider = sub.add_parser("rider", help="Fahrerdetail mit Plan, Splits und Ereignissen")
    p_rider.add_argument("race_id")
    p_rider.add_argument("--bib", type=int, default=1)
    p_rider.add_argument("--name", default=None)
    p_rider.set_defaults(func=cmd_rider)

    p_list = sub.add_parser("list", help="Strecken und Rennen auflisten")
    p_list.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    use_safe_console()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
