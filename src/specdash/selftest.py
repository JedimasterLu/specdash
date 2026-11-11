"""Headless sanity check of an installed or bundled build (``specdash --selftest``).

Verifies that the Dash app builds and serves every script it references, that a
spectrum can be parsed and processed, and that matplotlib can render both PNG exports.
"""

from __future__ import annotations

import re
import sys
import traceback

from specdash.io import parse_asc
from specdash.processing import MODES, Options, Role, process


def _check() -> None:
    from specdash import mplexport
    from specdash.app import PLOTLY_URL, create_app

    app = create_app()
    client = app.server.test_client()
    html = client.get("/").get_data(as_text=True)
    urls = re.findall(r'(?:src|href)="(/(?:_dash-component-suites|assets)/[^"]+)"', html)
    if len(urls) < 5:
        raise RuntimeError(f"page references only {len(urls)} assets; bundle looks incomplete")
    lazy = ["/_dash-layout", "/_dash-dependencies"]
    plotly = client.get(PLOTLY_URL)
    if plotly.status_code != 200 or not 0.5e6 < len(plotly.data) < 2e6:
        raise RuntimeError("the slim plotly.js bundle is not served")
    for url in [*urls, *lazy]:
        status = client.get(url).status_code
        if status != 200:
            raise RuntimeError(f"{url} returned {status}")

    text = "\n".join(f"{400 + i},{i},{2 * i},{3 * i}," for i in range(60)) + "\n\nExposure Time (secs): 1\n"
    spectrum = parse_asc(text, "test.asc")
    result = process(MODES["pl"], [spectrum], {Role.SUBSTRATE: None}, Options(quantity="raw"))
    from specdash.figures import result_figure, rows_figure

    result_figure(result, [spectrum.name])
    rows_figure(spectrum, (1, 2), spectrum.n_rows)
    for png in (
        mplexport.result_png(result, [spectrum.name]),
        mplexport.rows_png(spectrum.wavelength, spectrum.frames, (1, 2)),
    ):
        if not png.startswith(b"\x89PNG"):
            raise RuntimeError("PNG export did not produce a PNG")

    import webview  # noqa: F401  (import only; opening a window needs a display)

    if sys.platform == "win32":
        # pywebview drives WinForms through pythonnet; loading the .NET runtime here catches a
        # bundle that is missing Python.Runtime.dll or cannot start the CLR (needs no display).
        import clr  # noqa: F401


def run() -> int:
    """Run the checks, printing the outcome.

    Returns:
        Process exit code: 0 on success.
    """
    try:
        _check()
    except Exception:
        print("SELFTEST FAILED")
        traceback.print_exc()
        return 1
    print("SELFTEST OK")
    return 0
