import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import synth
from titanium_platform import __version__
from titanium_platform.api.app import create_app

CELLS = {"r1c1": (200, 60, 60), "r1c2": (60, 200, 60), "r2c1": (60, 60, 200), "r2c2": (200, 200, 60)}


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    app.state.store.set_setting("allow_non_raw_photos", True)   # tests upload PNG renders; real use requires RAW
    with TestClient(app) as c:
        yield c
    app.state.store.close()


def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def setup(client) -> dict:
    prof = client.post("/api/profiles", json={"name": "MOPA", "pulse_width": 200, "line_interval": 0.025, "passes": 1}).json()
    stand = client.post("/api/setups", json={"name": "Rig", "camera": "cam", "lighting": "LED", "angle": "90", "reference_chart": "ColorChecker Classic"}).json()
    client.put("/api/marker-layer", json={"power": 20, "frequency": 60, "speed": 300})
    return {"profile": prof, "stand": stand}


def test_version_health_and_ui_fallback(client):
    assert client.get("/api/version").json()["version"] == __version__
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["kind"] == "not_found"


def test_profile_crud_and_error_mapping(client):
    r = client.post("/api/profiles", json={"name": " ", "pulse_width": 200, "line_interval": 0.025, "passes": 1})
    assert r.status_code == 422 and "name" in r.json()["error"]
    assert client.post("/api/profiles", json={"name": "x"}).status_code == 422          # schema error
    p = client.post("/api/profiles", json={"name": "A", "pulse_width": 200, "line_interval": 0.025, "passes": 1}).json()
    r = client.patch(f"/api/profiles/{p['id']}", json={"pulse_width": 250})
    assert r.status_code == 422 and "new version" in r.json()["error"]
    v2 = client.patch(f"/api/profiles/{p['id']}", json={"pulse_width": 250, "confirm_new_version": True}).json()
    assert v2["version"] == 2 and v2["id"] != p["id"]
    assert client.get("/api/profiles/9999").status_code == 404
    assert client.delete(f"/api/profiles/{p['id']}").status_code == 204


def test_a_linked_profile_cannot_be_deleted(client):
    s = setup(client)
    r = client.post("/api/plates", json={"profile_id": s["profile"]["id"], "powers": "10 20", "frequencies": "40 80", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1})
    assert r.status_code == 201
    d = client.delete(f"/api/profiles/{s['profile']['id']}")
    assert d.status_code == 409 and d.json()["kind"] == "protected"


def test_rules_start_unset_and_agreeing_needs_thresholds(client):
    s = setup(client)
    pid = s["profile"]["id"]
    assert client.get(f"/api/profiles/{pid}/rules").json() == {"repeat_threshold": None, "delta_tolerance": None, "variance_threshold": None, "criteria_agreed": False}
    assert client.put(f"/api/profiles/{pid}/rules", json={"criteria_agreed": True}).status_code == 422
    r = client.put(f"/api/profiles/{pid}/rules", json={"repeat_threshold": 2, "delta_tolerance": 6, "variance_threshold": 5, "criteria_agreed": True})
    assert r.status_code == 200 and r.json()["criteria_agreed"] is True


def upload_pair(client, s, lbrn, photo, **form):
    data = {"profile_id": s["profile"]["id"], "stand_id": s["stand"]["id"], "context": json.dumps(form.pop("context", {})), **form}
    return client.post("/api/pairs", data=data, files={"lightburn": ("plate.lbrn2", lbrn), "photo": ("plate.png", photo)})


def test_uploads_are_validated(client):
    s = setup(client)
    base = {"profile_id": s["profile"]["id"], "stand_id": s["stand"]["id"]}
    assert client.post("/api/pairs", data=base).status_code == 422                     # no files
    r = client.post("/api/pairs", data=base, files={"lightburn": ("a.lbrn2", b""), "photo": ("p.png", b"x")})
    assert r.status_code == 422 and "empty" in json.dumps(r.json())
    r = client.post("/api/pairs", data=base, files={"lightburn": ("a.txt", b"x"), "photo": ("p.png", b"x")})
    assert r.status_code == 422 and "lbrn" in r.json()["error"]
    r = client.post("/api/pairs", data={**base, "context": "{bad"}, files={"lightburn": ("a.lbrn2", b"x"), "photo": ("p.png", b"x")})
    assert r.status_code == 422 and "JSON" in r.json()["error"]


