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

A photograph (strategy ``photo``, REQ-042) takes another path, described where it starts below: it is split into gapless
colour regions (:mod:`segment`) and coloured with every measured colour of the job's laser, lens and titanium
(:mod:`palette`, DEC-073); traced jobs keep the rules above.
"""
from __future__ import annotations

import copy
import json
import math
import uuid
from pathlib import Path

import cv2
import numpy as np

from . import color, colormap, conversion as cv, engraving_time, faces, palette, plans as pl, segment as seg, setup as su, tasks, vectorize as vz
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
    vector job uses, of every task (each entry names its own); questioned ones only when allowed for this job (REQ-004)."""
    entries = cv.eligible_palette(store, device_id, lens_id, allowed_questioned=allowed_questioned, modes=cv.FILL_MODES | cv.LINE_MODES,
                                  kinds=None)
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
          tolerance_mm: float = 0.05, min_area_mm2: float = 0.2, markers: bool = False, clean: bool = False, task: str | None = None,
          goals: dict | None = None) -> int:
    """Trace an image into a vector job of one laser, lens and titanium stock and assess every region against the knowledge.
    The job records its main engraving task (REQ-020): the operator's, else the one its tracing strategy serves; each region
    keeps its own."""
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
    engraving_task = tasks.chosen_or_default(task, tasks.VECTOR_STRATEGY_TASK[strategy], goals)
    identifier = pl.new_identifier("TCE-A")      # an artwork job: ingest resolves it from the TCE1 note of the exported file
    size = document["size_mm"]
    path = _write_document(store, document)
    lens = setup["lens"] or {}
    data = {"task": "vector", "engraving_task": engraving_task, "strategy": strategy, "image_path": cv._store_image(store, image_bytes), "size_mm": size,
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
            layer.setdefault("region_tasks", [])
            if row["task"] not in layer["region_tasks"]:
                layer["region_tasks"].append(row["task"])
    for layer in layers.values():           # the task a photograph of this layer is measured for (REQ-020); None when mixed
        layer["task"] = tasks.layer_task_of_regions(layer["region_tasks"])
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
    if is_photo(plan):
        raise cv.ConversionError("a photograph split into colour regions is changed by splitting it again and by its colouring")
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
    regions hatched, the history and the exported files (no server paths). A photograph job: :func:`photo_view`."""
    plan = _job(store, plan_id)
    if is_photo(plan):
        return photo_view(store, plan)
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
    if is_photo(plan):
        return _photo_export(store, plan)
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


# ======================================================================================================================
# A photograph split into gapless colour regions and coloured with measured titanium colours (REQ-042, REQ-043,
# DEC-073..DEC-077)
# ======================================================================================================================
# The job keeps the split's settings (``split``), the important areas found in its picture once (``detected``), the
# segment document (one JSON file per version, as above), the current colouring with the operator's choices, every
# automatic variant and the colourings to go back to (``undo``). Its palette is every measured colour of its laser, lens
# and titanium (palette.vector_palette, DEC-073); cleaning is always its first layer, so it holds at most 29 recipes, 28
# with registration markers.
#
# A colouring: ``assignment`` (source colour index -> palette entry) and ``how`` from the last automatic mode, ``groups``
# (a colour the operator chose by hand or whose proposed substitute he accepted; every automatic mode keeps them),
# ``regions`` (a region given its own colour), ``excluded_colours`` and ``excluded_regions`` (left out of the file).
# A source colour is unresolved while no colour the automatic modes may use lies within the delta E tolerance and the
# operator has neither accepted the proposed one (the current automatic choice), chosen another nor excluded it; the
# file is refused while any region of such a colour remains (REQ-042).
PHOTO = "photo"
DETAIL = {"coarse": (70, 1 / 1500), "medium": (100, 1 / 3000), "fine": (150, 1 / 7500)}
"""Levels of detail of a split: the coarse superpixels along the picture's longer side and the least region as a share
of the picture's area. On the operator's 150 mm portrait (12 colours) they gave about 300, 450 and 900 regions; the
medium level keeps flat areas calm while faces, eyes and lips keep their finer regions."""
DEFAULT_DETAIL = "medium"
COLOURING_OPS = ("assign", "set_colour", "set_region", "accept", "accept_all", "exclude_colour", "include_colour", "exclude_region",
                 "include_region", "restore", "undo", "settings")
UNDO_DEPTH = 50
RESOLVED = ("automatic", "hand", "accepted", "excluded")


def photo_cap(markers: bool) -> int:
    """Colours and recipes of a photograph job: LightBurn's 30 output colours less the cleaning, less the markers (DEC-073)."""
    return pl.MAX_LAYERS - 1 - int(markers)


def _split_settings(params: dict, markers: bool, detected: int) -> dict:
    """The split settings checked: colours within the job's layers, a level of detail, a smoothing in mm, faces on or off,
    areas marked by hand (in pixels of the working picture) and detected areas removed (by their number)."""
    cap = photo_cap(markers)
    n = params.get("n_colors")
    if isinstance(n, bool) or not isinstance(n, int) or not seg.MIN_COLORS <= n <= cap:
        raise cv.ConversionError(f"choose from {seg.MIN_COLORS} to {cap} colours: the cleaning takes one LightBurn layer"
                                 + (" and the markers another" if markers else ""))
    detail = params.get("detail") or DEFAULT_DETAIL
    if detail not in DETAIL:
        raise cv.ConversionError("the level of detail must be coarse, medium or fine")
    try:
        smoothing = float(params.get("tolerance_mm", seg.TOLERANCE_MM))
    except (TypeError, ValueError):
        smoothing = -1.0
    if not np.isfinite(smoothing) or smoothing < 0:
        raise cv.ConversionError("the smoothing must be a non-negative number of millimetres")
    manual = []
    for area in params.get("manual") or []:
        try:
            manual.append(faces.check_area({**area, "kind": "manual", "source": "manual", "score": None}))
        except (TypeError, ValueError):
            raise cv.ConversionError("an important area must be an ellipse or a polygon of finite numbers in picture pixels") from None
    removed = params.get("removed") or []
    if not isinstance(removed, list) or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < detected for i in removed):
        raise cv.ConversionError("a removed area must be one of the areas found in the picture")
    return {"n_colors": n, "detail": detail, "tolerance_mm": smoothing, "faces": bool(params.get("faces", True)), "manual": manual,
            "removed": sorted(set(removed))}


