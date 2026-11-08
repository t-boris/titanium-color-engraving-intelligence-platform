"""The SVG reader of the card editor (feature-3): sizes and units, every path command, transforms, style sheets and inheritance, colours,
opacity, fill rules, strokes, use/symbol, clip paths, gradients, what is counted in the notes, and the files that are refused.

The drawings are small synthetic SVG strings; the checks are on areas and bounds in millimetres (flattened curves are not exact)."""
import gzip
import math
import re
import time

import pytest
from shapely.geometry import MultiPolygon, Polygon

from titanium_platform import card_vector_svg as sv, setup as su
from titanium_platform.card_vector_geometry import Parsed, Shape

NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
MM = 'width="100mm" height="100mm" viewBox="0 0 100 100"'        # one user unit is one millimetre


def doc(body: str, attrs: str = MM) -> bytes:
    return f"<svg {NS} {attrs}>{body}</svg>".encode()


def read(body: str, attrs: str = MM) -> Parsed:
    return sv.parse(doc(body, attrs))


def one(body: str, attrs: str = MM) -> Shape:
    parsed = read(body, attrs)
    assert len(parsed.shapes) == 1, [s.fill for s in parsed.shapes]
    return parsed.shapes[0]


def bounds(shape: Shape):
    return pytest.approx(shape.geometry.bounds, abs=1e-6)


def near(value, expected, tol=1e-6):
    return value == pytest.approx(expected, abs=tol)


SQUARE = '<rect width="10" height="10"/>'


# -- the result ---------------------------------------------------------------------------------------------------------------------------
def test_a_plain_drawing_is_shapes_in_mm_with_no_notes():
    parsed = read('<rect x="10" y="20" width="30" height="40" fill="red"/>')
    assert isinstance(parsed, Parsed) and parsed.kind == "svg" and parsed.notes == []
    shape = parsed.shapes[0]
    assert shape.fill == "#ff0000" and shape.name is None
    assert shape.geometry.bounds == pytest.approx((10, 20, 40, 60))      # y points down, the origin is the top-left of the frame
    assert near(shape.geometry.area, 1200)


def test_fills_are_lowercase_rrggbb():
    for shape in read('<rect width="5" height="5" fill="#ABCDEF"/><circle cx="50" cy="50" r="5" fill="Tomato"/>').shapes:
        assert re.fullmatch(r"#[0-9a-f]{6}", shape.fill)


def test_an_id_is_the_name_of_the_shape():
    shapes = read('<rect id="box" width="5" height="5"/><rect width="5" height="5"/>').shapes
    assert [s.name for s in shapes] == ["box", None]


def test_shapes_come_in_painting_order():
    parsed = read('<rect width="5" height="5" fill="#ff0000"/><g><rect width="5" height="5" fill="#00ff00"/>'
                  '<circle cx="9" cy="9" r="3" fill="#0000ff"/></g><path d="M0 0H3V3Z" fill="#ffff00"/>')
    assert [s.fill for s in parsed.shapes] == ["#ff0000", "#00ff00", "#0000ff", "#ffff00"]


def test_a_stroke_is_its_own_shape_right_after_its_fill():
    parsed = read('<rect id="box" x="10" y="10" width="10" height="10" fill="#00ff00" stroke="#ff0000" stroke-width="2"/>'
                  '<rect width="5" height="5" fill="#0000ff"/>')
    fills = [(s.fill, s.name) for s in parsed.shapes]
    assert fills == [("#00ff00", "box"), ("#ff0000", "box outline"), ("#0000ff", None)]


def test_tiny_shapes_are_dropped_without_a_word():
    parsed = read('<rect width="0.0005" height="0.0005"/><rect width="5" height="5"/>')
    assert len(parsed.shapes) == 1 and parsed.notes == []


# -- size and units -----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("size", ["1in", "2.54cm", "25.4mm", "72pt", "6pc", "96px", "96"])
def test_the_width_in_any_unit_is_millimetres(size):
    shape = one('<rect width="100" height="100"/>', f'width="{size}" height="{size}" viewBox="0 0 100 100"')
    assert shape.geometry.bounds == pytest.approx((0, 0, 25.4, 25.4), abs=1e-6)


def test_without_viewbox_a_unitless_length_is_px():
    shape = one('<rect width="96" height="96"/>', 'width="96" height="96"')
    assert shape.geometry.bounds == pytest.approx((0, 0, 25.4, 25.4), abs=1e-6)


def test_the_width_in_mm_does_not_scale_a_drawing_without_viewbox():
    shape = one('<rect width="96" height="96"/>', 'width="100mm" height="100mm"')
    assert shape.geometry.bounds == pytest.approx((0, 0, 25.4, 25.4), abs=1e-6)      # a user unit is a px, whatever the page size


def test_a_viewbox_alone_is_the_size_in_px():
    shape = one('<rect width="96" height="96"/>', 'viewBox="0 0 96 96"')
    assert shape.geometry.bounds == pytest.approx((0, 0, 25.4, 25.4), abs=1e-6)


@pytest.mark.parametrize("size", ['width="100%" height="100%"', 'width="10em" height="5ex"', 'width="0" height="-3"'])
def test_percentages_and_font_units_fall_back_to_the_viewbox_size(size):
    shape = one('<rect width="96" height="96"/>', f'{size} viewBox="0 0 96 96"')
    assert shape.geometry.bounds == pytest.approx((0, 0, 25.4, 25.4), abs=1e-6)


def test_no_viewbox_and_no_size_is_the_drawing_in_px():
    shape = one('<rect x="96" width="96" height="96"/>', "")
    assert shape.geometry.bounds == pytest.approx((25.4, 0, 50.8, 25.4), abs=1e-6)


def test_only_a_width_gives_the_height_by_the_viewbox_aspect():
    shape = one('<rect width="100" height="50"/>', 'width="50mm" viewBox="0 0 100 50"')
    assert shape.geometry.bounds == pytest.approx((0, 0, 50, 25), abs=1e-6)


def test_the_viewbox_origin_is_the_origin_of_the_frame():
    shape = one('<rect x="10" y="20" width="10" height="10"/>', 'width="100mm" height="100mm" viewBox="10 20 100 100"')
    assert shape.geometry.bounds == pytest.approx((0, 0, 10, 10), abs=1e-6)


@pytest.mark.parametrize("aspect, expected", [
    ("", (50, 0, 150, 100)),                       # xMidYMid meet
    ('preserveAspectRatio="xMinYMin meet"', (0, 0, 100, 100)),
    ('preserveAspectRatio="xMaxYMax meet"', (100, 0, 200, 100)),
    ('preserveAspectRatio="xMidYMid slice"', (0, -50, 200, 150)),
    ('preserveAspectRatio="none"', (0, 0, 200, 100)),
])
def test_preserve_aspect_ratio_of_the_root(aspect, expected):
    shape = one('<rect width="100" height="100"/>', f'width="200mm" height="100mm" viewBox="0 0 100 100" {aspect}')
    assert shape.geometry.bounds == pytest.approx(expected, abs=1e-6)


def test_an_svg_without_a_namespace_is_read_too():
    parsed = sv.parse(b'<svg width="10mm" height="10mm" viewBox="0 0 10 10"><rect width="5" height="5"/></svg>')
    assert len(parsed.shapes) == 1


# -- elements -----------------------------------------------------------------------------------------------------------------------------
def test_rect_circle_ellipse_areas():
    assert near(one('<rect width="10" height="20"/>').geometry.area, 200)
    assert one('<circle cx="50" cy="50" r="5"/>').geometry.area == pytest.approx(math.pi * 25, rel=0.005)
    assert one('<ellipse cx="50" cy="50" rx="10" ry="5"/>').geometry.area == pytest.approx(math.pi * 50, rel=0.005)


