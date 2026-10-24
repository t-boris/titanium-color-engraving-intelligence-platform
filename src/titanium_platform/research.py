"""Goal-driven laser research, with one local tool set for the UI, AI and MCP.

The model may propose an experiment, but the existing plate builder validates the laser
passport, titanium cleaning pass, LightBurn layer count and physical dimensions.
Photographic measurements remain in the ingestion pipeline and are never invented here.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from . import analysis, application_guide, capability_plates, capability_results, devices, ingest, model, plans
from .db import Store, now

DEFAULT_MODEL = "gpt-6.1-sol"
MAX_HISTORY = 40
MAX_HISTORY_CHARS = 30000
MAX_TOOL_CALLS = 8
PAGE_MESSAGES = 40
MEMORY_INTERVAL = 4


class ResearchError(ValueError):
    """A research request cannot be fulfilled or safely interpreted."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _session_row(store: Store, session_id: int):
    row = store.one("SELECT * FROM research_session WHERE id=? AND status!='Deleted'", (session_id,))
    if row is None:
        raise KeyError(f"research session {session_id} not found")
    return row


def list_messages(store: Store, session_id: int, *, before: int | None = None,
                  limit: int = PAGE_MESSAGES) -> dict:
    _session_row(store, session_id)
    count = max(1, min(int(limit), 100))
    clause = " AND id<?" if before is not None else ""
    params = (session_id, before, count + 1) if before is not None else (session_id, count + 1)
    rows = store.query(
        "SELECT * FROM research_message WHERE session_id=?" + clause + " ORDER BY id DESC LIMIT ?", params)
    return {"messages": [dict(row, tool_trace=json.loads(row["tool_trace_json"])) for row in reversed(rows[:count])],
            "has_older_messages": len(rows) > count}


def get_session(store: Store, session_id: int) -> dict:
    row = _session_row(store, session_id)
    out = dict(row)
    page = list_messages(store, session_id)
    out.update(page)
    out["message_count"] = store.one("SELECT COUNT(*) AS n FROM research_message WHERE session_id=?", (session_id,))["n"]
    memory = store.one("SELECT through_message_id,summary,updated_at FROM research_memory WHERE session_id=?",
                       (session_id,))
    out["memory"] = dict(memory) if memory else None
    out["plans"] = [dict(p) for p in store.query(
        "SELECT id,name,status,created_at FROM plan WHERE research_session_id=? AND status!='Deleted' ORDER BY id DESC",
        (session_id,))]
    out["photos"] = [dict(p) for p in store.query(
        "SELECT q.id,q.plan_id,q.photo_name,q.status,q.created_at,q.accepted_at "
        "FROM pair q JOIN plan p ON p.id=q.plan_id "
        "WHERE p.research_session_id=? AND q.status!='Deleted' AND q.material_id=? "
        "AND q.device_id=? AND q.lens_id=? ORDER BY q.id DESC",
        (session_id, row["material_id"], row["device_id"], row["lens_id"]))]
    out["insights"] = [dict(item, evidence_pair_ids=json.loads(item["evidence_pair_ids_json"])) for item in store.query(
        "SELECT * FROM research_insight WHERE session_id=? ORDER BY id DESC", (session_id,))]
    return out


def list_sessions(store: Store) -> list[dict]:
    rows = store.query(
        "SELECT s.*,d.name AS device_name,l.name AS lens_name,m.name AS material_name,m.grade AS material_grade "
        "FROM research_session s JOIN laser_device d ON d.id=s.device_id JOIN lens l ON l.id=s.lens_id "
        "JOIN material_profile m ON m.id=s.material_id "
        "WHERE s.status!='Deleted' ORDER BY s.updated_at DESC,s.id DESC")
    return [dict(row) for row in rows]


def delete_session(store: Store, session_id: int) -> None:
    """Hide a research thread without destroying its chat or linked experimental evidence."""
    _session_row(store, session_id)
    with store.transaction():
        store.execute("UPDATE research_session SET status='Deleted',updated_at=? WHERE id=?", (now(), session_id))
        store.audit("research_session_deleted", session_id=session_id)


