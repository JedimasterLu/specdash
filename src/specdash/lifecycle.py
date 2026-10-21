"""Stop the server once every browser tab showing the app has been closed.

Needed for the windowed Windows build, which has no console that could be closed.
Pages register through ``assets/heartbeat.js``: a ping every few seconds, plus a
beacon when the tab is closed or reloaded.
"""

from __future__ import annotations

import os
import threading
import time

from flask import Flask, request

POLL_SECONDS = 1.0
CLOSE_GRACE_SECONDS = 3.0
"""Wait after the last tab says goodbye, so a reload can register again."""
STALE_SECONDS = 600.0
"""Forget a tab that has not pinged for this long (browser killed, machine asleep)."""
STARTUP_SECONDS = 180.0
"""Exit if no page ever connects within this time after start."""


class TabWatchdog:
    """Track open tabs and exit the process when none are left."""

    def __init__(self) -> None:
        self._tabs: dict[str, float] = {}
        self._started = time.monotonic()
        self._emptied_at: float | None = None
        self._seen_any = False
        self._lock = threading.Lock()

    def ping(self, tab: str) -> None:
        """Record that ``tab`` is open."""
        with self._lock:
            self._tabs[tab] = time.monotonic()
            self._seen_any = True
            self._emptied_at = None

    def bye(self, tab: str) -> None:
        """Record that ``tab`` was closed."""
        with self._lock:
            self._tabs.pop(tab, None)
            if self._seen_any and not self._tabs:
                self._emptied_at = time.monotonic()

    def should_exit(self) -> bool:
        """Return whether the app has been without a page long enough to stop."""
        now = time.monotonic()
        with self._lock:
            self._tabs = {t: seen for t, seen in self._tabs.items() if now - seen < STALE_SECONDS}
            if not self._seen_any:
                return now - self._started > STARTUP_SECONDS
            if self._tabs:
                return False
            if self._emptied_at is None:
                self._emptied_at = now
            return now - self._emptied_at > CLOSE_GRACE_SECONDS

    def run(self) -> None:
        """Poll until the app should stop, then exit the process."""
        while not self.should_exit():
            time.sleep(POLL_SECONDS)
        os._exit(0)


def install(server: Flask) -> None:
    """Add the heartbeat endpoints to ``server`` and start the watchdog thread.

    Args:
        server: The Flask server behind the Dash app.
    """
    watchdog = TabWatchdog()

    @server.post("/_specdash/ping")
    def ping() -> tuple[str, int]:
        watchdog.ping(request.get_data(as_text=True))
        return "", 204

    @server.post("/_specdash/bye")
    def bye() -> tuple[str, int]:
        watchdog.bye(request.get_data(as_text=True))
        return "", 204

    threading.Thread(target=watchdog.run, daemon=True).start()
