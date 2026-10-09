"""WFDB parsing, units, lead mapping and reference-annotation import on real PhysioNet data."""
from __future__ import annotations

from collections import Counter

import numpy as np
import wfdb

from conftest import PHYSIONET
from app.datasets import ADAPTERS
from app.datasets.base import normalize_lead
from app.datasets.mitdb import beat_reference


def test_ludb_header_and_units():
    p = ADAPTERS["ludb"].parse(PHYSIONET / "ludb", "1")
    hdr = wfdb.rdheader(str(PHYSIONET / "ludb" / "data" / "1"))
    assert p.fs == 500.0 == hdr.fs
    assert p.signal.shape == (hdr.sig_len, 12) == (5000, 12)
    assert p.leads == ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
    assert p.original_units == ["mV"] * 12
    assert p.patient_id == "ludb-1"
    assert p.meta["sex"] == "F" and p.meta["age"] == "51"


def test_voltage_conversion_matches_adc_formula():
    """physical = (digital - baseline) / gain, independently recomputed from the raw digital samples."""
    root = PHYSIONET / "mitdb"
    rec_d = wfdb.rdrecord(str(root / "100"), physical=False, sampto=3600)
    p = ADAPTERS["mitdb"].parse(root, "100")
    for ch in range(2):
        manual = (rec_d.d_signal[:, ch].astype(float) - rec_d.baseline[ch]) / rec_d.adc_gain[ch]
        np.testing.assert_allclose(p.signal[:3600, ch], manual, atol=1e-5)
    assert p.fs == 360.0 and p.signal.shape == (650000, 2) and p.leads == ["MLII", "V5"]


def test_lead_alias_mapping():
    assert [normalize_lead(x) for x in ["i", "avr", "AVL", "v6", "MLII"]] == ["I", "aVR", "aVL", "V6", "MLII"]


def test_ludb_reference_annotations_per_lead():
    p = ADAPTERS["ludb"].parse(PHYSIONET / "ludb", "1")
    raw = wfdb.rdann(str(PHYSIONET / "ludb" / "data" / "1"), "ii")
    n_qrs_raw = sum(1 for s in raw.symbol if s == "N")
    ii = [a for a in p.annotations if a.lead == "II"]
    qrs = [a for a in ii if a.label == "QRS_complex"]
    assert len([a for a in ii if a.label == "R_peak"]) == n_qrs_raw
    assert len(qrs) == n_qrs_raw  # all QRS complexes in record 1 have both boundaries
    # half-open conversion: end = inclusive offset + 1
    syms, samp = list(raw.symbol), list(raw.sample)
    k = syms.index("N")
    assert (qrs[0].start, qrs[0].end) == (samp[k - 1], samp[k + 1] + 1)
    rhythm = [a for a in p.annotations if a.tier == "Rhythm"]
    assert rhythm[0].label == "sinus_bradycardia" and rhythm[0].lead is None and rhythm[0].end == 5000


def test_mitdb_beats_and_rhythm():
    p = ADAPTERS["mitdb"].parse(PHYSIONET / "mitdb", "100")
    c = Counter(a.label for a in p.annotations if a.tier == "Beat")
    ref_samples, ref_syms = beat_reference(PHYSIONET / "mitdb", "100")
    assert sum(c.values()) == len(ref_samples) == 2273
    assert c["normal_beat"] == ref_syms.count("N") and c["PAC"] == ref_syms.count("A")
    assert all(a.lead is None for a in p.annotations)
    assert [a.label for a in p.annotations if a.tier == "Rhythm"] == ["sinus_rhythm"]


def test_qtdb_global_boundaries():
    p = ADAPTERS["qtdb"].parse(PHYSIONET / "qtdb", "sel100")
    assert p.fs == 250.0 and p.signal.shape == (225000, 2)
    waves = [a for a in p.annotations if a.tier in ("P Wave", "QRS Complex")]
    assert waves and all(a.lead is None for a in waves)
    # QTDB q1c lacks T onsets -> T peak/offset points, never invented T intervals
    assert not any(a.label == "T_wave" for a in p.annotations)
    assert sum(a.label == "T_offset" for a in p.annotations) == 30


def test_import_registers_recordings(client, imported):
    rec = imported[("ludb", "1")]
    assert rec["n_samples"] == 5000 and rec["fs"] == 500 and len(rec["leads"]) == 12
    assert rec["annotation_count"] > 300
    ds = {d["id"]: d for d in client.get("/datasets").json()}
    assert ds["ludb"]["license"].startswith("Open Data Commons Attribution")
    assert ds["mitdb"]["recording_count"] == 1
    anns = client.get(f"/recordings/{rec['id']}/annotations", params={"source": "reference"}).json()
    assert len(anns) >= 384 and all(a["review_status"] == "reviewed" for a in anns)
    assert all(a["provenance"]["dataset"] == "ludb" and a["provenance"]["file"] for a in anns)
    # idempotent import
    again = client.post("/datasets/ludb/import", json={"records": ["1"]}).json()["ludb"]
    assert again["already_present"] == ["1"]


def test_waveform_chunk_is_exact(client, mitdb100):
    rid = mitdb100["id"]
    p = ADAPTERS["mitdb"].parse(PHYSIONET / "mitdb", "100")
    raw = client.get(f"/recordings/{rid}/chunk", params={"bucket": 1, "index": 3, "leads": "MLII"}).json()
    assert raw["start"] == 3072 and raw["end"] == 4096
    np.testing.assert_allclose(raw["leads"]["MLII"]["values"], p.signal[3072:4096, 0], atol=1e-5)
    env = client.get(f"/recordings/{rid}/chunk", params={"bucket": 64, "index": 2, "leads": "MLII,V5"}).json()
    seg = p.signal[2 * 65536: 3 * 65536, 1].reshape(-1, 64)
    np.testing.assert_allclose(env["leads"]["V5"]["min"], seg.min(axis=1), atol=1e-5)
    np.testing.assert_allclose(env["leads"]["V5"]["max"], seg.max(axis=1), atol=1e-5)
    last = client.get(f"/recordings/{rid}/chunk", params={"bucket": 64, "index": 9, "leads": "MLII"}).json()
    assert last["end"] == 650000 and len(last["leads"]["MLII"]["min"]) == int(np.ceil((650000 - 9 * 65536) / 64))
    assert client.get(f"/recordings/{rid}/chunk", params={"leads": "XX"}).status_code == 422


def test_quality_indicators(client, ludb1):
    q = client.get(f"/recordings/{ludb1['id']}/quality", params={"leads": "II"}).json()["leads"]["II"]
    assert 0 <= q["flatline_fraction"] <= 1 and q["amplitude_range_mv"] > 0.3
