"""Task-first experiment suggestions for one laser, installed lens and physical stock.

Suggestions are deterministic and auditable. They narrow measured ranges but never promote a
photographic contrast proxy to a production recipe or infer cutting depth from a surface photo.
A suggestion names its engraving task (REQ-020, ``tasks``) and the observed evidence it builds on.
"""
from __future__ import annotations

import json

from . import capability_results, devices, setup as su, tasks
from .db import Store


GOALS = {
    "text": ("Lettering", "Legible letters and numbers at the chosen size"),
    "line": ("Lines and drawings", "A continuous fine line and distinguishable adjacent lines"),
    "black_mark": ("Black marking", "A dark, high-contrast mark with repeatable appearance"),
    "white_mark": ("Light marking", "A light, high-contrast mark with repeatable appearance"),
    "color": ("Color on metal", "Repeatable color with a reference chart"),
    "cleaning": ("Cleaning", "Remove surface contamination without unwanted marks"),
    "image": ("Pictures and images", "Details, midtones and even areas"),
    "deep": ("Deep engraving", "Depth in millimeters and wall quality after engraving and cleaning cycles"),
    "relief_3d": ("3D relief and coins", "Layered relief, geometry and texture"),
    "cutting": ("Cutting", "Cut-through, kerf width and edge condition"),
}


def list_goals() -> list[dict]:
    return [{"id": key, "name": value[0], "objective": value[1]} for key, value in GOALS.items()]


