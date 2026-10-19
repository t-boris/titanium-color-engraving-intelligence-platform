"""Device-scoped archive and parameter-to-result lookups for accepted engravings.

A lookup returns observed evidence only (REQ-020): one summary per recipe, titanium context and engraving task, each with the
observations and photographs behind it, how many independent engravings it has, how far they agree where that is measured,
and the context it lacks. Predictions are a separate question (the colour model) and never mix in here.
"""
from __future__ import annotations

import json

from . import devices, model, setup as su, tasks
from .db import Store


def for_device(store: Store, device_id: int) -> list[dict]:
    """Every uploaded LightBurn/photo pair for a laser, including work awaiting review."""
    devices.get_device(store, device_id)
    pairs = store.query(
        "SELECT pa.id FROM pair pa WHERE pa.device_id=? AND pa.status!='Deleted' ORDER BY pa.created_at DESC,pa.id DESC", (device_id,))
    out = []
    for item in pairs:
        row = store.one("SELECT * FROM pair WHERE id=?", (item["id"],))
        pair = dict(row)
        context = json.loads(pair["context_json"] or "{}")
        # The lens of the work is the pair's lens record (DEC-063); the hardware snapshot stays as it was stored.
        setup = su.resolve(store, pair["device_id"], pair["lens_id"])
        hardware = json.loads(pair["hardware_json"] or "{}")
        if not hardware.get("device"):
            hardware = {"device": {k: setup["device"].get(k) for k in ("id", "name", "manufacturer", "model", "serial")},
                        "lens": su.lens_snapshot(setup)}
        observations = store.query("SELECT * FROM observation WHERE pair_id=? ORDER BY layer_index", (pair["id"],))
        out.append({
            "pair_id": pair["id"], "status": pair["status"], "created_at": pair["created_at"],
            "accepted_at": pair["accepted_at"], "engraving_title": pair["engraving_title"],
            "lightburn_name": pair["lightburn_name"], "photo_name": pair["photo_name"],
            "engraving_id": pair["engraving_id"], "rephoto_of": json.loads(pair["data_json"] or "{}").get("rephoto_of"),
            "plan_id": pair["plan_id"], "plate_id": pair["plate_id"],
            "lens_id": pair["lens_id"],
            "lens": None if setup["lens"] is None else {k: setup["lens"][k] for k in ("id", "name", "focal_length_mm", "field_mm", "expansion")},
            "hardware": hardware,
            "material": {"id": pair["material_id"], "name": context.get("titanium_name"), "grade": context.get("titanium_grade"),
                         "thickness_mm": context.get("titanium_thickness_mm"), "surface": context.get("titanium_surface"),
                         "batch": context.get("batch")},
            "photo_url": f"/api/pairs/{pair['id']}/photo.png",
            "source_photo_url": f"/api/pairs/{pair['id']}/source-photo",
            "lightburn_url": f"/api/pairs/{pair['id']}/lightburn",
            "analysis_url": f"/analysis/{pair['id']}" if pair["status"] == "Accepted" else None,
            "review_url": None if pair["status"] == "Accepted" else f"/ingest?pair={pair['id']}",
            "observations": [{"id": o["id"], "layer_index": o["layer_index"], "lab": json.loads(o["lab_json"]),
                              "parameters": json.loads(o["parameters_json"]), "model_eligible": bool(o["model_eligible"]),
                              "repeat_eligible": bool(o["repeat_eligible"]), "context": json.loads(o["context_json"]),
                              "task": tasks.of_observation(o)}
                             for o in observations],
        })
    return out


def lookup_result(store: Store, device_id: int, lens_id: int | None, parameters: dict, task: str | None = None) -> dict:
    """Find measured outcomes for exact settings on one laser and lens (None: the unknown-lens records), keeping
    LightBurn modes, titanium contexts and engraving tasks separate; of one task when ``task`` is given (REQ-020)."""
    devices.get_device(store, device_id)
    if task is not None:
        tasks.require(task)
    base_key = model.base_parameters_key(parameters)
    observations = [o for o in model.eligible_observations(store, device_id, lens_id)
                    if model.base_parameters_key(o["parameters"]) == base_key and (task is None or o["task"]["kind"] == task)]
    # A lookup is an empirical record, not a blend across titanium stock, batch, or focus. Return a
    # separate measured summary for each such context, each LightBurn execution configuration and each task.
    fields = ("material_id", "titanium_name", "titanium_grade", "titanium_thickness_mm", "titanium_surface", "batch", "focus")
    groups: dict[tuple, list[dict]] = {}
    for observation in observations:
        context_key = tuple(observation["context"].get(field) for field in fields)
        key = model.observation_key(observation["parameters"], observation["context"], observation["task"])
        groups.setdefault((key, observation["task"]["kind"], context_key), []).append(observation)
    matches = []
    for (key, kind, _), group in groups.items():
        summary = model.summarize(group)
        context = group[0]["context"]
        summary.update(parameters=group[0]["parameters"], key=key)
        matches.append({"key": key, "parameters": summary["parameters"], "lab": summary["lab"], "evidence": "observed",
                        "task": {"kind": kind, "basis": group[0]["task"].get("basis", tasks.DERIVED)},
                        "available_for_prediction": summary["available"], "confidence": summary["confidence"],
                        "expected_delta_e": summary["expected_delta_e"], "stability": summary["stability"],
                        "rig_repeatability": summary["rig_repeatability"],
                        "observation_ids": summary["observation_ids"],
                        "source_pair_ids": sorted({o["pair_id"] for o in group}),
                        "sample": {"observations": summary["observations"], "independent_engravings": summary["independent_engravings"],
                                   "engravings": summary["engravings"], "photographs": len({o["pair_id"] for o in group})},
                        "missing_context": _missing_context(lens_id, group),
                        "material_contexts": model.context_groups(group), "context": context})
    matches.sort(key=lambda item: (item["parameters"].get("layer_type") or "", item["context"].get("titanium_name") or "",
                                   item["context"].get("batch") or "", item["task"]["kind"], item["key"]))
    return {"device_id": device_id, "lens_id": lens_id, "parameters": parameters, "task": task, "evidence": "observed",
            "matches": matches}


def _missing_context(lens_id: int | None, group: list[dict]) -> list[str]:
    """What the evidence of one match lacks, as the codes the colour-map search uses (accepted chart-corrected observations
    only reach a lookup, so they are never camera-relative or provisional)."""
    out = []
    if lens_id is None:
        out.append("lens_unknown")
    if any(o["context"].get("batch") is None for o in group):
        out.append("batch_unknown")
    if any(o["context"].get("focus") is None for o in group):
        out.append("focus_unknown")
    if any(o["parameters"].get(k) is None for o in group for k in ("power", "frequency", "speed", "pulse_width", "passes")):
        out.append("settings_incomplete")
    return out
