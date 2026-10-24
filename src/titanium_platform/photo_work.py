"""Photo engraving works (REQ-061, DEC-104): a picture engraved in LightBurn's grayscale mode on a measured scale, kept as a vector work
is (``vector_job``): the operator's works are listed, opened, copied, renamed and deleted, and each opens on one screen.

A work is a row of ``plan`` of its own mode (``plans.MODE_PHOTO_WORK``). The laser and lens are the row's columns; its data holds

* the picture as it was uploaded, stored once in the data folder (``image_path``), with its file name and size in pixels;
* the scale it is engraved on (``scale``): the titanium and the settings that do not vary with the grey, which with the laser and the
  lens make a ``prediction_store.Mode``; only a measured scale can be chosen;
* Min and Max power, the width on the titanium in mm and whether the greys are chosen for the picture's colours (``by_colour``), and how
  (``colour_choice``, DEC-108, DEC-109: keeping the drawing, the default, or the nearest colour); whether the edges its engraving would lose
  are drawn in (``contours``, off by default and only with ``by_colour``: the picture engraved as uploaded is never drawn on);
* the main colours of the picture's objects (``colouring``, 0.21.0, with ``colour_choice`` "objects"): the lips, the glasses, a piece of
  the background ... (:mod:`objects`) each coloured along its own stretch of the scale (:mod:`colouring`), by hand or from a theme;
* the rules of the picture's parts (``rules``, REQ-062): a part found by the people model (:mod:`people`) may be engraved by its own rule
  (:mod:`picture_rules`), set by hand or proposed by the AI (:mod:`ai_picture`); whether a reduced copy of the picture may be sent to
  the AI (``ai_photo``, off until the operator allows it) and the last request to it (``ai``: the wish, whether the picture went, the AI's
  note and the rules before it, so that they can be put back);
* the kind of engraving (``kind``, 0.21.0): grayscale, or one of LightBurn's dot kinds (:data:`KINDS`), whose dots all fire at one power
  (``dot_power``) chosen on the scale, or at a recipe picked on the colour map (``dot_recipe``, 0.25.0, :mod:`dot_colours`: its settings,
  its step the dots' pitch, and its colour at the work's width); a dot kind is shown from the dots' colour (the scale's at that power or
  the recipe's, the cleaned titanium between the dots) until that kind has been photographed at those settings (a ramp of «Проба этого
  вида», ``width_ramp``, or an engraving), then from its measured tones; its picture is engraved as uploaded (the greys chosen for
  colours, the contours and the rules of parts are grayscale's and wait for it);
* the steps that can be undone and redone (``undo``, ``redo``): each holds the work's state as it decides what is engraved (:data:`STATE`);
* when it last changed (``updated_at``).

Everything shown is computed from these and the scale's measurements as they are now, at the work's width (DEC-107: the colour depends
on the length of the scan rows, and a picture's rows are as long as it is wide): the picture beside its prediction, the time and the
LightBurn file. The pictures go through the render cache (folder ``photo-work-<id>``), known by everything they are drawn
from, the scale's measured points included, so a new measurement draws them again. The decoded pictures of the works opened last are
kept in memory (``KEEP_DECODED``). The file carries no identifier yet (DEC-104): its engraving is measured as the operator's own photo
engravings are and counts towards the scale.

How the picture is engraved (the kind and its powers, the greys, the contours, the objects' colours, the parts' rules, the AI) is
:mod:`photo_state`'s, shared with the photo zones of vector works (REQ-073); this module keeps the work: its row, picture, scale, width
and undo.
"""
from __future__ import annotations

import copy
import json
import mimetypes
import threading
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Mapping

import cv2
import numpy as np
import shapely

from . import (capability_plates as cp, color, conversion as cv, devices, dot_colours as dc, drawing, engraving_time, grayscale, ingest as ig,
               lettering, objects as ob, palette, people, photo_modes, photo_state as st, plans as pl, prediction, prediction_store as ps,
               render_cache as rc, row_length, setup as su, vector_job as vj)
from .db import Store, now
from .prediction import PredictionError
from .vector_job import COPY_SUFFIX

MODE = pl.MODE_PHOTO_WORK
IDENTIFIER_PREFIX = "TCE-P"
THUMB_PX = 360                      # the longer side of the picture of a work in the list
KEEP_DECODED = 2                    # decoded pictures kept in memory: the work open now and the one before
GRAYSCALE = st.GRAYSCALE
KINDS = st.KINDS
TILE_PX = 360                       # the longer side of a kind's picture in «Какая гравировка?»
DATA = ("image_path", "image_name", "image_size", "scale", "min_power", "max_power", "width_mm", "by_colour", "colour_choice", "contours", "rules",
        "colouring", "kind", "dot_power", "dot_recipe", "ai_photo", "ai", "ai_theme", "undo", "redo", "updated_at", "texts")
SETTINGS = ("scale", "width_mm", "dot_colour", *st.SETTINGS)        # ``dot_colour``: a point of the colour map picked for the dots
# what a work made before the rules of parts (0.19.0), undo, the drawing kept (0.20.1) or the kinds and objects (0.21.0) has
DEFAULTS = {**st.DEFAULTS, "undo": [], "redo": [], "texts": []}
# What one step of undo or redo brings back: everything that decides what the work engraves, and the AI's answer that led to it. The
# permission to send the picture to the AI is not part of it: undoing never allows more to be sent than the operator allows now.
STATE = ("scale", "device_id", "lens_id", "min_power", "max_power", "width_mm", "by_colour", "colour_choice", "contours", "rules", "colouring", "kind",
         "dot_power", "dot_recipe", "ai", "ai_theme", "texts")
UNDO_DEPTH = 50                     # steps kept to undo and redo together, as the vector editor keeps
KEEP_LOOKS = 8                      # what the dots of the works' last looks are (their share above all), so an open work is not dithered again
KEEP_CUT = 2                        # pictures cut by their inscriptions kept in memory, as the decoded ones
PALETTE_SETTINGS = {"max_time": None, "include_as_shot": True}      # an inscription's colour is the operator's: no colour of the titanium is barred

_decoded: OrderedDict[str, dict] = OrderedDict()
_cut: OrderedDict[str, dict] = OrderedDict()
_looks: OrderedDict[str, dict] = OrderedDict()
_lock = threading.Lock()


def _work(store: Store, plan_id: int) -> dict:
    plan = pl.get_plan(store, plan_id)
    if plan["status"] == "Deleted" or plan["mode"] != MODE:
        raise KeyError(f"photo work {plan_id} not found")
    for key, value in DEFAULTS.items():
        plan.setdefault(key, value)
    return plan


def _folder(plan_id: int) -> str:
    return f"photo-work-{int(plan_id)}"


def mode_of(plan: Mapping) -> ps.Mode:
    """The scale a work is engraved on."""
    scale = plan["scale"]
    return ps.mode_of({**{k: scale.get(k) for k in ps.SETTINGS}, "global_passes": scale.get("global_passes")}, plan["device_id"],
                      plan["lens_id"], scale.get("material_id"))


