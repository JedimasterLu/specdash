"""Post-process the py2app bundle: add package metadata, remove files that are never used.

py2app copies whole packages, including tests, source maps, other platforms' libraries and
the full 4.8 MB plotly.js (SpecDash serves its own slim copy). It also omits package
metadata (``*.dist-info``), which some dependencies read at import time (plotly does).

Run after the build; ``SpecDash --selftest`` afterwards verifies nothing needed was removed::

    python packaging/postprocess_macos.py dist/SpecDash.app
"""

import shutil
import sys
from importlib import metadata
from pathlib import Path

SKIP_METADATA = {"py2app", "pip", "setuptools", "wheel", "modulegraph", "altgraph", "macholib", "specdash"}

# Glob patterns relative to Resources/lib/python3.x; matching files and directories are deleted.
PRUNE = [
    # plotly: the app serves specdash/vendor/plotly-slim.min.js; datasets belong to plotly.express.
    "plotly/package_data/plotly.min.js",
    "plotly/package_data/datasets",
    "plotly/labextension",
    "plotly/express/data",
    # dash: source maps, bundled docs, test helpers.
    "dash/testing",
    "dash/**/*.map",
    "dash/**/*.md",
    "dash/**/*.tgz",
    # matplotlib: only the Agg PNG path is used.
    "matplotlib/tests",
    "matplotlib/*/tests",
    "matplotlib/mpl-data/sample_data",
    "matplotlib/mpl-data/images",
    "matplotlib/mpl-data/fonts/afm",
    "matplotlib/mpl-data/fonts/pdfcorefonts",
    "matplotlib/backends/web_backend",
    # numpy, Pillow: test suites.
    "numpy/**/tests",
    "PIL/tests",
    # pywebview: Windows web view libraries.
    "webview/lib/*.dll",
    "webview/lib/runtimes",
    # Type stubs and markers.
    "**/*.pyi",
    "**/py.typed",
]


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def add_metadata(target: Path) -> None:
    """Copy the ``*.dist-info`` directories of all installed distributions into ``target``."""
    count = 0
    for dist in metadata.distributions():
        path = Path(str(dist._path))  # type: ignore[attr-defined]
        name = dist.metadata["Name"]
        if name and name.lower().replace("_", "-") not in SKIP_METADATA and path.suffix == ".dist-info":
            shutil.copytree(path, target / path.name, dirs_exist_ok=True)
            count += 1
    print(f"Copied metadata of {count} distributions into {target}")


def prune(target: Path) -> None:
    """Delete everything matching :data:`PRUNE` below ``target``."""
    removed = 0
    for pattern in PRUNE:
        for path in sorted(target.glob(pattern), reverse=True):
            if not path.exists() and not path.is_symlink():
                continue  # already gone with its parent
            removed += _size(path) if path.is_dir() else path.stat().st_size
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
    print(f"Removed {removed / 1e6:.1f} MB of unused files")


def main(app: str) -> None:
    libs = sorted(Path(app, "Contents", "Resources", "lib").glob("python3.*"))
    if not libs:
        raise SystemExit(f"No python lib directory found inside {app}")
    before = _size(Path(app))
    add_metadata(libs[0])
    prune(libs[0])
    print(f"{app}: {before / 1e6:.1f} MB -> {_size(Path(app)) / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1])
