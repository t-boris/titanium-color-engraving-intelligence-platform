"""Colouring a photo work by its objects, like a colouring book (0.21.0): the objects of the picture are listed with the scale's colours to
colour them with, an object given a main colour by hand or by a theme is engraved in that colour's stretch of the scale (in the preview and
the file alike) while the others keep the drawing, and the colours are kept in the work with its undo."""
import numpy as np
import pytest

from test_ai_colouring import sent
from test_grey_scales import app_world  # noqa: F401  (the measured grey-ramp plate, four scales)
from test_photo_work_kinds import create, curve_of, png, settings
from test_photo_works import model, parts_model, step, stored_grey  # noqa: F401  (face skin on the left half, clothes on the right)
from titanium_platform import colouring, grayscale, objects, photo_work


def found(client, work):
    answer = client.get(f"/api/photo-works/{work['id']}/objects")
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_objects_of_the_picture_are_listed_with_the_scales_colours_and_the_themes_and_shown_tinted(app_world, parts_model):
    client = app_world["client"]
    work = create(client)
    listed = found(client, work)
    assert [(o["key"], o["kind"], o["share"], o["colour"]) for o in listed["objects"]] == [("face_skin", "face_skin", 0.5, None),
                                                                                           ("clothes", "clothes", 0.5, None)]
    assert listed["objects"][0]["tint"] == "#%02x%02x%02x" % objects.TINTS["face_skin"] and not listed["active"]
    assert listed["themes"] == list(colouring.THEMES)
    assert listed["notes"] == ["No face was found, so there are no lips or eyes."] and listed["faces"] == 0
    lo, hi = curve_of(client, work).span
    options = listed["options"]
    assert len(options) >= 3 and all(lo <= o["power"] <= hi and o["hex"].startswith("#") for o in options)
    tinted = png(client, listed["picture"])
    assert tinted.shape[:2] == (120, 240) and not np.array_equal(tinted[:, 10], tinted[:, -10])
    found(client, work)
    assert len(parts_model) == 1                                                           # found once for the decoded picture