def create_session(store: Store, device_id: int, material_id: int, goal: str, target: str,
                   model: str = DEFAULT_MODEL) -> dict:
    if goal not in application_guide.GOALS:
        raise ResearchError("выберите известную задачу гравировки")
    target = str(target or "").strip()
    if not 4 <= len(target) <= 600:
        raise ResearchError("опишите измеримую цель исследования (4–600 символов)")
    if model != DEFAULT_MODEL:
        raise ResearchError(f"сейчас поддерживается модель {DEFAULT_MODEL}")
    device = devices.get_device(store, device_id)
    lens = device.get("lens")
    if lens is None:
        raise ResearchError("сначала установите линзу на выбранный лазер")
    if store.one("SELECT id FROM material_profile WHERE id=?", (material_id,)) is None:
        raise ResearchError("выберите материал и заготовку")
    stamp = now()
    session_id = store.execute(
        "INSERT INTO research_session(device_id,lens_id,material_id,goal,target,model,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (device_id, lens["id"], material_id, goal, target, model, "active", stamp, stamp)).lastrowid
    store.audit("research_session_created", session_id=session_id, device_id=device_id,
                lens_id=lens["id"], material_id=material_id, goal=goal)
    return get_session(store, session_id)


def _scope(store: Store, session_id: int) -> tuple[dict, dict, dict]:
    session = dict(_session_row(store, session_id))
    device = devices.get_device(store, session["device_id"])
    material_row = store.one("SELECT * FROM material_profile WHERE id=?", (session["material_id"],))
    if material_row is None:
        raise ResearchError("материал этой сессии удалён")
    lens_row = store.one("SELECT * FROM lens WHERE id=?", (session["lens_id"],))
    if lens_row is None:
        raise ResearchError("линза этой сессии удалена")
    return session, device, dict(material_row)


def _pair_in_scope(store: Store, session_id: int, pair_id: int) -> dict:
    session, _, _ = _scope(store, session_id)
    row = store.one(
        "SELECT p.id FROM pair p "
        "WHERE p.id=? AND p.status!='Deleted' AND p.device_id=? AND p.lens_id=? AND p.material_id=?",
        (pair_id, session["device_id"], session["lens_id"], session["material_id"]))
    if row is None:
        raise ResearchError("эта проверка не относится к лазеру, линзе и материалу исследования")
    return ingest.get_pair(store, pair_id)


def evidence(store: Store, session_id: int, limit: int = 12) -> list[dict]:
    session, _, _ = _scope(store, session_id)
    rows = store.query(
        "SELECT p.id,p.engraving_title,p.photo_name,p.accepted_at,p.plan_id,t.test_type "
        "FROM pair p "
        "LEFT JOIN plate t ON t.id=p.plate_id WHERE p.status='Accepted' AND p.device_id=? "
        "AND p.lens_id=? AND p.material_id=? ORDER BY p.accepted_at DESC,p.id DESC LIMIT ?",
        (session["device_id"], session["lens_id"], session["material_id"], max(1, min(limit, 30))))
    out = []
    for row in rows:
        counts = store.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (row["id"],))
        out.append(dict(row, measured_layers=counts["n"], analysis_url=f"#/analysis/{row['id']}"))
    return out


def context(store: Store, session_id: int) -> dict:
    session, device, material = _scope(store, session_id)
    lens = store.one("SELECT * FROM lens WHERE id=?", (session["lens_id"],))
    relative_color_photos = []
    for photo_set in reversed(model.camera_relative_sets(store, session["device_id"], session["lens_id"])):
        if photo_set.get("provisional") or photo_set["material"].get("id") != session["material_id"]:
            continue
        variants = photo_set.get("color_variants") or []
        if variants:
            relative_color_photos.append({
                "pair_id": photo_set["pair_id"], "photo_name": photo_set["photo_name"],
                "candidates": [{k: variant[k] for k in ("name", "lab", "parameters", "settings_complete")}
                               for variant in variants[:16]],
            })
        if len(relative_color_photos) >= 2:
            break
    findings = capability_results.findings_for_device(store, session["device_id"])
    findings = [f for f in findings if f["lens_id"] == session["lens_id"] and f["material_id"] == session["material_id"]]
    session_plans = store.query(
        "SELECT p.id,p.name,p.status,t.test_type,"
        "(SELECT COUNT(*) FROM pair q WHERE q.plan_id=p.id AND q.status!='Deleted') AS photo_count,"
        "(SELECT COUNT(*) FROM pair q WHERE q.plan_id=p.id AND q.status='Accepted') AS accepted_photo_count "
        "FROM plan p LEFT JOIN plate t ON t.id=p.plate_id "
        "WHERE p.research_session_id=? AND p.status!='Deleted' ORDER BY p.id DESC LIMIT 12", (session_id,))
    recent = evidence(store, session_id)
    pending = _pending_plate(store, session_id)
    latest_photo = store.one(
        "SELECT q.id,q.plan_id,q.status,q.photo_name FROM pair q JOIN plan p ON p.id=q.plan_id "
        "WHERE p.research_session_id=? AND q.status!='Deleted' ORDER BY q.id DESC LIMIT 1", (session_id,))
    accepted_session_photos = store.query(
        "SELECT q.id FROM pair q JOIN plan p ON p.id=q.plan_id "
        "WHERE p.research_session_id=? AND q.status='Accepted' ORDER BY q.id DESC", (session_id,))
    memory = store.one("SELECT through_message_id,summary,updated_at FROM research_memory WHERE session_id=?",
                       (session_id,))
    def plan_state(plan):
        if plan["status"] in {"Superseded", "Cancelled"}:
            return "historical"
        if plan["accepted_photo_count"]:
            return "has_accepted_photo"
        if plan["photo_count"]:
            return "photo_needs_review"
        return "awaiting_engraving_or_photo"
    return {
        "session": {k: session[k] for k in ("id", "goal", "target", "model", "status")},
        "current_state": {
            "pending_plan_id": pending["id"] if pending else None,
            "latest_photo": dict(latest_photo) if latest_photo else None,
            "accepted_session_photo_ids": [photo["id"] for photo in accepted_session_photos],
            "plan_status_legend": {"Superseded": "replaced historical plate",
                                   "Cancelled": "cancelled historical plate",
                                   "Exported": "downloaded file, not necessarily awaiting photo"},
        },
        "working_memory": dict(memory) if memory else None,
        "session_plans": [dict(p, lifecycle=plan_state(p),
                               replaceable=p["status"] in {"Ready to export", "Exported"}
                               and p["photo_count"] == 0) for p in session_plans],
        "device": {k: device.get(k) for k in ("id", "name", "manufacturer", "model", "serial", "passport")},
        "lens": dict(lens), "material": material,
        "findings": [{k: f.get(k) for k in ("pair_id", "purpose", "status", "summary", "parameters", "evidence", "next_test")}
                     for f in findings[:24]],
        "relative_color_candidates": {"photos": relative_color_photos,
                                      "limit": "RAW without a reference chart: compare candidates only within the same photo; do not treat these as proven color recipes. Missing Q-Pulse cannot be inferred from a layer name."},
        "recent_evidence": recent,
        "insights": [{"purpose": i["purpose"], "claim": i["claim"], "confidence": i["confidence"],
                      "pair_ids": json.loads(i["evidence_pair_ids_json"])} for i in store.query(
                          "SELECT * FROM research_insight WHERE session_id=? ORDER BY id DESC LIMIT 12", (session_id,))],
        "available_tests": [{"id": p["id"], "purpose": p["purpose"], "action": p["action"], "finds": p["finds"]}
                            for p in capability_plates.PLATE_TYPES],
    }


