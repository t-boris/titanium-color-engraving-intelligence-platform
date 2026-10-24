"""The geometry of an inscription (feature inscriptions-in-works, REQ-002, DEC-003): a text set in a font at a letter height, laid out
straight, on an arc, around a circle or along a path, turned and placed, with the gap and the backing it cuts into a picture. Measured on
the test font of ``font_kit``, whose letters are rectangles of known area (cap height 700 of 1000 units)."""
import math

import numpy as np
import pytest

from font_kit import AREA, CAP, make_font
from titanium_platform import fonts, lettering as L, setup as su

WORK = {"width": 100.0, "height": 80.0}


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data"


def face(data, family="Test Sans", style="Regular"):
    return fonts.described(next(f for f in fonts.faces(data).values() if f["family"] == family and f["style"] == style))


def geo(data, size=WORK, **spec):
    return L.geometry(data, L.checked({"font": face(data), "x": 50, "y": 40, "height_mm": 7, **spec}), size)


def mm2(units2, height=7.0):
    """An area of the test font's units at a letter height, in mm²."""
    return units2 * (height / CAP) ** 2


def test_the_letter_height_is_the_height_of_the_capitals_and_the_area_is_the_fonts(data):
    g = geo(data, text="H", height_mm=7)
    x0, y0, x1, y1 = g["letters"].bounds
    assert y1 - y0 == pytest.approx(7.0, abs=1e-6) and x1 - x0 == pytest.approx(5.0, abs=1e-6)       # the stems 50..550 of 1000
    assert g["letters"].area == pytest.approx(mm2(AREA["H"]), rel=1e-9)                              # three overlapping contours made one
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((50, 40))                                 # a line stands with its middle on (x, y)
    ring = geo(data, text="O", height_mm=7)["letters"]
    assert ring.area == pytest.approx(mm2(AREA["O"])) and len(ring.geoms[0].interiors) == 1          # the hole of the O stays open


def test_a_font_that_does_not_state_its_cap_height_is_measured_on_its_h(data):
    make_font(fonts.own_dir(data) / "NoCap.ttf", family="No Cap", cap=-1)                         # as Corsiva Hebrew and Raanana do
    g = L.geometry(data, L.checked({"font": face(data, "No Cap"), "x": 50, "y": 40, "height_mm": 7, "text": "HO"}), WORK)
    x0, y0, x1, y1 = g["letters"].bounds
    assert y1 - y0 == pytest.approx(7.0, abs=1e-6) and g["letters"].area == pytest.approx(mm2(AREA["H"] + AREA["O"]))


def test_width_spacing_rotation_and_lines(data):
    plain, wide = geo(data, text="HH"), geo(data, text="HH", width_pct=200)
    assert wide["letters"].area == pytest.approx(2 * plain["letters"].area)
    width = lambda g: g["letters"].bounds[2] - g["letters"].bounds[0]          # noqa: E731
    assert width(wide) == pytest.approx(2 * width(plain))
    assert width(geo(data, text="HH", spacing_mm=3)) == pytest.approx(width(plain) + 3)               # spacing between letters, not after the last
    turned = geo(data, text="HH", rotation=90)["letters"].bounds
    assert turned[3] - turned[1] == pytest.approx(width(plain)) and turned[2] - turned[0] == pytest.approx(7.0)
    two = geo(data, text="H\nH", line_pct=100)["letters"]
    assert two.area == pytest.approx(2 * mm2(AREA["H"])) and two.bounds[3] - two.bounds[1] == pytest.approx(10 + 7)   # 1000 units a line


def test_the_letters_of_several_scripts_and_right_to_left(data):
    g = geo(data, text="HП ОH")          # Latin H, Cyrillic П and a Cyrillic О the test font does not have
    assert g["missing"] == ["О"] and g["letters"].area == pytest.approx(mm2(2 * AREA["H"] + AREA["П"]))
    assert geo(data, text="אגדה")["missing"] == ["ג", "ד", "ה"]      # named in the order of the text, though set right to left
    hebrew = geo(data, text="אב")["letters"].geoms
    alef = max(hebrew, key=lambda p: p.area)
    bet = min(hebrew, key=lambda p: p.area)
    assert alef.area == pytest.approx(mm2(AREA["א"])) and alef.centroid.x > bet.centroid.x            # read right to left: alef on the right
    assert L.runs("abc אב 12 de") == [("abc ", "ltr"), ("אב", "rtl"), (" 12 de", "ltr")]
    assert L.runs("אב 12 גד") == [(" גד", "rtl"), ("12", "ltr"), ("אב ", "rtl")]           # left to right as seen; digits left to right


