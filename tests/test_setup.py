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
    from titanium_platform import lenses
    lenses.update_lens(store, w["setup"][1], spot_diameter_um=42.0)       # measured with the installed lens (REQ-019)
    snap = su.lens_snapshot(su.installed(store, w["device"]["id"]))
    assert snap["id"] == w["setup"][1] and snap["focal_length_mm"] == 174
    assert snap["spot_diameter_um"] == 42.0 and snap["spot_basis"] == "measured"
    assert su.lens_snapshot(su.resolve(store, w["device"]["id"], None)) is None


def test_parameter_vector_contains_each_layers_job_settings(store, w):
    v = su.parameter_vector(w["device"]["passport"], 24, 40, 900, pulse_width=250, line_interval=0.05, passes=3)
    assert v == {"power": 24, "frequency": 40, "speed": 900, "pulse_width": 250, "line_interval": 0.05, "passes": 3}
    with pytest.raises(su.ValidationError, match="outside the range"):
        su.parameter_vector(w["device"]["passport"], 24, 40, 900, 600, 0.05, 3)
    assert su.parameter_vector(w["device"]["passport"], 24, 40, 900, 210, 0.05, 3)["pulse_width"] == 210       # any width in the range (DEC-089)
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


def test_a_capture_setup_carries_the_published_chart_values_until_the_operator_gives_its_own(store):
    """DEC-025: the reference values, white point and observer are an explicit setting of the capture setup."""
    rig = su.save_capture_setup(store, "Rig", "cam on stand", "LED 5600K", "90", "ColorChecker Classic")
    ref = rig["chart_reference"]
    assert ref["published"] and (ref["white_point"], ref["observer"]) == ("D65", "2°") and "published ColorChecker" in ref["source"]
    assert len(ref["patches_lab"]) == 24 and ref["patches_lab"][18][0] > 95 and ref["patches_lab"][23][0] < 25   # white ... black
    own = [[L + 1, a, b] for L, a, b in ref["patches_lab"]]
    saved = su.save_chart_reference(store, rig["id"], own, "D50", "2°", " X-Rite, after November 2014 ")["chart_reference"]
    assert saved == {"source": "X-Rite, after November 2014", "white_point": "D50", "observer": "2°", "patches_lab": own, "published": False}
    assert su.list_capture_setups(store)[0]["chart_reference"] == saved
    for args, message in (((own[:23], "D65", "2°", "x"), "24 Lab triples"), (([[120, 0, 0]] * 24, "D65", "2°", "x"), "24 Lab triples"),
                          ((own, "A", "2°", "x"), "white point must be one of D65, D50"), ((own, "D65", "10°", "x"), "2° standard observer"),
                          ((own, "D65", "2°", " "), "where the reference values come from")):
        with pytest.raises(su.ValidationError, match=message):
            su.save_chart_reference(store, rig["id"], *args)
    assert su.reset_chart_reference(store, rig["id"])["chart_reference"] == ref


def test_a_new_photograph_is_taken_on_the_rig_used_last_and_never_on_the_placeholder_of_old_pairs(store, w):
    """REQ-009: every photograph names its rig; 'as last time' is the default."""
    from titanium_platform.db import now
    rig = w["stand"]["id"]
    assert su.capture_setup_for_photo(store, None) == rig                 # the only rig there is
    other = su.save_capture_setup(store, "Window table", "phone", "daylight", "60", "ColorChecker Classic")["id"]
    with pytest.raises(su.ValidationError, match="select a capture setup"):
        su.capture_setup_for_photo(store, None)                           # two rigs and none used yet: the operator chooses
    obs.add(store, w, (50, 0, 0))                                         # a photograph on the first rig ...
    store.execute("UPDATE pair SET stand_id=? WHERE id=(SELECT MAX(id) FROM pair)", (other,))   # ... moved to the second
    assert su.capture_setup_for_photo(store, None) == other and su.last_capture_setup(store) == other
    assert [s["last_used"] for s in su.list_capture_setups(store)] == [False, True]
    legacy = store.execute("INSERT INTO capture_setup(name,camera,lighting,angle,reference_chart,created_at) VALUES (?,?,?,?,?,?)",
                           (su.LEGACY_SETUP_NAME, "not recorded", "not recorded", "not recorded", "ColorChecker Classic", now())).lastrowid
    store.execute("UPDATE pair SET stand_id=?", (legacy,))                # an old pair keeps its placeholder ...
    assert su.get_capture_setup(store, legacy)["legacy"] and su.last_capture_setup(store) is None
    with pytest.raises(su.ValidationError, match="placeholder capture setup"):
        su.capture_setup_for_photo(store, legacy)                         # ... a new photograph never gets it
    assert su.capture_setup_for_photo(store, legacy, keep=legacy) == legacy   # the same photograph aligned again keeps its record


def test_without_any_rig_no_photograph_can_be_uploaded(store):
    with pytest.raises(su.ValidationError, match="add the capture setup"):
        su.capture_setup_for_photo(store, None)


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
