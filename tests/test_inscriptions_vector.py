"""Inscriptions in a vector work (feature inscriptions-in-works, REQ-003, REQ-004, DEC-003): an inscription is an object of the work's
colouring, made, changed and taken away by the colour editor's operations (one step of undo each). Its letters are engraved in their
titanium colour on the layer of that colour; the regions under its cut (the letters widened by the gap, or its backing) give that part up,
in the area, the time and the file; a photo zone under it is transparent there; the file's letters read back have the area the work
promised. Measured on the test font (``font_kit``)."""
import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon

from test_grey_scales import app_world  # noqa: F401  (the world of the photo zones' tests is made from it)
from test_vector_photo_zones import colouring, create, mask_of, of_colour, refused, struck, world  # noqa: F401
from test_vector_work import RED
from titanium_platform import fonts, lettering, lightburn as lb, plans as pl, vector_job


def face(store, family="Test Sans"):
    return fonts.described(next(f for f in fonts.faces(store.data_dir).values() if f["family"] == family and f["style"] == "Regular"))


def add(world, job, **text):
    return colouring(world, job, op="text_add", text={"font": face(world["store"]), "text": "HOH", "height_mm": 8, "x": 30, "y": 25, **text})


def total_area(view) -> float:
    return sum(layer["area_mm2"] for layer in view["layers"])


def read_back(world, job) -> tuple[dict, lb.Project]:
    plan = pl.get_plan(world["store"], job["id"])
    return plan, lb.parse_bytes(world["client"].get(f"/api/vector/{job['id']}/export.lbrn2").content)


def shapes_of(plan, layer) -> shapely.MultiPolygon:
    """A layer's filled shapes read back from the file, in the work's mm (the file's offset taken off)."""
    dx, dy = pl.export_offset(plan)
    polygons = [Polygon(np.asarray(r.polygon) - [dx, dy], [np.asarray(h) - [dx, dy] for h in r.holes]) for r in layer.regions]
    return shapely.union_all([shapely.make_valid(p) for p in polygons])


def test_an_inscription_is_engraved_on_the_layer_of_its_colour_and_cut_into_the_regions_under_it(world):
    job = create(world)
    before = total_area(job)
    after = add(world, job)
    (text,) = after["texts"]
    assert text["id"] == "t1" and text["problem"] is None and text["shown"]["letters"].startswith("M") and text["shown"]["cut"]
    darkest = min(vector_job._palette(world["store"], pl.get_plan(world["store"], job["id"])), key=lambda e: (e["lab"][0], e["id"]))
    assert text["entry_id"] == darkest["id"] and text["srgb"] is not None                        # the colour that stands out most
    plan = pl.get_plan(world["store"], job["id"])
    found = lettering.geometry(world["store"].data_dir, text, plan["size_mm"])
    engraved = [r for layer in plan["layers"] for r in layer["region_ids"]]
    shapes = vector_job._region_shapes(plan)
    under = sum(shapely.intersection(shapes[r], found["cut"]).area for r in engraved)
    assert under > 0                                                                              # the inscription stands on the picture
    assert total_area(after) == pytest.approx(before - under + found["letters"].area, rel=0.01)
    layer = next(layer for layer in after["layers"] if layer["entry_id"] == text["entry_id"])
    assert layer["texts"] == ["t1"] and after["totals"]["texts"] == 1
    timed = {row["index"]: row for row in after["time"]["layers"]}
    assert timed[layer["index"]]["seconds"] > 0 and after["time"]["seconds"] == pytest.approx(sum(r["seconds"] for r in after["time"]["layers"]))
    assert after["export_blocked"] is None


