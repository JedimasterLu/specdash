"""Trimmed PyInstaller hook for Dash.

The stock hook bundles every data file shipped with Dash, including source
maps, JavaScript test fixtures and development bundles that are never served
in production mode. Skipping them noticeably shrinks the frozen app.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files(
    "dash",
    excludes=[
        "**/*.map",
        "**/*.md",
        "**/*.tgz",
        "**/.gitkeep",
        "**/*_test*.js",
        "**/*_tests*.js",
        "**/demo.js",
        "**/*.dev.js",
        "testing/**",
    ],
)
hiddenimports = collect_submodules("dash.backends")
