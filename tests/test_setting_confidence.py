"""Confidence in the colour of a setting reaches everything that takes a colour of a setting: the palette of a vector work, the knowledge
model and the colour map search (REQ-045, DEC-083). The operator's cases, end to end on observation rows."""
import json

import pytest

import obs
from titanium_platform import agreement, colormap, model, palette, setup as su
from titanium_platform.api.app import create_app
from titanium_platform.db import now

YELLOW = [80.0, 0.0, 45.0]
BROWN = [30.0, 12.0, 14.0]
BROWN_2 = [31.0, 12.0, 15.0]


@pytest.fixture
def world(store):
    w = obs.setup(store)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")["id"]
    return w


def add(store, w, lab, engraving, **extra):
    return obs.add(store, w, lab, material_id=w["ti"], engraving=engraving, layer_type="Scan", **extra)


def entries(store, w):
    return palette.vector_palette(store, w["setup"][0], w["setup"][1], w["ti"])["entries"]


def only(store, w):
    (entry,) = entries(store, w)
    return entry


# -- the palette: yellow first, dark brown when redone ----------------------------------------------------------------------------------
def test_a_setting_that_was_yellow_and_is_redone_as_dark_brown_gets_the_brown_and_waits_for_a_repeat_before_it_is_taken(store, world):
    add(store, world, YELLOW, "e1")
    first = only(store, world)
    assert first["lab"] == pytest.approx(YELLOW) and first["confidence"] is None and first["caution"] is None
    assert palette.automatic(first, None, False)

    add(store, world, BROWN, "e2")
    redone = only(store, world)
    assert redone["id"] == first["id"]                                                       # a saved work keeps pointing at it
    assert redone["lab"] == pytest.approx(BROWN)                                              # the new colour replaces the old one
    assert redone["agreement"] == {"engravings": 2, "agreeing": 1, "differing": 1, "contradicted": True, "limit": agreement.AGREEMENT_DE}
    assert redone["caution"] == "contradicted" and redone["confidence"] == pytest.approx(1 / 6)
    assert not palette.automatic(redone, None, False)                                         # the colour changed under the same settings

    add(store, world, BROWN_2, "e3")
    settled = only(store, world)
    assert settled["lab"] == pytest.approx([30.5, 12.0, 14.5]) and settled["agreement"]["agreeing"] == 2
    assert settled["caution"] is None and settled["confidence"] == pytest.approx(1 / 3) and palette.automatic(settled, None, False)
    assert settled["stability"]["variance"] > 100 and settled["engravings"] == 3             # the disagreement still shows in the spread


def test_one_wrong_measurement_among_agreeing_ones_does_not_move_the_colour_and_lowers_the_confidence(store, world):
    for i, lab in enumerate((BROWN, BROWN_2, [29.0, 12.0, 14.0])):
        add(store, world, lab, f"e{i}")
    sure = only(store, world)
    add(store, world, YELLOW, "odd")
    doubtful = only(store, world)
    assert doubtful["lab"] == pytest.approx(sure["lab"])                                      # not the yellowish mean of four
    assert sure["confidence"] == pytest.approx(0.6) and doubtful["confidence"] == pytest.approx(9 / 20)
    assert doubtful["confidence"] < sure["confidence"] and doubtful["caution"] is None       # three of four agree: still taken
    assert doubtful["agreement"]["agreeing"] == 3 and doubtful["agreement"]["differing"] == 1


def test_each_agreeing_repeat_raises_the_confidence_of_a_palette_entry(store, world):
    seen = []
    for i, lab in enumerate((BROWN, BROWN_2, [29.5, 12.0, 14.0], [30.5, 11.5, 14.0])):
        add(store, world, lab, f"e{i}")
        seen.append(only(store, world)["confidence"])
    assert seen[0] is None and seen[1:] == pytest.approx([0.5, 0.6, 4 / 6]) and seen[1:] == sorted(seen[1:])