def next_test(store: Store, session_id: int) -> dict:
    session, _, _ = _scope(store, session_id)
    return application_guide.suggest(store, session["device_id"], session["material_id"], session["goal"])


def preview_plate(store: Store, session_id: int, test_type: str, settings: dict | None = None) -> dict:
    session, device, _ = _scope(store, session_id)
    if session["goal"] in {"deep", "relief_3d", "cutting"}:
        raise ResearchError("для глубины, 3D-рельефа и резки пока нет специальной платы и физического измерения; "
                            "поверхностный фототест не проверяет эту цель")
    if not device.get("lens") or device["lens"]["id"] != session["lens_id"]:
        raise ResearchError("установленная линза изменилась; создайте новое исследование для новой пары лазер–линза")
    prepared = capability_plates.preview(store, session["device_id"], session["material_id"], test_type, settings or {})
    return {"test_type": test_type, "name": prepared["experiment"]["test_name"],
            "summary": prepared["experiment"]["summary"],
            "test_settings": prepared["experiment"]["test_settings"],
            "cleanup_settings": prepared["experiment"]["cleanup_settings"],
            "label_settings": prepared["experiment"]["label_settings"],
            "output_layers": len(prepared["layers"]) + 2,
            "description": prepared["experiment"]["test_description"]}


def _pending_plate(store: Store, session_id: int):
    return store.one(
        "SELECT p.id,p.status,"
        "(SELECT COUNT(*) FROM pair q WHERE q.plan_id=p.id AND q.status!='Deleted') AS photo_count "
        "FROM plan p WHERE p.research_session_id=? AND p.status IN ('Ready to export','Exported') "
        "AND NOT EXISTS (SELECT 1 FROM pair q WHERE q.plan_id=p.id AND q.status='Accepted') "
        "ORDER BY p.id DESC LIMIT 1", (session_id,))


def cancel_pending_plate(store: Store, session_id: int, plan_id: int, reason: str) -> dict:
    _scope(store, session_id)
    reason = str(reason or "").strip()
    if not 4 <= len(reason) <= 500:
        raise ResearchError("укажите причину отмены платы (4–500 символов)")
    with store.transaction():
        pending = _pending_plate(store, session_id)
        if pending is None or pending["id"] != plan_id:
            raise ResearchError("эта плата не является текущей ожидающей платой исследования")
        if pending["photo_count"]:
            raise ResearchError("к плате уже привязано фото; сначала разберите эту проверку")
        store.execute("UPDATE plan SET status='Cancelled' WHERE id=?", (plan_id,))
        store.audit("research_plate_cancelled", session_id=session_id, plan_id=plan_id, reason=reason)
    return {"cancelled_plan_id": plan_id, "status": "Cancelled", "reason": reason}


def create_plate(store: Store, session_id: int, test_type: str, settings: dict | None = None,
                 *, replace_plan_id: int | None = None) -> dict:
    session, _, _ = _scope(store, session_id)
    pending = _pending_plate(store, session_id)
    if replace_plan_id is not None and (pending is None or pending["id"] != replace_plan_id):
        raise ResearchError("заменять можно только текущую ожидающую плату этого исследования")
    if pending and replace_plan_id != pending["id"]:
        raise ResearchError(f"плата №{pending['id']} уже ожидает гравировку и фото; "
                            "если пользователь просит переделать её, вызовите replace_pending_test")
    if pending and pending["photo_count"]:
        raise ResearchError("к ожидающей плате уже привязано фото; замена недоступна до разбора проверки")
    preview_plate(store, session_id, test_type, settings)
    values = {**(settings or {}), "research_goal": session["goal"], "research_session_id": session_id}
    plate = capability_plates.create(store, session["device_id"], session["material_id"], test_type, values,
                                     research_session_id=session_id, supersede_plan_id=replace_plan_id)
    store.audit("research_plate_created", session_id=session_id, plan_id=plate["plan_id"],
                replaces_plan_id=replace_plan_id)
    return {**plate, "plan_url": f"#/plans/{plate['plan_id']}",
            "download_url": f"/api/plans/{plate['plan_id']}/export.lbrn2",
            "replaced_plan_id": replace_plan_id}


