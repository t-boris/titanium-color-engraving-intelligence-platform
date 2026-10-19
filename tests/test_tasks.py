"""REQ-020: task-conditioned engraving knowledge. The task vocabulary and how a layer's task is derived, the task a plan, a
plate and a photographed work record, keys of existing records unchanged, unlike tasks never one summary, search and
lookups by task with their evidence, and every metric with its method and basis."""
import json
import re
import sqlite3
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import obs
import recipes
import synth
from titanium_platform import (application_guide, capability_plates as cp, colormap, conversion as cv, devices, db, experiment_library,
                               experiments, ingest as ig, knowledge as kn, lenses, model, plans as pl, tasks)
from titanium_platform import setup as su
from titanium_platform.api.app import UI_DIR, create_app
from titanium_platform.db import Store, now

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "observation_keys_ce55426.json").read_text(encoding="utf-8"))


def scan_recipe(w) -> dict:
    """A Fill-mode recipe with every preserved LightBurn setting, as an accepted observation stores it."""
    return recipes.recipes(w["device"]["passport"])["Gold fill"]


def add(store: Store, w: dict, lab, params: dict, task: dict | None = None, engraving: str | None = None, material_id=None,
        model_eligible: int = 1, pair_status: str = "Accepted", evidence: dict | None = None) -> int:
    """An accepted observation with the task it was accepted with (``None``: accepted before tasks, task_kind NULL)."""
    w["n"] += 1
    device_id, lens_id = w["setup"]
    context = {"batch": None, "focus": None, "material_id": material_id}
    pair = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,material_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,"
        "context_json,data_json,created_at,accepted_at) VALUES (?,?,?,?,?,?,'a.lbrn2','/x',?,'/y',?,'{}',?,?)",
        (pair_status, device_id, lens_id, w["stand"]["id"], material_id, engraving or f"e{w['n']}", f"p{w['n']}.raw", json.dumps(context),
         now(), now())).lastrowid
    return store.execute(
        "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
        "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at,task_kind) VALUES (?,?,?,?,?,?,?,?,?,?,1,'test',?,?,?)",
        (pair, 1, device_id, lens_id, engraving or f"e{w['n']}", json.dumps(list(lab)), json.dumps(params), "markers", json.dumps(context),
         model_eligible, json.dumps({**(evidence or {}), **({"task": task} if task else {})}), now(), task["kind"] if task else None)).lastrowid


# -- the vocabulary and the task a layer implies --------------------------------------------------------------------------
def test_the_vocabulary_has_the_tasks_of_req_020_and_the_application_guide_goals():
    assert {"text", "line", "fill", "tonal_image", "color_image"} <= set(tasks.TASKS)
    assert {"mark", "cleaning", "deep", "relief", "cutting"} <= set(tasks.TASKS)
    assert set(tasks.GOAL_TASK) == set(__import__("titanium_platform.application_guide", fromlist=["GOALS"]).GOALS)
    for row in tasks.vocabulary():
        assert set(row["metrics"]) <= set(tasks.METRICS)
        assert all(item["note"] for item in row["unavailable"])          # an unavailable metric always says why
    assert {m["metric"] for m in next(r for r in tasks.vocabulary() if r["key"] == "text")["unavailable"]} >= {"text_legibility", "line_width_um"}
    assert {m["metric"] for m in next(r for r in tasks.vocabulary() if r["key"] == "deep")["unavailable"]} == {"depth"}


@pytest.mark.parametrize("layer_type, settings, kind, image_mode", [
    ("Cut", None, "line", None), ("Scan", None, "fill", None), ("OffsetFill", None, "fill", None), ("Offset Fill", None, "fill", None),
    ("Scan+Cut", None, "fill", None), (None, None, "fill", None), ("Image", {"ditherMode": {"Value": "grayscale"}}, "tonal_image", None),
    ("Image", {"ditherMode": {"Value": "jarvis"}}, "tonal_image", "jarvis")])
def test_a_layer_without_a_stated_task_takes_the_one_its_lightburn_mode_implies(layer_type, settings, kind, image_mode):
    task = tasks.derive(layer_type, settings)
    assert (task["kind"], task["basis"], task["source"], task.get("image_mode")) == (kind, "derived", "layer", image_mode)
    assert tasks.derive("Scan", None, "pre-test cleaning witness")["kind"] == "cleaning"


