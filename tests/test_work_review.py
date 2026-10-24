"""Work on the errors (DEC-090, proposed): the colour each layer of an exported file promised, set beside the colour the photograph of
the engraving measured; the conclusion kept in the work; the layers whose titanium colour moved since the operator saw them, with a
replacement proposed. The engraved file is matched to the promise by settings, never by layer number."""
import json

import cv2
import pytest

import obs
import synth
from test_supplied_settings import CELLS, JOB
from test_vector_work import PAPER, YELLOW, by_rgb, colouring, create, job, lab, palette_ids, picture, work    # noqa: F401  (fixtures)
from test_vector_list import pixels, share, works
from titanium_platform import color, conversion as cv, ingest, plans as pl, setup as su, work_errors, work_review as wr
from titanium_platform.db import now


# -- recognising a recipe ---------------------------------------------------------------------------------------------------------
def layer(index, power=20.0, speed=500.0, lab_=(70.0, 10.0, 10.0), area=100.0, **more):
    return {"index": index, "name": f"C{index:02d}", "entry_id": f"e{index}", "settings": {"power": power, "frequency": 40.0, "speed": speed,
            "line_interval": 0.02, "pulse_width": 200.0, "passes": 1.0, **more}, "lab": list(lab_), "srgb": [180, 120, 100], "basis": "chart",
            "area_mm2": area, "region_ids": [f"r{index}"]}


def seen(index, power=20.0, speed=500.0, lab_=(70.0, 10.0, 10.0), **more):
    e = layer(index, power, speed, lab_, **more)
    return {"layer_index": index + 10, "name": f"C{index + 10}", "settings": e["settings"], "lab": list(lab_), "basis": "chart", "measurement": "calibrated"}


def test_settings_match_within_the_rounding_lightburn_does_and_not_beyond_it():
    a = layer(1, power=10.5556, speed=127.778)["settings"]
    assert wr.closeness(a, {**a, "power": 10.56, "speed": 127.8}) is not None
    assert wr.closeness(a, {**a, "speed": 130.0}) is None                                  # a different recipe
    assert wr.closeness(a, {k: v for k, v in a.items() if k != "speed"}) is None            # a required setting is missing
    assert wr.closeness(a, {k: v for k, v in a.items() if k != "pulse_width"}) is not None  # an optional one is simply not compared


def test_each_layer_is_matched_once_to_the_closest_layer_of_the_other_file():
    promise = [layer(1, power=20.0), layer(2, power=20.05)]
    engraved = [seen(1, power=20.05)]
    assert wr.match(promise, engraved) == [(1, 0)]                                         # the closer promised layer takes it
    assert wr.match(promise, [seen(1, power=20.0), seen(2, power=20.05)]) == [(0, 0), (1, 1)]


def test_the_difference_names_lightness_chroma_and_hue_and_leaves_the_hue_of_a_grey_out():
    d = wr.difference((70, 20, 0), (60, 0, 20))
    assert d["dL"] == -10 and d["dC"] == pytest.approx(0.0) and d["dh"] == pytest.approx(90.0) and d["delta_e"] > 10
    assert wr.difference((70, 1, 1), (70, 3, 0))["dh"] is None


# -- the review ---------------------------------------------------------------------------------------------------------------------------
def test_the_review_sets_each_promised_layer_beside_the_engraved_layer_of_the_same_settings():
    promise = [layer(1, area=300, lab_=(80, 5, 5)), layer(2, power=30, area=100, lab_=(60, 20, 10)), layer(3, power=40, area=50)]
    engraved = [seen(1, lab_=(80, 5, 5)), seen(2, power=30, lab_=(52, 20, 10)), seen(9, power=99)]
    r = wr.review(promise, engraved)
    assert [row["promised_index"] for row in r["rows"]] == [1, 2] and [row["layer_index"] for row in r["rows"]] == [11, 12]
    assert r["rows"][0]["delta_e"] == pytest.approx(0.0) and r["rows"][0]["beyond"] is False
    assert r["rows"][1]["dL"] == -8 and r["rows"][1]["beyond"] is True
    assert [n["index"] for n in r["not_engraved"]] == [3] and [u["layer_index"] for u in r["unmatched"]] == [19]
    s = r["summary"]
    assert (s["promised"], s["engraved"], s["matched"], s["beyond_layers"]) == (3, 3, 2, 1)
    assert s["area_share_beyond"] == pytest.approx(100 / 400) and s["mean_delta_e"] == pytest.approx(r["rows"][1]["delta_e"] * 100 / 400)


