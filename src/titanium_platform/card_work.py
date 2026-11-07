"""Business card works (feature-2, REQ-001..005): a two-sided titanium card composed on a physically sized canvas and prepared, side by
side, for non-colour engraving in LightBurn.

A work is a row of ``plan`` of its own mode (:data:`plans.MODE_CARD_WORK`); the laser and lens are the row's columns (taken from the
workshop's creation context) and everything else is a JSON document in ``data_json``:

* ``size_mm`` and ``preset``: the card, 85 x 53 mm, 85 x 54 mm or a custom size (DEC-029);
* ``sides``: ``front`` and ``back``, each a list of elements in drawing order (the last is on top, DEC-032);
* ``settings``: the engraving settings the operator defines (power, speed, frequency, line interval ...; nothing is defaulted, DEC-033)
  and the ``default_settings_id`` of the elements that name none;
* ``undo`` / ``redo``: the steps that can be taken back (:data:`STATE`), as the photo work keeps them;
* ``updated_at`` and the id counters.

An element is ``{id, type, name, x, y, width, height, rotation, group, settings_id}`` plus one payload object named like its type:
``text`` (the lettering fields), ``shape`` / ``frame`` / ``icon`` (:mod:`card_library`), ``image`` (a stored picture and how it is traced,
:mod:`card_image`) or ``qr`` (:mod:`card_qr`). ``x``/``y`` is its centre in millimetres on the card (origin top-left, y down) and
``rotation`` is in degrees, clockwise on the screen.

Every element reduces to one shapely geometry in the card's millimetres. The screen draws that geometry, the preview shows it and the
LightBurn file of a side writes it, so what the operator sees is what is engraved. The file carries no cleaning layer: a card is
engraved, not colour-marked, and the operator's settings are written as given.
"""
from __future__ import annotations

import copy
import json
import math
import shutil
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Mapping

import shapely
from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box as shapely_box

from . import (card_generate, card_image, card_library, card_qr, conversion as cv, creation_context as cc, fonts, lettering, plans as pl,
               render_cache as rc, setup as su)
from .db import Store, now

MODE = pl.MODE_CARD_WORK
IDENTIFIER_PREFIX = "TCE-C"
SIDES = ("front", "back")
TYPES = ("text", "shape", "frame", "icon", "image", "qr")
PRESETS = [{"id": "85x53", "width": 85.0, "height": 53.0, "label": "85 × 53 mm"},
           {"id": "85x54", "width": 85.0, "height": 54.0, "label": "85 × 54 mm"}]
CUSTOM = "custom"
MIN_CARD_MM, MAX_CARD_MM = 10.0, 300.0
MIN_ELEMENT_MM, MAX_ELEMENT_MM = 0.2, 500.0
MAX_ELEMENTS = 300                      # on one side
MAX_NAME = 80
UNDO_DEPTH = 50
COPY_SHIFT_MM = 2.0
KEEP_GEOMETRIES = 512
KEEP_IMAGES = 4
OUTSIDE_TOLERANCE_MM = 0.05
DEFAULT_QR_MM = 18.0
IMAGE_LONG_SIDE_MM = 30.0
TEXT_KEYS = ("text", "font", "height_mm", "align", "width_pct", "spacing_mm", "line_pct")
TEXT_DEFAULT = {"text": "Text", "font": None, "height_mm": 5.0, "align": "center", "width_pct": 100.0, "spacing_mm": 0.0, "line_pct": 100.0}
SETTING_FIELDS = {"power": (0.0, 100.0, "power (%)"), "speed": (0.0, 100000.0, "speed (mm/s)"),
                  "frequency": (0.0, 10000.0, "frequency (kHz)"), "pulse_width": (0.0, 10000.0, "pulse width (ns)"),
                  "line_interval": (0.0, 10.0, "line interval (mm)")}
MODES = ("fill", "line")
DATA = ("size_mm", "preset", "sides", "settings", "default_settings_id", "next_id", "next_settings_id", "undo", "redo", "updated_at")
# What one step of undo or redo brings back: everything that decides what the card engraves.
STATE = ("size_mm", "preset", "sides", "settings", "default_settings_id", "next_id", "next_settings_id")
EDIT_OPS = ("add", "set", "move", "resize", "rotate", "reorder", "duplicate", "delete", "group", "ungroup", "assign_settings",
            "settings_add", "settings_set", "settings_delete", "set_size")

_lock = threading.Lock()
_geometries: OrderedDict[str, tuple] = OrderedDict()
_decoded: OrderedDict[str, object] = OrderedDict()


# -- numbers and small helpers --------------------------------------------------------------------------------------------------------
def _number(value, label: str, low: float, high: float) -> float:
    try:
        number = math.nan if isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number) or not low <= number <= high:
        raise su.ValidationError(f"{label} must be a number from {low:g} to {high:g}")
    return round(number, 4)


def _name(value, label: str = "the name") -> str:
    if not isinstance(value, str) or not value.strip():
        raise su.ValidationError(f"give {label} some text")
    return value.strip()[:MAX_NAME]


def _polygons(geometry) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, (MultiPolygon, GeometryCollection)):
        return [p for g in geometry.geoms for p in _polygons(g)]
    return []


