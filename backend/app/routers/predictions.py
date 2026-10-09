"""Automatic pre-annotation and prediction review."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Prediction, PredictionRun
from ..ontology import OntologyCache
from ..schemas import AcceptRange, DelineateRequest, DetectRequest, PredictionAccept
from ..services.annotations import ann_out, api_error, get_recording
from ..services.predictions import accept_prediction, reject_prediction, run_delineation, run_rpeak, run_segmentation

router = APIRouter(tags=["predictions"])


def pred_out(p: Prediction) -> dict:
    return {"id": p.id, "run_id": p.run_id, "recording_id": p.recording_id, "tier": p.tier, "label": p.label,
            "lead": p.lead, "kind": p.kind, "start_sample": p.start_sample, "end_sample": p.end_sample,
            "confidence": p.confidence, "attributes": p.attributes, "status": p.status, "annotation_id": p.annotation_id}


def run_out(r: PredictionRun, with_predictions: bool = False) -> dict:
    counts: dict[str, int] = {}
    for p in r.predictions:
        counts[p.status] = counts.get(p.status, 0) + 1
    d = {"id": r.id, "recording_id": r.recording_id, "algorithm": r.algorithm, "algorithm_version": r.algorithm_version,
         "parameters": r.parameters, "lead": r.lead, "start_sample": r.start_sample, "end_sample": r.end_sample,
         "experimental": r.experimental, "created_at": r.created_at.isoformat(), "counts": counts,
         "n_predictions": len(r.predictions)}
    if with_predictions:
        d["predictions"] = [pred_out(p) for p in sorted(r.predictions, key=lambda p: p.start_sample)]
    return d


@router.post("/recordings/{recording_id}/detect-r")
def detect_r(recording_id: str, body: DetectRequest | None = None, db: Session = Depends(get_db)):
    rec = get_recording(db, recording_id)
    body = body or DetectRequest()
    run = run_rpeak(db, rec, body.lead, body.start_sample, body.end_sample, body.algorithm)
    db.refresh(run)
    return run_out(run, True)


class SegmentBody(BaseModel):
    source_run_id: Optional[str] = None
    lead: Optional[str] = None


@router.post("/recordings/{recording_id}/segment-beats")
def segment(recording_id: str, body: SegmentBody, db: Session = Depends(get_db)):
    rec = get_recording(db, recording_id)
    run = run_segmentation(db, rec, body.source_run_id, body.lead)
    db.refresh(run)
    return run_out(run, True)


@router.post("/recordings/{recording_id}/delineate")
def delineate(recording_id: str, body: DelineateRequest, db: Session = Depends(get_db)):
    rec = get_recording(db, recording_id)
    run = run_delineation(db, rec, body.lead, body.start_sample, body.end_sample)
    db.refresh(run)
    return run_out(run, True)


@router.get("/recordings/{recording_id}/prediction-runs")
def list_runs(recording_id: str, db: Session = Depends(get_db)):
    get_recording(db, recording_id)
    runs = db.scalars(select(PredictionRun).where(PredictionRun.recording_id == recording_id)
                      .order_by(PredictionRun.created_at))
    return [run_out(r, True) for r in runs]


@router.delete("/prediction-runs/{run_id}")
def delete_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(PredictionRun, run_id)
    if run is None:
        raise api_error(404, "not_found", "Run not found")
    db.delete(run)  # accepted annotations stay; they carry provenance
    return {"deleted": run_id}


def _pred(db: Session, pred_id: str) -> Prediction:
    p = db.get(Prediction, pred_id)
    if p is None:
        raise api_error(404, "not_found", "Prediction not found")
    return p


@router.post("/predictions/{pred_id}/accept")
def accept(pred_id: str, body: PredictionAccept | None = None, db: Session = Depends(get_db)):
    p = _pred(db, pred_id)
    a = accept_prediction(db, p, body or PredictionAccept())
    return {"prediction": pred_out(p), "annotation": ann_out(a)}


@router.post("/predictions/{pred_id}/reject")
def reject(pred_id: str, db: Session = Depends(get_db)):
    p = _pred(db, pred_id)
    reject_prediction(p)
    return pred_out(p)


@router.post("/prediction-runs/{run_id}/accept-range")
def accept_range(run_id: str, body: AcceptRange, db: Session = Depends(get_db)):
    """Accept every pending prediction starting inside [start, end); conflicts are skipped and reported."""
    run = db.get(PredictionRun, run_id)
    if run is None:
        raise api_error(404, "not_found", "Run not found")
    onto = OntologyCache.load(db)
    accepted, skipped = [], []
    for p in sorted(run.predictions, key=lambda p: p.start_sample):
        if p.status != "pending" or not (body.start_sample <= p.start_sample < body.end_sample):
            continue
        try:
            with db.begin_nested():
                a = accept_prediction(db, p, PredictionAccept(review_status=body.review_status), onto)
            accepted.append(ann_out(a))
        except HTTPException as e:
            skipped.append({"prediction_id": p.id, "reason": e.detail})
    return {"accepted": accepted, "skipped": skipped}
