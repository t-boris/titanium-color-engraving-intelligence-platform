"""Unfinished creation tasks and the result previews (ux-work-creation-p0 REQ-002 DEC-001, REQ-003).

A task that setup or a starter test interrupted is kept on disk with its picture: closing the application is not discarding it, a task that
was completed or given up is never offered, and nothing half-made is left behind when a step fails.
"""
import json
import shutil

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from titanium_platform import creation_drafts as cd
from titanium_platform.api.app import create_app
from titanium_platform.db import Store

STATE = {"v": 1, "step": "result", "result": "colour", "name": "Portrait", "width_mm": "62.5", "method": {"colours": 9, "detail": "fine"},
         "waiting": {"for": "starter_test", "result": "colour"}}


def photo(rows=96, cols=144, seed=1) -> bytes:
    """A small picture with a few flat colour areas and a dark shape: something the previews have structure to find in."""
    img = np.full((rows, cols, 3), 235, np.uint8)
    img[10:60, 12:70] = (30, 60, 200)
    img[30:90, 80:130] = (200, 150, 20)
    cv2.circle(img, (40, 70), 14, (20, 20, 20), -1)
    cv2.line(img, (5, 5), (140, 90), (0, 0, 0), 3)
    return cv2.imencode(".png", img)[1].tobytes()


def other_photo() -> bytes:
    return cv2.imencode(".png", np.tile(np.linspace(255, 0, 120, dtype=np.uint8), (60, 1)))[1].tobytes()


def make(client, picture=None, **fields):
    data = {"flow": "new", "state": json.dumps(STATE), "name": "Portrait", **fields}
    files = {"picture": ("portrait.png", picture, "image/png")} if picture is not None else None
    return client.post("/api/creation/drafts", data=data, files=files)


