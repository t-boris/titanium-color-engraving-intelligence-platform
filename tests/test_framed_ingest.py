"""A framed, unmarked work through the whole pair check (REQ-024, DEC-048, DEC-049)."""
import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color
from titanium_platform import ingest as ig
from titanium_platform import devices
from titanium_platform import setup as su
from titanium_platform.db import Store

from test_anchoring import circle


@pytest.fixture(scope="module")
def work():
    # the tiled regions stop 8 mm short of the plate edge: a ring of the cleaned plate stays visible (the clean reference)
    return synth.framed_work(seed=3, blobs=60, with_chart=True, inset=8.0, extra=[(5, circle(11.0, 80.0, 0.7, 16)), (6, circle(16.0, 120.0, 5.5))])


@pytest.fixture(scope="module")
def world(tmp_path_factory, work):
    """One pair, checked once: the check takes a few seconds and every test below only reads its report."""
    store = Store(tmp_path_factory.mktemp("framed"))
    store.set_setting("allow_non_raw_photos", True)  # tests use PNG renders; real use requires RAW
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
    pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name="framed.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name="framed.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                         context={"material_id": material["id"]})
    yield store, pid, ig.check_pair(store, pid)
    store.close()


@pytest.fixture
def pair(world):
    return world[0], world[1]


@pytest.fixture
def report(world):
    return world[2]


def test_the_check_aligns_by_element_anchors_and_reports_the_frame(report):
    alignment = report["alignment"]
    assert alignment["valid"], report["problems"]
    assert alignment["method"] == "element anchors" and alignment["reflected"]
    assert len(alignment["window_px"]) == 4
    assert alignment["anchoring"]["details"]["counts"]["anchor"] >= 8
    assert any("The frame hides part of the work" in w for w in report["warnings"])


def test_layers_with_elements_under_the_frame_say_so(report):
    layers = {rep["index"]: rep for rep in report["layers"]}
    assert layers[5]["frame"]["hidden"] >= 1 and any("under the frame" in n for n in layers[5]["notes"])
    assert layers[6]["frame"]["partly_hidden"] >= 1


def test_the_visible_layer_is_measured_in_its_own_colour_not_the_frames(report, work):
    top = max(rep["index"] for rep in report["layers"] if rep["regions"])
    measured = {rep["index"]: rep for rep in report["layers"]}[top]["measured_lab"]
    b, g, r = work["palette"][(top - 1) % 12]
    expected = color.srgb8_to_lab(np.array([r, g, b], float))
    assert measured is not None and color.delta_e(measured, expected) < 12


def test_the_frame_window_limits_the_measured_surface(pair, report):
    store, pid = pair
    window = np.round(np.array(report["alignment"]["window_px"])).astype(int)
    shape = (report["image_size"][1], report["image_size"][0])
    mask = ig._visible_surface_mask(shape, report["alignment"])
    outside = np.ones(shape, np.uint8)
    cv2.fillConvexPoly(outside, window, 0)
    assert not mask[outside > 0].any()                                   # nothing under the frame is measured
    assert mask[tuple(window.mean(axis=0).astype(int)[::-1])]            # the middle of the window is


def test_the_overlay_draws_the_part_under_the_frame_in_its_own_colour(pair, report):
    store, pid = pair
    png = ig.overlay_png(store, pid, corrected=False)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    magenta = (img[..., 0] > 200) & (img[..., 1] < 120) & (img[..., 2] > 200)
    assert magenta.sum() > 50


def test_a_layer_is_not_sampled_where_a_later_layer_engraves_over_it(tmp_path):
    """Layer 1 is a big square, 86% of which a later layer 2 engraves over in another colour (DEC-050)."""
    square = [(40, 40), (110, 40), (110, 110), (40, 110)]
    cover = [(35, 35), (100, 35), (100, 115), (35, 115)]
    spots = [(25, 25, 6), (85, 22, 7), (145, 28, 8), (22, 88, 9), (148, 84, 10), (28, 143, 11), (88, 148, 12), (143, 140, 13)]
    extra = [(1, np.array(square, float)), (2, np.array(cover, float))]
    extra += [(3 + i, circle(x, y, r, 48)) for i, (x, y, r) in enumerate(spots)]
    work = synth.framed_work(style="none", extra=extra, with_chart=True)
    store = Store(tmp_path)
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
    pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name="x.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name="x.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                         context={"material_id": material["id"]})
    report = ig.check_pair(store, pid)
    assert report["alignment"]["valid"], (report["problems"], report["alignment"].get("anchoring"))
    layers = {rep["index"]: rep for rep in report["layers"]}
    assert layers[1]["covered_by_later_layers_percent"] > 50
    assert layers[2].get("covered_by_later_layers_percent", 0) == 0
    b, g, r = work["palette"][0]
    own = color.srgb8_to_lab(np.array([r, g, b], float))
    b, g, r = work["palette"][1]
    cover_colour = color.srgb8_to_lab(np.array([r, g, b], float))
    lab = layers[1]["measured_lab"]
    assert lab is not None and color.delta_e(lab, own) < color.delta_e(lab, cover_colour)      # sampled where it is still itself
    store.close()


