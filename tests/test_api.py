import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import synth
from titanium_platform import __version__
from titanium_platform.api.app import create_app

CELLS = {"r1c1": (200, 60, 60), "r1c2": (60, 200, 60), "r2c1": (60, 60, 200), "r2c2": (200, 200, 60)}
JOB = {"pulse_width": 200, "line_interval": 0.025, "passes": 1}


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
    laser = client.post("/api/devices/from-template", json={"template": "jpt-ydflp-e-60-m7-m-r"}).json()
    lens = client.post("/api/lenses", json={"name": "F-Theta 174", "focal_length_mm": 174, "field_mm": 170}).json()
    client.put(f"/api/devices/{laser['id']}/lens", json={"lens_id": lens["id"]})
    stand = client.post("/api/setups", json={"name": "Rig", "camera": "cam", "lighting": "LED", "angle": "90", "reference_chart": "ColorChecker Classic"}).json()
    material = client.post("/api/materials", json={"name": "Grade 2 sheet", "grade": "Grade 2", "thickness_mm": 1, "surface": "brushed"}).json()
    client.put("/api/marker-layer", json={"power": 20, "frequency": 60, "speed": 300})
    return {"laser": laser, "lens": lens, "setup": f"device_id={laser['id']}&lens_id={lens['id']}", "stand": stand, "material": material}


def test_version_health_and_ui_fallback(client):
    assert client.get("/api/version").json()["version"] == __version__
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["kind"] == "not_found"


def test_errors_are_mapped_and_laser_profiles_no_longer_exist(client):
    r = client.post("/api/materials", json={"name": " "})
    assert r.status_code == 422 and "name" in r.json()["error"]
    assert client.get("/api/profiles").status_code == 404 and client.post("/api/profiles", json={"name": "x"}).status_code in (404, 405)
    s = setup(client)
    assert client.get(f"/api/knowledge?device_id={s['laser']['id']}&lens_id=nonsense").json()["error"] == "choose the lens or mark it unknown"
    assert client.get(f"/api/knowledge?device_id={s['laser']['id']}").status_code == 422      # the lens is never assumed
    assert client.get(f"/api/knowledge?device_id={s['laser']['id']}&lens_id=unknown").json() == []


def test_a_laser_with_stored_plates_cannot_be_deleted(client):
    s = setup(client)
    r = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10 20", "frequencies": "40 80", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1})
    assert r.status_code == 201
    d = client.delete(f"/api/devices/{s['laser']['id']}")
    assert d.status_code == 409 and d.json()["kind"] == "protected"


def test_rules_start_unset_and_agreeing_needs_thresholds(client):
    s = setup(client)
    target = {"device_id": s["laser"]["id"], "lens_id": s["lens"]["id"]}
    assert client.get(f"/api/rules?{s['setup']}").json() == {"repeat_threshold": None, "delta_tolerance": None, "variance_threshold": None, "criteria_agreed": False}
    assert client.put("/api/rules", json={**target, "criteria_agreed": True}).status_code == 422
    r = client.put("/api/rules", json={**target, "repeat_threshold": 2, "delta_tolerance": 6, "variance_threshold": 5, "criteria_agreed": True})
    assert r.status_code == 200 and r.json()["criteria_agreed"] is True
    assert client.get(f"/api/rules?device_id={s['laser']['id']}&lens_id=unknown").json()["criteria_agreed"] is False   # another partition
    assert client.put("/api/rules", json={"device_id": s["laser"]["id"], "delta_tolerance": 6}).status_code == 422   # the lens is required


def upload_pair(client, s, lbrn, photo, **form):
    context = form.pop("context", {"material_id": s["material"]["id"]})
    data = {"device_id": s["laser"]["id"], "lens_id": str(s["lens"]["id"]), "stand_id": s["stand"]["id"], "context": json.dumps(context), **form}
    return client.post("/api/pairs", data=data, files={"lightburn": ("plate.lbrn2", lbrn), "photo": ("plate.png", photo)})