def _bounded_center(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


STARTING_PULSE_NS = 200.0       # an editable starting value, only when the laser offers it (DEC-043)


def _settings(device: dict, params: dict | None = None) -> dict:
    """Settings of a suggested plate: measured ones when a finding gives them, else starting values. The pulse width
    starts at 200 ns only on a laser that offers that step; otherwise it is None and the operator chooses it."""
    passport = device["passport"]
    steps = [float(s["pulse_width_ns"]) for s in passport["pulse_steps"]]
    rate = passport["repetition_rate_khz"]
    values = {"power": 20.0, "speed": 900.0, "frequency": 48.0, "pulse_width": STARTING_PULSE_NS if STARTING_PULSE_NS in steps else None,
              "line_interval": 0.025, "passes": 1, "global_passes": 1}
    for key in ("power", "speed", "frequency", "pulse_width", "line_interval", "passes"):
        if params and params.get(key) is not None:
            values[key] = params[key]
    values["power"] = _bounded_center(float(values["power"]), 1.0, 100.0)
    values["speed"] = _bounded_center(float(values["speed"]), 1.0, 10000.0)
    values["frequency"] = _bounded_center(float(values["frequency"]), float(rate["min"]), float(rate["max"]))
    if values["pulse_width"] is not None:
        values["pulse_width"] = min(steps, key=lambda item: abs(item - float(values["pulse_width"])))
    return values


def _accepted_runs(store: Store, device_id: int, material_id: int, lens_id: int, test_type: str) -> int:
    return store.one(
        "SELECT COUNT(DISTINCT p.engraving_id) AS n FROM pair p "
        "JOIN plate t ON t.id=p.plate_id WHERE p.status='Accepted' AND p.device_id=? AND p.lens_id=? "
        "AND p.material_id=? AND t.test_type=?",
        (device_id, lens_id, material_id, test_type))["n"]


def _pending_plan(store: Store, device_id: int, material_id: int, lens_id: int, goal: str) -> int | None:
    rows = store.query(
        "SELECT p.id,p.data_json FROM plan p JOIN plate t ON t.id=p.plate_id "
        "LEFT JOIN research_session s ON s.id=p.research_session_id "
        "WHERE p.status IN ('Ready to export','Exported') "
        "AND (s.id IS NULL OR s.status!='Deleted') AND t.material_id=? "
        "AND p.device_id=? AND p.lens_id=? ORDER BY p.id DESC",
        (material_id, device_id, lens_id))
    for row in rows:
        experiment = json.loads(row["data_json"]).get("experiment") or {}
        if experiment.get("research_goal") != goal:
            continue
        accepted = store.one("SELECT COUNT(*) AS n FROM pair WHERE plan_id=? AND status='Accepted'", (row["id"],))["n"]
        if not accepted:
            return row["id"]
    return None


def _support(store: Store, finding: dict | None) -> dict | None:
    """The evidence behind a finding the suggestion builds on (REQ-020): its observations and the photographs of its
    engraving, how many independent engravings it has (one: its repeatability is not assessed) and the context it lacks."""
    if finding is None:
        return None
    pair = store.one("SELECT engraving_id, lens_id, context_json FROM pair WHERE id=?", (finding["pair_id"],))
    layer = (finding.get("evidence") or {}).get("layer_index")
    rows = [r for r in store.query("SELECT id, layer_index, parameters_json, evidence_json FROM observation WHERE pair_id=? ORDER BY id",
                                   (finding["pair_id"],)) if layer is None or r["layer_index"] == layer]
    photographs = store.one("SELECT COUNT(*) AS n FROM pair WHERE engraving_id=? AND status='Accepted'", (pair["engraving_id"],))["n"]
    missing = []
    if pair["lens_id"] is None:
        missing.append("lens_unknown")
    if json.loads(pair["context_json"] or "{}").get("batch") is None:
        missing.append("batch_unknown")
    if any((json.loads(r["evidence_json"] or "{}").get("color_measurement") or {}).get("mode") == "raw_camera_relative" for r in rows):
        missing.append("camera_relative")
    if any(json.loads(r["parameters_json"]).get(k) is None for r in rows for k in ("power", "frequency", "speed", "pulse_width", "passes")):
        missing.append("settings_incomplete")
    return {"evidence": "observed", "pair_id": finding["pair_id"], "observation_ids": [r["id"] for r in rows],
            "engravings": 1, "photographs": photographs, "repeatability": {"assessed": False, "engravings": 1},
            "missing_context": missing}


def suggest(store: Store, device_id: int, material_id: int, goal: str | None = None, task: str | None = None) -> dict:
    """The next step for an engraving task on one laser, its installed lens and one titanium stock. The task is either a goal
    of this guide or a task kind of REQ-020 (``task``), which names the goal that serves it."""
    if goal is None and task is not None:
        goal = tasks.TASKS[tasks.require(task)]["guide_goal"]
    if goal not in GOALS:
        raise su.ValidationError("unknown engraving task")
    kind = tasks.require(task) if task is not None else tasks.GOAL_TASK[goal]
    device = devices.get_device(store, device_id)
    if not device.get("lens"):
        raise su.ValidationError("first install a lens on the selected laser")
    material = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
    if material is None:
        raise su.ValidationError("select a material and specific stock")
    lens_id = device["lens"]["id"]
    findings = [finding for finding in capability_results.findings_for_device(store, device_id)
                if finding["material_id"] == material_id and finding["lens_id"] == lens_id]
    latest = {}
    for finding in findings:
        latest.setdefault(finding["purpose"], finding)
    source = latest.get(goal)
    line = latest.get("line")
    text = latest.get("text")
    title, objective = GOALS[goal]
    base = {"goal": goal, "goal_name": title, "objective": objective, "task": {"kind": kind, "name": tasks.TASKS[kind]["name"]},
            "support": _support(store, source),
            "device": {"id": device_id, "name": device["name"]},
            "lens": {"id": lens_id, "name": device["lens"]["name"]},
            "material": {key: material[key] for key in ("id", "name", "family", "grade", "batch")},
            "finding": source, "plate": None, "status": "needs_test"}
    pending = _pending_plan(store, device_id, material_id, lens_id, goal)
    if pending:
        return base | {"status": "awaiting_photo", "pending_plan_id": pending,
                       "message": "The next plate for this goal has already been created. Continue with it instead of creating another.",
                       "next_step": "Open the plate’s LightBurn file, engrave it and add a RAW photo."}
    if goal in {"deep", "relief_3d", "cutting"}:
        details = {
            "deep": "Depth must be measured after each engraving and cleaning cycle; a surface photo cannot determine it.",
            "relief_3d": "Relief requires a height map or profilometry, not only a top-down photograph.",
            "cutting": "Cutting requires thickness, confirmation of cut-through and an edge assessment; current plates measure the surface.",
        }
        return base | {"status": "measurement_needed", "message": details[goal],
                       "next_step": "Add depth or edge measurement and a dedicated plate for this goal; no ready settings are available yet."}
    if material["family"] != "Titanium":
        return base | {"status": "cleaning_recipe_needed",
                       "message": "There is no verified preliminary cleaning recipe for this material yet. Titanium cleaning cannot be applied automatically.",
                       "next_step": "First save and verify a cleaning recipe for this material."}
    if goal == "text":
        if _accepted_runs(store, device_id, material_id, lens_id, "text_readability") >= 3:
            return base | {"status": "manual_review_needed",
                           "message": "Three lettering photo tests are already complete. Further narrowing based only on contrast may reduce legibility.",
                           "next_step": "Compare the actual letters and edges on the piece; mark the best option before the next test."}
        if text and text["status"] == "contrast_candidate":
            candidate = text["evidence"].get("parameters")
            rounds = sum(f["purpose"] == "text" and f["status"] == "contrast_candidate" for f in findings)
            settings = _settings(device, candidate)
            settings["text_spread"] = max(0.06, round(0.20 * (0.7 ** rounds), 3))
            message = ("The next small test narrows power and speed around the highest-contrast sample. "
                       "This search uses contrast: check letter legibility and edges on the piece before selecting production settings.")
            basis = text
        else:
            seed = (line["parameters"] if line and line["parameters"] else
                    text["evidence"].get("parameters") if text else None)
            settings = _settings(device, seed)
            message = ("Compare lettering at three power levels and three speeds, with three font sizes for each setting. "
                       "The starting point uses a confirmed line." if line and line["parameters"] else
                       "The starting point uses a distinguishable line; Q-Pulse was missing from the source file, so the specification value must be checked." if seed else
                       "Compare lettering at three power levels and three speeds, using baseline values from the specification.")
            basis = text or line
        settings["power"] = min(settings["power"], 83.0)
        settings["speed"] = min(settings["speed"], 8000.0)
        return base | {"status": "candidate_to_test", "message": message,
                       "next_step": "Engrave, add a RAW photo, check alignment and compare the A8M letters.",
                       "plate": {"test_type": "text_readability", "settings": settings,
                                 "source_pair_id": basis["pair_id"] if basis else None}}
    if goal == "line":
        seed = line["parameters"] or line["evidence"].get("parameters") if line else None
        if seed:
            settings = _settings(device, seed)
            power, speed = settings["power"], settings["speed"]
            rounds = _accepted_runs(store, device_id, material_id, lens_id, "material_matrix")
            if rounds >= 3:
                return base | {"status": "manual_review_needed", "message": "Three follow-up line matrices have already been measured.",
                               "next_step": "Compare the marks on metal and the repeatability of the selected settings before use."}
            spread = 0.25 * (0.7 ** rounds)
            settings["matrix"] = {"x_axis": "power", "y_axis": "speed", "geometry": "line",
                                  "x_min": round(max(1.0, power * (1 - spread)), 2), "x_max": round(min(100.0, power * (1 + spread)), 2), "x_count": 3,
                                  "y_min": round(max(1.0, speed * (1 - spread * 1.2)), 1),
                                  "y_max": round(min(10000.0, speed * (1 + spread * 1.2)), 1), "y_count": 3}
            return base | {"status": "candidate_to_test", "message": "Test a 3 × 3 neighborhood around the observed line; missing Q-Pulse is taken from the specification and checked again.",
                           "next_step": "Repeat the best lines and check their visibility in a new RAW photo.",
                           "plate": {"test_type": "material_matrix", "settings": settings, "source_pair_id": line["pair_id"]}}
        return base | {"message": "First find the region of visible lines using a compact survey plate.",
                       "next_step": "Make a survey plate, then narrow power and speed.",
                       "plate": {"test_type": "compact_capability", "settings": _settings(device), "source_pair_id": None}}
    mapping = {
        "black_mark": ("calibration", "Compare patch brightness. Select black settings only after checking the piece and a repeat photo."),
        "white_mark": ("calibration", "Compare patch brightness. Select light settings only after checking the piece and a repeat photo."),
        "color": ("calibration", "Color selection requires RAW photos with a reference chart and repeated samples."),
        "cleaning": ("compact_capability", "Assess the cleaned background separately from the test patches; a separate comparative cleaning test is needed next."),
        "image": ("hatch_interval", "Check hatch spacing; a sample with details and midtones will be needed later."),
    }
    test_type, message = mapping[goal]
    if _accepted_runs(store, device_id, material_id, lens_id, test_type):
        return base | {"status": "manual_review_needed",
                       "message": "The baseline plate for this goal has already been measured. Repeating it without a separate quality assessment is not useful.",
                       "next_step": "Compare the result on the piece and refine the criterion: brightness, color, uniformity, fine detail or cleaning level."}
    return base | {"message": message, "next_step": "Engrave a small plate and add a RAW photo of the same piece.",
                   "plate": {"test_type": test_type, "settings": _settings(device),
                             "source_pair_id": source["pair_id"] if source else None}}
