"""The library of shapes, frames and icons of a titanium business card (feature-2, S1): configurable items that become shapely geometry in
millimetres (y down, centred on the origin, filling their box), validated parameters and the listing a picker draws its thumbnails from."""
import json
import math
import re

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from titanium_platform import card_library as lib, setup as su

ITEMS = [(group, name) for group in lib.GROUPS for name in lib._GROUP[group]]
IDS = [f"{group}-{name}" for group, name in ITEMS]
SHAPE_NAMES = {"rectangle", "rounded_rectangle", "ellipse", "triangle", "diamond", "polygon", "star", "line", "arrow"}
FRAME_NAMES = {"single", "double", "rounded", "chamfered", "notched", "dashed"}
ICON_NAMES = {"phone", "mail", "globe", "pin", "clock", "star", "heart", "check", "cross", "arrow_right", "home", "user", "briefcase", "camera",
              "leaf", "sun", "moon", "key", "lock", "bolt", "book", "cup", "wrench", "bell", "gear", "tree", "anchor"}
LINE_ONLY_ICONS = {"check", "cross", "arrow_right"}               # open lines only: filling them changes nothing
SIZES = [(33.5, 21.25), (5.0, 9.0), (0.6, 0.6), (200.0, 120.0), (500.0, 500.0)]


def has(group, name, param):
    return any(spec["name"] == param for spec in lib._GROUP[group][name]["params"])


def box_of(group, name, width, height, params=None):
    """The box a geometry is expected to fill: a line is only as thick as its stroke."""
    if (group, name) == ("shape", "line"):
        return width, min(lib.checked(group, name, params)["stroke_mm"], height)
    return width, height


def area(group, name, width, height, **params):
    return lib.geometry(group, name, width, height, params).area


def within(geom, width, height, tol=1e-6):
    x0, y0, x1, y1 = geom.bounds
    return x0 >= -width / 2 - tol and x1 <= width / 2 + tol and y0 >= -height / 2 - tol and y1 <= height / 2 + tol


def test_the_library_has_what_the_card_needs():
    assert lib.GROUPS == ("shape", "frame", "icon")
    assert SHAPE_NAMES <= set(lib.SHAPES) and FRAME_NAMES <= set(lib.FRAMES) and ICON_NAMES <= set(lib.ICONS)
    assert len(lib.SHAPES) >= 8 and len(lib.FRAMES) >= 6 and len(lib.ICONS) >= 24
    assert list(lib.SHAPES)[:2] == ["rectangle", "rounded_rectangle"]                  # the dicts keep their order


@pytest.mark.parametrize("group,name", ITEMS, ids=IDS)
def test_every_parameter_spec_is_complete_and_its_default_passes(group, name):
    item = lib._GROUP[group][name]
    assert isinstance(item["label"], str) and item["label"] and set(item) == {"label", "params"}
    names = [spec["name"] for spec in item["params"]]
    assert len(names) == len(set(names))
    for spec in item["params"]:
        assert set(spec) == {"name", "label", "type", "min", "max", "default", "unit"}
        assert spec["type"] in ("number", "int", "bool") and isinstance(spec["label"], str) and isinstance(spec["unit"], str)
        if spec["type"] == "bool":
            assert spec["min"] is None and spec["max"] is None and isinstance(spec["default"], bool)
        else:
            assert spec["min"] <= spec["default"] <= spec["max"]
        if spec["type"] == "int":
            assert isinstance(spec["default"], int)
    assert lib.checked(group, name) == {spec["name"]: spec["default"] for spec in item["params"]}
    if group != "frame" and name != "line":
        assert has(group, name, "filled") and has(group, name, "stroke_mm")
    if group == "frame" or name == "line":
        assert has(group, name, "stroke_mm") and not has(group, name, "filled")


