"""Dataset snapshots (export) and round-trip import."""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import DatasetSnapshot
from ..schemas import SnapshotRequest
from ..services.annotations import ann_out, api_error, get_recording, list_annotations
from ..services.exporter import create_snapshot, import_bundle, verify_snapshot

router = APIRouter(tags=["export"])


def snap_out(s: DatasetSnapshot) -> dict:
    m = s.manifest or {}
    return {"id": s.id, "version": s.version, "name": s.name, "ontology_version": s.ontology_version,
            "created_at": s.created_at.isoformat(), "archive_sha256": s.archive_sha256,
            "recordings": m.get("recordings", []), "label_statistics": m.get("label_statistics", {}),
            "splits": m.get("splits", {}), "download_url": f"/exports/{s.version}/download"}


@router.post("/exports", status_code=201)
def create(body: SnapshotRequest, db: Session = Depends(get_db)):
    return snap_out(create_snapshot(db, body))


@router.get("/exports")
def list_exports(db: Session = Depends(get_db)):
    return [snap_out(s) for s in db.scalars(select(DatasetSnapshot).order_by(DatasetSnapshot.created_at.desc()))]


def _snap(db: Session, version: str) -> DatasetSnapshot:
    s = db.scalar(select(DatasetSnapshot).where(DatasetSnapshot.version == version))
    if s is None:
        raise api_error(404, "not_found", f"Snapshot {version} not found")
    return s


@router.get("/exports/{version}")
def get_export(version: str, db: Session = Depends(get_db)):
    return snap_out(_snap(db, version))


@router.get("/exports/{version}/download")
def download(version: str, db: Session = Depends(get_db)):
    s = _snap(db, version)
    path = get_settings().data_dir / s.archive_path
    if not path.exists():
        raise api_error(410, "gone", "Archive file missing on disk")
    return FileResponse(path, media_type="application/zip", filename=f"{s.version}.zip")


@router.get("/exports/{version}/verify")
def verify(version: str, db: Session = Depends(get_db)):
    return verify_snapshot(db, _snap(db, version))


@router.post("/imports")
async def import_snapshot(file: UploadFile = File(...), mode: str = Query("new_recording", pattern="^(verify|new_recording)$"),
                          db: Session = Depends(get_db)):
    raw = await file.read()
    return import_bundle(db, raw, file.filename or "upload", mode)


@router.get("/recordings/{recording_id}/export")
def quick_export(recording_id: str, format: str = "json", db: Session = Depends(get_db)):
    """Quick single-recording export (not versioned; use POST /exports for snapshots)."""
    rec = get_recording(db, recording_id)
    anns = [ann_out(a) for a in list_annotations(db, rec.id)]
    if format == "json":
        content = json.dumps({"recording": {"id": rec.id, "name": rec.name, "dataset_id": rec.dataset_id, "fs": rec.fs,
                                            "n_samples": rec.n_samples, "leads": rec.leads},
                              "annotations": anns, "interval_convention": "[start_sample, end_sample)"}, indent=1)
        return StreamingResponse(iter([content]), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="{rec.name}.json"'})
    if format == "csv":
        buf = io.StringIO()
        fields = ["id", "tier", "label", "lead", "kind", "start_sample", "end_sample", "source", "review_status", "revision"]
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for a in anns:
            w.writerow({k: a.get(k) for k in fields})
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{rec.name}.csv"'})
    raise api_error(422, "invalid_format", "Supported formats: json, csv")
