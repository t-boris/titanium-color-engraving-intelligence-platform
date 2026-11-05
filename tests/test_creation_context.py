"""The shared context of new work, its impact and what a result needs (ux-work-creation-p0 REQ-001, REQ-002).

A new task starts from the workshop's last explicit choice of laser, lens, titanium, rig and measurement source; the choice is only a
start and never changes a work that was made; a change is explained before it is confirmed; and a result whose measurements are missing
is answered with a concrete starter test.
"""
import json

import pytest
from fastapi.testclient import TestClient

from test_grey_scales import app_world, picture_png  # noqa: F401  (a measured grey-ramp plate on one laser, lens and titanium)
from test_lab_sources import lab  # noqa: F401  (a laboratory release connected by a workshop with a laser and titanium of its own)
from test_vector_photo_zones import world  # noqa: F401  (grey scales and flat colours on that laser, lens and titanium)
from titanium_platform import creation_context as cc, devices, lenses, plans
from titanium_platform import setup as su
from titanium_platform.api.app import create_app

TEMPLATE = "jpt-ydflp-e-60-m7-m-r"


def equipped(store, serial="CTX-1", with_lens=True):
    laser = devices.create_from_template(store, TEMPLATE, name="JPT M7", serial=serial)
    lens = None
    if with_lens:
        lens = lenses.create_lens(store, "F-Theta", 174, 170)
        lenses.install(store, laser["id"], lens["id"])
    return laser, lens


@pytest.fixture
def bare(tmp_path):
    """A workshop with one laser carrying a lens, a second laser without one, a lens on no laser, two titanium stocks and no measurement."""
    app = create_app(tmp_path)
    store = app.state.store
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    first, lens = equipped(store)
    second, _ = equipped(store, serial="CTX-2", with_lens=False)
    spare = lenses.create_lens(store, "Spare", 100, 100)
    five = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)
    two = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0)
    with TestClient(app) as client:
        yield {"client": client, "app": app, "store": store, "path": tmp_path, "first": first, "second": second, "lens": lens, "spare": spare,
               "five": five, "two": two}
    store.close()


@pytest.fixture
def measured(world):  # noqa: F811
    """The measured workshop with the shared choice cleared: every test names what it needs."""
    world["store"].set_setting(cc.KEY, {})
    return world


def put(client, **fields):
    return client.put("/api/creation/context", json=fields)


def impact(client, **fields):
    answer = client.post("/api/creation/context/impact", json=fields)
    assert answer.status_code == 200, answer.text
    return answer.json()


def codes(report):
    return [w["code"] for w in report["warnings"]]


# -- the choice ---------------------------------------------------------------------------------------------------------------------
def test_without_a_choice_the_context_is_what_is_there_and_nothing_is_invented(bare):
    context = bare["client"].get("/api/creation/context").json()
    assert (context["device_id"], context["lens_id"], context["lens_basis"]) == (bare["first"]["id"], bare["lens"]["id"], "installed")
    assert context["material_id"] == bare["five"]["id"] and context["capture_setup_id"] is None and context["source"] is None
    assert context["stored"] is False and context["stale"] == [] and context["device"]["passport"] is None            # the passport is no part of a context