def test_every_photograph_names_its_rig_and_the_rig_names_its_chart_values(client):
    """REQ-009 AC2, DEC-025: the upload takes the rig used last when none is chosen; the rig's chart values can be
    replaced and reset to the published ones."""
    s = setup(client)
    lbrn = b'<LightBurnProject><Notes Notes=""/></LightBurnProject>'
    window = client.post("/api/setups", json={"name": "Window", "camera": "phone", "lighting": "daylight", "angle": "60",
                                              "reference_chart": "ColorChecker Classic"}).json()
    chosen = upload_pair(client, s, lbrn, png(synth.scene()), stand_id=window["id"]).json()
    assert chosen["stand_id"] == window["id"]
    data = {"device_id": s["laser"]["id"], "lens_id": "unknown", "context": json.dumps({"material_id": s["material"]["id"]})}
    as_last_time = client.post("/api/pairs", data=data, files={"lightburn": ("a.lbrn2", lbrn), "photo": ("p.png", png(synth.scene()))}).json()
    assert as_last_time["stand_id"] == window["id"]
    rigs = client.get("/api/setups").json()
    assert [(r["id"], r["last_used"], r["legacy"], r["chart_reference"]["published"]) for r in rigs] == [
        (s["stand"]["id"], False, False, True), (window["id"], True, False, True)]
    values = rigs[0]["chart_reference"]["patches_lab"]
    saved = client.put(f"/api/setups/{window['id']}/chart-reference",
                       json={"patches_lab": values, "white_point": "D50", "source": "X-Rite, D50"}).json()
    assert saved["chart_reference"]["white_point"] == "D50" and not saved["chart_reference"]["published"]
    bad = client.put(f"/api/setups/{window['id']}/chart-reference", json={"patches_lab": values[:3], "source": "x"})
    assert bad.status_code == 422 and "24 Lab triples" in bad.json()["error"]
    assert client.delete(f"/api/setups/{window['id']}/chart-reference").json()["chart_reference"]["published"]


def test_uploads_are_validated(client):
    s = setup(client)
    base = {"device_id": s["laser"]["id"], "lens_id": "unknown", "stand_id": s["stand"]["id"]}
    assert client.post("/api/pairs", data=base).status_code == 422                     # no files
    r = client.post("/api/pairs", data=base, files={"lightburn": ("a.lbrn2", b""), "photo": ("p.png", b"x")})
    assert r.status_code == 422 and "empty" in json.dumps(r.json())
    r = client.post("/api/pairs", data=base, files={"lightburn": ("a.txt", b"x"), "photo": ("p.png", b"x")})
    assert r.status_code == 422 and "lbrn" in r.json()["error"]
    r = client.post("/api/pairs", data={**base, "context": "{bad"}, files={"lightburn": ("a.lbrn2", b"x"), "photo": ("p.png", b"x")})
    assert r.status_code == 422 and "JSON" in r.json()["error"]
    r = client.post("/api/pairs", data={**base, "lens_id": "999"}, files={"lightburn": ("a.lbrn2", b"x"), "photo": ("p.png", b"x")})
    assert r.status_code == 404 and "lens 999" in r.json()["error"]


