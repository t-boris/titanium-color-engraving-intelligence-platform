"""REQ-052, DEC-083 (vector-detail-and-colour-control): the shared borders of a split smoothed by a strength in mm and kept as cubic
Béziers; the preview and the LightBurn file draw the same curves; regions, colours and topology stay as they were."""
import math
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest

from test_segment import PAPER, outline_area, photo_like, ring_picture, shapes, walks
from titanium_platform import contour, lightburn as lb, segment as sg, vectorize as vz

SVG = "{http://www.w3.org/2000/svg}"


def noisy_sine(n=400, length=40.0, amplitude=2.0, noise=0.08, seed=3):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, length, n)
    clean = np.stack([x, amplitude * np.sin(x / 4.0)], axis=1)
    return clean, clean + np.stack([0 * x, rng.normal(0, noise, n)], axis=1)         # a wobble across the border, never back along it


def turning(points) -> float:
    """Sum of the absolute turning angles along a polyline, in degrees."""
    p = np.asarray(points, float)
    d = np.diff(p, axis=0)
    d = d[np.hypot(*d.T) > 1e-9]
    a = np.arctan2(d[:, 1], d[:, 0])
    t = np.abs((np.diff(a) + np.pi) % (2 * np.pi) - np.pi)
    return float(np.degrees(t).sum())


def bezier_points(nodes, per_segment=60):
    out = []
    arr = np.asarray(nodes, float)
    for a, b in zip(arr[:-1], arr[1:]):
        u = np.linspace(0, 1, per_segment, endpoint=False)
        out.append(contour._bezier(a[0:2], a[2:4], b[4:6], b[0:2], u))
    out.append(arr[-1:, 0:2])
    return np.vstack(out)


def tangent_breaks(nodes) -> list[float]:
    """The angle (degrees) between the in- and out-direction at every inner node."""
    out = []
    for n in nodes[1:-1]:
        into, outward = np.array(n[0:2]) - np.array(n[4:6]), np.array(n[2:4]) - np.array(n[0:2])
        if np.hypot(*into) < 1e-9 or np.hypot(*outward) < 1e-9:
            continue
        cos = float(np.dot(into, outward) / (np.hypot(*into) * np.hypot(*outward)))
        out.append(math.degrees(math.acos(max(-1.0, min(1.0, cos)))))
    return out


# -- one arc -----------------------------------------------------------------------------------------------------------------------
def test_a_straight_arc_stays_straight_and_keeps_its_ends():
    line = [[0.0, 0.0], [3.0, 1.0], [6.0, 2.0], [12.0, 4.0]]
    nodes = contour.smooth_arc(line, False, 0.8)
    assert nodes[0][0:2] == [0.0, 0.0] and nodes[-1][0:2] == [12.0, 4.0]
    p = bezier_points(nodes)
    assert np.abs(p[:, 1] - p[:, 0] / 3.0).max() < 1e-6                     # on the line y = x / 3
    assert len(nodes) <= 4                                                  # a straight run needs hardly any node


def test_no_strength_or_a_tiny_arc_comes_back_as_straight_nodes():
    points = [[0.0, 0.0], [1.0, 0.5], [2.0, 0.0]]
    for sigma in (0.0, -1.0):
        nodes = contour.smooth_arc(points, False, sigma)
        assert [n[0:2] for n in nodes] == points and all(n[0:2] == n[2:4] == n[4:6] for n in nodes)
    tiny = [[0.0, 0.0], [0.05, 0.0], [0.1, 0.02]]
    assert [n[0:2] for n in contour.smooth_arc(tiny, False, 1.0)] == tiny


