"""A framed, unmarked work through the whole pair check (REQ-024, DEC-048, DEC-049)."""
import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color
from titanium_platform import ingest as ig
from titanium_platform import profiles as pf
from titanium_platform.db import Store

from test_anchoring import circle


@pytest.fixture(scope="module")
def work():
    return synth.framed_work(seed=3, blobs=60, with_chart=True, extra=[(5, circle(11.0, 80.0, 0.7, 16)), (6, circle(16.0, 120.0, 5.5))])


@pytest.fixture(scope="module")
def world(tmp_path_factory, work):
    """One pair, checked once: the check takes a few seconds and every test below only reads its report."""
    store = Store(tmp_path_factory.mktemp("framed"))
    store.set_setting("allow_non_raw_photos", True)  # tests use PNG renders; real use requires RAW
    profile = pf.create_profile(store, "MOPA", 200, 0.025, 1)
    material = pf.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    pid = ig.create_pair(store, profile_id=profile["id"], lightburn_name="framed.lbrn2", lightburn_bytes=work["lightburn"],
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
    profile = pf.create_profile(store, "MOPA", 200, 0.025, 1)
    material = pf.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    pid = ig.create_pair(store, profile_id=profile["id"], lightburn_name="x.lbrn2", lightburn_bytes=work["lightburn"],
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
