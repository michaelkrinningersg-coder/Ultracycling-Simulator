"""Physikmodell (Game-Design-Dokument, Abschnitt 4).

Alle Funktionen arbeiten vektorisiert über das gesamte Feld: die
Eingaben sind Arrays der Länge ``n_riders``. Bei 250 Fahrern ist die
Feldgröße praktisch gratis – die Schleifenlänge ist die Tick-Anzahl,
nicht die Fahrerzahl (Abschnitt 8.1).
"""

from __future__ import annotations

import numpy as np

G = 9.80665
#: Antriebsstrangverluste.
DRIVETRAIN_EFFICIENCY = 0.975
#: Spezifische Gaskonstante trockener Luft.
R_SPEC = 287.058

#: Rollwiderstandsbeiwerte nach Oberfläche (Abschnitt 4.4).
CRR: dict[str, float] = {
    "asphalt_good": 0.0040,
    "asphalt_rough": 0.0055,
    "gravel": 0.0090,
    "cobbles": 0.0110,
}

#: Rauheit je Oberfläche — nicht dasselbe wie der Rollwiderstand oben.
#:
#: Der Beiwert sagt, wie viel Energie der Reifen beim Abrollen frisst.
#: Die Rauheit sagt, wie viel Energie in **Schwingung** geht: Der Reifen
#: schlägt gegen Kanten, Rad und Fahrer werden beschleunigt, und diese
#: Energie kommt nicht zurück. In der Reifenmessung heißt das Impedanz,
#: und sie ist der Grund, warum ein steinhart aufgepumpter Schmalreifen
#: auf Kopfsteinpflaster *langsamer* ist als ein weicher Breitreifen,
#: obwohl er auf glattem Asphalt gewinnt.
SURFACE_ROUGHNESS: dict[str, float] = {
    "asphalt_good": 0.0,
    "asphalt_rough": 0.5,
    "gravel": 1.0,
    "cobbles": 1.5,
}

#: Oberflächen, auf denen die Reifenwahl überhaupt eine Frage ist.
ROUGH_SURFACES = frozenset(k for k, v in SURFACE_ROUGHNESS.items() if v > 0.0)

#: Reifen als zweite Materialentscheidung neben dem Rad (Abschnitt 6.4).
#:
#: ``crr_factor`` wirkt auf den glatten Anteil, ``stiffness`` auf die
#: Impedanz. Der Schmalreifen gewinnt das eine und verliert das andere —
#: genau darin liegt die Entscheidung. ``comfort`` verschiebt, ab wann
#: der Sattel wehtut: Was den Reifen schont, schont auch den Fahrer.
#: Die Zahlen sind an Reifenmessungen angelehnt und nicht daran, eine
#: schöne Entscheidung zu erzwingen. Auf glattem Asphalt liegen zwischen
#: 25 mm hart und 32 mm weich rund 5 bis 10 % Rollwiderstand — nicht
#: mehr. Auf Kopfsteinpflaster kehrt sich das um, und zwar deutlich
#: stärker: Dort ist der Breitreifen um 30 bis 50 % besser, weil die
#: Impedanz alles andere überdeckt. Ein erster Ansatz hatte den
#: Schmalreifen auf Asphalt mit 14 % zu gut und auf Pflaster mit 10 % zu
#: wenig schlecht — die Wahl kippte damit erst bei rund 50 % Schotter,
#: also praktisch nie.
TYRES: dict[str, dict[str, float]] = {
    "schmal": {"crr_factor": 0.95, "stiffness": 1.00, "mass_kg": 0.00, "cda": 0.000, "comfort": 0.85},
    "breit": {"crr_factor": 1.03, "stiffness": 0.35, "mass_kg": 0.25, "cda": 0.002, "comfort": 1.20},
}
TYRE_NARROW = 0
TYRE_WIDE = 1
TYRE_NAMES = ("schmal", "breit")

#: Impedanzverlust je Einheit Rauheit bei steifem Reifen, als Aufschlag
#: auf den Rollwiderstandsbeiwert. Auf Kopfsteinpflaster (Rauheit 1,5)
#: sind das 0,0068 — deutlich mehr als der Grundwiderstand auf gutem
#: Asphalt, und genau das ist der Punkt: Auf schlechtem Untergrund
#: entscheidet nicht mehr das Abrollen, sondern das Durchgeschüttelt-
#: werden.
IMPEDANCE_CRR = 0.0045