def test_the_parameters_the_brief_names_exist_with_their_ranges():
    spec = lambda group, name, param: next(s for s in lib._GROUP[group][name]["params"] if s["name"] == param)      # noqa: E731
    assert (spec("shape", "star", "points")["min"], spec("shape", "star", "points")["max"]) == (3, 12)
    assert (spec("shape", "star", "inner_pct")["min"], spec("shape", "star", "inner_pct")["max"], spec("shape", "star", "inner_pct")["unit"]) == (15, 90, "%")
    assert (spec("shape", "polygon", "sides")["min"], spec("shape", "polygon", "sides")["max"]) == (3, 12)
    assert (spec("shape", "rectangle", "stroke_mm")["min"], spec("shape", "rectangle", "stroke_mm")["max"],
            spec("shape", "rectangle", "stroke_mm")["default"]) == (0.05, 3, 0.3)
    assert spec("shape", "rectangle", "filled")["default"] is False
    assert has("shape", "rounded_rectangle", "corner_mm") and has("frame", "double", "gap_mm") and has("frame", "rounded", "corner_mm")
    assert has("frame", "chamfered", "corner_mm") and has("frame", "notched", "corner_mm")
    assert has("frame", "dashed", "dash_mm") and has("frame", "dashed", "gap_mm")


# -- default sizes ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("group,name", ITEMS, ids=IDS)
def test_default_sizes_are_in_range_and_suit_a_card(group, name):
    size = lib.default_size(group, name)
    assert set(size) == {"width", "height"}
    assert lib.MIN_SIZE_MM <= size["width"] <= 85 and lib.MIN_SIZE_MM <= size["height"] <= 53


def test_default_sizes_are_what_the_brief_asks_for():
    assert lib.default_size("icon", "phone") == {"width": 8.0, "height": 8.0}
    assert lib.default_size("shape", "line") == {"width": 20.0, "height": 0.3}
    assert lib.default_size("shape", "rectangle") == {"width": 20.0, "height": 12.0}
    assert lib.default_size("frame", "single") == {"width": 80.0, "height": 49.0}


# -- every item builds ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("group,name", ITEMS, ids=IDS)
def test_every_item_builds_at_its_default_size_and_at_others(group, name):
    default = lib.default_size(group, name)
    for width, height in [(default["width"], default["height"]), *SIZES]:
        geom = lib.geometry(group, name, width, height)
        assert isinstance(geom, (Polygon, MultiPolygon)) and geom.is_valid and not geom.is_empty
        assert within(geom, width, height), (width, height, geom.bounds)
        assert lib.vertices(geom) <= lib.MAX_VERTICES
        if group != "icon":                                                                      # centred on the origin
            x0, y0, x1, y1 = geom.bounds
            assert (x0, y0) == pytest.approx((-x1, -y1), abs=1e-6)


@pytest.mark.parametrize("group,name", [item for item in ITEMS if item[0] != "icon"], ids=[i for i, item in zip(IDS, ITEMS) if item[0] != "icon"])
def test_shapes_and_frames_fill_their_box(group, name):
    for width, height in [tuple(lib.default_size(group, name).values()), *SIZES]:
        w, h = box_of(group, name, width, height)
        x0, y0, x1, y1 = lib.geometry(group, name, width, height).bounds
        assert (x0, y0, x1, y1) == pytest.approx((-w / 2, -h / 2, w / 2, h / 2), abs=1e-6), (width, height)


@pytest.mark.parametrize("name", sorted(lib.ICONS))
def test_an_icon_is_a_square_pictogram_in_the_middle_of_its_box(name):
    x0, y0, x1, y1 = lib.geometry("icon", name, 10.0, 10.0).bounds
    assert max(x1 - x0, y1 - y0) >= 9.0 and max(x1 - x0, y1 - y0) <= 10.0 + 1e-6
    wide = lib.geometry("icon", name, 30.0, 10.0)                  # the aspect is kept: the same pictogram in the middle of a wide box
    assert wide.equals(lib.geometry("icon", name, 10.0, 10.0))
    assert lib.geometry("icon", name, 10.0, 30.0).equals(wide)


@pytest.mark.parametrize("name", sorted(lib.ICONS))
def test_an_icon_stays_inside_its_box_at_any_line_width_and_size(name):
    for stroke in (0.05, 0.3, 1.0, 3.0):
        for width, height in ((8.0, 8.0), (30.0, 10.0), (0.5, 0.5), (4.0, 12.0), (500.0, 500.0)):
            for filled in (False, True):
                geom = lib.geometry("icon", name, width, height, {"stroke_mm": stroke, "filled": filled})
                assert geom.is_valid and not geom.is_empty and within(geom, width, height), (stroke, width, height, filled)


