"""Command-line entry point: ``specdash``."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser
from collections.abc import Sequence

from specdash import __version__


DEFAULT_PORT = 8050


def _is_frozen() -> bool:
    """Return whether the app runs from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


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
    from specdash.app import create_app

    args = parse_args(argv)
    app = create_app()
    port = args.port if args.port is not None else _pick_port(args.host, DEFAULT_PORT)
    debug = args.debug and not _is_frozen()  # the reloader cannot respawn a frozen app
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{port}"
    stop_hint = "close this window to quit" if _is_frozen() else "Ctrl+C to stop"
    print(f"SpecDash running at {url}  ({stop_hint})")
    if not args.no_browser and not debug:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host=args.host, port=port, debug=debug)


if __name__ == "__main__":
    main()
