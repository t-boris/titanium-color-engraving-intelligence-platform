"""Inscriptions in a vector work (feature inscriptions-in-works, REQ-003, REQ-004, DEC-003): an inscription is an object of the work's
colouring, made, changed and taken away by the colour editor's operations (one step of undo each). Its letters are engraved in their
titanium colour on the layer of that colour; the regions under its cut (the letters widened by the gap, or its backing) give that part up,
in the area, the time and the file; a photo zone under it is transparent there; the file's letters read back have the area the work
promised. Measured on the test font (``font_kit``)."""
import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon

import recipes
from test_grey_scales import app_world  # noqa: F401  (the world of the photo zones' tests is made from it)
from test_vector_photo_zones import colouring, create, mask_of, of_colour, refused, struck, world  # noqa: F401
from test_vector_work import RED
from titanium_platform import fonts, lettering, lightburn as lb, plans as pl, row_length, vector_job


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


def test_a_new_inscription_takes_the_font_of_the_one_changed_last_also_after_a_reload(world):
    job = create(world)
    add(world, job, font=face(world["store"], "Other Serif"))
    add(world, job)                                                                              # t2 in Test Sans, the newest
    colouring(world, job, op="text_set", id="t1", changes={"x": 20})                             # t1 changed last
    colouring(world, job, op="assign", mode="tonality")                                          # a step that changes no inscription
    fresh = colouring(world, job, op="text_add")                                                 # no font sent: the screen was reloaded
    assert fresh["texts"][-1]["font"]["family"] == "Other Serif"


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


def view_of(world, job) -> dict:
    return world["client"].get(f"/api/vector/{job['id']}").json()


def seconds(view) -> dict[int, float]:
    return {row["index"]: row["seconds"] for row in view["time"]["layers"]}


def test_an_inscription_in_a_colour_no_region_has_opens_a_layer_of_its_own_within_the_layer_cap(world, monkeypatch):
    """inscriptions-in-works REQ-004 c2: the letters of a recipe no region of the work has go to a new layer of that recipe, which counts
    against the layers the file holds; in a recipe of the regions they share its layer; the backing likewise. The layers' shapes are
    closed Paths, written with the recipe's settings as its regions' layer is."""
    job = create(world)
    darkest = lettering.darkest(vector_job._palette(world["store"], pl.get_plan(world["store"], job["id"])))
    colour = min((c for c in view_of(world, job)["colours"] if c["entry_id"] != darkest), key=lambda c: c["pixels"])
    entry = colour["entry_id"]
    passport = world["laser"]["passport"]
    _, project = read_back(world, job)                                                  # how the file writes that recipe for its regions
    of_regions = next(layer for layer in project.layers if layer.index == next(l["index"] for l in view_of(world, job)["layers"] if l["entry_id"] == entry))
    alone = colouring(world, job, op="exclude_colour", colour=colour["index"])         # no region has its recipe any more
    assert entry not in {layer["entry_id"] for layer in alone["layers"]}
    monkeypatch.setattr(vector_job, "photo_cap", lambda markers: len(alone["layers"]))    # the file holds just the layers there are
    assert alone["export_blocked"] is None
    view = add(world, job, entry_id=entry)
    (opened,) = [layer for layer in view["layers"] if layer["entry_id"] == entry]
    assert opened["texts"] == ["t1"] and opened["region_count"] == 0 and len(view["layers"]) == len(alone["layers"]) + 1
    n = len(view["layers"])
    assert view["export_blocked"] == f"{n} different recipes need more LightBurn layers than the {n - 1} available"
    assert world["client"].get(f"/api/vector/{job['id']}/export.lbrn2").status_code == 422
    monkeypatch.setattr(vector_job, "photo_cap", lambda markers: n)                       # room for it: the letters on a layer of their own
    view = view_of(world, job)
    assert view["export_blocked"] is None
    plan, project = read_back(world, job)
    found = lettering.geometry(world["store"].data_dir, view["texts"][0], plan["size_mm"])
    layer = next(layer for layer in project.layers if layer.index == opened["index"])
    recipe = vector_job._recipe(world["store"], next(e for e in vector_job._palette(world["store"], plan) if e["id"] == entry))
    assert layer.name == opened["name"] and layer.layer_type == "Scan"
    assert {k: recipes.parameters(layer, passport)[k] for k in recipe} == recipe                         # the recipe's settings
    assert recipes.parameters(layer, passport) == recipes.parameters(of_regions, passport)                 # written as for its regions
    assert layer.regions and all(r.kind == "path" and r.closed for r in layer.regions)       # closed Path shapes
    assert shapely.symmetric_difference(shapes_of(plan, layer), found["letters"]).area < 0.01 * found["letters"].area   # its letters only
    shared = colouring(world, job, op="text_set", id="t1", changes={"entry_id": darkest})    # a recipe of regions: their layer
    assert len(shared["layers"]) == len(alone["layers"]) and "t1" in next(l for l in shared["layers"] if l["entry_id"] == darkest)["texts"]
    monkeypatch.setattr(vector_job, "photo_cap", lambda markers: len(alone["layers"]))
    assert view_of(world, job)["export_blocked"] is None
    # the backing likewise: in the colour no region has, on a new layer of that recipe, which needs room within the cap
    backed = colouring(world, job, op="text_set", id="t1", changes={"backing": "rect", "padding_mm": 2, "backing_entry_id": entry})
    (own,) = [layer for layer in backed["layers"] if layer["entry_id"] == entry]
    assert own["texts"] == ["t1"] and own["region_count"] == 0 and len(backed["layers"]) == n
    assert backed["export_blocked"] == f"{n} different recipes need more LightBurn layers than the {n - 1} available"
    monkeypatch.setattr(vector_job, "photo_cap", lambda markers: n)
    plan, project = read_back(world, job)
    shape = lettering.geometry(world["store"].data_dir, backed["texts"][0], plan["size_mm"])
    layer = next(layer for layer in project.layers if layer.index == own["index"])
    assert recipes.parameters(layer, passport) == recipes.parameters(of_regions, passport)
    assert layer.regions and all(r.kind == "path" and r.closed for r in layer.regions)
    assert shapely.symmetric_difference(shapes_of(plan, layer), shape["backing"]).area < 0.01 * shape["backing"].area   # the backing only


