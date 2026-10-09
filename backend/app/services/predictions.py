"""Algorithm prediction layer (kept separate from annotations until reviewed)."""
from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Annotation, Prediction, PredictionRun, Recording, utcnow
from ..ontology import OntologyCache
from ..schemas import AnnotationCreate, PredictionAccept
from ..signal import delineation, rpeak
from ..storage import load_signal
from .annotations import api_error, check_overlaps, create_annotation

CONFLICT_TOLERANCE_S = 0.05


def _window(rec: Recording, lead: str | None, start: int, end: int | None) -> tuple[str, int, int]:
    lead = lead or ("II" if "II" in rec.leads else rec.leads[0])
    if lead not in rec.leads:
        raise api_error(422, "invalid_lead", f"Unknown lead '{lead}'")
    stop = min(end if end is not None else rec.n_samples, rec.n_samples)
    if stop - start < int(2 * rec.fs):
        raise api_error(422, "window_too_short", "Detection window must be at least 2 s")
    return lead, start, stop


def _x(rec: Recording, lead: str, start: int, stop: int) -> np.ndarray:
    sig = load_signal(rec.signal_path)
    return np.asarray(sig[start:stop, rec.leads.index(lead)], dtype=np.float64)


def run_rpeak(s: Session, rec: Recording, lead: str | None, start: int, end: int | None, algorithm: str) -> PredictionRun:
    lead, start, stop = _window(rec, lead, start, end)
    res = rpeak.detect(_x(rec, lead, start, stop), rec.fs, algorithm, offset=start)
    run = PredictionRun(recording_id=rec.id, algorithm=res.algorithm, algorithm_version=res.version,
                        parameters={**res.parameters, "fs": rec.fs}, lead=lead, start_sample=start, end_sample=stop,
                        experimental=False)
    s.add(run)
    s.flush()
    for smp, sc in zip(res.samples, res.scores):
        attrs = {} if np.isnan(sc) else {"x_detection_score": round(float(sc), 4)}
        s.add(Prediction(run_id=run.id, recording_id=rec.id, tier="Fiducial Points", label="R_peak", lead=lead,
                         kind="point", start_sample=int(smp), end_sample=None, confidence=None, attributes=attrs))
    s.flush()
    return run


def run_segmentation(s: Session, rec: Recording, source_run_id: str | None, lead: str | None) -> PredictionRun:
    """Beat regions from an R-peak run (or from reviewed R_peak / Beat annotations)."""
    if source_run_id:
        src = s.get(PredictionRun, source_run_id)
        if src is None or src.recording_id != rec.id:
            raise api_error(404, "not_found", "Source prediction run not found")
        peaks = sorted({p.start_sample for p in src.predictions if p.status != "rejected"})
        origin = f"prediction run {src.id} ({src.algorithm})"
    else:
        anns = s.scalars(select(Annotation).where(Annotation.recording_id == rec.id, Annotation.deleted.is_(False),
                                                  Annotation.kind == "point"))
        pts = [a for a in anns if a.label == "R_peak" and (lead is None or a.lead in (None, lead))]
        if not pts:
            pts = [a for a in s.scalars(select(Annotation).where(
                Annotation.recording_id == rec.id, Annotation.deleted.is_(False), Annotation.tier == "Beat",
                Annotation.kind == "point"))]
        peaks = sorted({a.start_sample for a in pts})
        origin = "existing R_peak/Beat annotations"
    if len(peaks) < 2:
        raise api_error(422, "insufficient_peaks", "Need at least two R peaks for beat segmentation")
    segs = rpeak.segment_beats(np.asarray(peaks), rec.n_samples, 0.6)
    run = PredictionRun(recording_id=rec.id, algorithm="rr_fraction_beat_segmentation", algorithm_version="1.0.0",
                        parameters={"split_fraction": 0.6, "origin": origin,
                                    "definition": "boundary = R_i + 0.6*(R_{i+1}-R_i); edges extend by the same fraction"},
                        lead=None, start_sample=segs[0][0], end_sample=segs[-1][1], experimental=False)
    s.add(run)
    s.flush()
    for a, b, r in segs:
        s.add(Prediction(run_id=run.id, recording_id=rec.id, tier="Beat", label="beat_region", lead=None,
                         kind="interval", start_sample=a, end_sample=b, attributes={"x_r_peak_sample": r}))
    s.flush()
    return run


