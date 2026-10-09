"""Signal-quality indicators (descriptive; thresholds are heuristic, not validated)."""
from __future__ import annotations

import numpy as np
from scipy.signal import welch


def quality_indicators(x: np.ndarray, fs: float) -> dict:
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    out: dict = {"n_samples": n, "method": "descriptive spectral/amplitude indicators (experimental thresholds)"}
    if n < max(16, int(fs)):
        out["status"] = "N/A: window shorter than 1 s"
        return out
    diff = np.abs(np.diff(x))
    flat = diff < 1e-4
    run = max(2, int(0.1 * fs))
    flat_frac = 0.0
    if flat.any():
        # fraction of samples inside flat runs of at least 100 ms
        edges = np.diff(np.concatenate([[0], flat.astype(np.int8), [0]]))
        starts, ends = np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]
        flat_frac = float(sum(e - s for s, e in zip(starts, ends) if e - s >= run)) / n
    lo, hi = float(x.min()), float(x.max())
    clip_frac = float(np.mean((x >= hi - 1e-6) | (x <= lo + 1e-6))) if hi > lo else 1.0
    f, p = welch(x - x.mean(), fs=fs, nperseg=min(n, int(4 * fs)))
    total = float(np.trapezoid(p, f)) if hasattr(np, "trapezoid") else float(np.trapz(p, f))

    def band(a: float, b: float) -> float:
        m = (f >= a) & (f < b)
        if not m.any():
            return 0.0
        return float(np.trapezoid(p[m], f[m])) if hasattr(np, "trapezoid") else float(np.trapz(p[m], f[m]))

    qrs_band = band(5, 15)
    out.update({
        "amplitude_range_mv": hi - lo,
        "flatline_fraction": flat_frac,
        "clipping_fraction": clip_frac,
        "baseline_wander_ratio": band(0, 0.7) / total if total > 0 else None,
        "high_frequency_noise_ratio": band(40, fs / 2) / max(qrs_band, 1e-12) if fs > 90 else None,
        "powerline_ratio": max(band(48, 52), band(58, 62)) / max(total, 1e-12) if fs > 130 else None,
    })
    flags = []
    if flat_frac > 0.05:
        flags.append("flatline")
    if clip_frac > 0.01:
        flags.append("possible_clipping")
    if out["baseline_wander_ratio"] is not None and out["baseline_wander_ratio"] > 0.5:
        flags.append("baseline_wander")
    if out["high_frequency_noise_ratio"] is not None and out["high_frequency_noise_ratio"] > 0.5:
        flags.append("high_frequency_noise")
    if hi - lo < 0.05:
        flags.append("very_low_amplitude")
    out["flags"] = flags
    out["status"] = "questionable" if flags else "no_flags"
    return out
