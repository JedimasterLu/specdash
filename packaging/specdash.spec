# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec producing a one-folder SpecDash build.

Build from the repository root with a runtime-only environment::

    uv sync --no-dev --group build
    uv run --no-sync pyinstaller packaging/specdash.spec --noconfirm

``--no-sync`` stops ``uv run`` from re-installing the dev dependency group.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821  (SPECPATH is injected by PyInstaller)

# Packages that are installed in developer environments but never used at runtime.
EXCLUDES = [
    "tkinter",
    "_tkinter",
    "matplotlib",
    "IPython",
    "ipykernel",
    "pytest",
    "scipy",
    "pandas",
    "PIL",
    "dash.testing",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "specdash" / "assets"), "specdash/assets")],
    hiddenimports=[],
    hookspath=[str(ROOT / "packaging" / "hooks")],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,  # strip asserts and docstrings from bytecode
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SpecDash",
    console=False,  # no terminal window; output goes to a log file and the app has a Quit button
    upx=False,  # UPX increases antivirus false positives
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SpecDash",
)
