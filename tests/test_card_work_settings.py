"""Business cards and their measured engraving settings (ready-engraving-settings-for-business-cards, REQ-001..005, 022..024, 026): a new card
starts from the best known proposal, a set is chosen from what was measured for the card's own laser, lens and material (never typed first),
typing turns it into Custom, a changed setup replaces what was chosen for the old one, and the LightBurn file carries every field of the
source. The measured data are written as accepted checks store them (``obs``)."""
import json

import pytest
from fastapi.testclient import TestClient

import obs
from titanium_platform import card_work as cw, creation_context as cc, lightburn as lb, setup as su
from titanium_platform.api.app import create_app
from titanium_platform.db import now

LINE = {"power": 12.0, "frequency": 60.0, "speed": 800.0, "pulse_width": 200.0, "passes": 2, "layer_type": "Cut"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    from titanium_platform import research

    def refuse():
        raise RuntimeError("a test must not reach the network")
    monkeypatch.setattr(research, "switched_on", False)
    monkeypatch.setattr(research, "openai_client", refuse)


@pytest.fixture
def world(store):
    w = obs.setup(store)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0)["id"]
    w["other_ti"] = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)["id"]
    cc.save(store, {"device_id": w["setup"][0], "material_id": w["ti"]})
    return w


def colour(store, w, lab, **extra):
    extra.setdefault("speed", 1000)
    extra.setdefault("line_interval", 0.01)
    extra.setdefault("material_id", w["ti"])
    return obs.add(store, w, lab, layer_type="Scan", **extra)


def finding(store, w, parameters=LINE, material_id=None):
    observation = obs.add(store, w, [50.0, 0.0, 0.0], material_id=material_id or w["ti"], layer_type="Cut")     # a line: no colour of the palette
    pair_id = store.one("SELECT pair_id FROM observation WHERE id=?", (observation,))["pair_id"]
    store.execute("INSERT INTO capability_finding(pair_id,purpose,status,summary,parameters_json,evidence_json,next_test,created_at) VALUES (?,?,?,?,?,?,?,?)",
                  (pair_id, "line", "candidate", "A photo-based line candidate.", json.dumps(parameters), "{}", "Repeat it.", now()))


def choices_of(view_or_choices, kind):
    return next(t for t in view_or_choices["types"] if t["type"] == kind)


def first_item(store, plan, kind):
    return choices_of(cw.settings_choices(store, plan), kind)["groups"][0]["items"][0]


def star(store, plan):
    return cw.edit(store, plan, {"op": "add", "side": "front", "element": {"type": "shape", "shape": {"kind": "star"}}})["added"][0]


# -- a new card starts from the best known proposal -------------------------------------------------------------------------------------------
def test_a_new_card_in_a_workshop_that_measured_nothing_says_unknown_and_offers_the_four_types(store, world):
    plan = cw.create(store, "Empty")
    first = cw.view(store, plan)["settings"][0]
    assert first["origin"] is None and first["status"]["state"] == "unknown" and first["power"] is None
    found = cw.settings_choices(store, plan)
    assert [t["type"] for t in found["types"]] == ["color", "photo", "line_text", "deep"] and not any(t["known"] for t in found["types"])


def test_a_new_card_starts_from_the_best_known_proposal_marked_proposed_until_the_operator_confirms_it(store, world):
    finding(store, world)
    plan = cw.create(store, "Proposed")
    first = cw.view(store, plan)["settings"][0]
    assert (first["power"], first["speed"], first["frequency"], first["mode"], first["passes"]) == (12.0, 800.0, 60.0, "line", 2)
    assert first["origin"]["kind"] == "choice" and first["origin"]["type"] == "line_text" and first["origin"]["proposed"] is True
    assert first["confirmed"] is False and first["status"]["state"] == "proposed" and not first["status"]["ready"]
    star(store, plan)
    review = cw.view(store, plan)["review"]["front"]
    assert not review["ready"] and "your confirmation" in review["problems"][0]
    with pytest.raises(su.ValidationError, match="not ready"):
        cw.export(store, plan, "front")
    done = cw.edit(store, plan, {"op": "settings_confirm", "id": 1})
    assert done["settings"][0]["status"]["state"] == "chosen" and done["settings"][0]["origin"]["proposed"] is False
    assert done["review"]["front"]["ready"]
    assert cw.export(store, plan, "front")[0].startswith(b"<?xml")