def test_a_rounded_rect_loses_its_corners():
    for corners in ('rx="2" ry="2"', 'rx="2"', 'ry="2"'):
        area = one(f'<rect width="10" height="10" {corners}/>').geometry.area
        assert area == pytest.approx(100 - (4 - math.pi) * 4, abs=0.1)
    assert one('<rect width="10" height="10" rx="50"/>').geometry.area == pytest.approx(math.pi * 25, rel=0.01)    # clamped to half the side


@pytest.mark.parametrize("body", ['<rect width="0" height="10"/>', '<rect width="-5" height="10"/>', '<circle r="0"/>', '<ellipse rx="5" ry="0"/>',
                                  '<polygon points="1,1"/>', '<path d=""/>', '<line x2="5" y2="5"/>'])
def test_degenerate_elements_draw_nothing(body):
    assert read(body).shapes == []


def test_polyline_and_polygon_fill_closes_and_stroke_follows_the_points():
    assert near(one('<polyline points="0,0 10,0 10,10"/>').geometry.area, 50)
    assert near(one('<polygon points="0,0 10,0 10,10"/>').geometry.area, 50)
    parsed = read('<polyline points="0,5 10,5" fill="none" stroke="#000" stroke-width="2"/>')
    assert near(parsed.shapes[0].geometry.area, 20)
    assert read('<polygon points="0 0 10 0 10 10 0" fill="none"/>').shapes == []                # the odd number is dropped, no stroke


def test_a_line_has_no_fill_but_a_stroke():
    assert read('<line x1="0" y1="0" x2="10" y2="0"/>').shapes == []
    shape = one('<line x1="0" y1="5" x2="10" y2="5" stroke="#000" stroke-width="2"/>')
    assert near(shape.geometry.area, 20)
    assert shape.geometry.bounds == pytest.approx((0, 4, 10, 6), abs=1e-6)


# -- path data ----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("d, area", [
    ("M0 0H10V10H0Z", 100),
    ("m0 0h10v10h-10z", 100),
    ("M0 0L10 0L10 10L0 10Z", 100),
    ("M0 0 10 0 10 10 0 10z", 100),                          # repeated L without the letter
    ("m0 0 10 0 0 10 -10 0z", 100),                          # repeated l
    ("M 0,0 L 10,0 10,10 0,10 z", 100),
    ("M0 0h10v10h-10", 100),                                 # an open path is closed to be filled
    ("M-.5-.5L9.5-.5L9.5 9.5L-.5 9.5Z", 100),
    ("M0 0L1e1 0L1E1 1e1L0 10Z", 100),
    ("M0 0L1e-3 0L0 .001Z", None),                           # a speck: nothing
    ("M0 0H10V10H0ZM2 2V4H4V2Z", 96),                        # a hole drawn the other way
    ("M0 0H10V10H0Z m2 2v2h2v-2z", 96),                      # relative m after z starts from the start of the last sub-path
    ("M0 0L10 0 10 10", 50),
])
def test_path_lines_and_closes(d, area):
    shapes = read(f'<path d="{d}"/>').shapes
    if area is None:
        assert shapes == []
    else:
        assert len(shapes) == 1 and near(shapes[0].geometry.area, area, 1e-6)


def test_numbers_written_together_are_split_as_the_syntax_says():
    expected = Polygon([(0, 0), (10.5, 0.5), (10, 10)]).area
    assert near(one('<path d="M0,0L10.5.5L10 10Z"/>').geometry.area, expected)
    assert near(one('<path d="M0 0l10.5.5-.5 9.5z"/>').geometry.area, Polygon([(0, 0), (10.5, 0.5), (10, 10)]).area)


def test_cubic_curves_with_smooth_continuation_draw_a_circle():
    for d in ("M0 5C0 2.2 2.2 0 5 0S10 2.2 10 5S7.8 10 5 10S0 7.8 0 5Z", "M0 5c0-2.8 2.2-5 5-5s5 2.2 5 5s-2.2 5-5 5s-5-2.2-5-5z"):
        shape = one(f'<path d="{d}"/>')
        assert shape.geometry.area == pytest.approx(math.pi * 25, rel=0.02)
        assert shape.geometry.bounds == pytest.approx((0, 0, 10, 10), abs=0.05)


def test_quadratic_curves():
    parabola = 2 / 3 * 10 * 5
    assert one('<path d="M0 0Q5 10 10 0Z"/>').geometry.area == pytest.approx(parabola, rel=0.005)
    assert one('<path d="M0 0q5 10 10 0z"/>').geometry.area == pytest.approx(parabola, rel=0.005)
    # T mirrors the control point: two lobes on either side of the chord
    lobes = one('<path d="M0 0Q2.5 5 5 0T10 0Z"/>').geometry
    assert lobes.area == pytest.approx(2 * (2 / 3 * 5 * 2.5), rel=0.01)
    assert lobes.bounds[1] == pytest.approx(-2.5, abs=0.05) and lobes.bounds[3] == pytest.approx(2.5, abs=0.05)
    assert one('<path d="M0 0Q2.5 5 5 0t5 0z"/>').geometry.area == pytest.approx(lobes.area, rel=0.01)


def test_arcs_sweep_the_way_svg_says():
    below = one('<path d="M0 0A5 5 0 0 0 10 0Z"/>').geometry                  # sweep 0: counter-clockwise on the screen, through the bottom
    above = one('<path d="M0 0A5 5 0 0 1 10 0Z"/>').geometry
    assert below.area == pytest.approx(math.pi * 25 / 2, rel=0.01) and above.area == pytest.approx(math.pi * 25 / 2, rel=0.01)
    assert below.bounds[1] == pytest.approx(0, abs=1e-6) and below.bounds[3] == pytest.approx(5, abs=0.01)
    assert above.bounds[1] == pytest.approx(-5, abs=0.01) and above.bounds[3] == pytest.approx(0, abs=1e-6)


def test_arc_flags_may_be_written_without_separators():
    shape = one('<path d="M0 0a5 5 0 0010 0z"/>')                              # flags 0 0, then x=10, y=0
    assert shape.geometry.area == pytest.approx(math.pi * 25 / 2, rel=0.01)
    assert sv._path_segments("M0 0a1 1 0 00.5.5") == [("M", 0.0, 0.0), ("A", 1.0, 1.0, 0.0, False, False, 0.5, 0.5)]
    assert sv._path_segments("M0 0a1 1 0 1110 0")[1] == ("A", 1.0, 1.0, 0.0, True, True, 10.0, 0.0)
    assert sv._path_segments("M0 0A1,1,0,0,1,2,0")[1] == ("A", 1.0, 1.0, 0.0, False, True, 2.0, 0.0)


def test_large_arc_and_radii_that_are_too_small():
    small = one('<path d="M0 0A10 10 0 0 1 10 0Z"/>').geometry.area
    large = one('<path d="M0 0A10 10 0 1 1 10 0Z"/>').geometry.area
    segment = 100 * (math.pi / 3 - math.sin(math.pi / 3)) / 2          # the part of the disc that lies beyond a chord of one radius
    assert small == pytest.approx(segment, rel=0.02)
    assert large == pytest.approx(math.pi * 100 - segment, rel=0.01)
    assert one('<path d="M0 0A1 1 0 0 1 10 0Z"/>').geometry.area == pytest.approx(math.pi * 25 / 2, rel=0.02)   # enlarged to reach


def test_a_rotated_elliptical_arc():
    shape = one('<path d="M0 0A10 5 90 0 1 10 0Z"/>')            # the long axis (10) turned to y: half of an ellipse 10 wide and 20 high, above the chord
    assert shape.geometry.area == pytest.approx(math.pi * 5 * 10 / 2, rel=0.01)
    assert shape.geometry.bounds == pytest.approx((0, -10, 10, 0), abs=0.05)


