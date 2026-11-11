"""Publication-style PNG export with matplotlib (Agg backend, no GUI)."""

from __future__ import annotations

import io
import struct
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from numpy.typing import NDArray

from specdash.figures import ACCENT, BACKGROUND_STYLES, SERIES_COLORS
from specdash.processing import Result

FloatArray = NDArray[np.float64]

_FONT_CANDIDATES = ("Arial", "Liberation Sans", "Helvetica", "Nimbus Sans", "DejaVu Sans")
_FONT_CHOICES = ("Arial", "Helvetica", "Times New Roman", "Calibri", "Courier New", "DejaVu Sans", "DejaVu Serif")
_DASHES = {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-."}
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")

FIG_CM = (4.5, 3.5)
"""Size of the axes in cm (width, height)."""
LEFT, RIGHT, BOTTOM, TOP = 0.2, 0.8, 0.2, 0.90
DPI = 600
PREVIEW_PX = 1400
"""Approximate width in pixels of the dialog preview, whatever the figure size."""

LEGEND_LOCATIONS: dict[str, str] = {
    "auto": "Auto (when several curves)",
    "best": "Best",
    "upper right": "Upper right",
    "upper left": "Upper left",
    "lower right": "Lower right",
    "lower left": "Lower left",
    "center right": "Center right",
    "outside right": "Outside, right",
    "outside top": "Outside, above",
    "outside bottom": "Outside, below",
    "off": "Hidden",
}
"""Legend placement choices: matplotlib ``loc`` values, ``outside ...`` and ``auto`` / ``off``."""


@dataclass(frozen=True)
class PlotStyle:
    """Look of the exported result figure; the defaults are the publication style.

    Attributes:
        width_cm: Axes width in cm.
        height_cm: Axes height in cm.
        line_width: Curve line width in pt.
        axis_width: Axes frame and tick line width in pt.
        font: Font family, or ``"auto"`` for Arial / the closest installed sans-serif.
        label_size: Axis label font size in pt.
        tick_size: Tick label font size in pt.
        legend_size: Legend font size in pt.
        legend: One of :data:`LEGEND_LOCATIONS`; the ``outside`` ones sit beside the axes and the
            saved image grows to include them.
        legend_frame: Draw a box around the legend.
        legend_cols: Number of legend columns (never more than the number of curves).
        tick_direction: ``"in"`` or ``"out"``.
        tick_length: Major tick length in pt.
        grid: Draw grid lines.
        box: Draw the top and right axes lines.
        x_min: Lower X limit, or ``None`` for the data range.
        x_max: Upper X limit, or ``None`` for the data range.
        y_min: Lower Y limit, or ``None`` for automatic.
        y_max: Upper Y limit, or ``None`` for automatic.
        x_label: X-axis label, or empty for the processed default.
        y_label: Y-axis label, or empty for the processed default.
        dpi: Resolution of the saved file.
        transparent: Save without a white background.
    """

    width_cm: float = FIG_CM[0]
    height_cm: float = FIG_CM[1]
    line_width: float = 0.8
    axis_width: float = 0.8
    font: str = "auto"
    label_size: float = 8
    tick_size: float = 7
    legend_size: float = 6
    legend: str = "auto"
    legend_frame: bool = False
    legend_cols: int = 1
    tick_direction: str = "in"
    tick_length: float = 3
    grid: bool = False
    box: bool = True
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    x_label: str = ""
    y_label: str = ""
    dpi: int = DPI
    transparent: bool = False


def available_fonts() -> list[str]:
    """Return the font families of :data:`_FONT_CHOICES` that are installed."""
    from matplotlib import font_manager

    found: list[str] = []
    for family in _FONT_CHOICES:
        try:
            font_manager.findfont(family, fallback_to_default=False)
        except ValueError:
            continue
        found.append(family)
    return found


def _font(requested: str = "auto") -> str:
    """Return the requested family if installed, else Arial or the closest sans-serif."""
    from matplotlib import font_manager

    candidates = (requested, *_FONT_CANDIDATES) if requested != "auto" else _FONT_CANDIDATES
    for family in candidates:
        try:
            font_manager.findfont(family, fallback_to_default=False)
        except ValueError:
            continue
        return family
    return "DejaVu Sans"


def _style(axes_cm: tuple[float, float] = FIG_CM, style: PlotStyle | None = None) -> dict[str, Any]:
    """Return the rcParams of the export style."""
    style = style or PlotStyle()
    font = _font(style.font)
    width, height = axes_cm[0] / 2.54, axes_cm[1] / 2.54
    return {
        "font.size": style.tick_size,
        "font.family": font,
        "mathtext.fontset": "custom",
        "mathtext.rm": font,
        "mathtext.it": f"{font}:italic",
        "mathtext.bf": f"{font}:bold",
        "figure.figsize": (width / (RIGHT - LEFT), height / (TOP - BOTTOM)),
        "figure.subplot.left": LEFT,
        "figure.subplot.right": RIGHT,
        "figure.subplot.bottom": BOTTOM,
        "figure.subplot.top": TOP,
        "axes.labelpad": 2,
        "axes.labelsize": style.label_size,
        "axes.linewidth": style.axis_width,
        "axes.grid": style.grid,
        "grid.linewidth": max(style.axis_width * 0.6, 0.2),
        "grid.color": "#d9dce1",
        "xtick.labelsize": style.tick_size,
        "ytick.labelsize": style.tick_size,
        "legend.fontsize": style.legend_size,
        "legend.frameon": style.legend_frame,
        "legend.labelspacing": 0.2,
        "legend.handlelength": 1.5,
        "legend.columnspacing": 1,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "savefig.dpi": style.dpi,
        "savefig.transparent": style.transparent,
        "xtick.direction": style.tick_direction,
        "ytick.direction": style.tick_direction,
        "xtick.major.size": style.tick_length,
        "ytick.major.size": style.tick_length,
        "xtick.major.width": style.axis_width,
        "ytick.major.width": style.axis_width,
        "axes.formatter.limits": (-2, 3),
        "axes.unicode_minus": True,
    }


def _mpl_text(text: str) -> str:
    """Convert Unicode sub/superscripts to mathtext, which Arial renders reliably."""
    out: list[str] = []
    for char in text:
        if char in "₀₁₂₃₄₅₆₇₈₉":
            out.append(f"$_{{{char.translate(_SUBSCRIPTS)}}}$")
        elif char in "⁰¹²³⁴⁵⁶⁷⁸⁹⁻":
            out.append(f"$^{{{char.translate(_SUPERSCRIPTS)}}}$")
        else:
            out.append(char)
    merged = "".join(out)
    # Join neighbouring mathtext fragments: "cm$^{-}$$^{1}$" -> "cm$^{-1}$".
    while "}$$^{" in merged:
        merged = merged.replace("}$$^{", "", 1)
    while "}$$_{" in merged:
        merged = merged.replace("}$$_{", "", 1)
    return merged


def _to_png(fig: Any) -> bytes:
    """Render a figure to PNG bytes using the active style's savefig settings."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()


def png_size(content: bytes) -> tuple[int, int]:
    """Return the (width, height) in pixels of PNG file content."""
    width, height = struct.unpack(">II", content[16:24])
    return width, height


def _limits(
    result: Result, curves: dict[str, FloatArray], style: PlotStyle
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Resolve the X and Y limits; ``None`` leaves an axis to matplotlib."""
    finite = result.x[np.isfinite(result.x)]
    xlim: tuple[float, float] | None = None
    if finite.size:
        low = float(finite.min()) if style.x_min is None else style.x_min
        high = float(finite.max()) if style.x_max is None else style.x_max
        if low >= high:
            low, high = float(finite.min()), float(finite.max())
        xlim = (low, high)

    ylim: tuple[float, float] | None = None
    if style.y_min is not None and style.y_max is not None and style.y_min < style.y_max:
        ylim = (style.y_min, style.y_max)
    elif xlim is not None and (style.x_min is not None or style.x_max is not None):
        # Fit the Y range to the visible part of the curves, as an interactive zoom does.
        inside = (result.x >= xlim[0]) & (result.x <= xlim[1])
        parts = [y[inside & np.isfinite(y)] for y in curves.values()]
        values = np.concatenate(parts) if parts else np.empty(0)
        if values.size:
            low, high = float(values.min()), float(values.max())
            pad = (high - low) * 0.05 or 0.5
            ylim = (low - pad if style.y_min is None else style.y_min, high + pad if style.y_max is None else style.y_max)
            if ylim[0] >= ylim[1]:
                ylim = None
    return xlim, ylim


Curve = tuple[str, FloatArray, str, str]
"""A line to draw: legend label, Y values, color and matplotlib line style."""


def _add_legend(ax: Any, count: int, style: PlotStyle) -> None:
    """Draw the legend at ``style.legend``, inside or outside the axes."""
    from matplotlib.transforms import ScaledTranslation

    where = style.legend
    ncol = max(1, min(style.legend_cols, count))
    if where == "auto":
        ax.legend(loc="best", ncol=ncol)
    elif where == "outside right":
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), borderaxespad=0, ncol=ncol)
    elif where == "outside top":
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), borderaxespad=0, ncol=ncol)
    elif where == "outside bottom":
        # Clear the tick labels and the X label, whose height follows the font sizes.
        below = (
            (style.tick_length if style.tick_direction == "out" else 0)
            + 3
            + style.tick_size * 1.2
            + 2
            + style.label_size * 1.3
            + 4
        ) / 72
        shift = ScaledTranslation(0, -below, ax.figure.dpi_scale_trans)
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, 0),
            bbox_transform=ax.transAxes + shift,
            borderaxespad=0,
            ncol=ncol,
        )
    else:
        ax.legend(loc=where, ncol=ncol)


