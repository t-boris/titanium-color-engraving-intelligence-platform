"""Analysis of the accumulated work (REQ-022): runs and their triggers, findings with evidence, uncertainty and history,
measured conclusions kept apart from anomalies and AI hypotheses, and proposals of the designer for gaps."""
import json
import threading
import time

import cv2
import pytest
from fastapi.testclient import TestClient

import obs
import synth
from titanium_platform import designer as ds, findings as fd, ingest as ig, knowledge as kn, plans as pl, setup as su
from titanium_platform.api.app import create_app
from titanium_platform.db import now


@pytest.fixture
def w(store):
    w = obs.setup(store)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    w["stock"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    return w


def add(store, w, lab, **kw):
    """A measured fill layer on the stock of the workshop (as an imported LightBurn Scan layer records it)."""
    kw = {"material_id": w["stock"]["id"], "layer_type": "Scan", **kw}
    return obs.add(store, w, lab, **kw)


def run(store, trigger="manual"):
    return fd.findings_of(store, fd.run_analysis(store, trigger)["id"])["findings"]


def one(findings, subkind):
    found = [f for f in findings if f["subkind"] == subkind]
    assert len(found) == 1, [f["key"] for f in found]
    return found[0]


def target(store, w, lab=(80.0, -10.0, 30.0)):
    return store.execute("INSERT INTO target_color(device_id,lens_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,1,?,?)",
                         (*w["setup"], json.dumps(list(lab)), f"c{lab}", now())).lastrowid


# -- AC2: what supports a finding, its context, samples and uncertainty --------------------------------------------------
def test_a_finding_names_its_evidence_context_sample_counts_and_uncertainty(store, w):
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=10, variance_threshold=2.0)
    first = add(store, w, (50, 0, 0), power=40)
    second = add(store, w, (56, 0, 0), power=40)
    again = add(store, w, (51, 0, 0), power=40, engraving="e1", rephoto=True)     # a re-photograph: a photograph, not an engraving
    kn.refresh(store, *w["setup"])

    f = one(run(store), "variance")

    pair_of = {r["id"]: r["pair_id"] for r in store.query("SELECT id, pair_id FROM observation")}
    assert f["kind"] == "unstable" and f["basis"] == "measured"
    assert f["evidence"]["observation_ids"] == [first, second, again]
    assert f["evidence"]["pair_ids"] == sorted(pair_of[i] for i in (first, second, again))
    assert f["evidence"]["knowledge_id"] == store.one("SELECT id FROM knowledge")["id"]
    assert f["samples"] == {"independent_engravings": 2, "engravings": 2, "photographs": 3, "observations": 3}
    assert f["uncertainty"]["assessed"] and f["uncertainty"]["expected_delta_e"] > 4
    assert f["uncertainty"]["confidence"] == pytest.approx(1 / 6)                  # the two engravings differ (dE 5.5): one of two agree, DEC-083
    assert f["compares"]["variance_threshold"] == 2.0 and f["compares"]["variance"] > 2.0
    assert (f["context"]["device_id"], f["context"]["lens"]["name"], f["context"]["stock"]["name"]) == \
        (w["device"]["id"], "F-Theta 174", "Grade 2 sheet")
    assert (f["task"], f["material_id"], f["setup"]) == ("fill", w["stock"]["id"], su.setup_key(*w["setup"]))
    assert f["recipe"]["parameters"]["power"] == 40 and f["statement"].startswith("repeat engravings of this recipe vary by")


def test_a_questioned_entry_is_unstable_with_the_doubt_it_carries(store, w):
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=4, variance_threshold=4.0, criteria_agreed=True)
    for lab in ((50, 0, 0), (51, 0, 0)):
        add(store, w, lab, power=30)
    kn.refresh(store, *w["setup"])
    kid = store.one("SELECT id FROM knowledge")["id"]
    kn.approve_for_production(store, kid, confirm=True)
    add(store, w, (70, 0, 0), power=30)                                        # a later engraving breaks the thresholds
    kn.refresh(store, *w["setup"])

    f = one(run(store), "questioned")

    assert f["kind"] == "unstable" and f["evidence"]["knowledge_id"] == kid and f["compares"]["stage"] == "production"
    assert f["statement"].startswith("this knowledge entry is questioned: variance")