#: Der Beiwert steigt mit dem Tempo: Die Walkarbeit im Reifen wächst,
#: weil dieselbe Verformung öfter je Sekunde durchlaufen wird. Grob
#: 0,0005 je 10 m/s, also bei 36 km/h rund ein Achtel Aufschlag auf
#: gutem Asphalt. Bis hierher war der Beiwert eine reine Konstante.
CRR_SPEED_PER_MS = 0.00005

#: Systemmasse, auf die sich die Impedanz bezieht, und wie stark sie
#: damit skaliert. Mehr Masse heißt mehr Schwingungsenergie bei
#: gleichem Schlag — ein schwerer Fahrer zahlt auf Schotter doppelt,
#: einmal über ``Crr · m · g`` und einmal hierüber.
CRR_LOAD_REF_KG = 80.0
CRR_LOAD_SPAN = 0.60

#: Wie stark ``oberflaechenkompetenz`` den Nachteil rauer Oberflächen
#: dämpft: ±30 %. Sie wirkt bewusst **nur** auf den Aufschlag gegenüber
#: gutem Asphalt — auf glatter Straße gibt es nichts zu können, und ein
#: Attribut, das dort etwas bewirkte, wäre ein verkappter Grundbonus.
SURFACE_SKILL_SPAN = 0.30


def rolling_crr(
    base_crr: np.ndarray,
    roughness: np.ndarray,
    tyre_crr_factor: np.ndarray,
    tyre_stiffness: np.ndarray,
    v: np.ndarray,
    mass: np.ndarray,
    surface_norm: np.ndarray | float = 0.0,
) -> np.ndarray:
    """Rollwiderstandsbeiwert aus Oberfläche, Reifen, Tempo und Last.

    Vier Beiträge, in dieser Reihenfolge:

    1. der glatte Grundwiderstand, mit dem Reifenfaktor skaliert,
    2. der Aufschlag der Oberfläche gegenüber gutem Asphalt,
    3. die Impedanz aus Rauheit × Reifensteifigkeit × Last,
    4. der Tempoterm.

    ``oberflaechenkompetenz`` greift an 2 und 3 an, also genau an dem,
    was die Oberfläche kostet. Der Tempoterm steht außerhalb: Walkarbeit
    ist Physik des Reifens, keine Frage des Könnens.
    """
    base = np.asarray(base_crr, dtype=np.float64)
    smooth = CRR["asphalt_good"] * tyre_crr_factor
    surface_excess = np.maximum(base - CRR["asphalt_good"], 0.0) * tyre_crr_factor

    load = 1.0 + CRR_LOAD_SPAN * (np.asarray(mass, dtype=np.float64) - CRR_LOAD_REF_KG) / CRR_LOAD_REF_KG
    impedance = IMPEDANCE_CRR * np.asarray(roughness) * tyre_stiffness * np.maximum(load, 0.1)

    skill = 1.0 - SURFACE_SKILL_SPAN * np.clip(np.asarray(surface_norm, dtype=np.float64), -1.0, 1.0)
    return smooth + (surface_excess + impedance) * skill + CRR_SPEED_PER_MS * np.maximum(v, 0.0)


#: Positionsfaktoren auf die Frontalfläche. CdA = k · A_frontal.
#: Kalibriert an den Richtwerten aus Abschnitt 4.4: mit A ≈ 0,257 m²
#: (180 cm / 70 kg) ergibt k=0,90 -> 0,23 (Zeitfahrposition),
#: k=1,20 -> 0,31 (Unterlenker), k=1,45 -> 0,37 (Anstieg/Oberlenker).
K_POSITION: dict[str, float] = {
    "tt": 0.90,
    "drops": 1.20,
    "climbing": 1.45,
}

#: Rad-Kenngrößen (Abschnitt 6.4).
#:
#: ``dev_min_m``/``dev_max_m`` sind die Entfaltung in Metern je
#: Kurbelumdrehung im kleinsten und größten Gang — bei 700×28 (2,10 m
#: Abrollumfang) entspricht das einer Kompaktkurbel 50/34 mit 11–34 am
#: Rennrad und 54/42 mit 11–28 am Zeitfahrrad.
#:
#: Sie ersetzen den früheren ``steep_penalty``: Der war eine Stufe von
#: 4 % ab sechs Prozent Steigung, gleich hoch bei sieben wie bei
#: fünfzehn. Aus der Entfaltung folgt stattdessen stetig, wie zäh es
#: wird — auf einer 15-%-Rampe bei 11 km/h tritt man am Rennrad 87 und
#: am Zeitfahrrad 58 Umdrehungen.
BIKES: dict[str, dict[str, float]] = {
    "road": {"mass_kg": 7.5, "cda_factor": 1.00, "dev_min_m": 2.10, "dev_max_m": 9.55},
    "tt": {"mass_kg": 9.0, "cda_factor": 0.80, "dev_min_m": 3.15, "dev_max_m": 10.31},
}
BIKE_ROAD = 0
BIKE_TT = 1
BIKE_NAMES = ("road", "tt")

