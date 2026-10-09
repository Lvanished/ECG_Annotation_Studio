"""Annotation CRUD, validation, concurrency, history and batch atomicity."""
from __future__ import annotations


def _create(client, rid, **kw):
    body = {"tier": "Fiducial Points", "label": "R_peak", "lead": "II", "start_sample": 1000, **kw}
    return client.post(f"/recordings/{rid}/annotations", json=body)


def test_crud_and_history(client, ludb1):
    rid = ludb1["id"]
    r = _create(client, rid, start_sample=1234, attributes={"note": "manual"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["kind"] == "point" and a["revision"] == 1 and a["source"] == "manual" and a["ontology_version"]
    u = client.put(f"/annotations/{a['id']}", json={**{k: a[k] for k in ("tier", "label", "lead", "attributes")},
                                                    "start_sample": 1240, "revision": 1})
    assert u.status_code == 200 and u.json()["revision"] == 2 and u.json()["start_sample"] == 1240
    stale = client.put(f"/annotations/{a['id']}", json={"tier": "Fiducial Points", "label": "R_peak", "lead": "II",
                                                        "start_sample": 1250, "revision": 1})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "revision_conflict"
    assert client.delete(f"/annotations/{a['id']}", params={"revision": 1}).status_code == 409
    assert client.delete(f"/annotations/{a['id']}", params={"revision": 2}).status_code == 200
    hist = client.get(f"/annotations/{a['id']}/history").json()
    assert [h["operation"] for h in hist] == ["create", "update", "delete"]
    assert hist[0]["snapshot"]["start_sample"] == 1234 and hist[1]["snapshot"]["start_sample"] == 1240
    ids = {x["id"] for x in client.get(f"/recordings/{rid}/annotations").json()}
    assert a["id"] not in ids
    deleted = client.get(f"/recordings/{rid}/annotations", params={"include_deleted": True}).json()
    assert any(x["id"] == a["id"] for x in deleted)  # soft delete keeps an auditable row


def test_ontology_validation(client, ludb1):
    rid = ludb1["id"]
    assert _create(client, rid, label="NotALabel").json()["detail"]["code"] == "ontology_violation"
    assert _create(client, rid, tier="P Wave", label="R_peak", end_sample=1100).status_code == 422
    assert _create(client, rid, tier="P Wave", label="P_wave").status_code == 422  # interval tier needs interval
    bad_attr = _create(client, rid, tier="QRS Complex", label="QRS_complex", start_sample=10, end_sample=20,
                       attributes={"morphology": "zigzag"})
    assert bad_attr.status_code == 422 and "morphology" in bad_attr.json()["detail"]["message"]
    assert _create(client, rid, start_sample=5000).json()["detail"]["code"] == "out_of_bounds"
    assert _create(client, rid, lead="V9").json()["detail"]["code"] == "invalid_lead"
    assert _create(client, rid, tier="QRS Complex", label="QRS_complex", start_sample=20, end_sample=20).status_code == 422
    ok = _create(client, rid, tier="QRS Complex", label="QRS_complex", lead="V1", start_sample=4990, end_sample=5000,
                 attributes={"morphology": "notched", "uncertain": True, "x_reader": "A"})
    assert ok.status_code == 201, ok.text


def test_overlap_policy_and_duplicates(client, ludb1):
    rid = ludb1["id"]
    anns = client.get(f"/recordings/{rid}/annotations", params={"tier": "QRS Complex"}).json()
    ref = next(a for a in anns if a["lead"] == "II")
    r = _create(client, rid, tier="QRS Complex", label="QRS_complex", start_sample=ref["start_sample"] + 2,
                end_sample=ref["end_sample"] + 5)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "overlap_violation"
    # half-open: an interval starting exactly at the previous end is not an overlap
    r2 = _create(client, rid, tier="QRS Complex", label="QRS_complex", start_sample=ref["end_sample"],
                 end_sample=ref["end_sample"] + 3)
    assert r2.status_code == 201, r2.text
    p = _create(client, rid, start_sample=3333, lead="V2")
    assert p.status_code == 201
    dup = _create(client, rid, start_sample=3333, lead="V2")
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "duplicate_point"
    # overlapping annotations across *different* tiers are allowed
    assert _create(client, rid, tier="Morphology", label="notched", start_sample=ref["start_sample"],
                   end_sample=ref["end_sample"]).status_code == 201


def test_reviewed_annotations_are_protected(client, ludb1):
    rid = ludb1["id"]
    ref = next(a for a in client.get(f"/recordings/{rid}/annotations", params={"tier": "P Wave"}).json()
               if a["lead"] == "I")
    body = {k: ref[k] for k in ("tier", "label", "lead", "start_sample", "end_sample", "attributes", "review_status")}
    r = client.put(f"/annotations/{ref['id']}", json={**body, "end_sample": ref["end_sample"] + 1, "revision": 1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewed_protected"
    assert client.delete(f"/annotations/{ref['id']}", params={"revision": 1}).json()["detail"]["code"] == "reviewed_protected"
    r = client.put(f"/annotations/{ref['id']}", json={**body, "end_sample": ref["end_sample"] + 1, "revision": 1,
                                                      "confirm_reviewed_change": True})
    assert r.status_code == 200 and r.json()["revision"] == 2
    hist = client.get(f"/annotations/{ref['id']}/history").json()
    assert hist[0]["snapshot"]["end_sample"] == ref["end_sample"]  # original reviewed version preserved


def test_batch_is_atomic(client, ludb1):
    rid = ludb1["id"]
    before = len(client.get(f"/recordings/{rid}/annotations").json())
    ops = [
        {"op": "create", "client_id": "tmp-1", "data": {"tier": "Fiducial Points", "label": "J_point", "lead": "V3",
                                                        "start_sample": 777}},
        {"op": "create", "client_id": "tmp-2", "data": {"tier": "Fiducial Points", "label": "BOGUS", "lead": "V3",
                                                        "start_sample": 778}},
    ]
    r = client.post(f"/recordings/{rid}/annotations/batch", json={"operations": ops})
    assert r.status_code == 422 and r.json()["detail"]["op_index"] == 1
    assert len(client.get(f"/recordings/{rid}/annotations").json()) == before  # first op rolled back
    ops[1]["data"]["label"] = "T_peak"
    r = client.post(f"/recordings/{rid}/annotations/batch", json={"operations": ops})
    assert r.status_code == 200, r.text
    res = r.json()
    assert set(res["id_map"]) == {"tmp-1", "tmp-2"}
    a1 = next(a for a in res["created"] if a["id"] == res["id_map"]["tmp-1"])
    ops2 = [{"op": "update", "id": a1["id"], "revision": 1,
             "data": {"tier": "Fiducial Points", "label": "J_point", "lead": "V3", "start_sample": 780}},
            {"op": "delete", "id": res["id_map"]["tmp-2"], "revision": 1}]
    r = client.post(f"/recordings/{rid}/annotations/batch", json={"operations": ops2})
    assert r.status_code == 200 and r.json()["updated"][0]["start_sample"] == 780
    hist = client.get(f"/annotations/{a1['id']}/history").json()
    assert hist[-1]["batch_id"] == r.json()["batch_id"]


def test_beat_id_assignment_and_relationships(client, ludb1):
    rid = ludb1["id"]
    beat = _create(client, rid, tier="Beat", label="beat_region", lead=None, start_sample=2000, end_sample=2400).json()
    assert beat["beat_id"] == beat["id"]
    child = _create(client, rid, label="S_peak", lead="aVF", start_sample=2100).json()
    assert child["beat_id"] == beat["id"]
    rel = client.post(f"/recordings/{rid}/relationships",
                      json={"source_id": child["id"], "target_id": beat["id"], "relation_type": "part_of"})
    assert rel.status_code == 201
    bad = client.post(f"/recordings/{rid}/relationships",
                      json={"source_id": child["id"], "target_id": beat["id"], "relation_type": "R_peak"})
    assert bad.status_code == 422
    assert len(client.get(f"/recordings/{rid}/relationships").json()) == 1


def test_ontology_extension(client, ludb1):
    v0 = client.get("/ontology").json()["version"]
    t = client.post("/tiers", json={"name": "Pacing Spikes", "kind": "point", "scope": "lead", "color": "#123456",
                                    "allow_free_labels": False})
    assert t.status_code == 201
    lb = client.post("/ontology/labels", json={"code": "pacing_spike", "name": "Pacing spike", "level": "L4",
                                               "geometry": "point", "tiers": ["Pacing Spikes"],
                                               "attributes_schema": {"chamber": {"type": "enum", "values": ["A", "V"]}}})
    assert lb.status_code == 201
    onto = client.get("/ontology").json()
    assert onto["version"] != v0 and any(x["code"] == "pacing_spike" for x in onto["labels"])
    r = _create(client, ludb1["id"], tier="Pacing Spikes", label="pacing_spike", start_sample=50,
                attributes={"chamber": "V"})
    assert r.status_code == 201 and r.json()["ontology_version"] == onto["version"]
    assert _create(client, ludb1["id"], tier="Pacing Spikes", label="pacing_spike", start_sample=51,
                   attributes={"chamber": "X"}).status_code == 422
    assert client.post("/ontology/labels", json={"code": "x1", "name": "x", "level": "L4",
                                                 "parent_code": "nope"}).status_code == 422
    v = client.get(f"/recordings/{ludb1['id']}/validate").json()
    assert "issues" in v
