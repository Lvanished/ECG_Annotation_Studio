"""EXPERIMENTAL P/QRS/T delineation (not clinically validated).

A search-based heuristic anchored on R peaks; it is provided so reviewers have
editable starting points, and its localisation error against LUDB reference
boundaries is reported in docs/TEST_REPORT.md.  Boundaries are found from the
signal (slope thresholds and tangent intersections), not from fixed-duration
windows, but the search ranges are physiological priors.

Per beat (signal filtered 0.5-40 Hz, baseline = median of the 60 ms before the
QRS onset search region):

* QRS onset/offset: walk outward from R until |dx/dt| stays below 12 % of the
  beat's maximal QRS slope for 10 ms (max 120 ms before / 160 ms after R).
* T wave: extremum (dominant polarity) in [QRS offset + 80 ms, min(R + 0.7 RR,
  next R - 120 ms)]; T offset = intersection of the steepest descending tangent
  after the peak with the baseline; T onset likewise before the peak (bounded by
  QRS offset).
* P wave: extremum in [R - 300 ms, QRS onset - 20 ms]; accepted only if the
  amplitude exceeds 0.04 mV and 2.5x the residual noise; onset/offset where the
  deviation falls below 25 % of the peak amplitude.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfiltfilt

ALGORITHM = "experimental_slope_tangent_delineator"
VERSION = "0.2.0"


def _filt(x: np.ndarray, fs: float) -> np.ndarray:
    sos = butter(2, [0.5, min(40.0, 0.45 * fs)], btype="bandpass", fs=fs, output="sos")
    return sosfiltfilt(sos, np.asarray(x, dtype=np.float64), padlen=min(len(x) - 1, int(3 * fs)))


def _tangent_cross(y: np.ndarray, d: np.ndarray, idx: int, base: float) -> float:
    if d[idx] == 0:
        return float(idx)
    return idx + (base - y[idx]) / d[idx]


def delineate(x: np.ndarray, fs: float, r_peaks: np.ndarray, offset: int = 0) -> list[dict]:
    """Return per-beat dict with absolute-sample boundaries (half-open intervals)."""
    y = _filt(x, fs)
    d = np.gradient(y)
    n = len(y)
    ms = lambda v: int(round(v * fs / 1000.0))  # noqa: E731
    r = np.sort(np.asarray(r_peaks, dtype=np.int64) - offset)
    r = r[(r > ms(150)) & (r < n - ms(200))]
    beats = []
    for i, rp in enumerate(r):
        rr_next = int(r[i + 1] - rp) if i + 1 < len(r) else (int(rp - r[i - 1]) if i > 0 else ms(800))
        rr_prev = int(rp - r[i - 1]) if i > 0 else rr_next
        qwin = d[max(0, rp - ms(60)): rp + ms(60)]
        smax = float(np.max(np.abs(qwin))) if len(qwin) else 0.0
        if smax <= 0:
            continue
        thr = 0.12 * smax
        hold = max(1, ms(10))
        # QRS onset
        on = rp
        lim = max(1, rp - ms(120))
        k = rp
        while k > lim:
            if np.all(np.abs(d[max(0, k - hold):k]) < thr):
                on = k
                break
            k -= 1
        else:
            on = lim
        # QRS offset
        off = rp
        lim2 = min(n - 1, rp + ms(160))
        k = rp
        while k < lim2:
            if np.all(np.abs(d[k:k + hold]) < thr):
                off = k
                break
            k += 1
        else:
            off = lim2
        bseg = y[max(0, on - ms(60)): max(1, on - ms(10))]
        base = float(np.median(bseg)) if len(bseg) else 0.0
        beat: dict = {"r": int(rp + offset), "qrs": (int(on + offset), int(off + 1 + offset))}
        # T wave
        t_lo = off + ms(80)
        t_hi = min(rp + int(0.7 * rr_next), (r[i + 1] - ms(120)) if i + 1 < len(r) else n - 1)
        if t_hi - t_lo > ms(60):
            seg = y[t_lo:t_hi] - base
            k_pos, k_neg = int(np.argmax(seg)), int(np.argmin(seg))
            tp = t_lo + (k_pos if abs(seg[k_pos]) >= abs(seg[k_neg]) else k_neg)
            sign = 1.0 if y[tp] - base >= 0 else -1.0
            after = d[tp:min(t_hi + ms(150), n - 1)] * sign
            before = d[max(off, t_lo - ms(40)):tp] * sign
            if len(after) > 2 and len(before) > 2:
                k_down = tp + int(np.argmin(after))
                k_up = max(off, t_lo - ms(40)) + int(np.argmax(before))
                t_off = _tangent_cross(y, d, k_down, base)
                t_on = _tangent_cross(y, d, k_up, base)
                t_on_i = int(np.clip(round(t_on), off + 1, tp))
                t_off_i = int(np.clip(round(t_off), tp + 1, min(n - 1, tp + ms(250))))
                if t_off_i > t_on_i:
                    beat["t"] = (int(t_on_i + offset), int(t_off_i + 1 + offset))
                    beat["t_peak"] = int(tp + offset)
        # P wave
        p_lo = max(0, rp - min(ms(300), int(0.6 * rr_prev)))
        p_hi = on - ms(20)
        if p_hi - p_lo > ms(40):
            seg = y[p_lo:p_hi] - base
            k_pos, k_neg = int(np.argmax(seg)), int(np.argmin(seg))
            kp = k_pos if abs(seg[k_pos]) >= abs(seg[k_neg]) else k_neg
            amp = float(seg[kp])
            noise = float(np.std(np.diff(y[p_lo:p_hi]))) * 2.5
            if abs(amp) > 0.04 and abs(amp) > noise:
                lvl = 0.25 * abs(amp)
                a = kp
                while a > 0 and abs(seg[a]) > lvl:
                    a -= 1
                b = kp
                while b < len(seg) - 1 and abs(seg[b]) > lvl:
                    b += 1
                if b > a:
                    beat["p"] = (int(p_lo + a + offset), int(p_lo + b + 1 + offset))
                    beat["p_peak"] = int(p_lo + kp + offset)
        beats.append(beat)
    return beats