def _segment(plan: dict, picture: np.ndarray) -> dict:
    """Split the job's picture with its settings; the faces found once in it are used unless removed or switched off."""
    s, found = plan["split"], plan["detected"]
    across, share = DETAIL[s["detail"]]
    size = plan["size_mm"]
    areas = [a for i, a in enumerate(found["areas"]) if i not in s["removed"]] if s["faces"] else []
    document = seg.segment(picture, size["width"], s["n_colors"], important=areas + s["manual"], use_faces=False,
                           min_area_mm2=share * size["width"] * size["height"], tolerance_mm=s["tolerance_mm"], superpixels=across)
    document["faces"] = {"searched": s["faces"], "found": found["faces"] if s["faces"] else 0, "error": found["error"] if s["faces"] else None}
    return document


def start_photo(store: Store, device_id: int, lens_id: int | None, material_id: int, image_bytes: bytes, width_mm: float, name: str, *,
                threshold=None, n_colors: int = 12, detail: str = DEFAULT_DETAIL, tolerance_mm: float = seg.TOLERANCE_MM,
                use_faces: bool = True, markers: bool = False, max_time: float | None = None, include_as_shot: bool = False,
                task: str | None = None, goals: dict | None = None) -> int:
    """Split a photograph into colour regions for one laser, lens and titanium stock and colour it automatically: the
    fastest measured colour within the delta E tolerance (DEC-075), else the nearest as a proposal."""
    if not (name or "").strip():
        raise cv.ConversionError("give the plan a name")
    setup = su.resolve(store, device_id, lens_id)
    material = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
    if material is None:
        raise su.ValidationError("the selected titanium stock was not found; choose it again")
    thr = cv._threshold(store, device_id, lens_id, threshold)
    try:
        width = float(width_mm)
    except (TypeError, ValueError):
        width = math.nan
    if not math.isfinite(width) or width <= 0:
        raise cv.ConversionError("the work width must be a positive number of millimetres")
    picture = _source_rgb(image_bytes)
    split = _split_settings({"n_colors": n_colors, "detail": detail, "tolerance_mm": tolerance_mm, "faces": use_faces}, markers, 0)
    search = faces.important_areas(picture)
    identifier = pl.new_identifier("TCE-A")
    h, w = picture.shape[:2]
    size = {"width": width, "height": h * width / w}
    lens = setup["lens"] or {}
    plan = {"task": "vector", "engraving_task": tasks.chosen_or_default(task, tasks.VECTOR_STRATEGY_TASK[PHOTO], goals), "strategy": PHOTO,
            "image_path": cv._store_image(store, image_bytes), "size_mm": size, "material_id": material_id, "threshold": thr,
            "lens": su.lens_snapshot(setup), "split": split, "detected": {"areas": search.areas, "faces": search.faces, "error": search.error},
            "colour_settings": {"max_time": colormap.time_limit(max_time), "include_as_shot": bool(include_as_shot)},
            "experiment": {"label": "Job", "test_name": JOB_NAME,
                           "device": {k: setup["device"].get(k) for k in ("id", "name", "manufacturer", "model", "serial", "title")},
                           "lens": {k: lens.get(k) for k in ("id", "name", "focal_length_mm", "field_mm", "expansion")},
                           "material": {k: material[k] for k in ("id", "name", "family", "grade", "batch", "thickness_mm", "surface")}},
            "markers": cv._plan_markers(identifier, markers, size["width"], size["height"], store),
            "marker_layer": pl.marker_layer_settings(store) if markers else None, "clean_layer": pl.clean_layer(setup["device"]["passport"]),
            "colouring": None, "variants": [], "undo": [], "exports": [], "regions": [], "layers": [], "weak": [], "unresolved": None}
    document = _segment(plan, picture)
    plan["document_path"], plan["document_version"] = _write_document(store, document), 1
    plan["history"] = [{"version": 1, "op": {"op": "split", **_split_op(split)}, "at": now(), "path": plan["document_path"]}]
    entries = _palette(store, {"device_id": device_id, "lens_id": lens_id, "material_id": material_id})
    plan["colouring"] = _automatic(plan, document, entries, "closest", 0, _empty_colouring())
    _add_variant(plan, document, entries)
    with store.transaction():
        plan_id = cv.save_plan(store, None, name=name.strip(), mode=pl.MODE_VECTOR, status=cv.ST_DRAFT, device_id=device_id, lens_id=lens_id,
                               markers=markers, identifier=identifier, band_count=None, data=plan)
        _photo_refresh(store, pl.get_plan(store, plan_id), document, entries)
    return plan_id


