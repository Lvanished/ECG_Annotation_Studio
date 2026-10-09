"""Annotation CRUD, batch transactions, history and relationships."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Annotation, AnnotationRelationship, AnnotationRevision
from ..ontology import RELATION_LEVEL, OntologyCache
from ..schemas import AnnotationCreate, AnnotationUpdate, BatchOp, BatchRequest, RelationshipIn
from ..services.annotations import (
    ann_out,
    api_error,
    apply_batch,
    get_recording,
    list_annotations,
)

router = APIRouter(tags=["annotations"])


@router.get("/recordings/{recording_id}/annotations")
def get_annotations(recording_id: str, start: Optional[int] = Query(None, ge=0), end: Optional[int] = Query(None, ge=0),
                    tier: Optional[str] = None, source: Optional[str] = None, include_deleted: bool = False,
                    db: Session = Depends(get_db)):
    get_recording(db, recording_id)
    rows = list_annotations(db, recording_id, start=start, end=end, include_deleted=include_deleted)
    if tier:
        rows = [a for a in rows if a.tier == tier]
    if source:
        rows = [a for a in rows if a.source == source]
    return [ann_out(a) for a in rows]


@router.post("/recordings/{recording_id}/annotations", status_code=201)
def create_one(recording_id: str, body: AnnotationCreate, db: Session = Depends(get_db)):
    rec = get_recording(db, recording_id)
    res = apply_batch(db, rec, [BatchOp(op="create", data=body.model_dump(exclude={"client_id"}), client_id=body.client_id)])
    return res["created"][0]


@router.post("/recordings/{recording_id}/annotations/batch")
def batch(recording_id: str, body: BatchRequest, db: Session = Depends(get_db)):
    """All operations succeed or none are applied (single DB transaction)."""
    rec = get_recording(db, recording_id)
    return apply_batch(db, rec, body.operations)


def _rec_of(db: Session, ann_id: str):
    a = db.get(Annotation, ann_id)
    if a is None:
        raise api_error(404, "not_found", "Annotation not found")
    return get_recording(db, a.recording_id)


@router.put("/annotations/{ann_id}")
def update_one(ann_id: str, body: AnnotationUpdate, db: Session = Depends(get_db)):
    rec = _rec_of(db, ann_id)
    data = body.model_dump(exclude={"revision", "confirm_reviewed_change"})
    res = apply_batch(db, rec, [BatchOp(op="update", id=ann_id, revision=body.revision, data=data,
                                        confirm_reviewed_change=body.confirm_reviewed_change)])
    return res["updated"][0]


@router.delete("/annotations/{ann_id}")
def delete_one(ann_id: str, revision: int, confirm_reviewed_change: bool = False, db: Session = Depends(get_db)):
    rec = _rec_of(db, ann_id)
    apply_batch(db, rec, [BatchOp(op="delete", id=ann_id, revision=revision,
                                  confirm_reviewed_change=confirm_reviewed_change)])
    return {"deleted": ann_id}


@router.get("/annotations/{ann_id}/history")
def history(ann_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(AnnotationRevision).where(AnnotationRevision.annotation_id == ann_id)
                      .order_by(AnnotationRevision.revision, AnnotationRevision.timestamp))
    out = [{"revision": h.revision, "operation": h.operation, "timestamp": h.timestamp.isoformat(), "actor": h.actor,
            "batch_id": h.batch_id, "snapshot": h.snapshot} for h in rows]
    if not out:
        raise api_error(404, "not_found", "No history for this annotation")
    return out


@router.get("/recordings/{recording_id}/history")
def recording_history(recording_id: str, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    get_recording(db, recording_id)
    rows = db.scalars(select(AnnotationRevision).where(AnnotationRevision.recording_id == recording_id)
                      .order_by(AnnotationRevision.timestamp.desc()).limit(limit))
    return [{"annotation_id": h.annotation_id, "revision": h.revision, "operation": h.operation,
             "timestamp": h.timestamp.isoformat(), "actor": h.actor, "label": h.snapshot.get("label"),
             "start_sample": h.snapshot.get("start_sample"), "end_sample": h.snapshot.get("end_sample")} for h in rows]


@router.get("/recordings/{recording_id}/relationships")
def list_relationships(recording_id: str, db: Session = Depends(get_db)):
    get_recording(db, recording_id)
    return [{"id": r.id, "source_id": r.source_id, "target_id": r.target_id, "relation_type": r.relation_type,
             "attributes": r.attributes}
            for r in db.scalars(select(AnnotationRelationship).where(AnnotationRelationship.recording_id == recording_id))]


@router.post("/recordings/{recording_id}/relationships", status_code=201)
def add_relationship(recording_id: str, body: RelationshipIn, db: Session = Depends(get_db)):
    get_recording(db, recording_id)
    onto = OntologyCache.load(db)
    lb = onto.labels.get(body.relation_type)
    if lb is None or lb.level != RELATION_LEVEL or lb.geometry != "relation":
        raise api_error(422, "ontology_violation", f"'{body.relation_type}' is not an L6 relationship type")
    for aid in (body.source_id, body.target_id):
        a = db.get(Annotation, aid)
        if a is None or a.deleted or a.recording_id != recording_id:
            raise api_error(422, "invalid_reference", f"Annotation {aid} not found in this recording")
    if body.source_id == body.target_id:
        raise api_error(422, "invalid_reference", "Relationship requires two different annotations")
    r = AnnotationRelationship(recording_id=recording_id, source_id=body.source_id, target_id=body.target_id,
                               relation_type=body.relation_type, attributes=body.attributes)
    db.add(r)
    db.flush()
    return {"id": r.id, "source_id": r.source_id, "target_id": r.target_id, "relation_type": r.relation_type,
            "attributes": r.attributes}


@router.delete("/relationships/{rel_id}")
def delete_relationship(rel_id: str, db: Session = Depends(get_db)):
    r = db.get(AnnotationRelationship, rel_id)
    if r is None:
        raise api_error(404, "not_found", "Relationship not found")
    db.delete(r)
    return {"deleted": rel_id}
