"""Signal storage on the local filesystem.

Signals are stored as float32 ``.npy`` arrays of shape ``[n_samples, n_leads]``
in millivolts and opened with ``mmap_mode='r'`` so long recordings are read
chunk-wise without loading the whole file.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .config import get_settings


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save_signal(recording_id: str, signal: np.ndarray) -> tuple[str, str]:
    """Persist signal; return (path relative to DATA_DIR, sha256)."""
    settings = get_settings()
    settings.signals_dir.mkdir(parents=True, exist_ok=True)
    arr = np.ascontiguousarray(signal, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("signal must be 2-D [samples, leads]")
    path = settings.signals_dir / f"{recording_id}.npy"
    np.save(path, arr, allow_pickle=False)
    return path.relative_to(settings.data_dir).as_posix(), sha256_file(path)


def resolve(rel_path: str) -> Path:
    p = Path(rel_path)
    return p if p.is_absolute() else get_settings().data_dir / p


def load_signal(rel_path: str) -> np.ndarray:
    return np.load(resolve(rel_path), mmap_mode="r", allow_pickle=False)


def envelope(values: np.ndarray, bucket: int) -> tuple[np.ndarray, np.ndarray]:
    """Min/max per bucket of ``bucket`` consecutive samples (last bucket may be partial)."""
    n = len(values)
    full = n // bucket
    mins = np.empty(full + (1 if n % bucket else 0), dtype=np.float32)
    maxs = np.empty_like(mins)
    if full:
        block = np.asarray(values[: full * bucket]).reshape(full, bucket)
        mins[:full] = block.min(axis=1)
        maxs[:full] = block.max(axis=1)
    if n % bucket:
        tail = np.asarray(values[full * bucket:])
        mins[-1] = tail.min()
        maxs[-1] = tail.max()
    return mins, maxs
