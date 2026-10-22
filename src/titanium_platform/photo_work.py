"""Photo engraving works (REQ-061, DEC-104): a picture engraved in LightBurn's grayscale mode on a measured scale, kept as a vector work
is (``vector_job``): the operator's works are listed, opened, copied, renamed and deleted, and each opens on one screen.

A work is a row of ``plan`` of its own mode (``plans.MODE_PHOTO_WORK``). The laser and lens are the row's columns; its data holds

* the picture as it was uploaded, stored once in the data folder (``image_path``), with its file name and size in pixels;
* the scale it is engraved on (``scale``): the titanium and the settings that do not vary with the grey, which with the laser and the
  lens make a ``prediction_store.Mode``; only a measured scale can be chosen;
* Min and Max power, the width on the titanium in mm and whether the greys are chosen for the picture's colours (``by_colour``);
* the rules of the picture's parts (``rules``, REQ-062): a part found by the people model (:mod:`people`) may be engraved by its own rule
  (:mod:`picture_rules`), set by hand or proposed by the AI (:mod:`ai_picture`); whether a reduced copy of the picture may be sent to
  the AI (``ai_photo``, off until the operator allows it) and the last request to it (``ai``: the wish, whether the picture went, the AI's
  note and the rules before it, so that they can be put back);
* the steps that can be undone and redone (``undo``, ``redo``): each holds the work's state as it decides what is engraved (:data:`STATE`);
* when it last changed (``updated_at``).

Everything shown is computed from these and the scale's measurements as they are now: the picture beside its prediction, the time
and the LightBurn file. The pictures go through the render cache (folder ``photo-work-<id>``), known by everything they are drawn
from, the scale's measured points included, so a new measurement draws them again. The decoded pictures of the works opened last are
kept in memory (``KEEP_DECODED``). The file carries no identifier yet (DEC-104): its engraving is measured as the operator's own photo
engravings are and counts towards the scale.
"""
from __future__ import annotations

import copy
import json
import math
import mimetypes
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Mapping

import cv2
import numpy as np

from . import (ai_colouring as ai, ai_picture, color, conversion as cv, grayscale, ingest as ig, people, picture_rules, plans as pl, prediction,
               prediction_store as ps, render_cache as rc, research, setup as su)
from .db import Store, now
from .prediction import PredictionError
from .vector_job import COPY_SUFFIX

MODE = pl.MODE_PHOTO_WORK
IDENTIFIER_PREFIX = "TCE-P"
THUMB_PX = 360                      # the longer side of the picture of a work in the list
KEEP_DECODED = 2                    # decoded pictures kept in memory: the work open now and the one before
PART_MIN_SHARE = 0.005              # a part covering less of the picture is not offered (to the operator or the AI): it is noise of the model
DATA = ("image_path", "image_name", "image_size", "scale", "min_power", "max_power", "width_mm", "by_colour", "rules", "ai_photo", "ai", "undo", "redo",
        "updated_at")
SETTINGS = ("scale", "min_power", "max_power", "width_mm", "by_colour", "rules", "ai_photo")
DEFAULTS = {"rules": [], "ai_photo": False, "ai": None, "undo": [], "redo": []}   # what a work made before the rules of parts (0.19.0) or undo has
# What one step of undo or redo brings back: everything that decides what the work engraves, and the AI's answer that led to it. The
# permission to send the picture to the AI is not part of it: undoing never allows more to be sent than the operator allows now.
STATE = ("scale", "device_id", "lens_id", "min_power", "max_power", "width_mm", "by_colour", "rules", "ai")
UNDO_DEPTH = 50                     # steps kept to undo and redo together, as the vector editor keeps

_decoded: OrderedDict[str, dict] = OrderedDict()
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


def measured_scale(store: Store, wanted) -> ps.Mode:
    """The measured scale named by ``wanted``: the laser, lens, titanium and fixed settings, as the list of scales gives them."""
    if isinstance(wanted, Mapping):
        for mode in ps.scale_modes(store):
            if (mode.device_id == wanted.get("device_id") and mode.lens_id == wanted.get("lens_id")
                    and mode.material_id == wanted.get("material_id") and mode.matches(wanted)):
                return mode
    raise su.ValidationError("this scale is not measured: choose one of the measured scales")


