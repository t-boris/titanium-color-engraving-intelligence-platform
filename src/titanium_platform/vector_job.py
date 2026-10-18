"""Vector LightBurn job from an image (REQ-021, DEC-065): the source image, its vector document, the task and settings of
every region, the predictions and the exported files as one work record.

A job is a plan of mode ``Vector job`` (no new table). The plan row and its data hold the laser, the lens snapshot, the
titanium stock, the threshold, markers and cleaning, the operator's decisions per region and per settings group, the last
assessment and the exported files. The vector document is a JSON file beside the stored image, one file per version: it
keeps the raw outlines and grows with the image, and every edit makes a new version that stays in the plan's history.

Settings are never invented (REQ-021). A settings group (the ``layer_key`` of its regions) takes one validated or
production knowledge entry of the job's laser and lens (DEC-063) measured on the job's titanium stock (REQ-020) whose
LightBurn mode fits the group: a filled outline (fill, colour, filled text, tonal) needs a filling mode, a line or a
centre-line needs Line mode. Colour areas take the nearest such entry by colour, tonal areas by lightness, and are adequate
only when the distance plus the entry's expected error is within the threshold (DEC-030); text and line art take the
nearest fitting entry by colour, because their legibility and line width are not measured (REQ-020). A region without an
adequate entry is weak: hatched in the preview, listed, never exported. The operator deletes it, excludes it ("без рецепта":
kept in the document, left out of the file), substitutes an entry of the eligible palette for its settings group, or sends
its colour to the Experiment Designer as a target.

Each distinct recipe is one LightBurn output layer (DEC-044: shapes with identical settings share a layer). The plan's own
layers start after the cleaning layer (C00, when the job cleans first) and the marker layer, which is always kept free so
that markers can be switched on later: at most 29 recipes, 28 with cleaning (DEC-066).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import cv2
import numpy as np

from . import color, conversion as cv, plans as pl, setup as su, vectorize as vz
from .db import Store, now

MAX_SOURCE_PX = 1200                    # the longer side an image is traced at; a larger one is reduced first
COLOUR_TASKS = ("color", "fill", "tonal")
DOCUMENT_OPS = ("set_task", "set_layer", "delete", "merge", "set_tolerance")
EXPORTED = ("matched", "chosen")
ST_EXPORTED = "Exported"
JOB_NAME = "Векторная работа"


def layer_cap(clean: bool) -> int:
    """Recipes a job can export: LightBurn's 30 output colours less the marker layer and, when it cleans first, the cleaning."""
    return pl.MAX_LAYERS - 1 - int(clean)


def eligible(store: Store, device_id: int, lens_id: int | None, material_id: int, allowed_questioned=()) -> list[dict]:
    """Validated and production recipes of one laser and lens measured on one titanium stock, in every LightBurn mode a
    vector job uses; questioned ones only when allowed for this job (REQ-004)."""
    entries = cv.eligible_palette(store, device_id, lens_id, allowed_questioned=allowed_questioned, modes=cv.FILL_MODES | cv.LINE_MODES)
    return [{**e, "srgb": color.lab_to_srgb8(e["lab"]).tolist()} for e in entries if e["material_id"] == material_id]


def _kind(region: dict) -> str:
    """What a region needs from LightBurn: a line (a centre-line, or an outline engraved as a line) or a fill."""
    return "line" if region["task"] == "line" or not region["loops"] else "fill"


def _fits(entry: dict, kind: str) -> bool:
    return entry["mode"] in (cv.LINE_MODES if kind == "line" else cv.FILL_MODES)


def _distance(task: str, lab, entry_lab) -> float:
    """Tonal areas are judged by lightness (DEC-007), everything else by colour."""
    return abs(float(lab[0]) - float(entry_lab[0])) if task == "tonal" else color.delta_e(lab, entry_lab)


# -- the stored record ------------------------------------------------------------------------------------------
def _job(store: Store, plan_id: int) -> dict:
    plan = pl.get_plan(store, plan_id)
    if plan["status"] == "Deleted":
        raise KeyError(f"plan {plan_id} not found")
    if plan["mode"] != pl.MODE_VECTOR:
        raise cv.ConversionError("this is not a vector job")
    return plan


def _document(plan: dict) -> dict:
    return json.loads(Path(plan["document_path"]).read_text(encoding="utf-8"))