# -- AC3: measured conclusions, exploratory anomalies and AI hypotheses are told apart --------------------------------------
def test_ai_insights_are_hypotheses_and_never_measured_conclusions(store, w):
    observation = add(store, w, (50, 0, 0), power=30)
    pair = store.one("SELECT pair_id FROM observation WHERE id=?", (observation,))["pair_id"]
    session = store.execute("INSERT INTO research_session(device_id,lens_id,material_id,goal,target,model,status,created_at,updated_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", (*w["setup"], w["stock"]["id"], "line", "thin dark line", "m", "active", now(), now())).lastrowid
    claim = "Линия при 40 % и 900 мм/с непрерывна на этой заготовке"
    store.execute("INSERT INTO research_insight(session_id,purpose,claim,confidence,evidence_pair_ids_json,created_at) VALUES (?,?,?,?,?,?)",
                  (session, "line", claim, "candidate", json.dumps([pair]), now()))

    found = run(store)

    f = one(found, "insight")
    assert (f["kind"], f["basis"], f["statement"], f["task"]) == ("hypothesis", "hypothesis", claim, "line")
    assert f["uncertainty"]["ai_confidence"] == "candidate"            # the AI's own word is kept; the basis is still a hypothesis
    assert f["evidence"]["pair_ids"] == [pair] and f["evidence"]["session_id"] == session and f["samples"]["photographs"] == 1
    assert any("hypothesis" in note for note in f["limitations"])
    assert {g["basis"] for g in found if g["kind"] != "hypothesis"} <= {"measured", "exploratory"}


def test_an_observation_beyond_the_tolerance_from_its_recipe_mean_is_an_exploratory_anomaly(store, w):
    su.save_rules(store, *w["setup"], delta_tolerance=10.0)
    for lab in ((50, 0, 0), (51, 0, 0), (52, 0, 0)):
        add(store, w, lab, power=30)
    far = add(store, w, (70, 0, 0), power=30)

    anomalies = [f for f in run(store) if f["kind"] == "anomaly"]

    assert [f["evidence"]["observation_ids"] for f in anomalies] == [[far]]
    f = anomalies[0]
    assert f["basis"] == "exploratory" and f["key"] == f"anomaly:observation:{far}"
    assert f["compares"]["rule"] == "tolerance" and f["compares"]["delta_e"] == pytest.approx(19.0)     # from the agreed colour 51, not the mean 55.75
    assert f["compares"]["reference_lab"] == pytest.approx([51.0, 0, 0]) and len(f["evidence"]["recipe_observation_ids"]) == 4


def test_without_a_tolerance_an_anomaly_is_three_standard_deviations_of_the_other_engravings(store, w):
    for lab in ((50, 0, 0), (50.5, 0, 0), (51, 0, 0)):
        add(store, w, lab, power=30)
    far = add(store, w, (60, 0, 0), power=30)

    anomalies = [f for f in run(store) if f["kind"] == "anomaly"]

    assert [f["evidence"]["observation_ids"] for f in anomalies] == [[far]]
    assert anomalies[0]["compares"]["rule"] == "three_sd" and anomalies[0]["compares"]["sd"] == pytest.approx(0.5)
    assert any("rough scale" in note for note in anomalies[0]["limitations"])


# -- the kinds: improvements, gaps ------------------------------------------------------------------------------------------
def test_a_validated_recipe_is_a_measured_improvement_that_is_new_only_in_the_run_that_first_sees_it(store, w):
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=4, variance_threshold=4.0, criteria_agreed=True)
    for lab in ((50, 0, 0), (51, 0, 0)):
        add(store, w, lab, power=30)
    kn.refresh(store, *w["setup"])

    first, second = one(run(store), "validated"), one(run(store), "validated")

    assert first["kind"] == "improvement" and first["basis"] == "measured" and first["compares"]["stage"] == "validated"
    assert first["compares"]["since"] is not None and first["new"] and not second["new"] and first["key"] == second["key"]