@pytest.fixture
def world(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        yield {"client": client, "app": app, "path": tmp_path}
    app.state.store.close()


def reopen(world):
    """Close the application and open the same workshop again, as a person quitting and starting it."""
    world["app"].state.store.close()
    app = create_app(world["path"])
    return app, TestClient(app)


def test_a_draft_keeps_its_form_and_its_picture_and_survives_closing_the_application(world):
    client = world["client"]
    picture = photo()
    made = make(client, picture)
    assert made.status_code == 201
    draft = made.json()
    assert draft["status"] == "open" and draft["state"] == STATE and draft["name"] == "Portrait" and draft["flow"] == "new"
    assert draft["image"] == {"name": "portrait.png", "type": "image/png", "size": len(picture)}
    app, again = reopen(world)
    with again as client:
        [kept] = client.get("/api/creation/drafts").json()
        assert kept["id"] == draft["id"] and kept["status"] == "open" and kept["state"] == STATE     # the same task, not selected or entered again
        shown = client.get(f"/api/creation/drafts/{draft['id']}/picture")
        assert shown.status_code == 200 and shown.content == picture and shown.headers["content-type"] == "image/png"
    app.state.store.close()


def test_the_picture_is_kept_in_the_workshop_under_a_relative_name_so_a_copy_of_the_workshop_still_has_it(world, tmp_path_factory):
    client, path = world["client"], world["path"]
    picture = photo()
    draft = make(client, picture).json()
    row = world["app"].state.store.one("SELECT image_file FROM creation_draft WHERE id=?", (draft["id"],))
    assert not row["image_file"].startswith("/") and (path / "files" / "drafts" / row["image_file"]).read_bytes() == picture
    world["app"].state.store.close()
    moved = tmp_path_factory.mktemp("moved") / "workshop"
    shutil.copytree(path, moved)                     # a backup restored into another folder
    app = create_app(moved)
    with TestClient(app) as copy:
        assert copy.get(f"/api/creation/drafts/{draft['id']}/picture").content == picture
        assert [d["id"] for d in copy.get("/api/creation/drafts").json()] == [draft["id"]]
    app.state.store.close()


def test_a_completed_draft_is_never_offered_again_and_its_picture_is_removed(world):
    client, path = world["client"], world["path"]
    draft = make(client, photo()).json()
    done = client.post(f"/api/creation/drafts/{draft['id']}/complete", json={"work_kind": "vector", "work_id": 7})
    assert done.status_code == 200
    assert done.json()["status"] == "completed" and (done.json()["work_kind"], done.json()["work_id"]) == ("vector", 7) and done.json()["image"] is None
    assert client.get("/api/creation/drafts").json() == []
    assert list((path / "files" / "drafts").iterdir()) == []                  # no picture is kept for a task that is over
    assert client.get(f"/api/creation/drafts/{draft['id']}/picture").status_code == 404
    app, again = reopen(world)
    with again as client:
        assert client.get("/api/creation/drafts").json() == []                 # nor after a restart
    app.state.store.close()


def test_a_discarded_draft_is_never_offered_again_and_finishing_twice_changes_nothing(world):
    client = world["client"]
    draft = make(client, photo()).json()
    other = make(client, photo()).json()
    gone = client.post(f"/api/creation/drafts/{draft['id']}/discard")
    assert gone.status_code == 200 and gone.json()["status"] == "discarded" and gone.json()["work_id"] is None
    assert [d["id"] for d in client.get("/api/creation/drafts").json()] == [other["id"]]         # the other one is untouched
    again = client.post(f"/api/creation/drafts/{draft['id']}/complete", json={"work_kind": "vector", "work_id": 1})
    assert again.status_code == 200 and again.json()["status"] == "discarded"          # a task given up stays given up
    assert client.post(f"/api/creation/drafts/{draft['id']}/discard").json()["finished_at"] == gone.json()["finished_at"]
    audit = [r["action"] for r in world["app"].state.store.query("SELECT action FROM audit WHERE action LIKE 'creation_draft_%' ORDER BY id")]
    assert audit == ["creation_draft_discarded"]                                         # one decision, one record


def test_a_finished_draft_cannot_be_changed(world):
    client = world["client"]
    draft = make(client, photo()).json()
    client.post(f"/api/creation/drafts/{draft['id']}/discard")
    refused = client.put(f"/api/creation/drafts/{draft['id']}", data={"state": json.dumps({"step": "picture"})})
    assert refused.status_code == 422 and refused.json()["error"] == "this task is finished: it cannot be changed"


def test_saving_again_keeps_what_was_not_sent_and_replaces_the_picture_without_leaving_the_old_file(world):
    client, path = world["client"], world["path"]
    draft = make(client, photo()).json()
    first = next((path / "files" / "drafts").iterdir()).name
    moved = client.put(f"/api/creation/drafts/{draft['id']}", data={"state": json.dumps({**STATE, "step": "method"})}).json()
    assert moved["state"]["step"] == "method" and moved["name"] == "Portrait" and moved["image"]["name"] == "portrait.png"
    other = other_photo()
    swapped = client.put(f"/api/creation/drafts/{draft['id']}", files={"picture": ("grey.png", other, "image/png")}).json()
    assert swapped["image"]["name"] == "grey.png" and swapped["state"]["step"] == "method"            # the form stays, the picture is the new one
    names = [p.name for p in (path / "files" / "drafts").iterdir()]
    assert len(names) == 1 and names[0] != first
    assert client.get(f"/api/creation/drafts/{draft['id']}/picture").content == other
    renamed = client.put(f"/api/creation/drafts/{draft['id']}", data={"name": "  New name  "}).json()
    assert renamed["name"] == "New name"


def test_a_draft_without_a_picture_is_kept_and_a_picture_can_be_added_later(world):
    client = world["client"]
    draft = make(client).json()
    assert draft["image"] is None and client.get(f"/api/creation/drafts/{draft['id']}/picture").status_code == 404
    added = client.put(f"/api/creation/drafts/{draft['id']}", files={"picture": ("a.png", photo(), "image/png")}).json()
    assert added["image"]["name"] == "a.png"


def test_a_picture_that_is_not_one_is_refused_and_leaves_no_task_and_no_file(world):
    client, path = world["client"], world["path"]
    refused = make(client, b"this is not a picture")
    assert refused.status_code == 422 and refused.json()["error"] == "the image could not be read"
    empty = client.post("/api/creation/drafts", data={"flow": "new", "state": "{}"}, files={"picture": ("e.png", b"", "image/png")})
    assert empty.status_code == 422
    assert client.get("/api/creation/drafts").json() == []
    folder = path / "files" / "drafts"
    assert not folder.exists() or list(folder.iterdir()) == []                          # a refused picture leaves no file behind
    kept = make(client, photo()).json()
    bad = client.put(f"/api/creation/drafts/{kept['id']}", files={"picture": ("x.png", b"nope", "image/png")})
    assert bad.status_code == 422
    assert client.get(f"/api/creation/drafts/{kept['id']}/picture").content == photo()                  # the picture it had is still there
    assert len(list((path / "files" / "drafts").iterdir())) == 1


def test_a_form_that_is_not_an_object_or_too_large_or_of_an_unknown_screen_is_refused(world):
    client = world["client"]
    for state in ("[1, 2]", "not json", '"text"'):
        refused = client.post("/api/creation/drafts", data={"flow": "new", "state": state})
        assert refused.status_code == 422 and refused.json()["error"] == "the unfinished task must be an object", state
    big = client.post("/api/creation/drafts", data={"flow": "new", "state": json.dumps({"x": "x" * cd.MAX_STATE_BYTES})})
    assert big.status_code == 422 and big.json()["error"] == "the unfinished task holds too much text"
    unknown = client.post("/api/creation/drafts", data={"flow": "somewhere", "state": "{}"})
    assert unknown.status_code == 422 and unknown.json()["error"] == "the unfinished task belongs to an unknown creation screen"
    assert client.get("/api/creation/drafts").json() == []


def test_a_task_that_does_not_exist_is_not_found(world):
    client = world["client"]
    assert client.get("/api/creation/drafts/99").status_code == 404
    assert client.put("/api/creation/drafts/99", data={"name": "x"}).status_code == 404
    assert client.post("/api/creation/drafts/99/discard").status_code == 404
    assert client.post("/api/creation/drafts/99/complete", json={"work_kind": "vector", "work_id": 1}).status_code == 404
    assert client.get("/api/creation/drafts/99/preview/colour.png?width_mm=50").status_code == 404


def test_a_work_kind_is_required_to_complete_a_task(world):
    client = world["client"]
    draft = make(client, photo()).json()
    refused = client.post(f"/api/creation/drafts/{draft['id']}/complete", json={"work_kind": "  ", "work_id": 1})
    assert refused.status_code == 422 and refused.json()["error"] == "name the kind of the work that was made"
    assert client.get(f"/api/creation/drafts/{draft['id']}").json()["status"] == "open"


def test_a_table_made_by_an_older_workshop_gets_the_drafts_table_and_the_existing_data_is_kept(tmp_path):
    first = Store(tmp_path / "w")
    first.execute("DROP TABLE creation_draft")                 # a workshop made before this feature
    first.set_setting("marker", 1)
    first.close()
    second = Store(tmp_path / "w")
    assert second.one("SELECT COUNT(*) AS n FROM creation_draft")["n"] == 0 and second.get_setting("marker") == 1
    second.close()


# -- the comparable previews (REQ-003) ----------------------------------------------------------------------------------------------
def tile(client, draft_id, result, width=60, **headers):
    return client.get(f"/api/creation/drafts/{draft_id}/preview/{result}.png", params={"width_mm": width}, headers=headers)


def decode(response):
    return cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)


