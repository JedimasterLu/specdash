"""Native window (pywebview) around the local Dash server.

The Dash app renders the UI inside a pywebview window. The window adds what a
browser tab cannot do well:

* dropping or browsing for ``.asc`` files hands *paths* to Python, which reads
  and parses the files in parallel straight from disk instead of pushing every
  file through base64 uploads;
* exports are written through native "Save as" dialogs.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import webview
from webview.dom import DOMEventHandler
from werkzeug.serving import make_server

from specdash import store
from specdash.processing import Role

_FILE_TYPES = ("Spectra (*.asc;*.txt;*.csv)", "All files (*.*)")

window: webview.Window | None = None
_drop_bound = False


# --------------------------------------------------------------------------- #
# Python -> page
# --------------------------------------------------------------------------- #


def _push(payload: dict[str, Any]) -> None:
    """Hand newly loaded files to the page through the hidden ``dropped`` store."""
    if window is not None:
        window.evaluate_js(f"window.dash_clientside.set_props('dropped', {{data: {json.dumps(payload)}}})")


def ingest(role: str, paths: Sequence[str]) -> None:
    """Load files for an input slot and tell the page about them.

    Args:
        role: Input role value (``"signal"``, ``"substrate"``, ...).
        paths: File paths on disk.
    """
    if role not in {r.value for r in Role}:
        role = Role.SIGNAL.value
    items, errors = store.load_paths(paths)
    # The nonce makes repeated drops of the same files distinct store values.
    _push({"role": role, "items": items, "errors": errors, "nonce": time.time_ns(), "n": len(paths)})


# --------------------------------------------------------------------------- #
# Page -> Python
# --------------------------------------------------------------------------- #


def _on_drop(event: dict[str, Any]) -> None:
    """Handle files dropped anywhere on the window; ``assets/desktop.js`` records the slot."""
    files = (event.get("dataTransfer") or {}).get("files") or []
    paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
    if not paths or window is None:
        return
    role = window.evaluate_js("window.__dropRole") or Role.SIGNAL.value
    threading.Thread(target=ingest, args=(role, paths), daemon=True).start()


class Api:
    """Methods the page can call as ``window.pywebview.api.<name>``."""

    def browse(self, role: str) -> None:
        """Pick spectra with the native open dialog for an input slot."""
        if window is None:
            return
        open_dialog = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        picked = window.create_file_dialog(open_dialog, allow_multiple=role == Role.SIGNAL.value, file_types=_FILE_TYPES)
        if picked:
            threading.Thread(target=ingest, args=(role, list(picked)), daemon=True).start()


def save_bytes(filename: str, content: bytes) -> Path | None:
    """Ask where to save ``content`` and write it there.

    Args:
        filename: Suggested file name.
        content: File content.

    Returns:
        The chosen path, or ``None`` if the dialog was cancelled.
    """
    if window is None:
        return None
    save_dialog = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
    suffix = Path(filename).suffix
    chosen = window.create_file_dialog(
        save_dialog,
        save_filename=filename,
        file_types=(f"{suffix.lstrip('.').upper()} file (*{suffix})", "All files (*.*)"),
    )
    if not chosen:
        return None
    path = Path(chosen if isinstance(chosen, str) else chosen[0])
    if not path.suffix:
        path = path.with_suffix(suffix)
    path.write_bytes(content)
    return path


def _on_loaded() -> None:
    """Register the native drop handler once the page has loaded."""
    global _drop_bound
    if window is None or _drop_bound:
        return
    _drop_bound = True
    # prevent_default: the page must not navigate to a dropped file.
    window.dom.document.events.drop += DOMEventHandler(_on_drop, prevent_default=True)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run(debug: bool = False) -> None:
    """Start the Dash server on a free local port and open the window.

    Args:
        debug: Enable the web inspector.
    """
    global window
    from specdash.app import create_app

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app = create_app()
    server = make_server("127.0.0.1", 0, app.server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    window = webview.create_window(
        "SpecDash",
        f"http://127.0.0.1:{server.server_port}",
        js_api=Api(),
        width=1440,
        height=920,
        min_size=(1000, 640),
    )
    window.events.loaded += _on_loaded
    webview.start(debug=debug)
    server.shutdown()