def test_a_difference_is_beyond_only_past_the_larger_of_the_visible_limit_and_the_photographs_own_error():
    gap = wr.VISIBLE_DE + 1
    promise, engraved = [layer(1, lab_=(70, 0, 0))], [seen(1, lab_=(70 - gap, 0, 0))]
    assert wr.review(promise, engraved)["rows"][0]["beyond"] is True                       # visible
    quiet = wr.review(promise, engraved, chart_residual=gap + 1)
    assert quiet["limit"] == gap + 1 and quiet["rows"][0]["beyond"] is False                # a photograph this uncertain convicts nothing
    assert wr.review(promise, engraved, chart_residual=wr.POOR_CHART_DE + 1)["notes"] == [{"code": "poor_chart", "residual": wr.POOR_CHART_DE + 1}]


def test_the_visible_limit_is_5_de_a_smaller_chart_residual_keeps_it_and_a_difference_exactly_at_it_is_not_beyond():
    """REQ-047 crit. 3: a layer is beyond when ΔE exceeds the larger of 5 and the chart residual; a row carries both colours."""
    assert wr.VISIBLE_DE == 5.0
    promise = [layer(1, lab_=(70, 0, 0)), layer(2, power=30, lab_=(60, 10, 10))]
    engraved = [seen(1, lab_=(65, 0, 0)), seen(2, power=30, lab_=(60, 10, 15.25))]                    # ΔE 5 exactly, and 5.25
    plain = wr.review(promise, engraved)
    assert plain["limit"] == 5.0 and [row["delta_e"] for row in plain["rows"]] == [5.0, 5.25]
    assert [row["beyond"] for row in plain["rows"]] == [False, True]                                    # at the limit is not beyond it
    small = wr.review(promise, engraved, chart_residual=3.6)
    assert small["limit"] == 5.0 and [row["beyond"] for row in small["rows"]] == [False, True]          # a good chart does not lower it
    first = plain["rows"][0]
    assert (first["promised_lab"], first["got_lab"]) == ([70.0, 0.0, 0.0], [65.0, 0.0, 0.0])
    assert first["promised_srgb"] == promise[0]["srgb"] and first["got_srgb"] == [int(v) for v in color.lab_to_srgb8([65, 0, 0])]
    assert (first["dL"], first["dC"], first["dh"]) == (-5.0, 0.0, None)


def test_one_shift_of_lightness_on_most_layers_is_called_systematic_and_not_blamed_on_the_recipes():
    promise = [layer(i, power=10.0 * i, lab_=(70, 5, 5)) for i in range(1, 6)]
    engraved = [seen(i, power=10.0 * i, lab_=(64, 5, 5)) for i in range(1, 6)]
    notes = wr.review(promise, engraved)["notes"]
    assert [n["code"] for n in notes] == ["systematic"] and notes[0]["dL"] == -6 and notes[0]["share"] == 1.0


def test_the_measurements_name_what_they_know_about_a_layer_and_nothing_else():
    promise = [layer(1, lab_=(80, 5, 5))]
    clipped = {**seen(1, lab_=(98.5, 0, 0)), "basis": "as-shot", "measurement": "relative"}
    codes = [c["code"] for c in wr.review(promise, [clipped])["rows"][0]["causes"]]
    assert codes == ["highlight", "basis", "relative_photo"]
    assert wr.review(promise, [seen(1, lab_=(80, 5, 5))])["rows"][0]["causes"] == []


# -- the drift ----------------------------------------------------------------------------------------------------------------------------
def candidates(*labs):
    return [{"id": f"c{i}", "lab": list(v), "srgb": [i, i, i]} for i, v in enumerate(labs)]


def colour_of(index, entry_id, lab_, status="automatic"):
    return {"index": index, "entry_id": entry_id, "lab": list(lab_), "srgb": [1, 2, 3], "status": status}


