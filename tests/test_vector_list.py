"""Saved vector works (feature vector-detail-and-colour-control, 0.9.0): the list of them with a thumbnail of each, the copy of a work to
try something else on, and the AI colouring on a computer whose environment lacks the language model's library."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from test_ai_colouring import ai_op, model, refused as ai_refused, state_of    # noqa: F401  (the fake client of the model)
from test_vector_work import PAPER, RED, by_rgb, colouring, create, job, picture, work    # noqa: F401  (fixtures)
from titanium_platform import conversion as cv, plans as pl, render_cache as rc, research, vector_job

LIST_KEYS = {"id", "name", "status", "created_at", "updated_at", "strategy", "width_mm", "height_mm", "algorithm", "n_colours", "regions", "layers",
             "mode", "ai_style", "ai_text", "variants", "smoothing_mm", "version"}


def works(c) -> list[dict]:
    r = c["client"].get("/api/vector")
    assert r.status_code == 200, r.text
    return r.json()


def traced(c, name="Old", strategy="fill") -> dict:
    r = c["client"].post("/api/vector", data={"device_id": c["w"]["setup"][0], "lens_id": c["w"]["setup"][1], "material_id": c["ti"], "name": name,
                                              "width_mm": 50, "strategy": strategy, "threshold": 8}, files={"image": ("a.png", picture(), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()


def thumb(c, j):
    return c["client"].get(f"/api/vector/{j['id']}/thumb.png")


def pixels(response) -> np.ndarray:
    """A thumbnail as RGB pixels."""
    assert response.status_code == 200 and response.headers["content-type"] == "image/png", response.text[:200]
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def share(img: np.ndarray, rgb) -> float:
    """The part of a picture that is exactly one colour."""
    return float((img == np.array(rgb, np.uint8)).all(axis=2).mean())


def stored(c, j) -> dict:
    return pl.get_plan(c["store"], j["id"])


def copy_of(c, j, **body) -> dict:
    """The view of a copy of a work, made with the name in ``body`` (or none: the name is made)."""
    r = c["client"].post(f"/api/vector/{j['id']}/copy", json=body or None)
    assert r.status_code == 201, r.text
    return c["client"].get(f"/api/vector/{r.json()['id']}").json()


# -- the list --------------------------------------------------------------------------------------------------------------------------
def test_the_list_shows_every_vector_work_newest_first_and_nothing_else(work, job):
    c, first = work, job
    second = create(c, name="Second", n_colors=4, algorithm="tonal").json()
    old = traced(c, "Traced")
    cv.save_plan(c["store"], None, name="A plate", mode=pl.MODE_PLATE, status="Draft", device_id=c["w"]["setup"][0], lens_id=c["w"]["setup"][1],
                 markers=False, identifier="PLATE-1", band_count=None, data={})
    listed = works(c)
    assert [w["id"] for w in listed] == [old["id"], second["id"], first["id"]]                           # newest first, the plate is not a work
    assert all(set(w) == LIST_KEYS for w in listed)
    portrait, tonal, trace = listed[2], listed[1], listed[0]
    assert (portrait["name"], portrait["strategy"], portrait["algorithm"], portrait["width_mm"], portrait["height_mm"]) == ("Portrait", "photo", "slic", 60, 45)
    assert portrait["n_colours"] == len(first["colours"]) and portrait["regions"] == first["document"]["regions"] and portrait["layers"] == len(first["layers"])
    assert (portrait["mode"], portrait["variants"], portrait["version"], portrait["smoothing_mm"]) == ("closest", 1, 1, 0.5)
    assert (portrait["ai_style"], portrait["ai_text"], portrait["status"]) == (None, None, first["status"])
    assert isinstance(portrait["created_at"], str) and isinstance(portrait["updated_at"], str)
    assert tonal["algorithm"] == "tonal" and tonal["n_colours"] == len(second["colours"])
    assert (trace["strategy"], trace["algorithm"], trace["smoothing_mm"], trace["mode"], trace["ai_style"]) == ("trace", None, None, None, None)
    assert trace["regions"] == len(old["regions"]) and trace["n_colours"] >= 1 and trace["width_mm"] == 50 and trace["version"] == 1


def test_a_deleted_work_leaves_the_list_and_its_pictures_and_copies_are_not_found(work, job):
    c, j = work, job
    assert thumb(c, j).status_code == 200
    folder = rc.pair_dir(c["store"], f"vector-{j['id']}")
    assert folder.is_dir()
    assert c["client"].delete(f"/api/plans/{j['id']}").status_code == 204
    assert works(c) == [] and not folder.exists()
    assert thumb(c, j).status_code == 404 and c["client"].post(f"/api/vector/{j['id']}/copy").status_code == 404
    assert thumb(c, {"id": 9999}).status_code == 404 and c["client"].post("/api/vector/9999/copy", json={"name": "x"}).status_code == 404


def test_the_list_follows_the_work_and_never_opens_a_document_for_it(work, job, monkeypatch):
    c, j = work, job
    before = works(c)[0]
    colouring(c, j, op="assign", mode="random")
    after = works(c)[0]
    history = c["client"].get(f"/api/vector/{j['id']}").json()["history"]
    assert after["variants"] == before["variants"] + 1 and after["mode"] == "random" and after["updated_at"] == history[-1]["at"] >= before["updated_at"]
    assert c["client"].post(f"/api/vector/{j['id']}/smoothing", json={"mm": 1.5}).status_code == 200
    assert works(c)[0]["smoothing_mm"] == 1.5
    monkeypatch.setattr(vector_job, "_document", lambda plan: pytest.fail("the list opened a document"))
    assert works(c)[0]["regions"] == j["document"]["regions"]


def test_a_work_saved_before_its_plan_kept_the_counts_is_read_once_from_its_document(work, job):
    c, j = work, job
    assert "counts" in stored(c, j)
    vector_job._MEMO.clear()
    plan = stored(c, j)
    data = {k: v for k, v in plan.items() if k not in vector_job.PLAN_COLUMNS and k != "counts"}
    c["store"].execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), j["id"]))
    assert "counts" not in stored(c, j)
    item = works(c)[0]
    assert (item["n_colours"], item["regions"]) == (len(j["colours"]), j["document"]["regions"])
    assert c["client"].get(f"/api/vector/{j['id']}").json().keys() == job.keys()                        # the counts are not part of the work's view


def test_the_ai_style_and_the_operators_text_reach_the_list_until_another_mode_colours(work, job, model):
    c, j = work, job
    model()
    assert ai_op(c, j, style="custom", text="как витраж").status_code == 200
    item = works(c)[0]
    assert (item["mode"], item["ai_style"], item["ai_text"], item["variants"]) == ("ai", "custom", "как витраж", 2)
    assert ai_op(c, j, style="cubism").status_code == 200
    assert (works(c)[0]["ai_style"], works(c)[0]["ai_text"]) == ("cubism", None)
    colouring(c, j, op="assign", mode="closest")
    item = works(c)[0]
    assert (item["mode"], item["ai_style"], item["ai_text"], item["variants"]) == ("closest", None, None, 4)


# -- the thumbnail ---------------------------------------------------------------------------------------------------------------------
def test_the_thumbnail_is_a_small_png_in_the_titanium_colours_with_the_holes_open(work, job):
    c, j = work, job
    r = thumb(c, j)
    img = pixels(r)
    assert max(img.shape[:2]) == 360 and img.shape[:2] == (270, 360)                                    # 60 x 45 mm, the longer side 360 px
    assert r.headers["etag"].startswith('"') and r.headers["cache-control"] == "private, max-age=0, must-revalidate"
    for layer in j["layers"]:                                                                          # every layer of the file is on the picture
        assert share(img, layer["srgb"]) > 0.005, layer["srgb"]
    sources = {tuple(col["srgb"]) for col in j["colours"]}
    assert not any(share(img, rgb) > 0.001 for rgb in sources - {tuple(layer["srgb"]) for layer in j["layers"]})   # not the source colours
    paper = next(col for col in j["colours"] if tuple(col["srgb"]) == PAPER)
    ring = next(col for col in j["colours"] if tuple(col["srgb"]) == RED)
    inside = tuple(img[round(70 / 180 * 270), round(60 / 240 * 360)])                                   # the middle of the red ring: paper shows through
    assert inside == tuple(next(layer["srgb"] for layer in j["layers"] if layer["entry_id"] == paper["entry_id"]))
    assert inside != tuple(next(layer["srgb"] for layer in j["layers"] if layer["entry_id"] == ring["entry_id"]))


def test_an_unchanged_thumbnail_is_not_drawn_or_sent_again_and_a_changed_one_is(work, job, monkeypatch):
    c, j = work, job
    first = thumb(c, j)
    etag = first.headers["etag"]
    drawn = []
    monkeypatch.setattr(vector_job, "_draw_thumbnail", lambda plan, painted: drawn.append(1) or b"")
    again = c["client"].get(f"/api/vector/{j['id']}/thumb.png", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b"" and drawn == []
    assert thumb(c, j).content == first.content and drawn == []                                         # from the cache
    monkeypatch.undo()
    colouring(c, j, op="assign", mode="random")
    recoloured = thumb(c, j)
    assert recoloured.headers["etag"] != etag and recoloured.content != first.content
    assert c["client"].post(f"/api/vector/{j['id']}/smoothing", json={"mm": 2}).status_code == 200
    assert thumb(c, j).headers["etag"] not in (etag, recoloured.headers["etag"])
    assert colouring(c, j, op="undo")["colouring"]["mode"] == "closest" and thumb(c, j).headers["etag"] not in (etag, recoloured.headers["etag"])


def test_a_region_left_out_of_the_file_is_not_drawn_and_a_work_with_nothing_left_is_all_background(work, job):
    c, j = work, job
    for col in j["colours"]:
        j = colouring(c, j, op="exclude_colour", colour=col["index"])
    assert j["layers"] == []
    img = pixels(thumb(c, j))
    assert (img == np.array(vector_job.THUMB_BACKGROUND, np.uint8)).all()


def test_a_traced_work_has_a_thumbnail_in_its_region_colours(work):
    c = work
    old = traced(c, "Flat", "fill")
    img = pixels(thumb(c, old))
    assert max(img.shape[:2]) == 360 and share(img, vector_job.THUMB_BACKGROUND) < 1
    colour = old["regions"][0]
    assert any(share(img, region["srgb"]) > 0 for region in json.loads(Path(stored(c, old)["document_path"]).read_text(encoding="utf-8"))["regions"]), colour


# -- the copy ----------------------------------------------------------------------------------------------------------------------------
def test_a_copy_is_a_work_of_its_own_with_the_same_picture_colouring_and_variants(work, job):
    c, j = work, job
    colouring(c, j, op="assign", mode="random")
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, RED)["index"], entry_id=by_rgb(j, PAPER)["entry_id"])        # a hand choice
    assert c["client"].post(f"/api/vector/{j['id']}/smoothing", json={"mm": 1.25}).status_code == 200
    assert c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").status_code == 200                                  # the original has an exported file
    original = c["client"].get(f"/api/vector/{j['id']}").json()
    assert original["exports"] and original["undo"] >= 2
    r = c["client"].post(f"/api/vector/{j['id']}/copy")                                                                # no body: the name is made
    assert r.status_code == 201 and set(r.json()) == {"id"} and r.json()["id"] != j["id"]
    copy = c["client"].get(f"/api/vector/{r.json()['id']}").json()
    assert copy["name"] == "Portrait (копия)" and [w["id"] for w in works(c)] == [copy["id"], j["id"]]
    for same in ("colours", "colouring", "settings", "layers", "variants", "split", "size_mm", "smoothing_mm", "totals", "engraving_task", "strategy"):
        assert copy[same] == original[same], same
    assert (copy["undo"], copy["redo"], copy["exports"]) == (0, 0, []) and copy["plan_identifier"] != original["plan_identifier"]
    assert copy["history"][0]["op"] == {"op": "copy", "from": j["id"]} and len(copy["history"]) == 1 and copy["document"]["version"] == original["document"]["version"]
    assert c["client"].get(f"/api/vector/{j['id']}").json() == original                                               # the original is as it was
    mine, theirs = stored(c, copy), stored(c, j)
    assert mine["image_path"] != theirs["image_path"] and mine["document_path"] != theirs["document_path"]
    assert Path(mine["image_path"]).read_bytes() == Path(theirs["image_path"]).read_bytes() and Path(mine["document_path"]).is_file()
    assert c["client"].get(f"/api/plans/{copy['id']}/source-image").status_code == 200


def test_a_copy_goes_on_alone_and_survives_the_deletion_of_the_work_it_came_from(work, job):
    c, j = work, job
    copy = copy_of(c, j, name="Try blue")
    colouring(c, copy, op="assign", mode="random")                                                                    # another colouring on the copy only
    assert c["client"].get(f"/api/vector/{j['id']}").json()["colouring"]["mode"] == "closest"
    assert c["client"].get(f"/api/vector/{copy['id']}").json()["colouring"]["mode"] == "random"
    first = stored(c, j)
    assert c["client"].delete(f"/api/plans/{j['id']}").status_code == 204
    for path in (first["image_path"], first["document_path"]):                                                        # and what the original kept on disk is gone
        Path(path).unlink()
    assert [w["id"] for w in works(c)] == [copy["id"]]
    assert c["client"].get(f"/api/vector/{copy['id']}").status_code == 200 and thumb(c, copy).status_code == 200
    export = c["client"].get(f"/api/vector/{copy['id']}/export.lbrn2")
    assert export.status_code == 200 and b"LightBurnProject" in export.content
    again = c["client"].post(f"/api/vector/{copy['id']}/copy")                                                         # a copy can be copied
    assert again.status_code == 201 and c["client"].get(f"/api/vector/{again.json()['id']}").json()["name"] == "Try blue (копия)"


def test_a_copy_keeps_the_ai_colouring_but_not_the_permission_to_send_the_photograph(work, job, model):
    c, j = work, job
    fake = model()
    assert c["client"].post(f"/api/vector/{j['id']}/ai-photo", json={"allowed": True}).status_code == 200
    assert ai_op(c, j, style="impressionism").status_code == 200 and len(fake.calls) == 1
    new = c["client"].post(f"/api/vector/{j['id']}/copy").json()["id"]
    copy = c["client"].get(f"/api/vector/{new}").json()
    assert copy["colouring"]["ai"]["style"] == "impressionism" and copy["variants"][-1]["ai"]["style"] == "impressionism"
    assert c["client"].get(f"/api/vector/{j['id']}").json()["ai"]["photo_allowed"] is True and copy["ai"]["photo_allowed"] is False
    assert len(fake.calls) == 1                                                                                       # nothing was asked again


def test_a_copy_of_a_work_with_markers_has_markers_of_its_own(work):
    c = work
    j = create(c, n_colors=5, markers="true").json()
    copy = copy_of(c, j)
    assert j["markers"]["identifier"] == j["plan_identifier"] and copy["markers"]["identifier"] == copy["plan_identifier"] != j["plan_identifier"]
    assert copy["markers"]["extent"] == j["markers"]["extent"] and copy["markers_enabled"] is True


def test_a_traced_work_is_copied_too(work):
    c = work
    old = traced(c, "Lines", "line")
    copy = copy_of(c, old, name=" Lines 2 ")
    assert copy["name"] == "Lines 2" and copy["document"]["strategy"] == "line" and copy["exports"] == [] and len(copy["history"]) == 1
    assert copy["history"][0]["op"] == {"op": "copy", "from": old["id"]} and len(copy["regions"]) == len(old["regions"])
    assert [w["strategy"] for w in works(c)] == ["trace", "trace"]


@pytest.mark.parametrize("name", ["", "   ", 7, ["x"], False])
def test_a_copy_needs_a_real_name_when_one_is_given(work, job, name):
    r = work["client"].post(f"/api/vector/{job['id']}/copy", json={"name": name})
    assert r.status_code == 422 and r.json()["error"] == "give the plan a name"
    assert [w["id"] for w in works(work)] == [job["id"]]


def test_a_null_name_or_an_empty_object_means_the_made_name(work, job):
    c, j = work, job
    assert c["client"].post(f"/api/vector/{j['id']}/copy", json={"name": None}).status_code == 201
    assert c["client"].post(f"/api/vector/{j['id']}/copy", json={}).status_code == 201
    assert [w["name"] for w in works(c)] == ["Portrait (копия)", "Portrait (копия)", "Portrait"]


def test_a_copy_of_a_plan_that_is_not_a_vector_work_is_refused(work):
    c = work
    plate = cv.save_plan(c["store"], None, name="A plate", mode=pl.MODE_PLATE, status="Draft", device_id=c["w"]["setup"][0], lens_id=c["w"]["setup"][1],
                         markers=False, identifier="PLATE-2", band_count=None, data={})
    r = c["client"].post(f"/api/vector/{plate}/copy")
    assert r.status_code == 422 and r.json()["error"] == "this is not a vector job" and thumb(c, {"id": plate}).status_code == 422


def test_a_copy_whose_source_image_is_gone_says_so_and_leaves_nothing_behind(work, job):
    c, j = work, job
    Path(stored(c, j)["image_path"]).unlink()
    r = c["client"].post(f"/api/vector/{j['id']}/copy")
    assert r.status_code == 404 and r.json()["error"] == "the stored source image is missing"
    assert [w["id"] for w in works(c)] == [j["id"]]


# -- the AI on a computer without its library -----------------------------------------------------------------------------------------
MISSING = "the AI could not be started on this computer: a library it needs is missing or broken, install the app's dependencies (see README)"


@pytest.mark.parametrize("failure", [ModuleNotFoundError("No module named 'openai' in /Users/x/.venv/site-packages"), RuntimeError("boom at /secret/path")])
def test_an_ai_client_that_cannot_be_built_is_a_message_and_changes_nothing(work, job, monkeypatch, failure):
    c, j = work, job
    monkeypatch.setattr(research, "ai_available", lambda: True)

    def build():
        raise failure
    monkeypatch.setattr(research, "openai_client", build)
    before = state_of(c, j)
    r = ai_op(c, j)
    ai_refused(r, MISSING)
    assert "openai" not in r.text and "/Users" not in r.text and "secret" not in r.text
    assert state_of(c, j) == before and works(c)[0]["variants"] == 1


def test_the_view_says_what_the_ai_lacks_and_is_available_only_when_nothing_is_missing(work, job, monkeypatch):
    c, j = work, job

    def ai(library, key):
        monkeypatch.setattr(research, "ai_library", lambda: library)
        monkeypatch.setattr(research, "ai_available", lambda: key)
        return c["client"].get(f"/api/vector/{j['id']}").json()["ai"]
    assert (ai(True, True)["available"], ai(True, True)["missing"]) == (True, None)
    assert (ai(True, False)["available"], ai(True, False)["missing"]) == (False, "key")
    assert (ai(False, True)["available"], ai(False, True)["missing"]) == (False, "library")
    assert (ai(False, False)["available"], ai(False, False)["missing"]) == (False, "library")             # without the library a key is not enough
    assert set(ai(True, True)) == {"available", "missing", "styles", "photo_allowed", "photo_px", "max_text"}


def test_the_library_check_looks_for_openai_in_the_environment(monkeypatch):
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "openai" else real(name, *a))
    assert research.ai_library() is False
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: object() if name == "openai" else real(name, *a))
    assert research.ai_library() is True