#: Gepäck im supported-Betrieb: das Meiste liegt im Begleitfahrzeug.
SUPPORTED_LUGGAGE_KG = 2.0
SUPPORTED_LUGGAGE_CDA = 0.010

#: Bevorzugte Trittfrequenz. Der Fahrer wählt den Gang, der ihn hier
#: hinbringt, solange die Kassette das hergibt.
CADENCE_PREFERRED = 87.0
#: Darüber wird es zum Leerdrehen: Ab hier fällt die Leistung ab …
CADENCE_MAX = 114.0
#: … und darunter zum Mahlen, weil die Pedalkraft steigt.
CADENCE_GRIND = 70.0
#: Ganz unten geht gar nichts mehr sinnvoll.
CADENCE_FLOOR = 40.0
#: Wirkungsgradverlust bei ganz niedriger Trittfrequenz.
GRIND_LOSS = 0.10
#: Wie stark ``berg`` das dämpft. Das Design-Dokument führt beim Attribut
#: *Berg* ausdrücklich „geringerer Wirkungsgradverlust bei niedriger
#: Trittfrequenz" — gebaut war davon bis hierher nichts.
GRIND_BERG_SPAN = 0.50

#: Alte Namen, hergeleitet statt gesetzt. Sie standen als 13,9 und
#: 18,1 m/s im Code, und das Nachrechnen war die eigentliche
#: Überraschung: Im größten Gang des Rennrads sind das **87,4 und
#: 113,8 rpm** — also exakt die bevorzugte und die maximale
#: Trittfrequenz. Die Konstanten waren bereits ein Trittfrequenzmodell,
#: nur eines für genau ein Rad. Hergeleitet gelten sie jetzt auch für
#: das Zeitfahrrad, das mit 54×11 eine längere Übersetzung hat und
#: deshalb länger mittreten kann.
DOWNHILL_TAPER_START = BIKES["road"]["dev_max_m"] * CADENCE_PREFERRED / 60.0
DOWNHILL_NO_POWER = BIKES["road"]["dev_max_m"] * CADENCE_MAX / 60.0
#: Globaler Sicherheitsdeckel gegen Ausreißer.
MAX_SPEED = 23.6  # 85 km/h
#: Untergrenze für die Antriebsrechnung (P/v ist bei v -> 0 singulär).
MIN_SPEED = 1.5
#: Haftbeiwert trocken.
MU_DRY = 0.75


#: Ab dieser Höhe kostet die dünne Luft Leistung. Darunter ist der
#: Effekt kleiner als die Streuung der Tagesform, darüber wird er
#: schnell deutlich.
ALTITUDE_THRESHOLD_M = 1500.0
#: Verlust je 1000 m über der Schwelle, für einen Fahrer mit
#: durchschnittlicher Höhenanpassung. Die Literatur nennt für
#: Ausdauerleistung grob 6–8 % je 1000 m über 1500 m; 7 % liegt
#: dazwischen und trifft auf 2500 m die oft genannten 7 %.
ALTITUDE_LOSS_PER_KM = 0.07
#: Wie stark das Attribut Höhenanpassung den Verlust dämpft oder
#: verschärft. ±50 % zwischen den Enden der Skala.
ALTITUDE_SKILL_SPAN = 0.50
#: Tiefer sinkt die Leistung nicht — auf 4000 m fährt niemand mehr
#: Rennen, aber ein Modell, das ins Bodenlose läuft, ist auch keins.
ALTITUDE_FLOOR = 0.78


