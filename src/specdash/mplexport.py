"""Publication-style PNG export with matplotlib (Agg backend, no GUI)."""

from __future__ import annotations

import io
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from specdash.figures import ACCENT, SERIES_COLORS
from specdash.processing import Result

FloatArray = NDArray[np.float64]

_FONT_CANDIDATES = ("Arial", "Liberation Sans", "Helvetica", "Nimbus Sans", "DejaVu Sans")
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")

FIG_CM = (4.5, 3.5)
"""Size of the axes in cm (width, height)."""
LEFT, RIGHT, BOTTOM, TOP = 0.2, 0.8, 0.2, 0.90
DPI = 600


def _font() -> str:
    """Return Arial, or the closest installed sans-serif font."""
    from matplotlib import font_manager

    for family in _FONT_CANDIDATES:
        try:
            font_manager.findfont(family, fallback_to_default=False)
        except ValueError:
            continue
        return family
    return "DejaVu Sans"


def _style(axes_cm: tuple[float, float] = FIG_CM) -> dict[str, Any]:
    """Return the rcParams of the export style."""
    font = _font()
    width, height = axes_cm[0] / 2.54, axes_cm[1] / 2.54
    return {
        "font.size": 7,
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
        "axes.labelsize": 8,
        "legend.fontsize": 6,
        "legend.frameon": False,
        "legend.labelspacing": 0.2,
        "legend.handlelength": 1.5,
        "legend.columnspacing": 1,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "savefig.dpi": DPI,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.major.size": 3,
        "ytick.major.size": 3,
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


def result_png(result: Result, signal_order: Sequence[str]) -> bytes:
    """Render the processed curves.

    Args:
        result: Processed result.
        signal_order: Signal names in upload order, so colors match the app.

    Returns:
        PNG file content.
    """
    import matplotlib

    from matplotlib.figure import Figure

    with matplotlib.rc_context(_style()):
        fig = Figure()
        ax = fig.subplots()
        order = list(signal_order)
        for name, y in result.curves.items():
            index = order.index(name) if name in order else 0
            ax.plot(result.x, y, lw=0.8, color=SERIES_COLORS[index % len(SERIES_COLORS)], label=name)
        finite = result.x[np.isfinite(result.x)]
        if finite.size:
            ax.set_xlim(float(finite.min()), float(finite.max()))
        ax.set_xlabel(_mpl_text(result.x_label))
        ax.set_ylabel(_mpl_text(result.y_label))
        if len(result.curves) > 1:
            ax.legend(loc="best")
        return _to_png(fig)


def rows_png(
    wavelength: FloatArray,
    frames: FloatArray,
    rows: tuple[int, int] | None,
) -> bytes:
    """Render the detector image with the selected rows outlined in blue.

    Args:
        wavelength: Wavelength per pixel, shape ``(n_pixels,)``.
        frames: Raw counts, shape ``(n_pixels, n_rows)``.
        rows: Inclusive one-based row range, or ``None`` for all rows.

    Returns:
        PNG file content.
    """
    import matplotlib

    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import MaxNLocator

    from specdash.figures import image_ratio

    n_rows = frames.shape[1]
    first, last = rows or (1, n_rows)
    image = frames.T
    low, high = np.percentile(image, [1, 99])
    if not high > low:
        high = low + 1.0
    ratio = image_ratio(wavelength, n_rows)
    x0, x1 = float(wavelength[0]), float(wavelength[-1])

    with matplotlib.rc_context(_style((FIG_CM[0], FIG_CM[0] * ratio))):
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
                    linewidth=0.8,
                )
            )
        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Row")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
        return _to_png(fig)
