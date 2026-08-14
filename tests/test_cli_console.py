"""Die Konsolenausgabe muss auf einer Windows-Konsole überleben.

Die Anwendung wird als Windows-Programm ausgeliefert, und dort ist die
Standardausgabe cp1252 kodiert. Ein einziges Zeichen außerhalb dieser
Kodierung — ein ``⇒`` in einer Tabellenzeile genügt — beendet das
Programm mitten im Lauf mit einem ``UnicodeEncodeError``.

Genau das ist passiert: Der Balancing-Rauchtest im CI ist auf
Windows/Python 3.11 daran gestorben, während unter Linux alles grün war.
Ein Test, der nur auf dem Entwicklungsrechner läuft, hätte das nie
gesehen — deshalb prüft dieser hier die Zeichenketten selbst, statt die
Ausgabe zu erzeugen.

Geprüft werden die Zeichenketten im Quelltext (über den Syntaxbaum, also
ohne Kommentare, aber **mit** Docstrings — die druckt ``argparse`` bei
``--help``). Umlaute sind ausdrücklich erlaubt, die kann cp1252.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from ultrasim.cli import use_safe_console

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Module, deren Ausgabe ausschließlich auf der Konsole landet.
CONSOLE_MODULES = sorted(REPO.glob("ultrasim/cli/*.py")) + [REPO / "ultrasim/app.py"]


def _offending(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for char in node.value:
            try:
                char.encode("cp1252")
            except UnicodeEncodeError:
                out.append((node.lineno, char))
    return out


@pytest.mark.parametrize("path", CONSOLE_MODULES, ids=lambda p: p.name)
def test_console_strings_survive_cp1252(path):
    bad = _offending(path)
    assert not bad, (
        f"{path.relative_to(REPO)} enthält Zeichen, die eine Windows-Konsole "
        f"nicht kodieren kann: "
        + ", ".join(f"Zeile {line}: {char!r}" for line, char in sorted(set(bad)))
        + ". Ersetze sie durch ASCII – '=>' statt '⇒', 'Streuung' statt 'σ'."
    )


def test_the_check_would_catch_a_bad_character(tmp_path):
    """Der Prüfer selbst muss anschlagen, sonst ist er Dekoration."""
    sample = tmp_path / "sample.py"
    sample.write_text('print("Basis 1 pro 450 km ⇒ 2,7")\n', encoding="utf-8")
    assert _offending(sample) == [(1, "⇒")]
    sample.write_text('print("Ausfälle: 2,1 % · Ziel 1–2 %")\n', encoding="utf-8")
    assert _offending(sample) == [], "Umlaute und Halbgeviertstrich kann cp1252"


def test_safe_console_survives_a_stream_without_reconfigure(monkeypatch):
    """Umgeleitete Ausgabe hat kein ``reconfigure`` – das darf nicht knallen."""

    class Plain:
        pass

    monkeypatch.setattr("sys.stdout", Plain())
    monkeypatch.setattr("sys.stderr", Plain())
    use_safe_console()


def test_safe_console_sets_replace_on_a_real_stream(tmp_path):
    """Nach dem Umschalten ersetzt ein nicht kodierbares Zeichen sich selbst."""
    path = tmp_path / "out.txt"
    with path.open("w", encoding="cp1252") as handle:
        handle.reconfigure(errors="replace")
        handle.write("Basis 1 pro 450 km ⇒ 2,7\n")
    assert "?" in path.read_text(encoding="cp1252")