def _span(store: Store, mode: ps.Mode) -> tuple[float, float]:
    """The scale's measured powers rounded inwards to 0.1 %, so that the white and the black of a picture both stay inside them."""
    lo, hi = ps.curve_for(store, mode)[0].span
    low, high = math.ceil(lo * 10 - 1e-9) / 10, math.floor(hi * 10 + 1e-9) / 10
    return (low, high) if low <= high else (float(lo), float(hi))


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
    upload = _upload(plan)
    item = ps.picture_item(store, mode_of(plan), upload, plan["name"], plan["by_colour"])
    if plan["rules"]:
        item["part_scores"] = ps.part_scores(upload)         # the people model runs once per decoded picture
    return item


def _shown(item: dict, plan: Mapping) -> dict:
    """The item as it is engraved: its own greys, the greys chosen for its colours (``by_colour``) and, inside each part with a rule,
    that rule's greys."""
    if plan["rules"]:
        return ps.with_rules(item, plan["min_power"], plan["max_power"], plan["rules"])
    return ps.with_colours(item, plan["min_power"], plan["max_power"]) if plan["by_colour"] else item


def _key(kind: str, plan: Mapping, curve: prediction.Curve) -> str:
    """The key of a picture of the work: everything it is drawn from, the measured points of the scale included."""
    return rc.key_of({"kind": kind, "image": rc.file_stamp(plan["image_path"]), "mode": mode_of(plan).as_dict(),
                      "curve": rc.text_digest(json.dumps(curve.as_dict(), sort_keys=True, default=str)),
                      "min_power": plan["min_power"], "max_power": plan["max_power"], "by_colour": plan["by_colour"], "rules": plan["rules"]})


def _material(store: Store, material_id: int | None) -> dict | None:
    row = store.one("SELECT id, name, family, grade, batch, thickness_mm FROM material_profile WHERE id=?", (material_id,)) if material_id else None
    return dict(row) if row else None


def _summary(store: Store, plan: Mapping) -> dict:
    """What the list of works and the head of an open work say: the name, the size, the scale, Min and Max, the time and the dates."""
    cols, rows = plan["image_size"]
    width = plan["width_mm"]
    height = width * rows / cols
    mode = mode_of(plan)
    return {"id": plan["id"], "name": plan["name"], "identifier": plan["plan_identifier"], "created_at": plan["created_at"],
            "updated_at": plan.get("updated_at") or plan["created_at"], "image_name": plan["image_name"], "image_size": [cols, rows],
            "scale": mode.as_dict(), "material": _material(store, mode.material_id),
            "dpi": grayscale.image_dpi(mode.line_interval) if mode.line_interval else None,
            "min_power": plan["min_power"], "max_power": plan["max_power"], "width_mm": width, "height_mm": round(height, 2),
            "by_colour": plan["by_colour"], "rules": [_shown_rule(r) for r in plan["rules"]], "ai": plan["ai"], "ai_photo": plan["ai_photo"],
            "undo": len(plan["undo"]), "redo": len(plan["redo"]), "time": ps.picture_time(mode, width, height)}


def _shown_rule(rule: Mapping) -> dict:
    """A rule as the screen shows it: with its target colour also as #rrggbb, for the colour picker."""
    return {**rule, "hex": _hex(rule["lab"])} if "lab" in rule else dict(rule)


def listing(store: Store) -> list[dict]:
    """Every photo work, the newest first."""
    rows = store.query("SELECT id FROM plan WHERE mode=? AND status!='Deleted' ORDER BY id DESC", (MODE,))
    return [_summary(store, _work(store, row["id"])) for row in rows]


def view(store: Store, plan_id: int) -> dict:
    """An open work: its summary and the picture beside its predicted look with what is said about it (as the scales' picture says it,
    ``prediction_store.describe``), or, when its scale is no longer measured, why there is no prediction (``problem``)."""
    plan = _work(store, plan_id)
    out = {**_summary(store, plan), "ai_missing": _ai_missing()}
    try:
        item = _item(store, plan)
    except PredictionError as exc:
        return {**out, "picture": None, "problem": str(exc)}
    low, high = ps.check_power_range(plan["min_power"], plan["max_power"])
    shown = _shown(item, plan)
    info, rgb8 = ps.predicted(shown, low, high)
    key = _key("photo-work-preview", plan, item["curve"])
    if rc.read(store, _folder(plan["id"]), key) is None:       # drawn here already: the preview the screen asks for next is not drawn again
        try:
            rc.write(store, _folder(plan["id"]), key, prediction.to_png(prediction.side_by_side(shown["picture"], rgb8)))
        except OSError:
            pass
    out["picture"] = {**info, "by_colour": plan["by_colour"], "colour_match": shown.get("colour_match"), "rules_report": shown.get("rules_report"),
                      "size_mm": {"width": out["width_mm"], "height": out["height_mm"]}, "time": out["time"], "dpi": out["dpi"],
                      "preview": f"/api/photo-works/{plan['id']}/preview.png?v={key[:16]}", "file": f"/api/photo-works/{plan['id']}/export.lbrn2"}
    return out


