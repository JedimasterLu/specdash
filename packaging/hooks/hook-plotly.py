"""Trimmed PyInstaller hook for Plotly.

Dash's ``dcc.Graph`` loads ``plotly/package_data/plotly.min.js`` from the
plotly package (served at ``/_dash-component-suites/plotly/package_data/``), so
it must be bundled or no graph can render. The Jupyter widget bundle and
sample datasets are dead weight. The stock hook also force-adds ``pandas``,
which this app does not use.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files(
    "plotly",
    includes=["package_data/templates/*", "package_data/plotly.min.js", "validators/**/*.*"],
)
hiddenimports = collect_submodules("plotly.validators") + ["cmath"]
