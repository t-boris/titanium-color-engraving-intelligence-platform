import json

from fastapi.testclient import TestClient

from titanium_platform import analysis, capability_plates as cp, capability_results, devices, lenses, plans
from titanium_platform import setup as su
from titanium_platform.api.app import create_app
from titanium_platform.db import now


def accepted_capability_pair(store, laser, material, test_type="calibration", made=None, with_line_metrics=False):
    if made is None:
        plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)   # the operator's C01 recipe (DEC-027)
        made = cp.create(store, laser["id"], material["id"], test_type, {"pulse_width": 200})
    plan = plans.get_plan(store, made["plan_id"])
    pair_id = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,material_id,plate_id,plan_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at,accepted_at) "
        "VALUES ('Accepted',?,?,?,?,?,?,'test.lbrn2','/test.lbrn2','test.raw','/test.raw',?,?,?,?)",
        (plan["device_id"], plan["lens_id"], material["id"], made["plate_id"], made["plan_id"], f"engraving-{made['plate_id']}",
         json.dumps({"titanium_name": material["name"], "titanium_grade": material["grade"], "batch": material["batch"]}),
         "{}", now(), now())).lastrowid
    sample_layers = plan["layers"][:2]
    for index, (layer, lab) in enumerate(zip(sample_layers, ([35.0, 1.0, 2.0], [65.0, 4.0, 6.0]))):
        evidence = {"layer_name": layer["name"]}
        if with_line_metrics:
            evidence["line_metrics"] = {"line_count": 1, "visible_line_count": index,
                                        "median_continuity_percent": 100.0 if index else 0.0}
        store.execute(
            "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) "
            "VALUES (?,?,?,?,?,?,?, 'markers', '{}',1,1,'accepted capability test',?,?)",
            (pair_id, layer["index"], plan["device_id"], plan["lens_id"], f"engraving-{made['plate_id']}", json.dumps(lab),
             json.dumps(layer["parameters"]), json.dumps(evidence), now()))
    return made, pair_id


def test_accepted_test_result_is_processed_with_hardware_and_material_provenance(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="RESULT-1")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    material = su.save_material(store, "Grade 2 sheet", batch="HEAT-19", grade="Grade 2")
    made, pair_id = accepted_capability_pair(store, laser, material)
    store.execute(
        "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) "
        "VALUES (?,?,?,?,?,?,?, 'markers', '{}',0,1,'cleaning witness',?,?)",
        (pair_id, -1, laser["id"], lens["id"], f"engraving-{made['plate_id']}",
         json.dumps([90.0, 0.0, 0.0]), json.dumps({}), json.dumps({"layer_name": "Cleaning witness", "role": "pre-test cleaning witness"}), now()))

    report = capability_results.report_for_pair(store, pair_id)
    assert report["device_id"] == laser["id"]
    assert report["lens"]["name"] == "F-Theta"
    assert report["material"] == {"name": "Grade 2 sheet", "grade": "Grade 2", "batch": "HEAT-19"}
    assert report["measured_features"] == 2
    assert report["operation_measurements"] == 1
    assert report["max_separation"]["delta_e"] > 30
    assert "порог видимого следа" in report["limitations"][0]
    assert [r["name"] for r in report["rows"] if r["role"] == "test feature"] == [x["name"] for x in plans.get_plan(store, made["plan_id"])["layers"][:2]]
    assert report["operation_rows"][0]["name"] == "Cleaning witness"
    assert [r["pair_id"] for r in capability_results.for_device(store, laser["id"])] == [pair_id]


