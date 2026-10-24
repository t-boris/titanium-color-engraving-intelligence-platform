"""A photograph split into gapless colour regions, faces first (REQ-033, DEC-076)."""
import itertools
import json
import math
import re
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest

from titanium_platform import faces, lightburn as lb, photo_zones as pz, segment as sg, vectorize as vz

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


def raster(doc):
    """The region index and the palette colour of every pixel of the working picture."""
    index = pz.labels(doc, {r["id"]: r["loops"] for r in sg.regions_as_loops(doc)})
    return index, np.array([r["color"] for r in doc["regions"]])[index]


def test_an_eye_given_a_finer_detail_gets_more_regions_and_the_split_outside_it_stays_as_it_was():
    """vector-detail-and-colour-control I-3 (overview criterion 3): an eye's own detail, the colour centres of the split kept, so that
    the borders and colours outside the changed eye are those of the split before (clustered anew, a fifth of them changed colour)."""
    img = photo_like(300, 450, seed=4)
    eye = {"kind": "eye", "source": "manual", "score": None, "ellipse": {"center": [140, 150], "axes": [60, 45], "angle": 20}}
    other = {"kind": "eye", "source": "manual", "score": None, "ellipse": {"center": [320, 150], "axes": [55, 40], "angle": 0}}
    split = {"use_faces": False, "min_area_mm2": 0.05, "superpixels": 25}                # coarse enough for the details to differ
    before = sg.segment(img, 45.0, 8, important=[eye, other], **split)
    assert sg.segment(img, 45.0, 8, important=[eye, other], **split, centres=before["centres"]) == before
    after = sg.segment(img, 45.0, 8, important=[{**eye, "detail": "finest"}, other], **split, centres=before["centres"])
    assert [a.get("detail") for a in after["important"]] == ["finest", None] and len(after["regions"]) > len(before["regions"])
    margin = 2 * before["superpixel_px"]["coarse"]
    near = faces.area_mask({**eye, "ellipse": {**eye["ellipse"], "axes": [60 + margin, 45 + margin]}}, img.shape[:2])
    (index0, colour0), (index1, colour1) = raster(before), raster(after)
    lab0, lab1 = ({p["index"]: p["lab"] for p in d["palette"]} for d in (before, after))
    same = {i: min(lab1, key=lambda k: sum((a - b) ** 2 for a, b in zip(lab0[i], lab1[k]))) for i in lab0}
    outside = ~near
    assert (np.vectorize(same.get)(colour0) == colour1)[outside].mean() >= 0.995
    for axis in (0, 1):                                                                 # the borders between pixels, outside the eye
        edge0, edge1 = (np.diff(index, axis=axis) != 0 for index in (index0, index1))
        keep = outside[:-1, :] & outside[1:, :] if axis == 0 else outside[:, :-1] & outside[:, 1:]
        assert (edge0 == edge1)[keep].mean() >= 0.995
    inside = faces.area_mask(eye, img.shape[:2])
    assert len(np.unique(index1[inside])) > len(np.unique(index0[inside]))              # more regions inside the eye


def test_a_detail_is_one_of_four_and_only_an_eye_the_lips_or_a_marked_area_has_one():
    eye = {"kind": "eye", "ellipse": {"center": [10, 10], "axes": [5, 4], "angle": 0}}
    assert [faces.check_area({**eye, "detail": d})["detail"] for d in faces.DETAILS] == list(faces.DETAILS)
    assert "detail" not in faces.check_area(eye)
    for area, message in [({**eye, "detail": "huge"}, "the detail of an important area must be one of"),
                          ({**eye, "kind": "face", "detail": "fine"}, "only an eye, the lips or a marked area")]:
        with pytest.raises(ValueError, match=message):
            faces.check_area(area)
    for centres in ([[50, 0]], [[50, 0, 0]] * 9, [[float("nan"), 0, 0]]):
        with pytest.raises(sg.SegmentError, match="colour centres"):
            sg.segment(shapes(), 60.0, 8, use_faces=False, centres=centres)


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