@pytest.mark.parametrize("sigma", [0.3, 0.8, 1.6])
def test_noise_is_smoothed_and_the_ends_stay_exactly_where_they_are(sigma):
    clean, noisy = noisy_sine()
    nodes = contour.smooth_arc(noisy, False, sigma)
    assert nodes[0][0:2] == noisy[0].tolist() and nodes[-1][0:2] == noisy[-1].tolist()
    flat = np.asarray(contour.flatten(nodes))
    assert turning(flat) < 0.25 * turning(noisy)                                 # the wiggle is gone
    d = np.array([np.hypot(*(clean - q).T).min() for q in flat[5:-5]])
    assert d.max() < 0.25 + 0.06 * sigma                                         # and the curve still follows the shape


@pytest.mark.parametrize("sigma", [0.3, 0.8, 1.6])
def test_inside_an_arc_the_tangent_is_continuous_at_every_node(sigma):
    _, noisy = noisy_sine()
    nodes = contour.smooth_arc(noisy, False, sigma)
    assert len(nodes) > 4 and max(tangent_breaks(nodes)) < 0.5                  # the handles of a node lie on one line, through it


def test_more_strength_gives_fewer_nodes_and_less_turning():
    _, noisy = noisy_sine()
    counts, turns = [], []
    for sigma in (0.2, 0.6, 1.2, 2.0):
        nodes = contour.smooth_arc(noisy, False, sigma)
        counts.append(len(nodes))
        turns.append(turning(contour.flatten(nodes)))
    assert counts == sorted(counts, reverse=True) and turns == sorted(turns, reverse=True)
    assert counts[-1] < 0.1 * len(noisy)


def test_a_closed_arc_closes_and_has_a_continuous_tangent_where_it_starts():
    rng = np.random.default_rng(4)
    angle = np.linspace(0, 2 * np.pi, 300)
    ring = np.stack([10 * np.cos(angle), 10 * np.sin(angle)], axis=1) + rng.normal(0, 0.05, (300, 2))
    ring[-1] = ring[0]
    nodes = contour.smooth_arc(ring, True, 0.6)
    assert nodes[0][0:2] == nodes[-1][0:2]
    seam = np.array(nodes[0][2:4]) - np.array(nodes[0][0:2]), np.array(nodes[-1][0:2]) - np.array(nodes[-1][4:6])
    cos = np.dot(*seam) / (np.hypot(*seam[0]) * np.hypot(*seam[1]))
    assert math.degrees(math.acos(min(1.0, cos))) < 1.0
    radius = np.hypot(*bezier_points(nodes).T)
    assert abs(radius.mean() - 10) < 0.05 and radius.std() < 0.03               # a circle again, whatever the noise


def test_a_corner_stays_a_corner_with_a_tangent_of_its_own_on_each_side():
    side = np.linspace(0, 10, 120)
    square = np.vstack([np.stack([side, 0 * side], 1), np.stack([10 + 0 * side, side], 1)[1:], np.stack([10 - side, 10 + 0 * side], 1)[1:]])
    nodes = contour.smooth_arc(square, False, 0.5)
    corners = [n for n in nodes if abs(n[0] - 10) < 0.02 and abs(n[1]) < 0.02]
    assert corners, "the corner at (10, 0) has no node"
    n = corners[0]
    into, outward = np.array(n[0:2]) - np.array(n[4:6]), np.array(n[2:4]) - np.array(n[0:2])
    angle = math.degrees(math.acos(np.dot(into, outward) / (np.hypot(*into) * np.hypot(*outward))))
    assert 80 < angle < 100                                                      # a right angle is not rounded off
    p = bezier_points(nodes)
    near_side = p[(p[:, 0] > 2) & (p[:, 0] < 8) & (p[:, 1] < 5)]                     # the first side of the square
    assert np.abs(near_side[:, 1]).max() < 0.02                                  # and the straight side stays straight


