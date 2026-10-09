"""Immutable dataset snapshots for medical-AI training, and round-trip import.

Snapshot layout (``DATA_DIR/exports/<version>/`` + ``<version>.zip``)::

    manifest.json        version, ontology version, recordings, annotation revisions,
                         label statistics, patient-level split, file checksums
    annotations.json     full structure (metadata, annotations, relationships, provenance, ontology)
    annotations.csv      one row per point/interval with attributes (JSON column)
    measurements.csv     beat measurements traced to samples/annotation ids
    splits.json          patient-grouped train/val/test assignment
    signals/<rec>.npz    waveform [n, leads] float32 mV + label arrays + segmentation masks
    README.txt           format description

Segmentation mask codes (``mask_<tier>``, int16, shape [n_leads, n_samples]):
``k >= 1`` class index into ``classes_<tier>`` (1-based), ``0`` annotated
background (inside the tier's annotated extent but no label), ``-1``
unannotated (outside the annotated extent), ``-2`` overlap of different
classes, ``-3`` uncertain (annotation has ``attributes.uncertain = true``).
``multihot_<tier>`` (uint8 [n_leads, n_samples, n_classes]) keeps every
overlapping label.  Global annotations (lead = null) apply to every lead.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Annotation, AnnotationRelationship, DatasetSnapshot, Recording, utcnow
from ..ontology import OntologyCache
from ..schemas import SnapshotRequest
from ..signal.measurements import compute_measurements
from ..storage import load_signal, sha256_file, save_signal
from .annotations import ann_out, record_revision

FORMAT = "ecg-annotation-studio/snapshot-1"
MASK_UNANNOTATED, MASK_OVERLAP, MASK_UNCERTAIN = -1, -2, -3


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower() or "x"


def patient_split(recs: list[Recording], fractions: dict[str, float], seed: int) -> dict:
    """Assign whole patient groups to splits (no patient appears in two splits)."""
    total = sum(fractions.values())
    if total <= 0:
        raise HTTPException(422, "split fractions must sum to > 0")
    names = list(fractions)
    groups: dict[str, list[Recording]] = defaultdict(list)
    for r in recs:
        groups[r.patient_id or f"recording:{r.id}"].append(r)
    keys = sorted(groups)
    rng = np.random.default_rng(seed)
    rng.shuffle(keys)
    n = len(recs)
    target = {k: fractions[k] / total * n for k in names}
    count = {k: 0 for k in names}
    assign: dict[str, str] = {}
    for g in keys:
        split = max(names, key=lambda k: (target[k] - count[k], -names.index(k)))
        for r in groups[g]:
            assign[r.id] = split
        count[split] += len(groups[g])
    by_split: dict[str, list[str]] = {k: [] for k in names}
    patients: dict[str, set[str]] = {k: set() for k in names}
    for r in recs:
        by_split[assign[r.id]].append(r.id)
        patients[assign[r.id]].add(r.patient_id or f"recording:{r.id}")
    leak = [p for i, a in enumerate(names) for b in names[i + 1:] for p in patients[a] & patients[b]]
    return {
        "grouping": "patient_id (recording id when patient identity is unknown)",
        "seed": seed, "fractions": fractions, "assignment": assign, "recordings": by_split,
        "patients": {k: sorted(v) for k, v in patients.items()},
        "patient_identity_available": sum(1 for r in recs if r.patient_id) / max(1, n),
        "leakage_check": "passed" if not leak else f"FAILED: {leak}",
    }


def build_masks(anns: list[dict], leads: list[str], n: int, tier: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    rows = [a for a in anns if a["tier"] == tier and a["end_sample"] is not None]
    classes = sorted({a["label"] for a in rows})
    cidx = {c: i for i, c in enumerate(classes)}
    L = len(leads)
    multi = np.zeros((L, n, max(1, len(classes))), dtype=np.uint8)
    uncertain = np.zeros((L, n), dtype=bool)
    covered = np.zeros((L, n), dtype=bool)
    for li, lead in enumerate(leads):
        mine = [a for a in rows if a["lead"] is None or a["lead"] == lead]
        if not mine:
            continue
        lo = min(a["start_sample"] for a in mine)
        hi = max(a["end_sample"] for a in mine)
        covered[li, lo:hi] = True
        for a in mine:
            multi[li, a["start_sample"]:a["end_sample"], cidx[a["label"]]] = 1
            if (a.get("attributes") or {}).get("uncertain") is True:
                uncertain[li, a["start_sample"]:a["end_sample"]] = True
    nlab = multi.sum(axis=2)
    dense = np.where(nlab == 1, multi.argmax(axis=2) + 1, 0).astype(np.int16)
    dense[nlab > 1] = MASK_OVERLAP
    dense[uncertain] = MASK_UNCERTAIN
    dense[~covered] = MASK_UNANNOTATED
    if not classes:
        multi = multi[:, :, :0]
    return dense, multi, uncertain, classes


def _readonly(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    except OSError:  # pragma: no cover
        pass


def create_snapshot(s: Session, req: SnapshotRequest) -> DatasetSnapshot:
    settings = get_settings()
    q = select(Recording)
    if req.recording_ids:
        q = q.where(Recording.id.in_(req.recording_ids))
    elif req.dataset_id:
        q = q.where(Recording.dataset_id == req.dataset_id)
    recs = list(s.scalars(q.order_by(Recording.dataset_id, Recording.name)))
    if not recs:
        raise HTTPException(422, "No recordings selected for export")
    if req.recording_ids and len(recs) != len(set(req.recording_ids)):
        raise HTTPException(404, "Some recording ids were not found")
    version = req.version
    if not version:
        n_prev = s.scalar(select(func.count()).select_from(DatasetSnapshot).where(DatasetSnapshot.name == req.name)) or 0
        version = f"{slug(req.name)}-v{n_prev + 1}"
        while s.scalar(select(DatasetSnapshot).where(DatasetSnapshot.version == version)) is not None:
            n_prev += 1
            version = f"{slug(req.name)}-v{n_prev + 1}"
    if s.scalar(select(DatasetSnapshot).where(DatasetSnapshot.version == version)) is not None:
        raise HTTPException(409, f"Dataset version '{version}' already exists (snapshots are immutable)")
    out = settings.exports_dir / version
    if out.exists() or (settings.exports_dir / f"{version}.zip").exists():
        raise HTTPException(409, f"Export directory for '{version}' already exists (snapshots are immutable)")
    onto = OntologyCache.load(s)
    created = utcnow()
    splits = patient_split(recs, req.split, req.seed)
    (out / "signals").mkdir(parents=True)

    doc_recs: list[dict] = []
    csv_rows: list[dict] = []
    meas_rows: list[dict] = []
    revisions: dict[str, int] = {}
    stats_label: Counter = Counter()
    stats_source: Counter = Counter()
    stats_split: dict[str, Counter] = defaultdict(Counter)
    for rec in recs:
        anns_db = list(s.scalars(select(Annotation).where(
            Annotation.recording_id == rec.id, Annotation.deleted.is_(False),
            Annotation.source.in_(req.sources), Annotation.review_status.in_(req.review_statuses),
        ).order_by(Annotation.start_sample, Annotation.id)))
        anns = [ann_out(a) for a in anns_db]
        ids = {a["id"] for a in anns}
        rels = [{"id": r.id, "source_id": r.source_id, "target_id": r.target_id, "relation_type": r.relation_type,
                 "attributes": r.attributes}
                for r in s.scalars(select(AnnotationRelationship).where(AnnotationRelationship.recording_id == rec.id))
                if r.source_id in ids and r.target_id in ids]
        split = splits["assignment"][rec.id]
        sig = np.asarray(load_signal(rec.signal_path), dtype=np.float32)
        n, leads = rec.n_samples, list(rec.leads)
        lead_idx = {l: i for i, l in enumerate(leads)}
        labels_all = sorted({a["label"] for a in anns})
        lab_idx = {l: i for i, l in enumerate(labels_all)}
        pts = [a for a in anns if a["kind"] == "point"]
        ivs = [a for a in anns if a["kind"] == "interval"]
        arrays: dict[str, Any] = {
            "signal": sig, "fs": np.float64(rec.fs), "leads": np.asarray(leads), "units": np.asarray(["mV"] * len(leads)),
            "label_names": np.asarray(labels_all if labels_all else [""]),
            "point_sample": np.asarray([a["start_sample"] for a in pts], dtype=np.int64),
            "point_label": np.asarray([lab_idx[a["label"]] for a in pts], dtype=np.int32),
            "point_lead": np.asarray([lead_idx.get(a["lead"], -1) for a in pts], dtype=np.int32),
            "interval_start": np.asarray([a["start_sample"] for a in ivs], dtype=np.int64),
            "interval_end": np.asarray([a["end_sample"] for a in ivs], dtype=np.int64),
            "interval_label": np.asarray([lab_idx[a["label"]] for a in ivs], dtype=np.int32),
            "interval_lead": np.asarray([lead_idx.get(a["lead"], -1) for a in ivs], dtype=np.int32),
        }
        mask_info = {}
        for tier in req.mask_tiers:
            dense, multi, unc, classes = build_masks(anns, leads, n, tier)
            key = slug(tier)
            arrays[f"mask_{key}"] = dense
            arrays[f"multihot_{key}"] = multi
            arrays[f"uncertain_{key}"] = unc
            arrays[f"classes_{key}"] = np.asarray(classes if classes else [""])
            mask_info[tier] = {"key": key, "classes": classes}
        meta = {"recording_id": rec.id, "dataset_id": rec.dataset_id, "name": rec.name, "patient_id": rec.patient_id,
                "split": split, "fs": rec.fs, "n_samples": n, "leads": leads, "masks": mask_info,
                "mask_codes": {"background": 0, "unannotated": MASK_UNANNOTATED, "overlap": MASK_OVERLAP,
                               "uncertain": MASK_UNCERTAIN, "class": ">=1 (index into classes_<tier>, 1-based)"},
                "interval_convention": "[start, end) integer samples", "point_lead/interval_lead": "-1 = global"}
        arrays["meta_json"] = np.asarray(json.dumps(meta))
        fname = f"signals/{slug(rec.dataset_id or 'rec')}_{slug(rec.name)}_{rec.id[:8]}.npz"
        np.savez_compressed(out / fname, **arrays)
        doc_recs.append({
            "recording": {"id": rec.id, "dataset_id": rec.dataset_id, "name": rec.name, "fs": rec.fs,
                          "n_samples": n, "leads": leads, "units": rec.units, "original_units": rec.original_units,
                          "gains": rec.gains, "patient_id": rec.patient_id, "meta": rec.meta,
                          "signal_sha256": rec.signal_sha256, "source": rec.source, "source_files": rec.source_files},
            "split": split, "signal_file": fname, "annotations": anns, "relationships": rels,
        })
        for a in anns:
            revisions[a["id"]] = a["revision"]
            stats_label[f"{a['tier']}::{a['label']}"] += 1
            stats_source[a["source"]] += 1
            stats_split[split][a["label"]] += 1
            csv_rows.append({
                "annotation_id": a["id"], "recording_id": rec.id, "dataset_id": rec.dataset_id, "record_name": rec.name,
                "patient_id": rec.patient_id or "", "split": split, "tier": a["tier"], "label": a["label"],
                "lead": a["lead"] or "", "kind": a["kind"], "start_sample": a["start_sample"],
                "end_sample": "" if a["end_sample"] is None else a["end_sample"],
                "start_s": f"{a['start_sample'] / rec.fs:.6f}",
                "end_s": "" if a["end_sample"] is None else f"{a['end_sample'] / rec.fs:.6f}",
                "fs": rec.fs, "source": a["source"], "review_status": a["review_status"], "revision": a["revision"],
                "beat_id": a["beat_id"] or "", "confidence": "" if a["confidence"] is None else a["confidence"],
                "ontology_version": a["ontology_version"], "attributes": json.dumps(a["attributes"], sort_keys=True),
                "provenance": json.dumps(a["provenance"], sort_keys=True),
            })
        lead_set = sorted({a["lead"] for a in anns if a["lead"]}) or leads[:1]
        for lead in lead_set:
            m = compute_measurements(anns, sig, rec.fs, lead, lead_idx.get(lead))
            for b in m["beats"]:
                for v in b["values"]:
                    meas_rows.append({"recording_id": rec.id, "record_name": rec.name, "lead": lead,
                                      "r_sample": b["r_sample"], "anchor": b["anchor"], "measurement": v["name"],
                                      "value": "" if v["value"] is None else f"{v['value']:.6g}", "unit": v["unit"],
                                      "samples": " ".join(map(str, v["samples"])),
                                      "annotation_ids": " ".join(v["annotation_ids"]), "method": v["method"],
                                      "experimental": v["experimental"], "na_reason": v["reason"] or ""})

    ontology_doc = {
        "version": onto.version,
        "tiers": [{"name": t.name, "kind": t.kind, "scope": t.scope, "level": t.level, "overlap_policy": t.overlap_policy,
                   "color": t.color, "is_custom": t.is_custom} for t in sorted(onto.tiers.values(), key=lambda t: t.order)],
        "labels": [{"code": l.code, "name": l.name, "level": l.level, "parent": l.parent_code, "geometry": l.geometry,
                    "tiers": l.tiers, "attributes_schema": l.attributes_schema, "is_custom": l.is_custom}
                   for l in onto.labels.values()],
    }
    doc = {"format": FORMAT, "dataset_version": version, "name": req.name, "created_at": created.isoformat(),
           "ontology_version": onto.version, "interval_convention": "[start_sample, end_sample) integer sample indices",
           "ontology": ontology_doc, "recordings": doc_recs}
    (out / "annotations.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    _write_csv(out / "annotations.csv", csv_rows, [
        "annotation_id", "recording_id", "dataset_id", "record_name", "patient_id", "split", "tier", "label", "lead",
        "kind", "start_sample", "end_sample", "start_s", "end_s", "fs", "source", "review_status", "revision", "beat_id",
        "confidence", "ontology_version", "attributes", "provenance"])
    _write_csv(out / "measurements.csv", meas_rows, [
        "recording_id", "record_name", "lead", "r_sample", "anchor", "measurement", "value", "unit", "samples",
        "annotation_ids", "method", "experimental", "na_reason"])
    (out / "splits.json").write_text(json.dumps(splits, indent=1), encoding="utf-8")
    (out / "README.txt").write_text(__doc__ or "", encoding="utf-8")
    files = {p.relative_to(out).as_posix(): sha256_file(p) for p in sorted(out.rglob("*")) if p.is_file()}
    manifest = {
        "format": FORMAT, "dataset_version": version, "name": req.name, "created_at": created.isoformat(),
        "ontology_version": onto.version, "params": req.model_dump(),
        "recordings": [{"id": d["recording"]["id"], "dataset_id": d["recording"]["dataset_id"],
                        "name": d["recording"]["name"], "patient_id": d["recording"]["patient_id"], "split": d["split"],
                        "fs": d["recording"]["fs"], "n_samples": d["recording"]["n_samples"],
                        "leads": d["recording"]["leads"], "signal_sha256": d["recording"]["signal_sha256"],
                        "signal_file": d["signal_file"], "n_annotations": len(d["annotations"])} for d in doc_recs],
        "annotation_revisions": revisions,
        "label_statistics": {"by_tier_label": dict(sorted(stats_label.items())), "by_source": dict(stats_source),
                             "by_split": {k: dict(v) for k, v in stats_split.items()}, "total": sum(stats_label.values())},
        "splits": {k: v for k, v in splits.items() if k != "assignment"},
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    zpath = settings.exports_dir / f"{version}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                z.write(p, f"{version}/{p.relative_to(out).as_posix()}")
    for p in out.rglob("*"):
        if p.is_file():
            _readonly(p)
    _readonly(zpath)
    snap = DatasetSnapshot(version=version, name=req.name, ontology_version=onto.version, params=req.model_dump(),
                           manifest={k: v for k, v in manifest.items() if k != "annotation_revisions"},
                           archive_path=zpath.relative_to(settings.data_dir).as_posix(),
                           archive_sha256=sha256_file(zpath), created_at=created)
    s.add(snap)
    s.flush()
    return snap


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def verify_snapshot(s: Session, snap: DatasetSnapshot) -> dict:
    """Re-hash snapshot files and compare exported revisions with the live database."""
    settings = get_settings()
    out = settings.exports_dir / snap.version
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    bad = [f for f, h in manifest["files"].items() if not (out / f).exists() or sha256_file(out / f) != h]
    zpath = settings.data_dir / snap.archive_path
    zip_ok = zpath.exists() and sha256_file(zpath) == snap.archive_sha256
    revs = manifest["annotation_revisions"]
    live = {a.id: a for a in s.scalars(select(Annotation).where(Annotation.id.in_(list(revs))))} if revs else {}
    changed = [i for i, r in revs.items() if i not in live or live[i].revision != r or live[i].deleted]
    return {"version": snap.version, "files_checked": len(manifest["files"]), "corrupted_files": bad,
            "archive_sha256_ok": zip_ok, "annotations_changed_since_export": len(changed),
            "immutable_integrity": "passed" if not bad and zip_ok else "FAILED"}


# ---------------------------------------------------------------------------
# Import (round trip)
# ---------------------------------------------------------------------------
COMPARE_FIELDS = ("tier", "label", "lead", "kind", "start_sample", "end_sample", "attributes")


def _load_bundle(raw: bytes, filename: str) -> tuple[dict, dict[str, bytes]]:
    if filename.lower().endswith(".zip") or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            ann_name = next((n for n in names if n.endswith("annotations.json")), None)
            if ann_name is None:
                raise HTTPException(422, "ZIP does not contain annotations.json")
            prefix = ann_name[: -len("annotations.json")]
            doc = json.loads(z.read(ann_name))
            signals = {n[len(prefix):]: z.read(n) for n in names if n.startswith(prefix + "signals/")}
            return doc, signals
    try:
        return json.loads(raw), {}
    except Exception as e:
        raise HTTPException(422, f"Not a snapshot ZIP or annotations.json: {e}") from e


def _same(a: dict, b: dict) -> list[str]:
    return [f for f in COMPARE_FIELDS if a.get(f) != b.get(f)]


def import_bundle(s: Session, raw: bytes, filename: str, mode: str) -> dict:
    doc, signals = _load_bundle(raw, filename)
    if doc.get("format") != FORMAT:
        raise HTTPException(422, f"Unsupported format {doc.get('format')!r}")
    onto = OntologyCache.load(s)
    report: dict = {"mode": mode, "dataset_version": doc.get("dataset_version"), "recordings": [], "ok": True}
    for entry in doc["recordings"]:
        rmeta = entry["recording"]
        exported = entry["annotations"]
        item: dict = {"name": rmeta["name"], "dataset_id": rmeta["dataset_id"], "n_exported": len(exported)}
        src = s.get(Recording, rmeta["id"])
        if src is None:
            src = s.scalar(select(Recording).where(Recording.dataset_id == rmeta["dataset_id"],
                                                   Recording.name == rmeta["name"]))
        if mode == "verify":
            if src is None:
                item.update(error="source recording not found in database")
                report["ok"] = False
                report["recordings"].append(item)
                continue
            live = {a.id: ann_out(a) for a in s.scalars(select(Annotation).where(
                Annotation.recording_id == src.id, Annotation.deleted.is_(False)))}
            mism = []
            for a in exported:
                cur = live.get(a["id"])
                if cur is None:
                    mism.append({"id": a["id"], "problem": "missing in database"})
                elif diff := _same(a, cur):
                    mism.append({"id": a["id"], "fields": diff})
            item.update(recording_id=src.id, n_matched=len(exported) - len(mism), mismatches=mism[:50],
                        signal_sha256_match=src.signal_sha256 == rmeta["signal_sha256"])
            report["ok"] &= not mism and item["signal_sha256_match"]
        else:  # new_recording
            sig_bytes = signals.get(entry.get("signal_file", ""))
            if sig_bytes is not None:
                with np.load(io.BytesIO(sig_bytes), allow_pickle=False) as z:
                    signal = np.asarray(z["signal"], dtype=np.float32)
                signal_origin = "snapshot npz"
            elif src is not None:
                signal = np.asarray(load_signal(src.signal_path), dtype=np.float32)
                signal_origin = "existing recording"
            else:
                raise HTTPException(422, f"No signal available for {rmeta['name']}")
            rec_id = str(uuid.uuid4())
            rel, digest = save_signal(rec_id, signal)
            name = f"{rmeta['name']} [import {doc.get('dataset_version')} {rec_id[:6]}]"
            rec = Recording(id=rec_id, dataset_id=rmeta["dataset_id"], name=name, fs=rmeta["fs"],
                            n_samples=int(signal.shape[0]), leads=rmeta["leads"], units=rmeta.get("units", []),
                            original_units=rmeta.get("original_units", []), gains=rmeta.get("gains", []),
                            patient_id=rmeta.get("patient_id"),
                            meta={**(rmeta.get("meta") or {}), "imported_from": doc.get("dataset_version"),
                                  "imported_from_recording": rmeta["id"]},
                            signal_path=rel, signal_sha256=digest, source="imported", source_files={})
            s.add(rec)
            s.flush()
            id_map: dict[str, str] = {}
            for a in exported:
                new = Annotation(
                    id=str(uuid.uuid4()), recording_id=rec.id, tier=a["tier"], label=a["label"], lead=a["lead"],
                    kind=a["kind"], start_sample=a["start_sample"], end_sample=a["end_sample"],
                    attributes=a["attributes"], source="imported",
                    provenance={"imported_from": doc.get("dataset_version"), "original_id": a["id"],
                                "original_source": a["source"], "original_revision": a["revision"],
                                "original_provenance": a["provenance"]},
                    review_status=a["review_status"], confidence=a.get("confidence"), beat_id=a.get("beat_id"),
                    ontology_version=a.get("ontology_version", onto.version), revision=1)
                s.add(new)
                id_map[a["id"]] = new.id
            s.flush()
            for a in s.scalars(select(Annotation).where(Annotation.recording_id == rec.id)):
                record_revision(s, a, "create", None, actor=f"import:{doc.get('dataset_version')}")
            for r in entry.get("relationships", []):
                if r["source_id"] in id_map and r["target_id"] in id_map:
                    s.add(AnnotationRelationship(recording_id=rec.id, source_id=id_map[r["source_id"]],
                                                 target_id=id_map[r["target_id"]], relation_type=r["relation_type"],
                                                 attributes=r.get("attributes", {})))
            s.flush()
            back = {a.provenance["original_id"]: ann_out(a) for a in s.scalars(
                select(Annotation).where(Annotation.recording_id == rec.id))}
            mism = [{"id": a["id"], "fields": d} for a in exported if (d := _same(a, back.get(a["id"], {})))]
            sig_equal = src is not None and np.array_equal(
                np.asarray(load_signal(src.signal_path)), np.asarray(load_signal(rec.signal_path)))
            item.update(new_recording_id=rec.id, new_recording_name=name, signal_origin=signal_origin,
                        n_matched=len(exported) - len(mism), mismatches=mism[:50],
                        signal_identical_to_source=bool(sig_equal) if src is not None else None,
                        signal_sha256_match=digest == rmeta["signal_sha256"])
            report["ok"] &= not mism
        report["recordings"].append(item)
    report["checked_fields"] = list(COMPARE_FIELDS)
    return report


def delete_export_dir(version: str) -> None:  # used only by tests
    settings = get_settings()
    for p in [settings.exports_dir / version, settings.exports_dir / f"{version}.zip"]:
        if p.is_dir():
            for f in p.rglob("*"):
                os.chmod(f, stat.S_IWRITE | stat.S_IREAD)
            shutil.rmtree(p)
        elif p.exists():
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            p.unlink()
