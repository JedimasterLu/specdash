"""Dash application: layout and callbacks."""

from __future__ import annotations

import base64
import math
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from specdash import __version__, lifecycle
from specdash.figures import GRAPH_CONFIG, empty_figure, image_ratio, inputs_figure, result_figure, rows_figure
from specdash.io import AndorSpectrum, parse_asc
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
)

ASSETS_DIR = Path(__file__).parent / "assets"

ROLE_HINTS: dict[Role, str] = {
    Role.SIGNAL: "Sample spectrum. Multiple files are processed together.",
    Role.SUBSTRATE: "Bare substrate next to the sample.",
    Role.REFERENCE: "Lamp / white standard / mirror spectrum.",
    Role.DARK: "Light source blocked or off.",
}

StoreData = list[dict[str, Any]]
# Parsed spectra stay on the server; the browser stores only small descriptors.
_SPECTRA: dict[str, AndorSpectrum] = {}
RowsData = dict[str, int]

ROWS_GRAPH_DEFAULT_STYLE = {"height": "72px"}
ROWS_PLOT_CHROME_PX = 52
"""Vertical space taken by the top and bottom margins of the image graph."""

LASER_LINES_NM = (325, 405, 532, 633, 785, 1064)
"""Popular excitation wavelengths marked on the excitation slider, from UV to NIR."""

EXPORT_FORMATS = ("csv", "txt", "npy", "json")

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
            dcc.Upload(
                id=f"upload-{role}",
                multiple=multiple,
                accept=".asc,.txt,.csv",
                className="dropzone",
                style_active={
                    "borderStyle": "dashed",
                    "borderColor": "var(--accent)",
                    "backgroundColor": "var(--accent-soft)",
                },
                children=html.Div(
                    [
                        "Drop ",
                        html.B(".asc" + (" files" if multiple else " file")),
                        " or ",
                        html.Span("browse", className="link"),
                    ]
                ),
            ),
            html.Div(id=f"files-{role}", className="file-list"),
            html.Div(id=f"error-{role}", className="slot-error"),
            dcc.Store(id=f"store-{role}", data=[]),
        ],
    )


def _mode_options() -> list[dict[str, Any]]:
    """Dropdown options for the measurement mode selector."""
    return [{"label": mode.label, "value": key} for key, mode in MODES.items()]


