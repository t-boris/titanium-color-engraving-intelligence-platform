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

import collections
import copy
import hashlib
import json
import math
import threading
import uuid
from pathlib import Path

import cv2
import numpy as np
import shapely

from . import ai_colouring as ai, capability_plates as cp, color, colormap, conversion as cv, dot_colours as dc, engraving_time, evidence_source as es, faces, grayscale, lettering, palette, photo_knowledge as pk, photo_state as st, photo_zones as pz, plans as pl, prediction, prediction_store as ps, render_cache as rc, research, row_length, segment as seg, setup as su, tasks, vectorize as vz, work_review
from .prediction import PredictionError
from .db import Store, now

MAX_SOURCE_PX = 1200                    # the longer side an image is traced at; a larger one is reduced first
COLOUR_TASKS = ("color", "fill", "tonal")
DOCUMENT_OPS = ("set_task", "set_layer", "delete", "merge", "set_tolerance")
EXPORTED = ("matched", "chosen")
ST_EXPORTED = "Exported"
JOB_NAME = "Векторная работа"
SMOOTHING_MM = 0.5                      # a new photograph work's smoothing of its borders; a work made before has none (0: as traced)
SMOOTHING_MAX_MM = 2.0                  # the end of the slider (REQ-052, DEC-083)
EXPORT_MIRROR_Y = True                  # the picture is laid out top-down, which LightBurn's galvo canvas shows upside down unless the file says
                                        # MirrorY: as for the plates (platform REQ-052, DEC-094; the operator had to flip every exported work by hand)


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


_MEMO: "collections.OrderedDict[tuple, object]" = collections.OrderedDict()
_MEMO_LOCK = threading.Lock()
MEMO_SIZE = 12


def _memo(key: tuple, make):
    """The last few smoothed documents and their pictures (the slider asks for the same strength again as often as it moves back) and the
    loops and row lengths of the last splits (DEC-107)."""
    with _MEMO_LOCK:
        if key in _MEMO:
            _MEMO.move_to_end(key)
            return _MEMO[key]
    value = make()
    with _MEMO_LOCK:
        _MEMO[key] = value
        while len(_MEMO) > MEMO_SIZE:
            _MEMO.popitem(last=False)
    return value


def _geometry(plan: dict) -> dict:
    """The current split with its borders at the work's smoothing (:func:`segment.smoothed`): what the preview and the file draw."""
    mm = float(plan.get("smoothing_mm", 0.0))
    return _memo(("geometry", plan["document_path"], mm), lambda: seg.smoothed(_document(plan), mm))


def _write_document(store: Store, document: dict) -> str:
    path = store.data_dir / "files" / f"vector-{uuid.uuid4().hex[:12]}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def _new_version(store: Store, plan: dict, document: dict, op: dict) -> None:
    """The edited document becomes the next version, numbered after every one in the history (a version left by an undo
    never gives its number again); the earlier ones stay on disk and in the history."""
    plan["document_version"] = 1 + max((h["version"] for h in plan["history"]), default=plan["document_version"])
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
    plan["export_mirror_y"] = EXPORT_MIRROR_Y
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
# DEC-073..DEC-077; its colour editor: the feature vector-work-colour-editor, REQ-043..REQ-049, DEC-001, DEC-075..DEC-077)
# ======================================================================================================================
# The job keeps the split's settings (``split``), the important areas found in its picture once (``detected``), the
# segment document (one JSON file per version, as above), the current colouring with the operator's choices, every
# automatic variant with the split version it was made on, and the steps to go back and forth (``undo``, ``redo``): each
# step holds a colouring with its split version, delta E tolerance and filters (editor DEC-077). Its palette is every
# measured colour of its laser, lens and titanium (palette.vector_palette, DEC-073); cleaning is always its first layer,
# so it holds at most 29 recipes, 28 with registration markers.
#
# A colouring: ``assignment`` (source colour index -> palette entry) and ``how`` from the last automatic mode, ``groups``
# (a colour the operator chose by hand, ``by`` "hand", or accepted before the editor, ``by`` "accepted"; every automatic
# mode keeps them), ``regions`` (a region given its own colour), ``excluded_colours`` and ``excluded_regions`` (left out of
# the file). Every source colour is coloured from the start: the fastest colour the automatic modes may use within the
# delta E tolerance, else the nearest (editor DEC-001). A colour beyond the tolerance is flagged with its delta E and
# never blocks the file; the file is refused only while the palette is empty, a chosen colour is no longer measured,
# nothing is left to engrave or the recipes outnumber the layers.
#
# The editor paints a region, a source colour or a fill over similar neighbours (editor DEC-075), merges titanium colours
# (hand choices), source colours and neighbouring regions (both a new version of the split, :mod:`segment`, editor
# DEC-076), and undoes and redoes all of it.
PHOTO = "photo"
DETAIL = {"coarse": (70, 1 / 1500), "medium": (100, 1 / 3000), "fine": (150, 1 / 7500)}
"""Levels of detail of a split: the coarse superpixels along the picture's longer side and the least region as a share
of the picture's area. On the operator's 150 mm portrait (12 colours, one face found) they gave 298, 489 and 891 regions
(least region 15, 7.5 and 3 mm²); the medium level keeps flat areas calm while the face, eyes and lips keep their finer
regions."""
DEFAULT_DETAIL = "medium"
DENSITY = (30, 250)
"""The density of a split (vector-detail-and-colour-control I-2, its DEC-093): the coarse superpixels along the picture's longer side, any whole number in
this range, independent of the number of colours; the three levels of detail are 70, 100 and 150 of it. The least region follows the
density (:func:`least_share`), so that a lower density gives fewer and larger regions."""


def least_share(density: int) -> float:
    """The least region, as a share of the picture's area, at a density: the share of a level of detail at its density, and between and
    beyond them along the straight line through the levels on logarithmic scales (log share against log density), as a slider needs it."""
    levels = sorted(DETAIL.values())
    for across, share in levels:
        if density == across:
            return share
    x = [math.log(across) for across, _ in levels]
    y = [math.log(share) for _, share in levels]
    k = 0 if density < levels[1][0] else 1                         # the segment it lies on, or the nearest one beyond the ends
    t = (math.log(density) - x[k]) / (x[k + 1] - x[k])
    return math.exp(y[k] + t * (y[k + 1] - y[k]))


def density_of(split: dict) -> int:
    """The density a split was made at: its own, or that of its level of detail (works split before 0.28.0)."""
    return int(split.get("density") or DETAIL[split.get("detail") or DEFAULT_DETAIL][0])
PHOTO_OPS = ("photo_add", "photo_remove", "photo_set", "photo_delete")     # the photo zones (REQ-073, :mod:`photo_zones`)
TEXT_OPS = lettering.OPS                                                  # the inscriptions (feature inscriptions-in-works)
COLOURING_OPS = ("assign", "ai_colour", "restore", "settings", "set_colour", "paint", "exclude_colour", "include_colour",
                 "exclude_region", "include_region", "merge_titanium", "merge_colours", "merge_regions", "undo", "redo") + PHOTO_OPS + TEXT_OPS
MERGE_OPS = ("merge_colours", "merge_regions")       # each makes a new version of the split
SCOPES = ("region", "colour", "fill")                # what a click of the brush paints (editor REQ-045)
UNDO_DEPTH = 50                                      # steps kept to undo and redo together


def photo_cap(markers: bool) -> int:
    """Colours and recipes of a photograph job: LightBurn's 30 output colours less the cleaning, less the markers (DEC-073)."""
    return pl.MAX_LAYERS - 1 - int(markers)


MARKED_KINDS = faces.FINE_KINDS            # what an area marked by hand is: an eye, the lips or another area


def _split_settings(params: dict, markers: bool, detected: list[dict]) -> dict:
    """The split settings checked: colours within the job's layers, the splitting algorithm (``segment.ALGORITHMS``, a level
    of detail is not one), a density, a smoothing in mm, faces on or off, areas marked by hand (in pixels of the working
    picture, each an eye, the lips or another area, with a detail of its own or not), detected areas removed (by their number)
    and detected areas given a detail or a boundary of their own (``adjusted``, vector-detail-and-colour-control I-3)."""
    cap = photo_cap(markers)
    n = params.get("n_colors")
    if isinstance(n, bool) or not isinstance(n, int) or not seg.MIN_COLORS <= n <= cap:
        raise cv.ConversionError(f"choose from {seg.MIN_COLORS} to {cap} colours: the cleaning takes one LightBurn layer"
                                 + (" and the markers another" if markers else ""))
    algorithm = params.get("algorithm") or seg.DEFAULT_ALGORITHM
    if algorithm not in seg.ALGORITHMS:
        raise cv.ConversionError("the splitting algorithm must be slic, tonal, planes or seeds")
    density = params.get("density")
    if density is None:
        detail = params.get("detail") or DEFAULT_DETAIL
        if detail not in DETAIL:
            raise cv.ConversionError("the level of detail must be coarse, medium or fine")
        density = DETAIL[detail][0]
    if isinstance(density, bool) or not isinstance(density, int) or not DENSITY[0] <= density <= DENSITY[1]:
        raise cv.ConversionError(f"the density must be a whole number from {DENSITY[0]} to {DENSITY[1]}")
    try:
        smoothing = float(params.get("tolerance_mm", seg.TOLERANCE_MM))
    except (TypeError, ValueError):
        smoothing = -1.0
    if not np.isfinite(smoothing) or smoothing < 0:
        raise cv.ConversionError("the smoothing must be a non-negative number of millimetres")
    manual = []
    for area in params.get("manual") or []:
        kind = (area.get("kind") or "manual") if isinstance(area, dict) else None
        if kind not in MARKED_KINDS:
            raise cv.ConversionError("a marked area is an eye, the lips or another area")
        manual.append(_area({**area, "kind": kind, "source": "manual", "score": None}))
    removed = params.get("removed") or []
    if not isinstance(removed, list) or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(detected) for i in removed):
        raise cv.ConversionError("a removed area must be one of the areas found in the picture")
    adjusted = {}
    for change in params.get("adjusted") or []:
        i = change.get("number") if isinstance(change, dict) else None
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(detected) or i in adjusted:
            raise cv.ConversionError("an adjusted area must be one of the areas found in the picture, each once")
        shape = {k: change[k] for k in ("ellipse", "polygon") if k in change}
        if change.get("detail") is None and not shape:
            continue
        found = {k: v for k, v in detected[i].items() if not shape or k not in ("ellipse", "polygon")}
        checked = _area({**found, **shape, "detail": change.get("detail")})
        adjusted[i] = {"number": i, **{k: checked[k] for k in ("detail", *shape) if k in checked}}
    return {"n_colors": n, "algorithm": algorithm, "density": density, "tolerance_mm": smoothing, "faces": bool(params.get("faces", True)),
            "manual": manual, "removed": sorted(set(removed)), "adjusted": [adjusted[i] for i in sorted(adjusted)]}


def _area(area: dict) -> dict:
    """An important area checked (``faces.check_area``), its detail first, so that each mistake has its own message."""
    detail = area.get("detail")
    if detail is not None:
        if area["kind"] not in faces.FINE_KINDS:
            raise cv.ConversionError("only an eye, the lips or a marked area takes a detail of its own")
        if detail not in faces.DETAILS:
            raise cv.ConversionError("the detail of an area must be face, fine, finer or finest")
    try:
        return faces.check_area(area)
    except (TypeError, ValueError):
        raise cv.ConversionError("an important area must be an ellipse or a polygon of finite numbers in picture pixels") from None


def _areas(plan: dict, split: dict | None = None) -> list[dict]:
    """The detected areas as the split uses them: each with the detail and boundary the operator gave it (``adjusted``)."""
    changes = {c["number"]: c for c in (split or plan["split"]).get("adjusted", [])}
    out = []
    for i, area in enumerate(plan["detected"]["areas"]):
        change = changes.get(i, {})
        shape = {k: change[k] for k in ("ellipse", "polygon") if k in change}
        out.append({**{k: v for k, v in area.items() if not shape or k not in ("ellipse", "polygon")}, **shape,
                    **({"detail": change["detail"]} if "detail" in change else {})})
    return out


def _centres(previous: dict, split: dict, document: dict) -> list | None:
    """The colour centres of the work's split, kept by a new split that changes only the detail, boundary or kind of its areas, so that
    the colours outside a changed area stay as they were (I-3); any other change (colours, algorithm, density, faces, areas removed or
    marked) clusters anew. None for a split made before 0.28.0, which has no centres."""
    same = (previous["n_colors"] == split["n_colors"] and previous.get("algorithm", seg.DEFAULT_ALGORITHM) == split["algorithm"]
            and density_of(previous) == split["density"] and previous["faces"] == split["faces"] and previous["removed"] == split["removed"]
            and len(previous["manual"]) == len(split["manual"]))
    return document.get("centres") if same else None


def _segment(plan: dict, picture: np.ndarray, centres: list | None = None) -> dict:
    """Split the job's picture with its settings; the faces found once in it are used unless removed or switched off, each area as the
    operator adjusted it, and the colour centres of an earlier split when given (:func:`_centres`)."""
    s, found = plan["split"], plan["detected"]
    across = density_of(s)
    share = least_share(across)
    size = plan["size_mm"]
    areas = [a for i, a in enumerate(_areas(plan)) if i not in s["removed"]] if s["faces"] else []
    document = seg.segment(picture, size["width"], s["n_colors"], important=areas + s["manual"], use_faces=False,
                           min_area_mm2=share * size["width"] * size["height"], tolerance_mm=s["tolerance_mm"], superpixels=across,
                           algorithm=s.get("algorithm", seg.DEFAULT_ALGORITHM), centres=centres)
    document["faces"] = {"searched": s["faces"], "found": found["faces"] if s["faces"] else 0, "error": found["error"] if s["faces"] else None}
    return document


