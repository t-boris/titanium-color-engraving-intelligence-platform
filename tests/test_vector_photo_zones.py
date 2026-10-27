"""Photo zones of a vector work (REQ-073, DEC-114): selected regions of the split are engraved as a photo engraving of the work's own picture
(grayscale on a measured scale, or a dot kind such as Jarvis) instead of flat titanium colours; the zone leaves the colour layers, is drawn as it
will come out, is undone and redone with the colouring, survives merges and a new split, and is written to the file as one Image layer cut to
the zone (transparent outside it) after the colour layers."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
import pytest

import obs
from test_grey_scales import app_world  # noqa: F401  (a laser, lens and titanium with four measured grey scales)
from test_vector_work import BLUE, GREEN, PAPER, RED, YELLOW, lab, picture
from titanium_platform import ingest, lightburn as lb, objects, people, photo_knowledge as pk, photo_modes, photo_zones as pz, plans as pl
from titanium_platform import prediction_store as ps
from titanium_platform import segment as sg, setup as su, vector_job


@pytest.fixture(scope="module")
def world(app_world):  # noqa: F811
    """The grey-scale world with measured flat colours of the picture's five colours on the same laser, lens and titanium."""
    s = app_world["client"].app.state.store
    w = {"device": app_world["laser"], "setup": (app_world["laser"]["id"], app_world["lens"]["id"]), "n": 1000,
         "stand": su.save_capture_setup(s, "Zone rig", "cam", "LED", "90", "ColorChecker Classic")}
    for rgb, power in ((PAPER, 10), (RED, 20), (BLUE, 30), (GREEN, 40), (YELLOW, 50)):
        for _ in range(2):
            obs.add(s, w, lab(rgb), power=power, speed=500, line_interval=0.02, material_id=app_world["titanium"]["id"], layer_type="Scan")
    return {**app_world, "store": s, "w": w}


