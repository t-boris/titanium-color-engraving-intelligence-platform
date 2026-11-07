"""Graphic -> engravable card geometry, with the optional pencil treatment (feature-2, REQ-002, REQ-004)."""
import json
import math
import time

import cv2
import numpy as np
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon

from titanium_platform import card_image as ci, setup as su

WHITE, BLACK = 255, 0


def canvas(h, w, tone=WHITE):
    return np.full((h, w, 3), tone, np.uint8)


def disc(size=400, radius=120, fg=BLACK, bg=WHITE, antialiased=True):
    img = canvas(size, size, bg)
    cv2.circle(img, (size // 2, size // 2), radius, (fg,) * 3, -1, cv2.LINE_AA if antialiased else cv2.LINE_8)
    return img


def ring_image():
    img = disc()
    cv2.circle(img, (200, 200), 60, (WHITE,) * 3, -1, cv2.LINE_AA)
    return img


def logo():
    """A black ring with a grey dot, a word in black, a word in dark grey and a frame: a typical logo on white."""
    img = canvas(600, 900)
    cv2.circle(img, (220, 300), 160, (0, 0, 0), -1, cv2.LINE_AA)
    cv2.circle(img, (220, 300), 80, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(img, (220, 300), 40, (120, 120, 120), -1, cv2.LINE_AA)
    cv2.putText(img, "Boris", (420, 250), cv2.FONT_HERSHEY_SIMPLEX, 3.5, (0, 0, 0), 10, cv2.LINE_AA)
    cv2.putText(img, "titanium", (430, 420), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 3, (60, 60, 60), 4, cv2.LINE_AA)
    cv2.rectangle(img, (430, 470), (850, 560), (0, 0, 0), 3, cv2.LINE_AA)
    return img


def photo(width=1600, height=1067, seed=1, noise=6.0):
    """A photo-like picture: a gradient, soft blobs of light and shade, sensor noise, and a dark disc and a word on top."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    grey = 60 + 90 * (x / width) + 32 * (y / height)
    for _ in range(14):
        cx, cy, r = rng.uniform(0, width), rng.uniform(0, height), rng.uniform(0.03, 0.14) * width
        grey += rng.uniform(-90, 90) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * r * r)))
    grey = np.clip(grey + rng.normal(0, noise, grey.shape), 0, 255).astype(np.uint8)
    img = cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)
    cv2.circle(img, (width // 2, height // 2), height // 4, (20, 20, 20), -1, cv2.LINE_AA)
    cv2.putText(img, "Titan", (width // 8, height // 4), cv2.FONT_HERSHEY_DUPLEX, width / 270, (10, 10, 10), width // 115, cv2.LINE_AA)
    return img


def parts(geom):
    return list(geom.geoms) if geom.geom_type == "MultiPolygon" else ([] if geom.is_empty else [geom])


def vertices(geom):
    return int(shapely.get_num_coordinates(geom))


def holes(geom):
    return sum(len(p.interiors) for p in parts(geom))


def png(img):
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def assert_clean(geom, box=None):
    """What the card editor relies on: polygons only, valid, and inside the box."""
    assert isinstance(geom, (Polygon, MultiPolygon))
    assert geom.is_valid
    for p in parts(geom):
        assert p.exterior.is_ring
        assert all(i.is_ring for i in p.interiors)
    if box and not geom.is_empty:
        x0, y0, x1, y1 = geom.bounds
        assert -box[0] / 2 - 1e-6 <= x0 and x1 <= box[0] / 2 + 1e-6 and -box[1] / 2 - 1e-6 <= y0 and y1 <= box[1] / 2 + 1e-6


# -- geometry of simple pictures ----------------------------------------------------------------------------------------------------
def test_disc_area_and_shape():
    g = ci.geometry(disc(), 40, 40)             # 0.1 mm per pixel, a radius of 120 pixels = 12 mm (the drawn disc reaches half a pixel further)
    assert_clean(g, (40, 40))
    assert g.geom_type == "Polygon" and not g.interiors
    assert g.area == pytest.approx(math.pi * 12.05 ** 2, rel=0.02)
    x, y = np.array(g.exterior.coords).T
    cx, cy = (x.max() + x.min()) / 2, (y.max() + y.min()) / 2
    assert abs(cx) < 0.1 and abs(cy) < 0.1                       # centred (the picture's own pixel grid is half a pixel off)
    radial = np.hypot(x - cx, y - cy)
    assert radial.max() - radial.min() < 0.1                     # round, to well under a pixel


def test_circle_edge_is_not_a_pixel_staircase():
    for antialiased in (True, False):
        g = ci.geometry(disc(size=400, radius=120, antialiased=antialiased), 40, 40)
        x, y = np.array(g.exterior.coords).T
        a = np.c_[2 * x, 2 * y, np.ones(len(x))]
        cx, cy, c = np.linalg.lstsq(a, x * x + y * y, rcond=None)[0]
        radius = math.sqrt(c + cx * cx + cy * cy)
        assert np.abs(np.hypot(x - cx, y - cy) - radius).max() < 0.05          # half a source pixel is 0.05 mm
        assert vertices(g) < 200                                                # a staircase of 0.1 mm steps would need ~1500


def test_ring_is_one_polygon_with_one_hole():
    g = ci.geometry(ring_image(), 40, 40)
    assert_clean(g, (40, 40))
    assert g.geom_type == "Polygon" and len(g.interiors) == 1
    assert g.area == pytest.approx(math.pi * (12.05 ** 2 - 5.95 ** 2), rel=0.02)
    assert Polygon(g.interiors[0]).contains(shapely.Point(0.05, 0.05))


def test_text_gives_letters_with_counters():
    img = canvas(300, 900)
    cv2.putText(img, "BAO", (20, 250), cv2.FONT_HERSHEY_SIMPLEX, 4.5, (0, 0, 0), 12, cv2.LINE_AA)
    g = ci.geometry(img, 90, 30)
    assert_clean(g, (90, 30))
    assert len(parts(g)) >= 3 and holes(g) >= 4                  # B has two counters, A one, O one


def test_contain_fit_keeps_the_aspect_and_stays_in_the_box():
    wide = ci.geometry(canvas(100, 400, BLACK), 40, 40)          # a solid 4:1 picture in a square box
    assert wide.bounds == pytest.approx((-20, -5, 20, 5), abs=1e-6)
    assert wide.area == pytest.approx(400, rel=1e-3)
    tall = ci.geometry(canvas(400, 100, BLACK), 40, 30)           # a 1:4 picture in a 40 x 30 box: the height limits
    assert tall.bounds == pytest.approx((-3.75, -15, 3.75, 15), abs=1e-6)
    wide_box = ci.geometry(canvas(200, 300, BLACK), 60, 60)       # 3:2 in a square
    assert wide_box.bounds == pytest.approx((-30, -20, 30, 20), abs=1e-6)
    off_centre = canvas(400, 400)                                 # a dot in the upper left quarter of a 20 mm box
    cv2.circle(off_centre, (100, 100), 30, (0, 0, 0), -1, cv2.LINE_AA)
    g = ci.geometry(off_centre, 20, 20)
    assert_clean(g, (20, 20))
    assert g.bounds == pytest.approx((-6.5, -6.5, -3.5, -3.5), abs=0.1)         # the position in the picture is kept, centred on (0, 0)


def test_solid_picture_is_an_exact_rectangle():
    g = ci.geometry(canvas(300, 600, BLACK), 80, 80)
    assert g.geom_type == "Polygon" and vertices(g) == 5 and g.bounds == pytest.approx((-40, -20, 40, 20), abs=1e-6)


def test_all_white_and_all_black_are_valid_not_errors():
    for treatment in ("none", "pencil"):
        white = ci.geometry(canvas(300, 600, WHITE), 80, 80, {"treatment": treatment})
        black = ci.geometry(canvas(300, 600, BLACK), 80, 80, {"treatment": treatment})
        assert_clean(white, (80, 80))
        assert_clean(black, (80, 80))
        assert white.is_empty
        assert not black.is_empty and black.bounds == pytest.approx((-40, -20, 40, 20), abs=1e-6)
        assert ci.geometry(canvas(300, 600, WHITE), 80, 80, {"treatment": treatment, "invert": True}).area > 0
    assert ci.geometry(canvas(300, 600, BLACK), 80, 80).area == pytest.approx(3200, rel=1e-6)


def test_invert_engraves_the_light_areas():
    img = disc()
    plain, inverted = ci.geometry(img, 40, 40), ci.geometry(img, 40, 40, {"invert": True})
    assert_clean(inverted, (40, 40))
    assert plain.area + inverted.area == pytest.approx(1600, rel=0.01)
    assert plain.intersection(inverted).area < 0.5
    assert inverted.geom_type == "Polygon" and len(inverted.interiors) == 1      # the box with a round hole


def test_grey_picture_and_colour_picture_are_read_by_their_grey_level():
    img = canvas(200, 200)
    cv2.rectangle(img, (40, 40), (160, 160), (30, 30, 200), -1)                  # saturated red: grey level about 80
    assert ci.geometry(img, 20, 20).area == pytest.approx(144, rel=0.03)
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert ci.geometry(grey, 20, 20).area == pytest.approx(144, rel=0.03)       # a 2-D grey array works too


def test_automatic_and_manual_threshold():
    img = canvas(400, 400, 200)
    cv2.circle(img, (200, 200), 120, (60, 60, 60), -1, cv2.LINE_AA)
    auto = ci.geometry(img, 40, 40)
    assert auto.area == pytest.approx(math.pi * 12.05 ** 2, rel=0.02)            # Otsu finds the level between 60 and 200
    assert ci.geometry(img, 40, 40, {"auto_threshold": False, "threshold": 128}).area == pytest.approx(auto.area, rel=0.01)
    assert ci.geometry(img, 40, 40, {"auto_threshold": False, "threshold": 30}).is_empty          # nothing is that dark
    assert ci.geometry(img, 40, 40, {"auto_threshold": False, "threshold": 220}).area == pytest.approx(1600, rel=1e-3)   # all of it is
    assert ci.geometry(img, 40, 40, {"threshold": None}).area == pytest.approx(auto.area, rel=1e-9)     # None means automatic


def test_manual_threshold_moves_the_edge_of_a_gradient():
    ramp = np.tile(np.linspace(0, 255, 600).astype(np.uint8), (200, 1))
    ramp = cv2.cvtColor(ramp, cv2.COLOR_GRAY2BGR)
    areas = [ci.geometry(ramp, 60, 20, {"auto_threshold": False, "threshold": t}).area for t in (50, 128, 200)]
    assert areas[0] == pytest.approx(1200 * 50 / 255, rel=0.03)
    assert areas[1] == pytest.approx(1200 * 128 / 255, rel=0.03)
    assert areas[2] == pytest.approx(1200 * 200 / 255, rel=0.03)
    assert areas[0] < areas[1] < areas[2]


def test_specks_and_pinholes_below_the_smallest_feature_are_removed():
    img = disc(radius=100)
    for x, y in ((30, 30), (370, 40), (40, 370), (370, 370), (200, 20)):         # 3 x 3 pixel specks: 0.09 mm2
        img[y:y + 3, x:x + 3] = 0
    for x, y in ((180, 200), (220, 150), (200, 250)):                            # and the same as pinholes in the disc
        img[y:y + 3, x:x + 3] = 255
    fine = ci.geometry(img, 40, 40, {"min_feature_mm": 0.05})
    coarse = ci.geometry(img, 40, 40, {"min_feature_mm": 0.5})                   # 0.25 mm2
    assert len(parts(fine)) == 6 and holes(fine) == 3
    assert len(parts(coarse)) == 1 and holes(coarse) == 0
    assert_clean(coarse, (40, 40))
    for g, floor in ((fine, 0.05 ** 2), (coarse, 0.5 ** 2)):
        assert all(p.area >= floor for p in parts(g))
        assert all(Polygon(i).area >= floor for p in parts(g) for i in p.interiors)


def test_every_polygon_and_hole_is_at_least_the_smallest_feature():
    rng = np.random.default_rng(3)
    noise = cv2.GaussianBlur(rng.integers(0, 256, (500, 500), dtype=np.uint8), (0, 0), 1.5)
    noise = cv2.normalize(noise, None, 0, 255, cv2.NORM_MINMAX)
    g = ci.geometry(cv2.cvtColor(noise, cv2.COLOR_GRAY2BGR), 50, 50, {"min_feature_mm": 0.3})
    assert_clean(g, (50, 50))
    assert len(parts(g)) > 5
    assert all(p.area >= 0.09 for p in parts(g)) and all(Polygon(i).area >= 0.09 for p in parts(g) for i in p.interiors)


def test_vertex_cap_holds_on_a_noisy_picture():
    rng = np.random.default_rng(5)
    noise = cv2.GaussianBlur(rng.integers(0, 256, (900, 900), dtype=np.uint8), (0, 0), 1.2)
    noise = cv2.cvtColor(cv2.normalize(noise, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)
    for params in ({"min_feature_mm": 0.05}, {"min_feature_mm": 0.05, "treatment": "pencil", "detail": 100, "strength": 100}):
        g = ci.geometry(noise, 60, 60, params)
        assert_clean(g, (60, 60))
        assert not g.is_empty
        assert vertices(g) <= ci.MAX_VERTICES


def test_vertex_cap_coarsens_instead_of_failing(monkeypatch):
    img = logo()
    full = ci.geometry(img, 85, 60)
    assert vertices(full) > 400
    monkeypatch.setattr(ci, "MAX_VERTICES", 400)
    capped = ci.geometry(img, 85, 60)
    assert_clean(capped, (85, 60))
    assert not capped.is_empty
    assert vertices(capped) <= 400
    assert capped.area == pytest.approx(full.area, rel=0.1)                      # the shapes are the same, only less finely drawn


def test_the_result_does_not_depend_on_the_run():
    img = logo()
    for params in ({}, {"treatment": "pencil"}):
        assert ci.geometry(img, 85, 60, params).equals_exact(ci.geometry(img, 85, 60, params), 0)


def test_small_picture_is_smooth_and_large_picture_is_capped():
    icon = disc(size=48, radius=15)
    g = ci.geometry(icon, 24, 24)
    assert_clean(g, (24, 24))
    assert g.area == pytest.approx(math.pi * 7.75 ** 2, rel=0.08)
    huge = disc(size=2400, radius=700)                                           # more than WORK_PX: read at WORK_PX, no error
    assert ci.geometry(huge, 40, 40).area == pytest.approx(math.pi * (700 / 2400 * 40) ** 2, rel=0.02)


def test_bad_arguments_are_operator_errors():
    for width, height in ((0, 10), (10, 0), (-1, 10), (float("nan"), 10), (10, float("inf")), ("x", 10), (None, 10)):
        with pytest.raises(su.ValidationError, match="positive"):
            ci.geometry(disc(), width, height)
    for bad in (np.zeros((10, 10, 3), np.float32), np.zeros((10, 10, 4), np.uint8), np.zeros((0, 5, 3), np.uint8), "picture", None):
        with pytest.raises(su.ValidationError, match="8-bit"):
            ci.geometry(bad, 10, 10)
    with pytest.raises(su.ValidationError, match="Treatment"):
        ci.geometry(disc(), 10, 10, {"treatment": "crayon"})


# -- the pencil treatment -----------------------------------------------------------------------------------------------------------
def test_pencil_gives_different_non_empty_valid_geometry():
    img = logo()
    plain, pencil = ci.geometry(img, 85, 60), ci.geometry(img, 85, 60, {"treatment": "pencil"})
    assert_clean(pencil, (85, 60))
    assert not pencil.is_empty
    assert not pencil.equals(plain)
    assert pencil.symmetric_difference(plain).area > 0.1 * plain.area            # not the same drawing
    assert vertices(pencil) > vertices(plain)                                    # strokes and hatching are more detail
    assert holes(pencil) > holes(plain)                                          # the hatching leaves paper between its strokes
    assert pencil.area < ci.geometry(img, 85, 60, {"invert": True}).area


def test_pencil_on_a_photo_is_valid_and_non_empty():
    img = photo(800, 533)
    plain, pencil = ci.geometry(img, 85, 54), ci.geometry(img, 85, 54, {"treatment": "pencil"})
    assert_clean(pencil, (85, 54))
    assert not pencil.is_empty and not pencil.equals(plain)
    assert vertices(pencil) <= ci.MAX_VERTICES


def test_pencil_strength_makes_the_strokes_darker_and_denser():
    for img in (logo(), photo(800, 533)):
        weak = ci.geometry(img, 85, 60, {"treatment": "pencil", "strength": 10})
        strong = ci.geometry(img, 85, 60, {"treatment": "pencil", "strength": 90})
        assert strong.area > 1.2 * weak.area
    grey = cv2.cvtColor(logo(), cv2.COLOR_BGR2GRAY)
    means = [ci.pencil_sketch(grey, 50, s).mean() for s in (0, 25, 50, 75, 100)]
    assert all(a > b for a, b in zip(means, means[1:]))                           # the sketch itself gets darker, step by step


def test_pencil_detail_keeps_more_fine_texture():
    img = photo(800, 533)
    coarse = ci.geometry(img, 85, 54, {"treatment": "pencil", "detail": 5})
    fine = ci.geometry(img, 85, 54, {"treatment": "pencil", "detail": 95})
    assert vertices(fine) > 1.3 * vertices(coarse)
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    low, high = ci.pencil_sketch(grey, 5, 60), ci.pencil_sketch(grey, 95, 60)
    assert np.abs(low.astype(int) - high.astype(int)).mean() > 5                  # a different drawing, not a tweak
    # at 100 % the image's own noise is drawn, at 0 % it is smoothed away: more strokes cross the picture
    assert (high < 128).sum() != (low < 128).sum()


def test_pencil_sketch_is_a_white_paper_with_dark_strokes():
    grey = cv2.cvtColor(logo(), cv2.COLOR_BGR2GRAY)
    sketch = ci.pencil_sketch(grey, 50, 60)
    assert sketch.dtype == np.uint8 and sketch.shape == grey.shape
    assert sketch.min() < 40 and np.median(sketch) == 255                         # strokes are dark, the paper is white
    assert (sketch[:100, :100] == 255).all()                                      # the white corner of the logo stays white
    assert (ci.pencil_sketch(np.full((60, 80), 255, np.uint8)) == 255).all()
    assert ci.pencil_sketch(np.zeros((60, 80), np.uint8)).mean() < 200            # solid black is hatched, not left blank
    assert ci.pencil_sketch(logo()).shape == grey.shape                           # a BGR picture is accepted
    for detail, strength in ((-1, 50), (101, 50), (50, -1), (50, 101), (50.5, 50), ("a", 50)):
        with pytest.raises(su.ValidationError):
            ci.pencil_sketch(grey, detail, strength)


def test_pencil_strokes_are_at_least_the_smallest_feature_wide():
    for img, box in ((logo(), (85, 60)), (photo(800, 533), (85, 54)), (logo(), (25, 25))):
        for feature in (0.1, 0.25):
            for detail, strength in ((50, 60), (100, 0), (0, 100)):
                g = ci.geometry(img, *box, {"treatment": "pencil", "min_feature_mm": feature, "detail": detail, "strength": strength})
                assert not g.is_empty
                r = 0.4 * feature                                                  # what is thinner than 0.8 x the feature vanishes here
                assert g.buffer(-r).buffer(r).area >= 0.95 * g.area


def test_pencil_follows_invert_and_threshold():
    light_on_dark = 255 - logo()
    normal = ci.geometry(logo(), 85, 60, {"treatment": "pencil"})
    inverted = ci.geometry(light_on_dark, 85, 60, {"treatment": "pencil", "invert": True})
    assert inverted.area == pytest.approx(normal.area, rel=0.1)
    assert ci.geometry(light_on_dark, 85, 60, {"treatment": "pencil"}).area != pytest.approx(normal.area, rel=0.1)
    low = ci.geometry(logo(), 85, 60, {"treatment": "pencil", "auto_threshold": False, "threshold": 40})
    high = ci.geometry(logo(), 85, 60, {"treatment": "pencil", "auto_threshold": False, "threshold": 200})
    assert low.area < normal.area < high.area


# -- reading files ------------------------------------------------------------------------------------------------------------------
def test_load_decodes_common_formats_and_reports_the_size():
    img = disc(size=120, radius=40)
    img = np.hstack([img, img[:, :60]])                                           # 180 x 120
    for ext in (".png", ".jpg", ".bmp", ".tif", ".webp"):
        ok, buf = cv2.imencode(ext, img)
        assert ok
        data = buf.tobytes()
        assert ci.image_size(data) == (180, 120), ext
        loaded = ci.load(data)
        assert loaded.shape == (120, 180, 3) and loaded.dtype == np.uint8, ext
        assert loaded[60, 40].max() < 60 and loaded[2, 2].min() > 200, ext
    ok, buf = cv2.imencode(".gif", img)
    if ok and cv2.imdecode(buf, cv2.IMREAD_UNCHANGED) is not None:
        assert ci.image_size(buf.tobytes()) == (180, 120) and ci.load(buf.tobytes()).shape == (120, 180, 3)


def test_image_size_of_a_hand_made_gif_and_unknown_headers():
    gif = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
           b"\x00\x02\x02D\x01\x00;")
    assert ci.image_size(gif) == (1, 1)
    with pytest.raises(su.ValidationError, match="not a picture"):
        ci.image_size(b"just some text, not a picture")
    with pytest.raises(su.ValidationError, match="empty"):
        ci.image_size(b"")


def test_load_rejects_empty_and_undecodable_data():
    for bad in (b"", None, "text", 12, b"definitely not an image", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, b"\xff\xd8\xff\xe0" + b"\x00" * 40):
        with pytest.raises(su.ValidationError):
            ci.load(bad)
    with pytest.raises(su.ValidationError, match="empty"):
        ci.load(b"")
    with pytest.raises(su.ValidationError, match="PNG, JPEG"):
        ci.load(b"definitely not an image")
    good = png(disc(size=60, radius=20))
    with pytest.raises(su.ValidationError):
        ci.load(good[:len(good) // 2])                                            # a cut-off file
    assert ci.load(bytearray(good)).shape == (60, 60, 3) and ci.load(memoryview(good)).shape == (60, 60, 3)


def test_load_rejects_huge_pictures_before_decoding_them():
    wide = png(np.zeros((10, 8001), np.uint8))
    with pytest.raises(su.ValidationError, match="too large") as e:
        ci.load(wide)
    assert "8001 x 10" in str(e.value) and "8000" in str(e.value)
    with pytest.raises(su.ValidationError, match="megapixels"):
        ci.load(png(np.zeros((6500, 6500), np.uint8)))                             # 42 megapixels
    assert ci.image_size(wide) == (8001, 10)
    assert ci.load(png(np.full((10, 8000), 255, np.uint8))).shape == (2, 1600, 3)          # the limit itself is allowed


def test_load_caps_the_long_side_and_keeps_small_pictures():
    big = ci.load(png(np.full((2000, 3000, 3), 200, np.uint8)))
    assert big.shape == (1067, 1600, 3) and big.dtype == np.uint8 and big.flags["C_CONTIGUOUS"]
    assert abs(int(big.mean()) - 200) <= 1
    tall = ci.load(png(np.full((3200, 800, 3), 10, np.uint8)))
    assert tall.shape == (1600, 400, 3)
    assert ci.load(png(np.full((40, 50, 3), 10, np.uint8))).shape == (40, 50, 3)     # never enlarged
    assert ci.load(png(np.full((8000, 4, 3), 10, np.uint8))).shape == (1600, 1, 3)    # a thin strip keeps one column


def test_load_composites_transparency_on_white():
    bgra = np.zeros((80, 120, 4), np.uint8)                       # fully transparent, and the hidden colour is black
    cv2.circle(bgra, (60, 40), 25, (0, 0, 0, 255), -1)             # an opaque black disc
    cv2.rectangle(bgra, (5, 5), (25, 25), (0, 0, 0, 128), -1)      # a half transparent black square
    loaded = ci.load(png(bgra))
    assert loaded.shape == (80, 120, 3)
    assert (loaded[0, 0] == 255).all() and (loaded[79, 119] == 255).all()        # transparent: white paper, not black
    assert (loaded[40, 60] == 0).all()
    assert abs(int(loaded[15, 15][0]) - 127) <= 1                                 # half transparent black on white: mid grey
    g = ci.geometry(loaded, 12, 8)                                                # and the logo engraves, not its background
    assert g.area == pytest.approx(math.pi * 2.5 ** 2 + 2 * 2, rel=0.12)
    assert ci.geometry(loaded, 12, 8).area < 40


def test_load_handles_grey_and_deep_pictures():
    grey = np.full((50, 70), 90, np.uint8)
    loaded = ci.load(png(grey))
    assert loaded.shape == (50, 70, 3) and (loaded == 90).all()
    deep = np.full((30, 40), 65535, np.uint16)
    deep[:, :20] = 0
    loaded = ci.load(png(deep))
    assert loaded.dtype == np.uint8 and (loaded[:, :20] == 0).all() and (loaded[:, 20:] == 255).all()
    palette_like = canvas(30, 40, 255)
    palette_like[:, :10] = (0, 0, 255)
    assert ci.load(png(palette_like))[5, 3].tolist() == [0, 0, 255]               # colour is kept (BGR order)


def test_a_jpeg_photograph_is_turned_by_its_exif_orientation():
    img = np.hstack([canvas(40, 40, 0), canvas(40, 40, 255)])                     # dark left, light right: 80 wide, 40 high
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    plain = buf.tobytes()
    assert ci.load(plain).shape == (40, 80, 3)
    exif = b"Exif\x00\x00" + b"II*\x00\x08\x00\x00\x00" + b"\x01\x00" + b"\x12\x01\x03\x00\x01\x00\x00\x00\x06\x00\x00\x00" + b"\x00\x00\x00\x00"
    turned = plain[:2] + b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif + plain[2:]       # orientation 6: turn 90 degrees clockwise
    loaded = ci.load(turned)
    assert loaded.shape == (80, 40, 3)
    assert loaded[:40].mean() < 60 and loaded[40:].mean() > 200                   # the dark half is now on top
    assert ci.image_size(turned) == (80, 40)                                      # the size is the stored one, as the docstring says


# -- settings -----------------------------------------------------------------------------------------------------------------------
def test_params_describe_the_card_editor_fields():
    names = [spec["name"] for spec in ci.IMAGE_PARAMS]
    assert set(names) == {"threshold", "auto_threshold", "invert", "treatment", "detail", "strength", "min_feature_mm"}
    for spec in ci.IMAGE_PARAMS:
        assert {"name", "label", "type", "min", "max", "default", "unit"} <= set(spec)
        assert spec["type"] in ("number", "int", "bool", "choice") and spec["label"]
        assert ci.DEFAULTS[spec["name"]] == spec["default"]
        if spec["type"] in ("number", "int"):
            assert spec["min"] <= spec["default"] <= spec["max"]
    by_name = {spec["name"]: spec for spec in ci.IMAGE_PARAMS}
    assert (by_name["threshold"]["min"], by_name["threshold"]["max"], by_name["threshold"]["default"]) == (0, 255, 128)
    assert by_name["auto_threshold"]["default"] is True and by_name["invert"]["default"] is False
    assert by_name["treatment"]["options"] == ["none", "pencil"] and by_name["treatment"]["default"] == "none"
    assert set(by_name["treatment"]["option_labels"]) == {"none", "pencil"}
    assert (by_name["detail"]["min"], by_name["detail"]["max"], by_name["detail"]["default"]) == (0, 100, 50)
    assert (by_name["strength"]["min"], by_name["strength"]["max"], by_name["strength"]["default"]) == (0, 100, 60)
    assert (by_name["min_feature_mm"]["min"], by_name["min_feature_mm"]["max"], by_name["min_feature_mm"]["default"]) == (0.05, 1, 0.15)
    json.dumps(ci.IMAGE_PARAMS)                                                   # the editor receives it as JSON


def test_checked_fills_defaults_and_is_idempotent():
    assert ci.checked(None) == ci.DEFAULTS == ci.checked({})
    full = ci.checked({"threshold": 77.0, "auto_threshold": False, "invert": True, "treatment": "pencil", "detail": 20, "strength": 95,
                       "min_feature_mm": 1})
    assert full == {"threshold": 77, "auto_threshold": False, "invert": True, "treatment": "pencil", "detail": 20, "strength": 95,
                    "min_feature_mm": 1.0}
    assert isinstance(full["threshold"], int) and isinstance(full["min_feature_mm"], float)
    assert ci.checked(full) == full
    assert ci.checked({"threshold": None})["auto_threshold"] is True
    assert ci.checked({"threshold": None, "auto_threshold": False})["auto_threshold"] is True
    assert ci.checked({"min_feature_mm": np.float64(0.2), "detail": np.int64(7)}) == {**ci.DEFAULTS, "min_feature_mm": 0.2, "detail": 7}


@pytest.mark.parametrize("params,field", [
    ({"threshold": 256}, "Threshold"), ({"threshold": -1}, "Threshold"), ({"threshold": "dark"}, "Threshold"),
    ({"threshold": 100.5}, "Threshold"), ({"threshold": True}, "Threshold"), ({"threshold": float("nan")}, "Threshold"),
    ({"auto_threshold": 1}, "Automatic threshold"), ({"auto_threshold": "yes"}, "Automatic threshold"),
    ({"invert": "no"}, "Invert"), ({"invert": 0}, "Invert"), ({"invert": None}, "Invert"),
    ({"treatment": "crayon"}, "Treatment"), ({"treatment": None}, "Treatment"), ({"treatment": ["pencil"]}, "Treatment"),
    ({"detail": -1}, "Detail"), ({"detail": 101}, "Detail"), ({"detail": 5.5}, "Detail"), ({"detail": None}, "Detail"),
    ({"strength": -5}, "Strength"), ({"strength": 100.1}, "Strength"), ({"strength": "strong"}, "Strength"),
    ({"min_feature_mm": 0.04}, "Smallest feature"), ({"min_feature_mm": 1.01}, "Smallest feature"), ({"min_feature_mm": 0}, "Smallest feature"),
    ({"min_feature_mm": "0.1"}, "Smallest feature"), ({"min_feature_mm": float("inf")}, "Smallest feature"), ({"min_feature_mm": False}, "Smallest feature"),
])
def test_checked_names_the_field_that_is_wrong(params, field):
    with pytest.raises(su.ValidationError) as e:
        ci.checked(params)
    assert field in str(e.value) and str(e.value).endswith(".")


def test_checked_rejects_unknown_fields_and_non_objects():
    with pytest.raises(su.ValidationError, match="'colour'"):
        ci.checked({"colour": "red"})
    for bad in ([], "pencil", 5, ("detail", 5)):
        with pytest.raises(su.ValidationError, match="object"):
            ci.checked(bad)
    with pytest.raises(su.ValidationError, match="Strength"):
        ci.geometry(disc(), 10, 10, {"strength": 500})


def test_cache_key_is_stable_and_follows_what_matters():
    key = ci.cache_key("abc", {"detail": 30}, 40.04, 25.0)
    assert key == ci.cache_key("abc", {"detail": 30, "treatment": "none", "strength": 60}, 40.0, 25.04)     # defaults spelled out, mm to 0.1
    assert key == ci.cache_key("abc", {"strength": 60, "detail": 30}, 40.0, 25.0)                          # key order is irrelevant
    assert json.loads(key)[0] == "abc"
    for other in (ci.cache_key("abd", {"detail": 30}, 40.0, 25.0), ci.cache_key("abc", {"detail": 31}, 40.0, 25.0),
                  ci.cache_key("abc", {"detail": 30}, 40.2, 25.0), ci.cache_key("abc", {"detail": 30}, 40.0, 24.8),
                  ci.cache_key("abc", {"detail": 30, "invert": True}, 40.0, 25.0)):
        assert other != key
    with pytest.raises(su.ValidationError):
        ci.cache_key("abc", {"detail": 300}, 40, 25)


# -- speed --------------------------------------------------------------------------------------------------------------------------
def test_a_full_size_picture_is_traced_in_time():
    img = ci.load(png(photo()))
    assert img.shape == (1067, 1600, 3)
    for params in ({}, {"treatment": "pencil"}, {"treatment": "pencil", "detail": 100, "strength": 100, "min_feature_mm": 0.05}):
        start = time.perf_counter()
        g = ci.geometry(img, 85, 54, params)
        elapsed = time.perf_counter() - start
        assert elapsed < 3.0, (params, elapsed)                                   # a generous guard; about 0.1 to 0.3 s here
        assert_clean(g, (85, 54))
        assert not g.is_empty and vertices(g) <= ci.MAX_VERTICES
