"""LUDB (Lobachevsky University Electrocardiography Database) v1.0.1 adapter.

* 200 records, 10 s, 12 leads, 500 Hz, physical units mV.
* Cardiologists annotated P, QRS and T onset/peak/offset **independently for
  each lead**; annotation files are named after the lead (``.i``, ``.ii``,
  ..., ``.v6``).  The middle symbol of the QRS triplet is ``N`` and marks the
  QRS peak (stored here as ``R_peak`` with ``original_symbol='N'``).
* Each record is a distinct subject, so ``patient_id = ludb-<record>``.
* The header comments carry age, sex, rhythm and diagnoses.
"""
from __future__ import annotations

import re
from pathlib import Path

import wfdb

from .base import AdapterError, DatasetAdapter, ParsedRecord, RefAnnotation, parse_wave_annotations

LUDB_LEAD_EXTS = ["i", "ii", "iii", "avr", "avl", "avf", "v1", "v2", "v3", "v4", "v5", "v6"]

RHYTHM_MAP = {
    "sinus rhythm": "sinus_rhythm",
    "sinus tachycardia": "sinus_tachycardia",
    "sinus bradycardia": "sinus_bradycardia",
    "sinus arrhythmia": "sinus_arrhythmia",
    "irregular sinus rhythm": "sinus_arrhythmia",
    "atrial fibrillation": "atrial_fibrillation",
    "atrial flutter": "atrial_flutter",
}


class LUDBAdapter(DatasetAdapter):
    id = "ludb"
    name = "Lobachevsky University Electrocardiography Database"
    version = "1.0.1"
    citation = (
        "Kalyakulina A, Yusipov I, Moskalenko V, Nikolskiy A, Kosonogov K, Zolotykh N, Ivanchenko M. "
        "Lobachevsky University Electrocardiography Database (version 1.0.1). PhysioNet (2021). "
        "https://doi.org/10.13026/eegm-h675. Also cite: Goldberger AL et al. PhysioBank, PhysioToolkit, "
        "and PhysioNet. Circulation 101(23):e215-e220 (2000)."
    )
    description = "200 x 10 s 12-lead ECGs at 500 Hz with manual per-lead P/QRS/T onset, peak and offset."
    annotation_semantics = (
        "Per-lead manual wave delineation by cardiologists. '(' onset, 'p'/'N'/'t' peak, ')' offset; "
        "offset is the last sample of the wave (inclusive) -> stored as half-open end = offset+1. "
        "'N' marks the QRS peak and is stored as R_peak. Record-level rhythm from header comments is stored as a "
        "global Rhythm interval spanning the record."
    )
    record_prefix = "data/"
    annotation_exts = tuple(LUDB_LEAD_EXTS)

    def parse(self, root: Path, record: str) -> ParsedRecord:
        rec, sig, leads, units, gains = self.read_signal(root, record)
        n = sig.shape[0]
        meta = parse_ludb_comments(rec.comments or [])
        anns: list[RefAnnotation] = []
        path = self.record_path(root, record)
        for ext in LUDB_LEAD_EXTS:
            if not Path(f"{path}.{ext}").exists():
                raise AdapterError(f"Missing LUDB annotation file {path}.{ext}")
            a = wfdb.rdann(str(path), ext)
            lead = {"avr": "aVR", "avl": "aVL", "avf": "aVF"}.get(ext, ext.upper())
            if lead not in leads:
                raise AdapterError(f"Annotation lead {lead} not in signal leads {leads}")
            prov = {"dataset": self.id, "dataset_version": self.version, "file": f"{record}.{ext}", "annotator": "LUDB cardiologists"}
            anns.extend(parse_wave_annotations(a.sample, list(a.symbol), lead, prov, n))
        rhythm_text = meta.get("rhythm")
        if rhythm_text:
            key = rhythm_text.strip().rstrip(".").lower()
            label = RHYTHM_MAP.get(key, "unknown_rhythm")
            anns.append(RefAnnotation("Rhythm", label, "interval", 0, n, None,
                                      {"original_aux": rhythm_text, "note": "record-level rhythm from LUDB header"},
                                      {"dataset": self.id, "dataset_version": self.version, "file": f"{record}.hea"}))
        return ParsedRecord(
            name=record, fs=float(rec.fs), signal=sig, leads=leads, original_units=units, gains=gains,
            patient_id=f"ludb-{record}", meta=meta, annotations=anns,
        )


def parse_ludb_comments(comments: list[str]) -> dict:
    meta: dict = {"diagnoses": []}
    for c in comments:
        c = c.strip()
        m = re.match(r"<(\w+)>:\s*(.*)", c)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "age":
                meta["age"] = val
            elif key == "sex":
                meta["sex"] = val
            elif key == "diagnoses":
                continue
            else:
                meta[key] = val
            continue
        if c.lower().startswith("rhythm:"):
            meta["rhythm"] = c.split(":", 1)[1].strip()
        elif c:
            meta["diagnoses"].append(c)
    return meta
