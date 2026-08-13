# Build und Release

Wie aus dem Repository eine `UltracyclingSimulator.exe` wird — und welche
Fallstricke dabei warten.

## Grundentscheidung

Der **Streckenbau läuft nicht in der EXE**, sondern vorab über den
GPX-Importer auf dem Entwicklungsrechner (Game-Design-Dokument,
Abschnitt 16). Strecken werden als gzip-JSON mit fertiger Segmentierung,
Anstiegen, Splits und Servicepunkten ins Repository eingecheckt und
mitgebündelt.

Daraus folgt: Die EXE braucht **kein Java** (kein GraphHopper), **keine
Kartendaten**, **kein Netz**. Auch im Betrieb nicht — ohne Kartenanzeige
gibt es keine Kachel-Downloads, und die beiden Frontend-Bibliotheken
liegen im Repository statt an einem CDN.

## Ein Release bauen

```bash
git tag v0.1.0
git push origin v0.1.0
```

Das löst `.github/workflows/release.yml` aus. Der Workflow läuft auf
`windows-latest` und macht in dieser Reihenfolge:

1. Abhängigkeiten installieren
2. Tests laufen lassen — ein Release aus rotem Code gibt es nicht
3. prüfen, dass Strecken im Repository liegen
4. `pyinstaller ultrasim.spec` ausführen
5. **die gebaute EXE starten und anfragen, ob sie antwortet**
6. Artefakt hochladen und bei einem `v*`-Tag ein GitHub-Release anlegen

Schritt 5 ist kein Zierrat. Ein PyInstaller-Build, der „erfolgreich"
meldet, aber beim Doppelklick sofort stirbt, ist der Normalfall bei
fehlenden versteckten Importen — und fällt sonst erst dem Nutzer auf.

Ohne Tag lässt sich der Workflow über *Actions → Release → Run workflow*
von Hand starten; dann entsteht nur ein Artefakt, kein Release.

## Lokal bauen

```bash
pip install -r requirements-dev.txt
pyinstaller ultrasim.spec --noconfirm --clean
dist/UltracyclingSimulator.exe
```

Beim ersten Start legt die EXE neben sich ein Verzeichnis
`ultrasim-daten/` an, kopiert die mitgelieferten Strecken hinein und
rechnet ein Demo-Rennen (40 Fahrer auf der kürzesten Strecke, rund fünf
Sekunden). Danach öffnet sich der Browser auf
`http://127.0.0.1:8000/`.

Optionen: `--no-browser`, `--no-demo`, `--port 8080`.

## Fallstricke

**Templates und Statisches werden nicht gefunden.**
Jinja2 und `StaticFiles` lesen zur Laufzeit von der Platte; PyInstaller
sieht diese Dateien beim Analysieren des Bytecodes nicht. Sie stehen
deshalb ausdrücklich in `datas` in `ultrasim.spec`. Symptom, wenn man es
vergisst: Der Start klappt, aber jede Seite endet in
`TemplateNotFound` oder liefert ein ungestyltes Gerippe.

**Uvicorn lädt Module über Zeichenketten.**
`uvicorn.run("modul:app")` importiert per Name — für PyInstaller
unsichtbar. Deshalb übergibt `ultrasim/app.py` das App-Objekt direkt
statt eines Importpfads, und `collect_submodules("uvicorn")` in der Spec
holt die Protokoll- und Loop-Implementierungen mit.

**Die Router-Module.**
Sie werden erst innerhalb von `create_app()` importiert (um Zirkelbezüge
zu vermeiden). Ein später, bedingter Import ist genau das, was die
statische Analyse übersieht — sie stehen deshalb in `hiddenimports`.

**SciPy nicht hereinlassen.**
Die Savitzky-Golay-Glättung ist bewusst selbst geschrieben (rund
20 Zeilen NumPy). Rutscht SciPy trotzdem über eine transitive
Abhängigkeit ins Bündel, wächst die EXE um etwa 60 MB. `excludes` in der
Spec verhindert das; nach einem Umbau der Abhängigkeiten lohnt ein Blick
auf die Dateigröße.

**Multiprocessing unter Windows.**
Ohne `multiprocessing.freeze_support()` startet ein eingefrorenes
Programm bei jedem Subprozess eine weitere Kopie seiner selbst — eine
Fork-Bombe im Zeitlupentempo. Der Aufruf steht in `ultrasim_app.py`.

**Virenscanner.**
Frisch gebaute, unsignierte PyInstaller-EXEs werden von SmartScreen und
manchen Scannern angemeckert. Das lässt sich ohne Code-Signing-Zertifikat
nicht abstellen; im Release-Text sollte ein Hinweis stehen.

**Schreibrechte.**
Das Bündelverzeichnis ist bei PyInstaller ein temporärer Ordner, der nach
dem Beenden verschwindet. Alles Geschriebene gehört deshalb nach
`ultrasim-daten/` neben die EXE. `ULTRASIM_DATA` überschreibt den Pfad,
falls die EXE in einem schreibgeschützten Verzeichnis liegt.

## Versionierung

Die Version steht an einer Stelle: `ultrasim/__init__.py` (und gespiegelt
in `pyproject.toml`). Ein Tag `vX.Y.Z` sollte dazu passen.

Umfang von v0.1.0 laut Abschnitt 16: eine Strecke, 40 generierte Fahrer,
Physik/Form/Ermüdung, Precompute mit Playback, Board, Höhenprofil,
Ergebnisliste. Keine Ereignisse, kein Schlaf, keine Verpflegung. Zweck
ist ausschließlich: einmal zuschauen können. Mitgeliefert werden drei
Strecken statt einer — je eine pro Distanzklasse, damit die
Klassenlogik (Split-Dichte, Startintervall, Abtastrate,
Servicepunkt-Abstand) auch benutzt wird und nicht nur existiert.

## Prüfliste vor einem Release

- [ ] `pytest -q` grün, `ruff check ultrasim tools tests` sauber
- [ ] `python -m ultrasim.cli.balance --runs 20` liefert plausible Zahlen
- [ ] Golden-Master unverändert oder Änderung bewusst übernommen
- [ ] Version in `ultrasim/__init__.py` und `pyproject.toml` gleich
- [ ] `data/routes/` enthält die mitgelieferten Strecken
- [ ] EXE lokal einmal gestartet, Rennen angesehen
