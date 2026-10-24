"""Inscriptions in a photo work (feature inscriptions-in-works, REQ-005, DEC-003, DEC-004): an inscription is part of the work's state,
made, changed and taken away one step of undo at a time. Its letters are engraved after the picture on a layer of their titanium colour,
the picture is transparent under its cut (the letters widened by the gap, or its backing), and the work's looks show the cut as clean
titanium with the letters in their colour on it. The objects and parts of the picture are found on the whole picture. Measured on the
test font (``font_kit``) and the grey-ramp world with the flat colours of the photo zones' tests."""
import cv2
import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon

import recipes
from test_grey_scales import app_world  # noqa: F401  (the world of the photo zones' tests is made from it)
from test_photo_works import create as make_work
from test_vector_photo_zones import world  # noqa: F401
from titanium_platform import color, engraving_time as et, fonts, lettering, lightburn as lb, photo_modes, photo_state, photo_work
from titanium_platform import model, palette, prediction, prediction_store as ps, row_length, vector_job

K = 10.0                                    # raster pixels per mm the file's picture is laid over


def face(store, family="Test Sans"):
    return fonts.described(next(f for f in fonts.faces(store.data_dir).values() if f["family"] == family and f["style"] == "Regular"))


def texts(world, work, **op) -> dict:
    answer = world["client"].post(f"/api/photo-works/{work['id']}/texts", json=op)
    assert answer.status_code == 200, answer.text
    return answer.json()


def add(world, work, **fields) -> dict:
    return texts(world, work, op="text_add", text={"font": face(world["store"]), "text": "HOH", "height_mm": 8, "x": 30, "y": 15, **fields})


def found(world, work, view, n=0) -> dict:
    plan = photo_work._work(world["store"], work["id"])
    return lettering.geometry(world["store"].data_dir, view["texts"][n], photo_work.size_mm(plan))


def settings(world, work, **changes) -> dict:
    answer = world["client"].post(f"/api/photo-works/{work['id']}/settings", json=changes)
    assert answer.status_code == 200, answer.text
    return answer.json()


def read_file(world, work) -> lb.Project:
    answer = world["client"].get(f"/api/photo-works/{work['id']}/export.lbrn2")
    assert answer.status_code == 200, answer.text
    return lb.parse_bytes(answer.content)


def struck(layer, size) -> np.ndarray:
    """Where the file's picture layer strikes, on a grid of K pixels per mm of the work (its rows top down: the file's y points up)."""
    to_mm = np.array([[1 / K, 0, 0.5 / K], [0, 1 / K, 0.5 / K], [0, 0, 1.0]])
    return photo_modes.struck_mask(layer, to_mm, (round(size["height"] * K), round(size["width"] * K)))[::-1]


def on_grid(shape, size) -> np.ndarray:
    return lettering.mask(shape, {"x": 0.0, "y": 0.0}, K, (round(size["width"] * K), round(size["height"] * K))).astype(bool)


def read_back(layer, size) -> shapely.MultiPolygon:
    """A vector layer's shapes read back from the file, reflected into the work's mm."""
    flip = lambda loop: [(x, size["height"] - y) for x, y in loop]      # noqa: E731
    return shapely.union_all([shapely.make_valid(Polygon(flip(r.polygon), [flip(h) for h in r.holes])) for r in layer.regions])


