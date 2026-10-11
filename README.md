# SpecDash

Interactive web app for processing Andor Solis `.asc` spectra, built with Plotly Dash.

## Download for Windows

No Python needed. Download `SpecDash-<version>-windows-x64.zip` (or the smaller `.7z`) from the
[Releases](../../releases) page, extract it, and double-click `SpecDash\SpecDash.exe`.
A console window opens and the app appears in your browser; close the console window to quit.

- On first launch Windows SmartScreen may warn about an unknown publisher (the exe is not
  code-signed). Click **More info → Run anyway**.
- Extract the whole folder before running; the exe does not work from inside the zip.
- If port 8050 is busy, a free port is chosen automatically; the address is printed in the console.

## Install & run (from source)

```bash
# with uv (from the project directory)
uv sync
uv run specdash

# or as a global tool
uv tool install .
specdash

# with pip
pip install .
specdash
```

Options: `specdash --port 8050 --host 127.0.0.1 --no-browser --debug`. `python -m specdash` also works.

## Measurement modes

Every input is averaged over the selected detector rows and, by default, normalized to
**counts/s per accumulation** using `Exposure Time (secs)` and `Number of Accumulations`
from the file footer. Backgrounds are interpolated onto the wavelength grid of the first signal.

| Mode | Inputs | Output quantities |
|---|---|---|
| Photoluminescence, Fluorescence, Raman | S, B | `S − B`, `S` |
| Dark-field scattering | S, B, R, D | `(S − B) / (R − D)`, `(S − D) / (R − D)` |
| Transmission | S, B, R, D | `(S − D) / (B − D)`, `(S − D) / (R − D)`, `1 − T/T₀`, `−log₁₀(T/T₀)` |
| Reflection | S, B, R, D | `(S − D) / (B − D)`, `(S − D) / (R − D)`, `(S − B) / (B − D)` |

S = signal (several files allowed), B = substrate background, R = reference, D = dark background.
Missing optional inputs are treated as zero, and the app shows a warning when that happens.

## Features

- Interactive plots (zoom, pan, hover crosshair, SVG snapshot from the mode bar).
- X axis in wavelength, photon energy or Raman shift (configurable excitation wavelength).
- Optional Savitzky–Golay smoothing and detector-row selection.
- Export the processed curves, plus the normalized inputs if you choose, as CSV or tab-separated TXT.

## Building the Windows executable

Releases are built by GitHub Actions ([build-windows.yml](.github/workflows/build-windows.yml)).
Bump the version in `pyproject.toml` and `src/specdash/__init__.py`, then push a matching tag:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The workflow builds a one-folder PyInstaller bundle, smoke-tests it (starts the exe and requests
the page and every bundled script), and attaches `.zip` and `.7z` archives to the GitHub Release.
It can also be started manually from the Actions tab; those runs only upload a build artifact.

To build locally on Windows:

```bash
uv sync --no-dev --group build
uv run --no-sync pyinstaller packaging/specdash.spec --noconfirm   # output: dist/SpecDash/
```

The spec in [packaging/](packaging/) drops Dash/Plotly files that are never used at runtime
(source maps, test fixtures, offline plotly.js) to keep the bundle small.
