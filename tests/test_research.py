import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from titanium_platform import application_guide, devices, lenses, lightburn, plans, profiles, research
from titanium_platform.api.app import create_app
from titanium_platform.db import now


def hardware(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT research", serial="R-1")
    lens = lenses.create_lens(store, "F-Theta research", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    material = profiles.save_material(store, "Grade 2 stock", grade="Grade 2", batch="R-A")
    return laser, lens, material


def test_session_plate_export_and_pending_guard(store):
    laser, lens, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "тонкая непрерывная линия")
    assert session["lens_id"] == lens["id"]
    assert research.context(store, session["id"])["device"]["id"] == laser["id"]
    preview = research.preview_plate(store, session["id"], "material_matrix", {
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
    with pytest.raises(research.ResearchError, match="ожидает"):
        research.create_plate(store, session["id"], "text_readability")


def test_ai_can_replace_a_pending_plate_without_losing_history(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "text", "найти читаемые буквы")
    old = research.create_plate(store, session["id"], "text_readability")
    store.execute("UPDATE plan SET status='Exported' WHERE id=?", (old["plan_id"],))
    settings = {"power": 60, "frequency": 200, "speed": 3750, "pulse_width": 200,
                "line_interval": 0.025, "passes": 1,
                "matrix": {"x_axis": "frequency", "y_axis": "pulse_width", "geometry": "fill",
                           "x_min": 105, "x_max": 420, "x_count": 3,
                           "y_min": 100, "y_max": 350, "y_count": 3}}
    preview = research.preview_plate(store, session["id"], "material_matrix", settings)
    assert preview["summary"]["size_mm"]["width"] < 100
    replaced = research.call_tool(store, session["id"], "replace_pending_test",
                                  {"plan_id": old["plan_id"], "test_type": "material_matrix", "settings": settings})
    assert replaced["replaced_plan_id"] == old["plan_id"]
    assert replaced["plan_id"] != old["plan_id"]
    assert store.one("SELECT status FROM plan WHERE id=?", (old["plan_id"],))["status"] == "Superseded"
    assert plans.get_plan(store, replaced["plan_id"])["research_session_id"] == session["id"]
    assert [p["status"] for p in research.get_session(store, session["id"])["plans"]] == ["Ready to export", "Superseded"]
    assert research.context(store, session["id"])["session_plans"][0]["replaceable"] is True
    with pytest.raises(research.ResearchError, match="текущую ожидающую плату"):
        research.create_plate(store, session["id"], "line_resolution", replace_plan_id=old["plan_id"])


def test_replacement_refuses_linked_photos_and_invalid_new_plate_without_discarding_old(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "найти непрерывную линию")
    old = research.create_plate(store, session["id"], "line_resolution")
    with pytest.raises(ValueError):
        research.create_plate(store, session["id"], "unknown_test", replace_plan_id=old["plan_id"])
    assert plans.get_plan(store, old["plan_id"])["status"] == "Ready to export"
    profile = store.one("SELECT id FROM laser_profile WHERE device_id=?", (laser["id"],))
    store.execute(
        "INSERT INTO pair(status,profile_id,material_id,plan_id,engraving_id,lightburn_name,lightburn_path,"
        "photo_name,photo_path,context_json,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Awaiting check", profile["id"], material["id"], old["plan_id"], "job-1",
         "file.lbrn2", "/missing.lbrn2", "photo.dng", "/missing.dng", "{}", "{}", now()))
    with pytest.raises(research.ResearchError, match="привязано фото"):
        research.create_plate(store, session["id"], "material_matrix", replace_plan_id=old["plan_id"])
    with pytest.raises(research.ResearchError, match="привязано фото"):
        research.cancel_pending_plate(store, session["id"], old["plan_id"], "тест больше не нужен")
    assert plans.get_plan(store, old["plan_id"])["status"] == "Ready to export"


def test_ai_can_cancel_only_the_current_pending_plate(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "найти непрерывную линию")
    old = research.create_plate(store, session["id"], "line_resolution")
    cancelled = research.call_tool(store, session["id"], "cancel_pending_test",
                                   {"plan_id": old["plan_id"], "reason": "оператор попросил другой эксперимент"})
    assert cancelled["status"] == "Cancelled"
    with pytest.raises(research.ResearchError, match="не является текущей"):
        research.cancel_pending_plate(store, session["id"], old["plan_id"], "повторная отмена")
    assert research.create_plate(store, session["id"], "material_matrix")["plan_id"] != old["plan_id"]


def test_evidence_and_insight_are_scoped_to_exact_hardware_and_accepted_photo(store):
    laser, lens, material = hardware(store)
    other = profiles.save_material(store, "Other stock", grade="Grade 5")
    session = research.create_session(store, laser["id"], material["id"], "text", "читаемый текст 1 мм")
    research.preview_plate(store, session["id"], "text_readability")
    profile = store.one("SELECT id FROM laser_profile WHERE device_id=? AND lens_id=?", (laser["id"], lens["id"]))
    accepted = []
    for stock in (material, other):
        accepted.append(store.execute(
            "INSERT INTO pair(status,profile_id,material_id,engraving_id,lightburn_name,lightburn_path,"
            "photo_name,photo_path,context_json,data_json,created_at,accepted_at) "
            "VALUES ('Accepted',?,?,?,?,?,?,?,?,?,?,?)",
            (profile["id"], stock["id"], f"job-{stock['id']}", "file.lbrn2", "/missing.lbrn2",
             "photo.dng", "/missing.dng", "{}", "{}", now(), now())).lastrowid)
    rows = research.evidence(store, session["id"])
    assert [r["id"] for r in rows] == [accepted[0]]
    saved = research.save_insight(store, session["id"], "text", "Контраст букв предварительно заметен на снимке.",
                                  "candidate", [accepted[0]])
    assert saved["evidence_pair_ids"] == [accepted[0]]
    with pytest.raises(research.ResearchError, match="не относится"):
        research.save_insight(store, session["id"], "text", "Другая заготовка дала чёткий текст.",
                              "candidate", [accepted[1]])
    with pytest.raises(research.ResearchError, match="подтверждение"):
        research.save_insight(store, session["id"], "text", "Готовый режим для работы.", "confirmed", [accepted[0]])


def test_ai_uses_bounded_local_tools_and_persists_evidence_trace(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "найти непрерывную линию")

    class FakeResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            assert kwargs["model"] == "gpt-6.1-sol"
            assert kwargs["store"] is False
            if self.calls == 1:
                return SimpleNamespace(output=[SimpleNamespace(type="function_call", name="create_test",
                    arguments=json.dumps({"test_type": "line_resolution", "settings": {}}), call_id="call-1")], output_text="")
            assert any(item.get("type") == "function_call_output" for item in kwargs["input"] if isinstance(item, dict))
            return SimpleNamespace(output=[], output_text="Плата создана. После гравировки добавьте RAW-фото.")

    result = research.answer(store, session["id"], "Создай тест разрешения линий", client=SimpleNamespace(responses=FakeResponses()))
    assert result["tool_trace"][0]["result"]["plan_id"]
    assert result["session"]["messages"][-1]["role"] == "assistant"
    assert result["session"]["plans"][0]["id"] == result["tool_trace"][0]["result"]["plan_id"]


def test_ai_keeps_created_plate_when_followup_response_fails(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "найти непрерывную линию")

    class FailingResponses:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(output=[SimpleNamespace(type="function_call", name="create_test",
                    arguments=json.dumps({"test_type": "line_resolution", "settings": {}}), call_id="call-1")], output_text="")
            raise RuntimeError("provider became unavailable")

    result = research.answer(store, session["id"], "Создай тест разрешения линий",
                             client=SimpleNamespace(responses=FailingResponses()))
    assert "Плата №" in result["text"]
    assert len(result["session"]["plans"]) == 1
    assert result["session"]["messages"][-1]["tool_trace"][0]["tool"] == "create_test"


def test_ai_reports_invalid_tool_arguments_without_losing_the_chat(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "найти непрерывную линию")

    class BadArguments:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(output=[SimpleNamespace(type="function_call", name="preview_test",
                    arguments="{bad json", call_id="call-1")], output_text="")
            assert kwargs["input"][-1]["type"] == "function_call_output"
            return SimpleNamespace(output=[], output_text="Не удалось разобрать параметры; уточните тест.")

    result = research.answer(store, session["id"], "Предложи тест", client=SimpleNamespace(responses=BadArguments()))
    assert result["tool_trace"][0]["error"]
    assert len(result["session"]["messages"]) == 2


def test_session_lists_photos_uploaded_for_its_plate(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "line", "найти непрерывную линию")
    plan = research.create_plate(store, session["id"], "line_resolution")
    profile = store.one("SELECT id FROM laser_profile WHERE device_id=?", (laser["id"],))
    photo_id = store.execute(
        "INSERT INTO pair(status,profile_id,material_id,plan_id,engraving_id,lightburn_name,lightburn_path,"
        "photo_name,photo_path,context_json,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Awaiting check", profile["id"], material["id"], plan["plan_id"], "job-1",
         "file.lbrn2", "/missing.lbrn2", "photo.dng", "/missing.dng", "{}", "{}", now())).lastrowid
    listed = research.get_session(store, session["id"])["photos"]
    assert [item["id"] for item in listed] == [photo_id]
    assert listed[0]["plan_id"] == plan["plan_id"]


def test_depth_goal_does_not_export_a_surface_photo_test_as_depth_evidence(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "deep", "Найти глубину 0,2 мм")
    assert research.next_test(store, session["id"])["status"] == "measurement_needed"
    with pytest.raises(research.ResearchError, match="физического измерения"):
        research.create_plate(store, session["id"], "material_matrix")


def test_research_routes_create_and_expose_session(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        laser, _, material = hardware(app.state.store)
        response = client.post("/api/research/sessions", json={"device_id": laser["id"],
            "material_id": material["id"], "goal": "line", "target": "тонкая непрерывная линия"})
        assert response.status_code == 201, response.text
        sid = response.json()["id"]
        assert client.get(f"/api/research/sessions/{sid}/context").json()["session"]["goal"] == "line"
        bad = client.post(f"/api/research/sessions/{sid}/preview-test", json={"test_type": "unknown"})
        assert bad.status_code == 422
        made = client.post(f"/api/research/sessions/{sid}/tests", json={"test_type": "text_readability"})
        assert made.status_code == 201, made.text
        assert client.get(made.json()["download_url"]).status_code == 200
        replaced = client.post(f"/api/research/sessions/{sid}/replace-test", json={
            "plan_id": made.json()["plan_id"], "test_type": "material_matrix", "settings": {}})
        assert replaced.status_code == 201, replaced.text
        assert client.get(made.json()["download_url"]).status_code == 409
        assert client.get(f"/api/plans/{made.json()['plan_id']}").json()["status"] == "Superseded"
        assert client.get(replaced.json()["download_url"]).status_code == 200
        cancelled = client.post(f"/api/research/sessions/{sid}/cancel-test", json={
            "plan_id": replaced.json()["plan_id"], "reason": "следующий тест выбран отдельно"})
        assert cancelled.status_code == 200, cancelled.text
        assert client.get(replaced.json()["download_url"]).status_code == 409
    app.state.store.close()


def test_research_delete_hides_thread_but_preserves_chat_and_experiment(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        laser, _, material = hardware(app.state.store)
        session = research.create_session(app.state.store, laser["id"], material["id"], "line", "видимая линия")
        sid = session["id"]
        plate = research.create_plate(app.state.store, sid, "line_resolution")
        research._save_exchange(app.state.store, sid, "Что проверяем?", "Непрерывность линии.", [])
        assert [m["content"] for m in client.get(f"/api/research/sessions/{sid}").json()["messages"]] == [
            "Что проверяем?", "Непрерывность линии."]
        assert client.delete(f"/api/research/sessions/{sid}").status_code == 204
        assert client.get("/api/research/sessions").json() == []
        assert client.get(f"/api/research/sessions/{sid}").status_code == 404
        assert app.state.store.one("SELECT COUNT(*) AS n FROM research_message WHERE session_id=?", (sid,))["n"] == 2
        assert app.state.store.one("SELECT status FROM plan WHERE id=?", (plate["plan_id"],))["status"] != "Deleted"
        assert application_guide.suggest(app.state.store, laser["id"], material["id"], "line")["status"] != "awaiting_photo"
    app.state.store.close()


def test_long_research_chat_pages_history_and_builds_durable_memory(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "text", "чёткая надпись")
    sid = session["id"]

    class Responses:
        def create(self, **kwargs):
            if "Обнови рабочую память" in kwargs["instructions"]:
                assert "первый вопрос" in kwargs["input"][0]["content"]
                return SimpleNamespace(output=[], output_text="Цель: чёткая надпись. Следующий шаг: сравнить линии.")
            if "третий вопрос" in str(kwargs["input"]):
                assert "Цель: чёткая надпись" in kwargs["instructions"]
            return SimpleNamespace(output=[], output_text="Нужен сравнимый тест.")

    client = SimpleNamespace(responses=Responses())
    for question in ("первый вопрос", "второй вопрос", "третий вопрос"):
        research.answer(store, sid, question, client=client)
    memory = store.one("SELECT summary,through_message_id FROM research_memory WHERE session_id=?", (sid,))
    assert "Следующий шаг" in memory["summary"]
    assert memory["through_message_id"] == 4
    assert len(research.get_session(store, sid)["messages"]) == 6
    for index in range(50):
        research._save_exchange(store, sid, f"вопрос {index}", f"ответ {index}", [])
    recent = research.get_session(store, sid)
    assert len(recent["messages"]) == research.PAGE_MESSAGES
    assert recent["has_older_messages"] is True
    older = research.list_messages(store, sid, before=recent["messages"][0]["id"])
    assert len(older["messages"]) == research.PAGE_MESSAGES
    assert older["messages"][-1]["id"] < recent["messages"][0]["id"]
    assert recent["memory"]["summary"] == memory["summary"]


def test_context_distinguishes_accepted_photo_from_pending_plate(store):
    laser, _, material = hardware(store)
    session = research.create_session(store, laser["id"], material["id"], "text", "чёткая надпись")
    plan = research.create_plate(store, session["id"], "text_readability")
    profile = store.one("SELECT id FROM laser_profile WHERE device_id=?", (laser["id"],))
    photo_id = store.execute(
        "INSERT INTO pair(status,profile_id,material_id,plan_id,engraving_id,lightburn_name,lightburn_path,"
        "photo_name,photo_path,context_json,data_json,created_at,accepted_at) "
        "VALUES ('Accepted',?,?,?,?,?,?,?,?,?,?,?,?)",
        (profile["id"], material["id"], plan["plan_id"], "job-1", "test.lbrn2", "/missing.lbrn2",
         "photo.dng", "/missing.dng", "{}", "{}", now(), now())).lastrowid
    state = research.context(store, session["id"])
    assert state["current_state"]["pending_plan_id"] is None
    assert state["current_state"]["latest_photo"]["id"] == photo_id
    assert state["session_plans"][0]["lifecycle"] == "has_accepted_photo"
