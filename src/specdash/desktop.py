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
import os
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import webview
from webview.dom import _dnd_state
from werkzeug.serving import make_server

from specdash import store
from specdash.processing import Role

_FILE_TYPES = ("Spectra (*.asc;*.txt;*.csv)", "All files (*.*)")

window: webview.Window | None = None
_drop_bound = False

_TRACE = bool(os.environ.get("SPECDASH_TRACE"))
"""Set ``SPECDASH_TRACE=1`` to print when each step of a file load happens (wall-clock ms)."""


def _trace(step: str) -> None:
    """Print a timestamp for ``step`` when tracing is on."""
    if _TRACE:
        print(f"[trace] {time.time() * 1000 % 1_000_000:10.0f} ms  {step}", flush=True)


# --------------------------------------------------------------------------- #
# Python -> page
# --------------------------------------------------------------------------- #


def _js(code: str) -> None:
    """Run a statement in the page, if the window exists."""
    if window is not None:
        window.evaluate_js(code)


def _push(payload: dict[str, Any]) -> None:
    """Hand newly loaded files to the page through the hidden ``dropped`` store.

    The loading dialog is told first to wait for the plot redraw that follows, so
    it cannot miss the redraw by closing too early. When nothing was loaded the
    plots stay as they are, so the dialog just closes.
    """
    finish = "rendering" if payload["items"] else "done"
    _js(
        f"window.__busy && window.__busy.{finish}();"
        f"window.dash_clientside.set_props('dropped', {{data: {json.dumps(payload)}}})"
    )


def ingest(role: str, paths: Sequence[str]) -> None:
    """Load files for an input slot and tell the page about them.

    Args:
        role: Input role value (``"signal"``, ``"substrate"``, ...).
        paths: File paths on disk.
    """
    if role not in {r.value for r in Role}:
        role = Role.SIGNAL.value
    count = len(paths)
    _trace(f"ingest start ({count} files)")
    _js(f"window.__busy && window.__busy.show({json.dumps(f'Reading {count} file' + ('s' if count != 1 else '') + '…')})")
    _trace("busy dialog told to show")
    try:
        items, errors = store.load_paths(paths)
        _trace("files parsed")
        # The nonce makes repeated drops of the same files distinct store values.
        _push({"role": role, "items": items, "errors": errors, "nonce": time.time_ns(), "n": count})
        _trace("pushed to page")
        if _TRACE and window is not None:
            _trace(f"page stamps (drop/shown/painted, epoch ms): {window.evaluate_js('JSON.stringify(window.__busyTrace)')}")
    except Exception:
        _js("window.__busy && window.__busy.done()")
        raise


# --------------------------------------------------------------------------- #
# Page -> Python
# --------------------------------------------------------------------------- #


def _resolve_dropped(names: Sequence[str]) -> list[str]:
    """Turn dropped file names into full paths using the paths pywebview's native layer recorded.

    pywebview's own drop handler would do this too, but it first serializes the whole DOM
    reachable from the drop event (``target``, ``currentTarget``, ...) to JSON. With many
    plot traces on screen that took seconds, so the page sends just the file names instead.
    """
    recorded: list[tuple[str, str]] = _dnd_state["paths"]
    paths = []
    for name in names:
        match = next((item for item in recorded if unquote(item[0]) == name), None)
        if match is not None:
            recorded.remove(match)
            paths.append(unquote(match[1]))
    return paths


class Api:
    """Methods the page can call as ``window.pywebview.api.<name>``."""

    def dropped(self, role: str | None, names: list[str]) -> None:
        """Load files dropped on the window; ``assets/desktop.js`` passes the zone and the file names."""
        _trace("python received drop")
        paths = _resolve_dropped(names)
        if not paths:
            _js("window.__busy && window.__busy.cancel()")  # the page showed its dialog on the drop
            return
        threading.Thread(target=ingest, args=(role or Role.SIGNAL.value, paths), daemon=True).start()

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
    """Make pywebview's native layer record the paths of dropped files, once the page has loaded."""
    global _drop_bound
    if window is None or _drop_bound:
        return
    _drop_bound = True
    # The native layer only records paths while some drop listener exists. A listener on an element
    # that never receives drops keeps that on without pywebview ever serializing a drop event.
    sentinel = window.dom.create_element("<div hidden></div>")
    sentinel.events.drop += lambda event: None


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