def test_the_line_width_of_an_icon_is_not_scaled_with_its_size():
    for size in (10.0, 40.0, 100.0):
        geom = lib.geometry("icon", "check", size, size, {"stroke_mm": 0.5})
        assert not geom.buffer(-0.8 * 0.25).is_empty            # the line is 0.5 mm wide at every size ...
        assert geom.buffer(-1.5 * 0.25).is_empty                # ... and not wider
    wide = lib.geometry("icon", "check", 40.0, 40.0, {"stroke_mm": 2.0})
    assert not wide.buffer(-0.8).is_empty and wide.buffer(-1.5).is_empty


# -- the stroke and the fill ---------------------------------------------------------------------------------------------------------
def outlined(group, name):
    """Parameters of an item drawn with a line, and the size that holds the widest line."""
    size = {"shape": (60.0, 40.0), "frame": (80.0, 49.0), "icon": (24.0, 24.0)}[group]
    if (group, name) == ("shape", "line"):
        size = (60.0, 3.0)
    return size, ({"filled": False} if has(group, name, "filled") else {})


@pytest.mark.parametrize("group,name", ITEMS, ids=IDS)
def test_a_wider_line_covers_more_area(group, name):
    (width, height), params = outlined(group, name)
    areas = [area(group, name, width, height, **params, stroke_mm=s) for s in (0.1, 0.3, 0.6, 1.0, 2.0)]
    assert all(b > a for a, b in zip(areas, areas[1:])), areas


@pytest.mark.parametrize("name", sorted(set(lib.SHAPES) - {"line"}))
def test_a_filled_shape_ignores_the_line_width_and_covers_more_than_its_outline(name):
    base = area("shape", name, 40.0, 30.0, filled=True, stroke_mm=0.3)
    assert area("shape", name, 40.0, 30.0, filled=True, stroke_mm=2.5) == pytest.approx(base, rel=1e-12)
    for stroke in (0.1, 0.3, 1.0, 2.5):
        assert base > area("shape", name, 40.0, 30.0, filled=False, stroke_mm=stroke)


@pytest.mark.parametrize("name", sorted(lib.ICONS))
def test_a_filled_icon_covers_more_than_its_outline(name):
    outline = area("icon", name, 24.0, 24.0, filled=False, stroke_mm=0.4)
    solid = area("icon", name, 24.0, 24.0, filled=True, stroke_mm=0.4)
    if name in LINE_ONLY_ICONS:
        assert solid == pytest.approx(outline, rel=1e-9)
    else:
        assert solid > outline * 1.05


def test_the_areas_of_the_plain_shapes_are_exact():
    assert area("shape", "rectangle", 20, 12, filled=True) == pytest.approx(240)
    assert area("shape", "rectangle", 20, 12, filled=False, stroke_mm=1.0) == pytest.approx(20 * 12 - 18 * 10)
    assert area("shape", "triangle", 16, 14, filled=True) == pytest.approx(0.5 * 16 * 14)
    assert area("shape", "diamond", 16, 14, filled=True) == pytest.approx(0.5 * 16 * 14)
    assert area("shape", "ellipse", 20, 12, filled=True) == pytest.approx(math.pi * 10 * 6, rel=2e-3)
    assert area("shape", "rounded_rectangle", 20, 12, filled=True, corner_mm=3) == pytest.approx(240 - (4 - math.pi) * 9, rel=2e-3)
    assert area("shape", "arrow", 20, 10, filled=True) == pytest.approx(4 * 12 + 0.5 * 8 * 10)      # the shaft and the head
    assert area("frame", "single", 80, 49, stroke_mm=0.3) == pytest.approx(80 * 49 - 79.4 * 48.4)


def test_a_line_is_as_thick_as_its_stroke_but_never_thicker_than_its_box():
    assert lib.geometry("shape", "line", 20.0, 0.3).bounds == pytest.approx((-10, -0.15, 10, 0.15))
    assert lib.geometry("shape", "line", 20.0, 5.0, {"stroke_mm": 1.0}).bounds == pytest.approx((-10, -0.5, 10, 0.5))
    assert lib.geometry("shape", "line", 20.0, 0.2, {"stroke_mm": 1.0}).bounds == pytest.approx((-10, -0.1, 10, 0.1))