def test_an_arc_a_circle_and_a_path(data):
    up = geo(data, text="H" * 10, layout="arc", bend=100)
    radius = (600 * 10 * 7 / CAP) / math.pi                                   # the line's advance (60 mm) makes a half circle
    a, b, c = (np.asarray(up["guide"][i]) for i in (0, 60, -1))
    cross = (b - a)[0] * (c - a)[1] - (b - a)[1] * (c - a)[0]
    circumradius = np.linalg.norm(a - b) * np.linalg.norm(b - c) * np.linalg.norm(c - a) / (2 * abs(cross))
    assert circumradius == pytest.approx(radius, rel=1e-3)
    assert up["letters"].area == pytest.approx(10 * mm2(AREA["H"]), rel=1e-6)                        # upright letters keep their shape
    along = sorted(up["letters"].geoms, key=lambda p: p.centroid.x)
    assert along[0].centroid.y > along[5].centroid.y + 10 < along[-1].centroid.y                     # bowed up: the ends lower (y down)
    round_ = geo(data, text="HHHH", layout="circle", radius_mm=20, start_deg=0)
    for p in round_["letters"].geoms:
        d = math.dist((p.centroid.x, p.centroid.y), (50, 40))
        assert 20 <= d <= 27.5                                                                        # standing outside the circle
    inside = geo(data, text="HHHH", layout="circle", radius_mm=20, inside=True)
    assert all(12.5 <= math.dist((p.centroid.x, p.centroid.y), (50, 40)) <= 20 for p in inside["letters"].geoms)
    top = geo(data, text="H", layout="circle", radius_mm=20, start_deg=0)["letters"].centroid
    assert top.x == pytest.approx(50, abs=1e-6) and top.y < 40 - 20                                  # the start angle 0 is at the top
    path = geo(data, text="HHHHHH", layout="path", points=[[0, 0], [20, -10], [40, 0]], letters="bent", x=20, y=60)
    curve = np.asarray(path["guide"])
    assert curve[0] == pytest.approx([20, 60]) and curve[-1] == pytest.approx([60, 60])               # the path's points are relative to (x, y)
    near = [min(math.dist((p.centroid.x, p.centroid.y), q) for q in curve) for p in path["letters"].geoms]
    assert max(near) < 7.0


def circumcentre(a, b, c):
    (ax, ay), (bx, by), (cx, cy) = a, b, c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    return ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d, \
        ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d


def angles(g, radius_from, radius_to, centre=(50, 40)):
    """The angles (radians, clockwise from the top) of the letters whose middle is between two distances from the centre, in order."""
    found = []
    for p in g["letters"].geoms:
        dx, dy = p.centroid.x - centre[0], centre[1] - p.centroid.y
        if radius_from <= math.hypot(dx, dy) <= radius_to:
            found.append(math.atan2(dx, dy))
    return sorted(found)


def test_every_line_runs_on_its_own_curve_with_its_letters_spaced_as_on_a_line(data):
    two = geo(data, text="HHHH\nHHHH", layout="circle", radius_mm=30, line_pct=100)           # a line 10 mm, an H 6 mm wide (600 units)
    first, second = angles(two, 30, 37), angles(two, 20, 27)                                      # the second line on a circle of 20 mm
    assert np.diff(first) == pytest.approx([6 / 30] * 3) and np.diff(second) == pytest.approx([6 / 20] * 3)
    assert sum(first) == pytest.approx(0, abs=1e-9) and sum(second) == pytest.approx(0, abs=1e-9)          # both centred on the start angle
    inside = geo(data, size=None, text="HHHH\nHHHH", layout="circle", radius_mm=40, inside=True, line_pct=100, spacing_mm=2)
    assert np.diff(angles(inside, 33, 40)) == pytest.approx([8 / 40] * 3)                       # hanging inside, read anticlockwise
    assert np.diff(angles(inside, 43, 50)) == pytest.approx([8 / 50] * 3)                       # the second line further out
    bent = geo(data, text="HHHH\nHHHH", layout="circle", radius_mm=30, line_pct=100, letters="bent")
    assert np.diff(angles(bent, 20, 27)) == pytest.approx([6 / 20] * 3, rel=1e-3)
    arc = geo(data, text="H" * 10 + "\nHHHH", layout="arc", bend=100, line_pct=100)
    r = 60 / math.pi                                                                              # the first line sweeps a half circle
    centre = circumcentre(*(arc["guide"][i] for i in (0, 60, -1)))
    assert np.diff(angles(arc, r, r + 7, centre)) == pytest.approx([6 / r] * 9, rel=1e-4)       # the guide's points are rounded to µm
    assert np.diff(angles(arc, r - 10, r - 3, centre)) == pytest.approx([6 / (r - 10)] * 3, rel=1e-4)   # an arc about the same centre
    # a path drawn as a half circle of 30 mm lays the lines as the circle does
    half = [[30 * math.sin(a), 30 - 30 * math.cos(a)] for a in np.linspace(-math.pi / 2, math.pi / 2, 61)]
    path = geo(data, text="HHHH\nHHHH", layout="path", points=half, x=50, y=10, line_pct=100)
    at = (50, 40)                                                                                # the path's circle about (x, y + 30)
    assert np.diff(angles(path, 30, 37, at)) == pytest.approx([6 / 30] * 3, rel=0.01)
    assert np.diff(angles(path, 20, 27, at)) == pytest.approx([6 / 20] * 3, rel=0.01)