def _split_op(split: dict) -> dict:
    """What the history records of a split: its settings and how many areas were marked or removed."""
    return {**{k: split[k] for k in ("n_colors", "detail", "tolerance_mm", "faces")}, "manual": len(split["manual"]), "removed": len(split["removed"])}


def is_photo(plan: dict) -> bool:
    return plan.get("strategy") == PHOTO


def _photo_job(store: Store, plan_id: int) -> dict:
    plan = _job(store, plan_id)
    if not is_photo(plan):
        raise cv.ConversionError("only a photograph split into colour regions is split and coloured this way")
    return plan


def resplit(store: Store, plan_id: int, params: dict) -> None:
    """Split the picture again with new settings and important areas: a new document version, coloured anew (closest);
    the variants and the colourings of the earlier split are left behind with it."""
    plan = _photo_job(store, plan_id)
    if not isinstance(params, dict):
        raise cv.ConversionError("the split settings must be an object")
    plan["split"] = _split_settings(params, plan["markers_enabled"], len(plan["detected"]["areas"]))
    document = _segment(plan, _source_rgb(Path(plan["image_path"]).read_bytes()))
    entries = _palette(store, plan)
    with store.transaction():
        _new_version(store, plan, document, {"op": "split", **_split_op(plan["split"])})
        plan["colouring"], plan["variants"], plan["undo"] = _automatic(plan, document, entries, "closest", 0, _empty_colouring()), [], []
        _add_variant(plan, document, entries)
        _photo_refresh(store, plan, document, entries)


# -- colouring -------------------------------------------------------------------------------------------------------------
def _palette(store: Store, plan: dict) -> list[dict]:
    """Every measured colour of the job's laser, lens and titanium stock that fills an area (DEC-073)."""
    return palette.vector_palette(store, plan["device_id"], plan["lens_id"], plan["material_id"])["entries"]


def _empty_colouring() -> dict:
    return {"mode": None, "seed": 0, "variant": None, "assignment": {}, "how": {}, "groups": {}, "regions": {}, "excluded_colours": [],
            "excluded_regions": []}


