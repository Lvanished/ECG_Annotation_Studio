"""SQLAlchemy ORM models.

Raw ECG samples live on disk (``DATA_DIR/signals/<recording_id>.npy``); the
database stores only metadata and annotations.  All annotation coordinates are
integer sample indices; intervals are half-open ``[start_sample, end_sample)``.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug, e.g. "ludb"
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(32), default="")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    license: Mapped[str] = mapped_column(String(200), default="")
    citation: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    annotation_semantics: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    fs: Mapped[float] = mapped_column(Float)
    n_samples: Mapped[int] = mapped_column(Integer)
    leads: Mapped[list] = mapped_column(JSON)
    units: Mapped[list] = mapped_column(JSON, default=list)  # stored units after conversion (always mV)
    original_units: Mapped[list] = mapped_column(JSON, default=list)
    gains: Mapped[list] = mapped_column(JSON, default=list)  # ADC gain per lead (adu/physical unit)
    patient_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    signal_path: Mapped[str] = mapped_column(String(500))
    signal_sha256: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(50), default="upload")  # physionet | upload | imported
    source_files: Mapped[dict] = mapped_column(JSON, default=dict)  # filename -> sha256
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("dataset_id", "name", name="uq_recording_dataset_name"),)


class OntologyMeta(Base):
    __tablename__ = "ontology_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class Tier(Base):
    __tablename__ = "tiers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # point | interval | mixed
    scope: Mapped[str] = mapped_column(String(16), default="lead")  # lead | global
    color: Mapped[str] = mapped_column(String(16), default="#2563eb")
    level: Mapped[str] = mapped_column(String(8), default="")
    overlap_policy: Mapped[str] = mapped_column(String(32), default="allow")  # allow | forbid_same_lead | forbid_same_label
    allow_free_labels: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OntologyLabel(Base):
    __tablename__ = "ontology_labels"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(8))  # L0..L7
    parent_code: Mapped[str | None] = mapped_column(ForeignKey("ontology_labels.code"), nullable=True)
    geometry: Mapped[str] = mapped_column(String(16), default="any")  # point | interval | any | attribute
    tiers: Mapped[list] = mapped_column(JSON, default=list)  # tier names where label may be used
    attributes_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_in_version: Mapped[str] = mapped_column(String(32), default="1.0.0")


class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    tier: Mapped[str] = mapped_column(String(100), index=True)
    label: Mapped[str] = mapped_column(String(64))
    lead: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None => global / all leads
    kind: Mapped[str] = mapped_column(String(16))  # point | interval
    start_sample: Mapped[int] = mapped_column(Integer)
    end_sample: Mapped[int | None] = mapped_column(Integer, nullable=True)  # exclusive; None for points
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | reference | algorithm | imported
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(32), default="draft")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    beat_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ontology_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (Index("ix_annotations_rec_start", "recording_id", "start_sample"),)


class AnnotationRelationship(Base):
    __tablename__ = "annotation_relationships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("annotations.id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(ForeignKey("annotations.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(32))  # part_of | same_beat | aligned_with
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnnotationRevision(Base):
    __tablename__ = "annotation_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    annotation_id: Mapped[str] = mapped_column(String(36), index=True)
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(16))  # create | update | delete
    snapshot: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(100), default="local-user")
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PredictionRun(Base):
    __tablename__ = "prediction_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    algorithm: Mapped[str] = mapped_column(String(100))
    algorithm_version: Mapped[str] = mapped_column(String(32))
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    lead: Mapped[str | None] = mapped_column(String(32), nullable=True)
    start_sample: Mapped[int] = mapped_column(Integer, default=0)
    end_sample: Mapped[int] = mapped_column(Integer, default=0)
    experimental: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("prediction_runs.id", ondelete="CASCADE"), index=True)
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    tier: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(64))
    lead: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    start_sample: Mapped[int] = mapped_column(Integer)
    end_sample: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | accepted | modified | rejected
    annotation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run: Mapped[PredictionRun] = relationship(back_populates="predictions")


class DatasetSnapshot(Base):
    """Immutable export snapshot. Rows are never updated after creation."""

    __tablename__ = "dataset_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    ontology_version: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    archive_path: Mapped[str] = mapped_column(String(500))
    archive_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