def test_the_time_leaves_out_the_cut_part_of_the_regions_and_the_row_length_of_a_layer_includes_its_letters(world):
    """inscriptions-in-works REQ-004 c4: each layer's area and time are of what it engraves: its regions less what the inscription's cut
    takes from them, plus its letters; the length of the scan rows its colour is predicted at counts the letters (as the file is scanned)."""
    job = create(world)
    before = view_of(world, job)
    regions = {layer["index"]: layer["region_ids"] for layer in pl.get_plan(world["store"], job["id"])["layers"]}
    after = add(world, job, text="HHHHHH", height_mm=10, gap_mm=0.5)
    text = after["texts"][0]
    plan = pl.get_plan(world["store"], job["id"])
    found = lettering.geometry(world["store"].data_dir, text, plan["size_mm"])
    shapes = vector_job._region_shapes(plan)
    was, now = {layer["index"]: layer for layer in before["layers"]}, {layer["index"]: layer for layer in after["layers"]}
    assert set(was) == set(now)
    letters_at = next(i for i, layer in now.items() if layer["entry_id"] == text["entry_id"])
    cut_off = 0.0
    for index, layer in was.items():
        under = sum(shapely.intersection(shapes[r], found["cut"]).area for r in regions[index])
        cut_off += under
        area = layer["area_mm2"] - under + (found["letters"].area if index == letters_at else 0.0)
        assert now[index]["area_mm2"] == pytest.approx(area, rel=0.01, abs=0.05), index
        assert seconds(after)[index] == pytest.approx(seconds(before)[index] * area / layer["area_mm2"], rel=0.01, abs=0.01), index
    assert cut_off > 20                                                                          # the cut took a good part of the regions
    assert after["time"]["seconds"] == pytest.approx(sum(seconds(after).values()))
    # the row length: the letters' layer read back from the file as LightBurn scans it, with and without its letters
    _, project = read_back(world, job)
    layer = next(layer for layer in project.layers if layer.index == letters_at)
    dx, dy = pl.export_offset(plan)
    letter = lambda r: found["letters"].buffer(0.01).contains(Polygon(np.asarray(r.polygon) - [dx, dy]))     # noqa: E731
    with_letters = row_length.of_layer(layer)
    without = row_length.of_regions([r for r in layer.regions if not letter(r)], layer.scan_angle or 0.0)
    assert any(letter(r) for r in layer.regions) and with_letters - without > 3                  # the letters lengthen its rows
    assert now[letters_at]["size"]["row_mm"] == pytest.approx(with_letters, abs=0.06)
    assert was[letters_at]["size"]["row_mm"] == pytest.approx(without, abs=0.6)                    # before them: its regions' (the cut aside)