# -- the automatic choice ---------------------------------------------------------------------------------------------------------------------
def test_a_contradicted_colour_is_not_chosen_by_the_automatic_modes_but_the_operator_can_choose_it(store, world):
    add(store, world, YELLOW, "e1", speed=1000)
    add(store, world, BROWN, "e2", speed=1000)                                                # the same settings: yellow then brown
    add(store, world, [60.0, 0.0, 0.0], "e3", speed=2000)
    contradicted, steady = sorted(entries(store, world), key=lambda e: e["caution"] is None)
    assert contradicted["caution"] == "contradicted" and steady["caution"] is None
    source = [{"index": 0, "lab": BROWN, "pixels": 100}]                                     # the contradicted colour is the nearest
    for mode in palette.MODES:
        picked = palette.assign(source, entries(store, world), mode, tolerance_de=3)["colours"][0]
        assert picked["entry_id"] == steady["id"]
        by_hand = palette.assign(source, entries(store, world), mode, tolerance_de=3, keep={0: contradicted["id"]})["colours"][0]
        assert by_hand["entry_id"] == contradicted["id"] and by_hand["how"] == "kept"


def test_when_every_colour_is_contradicted_the_automatic_modes_still_colour_with_them_and_say_so(store, world):
    add(store, world, YELLOW, "e1")
    add(store, world, BROWN, "e2")
    (only_entry,) = entries(store, world)
    result = palette.assign([{"index": 0, "lab": BROWN, "pixels": 1}], [only_entry], "closest", tolerance_de=3)
    assert result["cautioned"] is True and result["colours"][0]["entry_id"] == only_entry["id"]
    other = palette.assign([{"index": 0, "lab": BROWN, "pixels": 1}], [{**only_entry, "caution": None}], "closest", tolerance_de=3)
    assert other["cautioned"] is False
    chosen_from, cautioned = palette.choosable([only_entry], None, False)
    assert chosen_from == [only_entry] and cautioned is True
    assert palette.choosable([only_entry], None, False)[0] == [only_entry] and palette.choosable([{**only_entry, "basis": "as-shot"}], None, False) == ([], False)


def entry(entry_id, lab, seconds, confidence=None, caution=None):
    return {"id": entry_id, "lab": list(lab), "time_s_per_cm2": seconds, "confidence": confidence, "caution": caution, "basis": "chart"}


def chosen(result):
    return {c["index"]: c["entry_id"] for c in result["colours"]}


def test_inside_the_tolerance_the_more_confident_colour_is_taken_before_the_faster_one():
    pal = [entry("once-fast", [50, 0, 0], 5.0), entry("repeated-slow", [51, 0, 0], 40.0, confidence=0.6),
           entry("twice-slowest", [52, 0, 0], 90.0, confidence=0.5)]
    source = [{"index": 0, "lab": [50, 0, 0], "pixels": 100}]
    assert chosen(palette.assign(source, pal, "closest", tolerance_de=3)) == {0: "repeated-slow"}
    no_repeat = [e for e in pal if e["id"] != "repeated-slow"]
    assert chosen(palette.assign(source, no_repeat, "closest", tolerance_de=3)) == {0: "twice-slowest"}
    equal = [entry("slow", [51, 0, 0], 40.0, confidence=0.5), entry("fast", [52, 0, 0], 5.0, confidence=0.5)]
    assert chosen(palette.assign(source, equal, "closest", tolerance_de=3)) == {0: "fast"}      # equally confident: the faster, as before


def test_confidence_never_outweighs_the_distance_when_nothing_is_inside_the_tolerance():
    pal = [entry("near-once", [50, 0, 0], 5.0), entry("far-repeated", [58, 0, 0], 5.0, confidence=0.7)]
    assert chosen(palette.assign([{"index": 0, "lab": [47, 0, 0], "pixels": 100}], pal, "closest", tolerance_de=1)) == {0: "near-once"}


# -- a better measurement of the same settings replaces a worse one -------------------------------------------------------------
def add_against_clean_titanium(store, w, lab, engraving, **extra):
    """An observation measured against the clean titanium of its own photograph (no chart): a camera-relative layer and, in the same
    pair, the cleaning witness it is expressed against."""
    relative = {"color_measurement": {"mode": "raw_camera_relative"}}
    observation_id = obs.add(store, w, lab, material_id=w["ti"], engraving=engraving, layer_type="Scan", model_eligible=0, evidence=relative, **extra)
    row = store.one("SELECT * FROM observation WHERE id=?", (observation_id,))
    witness = {"role": colormap.WITNESS, "layer_name": "clean", **relative}
    store.execute(
        "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
        "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["pair_id"], -1, row["device_id"], row["lens_id"], row["engraving_id"], json.dumps(colormap.DEFAULT_CLEAN), row["parameters_json"], "markers",
         row["context_json"], 0, 0, "witness", json.dumps(witness), now()))
    return observation_id


