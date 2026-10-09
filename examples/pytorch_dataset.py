"""PyTorch Dataset for ECG Annotation Studio snapshots (format ecg-annotation-studio/snapshot-1).

Turns the per-tier segmentation masks of a snapshot into one wave-segmentation
target per lead:

    0 = background, 1 = P wave, 2 = QRS complex, 3 = T wave,
    IGNORE (-100) = unannotated / overlapping / uncertain / claimed by two tiers

and serves fixed-length windows ``x: float32 [n_leads, window]`` (mV) and
``y: int64 [n_leads, window]``.  Splits come from the snapshot's patient-level
assignment, so train/val/test never share a patient.

Usage (requires numpy and torch; CPU wheels are enough):

    python examples/pytorch_dataset.py path/to/<version>.zip --split train

The demo prints split statistics, checks that no patient crosses splits, and
runs one forward/backward pass of a tiny 1-D CNN with ``ignore_index``.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

IGNORE = -100
DEFAULT_TIERS = ("P Wave", "QRS Complex", "T Wave")


def open_snapshot(path: str | Path) -> Path:
    """Return a directory containing manifest.json (extracting a .zip if needed)."""
    p = Path(path)
    if p.is_dir():
        return p
    out = Path(tempfile.mkdtemp(prefix="ecg_snapshot_"))
    with zipfile.ZipFile(p) as z:
        z.extractall(out)
    hits = list(out.rglob("manifest.json"))
    if not hits:
        raise FileNotFoundError(f"{p} contains no manifest.json")
    return hits[0].parent


def combined_target(npz, meta: dict, tiers: tuple[str, ...]) -> np.ndarray:
    """[n_leads, n] int64 target from the per-tier dense masks."""
    n_leads, n = len(meta["leads"]), meta["n_samples"]
    y = np.zeros((n_leads, n), dtype=np.int64)
    claimed = np.zeros((n_leads, n), dtype=np.int8)
    ignore = np.zeros((n_leads, n), dtype=bool)
    for cls, tier in enumerate(tiers, start=1):
        info = meta["masks"].get(tier)
        if info is None:
            raise KeyError(f"snapshot has no mask for tier {tier!r}; export with mask_tiers including it")
        m = npz[f"mask_{info['key']}"]
        inside = m >= 1
        y[inside] = cls
        claimed += inside
        ignore |= m < 0  # -1 unannotated, -2 overlap, -3 uncertain
    ignore |= claimed > 1
    y[ignore] = IGNORE
    return y


class ECGSegmentationDataset(Dataset):
    def __init__(self, snapshot: str | Path, split: str = "train", tiers: tuple[str, ...] = DEFAULT_TIERS,
                 window_s: float = 2.0, stride_s: float | None = None, min_labelled: float = 0.5):
        self.root = open_snapshot(snapshot)
        self.manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.tiers = tiers
        self.records: list[tuple[np.ndarray, np.ndarray, dict]] = []
        self.index: list[tuple[int, int]] = []
        for r in self.manifest["recordings"]:
            if r["split"] != split:
                continue
            with np.load(self.root / r["signal_file"], allow_pickle=False) as z:
                meta = json.loads(str(z["meta_json"]))
                x = z["signal"].T.astype(np.float32)  # [leads, n]
                y = combined_target(z, meta, tiers)
            fs = float(meta["fs"])
            win = int(round(window_s * fs))
            hop = int(round((stride_s or window_s) * fs))
            ri = len(self.records)
            self.records.append((x, y, meta))
            for s in range(0, max(1, meta["n_samples"] - win + 1), hop):
                if (y[:, s:s + win] != IGNORE).mean() >= min_labelled:
                    self.index.append((ri, s))
            self.window = win

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, i: int):
        ri, s = self.index[i]
        x, y, meta = self.records[ri]
        return torch.from_numpy(x[:, s:s + self.window]), torch.from_numpy(y[:, s:s + self.window]), meta["recording_id"]


def _demo() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot")
    ap.add_argument("--split", default="train")
    ap.add_argument("--window", type=float, default=2.0)
    args = ap.parse_args()
    root = open_snapshot(args.snapshot)
    splits = json.loads((root / "splits.json").read_text(encoding="utf-8"))
    pats = splits["patients"]
    names = list(pats)
    leaks = {p for i, a in enumerate(names) for b in names[i + 1:] for p in set(pats[a]) & set(pats[b])}
    print("splits:", {k: len(v) for k, v in splits["recordings"].items()}, "| patient leakage:", sorted(leaks) or "none")
    if leaks:
        return 1
    ds = ECGSegmentationDataset(root, args.split, window_s=args.window)
    if not len(ds):
        print(f"split {args.split!r} has no labelled windows")
        return 1
    counts = np.zeros(4, dtype=np.int64)
    ign = 0
    for _, y, _ in ds.records:
        counts += np.bincount(y[y != IGNORE].ravel(), minlength=4)[:4]
        ign += int((y == IGNORE).sum())
    print(f"{args.split}: {len(ds.records)} recordings, {len(ds)} windows of {ds.window} samples;"
          f" labelled samples bg/P/QRS/T = {counts.tolist()}, ignored = {ign}")
    x, y, rec_ids = next(iter(DataLoader(ds, batch_size=4, shuffle=True)))
    n_leads = x.shape[1]
    model = torch.nn.Sequential(
        torch.nn.Conv1d(n_leads, 16, 9, padding=4), torch.nn.ReLU(),
        torch.nn.Conv1d(16, 4 * n_leads, 9, padding=4),
    )
    logits = model(x).view(x.shape[0], 4, n_leads, x.shape[2])
    loss = torch.nn.functional.cross_entropy(logits, y, ignore_index=IGNORE)
    loss.backward()
    print(f"batch x{tuple(x.shape)} y{tuple(y.shape)} from {sorted(set(rec_ids))}; loss={loss.item():.4f} (untrained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
