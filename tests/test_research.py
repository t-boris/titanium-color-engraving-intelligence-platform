import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from titanium_platform import application_guide, devices, lenses, lightburn, plans, research
from titanium_platform import setup as su
from titanium_platform.api.app import create_app
from titanium_platform.db import now

JOB = {"pulse_width": 200}      # the pulse width of a test plate is always given (DEC-043)


def hardware(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT research", serial="R-1")
    lens = lenses.create_lens(store, "F-Theta research", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)   # the operator's C01 recipe (DEC-027)
    material = su.save_material(store, "Grade 2 stock", grade="Grade 2", batch="R-A")
    return laser, lens, material


def test_session_plate_export_and_pending_guard(store):
    laser, lens, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "thin continuous line")
    assert session["lens_id"] == lens["id"]
    assert research.context(store, session["id"])["device"]["id"] == laser["id"]
    preview = research.preview_plate(store, session["id"], "material_matrix", {**JOB, 
        "power": 20, "frequency": 48, "speed": 900, "pulse_width": 200,
        "matrix": {"x_axis": "power", "y_axis": "speed", "geometry": "line",
                   "x_min": 10, "x_max": 30, "x_count": 3,
                   "y_min": 500, "y_max": 1500, "y_count": 3}})
    assert preview["summary"]["size_mm"]["width"] < 100
    assert preview["output_layers"] == 11
    assert preview["cleanup_settings"]["line_interval"] == 0.05
    made = research.create_plate(store, session["id"], "material_matrix", preview["test_settings"])
    assert made["download_url"].endswith(f"/{made['plan_id']}/export.lbrn2")
    stored = plans.get_plan(store, made["plan_id"])
    assert stored["research_session_id"] == session["id"]
    project = lightburn.parse_bytes(plans.export_lbrn2(stored))
    assert project.layer(0).name.startswith("CLEAN-")
    assert max(layer.index for layer in project.layers) <= 29
    with pytest.raises(research.ResearchError, match="awaiting"):
        research.create_plate(store, session["id"], "text_readability", JOB)


def test_ai_can_replace_a_pending_plate_without_losing_history(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "text", "find legible letters")
    old = research.create_plate(store, session["id"], "text_readability", JOB)
    store.execute("UPDATE plan SET status='Exported' WHERE id=?", (old["plan_id"],))
    settings = {"power": 60, "frequency": 200, "speed": 3750, "pulse_width": 200,
                "line_interval": 0.025, "passes": 1,
                "matrix": {"x_axis": "frequency", "y_axis": "pulse_width", "geometry": "fill",
                           "x_min": 105, "x_max": 420, "x_count": 3,
                           "y_min": 100, "y_max": 350, "y_count": 3}}
    preview = research.preview_plate(store, session["id"], "material_matrix", {**JOB, **settings})
    assert preview["summary"]["size_mm"]["width"] < 100
    replaced = research.call_tool(store, session["id"], "replace_pending_test",
                                  {"plan_id": old["plan_id"], "test_type": "material_matrix", "settings": settings})
    assert replaced["replaced_plan_id"] == old["plan_id"]
    assert replaced["plan_id"] != old["plan_id"]
    assert store.one("SELECT status FROM plan WHERE id=?", (old["plan_id"],))["status"] == "Superseded"
    assert plans.get_plan(store, replaced["plan_id"])["research_session_id"] == session["id"]
    assert [p["status"] for p in research.get_session(store, session["id"])["plans"]] == ["Ready to export", "Superseded"]
    assert research.context(store, session["id"])["session_plans"][0]["replaceable"] is True
    with pytest.raises(research.ResearchError, match="current pending plate"):
        research.create_plate(store, session["id"], "line_resolution", JOB, replace_plan_id=old["plan_id"])


