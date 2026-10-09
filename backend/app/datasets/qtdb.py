"""QT Database v1.0.0 adapter.

* 105 fifteen-minute two-lead excerpts at 250 Hz drawn from several source
  databases (MIT-BIH, ST-T, sudden death, ...).
* ``.q1c``: manual waveform boundaries by cardiologist 1 for a selection of
  (typically 30+) beats.  The annotator examined **both signals together**,
  so these annotations are stored with ``lead=None`` (global).
* The pattern is ``(`` onset, wave symbol (``p``, ``N``, ``t``, ``u``), ``)``
  offset; T onsets are frequently omitted, in which case only T peak and
  T offset fiducial points are created.
* ``.atr`` (when present) contains beat-class labels inherited from the source
  database.  Automatic ``.pu*`` annotations are not imported as reference.
* Patient identity is not provided; each record is treated as its own group.
"""
from __future__ import annotations

from pathlib import Path

import wfdb

from .base import DatasetAdapter, ParsedRecord, parse_wave_annotations
from .mitdb import parse_beat_and_rhythm


class QTDBAdapter(DatasetAdapter):
    id = "qtdb"
    name = "QT Database"
    version = "1.0.0"
    citation = (
        "Laguna P, Mark RG, Goldberger AL, Moody GB. A Database for Evaluation of Algorithms for Measurement "
        "of QT and Other Waveform Intervals in the ECG. Computers in Cardiology 24:673-676 (1997). "
        "Goldberger AL et al. PhysioBank, PhysioToolkit, and PhysioNet. Circulation 101(23):e215-e220 (2000). "
        "https://doi.org/10.13026/C24K59"
    )
    description = "105 x 15 min two-lead ECGs at 250 Hz with manual P/QRS/T boundaries for selected beats."
    annotation_semantics = (
        "Manual (.q1c, annotator 1) wave boundaries for selected beats, judged using both leads -> global "
        "(lead=None) P/QRS/T intervals and peaks; beats without both boundaries become fiducial points. "
        ".atr beat labels (when present) -> Beat tier points. Automatic .pu annotations are not imported."
    )
    annotation_exts = ("q1c",)
    optional_exts = ("atr", "q2c", "pu", "pu0", "pu1", "man")

    def parse(self, root: Path, record: str) -> ParsedRecord:
        rec, sig, leads, units, gains = self.read_signal(root, record)
        n = sig.shape[0]
        path = self.record_path(root, record)
        a = wfdb.rdann(str(path), "q1c")
        prov = {"dataset": self.id, "dataset_version": self.version, "file": f"{record}.q1c",
                "annotator": "QTDB cardiologist 1 (q1c)"}
        anns = parse_wave_annotations(a.sample, list(a.symbol), None, prov, n)
        for ann in anns:
            ann.attributes["note"] = "boundary judged on both leads"
        if Path(f"{path}.atr").exists():
            atr = wfdb.rdann(str(path), "atr")
            prov_b = {"dataset": self.id, "dataset_version": self.version, "file": f"{record}.atr",
                      "annotator": "source database reference"}
            anns.extend(x for x in parse_beat_and_rhythm(atr.sample, atr.symbol, atr.aux_note, n, prov_b)
                        if x.tier == "Beat")
        meta = {"header_comments": list(rec.comments or []),
                "q1c_beats_annotated": sum(1 for s in a.symbol if s == "N")}
        return ParsedRecord(name=record, fs=float(rec.fs), signal=sig, leads=leads, original_units=units,
                            gains=gains, patient_id=f"qtdb-{record}", meta=meta, annotations=anns)