def start_photo(store: Store, device_id: int, lens_id: int | None, material_id: int, image_bytes: bytes, width_mm: float, name: str, *,
                threshold=None, n_colors: int = 12, detail: str = DEFAULT_DETAIL, tolerance_mm: float = seg.TOLERANCE_MM,
                algorithm: str = seg.DEFAULT_ALGORITHM, use_faces: bool = True, markers: bool = False, max_time: float | None = None, include_as_shot: bool = False,
                task: str | None = None, goals: dict | None = None, source: dict | None = None) -> int:
    """Split a photograph into colour regions for one laser, lens and titanium stock and colour every source colour
    automatically: the fastest measured colour within the delta E tolerance (DEC-075), else the nearest (editor DEC-001). With ``source``
    (a connected laboratory release with the laser, lens and titanium it measured, feature electron REQ-085) the colours are that release's:
    the work is pinned to it and keeps the palette it was made with."""
    if not (name or "").strip():
        raise cv.ConversionError("give the plan a name")
    pin = None if source is None else es.pin(store, source)
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
    split = _split_settings({"n_colors": n_colors, "algorithm": algorithm, "detail": detail, "tolerance_mm": tolerance_mm, "faces": use_faces},
                            markers, [])
    search = faces.important_areas(picture)
    identifier = pl.new_identifier("TCE-A")
    h, w = picture.shape[:2]
    size = {"width": width, "height": h * width / w}
    lens = setup["lens"] or {}
    plan = {"task": "vector", "engraving_task": tasks.chosen_or_default(task, tasks.VECTOR_STRATEGY_TASK[PHOTO], goals), "strategy": PHOTO, "smoothing_mm": SMOOTHING_MM,
            "image_path": cv._store_image(store, image_bytes), "size_mm": size, "material_id": material_id, "threshold": thr,
            "lens": su.lens_snapshot(setup), "split": split, "detected": {"areas": search.areas, "faces": search.faces, "error": search.error},
            "colour_settings": {"max_time": colormap.time_limit(max_time), "include_as_shot": bool(include_as_shot)},
            "experiment": {"label": "Job", "test_name": JOB_NAME,
                           "device": {k: setup["device"].get(k) for k in ("id", "name", "manufacturer", "model", "serial", "title")},
                           "lens": {k: lens.get(k) for k in ("id", "name", "focal_length_mm", "field_mm", "expansion")},
                           "material": {k: material[k] for k in ("id", "name", "family", "grade", "batch", "thickness_mm", "surface")}},
            "markers": cv._plan_markers(identifier, markers, size["width"], size["height"], store),
            "marker_layer": pl.marker_layer_settings(store) if markers else None, "clean_layer": pl.clean_layer(setup["device"]["passport"]),
            "colouring": None, "variants": [], "undo": [], "redo": [], "exports": [], "regions": [], "layers": [], "weak": [],
            "evidence_source": pin, "source_versions": []}
    document = _segment(plan, picture)
    plan["document_path"], plan["document_version"] = _write_document(store, document), 1
    plan["history"] = [{"version": 1, "op": {"op": "split", **_split_op(split)}, "at": now(), "path": plan["document_path"]}]
    entries = _palette(store, {"device_id": device_id, "lens_id": lens_id, "material_id": material_id, "evidence_source": pin})
    if pin is not None:
        pin.update(_kept(store, plan, entries))
    plan["colouring"] = _automatic(plan, document, entries, "closest", 0, _empty_colouring())
    _add_variant(store, plan, document, entries)
    with store.transaction():
        plan_id = cv.save_plan(store, None, name=name.strip(), mode=pl.MODE_VECTOR, status=cv.ST_DRAFT, device_id=device_id, lens_id=lens_id,
                               markers=markers, identifier=identifier, band_count=None, data=plan)
        _photo_refresh(store, pl.get_plan(store, plan_id), document, entries)
    return plan_id


def _split_op(split: dict) -> dict:
    """What the history records of a split: its settings and how many areas were marked or removed."""
    return {**{k: split[k] for k in ("n_colors", "algorithm", "tolerance_mm", "faces")}, "density": density_of(split),
            "manual": len(split["manual"]), "removed": len(split["removed"]), "adjusted": len(split.get("adjusted", []))}


def is_photo(plan: dict) -> bool:
    return plan.get("strategy") == PHOTO


def _photo_job(store: Store, plan_id: int) -> dict:
    plan = _job(store, plan_id)
    if not is_photo(plan):
        raise cv.ConversionError("only a photograph split into colour regions is split and coloured this way")
    return plan


def resize(store: Store, plan_id: int, width_mm=None, height_mm=None) -> None:
    """The work engraved at another size (feature work-size-and-splitting-a-region-again, REQ-001, DEC-001): its new width or its new
    height in mm, the other side by the picture. The split is scaled, not made again (:func:`segment.scaled`): a new version with the same
    regions, colours, merges and variants, which undo brings back (:func:`_go`). The inscriptions are scaled with the picture
    (``lettering.scaled``), each photo zone is settled at its new width, the markers are drawn for the new size; the smoothing stays in
    mm (DEC-003). The size the work has already, both sides or neither, and a side that is not a positive number are refused."""
    plan = _photo_job(store, plan_id)
    if (width_mm is None) == (height_mm is None):
        raise cv.ConversionError("give the work's new width or its new height, one of them")
    given = "width" if height_mm is None else "height"
    try:
        side = float(width_mm if height_mm is None else height_mm)
    except (TypeError, ValueError):
        side = math.nan
    if not math.isfinite(side) or side <= 0:
        raise cv.ConversionError("the work's size must be a positive number of millimetres")
    factor = side / plan["size_mm"][given]
    if abs(factor - 1) < 1e-6:
        raise cv.ConversionError("the work is this size already")
    _pin_legacy(plan)
    _key_variants(plan, _document(plan))
    document = seg.scaled(_document(plan), factor)
    colouring = copy.deepcopy(plan["colouring"])
    if _texts(colouring):
        colouring["texts"] = lettering.scaled(_texts(colouring), factor)
    if pz.zones(colouring):
        loops = {r["id"]: r["loops"] for r in seg.regions_as_loops(seg.smoothed(document, float(plan.get("smoothing_mm", 0.0))))}
        for zone in pz.zones(colouring):
            pz.settle(_ev(store, plan), plan, zone, pz.width_of(loops, zone["regions"]))
    _snapshot(plan)
    plan["colouring"] = colouring
    _resized(store, plan, document["size_mm"])
    entries = _palette(store, plan)
    with store.transaction():
        _new_version(store, plan, document, {"op": "resize", "given": given, "width_mm": document["size_mm"]["width"],
                                             "height_mm": document["size_mm"]["height"]})
        _photo_refresh(store, plan, document, entries)
        store.audit("vector_work_resized", plan_id=plan["id"], given=given, width_mm=document["size_mm"]["width"],
                    height_mm=document["size_mm"]["height"])


def _resized(store: Store, plan: dict, size: dict) -> None:
    """The plan at the size of its document: the size itself and the registration markers drawn for it."""
    plan["size_mm"] = {"width": float(size["width"]), "height": float(size["height"])}
    plan["markers"] = cv._plan_markers(plan["plan_identifier"], plan["markers_enabled"], size["width"], size["height"], store)


def _same_size(a: dict, b: dict) -> bool:
    return all(abs(float(a[k]) - float(b[k])) < 1e-6 for k in ("width", "height"))


def resplit(store: Store, plan_id: int, params: dict) -> None:
    """Split the picture again with new settings and important areas: a new document version, coloured anew (closest);
    a fresh start, the variants and the steps to undo and redo of the earlier split are left behind with it."""
    plan = _photo_job(store, plan_id)
    if not isinstance(params, dict):
        raise cv.ConversionError("the split settings must be an object")
    previous, plan["split"] = plan["split"], _split_settings(params, plan["markers_enabled"], plan["detected"]["areas"])
    old = _document(plan)
    document = _segment(plan, _source_rgb(Path(plan["image_path"]).read_bytes()), _centres(previous, plan["split"], old))
    entries = _palette(store, plan)
    zones = _carried_zones(store, plan, old, document)
    with store.transaction():
        _new_version(store, plan, document, {"op": "split", **_split_op(plan["split"])})
        plan["colouring"] = _automatic(plan, document, entries, "closest", 0, {**_empty_colouring(), "photo": zones,
                                                                              "texts": copy.deepcopy(_texts(plan["colouring"]))})
        plan["variants"], plan["undo"], plan["redo"] = [], [], []
        _add_variant(store, plan, document, entries)
        _photo_refresh(store, plan, document, entries)


def split_preview(store: Store, plan_id: int, params: dict) -> dict:
    """How many regions and colours the picture would be split into with these settings (the ones «Разбить заново» takes), the work left as
    it is: the density slider shows the count before the split is made. Each answer is kept for its picture and settings."""
    plan = _photo_job(store, plan_id)
    if not isinstance(params, dict):
        raise cv.ConversionError("the split settings must be an object")
    split = _split_settings(params, plan["markers_enabled"], plan["detected"]["areas"])
    centres = _centres(plan["split"], split, _document(plan))

    def count() -> dict:
        document = _segment({**plan, "split": split}, _source_rgb(Path(plan["image_path"]).read_bytes()), centres)
        return {"regions": len(document["regions"]), "colours": len(document["palette"]), "min_area_mm2": document["min_area_mm2"]}

    key = json.dumps({**{k: v for k, v in split.items() if k != "tolerance_mm"}, "centres": centres}, sort_keys=True)
    return {"density": split["density"], **_memo(("split-preview", plan["image_path"], key), count)}


# -- colouring -------------------------------------------------------------------------------------------------------------
def _ev(store: Store, plan: dict) -> Store:
    """The store the job's measured colours and curves are read from: the workshop's, or the snapshot of the laboratory release the job is
    pinned to (feature electron, REQ-085). A pinned job that keeps its confirmed result is refused with the reason."""
    return es.require(es.of(store, plan))


def _kept(store: Store, plan: dict, entries: list[dict]) -> dict:
    """The palette a pinned job is confirmed with, kept with every entry's complete recipe (``evidence_source.keep_palette``)."""
    return es.keep_palette(store, entries, {e["id"]: _recipe(store, plan, e) for e in entries})


def _palette(store: Store, plan: dict) -> list[dict]:
    """Every measured colour that fills an area (DEC-073) of the job's laser, lens and titanium stock, or of the laser, lens and titanium
    of the laboratory release it is pinned to; a pinned job that cannot be calculated again keeps the palette it was confirmed with."""
    evidence = es.of(store, plan)
    if evidence.frozen is not None:
        return es.kept_palette(evidence.pin)
    return palette.vector_palette(evidence.store, evidence.device_id, evidence.lens_id, evidence.material_id)["entries"]


def _empty_colouring() -> dict:
    return {"mode": None, "seed": 0, "variant": None, "assignment": {}, "how": {}, "groups": {}, "regions": {}, "excluded_colours": [],
            "excluded_regions": []}


def _sources(document: dict) -> list[dict]:
    return [{"index": p["index"], "lab": p["lab"], "pixels": p["pixels"]} for p in document["palette"]]


def _automatic(plan: dict, document: dict, entries: list[dict], mode: str, seed: int, colouring: dict) -> dict:
    """A new colouring after an automatic mode: every colour without the operator's own choice gets the mode's entry
    (palette.assign), the operator's choices of colours (still measured, of a colour still in the split) and regions stay."""
    if mode == "ai":                         # the model's choices stay as they were made and are never asked for again (DEC-084)
        return copy.deepcopy(colouring)
    if mode not in palette.MODES:            # a mode of an older version (fewer_layers, most_colours): the work's colours are made by the standing ones (DEC-089)
        mode = "closest"
    by_id = {e["id"]: e for e in entries}
    out = {**copy.deepcopy(colouring), "mode": mode, "seed": seed, "assignment": {}, "how": {}}
    out.pop("ai", None)                      # what the model said belongs to the colouring it chose, not to this one
    if not entries:                          # nothing measured on this titanium: every colour stays without a titanium colour
        return out
    settings = plan["colour_settings"]
    indexes = {str(p["index"]) for p in document["palette"]}
    keep = {i: g["entry_id"] for i, g in colouring["groups"].items() if g["entry_id"] in by_id and i in indexes}
    colour_rows = _row_lengths(plan, document)[1]
    borders = _memo(("borders", plan["document_path"]), lambda: ai.touching(document, None)) if mode == "contrast" else None
    subset = colouring.get("subset") or "all"
    if mode == "artistic":
        out["subset"] = subset
    else:
        out.pop("subset", None)
    result = palette.assign(_sources(document), entries, mode, tolerance_de=plan["threshold"], seed=seed, max_time=settings["max_time"],
                            keep=keep, include_as_shot=settings["include_as_shot"], borders=borders, subset=subset,
                            size_of=lambda index, entry: colour_rows(index, _angle(entry)))     # each colour at its own size (DEC-107)
    out["assignment"] = {str(c["index"]): c["entry_id"] for c in result["colours"]}
    out["how"] = {str(c["index"]): c["how"] for c in result["colours"]}
    return out


def _carried_zones(store: Store, plan: dict, old: dict, new: dict) -> list[dict]:
    """The photo zones of the split ``old`` on the split ``new`` of the same picture: each on the new regions at least half inside it, a dot
    kind's power settled at its new width (:func:`photo_zones.carried`)."""
    zones = pz.zones(plan["colouring"])
    if not zones:
        return []
    old_raster = pz.labels(old, _loops_by_region(plan, old))
    new_raster = pz.labels(new, {r["id"]: r["loops"] for r in seg.regions_as_loops(new)})
    carried = pz.carried(old, old_raster, new, new_raster, zones)
    loops = {r["id"]: r["loops"] for r in seg.regions_as_loops(seg.smoothed(new, float(plan.get("smoothing_mm", 0.0))))}
    return [pz.settle(_ev(store, plan), plan, zone, pz.width_of(loops, zone["regions"])) for zone in carried]


def _add_variant(store: Store, plan: dict, document: dict, entries: list[dict]) -> None:
    """The current colouring, just made by an automatic mode, becomes a numbered variant that can be restored on a split with the
    regions it coloured (:func:`_split_key`)."""
    number = 1 + max((v["number"] for v in plan["variants"]), default=0)
    plan["colouring"]["variant"] = number
    state = _state(plan, document, entries, _inscribed(store, plan, entries))
    plan["variants"].append({"number": number, "mode": plan["colouring"]["mode"], "seed": plan["colouring"]["seed"], "at": now(),
                             **({"subset": plan["colouring"]["subset"]} if plan["colouring"].get("subset") else {}),
                             "version": plan["document_version"], "split": _split_key(document), "colouring": copy.deepcopy(plan["colouring"]),
                             "totals": state["totals"]})


def _split_key(document: dict) -> str:
    """What a colouring is made for: the regions of the split with their colours and sizes (work-size-and-splitting-a-region-again, DEC-002).
    A change of the work's size keeps it; a merge, a region split again or a new split changes it."""
    return hashlib.sha1(json.dumps([[r["id"], r["color"], r["pixels"]] for r in document["regions"]]).encode()).hexdigest()[:16]


def _key_variants(plan: dict, document: dict) -> None:
    """Variants made before the key (0.36.0) on the version the work is at now get it: this document is the split they coloured. Those of
    other versions keep the version rule until the work is back on their version."""
    key = None
    for variant in plan["variants"]:
        if "split" not in variant and variant.get("version", plan["document_version"]) == plan["document_version"]:
            key = key or _split_key(document)
            variant["split"] = key


def _restorable(plan: dict, document: dict, variant: dict) -> bool:
    """Whether a variant can be restored on the current split: one with the regions it coloured (DEC-002); a variant made before the key
    knows only the version it was made on (editor DEC-077)."""
    key = variant.get("split")
    return key == _split_key(document) if key else variant["version"] == plan["document_version"]


def _loops_by_region(plan: dict, document: dict) -> dict[str, list]:
    """The closed loops (mm) of every region of the split as it was made: the smoothing only redraws the borders, by far less than the 10 %
    that tells two sizes apart (``prediction.SIZE_TOLERANCE``), so the sizes and colours of a work do not move with the slider."""
    return _memo(("loops", plan["document_path"]), lambda: {r["id"]: r["loops"] for r in seg.regions_as_loops(document)})


def _angle(entry: dict) -> float:
    return float(entry["parameters"].get("scan_angle") or 0.0)


def _row_lengths(plan: dict, document: dict):
    """How long the scan rows of regions engraved as one layer are (DEC-107): ``of(region_ids, angle)`` fills their shapes together, as
    LightBurn fills a layer's shapes by default (the file writes no other grouping), and ``of_colour(index, angle)`` takes the regions
    of one source colour, the layer it makes when it has an entry of its own. Each length is computed once per split."""
    loops = _loops_by_region(plan, document)
    known = _memo(("rows", plan["document_path"]), dict)
    by_colour: dict[int, list[str]] = {}
    for region in document["regions"]:
        by_colour.setdefault(region["color"], []).append(region["id"])

    def of(region_ids, angle: float = 0.0) -> float | None:
        key = (frozenset(region_ids), round(angle, 3))
        if key not in known:
            known[key] = row_length.of_shapes([loops[r] for r in region_ids if r in loops], angle)
        return known[key]

    def of_colour(index: int, angle: float = 0.0) -> float | None:
        return of(by_colour.get(index, ()), angle)

    return of, of_colour