def test_the_whole_loop_over_http_plate_to_observation_to_report_to_proposal(client):
    s = setup(client)
    client.put("/api/rules", json={"device_id": s["laser"]["id"], "lens_id": s["lens"]["id"], "repeat_threshold": 2, "delta_tolerance": 6, "variance_threshold": 5})
    plates = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10 20", "frequencies": "40 80", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()
    assert len(plates) == 1
    plan = client.get(f"/api/plans/{plates[0]['plan_id']}").json()
    assert plan["mode"] == "Calibration plate" and plan["markers"]["identifier"] == plates[0]["experiment_id"] and "rects" not in json.dumps(plan["markers"])
    lbrn = client.get(f"/api/plans/{plates[0]['plan_id']}/export.lbrn2")
    assert lbrn.status_code == 200 and b"TCE1:" + plates[0]["experiment_id"].encode() in lbrn.content
    assert 'filename="Plate TCE-' in lbrn.headers["content-disposition"]

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
    layer_index = next(layer["index"] for layer in checked["check"]["layers"] if layer["measured_lab"] is not None)
    isolated = client.get(f"/api/pairs/{pair['id']}/overlay.png", params={"layer_index": layer_index, "visibility": "lifted"})
    assert isolated.status_code == 200 and isolated.content[:4] == b"\x89PNG" and isolated.content != overlay.content
    assert client.post(f"/api/pairs/{pair['id']}/review-masks").status_code == 200
    accepted = client.post(f"/api/pairs/{pair['id']}/accept").json()
    assert len(accepted["observation_ids"]) == 6 and accepted["pair"]["status"] == "Accepted"
    knowledge = client.get(f"/api/knowledge?{s['setup']}").json()
    assert len(knowledge) == 4 and {k["stage"] for k in knowledge} == {"measured"}       # the four cells; cleaning and markers never (DEC-027)
    m = client.get(f"/api/color-model?{s['setup']}").json()
    assert len(m["samples"]) == 4 and not any(s_["available"] for s_ in m["samples"])   # one engraving: no estimates yet
    assert client.post("/api/predict", json={"device_id": s["laser"]["id"], "lens_id": s["lens"]["id"], "lab": [50, 0, 0]}).json()["available"] is False

    report = client.get(f"/api/pairs/{pair['id']}/report").json()
    assert report["mode"] == "Calibration plate" and len(report["rows"]) == 6
    design = {"device_id": s["laser"]["id"], "lens_id": s["lens"]["id"], **JOB, "size": 4}
    assert client.post("/api/designer/propose", json={k: v for k, v in design.items() if k != "pulse_width"}).status_code == 422
    prop = client.post("/api/designer/propose", json=design).json()
    assert len(prop["parameters"]) == 4 and prop["model"]["gaussian_process"] is True
    again = client.post("/api/designer/propose", json=design).json()
    assert again["id"] == prop["id"] and prop["group"] == JOB
    assert [p["id"] for p in client.get(f"/api/designer/proposals?{s['setup']}").json()] == [prop["id"]]
    made = client.post(f"/api/designer/proposals/{prop['id']}/plates", json={"cell_width": 5, "cell_height": 4, "gap": 1})
    assert made.status_code == 201 and sum(p["cells"] for p in made.json()) >= 4

    stored_paths = st.one("SELECT lightburn_path,photo_path FROM pair WHERE id=?", (pair["id"],))
    assert client.delete(f"/api/pairs/{pair['id']}").status_code == 204
    assert all(not __import__("pathlib").Path(stored_paths[k]).exists() for k in ("lightburn_path", "photo_path"))
    assert not any(item["id"] == pair["id"] for item in client.get("/api/pairs").json())
    assert client.get(f"/api/pairs/{pair['id']}").status_code == 404
    assert st.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pair["id"],))["n"] == 6
    assert st.one("SELECT COUNT(*) AS n FROM observation o JOIN pair p ON p.id=o.pair_id WHERE p.status='Accepted'")["n"] == 0
    plan_id = plates[0]["plan_id"]
    assert client.delete(f"/api/plans/{plan_id}").status_code == 204
    assert st.one("SELECT status FROM plan WHERE id=?", (plan_id,))["status"] == "Deleted"
    assert st.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pair["id"],))["n"] == 6
    assert st.one("SELECT COUNT(*) AS n FROM audit WHERE action='plan_archived'")["n"] == 1