def inspect_pair(store: Store, session_id: int, pair_id: int) -> dict:
    pair = _pair_in_scope(store, session_id, pair_id)
    common = {"pair_id": pair_id, "status": pair["status"], "photo_name": pair["photo_name"],
              "plan_id": pair["plan_id"], "photo_url": f"/api/pairs/{pair_id}/photo.png",
              "overlay_url": f"/api/pairs/{pair_id}/overlay.png?corrected=false"}
    if pair["status"] != ingest.ST_ACCEPTED:
        check = pair.get("check") or {}
        return common | {"alignment": check.get("alignment"), "problems": check.get("problems", []),
                         "warnings": check.get("warnings", []), "next_step": "Проверьте совмещение и маски в интерфейсе перед принятием измерений."}
    report = analysis.report_for_pair(store, pair_id)
    rows = [{k: row.get(k) for k in ("layer_index", "name", "role", "parameters", "measured_lab", "line_metrics", "submeasurements")}
            for row in report["rows"][:40]]
    return common | {"alignment": report["alignment"], "rows": rows,
                     "capability": report.get("capability"), "limitations": report["limitations"],
                     "analysis_url": f"#/analysis/{pair_id}"}


def run_photo_mapping(store: Store, session_id: int, pair_id: int) -> dict:
    pair = _pair_in_scope(store, session_id, pair_id)
    if pair["status"] == ingest.ST_ACCEPTED:
        return inspect_pair(store, session_id, pair_id)
    report = ingest.check_pair(store, pair_id)
    store.audit("research_photo_mapping", session_id=session_id, pair_id=pair_id,
                alignment_valid=bool(report.get("alignment", {}).get("valid")))
    return {"pair_id": pair_id, "status": ingest.get_pair(store, pair_id)["status"],
            "alignment": report.get("alignment"), "problems": report.get("problems", []),
            "warnings": report.get("warnings", []), "discrepancies": report.get("discrepancies", [])[:12],
            "layers": [{"index": r.get("index"), "name": r.get("name"), "result": r.get("result")}
                       for r in report.get("layers", [])[:40]],
            "overlay_url": f"/api/pairs/{pair_id}/overlay.png?corrected=false",
            "review_url": f"#/ingest?pair={pair_id}"}


def save_insight(store: Store, session_id: int, purpose: str, claim: str,
                 confidence: str, evidence_pair_ids: list[int]) -> dict:
    if purpose not in application_guide.GOALS:
        raise ResearchError("неизвестная задача гравировки")
    if confidence not in {"hypothesis", "candidate"}:
        raise ResearchError("AI-вывод может быть гипотезой или кандидатом; подтверждение делает оператор")
    claim = str(claim or "").strip()
    if not 12 <= len(claim) <= 1200:
        raise ResearchError("вывод должен содержать 12–1200 символов")
    ids = list(dict.fromkeys(int(pid) for pid in evidence_pair_ids))
    if not 1 <= len(ids) <= 12:
        raise ResearchError("укажите от 1 до 12 принятых фото-проверок как доказательства")
    for pair_id in ids:
        pair = _pair_in_scope(store, session_id, pair_id)
        if pair["status"] != ingest.ST_ACCEPTED:
            raise ResearchError(f"проверка №{pair_id} ещё не принята")
    found = store.one("SELECT id FROM research_insight WHERE session_id=? AND purpose=? AND claim=?",
                      (session_id, purpose, claim))
    if found:
        insight_id = found["id"]
    else:
        insight_id = store.execute(
            "INSERT INTO research_insight(session_id,purpose,claim,confidence,evidence_pair_ids_json,created_at) "
            "VALUES (?,?,?,?,?,?)", (session_id, purpose, claim, confidence, _json(ids), now())).lastrowid
        store.audit("research_insight_saved", session_id=session_id, insight_id=insight_id, pair_ids=ids)
    return {"id": insight_id, "purpose": purpose, "claim": claim, "confidence": confidence,
            "evidence_pair_ids": ids}


def _api_key() -> str | None:
    env = os.environ.get("OPENAI_API_KEY", "").strip()
    if env:
        return env
    if os.environ.get("TCE_DESKTOP"):          # under the desktop shell only the environment counts: no developer file is read
        return None
    paths = [Path.cwd() / ".env.local", Path(__file__).resolve().parents[2] / ".env.local"]
    for path in paths:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() == "OPENAI_API_KEY":
                    return value.strip().strip('"\'') or None
    return None


