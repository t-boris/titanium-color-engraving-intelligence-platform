"""Vector artwork on a business card (feature-3, REQ-003..005; DEC-001..003): an imported file becomes a group of editable parts with design
colours, the engraving colours that go with them are suggested from what the workshop measured (never from another setup), the parts are edited
like any element, everything survives saving, copying and undo, and the LightBurn file carries the chosen engraving colours.

The readers of the two formats are tested in their own files (test_card_vector_svg.py, test_card_vector_ai.py); here the file is a stand-in that
hands over shapes, so that what is read is the work that holds them. One test at the end runs a real SVG through the whole path."""
import numpy as np
import pytest
from shapely.geometry import box

import obs
from titanium_platform import card_settings, card_vector as cvx, card_work as cw, creation_context as cc, lightburn as lb, setup as su
from titanium_platform.card_vector_geometry import Parsed, Shape

SETTINGS = {"power": 30, "speed": 500, "frequency": 40, "line_interval": 0.02}


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
    cc.save(store, {"device_id": w["setup"][0], "material_id": w["ti"]})
    return w


def measured(store, w, lab, power=10):
    """A colour the workshop measured on the card's own titanium; each needs settings of its own, as the palette keeps colours apart by them."""
    obs.add(store, w, lab, power=power, layer_type="Scan", speed=1000, line_interval=0.01, material_id=w["ti"], engraving=f"m{power}")


def dog():
    """A body (brown), an ear (dark), an eye (black) over the body and a white page behind all: 40 × 25 mm."""
    return Parsed([Shape(box(0, 0, 40, 25), "#ffffff", "page"), Shape(box(2, 5, 38, 25), "#a05a2c", "body"), Shape(box(30, 0, 38, 10), "#3a2a20", "ear"),
                   Shape(box(10, 8, 14, 12), "#000000", "path123")], ["2 text objects were not imported: convert the text to outlines in the program that made the file."], "svg")


def importing(store, plan, parsed=None, monkeypatch=None, side="front", name="dog.svg"):
    monkeypatch.setattr(cvx, "read", lambda data, file_name="": parsed or dog())
    return cw.import_vector(store, plan, side, name, b"<svg/>")


def elements(view, side="front"):
    return view["sides"][side]["elements"]


@pytest.fixture
def card(store, world):
    return cw.create(store, "Card")


# -- REQ-003: import --------------------------------------------------------------------------------------------------------------------
def test_an_imported_file_becomes_one_group_of_parts_with_their_design_colours(store, card, monkeypatch):
    view = importing(store, card, monkeypatch=monkeypatch)
    parts = elements(view)
    assert [e["type"] for e in parts] == ["vector"] * 3 and view["added"] == [e["id"] for e in parts]
    assert [e["vector"]["fill"] for e in parts] == ["#a05a2c", "#3a2a20", "#000000"] and [e["color"] for e in parts] == ["#a05a2c", "#3a2a20", "#000000"]
    assert len({e["group"] for e in parts}) == 1 and parts[0]["group"]
    assert [e["name"] for e in parts] == ["body", "ear", "dog 3"], "a name the file gives is kept; a generated id is not a name"
    assert all(e["d"] and not e["problems"] for e in parts)
    report = view["import"]
    assert report["parts"] == 3 and report["colours"] == 3 and report["kind"] == "svg" and report["background"] is True
    assert "A white background in the file was left out." in report["notes"] and any("text objects" in n for n in report["notes"])


def test_the_drawing_is_centred_on_the_card_and_fitted_to_it(store, card, monkeypatch):
    parts = elements(importing(store, card, monkeypatch=monkeypatch))
    x0 = min(e["x"] - e["width"] / 2 for e in parts)
    x1 = max(e["x"] + e["width"] / 2 for e in parts)
    y0 = min(e["y"] - e["height"] / 2 for e in parts)
    y1 = max(e["y"] + e["height"] / 2 for e in parts)
    assert (x0 + x1) / 2 == pytest.approx(42.5, abs=0.01) and (y0 + y1) / 2 == pytest.approx(26.5, abs=0.01)
    assert (x1 - x0, y1 - y0) == pytest.approx((36.0, 25.0), abs=0.01), "36 × 25 mm is a size a card can have: it keeps its size"
    big = Parsed([Shape(box(0, 0, 500, 300), "#102030")], [], "svg")
    wide = elements(importing(store, card, big, monkeypatch, name="big.svg"))[-1]
    assert max(wide["width"], wide["height"]) == pytest.approx(30.0, abs=0.01), "a drawing far from card size is fitted to 30 mm"
    tiny = Parsed([Shape(box(0, 0, 3, 3), "#102030")], [], "svg")
    icon = elements(importing(store, card, tiny, monkeypatch, name="icon.svg"))[-1]
    assert icon["width"] == pytest.approx(30.0, abs=0.01) or icon["width"] <= 49.0


