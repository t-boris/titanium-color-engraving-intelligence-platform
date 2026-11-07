"""A card picture engraved as a raster photo: the box a turned picture needs, its pixels at the layer's DPI (transparent where the turned
picture does not reach, inverted on request), the bounds of its size and resolution, the dithered look the screen shows and the layer
LightBurn's writer makes of it."""
import math

import cv2
import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import box

from titanium_platform import card_raster as cr, dots, lightburn, plans, setup as su

DPI = 254.0                                  # 10 pixels to the millimetre
MM_PER_INCH = 25.4


def encode(image, ext=".png") -> bytes:
    ok, buffer = cv2.imencode(ext, image)
    assert ok
    return buffer.tobytes()


def halves(rows=20, columns=40) -> bytes:
    """Black on the left, white on the right."""
    img = np.full((rows, columns, 3), 255, np.uint8)
    img[:, : columns // 2] = 0
    return encode(img)


def corner_mark(rows=20, columns=40) -> bytes:
    """White with a black block in the top-left corner."""
    img = np.full((rows, columns, 3), 255, np.uint8)
    img[: rows // 2, : columns // 4] = 0
    return encode(img)


def gradient(rows=60, columns=90) -> bytes:
    ramp = np.linspace(0, 255, columns).astype(np.uint8)
    img = np.repeat(ramp[None, :, None], rows, axis=0).repeat(3, axis=2)
    cv2.circle(img, (columns // 2, rows // 2), rows // 3, (0, 0, 0), -1)
    return encode(img)


def grey_of(pixels) -> np.ndarray:
    return pixels[..., 0]


def sentence(error) -> str:
    text = str(error.value)
    assert text.endswith(".") and text[0].isupper()
    return text


# -- bounds ---------------------------------------------------------------------------------------------------------------------------
def test_bounds_of_an_unturned_picture_is_its_own_size():
    assert cr.bounds(50, 30, 0) == (50.0, 30.0)
    assert cr.bounds(50, 30, 360) == (50.0, 30.0)
    assert cr.bounds(50, 30, 180) == (50.0, 30.0)


def test_bounds_of_a_quarter_turn_swaps_the_sides_exactly():
    assert cr.bounds(50, 30, 90) == (30.0, 50.0)
    assert cr.bounds(50, 30, -90) == (30.0, 50.0)
    assert cr.bounds(50, 30, 270) == (30.0, 50.0)


def test_bounds_of_a_45_degree_turn_is_the_sum_of_the_sides_over_root_two():
    side = (50 + 30) / math.sqrt(2)
    assert cr.bounds(50, 30, 45) == pytest.approx((side, side), abs=1e-6)
    assert cr.bounds(50, 30, -45) == pytest.approx((side, side), abs=1e-6)


@pytest.mark.parametrize("angle", (0, 17.5, 30, 45, 60, 90, 135, 180, -30, 200, 359.99))
def test_bounds_is_the_box_the_card_geometry_of_a_turned_rectangle_occupies(angle):
    """card_work turns the rectangle with shapely about its centre; the bounds are the extent of the result."""
    turned = affinity.rotate(box(-25, -15, 25, 15), angle, origin=(0, 0))
    x0, y0, x1, y1 = turned.bounds
    assert cr.bounds(50, 30, angle) == pytest.approx((x1 - x0, y1 - y0), abs=1e-6)


@pytest.mark.parametrize("width, height, rotation", ((0, 10, 0), (10, -1, 0), (math.nan, 10, 0), (10, math.inf, 0), ("wide", 10, 0),
                                                       (10, 10, math.nan), (10, 10, None)))
def test_bounds_refuses_nonsense_with_a_sentence(width, height, rotation):
    with pytest.raises(su.ValidationError) as error:
        cr.bounds(width, height, rotation)
    sentence(error)


# -- prepare: size --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("width, height, dpi", ((10, 5, DPI), (30.5, 12.7, 300), (85, 55, 600), (7.3, 7.3, 1503), (40, 20, 10), (2, 1, 2400)))
def test_the_pixels_are_the_size_in_millimetres_at_the_dpi(width, height, dpi):
    pixels = cr.prepare(halves(), width, height, 0, dpi, {})
    assert pixels.dtype == np.uint8 and pixels.ndim == 3 and pixels.shape[2] == 4
    assert abs(pixels.shape[1] - width * dpi / MM_PER_INCH) <= 1 and abs(pixels.shape[0] - height * dpi / MM_PER_INCH) <= 1


@pytest.mark.parametrize("rotation", (30, 45, -60, 90, 135, 180, 270))
def test_a_turned_picture_is_placed_in_the_bounding_box_at_the_dpi(rotation):
    pixels = cr.prepare(halves(), 20, 10, rotation, DPI, {})
    box_w, box_h = cr.bounds(20, 10, rotation)
    assert abs(pixels.shape[1] - box_w * DPI / MM_PER_INCH) <= 1 and abs(pixels.shape[0] - box_h * DPI / MM_PER_INCH) <= 1


def test_the_size_is_the_one_the_screen_announces():
    """card_work tells the screen round(bounds x dpi / 25.4) pixels: that is the size made."""
    for rotation in (0, 33.3, 90, -135):
        box_w, box_h = cr.bounds(41.37, 22.91, rotation)
        scale = 600.0 / MM_PER_INCH
        assert cr.prepare(halves(), 41.37, 22.91, rotation, 600.0, {}).shape[:2] == (round(box_h * scale), round(box_w * scale))


# -- prepare: transparency ------------------------------------------------------------------------------------------------------------
def test_an_unturned_picture_is_opaque_everywhere():
    pixels = cr.prepare(halves(), 20, 10, 0, DPI, {})
    assert (pixels[..., 3] == 255).all()


def test_a_picture_turned_45_degrees_leaves_its_corners_transparent_and_its_middle_opaque():
    pixels = cr.prepare(halves(), 20, 10, 45, DPI, {})
    rows, columns = pixels.shape[:2]
    for y, x in ((0, 0), (0, columns - 1), (rows - 1, 0), (rows - 1, columns - 1)):
        assert pixels[y, x, 3] == 0 and tuple(pixels[y, x, :3]) == (255, 255, 255)
    assert pixels[rows // 2, columns // 2, 3] == 255
    covered = (pixels[..., 3] > 127).mean()
    assert covered == pytest.approx(20 * 10 / (cr.bounds(20, 10, 45)[0] * cr.bounds(20, 10, 45)[1]), abs=0.01)   # the picture's share of its box


def test_a_quarter_turn_covers_its_whole_box():
    for rotation in (90, 180, 270, -90):
        assert (cr.prepare(halves(), 20, 10, rotation, DPI, {})[..., 3] == 255).all()


def test_a_turn_is_clockwise_on_the_screen():
    """A black block in the top-left of the picture is in the top-right after a quarter turn clockwise, bottom-left after a quarter turn
    back; the top corner of a wide picture turned 30 degrees clockwise is its left one."""
    mark = corner_mark()
    clockwise = cr.prepare(mark, 20, 10, 90, DPI, {})
    rows, columns = clockwise.shape[:2]
    assert (rows, columns) == (200, 100)
    assert grey_of(clockwise)[5, columns - 5] == 0 and grey_of(clockwise)[5, 5] == 255 and grey_of(clockwise)[rows - 5, columns - 5] == 255
    back = cr.prepare(mark, 20, 10, -90, DPI, {})
    assert grey_of(back)[back.shape[0] - 5, 5] == 0 and grey_of(back)[5, 5] == 255
    half = cr.prepare(mark, 20, 10, 180, DPI, {})
    assert grey_of(half)[half.shape[0] - 5, half.shape[1] - 5] == 0 and grey_of(half)[5, 5] == 255
    tilted = cr.prepare(halves(), 20, 10, 30, DPI, {})
    top = int(np.argmax((tilted[..., 3] > 127).any(axis=1)))
    assert (np.nonzero(tilted[top, :, 3] > 127)[0].mean()) < tilted.shape[1] / 2
    anti = cr.prepare(halves(), 20, 10, -30, DPI, {})
    top = int(np.argmax((anti[..., 3] > 127).any(axis=1)))
    assert (np.nonzero(anti[top, :, 3] > 127)[0].mean()) > anti.shape[1] / 2


def test_the_dark_half_of_a_turned_picture_stays_on_its_side():
    """Black on the left of the picture: after 20 degrees clockwise the middle of that half is up and left of the centre of the box, the
    middle of the white half down and right of it."""
    pixels = cr.prepare(halves(), 20, 10, 20, DPI, {})
    rows, columns = pixels.shape[:2]
    cy, cx = (rows - 1) / 2.0, (columns - 1) / 2.0
    turn = math.radians(20)
    for side, grey in ((-50, 0), (50, 255)):                       # +-5 mm along the picture's own x axis, 10 pixels a millimetre
        y, x = round(cy + side * math.sin(turn)), round(cx + side * math.cos(turn))
        assert pixels[y, x, 3] == 255 and grey_of(pixels)[y, x] == grey


# -- prepare: the picture -------------------------------------------------------------------------------------------------------------
def test_the_picture_fills_its_rectangle_dark_on_the_left():
    pixels = cr.prepare(halves(), 10, 5, 0, DPI, {})
    assert pixels.shape == (50, 100, 4)
    assert (pixels[..., 0] == pixels[..., 1]).all() and (pixels[..., 1] == pixels[..., 2]).all()
    assert grey_of(pixels)[25, 5] == 0 and grey_of(pixels)[25, 95] == 255


def test_invert_flips_a_black_and_white_picture():
    plain = cr.prepare(halves(), 10, 5, 0, DPI, {"invert": False})
    flipped = cr.prepare(halves(), 10, 5, 0, DPI, {"invert": True})
    assert grey_of(flipped)[25, 5] == 255 and grey_of(flipped)[25, 95] == 0
    assert np.array_equal(grey_of(flipped).astype(int), 255 - grey_of(plain).astype(int))
    assert np.array_equal(flipped[..., 3], plain[..., 3])


def test_invert_leaves_the_transparent_corners_transparent():
    flipped = cr.prepare(halves(), 20, 10, 45, DPI, {"invert": True})
    assert flipped[0, 0, 3] == 0 and tuple(flipped[0, 0, :3]) == (255, 255, 255)


def test_the_threshold_is_ignored():
    base = cr.prepare(gradient(), 20, 12, 15, DPI, {})
    assert np.array_equal(base, cr.prepare(gradient(), 20, 12, 15, DPI, {"threshold": 10, "auto_threshold": False}))
    assert np.array_equal(base, cr.prepare(gradient(), 20, 12, 15, DPI, None))


def test_a_transparent_file_is_composited_on_white_like_the_traced_form():
    rgba = np.zeros((20, 40, 4), np.uint8)
    rgba[:, :20] = (0, 0, 0, 255)                                    # opaque black on the left, fully transparent on the right
    pixels = cr.prepare(encode(rgba), 10, 5, 0, DPI, {})
    assert grey_of(pixels)[25, 5] == 0 and grey_of(pixels)[25, 95] == 255 and (pixels[..., 3] == 255).all()


def test_the_pencil_treatment_redraws_the_picture_at_the_same_size():
    plain = cr.prepare(gradient(), 40, 25, 0, DPI, {})
    pencil = cr.prepare(gradient(), 40, 25, 0, DPI, {"treatment": "pencil", "detail": 80, "strength": 80, "min_feature_mm": 0.3})
    assert pencil.shape == plain.shape and not np.array_equal(pencil, plain)
    assert (grey_of(pencil) > 200).mean() > 0.2 and (grey_of(pencil) < 128).mean() > 0.1            # white paper and dark strokes
    assert np.array_equal(pencil, cr.prepare(gradient(), 40, 25, 0, DPI, {"treatment": "pencil", "detail": 80, "strength": 80, "min_feature_mm": 0.3}))
    heavier = cr.prepare(gradient(), 40, 25, 0, DPI, {"treatment": "pencil", "detail": 80, "strength": 100, "min_feature_mm": 0.3})
    assert (grey_of(heavier) < 128).mean() > (grey_of(cr.prepare(gradient(), 40, 25, 0, DPI, {"treatment": "pencil", "detail": 80, "strength": 0,
                                                                                               "min_feature_mm": 0.3})) < 128).mean()


def test_the_pencil_treatment_can_be_turned_and_inverted():
    pixels = cr.prepare(gradient(), 40, 25, 45, DPI, {"treatment": "pencil", "invert": True})
    assert pixels[0, 0, 3] == 0 and pixels[pixels.shape[0] // 2, pixels.shape[1] // 2, 3] == 255


def test_settings_that_are_out_of_range_or_unknown_are_refused_with_a_sentence():
    for bad in ({"treatment": "oil"}, {"invert": "yes"}, {"detail": 101}, {"colour": 1}, [1]):
        with pytest.raises(su.ValidationError) as error:
            cr.prepare(halves(), 10, 5, 0, DPI, bad)
        sentence(error)


def test_a_file_that_is_not_a_picture_is_refused_with_a_sentence():
    for bad in (b"", b"this is not a picture"):
        with pytest.raises(su.ValidationError) as error:
            cr.prepare(bad, 10, 5, 0, DPI, {})
        sentence(error)


# -- prepare: limits ------------------------------------------------------------------------------------------------------------------
def test_a_side_beyond_6000_pixels_is_refused_before_the_file_is_read():
    with pytest.raises(su.ValidationError) as error:                 # 7000 x 100 pixels: garbage bytes show the size is checked first
        cr.prepare(b"not a picture", 700, 10, 0, DPI, {})
    assert "6000" in sentence(error) and "7000" in str(error.value)


def test_more_than_20_million_pixels_are_refused():
    with pytest.raises(su.ValidationError) as error:                 # 5080 x 5080 = 25.8 million
        cr.prepare(halves(), 508, 508, 0, DPI, {})
    assert "20 million" in sentence(error)


def test_the_turn_counts_towards_the_limits():
    assert cr.prepare(halves(), 500, 20, 0, DPI, {}).shape[:2] == (200, 5000)        # fine as it lies
    assert cr.prepare(halves(), 500, 20, 90, DPI, {}).shape[:2] == (5000, 200)       # and on its side
    with pytest.raises(su.ValidationError) as error:                                 # 7000 x 200 pixels: too long
        cr.prepare(halves(), 700, 20, 0, DPI, {})
    assert "7000" in sentence(error)
    assert cr.prepare(halves(), 400, 400, 0, DPI, {}).shape[:2] == (4000, 4000)      # 16 million pixels: allowed ...
    with pytest.raises(su.ValidationError) as error:                                 # ... but turned 45 degrees the box is 5657 x 5657
        cr.prepare(halves(), 400, 400, 45, DPI, {})
    assert "20 million" in sentence(error) and "5657" in str(error.value)


@pytest.mark.parametrize("dpi", (9.99, 0, -300, 5080.01, 6000, math.nan, math.inf, None, "fine", True))
def test_a_resolution_outside_10_to_5080_dpi_is_refused(dpi):
    with pytest.raises(su.ValidationError) as error:
        cr.prepare(halves(), 10, 5, 0, dpi, {})
    assert "10 to 5080" in sentence(error)


def test_the_limits_of_the_resolution_are_allowed():
    assert cr.prepare(halves(), 100, 50, 0, 10, {}).shape[:2] == (20, 39)
    assert cr.prepare(halves(), 10, 5, 0, 2400, {}).shape[:2] == (472, 945)


@pytest.mark.parametrize("width, height, rotation", ((0, 5, 0), (10, -5, 0), (math.nan, 5, 0), (10, 5, math.nan), ("x", 5, 0)))
def test_a_nonsense_size_or_turn_is_refused_with_a_sentence(width, height, rotation):
    with pytest.raises(su.ValidationError) as error:
        cr.prepare(halves(), width, height, rotation, DPI, {})
    sentence(error)


# -- preview_png ----------------------------------------------------------------------------------------------------------------------
def decode(png: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert image is not None
    return image


def test_the_preview_has_the_size_and_the_alpha_of_the_pixels():
    pixels = cr.prepare(gradient(), 24, 16, 40, DPI, {})
    for dither in ("grayscale", "jarvis", "threshold"):
        look = decode(cr.preview_png(pixels, dither, None, DPI))
        assert look.shape == pixels.shape and look.dtype == np.uint8
        assert np.array_equal(look[..., 3], pixels[..., 3])
    assert (pixels[..., 3] == 0).any() and (pixels[..., 3] == 255).any()


def test_plain_grey_is_the_grey_levels_of_the_pixels():
    pixels = cr.prepare(gradient(), 24, 16, 0, DPI, {})
    look = decode(cr.preview_png(pixels, "grayscale", None, DPI))
    assert np.array_equal(look[..., :3], pixels[..., :3])
    assert len(np.unique(look[..., 0])) > 50


@pytest.mark.parametrize("dither", ("sphere", "", None, "3dslice", "GRAYSCALE", "floyd steinberg", 7))
def test_an_unknown_image_mode_looks_like_plain_grey_and_never_raises(dither):
    pixels = cr.prepare(gradient(), 24, 16, 0, DPI, {})
    assert cr.preview_png(pixels, dither, None, DPI) == cr.preview_png(pixels, "grayscale", None, DPI)


@pytest.mark.parametrize("kind", dots.KINDS)
def test_a_dot_kind_is_drawn_as_black_dots_on_white_where_the_kind_fires(kind):
    pixels = cr.prepare(gradient(), 24, 16, 25, DPI, {})
    look = decode(cr.preview_png(pixels, kind, None, DPI))
    assert look.shape == pixels.shape
    assert set(np.unique(look[..., :3])) <= {0, 255}
    opaque = pixels[..., 3] >= 128
    grey = cv2.cvtColor(pixels[..., :3], cv2.COLOR_BGR2GRAY) / 255.0
    expected = dots.struck(grey, kind, dpi=DPI, alpha=pixels[..., 3] / 255.0)
    assert np.array_equal(look[..., 0] == 0, expected) and not expected[~opaque].any()
    assert np.array_equal(look[..., 3], pixels[..., 3])


def test_error_diffusion_gives_a_flat_grey_its_share_of_dots():
    flat = np.full((120, 160, 4), 255, np.uint8)
    flat[..., :3] = 191                                           # a quarter dark
    look = decode(cr.preview_png(flat, "dither", None, DPI))
    assert (look[..., 0] == 0).mean() == pytest.approx(0.25, abs=0.02)
    assert (decode(cr.preview_png(flat, "threshold", None, DPI))[..., 0] == 255).all()        # lighter than the cut: nothing fired
    assert len(np.unique(look[..., 0])) == 2


def test_the_names_of_the_catalogue_that_mean_a_dot_kind_are_drawn_as_it():
    pixels = cr.prepare(gradient(), 24, 16, 0, DPI, {})
    assert cr.preview_png(pixels, "FloydSteinberg", None, DPI) == cr.preview_png(pixels, "dither", None, DPI)
    assert cr.preview_png(pixels, "Jarvis", None, DPI) == cr.preview_png(pixels, "jarvis", None, DPI)
    assert cr.preview_png(pixels, "jarvis", None, DPI) != cr.preview_png(pixels, "grayscale", None, DPI)


def test_the_dot_width_is_not_drawn():
    pixels = cr.prepare(gradient(), 24, 16, 0, DPI, {})
    assert cr.preview_png(pixels, "jarvis", 0.03, DPI) == cr.preview_png(pixels, "jarvis", None, DPI)


def test_the_preview_accepts_grey_and_colour_pictures_and_refuses_the_rest_with_a_sentence():
    grey = np.tile(np.arange(0, 256, 4, dtype=np.uint8), (30, 1))
    assert decode(cr.preview_png(grey, "grayscale", None, DPI)).shape == (30, 64, 4)
    assert decode(cr.preview_png(np.dstack([grey] * 3), "dither", None, DPI)).shape == (30, 64, 4)
    for bad in (grey.astype(np.float32), np.zeros((5, 5, 2), np.uint8), np.zeros((0, 5), np.uint8), "picture", None):
        with pytest.raises(su.ValidationError) as error:
            cr.preview_png(bad, "grayscale", None, DPI)
        sentence(error)
    with pytest.raises(su.ValidationError):
        cr.preview_png(grey, "halftone", None, 0)


# -- determinism ----------------------------------------------------------------------------------------------------------------------
def test_the_same_input_gives_the_same_bytes():
    args = (gradient(), 24, 16, 33, 300.0, {"invert": True})
    first, second = cr.prepare(*args), cr.prepare(*args)
    assert first.tobytes() == second.tobytes()
    for dither in ("grayscale", "jarvis", "halftone", "ordered"):
        assert cr.preview_png(first, dither, None, 300.0) == cr.preview_png(second, dither, None, 300.0)


def test_the_cache_key_is_stable_short_and_follows_what_changes_the_picture():
    def key(**changes):
        base = dict(image_bytes_stamp="abc", width_mm=40.0, height_mm=25.0, rotation_deg=10.0, dpi=600.0, params={}, dither="jarvis", dot_width=None)
        return cr.cache_key(**{**base, **changes})

    base = key()
    assert base == key() and len(base) == 16 and int(base, 16) >= 0
    for change in ({"image_bytes_stamp": "abd"}, {"width_mm": 40.1}, {"height_mm": 24.0}, {"rotation_deg": 11.0}, {"dpi": 601.0},
                   {"params": {"invert": True}}, {"params": {"treatment": "pencil"}}, {"dither": "stucki"}, {"dither": "grayscale"},
                   {"dot_width": 0.02}):
        assert key(**change) != base
    assert key(params={"threshold": 30, "auto_threshold": False}) == base              # the threshold changes nothing here
    assert key(params={"detail": 10}) == base and key(params={"treatment": "pencil", "detail": 10}) != key(params={"treatment": "pencil"})
    assert key(dither="sphere") == key(dither=None) == key(dither="GRAYSCALE")           # all of them look like plain grey
    assert key(dither="FloydSteinberg") == key(dither="dither")
    assert key(image_bytes_stamp={"path": "/a.png", "size": 3, "mtime_ns": 5}) == key(image_bytes_stamp={"mtime_ns": 5, "size": 3, "path": "/a.png"})
    assert key(width_mm=40.0001) == base                                                  # millimetres to a thousandth


def test_the_cache_key_refuses_nonsense_with_a_sentence():
    for changes in ({"width_mm": 0}, {"rotation_deg": math.nan}, {"dpi": 5}, {"params": {"treatment": "oil"}}, {"dot_width": "wide"}):
        base = dict(image_bytes_stamp="abc", width_mm=40.0, height_mm=25.0, rotation_deg=10.0, dpi=600.0, params={}, dither="jarvis", dot_width=None)
        with pytest.raises(su.ValidationError) as error:
            cr.cache_key(**{**base, **changes})
        sentence(error)


# -- the layer ------------------------------------------------------------------------------------------------------------------------
def image_layer(pixels, width, height, dither="jarvis", x=5.0, y=6.0, interval=0.0169):
    return {"index": 1, "name": "Card - picture", "cut_type": "Image", "regions": [], "layer_keys": [], "prediction": None,
            "parameters": {"power": 30.0, "frequency": 60.0, "speed": 300.0, "pulse_width": None, "line_interval": interval, "passes": 1,
                           "min_power": 2.0, "global_passes": 1, "dot_width": None},
            "picture": {"x": x, "y": y, "width": width, "height": height, "pixels": pixels, "file": "picture.png", "dither": dither}}


@pytest.mark.parametrize("rotation", (0, 45))
def test_the_export_writes_the_pixels_as_an_image_layer_where_the_box_is(rotation):
    dpi = float(round(MM_PER_INCH / 0.0169))                           # the DPI LightBurn links to the layer's line interval
    pixels = cr.prepare(gradient(), 12, 8, rotation, dpi, {})
    width, height = cr.bounds(12, 8, rotation)
    plan = {"layers": [image_layer(pixels, width, height)], "export_mirror_y": True}
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    (layer,) = [l for l in project.layers if l.layer_type == "Image"]
    summary = layer.image_summary()
    assert (summary["dither"], summary["dpi"], summary["min_power"], layer.power) == ("jarvis", round(dpi), 2.0, 30.0)
    (region,) = layer.regions
    xs, ys = [p[0] for p in region.polygon], [p[1] for p in region.polygon]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((5.0, 5.0 + width, 6.0, 6.0 + height), abs=1e-3)
    stored = decode(region.bitmap["png"])
    assert np.array_equal(stored, pixels) and stored.shape[2] == 4                      # BGRA with its alpha, as laid out
    assert region.bitmap["w"] == pytest.approx(width, abs=1e-3) and region.bitmap["h"] == pytest.approx(height, abs=0.02)   # rows are whole pixels


def test_the_export_accepts_every_image_mode_the_preview_draws():
    pixels = cr.prepare(gradient(), 12, 8, 30, 600.0, {})
    width, height = cr.bounds(12, 8, 30)
    for kind in ("grayscale", *dots.KINDS):
        project = lightburn.parse_bytes(plans.export_lbrn2({"layers": [image_layer(pixels, width, height, dither=kind, interval=0.0423)],
                                                            "export_mirror_y": True}))
        assert [l.image_summary()["dither"] for l in project.layers if l.layer_type == "Image"] == [kind]


def test_check_says_the_size_or_the_sentence_without_decoding_anything():
    assert cr.check(85, 53, 0, 254) == (850, 530)
    with pytest.raises(su.ValidationError, match="8500 x 5300 pixels at 2540 dpi"):
        cr.check(85, 53, 0, 2540)
    with pytest.raises(su.ValidationError, match="resolution"):
        cr.check(85, 53, 0, 20000)
    assert cr.check(30, 20, 0, 2540) == (3000, 2000)
