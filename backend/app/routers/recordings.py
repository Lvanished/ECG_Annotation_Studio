"""Datasets, recordings, waveform access, quality and measurements."""
from __future__ import annotations

from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..datasets import ADAPTERS, BUNDLED_RECORDS, get_adapter
from ..datasets.download import download
from ..db import get_db
from ..models import Annotation, Dataset, Recording
from ..schemas import MeasurementRequest, RecordingOut
from ..services.annotations import api_error, get_recording, list_annotations, validate_recording
from ..services.importer import import_available, import_npz
from ..signal.measurements import compute_measurements
from ..signal.quality import quality_indicators
from ..storage import envelope, load_signal

router = APIRouter(tags=["recordings"])

CHUNK_BUCKETS = 1024


def rec_out(rec: Recording, count: int = 0) -> dict:
    d = RecordingOut.model_validate(rec).model_dump()
    d["duration_s"] = rec.n_samples / rec.fs
    d["annotation_count"] = count
    return d


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db)):
    settings = get_settings()
    counts = dict(db.execute(select(Recording.dataset_id, func.count()).group_by(Recording.dataset_id)).all())
    out = []
    known = {d.id: d for d in db.scalars(select(Dataset))}
    for ds_id, adapter in ADAPTERS.items():
        d = known.get(ds_id)
        out.append({
            "id": ds_id, "name": adapter.name, "version": adapter.version, "license": adapter.license,
            "source_url": adapter.page_url, "citation": adapter.citation, "description": adapter.description,
            "annotation_semantics": adapter.annotation_semantics, "registered": d is not None,
            "recording_count": counts.get(ds_id, 0),
            "local_records": adapter.available_records(settings.physionet_dir / ds_id),
            "bundled_records": BUNDLED_RECORDS.get(ds_id, []),
        })
    for ds_id, d in known.items():
        if ds_id not in ADAPTERS:
            out.append({"id": ds_id, "name": d.name, "version": d.version, "license": d.license,
                        "source_url": d.source_url, "citation": d.citation, "description": d.description,
                        "annotation_semantics": d.annotation_semantics, "registered": True,
                        "recording_count": counts.get(ds_id, 0), "local_records": [], "bundled_records": []})
    return out


class ImportBody(BaseModel):
    records: Optional[list[str]] = None
    limit: Optional[int] = None


@router.post("/datasets/{dataset_id}/import")
def import_dataset(dataset_id: str, body: ImportBody | None = None, db: Session = Depends(get_db)):
    if dataset_id not in ADAPTERS:
        raise api_error(404, "not_found", f"Unknown dataset {dataset_id}")
    body = body or ImportBody()
    if body.records:
        from ..services.importer import import_record

        report = {"imported": [], "already_present": [], "failed": {}}
        for r in body.records:
            try:
                with db.begin_nested():
                    _, created = import_record(db, dataset_id, r)
                (report["imported"] if created else report["already_present"]).append(r)
            except Exception as e:
                report["failed"][r] = repr(e)
        return {dataset_id: report}
    return import_available(db, [dataset_id], body.limit)


@router.post("/datasets/{dataset_id}/download")
def download_dataset(dataset_id: str, body: ImportBody):
    """Download records from PhysioNet (network required); files are SHA-256 verified."""
    adapter = get_adapter(dataset_id)
    records = body.records or BUNDLED_RECORDS.get(dataset_id, [])
    if len(records) > 50:
        raise HTTPException(422, "Download at most 50 records per request; use scripts/download_datasets.py for bulk")
    m = download(adapter, records, get_settings().physionet_dir / dataset_id)
    return {"downloaded": list(m["records"]), "failures": m["failures"]}


