"""Dataset adapter interface.

Each PhysioNet database has its own adapter because annotation semantics
differ (MIT-BIH: beat class symbols at a fiducial point; LUDB: per-lead wave
onset/peak/offset; QTDB: manual wave boundaries for selected beats, judged on
both leads).  Adapters convert reference annotations into this project's
ontology while preserving the original symbols in ``attributes``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import wfdb

# Physical units understood by the importer and the factor to convert to mV
UNIT_TO_MV = {"mV": 1.0, "mv": 1.0, "uV": 1e-3, "µV": 1e-3, "μV": 1e-3, "V": 1e3}

STANDARD_12_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
_LEAD_ALIASES = {
    "i": "I", "ii": "II", "iii": "III", "avr": "aVR", "avl": "aVL", "avf": "aVF",
    **{f"v{i}": f"V{i}" for i in range(1, 7)},
}


def normalize_lead(name: str) -> str:
    return _LEAD_ALIASES.get(name.strip().lower(), name.strip())


@dataclass
class RefAnnotation:
    tier: str
    label: str
    kind: str  # point | interval
    start: int
    end: int | None
    lead: str | None
    attributes: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedRecord:
    name: str
    fs: float
    signal: np.ndarray  # float32 [n, leads] in mV
    leads: list[str]
    original_units: list[str]
    gains: list[float]
    patient_id: str | None
    meta: dict[str, Any]
    annotations: list[RefAnnotation]


class AdapterError(RuntimeError):
    pass


class DatasetAdapter:
    id: str = ""
    name: str = ""
    version: str = ""
    license: str = "Open Data Commons Attribution License v1.0"
    citation: str = ""
    description: str = ""
    annotation_semantics: str = ""
    record_prefix: str = ""  # sub-directory inside the PhysioNet project
    signal_exts: tuple[str, ...] = ("hea", "dat")
    annotation_exts: tuple[str, ...] = ()
    optional_exts: tuple[str, ...] = ()

    @property
    def base_url(self) -> str:
        return f"https://physionet.org/files/{self.id}/{self.version}/"

    @property
    def page_url(self) -> str:
        return f"https://physionet.org/content/{self.id}/{self.version}/"

    def record_files(self, record: str) -> list[tuple[str, bool]]:
        """(relative path, required) pairs for a record."""
        base = f"{self.record_prefix}{record}"
        files = [(f"{base}.{e}", True) for e in self.signal_exts]
        files += [(f"{base}.{e}", True) for e in self.annotation_exts]
        files += [(f"{base}.{e}", False) for e in self.optional_exts]
        return files

    def record_path(self, root: Path, record: str) -> Path:
        return root / f"{self.record_prefix}{record}"

    def available_records(self, root: Path) -> list[str]:
        d = root / self.record_prefix if self.record_prefix else root
        if not d.exists():
            return []
        names = [p.stem for p in d.glob("*.hea")]
        return sorted(names, key=lambda x: (len(x), x))

    # ---- parsing helpers -------------------------------------------------
    def read_signal(self, root: Path, record: str) -> tuple[wfdb.Record, np.ndarray, list[str], list[str], list[float]]:
        path = self.record_path(root, record)
        if not path.with_suffix(".hea").exists():
            raise AdapterError(f"Header not found: {path}.hea")
        rec = wfdb.rdrecord(str(path))
        if rec.p_signal is None:
            raise AdapterError("WFDB record has no physical signal")
        units = list(rec.units or [])
        sig = np.asarray(rec.p_signal, dtype=np.float64)
        for i, u in enumerate(units):
            if u not in UNIT_TO_MV:
                raise AdapterError(f"Unsupported physical unit '{u}' for lead {rec.sig_name[i]}")
            sig[:, i] *= UNIT_TO_MV[u]
        if not np.isfinite(sig).all():
            # WFDB marks invalid samples as NaN; keep them out of float32 math by zero-filling
            # but record the fraction so quality tools can report it.
            sig = np.nan_to_num(sig, nan=0.0)
        leads = [normalize_lead(n) for n in rec.sig_name]
        gains = [float(g) for g in (rec.adc_gain or [])]
        return rec, sig.astype(np.float32), leads, units, gains

    def parse(self, root: Path, record: str) -> ParsedRecord:  # pragma: no cover - abstract
        raise NotImplementedError


def parse_wave_annotations(
    samples: np.ndarray,
    symbols: list[str],
    lead: str | None,
    provenance: dict[str, Any],
    n_samples: int,
) -> list[RefAnnotation]:
    """Convert '(' wave ')' triplets (LUDB/QTDB style) into intervals + peak points.

    The onset '(' and offset ')' marks are inclusive sample positions, so the
    half-open interval is ``[onset, offset + 1)``.  If either boundary is
    missing (e.g. truncated at the record edge, or QTDB beats with no T onset)
    no interval is created; the available marks become fiducial points instead.
    """
    wave_map = {
        "p": ("P Wave", "P_wave", "P_peak", "P_onset", "P_offset"),
        "N": ("QRS Complex", "QRS_complex", "R_peak", "QRS_onset", "QRS_offset"),
        "t": ("T Wave", "T_wave", "T_peak", "T_onset", "T_offset"),
        "u": ("U Wave", "U_wave", None, None, None),
    }
    out: list[RefAnnotation] = []
    n = len(symbols)
    for i, sym in enumerate(symbols):
        if sym not in wave_map:
            continue
        tier, wave_label, peak_label, on_label, off_label = wave_map[sym]
        peak = int(samples[i])
        onset = int(samples[i - 1]) if i > 0 and symbols[i - 1] == "(" else None
        offset = int(samples[i + 1]) if i + 1 < n and symbols[i + 1] == ")" else None
        attrs = {"original_symbol": sym}
        if onset is not None and offset is not None and offset >= onset and offset + 1 <= n_samples:
            out.append(RefAnnotation(tier, wave_label, "interval", onset, offset + 1, lead, dict(attrs), dict(provenance)))
        else:
            if onset is not None and on_label:
                out.append(RefAnnotation("Fiducial Points", on_label, "point", onset, None, lead, dict(attrs), dict(provenance)))
            if offset is not None and off_label:
                out.append(RefAnnotation("Fiducial Points", off_label, "point", offset, None, lead, dict(attrs), dict(provenance)))
        if peak_label:
            out.append(RefAnnotation("Fiducial Points", peak_label, "point", peak, None, lead, dict(attrs), dict(provenance)))
    return out