def test_a_layer_whose_recipe_moved_is_listed_with_the_closest_measured_colour_for_each_source_colour():
    layers = [layer(1, lab_=(70, 10, 10)), layer(2, lab_=(50, 0, 0))]
    by_id = {"e1": {"id": "e1", "lab": [58, 10, 10], "srgb": [9, 9, 9]}, "e2": {"id": "e2", "lab": [50.5, 0, 0], "srgb": [8, 8, 8]}}
    found = wr.drift(layers, [colour_of(0, "e1", (71, 10, 10)), colour_of(1, "e2", (50, 0, 0))], by_id, candidates((70.5, 10, 10), (50, 0, 0)), {"e1", "e2"})
    assert [d["index"] for d in found["layers"]] == [1]                                      # layer 2 moved less than the visible limit
    moved = found["layers"][0]
    assert moved["delta_e"] == pytest.approx(12.0) and moved["now_lab"] == [58, 10, 10] and moved["missing"] is False
    (proposal,) = moved["proposals"]
    assert proposal["colour"] == 0 and proposal["entry_id"] == "c0" and proposal["delta_e_proposed"] < proposal["delta_e_now"] - wr.IMPROVE_DE
    assert found["area_share"] == pytest.approx(0.5) and wr.attention_of(found, "t")["proposals"] == 1


def test_no_replacement_is_proposed_that_is_not_clearly_closer_or_for_an_excluded_colour():
    layers = [layer(1, lab_=(70, 10, 10))]
    by_id = {"e1": {"id": "e1", "lab": [60, 10, 10], "srgb": [9, 9, 9]}}
    still = wr.drift(layers, [colour_of(0, "e1", (60, 10, 10))], by_id, candidates((60.2, 10, 10)), {"e1"})
    assert still["layers"][0]["proposals"][0]["entry_id"] is None                           # nothing nearer than the colour it has
    gone = wr.drift(layers, [colour_of(0, "e1", (70, 10, 10), status="excluded")], by_id, candidates((70, 10, 10)), {"e1"})
    assert gone["layers"][0]["proposals"] == []


def test_a_promised_layer_whose_recipe_the_work_no_longer_uses_is_settled_and_not_listed():
    layers = [layer(1, lab_=(70, 10, 10))]
    by_id = {"e1": {"id": "e1", "lab": [58, 10, 10], "srgb": [9, 9, 9]}}
    assert wr.drift(layers, [colour_of(0, "e9", (70, 10, 10))], by_id, candidates((70, 10, 10)), {"e9"})["layers"] == []


def test_a_layer_whose_recipe_is_not_measured_any_more_has_no_colour_now_and_a_replacement_for_every_colour():
    layers = [layer(1, lab_=(70, 10, 10))]
    found = wr.drift(layers, [colour_of(0, "e1", (68, 10, 10))], {}, candidates((68.5, 10, 10)), {"e1"})
    (moved,) = found["layers"]
    assert moved["missing"] is True and moved["now_lab"] is None and moved["delta_e"] is None
    assert moved["proposals"][0]["entry_id"] == "c0" and moved["proposals"][0]["delta_e_now"] is None


# -- the work ---------------------------------------------------------------------------------------------------------------------------------
def exported(c, j) -> dict:
    """The work after a LightBurn file was made from it."""
    r = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert r.status_code == 200, r.text
    return pl.get_plan(c["store"], j["id"])


def engrave(c, j, labs=None, settings=None, engraving="eng-1", mode="reference_chart_corrected", plan_id=None) -> int:
    """An accepted pair linked to the work whose observations are the layers of its last export, each measured at ``labs[i]`` (as promised
    when not given) with ``settings[i]`` (as exported when not given)."""
    store, w = c["store"], c["w"]
    plan = pl.get_plan(store, j["id"])
    promise = plan["exports"][-1]["promised"]
    pair = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,material_id,plan_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,"
        "context_json,data_json,created_at) VALUES ('Accepted',?,?,?,?,?,?,'a.lbrn2','/x','IMG_1.DNG','/y','{}','{}',?)",
        (w["setup"][0], w["setup"][1], w["stand"]["id"], c["ti"], plan["id"] if plan_id is None else plan_id, engraving, now())).lastrowid
    for n, p in enumerate(promise):
        s = (settings or {}).get(n, p["settings"])
        parameters = su.parameter_vector(w["device"]["passport"], s["power"], s["frequency"], s["speed"], s.get("pulse_width", 200), s["line_interval"],
                                         int(s.get("passes", 1)))
        evidence = {"role": "test feature", "layer_name": p["name"], "color_measurement": {"mode": mode}}
        c["store"].execute(
            "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
            "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at,task_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pair, n + 1, w["setup"][0], w["setup"][1], engraving, json.dumps((labs or {}).get(n, p["lab"])), json.dumps(parameters), "markers",
             json.dumps({"material_id": c["ti"]}), 0, 0, "test", json.dumps(evidence), now(), None))
    return pair