def test_a_system_plate_without_a_separate_chart_can_be_checked_and_accepted(client):
    s = setup(client)
    plates = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10 20", "frequencies": "40 80", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()
    from titanium_platform import plans
    plan_full = plans.get_plan(client.app.state.store, plates[0]["plan_id"])
    lbrn = client.get(f"/api/plans/{plates[0]['plan_id']}/export.lbrn2").content
    pair = upload_pair(client, s, lbrn, png(synth.plate_photo(plan_full, CELLS, with_chart=False))).json()
    checked = client.post(f"/api/pairs/{pair['id']}/check", json={}).json()
    assert checked["status"] == "Ready to accept" and not checked["check"]["chart"]["detected"]
    assert checked["check"]["color_measurement"]["mode"] == "raw_camera_relative"
    assert client.post(f"/api/pairs/{pair['id']}/review-masks").status_code == 200
    accepted = client.post(f"/api/pairs/{pair['id']}/accept")
    assert accepted.status_code == 200 and len(accepted.json()["observation_ids"]) == 6
    assert client.get(f"/api/pairs/{pair['id']}/report").status_code == 200
    assert client.app.state.store.one("SELECT COUNT(*) AS n FROM observation WHERE model_eligible=1")["n"] == 0
    mapped = client.get(f"/api/color-model?{s['setup']}").json()
    assert mapped["samples"] == [] and len(mapped["camera_relative_sets"]) == 1
    assert len(mapped["camera_relative_sets"][0]["samples"]) == 6


def test_rephoto_upload_needs_only_photo_and_keeps_the_same_experiment(client):
    s = setup(client)
    plate = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10 20", "frequencies": "40 80",
                                              "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()[0]
    from titanium_platform import plans
    store = client.app.state.store
    plan = plans.get_plan(store, plate["plan_id"])
    lightburn = client.get(f"/api/plans/{plate['plan_id']}/export.lbrn2").content
    image = png(synth.plate_photo(plan, CELLS, with_chart=False))
    original = upload_pair(client, s, lightburn, image).json()
    rejected = client.post(f"/api/pairs/{original['id']}/rephotos", files={"photo": ("new.png", image)})
    assert rejected.status_code == 422
    assert client.post(f"/api/pairs/{original['id']}/check", json={}).status_code == 200
    assert client.post(f"/api/pairs/{original['id']}/review-masks").status_code == 200
    assert client.post(f"/api/pairs/{original['id']}/accept").status_code == 200

    response = client.post(f"/api/pairs/{original['id']}/rephotos", files={"photo": ("new.png", image)})
    assert response.status_code == 201
    new = response.json()
    assert new["status"] == "Awaiting check" and new["rephoto_of"] == original["id"]
    assert new["photo_name"] == "new.png" and new["lightburn_name"] == original["lightburn_name"]
    renamed = client.patch(f"/api/engravings/{new['engraving_id']}", json={"title": "Титан — первый запуск"})
    assert renamed.status_code == 200
    assert {p["engraving_title"] for p in client.get("/api/pairs").json()} == {"Титан — первый запуск"}
    assert client.patch(f"/api/engravings/{new['engraving_id']}", json={"title": "   "}).status_code == 422
    for key in ("device_id", "lens_id", "material_id", "plate_id", "plan_id", "engraving_id", "context", "hardware"):
        assert new[key] == client.get(f"/api/pairs/{original['id']}").json()[key]
    assert client.get(f"/api/pairs/{new['id']}/lightburn").content == lightburn
    assert client.post(f"/api/pairs/{new['id']}/check", json={}).json()["status"] == "Ready to accept"
    assert client.post(f"/api/pairs/{new['id']}/review-masks").status_code == 200
    assert client.post(f"/api/pairs/{new['id']}/accept").status_code == 200
    variant_image = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    variant_image[100, 100, 0] ^= 255
    same_name_other_file = client.post(f"/api/pairs/{new['id']}/rephotos",
                                       files={"photo": ("new.png", png(variant_image))}).json()
    listed = {item["id"]: item for item in client.get("/api/pairs").json()}
    assert listed[original["id"]]["photo_sha256"] == listed[new["id"]]["photo_sha256"]
    assert listed[new["id"]]["photo_name"] == listed[same_name_other_file["id"]]["photo_name"]
    assert listed[new["id"]]["photo_sha256"] != listed[same_name_other_file["id"]]["photo_sha256"]
    assert client.delete(f"/api/pairs/{same_name_other_file['id']}").status_code == 204
    report = client.get(f"/api/pairs/{new['id']}/report").json()
    assert report["rephoto_of"] == original["id"]
    assert [item["id"] for item in report["photos"]] == [original["id"], new["id"]]
    assert {row["repeat_eligible"] for row in store.query("SELECT repeat_eligible FROM observation WHERE pair_id=?", (new["id"],))} == {0}
    assert client.delete(f"/api/pairs/{original['id']}").status_code == 204
    third = client.post(f"/api/pairs/{new['id']}/rephotos", files={"photo": ("third.png", image)}).json()
    assert third["rephoto_of"] == new["id"] and third["engraving_id"] == new["engraving_id"]
    assert third["engraving_title"] == "Титан — первый запуск"
    assert client.get(f"/api/pairs/{third['id']}/lightburn").content == lightburn
    assert client.delete(f"/api/pairs/{third['id']}").status_code == 204
    remaining = client.get("/api/pairs").json()
    assert [p["id"] for p in remaining] == [new["id"]]
    assert remaining[0]["engraving_title"] == "Титан — первый запуск"
    assert client.get(f"/api/pairs/{new['id']}/report").json()["photos"] == [
        {"id": new["id"], "photo_name": "new.png", "status": "Accepted", "created_at": new["created_at"]}]