def test_a_colour_measured_against_a_chart_replaces_one_of_the_same_settings_measured_against_the_clean_titanium(store, world):
    add_against_clean_titanium(store, world, [60.0, 5.0, 20.0], "old")      # its witness is the nominal clean titanium: the colour stays as it is
    (alone,) = entries(store, world)
    assert alone["basis"] == "clean" and alone["caution"] is None                              # nothing better exists: it is taken
    add(store, world, BROWN, "new")                                                            # the redo, with a chart
    both = {e["basis"]: e for e in entries(store, world)}
    assert both["chart"]["caution"] is None and both["chart"]["lab"] == pytest.approx(BROWN)
    assert both["clean"]["caution"] == "superseded" and both["clean"]["id"] == alone["id"]    # still in the palette, with its id
    assert not palette.automatic(both["clean"], None, False) and not palette.automatic(both["clean"], None, True)
    got = palette.vector_palette(store, world["setup"][0], world["setup"][1], world["ti"])
    assert got["cautions"] == {"contradicted": 0, "superseded": 1}
    picked = palette.assign([{"index": 0, "lab": both["clean"]["lab"], "pixels": 1}], got["entries"], "closest", tolerance_de=3)["colours"][0]
    assert picked["entry_id"] == both["chart"]["id"]


def test_settings_of_different_recipes_do_not_replace_each_other(store, world):
    add(store, world, YELLOW, "a", speed=1000)
    add_against_clean_titanium(store, world, BROWN, "b", speed=2000)                           # other settings, a worse basis
    found = entries(store, world)
    assert {e["basis"] for e in found} == {"chart", "clean"} and all(e["caution"] is None for e in found)


# -- the knowledge model -------------------------------------------------------------------------------------------------------------------
def knowledge(store, w):
    (summary,) = model.knowledge_summaries(store, *w["setup"]).values()
    return summary


def test_the_knowledge_model_takes_the_agreed_colour_and_keeps_the_spread_over_all_engravings(store, world):
    add(store, world, YELLOW, "e1")
    add(store, world, BROWN, "e2")
    add(store, world, BROWN_2, "e3")
    s = knowledge(store, world)
    assert s["lab"] == pytest.approx([30.5, 12.0, 14.5]) and s["agreement"]["agreeing"] == 2 and s["caution"] is None
    assert s["confidence"] == pytest.approx(1 / 3) and s["stability"]["variance"] > 100 and s["expected_delta_e"] > 10


def test_one_engraving_is_not_assessed_and_contradicting_engravings_are_cautioned(store, world):
    add(store, world, YELLOW, "e1")
    s = knowledge(store, world)
    assert s["confidence"] is None and s["available"] is False and s["caution"] is None
    add(store, world, BROWN, "e2")
    s = knowledge(store, world)
    assert s["available"] and s["caution"] == "contradicted" and s["lab"] == pytest.approx(BROWN) and s["confidence"] == pytest.approx(1 / 6)


def test_a_prediction_does_not_take_a_contradicted_setting_while_another_one_is_available(store, world):
    add(store, world, YELLOW, "e1", speed=1000)
    add(store, world, BROWN, "e2", speed=1000)                                                # contradicted, and the nearest to the target
    add(store, world, [50.0, 0.0, 0.0], "e3", speed=2000)
    add(store, world, [52.0, 0.0, 0.0], "e4", speed=2000)
    samples = list(model.knowledge_summaries(store, *world["setup"]).values())
    sure = next(s for s in samples if not s["caution"])
    assert model.predict_for_lab(samples, BROWN)["key"] == sure["key"]
    only_contradicted = [s for s in samples if s["caution"]]
    assert model.predict_for_lab(only_contradicted, BROWN)["available"]                      # nothing else: it is still offered, with its low confidence


