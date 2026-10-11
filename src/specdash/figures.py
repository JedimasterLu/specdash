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
    fig.update_layout(_base_layout("", "", False))
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
