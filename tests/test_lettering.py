"""The geometry of an inscription (feature inscriptions-in-works, REQ-002, DEC-003): a text set in a font at a letter height, laid out
straight, on an arc, around a circle or along a path, turned and placed, with the gap and the backing it cuts into a picture. Measured on
the test font of ``font_kit``, whose letters are rectangles of known area (cap height 700 of 1000 units)."""
import math
import re

import numpy as np
import pytest
import shapely
from shapely import affinity
from shapely.geometry import Polygon

from font_kit import AREA, CAP, KERN, make_font, make_shaping_font
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


def test_neighbouring_letters_that_overlap_are_one_shape_engraved_once(data):
    """inscriptions-in-works REQ-002 c6: letters that overlap, side by side (a negative spacing) or one line over the next (a line spacing
    under the letter height), are one closed shape whose area counts their common part once."""
    # an H is drawn 0.5..5.5 mm of its 6 mm advance: 2 mm less spacing lays the second one's left stem on the first one's right stem
    side = geo(data, size=None, text="HH", spacing_mm=-2)["letters"]
    assert len(side.geoms) == 1 and side.area == pytest.approx(2 * mm2(AREA["H"]) - 1 * 7)          # the shared stem, 1 x 7 mm, once
    # a line 10 mm at 50 %: the lower H's stems reach 2 mm into the upper one's
    lines = geo(data, size=None, text="H\nH", line_pct=50)["letters"]
    assert len(lines.geoms) == 1 and lines.area == pytest.approx(2 * mm2(AREA["H"]) - 2 * 1 * 2)
    assert all(ring.is_closed for p in (side.geoms[0], lines.geoms[0]) for ring in (p.exterior, *p.interiors))
    apart = geo(data, size=None, text="HH")["letters"]
    assert len(apart.geoms) == 2 and apart.area == pytest.approx(2 * mm2(AREA["H"]))                # apart, each one its own shape


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


def test_alignment_and_line_spacing_change_the_outline_as_named(data):
    def lines(**spec):
        letters = sorted(geo(data, text="HHH\nH", **spec)["letters"].geoms, key=lambda p: p.centroid.y)
        return letters[:3], letters[3]                                   # the first line above (y down), then the second
    for align, edge in (("left", lambda b: b[0]), ("right", lambda b: b[2]), ("center", lambda b: (b[0] + b[2]) / 2)):
        first, second = lines(align=align)
        assert edge(second.bounds) == pytest.approx(edge(shapely.union_all(first).bounds)), align
    assert lines(align="left")[1].bounds[0] < lines(align="center")[1].bounds[0] < lines(align="right")[1].bounds[0]
    for pct in (50, 100, 150):                                           # a line is 1000 units: 10 mm at 7 mm capitals, times line_pct
        letters = geo(data, text="H\nH", line_pct=pct)["letters"]
        assert letters.bounds[3] - letters.bounds[1] == pytest.approx(10 * pct / 100 + 7), pct