# -- inscriptions (feature inscriptions-in-works, REQ-004, DEC-003) ------------------------------------------------------------------
TRIM_LEFT = 1e-6                     # a region the inscriptions cover all but this share of is not engraved


def _texts(colouring: dict | None) -> list[dict]:
    """The inscriptions of a colouring, the lowest first: a later one lies over the earlier ones."""
    return (colouring or {}).get("texts") or []


def _inscribed(store: Store, plan: dict, entries: list[dict]) -> dict:
    """The work's inscriptions laid out on it (:func:`lettering.inscribed`) with the measured colours of its laser, lens and titanium."""
    return lettering.inscribed(store.data_dir, _texts(plan["colouring"]), plan["size_mm"], {e["id"] for e in entries})


def _region_shapes(plan: dict) -> dict:
    """Every region as a polygon of its loops at the work's smoothing (what the file writes), to cut the inscriptions into."""
    mm = float(plan.get("smoothing_mm", 0.0))
    return _memo(("region-shapes", plan["document_path"], mm),
                 lambda: {rid: lettering.polygon(loops) for rid, loops in _zone_loops(plan).items()})


def _trimmed(plan: dict, region_ids, cut) -> dict[str, dict]:
    """The regions the inscriptions' ``cut`` takes a part of: what is left of each (``shapes``: closed loops in mm, outline then holes) and
    the share of the region it is."""
    if cut is None or cut.is_empty:
        return {}
    known = _region_shapes(plan)
    ids = [r for r in region_ids if r in known and not known[r].is_empty]
    if not ids:
        return {}
    polygons = np.array([known[r] for r in ids], dtype=object)
    shapely.prepare(cut)
    out = {}
    hit = shapely.intersects(polygons, cut)
    for rid, whole in zip(np.array(ids, dtype=object)[hit], polygons[hit]):
        left = lettering.minus(whole, cut)
        share = left.area / whole.area if whole.area > 0 else 0.0
        if share < 1.0 - 1e-9:                   # touching its border only takes nothing
            out[rid] = {"shapes": lettering.shapes(left), "share": share}
    return out


def _under(plan: dict, region_ids, cut) -> float:
    """How much of the regions (mm²) lies under the inscriptions' ``cut``."""
    if cut is None or cut.is_empty:
        return 0.0
    known = _region_shapes(plan)
    return float(sum(shapely.intersection(known[r], cut).area for r in region_ids if r in known))


def _text_op(store: Store, plan: dict, entries: list[dict], colouring: dict, op: dict) -> dict:
    """The inscriptions after an operation (:func:`lettering.operate`), on a copy of the colouring that is returned. A new inscription
    takes the darkest measured colour, the one that stands out most on clean titanium, and the last font used (its undo tells which
    inscription was changed last)."""
    by_id = {e["id"]: e for e in entries}
    try:
        colouring["texts"] = lettering.operate(store.data_dir, _texts(colouring), op, plan["size_mm"], lambda e: e in by_id,
                                               lambda: lettering.darkest(entries), [_texts(s["colouring"]) for s in plan["undo"]])
    except su.ValidationError as exc:
        raise cv.ConversionError(str(exc)) from None
    return colouring


def _state(plan: dict, document: dict, entries: list[dict], inscribed: dict | None = None) -> dict:
    """Every source colour and region with its titanium colour and status, the colours beyond the delta E tolerance, the
    regions whose titanium colour is no longer measured, the layers of the file and the totals of the current colouring.

    A colour's status: ``excluded``, ``missing`` (its titanium colour is not measured, or not any more), ``hand`` or
    ``accepted`` (the operator's choice; accepted before the editor) or ``automatic``. ``outside_tolerance`` flags a
    titanium colour farther than the delta E tolerance; it never blocks the file (editor DEC-001).

    A layer's titanium colour is its recipe's in rows as long as the layer's (DEC-107, ``palette.at_size``): ``by_id`` holds the entry of
    each layer at its size (with ``size``) and every other entry as measured, and a colour's delta E is to the colour of its layer (to its
    entry at the length of its own regions while it has none). ``nearest_delta_e`` compares every candidate at the colour's own length.

    The inscriptions (``inscribed``, :func:`_inscribed`) cut into the regions under them: a region keeps what lies outside their cut
    (``trimmed``: its shapes and the share of it left; one wholly under it is not engraved), and the letters and backings join the layer
    of their titanium colour (``texts`` of a layer, the shapes in ``text_shapes``). A layer's area and row length are of what it engraves."""
    measured = {e["id"]: e for e in entries}
    cut = (inscribed or {}).get("cut")
    trimmed = _trimmed(plan, [r["id"] for r in document["regions"]], cut)
    colouring, settings, tolerance = plan["colouring"], plan["colour_settings"], plan["threshold"]
    candidates = palette.choosable(entries, settings["max_time"], settings["include_as_shot"])[0]
    excluded_colours, excluded_regions = set(colouring["excluded_colours"]), set(colouring["excluded_regions"])
    zoned = pz.zone_of(colouring)                   # engraved as photo engravings, not in a colour (REQ-073)
    rows, colour_rows = _row_lengths(plan, document)
    colours = []
    for source in document["palette"]:
        key = str(source["index"])
        group = colouring["groups"].get(key)
        entry = measured.get(group["entry_id"] if group else colouring["assignment"].get(key))
        if source["index"] in excluded_colours:
            status = "excluded"
        elif entry is None:
            status = "missing"
        else:
            status = group["by"] if group else "automatic"
        colours.append({"index": source["index"], "lab": source["lab"], "srgb": source["srgb"], "pixels": source["pixels"], "status": status,
                        "entry_id": entry["id"] if entry else None, "how": "hand" if group else colouring["how"].get(key), "regions": 0,
                        "open_regions": 0})
    by_index = {c["index"]: c for c in colours}
    px_area = document["px_mm"] ** 2
    used: dict[str, dict] = {}
    missing_regions, open_pixels, placed = [], {}, []
    for region in document["regions"]:
        c = by_index[region["color"]]
        c["regions"] += 1
        chosen = colouring["regions"].get(region["id"])
        if region["id"] in excluded_regions or region["id"] in zoned:
            continue
        if chosen is not None:                  # a region's own colour wins over its colour's, even an excluded one
            if chosen not in measured:
                missing_regions.append(region["id"])
                continue
            entry_id = chosen
        elif c["status"] == "excluded":
            continue
        else:
            c["open_regions"] += 1
            open_pixels[c["index"]] = open_pixels.get(c["index"], 0) + region["pixels"]
            if c["status"] == "missing":
                missing_regions.append(region["id"])
                continue
            entry_id = c["entry_id"]
        share = trimmed[region["id"]]["share"] if region["id"] in trimmed else 1.0
        if share <= TRIM_LEFT:                  # wholly under an inscription: nothing of it is engraved
            continue
        layer = used.setdefault(entry_id, {"entry_id": entry_id, "region_ids": [], "pixels": 0, "area_mm2": 0.0})
        layer["region_ids"].append(region["id"])
        layer["pixels"] += region["pixels"]
        layer["area_mm2"] += region["pixels"] * px_area * share
        placed.append((region, entry_id))
    text_shapes: dict[str, list] = {}
    for entry_id, parts in lettering.by_colour((inscribed or {}).get("rows", ())).items():
        layer = used.setdefault(entry_id, {"entry_id": entry_id, "region_ids": [], "pixels": 0, "area_mm2": 0.0})
        layer["texts"] = list(dict.fromkeys(text_id for text_id, _ in parts))
        layer["area_mm2"] += sum(shape.area for _, shape in parts)
        text_shapes[entry_id] = [shape for _, shape in parts]
    loops = _loops_by_region(plan, document)
    by_id = dict(measured)
    for entry_id, layer in used.items():                 # each layer in the colour its recipe gives at the length of its rows
        entry = measured[entry_id]
        cut_here = [r for r in layer["region_ids"] if r in trimmed]
        if cut_here or entry_id in text_shapes:          # the rows of what is left of its regions and of its letters
            layer["row_mm"] = row_length.of_shapes([loops[r] for r in layer["region_ids"] if r not in trimmed and r in loops]
                                                   + [shape for r in cut_here for shape in trimmed[r]["shapes"]]
                                                   + [shape for found in text_shapes.get(entry_id, ()) for shape in lettering.shapes(found)],
                                                   _angle(entry))
        else:
            layer["row_mm"] = rows(layer["region_ids"], _angle(entry))
        seen = palette.at_size(entry, layer["row_mm"])
        by_id[entry_id] = {**entry, "lab": seen["lab"], "srgb": seen["srgb"], "size": seen["size"]}
    weighted = sum(region["pixels"] * color.delta_e(region["lab"], by_id[entry_id]["lab"]) for region, entry_id in placed)
    weight = sum(region["pixels"] for region, _ in placed)
    for c in colours:
        entry = measured.get(c["entry_id"])
        if entry is None:
            delta = None
        else:
            lab = by_id[entry["id"]]["lab"] if entry["id"] in used else palette.at_size(entry, colour_rows(c["index"], _angle(entry)))["lab"]
            delta = color.delta_e(c["lab"], lab)
        nearest = min((color.delta_e(c["lab"], palette.at_size(e, colour_rows(c["index"], _angle(e)))["lab"]) for e in candidates), default=None)
        c.update(delta_e=None if delta is None else round(delta, 2), outside_tolerance=delta is not None and delta > tolerance,
                 nearest_delta_e=None if nearest is None else round(nearest, 2))
    outside = [c for c in colours if c["outside_tolerance"] and c["status"] != "excluded" and c["open_regions"]]
    total = sum(p["pixels"] for p in document["palette"]) or 1
    layers = sorted(used.values(), key=lambda layer: (-by_id[layer["entry_id"]]["lab"][0], layer["entry_id"]))
    texts = (inscribed or {}).get("rows", [])
    return {"colours": colours, "layers": layers, "by_id": by_id, "missing_regions": missing_regions, "zones": pz.zones(colouring),
            "texts": texts, "trimmed": trimmed, "text_shapes": text_shapes, "cut": cut,
            "outside": {"colours": len(outside), "regions": sum(c["open_regions"] for c in outside),
                        "share": sum(open_pixels[c["index"]] for c in outside) / total, "indexes": [c["index"] for c in outside]},
            "totals": {"recipes": len(layers), "regions": sum(len(layer["region_ids"]) for layer in layers),
                       "mean_delta_e": round(weighted / weight, 2) if weight else None,
                       "within_tolerance": sum(1 for c in colours if c["delta_e"] is not None and c["delta_e"] <= tolerance),
                       "colours": len(colours), "seconds": _seconds(plan, layers, by_id), "zones": len(pz.zones(colouring)),
                       "zone_regions": len(zoned), "texts": len(texts)}}


def _seconds(plan: dict, layers: list[dict], by_id: dict) -> float | None:
    """The estimated engraving time of the colour layers alone, from each recipe's time per square centimetre (computed
    from its complete settings, DEC-075); None while a recipe's time is not known."""
    rates = [by_id[layer["entry_id"]]["time_s_per_cm2"] for layer in layers]
    if None in rates:
        return None
    return sum(rate * layer["area_mm2"] / 100 for rate, layer in zip(rates, layers))


def _blocker_photo(plan: dict, state: dict, zones: list[dict] | None = None) -> str | None:
    """Why the file cannot be written yet, or None; a colour beyond the delta E tolerance never is a reason (editor DEC-001). ``zones``
    (:func:`_zone_rows`) says why a photo zone cannot be engraved; each zone takes a layer of its own."""
    if not state["by_id"] and not state["zones"]:
        return "no measured colour of this laser, lens and titanium stock fills an area"
    if state["missing_regions"]:
        return (f"{len(state['missing_regions'])} region(s) have a titanium colour that is no longer measured on this laser, lens and "
                "titanium stock: choose another before export")
    blocked = lettering.text_blocker(state.get("texts") or [])
    if blocked:
        return blocked
    if not state["layers"] and not state["zones"]:
        return "every region is excluded: there is nothing to engrave"
    cap = photo_cap(plan["markers_enabled"])
    if len(state["layers"]) > cap:
        return f"{len(state['layers'])} different recipes need more LightBurn layers than the {cap} available"
    if len(state["layers"]) + len(state["zones"]) > cap:
        return (f"{len(state['layers'])} different recipes and {len(state['zones'])} photo zone(s) need more LightBurn layers than the {cap} "
                "available: merge titanium colours or zones")
    for row in zones or ():
        if row["problem"]:
            return f"photo zone {row['number']} cannot be engraved: {row['problem']}"
    return None


def _photo_refresh(store: Store, plan: dict, document: dict, entries: list[dict]) -> dict:
    """Store the layers of the current colouring and set the status: ready when it can be exported."""
    state = _state(plan, document, entries, _inscribed(store, plan, entries))
    zones = _zone_rows(store, plan, document, state["zones"], _first_zone(plan, state), state["cut"])
    plan["layers"] = _export_layers(store, plan, state)
    plan["regions"], plan["weak"] = [], []
    plan["counts"] = {"colours": len(document["palette"]), "regions": len(document["regions"])}    # for the list of works (:func:`listing`)
    plan.pop("unresolved", None)                 # kept by works made before the editor
    cv._persist(store, plan, cv.ST_READY if _blocker_photo(plan, state, zones) is None else cv.ST_DRAFT, plan["markers_enabled"])
    return state


def _prediction(entry: dict) -> dict | None:
    """The three estimates of REQ-002 when the colour's engravings give them, else None (not assessed)."""
    if entry["confidence"] is None or entry["expected_delta_e"] is None:
        return None
    return {"lab": entry["lab"], "confidence": entry["confidence"], "expected_delta_e": entry["expected_delta_e"], "stability": entry["stability"]}


def _recipe(store: Store, plan: dict, entry: dict) -> dict:
    """The complete settings of a palette colour's recipe as its observations store them, sub-layers and every LightBurn
    tag included (the palette shows only the main ones); all observations of one recipe share them. A kept palette carries them."""
    if entry.get("recipe") is not None:
        return entry["recipe"]
    evidence = _ev(store, plan)
    row = evidence.one("SELECT parameters_json FROM observation WHERE id=?", (entry["observation_ids"][0],)) if entry["observation_ids"] else None
    return json.loads(row["parameters_json"]) if row else entry["parameters"]


def _export_layers(store: Store, plan: dict, state: dict) -> list[dict]:
    """One LightBurn layer per recipe used, lightest colour first, with the recipe's complete settings: C00 cleans, C01
    carries the markers when they are on, the colours follow (DEC-044, DEC-073)."""
    first = 1 + int(bool(plan["markers_enabled"]))
    out = []
    for n, layer in enumerate(state["layers"]):
        entry = state["by_id"][layer["entry_id"]]
        out.append({"index": first + n, "name": _layer_name(first + n, entry), "entry_id": entry["id"], "parameters": _recipe(store, plan, entry),
                    "mode": entry["mode"], "cut_type": entry["mode"] or "Scan", "prediction": _prediction(entry), "knowledge_id": None,
                    "stage": None, "questioned": False, "basis": entry["basis"], "lab": entry["lab"], "srgb": entry["srgb"],
                    "time_s_per_cm2": entry["time_s_per_cm2"], "regions": [], "region_ids": layer["region_ids"], "texts": layer.get("texts", []),
                    "area_mm2": round(layer["area_mm2"], 3), "layer_keys": [f"e{entry['id']}"], "size": entry.get("size")})
    return out