def rgb_of(answer) -> np.ndarray:
    assert answer.status_code == 200, answer.text
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(answer.content, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def test_an_inscription_takes_the_darkest_colour_and_its_layer_follows_the_picture_with_its_area_and_time(world):
    client = world["client"]
    work = make_work(client)
    view = add(world, work)
    (text,) = view["texts"]
    palette = client.get(f"/api/photo-works/{work['id']}/palette").json()
    darkest = min(palette, key=lambda e: (e["lab"][0], e["id"]))
    assert text["id"] == "t1" and text["entry_id"] == darkest["id"] and text["problem"] is None and text["srgb"] is not None
    assert text["shown"]["letters"].startswith("M") and text["shown"]["cut"]
    (layer,) = view["text_layers"]
    assert (layer["index"], layer["entry_id"], layer["texts"]) == (2, darkest["id"], ["t1"])        # C00 cleans, C01 the picture
    assert layer["area_mm2"] == pytest.approx(found(world, work, view)["letters"].area, rel=1e-3)
    timed = {row["index"]: row for row in view["time"]["layers"]}
    assert timed[2]["seconds"] > 0 and view["time"]["seconds"] == pytest.approx(work["time"]["seconds"] + timed[2]["seconds"])
    assert view["export_blocked"] is None and view["texts_count"] == 1
    assert client.get("/api/photo-works").status_code == 200


@pytest.mark.parametrize("kind", photo_work.KINDS)
def test_the_file_leaves_the_picture_out_under_the_cut_and_engraves_the_letters_after_it(world, kind):
    """inscriptions-in-works REQ-005 c1: the Image layer's picture is transparent under the cut (LightBurn skips it) in grayscale and in
    every dot kind, and the same as without the inscription everywhere else."""
    work = make_work(world["client"])
    if kind != "grayscale":
        settings(world, work, kind=kind)
    size = photo_work.size_mm(photo_work._work(world["store"], work["id"]))
    plain = struck(read_file(world, work).layer(1), size)
    view = add(world, work, gap_mm=0.5)
    shape = found(world, work, view)
    project = read_file(world, work)
    picture, letters = project.layer(1), project.layer(2)
    assert picture.layer_type == "Image" and letters.layer_type != "Image" and picture.burn_order < letters.burn_order
    assert et.of_project(project)["seconds"] == pytest.approx(view["time"]["seconds"], rel=1e-6)    # the time shown is the file's
    read = read_back(letters, size)
    assert shapely.symmetric_difference(read, shape["letters"]).area < 0.005 * shape["letters"].area
    hit = struck(picture, size)
    stored = cv2.imdecode(np.frombuffer(picture.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)[::-1]   # upright
    rows, cols = stored.shape[:2]
    touched = lettering.coverage(shape["cut"], {"x": 0.0, "y": 0.0}, cols / size["width"], (cols, rows), supersample=8) > 0
    assert touched.sum() > 100 and (stored[..., 3][touched] == 0).all()        # every pixel the cut touches is left out, however little
    assert (stored[..., 3][~lettering.hole(shape["cut"], {"x": 0.0, "y": 0.0}, cols / size["width"], (cols, rows)).astype(bool)] == 255).all()
    pixel = size["width"] / cols                                                                  # mm of a pixel of the file's picture
    under, beside = on_grid(shape["cut"].buffer(-pixel), size), on_grid(shape["cut"].buffer(2 * pixel), size)
    assert under.sum() > 300 and not (hit & under).any()                                          # nothing of the picture under the cut
    assert (plain & under).sum() > 0.5 * under.sum()                                              # where the picture struck before
    assert np.mean(hit[~beside] == plain[~beside]) > 0.99                                         # and the same everywhere else


def test_the_looks_draw_the_letters_in_their_colour_and_the_cut_as_clean_titanium(world):
    client = world["client"]
    work = make_work(client)
    view = add(world, work, text="H", height_mm=20, x=30, y=15, gap_mm=2)
    stem = found(world, work, view)["letters"].bounds
    layer = view["text_layers"][0]
    clean = color.lab_to_srgb8(np.asarray([ps.clean_titanium(world["store"])], float))[0]
    size = photo_work.size_mm(photo_work._work(world["store"], work["id"]))
    for address in (f"/api/photo-works/{work['id']}/thumb.png", f"/api/photo-works/{work['id']}/kinds/grayscale.png"):
        look = rgb_of(client.get(address))
        k = look.shape[1] / size["width"]
        y = int((stem[1] + stem[3]) / 2 * k)
        assert np.abs(look[y, int((stem[0] + 0.7) * k)].astype(int) - layer["srgb"]).max() <= 3, address   # inside the left stem
        assert np.abs(look[y, int((stem[0] - 1.0) * k)].astype(int) - clean).max() <= 3, address           # in the gap: clean titanium
    preview = rgb_of(client.get(view["picture"]["preview"]))
    k = (preview.shape[1] - prediction.GAP) / 2 / size["width"]
    y = int((stem[1] + stem[3]) / 2 * k)
    assert (preview[y, int((stem[0] + 0.7) * k)] == 255).all()                                    # the picture beside: left out under the cut


def test_inscriptions_are_undone_copied_with_the_work_and_keep_their_place_when_the_width_changes(world):
    client = world["client"]
    work = make_work(client)
    add(world, work)
    moved = texts(world, work, op="text_set", id="t1", changes={"x": 35, "layout": "arc", "bend": 30})
    assert (moved["texts"][0]["x"], moved["texts"][0]["layout"]) == (35, "arc")
    assert client.post(f"/api/photo-works/{work['id']}/undo").json()["texts"][0]["x"] == 30
    assert client.post(f"/api/photo-works/{work['id']}/redo").json()["texts"][0]["x"] == 35
    copied = client.post(f"/api/photo-works/{work['id']}/copy").json()["id"]
    assert [t["id"] for t in client.get(f"/api/photo-works/{copied}").json()["texts"]] == ["t1"]
    wider = settings(world, work, width_mm=120)
    text = wider["texts"][0]
    assert (text["x"], text["y"], text["height_mm"], text["gap_mm"]) == (70, 30, 16, 0.3)          # a group scaled, its gap as it was
    narrow = client.post(f"/api/photo-works/{work['id']}/undo").json()
    assert (narrow["width_mm"], narrow["texts"][0]["x"]) == (60, 35)
    gone = texts(world, work, op="text_delete", id="t1")
    assert gone["texts"] == [] and gone["text_layers"] == [] and gone["time"]["seconds"] == pytest.approx(work["time"]["seconds"])
    refused = client.post(f"/api/photo-works/{work['id']}/texts", json={"op": "text_set", "id": "t9", "changes": {"x": 1}})
    assert refused.status_code == 422 and refused.json()["error"] == "there is no inscription 't9'"


def test_a_new_inscription_takes_the_font_of_the_one_changed_last_also_after_a_reload(world):
    """inscriptions-in-works REQ-003: the photo work's undo tells which inscription was changed last."""
    work = make_work(world["client"])
    add(world, work, font=face(world["store"], "Other Serif"))
    add(world, work, x=20)                                                                       # t2 in Test Sans, the newest
    texts(world, work, op="text_set", id="t1", changes={"x": 25})                                # t1 changed last
    settings(world, work, width_mm=60)                                                           # a step that changes no inscription
    fresh = texts(world, work, op="text_add")                                                    # no font sent: the screen was reloaded
    assert fresh["texts"][-1]["font"]["family"] == "Other Serif"


def test_an_inscription_that_cannot_be_engraved_says_why_and_refuses_the_file(world):
    client, store = world["client"], world["store"]
    work = make_work(client)
    add(world, work)
    plan = photo_work._work(store, work["id"])
    plan["texts"][0]["font"] = {"face": "0", "family": "Gone Sans", "style": "Regular"}
    photo_work._save(store, plan, plan["id"])
    view = client.get(f"/api/photo-works/{work['id']}").json()
    message = "inscription 1 cannot be engraved: the font 'Gone Sans' is not on this computer any more: choose another font"
    assert view["texts"][0]["problem"] and view["export_blocked"] == message
    answer = client.get(f"/api/photo-works/{work['id']}/export.lbrn2")
    assert answer.status_code == 422 and answer.json()["error"] == message
    plan["texts"][0].update(font=face(store), entry_id="e-gone")
    photo_work._save(store, plan, plan["id"])
    view = client.get(f"/api/photo-works/{work['id']}").json()
    assert view["export_blocked"] == ("inscription 1 cannot be engraved: its titanium colour is no longer measured on this laser, lens and "
                                      "titanium stock: choose another")


def test_the_objects_of_the_picture_are_found_on_the_whole_picture_not_the_one_cut_by_an_inscription(world, monkeypatch):
    work = make_work(world["client"])
    add(world, work, height_mm=12)
    seen = []
    monkeypatch.setattr(photo_state.ob, "find", lambda upload: seen.append(float(upload["alpha_full"].min())) or
                        {"objects": [], "faces": [], "notes": []})
    plan = {**photo_work._work(world["store"], work["id"]), "by_colour": True, "colour_choice": "objects", "colouring": {"o1": {"power": 10}}}
    item = photo_work._item(world["store"], plan)
    assert seen == [1.0] and float(item["alpha"].min()) == 0.0                                    # found on the whole, engraved with the cut


def palette_of(world, work) -> list[dict]:
    return photo_work._palette(world["store"], photo_work._work(world["store"], work["id"]))


def test_the_file_keeps_the_cleaning_and_the_picture_and_lays_the_backing_and_the_letters_after_them_with_their_full_recipes(world, monkeypatch):
    """inscriptions-in-works REQ-005 c2: the cleaning stays on C00 and the picture on C01 as without the inscription; the backing and the
    letters follow, on a layer of each recipe (the lightest first), with every setting of their recipe (here one with cross-hatch, angles,
    two passes and a sub-layer), laid where the screen and the look draw them. Letters that overlap are one shape there (REQ-002 c6)."""
    client, store, passport = world["client"], world["store"], world["laser"]["passport"]
    work = make_work(client)
    plain = read_file(world, work)
    entries = palette_of(world, work)
    light, dark = max(entries, key=lambda e: e["lab"][0]), min(entries, key=lambda e: e["lab"][0])
    full = recipes.recipes(passport)["Gold fill"]
    stored = vector_job._recipe
    monkeypatch.setattr(vector_job, "_recipe", lambda store_, plan_, entry: full if entry["id"] == dark["id"] else stored(store_, plan_, entry))
    view = add(world, work, text="HH O", spacing_mm=-1.5, height_mm=10, x=25, y=20, backing="rect", padding_mm=2, backing_entry_id=light["id"])
    text, shape = view["texts"][0], found(world, work, view)
    size = photo_work.size_mm(photo_work._work(store, work["id"]))
    project = read_file(world, work)
    assert [(layer["index"], layer["entry_id"]) for layer in view["text_layers"]] == [(2, light["id"]), (3, dark["id"])]
    assert [(layer.index, layer.name, layer.layer_type) for layer in project.layers] == [
        (0, plain.layer(0).name, "Scan"), (1, "C01", "Image"), *[(layer["index"], layer["name"], "Scan") for layer in view["text_layers"]]]
    for index in (0, 1):                                                                         # the cleaning and the picture as they were
        assert recipes.parameters(project.layer(index), passport) == recipes.parameters(plain.layer(index), passport)
    assert [r.as_dict() for r in project.layer(0).regions] == [r.as_dict() for r in plain.layer(0).regions]
    assert [r.as_dict() for r in project.layer(1).regions] == [r.as_dict() for r in plain.layer(1).regions]
    backing, letters = project.layer(2), project.layer(3)
    assert model.parameters_key(recipes.parameters(letters, passport)) == model.parameters_key(full)          # every setting of the recipe
    assert (letters.cross_hatch, letters.passes, letters.scan_angle) == (True, 2, 45.0)
    own = stored(store, photo_work._work(store, work["id"]), light)
    assert {k: recipes.parameters(backing, passport)[k] for k in own} == own
    # laid where the screen draws them, as closed Path shapes
    assert text["shown"]["letters"] == lettering.svg_d(shape["letters"]) and text["shown"]["backing"] == lettering.svg_d(shape["backing"])
    for layer, part in ((backing, shape["backing"]), (letters, shape["letters"])):
        assert layer.regions and all(r.kind == "path" and r.closed for r in layer.regions)
        assert shapely.symmetric_difference(read_back(layer, size), part).area < 0.005 * part.area
    # «HH» overlap: one shape, and no shape of the layer over another
    assert len(shape["letters"].geoms) == 2 and len(letters.regions) == 2
    assert sum(Polygon(r.polygon, r.holes).area for r in letters.regions) == pytest.approx(read_back(letters, size).area, rel=1e-6)
    # and where the look draws them: the letters in their colour, the backing in its own beside them
    look = rgb_of(client.get(f"/api/photo-works/{work['id']}/thumb.png"))
    k = look.shape[1] / size["width"]
    x0, y0, x1, y1 = shape["letters"].bounds
    y = int((y0 + y1) / 2 * k)
    assert np.abs(look[y, int((x0 + 0.7) * k)].astype(int) - text["srgb"]).max() <= 3                   # in the first stem
    assert np.abs(look[y, int((x0 - 1.2) * k)].astype(int) - text["backing_srgb"]).max() <= 3           # on the backing beside it


def test_the_letters_are_seen_in_their_recipes_colour_at_their_size_and_as_large_as_they_are(world, monkeypatch):
    """inscriptions-in-works REQ-005 c3: the predicted looks (in grayscale and in a dot kind) and the list's thumbnail show the cut as clean
    titanium and the letters in the colour their recipe takes at their size (the length of their rows, DEC-107: here a recipe measured
    at two sizes), as large as they are."""
    client, store = world["client"], world["store"]
    work = make_work(client)
    real = photo_work._palette
    dark = min(palette_of(world, work), key=lambda e: e["lab"][0])
    sizes = [{"row_mm": 1.0, "lab": [75.0, 5.0, 40.0]}, {"row_mm": 30.0, "lab": [40.0, 30.0, -40.0]}]
    monkeypatch.setattr(photo_work, "_palette", lambda store_, plan: [{**e, "sizes": sizes} if e["id"] == dark["id"] else e for e in real(store_, plan)])
    clean = color.lab_to_srgb8(np.asarray([ps.clean_titanium(store)], float))[0]
    size = photo_work.size_mm(photo_work._work(store, work["id"]))
    add(world, work, text="H", height_mm=8, x=20, y=15, gap_mm=1.5)
    colours = []
    for height in (8, 24):
        view = texts(world, work, op="text_set", id="t1", changes={"height_mm": height})
        text, shape = view["texts"][0], found(world, work, view)
        row = row_length.of_shapes(lettering.shapes(shape["letters"]), 0.0)
        expected = palette.at_size({**dark, "sizes": sizes}, row)["srgb"]
        assert text["srgb"] == expected == view["text_layers"][0]["srgb"], height                        # the colour at their size
        colours.append(expected)
        x0, y0, x1, y1 = shape["letters"].bounds
        for address in ("thumb.png", "kinds/grayscale.png", "kinds/jarvis.png"):
            look = rgb_of(client.get(f"/api/photo-works/{work['id']}/{address}"))
            rows, cols = look.shape[:2]
            k = cols / size["width"]
            y = int((y0 + y1) / 2 * k)
            assert np.abs(look[y, int((x0 + 0.08 * (x1 - x0)) * k)].astype(int) - expected).max() <= 3, (height, address)   # in a stem
            assert np.abs(look[y, int((x0 - 0.75) * k)].astype(int) - clean).max() <= 3, (height, address)                  # the gap: clean
            cut = lettering.mask(shape["cut"], {"x": 0.0, "y": 0.0}, k, (cols, rows)).astype(bool)
            ys, xs = np.nonzero(cut & (np.abs(look.astype(int) - expected).max(axis=2) <= 8))
            assert (xs.min() / k, ys.min() / k, (xs.max() + 1) / k, (ys.max() + 1) / k) == pytest.approx((x0, y0, x1, y1), abs=1.5 / k), (height, address)
    assert colours[0] != colours[1] and dark["srgb"] not in colours                                      # another size, another colour


def test_the_time_adds_the_fill_time_of_the_letters_and_the_backing_to_the_pictures(world):
    """inscriptions-in-works REQ-005 c4: the work's time is the picture's (its cleaning and its Image layer, as without the inscription) and
    the fill time of the letters' and the backing's layers, each as the file is timed; the list says the same."""
    client = world["client"]
    work = make_work(client)
    plain = {row["index"]: row["seconds"] for row in work["time"]["layers"]}
    light = max(palette_of(world, work), key=lambda e: e["lab"][0])["id"]
    view = add(world, work, backing="rect", padding_mm=2, backing_entry_id=light)
    timed = {row["index"]: row["seconds"] for row in view["time"]["layers"]}
    assert {i: timed[i] for i in plain} == plain                                                   # the picture's time as it was
    added = [layer["index"] for layer in view["text_layers"]]
    assert added == [2, 3] and set(timed) == set(plain) | set(added) and all(timed[i] > 0 for i in added)
    assert view["time"]["seconds"] == pytest.approx(work["time"]["seconds"] + timed[2] + timed[3])
    filed = {row["index"]: row["seconds"] for row in et.of_project(read_file(world, work))["layers"]}
    assert all(timed[i] == pytest.approx(filed[i], rel=1e-5) for i in timed)                       # each layer as the file is timed
    listed = next(w for w in client.get("/api/photo-works").json() if w["id"] == work["id"])
    assert listed["time"]["seconds"] == pytest.approx(view["time"]["seconds"])
    smaller = texts(world, work, op="text_set", id="t1", changes={"height_mm": 4, "padding_mm": 1})
    assert smaller["time"]["seconds"] < view["time"]["seconds"]                                     # less to fill, less time


def photo_outputs(world, work) -> dict:
    """What a photo work shows, times and writes: its view (time, inscriptions, picture), its LightBurn file and its pictures drawn afresh
    (not taken from the cache): the preview, the list's thumbnail and its looks in grayscale and in a dot kind."""
    store, plan_id = world["store"], work["id"]
    view = world["client"].get(f"/api/photo-works/{plan_id}").json()
    return {"view": {k: view[k] for k in ("time", "texts", "text_layers", "export_blocked", "texts_count", "picture")},
            "file": world["client"].get(f"/api/photo-works/{plan_id}/export.lbrn2").content,
            "preview": photo_work.preview(store, plan_id).draw(), "thumbnail": photo_work.thumbnail(store, plan_id).draw(),
            "grayscale": photo_work.kind_picture(store, plan_id, "grayscale").draw(),
            "jarvis": photo_work.kind_picture(store, plan_id, "jarvis").draw()}


def test_a_work_without_inscriptions_writes_draws_and_times_as_without_the_inscriptions_code(world, monkeypatch):
    """inscriptions-in-works REQ-005 c5 and REQ-003 c6 (a photo work): a work without inscriptions writes the same file, byte for byte, and
    draws and times the same as with the inscriptions' part taken out (no picture cut, no layers, nothing painted); an inscription added
    and taken away again leaves nothing behind."""
    work = make_work(world["client"])
    plain = photo_outputs(world, work)
    assert plain["view"]["texts"] == [] and plain["view"]["text_layers"] == [] and plain["view"]["export_blocked"] is None
    with monkeypatch.context() as patch:
        patch.setattr(photo_work, "_text_state", lambda store, plan: None)
        patch.setattr(photo_work, "_cut_upload", lambda store, plan: photo_work._upload(plan))
        patch.setattr(photo_work, "_holed", lambda picture, texts, width_mm: picture)
        patch.setattr(photo_work, "_paint", lambda store, plan, texts: [])
        patch.setattr(lettering, "inscribed", None)                                             # nothing of the inscriptions runs
        without = photo_outputs(world, work)
    assert without == plain
    add(world, work)
    assert photo_outputs(world, work)["file"] != plain["file"]
    texts(world, work, op="text_delete", id="t1")
    assert photo_outputs(world, work) == plain