def test_a_target_colour_is_a_gap_until_a_cell_reaches_it_and_its_history_shows_when(store, w):
    tid = target(store, w)
    assert one(run(store), "target_missing")["statement"].endswith("no plate cell made for it has been measured")
    observation = add(store, w, (80.0, -10.0, 32.0), power=30)
    pair = store.one("SELECT pair_id FROM observation WHERE id=?", (observation,))["pair_id"]
    store.execute("INSERT INTO target_check(target_id,pair_id,observation_id,cell_id,measured_lab_json,delta_e,tolerance,within_tolerance,comparable,created_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)", (tid, pair, observation, "r1c1", json.dumps([80.0, -10.0, 32.0]), 2.0, None, None, 1, now()))
    assert "cannot be judged" in one(run(store), "target_missing")["statement"]     # no tolerance saved: not judged reached
    su.save_rules(store, *w["setup"], delta_tolerance=3.0)

    reached = one(run(store), "target_reached")

    assert reached["kind"] == "improvement" and reached["compares"]["delta_e"] == 2.0 and reached["compares"]["tolerance"] == 3.0
    assert reached["evidence"]["observation_ids"] == [observation] and reached["evidence"]["pair_ids"] == [pair]
    assert [h["kind"] for h in fd.history(store, reached["id"])] == ["improvement", "gap", "gap"]


def test_gaps_name_tasks_stocks_and_single_engraving_recipes_without_evidence(store, w):
    other = su.save_material(store, "Grade 5 sheet", grade="Grade 5")
    add(store, w, (50, 0, 0), power=30)                                         # a fill on Grade 2, one engraving
    add(store, w, (40, 0, 0), power=30, material_id=other["id"], layer_type="Cut")   # a line on Grade 5

    gaps = [f for f in run(store) if f["kind"] == "gap"]

    coverage = {(f["material_id"], f["task"]): f for f in gaps if f["subkind"] == "coverage"}
    grade2, grade5 = w["stock"]["id"], other["id"]
    assert set(coverage) == {(grade2, "line"), (grade2, "tonal_image"), (grade5, "fill"), (grade5, "tonal_image")}
    assert coverage[(grade5, "fill")]["proposable"] and not coverage[(grade2, "line")]["proposable"]   # the designer plans fill plates
    assert coverage[(grade5, "fill")]["compares"]["stocks_with_this_task"] == [grade2]
    single = {(f["material_id"], f["task"]): f for f in gaps if f["subkind"] == "single_engraving"}
    assert set(single) == {(grade2, "fill"), (grade5, "line")} and all(f["samples"]["recipes"] == 1 for f in single.values())
    assert single[(grade2, "fill")]["compares"]["engravings_needed_for_validation"] is None    # criteria not agreed


def test_a_finding_takes_the_task_stated_for_its_observations_else_the_one_their_layer_implies(store, w):
    """REQ-020 in the analysis (tasks.of_observation): letters filled with a Scan recipe and accepted as text are a text, never
    a fill of the same settings; a layer whose LightBurn mode was not recorded was a fill; an AI insight takes the task of the
    guide goal it names."""
    su.save_rules(store, *w["setup"], delta_tolerance=10.0)
    for lab in ((50, 0, 0), (51, 0, 0), (52, 0, 0)):
        add(store, w, lab, power=30, task_kind="text")
    far = add(store, w, (70, 0, 0), power=30, task_kind="text")
    add(store, w, (30, 0, 0), power=30)                                  # the same Scan settings measured as a filled region
    add(store, w, (40, 0, 0), power=60, layer_type=None)                 # no LightBurn mode recorded
    other = su.save_material(store, "Grade 5 sheet", grade="Grade 5")
    add(store, w, (45, 0, 0), power=20, material_id=other["id"], task_kind="text")
    session = store.execute("INSERT INTO research_session(device_id,lens_id,material_id,goal,target,model,status,created_at,updated_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", (*w["setup"], w["stock"]["id"], "color", "blue", "m", "active", now(), now())).lastrowid
    store.execute("INSERT INTO research_insight(session_id,purpose,claim,confidence,evidence_pair_ids_json,created_at) VALUES (?,?,?,?,?,?)",
                  (session, "color", "Синий получается при 30 %", "hypothesis", "[]", now()))

    found = run(store)

    anomaly = one(found, "observation")                  # judged within the text recipe only: the fill at L* 30 takes no part
    assert anomaly["evidence"]["observation_ids"] == [far] and anomaly["task"] == "text"
    assert anomaly["compares"]["reference_lab"] == pytest.approx([51.0, 0, 0])               # the agreed colour: the far one does not move it
    single = {(f["material_id"], f["task"]): f["samples"]["recipes"] for f in found if f["subkind"] == "single_engraving"}
    assert single == {(w["stock"]["id"], "fill"): 2, (other["id"], "text"): 1}
    grade2 = {f["task"] for f in found if f["subkind"] == "coverage" and f["material_id"] == w["stock"]["id"]}
    grade5 = {f["task"]: f for f in found if f["subkind"] == "coverage" and f["material_id"] == other["id"]}
    assert grade2 == {"line", "tonal_image"}
    assert set(grade5) == {"line", "fill", "tonal_image"} and grade5["fill"]["compares"]["tasks_on_this_stock"] == ["text"]
    assert grade5["fill"]["proposable"] and one(found, "insight")["task"] == "fill"