def ai_available() -> bool:
    """Whether a key for the language model is configured (environment or .env.local)."""
    return _api_key() is not None


def ai_library() -> bool:
    """Whether the language model's client library is installed in this environment (a wheel installed without its dependencies lacks it)."""
    return importlib.util.find_spec("openai") is not None


def openai_client():
    """The client the researcher and the designer's explanation use, or None without a key."""
    key = _api_key()
    if not key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=key, timeout=90.0, max_retries=1)


def started_client():
    """:func:`openai_client` for a screen: None without a key, and a client library that is missing or broken (a wheel installed without
    its dependencies) is the operator's message with what to do, not a server error; the library's own text names paths."""
    try:
        return openai_client()
    except Exception:
        raise ResearchError("the AI could not be started on this computer: a library it needs is missing or broken, install the app's "
                            "dependencies (see README)") from None


EXPLAIN_INSTRUCTIONS = """Ты помогаешь оператору лазерной гравировки по титану понять предложенный эксперимент.
Предложение уже рассчитано офлайн-алгоритмом по измерениям; ты его не меняешь и не выбираешь параметры.
Ответь по-русски обычным текстом, до 1800 знаков: что проверяет плата, почему выбран каждый набор (по полю rationale),
какие физические гипотезы стоит проверить на результате (рост оксидной плёнки, тепловой вклад, нестабильность),
и что будет считаться подтверждением или опровержением. Гипотезы называй гипотезами; не выдавай их за измерения.
Не предлагай другие параметры и не пиши, что что-то уже доказано."""


def proposal_explainer(client=None):
    """An explainer for ``designer.attach_explanation`` (REQ-006, DEC-013): it sends a brief of the proposal to the model the
    researcher uses and returns its plain text. None without a client and without a key: the proposal stays as it is."""
    client = client if client is not None else started_client()
    if client is None:
        return None

    def explain(proposal: dict) -> str:
        brief = {k: proposal.get(k) for k in ("id", "questions", "worth", "task", "setup", "stock", "group", "notes", "model",
                                              "unaddressed_targets")}
        brief["parameters"] = [{k: p.get(k) for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes", "reason",
                                                     "rationale", "target_id", "estimated_distance_to_target")}
                               for p in proposal.get("parameters", [])]
        result = client.responses.create(model=DEFAULT_MODEL, reasoning={"effort": "low"}, store=False, max_output_tokens=1400,
                                         instructions=EXPLAIN_INSTRUCTIONS, input=[{"role": "user", "content": _json(brief)}])
        return getattr(result, "output_text", "") or ""
    return explain


# The settings of a test plate. The pulse width is required: no value is filled in for it (DEC-043); it must be one of the
# laser's steps, which research_context lists.
SETTINGS_SCHEMA = {"type": "object", "properties": {"pulse_width": {"type": "number", "description": "Q-Pulse width in ns: a step of this laser"}},
                   "required": ["pulse_width"]}
