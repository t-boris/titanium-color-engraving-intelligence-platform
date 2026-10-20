"""LightBurn leaves QPulseWidth out of a layer whose width is the laser's default: that default is a parameter of the laser, set by
the operator, and a layer without the tag takes it, shown as the laser's default and never as "not in the file" (DEC-086)."""
import json

import pytest

import test_supplied_settings as base
from titanium_platform import devices
from titanium_platform import ingest as ig
from titanium_platform import setup as su


def test_the_template_laser_carries_a_default_pulse_width_that_must_be_a_step_of_the_laser(store):
    device = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    assert device["passport"]["default_pulse_width_ns"] == 200
    for bad, message in ((123, "not a step of this laser"), (-5, "")):
        with pytest.raises(su.ValidationError) as caught:
            devices.update_device(store, device["id"], passport={**device["passport"], "default_pulse_width_ns": bad})
        assert message in str(caught.value)
    cleared = devices.update_device(store, device["id"], passport={**device["passport"], "default_pulse_width_ns": ""})
    assert cleared["passport"]["default_pulse_width_ns"] is None
    kept = devices.update_device(store, device["id"], passport={**device["passport"], "default_pulse_width_ns": 150})
    assert devices.get_passport(store, device["id"])["default_pulse_width_ns"] == 150 and kept["passport"]["default_pulse_width_ns"] == 150


def test_a_layer_without_the_tag_takes_the_laser_default_and_is_comparable(store):
    world = base.plate_world(store, default_pulse_width=200)
    pid = base.pair_without(world, "QPulseWidth")
    rep = base.cell(ig.check_pair(store, pid))
    assert rep["missing_settings"] == ["pulse_width"] and rep["pulse_width"] is None          # the file is still reported as it is
    assert rep["defaulted_settings"] == {"pulse_width": {"value": 200, "source": "laser default"}}
    assert rep["compatible"] and not any("pulse width" in n for n in rep["notes"]) and rep["measured_lab"] is not None
    assert ig.effective_setting(rep, "pulse_width") == 200
    assert set(base.cell(ig.check_pair(store, pid), "r2c2")["defaulted_settings"]) == set()   # a layer that holds it has nothing defaulted


def test_the_accepted_observation_carries_the_default_with_its_provenance_and_feeds_the_model(store):
    world = base.plate_world(store, default_pulse_width=200)
    pid = base.pair_without(world, "QPulseWidth")
    ig.check_pair(store, pid)
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)
    row = base.observation_of(store, pid, "r1c1")
    params, evidence = json.loads(row["parameters_json"]), json.loads(row["evidence_json"])
    assert params["pulse_width"] == 200 and row["model_eligible"] == 1 and evidence["parameter_error"] is None
    assert evidence["settings_provenance"]["pulse_width"] == "laser default" and evidence["settings_provenance"]["power"] == "file"
    assert evidence["defaulted_settings"]["pulse_width"] == {"value": 200, "source": "laser default"} and evidence["supplied_settings"] is None


def test_a_value_the_operator_supplies_beats_the_default_and_a_value_in_the_file_beats_both(store):
    world = base.plate_world(store, default_pulse_width=200)
    pid = base.pair_without(world, "QPulseWidth")
    first = base.cell(ig.check_pair(store, pid))
    after = base.cell(ig.supply_setting(store, pid, first["index"], "pulse_width", 100))
    assert ig.effective_setting(after, "pulse_width") == 100 and after["defaulted_settings"] == {}
    assert ig.settings_provenance(after)["pulse_width"] == "operator"
    holding = base.cell(ig.check_pair(store, pid), "r2c2")
    assert holding["pulse_width"] == 200 and ig.settings_provenance(holding)["pulse_width"] == "file"


def test_a_laser_without_a_default_keeps_the_layer_unknown(store):
    world = base.plate_world(store, default_pulse_width=None)
    rep = base.cell(ig.check_pair(store, base.pair_without(world, "QPulseWidth")))
    assert rep["defaulted_settings"] == {} and not rep["compatible"]
    assert any("pulse width is missing from this LightBurn layer" in n for n in rep["notes"])


def test_the_colour_map_shows_the_default_of_a_checked_layer_before_acceptance(store):
    from titanium_platform import colormap
    world = base.plate_world(store, default_pulse_width=200)
    pid = base.pair_without(world, "QPulseWidth")
    rep = base.cell(ig.check_pair(store, pid))
    assert colormap.layer_parameters(rep)["pulse_width"] == 200