def _scale_data(mode: ps.Mode) -> dict:
    return {"material_id": mode.material_id, **{k: getattr(mode, k) for k in ps.SETTINGS}, "global_passes": mode.global_passes}


measured_scale = ps.measured_mode         # the measured scale a work names (shared with the photo zones of vector works, REQ-073)
_span = ps.measured_span


def _remember(path: str, upload: dict) -> None:
    key = json.dumps(rc.file_stamp(path), sort_keys=True)
    with _lock:
        _decoded[key] = upload
        _decoded.move_to_end(key)
        while len(_decoded) > KEEP_DECODED:
            _decoded.popitem(last=False)


def _upload(plan: Mapping) -> dict:
    """The work's picture decoded as ``prediction_store.decode_upload`` does, from memory when it was decoded lately."""
    path = plan["image_path"]
    key = json.dumps(rc.file_stamp(path), sort_keys=True)
    with _lock:
        if key in _decoded:
            _decoded.move_to_end(key)
            return _decoded[key]
    try:
        data = Path(path).read_bytes()
    except OSError:
        raise KeyError("the stored picture of this work is missing") from None
    upload = ps.decode_upload(data)
    _remember(path, upload)
    return upload


def _item(store: Store, plan: Mapping) -> dict:
    """The work's picture prepared on its scale at its width (``photo_state.item``), transparent under its inscriptions (:func:`_cut_upload`);
    its objects and parts are those of the whole picture."""
    return st.item(store, mode_of(plan), _cut_upload(store, plan), plan, plan["name"], plan["width_mm"], whole=_upload(plan))


def _shown(item: dict, plan: Mapping) -> dict:
    """The item as it is engraved (``photo_state.engraved``)."""
    return st.engraved(item, plan)


def _digest(curve: prediction.Curve | None) -> str | None:
    return None if curve is None else rc.text_digest(json.dumps(curve.as_dict(), sort_keys=True, default=str))


def _key(kind: str, plan: Mapping, curve: prediction.Curve, measured: prediction.Curve | None = None, paint: list | None = None) -> str:
    """The key of a picture of the work: everything it is drawn from, the measured points of the scale included (and in a dot kind the
    measured tones of that kind, ``measured``), and the inscriptions as they are drawn on it (``paint``, :func:`_paint`)."""
    return rc.key_of({"kind": kind, "image": rc.file_stamp(plan["image_path"]), "mode": mode_of(plan).as_dict(), "dots_curve": _digest(measured),
                      "texts": _paint_key(paint),
                      "curve": _digest(curve), "width_mm": plan["width_mm"],
                      "min_power": plan["min_power"], "max_power": plan["max_power"], "by_colour": plan["by_colour"],
                      "colour_choice": plan["colour_choice"], "contours": plan["contours"], "rules": plan["rules"],
                      "colouring": plan["colouring"] if plan["colour_choice"] == "objects" else None, "engraving": plan["kind"], "dot_power": plan["dot_power"] if _dotted(plan) else None,
                      "dot_recipe": plan.get("dot_recipe") if _dotted(plan) else None})


# -- inscriptions (feature inscriptions-in-works, REQ-005, DEC-003) ---------------------------------------------------------------
def size_mm(plan: Mapping) -> dict:
    """The work's size in mm: its width and the height its picture gives it."""
    cols, rows = plan["image_size"]
    return {"width": plan["width_mm"], "height": plan["width_mm"] * rows / cols}


def _palette(store: Store, plan: Mapping) -> list[dict]:
    """The colours an inscription of the work is engraved in: every measured colour that fills an area on its laser, lens and its scale's
    titanium (``palette.vector_palette``, as a vector work's)."""
    material = plan["scale"].get("material_id")
    if material is None:
        return []
    return palette.vector_palette(store, plan["device_id"], plan["lens_id"], material)["entries"]


def palette_of(store: Store, plan_id: int) -> list[dict]:
    """The colours of :func:`_palette` as the colour window shows them."""
    return [vj._shown(e, PALETTE_SETTINGS) for e in _palette(store, _work(store, plan_id))]


def _cut_upload(store: Store, plan: Mapping) -> dict:
    """The work's picture (``_upload``) transparent under the cut of its inscriptions (DEC-003): there the picture engraves nothing and the
    inscriptions' own layers engrave their letters. Kept in memory for the works opened last, with what is found in it."""
    upload = _upload(plan)
    cut = lettering.inscribed(store.data_dir, plan["texts"], size_mm(plan), None)["cut"] if plan.get("texts") else None
    if cut is None:
        return upload
    key = json.dumps([rc.file_stamp(plan["image_path"]), plan["width_mm"], rc.text_digest(lettering.svg_d(cut))], sort_keys=True)
    with _lock:
        if key in _cut:
            _cut.move_to_end(key)
            return _cut[key]
    cols, rows = upload["size"]
    hole = lettering.hole(cut, {"x": 0.0, "y": 0.0}, cols / plan["width_mm"], (cols, rows)).astype(np.float32)
    small = upload["alpha"].shape[::-1]
    shown = hole if small == (cols, rows) else cv2.resize(hole, small, interpolation=cv2.INTER_AREA)
    out = {**upload, "alpha_full": upload["alpha_full"] * (1.0 - hole), "alpha": upload["alpha"] * (1.0 - shown)}
    with _lock:
        _cut[key] = out
        while len(_cut) > KEEP_CUT:
            _cut.popitem(last=False)
    return out


def _text_state(store: Store, plan: Mapping) -> dict | None:
    """The work's inscriptions laid out (``lettering.inscribed``) with the layers of the file that engrave them: one per titanium colour after
    the picture's, the lightest first as a vector work's, each with its recipe and in its colour at the length of its rows (DEC-107); the
    palette's entries in those colours (``by_id``) and why the file cannot be written (``problem``). None without an inscription."""
    if not plan.get("texts"):
        return None
    entries = _palette(store, plan)
    found = lettering.inscribed(store.data_dir, plan["texts"], size_mm(plan), {e["id"] for e in entries})
    by_id = {e["id"]: e for e in entries}
    groups = lettering.by_colour(found["rows"])
    first = (0 if ps.cleaning(store, mode_of(plan)) is None else pl.CLEAN_LAYER_INDEX + 1) + 1        # after the picture's layer
    layers = []
    for n, entry_id in enumerate(sorted(groups, key=lambda e: (-by_id[e]["lab"][0], e))):
        entry, index = by_id[entry_id], first + n
        shape = shapely.union_all([part for _, part in groups[entry_id]])
        loops = lettering.shapes(shape)
        seen = palette.at_size(entry, row_length.of_shapes(loops, vj._angle(entry)))
        by_id[entry_id] = {**entry, "lab": seen["lab"], "srgb": seen["srgb"], "size": seen["size"]}
        layers.append({"index": index, "name": vj._layer_name(index, entry), "entry_id": entry_id, "parameters": vj._recipe(store, entry),
                       "shapes": loops, "area_mm2": round(shape.area, 3), "srgb": seen["srgb"],
                       "texts": list(dict.fromkeys(text_id for text_id, _ in groups[entry_id]))})
    return {**found, "layers": layers, "by_id": by_id, "problem": lettering.text_blocker(found["rows"])}