def test_a_broken_path_is_drawn_as_far_as_it_can_be_read():
    assert near(one('<path d="M0 0L10 0L10 10L"/>').geometry.area, 50)
    assert near(one('<path d="M0 0L10 0L10 10 L20"/>').geometry.area, 50)
    assert near(one('<path d="M0 0L10 0L10 10 X 5 5 L0 10"/>').geometry.area, 50)
    assert read('<path d="L10 0L10 10"/>').shapes == []                          # it must begin with a move
    assert read('<path d="M0 0L1e999 0L0 5"/>').shapes == []
    assert read('<path d="hello"/>').shapes == []


def test_drawing_after_close_starts_a_new_sub_path_where_the_last_began():
    shape = one('<path d="M0 0H10V10Z L10 0 V-10 Z"/>')                        # two triangles that share the edge from (0, 0) to (10, 0)
    assert near(shape.geometry.area, 100)
    assert shape.geometry.bounds == pytest.approx((0, -10, 10, 10), abs=1e-6)


# -- transforms ---------------------------------------------------------------------------------------------------------------------------
def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def test_transform_functions():
    assert sv._transform("translate(10 20)") == (1, 0, 0, 1, 10, 20)
    assert sv._transform("translate(10)") == (1, 0, 0, 1, 10, 0)
    assert sv._transform("scale(2)") == (2, 0, 0, 2, 0, 0)
    assert sv._transform("scale(2, 3)") == (2, 0, 0, 3, 0, 0)
    assert sv._transform("matrix(1 2 3 4 5 6)") == (1, 2, 3, 4, 5, 6)
    assert apply(sv._transform("rotate(90)"), 1, 0) == pytest.approx((0, 1), abs=1e-12)
    assert apply(sv._transform("rotate(90 5 5)"), 0, 0) == pytest.approx((10, 0), abs=1e-12)
    assert apply(sv._transform("skewX(45)"), 0, 10) == pytest.approx((10, 10), abs=1e-12)
    assert apply(sv._transform("skewY(45)"), 10, 0) == pytest.approx((10, 10), abs=1e-12)
    assert apply(sv._transform("translate(10,0) scale(2)"), 1, 1) == pytest.approx((12, 2))        # the last function applies first
    assert sv._transform("rubbish(1) translate(1 2) rotate(1 2)") == (1, 0, 0, 1, 1, 2)             # what cannot be read is skipped
    assert sv._transform("") == sv.IDENTITY


def test_nested_transforms_compose():
    shape = one('<g transform="translate(10 10)"><g transform="scale(2)"><rect width="5" height="5"/></g></g>')
    assert shape.geometry.bounds == pytest.approx((10, 10, 20, 20), abs=1e-6)


def test_a_transform_on_the_shape_itself():
    shape = one('<rect width="10" height="20" transform="rotate(90)"/>')
    assert shape.geometry.bounds == pytest.approx((-20, 0, 0, 10), abs=1e-6)
    assert one('<rect width="10" height="10" transform="skewX(45)"/>').geometry.bounds == pytest.approx((0, 0, 20, 10), abs=1e-6)
    assert one('<rect width="10" height="10" transform="matrix(2 0 0 3 4 5)"/>').geometry.bounds == pytest.approx((4, 5, 24, 35), abs=1e-6)


def test_curves_are_flattened_in_mm_whatever_the_scale():
    """The same circle in a viewBox 1000 times smaller: still a smooth circle in mm (flattened after the transform is known)."""
    shape = one('<circle cx="0.05" cy="0.05" r="0.04"/>', 'width="100mm" height="100mm" viewBox="0 0 0.1 0.1"')
    assert shape.geometry.area == pytest.approx(math.pi * 40 ** 2, rel=0.005)
    assert len(shape.geometry.exterior.coords) > 30


# -- style: sheets, precedence, inheritance -----------------------------------------------------------------------------------------------
def styled(style: str, element: str) -> Shape:
    return one(f"<style>{style}</style>{element}")


def test_a_class_rule():
    assert styled(".a{fill:#ff0000}", '<rect class="a" width="5" height="5"/>').fill == "#ff0000"
    assert styled(".a{fill:#ff0000}", '<rect class="x a y" width="5" height="5"/>').fill == "#ff0000"


def test_specificity_id_over_class_over_type_then_source_order():
    rect = '<rect id="b" class="a" width="5" height="5"/>'
    assert styled("rect{fill:#0000ff} .a{fill:#ff0000}", rect).fill == "#ff0000"
    assert styled("#b{fill:#00ff00} .a{fill:#ff0000}", rect).fill == "#00ff00"
    assert styled(".a{fill:#ff0000} .a{fill:#00ff00}", rect).fill == "#00ff00"
    assert styled("#b{fill:#00ff00} rect{fill:#0000ff}", rect).fill == "#00ff00"
    assert styled("rect.a{fill:#123456} .a{fill:#ff0000}", rect).fill == "#123456"         # more specific than the class alone


def test_attribute_is_below_the_sheet_and_the_style_attribute_above_it():
    assert styled(".a{fill:#ff0000}", '<rect class="a" fill="#0000ff" width="5" height="5"/>').fill == "#ff0000"
    assert styled(".a{fill:#ff0000}", '<rect class="a" style="fill:#123456" width="5" height="5"/>').fill == "#123456"
    assert one('<rect fill="#0000ff" style="fill:#00ff00;stroke:none" width="5" height="5"/>').fill == "#00ff00"


def test_comma_lists_types_and_the_universal_selector():
    sheet = ".a, .b {fill:#ff0000} circle{fill:#00ff00} path.a{fill:#0000ff}"
    parsed = read(f'<style>{sheet}</style><rect class="b" width="5" height="5"/><circle cx="20" cy="20" r="5"/><rect class="a" x="30" width="5" height="5"/>')
    assert [s.fill for s in parsed.shapes] == ["#ff0000", "#00ff00", "#ff0000"]              # path.a does not match a rect
    assert styled("*{fill:#abcdef}", '<rect width="5" height="5"/>').fill == "#abcdef"


def test_what_cannot_be_read_in_a_sheet_is_ignored():
    sheet = ("/* a comment */ @import url(x.css); @font-face{font-family:x;src:url(y)} @media print{.a{fill:#00ff00}} "
             "svg g > rect{fill:#00ff00} .a:hover{fill:#00ff00} [x]{fill:#00ff00} .a{fill:#ff0000 !important} ::broken{{ ")
    assert styled(sheet, '<rect class="a" width="5" height="5"/>').fill == "#ff0000"


def test_a_sheet_in_cdata_and_other_types_of_style():
    assert one('<style type="text/css"><![CDATA[ .a{fill:#ff0000} ]]></style><rect class="a" width="5" height="5"/>').fill == "#ff0000"
    assert one('<style type="text/less">.a{fill:#ff0000}</style><rect class="a" width="5" height="5"/>').fill == "#000000"


def test_stroke_rules_from_a_sheet():
    parsed = read('<style>.s{fill:none;stroke:#ff0000;stroke-width:2}</style><line class="s" x1="0" y1="5" x2="10" y2="5"/>')
    assert parsed.shapes[0].fill == "#ff0000" and near(parsed.shapes[0].geometry.area, 20)


def test_fill_and_stroke_are_inherited_and_can_be_overridden():
    parsed = read('<g fill="#ff0000" stroke="#0000ff" stroke-width="2"><rect width="10" height="10"/><rect x="20" width="10" height="10" fill="#00ff00" stroke="none"/></g>')
    assert [s.fill for s in parsed.shapes] == ["#ff0000", "#0000ff", "#00ff00"]
    assert one('<g style="fill:#ff0000"><g><rect width="5" height="5"/></g></g>').fill == "#ff0000"
    assert one('<g fill="#ff0000"><rect width="5" height="5" fill="inherit"/></g>').fill == "#ff0000"