def test_accepted_photo_alignment_can_be_revised_without_a_new_upload(client):
    s = setup(client)
    plate = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10 20", "frequencies": "40 80",
                                              "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()[0]
    from titanium_platform import plans
    plan = plans.get_plan(client.app.state.store, plate["plan_id"])
    lightburn = client.get(f"/api/plans/{plate['plan_id']}/export.lbrn2").content
    image = png(synth.plate_photo(plan, CELLS, with_chart=False))
    original = upload_pair(client, s, lightburn, image).json()
    original_id = original["id"]
    assert client.post(f"/api/pairs/{original_id}/check", json={}).status_code == 200
    assert client.post(f"/api/pairs/{original_id}/review-masks").status_code == 200
    assert client.post(f"/api/pairs/{original_id}/accept").status_code == 200
    store = client.app.state.store
    old_data = json.loads(store.one("SELECT data_json FROM pair WHERE id=?", (original_id,))["data_json"])
    old_data["check"]["alignment"].pop("work_corners_fraction", None)  # accepted before the editor existed
    old_data["check"]["alignment"].pop("snap_candidates", None)
    store.execute("UPDATE pair SET data_json=? WHERE id=?", (json.dumps(old_data), original_id))

    response = client.post(f"/api/pairs/{original_id}/alignment-revisions")
    assert response.status_code == 201
    revision = response.json()
    assert revision["correction_of"] == original_id and revision["status"] == "Ready to accept"
    assert revision["check"]["alignment"]["valid"] and revision["masks_reviewed"] is False
    assert len(revision["check"]["alignment"]["work_corners_fraction"]) == 4
    assert "snap_candidates" in revision["check"]["alignment"]
    assert revision["engraving_id"] == original["engraving_id"]
    assert client.get(f"/api/pairs/{original_id}").status_code == 200
    moved = client.post(f"/api/pairs/{revision['id']}/check", json={"translation_fraction": [.002, 0]}).json()
    assert moved["status"] == "Ready to accept" and moved["check"]["alignment"]["method"] == "manual shift"
    full_turn = client.post(f"/api/pairs/{revision['id']}/check", json={"rotation_degrees": 360}).json()
    assert full_turn["status"] == "Ready to accept"
    assert full_turn["check"]["alignment"]["method"] == "manual shift"
    assert client.get(f"/api/pairs/{revision['id']}/vector-overlay.png").headers["content-type"] == "image/png"
    assert client.post(f"/api/pairs/{revision['id']}/review-masks").status_code == 200
    assert client.post(f"/api/pairs/{revision['id']}/accept").status_code == 200
    assert client.get(f"/api/pairs/{original_id}").status_code == 404
    assert [p["id"] for p in client.get("/api/pairs").json()] == [revision["id"]]
    assert client.get(f"/api/pairs/{revision['id']}/report").status_code == 200


