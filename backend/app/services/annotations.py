"""Annotation business logic: validation, batch transactions, history."""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Iterable

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Annotation, AnnotationRevision, Recording, utcnow
from ..ontology import OntologyCache
from ..schemas import AnnotationCreate, AnnotationOut, AnnotationUpdate, BatchOp

# Annotation fields that clients may set
EDITABLE = ("tier", "label", "lead", "start_sample", "end_sample", "attributes", "review_status", "beat_id", "confidence")
NO_BEAT_TIERS = {"Rhythm", "Interpretation", "Signal Quality", "Beat"}


def api_error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def ann_out(a: Annotation) -> dict:
    return AnnotationOut.model_validate(a).model_dump(mode="json")


def get_recording(s: Session, recording_id: str) -> Recording:
    rec = s.get(Recording, recording_id)
    if rec is None:
        raise api_error(404, "not_found", "Recording not found")
    return rec


def list_annotations(s: Session, recording_id: str, *, start: int | None = None, end: int | None = None,
                     include_deleted: bool = False) -> list[Annotation]:
    q = select(Annotation).where(Annotation.recording_id == recording_id)
    if not include_deleted:
        q = q.where(Annotation.deleted.is_(False))
    if end is not None:
        q = q.where(Annotation.start_sample < end)
    rows = list(s.scalars(q.order_by(Annotation.start_sample, Annotation.id)))
    if start is not None:
        rows = [a for a in rows if (a.end_sample if a.end_sample is not None else a.start_sample + 1) > start]
    return rows


def record_revision(s: Session, a: Annotation, operation: str, batch_id: str | None, actor: str = "local-user") -> None:
    s.add(AnnotationRevision(annotation_id=a.id, recording_id=a.recording_id, revision=a.revision,
                             operation=operation, snapshot=ann_out(a), actor=actor, batch_id=batch_id))


def check_geometry(rec: Recording, lead: str | None, start: int, end: int | None) -> None:
    if lead is not None and lead not in rec.leads:
        raise api_error(422, "invalid_lead", f"Unknown lead '{lead}' (recording leads: {', '.join(rec.leads)})")
    if start < 0 or start >= rec.n_samples:
        raise api_error(422, "out_of_bounds", f"start_sample {start} outside [0, {rec.n_samples})")
    if end is not None and (end <= start or end > rec.n_samples):
        raise api_error(422, "out_of_bounds", f"end_sample {end} must satisfy start < end <= {rec.n_samples}")


def _auto_beat_id(s: Session, rec_id: str, a: Annotation) -> str | None:
    if a.tier in NO_BEAT_TIERS:
        return None
    beats = s.scalars(select(Annotation).where(
        Annotation.recording_id == rec_id, Annotation.tier == "Beat", Annotation.kind == "interval",
        Annotation.deleted.is_(False), Annotation.start_sample <= a.start_sample,
        Annotation.end_sample > a.start_sample))
    for b in beats:
        if b.lead is None or b.lead == a.lead:
            return b.beat_id or b.id
    return None


def _validate(onto: OntologyCache, tier: str, label: str, kind: str, attributes: dict) -> None:
    errors = onto.validate(tier, label, kind, attributes)
    if errors:
        raise api_error(422, "ontology_violation", "; ".join(errors), errors=errors)


