"""What a laser allows and what its characterization uses (REQ-017 AC2 and AC5, REQ-018).

A pulse width outside the laser's range is refused with the range on every path (DEC-089); a handwritten note that
contradicts a printed controller value leaves both unresolved and neither used; the effective power, the frequency limits,
the warning and problem levels, the pulse-energy cap and the work-field check rest only on evidence that is reliable.
"""
import copy
import json
import re
from pathlib import Path

import cv2
import pytest
from fastapi.testclient import TestClient

import synth
from titanium_platform import capability_plates as cp
from titanium_platform import characterization as ch
from titanium_platform import devices as dv
from titanium_platform import ingest as ig
from titanium_platform import lenses, plans, research
from titanium_platform import setup as su
from titanium_platform.api.app import create_app

TEMPLATE = "jpt-ydflp-e-60-m7-m-r"
UNIT = Path(__file__).resolve().parents[1] / "tools" / "units" / "jpt-ydflp-e-60-m7-m-r-mc2bdjd71684.json"
OFF_STEP = re.escape("pulse width 600 ns is outside the range of this laser (1-500 ns)")
JOB = {"pulse_width": 200, "line_interval": 0.025, "passes": 1}


def unit_passport() -> dict:
    """The operator's JPT unit: its test report (62.6 W), and its EZCAD settings with Max PWM printed 200 kHz and a
    handwritten note beside it that could not be read."""
    unit = json.loads(UNIT.read_text(encoding="utf-8"))
    return dv.validate_passport(copy.deepcopy(dv.TEMPLATES[unit["template"]]["passport"]) | unit["passport"])


def template_passport(**extra) -> dict:
    return dv.validate_passport(copy.deepcopy(dv.TEMPLATES[TEMPLATE]["passport"]) | extra)


def with_controller(passport: dict, *fields) -> dict:
    """``passport`` with laser-control fields (key, value, status)."""
    tabs = [{"key": "laser_control", "fields": [{"key": k, "value": v, "unit": "кГц", "status": s} for k, v, s in fields]}]
    return dv.validate_passport(passport | {"controller": {"software": "EZCAD", "source": None, "tabs": tabs}})


def with_report_power(watts: float) -> dict:
    return template_passport(test_report={"rows": [{"key": "Nominal average output power", "unit": "W", "result": watts}]})