def test_the_file_has_the_letters_on_their_layer_and_nothing_of_the_regions_under_their_cut(world):
    job = create(world)
    plan, project = read_back(world, job)
    plain = {layer.index: shapes_of(plan, layer).area for layer in project.layers if layer.regions}
    view = add(world, job, gap_mm=0.5)
    text = view["texts"][0]
    plan, project = read_back(world, job)
    found = lettering.geometry(world["store"].data_dir, text, plan["size_mm"])
    layers = {layer.index: layer for layer in project.layers}
    promised = {layer["index"]: layer for layer in view["layers"]}
    was = {layer["index"]: layer["area_mm2"] for layer in job["layers"]}
    for index, layer in promised.items():   # what the inscription changed in each layer's shapes read back is what the work promised
        read = shapes_of(plan, layers[index]).area - plain[index]
        said = layer["area_mm2"] - was[index]
        assert read == pytest.approx(said, rel=0.02, abs=0.05)
    others = shapely.union_all([shapes_of(plan, layers[i]) for i, layer in promised.items() if layer["entry_id"] != text["entry_id"]])
    assert shapely.intersection(others, found["cut"]).area < 0.01                               # the cut is clean titanium
    own = shapes_of(plan, layers[next(i for i, layer in promised.items() if layer["entry_id"] == text["entry_id"])])
    assert shapely.intersection(own, found["letters"]).area == pytest.approx(found["letters"].area, rel=0.01)
    assert shapely.difference(shapely.intersection(own, found["cut"]), found["letters"]).area < 0.01     # the gap stays clean


def test_a_backing_in_its_own_colour_and_a_bare_backing(world):
    job = create(world)
    entries = vector_job._palette(world["store"], pl.get_plan(world["store"], job["id"]))
    light = max(entries, key=lambda e: e["lab"][0])["id"]
    view = add(world, job, backing="rect", padding_mm=2, backing_entry_id=light)
    text = view["texts"][0]
    assert text["shown"]["backing"] and text["backing_srgb"] is not None
    assert "t1" in next(layer for layer in view["layers"] if layer["entry_id"] == light)["texts"]
    plan = pl.get_plan(world["store"], job["id"])
    found = lettering.geometry(world["store"].data_dir, text, plan["size_mm"])
    x0, y0, x1, y1 = found["letters"].bounds
    assert found["backing"].area == pytest.approx((x1 - x0 + 4) * (y1 - y0 + 4) - found["letters"].buffer(0.3).area, rel=0.01)
    bare = colouring(world, job, op="text_set", id="t1", changes={"backing_entry_id": None})
    assert bare["texts"][0]["shown"]["backing"] == "" and bare["texts"][0]["shown"]["cut"]


def test_inscriptions_are_changed_copied_and_undone_with_the_colouring(world):
    job = create(world)
    add(world, job)
    moved = colouring(world, job, op="text_set", id="t1", changes={"x": 35, "rotation": 15, "layout": "arc", "bend": 40})
    assert (moved["texts"][0]["x"], moved["texts"][0]["rotation"], moved["texts"][0]["layout"]) == (35, 15, "arc")
    copied = colouring(world, job, op="text_copy", id="t1")
    assert [t["id"] for t in copied["texts"]] == ["t1", "t2"] and copied["texts"][1]["x"] == 38
    undone = colouring(world, job, op="undo")
    assert [t["id"] for t in undone["texts"]] == ["t1"]
    assert colouring(world, job, op="undo")["texts"][0]["x"] == 30
    assert [t["id"] for t in colouring(world, job, op="redo")["texts"]] == ["t1"]
    gone = colouring(world, job, op="text_delete", id="t1")
    assert gone["texts"] == [] and total_area(gone) == pytest.approx(total_area(job), rel=1e-6)    # the work as it was
    refused(world, job, {"op": "text_set", "id": "t9", "changes": {"x": 1}}, "there is no inscription 't9'")
    refused(world, job, {"op": "text_add", "text": {"height_mm": 0}}, "the letter height (mm) of an inscription must be a number from 0.3 to 500")


