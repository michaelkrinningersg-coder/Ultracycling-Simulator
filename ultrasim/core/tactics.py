"""Strategiemodul Stufe 2: der Regelkreis im Rennen (Abschnitt 7.2).

Stufe 1 ist der Rennplan: Er steht vor dem Start fest und wird dann
abgefahren. Das genügt für ein Ergebnis, aber nicht für das, was
Abschnitt 7.3 „sichtbare Persönlichkeit" nennt — dafür muss ein Fahrer
*während* des Rennens auf seine Lage reagieren.

Genau die fünf Regeln aus Abschnitt 7.2:

* Glykogen unter 25 %  → Intensität senken, Zufuhr erhöhen
* Schlafdruck kritisch → Schlafstopp am nächsten Servicepunkt einplanen
* Rückstand zu groß    → Intensität erhöhen (riskant!)
* Hitze über Schwelle  → Intensität senken
* W′ unter 20 %        → an Rampen nicht mehr überziehen

Die letzte Regel steckt schon in der Physik (``fatigue.W_PRIME_GUARD``):
Sie wirkt in jedem einzelnen Tick und braucht keinen Beschluss.

Zwei Dinge machen den Unterschied zwischen einem Regelkreis und einer
Formel:

**Nicht jeder befolgt ihn gleich.** Abschnitt 7.2 endet mit dem Satz,
dass die Disziplin an Pacing-Disziplin und mentaler Widerstandsfähigkeit
hängt. Hier heißt das: Die *schützenden* Regeln wirken bei einem
disziplinierten Fahrer fast vollständig und bei einem undisziplinierten
kaum — er fährt weiter, als wäre nichts. Bei der *riskanten* Regel ist es
umgekehrt: Wer wenig Pacing-Disziplin und wenig mentale Widerstandskraft
hat, überzieht am stärksten, wenn er Zeit verloren hat. Aus derselben
Lage werden so zwei verschiedene Rennen.

**Regeln schalten mit Hysterese.** Ohne getrennte Ein- und
Ausschaltschwellen flattert eine Regel an ihrer Grenze — der Ticker
bekäme im Sekundentakt „Sparmodus an / Sparmodus aus", und die
Intensität zappelte mit. Jede Regel schaltet deshalb bei einem Wert ein
und bei einem deutlich anderen wieder aus.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class RuleSpec:
    """Eine Regel des Regelkreises.

    ``if_delta`` ist die Änderung des Intensitätsfaktors bei voller
    Befolgung. ``protective`` trennt die Regeln, die einen Fahrer retten,
    von der einen, die ihn ins Risiko treibt — sie werden von
    verschiedenen Attributen gesteuert.
    """

    key: str
    label: str
    if_delta: float
    protective: bool
    on_text: str
    off_text: str


#: Glykogen unter dieser Marke: Sparmodus an …
GLYCO_ON = 0.25
#: … und erst hier wieder aus. Der Abstand ist die Hysterese.
GLYCO_OFF = 0.35

#: Wirksame Temperatur, ab der gedrosselt wird. „Wirksam" heißt: um die
#: Hitzetoleranz verschoben, ein hitzefester Fahrer fängt später an.
HEAT_ON_C = 30.0
HEAT_OFF_C = 27.0
HEAT_TOLERANCE_SHIFT_C = 6.0

#: Anteil verlorener Zeit an der *geplanten* Renndauer, ab dem ein Fahrer
#: aufholt. Verlorene Zeit ist die ehrlichste Rückstandsgröße, die im
#: Eigenzeit-Modell zur Verfügung steht: Ein Fahrer weiß, dass ihn zwei
#: Pannen vierzig Minuten gekostet haben — die Zwischenzeit eines Rivalen
#: sieht er auf der Straße nicht.
#:
#: Bezug ist bewusst die geplante Gesamtdauer und nicht die bisher
#: verstrichene Zeit. Mit der verstrichenen Zeit löste eine 25-minütige
#: Sperrung bei km 5 sofort eine Aufholjagd über die restlichen 295 km
#: aus — die Viertelstunde ist gemessen an zehn Rennstunden aber gar kein
#: Rückstand, der ein Risiko wert wäre.
DEFICIT_ON = 0.05
DEFICIT_OFF = 0.03

#: Schlafdruck, ab dem ein Fahrer den nächsten Halt zum Schlafstopp
#: macht. Deutlich unter dem Notschlaf-Wert: Das ist der Unterschied
#: zwischen einer Entscheidung und einem Zusammenbruch.
SLEEP_ON = 1.15
SLEEP_OFF = 0.70

RULES: tuple[RuleSpec, ...] = (
    RuleSpec(
        key="sparmodus",
        label="Sparmodus",
        if_delta=-0.10,
        protective=True,
        on_text="Glykogen unter {glyco:.0f} % – Tempo raus, Zufuhr hoch",
        off_text="Speicher wieder bei {glyco:.0f} % – Sparmodus beendet",
    ),
    RuleSpec(
        key="hitze",
        label="Hitzemodus",
        if_delta=-0.06,
        protective=True,
        on_text="{temp:.0f} °C – Tempo raus, damit die Hitze nicht das Rennen entscheidet",
        off_text="{temp:.0f} °C – Hitzemodus beendet",
    ),
    RuleSpec(
        key="aufholen",
        label="Aufholjagd",
        if_delta=+0.07,
        protective=False,
        on_text="{lost:.0f} min verloren – Intensität hoch, um aufzuholen (riskant)",
        off_text="Rückstand aufgeholt – zurück auf Planintensität",
    ),
    RuleSpec(
        key="schlafplan",
        label="Schlaf geplant",
        if_delta=-0.03,
        protective=True,
        on_text="Schlafdruck {press:.0f} % – Schlafstopp am nächsten Servicepunkt",
        off_text="Ausgeschlafen – Schlafstopp nicht mehr nötig",
    ),
)

RULE_INDEX = {rule.key: i for i, rule in enumerate(RULES)}

#: Band, in dem der Regelkreis die Zielintensität bewegen darf. Ohne
#: Deckel könnten sich Regeln zu einer Intensität summieren, die der
#: Energiehaushalt nie tragen würde – und die Planung wäre umsonst.
IF_MOD_CLIP = (0.82, 1.12)


def follow_protective(pacing_disziplin: np.ndarray) -> np.ndarray:
    """Wie konsequent ein Fahrer eine schützende Regel befolgt.

    Bei 0 Pacing-Disziplin bleibt knapp die Hälfte der Korrektur übrig:
    Auch der Undisziplinierteste merkt, dass er leer ist — er zieht nur
    nicht die volle Konsequenz.
    """
    return 0.45 + 0.55 * np.clip(np.asarray(pacing_disziplin) / 100.0, 0.0, 1.0)


def follow_risky(
    pacing_disziplin: np.ndarray, mentale_widerstandsfaehigkeit: np.ndarray
) -> np.ndarray:
    """Wie stark ein Fahrer bei Rückstand überzieht.

    Umgekehrt zur schützenden Regel: Wer diszipliniert *und* mental fest
    ist, bleibt auch mit vierzig Minuten Rückstand bei seinem Plan. Wer
    beides nicht ist, tritt an — und bezahlt es später.
    """
    pacing = np.clip(np.asarray(pacing_disziplin) / 100.0, 0.0, 1.0)
    mental = np.clip(np.asarray(mentale_widerstandsfaehigkeit) / 100.0, 0.0, 1.0)
    return np.clip((1.30 - 0.65 * pacing) * (1.15 - 0.40 * mental), 0.15, 1.6)


@dataclass
class TacticsState:
    """Welche Regeln bei welchem Fahrer gerade greifen."""

    active: np.ndarray = field(default_factory=lambda: np.zeros((0, len(RULES)), dtype=bool))

    @classmethod
    def for_field(cls, n_riders: int) -> TacticsState:
        return cls(active=np.zeros((n_riders, len(RULES)), dtype=bool))

    def is_on(self, key: str) -> np.ndarray:
        return self.active[:, RULE_INDEX[key]]


def desired(
    glyco_frac: np.ndarray,
    temp_c: np.ndarray,
    heat_norm: np.ndarray,
    lost_s: np.ndarray,
    planned_s: np.ndarray,
    sleep_press: np.ndarray,
    was_on: np.ndarray,
) -> np.ndarray:
    """Sollzustand aller Regeln, mit Hysterese.

    ``was_on`` ist der bisherige Zustand: Eine laufende Regel bleibt an,
    bis der Ausschaltwert erreicht ist, eine ruhende springt erst am
    Einschaltwert an.
    """
    glyco = np.asarray(glyco_frac)
    # Minus, nicht plus: Ein hitzefester Fahrer (heat_norm > 0) erlebt
    # dieselbe Temperatur als kühler und drosselt später. Mit dem
    # falschen Vorzeichen wurde ausgerechnet der Hitzefeste zuerst
    # langsam – der Wettertest hat es gefunden, weil Hitzetoleranz
    # dadurch unterm Strich nichts mehr wert war.
    temp_eff = np.asarray(temp_c) - HEAT_TOLERANCE_SHIFT_C * np.asarray(heat_norm)
    lost_frac = np.asarray(lost_s) / np.maximum(np.asarray(planned_s), 3600.0)
    press = np.asarray(sleep_press)

    out = np.empty_like(was_on)
    out[:, RULE_INDEX["sparmodus"]] = np.where(
        was_on[:, RULE_INDEX["sparmodus"]], glyco < GLYCO_OFF, glyco < GLYCO_ON
    )
    out[:, RULE_INDEX["hitze"]] = np.where(
        was_on[:, RULE_INDEX["hitze"]], temp_eff > HEAT_OFF_C, temp_eff > HEAT_ON_C
    )
    out[:, RULE_INDEX["aufholen"]] = np.where(
        was_on[:, RULE_INDEX["aufholen"]], lost_frac > DEFICIT_OFF, lost_frac > DEFICIT_ON
    )
    out[:, RULE_INDEX["schlafplan"]] = np.where(
        was_on[:, RULE_INDEX["schlafplan"]], press > SLEEP_OFF, press > SLEEP_ON
    )
    return out


def intensity_modifier(
    active: np.ndarray, follow_protect: np.ndarray, follow_risk: np.ndarray
) -> np.ndarray:
    """Faktor auf die Zielintensität aus allen laufenden Regeln.

    Die Beiträge addieren sich, bevor der Deckel greift: Wer gleichzeitig
    leer, überhitzt und im Rückstand ist, bekommt nicht das Produkt
    dreier Faktoren — er bekommt die Summe der Entscheidungen, und die
    heben sich teilweise auf. Genau das ist auch die reale Zwickmühle.
    """
    total = np.zeros(active.shape[0], dtype=np.float64)
    for i, rule in enumerate(RULES):
        weight = follow_protect if rule.protective else follow_risk
        total = total + np.where(active[:, i], rule.if_delta * weight, 0.0)
    return np.clip(1.0 + total, *IF_MOD_CLIP)


def reason(rule: RuleSpec, on: bool, **values: float) -> str:
    """Begründung im Klartext (Abschnitt 7.3, Debug-Anforderung)."""
    template = rule.on_text if on else rule.off_text
    safe = {"glyco": 0.0, "temp": 0.0, "lost": 0.0, "press": 0.0}
    safe.update(values)
    return template.format(**safe)


__all__ = [
    "DEFICIT_ON",
    "GLYCO_ON",
    "HEAT_ON_C",
    "IF_MOD_CLIP",
    "RULES",
    "RULE_INDEX",
    "RuleSpec",
    "SLEEP_ON",
    "TacticsState",
    "desired",
    "follow_protective",
    "follow_risky",
    "intensity_modifier",
    "reason",
]