def test_an_object_coloured_by_hand_is_engraved_in_its_colours_stretch_and_the_others_keep_the_drawing(app_world, parts_model):
    client = app_world["client"]
    work = create(client)
    drawn = settings(client, work, by_colour=True)
    before = stored_grey(client, work)
    options = found(client, work)["options"]
    main = options[len(options) // 2]
    coloured = settings(client, work, colour_choice="objects", colouring={"clothes": {"power": main["power"], "shift": 0}})
    assert coloured["colouring"] == {"clothes": {"power": main["power"], "shift": 0.0}} and coloured["undo"] == drawn["undo"] + 1
    (report,) = coloured["picture"]["colour_match"]["objects"]
    assert report["key"] == "clothes" and report["power"] == pytest.approx(main["power"], abs=0.5) and report["path"] >= 2
    assert coloured["picture"]["preview"] != drawn["picture"]["preview"]
    assert found(client, work)["active"] and found(client, work)["objects"][1]["colour"] == {"power": main["power"], "shift": 0.0}
    after = stored_grey(client, work)
    width = after.shape[1]
    assert np.array_equal(after[:, : width // 2 - 4], before[:, : width // 2 - 4])            # face skin: as the drawing has it
    assert not np.array_equal(after[:, width // 2 + 4:], before[:, width // 2 + 4:])
    plan = photo_work._work(client.app.state.store, work["id"])
    greys, labs = grayscale.usable_greys(curve_of(client, work), plan["min_power"], plan["max_power"])
    main_grey = int(np.argmin(np.abs(grayscale.grey_power(greys / 255, plan["min_power"], plan["max_power"]) - main["power"])))
    stretch = set(greys[colouring.path_through(labs, main_grey)].tolist())
    assert set(np.unique(after[:, width // 2 + 4:]).tolist()) <= stretch                      # clothes: only greys of its stretch
    darker = settings(client, work, colouring={"clothes": {"power": main["power"], "shift": -1}})
    assert darker["picture"]["preview"] != coloured["picture"]["preview"]
    back = step(client, work, "undo").json()
    assert back["colouring"] == coloured["colouring"] and back["picture"]["preview"] == coloured["picture"]["preview"]
    back = step(client, work, "undo").json()
    assert (back["colouring"], back["colour_choice"]) == ({}, "drawing") and back["picture"]["preview"] == drawn["picture"]["preview"]


def test_a_theme_colours_every_object_in_one_step_and_a_random_one_by_its_number(app_world, parts_model):
    client = app_world["client"]
    work = create(client)
    warm = client.post(f"/api/photo-works/{work['id']}/theme", json={"name": "warm"})
    assert warm.status_code == 200, warm.text
    warm = warm.json()
    assert (warm["by_colour"], warm["colour_choice"], set(warm["colouring"]), warm["undo"]) == (True, "objects", {"face_skin", "clothes"}, 1)
    powers = {o["power"] for o in found(client, work)["options"]}
    assert all(c["power"] in powers and c["shift"] == 0 for c in warm["colouring"].values())
    assert warm["picture"]["preview"] != work["picture"]["preview"]
    back = step(client, work, "undo").json()
    assert (back["by_colour"], back["colour_choice"], back["colouring"]) == (False, "drawing", {})
    seeds = [client.post(f"/api/photo-works/{work['id']}/theme", json={"name": "random", "seed": s}).json()["colouring"] for s in range(6)]
    assert len({str(sorted(c.items())) for c in seeds}) > 1
    again = client.post(f"/api/photo-works/{work['id']}/theme", json={"name": "random", "seed": 2}).json()
    assert again["colouring"] == seeds[2]                                                         # the same number, the same colours


@pytest.mark.parametrize("body, message", [
    ({"name": "pastel"}, "a theme is one of warm, cool, contrast, random"),
    ({"name": "random", "seed": -1}, "the seed of a random theme is a whole number from 0"),
    ({"name": "random", "seed": "7"}, "the seed of a random theme is a whole number from 0"),
])
def test_a_theme_that_does_not_exist_is_refused(app_world, parts_model, body, message):
    client = app_world["client"]
    work = create(client)
    refused = client.post(f"/api/photo-works/{work['id']}/theme", json=body)
    assert refused.status_code == 422 and refused.json()["error"] == message


def test_a_dot_kind_is_not_coloured_by_objects(app_world, parts_model):
    client = app_world["client"]
    work = create(client)
    settings(client, work, kind="jarvis")
    refused = client.post(f"/api/photo-works/{work['id']}/theme", json={"name": "warm"})
    assert refused.status_code == 422
    assert refused.json()["error"] == "the objects are coloured in grayscale only: a dot kind fires every dot at one power"
    assert not found(client, work)["active"]


@pytest.mark.parametrize("colouring_given, message", [
    ({"dress": {"power": 10}}, "an object is named by its kind (background, hair, face_skin, body_skin, clothes, other, lips, eyes), a background "
                               "piece also by its number"),
    ({"background-x": {"power": 10}}, "an object is named by its kind (background, hair, face_skin, body_skin, clothes, other, lips, eyes), a "
                                      "background piece also by its number"),
    ({"clothes": {"power": 120}}, "an object's colour is a power 0..100 % with lighter or darker -1..1"),
    ({"clothes": {"power": 10, "shift": 2}}, "an object's colour is a power 0..100 % with lighter or darker -1..1"),
    ({"clothes": {"power": True}}, "an object's colour is a power 0..100 % with lighter or darker -1..1"),
    ({"clothes": "gold"}, "an object's colour is a power 0..100 % with lighter or darker -1..1"),
    (["clothes"], "the colours of the objects must be a mapping of at most 32 objects"),
    ({f"background-{n}": {"power": 10} for n in range(1, 34)}, "the colours of the objects must be a mapping of at most 32 objects"),
])
def test_a_colour_of_an_object_that_cannot_be_kept_is_refused_with_the_reason(app_world, colouring_given, message):
    client = app_world["client"]
    work = create(client)
    refused = client.post(f"/api/photo-works/{work['id']}/settings", json={"colouring": colouring_given})
    assert refused.status_code == 422 and refused.json()["error"] == message
    assert client.get(f"/api/photo-works/{work['id']}").json()["colouring"] == {}


# -- the AI's theme -------------------------------------------------------------------------------------------------------------------
def ai_colours(brief):
    """The model's answer: the darkest colour for the clothes, the lightest for the face skin."""
    darkest = min(brief["colours"], key=lambda c: c["lab"][0])
    lightest = max(brief["colours"], key=lambda c: c["lab"][0])
    return {"colours": {"clothes": {"power": darkest["power"], "shift": -0.5}, "face_skin": {"power": lightest["power"]}, "lips": {"power": 1}},
            "note": "платье тёмным, кожа светлая"}


def test_the_ai_gets_the_wish_the_objects_and_the_scales_colours_and_its_colours_are_kept_with_its_note_and_undone(app_world, parts_model, model):
    client = app_world["client"]
    fake = model(ai_colours)
    work = create(client)
    settings(client, work, colour_choice="nearest")
    answer = client.post(f"/api/photo-works/{work['id']}/ai-theme", json={"wish": "  платье тёмным  "})
    assert answer.status_code == 200, answer.text
    done = answer.json()
    brief = sent(fake.calls[0])
    assert brief["wish"] == "платье тёмным" and [o["key"] for o in brief["objects"]] == ["face_skin", "clothes"] and brief["current"] == {}
    assert brief["colours"] == [{"power": c["power"], "lab": c["lab"]} for c in found(client, work)["options"]]
    assert isinstance(fake.calls[0]["input"][0]["content"], str)                                    # numbers only: no picture
    assert (done["by_colour"], done["colour_choice"], set(done["colouring"])) == (True, "objects", {"clothes", "face_skin"})   # no lips here
    assert done["colouring"]["clothes"]["shift"] == -0.5 and done["colouring"]["face_skin"]["shift"] == 0
    assert {k: done["ai_theme"][k] for k in ("wish", "photo", "note")} == {"wish": "платье тёмным", "photo": False, "note": "платье тёмным, кожа светлая"}
    back = step(client, work, "undo").json()
    assert (back["colour_choice"], back["colouring"], back["ai_theme"]) == ("nearest", {}, None)


def test_a_bad_ai_theme_is_sent_back_once_and_a_second_one_changes_nothing(app_world, parts_model, model):
    client = app_world["client"]
    unmeasured = {"colours": {"clothes": {"power": 77.7}}, "note": "?"}
    fake = model(unmeasured, ai_colours)
    work = create(client)
    assert client.post(f"/api/photo-works/{work['id']}/ai-theme", json={"wish": "ярче"}).json()["colour_choice"] == "objects"
    assert "Rejected: the AI chose a colour that is not among the measured colours of this titanium" in fake.calls[1]["input"][2]["content"]
    other = create(client)
    model({"colours": {"clothes": {"power": found(client, other)["options"][0]["power"], "shift": 3}}})
    refused = client.post(f"/api/photo-works/{other['id']}/ai-theme", json={"wish": "ярче"})
    assert refused.status_code == 422 and refused.json()["error"] == "the AI made an object lighter or darker beyond -1..1"
    kept = client.get(f"/api/photo-works/{other['id']}").json()
    assert (kept["colouring"], kept["ai_theme"], kept["undo"]) == ({}, None, 0)
