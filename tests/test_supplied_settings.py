"""A required setting that a LightBurn layer does not hold is supplied by the operator, with provenance (REQ-015, REQ-016)."""
import json
import re

import cv2
import pytest
from fastapi.testclient import TestClient

import synth
from titanium_platform import devices, lenses
from titanium_platform import ingest as ig
from titanium_platform import plans as pl
from titanium_platform import setup as su
from titanium_platform.api.app import create_app

CELLS = {"r1c1": (200, 60, 60), "r1c2": (60, 200, 60), "r2c1": (60, 60, 200), "r2c2": (200, 200, 60)}
JOB = {"pulse_width": 200, "line_interval": 0.025, "passes": 1}
FILE_FIELDS = ("power", "frequency_khz", "speed", "pulse_width", "line_interval", "passes")


def plate_world(store, default_pulse_width=None):
    """``default_pulse_width``: the laser's Q-Pulse default (DEC-086); the template carries 200, these tests are about a laser without one."""
    store.set_setting("allow_non_raw_photos", True)          # tests use PNG renders; real use requires RAW
    device = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    device = devices.update_device(store, device["id"], passport={**device["passport"], "default_pulse_width_ns": default_pulse_width})
    lens = lenses.create_lens(store, "F-Theta 174", 174, 170)
    lenses.install(store, device["id"], lens["id"])
    stand = su.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    pl.save_marker_layer_settings(store, 20, 60, 300)
    out = pl.create_plate_series(store, device["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)[0]
    plan = pl.get_plan(store, out["plan_id"])
    return {"store": store, "device": device, "lens": lens, "stand": stand, "material": material, "plan": plan, "lbrn": pl.export_lbrn2(plan)}


@pytest.fixture
def world(store):
    return plate_world(store)


def without(lbrn: bytes, tag: str, layer: str = "r1c1") -> bytes:
    """The plate file with the setting ``tag`` removed from one cell's layer: a LightBurn file that omits it."""
    text = lbrn.decode()
    start = text.index(f'<name Value="{layer}"/>')
    end = text.index("</CutSetting>", start)
    return (text[:start] + re.sub(rf'\s*<{tag} Value="[^"]*"/>', "", text[start:end], count=1) + text[end:]).encode()


def photo(w) -> bytes:
    return cv2.imencode(".png", synth.plate_photo(w["plan"], CELLS, gains=(0.9, 0.97, 1.08)))[1].tobytes()


def pair_without(w, tag: str) -> int:
    return ig.create_pair(w["store"], device_id=w["device"]["id"], lens_id=w["lens"]["id"], stand_id=w["stand"]["id"],
                          lightburn_name="plate.lbrn2", lightburn_bytes=without(w["lbrn"], tag), photo_name="plate.png",
                          photo_bytes=photo(w), context={"material_id": w["material"]["id"]})


def cell(report: dict, name: str = "r1c1") -> dict:
    return next(rep for rep in report["layers"] if rep["name"] == name)


def observation_of(store, pair_id: int, name: str):
    return store.one("SELECT parameters_json, evidence_json, model_eligible FROM observation WHERE pair_id=? AND evidence_json LIKE ?",
                     (pair_id, f'%"layer_name": "{name}"%'))


def test_a_pulse_width_missing_from_the_file_is_supplied_and_the_observation_carries_it_as_the_operators(world):
    s = world["store"]
    pid = pair_without(world, "QPulseWidth")
    before = cell(ig.check_pair(s, pid))
    assert before["missing_settings"] == ["pulse_width"] and before["supplied_settings"] == {}
    assert not before["compatible"] and any("pulse width is missing from this LightBurn layer" in n for n in before["notes"])

    after = cell(ig.supply_setting(s, pid, before["index"], "pulse_width", 200))
    assert after["compatible"] and not any("pulse width" in n for n in after["notes"]) and after["measured_lab"] is not None
    given = after["supplied_settings"]["pulse_width"]
    assert given["value"] == 200 and given["by"] == "operator" and given["at"]          # who and when
    assert after["pulse_width"] is None                                                   # the file's own value is still what the file says
    assert s.one("SELECT COUNT(*) AS n FROM audit WHERE action='setting_supplied'")["n"] == 1

    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    row = observation_of(s, pid, "r1c1")
    params, evidence = json.loads(row["parameters_json"]), json.loads(row["evidence_json"])
    assert params["pulse_width"] == 200 and params["power"] == 10 and params["frequency"] == 40 and row["model_eligible"] == 1
    assert evidence["settings_provenance"] == {"power": "file", "frequency": "file", "speed": "file", "pulse_width": "operator",
                                               "line_interval": "file", "passes": "file"}
    assert evidence["supplied_settings"]["pulse_width"]["by"] == "operator" and evidence["parameter_error"] is None
    other = json.loads(observation_of(s, pid, "r2c2")["evidence_json"])
    assert set(other["settings_provenance"].values()) == {"file"} and other["supplied_settings"] is None


def test_without_a_supplied_value_the_missing_setting_stays_unknown_and_out_of_the_model(world):
    s = world["store"]
    pid = pair_without(world, "QPulseWidth")
    ig.check_pair(s, pid)
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    row = observation_of(s, pid, "r1c1")
    assert json.loads(row["parameters_json"])["pulse_width"] is None and row["model_eligible"] == 0       # never 200 ns by default
    assert json.loads(row["evidence_json"])["settings_provenance"]["pulse_width"] is None


def test_a_pulse_width_outside_the_range_of_the_laser_is_refused_with_the_range(world):
    s = world["store"]
    pid = pair_without(world, "QPulseWidth")
    index = cell(ig.check_pair(s, pid))["index"]
    with pytest.raises(su.ValidationError, match=re.escape("pulse width 600 ns is outside the range of this laser (1-500 ns)")):
        ig.supply_setting(s, pid, index, "pulse_width", 600)
    assert ig.get_pair(s, pid)["supplied_settings"] is None


@pytest.mark.parametrize("setting, value, message", [
    ("power", 120, "power must not exceed 100 %"), ("power", 0, "power must be a finite positive number"),
    ("speed", -5, "speed must be a finite positive number"), ("passes", 1.5, "passes must be a positive integer")])
def test_a_supplied_value_is_validated_like_a_plate_setting(setting, value, message):
    passport = devices.validate_passport(devices.TEMPLATES["jpt-ydflp-e-60-m7-m-r"]["passport"])
    with pytest.raises(su.ValidationError, match=re.escape(message)):
        ig.supplied_value(passport, setting, value)
    assert ig.supplied_value(passport, "passes", 2.0) == 2 and ig.supplied_value(passport, "line_interval", 0.03) == 0.03


def test_a_missing_frequency_is_checked_against_the_laser_range_and_once_supplied_the_layer_is_measured(world):
    s = world["store"]
    pid = pair_without(world, "frequency")
    before = cell(ig.check_pair(s, pid))
    assert not before["readable"] and before["missing_settings"] == ["frequency"] and before["measured_lab"] is None
    with pytest.raises(su.ValidationError, match="outside the repetition rate range 1-4000 kHz"):
        ig.supply_setting(s, pid, before["index"], "frequency", 5000)
    after = cell(ig.supply_setting(s, pid, before["index"], "frequency", 40))
    assert after["readable"] and after["compatible"] and after["measured_lab"] is not None and after["frequency_khz"] is None


def test_a_value_read_from_the_file_is_never_replaced(world):
    s = world["store"]
    pid = pair_without(world, "QPulseWidth")
    report = ig.check_pair(s, pid)
    file_values = {rep["name"]: {k: rep[k] for k in FILE_FIELDS} for rep in report["layers"]}
    with pytest.raises(ig.IngestError, match="never replaced"):
        ig.supply_setting(s, pid, cell(report)["index"], "power", 30)
    with pytest.raises(ig.IngestError, match="never replaced"):
        ig.supply_setting(s, pid, cell(report, "r2c2")["index"], "pulse_width", 200)     # this layer has its own pulse width
    after = ig.supply_setting(s, pid, cell(report)["index"], "pulse_width", 200)
    assert {rep["name"]: {k: rep[k] for k in FILE_FIELDS} for rep in after["layers"]} == file_values
    assert cell(after, "r2c2")["pulse_width"] == 200 and cell(after, "r2c2")["supplied_settings"] == {}


def test_a_supplied_value_can_be_taken_back_before_acceptance_and_not_after(world):
    s = world["store"]
    pid = pair_without(world, "QPulseWidth")
    index = cell(ig.check_pair(s, pid))["index"]
    ig.supply_setting(s, pid, index, "pulse_width", 200)
    cleared = cell(ig.supply_setting(s, pid, index, "pulse_width", None))
    assert cleared["supplied_settings"] == {} and not cleared["compatible"] and ig.get_pair(s, pid)["supplied_settings"] is None
    ig.supply_setting(s, pid, index, "pulse_width", 200)
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    with pytest.raises(ig.IngestError, match="immutable"):
        ig.supply_setting(s, pid, index, "pulse_width", None)


def test_another_lightburn_file_drops_the_supplied_values_and_a_new_view_of_the_job_keeps_them(world):
    s = world["store"]
    pid = pair_without(world, "QPulseWidth")
    index = cell(ig.check_pair(s, pid))["index"]
    ig.supply_setting(s, pid, index, "pulse_width", 200)
    ig.replace_lightburn_file(s, pid, "fixed.lbrn2", without(world["lbrn"], "QPulseWidth"))
    assert ig.get_pair(s, pid)["supplied_settings"] is None
    ig.supply_setting(s, pid, index, "pulse_width", 200)
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    again = ig.create_rephoto(s, pid, photo_name="again.png", photo_bytes=photo(world))
    assert ig.get_pair(s, again)["supplied_settings"] == ig.get_pair(s, pid)["supplied_settings"]
    assert cell(ig.check_pair(s, again))["compatible"]


def test_the_operator_supplies_a_setting_over_http_and_a_pulse_width_outside_the_range_is_refused_with_it(tmp_path):
    app = create_app(tmp_path / "data")
    w = plate_world(app.state.store)
    pid = pair_without(w, "QPulseWidth")
    with TestClient(app) as client:
        index = cell(client.post(f"/api/pairs/{pid}/check", json={}).json()["check"])["index"]
        bad = client.post(f"/api/pairs/{pid}/supplied-settings", json={"layer_index": index, "setting": "pulse_width", "value": 600})
        assert bad.status_code == 422 and "outside the range of this laser (1-500 ns)" in bad.json()["error"]
        ok = client.post(f"/api/pairs/{pid}/supplied-settings", json={"layer_index": index, "setting": "pulse_width", "value": 200})
        assert ok.status_code == 200 and cell(ok.json()["check"])["supplied_settings"]["pulse_width"]["value"] == 200
        unknown = client.post(f"/api/pairs/{pid}/supplied-settings", json={"layer_index": index, "setting": "colour", "value": 1})
        assert unknown.status_code == 422
    app.state.store.close()