# -- choosing ---------------------------------------------------------------------------------------------------------------------------
def test_choosing_a_colour_copies_its_values_and_origin_and_is_chosen_at_once(store, world):
    colour(store, world, [60.0, 5.0, 20.0], lightburn={"cross_hatch": True, "bidirectional": False, "global_passes": 2})
    plan = cw.create(store, "Colour")
    item = first_item(store, plan, "color")
    done = cw.edit(store, plan, {"op": "settings_apply", "settings_id": 1, "choice_id": item["id"]})
    chosen = done["settings"][0]
    assert chosen["origin"]["choice_id"] == item["id"] and chosen["origin"]["label"] == item["label"] and chosen["confirmed"] is True
    assert chosen["status"]["state"] == "chosen" and chosen["origin"]["proposed"] is False
    assert (chosen["power"], chosen["speed"], chosen["line_interval"], chosen["mode"]) == (
        item["settings"]["power"], item["settings"]["speed"], item["settings"]["line_interval"], "fill")
    assert (chosen["cross_hatch"], chosen["bidirectional"], chosen["global_passes"]) == (True, False, 2)


def test_what_the_source_does_not_give_stays_unknown_and_a_stale_value_never_stays_behind(store, world):
    finding(store, world)
    colour(store, world, [60.0, 5.0, 20.0], lightburn={"cross_hatch": True})
    plan = cw.create(store, "Switch")
    cw.edit(store, plan, {"op": "settings_apply", "settings_id": 1, "choice_id": first_item(store, plan, "color")["id"]})
    assert cw.view(store, plan)["settings"][0]["cross_hatch"] is True
    cw.edit(store, plan, {"op": "settings_apply", "settings_id": 1, "choice_id": first_item(store, plan, "line_text")["id"]})
    after = cw.view(store, plan)["settings"][0]
    assert after["cross_hatch"] is None and after["line_interval"] is None and after["mode"] == "line"     # nothing of the colour is left


def test_a_choice_that_is_not_measured_for_this_card_is_refused(store, world):
    colour(store, world, [60.0, 5.0, 20.0], material_id=world["other_ti"])
    plan = cw.create(store, "Refuse")
    other = cc.get(store)
    ids = [i["id"] for t in cw.settings_choices(store, plan)["types"] for g in t["groups"] for i in g["items"]]
    assert ids == []
    from titanium_platform import card_settings
    foreign = card_settings.choices(store, {"device_id": other["device_id"], "lens_id": other["lens_id"], "material_id": world["other_ti"]})
    offered = choices_of(foreign, "color")["groups"][0]["items"][0]["id"]
    with pytest.raises(su.ValidationError, match="not measured"):
        cw.edit(store, plan, {"op": "settings_apply", "settings_id": 1, "choice_id": offered})


def test_typing_a_number_into_a_chosen_set_makes_it_custom_and_remembers_where_it_started(store, world):
    finding(store, world)
    plan = cw.create(store, "Custom")
    cw.edit(store, plan, {"op": "settings_confirm", "id": 1})
    typed = cw.edit(store, plan, {"op": "settings_set", "id": 1, "changes": {"power": 15}})["settings"][0]
    assert typed["power"] == 15.0 and typed["speed"] == 800.0                                     # the rest of the numbers stay
    assert typed["origin"]["kind"] == "custom" and typed["origin"]["note"] == "Started from Line candidate." and typed["status"]["state"] == "custom"


def test_marking_a_set_custom_keeps_its_numbers_and_confirms_them(store, world):
    finding(store, world)
    plan = cw.create(store, "Mark")
    custom = cw.edit(store, plan, {"op": "settings_custom", "id": 1})["settings"][0]
    assert custom["origin"]["kind"] == "custom" and custom["confirmed"] and custom["power"] == 12.0 and custom["status"]["state"] == "custom"


def test_a_raster_picture_needs_the_photo_fields_before_its_side_can_be_exported(store, world):
    finding(store, world)
    plan = cw.create(store, "Raster")
    cw.edit(store, plan, {"op": "settings_confirm", "id": 1})
    from test_card_work import png
    added = cw.add_image(store, plan, "front", "dot.png", png())["added"][0]
    cw.edit(store, plan, {"op": "set", "side": "front", "id": added, "changes": {"image": {"engrave": "raster"}}})
    view = cw.view(store, plan)
    picture = next(e for e in view["sides"]["front"]["elements"] if e["id"] == added)
    assert picture["image"]["engrave"] == "raster" and picture["raster"]["url"].startswith(f"/api/card-works/{plan}/elements/{added}/raster.png")
    review = view["review"]["front"]
    assert not review["ready"] and "min power" in review["problems"][0] and "dither" in review["problems"][0]