def test_the_operators_layer_choice_wins_over_the_work_the_plan_and_the_layer_and_service_layers_keep_their_own():
    eff = lambda **kw: tasks.effective("Scan", None, "test feature", **kw)
    assert eff(operator="text", work="fill", plan="color_image") | {} == {"kind": "text", "basis": "explicit", "source": "operator",
                                                                             "mode": "Scan", "derived": "fill"}
    assert eff(work="mark", plan="color_image")["source"] == "work" and eff(plan="color_image")["kind"] == "color_image"
    assert eff()["basis"] == "derived" and eff(operator="layer", work="text")["kind"] == "fill"       # "по слою LightBurn"
    assert tasks.effective("Scan", None, "registration, QR and engraved labels", operator="text")["basis"] == "derived"
    with pytest.raises(su.ValidationError, match="unknown engraving task"):
        tasks.require("engraving")


def test_a_plan_states_its_layer_tasks_only_when_someone_stated_them():
    plate = {"mode": pl.MODE_CAPABILITY, "layers": [{"name": "TEXT-P10-V900", "index": 3, "task": "text"}, {"name": "LINE-P10", "index": 4, "task": "line"}],
             "engraving_task": tasks.plan_task("text")}
    assert tasks.plan_layer_task(plate, "TEXT-P10-V900", 9) == "text" and tasks.plan_layer_task(plate, "CLEAN", 0) is None
    chosen = {"mode": pl.MODE_DISCRETE, "layers": [{"name": "C01", "index": 1}], "engraving_task": tasks.plan_task("color_image")}
    default = {**chosen, "engraving_task": tasks.plan_task("color_image", basis=tasks.DERIVED)}
    assert tasks.plan_layer_task(chosen, "C01", 1) == "color_image" and tasks.plan_layer_task(default, "C01", 1) is None
    vector = {"mode": pl.MODE_VECTOR, "layers": [{"name": "K1", "index": 2, "task": None}]}          # a layer of mixed tasks
    assert tasks.plan_layer_task(vector, "K1", 2) is None
    assert tasks.layer_task_of_regions(["color", "fill", "tonal"]) == "fill" and tasks.layer_task_of_regions(["text", "fill"]) is None
    assert tasks.plate_layer_task("TEXT-MATRIX-P10-V900", "Cut") == "text" and tasks.plate_layer_task("HATCH-0.05", "Scan") == "fill"


# -- keys of existing records stay exactly as they were (REQ-020 AC8, the approach of DEC-051) ----------------------------
def test_the_key_of_every_existing_observation_is_the_key_it_had_before_tasks():
    assert len(FIXTURE["observations"]) > 100
    for o in FIXTURE["observations"]:
        derived = tasks.derive_from_parameters(o["parameters"], o["evidence"]["role"])
        stated_same = tasks.explicit(tasks.derive_from_parameters(o["parameters"])["kind"], "operator")   # stated, as the mode implies anyway
        assert model.parameters_key(o["parameters"]) == o["parameters_key"]
        for task in (None, derived, stated_same):
            assert model.observation_key(o["parameters"], o["context"], task) == o["observation_key"], o["id"]
    text = tasks.explicit("text", "operator")
    scan = next(o for o in FIXTURE["observations"] if o["parameters"].get("layer_type") == "Scan")
    assert model.observation_key(scan["parameters"], scan["context"], text) != scan["observation_key"]


def test_rows_accepted_before_tasks_keep_null_and_their_knowledge_key(store):
    w = obs.setup(store)
    pair = store.execute("INSERT INTO pair(status,device_id,lens_id,stand_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,"
                         "context_json,data_json,created_at) VALUES ('Accepted',?,?,?,'old','a.lbrn2','/x','p.raw','/y','{}','{}',?)",
                         (*w["setup"], w["stand"]["id"], now())).lastrowid
    for o in FIXTURE["observations"]:
        store.execute("INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,"
                      "context_json,model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,'x',?,?)",
                      (pair, o["id"], *w["setup"], "old", "[50,0,0]", json.dumps(o["parameters"]), "markers", json.dumps(o["context"]),
                       o["model_eligible"], json.dumps(o["evidence"]), now()))
    rows = {r["layer_index"]: r for r in store.query("SELECT * FROM observation WHERE pair_id=?", (pair,))}
    for o in FIXTURE["observations"]:
        row = rows[o["id"]]
        assert row["task_kind"] is None and tasks.of_observation(row)["basis"] == "derived"
        test_feature = (o["evidence"]["role"] or "test feature") == "test feature"
        assert model.knowledge_key_of(row) == (o["observation_key"] if o["model_eligible"] and test_feature else None)