# -- parameters change the drawing -----------------------------------------------------------------------------------------------------
def test_polygon_sides_and_star_points_change_the_vertex_count():
    for sides in range(3, 13):
        assert lib.vertices(lib.geometry("shape", "polygon", 20, 20, {"filled": True, "sides": sides})) == sides + 1
        assert lib.vertices(lib.geometry("shape", "polygon", 20, 20, {"filled": False, "sides": sides})) == 2 * sides + 2
    for points in range(3, 13):
        assert lib.vertices(lib.geometry("shape", "star", 20, 20, {"filled": True, "points": points})) == 2 * points + 1
    assert lib.vertices(lib.geometry("shape", "star", 20, 20, {"points": 9})) > lib.vertices(lib.geometry("shape", "star", 20, 20, {"points": 5}))


def test_the_inner_radius_of_a_star_changes_its_area():
    areas = [area("shape", "star", 30, 30, filled=True, inner_pct=pct) for pct in (15, 30, 50, 70, 90)]
    assert all(b > a for a, b in zip(areas, areas[1:]))


def test_a_larger_corner_radius_takes_more_off_a_rounded_rectangle_and_is_held_to_the_box():
    areas = [area("shape", "rounded_rectangle", 30, 20, filled=True, corner_mm=c) for c in (0, 2, 5, 10)]
    assert all(b < a for a, b in zip(areas, areas[1:]))
    huge = lib.geometry("shape", "rounded_rectangle", 30, 6, {"filled": True, "corner_mm": 30})          # held to half of the short side
    assert huge.is_valid and huge.bounds == pytest.approx((-15, -3, 15, 3))
    assert huge.area == pytest.approx(30 * 6 - (4 - math.pi) * 9, rel=2e-3)


def test_a_double_frame_has_two_rings_a_gap_apart():
    geom = lib.geometry("frame", "double", 80, 49, {"gap_mm": 1.0, "stroke_mm": 0.3})
    assert isinstance(geom, MultiPolygon) and len(geom.geoms) == 2
    assert all(len(poly.interiors) == 1 for poly in geom.geoms)
    outer, inner = sorted(geom.geoms, key=lambda p: -p.area)
    assert outer.bounds == pytest.approx((-40, -24.5, 40, 24.5)) and inner.bounds == pytest.approx((-40 + 1.3, -24.5 + 1.3, 40 - 1.3, 24.5 - 1.3))
    assert outer.distance(inner) == pytest.approx(1.0)
    wider = lib.geometry("frame", "double", 80, 49, {"gap_mm": 3.0, "stroke_mm": 0.3})
    assert sorted(wider.geoms, key=lambda p: -p.area)[1].bounds == pytest.approx((-40 + 3.3, -24.5 + 3.3, 40 - 3.3, 24.5 - 3.3))
    assert len(lib.geometry("frame", "single", 80, 49).interiors) == 1


def test_a_double_frame_in_a_box_too_small_for_the_second_ring_is_one_ring():
    geom = lib.geometry("frame", "double", 2.0, 2.0, {"gap_mm": 1.0, "stroke_mm": 0.5})
    assert isinstance(geom, Polygon) and len(geom.interiors) == 1


def test_corner_styles_cut_the_corners_of_a_frame():
    single = area("frame", "single", 80, 49, stroke_mm=0.5)
    for style in ("rounded", "chamfered", "notched"):
        zero = lib.geometry("frame", style, 80, 49, {"corner_mm": 0, "stroke_mm": 0.5})
        assert zero.area == pytest.approx(single) and lib.vertices(zero) == 10
        cut = [area("frame", style, 80, 49, corner_mm=c, stroke_mm=0.5) for c in (2, 5, 10)]
        assert all(b < a for a, b in zip(cut, cut[1:])), style
    notched = lib.geometry("frame", "notched", 80, 49, {"corner_mm": 5, "stroke_mm": 0.5})
    assert notched.bounds == pytest.approx((-40, -24.5, 40, 24.5)) and len(notched.interiors) == 1
    assert not notched.contains(Point(-40 + 1, -24.5 + 1))                   # the corner is notched away
    assert lib.geometry("frame", "chamfered", 80, 49, {"corner_mm": 5}).contains(Point(-40 + 1, -24.5 + 1)) is False