# -- a changed setup never carries settings over ----------------------------------------------------------------------------------------------
def test_changing_the_material_replaces_what_was_chosen_for_the_old_one_with_the_new_proposal_or_unknown(store, world):
    finding(store, world)                                                                       # known for Grade 2 only
    plan = cw.create(store, "Moves")
    cw.edit(store, plan, {"op": "settings_add", "name": "Second"})
    cw.edit(store, plan, {"op": "settings_confirm", "id": 1})
    cw.edit(store, plan, {"op": "settings_confirm", "id": 2})
    before = cw.view(store, plan)
    assert [s["status"]["state"] for s in before["settings"]] == ["chosen", "chosen"]
    moved = cw.edit(store, plan, {"op": "set_setup", "device_id": world["setup"][0], "lens_id": world["setup"][1], "material_id": world["other_ti"]})
    assert moved["setup"]["material_id"] == world["other_ti"]
    for settings in moved["settings"]:
        assert settings["power"] is None and settings["speed"] is None and settings["origin"] is None            # nothing of Grade 2 is kept
        assert settings["status"]["state"] == "unknown"
    back = cw.edit(store, plan, {"op": "set_setup", "device_id": world["setup"][0], "lens_id": world["setup"][1], "material_id": world["ti"]})
    assert [s["status"]["state"] for s in back["settings"]] == ["proposed", "unknown"]                 # the default set gets the proposal again


def test_the_card_keeps_its_own_setup_when_the_workshops_context_moves_on(store, world):
    finding(store, world)
    plan = cw.create(store, "Own")
    cc.save(store, {"material_id": world["other_ti"]})
    view = cw.view(store, plan)
    assert view["setup"]["material_id"] == world["ti"] and cw.settings_choices(store, plan)["setup"]["material_id"] == world["ti"]
    assert choices_of(cw.settings_choices(store, plan), "line_text")["known"]


# -- the LightBurn file carries every field of the source ----------------------------------------------------------------------------------------
def test_the_file_writes_the_scan_fields_of_the_chosen_colour(store, world):
    colour(store, world, [60.0, 5.0, 20.0], lightburn={"cross_hatch": True, "bidirectional": False, "global_passes": 2, "scan_angle": 15})
    plan = cw.create(store, "File")
    cw.edit(store, plan, {"op": "settings_apply", "settings_id": 1, "choice_id": first_item(store, plan, "color")["id"]})
    star(store, plan)
    layer = lb.parse_bytes(cw.export(store, plan, "front")[0]).layers[0]
    assert (layer.layer_type, layer.cross_hatch, layer.bidirectional, layer.global_passes) == ("Scan", True, False, 2)
    assert layer.scan_angle == 15


# -- the routes ---------------------------------------------------------------------------------------------------------------------------------
def test_the_routes_give_the_choices_of_the_cards_own_setup_and_accept_the_new_edits(tmp_path):
    app = create_app(tmp_path)
    store = app.state.store
    w = obs.setup(store)
    ti = su.save_material(store, "Grade 2 sheet", grade="Grade 2")["id"]
    cc.save(store, {"device_id": w["setup"][0], "material_id": ti})
    w["ti"] = ti
    finding(store, w)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        pid = client.post("/api/card-works", json={"name": "Routes"}).json()["id"]
        found = client.get(f"/api/card-works/{pid}/settings-choices").json()
        assert [t["type"] for t in found["types"]] == ["color", "photo", "line_text", "deep"] and found["setup"]["complete"]
        item = found["types"][2]["groups"][0]["items"][0]
        applied = client.post(f"/api/card-works/{pid}/edit", json={"op": "settings_apply", "settings_id": 1, "choice_id": item["id"]})
        assert applied.status_code == 200 and applied.json()["settings"][0]["status"]["state"] == "chosen"
        bad = client.post(f"/api/card-works/{pid}/edit", json={"op": "settings_apply", "settings_id": 1, "choice_id": "color:nothing"})
        assert bad.status_code == 422
        assert client.get("/api/card-works/9999/settings-choices").status_code == 404
        assert client.get(f"/api/card-works/{pid}/elements/e1/raster.png").status_code == 404


