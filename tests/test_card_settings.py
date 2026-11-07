"""The engraving settings a business card may choose (ready-engraving-settings-for-business-cards, REQ-001..005, 022..024; Q-001 A, Q-005 A):
only what the workshop MEASURED for exactly the card's laser, lens and titanium, by type; unknown with a reason otherwise; nothing predicted and
nothing from another laser, lens or material. The measured data are written as accepted checks store them."""
import json

import pytest

import obs
import test_photo_knowledge as tpk
from titanium_platform import card_settings as cs, plans, setup as su
from titanium_platform.db import now

TYPES = ["color", "photo", "line_text", "deep"]


@pytest.fixture
def world(store):
    w = obs.setup(store)
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0)["id"]
    w["other_ti"] = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)["id"]
    w["card"] = {"device_id": w["setup"][0], "lens_id": w["setup"][1], "material_id": w["ti"]}
    w["photo"] = {"store": store, "laser": w["setup"][0], "lens": w["setup"][1], "titanium": w["ti"]}
    return w


def colour(store, w, lab, **extra):
    extra.setdefault("speed", 1000)
    extra.setdefault("line_interval", 0.01)
    extra.setdefault("material_id", w["ti"])
    return obs.add(store, w, lab, layer_type="Scan", **extra)


def types_of(store, setup):
    return {t["type"]: t for t in cs.choices(store, setup)["types"]}