def test_a_text_that_does_not_fit_its_circle_or_arc_is_said_so(data):
    assert not geo(data, text="HH", layout="circle", radius_mm=8)["overflow"]
    assert geo(data, text="H" * 10, layout="circle", radius_mm=8)["overflow"]                   # 60 mm around a circle of 50 mm
    assert geo(data, text="HH\nHH", layout="circle", radius_mm=8, line_pct=100)["overflow"]   # the second line past the centre
    assert geo(data, text="HHHHHHH\nHHHHHH", layout="circle", radius_mm=14, line_pct=100)["overflow"]   # 36 mm on a circle of 25
    assert not geo(data, text="HH", layout="circle", radius_mm=8, inside=True)["overflow"]
    assert geo(data, text="HH", layout="circle", radius_mm=6, inside=True)["overflow"]          # letters 7 mm high inside 6 mm
    assert geo(data, text="H" * 10 + "\n" + "H" * 10 + "\nH", layout="arc", bend=100, line_pct=100)["overflow"]
    assert not geo(data, text="H" * 10, layout="arc", bend=100)["overflow"]
    assert not geo(data, text="HH\nHH", layout="path", points=[[0, 0], [10, 0]], line_pct=100)["overflow"]


def test_a_backing_on_a_curve_holds_every_line(data):
    for spec in ({"layout": "circle", "radius_mm": 30}, {"layout": "circle", "radius_mm": 25, "inside": True}, {"layout": "arc", "bend": 40}):
        g = geo(data, text="HHHH\nHHHHHH", line_pct=100, backing="rect", padding_mm=1, backing_entry_id="e1", **spec)
        assert not g["overflow"] and g["backing"].area > 0 and g["cut"].buffer(-0.3).buffer(0.01).contains(g["letters"])     # the backing (the cut less the gap)


def test_the_cut_the_gap_and_the_backing(data):
    bare = geo(data, text="H", gap_mm=0)
    assert bare["cut"].area == pytest.approx(bare["letters"].area) and bare["backing"] is None
    gap = geo(data, text="H", gap_mm=0.5)
    assert gap["cut"].area > gap["letters"].area and gap["cut"].contains(gap["letters"])
    x0, y0, x1, y1 = gap["letters"].bounds
    rect = geo(data, text="H", gap_mm=0.5, backing="rect", padding_mm=2, backing_entry_id="e1")
    assert rect["backing"].area == pytest.approx((x1 - x0 + 4) * (y1 - y0 + 4) - gap["cut"].area, rel=1e-3)
    assert rect["cut"].area > (x1 - x0 + 4) * (y1 - y0 + 4)                                          # the backing and its gap are cut out
    clean = geo(data, text="H", gap_mm=0.5, backing="rect", padding_mm=2)                            # a backing without colour: clean titanium
    assert clean["backing"] is None and clean["cut"].area == pytest.approx((x1 - x0 + 4) * (y1 - y0 + 4))
    oval = geo(data, text="HH", backing="oval", padding_mm=1, backing_entry_id="e1")
    assert oval["backing"].area > 0 and oval["cut"].contains(oval["letters"])
    outline = geo(data, text="H", backing="outline", padding_mm=1, backing_entry_id="e1", gap_mm=0.3)
    assert outline["backing"].area == pytest.approx(outline["letters"].buffer(1).area - outline["letters"].buffer(0.3).area, rel=0.02)


def test_an_inscription_beyond_the_work_is_clipped_and_said_so(data):
    inside = geo(data, text="HHH", x=50)
    edge = geo(data, text="HHH", x=98)
    assert not inside["clipped"] and edge["clipped"] and edge["letters"].area < inside["letters"].area
    assert edge["letters"].bounds[2] <= 100 + 1e-9
    free = geo(data, size=None, text="HHH", x=98)
    assert not free["clipped"] and free["letters"].area == pytest.approx(inside["letters"].area)


