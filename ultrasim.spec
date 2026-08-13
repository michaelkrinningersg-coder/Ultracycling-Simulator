# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Beschreibung für UltraSim.

Was mit ins Bündel muss und warum:

* ``ultrasim/web/templates`` und ``ultrasim/web/static`` – Jinja2 und
  StaticFiles lesen sie zur Laufzeit von der Platte, PyInstaller findet
  sie deshalb nicht von allein.
* ``data/routes`` – Strecken sind Daten, keine Laufzeitabhängigkeit.
  Der Streckenbau läuft vorab über den GPX-Importer; die EXE braucht
  dadurch weder Java noch Kartendaten noch Netz.

Was bewusst *nicht* mitkommt: SciPy (die Savitzky-Golay-Glättung ist
selbst geschrieben, das spart rund 60 MB) und der GPX-Importer wird zwar
mitgebündelt, aber nicht benötigt – er läuft auf dem Entwicklungsrechner.
"""

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("ultrasim/web/templates", "ultrasim/web/templates"),
    ("ultrasim/web/static", "ultrasim/web/static"),
    ("data/routes", "data/routes"),
]

hiddenimports = collect_submodules("uvicorn") + [
    "ultrasim.web.routers.api",
    "ultrasim.web.routers.pages",
]

a = Analysis(
    ["ultrasim_app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["scipy", "matplotlib", "pandas", "tkinter", "PIL", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="UltracyclingSimulator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