def _write_document(store: Store, document: dict) -> str:
    path = store.data_dir / "files" / f"vector-{uuid.uuid4().hex[:12]}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def _new_version(store: Store, plan: dict, document: dict, op: dict) -> None:
    """The edited document becomes the next version; the earlier ones stay on disk and in the history."""
    plan["document_version"] += 1
    plan["document_path"] = _write_document(store, document)
    plan["history"].append({"version": plan["document_version"], "op": op, "at": now(), "path": plan["document_path"]})


def _source_rgb(image_bytes: bytes) -> np.ndarray:
    img = cv.decode_image_bytes(image_bytes)
    h, w = img.shape[:2]
    scale = MAX_SOURCE_PX / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def start(store: Store, device_id: int, lens_id: int | None, material_id: int, image_bytes: bytes, width_mm: float, strategy: str,
          name: str, *, threshold=None, n_colors: int | None = None, palette: list | None = None, grey_threshold=None,
          tolerance_mm: float = 0.05, min_area_mm2: float = 0.2, markers: bool = False, clean: bool = False) -> int:
    """Trace an image into a vector job of one laser, lens and titanium stock and assess every region against the knowledge."""
    if not (name or "").strip():
        raise cv.ConversionError("give the plan a name")
    setup = su.resolve(store, device_id, lens_id)
    material = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
    if material is None:
        raise su.ValidationError("the selected titanium stock was not found; choose it again")
    thr = cv._threshold(store, device_id, lens_id, threshold)
    cap = layer_cap(clean)
    colours = n_colors if palette is None else len(palette)
    if strategy == "color" and colours is not None and colours > cap:
        raise cv.ConversionError(f"at most {cap} colours: each needs its own LightBurn output layer"
                                 + (" beside the markers and the cleaning" if clean else " beside the markers"))
    document = vz.trace(_source_rgb(image_bytes), width_mm, strategy, colors=palette, n_colors=n_colors, threshold=grey_threshold,
                        tolerance_mm=tolerance_mm, min_area_mm2=min_area_mm2)
    if not document["regions"]:
        raise cv.ConversionError("nothing was traced in the image: there is no region to engrave")
    identifier = pl.new_identifier("TCE-A")      # an artwork job: ingest resolves it from the TCE1 note of the exported file
    size = document["size_mm"]
    path = _write_document(store, document)
    lens = setup["lens"] or {}
    data = {"task": "vector", "strategy": strategy, "image_path": cv._store_image(store, image_bytes), "size_mm": size,
            "trace": {"n_colors": n_colors, "palette": palette, "grey_threshold": grey_threshold, "tolerance_mm": tolerance_mm,
                      "min_area_mm2": min_area_mm2},
            "material_id": material_id, "threshold": thr, "lens": su.lens_snapshot(setup),
            "experiment": {"label": "Job", "test_name": JOB_NAME,
                           "device": {k: setup["device"].get(k) for k in ("id", "name", "manufacturer", "model", "serial", "title")},
                           "lens": {k: lens.get(k) for k in ("id", "name", "focal_length_mm", "field_mm", "expansion")},
                           "material": {k: material[k] for k in ("id", "name", "family", "grade", "batch", "thickness_mm", "surface")}},
            "markers": cv._plan_markers(identifier, markers, size["width"], size["height"], store),
            "marker_layer": pl.marker_layer_settings(store) if markers else None,
            "clean_layer": pl.clean_layer(setup["device"]["passport"]) if clean else None,
            "document_path": path, "document_version": 1,
            "history": [{"version": 1, "op": {"op": "trace", "strategy": strategy}, "at": now(), "path": path}],
            "choices": {}, "excluded": [], "allowed_questioned": [], "targets": [], "exports": [], "regions": [], "layers": [], "weak": []}
    with store.transaction():
        plan_id = cv.save_plan(store, None, name=name.strip(), mode=pl.MODE_VECTOR, status=cv.ST_DRAFT, device_id=device_id, lens_id=lens_id,
                               markers=markers, identifier=identifier, band_count=None, data=data)
        _refresh(store, pl.get_plan(store, plan_id))
    return plan_id