def test_the_default_fill_is_black_and_there_is_no_stroke():
    parsed = read('<rect width="5" height="5"/>')
    assert [s.fill for s in parsed.shapes] == ["#000000"]


def test_fill_rule_is_inherited_by_the_shapes_of_a_group():
    ring = "M0 0H10V10H0ZM2 2H8V8H2Z"                      # the inner ring runs the same way
    assert near(one(f'<g fill-rule="evenodd"><path d="{ring}"/></g>').geometry.area, 100 - 36)
    assert near(one(f'<path d="{ring}"/>').geometry.area, 100)


# -- colours ------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("#f00", ("#ff0000", 1.0)), ("#FF0000", ("#ff0000", 1.0)), ("#ff000080", ("#ff0000", 128 / 255)), ("#f008", ("#ff0000", 0x88 / 255)),
    ("rgb(255, 0, 0)", ("#ff0000", 1.0)), ("rgb(100%, 0%, 50%)", ("#ff0080", 1.0)), ("rgb(255 0 0 / 50%)", ("#ff0000", 0.5)),
    ("rgba(0,0,255,.5)", ("#0000ff", 0.5)), ("rgb(300, -4, 0)", ("#ff0000", 1.0)), ("rgb(10.6, 0, 0)", ("#0b0000", 1.0)),
    ("hsl(120, 100%, 50%)", ("#00ff00", 1.0)), ("hsl(0 100% 50%)", ("#ff0000", 1.0)), ("hsla(240, 100%, 50%, 0.5)", ("#0000ff", 0.5)),
    ("hsl(0.5turn 100% 50%)", ("#00ffff", 1.0)), ("hsl(180deg, 100%, 50%)", ("#00ffff", 1.0)), ("hsl(0, 0%, 50%)", ("#808080", 1.0)),
    ("red", ("#ff0000", 1.0)), ("  RED ", ("#ff0000", 1.0)), ("rebeccapurple", ("#663399", 1.0)), ("transparent", ("#000000", 0.0)),
])
def test_colour_syntaxes(text, expected):
    got = sv._colour(text)
    assert got[0] == expected[0] and got[1] == pytest.approx(expected[1], abs=1e-9)


@pytest.mark.parametrize("text", ["", "#ff", "#ggg", "#12345", "rgb(1,2)", "rgb(a,b,c)", "hsl(1)", "notacolour", "var(--x)", "url(#x)"])
def test_what_is_not_a_colour(text):
    assert sv._colour(text) is None


def test_there_are_148_css_colour_names():
    assert len(sv.NAMED_COLOURS) == 148
    assert all(re.fullmatch(r"#[0-9a-f]{6}", v) for v in sv.NAMED_COLOURS.values())
    for name, value in {"black": "#000000", "white": "#ffffff", "gray": "#808080", "grey": "#808080", "darkgrey": "#a9a9a9", "navy": "#000080",
                        "lime": "#00ff00", "tomato": "#ff6347", "goldenrod": "#daa520", "lightgoldenrodyellow": "#fafad2", "yellowgreen": "#9acd32",
                        "cornflowerblue": "#6495ed", "mediumspringgreen": "#00fa9a"}.items():
        assert sv._colour(name) == (value, 1.0)


def test_current_colour_none_and_transparent():
    assert one('<g color="#00f"><rect width="5" height="5" fill="currentColor"/></g>').fill == "#0000ff"
    assert one('<rect width="5" height="5" fill="currentColor"/>').fill == "#000000"
    assert one('<rect width="5" height="5" style="color:#f00" fill="currentColor"/>').fill == "#ff0000"
    assert read('<rect width="5" height="5" fill="none"/>').shapes == []
    assert read('<rect width="5" height="5" fill="transparent"/>').shapes == []
    assert read('<rect width="5" height="5" fill="rgba(0,0,0,0)"/>').shapes == []


def test_an_unreadable_fill_is_the_default_black_and_an_unreadable_stroke_is_none():
    parsed = read('<rect width="5" height="5" fill="nonsense" stroke="nonsense" stroke-width="2"/>')
    assert [s.fill for s in parsed.shapes] == ["#000000"]


def test_a_missing_paint_server_uses_its_fallback_or_nothing():
    assert one('<rect width="5" height="5" fill="url(#nothing) #ff0000"/>').fill == "#ff0000"
    assert read('<rect width="5" height="5" fill="url(#nothing)"/>').shapes == []


# -- opacity ------------------------------------------------------------------------------------------------------------------------------
def test_opacity_is_laid_on_white():
    assert one('<rect width="5" height="5" opacity="0.5"/>').fill == "#808080"
    assert one('<rect width="5" height="5" fill="#ff0000" fill-opacity="0.5"/>').fill == "#ff8080"
    assert one('<rect width="5" height="5" fill="rgba(255,0,0,0.5)"/>').fill == "#ff8080"
    assert one('<rect width="5" height="5" fill="#ff000080" fill-opacity="0.5"/>').fill == "#ffbfbf"            # 0.5 * 0.502 on white
    assert one('<rect width="5" height="5" style="opacity:50%"/>').fill == "#808080"


def test_opacity_multiplies_down_the_tree():
    assert one('<g opacity="0.5"><g opacity="0.5"><rect width="5" height="5" opacity="1"/></g></g>').fill == "#bfbfbf"
    assert one('<g opacity="0.5"><rect width="5" height="5" opacity="0.5" fill-opacity="1"/></g>').fill == "#bfbfbf"


def test_stroke_opacity():
    parsed = read('<line x1="0" y1="5" x2="10" y2="5" stroke="#ff0000" stroke-opacity="0.5" stroke-width="2"/>')
    assert parsed.shapes[0].fill == "#ff8080"


def test_nothing_is_drawn_with_zero_opacity_or_display_none():
    for body in ['<rect width="5" height="5" opacity="0"/>', '<g opacity="0">%s</g>' % SQUARE, '<rect width="5" height="5" fill-opacity="0"/>',
                 '<rect width="5" height="5" display="none"/>', '<rect width="5" height="5" style="display:none"/>',
                 '<g display="none">%s</g>' % SQUARE, '<style>.h{display:none}</style><g class="h">%s</g>' % SQUARE,
                 '<rect width="5" height="5" visibility="hidden"/>', '<g visibility="hidden">%s</g>' % SQUARE]:
        assert read(body).shapes == [], body


def test_a_child_may_show_itself_in_a_hidden_group():
    parsed = read('<g visibility="hidden"><rect width="5" height="5"/><rect x="10" width="5" height="5" visibility="visible"/></g>')
    assert [s.geometry.bounds[0] for s in parsed.shapes] == [10.0]


def test_display_none_hides_the_text_it_holds_from_the_notes_too():
    assert read('<g display="none"><text>A</text></g>%s' % SQUARE).notes == []


# -- fill rules ---------------------------------------------------------------------------------------------------------------------------
def test_nonzero_and_even_odd_holes():
    same_way = "M0 0H10V10H0ZM2 2H8V8H2Z"                 # both clockwise
    opposite = "M0 0H10V10H0ZM2 2V8H8V2Z"                 # the inner one the other way
    assert near(one(f'<path d="{same_way}" fill-rule="nonzero"/>').geometry.area, 100)
    assert near(one(f'<path d="{same_way}" fill-rule="evenodd"/>').geometry.area, 64)
    assert near(one(f'<path d="{opposite}" fill-rule="nonzero"/>').geometry.area, 64)
    assert near(one(f'<path d="{opposite}" fill-rule="evenodd"/>').geometry.area, 64)
    assert near(one(f'<path d="{same_way}" style="fill-rule:evenodd"/>').geometry.area, 64)


