"""Image -> editable vectors -> LightBurn Path shapes (REQ-021, DEC-065)."""
import json
import math
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest

from titanium_platform import lightburn as lb, vectorize as vz

WHITE, RED, BLUE, BLACK = (255, 255, 255), (200, 30, 30), (30, 30, 200), (0, 0, 0)
SVG = "{http://www.w3.org/2000/svg}"


def canvas(h, w, rgb=WHITE):
    return np.full((h, w, 3), rgb, np.uint8)


def ring(fg=BLACK, inner=WHITE):
    img = canvas(100, 100)
    cv2.circle(img, (50, 50), 35, fg, -1)
    cv2.circle(img, (50, 50), 15, inner, -1)
    return img


def shoelace(points) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]))) / 2


def project(document, layers: dict) -> lb.Project:
    """A minimal .lbrn2 around the shapes, with one CutSetting per used layer index."""
    settings = "".join(f'    <CutSetting type="Scan"><index Value="{i}"/><name Value="C{i:02d}"/><maxPower Value="40"/>'
                       f'<speed Value="1000"/><frequency Value="40000"/></CutSetting>\n' for i in sorted(set(layers.values())))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="2.0.04" FormatVersion="1" MirrorX="False" MirrorY="False">\n'
           + settings + "".join(vz.to_lbrn2_shapes(document, layers)) + "</LightBurnProject>\n")
    return lb.parse_bytes(xml.encode("utf-8"))


def test_a_ring_is_one_region_whose_hole_is_kept():
    doc = vz.trace(ring(), 50.0, "fill")
    assert len(doc["regions"]) == 1
    r = doc["regions"][0]
    assert r["task"] == "fill" and r["layer_key"] == "fill" and r["srgb"] == [0, 0, 0]
    assert len(r["loops"]) == 2                      # outer boundary, then the hole
    assert r["pixels"] == int((ring()[..., 0] < 128).sum())      # outlines follow pixel edges: area == pixel count
    assert vz.region_area_mm2(r) == pytest.approx(r["pixels"] * doc["px_mm"] ** 2, rel=0.01)
    outer, hole = r["loops"]
    xs = [p[0] for p in outer]
    assert min(xs) == pytest.approx(7.5, abs=0.5) and max(xs) == pytest.approx(42.5, abs=0.5)   # 15..85 px of 0.5 mm
    assert shoelace(hole) == pytest.approx(math.pi * 7.5 ** 2, rel=0.05)
    assert doc["size_mm"] == {"width": 50.0, "height": 50.0}


def test_two_colours_side_by_side_are_two_regions_with_the_palette_colours_preserved():
    img = canvas(40, 80)
    img[:, :40], img[:, 40:] = RED, BLUE
    doc = vz.trace(img, 80.0, "color", colors=[RED, BLUE])
    assert [(r["srgb"], r["layer_key"], r["task"], r["pixels"]) for r in doc["regions"]] == [
        (list(RED), "c0", "color", 1600), (list(BLUE), "c1", "color", 1600)]
    left, right = (r["loops"] for r in doc["regions"])
    assert sorted(map(tuple, left[0])) == [(0, 0), (0, 40), (40, 0), (40, 40)]
    assert sorted(map(tuple, right[0])) == [(40, 0), (40, 40), (80, 0), (80, 40)]    # neighbours share their border
    assert doc["regions"][0]["lab"] == pytest.approx(vz.color.srgb8_to_lab(np.array(RED, float)).tolist(), abs=1e-3)


def test_k_means_finds_the_colours_of_the_image_when_no_palette_is_given():
    img = canvas(40, 90)
    img[:, 30:60], img[:, 60:] = RED, BLUE
    doc = vz.trace(img, 90.0, "color", n_colors=3)
    colours = [r["srgb"] for r in doc["regions"]]
    assert len(colours) == 3 and colours[0] == list(WHITE)                       # lightest first
    for expected in (WHITE, RED, BLUE):
        assert min(np.abs(np.array(c) - expected).max() for c in colours) <= 1
    assert [r["layer_key"] for r in doc["regions"]] == ["c0", "c1", "c2"]


