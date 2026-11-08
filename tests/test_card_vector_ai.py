"""The Illustrator reader (card_vector_ai): synthetic PDF files built here, from content-stream text, in every way a file is laid out
(classic cross-reference, cross-reference stream with an object stream, damaged cross-reference, incremental update, compressed content).

The expected numbers are worked out by hand from the PDF operators: a 72 x 72 pt page is 25.4 mm square, so one point is 25.4 / 72 mm and
a rectangle at known point coordinates has exact bounds in millimetres (y pointing down)."""
from __future__ import annotations

import random
import time
import zlib

import pytest

from titanium_platform import card_vector_ai as ai
from titanium_platform import card_vector_geometry as geo
from titanium_platform.setup import ValidationError

PT = 25.4 / 72.0                         # millimetres in a point
VARIANTS = ("classic", "xrefstream", "bad_startxref", "bad_offsets", "no_xref", "flate")


# -- a small PDF writer --------------------------------------------------------------------------------------------------------------------
def _compress_zeros(size: int) -> bytes:
    compressor = zlib.compressobj(1)
    out = []
    block = bytes(1 << 20)
    for _ in range(size >> 20):
        out.append(compressor.compress(block))
    out.append(compressor.flush())
    return b"".join(out)


def lzw_encode(data: bytes) -> bytes:
    """LZW as PDF writes it (early change): a clear code first, nine bits at first, ten, eleven and twelve as the table grows. The data must
    be short enough not to fill the table."""
    table = {bytes([i]): i for i in range(256)}
    bits, entries, width = [format(256, "09b")], 258, 9
    word = b""
    for byte in data:
        extended = word + bytes([byte])
        if extended in table:
            word = extended
            continue
        bits.append(format(table[word], f"0{width}b"))
        table[extended] = entries
        entries += 1
        width = 9 if entries < 512 else 10 if entries < 1024 else 11 if entries < 2048 else 12
        word = bytes([byte])
    assert entries < 4000
    if word:
        bits.append(format(table[word], f"0{width}b"))
        entries += 1                                                    # the reader adds an entry for this code too
        width = 9 if entries < 512 else 10 if entries < 1024 else 11 if entries < 2048 else 12
    bits.append(format(257, f"0{width}b"))
    text = "".join(bits)
    text += "0" * (-len(text) % 8)
    return int(text, 2).to_bytes(len(text) // 8, "big")


class Pdf:
    """Objects 1..4 are the catalogue, the page tree, the first page and its content; ``add`` hands out the numbers from 5 on."""

    def __init__(self):
        self.objects: dict[int, tuple[bytes, bytes | None]] = {}
        self.next_num = 5

    def add(self, body: str | bytes) -> int:
        num, self.next_num = self.next_num, self.next_num + 1
        self.objects[num] = (body.encode() if isinstance(body, str) else body, None)
        return num

    def add_stream(self, data: bytes, entries: str = "", flate: bool = False) -> int:
        num, self.next_num = self.next_num, self.next_num + 1
        if flate:
            data, entries = zlib.compress(data), entries + " /Filter /FlateDecode"
        self.objects[num] = (entries.encode(), data)
        return num

    # -- serialising ---------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _object(num: int, text: bytes, data: bytes | None, length: str | None = None) -> bytes:
        if data is None:
            return b"%d 0 obj\n%s\nendobj\n" % (num, text)
        size = length or str(len(data))
        return b"%d 0 obj\n<< %s /Length %s >>\nstream\n%s\nendstream\nendobj\n" % (num, text, size.encode(), data)

    def build(self, content: str | bytes, *, resources: str = "", media: str = "[0 0 72 72]", rotate: int | None = None,
              user_unit: float | None = None, catalog: str = "", variant: str = "classic", pages: int = 1, page_extra: str = "",
              contents_entries: str = "", contents_data: bytes | None = None, header: bytes = b"%PDF-1.4\n", prefix: bytes = b"",
              trailer: str = "") -> bytes:
        content = content.encode() if isinstance(content, str) else content
        objects = dict(self.objects)
        entries, data = contents_entries, content if contents_data is None else contents_data
        if variant == "flate":
            data, entries = zlib.compress(content), entries + " /Filter /FlateDecode"
        extra = (f" /Rotate {rotate}" if rotate is not None else "") + (f" /UserUnit {user_unit}" if user_unit else "") + page_extra
        kids = ["3 0 R"]
        objects[1] = (f"<< /Type /Catalog /Pages 2 0 R {catalog} >>".encode(), None)
        objects[3] = (f"<< /Type /Page /Parent 2 0 R /MediaBox {media} /Contents 4 0 R /Resources << {resources} >>{extra} >>".encode(), None)
        objects[4] = (entries.encode(), data)
        for i in range(1, pages):
            num = max(objects) + 1
            objects[num] = (f"<< /Type /Page /Parent 2 0 R /MediaBox {media} /Resources << >> >>".encode(), None)
            kids.append(f"{num} 0 R")
        objects[2] = (f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {pages} >>".encode(), None)
        if variant == "xrefstream":
            return prefix + self._with_xref_stream(objects, header, trailer)
        out = bytearray(header + b"%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        for num in sorted(objects):
            offsets[num] = len(out)
            out += self._object(num, *objects[num])
        if variant == "no_xref":
            return prefix + bytes(out)
        size = max(objects) + 1
        position = len(out)
        shift = 7 if variant == "bad_offsets" else 0
        table = b"xref\n0 %d\n0000000000 65535 f \n" % size
        for num in range(1, size):
            table += (b"%010d 00000 n \n" % (offsets[num] + shift)) if num in offsets else b"0000000000 00000 f \n"
        start = 12345 if variant == "bad_startxref" else position
        out += table + b"trailer\n<< /Size %d /Root 1 0 R %s >>\nstartxref\n%d\n%%%%EOF\n" % (size, trailer.encode(), start)
        return prefix + bytes(out)

    def _with_xref_stream(self, objects: dict[int, tuple[bytes, bytes | None]], header: bytes, trailer: str = "") -> bytes:
        plain = sorted(num for num, (_, data) in objects.items() if data is None)
        streams = sorted(num for num, (_, data) in objects.items() if data is not None)
        stream_num, xref_num = max(objects) + 1, max(objects) + 2
        head, body = b"", b""
        for num in plain:
            head += b"%d %d " % (num, len(body))
            body += objects[num][0] + b" "
        packed = zlib.compress(head + body)
        out = bytearray(header + b"%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        for num in streams:
            offsets[num] = len(out)
            out += self._object(num, *objects[num])
        offsets[stream_num] = len(out)
        out += self._object(stream_num, b"/Type /ObjStm /N %d /First %d /Filter /FlateDecode" % (len(plain), len(head)), packed)
        offsets[xref_num] = position = len(out)
        rows = []
        for num in range(xref_num + 1):
            if num in offsets:
                rows.append(bytes([1]) + offsets[num].to_bytes(4, "big") + bytes(2))
            elif num in plain:
                rows.append(bytes([2]) + stream_num.to_bytes(4, "big") + plain.index(num).to_bytes(2, "big"))
            else:
                rows.append(bytes([0]) + bytes(6))
        previous, encoded = bytes(7), b""
        for row in rows:                                                # the PNG "up" predictor, as real writers use it
            encoded += bytes([2]) + bytes((a - b) & 255 for a, b in zip(row, previous))
            previous = row
        entries = (b"/Type /XRef /Size %d /W [1 4 2] /Root 1 0 R %s /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 7 >>"
                   % (xref_num + 1, trailer.encode()))
        out += self._object(xref_num, entries, zlib.compress(encoded))
        out += b"startxref\n%d\n%%%%EOF\n" % position
        return bytes(out)


def make(content: str | bytes, **kw) -> bytes:
    return Pdf().build(content, **kw)


def read(content: str | bytes, **kw):
    return ai.parse(make(content, **kw))


def area(shapes) -> float:
    return sum(s.geometry.area for s in shapes)


def bounds(shape) -> tuple[float, float, float, float]:
    return shape.geometry.bounds


def pt_box(x0: float, y0: float, x1: float, y1: float, height: float = 72.0) -> tuple[float, float, float, float]:
    """Millimetre bounds of a rectangle given in points on a page ``height`` points high (y up there, y down here)."""
    return (x0 * PT, (height - y1) * PT, x1 * PT, (height - y0) * PT)


# -- fills, colours, coordinates -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("variant", VARIANTS)
def test_a_filled_rectangle_in_millimetres_with_y_flipped_in_every_file_layout(variant):
    parsed = read("0 0 1 rg 10 20 30 40 re f", variant=variant)
    assert parsed.kind == "ai" and parsed.notes == []
    assert len(parsed.shapes) == 1
    shape = parsed.shapes[0]
    assert shape.fill == "#0000ff" and shape.name is None
    assert bounds(shape) == pytest.approx(pt_box(10, 20, 40, 60), abs=1e-9)
    assert shape.geometry.area == pytest.approx(30 * 40 * PT * PT)


@pytest.mark.parametrize("operators, colour", [
    ("1 0 0 rg", "#ff0000"), ("0.2 0.4 0.6 rg", "#336699"), ("0 g", "#000000"), ("1 g", "#ffffff"), ("0.5 g", "#808080"),
    ("0 0 0 1 k", "#000000"), ("0 1 1 0 k", "#ff0000"), ("1 0 0 0 k", "#00ffff"), ("0.2 0.4 0.6 0.1 k", "#b88a5c"),
    ("0 0 0 0 k", "#ffffff")])
def test_device_colours_give_the_exact_design_colour(operators, colour):
    assert read(f"{operators} 0 0 10 10 re f").shapes[0].fill == colour


def test_the_default_fill_is_black_and_stroke_colours_are_separate():
    parsed = read("0 0 10 10 re f 1 0 0 RG 1 w 20 20 10 10 re S")
    assert [s.fill for s in parsed.shapes] == ["#000000", "#ff0000"]


def test_shapes_come_in_painting_order_one_per_painting_operation():
    parsed = read("1 0 0 rg 0 0 10 10 re f 0 1 0 rg 5 5 10 10 re f 0 0 1 rg 10 10 10 10 re f")
    assert [s.fill for s in parsed.shapes] == ["#ff0000", "#00ff00", "#0000ff"]


def test_a_painting_operation_with_several_subpaths_is_one_shape():
    parsed = read("0 0 10 10 re 20 20 10 10 re f")
    assert len(parsed.shapes) == 1 and parsed.shapes[0].geometry.geom_type == "MultiPolygon"


@pytest.mark.parametrize("operator", ["f", "F", "f*"])
def test_every_fill_operator_paints(operator):
    assert len(read(f"0 0 10 10 re {operator}").shapes) == 1


def test_a_path_that_is_not_painted_makes_no_shape():
    assert read("0 0 10 10 re n 0 0 10 10 re").shapes == []


def test_open_subpaths_are_closed_for_filling():
    parsed = read("0 0 m 20 0 l 20 10 l f")
    assert area(parsed.shapes) == pytest.approx(0.5 * 20 * 10 * PT * PT)


def test_h_closes_a_subpath_and_a_following_line_starts_from_its_start():
    parsed = read("10 10 m 20 10 l 20 20 l h 30 30 l 40 30 l 40 40 l h f")
    assert area(parsed.shapes) == pytest.approx((50 + 50) * PT * PT)


def test_zero_area_paths_are_dropped_silently():
    parsed = read("0 0 m 10 0 l 20 0 l f 5 5 0 0 re f")
    assert parsed.shapes == [] and parsed.notes == []


# -- the matrix, q and Q -------------------------------------------------------------------------------------------------------------------
def test_cm_scales_and_translates_and_q_restores_the_state():
    parsed = read("q 2 0 0 2 10 10 cm 1 0 0 rg 0 0 10 10 re f Q 0 0 5 5 re f")
    first, second = parsed.shapes
    assert first.fill == "#ff0000" and bounds(first) == pytest.approx(pt_box(10, 10, 30, 30), abs=1e-9)
    assert second.fill == "#000000" and bounds(second) == pytest.approx(pt_box(0, 0, 5, 5), abs=1e-9)


def test_nested_q_and_cm_compose_in_the_right_order():
    parsed = read("q 1 0 0 1 10 0 cm q 2 0 0 2 0 0 cm 0 0 5 5 re f Q 0 0 5 5 re f Q 0 0 5 5 re f")
    assert [bounds(s) for s in parsed.shapes] == pytest.approx([pt_box(10, 0, 20, 10), pt_box(10, 0, 15, 5), pt_box(0, 0, 5, 5)], abs=1e-9)


def test_rotation_in_cm():
    parsed = read("0 1 -1 0 40 0 cm 0 0 10 20 re f")                    # 90 degrees counter-clockwise: x -> -y, y -> x
    assert bounds(parsed.shapes[0]) == pytest.approx(pt_box(20, 0, 40, 10), abs=1e-9)


def test_unbalanced_Q_is_ignored_and_a_missing_Q_does_no_harm():
    parsed = read("Q Q q q 1 0 0 rg 0 0 10 10 re f")
    assert len(parsed.shapes) == 1


# -- the page: box, rotation, units --------------------------------------------------------------------------------------------------------
def test_a_media_box_that_does_not_start_at_the_origin():
    parsed = read("10 20 10 10 re f", media="[10 20 110 70]")
    assert bounds(parsed.shapes[0]) == pytest.approx((0.0, 40 * PT, 10 * PT, 50 * PT), abs=1e-9)


def test_a_media_box_with_corners_that_are_not_normalised():
    parsed = read("10 20 10 10 re f", media="[110 70 10 20]")
    assert bounds(parsed.shapes[0]) == pytest.approx((0.0, 40 * PT, 10 * PT, 50 * PT), abs=1e-9)


@pytest.mark.parametrize("rotate, expected", [
    (0, (0, 30, 10, 50)), (90, (0, 0, 20, 10)), (180, (90, 0, 100, 20)), (270, (30, 90, 50, 100)), (360, (0, 30, 10, 50)),
    (-90, (30, 90, 50, 100))])
def test_page_rotation_turns_the_page_as_it_is_shown(rotate, expected):
    # a page 100 x 50 pt, a rectangle 10 x 20 pt in its bottom-left corner
    parsed = read("0 0 10 20 re f", media="[0 0 100 50]", rotate=rotate)
    assert bounds(parsed.shapes[0]) == pytest.approx(tuple(v * PT for v in expected), abs=1e-9)


def test_rotation_by_90_puts_the_bottom_left_corner_at_the_top_left():
    parsed = read("0 0 10 20 re f", media="[0 0 100 50]", rotate=90)
    assert bounds(parsed.shapes[0]) == pytest.approx((0.0, 0.0, 20 * PT, 10 * PT), abs=1e-9)


def test_user_unit_scales_the_page():
    parsed = read("10 20 30 40 re f", user_unit=2)
    assert bounds(parsed.shapes[0]) == pytest.approx(tuple(v * 2 for v in pt_box(10, 20, 40, 60)), abs=1e-9)


def test_a_missing_media_box_is_a_letter_page():
    data = make("0 0 10 10 re f", media="[0 0 612 792]").replace(b"/MediaBox [0 0 612 792]", b"/Mediabxx [0 0 612 792]")
    assert bounds(ai.parse(data).shapes[0]) == pytest.approx((0.0, 782 * PT, 10 * PT, 792 * PT), abs=1e-9)


def test_the_page_inherits_its_media_box_from_the_page_tree():
    pdf = Pdf()
    data = pdf.build("10 20 10 10 re f").replace(b"/MediaBox [0 0 72 72] /Contents", b"/Contents")
    data = data.replace(b"/Type /Pages", b"/Type /Pages /MediaBox [0 0 72 100]")
    assert bounds(ai.parse(data).shapes[0]) == pytest.approx(pt_box(10, 20, 20, 30, height=100), abs=1e-9)


# -- curves, fill rules, strokes ---------------------------------------------------------------------------------------------------------
K = 0.5522847498                         # the control-point distance of a quarter circle


def _circle(cx: float, cy: float, r: float) -> str:
    return (f"{cx + r} {cy} m {cx + r} {cy + K * r} {cx + K * r} {cy + r} {cx} {cy + r} c {cx - K * r} {cy + r} {cx - r} {cy + K * r} {cx - r} {cy} c "
            f"{cx - r} {cy - K * r} {cx - K * r} {cy - r} {cx} {cy - r} c {cx + K * r} {cy - r} {cx + r} {cy - K * r} {cx + r} {cy} c h")


def test_curves_are_flattened_into_a_polygon_with_the_area_of_the_circle():
    parsed = read(_circle(36, 36, 20) + " f")
    r = 20 * PT
    assert area(parsed.shapes) == pytest.approx(3.141592653589793 * r * r, rel=0.005)
    assert bounds(parsed.shapes[0]) == pytest.approx(pt_box(16, 16, 56, 56), abs=0.02)


def test_v_and_y_curves_are_the_cubic_with_one_control_point_repeated():
    v = read("0 0 m 20 20 30 0 v h f")                                # the first control point is the current point
    v_as_c = read("0 0 m 0 0 20 20 30 0 c h f")
    y = read("0 0 m 10 20 30 0 y h f")                                # the second control point is the end point
    y_as_c = read("0 0 m 10 20 30 0 30 0 c h f")
    assert area(v.shapes) > 0 and area(y.shapes) > 0
    assert v.shapes[0].geometry.symmetric_difference(v_as_c.shapes[0].geometry).area < 1e-9
    assert y.shapes[0].geometry.symmetric_difference(y_as_c.shapes[0].geometry).area < 1e-9


def test_a_curve_with_no_current_point_does_not_fail():
    assert read("1 2 3 4 5 6 c 10 10 20 20 re f").shapes


def test_even_odd_makes_a_hole_and_non_zero_fills_rings_that_run_the_same_way():
    outer, inner = "0 0 60 60 re ", "10 10 40 40 re "
    even = read(outer + inner + "f*")
    nonzero = read(outer + inner + "f")
    assert area(even.shapes) == pytest.approx((3600 - 1600) * PT * PT)
    assert area(nonzero.shapes) == pytest.approx(3600 * PT * PT)


def test_non_zero_makes_a_hole_with_a_ring_that_runs_the_other_way():
    outer, inner = "0 0 m 60 0 l 60 60 l 0 60 l h ", "10 10 m 10 50 l 50 50 l 50 10 l h "
    assert area(read(outer + inner + "f").shapes) == pytest.approx((3600 - 1600) * PT * PT)
    assert area(read(outer + inner + "f*").shapes) == pytest.approx((3600 - 1600) * PT * PT)


def test_a_stroke_covers_its_width_along_the_line():
    parsed = read("1 0 0 RG 4 w 10 36 m 62 36 l S")
    assert [s.fill for s in parsed.shapes] == ["#ff0000"]
    assert area(parsed.shapes) == pytest.approx(52 * 4 * PT * PT)
    assert bounds(parsed.shapes[0]) == pytest.approx(pt_box(10, 34, 62, 38), abs=1e-9)


def test_the_stroke_width_follows_the_matrix_scale():
    parsed = read("2 0 0 2 0 0 cm 1 w 5 10 m 25 10 l S")
    assert area(parsed.shapes) == pytest.approx(40 * 2 * PT * PT)


@pytest.mark.parametrize("cap, extra", [(0, 0), (2, 2 * 2)])
def test_line_caps(cap, extra):
    parsed = read(f"{cap} J 4 w 10 36 m 62 36 l S")
    assert area(parsed.shapes) == pytest.approx((52 * 4 + extra * 4) * PT * PT)


def test_round_joins_and_miter_joins_differ_at_a_corner():
    miter = read("0 j 10 w 10 10 m 40 10 l 40 40 l S")
    rounded = read("1 j 10 w 10 10 m 40 10 l 40 40 l S")
    assert area(miter.shapes) > area(rounded.shapes) > 0


def test_a_hairline_is_kept_as_a_thin_line():
    parsed = read("0 w 10 36 m 62 36 l S")
    assert len(parsed.shapes) == 1 and area(parsed.shapes) > 0


def test_closing_stroke_s_closes_the_path():
    open_ = read("2 w 10 10 m 40 10 l 40 40 l 10 40 l S")
    closed = read("2 w 10 10 m 40 10 l 40 40 l 10 40 l s")
    assert area(closed.shapes) > area(open_.shapes)


def test_B_makes_two_shapes_the_fill_and_then_the_stroke():
    parsed = read("1 0 0 rg 0 0 1 RG 2 w 10 10 40 40 re B")
    fill, line = parsed.shapes
    assert (fill.fill, line.fill) == ("#ff0000", "#0000ff")
    assert fill.geometry.area == pytest.approx(1600 * PT * PT)
    assert line.geometry.area == pytest.approx((42 * 42 - 38 * 38) * PT * PT)


@pytest.mark.parametrize("operator", ["B", "B*", "b", "b*"])
def test_every_fill_and_stroke_operator_makes_two_shapes(operator):
    assert len(read(f"2 w 10 10 40 40 re {operator}").shapes) == 2


def test_dashes_are_drawn_solid_and_counted_once():
    parsed = read("[3 2] 0 d 2 w 10 10 m 60 10 l S 10 20 m 60 20 l S [] 0 d 10 30 m 60 30 l S")
    assert len(parsed.shapes) == 3
    assert parsed.notes == ["2 dashed lines were drawn solid."]


def test_a_single_dash_is_said_in_the_singular():
    assert read("[3] 0 d 2 w 10 10 m 60 10 l S").notes == ["1 dashed line was drawn solid."]


# -- clipping --------------------------------------------------------------------------------------------------------------------------
def test_a_clip_rectangle_cuts_what_is_painted_after_it():
    parsed = read("q 0 0 36 72 re W n 0 0 1 rg 0 0 72 72 re f Q 1 0 0 rg 60 60 5 5 re f")
    blue, red = parsed.shapes
    assert bounds(blue) == pytest.approx(pt_box(0, 0, 36, 72), abs=1e-9)
    assert bounds(red) == pytest.approx(pt_box(60, 60, 65, 65), abs=1e-9)         # Q has restored the clip


def test_a_shape_inside_a_rectangular_clip_is_not_changed():
    parsed = read("0 0 72 72 re W n 10 10 20 20 re f")
    assert bounds(parsed.shapes[0]) == pytest.approx(pt_box(10, 10, 30, 30), abs=1e-9)


def test_a_shape_outside_the_clip_is_dropped():
    assert read("0 0 10 10 re W n 40 40 10 10 re f").shapes == []


def test_clips_intersect_each_other():
    parsed = read("0 0 40 72 re W n 20 0 40 72 re W n 0 0 72 72 re f")
    assert bounds(parsed.shapes[0]) == pytest.approx(pt_box(20, 0, 40, 72), abs=1e-9)


def test_a_non_rectangular_clip_cuts_to_its_outline():
    parsed = read("0 0 m 40 0 l 0 40 l h W n 0 0 72 72 re f")
    assert area(parsed.shapes) == pytest.approx(0.5 * 40 * 40 * PT * PT)


def test_a_curved_clip_and_the_even_odd_clip():
    circle = read(_circle(36, 36, 20) + " W n 0 0 72 72 re f")
    assert area(circle.shapes) == pytest.approx(3.14159265 * (20 * PT) ** 2, rel=0.01)
    ring = read("0 0 60 60 re 10 10 40 40 re W* n 0 0 72 72 re f")
    assert area(ring.shapes) == pytest.approx((3600 - 1600) * PT * PT)


def test_the_painting_operator_that_carries_W_is_not_clipped_by_it():
    parsed = read("0 0 10 10 re W f 20 20 10 10 re f")
    assert len(parsed.shapes) == 1 and bounds(parsed.shapes[0]) == pytest.approx(pt_box(0, 0, 10, 10), abs=1e-9)


def test_strokes_are_clipped_too():
    parsed = read("0 0 36 72 re W n 4 w 0 36 m 72 36 l S")
    assert bounds(parsed.shapes[0]) == pytest.approx(pt_box(0, 34, 36, 38), abs=1e-9)


# -- opacity ---------------------------------------------------------------------------------------------------------------------------
def test_fill_opacity_is_laid_on_white():
    parsed = read("/GS0 gs 1 0 0 rg 0 0 10 10 re f", resources="/ExtGState << /GS0 << /ca 0.5 /CA 0.25 >> >>")
    assert parsed.shapes[0].fill == "#ff8080"


def test_stroke_opacity_uses_CA_and_a_full_opacity_keeps_the_colour():
    parsed = read("/GS0 gs 0 0 0 RG 4 w 0 0 m 50 0 l S /GS1 gs 0 0 0 RG 4 w 0 10 m 50 10 l S",
                  resources="/ExtGState << /GS0 << /ca 0.5 /CA 0.25 >> /GS1 << /CA 1 >> >>")
    assert [s.fill for s in parsed.shapes] == ["#bfbfbf", "#000000"]


def test_a_shape_with_no_opacity_at_all_is_not_painted():
    parsed = read("/GS0 gs 0 0 10 10 re f", resources="/ExtGState << /GS0 << /ca 0 >> >>")
    assert parsed.shapes == []


def test_opacity_is_restored_by_Q():
    parsed = read("q /GS0 gs 0 0 10 10 re f Q 20 20 10 10 re f", resources="/ExtGState << /GS0 << /ca 0.5 >> >>")
    assert [s.fill for s in parsed.shapes] == ["#808080", "#000000"]


def test_the_graphics_state_dictionary_sets_the_line_width():
    parsed = read("/GS0 gs 10 36 m 62 36 l S", resources="/ExtGState << /GS0 << /LW 4 /LC 0 /LJ 0 /ML 10 >> >>")
    assert area(parsed.shapes) == pytest.approx(52 * 4 * PT * PT)


def test_soft_masks_are_counted_once_per_mask():
    pdf = Pdf()
    mask = pdf.add("<< /Type /Mask /S /Luminosity /G 99 0 R >>")
    data = pdf.build("/GS0 gs 0 0 10 10 re f /GS0 gs 20 20 10 10 re f /GS1 gs 30 30 10 10 re f",
                     resources=f"/ExtGState << /GS0 << /SMask {mask} 0 R >> /GS1 << /SMask /None >> >>")
    parsed = ai.parse(data)
    assert len(parsed.shapes) == 3 and parsed.notes == ["1 soft mask (transparency gradient) was ignored."]


# -- form XObjects ---------------------------------------------------------------------------------------------------------------------
def test_a_form_xobject_is_drawn_with_its_matrix():
    pdf = Pdf()
    form = pdf.add_stream(b"1 0 0 rg 0 0 10 10 re f", "/Type /XObject /Subtype /Form /BBox [0 0 10 10] /Matrix [2 0 0 2 20 20]")
    parsed = ai.parse(pdf.build("/Fm0 Do", resources=f"/XObject << /Fm0 {form} 0 R >>"))
    assert parsed.shapes[0].fill == "#ff0000"
    assert bounds(parsed.shapes[0]) == pytest.approx(pt_box(20, 20, 40, 40), abs=1e-9)


def test_a_form_is_clipped_to_its_bbox_and_uses_the_current_matrix():
    pdf = Pdf()
    form = pdf.add_stream(b"0 0 100 100 re f", "/Type /XObject /Subtype /Form /BBox [0 0 10 20]")
    parsed = ai.parse(pdf.build("q 1 0 0 1 30 30 cm /Fm0 Do Q", resources=f"/XObject << /Fm0 {form} 0 R >>"))
    assert bounds(parsed.shapes[0]) == pytest.approx(pt_box(30, 30, 40, 50), abs=1e-9)


def test_a_form_uses_its_own_resources_and_its_state_does_not_leak():
    pdf = Pdf()
    form = pdf.add_stream(b"/GS0 gs 0 0 1 rg 0 0 10 10 re f", "/Type /XObject /Subtype /Form /BBox [0 0 72 72] "
                          "/Resources << /ExtGState << /GS0 << /ca 0.5 >> >> >>")
    parsed = ai.parse(pdf.build("/Fm0 Do 20 20 10 10 re f", resources=f"/XObject << /Fm0 {form} 0 R >>"))
    assert [s.fill for s in parsed.shapes] == ["#8080ff", "#000000"]


def test_a_form_without_resources_uses_the_ones_of_the_page():
    pdf = Pdf()
    form = pdf.add_stream(b"/GS0 gs 0 0 10 10 re f", "/Type /XObject /Subtype /Form /BBox [0 0 72 72]")
    parsed = ai.parse(pdf.build("/Fm0 Do", resources=f"/XObject << /Fm0 {form} 0 R >> /ExtGState << /GS0 << /ca 0.5 >> >>"))
    assert parsed.shapes[0].fill == "#808080"


def test_a_transparency_group_carries_the_opacity_it_is_painted_with():
    pdf = Pdf()
    form = pdf.add_stream(b"/GS1 gs 0 0 10 10 re f", "/Type /XObject /Subtype /Form /BBox [0 0 72 72] /Group << /S /Transparency >> "
                          "/Resources << /ExtGState << /GS1 << /ca 0.5 >> >> >>")
    parsed = ai.parse(pdf.build("/GS0 gs /Fm0 Do", resources=f"/XObject << /Fm0 {form} 0 R >> /ExtGState << /GS0 << /ca 0.5 >> >>"))
    assert parsed.shapes[0].fill == "#bfbfbf"                            # 0.5 x 0.5 = 0.25 of black on white


def test_forms_inside_forms_and_a_form_that_draws_itself():
    pdf = Pdf()
    outer = pdf.next_num
    inner = outer + 1
    pdf.add_stream(f"0 0 5 5 re f q 1 0 0 1 10 0 cm /In Do Q /Self Do".encode(),
                   f"/Type /XObject /Subtype /Form /BBox [0 0 72 72] /Resources << /XObject << /In {inner} 0 R /Self {outer} 0 R >> >>")
    pdf.add_stream(b"1 0 0 rg 0 0 5 5 re f", "/Type /XObject /Subtype /Form /BBox [0 0 72 72]")
    parsed = ai.parse(pdf.build("/Fm0 Do", resources=f"/XObject << /Fm0 {outer} 0 R >>"))
    assert [s.fill for s in parsed.shapes] == ["#000000", "#ff0000"]


def test_a_chain_of_forms_deeper_than_the_limit_stops():
    pdf = Pdf()
    first = pdf.next_num
    count = ai.MAX_FORM_DEPTH + 8
    for i in range(count):
        nxt = f"/Next {first + i + 1} 0 R" if i + 1 < count else ""
        pdf.add_stream(f"0 0 5 5 re f /X Do".encode(), f"/Type /XObject /Subtype /Form /BBox [0 0 72 72] "
                       f"/Resources << /XObject << /X {first + i + 1} 0 R >> >>")
    parsed = ai.parse(pdf.build("/X Do", resources=f"/XObject << /X {first} 0 R >>"))
    assert len(parsed.shapes) == ai.MAX_FORM_DEPTH


# -- layers (optional content) ---------------------------------------------------------------------------------------------------------
def _layers(state: str = "/OFF [{off} 0 R]", base: str = ""):
    pdf = Pdf()
    shown = pdf.add("<< /Type /OCG /Name (Visible layer) >>")
    hidden = pdf.add("<< /Type /OCG /Name (Hidden layer) >>")
    catalog = f"/OCProperties << /OCGs [{shown} 0 R {hidden} 0 R] /D << {base} {state.format(off=hidden, on=shown)} >> >>"
    return pdf, shown, hidden, catalog


def test_a_hidden_layer_is_skipped_and_a_visible_one_keeps_its_name():
    pdf, shown, hidden, catalog = _layers()
    content = ("/OC /MC0 BDC 1 0 0 rg 0 0 10 10 re f EMC "
               "/OC /MC1 BDC 0 1 0 rg 20 20 10 10 re f /Span << /MCID 0 >> BDC 30 30 5 5 re f EMC EMC "
               "0 0 1 rg 40 40 10 10 re f")
    parsed = ai.parse(pdf.build(content, catalog=catalog, resources=f"/Properties << /MC0 {shown} 0 R /MC1 {hidden} 0 R >>"))
    assert [(s.fill, s.name) for s in parsed.shapes] == [("#ff0000", "Visible layer"), ("#0000ff", None)]
    assert parsed.notes == []


def test_hidden_content_does_not_count_pictures_text_or_forms_and_still_balances_q():
    pdf, shown, hidden, catalog = _layers()
    picture = pdf.add_stream(b"\x00", "/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8")
    form = pdf.add_stream(b"0 0 5 5 re f", "/Type /XObject /Subtype /Form /BBox [0 0 72 72]")
    content = ("/OC /MC1 BDC q /Im0 Do /Fm0 Do BT (x) Tj ET BI /W 1 /H 1 /BPC 8 /CS /G ID \x00 EI 1 0 0 rg 0 0 10 10 re f Q EMC "
               "10 10 10 10 re f")
    parsed = ai.parse(pdf.build(content, catalog=catalog, resources=f"/Properties << /MC1 {hidden} 0 R >> "
                                f"/XObject << /Im0 {picture} 0 R /Fm0 {form} 0 R >>"))
    assert [s.fill for s in parsed.shapes] == ["#000000"] and parsed.notes == []


def test_colours_set_inside_a_hidden_layer_still_apply_after_it():
    pdf, shown, hidden, catalog = _layers()
    parsed = ai.parse(pdf.build("/OC /MC1 BDC 0 1 0 rg EMC 0 0 10 10 re f", catalog=catalog,
                                resources=f"/Properties << /MC1 {hidden} 0 R >>"))
    assert parsed.shapes[0].fill == "#00ff00"


def test_a_base_state_of_off_with_an_on_list():
    pdf, shown, hidden, catalog = _layers(state="/ON [{on} 0 R]", base="/BaseState /OFF")
    content = "/OC /MC0 BDC 1 0 0 rg 0 0 10 10 re f EMC /OC /MC1 BDC 0 1 0 rg 20 20 10 10 re f EMC"
    parsed = ai.parse(pdf.build(content, catalog=catalog, resources=f"/Properties << /MC0 {shown} 0 R /MC1 {hidden} 0 R >>"))
    assert [s.name for s in parsed.shapes] == ["Visible layer"]


def test_the_innermost_visible_layer_names_the_shape():
    pdf = Pdf()
    outer = pdf.add("<< /Type /OCG /Name (Outer) >>")
    inner = pdf.add("<< /Type /OCG /Name <FEFF0049006E006E00650072> >>")           # "Inner" in UTF-16
    catalog = f"/OCProperties << /OCGs [{outer} 0 R {inner} 0 R] /D << >> >>"
    content = ("/OC /A BDC 0 0 5 5 re f /OC /B BDC 10 0 5 5 re f EMC 20 0 5 5 re f EMC")
    parsed = ai.parse(pdf.build(content, catalog=catalog, resources=f"/Properties << /A {outer} 0 R /B {inner} 0 R >>"))
    assert [s.name for s in parsed.shapes] == ["Outer", "Inner", "Outer"]


def test_a_membership_dictionary_follows_its_policy():
    pdf, shown, hidden, catalog = _layers()
    all_on = pdf.add(f"<< /Type /OCMD /OCGs [{shown} 0 R {hidden} 0 R] /P /AllOn >>")
    any_on = pdf.add(f"<< /Type /OCMD /OCGs [{shown} 0 R {hidden} 0 R] >>")
    all_off = pdf.add(f"<< /Type /OCMD /OCGs [{shown} 0 R {hidden} 0 R] /P /AllOff >>")
    expression = pdf.add(f"<< /Type /OCMD /VE [/And {shown} 0 R [/Not {hidden} 0 R]] >>")
    content = ("/OC /A BDC 0 0 5 5 re f EMC /OC /B BDC 10 0 5 5 re f EMC /OC /C BDC 20 0 5 5 re f EMC /OC /D BDC 30 0 5 5 re f EMC")
    parsed = ai.parse(pdf.build(content, catalog=catalog, resources=(
        f"/Properties << /A {all_on} 0 R /B {any_on} 0 R /C {all_off} 0 R /D {expression} 0 R >>")))
    assert [bounds(s)[0] / PT for s in parsed.shapes] == pytest.approx([10, 30])


def test_an_xobject_that_belongs_to_a_hidden_group_is_not_drawn():
    pdf, shown, hidden, catalog = _layers()
    form = pdf.add_stream(b"0 0 5 5 re f", f"/Type /XObject /Subtype /Form /BBox [0 0 72 72] /OC {hidden} 0 R")
    parsed = ai.parse(pdf.build("/Fm0 Do", catalog=catalog, resources=f"/XObject << /Fm0 {form} 0 R >>"))
    assert parsed.shapes == []


def test_marked_content_that_is_not_optional_content_changes_nothing():
    parsed = read("/Artifact BMC 0 0 5 5 re f EMC /Span << /ActualText (x) /MCID 3 >> BDC 10 0 5 5 re f EMC")
    assert len(parsed.shapes) == 2


# -- pictures and text, counted ------------------------------------------------------------------------------------------------------------
def test_an_image_xobject_is_counted_and_its_data_is_never_inflated(monkeypatch):
    monkeypatch.setattr(ai, "MAX_STREAM_BYTES", 1 << 20)
    pdf = Pdf()
    bomb = _compress_zeros(8 << 20)                                      # would raise as too large if anything inflated it
    picture = pdf.add_stream(bomb, "/Type /XObject /Subtype /Image /Width 8192 /Height 1024 /ColorSpace /DeviceGray /BitsPerComponent 8 "
                             "/Filter /FlateDecode")
    private = pdf.add_stream(bomb, "/Filter /FlateDecode")
    started = time.monotonic()
    parsed = ai.parse(pdf.build("/Im0 Do 0 0 10 10 re f /Im0 Do", resources=f"/XObject << /Im0 {picture} 0 R >>",
                                catalog=f"/PieceInfo << /Illustrator << /Private {private} 0 R >> >>"))
    assert time.monotonic() - started < 5
    assert len(parsed.shapes) == 1 and parsed.notes == ["2 pictures inside the file were not imported."]


def test_one_picture_is_said_in_the_singular_and_inline_images_count_too():
    pdf = Pdf()
    picture = pdf.add_stream(b"\x00", "/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8")
    parsed = ai.parse(pdf.build("/Im0 Do", resources=f"/XObject << /Im0 {picture} 0 R >>"))
    assert parsed.notes == ["1 picture inside the file was not imported."]
    inline = read(b"q 10 0 0 10 0 0 cm BI /W 2 /H 2 /BPC 8 /CS /G ID \x00 EI f EI \x01 EI Q 1 0 0 rg 20 20 10 10 re f")
    assert inline.notes == ["1 picture inside the file was not imported."]
    assert [s.fill for s in inline.shapes] == ["#ff0000"]


def test_text_objects_are_counted_and_do_not_disturb_the_paths():
    content = ("0 0 5 5 re BT /F1 12 Tf 10 10 Td (Hello q Q f W n \\) m l) Tj [(a) -20 (b)] TJ ET f "
               "BT 1 0 0 1 5 5 Tm (second) ' ET 10 10 5 5 re f")
    parsed = read(content)
    assert len(parsed.shapes) == 2
    assert parsed.notes == ["2 text objects were not imported: create outlines of the text in Illustrator and save again."]


def test_one_text_object_is_said_in_the_singular():
    assert read("BT (x) Tj ET").notes == ["1 text object was not imported: create outlines of the text in Illustrator and save again."]


def test_nothing_lost_means_no_notes():
    assert read("0 0 10 10 re f").notes == []


def test_the_notes_come_in_a_fixed_order_each_once():
    pdf = Pdf()
    picture = pdf.add_stream(b"\x00", "/Type /XObject /Subtype /Image /Width 1 /Height 1")
    parsed = ai.parse(pdf.build("BT ET /Im0 Do [2] 0 d 1 w 0 0 m 5 5 l S BT ET", resources=f"/XObject << /Im0 {picture} 0 R >>", pages=2))
    assert parsed.notes[0] == "Only the first artboard was imported."
    assert len(parsed.notes) == 4 and len(set(parsed.notes)) == 4


# -- pages -----------------------------------------------------------------------------------------------------------------------------
def test_two_pages_import_the_first_and_say_so():
    pdf = Pdf()
    data = pdf.build("1 0 0 rg 0 0 10 10 re f", pages=3)
    parsed = ai.parse(data)
    assert [s.fill for s in parsed.shapes] == ["#ff0000"]
    assert parsed.notes == ["Only the first artboard was imported."]


def test_content_streams_in_an_array_are_joined():
    pdf = Pdf()
    first = pdf.add_stream(b"1 0 0 rg 0 0 10 10 re", "")
    second = pdf.add_stream(b"f 0 1 0 rg 20 20 10 10 re f", "")
    data = pdf.build("", variant="classic").replace(b"/Contents 4 0 R", b"/Contents [%d 0 R %d 0 R]" % (first, second))
    assert [s.fill for s in ai.parse(data).shapes] == ["#ff0000", "#00ff00"]


def test_a_page_without_content_is_an_empty_result():
    data = make("").replace(b"/Contents 4 0 R", b"")
    parsed = ai.parse(data)
    assert parsed.shapes == [] and parsed.notes == [] and parsed.kind == "ai"


# -- colour spaces ---------------------------------------------------------------------------------------------------------------------
def test_icc_based_spaces_follow_their_component_count():
    pdf = Pdf()
    rgb = pdf.add_stream(b"not a profile", "/N 3")
    cmyk = pdf.add_stream(b"not a profile", "/N 4")
    gray = pdf.add_stream(b"not a profile", "/N 1")
    parsed = ai.parse(pdf.build("/R cs 1 0 0 sc 0 0 5 5 re f /C cs 0 1 1 0 scn 10 0 5 5 re f /G cs 0.5 sc 20 0 5 5 re f",
                                resources=f"/ColorSpace << /R [/ICCBased {rgb} 0 R] /C [/ICCBased {cmyk} 0 R] /G [/ICCBased {gray} 0 R] >>"))
    assert [s.fill for s in parsed.shapes] == ["#ff0000", "#ff0000", "#808080"]


def test_the_initial_colour_of_a_space_is_black_and_device_spaces_can_be_named():
    parsed = read("/DeviceRGB cs 0 0 5 5 re f /DeviceCMYK cs 10 0 5 5 re f /DeviceGray CS 0.5 SC 1 w 20 0 m 30 0 l S")
    assert [s.fill for s in parsed.shapes] == ["#000000", "#000000", "#808080"]


def test_lab_gives_the_neutral_grey_and_a_saturated_colour():
    resources = "/ColorSpace << /L [/Lab << /WhitePoint [0.9642 1 0.8249] /Range [-128 127 -128 127] >>] >>"
    grey = read("/L cs 50 0 0 sc 0 0 5 5 re f", resources=resources).shapes[0].fill
    red = read("/L cs 50 80 60 sc 0 0 5 5 re f", resources=resources).shapes[0].fill
    channels = [int(grey[i:i + 2], 16) for i in (1, 3, 5)]
    assert all(abs(c - 119) <= 2 for c in channels)
    r, g, b = (int(red[i:i + 2], 16) for i in (1, 3, 5))
    assert r > 180 and g < 90 and b < 90


def test_indexed_spaces_look_up_their_palette():
    resources = "/ColorSpace << /I [/Indexed /DeviceRGB 1 <ff0000 0000ff>] >>"
    parsed = read("/I cs 0 sc 0 0 5 5 re f 1 sc 10 0 5 5 re f 5 sc 20 0 5 5 re f", resources=resources)
    assert [s.fill for s in parsed.shapes] == ["#ff0000", "#0000ff", "#0000ff"]


def test_a_separation_uses_its_exponential_tint_transform():
    pdf = Pdf()
    function = pdf.add("<< /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 1 1 0] /N 1 >>")
    resources = f"/ColorSpace << /S [/Separation /Spot /DeviceCMYK {function} 0 R] >>"
    parsed = ai.parse(pdf.build("/S cs 1 scn 0 0 5 5 re f 0.5 scn 10 0 5 5 re f 0 scn 20 0 5 5 re f", resources=resources))
    assert [s.fill for s in parsed.shapes] == ["#ff0000", "#ff8080", "#ffffff"] and parsed.notes == []


def test_a_separation_with_a_sampled_function_and_one_with_a_stitching_function():
    pdf = Pdf()
    sampled = pdf.add_stream(bytes([255, 255, 255, 0, 0, 255]), "/FunctionType 0 /Domain [0 1] /Range [0 1 0 1 0 1] /Size [2] /BitsPerSample 8")
    low = pdf.add("<< /FunctionType 2 /Domain [0 1] /C0 [1] /C1 [0.5] /N 1 >>")
    high = pdf.add("<< /FunctionType 2 /Domain [0 1] /C0 [0.5] /C1 [0] /N 1 >>")
    stitched = pdf.add(f"<< /FunctionType 3 /Domain [0 1] /Functions [{low} 0 R {high} 0 R] /Bounds [0.5] /Encode [0 1 0 1] >>")
    resources = (f"/ColorSpace << /A [/Separation /A /DeviceRGB {sampled} 0 R] /B [/Separation /B /DeviceGray {stitched} 0 R] >>")
    parsed = ai.parse(pdf.build("/A cs 0.5 scn 0 0 5 5 re f /B cs 0.25 scn 10 0 5 5 re f /B cs 1 scn 20 0 5 5 re f", resources=resources))
    assert [s.fill for s in parsed.shapes] == ["#8080ff", "#bfbfbf", "#000000"]


def test_a_device_n_space_with_a_postscript_function():
    pdf = Pdf()
    function = pdf.add_stream(b"{ 1 exch sub exch 1 exch sub exch 0 }", "/FunctionType 4 /Domain [0 1 0 1] /Range [0 1 0 1 0 1]")
    resources = f"/ColorSpace << /N [/DeviceN [/A /B] /DeviceRGB {function} 0 R] >>"
    parsed = ai.parse(pdf.build("/N cs 1 0 scn 0 0 5 5 re f 0.25 0.5 scn 10 0 5 5 re f", resources=resources))
    assert [s.fill for s in parsed.shapes] == ["#00ff00", "#bf8000"]


@pytest.mark.parametrize("program, tint, colour", [
    ("{ dup 0.5 gt { pop 1 } { 2 mul } ifelse 0 0 }", 0.25, "#800000"),
    ("{ dup 0.5 gt { pop 1 } { 2 mul } ifelse 0 0 }", 0.75, "#ff0000"),
    ("{ 1 exch sub 0 0 }", 0.25, "#bf0000"),
    ("{ dup 2 copy pop pop 0 }", 0.5, "#808000"),
    ("{ 0 0 3 -1 roll }", 1, "#0000ff"),
    ("{ 3 mul dup floor sub 0 0 }", 0.5, "#800000"),
    ("{ sqrt 0 0 }", 0.25, "#800000"),
    ("{ 2 exp 0 0 }", 0.5, "#400000"),
    ("{ 1 eq { 1 } { 0 } ifelse 0 0 }", 1, "#ff0000"),
    ("{ 7 2 idiv 4 mod 5 div 0 0 }", 0, "#990000"),                      # 7 idiv 2 = 3, 3 mod 4 = 3, 3 / 5 = 0.6
    ("{ true { 0.5 } { 1 } ifelse 0 0 1 index pop }", 0, "#800000"),
])
def test_the_postscript_calculator_knows_its_operators(program, tint, colour):
    pdf = Pdf()
    function = pdf.add_stream(program.encode(), "/FunctionType 4 /Domain [0 1] /Range [0 1 0 1 0 1]")
    parsed = ai.parse(pdf.build(f"/N cs {tint} scn 0 0 5 5 re f",
                                resources=f"/ColorSpace << /N [/Separation /N /DeviceRGB {function} 0 R] >>"))
    assert [s.fill for s in parsed.shapes] == [colour] and parsed.notes == []


def test_a_spot_colour_without_a_usable_function_becomes_a_grey_and_is_counted():
    resources = "/ColorSpace << /S [/Separation /Spot /DeviceCMYK 99 0 R] >>"
    parsed = read("/S cs 1 scn 0 0 5 5 re f 0.25 scn 10 0 5 5 re f 1 scn 20 0 5 5 re f", resources=resources)
    assert [s.fill for s in parsed.shapes] == ["#000000", "#bfbfbf", "#000000"]
    assert parsed.notes == ["2 colours could not be converted exactly and were replaced by greys."]


def test_the_separation_none_paints_nothing():
    pdf = Pdf()
    function = pdf.add("<< /FunctionType 2 /Domain [0 1] /C0 [0] /C1 [1] /N 1 >>")
    parsed = ai.parse(pdf.build("/S cs 1 scn 0 0 5 5 re f", resources=f"/ColorSpace << /S [/Separation /None /DeviceGray {function} 0 R] >>"))
    assert parsed.shapes == []


AXIAL = ("<< /PatternType 2 /Shading << /ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 0 72 0] "
         "/Function << /FunctionType 2 /Domain [0 1] /C0 [1 0 0] /C1 [0 0 1] /N 1 >> /Extend [true true] >> >>")


def test_a_gradient_fill_becomes_its_average_colour_and_is_counted():
    pdf = Pdf()
    pattern = pdf.add(AXIAL)
    parsed = ai.parse(pdf.build("/Pattern cs /P0 scn 0 0 72 72 re f /Pattern CS /P0 SCN 2 w 0 0 m 50 0 l S",
                                resources=f"/Pattern << /P0 {pattern} 0 R >>"))
    assert [s.fill for s in parsed.shapes] == ["#800080", "#800080"]
    assert parsed.notes == ["2 gradient fills were replaced by their average colour."]


def test_a_radial_shading_with_a_stitching_function_and_the_sh_operator():
    pdf = Pdf()
    first = pdf.add("<< /FunctionType 2 /Domain [0 1] /C0 [1 1 1] /C1 [0 0 0] /N 1 >>")
    shading = pdf.add(f"<< /ShadingType 3 /ColorSpace /DeviceRGB /Coords [36 36 0 36 36 30] /Function {first} 0 R >>")
    parsed = ai.parse(pdf.build("q 10 10 40 40 re W n /Sh0 sh Q", resources=f"/Shading << /Sh0 {shading} 0 R >>"))
    assert len(parsed.shapes) == 1 and bounds(parsed.shapes[0]) == pytest.approx(pt_box(10, 10, 50, 50), abs=1e-9)
    assert parsed.shapes[0].fill == "#808080"
    assert parsed.notes == ["1 gradient fill was replaced by its average colour."]


def test_a_tiling_pattern_is_left_out_and_counted():
    pdf = Pdf()
    pattern = pdf.add_stream(b"0 0 2 2 re f", "/PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 4 4] /XStep 4 /YStep 4 /Resources << >>")
    parsed = ai.parse(pdf.build("/Pattern cs /P0 scn 0 0 72 72 re f 1 0 0 rg 0 0 5 5 re f", resources=f"/Pattern << /P0 {pattern} 0 R >>"))
    assert [s.fill for s in parsed.shapes] == ["#ff0000"]
    assert parsed.notes == ["1 pattern fill was not imported."]


# -- the file layout ---------------------------------------------------------------------------------------------------------------------
def test_an_incremental_update_wins_over_the_original_object():
    original = make("1 0 0 rg 0 0 10 10 re f")
    new = b"0 1 0 rg 0 0 10 10 re f"
    start = original.rfind(b"startxref")
    previous = int(original[start + 9:].split()[0])
    update_at = len(original)
    update = b"4 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj\n" % (len(new), new)
    table_at = update_at + len(update)
    table = (b"xref\n0 1\n0000000000 65535 f \n4 1\n%010d 00000 n \ntrailer\n<< /Size 5 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n"
             % (update_at, previous, table_at))
    assert [s.fill for s in ai.parse(original + update + table).shapes] == ["#00ff00"]
    assert [s.fill for s in ai.parse(original).shapes] == ["#ff0000"]


def test_a_free_entry_does_not_hide_an_older_object():
    original = make("1 0 0 rg 0 0 10 10 re f")
    start = original.rfind(b"startxref")
    previous = int(original[start + 9:].split()[0])
    table = b"xref\n0 1\n0000000000 65535 f \n4 1\n0000000000 00001 f \ntrailer\n<< /Size 5 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n"
    assert [s.fill for s in ai.parse(original + table % (previous, len(original))).shapes] == ["#ff0000"]


def _hybrid_file() -> bytes:
    """A classic table that lists the compressed objects as free and a /XRefStm in its trailer that tells where they are."""
    content = b"1 0 0 rg 0 0 10 10 re f"
    bodies = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
              b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] /Contents 4 0 R /Resources << >> >>"]
    head, body = b"", b""
    for num, text in enumerate(bodies, 1):
        head += b"%d %d " % (num, len(body))
        body += text + b" "
    out = bytearray(b"%PDF-1.5\n")
    at = {4: len(out)}
    out += Pdf._object(4, b"", content)
    at[5] = len(out)
    out += Pdf._object(5, b"/Type /ObjStm /N 3 /First %d" % len(head), head + body)
    at[6] = stream_at = len(out)
    rows = b"".join(bytes([2]) + (5).to_bytes(4, "big") + i.to_bytes(2, "big") for i in range(3))
    out += Pdf._object(6, b"/Type /XRef /Size 7 /W [1 4 2] /Index [1 3]", rows)
    table_at = len(out)
    out += b"xref\n0 7\n0000000000 65535 f \n" + b"0000000000 00000 f \n" * 3
    out += b"".join(b"%010d 00000 n \n" % at[n] for n in (4, 5, 6))
    out += b"trailer\n<< /Size 7 /Root 1 0 R /XRefStm %d >>\nstartxref\n%d\n%%%%EOF\n" % (stream_at, table_at)
    return bytes(out)


def test_a_hybrid_file_reads_the_objects_of_its_cross_reference_stream():
    parsed = ai.parse(_hybrid_file())
    assert [s.fill for s in parsed.shapes] == ["#ff0000"]


@pytest.mark.parametrize("variant, rebuilt", [("classic", False), ("flate", False), ("xrefstream", False), ("hybrid", False),
                                              ("bad_startxref", True), ("bad_offsets", True), ("no_xref", True)])
def test_a_sound_cross_reference_is_read_and_a_damaged_one_is_rebuilt(variant, rebuilt):
    data = _hybrid_file() if variant == "hybrid" else make("1 0 0 rg 0 0 10 10 re f", variant=variant)
    doc = ai._Doc(data)
    assert doc.rebuilt is rebuilt
    assert doc.resolve(doc.trailer["Root"])["Type"] == "Catalog"
    page, count = doc.first_page()
    assert count == 1 and page["MediaBox"] == [0, 0, 72, 72]


def test_a_cross_reference_stream_with_a_predictor_gives_the_same_result():
    plain = make("1 0 0 rg 0 0 10 10 re f", variant="xrefstream")
    assert b"/Predictor 12" in plain and [s.fill for s in ai.parse(plain).shapes] == ["#ff0000"]


def test_the_header_may_come_after_some_leading_bytes():
    parsed = ai.parse(Pdf().build("0 0 10 10 re f", prefix=b"\x00\x01junk before the header\r\n"))
    assert len(parsed.shapes) == 1
    assert len(ai.parse(Pdf().build("0 0 10 10 re f", prefix=b"junk\n", variant="xrefstream")).shapes) == 1


def test_a_stream_with_a_wrong_or_an_indirect_length():
    text = "1 0 0 rg 0 0 10 10 re f"
    good = make(text)
    exact = b"/Length %d" % len(text)
    assert exact in good
    short = good.replace(exact, b"/Length 5")
    assert len(ai.parse(short).shapes) == 1
    long = good.replace(exact, b"/Length 5000")
    assert len(ai.parse(long).shapes) == 1
    indirect = Pdf()
    length = indirect.add(str(len(text)))
    data = indirect.build(text).replace(exact, b"/Length %d 0 R" % length)
    assert b"/Length %d 0 R" % length in data and len(ai.parse(data).shapes) == 1


def test_flate_content_with_predictors_and_filter_arrays():
    plain = b"1 0 0 rg 0 0 10 10 re f"
    hexed = zlib.compress(plain).hex().encode() + b">"
    parsed = ai.parse(make("", contents_data=hexed, contents_entries="/Filter [/ASCIIHexDecode /FlateDecode]"))
    assert [s.fill for s in parsed.shapes] == ["#ff0000"]
    import base64
    a85 = base64.a85encode(zlib.compress(plain)) + b"~>"
    parsed = ai.parse(make("", contents_data=a85, contents_entries="/Filter [/ASCII85Decode /FlateDecode]"))
    assert [s.fill for s in parsed.shapes] == ["#ff0000"]


def test_lzw_content():
    plain = b"0 0 1 rg 0 0 10 10 re f"
    parsed = ai.parse(make("", contents_data=lzw_encode(plain), contents_entries="/Filter /LZWDecode"))
    assert [s.fill for s in parsed.shapes] == ["#0000ff"]


@pytest.mark.parametrize("count", [120, 300, 330, 700])
def test_lzw_content_that_grows_the_code_width(count):
    rng = random.Random(count)
    plain = " ".join(f"{rng.randrange(256)} g {rng.randrange(60)} {rng.randrange(60)} {rng.randrange(1, 9)} {rng.randrange(1, 9)} re f"
                     for _ in range(count)).encode()
    assert len(lzw_encode(plain)) < len(plain)
    parsed = ai.parse(make("", contents_data=lzw_encode(plain), contents_entries="/Filter /LZWDecode"))
    assert len(parsed.shapes) == count


def test_a_truncated_flate_stream_gives_what_could_be_read():
    compressor = zlib.compressobj()
    head = compressor.compress(b"1 0 0 rg 0 0 10 10 re f\n") + compressor.flush(zlib.Z_SYNC_FLUSH)
    tail = compressor.compress(b"0 1 0 rg 20 20 10 10 re f\n" * 50) + compressor.flush()
    data = head + tail[:len(tail) // 2]
    parsed = ai.parse(make("", contents_data=data, contents_entries="/Filter /FlateDecode"))
    assert parsed.shapes and parsed.shapes[0].fill == "#ff0000"


def test_a_stream_that_is_a_decompression_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(ai, "MAX_STREAM_BYTES", 1 << 20)
    with pytest.raises(ValidationError, match="too detailed"):
        ai.parse(make("", contents_data=_compress_zeros(4 << 20), contents_entries="/Filter /FlateDecode"))


def test_all_the_streams_together_are_limited_too(monkeypatch):
    monkeypatch.setattr(ai, "MAX_TOTAL_BYTES", 3 << 20)
    pdf = Pdf()
    forms = [pdf.add_stream(bytes(1 << 20), "/Type /XObject /Subtype /Form /BBox [0 0 72 72]") for _ in range(6)]
    names = " ".join(f"/F{i} {num} 0 R" for i, num in enumerate(forms))
    with pytest.raises(ValidationError, match="too detailed"):
        ai.parse(pdf.build(" ".join(f"/F{i} Do" for i in range(6)), resources=f"/XObject << {names} >>"))


# -- limits ----------------------------------------------------------------------------------------------------------------------------
def test_too_many_vertices_is_refused(monkeypatch):
    monkeypatch.setattr(ai, "MAX_VERTICES", 100)
    content = " ".join(f"{i} 0 m {i + 1} 0 l {i + 1} 1 l f" for i in range(60))
    with pytest.raises(ValidationError, match="too detailed"):
        read(content)


def test_too_many_shapes_is_refused(monkeypatch):
    monkeypatch.setattr(ai, "MAX_SHAPES", 10)
    with pytest.raises(ValidationError, match="too detailed"):
        read(" ".join("0 0 5 5 re f" for _ in range(20)))


def test_a_file_that_takes_too_long_is_refused(monkeypatch):
    monkeypatch.setattr(ai, "MAX_SECONDS", -1.0)
    with pytest.raises(ValidationError, match="too detailed"):
        read("0 0 5 5 re f " * 40000)


# -- refusals --------------------------------------------------------------------------------------------------------------------------
PS_MESSAGE = ("This Illustrator file has no PDF-compatible content, so it cannot be imported. Open it in Illustrator and save it again with "
              "“Create PDF Compatible File” ticked, or export it as SVG.")


def test_a_postscript_based_illustrator_file_is_refused_with_the_advice():
    data = b"%!PS-Adobe-3.0 EPSF-3.0\n%%Creator: Adobe Illustrator(R) 8.0\n" + b"0 0 m 10 10 l stroke\n" * 100
    with pytest.raises(ValidationError) as caught:
        ai.parse(data)
    assert str(caught.value) == PS_MESSAGE


def test_a_pdf_marker_after_the_first_kilobyte_does_not_make_a_postscript_file_readable():
    data = b"%!PS-Adobe-3.0\n" + b"x" * 2000 + make("0 0 10 10 re f")
    with pytest.raises(ValidationError) as caught:
        ai.parse(data)
    assert str(caught.value) == PS_MESSAGE


@pytest.mark.parametrize("data", [b"", b"hello", b"\x89PNG\r\n\x1a\n" + bytes(100), b"<svg xmlns='http://www.w3.org/2000/svg'/>", bytes(range(256))])
def test_a_file_that_is_not_a_pdf_is_refused(data):
    with pytest.raises(ValidationError, match="not an Illustrator file"):
        ai.parse(data)


@pytest.mark.parametrize("variant", ["classic", "xrefstream"])
def test_an_encrypted_file_is_refused_in_every_layout(variant):
    data = Pdf().build("0 0 10 10 re f", variant=variant, trailer="/Encrypt 9 0 R")
    with pytest.raises(ValidationError, match="password or encryption"):
        ai.parse(data)


def test_an_encrypted_file_with_a_damaged_cross_reference_is_refused_too():
    data = make("0 0 10 10 re f", variant="bad_startxref").replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt 9 0 R")
    with pytest.raises(ValidationError, match="password or encryption"):
        ai.parse(data)


def test_a_damaged_file_with_no_page_is_refused():
    data = make("0 0 10 10 re f").replace(b"/Kids [3 0 R]", b"/Kids []")
    with pytest.raises(ValidationError, match="no artboard"):
        ai.parse(data)
    with pytest.raises(ValidationError):
        ai.parse(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n")
    with pytest.raises(ValidationError):
        ai.parse(b"%PDF-1.4\n")


def test_a_pdf_header_with_nothing_readable_after_it_is_refused():
    with pytest.raises(ValidationError, match="damaged|no artboard"):
        ai.parse(b"%PDF-1.5\n" + bytes(range(256)) * 20)


def test_every_refusal_is_a_validation_error_with_a_message_for_the_operator():
    for data in (b"", b"%!PS-Adobe-3.0\n", b"%PDF-", make("0 0 1 1 re f")[:80]):
        with pytest.raises(ValidationError) as caught:
            ai.parse(data)
        assert str(caught.value).endswith(".") and str(caught.value)[0].isupper()


# -- cross-reference damage ------------------------------------------------------------------------------------------------------------
def test_a_cross_reference_that_points_to_the_wrong_places_is_rebuilt():
    data = make("1 0 0 rg 0 0 10 10 re f", variant="bad_offsets")
    assert [s.fill for s in ai.parse(data).shapes] == ["#ff0000"]


def test_a_rebuilt_file_finds_objects_inside_object_streams():
    data = make("1 0 0 rg 0 0 10 10 re f", variant="xrefstream")
    cut = data.rfind(b"startxref")
    broken = data[:cut] + b"startxref\n7\n%%EOF\n"
    broken = broken.replace(b"/Type /XRef", b"/Type /Xxxx")             # the cross-reference stream is no longer one
    assert [s.fill for s in ai.parse(broken).shapes] == ["#ff0000"]


def test_the_newest_object_wins_when_the_cross_reference_is_rebuilt():
    original = make("1 0 0 rg 0 0 10 10 re f", variant="no_xref")
    new = b"0 1 0 rg 0 0 10 10 re f"
    update = b"4 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj\n" % (len(new), new)
    assert [s.fill for s in ai.parse(original + update).shapes] == ["#00ff00"]


# -- robustness ------------------------------------------------------------------------------------------------------------------------
CONTENT_FOR_FUZZ = ("q 1 0 0 rg 0 0 40 40 re W n 2 0 0 2 0 0 cm 0 0 10 10 re B Q /GS0 gs 0 1 0 rg 5 5 m 20 5 30 20 5 30 c h f* "
                    "BT (x) Tj ET /OC /MC0 BDC 1 1 1 rg 0 0 5 5 re f EMC")


def _fuzz_source() -> list[bytes]:
    out = []
    for variant in ("classic", "xrefstream", "flate"):
        pdf = Pdf()
        form = pdf.add_stream(b"0 0 5 5 re f", "/Type /XObject /Subtype /Form /BBox [0 0 72 72]")
        out.append(pdf.build(CONTENT_FOR_FUZZ + " /Fm0 Do", variant=variant,
                             resources=f"/ExtGState << /GS0 << /ca 0.5 >> >> /XObject << /Fm0 {form} 0 R >>"))
    return out


def test_damaged_files_never_raise_anything_but_a_validation_error():
    rng = random.Random(20260511)
    started = time.monotonic()
    survived = 0
    for source in _fuzz_source():
        for _ in range(150):
            data = bytearray(source)
            kind = rng.randrange(4)
            if kind == 0:
                del data[rng.randrange(len(data)):]
            elif kind == 1:
                for _ in range(rng.randrange(1, 12)):
                    data[rng.randrange(len(data))] = rng.randrange(256)
            elif kind == 2:
                start = rng.randrange(len(data))
                del data[start:start + rng.randrange(1, 80)]
            else:
                at = rng.randrange(len(data))
                data[at:at] = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 40)))
            try:
                parsed = ai.parse(bytes(data))
            except ValidationError:
                continue
            survived += 1
            assert parsed.kind == "ai" and all(isinstance(note, str) for note in parsed.notes)
    assert survived > 100
    assert time.monotonic() - started < 60


def test_pathological_syntax_is_survived():
    deep = b"[" * 5000 + b"]" * 5000
    cases = [
        make(b"((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((( 0 0 5 5 re f"),
        make(b"[" * 10000 + b" 0 0 5 5 re f"),
        make(b"<< " * 2000 + b" 0 0 5 5 re f"),
        make(b"1e308 1e308 m 9" * 100 + b" 0 0 5 5 re f 99999999999999999999999999999999999999999999 0 m 5 5 l 5 0 l f"),
        make("-.5 +.5 4. --5 1.2.3 0 0 m 10 0 l 10 10 l f"),
        make(b"/ " * 100 + b"0 0 5 5 re f"),
        make("0 0 10 10 re f").replace(b"/Pages 2 0 R", b"/Pages 1 0 R"),
        make("0 0 10 10 re f").replace(b"/Kids [3 0 R]", b"/Kids [2 0 R]"),
        make("0 0 10 10 re f").replace(b"/Parent 2 0 R", b"/Parent " + deep),
    ]
    for data in cases:
        try:
            ai.parse(data)
        except ValidationError:
            pass


def test_a_page_content_with_millions_of_numbers_in_one_array_is_not_quadratic():
    started = time.monotonic()
    ai.parse(make(b"[" + b"1 " * 200000 + b"] 0 d 0 0 5 5 re f"))
    assert time.monotonic() - started < 5


def test_operands_that_are_not_numbers_skip_the_operator_only():
    parsed = read("/Name /Other m 0 0 re 5 l 0 0 5 5 re f")
    assert len(parsed.shapes) == 1


def test_strings_with_nested_parentheses_and_escapes_do_not_hide_operators():
    parsed = read("BT (a (nested (deep) q) and \\( escaped) Tj ET 0 0 5 5 re f")
    assert len(parsed.shapes) == 1 and len(parsed.notes) == 1


# -- the geometry the shapes carry -----------------------------------------------------------------------------------------------------
def test_every_shape_is_valid_polygonal_and_a_hex_colour():
    parsed = read(CONTENT_FOR_FUZZ, resources="/ExtGState << /GS0 << /ca 0.5 >> >>")
    assert parsed.shapes
    for shape in parsed.shapes:
        assert shape.geometry.geom_type in ("Polygon", "MultiPolygon") and shape.geometry.is_valid and not shape.geometry.is_empty
        assert geo.is_hex(shape.fill)


def test_the_result_is_a_parsed_tuple_of_the_shared_type():
    parsed = read("0 0 10 10 re f")
    assert isinstance(parsed, geo.Parsed) and isinstance(parsed.shapes[0], geo.Shape)


def test_parse_accepts_any_bytes_like_object():
    data = make("0 0 10 10 re f")
    assert len(ai.parse(bytearray(data)).shapes) == 1 and len(ai.parse(memoryview(data)).shapes) == 1