@pytest.mark.parametrize("smoothing", [0.0, 0.8])
def test_the_borders_of_the_editor_svg_outline_any_set_of_regions_as_its_merge_does(smoothing):
    """A selection is outlined as one shape (0.22.1): the borders with a region of the set on one side only are exactly the outline of
    the region a merge of that set makes (merges are made on the traced document), every border once, in the same curves as the regions."""
    traced = sg.segment(photo_like(), 50.0, 8, use_faces=False)
    doc = sg.smoothed(traced, smoothing)
    assert ET.fromstring(sg.to_svg(doc)).find(f"{SVG}g") is None                     # only the editor asks for them
    root = ET.fromstring(sg.to_svg(doc, borders=True))
    group = root.find(f"{SVG}g")
    assert group.get("class") == "vw-borders" and group.get("display") == "none"
    used = sorted({ref if ref >= 0 else ~ref for r in doc["regions"] for loop in r["loops"] for ref in loop})
    borders = {arc: (p.get("d"), set(p.get("data-sides").split(" "))) for arc, p in zip(used, group.findall(f"{SVG}path"), strict=True)}
    assert all(1 <= len(sides) <= 2 for _, sides in borders.values())
    curves = {p.get("data-region"): set(re.findall(r"C[^CMZ]+", p.get("d"))) for p in root.findall(f"{SVG}path[@data-region]")}
    tokens = lambda d: set(re.findall(r"C[^CMZ]+", d + " "))
    for arc, (d, sides) in borders.items():
        assert bool(tokens(d)) == bool(smoothing)
        if len(tokens(d)) >= 2:                              # a loop of single curves only is split in its first one (_loop_nodes)
            back = tokens(sg._arc_path({"nodes": sg._oriented(doc["arcs"][arc]["nodes"], True)}))
            assert all(tokens(d) <= curves[rid] or back <= curves[rid] for rid in sides)     # one side walks the border backwards
    rng = np.random.default_rng(3)
    for size in (2, 3, 6, 12):
        chosen = set(connected_set(traced, rng, size))
        outline = {arc for arc, (_, sides) in borders.items() if sides & chosen and not (len(sides) == 2 and sides <= chosen)}
        merged, keeper = sg.merge_regions(traced, chosen)
        kept = [i for i, arc in enumerate(traced["arcs"]) if not (arc["left"] in chosen and arc["right"] in chosen)]
        region = next(r for r in merged["regions"] if r["id"] == keeper)
        assert outline == {kept[ref if ref >= 0 else ~ref] for loop in region["loops"] for ref in loop}