def test_text_strokes_are_closed_outlines_with_their_counters_as_holes():
    img = canvas(60, 200)
    cv2.putText(img, "TOB", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.6, BLACK, 4)
    doc = vz.trace(img, 40.0, "text", min_area_mm2=0.05)
    assert {r["task"] for r in doc["regions"]} == {"text"} and all(not r["strokes"] for r in doc["regions"])
    assert sorted(len(r["loops"]) for r in doc["regions"]) == [1, 2, 3]          # T, O (one counter), B (two)
    for r in doc["regions"]:
        for loop in r["loops"]:
            assert loop[0] != loop[-1] and len(loop) >= 3                         # closed implicitly, never repeated
    traced = sum(r["pixels"] for r in doc["regions"])
    assert traced == pytest.approx(int((img[..., 0] <= doc["threshold"]).sum()), abs=5)


def test_a_line_drawing_becomes_centre_line_polylines():
    img = canvas(120, 160)
    cv2.line(img, (10, 20), (150, 20), BLACK, 5)
    cv2.polylines(img, [np.array([(20, 40), (60, 100), (100, 45)])], False, BLACK, 5)
    cv2.circle(img, (130, 80), 25, BLACK, 4)
    doc = vz.trace(img, 160.0, "line", tolerance_mm=0.6)
    assert len(doc["regions"]) == 3 and all(r["task"] == "line" and not r["loops"] for r in doc["regions"])
    by_left = sorted(doc["regions"], key=lambda r: min(p[0] for s in r["strokes"] for p in s))
    straight, vee, circle = by_left[0], by_left[1], by_left[2]
    assert len(straight["strokes"]) == 1 and len(straight["strokes"][0]) == 2   # one straight stroke: two points
    (x0, y0), (x1, y1) = straight["strokes"][0]
    assert {round(y0), round(y1)} == {20} and min(x0, x1) < 15 and max(x0, x1) > 145
    v = vee["strokes"][0]
    assert v[0] != v[-1] and len(vee["strokes"]) == 1
    assert max(p[1] for p in v) == pytest.approx(100, abs=4)                       # passes the drawn apex
    c = circle["strokes"][0]
    assert c[0] == c[-1] and len(c) > 8                                            # a closed centre-line cycle
    assert all(math.dist(p, (130.5, 80.5)) == pytest.approx(25, abs=2) for p in c)


def test_tiny_speckles_merge_into_the_region_around_them():
    img = canvas(100, 100)
    img[30:70, 30:70] = RED
    for y, x in [(5, 5), (10, 80), (50, 50), (40, 60), (90, 20)]:
        img[y:y + 2, x:x + 2] = BLACK                                           # 2 x 2 px = 0.16 mm2 at 0.2 mm/px
    palette = [WHITE, RED, BLACK]
    noisy = vz.trace(img, 20.0, "color", colors=palette, min_area_mm2=0)
    assert sum(r["layer_key"] == "c2" for r in noisy["regions"]) == 5
    doc = vz.trace(img, 20.0, "color", colors=palette, min_area_mm2=0.2)
    assert [(r["layer_key"], len(r["loops"]), r["pixels"]) for r in doc["regions"]] == [("c0", 2, 8400), ("c1", 1, 1600)]


def test_changing_the_tolerance_re_simplifies_from_the_stored_contours():
    img = canvas(200, 200)
    cv2.circle(img, (100, 100), 80, BLACK, -1)
    doc = vz.trace(img, 20.0, "fill", tolerance_mm=0.01)
    fine = doc["regions"][0]["loops"][0]
    coarse_doc = vz.edit(doc, {"op": "set_tolerance", "tolerance_mm": 0.3})
    coarse = coarse_doc["regions"][0]["loops"][0]
    assert coarse_doc["tolerance_mm"] == 0.3 and len(coarse) < len(fine) / 4
    assert shoelace(coarse) == pytest.approx(shoelace(fine), rel=0.03)
    assert coarse_doc["regions"][0]["raw"] == doc["regions"][0]["raw"]
    back = vz.edit(coarse_doc, {"op": "set_tolerance", "tolerance_mm": 0.01})
    assert back["regions"][0]["loops"][0] == fine


