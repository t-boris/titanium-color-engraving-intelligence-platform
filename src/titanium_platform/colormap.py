"""One general colour map (REQ-029, DEC-056): every colour measured in every kept experiment, with the settings that gave it
and where it came from, so that a wanted colour can be looked up without going through the experiments.

Colours measured against a reference chart are absolute (CIE Lab). Colours measured without one are relative to their camera and
cannot be compared between photographs, so each is expressed against the cleaned titanium of the *same* photograph (the cleaning
witness): the ratio of the two in linear light does not depend on the exposure, and multiplied with the nominal clean titanium it
gives the colour shown. They are marked approximate. A colour with no witness has no
reference: it is still on the map, as it was photographed and flagged ``referenced: false``, but it takes no part in the search
unless asked, because its distance to the other colours would mean nothing (operator, 2026-10-16).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import color, experiments, ingest, lightburn as lb, model
from .db import Store

DEFAULT_CLEAN = [68.0, 0.0, 2.0]          # cleaned titanium when no photograph with a chart has measured it yet
SERVICE = ("registration, QR and engraved labels",)


def _rows(store: Store):
    return store.query(
        "SELECT o.id, o.pair_id, o.layer_index, o.lab_json, o.parameters_json, o.model_eligible, o.alignment_method, o.evidence_json, "
        "p.plan_id, p.engraving_id, p.engraving_title, p.photo_name, p.lightburn_name, p.accepted_at, p.created_at AS pair_created, "
        "p.hardware_json, p.context_json AS pair_context, p.lightburn_path, pl.status AS plan_status "
        "FROM observation o JOIN pair p ON p.id=o.pair_id LEFT JOIN plan pl ON pl.id=p.plan_id "
        "WHERE p.status!='Deleted' ORDER BY o.pair_id, o.layer_index")


@lru_cache(maxsize=64)
def _cleaning_layer(path: str, stamp: int) -> int | None:
    """The cleaning layer of a finished work, found again from its stored LightBurn file (DEC-056); None if there is none."""
    from .ingest import _finished_work_cleaning_layer     # noqa: F811 (same module, imported at call time to keep the cache simple)
    try:
        return _finished_work_cleaning_layer(lb.parse_file(path))
    except (OSError, lb.LightBurnError):
        return None


def _pair_info(row) -> dict:
    hardware, context = json.loads(row["hardware_json"] or "{}"), json.loads(row["pair_context"] or "{}")
    laser = (hardware.get("device") or {}).get("name")
    lens = (hardware.get("lens") or {}).get("name")
    material = " · ".join(x for x in (context.get("titanium_name"), context.get("titanium_grade")) if x) or None
    key = experiments.plan_key(row["plan_id"]) if row["plan_id"] and row["plan_status"] not in (None, "Deleted") else experiments.engraving_key(row["engraving_id"])
    return {"experiment": key, "title": row["engraving_title"] or row["lightburn_name"].rsplit(".", 1)[0], "photo": row["photo_name"],
            "date": row["accepted_at"] or row["pair_created"], "laser": laser, "lens": lens,
            "setup": " · ".join(x for x in (laser, lens) if x) or "лазер не указан", "material": material}


def _against_clean(lab, clean, nominal) -> list[float]:
    """The colour as it would look on nominal clean titanium: the ratio to this photograph's clean surface, per channel in linear light."""
    ratio = np.clip(color.lab_to_linear_rgb(np.asarray(lab, float)), 0, 1) / np.maximum(color.lab_to_linear_rgb(np.asarray(clean, float)), 1e-4)
    shown = np.clip(color.lab_to_linear_rgb(np.asarray(nominal, float)) * ratio, 0, 1)
    return [float(v) for v in color.linear_rgb_to_lab(shown)]


def _kind(evidence: dict, eligible: int) -> str:
    mode = (evidence.get("color_measurement") or {}).get("mode")
    return "calibrated" if mode == "reference_chart_corrected" or (mode is None and eligible) else "relative"