def test_only_fill_recipes_on_a_single_engraving_are_offered_for_a_repeat(store, w):
    """A repeat is a designer plate of fill cells: a line recipe on a single engraving is a gap the designer does not plan."""
    add(store, w, (40, 0, 0), power=30, layer_type="Cut")
    add(store, w, (45, 0, 0), power=50, task_kind="text")
    gaps = {f["task"]: f for f in run(store) if f["subkind"] == "single_engraving"}

    assert set(gaps) == {"line", "text"}
    assert all(not f["proposable"] and f["compares"]["repeatable_keys"] == [] for f in gaps.values())
    with pytest.raises(ds.DesignerError, match="fill plates"):
        fd.propose_for(store, gaps["line"]["id"])
    keys = [f["compares"]["recipes"][0]["key"] for f in gaps.values()]
    with pytest.raises(ds.DesignerError, match="filled region"):
        ds.propose_repeats(store, *w["setup"], keys)


def test_an_expected_error_that_fell_since_the_previous_run_is_an_improvement(store, w):
    for lab in ((50, 0, 0), (56, 0, 0)):
        add(store, w, lab, power=40)
    run(store)
    for lab in ((53, 0, 0), (53, 0, 0)):
        add(store, w, lab, power=40)

    f = one(run(store), "error_reduced")

    assert f["kind"] == "improvement" and f["compares"]["before"]["expected_delta_e"] == pytest.approx(18 ** 0.5)
    assert f["compares"]["after"]["expected_delta_e"] == pytest.approx(6 ** 0.5) and f["samples"]["independent_engravings"] == 4


# -- AC6: recalculation keeps history and provenance -------------------------------------------------------------------------
def test_a_later_run_recalculates_while_earlier_findings_stay_readable_with_their_run_and_inputs(store, w):
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=10, variance_threshold=2.0)
    for lab in ((50, 0, 0), (56, 0, 0)):
        add(store, w, lab, power=40)
    first = fd.run_analysis(store, "manual")
    before = fd.findings_of(store, first["id"])
    for lab in ((53, 0, 0), (53, 0, 0)):
        add(store, w, lab, power=40)

    second = fd.run_analysis(store, "acceptance")

    assert second["previous_run_id"] == first["id"] and (first["trigger"], second["trigger"]) == ("manual", "acceptance")
    assert (first["inputs"]["eligible_observations"], second["inputs"]["eligible_observations"]) == (2, 4)
    assert fd.findings_of(store, first["id"]) == before                       # the earlier run is not rewritten
    unstable = one(before["findings"], "variance")
    history = fd.history(store, unstable["id"])
    assert [h["run_id"] for h in history] == [second["id"], first["id"]] and history[1]["run_trigger"] == "manual"
    assert history[1]["compares"]["variance"] == pytest.approx(18) and history[0]["compares"]["variance"] == pytest.approx(6)
    assert [r["id"] for r in fd.list_runs(store)] == [second["id"], first["id"]]


def test_findings_are_filtered_by_kind_task_laser_and_lens_and_stock(store, w):
    other = su.save_material(store, "Grade 5 sheet", grade="Grade 5")
    add(store, w, (50, 0, 0), power=30)
    add(store, w, (40, 0, 0), power=30, material_id=other["id"], layer_type="Cut")
    run_id = fd.run_analysis(store, "manual")["id"]

    everything = fd.findings_of(store, run_id)
    lines = fd.findings_of(store, run_id, kind="gap", task="line", setup=su.setup_key(*w["setup"]), material=str(other["id"]))

    assert [(f["subkind"], f["task"], f["material_id"]) for f in lines["findings"]] == [("single_engraving", "line", other["id"])]
    assert lines["total"] == len(everything["findings"]) and everything["options"]["kinds"] == ["gap"]
    assert everything["options"]["tasks"] == ["fill", "line", "tonal_image"]
    assert [s["key"] for s in everything["options"]["stocks"]] == sorted([str(w["stock"]["id"]), str(other["id"])])
    assert fd.findings_of(store, run_id, setup="laser:99/lens:unknown")["findings"] == []