def _layer_name(index: int, entry: dict) -> str:
    p = entry["parameters"]
    parts = [f"{key}{float(p[name]):g}" for key, name in (("P", "power"), ("F", "frequency"), ("V", "speed"), ("I", "line_interval"))
             if p.get(name) is not None]
    return f"C{index:02d} " + "-".join(parts)


def _estimate(plan: dict, layers: list[dict], zones: list[dict] = ()) -> dict:
    """The estimated engraving time of the whole job (DEC-075): the cleaning over the work (and the markers when they are
    on), then every colour layer over the area of its regions, then every photo zone over its area (:func:`_zone_rows`)."""
    clean, size, markers = plan["clean_layer"], plan["size_mm"], plan.get("markers")
    if markers and plan["markers_enabled"]:
        extent = markers["extent"]
        area = (extent["max_x"] - extent["min_x"]) * (extent["max_y"] - extent["min_y"])
    else:
        area = size["width"] * size["height"]
    return engraving_time.estimate([{"index": 0, "name": clean["name"], "parameters": clean, "area_mm2": area}]
                                   + [{"index": layer["index"], "name": layer["name"], "parameters": layer["parameters"],
                                       "area_mm2": layer["area_mm2"]} for layer in layers]
                                   + [row["time"] for row in zones if row["time"] is not None])


# -- photo zones (REQ-073, DEC-114) ---------------------------------------------------------------------------------------------
def _zone_loops(plan: dict) -> dict[str, list]:
    """The closed loops (mm) of every region at the work's smoothing: what the file's paths are written from and the zones are cut along."""
    mm = float(plan.get("smoothing_mm", 0.0))
    return _memo(("zone-loops", plan["document_path"], mm), lambda: {r["id"]: r["loops"] for r in seg.regions_as_loops(_geometry(plan))})


def _zone_rows(store: Store, plan: dict, document: dict, zones: list[dict], first: int, cut=None) -> list[dict]:
    """Every photo zone with what the screen, the time and the file need, its layer numbered from ``first``: how wide it is (the length of its
    rows, DEC-107), its area and box, its scale's curve at that width with the dots of a dot kind (their measured tones when that kind was
    photographed), the settings and the time of its layer; or why it cannot be engraved (``problem``: its scale is not measured there). The
    row's zone has every setting (``photo_zones.full``). What the inscriptions ``cut`` out of a zone is not engraved by it: its area and time
    leave it out. The zones of a pinned job that keeps its confirmed result are not calculated again: their problem says why."""
    source = es.of(store, plan)
    evidence = source.store
    loops = _zone_loops(plan)
    rows = []
    for n, zone in enumerate(pz.full(z) for z in zones):
        width = pz.width_of(loops, zone["regions"])
        box = pz.box_of(loops, zone["regions"], pz.layer_dpi(plan, zone))[0]
        area = pz.area_of(document, zone["regions"]) - _under(plan, zone["regions"], cut)
        row = {"zone": zone, "number": zone["number"], "index": first + n, "width_mm": width, "area_mm2": area,
               "box": box, "curve": None, "measured": None, "dots": None, "parameters": None, "time": None, "problem": None}
        try:
            if source.frozen is not None:
                raise PredictionError(source.frozen)
            curve = pz.curve(evidence, plan, zone, width)[0]
            p = pz.parameters(evidence, plan, zone, width)
            if pz.dotted(zone):
                row["dots"] = st.dots(evidence, {**zone, "dot_power": p["power"]}, curve)
                row["measured"] = pz.measured_dots(evidence, plan, zone, zone["kind"], p["power"], width)
            row.update(curve=curve, parameters=p, time={**pz.time_layer(plan, zone, document, loops, first + n, p), "area_mm2": area})
        except PredictionError as exc:
            row["problem"] = str(exc)
        rows.append(row)
    return rows


def _first_zone(plan: dict, state: dict) -> int:
    """The layer of the first photo zone: after the cleaning, the markers and the colour layers."""
    return 1 + int(bool(plan["markers_enabled"])) + len(state["layers"])


def _zone_shown(plan: dict, row: dict) -> dict:
    """A photo zone as the editor shows it: its photo engraving (the rules of its parts with their target colours as #rrggbb) and the AI's
    last answers, where it lies, its width and area, the scale's measured span at its width, the dots of a dot kind and whether they are
    estimated, its layer and the address of its picture."""
    zone, curve = row["zone"], row["curve"]
    key = pz.key(plan, zone, curve, row["measured"])
    return {**copy.deepcopy({k: zone[k] for k in ("number", "regions", *pz.SETTINGS, *pz.ANSWERS)}),
            "rules": [st.shown_rule(r) for r in zone["rules"]], "index": row["index"],
            "width_mm": round(row["width_mm"], 2), "area_mm2": round(row["area_mm2"], 2), "box": {k: round(v, 4) for k, v in row["box"].items()},
            "span": None if curve is None else [round(float(v), 2) for v in curve.span], "referenced": None if curve is None else curve.referenced,
            "dots": row["dots"], "estimate": pz.dotted(zone) and row["measured"] is None, "problem": row["problem"],
            "tone_used": st.tone_used(zone) is not None,
            "name": None if row["parameters"] is None else pz.layer_name(row["index"], zone, row["parameters"]),
            "picture": None if row["problem"] else f"/api/vector/{plan['id']}/photo/{zone['number']}.png?v={key[:16]}"}


def _region_list(document: dict, value) -> list[str]:
    if not isinstance(value, list) or not value:
        raise cv.ConversionError("choose one or more regions")
    return list(dict.fromkeys(_region_id(document, v) for v in value))


def _photo_op(store: Store, plan: dict, document: dict, colouring: dict, kind: str, op: dict) -> dict:
    """The photo zones after an operation, on a copy of the colouring that is returned (REQ-073). ``photo_add`` puts ``regions`` into the zone
    ``zone`` or, without one, into a new zone (:func:`photo_zones.new_zone`), taking them out of any other zone and out of the regions left
    out of the file; ``photo_remove`` gives ``regions`` back to their colours; ``photo_set`` changes the photo engraving of the zone ``zone``
    (``kind``, ``scale``, ``min_power``, ``max_power``, ``dot_power``, ``by_colour``, ``colour_choice``, ``contours``, ``rules``,
    ``colouring``: :func:`photo_zones.changed`); ``photo_delete`` gives
    every region of the zone back to its colours. A zone left without a region is gone."""
    zones = copy.deepcopy(pz.zones(colouring))
    loops = _zone_loops(plan)
    try:
        evidence = _ev(store, plan)
        if kind in ("photo_add", "photo_remove"):
            ids = _region_list(document, op.get("regions"))
            chosen = set(ids)
            target = None if kind == "photo_remove" or op.get("zone") is None else pz.find({"photo": zones}, op.get("zone"))
            for zone in zones:
                if zone is not target and chosen & set(zone["regions"]):
                    zone["regions"] = [r for r in zone["regions"] if r not in chosen]
                    if zone["regions"]:
                        pz.settle(evidence, plan, zone, pz.width_of(loops, zone["regions"]))
            if kind == "photo_add":
                if target is None:
                    zones.append(pz.new_zone(evidence, plan, {"photo": zones}, ids, pz.width_of(loops, ids)))
                else:
                    inside = set(target["regions"]) | chosen
                    target["regions"] = [r["id"] for r in document["regions"] if r["id"] in inside]
                    pz.settle(evidence, plan, target, pz.width_of(loops, target["regions"]))
                colouring["excluded_regions"] = [r for r in colouring["excluded_regions"] if r not in chosen]
        elif kind == "photo_set":
            zone = pz.find({"photo": zones}, op.get("zone"))
            changes = {k: v for k, v in op.items() if k not in ("op", "zone")}
            if not changes:
                raise cv.ConversionError("say what to change in the photo zone")
            zones[zones.index(zone)] = pz.changed(evidence, plan, zone, changes, pz.width_of(loops, zone["regions"]))
        else:
            zones.remove(pz.find({"photo": zones}, op.get("zone")))
    except (pz.ZoneError, PredictionError, su.ValidationError) as exc:
        raise cv.ConversionError(str(exc)) from None
    colouring["photo"] = [zone for zone in zones if zone["regions"]]
    return colouring


def _zone_found(store: Store, plan_id: int, number) -> tuple[dict, dict]:
    """The work and the row (:func:`_zone_rows`) of its zone ``number``, numbered as its layer in the file; KeyError when there is no such
    zone."""
    plan = _photo_job(store, plan_id)
    try:
        number = int(number)
        zone = pz.find(plan["colouring"], number)
    except (TypeError, ValueError):
        raise KeyError(f"there is no photo zone {number!r}") from None
    zones = pz.zones(plan["colouring"])
    first = _first_zone(plan, {"layers": plan["layers"]}) + zones.index(zone)
    return plan, _zone_rows(store, plan, _document(plan), [zone], first)[0]


def _zone_of_work(store: Store, plan_id: int, number) -> tuple[dict, dict, dict]:
    """The work, the zone ``number`` with every setting and its row (:func:`_zone_found`); ConversionError when its scale is not measured."""
    plan, row = _zone_found(store, plan_id, number)
    if row["problem"]:
        raise cv.ConversionError(row["problem"])
    return plan, row["zone"], row


def _zone_cut(plan: dict, zone: dict) -> dict:
    """The zone's picture (:func:`photo_zones.cut`) at its layer's DPI, as uploaded: the zone's tone is applied where it is drawn."""
    return pz.cut(plan, _zone_loops(plan), zone, pz.layer_dpi(plan, zone))


def zone_variations(store: Store, plan_id: int, number) -> dict:
    """A photo-variations plate of a photo zone (feature photo-engraving-quality): the part of the zone's picture with the most tone, as the
    work's file engraves it and as large, at the zone's settings and at one change each (``capability_plates.create_variations``)."""
    plan, zone, row = _zone_of_work(store, plan_id, number)
    if es.pin_of(plan) is not None:
        raise su.ValidationError("a variations plate tries settings on this workshop's laser, and this work uses a laboratory release's scale: "
                                 "check the release's settings on this laser with a transfer experiment («Проверить у себя»)")
    found = _zone_cut(plan, zone)
    layer = pz.file_layer(_ev(store, plan), plan, zone, found, 0)
    box, pixels = layer["picture"], layer["picture"]["pixels"]
    made = cp.create_variations(store, plan["device_id"], pz.mode_of(plan, zone).material_id, pixels, pixels.shape[1] / float(box["width"]),
                                layer["parameters"], f"{plan['name']} · zone {zone['number']}",
                                {"kind": "photo_zone", "plan_id": plan["id"], "zone": zone["number"]})
    store.audit("photo_zone_variations", plan_id=plan["id"], zone=zone["number"], variations_plan_id=made["plan_id"], kind=zone["kind"])
    return made


def zone_advice(store: Store, plan_id: int, number) -> dict:
    """What the laboratory knows of a photo zone's kind on the work's laser, lens and the zone's titanium and proposes
    (``photo_knowledge.advice``, feature photo-engraving-quality REQ-004, REQ-005), from the settings its layer engraves at; a zone writes
    no dot width correction."""
    plan, zone, row = _zone_of_work(store, plan_id, number)
    evidence = _ev(store, plan)
    centre = pz.parameters(evidence, plan, zone, _zone_cut(plan, zone)["box"]["width"])
    return pk.advice(evidence, pz.mode_of(plan, zone), centre, dot_width=False, own=es.pin_of(plan) is None)


def zone_picture(store: Store, plan_id: int, number) -> rc.Picture:
    """The photo zone as it will come out, transparent outside it, at preview size (:func:`photo_zones.look`)."""
    plan, zone, row = _zone_of_work(store, plan_id, number)
    return _zone_picture(store, plan, row)


def _zone_picture(store: Store, plan: dict, row: dict) -> rc.Picture:
    zone = row["zone"]

    def draw() -> bytes:
        return pz.to_png(pz.look(_ev(store, plan), plan, zone, _zone_cut(plan, zone), row["curve"])[0])
    return rc.Picture(store, f"vector-{plan['id']}", pz.key(plan, zone, row["curve"], row["measured"]), draw)


def zone_kinds(store: Store, plan_id: int, number) -> dict:
    """«Вид» of a photo zone: every kind that colours titanium with the zone as it would come out in it (the tiles), the one it has
    marked; a dot kind at the zone's dots' power, estimated from the scale until that kind was photographed there."""
    plan, zone, row = _zone_of_work(store, plan_id, number)
    evidence = _ev(store, plan)
    width, curve = row["width_mm"], row["curve"]
    power = ps.dot_power_at(evidence, pz.mode_of(plan, zone), width, zone.get("dot_power"))
    dots = st.dots(evidence, {**zone, "dot_power": power}, curve)
    out = []
    for kind in pz.KINDS:
        measured = pz.measured_dots(evidence, plan, zone, kind, power, width) if kind != pz.GRAYSCALE else None
        shown = {**zone, "kind": kind, "dot_power": power}
        entry = {"key": kind, "family": pz.photo_modes.MODES[kind].family, "basis": pz.photo_modes.MODES[kind].basis,
                 "estimate": kind != pz.GRAYSCALE and measured is None,
                 "picture": f"/api/vector/{plan['id']}/photo/{zone['number']}/kinds/{kind}.png?v="
                            f"{pz.key(plan, shown, curve, measured, px=pz.TILE_PX)[:16]}"}
        if kind == pz.GRAYSCALE:
            entry.update(min_power=zone["min_power"], max_power=zone["max_power"])
        else:
            entry.update(power=dots["power"], hex=dots["hex"], clean_hex=dots["clean_hex"], source=dots["source"])
        out.append(entry)
    return {"zone": zone["number"], "kind": zone["kind"], "kinds": out}


def zone_kind_picture(store: Store, plan_id: int, number, kind: str) -> rc.Picture:
    """The photo zone as it would come out in ``kind`` (:func:`zone_kinds`), the longer side ``photo_zones.TILE_PX``."""
    plan, zone, row = _zone_of_work(store, plan_id, number)
    evidence = _ev(store, plan)
    if kind not in pz.KINDS:
        raise KeyError(f"no kind of engraving {kind!r}")
    power = ps.dot_power_at(evidence, pz.mode_of(plan, zone), row["width_mm"], zone.get("dot_power"))
    shown = {**zone, "kind": kind, "dot_power": power}
    measured = pz.measured_dots(evidence, plan, zone, kind, power, row["width_mm"]) if kind != pz.GRAYSCALE else None

    def draw() -> bytes:
        return pz.to_png(pz.look(evidence, plan, shown, _zone_cut(plan, zone), row["curve"], px=pz.TILE_PX)[0])
    return rc.Picture(store, f"vector-{plan['id']}", pz.key(plan, shown, row["curve"], measured, px=pz.TILE_PX), draw)


