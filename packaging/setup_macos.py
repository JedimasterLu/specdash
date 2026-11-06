"""py2app configuration producing ``dist/SpecDash.app``.

Build from the repository root (after ``pip install . py2app``)::

    python packaging/make_icns.py          # optional: packaging/specdash.icns
    python packaging/setup_macos.py py2app
"""

from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "packaging" / "specdash.icns"

OPTIONS = {
    "argv_emulation": False,  # would interfere with the GUI event loop
    "packages": [
        "specdash",  # includes assets/
        "dash",
        "plotly",
        "flask",
        "werkzeug",
        "jinja2",
        "webview",
        "matplotlib",
        "numpy",
        "PIL",
        "certifi",
    ],
    "includes": ["objc", "Foundation", "AppKit", "WebKit", "Quartz", "PyObjCTools"],
    "excludes": ["tkinter", "IPython", "ipykernel", "pytest", "scipy", "pandas", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    "plist": {
        "CFBundleName": "SpecDash",
        "CFBundleDisplayName": "SpecDash",
        "CFBundleIdentifier": "io.github.specdash",
        "CFBundleShortVersionString": "0.0.0",  # replaced from specdash.__version__ below
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
}
if ICON.exists():
    OPTIONS["iconfile"] = str(ICON)

import re  # noqa: E402

init = (ROOT / "src" / "specdash" / "__init__.py").read_text(encoding="utf-8")
OPTIONS["plist"]["CFBundleShortVersionString"] = re.search(r'__version__ = "([^"]+)"', init).group(1)

setup(
    name="SpecDash",
    app=[str(ROOT / "packaging" / "launcher.py")],
    options={"py2app": OPTIONS},
)
