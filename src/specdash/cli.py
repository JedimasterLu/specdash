"""Command-line entry point: ``specdash``."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from specdash import __version__


def log_path() -> Path:
    """Return where a windowed build writes its console output."""
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "SpecDash" / "specdash.log"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "SpecDash" / "specdash.log"
    return Path.home() / ".specdash" / "specdash.log"


def _attach_log() -> None:
    """Send output to a log file when the process has no console.

    A windowed build has ``sys.stdout`` / ``sys.stderr`` set to ``None``,
    which breaks logging and Flask's startup banner.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def _unblock_bundle() -> None:
    """Strip Windows' "downloaded from the internet" mark from the bundled DLLs.

    A zip downloaded in a browser and extracted with Explorer tags every file with a
    ``Zone.Identifier`` stream. The .NET Framework then refuses to load ``Python.Runtime.dll``
    (needed by pywebview through pythonnet), which surfaces as ``Failed to resolve
    Python.Runtime.Loader.Initialize``. Removing the stream is what "Unblock" in the file
    properties does.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for dll in root.rglob("*.dll"):
        try:
            os.remove(f"{dll}:Zone.Identifier")
        except OSError:  # no mark, or a file system without streams
            pass


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list; ``None`` uses ``sys.argv``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="specdash",
        description="Desktop app for processing Andor .asc spectra.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable the web inspector (right-click > Inspect).")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)  # used by CI on built bundles
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Open the SpecDash window.

    Args:
        argv: Argument list; ``None`` uses ``sys.argv``.
    """
    _attach_log()  # before the heavy imports, some of which touch sys.stdout
    _unblock_bundle()  # before pywebview loads pythonnet
    args = parse_args(argv)
    if args.selftest:
        from specdash import selftest

        sys.exit(selftest.run())
    from specdash import desktop

    desktop.run(debug=args.debug)


if __name__ == "__main__":
    main()