def test_splitting_a_segment_in_two_keeps_the_curve():
    a = [0.0, 0.0, 1.0, 2.0, 0.0, 0.0]
    b = [4.0, 0.0, 4.0, 0.0, 3.0, 2.0]
    first, mid, last = sg._split_node(a, b)
    original = contour._bezier(np.array(a[0:2]), np.array(a[2:4]), np.array(b[4:6]), np.array(b[0:2]), np.linspace(0, 1, 41))
    halves = np.vstack([bezier_points([first, mid], 20)[:-1], bezier_points([mid, last], 20)])
    assert np.abs(original - halves).max() < 1e-4 and first[0:2] == a[0:2] and last[0:2] == b[0:2]


def test_flattening_stays_within_a_hundredth_of_a_millimetre_of_the_curve():
    _, noisy = noisy_sine()
    nodes = contour.smooth_arc(noisy, False, 0.8)
    flat = np.asarray(contour.flatten(nodes))
    exact = bezier_points(nodes, 400)
    dist = np.array([np.hypot(*(exact - q).T).min() for q in flat])
    assert dist.max() < 0.01 and flat[0] == pytest.approx(nodes[0][0:2], abs=1e-5) and flat[-1] == pytest.approx(nodes[-1][0:2], abs=1e-5)


# -- a split ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def split():
    return sg.segment(shapes(), 60.0, 7, use_faces=False)


def test_a_strength_of_zero_is_the_document_as_traced(split):
    assert sg.smoothed(split, 0) is split
    for bad in (-1, float("nan"), "x", None):
        with pytest.raises(sg.SegmentError):
            sg.smoothed(split, bad)


@pytest.mark.parametrize("sigma", [0.3, 1.0, 2.0])
def test_smoothing_changes_the_borders_and_nothing_else(split, sigma):
    smooth = sg.smoothed(split, sigma)
    assert smooth["regions"] == split["regions"] and smooth["palette"] == split["palette"] and smooth["size_mm"] == split["size_mm"]
    assert smooth["smoothing_mm"] == sigma and split.get("smoothing_mm") is None                   # the stored split is left alone
    for before, after in zip(split["arcs"], smooth["arcs"]):
        assert (before["id"], before["left"], before["right"], before["closed"]) == (after["id"], after["left"], after["right"], after["closed"])
        assert after["points"][0] == before["points"][0] and after["points"][-1] == before["points"][-1]   # junctions do not move
        assert "nodes" in after and after["nodes"][0][0:2] == before["points"][0]


@pytest.mark.parametrize("make, n_colors", [(shapes, 7), (photo_like, 12)])
@pytest.mark.parametrize("sigma", [0.4, 1.0, 2.0])
def test_smooth_borders_still_cover_the_picture_without_gaps_or_overlaps(make, n_colors, sigma):
    img = make()
    doc = sg.smoothed(sg.segment(img, 0.25 * img.shape[1], n_colors, use_faces=False), sigma)
    regions = sg.regions_as_loops(doc)
    cov = sg.coverage([r["loops"] for r in regions], doc["size_mm"]["width"], doc["size_mm"]["height"], 16)
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005
    assert sum(outline_area(r["loops"]) for r in regions) == pytest.approx(doc["size_mm"]["width"] * doc["size_mm"]["height"], rel=0.005)


def test_both_regions_of_a_border_walk_the_same_smooth_curve(split):
    smooth = sg.smoothed(split, 1.0)
    outlines = {r["id"]: r["loops"] for r in sg.regions_as_loops(smooth)}
    for arc in smooth["arcs"]:
        if arc["left"]:
            assert walks(outlines[arc["left"]], arc["points"])
        if arc["right"]:
            assert walks(outlines[arc["right"]], arc["points"][::-1])


def test_a_ring_keeps_its_hole_and_its_area_when_smoothed():
    doc = sg.segment(ring_picture(), 60.0, 3, use_faces=False)
    smooth = sg.smoothed(doc, 1.0)
    before = {r["id"]: len(r["loops"]) for r in doc["regions"]}
    regions = sg.regions_as_loops(smooth)
    assert {r["id"]: len(r["loops"]) for r in regions} == before and max(before.values()) == 2
    ring = math.pi * (42 ** 2 - 20 ** 2) * (60 / 120) ** 2                           # the red ring: a disc less its hole, in mm²
    assert any(outline_area(r["loops"]) == pytest.approx(ring, rel=0.03) for r in regions if len(r["loops"]) == 2)