def test_a_new_task_kind_changes_no_existing_record(monkeypatch):
    monkeypatch.setitem(tasks.TASKS, "engraved_code", {**tasks.TASKS["mark"], "name": "Engraved code"})
    for o in FIXTURE["observations"][:40]:
        assert model.observation_key(o["parameters"], o["context"], tasks.derive_from_parameters(o["parameters"])) == o["observation_key"]
    assert tasks.require("engraved_code") == "engraved_code"


def test_the_task_column_is_added_to_a_database_of_the_previous_version_without_touching_its_rows(tmp_path):
    data = tmp_path / "data"
    (data / "files").mkdir(parents=True)
    conn = sqlite3.connect(data / "titanium.sqlite")
    conn.executescript(db.SCHEMA)                       # the tables as the version before tasks created them
    conn.execute("INSERT INTO laser_device(id,name,data_json,created_at,updated_at) VALUES (1,'L','{}','t','t')")
    conn.execute("INSERT INTO pair(id,status,device_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at)"
                 " VALUES (1,'Accepted',1,'e','a.lbrn2','/x','p.raw','/y','{}','{}','t')")
    conn.execute("INSERT INTO observation(pair_id,layer_index,device_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
                 "model_eligible,repeat_eligible,eligibility_reason,created_at) VALUES (1,1,1,'e','[1,2,3]','{\"layer_type\": \"Cut\"}','m','{}',1,1,'x','t')")
    conn.commit()
    before = conn.execute("SELECT * FROM observation").fetchall()
    assert "task_kind" not in {r[1] for r in conn.execute("PRAGMA table_info(observation)")}
    conn.close()
    for _ in range(2):                                  # idempotent
        store = Store(data)
        columns = {r["name"]: r for r in store.query("PRAGMA table_info(observation)")}
        assert columns["task_kind"]["notnull"] == 0
        row = store.one("SELECT * FROM observation")
        assert tuple(row)[:len(before[0])] == before[0] and row["task_kind"] is None
        assert tasks.of_observation(row)["kind"] == "line"
        with pytest.raises(sqlite3.IntegrityError):    # still immutable
            store.execute("UPDATE observation SET task_kind='text'")
        store.close()


# -- unlike tasks are never one summary (REQ-020 AC5) ---------------------------------------------------------------------
@pytest.fixture
def two_tasks(store):
    """One Fill recipe engraved as a filled area twice (one stated, one derived) and as filled text twice."""
    w = obs.setup(store)
    params = scan_recipe(w)
    add(store, w, (50, 5, 10), params)                                                    # accepted before tasks
    add(store, w, (51, 5, 10), params, tasks.explicit("fill", "work"))                     # stated, as its mode implies
    add(store, w, (40, 2, 3), params, tasks.explicit("text", "operator"))
    add(store, w, (41, 2, 3), params, tasks.explicit("text", "plan"))
    kn.refresh(store, *w["setup"])
    return w


def test_filled_text_and_a_filled_area_of_one_fill_recipe_are_two_summaries_and_two_knowledge_entries(store, two_tasks):
    summaries = model.knowledge_summaries(store, *two_tasks["setup"])
    assert len(summaries) == 2
    by_task = {s["task"]["kind"]: s for s in summaries.values()}
    assert set(by_task) == {"fill", "text"} and by_task["fill"]["observations"] == 2 and by_task["text"]["observations"] == 2
    assert abs(by_task["text"]["lab"][0] - 40.5) < 1e-9 and abs(by_task["fill"]["lab"][0] - 50.5) < 1e-9     # never averaged together
    keys = {k["parameters_key"] for k in kn.list_for_setup(store, *two_tasks["setup"])}
    assert len(keys) == 2 and sum("|task:text" in k for k in keys) == 1
    # an area conversion never fills with a recipe measured as text; a vector job sees both, each with its task
    for entry in kn.list_for_setup(store, *two_tasks["setup"]):
        store.execute("UPDATE knowledge SET stage='validated' WHERE id=?", (entry["id"],))
    assert [e["task"] for e in cv.eligible_palette(store, *two_tasks["setup"])] == ["fill"]
    assert sorted(e["task"] for e in cv.eligible_palette(store, *two_tasks["setup"], kinds=None)) == ["fill", "text"]