# -- merging (the colour editor: REQ-047, REQ-048, DEC-076) ------------------------------------------------------------------
def pixel_document(region, of_class):
    """A segment document of a region map whose arcs keep their pixel corners as points (1 mm a pixel, no smoothing), so
    that every outline runs exactly along its pixels."""
    arcs, loops = sg._planar_map(region)
    h, w = region.shape
    name = [f"r{i + 1}" for i in range(len(of_class))]
    pixels = np.bincount(region.ravel(), minlength=len(of_class))
    labs = {c: [90.0 - 15 * c, 4.0 * c, -3.0 * c] for c in sorted(set(of_class.tolist()))}
    palette = [{"index": c, "lab": lab, "srgb": sg.color.lab_to_srgb8(np.asarray(lab)).tolist(), "pixels": int(pixels[of_class == c].sum())}
               for c, lab in labs.items()]
    regions = [{"id": name[i], "color": int(c), "lab": labs[c], "srgb": palette[[p["index"] for p in palette].index(c)]["srgb"],
                "pixels": int(pixels[i]), "important": False, "loops": loops[i]} for i, c in enumerate(of_class.tolist())]
    arc_list = [{"id": i, "left": name[left] if left >= 0 else None, "right": name[right] if right >= 0 else None, "closed": closed,
                 "points": [[v % (w + 1), v // (w + 1)] for v in vertices]} for i, (vertices, left, right, _, _, closed) in enumerate(arcs)]
    return {"size_mm": {"width": float(w), "height": float(h)}, "px_mm": 1.0, "image_px": {"width": w, "height": h},
            "palette": palette, "regions": regions, "arcs": arc_list}


def even_odd(loops, shape) -> np.ndarray:
    """The pixel centres inside a region's closed loops by the even-odd rule."""
    ys, xs = np.mgrid[0:shape[0], 0:shape[1]] + 0.5
    inside = np.zeros(shape, bool)
    for loop in loops:
        for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1]):
            if y0 != y1:
                inside ^= ((y0 > ys) != (y1 > ys)) & (xs < x0 + (ys - y0) * (x1 - x0) / (y1 - y0))
    return inside


def planar(doc) -> None:
    """The invariants of a planar map: an arc's id is its place, it separates two different regions (or one and the
    picture's edge), and every region walks it once, forward on its left and backward on its right; loops chain end to
    start and close; one outer boundary (area < 0, y down), then holes."""
    ids = {r["id"] for r in doc["regions"]}
    uses = {}
    for r in doc["regions"]:
        for loop in r["loops"]:
            ends = []
            for ref in loop:
                uses.setdefault(ref if ref >= 0 else ~ref, []).append((r["id"], ref >= 0))
                points = doc["arcs"][ref if ref >= 0 else ~ref]["points"]
                ends.append((points if ref >= 0 else points[::-1])[0::len(points) - 1])
            assert all(ends[k][1] == ends[(k + 1) % len(ends)][0] for k in range(len(ends)))     # end to start, closed
        areas = [sum(sg._doubled_area(doc["arcs"][ref if ref >= 0 else ~ref]["points"]) * (1 if ref >= 0 else -1) for ref in loop)
                 for loop in r["loops"]]
        assert areas[0] < 0 and all(a > 0 for a in areas[1:]), r["id"]
    for i, arc in enumerate(doc["arcs"]):
        assert arc["id"] == i and arc["left"] != arc["right"] and {arc["left"], arc["right"]} - {None} <= ids
        expected = ([(arc["left"], True)] if arc["left"] else []) + ([(arc["right"], False)] if arc["right"] else [])
        assert sorted(uses.pop(i), key=lambda u: not u[1]) == expected
    assert not uses                                                                          # no reference to a dropped arc


def connected_set(doc, rng, size) -> list[str]:
    near = sg.neighbours(doc)
    chosen = [sorted(near)[int(rng.integers(len(near)))]]
    frontier = sorted(near[chosen[0]])
    while len(chosen) < size and frontier:
        pick = frontier.pop(int(rng.integers(len(frontier))))
        if pick not in chosen:
            chosen.append(pick)
            frontier += sorted(near[pick] - set(chosen))
    return chosen


@pytest.mark.parametrize("seed", range(6))
def test_merged_regions_enclose_exactly_their_pixels_also_where_they_touch_at_a_corner(seed):
    rng = np.random.default_rng(seed)
    region, of_class = sg._components(rng.integers(0, 3, (14, 17)).astype(np.int32), 3)       # many diagonal touches
    doc = pixel_document(region, of_class)
    masks = {f"r{i + 1}": region == i for i in range(len(of_class))}
    for _ in range(5):                                                                       # merges of merged regions too
        chosen = connected_set(doc, rng, int(rng.integers(2, 7)))
        doc, keeper = sg.merge_regions(doc, chosen)
        masks[keeper] = np.logical_or.reduce([masks.pop(r) for r in chosen])
        planar(doc)
        assert {r["id"] for r in doc["regions"]} == set(masks)
        for r in sg.regions_as_loops(doc):                                                   # the others are unchanged
            assert (even_odd(r["loops"], region.shape) == masks[r["id"]]).all(), r["id"]
            assert r["pixels"] == masks[r["id"]].sum()


def ring_document():
    """Paper (r1) around a ring (r2) around inner paper (r3), none touching the picture's edge but the outer paper."""
    yy, xx = np.mgrid[0:16, 0:16]
    d = np.maximum(abs(xx - 7.5), abs(yy - 7.5))
    region = np.where(d > 6, 0, np.where(d > 3, 1, 2)).astype(np.int64)
    return pixel_document(region, np.array([0, 1, 0])), region


def test_a_ring_merged_with_the_paper_inside_it_drops_their_closed_border():
    doc, region = ring_document()
    inner_border = next(a for a in doc["arcs"] if {a["left"], a["right"]} == {"r2", "r3"})
    assert inner_border["closed"]
    merged, keeper = sg.merge_regions(doc, ["r3", "r2"])
    assert keeper == "r2" and [r["id"] for r in merged["regions"]] == ["r1", "r2"] and len(merged["arcs"]) == len(doc["arcs"]) - 1
    ring = merged["regions"][1]
    assert len(ring["loops"]) == 1 and ring["pixels"] == (region > 0).sum() and ring["color"] == 1
    assert [(p["index"], p["pixels"]) for p in merged["palette"]] == [(0, (region == 0).sum()), (1, (region > 0).sum())]
    planar(merged)
    assert (even_odd(sg.regions_as_loops(merged)[1]["loops"], region.shape) == (region > 0)).all()


def test_paper_merged_with_the_ring_inside_it_keeps_the_inner_paper_as_a_hole():
    doc, region = ring_document()
    merged, keeper = sg.merge_regions(doc, ["r1", "r2"])
    assert keeper == "r1" and [r["id"] for r in merged["regions"]] == ["r1", "r3"]
    (hole,) = merged["regions"][0]["loops"][1:]
    assert [merged["arcs"][ref if ref >= 0 else ~ref]["closed"] for ref in hole] == [True]       # the inner paper's border
    planar(merged)
    loops = sg.regions_as_loops(merged)
    assert (even_odd(loops[0]["loops"], region.shape) == (region < 2)).all() and (even_odd(loops[1]["loops"], region.shape) == (region == 2)).all()
    assert [(p["index"], p["pixels"]) for p in merged["palette"]] == [(0, region.size)]               # the ring's colour has no region left


def test_a_union_around_a_pocket_has_the_pocket_as_a_hole_and_keeps_its_two_arc_junctions():
    region = np.zeros((9, 9), np.int64)                         # A above, B and C below, the pocket P in the middle
    region[4:, :4], region[4:, 4:], region[3:6, 3:6] = 1, 2, 3
    doc = pixel_document(region, np.array([0, 1, 2, 3]))
    pocket = doc["regions"][3]["loops"]
    merged, keeper = sg.merge_regions(doc, ["r1", "r2", "r3"])
    union = next(r for r in merged["regions"] if r["id"] == keeper)
    assert len(union["loops"]) == 2 and len(union["loops"][1]) == len(pocket[0]) == 3                 # P's three arcs stay
    assert [r["id"] for r in merged["regions"]] == [keeper, "r4"]
    planar(merged)
    loops = {r["id"]: r["loops"] for r in sg.regions_as_loops(merged)}
    assert (even_odd(loops[keeper], region.shape) == (region < 3)).all() and (even_odd(loops["r4"], region.shape) == (region == 3)).all()


def test_a_union_touching_itself_at_a_corner_encloses_exactly_its_pixels():
    region = np.array([[0, 0, 0, 0],                         # A and B touch at a corner around two holes that do too
                       [0, 2, 1, 1],
                       [0, 0, 3, 1],
                       [0, 0, 1, 1]], np.int64)
    doc = pixel_document(region, np.array([0, 1, 2, 2]))
    merged, keeper = sg.merge_regions(doc, ["r1", "r2"])
    assert keeper == "r1" and [r["id"] for r in merged["regions"]] == ["r1", "r3", "r4"]
    planar(merged)
    for r in sg.regions_as_loops(merged):
        assert (even_odd(r["loops"], region.shape) == np.isin(region, [0, 1] if r["id"] == "r1" else [int(r["id"][1:]) - 1])).all()


@pytest.mark.parametrize("make, n_colors, seed, merges", [(shapes, 7, 0, 3), (photo_like, 12, 1, 8), (photo_like, 12, 2, 8)])
def test_merged_regions_keep_the_picture_covered_and_its_area(make, n_colors, seed, merges):
    img = make()
    doc = sg.segment(img, 0.25 * img.shape[1], n_colors, use_faces=False)
    size = doc["size_mm"]

    def measure(d):
        loops = [r["loops"] for r in sg.regions_as_loops(d)]
        return sg.coverage(loops, size["width"], size["height"], 16), sum(vz._signed_area(loop) for r in loops for loop in r)

    before, area = measure(doc)
    rng = np.random.default_rng(seed)
    for _ in range(merges):
        doc, keeper = sg.merge_regions(doc, connected_set(doc, rng, int(rng.integers(2, 4 if merges < 5 else 6))))
    after, area_after = measure(doc)
    planar(doc)
    assert after["overlap"] <= before["overlap"] and after["uncovered"] <= before["uncovered"] + before["overlap"]
    assert after["overlap"] < 0.005 and after["uncovered"] < 0.005
    assert area_after == pytest.approx(area, rel=1e-9) and area == pytest.approx(-size["width"] * size["height"], rel=0.005)
    assert sum(r["pixels"] for r in doc["regions"]) == sum(p["pixels"] for p in doc["palette"]) == img.shape[0] * img.shape[1]
    for p in doc["palette"]:                                                         # each colour holds its regions' pixels
        assert p["pixels"] == sum(r["pixels"] for r in doc["regions"] if r["color"] == p["index"])


def test_merged_regions_export_to_lightburn_closed_with_their_holes():
    doc = sg.segment(shapes(), 60.0, 7, use_faces=False)
    ring = next(r for r in doc["regions"] if r["color"] == colour_index(doc, RED) and len(r["loops"]) == 2)
    paper = doc["regions"][0]
    assert ring["id"] in sg.neighbours(doc)[paper["id"]] and len(paper["loops"]) == 3
    merged, keeper = sg.merge_regions(doc, [ring["id"], paper["id"]])               # the ring's hole in the paper gives way to its own
    assert keeper == paper["id"] and len(merged["regions"][0]["loops"]) == 3
    lightburn_round_trip(merged)
    many = sg.segment(photo_like(), 50.0, 12, use_faces=False)
    rng = np.random.default_rng(4)
    for _ in range(10):
        many, _ = sg.merge_regions(many, connected_set(many, rng, int(rng.integers(2, 6))))
    lightburn_round_trip(many)


def lightburn_round_trip(doc) -> None:
    """The regions written as LightBurn paths read back closed, with every hole as a hole, the same areas, gapless."""
    regions = sg.regions_as_loops(doc)
    layers = {f"c{p['index']}": n for n, p in enumerate(doc["palette"])}
    settings = "".join(f'<CutSetting type="Scan"><index Value="{i}"/><name Value="C{i:02d}"/><maxPower Value="40"/>'
                       f'<speed Value="1000"/><frequency Value="40000"/></CutSetting>' for i in layers.values())
    xml = ('<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="2.0.04" FormatVersion="1">' + settings
           + "".join(vz.to_lbrn2_shapes({"regions": regions}, layers)) + "</LightBurnProject>")
    back = [p for layer in lb.parse_bytes(xml.encode("utf-8")).layers for p in layer.regions]
    assert len(back) == len(regions) and all(p.closed and p.kind == "path" for p in back)
    mine = sorted((round(outline_area(r["loops"]), 3), len(r["loops"]) - 1) for r in regions)
    read = sorted((round(outline_area([p.polygon] + p.holes), 3), len(p.holes)) for p in back)
    assert [holes for _, holes in read] == [holes for _, holes in mine] and sum(h for _, h in mine) >= 1   # every hole read as a hole
    assert [a for a, _ in read] == pytest.approx([a for a, _ in mine], rel=0.01)
    cov = sg.coverage([[p.polygon] + p.holes for p in back], doc["size_mm"]["width"], doc["size_mm"]["height"], 16)
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005


def test_several_sets_merged_in_one_pass_give_what_merging_them_one_after_another_gives():
    """vector-detail-and-colour-control I-7: the file joins every same-layer set at once; one pass equals the merges one by one."""
    doc = sg.segment(photo_like(), 50.0, 12, use_faces=False)
    rng = np.random.default_rng(11)
    groups, taken = [], set()
    while len(groups) < 6:
        ids = connected_set(doc, rng, int(rng.integers(2, 5)))
        if taken.isdisjoint(ids):
            groups.append(ids)
            taken |= set(ids)
    at_once, keepers = sg.merge_groups(doc, groups)
    one_by_one = doc
    for ids in groups:
        one_by_one, _ = sg.merge_regions(one_by_one, ids)
    outline = lambda d: sorted((r["id"], round(outline_area(r["loops"]), 6), len(r["loops"])) for r in sg.regions_as_loops(d))   # noqa: E731
    assert outline(at_once) == outline(one_by_one) and keepers == [sg.merge_regions(doc, ids)[1] for ids in groups]
    planar(at_once)
    lightburn_round_trip(at_once)
    with pytest.raises(RuntimeError):
        sg.merge_groups(doc, [groups[0], [groups[0][0], groups[1][0]]])                      # a region in two sets


def test_a_set_that_is_not_connected_stays_as_it_was_when_the_merge_is_not_strict():
    doc = sg.segment(shapes(), 60.0, 7, use_faces=False)
    near = sg.neighbours(doc)
    a, b = next((x["id"], y["id"]) for x in doc["regions"] for y in doc["regions"] if x["id"] < y["id"] and y["id"] not in near[x["id"]])
    joined = connected_set(doc, np.random.default_rng(3), 2)
    if {a, b} & set(joined):
        a, b = next((x["id"], y["id"]) for x in doc["regions"] for y in doc["regions"]
                    if x["id"] < y["id"] and y["id"] not in near[x["id"]] and not {x["id"], y["id"]} & set(joined))
    merged, keepers = sg.merge_groups(doc, [[a, b], joined], strict=False)
    assert keepers[0] is None and keepers[1] in joined
    assert {a, b} <= {r["id"] for r in merged["regions"]} and len(merged["regions"]) == len(doc["regions"]) - 1
    with pytest.raises(RuntimeError):
        sg.merge_groups(doc, [[a, b]])


def test_a_merge_is_deterministic_and_leaves_its_input_unchanged():
    doc = sg.segment(photo_like(), 50.0, 9, use_faces=False)
    before = json.dumps(doc)
    ids = connected_set(doc, np.random.default_rng(7), 5)
    first, second = sg.merge_regions(doc, ids), sg.merge_regions(doc, list(reversed(ids)))
    assert json.dumps(first) == json.dumps(second) and json.dumps(doc) == before
    colours = [p["index"] for p in doc["palette"][2:5]]
    assert json.dumps(sg.merge_colours(doc, colours)) == json.dumps(sg.merge_colours(doc, colours[::-1])) and json.dumps(doc) == before
    with pytest.raises(RuntimeError):
        sg.merge_regions(doc, ids[:1])
    with pytest.raises(RuntimeError):
        sg.merge_colours(doc, [colours[0], 99])


def test_the_merged_region_keeps_its_largest_member_and_takes_over_the_pixels_of_the_others():
    doc = sg.segment(shapes(), 60.0, 7, use_faces=False)
    ids = connected_set(doc, np.random.default_rng(3), 4)
    members = [r for r in doc["regions"] if r["id"] in ids]
    largest = max(members, key=lambda r: r["pixels"])
    for r in doc["regions"]:                                         # an important member holding half the pixels makes it important
        r["important"] = r["id"] == largest["id"]
    merged, keeper = sg.merge_regions(doc, ids)
    region = next(r for r in merged["regions"] if r["id"] == keeper)
    total = sum(m["pixels"] for m in members)
    assert keeper == largest["id"] and [r["id"] for r in merged["regions"]] == [r["id"] for r in doc["regions"] if r["id"] == keeper or r["id"] not in ids]
    assert {k: region[k] for k in ("color", "lab", "srgb")} == {k: largest[k] for k in ("color", "lab", "srgb")} and region["pixels"] == total
    assert region["important"] == (2 * largest["pixels"] >= total)
    gone = {m["color"] for m in members} - {r["color"] for r in merged["regions"]}
    assert {p["index"] for p in merged["palette"]} == {p["index"] for p in doc["palette"]} - gone
    for p in merged["palette"]:
        old = next(q for q in doc["palette"] if q["index"] == p["index"])
        moved = sum(m["pixels"] for m in members if m["id"] != keeper and m["color"] == p["index"])
        assert p["pixels"] == old["pixels"] - moved + (total - largest["pixels"] if p["index"] == largest["color"] else 0)
        assert p["lab"] == old["lab"]


def test_merged_colours_take_the_pixel_weighted_mean_under_the_number_of_the_largest_and_the_others_keep_theirs():
    doc = sg.segment(photo_like(), 50.0, 9, use_faces=False)
    chosen = [doc["palette"][1]["index"], doc["palette"][4]["index"], doc["palette"][6]["index"]]
    members = [p for p in doc["palette"] if p["index"] in chosen]
    merged, keeper = sg.merge_colours(doc, chosen)
    assert keeper == max(members, key=lambda p: (p["pixels"], -p["index"]))["index"]
    weights = [p["pixels"] for p in members]
    mean = [round(float(v), 3) for v in np.average([p["lab"] for p in members], axis=0, weights=weights)]
    entry = next(p for p in merged["palette"] if p["index"] == keeper)
    assert entry["lab"] == mean and entry["srgb"] == sg.color.lab_to_srgb8(np.asarray(mean)).tolist() and entry["pixels"] == sum(weights)
    assert sorted(p["index"] for p in merged["palette"]) == sorted(set(p["index"] for p in doc["palette"]) - set(chosen) | {keeper})
    assert [p["lab"][0] for p in merged["palette"]] == sorted((p["lab"][0] for p in merged["palette"]), reverse=True)
    for old, new in zip(doc["regions"], merged["regions"]):
        assert (old["id"], old["loops"], old["pixels"]) == (new["id"], new["loops"], new["pixels"])
        if old["color"] in chosen:
            assert (new["color"], new["lab"], new["srgb"]) == (keeper, mean, entry["srgb"])
        else:
            assert (new["color"], new["lab"]) == (old["color"], old["lab"])
    assert merged["arcs"] == doc["arcs"]
    again, _ = sg.merge_colours(merged, [keeper, merged["palette"][0]["index"]])       # a palette with gaps merges on
    assert len(again["palette"]) == len(doc["palette"]) - 3


def test_neighbours_are_the_regions_across_an_arc_both_ways_and_never_the_picture_edge():
    doc = sg.segment(shapes(), 60.0, 7, use_faces=False)
    near = sg.neighbours(doc)
    assert set(near) == {r["id"] for r in doc["regions"]} and all(near.values())
    assert all(a in near[b] and a != b and b is not None for a, others in near.items() for b in others)
    colour = {r["id"]: r["color"] for r in doc["regions"]}
    assert all(colour[a] != colour[b] for a, others in near.items() for b in others)    # a fresh split: never one colour
    corner = pixel_document(*sg._components(np.array([[0, 1], [1, 0]], np.int32), 2))       # a touch at a corner is no border
    assert sg.neighbours(corner) == {"r1": {"r2", "r3"}, "r2": {"r1", "r4"}, "r3": {"r1", "r4"}, "r4": {"r2", "r3"}}


# -- the choice of the splitting algorithm (feature vector-detail-and-colour-control, DEC-076) -----------------------------------
def inked_page(noise=6.0, shade=0.45, w=640, h=420, seed=3):
    """A lit sheet with a headline, a table of thin ruled lines and a line of small text, with sensor-like noise and a dark band."""
    gx, gy = np.linspace(0, 1, w)[None, :], np.linspace(0, 1, h)[:, None]
    img = np.repeat(np.clip(205 + 40 * gx + 25 * gy, 0, 255)[..., None], 3, axis=2).astype(np.uint8)
    cv2.putText(img, "Product List", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 2, cv2.LINE_AA)
    for y in (140, 220, 300, 380):
        cv2.line(img, (30, y), (610, y), (25, 25, 25), 1, cv2.LINE_AA)
    for x in (30, 250, 610):
        cv2.line(img, (x, 140), (x, 380), (25, 25, 25), 1, cv2.LINE_AA)
    cv2.putText(img, "Checked by:", (60, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (30, 30, 30), 1, cv2.LINE_AA)
    img = img.astype(np.float32) * (1 - shade * np.exp(-((gy - 0.8) ** 2) / 0.02))[..., None]
    return np.clip(img + np.random.default_rng(seed).normal(0, noise, img.shape), 0, 255).astype(np.uint8)


def painted(doc, shape):
    """The Lab picture the regions of a split paint (even-odd, so holes stay holes)."""
    h, w = shape
    out = np.zeros((h, w, 3), np.float32)
    for r in sg.regions_as_loops(doc):
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [np.round(np.asarray(loop) / doc["px_mm"]).astype(np.int32) for loop in r["loops"]], 1)
        out[mask > 0] = r["lab"]
    return out


def ink_kept(img, doc) -> float:
    """The share of the strokes (clearly darker than their surroundings) that the split still paints clearly darker than theirs."""
    from titanium_platform import color
    lab, out = color.srgb8_to_lab(img), painted(doc, img.shape[:2])
    ink = (cv2.GaussianBlur(lab[..., 0], (0, 0), 9) - lab[..., 0]) > 25
    kept = (cv2.GaussianBlur(out[..., 0], (0, 0), 9) - out[..., 0]) > 12
    return float((ink & kept).sum() / ink.sum())


@pytest.mark.parametrize("algorithm", sg.ALGORITHMS)
def test_every_algorithm_splits_gaplessly_the_same_way_every_time_and_says_which_it_was(algorithm):
    img = shapes()
    docs = [sg.segment(img, 72.0, 6, use_faces=False, min_area_mm2=0.5, algorithm=algorithm) for _ in range(2)]
    assert docs[0] == docs[1] and docs[0]["algorithm"] == algorithm                       # deterministic, and recorded in the document
    cov = sg.coverage([r["loops"] for r in sg.regions_as_loops(docs[0])], docs[0]["size_mm"]["width"], docs[0]["size_mm"]["height"], 8)
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005
    assert sum(r["pixels"] for r in docs[0]["regions"]) == img.shape[0] * img.shape[1]
    photo = sg.segment(photo_like(), 60.0, 8, use_faces=False, algorithm=algorithm)
    cov = sg.coverage([r["loops"] for r in sg.regions_as_loops(photo)], photo["size_mm"]["width"], photo["size_mm"]["height"], 8)
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005


@pytest.mark.parametrize("algorithm", sg.ALGORITHMS)
def test_a_marked_area_smaller_than_two_superpixels_is_split_by_every_algorithm(algorithm):
    """Finer superpixels inside faces, eyes and marked areas: a crop of a few pixels must not break SEEDS, which cannot make one."""
    img = shapes()
    marked = faces.check_area({"polygon": [[100, 20], [106, 20], [106, 25], [100, 25]], "kind": "manual", "source": "manual", "score": None})
    doc = sg.segment(img, 72.0, 6, important=[marked], use_faces=False, min_area_mm2=0.5, algorithm=algorithm)
    assert doc["algorithm"] == algorithm and len(doc["regions"]) >= 6


def test_the_algorithm_default_is_slic_and_an_unknown_one_is_refused():
    assert sg.DEFAULT_ALGORITHM == "slic" and sg.ALGORITHMS == ("slic", "tonal", "planes", "seeds")
    assert sg.segment(shapes(), 72.0, 6, use_faces=False)["algorithm"] == "slic"
    for bad in ("lsc", "SLIC", "", None):
        with pytest.raises(sg.SegmentError, match="the algorithm must be slic, tonal, planes or seeds"):
            sg.segment(shapes(), 72.0, 6, use_faces=False, algorithm=bad)


def test_seeds_keeps_thin_strokes_at_least_as_well_as_slic_with_far_fewer_regions_on_a_noisy_unevenly_lit_page():
    """What the screen says of the two: measured on a lit sheet with noise and a dark band (6 colours, medium detail; 87-93 % of the
    strokes kept by SEEDS against 83-88 % by SLIC, and 81-114 regions against 276-442, over six noise and shading settings)."""
    page = inked_page()
    slic, seeds = (sg.segment(page, 100.0, 6, use_faces=False, min_area_mm2=0.2, superpixels=100, algorithm=a) for a in ("slic", "seeds"))
    assert ink_kept(page, seeds) >= ink_kept(page, slic) - 0.02
    assert len(seeds["regions"]) < len(slic["regions"])


# -- four methods that differ (feature vector-detail-and-colour-control, DEC-082) -------------------------------------------------
def region_borders(doc) -> np.ndarray:
    """The pixels of a split that lie next to a pixel of another region."""
    h, w = doc["image_px"]["height"], doc["image_px"]["width"]
    ids = np.zeros((h, w), np.int32)
    for number, r in enumerate(sg.regions_as_loops(doc), 1):
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [np.round(np.asarray(r["loops"][0]) / doc["px_mm"]).astype(np.int32)], 1)
        for hole in r["loops"][1:]:
            cv2.fillPoly(mask, [np.round(np.asarray(hole) / doc["px_mm"]).astype(np.int32)], 0)
        ids[mask == 1] = number
    border = np.zeros((h, w), bool)
    border[:, 1:] |= ids[:, 1:] != ids[:, :-1]
    border[1:, :] |= ids[1:, :] != ids[:-1, :]
    return border


def unmatched(a: np.ndarray, b: np.ndarray) -> float:
    """The share of the borders of ``a`` with no border of ``b`` within a pixel."""
    near = cv2.dilate(b.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return float((a & ~near).sum() / max(1, a.sum()))


@pytest.mark.parametrize("make, n_colors", [(photo_like, 12), (blots, 10)])
def test_the_four_methods_give_four_different_maps_on_a_photograph(make, n_colors):
    """A choice that changes nothing is not a feature (the operator, 0.7.0): SLIC and SEEDS gave one map, so every pair must differ."""
    img = make()
    docs = {a: sg.segment(img, 0.25 * img.shape[1], n_colors, use_faces=False, superpixels=40, algorithm=a) for a in sg.ALGORITHMS}
    borders = {a: region_borders(d) for a, d in docs.items()}
    for a, b in itertools.combinations(sg.ALGORITHMS, 2):
        assert min(unmatched(borders[a], borders[b]), unmatched(borders[b], borders[a])) > 0.25, (a, b)
    counts = {a: len(d["regions"]) for a, d in docs.items()}
    assert counts["tonal"] > counts["slic"] > counts["planes"]                           # tones: many small; planes: few large


def shaded_disc():
    """A lit sphere on a dark ground: one smooth tone from light to dark, like a cheek."""
    yy, xx = np.mgrid[0:200, 0:200].astype(float)
    shade = np.clip(1 - 0.55 * (np.hypot(xx - 75, yy - 70) / 120), 0, 1)
    img = np.empty((200, 200, 3))
    img[:] = (40, 40, 50)
    disc = np.hypot(xx - 100, yy - 100) < 90
    img[disc] = np.array([235, 180, 150.0])[None, :] * shade[disc][:, None]
    return np.clip(img, 0, 255).astype(np.uint8)


def test_the_planes_method_keeps_the_tones_of_a_smooth_face_instead_of_collapsing_it_into_one_plane(monkeypatch):
    img = shaded_disc()
    doc = sg.segment(img, 60.0, 8, use_faces=False, superpixels=30, algorithm="planes")
    assert len(doc["palette"]) == 8 and len(doc["regions"]) >= 8                           # every tone asked for is still there
    assert sg.PLANES_SCALE <= 300                                                          # measured: at 2000 the disc is 3 colours
    monkeypatch.setattr(sg, "PLANES_SCALE", 2000.0)
    collapsed = sg.segment(img, 60.0, 8, use_faces=False, superpixels=30, algorithm="planes")
    assert len(collapsed["palette"]) < len(doc["palette"])                                # what the bound is for


def test_a_fine_grid_is_merged_before_it_is_clustered_and_a_coarse_one_is_left_as_it_was(monkeypatch):
    seen = []
    real = sg._kmeans
    monkeypatch.setattr(sg, "_kmeans", lambda points, weights, k, seed: (seen.append(len(points)), real(points, weights, k, seed))[1])
    img = photo_like()
    sg.segment(img, 50.0, 8, use_faces=False, algorithm="tonal")
    uncapped = seen[-1]
    monkeypatch.setattr(sg, "KMEANS_POINTS", 400)
    sg.segment(img, 50.0, 8, use_faces=False, algorithm="tonal")
    assert seen[-1] < uncapped                                                            # a coarser colour step, not fewer superpixels
    seen.clear()
    monkeypatch.setattr(sg, "KMEANS_POINTS", 20000)
    first = sg.segment(img, 50.0, 8, use_faces=False, algorithm="slic")
    monkeypatch.setattr(sg, "KMEANS_POINTS", 10 ** 9)
    assert sg.segment(img, 50.0, 8, use_faces=False, algorithm="slic") == first         # a few thousand points: the cap changes nothing