def _sources(document: dict) -> list[dict]:
    return [{"index": p["index"], "lab": p["lab"], "pixels": p["pixels"]} for p in document["palette"]]


def _automatic(plan: dict, document: dict, entries: list[dict], mode: str, seed: int, colouring: dict) -> dict:
    """The colouring after an automatic mode: every colour without the operator's own choice gets the mode's entry
    (palette.assign), the operator's choices of colours and regions stay."""
    by_id = {e["id"]: e for e in entries}
    out = {**copy.deepcopy(colouring), "mode": mode, "seed": seed, "assignment": {}, "how": {}}
    if not entries:                          # nothing measured on this titanium: every colour stays without a titanium colour
        return out
    settings = plan["colour_settings"]
    keep = {i: g["entry_id"] for i, g in colouring["groups"].items() if g["entry_id"] in by_id}
    result = palette.assign(_sources(document), entries, mode, tolerance_de=plan["threshold"], seed=seed, max_time=settings["max_time"],
                            keep=keep, include_as_shot=settings["include_as_shot"])
    out["assignment"] = {str(c["index"]): c["entry_id"] for c in result["colours"]}
    out["how"] = {str(c["index"]): c["how"] for c in result["colours"]}
    return out


def _add_variant(plan: dict, document: dict, entries: list[dict]) -> None:
    """The current colouring, just made by an automatic mode, becomes a numbered variant that can be restored."""
    number = 1 + max((v["number"] for v in plan["variants"]), default=0)
    plan["colouring"]["variant"] = number
    state = _state(plan, document, entries)
    plan["variants"].append({"number": number, "mode": plan["colouring"]["mode"], "seed": plan["colouring"]["seed"], "at": now(),
                             "colouring": copy.deepcopy(plan["colouring"]), "totals": state["totals"]})


def _state(plan: dict, document: dict, entries: list[dict]) -> dict:
    """Every source colour and region with its titanium colour and status, the unresolved ones, the layers of the file
    and the totals of the current colouring."""
    by_id = {e["id"]: e for e in entries}
    colouring, settings, tolerance = plan["colouring"], plan["colour_settings"], plan["threshold"]
    candidates = [e for e in entries if palette.automatic(e, settings["max_time"], settings["include_as_shot"])]
    excluded_colours, excluded_regions = set(colouring["excluded_colours"]), set(colouring["excluded_regions"])
    colours = []
    for source in document["palette"]:
        key = str(source["index"])
        group = colouring["groups"].get(key)
        entry_id = group["entry_id"] if group else colouring["assignment"].get(key)
        nearest = min((color.delta_e(source["lab"], e["lab"]) for e in candidates), default=None)
        if source["index"] in excluded_colours:
            status = "excluded"
        elif entry_id not in by_id:
            status = "missing"
        elif group:
            status = group["by"]
        else:
            status = "automatic" if nearest is not None and nearest <= tolerance else "proposed"
        entry = by_id.get(entry_id)
        colours.append({"index": source["index"], "lab": source["lab"], "srgb": source["srgb"], "pixels": source["pixels"], "status": status,
                        "entry_id": entry_id if entry else None, "how": "hand" if group else colouring["how"].get(key),
                        "delta_e": None if entry is None else round(color.delta_e(source["lab"], entry["lab"]), 2),
                        "nearest_delta_e": None if nearest is None else round(nearest, 2), "regions": 0, "open_regions": 0})
    by_index = {c["index"]: c for c in colours}
    px_area = document["px_mm"] ** 2
    used: dict[str, dict] = {}
    unresolved_regions, missing_regions, weighted, weight = [], [], 0.0, 0.0
    for region in document["regions"]:
        c = by_index[region["color"]]
        c["regions"] += 1
        chosen = colouring["regions"].get(region["id"])
        if region["id"] in excluded_regions:
            continue
        if chosen is not None:                  # a region's own colour wins over its colour's, even an excluded one
            if chosen not in by_id:
                missing_regions.append(region["id"])
                continue
            entry_id = chosen
        elif c["status"] == "excluded":
            continue
        else:
            c["open_regions"] += 1
            if c["status"] not in RESOLVED:
                unresolved_regions.append(region["id"])
                continue
            entry_id = c["entry_id"]
        layer = used.setdefault(entry_id, {"entry_id": entry_id, "region_ids": [], "pixels": 0})
        layer["region_ids"].append(region["id"])
        layer["pixels"] += region["pixels"]
        weighted += region["pixels"] * color.delta_e(region["lab"], by_id[entry_id]["lab"])
        weight += region["pixels"]
    unresolved = [c for c in colours if c["status"] not in RESOLVED and c["open_regions"]]
    total = sum(p["pixels"] for p in document["palette"]) or 1
    layers = sorted(used.values(), key=lambda layer: (-by_id[layer["entry_id"]]["lab"][0], layer["entry_id"]))
    for layer in layers:
        layer["area_mm2"] = layer["pixels"] * px_area
    return {"colours": colours, "layers": layers, "by_id": by_id, "missing_regions": missing_regions,
            "unresolved": {"colours": len(unresolved), "regions": len(unresolved_regions),
                           "share": sum(c["pixels"] for c in unresolved) / total, "indexes": [c["index"] for c in unresolved]},
            "totals": {"recipes": len(layers), "regions": sum(len(layer["region_ids"]) for layer in layers),
                       "mean_delta_e": round(weighted / weight, 2) if weight else None,
                       "within_tolerance": sum(1 for c in colours if c["delta_e"] is not None and c["delta_e"] <= tolerance),
                       "colours": len(colours), "seconds": _seconds(plan, layers, by_id)}}


