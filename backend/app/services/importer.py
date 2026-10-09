"""Register parsed WFDB records (and their reference annotations) in the database."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..datasets import ADAPTERS, BUNDLED_RECORDS, get_adapter
from ..datasets.base import DatasetAdapter, ParsedRecord
from ..datasets.download import sha256
from ..models import Annotation, Dataset, Recording
from ..ontology import OntologyCache
from ..storage import save_signal
from .annotations import record_revision

log = logging.getLogger(__name__)


def ensure_dataset(s: Session, adapter: DatasetAdapter) -> Dataset:
    ds = s.get(Dataset, adapter.id)
    if ds is None:
        ds = Dataset(id=adapter.id, name=adapter.name, version=adapter.version, source_url=adapter.page_url,
                     license=adapter.license, citation=adapter.citation, description=adapter.description,
                     annotation_semantics=adapter.annotation_semantics)
        s.add(ds)
        s.flush()
    return ds


def ensure_upload_dataset(s: Session) -> Dataset:
    ds = s.get(Dataset, "uploads")
    if ds is None:
        ds = Dataset(id="uploads", name="User uploads", version="", license="user-provided",
                     description="Recordings uploaded as calibrated NPZ files",
                     annotation_semantics="No reference annotations")
        s.add(ds)
        s.flush()
    return ds


def register_parsed(s: Session, adapter: DatasetAdapter, parsed: ParsedRecord, source_files: dict[str, str]) -> Recording:
    ensure_dataset(s, adapter)
    onto = OntologyCache.load(s)
    rec_id = str(uuid.uuid4())
    rel_path, digest = save_signal(rec_id, parsed.signal)
    n = int(parsed.signal.shape[0])
    rec = Recording(
        id=rec_id, dataset_id=adapter.id, name=parsed.name, fs=parsed.fs, n_samples=n, leads=parsed.leads,
        units=["mV"] * len(parsed.leads), original_units=parsed.original_units, gains=parsed.gains,
        patient_id=parsed.patient_id, meta={**parsed.meta, "duration_s": n / parsed.fs},
        signal_path=rel_path, signal_sha256=digest, source="physionet", source_files=source_files,
    )
    s.add(rec)
    s.flush()
    rejected = 0
    for ra in parsed.annotations:
        errors = onto.validate(ra.tier, ra.label, ra.kind, ra.attributes)
        if errors or not (0 <= ra.start < n) or (ra.end is not None and not ra.start < ra.end <= n):
            rejected += 1
            log.warning("Skipping reference annotation %s %s: %s", ra.label, ra.start, errors)
            continue
        a = Annotation(
            id=str(uuid.uuid4()), recording_id=rec.id, tier=ra.tier, label=ra.label, lead=ra.lead, kind=ra.kind,
            start_sample=ra.start, end_sample=ra.end, attributes=ra.attributes, source="reference",
            provenance=ra.provenance, review_status="reviewed", ontology_version=onto.version, revision=1,
        )
        s.add(a)
        s.flush()
        record_revision(s, a, "create", None, actor=f"import:{adapter.id}")
    rec.meta = {**rec.meta, "reference_annotations": len(parsed.annotations) - rejected,
                "reference_annotations_rejected": rejected}
    return rec


def import_record(s: Session, dataset_id: str, record: str, root: Path | None = None) -> tuple[Recording, bool]:
    """Import one record; returns (recording, created). Idempotent on (dataset, name)."""
    adapter = get_adapter(dataset_id)
    existing = s.scalar(select(Recording).where(Recording.dataset_id == dataset_id, Recording.name == record))
    if existing is not None:
        return existing, False
    root = root or get_settings().physionet_dir / dataset_id
    parsed = adapter.parse(root, record)
    files = {}
    for rel, _required in adapter.record_files(record):
        p = root / rel
        if p.exists():
            files[rel] = sha256(p)
    return register_parsed(s, adapter, parsed, files), True


def import_available(s: Session, dataset_ids: list[str] | None = None, limit: int | None = None) -> dict:
    """Import all locally available records of the given datasets."""
    settings = get_settings()
    report: dict = {}
    for ds_id in dataset_ids or list(ADAPTERS):
        adapter = ADAPTERS[ds_id]
        root = settings.physionet_dir / ds_id
        names = adapter.available_records(root)
        if limit is not None:
            preferred = [r for r in BUNDLED_RECORDS.get(ds_id, []) if r in names]
            names = (preferred + [r for r in names if r not in preferred])[:limit]
        done, skipped, failed = [], [], {}
        for r in names:
            try:
                with s.begin_nested():
                    _, created = import_record(s, ds_id, r, root)
                (done if created else skipped).append(r)
            except Exception as e:  # keep importing other records
                failed[r] = repr(e)
                log.exception("Import of %s/%s failed", ds_id, r)
        report[ds_id] = {"imported": done, "already_present": skipped, "failed": failed}
    return report


def import_npz(s: Session, name: str, raw: bytes) -> Recording:
    """Register a user-provided NPZ (signal [samples, leads] in mV, fs, leads)."""
    import io

    from fastapi import HTTPException

    try:
        with np.load(io.BytesIO(raw), allow_pickle=False) as d:
            signal = np.asarray(d["signal"], dtype=np.float32)
            fs = float(d["fs"])
            leads = [str(v) for v in d["leads"]]
            units = [str(v) for v in d["units"]] if "units" in d else ["mV"] * len(leads)
    except Exception as e:
        raise HTTPException(422, f"Invalid NPZ: {e}") from e
    if signal.ndim != 2 or signal.shape[0] < 2 or signal.shape[1] != len(leads) or not 0 < fs <= 20000:
        raise HTTPException(422, "Invalid signal shape, sampling frequency or lead list")
    if not np.isfinite(signal).all():
        raise HTTPException(422, "Signal contains NaN/Inf")
    from ..datasets.base import UNIT_TO_MV

    for i, u in enumerate(units):
        if u not in UNIT_TO_MV:
            raise HTTPException(422, f"Unsupported unit {u}")
        signal[:, i] *= UNIT_TO_MV[u]
    ensure_upload_dataset(s)
    rec_id = str(uuid.uuid4())
    rel_path, digest = save_signal(rec_id, signal)
    rec = Recording(id=rec_id, dataset_id="uploads", name=f"{name}-{rec_id[:8]}", fs=fs, n_samples=int(signal.shape[0]),
                    leads=leads, units=["mV"] * len(leads), original_units=units, gains=[], patient_id=None,
                    meta={"duration_s": signal.shape[0] / fs}, signal_path=rel_path, signal_sha256=digest,
                    source="upload", source_files={})
    s.add(rec)
    s.flush()
    return rec
