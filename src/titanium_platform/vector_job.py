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
import json
import math
import threading
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
SMOOTHING_MM = 0.5                      # a new photograph work's smoothing of its borders; a work made before has none (0: as traced)
SMOOTHING_MAX_MM = 2.0                  # the end of the slider (REQ-052, DEC-083)


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
MEMO_SIZE = 6


def _memo(key: tuple, make):
    """The last few smoothed documents and their pictures: the slider asks for the same strength again as often as it moves back."""
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
COLOURING_OPS = ("assign", "restore", "settings", "set_colour", "paint", "exclude_colour", "include_colour",
                 "exclude_region", "include_region", "merge_titanium", "merge_colours", "merge_regions", "undo", "redo")
MERGE_OPS = ("merge_colours", "merge_regions")       # each makes a new version of the split
SCOPES = ("region", "colour", "fill")                # what a click of the brush paints (editor REQ-045)
UNDO_DEPTH = 50                                      # steps kept to undo and redo together


def photo_cap(markers: bool) -> int:
    """Colours and recipes of a photograph job: LightBurn's 30 output colours less the cleaning, less the markers (DEC-073)."""
    return pl.MAX_LAYERS - 1 - int(markers)


def _split_settings(params: dict, markers: bool, detected: int) -> dict:
    """The split settings checked: colours within the job's layers, the splitting algorithm (``segment.ALGORITHMS``, a level
    of detail is not one), a level of detail, a smoothing in mm, faces on or off, areas marked by hand (in pixels of the working
    picture) and detected areas removed (by their number)."""
    cap = photo_cap(markers)
    n = params.get("n_colors")
    if isinstance(n, bool) or not isinstance(n, int) or not seg.MIN_COLORS <= n <= cap:
        raise cv.ConversionError(f"choose from {seg.MIN_COLORS} to {cap} colours: the cleaning takes one LightBurn layer"
                                 + (" and the markers another" if markers else ""))
    algorithm = params.get("algorithm") or seg.DEFAULT_ALGORITHM
    if algorithm not in seg.ALGORITHMS:
        raise cv.ConversionError("the splitting algorithm must be slic or seeds")
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
    return {"n_colors": n, "algorithm": algorithm, "detail": detail, "tolerance_mm": smoothing, "faces": bool(params.get("faces", True)),
            "manual": manual, "removed": sorted(set(removed))}


def _segment(plan: dict, picture: np.ndarray) -> dict:
    """Split the job's picture with its settings; the faces found once in it are used unless removed or switched off."""
    s, found = plan["split"], plan["detected"]
    across, share = DETAIL[s["detail"]]
    size = plan["size_mm"]
    areas = [a for i, a in enumerate(found["areas"]) if i not in s["removed"]] if s["faces"] else []
    document = seg.segment(picture, size["width"], s["n_colors"], important=areas + s["manual"], use_faces=False,
                           min_area_mm2=share * size["width"] * size["height"], tolerance_mm=s["tolerance_mm"], superpixels=across,
                           algorithm=s.get("algorithm", seg.DEFAULT_ALGORITHM))
    document["faces"] = {"searched": s["faces"], "found": found["faces"] if s["faces"] else 0, "error": found["error"] if s["faces"] else None}
    return document


def start_photo(store: Store, device_id: int, lens_id: int | None, material_id: int, image_bytes: bytes, width_mm: float, name: str, *,
                threshold=None, n_colors: int = 12, detail: str = DEFAULT_DETAIL, tolerance_mm: float = seg.TOLERANCE_MM,
                algorithm: str = seg.DEFAULT_ALGORITHM, use_faces: bool = True, markers: bool = False, max_time: float | None = None, include_as_shot: bool = False,
                task: str | None = None, goals: dict | None = None) -> int:
    """Split a photograph into colour regions for one laser, lens and titanium stock and colour every source colour
    automatically: the fastest measured colour within the delta E tolerance (DEC-075), else the nearest (editor DEC-001)."""
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
    split = _split_settings({"n_colors": n_colors, "algorithm": algorithm, "detail": detail, "tolerance_mm": tolerance_mm, "faces": use_faces},
                            markers, 0)
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
            "colouring": None, "variants": [], "undo": [], "redo": [], "exports": [], "regions": [], "layers": [], "weak": []}
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
    return {**{k: split[k] for k in ("n_colors", "algorithm", "detail", "tolerance_mm", "faces")}, "manual": len(split["manual"]),
            "removed": len(split["removed"])}