def create(world, material_id=None):
    client = world["client"]
    data = {"device_id": world["laser"]["id"], "lens_id": world["lens"]["id"], "material_id": material_id or world["titanium"]["id"],
            "name": "Portrait", "width_mm": 60, "strategy": "photo", "n_colors": 5, "threshold": 6, "detail": "medium", "faces": "false"}
    answer = client.post("/api/vector", data=data, files={"image": ("photo.png", picture(), "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def colouring(world, job, **op):
    answer = world["client"].post(f"/api/vector/{job['id']}/colouring", json=op)
    assert answer.status_code == 200, answer.text
    return answer.json()


def refused(world, job, op, message):
    answer = world["client"].post(f"/api/vector/{job['id']}/colouring", json=op)
    assert answer.status_code == 422 and answer.json()["error"] == message, (op, answer.text)


def document_of(world, job) -> dict:
    return json.loads(Path(pl.get_plan(world["store"], job["id"])["document_path"]).read_text(encoding="utf-8"))


def of_colour(world, job, rgb) -> list[str]:
    """The regions of the picture's colour nearest ``rgb``, in the document's order."""
    document = document_of(world, job)
    index = min(document["palette"], key=lambda p: sum((a - b) ** 2 for a, b in zip(p["srgb"], rgb)))["index"]
    return [r["id"] for r in document["regions"] if r["color"] == index]


def coloured(world, job) -> set[str]:
    """The regions the colour layers of the work engrave (the view gives only their count)."""
    return {rid for layer in pl.get_plan(world["store"], job["id"])["layers"] for rid in layer["region_ids"]}


def png(world, path) -> np.ndarray:
    answer = world["client"].get(path)
    assert answer.status_code == 200 and answer.headers["content-type"] == "image/png", answer.text
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(answer.content, np.uint8), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGRA2RGBA)


def mask_of(world, job, region_ids, k=10.0) -> np.ndarray:
    """The regions as the file's paths draw them (the smoothed borders), on a grid of ``k`` pixels a mm over the work."""
    plan = pl.get_plan(world["store"], job["id"])
    loops = vector_job._zone_loops(plan)
    size = plan["size_mm"]
    out = np.zeros((round(size["height"] * k), round(size["width"] * k)), np.uint8)
    for rid in region_ids:
        cv2.fillPoly(out, [pz._fixed(loop, k) for loop in loops[rid]], 1, shift=4)
    return out.astype(bool)


def struck(project, plan, layer, k=10.0) -> np.ndarray:
    """What an Image layer of a read file strikes, on the same grid as :func:`mask_of` (the file's offset taken off)."""
    dx, dy = pl.export_offset(plan)
    size = plan["size_mm"]
    to_mm = np.array([[1 / k, 0, 0.5 / k + dx], [0, 1 / k, 0.5 / k + dy], [0, 0, 1.0]])
    return photo_modes.struck_mask(layer, to_mm, (round(size["height"] * k), round(size["width"] * k)))


def iou(a, b) -> float:
    return float((a & b).sum() / max(1, (a | b).sum()))


def saved_by_lightburn_2_2(data: bytes, height: float) -> bytes:
    """The file as LightBurn 2.2 saves it again: MirrorY rewritten and every XForm reflected over the work's height (DEC-103)."""
    root = ET.fromstring(data)
    root.set("MirrorY", "False")
    for shape in root.findall(".//Shape"):
        xform = shape.find("XForm")
        if xform is not None:
            a, b, c, d, e, f = (float(value) for value in xform.text.split())
            xform.text = " ".join(str(value) for value in (a, -b, c, -d, e, height - f))
    return ET.tostring(root)


# -- a zone is made, shown and left out of the colours ------------------------------------------------------------------------------
def test_selected_regions_become_a_photo_zone_on_the_best_measured_scale_and_leave_the_colour_layers(world):
    job = create(world)
    red = of_colour(world, job, RED)
    assert job["zones"] == [] and job["zone_kinds"] == list(pz.KINDS) and "3dslice" not in job["zone_kinds"]
    before = {layer["entry_id"]: layer for layer in job["layers"]}
    after = colouring(world, job, op="photo_add", regions=red)
    (zone,) = after["zones"]
    store = world["store"]
    plan = pl.get_plan(store, job["id"])
    mode = pz.best_scale(store, plan, zone["width_mm"])
    lo, hi = ps.measured_span(store, mode, zone["width_mm"])
    hi = min(hi, pk.ordered_span(store, mode)[1])         # the scale's oxide turns lighter again: the zone stops before (REQ-004 of photo quality)
    assert (zone["number"], zone["regions"], zone["kind"], zone["by_colour"], zone["dot_power"]) == (1, red, "grayscale", True, None)
    assert zone["scale"] == pz.scale_data(mode) and (zone["min_power"], zone["max_power"]) == (lo, hi) and zone["problem"] is None
    assert zone["span"] == pytest.approx(list(ps.curve_for(store, mode, zone["width_mm"])[0].span), abs=0.01)
    # the ring is 90 px of a 240 px picture 60 mm wide: its box, and its width is the length of its rows
    assert zone["box"]["x"] == pytest.approx(15 / 240 * 60 * 1, abs=0.6) and zone["width_mm"] == pytest.approx(90 / 240 * 60, abs=0.8)
    assert not coloured(world, job) & set(red)                                                        # the ring is in no colour layer
    assert after["totals"]["zones"] == 1 and after["totals"]["zone_regions"] == len(red)
    assert len(after["layers"]) == len(before) - 1                                                   # its red recipe is not needed any more
    assert zone["index"] == after["layers"][-1]["index"] + 1 and zone["name"].startswith(f"C{zone['index']:02d} Photo 1 grayscale P")
    assert after["export_blocked"] is None
    rows = {row["index"]: row for row in after["time"]["layers"]}
    assert zone["index"] in rows and rows[zone["index"]]["seconds"] > 0                              # the job's time counts the zone
    assert after["time"]["seconds"] == pytest.approx(sum(row["seconds"] for row in after["time"]["layers"]))


def test_the_zones_picture_is_the_photo_engraving_inside_its_regions_and_transparent_outside(world):
    job = create(world)
    red = of_colour(world, job, RED)
    zone = colouring(world, job, op="photo_add", regions=red)["zones"][0]
    shown = png(world, zone["picture"])
    box = zone["box"]
    assert shown.shape[1] / shown.shape[0] == pytest.approx(box["width"] / box["height"], rel=0.02)
    k = shown.shape[1] / box["width"]
    inside = mask_of(world, job, red, k)[round(box["y"] * k):, round(box["x"] * k):][:shown.shape[0], :shown.shape[1]]
    opaque = shown[..., 3] == 255
    assert iou(opaque, inside) > 0.95                                       # opaque exactly on the ring, its hole transparent
    assert not opaque[shown.shape[0] // 2, shown.shape[1] // 2]              # the paper in the middle of the ring is not the zone's
    colours = shown[opaque][:, :3]
    assert colours.std(axis=0).max() < 40 and len(np.unique(colours, axis=0)) >= 1    # one red: the scale's colour for its grey
    # the same picture again is the cached one, the address names its key
    assert world["client"].get(zone["picture"]).headers["etag"].strip('"').startswith(zone["picture"].split("v=")[1])


def test_the_kind_of_a_zone_is_chosen_from_tiles_of_the_zone_in_every_kind_and_a_dot_kind_fires_every_dot_at_one_power(world):
    job = create(world)
    red = of_colour(world, job, RED)
    colouring(world, job, op="photo_add", regions=red)
    offered = world["client"].get(f"/api/vector/{job['id']}/photo/1/kinds").json()
    assert offered["kind"] == "grayscale" and [k["key"] for k in offered["kinds"]] == list(pz.KINDS)
    tiles = {k["key"]: png(world, k["picture"]) for k in offered["kinds"]}
    assert all(max(t.shape[:2]) <= pz.TILE_PX for t in tiles.values()) and len({t.tobytes() for t in tiles.values()}) >= 3
    dots = [k for k in offered["kinds"] if k["key"] != "grayscale"]
    assert all(k["estimate"] and k["hex"].startswith("#") for k in dots) and len({k["power"] for k in dots}) == 1
    jarvis = colouring(world, job, op="photo_set", zone=1, kind="jarvis")["zones"][0]
    assert jarvis["kind"] == "jarvis" and jarvis["dot_power"] == dots[0]["power"] and jarvis["estimate"]
    assert jarvis["dots"]["hex"] == dots[0]["hex"] and jarvis["name"].endswith(f"jarvis P{jarvis['dot_power']:g}")
    assert world["client"].get(f"/api/vector/{job['id']}/photo/1/kinds/3dslice.png").status_code == 404
    refused(world, job, {"op": "photo_set", "zone": 1, "kind": "3dslice"}, "there is no kind of photo engraving '3dslice'")
    lo, hi = ps.curve_for(world["store"], pz.mode_of(pl.get_plan(world["store"], job["id"]), jarvis), jarvis["width_mm"])[0].span
    refused(world, job, {"op": "photo_set", "zone": 1, "dot_power": 99},
            f"the dots' power 99 % lies outside the measured powers {lo:g}..{hi:g} % of the scale at this width: choose it inside them")


def test_another_scale_brings_its_span_and_min_max_and_colours_by_the_picture_are_set_by_hand(world):
    job = create(world)
    red = of_colour(world, job, RED)
    zone = colouring(world, job, op="photo_add", regions=red)["zones"][0]
    store = world["store"]
    plan = pl.get_plan(store, job["id"])
    others = [m for m in ps.scale_modes(store, plan["device_id"], plan["lens_id"], plan["material_id"]) if pz.scale_data(m) != zone["scale"]]
    other = others[0]
    moved = colouring(world, job, op="photo_set", zone=1, scale=pz.scale_data(other))["zones"][0]
    assert moved["scale"] == pz.scale_data(other) and [moved["min_power"], moved["max_power"]] == list(pk.default_span(store, other, moved["width_mm"]))
    assert moved["max_power"] < ps.measured_span(store, other, moved["width_mm"])[1]       # up to where its tones turn back
    hand = colouring(world, job, op="photo_set", zone=1, min_power=5, max_power=12, by_colour=False)["zones"][0]
    assert (hand["min_power"], hand["max_power"], hand["by_colour"]) == (5, 12, False)
    refused(world, job, {"op": "photo_set", "zone": 1, "min_power": 30, "max_power": 12},
            "Min power 30 % and Max power 12 % must lie within 0..100 % with Min not above Max")
    refused(world, job, {"op": "photo_set", "zone": 1, "scale": {**pz.scale_data(other), "speed": 9999}},
            "this scale is not measured: choose one of the measured scales")
    refused(world, job, {"op": "photo_set", "zone": 7, "kind": "jarvis"}, "there is no photo zone 7")
    refused(world, job, {"op": "photo_set", "zone": 1}, "say what to change in the photo zone")
    refused(world, job, {"op": "photo_set", "zone": 1, "colour": 3}, "a photo zone has no setting 'colour'")


# -- zones one after another, regions moved, given back -------------------------------------------------------------------------------
def test_a_second_zone_takes_the_photo_engraving_of_the_last_one_regions_move_between_zones_and_go_back_to_their_colours(world):
    job = create(world)
    red, blue, yellow = of_colour(world, job, RED), of_colour(world, job, BLUE), of_colour(world, job, YELLOW)
    colouring(world, job, op="photo_add", regions=red)
    first = colouring(world, job, op="photo_set", zone=1, kind="atkinson")["zones"][0]
    two = colouring(world, job, op="photo_add", regions=blue)["zones"]
    assert [z["number"] for z in two] == [1, 2] and (two[1]["kind"], two[1]["scale"]) == ("atkinson", first["scale"])
    moved = colouring(world, job, op="photo_add", regions=blue, zone=1)["zones"]      # zone 2 is left without a region: it is gone
    assert [z["number"] for z in moved] == [1] and set(moved[0]["regions"]) == set(red + blue)
    back = colouring(world, job, op="photo_remove", regions=red)
    assert back["zones"][0]["regions"] == blue and set(red) <= coloured(world, job)  # the ring is coloured again
    third = colouring(world, job, op="photo_add", regions=yellow)["zones"]
    assert [z["number"] for z in third] == [1, 2] and third[1]["regions"] == yellow
    gone = colouring(world, job, op="photo_delete", zone=1)
    assert [z["number"] for z in gone["zones"]] == [2] and set(blue) <= coloured(world, job)
    refused(world, job, {"op": "photo_add", "regions": []}, "choose one or more regions")
    refused(world, job, {"op": "photo_add", "regions": ["r9999"]}, "there is no region 'r9999'")
    refused(world, job, {"op": "photo_delete", "zone": 1}, "there is no photo zone 1")


def test_a_region_left_out_of_the_file_is_engraved_again_when_it_is_put_into_a_zone(world):
    job = create(world)
    red = of_colour(world, job, RED)
    out = colouring(world, job, op="exclude_region", regions=red)
    assert set(red) <= set(out["colouring"]["excluded_regions"])
    zoned = colouring(world, job, op="photo_add", regions=red)
    assert not set(red) & set(zoned["colouring"]["excluded_regions"]) and zoned["zones"][0]["regions"] == red


def test_every_change_of_a_zone_is_undone_and_redone_and_a_colour_variant_keeps_the_zones(world):
    job = create(world)
    red = of_colour(world, job, RED)
    colouring(world, job, op="photo_add", regions=red)
    colouring(world, job, op="photo_set", zone=1, kind="jarvis")
    assert colouring(world, job, op="undo")["zones"][0]["kind"] == "grayscale"
    assert colouring(world, job, op="undo")["zones"] == []
    assert colouring(world, job, op="redo")["zones"][0]["kind"] == "grayscale"
    assert colouring(world, job, op="redo")["zones"][0]["kind"] == "jarvis"
    variant = colouring(world, job, op="assign", mode="random")
    assert variant["zones"][0]["kind"] == "jarvis"                                 # an automatic colouring keeps the zones
    colouring(world, job, op="photo_set", zone=1, kind="grayscale")
    restored = colouring(world, job, op="restore", variant=1)                       # made before the zone: the zone stays as it is now
    assert restored["zones"][0]["kind"] == "grayscale" and restored["colouring"]["variant"] == 1


def test_a_merged_region_is_in_the_zone_that_held_half_of_it_or_more(world):
    job = create(world)
    document = document_of(world, job)
    (ring,) = of_colour(world, job, RED)
    pixels = {r["id"]: r["pixels"] for r in document["regions"]}
    hole = min(sg.neighbours(document)[ring], key=pixels.get)                          # the paper inside the ring
    colouring(world, job, op="photo_add", regions=[ring])
    filled = colouring(world, job, op="merge_regions", regions=[ring, hole])
    assert filled["zones"][0]["regions"] == [ring]                                     # the ring is the larger: it is left, in the zone
    merged = document_of(world, filled)
    around = max(sg.neighbours(merged)[ring], key={r["id"]: r["pixels"] for r in merged["regions"]}.get)
    swallowed = colouring(world, job, op="merge_regions", regions=[ring, around])
    assert swallowed["zones"] == []                                                    # the paper around holds more: no zone is left
    assert colouring(world, job, op="undo")["zones"][0]["regions"] == [ring]


def test_a_new_split_keeps_the_zone_on_the_new_regions_inside_it(world):
    job = create(world)
    red = of_colour(world, job, RED)
    colouring(world, job, op="photo_add", regions=red)
    colouring(world, job, op="photo_set", zone=1, kind="jarvis")
    answer = world["client"].post(f"/api/vector/{job['id']}/split", json={"n_colors": 6, "detail": "fine", "faces": False})
    assert answer.status_code == 200, answer.text
    (zone,) = answer.json()["zones"]
    ring = np.zeros((450, 600), np.uint8)                                              # 10 px a mm over the 60 x 45 mm work
    cv2.circle(ring, (150, 175), 112, 1, -1)
    cv2.circle(ring, (150, 175), 45, 0, -1)
    assert zone["kind"] == "jarvis" and iou(mask_of(world, answer.json(), zone["regions"]), ring.astype(bool)) > 0.9


def test_a_lasso_selects_the_regions_at_least_half_inside_it(world):
    job = create(world)
    yellow = of_colour(world, job, YELLOW)
    cx, cy, r = 195 / 4, 150 / 4, 22 / 4 + 1.0                                     # mm: 4 px of the picture a mm
    circle = [[cx + r * np.cos(t), cy + r * np.sin(t)] for t in np.linspace(0, 2 * np.pi, 24, endpoint=False)]
    got = world["client"].post(f"/api/vector/{job['id']}/lasso", json={"points": circle}).json()
    assert got["regions"] == yellow and got["version"] == job["document"]["version"]
    half = [[cx, cy - r], [cx + r, cy - r], [cx + r, cy + r], [cx, cy + r]]          # the right half of the disc: under half of it
    assert set(world["client"].post(f"/api/vector/{job['id']}/lasso", json={"points": half}).json()["regions"]) <= set(yellow)
    bad = world["client"].post(f"/api/vector/{job['id']}/lasso", json={"points": [[0, 0], [1, 1]]})
    assert bad.status_code == 422 and bad.json()["error"] == "a lasso needs three points or more, each x and y in mm"


# -- the file -------------------------------------------------------------------------------------------------------------------------
def test_the_file_engraves_the_zone_as_an_image_layer_after_the_colours_transparent_outside_the_zone_and_upright(world):
    job = create(world)
    red, yellow = of_colour(world, job, RED), of_colour(world, job, YELLOW)    # top left and bottom right: upside down they would swap
    zone = colouring(world, job, op="photo_add", regions=red + yellow)["zones"][0]
    after = world["client"].get(f"/api/vector/{job['id']}").json()
    data = world["client"].get(f"/api/vector/{job['id']}/export.lbrn2").content
    assert b'MirrorY="True"' in data
    project = lb.parse_bytes(data)
    layers = sorted(project.layers, key=lambda layer: layer.index)
    assert layers[0].name.startswith("CLEAN-") and [layer.index for layer in layers] == list(range(len(layers)))
    image = layers[-1]
    assert (image.index, image.name, image.layer_type) == (zone["index"], zone["name"], "Image")
    summary = image.image_summary()
    assert (summary["dither"], summary["min_power"], summary["max_power"]) == ("grayscale", zone["min_power"], zone["max_power"])
    assert (image.speed, image.frequency_khz, image.line_interval) == (zone["scale"]["speed"], zone["scale"]["frequency"],
                                                                      pytest.approx(zone["scale"]["line_interval"]))
    assert all(layer.layer_type == "Scan" for layer in layers[1:-1]) and len(layers) - 2 == len(after["layers"])
    plan = pl.get_plan(world["store"], job["id"])
    wanted = mask_of(world, job, red + yellow)
    hit = struck(project, plan, image)
    assert iou(hit, wanted) > 0.93                                                  # the picture lies on the zone, the right way up
    paths = cv2.erode(mask_of(world, job, sorted(coloured(world, job))).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    assert (hit & paths).sum() / max(1, hit.sum()) < 0.002                          # and not over the colours around it (0.2 mm off a border)
    # LightBurn 2.2 saves it again with MirrorY off and every shape reflected: read against the work it lies on the zone still
    resaved = lb.parse_bytes(saved_by_lightburn_2_2(data, plan["size_mm"]["height"] - 2 * pl.export_offset(plan)[1]))
    assert ingest._normalize_project_to_plan(resaved, plan) == ["Y"]
    again = sorted(resaved.layers, key=lambda layer: layer.index)[-1]
    assert iou(struck(resaved, plan, again), wanted) > 0.93
    export = pl.get_plan(world["store"], job["id"])["exports"][-1]
    assert export["layers"] == len(after["layers"]) + 1 and export["zones"][0]["regions"] == red + yellow
    assert export["zones"][0]["name"] == zone["name"] and len(export["promised"]) == len(after["layers"])


def test_a_dot_kind_zone_is_written_with_every_dot_at_one_power_and_the_pictures_own_greys(world):
    job = create(world)
    red = of_colour(world, job, RED)
    colouring(world, job, op="photo_add", regions=red)
    zone = colouring(world, job, op="photo_set", zone=1, kind="jarvis")["zones"][0]
    project = lb.parse_bytes(world["client"].get(f"/api/vector/{job['id']}/export.lbrn2").content)
    image = sorted(project.layers, key=lambda layer: layer.index)[-1]
    summary = image.image_summary()
    assert (summary["dither"], summary["min_power"], summary["max_power"]) == ("jarvis", zone["dot_power"], zone["dot_power"])


def test_zones_take_layers_of_their_own_and_a_work_with_more_than_the_file_holds_is_not_written(world, monkeypatch):
    job = create(world)
    red = of_colour(world, job, RED)
    colours = len(colouring(world, job, op="photo_add", regions=red)["layers"])
    monkeypatch.setattr(vector_job, "photo_cap", lambda markers: colours)
    full = world["client"].get(f"/api/vector/{job['id']}").json()
    assert full["export_blocked"] == (f"{colours} different recipes and 1 photo zone(s) need more LightBurn layers than the {colours} available: "
                                      "merge titanium colours or zones")
    answer = world["client"].get(f"/api/vector/{job['id']}/export.lbrn2")
    assert answer.status_code == 422 and answer.json()["error"] == full["export_blocked"]


def test_no_zone_is_made_on_a_titanium_without_a_measured_grey_scale(world):
    store = world["store"]
    other = su.save_material(store, "Grade 1 sheet", grade="Grade 1", thickness_mm=1.0)["id"]
    for rgb, power in ((PAPER, 10), (RED, 20), (BLUE, 30), (GREEN, 40), (YELLOW, 50)):
        obs.add(store, world["w"], lab(rgb), power=power, speed=500, line_interval=0.02, material_id=other, layer_type="Scan")
    job = create(world, other)
    refused(world, job, {"op": "photo_add", "regions": of_colour(world, job, RED)},
            "no grey scale is measured on this laser, lens and titanium: engrave the grey-ramp plate (Фотогравировка → Шкалы серого) to make a photo zone")


def test_the_list_picture_shows_the_zone_as_it_will_come_out(world):
    job = create(world)
    red = of_colour(world, job, RED)
    before = png(world, f"/api/vector/{job['id']}/thumb.png")
    zone = colouring(world, job, op="photo_add", regions=red)["zones"][0]
    after = png(world, f"/api/vector/{job['id']}/thumb.png")
    assert before.shape == after.shape
    k = after.shape[1] / 60
    x, y = round((zone["box"]["x"] + 2) * k), round((70 / 4) * k)                  # on the ring, left of its hole
    shown = png(world, zone["picture"])
    kz = shown.shape[1] / zone["box"]["width"]
    expected = shown[round((70 / 4 - zone["box"]["y"]) * kz), round(2 * kz), :3].astype(int)
    assert np.abs(after[y, x, :3].astype(int) - expected).max() <= 12 and np.abs(before[y, x, :3].astype(int) - expected).max() > 12


def test_the_brush_on_a_zones_region_gives_it_a_colour_and_a_fill_stops_at_the_zone(world):
    job = create(world)
    red, blue = of_colour(world, job, RED), of_colour(world, job, BLUE)
    colouring(world, job, op="photo_add", regions=red + blue)
    entry = next(iter(job["entries"]))
    painted = colouring(world, job, op="paint", region=blue[0], scope="region", entry_id=entry)
    assert blue[0] not in painted["zones"][0]["regions"] and blue[0] in coloured(world, job)
    reach = world["client"].get(f"/api/vector/{job['id']}/reach", params={"region": of_colour(world, job, PAPER)[0], "similarity_de": 200}).json()
    assert not set(reach["regions"]) & set(red)                                    # the paper's fill does not spill into the ring's zone
    whole = colouring(world, job, op="paint", region=red[0], scope="colour", entry_id=entry)
    assert whole["zones"][0]["regions"] == red                                       # a whole source colour leaves the zone as it is


def test_a_region_of_a_zone_left_out_of_the_file_leaves_the_zone(world):
    job = create(world)
    red, blue = of_colour(world, job, RED), of_colour(world, job, BLUE)
    colouring(world, job, op="photo_add", regions=red + blue)
    out = colouring(world, job, op="exclude_region", regions=blue)
    assert out["zones"][0]["regions"] == red and set(blue) <= set(out["colouring"]["excluded_regions"])


def test_a_copy_of_the_work_keeps_its_photo_zones(world):
    job = create(world)
    red = of_colour(world, job, RED)
    made = colouring(world, job, op="photo_add", regions=red)
    copied = world["client"].post(f"/api/vector/{job['id']}/copy", json={}).json()["id"]
    view = world["client"].get(f"/api/vector/{copied}").json()
    assert [(z["number"], z["regions"], z["kind"]) for z in view["zones"]] == [(z["number"], z["regions"], z["kind"]) for z in made["zones"]]
    assert world["client"].get(view["zones"][0]["picture"]).status_code == 200


def test_the_engraving_plan_lists_each_zone_as_its_image_layer_after_the_colour_layers(world):
    job = create(world)
    assert world["client"].get(f"/api/plans/{job['id']}").json()["photo_zones"] == []
    red, yellow = of_colour(world, job, RED), of_colour(world, job, YELLOW)
    colouring(world, job, op="photo_add", regions=red)
    view = colouring(world, job, op="photo_add", regions=yellow)
    colouring(world, job, op="photo_set", zone=view["zones"][1]["number"], kind="jarvis")
    view = world["client"].get(f"/api/vector/{job['id']}").json()
    plan = world["client"].get(f"/api/plans/{job['id']}").json()
    assert [(z["index"], z["name"], z["regions"], z["picture"]) for z in plan["photo_zones"]] == \
        [(z["index"], z["name"], z["regions"], z["picture"]) for z in view["zones"]]
    assert [z["index"] for z in plan["photo_zones"]] == [layer["index"] + 1 + n for n, layer in enumerate(plan["layers"][-1:] * 2)]
    gray, dots = (z["parameters"] for z in plan["photo_zones"])
    assert gray["min_power"] < gray["power"] and dots["min_power"] == dots["power"] and dots["power"] == view["zones"][1]["dot_power"]
    assert all(z["parameters"]["speed"] > 0 and z["parameters"]["line_interval"] > 0 for z in plan["photo_zones"])
    data = world["client"].get(f"/api/plans/{job['id']}/export.lbrn2").content         # the plan's export writes them too
    names = [layer.name for layer in lb.parse_bytes(data).layers]
    assert [z["name"] for z in plan["photo_zones"]] == names[-2:]


# -- how a zone chooses its greys, as a photo work does (0.23.0, DEC-116) ----------------------------------------------------------------
def zone_grey(world, job) -> np.ndarray:
    """The picture of the last zone's Image layer as the file carries it (BGRA)."""
    project = lb.parse_bytes(world["client"].get(f"/api/vector/{job['id']}/export.lbrn2").content)
    image = sorted(project.layers, key=lambda layer: layer.index)[-1]
    return cv2.imdecode(np.frombuffer(image.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)


def stored_zones(world, job) -> list[dict]:
    return json.loads(world["store"].one("SELECT data_json FROM plan WHERE id=?", (job["id"],))["data_json"])["colouring"]["photo"]


def test_a_zone_chooses_its_greys_as_a_photo_work_does_and_its_picture_its_file_and_the_next_zone_follow(world):
    job = create(world)
    red, yellow = of_colour(world, job, RED), of_colour(world, job, YELLOW)
    zone = colouring(world, job, op="photo_add", regions=red + yellow)["zones"][0]
    assert {k: zone[k] for k in pz.DEFAULTS} == {"colour_choice": "drawing", "contours": False, "rules": [], "colouring": {}, "dot_recipe": None,
                                                 "tone": {"brightness": 0.0, "contrast": 0.0, "gamma": 1.0}, "sharpness": 0.0,
                                                 "tone_after_match": False, "ai": None, "ai_theme": None}
    drawn, filed = png(world, zone["picture"]), zone_grey(world, job)
    nearest = colouring(world, job, op="photo_set", zone=1, colour_choice="nearest")["zones"][0]
    assert nearest["colour_choice"] == "nearest" and nearest["picture"] != zone["picture"]
    assert not np.array_equal(png(world, nearest["picture"]), drawn) and not np.array_equal(zone_grey(world, job), filed)
    lined = colouring(world, job, op="photo_set", zone=1, contours=True)["zones"][0]
    assert lined["contours"] is True and lined["picture"] != nearest["picture"]
    two = colouring(world, job, op="photo_add", regions=of_colour(world, job, BLUE))["zones"]
    assert [(z["colour_choice"], z["contours"]) for z in two] == [("nearest", True)] * 2         # the last zone's photo engraving
    assert colouring(world, job, op="undo")["zones"] == [lined]
    assert colouring(world, job, op="undo")["zones"][0]["contours"] is False
    for change, message in (({"colour_choice": "prettiest"}, "the colour choice must keep the drawing, take the nearest colour or colour the objects"),
                            ({"contours": 1}, "the contours must be on or off"),
                            ({"colouring": {"dress": {"power": 10}}}, f"an object is named by its kind ({', '.join(objects.KINDS)}), a background "
                                                                        "piece also by its number"),
                            ({"rules": [{"part": "tail", "kind": "neutral"}]}, f"a rule must name one of the parts {', '.join(people.PARTS)}, each once")):
        refused(world, job, {"op": "photo_set", "zone": 1, **change}, message)


def test_a_rule_of_a_part_changes_the_zone_inside_that_part_only(world, monkeypatch):
    def scores(bgr):                                    # the people model as if the zone's left half were face skin and its right half clothes
        out = np.zeros((256, 256, 6), np.float32)
        out[:, :128, people.PARTS.index("face_skin")] = 1
        out[:, 128:, people.PARTS.index("clothes")] = 1
        return out
    monkeypatch.setattr(people, "scores", scores)
    monkeypatch.setattr(pz, "_cuts", type(pz._cuts)())   # the cuts of earlier tests carry no scores of this model
    job = create(world)
    red = of_colour(world, job, RED)
    zone = colouring(world, job, op="photo_add", regions=red)["zones"][0]
    before = zone_grey(world, job)
    ruled = colouring(world, job, op="photo_set", zone=1, rules=[{"part": "clothes", "kind": "colour", "hex": "#2040c0"}])["zones"][0]
    assert ruled["rules"] == [{"part": "clothes", "kind": "colour", "lab": ruled["rules"][0]["lab"], "hex": ruled["rules"][0]["hex"]}]
    assert stored_zones(world, job)[0]["rules"][0].keys() == {"part", "kind", "lab"} and ruled["picture"] != zone["picture"]
    after = zone_grey(world, job)
    half = after.shape[1] // 2
    opaque = after[..., 3] > 0
    changed = (after[..., 0] != before[..., 0]) & opaque
    assert changed[:, half + 2:].any() and not changed[:, :half - 2].any()


def test_a_zone_made_before_its_greys_could_be_chosen_reads_them_as_the_drawing_kept(world):
    job = create(world)
    made = colouring(world, job, op="photo_add", regions=of_colour(world, job, RED))["zones"][0]
    store = world["store"]
    data = json.loads(store.one("SELECT data_json FROM plan WHERE id=?", (job["id"],))["data_json"])
    data["colouring"]["photo"] = [{k: v for k, v in z.items() if k not in pz.DEFAULTS} for z in data["colouring"]["photo"]]
    with store.transaction():
        store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), job["id"]))
    old = world["client"].get(f"/api/vector/{job['id']}").json()["zones"][0]
    assert old == made and world["client"].get(old["picture"]).status_code == 200
    assert world["client"].get(f"/api/vector/{job['id']}/export.lbrn2").status_code == 200
    colouring(world, job, op="photo_set", zone=1, contours=True)
    assert stored_zones(world, job)[0].keys() >= set(pz.DEFAULTS)


# -- a zone on its own screen, as a photo work opens (0.23.0, DEC-116) -----------------------------------------------------------------
def test_a_zone_opens_on_its_own_screen_with_its_picture_beside_its_look_and_its_changes_are_steps_of_the_work(world):
    job = create(world)
    client = world["client"]
    made = colouring(world, job, op="photo_add", regions=of_colour(world, job, RED))["zones"][0]
    view = client.get(f"/api/vector/{job['id']}/photo/1").json()
    assert {k: view[k] for k in ("number", "regions", "index", "name", "kind", "min_power", "max_power", "colour_choice", "contours")} == \
        {k: made[k] for k in ("number", "regions", "index", "name", "kind", "min_power", "max_power", "colour_choice", "contours")}
    assert view["scale"]["device_id"] == world["laser"]["id"] and view["scale"]["speed"] == made["scale"]["speed"]
    assert view["work"] == {"id": job["id"], "name": "Portrait", "device_id": world["laser"]["id"], "lens_id": world["lens"]["id"],
                            "material_id": world["titanium"]["id"], "undo": 1, "redo": 0} and view["time"]["seconds"] > 0
    shown = view["picture"]
    assert shown["by_colour"] and shown["colour_match"]["choice"] == "drawing" and shown["size_mm"]["width"] == pytest.approx(made["box"]["width"], abs=0.01)
    both = png(world, shown["preview"])
    half = (both.shape[1] - 8) // 2
    assert both.shape[2] == 4 and not both[..., 3].all() and np.array_equal(both[:, :half, 3], both[:, half + 8:, 3])   # transparent outside it
    nearest = client.post(f"/api/vector/{job['id']}/photo/1/settings", json={"colour_choice": "nearest"}).json()
    assert nearest["colour_choice"] == "nearest" and nearest["picture"]["colour_match"]["choice"] == "nearest" and nearest["work"]["undo"] == 2
    assert nearest["picture"]["preview"] != shown["preview"]
    dots = client.post(f"/api/vector/{job['id']}/photo/1/settings", json={"kind": "jarvis"}).json()
    assert dots["picture"]["dots"]["power"] == dots["dot_power"] and dots["picture"]["estimate"] and dots["picture"]["dots"]["struck_share"] > 0
    assert png(world, dots["picture"]["closeup"]).shape[0] > 0 and png(world, dots["picture"]["preview"]).shape[2] == 4
    refused_ = client.post(f"/api/vector/{job['id']}/photo/1/settings", json={"colour_choice": "prettiest"})
    assert refused_.status_code == 422 and refused_.json()["error"] == "the colour choice must keep the drawing, take the nearest colour or colour the objects"
    back = client.post(f"/api/vector/{job['id']}/photo/1/undo").json()
    assert back["kind"] == "grayscale" and back["work"]["redo"] == 1
    assert client.post(f"/api/vector/{job['id']}/photo/1/redo").json()["kind"] == "jarvis"
    for _ in range(3):
        last = client.post(f"/api/vector/{job['id']}/photo/1/undo").json()
    assert last == {"gone": True, "work": {"id": job["id"]}}                           # the zone's making was undone too
    assert client.get(f"/api/vector/{job['id']}/photo/1").status_code == 404
