"""R-peak detection on real MIT-BIH data and the prediction review workflow."""
from __future__ import annotations

import numpy as np

from conftest import PHYSIONET
from app.datasets.mitdb import beat_reference
from app.signal.rpeak import match_peaks, segment_beats


def test_rpeak_detection_against_mitdb_reference(client, mitdb100):
    rid = mitdb100["id"]
    run = client.post(f"/recordings/{rid}/detect-r", json={"lead": "MLII"}).json()
    assert run["algorithm"] == "scipy_pan_tompkins" and run["algorithm_version"]
    assert run["parameters"]["bandpass_hz"] == [5.0, 15.0]
    det = np.array([p["start_sample"] for p in run["predictions"]])
    ref, _ = beat_reference(PHYSIONET / "mitdb", "100")
    tp, fp, fn = match_peaks(np.array(ref), det, int(0.150 * 360))
    se, ppv = tp / (tp + fn), tp / (tp + fp)
    assert se > 0.99 and ppv > 0.99, (tp, fp, fn)
    assert all(p["status"] == "pending" and p["tier"] == "Fiducial Points" for p in run["predictions"])
    # predictions are not annotations
    anns = client.get(f"/recordings/{rid}/annotations", params={"source": "algorithm"}).json()
    assert anns == []


def test_xqrs_alternative(client, mitdb100):
    run = client.post(f"/recordings/{mitdb100['id']}/detect-r",
                      json={"lead": "MLII", "start_sample": 0, "end_sample": 36000, "algorithm": "wfdb_xqrs"}).json()
    assert run["algorithm"] == "wfdb_xqrs" and 100 < run["n_predictions"] < 140


def test_accept_modify_reject_and_range(client, mitdb100):
    rid = mitdb100["id"]
    run = client.post(f"/recordings/{rid}/detect-r", json={"lead": "MLII", "start_sample": 0, "end_sample": 7200}).json()
    preds = run["predictions"]
    a = client.post(f"/predictions/{preds[0]['id']}/accept", json={}).json()
    ann = a["annotation"]
    assert a["prediction"]["status"] == "accepted" and ann["source"] == "algorithm"
    assert ann["provenance"]["algorithm"] == "scipy_pan_tompkins" and ann["provenance"]["run_id"] == run["id"]
    assert ann["provenance"]["modified_by_reviewer"] is False and ann["start_sample"] == preds[0]["start_sample"]
    m = client.post(f"/predictions/{preds[1]['id']}/accept", json={"start_sample": preds[1]["start_sample"] + 3}).json()
    assert m["prediction"]["status"] == "modified"
    assert m["annotation"]["provenance"]["original_start_sample"] == preds[1]["start_sample"]
    assert m["annotation"]["start_sample"] == preds[1]["start_sample"] + 3
    rj = client.post(f"/predictions/{preds[2]['id']}/reject").json()
    assert rj["status"] == "rejected"
    assert client.post(f"/predictions/{preds[2]['id']}/accept", json={}).status_code == 409
    # accept all in selection: one already accepted, rest accepted, nothing overwritten
    rng = client.post(f"/prediction-runs/{run['id']}/accept-range",
                      json={"start_sample": 0, "end_sample": preds[5]["start_sample"] + 1}).json()
    assert len(rng["accepted"]) == 3  # preds 3, 4, 5
    # a second run over the same window cannot duplicate accepted annotations
    run2 = client.post(f"/recordings/{rid}/detect-r", json={"lead": "MLII", "start_sample": 0, "end_sample": 7200}).json()
    dup = client.post(f"/predictions/{run2['predictions'][0]['id']}/accept", json={})
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "duplicate_annotation"
    runs = client.get(f"/recordings/{rid}/prediction-runs").json()
    assert any(r["id"] == run["id"] and r["counts"].get("accepted", 0) == 4 for r in runs)


def test_predictions_never_overwrite_reviewed(client, ludb1):
    rid = ludb1["id"]
    run = client.post(f"/recordings/{rid}/detect-r", json={"lead": "II"}).json()
    res = client.post(f"/predictions/{run['predictions'][3]['id']}/accept", json={})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "conflicts_with_reviewed"
    rng = client.post(f"/prediction-runs/{run['id']}/accept-range", json={"start_sample": 0, "end_sample": 5000}).json()
    assert rng["accepted"] == [] or all(a["start_sample"] < 400 or a["start_sample"] > 4600 for a in rng["accepted"])


def test_segmentation_and_experimental_delineation(client, ludb1):
    rid = ludb1["id"]
    run = client.post(f"/recordings/{rid}/detect-r", json={"lead": "II"}).json()
    seg = client.post(f"/recordings/{rid}/segment-beats", json={"source_run_id": run["id"]}).json()
    regions = [(p["start_sample"], p["end_sample"]) for p in seg["predictions"]]
    assert seg["parameters"]["split_fraction"] == 0.6
    assert all(regions[i][1] == regions[i + 1][0] for i in range(len(regions) - 1))  # contiguous, non-overlapping
    d = client.post(f"/recordings/{rid}/delineate", json={"lead": "II"}).json()
    assert d["experimental"] is True and d["algorithm"].startswith("experimental")
    assert {p["label"] for p in d["predictions"]} >= {"QRS_complex"}


def test_segment_beats_definition():
    segs = segment_beats(np.array([100, 300, 600]), 1000, 0.6)
    assert segs == [(20, 220, 100), (220, 480, 300), (480, 780, 600)]