def test_every_result_has_a_picture_of_the_users_own_image_and_they_differ(world):
    client = world["client"]
    draft = make(client, photo()).json()
    tiles = {result: tile(client, draft["id"], result) for result in ("colour", "photo", "silhouette", "lines")}
    for result, answer in tiles.items():
        assert answer.status_code == 200 and answer.headers["content-type"] == "image/png", result
        assert max(decode(answer).shape[:2]) <= 360 and decode(answer).shape[0] > 0
    pictures = {r: decode(a) for r, a in tiles.items()}
    shapes = {p.shape for p in pictures.values()}
    assert len(shapes) == 1                                    # the same picture at the same size: they can be compared side by side
    keys = list(pictures)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            assert not np.array_equal(pictures[a], pictures[b]), (a, b)
    facts = {r: json.loads(a.headers["x-preview-facts"]) for r, a in tiles.items()}
    assert facts["colour"]["areas"] >= 2 and facts["silhouette"]["areas"] >= 1 and facts["lines"]["strokes"] >= 1 and facts["photo"]["levels"] >= 2


def test_a_tile_is_revalidated_by_its_key_and_the_width_makes_another_one(world):
    client = world["client"]
    draft = make(client, photo()).json()
    first = tile(client, draft["id"], "silhouette")
    etag = first.headers["etag"]
    assert tile(client, draft["id"], "silhouette", **{"If-None-Match": etag}).status_code == 304
    wider = tile(client, draft["id"], "silhouette", width=120)
    assert wider.headers["etag"] != etag                       # the same picture at another width is not the same tile
    changed = client.put(f"/api/creation/drafts/{draft['id']}", files={"picture": ("g.png", other_photo(), "image/png")})
    assert changed.status_code == 200
    assert tile(client, draft["id"], "silhouette").headers["etag"] != etag               # nor another picture
    assert tile(client, draft["id"], "silhouette", **{"If-None-Match": etag}).status_code == 200


def test_a_tile_that_cannot_be_made_says_why(world):
    client = world["client"]
    draft = make(client, photo()).json()
    assert tile(client, draft["id"], "painting").status_code == 422
    assert tile(client, draft["id"], "colour", width=0).status_code == 422
    assert tile(client, draft["id"], "colour", width=-5).status_code == 422
    assert client.get(f"/api/creation/drafts/{draft['id']}/preview/colour.png", params={"width_mm": "wide"}).status_code == 422
    assert client.get(f"/api/creation/drafts/{draft['id']}/preview/colour.png").status_code == 422        # the width is required
    client.post(f"/api/creation/drafts/{draft['id']}/discard")
    assert tile(client, draft["id"], "colour").status_code == 404                        # a task that is over has no picture to draw