def test_capability_findings_are_available_in_the_pair_report_and_device_api(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        laser = client.post("/api/devices/from-template", json={"template": "jpt-ydflp-e-60-m7-m-r", "name": "JPT M7", "serial": "API-RESULT"}).json()
        lens = client.post("/api/lenses", json={"name": "F-Theta", "focal_length_mm": 174, "field_mm": 170}).json()
        client.put(f"/api/devices/{laser['id']}/lens", json={"lens_id": lens["id"]})
        client.put("/api/marker-layer", json={"power": 25, "frequency": 60, "speed": 150, "pulse_width": 200, "line_interval": 0.01, "passes": 1})
        material = client.post("/api/materials", json={"name": "Grade 2", "grade": "Grade 2", "batch": "API-19"}).json()
        made = client.post("/api/capability-plates", json={"device_id": laser["id"], "material_id": material["id"], "pulse_width": 200, "test_type": "hatch_interval"}).json()
        store = client.app.state.store
        laser_model = devices.get_device(store, laser["id"])
        stock = store.one("SELECT * FROM material_profile WHERE id=?", (material["id"],))
        _, pair_id = accepted_capability_pair(store, laser_model, dict(stock), "hatch_interval", made)

        report = client.get(f"/api/pairs/{pair_id}/report").json()
        history = client.get(f"/api/devices/{laser['id']}/capability-results").json()
        assert report["capability"]["test_type"] == "hatch_interval"
        assert report["capability"]["finding"].startswith("Самые различающиеся")
        assert history[0]["pair_id"] == pair_id and history[0]["lens"]["id"] == lens["id"]
        assert history[0]["material"]["batch"] == "API-19"


def test_compact_capability_reports_line_evidence_without_color_tolerance_columns(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="RESULT-LINES")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    _, pair_id = accepted_capability_pair(store, laser, material, "compact_capability", with_line_metrics=True)
    report = analysis.report_for_pair(store, pair_id)
    assert report["capability"]["line_response"]["visible"] == 1
    assert "1 из 2" in report["capability"]["finding"]
    assert any("кандидаты для повторной проверки" in signal for signal in report["capability"]["signals"])
    assert any("Q-Pulse" in step for step in report["capability"]["next_steps"])
    assert not any("delta E tolerance" in note for note in report["limitations"])
    use_cases = {item["purpose"]: item for item in report["capability"]["use_cases"]}
    assert use_cases["line"]["status"] == "candidate"
    assert use_cases["text"]["status"] == "needs_text_test"
    assert use_cases["text"]["parameters"] is None
    capability_results.save_findings(store, pair_id)
    saved = capability_results.findings_for_device(store, laser["id"], "text")
    assert len(saved) == 1 and saved[0]["pair_id"] == pair_id
    assert saved[0]["context"]["titanium_grade"] == "Grade 2"
    assert saved[0]["evidence"]["name"].startswith("LINE-P")
    store.execute("UPDATE pair SET status='Deleted' WHERE id=?", (pair_id,))
    assert capability_results.findings_for_device(store, laser["id"], "text") == []


def test_a_recalculated_capability_finding_keeps_the_version_it_replaced(store):
    """REQ-022 AC6: recalculation never erases what an earlier version of a finding said; an unchanged one is left alone."""
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="RESULT-HISTORY")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    _, pair_id = accepted_capability_pair(store, laser, material, "compact_capability", with_line_metrics=True)
    capability_results.save_findings(store, pair_id)
    capability_results.save_findings(store, pair_id)               # the same result again: nothing to keep
    assert store.one("SELECT COUNT(*) AS n FROM capability_finding_history")["n"] == 0
    line = store.one("SELECT * FROM capability_finding WHERE pair_id=? AND purpose='line'", (pair_id,))
    store.execute("UPDATE capability_finding SET summary='an earlier wording', status='insufficient' WHERE id=?", (line["id"],))   # as an older version wrote it

    capability_results.save_findings(store, pair_id)

    now_row = store.one("SELECT * FROM capability_finding WHERE id=?", (line["id"],))
    assert (now_row["summary"], now_row["status"]) == (line["summary"], line["status"]) and now_row["updated_at"] is not None
    history = capability_results.finding_history(store, line["id"])
    assert [(h["summary"], h["status"], h["valid_from"]) for h in history] == [("an earlier wording", "insufficient", line["created_at"])]
    with TestClient(create_app(store.data_dir)) as client:          # the experiment page shows the earlier version
        experiment = next(e for e in client.get("/api/experiments").json() if e.get("plan_id"))
        shown = client.get(f"/api/experiments/{experiment['key']}").json()["findings"]
    assert next(f for f in shown if f["purpose"] == "line")["history"][0]["summary"] == "an earlier wording"

