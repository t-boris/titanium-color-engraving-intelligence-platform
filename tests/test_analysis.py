import json

import cv2
import numpy as np
import pytest

import obs
from titanium_platform import analysis as an, color, conversion as cv, ingest as ig, knowledge as kn, plans as pl, profiles as pf
from titanium_platform.db import now

LIGHTNESS = {10: 20.0, 20: 40.0, 30: 60.0, 40: 80.0}


@pytest.fixture
def w(store):
    w = obs.setup(store)
    pid = w["profile"]["id"]
    pf.save_rules(store, pid, repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    pf.save_rules(store, pid, criteria_agreed=True)
    for power, l in LIGHTNESS.items():
        for dl in (-1.0, 1.0):
            obs.add(store, w, (l + dl, 0.0, 0.0), power=power)
    kn.refresh(store, pid)
    w["ids"] = {k["parameters"]["power"]: k["id"] for k in kn.list_for_profile(store, pid)}
    return w


def ramp() -> bytes:
    return cv2.imencode(".png", np.tile(np.linspace(0, 255, 100).astype(np.uint8), (20, 1)))[1].tobytes()


def accepted_pair(store, w, plan_id, measured: dict, alignment="markers", batch=None, focus=None) -> int:
    """An accepted pair for ``plan_id`` whose layers were measured as ``measured`` (layer index -> Lab)."""
    pair = store.execute(
        "INSERT INTO pair(status,profile_id,stand_id,plan_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at,accepted_at)"
        " VALUES ('Accepted',?,?,?,?,'a.lbrn2','/x','p.raw','/y',?,'{}',?,?)",
        (w["profile"]["id"], w["stand"]["id"], plan_id, f"eng-{plan_id}", json.dumps({"batch": batch, "focus": focus}), now(), now())).lastrowid
    plan = pl.get_plan(store, plan_id)
    by_index = {l["index"]: l for l in plan["layers"]}
    for idx, lab in measured.items():
        store.execute(
            "INSERT INTO observation(pair_id,layer_index,profile_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,repeat_eligible,"
            "eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,1,1,'t',?,?)",
            (pair, idx, w["profile"]["id"], f"eng-{plan_id}", json.dumps(list(lab)), json.dumps(by_index[idx]["parameters"]), alignment,
             json.dumps({"batch": batch, "focus": focus}), json.dumps({"layer_name": by_index[idx]["name"]}), now()))
    return pair


def test_the_report_needs_an_accepted_pair(store, w):
    pid = cv.create_continuous(store, w["profile"]["id"], "tonal", ramp(), 50, 4, "T")
    pending = store.execute("INSERT INTO pair(status,profile_id,stand_id,plan_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at)"
                            " VALUES ('Ready to accept',?,?,?,'x','a','/x','p','/y','{}','{}',?)", (w["profile"]["id"], w["stand"]["id"], pid, now())).lastrowid
    with pytest.raises(ig.IngestError, match="accepted pair"):
        an.report_for_pair(store, pending)


def test_tonal_reports_brightness_and_contrast_from_hand_computed_values(store, w):
    plan_id = cv.create_continuous(store, w["profile"]["id"], "tonal", ramp(), 50, 4, "T")
    # planned L per band: 20, 40, 60, 80 ; measured: 22, 38, 63, 75
    pair = accepted_pair(store, w, plan_id, {1: (22, 0, 0), 2: (38, 0, 0), 3: (63, 0, 0), 4: (75, 0, 0)})
    r = an.report_for_pair(store, pair)
    m = r["metrics"]
    assert m["kind"] == "brightness_contrast" and m["bands"] == 4
    assert m["planned_contrast"] == pytest.approx(60.0) and m["measured_contrast"] == pytest.approx(53.0)
    assert m["mean_abs_delta_l"] == pytest.approx((2 + 2 + 3 + 5) / 4) and m["monotonic"] is True
    assert [round(x["delta_l"], 6) for x in r["rows"]] == [2.0, -2.0, 3.0, -5.0]
    assert r["rows"][0]["planned_prediction"]["confidence"] is not None  # the plan's prediction is kept beside the measurement


def test_a_non_monotonic_tonal_result_is_reported_as_such(store, w):
    plan_id = cv.create_continuous(store, w["profile"]["id"], "tonal", ramp(), 50, 4, "T")
    pair = accepted_pair(store, w, plan_id, {1: (22, 0, 0), 2: (60, 0, 0), 3: (50, 0, 0), 4: (75, 0, 0)})
    assert an.report_for_pair(store, pair)["metrics"]["monotonic"] is False


def test_color_path_reports_delta_e_and_distance_from_the_trajectory(store, w):
    ids = [w["ids"][10], w["ids"][40]]   # a straight line in Lab from L=20 to L=80 (a=b=0)
    plan_id = cv.create_continuous(store, w["profile"]["id"], "color_path", ramp(), 50, 2, "P", path_ids=ids)
    plan = pl.get_plan(store, plan_id)
    assert [l["parameters"]["power"] for l in plan["layers"]] == [10, 40]
    # band 1 planned (20,0,0) measured (23,4,0): dE 5, distance to the line (a=4) 4
    # band 2 planned (80,0,0) measured (80,0,3): dE 3, distance to the line 3
    pair = accepted_pair(store, w, plan_id, {1: (23, 4, 0), 2: (80, 0, 3)})
    m = an.report_for_pair(store, pair)["metrics"]
    assert m["kind"] == "delta_e_along_path"
    assert m["mean_delta_e"] == pytest.approx(4.0) and m["max_delta_e"] == pytest.approx(5.0)
    assert m["mean_path_distance"] == pytest.approx(3.5) and m["max_path_distance"] == pytest.approx(4.0)


def test_discrete_reports_color_deviation_and_classifies_only_with_a_saved_tolerance(store, w):
    rgb = tuple(int(v) for v in color.lab_to_srgb8((40, 0, 0)))
    png = cv2.imencode(".png", np.full((20, 40, 3), rgb[::-1], np.uint8))[1].tobytes()
    plan_id = cv.start_discrete(store, w["profile"]["id"], png, 40, "D", threshold=10.0)
    cv.finalize_discrete(store, plan_id)
    planned = pl.get_plan(store, plan_id)["layers"][0]["prediction"]["lab"]
    pair = accepted_pair(store, w, plan_id, {1: (planned[0] + 4, planned[1] + 3, planned[2])})
    r = an.report_for_pair(store, pair)
    assert r["metrics"]["kind"] == "color_deviation" and r["metrics"]["max_delta_e"] == pytest.approx(5.0)
    assert r["rows"][0]["within_tolerance"] is True  # tolerance 6.0 saved in the fixture
    pf.save_rules(store, w["profile"]["id"], delta_tolerance=4.0)
    assert an.report_for_pair(store, pair)["rows"][0]["within_tolerance"] is False


def test_without_a_saved_tolerance_deviations_are_not_classified(store):
    w = obs.setup(store)
    plan_id = pl.create_plate_series  # noqa: F841 - not needed; build a plan row directly
    store.execute("INSERT INTO plan(name,mode,status,profile_id,markers,band_count,data_json,created_at) VALUES ('p',?,?,?,0,NULL,?,?)",
                  (pl.MODE_DISCRETE, "Ready to export", w["profile"]["id"], json.dumps({"layers": [{"index": 1, "name": "K1", "parameters": pf.parameter_vector(w["profile"], 10, 40, 900),
                   "regions": [], "prediction": {"lab": [50, 0, 0], "confidence": .5, "expected_delta_e": 1.0, "stability": {"assessed": True}}}]}), now()))
    pair = accepted_pair(store, w, 1, {1: (52, 0, 0)})
    r = an.report_for_pair(store, pair)
    assert r["rows"][0]["delta_e"] == pytest.approx(2.0) and r["rows"][0]["within_tolerance"] is None
    assert any("no delta E tolerance" in x for x in r["limitations"])


def test_a_pair_without_a_plan_reports_measurements_and_says_what_is_missing(store, w):
    pair = store.execute(
        "INSERT INTO pair(status,profile_id,stand_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at,accepted_at)"
        " VALUES ('Accepted',?,?,'e','a','/x','p','/y','{}','{}',?,?)", (w["profile"]["id"], w["stand"]["id"], now(), now())).lastrowid
    store.execute("INSERT INTO observation(pair_id,layer_index,profile_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,repeat_eligible,"
                  "eligibility_reason,evidence_json,created_at) VALUES (?,1,?,'e',?,?,'manual','{}',1,1,'t','{}',?)",
                  (pair, w["profile"]["id"], json.dumps([50, 0, 0]), json.dumps(pf.parameter_vector(w["profile"], 10, 40, 900)), now()))
    r = an.report_for_pair(store, pair)
    assert r["mode"] is None and r["rows"][0]["planned_lab"] is None and r["rows"][0]["delta_e"] is None
    text = " | ".join(r["limitations"])
    assert "no original plan" in text and "aligned manually" in text


def test_limitations_state_when_unknown_context_blocks_attribution(store, w):
    plan_id = cv.create_continuous(store, w["profile"]["id"], "tonal", ramp(), 50, 4, "T")
    obs.add(store, w, (21, 0, 0), power=10, batch="B1", focus=0.0)   # one repeat with known context, the rest unknown
    pair = accepted_pair(store, w, plan_id, {1: (22, 0, 0)}, batch=None, focus=None)
    text = " | ".join(an.report_for_pair(store, pair)["limitations"])
    assert "cannot be attributed to material batch or focus" in text


def test_the_report_never_changes_stored_measurements(store, w):
    plan_id = cv.create_continuous(store, w["profile"]["id"], "tonal", ramp(), 50, 4, "T")
    pair = accepted_pair(store, w, plan_id, {1: (22, 0, 0), 2: (38, 0, 0)})
    before = [tuple(r) for r in store.query("SELECT id, lab_json, parameters_json FROM observation ORDER BY id")]
    an.report_for_pair(store, pair)
    assert before == [tuple(r) for r in store.query("SELECT id, lab_json, parameters_json FROM observation ORDER BY id")]


def test_the_trajectory_is_the_one_planned_not_one_moved_by_the_result_being_judged(store, w):
    """Regression: the path used to be read from live knowledge, which already contained the measurement."""
    ids = [w["ids"][10], w["ids"][40]]
    plan_id = cv.create_continuous(store, w["profile"]["id"], "color_path", ramp(), 50, 2, "P", path_ids=ids)
    stored = [p["lab"] for p in pl.get_plan(store, plan_id)["transfer"]["points"]]
    assert stored == [pytest.approx([20, 0, 0]), pytest.approx([80, 0, 0])]
    pair = accepted_pair(store, w, plan_id, {1: (23, 4, 0), 2: (80, 0, 3)})
    kn.refresh(store, w["profile"]["id"])
    live = kn.get(store, w["ids"][10])["summary"]["lab"]
    assert live != pytest.approx([20, 0, 0])  # live knowledge has moved because of the new observation ...
    m = an.report_for_pair(store, pair)["metrics"]
    assert m["max_path_distance"] == pytest.approx(4.0)  # ... but the report still measures against the plan
    assert pl.get_plan(store, plan_id)["transfer"]["points"][0]["lab"] == pytest.approx([20, 0, 0])