def test_an_automatic_recolouring_a_variant_restored_and_a_new_split_keep_the_inscriptions(world):
    job = create(world)
    add(world, job)
    assert [t["id"] for t in colouring(world, job, op="assign", mode="tonality")["texts"]] == ["t1"]
    first = job["variants"][0]["number"]
    assert [t["id"] for t in colouring(world, job, op="restore", variant=first)["texts"]] == ["t1"]
    resplit = world["client"].post(f"/api/vector/{job['id']}/split", json={"n_colors": 4, "detail": "coarse"})
    assert resplit.status_code == 200, resplit.text
    assert [t["id"] for t in resplit.json()["texts"]] == ["t1"]


def test_an_inscription_whose_font_is_gone_or_whose_colour_is_no_longer_measured_blocks_the_file(world):
    job = create(world)
    add(world, job)
    store = world["store"]
    plan = pl.get_plan(store, job["id"])
    plan["colouring"]["texts"][0]["font"] = {"face": "0", "family": "Gone Sans", "style": "Regular"}
    vector_job.cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    view = world["client"].get(f"/api/vector/{job['id']}").json()
    assert view["texts"][0]["problem"] == "the font 'Gone Sans' is not on this computer any more: choose another font"
    assert view["export_blocked"] == "inscription 1 cannot be engraved: the font 'Gone Sans' is not on this computer any more: choose another font"
    assert world["client"].get(f"/api/vector/{job['id']}/export.lbrn2").status_code == 422
    plan["colouring"]["texts"][0]["font"] = face(store)
    plan["colouring"]["texts"][0]["entry_id"] = "e-gone"
    vector_job.cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    view = world["client"].get(f"/api/vector/{job['id']}").json()
    assert view["export_blocked"] == ("inscription 1 cannot be engraved: its titanium colour is no longer measured on this laser, lens and "
                                      "titanium stock: choose another")
    plan["colouring"]["texts"][0].update(entry_id=view["texts"][0]["entry_id"] or vector_job._palette(store, plan)[0]["id"], text="HЖЩ")
    vector_job.cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    view = world["client"].get(f"/api/vector/{job['id']}").json()
    assert view["export_blocked"] == "inscription 1 cannot be engraved: its font has no letters «Щ»: choose a font that has them"


def test_a_photo_zone_under_an_inscription_is_not_engraved_there(world):
    job = create(world)
    red = of_colour(world, job, RED)
    zone = colouring(world, job, op="photo_add", regions=red)["zones"][0]
    box = zone["box"]
    view = add(world, job, text="HH", x=box["x"] + box["width"] / 2, y=box["y"] + 4, height_mm=5)
    plan, project = read_back(world, job)
    found = lettering.geometry(world["store"].data_dir, view["texts"][0], plan["size_mm"])
    image = next(layer for layer in project.layers if layer.index == view["zones"][0]["index"])
    hit = struck(project, plan, image)
    under = lettering.mask(found["cut"].buffer(-0.2), {"x": 0, "y": 0}, 10.0, (hit.shape[1], hit.shape[0])).astype(bool)
    zone_mask = mask_of(world, job, red)
    assert (under & zone_mask).sum() > 50 and not (hit & under).any()                            # transparent under the cut
    assert (hit & zone_mask & ~under).sum() > 0.9 * (zone_mask & ~under).sum() - 400


def test_the_thumbnail_draws_the_inscription(world):
    job = create(world)
    view = add(world, job, text="H", height_mm=20, x=30, y=20)
    answer = world["client"].get(f"/api/vector/{job['id']}/thumb.png")
    assert answer.status_code == 200
    import cv2
    picture = cv2.cvtColor(cv2.imdecode(np.frombuffer(answer.content, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    plan = pl.get_plan(world["store"], job["id"])
    k = picture.shape[1] / plan["size_mm"]["width"]
    stem = lettering.geometry(world["store"].data_dir, view["texts"][0], plan["size_mm"])["letters"].bounds
    x, y = (stem[0] + 0.7) * k, (stem[1] + stem[3]) / 2 * k                                      # inside the left stem of the H
    colour = next(layer["srgb"] for layer in view["layers"] if layer["entry_id"] == view["texts"][0]["entry_id"])
    assert np.abs(picture[int(y), int(x)].astype(int) - colour).max() <= 3
