"""Measurements derived from annotation coordinates on a real LUDB record."""
from __future__ import annotations

import numpy as np

from conftest import PHYSIONET
from app.datasets import ADAPTERS
from app.signal.measurements import compute_measurements


def _ann(i, tier, label, lead, s, e=None):
    return {"id": f"a{i}", "tier": tier, "label": label, "lead": lead, "start_sample": s, "end_sample": e}


def test_intervals_from_annotations():
    p = ADAPTERS["ludb"].parse(PHYSIONET / "ludb", "1")
    fs = p.fs
    anns = [
        _ann(1, "Fiducial Points", "R_peak", "II", 1000), _ann(2, "Fiducial Points", "R_peak", "II", 1500),
        _ann(3, "QRS Complex", "QRS_complex", "II", 1480, 1530),
        _ann(4, "P Wave", "P_wave", "II", 1380, 1430),
        _ann(5, "T Wave", "T_wave", "II", 1600, 1720),
    ]
    m = compute_measurements(anns, p.signal, fs, "II", 1)
    b = {v["name"]: v for v in m["beats"][1]["values"]}
    assert b["RR"]["value"] == 1000.0 and b["RR"]["samples"] == [1000, 1500]
    assert b["QRS duration"]["value"] == 100.0 and b["QRS duration"]["annotation_ids"] == ["a3"]
    assert b["PR interval"]["value"] == 200.0 and b["PR interval"]["samples"] == [1380, 1480]
    assert b["QT interval"]["value"] == 480.0 and b["QT interval"]["samples"] == [1480, 1720]
    assert abs(b["QTc (Bazett)"]["value"] - 480.0) < 1e-9
    base = float(np.median(p.signal[1430:1480, 1]))
    assert abs(b["ST deviation (J+60ms)"]["value"] - (p.signal[1529 + 30, 1] - base)) < 1e-6
    assert b["ST deviation (J+60ms)"]["experimental"] is True
    first = {v["name"]: v for v in m["beats"][0]["values"]}
    assert first["RR"]["value"] is None and first["RR"]["reason"].startswith("N/A")
    assert first["QRS duration"]["value"] is None and first["PR interval"]["value"] is None


def test_reference_measurements_plausible(client, ludb1):
    m = client.post(f"/recordings/{ludb1['id']}/measurements", json={"lead": "II"}).json()
    s = m["summary"]
    assert m["anchor"] == "R_peak"
    assert 60 <= s["QRS duration"]["median"] <= 140
    assert 100 <= s["PR interval"]["median"] <= 300
    assert 300 <= s["QT interval"]["median"] <= 550
    assert 40 <= s["HR"]["median"] <= 70  # LUDB record 1 is labelled sinus bradycardia