def test_every_open_sub_path_is_a_ring_for_the_fill():
    shape = one('<path d="M0 0H10V10H0M20 0H30V10H20" fill-rule="evenodd"/>')
    assert near(shape.geometry.area, 200) and isinstance(shape.geometry, MultiPolygon)


# -- strokes ------------------------------------------------------------------------------------------------------------------------------
def test_stroke_of_a_closed_shape_is_the_band_around_its_outline():
    parsed = read('<rect x="20" y="20" width="10" height="10" fill="none" stroke="#000" stroke-width="2"/>')
    assert len(parsed.shapes) == 1 and near(parsed.shapes[0].geometry.area, 12 ** 2 - 8 ** 2)
    assert parsed.shapes[0].geometry.bounds == pytest.approx((19, 19, 31, 31), abs=1e-6)
    ring = one('<circle cx="50" cy="50" r="10" fill="none" stroke="#000" stroke-width="2"/>')
    assert ring.geometry.area == pytest.approx(math.pi * (11 ** 2 - 9 ** 2), rel=0.01)


@pytest.mark.parametrize("cap, area", [("butt", 20.0), ("square", 24.0), ("round", 20.0 + math.pi)])
def test_line_caps(cap, area):
    shape = one(f'<line x1="10" y1="5" x2="20" y2="5" stroke="#000" stroke-width="2" stroke-linecap="{cap}"/>')
    assert shape.geometry.area == pytest.approx(area, abs=0.05)


def test_line_joins_and_the_miter_limit():
    path = 'd="M0 0H10V10" fill="none" stroke="#000" stroke-width="2"'
    mitre = one(f'<path {path}/>').geometry.area
    round_ = one(f'<path {path} stroke-linejoin="round"/>').geometry.area
    bevel = one(f'<path {path} stroke-linejoin="bevel"/>').geometry.area
    assert mitre == pytest.approx(40, abs=1e-6)
    assert bevel < round_ < mitre
    thin = 'd="M0 0L10 0L0.5 1" fill="none" stroke="#000" stroke-width="2"'
    assert one(f'<path {thin} stroke-miterlimit="1"/>').geometry.area < one(f'<path {thin} stroke-miterlimit="50"/>').geometry.area


def test_the_stroke_width_follows_the_transform():
    assert near(one('<g transform="scale(2)"><line x1="0" y1="5" x2="10" y2="5" stroke="#000" stroke-width="1"/></g>').geometry.area, 20 * 2)
    # a stretch that is not even: the width is multiplied by the root of the area factor (sqrt(2 * 8) = 4), the length is stretched by 2
    assert near(one('<g transform="scale(2 8)"><line x1="0" y1="1" x2="10" y2="1" stroke="#000" stroke-width="1"/></g>').geometry.area, 20 * 4)


def test_stroke_widths_in_units_and_a_zero_width():
    mm_wide = one('<line x1="0" y1="5" x2="10" y2="5" stroke="#000" stroke-width="1mm"/>')            # 1mm = 3.78 user units, here also mm
    assert near(mm_wide.geometry.area, 10 * 96 / 25.4)
    assert read('<line x1="0" y1="5" x2="10" y2="5" stroke="#000" stroke-width="0"/>').shapes == []
    assert read('<line x1="0" y1="5" x2="10" y2="5" stroke="#000" stroke-width="-1"/>').shapes == []


def test_the_default_stroke_width_is_one_unit():
    assert near(one('<line x1="0" y1="5" x2="10" y2="5" stroke="#000"/>').geometry.area, 10)


def test_a_stroked_path_with_several_sub_paths_is_one_shape():
    parsed = read('<path d="M0 5H10M0 20H10M0 40H10" stroke="#000" stroke-width="2" fill="none"/>')
    assert len(parsed.shapes) == 1 and near(parsed.shapes[0].geometry.area, 60)


def test_dashes_are_drawn_solid_and_counted():
    solid = one('<line x1="0" y1="5" x2="10" y2="5" stroke="#000" stroke-width="2"/>').geometry.area
    parsed = read('<line x1="0" y1="5" x2="10" y2="5" stroke="#000" stroke-width="2" stroke-dasharray="1 1"/>')
    assert near(parsed.shapes[0].geometry.area, solid)
    assert parsed.notes == ["1 dashed line was drawn solid."]
    both = read('<g stroke="#000" stroke-dasharray="2,1"><line x2="10" y2="5"/><line x2="10" y1="9" y2="9"/></g>')
    assert both.notes == ["2 dashed lines were drawn solid."]
    assert read('<line x2="10" y2="5" stroke="#000" stroke-dasharray="none"/>').notes == []
    assert read('<line x2="10" y2="5" stroke="#000" stroke-dasharray="0"/>').notes == []


# -- use, symbol, nested svg, switch -----------------------------------------------------------------------------------------------------
def test_defs_are_not_drawn_and_use_places_them():
    parsed = read('<defs><rect id="r" width="10" height="10"/></defs><use href="#r" x="20" y="30"/>')
    assert len(parsed.shapes) == 1 and parsed.shapes[0].geometry.bounds == pytest.approx((20, 30, 30, 40), abs=1e-6)
    old = read('<defs><rect id="r" width="10" height="10"/></defs><use xlink:href="#r" transform="translate(5 5)"/>')
    assert old.shapes[0].geometry.bounds == pytest.approx((5, 5, 15, 15), abs=1e-6)


def test_a_use_passes_its_style_down_unless_the_shape_has_its_own():
    parsed = read('<defs><rect id="a" width="5" height="5"/><rect id="b" width="5" height="5" fill="#00ff00"/></defs>'
                  '<use href="#a" fill="#ff0000"/><use href="#b" fill="#ff0000"/>')
    assert [s.fill for s in parsed.shapes] == ["#ff0000", "#00ff00"]


def test_use_of_a_group_and_uses_of_uses():
    parsed = read('<g id="a"><rect width="5" height="5"/></g><use id="b" href="#a" x="10"/><use href="#b" transform="translate(0 20)"/>')
    assert [s.geometry.bounds[:2] for s in parsed.shapes] == [(0.0, 0.0), (10.0, 0.0), (10.0, 20.0)]


def test_a_use_names_its_shapes_when_they_have_no_id():
    parsed = read('<defs><rect id="own" width="5" height="5"/><rect width="5" height="5"/></defs><use id="u" href="#own"/>')
    assert parsed.shapes[0].name == "own"
    parsed = read('<defs><g id="g"><rect width="5" height="5"/></g></defs><use id="u" href="#g"/>')
    assert parsed.shapes[0].name == "u"


def test_a_symbol_with_a_viewbox_is_fitted_to_the_use():
    shape = one('<symbol id="s" viewBox="0 0 10 10"><rect width="10" height="10"/></symbol><use href="#s" width="20" height="20" x="5" y="5"/>')
    assert shape.geometry.bounds == pytest.approx((5, 5, 25, 25), abs=1e-6)
    shape = one('<symbol id="s" viewBox="2 2 10 10"><rect x="2" y="2" width="10" height="10"/></symbol><use href="#s" width="10" height="10"/>')
    assert shape.geometry.bounds == pytest.approx((0, 0, 10, 10), abs=1e-6)


def test_a_symbol_is_cut_at_its_viewport_and_only_drawn_by_a_use():
    shape = one('<symbol id="s" viewBox="0 0 10 10"><rect width="20" height="20"/></symbol><use href="#s" width="10" height="10"/>')
    assert shape.geometry.bounds == pytest.approx((0, 0, 10, 10), abs=1e-6)
    assert read('<symbol id="s"><rect width="10" height="10"/></symbol>').shapes == []
    loose = one('<symbol id="s"><rect width="10" height="10"/></symbol><use href="#s" x="5"/>')
    assert loose.geometry.bounds == pytest.approx((5, 0, 15, 10), abs=1e-6)


