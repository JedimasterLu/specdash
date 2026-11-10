"""Server-side registry of parsed spectra and fast multi-file loading.

Parsed spectra stay in this process; the browser only keeps small descriptors
(id, name, row count, wavelength range) in ``dcc.Store`` components.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from specdash.io import AndorSpectrum, read_asc

SPECTRA: dict[str, AndorSpectrum] = {}

MAX_WORKERS = min(8, (os.cpu_count() or 2))


def register(spectrum: AndorSpectrum) -> dict[str, Any]:
    """Keep ``spectrum`` in memory and return its descriptor for a ``dcc.Store``.

    Args:
        spectrum: The parsed spectrum.

    Returns:
        A small JSON-serializable descriptor.
    """
    key = uuid.uuid4().hex
    SPECTRA[key] = spectrum
    wl = spectrum.wavelength
    return {"id": key, "name": spectrum.name, "n_rows": spectrum.n_rows, "wl": [float(wl[0]), float(wl[-1])]}


def discard(items: list[dict[str, Any]] | None) -> None:
    """Free the spectra behind descriptors that were removed from the UI."""
    for item in items or []:
        SPECTRA.pop(item["id"], None)


def get(items: list[dict[str, Any]] | None) -> list[AndorSpectrum]:
    """Look up the spectra behind a list of descriptors."""
    return [SPECTRA[item["id"]] for item in items or [] if item["id"] in SPECTRA]


def _read(path: str) -> AndorSpectrum | str:
    """Read one file, returning the spectrum or an error message."""
    try:
        return read_asc(path)
    except (OSError, ValueError) as exc:
        return f"{Path(path).name}: {exc}"


def load_paths(paths: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Read and register several files, parsing them in parallel.

    Args:
        paths: File paths on disk.

    Returns:
        Descriptors of the loaded files, in the order given, and error messages
        for the files that could not be read.
    """
    paths = list(paths)
    if len(paths) > 1:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(paths))) as pool:
            results = list(pool.map(_read, paths))
    else:
        results = [_read(p) for p in paths]
    items = [register(r) for r in results if not isinstance(r, str)]
    errors = [r for r in results if isinstance(r, str)]
    return items, errors
