"""Prediction of a dot mode from what was photographed in it, the spread between independent engravings, and a picture with holes
(REQ-054, DEC-095)."""
import re

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import agreement, devices, ingest as ig, prediction as pr, prediction_store as ps, setup as su
from titanium_platform.db import Store


def point(power, lab, pair, how="tonal profile", referenced=True):
    return pr.Point(power, lab, {"kind": "pair", "id": pair, "pair_id": pair, "how": how}, referenced)


# -- how far independent engravings disagree -----------------------------------------------------------------------------------------
def test_the_spread_is_the_largest_distance_between_the_colours_the_independent_engravings_give_at_a_power():
    points = [point(10, (60, 0, 20), 1), point(20, (40, 0, 10), 1), point(10, (60, 0, 20), 2), point(20, (30, 0, 10), 2)]
    rows = pr.disagreement(points, [10, 15, 20])
    assert [r["engravings"] for r in rows] == [2, 2, 2]
    assert [r["spread_de"] for r in rows] == [0.0, 5.0, 10.0]                       # between pair 1 and pair 2, linear in between


def test_one_engraving_has_no_spread_and_says_how_many_measured_the_power():
    rows = pr.disagreement([point(10, (60, 0, 20), 1), point(20, (40, 0, 10), 1), point(30, (35, 0, 8), 2)], [10, 30])
    assert rows == [{"engravings": 1, "spread_de": None}, {"engravings": 1, "spread_de": None}]


def test_the_layers_of_one_pair_are_one_engraving_not_independent_ones():
    a, b = point(10, (60, 0, 20), 1), pr.Point(10, (30, 0, 20), {"kind": "pair", "id": 1, "pair_id": 1, "how": "flat fill"}, True)
    assert pr.disagreement([a, b], [10])[0]["engravings"] == 1


def test_a_curve_keeps_the_spread_on_every_point_and_interpolates_it_for_a_preview():
    points = [point(p, (80 - p, 0, 10), 1) for p in (10, 20, 30)] + [point(p, (80 - p - (10 if p == 20 else 0), 0, 10), 2) for p in (10, 20, 30)]
    curve = pr.curve(points)
    assert [row["spread_de"] for row in curve.points] == [0.0, 10.0, 0.0] and [row["engravings"] for row in curve.points] == [2, 2, 2]
    assert curve.spread_at([10, 15, 20, 25, 35]).tolist()[:4] == pytest.approx([0.0, 5.0, 10.0, 5.0]) and np.isnan(curve.spread_at(35))


def test_the_preview_names_the_share_of_the_picture_where_engravings_disagree_more_than_they_agree_within():
    points = [point(p, (80 - p, 0, 10), 1) for p in (4, 10, 16)] + [point(p, (80 - p - (12 if p == 10 else 0), 0, 10), 2) for p in (4, 10, 16)]
    curve = pr.curve(points)
    picture = np.tile(np.linspace(0, 1, 64), (16, 1))
    result = pr.render(picture, 4.0, 16.0, curve)
    assert result["spread"]["uncertain"] > 0.5 and result["spread"]["max_de"] == pytest.approx(12.0, abs=0.5)      # the pixels sample the peak
    note = next(n for n in result["notes"] if "independent engravings" in n)
    assert f"more than {agreement.AGREEMENT_DE:g} ΔE" in note and re.search(r"\(up to 1[12](\.\d)?\)", note)
    assert not any("only one engraving" in n for n in result["notes"])


def test_a_curve_of_one_engraving_says_its_repeatability_is_not_known():
    curve = pr.curve([point(p, (80 - p, 0, 10), 1) for p in (4, 10, 16)])
    result = pr.render(np.tile(np.linspace(0, 1, 32), (8, 1)), 4.0, 16.0, curve)
    assert result["spread"]["single"] == 1.0 and any("only one engraving measured" in n for n in result["notes"])


# -- a picture with holes: nothing is predicted where the layer engraves nothing --------------------------------------------------------
def test_a_transparent_part_of_the_picture_is_not_predicted_and_is_shown_blank():
    curve = pr.curve([point(p, (80 - p, 0, 10), 1) for p in (4, 10, 16)] + [point(p, (80 - p, 1, 10), 2) for p in (4, 10, 16)])
    picture = np.tile(np.linspace(0, 1, 40), (10, 1))
    alpha = np.ones_like(picture)
    alpha[:, :10] = 0.0
    result = pr.render(picture, 4.0, 16.0, curve, alpha=alpha)
    assert result["transparent_share"] == pytest.approx(0.25) and not result["covered"][:, :10].any() and result["covered"][:, 10:].all()
    assert (result["rgb8"][:, :10] == pr.BLANK).all() and result["outside_share"] == 0.0
    assert any("25 % of the picture is transparent" in n for n in result["notes"])


