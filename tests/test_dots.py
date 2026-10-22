"""Which dots each dot kind of a LightBurn image layer fires: the tone a flat grey gives, white and transparent pixels, the error
diffusion kernels against the plain loop, the halftone grid, sketch's edges and the coverage a preview shows."""
import math

import cv2
import numpy as np
import pytest

from titanium_platform import dots, photo_modes as pm

DPI = 1000
DIFFUSION = tuple(dots.KERNELS)
KEEP_TONE = ("ordered", "dither", "stucki", "jarvis", "newsprint", "halftone")


def flat(grey, shape=(200, 200)):
    return np.full(shape, float(grey))


def raster_loop(grey, kind, alpha=None):
    """Error diffusion as textbooks write it: dot by dot in raster order, each dot pushing its error to the dots after it."""
    divisor, taps = dots.KERNELS[kind]
    g = np.clip(np.asarray(grey, float), 0.0, 1.0)
    empty = g >= 1.0 - pm.WHITE
    if alpha is not None:
        empty |= np.asarray(alpha, float) < pm.ALPHA_MIN
    value = np.where(empty, 0.0, 1.0 - g)
    h, w = g.shape
    fired = np.zeros((h, w), bool)
    for y in range(h):
        for x in range(w):
            hit = bool(value[y, x] >= 0.5) and not empty[y, x]
            error = 0.0 if empty[y, x] else value[y, x] - hit
            fired[y, x] = hit
            for dx, dy, n in taps:
                if 0 <= x + dx < w and y + dy < h:
                    value[y + dy, x + dx] += error * n / divisor
    return fired


def spot_centres(fired):
    count, _, _, centres = cv2.connectedComponentsWithStats(fired.astype(np.uint8), connectivity=8)
    return count - 1, centres[1:]


# -- the kinds ------------------------------------------------------------------------------------------------------------------------
def test_the_kinds_are_the_dot_and_edge_kinds_of_the_catalogue_and_nothing_else():
    assert set(dots.KINDS) == {key for key, m in pm.MODES.items() if m.family in (pm.DOTS, pm.EDGES)}
    grey = np.random.default_rng(3).random((20, 30))
    assert np.array_equal(dots.struck(grey, "FloydSteinberg", dpi=DPI), dots.struck(grey, "dither", dpi=DPI))   # the catalogue's aliases
    for name in ("grayscale", "3dslice", "spiral", None):
        with pytest.raises(ValueError):
            dots.struck(grey, name, dpi=DPI)


# -- tone -----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", KEEP_TONE)
@pytest.mark.parametrize("grey", (0.1, 0.25, 0.5, 0.75, 0.9))
def test_a_flat_grey_strikes_as_many_dots_as_it_is_dark(kind, grey):
    fired = dots.struck(flat(grey), kind, dpi=DPI)
    assert fired.dtype == bool and fired.shape == (200, 200)
    assert fired.mean() == pytest.approx(1.0 - grey, abs=0.01)


def test_threshold_strikes_all_or_nothing_at_mid_grey():
    gradient = np.tile(np.linspace(0, 1, 101), (5, 1))
    assert np.array_equal(dots.struck(gradient, "threshold", dpi=DPI), gradient < pm.THRESHOLD_CUT)
    assert dots.struck(flat(0.49, (8, 8)), "threshold", dpi=DPI).all()
    assert not dots.struck(flat(0.51, (8, 8)), "threshold", dpi=DPI).any()


def test_ordered_repeats_one_8_by_8_tile():
    fired = dots.struck(flat(0.3, (32, 48)), "ordered", dpi=DPI)
    assert np.array_equal(fired, np.tile(fired[:8, :8], (4, 6)))
    assert fired[:8, :8].sum() == 45                                       # 0.7 of 64 dots, rounded