def test_delete_removes_one_region_and_never_changes_the_input_document():
    img = canvas(40, 80)
    img[:, :40], img[:, 40:] = RED, BLUE
    doc = vz.trace(img, 80.0, "color", colors=[RED, BLUE])
    before = json.dumps(doc)
    out = vz.edit(doc, {"op": "delete", "region": "r1"})
    assert [r["id"] for r in out["regions"]] == ["r2"] and json.dumps(doc) == before
    with pytest.raises(vz.VectorizeError):
        vz.edit(doc, {"op": "delete", "region": "r9"})


def test_task_and_settings_group_of_a_region_can_be_changed():
    doc = vz.trace(ring(), 50.0, "fill")
    out = vz.edit(vz.edit(doc, {"op": "set_task", "region": "r1", "task": "tonal"}),
                  {"op": "set_layer", "region": "r1", "layer_key": "deep blue"})
    r = out["regions"][0]
    assert (r["task"], r["layer_key"]) == ("tonal", "deep blue")
    assert (r["srgb"], r["pixels"], r["raw"]) == (doc["regions"][0]["srgb"], doc["regions"][0]["pixels"], doc["regions"][0]["raw"])
    with pytest.raises(vz.VectorizeError):
        vz.edit(doc, {"op": "set_task", "region": "r1", "task": "cut"})
    line = canvas(40, 80)
    cv2.line(line, (5, 20), (75, 20), BLACK, 3)
    with pytest.raises(vz.VectorizeError, match="centre-line"):
        vz.edit(vz.trace(line, 80.0, "line"), {"op": "set_task", "region": "r1", "task": "fill"})


def test_merging_neighbours_unites_their_outline_in_the_first_regions_colour_and_group():
    img = canvas(40, 80)
    img[:, :40], img[:, 40:] = RED, BLUE
    doc = vz.trace(img, 80.0, "color", colors=[RED, BLUE])
    out = vz.edit(doc, {"op": "merge", "regions": ["r2", "r1"]})
    assert len(out["regions"]) == 1
    r = out["regions"][0]
    assert (r["id"], r["srgb"], r["layer_key"], r["pixels"]) == ("r2", list(BLUE), "c1", 3200)
    assert len(r["loops"]) == 1 and sorted(map(tuple, r["loops"][0])) == [(0, 0), (0, 40), (80, 0), (80, 40)]


def test_merging_a_disc_into_the_ring_around_it_fills_the_hole():
    doc = vz.trace(ring(RED, BLUE), 50.0, "color", colors=[WHITE, RED, BLUE])
    ring_id, disc_id = (r["id"] for r in doc["regions"][1:])
    out = vz.edit(doc, {"op": "merge", "regions": [ring_id, disc_id]})
    merged = next(r for r in out["regions"] if r["id"] == ring_id)
    assert len(merged["loops"]) == 1 and merged["srgb"] == list(RED)
    assert merged["pixels"] == sum(r["pixels"] for r in doc["regions"][1:])
    with pytest.raises(vz.VectorizeError):
        vz.edit(doc, {"op": "merge", "regions": [ring_id, ring_id]})


def test_the_same_input_gives_an_identical_document():
    rng = np.random.default_rng(7)
    img = cv2.GaussianBlur(rng.integers(0, 256, (120, 150, 3), dtype=np.uint8), (15, 15), 4)
    first = vz.trace(img, 30.0, "color", n_colors=5)
    second = vz.trace(img.copy(), 30.0, "color", n_colors=5)
    assert len(first["regions"]) > 5
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert json.loads(json.dumps(first)) == first                                  # plain JSON, nothing lost