def test_a_nested_svg_has_its_own_viewport():
    shape = one('<svg x="10" y="10" width="20" height="20" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
    assert shape.geometry.bounds == pytest.approx((10, 10, 30, 30), abs=1e-6)
    cut = one('<svg x="10" y="10" width="20" height="20"><rect width="100" height="100"/></svg>')
    assert cut.geometry.bounds == pytest.approx((10, 10, 30, 30), abs=1e-6)
    visible = one('<svg x="10" y="10" width="20" height="20" overflow="visible"><rect width="100" height="100"/></svg>')
    assert visible.geometry.bounds == pytest.approx((10, 10, 110, 110), abs=1e-6)


def test_percentages_refer_to_the_viewport():
    assert one('<rect width="50%" height="10%"/>').geometry.bounds == pytest.approx((0, 0, 50, 10), abs=1e-6)


def test_a_reference_in_a_circle_does_no_harm():
    assert read('<g id="a"><use href="#a"/></g>').shapes == []
    assert read('<g id="a"><use href="#b"/></g><g id="b"><use href="#a"/><rect width="5" height="5"/></g>').shapes != []   # drawn once each, no loop


def test_a_use_that_multiplies_itself_is_refused(monkeypatch):
    monkeypatch.setattr(sv, "MAX_NODES", 5000)
    body = '<defs><rect id="l0" width="1" height="1"/>' + "".join(
        f'<g id="l{i}">' + f'<use href="#l{i - 1}"/>' * 10 + "</g>" for i in range(1, 8)) + '</defs><use href="#l7"/>'
    with pytest.raises(su.ValidationError, match="too complex"):
        read(body)


def test_missing_references_are_counted():
    parsed = read('<use href="#nothing"/><use href="other.svg#x"/>%s' % SQUARE)
    assert parsed.notes == ["2 references to objects that are not in the file were skipped."]
    assert read('<use href="#nothing"/>%s' % SQUARE).notes == ["1 reference to an object that is not in the file was skipped."]


def test_switch_shows_its_first_child_that_can_be_shown():
    body = ('<switch><foreignObject requiredExtensions="http://ns.adobe.com/AdobeIllustrator/10.0/"><x/></foreignObject>'
            '<g><rect width="5" height="5"/></g><rect x="50" width="5" height="5"/></switch>')
    assert [s.geometry.bounds[0] for s in read(body).shapes] == [0.0]
    german = '<switch><rect systemLanguage="de" width="5" height="5"/><rect systemLanguage="en-US" x="9" width="5" height="5"/></switch>'
    assert [s.geometry.bounds[0] for s in read(german).shapes] == [9.0]


# -- clipping -----------------------------------------------------------------------------------------------------------------------------
CLIP = '<clipPath id="c"><rect x="0" y="0" width="5" height="10"/></clipPath>'


def test_clip_path_cuts_the_shape_and_the_clip_itself_is_not_drawn():
    shape = one(f'{CLIP}<rect width="10" height="10" clip-path="url(#c)"/>')
    assert shape.geometry.bounds == pytest.approx((0, 0, 5, 10), abs=1e-6) and near(shape.geometry.area, 50)
    assert one(f'{CLIP}<rect width="10" height="10" style="clip-path:url(#c)"/>').geometry.area == pytest.approx(50)


def test_clip_path_of_a_group_cuts_all_its_shapes_and_strokes():
    parsed = read(f'{CLIP}<g clip-path="url(#c)"><rect width="10" height="10" fill="#f00" stroke="#00f" stroke-width="2"/><circle cx="2" cy="5" r="2"/></g>')
    assert all(s.geometry.bounds[2] <= 5 + 1e-9 for s in parsed.shapes) and len(parsed.shapes) == 3


def test_the_clip_is_in_the_user_space_of_the_element_that_names_it():
    shape = one(f'{CLIP}<rect width="10" height="10" transform="translate(20 0)" clip-path="url(#c)"/>')
    assert shape.geometry.bounds == pytest.approx((20, 0, 25, 10), abs=1e-6)
    shape = one(f'{CLIP}<g transform="scale(2)"><rect width="10" height="10" clip-path="url(#c)"/></g>')
    assert shape.geometry.bounds == pytest.approx((0, 0, 10, 20), abs=1e-6)


def test_a_clip_made_of_a_circle_or_of_a_use_with_a_transform():
    clip = '<clipPath id="c"><circle cx="5" cy="5" r="5"/></clipPath>'
    assert one(f'{clip}<rect width="10" height="10" clip-path="url(#c)"/>').geometry.area == pytest.approx(math.pi * 25, rel=0.01)
    via_use = '<defs><rect id="r" width="5" height="10"/></defs><clipPath id="c"><use href="#r" x="5"/></clipPath>'
    assert one(f'{via_use}<rect width="10" height="10" clip-path="url(#c)"/>').geometry.bounds == pytest.approx((5, 0, 10, 10), abs=1e-6)
    moved = '<clipPath id="c" transform="translate(5 0)"><rect width="5" height="10"/></clipPath>'
    assert one(f'{moved}<rect width="10" height="10" clip-path="url(#c)"/>').geometry.bounds == pytest.approx((5, 0, 10, 10), abs=1e-6)


def test_clip_path_in_object_bounding_box_units():
    clip = '<clipPath id="c" clipPathUnits="objectBoundingBox"><rect width="0.5" height="1"/></clipPath>'
    shape = one(f'{clip}<rect x="20" y="20" width="10" height="10" clip-path="url(#c)"/>')
    assert shape.geometry.bounds == pytest.approx((20, 20, 25, 30), abs=1e-6)
    group = read(f'{clip}<g clip-path="url(#c)"><rect x="20" y="20" width="10" height="10"/><rect x="40" y="20" width="20" height="10"/></g>')
    assert [s.geometry.bounds for s in group.shapes] == [pytest.approx((20, 20, 30, 30), abs=1e-6)]      # the box is x 20..60: its left half ends at 40
    turned = one(f'{clip}<rect width="10" height="10" transform="translate(50 0) rotate(90)" clip-path="url(#c)"/>')
    assert near(turned.geometry.area, 50)                                                      # the box is measured before the rotation


def test_an_empty_clip_hides_everything_and_a_missing_one_hides_nothing():
    assert read('<clipPath id="c"/><rect width="10" height="10" clip-path="url(#c)"/>').shapes == []
    assert len(read('<rect width="10" height="10" clip-path="url(#nothing)"/>').shapes) == 1
    assert len(read('<rect id="r" width="10" height="10"/><rect width="10" height="10" clip-path="url(#r)"/>').shapes) == 2


def test_clips_are_intersected_down_the_tree():
    two = f'{CLIP}<clipPath id="d"><rect x="0" y="0" width="10" height="4"/></clipPath>'
    shape = one(f'{two}<g clip-path="url(#c)"><rect width="10" height="10" clip-path="url(#d)"/></g>')
    assert near(shape.geometry.area, 5 * 4)


def test_the_clip_rule_of_the_clip_path():
    rings = "M0 0H10V10H0ZM2 2H8V8H2Z"                    # the inner ring runs the same way as the outer
    even = one(f'<clipPath id="c"><path d="{rings}" clip-rule="evenodd"/></clipPath><rect width="10" height="10" clip-path="url(#c)"/>')
    plain = one(f'<clipPath id="c"><path d="{rings}"/></clipPath><rect width="10" height="10" clip-path="url(#c)"/>')
    inherited = one(f'<clipPath id="c" clip-rule="evenodd"><path d="{rings}"/></clipPath><rect width="10" height="10" clip-path="url(#c)"/>')
    assert near(plain.geometry.area, 100) and near(even.geometry.area, 64) and near(inherited.geometry.area, 64)


# -- gradients and patterns ---------------------------------------------------------------------------------------------------------------
def test_a_gradient_is_the_average_colour_of_its_stops_and_counted_once():
    grad = '<linearGradient id="g"><stop offset="0" stop-color="#000000"/><stop offset="1" stop-color="#ffffff"/></linearGradient>'
    parsed = read(f'<defs>{grad}</defs><rect width="5" height="5" fill="url(#g)"/>')
    assert parsed.shapes[0].fill == "#808080"
    assert parsed.notes == ["1 gradient fill was replaced by its average colour."]
    two = read(f'<defs>{grad}</defs><rect width="5" height="5" fill="url(#g)"/><circle cx="20" cy="20" r="3" style="fill:url(#g)"/>')
    assert [s.fill for s in two.shapes] == ["#808080", "#808080"]
    assert two.notes == ["2 gradient fills were replaced by their average colour."]


def test_a_radial_gradient_and_stops_of_a_gradient_it_points_to():
    parsed = read('<defs><linearGradient id="a" xlink:href="#b"/><radialGradient id="b"><stop offset="0" stop-color="red"/>'
                  '<stop offset="1" stop-color="blue"/></radialGradient></defs><rect width="5" height="5" fill="url(#a)"/>')
    assert parsed.shapes[0].fill == "#800080"


def test_the_average_is_taken_over_the_gradient_not_over_the_stops():
    grad = ('<linearGradient id="g"><stop offset="0" stop-color="#000"/><stop offset="0.5" stop-color="#000"/>'
            '<stop offset="100%" stop-color="#fff"/></linearGradient>')
    assert one(f'{grad}<rect width="5" height="5" fill="url(#g)"/>').fill == "#404040"


def test_stop_opacity_and_stops_styled_by_a_sheet_or_an_attribute():
    parsed = read('<style>.s{stop-color:#ff0000}</style><linearGradient id="a"><stop class="s" stop-opacity="0.5"/></linearGradient>'
                  '<linearGradient id="b"><stop style="stop-color:rgb(0,0,255);stop-opacity:0.5" offset="0.3"/></linearGradient>'
                  '<rect width="5" height="5" fill="url(#a)"/><rect x="10" width="5" height="5" fill="url(#b)"/>')
    assert [s.fill for s in parsed.shapes] == ["#ff8080", "#8080ff"]


def test_a_gradient_without_stops_paints_nothing_and_a_gradient_stroke_is_counted():
    assert read('<linearGradient id="g"/><rect width="5" height="5" fill="url(#g)"/>').shapes == []
    grad = '<linearGradient id="g"><stop stop-color="#00f"/></linearGradient>'
    parsed = read(f'{grad}<line x2="10" y1="5" y2="5" stroke="url(#g)" stroke-width="2"/>')
    assert parsed.shapes[0].fill == "#0000ff" and parsed.notes == ["1 gradient fill was replaced by its average colour."]


def test_a_pattern_fill_is_skipped_and_counted():
    pattern = '<pattern id="p" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="2" height="2"/></pattern>'
    parsed = read(f'<defs>{pattern}</defs><rect width="5" height="5" fill="url(#p)"/>%s' % SQUARE)
    assert len(parsed.shapes) == 1
    assert parsed.notes == ["1 pattern fill was not imported: patterns cannot be carried over."]
    kept = read(f'<defs>{pattern}</defs><rect width="5" height="5" fill="url(#p)" stroke="#f00" stroke-width="1"/>')
    assert [s.fill for s in kept.shapes] == ["#ff0000"]


# -- what is counted ----------------------------------------------------------------------------------------------------------------------
def test_text_is_counted_by_the_text_object():
    parsed = read('<text x="1" y="5">A</text><text><tspan>B</tspan><tspan>C</tspan></text><text><textPath href="#p">D</textPath></text>%s' % SQUARE)
    assert parsed.notes == ["3 text objects were not imported: convert the text to outlines in the program that made the file."]
    assert read('<text>A</text>%s' % SQUARE).notes == ["1 text object was not imported: convert the text to outlines in the program that made the file."]
    assert read('<text>  </text><defs><text>A</text></defs>%s' % SQUARE).notes == []


def test_pictures_masks_filters_and_markers_are_counted():
    parsed = read('<image href="data:image/png;base64,AAAA" width="10" height="10"/><image xlink:href="photo.png"/>'
                  '<mask id="m"/><filter id="f"/><rect width="5" height="5" mask="url(#m)"/><g style="filter:url(#f)"><circle cx="20" cy="20" r="4"/></g>'
                  '<defs><marker id="k"/></defs><path d="M0 0L10 10" marker-end="url(#k)" stroke="#000"/>')
    assert parsed.notes == ["2 pictures were not imported: only vector drawings can be carried over, not embedded or linked images.",
                            "Masks and filters are not applied: 2 objects were drawn without their mask or filter.",
                            "1 line end marker (an arrowhead or similar) was not drawn."]
    assert len(parsed.shapes) == 3 and not any(s.geometry.is_empty for s in parsed.shapes)      # the masked shapes are drawn plain


def test_nothing_lost_means_no_note_and_unknown_elements_are_ignored():
    body = ('<sodipodi:namedview xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" id="nv"/><title>t</title><desc>d</desc>'
            '<metadata><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></metadata><foo:bar xmlns:foo="urn:x"><rect/></foo:bar>'
            '<unknown><rect width="9" height="9"/></unknown>' + SQUARE)
    parsed = read(body)
    assert parsed.notes == [] and len(parsed.shapes) == 1


def test_a_file_with_nothing_to_import_says_so():
    for body in ["", "<text>A</text>"]:
        parsed = read(body)
        assert parsed.shapes == [] and parsed.notes[-1] == "The file contains no vector drawing that can be imported."


# -- files that are refused or odd ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("data", [b"", b"hello", b"<svg", b"<svg xmlns='http://www.w3.org/2000/svg'><g></svg>", b"\x00\x01\x02\xff", b"<<<>>>",
                                  b"PK\x03\x04 a zip", None, 5, "not xml"])