# -- a photo zone on its own screen, as a photo work opens (0.23.0, DEC-116) ------------------------------------------------
def zone_view(store: Store, plan_id: int, number) -> dict:
    """A photo zone opened on its own screen as a photo work opens (``photo_work.view``): the zone as the editor shows it, with its scale as
    a mode (the work's laser and lens, the zone's titanium and settings) and its layer's time; the work it belongs to, whose undo and redo
    its changes are steps of, and whether the AI may run and see the picture (the work's permission, DEC-084); the zone's picture beside its
    predicted look with what is said about it, or why there is none (``problem``: its scale is not measured at its width)."""
    plan, row = _zone_found(store, plan_id, number)
    evidence = _ev(store, plan)
    zone = row["zone"]
    mode = pz.mode_of(plan, zone)
    base = f"/api/vector/{plan['id']}/photo/{zone['number']}"
    out = {**_zone_shown(plan, row), "scale": mode.as_dict(), "dpi": pz.layer_dpi(plan, zone),
           "time": None if row["time"] is None else engraving_time.estimate([row["time"]]), "ai_missing": st.ai_missing(),
           "ai_photo": bool(plan.get("ai_photo")),
           "work": {"id": plan["id"], "name": plan["name"], "device_id": plan["device_id"], "lens_id": plan["lens_id"], "material_id": plan["material_id"],
                    "undo": len(plan["undo"]), "redo": len(plan["redo"])}}
    if row["problem"]:
        return {**out, "picture": None}
    found = _zone_cut(plan, zone)
    width = found["box"]["width"]
    sizes = ps.curve_for(evidence, mode, width)[1]["sizes"]
    common = {"scale_size": dict(row["curve"].size), "scale_sizes": sizes, "time": out["time"], "dpi": out["dpi"],
              "size_mm": {"width": round(found["box"]["width"], 2), "height": round(found["box"]["height"], 2)}}
    key = _zone_preview_key(plan, row)
    if pz.dotted(zone):
        state = {**zone, "dot_power": zone["dot_power"] if zone.get("dot_recipe") else row["parameters"]["power"]}
        grey = st.toned(found, state)["picture"]
        rgb8, dots = st.dot_look(evidence, mode, grey, found["alpha"], state, width, row["curve"], row["measured"])
        _keep(store, plan, key, lambda: pz.side_by_side(grey, rgb8, found["alpha"]))
        rows, cols = found["picture"].shape
        out["picture"] = {**common, "kind": zone["kind"], "dots": dots, "estimate": row["measured"] is None, "span": list(row["curve"].span),
                          "shown": {"width": cols, "height": rows}, "preview": f"{base}/preview.png?v={key[:16]}",
                          "closeup": f"{base}/closeup.png?v={key[:16]}", "closeup_mm": ps.CLOSEUP_MM, "closeup_px": ps.CLOSEUP_PX}
        return out
    shown = st.engraved(st.item(evidence, mode, found, zone, f"zone {zone['number']}", width), zone)
    info, rgb8 = ps.predicted(shown, *ps.check_power_range(zone["min_power"], zone["max_power"]))
    _keep(store, plan, key, lambda: pz.side_by_side(shown["picture"], rgb8, found["alpha"]))
    out["picture"] = {**info, **common, "by_colour": zone["by_colour"], "colour_choice": zone["colour_choice"], "contours": zone["contours"],
                      "colour_match": shown.get("colour_match"), "rules_report": shown.get("rules_report"),
                      "contours_report": shown.get("contours_report"), "preview": f"{base}/preview.png?v={key[:16]}"}
    return out


def zone_dot_map(store: Store, plan_id: int, number) -> tuple[Store, str]:
    """The map the colour of a zone's dots is picked on (0.27.0): the measurements of the work's source and its laser and lens as the colour
    map keys them."""
    plan, _ = _zone_found(store, plan_id, number)
    return _ev(store, plan), su.setup_key(*es.setup_of(plan))


def zone_dot_colours(store: Store, plan_id: int, number, points: list[dict]) -> dict:
    """For the colour map picking the colour of a zone's dots, as a photo work's (``photo_work.dot_colours``): the work and the zone (its
    kind, width, laser and lens and titanium) and each colour of the map's ``points`` with what it gives the dots or why it cannot
    (``dot_colours.options`` on the zone's scale at its width)."""
    plan, row = _zone_found(store, plan_id, number)
    evidence = _ev(store, plan)
    zone = row["zone"]
    mode = pz.mode_of(plan, zone)
    material = evidence.one("SELECT id, name, family, grade, batch, thickness_mm FROM material_profile WHERE id=?", (mode.material_id,)) \
        if mode.material_id else None
    return {"work": {"id": plan["id"], "name": plan["name"], "zone": zone["number"], "kind": zone["kind"], "width_mm": round(row["width_mm"], 2),
                     "device_id": mode.device_id, "lens_id": mode.lens_id, "material": dict(material) if material else None,
                     "dot_recipe": zone["dot_recipe"]},
            **dc.options(evidence, mode, row["width_mm"], points)}


def _zone_preview_key(plan: dict, row: dict) -> str:
    return rc.key_of({"kind": "vector-photo-zone-preview", "of": pz.key(plan, row["zone"], row["curve"], row["measured"])})


def _keep(store: Store, plan: dict, key: str, draw) -> None:
    """A picture drawn while its numbers were computed, kept so that the screen's request for it next is not drawn again."""
    if rc.read(store, f"vector-{plan['id']}", key) is None:
        try:
            rc.write(store, f"vector-{plan['id']}", key, pz.to_png(draw()))
        except OSError:
            pass


def zone_preview(store: Store, plan_id: int, number) -> rc.Picture:
    """The zone's picture beside its predicted look (:func:`photo_zones.side_by_side`), at preview size, transparent outside the zone."""
    plan, zone, row = _zone_of_work(store, plan_id, number)

    def draw() -> bytes:
        found = _zone_cut(plan, zone)
        mode, width = pz.mode_of(plan, zone), found["box"]["width"]
        if pz.dotted(zone):
            state = {**zone, "dot_power": zone["dot_power"] if zone.get("dot_recipe") else row["parameters"]["power"]}
            grey = st.toned(found, state)["picture"]
            rgb8 = st.dot_look(_ev(store, plan), mode, grey, found["alpha"], state, width, row["curve"], row["measured"])[0]
            return pz.to_png(pz.side_by_side(grey, rgb8, found["alpha"]))
        shown = st.engraved(st.item(_ev(store, plan), mode, found, zone, f"zone {zone['number']}", width), zone)
        _, rgb8 = ps.predicted(shown, *ps.check_power_range(zone["min_power"], zone["max_power"]))
        return pz.to_png(pz.side_by_side(shown["picture"], rgb8, found["alpha"]))
    return rc.Picture(store, f"vector-{plan['id']}", _zone_preview_key(plan, row), draw)


def zone_closeup(store: Store, plan_id: int, number) -> rc.Picture:
    """The dots of a zone in a dot kind dot for dot from the middle of its box (``prediction_store.dot_closeup``)."""
    plan, zone, row = _zone_of_work(store, plan_id, number)
    if not pz.dotted(zone):
        raise su.ValidationError("a work in grayscale has no dots to show")

    def draw() -> bytes:
        found = _zone_cut(plan, zone)
        dots = row["dots"]
        item = st.item(_ev(store, plan), pz.mode_of(plan, zone), found, zone, f"zone {zone['number']}", found["box"]["width"])
        return prediction.to_png(ps.dot_closeup(item, zone["kind"], dots["lab"], dots["clean_lab"], found["box"]["width"], pz.fired(plan, zone)))
    return rc.Picture(store, f"vector-{plan['id']}", rc.key_of({"kind": "vector-photo-zone-closeup", "of": pz.key(plan, zone, row["curve"], None)}), draw)


def zone_change(store: Store, plan_id: int, number, changes) -> dict:
    """Change the photo engraving of the zone ``number`` from its own screen: one operation ``photo_set`` of the work's colour editor (one
    step of its undo); the zone as it is now (:func:`zone_view`)."""
    if not isinstance(changes, dict):
        raise cv.ConversionError("say what to change in the photo zone")
    colour(store, plan_id, {**{k: v for k, v in changes.items() if k not in ("op", "zone")}, "op": "photo_set", "zone": number})
    return zone_view(store, plan_id, number)


def zone_step(store: Store, plan_id: int, number, direction: str) -> dict:
    """Undo or redo one operation of the work's colour editor from the zone's screen; the zone as it is then, or ``{"gone": true}`` when it
    is not there any more (the step took it away)."""
    colour(store, plan_id, {"op": direction})
    try:
        return zone_view(store, plan_id, number)
    except KeyError:
        return {"gone": True, "work": {"id": int(plan_id)}}


def lasso(store: Store, plan_id: int, points) -> dict:
    """The regions of the current split a lasso drawn through ``points`` (mm) encloses, at least half of each (REQ-073); nothing is changed."""
    plan = _photo_job(store, plan_id)
    document = _document(plan)
    raster = _memo(("labels", plan["document_path"]), lambda: pz.labels(document, _loops_by_region(plan, document)))
    try:
        ids = pz.lasso(document, raster, points)
    except pz.ZoneError as exc:
        raise cv.ConversionError(str(exc)) from None
    return {"version": plan["document_version"], "regions": ids}


def plan_zones(store: Store, plan: dict) -> list[dict]:
    """The photo zones of a vector work as its engraving plan lists them, after its colour layers (REQ-073): each zone's Image layer as the
    editor shows it, with the settings the file gives it (``parameters``; None when its scale is not measured there, ``problem`` says why)."""
    zones = pz.zones(plan.get("colouring")) if plan["mode"] == pl.MODE_VECTOR and plan.get("strategy") == "photo" else []
    if not zones:
        return []
    first = 1 + int(bool(plan["markers_enabled"])) + len(plan["layers"])       # the colour layers stored with the colouring
    return [{**_zone_shown(plan, row), "parameters": row["parameters"]} for row in _zone_rows(store, plan, _document(plan), zones, first)]


def _zone_layers(store: Store, plan: dict, rows: list[dict], cut=None) -> list[dict]:
    """The Image layer of every photo zone for the file (:func:`photo_zones.file_layer`), transparent where the inscriptions ``cut`` it."""
    return [pz.file_layer(_ev(store, plan), plan, row["zone"], _uncut(_zone_cut(plan, row["zone"]), cut), row["index"]) for row in rows]


def _uncut(found: dict, cut) -> dict:
    """A zone's picture (:func:`_zone_cut`) transparent where the inscriptions cut the work (DEC-003): there the file engraves nothing of it."""
    if cut is None or cut.is_empty:
        return found
    cols, rows = found["size"]
    hole = lettering.hole(cut, found["box"], found["px_per_mm"], (cols, rows)).astype(np.float32)
    small = found["alpha"].shape[::-1]
    shown = hole if small == (cols, rows) else cv2.resize(hole, small, interpolation=cv2.INTER_AREA)
    return {**found, "alpha_full": found["alpha_full"] * (1.0 - hole), "alpha": found["alpha"] * (1.0 - shown)}


# -- reading and the file ------------------------------------------------------------------------------------------------------
SHOWN_ENTRY = ("id", "lab", "srgb", "basis", "engravings", "photographs", "parameters", "mode", "time_s_per_cm2", "confidence",
               "expected_delta_e", "stability", "agreement", "caution", "doubtful", "sources")


def _shown(entry: dict, settings: dict) -> dict:
    """A palette colour as the screen shows it, and whether the automatic modes may choose it."""
    return {**{k: entry[k] for k in SHOWN_ENTRY}, "experiments": len(entry["experiments"]), "sizes": entry.get("sizes") or [],
            "size": entry.get("size"), "automatic": palette.automatic(entry, settings["max_time"], settings["include_as_shot"])}


def photo_palette(store: Store, plan_id: int) -> list[dict]:
    """The colours the operator may choose from by hand: every measured colour of the job's laser, lens and titanium."""
    plan = _photo_job(store, plan_id)
    return [_shown(e, plan["colour_settings"]) for e in _palette(store, plan)]


def split_svg(store: Store, plan_id: int) -> str:
    """The current split in its source colours (one path per region, with its id and colour index), borders at the work's smoothing;
    every border also once on its own, with the regions on its sides (the editor outlines a selection with them)."""
    plan = _photo_job(store, plan_id)
    return _memo(("svg", plan["document_path"], float(plan.get("smoothing_mm", 0.0))), lambda: seg.to_svg(_geometry(plan), borders=True))


def smooth(store: Store, plan_id: int, mm) -> None:
    """Set how smooth the borders are, in mm (0: as traced). Only the drawing of the borders changes, not a region or a colour, so
    nothing is reset and nothing is added to the steps of undo; the picture and the file follow it from now on."""
    plan = _photo_job(store, plan_id)
    try:
        value = float(mm)
    except (TypeError, ValueError):
        value = math.nan
    if isinstance(mm, bool) or not math.isfinite(value) or not 0 <= value <= SMOOTHING_MAX_MM:
        raise cv.ConversionError(f"the smoothing must be a number of millimetres from 0 to {SMOOTHING_MAX_MM:g}")
    plan["smoothing_mm"] = round(value, 3)
    document = _document(plan)
    with store.transaction():
        _photo_refresh(store, plan, document, _palette(store, plan))


def _attention(plan: dict, state: dict, entries: list[dict], settings: dict) -> dict | None:
    """The layers whose titanium colour moved since the last file promised it (DEC-090); None for a work never exported."""
    baseline, approximate = work_review.baseline_of(plan)
    if baseline is None:
        return None
    return work_review.drift(baseline, state["colours"], state["by_id"], palette.choosable(entries, settings["max_time"], settings["include_as_shot"])[0],
                             {layer["entry_id"] for layer in state["layers"]}, approximate)


def _used(state: dict, colouring: dict) -> set[str]:
    """The titanium colours a photograph job uses: of its colours, its regions and its inscriptions."""
    by_id = state["by_id"]
    return ({c["entry_id"] for c in state["colours"] if c["entry_id"]} | {e for e in colouring["regions"].values() if e in by_id}
            | {t[k] for t in _texts(colouring) for k in lettering.ENTRIES if t[k] in by_id})


def source_change(store: Store, plan_id: int, request: dict | None, confirm: bool = False) -> dict:
    """Update the source of a photograph job pinned to a laboratory release (feature electron REQ-085), an explicit step: to the release
    ``request`` names (by default the current release of its laboratory with the same laser, lens and titanium), or back to the source it
    had before (``{"back": true}``). Without ``confirm`` nothing changes and the preview says what would: each colour the job uses with
    its colour before and after and their ΔE or that it is not measured there any more, and every photo zone whose scale the new source
    does not measure. Confirmed, the job keeps its choices (a colour gone is shown missing), records the step in its history and keeps the
    earlier source to go back to."""
    plan = _photo_job(store, plan_id)
    back = isinstance(request, dict) and bool(request.get("back"))
    new = es.previous_pin(plan) if back else es.next_pin(store, plan, request)
    trial = {**plan, "evidence_source": new}
    document = _document(plan)
    before, after = _palette(store, plan), _palette(store, trial)
    state = _state(plan, document, before, _inscribed(store, plan, before))
    zones = []
    for row in _zone_rows(store, trial, document, state["zones"], _first_zone(plan, state), state["cut"]):
        zones.append({"zone": row["number"], "problem": row["problem"]})
    preview = {"from": es.shown(store, plan), "to": es.summary(store, new), "back": back, **es.compared(before, after, _used(state, plan["colouring"])),
               "zones": zones}
    if not confirm:
        return preview
    plan["source_versions"] = es.moved(plan, new, back)
    plan["evidence_source"] = new if back else {**new, **_kept(store, trial, after)}
    plan["history"].append({"version": plan["document_version"], "op": {"op": "source", "release_id": new["release_id"], "back": back}, "at": now()})
    with store.transaction():
        _photo_refresh(store, plan, document, after)
        store.audit("vector_work_source", plan_id=plan["id"], release_id=new["release_id"], back=back)
    return preview