# -- the colour map search --------------------------------------------------------------------------------------------------------------------
def test_the_search_measures_the_distance_to_the_agreed_colour_not_to_the_nearest_single_measurement(store, world):
    for i, lab in enumerate((BROWN, BROWN_2)):
        add(store, world, lab, f"b{i}")
    add(store, world, YELLOW, "y")                                                            # one yellow among two browns
    (match,) = colormap.search(store, YELLOW)["matches"]
    assert match["display_lab"] == pytest.approx([30.5, 12.0, 14.5])
    assert match["distance"] > 50                                                              # the yellow is not "found" here any more
    assert match["repeats"] == 3 and match["agreement"]["agreeing"] == 2 and match["agreement"]["differing"] == 1
    assert match["confidence"] == pytest.approx(1 / 3) and match["caution"] is None


def test_inside_the_tolerance_the_search_puts_the_confident_recipe_before_the_faster_one(store, world):
    add(store, world, [50.0, 0.0, 0.0], "a1", speed=1000, line_interval=0.02)                 # engraved once, fast
    add(store, world, [51.0, 0.0, 0.0], "b1", speed=500, line_interval=0.01)                  # engraved twice, slow
    add(store, world, [51.5, 0.0, 0.0], "b2", speed=500, line_interval=0.01)
    found = colormap.search(store, [50.0, 0.0, 0.0], tolerance_de=3)["matches"]
    assert [m["repeats"] for m in found] == [2, 1] and found[0]["confidence"] == pytest.approx(0.5) and found[1]["confidence"] is None
    assert found[0]["time_s_per_cm2"] > found[1]["time_s_per_cm2"]


