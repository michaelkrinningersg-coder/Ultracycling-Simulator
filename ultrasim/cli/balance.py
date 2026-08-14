"""Balancing-Werkzeug: Rennen im Batch rechnen und Verteilungen prüfen.

    python -m ultrasim.cli.balance --route voralpen-runde --runs 20

Das Dokument nennt als ersten zu bauenden Golden-Master-Test genau das:
200 Rennen im Batch, DNF-Quote je Klasse prüfen (Abschnitt 6.5). Dieses
Werkzeug liefert die Zahlen dafür – und dazu die Kennzahlen, an denen
man sieht, ob sich das Feld noch richtig anfühlt.

Weil die Simulation eine reine Bibliothek ohne Web-Abhängigkeit ist,
läuft das hier ohne Browser und ohne Datenbank.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from ..calibration import DNF_TARGET, DURATION_TARGET_H, duration_band
from ..core import incidents as inc
from ..core.engine import RaceConfig, simulate_race
from ..core.events import INCIDENT
from ..core.rider import generate_pool
from ..data.store import Store
from . import use_safe_console

#: Die Zielkorridore stehen in ``ultrasim.calibration`` – dort misst der
#: Kalibrierungsbericht dagegen, hier die Konsolenausgabe. Zwei Kopien
#: derselben Zahl wären genau die Sorte Fehler, die man erst bemerkt,
#: wenn die beiden Werkzeuge sich widersprechen.
__all__ = ["DNF_TARGET", "DURATION_TARGET_H", "main", "run"]


def percentile_line(label: str, values: np.ndarray, unit: str = "", scale: float = 1.0) -> str:
    if values.size == 0:
        return f"{label:28s} –"
    v = values * scale
    return (
        f"{label:28s} Ø {v.mean():8.2f}{unit}  "
        f"min {v.min():8.2f}  p25 {np.percentile(v, 25):8.2f}  "
        f"median {np.median(v):8.2f}  p75 {np.percentile(v, 75):8.2f}  max {v.max():8.2f}"
    )


def run(args: argparse.Namespace) -> int:
    store = Store(args.data)
    route = store.load_route(args.route)

    if store.pool_exists():
        teams, pool = store.load_pool()
    else:
        teams, pool = generate_pool(max(args.riders, 60), seed=args.pool_seed)
    riders = pool[: args.riders]

    print(
        f"{route.name}: {route.distance_km:.1f} km · {route.ascent_m:.0f} hm · "
        f"Klasse {route.distance_class}"
    )
    print(f"{args.runs} Rennen à {len(riders)} Fahrer, Seeds {args.seed}…{args.seed + args.runs - 1}")
    print()

    winner_times: list[float] = []
    all_times: list[float] = []
    spreads: list[float] = []
    dnf = 0
    otl = 0
    starters = 0
    rank_corr: list[float] = []
    compute: list[float] = []
    bike_changes: list[int] = []
    incidents: Counter[str] = Counter()
    incident_lost_s: Counter[str] = Counter()
    dnf_reasons: Counter[str] = Counter()
    lost_h: list[float] = []

    by_id = {r.id: r for r in riders}
    for i in range(args.runs):
        seed = args.seed + i
        result = simulate_race(route, riders, teams, RaceConfig(seed=seed))
        compute.append(result.compute_seconds)
        finished = [e for e in result.entries if e.finish_time_s is not None]
        starters += len(result.entries)
        dnf += sum(1 for e in result.entries if e.status == "DNF")
        otl += sum(1 for e in result.entries if e.status == "OTL")
        bike_changes.append(sum(1 for e in result.events if e.type == "BIKE_CHANGE"))
        for event in result.events:
            if event.type == INCIDENT:
                incidents[event.payload["typ"]] += 1
                incident_lost_s[event.payload["typ"]] += event.payload["stop_s"]
        for entry in result.entries:
            lost_h.append(entry.lost_s / 3600.0)
            if entry.status == "DNF":
                dnf_reasons[entry.dnf_reason.split(":")[0] or "unbekannt"] += 1
        if finished:
            times = np.array([e.finish_time_s for e in finished])
            winner_times.append(float(times.min()))
            all_times.extend(times.tolist())
            spreads.append(float(times.max() - times.min()))
            # Setzt sich das Potenzial durch? Rangkorrelation Potenzial/Zeit.
            pot = np.array([by_id[e.rider_id].potential for e in finished])
            rank_corr.append(
                float(np.corrcoef(_rankdata(-pot), _rankdata(times))[0, 1])
            )
        if args.verbose:
            print(f"  Seed {seed}: Sieger {winner_times[-1] / 3600:.3f} h")

    wt = np.array(winner_times)
    print(percentile_line("Siegerzeit (h)", wt, scale=1 / 3600.0))
    print(percentile_line("Siegerschnitt (km/h)", route.distance_km / (wt / 3600.0)))
    print(percentile_line("Feldschnitt (km/h)", route.distance_km / (np.array(all_times) / 3600.0)))
    print(percentile_line("Feldspanne (min)", np.array(spreads), scale=1 / 60.0))
    print(percentile_line("Rangkorrelation Potenzial", np.array(rank_corr)))
    print(percentile_line("Radwechsel je Rennen", np.array(bike_changes, dtype=float)))
    print(percentile_line("Verlorene Zeit (h)", np.array(lost_h)))
    print(percentile_line("Rechenzeit (s)", np.array(compute)))
    print()

    # --- Ereigniskatalog (Abschnitt 6.5) ----------------------------
    if incidents:
        print(
            "Zwischenfälle je Fahrer und Rennen. Die Basisrate gilt unter\n"
            "Referenzbedingungen (Asphalt, trocken, Tageslicht, ausgeruht);\n"
            "Nässe, Dunkelheit, Hitze und Müdigkeit heben sie an, deshalb liegt\n"
            "die gemessene Häufigkeit je nach Strecke und Wetter darüber:"
        )
        for typ, count in incidents.most_common():
            print(
                f"  {inc.CATALOG[typ].label:22s} {count / max(starters, 1):5.2f}/Fahrer  "
                f"Ø {incident_lost_s[typ] / max(count, 1) / 60.0:5.1f} min  "
                f"(Basis 1 pro {inc.CATALOG[typ].km_per_event:.0f} km => "
                f"{route.distance_km / inc.CATALOG[typ].km_per_event:.2f})"
            )
        print()

    # --- Abgleich mit dem Dauerband der Klasse ----------------------
    lo_h, hi_h = duration_band(route.distance_km, route.ascent_m)
    field_h = np.array(all_times) / 3600.0
    inside = float(np.mean((field_h >= lo_h) & (field_h <= hi_h))) * 100.0
    print(
        f"Erwartete Dauer ({route.distance_km:.0f} km + {route.ascent_m:.0f} hm): "
        f"{lo_h:.1f}–{hi_h:.1f} h · "
        f"Feld liegt zu {inside:.0f} % darin "
        f"(Sieger {wt.mean() / 3600:.1f} h, Letzter {field_h.max():.1f} h)"
    )
    if wt.mean() / 3600.0 < lo_h:
        print(
            "  Hinweis: Die Siegerzeit unterschreitet die erwartete Dauer. Das Band "
            "kommt aus Distanz plus Höhenmetern (100 hm rechnen wie 2,3 km) – wenn "
            "es hier nicht passt, ist entweder die Strecke ungewöhnlich oder das "
            "Balancing hat sich verschoben."
        )
    print()

    dnf_rate = dnf / max(starters, 1)
    otl_rate = otl / max(starters, 1)
    lo, hi = DNF_TARGET.get(route.distance_class, (0.05, 0.10))
    verdict = "im Zielkorridor" if lo <= dnf_rate + otl_rate <= hi else "AUSSERHALB des Korridors"
    print(
        f"Ausfälle: {dnf_rate * 100:.2f} % DNF + {otl_rate * 100:.2f} % Zeitlimit "
        f"= {(dnf_rate + otl_rate) * 100:.2f} % · Ziel für Klasse "
        f"'{route.distance_class}': {lo * 100:.0f}–{hi * 100:.0f} % · {verdict}"
    )
    for reason, count in dnf_reasons.most_common():
        print(f"    {count / max(starters, 1) * 100:5.2f} %  {reason}")
    if not lo <= dnf_rate + otl_rate <= hi:
        print(
            "  Hinweis: Der Korridor aus Abschnitt 6.5 ist eine Stufenfunktion — er\n"
            "  springt bei 400 km von 1–2 auf 4–7 % und bei 1200 km auf 8–12 %. Eine\n"
            "  Strecke am unteren Rand ihrer Klasse landet deshalb systematisch unter\n"
            "  dem Band, eine am oberen darüber. Gemessen über 480 Starts je Strecke:\n"
            "  300 km 1,2 % · 507 km 3,5 % · 1230 km 10,0 % — also 0,12, 0,21 und\n"
            "  0,28 Prozentpunkte je Rennstunde. Der Korridor selbst verlangt in\n"
            "  seiner Mitte 0,15, 0,32 und 0,28 Punkte je Stunde und ist damit nicht\n"
            "  monoton in der Dauer; mit einem einzigen Regler ist er an den\n"
            "  Klassengrenzen nicht überall gleichzeitig zu treffen."
        )
    return 0


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.float64)
    ranks[order] = np.arange(values.size, dtype=np.float64)
    return ranks


def main(argv: list[str] | None = None) -> int:
    use_safe_console()
    parser = argparse.ArgumentParser(prog="python -m ultrasim.cli.balance", description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--route", default="voralpen-runde")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--riders", type=int, default=40)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--pool-seed", type=int, default=1)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except FileNotFoundError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
