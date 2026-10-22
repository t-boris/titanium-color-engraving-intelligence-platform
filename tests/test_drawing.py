"""Greys chosen so that the drawing of a picture survives on titanium (``drawing``, REQ-067, DEC-108), on made-up scales whose colours are
known. Min 0 % and Max 50 %: grey 255 is 0 % power, grey 0 is 50 %."""
import numpy as np
import pytest

from titanium_platform import drawing, grayscale, prediction

LO, HI = 0.0, 50.0
# light blue-grey titanium, blue, a dark tan of the skin's hue, dark: a light skin tone comes nearest the dark tan
SKIN_SCALE = prediction.Curve(powers=np.array([0, 10, 20, 30, 50], float),
                              labs=np.array([(82, -6, -12), (65, -8, -25), (45, 14, 24), (35, 3, 5), (30, 1, 1)], float),
                              points=(), referenced=True, left_out=0)
FOREHEAD, CHEEK, LIPS = (75, 12, 22), (68, 12, 22), (58, 25, 15)


def predicted_l(curve, grey8):
    greys, labs = grayscale.usable_greys(curve, LO, HI)
    table = np.full((256, 3), np.nan)
    table[greys] = labs
    return table[grey8][..., 0]


def face(px_per_mm=10.0):
    """20 x 20 mm: forehead above, cheeks below with the lips in the middle of the lower half."""
    n = round(20 * px_per_mm)
    lab = np.zeros((n, n, 3))
    lab[: n // 2] = FOREHEAD
    lab[n // 2:] = CHEEK
    lab[int(n * .7):int(n * .8), int(n * .3):int(n * .7)] = LIPS
    return lab, np.ones((n, n), bool)


def test_a_light_skin_that_comes_nearest_a_dark_tan_is_engraved_light_when_the_drawing_is_kept():
    lab, opaque = face()
    near = grayscale.grey_for_colours(lab, SKIN_SCALE, LO, HI)
    kept = drawing.choose(lab, opaque, SKIN_SCALE, LO, HI, 10.0)
    assert predicted_l(SKIN_SCALE, near["grey8"])[5, 5] < 50                  # nearest colour: the black on the forehead
    assert predicted_l(SKIN_SCALE, kept["grey8"])[5, 5] > 70                  # kept: the lightest the scale reaches
    assert kept["reach"][0] < kept["reach"][1] and kept["choices"] == 256 and kept["order"] > 0.8
    assert kept["grey8"].dtype == np.uint8 and kept["lab"].shape == lab.shape and kept["delta_e"].shape == lab.shape[:2]


def test_lips_darker_than_the_skin_stay_darker_and_the_light_and_dark_keep_their_order():
    lab, opaque = face()
    light = predicted_l(SKIN_SCALE, drawing.choose(lab, opaque, SKIN_SCALE, LO, HI, 10.0)["grey8"])
    n = lab.shape[0]
    forehead, cheek, lips = light[n // 4, n // 2], light[int(n * .9), n // 2], light[int(n * .75), n // 2]
    assert forehead >= cheek > lips


def test_a_picture_of_one_lightness_is_not_stretched():
    lab = np.full((40, 40, 3), (60.0, 0.0, 0.0))
    flat = prediction.Curve(powers=np.array([0, 50], float), labs=np.array([(80, 0, 0), (40, 0, 0)], float), points=(), referenced=True, left_out=0)
    got = predicted_l(flat, drawing.choose(lab, np.ones((40, 40), bool), flat, LO, HI, 10.0)["grey8"])
    assert np.allclose(got, 60, atol=0.5)


# cream, gold, brown, then a swing to blue at the brown's lightness and a light-blue bump, then grey falling to dark: the operator's scale
BUMP = prediction.Curve(powers=np.array([0, 10, 20, 25, 30, 40, 50], float),
                        labs=np.array([(90, 0, 6), (78, 4, 38), (60, 4, 0), (60, 0, -20), (71, -6, -20), (60, 0, 5), (40, 0, 4)], float),
                        points=(), referenced=True, left_out=0)


def test_the_path_runs_from_the_lightest_grey_to_the_darkest_never_lighter_and_skips_a_swing_of_hue():
    greys, labs = grayscale.usable_greys(BUMP, LO, HI)
    on = drawing.path(greys, labs)
    way = labs[on]
    assert way[0, 0] == labs[:, 0].max() and way[-1, 0] == labs[:, 0].min()
    assert np.all(np.diff(way[:, 0]) <= drawing.PATH_RISE_L)                  # lightness never rises
    assert np.all(np.diff(greys[on].astype(int)) < 0)                         # in the order of power
    assert way[:, 2].min() > -5                                               # the blue swing and bump are skipped
    assert np.linalg.norm(np.diff(way, axis=0), axis=1).max() < 10            # no jump of colour along it


def test_a_gradient_of_the_picture_gets_neighbouring_powers_and_its_grain_does_not_become_spots():
    n = 200
    lab = np.zeros((n, n, 3))
    lab[..., 0] = np.linspace(85, 35, n)[None, :]                             # light to dark, left to right
    lab[..., 1:] = (12, 20)                                                   # one skin hue
    grain = lab.copy()
    grain[..., 0] += np.random.default_rng(1).normal(0, 2, (n, n))             # JPEG blocks and skin grain
    for picture in (lab, grain):
        got = drawing.choose(picture, np.ones((n, n), bool), BUMP, LO, HI, 10.0)
        power = 255 - np.median(got["grey8"].astype(int), axis=0)              # each column's power, in grey steps
        assert np.all(np.diff(power) >= -1)                                   # darker picture, more power: no going back
        assert got["lab"][..., 2].min() > -5 and got["order"] > 0.95
    smooth = drawing.choose(grain, np.ones((n, n), bool), BUMP, LO, HI, 10.0)
    column = predicted_l(BUMP, smooth["grey8"])[:, 40:60]
    assert np.std(column - column.mean(axis=0)) < 1.5                          # one column of the gradient: an even tone, not spots


# -- contours ------------------------------------------------------------------------------------------------------------------------
# one light and one dark colour: two different light colours of the picture both come nearest the light one, so the edge between them
# is lost
TWO = prediction.Curve(powers=np.array([0, 25, 50], float), labs=np.array([(80, 0, 10), (80, 0, 10), (30, 0, 0)], float), points=(),
                       referenced=True, left_out=0)


def halves(px_per_mm, left=(80, 20, 10), right=(80, -20, 10), mm=20):
    """A ``mm`` square picture: two colours meeting along a vertical edge in the middle."""
    n = round(mm * px_per_mm)
    lab = np.zeros((n, n, 3))
    lab[:, : n // 2], lab[:, n // 2:] = left, right
    return lab, np.ones((n, n), bool)


def light_grey():
    return int(grayscale.grey_for_colours(np.array([[80.0, 0.0, 10.0]]), TWO, LO, HI)["grey8"][0])


@pytest.mark.parametrize("px_per_mm", [8.0, 25.0])
def test_an_edge_the_engraving_loses_is_drawn_dark_and_as_wide_as_a_line_at_any_resolution(px_per_mm):
    lab, opaque = halves(px_per_mm)
    base = np.full(opaque.shape, light_grey(), np.uint8)                     # both halves engrave the same light colour
    done = drawing.contours(base, lab, opaque, TWO, LO, HI, px_per_mm)
    lines = done["grey8"] != base
    n = lab.shape[0]
    columns = np.flatnonzero(lines[n // 2])
    assert columns.size and abs(columns.mean() - n / 2) <= px_per_mm * 0.3         # along the edge
    assert columns.size == pytest.approx(drawing.LINE_MM * px_per_mm, abs=px_per_mm * 0.15 + 1)   # 0.3 mm wide
    assert predicted_l(TWO, done["grey8"][lines]).max() <= 31                # in the darkest grey of the scale
    assert done["share"] == pytest.approx(lines.mean(), abs=1e-3) and 0.005 < done["share"] < 0.03


def test_an_edge_the_engraving_keeps_a_part_spared_or_a_speck_is_not_drawn():
    lab, opaque = halves(10.0)
    n = lab.shape[0]
    kept = np.full(opaque.shape, light_grey(), np.uint8)
    kept[:, n // 2:] = 0                                                      # the right half engraves dark: the edge shows
    assert drawing.contours(kept, lab, opaque, TWO, LO, HI, 10.0)["share"] == 0
    base = np.full(opaque.shape, light_grey(), np.uint8)
    spare = np.zeros(opaque.shape, bool)
    spare[:, n // 2 - 20:n // 2 + 20] = True                                  # a part engraved in one tone on purpose
    assert drawing.contours(base, lab, opaque, TWO, LO, HI, 10.0, spare)["share"] == 0
    speck = np.zeros((n, n, 3))
    speck[:] = (80, 20, 10)
    speck[100:104, 100:104] = (80, -20, 10)                                   # 0.4 mm: texture, not a line of the drawing
    assert drawing.contours(base, speck, opaque, TWO, LO, HI, 10.0)["share"] == 0


def test_a_lost_edge_in_an_engraving_too_dark_for_a_dark_line_is_drawn_light():
    lab, opaque = halves(10.0, left=(30, 20, 0), right=(30, -20, 0))
    base = np.zeros(opaque.shape, np.uint8)                                   # all dark
    done = drawing.contours(base, lab, opaque, TWO, LO, HI, 10.0)
    lines = done["grey8"] != base
    assert lines.any() and predicted_l(TWO, done["grey8"][lines]).min() >= 79


def test_without_a_grey_inside_the_measured_span_nothing_is_drawn():
    lab, opaque = halves(10.0)
    base = np.full(opaque.shape, 128, np.uint8)
    narrow = prediction.Curve(powers=np.array([60, 70], float), labs=np.array([(80, 0, 0), (40, 0, 0)], float), points=(), referenced=True, left_out=0)
    done = drawing.contours(base, lab, opaque, narrow, LO, HI, 10.0)
    assert done["share"] == 0 and np.array_equal(done["grey8"], base)