def test_the_colour_map_search_keeps_tasks_apart_filters_by_task_and_discloses_its_evidence(store, two_tasks):
    found = colormap.search(store, [45, 3, 6])
    assert found["evidence"] == "observed" and len(found["matches"]) == 2
    assert {m["task"]["kind"] for m in found["matches"]} == {"fill", "text"}
    text = colormap.search(store, [45, 3, 6], task="text")["matches"]
    assert [m["task"]["kind"] for m in text] == ["text"]
    m = text[0]
    assert (m["repeats"], m["photographs"], len(m["observation_ids"])) == (2, 2, 2)
    assert m["repeatability"]["assessed"] and m["repeatability"]["max_delta_e"] == pytest.approx(0.5, abs=1e-6)
    assert {"batch_unknown"} <= set(m["missing_context"]) and "lens_unknown" not in m["missing_context"]
    data = colormap.collect(store, task="text")
    assert {p["task"]["kind"] for p in data["points"]} == {"text"} and data["options"]["tasks"] == ["text", "fill"]
    with pytest.raises(su.ValidationError):
        colormap.collect(store, task="engraving")


def test_the_result_lookup_keeps_tasks_apart_and_counts_its_evidence(store, two_tasks):
    params = scan_recipe(two_tasks)
    found = experiment_library.lookup_result(store, two_tasks["setup"][0], two_tasks["setup"][1], params)
    assert found["evidence"] == "observed" and sorted(m["task"]["kind"] for m in found["matches"]) == ["fill", "text"]
    only = experiment_library.lookup_result(store, two_tasks["setup"][0], two_tasks["setup"][1], params, task="text")["matches"]
    assert len(only) == 1 and only[0]["task"]["kind"] == "text"
    assert only[0]["sample"] == {"observations": 2, "independent_engravings": 2, "engravings": 2, "photographs": 2}
    assert only[0]["stability"]["assessed"] and "batch_unknown" in only[0]["missing_context"] and len(only[0]["observation_ids"]) == 2


def test_the_experiment_list_names_and_filters_by_task(store, two_tasks):
    listed = experiments.list_experiments(store)
    assert sorted(k for e in listed for k in e["tasks"]) == ["fill", "fill", "text", "text"]
    assert {tuple(e["tasks"]) for e in experiments.list_experiments(store, task="text")} == {("text",)}
    assert len(experiments.list_experiments(store, task="tonal_image")) == 0


# -- plans, plates and works record their task (REQ-020 AC1) --------------------------------------------------------------
def stripes():
    img = np.zeros((40, 80, 3), np.uint8)
    img[:, :40], img[:, 40:] = (40, 40, 200), (200, 60, 30)
    return cv2.imencode(".png", img)[1].tobytes()


def test_a_conversion_records_its_task_and_its_goals(store):
    w = obs.setup(store)
    chosen = cv.start_discrete(store, *w["setup"], stripes(), 40, "Logo", threshold=8.0, task="fill",
                               goals={"target_lab": [50, 10, 20], "line_width_mm": 0.1, "note": "flat areas"})
    assert pl.get_plan(store, chosen)["engraving_task"] == {"kind": "fill", "goals": {"target_lab": [50.0, 10.0, 20.0], "note": "flat areas"},
                                                            "basis": "explicit"}          # a line width is not a goal of a fill
    default = cv.start_discrete(store, *w["setup"], stripes(), 40, "Picture", threshold=8.0)
    assert pl.get_plan(store, default)["engraving_task"] == {"kind": "color_image", "goals": {}, "basis": "derived"}
    with pytest.raises(su.ValidationError, match="target colour"):
        tasks.clean_goals("fill", {"target_lab": [120, 0, 0]})
    with pytest.raises(su.ValidationError, match="positive numbers"):
        tasks.clean_goals("line", {"line_width_mm": -1})
    assert tasks.clean_goals("text", {"text_height_mm": "1.5", "legibility_note": " A8M from 1 m "}) == {"text_height_mm": 1.5,
                                                                                                         "legibility_note": "A8M from 1 m"}


