"""A photograph split into gapless colour regions, faces first (REQ-033, DEC-076)."""
import json
import math
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest

from titanium_platform import faces, lightburn as lb, segment as sg, vectorize as vz

SVG = "{http://www.w3.org/2000/svg}"
PAPER, RED, YELLOW, BLUE = (235, 230, 215), (200, 40, 40), (240, 200, 40), (30, 40, 200)


def shapes(h=180, w=240):
    """Several colours with curved borders: a ring, a turned ellipse, a wavy band, a disc and a slanted line."""
    img = np.full((h, w, 3), PAPER, np.uint8)
    cv2.circle(img, (60, 70), 45, RED, -1)
    cv2.circle(img, (60, 70), 18, PAPER, -1)
    cv2.ellipse(img, (170, 55), (50, 25), 25, 0, 360, BLUE, -1)
    xs = np.arange(0, w + 1)
    band = np.concatenate([np.stack([xs, 125 + 12 * np.sin(xs / 19)], 1), [[w, h], [0, h]]]).astype(np.int32)
    cv2.fillPoly(img, [band], (40, 150, 70))
    cv2.circle(img, (195, 150), 22, YELLOW, -1)
    cv2.line(img, (0, 178), (240, 100), (25, 25, 25), 5)
    return img


def photo_like(h=160, w=200, seed=5):
    """Smooth colour fields with soft blots and sensor-like noise."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    img = np.stack([120 + 80 * np.sin(xx / 37), 110 + 70 * np.cos(yy / 29), 140 + 60 * np.sin((xx + yy) / 45)], axis=-1)
    for _ in range(14):
        cv2.circle(img, (int(rng.integers(0, w)), int(rng.integers(0, h))), int(rng.integers(6, 25)),
                   rng.integers(0, 256, 3).tolist(), -1)
    img = cv2.GaussianBlur(img, (0, 0), 1.5) + rng.normal(0, 12, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def ring_picture():
    img = np.full((120, 120, 3), PAPER, np.uint8)
    cv2.circle(img, (60, 60), 42, RED, -1)
    cv2.circle(img, (60, 60), 20, PAPER, -1)
    return img


def outline_area(loops) -> float:
    """Area of an outer loop less its holes (even-odd), mm²."""
    return sum((-1 if i else 1) * abs(vz._signed_area(loop)) for i, loop in enumerate(loops))


def region_at(document, x_mm, y_mm):
    """The region whose outline (even-odd) contains the point."""
    for r in sg.regions_as_loops(document):
        inside = sum(cv2.pointPolygonTest(np.asarray(loop, np.float32), (x_mm, y_mm), False) > 0 for loop in r["loops"])
        if inside % 2:
            return r
    return None


def centroids(document):
    """The centre (in pixels) and pixel count of every region."""
    out = []
    for r in sg.regions_as_loops(document):
        outer = np.asarray(r["loops"][0])
        out.append(((outer.mean(axis=0) / document["px_mm"]).tolist(), r["pixels"]))
    return out


def colour_index(document, rgb):
    lab = sg.color.srgb8_to_lab(np.array(rgb, float))
    return min(document["palette"], key=lambda p: float(np.linalg.norm(np.array(p["lab"]) - lab)))["index"]


# -- gapless ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("make, n_colors", [(shapes, 7), (photo_like, 12)])
def test_regions_cover_the_picture_without_gaps_or_overlaps(make, n_colors):
    img = make()
    doc = sg.segment(img, 0.25 * img.shape[1], n_colors, use_faces=False)
    regions = sg.regions_as_loops(doc)
    assert len(regions) == len(doc["regions"]) > n_colors
    cov = sg.coverage([r["loops"] for r in regions], doc["size_mm"]["width"], doc["size_mm"]["height"], 16)   # 4 per pixel
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005
    assert sum(r["pixels"] for r in doc["regions"]) == img.shape[0] * img.shape[1]
    total = sum(outline_area(r["loops"]) for r in regions)
    assert total == pytest.approx(doc["size_mm"]["width"] * doc["size_mm"]["height"], rel=0.005)


def test_the_coverage_measure_finds_gaps_and_overlaps():
    left = [[[0, 0], [5, 0], [5, 10], [0, 10]]]
    right = [[[5, 0], [10, 0], [10, 10], [5, 10]]]
    assert sg.coverage([left, right], 10, 10, 8) == {"uncovered": 0.0, "overlap": 0.0}
    assert sg.coverage([left], 10, 10, 8) == {"uncovered": 0.5, "overlap": 0.0}
    wide = [[[0, 0], [6, 0], [6, 10], [0, 10]]]
    assert sg.coverage([wide, right], 10, 10, 8) == {"uncovered": 0.0, "overlap": pytest.approx(0.1)}
    framed = [[[0, 0], [10, 0], [10, 10], [0, 10]], [[2, 2], [8, 2], [8, 8], [2, 8]]]             # a frame and its hole
    assert sg.coverage([framed], 10, 10, 8)["uncovered"] == pytest.approx(0.36)


def walks(loops, points) -> bool:
    """Whether one of the closed outlines runs through exactly these points in this order (a straight two-point arc may
    have its midpoint added as the outline's start)."""
    halfway = [round((a + b) / 2, 5) for a, b in zip(*points)] if len(points) == 2 else None
    for loop in loops:
        n = len(loop)
        for i in (i for i, p in enumerate(loop) if p == points[0]):
            run = [loop[(i + k) % n] for k in range(len(points) + 1)]
            if run[:len(points)] == points or (halfway and run == [points[0], halfway, points[1]]):
                return True
    return False


def test_every_border_is_one_shared_arc_walked_both_ways_by_its_two_regions():
    doc = sg.segment(shapes(), 60.0, 7, use_faces=False)
    outlines = {r["id"]: r["loops"] for r in sg.regions_as_loops(doc)}
    uses = {}
    for r in doc["regions"]:
        assert r["loops"]
        for ref in (ref for loop in r["loops"] for ref in loop):
            uses.setdefault(ref if ref >= 0 else ~ref, []).append((r["id"], ref >= 0))
    for arc in doc["arcs"]:
        expected = ([(arc["left"], True)] if arc["left"] else []) + ([(arc["right"], False)] if arc["right"] else [])
        assert sorted(uses[arc["id"]], key=lambda u: not u[1]) == expected          # once forward on its left, once back
        assert arc["left"] or arc["right"]
        if arc["left"]:
            assert walks(outlines[arc["left"]], arc["points"])
        if arc["right"]:
            assert walks(outlines[arc["right"]], arc["points"][::-1])              # the very same points, walked back
    assert sum(1 for arc in doc["arcs"] if arc["left"] and arc["right"]) > 10
    assert any(arc["closed"] for arc in doc["arcs"])                                # the ring's hole has no junction


@pytest.mark.parametrize("seed", range(4))
def test_the_loops_of_every_region_enclose_exactly_its_pixels_also_where_regions_touch_at_a_corner(seed):
    classes = np.random.default_rng(seed).integers(0, 3, (14, 17)).astype(np.int32)     # many diagonal touches
    region, _ = sg._components(classes, 3)
    arcs, loops = sg._planar_map(region)
    cols = region.shape[1] + 1
    centres = [(x + 0.5, y + 0.5) for y in range(region.shape[0]) for x in range(region.shape[1])]
    for r, region_loops in enumerate(loops):
        polygons = []
        for loop in region_loops:
            path = []
            for ref in loop:
                vertices = arcs[ref][0] if ref >= 0 else arcs[~ref][0][::-1]
                assert not path or path[-1] == vertices[0]                       # each arc starts where the last ended
                path += vertices if not path else vertices[1:]
            assert path[0] == path[-1]
            polygons.append(np.array([(v % cols, v // cols) for v in path[:-1]], np.float32))
        signs = [vz._signed_area(p) < 0 for p in polygons]
        assert signs[0] and not any(signs[1:])                                   # one outer boundary, then holes
        inside = [sum(cv2.pointPolygonTest(p, c, False) > 0 for p in polygons) % 2 == 1 for c in centres]
        assert inside == (region.ravel() == r).tolist()


def test_a_ring_keeps_its_hole_and_its_area():
    doc = sg.segment(ring_picture(), 60.0, 2, use_faces=False)
    assert len(doc["regions"]) == 3                                               # paper outside, the ring, paper inside
    ring = next(r for r in sg.regions_as_loops(doc) if r["color"] == colour_index(doc, RED))
    assert len(ring["loops"]) == 2
    px2 = doc["px_mm"] ** 2
    assert outline_area(ring["loops"]) == pytest.approx(ring["pixels"] * px2, rel=0.02)
    assert abs(vz._signed_area(ring["loops"][1])) == pytest.approx(math.pi * 20 ** 2 * px2, rel=0.05)
    inner = region_at(doc, 30.0, 30.0)
    assert inner["color"] == colour_index(doc, PAPER) and len(inner["loops"]) == 1 and inner["id"] != doc["regions"][0]["id"]


# -- colours ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n_colors", [2, 5, 29])
def test_the_split_never_has_more_colours_than_chosen(n_colors):
    img = photo_like()
    doc = sg.segment(img, 50.0, n_colors, use_faces=False)
    assert 1 <= len(doc["palette"]) <= n_colors and doc["n_colors"] == n_colors
    assert [p["index"] for p in doc["palette"]] == list(range(len(doc["palette"])))
    assert {r["color"] for r in doc["regions"]} == set(range(len(doc["palette"])))
    assert sum(p["pixels"] for p in doc["palette"]) == img.shape[0] * img.shape[1]
    assert [p["lab"][0] for p in doc["palette"]] == sorted((p["lab"][0] for p in doc["palette"]), reverse=True)  # lightest first
    for r in doc["regions"]:
        assert r["lab"] == doc["palette"][r["color"]]["lab"] and r["srgb"] == doc["palette"][r["color"]]["srgb"]


def test_a_picture_of_three_colours_keeps_them_even_when_more_are_allowed():
    img = np.full((60, 90, 3), PAPER, np.uint8)
    img[:, 30:60], img[:, 60:] = RED, BLUE
    doc = sg.segment(img, 45.0, 8, use_faces=False)
    assert len(doc["palette"]) == 3 and len(doc["regions"]) == 3
    for rgb in (PAPER, RED, BLUE):
        assert min(np.abs(np.array(p["srgb"]) - rgb).max() for p in doc["palette"]) <= 2


@pytest.mark.parametrize("n_colors", [1, 30, 0, -3, 2.5, True, "5", None])
def test_the_number_of_colours_must_be_from_2_to_29(n_colors):
    with pytest.raises(ValueError, match="number of colours"):
        sg.segment(shapes(), 60.0, n_colors, use_faces=False)


@pytest.mark.parametrize("kwargs", [{"width_mm": 0}, {"width_mm": "wide"}, {"min_area_mm2": -1}, {"tolerance_mm": float("nan")},
                                    {"seed": -1}, {"important": [{"polygon": [[0, 0], [1, 1]]}]}, {"image": np.zeros((10, 10))},
                                    {"superpixels": 5}, {"superpixels": 80.5}])
def test_invalid_settings_are_refused(kwargs):
    args = {"image": shapes(), "width_mm": 60.0, **kwargs}
    with pytest.raises(ValueError):
        sg.segment(args.pop("image"), args.pop("width_mm"), 5, use_faces=False, **args)


def test_fewer_superpixels_across_the_picture_make_larger_superpixels_and_follow_only_the_larger_edges():
    img = photo_like()
    fine = sg.segment(img, 60.0, 8, use_faces=False, min_area_mm2=0)
    coarse = sg.segment(img, 60.0, 8, use_faces=False, min_area_mm2=0, superpixels=20)
    assert fine["superpixels"] == sg.SUPERPIXELS_ACROSS and coarse["superpixels"] == 20
    assert coarse["superpixel_px"]["coarse"] == round(200 / 20) > fine["superpixel_px"]["coarse"]
    assert len(coarse["regions"]) < len(fine["regions"])


# -- important areas ------------------------------------------------------------------------------------------------------
def blots(h=240, w=360, seed=11):
    """Small blots of many colours on paper; the picture twice, side by side."""
    rng = np.random.default_rng(seed)
    half = np.full((h, w, 3), (205, 195, 175), np.uint8)
    for _ in range(140):
        cv2.circle(half, (int(rng.integers(0, w)), int(rng.integers(0, h))), int(rng.integers(2, 6)),
                   rng.integers(20, 236, 3).tolist(), -1)
    return np.hstack([half, half])


def counted(doc, x0, x1, y0, y1):
    inside = [pixels for (x, y), pixels in centroids(doc) if x0 <= x < x1 and y0 <= y < y1]
    return len(inside), float(np.median(inside))


def test_an_area_marked_by_hand_gets_more_and_smaller_regions_than_the_same_content_outside_it():
    img = blots()
    marked = {"polygon": [[20, 20], [340, 20], [340, 220], [20, 220]]}           # the left copy, less a margin
    doc = sg.segment(img, 72.0, 8, important=[marked], use_faces=False, min_area_mm2=0.5)
    assert doc["important"] == [faces.check_area(marked)] and doc["important"][0]["source"] == "manual"
    assert doc["superpixel_px"]["fine"] < doc["superpixel_px"]["coarse"]
    inside, inside_median = counted(doc, 20, 340, 20, 220)
    outside, outside_median = counted(doc, 380, 700, 20, 220)                     # the same blots in the right copy
    assert inside > 1.3 * outside and inside_median < outside_median
    unmarked = sg.segment(img, 72.0, 8, use_faces=False, min_area_mm2=0.5)          # removing the area splits it normally again
    assert unmarked["important"] == [] and counted(unmarked, 20, 340, 20, 220)[0] < inside


def test_eyes_get_finer_regions_than_the_rest_of_the_face(monkeypatch):
    img = blots()
    box = [[0, 0], [720, 0], [720, 240], [0, 240]]
    detected = faces.face_areas(box, [(180, 120), (540, 120)], [(300, 200), (420, 200)], 0.9)
    eye = {**detected[1], "ellipse": {"center": [180, 120], "axes": [150, 95], "angle": 0}}
    monkeypatch.setattr(faces, "important_areas", lambda image: faces.FaceSearch([detected[0], eye], 1))
    doc = sg.segment(img, 72.0, 8, min_area_mm2=0.5)
    assert doc["faces"] == {"searched": True, "found": 1, "error": None}
    assert [(a["kind"], a["source"]) for a in doc["important"]] == [("face", "detected"), ("eye", "detected")]
    in_eye, eye_median = counted(doc, 80, 280, 60, 180)
    in_face, face_median = counted(doc, 440, 640, 60, 180)                          # the same blots, face only
    assert in_eye > 1.3 * in_face and eye_median < face_median
    assert any(r["important"] for r in doc["regions"]) and not all(r["important"] for r in doc["regions"])


def test_a_picture_without_a_face_is_split_normally_and_says_so():
    doc = sg.segment(shapes(), 60.0, 6)
    assert doc["faces"] == {"searched": True, "found": 0, "error": None} and doc["important"] == []
    assert len(doc["regions"]) > 6
    assert sg.segment(shapes(), 60.0, 6, use_faces=False)["faces"] == {"searched": False, "found": 0, "error": None}


def test_a_detector_failure_is_reported_and_the_picture_still_split(monkeypatch):
    monkeypatch.setattr(faces, "_yunet", lambda bgr: (_ for _ in ()).throw(cv2.error("no model")))
    doc = sg.segment(shapes(), 60.0, 6)
    assert doc["faces"]["found"] == 0 and "no model" in doc["faces"]["error"] and doc["regions"]


def test_small_regions_merge_into_the_neighbour_of_nearest_colour_except_inside_important_areas():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :50], img[:, 50:] = RED, YELLOW
    img[18:24, 48:54] = BLUE              # mostly on the yellow side, but blue is nearer to red than to yellow
    img[76:82, 48:54] = BLUE              # the same speck inside an area marked by hand
    marked = {"ellipse": {"center": [51, 79], "axes": [12, 12]}}
    doc = sg.segment(img, 25.0, 3, important=[marked], use_faces=False, min_area_mm2=4.0)   # 36 px = 2.25 mm²
    red, blue = colour_index(doc, RED), colour_index(doc, BLUE)
    merged = region_at(doc, 51 * 0.25, 21 * 0.25)
    kept = region_at(doc, 51 * 0.25, 79 * 0.25)
    assert merged["color"] == red and merged["pixels"] > 2000
    assert kept["color"] == blue and kept["important"] and kept["pixels"] < 100
    assert all(r["pixels"] * doc["px_mm"] ** 2 >= 4.0 or r["important"] for r in doc["regions"])


# -- determinism and the rest of the application ------------------------------------------------------------------------
def test_the_same_picture_and_settings_give_the_same_document():
    img = photo_like()
    first = sg.segment(img, 50.0, 9, use_faces=False, seed=3)
    second = sg.segment(img.copy(), 50.0, 9, use_faces=False, seed=3)
    assert json.dumps(first) == json.dumps(second)
    assert json.loads(json.dumps(first)) == first                                  # plain JSON, nothing lost


def test_regions_export_to_lightburn_closed_with_their_holes_and_areas():
    doc = sg.segment(shapes(), 60.0, 7, use_faces=False)
    regions = sg.regions_as_loops(doc)
    layers = {f"c{p['index']}": p["index"] for p in doc["palette"]}
    settings = "".join(f'<CutSetting type="Scan"><index Value="{i}"/><name Value="C{i:02d}"/><maxPower Value="40"/>'
                       f'<speed Value="1000"/><frequency Value="40000"/></CutSetting>' for i in layers.values())
    xml = ('<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="2.0.04" FormatVersion="1">' + settings
           + "".join(vz.to_lbrn2_shapes({"regions": regions}, layers)) + "</LightBurnProject>")
    parsed = lb.parse_bytes(xml.encode("utf-8"))
    back = {r: [] for r in layers.values()}
    for layer in parsed.layers:
        back[layer.index] += layer.regions
    assert sum(len(v) for v in back.values()) == len(regions)
    for index in layers.values():
        mine = sorted((outline_area(r["loops"]), len(r["loops"]) - 1) for r in regions if r["color"] == index)
        read = sorted((outline_area([p.polygon] + p.holes), len(p.holes)) for p in back[index])
        assert all(p.closed and p.kind == "path" for p in back[index])
        assert [holes for _, holes in read] == [holes for _, holes in mine]       # every hole read back as a hole
        for (a, _), (b, _) in zip(mine, read):
            assert b == pytest.approx(a, rel=0.01)
    assert max(len(p.holes) for v in back.values() for p in v) >= 1                 # the ring
    cov = sg.coverage([[p.polygon] + p.holes for v in back.values() for p in v], doc["size_mm"]["width"], doc["size_mm"]["height"], 16)
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005


def test_the_svg_preview_fills_every_region_with_its_colour_or_the_assigned_one():
    doc = sg.segment(shapes(), 60.0, 7, use_faces=False)
    root = ET.fromstring(sg.to_svg(doc))
    paths = root.findall(f"{SVG}path")
    assert root.get("viewBox") == f"0 0 60 {vz._num(doc['size_mm']['height'])}"
    assert [p.get("data-region") for p in paths] == [r["id"] for r in doc["regions"]]
    assert all(p.get("fill-rule") == "evenodd" and p.get("fill") == p.get("stroke") for p in paths)
    first = doc["regions"][0]
    assert paths[0].get("fill") == "#{:02x}{:02x}{:02x}".format(*doc["palette"][first["color"]]["srgb"])
    titanium = ET.fromstring(sg.to_svg(doc, {first["color"]: [12, 34, 56]})).findall(f"{SVG}path")
    assert {p.get("fill") for p, r in zip(titanium, doc["regions"]) if r["color"] == first["color"]} == {"#0c2238"}
    assert all(p.get("fill") == q.get("fill") for p, q, r in zip(titanium, paths, doc["regions"]) if r["color"] != first["color"])
    with pytest.raises(ValueError):
        sg.to_svg(doc, {0: [300, 0, 0]})
