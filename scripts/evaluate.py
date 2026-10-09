"""Evaluate the R-peak detectors and the experimental delineator on real PhysioNet data.

Prerequisite (about 110 MB, SHA-256 verified):

    python scripts/download_datasets.py --preset evaluation --out data/physionet_eval

Then:

    python scripts/evaluate.py --root data/physionet_eval --out docs/evaluation

Protocol
--------
R peaks, MIT-BIH (48 records, 30 min, 360 Hz):
  * reference = every ``.atr`` beat annotation (beat symbols only), channel 0;
  * a detection matches a reference beat if within +/-150 ms (ANSI/AAMI EC57
    tolerance), greedy one-to-one; TP/FP/FN, precision (+P), recall (Se), F1;
  * reported for all 48 records and for the 44 non-paced records
    (102, 104, 107, 217 excluded, as in AAMI practice). Unlike EC57 the first
    5 minutes are *not* excluded (the detectors have no learning phase to
    discount), so the numbers are slightly conservative.
R peaks, LUDB (200 records, 10 s, 500 Hz, lead II):
  * reference = 'N' annotations of lead II; LUDB leaves the first/last beat
    of many records unannotated, so detections are scored only inside
    [first annotated QRS onset - 150 ms, last annotated QRS offset + 150 ms].
Delineation, LUDB lead II (experimental delineator):
  * anchored on the *reference* R peaks so that delineation error is isolated
    from detection error;
  * for every reference P/QRS/T interval of lead II, the delineated wave of the
    same beat is compared: onset error = detected start - reference start,
    offset error = (detected end - 1) - (reference end - 1), in ms;
  * reported: n reference waves, n delineated, sensitivity (wave found),
    mean, SD and median |error|, and the fraction within the CSE 2*SD
    tolerances (P on 10.2 / off 12.7, QRS on 6.5 / off 11.6, T off 30.6 ms);
  * thresholds were calibrated on records 1-100 only
    (scripts/calibrate_delineation.py); records 101-200 are the held-out split.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.datasets.ludb import LUDBAdapter  # noqa: E402
from app.datasets.mitdb import MITDBAdapter, beat_reference  # noqa: E402
from app.signal.delineation import PARAMS as DELIN_PARAMS, VERSION as DELIN_VERSION, delineate  # noqa: E402
from app.signal.rpeak import VERSION as PT_VERSION, detect, match_peaks  # noqa: E402

ALGORITHMS = ("scipy_pan_tompkins", "wfdb_xqrs")
PACED = {"102", "104", "107", "217"}
TOL_MS = 150.0
CSE_TOL = {"P_on": 10.2, "P_off": 12.7, "QRS_on": 6.5, "QRS_off": 11.6, "T_off": 30.6}


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * p * r / (p + r) if p + r else float("nan")
    return {"TP": tp, "FP": fp, "FN": fn, "precision": round(p, 5), "recall": round(r, 5), "F1": round(f, 5)}


def eval_mitdb(args: tuple[str, str]) -> dict:
    root, record = args
    ad = MITDBAdapter()
    _, sig, leads, _, _ = ad.read_signal(Path(root), record)
    ref, _ = beat_reference(Path(root), record, ad.record_prefix)
    fs = 360.0
    tol = int(round(TOL_MS * fs / 1000))
    out = {"record": record, "lead": leads[0], "n_ref": len(ref)}
    for alg in ALGORITHMS:
        t0 = time.perf_counter()
        det = detect(sig[:, 0].astype(np.float64), fs, alg).samples
        tp, fp, fn = match_peaks(np.asarray(ref), det, tol)
        out[alg] = {**prf(tp, fp, fn), "seconds": round(time.perf_counter() - t0, 2)}
    return out


def _wave(anns, tier: str, lead: str):
    return sorted((a.start, a.end) for a in anns if a.tier == tier and a.lead == lead and a.kind == "interval")


def eval_ludb(args: tuple[str, str]) -> dict:
    root, record = args
    ad = LUDBAdapter()
    pr = ad.parse(Path(root), record)
    fs = pr.fs
    li = pr.leads.index("II")
    x = pr.signal[:, li].astype(np.float64)
    tol = int(round(TOL_MS * fs / 1000))
    ref_r = np.array(sorted(a.start for a in pr.annotations if a.label == "R_peak" and a.lead == "II"), dtype=np.int64)
    qrs = _wave(pr.annotations, "QRS Complex", "II")
    out: dict = {"record": record, "n_ref_r": int(len(ref_r)), "rhythm": pr.meta.get("rhythm")}
    if len(qrs):
        lo, hi = qrs[0][0] - tol, qrs[-1][1] - 1 + tol
        for alg in ALGORITHMS:
            det = detect(x, fs, alg).samples
            det = det[(det >= lo) & (det <= hi)]
            out[alg] = prf(*match_peaks(ref_r, det, tol))
    errs, counts = delineation_errors(pr)
    out["delineation"] = {"counts": counts, "errors_ms": errs}
    return out


def delineation_errors(pr, params: dict | None = None) -> tuple[dict[str, list[float]], dict[str, dict[str, int]]]:
    """Delineate lead II anchored on the reference R peaks and compare with the reference waves."""
    fs = pr.fs
    x = pr.signal[:, pr.leads.index("II")].astype(np.float64)
    ref_r = np.array(sorted(a.start for a in pr.annotations if a.label == "R_peak" and a.lead == "II"), dtype=np.int64)
    beats = delineate(x, fs, ref_r, **(params or {})) if len(ref_r) else []
    errs: dict[str, list[float]] = {k: [] for k in ("P_on", "P_off", "QRS_on", "QRS_off", "T_on", "T_off")}
    counts = {}
    ms = 1000.0 / fs
    near = int(0.05 * fs)
    for tier, key in (("P Wave", "p"), ("QRS Complex", "qrs"), ("T Wave", "t")):
        name = {"p": "P", "qrs": "QRS", "t": "T"}[key]
        refs = _wave(pr.annotations, tier, "II")
        found = 0
        for (s, e) in refs:
            cand = [b for b in beats if key in b and b[key][0] < e + near and b[key][1] > s - near]
            if not cand:
                continue
            b = min(cand, key=lambda bb: abs(bb[key][0] - s))
            found += 1
            errs[f"{name}_on"].append((b[key][0] - s) * ms)
            errs[f"{name}_off"].append(((b[key][1] - 1) - (e - 1)) * ms)
        counts[name] = {"n_ref": len(refs), "n_matched": found, "n_delineated": sum(1 for b in beats if key in b)}
    return errs, counts


def summarize_errors(per: list[dict]) -> dict:
    all_err: dict[str, list[float]] = {}
    counts: dict[str, dict[str, int]] = {}
    for r in per:
        for k, v in r["delineation"]["errors_ms"].items():
            all_err.setdefault(k, []).extend(v)
        for w, c in r["delineation"]["counts"].items():
            agg = counts.setdefault(w, {"n_ref": 0, "n_matched": 0, "n_delineated": 0})
            for kk in agg:
                agg[kk] += c[kk]
    out = {}
    for k, v in all_err.items():
        a = np.asarray(v)
        d = {"n": int(len(a))}
        if len(a):
            d.update(mean=round(float(a.mean()), 2), sd=round(float(a.std(ddof=1)) if len(a) > 1 else 0.0, 2),
                     median_abs=round(float(np.median(np.abs(a))), 2))
            if k in CSE_TOL:
                d["within_cse_tol"] = round(float(np.mean(np.abs(a) <= CSE_TOL[k])), 4)
                d["cse_tol_ms"] = CSE_TOL[k]
        out[k] = d
    for w, c in counts.items():
        c["sensitivity"] = round(c["n_matched"] / c["n_ref"], 4) if c["n_ref"] else None
    return {"errors_ms": out, "counts": counts}


def aggregate(per: list[dict], alg: str) -> dict:
    tp = sum(r[alg]["TP"] for r in per if alg in r)
    fp = sum(r[alg]["FP"] for r in per if alg in r)
    fn = sum(r[alg]["FN"] for r in per if alg in r)
    return {**prf(tp, fp, fn), "n_records": sum(1 for r in per if alg in r)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(ROOT / "data" / "physionet_eval"))
    p.add_argument("--out", default=str(ROOT / "docs" / "evaluation"))
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--only", choices=["mitdb", "ludb"])
    args = p.parse_args()
    root = Path(args.root)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "protocol": __doc__.split("Protocol", 1)[1].strip(),
        "tolerance_ms": TOL_MS,
        "algorithms": {"scipy_pan_tompkins": PT_VERSION, "wfdb_xqrs": "wfdb", "delineator": DELIN_VERSION},
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with ProcessPoolExecutor(args.workers) as ex:
        if args.only in (None, "mitdb"):
            recs = MITDBAdapter().available_records(root / "mitdb")
            if not recs:
                print("no MIT-BIH records under", root / "mitdb", file=sys.stderr)
                return 2
            per = list(ex.map(eval_mitdb, [(str(root / "mitdb"), r) for r in recs]))
            non_paced = [r for r in per if r["record"] not in PACED]
            result["mitdb"] = {
                "records": per,
                "all": {a: aggregate(per, a) for a in ALGORITHMS},
                "non_paced_44": {a: aggregate(non_paced, a) for a in ALGORITHMS},
            }
            print("MIT-BIH", json.dumps({"all": result["mitdb"]["all"], "non_paced": result["mitdb"]["non_paced_44"]}, indent=1))
        if args.only in (None, "ludb"):
            recs = sorted(LUDBAdapter().available_records(root / "ludb"), key=lambda s: int(s))
            if not recs:
                print("no LUDB records under", root / "ludb", file=sys.stderr)
                return 2
            per = list(ex.map(eval_ludb, [(str(root / "ludb"), r) for r in recs]))
            result["ludb"] = {
                "records": [{k: v for k, v in r.items() if k != "delineation"} | {"delineation_counts": r["delineation"]["counts"]} for r in per],
                "rpeak": {a: aggregate(per, a) for a in ALGORITHMS},
                "delineation": summarize_errors(per),
                "delineation_calibration_1_100": summarize_errors([r for r in per if int(r["record"]) <= 100]),
                "delineation_heldout_101_200": summarize_errors([r for r in per if int(r["record"]) > 100]),
                "delineation_params": DELIN_PARAMS,
            }
            print("LUDB R", json.dumps(result["ludb"]["rpeak"], indent=1))
            print("LUDB delineation (held-out 101-200)", json.dumps(result["ludb"]["delineation_heldout_101_200"], indent=1))
    name = "results.json" if args.only is None else f"results_{args.only}.json"
    (out_dir / name).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("wrote", out_dir / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