# -- AC1: triggers, the schedule, one run at a time ------------------------------------------------------------------------
def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def photographed_plate(store, w, plan_id, cell_rgb=(110, 90, 70)) -> int:
    """A checked photograph of a plate, its masks reviewed, ready to accept."""
    plan = pl.get_plan(store, plan_id)
    cells = json.loads(store.one("SELECT cells_json FROM plate WHERE id=?", (plan["plate_id"],))["cells_json"])
    pid = ig.create_pair(store, device_id=w["setup"][0], lens_id=w["setup"][1], stand_id=w["stand"]["id"], lightburn_name="plate.lbrn2",
                         lightburn_bytes=pl.export_lbrn2(plan), photo_name="plate.png", plan_id=plan_id, context={"material_id": w["stock"]["id"]},
                         photo_bytes=png(synth.plate_photo(plan, {c["id"]: cell_rgb for c in cells})))
    assert ig.check_pair(store, pid)["problems"] == []
    ig.review_masks(store, pid)
    return pid


def test_accepting_a_photograph_runs_the_analysis(tmp_path):
    app = create_app(tmp_path / "data")
    store = app.state.store
    store.set_setting("allow_non_raw_photos", True)                  # tests use PNG renders; real use requires RAW
    with TestClient(app) as client:
        w = obs.setup(store)
        pl.save_marker_layer_settings(store, 20, 60, 300)
        w["stock"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
        made = pl.create_plate_series(store, w["device"]["id"], "20,40", "100", "800", 5, 4, 1, pulse_width=200, line_interval=0.025, passes=1)
        pid = photographed_plate(store, w, made[0]["plan_id"])

        accepted = client.post(f"/api/pairs/{pid}/accept").json()

        latest = client.get("/api/analysis/runs/latest").json()
    assert latest["run"]["trigger"] == "acceptance" and accepted["analysis_run_id"] == latest["run"]["id"]
    assert latest["run"]["inputs"]["accepted_pairs"] == 1 and latest["total"] == len(latest["findings"]) > 0


def test_the_operator_runs_the_analysis_now_and_sets_its_schedule(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        scheduler = app.state.analysis_scheduler
        assert client.get("/api/analysis/runs/latest").json()["run"] is None
        assert client.get("/api/analysis/schedule").json() == {"interval_hours": 0, "last_run_at": None, "next_due_at": None, "running": False}
        assert not scheduler.running                                    # the default (0) never starts a thread

        made = client.post("/api/analysis/runs")
        assert made.status_code == 201 and made.json()["trigger"] == "manual"
        assert client.put("/api/analysis/schedule", json={"interval_hours": -1}).status_code == 422
        on = client.put("/api/analysis/schedule", json={"interval_hours": 12}).json()
        assert on["interval_hours"] == 12 and on["running"] and on["next_due_at"] > on["last_run_at"]
        assert client.get("/api/analysis/runs").json()[0]["id"] == made.json()["id"]
    assert not scheduler.running                                        # stopped with the app


def test_the_scheduler_runs_a_due_analysis_and_stops_cleanly(store, w):
    add(store, w, (50, 0, 0), power=30)
    scheduler = fd.Scheduler(store, poll_seconds=0.02)
    assert not scheduler.start_if_enabled()                             # no interval: no thread
    fd.set_interval(store, 0.0001)                                      # 0.36 s

    assert scheduler.start_if_enabled()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and store.one("SELECT COUNT(*) AS n FROM analysis_run WHERE trigger='schedule'")["n"] < 2:
        time.sleep(0.02)
    scheduler.stop()

    made = store.one("SELECT COUNT(*) AS n FROM analysis_run WHERE trigger='schedule'")["n"]
    assert made >= 2 and not scheduler.running
    time.sleep(0.5)
    assert store.one("SELECT COUNT(*) AS n FROM analysis_run")["n"] == made     # nothing runs after the stop


def test_two_analyses_of_one_database_never_run_at_once(store, w, monkeypatch):
    add(store, w, (50, 0, 0), power=30)
    with fd._lock(store):
        assert fd.run_analysis(store, "schedule", blocking=False) is None   # the scheduler skips while a run is in progress
    active, most = [0], [0]
    analyse = fd._analyse

    def slow(*args):
        active[0] += 1
        most[0] = max(most[0], active[0])
        time.sleep(0.1)
        try:
            return analyse(*args)
        finally:
            active[0] -= 1

    monkeypatch.setattr(fd, "_analyse", slow)
    threads = [threading.Thread(target=fd.run_analysis, args=(store, "manual")) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most[0] == 1 and store.one("SELECT COUNT(*) AS n FROM analysis_run")["n"] == 3


def test_the_interval_is_a_number_of_hours_from_zero(store):
    with pytest.raises(su.ValidationError, match="number of hours"):
        fd.set_interval(store, -1)
    with pytest.raises(su.ValidationError, match="number of hours"):
        fd.set_interval(store, "often")
    assert fd.schedule(store) == {"interval_hours": 0.0, "last_run_at": None, "next_due_at": None}
    assert fd.set_interval(store, 0.5)["next_due_at"] is not None and fd.due(store)


# -- a proposal for a gap ----------------------------------------------------------------------------------------------------
def seed_measurements(store, w):
    for power, frequency, speed, lab in ((20, 100, 800, (30, 5, 5)), (50, 400, 1500, (60, 20, -10)), (80, 1000, 3000, (80, -10, 30)),
                                         (35, 250, 2000, (45, 0, 15))):
        for k in range(2):
            add(store, w, (lab[0] + (-1) ** k, lab[1], lab[2]), power=power, frequency=frequency, speed=speed)


def test_a_target_gap_becomes_a_proposal_of_the_designer_linked_to_the_finding(store, w):
    seed_measurements(store, w)
    tid = target(store, w)
    gap = one(run(store), "target_missing")

    proposal = fd.propose_for(store, gap["id"])
    again = fd.propose_for(store, gap["id"])

    assert proposal["target_ids"] == [tid] and proposal["group"] == {"pulse_width": 200, "line_interval": 0.025, "passes": 1}
    assert proposal["status"] == "proposed" and [o["finding_id"] for o in proposal["origins"]] == [gap["id"]]
    assert again["id"] == proposal["id"] and [o["finding_id"] for o in again["origins"]] == [gap["id"]]    # linked once
    assert ds.get_proposal(store, proposal["id"])["status_history"][0]["finding_id"] == gap["id"]


def test_a_gap_of_fill_evidence_on_a_stock_is_proposed_for_that_stock_and_a_line_gap_is_not_planned(store, w):
    other = su.save_material(store, "Grade 5 sheet", grade="Grade 5")
    seed_measurements(store, w)
    add(store, w, (40, 0, 0), power=30, material_id=other["id"], layer_type="Cut")
    gaps = {(f["material_id"], f["task"]): f for f in run(store) if f["subkind"] == "coverage"}

    proposal = fd.propose_for(store, gaps[(other["id"], "fill")]["id"])

    # the Grade 2 fills are another stock and the Grade 5 line is another task: a fill proposal for Grade 5 models nothing
    assert proposal["stock"]["material_id"] == other["id"] and proposal["model"]["measured_sets"] == 0
    assert {x["reason"] for x in proposal["parameters"]} == {"gap"} and proposal["task"] == "fill"
    assert all(x["rationale"].startswith("nothing is measured with these job settings yet") for x in proposal["parameters"])
    with pytest.raises(ds.DesignerError, match="fill plates"):
        fd.propose_for(store, gaps[(w["stock"]["id"], "line")]["id"])


def test_recipes_on_a_single_engraving_are_proposed_for_a_repeat(store, w):
    for power in (20, 40, 60):
        add(store, w, (30 + power / 2, 0, 0), power=power)
    gap = one(run(store), "single_engraving")

    proposal = fd.propose_for(store, gap["id"], size=2)

    assert [x["reason"] for x in proposal["parameters"]] == ["repeat", "repeat"]
    assert [x["repeats"]["key"] for x in proposal["parameters"]] == sorted(gap["compares"]["repeatable_keys"])[:2]
    assert all(x["rationale"].startswith("repeats a recipe measured on a single engraving") for x in proposal["parameters"])
    assert proposal["questions"][0].startswith("Do recipes measured on a single engraving") and proposal["stock"]["material_id"] == w["stock"]["id"]
    assert fd.propose_for(store, gap["id"], size=2)["id"] == proposal["id"]
    assert len(ds.create_plates(store, proposal["id"], 5, 4, 1)) >= 1
