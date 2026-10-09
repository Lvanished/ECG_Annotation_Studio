"""R-peak detection.

``scipy_pan_tompkins`` is a re-implementation of the Pan & Tompkins (1985)
scheme with zero-phase filtering:

1. 5-15 Hz Butterworth band-pass (order 2, ``sosfiltfilt``)
2. five-point derivative, squaring, 150 ms moving-window integration (MWI)
3. MWI peaks at least 200 ms apart (refractory period)
4. adaptive signal/noise peak levels; threshold = NPKI + 0.25 (SPKI - NPKI)
5. search-back with half threshold when an RR gap exceeds 1.66 x mean RR
6. T-wave rejection: a candidate within 360 ms of the previous beat whose
   maximal slope is < 50 % of the previous QRS slope is classified as T wave
7. the R location is refined to the extreme of the 0.5-40 Hz filtered signal
   in a [-150 ms, +75 ms] window around the MWI peak, using the polarity
   that dominates the record.

``detection_score`` (MWI peak / threshold) is an uncalibrated ranking value,
**not** a probability.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt

ALGORITHM = "scipy_pan_tompkins"
VERSION = "1.0.0"


@dataclass
class RPeakResult:
    samples: np.ndarray  # absolute sample indices (int64)
    scores: np.ndarray
    parameters: dict
    algorithm: str
    version: str


def _bandpass(x: np.ndarray, fs: float, lo: float, hi: float, order: int = 2) -> np.ndarray:
    hi = min(hi, 0.45 * fs)
    sos = butter(order, [lo, hi], btype="bandpass", fs=fs, output="sos")
    padlen = min(len(x) - 1, 3 * fs)
    return sosfiltfilt(sos, x, padlen=int(padlen))


def detect_pan_tompkins(x: np.ndarray, fs: float, offset: int = 0) -> RPeakResult:
    x = np.asarray(x, dtype=np.float64)
    params = {"bandpass_hz": [5.0, 15.0], "mwi_ms": 150, "refractory_ms": 200, "threshold_fraction": 0.25,
              "searchback_rr_factor": 1.66, "t_wave_window_ms": 360, "refine_window_ms": [-150, 75],
              "refine_band_hz": [0.5, 40.0]}
    if len(x) < int(fs):
        return RPeakResult(np.array([], dtype=np.int64), np.array([]), params, ALGORITHM, VERSION)
    bp = _bandpass(x, fs, 5.0, 15.0)
    deriv = np.convolve(bp, np.array([1, 2, 0, -2, -1]) * (fs / 8.0), mode="same")
    sq = deriv ** 2
    w = max(1, int(round(0.150 * fs)))
    mwi = np.convolve(sq, np.ones(w) / w, mode="same")
    refractory = int(round(0.200 * fs))
    cand, _ = find_peaks(mwi, distance=refractory)
    if len(cand) == 0:
        return RPeakResult(np.array([], dtype=np.int64), np.array([]), params, ALGORITHM, VERSION)

    init = mwi[: int(2 * fs)]
    spki = 0.25 * float(init.max())
    npki = 0.5 * float(init.mean())
    thr = npki + 0.25 * (spki - npki)
    beats: list[int] = []
    scores: list[float] = []
    slopes: list[float] = []
    rr: list[int] = []
    half_t = int(round(0.360 * fs))
    swin = max(1, int(round(0.075 * fs)))

    def slope_at(p: int) -> float:
        lo, hi = max(0, p - swin), min(len(deriv), p + 1)
        return float(np.max(np.abs(deriv[lo:hi]))) if hi > lo else 0.0

    thr_hist = np.empty(len(cand))
    for i, p in enumerate(int(c) for c in cand):
        val = float(mwi[p])
        thr_hist[i] = thr
        if val > thr:
            if beats and p - beats[-1] < half_t and slopes and slope_at(p) < 0.5 * slopes[-1]:
                npki = 0.125 * val + 0.875 * npki  # T wave
            else:
                if beats:
                    rr.append(p - beats[-1])
                beats.append(p)
                scores.append(val / thr)
                slopes.append(slope_at(p))
                spki = 0.125 * val + 0.875 * spki
        else:
            npki = 0.125 * val + 0.875 * npki
        thr = npki + 0.25 * (spki - npki)

    # search-back: one additional beat per abnormally long RR gap, at half threshold
    added: list[tuple[int, float]] = []
    for k in range(1, len(beats)):
        gap = beats[k] - beats[k - 1]
        local = np.median(np.diff(beats[max(0, k - 9): k])) if k >= 3 else gap
        if gap > 1.66 * local:
            lo, hi = beats[k - 1] + refractory, beats[k] - refractory
            mask = (cand >= lo) & (cand <= hi)
            idx = np.nonzero(mask)[0]
            idx = [j for j in idx if mwi[cand[j]] > 0.5 * thr_hist[j]]
            if idx:
                j = max(idx, key=lambda j: mwi[cand[j]])
                added.append((int(cand[j]), float(mwi[cand[j]] / thr_hist[j])))
    for p, sc in added:
        beats.append(p)
        scores.append(sc)

    beats_arr = np.array(sorted(set(beats)), dtype=np.int64)
    score_map = dict(zip(beats, scores))
    # refine on the broadband signal using the record's dominant polarity
    wide = _bandpass(x, fs, 0.5, 40.0)
    lo_off, hi_off = int(round(0.150 * fs)), int(round(0.075 * fs))
    pos = [float(wide[max(0, b - lo_off): b + hi_off + 1].max()) for b in beats_arr]
    neg = [float(-wide[max(0, b - lo_off): b + hi_off + 1].min()) for b in beats_arr]
    polarity = 1.0 if np.median(pos) >= np.median(neg) else -1.0
    refined: list[int] = []
    for b in beats_arr:
        lo, hi = max(0, b - lo_off), min(len(wide), b + hi_off + 1)
        refined.append(lo + int(np.argmax(polarity * wide[lo:hi])))
    out, out_scores = [], []
    for r, b in zip(refined, beats_arr):
        if out and r - out[-1] < refractory:
            continue
        out.append(r)
        out_scores.append(score_map.get(int(b), 1.0))
    params["polarity"] = "positive" if polarity > 0 else "negative"
    return RPeakResult(np.asarray(out, dtype=np.int64) + offset, np.asarray(out_scores), params, ALGORITHM, VERSION)


def detect_xqrs(x: np.ndarray, fs: float, offset: int = 0) -> RPeakResult:
    """WFDB's XQRS detector followed by local-extremum correction."""
    import wfdb
    from wfdb import processing

    x = np.asarray(x, dtype=np.float64)
    q = processing.XQRS(sig=x, fs=fs)
    q.detect(verbose=False)
    idx = np.asarray(q.qrs_inds, dtype=np.int64)
    if len(idx):
        idx = np.asarray(processing.correct_peaks(x, idx, search_radius=int(0.1 * fs),
                                                  smooth_window_size=int(0.15 * fs), peak_dir="compare"), dtype=np.int64)
        idx = np.unique(idx[(idx >= 0) & (idx < len(x))])
    return RPeakResult(idx + offset, np.full(len(idx), np.nan), {"wfdb_version": wfdb.__version__, "search_radius_ms": 100},
                       "wfdb_xqrs", "wfdb-" + wfdb.__version__)