def test_an_export_keeps_what_every_layer_promised_apart_from_the_work_that_may_be_recoloured_later(work, job):
    plan = exported(work, job)
    (export,) = plan["exports"]
    assert [p["index"] for p in export["promised"]] == [l["index"] for l in plan["layers"]]
    first = export["promised"][0]
    assert {"power", "frequency", "speed", "line_interval"} <= set(first["settings"]) and first["lab"] and first["region_ids"] and first["area_mm2"] > 0
    shown = work["client"].get(f"/api/vector/{job['id']}").json()
    assert all("promised" not in e for e in shown["exports"])                              # the screen gets the list of files, not their promises
    # REQ-047 crit. 1: per layer the colour the preview showed and its basis, as the palette measured the layer's recipe
    entries = {e["id"]: e for e in work["client"].get("/api/vector-palette", params={"device_id": work["w"]["setup"][0], "lens_id": work["w"]["setup"][1],
                                                                                     "material_id": work["ti"]}).json()["entries"]}
    layers = {layer["index"]: layer for layer in shown["layers"]}
    for promised in export["promised"]:
        assert promised["basis"] and promised["basis"] == entries[promised["entry_id"]]["basis"]
        assert promised["lab"] == pytest.approx(layers[promised["index"]]["lab"]) and promised["srgb"] == layers[promised["index"]]["srgb"]


def test_the_photograph_of_an_engraving_is_set_against_the_promise_by_settings_and_the_conclusion_goes_into_the_work(work, job):
    c, j = work, job
    plan = exported(c, j)
    n = len(plan["layers"])
    labs = {0: [plan["layers"][0]["lab"][0] - 9, *plan["layers"][0]["lab"][1:]]}          # the first layer came out 9 L* darker
    pair = engrave(c, j, labs=labs)
    concluded = work_errors.after_acceptance(c["store"], pair)
    review = concluded["review"]
    assert concluded["plan_id"] == j["id"] and concluded["work"] == "Portrait"
    assert review["summary"]["matched"] == n and review["summary"]["beyond_layers"] == 1 and review["approximate"] is False
    first = review["rows"][0]
    assert first["dL"] == pytest.approx(-9) and first["beyond"] is True and first["promised_name"] == plan["layers"][0]["name"]
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    assert [r["engraving_id"] for r in view["reviews"]] == ["eng-1"] and view["reviews"][0]["rows"][0]["dL"] == pytest.approx(-9)
    listed = next(w for w in works(c) if w["id"] == j["id"])
    assert listed["review"]["matched"] == n and listed["review"]["beyond_layers"] == 1 and listed["review"]["photo_name"] == "IMG_1.DNG"


def test_a_file_that_is_not_the_one_the_work_exported_matches_nothing_and_says_so(work, job):
    c, j = work, job
    plan = exported(c, j)
    other = {n: {**p["settings"], "speed": p["settings"]["speed"] * 2} for n, p in enumerate(plan["exports"][-1]["promised"])}
    review = work_errors.after_acceptance(c["store"], engrave(c, j, settings=other))["review"]
    assert review["rows"] == [] and review["summary"]["matched"] == 0
    assert len(review["unmatched"]) == len(plan["layers"]) and len(review["not_engraved"]) == len(plan["layers"])