def _seconds(plan: dict, layers: list[dict], by_id: dict) -> float | None:
    """The estimated engraving time of the colour layers alone, from each recipe's time per square centimetre (computed
    from its complete settings, DEC-075); None while a recipe's time is not known."""
    rates = [by_id[layer["entry_id"]]["time_s_per_cm2"] for layer in layers]
    if None in rates:
        return None
    return sum(rate * layer["area_mm2"] / 100 for rate, layer in zip(rates, layers))


def _blocker_photo(plan: dict, state: dict) -> str | None:
    """Why the file cannot be written yet, or None."""
    open_ = state["unresolved"]
    if open_["colours"]:
        return (f"{open_['colours']} colour(s) in {open_['regions']} region(s) have no titanium colour within the delta E tolerance: "
                "accept the proposed colour, choose another or exclude it before export")
    if state["missing_regions"]:
        return (f"{len(state['missing_regions'])} region(s) have a titanium colour that is no longer measured on this laser, lens and "
                "titanium stock: choose another before export")
    if not state["layers"]:
        return "every region is excluded: there is nothing to engrave"
    cap = photo_cap(plan["markers_enabled"])
    if len(state["layers"]) > cap:
        return f"{len(state['layers'])} different recipes need more LightBurn layers than the {cap} available"
    return None


def _photo_refresh(store: Store, plan: dict, document: dict, entries: list[dict]) -> dict:
    """Store the layers and the unresolved summary of the current colouring and set the status: ready when it can be exported."""
    state = _state(plan, document, entries)
    plan["layers"] = _export_layers(store, plan, state)
    plan["unresolved"], plan["regions"], plan["weak"] = state["unresolved"], [], []
    cv._persist(store, plan, cv.ST_READY if _blocker_photo(plan, state) is None else cv.ST_DRAFT, plan["markers_enabled"])
    return state


def _prediction(entry: dict) -> dict | None:
    """The three estimates of REQ-002 when the colour's engravings give them, else None (not assessed)."""
    if entry["confidence"] is None or entry["expected_delta_e"] is None:
        return None
    return {"lab": entry["lab"], "confidence": entry["confidence"], "expected_delta_e": entry["expected_delta_e"], "stability": entry["stability"]}


def _recipe(store: Store, entry: dict) -> dict:
    """The complete settings of a palette colour's recipe as its observations store them, sub-layers and every LightBurn
    tag included (the palette shows only the main ones); all observations of one recipe share them."""
    row = store.one("SELECT parameters_json FROM observation WHERE id=?", (entry["observation_ids"][0],)) if entry["observation_ids"] else None
    return json.loads(row["parameters_json"]) if row else entry["parameters"]