def plate_hardware(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="TASK-1")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    pl.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    return laser, su.save_material(store, "Grade 2 sheet", grade="Grade 2")


def test_a_plate_records_its_task_and_every_cell_its_own(store):
    laser, titanium = plate_hardware(store)
    text = pl.get_plan(store, cp.create(store, laser["id"], titanium["id"], "text_readability", {"pulse_width": 200})["plan_id"])
    assert text["engraving_task"]["kind"] == "text" and {l["task"] for l in text["layers"]} == {"text"}
    compact = pl.get_plan(store, cp.create(store, laser["id"], titanium["id"], "compact_capability",
                                           {"pulse_width": 200, "task": "line", "task_goals": {"line_width_mm": 0.05}})["plan_id"])
    assert compact["engraving_task"] == {"kind": "line", "goals": {"line_width_mm": 0.05}, "basis": "explicit"}
    by_name = {l["name"]: l["task"] for l in compact["layers"]}
    assert {by_name[n] for n in by_name if n.startswith("TEXT")} == {"text"} and {by_name[n] for n in by_name if n.startswith("HATCH")} == {"fill"}
    assert {by_name[n] for n in by_name if n.startswith("LINE")} == {"line"}
    goal = pl.get_plan(store, cp.create(store, laser["id"], titanium["id"], "calibration", {"pulse_width": 200, "research_goal": "black_mark"})["plan_id"])
    assert goal["engraving_task"] == {"kind": "mark", "goals": {}, "basis": "derived"}


def test_the_application_guide_takes_a_task_and_names_it(store):
    laser, titanium = plate_hardware(store)
    by_task = application_guide.suggest(store, laser["id"], titanium["id"], task="text")
    assert by_task["goal"] == "text" and by_task["task"]["kind"] == "text" and by_task["support"] is None
    assert application_guide.suggest(store, laser["id"], titanium["id"], task="color_image")["goal"] == "color"
    assert application_guide.suggest(store, laser["id"], titanium["id"], "white_mark")["task"]["kind"] == "mark"
    with pytest.raises(su.ValidationError):
        application_guide.suggest(store, laser["id"], titanium["id"], task="engraving")


# -- a photographed work: the task of every layer, recorded at acceptance --------------------------------------------------
@pytest.fixture(scope="module")
def accepted(tmp_path_factory):
    """A framed finished work with a chart: the whole work is fill, one layer the operator calls text, one is left to its
    LightBurn mode. Checked, then accepted."""
    work = synth.framed_work(seed=3, blobs=60, with_chart=True, inset=8.0)
    store = Store(tmp_path_factory.mktemp("tasks"))
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")
    pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name="work.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name="work.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                         context={"material_id": material["id"]}, task="fill")
    report = ig.check_pair(store, pid)
    assert report["alignment"]["valid"] and not report["problems"], report["problems"]
    measured = [rep["index"] for rep in report["layers"] if rep["measured_lab"] and rep.get("role", "test feature") == "test feature"]
    text_layer, own_layer = measured[0], measured[1]
    ig.set_task(store, pid, text_layer, "text")
    ig.set_task(store, pid, own_layer, "layer")
    before = ig.get_pair(store, pid)
    ig.review_masks(store, pid)
    ids = ig.accept_pair(store, pid)
    kn.refresh(store, laser["id"], None)
    yield {"store": store, "pid": pid, "ids": ids, "text": text_layer, "own": own_layer, "before": before, "laser": laser}
    store.close()