def test_a_part_is_a_path_of_the_file_and_its_geometry_is_the_drawn_shape(store, card, monkeypatch):
    view = importing(store, card, monkeypatch=monkeypatch)
    body = elements(view)[0]
    assert body["bounds"][2] - body["bounds"][0] == pytest.approx(36.0, abs=0.01) and body["bounds"][3] - body["bounds"][1] == pytest.approx(20.0, abs=0.01)
    assert body["width"] == pytest.approx(36.0, abs=0.01) and body["height"] == pytest.approx(20.0, abs=0.01)


def test_specks_too_small_to_engrave_are_dropped_and_the_operator_is_told(store, card, monkeypatch):
    parsed = Parsed([Shape(box(0, 0, 40, 25), "#112233"), Shape(box(1, 1, 1.005, 1.005), "#445566")], [], "svg")
    view = importing(store, card, parsed, monkeypatch)
    assert len(elements(view)) == 1 and view["import"]["dropped"] == 1 and any("could not be engraved" in n for n in view["import"]["notes"])


def test_parts_of_one_colour_are_merged_only_when_the_side_has_no_room_and_it_is_said(store, card, monkeypatch):
    monkeypatch.setattr(cw, "MAX_ELEMENTS", 4)
    cw.edit(store, card, {"op": "add", "side": "front", "element": {"type": "text"}})
    parsed = Parsed([Shape(box(0, 0, 10, 10), "#aa0000"), Shape(box(11, 0, 21, 10), "#aa0000"), Shape(box(22, 0, 32, 10), "#00aa00"), Shape(box(33, 0, 40, 10), "#aa0000")], [], "svg")
    view = importing(store, card, parsed, monkeypatch)
    assert [e["vector"]["fill"] for e in elements(view)[1:]] == ["#aa0000", "#00aa00", "#aa0000"] and view["import"]["merged"] == 1
    assert any("were merged" in n for n in view["import"]["notes"])
    with pytest.raises(su.ValidationError, match="room"):
        importing(store, cw.create(store, "Other"), Parsed([Shape(box(i * 5, 0, i * 5 + 4, 4), f"#{i:02x}0000") for i in range(1, 6)], [], "svg"), monkeypatch)


def test_a_long_run_of_one_colour_is_united_at_once_not_piece_by_piece(store, card, monkeypatch):
    """A CorelDRAW card of 927 pieces took minutes when each piece was united with everything before it."""
    import time
    pieces = [Shape(box(i * 0.5, 0, i * 0.5 + 0.6, 6 + (i % 7) * 0.1), "#aa0000" if i < 900 else "#0000aa") for i in range(1000)]
    started = time.monotonic()
    view = importing(store, card, Parsed(pieces, [], "svg"), monkeypatch)
    assert time.monotonic() - started < 20
    assert [e["vector"]["fill"] for e in elements(view)] == ["#aa0000", "#0000aa"] and view["import"]["merged"] == 998
    assert elements(view)[0]["width"] > 8 * elements(view)[1]["width"], "the first colour is the long run of 900 pieces, the second the last 100"


def test_a_file_that_gives_nothing_to_engrave_or_cannot_be_read_is_refused_with_the_reason(store, card, monkeypatch):
    with pytest.raises(su.ValidationError, match="nothing to engrave"):
        importing(store, card, Parsed([], ["1 picture was not imported."], "svg"), monkeypatch)
    monkeypatch.undo()
    with pytest.raises(su.ValidationError, match="not an SVG or Adobe Illustrator file"):
        cw.import_vector(store, card, "front", "x.txt", b"hello")
    with pytest.raises(su.ValidationError, match="PDF-compatible"):
        cw.import_vector(store, card, "front", "old.ai", b"%!PS-Adobe-3.0\n%%Creator: Adobe Illustrator\n")
    with pytest.raises(su.ValidationError, match="empty"):
        cw.import_vector(store, card, "front", "x.svg", b"")
    assert elements(cw.view(store, card)) == []