# -- assessment ---------------------------------------------------------------------------------------------------
def assess(store: Store, plan: dict, document: dict) -> dict:
    """Settings and evidence of every region and settings group from the knowledge as it is now; nothing is stored."""
    palette = eligible(store, plan["device_id"], plan["lens_id"], plan["material_id"], plan["allowed_questioned"])
    by_id = {e["id"]: e for e in palette}
    excluded, targets = set(plan["excluded"]), set(plan["targets"])
    members: dict[str, list[dict]] = {}
    for region in document["regions"]:
        members.setdefault(region["layer_key"], []).append(region)
    groups, rows = [], []
    for key, regions in members.items():
        active = [r for r in regions if r["id"] not in excluded]
        lead = max(active, key=lambda r: r["pixels"]) if active else None     # the first of the largest decides the group's need
        kind = _kind(lead) if lead else None
        same = [r for r in active if _kind(r) == kind]
        target = (np.average([r["lab"] for r in same], axis=0, weights=[max(r["pixels"], 1) for r in same]).tolist() if same else None)
        fitting = sorted((e for e in palette if lead and _fits(e, kind)),
                         key=lambda e: (_distance(lead["task"], target, e["lab"]), e["id"]))
        choice = plan["choices"].get(key)
        chosen = choice is not None and choice in {e["id"] for e in fitting}
        entry = by_id[choice] if chosen else (fitting[0] if fitting else None)
        groups.append({"key": key, "kind": kind, "knowledge_id": entry["id"] if entry else None, "chosen": chosen,
                       "choice_unavailable": choice is not None and not chosen, "target_lab": target,
                       "regions": [r["id"] for r in regions],
                       "candidates": [{"knowledge_id": e["id"], "distance": _distance(lead["task"], target, e["lab"])} for e in fitting]})
        rows += [_region(r, entry, chosen, kind, plan["threshold"], excluded, targets) for r in regions]
    first = 1 + int(plan.get("clean_layer") is not None)          # C00 cleans, the next colour is kept for the markers
    layers: dict[int, dict] = {}
    for row in rows:
        if row["status"] in EXPORTED:
            e = by_id[row["knowledge_id"]]
            layer = layers.setdefault(e["id"], {"index": first + len(layers), "name": f"K{e['id']}", "parameters": e["parameters"],
                                                "regions": [], "region_ids": [], "layer_keys": [], "prediction": cv.prediction_of(e),
                                                "knowledge_id": e["id"], "stage": e["stage"], "questioned": e["questioned"],
                                                "mode": e["mode"], "cut_type": e["mode"] or "Scan"})
            layer["region_ids"].append(row["id"])
            if row["layer_key"] not in layer["layer_keys"]:
                layer["layer_keys"].append(row["layer_key"])
    return {"palette": palette, "groups": groups, "regions": rows, "layers": list(layers.values()),
            "weak": [row["id"] for row in rows if row["status"] == "weak"]}


def _region(r: dict, entry: dict | None, chosen: bool, kind: str | None, threshold: float, excluded: set, targets: set) -> dict:
    row = {"id": r["id"], "task": r["task"], "layer_key": r["layer_key"], "srgb": r["srgb"], "lab": r["lab"], "pixels": r["pixels"],
           "outline": "closed" if r["loops"] else "centre-line", "kind": _kind(r),
           "area_mm2": round(vz.region_area_mm2(r), 3) if r["loops"] else None, "status": "weak", "knowledge_id": None, "mode": None,
           "parameters": None, "prediction": None, "stage": None, "questioned": False, "distance": None, "match_error": None,
           "note": None, "target_sent": r["id"] in targets}
    if r["id"] in excluded:
        row["status"] = "excluded"
        return row
    if entry is None:
        row["note"] = ("no validated or production recipe of this laser, lens and titanium stock engraves a line (LightBurn Line mode)"
                       if row["kind"] == "line" else "no validated or production recipe of this laser, lens and titanium stock fills an area")
        return row
    if row["kind"] != kind:
        row["note"] = "its task needs another LightBurn mode than the rest of its settings group; give it a settings group of its own"
        return row
    distance = _distance(r["task"], r["lab"], entry["lab"])
    row.update(knowledge_id=entry["id"], mode=entry["mode"], parameters=entry["parameters"], prediction=cv.prediction_of(entry),
               stage=entry["stage"], questioned=entry["questioned"], distance=distance, match_error=distance + entry["expected_delta_e"])
    if chosen:
        row["status"] = "chosen"
    elif r["task"] in COLOUR_TASKS and row["match_error"] > threshold:
        row["note"] = (f"the nearest recipe misses the {'lightness' if r['task'] == 'tonal' else 'colour'} by {distance:.1f} plus its "
                       f"expected error {entry['expected_delta_e']:.1f}, above the threshold {threshold:g}")
    else:
        row["status"] = "matched"
    return row