@router.get("/recordings")
def list_recordings(dataset_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = select(Recording)
    if dataset_id:
        q = q.where(Recording.dataset_id == dataset_id)
    recs = list(db.scalars(q))
    counts = dict(db.execute(select(Annotation.recording_id, func.count()).where(Annotation.deleted.is_(False))
                             .group_by(Annotation.recording_id)).all())
    recs.sort(key=lambda r: (r.dataset_id or "", len(r.name), r.name))
    return [rec_out(r, counts.get(r.id, 0)) for r in recs]


@router.get("/recordings/{recording_id}")
def get_recording_detail(recording_id: str, db: Session = Depends(get_db)):
    rec = get_recording(db, recording_id)
    n = db.scalar(select(func.count()).select_from(Annotation).where(
        Annotation.recording_id == rec.id, Annotation.deleted.is_(False))) or 0
    return rec_out(rec, n)


@router.post("/recordings/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".npz"):
        raise HTTPException(415, "Upload an .npz containing signal [samples, leads] (mV), fs and leads")
    raw = await file.read()
    if len(raw) > get_settings().max_upload_bytes:
        raise HTTPException(413, "File too large")
    stem = (file.filename or "upload").rsplit(".", 1)[0]
    rec = import_npz(db, stem, raw)
    return rec_out(rec)


def _leads(rec: Recording, leads: Optional[str]) -> list[str]:
    names = [x for x in (leads or "").split(",") if x] or list(rec.leads)
    bad = [x for x in names if x not in rec.leads]
    if bad:
        raise api_error(422, "invalid_lead", f"Unknown lead(s): {', '.join(bad)}")
    return names


@router.get("/recordings/{recording_id}/chunk")
def chunk(recording_id: str, bucket: int = Query(1, ge=1, le=1 << 20), index: int = Query(0, ge=0),
          leads: Optional[str] = None, db: Session = Depends(get_db)):
    """Level-of-detail chunk: ``CHUNK_BUCKETS`` buckets of ``bucket`` samples each.

    Chunk ``index`` covers samples ``[index*1024*bucket, (index+1)*1024*bucket)``.
    ``bucket == 1`` returns raw samples (``values``); otherwise per-bucket
    ``min``/``max`` envelopes so narrow extrema (QRS) are never dropped.
    """
    rec = get_recording(db, recording_id)
    names = _leads(rec, leads)
    span = CHUNK_BUCKETS * bucket
    start = index * span
    if start >= rec.n_samples:
        raise api_error(422, "out_of_bounds", "Chunk beyond end of recording")
    stop = min(rec.n_samples, start + span)
    sig = load_signal(rec.signal_path)
    out: dict = {"start": start, "end": stop, "bucket": bucket, "index": index, "fs": rec.fs, "leads": {}}
    for name in names:
        col = np.asarray(sig[start:stop, rec.leads.index(name)], dtype=np.float32)
        if bucket == 1:
            out["leads"][name] = {"values": np.round(col, 5).tolist()}
        else:
            mn, mx = envelope(col, bucket)
            out["leads"][name] = {"min": np.round(mn, 5).tolist(), "max": np.round(mx, 5).tolist()}
    return out


@router.get("/recordings/{recording_id}/samples")
def samples(recording_id: str, start: int = Query(0, ge=0), end: Optional[int] = None, leads: Optional[str] = None,
            db: Session = Depends(get_db)):
    """Raw samples (mV) for an explicit window, max 200k samples."""
    rec = get_recording(db, recording_id)
    names = _leads(rec, leads)
    stop = min(rec.n_samples, end if end is not None else start + int(rec.fs * 10))
    if stop <= start or stop - start > 200_000:
        raise api_error(422, "invalid_window", "Window must be non-empty and at most 200000 samples")
    sig = load_signal(rec.signal_path)
    return {"start": start, "end": stop, "fs": rec.fs,
            "leads": {n: np.asarray(sig[start:stop, rec.leads.index(n)], dtype=np.float32).astype(float).tolist()
                      for n in names}}


@router.get("/recordings/{recording_id}/waveform")
def waveform(recording_id: str, start: int = Query(0, ge=0), end: Optional[int] = None, lead: str = "II",
             max_points: int = Query(6000, ge=100, le=100000), db: Session = Depends(get_db)):
    """Backward-compatible single-lead window (min/max envelope when decimated)."""
    rec = get_recording(db, recording_id)
    if lead not in rec.leads:
        raise api_error(422, "invalid_lead", "Unknown lead")
    stop = min(end if end is not None else start + int(rec.fs * 10), rec.n_samples)
    if stop <= start:
        raise api_error(422, "invalid_window", "Invalid window")
    col = np.asarray(load_signal(rec.signal_path)[start:stop, rec.leads.index(lead)], dtype=np.float32)
    step = max(1, int(np.ceil(len(col) / max_points)))
    if step == 1:
        return {"start": start, "end": stop, "step": 1, "fs": rec.fs, "lead": lead,
                "indices": list(range(start, stop)), "values": col.astype(float).tolist(), "decimated": False}
    mn, mx = envelope(col, step)
    return {"start": start, "end": stop, "step": step, "fs": rec.fs, "lead": lead,
            "indices": list(range(start, stop, step)), "min": mn.astype(float).tolist(), "max": mx.astype(float).tolist(),
            "values": ((mn + mx) / 2).astype(float).tolist(), "decimated": True}


@router.get("/recordings/{recording_id}/quality")
def quality(recording_id: str, start: int = Query(0, ge=0), end: Optional[int] = None, leads: Optional[str] = None,
            db: Session = Depends(get_db)):
    rec = get_recording(db, recording_id)
    names = _leads(rec, leads)
    stop = min(rec.n_samples, end if end is not None else rec.n_samples)
    if stop - start > int(rec.fs * 600):
        stop = start + int(rec.fs * 600)
    sig = load_signal(rec.signal_path)
    return {"start": start, "end": stop, "leads": {
        n: quality_indicators(np.asarray(sig[start:stop, rec.leads.index(n)]), rec.fs) for n in names}}


@router.post("/recordings/{recording_id}/measurements")
def measurements(recording_id: str, body: MeasurementRequest, db: Session = Depends(get_db)):
    rec = get_recording(db, recording_id)
    lead = body.lead
    if lead is not None and lead not in rec.leads:
        raise api_error(422, "invalid_lead", "Unknown lead")
    end = body.end_sample if body.end_sample is not None else rec.n_samples
    margin = int(rec.fs * 3)
    if body.annotations is not None:
        anns = body.annotations
    else:
        anns = list_annotations(db, rec.id, start=max(0, body.start_sample - margin), end=end + margin)
    sig = load_signal(rec.signal_path)
    li = rec.leads.index(lead) if lead else None
    return compute_measurements(anns, sig, rec.fs, lead, li, window=(body.start_sample, end))


@router.get("/recordings/{recording_id}/validate")
def validate(recording_id: str, db: Session = Depends(get_db)):
    rec = get_recording(db, recording_id)
    issues = validate_recording(db, rec)
    return {"recording_id": rec.id, "issues": issues[:500], "n_issues": len(issues)}
