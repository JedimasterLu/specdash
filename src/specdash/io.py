"""Reading Andor Solis ``.asc`` exports.

An Andor ``.asc`` file exported from Solis consists of a comma-separated data
block followed by a blank-line-separated metadata footer of ``key: value``
lines. Each data row holds a wavelength followed by one count value per
detector row (image readout) or a single value (full vertical binning).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

_META_PATTERN = re.compile(r"^([^:]+?):\s*(.*)$")


@dataclass
class AndorSpectrum:
    """A spectrum parsed from an Andor ``.asc`` file.

    Attributes:
        name: Display name, usually the source file name.
        wavelength: Wavelength axis in nm, shape ``(n_pixels,)``.
        frames: Raw counts, shape ``(n_pixels, n_rows)``; one column per
            detector row.
        metadata: Raw ``key -> value`` strings from the file footer.
    """

    name: str
    wavelength: FloatArray
    frames: FloatArray
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def n_rows(self) -> int:
        """Number of detector rows stored in the file."""
        return int(self.frames.shape[1])

    @property
    def exposure_time(self) -> float | None:
        """Exposure time per acquisition in seconds, if present."""
        return _to_float(self.metadata.get("Exposure Time (secs)"))

    @property
    def accumulations(self) -> int:
        """Number of accumulations summed into the data (1 for single scans)."""
        value = _to_float(self.metadata.get("Number of Accumulations"))
        if value is None or self.metadata.get("Acquisition Mode", "").strip() != "Accumulate":
            return 1
        return max(int(value), 1)

    def counts(self, rows: tuple[int, int] | None = None) -> FloatArray:
        """Return counts averaged over a range of detector rows.

        Args:
            rows: Inclusive ``(first, last)`` zero-based row indices. ``None``
                averages over all rows. Indices are clipped to the valid range.

        Returns:
            Row-averaged counts, shape ``(n_pixels,)``.
        """
        cache: dict[Any, FloatArray] = self.__dict__.setdefault("_counts_cache", {})
        if rows not in cache:
            if rows is None:
                mean = self.frames.mean(axis=1)
            else:
                first = int(np.clip(rows[0], 0, self.n_rows - 1))
                last = int(np.clip(rows[1], first, self.n_rows - 1))
                mean = self.frames[:, first : last + 1].mean(axis=1)
            mean.setflags(write=False)
            cache[rows] = mean
        return cache[rows]

    def rate(
        self,
        rows: tuple[int, int] | None = None,
        per_second: bool = True,
        per_accumulation: bool = True,
    ) -> FloatArray:
        """Return row-averaged counts normalized by acquisition time.

        Args:
            rows: Inclusive detector row range; see :meth:`counts`.
            per_second: Divide by the exposure time (counts/s).
            per_accumulation: Divide by the number of accumulations.

        Returns:
            Normalized intensity, shape ``(n_pixels,)``.

        Raises:
            ValueError: If ``per_second`` is requested but the file has no
                exposure time.
        """
        data = self.counts(rows)
        if per_second:
            exposure = self.exposure_time
            if not exposure:
                raise ValueError(f"{self.name}: exposure time not found in file metadata.")
            data = data / exposure
        if per_accumulation:
            data = data / self.accumulations
        return data

    def display_image(self, max_columns: int) -> tuple[FloatArray, FloatArray, float, float]:
        """Return the detector image prepared for display, computed once per spectrum.

        The spectral axis is block-averaged down to ``max_columns`` and the contrast
        limits are the 1st and 99th percentile of the raw image, so dragging a row
        selection does not recompute either.

        Args:
            max_columns: Upper bound on the number of output columns.

        Returns:
            Wavelength per column, intensities of shape ``(n_rows, n_columns)``,
            and the lower and upper contrast limits.
        """
        cache: dict[int, tuple[FloatArray, FloatArray, float, float]] = self.__dict__.setdefault("_image_cache", {})
        if max_columns not in cache:
            image = self.frames.T
            low, high = np.percentile(image, [1, 99])
            step = -(-self.wavelength.size // max_columns)
            if step <= 1:
                x, z = self.wavelength, image
            else:
                edges = np.arange(0, self.wavelength.size, step)
                sizes = np.diff(np.append(edges, self.wavelength.size))
                x = np.add.reduceat(self.wavelength, edges) / sizes
                z = np.add.reduceat(image, edges, axis=1) / sizes
            cache[max_columns] = (x, z, float(low), float(high))
        return cache[max_columns]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "wavelength": self.wavelength.tolist(),
            "frames": self.frames.tolist(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AndorSpectrum:
        """Deserialize from :meth:`to_dict` output.

        Args:
            data: Dictionary produced by :meth:`to_dict`.

        Returns:
            The reconstructed spectrum.
        """
        return cls(
            name=str(data["name"]),
            wavelength=np.asarray(data["wavelength"], dtype=np.float64),
            frames=np.asarray(data["frames"], dtype=np.float64).reshape(len(data["wavelength"]), -1),
            metadata=dict(data.get("metadata", {})),
        )


def _to_float(value: str | None) -> float | None:
    """Convert a metadata string to float, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


