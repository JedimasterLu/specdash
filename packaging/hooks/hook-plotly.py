"""Trimmed PyInstaller hook for Plotly.

Dash serves its own copy of plotly.js, so the offline ``plotly.min.js`` and
Jupyter widget bundles in ``plotly/package_data`` are dead weight. Only the
figure templates are needed at runtime. The stock hook also force-adds
``pandas``, which this app does not use.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files(
    "plotly",
    includes=["package_data/templates/*", "validators/**/*.*"],
)
hiddenimports = collect_submodules("plotly.validators") + ["cmath"]
