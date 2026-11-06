# SpecDash

Desktop app for processing Andor Solis `.asc` spectra, with a Plotly Dash UI in a pywebview window.

## Download

No Python needed. Download from the [Releases](../../releases) page:

- **Windows**: `SpecDash-<version>-windows-x64.zip`. Extract the whole folder and run `SpecDash\SpecDash.exe`
  (requires the Edge WebView2 runtime, preinstalled on current Windows). SmartScreen may warn about an unknown
  publisher because the exe is not code-signed: **More info → Run anyway**.
- **macOS** (Apple silicon): `SpecDash-<version>-macos-arm64.zip`. Unzip and move `SpecDash.app` to Applications.
  The app is not notarized; on first launch right-click → **Open** (or run `xattr -cr SpecDash.app`).

Startup errors are written to `%LOCALAPPDATA%\SpecDash\specdash.log` (Windows) or `~/Library/Logs/SpecDash/specdash.log` (macOS).

## Install & run (from source)

```bash
uv sync
uv run specdash          # add --debug for the web inspector
```

SpecDash is a native window ([pywebview](https://pywebview.flowrl.com/)) around a local Dash server.

On import, a first or last detector row whose mean is more than 5× the mean of the interior rows
(typically a saturated or artifact row) is ignored and noted in the file metadata table.

## Measurement modes

Every input (signal and backgrounds alike) is averaged over the selected detector rows (drag vertically on the grayscale image
of the first signal file in the sidebar; display is clipped to the 1st–99th percentile) and, by default, normalized to
**counts/s per accumulation** using `Exposure Time (secs)` and `Number of Accumulations`
from the file footer. Backgrounds are interpolated onto the wavelength grid of the first signal.

| Mode | Inputs | Output quantities |
|---|---|---|
| Photoluminescence, Raman | S, B | `S − B`, `S` |
| Dark-field scattering | S, B, R, D | `(S − B) / (R − D)`, `(S − D) / (R − D)` |
| Transmission | S, B, R, D | `(S − D) / (B − D)`, `(S − D) / (R − D)`, `1 − T/T₀`, `−log₁₀(T/T₀)` |
| Reflection | S, B, R, D | `(S − D) / (B − D)`, `(S − D) / (R − D)`, `(S − B) / (B − D)` |

S = signal (several files allowed), B = substrate background, R = reference, D = dark background.
Missing optional inputs are treated as zero, and the app shows a warning when that happens.

## Features

- Drop several `.asc` files at once anywhere on the window (or onto a specific input slot), or click a slot to browse.
  Files are read from disk by Python and parsed in parallel, so large batches load quickly.
- Interactive plots (zoom, pan, hover crosshair, SVG snapshot from the mode bar).
- X axis in wavelength, photon energy or Raman shift (configurable excitation wavelength).
- Optional Savitzky–Golay smoothing and detector-row selection.
- Export the processed curves, plus the normalized inputs, as CSV, TXT, NPY or JSON through a native Save dialog.
- Export **PNG** figures: the Result curves (Export → PNG) and the detector-row image with the selected rows
  outlined in blue (**Save PNG** in the Detector rows card). Both use a publication style
  (Arial 7 pt, 4.5 × 3.5 cm axes, inward ticks, 600 dpi) defined in [mplexport.py](src/specdash/mplexport.py).

## Slim plotly.js

`dcc.Graph` normally loads the full 4.8 MB plotly.js. SpecDash serves its own 1.1 MB build with only the core,
`scatter` and `heatmap` ([src/specdash/vendor/](src/specdash/vendor/)), so the Plotly API is unchanged. If you add other
trace types or upgrade Dash/plotly, rebuild it with Node (version in `tools/plotly-bundle/package.json` must match
`plotly.offline.get_plotlyjs_version()`):

```bash
cd tools/plotly-bundle && npm install && npm run build
```

## Building the apps

Releases are built by GitHub Actions ([build.yml](.github/workflows/build.yml)).
Bump the version in `pyproject.toml` and `src/specdash/__init__.py`, then push a matching tag:

```bash
git tag v0.3.0 && git push origin v0.3.0
```

- **Windows**: PyInstaller one-folder bundle ([packaging/specdash.spec](packaging/specdash.spec)).
- **macOS**: py2app `.app` bundle ([packaging/setup_macos.py](packaging/setup_macos.py)).

Each job runs `SpecDash --selftest` on the built bundle (serves every script, parses a spectrum, renders both PNGs),
zips the result and attaches it to the GitHub Release. The workflow can also be started manually from the Actions tab;
those runs only upload build artifacts.

To build locally:

```bash
uv sync --no-dev --group build
uv run --no-sync pyinstaller packaging/specdash.spec --noconfirm        # Windows -> dist/SpecDash/
uv run --no-sync python packaging/setup_macos.py py2app                 # macOS   -> dist/SpecDash.app
```