def check_exportable(assessment: dict, cap: int) -> None:
    """Export is refused while a region lacks evidence or the recipes outnumber LightBurn's output layers (REQ-012, REQ-021)."""
    weak = assessment["weak"]
    if weak:
        raise cv.ConversionError(f"{len(weak)} region(s) have no adequate evidence: delete or exclude each, or choose settings for its group, before export")
    if not assessment["layers"]:
        raise cv.ConversionError("every region is excluded: there is nothing to engrave")
    if len(assessment["layers"]) > cap:
        raise cv.ConversionError(f"{len(assessment['layers'])} different recipes need more LightBurn layers than the {cap} available")


def _blocker(assessment: dict, plan: dict) -> str | None:
    try:
        check_exportable(assessment, layer_cap(plan.get("clean_layer") is not None))
    except cv.ConversionError as exc:
        return str(exc)
    return None


def _refresh(store: Store, plan: dict) -> dict:
    """Assess the current document, store the result in the plan and set its status: ready when it can be exported."""
    a = assess(store, plan, _document(plan))
    plan["regions"], plan["layers"], plan["weak"] = a["regions"], a["layers"], a["weak"]
    cv._persist(store, plan, cv.ST_READY if _blocker(a, plan) is None else cv.ST_DRAFT, plan["markers_enabled"])
    return a


# -- review ---------------------------------------------------------------------------------------------------------
def _region_ids(document: dict) -> set[str]:
    return {r["id"] for r in document["regions"]}


def edit(store: Store, plan_id: int, op: dict) -> None:
    """One operation of the review, recorded in the plan's history.

    Document edits (``set_task``, ``set_layer``, ``delete``, ``merge``, ``set_tolerance``, see :func:`vectorize.edit`) and
    ``{"op": "revert", "version"}`` make a new document version. The others decide about evidence and keep the document:
    ``{"op": "set_settings", "group", "knowledge_id"}`` (an eligible recipe for a settings group; null returns it to the
    nearest), ``{"op": "exclude" | "include", "region"}``, ``{"op": "set_threshold", "threshold"}``,
    ``{"op": "allow_questioned", "knowledge_ids"}`` (this job only) and ``{"op": "to_designer", "region"}``.
    """
    if not isinstance(op, dict):
        raise cv.ConversionError("an edit must name its operation")
    plan, kind = _job(store, plan_id), op.get("op")
    document = _document(plan)
    with store.transaction():
        if kind in DOCUMENT_OPS:
            _new_version(store, plan, vz.edit(document, op), op)
        elif kind == "revert":
            entry = next((h for h in plan["history"] if h.get("path") and h["version"] == op.get("version")), None)
            if entry is None:
                raise cv.ConversionError("there is no such version of the vector document")
            _new_version(store, plan, json.loads(Path(entry["path"]).read_text(encoding="utf-8")), {"op": "revert", "version": entry["version"]})
        else:
            _decide(store, plan, document, kind, op)
            plan["history"].append({"version": plan["document_version"], "op": op, "at": now()})
        _refresh(store, plan)