def test_each_layer_shows_its_task_before_acceptance_with_where_it_came_from(accepted):
    layers = {rep["index"]: rep for rep in accepted["before"]["check"]["layers"]}
    assert accepted["before"]["work_task"] == "fill"
    assert layers[accepted["text"]]["task"] == {"kind": "text", "basis": "explicit", "source": "operator", "mode": "Scan", "derived": "fill"}
    assert layers[accepted["own"]]["task"]["basis"] == "derived" and layers[accepted["own"]]["task"]["kind"] == "fill"
    others = [rep for i, rep in layers.items() if rep["measured_lab"] and i not in (accepted["text"], accepted["own"])
              and rep.get("role", "test feature") == "test feature"]
    assert others and all(rep["task"]["source"] == "work" for rep in others)


def test_acceptance_records_each_layers_task_and_only_a_stated_different_task_changes_the_key(accepted):
    store = accepted["store"]
    rows = {json.loads(r["evidence_json"])["layer_name"]: r for r in store.query("SELECT * FROM observation WHERE pair_id=?", (accepted["pid"],))}
    names = {rep["index"]: rep["name"] for rep in accepted["before"]["check"]["layers"]}
    text, own = rows[names[accepted["text"]]], rows[names[accepted["own"]]]
    assert text["task_kind"] == "text" and json.loads(text["evidence_json"])["task"]["basis"] == "explicit"
    assert own["task_kind"] == "fill" and json.loads(own["evidence_json"])["task"]["basis"] == "derived"
    assert "|task:text" in model.knowledge_key_of(text)
    plain = [model.knowledge_key_of(r) for r in rows.values() if r["task_kind"] == "fill" and r["model_eligible"]]
    assert plain and not any("|task:" in k for k in plain)
    assert any("|task:text" in k["parameters_key"] for k in kn.list_for_setup(store, accepted["laser"]["id"], None))
    # the accepted record is immutable, its task included; the screens show the task it was accepted with
    with pytest.raises(ig.IngestError):
        ig.set_task(store, accepted["pid"], accepted["text"], "line")
    shown = {rep["index"]: rep["task"] for rep in ig.get_pair(store, accepted["pid"])["check"]["layers"]}
    assert shown[accepted["text"]]["kind"] == "text"


def test_every_measured_layer_reports_its_metrics_with_method_and_basis(accepted):
    layers = {rep["index"]: rep for rep in ig.get_pair(accepted["store"], accepted["pid"])["check"]["layers"]}
    for rep in layers.values():
        if not rep["measured_lab"]:
            continue
        for m in rep["metrics"]:
            if m["available"]:                       # a photograph with a chart: colours by the chart, widths by the registration
                assert m["method"] in tasks.METHODS and m["basis"] == ("registration_scale" if m["metric"] == "apparent_trace_width" else "chart")
            else:
                assert m["note"] and "value" not in m
    text = {m["metric"]: m for m in layers[accepted["text"]]["metrics"]}
    assert not text["text_legibility"]["available"] and not text["line_width_um"]["available"]
    report = __import__("titanium_platform.analysis", fromlist=["report_for_pair"]).report_for_pair(accepted["store"], accepted["pid"])
    assert report["photo_scale"]["px_per_mm"] > 1
    row = next(r for r in report["rows"] if r["task"]["kind"] == "text")
    assert {m["metric"] for m in row["metrics"] if not m["available"]} >= {"text_legibility"}


def test_a_new_photograph_of_the_work_keeps_its_tasks_and_they_can_change_until_it_is_accepted(accepted):
    store = accepted["store"]
    pid = ig.create_rephoto(store, accepted["pid"], photo_name="again.png", photo_bytes=b"not decoded before the check")
    again = ig.get_pair(store, pid)
    assert again["work_task"] == "fill" and again["layer_tasks"] == {str(accepted["text"]): "text", str(accepted["own"]): "layer"}
    ig.set_task(store, pid, None, "mark")
    ig.set_task(store, pid, accepted["text"], None)                         # cleared: the layer takes the work's task again
    again = ig.get_pair(store, pid)
    assert again["work_task"] == "mark" and again["layer_tasks"] == {str(accepted["own"]): "layer"}
    with pytest.raises(su.ValidationError):
        ig.set_task(store, pid, None, "engraving")