def test_files_that_are_not_xml_are_refused_with_a_message(data):
    with pytest.raises(su.ValidationError) as caught:
        sv.parse(data)
    assert str(caught.value)


@pytest.mark.parametrize("data", [b"<html><body><svg xmlns='http://www.w3.org/2000/svg'/></body></html>", b"<g xmlns='http://www.w3.org/2000/svg'/>",
                                  b"<svg xmlns='http://example.com/other'><rect/></svg>", b"<?xml version='1.0'?><root/>"])
def test_xml_without_an_svg_root_is_refused(data):
    with pytest.raises(su.ValidationError, match="svg"):
        sv.parse(data)


BILLION_LAUGHS = b"""<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><svg xmlns="http://www.w3.org/2000/svg"><text>&c;</text></svg>"""
EXTERNAL = b"""<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg"><text>&xxe;</text></svg>"""


@pytest.mark.parametrize("data", [BILLION_LAUGHS, EXTERNAL, EXTERNAL.replace(b"ENTITY", b"entity"), b"\xef\xbb\xbf" + EXTERNAL,
                                  EXTERNAL.replace(b'SYSTEM "file:///etc/passwd"', b'"x"'), EXTERNAL.replace(b"ENTITY xxe", b"ENTITY % xxe")])
def test_entity_declarations_are_refused_before_parsing(data):
    with pytest.raises(su.ValidationError, match="entities"):
        sv.parse(data)


def test_a_doctype_without_entities_is_fine():
    data = (b'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'
            b'<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"><rect width="5" height="5"/></svg>')
    assert len(sv.parse(data).shapes) == 1