def _export_layers(store: Store, plan: dict, state: dict) -> list[dict]:
    """One LightBurn layer per recipe used, lightest colour first, with the recipe's complete settings: C00 cleans, C01
    carries the markers when they are on, the colours follow (DEC-044, DEC-073)."""
    first = 1 + int(bool(plan["markers_enabled"]))
    out = []
    for n, layer in enumerate(state["layers"]):
        entry = state["by_id"][layer["entry_id"]]
        out.append({"index": first + n, "name": _layer_name(first + n, entry), "entry_id": entry["id"], "parameters": _recipe(store, entry),
                    "mode": entry["mode"], "cut_type": entry["mode"] or "Scan", "prediction": _prediction(entry), "knowledge_id": None,
                    "stage": None, "questioned": False, "basis": entry["basis"], "lab": entry["lab"], "srgb": entry["srgb"],
                    "time_s_per_cm2": entry["time_s_per_cm2"], "regions": [], "region_ids": layer["region_ids"],
                    "area_mm2": round(layer["area_mm2"], 3), "layer_keys": [f"e{entry['id']}"]})
    return out


def _layer_name(index: int, entry: dict) -> str:
    p = entry["parameters"]
    parts = [f"{key}{float(p[name]):g}" for key, name in (("P", "power"), ("F", "frequency"), ("V", "speed"), ("I", "line_interval"))
             if p.get(name) is not None]
    return f"C{index:02d} " + "-".join(parts)


def _estimate(plan: dict, layers: list[dict]) -> dict:
    """The estimated engraving time of the whole job (DEC-075): the cleaning over the work (and the markers when they are
    on), then every colour layer over the area of its regions."""
    clean, size, markers = plan["clean_layer"], plan["size_mm"], plan.get("markers")
    if markers and plan["markers_enabled"]:
        extent = markers["extent"]
        area = (extent["max_x"] - extent["min_x"]) * (extent["max_y"] - extent["min_y"])
    else:
        area = size["width"] * size["height"]
    return engraving_time.estimate([{"index": 0, "name": clean["name"], "parameters": clean, "area_mm2": area}]
                                   + [{"index": layer["index"], "name": layer["name"], "parameters": layer["parameters"],
                                       "area_mm2": layer["area_mm2"]} for layer in layers])


# -- reading and the file ------------------------------------------------------------------------------------------------------
SHOWN_ENTRY = ("id", "lab", "srgb", "basis", "engravings", "photographs", "parameters", "mode", "time_s_per_cm2", "confidence",
               "expected_delta_e", "stability")


def _shown(entry: dict, settings: dict) -> dict:
    """A palette colour as the screen shows it, and whether the automatic modes may choose it."""
    return {**{k: entry[k] for k in SHOWN_ENTRY}, "experiments": len(entry["experiments"]),
            "automatic": palette.automatic(entry, settings["max_time"], settings["include_as_shot"])}


def photo_palette(store: Store, plan_id: int) -> list[dict]:
    """The colours the operator may choose from by hand: every measured colour of the job's laser, lens and titanium."""
    plan = _photo_job(store, plan_id)
    return [_shown(e, plan["colour_settings"]) for e in _palette(store, plan)]


def split_svg(store: Store, plan_id: int) -> str:
    """The current split in its source colours (one path per region, with its id and colour index)."""
    return seg.to_svg(_document(_photo_job(store, plan_id)))


