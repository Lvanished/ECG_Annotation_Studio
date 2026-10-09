"""Snapshot export, segmentation masks, patient splits and round-trip import."""
from __future__ import annotations

import csv
import io
import json
import zipfile

import numpy as np

from app.services.exporter import MASK_OVERLAP, MASK_UNANNOTATED, MASK_UNCERTAIN, build_masks, patient_split


def test_mask_codes():
    anns = [
        {"tier": "P Wave", "label": "P_wave", "lead": "II", "start_sample": 10, "end_sample": 20, "attributes": {}},
        {"tier": "P Wave", "label": "U_like", "lead": "II", "start_sample": 15, "end_sample": 25, "attributes": {}},
        {"tier": "P Wave", "label": "P_wave", "lead": None, "start_sample": 40, "end_sample": 45,
         "attributes": {"uncertain": True}},
    ]
    dense, multi, unc, classes = build_masks(anns, ["I", "II"], 60, "P Wave")
    assert classes == ["P_wave", "U_like"]
    ii = dense[1]
    assert (ii[:10] == MASK_UNANNOTATED).all() and (ii[45:] == MASK_UNANNOTATED).all()
    assert (ii[10:15] == 1).all() and (ii[15:20] == MASK_OVERLAP).all() and (ii[20:25] == 2).all()
    assert (ii[25:40] == 0).all() and (ii[40:45] == MASK_UNCERTAIN).all()
    # lead I only has the global annotation -> coverage [40,45)
    assert (dense[0][:40] == MASK_UNANNOTATED).all() and (dense[0][40:45] == MASK_UNCERTAIN).all()
    assert multi[1, 17].tolist() == [1, 1] and unc[0, 42]


class _R:
    def __init__(self, i, p):
        self.id, self.patient_id = i, p


def test_patient_split_prevents_leakage():
    recs = [_R(f"r{i}", f"p{i // 3}") for i in range(30)] + [_R("x", None)]
    sp = patient_split(recs, {"train": 0.7, "val": 0.15, "test": 0.15}, seed=1)
    assert sp["leakage_check"] == "passed"
    for p in {r.patient_id for r in recs if r.patient_id}:
        assert len({sp["assignment"][r.id] for r in recs if r.patient_id == p}) == 1
    assert sp == patient_split(recs, {"train": 0.7, "val": 0.15, "test": 0.15}, seed=1)  # deterministic


