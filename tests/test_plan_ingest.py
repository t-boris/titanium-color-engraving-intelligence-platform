"""A photograph of an engraving made from a plan of this system closes the loop (REQ-013): the file names its plan, the
photograph is aligned by the plan's markers or by four corners, and the analysis compares it with the planned colours."""
import json

import cv2
import numpy as np
import pytest

import obs
import synth
from titanium_platform import analysis as an, capability_plates as cp, color, conversion as cv, ingest as ig, knowledge as kn
from titanium_platform import lightburn as lb, plans as pl, registration, setup as su

RED_LAB = (45.0, 60.0, 40.0)
BLUE_LAB = (35.0, 20.0, -50.0)
CELLS = {"r1c1": (200, 60, 60), "r1c2": (60, 200, 60), "r2c1": (60, 60, 200), "r2c2": (200, 200, 60)}


def rgb_of(lab):
    return tuple(int(v) for v in color.lab_to_srgb8(lab))


def stripes(*rgbs, size=(60, 120)) -> bytes:
    h, w = size
    img = np.zeros((h, w, 3), np.uint8)
    step = w // len(rgbs)
    for i, rgb in enumerate(rgbs):
        img[:, i * step:(i + 1) * step if i < len(rgbs) - 1 else w] = rgb[::-1]
    return cv2.imencode(".png", img)[1].tobytes()


