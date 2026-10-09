"""Pydantic request/response schemas."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["point", "interval"]
ReviewStatus = Literal["draft", "needs_review", "reviewed", "rejected"]
Source = Literal["manual", "reference", "algorithm", "imported"]


class AnnotationBase(BaseModel):
    tier: str
    label: str
    lead: Optional[str] = None
    start_sample: int = Field(ge=0)
    end_sample: Optional[int] = Field(default=None, ge=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    review_status: ReviewStatus = "draft"
    beat_id: Optional[str] = None
    confidence: Optional[float] = None

    @property
    def kind(self) -> str:
        return "point" if self.end_sample is None else "interval"

    @model_validator(mode="after")
    def _geometry(self):
        if self.end_sample is not None and self.end_sample <= self.start_sample:
            raise ValueError("end_sample must be > start_sample (half-open interval [start, end))")
        return self


class AnnotationCreate(AnnotationBase):
    source: Source = "manual"
    provenance: dict[str, Any] = Field(default_factory=dict)
    client_id: Optional[str] = None  # echoed back so clients can map temporary ids


class AnnotationUpdate(AnnotationBase):
    revision: int = Field(ge=1)
    confirm_reviewed_change: bool = False


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    recording_id: str
    tier: str
    label: str
    lead: Optional[str]
    kind: str
    start_sample: int
    end_sample: Optional[int]
    attributes: dict[str, Any]
    source: str
    provenance: dict[str, Any]
    review_status: str
    confidence: Optional[float]
    beat_id: Optional[str]
    ontology_version: str
    revision: int
    created_at: dt.datetime
    updated_at: dt.datetime


class BatchOp(BaseModel):
    op: Literal["create", "update", "delete"]
    id: Optional[str] = None
    revision: Optional[int] = None
    data: Optional[dict[str, Any]] = None
    client_id: Optional[str] = None
    confirm_reviewed_change: bool = False


class BatchRequest(BaseModel):
    operations: list[BatchOp]


class BatchResult(BaseModel):
    batch_id: str
    created: list[AnnotationOut]
    updated: list[AnnotationOut]
    deleted: list[str]
    id_map: dict[str, str]


class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    dataset_id: Optional[str]
    name: str
    fs: float
    n_samples: int
    leads: list[str]
    units: list[str]
    original_units: list[str]
    gains: list[float]
    patient_id: Optional[str]
    meta: dict[str, Any]
    source: str
    signal_sha256: str
    duration_s: float = 0.0
    annotation_count: int = 0


class TierIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["point", "interval", "mixed"] = "mixed"
    scope: Literal["lead", "global"] = "lead"
    color: str = Field(default="#334155", pattern=r"^#[0-9a-fA-F]{6}$")
    level: str = ""
    overlap_policy: Literal["allow", "forbid_same_lead", "forbid_same_label"] = "allow"
    allow_free_labels: bool = True
    description: str = ""


class TierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    kind: str
    scope: str
    color: str
    level: str
    overlap_policy: str
    allow_free_labels: bool
    order: int
    is_custom: bool
    description: str


class LabelIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    name: str
    level: Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7"]
    parent_code: Optional[str] = None
    geometry: Literal["point", "interval", "any", "relation"] = "any"
    tiers: list[str] = Field(default_factory=list)
    attributes_schema: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class LabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    level: str
    parent_code: Optional[str]
    geometry: str
    tiers: list[str]
    attributes_schema: dict[str, Any]
    description: str
    is_custom: bool
    active: bool
    added_in_version: str


class RelationshipIn(BaseModel):
    source_id: str
    target_id: str
    relation_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class PredictionAccept(BaseModel):
    start_sample: Optional[int] = Field(default=None, ge=0)
    end_sample: Optional[int] = None
    label: Optional[str] = None
    tier: Optional[str] = None
    lead: Optional[str] = None
    review_status: ReviewStatus = "draft"


class AcceptRange(BaseModel):
    start_sample: int = Field(ge=0)
    end_sample: int = Field(ge=1)
    review_status: ReviewStatus = "draft"


class DetectRequest(BaseModel):
    lead: Optional[str] = None
    start_sample: int = Field(default=0, ge=0)
    end_sample: Optional[int] = None
    algorithm: Literal["scipy_pan_tompkins", "wfdb_xqrs"] = "scipy_pan_tompkins"


class DelineateRequest(BaseModel):
    lead: Optional[str] = None
    start_sample: int = Field(default=0, ge=0)
    end_sample: Optional[int] = None


class MeasurementRequest(BaseModel):
    lead: Optional[str] = None
    start_sample: int = Field(default=0, ge=0)
    end_sample: Optional[int] = None
    annotations: Optional[list[dict[str, Any]]] = None  # unsaved working copy; DB annotations if omitted


class SnapshotRequest(BaseModel):
    name: str = Field(default="dataset", min_length=1, max_length=200)
    version: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")
    recording_ids: Optional[list[str]] = None
    dataset_id: Optional[str] = None
    sources: list[Source] = Field(default_factory=lambda: ["manual", "reference", "algorithm", "imported"])
    review_statuses: list[ReviewStatus] = Field(default_factory=lambda: ["draft", "needs_review", "reviewed"])
    mask_tiers: list[str] = Field(default_factory=lambda: ["P Wave", "QRS Complex", "T Wave"])
    split: dict[str, float] = Field(default_factory=lambda: {"train": 0.7, "val": 0.15, "test": 0.15})
    seed: int = 42