def test_a_vector_part_cannot_be_added_without_an_imported_file(store, card):
    with pytest.raises(su.ValidationError, match="import the file"):
        cw.edit(store, card, {"op": "add", "side": "front", "element": {"type": "vector"}})


# -- REQ-005: the parts are edited like any element, and it is all saved ------------------------------------------------------------------------
def test_parts_are_selected_moved_resized_rotated_duplicated_ordered_grouped_and_deleted_one_by_one(store, card, monkeypatch):
    view = importing(store, card, monkeypatch=monkeypatch)
    body, ear, eye = elements(view)
    moved = cw.edit(store, card, {"op": "move", "side": "front", "ids": [ear["id"]], "dx": 3.0, "dy": -1.0})
    assert elements(moved)[1]["x"] == pytest.approx(ear["x"] + 3.0) and elements(moved)[0]["x"] == body["x"]
    resized = cw.edit(store, card, {"op": "resize", "side": "front", "id": eye["id"], "width": 8.0, "height": 2.0})
    assert (elements(resized)[2]["width"], elements(resized)[2]["height"]) == (8.0, 2.0)
    bounds = elements(resized)[2]["bounds"]
    assert bounds[2] - bounds[0] == pytest.approx(8.0, abs=0.01) and bounds[3] - bounds[1] == pytest.approx(2.0, abs=0.01), "the drawing is stretched to the box"
    turned = cw.edit(store, card, {"op": "rotate", "side": "front", "id": eye["id"], "rotation": 90})
    assert elements(turned)[2]["rotation"] == 90 and elements(turned)[2]["vector"]["fill"] == "#000000"
    twin = cw.edit(store, card, {"op": "duplicate", "side": "front", "ids": [ear["id"]]})
    assert len(elements(twin)) == 4 and elements(twin)[3]["vector"] == elements(twin)[1]["vector"] and elements(twin)[3]["name"] == "ear copy"
    ordered = cw.edit(store, card, {"op": "reorder", "side": "front", "id": body["id"], "to": "front"})
    assert elements(ordered)[-1]["id"] == body["id"]
    ungrouped = cw.edit(store, card, {"op": "ungroup", "side": "front", "ids": [body["id"]]})
    assert all(e["group"] is None for e in elements(ungrouped))
    regrouped = cw.edit(store, card, {"op": "group", "side": "front", "ids": [body["id"], ear["id"]]})
    assert sum(1 for e in elements(regrouped) if e["group"]) == 2
    gone = cw.edit(store, card, {"op": "delete", "side": "front", "ids": [ear["id"], twin["added"][0]]})
    assert [e["id"] for e in elements(gone)] == [eye["id"], body["id"]]


def test_the_parts_their_edits_and_colours_survive_saving_reopening_and_copying_the_card(store, card, monkeypatch):
    view = importing(store, card, monkeypatch=monkeypatch)
    body, ear, eye = elements(view)
    cw.edit(store, card, {"op": "recolour", "side": "front", "ids": [ear["id"]], "fill": "#C0A080"})
    cw.edit(store, card, {"op": "move", "side": "front", "ids": [eye["id"]], "dx": 1.0, "dy": 1.0})
    again = cw.view(store, card)
    assert [e["vector"]["fill"] for e in elements(again)] == ["#a05a2c", "#c0a080", "#000000"] and elements(again)[1]["vector"]["source"] == "#3a2a20"
    assert elements(again)[2]["x"] == pytest.approx(eye["x"] + 1.0) and [e["d"] for e in elements(again)] == [e["d"] for e in elements(cw.view(store, card))]
    copy = cw.view(store, cw.copy_work(store, card, "Twin"))
    assert [e["d"] for e in elements(copy)] == [e["d"] for e in elements(again)] and [e["vector"]["fill"] for e in elements(copy)] == [e["vector"]["fill"] for e in elements(again)]


def test_importing_is_one_change_that_undo_takes_back_whole_with_the_engraving_colours_it_chose(store, world, monkeypatch):
    measured(store, world, [60.0, 30.0, 40.0], power=15)
    card = cw.create(store, "Card")
    view = importing(store, card, monkeypatch=monkeypatch)
    assert view["can_undo"] and len(view["settings"]) >= 2
    undone = cw.step(store, card, "undo")
    assert elements(undone) == [] and len(undone["settings"]) == 1
    redone = cw.step(store, card, "redo")
    assert len(elements(redone)) == 3 and len(redone["settings"]) == len(view["settings"])


