"""Plotly figure construction with a consistent, minimal style."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import plotly.graph_objects as go
from numpy.typing import NDArray

from specdash.processing import Result

FloatArray = NDArray[np.float64]

SERIES_COLORS: tuple[str, ...] = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#6250d6",  # violet
    "#e34948",  # red
)
"""Categorical palette, assigned in fixed order."""

BACKGROUND_STYLES: dict[str, tuple[str, str]] = {
    "B": ("#6250d6", "dash"),
    "R": ("#008300", "dot"),
    "D": ("#52514e", "dashdot"),
}
"""Color and dash style per background role symbol."""

TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#ebeae6"
AXIS = "#c9c8c2"
SURFACE = "#ffffff"
FONT_FAMILY = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'

GRAPH_CONFIG: dict[str, object] = {
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {"format": "svg", "filename": "spectrum"},
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}
"""``dcc.Graph`` config: SVG snapshot export and a trimmed mode bar."""


def _base_layout(x_label: str, y_label: str, show_legend: bool) -> dict[str, object]:
    """Return the shared layout dictionary."""
    axis = {
        "showgrid": True,
        "gridcolor": GRID,
        "zeroline": False,
        "showline": True,
        "linecolor": AXIS,
        "ticks": "outside",
        "tickcolor": AXIS,
        "ticklen": 4,
        "title": {"font": {"color": TEXT_SECONDARY, "size": 13}},
        "tickfont": {"color": TEXT_SECONDARY, "size": 12},
        "exponentformat": "power",
        "showspikes": True,
        "spikemode": "across",
        "spikethickness": 1,
        "spikedash": "solid",
        "spikecolor": AXIS,
    }
    return {
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "font": {"family": FONT_FAMILY, "color": TEXT_PRIMARY, "size": 12},
        "margin": {"l": 72, "r": 24, "t": 16, "b": 56},
        "hovermode": "x unified",
        "hoverlabel": {"bgcolor": SURFACE, "bordercolor": AXIS, "font": {"color": TEXT_PRIMARY}},
        "showlegend": show_legend,
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "left",
            "x": 0,
            "font": {"color": TEXT_SECONDARY, "size": 12},
            "bgcolor": "rgba(0,0,0,0)",
        },
        "xaxis": {**axis, "title": {**axis["title"], "text": x_label}},  # type: ignore[dict-item]
        "yaxis": {**axis, "title": {**axis["title"], "text": y_label}},  # type: ignore[dict-item]
        "uirevision": "keep",
    }


def empty_figure(message: str) -> go.Figure:
    """Create a blank figure carrying a centered hint.

    Args:
        message: Hint text.

    Returns:
        The placeholder figure.
    """
    fig = go.Figure()
    # No axes are shown, so the margins must be symmetric for the hint to be centered.
    fig.update_layout({**_base_layout("", "", False), "margin": {"l": 16, "r": 16, "t": 16, "b": 16}})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.add_annotation(
        text=message,
        showarrow=False,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        font={"color": TEXT_SECONDARY, "size": 14},
    )
    return fig


def _line(
    x: FloatArray, y: FloatArray, name: str, color: str, dash: str = "solid", hover_x: str = ".2f"
) -> go.Scattergl:
    """Create a thin line trace."""
    return go.Scattergl(
        x=x,
        y=y,
        name=name,
        mode="lines",
        line={"color": color, "width": 2, "dash": dash},
        hovertemplate=f"%{{y:.4g}}<extra>{name}</extra>",
        xhoverformat=hover_x,
    )


def result_figure(result: Result, signal_order: Sequence[str]) -> go.Figure:
    """Plot the processed curves.

    Args:
        result: Processed result.
        signal_order: Signal names in upload order, so colors follow the file
            rather than its position after filtering.

    Returns:
        The result figure.
    """
    fig = go.Figure()
    for name, y in result.curves.items():
        index = list(signal_order).index(name) if name in signal_order else 0
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        fig.add_trace(_line(result.x, y, name, color))
    fig.update_layout(_base_layout(result.x_label, result.y_label, len(result.curves) > 1))
    return fig


def inputs_figure(result: Result, signal_order: Sequence[str]) -> go.Figure:
    """Plot the normalized input spectra on the common grid.

    Args:
        result: Processed result.
        signal_order: Signal names in upload order.

    Returns:
        The inputs figure.
    """
    fig = go.Figure()
    for label, y in result.inputs.items():
        symbol, _, name = label.partition(": ")
        if symbol == "S":
            index = list(signal_order).index(name) if name in signal_order else 0
            color, dash = SERIES_COLORS[index % len(SERIES_COLORS)], "solid"
        else:
            color, dash = BACKGROUND_STYLES.get(symbol, (TEXT_SECONDARY, "dash"))
        fig.add_trace(_line(result.x, y, label, color, dash))
    fig.update_layout(
        _base_layout(result.x_label, f"Intensity ({result.intensity_unit})", len(result.inputs) > 1)
    )
    return fig


MAX_IMAGE_COLUMNS = 400
"""Spectral pixels are block-averaged down to this many columns for display."""

ACCENT = "#2a78d6"


def _downsample_columns(
    wavelength: FloatArray, image: FloatArray, max_columns: int
) -> tuple[FloatArray, FloatArray]:
    """Block-average the spectral axis so the thumbnail stays light.

    Args:
        wavelength: Wavelength per pixel, shape ``(n_pixels,)``.
        image: Intensities, shape ``(n_rows, n_pixels)``.
        max_columns: Upper bound on the number of output columns.

    Returns:
        The reduced wavelength axis and image.
    """
    step = -(-wavelength.size // max_columns)
    if step <= 1:
        return wavelength, image
    edges = np.arange(0, wavelength.size, step)
    sizes = np.diff(np.append(edges, wavelength.size))
    return (
        np.add.reduceat(wavelength, edges) / sizes,
        np.add.reduceat(image, edges, axis=1) / sizes,
    )


MIN_IMAGE_RATIO = 1 / 3
"""Flattest height / width the detector image is drawn with."""

MAX_IMAGE_RATIO = 1.0
"""Tallest height / width the detector image is drawn with."""


def image_ratio(wavelength: FloatArray, n_rows: int) -> float:
    """Return the drawn height / width of the detector image.

    The image keeps the aspect of the data (one pixel column as wide as one row
    is tall). If that is flatter than 1:3 it is stretched vertically to 1:3,
    and it is never taller than square.

    Args:
        wavelength: Wavelength per pixel, shape ``(n_pixels,)``.
        n_rows: Number of detector rows.

    Returns:
        Height divided by width.
    """
    return float(np.clip(n_rows / wavelength.size, MIN_IMAGE_RATIO, MAX_IMAGE_RATIO))


def rows_figure(
    wavelength: FloatArray,
    frames: FloatArray,
    rows: tuple[int, int] | None,
    selectable: int | None = None,
) -> go.Figure:
    """Show the detector image as grayscale (99:1 contrast) with the selected rows outlined.

    The outline is the figure's only shape. ``assets/rows_select.js`` moves it
    while the user drags, snapped to whole rows, and reads ``layout.meta`` for
    the number of selectable rows.

    Args:
        wavelength: Wavelength per pixel, shape ``(n_pixels,)``.
        frames: Raw counts, shape ``(n_pixels, n_rows)``.
        rows: Inclusive one-based row range, or ``None`` for all rows.
        selectable: Number of rows that may be selected, defaulting to all.

    Returns:
        The image figure.
    """
    n_rows = frames.shape[1]
    first, last = rows or (1, n_rows)
    image = frames.T
    low, high = np.percentile(image, [1, 99])
    x, z = _downsample_columns(wavelength, image, MAX_IMAGE_COLUMNS)

    fig = go.Figure(
        go.Heatmap(
            x=x,
            y=np.arange(1, n_rows + 1),
            z=z,
            zmin=float(low),
            zmax=float(high) if high > low else float(low) + 1.0,
            colorscale=[[0, "#000000"], [1, "#ffffff"]],
            showscale=False,
            hovertemplate="row %{y}<br>%{x:.1f} nm<br>%{z:.4g}<extra></extra>",
        )
    )
    axis = {
        "fixedrange": True,
        # Fixed margins keep the image flush with the card; tick labels that would
        # overflow the graph are hidden instead of pushing the plot area inward.
        "automargin": False,
        "ticklabeloverflow": "hide past div",
        "showgrid": False,
        "zeroline": False,
        "showline": True,
        "linecolor": AXIS,
        "ticks": "outside",
        "tickcolor": AXIS,
        "ticklen": 5,
        "minor": {"ticks": "outside", "tickcolor": AXIS, "ticklen": 2.5},
    }
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"family": FONT_FAMILY, "color": TEXT_SECONDARY, "size": 11},
        margin={"l": 0, "r": 0, "t": 4, "b": 48},
        showlegend=False,
        dragmode=False,
        hoverlabel={"bgcolor": SURFACE, "bordercolor": AXIS, "font": {"color": TEXT_PRIMARY}},
        xaxis={
            **axis,
            "title": {"text": "Wavelength (nm)", "standoff": 4},
            "range": [float(x[0]), float(x[-1])],
            "constrain": "domain",
            "constraintoward": "left",
        },
        yaxis={
            **axis,
            # Pin the pixel aspect so the plot area matches the container height
            # that the app derives from ``image_ratio``.
            "scaleanchor": "x",
            "scaleratio": image_ratio(wavelength, n_rows) * float(x[-1] - x[0]) / n_rows,
            "constrain": "domain",
            "constraintoward": "top",
            "range": [n_rows + 0.5, 0.5],
            "ticks": "",
            "showticklabels": False,
        },
        shapes=[
            {
                "type": "rect",
                # Axis references (not paper) clip the outline to the plot area.
                "xref": "x",
                "yref": "y",
                "x0": float(x[0]),
                "x1": float(x[-1]),
                "y0": first - 0.5,
                "y1": last + 0.5,
                "line": {"color": ACCENT, "width": 1.4},
            }
        ]
        if n_rows > 1
        else [],
        meta={"count": min(selectable or n_rows, n_rows)},
    )
    return fig