EDGE_ROW_RATIO = 5.0
"""An edge row whose mean exceeds the interior rows' mean by this factor is dropped."""


def _trim_edge_rows(frames: FloatArray) -> tuple[FloatArray, list[str]]:
    """Drop first / last detector rows that are far brighter than the rest.

    Edge rows of a CCD image are often saturated or hold readout artifacts.

    Args:
        frames: Raw counts, shape ``(n_pixels, n_rows)``.

    Returns:
        The trimmed frames and which edges (``"first"`` / ``"last"``) were dropped.
    """
    if frames.shape[1] < 3:
        return frames, []
    means = frames.mean(axis=0)
    interior = means[1:-1].mean()
    if interior <= 0:
        return frames, []
    dropped = []
    first = int(means[0] > EDGE_ROW_RATIO * interior)
    last = int(means[-1] > EDGE_ROW_RATIO * interior)
    if first:
        dropped.append("first")
    if last:
        dropped.append("last")
    return frames[:, first : frames.shape[1] - last], dropped


_NUMERIC_START = frozenset("0123456789+-.")


def _slow_block(lines: list[str]) -> list[list[float]]:
    """Parse a data block line by line, tolerating ragged or partly non-numeric rows.

    Args:
        lines: Stripped candidate data lines.

    Returns:
        The rows that consist of at least two numbers, up to the first non-numeric line after them.
    """
    rows: list[list[float]] = []
    for line in lines:
        parts = [p for p in re.split(r"[,\t;]", line) if p.strip()]
        try:
            values = [float(p) for p in parts]
        except ValueError:
            if rows:
                break
            continue  # text before the data block is header metadata
        if len(values) >= 2:
            rows.append(values)
    return rows


def _fast_block(lines: list[str]) -> FloatArray | None:
    """Parse a rectangular data block with numpy's C text reader.

    Args:
        lines: Stripped candidate data lines.

    Returns:
        The array of shape ``(n_lines, n_columns)``, or ``None`` if the block is
        not a clean rectangular table (the caller then falls back to a slow path).
    """
    block = "\n".join(line.rstrip(" ,;\t") for line in lines).replace("\t", ",").replace(";", ",")
    try:
        array = np.loadtxt(io.StringIO(block), delimiter=",", dtype=np.float64, ndmin=2)
    except ValueError:
        return None
    return array if array.shape[1] >= 2 else None


def parse_asc(text: str, name: str = "spectrum") -> AndorSpectrum:
    """Parse the contents of an Andor ``.asc`` file.

    Args:
        text: Full file content.
        name: Display name for the spectrum.

    Returns:
        The parsed spectrum.

    Raises:
        ValueError: If no numeric data block is found.
    """
    data_lines: list[str] = []
    meta_lines: list[str] = []
    state = 0  # 0: header, 1: data block, 2: footer
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if state == 1:
                state = 2
            continue
        if state != 2 and line[0] in _NUMERIC_START:
            state = 1
            data_lines.append(line)
            continue
        if state == 1:
            state = 2
        meta_lines.append(line)

    array = _fast_block(data_lines) if data_lines else None
    if array is None:
        rows = _slow_block(data_lines)
        if not rows:
            raise ValueError(f"{name}: no spectral data found.")
        width = min(len(r) for r in rows)
        array = np.array([r[:width] for r in rows], dtype=np.float64)

    metadata: dict[str, str] = {}
    for line in meta_lines:
        match = _META_PATTERN.match(line)
        if match:
            metadata.setdefault(match.group(1).strip(), match.group(2).strip())

    if not np.all(np.diff(array[:, 0]) >= 0):
        array = array[np.argsort(array[:, 0], kind="stable")]
    frames, dropped = _trim_edge_rows(array[:, 1:])
    if dropped:
        metadata["Ignored Rows"] = " and ".join(dropped)
    return AndorSpectrum(name=name, wavelength=np.ascontiguousarray(array[:, 0]), frames=frames, metadata=metadata)


def decode_bytes(raw: bytes) -> str:
    """Decode file content as UTF-8, falling back to Latin-1."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_asc(path: str | Path) -> AndorSpectrum:
    """Read an Andor ``.asc`` file from disk.

    Args:
        path: Path to the file.

    Returns:
        The parsed spectrum, named after the file.
    """
    path = Path(path)
    return parse_asc(decode_bytes(path.read_bytes()), name=path.name)