def detect(x: np.ndarray, fs: float, algorithm: str = ALGORITHM, offset: int = 0) -> RPeakResult:
    if algorithm == "wfdb_xqrs":
        return detect_xqrs(x, fs, offset)
    return detect_pan_tompkins(x, fs, offset)


def match_peaks(reference: np.ndarray, detected: np.ndarray, tolerance: int) -> tuple[int, int, int]:
    """Greedy one-to-one matching within ``tolerance`` samples. Returns (TP, FP, FN)."""
    ref = np.sort(np.asarray(reference))
    det = np.sort(np.asarray(detected))
    used = np.zeros(len(det), dtype=bool)
    tp = 0
    j0 = 0
    for r in ref:
        while j0 < len(det) and det[j0] < r - tolerance:
            j0 += 1
        best, best_d = -1, tolerance + 1
        j = j0
        while j < len(det) and det[j] <= r + tolerance:
            if not used[j] and abs(int(det[j]) - int(r)) < best_d:
                best, best_d = j, abs(int(det[j]) - int(r))
            j += 1
        if best >= 0:
            used[best] = True
            tp += 1
    fp = int((~used).sum())
    fn = len(ref) - tp
    return tp, fp, fn


def segment_beats(r_peaks: np.ndarray, n: int, split_fraction: float = 0.6) -> list[tuple[int, int, int]]:
    """Beat regions [start, end) around each R peak.

    The boundary between beat i and i+1 lies at ``R_i + split_fraction*(R_{i+1}-R_i)``
    (default 0.6: P waves usually sit within the last 40 % of the RR interval).
    The first/last beats extend by the same fraction of the adjacent RR,
    clipped to the record.  Returns (start, end, r_peak) triples.
    """
    r = np.sort(np.asarray(r_peaks, dtype=np.int64))
    out = []
    for i, rp in enumerate(r):
        if i > 0:
            start = int(r[i - 1] + round(split_fraction * (rp - r[i - 1])))
        else:
            nxt = int(r[1] - rp) if len(r) > 1 else n
            start = max(0, int(rp - round((1 - split_fraction) * nxt)))
        if i + 1 < len(r):
            end = int(rp + round(split_fraction * (r[i + 1] - rp)))
        else:
            prev = int(rp - r[i - 1]) if i > 0 else n
            end = min(n, int(rp + round(split_fraction * prev)))
        if end > start:
            out.append((start, end, int(rp)))
    return out