def test_an_empty_workshop_has_no_context_and_cannot_start_anything(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        context = client.get("/api/creation/context").json()
        assert context["device_id"] is None and context["lens_id"] is None and context["material_id"] is None and context["device"] is None
        for result in cc.RESULTS:
            answer = client.get("/api/creation/readiness", params={"result": result}).json()
            assert answer["ready"] is False and answer["missing"] == ["laser", "titanium"] and answer["starter_test"] is None
    app.state.store.close()


def test_an_explicit_choice_is_kept_and_found_again_after_a_restart(bare):
    client = bare["client"]
    rig = su.save_capture_setup(bare["store"], "Rig", "cam", "LED", "90", "ColorChecker Classic")
    saved = put(client, device_id=bare["second"]["id"], lens_id=bare["spare"]["id"], material_id=bare["two"]["id"], capture_setup_id=rig["id"])
    assert saved.status_code == 200
    expected = {k: saved.json()[k] for k in ("device_id", "lens_id", "lens_basis", "material_id", "capture_setup_id")}
    assert expected == {"device_id": bare["second"]["id"], "lens_id": bare["spare"]["id"], "lens_basis": "chosen",
                        "material_id": bare["two"]["id"], "capture_setup_id": rig["id"]}
    bare["store"].close()
    app = create_app(bare["path"])
    with TestClient(app) as again:
        kept = again.get("/api/creation/context").json()
        assert {k: kept[k] for k in expected} == expected and kept["stored"] is True
    app.state.store.close()


def test_a_laser_chosen_alone_takes_the_lens_standing_on_it_and_the_unknown_lens_is_a_choice_of_its_own(bare):
    client = bare["client"]
    put(client, lens_id=bare["spare"]["id"])
    assert client.get("/api/creation/context").json()["lens_id"] == bare["spare"]["id"]
    moved = put(client, device_id=bare["second"]["id"]).json()               # the second laser has no lens: the chosen one is not carried over
    assert (moved["lens_id"], moved["lens_basis"]) == (None, "unknown")
    back = put(client, device_id=bare["first"]["id"]).json()
    assert (back["lens_id"], back["lens_basis"]) == (bare["lens"]["id"], "installed")
    unknown = put(client, lens_id="unknown").json()
    assert (unknown["lens_id"], unknown["lens_basis"]) == (None, "unknown")           # chosen, though a lens stands on the laser
    assert put(client, lens_id=None).json()["lens_basis"] == "unknown"
    both = put(client, device_id=bare["second"]["id"], lens_id=bare["lens"]["id"]).json()
    assert (both["device_id"], both["lens_id"], both["lens_basis"]) == (bare["second"]["id"], bare["lens"]["id"], "chosen")


def test_a_choice_that_names_nothing_that_exists_is_refused_and_nothing_is_kept(bare):
    client = bare["client"]
    legacy = su.save_capture_setup(bare["store"], su.LEGACY_SETUP_NAME, "cam", "LED", "90", "ColorChecker Classic")
    expected = {
        "device_id": (999, "the selected laser was not found; choose it again"),
        "lens_id": (999, "the selected lens was not found; choose it again"),
        "material_id": (999, "the selected titanium stock was not found; choose it again"),
        "capture_setup_id": (999, "the selected photography setup was not found; choose it again"),
        "source": ({"release_id": "nope", "laser": "x", "lens": None, "material": "y"}, "this laboratory release is not connected: choose a connected laboratory"),
    }
    for field, (value, message) in expected.items():
        refused = put(client, **{field: value})
        assert refused.status_code == 422 and refused.json()["error"] == message, field
    assert put(client, lens_id="seven").status_code == 422
    placeholder = put(client, capture_setup_id=legacy["id"])
    assert placeholder.status_code == 422 and "placeholder capture setup" in placeholder.json()["error"]
    assert put(client, device_id=bare["first"]["id"], material_id=999).status_code == 422
    assert client.get("/api/creation/context").json()["stored"] is False            # the half that was valid was not kept either


def test_a_record_that_is_gone_is_not_used_and_the_context_says_which_one(bare):
    client, store = bare["client"], bare["store"]
    rig = su.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    put(client, material_id=bare["two"]["id"], capture_setup_id=rig["id"], device_id=bare["second"]["id"], lens_id=bare["spare"]["id"])
    store.execute("DELETE FROM material_profile WHERE id=?", (bare["two"]["id"],))
    store.execute("DELETE FROM capture_setup WHERE id=?", (rig["id"],))
    context = client.get("/api/creation/context").json()
    assert sorted(context["stale"]) == ["capture_setup", "material"]
    assert context["material_id"] == bare["five"]["id"] and context["capture_setup_id"] is None            # the default, not the lost record
    assert context["device_id"] == bare["second"]["id"] and context["lens_id"] == bare["spare"]["id"]        # the rest of the choice stays
    store.execute("DELETE FROM laser_device WHERE id=?", (bare["second"]["id"],))
    again = client.get("/api/creation/context").json()
    assert "device" in again["stale"] and again["device_id"] == bare["first"]["id"] and again["lens_id"] == bare["lens"]["id"]


def test_the_choice_never_changes_a_work_that_was_made(measured):
    client, store = measured["client"], measured["store"]
    made = client.post("/api/photo-works", data={"width_mm": 50, "name": "Own"}, files={"picture": ("g.png", picture_png(), "image/png")}).json()
    before_row = dict(store.one("SELECT * FROM plan WHERE id=?", (made["id"],)))
    before_view = client.get(f"/api/photo-works/{made['id']}").json()
    other, _ = equipped(store, serial="OTHER-1")
    stock = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0)
    assert put(client, device_id=other["id"], lens_id="unknown", material_id=stock["id"]).status_code == 200
    assert dict(store.one("SELECT * FROM plan WHERE id=?", (made["id"],))) == before_row                      # the record is the same bytes
    assert client.get(f"/api/photo-works/{made['id']}").json() == before_view                          # and the work opens with its own setup
    assert before_view["scale"]["device_id"] == measured["laser"]["id"]