def is_photo(plan: dict) -> bool:
    return plan.get("strategy") == PHOTO


def _photo_job(store: Store, plan_id: int) -> dict:
    plan = _job(store, plan_id)
    if not is_photo(plan):
        raise cv.ConversionError("only a photograph split into colour regions is split and coloured this way")
    return plan


def resplit(store: Store, plan_id: int, params: dict) -> None:
    """Split the picture again with new settings and important areas: a new document version, coloured anew (closest);
    a fresh start, the variants and the steps to undo and redo of the earlier split are left behind with it."""
    plan = _photo_job(store, plan_id)
    if not isinstance(params, dict):
        raise cv.ConversionError("the split settings must be an object")
    plan["split"] = _split_settings(params, plan["markers_enabled"], len(plan["detected"]["areas"]))
    document = _segment(plan, _source_rgb(Path(plan["image_path"]).read_bytes()))
    entries = _palette(store, plan)
    with store.transaction():
        _new_version(store, plan, document, {"op": "split", **_split_op(plan["split"])})
        plan["colouring"] = _automatic(plan, document, entries, "closest", 0, _empty_colouring())
        plan["variants"], plan["undo"], plan["redo"] = [], [], []
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
    """A new colouring after an automatic mode: every colour without the operator's own choice gets the mode's entry
    (palette.assign), the operator's choices of colours (still measured, of a colour still in the split) and regions stay."""
    by_id = {e["id"]: e for e in entries}
    out = {**copy.deepcopy(colouring), "mode": mode, "seed": seed, "assignment": {}, "how": {}}
    if not entries:                          # nothing measured on this titanium: every colour stays without a titanium colour
        return out
    settings = plan["colour_settings"]
    indexes = {str(p["index"]) for p in document["palette"]}
    keep = {i: g["entry_id"] for i, g in colouring["groups"].items() if g["entry_id"] in by_id and i in indexes}
    result = palette.assign(_sources(document), entries, mode, tolerance_de=plan["threshold"], seed=seed, max_time=settings["max_time"],
                            keep=keep, include_as_shot=settings["include_as_shot"])
    out["assignment"] = {str(c["index"]): c["entry_id"] for c in result["colours"]}
    out["how"] = {str(c["index"]): c["how"] for c in result["colours"]}
    return out


def _add_variant(plan: dict, document: dict, entries: list[dict]) -> None:
    """The current colouring, just made by an automatic mode, becomes a numbered variant that can be restored on the
    version of the split it was made on."""
    number = 1 + max((v["number"] for v in plan["variants"]), default=0)
    plan["colouring"]["variant"] = number
    state = _state(plan, document, entries)
    plan["variants"].append({"number": number, "mode": plan["colouring"]["mode"], "seed": plan["colouring"]["seed"], "at": now(),
                             "version": plan["document_version"], "colouring": copy.deepcopy(plan["colouring"]), "totals": state["totals"]})