def test_a_new_measurement_of_the_same_engraving_replaces_its_review_and_another_engraving_adds_one(work, job):
    c, j = work, job
    exported(c, j)
    work_errors.after_acceptance(c["store"], engrave(c, j, engraving="eng-1"))
    work_errors.after_acceptance(c["store"], engrave(c, j, engraving="eng-1", labs={0: [10, 0, 0]}))
    assert [r["engraving_id"] for r in pl.get_plan(c["store"], j["id"])["reviews"]] == ["eng-1"]
    work_errors.after_acceptance(c["store"], engrave(c, j, engraving="eng-2"))
    assert sorted(r["engraving_id"] for r in pl.get_plan(c["store"], j["id"])["reviews"]) == ["eng-1", "eng-2"]


def test_a_work_exported_before_promises_were_kept_is_reviewed_against_its_layers_and_the_review_says_it_is_approximate(work, job):
    c, j = work, job
    plan = exported(c, j)
    pair = engrave(c, j)
    del plan["exports"][-1]["promised"]
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])
    review = work_errors.review_pair(c["store"], pair)
    assert review["approximate"] is True and review["export_number"] == 1 and review["summary"]["matched"] == len(plan["layers"])


def test_the_review_of_a_file_made_before_promises_were_kept_claims_nothing_once_the_work_was_recoloured(work, job):
    c, j = work, job
    plan = exported(c, j)
    pair = engrave(c, j)
    del plan["exports"][-1]["promised"]
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])
    colouring(c, j, op="assign", mode="random")                                              # recoloured since the file: its promise is lost
    review = work_errors.review_pair(c["store"], pair)
    assert review["promise_lost"] is True and review["approximate"] is False and review["export_number"] == 1
    assert review["rows"] == [] and review["not_engraved"] == [] and review["summary"]["matched"] == 0
    assert len(review["unmatched"]) == len(plan["layers"])                                    # what the photograph measured is still listed
    colouring(c, j, op="undo")                                                                # the file's colouring again: reconstructed
    again = work_errors.review_pair(c["store"], pair)
    assert again["promise_lost"] is False and again["approximate"] is True and again["summary"]["matched"] == len(plan["layers"])


def test_a_file_made_before_promises_were_kept_is_reconstructed_from_the_layers_while_the_colouring_is_unchanged(work, job):
    c, j = work, job
    plan = exported(c, j)
    del plan["exports"][-1]["promised"]
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])
    baseline, approximate = wr.baseline_of(pl.get_plan(c["store"], j["id"]))
    assert approximate is True and [b["index"] for b in baseline] == [l["index"] for l in plan["layers"]]
    assert c["client"].get(f"/api/vector/{j['id']}").json()["attention"]["approximate"] is True
    colouring(c, j, op="assign", mode="random")                                              # recoloured since the file: its promise is lost
    assert wr.baseline_of(pl.get_plan(c["store"], j["id"])) == (None, False)
    assert c["client"].get(f"/api/vector/{j['id']}").json()["attention"] is None


def test_a_pair_linked_to_no_vector_work_has_no_review(work, job):
    c, j = work, job
    exported(c, j)
    pair = engrave(c, j)
    c["store"].execute("UPDATE pair SET plan_id=NULL WHERE id=?", (pair,))
    assert work_errors.review_pair(c["store"], pair) is None and work_errors.after_acceptance(c["store"], pair) is None


def test_the_picture_of_the_result_paints_each_region_in_the_colour_its_layer_measured(work, job):
    c, j = work, job
    exported(c, j)
    mark = [90.0, 60.0, 40.0]                                                              # a red nothing else in the work has
    work_errors.after_acceptance(c["store"], engrave(c, j, labs={0: mark}))
    r = c["client"].get(f"/api/vector/{j['id']}/engraved.png", params={"engraving": "eng-1"})
    img = pixels(r)
    assert share(img, [int(v) for v in color.lab_to_srgb8(mark)]) > 0.001
    missing = c["client"].get(f"/api/vector/{j['id']}/engraved.png", params={"engraving": "nope"})
    assert missing.status_code == 404


def test_the_report_of_a_pair_carries_the_review_of_its_work(work, job):
    c, j = work, job
    exported(c, j)
    pair = engrave(c, j)
    work_errors.after_acceptance(c["store"], pair)
    report = c["client"].get(f"/api/pairs/{pair}/report").json()
    assert report["work_review"]["plan_id"] == j["id"] and report["work_review"]["review"]["summary"]["matched"] > 0


