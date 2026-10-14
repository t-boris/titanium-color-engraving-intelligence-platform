import json

import cv2
import pytest

import synth
from titanium_platform import ingest as ig
from titanium_platform import plans as pl
from titanium_platform import profiles as pf

CELLS = {"r1c1": (200, 60, 60), "r1c2": (60, 200, 60), "r2c1": (60, 60, 200), "r2c2": (200, 200, 60)}


@pytest.fixture
def world(store):
    store.set_setting("allow_non_raw_photos", True)  # tests use PNG renders; real use requires RAW
    profile = pf.create_profile(store, "MOPA", 200, 0.025, 1)
    stand = pf.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    pl.save_marker_layer_settings(store, 20, 60, 300)
    out = pl.create_plate_series(store, profile["id"], "10 20", "40 80", "900", 5, 4, 1)[0]
    plan = pl.get_plan(store, out["plan_id"])
    return {"store": store, "profile": profile, "stand": stand, "plan": plan, "plate": out, "lbrn": pl.export_lbrn2(plan)}


def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def make_pair(w, lbrn=None, photo=None, **kw):
    return ig.create_pair(w["store"], profile_id=w["profile"]["id"], stand_id=w["stand"]["id"], lightburn_name="plate.lbrn2",
                          lightburn_bytes=lbrn or w["lbrn"], photo_name="plate.png",
                          photo_bytes=photo or png(synth.plate_photo(w["plan"], CELLS, gains=(0.9, 0.97, 1.08))), **kw)


def test_a_good_plate_pair_passes_every_check_and_measures_each_cell(world):
    s = world["store"]
    pid = make_pair(world)
    report = ig.check_pair(s, pid)
    assert report["problems"] == [], report
    assert report["chart"]["detected"] and report["alignment"] == {"method": "markers", "valid": True, "error": None}
    assert report["discrepancies"] == [] and report["plate"]["experiment_id"] == world["plate"]["experiment_id"]
    measured = {l["name"]: l["measured_lab"] for l in report["layers"] if l["measured_lab"]}
    assert set(measured) == set(CELLS)
    assert len({tuple(round(v) for v in lab) for lab in measured.values()}) == 4  # four distinguishable colours
    assert ig.get_pair(s, pid)["status"] == ig.ST_READY


def test_accepting_requires_the_mask_review_then_writes_immutable_observations(world):
    s = world["store"]
    pid = make_pair(world)
    ig.check_pair(s, pid)
    with pytest.raises(ig.IngestError, match="masks"):
        ig.accept_pair(s, pid)
    ig.review_masks(s, pid)
    calls = []
    ids = ig.accept_pair(s, pid, on_accepted=lambda st, prof: calls.append(prof))
    assert len(ids) == 4 and calls == [world["profile"]["id"]]
    obs = s.one("SELECT * FROM observation ORDER BY id LIMIT 1")
    params = json.loads(obs["parameters_json"])
    assert {k: params[k] for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")} == {
        "power": 10, "frequency": 40, "speed": 900, "pulse_width": 200, "line_interval": 0.025, "passes": 1}
    assert obs["alignment_method"] == "markers" and obs["model_eligible"] == 1 and obs["repeat_eligible"] == 1
    assert ig.get_pair(s, pid)["status"] == ig.ST_ACCEPTED
    with pytest.raises(ig.IngestError, match="immutable"):
        ig.check_pair(s, pid)
    with pytest.raises(ig.IngestError, match="protected"):
        ig.delete_pair(s, pid)


def test_a_photo_without_a_chart_creates_no_observations(world):
    s = world["store"]
    pid = make_pair(world, photo=png(synth.plate_photo(world["plan"], CELLS, with_chart=False)))
    report = ig.check_pair(s, pid)
    assert not report["chart"]["detected"] and any("Reference chart" in p for p in report["problems"])
    assert ig.get_pair(s, pid)["status"] == ig.ST_CORRECTION
    with pytest.raises(ig.IngestError):
        ig.accept_pair(s, pid)
    assert s.one("SELECT COUNT(*) AS n FROM observation")["n"] == 0


def test_missing_markers_stop_the_plate_mapping_instead_of_guessing(world):
    s = world["store"]
    plan = dict(world["plan"])
    plan["markers"] = {**plan["markers"], "aruco": plan["markers"]["aruco"][:2]}  # two markers never engraved
    pid = make_pair(world, photo=png(synth.plate_photo({**world["plan"], "markers": plan["markers"]}, CELLS)))
    report = ig.check_pair(s, pid)
    assert not report["alignment"]["valid"] and "markers not detected" in report["alignment"]["error"]
    assert s.one("SELECT COUNT(*) AS n FROM observation")["n"] == 0


def test_a_non_raw_photo_is_refused_when_not_allowed(world):
    world["store"].set_setting("allow_non_raw_photos", False)
    with pytest.raises(ig.IngestError, match="RAW"):
        make_pair(world)


def test_bad_inputs_are_rejected_before_anything_is_stored(world):
    s = world["store"]
    with pytest.raises(ig.IngestError, match="lbrn"):
        ig.create_pair(s, profile_id=world["profile"]["id"], stand_id=world["stand"]["id"], lightburn_name="x.txt", lightburn_bytes=b"x", photo_name="p.png", photo_bytes=b"x")
    with pytest.raises(ig.IngestError, match="capture setup"):
        ig.create_pair(s, profile_id=world["profile"]["id"], stand_id=999, lightburn_name="x.lbrn2", lightburn_bytes=b"x", photo_name="p.png", photo_bytes=b"x")
    assert s.one("SELECT COUNT(*) AS n FROM pair")["n"] == 0


def test_context_is_optional_and_defaults_to_unknown():
    assert ig.clean_context(None) == {"material_id": None, "batch": None, "focus": None, "engraved_at": None, "note": None}
    c = ig.clean_context({"focus": "1.5", "engraved_at": "2026-10-14", "batch": " B1 "})
    assert (c["focus"], c["engraved_at"], c["batch"]) == (1.5, "2026-10-14", "B1")
    for bad in ({"focus": "abc"}, {"focus": "nan"}, {"engraved_at": "14.10.2026"}):
        with pytest.raises(pf.ValidationError):
            ig.clean_context(bad)


def test_same_as_previous_uses_the_last_accepted_pair_of_the_profile(world):
    s = world["store"]
    assert ig.previous_context(s, world["profile"]["id"]) is None
    pid = make_pair(world, context={"batch": "B-7", "focus": 0.5})
    ig.check_pair(s, pid)
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    assert ig.previous_context(s, world["profile"]["id"])["batch"] == "B-7"
