"""Beat-level ECG measurements derived from annotation coordinates and samples.

Conventions
-----------
* Durations of intervals use the half-open geometry: ``(end - start) / fs``.
  Fiducial point pairs (onset, offset) are first converted to
  ``[onset, offset + 1)``.
* PR interval = QRS start - P start;  QT interval = T end - QRS start;
  RR = R_i - R_{i-1}.
* Every value carries the sample indices and annotation ids it derives from.
  If a required annotation is missing the value is ``None`` with a reason.
* ST deviation and amplitudes are labelled ``experimental``: baseline =
  median of the PR segment ``[P end, QRS start)`` when a P wave exists, else of
  ``[QRS start - 40 ms, QRS start - 10 ms)``; ST level is sampled at
  J + 60 ms where J = last QRS sample (end - 1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

BEAT_POINT_TIERS = {"Beat"}


@dataclass
class A:
    id: str
    tier: str
    label: str
    lead: str | None
    start: int
    end: int | None

    @classmethod
    def from_any(cls, d: Any) -> "A":
        g = d.get if isinstance(d, dict) else (lambda k, default=None: getattr(d, k, default))
        return cls(str(g("id")), g("tier"), g("label"), g("lead"), int(g("start_sample")), g("end_sample"))


def _on_lead(a: A, lead: str | None) -> bool:
    return a.lead is None or lead is None or a.lead == lead


def _value(name: str, value: float | None, unit: str, samples: list[int], ids: list[str], method: str,
           experimental: bool = False, reason: str | None = None) -> dict:
    return {"name": name, "value": value, "unit": unit, "samples": samples, "annotation_ids": ids,
            "method": method, "experimental": experimental, "reason": reason if value is None else None}


def _na(name: str, unit: str, reason: str, experimental: bool = False) -> dict:
    return _value(name, None, unit, [], [], "", experimental, reason)


def compute_measurements(annotations: Iterable[Any], signal: np.ndarray | None, fs: float, lead: str | None,
                         lead_index: int | None, window: tuple[int, int] | None = None) -> dict:
    anns = [A.from_any(a) for a in annotations]
    anns = [a for a in anns if _on_lead(a, lead)]
    r_points = sorted((a for a in anns if a.end is None and a.label == "R_peak"), key=lambda a: a.start)
    anchor_kind = "R_peak"
    if not r_points:
        r_points = sorted((a for a in anns if a.end is None and a.tier in BEAT_POINT_TIERS), key=lambda a: a.start)
        anchor_kind = "Beat"
    if not r_points:
        qrs_only = sorted((a for a in anns if a.label == "QRS_complex" and a.end is not None), key=lambda a: a.start)
        r_points = [A(q.id, q.tier, "QRS_center", q.lead, (q.start + q.end - 1) // 2, None) for q in qrs_only]
        anchor_kind = "QRS_complex center"
    # one anchor per sample (global and lead-specific duplicates collapse)
    dedup: dict[int, A] = {}
    for a in r_points:
        dedup.setdefault(a.start, a)
    anchors = [dedup[k] for k in sorted(dedup)]
    intervals = {lab: sorted((a for a in anns if a.label == lab and a.end is not None), key=lambda a: a.start)
                 for lab in ("P_wave", "QRS_complex", "T_wave")}
    points = {lab: sorted((a for a in anns if a.label == lab and a.end is None), key=lambda a: a.start)
              for lab in ("P_onset", "P_offset", "QRS_onset", "QRS_offset", "T_offset")}
    x = None
    if signal is not None and lead_index is not None:
        x = signal[:, lead_index]
    ms = lambda samples: 1000.0 * samples / fs  # noqa: E731
    beats_out = []
    for i, r in enumerate(anchors):
        if window and not (window[0] <= r.start < window[1]):
            continue
        res: dict = {"r_sample": r.start, "anchor": anchor_kind, "anchor_id": r.id, "values": []}
        vals = res["values"]
        if i > 0:
            p = anchors[i - 1]
            vals.append(_value("RR", ms(r.start - p.start), "ms", [p.start, r.start], [p.id, r.id],
                               f"R[i]-R[i-1] using {anchor_kind} anchors"))
            vals.append(_value("HR", 60000.0 / ms(r.start - p.start), "bpm", [p.start, r.start], [p.id, r.id],
                               "60000 / RR"))
        else:
            vals.append(_na("RR", "ms", "N/A: no previous beat anchor"))
            vals.append(_na("HR", "bpm", "N/A: no previous beat anchor"))
        # QRS: interval containing R or onset/offset points around it
        qrs = next((q for q in intervals["QRS_complex"] if q.start <= r.start < q.end), None)
        qrs_bounds: tuple[int, int, list[str]] | None = None
        if qrs:
            qrs_bounds = (qrs.start, qrs.end, [qrs.id])
        else:
            on = next((p for p in reversed(points["QRS_onset"]) if r.start - fs * 0.2 <= p.start <= r.start), None)
            off = next((p for p in points["QRS_offset"] if r.start <= p.start <= r.start + fs * 0.2), None)
            if on and off:
                qrs_bounds = (on.start, off.start + 1, [on.id, off.id])
        if qrs_bounds:
            vals.append(_value("QRS duration", ms(qrs_bounds[1] - qrs_bounds[0]), "ms", [qrs_bounds[0], qrs_bounds[1]],
                               qrs_bounds[2], "QRS end - QRS start (half-open)"))
        else:
            vals.append(_na("QRS duration", "ms", "N/A: no QRS interval / onset+offset around this beat"))
        # P wave preceding QRS
        p_bounds: tuple[int, int, list[str]] | None = None
        q_start = qrs_bounds[0] if qrs_bounds else r.start
        pw = next((p for p in reversed(intervals["P_wave"]) if q_start - fs * 0.45 <= p.start < q_start), None)
        if pw:
            p_bounds = (pw.start, pw.end, [pw.id])
        else:
            pon = next((p for p in reversed(points["P_onset"]) if q_start - fs * 0.45 <= p.start < q_start), None)
            poff = next((p for p in reversed(points["P_offset"]) if pon and pon.start < p.start < q_start), None)
            if pon and poff:
                p_bounds = (pon.start, poff.start + 1, [pon.id, poff.id])
        if p_bounds and qrs_bounds:
            vals.append(_value("PR interval", ms(qrs_bounds[0] - p_bounds[0]), "ms", [p_bounds[0], qrs_bounds[0]],
                               p_bounds[2] + qrs_bounds[2], "QRS start - P start"))
            vals.append(_value("P duration", ms(p_bounds[1] - p_bounds[0]), "ms", [p_bounds[0], p_bounds[1]],
                               p_bounds[2], "P end - P start (half-open)"))
        else:
            reason = "N/A: missing " + " and ".join(n for n, v in (("P wave", p_bounds), ("QRS", qrs_bounds)) if not v)
            vals.append(_na("PR interval", "ms", reason))
            vals.append(_na("P duration", "ms", "N/A: missing P wave" if not p_bounds else reason))
        # T wave following QRS
        t_end: tuple[int, list[str]] | None = None
        t_iv = None
        if qrs_bounds:
            t_iv = next((t for t in intervals["T_wave"] if qrs_bounds[1] - 1 <= t.start <= qrs_bounds[0] + fs * 0.7), None)
            if t_iv:
                t_end = (t_iv.end, [t_iv.id])
            else:
                toff = next((t for t in points["T_offset"] if qrs_bounds[1] <= t.start <= qrs_bounds[0] + fs * 0.8), None)
                if toff:
                    t_end = (toff.start + 1, [toff.id])
        if qrs_bounds and t_end:
            qt = ms(t_end[0] - qrs_bounds[0])
            vals.append(_value("QT interval", qt, "ms", [qrs_bounds[0], t_end[0]], qrs_bounds[2] + t_end[1],
                               "T end - QRS start"))
            rr_val = next((v["value"] for v in vals if v["name"] == "RR" and v["value"]), None)
            if rr_val:
                vals.append(_value("QTc (Bazett)", qt / np.sqrt(rr_val / 1000.0), "ms", [qrs_bounds[0], t_end[0]],
                                   qrs_bounds[2] + t_end[1], "QT / sqrt(RR[s])"))
            else:
                vals.append(_na("QTc (Bazett)", "ms", "N/A: RR unavailable"))
        else:
            vals.append(_na("QT interval", "ms", "N/A: missing " + ("T wave end" if qrs_bounds else "QRS")))
            vals.append(_na("QTc (Bazett)", "ms", "N/A: QT unavailable"))
        # amplitude measurements (experimental)
        if x is not None and qrs_bounds:
            if p_bounds and p_bounds[1] < qrs_bounds[0]:
                b0, b1, bmethod = p_bounds[1], qrs_bounds[0], "median of PR segment"
            else:
                b0, b1 = qrs_bounds[0] - int(0.04 * fs), qrs_bounds[0] - int(0.01 * fs)
                bmethod = "median of [QRS start-40ms, QRS start-10ms)"
            b0, b1 = max(0, b0), max(1, b1)
            baseline = float(np.median(x[b0:b1])) if b1 > b0 else float(x[max(0, qrs_bounds[0] - 1)])
            vals.append(_value("Baseline", baseline, "mV", [b0, b1], qrs_bounds[2], bmethod, experimental=True))
            vals.append(_value("R amplitude", float(x[r.start]) - baseline, "mV", [r.start], [r.id],
                               f"x[R] - baseline ({bmethod})", experimental=True))
            seg = np.asarray(x[qrs_bounds[0]:qrs_bounds[1]])
            if len(seg):
                k = int(np.argmax(np.abs(seg - baseline)))
                vals.append(_value("QRS peak amplitude", float(seg[k]) - baseline, "mV", [qrs_bounds[0] + k],
                                   qrs_bounds[2], "max |x - baseline| within QRS", experimental=True))
            j = qrs_bounds[1] - 1
            st = j + int(round(0.06 * fs))
            if st < len(x):
                vals.append(_value("ST deviation (J+60ms)", float(x[st]) - baseline, "mV", [j, st], qrs_bounds[2],
                                   f"x[J+60ms] - baseline ({bmethod})", experimental=True))
            else:
                vals.append(_na("ST deviation (J+60ms)", "mV", "N/A: J+60ms beyond record", True))
            if t_iv is not None:
                tseg = np.asarray(x[t_iv.start:t_iv.end])
                k = int(np.argmax(np.abs(tseg - baseline)))
                vals.append(_value("T peak amplitude", float(tseg[k]) - baseline, "mV", [t_iv.start + k], [t_iv.id],
                                   "max |x - baseline| within T wave", experimental=True))
        else:
            vals.append(_na("ST deviation (J+60ms)", "mV", "N/A: requires QRS boundaries and signal", True))
        beats_out.append(res)
    summary: dict[str, dict] = {}
    for b in beats_out:
        for v in b["values"]:
            if v["value"] is not None and v["name"] != "Baseline":
                summary.setdefault(v["name"], {"unit": v["unit"], "values": []})["values"].append(v["value"])
    for name, s in summary.items():
        arr = np.asarray(s.pop("values"))
        s.update({"n": int(len(arr)), "mean": float(arr.mean()), "median": float(np.median(arr)),
                  "std": float(arr.std()), "min": float(arr.min()), "max": float(arr.max())})
    return {"lead": lead, "fs": fs, "anchor": anchor_kind if anchors else None, "beats": beats_out, "summary": summary,
            "conventions": __doc__}