def test_an_inscription_is_checked(data):
    ok = L.checked({"text": "a\r\nb"})
    assert ok["text"] == "a\nb" and ok["gap_mm"] == 0.3 and ok["layout"] == "line" and ok["offset_pct"] == 50
    for spec, message in (({"colour": 1}, "an inscription has no field 'colour'"),
                          ({"height_mm": 0}, "the letter height (mm) of an inscription must be a number from 0.3 to 500"),
                          ({"bend": 120}, "the bend (%) of an inscription must be a number from -100 to 100"),
                          ({"layout": "spiral"}, "the layout of an inscription must be one of line, arc, circle, path"),
                          ({"layout": "path", "points": [[0, 0]]}, "draw the path of the inscription: two points or more"),
                          ({"points": [[0, "x"]]}, "every point of the path of an inscription must be two numbers (mm)"),
                          ({"text": 5}, "the text of an inscription must be text"),
                          ({"inside": "yes"}, "the switch «inside the circle» of an inscription must be true or false"),
                          ({"entry_id": 3}, "the colour of an inscription must be a measured colour"),
                          ({"font": {"face": 1}}, "choose the font of the inscription")):
        with pytest.raises(su.ValidationError) as caught:
            L.checked(spec)
        assert str(caught.value) == message


def test_the_operations_of_a_works_list(data):
    ok = lambda entry: entry in ("e1", "e2")              # noqa: E731
    texts = L.operate(data, [], {"op": "text_add", "text": {"text": "HH"}}, WORK, ok, lambda: "e1")
    assert [t["id"] for t in texts] == ["t1"] and texts[0]["x"] == 50 and texts[0]["y"] == 40 and texts[0]["entry_id"] == "e1"
    assert texts[0]["height_mm"] == 8.0 and texts[0]["font"]["family"] in ("Test Sans", "Other Serif")   # a tenth of the shorter side
    texts = L.operate(data, texts, {"op": "text_copy", "id": "t1"}, WORK, ok, lambda: "e1")
    assert [t["id"] for t in texts] == ["t1", "t2"] and texts[1]["x"] == 53
    texts = L.operate(data, texts, {"op": "text_set", "id": "t2", "changes": {"text": "П", "entry_id": "e2"}}, WORK, ok, lambda: "e1")
    assert texts[1]["text"] == "П" and texts[1]["entry_id"] == "e2"
    with pytest.raises(su.ValidationError, match="measured colour of this laser"):
        L.operate(data, texts, {"op": "text_set", "id": "t2", "changes": {"entry_id": "e9"}}, WORK, ok, lambda: "e1")
    with pytest.raises(su.ValidationError, match="is not on this computer any more"):
        L.operate(data, texts, {"op": "text_set", "id": "t2", "changes": {"font": {"face": "x", "family": "Gone", "style": "Regular"}}},
                  WORK, ok, lambda: "e1")
    texts = L.operate(data, texts, {"op": "text_delete", "id": "t1"}, WORK, ok, lambda: "e1")
    assert [t["id"] for t in texts] == ["t2"]
    assert L.operate(data, texts, {"op": "text_add"}, WORK, ok, lambda: "e1")[-1]["id"] == "t3"       # a name is never given twice


def test_a_moved_font_is_found_by_its_family_and_style(data):
    known = face(data, style="Bold")
    assert L.checked({"font": known})["font"] == known
    moved = fonts.resolve(data, {**known, "face": "0000"})
    assert (moved["family"], moved["style"]) == ("Test Sans", "Bold")
    other = fonts.resolve(data, {"face": "0000", "family": "Test Sans", "style": "Light"})            # the style is gone: the regular one
    assert other["style"] == "Regular"


def test_the_font_window_draws_the_text_and_the_missing_letters_red(data):
    svg = L.preview_svg(data, face(data)["face"], "HО")
    assert svg.startswith("<svg") and 'fill="#1f1f1f"' in svg and 'fill="#d32f2f"' in svg
    assert 'fill="#d32f2f"' not in L.preview_svg(data, face(data)["face"], "HП")


def test_the_mask_of_a_shape_on_a_picture(data):
    g = geo(data, text="H", height_mm=7, gap_mm=0)
    mask = L.mask(g["letters"], {"x": 0, "y": 0}, 10, (1000, 800))
    assert mask.sum() / 100 == pytest.approx(g["letters"].area, rel=0.01)
    cover = L.coverage(g["letters"], {"x": 0, "y": 0}, 10, (1000, 800))
    assert cover.sum() / 100 == pytest.approx(g["letters"].area, rel=0.01)