def test_atkinson_loses_the_lightest_and_the_darkest_tones():
    # Atkinson passes on 6/8 of the error, so a grey of darkness d never builds above 4 d: below 1/8 no dot fires, above 7/8 all do.
    assert not dots.struck(flat(0.9), "atkinson", dpi=DPI).any() and not dots.struck(flat(0.95), "atkinson", dpi=DPI).any()
    assert dots.struck(flat(0.1), "atkinson", dpi=DPI).all() and dots.struck(flat(0.05), "atkinson", dpi=DPI).all()
    assert dots.struck(flat(0.95), "dither", dpi=DPI).mean() == pytest.approx(0.05, abs=0.01)   # Floyd-Steinberg keeps them
    assert dots.struck(flat(0.5), "atkinson", dpi=DPI).mean() == pytest.approx(0.5, abs=0.01)    # and mid grey is kept
    assert dots.struck(flat(0.25), "atkinson", dpi=DPI).mean() > 0.8                            # a dark grey comes out darker


def test_the_error_diffusion_kinds_are_four_different_algorithms():
    gradient = np.tile(np.linspace(0, 1, 256), (64, 1))
    fired = {kind: dots.struck(gradient, kind, dpi=DPI) for kind in DIFFUSION}
    for i, a in enumerate(DIFFUSION):
        for b in DIFFUSION[i + 1:]:
            assert (fired[a] != fired[b]).mean() > 0.05, (a, b)


# -- white and transparent pixels -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", dots.KINDS)
def test_white_is_never_struck(kind):
    grey = np.random.default_rng(5).random((90, 120)) * 0.6
    grey[20:30, :] = 1.0
    grey[:, 50:60] = 1.0 - 0.4 / 255                                   # within one 8-bit level of white is white
    grey[60:80, 80:100] = 0.0                                           # black next to ...
    grey[60:80, 100:115] = 1.0                                          # ... white: a hard edge
    white = grey >= 1.0 - pm.WHITE
    fired = dots.struck(grey, kind, dpi=DPI)
    assert fired.any() and not fired[white].any()


@pytest.mark.parametrize("kind", dots.KINDS)
def test_transparent_pixels_are_never_struck(kind):
    rng = np.random.default_rng(6)
    grey = rng.random((90, 120)) * 0.4
    grey[40:70, 30:90] = 0.0
    alpha = np.ones_like(grey)
    alpha[40:70, 50:70] = 0.0                                           # a hole in a black area
    alpha[:, :20] = pm.ALPHA_MIN - 0.01
    alpha[:, 100:] = rng.random((90, 20))
    fired = dots.struck(grey, kind, dpi=DPI, alpha=alpha)
    assert fired.any() and not fired[alpha < pm.ALPHA_MIN].any()


# -- the wavefronts are the plain loop ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", DIFFUSION)
def test_the_wavefronts_fire_the_same_dots_as_the_plain_loop(kind):
    rng = np.random.default_rng(11)
    grey = rng.random((40, 50))
    grey[5:8, :] = 1.0
    alpha = np.ones_like(grey)
    alpha[20:26, 10:30] = 0.0
    assert np.array_equal(dots.struck(grey, kind, dpi=DPI, alpha=alpha), raster_loop(grey, kind, alpha))
    for shape in ((1, 7), (7, 1), (5, 2), (3, 3)):                     # narrower than a wavefront's skew
        small = rng.random(shape)
        assert np.array_equal(dots.struck(small, kind, dpi=DPI), raster_loop(small, kind)), shape


# -- halftone and newsprint -----------------------------------------------------------------------------------------------------------
def test_halftone_lays_one_spot_per_cell_and_the_cells_follow_cells_per_inch():
    count, _ = spot_centres(dots.struck(flat(0.85, (400, 400)), "halftone", dpi=DPI, cells_per_inch=100, angle_deg=0))
    assert count == 40 * 40                                             # 10 dots per cell at 1000 dpi
    count, _ = spot_centres(dots.struck(flat(0.85, (400, 400)), "halftone", dpi=DPI))
    assert count == pytest.approx(20 * 20, rel=0.1)                     # LightBurn's 50 cells per inch, turned 22.5 degrees