def test_deleting_the_only_photograph_of_an_engraving_takes_its_review_out_of_the_work(work, job):
    c, j = work, job
    exported(c, j)
    pair = engrave(c, j)
    work_errors.after_acceptance(c["store"], pair)
    assert c["client"].delete(f"/api/pairs/{pair}").status_code == 204
    assert pl.get_plan(c["store"], j["id"]).get("reviews") == []


def test_the_review_stays_while_another_photograph_of_the_same_engraving_is_still_accepted(work, job):
    """REQ-047 crit. 5: one review per engraving; deleting a photograph removes it only when it was the engraving's last."""
    c, j = work, job
    exported(c, j)
    first = engrave(c, j)
    work_errors.after_acceptance(c["store"], first)
    second = engrave(c, j, labs={0: [10.0, 0.0, 0.0]})                                         # a second photograph of eng-1
    work_errors.after_acceptance(c["store"], second)
    assert [r["pair_id"] for r in pl.get_plan(c["store"], j["id"])["reviews"]] == [second]
    assert c["client"].delete(f"/api/pairs/{first}").status_code == 204
    assert [r["pair_id"] for r in pl.get_plan(c["store"], j["id"])["reviews"]] == [second]           # eng-1 is still photographed
    assert c["client"].delete(f"/api/pairs/{second}").status_code == 204
    assert pl.get_plan(c["store"], j["id"])["reviews"] == []


def test_measuring_a_photograph_again_through_the_api_replaces_the_review_of_its_engraving(work, job, monkeypatch):
    """REQ-047 crit. 5: the re-measure route puts the review of the new measurement in place of the old one. What ``ingest.remeasure_pair``
    does when the new measurement comes out whole (the old pair deleted, the same engraving accepted again) is done here directly: a
    vector work's own photograph is not synthesised."""
    c, j = work, job
    plan = exported(c, j)
    old = engrave(c, j)
    work_errors.after_acceptance(c["store"], old)
    darker = [plan["layers"][0]["lab"][0] - 9, *plan["layers"][0]["lab"][1:]]

    def remeasured(store, pair_id, on_accepted=None):
        store.execute("UPDATE pair SET status='Deleted' WHERE id=?", (pair_id,))
        return {"pair_id": pair_id, "status": "replaced", "replaced_by": engrave(c, j, labs={0: darker}), "reason": None, "layers": []}
    monkeypatch.setattr(ingest, "remeasure_pair", remeasured)
    answer = c["client"].post(f"/api/pairs/{old}/remeasure")
    assert answer.status_code == 200 and answer.json()["status"] == "replaced"
    (review,) = pl.get_plan(c["store"], j["id"])["reviews"]
    assert review["pair_id"] == answer.json()["replaced_by"] and review["engraving_id"] == "eng-1"
    assert review["rows"][0]["dL"] == pytest.approx(-9) and review["summary"]["beyond_layers"] == 1


def test_a_copy_of_a_work_starts_without_the_photographs_of_the_engraving_of_the_first(work, job):
    c, j = work, job
    exported(c, j)
    work_errors.after_acceptance(c["store"], engrave(c, j))
    copy_id = c["client"].post(f"/api/vector/{j['id']}/copy", json={}).json()["id"]
    assert "reviews" not in pl.get_plan(c["store"], copy_id) and c["client"].get(f"/api/vector/{copy_id}").json()["reviews"] == []


# -- the drift in a work ------------------------------------------------------------------------------------------------------------------------
def moved(c, j, entry_id, shift=14.0) -> dict:
    """The last file of the work promised the colour of the layer of ``entry_id`` ``shift`` L* away from what the palette gives now."""
    plan = pl.get_plan(c["store"], j["id"])
    promised = next(l for l in plan["exports"][-1]["promised"] if l["entry_id"] == entry_id)
    promised["lab"][0] += shift
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])
    return promised


