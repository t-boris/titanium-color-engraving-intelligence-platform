"""One region of a photo work split again into finer regions (feature work-size-and-splitting-a-region-again, REQ-002, DEC-084): the region's
picture is clustered into a few colours and every connected part becomes a region; every other region keeps its traced geometry, the picture
stays watertight, each new colour of the parts is one new colour of the palette, and the colouring, the exclusions and the photo zones of the
region carry to its parts. Run on a picture with a gradient square, which a split into a few colours keeps as one region."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from test_grey_scales import app_world  # noqa: F401  (the world of the photo zones' tests is made from it)
from test_vector_photo_zones import world  # noqa: F401
from test_vector_work import PAPER, colouring, refused, work  # noqa: F401  (fixtures)
from titanium_platform import plans as pl, segment as sg, vector_job


def gradient() -> bytes:
    """Paper with a square that runs from dark brown at the top to light orange at the bottom, and a blue disc."""
    img = np.full((180, 240, 3), PAPER, np.uint8)
    for y in range(40, 140):
        v = (y - 40) / 99
        img[y, 60:160] = (round(70 + 170 * v), round(35 + 120 * v), round(20 + 40 * v))
    cv2.circle(img, (200, 60), 25, (40, 70, 200), -1)
    return cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


def create(c, **extra):
    data = {"device_id": c["w"]["setup"][0], "lens_id": c["w"]["setup"][1], "material_id": c["ti"], "name": "Gradient", "width_mm": 60,
            "strategy": "photo", "n_colors": 3, "threshold": 6, "detail": "medium", "faces": "false", **extra}
    answer = c["client"].post("/api/vector", data=data, files={"image": ("gradient.png", gradient(), "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def document_of(c, j) -> dict:
    return json.loads(Path(pl.get_plan(c["store"], j["id"])["document_path"]).read_text(encoding="utf-8"))


def square_of(document) -> dict:
    """The gradient square: the region of 100 x 100 pixels, give or take its border."""
    return next(r for r in document["regions"] if 9000 <= r["pixels"] <= 11000)


def split(c, j, region, colours=3):
    return colouring(c, j, op="split_region", region=region, colours=colours)


def test_a_region_split_again_becomes_parts_and_every_other_region_keeps_its_traced_border(work):
    c = work
    j = create(c)
    before = document_of(c, j)
    square = square_of(before)
    after_view = split(c, j, square["id"])
    after = document_of(c, j)
    parts = [r for r in after["regions"] if r["id"] not in {r["id"] for r in before["regions"]}] + [r for r in after["regions"] if r["id"] == square["id"]]
    assert len(parts) >= 2 and after_view["document"]["version"] == 2 and after_view["document"]["regions"] == len(before["regions"]) + len(parts) - 1
    assert sum(r["pixels"] for r in parts) == square["pixels"] and max(parts, key=lambda r: r["pixels"])["id"] == square["id"]
    old_palette = {p["index"]: p for p in before["palette"]}
    new_colours = [p for p in after["palette"] if p["index"] not in old_palette]
    assert 1 <= len(new_colours) <= 2 and {r["color"] for r in parts} <= {square["color"]} | {p["index"] for p in new_colours}
    assert sum(p["pixels"] for p in after["palette"]) == sum(p["pixels"] for p in before["palette"])
    # the other regions: the same arcs point for point, the same pixels and colour
    def border(document, rid):
        arcs = document["arcs"]
        return sorted(tuple(map(tuple, arcs[ref if ref >= 0 else ~ref]["points"])) for loop in next(r for r in document["regions"] if r["id"] == rid)["loops"]
                      for ref in loop)
    for region in before["regions"]:
        if region["id"] == square["id"]:
            continue
        kept = next(r for r in after["regions"] if r["id"] == region["id"])
        assert (kept["pixels"], kept["color"]) == (region["pixels"], region["color"])
        old_points = [p for arc in border(before, region["id"]) for p in arc]
        new_points = {p for arc in border(after, region["id"]) for p in arc}
        assert set(old_points) <= new_points                      # every traced point is still there; a cut only adds the points it cuts at
    loops = [r["loops"] for r in sg.regions_as_loops(after)]
    covered = sg.coverage(loops, 60, 45, 8)
    assert covered["uncovered"] < 0.005 and covered["overlap"] < 0.005
    smooth = sg.coverage([r["loops"] for r in sg.regions_as_loops(sg.smoothed(after, 0.5))], 60, 45, 8)
    assert smooth["uncovered"] < 0.005 and smooth["overlap"] < 0.005
    # the new colours take the nearest titanium colour; the history names the step; the LightBurn file is written
    shown = {col["index"]: col for col in after_view["colours"]}
    assert all(shown[p["index"]]["status"] == "automatic" and shown[p["index"]]["entry_id"] for p in new_colours)
    plan = pl.get_plan(c["store"], j["id"])
    assert plan["history"][-1]["op"] == {"op": "split_region", "region": square["id"], "colours": 3, "keeper": square["id"]}
    assert c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").status_code == 200
    back = colouring(c, j, op="undo")
    assert back["document"]["version"] == 1 and document_of(c, j) == before


def test_the_parts_keep_the_regions_hand_colour_and_exclusion(work):
    c = work
    j = create(c)
    document = document_of(c, j)
    square = square_of(document)
    entry = next(e for e in j["entries"])
    colouring(c, j, op="paint", region=square["id"], scope="region", entry_id=entry)
    colouring(c, j, op="exclude_region", region=square["id"])
    after = split(c, j, square["id"])
    ids = [r["id"] for r in document_of(c, j)["regions"] if r["id"] == square["id"] or r["id"] not in {r["id"] for r in document["regions"]}]
    assert len(ids) >= 2 and after["colouring"]["regions"] == {square["id"]: entry}      # the hand colour stays on the largest part
    assert set(ids) <= set(after["colouring"]["excluded_regions"])


def test_a_region_of_a_photo_zone_splits_into_parts_of_that_zone(world):
    c = {"client": world["client"], "store": world["store"]}
    data = {"device_id": world["laser"]["id"], "lens_id": world["lens"]["id"], "material_id": world["titanium"]["id"], "name": "Gradient zone",
            "width_mm": 60, "strategy": "photo", "n_colors": 3, "threshold": 6, "detail": "medium", "faces": "false"}
    answer = world["client"].post("/api/vector", data=data, files={"image": ("gradient.png", gradient(), "image/png")})
    assert answer.status_code == 201, answer.text
    j = answer.json()
    document = document_of(c, j)
    square = square_of(document)
    colouring(c, j, op="photo_add", regions=[square["id"]])
    after = split(c, j, square["id"])
    ids = {r["id"] for r in document_of(c, j)["regions"]} - {r["id"] for r in document["regions"]} | {square["id"]}
    assert len(ids) >= 2 and set(after["zones"][0]["regions"]) == ids


def test_a_region_of_one_colour_or_a_wrong_number_of_colours_is_refused(work, monkeypatch):
    c = work
    j = create(c)
    document = document_of(c, j)
    square = square_of(document)
    paper = max(document["regions"], key=lambda r: r["pixels"])
    refused(c, j, {"op": "split_region", "region": paper["id"], "colours": 3}, "the region is one colour at this detail: there is nothing to split")
    for bad in (1, 9, "3", 2.5, True):
        refused(c, j, {"op": "split_region", "region": square["id"], "colours": bad}, "split a region into a whole number of colours from 2 to 8")
    refused(c, j, {"op": "split_region", "region": "r999", "colours": 3}, "there is no region 'r999'")
    monkeypatch.setattr(vector_job, "photo_cap", lambda markers: len(document["palette"]) + 1)
    refused(c, j, {"op": "split_region", "region": square["id"], "colours": 3}, "the work has room for 1 more colours: split the region into at most 2")
    monkeypatch.setattr(vector_job, "photo_cap", lambda markers: len(document["palette"]))
    refused(c, j, {"op": "split_region", "region": square["id"], "colours": 2},
            f"the work has all the {len(document['palette'])} colours LightBurn's layers allow: merge colours to split a region")
    assert c["client"].get(f"/api/vector/{j['id']}").json()["document"]["version"] == 1 and pl.get_plan(c["store"], j["id"])["undo"] == []


def test_a_split_region_can_be_split_again_and_a_size_change_keeps_the_parts(work):
    c = work
    j = create(c)
    square = square_of(document_of(c, j))
    once = split(c, j, square["id"], 2)
    again = split(c, j, square["id"], 2)                                               # the largest part keeps the id: split it again
    assert again["document"]["regions"] > once["document"]["regions"] and again["document"]["version"] == 3
    current = document_of(c, j)
    assert sg.coverage([x["loops"] for x in sg.regions_as_loops(current)], 60, 45, 8)["uncovered"] < 0.005
    r = c["client"].post(f"/api/vector/{j['id']}/size", json={"width_mm": 120})
    assert r.status_code == 200, r.text
    assert [x["id"] for x in document_of(c, j)["regions"]] == [x["id"] for x in current["regions"]]
    assert sg.coverage([x["loops"] for x in sg.regions_as_loops(document_of(c, j))], 120, 90, 4)["uncovered"] < 0.005


# -- the geometry of segment.split_region itself ---------------------------------------------------------------------------------------
def picture(hole: bool = False) -> np.ndarray:
    img = cv2.cvtColor(cv2.imdecode(np.frombuffer(gradient(), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    if hole:
        cv2.circle(img, (110, 90), 18, (40, 160, 60), -1)              # a green disc inside the square: a hole of the square's region
    return img


def split_alone(img: np.ndarray, n_colors: int, *, find=lambda r: 8000 <= r["pixels"] <= 11000):
    from titanium_platform import photo_zones as pz
    document = sg.segment(img, 60.0, 3, use_faces=False)
    raster = pz.labels(document, {r["id"]: r["loops"] for r in sg.regions_as_loops(document)})
    region = next(r for r in document["regions"] if find(r))
    new, parts = sg.split_region(document, raster, img, region["id"], n_colors)
    return document, region, new, parts


def shape(document: dict, region_id: str):
    from shapely.geometry import Polygon
    loops = next(r["loops"] for r in sg.regions_as_loops(document) if r["id"] == region_id)
    return Polygon(loops[0], loops[1:])


@pytest.mark.parametrize("n_colors", range(2, 9))
def test_every_number_of_colours_gives_parts_with_clean_outlines_that_fill_the_region_exactly(n_colors):
    """Each part's outline is a valid polygon (a loop may touch itself at a corner, as the split's own do, never cross), the parts
    cover the region exactly, and every other region is the same shape (to the 5 decimals points are kept at)."""
    import shapely
    document, region, new, parts = split_alone(picture(), n_colors)
    for part in parts:
        reason = shapely.is_valid_reason(shape(new, part))
        assert reason == "Valid Geometry" or reason.startswith("Ring Self-intersection"), (part, reason)
    union = shapely.union_all([shapely.make_valid(shape(new, p)) for p in parts])
    assert union.symmetric_difference(shape(document, region["id"])).area < 1e-3 * union.area
    for other in document["regions"]:                # the same curve: a cut point lies on it, rounded to 5 decimals as every point
        if other["id"] != region["id"]:
            assert shape(new, other["id"]).hausdorff_distance(shape(document, other["id"])) < 2e-5
    assert len({r["color"] for r in new["regions"] if r["id"] in parts}) <= n_colors


def test_a_region_with_a_hole_keeps_the_hole_and_the_region_in_it():
    document, region, new, parts = split_alone(picture(hole=True), 3, find=lambda r: len(r["loops"]) == 2)
    disc = next(r for r in document["regions"] if 900 <= r["pixels"] <= 1100)          # the disc of 18 px radius, the square's hole
    assert len(parts) >= 2 and shape(new, disc["id"]).hausdorff_distance(shape(document, disc["id"])) < 2e-5
    assert len(sg.neighbours(new)[disc["id"]] & set(parts)) >= 2 and sg.neighbours(new)[disc["id"]] <= set(parts)  # the bands cross it
    covered = sg.coverage([r["loops"] for r in sg.regions_as_loops(new)], 60, 45, 8)
    assert covered["uncovered"] < 0.005 and covered["overlap"] < 0.005


def test_the_pixels_of_a_region_become_one_piece_with_the_holes_of_its_outline_only():
    """A pixel left out inside the outline is filled, a hole of the outline stays, pieces touching at a corner are joined."""
    from shapely.geometry import Polygon
    mask = np.zeros((20, 20), bool)
    mask[2:18, 2:18] = True
    mask[5, 5] = False                                                   # left out by the rasterisation: inside the outline
    mask[10:13, 10:13] = False                                           # a hole of the outline
    hole = Polygon([(10, 10), (13, 10), (13, 13), (10, 13)])            # px_mm = 1
    out = sg._whole_mask(mask, [hole], 1.0)
    assert out[5, 5] and not out[11, 11]
    corners = np.zeros((10, 10), bool)
    corners[1:5, 1:5] = True
    corners[5:9, 5:9] = True                                             # touches the first only at the corner (5, 5)
    joined = sg._whole_mask(corners, [], 1.0)                            # by the two pixels next to both
    assert cv2.connectedComponents(joined.astype(np.uint8), connectivity=4)[0] == 2 and joined.sum() == corners.sum() + 2
    apart = np.zeros((20, 20), bool)
    apart[1:10, 1:10] = True
    apart[14:19, 14:19] = True                                           # a quarter of the pixels far apart: not a rasterisation slip
    with pytest.raises(sg.SplitError, match="outline does not match"):
        sg._whole_mask(apart, [], 1.0)
