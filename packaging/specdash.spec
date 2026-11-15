# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec producing a one-folder SpecDash build on Windows and a ``.app`` bundle on macOS.

Build from the repository root with a runtime-only environment::

    uv sync --no-dev --group build
    uv run --no-sync pyinstaller packaging/specdash.spec --noconfirm

On macOS run ``uv run --no-sync python packaging/make_icns.py`` first (optional app icon).
``--no-sync`` stops ``uv run`` from re-installing the dev dependency group.
"""

import re
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821  (SPECPATH is injected by PyInstaller)
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

# Packages and stdlib modules that are never used at runtime (shared by all platforms).
EXCLUDES = [
    # GUI toolkits / notebooks / test tooling that may be present in developer environments.
    "tkinter",
    "_tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "ipykernel",
    "pytest",
    "scipy",
    "pandas",
    "dash.testing",
    "matplotlib.tests",
    # Stdlib parts nobody imports in a frozen app.
    "idlelib",
    "lib2to3",
    "pydoc_data",
    "turtledemo",
    "test",
    # Only the Agg backend (PNG export) is used.
    "matplotlib.backends.backend_qt",
    "matplotlib.backends.backend_qt5",
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends.backend_tkcairo",
    "matplotlib.backends.backend_gtk3",
    "matplotlib.backends.backend_gtk3agg",
    "matplotlib.backends.backend_gtk4",
    "matplotlib.backends.backend_gtk4agg",
    "matplotlib.backends.backend_wx",
    "matplotlib.backends.backend_wxagg",
    "matplotlib.backends.backend_webagg",
    "matplotlib.backends.backend_nbagg",
    "matplotlib.backends.backend_macosx",
    "matplotlib.backends.backend_pdf",
    "matplotlib.backends.backend_ps",
    "matplotlib.backends.backend_svg",
    "matplotlib.backends.backend_pgf",
    "matplotlib.backends.backend_cairo",
]

# pywebview ships one backend per platform; keep only the one that is used.
if IS_MAC:
    EXCLUDES += [
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        "webview.platforms.gtk",
        "webview.platforms.qt",
        "webview.platforms.android",
        "webview.platforms.cef",
        "clr",
        "pythonnet",
    ]
elif IS_WIN:
    EXCLUDES += [
        "webview.platforms.cocoa",
        "webview.platforms.gtk",
        "webview.platforms.qt",
        "webview.platforms.android",
        "webview.platforms.cef",
    ]

# Data files dropped from the bundle; matched against the destination path inside the bundle.
DATA_PRUNE = [
    "matplotlib/mpl-data/sample_data/*",
    "matplotlib/mpl-data/images/*",
    "matplotlib/mpl-data/fonts/afm/*",
    "matplotlib/mpl-data/fonts/pdfcorefonts/*",
    "matplotlib/backends/web_backend/*",
    "matplotlib/tests/*",
    "matplotlib/*/tests/*",
    "numpy/*/tests/*",
    "numpy/*/*/tests/*",
    "PIL/tests/*",
    "plotly/package_data/datasets/*",
    "plotly/labextension/*",
    "plotly/express/data/*",
    "**/*.pyi",
    "**/py.typed",
]
if IS_MAC:
    DATA_PRUNE += ["webview/lib/*.dll", "webview/lib/runtimes/*"]


def _pruned(dest: str) -> bool:
    dest = dest.replace("\\", "/")
    return any(fnmatch(dest, pattern) for pattern in DATA_PRUNE)


a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ROOT / "src" / "specdash" / "assets"), "specdash/assets"),
        (str(ROOT / "src" / "specdash" / "vendor"), "specdash/vendor"),
    ],
    hiddenimports=["webview.platforms.cocoa"] if IS_MAC else [],
    hookspath=[str(ROOT / "packaging" / "hooks")],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,  # strip asserts and docstrings from bytecode
)
a.datas = [entry for entry in a.datas if not _pruned(entry[0])]
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SpecDash",
    icon=None if IS_MAC else str(ROOT / "packaging" / "specdash.ico"),
    console=False,  # no terminal window; output goes to a log file
    upx=False,  # UPX increases antivirus false positives
    target_arch="arm64" if IS_MAC else None,
    # None: PyInstaller signs ad hoc on Apple silicon, which a downloaded app needs to launch.
    codesign_identity=None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SpecDash",
)

if IS_MAC:
    _icns = ROOT / "packaging" / "specdash.icns"
    _init = (ROOT / "src" / "specdash" / "__init__.py").read_text(encoding="utf-8")
    _version = re.search(r'__version__ = "([^"]+)"', _init).group(1)
    app = BUNDLE(  # noqa: F821
        coll,
        name="SpecDash.app",
        icon=str(_icns) if _icns.exists() else None,
        bundle_identifier="io.github.specdash",
        version=_version,
        info_plist={
            "CFBundleName": "SpecDash",
            "CFBundleDisplayName": "SpecDash",
            "CFBundleShortVersionString": _version,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