def run_delineation(s: Session, rec: Recording, lead: str | None, start: int, end: int | None) -> PredictionRun:
    lead, start, stop = _window(rec, lead, start, end)
    x = _x(rec, lead, start, stop)
    r = rpeak.detect(x, rec.fs, rpeak.ALGORITHM, offset=start)
    beats = delineation.delineate(x, rec.fs, r.samples, offset=start)
    run = PredictionRun(recording_id=rec.id, algorithm=delineation.ALGORITHM, algorithm_version=delineation.VERSION,
                        parameters={"r_peak_algorithm": f"{r.algorithm}@{r.version}", "fs": rec.fs,
                                    "description": (delineation.__doc__ or "").strip().splitlines()[0]},
                        lead=lead, start_sample=start, end_sample=stop, experimental=True)
    s.add(run)
    s.flush()
    spec = [("p", "P Wave", "P_wave"), ("qrs", "QRS Complex", "QRS_complex"), ("t", "T Wave", "T_wave")]
    for b in beats:
        for key, tier, label in spec:
            if key in b:
                a, e = b[key]
                if 0 <= a < e <= rec.n_samples:
                    s.add(Prediction(run_id=run.id, recording_id=rec.id, tier=tier, label=label, lead=lead,
                                     kind="interval", start_sample=a, end_sample=e,
                                     attributes={"x_experimental": True}))
    s.flush()
    return run


def _conflicts(s: Session, rec: Recording, tier: str, label: str, lead: str | None, start: int, end: int | None) -> list[Annotation]:
    tol = int(round(CONFLICT_TOLERANCE_S * rec.fs))
    q = select(Annotation).where(Annotation.recording_id == rec.id, Annotation.deleted.is_(False),
                                 Annotation.tier == tier, Annotation.label == label)
    out = []
    for a in s.scalars(q):
        if not (a.lead is None or lead is None or a.lead == lead):
            continue
        if end is None and a.end_sample is None:
            if abs(a.start_sample - start) <= tol:
                out.append(a)
        elif end is not None and a.end_sample is not None:
            if a.start_sample < end and start < a.end_sample:
                out.append(a)
    return out


def accept_prediction(s: Session, pred: Prediction, body: PredictionAccept, onto: OntologyCache | None = None) -> Annotation:
    if pred.status not in ("pending",):
        raise api_error(409, "already_reviewed", f"Prediction already {pred.status}")
    rec = s.get(Recording, pred.recording_id)
    assert rec is not None
    run = pred.run
    onto = onto or OntologyCache.load(s)
    start = body.start_sample if body.start_sample is not None else pred.start_sample
    end = pred.end_sample if pred.kind == "point" or body.end_sample is None else body.end_sample
    if pred.kind == "point":
        end = None
    tier = body.tier or pred.tier
    label = body.label or pred.label
    lead = body.lead if body.lead is not None else pred.lead
    conflicts = _conflicts(s, rec, tier, label, lead, start, end)
    reviewed = [c for c in conflicts if c.review_status == "reviewed"]
    if reviewed:
        raise api_error(409, "conflicts_with_reviewed",
                        f"Prediction overlaps reviewed annotation(s) {', '.join(c.id for c in reviewed)}; "
                        "reviewed annotations are never overwritten", annotation_ids=[c.id for c in reviewed])
    if conflicts:
        raise api_error(409, "duplicate_annotation",
                        f"An equivalent {label} annotation already exists near sample {start}",
                        annotation_ids=[c.id for c in conflicts])
    modified = (start != pred.start_sample or end != pred.end_sample or tier != pred.tier or label != pred.label
                or lead != pred.lead)
    payload = AnnotationCreate(
        tier=tier, label=label, lead=lead, start_sample=start, end_sample=end,
        attributes={k: v for k, v in (pred.attributes or {}).items() if not k.startswith("x_experimental")},
        review_status=body.review_status, confidence=pred.confidence, source="algorithm",
        provenance={"prediction_id": pred.id, "run_id": run.id, "algorithm": run.algorithm,
                    "algorithm_version": run.algorithm_version, "parameters": run.parameters,
                    "experimental": run.experimental, "original_start_sample": pred.start_sample,
                    "original_end_sample": pred.end_sample, "modified_by_reviewer": modified},
    )
    a = create_annotation(s, rec, onto, payload, batch_id=None, actor="prediction-review")
    s.flush()
    check_overlaps(s, onto, rec.id, {(a.tier, a.lead)}, {a.id})
    pred.status = "modified" if modified else "accepted"
    pred.annotation_id = a.id
    pred.reviewed_at = utcnow()
    return a


def reject_prediction(pred: Prediction) -> None:
    if pred.status != "pending":
        raise api_error(409, "already_reviewed", f"Prediction already {pred.status}")
    pred.status = "rejected"
    pred.reviewed_at = utcnow()