def check_overlaps(s: Session, onto: OntologyCache, rec_id: str, groups: Iterable[tuple[str, str | None]],
                   touched: set[str]) -> None:
    """Enforce tier overlap policies on the final state, for pairs involving touched annotations."""
    for tier_name, lead in groups:
        tier = onto.tiers.get(tier_name)
        q = select(Annotation).where(Annotation.recording_id == rec_id, Annotation.tier == tier_name,
                                     Annotation.deleted.is_(False))
        q = q.where(Annotation.lead.is_(None)) if lead is None else q.where(Annotation.lead == lead)
        rows = list(s.scalars(q.order_by(Annotation.start_sample)))
        # duplicate points (same label & sample) are always rejected
        seen: dict[tuple[str, int], str] = {}
        for a in rows:
            if a.kind == "point":
                key = (a.label, a.start_sample)
                if key in seen and (a.id in touched or seen[key] in touched):
                    raise api_error(409, "duplicate_point",
                                    f"Duplicate {a.label} point at sample {a.start_sample} on tier '{tier_name}'",
                                    annotation_ids=[seen[key], a.id])
                seen[key] = a.id
        if tier is None or tier.overlap_policy == "allow":
            continue
        intervals = [a for a in rows if a.kind == "interval"]
        buckets: dict[str, list[Annotation]] = defaultdict(list)
        for a in intervals:
            buckets[a.label if tier.overlap_policy == "forbid_same_label" else ""].append(a)
        for items in buckets.values():
            active: list[Annotation] = []
            for a in items:  # sorted by start
                active = [b for b in active if b.end_sample > a.start_sample]
                for b in active:
                    if a.id in touched or b.id in touched:
                        raise api_error(409, "overlap_violation",
                                        f"'{a.label}' [{a.start_sample},{a.end_sample}) overlaps '{b.label}' "
                                        f"[{b.start_sample},{b.end_sample}) on tier '{tier_name}' "
                                        f"(policy {tier.overlap_policy}, lead {lead or 'global'})",
                                        annotation_ids=[b.id, a.id])
                active.append(a)


def apply_batch(s: Session, rec: Recording, ops: list[BatchOp], actor: str = "local-user") -> dict:
    """Apply create/update/delete operations atomically (caller's transaction)."""
    onto = OntologyCache.load(s)
    batch_id = str(uuid.uuid4())
    created: list[Annotation] = []
    updated: list[Annotation] = []
    deleted: list[str] = []
    id_map: dict[str, str] = {}
    groups: set[tuple[str, str | None]] = set()
    touched: set[str] = set()

    for i, op in enumerate(ops):
        try:
            if op.op == "create":
                body = AnnotationCreate.model_validate({**(op.data or {}), "client_id": op.client_id})
                a = create_annotation(s, rec, onto, body, batch_id, actor)
                created.append(a)
                if op.client_id:
                    id_map[op.client_id] = a.id
                groups.add((a.tier, a.lead))
                touched.add(a.id)
            elif op.op == "update":
                if not op.id or op.revision is None:
                    raise api_error(422, "invalid_op", "update requires id and revision")
                body = AnnotationUpdate.model_validate({**(op.data or {}), "revision": op.revision,
                                                        "confirm_reviewed_change": op.confirm_reviewed_change})
                a = s.get(Annotation, op.id)
                if a is not None:
                    groups.add((a.tier, a.lead))
                a = update_annotation(s, rec, onto, op.id, body, batch_id, actor)
                updated.append(a)
                groups.add((a.tier, a.lead))
                touched.add(a.id)
            elif op.op == "delete":
                if not op.id or op.revision is None:
                    raise api_error(422, "invalid_op", "delete requires id and revision")
                delete_annotation(s, rec, op.id, op.revision, op.confirm_reviewed_change, batch_id, actor)
                deleted.append(op.id)
        except ValidationError as e:
            raise api_error(422, "invalid_op", f"Operation {i}: {e.errors()[0]['msg']}", op_index=i)
        except HTTPException as e:
            if isinstance(e.detail, dict):
                e.detail.setdefault("op_index", i)
            raise
    s.flush()
    check_overlaps(s, onto, rec.id, groups, touched)
    return {
        "batch_id": batch_id,
        "created": [ann_out(a) for a in created],
        "updated": [ann_out(a) for a in updated],
        "deleted": deleted,
        "id_map": id_map,
    }


def create_annotation(s: Session, rec: Recording, onto: OntologyCache, body: AnnotationCreate,
                      batch_id: str | None, actor: str = "local-user") -> Annotation:
    check_geometry(rec, body.lead, body.start_sample, body.end_sample)
    _validate(onto, body.tier, body.label, body.kind, body.attributes)
    a = Annotation(
        id=str(uuid.uuid4()), recording_id=rec.id, tier=body.tier, label=body.label, lead=body.lead,
        kind=body.kind, start_sample=body.start_sample, end_sample=body.end_sample,
        attributes=dict(body.attributes), source=body.source, provenance=dict(body.provenance),
        review_status=body.review_status, confidence=body.confidence, beat_id=body.beat_id,
        ontology_version=onto.version, revision=1,
    )
    s.add(a)
    s.flush()
    if a.beat_id is None:
        a.beat_id = a.id if (a.tier == "Beat" and a.kind == "interval") else _auto_beat_id(s, rec.id, a)
    record_revision(s, a, "create", batch_id, actor)
    return a