# -- raster pictures (REQ-026) ------------------------------------------------------------------------------------------------------------------
def raster_card(store, world, interval=0.0254):
    """A card with a confirmed set of photo-engraving numbers (a Custom set made from a photo engraving's) and one raster picture on the front."""
    from test_card_work import png
    plan = cw.create(store, "Photo card")
    cw.edit(store, plan, {"op": "settings_set", "id": 1, "changes": {"mode": "fill", "power": 25, "speed": 125, "frequency": 60, "line_interval": interval,
                                                                      "min_power": 8, "dither": "jarvis", "dot_width": 0.02}})
    added = cw.add_image(store, plan, "front", "dot.png", png(80, 50))["added"][0]
    cw.edit(store, plan, {"op": "set", "side": "front", "id": added, "changes": {"image": {"engrave": "raster"}, "width": 30, "height": 18.75}})
    return plan, added


def test_a_raster_picture_is_a_photo_layer_of_the_file_with_the_image_mode_and_dpi_of_its_set(store, world):
    plan, added = raster_card(store, world)
    view = cw.view(store, plan)
    picture = next(e for e in view["sides"]["front"]["elements"] if e["id"] == added)
    assert picture["image"]["engrave"] == "raster" and picture["raster"]["dpi"] == 1000.0 and picture["raster"]["width_px"] == 1181
    assert view["review"]["front"]["ready"] is True, view["review"]["front"]["problems"]
    project = lb.parse_bytes(cw.export(store, plan, "front")[0])
    layer = project.layers[0]
    assert layer.layer_type == "Image" and (layer.power, layer.speed) == (25, 125) and layer.line_interval == 0.0254
    assert len(project.layers) == 1 and [r.kind for r in layer.regions] == ["bitmap"]               # a photo layer holds the bitmap, not shapes
    bitmap = layer.regions[0]
    assert (bitmap.x, bitmap.y, bitmap.width, bitmap.height) == pytest.approx((27.5, 17.125, 30.0, 18.75), abs=0.01)     # where the picture is on the card
    png_bytes = cw.raster_png(store, plan, added)
    assert png_bytes.startswith(b"\x89PNG")


def test_a_traced_picture_and_a_raster_picture_on_one_side_are_two_layers(store, world):
    from test_card_work import png
    plan, added = raster_card(store, world)
    cw.add_image(store, plan, "front", "disc.png", png(60, 40))
    layers = lb.parse_bytes(cw.export(store, plan, "front")[0]).layers
    assert sorted(l.layer_type for l in layers) == ["Image", "Scan"]


def test_a_raster_picture_too_large_for_the_line_interval_says_so_and_blocks_the_export(store, world):
    plan, added = raster_card(store, world, interval=0.01)                                       # 2540 dpi
    cw.edit(store, plan, {"op": "set", "side": "front", "id": added, "changes": {"width": 80, "height": 50}})
    view = cw.view(store, plan)
    picture = next(e for e in view["sides"]["front"]["elements"] if e["id"] == added)
    assert picture["raster"] is None and "pixels" in picture["problems"][0]
    review = view["review"]["front"]
    assert not review["ready"] and "cannot be engraved as a photo" in review["problems"][0]
    with pytest.raises(su.ValidationError, match="not ready"):
        cw.export(store, plan, "front")
    cw.edit(store, plan, {"op": "set", "side": "front", "id": added, "changes": {"width": 30, "height": 18.75}})
    assert cw.view(store, plan)["review"]["front"]["ready"]


def test_the_raster_route_serves_the_dithered_picture(tmp_path):
    app = create_app(tmp_path)
    store = app.state.store
    w = obs.setup(store)
    su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    from test_card_work import png
    with TestClient(app, base_url="http://127.0.0.1") as client:
        pid = client.post("/api/card-works", json={"name": "Raster route"}).json()["id"]
        client.post(f"/api/card-works/{pid}/edit", json={"op": "settings_set", "id": 1, "changes": {
            "power": 25, "speed": 125, "frequency": 60, "line_interval": 0.0254, "min_power": 8, "dither": "jarvis"}})
        up = client.post(f"/api/card-works/{pid}/images", data={"side": "front"}, files={"picture": ("dot.png", png(), "image/png")}).json()
        eid = up["added"][0]
        client.post(f"/api/card-works/{pid}/edit", json={"op": "set", "side": "front", "id": eid, "changes": {"image": {"engrave": "raster"}}})
        got = client.get(f"/api/card-works/{pid}/elements/{eid}/raster.png")
        assert got.status_code == 200 and got.headers["content-type"] == "image/png" and got.content.startswith(b"\x89PNG")
        assert client.get(f"/api/card-works/{pid}/elements/nope/raster.png").status_code == 404
