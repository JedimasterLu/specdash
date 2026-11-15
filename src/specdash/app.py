"""Dash application: layout and callbacks (hosted in a pywebview window, see ``desktop``)."""

from __future__ import annotations

import base64
import math
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
from flask import request, send_file

from specdash import __version__, desktop, mplexport, store
from specdash.mplexport import LEGEND_LOCATIONS, LINE_STYLES, CurveStyle, PlotStyle
from specdash.figures import (
    GRAPH_CONFIG,
    SERIES_COLORS,
    empty_figure,
    image_ratio,
    inputs_figure,
    result_figure,
    rows_figure,
)
from specdash.io import AndorSpectrum
from specdash.processing import (
    MODES,
    ROLE_LABELS,
    ROLE_SYMBOLS,
    Family,
    Mode,
    Options,
    Result,
    Role,
    XAxis,
    export_bytes,
    process,
    process_intervals,
)

ASSETS_DIR = Path(__file__).parent / "assets"
SLIM_PLOTLY = "vendor/plotly-slim.min.js"

ROLE_HINTS: dict[Role, str] = {
    Role.SIGNAL: "Sample spectrum. Multiple files are processed together.",
    Role.SUBSTRATE: "Bare substrate next to the sample.",
    Role.REFERENCE: "Lamp / white standard / mirror spectrum.",
    Role.DARK: "Light source blocked or off.",
}

StoreData = list[dict[str, Any]]
RowsData = dict[str, Any]
"""Value of the ``rows`` store: ``{"count": n_rows, "ranges": [[first, last], ...], "active": index}``,
the ranges being inclusive and one-based; the active one is what dragging on the detector image edits."""

MAX_INTERVALS = len(SERIES_COLORS)
"""Most detector row intervals at once; each has its own color."""

ROWS_GRAPH_DEFAULT_STYLE = {"height": "72px"}
ROWS_PLOT_CHROME_PX = 52
"""Vertical space taken by the top and bottom margins of the image graph."""

LASER_LINES_NM = (325, 405, 532, 633, 785, 1064)
"""Popular excitation wavelengths marked on the excitation slider, from UV to NIR."""

EXPORT_FORMATS = ("csv", "txt", "npy", "json", "png")

ROWS_GRAPH_CONFIG: dict[str, object] = {"displayModeBar": False, "responsive": True, "doubleClick": False}


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


def _upload_slot(role: Role) -> html.Div:
    """Build the upload widget for one input role."""
    multiple = role is Role.SIGNAL
    return html.Div(
        className="slot",
        id=f"slot-{role}",
        children=[
            html.Div(
                className="slot-head",
                children=[
                    html.Span(ROLE_SYMBOLS[role], className=f"badge badge-{role}"),
                    html.Div(
                        [
                            html.Div(ROLE_LABELS[role], className="slot-title"),
                            html.Div(ROLE_HINTS[role], className="slot-hint"),
                        ]
                    ),
                    html.Button("Clear", id=f"clear-{role}", className="btn-link", n_clicks=0),
                ],
            ),
            # Files arrive as paths through assets/desktop.js and desktop.py, not as browser uploads.
            html.Div(
                id=f"upload-{role}",
                className="dropzone",
                children=[
                    "Drop ",
                    html.B(".asc" + (" files" if multiple else " file")),
                    " or ",
                    html.Span("browse", className="link"),
                ],
            ),
            html.Div(id=f"files-{role}", className="file-list"),
            html.Div(id=f"error-{role}", className="slot-error"),
            dcc.Store(id=f"store-{role}", data=[]),
        ],
    )


def _mode_options() -> list[dict[str, Any]]:
    """Dropdown options for the measurement mode selector."""
    return [{"label": mode.label, "value": key} for key, mode in MODES.items()]


# --------------------------------------------------------------------------- #
# PNG export dialog
# --------------------------------------------------------------------------- #

PNG_OPT = "png-opt"
"""``type`` of every control in the PNG dialog; ``name`` is the :class:`PlotStyle` field it edits."""

_CHECKBOX_FIELDS = frozenset({"legend_frame", "grid", "box", "transparent"})
_TEXT_FIELDS = frozenset({"font", "legend", "tick_direction", "x_label", "y_label"})
_INT_FIELDS = frozenset({"dpi", "legend_cols"})
_RANGES: dict[str, tuple[float, float]] = {
    "width_cm": (1.0, 40.0),
    "height_cm": (1.0, 40.0),
    "line_width": (0.1, 2.0),
    "line_alpha": (0.0, 1.0),
    "axis_width": (0.1, 4.0),
    "label_size": (3.0, 40.0),
    "tick_size": (3.0, 40.0),
    "legend_size": (3.0, 40.0),
    "tick_length": (0.0, 20.0),
    "dpi": (72, 1200),
    "legend_cols": (1, 10),
}


def _opt_id(name: str) -> dict[str, str]:
    return {"type": PNG_OPT, "name": name}


CURVE_OPT = "png-curve"
"""``type`` of the per-curve controls (color, line style); ``label`` is the curve, ``field`` the property."""

CURVE_PATTERN = {"type": CURVE_OPT, "label": ALL, "field": ALL}
_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def _curve_id(label: str, field: str) -> dict[str, str]:
    return {"type": CURVE_OPT, "label": label, "field": field}


def _curve_row(label: str, color: str, linestyle: str) -> html.Div:
    """Controls of one curve: color (a picker is attached by ``assets/png_dialog.js``) and line style."""
    return html.Div(
        className="png-curve",
        children=[
            html.Div(label, className="png-curve-name", title=label),
            html.Div(
                className="png-curve-grid",
                children=[
                    html.Div(
                        className="png-color",
                        children=dcc.Input(
                            id=_curve_id(label, "color"),
                            type="text",
                            value=color,
                            maxLength=7,
                            debounce=0.3,
                            className="png-input",
                        ),
                    ),
                    dcc.Dropdown(
                        id=_curve_id(label, "linestyle"),
                        options=[{"label": name, "value": key} for key, name in LINE_STYLES.items()],
                        value=linestyle,
                        clearable=False,
                        searchable=False,
                    ),
                ],
            ),
        ],
    )