def _curves_png(
    result: Result, curves: Sequence[Curve], y_label: str, style: PlotStyle, dpi: int | None
) -> bytes:
    """Draw lines over ``result.x`` in ``style`` and return the PNG."""
    import matplotlib

    from matplotlib.figure import Figure

    if dpi is not None:
        style = replace(style, dpi=dpi)
    with matplotlib.rc_context(_style((style.width_cm, style.height_cm), style)):
        fig = Figure()
        ax = fig.subplots()
        for label, y, color, linestyle in curves:
            ax.plot(result.x, y, lw=style.line_width, color=color, ls=linestyle, label=label)
        xlim, ylim = _limits(result, {label: y for label, y, _, _ in curves}, style)
        if xlim:
            ax.set_xlim(xlim)
        if ylim:
            ax.set_ylim(ylim)
        ax.set_xlabel(_mpl_text(style.x_label or result.x_label))
        ax.set_ylabel(_mpl_text(style.y_label or y_label))
        if not style.box:
            ax.spines[["top", "right"]].set_visible(False)
        show_legend = len(curves) > 1 if style.legend == "auto" else style.legend != "off"
        if show_legend and curves:
            _add_legend(ax, len(curves), style)
        return _to_png(fig)


def result_png(
    result: Result,
    signal_order: Sequence[str],
    style: PlotStyle | None = None,
    dpi: int | None = None,
) -> bytes:
    """Render the processed curves.

    Args:
        result: Processed result.
        signal_order: Signal names in upload order, so colors match the app.
        style: Look of the figure; the publication style when omitted.
        dpi: Override of ``style.dpi``, e.g. for a quick preview.

    Returns:
        PNG file content.
    """
    order = list(signal_order)
    curves = [
        (name, y, SERIES_COLORS[(order.index(name) if name in order else 0) % len(SERIES_COLORS)], "-")
        for name, y in result.curves.items()
    ]
    return _curves_png(result, curves, result.y_label, style or PlotStyle(), dpi)