def test_a_layer_whose_titanium_colour_moved_since_the_operator_saw_it_is_listed_and_a_replacement_applies_as_an_edit(work, job):
    c, j = work, job
    ids = palette_ids(c)
    fast, exact = ids[(round(lab(PAPER)[0] - 2), 3000)], ids[(round(lab(PAPER)[0]), 500)]       # the same paper twice, the fast one 2 dE darker
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    exported(c, j)
    seen_layer = moved(c, j, fast)
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    (drifted,) = view["attention"]["layers"]
    assert drifted["entry_id"] == fast and drifted["delta_e"] == pytest.approx(14.0, abs=0.5)
    assert view["attention"]["area_share"] > 0
    proposal = next(p for p in drifted["proposals"] if p["colour"] == by_rgb(j, PAPER)["index"])      # every source colour that uses the layer is judged
    assert proposal["entry_id"] == exact and proposal["delta_e_proposed"] < proposal["delta_e_now"] - wr.IMPROVE_DE
    done = colouring(c, view, op="set_colour", colour=proposal["colour"], entry_id=proposal["entry_id"])
    assert by_rgb(done, PAPER)["entry_id"] == exact
    (still,) = done["attention"]["layers"]                                                 # the yellow still uses the recipe, and no measured colour is nearer
    assert still["entry_id"] == fast and [p["colour"] for p in still["proposals"]] == [by_rgb(done, YELLOW)["index"]]
    assert still["proposals"][0]["entry_id"] is None
    undone = c["client"].post(f"/api/vector/{j['id']}/colouring", json={"op": "undo"}).json()
    assert by_rgb(undone, PAPER)["entry_id"] == fast and len(undone["attention"]["layers"][0]["proposals"]) == 2    # undone: both colours again


def test_a_proposed_replacement_changes_nothing_in_the_work_until_the_operator_applies_it(work, job):
    """REQ-047 crit. 7: nothing is applied by the system; showing the proposal, counting the works again and listing them leave the colouring,
    its steps and the file's promise as they were."""
    c, j = work, job
    ids = palette_ids(c)
    fast, exact = ids[(round(lab(PAPER)[0] - 2), 3000)], ids[(round(lab(PAPER)[0]), 500)]
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    exported(c, j)
    moved(c, j, fast)
    before = pl.get_plan(c["store"], j["id"])
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    assert any(p["entry_id"] == exact for p in view["attention"]["layers"][0]["proposals"])           # proposed ...
    work_errors.after_change(c["store"], c["w"]["setup"][0], c["w"]["setup"][1])
    assert next(w for w in works(c) if w["id"] == j["id"])["attention"]["proposals"] >= 1
    again = c["client"].get(f"/api/vector/{j['id']}").json()
    after = pl.get_plan(c["store"], j["id"])
    assert by_rgb(again, PAPER)["entry_id"] == fast and again["undo"] == view["undo"]                     # ... and not applied
    assert after["colouring"] == before["colouring"] and len(after["undo"]) == len(before["undo"]) and after["redo"] == before["redo"]
    assert [e["promised"] for e in after["exports"]] == [e["promised"] for e in before["exports"]]


def test_the_list_of_works_counts_the_drifted_layers_from_what_the_work_stored_and_new_measurements_refresh_it(work, job):
    c, j = work, job
    ids = palette_ids(c)
    fast = ids[(round(lab(PAPER)[0] - 2), 3000)]
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    assert c["client"].get(f"/api/vector/{j['id']}").json()["attention"] is None                    # never exported: nothing was promised
    exported(c, j)
    moved(c, j, fast)
    work_errors.after_change(c["store"], c["w"]["setup"][0], c["w"]["setup"][1])
    after = next(w for w in works(c) if w["id"] == j["id"])
    assert after["attention"]["layers"] == 1 and after["attention"]["area_share"] > 0 and "checked_at" in after["attention"]
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    exact = ids[(round(lab(PAPER)[0]), 500)]
    for colour in (by_rgb(view, PAPER), by_rgb(view, YELLOW)):                                              # the work no longer uses that recipe
        view = colouring(c, view, op="set_colour", colour=colour["index"], entry_id=exact)
    work_errors.after_change(c["store"], c["w"]["setup"][0], c["w"]["setup"][1])
    assert next(w for w in works(c) if w["id"] == j["id"])["attention"]["layers"] == 0