def test_a_byte_order_mark_utf16_and_gzip_are_read():
    plain = doc('<rect width="5" height="5" fill="#f00"/>')
    for data in (b"\xef\xbb\xbf" + plain, ('<?xml version="1.0" encoding="UTF-16"?>' + plain.decode()).encode("utf-16"), gzip.compress(plain)):
        parsed = sv.parse(data)
        assert [s.fill for s in parsed.shapes] == ["#ff0000"]
    with pytest.raises(su.ValidationError):
        sv.parse(b"\x1f\x8b broken")


def test_utf8_text_and_ids_are_kept():
    shape = one('<rect id="café ☃" width="5" height="5"/>')
    assert shape.name == "café ☃"


def test_too_many_elements_are_refused(monkeypatch):
    monkeypatch.setattr(sv, "MAX_ELEMENTS", 50)
    with pytest.raises(su.ValidationError, match="too complex"):
        read(SQUARE * 100)
    assert len(read(SQUARE * 40).shapes) == 40


def test_too_many_vertices_are_refused(monkeypatch):
    monkeypatch.setattr(sv, "MAX_VERTICES", 100)
    with pytest.raises(su.ValidationError, match="too complex"):
        read('<circle cx="50" cy="50" r="40"/><circle cx="50" cy="50" r="30"/><circle cx="50" cy="50" r="20"/>')


def test_nesting_too_deep_is_refused_not_a_recursion_error():
    for depth in (150, 5000):
        with pytest.raises(su.ValidationError, match="too complex"):
            read("<g>" * depth + SQUARE + "</g>" * depth)
    assert len(read("<g>" * 50 + SQUARE + "</g>" * 50).shapes) == 1


def test_the_time_limit_is_a_refusal(monkeypatch):
    monkeypatch.setattr(sv, "MAX_SECONDS", -1.0)
    with pytest.raises(su.ValidationError, match="takes too long"):
        read(SQUARE * 2000)


@pytest.mark.parametrize("body", [
    '<rect width="1e308" height="1e308"/>', '<rect x="-1e308" width="1e308" height="5" stroke="#000" stroke-width="1e308"/>',
    '<path d="M0 0L1e308 1e308L-1e308 5Z" stroke="#000"/>', '<circle r="1e300" stroke="#000"/>', '<path d="M0 0A1e-300 1e300 0 1 1 1e300 0Z"/>',
    '<path d="M0 0C1e8 1e8 -1e8 1e8 5 5Z"/>', '<g transform="scale(0)">%s</g>' % SQUARE, '<g transform="matrix(1e300 0 0 1e300 0 0)">%s</g>' % SQUARE,
    '<polygon points="a,b c,d"/>', '<rect width="NaN" height="inf"/>', '<line x2="1e999"/>', '<ellipse cx="1" cy="1e999" rx="2" ry="2"/>',
    '<g transform="rotate(1e999)">%s</g>' % SQUARE, '<polygon points="1e999,0 5,5 9,0"/>', '<circle r="5" stroke="#000" stroke-miterlimit="1e999"/>',
    '<clipPath id="c"><rect width="5" height="5" transform="rotate(1e999)"/></clipPath><rect width="9" height="9" clip-path="url(#c)"/>', '<path d="M 0 0 L 5 5 5 5 5 5 Z" stroke="#000" stroke-linejoin="round"/>',
    '<path d="M1 1Z" stroke="#000" stroke-linecap="round"/>', '<path d="M1 1L1 1" stroke="#000" stroke-linecap="round"/>',
])
def test_extreme_input_never_raises_anything_but_a_validation_error(body):
    try:
        parsed = read(body)
    except su.ValidationError:
        return
    assert isinstance(parsed, Parsed)
    for shape in parsed.shapes:
        assert not shape.geometry.is_empty and shape.geometry.is_valid


def tangled_path(points: int, seed: int = 1) -> str:
    """One outline that crosses itself over and over (a random walk): the input that makes the geometry library slow."""
    rng = __import__("random").Random(seed)
    x = y = 50.0
    out = []
    for _ in range(points):
        x, y = x + rng.uniform(-1, 1), y + rng.uniform(-1, 1)
        out.append("%.2f %.2f" % (x, y))
    return "M" + " L".join(out) + "z"


def test_a_long_outline_that_crosses_itself_is_left_out_and_counted():
    start = time.perf_counter()
    parsed = read(f'<path d="{tangled_path(30000)}"/>{SQUARE}')
    assert time.perf_counter() - start < 5                                       # made valid it would take minutes
    assert len(parsed.shapes) == 1
    assert parsed.notes == ["1 outline was left out: it crosses itself too many times to be imported."]
    assert len(read(f'<path d="{tangled_path(600)}"/>').shapes) == 1             # a short one is made into geometry as usual
    assert len(read(f'<path d="{tangled_path(3000)}"/>').shapes) == 1            # and so is one of a few thousand points


def test_the_budget_for_outlines_that_cross_themselves_is_spent_over_the_file(monkeypatch):
    monkeypatch.setattr(sv, "MAX_TANGLED_TOTAL", 3000)
    parsed = read("".join(f'<path d="{tangled_path(1500, seed)}" fill="#00f"/>' for seed in (1, 2, 3)))
    assert len(parsed.shapes) == 2 and parsed.notes == ["1 outline was left out: it crosses itself too many times to be imported."]
    monkeypatch.setattr(sv, "MAX_TANGLED_RING", 1000)
    stroked = read(f'<path d="{tangled_path(8000)}" fill="none" stroke="#000"/>')        # a stroke weighs a quarter of a fill: 2000 > 1000
    assert stroked.shapes == [] and stroked.notes[0].startswith("1 outline was left out")


def test_a_zero_length_round_cap_is_a_dot():
    assert near(one('<path d="M20 20L20 20" stroke="#000" stroke-width="2" stroke-linecap="round"/>').geometry.area, math.pi, 0.05)


# -- size and speed -----------------------------------------------------------------------------------------------------------------------
def test_many_shapes_are_read_in_seconds():
    rects = "".join(f'<rect x="{i % 60}" y="{i // 60}" width="0.5" height="0.5" fill="#{(i * 37) % 4096:03x}"/>' for i in range(3000))
    start = time.perf_counter()
    parsed = read(rects)
    assert len(parsed.shapes) == 3000 and time.perf_counter() - start < 10


def test_a_file_of_a_megabyte_and_a_half_is_read_in_seconds():
    rng = __import__("random").Random(3)
    paths = []
    for i in range(500):                              # wobbly closed outlines of 200 points each, none crossing itself
        cx, cy, radius = rng.uniform(10, 90), rng.uniform(10, 90), rng.uniform(1, 6)
        points = []
        for k in range(200):
            angle = 2 * math.pi * k / 200
            r = radius * (1 + 0.3 * math.sin(5 * angle) + 0.05 * rng.random())
            points.append("%.4f %.4f" % (cx + r * math.cos(angle), cy + r * math.sin(angle)))
        d = "M" + points[0] + "".join(" Q" + points[k] + " " + points[k + 1] for k in range(1, 199, 2)) + "L" + points[-1] + "z"
        paths.append(f'<path d="{d}" fill="#{rng.randrange(1 << 24):06x}" stroke="#000" stroke-width="0.1"/>')
    data = doc("".join(paths))
    assert len(data) > 1_000_000
    start = time.perf_counter()
    parsed = sv.parse(data)
    assert len(parsed.shapes) == 1000 and time.perf_counter() - start < 10


def test_a_style_sheet_with_many_rules_stays_fast():
    rules = "".join(f".c{i}{{fill:#{i % 4096:03x}}}" for i in range(2000))
    rects = "".join(f'<rect class="c{i % 2000}" x="{i % 90}" y="{i // 90}" width="0.5" height="0.5"/>' for i in range(2000))
    start = time.perf_counter()
    parsed = read(f"<style>{rules}</style>{rects}")
    assert len(parsed.shapes) == 2000 and time.perf_counter() - start < 10
    assert parsed.shapes[1].fill == "#000011"
