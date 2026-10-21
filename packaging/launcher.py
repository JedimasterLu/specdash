"""PyInstaller entry point for the SpecDash executable."""

import sys
import traceback

from specdash.cli import log_path, main


def _report_fatal() -> None:
    """Tell the user why a windowed build died, since there is no console to show it."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(traceback.format_exc(), encoding="utf-8")
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, f"SpecDash failed to start.\nDetails: {path}", "SpecDash", 0x10)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _report_fatal()
        raise