def photographed_plate(c) -> int:
    """A calibration plate engraved with the works' laser and lens on Grade 5 titanium (its colours are no colour of the Grade 2 works) and
    photographed: a real pair, waiting for its check."""
    store, w = c["store"], c["w"]
    store.set_setting("allow_non_raw_photos", True)                                         # tests use PNG renders; real use requires RAW
    rod = su.save_material(store, "Grade 5 rod", grade="Grade 5", thickness_mm=1, surface="brushed")["id"]
    plan = pl.get_plan(store, pl.create_plate_series(store, w["setup"][0], "10 20", "40 80", "900", 5, 4, 1, **JOB)[0]["plan_id"])
    photo = synth.plate_photo(plan, CELLS, gains=(0.9, 0.97, 1.08))
    return ingest.create_pair(store, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="plate.lbrn2",
                              lightburn_bytes=pl.export_lbrn2(plan), photo_name="plate.png", photo_bytes=cv2.imencode(".png", photo)[1].tobytes(),
                              context={"material_id": rod})


def test_accepting_measuring_again_and_deleting_a_photograph_through_the_api_count_again_every_work_of_its_laser_and_lens(work, job):
    """REQ-047 crit. 6: the routes, not only ``after_change``, refresh the drifted layers the list of works shows, for every work of the laser
    and lens (here a plate's photograph that belongs to none of them); a work never exported has no count."""
    c, client = work, work["client"]
    fast = palette_ids(c)[(round(lab(PAPER)[0] - 2), 3000)]
    first = colouring(c, job, op="set_colour", colour=by_rgb(job, PAPER)["index"], entry_id=fast)
    second = create(c).json()
    second = colouring(c, second, op="set_colour", colour=by_rgb(second, PAPER)["index"], entry_id=fast)
    never = create(c).json()
    for j in (first, second):
        exported(c, j)
        moved(c, j, fast)

    def counted() -> dict:
        return {w["id"]: None if w["attention"] is None else w["attention"]["layers"] for w in works(c) if w["id"] in (first["id"], second["id"], never["id"])}
    assert counted() == {first["id"]: None, second["id"]: None, never["id"]: None}                # nothing counted since the files were made
    pair = photographed_plate(c)
    assert client.post(f"/api/pairs/{pair}/check", json={}).json()["status"] == "Ready to accept"
    assert client.post(f"/api/pairs/{pair}/review-masks").status_code == 200
    accepted = client.post(f"/api/pairs/{pair}/accept")
    assert accepted.status_code == 200 and accepted.json()["work_review"] is None                     # the plate is no work's
    assert counted() == {first["id"]: 1, second["id"]: 1, never["id"]: None}
    moved(c, first, fast, shift=-14.0)                                                                  # its file promised what the recipe gives now
    again = client.post(f"/api/pairs/{pair}/remeasure").json()
    assert again["status"] == "replaced", again
    assert counted() == {first["id"]: 0, second["id"]: 1, never["id"]: None}
    moved(c, second, fast, shift=-14.0)
    assert client.delete(f"/api/pairs/{again['replaced_by']}").status_code == 204
    assert counted() == {first["id"]: 0, second["id"]: 0, never["id"]: None}


def test_a_work_exported_before_the_counts_were_kept_gets_them_once_when_the_app_starts(work, job):
    c, j = work, job
    ids = palette_ids(c)
    fast = ids[(round(lab(PAPER)[0] - 2), 3000)]
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    exported(c, j)
    moved(c, j, fast)
    plan = pl.get_plan(c["store"], j["id"])
    plan.pop("attention", None)
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])
    pair = engrave(c, j)                                                                          # accepted before the review existed
    assert work_errors.refresh_missing(c["store"]) == 2 and pl.get_plan(c["store"], j["id"])["attention"]["layers"] == 1
    assert [r["pair_id"] for r in pl.get_plan(c["store"], j["id"])["reviews"]] == [pair]
    assert work_errors.refresh_missing(c["store"]) == 0                                       # counted and reviewed: not again
    never = c["client"].post("/api/vector", data={"device_id": c["w"]["setup"][0], "lens_id": c["w"]["setup"][1], "material_id": c["ti"], "name": "Never",
                                                  "width_mm": 60, "strategy": "photo", "n_colors": 5, "threshold": 6}, files={"image": ("p.png", picture(), "image/png")})
    assert never.status_code == 201 and work_errors.refresh_missing(c["store"]) == 0           # a work never exported is left alone