def test_the_halftone_grid_turns_counter_clockwise_as_the_picture_is_seen():
    _, centres = spot_centres(dots.struck(flat(0.9, (300, 300)), "halftone", dpi=DPI, cells_per_inch=50, angle_deg=30))
    middle = centres[np.argmin(np.hypot(*(centres - 150).T))]
    offsets = centres - middle
    right = offsets[(offsets[:, 0] > 5) & (np.abs(offsets[:, 1]) < offsets[:, 0])]   # the neighbour to the right
    dx, dy = right[np.argmin(np.hypot(*right.T))]
    assert math.degrees(math.atan2(-dy, dx)) == pytest.approx(30, abs=3)              # rows run down: up is -y
    assert math.hypot(dx, dy) == pytest.approx(20, abs=1)


def test_newsprint_is_a_fixed_grid_that_ignores_the_halftone_settings():
    fired = dots.struck(flat(0.85, (300, 300)), "newsprint", dpi=DPI)
    count, _ = spot_centres(fired)
    assert count == pytest.approx(300 * 300 / dots.NEWSPRINT_PITCH ** 2, rel=0.05)
    assert np.array_equal(fired, dots.struck(flat(0.85, (300, 300)), "newsprint", dpi=254, cells_per_inch=10, angle_deg=0))


# -- sketch ---------------------------------------------------------------------------------------------------------------------------
def test_sketch_strikes_the_dark_side_of_hard_edges_and_leaves_flat_and_soft_areas_blank():
    grey = np.ones((100, 200))
    grey[30:70, 30:70] = 0.0                                            # a black square on white
    grey[20:80, 110:190] = np.linspace(0.2, 0.8, 80)                    # a soft gradient ...
    grey[20:80, 110:120] = 0.5                                          # ... beside a flat grey
    fired = dots.struck(grey, "sketch", dpi=DPI)
    assert fired[30, 35:65].all() and fired[69, 35:65].all() and fired[35:65, 30].all() and fired[35:65, 69].all()
    assert not fired[36:64, 36:64].any()                                # the inside of the square is flat
    assert not fired[grey >= 1.0].any()
    assert fired[25:75, 113:187].mean() < 0.01


# -- coverage -------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", DIFFUSION + ("halftone",))
def test_coverage_is_the_share_of_each_preview_pixel_the_dots_strike(kind):
    rng = np.random.default_rng(8)
    grey = cv2.GaussianBlur(rng.random((60, 80)), (0, 0), 6)
    grey = (grey - grey.min()) / (grey.max() - grey.min()) * 0.8 + 0.1
    cover = dots.coverage(grey, kind, dots_per_px=3, dpi=DPI)
    assert cover.shape == grey.shape and cover.min() >= 0.0 and cover.max() <= 1.0
    if kind != "atkinson":
        assert cover.mean() == pytest.approx(1.0 - grey.mean(), abs=0.01)
    assert np.isin(cover * 9, np.arange(10)).all()                      # whole dots of 3 x 3


def test_coverage_is_the_mean_of_the_struck_dots_of_each_pixel_and_empty_where_transparent():
    grey = np.random.default_rng(9).random((30, 40))
    alpha = np.ones_like(grey)
    alpha[10:20, 10:20] = 0.0
    cover = dots.coverage(grey, "jarvis", dots_per_px=2, dpi=DPI, alpha=alpha)
    fired = dots.struck(np.kron(grey, np.ones((2, 2))), "jarvis", dpi=DPI, alpha=np.kron(alpha, np.ones((2, 2))))
    assert np.array_equal(cover, fired.reshape(30, 2, 40, 2).mean(axis=(1, 3)))
    assert not cover[10:20, 10:20].any()
    with pytest.raises(ValueError):
        dots.coverage(grey, "jarvis", dots_per_px=0, dpi=DPI)
