"""Business card works (feature-2, REQ-001..005): the workspace, its two sides, composition, persistence, undo, the engraving settings, the
physical QR check and the LightBurn file of each side. The shapes, QR codes and pictures themselves are tested in their own modules; here the
work that holds them is."""
import base64
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from titanium_platform import card_generate, card_qr, card_work as cw, catalog, devices, lightburn as lb, research, setup as su
from titanium_platform.api.app import create_app
from titanium_platform.db import Store

TEMPLATE = "jpt-ydflp-e-60-m7-m-r"
SETTINGS = {"power": 30, "speed": 500, "frequency": 40, "line_interval": 0.02}


def png(width=60, height=40, shape="disc") -> bytes:
    """A black disc (or bar) on white, as a PNG."""
    image = np.full((height, width, 3), 255, np.uint8)
    if shape == "disc":
        cv2.circle(image, (width // 2, height // 2), min(width, height) // 3, (0, 0, 0), -1)
    else:
        image[height // 4: 3 * height // 4, width // 8: 7 * width // 8] = 0
    return cv2.imencode(".png", image)[1].tobytes()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """A test never reaches the image service, whatever key this computer holds or whatever a created app makes of the AI switch: the
    client cannot be built unless a test hands the code a fake one."""
    def refuse():
        raise RuntimeError("a test must not reach the network")
    monkeypatch.setattr(research, "switched_on", False)
    monkeypatch.setattr(research, "openai_client", refuse)


@pytest.fixture
def workshop(store):
    devices.create_from_template(store, TEMPLATE, name="JPT M7", serial="CARD-1")
    return store


@pytest.fixture
def card(workshop):
    return cw.create(workshop, "My card")


def add(store, plan_id, side="front", **element):
    return cw.edit(store, plan_id, {"op": "add", "side": side, "element": element})["added"][0]


def element(view, element_id, side="front"):
    return next(e for e in view["sides"][side]["elements"] if e["id"] == element_id)


def ready(store, plan_id):
    cw.edit(store, plan_id, {"op": "settings_set", "id": 1, "changes": SETTINGS})


# -- REQ-001: the workspace ---------------------------------------------------------------------------------------------------------------
def test_a_card_is_made_from_either_preset_or_a_custom_size(workshop):
    assert cw.view(workshop, cw.create(workshop, "a", "85x53"))["size_mm"] == {"width": 85.0, "height": 53.0}
    assert cw.view(workshop, cw.create(workshop, "b", "85x54"))["size_mm"] == {"width": 85.0, "height": 54.0}
    custom = cw.view(workshop, cw.create(workshop, "c", "custom", 60, 40))
    assert custom["size_mm"] == {"width": 60.0, "height": 40.0} and custom["preset"] == "custom"
    assert [p["id"] for p in custom["presets"]] == ["85x53", "85x54"]


@pytest.mark.parametrize("preset,width,height", [("custom", 5, 40), ("custom", 60, 400), ("custom", None, 40), ("custom", "wide", 40),
                                                 ("custom", True, 40), ("90x60", None, None)])
def test_a_bad_card_size_is_refused_with_its_reason(workshop, preset, width, height):
    with pytest.raises(su.ValidationError):
        cw.create(workshop, "x", preset, width, height)


def test_a_card_needs_a_laser(store):
    with pytest.raises(su.ValidationError, match="laser"):
        cw.create(store, "no laser")


def test_both_sides_are_separate_canvases_that_can_be_edited_one_after_the_other(workshop, card):
    front = add(workshop, card, "front", type="text", text={"text": "HO"})
    back = add(workshop, card, "back", type="shape", shape={"kind": "ellipse"})
    view = cw.view(workshop, card)
    assert [e["id"] for e in view["sides"]["front"]["elements"]] == [front]
    assert [e["id"] for e in view["sides"]["back"]["elements"]] == [back]
    cw.edit(workshop, card, {"op": "move", "side": "front", "ids": [front], "dx": 3, "dy": 0})
    assert element(cw.view(workshop, card), back, "back")["x"] == 42.5            # the other side is untouched
    with pytest.raises(su.ValidationError, match="side"):
        cw.edit(workshop, card, {"op": "add", "side": "middle", "element": {"type": "text"}})


def test_the_whole_card_comes_back_after_the_application_restarts(tmp_path):
    first = Store(tmp_path / "data")
    devices.create_from_template(first, TEMPLATE, name="JPT M7", serial="CARD-1")
    plan = cw.create(first, "Persistent", "custom", 70, 45)
    text = add(first, plan, "front", type="text", text={"text": "HOH"})
    qr = add(first, plan, "back", type="qr", qr={"kind": "link", "fields": {"url": "https://example.com/a"}})
    add(first, plan, "front", type="shape", shape={"kind": "star", "points": 6})
    cw.add_image(first, plan, "back", "disc.png", png())
    cw.edit(first, plan, {"op": "settings_add", "name": "Fine"})
    cw.edit(first, plan, {"op": "settings_set", "id": 2, "changes": {**SETTINGS, "mode": "line", "passes": 3}})
    cw.edit(first, plan, {"op": "assign_settings", "side": "front", "ids": [text], "settings_id": 2})
    cw.edit(first, plan, {"op": "rotate", "side": "back", "id": qr, "rotation": 15})
    before = cw.view(first, plan)
    first.close()
    second = Store(tmp_path / "data")
    try:
        after = cw.view(second, plan)
    finally:
        second.close()
    assert after["size_mm"] == {"width": 70.0, "height": 45.0}
    for side in ("front", "back"):
        assert [(e["id"], e["type"], e["x"], e["y"], e["width"], e["height"], e["rotation"], e["d"]) for e in after["sides"][side]["elements"]] == \
               [(e["id"], e["type"], e["x"], e["y"], e["width"], e["height"], e["rotation"], e["d"]) for e in before["sides"][side]["elements"]]
    assert after["settings"] == before["settings"] and after["settings"][1]["mode"] == "line"
    assert element(after, text)["settings_id"] == 2
    # and it can be edited again
    cw.edit(second.__class__(tmp_path / "data"), plan, {"op": "move", "side": "front", "ids": [text], "dx": 1, "dy": 1})


# -- REQ-002: composition and independent editing ---------------------------------------------------------------------------------------
ADDED = [("text", {"text": {"text": "HOH"}}), ("shape", {"shape": {"kind": "rounded_rectangle"}}), ("frame", {"frame": {"style": "double"}}),
         ("icon", {"icon": {"name": "phone"}}), ("qr", {"qr": {"kind": "phone", "fields": {"number": "+1 555 0100"}}})]


@pytest.mark.parametrize("kind,payload", ADDED)
def test_every_kind_of_element_is_drawn_as_engravable_geometry(workshop, card, kind, payload):
    eid = add(workshop, card, type=kind, **payload)
    e = element(cw.view(workshop, card), eid)
    assert e["type"] == kind and e["d"].startswith("M") and not e["empty"] and e["bounds"][2] > e["bounds"][0]
    assert 0 < e["x"] < 85 and 0 < e["y"] < 53


@pytest.mark.parametrize("kind,payload", ADDED)
def test_each_element_can_be_moved_resized_rotated_reordered_duplicated_and_deleted_alone(workshop, card, kind, payload):
    other = add(workshop, card, type="shape", shape={"kind": "rectangle"})
    eid = add(workshop, card, type=kind, **payload)
    base = cw.view(workshop, card)
    untouched = element(base, other)
    moved = cw.edit(workshop, card, {"op": "move", "side": "front", "ids": [eid], "dx": 4.5, "dy": -2})
    assert (element(moved, eid)["x"], element(moved, eid)["y"]) == (element(base, eid)["x"] + 4.5, element(base, eid)["y"] - 2)
    resized = cw.edit(workshop, card, {"op": "resize", "side": "front", "id": eid, "x": 30, "y": 20,
                                       "width": element(base, eid)["width"] * 1.5, "height": element(base, eid)["height"] * 1.5})
    assert (element(resized, eid)["x"], element(resized, eid)["y"]) == (30, 20)
    assert element(resized, eid)["width"] > element(base, eid)["width"] * 1.2
    rotated = cw.edit(workshop, card, {"op": "rotate", "side": "front", "id": eid, "rotation": 270})
    assert element(rotated, eid)["rotation"] == -90
    ordered = cw.edit(workshop, card, {"op": "reorder", "side": "front", "ids": [eid], "to": "back"})
    assert [e["id"] for e in ordered["sides"]["front"]["elements"]] == [eid, other]
    twin = cw.edit(workshop, card, {"op": "duplicate", "side": "front", "ids": [eid]})["added"][0]
    after = cw.view(workshop, card)
    assert element(after, twin)["type"] == kind and twin != eid and element(after, twin)["d"] != element(after, eid)["d"]
    gone = cw.edit(workshop, card, {"op": "delete", "side": "front", "ids": [eid]})
    assert eid not in [e["id"] for e in gone["sides"]["front"]["elements"]] and twin in [e["id"] for e in gone["sides"]["front"]["elements"]]
    assert element(gone, other) == element(base, other) == untouched                # the neighbour never changed


def test_layer_order_can_go_forward_and_backward_one_step(workshop, card):
    a, b, c = (add(workshop, card, type="shape", shape={"kind": "ellipse"}) for _ in range(3))
    order = lambda v: [e["id"] for e in v["sides"]["front"]["elements"]]
    assert order(cw.edit(workshop, card, {"op": "reorder", "side": "front", "ids": [a], "to": "forward"})) == [b, a, c]
    assert order(cw.edit(workshop, card, {"op": "reorder", "side": "front", "ids": [c], "to": "backward"})) == [b, c, a]
    assert order(cw.edit(workshop, card, {"op": "reorder", "side": "front", "ids": [a], "to": "front"})) == [b, c, a]
    assert order(cw.edit(workshop, card, {"op": "reorder", "side": "front", "ids": [a], "to": "back"})) == [a, b, c]
    with pytest.raises(su.ValidationError):
        cw.edit(workshop, card, {"op": "reorder", "side": "front", "ids": [a], "to": "sideways"})


def test_a_text_is_scaled_by_its_height_and_measures_its_own_box(workshop, card):
    eid = add(workshop, card, type="text", text={"text": "HOH", "height_mm": 5})
    small = element(cw.view(workshop, card), eid)
    big = element(cw.edit(workshop, card, {"op": "resize", "side": "front", "id": eid, "x": 40, "y": 25,
                                           "width": small["width"] * 2, "height": small["height"] * 2}), eid)
    assert big["text"]["height_mm"] == pytest.approx(10, rel=0.01) and big["width"] == pytest.approx(small["width"] * 2, rel=0.05)
    edited = element(cw.edit(workshop, card, {"op": "set", "side": "front", "id": eid, "changes": {"text": {"text": "HOH HOH"}}}), eid)
    assert edited["width"] > big["width"]
    empty = element(cw.edit(workshop, card, {"op": "set", "side": "front", "id": eid, "changes": {"text": {"text": " "}}}), eid)
    assert empty["empty"] and "Nothing to engrave" in empty["problems"][0]


def test_a_qr_code_stays_square(workshop, card):
    eid = add(workshop, card, type="qr", qr={"kind": "link", "fields": {"url": "https://example.com"}})
    view = cw.edit(workshop, card, {"op": "resize", "side": "front", "id": eid, "x": 20, "y": 20, "width": 25, "height": 10})
    assert element(view, eid)["width"] == element(view, eid)["height"] == 25


def test_invalid_edits_are_refused_by_name(workshop, card):
    eid = add(workshop, card, type="shape", shape={"kind": "rectangle"})
    for body, words in [({"op": "set", "side": "front", "id": eid, "changes": {"type": "text"}}, "type"),
                        ({"op": "set", "side": "front", "id": eid, "changes": {"width": -3}}, "width"),
                        ({"op": "set", "side": "front", "id": eid, "changes": {"colour": "red"}}, "colour"),
                        ({"op": "set", "side": "front", "id": eid, "changes": {"shape": {"stroke_mm": 99}}}, "line width"),
                        ({"op": "move", "side": "front", "ids": ["e999"], "dx": 1, "dy": 1}, "no longer"),
                        ({"op": "move", "side": "front", "ids": [eid], "dx": "far", "dy": 0}, "shift"),
                        ({"op": "dance", "side": "front"}, "not known")]:
        with pytest.raises(su.ValidationError, match=words):
            cw.edit(workshop, card, body)
    assert element(cw.view(workshop, card), eid)["width"] > 1                       # nothing was half-applied


def test_groups_are_made_split_and_dissolved_with_their_members(workshop, card):
    a, b, c = (add(workshop, card, type="shape", shape={"kind": "ellipse"}) for _ in range(3))
    grouped = cw.edit(workshop, card, {"op": "group", "side": "front", "ids": [a, b]})
    assert element(grouped, a)["group"] == element(grouped, b)["group"] is not None and element(grouped, c)["group"] is None
    twins = cw.edit(workshop, card, {"op": "duplicate", "side": "front", "ids": [a, b]})
    new = cw.view(workshop, card)
    assert element(new, twins["added"][0])["group"] not in (None, element(new, a)["group"])
    after_delete = cw.edit(workshop, card, {"op": "delete", "side": "front", "ids": [b]})
    assert element(after_delete, a)["group"] is None                                 # a group of one is no group
    with pytest.raises(su.ValidationError, match="two"):
        cw.edit(workshop, card, {"op": "group", "side": "front", "ids": [a]})
    again = cw.edit(workshop, card, {"op": "group", "side": "front", "ids": [a, c]})
    ungrouped = cw.edit(workshop, card, {"op": "ungroup", "side": "front", "ids": [a]})
    assert element(again, a)["group"] and element(ungrouped, a)["group"] is None and element(ungrouped, c)["group"] is None


def test_an_element_outside_the_card_is_flagged_but_not_blocked(workshop, card):
    eid = add(workshop, card, type="shape", shape={"kind": "rectangle"})
    view = cw.edit(workshop, card, {"op": "set", "side": "front", "id": eid, "changes": {"x": 84}})
    assert [w["code"] for w in element(view, eid)["warnings"]] == ["outside_card"]


# -- undo and redo ----------------------------------------------------------------------------------------------------------------------
def test_every_change_can_be_undone_and_redone_and_a_new_change_ends_the_redo(workshop, card):
    first = add(workshop, card, type="shape", shape={"kind": "rectangle"})
    second = add(workshop, card, type="shape", shape={"kind": "ellipse"})
    assert cw.view(workshop, card)["can_undo"] and not cw.view(workshop, card)["can_redo"]
    undone = cw.step(workshop, card, "undo")
    assert [e["id"] for e in undone["sides"]["front"]["elements"]] == [first] and undone["can_redo"]
    redone = cw.step(workshop, card, "redo")
    assert [e["id"] for e in redone["sides"]["front"]["elements"]] == [first, second]
    cw.step(workshop, card, "undo")
    add(workshop, card, type="frame", frame={"style": "single"})
    assert not cw.view(workshop, card)["can_redo"]
    with pytest.raises(su.ValidationError, match="redo"):
        cw.step(workshop, card, "redo")
    for _ in range(2):                                                               # nothing, then the rectangle, then the frame
        cw.step(workshop, card, "undo")
    assert cw.view(workshop, card)["sides"]["front"]["elements"] == [] and not cw.view(workshop, card)["can_undo"]
    with pytest.raises(su.ValidationError, match="undo"):
        cw.step(workshop, card, "undo")


def test_undo_takes_back_size_settings_and_pictures_too(workshop, card):
    cw.edit(workshop, card, {"op": "set_size", "preset": "85x54"})
    cw.edit(workshop, card, {"op": "settings_set", "id": 1, "changes": {"power": 55}})
    cw.add_image(workshop, card, "front", "a.png", png())
    cw.step(workshop, card, "undo")
    assert cw.view(workshop, card)["sides"]["front"]["elements"] == []
    cw.step(workshop, card, "undo")
    assert cw.view(workshop, card)["settings"][0]["power"] is None
    cw.step(workshop, card, "undo")
    assert cw.view(workshop, card)["size_mm"]["height"] == 53.0


# -- REQ-003: engraving settings, review and the LightBurn file --------------------------------------------------------------------------
def test_engraving_settings_are_the_operators_and_nothing_is_defaulted(workshop, card):
    first = cw.view(workshop, card)["settings"][0]
    assert first["power"] is None and first["speed"] is None and first["frequency"] is None and first["mode"] == "fill"
    for changes, words in [({"power": 120}, "power"), ({"power": -1}, "power"), ({"speed": 0}, "speed"), ({"frequency": True}, "frequency"),
                           ({"mode": "burn"}, "filling"), ({"passes": 2.5}, "passes"), ({"passes": 0}, "passes"), ({"colour": 1}, "colour"),
                           ({"line_interval": "thin"}, "line interval")]:
        with pytest.raises(su.ValidationError, match=words):
            cw.edit(workshop, card, {"op": "settings_set", "id": 1, "changes": changes})
    ok = cw.edit(workshop, card, {"op": "settings_set", "id": 1, "changes": {**SETTINGS, "pulse_width": 120, "passes": 2}})
    assert ok["settings"][0] == {"id": 1, "name": "Engraving 1", "mode": "fill", **SETTINGS, "pulse_width": 120.0, "passes": 2}


def test_settings_sets_are_added_assigned_and_removed_without_orphans(workshop, card):
    a = add(workshop, card, type="shape", shape={"kind": "rectangle"})
    added = cw.edit(workshop, card, {"op": "settings_add", "name": "Fine text"})
    assert [s["name"] for s in added["settings"]] == ["Engraving 1", "Fine text"]
    assigned = cw.edit(workshop, card, {"op": "assign_settings", "side": "front", "ids": [a], "settings_id": 2})
    assert element(assigned, a)["settings_id"] == 2
    removed = cw.edit(workshop, card, {"op": "settings_delete", "id": 2})
    assert element(removed, a)["settings_id"] is None and [s["id"] for s in removed["settings"]] == [1]
    with pytest.raises(su.ValidationError, match="at least one"):
        cw.edit(workshop, card, {"op": "settings_delete", "id": 1})
    with pytest.raises(su.ValidationError, match="no longer exist"):
        cw.edit(workshop, card, {"op": "assign_settings", "side": "front", "ids": [a], "settings_id": 9})


def test_settings_given_to_a_group_reach_every_member(workshop, card):
    a, b, c = (add(workshop, card, type="shape", shape={"kind": "ellipse"}) for _ in range(3))
    cw.edit(workshop, card, {"op": "group", "side": "front", "ids": [a, b]})
    cw.edit(workshop, card, {"op": "settings_add"})
    view = cw.edit(workshop, card, {"op": "assign_settings", "side": "front", "ids": [a], "settings_id": 2})
    assert [element(view, i)["settings_id"] for i in (a, b, c)] == [2, 2, None]


def test_a_side_is_not_ready_until_its_settings_are_complete_and_the_review_says_what_is_missing(workshop, card):
    empty = cw.view(workshop, card)["review"]["front"]
    assert not empty["ready"] and empty["empty"] and "nothing to engrave" in empty["problems"][0].lower()
    a = add(workshop, card, type="text", text={"text": "H"})
    b = add(workshop, card, type="shape", shape={"kind": "star"})
    review = cw.view(workshop, card)["review"]["front"]
    assert not review["ready"] and review["sets"][0]["missing"] == ["power", "speed", "frequency", "line_interval"]
    assert "power" in review["problems"][0]
    with pytest.raises(su.ValidationError, match="not ready"):
        cw.export(workshop, card, "front")
    cw.edit(workshop, card, {"op": "settings_add", "name": "Text"})
    cw.edit(workshop, card, {"op": "settings_set", "id": 2, "changes": {**SETTINGS, "mode": "line", "power": 10}})
    cw.edit(workshop, card, {"op": "assign_settings", "side": "front", "ids": [a], "settings_id": 2})
    partial = cw.view(workshop, card)["review"]["front"]
    assert [s["complete"] for s in partial["sets"]] == [False, True] and not partial["ready"]
    assert {r["id"]: r["effective_settings_id"] for r in partial["elements"]} == {a: 2, b: 1}
    ready(workshop, card)
    assert cw.view(workshop, card)["review"]["front"]["ready"]
    assert not cw.view(workshop, card)["review"]["back"]["ready"]                   # the other side is prepared on its own


def bounds_of(layer):
    xs = [x for r in layer.regions for x, _ in r.polygon]
    ys = [y for r in layer.regions for _, y in r.polygon]
    return min(xs), min(ys), max(xs), max(ys)


def test_each_side_is_its_own_lightburn_project_with_its_geometry_and_settings(workshop, card):
    text = add(workshop, card, type="text", text={"text": "HOH", "height_mm": 6})
    ring = add(workshop, card, type="frame", frame={"style": "single"})
    star = add(workshop, card, "back", type="shape", shape={"kind": "star", "filled": True})
    ready(workshop, card)
    cw.edit(workshop, card, {"op": "settings_add", "name": "Frame line"})
    cw.edit(workshop, card, {"op": "settings_set", "id": 2, "changes": {"mode": "line", "power": 12.5, "speed": 800, "frequency": 60, "passes": 2}})
    cw.edit(workshop, card, {"op": "assign_settings", "side": "front", "ids": [ring], "settings_id": 2})
    view = cw.view(workshop, card)
    front, name = cw.export(workshop, card, "front")
    back, _ = cw.export(workshop, card, "back")
    assert name == "My card front" and front != back
    project, other = lb.parse_bytes(front), lb.parse_bytes(back)
    assert project.mirror_y is True and project.identifier is None and "Business card front" in project.notes
    assert len(project.layers) == 2 and len(other.layers) == 1                       # different settings on one side: two layers
    fill, line = project.layers
    assert (fill.layer_type, fill.power, fill.speed, fill.frequency_hz, fill.line_interval) == ("Scan", 30, 500, 40000, 0.02)
    assert (line.layer_type, line.power, line.speed, line.frequency_hz, line.passes) == ("Cut", 12.5, 800, 60000, 2)
    assert line.line_interval is None
    # physical geometry: the file's shapes are the element's shapes, in millimetres, on the card
    x0, y0, x1, y1 = bounds_of(fill)
    t = element(view, text)["bounds"]
    assert (x0, y0, x1, y1) == pytest.approx(tuple(t), abs=0.01)
    fx0, fy0, fx1, fy1 = bounds_of(line)
    assert (fx0, fy0, fx1, fy1) == pytest.approx(tuple(element(view, ring)["bounds"]), abs=0.01)
    assert 0 <= fx0 and fx1 <= 85 and 0 <= fy0 and fy1 <= 53
    assert bounds_of(other.layers[0]) == pytest.approx(tuple(element(view, star, "back")["bounds"]), abs=0.01)
    assert any(r.holes for r in line.regions)                                         # a ring keeps its hole


def test_a_rotated_element_is_exported_where_it_is_drawn(workshop, card):
    eid = add(workshop, card, type="shape", shape={"kind": "rectangle", "filled": True}, width=30, height=6, rotation=40)
    ready(workshop, card)
    drawn = element(cw.view(workshop, card), eid)["bounds"]
    layer = lb.parse_bytes(cw.export(workshop, card, "front")[0]).layers[0]
    assert bounds_of(layer) == pytest.approx(tuple(drawn), abs=0.01)
    assert drawn[2] - drawn[0] < 30 and drawn[3] - drawn[1] > 6


def test_the_preview_is_drawn_from_the_same_geometry(workshop, card):
    eid = add(workshop, card, type="shape", shape={"kind": "ellipse", "filled": True})
    svg = cw.preview_svg(workshop, card, "front")
    assert svg.startswith("<svg") and 'viewBox="0 0 85 53"' in svg and element(cw.view(workshop, card), eid)["d"] in svg


# -- REQ-005: QR codes ------------------------------------------------------------------------------------------------------------------
QR_KINDS = [("link", {"url": "https://example.com/card"}), ("text", {"text": "Open on Monday"}),
            ("vcard", {"first_name": "Boris", "last_name": "T", "phone": "+15550100", "email": "b@example.com"}),
            ("wifi", {"ssid": "Workshop", "password": "secret", "security": "WPA"}), ("email", {"address": "b@example.com", "subject": "Hi"}),
            ("phone", {"number": "+1 555 0100"})]


@pytest.mark.parametrize("kind,fields", QR_KINDS)
def test_a_qr_code_of_each_kind_represents_its_content_on_either_side(workshop, card, kind, fields):
    for side in ("front", "back"):
        eid = add(workshop, card, side, type="qr", qr={"kind": kind, "fields": fields})
        info = element(cw.view(workshop, card), eid, side)["qr_info"]
        assert info["content"] == card_qr.payload({"kind": kind, "fields": fields, "ecc": "M"})
        assert info["modules"] >= 21


def test_the_qr_check_warns_about_module_size_and_quiet_zone_but_never_blocks(workshop, card):
    eid = add(workshop, card, type="qr", qr={"kind": "link", "fields": {"url": "https://example.com/a-fairly-long-address/path"}},
              width=8, height=8)
    ready(workshop, card)
    view = cw.view(workshop, card)
    info = element(view, eid)["qr_info"]
    codes = [w["code"] for w in element(view, eid)["warnings"]]
    assert info["module_mm"] < 0.4 and "module_size" in codes
    assert info["thresholds"] == {"module_mm": 0.4, "quiet_modules": 4.0} and "does not guarantee" in info["note"]
    assert cw.view(workshop, card)["review"]["front"]["ready"] and cw.export(workshop, card, "front")[0]       # warnings never block
    # a neighbour two millimetres away leaves less than four modules of quiet zone
    big = cw.edit(workshop, card, {"op": "resize", "side": "front", "id": eid, "x": 42.5, "y": 26.5, "width": 25, "height": 25})
    assert "module_size" not in [w["code"] for w in element(big, eid)["warnings"]]
    neighbour = add(workshop, card, type="shape", shape={"kind": "rectangle", "filled": True}, x=42.5 + 12.5 + 1.0, y=26.5, width=1, height=10)
    near = cw.view(workshop, card)
    assert "quiet_zone" in [w["code"] for w in element(near, eid)["warnings"]]
    cw.edit(workshop, card, {"op": "delete", "side": "front", "ids": [neighbour]})
    assert "quiet_zone" not in [w["code"] for w in element(cw.view(workshop, card), eid)["warnings"]]
    edge = cw.edit(workshop, card, {"op": "move", "side": "front", "ids": [eid], "dx": 40, "dy": 0})
    assert "quiet_zone" in [w["code"] for w in element(edge, eid)["warnings"]]


def test_each_qr_code_is_checked_on_its_own(workshop, card):
    small = add(workshop, card, type="qr", qr={"kind": "text", "fields": {"text": "x" * 60}}, width=7, height=7, x=15, y=15)
    fine = add(workshop, card, type="qr", qr={"kind": "text", "fields": {"text": "hi"}}, width=20, height=20, x=60, y=26)
    view = cw.view(workshop, card)
    assert element(view, small)["warnings"] and not [w for w in element(view, fine)["warnings"] if w["code"] == "module_size"]


# -- pictures: imported, traced, pencil, generated --------------------------------------------------------------------------------------
def test_an_imported_graphic_is_added_traced_and_sized_to_the_card(workshop, card):
    view = cw.add_image(workshop, card, "back", "Logo.png", png(120, 60))
    eid = view["added"][0]
    e = element(view, eid, "back")
    assert e["type"] == "image" and e["name"] == "Logo" and e["image"]["origin"] == "import" and "file" not in e["image"]
    assert e["width"] / e["height"] == pytest.approx(2.0, rel=0.01) and e["width"] <= 30 and not e["empty"] and e["d"]
    with pytest.raises(su.ValidationError):
        cw.add_image(workshop, card, "back", "notes.txt", b"not a picture")
    with pytest.raises(su.ValidationError, match="side"):
        cw.add_image(workshop, card, "top", "a.png", png())


def test_the_pencil_treatment_changes_the_design_before_anything_is_exported(workshop, card):
    eid = cw.add_image(workshop, card, "front", "face.png", png(90, 90))["added"][0]
    plain = element(cw.view(workshop, card), eid)
    pencil = element(cw.edit(workshop, card, {"op": "set", "side": "front", "id": eid, "changes": {"image": {"treatment": "pencil"}}}), eid)
    assert pencil["image"]["treatment"] == "pencil" and pencil["d"] and pencil["d"] != plain["d"]
    inverted = element(cw.edit(workshop, card, {"op": "set", "side": "front", "id": eid, "changes": {"image": {"invert": True}}}), eid)
    assert inverted["d"] != pencil["d"]
    with pytest.raises(su.ValidationError, match="(?i)treatment"):
        cw.edit(workshop, card, {"op": "set", "side": "front", "id": eid, "changes": {"image": {"treatment": "oil"}}})


def test_a_copy_of_a_card_owns_its_pictures(workshop, card):
    eid = cw.add_image(workshop, card, "front", "a.png", png())["added"][0]
    twin = cw.copy_work(workshop, card)
    assert cw.view(workshop, twin)["name"] == "My card copy" and not cw.view(workshop, twin)["can_undo"]
    original = cw._work(workshop, card)["sides"]["front"]["elements"][0]["image"]["file"]
    copied = cw._work(workshop, twin)["sides"]["front"]["elements"][0]["image"]["file"]
    assert original != copied and open(original, "rb").read() == open(copied, "rb").read()
    cw.edit(workshop, twin, {"op": "delete", "side": "front", "ids": [eid]})
    assert len(cw.view(workshop, card)["sides"]["front"]["elements"]) == 1
    assert cw.rename_work(workshop, twin, "  Renamed ") == "Renamed"


class FakeImages:
    def __init__(self, outcome):
        self.calls, self.outcome = [], outcome

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        item = type("Item", (), {"b64_json": base64.b64encode(self.outcome).decode()})()
        return type("Result", (), {"data": [item]})()


class FakeClient:
    def __init__(self, outcome):
        self.images = FakeImages(outcome)

    def with_options(self, **_):
        return self


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setattr(research, "switched_on", True)
    monkeypatch.setattr(research, "ai_available", lambda: True)
    monkeypatch.setattr(research, "ai_library", lambda: True)


def test_generation_adds_the_picture_the_service_returns_as_an_image_element(workshop, card, online, monkeypatch):
    client = FakeClient(png(80, 80))
    monkeypatch.setattr(research, "started_client", lambda: client)
    view = cw.generate(workshop, card, "front", "a small fox", "icon")
    e = element(view, view["added"][0])
    assert e["image"]["origin"] == "generated" and e["image"]["prompt"] == "a small fox" and not e["empty"] and e["name"] == "A small fox"
    sent = client.images.calls[0]
    assert sent["model"] == card_generate.DEFAULT_MODEL and "a small fox" in sent["prompt"] and sent["size"] == "1024x1024"
    assert "icon" in sent["prompt"].lower()
    cw.generate(workshop, card, "back", "an oak tree", "drawing")
    assert "pencil" in client.images.calls[1]["prompt"].lower()


def test_generation_says_what_is_missing_and_the_rest_of_the_card_keeps_working(workshop, card, monkeypatch):
    monkeypatch.setattr(research, "switched_on", False)
    assert cw.view(workshop, card)["generation"] == {"available": False, "reason": "The AI switch is off: turn it on in the network settings to generate pictures."}
    with pytest.raises(su.ValidationError, match="AI switch"):
        cw.generate(workshop, card, "front", "a small fox", "icon")
    monkeypatch.setattr(research, "switched_on", True)
    monkeypatch.setattr(research, "ai_available", lambda: False)
    assert "key" in cw.view(workshop, card)["generation"]["reason"]
    assert add(workshop, card, type="text", text={"text": "still works"})


def test_generation_reports_an_unreachable_service_and_a_refused_description(workshop, card, online, monkeypatch):
    import httpx
    import openai
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    for error, words in [(openai.APIConnectionError(request=request), "internet"),
                         (openai.AuthenticationError("no", response=httpx.Response(401, request=request), body=None), "key was refused"),
                         (openai.BadRequestError("bad", response=httpx.Response(400, request=request), body=None), "describe the picture differently")]:
        monkeypatch.setattr(research, "started_client", lambda e=error: FakeClient(e))
        with pytest.raises(su.ValidationError, match=words):
            cw.generate(workshop, card, "front", "a small fox", "icon")
    with pytest.raises(su.ValidationError, match="characters"):
        cw.generate(workshop, card, "front", "x", "icon")
    with pytest.raises(su.ValidationError, match="icon or a drawing"):
        cw.generate(workshop, card, "front", "a small fox", "photo")
    assert cw.view(workshop, card)["sides"]["front"]["elements"] == []


# -- the catalog and the API ------------------------------------------------------------------------------------------------------------
def test_a_card_is_listed_with_the_other_works(workshop, card):
    entry = next(e for e in catalog.all_works(workshop) if e["key"] == f"card-{card}")
    assert entry["kind"] == entry["type"] == "card" and entry["name"] == "My card" and (entry["width_mm"], entry["height_mm"]) == (85.0, 53.0)
    assert entry["open"] == f"/card-work?work={card}" and entry["base"] == "/card-works" and f"/api/card-works/{card}/thumb.svg" in entry["thumb"]
    assert "card" in catalog.list_works(workshop)["facets"]["type"]
    assert catalog.list_works(workshop, type="card")["total"] == 1 and catalog.list_works(workshop, type="photo")["total"] == 0


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    devices.create_from_template(app.state.store, TEMPLATE, name="JPT M7", serial="API-1")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_the_api_carries_a_card_from_creation_to_the_files_of_both_sides(client):
    made = client.post("/api/card-works", json={"name": "API card", "preset": "85x54"})
    assert made.status_code == 201
    pid = made.json()["id"]
    library = client.get("/api/card-library").json()
    assert {"shape", "frame", "icon", "qr", "image", "presets"} <= set(library) and library["qr"]["thresholds"]["quiet_modules"] == 4.0
    added = client.post(f"/api/card-works/{pid}/edit", json={"op": "add", "side": "front", "element": {"type": "shape", "shape": {"kind": "star"}}})
    assert added.status_code == 200 and added.json()["added"] == ["e1"]
    upload = client.post(f"/api/card-works/{pid}/images", data={"side": "back"}, files={"picture": ("dot.png", png(), "image/png")})
    assert upload.status_code == 200 and upload.json()["added"] == ["e2"]
    assert client.post(f"/api/card-works/{pid}/edit", json={"op": "add", "side": "front", "element": {"type": "star"}}).status_code == 422
    assert client.get(f"/api/card-works/{pid}/sides/front/export.lbrn2").status_code == 422
    for settings_id in (1,):
        client.post(f"/api/card-works/{pid}/edit", json={"op": "settings_set", "id": settings_id, "changes": SETTINGS})
    for side in ("front", "back"):
        file = client.get(f"/api/card-works/{pid}/sides/{side}/export.lbrn2")
        assert file.status_code == 200 and b"LightBurnProject" in file.content and ".lbrn2" in file.headers["content-disposition"]
        assert client.get(f"/api/card-works/{pid}/sides/{side}/preview.svg").headers["content-type"].startswith("image/svg+xml")
    assert client.get(f"/api/card-works/{pid}/thumb.svg").status_code == 200
    assert client.post(f"/api/card-works/{pid}/undo").json()["can_redo"]
    assert client.post(f"/api/card-works/{pid}/redo").status_code == 200
    assert client.post(f"/api/card-works/{pid}/rename", json={"name": "Renamed"}).json() == {"name": "Renamed"}
    copy = client.post(f"/api/card-works/{pid}/copy", json={}).json()
    assert copy["id"] != pid and copy["name"] == "Renamed copy"
    assert [c["name"] for c in client.get("/api/card-works").json()][:1] == ["Renamed copy"]
    works = client.get("/api/works", params={"type": "card"}).json()
    assert works["total"] == 2
    assert client.delete(f"/api/plans/{pid}").status_code == 204
    assert client.get(f"/api/card-works/{pid}").status_code == 404
    assert client.get("/api/works", params={"type": "card"}).json()["total"] == 1
    assert client.get(f"/api/card-works/{pid}/sides/middle/preview.svg").status_code in (404, 422)
    assert client.post("/api/card-works", json={"preset": "custom", "width_mm": 2, "height_mm": 2}).status_code == 422
    assert client.post(f"/api/card-works/{copy['id']}/generate", json={"side": "front", "description": "a fox", "kind": "icon"}).status_code == 422