def photo_view(store: Store, plan: dict) -> dict:
    """A photograph job as its screen shows it: the split's settings, counts and important areas, every source colour
    with its titanium colour and status, the colours beyond the tolerance (``outside``) and the regions whose colour is no
    longer measured (``missing``), the variants with the split version of each, the steps to undo and redo, the layers of
    the file with the estimated time of the whole job, and the exported files. The geometry itself is in :func:`split_svg`."""
    document = _document(plan)
    entries = _palette(store, plan)
    state = _state(plan, document, entries, _inscribed(store, plan, entries))
    by_id, colouring, settings = state["by_id"], plan["colouring"], plan["colour_settings"]
    used = _used(state, colouring)
    layers = _export_layers(store, plan, state)
    zones = _zone_rows(store, plan, document, state["zones"], _first_zone(plan, state), state["cut"])
    hidden = ("document_path", "history", "exports", "undo", "redo", "variants", "colouring", "detected", "regions", "weak", "layers",
              "unresolved", "ai_photo", "counts", "evidence_source", "source_versions")
    out = {k: v for k, v in plan.items() if k not in hidden}
    found = plan["detected"]
    out.update(
        strategy=PHOTO, source=es.shown(store, plan),
        split={**plan["split"], "algorithm": plan["split"].get("algorithm", seg.DEFAULT_ALGORITHM),   # made before the choice: slic
               "adjusted": plan["split"].get("adjusted", [])},                                       # made before 0.28.0: none
        document={**{k: document[k] for k in ("size_mm", "px_mm", "image_px", "n_colors", "min_area_mm2", "tolerance_mm", "superpixels",
                                               "faces")},
                  "algorithm": document.get("algorithm", seg.DEFAULT_ALGORITHM), "version": plan["document_version"], "colours": len(document["palette"]), "regions": len(document["regions"]),
                  "important_regions": sum(r["important"] for r in document["regions"])},
        areas={"detected": [{**a, "number": i, "removed": i in plan["split"]["removed"]} for i, a in enumerate(found["areas"])],   # as found
               "faces": found["faces"], "search_failed": found["error"] is not None},
        colours=state["colours"], entries={i: _shown(by_id[i], settings) for i in sorted(used)},
        colouring={**{k: colouring[k] for k in ("mode", "seed", "variant", "regions", "excluded_colours", "excluded_regions")},
                   **({"ai": colouring["ai"]} if colouring.get("ai") else {})},
        settings={"tolerance_de": plan["threshold"], **settings},
        outside=state["outside"], missing={"regions": len(state["missing_regions"])}, totals=state["totals"],
        variants=[{**{k: v[k] for k in ("number", "mode", "seed", "at", "totals")}, "version": v.get("version", plan["document_version"]),
                   "restorable": _restorable(plan, document, v),
                   **({"ai": v["colouring"]["ai"]} if v["colouring"].get("ai") else {}),
                   **({"subset": v["subset"]} if v.get("subset") else {})} for v in plan["variants"]],
        ai={"available": _ai_missing() is None, "missing": _ai_missing(), "styles": list(ai.STYLES), "photo_allowed": bool(plan.get("ai_photo")),
            "photo_px": ai.PHOTO_PX, "max_text": ai.MAX_TEXT},
        undo=len(plan["undo"]), redo=len(plan.get("redo", [])),
        layers=[{k: v for k, v in layer.items() if k not in ("region_ids", "layer_keys")} | {"regions": layer["region_ids"]} for layer in layers],
        zones=[_zone_shown(plan, row) for row in zones], zone_kinds=list(pz.KINDS),
        texts=[lettering.shown_row(row, by_id) for row in state["texts"]], text_defaults=lettering.DEFAULTS,
        time=_estimate(plan, layers, zones), export_blocked=_blocker_photo(plan, state, zones), layer_cap=photo_cap(plan["markers_enabled"]),
        palette_size=len(entries), smoothing_mm=plan.get("smoothing_mm", 0.0), smoothing_max_mm=SMOOTHING_MAX_MM,
        history=[{k: h[k] for k in ("version", "op", "at")} for h in plan["history"]],
        exports=[{k: e.get(k) for k in ("number", "name", "at", "document_version", "layers", "regions", "variant", "seconds")}
                 for e in plan["exports"]],
        attention=_attention(plan, state, entries, settings),
        reviews=work_review.newest_first(plan.get("reviews") or []))
    return out


def _photo_export(store: Store, plan: dict) -> tuple[str, bytes]:
    """The LightBurn file of a photograph job: cleaning first, one layer per recipe with its complete settings, every
    region a closed Path made of the shared borders with its holes (REQ-043); kept in the job with the colouring it came from."""
    document = _document(plan)
    entries = _palette(store, plan)
    state = _state(plan, document, entries, _inscribed(store, plan, entries))
    zones = _zone_rows(store, plan, document, state["zones"], _first_zone(plan, state), state["cut"])
    blocker = _blocker_photo(plan, state, zones)
    if blocker is not None:
        raise cv.ConversionError(blocker)
    layers = _export_layers(store, plan, state)
    pictures = _zone_layers(store, plan, zones, state["cut"])
    if es.pin_of(plan) is not None:              # the release's settings on the own laser (feature electron REQ-085)
        es.own_limits(store, plan["device_id"], [(layer["name"], layer["parameters"]) for layer in layers + pictures])
    key = {region: layer["layer_keys"][0] for layer in layers for region in layer["region_ids"]}
    regions = []
    for r in seg.regions_as_loops(_joined(_geometry(plan), {k: v for k, v in key.items() if k not in state["trimmed"]})):
        if r["id"] not in key:
            continue
        if r["id"] in state["trimmed"]:          # cut by an inscription: what is left of it, as straight pieces
            regions += [{"id": r["id"], "loops": shape, "strokes": [], "layer_key": key[r["id"]]} for shape in state["trimmed"][r["id"]]["shapes"]]
        else:
            regions.append({**r, "layer_key": key[r["id"]]})
    for entry_id, found in state["text_shapes"].items():        # the letters and backings on the layer of their colour
        regions += [{"id": None, "loops": shape, "strokes": [], "layer_key": f"e{entry_id}"} for part in found for shape in lettering.shapes(part)]
    plan["export_mirror_y"] = EXPORT_MIRROR_Y
    data = pl.export_lbrn2({**plan, "layers": layers + pictures, "vector_document": {"regions": regions}})
    path = store.data_dir / "files" / f"vector-export-{uuid.uuid4().hex[:12]}.lbrn2"
    path.write_bytes(data)
    plan["layers"] = layers
    plan.pop("unresolved", None)
    plan["exports"].append({"number": len(plan["exports"]) + 1, "name": plan["name"] + ".lbrn2", "path": str(path), "at": now(),
                            "document_version": plan["document_version"], "layers": len(layers) + len(zones), "regions": len(regions),
                            "variant": plan["colouring"]["variant"], "colouring": copy.deepcopy(plan["colouring"]),
                            "smoothing_mm": plan.get("smoothing_mm", 0.0), "seconds": _estimate(plan, layers, zones)["seconds"],
                            "promised": work_review.promised_layers(layers),       # what this file shows in the preview (DEC-090)
                            "zones": [{**copy.deepcopy(row["zone"]), "index": row["index"], "name": pz.layer_name(row["index"], row["zone"], row["parameters"]),
                                       "parameters": row["parameters"]} for row in zones]})
    cv._persist(store, plan, ST_EXPORTED, plan["markers_enabled"])
    return plan["name"], data


def _joined(geometry: dict, layer_of: dict[str, str]) -> dict:
    """The split as the file writes it (feature vector-detail-and-colour-control, I-7, its DEC-090): every set of regions on one layer (``layer_of``,
    region id to layer key) connected through shared borders is one region, its inner borders dropped and its holes kept
    (:func:`segment.merge_groups`); a touch at a corner only joins nothing. The stored split, the editor, the undo steps and the variants
    keep every region, so painting one of them again, or undoing the colouring, gives the borders back."""
    near = seg.neighbours(geometry)
    parent = {r: r for r in layer_of}

    def root(r: str) -> str:
        while parent[r] != r:
            parent[r] = parent[parent[r]]
            r = parent[r]
        return r

    for r, layer in layer_of.items():
        for other in near.get(r, ()):
            if layer_of.get(other) == layer:
                parent[root(other)] = root(r)
    groups: dict[str, list[str]] = {}
    for r in layer_of:
        groups.setdefault(root(r), []).append(r)
    joined = [g for g in groups.values() if len(g) > 1]
    return seg.merge_groups(geometry, joined, strict=False)[0] if joined else geometry


# -- the colour editor: checks ---------------------------------------------------------------------------------------------
def _colour_index(document: dict, value) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or not any(p["index"] == value for p in document["palette"]):
        raise cv.ConversionError("there is no such source colour")
    return str(value)


def _region_id(document: dict, value) -> str:
    if not any(r["id"] == value for r in document["regions"]):
        raise cv.ConversionError(f"there is no region {value!r}")
    return value


def _entry_id(by_id: dict, value) -> str:
    if not isinstance(value, str) or value not in by_id:
        raise cv.ConversionError("the titanium colour must be a measured colour of this laser, lens and titanium stock")
    return value


def _similarity(value) -> float:
    """The similarity of a fill: a delta E between source colours, given as a number or as text (a query parameter)."""
    try:
        number = math.nan if isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number) or number < 0:
        raise cv.ConversionError("the similarity must be a non-negative delta E")
    return number


def _colour_set(document: dict, value) -> list[int]:
    """Source colours to merge: two or more of the split."""
    if not isinstance(value, list):
        raise cv.ConversionError("choose two or more source colours to merge")
    indexes = list(dict.fromkeys(int(_colour_index(document, v)) for v in value))
    if len(indexes) < 2:
        raise cv.ConversionError("choose two or more source colours to merge")
    return indexes


def _merge_set(document: dict, value) -> list[str]:
    """Regions to merge: two or more of the split, connected through shared borders (a touch at a corner is none)."""
    if not isinstance(value, list):
        raise cv.ConversionError("choose two or more regions to merge")
    ids = list(dict.fromkeys(_region_id(document, v) for v in value))
    if len(ids) < 2:
        raise cv.ConversionError("choose two or more regions to merge")
    near, wanted = seg.neighbours(document), set(ids)
    reached, queue = {ids[0]}, [ids[0]]
    while queue:
        found = (near[queue.pop()] & wanted) - reached
        reached |= found
        queue += sorted(found)
    if reached != wanted:
        raise cv.ConversionError("the regions to merge must border one another")
    return ids


# -- the colour editor: undo and redo (editor DEC-077) ----------------------------------------------------------------------
def _here(plan: dict) -> dict:
    """What a step of undo or redo brings back: the colouring with its split version, delta E tolerance and filters."""
    return {"colouring": copy.deepcopy(plan["colouring"]), "version": plan["document_version"], "threshold": plan["threshold"],
            "colour_settings": copy.deepcopy(plan["colour_settings"])}


def _snapshot(plan: dict) -> None:
    """Before an operation: the job as it is can be undone (the last UNDO_DEPTH steps), what was undone is not redone any more."""
    plan["undo"], plan["redo"] = (plan["undo"] + [_here(plan)])[-UNDO_DEPTH:], []


def _step(store: Store, plan: dict, direction: str) -> None:
    """Undo or redo one operation: the state on top of that stack comes back and the present one goes onto the other."""
    if not plan[direction]:
        raise cv.ConversionError("there is no earlier colouring to go back to" if direction == "undo" else "there is no undone change to redo")
    there = plan[direction].pop()
    plan["redo" if direction == "undo" else "undo"].append(_here(plan))
    _go(store, plan, there)


def _go(store: Store, plan: dict, there: dict) -> None:
    """Bring a state back; one of another split version brings that version's document back from the history, and the work's size
    and markers with it when the version was made by a size change (work-size-and-splitting-a-region-again, DEC-001)."""
    if there["version"] != plan["document_version"]:
        entry = next((h for h in plan["history"] if h.get("path") and h["version"] == there["version"]), None)
        if entry is None or not Path(entry["path"]).is_file():
            raise cv.ConversionError("there is no such version of the vector document")
        plan["document_version"], plan["document_path"] = entry["version"], entry["path"]
        size = _document(plan)["size_mm"]
        if not _same_size(size, plan["size_mm"]):
            _resized(store, plan, size)
    plan["colouring"], plan["threshold"] = copy.deepcopy(there["colouring"]), there["threshold"]
    plan["colour_settings"] = copy.deepcopy(there["colour_settings"])


def _pin_legacy(plan: dict) -> None:
    """Works made before the editor kept bare colourings to undo and variants without a split version: both belong to the
    current version (editor DEC-077), with the tolerance and filters in force now."""
    here = {"version": plan["document_version"], "threshold": plan["threshold"], "colour_settings": plan["colour_settings"]}
    plan["undo"] = [e if "colouring" in e else {"colouring": e, **copy.deepcopy(here)} for e in plan.get("undo", [])]
    plan.setdefault("redo", [])
    for v in plan["variants"]:
        v.setdefault("version", plan["document_version"])


# -- the colour editor: operations ---------------------------------------------------------------------------------------------
def colour(store: Store, plan_id: int, op: dict) -> None:
    """One operation of the colour editor, recorded in the history; every one but ``undo`` and ``redo`` can be undone, and
    a new one clears what was undone (editor DEC-077).

    ``{"op": "assign", "mode", "subset"?}`` recolours automatically (closest, tonality, contrast; random and artistic with a new seed each
    time, artistic within a ``subset`` of the palette: all, warm, cool or bright) and
    adds a variant; ``{"op": "ai_colour", "style", "text"?, "free_lightness"?}`` lets the language model choose the colours
    in a style (:func:`_ai_colour`) and adds a variant; ``{"op": "restore", "variant"}`` brings back one made on the current version of the split;
    ``{"op": "settings", "tolerance_de", "max_time", "include_as_shot"}`` changes the choice and recolours with the current
    mode. ``{"op": "paint", "region", "scope", "entry_id", "similarity_de"}`` is a click of the brush (:func:`_paint`);
    ``{"op": "set_colour", "colour", "entry_id"}`` chooses a colour's titanium colour by hand (null returns to the automatic
    choice; one area is painted with ``paint``); ``exclude_colour``, ``include_colour`` and ``exclude_region``, ``include_region`` (one
    ``region`` or several ``regions``) leave them out of the file or bring them back. ``{"op": "merge_titanium", "entries",
    "into"}`` makes titanium colours one (:func:`_merge_titanium`); ``{"op": "merge_colours", "colours", "entry_id"?}`` and
    ``{"op": "merge_regions", "regions"}`` make a new version of the split (:func:`_merge`). ``undo`` and ``redo`` step
    back and forth through all of them, the split version, the tolerance and the filters included.
    """
    if not isinstance(op, dict):
        raise cv.ConversionError("an edit must name its operation")
    plan, kind = _photo_job(store, plan_id), op.get("op")
    if kind not in COLOURING_OPS:
        raise cv.ConversionError(f"unknown edit operation {kind!r}")
    _pin_legacy(plan)
    document = _document(plan)
    _key_variants(plan, document)
    entries = _palette(store, plan)
    if kind in ("undo", "redo"):
        _step(store, plan, kind)
        document = _document(plan)
        _key_variants(plan, document)                # back on an earlier version: its old variants get the key too
    elif kind in MERGE_OPS:
        merged, colouring, keeper = _merge(plan, document, entries, kind, op)
        _snapshot(plan)
        plan["colouring"], document = colouring, merged
    else:
        changes = _change(store, plan, document, entries, kind, op)
        _snapshot(plan)
        plan.update(changes)
        if kind in ("assign", "settings", "ai_colour"):
            _add_variant(store, plan, document, entries)
    with store.transaction():
        if kind in MERGE_OPS:                    # the new version is the history's entry of the operation
            _new_version(store, plan, document, {**op, "keeper": keeper})
        else:
            plan["history"].append({"version": plan["document_version"], "op": op, "at": now()})
        _photo_refresh(store, plan, document, entries)


