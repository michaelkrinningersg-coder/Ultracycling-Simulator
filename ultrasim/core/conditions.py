"""Zustandssystem (Game-Design-Dokument, Abschnitt 6.5).

Ereignisse haben zwei streng getrennte Wirkungsarten:

* **Sofortwirkung** — einmaliger Zeitverlust in Sekunden (Ampel, Panne,
  Radwechsel). Die steckt im Ereignis selbst, nicht hier.
* **Zustand** — ein Modifikator, der über eine Strecke oder eine Zeit
  nachwirkt (Magenprobleme, schlechter Schlaf, Sturzfolgen). Darum geht
  es in diesem Modul.

Alle aktiven Zustände eines Fahrers werden pro Tick multipliziert und
fließen als ``f_umwelt`` in die Formgleichung ein. Damit ist jedes
Ereignis ohne Sonderfall im Physikcode abbildbar — **neue Ereignisarten
sind reine Datenzeilen** im Katalog unten.

Anker in Zeit *oder* Distanz
----------------------------
Physiologische Zustände (Magen, Schlaf, Hitze) klingen über die Zeit ab —
wer steht, wird trotzdem wieder gesund. Fahrtbedingte Zustände
(Sturzfolgen, Fehlplanung, schlechteres Ersatzrad) wirken über die
Strecke: Sie enden an einem festen Kilometerpunkt, und die Telemetrie
kann sie als Balken über dem Streckenprofil anzeigen.

Bauform
-------
Zustände liegen als Arrays vor, nicht als Objektliste. Bei 250 Fahrern
über 400.000 Ticks wäre eine Python-Schleife über die aktiven Zustände
der teuerste Teil der Simulation. Stattdessen wird das Produkt aller
Modifikatoren je Fahrer über ``np.bincount`` auf Logarithmen gebildet —
ein paar Array-Operationen, unabhängig davon, wie viele Zustände gerade
laufen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

#: Größen, auf die ein Zustand wirken kann. Die Reihenfolge ist die
#: Spaltenordnung im Wirkungsarray und darf nur hinten wachsen.
CHANNELS: tuple[str, ...] = (
    "ftp",  # haltbare Leistung
    "kcal_aufnahme",  # aufnehmbare Energie je Stunde (ab M5.2)
    "abfahrtstempo",  # Kurven- und Abfahrtsgeschwindigkeit
    "crr",  # Rollwiderstand
)
CHANNEL_INDEX = {name: i for i, name in enumerate(CHANNELS)}

#: Verankerung der Dauer.
ANCHOR_TIME = 0
ANCHOR_DIST = 1

#: Abklingverhalten.
DECAY_STEP = 0  # wirkt voll und endet schlagartig
DECAY_LINEAR = 1  # Wirkung läuft linear auf 1,0 zurück


@dataclass(frozen=True)
class ConditionSpec:
    """Katalogeintrag: was ein Zustandstyp tut.

    ``effects`` sind multiplikative Modifikatoren, 1,0 = neutral.
    ``duration`` ist je nach ``anchor`` in Sekunden oder in Metern.
    """

    typ: str
    label: str
    effects: dict[str, float]
    anchor: int = ANCHOR_TIME
    decay: int = DECAY_LINEAR

    def effect_row(self) -> np.ndarray:
        row = np.ones(len(CHANNELS), dtype=np.float64)
        for name, value in self.effects.items():
            if name not in CHANNEL_INDEX:
                raise KeyError(f"Unbekannter Wirkungskanal: {name}")
            row[CHANNEL_INDEX[name]] = float(value)
        return row


#: Zustandskatalog. Die auskommentierten Einträge stehen bewusst hier
#: statt in einem späteren Commit: Sie zeigen, dass der Katalog die
#: einzige Stelle ist, die für eine neue Mechanik wachsen muss.
CATALOG: dict[str, ConditionSpec] = {
    # --- fahrtbedingt, in Distanz verankert -------------------------
    "fehlplanung": ConditionSpec(
        typ="fehlplanung",
        label="Fehlplanung",
        effects={"ftp": 0.92},
        anchor=ANCHOR_DIST,
        decay=DECAY_LINEAR,
    ),
    "sturzfolgen": ConditionSpec(
        typ="sturzfolgen",
        label="Sturzfolgen",
        effects={"ftp": 0.94, "abfahrtstempo": 0.80},
        anchor=ANCHOR_DIST,
        decay=DECAY_LINEAR,
    ),
    "ersatzrad": ConditionSpec(
        typ="ersatzrad",
        label="Ersatzrad",
        effects={"crr": 1.12},
        anchor=ANCHOR_DIST,
        decay=DECAY_STEP,
    ),
    "lichtausfall": ConditionSpec(
        typ="lichtausfall",
        label="Lichtausfall",
        effects={"abfahrtstempo": 0.85},
        anchor=ANCHOR_DIST,
        decay=DECAY_STEP,
    ),
    # --- physiologisch, in Zeit verankert ---------------------------
    "magen": ConditionSpec(
        typ="magen",
        label="Magenprobleme",
        effects={"kcal_aufnahme": 0.45, "ftp": 0.97},
        anchor=ANCHOR_TIME,
        decay=DECAY_LINEAR,
    ),
    "sitzbeschwerden": ConditionSpec(
        typ="sitzbeschwerden",
        label="Sitzbeschwerden",
        # Wundsein zwingt aus dem Sattel und kostet vor allem Leistung;
        # bergab traut sich niemand mehr, der im Sitzen Schmerzen hat.
        effects={"ftp": 0.94, "abfahrtstempo": 0.94},
        anchor=ANCHOR_TIME,
        decay=DECAY_STEP,
    ),
    "hitze": ConditionSpec(
        typ="hitze",
        label="Hitzeeinbruch",
        effects={"ftp": 0.90},
        anchor=ANCHOR_TIME,
        decay=DECAY_STEP,
    ),
    "schlafdefizit": ConditionSpec(
        typ="schlafdefizit",
        label="Schlafdefizit",
        effects={"ftp": 0.93, "abfahrtstempo": 0.88},
        anchor=ANCHOR_TIME,
        decay=DECAY_LINEAR,
    ),
    "unterversorgt": ConditionSpec(
        typ="unterversorgt",
        label="Unterversorgung",
        effects={"ftp": 0.93},
        anchor=ANCHOR_TIME,
        decay=DECAY_LINEAR,
    ),
    "moral": ConditionSpec(
        typ="moral",
        label="Moraltief",
        effects={"ftp": 0.98},
        anchor=ANCHOR_TIME,
        decay=DECAY_LINEAR,
    ),
    "verfahren": ConditionSpec(
        typ="verfahren",
        label="Verfahren",
        effects={"ftp": 0.98},
        anchor=ANCHOR_TIME,
        decay=DECAY_LINEAR,
    ),
}


@dataclass
class ConditionRecord:
    """Ein Zustand, wie er in Ergebnis und UI auftaucht.

    Führt beide Achsen mit: Der Balken über dem Höhenprofil braucht
    Kilometer, der Fahrer-Ticker braucht die Eigenzeit — auch dann, wenn
    der Zustand nur in einer der beiden verankert ist.
    """

    entry_id: int
    typ: str
    label: str
    start_t_s: float
    start_dist_m: float
    end_t_s: float | None = None
    end_dist_m: float | None = None
    strength: float = 1.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "typ": self.typ,
            "label": self.label,
            "start_t_s": round(self.start_t_s, 1),
            "start_dist_m": round(self.start_dist_m, 1),
            "end_t_s": None if self.end_t_s is None else round(self.end_t_s, 1),
            "end_dist_m": None if self.end_dist_m is None else round(self.end_dist_m, 1),
            "strength": round(self.strength, 3),
            "reason": self.reason,
        }


class ConditionStore:
    """Alle Zustände des Feldes als Arrays.

    Die Modifikatoren werden nicht bei jedem Tick neu gebildet, sondern
    nur, wenn sich etwas ändern kann: wenn ein Zustand hinzukommt,
    ausläuft oder linear abklingt. Ein Feld ganz ohne Zustände kostet
    dadurch genau nichts.
    """

    def __init__(self, n_riders: int) -> None:
        self.n_riders = n_riders
        self._entry: list[int] = []
        self._effects: list[np.ndarray] = []
        self._start: list[float] = []
        self._end: list[float] = []
        self._anchor: list[int] = []
        self._decay: list[int] = []
        self._records: list[ConditionRecord] = []
        self._index: list[int] = []  # Zeile -> Position in _records

        self._mods = np.ones((n_riders, len(CHANNELS)), dtype=np.float64)
        self._dirty = True
        self._has_linear = False
        # Arrays, die aus den Listen gebacken werden. None = neu backen.
        self._baked: tuple[np.ndarray, ...] | None = None

    # ------------------------------------------------------------------
    @property
    def records(self) -> list[ConditionRecord]:
        return self._records

    def __len__(self) -> int:
        return len(self._entry)

    @property
    def active_count(self) -> int:
        return len(self._entry)

    # ------------------------------------------------------------------
    def add(
        self,
        entry_id: int,
        spec: ConditionSpec,
        *,
        t_s: float,
        dist_m: float,
        duration: float,
        strength: float = 1.0,
        reason: str = "",
    ) -> ConditionRecord:
        """Zustand aufnehmen.

        ``duration`` ist in Sekunden (``ANCHOR_TIME``) oder in Metern
        (``ANCHOR_DIST``). ``strength`` skaliert die Wirkung: 0 = keine,
        1 = wie im Katalog, 2 = doppelte Abweichung von 1,0.
        """
        row = spec.effect_row()
        if strength != 1.0:
            row = 1.0 + (row - 1.0) * strength

        start = t_s if spec.anchor == ANCHOR_TIME else dist_m
        record = ConditionRecord(
            entry_id=entry_id,
            typ=spec.typ,
            label=spec.label,
            start_t_s=t_s,
            start_dist_m=dist_m,
            end_t_s=t_s + duration if spec.anchor == ANCHOR_TIME else None,
            end_dist_m=dist_m + duration if spec.anchor == ANCHOR_DIST else None,
            strength=strength,
            reason=reason,
        )

        self._entry.append(int(entry_id))
        self._effects.append(row)
        self._start.append(float(start))
        self._end.append(float(start + duration))
        self._anchor.append(spec.anchor)
        self._decay.append(spec.decay)
        self._records.append(record)
        self._index.append(len(self._records) - 1)

        self._baked = None
        self._dirty = True
        self._has_linear = self._has_linear or spec.decay == DECAY_LINEAR
        return record

    # ------------------------------------------------------------------
    def _bake(self) -> tuple[np.ndarray, ...]:
        if self._baked is None:
            self._baked = (
                np.asarray(self._entry, dtype=np.int64),
                np.asarray(self._effects, dtype=np.float64).reshape(-1, len(CHANNELS)),
                np.asarray(self._start, dtype=np.float64),
                np.asarray(self._end, dtype=np.float64),
                np.asarray(self._anchor, dtype=np.int64),
                np.asarray(self._decay, dtype=np.int64),
            )
        return self._baked

    def update(self, t_s: float, dist_m: np.ndarray) -> np.ndarray:
        """Modifikatoren je Fahrer und Kanal, Form ``(n_riders, n_channels)``.

        Das Produkt der Einzelwirkungen wird über die Summe ihrer
        Logarithmen gebildet: ``np.bincount`` kann summieren,
        multiplizieren kann es nicht — und ``np.multiply.at`` ist um
        Größenordnungen langsamer.
        """
        if not self._entry:
            # Wichtig: nicht einfach den letzten Stand zurückgeben. Läuft
            # der letzte Zustand aus, wären dessen Modifikatoren sonst für
            # den Rest des Rennens eingefroren – und zwar unterschiedlich,
            # je nachdem wie viele andere Fahrer gerade Zustände haben.
            if self._dirty:
                self._mods = np.ones((self.n_riders, len(CHANNELS)), dtype=np.float64)
                self._dirty = False
            return self._mods

        if not (self._dirty or self._has_linear):
            return self._mods

        entry, effects, start, end, anchor, decay = self._bake()

        # Position auf der jeweiligen Achse, je Zustand.
        now = np.where(anchor == ANCHOR_TIME, t_s, dist_m[entry])
        span = np.maximum(end - start, 1e-9)
        progress = np.clip((now - start) / span, 0.0, 1.0)
        active = (now >= start) & (now < end)

        # Linear abklingend: Wirkung läuft auf 1,0 zurück.
        fade = np.where(decay == DECAY_LINEAR, 1.0 - progress, 1.0)
        fade = np.where(active, fade, 0.0)

        factor = 1.0 + (effects - 1.0) * fade[:, None]
        logs = np.log(np.maximum(factor, 1e-6))

        out = np.zeros((self.n_riders, len(CHANNELS)), dtype=np.float64)
        for c in range(len(CHANNELS)):
            out[:, c] = np.bincount(entry, weights=logs[:, c], minlength=self.n_riders)
        np.exp(out, out=out)
        self._mods = out
        self._dirty = False
        return self._mods

    # ------------------------------------------------------------------
    def expire(self, t_s: float, dist_m: np.ndarray) -> list[ConditionRecord]:
        """Ausgelaufene Zustände entfernen und ihre Endpunkte festhalten.

        Ein in Distanz verankerter Zustand bekommt hier seine Endzeit und
        umgekehrt — sonst fehlte der UI für den Ticker oder für den
        Balken über dem Profil je eine Achse.
        """
        if not self._entry:
            return []
        entry, _, _, end, anchor, _ = self._bake()
        now = np.where(anchor == ANCHOR_TIME, t_s, dist_m[entry])
        done = np.flatnonzero(now >= end)
        if done.size == 0:
            return []

        finished: list[ConditionRecord] = []
        for row in done:
            record = self._records[self._index[row]]
            if record.end_t_s is None:
                record.end_t_s = t_s
            if record.end_dist_m is None:
                record.end_dist_m = float(dist_m[record.entry_id])
            finished.append(record)

        keep = np.ones(len(self._entry), dtype=bool)
        keep[done] = False
        self._compact(keep)
        return finished

    def close_all(self, t_s: float | np.ndarray, dist_m: np.ndarray) -> None:
        """Am Rennende offene Zustände abschließen.

        ``t_s`` darf ein Array je Fahrer sein — und sollte es auch: Ein
        Zustand endet, wenn *dieser* Fahrer fertig ist, nicht wenn der
        letzte des Feldes ankommt. Sonst trüge ein Sieger seine
        Magenprobleme in der Anzeige noch stundenlang mit sich herum.
        """
        ends = np.broadcast_to(np.asarray(t_s, dtype=np.float64), (self.n_riders,))
        for record_idx in self._index:
            record = self._records[record_idx]
            end = float(ends[record.entry_id])
            # Nicht nur füllen, sondern auch kürzen: Ein Zustand, dessen
            # geplantes Ende hinter der Zieldurchfahrt liegt, endet mit
            # dem Rennen. Ein Datensatz, der behauptet, die Magenprobleme
            # hätten noch anderthalb Stunden nach dem Ziel angehalten,
            # zwingt jede Anzeige zu einer Notkorrektur.
            record.end_t_s = end if record.end_t_s is None else min(record.end_t_s, end)
            final_dist = float(dist_m[record.entry_id])
            record.end_dist_m = (
                final_dist if record.end_dist_m is None else min(record.end_dist_m, final_dist)
            )
        self._compact(np.zeros(len(self._entry), dtype=bool))

    def _compact(self, keep: np.ndarray) -> None:
        idx = np.flatnonzero(keep).tolist()
        self._entry = [self._entry[i] for i in idx]
        self._effects = [self._effects[i] for i in idx]
        self._start = [self._start[i] for i in idx]
        self._end = [self._end[i] for i in idx]
        self._anchor = [self._anchor[i] for i in idx]
        self._decay = [self._decay[i] for i in idx]
        self._index = [self._index[i] for i in idx]
        self._baked = None
        self._dirty = True
        self._has_linear = any(d == DECAY_LINEAR for d in self._decay)


def channel(mods: np.ndarray, name: str) -> np.ndarray:
    """Eine Kanalspalte aus dem Modifikatorarray."""
    return mods[:, CHANNEL_INDEX[name]]
