"""Post-engraving analysis: compare an accepted pair with its plan (REQ-001, REQ-013).

The comparison metric depends on the plan mode:

* Discrete / plate / restored: delta E between each layer's planned color and its measured color.
* Tonal: planned and measured lightness per band, and contrast = largest minus smallest L across bands.
* Color-path: delta E to the planned color per band and the distance of the measured color from the
  trajectory polyline (proposed DEC-032).

Planned predictions are kept next to measured results and never overwritten. No pass/fail threshold is
invented: a deviation is only classified when the operator saved a delta E tolerance.
"""
from __future__ import annotations

import json

import numpy as np

from . import capability_results, color, designer, ingest, model, plans as pl, setup as su, tasks
from .db import Store


def _polyline_distance(lab, vertices: list) -> float:
    """Shortest Lab distance from a color to a polyline of Lab vertices."""
    p = np.asarray(lab, float)
    pts = [np.asarray(v, float) for v in vertices]
    if len(pts) == 1:
        return float(np.linalg.norm(p - pts[0]))
    best = float("inf")
    for a, b in zip(pts, pts[1:]):
        ab = b - a
        denom = float(ab @ ab)
        t = 0.0 if denom == 0 else max(0.0, min(1.0, float((p - a) @ ab) / denom))
        best = min(best, float(np.linalg.norm(p - (a + t * ab))))
    return best


def _observations(store: Store, pair_id: int) -> list[dict]:
    return [{"id": r["id"], "layer_index": r["layer_index"], "lab": json.loads(r["lab_json"]), "parameters": json.loads(r["parameters_json"]),
             "alignment": r["alignment_method"], "context": json.loads(r["context_json"]), "repeat_eligible": bool(r["repeat_eligible"]),
             "evidence": json.loads(r["evidence_json"]), "task": tasks.of_observation(r)}
            for r in store.query("SELECT * FROM observation WHERE pair_id=? ORDER BY layer_index", (pair_id,))]