def _curve_styles(ids: list[dict[str, str]], values: list[Any]) -> dict[str, CurveStyle]:
    """Collect the per-curve controls into overrides; invalid or empty entries keep the default."""
    fields: dict[str, dict[str, Any]] = {}
    for control, value in zip(ids, values, strict=True):
        fields.setdefault(control["label"], {})[control["field"]] = value
    styles: dict[str, CurveStyle] = {}
    for label, own in fields.items():
        color = own.get("color")
        linestyle = own.get("linestyle")
        styles[label] = CurveStyle(
            color=color.strip() if isinstance(color, str) and _HEX_COLOR.fullmatch(color.strip()) else None,
            linestyle=linestyle if linestyle in LINE_STYLES else None,
        )
    return styles


def _number(name: str, step: float, **extra: Any) -> dcc.Input:
    """Numeric input of a :class:`PlotStyle` field (sends its value 0.3 s after the last edit)."""
    low, high = _RANGES.get(name, (None, None))
    return dcc.Input(
        id=_opt_id(name),
        type="number",
        value=getattr(PlotStyle(), name),
        min=low,
        max=high,
        step=step,
        debounce=0.3,
        className="png-input",
        **extra,
    )


def _slider(name: str, step: float, ticks: tuple[float, ...]) -> dcc.Slider:
    """Slider of a :class:`PlotStyle` field, with the value box dash puts beside it; sent on release."""
    low, high = _RANGES[name]
    return dcc.Slider(
        id=_opt_id(name),
        min=low,
        max=high,
        step=step,
        value=getattr(PlotStyle(), name),
        marks={tick: f"{tick:g}" for tick in ticks},
        updatemode="mouseup",
    )


def _only(base: str, curves_only: bool) -> str:
    """Add the class that hides a control while the dialog edits the detector image (see style.css)."""
    return f"{base} png-curves-only" if curves_only else base


def _check(name: str, label: str, curves_only: bool = False) -> dcc.Checklist:
    return dcc.Checklist(
        id=_opt_id(name),
        options=[{"label": label, "value": "on"}],
        value=["on"] if getattr(PlotStyle(), name) else [],
        className=_only("checks", curves_only),
        labelClassName="check",
    )


def _field(label: str, control: Any, curves_only: bool = False) -> html.Div:
    return html.Div(
        className=_only("png-field", curves_only), children=[html.Label(label, className="png-label"), control]
    )


def _group(title: str, *children: Any, curves_only: bool = False) -> html.Div:
    return html.Div(
        className=_only("png-group", curves_only),
        children=[html.H3(title), html.Div(className="png-grid", children=list(children))],
    )


def _png_dialog() -> html.Div:
    """Build the (initially hidden) PNG export dialog: parameters on the left, live preview on the right."""
    defaults = PlotStyle()
    controls = html.Div(
        className="png-controls",
        children=[
            _group(
                "Size",
                _field("Width (cm)", _number("width_cm", 0.1)),
                _field("Height (cm)", _number("height_cm", 0.1), curves_only=True),
            ),
            _group(
                "Curves",
                html.Div(className="png-wide", children=_field("Line width (pt)", _slider("line_width", 0.1, (0.1, 0.5, 1.0, 1.5, 2.0)))),
                html.Div(
                    className="png-wide png-curves-only",
                    children=_field("Line opacity", _slider("line_alpha", 0.1, (0.0, 0.2, 0.4, 0.6, 0.8, 1.0))),
                ),
                html.Div(id="png-curve-rows", className="png-wide png-curves-only"),
            ),
            _group(
                "Font",
                html.Div(
                    className="png-wide",
                    children=_field(
                        "Family",
                        dcc.Dropdown(
                            id=_opt_id("font"),
                            options=[{"label": "Auto (Arial)", "value": "auto"}],
                            value=defaults.font,
                            clearable=False,
                            searchable=False,
                        ),
                    ),
                ),
                _field("Axis labels (pt)", _number("label_size", 0.5)),
                _field("Tick labels (pt)", _number("tick_size", 0.5)),
                _field("Legend (pt)", _number("legend_size", 0.5), curves_only=True),
            ),
            _group(
                "Legend",
                html.Div(
                    className="png-wide",
                    children=_field(
                        "Position",
                        dcc.Dropdown(
                            id=_opt_id("legend"),
                            options=[{"label": label, "value": key} for key, label in LEGEND_LOCATIONS.items()],
                            value=defaults.legend,
                            clearable=False,
                            searchable=False,
                        ),
                    ),
                ),
                _field("Columns", _number("legend_cols", 1)),
                html.Div(className="png-wide", children=_check("legend_frame", "Frame")),
            
                curves_only=True,
            ),
            _group(
                "Axes",
                _field(
                    "Ticks",
                    dcc.RadioItems(
                        id=_opt_id("tick_direction"),
                        options=[{"label": "In", "value": "in"}, {"label": "Out", "value": "out"}],
                        value=defaults.tick_direction,
                        className="pills pills-compact png-pills",
                        inputClassName="pill-input",
                        labelClassName="pill",
                    ),
                ),
                _field("Tick length (pt)", _number("tick_length", 0.5)),
                _field("Axes width (pt)", _number("axis_width", 0.1)),
                html.Div(className="png-wide png-checks", children=[_check("box", "Box (top and right lines)"), _check("grid", "Grid", curves_only=True)]),
            ),
            _group(
                "Range",
                _field("X min", _number("x_min", "any", placeholder="auto")),
                _field("X max", _number("x_max", "any", placeholder="auto")),
                _field("Y min", _number("y_min", "any", placeholder="auto")),
                _field("Y max", _number("y_max", "any", placeholder="auto")),
                curves_only=True,
            ),
            _group(
                "Labels",
                html.Div(
                    className="png-wide",
                    children=_field(
                        "X label",
                        dcc.Input(id=_opt_id("x_label"), type="text", value="", placeholder="auto", debounce=0.4, className="png-input"),
                    ),
                ),
                html.Div(
                    className="png-wide",
                    children=_field(
                        "Y label",
                        dcc.Input(id=_opt_id("y_label"), type="text", value="", placeholder="auto", debounce=0.4, className="png-input"),
                    ),
                ),
            ),
            _group(
                "Output",
                _field(
                    "Resolution",
                    dcc.Dropdown(
                        id=_opt_id("dpi"),
                        options=[{"label": f"{dpi} dpi", "value": dpi} for dpi in (150, 300, 600, 1200)],
                        value=defaults.dpi,
                        clearable=False,
                        searchable=False,
                    ),
                ),
                html.Div(className="png-wide", children=_check("transparent", "Transparent background")),
            ),
        ],
    )
    preview = html.Div(
        className="png-preview",
        children=[
            html.Div(className="png-canvas", children=html.Img(id="png-preview-img", alt="Preview")),
            html.Div(id="png-preview-info", className="muted small png-info"),
        ],
    )
    return html.Div(
        id="png-modal",
        className="modal",
        children=[
            dcc.Store(id="png-last-target"),
            dcc.Store(id="png-curve-sig"),
            html.Div(id="png-backdrop", className="modal-backdrop", n_clicks=0),
            html.Div(
                className="modal-card",
                role="dialog",
                children=[
                    html.Div(
                        className="modal-head",
                        children=[
                            html.H2(
                                [
                                    html.Span("Export PNG", className="png-title-main"),
                                    html.Span(" · Result", className="png-title-result"),
                                    html.Span(" · Raw inputs", className="png-title-inputs"),
                                    html.Span(" · Detector rows", className="png-title-rows"),
                                ],
                                className="inline",
                            ),
                            html.Button("Reset", id="png-reset", className="btn-link", n_clicks=0),
                        ],
                    ),
                    html.Div(className="modal-body", children=[controls, preview]),
                    html.Div(
                        className="modal-foot",
                        children=[
                            html.Button("Cancel", id="png-cancel", className="btn", n_clicks=0),
                            html.Button("Save PNG…", id="png-save", className="btn btn-primary", n_clicks=0),
                        ],
                    ),
                ],
            ),
        ],
    )