# -- metrics: method, basis, and what a photograph cannot give (REQ-020 AC6) -------------------------------------------------
def test_the_basis_of_a_colour_is_the_chart_the_clean_titanium_of_the_photograph_or_the_photograph_as_shot():
    chart = tasks.quality_metrics("fill", lab=[50, 3, 4], mode="reference_chart_corrected")
    clean = tasks.quality_metrics("fill", lab=[20, 1, 1], against_clean=[55, 3, 4], mode="raw_camera_relative")
    shot = tasks.quality_metrics("fill", lab=[20, 1, 1], mode="raw_camera_relative")
    basis = lambda metrics: {m["basis"] for m in metrics if m["available"]}
    assert basis(chart) == {"chart"} and basis(clean) == {"clean"} and basis(shot) == {"as_shot"}
    assert next(m for m in clean if m["metric"] == "lightness")["value"] == 55          # the value its basis gives
    assert next(m for m in chart if m["metric"] == "chroma")["value"] == 5.0
    assert [m["metric"] for m in chart if not m["available"]] == ["dimensional_accuracy"]


def test_a_line_width_comes_with_the_scale_of_the_registration_and_a_micrometre_width_is_unavailable():
    h = np.linalg.inv(np.array([[20.0, 0, 100], [0, 20.0, 50], [0, 0, 1]]))          # photo px -> mm at 20 px/mm
    scale = tasks.photo_scale({"image_to_mm": h.tolist(), "residual_px": 2.0})
    assert scale["px_per_mm"] == pytest.approx(20.0) and scale["uncertainty_mm"] == pytest.approx(0.1)
    assert tasks.photo_scale({"image_to_mm": h.tolist()})["uncertainty_mm"] == tasks.TRACE_SAMPLING_MM
    line = {"line_count": 5, "visible_line_count": 4, "median_continuity_percent": 92.0, "median_contrast_Lstar": 6.5,
            "median_apparent_trace_width_mm": 0.06}
    metrics = {m["metric"]: m for m in tasks.quality_metrics("line", lab=[40, 0, 0], mode="raw_camera_relative", line_metrics=line, scale=scale)}
    width = metrics["apparent_trace_width"]
    assert (width["value"], width["basis"], width["method"], width["scale"]["px_per_mm"]) == (0.06, "registration_scale", "line_profile_threshold", 20.0)
    assert metrics["line_continuity"]["basis"] == "as_shot" and metrics["line_visibility"]["value"] == [4, 5]
    assert not metrics["line_width_um"]["available"] and "calibrated image scale" in metrics["line_width_um"]["note"]
    deep = {m["metric"]: m for m in tasks.quality_metrics("deep", lab=[30, 0, 0], mode="reference_chart_corrected")}
    assert not deep["depth"]["available"] and "physical measurement" in deep["depth"]["note"]
    assert {m["metric"] for m in tasks.quality_metrics("cutting", lab=[30, 0, 0])} == {"cut_through", "kerf_width"}


