"""Ontology and tier configuration."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Annotation, OntologyLabel, Tier
from ..ontology import MORPHOLOGY_VALUES, OntologyCache, bump_version, get_version
from ..schemas import LabelIn, LabelOut, TierIn, TierOut
from ..services.annotations import api_error

router = APIRouter(tags=["ontology"])


@router.get("/ontology")
def ontology(db: Session = Depends(get_db)):
    tiers = db.scalars(select(Tier).order_by(Tier.order))
    labels = db.scalars(select(OntologyLabel).order_by(OntologyLabel.level, OntologyLabel.code))
    return {"version": get_version(db), "morphology_values": MORPHOLOGY_VALUES,
            "tiers": [TierOut.model_validate(t).model_dump() for t in tiers],
            "labels": [LabelOut.model_validate(lb).model_dump() for lb in labels]}


@router.get("/tiers")
def tiers(db: Session = Depends(get_db)):
    return [TierOut.model_validate(t).model_dump() for t in db.scalars(select(Tier).order_by(Tier.order))]


@router.post("/tiers", status_code=201)
def create_tier(body: TierIn, db: Session = Depends(get_db)):
    if db.scalar(select(Tier).where(Tier.name == body.name)) is not None:
        raise api_error(409, "exists", f"Tier '{body.name}' already exists")
    order = (db.scalar(select(func.max(Tier.order))) or 0) + 1
    t = Tier(**body.model_dump(), order=order, is_custom=True)
    db.add(t)
    version = bump_version(db)
    db.flush()
    return {**TierOut.model_validate(t).model_dump(), "ontology_version": version}


class TierPatch(BaseModel):
    color: str | None = None
    order: int | None = None
    overlap_policy: str | None = None
    allow_free_labels: bool | None = None
    description: str | None = None


@router.patch("/tiers/{tier_id}")
def patch_tier(tier_id: str, body: TierPatch, db: Session = Depends(get_db)):
    t = db.get(Tier, tier_id)
    if t is None:
        raise api_error(404, "not_found", "Tier not found")
    data = body.model_dump(exclude_none=True)
    if "overlap_policy" in data and data["overlap_policy"] not in ("allow", "forbid_same_lead", "forbid_same_label"):
        raise api_error(422, "invalid", "Invalid overlap policy")
    for k, v in data.items():
        setattr(t, k, v)
    if {"overlap_policy", "allow_free_labels"} & data.keys():
        bump_version(db)
    db.flush()
    return TierOut.model_validate(t).model_dump()


@router.delete("/tiers/{tier_id}")
def delete_tier(tier_id: str, db: Session = Depends(get_db)):
    t = db.get(Tier, tier_id)
    if t is None:
        raise api_error(404, "not_found", "Tier not found")
    if not t.is_custom:
        raise api_error(409, "protected", "Default tiers cannot be deleted")
    used = db.scalar(select(func.count()).select_from(Annotation).where(Annotation.tier == t.name,
                                                                         Annotation.deleted.is_(False)))
    if used:
        raise api_error(409, "in_use", f"Tier has {used} annotations")
    db.delete(t)
    bump_version(db)
    return {"deleted": tier_id}


@router.post("/ontology/labels", status_code=201)
def create_label(body: LabelIn, db: Session = Depends(get_db)):
    onto = OntologyCache.load(db)
    if body.code in onto.labels:
        raise api_error(409, "exists", f"Label '{body.code}' already exists")
    if body.parent_code and body.parent_code not in onto.labels:
        raise api_error(422, "invalid_parent", f"Unknown parent label '{body.parent_code}'")
    unknown = [t for t in body.tiers if t not in onto.tiers]
    if unknown:
        raise api_error(422, "invalid_tier", f"Unknown tiers: {unknown}")
    for key, spec in body.attributes_schema.items():
        if not isinstance(spec, dict) or spec.get("type") not in ("enum", "string", "number", "boolean"):
            raise api_error(422, "invalid_schema", f"Attribute '{key}' needs type enum|string|number|boolean")
    version = bump_version(db)
    lb = OntologyLabel(**body.model_dump(), is_custom=True, added_in_version=version)
    db.add(lb)
    db.flush()
    return LabelOut.model_validate(lb).model_dump()