# -- what a change does, before it is confirmed -------------------------------------------------------------------------------------
def test_a_change_is_explained_without_being_made(bare):
    client = bare["client"]
    before = client.get("/api/creation/context").json()
    same = impact(client, device_id=bare["first"]["id"], material_id=bare["five"]["id"])
    assert same["changed"] is False and same["warnings"] == []
    lens = impact(client, lens_id="unknown")
    assert lens["changed"] is True and codes(lens) == ["lens_unknown"]
    off = impact(client, lens_id=bare["spare"]["id"])
    assert codes(off) == ["lens_not_installed"] and off["warnings"][0]["lens_id"] == bare["spare"]["id"]
    stock = impact(client, material_id=bare["two"]["id"])
    assert codes(stock) == ["titanium_differs"] and stock["warnings"][0] == {"code": "titanium_differs", "now": bare["five"]["id"], "after": bare["two"]["id"]}
    laser = impact(client, device_id=bare["second"]["id"])                               # a laser with no lens: the unknown lens
    assert "lens_unknown" in codes(laser)
    assert client.get("/api/creation/context").json() == before                         # nothing was kept by asking


def test_a_candidate_that_names_nothing_that_exists_is_refused(bare):
    client = bare["client"]
    for field, value in (("device_id", 999), ("lens_id", 999), ("material_id", 999)):
        answer = client.post("/api/creation/context/impact", json={field: value})
        assert answer.status_code == 422, field


def test_fewer_measured_things_and_none_left_are_told_with_their_numbers(bare, monkeypatch):
    client = bare["client"]
    first, second = bare["first"]["id"], bare["second"]["id"]
    counts = {first: {"photo": 4, "colour": 12, "silhouette": 3, "lines": 2}, second: {"photo": 0, "colour": 5, "silhouette": 3, "lines": 0}}
    monkeypatch.setattr(cc, "measured", lambda store, device_id, lens_id, material_id: dict(counts[device_id]))
    report = impact(client, device_id=second)
    found = {(w["code"], w["result"]): w for w in report["warnings"] if "result" in w}
    assert found[("none_left", "photo")] == {"code": "none_left", "result": "photo", "now": 4}
    assert found[("fewer", "colour")] == {"code": "fewer", "result": "colour", "now": 12, "after": 5}
    assert found[("none_left", "lines")]["now"] == 2 and ("fewer", "silhouette") not in found                 # equal counts are no loss
    assert report["now"] == counts[first] and report["after"] == counts[second]
    gain = impact(client, material_id=bare["two"]["id"])
    assert [w for w in gain["warnings"] if "result" in w] == [] and gain["after"] == counts[first]                # the same counts lose nothing