def test_a_negative_bend_bends_the_other_way_and_the_offset_moves_the_text_along_its_path(data):
    def sag(bend):                                                      # how much lower (y down) the baseline's ends are than its middle
        guide = np.asarray(geo(data, text="H" * 10, layout="arc", bend=bend)["guide"])
        return (guide[0][1] + guide[-1][1]) / 2 - guide[len(guide) // 2][1]
    # the line's 60 mm make a half circle at 100 %; the guide runs a tenth of the line further at each end: 0.6 π each side of the middle
    half = 60 / math.pi * (1 - math.cos(0.6 * math.pi))
    assert sag(100) == pytest.approx(half, rel=1e-3) and sag(-100) == pytest.approx(-half, rel=1e-3)           # bowed up, bowed down
    assert sag(-40) == pytest.approx(-sag(40)) and 0 < sag(40) < sag(100)
    for pct, x in ((0, 20), (25, 35), (50, 50), (100, 80)):                                    # a straight path of 60 mm from x = 20
        letter = geo(data, text="H", layout="path", points=[[0, 0], [60, 0]], x=20, y=60, offset_pct=pct)["letters"]
        assert letter.centroid.x == pytest.approx(x) and letter.centroid.y == pytest.approx(60 - 3.5), pct    # the text's middle there


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


def shaped(data, text, **spec):
    """The text in the shaping font of ``font_kit`` (its kerning pair H O, its ligature HH and two Arabic letters), nothing clipped."""
    make_shaping_font(fonts.own_dir(data) / "Shaping.ttf")
    return L.geometry(data, L.checked({"font": face(data, "Shaping Sans"), "x": 50, "y": 40, "height_mm": 7, "text": text, **spec}), None)


def test_the_kerning_and_the_ligatures_of_the_font_are_applied(data):
    """inscriptions-in-works REQ-002 c2: the text is shaped with the font's kerning (GPOS kern) and ligatures (GSUB liga)."""
    width = lambda g: g["letters"].bounds[2] - g["letters"].bounds[0]          # noqa: E731
    # an H is drawn 50..550 of its 600 units, an O 50..650 of its 700: «OH» spans 1200 units, 12 mm at capitals of 7 mm (100 units a mm)
    assert width(shaped(data, "OH")) == pytest.approx(12.0)                                           # no pair O H: as the advances lay them
    assert width(shaped(data, "HO")) == pytest.approx(12.0 + KERN / 100)                              # the pair H O kerned 0.5 mm closer
    assert width(geo(data, size=None, text="HO")) == pytest.approx(12.0)                              # a font without that pair: not closer
    assert width(shaped(data, "HO", width_pct=200)) == pytest.approx(2 * (12.0 + KERN / 100))         # the kerning stretched with the width
    pair = shaped(data, "HH")["letters"]                                                              # HH is the font's ligature H_H
    assert len(pair.geoms) == 1 and pair.area == pytest.approx(mm2(AREA["H_H"])) and pair.bounds[2] - pair.bounds[0] == pytest.approx(11.0)
    three = shaped(data, "HHH")
    assert three["letters"].area == pytest.approx(mm2(AREA["H_H"] + AREA["H"])) and three["missing"] == []      # the ligature, then an H
    assert geo(data, size=None, text="HH")["letters"].area == pytest.approx(2 * mm2(AREA["H"]))       # without the ligature: two Hs


def test_arabic_is_written_right_to_left_and_a_line_of_both_directions_keeps_each_run_in_its_own(data):
    """inscriptions-in-works REQ-002 c2: Arabic, like Hebrew, is set right to left; a Latin run inside it stays left to right."""
    arabic = shaped(data, "اب")["letters"].geoms                                          # alef typed first, then beh
    alef, beh = max(arabic, key=lambda p: p.area), min(arabic, key=lambda p: p.area)
    assert (alef.area, beh.area) == (pytest.approx(mm2(AREA["ا"])), pytest.approx(mm2(AREA["ب"])))
    assert alef.centroid.x > beh.centroid.x                                                         # the first letter typed on the right
    letter = {AREA["O"]: "O", AREA["H"]: "H", AREA["ا"]: "alef", AREA["ب"]: "beh"}

    def seen(text):                                                                                  # the letters from left to right
        found = sorted(shaped(data, text)["letters"].geoms, key=lambda p: p.centroid.x)
        return [letter[round(p.area / mm2(1))] for p in found]
    assert L.runs("OH اب") == [("OH ", "ltr"), ("اب", "rtl")]
    assert seen("OH اب") == ["O", "H", "beh", "alef"]                                              # a Latin line, then the Arabic run
    assert L.runs("اب HO") == [("HO", "ltr"), ("اب ", "rtl")]
    assert seen("اب HO") == ["H", "O", "beh", "alef"]                                              # an Arabic line: the Latin run on its left


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


def headings(points) -> np.ndarray:
    """The direction (radians) of every step of a polyline, unwrapped."""
    steps = np.diff(np.asarray(points, np.float64), axis=0)
    return np.unwrap(np.arctan2(steps[:, 1], steps[:, 0]))


def test_a_path_is_a_smooth_curve_through_the_operators_points(data):
    """inscriptions-in-works REQ-002 c4: the path runs through every point the operator placed, smooth: it bends a little at every step
    instead of turning at the points as the line through them does."""
    clicked = [[0, 0], [20, -10], [40, 0], [60, 10]]
    guide = np.asarray(geo(data, text="H", layout="path", points=clicked, x=20, y=60)["guide"])
    for px, py in clicked:
        assert min(math.dist(q, (20 + px, 60 + py)) for q in guide) < 1e-3                  # through each point (the guide is rounded to µm)
    assert np.degrees(np.abs(np.diff(headings(clicked)))).max() > 50                          # the line through the points turns 53° at once
    assert np.degrees(np.abs(np.diff(headings(guide)))).max() < 2.5                            # the curve: no corner, a little at every step
    assert np.hypot(*np.diff(guide, axis=0).T).max() < 0.3                                     # in steps of a quarter of a millimetre


def straight_h(data):
    return geo(data, size=None, text="H")["letters"]


def turned_back(letter, up):
    """``letter`` turned about its middle so that ``up`` (a unit vector in the work, y down) points up again."""
    phi = math.atan2(up[1], up[0]) - math.atan2(-1.0, 0.0)
    return affinity.rotate(letter, -phi, origin=(letter.centroid.x, letter.centroid.y), use_radians=True)


def test_an_upright_letter_on_a_curve_is_turned_to_it_at_its_middle_and_keeps_its_shape(data):
    """inscriptions-in-works REQ-002 c5: an upright letter is the straight letter turned so that it stands square on the curve where its
    middle is: on a circle and on a path drawn as a half circle its up is the radius through its middle, its foot on the curve."""
    h = straight_h(data)
    mid = h.centroid
    laid = {"circle": (geo(data, size=None, text="HHHH", layout="circle", radius_mm=20, start_deg=0), (50, 40), 20, 1e-9),
            "path": (geo(data, size=None, text="HHHH", layout="path", x=50, y=10,
                         points=[[30 * math.sin(a), 30 - 30 * math.cos(a)] for a in np.linspace(-math.pi / 2, math.pi / 2, 61)]), (50, 40), 30, 1e-3)}
    for name, (g, centre, radius, tol) in laid.items():
        assert len(g["letters"].geoms) == 4, name
        for letter in g["letters"].geoms:
            out = np.array([letter.centroid.x - centre[0], letter.centroid.y - centre[1]])
            assert np.linalg.norm(out) == pytest.approx(radius + 3.5, abs=1e-3), name                 # its foot on the curve, 3.5 mm under its middle
            back = turned_back(letter, out / np.linalg.norm(out))
            straight = affinity.translate(h, letter.centroid.x - mid.x, letter.centroid.y - mid.y)
            assert back.symmetric_difference(straight).area < tol * straight.area, name                 # the straight letter, only turned


def test_every_point_of_a_bent_letter_follows_the_curve(data):
    """inscriptions-in-works REQ-002 c5: a letter bent with a circle is the straight text with every point carried onto the circle: its
    length along the line becomes the length along the circle and its height the distance outside it. Unbent (each point of the outline
    read back as its angle times the radius and its distance from the circle), the bent text is the straight one."""
    radius, centre = 20.0, (50.0, 40.0)
    bent = geo(data, size=None, text="HHHH", layout="circle", radius_mm=radius, start_deg=0, letters="bent")["letters"]

    def unbent(ring):
        p = np.asarray(ring.coords)
        dx, dy = p[:, 0] - centre[0], p[:, 1] - centre[1]
        return np.column_stack([radius * np.arctan2(dx, -dy), radius - np.hypot(dx, dy)])     # along the circle from the top; y down
    flat = shapely.union_all([Polygon(unbent(p.exterior), [unbent(r) for r in p.interiors]) for p in bent.geoms])
    line = geo(data, size=None, text="HHHH", x=0, y=-3.5)["letters"]                           # the same text straight, its baseline at y 0
    assert flat.bounds == pytest.approx((-11.5, -7.0, 11.5, 0.0), abs=1e-6)                    # centred on the start angle, on the circle
    assert flat.symmetric_difference(line).area < 1e-6 * line.area
    assert bent.area > line.area * 1.1                                                        # bent outside the circle: wider at the top
    upright = geo(data, size=None, text="HHHH", layout="circle", radius_mm=radius, start_deg=0)["letters"]
    assert upright.area == pytest.approx(line.area)                                            # upright letters are not bent: as straight


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


def test_letters_that_crowd_on_a_tight_bend_of_a_path_are_named_by_their_line(data):
    # an H is 5 mm wide in a 6 mm advance and 7 mm tall: upright on the inside of a bend of radius R their tops meet below R ≈ 42 mm
    valley = [[10 * math.sin(a), 10 * math.cos(a) - 10] for a in np.linspace(-math.pi / 2, math.pi / 2, 31)]     # a U of 10 mm (y down)
    assert geo(data, text="HHHHHH", layout="path", points=valley)["crowded"] == [1]
    # bent, a letter is narrower at its top on the inside of a bend but stays apart from its neighbours until its top passes the centre
    assert geo(data, text="HHHHHH", layout="path", points=valley, letters="bent")["crowded"] == []
    tight = [[5 * math.sin(a), 5 * math.cos(a) - 5] for a in np.linspace(-math.pi / 2, math.pi / 2, 31)]
    assert geo(data, text="HHHHHH", layout="path", points=tight, letters="bent")["crowded"] == [1]       # 7 mm letters in a U of 5 mm
    hill = [[30 * math.sin(a), 30 - 30 * math.cos(a)] for a in np.linspace(-math.pi / 2, math.pi / 2, 61)]
    assert geo(data, text="HHHHHH", layout="path", points=hill)["crowded"] == []                           # on the outside they spread
    wide = [[100 * math.sin(a), 100 * math.cos(a) - 100] for a in np.linspace(-0.4, 0.4, 31)]
    assert geo(data, text="HHHHHH", layout="path", points=wide)["crowded"] == []                           # a gentle bend leaves them apart
    # 3 mm letters: the second line runs 4.3 mm under the first, so on a hill of 3 mm it passes the centre and its letters pile up where
    # the run stops; the first line stands free on the outside
    small_hill = [[3 * math.sin(a), 3 - 3 * math.cos(a)] for a in np.linspace(-math.pi / 2, math.pi / 2, 31)]
    assert geo(data, text="HH\nHHHH", layout="path", points=small_hill, height_mm=3, line_pct=100)["crowded"] == [2]
    # letters that overlap on a straight line already (a negative spacing) are the font's look, not a crowd
    assert geo(data, text="HHHHHH", layout="path", points=[[0, 0], [40, 0]], spacing_mm=-2)["crowded"] == []
    assert geo(data, text="HHHHHH", layout="circle", radius_mm=8)["crowded"] == []                       # a circle says «overflow» instead
    assert L.shown(geo(data, text="HHHHHH", layout="path", points=valley))["crowded"] == [1]


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


def test_a_new_inscription_takes_the_font_of_the_inscription_changed_last(data):
    ok = lambda entry: True                               # noqa: E731
    run = lambda texts, op, earlier=(): L.operate(data, texts, op, WORK, ok, lambda: "e1", earlier)     # noqa: E731
    font = lambda texts, earlier=(): run(texts, {"op": "text_add"}, earlier)[-1]["font"]              # noqa: E731
    serif, bold = face(data, family="Other Serif"), face(data, style="Bold")
    default = fonts.described(L.default_face(data))
    assert font([]) == default                                                                       # the first one of a work
    one = run([], {"op": "text_add", "text": {"font": serif}})
    two = run(one, {"op": "text_add", "text": {"font": bold}})
    assert font(two) == bold                                                                         # no step kept: the newest one's
    moved = run(two, {"op": "text_set", "id": "t1", "changes": {"x": 10}})
    undo = [one, two]                                                                                # the lists before each change
    assert font(moved, undo) == serif                                                                # t1 was moved last, t2 is newer
    assert font(moved, undo + [moved]) == serif                                                      # a step that left them as they were
    gone = run(moved, {"op": "text_delete", "id": "t1"})
    assert font(gone, undo + [moved]) == bold                                                        # the one changed last is gone
    assert run(moved, {"op": "text_add", "text": {"font": bold}}, undo)[-1]["font"] == bold          # a font given is the font
    missing = [{**one[0], "font": {"face": "x", "family": "Gone", "style": "Regular"}}]
    assert font(missing) == default                                                                  # a font no more on this computer


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


def test_the_font_window_draws_the_outline_the_file_gets_and_the_sample_while_the_text_is_empty(data):
    """inscriptions-in-works REQ-001 c4: the text drawn in the font window is the outline of the letters the file gets (the geometry the
    work cuts and engraves), filled as fonts are (non-zero), point for point; an empty text shows the sample."""
    svg = L.preview_svg(data, face(data)["face"], "HOП", height_mm=10)
    d = re.search(r'<path fill="#1f1f1f" fill-rule="nonzero" d="([^"]*)"/>', svg).group(1)
    rings = [np.array(re.findall(r"[ML]([-\d.]+) ([-\d.]+)", part), np.float64) for part in d.split("Z") if part.strip()]
    lo, hi = np.vstack(rings).min(axis=0), np.vstack(rings).max(axis=0)
    xs, ys = (a.ravel() for a in np.meshgrid(np.arange(lo[0] - 0.3, hi[0] + 0.3, 0.0173), np.arange(lo[1] - 0.3, hi[1] + 0.3, 0.0173)))
    winding = np.zeros(xs.size, int)
    for ring in rings:                                     # each contour adds its turn (+1 or -1) to the points inside it
        turn = 1 if np.dot(ring[:, 0], np.roll(ring[:, 1], -1)) > np.dot(ring[:, 1], np.roll(ring[:, 0], -1)) else -1
        winding += turn * shapely.contains_xy(Polygon(ring), xs, ys)
    letters = geo(data, size=None, text="HOП", height_mm=10)["letters"]
    x0, y0, x1, y1 = letters.bounds
    dx, dy = (x0 + x1 - lo[0] - hi[0]) / 2, (y0 + y1 - lo[1] - hi[1]) / 2               # the window's drawing laid on the work's
    drawn, engraved = winding != 0, shapely.contains_xy(letters, xs + dx, ys + dy)
    assert drawn.sum() > 100_000 and (drawn != engraved).sum() == 0
    assert drawn.sum() * 0.0173 ** 2 == pytest.approx(mm2(AREA["H"] + AREA["O"] + AREA["П"], height=10), rel=0.01)
    sample = L.preview_svg(data, face(data)["face"], L.SAMPLE)
    assert L.preview_svg(data, face(data)["face"], "") == sample and L.preview_svg(data, face(data)["face"], None) == sample


def test_the_mask_of_a_shape_on_a_picture(data):
    g = geo(data, text="H", height_mm=7, gap_mm=0)
    mask = L.mask(g["letters"], {"x": 0, "y": 0}, 10, (1000, 800))
    assert mask.sum() / 100 == pytest.approx(g["letters"].area, rel=0.01)
    cover = L.coverage(g["letters"], {"x": 0, "y": 0}, 10, (1000, 800))
    assert cover.sum() / 100 == pytest.approx(g["letters"].area, rel=0.01)