# -- a dot mode, from two accepted engravings in that mode -------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    store = Store(tmp_path_factory.mktemp("dots"))
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    titanium = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")
    pairs = []
    for seed in (4, 5):
        work = synth.picture_work(seed=seed, dither="jarvis", max_power=25.0)
        pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name=f"jarvis{seed}.lbrn2", lightburn_bytes=work["lightburn"],
                             photo_name=f"jarvis{seed}.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                             context={"material_id": titanium["id"]})
        assert ig.check_pair(store, pid)["alignment"]["valid"]
        ig.review_masks(store, pid)
        ig.accept_pair(store, pid)
        pairs.append(pid)
    yield {"store": store, "laser": laser, "titanium": titanium, "pairs": pairs}
    store.close()


def prepare(world, work):
    return ps.prepare(world["store"], work["lightburn"], world["laser"]["id"], None, world["titanium"]["id"])[0]


def test_a_picture_in_a_dot_mode_is_predicted_from_the_tones_photographed_in_that_mode(world):
    """The metal of the synthetic engravings takes L* = 8 + 30 x grey; a third picture, never photographed, must come out so."""
    item = prepare(world, synth.picture_work(seed=9, dither="jarvis", max_power=25.0))
    assert item["refused"] is None and item["curve"].axis == pr.TONE_AXIS and item["mode"].dither == "jarvis" and item["mode"].power == 25.0
    assert {s["pair_id"] for row in item["curve"].points for s in row["sources"]} == set(world["pairs"])
    result = pr.render(item["picture"], None, None, item["curve"], item["adjustments"], alpha=item["alpha"])
    error = np.abs(result["lab"][..., 0][result["covered"]] - (8 + 30 * item["picture"][result["covered"]]))
    assert result["covered"].mean() > 0.9 and error.mean() < 3.0, (error.mean(), result["covered"].mean())
    info, image = ps.describe(item)
    assert info["axis"] == "darkness" and info["power_range"] is None and info["refused"] is None
    assert all(row["grey"] is not None for row in info["curve"]["points"]) and any("Dithering is not modelled" in n for n in info["notes"])
    assert image.shape[0] == item["picture"].shape[0]


def test_the_two_engravings_of_the_mode_give_a_spread_at_every_tone_they_share(world):
    item = prepare(world, synth.picture_work(seed=9, dither="jarvis", max_power=25.0))
    spreads = [row["spread_de"] for row in item["curve"].points if row["spread_de"] is not None]
    assert len(spreads) >= 8 and max(spreads) < agreement.AGREEMENT_DE         # the synthetic metal is the same colour at a tone: they agree


def test_a_dot_mode_at_another_power_or_another_mode_has_nothing_measured_and_says_so(world):
    for dither, power in (("jarvis", 20.0), ("stucki", 25.0)):
        item = prepare(world, synth.picture_work(seed=9, dither=dither, max_power=power))
        assert item["refused"] == "no colour has been measured at this mode: there is nothing to predict from", (dither, power)


def test_a_grayscale_layer_does_not_take_the_tones_of_a_dot_mode_for_its_curve(world):
    item = prepare(world, synth.picture_work(seed=9))
    assert item["refused"] == "no colour has been measured at this mode: there is nothing to predict from"


def test_a_threshold_layer_is_refused_because_it_has_no_tones(world):
    item = prepare(world, synth.picture_work(seed=9, dither="threshold", max_power=25.0))
    assert item["refused"].startswith("threshold mode is not predicted: it is a cut at mid grey")


# -- the spread of a sampled colour --------------------------------------------------------------------------------------------------------
def test_a_flat_patch_has_almost_no_spread_and_a_ramp_has_a_wide_one():
    from titanium_platform import photo as ph
    flat = np.full((60, 60, 3), 0.5)
    ramp = np.tile(np.linspace(0.1, 0.9, 60)[None, :, None], (60, 1, 3))
    mask = np.ones((60, 60), bool)
    assert ph.sample_spread(flat, mask) == {"L": 0.0, "chroma": 0.0, "L_range": [pytest.approx(53.4, abs=0.5)] * 2}
    spread = ph.sample_spread(ramp, mask)
    assert spread["L"] > 10 and spread["L_range"][1] - spread["L_range"][0] > 30


def test_a_few_specks_do_not_count_as_spread_and_only_the_masked_pixels_are_read():
    from titanium_platform import photo as ph
    patch = np.full((60, 60, 3), 0.5)
    patch[:2, :2] = 1.0                                              # 4 pixels of 3600
    mask = np.ones((60, 60), bool)
    assert ph.sample_spread(patch, mask)["L"] == 0.0
    picture = np.concatenate([np.full((60, 30, 3), 0.5), np.linspace(0.0, 1.0, 1800).reshape(60, 30, 1).repeat(3, 2)], axis=1)
    left = np.zeros((60, 60), bool)
    left[:, :30] = True
    assert ph.sample_spread(picture, left)["L"] == 0.0 and ph.sample_spread(picture, ~left)["L"] > 10