def _paint(store: Store, texts: dict | None) -> list[tuple]:
    """The inscriptions as a look of the work draws them, in order: each one's cut in the colour of cleaned titanium (``True``: the picture
    beside the look is left white there), then its backing and letters in the colours of their layers."""
    if not texts:
        return []
    clean = [int(v) for v in np.clip(color.lab_to_srgb8(np.asarray([ps.clean_titanium(store)], np.float64)), 0, 255).round()[0]]
    out = []
    for row in texts["rows"]:
        if row["geometry"] is None:
            continue
        out.append((row["geometry"]["cut"], clean, True))
        for shape, key in ((row["backing"], "backing_entry_id"), (row["letters"], "entry_id")):
            entry = texts["by_id"].get(row["text"][key])
            if shape is not None and not shape.is_empty and entry is not None:
                out.append((shape, [int(v) for v in entry["srgb"]], False))
    return out


def _paint_key(paint: list | None) -> str | None:
    return rc.text_digest(json.dumps([[lettering.svg_d(shape), rgb] for shape, rgb, _ in paint])) if paint else None


def _drawn(paint: list, width_mm: float, rgb8: np.ndarray, grey: np.ndarray | None = None):
    """The look ``rgb8`` with the inscriptions drawn on (:func:`_paint`), and the picture ``grey`` beside it white under their cuts."""
    if not paint:
        return rgb8 if grey is None else (grey, rgb8)
    rows, cols = rgb8.shape[:2]
    canvas = rgb8.astype(np.float32)
    for shape, rgb, _ in paint:
        cover = lettering.coverage(shape, {"x": 0.0, "y": 0.0}, cols / width_mm, (cols, rows), supersample=2)[..., None]
        canvas = canvas * (1 - cover) + np.asarray(rgb, np.float32) * cover
    look = canvas.round().astype(np.uint8)
    if grey is None:
        return look
    g_rows, g_cols = grey.shape[:2]
    white = np.asarray(grey, np.float32).copy()
    for shape, _, cut in paint:
        if cut:
            cover = lettering.coverage(shape, {"x": 0.0, "y": 0.0}, g_cols / width_mm, (g_cols, g_rows), supersample=2)
            white = white * (1 - cover) + cover
    return white, look


def _holed(picture: np.ndarray, texts: dict | None, width_mm: float) -> np.ndarray:
    """The file's picture transparent on every pixel the inscriptions' cut touches (BGRA, ``lettering.hole``): the Image layer leaves the cut
    alone."""
    if not texts or texts["cut"] is None:
        return picture
    rows, cols = picture.shape[:2]
    hole = lettering.hole(texts["cut"], {"x": 0.0, "y": 0.0}, cols / width_mm, (cols, rows)).astype(bool)
    return np.dstack([picture, picture, picture, np.where(hole, 0, 255).astype(np.uint8)])


def _time(store: Store, plan: Mapping, fired: ps.Mode, texts: dict | None) -> dict:
    """How long the work's file engraves: the picture (``prediction_store.picture_time``), then its inscriptions' layers over their area."""
    size = size_mm(plan)
    time = ps.picture_time(fired, size["width"], size["height"], ps.cleaning(store, mode_of(plan)))
    if not texts or not texts["layers"]:
        return time
    more = engraving_time.estimate([{**{k: layer[k] for k in ("index", "name", "parameters", "area_mm2")}, "scan_pieces": _pieces(layer)}
                                    for layer in texts["layers"]])
    return {"seconds": time["seconds"] + more["seconds"], "complete": time["complete"] and more["complete"], "estimate": True,
            "layers": time["layers"] + more["layers"]}


def _pieces(layer: dict) -> float | None:
    """The pieces of scan line an inscription layer's fill makes over its shapes, as the file is timed (``engraving_time.loop_pieces``,
    cross-hatch twice)."""
    p = layer["parameters"]
    if not p.get("line_interval"):
        return None
    angle = float(p.get("scan_angle") or 0.0)
    pieces = engraving_time.loop_pieces(layer["shapes"], p["line_interval"], angle)
    return pieces + (engraving_time.loop_pieces(layer["shapes"], p["line_interval"], angle + 90) if p.get("cross_hatch") else 0.0)


def text(store: Store, plan_id: int, op) -> None:
    """One operation on the work's inscriptions (``lettering.operate``: ``text_add``, ``text_set``, ``text_copy``, ``text_delete``), one step
    of undo. A new inscription takes the darkest measured colour of the work's titanium."""
    plan = _work(store, plan_id)
    if not isinstance(op, Mapping):
        raise su.ValidationError("an edit must name its operation")
    before = _here(plan)
    entries = _palette(store, plan)
    ids = {e["id"] for e in entries}
    plan["texts"] = lettering.operate(store.data_dir, plan["texts"], dict(op), size_mm(plan), lambda e: e in ids, lambda: lettering.darkest(entries))
    if _here(plan) != before:
        _push(plan, before)
    plan["updated_at"] = now()
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("photo_work_texts", plan_id=plan["id"], op=op.get("op"))


# -- the kinds of engraving (0.21.0) ----------------------------------------------------------------------------------------------
_dotted = st.dotted
_dot_power = ps.dot_power_at


def _measured_dots(store: Store, plan: Mapping) -> prediction.Curve | None:
    """The tones of the work's dot kind at the settings its dots fire at and its titanium, as photographs of that kind measured them (a
    ramp of «Проба этого вида» or an engraving in that kind), at the work's width; None until that kind was photographed there."""
    try:
        return ps.curve_for(store, st.kind_mode(mode_of(plan), plan), plan["width_mm"])[0]
    except PredictionError:
        return None


