"""Color-space model: knowledge from eligible observations, estimates and predictions.

Measured values are never changed (REQ-001): everything here is derived on read from the immutable
observation rows and carries the ids of the observations it was derived from. The formulas for confidence,
expected color error and stability are an explicit assumption (proposed DEC-029); the requirements define
only that all three must accompany every prediction (REQ-002).
"""
from __future__ import annotations

import json
import hashlib
import math
from typing import Any

import numpy as np

from . import color, lightburn
from .db import Store

CONFIDENCE_K = 2.0


def _normalized_setting(value):
    """A layer setting as data for the key: numbers written differently ('20', '20.0') are the same value, at any depth
    (sub-layers nest their own settings)."""
    if isinstance(value, dict):
        return {attr: _normalized_setting(raw) for attr, raw in value.items()}
    if isinstance(value, list):
        return [_normalized_setting(item) for item in value]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return f"{number:g}" if math.isfinite(number) else value


def parameters_key(p: dict) -> str:
    """Key all six requested settings and any recorded LightBurn execution controls.

    Legacy rows with no additional LightBurn metadata keep their original readable key. For imported
    files, line/fill mode, scan controls, and preserved source settings prevent unlike operations from
    being averaged together even when their six numeric settings happen to match.
    """
    base = "|".join("?" if p.get(k) is None else f"{float(p[k]):g}" for k in
                    ("power", "frequency", "speed", "pulse_width", "line_interval", "passes"))
    controls = {k: p[k] for k in ("layer_type", "global_passes", "bidirectional", "cross_hatch", "scan_angle", "angle_increment") if k in p}
    source = p.get("source_settings")
    if source:
        known = {"maxPower", "frequency", "speed", "QPulseWidth", "interval", "numPasses", "passes",
                 "globalRepeat", "bidir", "crossHatch", "angle", "anglePerPass"}
        extra = {}
        for tag, value in source.items():
            if tag in known:
                continue  # normalized equivalents are already represented above
            extra[tag] = _normalized_setting(value)
        if extra:
            controls["source_settings"] = extra
    if not controls:
        return base
    encoded = json.dumps(controls, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"{base}|lb:{hashlib.sha256(encoded).hexdigest()}"


TEST_FEATURE_SQL = "COALESCE(json_extract(o.evidence_json, '$.role'), 'test feature')='test feature'"


def eligible_observations(store: Store, device_id: int, lens_id: int | None) -> list[dict]:
    """Chart-gated observations of one laser and one lens record (DEC-063); an unknown lens (None) is a partition of its own.

    Only test features: a cleaning witness or a marker and label layer accepted as eligible by an older version is still
    left out (DEC-027, DEC-028)."""
    out = []
    rows = store.query(
        "SELECT o.*,p.photo_name,p.lightburn_name,p.accepted_at,p.created_at AS pair_created_at,p.material_id "
        "FROM observation o JOIN pair p ON p.id=o.pair_id WHERE o.device_id=? AND o.lens_id IS ? AND p.status='Accepted' "
        f"AND o.model_eligible=1 AND {TEST_FEATURE_SQL} ORDER BY o.id", (device_id, lens_id))
    for r in rows:
        out.append({"id": r["id"], "pair_id": r["pair_id"], "engraving_id": r["engraving_id"], "lab": json.loads(r["lab_json"]),
                    "parameters": json.loads(r["parameters_json"]), "repeat_eligible": bool(r["repeat_eligible"]),
                    "context": json.loads(r["context_json"]), "alignment": r["alignment_method"],
                    "source": {"photo_name": r["photo_name"], "lightburn_name": r["lightburn_name"],
                               "accepted_at": r["accepted_at"], "created_at": r["pair_created_at"],
                               "material_id": r["material_id"]}})
    return out


def knowledge_key_of(row) -> str | None:
    """The knowledge entry an observation row counts toward within its laser and lens, or None when it feeds no knowledge."""
    if not row["model_eligible"] or json.loads(row["evidence_json"] or "{}").get("role", "test feature") != "test feature":
        return None
    return observation_key(json.loads(row["parameters_json"]), json.loads(row["context_json"]))


def _by_engraving(obs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for o in obs:
        groups.setdefault(o["engraving_id"], []).append(o)
    return groups


def summarize(obs: list[dict]) -> dict:
    """Derived values for the observations that share one parameter vector."""
    groups = _by_engraving(obs)
    per_engraving = np.array([np.mean([o["lab"] for o in g], axis=0) for g in groups.values()])
    independent = len({o["engraving_id"] for o in obs if o["repeat_eligible"]})
    n = len(per_engraving)
    lab = per_engraving.mean(axis=0)
    if n >= 2:
        variance = float(np.var(per_engraving, axis=0, ddof=1).sum())
        deviations = [color.delta_e(x, lab) for x in per_engraving]
        stability = {"assessed": True, "variance": variance, "max_deviation": max(deviations), "engravings": n}
    else:
        variance, deviations = None, [0.0]
        stability = {"assessed": False, "variance": None, "max_deviation": None, "engravings": n}
    repeat_devs = [color.delta_e(o["lab"], np.mean([x["lab"] for x in g], axis=0)) for g in groups.values() if len(g) > 1 for o in g]
    rig = {"assessed": bool(repeat_devs), "photos": max(len(g) for g in groups.values()),
           "mean_delta_e": float(np.mean(repeat_devs)) if repeat_devs else None}
    expected = None if variance is None else math.sqrt(variance) + (rig["mean_delta_e"] or 0.0)
    confidence = n / (n + CONFIDENCE_K) if variance is not None else None
    return {"lab": [float(v) for v in lab], "observation_ids": [o["id"] for o in obs], "observations": len(obs),
            "independent_engravings": independent, "engravings": n, "stability": stability, "rig_repeatability": rig,
            "expected_delta_e": expected, "confidence": confidence, "available": variance is not None,
            "context_groups": context_groups(obs)}


def context_groups(obs: list[dict]) -> list[dict]:
    """Keep stock identity, batch and focus attached to each measured result grouping."""
    groups: dict[tuple, list[dict]] = {}
    fields = ("material_id", "titanium_name", "titanium_grade", "titanium_thickness_mm", "titanium_surface", "batch", "focus")
    for o in obs:
        c = o["context"]
        groups.setdefault(tuple(c.get(k) for k in fields), []).append(o)
    out = []
    for values, g in groups.items():
        context = dict(zip(fields, values))
        batch, focus = context["batch"], context["focus"]
        labs = np.array([o["lab"] for o in g])
        out.append({**context, "batch_known": batch is not None, "focus_known": focus is not None,
                    "material_known": context["material_id"] is not None or context["titanium_name"] is not None,
                    "observations": len(g), "mean_lab": [float(v) for v in labs.mean(axis=0)]})
    return out


def attribution_note(groups: list[dict]) -> str | None:
    """REQ-010/016: say plainly when unknown context prevents attributing a deviation."""
    if len(groups) < 2 and not any(not g["batch_known"] or not g["focus_known"] for g in groups):
        return None
    unknown = [g for g in groups if not g["batch_known"] or not g["focus_known"]]
    if unknown:
        return "Context is unknown for some repeats: a deviation cannot be attributed to material batch or focus for those."
    return None


def knowledge_summaries(store: Store, device_id: int, lens_id: int | None) -> dict[str, dict]:
    """One summary per recipe key within the laser and lens: different job settings never share a summary (DEC-042)."""
    groups: dict[str, list[dict]] = {}
    for o in eligible_observations(store, device_id, lens_id):
        groups.setdefault(observation_key(o["parameters"], o["context"]), []).append(o)
    out = {}
    for key, obs in groups.items():
        s = summarize(obs)
        s["parameters"] = obs[0]["parameters"]
        s["key"] = key
        s["attribution_note"] = attribution_note(s["context_groups"])
        out[key] = s
    return out


def _finish_camera_relative_set(entry: dict) -> dict:
    """Add same-photo comparisons and human-readable findings to one relative set."""
    clean = next((s for s in entry["samples"] if s["role"] == "pre-test cleaning witness"), None)
    tests = [s for s in entry["samples"] if s["role"] == "test feature"]
    if clean:
        for sample in tests:
            sample["delta_e_from_clean_witness"] = color.delta_e(sample["lab"], clean["lab"])
            for sub in sample["submeasurements"]:
                if sub.get("measured_lab") is not None:
                    sub["delta_e_from_clean_witness"] = color.delta_e(sub["measured_lab"], clean["lab"])
    for sample in entry["samples"]:
        lab = sample["lab"]
        if sample.get("delta_e_from_clean_witness", 99) <= 4:
            sample["relative_appearance"] = "почти как очищенная поверхность на этом фото"
        elif lab[0] < 28:
            sample["relative_appearance"] = "тёмный, почти чёрный на этом фото"
        elif lab[2] >= 8:
            sample["relative_appearance"] = "тёплый / желтоватый сдвиг b* на этом фото"
        elif lab[0] >= 40 and (lab[1] ** 2 + lab[2] ** 2) ** 0.5 < 10:
            sample["relative_appearance"] = "нейтральный серый / серебристый вид на этом фото"
        else:
            sample["relative_appearance"] = "относительный оттенок на этом фото"
    findings = []
    if tests:
        darkest = min(tests, key=lambda s: s["lab"][0])
        brightest = max(tests, key=lambda s: s["lab"][0])
        warmest = max(tests, key=lambda s: s["lab"][2])
        findings = [
            {"kind": "darkest", "label": "Самый тёмный тестовый след", "name": darkest["name"], "lab": darkest["lab"], "parameters": darkest["parameters"]},
            {"kind": "brightest", "label": "Самый светлый тестовый участок", "name": brightest["name"], "lab": brightest["lab"], "parameters": brightest["parameters"]},
            {"kind": "warmest", "label": "Наибольшее смещение по жёлтой оси b*", "name": warmest["name"], "lab": warmest["lab"], "parameters": warmest["parameters"]},
        ]
        if clean:
            distinct = max(tests, key=lambda s: s.get("delta_e_from_clean_witness", 0.0))
            findings.append({"kind": "surface_contrast", "label": "Сильнее всего отличается от очищенной поверхности",
                             "name": distinct["name"], "lab": distinct["lab"], "delta_e": distinct["delta_e_from_clean_witness"],
                             "parameters": distinct["parameters"]})
    entry["findings"] = findings
    # Keep every filled test patch as a traceable color *candidate*. A layer mean must not
    # hide separately measured patches, and text/line witnesses are not color swatches.
    variants = []
    for sample in tests:
        p = sample["parameters"]
        if p.get("layer_type") not in {"Scan", "Fill", "Offset Fill"} or sample["name"].upper().startswith("TEXT"):
            continue
        pieces = [sub for sub in sample["submeasurements"] if sub.get("measured_lab") is not None]
        for piece in pieces or [None]:
            lab = piece["measured_lab"] if piece else sample["lab"]
            variants.append({
                "pair_id": entry["pair_id"], "observation_id": sample["observation_id"],
                "layer_index": sample["layer_index"],
                "name": f"{sample['name']} / {piece['name']}" if piece else sample["name"],
                "lab": lab, "parameters": p,
                "pixels": piece.get("pixels") if piece else sample.get("pixels"),
                "delta_e_from_clean_witness": (piece or sample).get("delta_e_from_clean_witness"),
                "settings_complete": all(p.get(k) is not None for k in
                                         ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")),
                "status": "provisional" if entry.get("provisional") else "measured_relative",
            })
    entry["color_variants"] = variants
    entry["limits"] = ["Цвет и Lab относительны только к этому RAW-снимку. Разные фото нельзя объединять без эталонной карты.",
                       "Эти наблюдения видны на карте для сравнения, но не используются как стандартные цветовые прогнозы."]
    return entry


def camera_relative_sets(store: Store, device_id: int, lens_id: int | None) -> list[dict]:
    """Return per-photo RAW observations of one laser and lens for the color map without mixing them into predictions.

    Camera-relative Lab is useful for ranking marks within the same photograph. It is not normalized
    across photos and must never enter the standard-color prediction model.
    """
    rows = store.query(
        "SELECT o.*,p.photo_name,p.lightburn_name,p.accepted_at,p.context_json,p.data_json,p.material_id,"
        "m.name AS material_name,m.grade AS material_grade,m.batch AS material_batch,t.test_type "
        "FROM observation o JOIN pair p ON p.id=o.pair_id "
        "LEFT JOIN material_profile m ON m.id=p.material_id "
        "LEFT JOIN plate t ON t.id=COALESCE(p.plate_id,(SELECT plate_id FROM plan WHERE id=p.plan_id)) "
        "WHERE o.device_id=? AND o.lens_id IS ? AND p.status='Accepted' ORDER BY p.accepted_at DESC,p.id DESC,o.layer_index",
        (device_id, lens_id))
    grouped: dict[int, dict] = {}
    for row in rows:
        evidence = json.loads(row["evidence_json"] or "{}")
        measurement = evidence.get("color_measurement") or {}
        if measurement.get("mode") != "raw_camera_relative":
            continue
        pair_data = json.loads(row["data_json"] or "{}")
        check = pair_data.get("check") or {}
        layer_report = next((item for item in check.get("layers", [])
                             if item.get("index") == row["layer_index"]
                             or (item.get("name") and item.get("name") == evidence.get("layer_name"))), {})
        sample = {"observation_id": row["id"], "layer_index": row["layer_index"],
                  "name": evidence.get("layer_name") or f"Слой {row['layer_index']}",
                  "role": evidence.get("role") or "test feature", "lab": json.loads(row["lab_json"]),
                  "parameters": json.loads(row["parameters_json"]), "pixels": evidence.get("pixels"),
                  "line_metrics": evidence.get("line_metrics"), "submeasurements": evidence.get("submeasurements", []),
                  "notes": layer_report.get("notes", []),
                  "available_for_prediction": False}
        context = json.loads(row["context_json"] or "{}")
        entry = grouped.setdefault(row["pair_id"], {
            "pair_id": row["pair_id"], "photo_name": row["photo_name"], "lightburn_name": row["lightburn_name"],
            "accepted_at": row["accepted_at"], "test_type": row["test_type"],
            "material": {"id": row["material_id"], "name": row["material_name"] or context.get("titanium_name"),
                         "grade": row["material_grade"] or context.get("titanium_grade"),
                         "batch": row["material_batch"] or context.get("batch")},
            "measurement": {"mode": "raw_camera_relative", "reference_chart_used": False,
                            "relative_to_this_photo_only": True},
            "warnings": check.get("warnings", []), "samples": []})
        entry["samples"].append(sample)

    for entry in grouped.values():
        _finish_camera_relative_set(entry)

    # A checked but not yet accepted RAW pair already contains useful, photo-relative measurements.
    # Show them on the map as provisional evidence so one experiment is not invisible while awaiting
    # mask review; acceptance remains the only path that writes immutable observation rows.
    pending_rows = store.query(
        "SELECT p.id,p.status,p.created_at,p.data_json,p.context_json,p.photo_name,p.lightburn_name,p.material_id,"
        "m.name AS material_name,m.grade AS material_grade,m.batch AS material_batch,t.test_type "
        "FROM pair p LEFT JOIN material_profile m ON m.id=p.material_id "
        "LEFT JOIN plate t ON t.id=COALESCE(p.plate_id,(SELECT plate_id FROM plan WHERE id=p.plan_id)) "
        "WHERE p.device_id=? AND p.lens_id IS ? AND p.status NOT IN ('Accepted','Deleted') ORDER BY p.created_at DESC,p.id DESC",
        (device_id, lens_id))
    for row in pending_rows:
        data = json.loads(row["data_json"] or "{}")
        check = data.get("check") or {}
        measurement = check.get("color_measurement") or {}
        alignment = check.get("alignment") or {}
        if measurement.get("mode") != "raw_camera_relative" or not alignment.get("valid"):
            continue
        context = json.loads(row["context_json"] or "{}")
        entry = {"pair_id": row["id"], "photo_name": row["photo_name"], "lightburn_name": row["lightburn_name"],
                 "accepted_at": None, "test_type": row["test_type"], "provisional": True,
                 "status": row["status"], "masks_reviewed": bool(data.get("masks_reviewed")),
                 "check_problems": check.get("problems", []),
                 "warnings": check.get("warnings", []),
                 "material": {"id": row["material_id"], "name": row["material_name"] or context.get("titanium_name"),
                              "grade": row["material_grade"] or context.get("titanium_grade"),
                              "batch": row["material_batch"] or context.get("batch")},
                 "measurement": {"mode": "raw_camera_relative", "reference_chart_used": False,
                                 "relative_to_this_photo_only": True}, "samples": []}
        for rep in check.get("layers", []):
            if rep.get("measured_lab") is None:
                continue
            params = {"power": rep.get("power"), "frequency": rep.get("frequency_khz"), "speed": rep.get("speed"),
                      "pulse_width": rep.get("pulse_width"), "line_interval": rep.get("line_interval"), "passes": rep.get("passes"),
                      "layer_type": rep.get("type"), "global_passes": rep.get("global_passes"),
                      "bidirectional": rep.get("bidirectional"), "cross_hatch": rep.get("cross_hatch"),
                      "scan_angle": rep.get("scan_angle"), "angle_increment": rep.get("angle_increment"),
                      "source_settings": lightburn.recipe_settings(rep.get("source_settings"))}
            entry["samples"].append({"observation_id": None, "layer_index": rep.get("index"),
                                     "name": rep.get("name") or f"Слой {rep.get('index')}",
                                     "role": rep.get("role") or "test feature", "lab": rep["measured_lab"],
                                     "parameters": params, "pixels": rep.get("pixels"),
                                     "line_metrics": rep.get("line_metrics"), "submeasurements": rep.get("submeasurements", []),
                                     "notes": rep.get("notes", []),
                                     "available_for_prediction": False})
        if entry["samples"]:
            grouped[row["id"]] = _finish_camera_relative_set(entry)
    return sorted(grouped.values(), key=lambda item: (item.get("accepted_at") is not None,
                                                     item.get("accepted_at") or "", item["pair_id"]), reverse=True)


def base_parameters_key(p: dict) -> str:
    """The six numeric settings alone, used for a forward lookup across operation variants."""
    return "|".join("?" if p.get(k) is None else f"{float(p[k]):g}" for k in
                    ("power", "frequency", "speed", "pulse_width", "line_interval", "passes"))


def observation_key(parameters: dict, context: dict | None = None) -> str:
    """Keep results for different titanium stocks separate; unknown stock never joins a known one."""
    key = parameters_key(parameters)
    context = context or {}
    stock = {k: context.get(k) for k in ("material_id", "titanium_name", "titanium_grade", "titanium_thickness_mm",
                                         "titanium_surface", "batch") if context.get(k) is not None}
    if not stock:
        return key
    if stock.get("material_id") is not None:
        suffix = f"id:{stock['material_id']}"
    else:
        encoded = json.dumps(stock, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        suffix = "spec:" + hashlib.sha256(encoded).hexdigest()
    return f"{key}|ti:{suffix}"


def coverage_box(samples: list[dict]) -> tuple[np.ndarray, np.ndarray] | None:
    labs = np.array([s["lab"] for s in samples if s["available"]])
    return None if labs.size == 0 else (labs.min(axis=0), labs.max(axis=0))


def predict_for_lab(samples: list[dict], target_lab) -> dict:
    """Nearest available measured sample for a requested color. Never returns a partial prediction (REQ-002)."""
    if not color.valid_lab(target_lab):
        raise ValueError("target color is not a valid Lab value")
    avail = [s for s in samples if s["available"]]
    if not avail:
        return {"available": False, "reason": "not enough data for a prediction", "outside_coverage": True}
    best = min(avail, key=lambda s: (color.delta_e(s["lab"], target_lab), s["key"]))
    lo, hi = coverage_box(avail)
    t = np.asarray(target_lab, float)
    outside = bool((t < lo).any() or (t > hi).any())
    return {"available": True, "outside_coverage": outside, "key": best["key"], "parameters": best["parameters"], "lab": best["lab"],
            "confidence": best["confidence"], "expected_delta_e": best["expected_delta_e"], "stability": best["stability"],
            "distance_to_target": color.delta_e(best["lab"], target_lab), "observation_ids": best["observation_ids"]}


def unstable_regions(samples: list[dict], variance_threshold: float | None) -> list[dict]:
    """Parameter sets whose repeats vary more than the configured threshold (REQ-001). Needs a saved threshold."""
    if variance_threshold is None:
        return []
    return [{"key": s["key"], "variance": s["stability"]["variance"], "parameters": s["parameters"]}
            for s in samples if s["stability"]["assessed"] and s["stability"]["variance"] > variance_threshold]
