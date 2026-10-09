"""MIT-BIH Arrhythmia Database v1.0.0 adapter.

* 48 half-hour two-channel ambulatory records, 360 Hz, 47 subjects
  (records 201 and 202 come from the same subject).
* ``.atr`` reference annotations: one beat-class symbol per beat located at
  the beat's fiducial point (not guaranteed to be the R apex), plus rhythm
  change annotations (``+`` with aux note such as ``(AFIB``).
* Beat labels are not lead-specific, so they are stored with ``lead=None``.
"""
from __future__ import annotations

from pathlib import Path

import wfdb

from .base import DatasetAdapter, ParsedRecord, RefAnnotation

BEAT_SYMBOLS = {
    "N": "normal_beat", "L": "LBBB_beat", "R": "RBBB_beat", "A": "PAC", "a": "aberrant_PAC",
    "J": "nodal_premature_beat", "S": "supraventricular_premature_beat", "V": "PVC",
    "F": "fusion_beat", "e": "atrial_escape_beat", "j": "nodal_escape_beat",
    "E": "ventricular_escape_beat", "/": "paced_beat", "f": "paced_fusion_beat", "Q": "unknown_beat",
}

RHYTHM_AUX = {
    "(N": "sinus_rhythm", "(AFIB": "atrial_fibrillation", "(AFL": "atrial_flutter",
    "(B": "ventricular_bigeminy", "(BII": "second_degree_av_block", "(IVR": "idioventricular_rhythm",
    "(NOD": "nodal_rhythm", "(P": "paced_rhythm", "(PREX": "preexcitation",
    "(SBR": "sinus_bradycardia", "(SVTA": "supraventricular_tachyarrhythmia",
    "(T": "ventricular_trigeminy", "(VFL": "ventricular_flutter", "(VT": "ventricular_tachycardia",
    "(AB": "atrial_bigeminy",
}

SAME_SUBJECT = {"202": "201"}


def beat_reference(root: Path, record: str, prefix: str = "") -> tuple[list[int], list[str]]:
    """Return sample indices and symbols of beat annotations (for evaluation)."""
    a = wfdb.rdann(str(root / f"{prefix}{record}"), "atr")
    keep = [(int(s), sym) for s, sym in zip(a.sample, a.symbol) if sym in BEAT_SYMBOLS]
    return [k[0] for k in keep], [k[1] for k in keep]


def parse_beat_and_rhythm(samples, symbols, aux_notes, n: int, prov: dict) -> list[RefAnnotation]:
    anns: list[RefAnnotation] = []
    rhythm_starts: list[tuple[int, str, str]] = []
    for s, sym, aux in zip(samples, symbols, aux_notes):
        s = int(s)
        if not 0 <= s < n:
            continue
        if sym in BEAT_SYMBOLS:
            anns.append(RefAnnotation("Beat", BEAT_SYMBOLS[sym], "point", s, None, None,
                                      {"original_symbol": sym}, dict(prov)))
        elif sym == "+" and aux:
            aux = aux.strip("\x00").strip()
            rhythm_starts.append((s, RHYTHM_AUX.get(aux, "unknown_rhythm"), aux))
    for i, (s, label, aux) in enumerate(rhythm_starts):
        end = rhythm_starts[i + 1][0] if i + 1 < len(rhythm_starts) else n
        if end > s:
            anns.append(RefAnnotation("Rhythm", label, "interval", s, end, None, {"original_aux": aux}, dict(prov)))
    return anns


class MITDBAdapter(DatasetAdapter):
    id = "mitdb"
    name = "MIT-BIH Arrhythmia Database"
    version = "1.0.0"
    citation = (
        "Moody GB, Mark RG. The impact of the MIT-BIH Arrhythmia Database. IEEE Eng in Med and Biol "
        "20(3):45-50 (2001). Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. "
        "Circulation 101(23):e215-e220 (2000). https://doi.org/10.13026/C2F305"
    )
    description = "48 x 30 min two-channel ambulatory ECG at 360 Hz with reference beat and rhythm labels."
    annotation_semantics = (
        "Beat-class symbols at each beat's fiducial point (lead-independent) -> Beat tier points; "
        "'+' rhythm-change annotations (aux note) -> Rhythm intervals until the next change. "
        "No wave boundaries are provided. Signal-quality ('~') and comment annotations are not imported."
    )
    annotation_exts = ("atr",)

    def parse(self, root: Path, record: str) -> ParsedRecord:
        rec, sig, leads, units, gains = self.read_signal(root, record)
        n = sig.shape[0]
        a = wfdb.rdann(str(self.record_path(root, record)), "atr")
        prov = {"dataset": self.id, "dataset_version": self.version, "file": f"{record}.atr",
                "annotator": "MIT-BIH reference (two or more cardiologists)"}
        anns = parse_beat_and_rhythm(a.sample, a.symbol, a.aux_note, n, prov)
        meta = {"header_comments": list(rec.comments or [])}
        subject = SAME_SUBJECT.get(record, record)
        return ParsedRecord(name=record, fs=float(rec.fs), signal=sig, leads=leads, original_units=units,
                            gains=gains, patient_id=f"mitdb-{subject}", meta=meta, annotations=anns)