def test_exporting_a_draft_plan_is_refused(client):
    s = setup(client)
    st = client.app.state.store
    st.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,data_json,created_at) VALUES ('d','Discrete color engraving','Draft',?,?,0,'{\"layers\":[]}','t')", (s["laser"]["id"], s["lens"]["id"]))
    r = client.get("/api/plans/1/export.lbrn2")
    assert r.status_code == 422 and "draft" in r.json()["error"]


def test_deleting_a_plate_plan_removes_the_plate_with_it(client):
    s = setup(client)
    plates = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10", "frequencies": "40", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()
    assert client.delete(f"/api/plans/{plates[0]['plan_id']}").status_code == 204
    st = client.app.state.store
    assert st.one("SELECT COUNT(*) AS n FROM plate")["n"] == 0 and st.one("SELECT COUNT(*) AS n FROM plan")["n"] == 0
    assert client.delete(f"/api/plans/{plates[0]['plan_id']}").status_code == 404


def test_archiving_a_plan_with_deleted_pairs_hides_it_but_preserves_pair_history(client):
    s = setup(client)
    plate = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10", "frequencies": "40", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()[0]
    plan_id = plate["plan_id"]
    plan_xml = client.get(f"/api/plans/{plan_id}/export.lbrn2").content
    pair = upload_pair(client, s, plan_xml, png(synth.scene()), plan_id=plan_id).json()
    st = client.app.state.store

    blocked = client.delete(f"/api/plans/{plan_id}")
    assert blocked.status_code == 409 and "active input pairs" in blocked.json()["error"]

    assert client.delete(f"/api/pairs/{pair['id']}").status_code == 204
    assert not client.get("/api/pairs").json()
    assert client.delete(f"/api/plans/{plan_id}").status_code == 204

    assert all(row["id"] != plan_id for row in client.get("/api/plans").json())
    assert client.get(f"/api/plans/{plan_id}").status_code == 404
    assert client.get(f"/api/plans/{plan_id}/export.lbrn2").status_code == 404
    archived_pair = st.one("SELECT plan_id,status FROM pair WHERE id=?", (pair["id"],))
    assert archived_pair["plan_id"] == plan_id and archived_pair["status"] == "Deleted"
    assert st.one("SELECT status FROM plan WHERE id=?", (plan_id,))["status"] == "Deleted"
    assert st.one("SELECT status FROM plate WHERE id=?", (plate["plate_id"],))["status"] == "Deleted"   # kept as history, archived with its plan


def test_a_test_with_active_checks_is_removed_only_after_each_check_is_deleted(client):
    """DEC-047: active pairs prevent plan removal, there is no cascade; the plate is archived with its plan."""
    s = setup(client)
    plate = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10", "frequencies": "40",
        "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()[0]
    plan_id = plate["plan_id"]
    plan_xml = client.get(f"/api/plans/{plan_id}/export.lbrn2").content
    from titanium_platform import plans
    st = client.app.state.store
    photo = png(synth.plate_photo(plans.get_plan(st, plan_id), CELLS))
    pair = upload_pair(client, s, plan_xml, photo, plan_id=plan_id).json()
    assert client.post(f"/api/pairs/{pair['id']}/check", json={}).status_code == 200
    assert client.post(f"/api/pairs/{pair['id']}/review-masks").status_code == 200
    assert client.post(f"/api/pairs/{pair['id']}/accept").status_code == 200
    assert client.get(f"/api/plans/{plan_id}").json()["active_pairs"] == 1
    for refused in (client.delete(f"/api/plans/{plan_id}"), client.delete(f"/api/plans/{plan_id}?with_pairs=true")):
        assert refused.status_code == 409 and refused.json()["error"] == "active input pairs are linked to this plan; delete those pairs first"
    assert client.get(f"/api/plans/{plan_id}").status_code == 200 and client.get("/api/pairs").json()
    assert client.delete(f"/api/pairs/{pair['id']}").status_code == 204
    assert client.delete(f"/api/plans/{plan_id}").status_code == 204
    assert not client.get("/api/plans").json()
    assert not client.get("/api/pairs").json()
    assert st.one("SELECT status,plan_id FROM pair WHERE id=?", (pair["id"],))["status"] == "Deleted"
    assert st.one("SELECT status FROM plan WHERE id=?", (plan_id,))["status"] == "Deleted"
    assert st.one("SELECT status FROM plate WHERE id=?", (plate["plate_id"],))["status"] == "Deleted"
    assert st.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pair["id"],))["n"] > 0
    assert client.get(f"/api/color-model?{s['setup']}").json()["samples"] == []
    # a new photograph of the archived plate is not taken into an active experiment
    assert upload_pair(client, s, plan_xml, photo, plan_id=plan_id).status_code == 422
    again = upload_pair(client, s, plan_xml, photo).json()
    problems = client.post(f"/api/pairs/{again['id']}/check", json={}).json()["check"]["problems"]
    assert f"experiment identifier {plate['experiment_id']} belongs to a deleted experiment" in problems