def test_svg_preview_is_well_formed_one_path_per_region_and_weak_regions_are_hatched():
    doc = vz.trace(ring(RED, BLUE), 50.0, "color", colors=[WHITE, RED, BLUE])
    weak = doc["regions"][1]["id"]
    root = ET.fromstring(vz.to_svg(doc, weak={weak}))
    assert root.get("viewBox") == "0 0 50 50"
    paths = root.findall(f"{SVG}path")
    assert [p.get("data-region") for p in paths] == [r["id"] for r in doc["regions"]]
    assert all(p.get("fill-rule") == "evenodd" for p in paths)
    by_id = {p.get("data-region"): p for p in paths}
    assert by_id[doc["regions"][2]["id"]].get("fill") == "#1e1ec8"
    hatched = by_id[weak]
    assert hatched.get("fill").startswith("url(#") and hatched.get("stroke-dasharray") and hatched.get("stroke") == vz.WEAK
    assert root.find(f"{SVG}defs/{SVG}pattern") is not None
    lines = canvas(40, 80)
    cv2.line(lines, (5, 20), (75, 20), BLACK, 3)
    stroke = ET.fromstring(vz.to_svg(vz.trace(lines, 80.0, "line"))).find(f"{SVG}path")
    assert stroke.get("fill") == "none" and stroke.get("stroke") == "#000000" and "Z" not in stroke.get("d")


def test_lightburn_paths_round_trip_closed_with_holes_and_their_areas():
    doc = vz.trace(ring(RED, BLUE), 50.0, "color", colors=[WHITE, RED, BLUE])
    layers = {"c0": 0, "c1": 5, "c2": 29}
    parsed = project(doc, layers)
    assert [l.index for l in parsed.layers] == [0, 5, 29]
    for region in doc["regions"]:
        found = parsed.layer(layers[region["layer_key"]]).regions
        assert len(found) == 1 and found[0].closed and found[0].kind == "path"
        assert len(found[0].holes) == len(region["loops"]) - 1
        area = shoelace(found[0].polygon) - sum(shoelace(h) for h in found[0].holes)
        assert area == pytest.approx(vz.region_area_mm2(region), rel=0.01)
        assert area == pytest.approx(region["pixels"] * doc["px_mm"] ** 2, rel=0.01)
    assert len(parsed.layer(5).regions[0].holes) == 1                             # the ring keeps its hole


def test_lightburn_paths_of_line_art_stay_open_and_the_offset_is_the_shape_transform():
    img = canvas(60, 120)
    cv2.line(img, (10, 15), (110, 15), BLACK, 4)
    cv2.line(img, (10, 45), (110, 45), BLACK, 4)
    doc = vz.trace(img, 120.0, "line")
    parsed = project(doc, {"line": 3})
    found = parsed.layer(3).regions
    assert len(found) == 2 and not any(r.closed for r in found)
    shifted = vz.to_lbrn2_shapes(doc, lambda key: 3, offset=(10.0, -2.5))
    assert all("<XForm>1 0 0 1 10.00000 -2.50000</XForm>" in s for s in shifted)


@pytest.mark.parametrize("index", [30, -1, 31, True, 2.0])
def test_a_layer_outside_lightburns_output_colours_is_refused(index):
    doc = vz.trace(ring(), 50.0, "fill")
    with pytest.raises(vz.VectorizeError):
        vz.to_lbrn2_shapes(doc, {"fill": index})
    with pytest.raises(vz.VectorizeError, match="settings group"):
        vz.to_lbrn2_shapes(doc, {})


@pytest.mark.parametrize("kwargs", [
    {"strategy": "tonal"},
    {"strategy": "color"},                                                          # neither palette nor count
    {"strategy": "color", "colors": [RED], "n_colors": 2},
    {"strategy": "color", "colors": [(300, 0, 0)]},
    {"strategy": "color", "n_colors": 31},
    {"strategy": "fill", "width_mm": 0},
    {"strategy": "fill", "threshold": 300},
    {"strategy": "fill", "tolerance_mm": -1},
])
def test_invalid_requests_are_refused(kwargs):
    args = {"width_mm": 50.0, **kwargs}
    with pytest.raises(vz.VectorizeError):
        vz.trace(ring(), args.pop("width_mm"), args.pop("strategy"), **args)
