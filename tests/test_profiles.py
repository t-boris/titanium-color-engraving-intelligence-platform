import pytest

from titanium_platform import profiles as pf
from titanium_platform.db import now


def make(store, **kw):
    args = dict(name="MOPA")
    args.update(kw)
    return pf.create_profile(store, **args)


def test_create_profile_identifies_hardware_without_process_settings(store):
    # Legacy process arguments are tolerated during migration but are not saved on a hardware identity.
    p = make(store, pulse_width=200, line_interval=0.025, passes=1)
    assert [a["key"] for a in p["axes"]] == ["power", "frequency", "speed"]
    assert not {"pulse_width", "line_interval", "passes", "constants"} & p.keys()
    assert p["version"] == 1


@pytest.mark.parametrize("kw", [dict(name="  ")])
def test_create_profile_validates(store, kw):
    with pytest.raises(pf.ValidationError):
        make(store, **kw)


def test_axes_validation(store):
    with pytest.raises(pf.ValidationError):
        make(store, axes=[{"key": "power", "unit": "%", "min": 1, "max": 2}])
    bad = [dict(a) for a in pf.DEFAULT_AXES]
    bad[0]["min"], bad[0]["max"] = 5, 5
    with pytest.raises(pf.ValidationError):
        make(store, axes=bad)


def test_extra_axis_needs_no_migration(store):
    axes = [dict(a) for a in pf.DEFAULT_AXES] + [{"key": "focus", "name": "Focus", "unit": "mm", "min": -2, "max": 2}]
    p = make(store, axes=axes)
    assert [a["key"] for a in p["axes"]][-1] == "focus"


def test_process_settings_do_not_create_profile_versions(store):
    p = make(store, pulse_width=200, line_interval=0.025, passes=1)
    unchanged = pf.update_profile(store, p["id"], pulse_width=250, line_interval=0.05, passes=3)
    assert unchanged["id"] == p["id"] and unchanged["version"] == 1
    assert not {"pulse_width", "line_interval", "passes", "constants"} & unchanged.keys()


def test_rename_keeps_the_version(store):
    p = make(store)
    assert pf.update_profile(store, p["id"], name="Renamed")["name"] == "Renamed"
    assert len(pf.list_profiles(store)) == 1


def test_unlinked_profile_can_be_deleted_linked_one_cannot(store):
    p = make(store)
    pf.delete_profile(store, p["id"])
    assert pf.list_profiles(store) == []
    q = make(store, name="B")
    store.execute("INSERT INTO plate(experiment_id,profile_id,speed,geometry_json,cells_json,created_at) VALUES ('e',?,1,'{}','[]',?)", (q["id"], now()))
    with pytest.raises(pf.ProtectedError, match="plates"):
        pf.delete_profile(store, q["id"])


def test_parameter_vector_contains_each_layers_process_settings(store):
    p = make(store)
    v = pf.parameter_vector(p, 24, 40, 900, pulse_width=250, line_interval=0.05, passes=3)
    assert v == {"power": 24, "frequency": 40, "speed": 900, "pulse_width": 250, "line_interval": 0.05, "passes": 3, "profile_id": p["id"]}


def test_range_check(store):
    p = make(store)
    assert pf.check_in_range(p, 24, 40, 900) == []
    assert len(pf.check_in_range(p, 500, 40, 900)) == 1


def test_capture_setup_requires_all_fields_and_is_protected_when_used(store):
    with pytest.raises(pf.ValidationError, match="lighting"):
        pf.save_capture_setup(store, "s", "cam", "", "90", "ColorChecker")
    s = pf.save_capture_setup(store, "Rig", "cam on stand", "LED 5600K", "90", "ColorChecker Classic")
    assert s["raw_format"] == 1 and s["chart_detection_verified"] == 0
    pf.delete_capture_setup(store, s["id"])
    assert pf.list_capture_setups(store) == []


def test_material_batch_is_optional(store):
    m = pf.save_material(store, "Ti grade 2")
    assert m["batch"] is None and m["family"] == "Titanium"
    assert pf.save_material(store, "Ti grade 2", "B-41", m["id"])["batch"] == "B-41"


def test_rules_start_unset_and_numbers_alone_do_not_agree_the_criteria(store):
    p = make(store)
    r = pf.get_rules(store, p["id"])
    assert r == {"repeat_threshold": None, "delta_tolerance": None, "variance_threshold": None, "criteria_agreed": False}
    r = pf.save_rules(store, p["id"], repeat_threshold=3, delta_tolerance=4, variance_threshold=2)
    assert r["criteria_agreed"] is False
    assert pf.save_rules(store, p["id"], criteria_agreed=True)["criteria_agreed"] is True


def test_cannot_agree_criteria_before_thresholds_exist(store):
    p = make(store)
    with pytest.raises(pf.ValidationError):
        pf.save_rules(store, p["id"], criteria_agreed=True)
    with pytest.raises(pf.ValidationError):
        pf.save_rules(store, p["id"], repeat_threshold=0)
    with pytest.raises(pf.ValidationError):
        pf.save_rules(store, p["id"], delta_tolerance=-1)
