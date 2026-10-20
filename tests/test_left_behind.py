"""Layers a LightBurn file left behind, and layers whose output is off, are left out of the measurement (REQ-050).

The operator moves and resizes the picture in LightBurn; the tools skip the shapes of a hidden layer, so that layer stays where the exported
file had it and the photograph cannot show it there. Files are built here from rectangles, as the real ones are read."""
import pytest

from titanium_platform import ingest, left_behind as lbh, lightburn as lb, plans as pl

# (index, name, [(x, y, w, h), ...]) in the exported file: six layers spread over a 150 x 140 mm sheet
EXPORTED = [(1, "C01 a", [(10, 10, 20, 15), (50, 40, 30, 20), (100, 90, 25, 30)]),
            (2, "C02 b", [(20, 100, 40, 20), (70, 20, 15, 25), (120, 60, 20, 20)]),
            (3, "C03 c", [(5, 60, 30, 30), (60, 70, 50, 25), (110, 15, 30, 40)]),
            (4, "C04 d", [(30, 30, 25, 25), (80, 100, 35, 30), (125, 110, 20, 25)]),
            (5, "C05 e", [(15, 120, 30, 15), (65, 5, 30, 20), (105, 75, 35, 35)]),
            (6, "C06 f", [(0, 0, 150, 140), (40, 50, 20, 20), (90, 40, 30, 30)])]