def photo_view(store: Store, plan: dict) -> dict:
    """A photograph job as its screen shows it: the split's settings, counts and important areas, every source colour
    with its titanium colour and status, the unresolved summary, the variants, the layers of the file with the estimated
    time of the whole job, and the exported files. The geometry itself is in :func:`split_svg`."""
    document = _document(plan)
    entries = _palette(store, plan)
    state = _state(plan, document, entries)
    by_id, colouring, settings = state["by_id"], plan["colouring"], plan["colour_settings"]
    used = {c["entry_id"] for c in state["colours"] if c["entry_id"]} | {e for e in colouring["regions"].values() if e in by_id}
    layers = _export_layers(store, plan, state)
    hidden = ("document_path", "history", "exports", "undo", "variants", "colouring", "detected", "regions", "weak", "layers")
    out = {k: v for k, v in plan.items() if k not in hidden}
    found = plan["detected"]
    out.update(
        strategy=PHOTO,
        document={**{k: document[k] for k in ("size_mm", "px_mm", "image_px", "n_colors", "min_area_mm2", "tolerance_mm", "superpixels",
                                               "faces")},
                  "version": plan["document_version"], "colours": len(document["palette"]), "regions": len(document["regions"]),
                  "important_regions": sum(r["important"] for r in document["regions"])},
        areas={"detected": [{**a, "number": i, "removed": i in plan["split"]["removed"]} for i, a in enumerate(found["areas"])],
               "faces": found["faces"], "search_failed": found["error"] is not None},
        colours=state["colours"], entries={i: _shown(by_id[i], settings) for i in sorted(used)},
        colouring={k: colouring[k] for k in ("mode", "seed", "variant", "regions", "excluded_colours", "excluded_regions")},
        settings={"tolerance_de": plan["threshold"], **settings},
        unresolved={**state["unresolved"], "missing_regions": len(state["missing_regions"])}, totals=state["totals"],
        variants=[{k: v[k] for k in ("number", "mode", "seed", "at", "totals")} for v in plan["variants"]], undo=len(plan["undo"]),
        layers=[{k: v for k, v in layer.items() if k not in ("region_ids", "layer_keys")} | {"regions": layer["region_ids"]} for layer in layers],
        time=_estimate(plan, layers), export_blocked=_blocker_photo(plan, state), layer_cap=photo_cap(plan["markers_enabled"]),
        palette_size=len(entries),
        history=[{k: h[k] for k in ("version", "op", "at")} for h in plan["history"]],
        exports=[{k: e.get(k) for k in ("number", "name", "at", "document_version", "layers", "regions", "variant", "seconds")}
                 for e in plan["exports"]])
    return out


def _photo_export(store: Store, plan: dict) -> tuple[str, bytes]:
    """The LightBurn file of a photograph job: cleaning first, one layer per recipe with its complete settings, every
    region a closed Path made of the shared borders with its holes (REQ-043); kept in the job with the colouring it came from."""
    document = _document(plan)
    entries = _palette(store, plan)
    state = _state(plan, document, entries)
    blocker = _blocker_photo(plan, state)
    if blocker is not None:
        raise cv.ConversionError(blocker)
    layers = _export_layers(store, plan, state)
    key = {region: layer["layer_keys"][0] for layer in layers for region in layer["region_ids"]}
    regions = [{**r, "layer_key": key[r["id"]]} for r in seg.regions_as_loops(document) if r["id"] in key]
    data = pl.export_lbrn2({**plan, "layers": layers, "vector_document": {"regions": regions}})
    path = store.data_dir / "files" / f"vector-export-{uuid.uuid4().hex[:12]}.lbrn2"
    path.write_bytes(data)
    plan["layers"], plan["unresolved"] = layers, state["unresolved"]
    plan["exports"].append({"number": len(plan["exports"]) + 1, "name": plan["name"] + ".lbrn2", "path": str(path), "at": now(),
                            "document_version": plan["document_version"], "layers": len(layers), "regions": len(regions),
                            "variant": plan["colouring"]["variant"], "colouring": copy.deepcopy(plan["colouring"]),
                            "seconds": _estimate(plan, layers)["seconds"]})
    cv._persist(store, plan, ST_EXPORTED, plan["markers_enabled"])
    return plan["name"], data


def _snapshot(plan: dict) -> None:
    plan["undo"] = (plan["undo"] + [copy.deepcopy(plan["colouring"])])[-UNDO_DEPTH:]


def _colour_index(document: dict, value) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or not any(p["index"] == value for p in document["palette"]):
        raise cv.ConversionError("there is no such source colour")
    return str(value)


def _region_id(document: dict, value) -> str:
    if not any(r["id"] == value for r in document["regions"]):
        raise cv.ConversionError(f"there is no region {value!r}")
    return value


def _entry_id(by_id: dict, value) -> str:
    if value not in by_id:
        raise cv.ConversionError("the titanium colour must be a measured colour of this laser, lens and titanium stock")
    return value


