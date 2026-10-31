"""Spectral processing for emission and reference-based measurements.

Two families of measurements are supported:

* **Emission** (PL, Raman): the sample emits light and the
  result is the signal minus the substrate background.
* **Optical** (dark-field scattering, transmission, reflection): the result is
  a ratio against a reference (lamp) spectrum, with dark counts removed.

All inputs are first averaged over the selected detector rows and, optionally,
normalized to counts per second per accumulation using the exposure time and
accumulation count stored in each ``.asc`` file. Background/reference spectra
are linearly interpolated onto the wavelength grid of the first signal.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from specdash.io import AndorSpectrum

FloatArray = NDArray[np.float64]

HC_EV_NM = 1239.841984
"""Photon energy conversion constant, ``E[eV] = HC_EV_NM / lambda[nm]``."""


class Family(StrEnum):
    """Measurement family, which determines the required inputs."""

    EMISSION = "emission"
    OPTICAL = "optical"


class Role(StrEnum):
    """Role of an input file in the processing chain."""

    SIGNAL = "signal"
    SUBSTRATE = "substrate"
    REFERENCE = "reference"
    DARK = "dark"


class XAxis(StrEnum):
    """Available x-axis representations."""

    WAVELENGTH = "wavelength"
    ENERGY = "energy"
    RAMAN = "raman"


X_AXIS_LABELS: dict[XAxis, str] = {
    XAxis.WAVELENGTH: "Wavelength (nm)",
    XAxis.ENERGY: "Energy (eV)",
    XAxis.RAMAN: "Raman shift (cm⁻¹)",
}


@dataclass(frozen=True)
class Quantity:
    """An output quantity that a mode can compute.

    Attributes:
        key: Identifier used in the UI and export headers.
        label: Human-readable name, also used as the y-axis title.
        formula: Formula shown to the user (S, B, R, D notation).
    """

    key: str
    label: str
    formula: str


@dataclass(frozen=True)
class Mode:
    """A measurement mode.

    Attributes:
        key: Identifier used in the UI.
        label: Human-readable name.
        family: Measurement family.
        quantities: Output quantities, the first being the default.
    """

    key: str
    label: str
    family: Family
    quantities: tuple[Quantity, ...]

    @property
    def roles(self) -> tuple[Role, ...]:
        """Input roles used by this mode."""
        if self.family is Family.EMISSION:
            return (Role.SIGNAL, Role.SUBSTRATE)
        return (Role.SIGNAL, Role.SUBSTRATE, Role.REFERENCE, Role.DARK)

    def quantity(self, key: str | None) -> Quantity:
        """Look up a quantity by key, falling back to the default.

        Args:
            key: Quantity key, or ``None`` for the default.

        Returns:
            The matching quantity.
        """
        for q in self.quantities:
            if q.key == key:
                return q
        return self.quantities[0]


_EMISSION_QUANTITIES = (
    Quantity("net", "Net intensity", "S − B"),
    Quantity("raw", "Signal", "S"),
)

MODES: dict[str, Mode] = {
    m.key: m
    for m in (
        Mode("pl", "Photoluminescence", Family.EMISSION, _EMISSION_QUANTITIES),
        Mode("raman", "Raman", Family.EMISSION, _EMISSION_QUANTITIES),
        Mode(
            "darkfield",
            "Dark-field scattering",
            Family.OPTICAL,
            (
                Quantity("scattering", "Scattering intensity", "(S − B) / (R − D)"),
                Quantity("raw_ratio", "Signal / reference", "(S − D) / (R − D)"),
            ),
        ),
        Mode(
            "transmission",
            "Transmission",
            Family.OPTICAL,
            (
                Quantity("relative", "Relative transmission T/T₀", "(S − D) / (B − D)"),
                Quantity("absolute", "Transmission T", "(S − D) / (R − D)"),
                Quantity("extinction", "Extinction 1 − T/T₀", "1 − (S − D) / (B − D)"),
                Quantity("absorbance", "Absorbance −log₁₀(T/T₀)", "−log₁₀[(S − D) / (B − D)]"),
            ),
        ),
        Mode(
            "reflection",
            "Reflection",
            Family.OPTICAL,
            (
                Quantity("relative", "Relative reflection R/R₀", "(S − D) / (B − D)"),
                Quantity("absolute", "Reflection R", "(S − D) / (R − D)"),
                Quantity("contrast", "Reflection contrast ΔR/R₀", "(S − B) / (B − D)"),
            ),
        ),
    )
}

ROLE_LABELS: dict[Role, str] = {
    Role.SIGNAL: "Signal",
    Role.SUBSTRATE: "Substrate background",
    Role.REFERENCE: "Reference",
    Role.DARK: "Dark background",
}

ROLE_SYMBOLS: dict[Role, str] = {
    Role.SIGNAL: "S",
    Role.SUBSTRATE: "B",
    Role.REFERENCE: "R",
    Role.DARK: "D",
}


@dataclass
class Options:
    """User-selectable processing options.

    Attributes:
        rows: Inclusive zero-based detector row range, or ``None`` for all.
        per_second: Normalize by exposure time.
        per_accumulation: Normalize by number of accumulations.
        smooth_window: Savitzky–Golay window length in points; values below
            3 disable smoothing.
        wavelength_range: Inclusive wavelength range in nm to keep, or ``None``
            for the full grid.
        divide_max: Scale each processed curve by its maximum.
        excitation_nm: Excitation wavelength for the Raman shift axis.
        x_axis: X-axis representation.
        quantity: Output quantity key; ``None`` selects the mode default.
    """

    rows: tuple[int, int] | None = None
    per_second: bool = True
    per_accumulation: bool = True
    smooth_window: int = 0
    divide_max: bool = False
    wavelength_range: tuple[float, float] | None = None
    excitation_nm: float = 532.0
    x_axis: XAxis = XAxis.WAVELENGTH
    quantity: str | None = None


@dataclass
class Result:
    """Output of :func:`process`.

    Attributes:
        wavelength: Common wavelength grid in nm.
        x: X values in the selected representation.
        x_label: X-axis title.
        y_label: Y-axis title for the processed curves.
        intensity_unit: Unit of the normalized input spectra.
        formula: Formula used for the processed curves.
        curves: Processed curve per signal, keyed by signal name.
        inputs: Normalized input spectra on the common grid, keyed by a
            ``"<symbol>: <name>"`` label.
        warnings: Non-fatal issues encountered during processing.
    """

    wavelength: FloatArray
    x: FloatArray
    x_label: str
    y_label: str
    intensity_unit: str
    formula: str
    curves: dict[str, FloatArray] = field(default_factory=dict)
    inputs: dict[str, FloatArray] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _safe_divide(num: FloatArray, den: FloatArray) -> FloatArray:
    """Element-wise division returning NaN where the denominator is ~0."""
    out = np.full_like(num, np.nan)
    scale = np.nanmax(np.abs(den)) if den.size and np.any(np.isfinite(den)) else 0.0
    mask = np.abs(den) > max(scale * 1e-9, np.finfo(np.float64).tiny)
    np.divide(num, den, out=out, where=mask)
    return out


def _on_grid(
    spectrum: AndorSpectrum, grid: FloatArray, options: Options, warnings: list[str]
) -> FloatArray:
    """Normalize a spectrum and interpolate it onto ``grid``."""
    if options.rows is not None and options.rows[1] >= spectrum.n_rows:
        warnings.append(
            f"{spectrum.name} has only {spectrum.n_rows} detector rows; the row selection is clipped."
        )
    values = spectrum.rate(options.rows, options.per_second, options.per_accumulation)
    if spectrum.wavelength.shape == grid.shape and np.allclose(spectrum.wavelength, grid, atol=1e-3):
        return values
    lo, hi = spectrum.wavelength[0], spectrum.wavelength[-1]
    if grid[0] < lo - 1e-6 or grid[-1] > hi + 1e-6:
        warnings.append(
            f"{spectrum.name} covers {lo:.1f}–{hi:.1f} nm only; values outside are set to NaN."
        )
    return np.interp(grid, spectrum.wavelength, values, left=np.nan, right=np.nan)


def _savgol(values: FloatArray, window: int, polyorder: int = 2) -> FloatArray:
    """Savitzky–Golay smoothing with polynomial-fitted edges.

    Equivalent to ``scipy.signal.savgol_filter(..., mode="interp")``, implemented
    with numpy only to keep the dependency footprint (and frozen builds) small.

    Args:
        values: Input samples; must contain at least ``window`` points.
        window: Odd window length, greater than ``polyorder``.
        polyorder: Order of the fitted polynomial.

    Returns:
        The smoothed samples.
    """
    half = window // 2
    offsets = np.arange(-half, half + 1, dtype=np.float64)
    design = np.vander(offsets, polyorder + 1, increasing=True)
    projector = np.linalg.pinv(design)
    out = np.empty_like(values)
    out[half : len(values) - half] = np.convolve(values, projector[0][::-1], mode="valid")
    out[:half] = (design @ (projector @ values[:window]))[:half]
    out[len(values) - half :] = (design @ (projector @ values[-window:]))[window - half :]
    return out


def _smooth(values: FloatArray, window: int) -> FloatArray:
    """Apply Savitzky–Golay smoothing (polyorder 2) when ``window >= 3``."""
    finite = np.isfinite(values)
    n_finite = int(finite.sum())
    window = min(window | 1, n_finite if n_finite % 2 else n_finite - 1)
    if window < 3:
        return values
    out = values.copy()
    out[finite] = _savgol(values[finite], window)
    return out


def _x_values(wavelength: FloatArray, options: Options) -> FloatArray:
    """Convert the wavelength grid to the selected x representation."""
    if options.x_axis is XAxis.ENERGY:
        return HC_EV_NM / wavelength
    if options.x_axis is XAxis.RAMAN:
        return 1e7 * (1.0 / options.excitation_nm - 1.0 / wavelength)
    return wavelength


def _compute(
    quantity: str, s: FloatArray, b: FloatArray | None, r: FloatArray | None, d: FloatArray | None
) -> FloatArray:
    """Evaluate a quantity formula; missing optional inputs act as zero."""
    zeros = np.zeros_like(s)
    b_ = zeros if b is None else b
    r_ = zeros if r is None else r
    d_ = zeros if d is None else d
    match quantity:
        case "net":
            return s - b_
        case "raw":
            return s
        case "scattering":
            return _safe_divide(s - b_, r_ - d_)
        case "raw_ratio" | "absolute":
            return _safe_divide(s - d_, r_ - d_)
        case "relative":
            return _safe_divide(s - d_, b_ - d_)
        case "extinction":
            return 1.0 - _safe_divide(s - d_, b_ - d_)
        case "absorbance":
            ratio = _safe_divide(s - d_, b_ - d_)
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where(ratio > 0, -np.log10(np.where(ratio > 0, ratio, 1.0)), np.nan)
        case "contrast":
            return _safe_divide(s - b_, b_ - d_)
    raise ValueError(f"Unknown quantity: {quantity}")


_REQUIRED_ROLES: dict[str, tuple[Role, ...]] = {
    "net": (Role.SUBSTRATE,),
    "raw": (),
    "scattering": (Role.REFERENCE,),
    "raw_ratio": (Role.REFERENCE,),
    "absolute": (Role.REFERENCE,),
    "relative": (Role.SUBSTRATE,),
    "extinction": (Role.SUBSTRATE,),
    "absorbance": (Role.SUBSTRATE,),
    "contrast": (Role.SUBSTRATE,),
}


def process(
    mode: Mode,
    signals: list[AndorSpectrum],
    backgrounds: dict[Role, AndorSpectrum | None],
    options: Options,
) -> Result:
    """Process one or more signal spectra against shared backgrounds.

    Args:
        mode: Measurement mode.
        signals: Signal spectra; the first defines the wavelength grid.
        backgrounds: Spectra for the non-signal roles; missing roles map to
            ``None`` and are treated as zero where the formula allows.
        options: Processing options.

    Returns:
        The processed result.

    Raises:
        ValueError: If no signal is given or a required input is missing.
    """
    if not signals:
        raise ValueError("Upload at least one signal spectrum.")
    quantity = mode.quantity(options.quantity)
    missing = [
        ROLE_LABELS[role] for role in _REQUIRED_ROLES[quantity.key] if backgrounds.get(role) is None
    ]
    if missing:
        raise ValueError(f"{quantity.label} requires: {', '.join(missing)}.")

    warnings: list[str] = []
    grid = signals[0].wavelength
    if options.wavelength_range is not None:
        lo, hi = options.wavelength_range
        grid = grid[(grid >= lo) & (grid <= hi)]
        if grid.size < 2:
            raise ValueError("The selected wavelength range contains no data.")
    unit = "counts"
    if options.per_second:
        unit += "/s"
    if options.per_accumulation:
        unit += " per acc."

    inputs: dict[str, FloatArray] = {}
    bg: dict[Role, FloatArray | None] = {}
    for role in mode.roles[1:]:
        spectrum = backgrounds.get(role)
        if spectrum is None:
            bg[role] = None
            continue
        bg[role] = _on_grid(spectrum, grid, options, warnings)
        inputs[f"{ROLE_SYMBOLS[role]}: {spectrum.name}"] = bg[role]

    if mode.family is Family.OPTICAL and bg.get(Role.DARK) is None and quantity.key != "raw":
        warnings.append("No dark background supplied; dark counts are assumed to be zero.")

    curves: dict[str, FloatArray] = {}
    for spectrum in signals:
        s = _on_grid(spectrum, grid, options, warnings)
        inputs[f"S: {spectrum.name}"] = s
        y = _compute(quantity.key, s, bg.get(Role.SUBSTRATE), bg.get(Role.REFERENCE), bg.get(Role.DARK))
        y = _smooth(y, options.smooth_window)
        if options.divide_max and np.any(np.isfinite(y)) and np.nanmax(y) > 0:
            y = y / np.nanmax(y)
        curves[spectrum.name] = y

    y_label = quantity.label
    if mode.family is Family.EMISSION:
        y_label = f"{quantity.label} ({unit})"

    return Result(
        wavelength=grid,
        x=_x_values(grid, options),
        x_label=X_AXIS_LABELS[options.x_axis],
        y_label=y_label,
        intensity_unit=unit,
        formula=quantity.formula,
        curves=curves,
        inputs=inputs,
        warnings=list(dict.fromkeys(warnings)),
    )


def _export_columns(result: Result, include_inputs: bool) -> dict[str, FloatArray]:
    """Collect the named columns written by every export format."""
    columns: dict[str, FloatArray] = {"wavelength_nm": result.wavelength}
    if result.x_label != X_AXIS_LABELS[XAxis.WAVELENGTH]:
        columns[result.x_label] = result.x
    for name, values in result.curves.items():
        columns[f"{name} [{result.formula}]"] = values
    if include_inputs:
        for name, values in result.inputs.items():
            columns[f"{name} ({result.intensity_unit})"] = values
    return columns


def export_bytes(result: Result, mode: Mode, fmt: str = "csv", include_inputs: bool = True) -> bytes:
    """Render a result in any supported export format.

    Args:
        result: Processed result.
        mode: Measurement mode, used for the header.
        fmt: One of ``"csv"``, ``"txt"``, ``"npy"`` (structured array with one
            float field per column) or ``"json"``.
        include_inputs: Also export the normalized input spectra.

    Returns:
        The encoded file content.
    """
    if fmt == "npy":
        columns = _export_columns(result, include_inputs)
        table = np.empty(len(result.wavelength), dtype=[(name, "f8") for name in columns])
        for name, values in columns.items():
            table[name] = values
        buffer = io.BytesIO()
        np.save(buffer, table)
        return buffer.getvalue()
    if fmt == "json":
        columns = _export_columns(result, include_inputs)
        payload = {
            "mode": mode.label,
            "quantity": result.y_label,
            "formula": result.formula,
            "input_intensity_unit": result.intensity_unit,
            "columns": {name: [None if not np.isfinite(v) else float(v) for v in values] for name, values in columns.items()},
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return export_table(result, mode, fmt, include_inputs).encode("utf-8")


def export_table(result: Result, mode: Mode, fmt: str = "csv", include_inputs: bool = True) -> str:
    """Render a result as a delimited text table.

    Args:
        result: Processed result.
        mode: Measurement mode, used for the header.
        fmt: ``"csv"`` for comma-separated output or ``"txt"`` for a
            tab-separated table with a ``#``-prefixed comment header.
        include_inputs: Also export the normalized input spectra.

    Returns:
        The table as a string.
    """
    columns = _export_columns(result, include_inputs)

    delimiter = "," if fmt == "csv" else "\t"
    buffer = io.StringIO()
    if fmt != "csv":
        buffer.write(f"# Mode: {mode.label}\n")
        buffer.write(f"# Quantity: {result.y_label}\n")
        buffer.write(f"# Formula: {result.formula}\n")
        buffer.write(f"# Input intensity unit: {result.intensity_unit}\n")
    headers = [h.replace(delimiter, ";") if delimiter == "," else h for h in columns]
    if fmt == "csv":
        headers = [f'"{h}"' for h in headers]
    buffer.write(delimiter.join(headers) + "\n")
    data = np.column_stack(list(columns.values()))
    np.savetxt(buffer, data, delimiter=delimiter, fmt="%.8g")
    text = buffer.getvalue()
    # A BOM lets spreadsheet software detect UTF-8 for the Unicode headers.
    return "\ufeff" + text if fmt == "csv" else text