def build_layout(quit_button: bool = False) -> html.Div:
    """Build the application layout.

    Args:
        quit_button: Show a button that stops the server and make pages report their
            presence, for builds without a console.

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
                            html.Button("All rows", id="rows-reset", className="btn-link", n_clicks=0),
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
                    html.Div(id="rows-label", className="muted small"),
                    dcc.Store(id="rows", data=None),
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
                    html.H2("Raw inputs"),
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
                            dcc.Download(id="download"),
                            *(
                                [
                                    html.Button("Quit", id="quit", className="btn", n_clicks=0),
                                    html.Span(id="quit-status", className="muted small"),
                                ]
                                if quit_button
                                else []
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(className="layout", children=[sidebar, main]),
            *([html.Div(id="heartbeat", hidden=True)] if quit_button else []),
        ],
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _decode_upload(contents: str, filename: str) -> AndorSpectrum:
    """Decode a ``dcc.Upload`` payload into a spectrum.

    Args:
        contents: Data URL produced by ``dcc.Upload``.
        filename: Original file name.

    Returns:
        The parsed spectrum.
    """
    _, _, payload = contents.partition(",")
    raw = base64.b64decode(payload)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return parse_asc(text, name=filename)


def _load(store: StoreData | None) -> list[AndorSpectrum]:
    """Deserialize spectra from a ``dcc.Store``."""
    return [_SPECTRA[item["id"]] for item in store or [] if item["id"] in _SPECTRA]


def _register(spectrum: AndorSpectrum) -> dict[str, Any]:
    """Keep ``spectrum`` on the server and return its descriptor for a ``dcc.Store``."""
    key = uuid.uuid4().hex
    _SPECTRA[key] = spectrum
    wl = spectrum.wavelength
    return {"id": key, "name": spectrum.name, "n_rows": spectrum.n_rows, "wl": [float(wl[0]), float(wl[-1])]}


def _build_options(
    normalize: list[str] | None,
    rows: RowsData | None,
    smooth: int | None,
    x_axis: str | None,
    excitation: float | None,
    quantity: str | None,
    wl_range: list[float] | None = None,
) -> Options:
    """Assemble processing options from raw UI values."""
    normalize = normalize or []
    return Options(
        rows=(rows["first"] - 1, rows["last"] - 1) if rows else None,
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
) -> tuple[Mode, list[AndorSpectrum], Result]:
    """Load spectra from stores and process them."""
    mode = MODES[mode_key]
    signals = _load(stores[Role.SIGNAL])
    backgrounds: dict[Role, AndorSpectrum | None] = {}
    for role in mode.roles[1:]:
        loaded = _load(stores.get(role))
        backgrounds[role] = loaded[0] if loaded else None
    return mode, signals, process(mode, signals, backgrounds, options)


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
        Output(f"upload-{role}", "contents"),
        Input(f"upload-{role}", "contents"),
        Input(f"clear-{role}", "n_clicks"),
        Input({"type": "remove", "role": role.value, "index": ALL}, "n_clicks"),
        State(f"upload-{role}", "filename"),
        State(f"store-{role}", "data"),
        prevent_initial_call=True,
    )
    def update_store(
        contents: str | list[str] | None,
        _clear: int,
        _remove: list[int | None],
        filenames: str | list[str] | None,
        store: StoreData | None,
    ) -> tuple[StoreData, str, None]:
        trigger = ctx.triggered_id
        if trigger == f"clear-{role}":
            return [], "", None
        if isinstance(trigger, dict) and trigger.get("type") == "remove":
            if not ctx.triggered or not ctx.triggered[0]["value"]:
                raise PreventUpdate
            index = int(trigger["index"])
            return [s for i, s in enumerate(store or []) if i != index], "", None
        if not contents:
            raise PreventUpdate

        content_list = contents if isinstance(contents, list) else [contents]
        name_list = filenames if isinstance(filenames, list) else [filenames or "file.asc"]
        loaded: StoreData = []
        errors: list[str] = []
        for content, name in zip(content_list, name_list, strict=False):
            try:
                loaded.append(_register(_decode_upload(content, name)))
            except (ValueError, UnicodeDecodeError) as exc:
                errors.append(str(exc))
        if multiple:
            existing = {item["name"] for item in loaded}
            new_store = [s for s in store or [] if s["name"] not in existing] + loaded
        else:
            new_store = loaded[:1] if loaded else list(store or [])
        return new_store, " ".join(errors), None

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
        if ctx.triggered_id == "rows-reset" or not current or current["count"] != count:
            return {"first": 1, "last": count, "count": count}
        return current

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
        Output("rows-label", "children"),
        Input(f"store-{Role.SIGNAL}", "data"),
        Input("rows", "data"),
        Input("rows-signal", "value"),
    )
    def update_rows_image(
        signals: StoreData | None, rows: RowsData | None, index: int | None
    ) -> tuple[Any, dict[str, str], str]:
        if not signals:
            return empty_figure("Upload a signal spectrum"), ROWS_GRAPH_DEFAULT_STYLE, ""
        spectrum = _load([signals[index if index is not None and index < len(signals) else 0]])[0]
        figure = rows_figure(
            spectrum.wavelength,
            spectrum.frames,
            (rows["first"], rows["last"]) if rows else None,
            rows["count"] if rows else None,
        )
        ratio = image_ratio(spectrum.wavelength, spectrum.n_rows)
        style = {"height": f"calc(100cqw * {ratio:.4f} + {ROWS_PLOT_CHROME_PX}px)"}
        if not rows or rows["count"] <= 1:
            return figure, style, "Single detector row"
        if rows["first"] == rows["last"]:
            label = f"Row {rows['first']} of {rows['count']}"
        else:
            n = rows["last"] - rows["first"] + 1
            label = f"Rows {rows['first']}–{rows['last']} of {rows['count']} averaged ({n})"
        return figure, style, label

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
        *stores: StoreData | None,
    ) -> tuple[Any, Any, str, list[html.Div], Any]:
        store_map = dict(zip(Role, stores, strict=True))
        mode = MODES[mode_key]
        quantity_obj = mode.quantity(quantity)
        meta = _metadata_table(store_map, mode)
        if not store_map[Role.SIGNAL]:
            hint = empty_figure("Upload a signal spectrum to begin")
            return hint, empty_figure("No inputs yet"), quantity_obj.formula, [], meta
        options = _build_options(normalize, rows, smooth, x_axis, excitation, quantity, wl_range)
        try:
            _, signals, result = _run(mode_key, store_map, options)
        except ValueError as exc:
            alert = html.Div(str(exc), className="alert alert-error")
            return empty_figure(str(exc)), no_update, quantity_obj.formula, [alert], meta
        order = [s.name for s in signals]
        alerts = [html.Div(w, className="alert") for w in result.warnings]
        return result_figure(result, order), inputs_figure(result, order), result.formula, alerts, meta

    @app.callback(
        Output("download", "data"),
        Output("export-format", "value"),
        Input("export-format", "value"),
        State("mode", "value"),
        State("quantity", "value"),
        State("normalize", "value"),
        State("rows", "data"),
        State("smooth", "value"),
        State("x-axis", "value"),
        State("excitation", "value"),
        State("wl-range", "value"),
        *[State(f"store-{role}", "data") for role in Role],
        prevent_initial_call=True,
    )
    def export(
        fmt: str | None,
        mode_key: str,
        quantity: str | None,
        normalize: list[str] | None,
        rows: RowsData | None,
        smooth: int | None,
        x_axis: str | None,
        excitation: float | None,
        wl_range: list[float] | None,
        *stores: StoreData | None,
    ) -> tuple[Any, None]:
        if fmt not in EXPORT_FORMATS:
            raise PreventUpdate
        store_map = dict(zip(Role, stores, strict=True))
        if not store_map[Role.SIGNAL]:
            return no_update, None
        options = _build_options(normalize, rows, smooth, x_axis, excitation, quantity, wl_range)
        try:
            mode, signals, result = _run(mode_key, store_map, options)
        except ValueError:
            return no_update, None
        content = export_bytes(result, mode, fmt)
        stem = Path(signals[0].name).stem
        quantity_key = mode.quantity(quantity).key
        return dcc.send_bytes(content, filename=f"{stem}_{mode.key}_{quantity_key}.{fmt}"), None


def register_quit_callback(app: Dash) -> None:
    """Register the callback behind the Quit button.

    Args:
        app: The Dash application.
    """

    @app.callback(
        Output("quit-status", "children"),
        Input("quit", "n_clicks"),
        prevent_initial_call=True,
    )
    def quit_app(_clicks: int) -> str:
        # Exit after the response has been sent so the page can show the message.
        threading.Timer(0.5, os._exit, args=(0,)).start()
        return "SpecDash stopped. You can close this tab."


def create_app(quit_button: bool = False) -> Dash:
    """Create and configure the Dash application.

    Args:
        quit_button: Add a Quit button and quit automatically when the last
            browser tab closes. Needed when the app runs without a console
            window that could be closed instead.

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
    app.layout = build_layout(quit_button)
    register_callbacks(app)
    if quit_button:
        register_quit_callback(app)
        lifecycle.install(app.server)
    return app
