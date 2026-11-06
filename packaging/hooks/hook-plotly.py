"""Trimmed PyInstaller hook for Plotly.

The app serves its own slim plotly.js (``specdash/vendor``), so the 4.8 MB
``package_data/plotly.min.js`` is not bundled. The Jupyter widget bundle and
sample datasets are dead weight, and the stock hook force-adds ``pandas``,
which this app does not use.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files(
    "plotly",
    includes=["package_data/templates/*", "validators/**/*.*"],
)
hiddenimports = collect_submodules("plotly.validators") + ["cmath"]
