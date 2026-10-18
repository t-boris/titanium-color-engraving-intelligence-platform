import json

from fastapi.testclient import TestClient
import pytest

from titanium_platform import application_guide, capability_plates, capability_results, devices, lenses, plans
from titanium_platform import setup as su
from titanium_platform.api.app import create_app
from titanium_platform.db import now

JOB = {"pulse_width": 200}      # the pulse width of a test plate is always given (DEC-043)


def hardware(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="GOAL-1")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    other = su.save_material(store, "Other titanium sheet", grade="Grade 5")
    return laser, material, other


def test_text_goal_creates_compact_clean_first_plate_and_records_its_goal(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        store = client.app.state.store
        laser, material, _ = hardware(store)
        suggestion = client.get("/api/application-guide", params={"device_id": laser["id"],
            "material_id": material["id"], "goal": "text"}).json()
        assert suggestion["plate"]["test_type"] == "text_readability"
        assert suggestion["finding"] is None
        created = client.post("/api/application-guide/next-plate", json={"device_id": laser["id"],
            "material_id": material["id"], "goal": "text"})
        assert created.status_code == 201, created.text
        plan = plans.get_plan(store, created.json()["plan_id"])
        assert plan["experiment"]["research_goal"] == "text"
        assert plan["experiment"]["source_pair_id"] is None
        assert len(plan["layers"]) == 9
        assert all(len(layer["measurement_groups"]) == 3 for layer in plan["layers"])
        assert plan["experiment"]["summary"]["size_mm"]["width"] < 65
        assert plan["experiment"]["summary"]["size_mm"]["height"] < 65
        waiting = client.get("/api/application-guide", params={"device_id": laser["id"],
            "material_id": material["id"], "goal": "text"}).json()
        assert waiting["status"] == "awaiting_photo"
        assert waiting["pending_plan_id"] == created.json()["plan_id"]
        assert waiting["plate"] is None


def test_replaced_or_cancelled_plate_is_not_reported_as_awaiting_photo(store):
    laser, material, _ = hardware(store)
    plate = capability_plates.create(store, laser["id"], material["id"], "text_readability",
                                     {**JOB, "research_goal": "text"})
    plan_id = plate["plan_id"]
    assert application_guide.suggest(store, laser["id"], material["id"], "text")["pending_plan_id"] == plan_id
    for inactive in ("Superseded", "Cancelled"):
        store.execute("UPDATE plan SET status=? WHERE id=?", (inactive, plan_id))
        suggestion = application_guide.suggest(store, laser["id"], material["id"], "text")
        assert suggestion["status"] != "awaiting_photo"
        assert suggestion.get("pending_plan_id") is None


def test_next_text_plate_uses_only_same_material_and_lens_evidence(store):
    laser, material, other = hardware(store)
    lens_id = devices.get_device(store, laser["id"])["lens"]["id"]
    pair_id = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,material_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at,accepted_at) "
        "VALUES ('Accepted',?,?,?, 'goal-source','source.lbrn2','/source.lbrn2','source.dng','/source.dng','{}','{}',?,?)",
        (laser["id"], lens_id, material["id"], now(), now())).lastrowid
    store.execute(
        "INSERT INTO capability_finding(pair_id,purpose,status,summary,parameters_json,evidence_json,next_test,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (pair_id, "line", "candidate", "линия", json.dumps({"power": 40, "speed": 1200,
         "frequency": 48, "pulse_width": 200, "line_interval": 0.025, "passes": 1}), "{}", "повтор", now()))
    selected = application_guide.suggest(store, laser["id"], material["id"], "text")
    assert selected["plate"]["settings"]["power"] == 40
    assert selected["plate"]["settings"]["speed"] == 1200
    assert selected["plate"]["source_pair_id"] == pair_id
    assert application_guide.suggest(store, laser["id"], other["id"], "text")["plate"]["source_pair_id"] is None
    assert lens_id == selected["lens"]["id"]


def test_depth_and_cutting_are_not_presented_as_surface_photo_recipes(store):
    laser, material, _ = hardware(store)
    for goal in ("deep", "relief_3d", "cutting"):
        suggestion = application_guide.suggest(store, laser["id"], material["id"], goal)
        assert suggestion["status"] == "measurement_needed"
        assert suggestion["plate"] is None
        assert "пока" in suggestion["next_step"]


def test_other_material_can_be_catalogued_without_using_titanium_cleaning(store):
    laser, _, _ = hardware(store)
    steel = su.save_material(store, "Steel coin blank", family="Steel", grade="304", thickness_mm=1)
    guide = application_guide.suggest(store, laser["id"], steel["id"], "text")
    assert guide["status"] == "cleaning_recipe_needed" and guide["plate"] is None
    with pytest.raises(su.ValidationError, match="рецепт очистки"):
        capability_plates.create(store, laser["id"], steel["id"], "text_readability", JOB)


def test_text_finding_ranks_contrast_but_does_not_claim_readability():
    rows = [{"name": "CLEAN", "role": "pre-test cleaning witness", "lab": [50, 0, 0]},
            {"name": "TEXT-P20-V900", "role": "test feature", "layer_index": 2,
             "parameters": {"power": 20, "speed": 900},
             "submeasurements": [{"measured_lab": [40, 0, 0]}] * 3},
            {"name": "TEXT-P30-V1200", "role": "test feature", "layer_index": 3,
             "parameters": {"power": 30, "speed": 1200},
             "submeasurements": [{"measured_lab": [30, 0, 0]}] * 3}]
    finding = capability_results._text_case(rows)
    assert finding["status"] == "contrast_candidate"
    assert finding["evidence"]["name"] == "TEXT-P30-V1200"
    assert finding["parameters"] is None
    assert "читаемость" in finding["summary"]


def test_text_matrix_cells_can_produce_preliminary_text_findings():
    rows = [{"name": "CLEAN", "role": "pre-test cleaning witness", "lab": [50, 0, 0]},
            {"name": "TEXT-MATRIX-V500-F105", "role": "test feature", "layer_index": 2,
             "parameters": {"speed": 500, "frequency": 105},
             "submeasurements": [{"measured_lab": [30, 0, 0]}] * 3}]
    finding = capability_results._text_case(rows)
    assert finding["status"] == "contrast_candidate"
    assert finding["evidence"]["parameters"]["speed"] == 500
    assert "читаемость" in finding["summary"]


def test_the_guide_starts_at_200_ns_only_when_the_laser_offers_it_and_otherwise_asks(store):
    laser, material, _ = hardware(store)
    assert application_guide.suggest(store, laser["id"], material["id"], "color")["plate"]["settings"]["pulse_width"] == 200
    without = dict(laser["passport"], pulse_steps=[s for s in laser["passport"]["pulse_steps"] if s["pulse_width_ns"] != 200])
    devices.update_device(store, laser["id"], passport=without)
    suggestion = application_guide.suggest(store, laser["id"], material["id"], "color")
    assert suggestion["plate"]["settings"]["pulse_width"] is None                # the operator is asked
    app_settings = {**suggestion["plate"]["settings"], "pulse_width": 250}
    assert capability_plates.preview(store, laser["id"], material["id"], suggestion["plate"]["test_type"], app_settings)
