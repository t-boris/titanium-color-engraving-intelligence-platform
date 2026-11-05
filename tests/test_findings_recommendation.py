"""The findings as a decision queue (feature ux-evidence-summaries-p0, REQ-002, DEC-001): each finding carries the ONE next step the server
recommends for it, from rules kept as data beside the actions a finding offers. A measurement that looks wrong is looked at again before it
is taken out of the calculation; when the corrective choice is ambiguous the evidence is opened first; a run that is not the latest never
recommends a corrective action; what the finding offers (``remedies``), the marks and the order of the list are unchanged."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import obs  # noqa: E402
from titanium_platform import findings as fd, knowledge as kn, plans as pl, recheck as rc, setup as su  # noqa: E402
from titanium_platform.api.app import create_app  # noqa: E402

ACTIONS = {"none", "remeasure", "open_evidence", "propose_experiment", "acknowledge"}
PHOTO_ACTIONS = {"none", "open_evidence", "make_plate", "open_scales", "add_photograph"}


def world(store):
    w = obs.setup(store)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    w["stock"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    return w


def add(store, w, lab, **kw):
    return obs.add(store, w, lab, **{"material_id": w["stock"]["id"], "layer_type": "Scan", "power": 40, **kw})


def latest(store, **kw):
    return fd.findings_of(store, fd.get_run(store)["id"], **kw)["findings"]


@pytest.fixture
def anomaly_world(store):
    """One recipe engraved three times; the third lies far from the other two: an anomaly beyond the saved tolerance."""
    w = world(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=5, variance_threshold=4.0)
    w["good"] = [add(store, w, (50, 0, 0)), add(store, w, (51, 0, 0))]
    w["bad"] = add(store, w, (80, 0, 0))
    kn.refresh(store, *w["setup"])
    fd.run_analysis(store, "manual")
    return w


def anomaly_of(store):
    return next(f for f in latest(store) if f["kind"] == "anomaly")


# -- the rules are data, read in order -------------------------------------------------------------------------------------------
def test_the_rules_are_data_named_ordered_and_end_with_one_that_fits_everything():
    ids = [r["id"] for r in fd.RECOMMENDATION_RULES]
    assert len(ids) == len(set(ids)) and ids[0] == "already_handled"
    assert {r["action"] for r in fd.RECOMMENDATION_RULES} <= ACTIONS
    assert set(fd.RECOMMENDATION_RULES[-1]) == {"id", "action"}                       # the last rule has no condition
    # the remeasure advice is read before any corrective choice, so a measurement is looked at again before it is taken out (DEC-001)
    assert ids.index("recheck_running") < ids.index("measurement_anomaly") < ids.index("corrective_choice_ambiguous")
    assert set(fd.CORRECTIVE) == {"exclude_measurement", "count_from_latest", "confirm_questioned"}


def finding(**kw):
    return {"kind": "anomaly", "subkind": "observation", "state": "attention", "remedies": [], "evidence": {}, **kw}


OFFERED = [{"action": "exclude_measurement", "observation_id": 7}, {"action": "remeasure", "pair_id": 3}, {"action": "count_from_latest"}]


def test_an_actionable_measurement_anomaly_recommends_measuring_its_photograph_again():
    r = fd.recommend(finding(remedies=OFFERED, evidence={"observation_ids": [7], "pair_ids": [3]}))
    assert r == {"action": "remeasure", "rule": "measurement_anomaly", "pair_id": 3}


def test_an_ambiguous_corrective_choice_recommends_opening_the_evidence_first():
    only_corrective = [r for r in OFFERED if r["action"] != "remeasure"]
    r = fd.recommend(finding(remedies=only_corrective, evidence={"observation_ids": [7], "pair_ids": [3]}))
    assert r == {"action": "open_evidence", "rule": "corrective_choice_ambiguous", "target": {"kind": "pair", "id": 3}}

    unstable = finding(kind="unstable", subkind="variance", remedies=[{"action": "count_from_latest"}], evidence={"pair_ids": [4, 5], "knowledge_id": 9})
    assert fd.recommend(unstable)["target"] == {"kind": "pair", "id": 4}

    questioned = finding(kind="unstable", subkind="questioned", remedies=[{"action": "count_from_latest"}, {"action": "confirm_questioned", "knowledge_id": 9}],
                         evidence={"knowledge_id": 9, "pair_ids": [4]})
    assert fd.recommend(questioned) == {"action": "open_evidence", "rule": "corrective_choice_ambiguous", "target": {"kind": "knowledge", "id": 9}}


def test_a_finding_of_an_earlier_run_never_recommends_a_corrective_action():
    """An earlier run offers no remedies (the data moved on): what is left is to read the evidence, never to remeasure or take out."""
    r = fd.recommend(finding(remedies=[], evidence={"observation_ids": [7], "pair_ids": [3]}))
    assert r["action"] == "open_evidence" and r["rule"] == "evidence_to_read" and r["target"] == {"kind": "pair", "id": 3}
    assert r["action"] not in ("remeasure",) and "pair_id" not in r


def test_while_every_work_is_rechecked_no_corrective_action_is_recommended():
    r = fd.recommend(finding(remedies=OFFERED, evidence={"observation_ids": [7], "pair_ids": [3]}), busy=True)
    assert r == {"action": "open_evidence", "rule": "recheck_running", "target": {"kind": "pair", "id": 3}}
    gap = {"kind": "gap", "subkind": "target_missing", "proposable": True, "remedies": [], "evidence": {}}
    assert fd.recommend(gap, busy=True)["action"] == "propose_experiment"                # only the corrective steps wait for the re-check
    assert fd.recommend(finding(remedies=OFFERED, evidence={"observation_ids": [7]}), busy=True)["rule"] == "nothing_to_do"      # nothing to open: no advice


def test_a_finding_the_operator_dealt_with_recommends_nothing_new():
    for state in ("acknowledged", "hidden"):
        assert fd.recommend(finding(remedies=OFFERED, state=state)) == {"action": "none", "rule": "already_handled"}


def test_gaps_improvements_hypotheses_and_findings_without_evidence():
    gap = {"kind": "gap", "subkind": "target_missing", "proposable": True, "remedies": [], "evidence": {"target_id": 1}}
    assert fd.recommend(gap) == {"action": "propose_experiment", "rule": "experiment_for_gap"}
    assert fd.recommend({**gap, "proposable": False}) == {"action": "acknowledge", "rule": "nothing_to_do"}
    assert fd.recommend({"kind": "improvement", "subkind": "validated", "remedies": [], "evidence": {"pair_ids": [1]}}) == {"action": "acknowledge", "rule": "good_news"}
    insight = {"kind": "hypothesis", "subkind": "insight", "remedies": [], "evidence": {"session_id": 5, "pair_ids": [1]}}
    assert fd.recommend(insight)["target"] == {"kind": "research", "id": 5}
    assert fd.recommend({"kind": "gap", "subkind": "coverage", "remedies": [], "evidence": {}})["action"] == "acknowledge"
    assert fd.evidence_target({"evidence": {"knowledge_ids": [11, 12]}}) == {"kind": "knowledge", "id": 11}
    assert fd.evidence_target({"evidence": {}}) is None and fd.evidence_target({}) is None


# -- on real findings ------------------------------------------------------------------------------------------------------------
def test_the_anomaly_of_the_latest_run_recommends_the_remeasure_it_offers_and_keeps_every_remedy(store, anomaly_world):
    anomaly = anomaly_of(store)
    pair = store.one("SELECT pair_id FROM observation WHERE id=?", (anomaly_world["bad"],))["pair_id"]

    assert anomaly["recommendation"] == {"action": "remeasure", "rule": "measurement_anomaly", "pair_id": pair}
    assert anomaly["remedies"] == [{"action": "exclude_measurement", "observation_id": anomaly_world["bad"]},     # the other remedies stay reachable
                                   {"action": "remeasure", "pair_id": pair}, {"action": "count_from_latest"}]
    assert fd.get_finding(store, anomaly["id"])["recommendation"] == anomaly["recommendation"]


def test_after_a_new_run_the_earlier_finding_recommends_no_corrective_action_and_the_new_one_does(store, anomaly_world):
    old = anomaly_of(store)
    fd.run_analysis(store, "manual")

    earlier = next(f for f in fd.findings_of(store, old["run_id"])["findings"] if f["kind"] == "anomaly")
    now = anomaly_of(store)

    assert earlier["remedies"] == [] and earlier["recommendation"]["action"] == "open_evidence"
    assert fd.get_finding(store, old["id"])["recommendation"]["action"] == "open_evidence"
    assert now["recommendation"]["action"] == "remeasure" and now["run_id"] != old["run_id"]


def test_acknowledging_takes_the_recommendation_away_and_a_change_of_substance_brings_it_back(store, anomaly_world):
    anomaly = anomaly_of(store)
    fd.mark(store, anomaly["id"], "acknowledge")
    assert anomaly_of(store)["recommendation"] == {"action": "none", "rule": "already_handled"} and anomaly_of(store)["state"] == "acknowledged"

    fd.mark(store, anomaly["id"], "reopen")
    assert anomaly_of(store)["recommendation"]["action"] == "remeasure" and anomaly_of(store)["state"] == "attention"

    fd.mark(store, anomaly["id"], "hide")
    fd.mark(store, anomaly["id"], "pin")                                  # a pin and a note do not change what is advised or the order
    fd.mark(store, anomaly["id"], "note", "looked at the photograph")
    again = anomaly_of(store)
    assert again["state"] == "hidden" and again["mark"]["pinned"] and again["mark"]["note"] == "looked at the photograph"
    assert again["recommendation"]["action"] == "none"


def test_while_a_recheck_runs_the_list_recommends_no_remeasure_and_afterwards_it_does(store, anomaly_world):
    lock = rc._lock(store)
    lock.acquire()
    try:
        busy = anomaly_of(store)
        assert busy["recommendation"]["action"] == "open_evidence" and busy["recommendation"]["target"]["kind"] == "pair"
        assert fd.get_finding(store, busy["id"])["recommendation"]["action"] == "open_evidence"
    finally:
        lock.release()
    assert anomaly_of(store)["recommendation"]["action"] == "remeasure"


def test_no_finding_recommends_a_remeasure_or_a_proposal_it_does_not_offer(store, anomaly_world):
    for f in latest(store):
        r = f["recommendation"]
        assert r["action"] in ACTIONS and r["rule"]
        if r["action"] == "remeasure":
            assert {"action": "remeasure", "pair_id": r["pair_id"]} in f["remedies"]
        if r["action"] == "propose_experiment":
            assert f["kind"] == "gap" and f["proposable"]
        if r["action"] == "open_evidence":
            assert r["target"] is not None


def test_the_order_of_the_list_and_the_counts_do_not_depend_on_the_recommendation(store, anomaly_world):
    page = fd.findings_of(store, fd.get_run(store)["id"], sort="important")
    assert [f["kind"] for f in page["findings"]] == sorted((f["kind"] for f in page["findings"]), key=fd._KIND_RANK.get)
    assert page["counts"]["state"]["attention"] == page["matched"]


# -- photo engraving follows the same queue --------------------------------------------------------------------------------------
def kind(name="grayscale", status="measured", best=True, failed=(), proposal=None):
    return {"kind": name, "status": status, "best": {"source": {"pair_id": 21, "layer": 1}} if best else None,
            "failed": [{"source": {"pair_id": p, "layer": 1}} for p in failed], "proposal": proposal}


def test_a_photo_kind_that_showed_no_picture_is_looked_at_before_a_plate_is_made():
    r = fd.photo_recommend(kind("jarvis", "failed", best=False, failed=(31, 32), proposal={"kind": "around", "plate": {"copy_mm": [1, 1]}}))
    assert r == {"action": "open_evidence", "rule": "failed_look_first", "rank": 0, "target": {"kind": "pair", "id": 31}}


def test_a_photo_kind_with_a_plate_to_make_recommends_the_plate_and_a_search_in_progress_its_next_plate():
    searching = fd.photo_recommend(kind("grayscale", "searching", proposal={"kind": "next", "pair_id": 44, "plate": None}))
    assert searching == {"action": "make_plate", "rule": "plate_offered", "rank": 2, "proposal": "next", "pair_id": 44}
    around = fd.photo_recommend(kind("jarvis", "measured", proposal={"kind": "around", "plate": {"copy_mm": [10, 10]}}))
    assert around == {"action": "make_plate", "rule": "plate_offered", "rank": 2, "proposal": "around"}


def test_a_photo_kind_with_nothing_to_make_reads_its_best_or_starts_where_the_kind_starts():
    settled = fd.photo_recommend(kind("grayscale", "settled", proposal=None))
    assert settled == {"action": "none", "rule": "settled", "rank": 1}                      # a search that converged asks nothing of the operator
    measured = fd.photo_recommend(kind("grayscale", "measured", proposal=None))
    assert measured == {"action": "open_evidence", "rule": "read_the_best", "rank": 3, "target": {"kind": "pair", "id": 21}}
    no_plate = fd.photo_recommend(kind("jarvis", "measured", proposal={"kind": "around", "plate": None}))        # no photographed plate to take the picture from
    assert no_plate["rule"] == "read_the_best"
    assert fd.photo_recommend(kind("grayscale", "unmeasured", best=False))["action"] == "open_scales"
    assert fd.photo_recommend(kind("stucki", "unmeasured", best=False))["action"] == "add_photograph"
    assert {fd.photo_recommend(k)["action"] for k in (kind("a", "failed", False, (1,)), kind("b", "searching", proposal={"kind": "next", "pair_id": 1}),
                                                       kind("grayscale", "unmeasured", False), kind("c", "unmeasured", False))} <= PHOTO_ACTIONS


def test_the_photo_queue_is_empty_without_a_photograph_and_gives_each_kind_its_recommendation(tmp_path, monkeypatch):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        assert client.get("/api/analysis/photo-queue").json() == []

        place = {"device_id": 1, "lens_id": None, "material_id": 2, "setup": "Laser · F-Theta", "titanium": "Grade 2",
                 "kinds": [kind("grayscale", "settled"), kind("jarvis", "failed", best=False, failed=(8,))]}
        monkeypatch.setattr(fd.photo_knowledge, "everywhere", lambda store: [place])
        queue = client.get("/api/analysis/photo-queue").json()
    assert [k["recommendation"]["action"] for k in queue[0]["kinds"]] == ["none", "open_evidence"]
    assert [k["recommendation"]["rank"] for k in queue[0]["kinds"]] == [1, 0]