def lightburn(layers, hidden=(), output_off=(), name="project"):
    """The bytes of a LightBurn file with a rectangle for each box ``(x, y, w, h)`` (its top-left corner and size, in mm)."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="2.0.04" MirrorX="False" MirrorY="False">']
    for index, title, _ in layers:
        extra = ('<hide Value="1"/>' if index in hidden else '') + ('<doOutput Value="0"/>' if index in output_off else '')
        parts.append(f'<CutSetting type="Scan"><index Value="{index}"/><name Value="{title}"/><maxPower Value="20"/><frequency Value="60000"/>'
                     f'<speed Value="100"/><interval Value="0.02"/>{extra}</CutSetting>')
    for index, _, boxes in layers:
        for x, y, w, h in boxes:
            parts.append(f'<Shape Type="Rect" CutIndex="{index}" W="{w}" H="{h}"><XForm>1 0 0 1 {x + w / 2} {y + h / 2}</XForm></Shape>')
    parts.append("</LightBurnProject>")
    return "".join(parts).encode("utf-8")


def moved(layers, scale=(0.5, 0.6), offset=(30, 20), flip_y=False, keep=(), sheet_h=140):
    """The same layers resized and moved the way LightBurn would, except the ``keep`` layers, which stay where they were."""
    out = []
    for index, title, boxes in layers:
        if index in keep:
            out.append((index, title, boxes))
            continue
        shifted = []
        for x, y, w, h in boxes:
            ny = (sheet_h - y - h) * scale[1] + offset[1] if flip_y else y * scale[1] + offset[1]
            shifted.append((x * scale[0] + offset[0], ny, w * scale[0], h * scale[1]))
        out.append((index, title, shifted))
    return out


def parse(layers, **kw):
    return lb.parse_bytes(lightburn(layers, **kw))


def test_a_layer_that_stayed_while_the_rest_was_resized_and_moved_is_left_behind():
    found = lbh.compare(parse(moved(EXPORTED, keep=(4,)), hidden=(4,)), parse(EXPORTED))
    assert found["verdict"] == "moved" and found["left"] == [4] and found["followed"] == [1, 2, 3, 5, 6]
    assert found["scale"] == pytest.approx([0.5, 0.6]) and found["offset_mm"] == pytest.approx([30, 20]) and found["flipped"] == [False, False]


def test_a_mirrored_axis_is_part_of_the_move():
    found = lbh.compare(parse(moved(EXPORTED, flip_y=True, keep=(2, 5))), parse(EXPORTED))
    assert found["verdict"] == "moved" and found["left"] == [2, 5] and found["flipped"] == [False, True]
    assert found["scale"] == pytest.approx([0.5, 0.6])


def test_a_file_that_did_not_move_has_no_layer_left_behind():
    assert lbh.compare(parse(EXPORTED), parse(EXPORTED)) == {"verdict": "unmoved", "left": [], "followed": []}


def test_with_too_few_layers_to_agree_on_a_move_nothing_is_said():
    two = EXPORTED[:2]
    assert lbh.compare(parse(moved(two, keep=(2,))), parse(two))["verdict"] == "unknown"


def test_a_layer_that_was_edited_is_not_named_because_the_comparison_cannot_tell_where_it_is():
    edited = moved(EXPORTED)
    edited[2] = (3, "C03 c", [(40, 40, 7, 9), (55, 33, 6, 6), (70, 70, 12, 11)])        # new shapes: matches neither place
    found = lbh.compare(parse(edited), parse(EXPORTED))
    assert found["verdict"] == "moved" and found["left"] == [] and 3 not in found["followed"]


def test_a_deleted_shape_does_not_make_a_layer_look_left_behind():
    smaller = moved(EXPORTED)
    smaller[0] = (1, "C01 a", smaller[0][2][:2])
    found = lbh.compare(parse(smaller), parse(EXPORTED))
    assert found["verdict"] == "moved" and found["left"] == [] and 1 in found["followed"]


def test_the_show_and_output_switches_of_a_layer_are_read():
    project = parse(EXPORTED, hidden=(2,), output_off=(3,))
    assert [(l.index, l.hidden, l.output_off) for l in project.layers] == [(1, False, False), (2, True, False), (3, False, True),
                                                                          (4, False, False), (5, False, False), (6, False, False)]


def report_of(project):
    return {"layers": [{"index": l.index, "name": l.name, "notes": [], "compatible": True, "measured_lab": None} for l in project.layers], "warnings": []}


def test_the_check_leaves_out_a_layer_left_behind_with_a_note_and_a_warning_and_drops_its_shapes(tmp_path):
    exported = tmp_path / "export.lbrn2"
    exported.write_bytes(lightburn(EXPORTED))
    plan = {"mode": pl.MODE_VECTOR, "exports": [{"number": 1, "path": str(tmp_path / "gone.lbrn2")}, {"number": 2, "path": str(exported)}]}
    project = parse(moved(EXPORTED, keep=(4,)), hidden=(4,))
    report = report_of(project)
    ingest._leave_out_layers(project, plan, report)
    left = next(l for l in report["layers"] if l["index"] == 4)
    assert left["left_out"] == "left_behind" and left["compatible"] is False and "left behind" in left["notes"][0]
    assert all("left_out" not in l and l["compatible"] for l in report["layers"] if l["index"] != 4)
    assert report["warnings"] == ["layers C04 stayed where the exported file had them while the rest of the file was resized to 50% by 60% of its exported "
                                  "size, and they are hidden in LightBurn, whose tools skip hidden layers; they are not measured"]
    assert next(l for l in project.layers if l.index == 4).regions == [] and all(l.regions for l in project.layers if l.index != 4)


def test_a_layer_left_behind_that_is_not_hidden_is_named_without_the_reason_of_hiding(tmp_path):
    exported = tmp_path / "export.lbrn2"
    exported.write_bytes(lightburn(EXPORTED))
    project = parse(moved(EXPORTED, keep=(2, 5)))
    report = report_of(project)
    ingest._leave_out_layers(project, {"mode": pl.MODE_VECTOR, "exports": [{"number": 1, "path": str(exported)}]}, report)
    assert report["warnings"] == ["layers C02, C05 stayed where the exported file had them while the rest of the file was resized to 50% by 60% of its "
                                  "exported size; they are not measured"]


def test_a_layer_whose_output_is_off_is_not_measured_with_or_without_an_exported_file():
    project = parse(EXPORTED, output_off=(3,))
    report = report_of(project)
    ingest._leave_out_layers(project, None, report)
    assert [l["index"] for l in report["layers"] if l.get("left_out") == "output_off"] == [3]
    assert report["warnings"] == ["layers C03 have their output switched off in LightBurn: they were not engraved and are not measured"]
    assert next(l for l in project.layers if l.index == 3).regions == []


def test_a_file_that_moved_nothing_or_a_plan_without_exports_leaves_every_layer_in(tmp_path):
    exported = tmp_path / "export.lbrn2"
    exported.write_bytes(lightburn(EXPORTED))
    for plan in ({"mode": pl.MODE_VECTOR, "exports": [{"number": 1, "path": str(exported)}]}, {"mode": pl.MODE_VECTOR, "exports": []}, None,
                 {"mode": pl.MODE_PLATE, "exports": [{"number": 1, "path": str(exported)}]}):
        project = parse(moved(EXPORTED, keep=(4,))) if plan and plan["mode"] == pl.MODE_PLATE else parse(EXPORTED)
        report = report_of(project)
        ingest._leave_out_layers(project, plan, report)
        assert report["warnings"] == [] and all(l.regions for l in project.layers) and not any("left_out" in l for l in report["layers"])