def test_the_source_that_does_not_serve_is_told_and_leaving_a_source_is_told(bare):
    client = bare["client"]
    gone = {"release_id": "nope", "laser": "x", "lens": None, "material": "y"}
    report = impact(client, source=gone)
    assert codes(report) == ["source_unavailable"] and report["warnings"][0]["detail"] == "this laboratory release is not connected: choose a connected laboratory"
    bare["store"].set_setting(cc.KEY, {"source": gone})                                      # a source that served when it was chosen
    leaving = impact(client, source=None)
    assert codes(leaving) == ["source_dropped"]


# -- what a result needs ------------------------------------------------------------------------------------------------------------
def test_without_measurements_a_photo_work_is_offered_the_grey_scales_and_told_what_they_make_available(bare):
    client = bare["client"]
    answer = client.get("/api/creation/readiness", params={"result": "photo"}).json()
    assert answer["ready"] is False and answer["missing"] == ["measurements"] and answer["measured"] == 0
    assert answer["starter_test"] == {"result": "photo", "needs_rig": True, "becomes": "measured_scale", "device_id": bare["first"]["id"],
                                      "material_id": bare["five"]["id"], "test_type": "grey_scales", "guide": None}
    rig = su.save_capture_setup(bare["store"], "Rig", "cam", "LED", "90", "ColorChecker Classic")
    put(client, capture_setup_id=rig["id"])
    assert client.get("/api/creation/readiness", params={"result": "photo"}).json()["starter_test"]["needs_rig"] is False


def test_without_measurements_a_vector_result_is_offered_the_step_the_experiment_guide_proposes(bare):
    client = bare["client"]
    for result, task in (("colour", "color_image"), ("silhouette", "fill"), ("lines", "line")):
        answer = client.get("/api/creation/readiness", params={"result": result}).json()
        starter = answer["starter_test"]
        assert answer["missing"] == ["measurements"] and starter["becomes"] == "validated_recipes" and starter["task"] == task, result
        assert starter["test_type"] and starter["guide"]["status"] in ("needs_test", "candidate_to_test") and starter["guide"]["next_step"], result
    assert client.get("/api/creation/readiness", params={"result": "lines"}).json()["starter_test"]["test_type"] == "compact_capability"


def test_a_laser_without_a_lens_cannot_make_a_test_and_is_told_so(bare):
    client = bare["client"]
    put(client, device_id=bare["second"]["id"])
    answer = client.get("/api/creation/readiness", params={"result": "photo"}).json()
    assert answer["missing"] == ["lens", "measurements"] and answer["starter_test"] is None


def test_a_result_that_does_not_exist_is_refused(bare):
    answer = bare["client"].get("/api/creation/readiness", params={"result": "painting"})
    assert answer.status_code == 422 and answer.json()["error"] == "choose what the work will be: colour areas, photo engraving, a silhouette or lines"
    assert bare["client"].get("/api/creation/readiness").status_code == 422


def test_the_starter_test_of_a_vector_result_is_made_as_the_guide_proposes_and_not_made_twice(bare):
    client = bare["client"]
    made = client.post("/api/creation/starter-plate", json={"result": "lines"})
    assert made.status_code == 201, made.text
    plan = made.json()
    assert plan["plan_id"] and plan["test_type"] == "compact_capability"
    again = client.post("/api/creation/starter-plate", json={"result": "lines"})
    assert again.status_code == 422                                            # the guide has the next plate made already: continue it
    waiting = client.get("/api/creation/readiness", params={"result": "lines"}).json()["starter_test"]["guide"]
    assert waiting["status"] == "awaiting_photo" and waiting["pending_plan_id"] == plan["plan_id"]


def test_the_grey_scales_are_not_made_here_because_the_dialog_asks_for_their_settings(bare):
    answer = bare["client"].post("/api/creation/starter-plate", json={"result": "photo"})
    assert answer.status_code == 422 and answer.json()["error"] == "the grey scales are made in the test dialog, which asks for their settings"
    assert bare["client"].post("/api/creation/starter-plate", json={"result": "painting"}).status_code == 422


