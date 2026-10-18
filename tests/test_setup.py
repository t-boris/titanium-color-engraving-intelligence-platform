import pytest

import obs
from titanium_platform import setup as su


@pytest.fixture
def w(store):
    return obs.setup(store)


def test_the_setup_key_separates_lasers_lenses_and_the_unknown_lens():
    assert su.setup_key(1, 2) == "laser:1/lens:2"
    assert su.setup_key(1, None) == "laser:1/lens:unknown"
    assert len({su.setup_key(1, 2), su.setup_key(1, None), su.setup_key(2, 2)}) == 3


def test_a_setup_resolves_the_laser_and_the_chosen_lens(store, w):
    device_id, lens_id = w["setup"]
    s = su.resolve(store, device_id, lens_id)
    assert s["key"] == su.setup_key(device_id, lens_id) and s["lens"]["id"] == lens_id and s["device"]["passport"]["pulse_steps"]
    assert su.resolve(store, device_id, None)["lens"] is None
    assert su.installed(store, device_id)["lens_id"] == lens_id
    with pytest.raises(KeyError):
        su.resolve(store, device_id, 999)


def test_the_lens_snapshot_keeps_the_spot_value_with_its_basis(store, w):
    from titanium_platform import devices
    passport = dict(w["device"]["passport"], spot_diameter_um=42.0)
    devices.update_device(store, w["device"]["id"], passport=passport)
    snap = su.lens_snapshot(su.installed(store, w["device"]["id"]))
    assert snap["id"] == w["setup"][1] and snap["focal_length_mm"] == 174
    assert snap["spot_diameter_um"] == 42.0 and snap["spot_basis"] == "measured"
    assert su.lens_snapshot(su.resolve(store, w["device"]["id"], None)) is None


def test_parameter_vector_contains_each_layers_job_settings(store, w):
    v = su.parameter_vector(w["device"]["passport"], 24, 40, 900, pulse_width=250, line_interval=0.05, passes=3)
    assert v == {"power": 24, "frequency": 40, "speed": 900, "pulse_width": 250, "line_interval": 0.05, "passes": 3}
    with pytest.raises(su.ValidationError, match="not a selectable step"):
        su.parameter_vector(w["device"]["passport"], 24, 40, 900, 210, 0.05, 3)
    with pytest.raises(TypeError):
        su.parameter_vector(w["device"]["passport"], 24, 40, 900)          # no job setting is filled in (DEC-043)


def test_range_check_uses_the_laser(store, w):
    passport = w["device"]["passport"]
    assert su.check_in_range(passport, 24, 40) == []
    assert su.check_in_range(passport, 500, 40) == ["power 500 % is outside 0-100"]
    assert su.check_in_range(passport, 24, 5000) == ["frequency 5000 kHz is outside 1-4000"]


def test_capture_setup_requires_all_fields_and_is_protected_when_used(store):
    with pytest.raises(su.ValidationError, match="lighting"):
        su.save_capture_setup(store, "s", "cam", "", "90", "ColorChecker")
    s = su.save_capture_setup(store, "Rig", "cam on stand", "LED 5600K", "90", "ColorChecker Classic")
    assert s["raw_format"] == 1 and s["chart_detection_verified"] == 0
    su.delete_capture_setup(store, s["id"])
    assert su.list_capture_setups(store) == []


def test_material_batch_is_optional(store):
    m = su.save_material(store, "Ti grade 2")
    assert m["batch"] is None and m["family"] == "Titanium"
    assert su.save_material(store, "Ti grade 2", "B-41", m["id"])["batch"] == "B-41"


def test_rules_start_unset_and_numbers_alone_do_not_agree_the_criteria(store, w):
    r = su.get_rules(store, *w["setup"])
    assert r == {"repeat_threshold": None, "delta_tolerance": None, "variance_threshold": None, "criteria_agreed": False}
    r = su.save_rules(store, *w["setup"], repeat_threshold=3, delta_tolerance=4, variance_threshold=2)
    assert r["criteria_agreed"] is False
    assert su.save_rules(store, *w["setup"], criteria_agreed=True)["criteria_agreed"] is True


def test_cannot_agree_criteria_before_thresholds_exist(store, w):
    with pytest.raises(su.ValidationError):
        su.save_rules(store, *w["setup"], criteria_agreed=True)
    with pytest.raises(su.ValidationError):
        su.save_rules(store, *w["setup"], repeat_threshold=0)
    with pytest.raises(su.ValidationError):
        su.save_rules(store, *w["setup"], delta_tolerance=-1)
    with pytest.raises(KeyError):
        su.save_rules(store, 999, None, delta_tolerance=1)
