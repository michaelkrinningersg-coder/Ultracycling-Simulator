"""Fahrerentwicklung zwischen zwei Saisons (Abschnitt 14, M7).

Ohne Entwicklung ist ein Kalender nur eine Liste von Rennen. Erst wenn
der Rohdiamant nach drei Jahren tatsächlich vorne mitfährt und der
36-Jährige seine Bergwertung nicht mehr gewinnt, entsteht der Bogen, den
das Dokument mit „Langzeitmotivation" meint.

Drei Größen bewegen sich:

* **Alter** — eine Kurve mit Scheitel um 31 Jahre, dieselbe, mit der der
  Generator schon die Startwerte zieht
* **Erfahrung** — wächst mit gefahrenen Rennen und Kilometern, am
  schnellsten am Anfang
* **Potenzial** — driftet nach oben, solange ein Fahrer jung ist, und
  nach unten, wenn er alt wird; dazu eine Zufallskomponente, damit nicht
  jede Karriere gleich aussieht

Die Attribute selbst werden dabei *nicht* einzeln nachgeführt. Sie
verschieben sich nur über das Potenzial-Budget, und zwar so, dass die
Form des Fahrers erhalten bleibt: Ein Kletterer wird ein besserer oder
schlechterer Kletterer, aber kein Zeitfahrer. Genau dafür gibt es die
Budgetnormierung im Generator, die hier wiederverwendet wird.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .rider import ARCHETYPES, ATTRIBUTES, WKG_RANGE, Rider, _apply_potential_budget

#: Alter, bis zu dem ein Fahrer im Mittel dazugewinnt …
PEAK_AGE = 31.0
#: … und wie schnell. Ein 22-Jähriger legt rund 1,4 Potenzialpunkte je
#: Saison zu, ein 30-Jähriger fast nichts mehr.
GROWTH_PER_YEAR = 0.16
#: Abbau nach dem Scheitel, pro Jahr über PEAK_AGE. Bewusst steiler als
#: der Aufbau: Aufsteigen dauert, absteigen geht schnell.
DECLINE_PER_YEAR = 0.24
#: Zufällige Streuung der Entwicklung je Saison, in Potenzialpunkten.
DRIFT_SD = 0.9
#: Grenzen des Potenzial-Budgets, wie im Generator.
POTENTIAL_CLIP = (34.0, 68.0)

#: Alter, ab dem ein Fahrer zurücktreten kann …
RETIREMENT_FROM_AGE = 34
#: … und ab dem er es sicher tut.
RETIREMENT_CERTAIN_AGE = 44

#: Erfahrungsgewinn: Ein volles Saisonprogramm bringt einem Neuling rund
#: zwölf Punkte, einem Routinier kaum noch etwas.
EXPERIENCE_PER_SEASON = 14.0
EXPERIENCE_PER_10000_KM = 6.0
EXPERIENCE_CEILING = 97.0

#: Körpergewicht driftet mit dem Alter leicht nach oben.
WEIGHT_DRIFT_KG_PER_YEAR = 0.12
WEIGHT_DRIFT_FROM_AGE = 30


@dataclass
class SeasonRecord:
    """Was ein Fahrer in einer Saison zusammengefahren hat."""

    starts: int = 0
    finishes: int = 0
    wins: int = 0
    distance_km: float = 0.0
    points: float = 0.0


def potential_delta(age: int, rng: np.random.Generator) -> float:
    """Erwartete Veränderung des Potenzial-Budgets in einer Saison."""
    if age <= PEAK_AGE:
        trend = GROWTH_PER_YEAR * (PEAK_AGE - age)
    else:
        trend = -DECLINE_PER_YEAR * (age - PEAK_AGE)
    return trend + float(rng.normal(0.0, DRIFT_SD))


def experience_gain(current: float, record: SeasonRecord) -> float:
    """Erfahrungszuwachs einer Saison.

    Der Zuwachs skaliert mit dem Abstand zur Obergrenze: Die ersten
    Saisons lehren viel, die zehnte kaum noch etwas. Ohne diese Dämpfung
    hätte nach fünf Jahren jeder Fahrer im Feld 97 Erfahrung und das
    Attribut wäre bedeutungslos.
    """
    if record.starts <= 0:
        return 0.0
    room = max(EXPERIENCE_CEILING - current, 0.0) / EXPERIENCE_CEILING
    raw = EXPERIENCE_PER_SEASON * min(record.starts / 8.0, 1.5)
    raw += EXPERIENCE_PER_10000_KM * (record.distance_km / 10_000.0)
    return raw * room


def retirement_probability(age: int) -> float:
    """Rücktrittswahrscheinlichkeit nach einer Saison."""
    if age < RETIREMENT_FROM_AGE:
        return 0.0
    if age >= RETIREMENT_CERTAIN_AGE:
        return 1.0
    span = RETIREMENT_CERTAIN_AGE - RETIREMENT_FROM_AGE
    return float(min(1.0, ((age - RETIREMENT_FROM_AGE) / span) ** 1.8))


def _implied_wkg_noise(rider: Rider, potential: float) -> float:
    """Die persönliche Abweichung eines Fahrers von der Formel.

    Der Generator zieht W/kg aus einer Formel plus Rauschen. Für die
    Entwicklung darf nur die *Formel* neu ausgewertet werden — das
    Rauschen ist der Fahrer selbst und muss ihn begleiten, sonst wird aus
    dem überdurchschnittlich starken Kletterer über Nacht ein
    Durchschnittsfahrer.
    """
    return rider.wkg - _wkg_base(rider, potential)


def _wkg_base(rider: Rider, potential: float) -> float:
    arch = ARCHETYPES.get(rider.archetype)
    bias = arch.wkg_bias if arch else 0.0
    base = 4.35 + (potential - 50.0) * 0.035 + bias
    return base - 0.020 * abs(rider.age - 31) ** 1.25


def develop_rider(
    rider: Rider,
    record: SeasonRecord,
    rng: np.random.Generator,
) -> tuple[Rider, dict[str, Any]]:
    """Einen Fahrer um eine Saison altern lassen.

    Gibt den neuen Fahrer und ein Protokoll zurück. Das Protokoll ist
    nicht Zierde: Ohne Begründung ist eine Entwicklung von außen nicht
    von einem Fehler zu unterscheiden.
    """
    before_potential = rider.potential
    before_wkg = rider.wkg
    noise = _implied_wkg_noise(rider, before_potential)

    new_age = rider.age + 1
    delta = potential_delta(rider.age, rng)
    target = float(np.clip(before_potential + delta, *POTENTIAL_CLIP))

    # Erfahrung zuerst setzen, dann das Budget normieren: Sonst würde die
    # Normierung den Erfahrungsgewinn gleich wieder wegrechnen.
    attributes = dict(rider.attributes)
    gain = experience_gain(attributes.get("erfahrung", 50.0), record)
    attributes["erfahrung"] = float(
        min(EXPERIENCE_CEILING, attributes.get("erfahrung", 50.0) + gain)
    )
    attributes = _apply_potential_budget(attributes, target)

    weight = rider.weight_kg
    if new_age > WEIGHT_DRIFT_FROM_AGE:
        weight = round(weight + WEIGHT_DRIFT_KG_PER_YEAR, 1)

    grown = Rider(
        id=rider.id,
        name=rider.name,
        nation=rider.nation,
        team_id=rider.team_id,
        age=new_age,
        height_cm=rider.height_cm,
        weight_kg=weight,
        ftp_w=rider.ftp_w,
        archetype=rider.archetype,
        attributes=attributes,
        form_peak_day=int(rng.integers(120, 260)),
        gender=rider.gender,
    )
    wkg = float(np.clip(_wkg_base(grown, grown.potential) + noise, *WKG_RANGE))
    ftp = round(wkg * grown.weight_kg)
    grown.ftp_w = float(
        min(
            max(ftp, math.ceil(WKG_RANGE[0] * grown.weight_kg)),
            math.floor(WKG_RANGE[1] * grown.weight_kg),
        )
    )

    log = {
        "rider_id": rider.id,
        "name": rider.name,
        "age": new_age,
        "potential_before": round(before_potential, 2),
        "potential_after": round(grown.potential, 2),
        "wkg_before": round(before_wkg, 3),
        "wkg_after": round(grown.wkg, 3),
        "experience_gain": round(gain, 1),
        "starts": record.starts,
        "note": _describe(rider.age, grown.potential - before_potential, gain),
    }
    return grown, log


def _describe(age: int, delta: float, experience_gain: float) -> str:
    if delta >= 1.2:
        core = "deutlicher Sprung"
    elif delta >= 0.3:
        core = "Fortschritt"
    elif delta <= -1.2:
        core = "deutlicher Rückgang"
    elif delta <= -0.3:
        core = "leichter Rückgang"
    else:
        core = "gehalten"
    tail = f", Erfahrung +{experience_gain:.0f}" if experience_gain >= 0.5 else ""
    return f"{age} Jahre alt geworden, {core} ({delta:+.1f} Potenzial){tail}"


def advance_season(
    riders: list[Rider],
    records: dict[int, SeasonRecord],
    seed: int,
    allow_retirement: bool = True,
) -> tuple[list[Rider], list[Rider], list[dict[str, Any]]]:
    """Ein ganzes Feld um eine Saison altern lassen.

    Gibt (weiterfahrende Fahrer, Zurückgetretene, Protokoll) zurück.
    Ersatz für die Zurückgetretenen zu erzeugen ist Sache des Aufrufers —
    er weiß, wie groß der Pool bleiben soll und welche Teams Plätze
    frei haben.

    Der Zufallsstrom hängt an Seed und Fahrer-ID, nicht an der Position
    in der Liste. Sonst änderte sich die Entwicklung eines Fahrers, nur
    weil jemand anderes zurückgetreten ist.
    """
    active: list[Rider] = []
    retired: list[Rider] = []
    log: list[dict[str, Any]] = []

    for rider in riders:
        rng = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(rider.id, 7)))
        record = records.get(rider.id, SeasonRecord())
        grown, entry = develop_rider(rider, record, rng)
        if allow_retirement and rng.random() < retirement_probability(grown.age):
            entry["retired"] = True
            entry["note"] = f"{entry['note']} — Rücktritt"
            retired.append(grown)
        else:
            entry["retired"] = False
            active.append(grown)
        log.append(entry)

    return active, retired, log


__all__ = [
    "ATTRIBUTES",
    "DECLINE_PER_YEAR",
    "GROWTH_PER_YEAR",
    "PEAK_AGE",
    "SeasonRecord",
    "advance_season",
    "develop_rider",
    "experience_gain",
    "potential_delta",
    "retirement_probability",
]