def _load_live(s: Session, rec: Recording, ann_id: str) -> Annotation:
    a = s.get(Annotation, ann_id)
    if a is None or a.deleted or a.recording_id != rec.id:
        raise api_error(404, "not_found", f"Annotation {ann_id} not found")
    return a


def update_annotation(s: Session, rec: Recording, onto: OntologyCache, ann_id: str, body: AnnotationUpdate,
                      batch_id: str | None, actor: str = "local-user") -> Annotation:
    a = _load_live(s, rec, ann_id)
    if a.revision != body.revision:
        raise api_error(409, "revision_conflict",
                        f"Annotation {ann_id} is at revision {a.revision}, request was based on {body.revision}",
                        annotation_id=ann_id, current=ann_out(a))
    new = body.model_dump(include=set(EDITABLE))
    new["kind"] = body.kind
    changed = {k: v for k, v in new.items() if getattr(a, k) != v}
    if not changed:
        return a
    if a.review_status == "reviewed" and not body.confirm_reviewed_change:
        raise api_error(409, "reviewed_protected",
                        f"Annotation {ann_id} is expert-reviewed; resend with confirm_reviewed_change=true",
                        annotation_id=ann_id)
    check_geometry(rec, body.lead, body.start_sample, body.end_sample)
    _validate(onto, body.tier, body.label, body.kind, body.attributes)
    for k, v in changed.items():
        setattr(a, k, v)
    a.ontology_version = onto.version
    a.revision += 1
    a.updated_at = utcnow()
    s.flush()
    record_revision(s, a, "update", batch_id, actor)
    return a


def delete_annotation(s: Session, rec: Recording, ann_id: str, revision: int, confirm_reviewed: bool,
                      batch_id: str | None, actor: str = "local-user") -> None:
    """Soft delete: the row is kept (deleted=True) and a revision snapshot is written."""
    a = _load_live(s, rec, ann_id)
    if a.revision != revision:
        raise api_error(409, "revision_conflict",
                        f"Annotation {ann_id} is at revision {a.revision}, request was based on {revision}",
                        annotation_id=ann_id, current=ann_out(a))
    if a.review_status == "reviewed" and not confirm_reviewed:
        raise api_error(409, "reviewed_protected",
                        f"Annotation {ann_id} is expert-reviewed; resend with confirm_reviewed_change=true",
                        annotation_id=ann_id)
    a.deleted = True
    a.revision += 1
    a.updated_at = utcnow()
    s.flush()
    record_revision(s, a, "delete", batch_id, actor)


def validate_recording(s: Session, rec: Recording) -> list[dict]:
    """Soft constraint checks (warnings): parent/child containment and wave ordering."""
    onto = OntologyCache.load(s)
    anns = list_annotations(s, rec.id)
    issues: list[dict] = []
    intervals_by_label: dict[str, list[Annotation]] = defaultdict(list)
    for a in anns:
        if a.kind == "interval":
            intervals_by_label[a.label].append(a)
    for a in anns:
        errs = onto.validate(a.tier, a.label, a.kind, a.attributes or {})
        for e in errs:
            issues.append({"severity": "error", "annotation_id": a.id, "message": e})
        lb = onto.labels.get(a.label)
        if a.kind == "point" and lb is not None and lb.parent_code:
            parents = intervals_by_label.get(lb.parent_code, [])
            if parents and not any(p.start_sample <= a.start_sample < p.end_sample and
                                   (p.lead is None or a.lead is None or p.lead == a.lead) for p in parents):
                issues.append({"severity": "warning", "annotation_id": a.id,
                               "message": f"{a.label} at {a.start_sample} is outside any {lb.parent_code} interval"})
    return issues