# -- REQ-004: design colours and engraving colours -----------------------------------------------------------------------------------------
def test_a_design_colour_is_changed_for_parts_and_reset_to_the_colour_of_the_file(store, card, monkeypatch):
    body, ear, eye = elements(importing(store, card, monkeypatch=monkeypatch))
    many = cw.edit(store, card, {"op": "recolour", "side": "front", "ids": [body["id"], ear["id"]], "fill": "#abc"})
    assert [e["vector"]["fill"] for e in elements(many)] == ["#aabbcc", "#aabbcc", "#000000"] and [e["color"] for e in elements(many)] == ["#aabbcc", "#aabbcc", "#000000"]
    one = cw.edit(store, card, {"op": "set", "side": "front", "id": ear["id"], "changes": {"vector": {"fill": "#112233"}}})
    assert elements(one)[1]["vector"]["fill"] == "#112233"
    back = cw.edit(store, card, {"op": "recolour", "side": "front", "ids": [body["id"], ear["id"]], "reset": True})
    assert [e["vector"]["fill"] for e in elements(back)] == ["#a05a2c", "#3a2a20", "#000000"]
    assert elements(back)[0]["vector"]["source"] == "#a05a2c", "the colour of the file is kept as a design colour"
    for bad in ("red", "#12", "#gggggg", None, 5):
        with pytest.raises(su.ValidationError, match="design colour"):
            cw.edit(store, card, {"op": "recolour", "side": "front", "ids": [body["id"]], "fill": bad})
    with pytest.raises(su.ValidationError, match="only the design colour"):
        cw.edit(store, card, {"op": "set", "side": "front", "id": ear["id"], "changes": {"vector": {"part": 0}}})
    text = cw.edit(store, card, {"op": "add", "side": "front", "element": {"type": "text"}})["added"][0]
    with pytest.raises(su.ValidationError, match="vector parts"):
        cw.edit(store, card, {"op": "recolour", "side": "front", "ids": [text], "fill": "#112233"})


def test_the_close_measured_engraving_colours_are_chosen_at_import_and_the_far_ones_are_left_to_the_operator(store, world, monkeypatch):
    measured(store, world, [43.0, 25.0, 33.0])                  # about the brown of the body
    measured(store, world, [10.0, 0.0, 0.0], power=20)           # near black
    card = cw.create(store, "Card")
    view = importing(store, card, monkeypatch=monkeypatch)
    body, ear, eye = elements(view)
    engraving = view["import"]["engraving"]
    assert engraving["available"] is True and engraving["colours"] == 3 and engraving["assigned"] >= 2
    assert body["settings_id"] is not None and eye["settings_id"] is not None
    sets = {s["id"]: s for s in view["settings"]}
    assert sets[body["settings_id"]]["origin"]["kind"] == "choice" and sets[body["settings_id"]]["origin"]["type"] == "color"
    assert sets[body["settings_id"]]["confirmed"] is True and body["settings_id"] != eye["settings_id"]
    answer = cw.colour_matches(store, card, ["#a05a2c", "#00ff00"])
    assert answer["available"] is True and answer["close_delta_e"] == cvx.CLOSE_DELTA_E
    near, far = answer["matches"]["#a05a2c"], answer["matches"]["#00ff00"]
    assert near["close"] is True and near["best"]["delta_e"] <= cvx.CLOSE_DELTA_E and near["best"]["swatch"].startswith("#") and near["best"]["choice_id"].startswith("color:")
    assert far["close"] is False and far["best"] is not None, "the nearest measured colour is still named, with its distance"
    assert far["best"]["delta_e"] > cvx.CLOSE_DELTA_E


def test_with_nothing_measured_the_colours_stay_design_colours_and_the_reason_is_told(store, card, monkeypatch):
    view = importing(store, card, monkeypatch=monkeypatch)
    engraving = view["import"]["engraving"]
    assert engraving["available"] is False and "No colour is measured" in engraving["reason"] and engraving["assigned"] == 0
    assert all(e["settings_id"] is None for e in elements(view)) and len(view["settings"]) == 1
    answer = cw.colour_matches(store, card, ["#a05a2c"])
    assert answer["available"] is False and answer["matches"]["#a05a2c"] == {"best": None, "close": False, "alternatives": []}


def test_the_suggestions_come_only_from_the_cards_own_laser_lens_and_material(store, world, card, monkeypatch):
    other = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)["id"]
    obs.add(store, world, [43.0, 25.0, 33.0], layer_type="Scan", speed=1000, line_interval=0.01, material_id=other)
    assert cw.colour_matches(store, card, ["#a05a2c"])["available"] is False, "a colour measured on another titanium is never offered"
    assert importing(store, card, monkeypatch=monkeypatch)["import"]["engraving"]["assigned"] == 0