def test_replacement_refuses_linked_photos_and_invalid_new_plate_without_discarding_old(store):
    laser, lens, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")
    old = research.create_plate(store, session["id"], "line_resolution", JOB)
    with pytest.raises(ValueError):
        research.create_plate(store, session["id"], "unknown_test", JOB, replace_plan_id=old["plan_id"])
    assert plans.get_plan(store, old["plan_id"])["status"] == "Ready to export"
    store.execute(
        "INSERT INTO pair(status,device_id,lens_id,material_id,plan_id,engraving_id,lightburn_name,lightburn_path,"
        "photo_name,photo_path,context_json,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Awaiting check", laser["id"], lens["id"], material["id"], old["plan_id"], "job-1",
         "file.lbrn2", "/missing.lbrn2", "photo.dng", "/missing.dng", "{}", "{}", now()))
    with pytest.raises(research.ResearchError, match="photo"):
        research.create_plate(store, session["id"], "material_matrix", JOB, replace_plan_id=old["plan_id"])
    with pytest.raises(research.ResearchError, match="photo"):
        research.cancel_pending_plate(store, session["id"], old["plan_id"], "test is no longer needed")
    assert plans.get_plan(store, old["plan_id"])["status"] == "Ready to export"


def test_ai_can_cancel_only_the_current_pending_plate(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")
    old = research.create_plate(store, session["id"], "line_resolution", JOB)
    cancelled = research.call_tool(store, session["id"], "cancel_pending_test",
                                   {"plan_id": old["plan_id"], "reason": "operator requested another experiment"})
    assert cancelled["status"] == "Cancelled"
    with pytest.raises(research.ResearchError, match="not the current pending"):
        research.cancel_pending_plate(store, session["id"], old["plan_id"], "repeated cancellation")
    assert research.create_plate(store, session["id"], "material_matrix", JOB)["plan_id"] != old["plan_id"]


def test_evidence_and_insight_are_scoped_to_exact_hardware_and_accepted_photo(store):
    laser, lens, material = hardware(store)
    other = su.save_material(store, "Other stock", grade="Grade 5")
    session = research.create_session(store, laser["id"], material["id"], "text", "legible text 1 mm")
    research.preview_plate(store, session["id"], "text_readability", JOB)
    accepted = []
    for stock in (material, other):
        accepted.append(store.execute(
            "INSERT INTO pair(status,device_id,lens_id,material_id,engraving_id,lightburn_name,lightburn_path,"
            "photo_name,photo_path,context_json,data_json,created_at,accepted_at) "
            "VALUES ('Accepted',?,?,?,?,?,?,?,?,?,?,?,?)",
            (laser["id"], lens["id"], stock["id"], f"job-{stock['id']}", "file.lbrn2", "/missing.lbrn2",
             "photo.dng", "/missing.dng", "{}", "{}", now(), now())).lastrowid)
    rows = research.evidence(store, session["id"])
    assert [r["id"] for r in rows] == [accepted[0]]
    saved = research.save_insight(store, session["id"], "text", "Letter contrast is provisionally visible in the photograph.",
                                  "candidate", [accepted[0]])
    assert saved["evidence_pair_ids"] == [accepted[0]]
    with pytest.raises(research.ResearchError, match="does not match"):
        research.save_insight(store, session["id"], "text", "Another blank produced clear text.",
                              "candidate", [accepted[1]])
    with pytest.raises(research.ResearchError, match="operator confirms"):
        research.save_insight(store, session["id"], "text", "Production-ready settings.", "confirmed", [accepted[0]])


def test_ai_previews_a_test_and_creation_requires_a_separate_idempotent_action(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")

    class FakeResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            assert kwargs["model"] == "gpt-6.1-sol"
            assert kwargs["store"] is False
            if self.calls == 1:
                assert not any(spec["name"] in {"create_test", "replace_pending_test"} for spec in kwargs["tools"])
                return SimpleNamespace(output=[SimpleNamespace(type="function_call", name="preview_test",
                    arguments=json.dumps({"test_type": "line_resolution", "settings": JOB}), call_id="call-1")], output_text="")
            assert any(item.get("type") == "function_call_output" for item in kwargs["input"] if isinstance(item, dict))
            return SimpleNamespace(output=[], output_text="I suggest a line test; confirm creation separately.")

    result = research.answer(store, session["id"], "Create a line resolution test", client=SimpleNamespace(responses=FakeResponses()))
    proposal = result["tool_trace"][0]["result"]
    assert proposal["context_signature"] and proposal["summary"]["size_mm"] and proposal["time_estimate"] is None
    assert not result["session"]["plans"]
    message = result["session"]["messages"][-1]
    made = research.create_proposed_plate(store, session["id"], message["id"], 0)
    assert research.create_proposed_plate(store, session["id"], message["id"], 0) == made
    assert [p["id"] for p in research.get_session(store, session["id"])["plans"]] == [made["plan_id"]]


def test_ai_cannot_create_a_plate_by_calling_a_forbidden_tool(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")

    class FailingResponses:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(output=[SimpleNamespace(type="function_call", name="create_test",
                    arguments=json.dumps({"test_type": "line_resolution", "settings": JOB}), call_id="call-1")], output_text="")
            assert not kwargs["input"][-1]["output"].startswith('{"ok": true')
            return SimpleNamespace(output=[], output_text="Separate confirmation is required.")

    result = research.answer(store, session["id"], "Create a line resolution test",
                             client=SimpleNamespace(responses=FailingResponses()))
    assert not result["session"]["plans"]
    assert "separate operator action" in result["tool_trace"][0]["error"]


def test_proposal_cannot_be_created_after_its_context_changes(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")
    args = {"test_type": "line_resolution", "settings": JOB}
    preview = research.preview_plate(store, session["id"], **args)
    research._save_exchange(store, session["id"], "Suggest a test", "Proposal", [{"tool": "preview_test", "arguments": args, "result": preview}])
    message = research.get_session(store, session["id"])["messages"][-1]
    store.execute("UPDATE research_session SET target=? WHERE id=?", ("Another goal", session["id"]))
    with pytest.raises(research.ResearchError, match="the research context has changed"):
        research.create_proposed_plate(store, session["id"], message["id"], 0)
    assert not research.get_session(store, session["id"])["plans"]


def test_concurrent_retries_of_the_same_proposal_create_only_one_plate(store):
    from concurrent.futures import ThreadPoolExecutor

    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")
    args = {"test_type": "line_resolution", "settings": JOB}
    preview = research.preview_plate(store, session["id"], **args)
    research._save_exchange(store, session["id"], "Suggest a test", "Proposal", [{"tool": "preview_test", "arguments": args, "result": preview}])
    message = research.get_session(store, session["id"])["messages"][-1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        made = list(pool.map(lambda _: research.create_proposed_plate(store, session["id"], message["id"], 0), range(2)))
    assert made[0]["plan_id"] == made[1]["plan_id"]
    reloaded = research.get_session(store, session["id"])
    assert len(reloaded["plans"]) == 1 and reloaded["messages"][-1]["tool_trace"][0]["created_plan"]["plan_id"] == made[0]["plan_id"]


def test_changed_marker_settings_require_a_fresh_preview(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")
    args = {"test_type": "line_resolution", "settings": JOB}
    preview = research.preview_plate(store, session["id"], **args)
    research._save_exchange(store, session["id"], "Suggest a test", "Proposal", [{"tool": "preview_test", "arguments": args, "result": preview}])
    message_id = research.get_session(store, session["id"])["messages"][-1]["id"]
    plans.save_marker_layer_settings(store, 35, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    with pytest.raises(research.ResearchError, match="settings or size"):
        research.create_proposed_plate(store, session["id"], message_id, 0)
    assert not research.get_session(store, session["id"])["plans"]


def test_pending_plate_is_replaced_only_by_the_separate_confirmed_action(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")
    old = research.create_plate(store, session["id"], "line_resolution", JOB)
    args = {"test_type": "line_resolution", "settings": JOB}
    preview = research.preview_plate(store, session["id"], **args)
    assert preview["pending_plan_id"] == old["plan_id"] and preview["pending_replaceable"]
    research._save_exchange(store, session["id"], "Suggest a replacement", "Proposal", [{"tool": "preview_test", "arguments": args, "result": preview}])
    message_id = research.get_session(store, session["id"])["messages"][-1]["id"]
    with pytest.raises(research.ResearchError, match="separate review"):
        research.create_proposed_plate(store, session["id"], message_id, 0)
    made = research.create_proposed_plate(store, session["id"], message_id, 0, replace_plan_id=old["plan_id"])
    assert made["replaced_plan_id"] == old["plan_id"]
    assert store.one("SELECT status FROM plan WHERE id=?", (old["plan_id"],))["status"] == "Superseded"
    assert research.create_proposed_plate(store, session["id"], message_id, 0, replace_plan_id=old["plan_id"]) == made


def test_advisory_actions_cannot_write_even_if_the_model_requests_it(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")

    class Responses:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            assert not {"create_test", "replace_pending_test", "cancel_pending_test", "run_photo_mapping", "save_research_insight"} & {t["name"] for t in kwargs["tools"]}
            if self.calls == 1:
                return SimpleNamespace(output=[SimpleNamespace(type="function_call", name="save_research_insight",
                    arguments=json.dumps({"purpose": "line", "claim": "A sufficiently detailed finding", "confidence": "hypothesis", "evidence_pair_ids": [1]}), call_id="x")], output_text="")
            return SimpleNamespace(output=[], output_text="This is only an explanation.")

    result = research.answer(store, session["id"], "Explain the result", client=SimpleNamespace(responses=Responses()), advisory=True)
    assert result["tool_trace"][0].get("error") and not result["session"]["insights"] and not result["session"]["plans"]


def test_confirm_proposal_route_survives_retry_and_preserves_the_link(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        store = app.state.store
        laser, _, material = hardware(store)
        session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")
        args = {"test_type": "line_resolution", "settings": JOB}
        preview = research.preview_plate(store, session["id"], **args)
        research._save_exchange(store, session["id"], "Suggest a test", "Proposal", [{"tool": "preview_test", "arguments": args, "result": preview}])
        message_id = research.get_session(store, session["id"])["messages"][-1]["id"]
        path = f"/api/research/sessions/{session['id']}/proposals/{message_id}/0/create"
        first = client.post(path, json={})
        retry = client.post(path, json={})
        assert first.status_code == retry.status_code == 201 and first.json()["plan_id"] == retry.json()["plan_id"]
        loaded = client.get(f"/api/research/sessions/{session['id']}").json()
        assert loaded["messages"][-1]["tool_trace"][0]["created_plan"]["plan_url"] == first.json()["plan_url"]


def test_ai_reports_invalid_tool_arguments_without_losing_the_chat(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")

    class BadArguments:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(output=[SimpleNamespace(type="function_call", name="preview_test",
                    arguments="{bad json", call_id="call-1")], output_text="")
            assert kwargs["input"][-1]["type"] == "function_call_output"
            return SimpleNamespace(output=[], output_text="Could not parse the parameters; clarify the test.")

    result = research.answer(store, session["id"], "Suggest a test", client=SimpleNamespace(responses=BadArguments()))
    assert result["tool_trace"][0]["error"]
    assert len(result["session"]["messages"]) == 2


def test_session_lists_photos_uploaded_for_its_plate(store):
    laser, lens, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "find a continuous line")
    plan = research.create_plate(store, session["id"], "line_resolution", JOB)
    photo_id = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,material_id,plan_id,engraving_id,lightburn_name,lightburn_path,"
        "photo_name,photo_path,context_json,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Awaiting check", laser["id"], lens["id"], material["id"], plan["plan_id"], "job-1",
         "file.lbrn2", "/missing.lbrn2", "photo.dng", "/missing.dng", "{}", "{}", now())).lastrowid
    listed = research.get_session(store, session["id"])["photos"]
    assert [item["id"] for item in listed] == [photo_id]
    assert listed[0]["plan_id"] == plan["plan_id"]


def test_depth_goal_does_not_export_a_surface_photo_test_as_depth_evidence(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "deep", "Find a depth of 0.2 mm")
    assert research.next_test(store, session["id"])["status"] == "measurement_needed"
    with pytest.raises(research.ResearchError, match="physical measurement"):
        research.create_plate(store, session["id"], "material_matrix", JOB)


def test_research_routes_create_and_expose_session(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        laser, _, material = hardware(app.state.store)
        response = client.post("/api/research/sessions", json={"device_id": laser["id"],
            "material_id": material["id"], "goal": "line", "target": "thin continuous line"})
        assert response.status_code == 201, response.text
        sid = response.json()["id"]
        assert client.get(f"/api/research/sessions/{sid}/context").json()["session"]["goal"] == "line"
        bad = client.post(f"/api/research/sessions/{sid}/preview-test", json={"test_type": "unknown"})
        assert bad.status_code == 422
        made = client.post(f"/api/research/sessions/{sid}/tests", json={"test_type": "text_readability", "settings": JOB})
        assert made.status_code == 201, made.text
        assert client.get(made.json()["download_url"]).status_code == 200
        replaced = client.post(f"/api/research/sessions/{sid}/replace-test", json={
            "plan_id": made.json()["plan_id"], "test_type": "material_matrix", "settings": JOB})
        assert replaced.status_code == 201, replaced.text
        assert client.get(made.json()["download_url"]).status_code == 409
        assert client.get(f"/api/plans/{made.json()['plan_id']}").json()["status"] == "Superseded"
        assert client.get(replaced.json()["download_url"]).status_code == 200
        cancelled = client.post(f"/api/research/sessions/{sid}/cancel-test", json={
            "plan_id": replaced.json()["plan_id"], "reason": "the next test was selected separately"})
        assert cancelled.status_code == 200, cancelled.text
        assert client.get(replaced.json()["download_url"]).status_code == 409
    app.state.store.close()


def test_research_delete_hides_thread_but_preserves_chat_and_experiment(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        laser, _, material = hardware(app.state.store)
        session = research.create_session(app.state.store, laser["id"], material["id"], "line", "visible line")
        sid = session["id"]
        plate = research.create_plate(app.state.store, sid, "line_resolution", JOB)
        research._save_exchange(app.state.store, sid, "What are we testing?", "Line continuity.", [])
        assert [m["content"] for m in client.get(f"/api/research/sessions/{sid}").json()["messages"]] == [
            "What are we testing?", "Line continuity."]
        experiment_url = f"/api/experiments/plan-{plate['plan_id']}"
        assert client.get(experiment_url).json()["plate"]["research_session_id"] == sid
        assert client.delete(f"/api/research/sessions/{sid}").status_code == 204
        assert client.get(experiment_url).json()["plate"]["research_session_id"] is None
        assert client.get("/api/research/sessions").json() == []
        assert client.get(f"/api/research/sessions/{sid}").status_code == 404
        assert app.state.store.one("SELECT COUNT(*) AS n FROM research_message WHERE session_id=?", (sid,))["n"] == 2
        assert app.state.store.one("SELECT status FROM plan WHERE id=?", (plate["plan_id"],))["status"] != "Deleted"
        assert application_guide.suggest(app.state.store, laser["id"], material["id"], "line")["status"] != "awaiting_photo"
    app.state.store.close()


def test_long_research_chat_pages_history_and_builds_durable_memory(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "text", "clear lettering")
    sid = session["id"]

    class Responses:
        def create(self, **kwargs):
            if "Update the working memory" in kwargs["instructions"]:
                assert "first question" in kwargs["input"][0]["content"]
                return SimpleNamespace(output=[], output_text="Goal: clear lettering. Next step: compare lines.")
            if "third question" in str(kwargs["input"]):
                assert "Goal: clear lettering" in kwargs["instructions"]
            return SimpleNamespace(output=[], output_text="A comparable test is needed.")

    client = SimpleNamespace(responses=Responses())
    for question in ("first question", "second question", "third question"):
        research.answer(store, sid, question, client=client)
    memory = store.one("SELECT summary,through_message_id FROM research_memory WHERE session_id=?", (sid,))
    assert "Next step" in memory["summary"]
    assert memory["through_message_id"] == 4
    assert len(research.get_session(store, sid)["messages"]) == 6
    for index in range(50):
        research._save_exchange(store, sid, f"question {index}", f"answer {index}", [])
    recent = research.get_session(store, sid)
    assert len(recent["messages"]) == research.PAGE_MESSAGES
    assert recent["has_older_messages"] is True
    older = research.list_messages(store, sid, before=recent["messages"][0]["id"])
    assert len(older["messages"]) == research.PAGE_MESSAGES
    assert older["messages"][-1]["id"] < recent["messages"][0]["id"]
    assert recent["memory"]["summary"] == memory["summary"]


def test_context_distinguishes_accepted_photo_from_pending_plate(store):
    laser, lens, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "text", "clear lettering")
    plan = research.create_plate(store, session["id"], "text_readability", JOB)
    photo_id = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,material_id,plan_id,engraving_id,lightburn_name,lightburn_path,"
        "photo_name,photo_path,context_json,data_json,created_at,accepted_at) "
        "VALUES ('Accepted',?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (laser["id"], lens["id"], material["id"], plan["plan_id"], "job-1", "test.lbrn2", "/missing.lbrn2",
         "photo.dng", "/missing.dng", "{}", "{}", now(), now())).lastrowid
    state = research.context(store, session["id"])
    assert state["current_state"]["pending_plan_id"] is None
    assert state["current_state"]["latest_photo"]["id"] == photo_id
    assert state["session_plans"][0]["lifecycle"] == "has_accepted_photo"


def test_the_research_tools_require_the_pulse_width_of_a_plate():
    for name in ("preview_test", "create_test", "replace_pending_test"):
        spec = next(s for s in research.TOOL_SPECS if s["name"] == name)
        assert spec["parameters"]["properties"]["settings"]["required"] == ["pulse_width"]


def test_a_key_without_the_client_library_is_a_message_in_the_chat_and_in_the_explanation_not_a_server_error(tmp_path, monkeypatch):
    """The app environment once lacked ``openai`` (a wheel installed without its dependencies): with a key set, the chat and the designer's
    explanation answered a bare 500. They now say what is missing and what to do, as the AI colouring does; nothing is stored."""
    import sys
    monkeypatch.setattr(research, "_api_key", lambda: "test-key")
    monkeypatch.setitem(sys.modules, "openai", None)                  # `from openai import OpenAI` raises ImportError, as without the library
    app = create_app(tmp_path / "data")
    with TestClient(app, raise_server_exceptions=False) as client:
        laser, _, material = hardware(app.state.store)
        sid = research.create_session(app.state.store, laser["id"], material["id"], "line", "visible line")["id"]
        asked = client.post(f"/api/research/sessions/{sid}/messages", json={"message": "What should be tested next?"})
        assert asked.status_code == 422 and asked.json()["error"].startswith("the AI could not be started on this computer")
        assert "openai" not in asked.json()["error"]
        assert client.get(f"/api/research/sessions/{sid}").json()["messages"] == []
    app.state.store.close()
    with pytest.raises(research.ResearchError, match="install the app's dependencies"):
        research.proposal_explainer()