def test_a_dashed_frame_is_dashes_in_a_rectangle_with_the_corners_closed():
    geom = lib.geometry("frame", "dashed", 80, 49, {"dash_mm": 3, "gap_mm": 1.5, "stroke_mm": 0.3})
    assert isinstance(geom, MultiPolygon) and len(geom.geoms) > 40 and not any(poly.interiors for poly in geom.geoms)
    assert geom.bounds == pytest.approx((-40, -24.5, 40, 24.5))
    pieces = list(geom.geoms)
    assert min(a.distance(b) for i, a in enumerate(pieces) for b in pieces[i + 1:]) >= 1.5 - 1e-6                  # never closer than the gap
    longer = lib.geometry("frame", "dashed", 80, 49, {"dash_mm": 8, "gap_mm": 1.5, "stroke_mm": 0.3})
    wider = lib.geometry("frame", "dashed", 80, 49, {"dash_mm": 3, "gap_mm": 6, "stroke_mm": 0.3})
    assert len(longer.geoms) < len(geom.geoms) and len(wider.geoms) < len(geom.geoms)
    assert geom.area < lib.geometry("frame", "single", 80, 49, {"stroke_mm": 0.3}).area
    for corner in ((-40, -24.5), (40, -24.5), (40, 24.5), (-40, 24.5)):                           # an L-shaped dash in every corner
        assert geom.distance(Point(corner)) < 1e-9


def test_a_dashed_frame_too_small_for_its_dashes_is_a_plain_frame_and_too_many_dashes_are_refused():
    small = lib.geometry("frame", "dashed", 5.0, 5.0, {"dash_mm": 8, "gap_mm": 1.5, "stroke_mm": 0.3})
    assert isinstance(small, Polygon) and len(small.interiors) == 1
    with pytest.raises(su.ValidationError, match="dashes"):
        lib.geometry("frame", "dashed", 500, 500, {"dash_mm": 0.5, "gap_mm": 0.3, "stroke_mm": 0.3})


def test_scaling_the_box_scales_the_geometry():
    for group, name in ITEMS:
        if group == "icon" or (group, name) == ("shape", "line"):
            continue
        small, large = lib.geometry(group, name, 40.0, 24.0, {}), lib.geometry(group, name, 80.0, 72.0, {})
        assert small.bounds == pytest.approx((-20, -12, 20, 12), abs=1e-6) and large.bounds == pytest.approx((-40, -36, 40, 36), abs=1e-6)
    for name in ("rectangle", "ellipse", "triangle", "diamond", "star", "polygon"):                  # (an arrow's head is not scaled evenly)
        a, b = area("shape", name, 20, 10, filled=True), area("shape", name, 40, 30, filled=True)
        assert b / a == pytest.approx(6.0, rel=5e-3), name
    icon = lib.geometry("icon", "heart", 8.0, 8.0, {"stroke_mm": 0.3})
    bigger = lib.geometry("icon", "heart", 16.0, 16.0, {"stroke_mm": 0.3})
    width = lambda g: g.bounds[2] - g.bounds[0]                                                    # noqa: E731
    assert (width(bigger) - 0.3) / (width(icon) - 0.3) == pytest.approx((16 - 0.3) / (8 - 0.3), rel=1e-3)      # the centre-lines scale, the line does not


def test_the_geometry_of_the_same_request_is_the_same_and_the_requests_do_not_disturb_each_other():
    a = lib.geometry("shape", "star", 20, 12, {"points": 6})
    assert lib.geometry("shape", "star", 20, 12, {"points": 6}).equals(a) and lib.geometry("shape", "star", 20, 12, {"points": 6, "inner_pct": 40}).equals(a)
    assert not lib.geometry("shape", "star", 20, 12, {"points": 7}).equals(a)


@pytest.mark.parametrize("group", lib.GROUPS)
def test_no_item_has_more_than_the_vertex_limit_at_the_largest_size(group):
    for name in lib._GROUP[group]:
        for filled in (False, True):
            params = {"filled": filled} if has(group, name, "filled") else {}
            geom = lib.geometry(group, name, 500.0, 500.0, params)
            assert lib.vertices(geom) <= lib.MAX_VERTICES and geom.is_valid and not geom.is_empty