def _change(store: Store, plan: dict, document: dict, entries: list[dict], kind: str, op: dict) -> dict:
    """The job's colouring (and for ``settings`` its tolerance and filters) after an operation that keeps the split,
    computed without changing the job, so that a refused operation leaves nothing behind."""
    current = plan["colouring"]
    if kind == "assign":
        mode = op.get("mode")
        if mode not in palette.MODES:
            raise cv.ConversionError("the recolouring mode must be closest, tonality, random, contrast or artistic")
        if mode == "artistic" and op.get("subset", "all") not in palette.SUBSETS:
            raise cv.ConversionError("the group of colours must be all, warm, cool or bright")
        seeded = mode in ("random", "artistic")              # a new arrangement each time, the earlier ones kept as variants
        seed = 1 + max((v["seed"] for v in plan["variants"] if v["mode"] == mode), default=0) if seeded else 0
        return {"colouring": _automatic(plan, document, entries, mode, seed, {**current, "subset": op.get("subset", "all")})}
    if kind == "ai_colour":
        return {"colouring": _ai_colour(store, plan, document, entries, op)}
    if kind == "restore":
        variant = next((v for v in plan["variants"] if v["number"] == op.get("variant")), None)
        if variant is None:
            raise cv.ConversionError("there is no such variant of the colouring")
        if not _restorable(plan, document, variant):
            raise cv.ConversionError("this variant of the colouring belongs to another version of the split")
        return {"colouring": {**copy.deepcopy(variant["colouring"]), "photo": copy.deepcopy(pz.zones(current)),        # the zones and the
                              "texts": copy.deepcopy(_texts(current))}}                                                # inscriptions stay
    if kind == "settings":
        settings = {"max_time": colormap.time_limit(op.get("max_time")), "include_as_shot": bool(op.get("include_as_shot"))}
        threshold = cv._threshold(store, plan["device_id"], plan["lens_id"], op.get("tolerance_de", plan["threshold"]))
        ruled = {**plan, "threshold": threshold, "colour_settings": settings}
        return {"threshold": threshold, "colour_settings": settings,
                "colouring": _automatic(ruled, document, entries, current["mode"] or "closest", current["seed"], current)}
    if kind in PHOTO_OPS:
        return {"colouring": _photo_op(store, plan, document, copy.deepcopy(current), kind, op)}
    if kind in TEXT_OPS:
        return {"colouring": _text_op(store, plan, entries, copy.deepcopy(current), op)}
    return {"colouring": _choose(copy.deepcopy(current), plan, document, entries, kind, op)}


def _ai_colour(store: Store, plan: dict, document: dict, entries: list[dict], op: dict) -> dict:
    """The colouring after the model chose a measured colour for every source colour the operator has not decided (REQ-050, DEC-084),
    computed without changing the job. The operator's own choices of colours stay, excluded colours are left out of what the model sees,
    and an answer that breaks a rule of :mod:`ai_colouring` is refused here, so that nothing is left behind. The model sees numbers only;
    a reduced photograph goes with them only when the operator allowed it for this work (:func:`allow_photo`)."""
    style, text, free_lightness = ai.request(op)
    if not research.ai_available():
        raise cv.ConversionError("the AI colouring is off: no key for the language model is set (OPENAI_API_KEY)")
    try:
        client = research.openai_client()
    except Exception:                        # a missing or broken library: its own text names paths and is of no use to the operator
        raise cv.ConversionError("the AI could not be started on this computer: a library it needs is missing or broken, install the app's dependencies (see README)") from None
    settings, current = plan["colour_settings"], plan["colouring"]
    candidates = palette.choosable(entries, settings["max_time"], settings["include_as_shot"])[0]
    if not candidates:
        raise cv.ConversionError("no measured colour of this titanium may be chosen with the present limits: widen them to colour with AI")
    by_id = {e["id"]: e for e in candidates}
    all_ids = {e["id"] for e in entries}
    indexes = {str(p["index"]) for p in document["palette"]}
    fixed = {i: g["entry_id"] for i, g in current["groups"].items() if g["entry_id"] in all_ids and i in indexes}
    excluded = set(current["excluded_colours"])
    free = [p for p in document["palette"] if str(p["index"]) not in fixed and p["index"] not in excluded]
    if not free:
        raise cv.ConversionError("every colour of the picture is chosen by hand or left out: there is nothing for the AI to colour")
    base = _automatic(plan, document, entries, "closest", 0, current)          # what the model does not decide: left-out colours
    inscribed = _inscribed(store, plan, entries)
    total = sum(p["pixels"] for p in document["palette"]) or 1
    sources = [{"index": p["index"], "lab": [round(v, 1) for v in p["lab"]], "share": round(p["pixels"] / total, 4)} for p in free]
    cap = photo_cap(plan["markers_enabled"]) - len(pz.zones(current))          # each photo zone takes a layer of its own
    what = ai.brief(style, text, free_lightness, free=sources, fixed=fixed, touches=ai.touching(document), palette=candidates, max_recipes=cap)
    photo = ai.photo_data_url(Path(plan["image_path"]).read_bytes()) if plan.get("ai_photo") else None

    def recipes(chosen: dict) -> int:
        trial = {**copy.deepcopy(base), "mode": "ai", "assignment": {**base["assignment"], **{str(i): e for i, e in chosen.items()}}}
        return len(_state({**plan, "colouring": trial}, document, entries, inscribed)["layers"])

    def check(answer) -> dict:
        return ai.validate(answer, free={s["index"] for s in free}, palette=by_id, lightness={s["index"]: s["lab"][0] for s in free},
                           keep_order=not free_lightness, max_recipes=cap, recipes=recipes)

    chosen, note = ai.choose(client, what, photo, check)
    out = copy.deepcopy(base)
    out.update(mode="ai", seed=0)
    out["assignment"].update({str(i): e for i, e in chosen.items()})
    out["how"].update({str(i): "ai" for i in chosen})
    out["ai"] = {"style": style, "text": text, "free_lightness": free_lightness, "photo": photo is not None, "note": note}
    return out


def _ai_missing() -> str | None:
    """Why the AI colouring cannot run on this computer: ``library`` (the client library is not installed), ``key`` (no key is set) or None."""
    if not research.ai_library():
        return "library"
    return None if research.ai_available() else "key"


def allow_photo(store: Store, plan_id: int, allowed) -> None:
    """Allow or forbid sending a reduced copy of this work's photograph to the language model with its numbers (DEC-084). The work
    remembers the answer; the history records it. It is not a step of undo and changes no colour."""
    plan = _photo_job(store, plan_id)
    if not isinstance(allowed, bool):
        raise cv.ConversionError("the permission to send the photograph must be on or off")
    plan["ai_photo"] = allowed
    plan["history"].append({"version": plan["document_version"], "op": {"op": "ai_photo", "allowed": allowed}, "at": now()})
    document = _document(plan)
    with store.transaction():
        _photo_refresh(store, plan, document, _palette(store, plan))


def _choose(colouring: dict, plan: dict, document: dict, entries: list[dict], kind: str, op: dict) -> dict:
    """The operator's own choices on a copy of the colouring, which is returned (or the colouring an automatic mode makes of
    it when a choice goes back to the automatic one): a colour or a region by hand, a click of the brush, titanium colours
    merged, exclusions."""
    by_id = {e["id"]: e for e in entries}
    if kind == "set_colour":
        key = _colour_index(document, op.get("colour"))
        if op.get("entry_id") is None:
            colouring["groups"].pop(key, None)
            return _automatic(plan, document, entries, colouring["mode"] or "closest", colouring["seed"], colouring)
        colouring["groups"][key] = {"entry_id": _entry_id(by_id, op["entry_id"]), "by": "hand"}
    elif kind == "paint":
        return _paint(colouring, plan, document, entries, op)
    elif kind == "merge_titanium":
        _merge_titanium(colouring, by_id, op)
    elif kind in ("exclude_colour", "include_colour"):
        index = int(_colour_index(document, op.get("colour")))
        colouring["excluded_colours"] = sorted(set(colouring["excluded_colours"]) - {index} | ({index} if kind == "exclude_colour" else set()))
    else:
        ids = op["regions"] if "regions" in op else [op.get("region")]
        if not isinstance(ids, list) or not ids:
            raise cv.ConversionError(f"there is no region {ids!r}")
        chosen = {_region_id(document, region) for region in ids}
        colouring["excluded_regions"] = sorted(set(colouring["excluded_regions"]) - chosen | (chosen if kind == "exclude_region" else set()))
        if kind == "exclude_region":                 # a region left out of the file is not engraved by its photo zone either
            colouring["photo"] = [z for z in ({**z, "regions": [r for r in z["regions"] if r not in chosen]} for z in pz.zones(colouring))
                                  if z["regions"]]
    return colouring


def _paint(colouring: dict, plan: dict, document: dict, entries: list[dict], op: dict) -> dict:
    """A click of the brush (editor REQ-045) with a titanium colour, or null for the automatic choice. Scope ``region``
    paints the clicked region; ``colour`` its whole source colour, the own colours of the regions inside it cleared (null:
    the colour goes back to the automatic choice); ``fill`` every region :func:`_reach` finds from it. A region or colour
    painted with a titanium colour is included again, and with the scope ``colour`` so is every region of the colour that
    was excluded one by one (editor DEC-079), as the hover outlines them. A region painted with the scope ``region`` or ``fill`` leaves
    its photo zone (REQ-073: the brush gives it a colour); the scope ``colour`` leaves the zones as they are. With the scope ``region``,
    ``regions`` (a list) paints every region of the editor's selection in one step instead of the one ``region``."""
    scope, entry = op.get("scope"), op.get("entry_id")
    if scope not in SCOPES:
        raise cv.ConversionError("the scope must be region, colour or fill")
    many = op.get("regions") if scope == "region" and "regions" in op else None
    if many is not None and (not isinstance(many, list) or not many):
        raise cv.ConversionError("choose the regions to paint")
    region = None if many is not None else _region_id(document, op.get("region"))
    if entry is not None:
        _entry_id({e["id"]: e for e in entries}, entry)
    if scope == "colour":
        index = next(r["color"] for r in document["regions"] if r["id"] == region)
        inside = {r["id"] for r in document["regions"] if r["color"] == index}
        colouring["regions"] = {k: v for k, v in colouring["regions"].items() if k not in inside}
        if entry is None:
            colouring["groups"].pop(str(index), None)
            return _automatic(plan, document, entries, colouring["mode"] or "closest", colouring["seed"], colouring)
        colouring["groups"][str(index)] = {"entry_id": entry, "by": "hand"}
        colouring["excluded_colours"] = [i for i in colouring["excluded_colours"] if i != index]
        painted = inside
    else:
        painted = ({_region_id(document, r) for r in many} if many is not None else {region} if scope == "region"
                   else set(_reach(document, colouring, region, _similarity(op.get("similarity_de")))))
        colouring["photo"] = [z for z in ({**z, "regions": [r for r in z["regions"] if r not in painted]} for z in pz.zones(colouring))
                              if z["regions"]]
        for r in painted:
            if entry is None:
                colouring["regions"].pop(r, None)
            else:
                colouring["regions"][r] = entry
    if entry is not None:
        colouring["excluded_regions"] = [r for r in colouring["excluded_regions"] if r not in painted]
    return colouring


def _reach(document: dict, colouring: dict, region: str, similarity: float) -> list[str]:
    """The regions a fill from ``region`` paints, in the document's order (editor REQ-045): breadth first over shared
    borders, a neighbour joins when its source colour lies within ``similarity`` delta E of the clicked region's (never
    of the region it was reached from); excluded regions, regions of excluded colours and of photo zones stop it, the clicked one aside."""
    excluded_colours = set(colouring["excluded_colours"])
    walls = (set(colouring["excluded_regions"]) | {r["id"] for r in document["regions"] if r["color"] in excluded_colours}
             | set(pz.zone_of(colouring)))
    walls.discard(region)
    lab = {r["id"]: r["lab"] for r in document["regions"]}
    near, seen, queue = seg.neighbours(document), {region}, collections.deque([region])
    reached = {region}
    while queue:
        for other in sorted(near[queue.popleft()] - seen - walls):
            seen.add(other)
            if color.delta_e(lab[other], lab[region]) <= similarity:
                reached.add(other)
                queue.append(other)
    return [r["id"] for r in document["regions"] if r["id"] in reached]


def reach(store: Store, plan_id: int, region, similarity_de) -> dict:
    """What a click of the brush with the fill scope would paint on the current split, found as the paint finds it
    (:func:`_reach`); nothing is changed. ``similarity_de`` may come as text, as a query parameter does."""
    plan = _photo_job(store, plan_id)
    document = _document(plan)
    start, similarity = _region_id(document, region), _similarity(similarity_de)
    ids = _reach(document, plan["colouring"], start, similarity)
    inside = set(ids)
    pixels = sum(r["pixels"] for r in document["regions"] if r["id"] in inside)
    return {"region": start, "similarity_de": similarity, "version": plan["document_version"], "regions": ids, "pixels": pixels,
            "share": pixels / (sum(p["pixels"] for p in document["palette"]) or 1)}


def neighbours(store: Store, plan_id: int) -> dict:
    """Which regions border which on the current split, as merging finds it (:func:`segment.neighbours`: across a shared
    arc, never at a corner only), for every region in the document's order; nothing is changed. The screen asks once per
    split version to offer the merge of regions only for a connected selection (editor DEC-080)."""
    plan = _photo_job(store, plan_id)
    near = seg.neighbours(_document(plan))
    return {"version": plan["document_version"], "neighbours": {rid: sorted(others) for rid, others in near.items()}}


def _merge_titanium(colouring: dict, by_id: dict, op: dict) -> None:
    """Titanium colours into one (editor REQ-046, DEC-078): every colour and region whose titanium colour is one of ``entries``
    (by hand or automatically) takes ``into`` by hand, so the file has one layer fewer for each; the automatic modes keep it.
    ``entries`` are two or more distinct colours the colouring uses; ``into`` is any measured colour, selected or not."""
    into, entries = _entry_id(by_id, op.get("into")), op.get("entries")
    used = ({g["entry_id"] for g in colouring["groups"].values()} | set(colouring["regions"].values())
            | set(colouring["assignment"].values()))
    chosen = set(entries) if isinstance(entries, list) and all(isinstance(e, str) for e in entries) else set()
    if len(chosen) < 2 or not chosen <= used:
        raise cv.ConversionError("choose two or more titanium colours of the colouring to merge")
    away = chosen - {into}
    for key, entry_id in colouring["assignment"].items():
        if key not in colouring["groups"] and entry_id in away:
            colouring["groups"][key] = {"entry_id": into, "by": "hand"}
    for key, group in list(colouring["groups"].items()):
        if group["entry_id"] in away:
            colouring["groups"][key] = {"entry_id": into, "by": "hand"}
    colouring["regions"] = {region: into if entry_id in away else entry_id for region, entry_id in colouring["regions"].items()}