# -- the API and the screens ------------------------------------------------------------------------------------------------
def test_the_api_serves_the_vocabulary_and_records_a_works_task(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        store = client.app.state.store
        assert {t["key"] for t in client.get("/api/tasks").json()} >= {"text", "line", "fill", "tonal_image", "color_image"}
        w = obs.setup(store)
        check = {"layers": [{"index": 2, "name": "C02", "type": "Scan", "measured_lab": None}], "problems": []}
        pending = store.execute(
            "INSERT INTO pair(status,device_id,lens_id,stand_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,"
            "data_json,created_at) VALUES ('Ready to accept',?,?,?,'w','a.lbrn2','/x','p.raw','/y','{}',?,?)",
            (*w["setup"], w["stand"]["id"], json.dumps({"check": check}), now())).lastrowid
        r = client.put(f"/api/pairs/{pending}/tasks", json={"layer_index": None, "task": "text"})
        assert r.status_code == 200 and r.json()["work_task"] == "text"
        assert r.json()["check"]["layers"][0]["task"]["source"] == "work"
        r = client.put(f"/api/pairs/{pending}/tasks", json={"layer_index": 2, "task": "line"})
        assert r.json()["layer_tasks"] == {"2": "line"} and r.json()["check"]["layers"][0]["task"]["kind"] == "line"
        assert json.loads(store.one("SELECT data_json FROM pair WHERE id=?", (pending,))["data_json"])["check"] == check   # nothing derived is stored
        missing = client.put(f"/api/pairs/{pending}/tasks", json={"layer_index": 7, "task": "line"})
        assert missing.status_code == 422 and "not in the LightBurn file" in missing.json()["error"]
        bad = client.put(f"/api/pairs/{pending}/tasks", json={"layer_index": None, "task": "engraving"})
        assert bad.status_code == 422 and "unknown engraving task" in bad.json()["error"]
        add(store, w, (40, 2, 3), scan_recipe(w), tasks.explicit("text", "operator"))
        assert [m["task"]["kind"] for m in client.get("/api/colors/search", params={"L": 40, "a": 2, "b": 3, "task": "text"}).json()["matches"]] == ["text"]
        assert client.get("/api/colors", params={"task": "fill"}).json()["points"] == []
        assert {tuple(e["tasks"]) for e in client.get("/api/experiments", params={"task": "text"}).json()} == {("text",)}


def _js_keys(name: str) -> set[str]:
    source = (UI_DIR / "i18n-tasks.js").read_text(encoding="utf-8")
    body = re.search(rf"const {name} = \{{(.*?)\}};", source, re.S).group(1)
    return set(re.findall(r"(\w+):", body))


def test_every_task_metric_basis_and_missing_context_has_a_russian_label():
    assert set(tasks.TASKS) <= _js_keys("KIND")
    assert set(tasks.METRICS) | set(tasks.UNAVAILABLE) <= _js_keys("METRIC")
    assert set(tasks.BASES) <= _js_keys("BASIS")
    assert {"lens_unknown", "batch_unknown", "focus_unknown", "camera_relative", "unreferenced", "provisional", "settings_incomplete"} <= _js_keys("MISSING")
    assert {g for t in tasks.TASKS.values() for g in t["goals"]} | {"note"} <= _js_keys("GOAL")
    assert set(tasks.METHODS) <= _js_keys("METHOD")
    line = {"line_count": 2, "visible_line_count": 1, "median_continuity_percent": 50.0, "median_contrast_Lstar": 4.0, "median_apparent_trace_width_mm": 0.1}
    scale = {"px_per_mm": 10.0, "residual_px": None, "uncertainty_mm": 0.025, "sampling_mm": 0.025}
    produced = [m for kind in tasks.TASKS for m in tasks.quality_metrics(kind, lab=[50, 1, 1], clean_lab=[60, 0, 0], mode="raw_camera_relative",
                                                                        tonal={"bins": [{}], "rho": 0.9, "range_L": 30}, scale=scale)]
    produced += tasks.quality_metrics("line", lab=[50, 1, 1], line_metrics=line, scale=scale)
    assert {m["method"] for m in produced if m["available"]} == set(tasks.METHODS)
    assert {m["basis"] for m in produced if m["available"]} <= set(tasks.BASES)


def test_the_screens_choose_show_and_filter_by_task():
    scripts = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
    order = {s: i for i, s in enumerate(scripts)}
    assert order["/i18n-tasks.js"] < order["/i18n-data.js"] < order["/app.js"] < order["/tasks.js"] < order["/screens/experiment-cards.js"]
    assert order["/screens/ingest-tasks.js"] < order["/screens/ingest-review.js"]
    screen = lambda name: (UI_DIR / "screens" / name).read_text(encoding="utf-8")
    for name in ("artwork-start.js", "photo-form.js", "vector.js", "plate-dialog.js"):
        assert "Tasks.chooser(" in screen(name), name                       # a plan or plate is made with its task
    assert "Tasks.select(" in screen("ingest-upload.js") and "fd.append('task'" in screen("ingest-upload.js")
    assert "IngestTasks.card(pair, reload)" in screen("ingest-review.js") and "/tasks`" in screen("ingest-tasks.js")
    assert "Tasks.badge(l.task)" in screen("experiment.js") and "Tasks.metrics(l.metrics" in screen("experiment.js")
    assert "Tasks.metrics(row.metrics)" in screen("analysis.js")
    assert "q.set('task'" in screen("color-map.js") and "Прогноз модели, не измерение" in screen("color-map.js")
    assert "experiment-task" in screen("experiments.js") and "task: taskPicker.value" in screen("device-view.js")