def outputs(world, job) -> dict:
    """What a work shows, times and writes: its view's colours, layers, totals and time, its LightBurn file, its list picture (drawn
    afresh, not taken from the cache) and the editor's picture of its regions."""
    client = world["client"]
    view = view_of(world, job)
    keep = ("colours", "entries", "layers", "totals", "time", "outside", "missing", "zones", "texts", "export_blocked", "layer_cap")
    return {"view": {k: view[k] for k in keep}, "file": client.get(f"/api/vector/{job['id']}/export.lbrn2").content,
            "thumbnail": vector_job.thumbnail(world["store"], job["id"]).draw(),
            "regions": client.get(f"/api/vector/{job['id']}/split.svg").content}


def test_a_work_without_inscriptions_draws_times_and_writes_as_without_the_inscriptions_code(world, monkeypatch):
    """inscriptions-in-works REQ-003 c6: a vector work without inscriptions shows, times and writes exactly what it does with the
    inscriptions' part of the work taken out (nothing laid out, cut or drawn: the work before inscriptions), byte for byte; an inscription
    added and taken away again leaves nothing behind."""
    job = create(world)
    plain = outputs(world, job)
    assert plain["view"]["texts"] == [] and plain["view"]["export_blocked"] is None
    with monkeypatch.context() as patch:
        patch.setattr(vector_job, "_inscribed", lambda store, plan, entries: None)
        patch.setattr(vector_job, "_text_paint", lambda store, plan: [])
        patch.setattr(lettering, "inscribed", None)                                             # nothing of the inscriptions runs
        without = outputs(world, job)
    assert without == plain
    assert add(world, job)["texts"] and outputs(world, job) != plain
    colouring(world, job, op="text_delete", id="t1")
    assert outputs(world, job) == plain


def test_an_inscription_beyond_the_edge_says_so_and_the_file_engraves_it_up_to_the_edge(world):
    """inscriptions-in-works REQ-004 c5: an inscription that runs off the work says it is cut off there, and the file's letters end at the
    work's edge (the file is written: only a gone font or an unmeasured colour blocks it)."""
    job = create(world)
    width = pl.get_plan(world["store"], job["id"])["size_mm"]["width"]
    view = add(world, job, text="HHHHHH", x=width - 8)
    text = view["texts"][0]
    assert text["shown"]["clipped"] is True and text["problem"] is None and view["export_blocked"] is None
    plan, project = read_back(world, job)
    clipped = lettering.geometry(world["store"].data_dir, text, plan["size_mm"])
    whole = lettering.geometry(world["store"].data_dir, text, None)                              # the same inscription, not cut off
    assert whole["letters"].bounds[2] > width + 5 and clipped["letters"].bounds[2] <= width + 1e-6
    index = next(layer["index"] for layer in view["layers"] if layer["entry_id"] == text["entry_id"])
    engraved = shapes_of(plan, next(layer for layer in project.layers if layer.index == index))
    assert engraved.bounds[2] <= width + 0.01
    letters = engraved.intersection(whole["cut"])                                                 # under the cut the layer has its letters only
    assert shapely.symmetric_difference(letters, clipped["letters"]).area < 0.01 * clipped["letters"].area
    assert clipped["letters"].area < 0.8 * whole["letters"].area