def report_for_pair(store: Store, pair_id: int) -> dict:
    pair = ingest.get_pair(store, pair_id)
    if pair["status"] != ingest.ST_ACCEPTED:
        raise ingest.IngestError("the report needs an accepted pair")
    obs = _observations(store, pair_id)
    rules = su.get_rules(store, pair["device_id"], pair["lens_id"])
    tol = rules["delta_tolerance"]
    plan = pl.get_plan(store, pair["plan_id"]) if pair["plan_id"] else None
    mode = plan["mode"] if plan else None
    summaries = model.knowledge_summaries(store, pair["device_id"], pair["lens_id"])
    limitations = []
    planned = {l["index"]: l for l in plan["layers"]} if plan else {}
    # colours of a photograph without a chart, as they would look next to clean titanium (derived by get_pair, DEC-056)
    checked = {rep["index"]: rep for rep in (pair.get("check") or {}).get("layers", [])}
    scale = tasks.photo_scale((pair.get("check") or {}).get("alignment"))
    witness = next((o["lab"] for o in obs if o["evidence"].get("role") == tasks.WITNESS), None)
    rows = []
    for o in obs:
        role = o["evidence"].get("role", "test feature")
        # the cleaning witness and the marker layer are engraved operations of the system, never a planned colour
        layer = planned.get(o["layer_index"]) if role == "test feature" else None
        pred = (layer or {}).get("prediction")
        row = {"observation_id": o["id"], "layer_index": o["layer_index"], "name": o["evidence"].get("layer_name"), "parameters": o["parameters"],
               "measured_lab": o["lab"], "planned_lab": None, "delta_e": None, "within_tolerance": None, "planned_prediction": pred,
               "alignment": o["alignment"], "knowledge": None, "role": role,
               "submeasurements": o["evidence"].get("submeasurements", []), "line_metrics": o["evidence"].get("line_metrics"),
               "measured_lab_against_clean": (checked.get(o["layer_index"]) or {}).get("measured_lab_against_clean"),
               "task": o["task"]}
        # every quality metric with its method and basis, and what the task needs that a photograph cannot give (REQ-020)
        row["metrics"] = tasks.quality_metrics(
            o["task"]["kind"], lab=o["lab"], against_clean=row["measured_lab_against_clean"],
            mode=(o["evidence"].get("color_measurement") or {}).get("mode"), line_metrics=row["line_metrics"],
            tonal=(checked.get(o["layer_index"]) or {}).get("tonal"), scale=scale, clean_lab=witness if role != tasks.WITNESS else None)
        if pred is not None:
            row["planned_lab"] = pred["lab"]
            row["delta_e"] = color.delta_e(o["lab"], pred["lab"])
        elif layer is not None and mode == pl.MODE_PLATE:
            row["note"] = "calibration plate cells have no planned color"
        elif layer is not None and mode == pl.MODE_RESTORED:
            row["note"] = "no prediction: no knowledge entry of these settings had all three estimates when the plan was restored"
        elif layer is None and plan is not None and role == "test feature":
            row["note"] = "the layer is not part of the original plan"
        if row["delta_e"] is not None and tol is not None:
            row["within_tolerance"] = row["delta_e"] <= tol
        s = summaries.get(model.observation_key(o["parameters"], o["context"], o["task"]))
        if s:
            row["knowledge"] = {"independent_engravings": s["independent_engravings"], "stability": s["stability"], "rig_repeatability": s["rig_repeatability"],
                                "attribution_note": s["attribution_note"]}
        rows.append(row)
    result = {"pair_id": pair_id, "engraving_id": pair["engraving_id"], "engraving_title": pair["engraving_title"],
              "plan_id": pair["plan_id"], "mode": mode, "alignment": rows[0]["alignment"] if rows else None, "rows": rows,
              "clean_reference": (pair.get("check") or {}).get("clean_reference"), "photo_scale": scale,
              "tolerance": tol, "limitations": limitations, "metrics": {}}
    result["rephoto_of"] = pair.get("rephoto_of")
    result["photos"] = [dict(row) for row in store.query(
        "SELECT id,photo_name,status,created_at FROM pair WHERE engraving_id=? AND status!='Deleted' ORDER BY id",
        (pair["engraving_id"],))]
    result["rig_repeatability"] = model.engraving_rig_repeatability(store, pair["engraving_id"])
    result["target_checks"] = designer.target_checks(store, pair_id)
    plate_id = pair["plate_id"] or (plan or {}).get("plate_id")
    result["proposal"] = designer.proposal_of_plate(store, plate_id)       # a plate of the designer links back to its proposal
    result["capability"] = capability_results.report_for_pair(store, pair_id)
    mine = next((r for r in (plan or {}).get("reviews") or [] if r["engraving_id"] == pair["engraving_id"]), None)
    result["work_review"] = None if mine is None else {"plan_id": plan["id"], "work": plan["name"], "review": mine}      # DEC-090
    if plan is None:
        limitations.append("no original plan is linked to this pair: only measurements and repeat comparison are available")
    elif mode == pl.MODE_RESTORED:
        limitations.append("the plan was restored from the imported LightBurn file: a planned colour is the prediction its knowledge entry "
                           "gave when the plan was restored")
    if tol is None and result["capability"] is None:
        limitations.append("no delta E tolerance is saved for this laser and lens: deviations are shown but not classified")
    if any(o["evidence"].get("color_measurement", {}).get("mode") == "raw_camera_relative" for o in obs):
        limitations.append("these Lab readings are camera-relative RAW measurements; they are preserved for experiment analysis but excluded from standard-color predictions")
    if mode == pl.MODE_TONAL:
        _tonal(result, rows, planned)
    elif mode == pl.MODE_COLOR_PATH:
        _color_path(result, rows, plan, store)
    elif rows and any(r["delta_e"] is not None for r in rows):
        d = [r["delta_e"] for r in rows if r["delta_e"] is not None]
        result["metrics"] = {"kind": "color_deviation", "mean_delta_e": float(np.mean(d)), "max_delta_e": float(max(d)), "layers": len(d)}
    if result["capability"] is None and any(not (r["knowledge"] or {}).get("stability", {}).get("assessed") for r in rows):
        limitations.append("stability is not assessed for parameter sets with fewer than two independent engravings")
    notes = {r["knowledge"]["attribution_note"] for r in rows if r["knowledge"] and r["knowledge"]["attribution_note"]}
    limitations += sorted(notes)
    if any(o["alignment"] in ("manual", "manual shift", "manual rotation", "manual transform", "element anchor") for o in obs):
        limitations.append("the photograph was aligned manually or corrected by hand: review its vector overlay before using these measurements")
    return result


def _tonal(result: dict, rows: list[dict], planned: dict) -> None:
    both = [r for r in rows if r["planned_lab"] is not None]
    if not both:
        return
    planned_l = [r["planned_lab"][0] for r in both]
    measured_l = [r["measured_lab"][0] for r in both]
    for r in both:
        r["delta_l"] = r["measured_lab"][0] - r["planned_lab"][0]
    # monotonic: measured lightness must not fall as the planned lightness rises (compared in planned order)
    seq = [measured_l[i] for i in sorted(range(len(both)), key=lambda i: planned_l[i])]
    result["metrics"] = {"kind": "brightness_contrast", "bands": len(both), "planned_contrast": max(planned_l) - min(planned_l),
                         "measured_contrast": max(measured_l) - min(measured_l),
                         "mean_abs_delta_l": float(np.mean([abs(r["delta_l"]) for r in both])),
                         "monotonic": all(a <= b + 1e-9 for a, b in zip(seq, seq[1:]))}


def _color_path(result: dict, rows: list[dict], plan: dict, store: Store) -> None:
    points = plan.get("transfer", {}).get("points", [])
    labs = [p["lab"] for p in points if p.get("lab") is not None]
    if len(labs) != len(points) or not labs:
        result["limitations"].append("the plan does not store its trajectory colors: the distance from the path cannot be computed")
        labs = []
    for r in rows:
        r["path_distance"] = _polyline_distance(r["measured_lab"], labs) if labs else None
    d = [r["delta_e"] for r in rows if r["delta_e"] is not None]
    pd = [r["path_distance"] for r in rows if r["path_distance"] is not None]
    if d:
        result["metrics"] = {"kind": "delta_e_along_path", "bands": len(d), "mean_delta_e": float(np.mean(d)), "max_delta_e": float(max(d)),
                             "mean_path_distance": float(np.mean(pd)) if pd else None, "max_path_distance": float(max(pd)) if pd else None}