def _state(plan: dict, document: dict, entries: list[dict]) -> dict:
    """Every source colour and region with its titanium colour and status, the colours beyond the delta E tolerance, the
    regions whose titanium colour is no longer measured, the layers of the file and the totals of the current colouring.

    A colour's status: ``excluded``, ``missing`` (its titanium colour is not measured, or not any more), ``hand`` or
    ``accepted`` (the operator's choice; accepted before the editor) or ``automatic``. ``outside_tolerance`` flags a
    titanium colour farther than the delta E tolerance; it never blocks the file (editor DEC-001)."""
    by_id = {e["id"]: e for e in entries}
    colouring, settings, tolerance = plan["colouring"], plan["colour_settings"], plan["threshold"]
    candidates = [e for e in entries if palette.automatic(e, settings["max_time"], settings["include_as_shot"])]
    excluded_colours, excluded_regions = set(colouring["excluded_colours"]), set(colouring["excluded_regions"])
    colours = []
    for source in document["palette"]:
        key = str(source["index"])
        group = colouring["groups"].get(key)
        entry = by_id.get(group["entry_id"] if group else colouring["assignment"].get(key))
        nearest = min((color.delta_e(source["lab"], e["lab"]) for e in candidates), default=None)
        if source["index"] in excluded_colours:
            status = "excluded"
        elif entry is None:
            status = "missing"
        else:
            status = group["by"] if group else "automatic"
        delta = None if entry is None else color.delta_e(source["lab"], entry["lab"])
        colours.append({"index": source["index"], "lab": source["lab"], "srgb": source["srgb"], "pixels": source["pixels"], "status": status,
                        "entry_id": entry["id"] if entry else None, "how": "hand" if group else colouring["how"].get(key),
                        "delta_e": None if delta is None else round(delta, 2), "outside_tolerance": delta is not None and delta > tolerance,
                        "nearest_delta_e": None if nearest is None else round(nearest, 2), "regions": 0, "open_regions": 0})
    by_index = {c["index"]: c for c in colours}
    px_area = document["px_mm"] ** 2
    used: dict[str, dict] = {}
    missing_regions, open_pixels, weighted, weight = [], {}, 0.0, 0.0
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
            open_pixels[c["index"]] = open_pixels.get(c["index"], 0) + region["pixels"]
            if c["status"] == "missing":
                missing_regions.append(region["id"])
                continue
            entry_id = c["entry_id"]
        layer = used.setdefault(entry_id, {"entry_id": entry_id, "region_ids": [], "pixels": 0})
        layer["region_ids"].append(region["id"])
        layer["pixels"] += region["pixels"]
        weighted += region["pixels"] * color.delta_e(region["lab"], by_id[entry_id]["lab"])
        weight += region["pixels"]
    outside = [c for c in colours if c["outside_tolerance"] and c["status"] != "excluded" and c["open_regions"]]
    total = sum(p["pixels"] for p in document["palette"]) or 1
    layers = sorted(used.values(), key=lambda layer: (-by_id[layer["entry_id"]]["lab"][0], layer["entry_id"]))
    for layer in layers:
        layer["area_mm2"] = layer["pixels"] * px_area
    return {"colours": colours, "layers": layers, "by_id": by_id, "missing_regions": missing_regions,
            "outside": {"colours": len(outside), "regions": sum(c["open_regions"] for c in outside),
                        "share": sum(open_pixels[c["index"]] for c in outside) / total, "indexes": [c["index"] for c in outside]},
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
    """Why the file cannot be written yet, or None; a colour beyond the delta E tolerance never is a reason (editor DEC-001)."""
    if not state["by_id"]:
        return "no measured colour of this laser, lens and titanium stock fills an area"
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
    """Store the layers of the current colouring and set the status: ready when it can be exported."""
    state = _state(plan, document, entries)
    plan["layers"] = _export_layers(store, plan, state)
    plan["regions"], plan["weak"] = [], []
    plan.pop("unresolved", None)                 # kept by works made before the editor
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
    """The current split in its source colours (one path per region, with its id and colour index), borders at the work's smoothing."""
    plan = _photo_job(store, plan_id)
    return _memo(("svg", plan["document_path"], float(plan.get("smoothing_mm", 0.0))), lambda: seg.to_svg(_geometry(plan)))


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


def photo_view(store: Store, plan: dict) -> dict:
    """A photograph job as its screen shows it: the split's settings, counts and important areas, every source colour
    with its titanium colour and status, the colours beyond the tolerance (``outside``) and the regions whose colour is no
    longer measured (``missing``), the variants with the split version of each, the steps to undo and redo, the layers of
    the file with the estimated time of the whole job, and the exported files. The geometry itself is in :func:`split_svg`."""
    document = _document(plan)
    entries = _palette(store, plan)
    state = _state(plan, document, entries)
    by_id, colouring, settings = state["by_id"], plan["colouring"], plan["colour_settings"]
    used = {c["entry_id"] for c in state["colours"] if c["entry_id"]} | {e for e in colouring["regions"].values() if e in by_id}
    layers = _export_layers(store, plan, state)
    hidden = ("document_path", "history", "exports", "undo", "redo", "variants", "colouring", "detected", "regions", "weak", "layers",
              "unresolved")
    out = {k: v for k, v in plan.items() if k not in hidden}
    found = plan["detected"]
    out.update(
        strategy=PHOTO,
        split={**plan["split"], "algorithm": plan["split"].get("algorithm", seg.DEFAULT_ALGORITHM)},   # made before the choice: slic
        document={**{k: document[k] for k in ("size_mm", "px_mm", "image_px", "n_colors", "min_area_mm2", "tolerance_mm", "superpixels",
                                               "faces")},
                  "algorithm": document.get("algorithm", seg.DEFAULT_ALGORITHM), "version": plan["document_version"], "colours": len(document["palette"]), "regions": len(document["regions"]),
                  "important_regions": sum(r["important"] for r in document["regions"])},
        areas={"detected": [{**a, "number": i, "removed": i in plan["split"]["removed"]} for i, a in enumerate(found["areas"])],
               "faces": found["faces"], "search_failed": found["error"] is not None},
        colours=state["colours"], entries={i: _shown(by_id[i], settings) for i in sorted(used)},
        colouring={k: colouring[k] for k in ("mode", "seed", "variant", "regions", "excluded_colours", "excluded_regions")},
        settings={"tolerance_de": plan["threshold"], **settings},
        outside=state["outside"], missing={"regions": len(state["missing_regions"])}, totals=state["totals"],
        variants=[{**{k: v[k] for k in ("number", "mode", "seed", "at", "totals")}, "version": v.get("version", plan["document_version"])}
                  for v in plan["variants"]],
        undo=len(plan["undo"]), redo=len(plan.get("redo", [])),
        layers=[{k: v for k, v in layer.items() if k not in ("region_ids", "layer_keys")} | {"regions": layer["region_ids"]} for layer in layers],
        time=_estimate(plan, layers), export_blocked=_blocker_photo(plan, state), layer_cap=photo_cap(plan["markers_enabled"]),
        palette_size=len(entries), smoothing_mm=plan.get("smoothing_mm", 0.0), smoothing_max_mm=SMOOTHING_MAX_MM,
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
    regions = [{**r, "layer_key": key[r["id"]]} for r in seg.regions_as_loops(_geometry(plan)) if r["id"] in key]
    data = pl.export_lbrn2({**plan, "layers": layers, "vector_document": {"regions": regions}})
    path = store.data_dir / "files" / f"vector-export-{uuid.uuid4().hex[:12]}.lbrn2"
    path.write_bytes(data)
    plan["layers"] = layers
    plan.pop("unresolved", None)
    plan["exports"].append({"number": len(plan["exports"]) + 1, "name": plan["name"] + ".lbrn2", "path": str(path), "at": now(),
                            "document_version": plan["document_version"], "layers": len(layers), "regions": len(regions),
                            "variant": plan["colouring"]["variant"], "colouring": copy.deepcopy(plan["colouring"]),
                            "smoothing_mm": plan.get("smoothing_mm", 0.0), "seconds": _estimate(plan, layers)["seconds"]})
    cv._persist(store, plan, ST_EXPORTED, plan["markers_enabled"])
    return plan["name"], data


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


def _step(plan: dict, direction: str) -> None:
    """Undo or redo one operation: the state on top of that stack comes back and the present one goes onto the other."""
    if not plan[direction]:
        raise cv.ConversionError("there is no earlier colouring to go back to" if direction == "undo" else "there is no undone change to redo")
    there = plan[direction].pop()
    plan["redo" if direction == "undo" else "undo"].append(_here(plan))
    _go(plan, there)


def _go(plan: dict, there: dict) -> None:
    """Bring a state back; one of another split version brings that version's document back from the history."""
    if there["version"] != plan["document_version"]:
        entry = next((h for h in plan["history"] if h.get("path") and h["version"] == there["version"]), None)
        if entry is None or not Path(entry["path"]).is_file():
            raise cv.ConversionError("there is no such version of the vector document")
        plan["document_version"], plan["document_path"] = entry["version"], entry["path"]
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

    ``{"op": "assign", "mode"}`` recolours automatically (closest, tonality, random: a new seed each time, fewer_layers) and
    adds a variant; ``{"op": "restore", "variant"}`` brings back one made on the current version of the split;
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
    entries = _palette(store, plan)
    if kind in ("undo", "redo"):
        _step(plan, kind)
        document = _document(plan)
    elif kind in MERGE_OPS:
        merged, colouring, keeper = _merge(plan, document, entries, kind, op)
        _snapshot(plan)
        plan["colouring"], document = colouring, merged
    else:
        changes = _change(store, plan, document, entries, kind, op)
        _snapshot(plan)
        plan.update(changes)
        if kind in ("assign", "settings"):
            _add_variant(plan, document, entries)
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
            raise cv.ConversionError("the recolouring mode must be closest, tonality, random or fewer_layers")
        seed = 1 + max((v["seed"] for v in plan["variants"] if v["mode"] == "random"), default=0) if mode == "random" else 0
        return {"colouring": _automatic(plan, document, entries, mode, seed, current)}
    if kind == "restore":
        variant = next((v for v in plan["variants"] if v["number"] == op.get("variant")), None)
        if variant is None:
            raise cv.ConversionError("there is no such variant of the colouring")
        if variant["version"] != plan["document_version"]:
            raise cv.ConversionError("this variant of the colouring belongs to another version of the split")
        return {"colouring": copy.deepcopy(variant["colouring"])}
    if kind == "settings":
        settings = {"max_time": colormap.time_limit(op.get("max_time")), "include_as_shot": bool(op.get("include_as_shot"))}
        threshold = cv._threshold(store, plan["device_id"], plan["lens_id"], op.get("tolerance_de", plan["threshold"]))
        ruled = {**plan, "threshold": threshold, "colour_settings": settings}
        return {"threshold": threshold, "colour_settings": settings,
                "colouring": _automatic(ruled, document, entries, current["mode"] or "closest", current["seed"], current)}
    return {"colouring": _choose(copy.deepcopy(current), plan, document, entries, kind, op)}


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
    return colouring


def _paint(colouring: dict, plan: dict, document: dict, entries: list[dict], op: dict) -> dict:
    """A click of the brush (editor REQ-045) with a titanium colour, or null for the automatic choice. Scope ``region``
    paints the clicked region; ``colour`` its whole source colour, the own colours of the regions inside it cleared (null:
    the colour goes back to the automatic choice); ``fill`` every region :func:`_reach` finds from it. A region or colour
    painted with a titanium colour is included again, and with the scope ``colour`` so is every region of the colour that
    was excluded one by one (editor DEC-079), as the hover outlines them."""
    region = _region_id(document, op.get("region"))
    scope, entry = op.get("scope"), op.get("entry_id")
    if scope not in SCOPES:
        raise cv.ConversionError("the scope must be region, colour or fill")
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
        painted = {region} if scope == "region" else set(_reach(document, colouring, region, _similarity(op.get("similarity_de"))))
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
    of the region it was reached from); excluded regions and regions of excluded colours stop it, the clicked one aside."""
    excluded_colours = set(colouring["excluded_colours"])
    walls = set(colouring["excluded_regions"]) | {r["id"] for r in document["regions"] if r["color"] in excluded_colours}
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
    left = {p["index"] for p in merged["palette"]}           # a colour merged away, or left without a region
    for part in ("groups", "assignment", "how"):
        colouring[part] = {k: v for k, v in colouring[part].items() if int(k) in left}
    colouring["excluded_colours"] = [i for i in colouring["excluded_colours"] if i in left]
    return merged, colouring, keeper
