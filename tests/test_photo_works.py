"""Photo engraving works (REQ-061, DEC-104): kept like vector works, each on its measured scale with Min, Max, width and colour choice."""
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from test_ai_colouring import Fake, sent
from test_grey_scales import HUES, app_world, picture_png  # noqa: F401  (the measured grey-ramp plate, four scales)
from titanium_platform import grayscale, lightburn, people, photo_work, research
from titanium_platform.api.app import create_app


def create(client, **fields):
    data = {"width_mm": 60, **fields}
    answer = client.post("/api/photo-works", data=data, files={"picture": ("girl.png", picture_png(), "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def scale_of(client, speed, line_interval):
    scales = client.get("/api/grey-scales").json()["scales"]
    return next(sc["mode"] for sc in scales if sc["mode"]["speed"] == speed and sc["mode"]["line_interval"] == line_interval)


def test_a_new_work_starts_on_the_best_measured_scale_at_its_measured_min_and_max_and_is_listed(app_world):
    client = app_world["client"]
    best = client.get("/api/grey-scales").json()["scales"][0]
    work = create(client)
    assert work["name"] == "girl" and work["image_name"] == "girl.png" and work["image_size"] == [240, 120]
    assert work["scale"] == best["mode"] and (work["min_power"], work["max_power"]) == (2.0, 40.0) and not work["by_colour"]
    assert (work["width_mm"], work["height_mm"]) == (60, 30) and work["time"]["seconds"] > 0
    shown = work["picture"]
    assert shown["power_range"] == [2.0, 40.0] and shown["size_mm"] == {"width": 60, "height": 30}
    png = client.get(shown["preview"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.headers["etag"]
    listed = client.get("/api/photo-works").json()
    assert listed[0]["id"] == work["id"] and listed[0]["name"] == "girl" and "picture" not in listed[0]
    thumb = client.get(f"/api/photo-works/{work['id']}/thumb.png")
    assert thumb.status_code == 200 and max(cv2.imdecode(np.frombuffer(thumb.content, np.uint8), cv2.IMREAD_COLOR).shape[:2]) == 240
    assert client.get(f"/api/photo-works/{work['id']}/thumb.png", headers={"If-None-Match": thumb.headers["etag"]}).status_code == 304
    original = client.get(f"/api/photo-works/{work['id']}/picture")
    assert original.content == picture_png() and original.headers["content-type"] == "image/png"
    # a work nobody photographed is the operator's work, not an experiment
    experiments = client.get("/api/experiments").json()
    assert not any((e.get("plan_id") or e.get("id")) in (work["id"], f"plan-{work['id']}") for e in experiments)


def test_another_scale_keeps_the_picture_and_takes_its_measured_span_and_every_change_is_saved(app_world):
    client = app_world["client"]
    work = create(client, name="  Портрет  ")
    assert work["name"] == "Портрет"
    other = scale_of(client, 250, 0.0254)
    moved = client.post(f"/api/photo-works/{work['id']}/settings", json={"scale": other}).json()
    assert moved["scale"] == other and moved["image_size"] == [240, 120] and moved["picture"]["power_range"] == [moved["min_power"], moved["max_power"]]
    assert moved["picture"]["preview"] != work["picture"]["preview"]
    changed = client.post(f"/api/photo-works/{work['id']}/settings", json={"min_power": 10, "max_power": 30, "width_mm": 100, "by_colour": True}).json()
    assert (changed["min_power"], changed["max_power"], changed["width_mm"], changed["height_mm"], changed["by_colour"]) == (10, 30, 100, 50, True)
    assert changed["picture"]["colour_match"]["greys_available"] > 0
    again = client.get(f"/api/photo-works/{work['id']}").json()
    assert (again["scale"], again["min_power"], again["max_power"], again["width_mm"], again["by_colour"]) == (other, 10, 30, 100, True)
    assert again["updated_at"] >= work["updated_at"]
    only_max = client.post(f"/api/photo-works/{work['id']}/settings", json={"max_power": 25}).json()
    assert (only_max["min_power"], only_max["max_power"]) == (10, 25)


@pytest.mark.parametrize("body, message", [
    ({}, "change the scale, Min and Max power, the width, the colour choice, the contours or the rules of the parts of the work"),
    ({"name": "x"}, "change the scale, Min and Max power, the width, the colour choice, the contours or the rules of the parts of the work"),
    ({"scale": {"speed": 999}}, "this scale is not measured: choose one of the measured scales"),
    ({"width_mm": 0}, "the width of the picture must be 1..1000 mm"),
    ({"width_mm": True}, "the width of the picture must be 1..1000 mm"),
    ({"by_colour": "yes"}, "the colour choice must be on or off"),
    ({"colour_choice": "prettiest"}, "the colour choice must keep the drawing or take the nearest colour"),
    ({"contours": 1}, "the contours must be on or off"),
    ({"min_power": 50, "max_power": 20}, "Min power 50 % and Max power 20 % must lie within 0..100 % with Min not above Max"),
])
def test_a_change_that_cannot_be_made_is_refused_with_the_reason_and_the_work_stays_as_it_was(app_world, body, message):
    client = app_world["client"]
    work = create(client)
    refused = client.post(f"/api/photo-works/{work['id']}/settings", json=body)
    assert refused.status_code == 422 and refused.json()["error"] == message
    kept = client.get(f"/api/photo-works/{work['id']}").json()
    assert {k: kept[k] for k in ("scale", "min_power", "max_power", "width_mm", "by_colour")} == \
        {k: work[k] for k in ("scale", "min_power", "max_power", "width_mm", "by_colour")}


def test_the_file_is_one_grayscale_image_layer_with_the_works_settings_named_after_the_work(app_world):
    client = app_world["client"]
    work = create(client, name="Мотоцикл")
    client.post(f"/api/photo-works/{work['id']}/settings", json={"min_power": 10, "max_power": 30})
    file = client.get(work["picture"]["file"])
    assert file.status_code == 200 and "filename*=UTF-8''%D0%9C%D0%BE%D1%82%D0%BE%D1%86%D0%B8%D0%BA%D0%BB-P10-30.lbrn2" in file.headers["content-disposition"]
    layer = lightburn.parse_bytes(file.content).layer(0)
    mode = work["scale"]
    assert (layer.layer_type, layer.power, layer.image_summary()["min_power"]) == ("Image", 30, 10)
    assert (layer.speed, layer.line_interval, layer.frequency_khz) == (mode["speed"], mode["line_interval"], mode["frequency"])
    stored = cv2.imdecode(np.frombuffer(layer.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)
    assert stored.shape == (120, 240) and stored[0, 0] == 255 and stored[0, -1] == 0


def test_a_copy_is_a_work_of_its_own_rename_changes_the_name_only_and_delete_removes_the_work(app_world):
    client = app_world["client"]
    work = create(client, name="Inna")
    client.post(f"/api/photo-works/{work['id']}/settings", json={"min_power": 12, "max_power": 28, "by_colour": True})
    made = client.post(f"/api/photo-works/{work['id']}/copy", json={}).json()
    copy = client.get(f"/api/photo-works/{made['id']}").json()
    assert copy["name"] == "Inna (копия)" and copy["identifier"] != work["identifier"]
    assert (copy["min_power"], copy["max_power"], copy["by_colour"], copy["scale"]) == (12, 28, True, work["scale"])
    store = app_world["client"].app.state.store
    paths = [photo_work._work(store, i)["image_path"] for i in (work["id"], made["id"])]
    assert paths[0] != paths[1]
    assert client.post(f"/api/photo-works/{made['id']}/rename", json={"name": " Инна "}).json() == {"id": made["id"], "name": "Инна"}
    assert client.get(f"/api/photo-works/{made['id']}").json()["min_power"] == 12
    assert client.post(f"/api/photo-works/{made['id']}/rename", json={"name": " "}).status_code == 422
    assert client.delete(f"/api/plans/{made['id']}").status_code == 204
    assert made["id"] not in [w["id"] for w in client.get("/api/photo-works").json()]
    gone = client.get(f"/api/photo-works/{made['id']}")
    assert gone.status_code == 404 and gone.json()["error"] == f"plan {made['id']} not found"          # never photographed: removed
    assert client.get(f"/api/photo-works/{work['id']}").json()["name"] == "Inna"           # the first stays as it was


def test_a_work_whose_scale_is_no_longer_measured_opens_and_says_why_and_another_scale_can_be_chosen(app_world):
    client = app_world["client"]
    store = client.app.state.store
    work = create(client)
    row = store.one("SELECT data_json FROM plan WHERE id=?", (work["id"],))
    data = json.loads(row["data_json"])
    data["scale"]["speed"] = 999                        # as if its measurements were deleted
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), work["id"]))
    shown = client.get(f"/api/photo-works/{work['id']}").json()
    assert shown["picture"] is None and shown["problem"] == "no colour has been measured at this mode: there is nothing to predict from"
    assert client.get(f"/api/photo-works/{work['id']}/thumb.png").status_code == 200       # the picture as LightBurn sees it
    assert client.get(f"/api/photo-works/{work['id']}/export.lbrn2").status_code == 422
    back = client.post(f"/api/photo-works/{work['id']}/settings", json={"scale": scale_of(client, 150, 0.0169)}).json()
    assert back["picture"]["power_range"] == [2.0, 40.0]


def test_without_a_measured_scale_a_new_work_is_refused_with_the_way_to_measure_one(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        refused = client.post("/api/photo-works", data={"width_mm": 50}, files={"picture": ("p.png", picture_png(), "image/png")})
        assert refused.status_code == 422
        assert refused.json()["error"] == "no grayscale scale is measured yet: engrave the grey-scale plate and add its photograph first"
        not_a_picture = client.post("/api/photo-works", data={"width_mm": 50}, files={"picture": ("p.png", b"nothing", "image/png")})
        assert not_a_picture.status_code == 422
    app.state.store.close()


# -- the parts of the picture and their rules (REQ-062, DEC-105) ----------------------------------------------------------------------
@pytest.fixture
def parts_model(monkeypatch):
    """The people model as if it found face skin on the left half of the test picture (white to grey) and clothes on the right."""
    calls = []

    def scores(bgr):
        calls.append(bgr.shape)
        out = np.zeros((256, 256, 6), np.float32)
        out[:, :128, people.PARTS.index("face_skin")] = 1
        out[:, 128:, people.PARTS.index("clothes")] = 1
        return out
    monkeypatch.setattr(people, "scores", scores)
    return calls


@pytest.fixture
def model(monkeypatch):
    def install(*replies, available=True):
        fake = Fake(*replies)
        monkeypatch.setattr(research, "ai_available", lambda: available)
        monkeypatch.setattr(research, "openai_client", lambda: fake)
        return fake
    return install


def stored_grey(client, work):
    layer = lightburn.parse_bytes(client.get(f"/api/photo-works/{work['id']}/export.lbrn2").content).layer(0)
    return cv2.imdecode(np.frombuffer(layer.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)


def test_the_parts_of_the_picture_are_found_once_with_their_share_and_colour_and_shown_tinted(app_world, parts_model):
    client = app_world["client"]
    work = create(client)
    found = client.get(f"/api/photo-works/{work['id']}/parts").json()
    assert [(p["part"], p["share"], p["tint"]) for p in found["parts"]] == [("face_skin", 0.5, "#ff8c64"), ("clothes", 0.5, "#4678ff")]
    face, clothes = found["parts"]
    assert face["lab"][0] > clothes["lab"][0] and face["hex"].startswith("#")              # the white half is lighter
    png = client.get(found["picture"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.headers["etag"]
    client.get(f"/api/photo-works/{work['id']}/parts")
    assert len(parts_model) == 1                                                              # kept with the decoded picture


def test_a_rule_set_by_hand_changes_the_prediction_and_the_file_inside_its_part_only_and_a_copy_keeps_it(app_world, parts_model):
    client = app_world["client"]
    work = create(client)
    before = stored_grey(client, work)
    ruled = client.post(f"/api/photo-works/{work['id']}/settings", json={"rules": [{"part": "clothes", "kind": "even", "hex": "#808080"}]}).json()
    assert [(r["part"], r["kind"]) for r in ruled["rules"]] == [("clothes", "even")] and len(ruled["rules"][0]["lab"]) == 3
    report = ruled["picture"]["rules_report"]
    assert [(r["part"], r["share"]) for r in report] == [("clothes", 0.5)] and report[0]["median_de"] is not None
    assert ruled["picture"]["preview"] != work["picture"]["preview"] and ruled["time"] == work["time"]   # every pixel is scanned anyway
    after = stored_grey(client, work)
    assert len(np.unique(after[:, 125:])) == 1 and len(np.unique(before[:, 125:])) > 10              # clothes: one even tone
    assert np.array_equal(after[:, :115], before[:, :115])                                            # face skin: as it was
    made = client.post(f"/api/photo-works/{work['id']}/copy", json={}).json()
    assert client.get(f"/api/photo-works/{made['id']}").json()["rules"] == ruled["rules"]
    cleared = client.post(f"/api/photo-works/{work['id']}/settings", json={"rules": [{"part": "clothes", "kind": "as_is"}]}).json()
    assert cleared["rules"] == [] and cleared["picture"]["preview"] == work["picture"]["preview"]


@pytest.mark.parametrize("body, message", [
    ({"rules": [{"part": "dress", "kind": "even"}]}, "a rule must name one of the parts background, hair, body_skin, face_skin, clothes, other, each once"),
    ({"rules": [{"part": "clothes", "kind": "glow"}]}, "a rule must be one of as_is, photo, neutral, colour, even"),
    ({"rules": [{"part": "clothes", "kind": "colour"}]}, "a target colour must be L*a*b*: L 0..100, a and b -128..128"),
    ({"rules": [{"part": "clothes", "kind": "even", "hex": "violet"}]}, "a target colour must be given as #rrggbb"),
    ({"rules": "all"}, "the rules of the parts must be a list of at most 6"),
    ({"ai_photo": "yes"}, "the permission to send the photograph must be on or off"),
])
def test_a_rule_that_cannot_be_applied_is_refused_with_the_reason(app_world, body, message):
    client = app_world["client"]
    work = create(client)
    refused = client.post(f"/api/photo-works/{work['id']}/settings", json=body)
    assert refused.status_code == 422 and refused.json()["error"] == message
    kept = client.get(f"/api/photo-works/{work['id']}").json()
    assert (kept["rules"], kept["ai_photo"]) == ([], False)


VIOLET = {"rules": [{"part": "clothes", "kind": "colour", "lab": [40, 40, -40]}, {"part": "hair", "kind": "neutral"}, {"part": "face_skin", "kind": "as_is"}],
          "note": "платье фиолетовым, остальное как есть"}


def test_the_ai_gets_the_wish_the_parts_and_the_scale_and_its_rules_are_saved_with_its_note(app_world, parts_model, model):
    client = app_world["client"]
    fake = model(VIOLET)
    work = create(client)
    answer = client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": "  платье сделать фиолетовым  "})
    assert answer.status_code == 200, answer.text
    done = answer.json()
    assert [{k: r[k] for k in ("part", "kind", "lab")} for r in done["rules"]] == [{"part": "clothes", "kind": "colour", "lab": [40.0, 40.0, -40.0]}]
    assert done["rules"][0]["hex"].startswith("#")                                                    # no hair in the picture; as_is is no rule
    assert {k: done["ai"][k] for k in ("wish", "photo", "note", "before")} == {"wish": "платье сделать фиолетовым", "photo": False,
                                                                                "note": "платье фиолетовым, остальное как есть", "before": []}
    brief = sent(fake.calls[0])
    assert brief["wish"] == "платье сделать фиолетовым" and [p["part"] for p in brief["parts"]] == ["face_skin", "clothes"]
    assert brief["scale"][0]["grey"] == 255 and len(brief["scale"]) == 16 and brief["current"] == []
    assert isinstance(fake.calls[0]["input"][0]["content"], str)                                    # numbers only: no picture
    assert client.get(f"/api/photo-works/{work['id']}").json()["rules"] == done["rules"]
    back = client.post(f"/api/photo-works/{work['id']}/settings", json={"rules": done["ai"]["before"]}).json()
    assert back["rules"] == []                                                                        # "Вернуть как было"


def test_the_picture_goes_to_the_ai_only_when_allowed(app_world, parts_model, model):
    client = app_world["client"]
    fake = model(VIOLET)
    work = create(client)
    assert client.post(f"/api/photo-works/{work['id']}/settings", json={"ai_photo": True}).json()["ai_photo"] is True
    done = client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": "платье фиолетовым"}).json()
    content = fake.calls[0]["input"][0]["content"]
    assert [part["type"] for part in content] == ["input_text", "input_image"] and done["ai"]["photo"] is True


def test_a_bad_ai_answer_is_sent_back_once_and_a_second_one_changes_nothing(app_world, parts_model, model):
    client = app_world["client"]
    bad = {"rules": [{"part": "clothes", "kind": "glow"}], "note": "?"}
    fake = model(bad, VIOLET)
    work = create(client)
    assert client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": "платье фиолетовым"}).json()["rules"][0]["part"] == "clothes"
    assert "Rejected: a rule must be one of as_is, photo, neutral, colour, even" in fake.calls[1]["input"][2]["content"]
    other = create(client)
    model(bad, bad)
    refused = client.post(f"/api/photo-works/{other['id']}/ai", json={"wish": "платье фиолетовым"})
    assert refused.status_code == 422 and refused.json()["error"] == "a rule must be one of as_is, photo, neutral, colour, even"
    kept = client.get(f"/api/photo-works/{other['id']}").json()
    assert (kept["rules"], kept["ai"]) == ([], None)


@pytest.mark.parametrize("wish, available, message", [
    ("  ", True, "describe what the AI should change in the picture"),
    ("я" * 401, True, "the description may have at most 400 characters"),
    ("платье фиолетовым", False, "the AI is off: no key for the language model is set (OPENAI_API_KEY)"),
])
def test_the_ai_is_not_asked_without_a_wish_or_a_key(app_world, model, wish, available, message):
    client = app_world["client"]
    fake = model(VIOLET, available=available)
    work = create(client)
    refused = client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": wish})
    assert refused.status_code == 422 and refused.json()["error"] == message and fake.calls == []


def test_a_work_saved_before_the_rules_of_parts_is_listed_opened_changed_and_copied(app_world):
    client = app_world["client"]
    store = client.app.state.store
    work = create(client)
    row = store.one("SELECT data_json FROM plan WHERE id=?", (work["id"],))
    data = {k: v for k, v in json.loads(row["data_json"]).items() if k not in ("rules", "ai_photo", "ai")}   # as 0.19.0 stored it
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), work["id"]))
    listed = client.get("/api/photo-works")
    assert listed.status_code == 200 and listed.json()[0]["rules"] == []
    opened = client.get(f"/api/photo-works/{work['id']}").json()
    assert (opened["rules"], opened["ai"], opened["ai_photo"]) == ([], None, False)
    assert client.post(f"/api/photo-works/{work['id']}/settings", json={"max_power": 30}).json()["max_power"] == 30
    assert client.post(f"/api/photo-works/{work['id']}/copy", json={}).status_code == 201


def test_a_change_made_while_the_ai_answers_is_kept(app_world, parts_model, model):
    client = app_world["client"]
    work = create(client)

    def answer(brief):
        assert client.post(f"/api/photo-works/{work['id']}/settings", json={"max_power": 30}).status_code == 200
        return VIOLET
    model(answer)
    done = client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": "платье фиолетовым"}).json()
    assert done["max_power"] == 30 and done["rules"][0]["part"] == "clothes"


# -- undo and redo (0.19.2) -----------------------------------------------------------------------------------------------------------
def settings(client, work, **changes):
    answer = client.post(f"/api/photo-works/{work['id']}/settings", json=changes)
    assert answer.status_code == 200, answer.text
    return answer.json()


def step(client, work, direction):
    return client.post(f"/api/photo-works/{work['id']}/{direction}")


def test_every_change_of_what_the_work_engraves_is_undone_and_redone_one_step_at_a_time(app_world, parts_model, model):
    client = app_world["client"]
    model(VIOLET)
    work = create(client)
    assert (work["undo"], work["redo"]) == (0, 0)
    settings(client, work, max_power=30)
    settings(client, work, width_mm=40, by_colour=True)
    settings(client, work, rules=[{"part": "face_skin", "kind": "neutral"}])
    asked = client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": "платье фиолетовым"}).json()
    assert asked["undo"] == 4 and [r["part"] for r in asked["rules"]] == ["clothes"]           # the AI left face skin as it is
    back = step(client, work, "undo").json()                                                     # the AI's answer
    assert (back["rules"], back["ai"], back["undo"], back["redo"]) == ([{"part": "face_skin", "kind": "neutral"}], None, 3, 1)
    back = step(client, work, "undo").json()                                                     # the rule set by hand
    assert back["rules"] == [] and back["picture"]["preview"] != asked["picture"]["preview"]
    back = step(client, work, "undo").json()                                                     # width and colour choice together
    assert (back["width_mm"], back["by_colour"], back["max_power"]) == (60, False, 30)
    back = step(client, work, "undo").json()
    assert (back["max_power"], back["undo"], back["redo"]) == (work["max_power"], 0, 4)
    assert back["picture"]["preview"] == work["picture"]["preview"]                             # the work as it was made
    refused = step(client, work, "undo")
    assert refused.status_code == 422 and refused.json()["error"] == "there is no earlier change of the work to undo"
    again = step(client, work, "redo").json()
    assert (again["max_power"], again["undo"], again["redo"]) == (30, 1, 3)
    for _ in range(3):
        again = step(client, work, "redo").json()
    assert again["rules"] == asked["rules"] and again["ai"]["wish"] == "платье фиолетовым" and again["redo"] == 0
    refused = step(client, work, "redo")
    assert refused.status_code == 422 and refused.json()["error"] == "there is no undone change to redo"


def test_a_new_change_after_an_undo_drops_what_could_be_redone_and_a_change_to_nothing_is_no_step(app_world):
    client = app_world["client"]
    work = create(client)
    settings(client, work, max_power=30)
    assert step(client, work, "undo").json()["redo"] == 1
    assert settings(client, work, width_mm=50)["redo"] == 0
    same = settings(client, work, width_mm=50, rules=[{"part": "hair", "kind": "as_is"}])
    assert same["undo"] == 1                                                                      # nothing changed: no step
    allowed = settings(client, work, ai_photo=True)
    assert (allowed["undo"], allowed["ai_photo"]) == (1, True)                                   # the permission is not a step
    undone = step(client, work, "undo").json()
    assert (undone["width_mm"], undone["ai_photo"]) == (60, True)                                # and undo does not touch it


def test_undo_brings_back_another_scale_with_its_min_and_max(app_world):
    client = app_world["client"]
    work = create(client)
    other = next(sc for sc in client.get("/api/grey-scales").json()["scales"] if sc["mode"] != work["scale"])
    moved = settings(client, work, scale=other["mode"])
    assert moved["scale"] == other["mode"]
    back = step(client, work, "undo").json()
    assert (back["scale"], back["min_power"], back["max_power"]) == (work["scale"], work["min_power"], work["max_power"])
    assert back["picture"]["preview"] == work["picture"]["preview"]


def test_a_copy_starts_without_history_and_the_steps_are_kept_with_the_work(app_world):
    client = app_world["client"]
    work = create(client)
    settings(client, work, max_power=30)
    made = client.post(f"/api/photo-works/{work['id']}/copy", json={}).json()
    copied = client.get(f"/api/photo-works/{made['id']}").json()
    assert (copied["max_power"], copied["undo"], copied["redo"]) == (30, 0, 0)
    assert client.get(f"/api/photo-works/{work['id']}").json()["undo"] == 1
    assert client.get("/api/photo-works").json()[1]["undo"] == 1


def test_asked_again_from_the_picture_the_ai_is_not_told_the_present_rules(app_world, parts_model, model):
    client = app_world["client"]
    fake = model(VIOLET)
    work = create(client)
    settings(client, work, rules=[{"part": "face_skin", "kind": "neutral"}])
    client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": "платье фиолетовым"})
    assert sent(fake.calls[-1])["current"] == [{"part": "face_skin", "kind": "neutral"}]
    fresh = client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": "платье фиолетовым", "fresh": True}).json()
    assert sent(fake.calls[-1])["current"] == []
    assert [r["part"] for r in fresh["rules"]] == ["clothes"] and fresh["ai"]["fresh"] is True    # face skin as it is again
    refused = client.post(f"/api/photo-works/{work['id']}/ai", json={"wish": "платье", "fresh": "yes"})
    assert refused.status_code == 422 and refused.json()["error"] == "starting again from the picture must be on or off"


# -- the drawing kept and contours (0.20.1, DEC-108) -----------------------------------------------------------------------------------
def portrait_png(rows=800, cols=1600) -> bytes:
    """A coloured picture larger than the preview: a light skin-coloured field over a grey gradient, a darker reddish 'mouth' with a dark
    crease, and a blue band."""
    bgr = np.tile(np.linspace(230, 60, cols), (rows, 1))[..., None].repeat(3, axis=2).astype(np.uint8)
    bgr[100:700, 200:1000] = (150, 180, 220)
    bgr[450:550, 400:800] = (120, 120, 200)
    bgr[497:503, 420:780] = (60, 60, 110)
    bgr[150:300, 1100:1500] = (200, 120, 60)
    return cv2.imencode(".png", bgr)[1].tobytes()


def test_a_new_work_keeps_the_drawing_without_contours_and_lines_are_drawn_only_on_greys_picked_by_colour(app_world):
    client = app_world["client"]
    work = create(client)
    assert (work["colour_choice"], work["contours"], work["picture"]["contours_report"]) == ("drawing", False, None)
    plain = settings(client, work, contours=True)
    assert plain["contours"] is True and plain["picture"]["contours_report"] is None                # the picture as uploaded is never drawn on
    coloured = settings(client, work, by_colour=True)
    match = coloured["picture"]["colour_match"]
    assert match["choice"] == "drawing" and match["reach"][0] < match["reach"][1] and match["path"] > 1 and match["order"] > 0.9
    assert coloured["picture"]["contours_report"] == {"share": 0.0}                                 # a smooth gradient loses no edge
    changed = settings(client, work, colour_choice="nearest", contours=False)
    assert (changed["colour_choice"], changed["contours"], changed["picture"]["contours_report"]) == ("nearest", False, None)
    assert changed["picture"]["colour_match"]["choice"] == "nearest" and changed["picture"]["preview"] != coloured["picture"]["preview"]
    back = step(client, work, "undo").json()
    assert (back["colour_choice"], back["contours"], back["by_colour"]) == ("drawing", True, True)


def test_a_work_saved_before_the_drawing_was_kept_opens_keeping_it_without_contours(app_world):
    client = app_world["client"]
    store = client.app.state.store
    work = create(client)
    row = store.one("SELECT data_json FROM plan WHERE id=?", (work["id"],))
    data = json.loads(row["data_json"])
    del data["colour_choice"], data["contours"]
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), work["id"]))
    shown = client.get(f"/api/photo-works/{work['id']}").json()
    assert (shown["colour_choice"], shown["contours"], shown["picture"]["contours_report"]) == ("drawing", False, None)


def test_the_file_is_the_picture_the_preview_shows_at_the_layers_resolution(app_world):
    client = app_world["client"]
    store = client.app.state.store
    answer = client.post("/api/photo-works", data={"width_mm": 60}, files={"picture": ("face.png", portrait_png(), "image/png")})
    work = answer.json()
    settings(client, work, by_colour=True)
    plan = photo_work._work(store, work["id"])
    item = photo_work._item(store, plan)
    preview = (np.clip(photo_work._shown(item, plan)["picture"], 0, 1) * 255).round().astype(np.uint8)
    layer = lightburn.parse_bytes(client.get(f"/api/photo-works/{work['id']}/export.lbrn2").content).layer(0)
    stored = cv2.imdecode(np.frombuffer(layer.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)[::-1]   # stored bottom row first
    assert stored.shape == (800, 1600) and preview.shape == (400, 800)                         # the file has twice the preview's pixels
    greys, labs = grayscale.usable_greys(item["curve"], plan["min_power"], plan["max_power"])
    table = np.zeros((256, 3), np.float32)
    table[greys] = labs
    file_look = cv2.resize(table[stored], (800, 400), interpolation=cv2.INTER_AREA)
    differ = np.linalg.norm(file_look - table[preview], axis=-1)
    assert np.median(differ) < 2 and np.percentile(differ, 90) < 8                              # the same picture, finer