def _merge(plan: dict, document: dict, entries: list[dict], kind: str, op: dict) -> tuple[dict, dict, int | str]:
    """Source colours or neighbouring regions merged into a new split (editor REQ-047, REQ-048), computed without changing
    the job: the new document, the colouring carried over to it and the colour index or region id that is left. The
    choices and exclusions of a merged-away colour or region are dropped, the one left keeps its own; ``entry_id`` gives
    merged colours a titanium colour by hand."""
    colouring = copy.deepcopy(plan["colouring"])
    if kind == "merge_colours":
        indexes, entry = _colour_set(document, op.get("colours")), op.get("entry_id")
        if entry is not None:
            _entry_id({e["id"]: e for e in entries}, entry)
        merged, keeper = seg.merge_colours(document, indexes)
        if entry is not None:
            colouring["groups"][str(keeper)] = {"entry_id": entry, "by": "hand"}
    else:
        ids = _merge_set(document, op.get("regions"))
        merged, keeper = seg.merge_regions(document, ids)
        away = set(ids) - {keeper}
        colouring["regions"] = {k: v for k, v in colouring["regions"].items() if k not in away}
        colouring["excluded_regions"] = [r for r in colouring["excluded_regions"] if r not in away]
        sizes = {r["id"]: r["pixels"] for r in document["regions"] if r["id"] in set(ids)}
        for zone in pz.zones(colouring):                     # the region left is in a photo zone that held half of it or more
            held = sum(sizes[r] for r in zone["regions"] if r in sizes)
            inside = set(zone["regions"]) - set(ids) | ({keeper} if 2 * held >= sum(sizes.values()) else set())
            zone["regions"] = [r["id"] for r in merged["regions"] if r["id"] in inside]
    left = {p["index"] for p in merged["palette"]}           # a colour merged away, or left without a region
    for part in ("groups", "assignment", "how"):
        colouring[part] = {k: v for k, v in colouring[part].items() if int(k) in left}
    colouring["excluded_colours"] = [i for i in colouring["excluded_colours"] if i in left]
    colouring["photo"] = [z for z in pz.zones(colouring) if z["regions"]]
    return merged, colouring, keeper


# ======================================================================================================================
# Saved works: the list of them, a thumbnail of each and the copy of one (feature vector-detail-and-colour-control, 0.9.0)
# ======================================================================================================================
# A work is saved by every operation (the plan row holds its settings, its colouring and variants, the history of its splits, the
# files hold its picture and its documents), so nothing here changes the record except the copy, which is a work of its own.
THUMB_PX = 360                              # the longer side of a thumbnail
THUMB_SUPERSAMPLE = 2                       # drawn twice as large and reduced: smooth edges and no seam between two neighbours
THUMB_BACKGROUND = (58, 60, 66)             # what no colour covers: a region left out of the file, or a work not coloured yet
COPY_SUFFIX = " (копия)"
PLAN_COLUMNS = ("id", "name", "mode", "status", "device_id", "lens_id", "legacy_profile_id", "plate_id", "markers_enabled", "plan_identifier",
                "band_count", "created_at", "research_session_id")        # what the plan row holds; the rest of a plan is its data


def _counts_of(data: dict) -> dict:
    """The colours and regions of a photograph work saved before its plan kept them, read from its document (remembered for the list)."""
    def read() -> dict:
        try:
            document = _document(data)
        except (OSError, ValueError):
            return {"colours": None, "regions": None}
        return {"colours": len(document["palette"]), "regions": len(document["regions"])}
    return _memo(("counts", data["document_path"]), read)


def _summary(row, data: dict) -> dict:
    """One work as the list shows it, from what its plan keeps; no document is opened (a work saved before the plan kept its counts: once)."""
    photo = is_photo(data)
    size, colouring, history = data["size_mm"], data.get("colouring") or {}, data.get("history") or []
    said = colouring.get("ai") or {}
    if photo:
        counts = data.get("counts") or _counts_of(data)
        colours, regions = counts["colours"], counts["regions"]
    else:
        colours, regions = len({r["layer_key"] for r in data["regions"]}), len(data["regions"])
    return {"id": row["id"], "name": row["name"], "status": row["status"], "created_at": row["created_at"],
            "updated_at": history[-1]["at"] if history else row["created_at"], "strategy": PHOTO if photo else "trace",
            "width_mm": round(size["width"], 2), "height_mm": round(size["height"], 2),
            "algorithm": data.get("split", {}).get("algorithm", seg.DEFAULT_ALGORITHM) if photo else None,
            "n_colours": colours, "regions": regions, "layers": len(data.get("layers") or []), "zones": len(pz.zones(colouring)),
            "mode": colouring.get("mode"),
            "ai_style": said.get("style"), "ai_text": said.get("text"), "variants": len(data.get("variants") or []),
            "smoothing_mm": data.get("smoothing_mm", 0.0) if photo else None, "version": data["document_version"],
            "attention": data.get("attention") if photo else None, "review": _last_review(data) if photo else None}


def _last_review(data: dict) -> dict | None:
    """The newest review of a work in the few numbers the list shows (DEC-090)."""
    reviews = work_review.newest_first(data.get("reviews") or [])
    if not reviews:
        return None
    last = reviews[0]
    return {"engraving_id": last["engraving_id"], "photo_name": last["photo_name"], "reviewed_at": last["reviewed_at"],
            "matched": last["summary"]["matched"], "engraved": last["summary"]["engraved"], "mean_delta_e": last["summary"]["mean_delta_e"],
            "area_share_beyond": last["summary"]["area_share_beyond"], "beyond_layers": last["summary"]["beyond_layers"],
            "promise_lost": bool(last.get("promise_lost"))}


def listing(store: Store) -> list[dict]:
    """Every saved vector work, the newest first: what it is, how it was split and coloured and when it last changed."""
    rows = store.query("SELECT id, name, status, created_at, data_json FROM plan WHERE mode=? AND status!='Deleted' ORDER BY id DESC", (pl.MODE_VECTOR,))
    return [_summary(row, json.loads(row["data_json"])) for row in rows]


def _painted(plan: dict) -> dict[str, list[int]] | None:
    """The titanium colour of every region the file engraves, as the last colouring left it in the plan's layers; None while a work has no
    colouring (its regions are then drawn in their source colours)."""
    layers = plan.get("layers") or []
    if not is_photo(plan) or plan.get("colouring") is None or any("region_ids" not in layer for layer in layers):
        return None
    return {region: layer["srgb"] for layer in layers for region in layer["region_ids"]}


def _draw_thumbnail(plan: dict, painted: dict[str, list[int]] | None, zones: list[tuple[dict, rc.Picture]] = (), texts: list = ()) -> bytes:
    photo = is_photo(plan)
    document = _geometry(plan) if photo else _document(plan)
    size = document["size_mm"]
    scale = THUMB_PX / max(size["width"], size["height"])
    cols, rows = max(1, round(size["width"] * scale)), max(1, round(size["height"] * scale))
    big = scale * THUMB_SUPERSAMPLE
    canvas = np.empty((rows * THUMB_SUPERSAMPLE, cols * THUMB_SUPERSAMPLE, 3), np.uint8)
    canvas[:] = THUMB_BACKGROUND
    width = max(1, round(max(document["px_mm"], 0.05) * big))
    for region in seg.regions_as_loops(document) if photo else document["regions"]:
        rgb = region["srgb"] if painted is None else painted.get(region["id"])
        if rgb is None:                                   # left out of the file: nothing is engraved there
            continue
        colour = tuple(int(v) for v in rgb)
        if region["loops"]:                               # outer boundary and holes in one call: the holes stay open
            cv2.fillPoly(canvas, [np.round(np.asarray(loop) * big).astype(np.int32) for loop in region["loops"] if len(loop) >= 3], colour)
        else:                                             # a line of a traced work
            for stroke in region["strokes"]:
                cv2.polylines(canvas, [np.round(np.asarray(stroke) * big).astype(np.int32)], False, colour, width)
    for box, picture in zones:                            # a photo zone: its picture as it will come out, transparent outside it
        _paste(canvas, cv2.cvtColor(cv2.imdecode(np.frombuffer(picture.png(), np.uint8), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGRA2RGBA), box, big)
    origin = {"x": 0.0, "y": 0.0}
    for shape, rgb in texts:                              # an inscription: its cut left clean, its backing and letters in their colours
        cover = lettering.coverage(shape, origin, big, (canvas.shape[1], canvas.shape[0]), supersample=1)[..., None]
        canvas[:] = (canvas * (1 - cover) + np.asarray(rgb, np.float32) * cover).round().astype(np.uint8)
    small = cv2.resize(canvas, (cols, rows), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".png", cv2.cvtColor(small, cv2.COLOR_RGB2BGR))[1].tobytes()


def _paste(canvas: np.ndarray, rgba: np.ndarray, box: dict, scale: float) -> None:
    """``rgba`` laid over ``canvas`` (RGB) on ``box`` (mm) at ``scale`` pixels a mm, through its transparency."""
    x0, y0 = round(box["x"] * scale), round(box["y"] * scale)
    w, h = max(1, round(box["width"] * scale)), max(1, round(box["height"] * scale))
    shown = cv2.resize(rgba, (w, h), interpolation=cv2.INTER_AREA if w < rgba.shape[1] else cv2.INTER_LINEAR)
    rows, cols = canvas.shape[:2]
    cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(cols, x0 + w), min(rows, y0 + h)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    part = shown[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
    alpha = part[..., 3:4].astype(np.float32) / 255.0
    under = canvas[cy0:cy1, cx0:cx1].astype(np.float32)
    canvas[cy0:cy1, cx0:cx1] = (part[..., :3] * alpha + under * (1 - alpha)).round().astype(np.uint8)


def thumbnail(store: Store, plan_id: int) -> rc.Picture:
    """A work's picture for the list: its regions in the titanium colours of its current colouring (in their source colours before it has
    one, and for a traced work). Known by a key of everything it is drawn from, so a recolouring, a new split or another smoothing gives
    another picture and an unchanged one is neither drawn nor sent again; it lives in the render cache (``vector-<id>``)."""
    plan = _job(store, plan_id)
    painted = _painted(plan)
    zones = []
    if painted is not None and pz.zones(plan["colouring"]):          # its photo zones as they will come out (REQ-073)
        rows = _zone_rows(store, plan, _document(plan), pz.zones(plan["colouring"]), 0)
        zones = [(row["box"], _zone_picture(store, plan, row)) for row in rows if not row["problem"]]
    texts = _text_paint(store, plan) if painted is not None else []
    key = rc.key_of({"kind": "vector-thumbnail", "plan": plan["id"], "px": THUMB_PX, "version": plan["document_version"],
                     "document": rc.file_stamp(plan["document_path"]), "smoothing_mm": plan.get("smoothing_mm", 0.0),
                     "painted": None if painted is None else rc.text_digest(json.dumps(painted, sort_keys=True)),
                     "zones": [picture.key for _, picture in zones],
                     "texts": rc.text_digest(json.dumps([[lettering.svg_d(shape), rgb] for shape, rgb in texts]))})
    return rc.Picture(store, f"vector-{plan['id']}", key, lambda: _draw_thumbnail(plan, painted, zones, texts))


def _text_paint(store: Store, plan: dict) -> list[tuple]:
    """The inscriptions of a work as its thumbnail draws them, in order: the cut of each in the colour of what is not engraved, then its
    backing and letters in the colours of their layers as the last colouring stored them. An inscription that cannot be drawn (its font is
    gone) is left out."""
    colours = {layer.get("entry_id"): layer["srgb"] for layer in plan.get("layers") or [] if layer.get("srgb")}
    out = []
    for spec in _texts(plan["colouring"]):
        try:
            found = lettering.geometry(store.data_dir, spec, plan["size_mm"])
        except su.ValidationError:
            continue
        out.append((found["cut"], list(THUMB_BACKGROUND)))
        for shape, key in ((found["backing"], "backing_entry_id"), (found["letters"], "entry_id")):
            if shape is not None and not shape.is_empty and colours.get(spec[key]):
                out.append((shape, list(colours[spec[key]])))
    return out


def copy_work(store: Store, plan_id: int, name=None) -> int:
    """A work of its own made from this one: the same picture, split, colouring, variants, settings and task, to try something else
    on while the first stays as it is. It has its own copies of the image and the document (deleting one never breaks the other),
    its own identifier (the photograph of an engraving finds its work by it), no undo, redo, exported files or targets sent to the
    designer, and one entry in its history saying whose copy it is. The permission to send the photograph to the language model is
    per work and is not carried over."""
    plan = _job(store, plan_id)
    if name is None:
        title = plan["name"] + COPY_SUFFIX
    elif isinstance(name, str) and name.strip():
        title = name.strip()
    else:
        raise cv.ConversionError("give the plan a name")
    image = Path(plan["image_path"])
    if not image.is_file():
        raise KeyError("the stored source image is missing")
    document = _document(plan)
    data = {k: copy.deepcopy(v) for k, v in plan.items() if k not in PLAN_COLUMNS}
    identifier = pl.new_identifier("TCE-A")
    enabled, size = plan["markers_enabled"], plan["size_mm"]
    data.update(image_path=cv._store_image(store, image.read_bytes()), document_path=_write_document(store, document), exports=[],
                markers=cv._plan_markers(identifier, enabled, size["width"], size["height"], store),
                marker_layer=pl.marker_layer_settings(store) if enabled else None)
    data["history"] = [{"version": plan["document_version"], "op": {"op": "copy", "from": plan["id"]}, "at": now(), "path": data["document_path"]}]
    for part, empty in (("undo", []), ("redo", []), ("targets", [])):
        if part in data:
            data[part] = empty
    data.pop("ai_photo", None)
    data.pop("reviews", None)                  # the photographs of an engraving belong to the work that was engraved (DEC-090)
    data.pop("attention", None)
    with store.transaction():
        new_id = cv.save_plan(store, None, name=title, mode=pl.MODE_VECTOR, status=cv.ST_DRAFT, device_id=plan["device_id"], lens_id=plan["lens_id"],
                              markers=enabled, identifier=identifier, band_count=None, data=data)
        fresh = pl.get_plan(store, new_id)
        if is_photo(fresh):
            _photo_refresh(store, fresh, document, _palette(store, fresh))
        else:
            _refresh(store, fresh)
        store.audit("vector_work_copied", plan_id=new_id, source_plan_id=plan["id"])
    return new_id


def rename_work(store: Store, plan_id: int, name) -> str:
    """Give a work another name and return it as stored. Only the name changes: a rename is not an edit of the document, so it has no
    history entry, no document version, nothing to undo, and the files exported earlier keep the name they were saved under. Naming it
    as it is already named writes nothing."""
    plan = _job(store, plan_id)
    if not isinstance(name, str) or not name.strip():
        raise cv.ConversionError("give the plan a name")
    title = name.strip()
    if title != plan["name"]:
        with store.transaction():
            store.execute("UPDATE plan SET name=? WHERE id=?", (title, plan_id))
            store.audit("vector_work_renamed", plan_id=plan_id, old_name=plan["name"], new_name=title)
    return title