def _dot_look(store: Store, plan: Mapping, curve: prediction.Curve, px: int | None = None,
              measured: prediction.Curve | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """The work in its dot kind seen from a distance at preview size, or with the longer side ``px``: the picture's grey, the look (RGB
    uint8) and the dots (``photo_state.dot_look``, with the ``measured`` tones of the kind, ``_measured_dots``)."""
    upload = _cut_upload(store, plan)
    grey, alpha = st.reduced(upload, px) if px else (upload["picture"], upload["alpha"])
    rgb8, dots = st.dot_look(store, mode_of(plan), grey, alpha, plan, plan["width_mm"], curve, measured)
    return grey, rgb8, dots


def _material(store: Store, material_id: int | None) -> dict | None:
    row = store.one("SELECT id, name, family, grade, batch, thickness_mm FROM material_profile WHERE id=?", (material_id,)) if material_id else None
    return dict(row) if row else None


def _summary(store: Store, plan: Mapping, texts: dict | None = None) -> dict:
    """What the list of works and the head of an open work say: the name, the size, the scale, Min and Max, the time (its inscriptions'
    layers included, ``texts``: :func:`_text_state`) and the dates."""
    texts = _text_state(store, plan) if texts is None else texts
    cols, rows = plan["image_size"]
    width = plan["width_mm"]
    height = width * rows / cols
    mode = mode_of(plan)
    fired = st.fired_at(mode, plan) if _dotted(plan) else mode        # a dot kind's layer: its dots' settings
    return {"id": plan["id"], "name": plan["name"], "identifier": plan["plan_identifier"], "created_at": plan["created_at"],
            "updated_at": plan.get("updated_at") or plan["created_at"], "image_name": plan["image_name"], "image_size": [cols, rows],
            "scale": mode.as_dict(), "material": _material(store, mode.material_id),
            "dpi": grayscale.image_dpi(fired.line_interval) if fired.line_interval else None,
            "min_power": plan["min_power"], "max_power": plan["max_power"], "width_mm": width, "height_mm": round(height, 2),
            "by_colour": plan["by_colour"], "colour_choice": plan["colour_choice"], "contours": plan["contours"],
            "kind": plan["kind"], "dot_power": plan["dot_power"], "dot_recipe": plan["dot_recipe"], "colouring": plan["colouring"],
            "rules": [st.shown_rule(r) for r in plan["rules"]], "ai": plan["ai"], "ai_theme": plan["ai_theme"], "ai_photo": plan["ai_photo"],
            "undo": len(plan["undo"]), "redo": len(plan["redo"]), "time": _time(store, plan, fired, texts), "texts_count": len(plan["texts"])}


def listing(store: Store) -> list[dict]:
    """Every photo work, the newest first."""
    rows = store.query("SELECT id FROM plan WHERE mode=? AND status!='Deleted' ORDER BY id DESC", (MODE,))
    return [_summary(store, _work(store, row["id"])) for row in rows]


def view(store: Store, plan_id: int) -> dict:
    """An open work: its summary and the picture beside its predicted look with what is said about it (as the scales' picture says it,
    ``prediction_store.describe``), or, when its scale is no longer measured, why there is no prediction (``problem``)."""
    plan = _work(store, plan_id)
    texts = _text_state(store, plan)
    out = {**_summary(store, plan, texts), "ai_missing": st.ai_missing(), **_texts_shown(texts)}
    paint = _paint(store, texts)
    try:
        item = _item(store, plan)
        if _dotted(plan):
            return _dot_view(store, plan, item, out, paint)
    except PredictionError as exc:
        return {**out, "picture": None, "problem": str(exc)}
    low, high = ps.check_power_range(plan["min_power"], plan["max_power"])
    shown = _shown(item, plan)
    info, rgb8 = ps.predicted(shown, low, high)
    key = _key("photo-work-preview", plan, item["curve"], paint=paint)
    if rc.read(store, _folder(plan["id"]), key) is None:       # drawn here already: the preview the screen asks for next is not drawn again
        try:
            rc.write(store, _folder(plan["id"]), key, prediction.to_png(prediction.side_by_side(*_drawn(paint, plan["width_mm"], rgb8, shown["picture"]))))
        except OSError:
            pass
    out["picture"] = {**info, "by_colour": plan["by_colour"], "colour_choice": plan["colour_choice"], "contours": plan["contours"],
                      "colour_match": shown.get("colour_match"), "rules_report": shown.get("rules_report"), "contours_report": shown.get("contours_report"),
                      "scale_size": dict(item["curve"].size), "scale_sizes": item["sizes"],
                      "size_mm": {"width": out["width_mm"], "height": out["height_mm"]}, "time": out["time"], "dpi": out["dpi"],
                      "preview": f"/api/photo-works/{plan['id']}/preview.png?v={key[:16]}", "file": f"/api/photo-works/{plan['id']}/export.lbrn2"}
    return out


def _texts_shown(texts: dict | None) -> dict:
    """The inscriptions as the work's screen shows them: each one (``lettering.shown_row``), the layers that engrave them and why the file
    cannot be written (``export_blocked``)."""
    return {"texts": [lettering.shown_row(row, texts["by_id"]) for row in texts["rows"]] if texts else [],
            "text_layers": [{k: v for k, v in layer.items() if k != "shapes"} for layer in texts["layers"]] if texts else [],
            "text_defaults": lettering.DEFAULTS, "export_blocked": texts["problem"] if texts else None}


def _look_dots(store: Store, plan: Mapping, curve: prediction.Curve, measured: prediction.Curve | None, key: str, paint: list = ()) -> dict:
    """The dots of the work's look at preview size (``_dot_look``): kept in memory by the preview's ``key`` with the share they strike, so
    an open work is dithered once; the preview is drawn and stored with them."""
    with _lock:
        if key in _looks and rc.read(store, _folder(plan["id"]), key) is not None:
            _looks.move_to_end(key)
            return _looks[key]
    grey, rgb8, dots = _dot_look(store, plan, curve, measured=measured)
    try:
        rc.write(store, _folder(plan["id"]), key, prediction.to_png(prediction.side_by_side(*_drawn(paint, plan["width_mm"], rgb8, grey))))
    except OSError:
        pass
    with _lock:
        _looks[key] = dots
        _looks.move_to_end(key)
        while len(_looks) > KEEP_LOOKS:
            _looks.popitem(last=False)
    return dots


def _dot_view(store: Store, plan: Mapping, item: dict, out: dict, paint: list = ()) -> dict:
    """``view`` of a work in a dot kind: the picture beside its dots seen from a distance, estimated from the dots' colour (the scale's at
    the dots' power at the work's width, or the recipe picked on the colour map; the cleaned titanium between them)."""
    measured = _measured_dots(store, plan)
    key = _key("photo-work-preview", plan, item["curve"], measured, paint)
    dots = _look_dots(store, plan, item["curve"], measured, key, paint)
    rows, cols = _upload(plan)["picture"].shape
    out["picture"] = {"kind": plan["kind"], "dots": dots, "estimate": measured is None, "span": list(item["curve"].span),
                      "scale_size": dict(item["curve"].size), "scale_sizes": item["sizes"], "dpi": out["dpi"], "time": out["time"],
                      "size_mm": {"width": out["width_mm"], "height": out["height_mm"]}, "shown": {"width": cols, "height": rows},
                      "transparent_share": round(float((np.asarray(item["alpha"]) < photo_modes.ALPHA_MIN).mean()), 4),
                      "preview": f"/api/photo-works/{plan['id']}/preview.png?v={key[:16]}",
                      "closeup": f"/api/photo-works/{plan['id']}/closeup.png?v={key[:16]}", "closeup_mm": ps.CLOSEUP_MM, "closeup_px": ps.CLOSEUP_PX,
                      "file": f"/api/photo-works/{plan['id']}/export.lbrn2"}
    return out


def preview(store: Store, plan_id: int) -> rc.Picture:
    """The picture beside its predicted look (``prediction.side_by_side``), at preview size."""
    plan = _work(store, plan_id)
    curve, _ = ps.curve_for(store, mode_of(plan), plan["width_mm"])
    paint = _paint(store, _text_state(store, plan))
    measured = _measured_dots(store, plan) if _dotted(plan) else None

    def draw() -> bytes:
        if _dotted(plan):
            grey, rgb8, _ = _dot_look(store, plan, curve, measured=measured)
            return prediction.to_png(prediction.side_by_side(*_drawn(paint, plan["width_mm"], rgb8, grey)))
        shown = _shown(_item(store, plan), plan)
        _, rgb8 = ps.predicted(shown, plan["min_power"], plan["max_power"])
        return prediction.to_png(prediction.side_by_side(*_drawn(paint, plan["width_mm"], rgb8, shown["picture"])))
    return rc.Picture(store, _folder(plan["id"]), _key("photo-work-preview", plan, curve, measured, paint), draw)


def thumbnail(store: Store, plan_id: int) -> rc.Picture:
    """The work in the list: its predicted look on the titanium, or the picture as LightBurn sees it while its scale is not measured."""
    plan = _work(store, plan_id)
    try:
        curve = ps.curve_for(store, mode_of(plan), plan["width_mm"])[0]
    except PredictionError:
        curve = None
    measured = _measured_dots(store, plan) if curve is not None and _dotted(plan) else None
    paint = _paint(store, _text_state(store, plan)) if curve is not None else []

    def draw() -> bytes:
        upload = _upload(plan)
        if curve is None:
            rgb8 = np.repeat((np.clip(upload["picture"], 0, 1) * 255).round().astype(np.uint8)[..., None], 3, axis=-1)
        elif _dotted(plan):
            rgb8 = _dot_look(store, plan, curve, THUMB_PX, measured)[1]
        else:
            _, rgb8 = ps.predicted(_shown(_item(store, plan), plan), plan["min_power"], plan["max_power"])
        rgb8 = _drawn(paint, plan["width_mm"], rgb8)
        rows, cols = rgb8.shape[:2]
        scale = min(1.0, THUMB_PX / max(rows, cols))
        small = cv2.resize(rgb8, (max(1, round(cols * scale)), max(1, round(rows * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else rgb8
        return prediction.to_png(small)
    key = rc.key_of({"kind": "photo-work-thumbnail", "px": THUMB_PX, "image": rc.file_stamp(plan["image_path"]), "unmeasured": True}) \
        if curve is None else _key("photo-work-thumbnail", plan, curve, measured, paint)
    return rc.Picture(store, _folder(plan["id"]), key, draw)


def original(store: Store, plan_id: int) -> tuple[bytes, str]:
    """The picture as it was uploaded, with its media type."""
    plan = _work(store, plan_id)
    try:
        data = Path(plan["image_path"]).read_bytes()
    except OSError:
        raise KeyError("the stored picture of this work is missing") from None
    return data, mimetypes.guess_type(plan["image_name"] or "")[0] or "application/octet-stream"


def closeup(store: Store, plan_id: int) -> rc.Picture:
    """The dots of a work in a dot kind dot for dot from the middle of the picture (``prediction_store.dot_closeup``)."""
    plan = _work(store, plan_id)
    if not _dotted(plan):
        raise su.ValidationError("a work in grayscale has no dots to show")
    curve, _ = ps.curve_for(store, mode_of(plan), plan["width_mm"])

    def draw() -> bytes:
        dots = st.dots(store, plan, curve)
        return prediction.to_png(ps.dot_closeup(_item(store, plan), plan["kind"], dots["lab"], dots["clean_lab"], plan["width_mm"],
                                                st.fired_at(mode_of(plan), plan)))
    return rc.Picture(store, _folder(plan["id"]), _key("photo-work-closeup", plan, curve), draw)


def kinds(store: Store, plan_id: int) -> dict:
    """«Какая гравировка?»: every kind that colours titanium (:data:`KINDS`) with the work's picture as it would come out in it, the one
    the work has marked. Grayscale on the work's Min and Max and greys; a dot kind at the work's dots' power, or where the scale's colour
    stands out most, estimated from the scale (``_dot_look``). With no measured scale there is nothing to show (``problem``)."""
    plan = _work(store, plan_id)
    mode = mode_of(plan)
    try:
        curve = ps.curve_for(store, mode, plan["width_mm"])[0]
        power = _dot_power(store, mode, plan["width_mm"], plan["dot_power"])
    except PredictionError as exc:
        return {"kind": plan["kind"], "kinds": [], "problem": str(exc)}
    dots = st.dots(store, {**plan, "dot_power": power}, curve)
    paint = _paint(store, _text_state(store, plan))
    out = []
    for key in KINDS:
        shown = {**plan, "kind": key, "dot_power": power}
        measured = _measured_dots(store, shown) if key != GRAYSCALE else None
        entry = {"key": key, "family": photo_modes.MODES[key].family, "basis": photo_modes.MODES[key].basis,
                 "estimate": key != GRAYSCALE and measured is None,
                 "picture": f"/api/photo-works/{plan['id']}/kinds/{key}.png?v={_key('photo-work-kind', shown, curve, measured, paint)[:16]}"}
        if key == GRAYSCALE:
            entry.update(min_power=plan["min_power"], max_power=plan["max_power"])
        else:
            entry.update(power=dots["power"], hex=dots["hex"], clean_hex=dots["clean_hex"], source=dots["source"])
        out.append(entry)
    return {"kind": plan["kind"], "kinds": out, "problem": None}


def dot_setup(store: Store, plan_id: int) -> str:
    """The laser and lens of the work's scale as the colour map keys them: the map the colour of its dots is picked on."""
    mode = mode_of(_work(store, plan_id))
    return su.setup_key(mode.device_id, mode.lens_id)


def dot_colours(store: Store, plan_id: int, points: list[dict]) -> dict:
    """For the colour map picking the colour of the work's dots: the work (its name, kind, width, laser and lens) and each colour of the
    map's ``points`` (of the work's laser and lens, :func:`dot_setup`) with what it gives the dots or why it cannot
    (``dot_colours.options``)."""
    plan = _work(store, plan_id)
    mode = mode_of(plan)
    return {"work": {"id": plan["id"], "name": plan["name"], "kind": plan["kind"], "width_mm": plan["width_mm"], "device_id": mode.device_id,
                     "lens_id": mode.lens_id, "material": _material(store, mode.material_id), "dot_recipe": plan["dot_recipe"]},
            **dc.options(store, mode, plan["width_mm"], points)}


def kind_picture(store: Store, plan_id: int, kind: str) -> rc.Picture:
    """The work's picture as it would come out in ``kind`` (``kinds``), the longer side TILE_PX."""
    plan = _work(store, plan_id)
    if kind not in KINDS:
        raise KeyError(f"no kind of engraving {kind!r}")
    mode = mode_of(plan)
    curve = ps.curve_for(store, mode, plan["width_mm"])[0]
    shown = {**plan, "kind": kind, "dot_power": _dot_power(store, mode, plan["width_mm"], plan["dot_power"])}
    measured = _measured_dots(store, shown) if _dotted(shown) else None
    paint = _paint(store, _text_state(store, plan))

    def draw() -> bytes:
        if _dotted(shown):
            return prediction.to_png(_drawn(paint, plan["width_mm"], _dot_look(store, shown, curve, TILE_PX, measured)[1]))
        _, rgb8 = ps.predicted(_shown(_item(store, shown), shown), shown["min_power"], shown["max_power"])
        rgb8 = _drawn(paint, plan["width_mm"], rgb8)
        rows, cols = rgb8.shape[:2]
        scale = min(1.0, TILE_PX / max(rows, cols))
        small = cv2.resize(rgb8, (max(1, round(cols * scale)), max(1, round(rows * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else rgb8
        return prediction.to_png(small)
    return rc.Picture(store, _folder(plan["id"]), rc.key_of({"tile": TILE_PX, "of": _key("photo-work-kind", shown, curve, measured, paint)}), draw)


def export(store: Store, plan_id: int) -> tuple[bytes, str]:
    """The LightBurn file of the work (the cleaning, then one Image layer in the work's kind, ``plans.export_picture``) and the name to
    save it under. A dot kind's layer fires every dot at the dots' power (Min = Max) and the settings they fire at (the scale's, or the
    recipe's picked on the colour map, whose step is the layer's DPI) and carries the picture as uploaded: LightBurn makes the dots.
    The picture is transparent under its inscriptions' cut, and their letters follow on a layer of each titanium colour (DEC-003); an
    inscription that cannot be engraved refuses the file."""
    plan = _work(store, plan_id)
    texts = _text_state(store, plan)
    if texts and texts["problem"]:
        raise su.ValidationError(texts["problem"])
    vectors = [{k: layer[k] for k in ("index", "name", "parameters", "shapes")} for layer in texts["layers"]] if texts else []
    item = _item(store, plan)
    if _dotted(plan):
        power = st.dots(store, plan, item["curve"])["power"]
        fired = st.fired_at(item["mode"], plan)
        picture = _holed(ps.picture_for_file(item, power, power, plan["width_mm"], fired=fired), texts, plan["width_mm"])
        data = pl.export_picture(picture, plan["width_mm"], ps.file_parameters(fired, power, power), plan["name"], plan["plan_identifier"],
                                 clean=ps.cleaning(store, item["mode"]), dither=plan["kind"], vectors=vectors)
        return data, f"{plan['name']}-{plan['kind']}-P{power:g}"
    low, high = ps.check_power_range(plan["min_power"], plan["max_power"])
    picture = _holed(ps.picture_for_file(item, low, high, plan["width_mm"], plan["rules"]), texts, plan["width_mm"])
    data = pl.export_picture(picture, plan["width_mm"], ps.file_parameters(item["mode"], low, high), plan["name"], plan["plan_identifier"],
                             clean=ps.cleaning(store, item["mode"]), vectors=vectors)
    return data, f"{plan['name']}-P{low:g}-{high:g}"


def _save(store: Store, plan: Mapping, plan_id: int | None = None, *, name: str | None = None, identifier: str | None = None) -> int:
    return cv.save_plan(store, plan_id, name=name or plan["name"], mode=MODE, status=cv.ST_DRAFT, device_id=plan["device_id"],
                        lens_id=plan["lens_id"], markers=False, identifier=identifier or plan["plan_identifier"], band_count=None,
                        data={k: plan[k] for k in DATA})


def create(store: Store, data: bytes, file_name: str, name, width_mm, scale=None) -> int:
    """A new work of an uploaded picture: on ``scale`` (a measured one) or on the best measured scale, at its measured Min and Max."""
    upload = ps.decode_upload(data)
    width = ps.check_width(width_mm)
    if scale is not None:
        mode = measured_scale(store, scale)
    else:
        found = ps.scales(store)
        if not found:
            raise su.ValidationError("no grayscale scale is measured yet: engrave the grey-scale plate and add its photograph first")
        mode = ps.Mode(**found[0]["mode"])
    title = name.strip() if isinstance(name, str) and name.strip() else (Path(file_name or "").stem or "picture")
    low, high = _span(store, mode, width)
    cols, rows = upload["size"]
    plan = {"device_id": mode.device_id, "lens_id": mode.lens_id, "image_path": cv._store_image(store, data), "image_name": file_name,
            "image_size": [cols, rows], "scale": _scale_data(mode), "min_power": low, "max_power": high, "width_mm": width,
            "by_colour": False, "colour_choice": drawing.CHOICES[0], "contours": False, "rules": [], "colouring": {}, "kind": GRAYSCALE,
            "dot_power": None, "dot_recipe": None, "ai_photo": False, "ai": None, "ai_theme": None, "undo": [], "redo": [], "updated_at": now(),
            "texts": []}
    with store.transaction():
        plan_id = _save(store, plan, name=title, identifier=pl.new_identifier(IDENTIFIER_PREFIX))
        store.audit("photo_work_created", plan_id=plan_id)
    _remember(plan["image_path"], upload)
    return plan_id


def update(store: Store, plan_id: int, changes) -> None:
    """Change what the work is engraved with: ``scale`` (Min and Max then become its measured span unless they are given too),
    ``min_power`` and ``max_power``, ``width_mm``, ``by_colour`` and how (``colour_choice``), ``contours``, the main colours of the
    picture's objects (``colouring``: an object's key to its ``power`` and ``shift``) and the ``rules`` of the parts, the ``kind`` of
    engraving and the power of a dot kind's dots (``dot_power``, inside the scale's measured powers at the work's width;
    kept through another kind, scale or width while the scale is measured there, otherwise where its colour stands out most), the colour
    of a dot kind's dots picked on the colour map (``dot_colour``, a point's group, ``dot_colours.picked``: a tone of a grey scale puts the
    dots on that scale at its power, a fill makes them fire at its settings, kept as ``dot_recipe`` and its colour taken again when the
    width changes; another scale or a power on the scale puts them back on the scale), or whether the picture may be sent to the AI
    (``ai_photo``). A change of what is engraved can be undone."""
    plan = _work(store, plan_id)
    before = _here(plan)
    if not isinstance(changes, Mapping) or not changes or not set(changes) <= set(SETTINGS):
        raise su.ValidationError("change the scale, Min and Max power, the width, the colour choice, the contours, the colours of the objects, the "
                                 "rules of the parts, the kind of engraving, the power of its dots or their colour on the colour map")
    if "width_mm" in changes:
        width = ps.check_width(changes["width_mm"])
        plan["texts"] = lettering.scaled(plan["texts"], width / plan["width_mm"])     # they keep their place on the picture (DEC-004)
        plan["width_mm"] = width
    recipe = None
    if "dot_colour" in changes:
        if not _dotted({"kind": changes.get("kind", plan["kind"])}):
            raise su.ValidationError("the dots' colour is picked for a dot kind: choose one of them first")
        picked = dc.picked(store, mode_of(plan), plan["width_mm"], changes["dot_colour"])
        recipe = picked.pop("dot_recipe", None)
        changes = {**{k: v for k, v in changes.items() if k != "dot_colour"}, **picked}
    if "scale" in changes:
        mode = measured_scale(store, changes["scale"])
        plan.update(scale=_scale_data(mode), device_id=mode.device_id, lens_id=mode.lens_id, dot_recipe=None)
        if "min_power" not in changes and "max_power" not in changes:
            plan["min_power"], plan["max_power"] = _span(store, mode, plan["width_mm"])
    st.change(store, plan, {k: v for k, v in changes.items() if k not in ("scale", "width_mm")}, mode_of(plan), plan["width_mm"],
              moved=bool({"scale", "width_mm"} & set(changes)))
    if recipe is not None:
        plan["dot_recipe"] = recipe
    elif "width_mm" in changes and plan["dot_recipe"]:
        plan["dot_recipe"] = dc.at_width(store, mode_of(plan), plan["dot_recipe"], plan["width_mm"])
    if _here(plan) != before:
        _push(plan, before)
    plan["updated_at"] = now()
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("photo_work_changed", plan_id=plan["id"], changed=sorted(changes))


# -- undo and redo (as the vector editor's, DEC-077) ------------------------------------------------------------------------------
def _here(plan: Mapping) -> dict:
    return copy.deepcopy({k: plan[k] for k in STATE})


def _push(plan: dict, before: dict) -> None:
    """After a change: the state ``before`` it can be undone (the last UNDO_DEPTH steps), what was undone is not redone any more."""
    plan["undo"], plan["redo"] = (plan["undo"] + [before])[-UNDO_DEPTH:], []


def step(store: Store, plan_id: int, direction: str) -> None:
    """Undo (``direction`` "undo") or redo ("redo") one change: the state on top of that stack comes back, the present one goes onto the
    other. A state on a scale measured no more comes back too; the work then says that its scale must be chosen again."""
    plan = _work(store, plan_id)
    if not plan[direction]:
        raise cv.ConversionError("there is no earlier change of the work to undo" if direction == "undo" else "there is no undone change to redo")
    there = plan[direction].pop()
    plan["redo" if direction == "undo" else "undo"].append(_here(plan))
    plan.update(copy.deepcopy(there))
    plan["updated_at"] = now()
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("photo_work_" + direction, plan_id=plan["id"])


def copy_work(store: Store, plan_id: int, name=None) -> int:
    """A work of its own made from this one, with its own copy of the picture and a new identifier; the first stays as it is."""
    plan = _work(store, plan_id)
    if name is None:
        title = plan["name"] + COPY_SUFFIX
    elif isinstance(name, str) and name.strip():
        title = name.strip()
    else:
        raise cv.ConversionError("give the plan a name")
    try:
        data = Path(plan["image_path"]).read_bytes()
    except OSError:
        raise KeyError("the stored picture of this work is missing") from None
    fresh = {**plan, "image_path": cv._store_image(store, data), "undo": [], "redo": [], "updated_at": now()}
    with store.transaction():
        new_id = _save(store, fresh, name=title, identifier=pl.new_identifier(IDENTIFIER_PREFIX))
        store.audit("photo_work_copied", plan_id=new_id, source_plan_id=plan["id"])
    return new_id


def rename_work(store: Store, plan_id: int, name) -> str:
    """Give a work another name and return it as stored; nothing else changes."""
    plan = _work(store, plan_id)
    if not isinstance(name, str) or not name.strip():
        raise cv.ConversionError("give the plan a name")
    title = name.strip()
    if title != plan["name"]:
        with store.transaction():
            store.execute("UPDATE plan SET name=? WHERE id=?", (title, plan["id"]))
            store.audit("photo_work_renamed", plan_id=plan["id"], old_name=plan["name"], new_name=title)
    return title


# -- a ramp at the work's width (DEC-107) ----------------------------------------------------------------------------------------------
RAMP_MARGIN_MM = 19.0                # what a grey-ramp plate adds to its widest ramp: the labels, the markers and their margins


def width_ramp(store: Store, plan_id: int) -> dict:
    """A grey-ramp plate of one ramp as wide as the work, at its scale's settings, Min and Max: engraved and photographed before the
    picture, it measures the scale at the size the picture is engraved at (the colour depends on the length of the rows, DEC-107). In a
    dot kind the ramp is engraved in that kind at the dots' power («Проба этого вида»): its photograph measures the kind's tones, which
    then replace the estimate from the scale. A plate is made for the lens on the laser now, so the work's lens must be on it."""
    plan = _work(store, plan_id)
    mode = mode_of(plan)
    lens = devices.get_device(store, plan["device_id"]).get("lens") or {}
    if lens.get("id") != plan["lens_id"]:
        raise su.ValidationError("the laser has another lens on it than this work's scale was measured with: put that lens on the laser first")
    width = float(plan["width_mm"])
    dotted = _dotted(plan)
    fired = st.kind_mode(mode, plan) if dotted else mode            # a dot kind at the settings and power its dots fire at
    fixed = {k: v for k, v in {"speed": fired.speed, "frequency": fired.frequency, "pulse_width": fired.pulse_width, "line_interval": fired.line_interval,
                               "passes": fired.passes, "global_passes": fired.global_passes}.items() if v is not None}
    powers = {"dither": plan["kind"]} if dotted else {"min_power": plan["min_power"], "max_power": plan["max_power"]}
    settings = {**fixed, "power": fired.power if dotted else plan["max_power"], "max_width_mm": min(cp.PLATE_MAX_MM, width + RAMP_MARGIN_MM),
                "scales": {"rows": {"axis": "width", "values": [width]}, "columns": {"axis": "speed", "values": [fired.speed]}, **powers}}
    made = cp.create(store, plan["device_id"], mode.material_id, "grey_scales", settings)
    store.audit("photo_work_width_ramp", plan_id=plan["id"], ramp_plan_id=made["plan_id"], width_mm=width, kind=plan["kind"])
    return made


# -- the engravings of the work (0.19.3) --------------------------------------------------------------------------------------------
def _engraved_layer(check: Mapping) -> dict | None:
    """The picture layer a photograph measured: the first layer with a tonal profile."""
    return next((rep for rep in check.get("layers", []) if rep.get("tonal")), None)


def engravings(store: Store, plan_id: int) -> list[dict]:
    """Every photograph linked to the work (its file names the work, or it was uploaded for it), the newest first: its state, the
    settings, Min and Max and row length (its width as engraved, ``row_mm``) it was engraved with and, once accepted, each grey of it
    against the colour the other engravings of those settings predict at its size (``prediction_store.engraving_check``). An engraving
    with other settings than the work's scale (or on another titanium) is checked on its own settings and says so."""
    plan = _work(store, plan_id)
    work_mode = mode_of(plan)
    plates = su.same_titanium(store, work_mode.material_id) if work_mode.material_id is not None else [None]
    out = []
    for row in store.query("SELECT id, status, device_id, lens_id, material_id, photo_name, lightburn_name, lightburn_path, created_at, accepted_at, "
                           "data_json FROM pair WHERE plan_id=? AND status!=? ORDER BY id DESC", (plan["id"], ig.ST_DELETED)):
        rep = _engraved_layer(json.loads(row["data_json"] or "{}").get("check") or {})
        item = {"pair_id": row["id"], "status": row["status"], "photo_name": row["photo_name"], "lightburn_name": row["lightburn_name"],
                "created_at": row["created_at"], "accepted_at": row["accepted_at"], "settings": None, "same_scale": None, "mode": None, "check": None,
                "row_mm": None if rep is None else row_length.of_file(row["lightburn_path"]).get(rep["index"])}
        if rep is not None:
            settings = {"speed": rep.get("speed"), "frequency": rep.get("frequency_khz"), "pulse_width": rep.get("pulse_width"),
                        "line_interval": rep.get("line_interval"), "passes": rep.get("passes"), "global_passes": rep.get("global_passes")}
            dither = (rep.get("image") or {}).get("dither") or prediction.PREDICTED_MODE
            same = ((row["device_id"], row["lens_id"], dither) == (work_mode.device_id, work_mode.lens_id, work_mode.dither)
                    and row["material_id"] in plates and work_mode.matches(settings))          # any plate of the work's titanium (DEC-110)
            mode = work_mode if same else ps.mode_of(settings, row["device_id"], row["lens_id"], row["material_id"], dither)
            item.update(settings={**settings, "power_range": rep["tonal"].get("power_range"), "evidence": rep["tonal"].get("evidence")},
                        same_scale=same, mode=mode.as_dict())
            if row["status"] == ig.ST_ACCEPTED:
                try:
                    item["check"] = ps.engraving_check(store, mode, row["id"])
                except PredictionError:
                    item["check"] = {"reason": "no_points", "compared": 0, "bands": []}
                for band in item["check"]["bands"]:
                    band["hex"], band["predicted_hex"] = st.hex_of(band["lab"]), st.hex_of(band["predicted"])
        out.append(item)
    return out


# -- the parts of the picture and the AI (REQ-062, DEC-105) -------------------------------------------------------------------------
def _parts_key(plan: Mapping) -> str:
    return rc.key_of({"kind": "photo-work-parts", "image": rc.file_stamp(plan["image_path"]), "model": people.MODEL.name, "colours": ps.PART_COLOURS})


def parts(store: Store, plan_id: int) -> dict:
    """The parts the people model finds in the work's picture (each one's share of the picture and mean colour in it) and the address of
    the picture with each part tinted, to check what was found."""
    plan = _work(store, plan_id)
    return {"parts": st.parts_listed(_upload(plan)),
            "picture": f"/api/photo-works/{plan['id']}/parts.png?v={_parts_key(plan)[:16]}"}


def parts_picture(store: Store, plan_id: int) -> rc.Picture:
    """The work's picture with every part tinted in its colour (``prediction_store.PART_COLOURS``)."""
    plan = _work(store, plan_id)

    def draw() -> bytes:
        upload = _upload(plan)
        ps.part_scores(upload)
        return prediction.to_png(ps.parts_overlay(upload))
    return rc.Picture(store, _folder(plan["id"]), _parts_key(plan), draw)


# -- the objects of the picture and their colours (0.21.0) ----------------------------------------------------------------------------
def _objects_key(plan: Mapping) -> str:
    return rc.key_of({"kind": "photo-work-objects", "image": rc.file_stamp(plan["image_path"]), "model": people.MODEL.name, "tints": ob.TINTS,
                      "pieces": ob.PIECE_TINTS})


def objects_of(store: Store, plan_id: int) -> dict:
    """The objects of the work's picture to colour at the work's Min and Max (``photo_state.objects_listed``) and the address of the
    picture with them tinted."""
    plan = _work(store, plan_id)
    return {**st.objects_listed(store, mode_of(plan), _upload(plan), plan, plan["width_mm"]),
            "picture": f"/api/photo-works/{plan['id']}/objects.png?v={_objects_key(plan)[:16]}"}


def objects_picture(store: Store, plan_id: int) -> rc.Picture:
    """The work's picture with every object tinted in its colour (``objects.overlay``)."""
    plan = _work(store, plan_id)

    def draw() -> bytes:
        upload = _upload(plan)
        return prediction.to_png(ob.overlay(upload, st.objects(upload)))
    return rc.Picture(store, _folder(plan["id"]), _objects_key(plan), draw)


def colour_theme(store: Store, plan_id: int, name, seed=0) -> None:
    """Colour every object of the picture by the theme ``name`` (``photo_state.theme``) on the scale's colours at the work's Min and Max:
    the work then chooses its greys for the objects (one step to undo)."""
    st.theme_checked(name, seed)
    plan = _work(store, plan_id)
    update(store, plan_id, st.theme(store, mode_of(plan), _upload(plan), plan, plan["width_mm"], name, seed))


def _picture_bytes(plan: Mapping):
    return lambda: Path(plan["image_path"]).read_bytes()


def ai_theme(store: Store, plan_id: int, wish) -> None:
    """Ask the AI for the main colours of the picture's objects after the operator's ``wish`` (``photo_state.ai_theme``) and colour the
    work with them, keeping its note (one step to undo); a refused answer changes nothing."""
    plan = _work(store, plan_id)
    changes, answer = st.ai_theme(store, mode_of(plan), _upload(plan), plan, plan["width_mm"], wish, _picture_bytes(plan))
    plan = _work(store, plan_id)                             # as it is now: other changes made while the AI answered are kept
    _push(plan, _here(plan))
    plan.update({**changes, "updated_at": now(), "ai_theme": answer})
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("photo_work_ai_theme", plan_id=plan["id"], objects=len(changes["colouring"]), photo=answer["photo"])


def ask_ai(store: Store, plan_id: int, wish, fresh=False) -> None:
    """Ask the AI for the rules of the parts after the operator's ``wish`` (``photo_state.ai_rules``) and save them in the work with the
    AI's note and the rules before them. The answer can be undone; a refused answer changes nothing (``ai_picture.ask``)."""
    plan = _work(store, plan_id)
    rules, answer = st.ai_rules(store, mode_of(plan), _upload(plan), plan, plan["width_mm"], plan["name"], wish, fresh, _picture_bytes(plan))
    plan = _work(store, plan_id)                             # as it is now: other changes made while the AI answered are kept
    _push(plan, _here(plan))
    plan["ai"] = {**answer, "before": plan["rules"]}
    plan["rules"] = rules
    plan["updated_at"] = now()
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("photo_work_ai", plan_id=plan["id"], rules=len(rules), photo=answer["photo"], fresh=answer["fresh"])
