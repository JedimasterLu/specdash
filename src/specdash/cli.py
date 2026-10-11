"""Command-line entry point: ``specdash``."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from collections.abc import Sequence

from specdash import __version__


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
    parser.add_argument("--port", type=int, default=8050, help="Port to listen on (default: 8050).")
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
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"SpecDash running at {url}  (Ctrl+C to stop)")
    if not args.no_browser and not args.debug:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