def build_layout() -> html.Div:
    """Build the application layout.

    Returns:
        The root component.
    """
    sidebar = html.Aside(
        className="sidebar",
        children=[
            html.Section(
                className="card",
                children=[
                    html.H2("Measurement"),
                    dcc.Dropdown(
                        id="mode",
                        options=_mode_options(),
                        value="pl",
                        clearable=False,
                        searchable=False,
                    ),
                    html.Div(id="mode-description", className="muted small"),
                ],
            ),
            html.Section(
                className="card",
                children=[
                    html.H2("Inputs"),
                    _upload_slot(Role.SIGNAL),
                    _upload_slot(Role.SUBSTRATE),
                    html.Div(
                        id="optical-slots",
                        children=[_upload_slot(Role.REFERENCE), _upload_slot(Role.DARK)],
                    ),
                ],
            ),
            html.Section(
                className="card",
                children=[
                    html.Div(
                        className="card-head",
                        children=[
                            html.H2("Detector rows", className="inline"),
                            html.Div(
                                [
                                    html.Button("Save PNG", id="rows-png", className="btn-link", n_clicks=0),
                                    html.Button("All rows", id="rows-reset", className="btn-link", n_clicks=0),
                                ]
                            ),
                        ],
                    ),
                    html.Label("Signal", className="field-label"),
                    dcc.Dropdown(id="rows-signal", clearable=False, searchable=False, placeholder="File name"),
                    html.Div(
                        className="field-row",
                        children=[
                            html.Label("Image view", className="field-label"),
                            html.Span(id="rows-hover", className="rows-hover muted small"),
                        ],
                    ),
                    html.Div(
                        className="rows-wrap",
                        children=dcc.Graph(
                            id="rows-graph",
                            config=ROWS_GRAPH_CONFIG,
                            style=ROWS_GRAPH_DEFAULT_STYLE,
                        ),
                    ),
                    html.Div(id="rows-intervals", className="intervals"),
                    html.Button(
                        "+ Add interval", id="rows-add", className="btn-link rows-add", n_clicks=0, style={"display": "none"}
                    ),
                    dcc.Store(id="rows", data=None),
                    dcc.Store(id="rows-intervals-sig", data=None),
                ],
            ),
            html.Section(
                className="card",
                children=[
                    html.H2("Processing"),
                    html.Label("Output quantity", className="field-label"),
                    dcc.Dropdown(id="quantity", clearable=False, searchable=False),
                    html.Label("X axis", className="field-label"),
                    dcc.RangeSlider(
                        id="wl-range",
                        min=0,
                        max=1,
                        value=[0, 1],
                        allowCross=False,
                    ),
                    dcc.RadioItems(
                        id="x-axis",
                        options=[
                            {"label": "Wavelength", "value": XAxis.WAVELENGTH.value},
                            {"label": "Energy", "value": XAxis.ENERGY.value},
                            {"label": "Raman shift", "value": XAxis.RAMAN.value},
                        ],
                        value=XAxis.WAVELENGTH.value,
                        className="pills pills-compact",
                        inputClassName="pill-input",
                        labelClassName="pill",
                    ),
                    html.Div(
                        id="excitation-field",
                        children=[
                            html.Label("Excitation wavelength (nm)", className="field-label"),
                            dcc.Slider(
                                id="excitation",
                                min=LASER_LINES_NM[0],
                                max=LASER_LINES_NM[-1],
                                value=532,
                                step=1,
                                marks={line: str(line) for line in LASER_LINES_NM},
                            ),
                        ],
                    ),
                    html.Label("Normalization", className="field-label"),
                    dcc.Checklist(
                        id="normalize",
                        options=[
                            {"label": "Divide by exposure time", "value": "second"},
                            {"label": "Divide by accumulations", "value": "accumulation"},
                            {"label": "Divided by maximum", "value": "max"},
                        ],
                        value=["second", "accumulation"],
                        className="checks",
                        labelClassName="check",
                    ),
                    html.Label("Smoothing (Savitzky–Golay window)", className="field-label"),
                    dcc.Slider(
                        id="smooth",
                        min=0,
                        max=51,
                        step=1,
                        value=0,
                        marks={0: "off", 11: "11", 21: "21", 31: "31", 51: "51"},
                    ),
                ],
            ),
        ],
    )

    main = html.Main(
        className="content",
        children=[
            html.Section(
                className="card card-plot",
                children=[
                    html.Div(
                        className="card-head",
                        children=[
                            html.Div(
                                [
                                    html.H2("Result", className="inline"),
                                    html.Code(id="formula", className="formula"),
                                ]
                            ),
                        ],
                    ),
                    html.Div(id="alerts"),
                    dcc.Loading(
                        dcc.Graph(id="result-graph", config=GRAPH_CONFIG, style={"height": "460px"}),
                        type="dot",
                        color="#2a78d6",
                    ),
                ],
            ),
            html.Section(
                className="card card-plot",
                children=[
                    html.Div(
                        className="card-head",
                        children=[
                            html.H2("Raw inputs", className="inline"),
                            html.Button("Save PNG", id="inputs-png", className="btn-link", n_clicks=0),
                        ],
                    ),
                    dcc.Graph(id="inputs-graph", config=GRAPH_CONFIG, style={"height": "320px"}),
                ],
            ),
            html.Section(
                className="card",
                children=[html.H2("File metadata"), html.Div(id="metadata")],
            ),
        ],
    )

    return html.Div(
        className="app",
        children=[
            html.Header(
                className="topbar",
                children=[
                    html.Div(
                        [html.Span("SpecDash", className="brand"), html.Span(f"v{__version__}", className="version")]
                    ),
                    html.Div(
                        className="actions",
                        children=[
                            dcc.Dropdown(
                                id="export-format",
                                options=[{"label": fmt.upper(), "value": fmt} for fmt in EXPORT_FORMATS],
                                value=None,
                                placeholder="Export",
                                clearable=False,
                                searchable=False,
                                className="export-menu",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(className="layout", children=[sidebar, main]),
            _png_dialog(),
            # Files loaded by Python (drop / browse) are announced here; see desktop.ingest.
            dcc.Store(id="dropped", data=None),
        ],
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _style_from_form(names: list[str], values: list[Any]) -> PlotStyle:
    """Build a :class:`PlotStyle` from the PNG dialog controls, falling back to defaults for bad input."""
    defaults = PlotStyle()
    kwargs: dict[str, Any] = {}
    for name, value in zip(names, values, strict=True):
        default = getattr(defaults, name)
        if name in _CHECKBOX_FIELDS:
            kwargs[name] = bool(value)
        elif name in _TEXT_FIELDS:
            kwargs[name] = str(value) if value is not None else default
        elif default is None:  # optional limit: empty means automatic
            kwargs[name] = float(value) if isinstance(value, (int, float)) else None
        else:
            low, high = _RANGES[name]
            number = float(value) if isinstance(value, (int, float)) else float(default)
            number = min(max(number, low), high)
            kwargs[name] = int(round(number)) if name in _INT_FIELDS else number
    if kwargs.get("legend") not in LEGEND_LOCATIONS:
        kwargs["legend"] = defaults.legend
    if kwargs.get("tick_direction") not in ("in", "out"):
        kwargs["tick_direction"] = defaults.tick_direction
    return PlotStyle(**kwargs)


def _full_style(
    names: list[str], values: list[Any], curve_ids: list[dict[str, str]], curve_values: list[Any]
) -> PlotStyle:
    """Build the export style from the general and the per-curve controls."""
    return replace(_style_from_form(names, values), curves=_curve_styles(curve_ids, curve_values))


def _form_default(name: str) -> Any:
    """Control value of a :class:`PlotStyle` default."""
    value = getattr(PlotStyle(), name)
    if name in _CHECKBOX_FIELDS:
        return ["on"] if value else []
    return value


def _load(items: StoreData | None) -> list[AndorSpectrum]:
    """Look up the spectra behind a ``dcc.Store`` value."""
    return store.get(items)


def _full_rows(count: int) -> RowsData:
    """One interval covering all ``count`` detector rows."""
    return {"count": count, "ranges": [[1, count]], "active": 0}


def _intervals(rows: RowsData | None) -> list[tuple[int, int]]:
    """The selected one-based row intervals; empty without a selection."""
    return [(int(first), int(last)) for first, last in (rows or {}).get("ranges", [])]


def _build_options(
    normalize: list[str] | None,
    rows: RowsData | None,
    smooth: int | None,
    x_axis: str | None,
    excitation: float | None,
    quantity: str | None,
    wl_range: list[float] | None = None,
) -> Options:
    """Assemble processing options from raw UI values.

    With several row intervals ``rows`` stays unset here: :func:`process_intervals` applies each interval.
    """
    intervals = _intervals(rows)
    normalize = normalize or []
    return Options(
        rows=(intervals[0][0] - 1, intervals[0][1] - 1) if len(intervals) == 1 else None,
        per_second="second" in normalize,
        per_accumulation="accumulation" in normalize,
        divide_max="max" in normalize,
        wavelength_range=(wl_range[0], wl_range[1]) if wl_range else None,
        smooth_window=int(smooth or 0),
        excitation_nm=float(excitation) if excitation else 532.0,
        x_axis=XAxis(x_axis or XAxis.WAVELENGTH),
        quantity=quantity,
    )


def _run(
    mode_key: str,
    stores: dict[Role, StoreData | None],
    options: Options,
    intervals: list[tuple[int, int]],
    signal_index: int | None,
) -> tuple[Mode, list[AndorSpectrum], Result]:
    """Load spectra from stores and process them.

    With one row interval every signal is processed together. With several, only the signal
    picked in the Detector rows card is, once per interval.
    """
    mode = MODES[mode_key]
    signals = _load(stores[Role.SIGNAL])
    backgrounds: dict[Role, AndorSpectrum | None] = {}
    for role in mode.roles[1:]:
        loaded = _load(stores.get(role))
        backgrounds[role] = loaded[0] if loaded else None
    if len(intervals) > 1:
        picked = signal_index if signal_index is not None and signal_index < len(signals) else 0
        signals = signals[picked : picked + 1]
        return mode, signals, process_intervals(mode, signals[0], backgrounds, options, intervals)
    return mode, signals, process(mode, signals, backgrounds, options)


def _interval_row(index: int, first: int, last: int, count: int, removable: bool) -> html.Div:
    """Controls of one row interval: its color (as drawn on the image and in the plots), a slider and a remove button."""
    color = SERIES_COLORS[index % len(SERIES_COLORS)]
    return html.Div(
        className="interval",
        children=[
            html.Div(
                className="interval-head",
                children=[
                    html.Span(className="interval-dot", style={"background": color}),
                    html.Span(f"Interval {index + 1}", className="interval-name"),
                    html.Button(
                        "×",
                        id={"type": "rows-del", "index": index},
                        className="chip-x",
                        n_clicks=0,
                        title="Remove interval",
                    )
                    if removable
                    else None,
                ],
            ),
            dcc.RangeSlider(
                id={"type": "rows-range", "index": index},
                min=1,
                max=count,
                step=1,
                value=[first, last],
                allowCross=False,
            ),
        ],
    )


def _rows_cell(spectrum: AndorSpectrum) -> str:
    """Describe the row count of a spectrum, noting any ignored edge rows."""
    ignored = spectrum.metadata.get("Ignored Rows")
    return f"{spectrum.n_rows} ({ignored} ignored)" if ignored else str(spectrum.n_rows)


def _metadata_table(stores: dict[Role, StoreData | None], mode: Mode) -> html.Table | html.Div:
    """Render a table summarizing the loaded files."""
    rows: list[html.Tr] = []
    for role in mode.roles:
        for spectrum in _load(stores.get(role)):
            wl = spectrum.wavelength
            rows.append(
                html.Tr(
                    [
                        html.Td(html.Span(ROLE_SYMBOLS[role], className=f"badge badge-{role}")),
                        html.Td(spectrum.name, className="mono"),
                        html.Td(f"{spectrum.exposure_time:g} s" if spectrum.exposure_time else "—"),
                        html.Td(str(spectrum.accumulations)),
                        html.Td(spectrum.metadata.get("Acquisition Mode", "—")),
                        html.Td(_rows_cell(spectrum)),
                        html.Td(f"{wl[0]:.1f}–{wl[-1]:.1f} nm ({len(wl)} px)"),
                        html.Td(spectrum.metadata.get("Date and Time", "—")),
                    ]
                )
            )
    if not rows:
        return html.Div("No files loaded.", className="muted small")
    header = html.Tr(
        [
            html.Th(h)
            for h in ("", "File", "Exposure", "Acc.", "Acquisition", "Rows", "Range", "Acquired")
        ]
    )
    return html.Div(html.Table([html.Thead(header), html.Tbody(rows)], className="table"), className="table-wrap")


# --------------------------------------------------------------------------- #
# Callbacks
# --------------------------------------------------------------------------- #


def _register_slot_callbacks(app: Dash, role: Role) -> None:
    """Register upload / clear / file-list callbacks for one role."""
    multiple = role is Role.SIGNAL

    @app.callback(
        Output(f"store-{role}", "data"),
        Output(f"error-{role}", "children"),
        Input("dropped", "data"),
        Input(f"clear-{role}", "n_clicks"),
        Input({"type": "remove", "role": role.value, "index": ALL}, "n_clicks"),
        State(f"store-{role}", "data"),
        prevent_initial_call=True,
    )
    def update_store(
        dropped: dict[str, Any] | None,
        _clear: int,
        _remove: list[int | None],
        current: StoreData | None,
    ) -> tuple[StoreData, str]:
        trigger = ctx.triggered_id
        if trigger == f"clear-{role}":
            store.discard(current)
            return [], ""
        if isinstance(trigger, dict) and trigger.get("type") == "remove":
            if not ctx.triggered or not ctx.triggered[0]["value"]:
                raise PreventUpdate
            index = int(trigger["index"])
            store.discard([s for i, s in enumerate(current or []) if i == index])
            return [s for i, s in enumerate(current or []) if i != index], ""
        if trigger != "dropped" or not dropped or dropped.get("role") != role.value:
            raise PreventUpdate

        loaded: StoreData = dropped["items"]
        errors = " ".join(dropped["errors"])
        if multiple:
            existing = {item["name"] for item in loaded}
            replaced = [s for s in current or [] if s["name"] in existing]
            new_store = [s for s in current or [] if s["name"] not in existing] + loaded
        elif loaded:
            replaced, new_store = list(current or []), loaded[:1]
            store.discard(loaded[1:])
        else:
            replaced, new_store = [], list(current or [])
        store.discard(replaced)
        return new_store, errors

    @app.callback(Output(f"files-{role}", "children"), Input(f"store-{role}", "data"))
    def render_files(store: StoreData | None) -> list[html.Div]:
        return [
            html.Div(
                className="file-chip",
                children=[
                    html.Span(item["name"], className="mono"),
                    html.Button(
                        "×",
                        id={"type": "remove", "role": role.value, "index": i},
                        className="chip-x",
                        n_clicks=0,
                        title="Remove",
                    ),
                ],
            )
            for i, item in enumerate(store or [])
        ]


def register_callbacks(app: Dash) -> None:
    """Register all callbacks on ``app``.

    Args:
        app: The Dash application.
    """
    for role in Role:
        _register_slot_callbacks(app, role)

    store_inputs = [Input(f"store-{role}", "data") for role in Role]

    @app.callback(
        Output("optical-slots", "style"),
        Output("quantity", "options"),
        Output("quantity", "value"),
        Output("x-axis", "value"),
        Output("mode-description", "children"),
        Input("mode", "value"),
        State("x-axis", "value"),
    )
    def on_mode(mode_key: str, x_axis: str) -> tuple[dict[str, str], list[dict[str, str]], str, str, str]:
        mode = MODES[mode_key]
        optical = mode.family is Family.OPTICAL
        options = [{"label": f"{q.label}   ·   {q.formula}", "value": q.key} for q in mode.quantities]
        if mode_key == "raman":
            x_axis = XAxis.RAMAN.value
        elif x_axis == XAxis.RAMAN.value:
            x_axis = XAxis.WAVELENGTH.value
        description = (
            "Inputs: signal S, substrate background B, reference R, dark background D."
            if optical
            else "Inputs: signal S and substrate background B."
        )
        return {"display": "block" if optical else "none"}, options, mode.quantities[0].key, x_axis, description

    @app.callback(
        Output("excitation-field", "style"),
        Input("x-axis", "value"),
    )
    def on_x_axis(x_axis: str) -> dict[str, str]:
        return {"display": "block" if x_axis == XAxis.RAMAN.value else "none"}

    @app.callback(
        Output("wl-range", "min"),
        Output("wl-range", "max"),
        Output("wl-range", "value"),
        Input(f"store-{Role.SIGNAL}", "data"),
        State("wl-range", "value"),
        State("wl-range", "max"),
    )
    def on_wl_range(
        signals: StoreData | None, current: list[float], old_max: float
    ) -> tuple[int, int, list[float]]:
        if not signals:
            return 0, 1, [0, 1]
        lo, hi = math.floor(signals[0]["wl"][0]), math.ceil(signals[0]["wl"][1])
        if old_max > 1:  # keep the user's selection, clipped to the new bounds
            kept = [max(current[0], lo), min(current[1], hi)]
            if kept[0] < kept[1]:
                return lo, hi, kept
        return lo, hi, [lo, hi]

    @app.callback(
        Output("smooth", "value"),
        Input("smooth", "value"),
        prevent_initial_call=True,
    )
    def on_smooth(window: int | None) -> int:
        """Keep the smoothing window at 0 (off) or an odd length of at least 3."""
        if window is None or window <= 0:
            return 0
        return max(3, int(window) | 1)

    @app.callback(
        Output("rows", "data"),
        Input(f"store-{Role.SIGNAL}", "data"),
        Input("rows-reset", "n_clicks"),
        State("rows", "data"),
    )
    def on_rows(*args: Any) -> RowsData | None:
        signals, _reset, current = args
        counts = [item["n_rows"] for item in signals or []]
        if not counts:
            return None
        count = min(counts)
        if not current or current["count"] != count:
            return _full_rows(count)
        if ctx.triggered_id == "rows-reset":  # "All rows" resets the selected interval only
            ranges = [list(r) for r in current["ranges"]]
            active = min(int(current.get("active", 0)), len(ranges) - 1)
            ranges[active] = [1, count]
            return {"count": count, "ranges": ranges, "active": active}
        return current

    @app.callback(
        Output("rows-intervals", "children"),
        Output("rows-intervals-sig", "data"),
        Output("rows-add", "style"),
        Output("rows-add", "disabled"),
        Input("rows", "data"),
        State("rows-intervals-sig", "data"),
    )
    def render_intervals(rows: RowsData | None, last: list[int] | None) -> tuple[Any, Any, Any, bool]:
        """Build one slider per interval; sliders are kept (not rebuilt) while only their values change."""
        if not rows or rows["count"] <= 1:
            return [], None, {"display": "none"}, True
        signature = [rows["count"], len(rows["ranges"])]
        if signature == last:
            raise PreventUpdate
        ranges = rows["ranges"]
        children: list[Any] = [
            _interval_row(i, first, last_, rows["count"], removable=len(ranges) > 1)
            for i, (first, last_) in enumerate(ranges)
        ]
        return children, signature, {"display": "inline-block"}, len(ranges) >= MAX_INTERVALS

    @app.callback(
        Output({"type": "rows-range", "index": ALL}, "value"),
        Input("rows", "data"),
        State({"type": "rows-range", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def sync_sliders(rows: RowsData | None, current: list[list[int]]) -> list[Any]:
        """Move the sliders when the intervals were changed on the image."""
        ranges = (rows or {}).get("ranges", [])
        if len(current) != len(ranges):
            raise PreventUpdate  # the sliders are being rebuilt with the right values
        out = [no_update if list(now) == list(want) else list(want) for now, want in zip(current, ranges, strict=True)]
        if all(value is no_update for value in out):
            raise PreventUpdate
        return out

    @app.callback(
        Output("rows", "data", allow_duplicate=True),
        Input({"type": "rows-range", "index": ALL}, "value"),
        Input({"type": "rows-del", "index": ALL}, "n_clicks"),
        Input("rows-add", "n_clicks"),
        State("rows", "data"),
        prevent_initial_call=True,
    )
    def edit_intervals(values: list[Any], _dels: list[int | None], _add: int | None, rows: RowsData | None) -> RowsData:
        """Apply a slider move, add an interval or remove one."""
        if not rows or not ctx.triggered:
            raise PreventUpdate
        trigger = ctx.triggered_id
        count = rows["count"]
        ranges = [list(r) for r in rows["ranges"]]
        active = int(rows.get("active", 0))
        if trigger == "rows-add":
            if not ctx.triggered[0]["value"] or len(ranges) >= MAX_INTERVALS:
                raise PreventUpdate
            # As wide as the selected interval, placed right after it (moved back to fit within the rows).
            first, last = ranges[active] if 0 <= active < len(ranges) else (1, count)
            width = last - first + 1
            start = max(1, min(last + 1, count - width + 1))
            ranges.append([start, start + width - 1])
            active = len(ranges) - 1
        elif isinstance(trigger, dict) and trigger.get("type") == "rows-del":
            if not ctx.triggered[0]["value"] or len(ranges) <= 1 or not 0 <= trigger["index"] < len(ranges):
                raise PreventUpdate
            del ranges[trigger["index"]]
            active = min(active, len(ranges) - 1)
        elif isinstance(trigger, dict) and trigger.get("type") == "rows-range":
            index = trigger["index"]
            if len(values) != len(ranges) or not 0 <= index < len(ranges) or None in values[index]:
                raise PreventUpdate
            new = [min(max(int(round(v)), 1), count) for v in values[index]]
            if new[0] > new[1] or new == ranges[index]:
                raise PreventUpdate
            ranges[index] = new
            active = index
        else:
            raise PreventUpdate
        return {"count": count, "ranges": ranges, "active": active}

    @app.callback(
        Output("rows-signal", "options"),
        Output("rows-signal", "value"),
        Output("rows-signal", "disabled"),
        Input(f"store-{Role.SIGNAL}", "data"),
        State("rows-signal", "value"),
    )
    def on_rows_signal(signals: StoreData | None, current: int | None) -> tuple[list[dict[str, Any]], int | None, bool]:
        options = [{"label": item["name"], "value": i} for i, item in enumerate(signals or [])]
        if not options:
            return options, None, True
        return options, current if current is not None and current < len(options) else 0, False

    @app.callback(
        Output("rows-graph", "figure"),
        Output("rows-graph", "style"),
        Input(f"store-{Role.SIGNAL}", "data"),
        Input("rows", "data"),
        Input("rows-signal", "value"),
    )
    def update_rows_image(
        signals: StoreData | None, rows: RowsData | None, index: int | None
    ) -> tuple[Any, dict[str, str]]:
        if not signals:
            return empty_figure("Upload a signal spectrum"), ROWS_GRAPH_DEFAULT_STYLE
        spectrum = _load([signals[index if index is not None and index < len(signals) else 0]])[0]
        intervals = _intervals(rows)
        figure = rows_figure(
            spectrum,
            intervals or None,
            rows["count"] if rows else None,
            int(rows.get("active", 0)) if rows else 0,
        )
        ratio = image_ratio(spectrum.wavelength, spectrum.n_rows)
        style = {"height": f"calc(100cqw * {ratio:.4f} + {ROWS_PLOT_CHROME_PX}px)"}
        return figure, style

    @app.callback(
        Output("result-graph", "figure"),
        Output("inputs-graph", "figure"),
        Output("formula", "children"),
        Output("alerts", "children"),
        Output("metadata", "children"),
        Input("mode", "value"),
        Input("quantity", "value"),
        Input("normalize", "value"),
        Input("rows", "data"),
        Input("smooth", "value"),
        Input("x-axis", "value"),
        Input("excitation", "value"),
        Input("wl-range", "value"),
        Input("rows-signal", "value"),
        *store_inputs,
    )
    def update_plots(
        mode_key: str,
        quantity: str | None,
        normalize: list[str] | None,
        rows: RowsData | None,
        smooth: int | None,
        x_axis: str | None,
        excitation: float | None,
        wl_range: list[float] | None,
        signal_index: int | None,
        *stores: StoreData | None,
    ) -> tuple[Any, Any, str, list[html.Div], Any]:
        intervals = _intervals(rows)
        if ctx.triggered_id == "rows-signal" and len(intervals) <= 1:
            raise PreventUpdate  # the picked file only matters while several intervals are compared
        store_map = dict(zip(Role, stores, strict=True))
        mode = MODES[mode_key]
        quantity_obj = mode.quantity(quantity)
        meta = _metadata_table(store_map, mode)
        if not store_map[Role.SIGNAL]:
            hint = empty_figure("Upload a signal spectrum to begin")
            return hint, empty_figure("No inputs yet"), quantity_obj.formula, [], meta
        options = _build_options(normalize, rows, smooth, x_axis, excitation, quantity, wl_range)
        try:
            _, signals, result = _run(mode_key, store_map, options, intervals, signal_index)
        except ValueError as exc:
            alert = html.Div(str(exc), className="alert alert-error")
            return empty_figure(str(exc)), no_update, quantity_obj.formula, [alert], meta
        order = [s.name for s in signals]
        alerts = [html.Div(w, className="alert") for w in result.warnings]
        return result_figure(result, order), inputs_figure(result, order), result.formula, alerts, meta

    process_states = [
        State("mode", "value"),
        State("quantity", "value"),
        State("normalize", "value"),
        State("rows", "data"),
        State("smooth", "value"),
        State("x-axis", "value"),
        State("excitation", "value"),
        State("wl-range", "value"),
        *[State(f"store-{role}", "data") for role in Role],
        State("rows-signal", "value"),
    ]

    def run_current(
        mode_key: str,
        quantity: str | None,
        normalize: list[str] | None,
        rows: RowsData | None,
        smooth: int | None,
        x_axis: str | None,
        excitation: float | None,
        wl_range: list[float] | None,
        stores: tuple[StoreData | None, ...],
        signal_index: int | None,
    ) -> tuple[Mode, list[AndorSpectrum], Result] | None:
        """Process the current UI state, or return ``None`` when there is nothing to export."""
        store_map = dict(zip(Role, stores, strict=True))
        if not store_map[Role.SIGNAL]:
            return None
        options = _build_options(normalize, rows, smooth, x_axis, excitation, quantity, wl_range)
        try:
            return _run(mode_key, store_map, options, _intervals(rows), signal_index)
        except ValueError:
            return None

    # The PNG dialog is opened by the Export menu (Result), and by the Save PNG buttons of the Raw inputs
    # and Detector rows cards. Its target is kept in the dialog's class ("modal open target-<name>").
    reset_on_target_change = ["x_label", "y_label", "x_min", "x_max", "y_min", "y_max"]

    @app.callback(
        Output("export-format", "value"),
        Output("png-modal", "className"),
        Output("png-last-target", "data"),
        Output({"type": PNG_OPT, "name": ALL}, "value", allow_duplicate=True),
        Input("export-format", "value"),
        Input("inputs-png", "n_clicks"),
        Input("rows-png", "n_clicks"),
        State("png-last-target", "data"),
        State({"type": PNG_OPT, "name": ALL}, "id"),
        State({"type": PNG_OPT, "name": ALL}, "value"),
        *process_states,
        prevent_initial_call=True,
    )
    def open_or_export(
        fmt: str | None,
        _inputs_clicks: int | None,
        _rows_clicks: int | None,
        last_target: str | None,
        ids: list[dict[str, str]],
        values: list[Any],
        *state: Any,
    ) -> tuple[None, Any, Any, Any]:
        trigger = ctx.triggered_id
        keep = (None, no_update, no_update, [no_update] * len(ids))
        if trigger == "export-format":
            if fmt not in EXPORT_FORMATS:
                raise PreventUpdate
            target = "result" if fmt == "png" else None
        elif not ctx.triggered or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        else:
            target = "inputs" if trigger == "inputs-png" else "rows"
        args, stores, signal_index = state[:8], state[8:12], state[12]

        if target == "rows":
            if not stores[0]:
                return keep
        else:
            current = run_current(*args, tuple(stores), signal_index)
            if current is None:
                return keep
            mode, signals, result = current
            if target is None:  # a data format: save straight away
                quantity_key = mode.quantity(args[1]).key
                desktop.save_bytes(
                    f"{Path(signals[0].name).stem}_{mode.key}_{quantity_key}.{fmt}", export_bytes(result, mode, fmt)
                )
                return keep
        # Labels and ranges belong to one figure; do not carry them over to another.
        fresh = target != last_target
        updated = [
            _form_default(i["name"]) if fresh and i["name"] in reset_on_target_change else no_update for i in ids
        ]
        return None, f"modal open target-{target}", target, updated

    def dialog_target(css: str) -> str | None:
        """Target of an open dialog, or ``None`` while it is closed."""
        classes = css.split()
        if "open" not in classes:
            return None
        return next((c.removeprefix("target-") for c in classes if c.startswith("target-")), "result")

    @app.callback(
        Output("png-modal", "className", allow_duplicate=True),
        Input("png-cancel", "n_clicks"),
        Input("png-backdrop", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_png_dialog(*_clicks: int | None) -> str:
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        return "modal"

    @app.callback(
        Output({"type": PNG_OPT, "name": "font"}, "options"),
        Input("png-modal", "className"),
        State({"type": PNG_OPT, "name": "font"}, "options"),
    )
    def load_fonts(css: str, current: list[dict[str, str]]) -> list[dict[str, str]]:
        """List the installed fonts the first time the dialog opens (importing matplotlib is slow)."""
        if dialog_target(css) is None or len(current) > 1:
            raise PreventUpdate
        installed = mplexport.available_fonts()
        auto = {"label": "Auto (Arial)", "value": "auto"}
        return [auto, *({"label": family, "value": family} for family in installed)]

    @app.callback(
        Output("png-curve-rows", "children"),
        Output("png-curve-sig", "data"),
        Input("png-modal", "className"),
        Input("png-reset", "n_clicks"),
        State("png-curve-sig", "data"),
        *process_states,
        prevent_initial_call=True,
    )
    def render_curve_rows(css: str, _reset: int | None, last: dict[str, Any] | None, *state: Any) -> tuple[Any, Any]:
        """List the curves of the figure being exported, each with its default look.

        The rows (and so any edits) are kept while the curves stay the same, and rebuilt
        when they change or the dialog is reset.
        """
        target = dialog_target(css)
        if target is None:
            raise PreventUpdate
        current = run_current(*state[:8], tuple(state[8:12]), state[12]) if target != "rows" else None
        if current is None:
            return [], {"curves": [], "stamp": time.time_ns()}
        _, signals, result = current
        defaults = mplexport.curve_defaults(result, [s.name for s in signals], target)
        curves = [list(d) for d in defaults]
        if ctx.triggered_id != "png-reset" and last and last["curves"] == curves:
            raise PreventUpdate
        return [_curve_row(*d) for d in defaults], {"curves": curves, "stamp": time.time_ns()}

    @app.callback(
        Output({"type": PNG_OPT, "name": ALL}, "value"),
        Input("png-reset", "n_clicks"),
        State({"type": PNG_OPT, "name": ALL}, "id"),
        prevent_initial_call=True,
    )
    def reset_png_options(clicks: int | None, ids: list[dict[str, str]]) -> list[Any]:
        if not clicks:
            raise PreventUpdate
        return [_form_default(i["name"]) for i in ids]

    def render_png(target: str, style: PlotStyle, state: tuple[Any, ...], dpi: int | None) -> tuple[bytes, str] | None:
        """Draw the dialog's figure; returns the PNG and a suggested file name, or ``None`` without data."""
        args, stores, rows_index = state[:8], state[8:12], state[12]
        if target == "rows":
            signals = stores[0]
            if not signals:
                return None
            spectrum = _load([signals[rows_index if rows_index is not None and rows_index < len(signals) else 0]])[0]
            rows = args[3]
            content = mplexport.rows_png(
                spectrum.wavelength,
                spectrum.frames,
                _intervals(rows) or None,
                style,
                dpi,
            )
            return content, f"{Path(spectrum.name).stem}_rows.png"
        current = run_current(*args, tuple(stores), rows_index)
        if current is None:
            return None
        mode, signals, result = current
        order = [s.name for s in signals]
        stem = Path(signals[0].name).stem
        if target == "inputs":
            return mplexport.inputs_png(result, order, style, dpi), f"{stem}_{mode.key}_inputs.png"
        return mplexport.result_png(result, order, style, dpi), f"{stem}_{mode.key}_{mode.quantity(args[1]).key}.png"

    dialog_states = process_states

    @app.callback(
        Output("png-preview-img", "src"),
        Output("png-preview-info", "children"),
        Input("png-modal", "className"),
        Input({"type": PNG_OPT, "name": ALL}, "value"),
        Input(CURVE_PATTERN, "value"),
        Input("png-curve-sig", "data"),  # rebuilt curve rows: wait for them, then draw once
        State({"type": PNG_OPT, "name": ALL}, "id"),
        State(CURVE_PATTERN, "id"),
        *dialog_states,
        prevent_initial_call=True,
    )
    def update_png_preview(
        css: str,
        values: list[Any],
        curve_values: list[Any],
        _curves: Any,
        ids: list[dict[str, str]],
        curve_ids: list[dict[str, str]],
        *state: Any,
    ) -> tuple[Any, Any]:
        target = dialog_target(css)
        if target is None:
            raise PreventUpdate
        style = _full_style([i["name"] for i in ids], values, curve_ids, curve_values)
        rendered = render_png(target, style, state, mplexport.preview_dpi(style))
        if rendered is None:
            return no_update, "Nothing to export."
        content = rendered[0]
        scale = style.dpi / mplexport.preview_dpi(style)
        width, height = (round(side * scale) for side in mplexport.png_size(content))
        info = f"Axes {style.width_cm:g} cm wide · saved as {width} × {height} px at {style.dpi} dpi"
        return "data:image/png;base64," + base64.b64encode(content).decode(), info

    @app.callback(
        Output("png-modal", "className", allow_duplicate=True),
        Input("png-save", "n_clicks"),
        State("png-modal", "className"),
        State({"type": PNG_OPT, "name": ALL}, "value"),
        State({"type": PNG_OPT, "name": ALL}, "id"),
        State(CURVE_PATTERN, "value"),
        State(CURVE_PATTERN, "id"),
        *dialog_states,
        prevent_initial_call=True,
    )
    def save_png(
        clicks: int | None,
        css: str,
        values: list[Any],
        ids: list[dict[str, str]],
        curve_values: list[Any],
        curve_ids: list[dict[str, str]],
        *state: Any,
    ) -> Any:
        target = dialog_target(css)
        if not clicks or target is None:
            raise PreventUpdate
        style = _full_style([i["name"] for i in ids], values, curve_ids, curve_values)
        rendered = render_png(target, style, state, None)
        if rendered is None:
            raise PreventUpdate
        content, name = rendered
        return "modal" if desktop.save_bytes(name, content) else no_update  # stay open when the dialog was cancelled


PLOTLY_URL = "/_dash-component-suites/plotly/package_data/plotly.min.js"
"""Where dash-renderer fetches plotly.js from (hard-coded in the renderer)."""


def _use_slim_plotly(app: Dash) -> None:
    """Serve the slim plotly.js bundle (core + scatter + heatmap) instead of the full one.

    ``dcc.Graph`` fetches the 4.8 MB plotly.js with every trace type from
    ``PLOTLY_URL``. Answering that request from ``vendor/plotly-slim.min.js``
    (1.1 MB, built by ``tools/plotly-bundle``) keeps the identical Plotly API
    while loading far less, and lets the bundle drop the plotly package's copy.
    """
    slim = ASSETS_DIR.parent / SLIM_PLOTLY
    # Point Dash's own bookkeeping at our file too, so it never looks for the plotly package's copy.
    for resource in dcc._js_dist:
        if resource.get("namespace") == "plotly":
            resource.update(namespace="specdash", relative_package_path=SLIM_PLOTLY)

    @app.server.before_request
    def serve_slim_plotly() -> Any:
        if request.path == PLOTLY_URL:
            return send_file(slim, mimetype="text/javascript", max_age=86400)
        return None


def create_app() -> Dash:
    """Create and configure the Dash application.

    Returns:
        The configured application.
    """
    app = Dash(
        __name__,
        title="SpecDash",
        assets_folder=str(ASSETS_DIR),
        suppress_callback_exceptions=True,
        update_title=None,
    )
    _use_slim_plotly(app)
    app.layout = build_layout()
    register_callbacks(app)
    return app