def test_a_checked_framed_pair_can_be_reviewed_and_accepted_into_observations(world):
    """The whole path of a framed work: check, review of the masks, acceptance, immutable observations."""
    store, pid, report = world
    assert report["alignment"]["valid"] and not report["problems"]
    ig.review_masks(store, pid)
    ids = ig.accept_pair(store, pid)
    assert len(ids) >= 5
    rows = store.query("SELECT alignment_method, parameters_json, lab_json FROM observation WHERE pair_id=?", (pid,))
    assert {r["alignment_method"] for r in rows} == {"element anchors"}
    import json
    for row in rows:
        settings = json.loads(row["parameters_json"]).get("source_settings", {})
        assert "priority" not in settings                  # the run order is job context, not part of the recipe (DEC-051)
        assert len(json.loads(row["lab_json"])) == 3


# -- a finished work without a reference chart (DEC-053) ---------------------------------------------------------
@pytest.fixture
def chartless(tmp_path):
    work = synth.framed_work(seed=3, blobs=60, with_chart=False, inset=8.0)
    store = Store(tmp_path)
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
    pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name="work.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name="work.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                         context={"material_id": material["id"]})
    yield store, pid
    store.close()


def test_a_finished_work_without_a_chart_is_measured_relative_to_the_camera(chartless):
    store, pid = chartless
    report = ig.check_pair(store, pid)
    assert report["problems"] == [] and report["alignment"]["method"] == "element anchors"
    assert report["color_measurement"] == {"mode": "raw_camera_relative", "reference_chart_used": False, "relative": True}
    assert any(w.startswith("Finished work measured from decoded RAW") for w in report["warnings"])


def test_colours_of_a_chartless_photograph_are_also_given_against_the_clean_titanium_of_that_photograph(chartless):
    """An underexposed photograph makes every camera-relative colour dark; the ratio to the cleaned plate in the same
    photograph does not depend on the exposure (DEC-056), so every colour is also expressed next to nominal clean titanium."""
    store, pid = chartless
    report = ig.check_pair(store, pid)
    ref = report["clean_reference"]
    assert ref["layer_index"] == 0 and ref["nominal_source"] == "default" and len(ref["nominal"]) == 3
    witness = {rep["index"]: rep for rep in report["layers"]}[0]
    assert "measured_lab_against_clean" not in witness                     # the reference itself is not re-expressed
    measured = [rep for rep in report["layers"] if rep.get("measured_lab") and rep["index"] != 0]
    assert measured and all(rep.get("measured_lab_against_clean") for rep in measured)
    for rep in measured:                                                   # lighter than the clean plate stays lighter, darker darker
        assert (rep["measured_lab_against_clean"][0] > ref["nominal"][0]) == (rep["measured_lab"][0] > ref["lab"][0])
    assert ig.get_pair(store, pid)["check"]["clean_reference"] == ref      # derived on every read, not only on the check


def test_such_observations_are_kept_as_evidence_and_never_enter_the_colour_model(chartless):
    store, pid = chartless
    ig.check_pair(store, pid)
    ig.review_masks(store, pid)
    ids = ig.accept_pair(store, pid)
    rows = store.query("SELECT model_eligible, eligibility_reason FROM observation WHERE pair_id=?", (pid,))
    assert len(ids) >= 5 and {r["model_eligible"] for r in rows} == {0}
    assert all("excluded from standard-color predictions" in r["eligibility_reason"] for r in rows)


def test_the_strict_rule_of_req_009_comes_back_with_the_setting(chartless):
    store, pid = chartless
    store.set_setting("allow_relative_finished_works", False)
    report = ig.check_pair(store, pid)
    assert any("Reference chart not detected" in p for p in report["problems"])


def test_the_cleaning_rectangle_of_a_finished_work_is_its_clean_titanium_reference(report):
    layers = {rep["index"]: rep for rep in report["layers"]}
    assert layers[0]["role"] == "pre-test cleaning witness" and layers[1]["role"] == "test feature"
    assert layers[0]["measured_lab"] is not None                  # the plate's own clean surface, measured where nothing was engraved over it


def test_the_witness_becomes_observation_minus_one_and_the_colours_keep_their_layer_index(pair):
    store, pid = pair                                            # accepted by the test above
    indices = sorted(r["layer_index"] for r in store.query("SELECT layer_index FROM observation WHERE pair_id=?", (pid,)))
    assert indices.count(-1) == 1 and 0 not in indices and max(indices) >= 5


def test_a_cleaning_layer_engraved_over_entirely_is_not_measured_and_says_so(tmp_path):
    """Every square millimetre of the plate is engraved by layer 1: nothing of the first layer shows, so it is not a
    clean reference and must not fall into the narrow-stroke fallback that would sample the whole plate."""
    cover = [(10, 10), (160, 10), (160, 160), (10, 160)]
    spots = [(25, 25, 6), (85, 22, 7), (145, 28, 8), (22, 88, 9), (148, 84, 10), (28, 143, 11), (88, 148, 12), (143, 140, 13), (85, 85, 14)]
    extra = [(1, np.array(cover, float))] + [(2 + i % 3, circle(x, y, r, 48)) for i, (x, y, r) in enumerate(spots)]
    work = synth.framed_work(style="none", extra=extra, with_chart=True)
    store = Store(tmp_path)
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
    pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name="x.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name="x.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                         context={"material_id": material["id"]})
    report = ig.check_pair(store, pid)
    assert report["alignment"]["valid"], (report["problems"], report["alignment"].get("anchoring"))
    witness = {rep["index"]: rep for rep in report["layers"]}[0]
    assert witness["role"] == "pre-test cleaning witness" and witness["measured_lab"] is None
    assert any("engraved over entirely" in n for n in witness["notes"])
    assert "clean_reference" not in report
    store.close()