def inputs_png(
    result: Result,
    signal_order: Sequence[str],
    style: PlotStyle | None = None,
    dpi: int | None = None,
) -> bytes:
    """Render the normalized input spectra (signals, substrate, reference, dark).

    Args:
        result: Processed result.
        signal_order: Signal names in upload order, so colors match the app.
        style: Look of the figure; the publication style when omitted.
        dpi: Override of ``style.dpi``, e.g. for a quick preview.

    Returns:
        PNG file content.
    """
    order = list(signal_order)
    curves: list[Curve] = []
    for label, y in result.inputs.items():
        symbol, _, name = label.partition(": ")
        if symbol == "S":
            color, linestyle = SERIES_COLORS[(order.index(name) if name in order else 0) % len(SERIES_COLORS)], "-"
        else:
            color, dash = BACKGROUND_STYLES.get(symbol, ("#50555e", "dash"))
            linestyle = _DASHES.get(dash, "--")
        curves.append((label, y, color, linestyle))
    return _curves_png(result, curves, f"Intensity ({result.intensity_unit})", style or PlotStyle(), dpi)


def preview_dpi(style: PlotStyle) -> int:
    """Resolution of the dialog preview: about :data:`PREVIEW_PX` pixels wide for any figure size."""
    return int(min(max(PREVIEW_PX / (style.width_cm / 2.54 / (RIGHT - LEFT)), 100), 1200))