def finding(store, w, parameters, purpose="line", status="candidate", lens_id=obs._SAME, material_id=None):
    """An accepted capability finding of the world with ``parameters``."""
    observation = obs.add(store, w, [50.0, 0.0, 0.0], material_id=material_id or w["ti"], lens_id=lens_id)
    pair_id = store.one("SELECT pair_id FROM observation WHERE id=?", (observation,))["pair_id"]
    return store.execute(
        "INSERT INTO capability_finding(pair_id,purpose,status,summary,parameters_json,evidence_json,next_test,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (pair_id, purpose, status, "A photo-based line candidate.", json.dumps(parameters), "{}", "Repeat it on a new small area.", now())).lastrowid


LINE = {"power": 12.0, "frequency": 60.0, "speed": 800.0, "pulse_width": 200.0, "passes": 2, "layer_type": "Cut"}


# -- the setup --------------------------------------------------------------------------------------------------------------------------
def test_the_setup_is_complete_with_a_laser_and_a_material_and_an_unknown_lens_is_a_valid_choice(store, world):
    view = cs.setup_view(store, world["card"])
    assert view["complete"] and view["missing"] == [] and view["device"]["name"] and view["material"]["name"] == "Grade 2 sheet"
    assert view["lens"]["name"].startswith("F-Theta")
    unknown_lens = cs.setup_view(store, {**world["card"], "lens_id": None})
    assert unknown_lens["complete"] and unknown_lens["lens"] is None and unknown_lens["lens_id"] is None


def test_a_setup_without_a_material_or_with_a_lost_laser_is_incomplete_and_says_what_is_missing(store, world):
    assert cs.setup_view(store, {**world["card"], "material_id": None})["missing"] == ["the material"]
    gone = cs.setup_view(store, {**world["card"], "device_id": 9999, "material_id": 9999})
    assert not gone["complete"] and gone["missing"] == ["the laser", "the material"]


# -- nothing is measured: unknown with a reason, never a blank --------------------------------------------------------------------------------
def test_with_nothing_measured_every_type_is_unknown_with_a_plain_reason(store, world):
    found = cs.choices(store, world["card"])
    assert [t["type"] for t in found["types"]] == TYPES and found["setup"]["complete"]
    for t in found["types"]:
        assert not t["known"] and t["groups"] == [] and t["reason"].endswith(".") and len(t["reason"]) > 40
    assert "Measure colours" in found["types"][0]["reason"] and "Photograph" in found["types"][1]["reason"]


def test_deep_engraving_is_always_unknown_even_when_everything_else_is_measured(store, world):
    colour(store, world, [60.0, 5.0, 20.0])
    deep = types_of(store, world["card"])["deep"]
    assert not deep["known"] and "not measured" in deep["reason"] and deep["groups"] == []


def test_an_incomplete_setup_offers_nothing_and_says_to_choose_the_material(store, world):
    colour(store, world, [60.0, 5.0, 20.0])
    found = cs.choices(store, {**world["card"], "material_id": None})
    assert all(not t["known"] and "material" in t["reason"] for t in found["types"]) and not found["setup"]["complete"]
    assert cs.proposal(store, {**world["card"], "material_id": None}) is None


# -- colour -----------------------------------------------------------------------------------------------------------------------------
def test_the_colours_measured_for_this_laser_lens_and_titanium_are_offered_with_their_settings_and_evidence(store, world):
    colour(store, world, [60.0, 5.0, 20.0], engraving="a1")
    colour(store, world, [62.0, 5.0, 20.0], engraving="a2")
    colour(store, world, [40.0, -30.0, -30.0], speed=2000, line_interval=0.02)
    found = types_of(store, world["card"])["color"]
    assert found["known"] and found["reason"] is None
    items = [i for g in found["groups"] for i in g["items"]]
    assert len(items) == 2 and sum(g["count"] for g in found["groups"]) == 2
    best = items[0]                                                                         # the most engraved recipe first
    assert best["id"].startswith("color:") and best["type"] == "color" and best["evidence"]["engravings"] == 2
    assert best["evidence"]["status"] == "repeated" and best["swatch"]["srgb"].startswith("#") and len(best["swatch"]["srgb"]) == 7
    assert best["settings"]["mode"] == "fill" and best["settings"]["speed"] == 1000 and best["settings"]["line_interval"] == 0.01
    assert best["unused"] == [] and all(v is not None for v in best["settings"].values())
    assert "origin" not in best                                                             # the answer stays small; the origin comes with the choice
    chosen = cs.item_by_id(store, world["card"], best["id"])
    assert {k: v for k, v in chosen.items() if k != "origin"} == best
    assert chosen["origin"] == {"kind": "choice", "choice_id": best["id"], "type": "color", "source": best["source"], "label": best["label"],
                                "detail": best["detail"], "evidence": best["evidence"], "setup": world["card"]}


def test_a_colour_of_another_titanium_lens_or_laser_is_never_offered_not_even_as_the_nearest(store, world):
    colour(store, world, [50.0, 0.0, 0.0], material_id=world["other_ti"])                       # other grade of titanium
    colour(store, world, [55.0, 0.0, 0.0], lens_id=None)                                        # the lens unknown when measured
    other = obs.setup(store)
    other["n"] = 100
    obs.add(store, other, [45.0, 0.0, 0.0], speed=1000, line_interval=0.01, material_id=world["ti"], layer_type="Scan")   # another laser
    found = types_of(store, world["card"])["color"]
    assert not found["known"] and found["groups"] == []
    elsewhere = cs.choices(store, {**world["card"], "material_id": world["other_ti"]})["types"][0]
    assert elsewhere["known"] and sum(g["count"] for g in elsewhere["groups"]) == 1                # it is offered to a card on that titanium
    ids = [i["id"] for g in elsewhere["groups"] for i in g["items"]]
    assert cs.item_by_id(store, world["card"], ids[0]) is None                                      # but its id never resolves for this setup


def test_a_colour_recipe_that_contradicts_itself_is_left_out(store, world):
    colour(store, world, [30.0, 40.0, 40.0], engraving="x1")
    colour(store, world, [70.0, -40.0, -40.0], engraving="x2")                                  # the same settings, a very different colour
    found = types_of(store, world["card"])["color"]
    assert not found["known"]


# -- photo ------------------------------------------------------------------------------------------------------------------------------
def test_a_photo_engraving_that_shows_a_picture_is_offered_with_the_settings_of_a_raster_picture(store, world):
    tpk.accepted(world["photo"], [tpk.layer("L1", "jarvis", tpk.LINEAR, power=25.0, speed=125.0, interval=0.01)])
    found = types_of(store, world["card"])["photo"]
    assert found["known"]
    item = found["groups"][0]["items"][0]
    assert item["id"].startswith("photo:jarvis:") and item["settings"]["dither"] == "jarvis" and item["settings"]["power"] == 25.0
    assert item["settings"]["line_interval"] == 0.01 and item["settings"]["mode"] == "fill"
    assert set(item["unused"]) == {"dither", "min_power"} & set(item["settings"]) | ({"dot_width"} & set(item["settings"]))
    assert "dither" in item["unused"] and cs.item_by_id(store, world["card"], item["id"])["origin"]["setup"] == world["card"]


def test_a_photo_engraving_that_shows_no_picture_or_was_made_on_another_titanium_is_not_offered(store, world):
    tpk.accepted(world["photo"], [tpk.layer("N1", "jarvis", tpk.NEGATIVE, power=25.0)])                       # dots lighter than the titanium
    tpk.accepted(world["photo"], [tpk.layer("B1", "atkinson", tpk.BLOCKED, power=40.0)], material=world["other_ti"])   # another grade
    found = types_of(store, world["card"])["photo"]
    assert not found["known"] and "Photograph" in found["reason"]


# -- lines and text ---------------------------------------------------------------------------------------------------------------------
def test_a_line_candidate_with_complete_settings_is_offered_as_a_cut_with_the_plates_own_words(store, world):
    finding(store, world, LINE)
    found = types_of(store, world["card"])["line_text"]
    assert found["known"]
    item = found["groups"][0]["items"][0]
    assert item["settings"] == {"mode": "line", "power": 12.0, "speed": 800.0, "frequency": 60.0, "pulse_width": 200.0, "passes": 2}
    assert item["evidence"]["status"] == "candidate" and "line candidate" in item["evidence"]["summary"] and item["source"] == "Capability plate"


def test_a_finding_with_missing_settings_or_on_another_lens_or_titanium_is_not_offered(store, world):
    finding(store, world, {**LINE, "power": None})                                              # not repeatable as it stands
    finding(store, world, LINE, lens_id=None)                                                    # measured with the lens unknown
    finding(store, world, LINE, material_id=world["other_ti"])                                  # another grade
    assert not types_of(store, world["card"])["line_text"]["known"]


# -- the proposal for a new card ----------------------------------------------------------------------------------------------------------
def test_nothing_known_means_no_proposal_and_the_best_known_type_is_proposed_in_the_agreed_order(store, world):
    assert cs.proposal(store, world["card"]) is None
    tpk.accepted(world["photo"], [tpk.layer("L1", "jarvis", tpk.LINEAR, power=25.0)])
    assert cs.proposal(store, world["card"])["type"] == "photo"
    colour(store, world, [60.0, 5.0, 20.0])
    assert cs.proposal(store, world["card"])["type"] == "color"
    finding(store, world, LINE)
    assert cs.proposal(store, world["card"])["type"] == "line_text"


def test_an_id_from_a_type_that_does_not_exist_or_is_not_text_never_resolves(store, world):
    colour(store, world, [60.0, 5.0, 20.0])
    for bad in (None, 7, "", "color", "deep:1", "nonsense:1", "color:nothing"):
        assert cs.item_by_id(store, world["card"], bad) is None


def test_two_palette_entries_with_the_same_settings_and_colour_are_one_choice(store, world, monkeypatch):
    colour(store, world, [60.0, 5.0, 20.0])
    real = cs.palette.vector_palette(store, *world["setup"], world["ti"])
    twin = {**real["entries"][0], "id": "twin-of-the-first"}
    monkeypatch.setattr(cs.palette, "vector_palette", lambda *args, **kwargs: {**real, "entries": [real["entries"][0], twin]})
    found = types_of(store, world["card"])["color"]
    assert sum(g["count"] for g in found["groups"]) == 1
