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

from test_grey_scales import app_world  # noqa: F401  (the world of the photo zones' tests is made from it)
from test_photo_works import create as make_work
from test_vector_photo_zones import world  # noqa: F401
from titanium_platform import color, engraving_time as et, fonts, lettering, lightburn as lb, photo_modes, photo_state, photo_work
from titanium_platform import prediction, prediction_store as ps

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


@pytest.mark.parametrize("kind", ["grayscale", "jarvis"])
def test_the_file_leaves_the_picture_out_under_the_cut_and_engraves_the_letters_after_it(world, kind):
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