def altitude_factor(
    elevation_m: np.ndarray | float, altitude_norm: np.ndarray | float = 0.0
) -> np.ndarray:
    """Leistungsfaktor aus der Höhe (Attribut ``hoehenanpassung``).

    Getrennt von ``air_density``, weil es das Gegenteil bewirkt: Dünne
    Luft macht *schneller* (weniger Luftwiderstand) und gleichzeitig
    *schwächer* (weniger Sauerstoff). Bisher stand nur die erste Hälfte
    im Modell — auf 2500 m war Höhe damit ein reiner Vorteil, und das
    Attribut Höhenanpassung ohne Wirkung.
    """
    over_km = np.maximum(np.asarray(elevation_m, dtype=np.float64) - ALTITUDE_THRESHOLD_M, 0.0)
    over_km /= 1000.0
    loss = ALTITUDE_LOSS_PER_KM * over_km
    loss = loss * (1.0 - ALTITUDE_SKILL_SPAN * np.asarray(altitude_norm, dtype=np.float64))
    return np.maximum(1.0 - loss, ALTITUDE_FLOOR)


def air_density(elevation_m: np.ndarray | float, temperature_c: np.ndarray | float = 15.0) -> np.ndarray:
    """Luftdichte aus Höhe und Temperatur.

    Höhe wirkt real spürbar: auf 2000 m fährt man bei gleicher Leistung
    im Flachen messbar schneller.
    """
    ele = np.asarray(elevation_m, dtype=np.float64)
    # Barometrische Höhenformel der Standardatmosphäre.
    pressure = 101325.0 * np.power(np.maximum(1.0 - 2.25577e-5 * ele, 1e-6), 5.25588)
    kelvin = np.asarray(temperature_c, dtype=np.float64) + 273.15
    return pressure / (R_SPEC * kelvin)


def cda_for(
    frontal_area: np.ndarray,
    position_k: np.ndarray,
    bike_cda_factor: np.ndarray,
    luggage_cda: float = SUPPORTED_LUGGAGE_CDA,
) -> np.ndarray:
    """CdA aus Körpermaßen, Position, Rad und Gepäck."""
    return frontal_area * position_k * bike_cda_factor + luggage_cda


#: Spannweite der Positionsdisziplin auf den aerodynamischen Anteil.
#:
#: Stand lange bei 0,03 und war damit der Grund, warum der
#: Zeitfahr-Spezialist auf keiner Strecke gewonnen hat. Über ein
#: realistisches Feld (Attribut 20 bis 90) sind ±3 % gerade 4,3 %
#: Unterschied im Luftwiderstand und damit 1,4 % Tempo — während das
#: Attribut *Berg* über den Anstiegsaufschlag 12,7 % Leistung bewegt.
#: Ein Kanal war eine Nachkommastelle, der andere eine Ansage.
#:
#: 0,08 ist dabei nicht großzügig, sondern realistisch: Zwischen einer
#: eingefahrenen Zeitfahrposition und einer schlampigen liegen in
#: Windkanalmessungen 10 bis 15 % CdA. Die alten 4,3 % über das ganze
#: Feld waren die zu zaghafte Zahl, nicht die neuen 11,5 %.
AERO_DISCIPLINE_SPAN = 0.08


def position_k(grade: np.ndarray, flat_attr_norm: np.ndarray) -> np.ndarray:
    """Sitzposition als weiche Funktion der Steigung.

    Im Flachen und bergab wird aerodynamisch gefahren, am Anstieg
    aufrecht. Der Übergang ist gleitend, sonst springt der CdA an jeder
    Segmentgrenze. Das Attribut *Flach* wirkt als Positionsdisziplin
    (siehe ``AERO_DISCIPLINE_SPAN``).

    Dass der Bonus auch am Anstieg anliegt, ist kein Versehen: Er wirkt
    dort von selbst kaum, weil bei 15 km/h der Luftwiderstand klein ist.
    Ihn künstlich auszublenden hieße, eine Fallunterscheidung zu
    schreiben, die die Physik ohnehin erledigt.
    """
    # 0 bei <= 1 % Steigung, 1 ab 6 %.
    blend = np.clip((grade - 0.01) / 0.05, 0.0, 1.0)
    k = K_POSITION["drops"] + blend * (K_POSITION["climbing"] - K_POSITION["drops"])
    return k * (1.0 - AERO_DISCIPLINE_SPAN * flat_attr_norm)