# -- the colour map draws a circle by the confidence of the recipe of each colour ---------------------------------------------------------
def test_every_point_of_the_map_carries_the_confidence_of_its_recipe_through_the_api(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")["id"]
    add(store, w, [60.0, 0.0, 0.0], "once", speed=1000)                                         # engraved once
    for i, lab in enumerate((BROWN, BROWN_2, [29.5, 12.0, 14.0])):
        add(store, w, lab, f"three{i}", speed=2000)                                              # three that agree
    add(store, w, YELLOW, "y", speed=3000)
    add(store, w, BROWN, "b", speed=3000)                                                        # a colour that changed
    points = TestClient(app).get("/api/colors").json()["points"]
    by_speed = {}
    for point in points:
        by_speed.setdefault(point["parameters"]["speed"], []).append(point)
    once, agreeing, changed = by_speed[1000][0], by_speed[2000], by_speed[3000]
    assert once["confidence"] is None and once["trust"] == pytest.approx(1 / 3) and once["agreement"]["engravings"] == 1
    assert [p["trust"] for p in agreeing] == pytest.approx([0.6] * 3) and agreeing[0]["agreement"]["agreeing"] == 3 and agreeing[0]["caution"] is None
    assert {p["caution"] for p in changed} == {"contradicted"} and [p["trust"] for p in changed] == pytest.approx([1 / 6] * 2)
    assert min(p["trust"] for p in changed) < once["trust"] < agreeing[0]["trust"]                # the diameter order: changed < once < repeated


def test_annotate_gives_the_points_of_a_recipe_the_same_confidence_in_place(store, world):
    for i, lab in enumerate((BROWN, BROWN_2)):
        add(store, world, lab, f"e{i}")
    points = colormap.collect(store)["points"]
    assert all("trust" not in p for p in points)
    assert colormap.annotate(points) is points
    assert [p["trust"] for p in points] == pytest.approx([0.5, 0.5]) and [p["confidence"] for p in points] == pytest.approx([0.5, 0.5])


# -- the colour map says how far a colour is trusted and where it comes from (REQ-049) ---------------------------------------------------------
def test_a_colour_is_doubtful_when_its_circle_is_smaller_than_that_of_one_engraving():
    """The circle of DEC-084 is 4 * 1.5 ** (agreeing - 1 - differing): smaller than 4 exactly when that exponent is negative."""
    def found(agreeing, differing):
        return {"agreeing": agreeing, "differing": differing}
    assert not agreement.doubtful(found(1, 0))                       # engraved once: not assessed, not doubtful
    assert not agreement.doubtful(found(3, 0)) and not agreement.doubtful(found(2, 1))      # the circle of one engraving or larger
    assert agreement.doubtful(found(1, 1)) and agreement.doubtful(found(1, 2)) and agreement.doubtful(found(2, 2))
    assert agreement.doubtful(agreement.shown(agreement.consensus([{"lab": YELLOW}, {"lab": BROWN}])))


def build_map(store, w):
    add(store, w, [60.0, 0.0, 0.0], "once", speed=1000)                                           # engraved once
    for i, lab in enumerate((BROWN, BROWN_2, [29.5, 12.0, 14.0])):
        add(store, w, lab, f"three{i}", speed=2000)                                                # three that agree
    add(store, w, YELLOW, "y", speed=3000)
    add(store, w, BROWN, "b", speed=3000)                                                          # a colour that changed


def test_the_map_marks_the_doubtful_colours_names_their_sources_and_can_leave_them_out(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")["id"]
    build_map(store, w)
    client = TestClient(app)
    data = client.get("/api/colors").json()
    speeds = {p["parameters"]["speed"]: p["doubtful"] for p in data["points"]}
    assert speeds == {1000: False, 2000: False, 3000: True} and data["counts"]["doubtful"] == 2
    # the sources: every recipe engraved more than once, by group; a recipe engraved once is told by its own point
    by_group = {p["parameters"]["speed"]: p["group"] for p in data["points"]}
    assert set(data["recipes"]) == {by_group[2000], by_group[3000]}
    three = data["recipes"][by_group[2000]]
    assert len(three["sources"]) == 3 and all(s["agrees"] for s in three["sources"]) and three["lab"] == pytest.approx([30.17, 12.0, 14.33], abs=0.1)
    changed = data["recipes"][by_group[3000]]["sources"]
    assert sorted(s["agrees"] for s in changed) == [False, True] and {s["engraving_id"] for s in changed} == {"y", "b"}
    one = three["sources"][0]
    assert {"engraving_id", "experiment", "title", "date", "pair_ids", "photos", "layers", "observation_ids", "lab", "delta_e", "measurement",
            "provisional"} <= set(one) and one["pair_ids"] and one["delta_e"] < 2
    hidden = client.get("/api/colors?hide_doubtful=true").json()
    assert {p["parameters"]["speed"] for p in hidden["points"]} == {1000, 2000} and hidden["counts"]["doubtful"] == 2
    assert hidden["counts"]["calibrated"] + hidden["counts"]["relative"] == len(hidden["points"]) == 4


def test_a_search_entry_names_the_engravings_its_colour_is_known_from_and_the_doubtful_can_be_left_out(store, world):
    for i, lab in enumerate((BROWN, BROWN_2)):
        add(store, world, lab, f"b{i}", speed=1000)
    add(store, world, YELLOW, "y", speed=1000)                                                     # one yellow among two browns: still not doubtful
    add(store, world, YELLOW, "c1", speed=2000)
    add(store, world, BROWN, "c2", speed=2000)                                                     # two that disagree: doubtful
    add(store, world, [60.0, 0.0, 0.0], "alone", speed=3000)
    found = {m["parameters"]["speed"]: m for m in colormap.search(store, YELLOW, limit=10)["matches"]}
    assert set(found) == {1000, 2000, 3000}
    assert [found[s]["doubtful"] for s in (1000, 2000, 3000)] == [False, True, False]
    assert sorted(s["agrees"] for s in found[1000]["sources"]) == [False, True, True]
    off = next(s for s in found[1000]["sources"] if not s["agrees"])
    assert off["engraving_id"] == "y" and off["delta_e"] > 50 and off["lab"] == YELLOW              # the engraving that does not agree says how far it is
    assert [s["engraving_id"] for s in found[3000]["sources"]] == ["alone"] and found[3000]["sources"][0]["agrees"] is True
    left = colormap.search(store, YELLOW, limit=10, hide_doubtful=True)
    assert {m["parameters"]["speed"] for m in left["matches"]} == {1000, 3000} and left["counts"]["doubtful"] == 1
    assert colormap.search(store, YELLOW, limit=10)["counts"]["doubtful"] == 1                      # counted when shown too


def test_the_api_passes_the_doubtful_filter_to_the_search(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")["id"]
    build_map(store, w)
    client = TestClient(app)
    query = "L=50&a=0&b=0&limit=10"
    assert {m["parameters"]["speed"] for m in client.get(f"/api/colors/search?{query}").json()["matches"]} == {1000, 2000, 3000}
    hidden = client.get(f"/api/colors/search?{query}&hide_doubtful=true").json()
    assert {m["parameters"]["speed"] for m in hidden["matches"]} == {1000, 2000} and hidden["counts"]["doubtful"] == 1
