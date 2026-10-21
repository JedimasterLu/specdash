"""Command-line entry point: ``specdash``."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from specdash import __version__


DEFAULT_PORT = 8050


def _is_frozen() -> bool:
    """Return whether the app runs from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def log_path() -> Path:
    """Return where a windowed build writes its console output."""
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) / "SpecDash" if local else Path.home() / ".specdash") / "specdash.log"


def _attach_log() -> None:
    """Send output to a log file when the process has no console.

    A windowed (``console=False``) build has ``sys.stdout`` / ``sys.stderr`` set
    to ``None``, which breaks logging and Flask's startup banner.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def _pick_port(host: str, preferred: int) -> int:
    """Return ``preferred`` if it can be bound, otherwise a free OS-assigned port.

    Args:
        host: Interface to bind.
        preferred: Preferred port number.

    Returns:
        A port number that was free a moment ago.
    """
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise OSError(f"No free port available on {host}.")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list; ``None`` uses ``sys.argv``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="specdash",
        description="Launch the SpecDash web app for processing Andor .asc spectra.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1).")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Port to listen on (default: {DEFAULT_PORT}, or a free port if it is busy).",
    )
    parser.add_argument("--debug", action="store_true", help="Enable Dash debug mode with hot reload.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Start the web server.

    Args:
        argv: Argument list; ``None`` uses ``sys.argv``.
    """
    _attach_log()  # before the heavy imports, some of which touch sys.stdout
    from specdash.app import create_app

    args = parse_args(argv)
    app = create_app(quit_button=_is_frozen())
    port = args.port if args.port is not None else _pick_port(args.host, DEFAULT_PORT)
    debug = args.debug and not _is_frozen()  # the reloader cannot respawn a frozen app
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{port}"
    stop_hint = "use the Quit button to stop" if _is_frozen() else "Ctrl+C to stop"
    print(f"SpecDash running at {url}  ({stop_hint})")
    if not args.no_browser and not debug:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host=args.host, port=port, debug=debug)


if __name__ == "__main__":
    main()