def preview_png(result: Result, signal_order: Sequence[str], style: PlotStyle) -> bytes:
    """Render :func:`result_png` at a resolution suited to the dialog preview.

    The preview has the same layout as the saved file; only the pixel density differs.
    """
    return result_png(result, signal_order, style, dpi=preview_dpi(style))


def rows_png(
    wavelength: FloatArray,
    frames: FloatArray,
    rows: tuple[int, int] | None,
    style: PlotStyle | None = None,
    dpi: int | None = None,
) -> bytes:
    """Render the detector image with the selected rows outlined in blue.

    Args:
        wavelength: Wavelength per pixel, shape ``(n_pixels,)``.
        frames: Raw counts, shape ``(n_pixels, n_rows)``.
        rows: Inclusive one-based row range, or ``None`` for all rows.
        style: Look of the figure. The axes keep the image's aspect, so only
            ``width_cm`` sets the size; ``line_width`` is the outline width.
        dpi: Override of ``style.dpi``, e.g. for a quick preview.

    Returns:
        PNG file content.
    """
    import matplotlib

    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import MaxNLocator

    from specdash.figures import image_ratio

    style = replace(style or PlotStyle(), grid=False)
    if dpi is not None:
        style = replace(style, dpi=dpi)
    n_rows = frames.shape[1]
    first, last = rows or (1, n_rows)
    image = frames.T
    low, high = np.percentile(image, [1, 99])
    if not high > low:
        high = low + 1.0
    ratio = image_ratio(wavelength, n_rows)
    x0, x1 = float(wavelength[0]), float(wavelength[-1])

    with matplotlib.rc_context(_style((style.width_cm, style.width_cm * ratio), style)):
        fig = Figure()
        ax = fig.subplots()
        ax.imshow(
            image,
            cmap="gray",
            vmin=float(low),
            vmax=float(high),
            aspect="auto",
            interpolation="nearest",
            extent=(x0, x1, n_rows + 0.5, 0.5),
        )
        if n_rows > 1:
            ax.add_patch(
                Rectangle(
                    (x0, first - 0.5),
                    x1 - x0,
                    last - first + 1,
                    fill=False,
                    edgecolor=ACCENT,
                    linewidth=style.line_width,
                )
            )
        ax.set_xlabel(_mpl_text(style.x_label or "Wavelength (nm)"))
        ax.set_ylabel(_mpl_text(style.y_label or "Row"))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
        if not style.box:
            ax.spines[["top", "right"]].set_visible(False)
        return _to_png(fig)