def colour(store: Store, plan_id: int, op: dict) -> None:
    """One colouring operation, recorded in the history; every one but ``undo`` can itself be undone.

    ``{"op": "assign", "mode"}`` recolours automatically (closest, tonality, random: a new seed each time, fewer_layers) and
    adds a variant; ``{"op": "restore", "variant"}`` brings one back; ``{"op": "settings", "tolerance_de", "max_time",
    "include_as_shot"}`` changes the choice and recolours with the current mode. ``{"op": "set_colour", "colour",
    "entry_id"}`` and ``{"op": "set_region", "region", "entry_id"}`` choose by hand (null returns to the automatic choice);
    ``{"op": "accept", "colour"}`` and ``{"op": "accept_all"}`` accept proposed substitutes; ``exclude_colour``,
    ``include_colour``, ``exclude_region`` and ``include_region`` leave colours and regions out of the file or bring them back.
    """
    if not isinstance(op, dict):
        raise cv.ConversionError("an edit must name its operation")
    plan, kind = _photo_job(store, plan_id), op.get("op")
    if kind not in COLOURING_OPS:
        raise cv.ConversionError(f"unknown edit operation {kind!r}")
    document = _document(plan)
    entries = _palette(store, plan)
    by_id = {e["id"]: e for e in entries}
    current = plan["colouring"]
    if kind == "undo":
        if not plan["undo"]:
            raise cv.ConversionError("there is no earlier colouring to go back to")
        plan["colouring"] = plan["undo"].pop()
    elif kind == "assign":
        mode = op.get("mode")
        if mode not in palette.MODES:
            raise cv.ConversionError("the recolouring mode must be closest, tonality, random or fewer_layers")
        seed = 1 + max((v["seed"] for v in plan["variants"] if v["mode"] == "random"), default=0) if mode == "random" else 0
        _snapshot(plan)
        plan["colouring"] = _automatic(plan, document, entries, mode, seed, current)
        _add_variant(plan, document, entries)
    elif kind == "restore":
        variant = next((v for v in plan["variants"] if v["number"] == op.get("variant")), None)
        if variant is None:
            raise cv.ConversionError("there is no such variant of the colouring")
        _snapshot(plan)
        plan["colouring"] = copy.deepcopy(variant["colouring"])
    elif kind == "settings":
        settings = {"max_time": colormap.time_limit(op.get("max_time")), "include_as_shot": bool(op.get("include_as_shot"))}
        threshold = cv._threshold(store, plan["device_id"], plan["lens_id"], op.get("tolerance_de", plan["threshold"]))
        _snapshot(plan)
        plan["threshold"], plan["colour_settings"] = threshold, settings
        plan["colouring"] = _automatic(plan, document, entries, current["mode"] or "closest", current["seed"], current)
        _add_variant(plan, document, entries)
    else:
        _snapshot(plan)
        _choose(plan["colouring"], plan, document, entries, by_id, kind, op)
    with store.transaction():
        plan["history"].append({"version": plan["document_version"], "op": op, "at": now()})
        _photo_refresh(store, plan, document, entries)


def _choose(colouring: dict, plan: dict, document: dict, entries: list[dict], by_id: dict, kind: str, op: dict) -> None:
    """The operator's own choices: a colour or region by hand, accepted proposals, exclusions."""
    if kind == "set_colour":
        key = _colour_index(document, op.get("colour"))
        if op.get("entry_id") is None:
            colouring["groups"].pop(key, None)
            plan["colouring"] = _automatic(plan, document, entries, colouring["mode"] or "closest", colouring["seed"], colouring)
        else:
            colouring["groups"][key] = {"entry_id": _entry_id(by_id, op["entry_id"]), "by": "hand"}
    elif kind == "set_region":
        region = _region_id(document, op.get("region"))
        if op.get("entry_id") is None:
            colouring["regions"].pop(region, None)
        else:
            colouring["regions"][region] = _entry_id(by_id, op["entry_id"])
    elif kind in ("accept", "accept_all"):
        state = _state(plan, document, entries)
        wanted = None if kind == "accept_all" else int(_colour_index(document, op.get("colour")))
        proposed = [c for c in state["colours"] if c["status"] == "proposed" and wanted in (None, c["index"])]
        if not proposed:
            raise cv.ConversionError("there is no proposed titanium colour to accept")
        for c in proposed:
            colouring["groups"][str(c["index"])] = {"entry_id": c["entry_id"], "by": "accepted"}
    elif kind in ("exclude_colour", "include_colour"):
        index = int(_colour_index(document, op.get("colour")))
        colouring["excluded_colours"] = sorted(set(colouring["excluded_colours"]) - {index} | ({index} if kind == "exclude_colour" else set()))
    else:
        region = _region_id(document, op.get("region"))
        colouring["excluded_regions"] = sorted(set(colouring["excluded_regions"]) - {region} | ({region} if kind == "exclude_region" else set()))
