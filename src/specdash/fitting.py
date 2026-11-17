"""Peak fitting with plain numpy: line shapes and a bounded Levenberg–Marquardt least-squares fit.

Parameters are kept in one flat vector: ``MAX_PEAKS`` blocks of ``[center, width, extra, height]``
followed by the constant background. Frozen parameters keep their value and are left out of the fit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

FloatArray = np.ndarray

MAX_PEAKS = 5
SHAPES: dict[str, str] = {
    "gauss": "Gaussian",
    "lorentz": "Lorentzian",
    "voigt": "Voigt",
    "split": "Split Gaussian",
}
"""Line shapes. Width is sigma (Gaussian, Voigt, split) or HWHM (Lorentzian); extra is gamma (Voigt) or the right sigma (split)."""
PARAMS = ("c", "w", "e", "h")
PARAM_LABELS = {"c": "Center", "w": "Width", "e": "Extra", "h": "Height"}
EXTRA_LABELS = {"voigt": "Gamma (HWHM)", "split": "Sigma, right side"}
NO_EXTRA = ("gauss", "lorentz")


def _faddeeva(z: FloatArray, n: int = 32) -> FloatArray:
    """Faddeeva function w(z) for Im z >= 0 (Weideman's rational approximation)."""
    m = 2 * n
    k = np.arange(-m + 1, m)
    scale = np.sqrt(n / np.sqrt(2))
    t = scale * np.tan(k * np.pi / (2 * m))
    f = np.concatenate([[0.0], np.exp(-(t**2)) * (scale**2 + t**2)])
    a = np.fft.fft(np.fft.fftshift(f)).real / (2 * m)
    coef = a[1 : n + 1][::-1]
    den = scale - 1j * z
    return 2 * np.polyval(coef, (scale + 1j * z) / den) / den**2 + (1 / np.sqrt(np.pi)) / den


def profile(shape: str, x: FloatArray, c: float, w: float, e: float) -> FloatArray:
    """Line shape of peak height 1."""
    d = x - c
    if shape == "lorentz":
        return 1.0 / (1.0 + (d / w) ** 2)
    if shape == "split":
        return np.exp(-0.5 * (d / np.where(d < 0, w, e)) ** 2)
    if shape == "voigt":
        k = w * np.sqrt(2.0)
        return _faddeeva((d + 1j * e) / k).real / _faddeeva(np.array([1j * e / k])).real[0]
    return np.exp(-0.5 * (d / w) ** 2)


def components(shapes: list[str], v: FloatArray, x: FloatArray) -> list[FloatArray]:
    """Curve of every peak (height included)."""
    return [v[4 * i + 3] * profile(s, x, *v[4 * i : 4 * i + 3]) for i, s in enumerate(shapes)]


def model(shapes: list[str], v: FloatArray, x: FloatArray) -> FloatArray:
    """Sum of the peaks plus the constant background ``v[-1]``."""
    return sum(components(shapes, v, x), np.zeros_like(x)) + v[-1]


@dataclass
class FitResult:
    """Outcome of :func:`fit`; ``values`` / ``errors`` follow the flat parameter layout."""

    values: FloatArray
    errors: FloatArray
    vary: FloatArray
    x: FloatArray
    y: FloatArray
    fit: FloatArray
    parts: list[FloatArray]
    chi2: float
    r2: float
    aic: float
    bic: float
    warnings: list[str] = field(default_factory=list)


def fit(
    x: FloatArray,
    y: FloatArray,
    shapes: list[str],
    v0: FloatArray,
    lo: FloatArray,
    hi: FloatArray,
    vary: FloatArray,
    max_iter: int = 300,
) -> FitResult:
    """Least-squares fit of ``model`` to ``y``; parameters with ``vary`` false stay fixed."""
    v = np.clip(v0, lo, hi)
    free = np.flatnonzero(vary)
    warnings: list[str] = []

    def chi2_of(p: FloatArray) -> float:
        return float(np.sum((y - model(shapes, p, x)) ** 2))

    def jacobian(p: FloatArray, idx: np.ndarray) -> FloatArray:
        base = model(shapes, p, x)
        cols = []
        for i in idx:
            step = 1e-6 * max(abs(p[i]), 1e-3 * (hi[i] - lo[i]) if np.isfinite(hi[i] - lo[i]) else 1e-3, 1e-9)
            q = p.copy()
            q[i] += -step if p[i] + step > hi[i] else step
            cols.append((model(shapes, q, x) - base) / (q[i] - p[i]))
        return np.column_stack(cols) if cols else np.empty((x.size, 0))

    cost, damping, converged = chi2_of(v), 1e-3, False
    for _ in range(max_iter if free.size else 0):
        r = y - model(shapes, v, x)
        jac = jacobian(v, free)
        grad = jac.T @ r  # descent direction of the cost is +grad
        # Parameters sitting on a bound and pushed outwards stay put for this step.
        movable = ~(((v[free] <= lo[free]) & (grad < 0)) | ((v[free] >= hi[free]) & (grad > 0)))
        idx, jac, grad = free[movable], jac[:, movable], grad[movable]
        if idx.size == 0:
            converged = True
            break
        hess = jac.T @ jac
        while damping < 1e12:
            try:
                step = np.linalg.solve(hess + damping * np.diag(np.maximum(np.diag(hess), 1e-12)), grad)
            except np.linalg.LinAlgError:
                damping *= 10
                continue
            trial = v.copy()
            trial[idx] = np.clip(v[idx] + step, lo[idx], hi[idx])
            new_cost = chi2_of(trial)
            if new_cost < cost:
                done = cost - new_cost <= 1e-12 * cost or np.max(np.abs(trial - v)) < 1e-12
                v, cost, damping = trial, new_cost, max(damping / 3, 1e-12)
                converged = done
                break
            damping *= 4
        else:
            converged = True
        if converged:
            break
    if free.size and max_iter and not converged:
        warnings.append("The fit did not converge; increase the iterations or adjust the start values.")

    errors = np.full(v.size, np.nan)
    dof = x.size - free.size
    if free.size and dof > 0:
        jac = jacobian(v, free)
        errors[free] = np.sqrt(np.abs(np.diag(np.linalg.pinv(jac.T @ jac))) * cost / dof)
    for i in free:
        if v[i] <= lo[i] or v[i] >= hi[i]:
            warnings.append(f"{param_name(i, len(shapes))} hit a bound ({v[i]:.5g}).")
    total = float(np.sum((y - y.mean()) ** 2))
    n, k = x.size, free.size
    nll = n * np.log(max(cost, 1e-300) / n)
    return FitResult(
        values=v, errors=errors, vary=vary, x=x, y=y, fit=model(shapes, v, x), parts=components(shapes, v, x),
        chi2=cost, r2=1 - cost / total if total else np.nan, aic=nll + 2 * k, bic=nll + k * np.log(n),
        warnings=warnings,
    )


def param_name(index: int, peaks: int) -> str:
    """Name of a flat parameter, e.g. ``"Peak 2 center"``."""
    if index == 4 * peaks:
        return "Background"
    return f"Peak {index // 4 + 1} {PARAM_LABELS[PARAMS[index % 4]].lower()}"


def detect(x: FloatArray, y: FloatArray, count: int, shapes: list[str]) -> FloatArray:
    """Start values for ``count`` peaks from the strongest local maxima (flat parameter vector)."""
    kernel = np.ones(max(3, x.size // 100)) / max(3, x.size // 100)
    s = np.convolve(y, kernel, mode="same")
    base = float(np.min(s))
    inner = np.flatnonzero((s[1:-1] >= s[:-2]) & (s[1:-1] > s[2:])) + 1
    picks: list[int] = []
    for i in inner[np.argsort(-s[inner])]:
        if all(abs(x[i] - x[j]) > (x[-1] - x[0]) / 25 for j in picks):
            picks.append(int(i))
        if len(picks) == count:
            break
    span = x[-1] - x[0]
    v = np.zeros(4 * count + 1)
    v[-1] = base
    for n in range(count):
        i = picks[n] if n < len(picks) else int(np.argmax(s))
        half = base + (s[i] - base) / 2
        left = np.flatnonzero(s[:i] < half)
        right = np.flatnonzero(s[i:] < half)
        lo_x = x[left[-1]] if left.size else x[0]
        hi_x = x[i + right[0]] if right.size else x[-1]
        sigma = max((hi_x - lo_x) / 2.355, span / 500)
        extra = {"voigt": sigma * 0.5, "split": sigma}.get(shapes[n], 0.0)
        v[4 * n : 4 * n + 4] = [x[i], sigma, extra, max(s[i] - base, 1e-12)]
    return v


def default_bounds(x: FloatArray, y: FloatArray, count: int) -> tuple[FloatArray, FloatArray]:
    """Bounds of the flat parameters when the user gives none."""
    span, top = float(x[-1] - x[0]), float(np.max(np.abs(y)))
    lo = np.tile([x[0], span * 1e-4, span * 1e-4, 0.0], count)
    hi = np.tile([x[-1], span, span, 10 * top], count)
    return np.append(lo, -np.inf), np.append(hi, np.inf)


def svd_components(curves: FloatArray, threshold: float = 0.03) -> tuple[int, FloatArray]:
    """Number of significant SVD components of a ``(points, curves)`` matrix, and its singular values.

    A component counts when its singular value exceeds ``threshold`` times the largest one.
    """
    sv = np.linalg.svd(curves, compute_uv=False)
    return max(int(np.sum(sv > threshold * sv[0])), 1), sv


def _param_rows(result: FitResult, shapes: list[str], used: FloatArray, lo: FloatArray, hi: FloatArray) -> list[list[str]]:
    """Parameter table rows (peak, shape, parameter, value, stderr, fixed, min, max), then the statistics."""
    n = len(shapes)
    rows = []
    for j in range(4 * n + 1):
        peak, kind = (str(j // 4 + 1), shapes[j // 4]) if j < 4 * n else ("", "")
        name = PARAM_LABELS[PARAMS[j % 4]].lower() if j < 4 * n else "offset"
        err = "" if not result.vary[j] or not np.isfinite(result.errors[j]) else f"{result.errors[j]:.6g}"
        bounds = ["" if not np.isfinite(b) else f"{b:.10g}" for b in (lo[j], hi[j])]
        rows.append([peak, kind, name, f"{result.values[j]:.10g}", err, str(int(not result.vary[j])), *bounds])
    for name, value in (("chi2", result.chi2), ("r2", result.r2), ("aic", result.aic), ("bic", result.bic), ("n_fitted", int(used.sum()))):
        rows.append(["", "", name, f"{value:.10g}", "", "", "", ""])
    return rows


def to_csv(
    result: FitResult, shapes: list[str], x_label: str, used: FloatArray, lo: FloatArray, hi: FloatArray
) -> dict[str, str]:
    """A fit as two plain CSV tables (one header row, no comments), ready for pandas / Origin.

    ``curves`` has one row per point: X, data, fit, every peak, residual and ``masked`` (1 for points left
    out of the fit). ``params`` has one row per parameter (peak, shape, parameter, value, stderr, fixed,
    min, max) followed by the fit statistics as rows without a peak.
    """
    names = [x_label.replace(",", " "), "data", "fit", *(f"peak{i + 1}" for i in range(len(shapes))), "residual", "masked"]
    cols = [result.x, result.y, result.fit, *result.parts, result.y - result.fit, ~used]
    curves = [",".join(names)] + [",".join(f"{float(c[i]):.10g}" for c in cols) for i in range(result.x.size)]
    params = ["peak,shape,parameter,value,stderr,fixed,min,max"] + [",".join(r) for r in _param_rows(result, shapes, used, lo, hi)]
    return {"curves": "\n".join(curves) + "\n", "params": "\n".join(params) + "\n"}


def batch_csv(
    fits: dict[str, FitResult], shapes: list[str], x_label: str, used: FloatArray, bounds: dict[str, tuple[FloatArray, FloatArray]]
) -> dict[str, str]:
    """Several fits of one curve set: a wide ``curves`` table (shared X, then data / fit / peaks / residual per curve)
    and a long ``params`` table with a leading ``curve`` column."""
    first = next(iter(fits.values()))
    names, cols = [x_label.replace(",", " ")], [first.x]
    for name, r in fits.items():
        label = name.replace(",", " ")
        names += [f"{label} data", f"{label} fit", *(f"{label} peak{i + 1}" for i in range(len(shapes))), f"{label} residual"]
        cols += [r.y, r.fit, *r.parts, r.y - r.fit]
    names.append("masked")
    cols.append(~used)
    curves = [",".join(names)] + [",".join(f"{float(c[i]):.10g}" for c in cols) for i in range(first.x.size)]
    params = ["curve,peak,shape,parameter,value,stderr,fixed,min,max"]
    for name, r in fits.items():
        params += [",".join([name.replace(",", " "), *row]) for row in _param_rows(r, shapes, used, *bounds[name])]
    return {"curves": "\n".join(curves) + "\n", "params": "\n".join(params) + "\n"}