def test_curves_are_flattened_within_a_hundredth_of_a_millimetre():
    ellipse = lib.geometry("shape", "ellipse", 100.0, 100.0, {"filled": True})                        # a circle of radius 50
    radii = [math.hypot(x, y) for x, y in ellipse.exterior.coords]
    assert max(radii) <= 50 + 1e-9 and 50 - min(radii) <= 0.0101
    mid = [math.hypot((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(ellipse.exterior.coords, list(ellipse.exterior.coords)[1:])]
    assert 50 - min(mid) <= 0.0101                                                                  # and between the vertices
    rounded = lib.geometry("frame", "rounded", 80, 49, {"corner_mm": 20})
    assert lib.vertices(rounded) > 100


# -- validation ----------------------------------------------------------------------------------------------------------------------
def refused(call, *args, **kwargs):
    with pytest.raises(su.ValidationError) as error:
        call(*args, **kwargs)
    message = str(error.value)
    assert message and message.isascii() and not message.endswith(":")                          # a plain English sentence
    return message


def test_unknown_groups_names_and_settings_are_refused_by_name():
    assert "'cube'" in refused(lib.checked, "shape", "cube")
    assert "'nothing'" in refused(lib.checked, "nothing", "rectangle")
    assert "'rectangle'" in refused(lib.checked, "frame", "rectangle")                    # a shape's name is not a frame's
    assert "'colour'" in refused(lib.checked, "shape", "rectangle", {"colour": "red"})
    assert "'filled'" in refused(lib.checked, "frame", "single", {"filled": True})
    assert "'corner_mm'" in refused(lib.checked, "shape", "rectangle", {"corner_mm": 2})
    assert "'filled'" in refused(lib.checked, "shape", "line", {"filled": True})
    refused(lib.checked, "shape", None)
    refused(lib.checked, "shape", ["rectangle"])
    refused(lib.checked, "shape", "rectangle", [1, 2])
    for call in (lib.default_size, lambda g, n: lib.geometry(g, n, 10, 10), lambda g, n: lib.geometry(g, n, 10, 10, {})):
        refused(call, "icon", "teapot")


def test_numbers_must_be_in_range_and_really_numbers():
    for params in ({"stroke_mm": 0.04}, {"stroke_mm": 3.01}, {"stroke_mm": -1}, {"stroke_mm": float("nan")}, {"stroke_mm": float("inf")},
                   {"stroke_mm": "0.3"}, {"stroke_mm": None}, {"stroke_mm": [0.3]}):
        assert "line width" in refused(lib.checked, "shape", "rectangle", params), params
    assert "line width" in refused(lib.checked, "icon", "phone", {"stroke_mm": 4})
    assert "points" in refused(lib.checked, "shape", "star", {"points": 2})
    assert "points" in refused(lib.checked, "shape", "star", {"points": 13})
    assert "points" in refused(lib.checked, "shape", "star", {"points": 5.5})                  # a whole number
    assert "inner radius" in refused(lib.checked, "shape", "star", {"inner_pct": 14.9})
    assert "inner radius" in refused(lib.checked, "shape", "star", {"inner_pct": 90.1})
    assert "sides" in refused(lib.checked, "shape", "polygon", {"sides": 2})
    assert "corner radius" in refused(lib.checked, "shape", "rounded_rectangle", {"corner_mm": -0.1})
    assert "gap" in refused(lib.checked, "frame", "double", {"gap_mm": 0.0})
    assert "dash length" in refused(lib.checked, "frame", "dashed", {"dash_mm": 0.1})
    assert "from 0.05 to 3 mm" in refused(lib.checked, "shape", "rectangle", {"stroke_mm": 9})
    assert "%" in refused(lib.checked, "shape", "star", {"inner_pct": 5})


def test_a_bool_is_not_a_number_and_a_number_is_not_a_bool():
    assert "line width" in refused(lib.checked, "shape", "rectangle", {"stroke_mm": True})
    assert "line width" in refused(lib.checked, "icon", "phone", {"stroke_mm": False})
    assert "points" in refused(lib.checked, "shape", "star", {"points": True})
    assert "filled" in refused(lib.checked, "shape", "rectangle", {"filled": 1}) and "filled" in refused(lib.checked, "icon", "key", {"filled": "yes"})
    assert "filled" in refused(lib.checked, "shape", "rectangle", {"filled": None})


def test_checked_fills_defaults_keeps_good_values_and_accepts_numpy_numbers():
    assert lib.checked("shape", "star") == {"points": 5, "inner_pct": 40.0, "filled": False, "stroke_mm": 0.3}
    got = lib.checked("shape", "star", {"points": 7.0, "stroke_mm": 1, "filled": True})
    assert got == {"points": 7, "inner_pct": 40.0, "filled": True, "stroke_mm": 1.0} and isinstance(got["points"], int)
    assert isinstance(got["stroke_mm"], float)
    assert lib.checked("icon", "key", {"stroke_mm": np.float64(0.5), "filled": True}) == {"filled": True, "stroke_mm": 0.5}
    assert lib.checked("frame", "dashed", {"dash_mm": np.int64(4)})["dash_mm"] == 4.0
    assert lib.checked("shape", "rectangle", {}) == lib.checked("shape", "rectangle", None)
    params = {"stroke_mm": 0.8}
    lib.checked("shape", "rectangle", params)
    assert params == {"stroke_mm": 0.8}                                                          # the argument is not changed
    for edge in (0.05, 3):
        assert lib.checked("shape", "rectangle", {"stroke_mm": edge})["stroke_mm"] == edge        # both ends of the range are allowed


def test_the_size_of_an_element_is_checked():
    for bad in (0.19, 0, -5, 500.1, 1e9, float("nan"), float("inf"), True, "20", None, [20]):
        assert "width" in refused(lib.geometry, "shape", "rectangle", bad, 10), bad
        assert "height" in refused(lib.geometry, "shape", "rectangle", 10, bad), bad
    assert "from 0.2 to 500 mm" in refused(lib.geometry, "icon", "bell", 600, 8)
    for ok in (0.2, 500, np.float64(12.5), 7):
        assert lib.geometry("shape", "rectangle", ok, ok).bounds == pytest.approx((-ok / 2, -ok / 2, ok / 2, ok / 2))
    refused(lib.geometry, "shape", "rectangle", 10, 10, {"stroke_mm": 99})


# -- the listing a picker draws its thumbnails from ----------------------------------------------------------------------------------------
def test_the_listing_describes_every_item_and_round_trips_through_json():
    listing = lib.listing()
    assert json.loads(json.dumps(listing)) == listing
    assert list(listing) == ["shape", "frame", "icon"]
    for group in lib.GROUPS:
        assert [item["name"] for item in listing[group]] == list(lib._GROUP[group])
        for item in listing[group]:
            name = item["name"]
            assert set(item) == {"name", "label", "params", "default_size", "preview"}
            assert item["label"] == lib._GROUP[group][name]["label"] and item["params"] == lib._GROUP[group][name]["params"]
            assert item["default_size"] == lib.default_size(group, name)
    assert len(listing["shape"]) >= 8 and len(listing["frame"]) >= 6 and len(listing["icon"]) >= 24


@pytest.mark.parametrize("group,name", ITEMS, ids=IDS)
def test_every_preview_is_a_path_drawn_inside_a_24_box_around_its_middle(group, name):
    d = next(item for item in lib.listing()[group] if item["name"] == name)["preview"]
    assert isinstance(d, str) and d.startswith("M") and d.endswith("Z") and re.fullmatch(r"[MLZ0-9. \-]+", d)
    numbers = np.array([float(x) for x in re.findall(r"-?\d+\.?\d*", d)]).reshape(-1, 2)
    assert numbers.min() >= 0 and numbers.max() <= 24
    (x0, y0), (x1, y1) = numbers.min(axis=0), numbers.max(axis=0)
    assert (x0 + x1) / 2 == pytest.approx(12, abs=0.02) and (y0 + y1) / 2 == pytest.approx(12, abs=0.02)
    assert max(x1 - x0, y1 - y0) >= 20                                                             # as large as the box allows
    assert all(len(ring.split(" L")) >= 3 for ring in d.split("M")[1:])                               # every ring has at least three points


def test_a_preview_is_the_item_seen_even_when_its_lines_are_thin():
    previews = {(group, item["name"]): item["preview"] for group in lib.GROUPS for item in lib.listing()[group]}
    assert len(set(previews.values())) == len(previews)                                           # every thumbnail is different
    assert previews[("shape", "line")].count("M") == 1 and previews[("frame", "double")].count("M") == 4       # two rings: four outlines
    assert previews[("frame", "dashed")].count("M") > 8 and previews[("frame", "single")].count("M") == 2


def test_the_listing_is_a_copy_the_caller_may_change():
    first = lib.listing()
    first["shape"][0]["params"][0]["default"] = "changed"
    first["shape"].pop()
    again = lib.listing()
    assert again["shape"][0]["params"][0]["default"] != "changed" and len(again["shape"]) == len(lib.SHAPES)
    assert lib.SHAPES["rectangle"]["params"][0]["default"] is False