# -- the measured workshop ----------------------------------------------------------------------------------------------------------
def test_the_counts_are_what_the_measurement_routes_of_the_workshop_say(measured):
    client, laser, lens, stock = measured["client"], measured["laser"]["id"], measured["lens"]["id"], measured["titanium"]["id"]
    counts = cc.measured(measured["store"], laser, lens, stock)
    assert counts["photo"] == len(client.get("/api/grey-scales", params={"device_id": laser}).json()["scales"]) == 4
    palette = client.get("/api/vector-palette", params={"device_id": laser, "lens_id": lens, "material_id": stock}).json()
    assert counts["colour"] == len(palette["entries"]) and counts["colour"] >= 1
    recipes = client.get("/api/vector/palette", params={"device_id": laser, "lens_id": lens, "material_id": stock}).json()
    assert counts["silhouette"] == sum(e["mode"] != "Cut" for e in recipes) and counts["lines"] == sum(e["mode"] == "Cut" for e in recipes)
    other = cc.measured(measured["store"], laser, None, stock)                         # the unknown lens is a partition of its own
    assert other["photo"] == 0


def test_a_result_with_measurements_is_ready_and_a_setup_without_them_is_told_what_is_lost(measured):
    client, store = measured["client"], measured["store"]
    ready = client.get("/api/creation/readiness", params={"result": "photo"}).json()
    assert ready["ready"] is True and ready["missing"] == [] and ready["measured"] == 4 and ready["starter_test"] is None
    laser, _ = equipped(store, serial="EMPTY-1")
    report = impact(client, device_id=laser["id"])
    assert any(w["code"] == "none_left" and w["result"] == "photo" and w["now"] == 4 for w in report["warnings"])
    assert report["now"]["photo"] == 4 and report["after"]["photo"] == 0
    put(client, device_id=laser["id"])
    after = client.get("/api/creation/readiness", params={"result": "photo"}).json()
    assert after["missing"] == ["measurements"] and after["starter_test"]["test_type"] == "grey_scales"


# -- a laboratory release as the source -----------------------------------------------------------------------------------------------
def test_a_source_that_serves_is_kept_with_its_label_and_stands_in_for_own_measurements(lab):
    client = lab["client"]
    lab["store"].set_setting(cc.KEY, {})
    label = "Grey lab: Own laser " + "x" * 600
    saved = put(client, source={**lab["source"], "label": label})
    assert saved.status_code == 200, saved.text
    source = saved.json()["source"]
    assert {k: source[k] for k in ("release_id", "laser", "lens", "material")} == lab["source"] and source["label"] == label[:cc.MAX_LABEL]
    for result in ("photo", "colour"):                                                   # these two take the laboratory's scales and colours
        answer = client.get("/api/creation/readiness", params={"result": result}).json()
        assert answer["ready"] is True, result
    own = client.get("/api/creation/readiness", params={"result": "silhouette"}).json()
    assert own["ready"] is False and "measurements" in own["missing"]                         # a silhouette is made from own recipes only
    report = impact(client, source=None)
    assert codes(report) == ["source_dropped"]
    assert put(client, source=None).json()["source"] is None
    assert client.get("/api/creation/readiness", params={"result": "photo"}).json()["ready"] is False


def test_a_source_the_release_did_not_measure_is_refused_and_not_kept(lab):
    client = lab["client"]
    lab["store"].set_setting(cc.KEY, {})
    wrong = {**lab["source"], "laser": "0" * 32}
    refused = put(client, source=wrong)
    assert refused.status_code == 422 and refused.json()["error"] == "choose a laser this release measured"
    assert client.get("/api/creation/context").json()["source"] is None
    assert put(client, source="text").status_code == 422
    assert json.loads(json.dumps(client.get("/api/creation/context").json()))["stored"] is False