def test_the_engraving_colour_the_operator_chooses_is_kept_apart_from_the_design_colour(store, world, monkeypatch):
    measured(store, world, [43.0, 25.0, 33.0])
    measured(store, world, [70.0, -5.0, 60.0], power=30)
    card = cw.create(store, "Card")
    view = importing(store, card, monkeypatch=monkeypatch)
    body, ear, eye = elements(view)
    gold = card_settings.colour_items(store, cw._setup(cw._work(store, card)))
    other = next(i for i in gold if i["id"] != cw.colour_matches(store, card, ["#a05a2c"])["matches"]["#a05a2c"]["best"]["choice_id"])
    changed = cw.edit(store, card, {"op": "assign_choice", "side": "front", "ids": [body["id"]], "choice_id": other["id"], "only": True})
    assert elements(changed)[0]["vector"]["fill"] == "#a05a2c", "choosing an engraving colour does not recolour the design"
    assert elements(changed)[0]["settings_id"] != body["settings_id"] and elements(changed)[1]["settings_id"] == ear["settings_id"], "only the part chosen changes"


# -- DEC-003: the chosen engraving colours reach the LightBurn file -------------------------------------------------------------------------
def test_the_exported_side_has_a_layer_for_each_chosen_engraving_colour_with_its_parts_in_it(store, world, monkeypatch):
    measured(store, world, [43.0, 25.0, 33.0])
    measured(store, world, [10.0, 0.0, 0.0], power=20)
    card = cw.create(store, "Card")
    view = importing(store, card, monkeypatch=monkeypatch)
    body, ear, eye = elements(view)
    assert body["settings_id"] is not None and eye["settings_id"] is not None and body["settings_id"] != eye["settings_id"]
    assert view["review"]["front"]["ready"], "the colours chosen at import are complete settings of the workshop's own measurements"
    project = lb.parse_bytes(cw.export(store, card, "front")[0])
    used = {body["settings_id"], ear["settings_id"], eye["settings_id"]}
    assert len(project.layers) == len(used) and sorted(layer.power for layer in project.layers) == sorted({10.0, 20.0})
    assert sum(len(layer.regions) for layer in project.layers) == 3, "every part is a shape of the file"


def test_the_layers_of_a_side_follow_the_engraving_settings_of_its_vector_parts(store, world, card, monkeypatch):
    view = importing(store, card, monkeypatch=monkeypatch)
    body, ear, eye = elements(view)
    cw.edit(store, card, {"op": "settings_set", "id": 1, "changes": SETTINGS})
    second = cw.edit(store, card, {"op": "settings_add"})["settings"][-1]["id"]
    cw.edit(store, card, {"op": "settings_set", "id": second, "changes": {**SETTINGS, "power": 55}})
    cw.edit(store, card, {"op": "assign_settings", "side": "front", "ids": [eye["id"]], "settings_id": second, "only": True})
    project = lb.parse_bytes(cw.export(store, card, "front")[0])
    assert [layer.power for layer in project.layers] == [30, 55] and [len(layer.regions) for layer in project.layers] == [2, 1]
    drawn = elements(cw.view(store, card))[2]["bounds"]
    assert drawn[2] - drawn[0] == pytest.approx(4.0, abs=0.01), "the eye is where it is drawn, 4 mm wide"


# -- scale ----------------------------------------------------------------------------------------------------------------------------
def test_a_selection_is_scaled_about_its_centre_as_one_change(store, card, monkeypatch):
    view = importing(store, card, monkeypatch=monkeypatch)
    before = elements(view)
    ids = [e["id"] for e in before]
    after = elements(cw.edit(store, card, {"op": "scale", "side": "front", "ids": ids, "factor": 0.5}))
    for was, now in zip(before, after):
        assert now["width"] == pytest.approx(was["width"] / 2, abs=0.01) and now["height"] == pytest.approx(was["height"] / 2, abs=0.01)
    x0 = min(e["x"] - e["width"] / 2 for e in before)
    x1 = max(e["x"] + e["width"] / 2 for e in before)
    nx0 = min(e["x"] - e["width"] / 2 for e in after)
    nx1 = max(e["x"] + e["width"] / 2 for e in after)
    assert (nx0 + nx1) / 2 == pytest.approx((x0 + x1) / 2, abs=0.01) and (nx1 - nx0) == pytest.approx((x1 - x0) / 2, abs=0.02)
    assert cw.view(store, card)["can_undo"]
    assert elements(cw.step(store, card, "undo"))[0]["width"] == before[0]["width"]
    for bad in (0, -1, 100, "x", None):
        with pytest.raises(su.ValidationError, match="scale factor"):
            cw.edit(store, card, {"op": "scale", "side": "front", "ids": ids, "factor": bad})