def collect(store: Store, include_unreferenced: bool = True, setup: str | None = None, material: str | None = None,
            measurement: str | None = None) -> dict:
    """Every colour of the map. Filters narrow the points; the options and counts describe everything that exists."""
    rows = list(_rows(store))
    witness: dict[int, dict] = {}
    for row in rows:
        evidence = json.loads(row["evidence_json"] or "{}")
        if evidence.get("role") == "pre-test cleaning witness" or row["layer_index"] == -1:
            witness[row["pair_id"]] = {"lab": json.loads(row["lab_json"]), "kind": _kind(evidence, row["model_eligible"])}
    # Works accepted before the cleaning layer was recognised have no witness observation: find the layer again in the stored file.
    derived: dict[int, int] = {}
    for row in rows:
        if row["pair_id"] in witness or row["plan_id"] or row["pair_id"] in derived:
            continue
        try:
            stamp = Path(row["lightburn_path"]).stat().st_mtime_ns
        except OSError:
            continue
        layer = _cleaning_layer(row["lightburn_path"], stamp)
        if layer is not None:
            derived[row["pair_id"]] = layer
    for row in rows:
        if derived.get(row["pair_id"]) == row["layer_index"] and row["pair_id"] not in witness:
            evidence = json.loads(row["evidence_json"] or "{}")
            witness[row["pair_id"]] = {"lab": json.loads(row["lab_json"]), "kind": _kind(evidence, row["model_eligible"]), "layer": row["layer_index"]}
    calibrated_clean = [w["lab"] for w in witness.values() if w["kind"] == "calibrated"]
    nominal = [float(v) for v in np.median(np.array(calibrated_clean), axis=0)] if calibrated_clean else list(DEFAULT_CLEAN)

    points, setups, materials = [], set(), set()
    for row in rows:
        evidence = json.loads(row["evidence_json"] or "{}")
        role = evidence.get("role")
        if role in SERVICE or role == "pre-test cleaning witness" or row["layer_index"] == -1 or derived.get(row["pair_id"]) == row["layer_index"]:
            continue
        info = _pair_info(row)
        lab = json.loads(row["lab_json"])
        kind = _kind(evidence, row["model_eligible"])
        ref = witness.get(row["pair_id"])
        delta = [lab[i] - ref["lab"][i] for i in range(3)] if ref else None
        if kind == "calibrated":
            display, approximate, referenced = lab, False, True
        elif delta is not None:
            display, approximate, referenced = _against_clean(lab, ref["lab"], nominal), True, True
        else:
            display, approximate, referenced = lab, True, False
        setups.add(info["setup"])
        if info["material"]:
            materials.add(info["material"])
        params = json.loads(row["parameters_json"] or "{}")
        points.append({"id": row["id"], "pair_id": row["pair_id"], "layer_index": row["layer_index"], "layer_name": evidence.get("layer_name"),
                       "measurement": kind, "approximate": approximate, "referenced": referenced, "lab": lab, "delta": delta, "display_lab": display,
                       "parameters": {k: params.get(k) for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes",
                                                                  "layer_type", "global_passes", "bidirectional", "cross_hatch", "scan_angle")},
                       "group": f"{model.parameters_key(params)}|{info['setup']}|{info['material']}", **info})
    # A grayscale-mode image is a continuum of recipes: the grey level sets the power and the power sets the colour. Each step of
    # its tonal profile is a colour with the settings of that power (DEC-056).
    first_row = {}
    for row in rows:
        first_row.setdefault(row["pair_id"], row)
    for pair_id, row in first_row.items():
        info = _pair_info(row)
        check = ingest.get_pair(store, pair_id).get("check") or {}
        kind = "calibrated" if (check.get("color_measurement") or {}).get("mode") == "reference_chart_corrected" else "relative"
        ref = witness.get(pair_id)
        for rep in check.get("layers", []):
            tonal = rep.get("tonal")
            if not tonal or tonal.get("evidence") != "clear" or not tonal.get("power_range"):
                continue
            for step in tonal["bins"]:
                if "power_pct" not in step:
                    continue
                lab = [step["L"], step["a"], step["b"]]
                if kind == "calibrated":
                    display, approximate, referenced = lab, False, True
                elif ref:
                    display, approximate, referenced = _against_clean(lab, ref["lab"], nominal), True, True
                else:
                    display, approximate, referenced = lab, True, False
                setups.add(info["setup"])
                if info["material"]:
                    materials.add(info["material"])
                params = {"power": step["power_pct"], "frequency": rep.get("frequency_khz"), "speed": rep.get("speed"),
                          "pulse_width": rep.get("pulse_width"), "line_interval": rep.get("line_interval"), "passes": rep.get("passes"),
                          "layer_type": "Image", "grayscale": True}
                points.append({"id": f"tonal-{pair_id}-{rep['index']}-{step['gray']}", "pair_id": pair_id, "layer_index": rep["index"],
                               "layer_name": f"{rep.get('name')} · серый {step['gray']:.2f}", "measurement": kind, "approximate": approximate,
                               "referenced": referenced, "lab": lab, "delta": None, "display_lab": display, "parameters": params, "source": "tonal",
                               "group": f"{model.parameters_key(params)}|tonal|{pair_id}|{rep['index']}|{info['setup']}|{info['material']}", **info})
    shown = [p for p in points if (setup is None or p["setup"] == setup) and (material is None or p["material"] == material)
             and (measurement is None or p["measurement"] == measurement)]
    unreferenced = sum(not p["referenced"] for p in shown)
    if not include_unreferenced:
        shown = [p for p in shown if p["referenced"]]
    return {"points": shown, "nominal_clean": {"lab": nominal, "source": "chart" if calibrated_clean else "default"},
            "options": {"setups": sorted(setups), "materials": sorted(materials)},
            "counts": {"calibrated": sum(p["measurement"] == "calibrated" for p in shown),
                       "relative": sum(p["measurement"] == "relative" for p in shown), "unreferenced": unreferenced}}


def search(store: Store, lab: list[float], limit: int = 12, include_unreferenced: bool = False, **filters) -> dict:
    """The recipes whose colour is nearest to ``lab``: one entry per recipe, with how often it came out and where.
    Colours without a clean reference are left out unless asked for; their number is returned."""
    data = collect(store, include_unreferenced=include_unreferenced, **filters)
    best: dict[str, dict] = {}
    for point in data["points"]:
        distance = color.delta_e(lab, point["display_lab"])
        entry = best.setdefault(point["group"], {"best": point, "distance": distance, "repeats": 0, "experiments": []})
        entry["repeats"] += 1
        if point["experiment"] not in entry["experiments"]:
            entry["experiments"].append(point["experiment"])
        if distance < entry["distance"]:
            entry["best"], entry["distance"] = point, distance
    ranked = sorted(best.values(), key=lambda e: e["distance"])[:limit]
    return {"target": lab, "matches": [{"distance": round(float(e["distance"]), 2), "repeats": e["repeats"], "experiments": e["experiments"], **e["best"]} for e in ranked],
            "nominal_clean": data["nominal_clean"], "counts": data["counts"]}