def test_the_photo_preview_is_a_downscaled_png_of_the_uploaded_photo(client):
    s = setup(client)
    big = synth.scene(width=3000, height=2000)
    pair = upload_pair(client, s, b'<LightBurnProject><Notes Notes=""/></LightBurnProject>', png(big)).json()
    r = client.get(f"/api/pairs/{pair['id']}/photo.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) == 1400 and abs(img.shape[1] / img.shape[0] - 1.5) < 0.01
    lifted = client.get(f"/api/pairs/{pair['id']}/photo.png?visibility=lifted")
    brighter = cv2.imdecode(np.frombuffer(lifted.content, np.uint8), cv2.IMREAD_COLOR)
    assert lifted.status_code == 200 and brighter.mean() > img.mean()
    assert client.get(f"/api/pairs/{pair['id']}/photo.png?visibility=unknown").status_code == 422
    assert client.get("/api/pairs/999/photo.png").status_code == 404



@pytest.mark.parametrize("name,ascii_part,utf8_part", [
    ("Портрет мамы", "filename=\"_______ ____.lbrn2\"", "filename*=UTF-8''%D0%9F%D0%BE%D1%80%D1%82%D1%80%D0%B5%D1%82%20%D0%BC%D0%B0%D0%BC%D1%8B.lbrn2"),
    ("Plate 1", "filename=\"Plate 1.lbrn2\"", "filename*=UTF-8''Plate%201.lbrn2"),
    ('a"b\\c/d:e*f?g', "filename=\"abcdefg.lbrn2\"", "filename*=UTF-8''abcdefg.lbrn2"),
    ("   ...   ", "filename=\"plan.lbrn2\"", "filename*=UTF-8''plan.lbrn2"),
])
def test_content_disposition_survives_any_plan_name(name, ascii_part, utf8_part):
    """Regression: a Russian plan name made the export answer 500 (header values must be Latin-1)."""
    from titanium_platform.api.common import content_disposition
    header = content_disposition(name, ".lbrn2")
    header.encode("latin-1")                       # must not raise
    assert header.startswith("attachment; ") and ascii_part in header and utf8_part in header
    assert "\n" not in header and "\r" not in header


def test_exporting_a_plan_with_a_russian_name_works_end_to_end(client):
    s = setup(client)
    plates = client.post("/api/plates", json={"device_id": s["laser"]["id"], **JOB, "powers": "10", "frequencies": "40", "speeds": "900", "cell_width": 5, "cell_height": 4, "gap": 1}).json()
    client.app.state.store.execute("UPDATE plan SET name=? WHERE id=?", ("Рисунок A", plates[0]["plan_id"]))
    r = client.get(f"/api/plans/{plates[0]['plan_id']}/export.lbrn2")
    assert r.status_code == 200 and r.content.startswith(b"<?xml")
    assert "filename*=UTF-8''%D0%A0%D0%B8%D1%81%D1%83%D0%BD%D0%BE%D0%BA%20A.lbrn2" in r.headers["content-disposition"]
