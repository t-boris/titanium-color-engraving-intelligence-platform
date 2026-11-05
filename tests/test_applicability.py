"""How far a forecast rests on what was measured (feature ux-evidence-summaries-p0, REQ-001): the label above a forecast (measured at this
size, at another width, or on a test scale only) is derived from the curve's own evidence, never assumed; the weakest limit names it and
every limit that applies is listed."""
from __future__ import annotations

import cv2
import pytest

import synth
from titanium_platform import applicability as ap, devices, ingest as ig, prediction as pr, prediction_store as ps, setup as su
from titanium_platform.db import Store


def point(power, row_mm, how="tonal profile", engraving="e1", lab=None):
    source = {"kind": "pair", "id": engraving, "pair_id": engraving, "engraving_id": engraving, "how": how}
    if row_mm is not None:
        source["row_mm"] = row_mm
    return pr.Point(power, lab or (80 - power, 5, 10), source, True)


def curve(row_mm, sizes=(60.0,), how="tonal profile"):
    return pr.curve_at([point(p, size, how, f"e{i}") for i, size in enumerate(sizes) for p in (5, 10, 15)], row_mm)


def test_a_size_that_was_measured_is_measured_here_and_names_nothing_it_does_not_have():
    made = curve(62.0)
    claim = ap.of_size(made.size, ps.prediction_evidence(made)["ramp_only"])
    assert claim["level"] == ap.MEASURED_HERE and claim["limits"] == []
    assert claim["size"] == {"how": "measured", "row_mm": 62.0, "measured_mm": [60.0], "from_mm": [60.0]}


def test_a_size_between_two_measured_ones_or_beyond_them_is_another_width_with_the_sizes_it_comes_from():
    between = curve(90.0, sizes=(60.0, 120.0))
    assert between.size["how"] == pr.BETWEEN
    claim = ap.of_size(between.size)
    assert claim["level"] == ap.OTHER_WIDTH and claim["limits"] == [ap.OTHER_WIDTH] and claim["size"]["from_mm"] == [60.0, 120.0]

    outside = curve(300.0, sizes=(60.0, 120.0))
    assert outside.size["how"] == pr.OUTSIDE
    assert ap.of_size(outside.size)["level"] == ap.OTHER_WIDTH and ap.of_size(outside.size)["size"]["from_mm"] == [120.0]    # never extrapolated


def test_points_that_say_no_size_give_a_width_that_is_unknown_and_never_a_guess():
    made = curve(None, sizes=(None,))
    assert made.size["how"] == pr.UNKNOWN
    assert ap.of_size(made.size)["level"] == ap.UNKNOWN
    assert ap.of_size(None)["level"] == ap.UNKNOWN and ap.of_size(None)["size"]["measured_mm"] == []


def test_a_test_scale_alone_is_test_scale_only_at_any_width_and_the_width_limit_is_kept_beside_it():
    ramp = curve(60.0, how="grey ramp")
    assert ps.prediction_evidence(ramp)["ramp_only"]
    here = ap.of_size(ramp.size, True)
    assert here["level"] == ap.TEST_SCALE_ONLY and here["limits"] == [ap.TEST_SCALE_ONLY]

    wider = ap.of_size(curve(300.0, sizes=(60.0, 120.0), how="grey ramp").size, True)
    assert wider["level"] == ap.TEST_SCALE_ONLY and wider["limits"] == [ap.TEST_SCALE_ONLY, ap.OTHER_WIDTH]

    mixed = pr.curve_at([point(5, 60.0, "grey ramp", "e1"), point(10, 60.0, "tonal profile", "e2")], 60.0)
    assert ps.prediction_evidence(mixed)["ramp_only"] is False
    assert ap.of_size(mixed.size, False)["level"] == ap.MEASURED_HERE            # one observed photograph is more than a test ramp


def test_a_whole_work_claims_the_weakest_of_its_layers_and_zones():
    assert ap.of_counts(0, 0, 0, 0)["level"] == ap.MEASURED_HERE
    assert ap.of_counts(3, 0, 0, 0, zones=2)["level"] == ap.MEASURED_HERE
    layers = ap.of_counts(3, 1, 0, 0)
    assert layers["level"] == ap.OTHER_WIDTH and layers["limits"] == [ap.OTHER_WIDTH] and layers["counts"]["estimated_layers"] == 1
    zones = ap.of_counts(3, 0, 2, 1, zones=4)
    assert zones["level"] == ap.TEST_SCALE_ONLY and zones["limits"] == [ap.TEST_SCALE_ONLY, ap.OTHER_WIDTH]
    assert zones["counts"] == {"layers": 3, "estimated_layers": 0, "zones": 4, "estimated_zones": 2, "ramp_only_zones": 1}


def test_the_counts_a_vector_work_already_keeps_give_the_same_claim():
    kept = {"layers": 3, "estimated_layers": 2, "estimated_zones": 0, "ramp_only_zones": 0}
    assert ap.of_preview(kept) == ap.of_counts(3, 2, 0, 0) and ap.of_preview(kept)["level"] == ap.OTHER_WIDTH
    assert ap.of_preview({**kept, "ramp_only_zones": 1})["level"] == ap.TEST_SCALE_ONLY
    assert ap.of_preview({"layers": 4, "estimated_layers": 0, "estimated_zones": 0, "ramp_only_zones": 0})["limits"] == []


def test_every_level_the_label_can_take_is_named():
    assert set(ap.LEVELS) == {ap.MEASURED_HERE, ap.OTHER_WIDTH, ap.TEST_SCALE_ONLY, ap.UNKNOWN}
    seen = {ap.of_size({"how": how}, ramp)["level"] for how in (pr.MEASURED, pr.BETWEEN, pr.OUTSIDE, pr.UNKNOWN, None) for ramp in (False, True)}
    assert seen == set(ap.LEVELS)


# -- on the description of a prepared layer (what the preview, the vector work and the photo screens read) ---------------------
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    store = Store(tmp_path_factory.mktemp("applicability"))
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    titanium = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")
    for seed in (4, 5):
        work = synth.picture_work(seed=seed, dither="jarvis", max_power=25.0)
        pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name=f"jarvis{seed}.lbrn2", lightburn_bytes=work["lightburn"],
                             photo_name=f"jarvis{seed}.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                             context={"material_id": titanium["id"]})
        assert ig.check_pair(store, pid)["alignment"]["valid"]
        ig.review_masks(store, pid)
        ig.accept_pair(store, pid)
    yield {"store": store, "laser": laser, "titanium": titanium}
    store.close()


def test_the_description_of_a_prepared_layer_carries_the_label_derived_from_its_curve(world):
    work = synth.picture_work(seed=9, dither="jarvis", max_power=25.0)
    item = ps.prepare(world["store"], work["lightburn"], world["laser"]["id"], None, world["titanium"]["id"])[0]
    info, _ = ps.describe(item)

    assert info["prediction_evidence"]["ramp_only"] is False
    assert info["applicability"] == ap.of_size(item["curve"].size, info["prediction_evidence"]["ramp_only"])
    assert info["applicability"]["level"] in (ap.MEASURED_HERE, ap.OTHER_WIDTH, ap.UNKNOWN)
    assert info["applicability"]["size"]["how"] == item["curve"].size["how"] and info["applicability"]["size"]["measured_mm"]