def test_snapshot_export_and_roundtrip(client, imported):
    ludb = imported[("ludb", "1")]
    rid = ludb["id"]
    # add a manual morphology-annotated QRS in a lead to check it survives the round trip exactly
    m = client.post(f"/recordings/{rid}/annotations", json={
        "tier": "Morphology", "label": "fragmented", "lead": "V4", "start_sample": 1501, "end_sample": 1544,
        "attributes": {"note": "export test", "x_reader": "r1"}}).json()
    rec_ids = [rid, imported[("ludb", "2")]["id"], imported[("mitdb", "100")]["id"]]
    r = client.post("/exports", json={"name": "unit test", "recording_ids": rec_ids,
                                      "mask_tiers": ["P Wave", "QRS Complex", "T Wave", "Beat"]})
    assert r.status_code == 201, r.text
    snap = r.json()
    assert snap["version"] == "unit_test-v1" and snap["ontology_version"]
    assert snap["splits"]["leakage_check"] == "passed"
    assert client.post("/exports", json={"name": "x", "version": "unit_test-v1", "recording_ids": rec_ids}).status_code == 409
    z = client.get(f"/exports/{snap['version']}/download")
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    names = zf.namelist()
    root = "unit_test-v1/"
    for f in ("manifest.json", "annotations.json", "annotations.csv", "measurements.csv", "splits.json", "README.txt"):
        assert root + f in names
    manifest = json.loads(zf.read(root + "manifest.json"))
    assert manifest["annotation_revisions"][m["id"]] == 1
    assert manifest["label_statistics"]["total"] > 1000
    doc = json.loads(zf.read(root + "annotations.json"))
    ludb_entry = next(e for e in doc["recordings"] if e["recording"]["id"] == rid)
    npz = np.load(io.BytesIO(zf.read(root + ludb_entry["signal_file"])))
    assert npz["signal"].shape == (5000, 12) and float(npz["fs"]) == 500.0
    meta = json.loads(str(npz["meta_json"]))
    # mask agrees with annotation coordinates
    qrs_ii = [a for a in ludb_entry["annotations"] if a["label"] == "QRS_complex" and a["lead"] == "II"]
    classes = list(npz["classes_qrs_complex"])
    li = meta["leads"].index("II")
    for a in qrs_ii:
        assert (npz["mask_qrs_complex"][li, a["start_sample"]:a["end_sample"]] == classes.index("QRS_complex") + 1).all()
    assert npz["mask_qrs_complex"][li, 0] == MASK_UNANNOTATED  # LUDB does not annotate the first samples
    rows = list(csv.DictReader(io.StringIO(zf.read(root + "annotations.csv").decode())))
    row = next(x for x in rows if x["annotation_id"] == m["id"])
    assert row["start_sample"] == "1501" and row["end_sample"] == "1544" and json.loads(row["attributes"])["x_reader"] == "r1"
    meas = list(csv.DictReader(io.StringIO(zf.read(root + "measurements.csv").decode())))
    qrs_rows = [x for x in meas if x["measurement"] == "QRS duration" and x["lead"] == "II" and x["value"]]
    assert qrs_rows and all(x["samples"] and x["annotation_ids"] for x in qrs_rows)
    ver = client.get(f"/exports/{snap['version']}/verify").json()
    assert ver["immutable_integrity"] == "passed" and ver["corrupted_files"] == []
    # round trip 1: verify against live DB
    rep = client.post("/imports", params={"mode": "verify"},
                      files={"file": ("snap.zip", z.content, "application/zip")}).json()
    assert rep["ok"] is True, rep
    assert all(x["n_matched"] == x["n_exported"] for x in rep["recordings"])
    # round trip 2: import into new recordings (signals from the snapshot NPZ)
    rep2 = client.post("/imports", params={"mode": "new_recording"},
                       files={"file": ("snap.zip", z.content, "application/zip")}).json()
    assert rep2["ok"] is True, rep2
    item = next(x for x in rep2["recordings"] if x["name"] == "1")
    assert item["signal_identical_to_source"] is True and item["signal_origin"] == "snapshot npz"
    new_anns = client.get(f"/recordings/{item['new_recording_id']}/annotations").json()
    orig = {(a["tier"], a["label"], a["lead"], a["start_sample"], a["end_sample"]) for a in ludb_entry["annotations"]}
    back = {(a["tier"], a["label"], a["lead"], a["start_sample"], a["end_sample"]) for a in new_anns}
    assert orig == back
    assert all(a["source"] == "imported" and a["provenance"]["original_id"] for a in new_anns)
    # export is immutable even after edits
    client.delete(f"/annotations/{m['id']}", params={"revision": 1})
    ver2 = client.get(f"/exports/{snap['version']}/verify").json()
    assert ver2["immutable_integrity"] == "passed" and ver2["annotations_changed_since_export"] == 1
    rep3 = client.post("/imports", params={"mode": "verify"},
                       files={"file": ("snap.zip", z.content, "application/zip")}).json()
    assert rep3["ok"] is False  # the deleted annotation is reported, not silently ignored


def test_quick_export(client, ludb1):
    j = client.get(f"/recordings/{ludb1['id']}/export").json()
    assert j["interval_convention"] == "[start_sample, end_sample)"
    assert client.get(f"/recordings/{ludb1['id']}/export", params={"format": "csv"}).status_code == 200