# -- REQ-017 AC2: a pulse width off the laser's steps is refused with the steps listed, on every path ----------------------
@pytest.fixture
def hardware(store):
    laser = dv.create_from_template(store, TEMPLATE)
    lens = lenses.create_lens(store, "F-Theta 174", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", batch="A")
    return {"store": store, "laser": laser, "lens": lens, "material": material}


def test_a_calibration_plate_with_a_pulse_width_outside_the_range_is_refused_with_the_range(hardware):
    with pytest.raises(su.ValidationError, match=OFF_STEP):
        plans.create_plate_series(hardware["store"], hardware["laser"]["id"], "10 20", "40 80", "900", 5, 4, 1,
                                  pulse_width=600, line_interval=0.025, passes=1)


@pytest.mark.parametrize("test_type", ["calibration", "small_patches", "material_matrix", "power_speed"])
def test_a_capability_plate_with_a_pulse_width_outside_the_range_is_refused_with_the_range(hardware, test_type):
    with pytest.raises(su.ValidationError, match=OFF_STEP):
        cp.preview(hardware["store"], hardware["laser"]["id"], hardware["material"]["id"], test_type, {"pulse_width": 600})


def test_one_patch_outside_the_range_refuses_the_small_patch_plate_with_the_steps(hardware):
    with pytest.raises(su.ValidationError, match=OFF_STEP):
        cp.preview(hardware["store"], hardware["laser"]["id"], hardware["material"]["id"], "small_patches",
                   {"pulse_width": 200, "patches": [{}, {"pulse_width": 600}]})


def test_a_plan_whose_marker_layer_names_a_pulse_width_outside_the_range_is_refused_with_the_range(hardware):
    plans.save_marker_layer_settings(hardware["store"], 25, 60, 150, pulse_width=600)
    with pytest.raises(su.ValidationError, match=OFF_STEP):
        plans.create_plate_series(hardware["store"], hardware["laser"]["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)


def test_the_research_tools_refuse_a_pulse_width_outside_the_range_with_the_range(hardware):
    session = research.create_session(hardware["store"], hardware["laser"]["id"], hardware["material"]["id"], "line", "непрерывная линия")
    for tool in ("preview_test", "create_test"):
        with pytest.raises(su.ValidationError, match=OFF_STEP):
            research.call_tool(hardware["store"], session["id"], tool, {"test_type": "calibration", "settings": {"pulse_width": 600}})


def test_a_matrix_with_a_pulse_width_outside_the_range_cannot_be_confirmed_and_its_check_names_the_range(hardware):
    store = hardware["store"]
    store.set_setting("allow_non_raw_photos", True)
    su.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    work = synth.material_test(cols=3, rows=3, x_values=[20.0, 30.0, 40.0], y_values=[900.0, 600.0, 300.0])
    pid = ig.create_matrix_pair(store, device_id=hardware["laser"]["id"], lens_id=None, photo_name="m.png",
                                photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(), context={"material_id": hardware["material"]["id"]})
    edit = {"x": {"param": "power", "first": 20, "last": 40}, "y": {"param": "speed", "first": 900, "last": 300},
            "fixed": {"frequency": 330, "pulse_width": 600, "line_interval": 0.003, "passes": 1}}
    with pytest.raises(su.ValidationError, match=OFF_STEP):
        ig.update_matrix(store, pid, edit, confirm=True)
    report = ig.update_matrix(store, pid, edit)
    assert any(re.search(OFF_STEP, p) for p in report["problems"])
    with pytest.raises(su.ValidationError, match=OFF_STEP):
        ig.confirm_matrix(store, pid)
    report = ig.update_matrix(store, pid, {**edit, "fixed": {**edit["fixed"], "pulse_width": 4}}, confirm=True)
    assert not any("outside the range" in p for p in report["problems"]) and ig.get_pair(store, pid)["matrix"]["confirmed"]


def test_the_operating_point_and_the_photo_prediction_refuse_a_pulse_width_outside_the_range_over_http(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        laser = client.post("/api/devices/from-template", json={"template": TEMPLATE}).json()
        point = {"device_id": laser["id"], "lens_id": None, "power": 30, "frequency": 80, "speed": 900, **JOB, "pulse_width": 600}
        refused = client.post("/api/operating-point", json=point)
        assert refused.status_code == 422 and "outside the range of this laser (1-500 ns)" in refused.json()["error"]
        predicted = client.post("/api/predictions/photo", data={"device_id": laser["id"], "lens_id": "unknown", "pulse_width": 600},
                                files={"lightburn": ("p.lbrn2", synth.picture_work()["lightburn"], "application/octet-stream")})
        assert predicted.status_code == 422 and "outside the range of this laser (1-500 ns)" in predicted.json()["error"]
    app.state.store.close()


# -- REQ-017 AC5: a handwritten note against a printed value leaves both unresolved and neither used -----------------------
def test_conflicting_printed_and_handwritten_max_pwm_are_shown_together_and_neither_is_used():
    passport = unit_passport()
    c = ch.characterize(passport)
    (conflict,) = [u for u in c["unresolved"] if u["key"] == "Max PWM"]
    assert conflict["values"] == [{"value": 200.0, "status": "printed"}, {"value": "см. фото", "status": "handwritten"}]
    freq = next(i for i in c["items"] if i["key"] == "frequency_range")
    assert freq["unresolved"] == [conflict] and "Max PWM" in freq["waiting_for"]
    assert c["controller_limits_khz"]["max"] is None                       # neither 200 nor 4000 is asserted as the controller's limit
    assert c["frequency_range_khz"]["max"] == passport["repetition_rate_khz"]["max"]       # the laser's own limit stays
    assert dv.operating_point(passport, 50, 300, 900, 200, 0.025)["outside_controller_range"] is False   # 300 > 200: no warning from it
    assert not any("Max PWM" in n for n in dv.operating_point(passport, 50, 300, 900, 200, 0.025)["notes"])


def test_once_the_operator_confirms_max_pwm_it_becomes_a_limit_and_is_no_longer_unresolved():
    passport = unit_passport()
    for tab in passport["controller"]["tabs"]:
        for f in tab["fields"]:
            if f["key"] == "Max PWM":
                f["status"] = "confirmed"
    c = ch.characterize(passport)
    assert not [u for u in c["unresolved"] if u["key"] == "Max PWM"]
    assert c["controller_limits_khz"]["max"] == 200 and c["frequency_range_khz"]["max"] == 200
    op = dv.operating_point(passport, 50, 300, 900, 200, 0.025)
    assert op["outside_controller_range"] and "frequency 300 kHz is above Max PWM 200 kHz of the laser settings" in op["notes"]


# -- REQ-018 --------------------------------------------------------------------------------------------------------------
def test_the_effective_power_is_the_units_test_report_value_for_the_jpt_unit():
    c = ch.characterize(unit_passport())
    assert c["effective_power_w"] == 62.6 and c["power_basis"] == "measured"
    assert dv.operating_point(unit_passport(), 100, 48, 900, 200, 0.025)["output_power_w"] == pytest.approx(62.6)


@pytest.mark.parametrize("watts, used, basis", [(30.0, 30.0, "measured"), (90.0, 90.0, "measured"), (29.9, 60, "rated"),
                                                (90.1, 60, "rated"), (100.0, 60, "rated")])
def test_a_measured_power_is_used_only_within_half_to_one_and_a_half_times_the_rated_power(watts, used, basis):
    c = ch.characterize(with_report_power(watts))
    assert (c["effective_power_w"], c["power_basis"]) == (used, basis)


@pytest.mark.parametrize("status, contested, narrows", [("printed", False, True), ("confirmed", False, True), ("handwritten", False, False),
                                                        ("printed", True, False), ("confirmed", True, True)])
def test_only_an_uncontested_printed_or_a_confirmed_controller_limit_narrows_the_frequency_range(status, contested, narrows):
    fields = [("Min PWM", 30.0, status)] + ([("Min PWM: рукописная пометка", "см. фото", "handwritten")] if contested else [])
    c = ch.characterize(with_controller(template_passport(), *fields))
    assert (c["frequency_range_khz"]["min"] == 30.0) is narrows and (c["controller_limits_khz"]["min"] == 30.0) is narrows
    if not narrows:
        assert c["frequency_range_khz"]["min"] == 1 and "Min PWM" in next(i for i in c["items"] if i["key"] == "frequency_range")["waiting_for"]


def test_contradictory_controller_limits_are_excluded_and_flagged():
    c = ch.characterize(with_controller(template_passport(), ("Min PWM", 500.0, "printed"), ("Max PWM", 200.0, "printed")))
    assert c["frequency_range_khz"] == {"min": 1, "max": 4000} and c["controller_limits_khz"] == {"min": None, "max": None, "contradictory": True}
    item = next(i for i in c["items"] if i["key"] == "frequency_range")
    assert item["waiting_for"] == ["Min PWM", "Max PWM"] and item["basis"] == "laser"


def test_a_frequency_outside_the_controller_limits_is_a_warning_and_outside_the_laser_limits_a_problem():
    passport = with_controller(template_passport(), ("Min PWM", 20.0, "printed"), ("Max PWM", 200.0, "confirmed"))
    below = dv.operating_point(passport, 50, 10, 900, 200, 0.025)
    assert below["problems"] == [] and below["outside_controller_range"] and "frequency 10 kHz is below Min PWM 20 kHz of the laser settings" in below["notes"]
    above = dv.operating_point(passport, 50, 300, 900, 200, 0.025)
    assert above["problems"] == [] and above["outside_controller_range"]
    inside = dv.operating_point(passport, 50, 100, 900, 200, 0.025)
    assert inside["problems"] == [] and not inside["outside_controller_range"]
    outside = dv.operating_point(passport, 50, 4500, 900, 200, 0.025)
    assert outside["problems"] == ["frequency 4500 kHz is outside the repetition rate range 1-4000 kHz of this laser"]


def test_the_modelled_pulse_energy_never_exceeds_the_passport_maximum():
    """500 ns at 20 kHz on the unit (62.6 W): 62.6 x 20/40 / 20 = 1.565 mJ, above the passport's 1.5 mJ."""
    op = dv.operating_point(unit_passport(), 100, 20, 900, 500, 0.025)
    assert op["pulse_energy_mj"] == pytest.approx(1.5) and op["output_power_w"] == pytest.approx(1.5 * 20)
    assert any("exceeds the passport maximum 1.5 mJ: limited to the maximum" in n for n in op["notes"])
    curve = next(c for c in dv.charts(unit_passport())["curves"] if c["pulse_width_ns"] == 500)
    assert max(p["pulse_energy_mj"] for p in curve["points"]) <= 1.5 + 1e-9


def test_a_plate_checked_against_an_unknown_work_field_says_the_placement_was_not_checked(store):
    laser = dv.create_from_template(store, TEMPLATE)
    plans.save_marker_layer_settings(store, 25, 60, 150)
    lens = lenses.create_lens(store, "F-Theta without a field", 174)                 # the field of this lens is not known
    lenses.install(store, laser["id"], lens["id"])
    (made,) = plans.create_plate_series(store, laser["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)
    assert made["work_field"]["checked"] is False and made["work_field"]["field_mm"] is None
    assert made["work_field"]["note"] == "the work field of the lens is unknown: the placement was not checked"
    assert plans.get_plan(store, made["plan_id"])["work_field"]["checked"] is False
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", batch="A")
    preview = cp.preview(store, laser["id"], material["id"], "calibration", {"pulse_width": 200})
    assert preview["experiment"]["summary"]["work_field"]["checked"] is False
    lenses.update_lens(store, lens["id"], field_mm=170)
    (fits,) = plans.create_plate_series(store, laser["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)
    assert fits["work_field"]["checked"] is True and fits["work_field"]["field_mm"] == {"width": 170, "height": 170}
    assert fits["work_field"]["needed_mm"]["width"] <= 170
    lenses.update_lens(store, lens["id"], field_mm=20)
    with pytest.raises(su.ValidationError, match="larger than the work field 20 x 20 mm"):
        cp.preview(store, laser["id"], material["id"], "calibration", {"pulse_width": 200})