def _decide(store: Store, plan: dict, document: dict, kind, op: dict) -> None:
    if kind == "set_settings":
        key = op.get("group")
        if key not in {r["layer_key"] for r in document["regions"]}:
            raise cv.ConversionError(f"there is no settings group {key!r}")
        if op.get("knowledge_id") is None:
            plan["choices"].pop(key, None)
            return
        group = next(g for g in assess(store, plan, document)["groups"] if g["key"] == key)
        if op["knowledge_id"] not in {c["knowledge_id"] for c in group["candidates"]}:
            raise cv.ConversionError("the settings must be a validated or production recipe of this laser, lens and titanium stock "
                                     "whose LightBurn mode fits the settings group")
        plan["choices"][key] = int(op["knowledge_id"])
    elif kind in ("exclude", "include"):
        region = op.get("region")
        if region not in _region_ids(document):
            raise cv.ConversionError(f"there is no region {region!r}")
        plan["excluded"] = sorted(set(plan["excluded"]) - {region} | ({region} if kind == "exclude" else set()))
    elif kind == "set_threshold":
        plan["threshold"] = cv._threshold(store, plan["device_id"], plan["lens_id"], op.get("threshold"))
    elif kind == "allow_questioned":
        try:
            plan["allowed_questioned"] = sorted({int(x) for x in op.get("knowledge_ids") or []})
        except (TypeError, ValueError):
            raise cv.ConversionError("the allowed entries must be a list of whole numbers") from None
    elif kind == "to_designer":
        region = next((r for r in document["regions"] if r["id"] == op.get("region")), None)
        if region is None:
            raise cv.ConversionError(f"there is no region {op.get('region')!r}")
        if _kind(region) == "line":
            raise cv.ConversionError("only a colour can be a target of the Experiment Designer; a line needs a line test plate")
        store.execute("INSERT OR IGNORE INTO target_color(device_id,lens_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,?,?,?)",
                      (plan["device_id"], plan["lens_id"], json.dumps(region["lab"]), plan["id"], f"region:{region['id']}", now()))
        plan["targets"] = sorted(set(plan["targets"]) | {region["id"]})
    else:
        raise cv.ConversionError(f"unknown edit operation {kind!r}")


# -- reading and export -------------------------------------------------------------------------------------------
def view(store: Store, plan_id: int) -> dict:
    """The job as the review screen shows it: the assessment from the current knowledge, the SVG preview with the weak
    regions hatched, the history and the exported files (no server paths)."""
    plan = _job(store, plan_id)
    document = _document(plan)
    a = assess(store, plan, document)
    out = {k: v for k, v in plan.items() if k not in ("document_path", "history", "exports")}
    out.update(regions=a["regions"], groups=a["groups"], layers=a["layers"], weak=a["weak"], palette=a["palette"],
               export_blocked=_blocker(a, plan), layer_cap=layer_cap(plan.get("clean_layer") is not None),
               svg=vz.to_svg(document, weak=frozenset(a["weak"])),
               document={k: document[k] for k in ("strategy", "size_mm", "px_mm", "image_px", "tolerance_mm", "min_area_mm2", "threshold")}
               | {"version": plan["document_version"]},
               history=[{k: h[k] for k in ("version", "op", "at")} for h in plan["history"]],
               exports=[{k: e[k] for k in ("number", "name", "at", "document_version", "layers", "regions")} for e in plan["exports"]])
    return out


def export(store: Store, plan_id: int) -> tuple[str, bytes]:
    """The standard LightBurn file of the job's current version, kept in the plan so that the photograph of the engraving
    links back to it (the ``TCE1:`` note names the plan identifier)."""
    plan = _job(store, plan_id)
    document = _document(plan)
    a = assess(store, plan, document)
    check_exportable(a, layer_cap(plan.get("clean_layer") is not None))
    keep = {r["id"] for r in a["regions"] if r["status"] in EXPORTED}
    plan["regions"], plan["layers"], plan["weak"] = a["regions"], a["layers"], a["weak"]
    data = pl.export_lbrn2({**plan, "vector_document": {**document, "regions": [r for r in document["regions"] if r["id"] in keep]}})
    path = store.data_dir / "files" / f"vector-export-{uuid.uuid4().hex[:12]}.lbrn2"
    path.write_bytes(data)
    plan["exports"].append({"number": len(plan["exports"]) + 1, "name": plan["name"] + ".lbrn2", "path": str(path), "at": now(),
                            "document_version": plan["document_version"], "layers": len(a["layers"]), "regions": len(keep)})
    cv._persist(store, plan, ST_EXPORTED, plan["markers_enabled"])
    return plan["name"], data


def stored_export(store: Store, plan_id: int, number: int) -> tuple[str, bytes]:
    plan = _job(store, plan_id)
    entry = next((e for e in plan["exports"] if e["number"] == number), None)
    if entry is None or not Path(entry["path"]).is_file():
        raise KeyError(f"exported file {number} of plan {plan_id} not found")
    return entry["name"], Path(entry["path"]).read_bytes()
