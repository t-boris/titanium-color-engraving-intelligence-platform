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
    al = report["alignment"]
    assert report["chart"]["detected"] and (al["method"], al["valid"], al["error"]) == ("markers", True, None)
    assert len(al["image_to_mm"]) == 3 and all(len(r) == 3 for r in al["image_to_mm"])  # kept so the overlay matches the measurement
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


def edited_lbrn(world, power_for_r1c2=None, pulse_width=None):
    """The plate file as exported, then edited the way an operator might in LightBurn."""
    text = world["lbrn"].decode()
    if power_for_r1c2 is not None:
        # r1c2 is the second cell: power 20, frequency 40
        text = text.replace('<name Value="r1c2"/>\n        <maxPower Value="20"/>\n        <maxPower2 Value="20"/>',
                            f'<name Value="r1c2"/>\n        <maxPower Value="{power_for_r1c2}"/>\n        <maxPower2 Value="{power_for_r1c2}"/>')
    if pulse_width is not None:
        text = text.replace('<QPulseWidth Value="200"/>', f'<QPulseWidth Value="{pulse_width}"/>', 1)
    return text.encode()


def test_a_file_that_differs_from_the_plate_blocks_acceptance_until_confirmed(world):
    s = world["store"]
    pid = make_pair(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    report = ig.check_pair(s, pid)
    assert report["discrepancies"] == [{"cell_id": "r1c2", "field": "power", "defined": 20, "from_file": 33}]
    assert any("differs from the plate definition" in p for p in report["problems"])
    ig.review_masks(s, pid)
    with pytest.raises(ig.IngestError):
        ig.accept_pair(s, pid)
    with pytest.raises(ig.IngestError, match="own words"):
        ig.confirm_file(s, pid, "  ")
    conf = ig.confirm_file(s, pid, "I engraved with this exact file")
    assert conf["discrepancies"] == report["discrepancies"] and conf["file_name"] == "plate.lbrn2"
    assert ig.get_pair(s, pid)["status"] == ig.ST_READY
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    power = {r["layer_index"]: json.loads(r["parameters_json"])["power"] for r in s.query("SELECT layer_index, parameters_json FROM observation")}
    # layers follow the cell order r1c1, r1c2, r2c1, r2c2 -> indices 1..4; r1c2 was edited from 20 to 33 in the file
    assert power == {1: 10, 2: 33, 3: 10, 4: 20}  # the FILE's value is stored for the edited cell, not the plate definition's
    evidence = json.loads(s.one("SELECT evidence_json FROM observation WHERE layer_index=2")["evidence_json"])
    assert evidence["discrepancies"][0]["from_file"] == 33 and evidence["file_confirmation"]["text"].startswith("I engraved")
    assert s.one("SELECT COUNT(*) AS n FROM audit WHERE action='file_confirmed'")["n"] == 1


def test_correcting_the_pair_with_a_matching_file_clears_the_mismatch(world):
    s = world["store"]
    pid = make_pair(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ig.check_pair(s, pid)
    ig.confirm_file(s, pid, "used")
    ig.replace_lightburn_file(s, pid, "fixed.lbrn2", world["lbrn"])
    pair = ig.get_pair(s, pid)
    assert pair["status"] == ig.ST_PENDING and pair["file_confirmation"] is None and not pair["masks_reviewed"] and pair["check"] is None
    assert ig.check_pair(s, pid)["discrepancies"] == []
    with pytest.raises(ig.IngestError, match="no discrepancy"):
        ig.confirm_file(s, pid, "used")


def test_a_layer_with_a_different_pulse_width_is_skipped_not_comparable(world):
    s = world["store"]
    pid = make_pair(world, lbrn=edited_lbrn(world, pulse_width=500))
    report = ig.check_pair(s, pid)
    skipped = [l for l in report["layers"] if not l["compatible"] and l["index"] != pl.MARKER_LAYER_INDEX]
    assert len(skipped) == 1 and any("pulse width" in n and "not comparable" in n for n in skipped[0]["notes"])
    assert skipped[0]["measured_lab"] is None
    ig.review_masks(s, pid)
    ids = ig.accept_pair(s, pid)
    assert len(ids) == 3  # the incomparable layer never becomes an observation


def test_the_marker_layer_is_never_measured(world):
    s = world["store"]
    pid = make_pair(world)
    report = ig.check_pair(s, pid)
    marker = next(l for l in report["layers"] if l["index"] == pl.MARKER_LAYER_INDEX)
    assert marker["measured_lab"] is None and "not measured" in marker["notes"][0]


def test_a_rephotograph_shares_the_engraving_and_is_never_an_independent_repetition(world):
    s = world["store"]
    first = make_pair(world)
    ig.check_pair(s, first)
    ig.review_masks(s, first)
    ig.accept_pair(s, first)
    again = make_pair(world, rephoto_of=first)
    ig.check_pair(s, again)
    ig.review_masks(s, again)
    ig.accept_pair(s, again)
    rows = s.query("SELECT pair_id, engraving_id, repeat_eligible, model_eligible FROM observation")
    assert len({r["engraving_id"] for r in rows}) == 1
    assert {r["repeat_eligible"] for r in rows if r["pair_id"] == first} == {1}
    assert {r["repeat_eligible"] for r in rows if r["pair_id"] == again} == {0}
    assert {r["model_eligible"] for r in rows} == {1}
    with pytest.raises(ig.IngestError, match="accepted pair"):
        make_pair(world, rephoto_of=make_pair(world))


def test_a_marked_work_without_a_known_plate_needs_corners_and_aligns_manually(world):
    """A finished work from LightBurn: no markers, so the operator places the four corners."""
    s = world["store"]
    lbrn = (b'<LightBurnProject AppVersion="2.0.04"><CutSetting type="Scan"><index Value="5"/><name Value="C05"/>'
            b'<maxPower Value="24"/><speed Value="900"/><frequency Value="40000"/><QPulseWidth Value="200"/><interval Value="0.025"/></CutSetting>'
            b'<Shape Type="Rect" CutIndex="5" W="40" H="20" Cr="0"><XForm>1 0 0 1 30 20</XForm></Shape></LightBurnProject>')
    import numpy as np
    img = synth.scene(work_rgb=(200, 120, 40), work_box=(560, 200, 960, 400))
    pid = make_pair(world, lbrn=lbrn, photo=png(img))
    first = ig.check_pair(s, pid)
    assert not first["alignment"]["valid"] and any("four image corners" in p for p in first["problems"])
    corners = [(560, 200), (960, 200), (960, 400), (560, 400)]
    report = ig.check_pair(s, pid, corners=corners)
    assert report["problems"] == [] and report["alignment"]["method"] == "manual"
    lab = report["layers"][0]["measured_lab"]
    from titanium_platform import color
    assert color.delta_e(lab, color.srgb8_to_lab(np.array([200, 120, 40]))) < 6
    assert ig.get_pair(s, pid)["corners"] == [list(c) for c in corners]  # stored as JSON lists
    bad = ig.check_pair(s, pid, corners=[(0, 0), (10, 0), (0, 10), (10, 10)])
    assert not bad["alignment"]["valid"] and "convex" in bad["alignment"]["error"]


def test_a_photo_of_another_plate_is_refused(world):
    s = world["store"]
    other = pl.create_plate_series(s, world["profile"]["id"], "10 20", "40 80", "1200", 5, 4, 1)[0]
    other_plan = pl.get_plan(s, other["plan_id"])
    pid = make_pair(world, photo=png(synth.plate_photo(other_plan, CELLS)))
    report = ig.check_pair(s, pid)
    assert not report["alignment"]["valid"] and "photographed plate is" in report["alignment"]["error"]


def test_corners_can_be_given_as_fractions_of_the_photo_and_must_lie_inside_it(world):
    s = world["store"]
    lbrn = (b'<LightBurnProject AppVersion="2.0.04"><CutSetting type="Scan"><index Value="5"/><name Value="C05"/>'
            b'<maxPower Value="24"/><speed Value="900"/><frequency Value="40000"/><QPulseWidth Value="200"/><interval Value="0.025"/></CutSetting>'
            b'<Shape Type="Rect" CutIndex="5" W="40" H="20" Cr="0"><XForm>1 0 0 1 30 20</XForm></Shape></LightBurnProject>')
    img = synth.scene(work_rgb=(200, 120, 40), work_box=(560, 200, 960, 400))   # 1500 x 1000 px
    pid = make_pair(world, lbrn=lbrn, photo=png(img))
    report = ig.check_pair(s, pid, corners_fraction=[(560 / 1500, 0.2), (960 / 1500, 0.2), (960 / 1500, 0.4), (560 / 1500, 0.4)])
    assert report["problems"] == [] and report["alignment"]["method"] == "manual" and report["image_size"] == [1500, 1000]
    assert len(report["alignment"]["image_to_mm"]) == 3
    stored = ig.get_pair(s, pid)["corners"]
    assert stored[0] == pytest.approx([560, 200]) and stored[2] == pytest.approx([960, 400])
    bad = ig.check_pair(s, pid, corners_fraction=[(0, 0), (1.2, 0), (1, 1), (0, 1)])
    assert any("inside the photograph" in p for p in bad["problems"])


def test_the_overlay_outlines_the_measured_layers_on_the_photograph(world):
    import numpy as np
    s = world["store"]
    pid = make_pair(world)
    with pytest.raises(ig.IngestError, match="not aligned"):
        ig.overlay_png(s, pid)
    ig.check_pair(s, pid)
    raw = cv2.imdecode(np.frombuffer(ig.overlay_png(s, pid, corrected=False), np.uint8), cv2.IMREAD_COLOR)
    plain = cv2.imdecode(np.frombuffer(open(ig.get_pair(s, pid)["photo_path"], "rb").read(), np.uint8), cv2.IMREAD_COLOR)
    scale = raw.shape[1] / plain.shape[1]
    assert scale <= 1.0 and raw.shape[2] == 3
    resized = cv2.resize(plain, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_AREA)
    changed = (np.abs(raw.astype(int) - resized.astype(int)).sum(axis=2) > 30)
    assert 0 < changed.mean() < 0.05  # thin outlines were drawn, the picture is otherwise untouched
    assert len(ig.overlay_png(s, pid, corrected=True)) > 1000