def test_the_whole_loop_over_http_plate_to_observation_to_report_to_proposal(client):
    s = setup(client)
    pid = s["profile"]["id"]
    client.put(f"/api/profiles/{pid}/rules", json={"repeat_threshold": 2, "delta_tolerance": 6, "variance_threshold": 5})
    plates = client.post("/api/plates", json={"profile_id": pid, "powers": "10 20", "frequencies": "40 80", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()
    assert len(plates) == 1
    plan = client.get(f"/api/plans/{plates[0]['plan_id']}").json()
    assert plan["mode"] == "Calibration plate" and plan["markers"]["identifier"] == plates[0]["experiment_id"] and "rects" not in json.dumps(plan["markers"])
    lbrn = client.get(f"/api/plans/{plates[0]['plan_id']}/export.lbrn2")
    assert lbrn.status_code == 200 and b"TCE1:" + plates[0]["experiment_id"].encode() in lbrn.content
    assert 'filename="Plate_' in lbrn.headers["content-disposition"]

    full = __import__("titanium_platform.plans", fromlist=["x"])
    st = client.app.state.store
    plan_full = full.get_plan(st, plates[0]["plan_id"])
    pair = upload_pair(client, s, lbrn.content, png(synth.plate_photo(plan_full, CELLS, gains=(0.9, 0.97, 1.08)))).json()
    assert pair["status"] == "Awaiting check" and "photo_path" not in pair and "lightburn_path" not in pair

    checked = client.post(f"/api/pairs/{pair['id']}/check", json={}).json()
    assert checked["status"] == "Ready to accept" and checked["check"]["alignment"]["method"] == "markers"
    assert client.post(f"/api/pairs/{pair['id']}/accept").status_code == 422             # masks not reviewed yet
    overlay = client.get(f"/api/pairs/{pair['id']}/overlay.png")
    assert overlay.status_code == 200 and overlay.headers["content-type"] == "image/png" and overlay.content[:4] == b"\x89PNG"
    assert client.post(f"/api/pairs/{pair['id']}/review-masks").status_code == 200
    accepted = client.post(f"/api/pairs/{pair['id']}/accept").json()
    assert len(accepted["observation_ids"]) == 4 and accepted["pair"]["status"] == "Accepted"
    assert client.delete(f"/api/pairs/{pair['id']}").status_code == 422                 # protected

    knowledge = client.get(f"/api/profiles/{pid}/knowledge").json()
    assert len(knowledge) == 4 and {k["stage"] for k in knowledge} == {"measured"}
    m = client.get(f"/api/profiles/{pid}/map").json()
    assert len(m["samples"]) == 4 and not any(s_["available"] for s_ in m["samples"])   # one engraving: no estimates yet
    assert client.post(f"/api/profiles/{pid}/predict", json={"lab": [50, 0, 0]}).json()["available"] is False

    report = client.get(f"/api/pairs/{pair['id']}/report").json()
    assert report["mode"] == "Calibration plate" and len(report["rows"]) == 4
    prop = client.post("/api/designer/propose", json={"profile_id": pid, "size": 4}).json()
    assert len(prop["parameters"]) == 4 and prop["model"]["gaussian_process"] is True
    again = client.post("/api/designer/propose", json={"profile_id": pid, "size": 4}).json()
    assert again["id"] == prop["id"]
    made = client.post(f"/api/designer/proposals/{prop['id']}/plates", json={"cell_width": 5, "cell_height": 4, "gap": 1})
    assert made.status_code == 201 and sum(p["cells"] for p in made.json()) >= 4


def test_a_photo_without_a_chart_is_rejected_by_the_check_and_cannot_be_accepted(client):
    s = setup(client)
    pid = s["profile"]["id"]
    plates = client.post("/api/plates", json={"profile_id": pid, "powers": "10 20", "frequencies": "40 80", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()
    from titanium_platform import plans
    plan_full = plans.get_plan(client.app.state.store, plates[0]["plan_id"])
    lbrn = client.get(f"/api/plans/{plates[0]['plan_id']}/export.lbrn2").content
    pair = upload_pair(client, s, lbrn, png(synth.plate_photo(plan_full, CELLS, with_chart=False))).json()
    checked = client.post(f"/api/pairs/{pair['id']}/check", json={}).json()
    assert checked["status"] == "Needs correction" and not checked["check"]["chart"]["detected"]
    r = client.post(f"/api/pairs/{pair['id']}/review-masks")   # nothing is aligned, so there is nothing to review
    assert r.status_code == 422 and "align" in r.json()["error"]
    assert client.post(f"/api/pairs/{pair['id']}/accept").status_code == 422
    assert client.get(f"/api/pairs/{pair['id']}/report").status_code == 422
    assert client.app.state.store.one("SELECT COUNT(*) AS n FROM observation")["n"] == 0


def test_exporting_a_draft_plan_is_refused(client):
    s = setup(client)
    st = client.app.state.store
    st.execute("INSERT INTO plan(name,mode,status,profile_id,markers,data_json,created_at) VALUES ('d','Discrete color engraving','Draft',?,0,'{\"layers\":[]}','t')", (s["profile"]["id"],))
    r = client.get("/api/plans/1/export.lbrn2")
    assert r.status_code == 422 and "draft" in r.json()["error"]


def test_deleting_a_plate_plan_removes_the_plate_with_it(client):
    s = setup(client)
    plates = client.post("/api/plates", json={"profile_id": s["profile"]["id"], "powers": "10", "frequencies": "40", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()
    assert client.delete(f"/api/plans/{plates[0]['plan_id']}").status_code == 204
    st = client.app.state.store
    assert st.one("SELECT COUNT(*) AS n FROM plate")["n"] == 0 and st.one("SELECT COUNT(*) AS n FROM plan")["n"] == 0
    assert client.delete(f"/api/plans/{plates[0]['plan_id']}").status_code == 404


def test_the_photo_preview_is_a_downscaled_png_of_the_uploaded_photo(client):
    s = setup(client)
    big = synth.scene(width=3000, height=2000)
    pair = upload_pair(client, s, b'<LightBurnProject><Notes Notes=""/></LightBurnProject>', png(big)).json()
    r = client.get(f"/api/pairs/{pair['id']}/photo.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) == 1400 and abs(img.shape[1] / img.shape[0] - 1.5) < 0.01
    assert client.get("/api/pairs/999/photo.png").status_code == 404

