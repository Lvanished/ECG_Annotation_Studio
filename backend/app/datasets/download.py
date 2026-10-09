"""Reproducible PhysioNet downloads with SHA-256 verification.

PhysioNet publishes ``SHA256SUMS.txt`` for every project version; each
downloaded file is checked against it.  A file that fails verification is
deleted and reported.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .base import DatasetAdapter

USER_AGENT = "ECG-Annotation-Studio/1.0 (research prototype; +https://physionet.org)"


def _get(url: str, timeout: float = 60.0, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # network errors: retry with backoff
            last = e
        time.sleep(1.5 * (attempt + 1))
    assert last is not None
    raise last


def fetch_checksums(adapter: DatasetAdapter, root: Path) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    cache = root / "SHA256SUMS.txt"
    if not cache.exists():
        cache.write_bytes(_get(adapter.base_url + "SHA256SUMS.txt"))
    sums: dict[str, str] = {}
    for line in cache.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download_record(adapter: DatasetAdapter, record: str, root: Path, sums: dict[str, str]) -> list[dict]:
    """Download (or re-verify) all files of one record. Returns manifest entries."""
    entries = []
    for rel, required in adapter.record_files(record):
        target = root / rel
        expected = sums.get(rel)
        if expected is None:
            if required:
                raise RuntimeError(f"{adapter.id}: {rel} not listed in SHA256SUMS.txt")
            continue  # optional file does not exist for this record
        if target.exists() and sha256(target) == expected:
            entries.append({"file": rel, "sha256": expected, "status": "verified-cached"})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _get(adapter.base_url + rel)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Checksum mismatch for {rel}: expected {expected}, got {actual}")
        target.write_bytes(data)
        entries.append({"file": rel, "sha256": actual, "status": "downloaded"})
    return entries


def download(adapter: DatasetAdapter, records: list[str], root: Path, *, extra_files: tuple[str, ...] = (),
             workers: int = 6) -> dict:
    sums = fetch_checksums(adapter, root)
    manifest: dict = {
        "dataset": adapter.id, "version": adapter.version, "source": adapter.base_url,
        "license": adapter.license, "records": {}, "failures": {},
    }
    for extra in extra_files:
        try:
            target = root / extra
            if not target.exists():
                target.write_bytes(_get(adapter.base_url + extra))
            if extra in sums and sha256(target) != sums[extra]:
                raise RuntimeError(f"Checksum mismatch for {extra}")
        except Exception as e:  # pragma: no cover - network dependent
            manifest["failures"][extra] = repr(e)
    from concurrent.futures import ThreadPoolExecutor

    def one(r: str) -> tuple[str, list[dict] | None, str | None]:
        try:
            return r, download_record(adapter, r, root, sums), None
        except Exception as e:
            return r, None, repr(e)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r, entries, err in pool.map(one, records):
            if err is None:
                manifest["records"][r] = entries
            else:
                manifest["failures"][r] = err
    (root / "download_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