def _fmt(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def path_d(geometry) -> str:
    """The SVG path data of a geometry in the card's millimetres: one closed sub-path per ring, to be filled with the even-odd rule."""
    parts = []
    for polygon in _polygons(geometry):
        for ring in (polygon.exterior, *polygon.interiors):
            points = list(ring.coords)[:-1]
            if len(points) >= 3:
                parts.append("M" + "L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in points) + "Z")
    return "".join(parts)


def _rings(geometry) -> list[list[list[float]]]:
    """The loops of every polygon of a geometry as the LightBurn writer wants them: the outline, then its holes, not closed twice."""
    return [[[round(x, 5), round(y, 5)] for x, y in list(ring.coords)[:-1]] for polygon in _polygons(geometry)
            for ring in (polygon.exterior, *polygon.interiors) if len(ring.coords) > 3]


# -- the work -------------------------------------------------------------------------------------------------------------------------
def _work(store: Store, plan_id: int) -> dict:
    plan = pl.get_plan(store, plan_id)
    if plan["status"] == "Deleted" or plan["mode"] != MODE:
        raise KeyError(f"business card work {plan_id} not found")
    return plan


def size_mm(plan: Mapping) -> dict:
    return {"width": float(plan["size_mm"]["width"]), "height": float(plan["size_mm"]["height"])}


def _blank_settings(settings_id: int, name: str) -> dict:
    return {"id": settings_id, "name": name, "mode": "fill", "power": None, "speed": None, "frequency": None, "pulse_width": None,
            "line_interval": None, "passes": 1}


def _card_size(preset, width_mm=None, height_mm=None) -> tuple[str, dict]:
    for item in PRESETS:
        if preset == item["id"]:
            return item["id"], {"width": item["width"], "height": item["height"]}
    if preset != CUSTOM:
        raise su.ValidationError("choose a card size: 85 × 53 mm, 85 × 54 mm or a custom size")
    return CUSTOM, {"width": _number(width_mm, "the card width (mm)", MIN_CARD_MM, MAX_CARD_MM),
                    "height": _number(height_mm, "the card height (mm)", MIN_CARD_MM, MAX_CARD_MM)}


def _save(store: Store, plan: Mapping, plan_id: int | None = None, *, name: str | None = None, identifier: str | None = None) -> int:
    return cv.save_plan(store, plan_id, name=name or plan["name"], mode=MODE, status=cv.ST_DRAFT, device_id=plan["device_id"],
                        lens_id=plan["lens_id"], markers=False, identifier=identifier or plan["plan_identifier"], band_count=None,
                        data={k: plan[k] for k in DATA})


def create(store: Store, name, preset=PRESETS[0]["id"], width_mm=None, height_mm=None) -> int:
    """A new, empty card work on the laser of the workshop's creation context; returns its id."""
    context = cc.get(store)
    if context["device_id"] is None:
        raise su.ValidationError("add the laser first: a card is engraved with a laser of the workshop")
    chosen, size = _card_size(preset, width_mm, height_mm)
    title = _name(name, "the card") if isinstance(name, str) and name.strip() else "Business card"
    plan = {"device_id": context["device_id"], "lens_id": context["lens_id"], "size_mm": size, "preset": chosen,
            "sides": {side: {"elements": []} for side in SIDES}, "settings": [_blank_settings(1, "Engraving 1")], "default_settings_id": 1,
            "next_id": 1, "next_settings_id": 2, "undo": [], "redo": [], "updated_at": now()}
    with store.transaction():
        plan_id = _save(store, plan, name=title, identifier=pl.new_identifier(IDENTIFIER_PREFIX))
        store.audit("card_work_created", plan_id=plan_id)
    return plan_id


def listing(store: Store) -> list[dict]:
    rows = store.query("SELECT id, name, data_json FROM plan WHERE mode=? AND status!='Deleted' ORDER BY id DESC", (MODE,))
    out = []
    for row in rows:
        try:
            data = json.loads(row["data_json"] or "{}")
        except ValueError:
            data = {}
        out.append({"id": row["id"], "name": row["name"], "size_mm": data.get("size_mm"), "updated_at": data.get("updated_at"),
                    "elements": sum(len((data.get("sides") or {}).get(side, {}).get("elements", [])) for side in SIDES)})
    return out


# -- elements ---------------------------------------------------------------------------------------------------------------------------
def _side(plan: Mapping, side) -> list[dict]:
    if side not in SIDES:
        raise su.ValidationError("choose a side of the card: front or back")
    return plan["sides"][side]["elements"]


def _find(elements: list[dict], ids) -> list[dict]:
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise su.ValidationError("choose at least one element of the card")
    found = [e for e in elements if e["id"] in ids]
    if len(found) != len(set(ids)):
        raise su.ValidationError("an element you chose is no longer on this side of the card")
    return found


def _text_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise su.ValidationError("the text of an element must be an object")
    unknown = sorted(set(payload) - set(TEXT_KEYS))
    if unknown:
        raise su.ValidationError(f"a text element has no field {unknown[0]!r}")
    spec = lettering.checked({**TEXT_DEFAULT, **payload})
    return {key: spec[key] for key in TEXT_KEYS}


def _library_payload(group: str, key: str, payload) -> dict:
    if not isinstance(payload, dict):
        raise su.ValidationError(f"the {group} of an element must be an object")
    payload = dict(payload)
    chosen = payload.pop(key, None)
    if not isinstance(chosen, str):
        raise su.ValidationError(f"choose the {group}")
    return {key: chosen, **card_library.checked(group, chosen, payload)}


def _image_payload(payload) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("file"), str):
        raise su.ValidationError("an image element needs its stored picture")
    params = card_image.checked({k: v for k, v in payload.items() if k in card_image.DEFAULTS})
    size = payload.get("size")
    if not (isinstance(size, (list, tuple)) and len(size) == 2):
        raise su.ValidationError("an image element needs the size of its picture")
    return {"file": payload["file"], "name": str(payload.get("name") or "picture")[:MAX_NAME], "size": [int(size[0]), int(size[1])], **params,
            "origin": payload.get("origin") if payload.get("origin") in ("import", "generated") else "import",
            "prompt": payload.get("prompt") if isinstance(payload.get("prompt"), str) else None}


def _checked(plan: Mapping, element: Mapping) -> dict:
    """An element with every field present and in range; ValidationError names the first that is not."""
    kind = element.get("type")
    if kind not in TYPES:
        raise su.ValidationError("an element is a text, shape, frame, icon, image or QR code")
    out = {"id": element["id"], "type": kind}
    out["name"] = _name(element.get("name") or kind.capitalize(), "the element's name")
    out["x"] = _number(element.get("x"), "the position x (mm)", -1000.0, 1000.0)
    out["y"] = _number(element.get("y"), "the position y (mm)", -1000.0, 1000.0)
    rotation = _number(element.get("rotation", 0.0), "the rotation (degrees)", -3600.0, 3600.0)
    out["rotation"] = round(((rotation + 180.0) % 360.0) - 180.0, 2)
    group = element.get("group")
    if group is not None and not isinstance(group, str):
        raise su.ValidationError("the group of an element must be text")
    out["group"] = group or None
    settings_id = element.get("settings_id")
    if settings_id is not None and settings_id not in [s["id"] for s in plan["settings"]]:
        raise su.ValidationError("the engraving settings you chose no longer exist")
    out["settings_id"] = settings_id
    payload = element.get(kind)
    if kind == "text":
        out["text"] = _text_payload(payload)
    elif kind == "shape":
        out["shape"] = _library_payload("shape", "kind", payload)
    elif kind == "frame":
        out["frame"] = _library_payload("frame", "style", payload)
    elif kind == "icon":
        out["icon"] = _library_payload("icon", "name", payload)
    elif kind == "image":
        out["image"] = _image_payload(payload)
    else:
        out["qr"] = card_qr.checked(payload)
    out["width"] = _number(element.get("width", 1.0), "the width (mm)", MIN_ELEMENT_MM, MAX_ELEMENT_MM)
    out["height"] = _number(element.get("height", 1.0), "the height (mm)", MIN_ELEMENT_MM, MAX_ELEMENT_MM)
    if kind == "qr":
        out["width"] = out["height"] = max(out["width"], out["height"])
    return out


def _remember(cache: OrderedDict, key: str, value, keep: int) -> None:
    with _lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > keep:
            cache.popitem(last=False)


def _picture(path: str):
    key = json.dumps(rc.file_stamp(path), sort_keys=True)
    with _lock:
        if key in _decoded:
            _decoded.move_to_end(key)
            return _decoded[key]
    image = card_image.load(Path(path).read_bytes())
    _remember(_decoded, key, image, KEEP_IMAGES)
    return image


def _local(store: Store, element: Mapping):
    """The element's geometry centred on (0, 0), unrotated, with the problems found and, for a text, the size it measures."""
    kind = element["type"]
    key_parts = {"type": kind, kind: element[kind]}
    if kind != "text":                                  # a text measures its own box
        key_parts.update(w=round(element["width"], 3), h=round(element["height"], 3))
    if kind == "image":
        key_parts["stamp"] = rc.file_stamp(element["image"]["file"])
    key = json.dumps(key_parts, sort_keys=True, default=str)
    with _lock:
        if key in _geometries:
            _geometries.move_to_end(key)
            return _geometries[key]
    problems: list[str] = []
    measured = None
    try:
        if kind == "text":
            spec = lettering.checked({**TEXT_DEFAULT, **element["text"]})
            letters = lettering.geometry(store.data_dir, spec, None)
            shape = letters["letters"]
            if letters["missing"]:
                problems.append("The font has no letter for " + " ".join(sorted(set(str(c) for c in letters["missing"]))) + ".")
            if shape.is_empty:
                problems.append("Nothing to engrave: the text is empty")
                geometry = Polygon()
            else:
                x0, y0, x1, y1 = shape.bounds
                geometry = affinity.translate(shape, -(x0 + x1) / 2, -(y0 + y1) / 2)
                measured = (round(x1 - x0, 3), round(y1 - y0, 3))
        elif kind == "shape":
            geometry = card_library.geometry("shape", element["shape"]["kind"], element["width"], element["height"],
                                             {k: v for k, v in element["shape"].items() if k != "kind"})
        elif kind == "frame":
            geometry = card_library.geometry("frame", element["frame"]["style"], element["width"], element["height"],
                                             {k: v for k, v in element["frame"].items() if k != "style"})
        elif kind == "icon":
            geometry = card_library.geometry("icon", element["icon"]["name"], element["width"], element["height"],
                                             {k: v for k, v in element["icon"].items() if k != "name"})
        elif kind == "image":
            path = element["image"]["file"]
            if not Path(path).exists():
                problems.append("The picture file of this element is missing")
                geometry = Polygon()
            else:
                params = {k: v for k, v in element["image"].items() if k in card_image.DEFAULTS}
                geometry = card_image.geometry(_picture(path), element["width"], element["height"], params)
        else:
            geometry = card_qr.geometry(element["qr"], element["width"])
    except fonts.FontError as error:
        problems.append(str(error))
        geometry = Polygon()
    except su.ValidationError as error:
        problems.append(str(error))
        geometry = Polygon()
    if geometry.is_empty and not problems:
        problems.append("Nothing to engrave: the picture has no dark areas (a white graphic on a transparent background loads as all white); "
                        "try Invert or another threshold" if kind == "image" else "Nothing to engrave")
    found = (geometry, problems, measured)
    _remember(_geometries, key, found, KEEP_GEOMETRIES)
    return found


def _placed(geometry, element: Mapping):
    if geometry.is_empty:
        return geometry
    if element["rotation"]:
        geometry = affinity.rotate(geometry, element["rotation"], origin=(0, 0))
    return affinity.translate(geometry, element["x"], element["y"])


def _fit_text(store: Store, element: dict) -> None:
    """A text element's box is what its letters measure."""
    if element["type"] != "text":
        return
    _, _, measured = _local(store, element)
    if measured is not None:
        element["width"] = max(MIN_ELEMENT_MM, measured[0])
        element["height"] = max(MIN_ELEMENT_MM, measured[1])


def _label_of(kind: str) -> str:
    return {"qr": "QR code"}.get(kind, kind.capitalize())


def _new_name(elements: list[dict], kind: str) -> str:
    label = _label_of(kind)
    return f"{label} {sum(1 for e in elements if e['type'] == kind) + 1}"


def _defaults_for(plan: Mapping, spec: Mapping) -> dict:
    """A new element from the operator's request: what it names, the rest from the library's defaults, in the middle of the card."""
    kind = spec.get("type")
    if kind not in TYPES:
        raise su.ValidationError("an element is a text, shape, frame, icon, image or QR code")
    card = size_mm(plan)
    element = {k: copy.deepcopy(v) for k, v in spec.items() if k not in ("id",)}
    element.setdefault("x", round(card["width"] / 2, 3))
    element.setdefault("y", round(card["height"] / 2, 3))
    element.setdefault("rotation", 0.0)
    payload = element.get(kind)
    if kind == "text":
        element[kind] = {**TEXT_DEFAULT, **(payload or {})}
        element.setdefault("width", 20.0)
        element.setdefault("height", element[kind]["height_mm"])
    elif kind in ("shape", "frame", "icon"):
        key = {"shape": "kind", "frame": "style", "icon": "name"}[kind]
        payload = dict(payload or {})
        payload.setdefault(key, {"shape": "rectangle", "frame": "single", "icon": "star"}[kind])
        element[kind] = payload
        size = card_library.default_size(kind, payload[key])
        if kind == "frame":
            size = {"width": max(MIN_ELEMENT_MM, card["width"] - 4.0), "height": max(MIN_ELEMENT_MM, card["height"] - 4.0)}
        element.setdefault("width", size["width"])
        element.setdefault("height", size["height"])
    elif kind == "image":
        element.setdefault("width", IMAGE_LONG_SIDE_MM)
        element.setdefault("height", IMAGE_LONG_SIDE_MM)
    else:
        element[kind] = payload if isinstance(payload, dict) else {"kind": "link", "fields": {}}
        element.setdefault("width", DEFAULT_QR_MM)
        element.setdefault("height", DEFAULT_QR_MM)
    return element


def _add(store: Store, plan: dict, side: str, spec) -> str:
    elements = _side(plan, side)
    if len(elements) >= MAX_ELEMENTS:
        raise su.ValidationError(f"a side holds at most {MAX_ELEMENTS} elements")
    if not isinstance(spec, dict):
        raise su.ValidationError("an element must be an object")
    element = _defaults_for(plan, spec)
    element["id"] = f"e{plan['next_id']}"
    if not element.get("name"):
        element["name"] = _new_name(elements, element.get("type"))
    element = _checked(plan, element)
    _fit_text(store, element)
    plan["next_id"] += 1
    elements.append(element)
    return element["id"]


# -- the edit operations --------------------------------------------------------------------------------------------------------------
def _merged(plan: Mapping, element: dict, changes) -> dict:
    if not isinstance(changes, dict) or not changes:
        raise su.ValidationError("give the changes to make")
    if "type" in changes and changes["type"] != element["type"]:
        raise su.ValidationError("an element cannot change its type: add a new one")
    merged = copy.deepcopy(element)
    for key, value in changes.items():
        if key in ("id", "type"):
            continue
        if key == element["type"]:
            if not isinstance(value, dict):
                raise su.ValidationError(f"the {key} settings must be an object")
            merged[key] = {**merged[key], **value}
        elif key in ("name", "x", "y", "width", "height", "rotation", "group", "settings_id"):
            merged[key] = value
        else:
            raise su.ValidationError(f"an element has no field {key!r}")
    return merged


def _resize(store: Store, plan: dict, element: dict, body: Mapping) -> dict:
    new = copy.deepcopy(element)
    width = _number(body.get("width", element["width"]), "the width (mm)", MIN_ELEMENT_MM, MAX_ELEMENT_MM)
    height = _number(body.get("height", element["height"]), "the height (mm)", MIN_ELEMENT_MM, MAX_ELEMENT_MM)
    if "x" in body:
        new["x"] = body["x"]
    if "y" in body:
        new["y"] = body["y"]
    if element["type"] == "text":
        factor = width / element["width"] if element["width"] else 1.0
        new["text"]["height_mm"] = round(element["text"]["height_mm"] * factor, 4)
    elif element["type"] == "qr":
        new["width"] = new["height"] = max(width, height)
    else:
        new["width"], new["height"] = width, height
    return new


def _reordered(elements: list[dict], ids: list[str], to: str) -> list[dict]:
    if to not in ("front", "back", "forward", "backward"):
        raise su.ValidationError("move an element to the front, back, forward or backward")
    chosen = [e for e in elements if e["id"] in ids]
    rest = [e for e in elements if e["id"] not in ids]
    if to == "front":
        return rest + chosen
    if to == "back":
        return chosen + rest
    out = list(elements)
    if to == "forward":
        for i in range(len(out) - 2, -1, -1):
            if out[i]["id"] in ids and out[i + 1]["id"] not in ids:
                out[i], out[i + 1] = out[i + 1], out[i]
    else:
        for i in range(1, len(out)):
            if out[i]["id"] in ids and out[i - 1]["id"] not in ids:
                out[i], out[i - 1] = out[i - 1], out[i]
    return out


def _regroup(elements: list[dict]) -> None:
    """A group of one member is no group."""
    counts: dict[str, int] = {}
    for e in elements:
        if e["group"]:
            counts[e["group"]] = counts.get(e["group"], 0) + 1
    for e in elements:
        if e["group"] and counts[e["group"]] < 2:
            e["group"] = None


def _checked_settings(changes: Mapping, current: Mapping) -> dict:
    if not isinstance(changes, dict) or not changes:
        raise su.ValidationError("give the engraving settings to change")
    unknown = sorted(set(changes) - {"name", "mode", "passes", *SETTING_FIELDS})
    if unknown:
        raise su.ValidationError(f"engraving settings have no field {unknown[0]!r}")
    out = dict(current)
    for key, value in changes.items():
        if key == "name":
            out[key] = _name(value, "the settings")
        elif key == "mode":
            if value not in MODES:
                raise su.ValidationError("engrave by filling areas or along lines")
            out[key] = value
        elif key == "passes":
            number = _number(value, "the passes", 1, 100)
            if number != int(number):
                raise su.ValidationError("the passes must be a whole number from 1 to 100")
            out[key] = int(number)
        elif value is None:
            out[key] = None
        else:
            low, high, label = SETTING_FIELDS[key]
            number = _number(value, label, low, high)
            if number <= low:
                raise su.ValidationError(f"{label} must be above {low:g}")
            out[key] = number
    return out


def _apply(store: Store, plan: dict, body: Mapping) -> list[str]:
    """Carry out one edit on the plan's state (not yet saved). Returns the ids of the elements it added."""
    op = body.get("op")
    if op not in EDIT_OPS:
        raise su.ValidationError("this edit is not known")
    added: list[str] = []
    if op in ("settings_add", "settings_set", "settings_delete", "set_size"):
        return _apply_card(plan, op, body)
    elements = _side(plan, body.get("side"))
    if op == "add":
        added.append(_add(store, plan, body["side"], body.get("element")))
        return added
    chosen = _find(elements, body["ids"] if "ids" in body else [body.get("id")]) if op != "assign_settings" or body.get("ids") else []
    if op == "set":
        element = chosen[0]
        merged = _checked(plan, _merged(plan, element, body.get("changes")))
        _fit_text(store, merged)
        elements[elements.index(element)] = merged
    elif op == "move":
        dx = _number(body.get("dx", 0), "the shift x (mm)", -1000.0, 1000.0)
        dy = _number(body.get("dy", 0), "the shift y (mm)", -1000.0, 1000.0)
        for element in chosen:
            element["x"], element["y"] = round(element["x"] + dx, 4), round(element["y"] + dy, 4)
    elif op == "resize":
        element = chosen[0]
        merged = _checked(plan, _resize(store, plan, element, body))
        _fit_text(store, merged)
        elements[elements.index(element)] = merged
    elif op == "rotate":
        element = chosen[0]
        merged = _checked(plan, {**element, "rotation": body.get("rotation")})
        elements[elements.index(element)] = merged
    elif op == "reorder":
        plan["sides"][body["side"]]["elements"] = _reordered(elements, [e["id"] for e in chosen], body.get("to"))
    elif op == "duplicate":
        groups: dict[str, str] = {}
        for element in chosen:
            if len(elements) >= MAX_ELEMENTS:
                raise su.ValidationError(f"a side holds at most {MAX_ELEMENTS} elements")
            twin = copy.deepcopy(element)
            twin["id"] = f"e{plan['next_id']}"
            plan["next_id"] += 1
            twin["x"], twin["y"] = round(element["x"] + COPY_SHIFT_MM, 4), round(element["y"] + COPY_SHIFT_MM, 4)
            if element["group"]:
                if element["group"] not in groups:
                    groups[element["group"]] = f"g{plan['next_id']}"
                    plan["next_id"] += 1
                twin["group"] = groups[element["group"]]
            twin["name"] = _name(element["name"] + " copy", "the element's name")
            elements.append(twin)
            added.append(twin["id"])
        _regroup(elements)
    elif op == "delete":
        gone = {e["id"] for e in chosen}
        plan["sides"][body["side"]]["elements"] = [e for e in elements if e["id"] not in gone]
        _regroup(plan["sides"][body["side"]]["elements"])
    elif op == "group":
        if len(chosen) < 2:
            raise su.ValidationError("choose at least two elements to group")
        label = f"g{plan['next_id']}"
        plan["next_id"] += 1
        for element in chosen:
            element["group"] = label
        _regroup(elements)
    elif op == "ungroup":
        labels = {e["group"] for e in chosen if e["group"]}
        for element in elements:
            if element["group"] in labels:
                element["group"] = None
    elif op == "assign_settings":
        wanted = body.get("settings_id")
        if wanted is not None and wanted not in [s["id"] for s in plan["settings"]]:
            raise su.ValidationError("the engraving settings you chose no longer exist")
        members = {e["id"] for e in chosen}
        labels = {e["group"] for e in chosen if e["group"]}
        if isinstance(body.get("group"), str):
            labels.add(body["group"])
        if not members and not labels:
            raise su.ValidationError("choose the elements or the group to give these engraving settings")
        for element in elements:
            if element["id"] in members or (element["group"] and element["group"] in labels):
                element["settings_id"] = wanted
    return added


def _apply_card(plan: dict, op: str, body: Mapping) -> list[str]:
    if op == "set_size":
        plan["preset"], plan["size_mm"] = _card_size(body.get("preset", CUSTOM), body.get("width_mm"), body.get("height_mm"))
    elif op == "settings_add":
        settings_id = plan["next_settings_id"]
        plan["next_settings_id"] += 1
        plan["settings"].append(_checked_settings({"name": body.get("name") or f"Engraving {settings_id}"}, _blank_settings(settings_id, "")))
    else:
        known = {s["id"]: s for s in plan["settings"]}
        settings_id = body.get("id")
        if settings_id not in known:
            raise su.ValidationError("these engraving settings no longer exist")
        if op == "settings_set":
            plan["settings"][plan["settings"].index(known[settings_id])] = _checked_settings(body.get("changes"), known[settings_id])
        else:
            if len(known) < 2:
                raise su.ValidationError("a card keeps at least one set of engraving settings")
            plan["settings"] = [s for s in plan["settings"] if s["id"] != settings_id]
            if plan["default_settings_id"] == settings_id:
                plan["default_settings_id"] = plan["settings"][0]["id"]
            for side in SIDES:
                for element in plan["sides"][side]["elements"]:
                    if element["settings_id"] == settings_id:
                        element["settings_id"] = None
    return []


def _here(plan: Mapping) -> dict:
    return copy.deepcopy({k: plan[k] for k in STATE})


def _push(plan: dict, before: dict) -> None:
    plan["undo"], plan["redo"] = (plan["undo"] + [before])[-UNDO_DEPTH:], []


def edit(store: Store, plan_id: int, body) -> dict:
    """Carry out one edit (``body['op']``, see :data:`EDIT_OPS`) and return the work as it is now, with ``added``: the ids the edit made."""
    if not isinstance(body, dict):
        raise su.ValidationError("an edit must be an object")
    plan = _work(store, plan_id)
    before = _here(plan)
    added = _apply(store, plan, body)
    if _here(plan) != before:
        _push(plan, before)
        plan["updated_at"] = now()
        with store.transaction():
            _save(store, plan, plan["id"])
            store.audit("card_work_changed", plan_id=plan["id"], op=body["op"])
    return _view(store, plan, added)


def step(store: Store, plan_id: int, direction: str) -> dict:
    """Undo (``direction`` "undo") or redo ("redo") one change; the work is returned as it is now."""
    plan = _work(store, plan_id)
    if not plan[direction]:
        raise su.ValidationError("there is no earlier change of the card to undo" if direction == "undo" else "there is no undone change to redo")
    there = plan[direction].pop()
    plan["redo" if direction == "undo" else "undo"].append(_here(plan))
    plan.update(copy.deepcopy(there))
    plan["updated_at"] = now()
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("card_work_" + direction, plan_id=plan["id"])
    return _view(store, plan)


def rename_work(store: Store, plan_id: int, name) -> str:
    plan = _work(store, plan_id)
    title = _name(name, "the card")
    with store.transaction():
        _save(store, plan, plan["id"], name=title)
        store.audit("card_work_renamed", plan_id=plan["id"])
    return title


def copy_work(store: Store, plan_id: int, name=None) -> int:
    """A card of its own made from this one, with its own copies of the pictures; the first stays as it is."""
    plan = _work(store, plan_id)
    title = _name(name, "the card") if name is not None else _name(plan["name"] + " copy", "the card")
    twin = copy.deepcopy(plan)
    for side in SIDES:
        for element in twin["sides"][side]["elements"]:
            if element["type"] == "image":
                source = Path(element["image"]["file"])
                if source.exists():
                    element["image"]["file"] = cv._store_image(store, source.read_bytes())
    twin["undo"], twin["redo"], twin["updated_at"] = [], [], now()
    with store.transaction():
        new_id = _save(store, twin, name=title, identifier=pl.new_identifier(IDENTIFIER_PREFIX))
        store.audit("card_work_copied", plan_id=new_id, source=plan["id"])
    return new_id


# -- pictures: imported and generated ---------------------------------------------------------------------------------------------------
def _image_spec(plan: Mapping, file: str, name: str, size, origin: str, prompt=None) -> dict:
    card = size_mm(plan)
    cols, rows = size
    longest = min(IMAGE_LONG_SIDE_MM, max(card["width"], card["height"]) - 4.0)
    width, height = (longest, longest * rows / cols) if cols >= rows else (longest * cols / rows, longest)
    room = min(card["width"], card["height"]) - 4.0
    if max(width, height) > room and max(width, height) > 0:
        scale = room / max(width, height)
        width, height = width * scale, height * scale
    return {"type": "image", "name": name, "width": round(max(width, MIN_ELEMENT_MM), 3), "height": round(max(height, MIN_ELEMENT_MM), 3),
            "image": {"file": file, "name": name, "size": list(size), **card_image.DEFAULTS, "origin": origin, "prompt": prompt}}


def add_image(store: Store, plan_id: int, side: str, file_name: str, data: bytes, *, origin: str = "import", prompt=None) -> dict:
    """Add a picture (PNG, JPEG ...) to a side as an image element traced into engravable shapes; returns the work."""
    plan = _work(store, plan_id)
    _side(plan, side)
    card_image.load(data)                                  # refuses what is not a usable picture, with a message
    size = card_image.image_size(data)
    before = _here(plan)
    path = cv._store_image(store, data)
    title = ((Path(file_name or "").stem if origin == "import" else file_name) or "picture")[:MAX_NAME]
    added = _add(store, plan, side, _image_spec(plan, path, title, size, origin, prompt))
    _push(plan, before)
    plan["updated_at"] = now()
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("card_work_image_added", plan_id=plan["id"], origin=origin)
    return _view(store, plan, [added])


def generation(store: Store) -> dict:
    """Whether a picture can be generated now, and what is missing when it cannot (DEC-039)."""
    return card_generate.available(store)


def generate(store: Store, plan_id: int, side: str, description, kind: str) -> dict:
    """Generate an icon or a drawing from a description with the OpenAI image service and add it to a side as an image element."""
    plan = _work(store, plan_id)
    _side(plan, side)
    data, text = card_generate.generate(store, description, kind)
    return add_image(store, plan_id, side, text[:40].capitalize(), data, origin="generated", prompt=text)


# -- the view ---------------------------------------------------------------------------------------------------------------------------
def _effective(plan: Mapping, element: Mapping) -> int:
    ids = [s["id"] for s in plan["settings"]]
    return element["settings_id"] if element["settings_id"] in ids else plan["default_settings_id"]


def _missing(settings: Mapping) -> list[str]:
    need = ["power", "speed", "frequency"] + (["line_interval"] if settings["mode"] == "fill" else [])
    return [key for key in need if settings.get(key) is None]


def _side_elements(store: Store, plan: Mapping, side: str) -> list[dict]:
    """The side's elements with their placed geometry (``_geometry``), problems and measured box; text boxes are brought up to date."""
    built = []
    for element in plan["sides"][side]["elements"]:
        local, problems, measured = _local(store, element)
        item = copy.deepcopy(element)
        if measured is not None:
            item["width"], item["height"] = max(MIN_ELEMENT_MM, measured[0]), max(MIN_ELEMENT_MM, measured[1])
        built.append({"element": item, "geometry": _placed(local, item), "problems": list(problems)})
    return built


def _element_view(plan: Mapping, built: list[dict], index: int, card) -> dict:
    entry = built[index]
    element, geometry = entry["element"], entry["geometry"]
    out = copy.deepcopy(element)
    if element["type"] == "image":
        out["image"].pop("file", None)
    out["d"] = path_d(geometry)
    out["bounds"] = [round(v, 3) for v in geometry.bounds] if not geometry.is_empty else None
    out["empty"] = geometry.is_empty
    out["problems"] = entry["problems"]
    warnings = []
    if not geometry.is_empty and not card.buffer(OUTSIDE_TOLERANCE_MM).covers(geometry):
        warnings.append({"code": "outside_card", "message": "Part of this element lies outside the card and would not be engraved on it."})
    if element["type"] == "qr":
        others = [b["geometry"] for i, b in enumerate(built) if i != index and not b["geometry"].is_empty]
        half = element["width"] / 2
        symbol = _placed(shapely_box(-half, -half, half, half), element)
        try:
            info = card_qr.placed_check(element["qr"], element["width"], symbol, others, card)
        except su.ValidationError as error:                 # incomplete content: the geometry carries the same problem, the view stays whole
            out["qr_info"] = None
            if str(error) not in out["problems"]:
                out["problems"] = out["problems"] + [str(error)]
        else:
            out["qr_info"] = {key: info[key] for key in ("content", "modules", "module_mm", "quiet_modules", "clearance_mm", "thresholds", "note")}
            warnings += info["warnings"]
    out["warnings"] = warnings
    return out


def _review(plan: Mapping, side: str, built: list[dict]) -> dict:
    sets: dict[int, dict] = {}
    rows = []
    problems = []
    names = {s["id"]: s for s in plan["settings"]}
    engraved = [b for b in built if not b["geometry"].is_empty]
    for entry in built:
        element = entry["element"]
        effective = _effective(plan, element)
        complete = not _missing(names[effective])
        rows.append({"id": element["id"], "name": element["name"], "type": element["type"], "settings_id": element["settings_id"],
                     "effective_settings_id": effective, "complete": complete, "empty": entry["geometry"].is_empty})
        if not entry["geometry"].is_empty:
            sets.setdefault(effective, {"settings_id": effective, "name": names[effective]["name"], "elements": [], "missing": _missing(names[effective])})
            sets[effective]["elements"].append(element["id"])
    for item in sets.values():
        item["complete"] = not item["missing"]
        if item["missing"]:
            problems.append(f"The engraving settings “{item['name']}” still need " + ", ".join(item["missing"]) + ".")
    if not engraved:
        problems.append(f"There is nothing to engrave on the {side}")
    return {"ready": not problems, "problems": problems, "sets": sorted(sets.values(), key=lambda s: s["settings_id"]), "elements": rows,
            "empty": not engraved}


def _view(store: Store, plan: dict, added=None) -> dict:
    card_size = size_mm(plan)
    card = shapely_box(0, 0, card_size["width"], card_size["height"])
    sides, review = {}, {}
    for side in SIDES:
        built = _side_elements(store, plan, side)
        sides[side] = {"elements": [_element_view(plan, built, i, card) for i in range(len(built))]}
        review[side] = _review(plan, side, built)
    context = cc.get(store)
    out = {"id": plan["id"], "name": plan["name"], "size_mm": card_size, "preset": plan["preset"], "presets": PRESETS, "sides": sides,
           "settings": copy.deepcopy(plan["settings"]), "default_settings_id": plan["default_settings_id"], "review": review,
           "can_undo": bool(plan["undo"]), "can_redo": bool(plan["redo"]), "updated_at": plan["updated_at"],
           "laser": context["device"] and {"id": context["device_id"], "name": context["device"].get("name")},
           "generation": generation(store), "qr": {"thresholds": card_qr.THRESHOLDS}}
    if added is not None:
        out["added"] = list(added)
    return out


def view(store: Store, plan_id: int) -> dict:
    return _view(store, _work(store, plan_id))


def library() -> dict:
    """What the editor offers: the shapes, frames and icons, the QR kinds with their fields, the picture treatment and the card sizes."""
    return {**card_library.listing(),
            "qr": {"kinds": list(card_qr.KINDS), "fields": card_qr.FIELDS, "ecc": list(card_qr.ECC_LEVELS), "thresholds": card_qr.THRESHOLDS},
            "image": {"params": card_image.IMAGE_PARAMS}, "presets": PRESETS}


# -- pictures of a side and its LightBurn file ------------------------------------------------------------------------------------------
CARD_FILL, ENGRAVED_FILL = "#d5d9df", "#23262b"


def preview_svg(store: Store, plan_id: int, side: str) -> str:
    """One side as an SVG picture in the card's millimetres: the same geometry the LightBurn file of the side writes."""
    plan = _work(store, plan_id)
    _side(plan, side)
    card = size_mm(plan)
    paths = "".join(f'<path d="{path_d(b["geometry"])}" fill-rule="evenodd"/>' for b in _side_elements(store, plan, side) if not b["geometry"].is_empty)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(card["width"])} {_fmt(card["height"])}">'
            f'<rect width="{_fmt(card["width"])}" height="{_fmt(card["height"])}" rx="3" fill="{CARD_FILL}"/>'
            f'<g fill="{ENGRAVED_FILL}">{paths}</g></svg>')


