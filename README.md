# SpecDash

Interactive web app for processing Andor Solis `.asc` spectra, built with Plotly Dash.

## Install & run

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
