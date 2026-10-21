"""Predicted look of a photo engraving from its picture and the layer's settings (REQ-030, DEC-057, DEC-062)."""
import base64
import copy

import cv2
import numpy as np
import pytest

from titanium_platform import color, ingest as ig, lightburn as lb, prediction as pr

KNOTS = (4.0, 8.0, 12.0, 16.0)
LABS = ((20.0, 5.0, -10.0), (35.0, 20.0, 15.0), (50.0, -5.0, 40.0), (62.0, 2.0, 25.0))   # not collinear: a wrong segment shows


def point(power, lab, referenced=True, kind="plate", id=1, layer=0):
    return pr.Point(power, lab, {"kind": kind, "id": id, "layer": layer, "label": f"{kind} {id}, layer {layer}"}, referenced)


def synthetic_curve(referenced=True):
    return pr.curve([point(p, lab, referenced, id=i) for i, (p, lab) in enumerate(zip(KNOTS, LABS))])


def expected_lab(power: np.ndarray) -> np.ndarray:
    """The synthetic curve written out by hand: linear in Lab between the two knots around each power."""
    out = np.empty(np.shape(power) + (3,))
    for idx, p in np.ndenumerate(np.asarray(power, float)):
        i = min(int((p - KNOTS[0]) // 4), len(KNOTS) - 2)
        t = (p - KNOTS[i]) / (KNOTS[i + 1] - KNOTS[i])
        out[idx] = (1 - t) * np.array(LABS[i]) + t * np.array(LABS[i + 1])
    return out


def gradient(rows=6, cols=241):
    return np.tile(np.linspace(0.0, 1.0, cols), (rows, 1))


def test_the_lightest_grey_gets_min_power_and_the_darkest_max_power_linearly_between():
    assert pr.grey_to_power(np.array([1.0, 0.5, 0.0]), 5.0, 16.1).tolist() == pytest.approx([5.0, 10.55, 16.1])
    with pytest.raises(pr.PredictionError, match="Min and Max power must be numbers"):
        pr.grey_to_power(0.5, None, 16)


def test_every_predicted_pixel_has_the_colour_of_the_curve_at_its_power_within_half_a_delta_e():
    """REQ-030 AC7, first half: a synthetic picture through a synthetic curve."""
    picture = gradient()
    result = pr.render(picture, 4.0, 16.0, synthetic_curve())
    power = 4.0 + 12.0 * (1.0 - picture)
    truth = expected_lab(power)
    assert result["covered"].all() and result["outside_share"] == 0.0           # Min and Max sit exactly on the measured span
    assert np.linalg.norm(result["lab"] - truth, axis=-1).max() < 0.5
    assert np.abs(result["rgb8"].astype(int) - color.lab_to_srgb8(truth)).max() <= 1   # the preview shows those colours


def test_a_power_outside_the_measured_span_is_not_predicted_and_is_hatched():
    # 40 x 40: 12 columns too light for the span (power 2.8 < 4), 4 too dark (power 18 > 16), 24 inside (power 10)
    picture = np.full((40, 40), 0.5)
    picture[:, :12], picture[:, 36:] = 0.95, 0.0
    result = pr.render(picture, 2.0, 18.0, synthetic_curve())
    outside = np.zeros((40, 40), bool)
    outside[:, :12] = outside[:, 36:] = True
    assert result["outside_share"] == pytest.approx(16 / 40, abs=1e-12)
    assert (result["covered"] == ~outside).all() and np.isnan(result["lab"][outside]).all()
    assert np.isfinite(result["lab"][~outside]).all()
    assert any("40 % of the picture needs a power outside the measured span 4..16 %" in n for n in result["notes"])
    rgb = result["rgb8"]
    light, dark = rgb[:, :12].reshape(-1, 3), rgb[:, 36:].reshape(-1, 3)
    assert set(map(tuple, light)) == {(242, 242, 242), (0, 0, 0)}               # the picture's grey crossed by dark lines
    assert set(map(tuple, dark)) == {(0, 0, 0), (255, 255, 255)}                # and by light lines on a dark grey
    lines = rgb[:, :12, 0] == 0
    assert 0.15 < lines.mean() < 0.5 and (lines[1:, :-1] == lines[:-1, 1:]).all()   # diagonal: constant along x + y
    inside = rgb[:, 12:36].reshape(-1, 3)
    assert set(map(tuple, inside)) == {tuple(color.lab_to_srgb8(expected_lab(np.array(10.0))))}   # no hatch where predicted


def test_the_share_outside_the_span_can_be_counted_on_the_whole_picture_and_given_to_a_scaled_down_render():
    picture = np.full((40, 40), 0.5)
    picture[:, :12], picture[:, 36:] = 0.95, 0.0
    levels, counts = np.unique(picture, return_counts=True)
    whole = pr.share_outside(levels, counts, 2.0, 18.0, synthetic_curve())
    assert whole == pytest.approx(pr.render(picture, 2.0, 18.0, synthetic_curve())["outside_share"], abs=1e-12)
    preview = pr.render(np.full((4, 4), 0.5), 2.0, 18.0, synthetic_curve(), outside_share=whole)    # nothing outside in the preview
    assert preview["outside_share"] == whole and preview["covered"].all()
    assert any(n.startswith("40 % of the picture needs a power outside") for n in preview["notes"])


def test_the_curve_never_extrapolates_beyond_its_measured_powers():
    c = synthetic_curve()
    assert c.span == (4.0, 16.0)
    lab = c.lab_at([3.99, 4.0, 10.0, 16.0, 16.01])
    assert np.isnan(lab[[0, 4]]).all() and np.isfinite(lab[1:4]).all()
    assert lab[1].tolist() == list(LABS[0]) and lab[3].tolist() == list(LABS[-1])
    assert c.lab_at(6.0).shape == (3,) and c.lab_at(6.0) == pytest.approx(expected_lab(np.array(6.0)))


def test_points_at_the_same_power_are_averaged_and_keep_every_source():
    c = pr.curve([point(8.0, (30.0, 10.0, 0.0), kind="pair", id=22, layer=3), point(8.0, (40.0, 20.0, 10.0), id=5),
                  point(12.0, (50.0, 0.0, 30.0), id=6)])
    assert c.powers.tolist() == [8.0, 12.0]
    assert c.points[0]["lab"] == [35.0, 15.0, 5.0]
    assert [s["kind"] for s in c.points[0]["sources"]] == ["pair", "plate"] and c.points[0]["sources"][0]["layer"] == 3
    assert c.as_dict()["points"][1]["sources"] == [{"kind": "plate", "id": 6, "layer": 0, "label": "plate 6, layer 0"}]


def test_referenced_points_win_over_camera_relative_ones_and_the_two_are_never_mixed():
    points = [point(4.0, LABS[0], True), point(12.0, LABS[2], True),
              point(6.0, (10.0, 0.0, 0.0), False), point(8.0, (11.0, 0.0, 0.0), False), point(16.0, (12.0, 0.0, 0.0), False)]
    c = pr.curve(points)
    assert c.referenced and c.powers.tolist() == [4.0, 12.0] and c.left_out == 3
    assert c.span == (4.0, 12.0)                                    # a camera-relative point does not stretch the referenced span
    assert all(row["referenced"] for row in c.points)
    relative = pr.curve(points, prefer_referenced=False)
    assert not relative.referenced and relative.powers.tolist() == [6.0, 8.0, 16.0] and relative.left_out == 2
    only_relative = pr.curve(points[2:])
    assert not only_relative.referenced and only_relative.left_out == 0


def test_a_prediction_built_on_camera_relative_colours_says_so_on_the_preview():
    camera = pr.render(gradient(), 4.0, 16.0, synthetic_curve(referenced=False))
    assert camera["referenced"] is False
    assert any("as that camera saw them under that light" in n for n in camera["notes"])
    charted = pr.render(gradient(), 4.0, 16.0, synthetic_curve(referenced=True))
    assert charted["referenced"] is True and not any("camera saw" in n for n in charted["notes"])
    assert any("chart-corrected (referenced)" in n for n in charted["notes"])


def test_every_curve_point_must_say_where_it_was_measured_and_hold_a_real_colour():
    with pytest.raises(ValueError, match="where it was measured"):
        pr.Point(5.0, (50.0, 0.0, 0.0), {"id": 1}, True)
    with pytest.raises(ValueError, match="finite power and Lab"):
        pr.Point(5.0, (np.nan, 0.0, 0.0), {"kind": "pair"}, False)
    with pytest.raises(pr.PredictionError, match="nothing to predict from"):
        pr.curve([])


def test_the_default_picture_adjustments_leave_the_grey_exactly_as_it_is():
    grey = np.random.default_rng(0).random((30, 30))
    assert np.array_equal(pr.adjust_grey(grey), grey)
    assert np.array_equal(pr.adjust_grey(grey, gamma=1.0, contrast=0.0, brightness=0.0), grey)
    defaults = pr.adjustments_of({"Gamma": "1", "Contrast": "0", "Brightness": "0", "EnhanceAmount": "0"})
    assert defaults["assumed"] == [] and defaults["not_modelled"] == []
    assert np.array_equal(pr.render(grey, 4, 16, synthetic_curve())["lab"], pr.render(grey, 4, 16, synthetic_curve(), defaults["values"])["lab"])


def test_gamma_contrast_and_brightness_keep_the_order_of_grey_levels_and_move_them_as_lightburn_documents():
    g = np.linspace(0.0, 1.0, 256)
    for kwargs in ({"gamma": 2.2}, {"gamma": 0.45}, {"contrast": 40}, {"contrast": -60}, {"brightness": 15}, {"brightness": -15},
                   {"gamma": 1.4, "contrast": 25, "brightness": -10}):
        assert (np.diff(pr.adjust_grey(g, **kwargs)) >= 0).all(), kwargs          # no grey level overtakes another
    adjust = lambda v, **kw: float(pr.adjust_grey(np.array(v), **kw))
    assert adjust(0.5, gamma=2.2) < 0.5 < adjust(0.5, gamma=0.45)                # lower gamma lightens the mid-tones
    assert adjust(0.0, gamma=2.2) == 0.0 and adjust(1.0, gamma=2.2) == 1.0
    assert adjust(0.7, contrast=40) > 0.7 and adjust(0.3, contrast=40) < 0.3 and adjust(0.5, contrast=40) == 0.5
    assert adjust(0.5, brightness=10) == pytest.approx(0.6) and adjust(0.95, brightness=10) == 1.0
    with pytest.raises(pr.PredictionError, match="out of range"):
        pr.adjust_grey(g, gamma=0)


def test_picture_adjustments_are_applied_before_the_grey_becomes_power_and_marked_assumed():
    picture = gradient(cols=101) * 0.8
    brighter = pr.render(picture, 4.0, 16.0, synthetic_curve(), {"Brightness": "10"})
    assert np.allclose(brighter["lab"], pr.render(picture + 0.1, 4.0, 16.0, synthetic_curve())["lab"], equal_nan=True)
    assert brighter["adjustments"]["assumed"] == ["Brightness"]
    assert any("standard formulas, assumed" in n and "Brightness 10" in n for n in brighter["notes"])


def test_enhance_and_denoise_are_not_modelled_and_are_named():
    assert pr.ASSUMED == ("Gamma", "Contrast", "Brightness")
    assert pr.NOT_MODELLED == ("EnhanceAmount", "EnhanceRadius", "EnhanceDenoise")
    settings = {"Gamma": "1.2", "Contrast": "0", "Brightness": "0", "EnhanceAmount": "200", "EnhanceRadius": "4", "EnhanceDenoise": "0"}
    result = pr.render(gradient(), 4.0, 16.0, synthetic_curve(), settings)
    assert result["adjustments"]["assumed"] == ["Gamma"]
    assert result["adjustments"]["not_modelled"] == ["EnhanceAmount", "EnhanceRadius"]
    assert any("not modelled" in n and "EnhanceAmount 200" in n and "EnhanceRadius 4" in n for n in result["notes"])
    assert any("assumed" in n and "Gamma 1.2" in n for n in result["notes"])


TAIL = "only grayscale mode, where the grey level sets the power, and the dot modes whose grey level sets the density of dots are predicted"


@pytest.mark.parametrize("mode,why", [("threshold", "a cut at mid grey"), ("3dslice", "engraves depth"), ("sketch", "the edges of the picture"),
                                      ("flux", "does not set the power or the density of dots"), ("", None), (None, None)])
def test_modes_without_tones_to_measure_are_refused_with_a_reason(mode, why):
    with pytest.raises(pr.PredictionError, match=TAIL) as raised:
        pr.refuse_mode(mode)
    assert why is None or why in str(raised.value)


@pytest.mark.parametrize("mode", ["grayscale", " Grayscale ", "stucki", "Stucki", "jarvis", "dither", "dithered", "ordered", "atkinson", "newsprint", "halftone"])
def test_grayscale_and_the_dot_modes_whose_grey_sets_the_density_are_predicted(mode):
    """REQ-054: the dot modes are predicted from what was photographed in the same mode (REQ-030 refused them all)."""
    assert issubclass(pr.PredictionError, ValueError)
    pr.refuse_mode(mode)


@pytest.mark.parametrize("picture", [None, np.zeros((0, 0)), np.zeros((4, 4, 3)), np.full((4, 4), 1.5)])
def test_a_layer_without_a_usable_picture_is_refused_with_a_reason(picture):
    with pytest.raises(pr.PredictionError, match="picture"):
        pr.render(picture, 4.0, 16.0, synthetic_curve())


def test_changing_min_or_max_power_re_renders_from_the_same_curve():
    picture, c = gradient(), synthetic_curve()
    kept_points, kept_picture = copy.deepcopy(c.points), picture.copy()
    first = pr.render(picture, 4.0, 16.0, c)
    narrower = pr.render(picture, 6.0, 12.0, c)
    assert np.linalg.norm(narrower["lab"] - expected_lab(6.0 + 6.0 * (1.0 - picture)), axis=-1).max() < 0.5
    assert narrower["power_range"] == [6.0, 12.0] and not np.allclose(first["lab"], narrower["lab"])
    wider = pr.render(picture, 0.0, 20.0, c)
    assert wider["outside_share"] == pytest.approx(np.mean((picture > 0.8) | (picture < 0.2)), abs=1e-12)
    again = pr.render(picture, 4.0, 16.0, c)
    assert np.array_equal(again["rgb8"], first["rgb8"]) and np.array_equal(again["lab"], first["lab"])
    assert c.points == kept_points and np.array_equal(picture, kept_picture)       # nothing is changed by rendering


def test_a_grayscale_layer_read_from_its_file_is_predicted_from_its_own_picture_and_settings():
    """The settings and the picture come out of the parser under the names it gives them."""
    png = cv2.imencode(".png", (gradient(rows=20, cols=64) * 255).astype(np.uint8))[1].tobytes()
    xml = (f'<LightBurnProject AppVersion="1.7.01"><CutSetting_Img type="Image"><index Value="0"/><name Value="C00"/>'
           f'<minPower Value="4"/><maxPower Value="16"/><speed Value="128"/><frequency Value="60000"/>'
           f'<ditherMode Value="grayscale"/><dpi Value="254"/></CutSetting_Img>'
           f'<Shape Type="Bitmap" CutIndex="0" W="40" H="30" Gamma="1" Contrast="0" Brightness="0" EnhanceAmount="0" '
           f'EnhanceRadius="0" EnhanceDenoise="1" File="/x/p.png" SourceHash="0" Data="{base64.b64encode(png).decode()}">'
           f'<XForm>1 0 0 1 30 20</XForm></Shape></LightBurnProject>').encode()
    layer = lb.parse_bytes(xml).layer(0)
    pr.refuse_mode(layer.image_summary()["dither"])
    picture = ig._picture_gray(layer.regions[0].bitmap["png"])
    low, high = (float(layer.source_settings[k]["Value"]) for k in ("minPower", "maxPower"))
    result = pr.render(picture, low, high, synthetic_curve(), layer.source_settings["bitmaps"][0])
    assert result["covered"].all()
    assert np.linalg.norm(result["lab"] - expected_lab(4.0 + 12.0 * (1.0 - picture)), axis=-1).max() < 0.5
    assert result["adjustments"]["not_modelled"] == ["EnhanceDenoise"]


def test_the_picture_and_its_prediction_are_shown_side_by_side_and_encode_as_png():
    picture = gradient(rows=10, cols=30)
    result = pr.render(picture, 2.0, 18.0, synthetic_curve())
    both = pr.side_by_side(picture, result["rgb8"])
    assert both.shape == (10, 30 + pr.GAP + 30, 3) and both.dtype == np.uint8
    assert np.array_equal(both[:, :30, 0], np.round(picture * 255).astype(np.uint8)) and (both[:, :30, 0] == both[:, :30, 2]).all()
    assert np.array_equal(both[:, 30 + pr.GAP:], result["rgb8"])
    decoded = cv2.cvtColor(cv2.imdecode(np.frombuffer(pr.to_png(both), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    assert np.array_equal(decoded, both)                                         # the colours survive in the right channel order
