"""Kommandozeilenwerkzeuge.

Auf einer deutschen Windows-Konsole ist die Standardausgabe cp1252
kodiert, und ein einziges Zeichen außerhalb dieser Kodierung beendet das
Programm mit einem ``UnicodeEncodeError``. Das ist keine Theorie: Genau
daran ist der Balancing-Rauchtest im CI gescheitert — an einem
Doppelpfeil in einer Tabellenzeile, mitten in einer sonst fehlerfreien
Ausgabe. Und die Anwendung wird als Windows-Programm ausgeliefert.

Dagegen zwei Maßnahmen, die sich ergänzen. Die gedruckten Zeichenketten
kommen ohne Sonderzeichen aus, die cp1252 nicht kennt; ein Test hält das
fest. Zusätzlich schaltet ``use_safe_console`` die Ausgabe auf
``errors="replace"``, damit aus einem künftigen Ausrutscher ein
Fragezeichen wird und kein Absturz.

Warum nicht einfach auf UTF-8 umschalten? Weil die Konsole dann zwar
alles annimmt, aber Umlaute als Buchstabensalat anzeigt. Ein ``?`` an
einer Stelle ist besser als ``Ã¼`` an allen.
"""

from __future__ import annotations

import sys

__all__ = ["use_safe_console"]


def use_safe_console() -> None:
    """Macht die Ausgabe unempfindlich gegen nicht kodierbare Zeichen."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # umgeleitete Ausgabe, etwa im Test
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):  # pragma: no cover - defensive
            pass
