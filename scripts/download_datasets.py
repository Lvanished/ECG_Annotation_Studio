"""Download PhysioNet ECG records with SHA-256 verification.

Examples (run from the repository root):

    python scripts/download_datasets.py --preset bundled
    python scripts/download_datasets.py --dataset ludb --records 1 2 3
    python scripts/download_datasets.py --preset evaluation --out data/physionet_eval

All three databases (LUDB 1.0.1, QTDB 1.0.0, MIT-BIH 1.0.0) are published on
PhysioNet under the Open Data Commons Attribution License v1.0; cite them as
listed in docs/THIRD_PARTY_AND_DATA.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.datasets import ADAPTERS, BUNDLED_RECORDS  # noqa: E402
from app.datasets.download import download  # noqa: E402

MITDB_ALL = [
    "100", "101", "102", "103", "104", "105", "106", "107", "108", "109", "111", "112", "113", "114", "115",
    "116", "117", "118", "119", "121", "122", "123", "124", "200", "201", "202", "203", "205", "207", "208",
    "209", "210", "212", "213", "214", "215", "217", "219", "220", "221", "222", "223", "228", "230", "231",
    "232", "233", "234",
]
EVALUATION = {
    "mitdb": MITDB_ALL,
    "ludb": [str(i) for i in range(1, 201)],
}
EXTRA_FILES = {"ludb": ("RECORDS", "ludb.csv", "LICENSE.txt"), "qtdb": ("RECORDS",), "mitdb": ("RECORDS",)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preset", choices=["bundled", "evaluation"])
    p.add_argument("--dataset", choices=sorted(ADAPTERS))
    p.add_argument("--records", nargs="*", default=[])
    p.add_argument("--out", default=str(ROOT / "data" / "physionet"))
    args = p.parse_args()
    if args.preset:
        plan = BUNDLED_RECORDS if args.preset == "bundled" else EVALUATION
    elif args.dataset:
        plan = {args.dataset: args.records or BUNDLED_RECORDS[args.dataset]}
    else:
        p.error("choose --preset or --dataset")
    ok = True
    for ds, records in plan.items():
        adapter = ADAPTERS[ds]
        root = Path(args.out) / ds
        print(f"[{ds}] {len(records)} record(s) from {adapter.base_url} -> {root}")
        manifest = download(adapter, records, root, extra_files=EXTRA_FILES.get(ds, ()))
        n_ok = len(manifest["records"])
        print(f"[{ds}] verified {n_ok}/{len(records)} records")
        if manifest["failures"]:
            ok = False
            print(json.dumps(manifest["failures"], indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