def export(store: Store, plan_id: int, side: str) -> tuple[bytes, str]:
    """One side as a LightBurn project (DEC-035): its elements' shapes in the card's millimetres, one layer for each set of engraving
    settings the side uses, written as the operator defined them. Refused with the problems of the side's review when it is not ready."""
    plan = _work(store, plan_id)
    _side(plan, side)
    built = _side_elements(store, plan, side)
    review = _review(plan, side, built)
    if not review["ready"]:
        raise su.ValidationError("the " + side + " is not ready to export: " + "; ".join(review["problems"]))
    names = {s["id"]: s for s in plan["settings"]}
    used = [item["settings_id"] for item in review["sets"]]
    layers, regions = [], []
    for position, settings_id in enumerate(used, start=1):
        s = names[settings_id]
        layers.append({"index": position, "name": s["name"], "cut_type": "Scan" if s["mode"] == "fill" else "Cut", "regions": [],
                       "layer_keys": [f"s{settings_id}"], "prediction": None,
                       "parameters": {"power": s["power"], "frequency": s["frequency"], "speed": s["speed"], "pulse_width": s["pulse_width"],
                                      "line_interval": s["line_interval"] if s["mode"] == "fill" else None, "passes": s["passes"]}})
    for entry in built:
        if entry["geometry"].is_empty:
            continue
        loops = _rings(entry["geometry"])
        if loops:
            regions.append({"id": entry["element"]["id"], "layer_key": f"s{_effective(plan, entry['element'])}", "loops": loops, "strokes": []})
    context = cc.get(store)
    device, lens, material = context.get("device") or {}, context.get("lens") or {}, context.get("material") or {}
    data = pl.export_lbrn2({"mode": MODE, "name": f"{plan['name']} {side}", "layers": layers, "vector_document": {"regions": regions},
                            "size_mm": size_mm(plan), "export_mirror_y": True, "plan_identifier": "",
                            "experiment": {"label": f"Business card {side}", "test_name": plan["name"], "device": device, "lens": lens,
                                           "material": material}})
    store.audit("card_work_exported", plan_id=plan["id"], side=side)
    return data, f"{plan['name']} {side}"
