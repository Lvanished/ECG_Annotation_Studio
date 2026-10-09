"""Grid-search the experimental delineator thresholds on LUDB records 1-100 only.

Records 101-200 are never used here; scripts/evaluate.py reports them as the
held-out split. Default objective (``--objective cse``): mean fraction of P
on/off and QRS on/off boundaries of lead II outside the CSE tolerances,
anchored on reference R peaks; ``--objective mae`` minimises the mean
absolute error instead.

    python scripts/calibrate_delineation.py --root data/physionet_eval
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.datasets.ludb import LUDBAdapter  # noqa: E402
from evaluate import delineation_errors  # noqa: E402

GRID = {"qrs_slope_fraction": [0.02, 0.03, 0.04, 0.06, 0.08, 0.10, 0.12], "qrs_hold_ms": [3.0, 4.0, 6.0, 10.0, 16.0],
        "p_level_fraction": [0.15, 0.25, 0.35, 0.45, 0.55]}
CAL_RECORDS = [str(i) for i in range(1, 101)]


def _load(args):
    root, r = args
    return LUDBAdapter().parse(Path(root), r)


CSE_TOL = {"P_on": 10.2, "P_off": 12.7, "QRS_on": 6.5, "QRS_off": 11.6}


def _score(args):
    parsed, prm, objective = args
    errs: dict[str, list[float]] = {}
    for pr in parsed:
        e, _ = delineation_errors(pr, prm)
        for k, v in e.items():
            errs.setdefault(k, []).extend(v)
    if objective == "cse":
        # minimise the mean fraction of boundaries *outside* the CSE tolerance
        per = {k: float(np.mean(np.abs(errs[k]) > t)) for k, t in CSE_TOL.items()}
    else:
        per = {k: float(np.mean(np.abs(errs[k]))) for k in CSE_TOL}
    return prm, float(np.mean(list(per.values()))), per


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=str(ROOT / "data" / "physionet_eval"))
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--objective", choices=["cse", "mae"], default="cse")
    args = p.parse_args()
    root = str(Path(args.root) / "ludb")
    with ProcessPoolExecutor(args.workers) as ex:
        parsed = list(ex.map(_load, [(root, r) for r in CAL_RECORDS]))
        combos = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
        results = list(ex.map(_score, [(parsed, c, args.objective) for c in combos]))
    results.sort(key=lambda t: t[1])
    for prm, score, per in results[:8]:
        print(f"{score:7.3f}  {prm}  {json.dumps({k: round(v, 3) for k, v in per.items()})}")
    best = results[0]
    print("best", json.dumps(best[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
