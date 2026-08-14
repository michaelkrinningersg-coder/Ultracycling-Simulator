"""Saison auf der Kommandozeile (Abschnitte 11 und 14).

    python -m ultrasim.cli.season new 2027 --races 10
    python -m ultrasim.cli.season show 2027-weltserie
    python -m ultrasim.cli.season run 2027-weltserie --all
    python -m ultrasim.cli.season close 2027-weltserie

Der Kalender-Editor sitzt im Browser; hier steht dasselbe für Batch und
Balancing zur Verfügung. Beide rufen dieselben Funktionen aus
``ultrasim.season_runner`` auf — es gibt genau einen Ablauf, nicht zwei.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .. import season_runner as runner
from ..core.season import Season
from ..data.store import Store
from . import use_safe_console


def _hms(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = int(round(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}"


# ----------------------------------------------------------------------
def cmd_new(args: argparse.Namespace) -> int:
    store = Store(args.data)
    name = args.name or "Weltserie"
    season_id = args.id or runner.slugify(f"{args.year}-{name}", fallback=str(args.year))
    if store.season_path(season_id).exists() and not args.force:
        print(f"Saison '{season_id}' gibt es schon (--force überschreibt)", file=sys.stderr)
        return 2

    season = Season(id=season_id, name=name, year=args.year)
    if args.races > 0:
        season.races = runner.suggest_calendar(store, args.year, args.races)
    store.save_season(season)
    print(f"Saison '{season_id}' angelegt: {len(season.races)} Termine")
    _print_calendar(store, season)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = Store(args.data)
    season = store.load_season(args.season)
    print(f"{season.name} ({season.year}) · {len(season.races)} Termine")
    print()
    _print_calendar(store, season)

    table = runner.standings(store, season)
    if not table:
        print("\nNoch kein Rennen gerechnet.")
        return 0
    print(f"\nGesamtwertung nach {sum(1 for r in season.races if r.computed)} Rennen:")
    print(f"{'Rg':>3} {'Fahrer':26s} {'Team':24s} {'Punkte':>7} {'S':>3} {'P':>3} {'St':>3}")
    print("-" * 74)
    for row in table[: args.top]:
        print(
            f"{row.rank:>3} {row.name:26s} {row.team_name:24s} "
            f"{row.points:>7.0f} {row.wins:>3} {row.podiums:>3} {row.starts:>3}"
        )
    return 0


def _print_calendar(store: Store, season: Season) -> None:
    coefficients = runner.coefficients(store, season)
    summaries = runner.race_summaries(store, season)
    previous: date | None = None
    print(f"{'Datum':10s} {'Pause':>6} {'Rennen':28s} {'Koeff':>6}  Stand")
    print("-" * 78)
    for calendar_race in season.sorted_races():
        gap = f"{(calendar_race.day - previous).days} T" if previous else ""
        summary = summaries.get(calendar_race.id)
        if summary is None:
            stand = "geplant" if not calendar_race.computed else "Ergebnis fehlt"
        else:
            winner = next((e for e in summary.entries if e.rank == 1), None)
            rider = (
                next((r for r in summary.riders if r.id == winner.rider_id), None)
                if winner
                else None
            )
            stand = (
                f"{rider.name if rider else '?'} in {_hms(winner.finish_time_s)}"
                if winner
                else "gerechnet"
            )
        print(
            f"{calendar_race.day.isoformat():10s} {gap:>6} {calendar_race.name[:28]:28s} "
            f"{coefficients.get(calendar_race.id, 1.0):>6.2f}  {stand}"
        )
        previous = calendar_race.day


def cmd_run(args: argparse.Namespace) -> int:
    store = Store(args.data)
    season = store.load_season(args.season)

    if args.race:
        targets = [r for r in season.sorted_races() if r.id == args.race]
        if not targets:
            print(f"Kein Termin '{args.race}'", file=sys.stderr)
            return 2
    else:
        targets = runner.pending_races(season)
        if not args.all:
            targets = targets[:1]
    if not targets:
        print("Alle Termine sind gerechnet.")
        return 0

    for calendar_race in targets:
        print(f"-> {calendar_race.day.isoformat()} {calendar_race.name} … ", end="", flush=True)
        outcome = runner.run_calendar_race(store, season, calendar_race.id)
        print(
            f"{outcome.n_entries} Starter, Sieger {_hms(outcome.winner_time_s)}, "
            f"{outcome.compute_seconds:.1f} s"
        )
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    store = Store(args.data)
    season = store.load_season(args.season)
    report = runner.close_season(store, season, seed=args.seed)
    print(
        f"{report['active']} Fahrer weiter · {len(report['retired'])} zurückgetreten · "
        f"{len(report['newcomers'])} nachgerückt"
    )
    movers = sorted(
        report["log"], key=lambda r: r["potential_after"] - r["potential_before"], reverse=True
    )
    print("\nGrößte Sprünge:")
    for row in movers[: args.top]:
        print(f"  {row['name']:26s} {row['note']}")
    print("\nGrößte Rückgänge:")
    for row in movers[-args.top :]:
        print(f"  {row['name']:26s} {row['note']}")
    return 0


# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    use_safe_console()
    parser = argparse.ArgumentParser(prog="python -m ultrasim.cli.season", description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    sub = parser.add_subparsers(dest="cmd", required=True)

    new = sub.add_parser("new", help="Saison anlegen")
    new.add_argument("year", type=int)
    new.add_argument("--name", default=None)
    new.add_argument("--id", default=None)
    new.add_argument("--races", type=int, default=10, help="Kalendervorschlag, 0 = leer")
    new.add_argument("--force", action="store_true")
    new.set_defaults(func=cmd_new)

    show = sub.add_parser("show", help="Kalender und Gesamtwertung")
    show.add_argument("season")
    show.add_argument("--top", type=int, default=20)
    show.set_defaults(func=cmd_show)

    run = sub.add_parser("run", help="Termine rechnen")
    run.add_argument("season")
    run.add_argument("--race", default=None, help="einzelner Termin")
    run.add_argument("--all", action="store_true", help="alle offenen Termine")
    run.set_defaults(func=cmd_run)

    close = sub.add_parser("close", help="Saison abschließen, Fahrer altern lassen")
    close.add_argument("season")
    close.add_argument("--seed", type=int, default=1)
    close.add_argument("--top", type=int, default=8)
    close.set_defaults(func=cmd_close)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