TOOL_SPECS = [
    {"type": "function", "name": "research_context", "description": "Read this laser, lens, material, goal, accepted findings and available test types.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "suggest_next_test", "description": "Read the deterministic, evidence-based next test suggestion without creating a plate.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "preview_test", "description": "Validate and preview a content-sized LightBurn plate. For one to four tiny filled samples use test_type=small_patches; settings.patch_size_mm=3..5 and settings.patches=[{}, {power:30}, ...] (one dict per square). Set settings.registration=none for the smallest footprint (3 mm patch occupies 6 x 6 mm); full adds QR and four photo-registration marks. Optional settings.max_width_mm/max_height_mm (default 100, at most 300 mm) constrain the full size; they are only an upper bound. To see how a flat fill's colour changes with its size use test_type=fill_sizes; settings.recipes=[{}, {power:40}, ...] (1..7, missing keys from the base settings) and settings.widths_mm=[5,20,50,100] (1..5 widths of 3..300 mm) make one 4 mm high Scan strip per recipe and width, at most 28. For speed x wobble on open vector letters use test_type=material_matrix; settings.matrix={x_axis:speed,y_axis:wobble_size,geometry:vector_text,x_min:500,x_max:2300,x_count:3,y_min:0,y_max:0.08,y_count:3,wobble_step:0.02}. Zero wobble size is the OFF control. Laser limits, titanium cleaning first and <=30 output layers are enforced.",
     "parameters": {"type": "object", "properties": {"test_type": {"type": "string"}, "settings": SETTINGS_SCHEMA},
                    "required": ["test_type", "settings"]}, "strict": False},
    {"type": "function", "name": "create_test", "description": "Create one validated LightBurn plate for this research session; use only when the user asks to create a test.",
     "parameters": {"type": "object", "properties": {"test_type": {"type": "string"}, "settings": SETTINGS_SCHEMA},
                    "required": ["test_type", "settings"]}, "strict": False},
    {"type": "function", "name": "replace_pending_test", "description": "When the user asks to redo an unengraved test, atomically supersede the current pending plate and create a new validated LightBurn plate. Requires its plan ID. Refuses if any photo is linked. Old plate stays in history but can no longer be exported.",
     "parameters": {"type": "object", "properties": {"plan_id": {"type": "integer"},
                    "test_type": {"type": "string"}, "settings": SETTINGS_SCHEMA},
                    "required": ["plan_id", "test_type", "settings"]}, "strict": False},
    {"type": "function", "name": "cancel_pending_test", "description": "Cancel the current pending plate without creating a new one, only when the user asks to discard it. Requires a reason. Refuses if any photo is linked; preserves history.",
     "parameters": {"type": "object", "properties": {"plan_id": {"type": "integer"}, "reason": {"type": "string"}},
                    "required": ["plan_id", "reason"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "inspect_photo", "description": "Read a photo check or accepted per-vector measurements by pair ID for the same laser, lens and material.",
     "parameters": {"type": "object", "properties": {"pair_id": {"type": "integer"}}, "required": ["pair_id"],
                    "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "run_photo_mapping", "description": "Run existing automatic LightBurn-vector to photo alignment and measurement for an uploaded RAW pair. User still reviews and accepts it.",
     "parameters": {"type": "object", "properties": {"pair_id": {"type": "integer"}}, "required": ["pair_id"],
                    "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "save_research_insight", "description": "Store a cautious hypothesis or candidate derived from accepted photo evidence; never mark an AI result as production-proven.",
     "parameters": {"type": "object", "properties": {"purpose": {"type": "string"}, "claim": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["hypothesis", "candidate"]},
                    "evidence_pair_ids": {"type": "array", "items": {"type": "integer"}}},
                    "required": ["purpose", "claim", "confidence", "evidence_pair_ids"],
                    "additionalProperties": False}, "strict": True},
]


def call_tool(store: Store, session_id: int, name: str, arguments: dict, *, allow_create: bool = True) -> dict:
    if not isinstance(arguments, dict):
        raise ResearchError("аргументы инструмента должны быть объектом")
    if name == "research_context":
        return context(store, session_id)
    if name == "suggest_next_test":
        return next_test(store, session_id)
    if name == "preview_test":
        return preview_plate(store, session_id, arguments["test_type"], arguments.get("settings"))
    if name == "create_test":
        if not allow_create:
            raise ResearchError("за этот ответ уже создана одна плата")
        return create_plate(store, session_id, arguments["test_type"], arguments.get("settings"))
    if name == "replace_pending_test":
        if not allow_create:
            raise ResearchError("за этот ответ уже создана одна плата")
        return create_plate(store, session_id, arguments["test_type"], arguments.get("settings"),
                            replace_plan_id=int(arguments["plan_id"]))
    if name == "cancel_pending_test":
        return cancel_pending_plate(store, session_id, int(arguments["plan_id"]), arguments["reason"])
    if name == "inspect_photo":
        return inspect_pair(store, session_id, int(arguments["pair_id"]))
    if name == "run_photo_mapping":
        return run_photo_mapping(store, session_id, int(arguments["pair_id"]))
    if name == "save_research_insight":
        return save_insight(store, session_id, arguments["purpose"], arguments["claim"],
                            arguments["confidence"], arguments["evidence_pair_ids"])
    raise ResearchError(f"неизвестный инструмент: {name}")


INSTRUCTIONS = """Ты исследователь параметров лазерной обработки. Отвечай по-русски, кратко и предметно.
Используй данные выбранного физического лазера, установленной при создании сессии линзы и материала.
Отделяй результаты этой сессии от связанных данных того же оборудования в recent_evidence.
История диалога сохраняется, но старые ответы AI могут описывать уже заменённые платы. Текущее состояние
из current_state и session_plans важнее старых реплик. Перед ответом сверяй ID платы, статус, число фото
и accepted_photo_count. Экспортированная плата с принятым фото уже дала результат и не ожидает RAW.
Superseded/Cancelled — история, а не текущий тест. Не говори, что не знаешь статус, если он есть в контексте.
working_memory — конспект прошлых решений и гипотез, а не источник измерений. Полная история сохранена локально.
Когда пользователь спрашивает о результате, проверь последнее принятое фото через inspect_photo
и сравни предложенный suggest_next_test с пробелами именно этого результата. Ответь: что наблюдалось,
какие параметры это подтверждают, что пока неизвестно и какой один тест даст максимальный прирост знания.
Если появился новый предметный вывод, сохрани его с ID принятого фото.
Сначала изучи контекст и результаты. Для вывода о конкретном режиме называй фото-проверку №ID,
все записанные параметры и ограничения измерения. Отсутствующий параметр называй неизвестным.
Фото без эталонной карты даёт относительный отклик камеры, не стандартизованный цвет.
Контраст текста не доказывает читаемость; фото сверху не измеряет глубину и сквозной рез.
Для целей глубины, 3D-рельефа и резки сначала вызови suggest_next_test и честно укажи,
если специальная плата и физическое измерение ещё не реализованы. Не выдавай поверхностный тест за проверку глубины или реза.
Для предложения следующего теста укажи гипотезу, два меняемых параметра, фиксированные параметры,
проверяемый критерий и площадь платы. Предпочитай маленький тест, который снимает конкретную неопределённость.
Предел размера платы (по умолчанию 100 × 100 мм, не больше 300 мм) — лишь верхняя граница, а не желаемый размер.
Чтобы узнать, как цвет заливки меняется с её размером, выбирай fill_sizes: settings.recipes (1–7 рецептов)
и settings.widths_mm (1–5 ширин полосок, 3–300 мм). Для простой проверки одного режима или
сравнения 2–4 заливок выбирай small_patches: квадрат 3–5 мм, settings.patches с полными или частичными
параметрами каждого участка, settings.max_width_mm/max_height_mm как лимит всего файла.
Для минимальной площади ставь settings.registration="none"; тогда автоматическое совмещение фото менее
надёжно. Если важнее уверенная привязка фото к векторам, оставь "full" с QR и четырьмя метками.
Локальная очистка квадратиков и имеющихся меток встроена первым слоем. Не расширяй тест до
длинных надписей и линий, пока пользователь не определил нужные образцы.
Для сетки частота × скорость на заполненных буквах используй material_matrix с matrix.geometry="text".
Для опыта на однолинейных буквах с включённым и выключенным wobble используй material_matrix с
matrix.geometry="vector_text", осями speed и wobble_size (ноль выключает wobble) и matrix.wobble_step.
Этот тип делает одинаковые A8M B012 высотой 2 и 4 мм дважды в каждой ячейке, режим LightBurn Cut.
text_readability перебирает только мощность × скорость. Сначала проверь файл через preview_test.
Создавай плату только по явной просьбе пользователя. Не создавай более одной платы за ответ.
Если пользователь просит переделать ожидающую плату без фото, используй replace_pending_test:
старая останется в истории как заменённая, новая появится в той же сессии. Не проси ручной отмены.
Если пользователь просит только отменить ожидающую плату, используй cancel_pending_test.
Если к плате уже привязано фото, не заменяй и не отменяй её автоматически.
Не запускай лазер. Пользователь гравирует, загружает RAW, проверяет совмещение и принимает измерения.
AI-выводы в базе — гипотезы или кандидаты; не выдавай их за подтверждённый рабочий рецепт.
Когда из принятой фото-проверки следует новый предметный вывод, сохрани его через save_research_insight
со ссылкой на номер проверки и назови ограничение. Не сохраняй догадки без принятого фото.
"""


def _save_exchange(store: Store, session_id: int, question: str, response: str, trace: list[dict]) -> None:
    with store.transaction():
        store.execute("INSERT INTO research_message(session_id,role,content,tool_trace_json,created_at) VALUES (?,?,?,?,?)",
                      (session_id, "user", question, "[]", now()))
        store.execute("INSERT INTO research_message(session_id,role,content,tool_trace_json,created_at) VALUES (?,?,?,?,?)",
                      (session_id, "assistant", response, _json(trace), now()))
        store.execute("UPDATE research_session SET updated_at=? WHERE id=?", (now(), session_id))


def _refresh_memory(store: Store, session_id: int, model: str, client) -> None:
    """Compact completed turns into durable working memory; never discard the source messages."""
    old = store.one("SELECT through_message_id,summary FROM research_memory WHERE session_id=?", (session_id,))
    cursor = old["through_message_id"] if old else 0
    rows = store.query("SELECT id,role,content FROM research_message WHERE session_id=? AND id>? "
                       "ORDER BY id LIMIT 24", (session_id, cursor))
    if len(rows) < MEMORY_INTERVAL:
        return
    excerpt = [{"id": row["id"], "role": row["role"], "content": row["content"][:4000],
                "excerpt_truncated": len(row["content"]) > 4000} for row in rows]
    result = client.responses.create(
        model=model, reasoning={"effort": "low"}, store=False, max_output_tokens=1100,
        instructions=("Обнови рабочую память длительного исследования лазера. Ответь по-русски, до 3000 знаков. "
                      "Сохраняй цель пользователя, его решения и ограничения, установленные выводы со ссылкой "
                      "на ID принятого фото, гипотезы отдельно от фактов, открытые вопросы и согласованный "
                      "следующий шаг. Не объявляй слова AI измерением. Не сохраняй временный статус платы: "
                      "он всегда берётся из свежей базы. Не теряй важное из прежнего конспекта. "
                      "Если excerpt_truncated=true, это только предел переданного фрагмента, не делай "
                      "выводов о том, что сам ответ или работа оборвались."),
        input=[{"role": "user", "content": _json({"previous_memory": old["summary"] if old else "",
                                                   "new_messages": excerpt})}])
    if getattr(result, "status", None) == "incomplete":
        return
    summary = (getattr(result, "output_text", "") or "").strip()[:5000]
    if not summary:
        return
    with store.transaction():
        store.execute("INSERT INTO research_memory(session_id,through_message_id,summary,updated_at) "
                      "VALUES (?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET "
                      "through_message_id=excluded.through_message_id,summary=excluded.summary,"
                      "updated_at=excluded.updated_at", (session_id, rows[-1]["id"], summary, now()))


def _interrupted_after_write(store: Store, session_id: int, question: str, trace: list[dict]) -> dict | None:
    completed = [item for item in trace if item.get("result") and item["tool"] in
                 {"create_test", "replace_pending_test", "cancel_pending_test", "run_photo_mapping", "save_research_insight"}]
    if not completed:
        return None
    details = []
    for item in completed:
        result = item["result"]
        if item["tool"] in {"create_test", "replace_pending_test"}:
            details.append(f"Плата №{result['plan_id']} создана; файл LightBurn доступен справа.")
        elif item["tool"] == "cancel_pending_test":
            details.append(f"Плата №{result['cancelled_plan_id']} отменена.")
        elif item["tool"] == "run_photo_mapping":
            details.append(f"Проверка фото №{result['pair_id']} выполнена; откройте наложение и проверьте результат.")
        else:
            details.append(f"Гипотеза №{result['id']} сохранена.")
    reply = " ".join(details) + " AI не завершил пояснение. Действие сохранено; повторите вопрос, если нужен анализ."
    _save_exchange(store, session_id, question, reply, trace)
    return {"text": reply, "model": _session_row(store, session_id)["model"], "tool_trace": trace,
            "session": get_session(store, session_id)}


def answer(store: Store, session_id: int, message: str, client=None) -> dict:
    """One bounded Responses tool loop, persisting the conversation and tool evidence locally."""
    text = str(message or "").strip()
    if not 2 <= len(text) <= 4000:
        raise ResearchError("сообщение должно содержать 2–4000 символов")
    session = get_session(store, session_id)
    if session["status"] != "active":
        raise ResearchError("исследование закрыто")
    client = client if client is not None else started_client()
    if client is None:
        raise ResearchError("OPENAI_API_KEY не найден в окружении или локальном .env.local")
    if session["memory"] is None and session["message_count"] >= MEMORY_INTERVAL:
        try:
            _refresh_memory(store, session_id, session["model"], client)
            session = get_session(store, session_id)
        except Exception:
            # The full local transcript remains available if compaction is temporarily unavailable.
            pass
    # Preserve the whole chat locally; send the largest recent suffix that fits the bounded model context.
    history = []
    used_chars = 0
    history_window = 12 if session["memory"] else MAX_HISTORY
    for row in reversed(session["messages"][-history_window:]):
        if row["role"] not in ("user", "assistant"):
            continue
        content = row["content"]
        if history and used_chars + len(content) > MAX_HISTORY_CHARS:
            break
        history.append({"role": row["role"], "content": content})
        used_chars += len(content)
    history.reverse()
    input_items: list[Any] = [*history, {"role": "user", "content": text}]
    scope = context(store, session_id)
    instructions = INSTRUCTIONS + "\nКонтекст на начало ответа:\n" + _json(scope)[:45000]
    trace: list[dict] = []
    created = False
    response = None
    try:
        for _ in range(MAX_TOOL_CALLS + 1):
            response = client.responses.create(model=session["model"], reasoning={"effort": "medium"},
                                               instructions=instructions, input=input_items,
                                               tools=TOOL_SPECS, parallel_tool_calls=False,
                                               max_output_tokens=2400, store=False)
            calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
            if not calls:
                break
            input_items.extend(response.output)
            for item in calls:
                args: dict = {}
                try:
                    args = json.loads(item.arguments or "{}")
                    result = call_tool(store, session_id, item.name, args, allow_create=not created)
                    if item.name in {"create_test", "replace_pending_test"}:
                        created = True
                    output = {"ok": True, "result": result}
                    trace.append({"tool": item.name, "arguments": args, "result": result})
                except (KeyError, ValueError, TypeError) as exc:
                    output = {"ok": False, "error": str(exc)}
                    trace.append({"tool": item.name, "arguments": args, "error": str(exc)})
                input_items.append({"type": "function_call_output", "call_id": item.call_id,
                                    "output": _json(output)[:60000]})
        else:
            raise ResearchError("AI вызвал слишком много инструментов за один ответ; уточните задачу")
    except ResearchError:
        recovered = _interrupted_after_write(store, session_id, text, trace)
        if recovered:
            return recovered
        raise
    except Exception as exc:
        # The SDK exception can contain request details. Keep credentials and provider internals out of the UI.
        recovered = _interrupted_after_write(store, session_id, text, trace)
        if recovered:
            return recovered
        raise ResearchError(f"AI-сервис не ответил ({type(exc).__name__}). Проверьте доступ модели и оплату API.") from None
    output_text = (getattr(response, "output_text", "") or "").strip()
    if not output_text:
        recovered = _interrupted_after_write(store, session_id, text, trace)
        if recovered:
            return recovered
        raise ResearchError("AI не вернул текст ответа; повторите запрос")
    _save_exchange(store, session_id, text, output_text, trace)
    try:
        _refresh_memory(store, session_id, session["model"], client)
    except Exception:
        # A memory update cannot roll back the durable answer or experimental writes.
        pass
    return {"text": output_text, "model": session["model"], "tool_trace": trace,
            "session": get_session(store, session_id)}