def test_the_curves_of_a_region_are_closed_rings_that_start_inside_an_arc(split):
    smooth = sg.smoothed(split, 1.0)
    for r in sg.regions_as_loops(smooth):
        assert len(r["nodes"]) == len(r["loops"])
        for ring, loop in zip(r["nodes"], r["loops"]):
            assert len(ring) >= 2 and all(len(n) == 6 for n in ring)
            flat = np.asarray(contour.flatten(ring + ring[:1]))               # round the ring and back to its start
            assert np.abs(abs(vz._signed_area(flat.tolist())) - abs(vz._signed_area(loop))) <= 0.01 * abs(vz._signed_area(loop)) + 0.05


def test_the_preview_draws_the_curves_one_path_per_region(split):
    smooth = sg.smoothed(split, 1.0)
    paths = ET.fromstring(sg.to_svg(smooth)).findall(f"{SVG}path")
    assert len(paths) == len(split["regions"])
    for path in paths:
        d = path.get("d")
        assert d.startswith("M") and d.rstrip().endswith("Z") and " C" in d and " L" not in d
    assert " C" not in sg.to_svg(split)                                        # as traced: straight pieces, as before


def read_back(doc):
    regions = sg.regions_as_loops(doc)
    layers = {f"c{p['index']}": n for n, p in enumerate(doc["palette"])}
    settings = "".join(f'<CutSetting type="Scan"><index Value="{i}"/><name Value="C{i:02d}"/><maxPower Value="40"/>'
                       f'<speed Value="1000"/><frequency Value="40000"/></CutSetting>' for i in layers.values())
    xml = ('<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="2.0.04" FormatVersion="1">' + settings
           + "".join(vz.to_lbrn2_shapes({"regions": regions}, layers)) + "</LightBurnProject>")
    return regions, xml, [p for layer in lb.parse_bytes(xml.encode("utf-8")).layers for p in layer.regions]


@pytest.mark.parametrize("sigma", [0.5, 1.5])
def test_the_file_carries_the_curves_and_reads_back_where_the_preview_drew_them(split, sigma):
    regions, xml, back = read_back(sg.smoothed(split, sigma))
    assert xml.count("<PrimList>") == len(regions) and "B" in "".join(ET.fromstring(xml).itertext()) + xml.split("<PrimList>")[1]
    assert sum(chunk.count("B") for chunk in xml.split("<PrimList>")[1:]) > len(regions)           # curves, not only lines
    assert len(back) == len(regions) and all(p.closed and p.kind == "path" for p in back)
    mine = sorted(regions, key=lambda r: (round(outline_area(r["loops"]), 3), len(r["loops"])))
    read = sorted(back, key=lambda p: (round(outline_area([p.polygon] + p.holes), 3), len(p.holes)))
    for r, p in zip(mine, read):
        assert len(r["loops"]) - 1 == len(p.holes) and outline_area([p.polygon] + p.holes) == pytest.approx(outline_area(r["loops"]), rel=0.01)
        outline = np.asarray(p.polygon, np.float32)
        for point in np.vstack([np.asarray(loop) for loop in r["loops"][:1]]):                      # the preview's outline, point by point
            assert abs(cv2.pointPolygonTest(outline, (float(point[0]), float(point[1])), True)) < 0.02
    cov = sg.coverage([[p.polygon] + p.holes for p in back], split["size_mm"]["width"], split["size_mm"]["height"], 16)
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005


def test_a_split_as_traced_is_written_with_straight_lines_only(split):
    _, xml, back = read_back(split)
    assert all(chunk.count("B") == 0 for chunk in xml.split("<PrimList>")[1:] for chunk in [chunk.split("</PrimList>")[0]])
    assert back