# -- the artwork file, the preview and a real SVG end to end ---------------------------------------------------------------------------------
def test_the_artwork_file_is_named_not_pathed_and_a_lost_file_is_a_problem_of_the_part_not_a_crash(store, card, monkeypatch):
    view = importing(store, card, monkeypatch=monkeypatch)
    part = elements(view)[0]
    name = part["vector"]["artwork"]
    assert cvx.FILE_PATTERN.match(name) and "/" not in name
    (store.data_dir / "files" / name).unlink()
    cvx._artworks.clear()
    cw._geometries.clear()
    lost = elements(cw.view(store, card))
    assert all(e["empty"] and e["problems"] == ["The artwork file of this part is missing"] for e in lost)


def damaged(store, card, monkeypatch, polys):
    """A card whose first part has the outlines ``polys`` in its artwork file, as a file damaged or written by another program would have them."""
    import json
    view = importing(store, card, monkeypatch=monkeypatch)
    name = elements(view)[0]["vector"]["artwork"]
    path = store.data_dir / "files" / name
    body = json.loads(path.read_text(encoding="utf-8"))
    body["parts"][0]["polys"] = polys
    path.write_text(json.dumps(body), encoding="utf-8")
    cvx._artworks.clear()
    cw._geometries.clear()
    return elements(cw.view(store, card))


def test_outlines_that_touch_themselves_are_repaired_when_a_part_is_drawn_not_a_crash_of_the_card(store, card, monkeypatch):
    """Found with a real SVG: rounding the outlines to a tenth of a micron left a polygon that crossed itself, and every view of the card was an error."""
    bow_tie = [[[0, 0, 10, 0, 0, 10, 10, 10]]]
    drawn = damaged(store, card, monkeypatch, bow_tie)
    assert drawn[0]["empty"] is False and drawn[0]["problems"] == [] and drawn[0]["d"]
    assert len(drawn) == 3, "the other parts are drawn as before"


def test_a_part_whose_outlines_cannot_be_read_is_a_problem_of_that_part_and_the_card_still_opens(store, card, monkeypatch):
    drawn = damaged(store, card, monkeypatch, [[[0, 0, 1, 1]]])
    assert drawn[0]["empty"] is True and drawn[0]["problems"] == ["The shape of this part could not be read from its artwork file"]
    assert all(not e["empty"] for e in drawn[1:])


def test_a_file_whose_parts_cannot_be_drawn_is_refused_and_leaves_nothing_in_the_card(store, card, monkeypatch):
    def broken(item, width, height):
        raise ValueError("nothing can be drawn")
    monkeypatch.setattr(cvx, "part_geometry", broken)
    before = cw.view(store, card)
    with pytest.raises(Exception):
        importing(store, card, monkeypatch=monkeypatch)
    cw._geometries.clear()
    assert cw.view(store, card)["sides"]["front"]["elements"] == before["sides"]["front"]["elements"] == []


def test_the_preview_draws_each_part_in_its_design_colour(store, card, monkeypatch):
    importing(store, card, monkeypatch=monkeypatch)
    svg = cw.preview_svg(store, card, "front")
    assert 'fill="#a05a2c"' in svg and 'fill="#3a2a20"' in svg and 'fill="#000000"' in svg


def test_a_real_svg_goes_through_the_whole_path(store, card):
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="25mm" viewBox="0 0 40 25"><rect width="40" height="25" fill="#fff"/>'
           b'<path d="M2 25V8l6-8h24l6 8v17z" fill="#a05a2c"/><circle cx="12" cy="10" r="2" fill="#000"/><text x="3" y="3">hi</text></svg>')
    view = cw.import_vector(store, card, "front", "dog.svg", svg)
    parts = elements(view)
    assert [e["vector"]["fill"] for e in parts] == ["#a05a2c", "#000000"] and all(e["d"] for e in parts)
    assert view["import"]["background"] is True and any("text" in n for n in view["import"]["notes"])
    assert parts[0]["width"] == pytest.approx(36.0, abs=0.05)
