import cv2
import numpy as np
import pytest

import obs
from titanium_platform import color, conversion as cv, knowledge as kn, lightburn as lb, plans as pl, profiles as pf

# Four measured colours with distinct lightness. Each comes from two engravings 2 apart in L (a=b=0).
LIGHTNESS = {10: 20.0, 20: 40.0, 30: 60.0, 40: 80.0}   # power -> L


def gradient_png(width=100, height=20) -> bytes:
    """A horizontal grey ramp from black to white."""
    row = np.linspace(0, 255, width).astype(np.uint8)
    return cv2.imencode(".png", np.tile(row, (height, 1)))[1].tobytes()


def flat_png(gray=128) -> bytes:
    return cv2.imencode(".png", np.full((20, 40), gray, np.uint8))[1].tobytes()


@pytest.fixture
def w(store):
    w = obs.setup(store)
    pid = w["profile"]["id"]
    pf.save_rules(store, pid, repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    pf.save_rules(store, pid, criteria_agreed=True)
    for power, l in LIGHTNESS.items():
        for dl in (-1.0, 1.0):
            obs.add(store, w, (l + dl, 0.0, 0.0), power=power)
    kn.refresh(store, pid)
    w["ids"] = {k["parameters"]["power"]: k["id"] for k in kn.list_for_profile(store, pid)}
    return w


def test_tonal_curve_is_monotonic_in_measured_lightness_and_normalised(store, w):
    entries = cv.eligible_palette(store, w["profile"]["id"])
    t = cv.build_transfer("tonal", list(reversed(entries)))  # input order must not matter
    assert [p["knowledge_id"] for p in t["points"]] == [w["ids"][p] for p in (10, 20, 30, 40)]
    assert [round(p["position"], 6) for p in t["points"]] == [0.0, round(1 / 3, 6), round(2 / 3, 6), 1.0]


def test_tonal_needs_two_colors_with_different_lightness(store):
    w = obs.setup(store)
    with pytest.raises(cv.ConversionError, match="at least two"):
        cv.build_transfer("tonal", [])


def test_band_assignment_follows_the_hand_computed_midpoints(store, w):
    t = cv.build_transfer("tonal", cv.eligible_palette(store, w["profile"]["id"]))
    # N=4 band middles 0.125, 0.375, 0.625, 0.875 against positions 0, 1/3, 2/3, 1 -> entries 10, 20, 30, 40
    assert cv.band_entries(t, 4) == [w["ids"][p] for p in (10, 20, 30, 40)]
    # N=2 band middles 0.25 and 0.75 -> nearest are 1/3 (entry 20) and 2/3... 0.75 is nearer 2/3 than 1
    assert cv.band_entries(t, 2) == [w["ids"][20], w["ids"][30]]
    # N=1: middle 0.5 is exactly between 1/3 and 2/3; the tie goes to the lower position
    assert cv.band_entries(t, 1) == [w["ids"][20]]


def test_quantisation_puts_black_in_the_first_band_and_white_in_the_last():
    img = cv2.cvtColor(cv2.imdecode(np.frombuffer(gradient_png(), np.uint8), 1), cv2.COLOR_BGR2RGB)
    bands = cv.quantize_luminance(img, 8)
    assert bands.min() == 0 and bands.max() == 7 and (np.diff(bands[0]) >= 0).all()  # monotonic along the ramp
    white = cv.quantize_luminance(np.full((2, 2, 3), 255, np.uint8), 8)
    assert (white == 7).all()


def test_a_tonal_preview_makes_n_layers_that_tile_the_image_and_carry_estimates(store, w):
    p = cv.preview_continuous(store, w["profile"]["id"], "tonal", gradient_png(), 50, 32)
    assert len(p["layers"]) == 32 and p["distinct_entries"] == 4
    area = sum(r["width"] * r["height"] for l in p["layers"] for r in l["regions"])
    assert area == pytest.approx(p["size_mm"]["width"] * p["size_mm"]["height"], rel=1e-6)
    assert all(set(l["prediction"]) == {"lab", "confidence", "expected_delta_e", "stability"} for l in p["layers"])
    powers = [l["parameters"]["power"] for l in p["layers"]]
    assert powers == sorted(powers)  # darker bands never get a brighter measured set: the curve is monotonic
    shares = [l["share"] for l in p["layers"]]
    assert sum(shares) == pytest.approx(1.0) and min(shares) > 0


def test_creating_a_32_band_plan_exports_32_layers_with_their_own_parameters(store, w):
    pid = cv.create_continuous(store, w["profile"]["id"], "tonal", gradient_png(200), 60, 32, "Portrait")
    plan = pl.get_plan(store, pid)
    assert plan["mode"] == pl.MODE_TONAL and plan["band_count"] == 32 and plan["status"] == cv.ST_READY
    project = lb.parse_bytes(pl.export_lbrn2(plan))
    assert len(project.layers) == 32
    assert {(l.power, l.frequency_khz, l.speed) for l in project.layers} == {(p, 40.0, 900.0) for p in (10.0, 20.0, 30.0, 40.0)}


@pytest.mark.parametrize("n,msg", [(0, "positive"), (-3, "positive"), (2.5, "positive"), (256, "layers")])
def test_the_band_count_is_validated(store, w, n, msg):
    with pytest.raises(cv.ConversionError, match=msg):
        cv.preview_continuous(store, w["profile"]["id"], "tonal", gradient_png(), 50, n)


def test_color_path_follows_the_operators_ordered_trajectory(store, w):
    ids = [w["ids"][p] for p in (40, 10, 30)]  # an order that is NOT sorted by lightness
    entries = cv.eligible_palette(store, w["profile"]["id"])
    t = cv.build_transfer("color_path", entries, ids)
    assert [p["knowledge_id"] for p in t["points"]] == ids
    # delta E steps: 40->10 = 60, 10->30 = 40: cumulative 0, 0.6, 1.0
    assert [round(p["position"], 6) for p in t["points"]] == [0.0, 0.6, 1.0]
    p = cv.preview_continuous(store, w["profile"]["id"], "color_path", gradient_png(), 50, 8, path_ids=ids)
    used = {l["parameters"]["power"] for l in p["layers"]}
    assert used <= {40, 10, 30} and 20 not in used


@pytest.mark.parametrize("ids_fn,msg", [(lambda i: [i[10]], "at least two"), (lambda i: [i[10], i[10]], "at least two"), (lambda i: [i[10], 999], "not eligible")])
def test_color_path_validation(store, w, ids_fn, msg):
    with pytest.raises(cv.ConversionError, match=msg):
        cv.build_transfer("color_path", cv.eligible_palette(store, w["profile"]["id"]), ids_fn(w["ids"]))


def make_questioned(store, w):
    kid = w["ids"][30]
    kn.approve_for_production(store, kid, True)
    obs.add(store, w, (95, 0, 0), power=30)
    kn.refresh(store, w["profile"]["id"])
    assert kn.get(store, kid)["questioned"]
    return kid


def test_tonal_uses_questioned_entries_with_a_warning_and_no_confirmation(store, w):
    kid = make_questioned(store, w)
    p = cv.preview_continuous(store, w["profile"]["id"], "tonal", gradient_png(), 50, 8)
    assert any(l["knowledge_id"] == kid and l["questioned"] for l in p["layers"])
    warning = p["warnings"][0]
    assert warning["type"] == "questioned_in_tonal" and kid in warning["knowledge_ids"] and warning["observation_ids"]


def test_color_path_excludes_questioned_entries_unless_allowed_for_that_plan(store, w):
    kid = make_questioned(store, w)
    ids = [w["ids"][p] for p in (10, 30, 40)]
    with pytest.raises(cv.ConversionError, match="not eligible"):
        cv.preview_continuous(store, w["profile"]["id"], "color_path", gradient_png(), 50, 8, path_ids=ids)
    p = cv.preview_continuous(store, w["profile"]["id"], "color_path", gradient_png(), 50, 8, path_ids=ids, allowed_questioned=[kid])
    assert any(l["knowledge_id"] == kid for l in p["layers"]) and p["warnings"] == []
    plan_id = cv.create_continuous(store, w["profile"]["id"], "color_path", gradient_png(), 50, 8, "P", path_ids=ids, allowed_questioned=[kid])
    again = pl.get_plan(store, plan_id)
    assert again["allowed_questioned"] == [kid]
    with pytest.raises(cv.ConversionError, match="not eligible"):  # a second plan does not inherit the allowance
        cv.create_continuous(store, w["profile"]["id"], "color_path", gradient_png(), 50, 8, "Q", path_ids=ids)


def test_plan_generation_changes_neither_stage_nor_questioned_flag(store, w):
    kid = make_questioned(store, w)
    before = [(k["id"], k["stage"], k["questioned"], len(k["history"])) for k in kn.list_for_profile(store, w["profile"]["id"])]
    cv.create_continuous(store, w["profile"]["id"], "tonal", gradient_png(), 50, 16, "T")
    assert before == [(k["id"], k["stage"], k["questioned"], len(k["history"])) for k in kn.list_for_profile(store, w["profile"]["id"])]


def test_a_flat_image_still_yields_n_layers_most_of_them_empty(store, w):
    p = cv.preview_continuous(store, w["profile"]["id"], "tonal", flat_png(128), 40, 8)
    assert len(p["layers"]) == 8 and p["empty_bands"] == 7
    assert sum(1 for l in p["layers"] if l["regions"]) == 1