def slope_trig(grade: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(cos, sin) des Steigungswinkels ohne Umweg über arctan.

    Mit ``grade = tan(α)`` gilt ``cos α = 1/sqrt(1+grade²)`` und
    ``sin α = grade · cos α``. Das ist nicht nur schneller, es erlaubt
    vor allem, beides einmal je Rasterpunkt vorzurechnen – die Steigung
    hängt an der Strecke, nicht am Fahrer.
    """
    cos = 1.0 / np.sqrt(1.0 + np.asarray(grade, dtype=np.float64) ** 2)
    return cos, grade * cos


def rolling_resistance(
    crr: np.ndarray, mass: np.ndarray, grade: np.ndarray, cos_slope: np.ndarray | None = None
) -> np.ndarray:
    if cos_slope is None:
        cos_slope, _ = slope_trig(grade)
    return crr * mass * G * cos_slope


def gravity_force(
    mass: np.ndarray, grade: np.ndarray, sin_slope: np.ndarray | None = None
) -> np.ndarray:
    if sin_slope is None:
        _, sin_slope = slope_trig(grade)
    return mass * G * sin_slope


def air_force(rho: np.ndarray, cda: np.ndarray, v: np.ndarray, headwind: np.ndarray | float = 0.0) -> np.ndarray:
    """Luftwiderstand. ``headwind`` ist positiv bei Gegenwind.

    Das Vorzeichen folgt der Anströmgeschwindigkeit: bei starkem
    Rückenwind, der schneller ist als der Fahrer, schiebt die Luft.
    """
    v_air = v + headwind
    return 0.5 * rho * cda * v_air * np.abs(v_air)


def cadence_rpm(
    v: np.ndarray, dev_min_m: np.ndarray, dev_max_m: np.ndarray
) -> np.ndarray:
    """Trittfrequenz im jeweils besten verfügbaren Gang.

    Der Fahrer sucht die Entfaltung, die ihn auf seine bevorzugte
    Frequenz bringt; die Kassette begrenzt ihn nach oben und unten. Erst
    dort, wo sie nicht mehr reicht, weicht die Frequenz ab — und genau
    dann kostet es etwas.
    """
    v = np.maximum(np.asarray(v, dtype=np.float64), 0.0)
    want = 60.0 * v / CADENCE_PREFERRED
    dev = np.clip(want, dev_min_m, dev_max_m)
    return 60.0 * v / np.maximum(dev, 1e-6)


def downhill_power_taper(v: np.ndarray, dev_max_m: np.ndarray | float = None) -> np.ndarray:
    """Anteil der Zielleistung, der bei hohem Tempo noch ankommt.

    Ohne diese Begrenzung werden Abfahrten unrealistisch schnell, weil
    der Fahrer bei 70 km/h weiter 250 W in die Kurbel drückt. Der Grund
    ist die Trittfrequenz: Im größten Gang ist irgendwann Schluss.
    """
    if dev_max_m is None:
        dev_max_m = BIKES["road"]["dev_max_m"]
    rpm = 60.0 * np.asarray(v, dtype=np.float64) / np.asarray(dev_max_m)
    return np.clip((CADENCE_MAX - rpm) / (CADENCE_MAX - CADENCE_PREFERRED), 0.0, 1.0)


def grind_factor(rpm: np.ndarray, berg_norm: np.ndarray | float = 0.0) -> np.ndarray:
    """Wirkungsgradverlust beim Mahlen mit zu niedriger Trittfrequenz.

    Bei gleicher Leistung und halber Frequenz steht die doppelte
    Pedalkraft an. Das kostet Wirkungsgrad und rekrutiert anaerob — den
    zweiten Teil erledigt die Engine, indem sie die Schwelle für die
    W′-Bilanz um denselben Faktor absenkt.
    """
    short = np.clip(
        (CADENCE_GRIND - np.asarray(rpm, dtype=np.float64)) / (CADENCE_GRIND - CADENCE_FLOOR),
        0.0,
        1.0,
    )
    damp = 1.0 - GRIND_BERG_SPAN * np.clip(np.asarray(berg_norm, dtype=np.float64), -1.0, 1.0)
    return 1.0 - GRIND_LOSS * short * damp


#: Wie viel enger die *engste* Kurve eines Abschnitts ist als der
#: Durchschnitt. Die Kurvigkeit ist ein Mittelwert über den Abschnitt,
#: gebremst wird aber für die engste Kehre darin: Ein Abschnitt mit
#: 250 Grad je Kilometer ist selten ein gleichmäßiger Bogen von 230 m
#: Radius, sondern meist eine Gerade und eine 180-Grad-Kehre mit 15 m.
#: Der Faktor 5 ist gegenüber diesem Extremfall noch zurückhaltend.
#:
#: Ohne ihn lag das Kurvenlimit auf allen mitgelieferten Strecken über
#: 150 km/h und hat nie gebunden — Abfahrtstechnik und
#: Risikobereitschaft waren damit messbar wirkungslos.
CORNER_TIGHTNESS = 5.0


def corner_radius_m(curviness: np.ndarray) -> np.ndarray:
    """Bremswirksamer Kurvenradius aus der Kurvigkeit in Grad je km.

    Wer sich auf 1000 m um C Grad dreht, fährt im Mittel einen Radius von
    360/(2π) · 1000/C ≈ 57296/C Metern. Maßgeblich ist aber die engste
    Kurve, nicht der Mittelwert — daher ``CORNER_TIGHTNESS``.
    """
    c = np.maximum(np.asarray(curviness, dtype=np.float64), 1.0)
    return np.clip(57296.0 / c / CORNER_TIGHTNESS, 8.0, 4000.0)


def corner_speed_limit(
    curviness: np.ndarray,
    skill_norm: np.ndarray,
    risk_norm: np.ndarray,
    mu: float = MU_DRY,
) -> np.ndarray:
    """Kurvenlimit v_max = sqrt(µ · g · r)."""
    radius = corner_radius_m(curviness)
    skill = 1.0 + 0.12 * skill_norm + 0.08 * risk_norm
    return np.minimum(np.sqrt(mu * G * radius) * skill, MAX_SPEED)


def integrate_step(
    v: np.ndarray,
    power_w: np.ndarray,
    grade: np.ndarray,
    mass: np.ndarray,
    cda: np.ndarray,
    crr: np.ndarray,
    rho: np.ndarray,
    dt: float,
    headwind: np.ndarray | float = 0.0,
    v_limit: np.ndarray | float = MAX_SPEED,
    cos_slope: np.ndarray | None = None,
    sin_slope: np.ndarray | None = None,
) -> np.ndarray:
    """Ein Euler-Schritt: neue Geschwindigkeit aus der Leistungsbilanz.

        a = (P·η/v − F_roll − F_grav − F_air) / m

    Euler statt Newton-Raphson auf die kubische Gleichung: robuster, kein
    Löser nötig, und die Trägheit ist gratis mit dabei – Antritte und
    Anstiegsübergänge werden dadurch von selbst plausibel.
    """
    v_eff = np.maximum(v, MIN_SPEED)
    f_prop = power_w * DRIVETRAIN_EFFICIENCY / v_eff
    f_resist = (
        rolling_resistance(crr, mass, grade, cos_slope)
        + gravity_force(mass, grade, sin_slope)
        + air_force(rho, cda, v, headwind)
    )
    a = (f_prop - f_resist) / mass
    # Bremsbeschleunigung begrenzen: ohne Deckel schießt ein 25-%-Segment
    # die Geschwindigkeit in einem Tick ins Negative.
    a = np.clip(a, -4.0, 4.0)
    v_new = v + a * dt

    # Geschwindigkeitsdeckel (Kurve, Sicherheit) als Bremsung, nicht als
    # harter Schnitt – sonst rollt der Fahrer nach der Kurve nicht aus.
    v_new = np.minimum(v_new, v_limit)
    return np.clip(v_new, 0.5, MAX_SPEED)


def steady_state_speed(
    power_w: np.ndarray | float,
    grade: np.ndarray | float,
    mass: np.ndarray | float,
    cda: np.ndarray | float,
    crr: np.ndarray | float,
    rho: np.ndarray | float = 1.225,
    iterations: int = 40,
) -> np.ndarray:
    """Gleichgewichtsgeschwindigkeit per Bisektion.

    Wird nicht im Tick benutzt, sondern für Abschätzungen: Rennplan,
    Radwahl und Tests. Bisektion statt Newton, weil sie garantiert
    konvergiert – die Genauigkeit reicht für eine Planungsgröße allemal.
    """
    power_w = np.asarray(power_w, dtype=np.float64)
    lo = np.full_like(power_w, 0.05, dtype=np.float64)
    hi = np.full_like(power_w, MAX_SPEED * 1.5, dtype=np.float64)
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        resist = (
            rolling_resistance(np.asarray(crr), np.asarray(mass), np.asarray(grade))
            + gravity_force(np.asarray(mass), np.asarray(grade))
            + air_force(np.asarray(rho), np.asarray(cda), mid)
        )
        need = resist * mid / DRIVETRAIN_EFFICIENCY
        too_slow = need < power_w
        lo = np.where(too_slow, mid, lo)
        hi = np.where(too_slow, hi, mid)
    return 0.5 * (lo + hi)
