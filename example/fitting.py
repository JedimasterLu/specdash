"""
Fit of the two broad PL peaks A and B (specific to CS_NR50uM_10mw_5um_1_pl_net.csv).

Run directly:  python fitting.py   (needs an environment with lmfit/scipy/pandas, e.g. uv run python fitting.py)
All settings live in CONFIG below; there are no command-line arguments.

Conventions:
  * E = 1239.84/λ (eV), I(E) = I(λ)·λ²/1239.84, sorted by ascending energy.
  * Every line shape is normalized to peak height = 1, so A1 and A2 are peak heights (counts/s/eV)
    and the three shapes can be compared directly.
  * Shapes: gauss: parameters (E, σ)
            voigt: parameters (E, σ, γ)  σ = Gaussian std, γ = Lorentzian HWHM (scipy.special.wofz)
            split: parameters (E, σ, σR) σ = std on the low-energy (red) side, σR = std on the high-energy (blue) side
    Parameter names per peak: E1, s1, x1 / E2, s2, x2   (x is γ or σR; gauss has no x)

The script is linear: load → preprocess → SVD → fit → report/plots → shape comparison → warnings.
Only two functions remain: peak (line shape, reused in several places) and resid (required as the lmfit callback).
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import lmfit
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import nnls
from scipy.special import wofz

plt.rcParams["font.family"] = "Arial"

HC = 1239.84  # eV·nm

# ───────────────────────── Constants ─────────────────────────
# Wavelength ranges (nm) dropped at the data-processing stage (notch region + around the 532 nm laser); they enter no later step or plot
DEFAULT_DROP = [(521.0, 541.0)]
DEFAULT_MASKS = [(580.0, 586.0), (627.0, 633.0)]  # nm, narrow spikes (likely Raman), excluded from the fit
# Annotated in plots only (does not affect the fit): (λ_lo, λ_hi, label)
ANNOTATIONS = [(510.0, 516.0, "513 nm peak")]
LASER_NM = 532.0
# Initial values and bounds: name -> (init, lo, hi). E1/s1 are weakly constrained because the blue side is cut by a filter.
PEAK_DEFAULTS = {
    "E1": (2.19, 2.05, 2.40), "s1": (0.13, 0.05, 0.30),
    "E2": (2.00, 1.85, 2.12), "s2": (0.13, 0.05, 0.30),
}
EXTRA_DEFAULTS = {  # Third shape parameter x: shape -> (init, lo, hi); for split, init defaults to the σ initial value
    "voigt": (0.02, 0.0, 0.25),
    "split": (None, 0.03, 0.35),
}
BOUND_TOL = 1e-3  # A parameter within (range × BOUND_TOL) of a bound counts as hitting it
MAX_NFEV = 4000  # Max leastsq function calls (incl. numerical Jacobian); exceeding it gives a non-convergence warning
CORR_WARN = 0.95  # Warn when |correlation| exceeds this


# ───────────────────────── Settings ─────────────────────────
CONFIG = {
    "path": "data/CSM2_NR50µM_10mW.csv",
    "outdir": "CSM2",  # output directory: fit-result CSVs + figures
    "col_regex": r"\[S\s*\S\s*B\]",              # select net-spectrum columns (column name contains "[S − B]")
    "label_regex": r"_(\d+(?:\.\d+)?um)(?=_|$)",    # short label extracted from the column name, e.g. "5um"; also used for sorting
    "lam_max": 850.0,       # nm: upper limit of the fit range; no lower limit, everything from the data minimum wavelength is fitted (except drops/masks)
    "drops": DEFAULT_DROP, "masks": DEFAULT_MASKS,
    "mode": "global",       # "global"=(a) all spectra together | "staged"=(b) staged, shape fixed step by step | "per_spectrum"=(c) each spectrum independent
    "shift_max": 0,      # eV: max per-spectrum drift of the peak positions E1, E2 from the shared value (global/staged modes; 0 = no drift)
    "shape": "split",       # "gauss" | "voigt" | "split"(measured: gauss/voigt do not converge; split converges and halves the rms)
    "c0": True,             # include a constant background
    "weight": "none",       # "none"=equal weights | "sqrt"=weight by sqrt(I)
    # Initial values and bounds (the blue side of peak A is cut off so E1/s1 are weakly constrained; edit here if needed)
    "E1": 2.19, "E1_bounds": (2.05, 2.40), "s1": 0.13, "s1_bounds": (0.05, 0.30),
    "E2": 2.00, "E2_bounds": (1.85, 2.12), "s2": 0.13, "s2_bounds": (0.05, 0.30),
    "x1_bounds": None, "x2_bounds": None,   # bounds for voigt γ / split σR; None uses EXTRA_DEFAULTS
    "a_spec": "3um", "b_spec": "50um",      # (b) mode: A-dominated spectrum / B-dominated spectrum
    "compare": True,        # compare χ²/AIC/BIC of the three shapes
    "show": False,           # show figure windows at the end
}


# ───────────────────────── Functions ─────────────────────────
def peak(E, E0, s, x, shape):
    """Line shape normalized to peak height 1."""
    d = E - E0
    if shape == "gauss":
        return np.exp(-0.5 * (d / s) ** 2)
    if shape == "split":
        sig = np.where(d < 0, s, x)
        return np.exp(-0.5 * (d / sig) ** 2)
    if shape == "voigt":
        k = s * np.sqrt(2.0)
        return wofz((d + 1j * x) / k).real / wofz(1j * x / k).real
    raise ValueError(shape)


def resid(p, E, Y, W, shape, c0, names, shift=False):
    """lmfit residual callback: weighted residuals of all spectra, flattened to 1-D."""
    sh = {n: p[n].value for n in names}
    out = np.empty_like(Y)
    for k in range(Y.shape[1]):
        E1, E2 = sh["E1"], sh["E2"]
        if shift:  # per-spectrum peak positions drift slightly around the shared value
            E1 = E1 + p[f"dE1_{k}"].value
            E2 = E2 + p[f"dE2_{k}"].value
        g1 = p[f"A1_{k}"].value * peak(E, E1, sh["s1"], sh.get("x1", 0.0), shape)
        g2 = p[f"A2_{k}"].value * peak(E, E2, sh["s2"], sh.get("x2", 0.0), shape)
        out[:, k] = (Y[:, k] - (g1 + g2 + (p[f"c0_{k}"].value if c0 else 0.0))) * W[:, k]
    return out.ravel()


a = SimpleNamespace(**CONFIG)
outdir = Path(a.outdir)
outdir.mkdir(parents=True, exist_ok=True)

# ───────────────────────── Load and preprocess ─────────────────────────
p = Path(a.path)
if p.is_dir():
    files = sorted(p.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSV in {p}")
else:
    files = [p]

series = []  # (name, lam, y)
for f in files:
    with open(f, encoding="utf-8-sig") as fh:
        first = fh.readline().split(",")[0].strip().strip('"')
    try:
        float(first)
        d = pd.read_csv(f, header=None, encoding="utf-8-sig")
    except ValueError:
        d = pd.read_csv(f, encoding="utf-8-sig")
    if p.is_dir():
        series.append((f.stem, d.iloc[:, 0].to_numpy(float), d.iloc[:, 1].to_numpy(float)))
    else:
        cols = list(d.columns[1:])
        sel = [c for c in cols if re.search(a.col_regex, str(c))] or cols
        for c in sel:
            series.append((str(c).split(".asc")[0], d.iloc[:, 0].to_numpy(float), d[c].to_numpy(float)))

short = []
for name, _, _ in series:
    mt = re.search(a.label_regex, name)
    short.append(mt.group(1) if mt else name)
order = list(range(len(series)))
try:  # sort by the numeric value in the label
    order = sorted(order, key=lambda i: float(re.findall(r"^[\d.]+", short[i])[0]))
except IndexError:
    pass  # label does not start with a number: keep file order
series = [series[i] for i in order]
labels = [short[i] for i in order]

# Common wavelength grid (taken from the first spectrum)
lam = series[0][1]
cols_y = []
for name, lam_i, y in series:
    ok = np.isfinite(lam_i) & np.isfinite(y)
    lam_i, y = lam_i[ok], y[ok]
    if lam_i.shape == lam.shape and np.allclose(lam_i, lam):
        cols_y.append(y)
    else:
        print(f"WARNING: wavelength grid of {name} differs from the first spectrum; interpolated onto the first spectrum's grid")
        o = np.argsort(lam_i)
        cols_y.append(np.interp(lam, lam_i[o], y[o]))
Y = np.column_stack(cols_y)

# Wavelength → energy, convert to I(E) (incl. Jacobian), sort by ascending energy
E_all = HC / lam
Y_all = Y * lam[:, None] ** 2 / HC
o = np.argsort(E_all)
lam, E_all, Y_all = lam[o], E_all[o], Y_all[o]
inwin = lam <= a.lam_max
excluded = np.zeros_like(inwin)  # drops + masks: excluded from fit/SVD but kept in the data and shown in plots
for lo, hi in list(a.drops) + list(a.masks):
    excluded |= (lam >= lo) & (lam <= hi)
fit_mask = inwin & ~excluded      # used in the fit
masked = inwin & excluded         # dropped/masked (not fitted but still plotted)

E, Yf = E_all[fit_mask], Y_all[fit_mask]
if a.weight == "none":
    W = np.ones_like(Yf)
else:
    W = 1.0 / np.sqrt(np.clip(Yf, 0.01 * Yf.max(axis=0, keepdims=True), None))
    W = W / np.sqrt(np.mean(W ** 2))  # normalized so χ² is comparable with equal weights
n, m = Yf.shape
print(f"{len(labels)} spectra: {labels}")
print(f"Fit points per spectrum = {fit_mask.sum()}  (λ {lam.min():.1f}–{min(a.lam_max, lam.max()):.1f} nm, "
      f"dropped {a.drops}, masked {a.masks}, points not fitted {masked.sum()})")

# ───────────────────────── SVD diagnostic ─────────────────────────
sv = np.linalg.svd(Yf, compute_uv=False)
kk = min(5, len(sv))
tbl = pd.DataFrame({"index": np.arange(1, kk + 1), "singular_value": sv[:kk],
                    "variance_fraction": (sv ** 2 / np.sum(sv ** 2))[:kk],
                    "ratio_to_first": sv[:kk] / sv[0]})
print("\n=== SVD (intensity matrix within the fit range, not mean-centered) ===")
print(tbl.to_string(index=False, float_format=lambda x: f"{x:.4g}"))
if len(sv) >= 3:
    print(f"σ3/σ2 = {sv[2] / sv[1]:.3g} (much smaller than σ2/σ1 = {sv[1] / sv[0]:.3g} supports only two significant components)")
tbl.to_csv(outdir / "svd.csv", index=False)
fig, ax = plt.subplots(figsize=(4.5, 3.5))
ax.semilogy(np.arange(1, len(sv) + 1), sv, "o-")
ax.set(xlabel="component", ylabel="singular value", title="Scree plot")
ax.set_xticks(np.arange(1, len(sv) + 1))
fig.tight_layout()
fig.savefig(outdir / "svd_scree.png", dpi=150)

# ───────────────────────── Fitting ─────────────────────────
shapes = [a.shape] + ([s for s in ("gauss", "voigt", "split") if s != a.shape] if a.compare else [])
fits = {}
for shape in shapes:
    # Shared parameter names, initial values, bounds
    names = ["E1", "s1", "E2", "s2"] if shape == "gauss" else ["E1", "s1", "x1", "E2", "s2", "x2"]
    init = {nm: getattr(a, nm) for nm in PEAK_DEFAULTS}
    bnd = {nm: tuple(getattr(a, f"{nm}_bounds")) for nm in PEAK_DEFAULTS}
    if shape != "gauss":
        x0, xlo, xhi = EXTRA_DEFAULTS[shape]
        for i in (1, 2):
            init[f"x{i}"] = x0 if x0 is not None else getattr(a, f"s{i}")
            xb = getattr(a, f"x{i}_bounds")
            bnd[f"x{i}"] = tuple(xb) if xb else (xlo, xhi)
    namps = 2 + int(a.c0)
    nshift = 2 * (m - 1) if (a.shift_max > 0 and m > 1 and a.mode != "per_spectrum") else 0  # number of free drift parameters

    # Plan the fit stages: each stage = a set of spectra + varying parameters + whether drift is allowed
    vary_a, s1_init = set(), {}  # only used in staged mode
    if a.mode == "global":
        stages = [{"tag": "global", "cols": list(range(m)), "vary": set(names), "shift": True}]
    elif a.mode == "staged":
        idx = []
        for spec in (a.b_spec, a.a_spec):
            try:
                i = int(spec) % m
            except ValueError:
                if spec not in labels:
                    raise SystemExit(f"Spectrum {spec!r} not found; available: {labels}")
                i = labels.index(spec)
            idx.append(i)
        ib, ia = idx
        if ia == ib:
            raise SystemExit("a_spec and b_spec in CONFIG must not be the same spectrum")
        vary_a = {nm for nm in ("E1", "s1", "x1") if nm in names}
        stages = [{"tag": f"stage1 B-dominated {labels[ib]}", "cols": [ib], "vary": set(names), "shift": False},
                  {"tag": f"stage2 A-dominated {labels[ia]}", "cols": [ia], "vary": vary_a, "shift": False},
                  {"tag": "stage3 amplitudes", "cols": list(range(m)), "vary": set(), "shift": True}]
    else:  # per_spectrum
        stages = [{"tag": labels[i], "cols": [i], "vary": set(names), "shift": False} for i in range(m)]

    cores = []
    for si, st in enumerate(stages):
        cols, vary, tag_s = st["cols"], st["vary"], st["tag"]
        Ys, Ws, lb, mm = Yf[:, cols], W[:, cols], [labels[i] for i in cols], len(cols)
        pre = f"[{tag_s}] " if tag_s else ""

        # Initial shared parameters for this stage
        if a.mode == "staged" and si == 1:  # A-dominated spectrum: take the B peak from stage1
            shared0 = dict(init)
            for nm in ("E2", "s2", "x2"):
                if nm in names:
                    shared0[nm] = cores[0]["shared"][nm][0]
            s1_init = shared0
        elif a.mode == "staged" and si == 2:  # amplitude stage: all shape parameters fixed
            shared0 = dict(s1_init)
            for nm in vary_a:
                shared0[nm] = cores[1]["shared"][nm][0]
        else:
            shared0 = init

        shift = st["shift"] and a.shift_max > 0 and mm > 1
        # When drift is allowed, first fit without drift and start the drift fit from that solution (otherwise it easily lands in a worse local minimum)
        res: Any = None  # lmfit's type stubs are incomplete; treat as Any
        warns: list = []
        do_shift = False
        shared = {}  # result of the first pass (no drift), used as the start of the second pass (with drift)
        for do_shift in ([False, True] if shift else [False]):
            if do_shift:
                shared0 = {nm: shared[nm][0] for nm in names}
            ps = lmfit.Parameters()
            for nm in names:
                ps.add(nm, value=shared0[nm], min=bnd[nm][0], max=bnd[nm][1], vary=nm in vary)
            # Initial amplitudes: non-negative linear least squares with the current shapes
            ymax = float(Ys.max())
            for k in range(mm):
                B = [peak(E, shared0["E1"], shared0["s1"], shared0.get("x1", 0), shape),
                     peak(E, shared0["E2"], shared0["s2"], shared0.get("x2", 0), shape)]
                if a.c0:
                    B.append(np.ones_like(E))
                coef, _ = nnls(np.column_stack(B) * Ws[:, [k]], Ys[:, k] * Ws[:, k])
                ps.add(f"A1_{k}", value=max(coef[0], 1e-3 * ymax), min=0)
                ps.add(f"A2_{k}", value=max(coef[1], 1e-3 * ymax), min=0)
                if a.c0:
                    ps.add(f"c0_{k}", value=coef[2])
            if do_shift:
                # Peak drift dE_k ∈ [-δ, δ]; the last spectrum takes -Σ(others) so the mean drift is 0, avoiding degeneracy with the shared position
                for q in ("1", "2"):
                    for k in range(mm - 1):
                        ps.add(f"dE{q}_{k}", value=0.0, min=-a.shift_max, max=a.shift_max)
                    ps.add(f"dE{q}_{mm - 1}", expr="-(" + "+".join(f"dE{q}_{k}" for k in range(mm - 1)) + ")")
            args = (E, Ys, Ws, shape, a.c0, names, do_shift)
            res = lmfit.minimize(resid, ps, args=args, method="leastsq", max_nfev=MAX_NFEV)

            warns, stuck = [], []
            if not res.success:
                warns.append(f"{pre}fit did not converge: {res.message}")
            for rnd in (0, 1):  # rnd=1: refit with bound-hitting parameters fixed at the bound so the others get uncertainties
                if rnd == 1:
                    if not (stuck and not res.errorbars):
                        break
                    p2 = res.params.copy()
                    for nm in stuck:
                        p2[nm].vary = False
                    res = lmfit.minimize(resid, p2, args=args, method="leastsq", max_nfev=MAX_NFEV)
                    warns.append(f"{pre}parameters at bounds {stuck} were fixed and the fit repeated to estimate uncertainties of the rest (these parameters have no uncertainty)")
                for nm, par in res.params.items():  # new bound-hitting parameters may appear after the refit
                    if not par.vary:
                        continue
                    lo, hi = par.min, par.max
                    rng = (hi - lo) if np.isfinite(lo) and np.isfinite(hi) else ymax
                    tol = BOUND_TOL * rng
                    if np.isfinite(lo) and par.value - lo < tol:
                        side, b = "lower bound", lo
                    elif np.isfinite(hi) and hi - par.value < tol:
                        side, b = "upper bound", hi
                    else:
                        continue
                    if rnd == 0:
                        stuck.append(nm)
                    warns.append(f"{pre}parameter {nm} = {par.value:.4g} hit the {side} {b:g}")
            if do_shift:
                for q in ("1", "2"):
                    v = res.params[f"dE{q}_{mm - 1}"].value
                    if abs(v) > a.shift_max * (1 + 1e-6):
                        warns.append(f"{pre}dE{q}_{mm - 1} = {v:.4f} exceeds ±{a.shift_max:g} eV (implied by the zero-mean-drift constraint)")
            if not res.errorbars:
                warns.append(f"{pre}cannot estimate uncertainties from the covariance matrix (degenerate parameters)")

            shared = {nm: (res.params[nm].value,
                           np.nan if res.params[nm].stderr is None else res.params[nm].stderr,
                           res.params[nm].vary) for nm in names}

        # Per-spectrum amplitude table and parameters
        rows, spec_pars = [], []
        for k in range(mm):
            A1, A2 = res.params[f"A1_{k}"], res.params[f"A2_{k}"]
            c0p = res.params[f"c0_{k}"] if a.c0 else None
            s = A1.value + A2.value
            frac = A1.value / s if s > 0 else np.nan
            ferr = np.nan
            if res.errorbars and s > 0 and A1.name in res.var_names and A2.name in res.var_names:
                ii = [res.var_names.index(A1.name), res.var_names.index(A2.name)]
                g = np.array([A2.value, -A1.value]) / s ** 2
                ferr = float(np.sqrt(g @ res.covar[np.ix_(ii, ii)] @ g))
            row = {"spectrum": lb[k], "A1": A1.value, "A1_err": np.nan if A1.stderr is None else A1.stderr,
                       "A2": A2.value, "A2_err": np.nan if A2.stderr is None else A2.stderr,
                       "c0": c0p.value if c0p else 0.0,
                       "c0_err": (np.nan if c0p.stderr is None else c0p.stderr) if c0p else np.nan,
                       "frac_A": frac, "frac_A_err": ferr}
            pk = {nm: shared[nm][0] for nm in names}
            if do_shift:
                for q in ("1", "2"):
                    dp = res.params[f"dE{q}_{k}"]
                    row[f"dE{q}"], row[f"dE{q}_err"] = dp.value, np.nan if dp.stderr is None else dp.stderr
                    pk[f"E{q}"] += dp.value
                    row[f"E{q}_spec"] = pk[f"E{q}"]
            rows.append(row)
            spec_pars.append({**pk, "A1": A1.value, "A2": A2.value, "c0": c0p.value if c0p else 0.0})

        # Correlation matrix
        C = pd.DataFrame(np.nan, index=names, columns=names)
        if res.errorbars:
            sd = np.sqrt(np.diag(res.covar))
            R = res.covar / np.outer(sd, sd)
            for i, ni in enumerate(res.var_names):
                for j, nj in enumerate(res.var_names):
                    if ni in names and nj in names:
                        C.loc[ni, nj] = R[i, j]

        cores.append({"shared": shared, "amps": pd.DataFrame(rows), "spec_pars": spec_pars, "corr": C,
                          "chi2": float(res.chisqr), "warns": warns})

    # Assemble into a single fit
    if a.mode == "global":
        c = cores[0]
        shared_tbl = pd.DataFrame([{"spectrum": "all", "name": nm, "value": v, "stderr": e, "vary": vy}
                                   for nm, (v, e, vy) in c["shared"].items()])
        fit = {"shared_tbl": shared_tbl, "amps": c["amps"], "corr": {"all": c["corr"]}, "spec_pars": c["spec_pars"],
                   "chi2": c["chi2"], "N": n * m, "k": len(names) + m * namps + nshift, "warnings": c["warns"]}
    elif a.mode == "staged":
        c1, c2, c3 = cores
        # Shared-parameter table: values from the two stages; errors from the single-spectrum fits of each stage
        rows = []
        for nm in names:
            v, e, _ = (c1 if nm in ("E2", "s2", "x2") else c2)["shared"][nm]
            rows.append({"spectrum": "all", "name": nm, "value": v, "stderr": e, "vary": False})
        C = pd.DataFrame(np.nan, index=names, columns=names)
        for src, grp in ((c1, [x for x in names if x.endswith("2")]), (c2, [x for x in names if x.endswith("1")])):
            C.loc[grp, grp] = src["corr"].loc[grp, grp].to_numpy()
        warns = c1["warns"] + c2["warns"] + c3["warns"]
        warns.append("(b) mode: shape-parameter uncertainties come from the single-spectrum stage fits; correlations between A1/E1 and the B-peak parameters are not estimated (NaN)")
        fit = {"shared_tbl": pd.DataFrame(rows), "amps": c3["amps"], "corr": {"all": C}, "spec_pars": c3["spec_pars"],
                   "chi2": c3["chi2"], "N": n * m, "k": len(names) + m * namps + nshift, "warnings": warns}
    else:  # per_spectrum
        rows, warns = [], []
        for i, c in enumerate(cores):
            rows += [{"spectrum": labels[i], "name": nm, "value": v, "stderr": e, "vary": vy} for nm, (v, e, vy) in c["shared"].items()]
            warns += c["warns"]
        fit = {"shared_tbl": pd.DataFrame(rows), "amps": pd.concat([c["amps"] for c in cores], ignore_index=True),
                   "corr": {labels[i]: c["corr"] for i, c in enumerate(cores)},
                   "spec_pars": [sp for c in cores for sp in c["spec_pars"]],
                   "chi2": sum(c["chi2"] for c in cores), "N": n * m, "k": m * (len(names) + namps), "warnings": warns}
    fit["shape"], fit["mode"] = shape, a.mode
    fit["aic"] = fit["N"] * np.log(fit["chi2"] / fit["N"]) + 2 * fit["k"]
    fit["bic"] = fit["N"] * np.log(fit["chi2"] / fit["N"]) + fit["k"] * np.log(fit["N"])
    fits[shape] = fit

# ───────────────────────── Output ─────────────────────────
main_fit = fits[a.shape]
tag = f"{a.shape}_{a.mode}"
fmt = "{:.5g}".format

print(f"\n=== Fit results [{main_fit['shape']} | {main_fit['mode']}] ===")
print(f"chi2={main_fit['chi2']:.5g}  N={main_fit['N']}  k={main_fit['k']}  "
      f"redchi2={main_fit['chi2'] / (main_fit['N'] - main_fit['k']):.5g}  "
      f"AIC={main_fit['aic']:.2f}  BIC={main_fit['bic']:.2f}")
print("\n-- Shape parameters (value ± stderr) --")
print(main_fit["shared_tbl"].to_string(index=False, float_format=fmt))
print("\n-- Per-spectrum amplitudes --")
print(main_fit["amps"].to_string(index=False, float_format=fmt))
for key, C in main_fit["corr"].items():
    if a.mode == "per_spectrum":
        continue  # per-spectrum correlation matrices are only written to CSV
    print(f"\n-- Correlation matrix ({key}) --")
    print(C.to_string(float_format=lambda x: f"{x:.3f}"))
main_fit["shared_tbl"].to_csv(outdir / f"params_{tag}.csv", index=False)
main_fit["amps"].to_csv(outdir / f"amplitudes_{tag}.csv", index=False)
pd.concat(main_fit["corr"], names=["spectrum", "param"]).to_csv(outdir / f"corr_{tag}.csv")
if a.mode == "per_spectrum":
    t = main_fit["shared_tbl"].pivot(index="spectrum", columns="name", values="value").loc[labels]
    print("\n-- Per-spectrum peak position / width variation (mean ± std) --")
    print(pd.DataFrame({"mean": t.mean(), "std": t.std()}).to_string(float_format=fmt))

# ───────────────────────── Plots: single spectra ─────────────────────────
for k in range(m):
    pars = main_fit["spec_pars"][k]
    g1 = pars["A1"] * peak(E_all, pars["E1"], pars["s1"], pars.get("x1", 0.0), a.shape)
    g2 = pars["A2"] * peak(E_all, pars["E2"], pars["s2"], pars.get("x2", 0.0), a.shape)
    tot = g1 + g2 + pars.get("c0", 0.0)
    y = Y_all[:, k]
    fig, (ax, rx) = plt.subplots(2, 1, figsize=(8, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1], "hspace": 0.05})
    for lo, hi, name in ANNOTATIONS:
        for x in (ax, rx):
            x.axvspan(HC / hi, HC / lo, color="tab:orange", alpha=0.15, lw=0)
        ax.text(HC / (0.5 * (lo + hi)), 0.97, name, transform=ax.get_xaxis_transform(), rotation=90,
                va="top", ha="center", fontsize=7, color="tab:orange")
    for x in (ax, rx):
        x.axvline(HC / LASER_NM, color="tab:purple", ls=":", lw=0.8)
    ax.plot(E_all, y, ".", ms=2, color="0.35", label="data")
    ax.plot(E_all, tot, "r-", lw=1.5, label="total fit")
    ax.plot(E_all, g1, "-", color="tab:blue", lw=1.2, label=f"A peak (E1={pars['E1']:.3f})")
    ax.plot(E_all, g2, "-", color="tab:green", lw=1.2, label=f"B peak (E2={pars['E2']:.3f})")
    if a.c0:
        ax.axhline(pars["c0"], color="0.5", ls="--", lw=0.8, label="c0")
    ax.set_ylabel("I(E)  (counts/s/eV)")
    ax.set_title(f"{labels[k]}  [{a.shape}, {a.mode}]   A1={pars['A1']:.3g}  A2={pars['A2']:.3g}")
    ax.legend(fontsize=8, loc="upper left")
    ax.set_ylim(min(-0.5, np.nanmin(y[fit_mask]) * 1.1), np.nanmax(y[fit_mask]) * 1.2)
    rx.plot(E_all[fit_mask], (y - tot)[fit_mask], ".", ms=2, color="0.3")
    rx.axhline(0, color="r", lw=0.8)
    rx.set(xlabel="Energy (eV)", ylabel="residual")
    rx.set_xlim(E_all.min(), E_all.max())
    sec = ax.secondary_xaxis("top", functions=(lambda e: HC / np.where(e == 0, np.nan, e),
                                                  lambda l: HC / np.where(l == 0, np.nan, l)))
    sec.set_xlabel("Wavelength (nm)")
    sec.set_xticks([500, 525, 550, 575, 600, 650, 700, 800])
    fig.savefig(outdir / f"fit_{tag}_{labels[k]}.png", dpi=150, bbox_inches="tight")

# ───────────────────────── Plots: amplitudes ─────────────────────────
# x axis: use actual numeric values when labels contain numbers (e.g. "5um"), otherwise evenly spaced by index
t = main_fit["amps"]
try:
    ax_x = np.array([float(re.findall(r"^[\d.]+", lb)[0]) for lb in labels])
    unit = re.sub(r"^[\d.]+", "", labels[0])
    ax_xt, ax_xl = [f"{v:g}" for v in ax_x], f"spectrum ({unit})" if unit else "spectrum"
except IndexError:
    ax_x, ax_xt, ax_xl = np.arange(len(labels)), list(labels), "spectrum"

fig, (a1, a2) = plt.subplots(2, 1, figsize=(6, 6), sharex=True)
a1.errorbar(ax_x, t.A1, t.A1_err, fmt="o-", color="tab:blue", capsize=3, label="A1 (A peak)")
a1.errorbar(ax_x, t.A2, t.A2_err, fmt="s-", color="tab:green", capsize=3, label="A2 (B peak)")
a1.set(ylabel="amplitude (counts/s/eV)", title=f"Amplitudes [{a.shape}, {a.mode}]")
a1.legend()
a2.errorbar(ax_x, t.frac_A, t.frac_A_err, fmt="o-", color="k", capsize=3)
a2.set(ylabel="A1 / (A1 + A2)", xlabel=ax_xl, ylim=(-0.05, 1.05))
a2.set_xticks(ax_x)
a2.set_xticklabels(ax_xt)
fig.tight_layout()
fig.savefig(outdir / f"amplitudes_{tag}.png", dpi=150)

# ───────────────────────── Plots: 3×3 overview ─────────────────────────
# Fits of 7 spectra (data / total fit / A peak / B peak) + amplitude trend + SVD scree plot. Same style as the single-spectrum plots.
fig = plt.figure(figsize=(14, 11))
gs = fig.add_gridspec(3, 3, hspace=0.32, wspace=0.42)
ymax_grid = max(Y_all[fit_mask].max(), 1) * 1.15
first = None
for k in range(min(m, 7)):
    ax = fig.add_subplot(gs[k // 3, k % 3], sharex=first, sharey=first)
    first = first or ax
    pars = main_fit["spec_pars"][k]
    g1 = pars["A1"] * peak(E_all, pars["E1"], pars["s1"], pars.get("x1", 0.0), a.shape)
    g2 = pars["A2"] * peak(E_all, pars["E2"], pars["s2"], pars.get("x2", 0.0), a.shape)
    ax.plot(E_all, Y_all[:, k], ".", ms=2, color="0.35", label="data")
    ax.plot(E_all, g1 + g2 + pars.get("c0", 0.0), "r-", lw=1.5, label="total fit")
    ax.plot(E_all, g1, "-", color="tab:blue", lw=1.2, label="A peak")
    ax.plot(E_all, g2, "-", color="tab:green", lw=1.2, label="B peak")
    ax.text(0.97, 0.95, labels[k], transform=ax.transAxes, ha="right", va="top", fontsize=11)
    ax.set_xlim(E_all.min(), E_all.max())
    ax.set_ylim(0, ymax_grid)
    if k // 3 == 2 or k >= 4:
        ax.set_xlabel("Energy (eV)")
    if k % 3 == 0:
        ax.set_ylabel("I(E)  (counts/s/eV)")
    if k == 0:
        ax.legend(fontsize=8, loc="upper left")
ax = fig.add_subplot(gs[2, 1])  # amplitudes
ax.errorbar(ax_x, t.A1, t.A1_err, fmt="o-", color="tab:blue", capsize=3, label="A1 (A peak)")
ax.errorbar(ax_x, t.A2, t.A2_err, fmt="s-", color="tab:green", capsize=3, label="A2 (B peak)")
ax.set(ylabel="amplitude (counts/s/eV)", xlabel=ax_xl)
ax.text(0.97, 0.95, "Amplitudes", transform=ax.transAxes, ha="right", va="top", fontsize=11)
ax.set_ylim(0, max(t.A1.max(), t.A2.max()) * 1.2)  # leave room for the top-right text
ax.set_xticks(ax_x)
ax.set_xticklabels(ax_xt)
ax.legend(fontsize=8, loc="center right")
ax = fig.add_subplot(gs[2, 2])  # SVD
ax.semilogy(np.arange(1, len(sv) + 1), sv, "o-", color="tab:blue")
ax.set(xlabel="component", ylabel="singular value")
ax.text(0.97, 0.95, "SVD", transform=ax.transAxes, ha="right", va="top", fontsize=11)
ax.set_xticks(np.arange(1, len(sv) + 1))
fig.savefig(outdir / f"summary_{tag}.png", dpi=150, bbox_inches="tight")

# ───────────────────────── Shape comparison ─────────────────────────
if a.compare:
    cmp = pd.DataFrame([{"shape": s, "chi2": f["chi2"], "N": f["N"], "k": f["k"], "redchi2": f["chi2"] / (f["N"] - f["k"]),
                             "AIC": f["aic"], "BIC": f["bic"]} for s, f in fits.items()])
    cmp["dAIC"] = cmp.AIC - cmp.AIC.min()
    cmp["dBIC"] = cmp.BIC - cmp.BIC.min()
    print(f"\n=== Shape comparison [{a.mode}] ===")
    print(cmp.to_string(index=False, float_format=fmt))
    cmp.to_csv(outdir / f"model_comparison_{a.mode}.csv", index=False)

# ───────────────────────── Warnings ─────────────────────────
print("\n=== Warnings ===")
any_w = False
for s, f in fits.items():
    for w in f["warnings"]:
        print(f"WARNING [{s}] {w}")
        any_w = True
    for key, M in f["corr"].items():
        pn = [nm for nm in ("E1", "s1", "E2", "s2") if nm in M.index]
        for i, p1 in enumerate(pn):
            for q1 in pn[i + 1:]:
                r = M.loc[p1, q1]
                if np.isfinite(r) and abs(r) > CORR_WARN:
                    print(f"WARNING [{s}] {key}: corr({p1},{q1}) = {r:.3f}, parameters strongly correlated")
                    any_w = True
if not any_w:
    print("None")
print(f"\nResults saved to {outdir.resolve()}")
if a.show:
    plt.show()
else:
    plt.close("all")