def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def w(store):
    store.set_setting("allow_non_raw_photos", True)        # tests use PNG renders; real use requires RAW
    w = obs.setup(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *w["setup"], criteria_agreed=True)
    for power, base in ((10, RED_LAB), (30, BLUE_LAB)):
        for dl in (-1.0, 1.0):
            obs.add(store, w, (base[0] + dl, base[1], base[2]), power=power)
    kn.refresh(store, *w["setup"])
    pl.save_marker_layer_settings(store, 20, 60, 300)
    w["material"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    w["store"] = store
    return w


def discrete_plan(w, markers: bool) -> dict:
    pid = cv.start_discrete(w["store"], *w["setup"], stripes(rgb_of(RED_LAB), rgb_of(BLUE_LAB)), 40, "Stripes", threshold=8.0, markers=markers)
    return cv.finalize_discrete(w["store"], pid)


def engraved_as_planned(plan: dict, shift=(1.5, 0.0, 0.0)) -> dict:
    """The colour of every layer: its planned colour, a little off, as a real engraving would come out."""
    return {layer["name"]: rgb_of(np.add(layer["prediction"]["lab"], shift)) for layer in plan["layers"]}


def upload(w, plan: dict, photo: bytes, plan_id=None) -> int:
    return ig.create_pair(w["store"], device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"],
                          lightburn_name="stripes.lbrn2", lightburn_bytes=pl.export_lbrn2(plan), photo_name="stripes.png",
                          photo_bytes=photo, plan_id=plan_id, context={"material_id": w["material"]["id"]})


def test_a_marked_discrete_plan_closes_the_loop_from_its_file_to_a_deviation_report(w):
    s = w["store"]
    plan = discrete_plan(w, markers=True)
    assert plan["markers_enabled"] and plan["plan_identifier"].startswith("TCE-A-")
    pid = upload(w, plan, png(synth.plate_photo(plan, engraved_as_planned(plan))))

    report = ig.check_pair(s, pid)

    assert report["problems"] == [], report["problems"]
    assert report["alignment"]["method"] == "markers" and report["alignment"]["identifier_verified"]
    assert report["plan"]["identifier"] == plan["plan_identifier"] and report["lens"]["warnings"] == []
    assert report["color_measurement"]["mode"] == "reference_chart_corrected"
    pair = ig.get_pair(s, pid)
    assert pair["plan_id"] == plan["id"] and pair["plate_id"] is None
    roles = {layer["name"]: layer["role"] for layer in report["layers"]}
    assert roles["Markers"] == "registration, QR and engraved labels"
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    rows = s.query("SELECT layer_index, alignment_method, model_eligible FROM observation WHERE pair_id=? ORDER BY layer_index", (pid,))
    assert {r["alignment_method"] for r in rows} == {"markers"}
    assert [r["model_eligible"] for r in rows] == [0, 1, 1]          # the marker layer never feeds the model (DEC-027)

    result = an.report_for_pair(s, pid)

    assert result["mode"] == pl.MODE_DISCRETE and result["plan_id"] == plan["id"]
    measured = [row for row in result["rows"] if row["role"] == "test feature"]
    assert len(measured) == 2 and all(row["planned_lab"] is not None for row in measured)
    assert all(1.0 < row["delta_e"] < 4.0 and row["within_tolerance"] for row in measured)
    assert result["metrics"]["kind"] == "color_deviation" and result["metrics"]["layers"] == 2
    marker_row = next(row for row in result["rows"] if row["role"] != "test feature")
    assert marker_row["planned_lab"] is None and "note" not in marker_row   # a system layer is not a planned colour


def test_an_unmarked_plan_is_identified_by_its_file_and_aligned_by_four_corners(w, monkeypatch):
    s = w["store"]
    plan = discrete_plan(w, markers=False)
    assert not plan["markers_enabled"]
    pid = upload(w, plan, png(synth.plate_photo(plan, engraved_as_planned(plan))))
    monkeypatch.setattr(ig.ph, "detect_marker_candidates", lambda *_: pytest.fail("an unmarked plan has no markers to look for"))

    report = ig.check_pair(s, pid, corners=synth.work_corners(plan))

    assert report["problems"] == [], report["problems"]
    assert report["alignment"]["method"] == "manual" and report["plan"]["identifier"] == plan["plan_identifier"]
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    assert {r["alignment_method"] for r in s.query("SELECT alignment_method FROM observation WHERE pair_id=?", (pid,))} == {"manual"}
    result = an.report_for_pair(s, pid)
    assert result["plan_id"] == plan["id"] and len(result["rows"]) == 2
    assert all(row["delta_e"] < 4.0 for row in result["rows"])
    assert any("aligned manually" in text for text in result["limitations"])


def test_a_plan_made_for_another_laser_blocks_the_pair(w):
    from titanium_platform import devices
    s = w["store"]
    plan = discrete_plan(w, markers=True)
    other = devices.create_from_template(s, "jpt-ydflp-e-60-m7-m-r", "Second laser")
    pid = ig.create_pair(s, device_id=other["id"], lens_id=None, stand_id=w["stand"]["id"], lightburn_name="stripes.lbrn2",
                         lightburn_bytes=pl.export_lbrn2(plan), photo_name="stripes.png", context={"material_id": w["material"]["id"]},
                         photo_bytes=png(synth.plate_photo(plan, engraved_as_planned(plan))))
    report = ig.check_pair(s, pid)
    assert "this plan was made for a different laser than the one selected" in report["problems"]
    assert any("the plan was made with" in warning for warning in report["lens"]["warnings"])


def test_a_photograph_cannot_be_linked_to_a_plan_that_does_not_exist(w):
    with pytest.raises(ig.IngestError, match="was not found"):
        upload(w, discrete_plan(w, markers=False), png(synth.scene()), plan_id=999)


# -- four markers and an unreadable identifier (REQ-003) -------------------------------------------------------------
@pytest.fixture
def plate(w):
    out = pl.create_plate_series(w["store"], w["setup"][0], "10 20", "40 80", "900", 5, 4, 1, pulse_width=200, line_interval=0.025, passes=1)[0]
    return pl.get_plan(w["store"], out["plan_id"])


def unreadable_identifier(monkeypatch):
    """The four engraved markers are found, the QR code is not legible."""
    monkeypatch.setattr(ig.ph, "detect_marker_candidates", lambda *_: [])
    monkeypatch.setattr(ig, "_read_aligned_identifier", lambda *_: None)


def test_four_markers_without_a_legible_identifier_are_refused_and_leave_corner_placement(w, plate, monkeypatch):
    s = w["store"]
    unreadable_identifier(monkeypatch)
    pid = upload(w, plate, png(synth.plate_photo(plate, CELLS)))

    report = ig.check_pair(s, pid)

    assert not report["alignment"]["valid"] and report["alignment"]["identifier_unreadable"]
    assert report["alignment"]["marker_count"] == 4
    assert any(p.startswith("Alignment: four registration markers match the LightBurn geometry") for p in report["problems"])
    assert ig.get_pair(s, pid)["status"] == ig.ST_CORRECTION
    ext, scale, (ox, oy) = plate["markers"]["extent"], 20.0, (520, 80)
    corners = [(ox, oy), (ox + (ext["max_x"] - ext["min_x"]) * scale, oy),
               (ox + (ext["max_x"] - ext["min_x"]) * scale, oy + (ext["max_y"] - ext["min_y"]) * scale),
               (ox, oy + (ext["max_y"] - ext["min_y"]) * scale)]
    placed = ig.check_pair(s, pid, corners=corners)
    assert placed["alignment"]["valid"] and placed["alignment"]["method"] == "manual" and placed["problems"] == []


def test_four_markers_without_a_legible_identifier_are_accepted_for_the_plate_the_operator_chose(w, plate, monkeypatch):
    unreadable_identifier(monkeypatch)
    pid = upload(w, plate, png(synth.plate_photo(plate, CELLS)), plan_id=plate["id"])

    report = ig.check_pair(w["store"], pid)

    assert report["alignment"]["valid"] and report["alignment"]["marker_count"] == 4
    assert report["alignment"]["identifier_verified"] is False and report["problems"] == []
    assert any("QR identifier is unreadable" in warning for warning in report["warnings"])


def test_a_rephotograph_keeps_the_identity_its_engraving_was_accepted_with(w, plate, monkeypatch):
    s = w["store"]
    pid = upload(w, plate, png(synth.plate_photo(plate, CELLS)))
    ig.check_pair(s, pid)
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    again = ig.create_rephoto(s, pid, photo_name="again.png", photo_bytes=png(synth.plate_photo(plate, CELLS)))
    unreadable_identifier(monkeypatch)
    assert ig.check_pair(s, again)["alignment"]["valid"]


def test_an_unmarked_small_patch_plate_is_never_aligned_by_markers(w, monkeypatch):
    s = w["store"]
    titanium = w["material"]
    made = cp.create(s, w["setup"][0], titanium["id"], "small_patches",
                     {"pulse_width": 200, "patch_size_mm": 3, "registration": "none", "max_width_mm": 6, "max_height_mm": 6})
    plan = pl.get_plan(s, made["plan_id"])
    assert plan["markers"] is None
    photo = synth.plate_photo(plan, {layer["name"]: (90, 60, 150) for layer in plan["layers"]}, scale=60.0, with_chart=False)
    pid = upload(w, plan, png(photo))
    monkeypatch.setattr(ig.ph, "detect_marker_candidates", lambda *_: pytest.fail("no markers were engraved"))
    monkeypatch.setattr(registration, "register_markers", lambda *_a, **_k: pytest.fail("no markers were engraved"))

    report = ig.check_pair(s, pid, corners=synth.work_corners(plan, scale=60.0))

    assert report["problems"] == [], report["problems"]
    assert report["alignment"]["method"] == "manual" and report["plate"]["experiment_id"] == made["identifier"]
    patch = next(layer for layer in report["layers"] if layer["role"] == "test feature")
    assert patch["measured_lab"] is not None
    project = lb.parse_bytes(pl.export_lbrn2(plan))
    assert project.identifier == made["identifier"]


# -- an imported work becomes a restored plan (REQ-005, REQ-006) -----------------------------------------------------
def imported(plan: dict) -> bytes:
    """The file of a plan saved without its identifier: to this system it is an imported work."""
    return pl.export_lbrn2(plan).replace(f"TCE1:{plan['plan_identifier']}".encode(), b"")


def import_and_accept(w, plan: dict, colours: dict) -> int:
    s = w["store"]
    pid = ig.create_pair(s, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="imported.lbrn2",
                         lightburn_bytes=imported(plan), photo_name="imported.png", photo_bytes=png(synth.plate_photo(plan, colours)),
                         context={"material_id": w["material"]["id"]})
    report = ig.check_pair(s, pid, corners=synth.work_corners(plan))
    assert report["problems"] == [], report["problems"]
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    kn.refresh(s, *w["setup"])
    return pid


def test_an_imported_work_is_restored_as_a_plan_and_judged_against_the_predictions_of_its_time(w):
    s = w["store"]
    plan = discrete_plan(w, markers=False)
    colours = engraved_as_planned(plan, shift=(0.0, 0.0, 0.0))
    first = import_and_accept(w, plan, colours)
    pair = ig.get_pair(s, first)
    restored = pl.get_plan(s, pair["plan_id"])
    assert (restored["mode"], restored["status"], pair["plan_mode"]) == (pl.MODE_RESTORED, pl.ST_RESTORED, pl.MODE_RESTORED)
    assert restored["restored"]["pair_id"] == first and restored["lens_id"] == w["setup"][1] and restored["plan_identifier"] is None
    project = lb.parse_bytes(imported(plan))
    assert [(l["index"], l["name"], l["parameters"]["power"], l["parameters"]["frequency"], l["parameters"]["speed"],
             l["parameters"]["pulse_width"], l["parameters"]["line_interval"], l["parameters"]["passes"], len(l["regions"]))
            for l in restored["layers"]] == [(l.index, l.name, l.power, l.frequency_khz, l.speed, l.pulse_width, l.line_interval,
                                               l.passes, len(l.regions)) for l in project.layers if l.regions]
    assert all(l["prediction"] is None for l in restored["layers"])          # nothing was known of these settings yet
    first_report = an.report_for_pair(s, first)
    assert first_report["mode"] == pl.MODE_RESTORED and all(r["planned_lab"] is None for r in first_report["rows"])
    assert all(r["note"].startswith("no prediction") for r in first_report["rows"])
    import_and_accept(w, plan, colours)                                        # a second engraving: the settings get estimates
    third = import_and_accept(w, plan, engraved_as_planned(plan, shift=(3.0, 0.0, 0.0)))
    later = pl.get_plan(s, ig.get_pair(s, third)["plan_id"])
    assert later["id"] != restored["id"] and all(l["prediction"] is not None and l["knowledge_id"] for l in later["layers"])
    report = an.report_for_pair(s, third)
    assert report["metrics"]["kind"] == "color_deviation" and report["metrics"]["layers"] == 2
    assert all(2.0 < r["delta_e"] < 4.5 for r in report["rows"])              # measured against the colour predicted at the time
    assert any(t.startswith("the plan was restored from the imported LightBurn file") for t in report["limitations"])
    assert pl.get_plan(s, restored["id"])["layers"] == restored["layers"]      # an older restored plan keeps its own predictions


def test_a_layer_without_its_settings_is_restored_as_it_is_without_a_prediction(w):
    lbrn = (b'<LightBurnProject AppVersion="2.0.04"><CutSetting type="Scan"><index Value="5"/><name Value="C05"/>'
            b'<maxPower Value="24"/><speed Value="900"/></CutSetting>'
            b'<Shape Type="Rect" CutIndex="5" W="40" H="20" Cr="0"><XForm>1 0 0 1 30 20</XForm></Shape></LightBurnProject>')
    pid = ig.create_pair(w["store"], device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="old.lbrn2",
                         lightburn_bytes=lbrn, photo_name="old.png", photo_bytes=png(synth.scene()), context={"material_id": w["material"]["id"]})
    layer = pl.get_plan(w["store"], ig.get_pair(w["store"], pid)["plan_id"])["layers"][0]
    assert (layer["parameters"]["power"], layer["parameters"]["frequency"], layer["prediction"]) == (24, None, None)


def test_a_file_of_this_system_or_a_linked_plan_restores_nothing(w):
    s = w["store"]
    plan = discrete_plan(w, markers=False)
    own = upload(w, plan, png(synth.scene()))
    assert ig.get_pair(s, own)["plan_id"] is None                             # it names its plan; the check links it
    linked = upload(w, plan, png(synth.scene()), plan_id=plan["id"])
    assert ig.get_pair(s, linked)["plan_id"] == plan["id"]
    assert s.one("SELECT COUNT(*) AS n FROM plan WHERE mode=?", (pl.MODE_RESTORED,))["n"] == 0


def test_a_restored_plan_follows_a_replaced_file_and_leaves_with_the_last_of_its_photographs(w):
    s = w["store"]
    plan = discrete_plan(w, markers=False)
    pid = ig.create_pair(s, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="a.lbrn2",
                         lightburn_bytes=imported(plan), photo_name="a.png", photo_bytes=png(synth.scene()),
                         context={"material_id": w["material"]["id"]})
    restored = ig.get_pair(s, pid)["plan_id"]
    ig.replace_lightburn_file(s, pid, "b.lbrn2", imported(plan).replace(b'<maxPower Value="10"/>', b'<maxPower Value="12"/>', 1))
    assert ig.get_pair(s, pid)["plan_id"] == restored
    assert pl.get_plan(s, restored)["layers"][0]["parameters"]["power"] == 12 and pl.get_plan(s, restored)["restored"]["lightburn_name"] == "b.lbrn2"
    ig.replace_lightburn_file(s, pid, "own.lbrn2", pl.export_lbrn2(plan))      # now the file names its plan: no restored plan
    assert ig.get_pair(s, pid)["plan_id"] is None and s.one("SELECT COUNT(*) AS n FROM plan WHERE id=?", (restored,))["n"] == 0
    again = ig.create_pair(s, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="c.lbrn2",
                           lightburn_bytes=imported(plan), photo_name="c.png", photo_bytes=png(synth.scene()),
                           context={"material_id": w["material"]["id"]})
    record = ig.get_pair(s, again)["plan_id"]
    ig.delete_pair(s, again)
    assert s.one("SELECT status FROM plan WHERE id=?", (record,))["status"] == "Deleted"


def test_a_file_that_names_another_work_than_the_one_chosen_is_linked_to_its_own_work_and_says_so(w):
    s = w["store"]
    chosen, own = discrete_plan(w, markers=False), discrete_plan(w, markers=False)
    pid = upload(w, own, png(synth.scene()), plan_id=chosen["id"])
    assert ig.get_pair(s, pid)["plan_id"] == chosen["id"]                       # until the check reads the file
    report = ig.check_pair(s, pid)
    assert any("not to" in text and "the work chosen for this photograph" in text for text in report["warnings"]), report["warnings"]
    pair = ig.get_pair(s, pid)
    assert pair["plan_id"] == own["id"] and pair["plan_name"] == own["name"]     # the file's own identifier decides
    same = upload(w, own, png(synth.scene()), plan_id=own["id"])
    assert not any("the work chosen for this photograph" in text for text in ig.check_pair(s, same)["warnings"])
    bare = upload(w, own, png(synth.scene()))
    assert ig.get_pair(s, bare)["plan_name"] is None and not any("chosen" in text for text in ig.check_pair(s, bare)["warnings"])