def preview(store: Store, plan_id: int) -> rc.Picture:
    """The picture beside its predicted look (``prediction.side_by_side``), at preview size."""
    plan = _work(store, plan_id)
    curve, _ = ps.curve_for(store, mode_of(plan))

    def draw() -> bytes:
        shown = _shown(_item(store, plan), plan)
        _, rgb8 = ps.predicted(shown, plan["min_power"], plan["max_power"])
        return prediction.to_png(prediction.side_by_side(shown["picture"], rgb8))
    return rc.Picture(store, _folder(plan["id"]), _key("photo-work-preview", plan, curve), draw)


def thumbnail(store: Store, plan_id: int) -> rc.Picture:
    """The work in the list: its predicted look on the titanium, or the picture as LightBurn sees it while its scale is not measured."""
    plan = _work(store, plan_id)
    try:
        curve = ps.curve_for(store, mode_of(plan))[0]
    except PredictionError:
        curve = None

    def draw() -> bytes:
        upload = _upload(plan)
        if curve is None:
            rgb8 = np.repeat((np.clip(upload["picture"], 0, 1) * 255).round().astype(np.uint8)[..., None], 3, axis=-1)
        else:
            _, rgb8 = ps.predicted(_shown(_item(store, plan), plan), plan["min_power"], plan["max_power"])
        rows, cols = rgb8.shape[:2]
        scale = min(1.0, THUMB_PX / max(rows, cols))
        small = cv2.resize(rgb8, (max(1, round(cols * scale)), max(1, round(rows * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else rgb8
        return prediction.to_png(small)
    key = rc.key_of({"kind": "photo-work-thumbnail", "px": THUMB_PX, "image": rc.file_stamp(plan["image_path"]), "unmeasured": True}) \
        if curve is None else _key("photo-work-thumbnail", plan, curve)
    return rc.Picture(store, _folder(plan["id"]), key, draw)


def original(store: Store, plan_id: int) -> tuple[bytes, str]:
    """The picture as it was uploaded, with its media type."""
    plan = _work(store, plan_id)
    try:
        data = Path(plan["image_path"]).read_bytes()
    except OSError:
        raise KeyError("the stored picture of this work is missing") from None
    return data, mimetypes.guess_type(plan["image_name"] or "")[0] or "application/octet-stream"


def export(store: Store, plan_id: int) -> tuple[bytes, str]:
    """The LightBurn file of the work (one grayscale Image layer, ``plans.export_picture``) and the name to save it under."""
    plan = _work(store, plan_id)
    item = _item(store, plan)
    low, high = ps.check_power_range(plan["min_power"], plan["max_power"])
    picture = ps.picture_for_file(item, low, high, plan["width_mm"], plan["rules"])
    data = pl.export_picture(picture, plan["width_mm"], ps.file_parameters(item["mode"], low, high), plan["name"], plan["plan_identifier"])
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
    low, high = _span(store, mode)
    cols, rows = upload["size"]
    plan = {"device_id": mode.device_id, "lens_id": mode.lens_id, "image_path": cv._store_image(store, data), "image_name": file_name,
            "image_size": [cols, rows], "scale": _scale_data(mode), "min_power": low, "max_power": high, "width_mm": width,
            "by_colour": False, "rules": [], "ai_photo": False, "ai": None, "undo": [], "redo": [], "updated_at": now()}
    with store.transaction():
        plan_id = _save(store, plan, name=title, identifier=pl.new_identifier(IDENTIFIER_PREFIX))
        store.audit("photo_work_created", plan_id=plan_id)
    _remember(plan["image_path"], upload)
    return plan_id


def update(store: Store, plan_id: int, changes) -> None:
    """Change what the work is engraved with: ``scale`` (Min and Max then become its measured span unless they are given too),
    ``min_power`` and ``max_power``, ``width_mm``, ``by_colour`` and the ``rules`` of the parts, or whether the picture may be sent to the
    AI (``ai_photo``). A change of what is engraved can be undone."""
    plan = _work(store, plan_id)
    before = _here(plan)
    if not isinstance(changes, Mapping) or not changes or not set(changes) <= set(SETTINGS):
        raise su.ValidationError("change the scale, Min and Max power, the width, the colour choice or the rules of the parts of the work")
    if "scale" in changes:
        mode = measured_scale(store, changes["scale"])
        plan.update(scale=_scale_data(mode), device_id=mode.device_id, lens_id=mode.lens_id)
        if "min_power" not in changes and "max_power" not in changes:
            plan["min_power"], plan["max_power"] = _span(store, mode)
    if "min_power" in changes or "max_power" in changes:
        plan["min_power"], plan["max_power"] = ps.check_power_range(changes.get("min_power", plan["min_power"]), changes.get("max_power", plan["max_power"]))
    if "width_mm" in changes:
        plan["width_mm"] = ps.check_width(changes["width_mm"])
    if "by_colour" in changes:
        if not isinstance(changes["by_colour"], bool):
            raise su.ValidationError("the colour choice must be on or off")
        plan["by_colour"] = changes["by_colour"]
    if "rules" in changes:
        plan["rules"] = _rules_in(changes["rules"])
    if "ai_photo" in changes:
        if not isinstance(changes["ai_photo"], bool):
            raise su.ValidationError("the permission to send the photograph must be on or off")
        plan["ai_photo"] = changes["ai_photo"]
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


# -- the engravings of the work (0.19.3) --------------------------------------------------------------------------------------------
def _engraved_layer(check: Mapping) -> dict | None:
    """The picture layer a photograph measured: the first layer with a tonal profile."""
    return next((rep for rep in check.get("layers", []) if rep.get("tonal")), None)


def engravings(store: Store, plan_id: int) -> list[dict]:
    """Every photograph linked to the work (its file names the work, or it was uploaded for it), the newest first: its state, the
    settings and Min and Max it was engraved with and, once accepted, each grey of it against the colour the other engravings of those
    settings predict (``prediction_store.engraving_check``). An engraving with other settings than the work's scale is checked on its
    own settings and says so."""
    plan = _work(store, plan_id)
    work_mode = mode_of(plan)
    out = []
    for row in store.query("SELECT id, status, device_id, lens_id, material_id, photo_name, lightburn_name, created_at, accepted_at, data_json "
                           "FROM pair WHERE plan_id=? AND status!=? ORDER BY id DESC", (plan["id"], ig.ST_DELETED)):
        rep = _engraved_layer(json.loads(row["data_json"] or "{}").get("check") or {})
        item = {"pair_id": row["id"], "status": row["status"], "photo_name": row["photo_name"], "lightburn_name": row["lightburn_name"],
                "created_at": row["created_at"], "accepted_at": row["accepted_at"], "settings": None, "same_scale": None, "mode": None, "check": None}
        if rep is not None:
            settings = {"speed": rep.get("speed"), "frequency": rep.get("frequency_khz"), "pulse_width": rep.get("pulse_width"),
                        "line_interval": rep.get("line_interval"), "passes": rep.get("passes"), "global_passes": rep.get("global_passes")}
            dither = (rep.get("image") or {}).get("dither") or prediction.PREDICTED_MODE
            same = (row["device_id"], row["lens_id"], row["material_id"], dither) == (work_mode.device_id, work_mode.lens_id, work_mode.material_id,
                                                                                      work_mode.dither) and work_mode.matches(settings)
            mode = work_mode if same else ps.mode_of(settings, row["device_id"], row["lens_id"], row["material_id"], dither)
            item.update(settings={**settings, "power_range": rep["tonal"].get("power_range"), "evidence": rep["tonal"].get("evidence")},
                        same_scale=same, mode=mode.as_dict())
            if row["status"] == ig.ST_ACCEPTED:
                try:
                    item["check"] = ps.engraving_check(store, mode, row["id"])
                except PredictionError:
                    item["check"] = {"reason": "no_points", "compared": 0, "bands": []}
                for band in item["check"]["bands"]:
                    band["hex"], band["predicted_hex"] = _hex(band["lab"]), _hex(band["predicted"])
        out.append(item)
    return out


def _hex(lab) -> str:
    rgb = np.clip(color.lab_to_srgb8(np.asarray([lab], float)), 0, 255).round().astype(int)[0]
    return "#%02x%02x%02x" % tuple(rgb)


# -- the parts of the picture and the AI (REQ-062, DEC-105) -------------------------------------------------------------------------
def _with_lab(rule):
    """A rule whose target colour is given by hand as ``hex`` (#rrggbb), with it as L*a*b*, as the rules keep it."""
    if not isinstance(rule, Mapping) or "hex" not in rule or "lab" in rule:
        return rule
    hexed = rule["hex"]
    if not isinstance(hexed, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", hexed):
        raise su.ValidationError("a target colour must be given as #rrggbb")
    lab = color.srgb8_to_lab(np.array([[int(hexed[i:i + 2], 16) for i in (1, 3, 5)]], float))[0]
    return {**{k: v for k, v in rule.items() if k != "hex"}, "lab": [round(float(v), 2) for v in lab]}


def _rules_in(rules) -> list[dict]:
    """The rules of the parts as given by hand, checked (``picture_rules.check``); ``as_is`` is a part without a rule."""
    try:
        checked = picture_rules.check([_with_lab(r) for r in rules] if isinstance(rules, list) else rules)
    except picture_rules.RuleError as exc:
        raise su.ValidationError(str(exc)) from None
    return [r for r in checked if r["kind"] != "as_is"]


def _ai_missing() -> str | None:
    """Why the AI cannot run on this computer: ``library`` (the client library is not installed), ``key`` (no key is set) or None."""
    if not research.ai_library():
        return "library"
    return None if research.ai_available() else "key"


def _parts_key(plan: Mapping) -> str:
    return rc.key_of({"kind": "photo-work-parts", "image": rc.file_stamp(plan["image_path"]), "model": people.MODEL.name, "colours": ps.PART_COLOURS})


def _parts_found(upload: dict) -> list[dict]:
    ps.part_scores(upload)                                   # kept with the decoded picture: the model runs once for it
    return [p for p in ps.parts_of(upload) if p["share"] >= PART_MIN_SHARE]


def parts(store: Store, plan_id: int) -> dict:
    """The parts the people model finds in the work's picture (each one's share of the picture and mean colour in it) and the address of
    the picture with each part tinted, to check what was found."""
    plan = _work(store, plan_id)
    tint = {name: "#%02x%02x%02x" % rgb for name, rgb in zip(people.PARTS, ps.PART_COLOURS)}
    return {"parts": [{**p, "tint": tint[p["part"]]} for p in _parts_found(_upload(plan))],
            "picture": f"/api/photo-works/{plan['id']}/parts.png?v={_parts_key(plan)[:16]}"}


def parts_picture(store: Store, plan_id: int) -> rc.Picture:
    """The work's picture with every part tinted in its colour (``prediction_store.PART_COLOURS``)."""
    plan = _work(store, plan_id)

    def draw() -> bytes:
        upload = _upload(plan)
        ps.part_scores(upload)
        return prediction.to_png(ps.parts_overlay(upload))
    return rc.Picture(store, _folder(plan["id"]), _parts_key(plan), draw)


def ask_ai(store: Store, plan_id: int, wish, fresh=False) -> None:
    """Ask the AI for the rules of the parts after the operator's ``wish`` and save them in the work with the AI's note and the rules
    before them; the AI sees the present rules and changes what the wish asks, or with ``fresh`` starts from the plain picture (it is not
    told the present rules, its answer replaces them). The answer can be undone; a refused answer changes nothing (``ai_picture.ask``)."""
    plan = _work(store, plan_id)
    text = ai_picture.request(wish)
    if not isinstance(fresh, bool):
        raise su.ValidationError("starting again from the picture must be on or off")
    if not research.ai_available():
        raise cv.ConversionError("the AI is off: no key for the language model is set (OPENAI_API_KEY)")
    try:
        client = research.openai_client()
    except Exception:                        # a missing or broken library: its own text names paths and is of no use to the operator
        raise cv.ConversionError("the AI could not be started on this computer: a library it needs is missing or broken, install the app's dependencies (see README)") from None
    upload = _upload(plan)
    item = ps.picture_item(store, mode_of(plan), upload, plan["name"], plan["by_colour"])
    low, high = ps.check_power_range(plan["min_power"], plan["max_power"])
    found = _parts_found(upload)
    what = ai_picture.brief(text, found, grayscale.scale_of_greys(item["curve"], low, high), [] if fresh else plan["rules"])
    photo = ai.photo_data_url(Path(plan["image_path"]).read_bytes()) if plan["ai_photo"] else None
    rules, note = ai_picture.ask(client, what, photo, {p["part"] for p in found})
    plan = _work(store, plan_id)                             # as it is now: other changes made while the AI answered are kept
    _push(plan, _here(plan))
    plan["ai"] = {"wish": text, "photo": photo is not None, "fresh": fresh, "note": note, "at": now(), "before": plan["rules"]}
    plan["rules"] = rules
    plan["updated_at"] = now()
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("photo_work_ai", plan_id=plan["id"], rules=len(rules), photo=photo is not None, fresh=fresh)
