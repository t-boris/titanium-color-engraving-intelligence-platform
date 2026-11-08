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
:mod:`card_image`), ``qr`` (:mod:`card_qr`) or ``vector`` (one part of an imported SVG or Illustrator artwork, :mod:`card_vector`: the name of the
stored artwork file, the part's number, its design colour ``fill`` and the colour the file gave it, ``source``). ``x``/``y`` is its centre in millimetres on the card (origin top-left, y down) and
``rotation`` is in degrees, clockwise on the screen.

Every element reduces to one shapely geometry in the card's millimetres. The screen draws that geometry, the preview shows it and the
LightBurn file of a side writes it, so what the operator sees is what is engraved. The file carries no cleaning layer: a card is
engraved, not colour-marked, and the operator's settings are written as given.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import math
import shutil
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Mapping

import shapely
from shapely import affinity
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box as shapely_box

from . import (card_generate, card_image, card_library, card_qr, card_raster, card_settings, card_vector, conversion as cv, creation_context as cc, devices,
               fonts, grayscale, lenses, lettering, plans as pl, render_cache as rc, setup as su)
from .db import Store, now

log = logging.getLogger(__name__)
MODE = pl.MODE_CARD_WORK
UNREADABLE_PART = "The shape of this part could not be read from its artwork file"
IDENTIFIER_PREFIX = "TCE-C"
SIDES = ("front", "back")
TYPES = ("text", "shape", "frame", "icon", "image", "qr", "vector")
PRESETS = [{"id": "85x53", "width": 85.0, "height": 53.0, "label": "85 × 53 mm"},
           {"id": "85x54", "width": 85.0, "height": 54.0, "label": "85 × 54 mm"}]
CUSTOM = "custom"
MIN_CARD_MM, MAX_CARD_MM = 10.0, 300.0
MIN_ELEMENT_MM, MAX_ELEMENT_MM = 0.2, 500.0
MIN_VECTOR_MM = card_vector.MIN_PART_MM       # an imported part may be a hairline: it is as thin as the artwork draws it
SCALE_RANGE = (0.05, 20.0)
MAX_COLOURS_ASKED = 64
MAX_ELEMENTS = 300                      # on one side
MAX_NAME = 80
UNDO_DEPTH = 50
COPY_SHIFT_MM = 2.0
KEEP_GEOMETRIES = 512
KEEP_IMAGES = 4
KEEP_RASTERS = 8
OUTSIDE_TOLERANCE_MM = 0.05
DEFAULT_QR_MM = 18.0
IMAGE_LONG_SIDE_MM = 30.0
TEXT_KEYS = ("text", "font", "height_mm", "align", "width_pct", "spacing_mm", "line_pct")
TEXT_DEFAULT = {"text": "Text", "font": None, "height_mm": 5.0, "align": "center", "width_pct": 100.0, "spacing_mm": 0.0, "line_pct": 100.0}
SETTING_FIELDS = {"power": (0.0, 100.0, "power (%)"), "speed": (0.0, 100000.0, "speed (mm/s)"),
                  "frequency": (0.0, 10000.0, "frequency (kHz)"), "pulse_width": (0.0, 10000.0, "pulse width (ns)"),
                  "line_interval": (0.0, 10.0, "line interval (mm)")}
MODES = ("fill", "line")
# What a set of settings carries beyond the six numbers of 0.41.0 (ready-engraving-settings-for-business-cards, REQ-023): the fields of a
# scan layer and of a photo (image) layer. ``None`` is "the source does not give it"; nothing is defaulted.
EXTRA_NUMBERS = {"min_power": (0.0, 100.0, "minimum power (%)"), "scan_angle": (-360.0, 360.0, "scan angle (degrees)"),
                 "dot_width": (0.0, 5.0, "dot width (mm)")}
EXTRA_FLAGS = ("bidirectional", "cross_hatch")
VALUE_KEYS = ("mode", "power", "speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes", "bidirectional", "cross_hatch",
              "scan_angle", "min_power", "dither", "dot_width")
ENGRAVE = ("vector", "raster")
RASTER_DPI_PREVIEW = 254.0                 # the preview of a raster picture before it has a line interval (0.1 mm)
STATES = ("unknown", "proposed", "chosen", "custom", "other_setup")
DATA = ("size_mm", "preset", "sides", "settings", "default_settings_id", "setup", "next_id", "next_settings_id", "undo", "redo", "updated_at")
# What one step of undo or redo brings back: everything that decides what the card engraves.
STATE = ("size_mm", "preset", "sides", "settings", "default_settings_id", "setup", "next_id", "next_settings_id")
EDIT_OPS = ("add", "set", "move", "resize", "rotate", "reorder", "duplicate", "delete", "group", "ungroup", "assign_settings", "assign_choice",
            "settings_add", "settings_set", "settings_delete", "set_size", "settings_apply", "settings_confirm", "settings_custom", "set_setup",
            "recolour", "scale")

CARD_OPS = ("settings_add", "settings_set", "settings_delete", "set_size", "settings_apply", "settings_confirm", "settings_custom", "set_setup")

_lock = threading.Lock()
_geometries: OrderedDict[str, tuple] = OrderedDict()
_rasters: OrderedDict[str, bytes] = OrderedDict()
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
    return _normalized(plan)


def _setup(plan: Mapping) -> dict:
    """The laser, lens and material the card is tied to (DEC-009): the only setup whose measurements may be offered to it."""
    value = plan["setup"]
    return {"device_id": value["device_id"], "lens_id": value["lens_id"], "material_id": value["material_id"]}


def _custom_origin(setup, note=None) -> dict:
    return {"kind": "custom", "choice_id": None, "type": None, "source": "Custom", "label": "Typed by the operator",
            "detail": "The values were typed by hand, not taken from a measurement.", "evidence": None, "setup": setup, "at": now(),
            "note": note, "proposed": False}


def _normalized(plan: dict) -> dict:
    """A work saved by 0.41.0 brought to the present shape: it gets the laser and lens it already had and no material, its sets get an
    origin (typed numbers count as Custom, never confirmed for a setup) and its pictures are traced shapes. Nothing is lost or invented."""
    if not isinstance(plan.get("setup"), dict):
        plan["setup"] = {"device_id": plan["device_id"], "lens_id": plan["lens_id"], "material_id": None}
    sets = []
    for item in plan["settings"]:
        value = {**_blank_settings(item["id"], item["name"]), **item}
        if "origin" not in item:
            typed = any(value.get(key) is not None for key in ("power", "speed", "frequency", "pulse_width", "line_interval"))
            value["origin"] = _custom_origin(None, "Typed before settings could be chosen.") if typed else None
            value["confirmed"] = False
        sets.append(value)
    plan["settings"] = sets
    for side in SIDES:
        for element in plan["sides"][side]["elements"]:
            if element["type"] == "image":
                element["image"].setdefault("engrave", "vector")
    return plan


def size_mm(plan: Mapping) -> dict:
    return {"width": float(plan["size_mm"]["width"]), "height": float(plan["size_mm"]["height"])}


def _blank_settings(settings_id: int, name: str) -> dict:
    """Settings with no value given: not a form to type into but a set waiting for a choice (the editor offers one or says unknown)."""
    return {"id": settings_id, "name": name, "mode": "fill", "power": None, "speed": None, "frequency": None, "pulse_width": None,
            "line_interval": None, "passes": 1, "global_passes": None, "bidirectional": None, "cross_hatch": None, "scan_angle": None,
            "min_power": None, "dither": None, "dot_width": None, "origin": None, "confirmed": False}


def _card_size(preset, width_mm=None, height_mm=None) -> tuple[str, dict]:
    for item in PRESETS:
        if preset == item["id"]:
            return item["id"], {"width": item["width"], "height": item["height"]}
    if preset != CUSTOM:
        raise su.ValidationError("choose a card size: 85 × 53 mm, 85 × 54 mm or a custom size")
    return CUSTOM, {"width": _number(width_mm, "the card width (mm)", MIN_CARD_MM, MAX_CARD_MM),
                    "height": _number(height_mm, "the card height (mm)", MIN_CARD_MM, MAX_CARD_MM)}


def _save(store: Store, plan: Mapping, plan_id: int | None = None, *, name: str | None = None, identifier: str | None = None) -> int:
    setup = plan["setup"]                              # the laser and lens columns of the row follow the card's own setup
    return cv.save_plan(store, plan_id, name=name or plan["name"], mode=MODE, status=cv.ST_DRAFT, device_id=setup["device_id"],
                        lens_id=setup["lens_id"], markers=False, identifier=identifier or plan["plan_identifier"], band_count=None,
                        data={k: plan[k] for k in DATA})


def create(store: Store, name, preset=PRESETS[0]["id"], width_mm=None, height_mm=None) -> int:
    """A new, empty card work on the laser of the workshop's creation context; returns its id."""
    context = cc.get(store)
    if context["device_id"] is None:
        raise su.ValidationError("add the laser first: a card is engraved with a laser of the workshop")
    chosen, size = _card_size(preset, width_mm, height_mm)
    title = _name(name, "the card") if isinstance(name, str) and name.strip() else "Business card"
    setup = {"device_id": context["device_id"], "lens_id": context["lens_id"], "material_id": context["material_id"]}
    plan = {"device_id": setup["device_id"], "lens_id": setup["lens_id"], "size_mm": size, "preset": chosen, "setup": setup,
            "sides": {side: {"elements": []} for side in SIDES}, "settings": [_blank_settings(1, "Engraving 1")], "default_settings_id": 1,
            "next_id": 1, "next_settings_id": 2, "undo": [], "redo": [], "updated_at": now()}
    plan["settings"][0] = _proposed(store, plan, plan["settings"][0])
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
            "prompt": payload.get("prompt") if isinstance(payload.get("prompt"), str) else None,
            "engrave": payload.get("engrave") if payload.get("engrave") in ENGRAVE else "vector"}


def _vector_payload(payload) -> dict:
    """One part of an imported artwork: the stored file of the artwork, the part's number, its design colour and the colour the file gave it."""
    if not isinstance(payload, dict) or not isinstance(payload.get("artwork"), str) or not card_vector.FILE_PATTERN.match(payload["artwork"]):
        raise su.ValidationError("a vector part needs the stored file of its artwork")
    part = payload.get("part")
    if not isinstance(part, int) or isinstance(part, bool) or part < 0:
        raise su.ValidationError("a vector part needs its number in the artwork")
    fill = card_vector.fill_of(payload.get("fill"))
    return {"artwork": payload["artwork"], "part": part, "fill": fill, "source": card_vector.fill_of(payload.get("source", fill)),
            "file": str(payload.get("file") or "artwork")[:MAX_NAME], "kind": payload.get("kind") if payload.get("kind") in ("svg", "ai") else "svg"}


def _checked(plan: Mapping, element: Mapping) -> dict:
    """An element with every field present and in range; ValidationError names the first that is not."""
    kind = element.get("type")
    if kind not in TYPES:
        raise su.ValidationError("an element is a text, shape, frame, icon, image, QR code or vector part")
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
    elif kind == "vector":
        out["vector"] = _vector_payload(payload)
    else:
        out["qr"] = card_qr.checked(payload)
    least = MIN_VECTOR_MM if kind == "vector" else MIN_ELEMENT_MM
    out["width"] = _number(element.get("width", 1.0), "the width (mm)", least, MAX_ELEMENT_MM)
    out["height"] = _number(element.get("height", 1.0), "the height (mm)", least, MAX_ELEMENT_MM)
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
    key_parts = {"type": kind, kind: element[kind] if kind != "vector" else {k: v for k, v in element[kind].items() if k not in ("fill", "source", "file", "kind")}}
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
        elif kind == "vector":
            payload = element["vector"]
            if not card_vector.exists(store.data_dir, payload["artwork"]):
                problems.append("The artwork file of this part is missing")
                geometry = Polygon()
            else:
                artwork = card_vector.load(store.data_dir, payload["artwork"])
                try:
                    geometry = card_vector.part_geometry(card_vector.part(artwork, payload["part"]), element["width"], element["height"])
                except (shapely.errors.GEOSException, ValueError, IndexError, KeyError, TypeError) as error:       # a damaged part is one problem of the card, not the end of its view
                    log.warning("the shape of part %s of %s could not be built: %s", payload.get("part"), payload.get("artwork"), error)
                    problems.append(UNREADABLE_PART)
                    geometry = Polygon()
        elif kind == "image":
            path = element["image"]["file"]
            if not Path(path).exists():
                problems.append("The picture file of this element is missing")
                geometry = Polygon()
            elif element["image"].get("engrave") == "raster":          # REQ-026: engraved as a photo, it fills its rectangle
                _picture(path)
                geometry = shapely_box(-element["width"] / 2, -element["height"] / 2, element["width"] / 2, element["height"] / 2)
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
    return {"qr": "QR code", "vector": "Vector part"}.get(kind, kind.capitalize())


def _new_name(elements: list[dict], kind: str) -> str:
    label = _label_of(kind)
    return f"{label} {sum(1 for e in elements if e['type'] == kind) + 1}"


def _defaults_for(plan: Mapping, spec: Mapping) -> dict:
    """A new element from the operator's request: what it names, the rest from the library's defaults, in the middle of the card."""
    kind = spec.get("type")
    if kind not in TYPES:
        raise su.ValidationError("an element is a text, shape, frame, icon, image, QR code or vector part")
    if kind == "vector":
        raise su.ValidationError("vector parts come from an imported SVG or Illustrator file: import the file")
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
            if key == "vector" and set(value) - {"fill"}:
                raise su.ValidationError("only the design colour of an imported part can be changed here")
            merged[key] = {**merged[key], **value}
        elif key in ("name", "x", "y", "width", "height", "rotation", "group", "settings_id"):
            merged[key] = value
        else:
            raise su.ValidationError(f"an element has no field {key!r}")
    return merged


def _resize(store: Store, plan: dict, element: dict, body: Mapping) -> dict:
    new = copy.deepcopy(element)
    least = MIN_VECTOR_MM if element["type"] == "vector" else MIN_ELEMENT_MM
    width = _number(body.get("width", element["width"]), "the width (mm)", least, MAX_ELEMENT_MM)
    height = _number(body.get("height", element["height"]), "the height (mm)", least, MAX_ELEMENT_MM)
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


def _whole(value, label: str, low: int, high: int) -> int:
    number = _number(value, label, low, high)
    if number != int(number):
        raise su.ValidationError(f"the {label} must be a whole number from {low} to {high}")
    return int(number)


def _checked_settings(changes: Mapping, current: Mapping) -> dict:
    """``current`` with ``changes`` applied, each value checked; ``None`` clears a value. The origin is not touched here."""
    if not isinstance(changes, dict) or not changes:
        raise su.ValidationError("give the engraving settings to change")
    allowed = {"name", "mode", "passes", "global_passes", "dither", *EXTRA_FLAGS, *SETTING_FIELDS, *EXTRA_NUMBERS}
    unknown = sorted(set(changes) - allowed)
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
        elif key in ("passes", "global_passes"):
            out[key] = None if value is None and key == "global_passes" else _whole(value, "the passes" if key == "passes" else "the global passes", 1, 100)
        elif key in EXTRA_FLAGS:
            if value is not None and not isinstance(value, bool):
                raise su.ValidationError(f"{key.replace('_', ' ')} is on or off")
            out[key] = value
        elif key == "dither":
            if value is not None and not (isinstance(value, str) and 0 < len(value) <= 40):
                raise su.ValidationError("the image mode must be a name")
            out[key] = value
        elif value is None:
            out[key] = None
        elif key in EXTRA_NUMBERS:
            low, high, label = EXTRA_NUMBERS[key]
            out[key] = _number(value, label, low, high)
        else:
            low, high, label = SETTING_FIELDS[key]
            number = _number(value, label, low, high)
            if number <= low:
                raise su.ValidationError(f"{label} must be above {low:g}")
            out[key] = number
    return out


# -- settings that come from the workshop's measurements (ready-engraving-settings-for-business-cards) ------------------------------------
def _same_setup(a, b) -> bool:
    return isinstance(a, dict) and isinstance(b, dict) and all(a.get(k) == b.get(k) for k in ("device_id", "lens_id", "material_id"))


def _applied(plan: Mapping, current: Mapping, item: Mapping, *, proposed: bool) -> dict:
    """``current`` replaced, whole, by the values of a choice (a field the source does not give becomes unknown) and the origin it came from."""
    values = {k: v for k, v in item["settings"].items() if k in VALUE_KEYS and v is not None}
    base = {**_blank_settings(current["id"], current["name"]), "passes": None}
    out = _checked_settings(values, base) if values else base
    out["origin"] = {**item["origin"], "kind": "choice", "at": now(), "note": None, "proposed": proposed, "setup": _setup(plan)}
    out["confirmed"] = not proposed
    return out


def _proposed(store: Store, plan: Mapping, current: Mapping) -> dict:
    """``current`` filled with the best known proposal for the card's setup (marked proposed, to be confirmed), or left unknown when none."""
    if not card_settings.setup_view(store, _setup(plan))["complete"]:
        return current
    item = card_settings.proposal(store, _setup(plan))
    return current if item is None else _applied(plan, current, item, proposed=True)


def _set_of_choice(plan: dict, item: Mapping) -> int:
    """The id of the card's set that holds ``item`` exactly as chosen (made when there is none): the operator picks a colour for an element and
    never has to manage sets; two elements given the same choice share one set, so the file has one layer for it."""
    for current in plan["settings"]:
        origin = current.get("origin")
        if origin and origin["kind"] == "choice" and origin.get("choice_id") == item["id"] and current.get("confirmed") and _same_setup(origin.get("setup"), _setup(plan)):
            return current["id"]
    settings_id = plan["next_settings_id"]
    plan["next_settings_id"] += 1
    fresh = _checked_settings({"name": str(item["label"])[:80]}, _blank_settings(settings_id, ""))
    plan["settings"].append(_applied(plan, fresh, item, proposed=False))
    return settings_id


def _drop_unused_copies(plan: dict) -> None:
    """Sets that :func:`_set_of_choice` made and nothing uses any more (the operator tried another colour) go away; a set the operator made, renamed or edited stays."""
    used = {e["settings_id"] for side in SIDES for e in plan["sides"][side]["elements"]}
    plan["settings"] = [s for s in plan["settings"]
                        if s["id"] in used or s["id"] == plan["default_settings_id"] or not _is_copy_of_choice(s)]


def _is_copy_of_choice(current: Mapping) -> bool:
    origin = current.get("origin")
    return bool(origin) and origin["kind"] == "choice" and current.get("confirmed") is True and current["name"] == str(origin["label"])[:80]


def _unknown_set(current: Mapping) -> dict:
    return {**_blank_settings(current["id"], current["name"])}


def _need(settings: Mapping, raster: bool = False) -> list[str]:
    need = ["power", "speed", "frequency"] + (["line_interval"] if settings["mode"] == "fill" or raster else [])
    if raster:
        need += ["min_power", "dither"]
    return [key for key in need if settings.get(key) is None]


def _state(plan: Mapping, settings: Mapping) -> str:
    origin = settings.get("origin")
    if origin is None:
        return "unknown"
    if not _same_setup(origin.get("setup"), _setup(plan)) or plan["setup"]["material_id"] is None:
        return "other_setup"
    if origin["kind"] == "custom":
        return "custom"
    return "proposed" if not settings.get("confirmed") else "chosen"


def _status(plan: Mapping, settings: Mapping, raster: bool = False) -> dict:
    """Where a set stands: its state, what it still needs before an export, and one sentence for the screen."""
    state = _state(plan, settings)
    needs = []
    if plan["setup"]["material_id"] is None:
        needs.append("the material of this card")
    if state == "unknown":
        needs.append("settings chosen for this laser, lens and material")
    elif state == "other_setup":
        needs.append("settings chosen again, or confirmed, for this laser, lens and material")
    elif state in ("proposed", "custom") and not settings.get("confirmed"):
        needs.append("your confirmation")
    missing = _need(settings, raster) if state != "unknown" else []
    if missing:
        needs.append(", ".join(k.replace("_", " ") for k in missing))
    summary = {"unknown": "No settings are chosen yet.",
               "proposed": "Proposed from the workshop's measurements. Confirm them or choose others.",
               "chosen": "Chosen from the workshop's measurements.",
               "custom": "Typed by hand, the last resort.",
               "other_setup": "Chosen for another laser, lens or material."}[state]
    return {"state": state, "ready": not needs, "needs": needs, "summary": summary}


def _apply(store: Store, plan: dict, body: Mapping) -> list[str]:
    """Carry out one edit on the plan's state (not yet saved). Returns the ids of the elements it added."""
    op = body.get("op")
    if op not in EDIT_OPS:
        raise su.ValidationError("this edit is not known")
    added: list[str] = []
    if op in CARD_OPS:
        return _apply_card(store, plan, op, body)
    elements = _side(plan, body.get("side"))
    if op == "add":
        added.append(_add(store, plan, body["side"], body.get("element")))
        return added
    chosen = _find(elements, body["ids"] if "ids" in body else [body.get("id")]) if op not in ("assign_settings", "assign_choice") or body.get("ids") else []
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
    elif op == "recolour":
        parts = [e for e in chosen if e["type"] == "vector"]
        if not parts:
            raise su.ValidationError("choose imported vector parts to give a design colour")
        wanted = None if body.get("reset") is True else card_vector.fill_of(body.get("fill"))
        for element in parts:
            element["vector"]["fill"] = wanted or element["vector"]["source"]
    elif op == "scale":
        _scale(store, plan, body["side"], chosen, body.get("factor"))
    elif op in ("assign_settings", "assign_choice"):
        if op == "assign_choice":
            item = card_settings.item_by_id(store, _setup(plan), body.get("choice_id"))
            if item is None:
                raise su.ValidationError("these settings are not measured for this laser, lens and material.")
            wanted = None
        else:
            wanted = body.get("settings_id")
            if wanted is not None and wanted not in [s["id"] for s in plan["settings"]]:
                raise su.ValidationError("the engraving settings you chose no longer exist")
        members = {e["id"] for e in chosen}
        labels = set() if body.get("only") is True else {e["group"] for e in chosen if e["group"]}      # "only": just these, a part picked out of its group
        if isinstance(body.get("group"), str):
            labels.add(body["group"])
        if not members and not labels:
            raise su.ValidationError("choose the elements or the group to give these engraving settings")
        if op == "assign_choice":
            wanted = _set_of_choice(plan, item)
        for element in elements:
            if element["id"] in members or (element["group"] and element["group"] in labels):
                element["settings_id"] = wanted
        if op == "assign_choice":
            _drop_unused_copies(plan)
    return added


def _scale(store: Store, plan: dict, side: str, chosen: list[dict], factor) -> None:
    """The chosen elements made ``factor`` times as large about the centre of their boxes (their places keep their proportions), as one change."""
    factor = _number(factor, "the scale factor", *SCALE_RANGE)
    elements = plan["sides"][side]["elements"]
    cx = (min(e["x"] - e["width"] / 2 for e in chosen) + max(e["x"] + e["width"] / 2 for e in chosen)) / 2
    cy = (min(e["y"] - e["height"] / 2 for e in chosen) + max(e["y"] + e["height"] / 2 for e in chosen)) / 2
    for element in chosen:
        grown = copy.deepcopy(element)
        grown["x"], grown["y"] = cx + (element["x"] - cx) * factor, cy + (element["y"] - cy) * factor
        if element["type"] == "text":
            grown["text"]["height_mm"] = round(element["text"]["height_mm"] * factor, 4)
        else:
            grown["width"], grown["height"] = element["width"] * factor, element["height"] * factor
        merged = _checked(plan, grown)
        _fit_text(store, merged)
        elements[elements.index(element)] = merged


def _exists(store: Store, table: str, record_id) -> bool:
    return isinstance(record_id, int) and not isinstance(record_id, bool) and store.one(f"SELECT 1 FROM {table} WHERE id=?", (record_id,)) is not None


def _checked_setup(store: Store, body: Mapping) -> dict:
    device_id, lens_id, material_id = body.get("device_id"), body.get("lens_id"), body.get("material_id")
    if not _exists(store, "laser_device", device_id):
        raise su.ValidationError("choose the laser of this card.")
    if lens_id is not None and not _exists(store, "lens", lens_id):
        raise su.ValidationError("choose a lens, or the unknown lens.")
    if not _exists(store, "material_profile", material_id):
        raise su.ValidationError("choose the material of this card.")
    return {"device_id": device_id, "lens_id": lens_id, "material_id": material_id}


def _resetup(store: Store, plan: dict, setup: dict) -> None:
    """The card moves to another laser, lens or material (DEC-009): what was chosen for the old one never carries over. A set that was
    chosen is replaced by the same choice for the new setup when it is measured there, else by the proposal (the default set) or by unknown;
    a set typed by hand keeps its numbers and must be confirmed again."""
    old = _setup(plan)
    plan["setup"] = dict(setup)
    if old == setup:
        return
    complete = card_settings.setup_view(store, setup)["complete"]
    for position, current in enumerate(plan["settings"]):
        origin = current.get("origin")
        if origin is None:                                       # nothing was chosen: the first set gets the new setup's proposal, as a new card does
            if current["id"] == plan["default_settings_id"]:
                plan["settings"][position] = _proposed(store, plan, current)
            continue
        if origin["kind"] == "custom":
            plan["settings"][position] = {**current, "confirmed": False}
            continue
        item = card_settings.item_by_id(store, setup, origin.get("choice_id")) if complete else None
        if item is not None:
            plan["settings"][position] = _applied(plan, current, item, proposed=True)
        elif current["id"] == plan["default_settings_id"]:
            plan["settings"][position] = _proposed(store, plan, _unknown_set(current))
        else:
            plan["settings"][position] = _unknown_set(current)


def _apply_card(store: Store, plan: dict, op: str, body: Mapping) -> list[str]:
    if op == "set_size":
        plan["preset"], plan["size_mm"] = _card_size(body.get("preset", CUSTOM), body.get("width_mm"), body.get("height_mm"))
        return []
    if op == "set_setup":
        _resetup(store, plan, _checked_setup(store, body))
        return []
    if op == "settings_add":
        settings_id = plan["next_settings_id"]
        plan["next_settings_id"] += 1
        fresh = _checked_settings({"name": body.get("name") or f"Engraving {settings_id}"}, _blank_settings(settings_id, ""))
        plan["settings"].append(_proposed(store, plan, fresh))
        return []
    known = {s["id"]: s for s in plan["settings"]}
    settings_id = body.get("settings_id", body.get("id"))
    if settings_id not in known:
        raise su.ValidationError("these engraving settings no longer exist")
    current = known[settings_id]
    position = plan["settings"].index(current)
    if op == "settings_set":
        changes = body.get("changes")
        out = _checked_settings(changes, current)
        if any(key != "name" for key in changes):                 # a number was typed: the set is the operator's own now
            before = current.get("origin")
            note = None
            if before is not None and before["kind"] == "choice":
                note = f"Started from {before['label']}."
            elif before is not None:
                note = before.get("note")
            out["origin"], out["confirmed"] = _custom_origin(_setup(plan), note), True
        plan["settings"][position] = out
    elif op == "settings_apply":
        item = card_settings.item_by_id(store, _setup(plan), body.get("choice_id"))
        if item is None:
            raise su.ValidationError("these settings are not measured for this laser, lens and material.")
        plan["settings"][position] = _applied(plan, current, item, proposed=False)
    elif op == "settings_confirm":
        origin = current.get("origin")
        if origin is None:
            raise su.ValidationError("there are no settings to confirm: choose some first.")
        if origin["kind"] == "choice" and not _same_setup(origin.get("setup"), _setup(plan)):
            raise su.ValidationError("these settings were chosen for another laser, lens or material: choose them again.")
        plan["settings"][position] = {**current, "origin": {**origin, "setup": _setup(plan), "proposed": False}, "confirmed": True}
    elif op == "settings_custom":
        before = current.get("origin")
        note = f"Started from {before['label']}." if before is not None and before["kind"] == "choice" else None
        plan["settings"][position] = {**current, "origin": _custom_origin(_setup(plan), note), "confirmed": True}
    else:                                                          # settings_delete
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


# -- imported vector artwork (feature-3) --------------------------------------------------------------------------------------------------
def _suggest_engraving(store: Store, plan: dict, parts: list[dict]) -> dict:
    """Give the parts of a new artwork the measured engraving colour that is close to their design colour (the operator changes any of them
    with the chooser; a colour with no close match keeps the card's default settings and is told so). Returns what was done, for the report."""
    setup = _setup(plan)
    colours = sorted({e["vector"]["fill"] for e in parts})
    items = card_settings.colour_items(store, setup)
    out = {"available": bool(items), "reason": None, "colours": len(colours), "assigned": 0, "unmatched": []}
    if not items:
        out["reason"] = card_settings.REASONS["color" if card_settings.setup_view(store, setup)["complete"] else "setup"]
        return out
    found = card_vector.matches(colours, items)
    by_id = {item["id"]: item for item in items}
    for colour in colours:
        best = found[colour]["best"]
        if best is not None and found[colour]["close"]:
            settings_id = _set_of_choice(plan, by_id[best["choice_id"]])
            for element in parts:
                if element["vector"]["fill"] == colour:
                    element["settings_id"] = settings_id
            out["assigned"] += 1
        else:
            out["unmatched"].append(colour)
    if out["assigned"]:
        _drop_unused_copies(plan)
    return out


def import_vector(store: Store, plan_id: int, side: str, file_name: str, data: bytes) -> dict:
    """Import an SVG or Adobe Illustrator file as a group of editable parts on a side (REQ-003): each path of the file is a part with its design
    colour, the drawing is fitted to the card and centred, close measured engraving colours are suggested for it (REQ-004), all as one change
    that can be undone. Returns the work with ``added`` and ``import``: what was imported and what could not be carried over."""
    plan = _work(store, plan_id)
    elements = _side(plan, side)
    room = MAX_ELEMENTS - len(elements)
    if room < 1:
        raise su.ValidationError(f"a side holds at most {MAX_ELEMENTS} elements")
    parsed = card_vector.read(data, file_name or "")
    stem = (Path(file_name or "").stem or "artwork")[:40]
    card = size_mm(plan)
    artwork = card_vector.prepare(parsed, stem, card, room)
    before = _here(plan)
    stored = card_vector.store(store.data_dir, artwork)
    factor, shown = artwork["factor"], (file_name or "artwork")[:MAX_NAME]
    label = None
    if len(artwork["parts"]) > 1:
        label = f"g{plan['next_id']}"
        plan["next_id"] += 1
    added = []
    for number, item in enumerate(artwork["parts"]):
        x0, y0, x1, y1 = item["box"]
        spec = {"id": f"e{plan['next_id']}", "type": "vector", "name": item["name"], "rotation": 0.0, "group": label, "settings_id": None,
                "x": card["width"] / 2 + ((x0 + x1) / 2 - artwork["width"] / 2) * factor, "y": card["height"] / 2 + ((y0 + y1) / 2 - artwork["height"] / 2) * factor,
                "width": max((x1 - x0) * factor, MIN_VECTOR_MM), "height": max((y1 - y0) * factor, MIN_VECTOR_MM),
                "vector": {"artwork": stored, "part": number, "fill": item["fill"], "source": item["fill"], "file": shown, "kind": artwork["kind"]}}
        plan["next_id"] += 1
        elements.append(_checked(plan, spec))
        added.append(spec["id"])
    parts = [e for e in elements if e["id"] in added]
    report = {**artwork["report"], "size_mm": {"width": round(artwork["width"] * factor, 1), "height": round(artwork["height"] * factor, 1)},
              "file": shown, "engraving": _suggest_engraving(store, plan, parts)}
    _push(plan, before)
    plan["updated_at"] = now()
    out = _view(store, plan, added)                 # drawn before anything is saved: a file whose parts cannot be drawn is refused, not kept in the card
    if any(UNREADABLE_PART in problem for e in out["sides"][side]["elements"] if e["id"] in added for problem in e["problems"]):
        raise su.ValidationError("the shapes of this file could not be built: save it again from the program that made it, or export it as SVG")
    out["import"] = report
    with store.transaction():
        _save(store, plan, plan["id"])
        store.audit("card_work_vector_added", plan_id=plan["id"], kind=artwork["kind"], parts=len(added))
    return out


def colour_matches(store: Store, plan_id: int, colours) -> dict:
    """For design colours, the measured engraving colours of this card's own laser, lens and material that are nearest, by ΔE (REQ-004):
    ``matches[colour]`` has ``best`` (None when nothing is measured), ``close`` and ``alternatives``; ``available`` and ``reason`` say whether and why not."""
    plan = _work(store, plan_id)
    if not isinstance(colours, (list, tuple)) or len(colours) > MAX_COLOURS_ASKED:
        raise su.ValidationError(f"ask for at most {MAX_COLOURS_ASKED} colours at a time")
    wanted = sorted({card_vector.fill_of(c) for c in colours})
    setup = _setup(plan)
    items = card_settings.colour_items(store, setup)
    reason = None if items else card_settings.REASONS["color" if card_settings.setup_view(store, setup)["complete"] else "setup"]
    return {"available": bool(items), "reason": reason, "close_delta_e": card_vector.CLOSE_DELTA_E, "matches": card_vector.matches(wanted, items)}


# -- the view ---------------------------------------------------------------------------------------------------------------------------
def _is_raster(element: Mapping) -> bool:
    return element["type"] == "image" and element["image"].get("engrave") == "raster"


def _raster_params(element: Mapping) -> dict:
    return {k: v for k, v in element["image"].items() if k in card_image.DEFAULTS}


def _raster_look(plan: Mapping, element: Mapping) -> dict:
    """What decides the pixels of a raster picture: its set's line interval (as DPI), image mode and dot width, with plain grey and a
    default DPI shown until the set gives them."""
    settings = {s["id"]: s for s in plan["settings"]}[_effective(plan, element)]
    interval = settings.get("line_interval")
    return {"dpi": float(grayscale.image_dpi(interval)) if interval else RASTER_DPI_PREVIEW, "dither": settings.get("dither") or "grayscale",
            "dot_width": settings.get("dot_width"), "given": bool(interval and settings.get("dither"))}


def _raster_key(element: Mapping, look: Mapping) -> str:
    parts = {"stamp": rc.file_stamp(element["image"]["file"]), "w": round(element["width"], 3), "h": round(element["height"], 3),
             "rotation": element["rotation"], "params": _raster_params(element), "look": look}
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _raster_view(plan: Mapping, element: Mapping) -> dict:
    look = _raster_look(plan, element)
    width, height = card_raster.bounds(element["width"], element["height"], element["rotation"])
    scale = look["dpi"] / grayscale.MM_PER_INCH
    return {"url": f"/api/card-works/{plan['id']}/elements/{element['id']}/raster.png?v={_raster_key(element, look)}",
            "width_px": round(width * scale), "height_px": round(height * scale), "dpi": look["dpi"], "dither": look["dither"],
            "given": look["given"]}


def raster_png(store: Store, plan_id: int, element_id: str) -> bytes:
    """The dithered look of a raster picture at its size, as the screen shows it (REQ-026)."""
    plan = _work(store, plan_id)
    for side in SIDES:
        for element in plan["sides"][side]["elements"]:
            if element["id"] == element_id and _is_raster(element):
                look = _raster_look(plan, element)
                key = _raster_key(element, look)
                with _lock:
                    if key in _rasters:
                        _rasters.move_to_end(key)
                        return _rasters[key]
                pixels = card_raster.prepare(Path(element["image"]["file"]).read_bytes(), element["width"], element["height"], element["rotation"],
                                             look["dpi"], _raster_params(element))
                png = card_raster.preview_png(pixels, look["dither"], look["dot_width"], look["dpi"])
                _remember(_rasters, key, png, KEEP_RASTERS)
                return png
    raise KeyError(f"raster picture {element_id} not found")


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
        found = list(problems)
        if _is_raster(item) and not local.is_empty:                  # a picture too large for its line interval cannot be made: say so before export
            try:
                card_raster.check(item["width"], item["height"], item["rotation"], _raster_look(plan, item)["dpi"])
            except su.ValidationError as error:
                found.append(str(error))
        built.append({"element": item, "geometry": _placed(local, item), "problems": found})
    return built


def _element_view(plan: Mapping, built: list[dict], index: int, card) -> dict:
    entry = built[index]
    element, geometry = entry["element"], entry["geometry"]
    out = copy.deepcopy(element)
    if element["type"] == "image":
        out["image"].pop("file", None)
        out["raster"] = _raster_view(plan, element) if _is_raster(element) and not geometry.is_empty and not entry["problems"] else None
    if element["type"] == "vector":
        out["color"] = element["vector"]["fill"]
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


def _raster_sets(plan: Mapping) -> set[int]:
    """The ids of the settings sets that engrave at least one raster picture (on either side)."""
    return {_effective(plan, e) for side in SIDES for e in plan["sides"][side]["elements"] if _is_raster(e)}


def _review(plan: Mapping, side: str, built: list[dict]) -> dict:
    sets: dict[int, dict] = {}
    rows = []
    problems = []
    names = {s["id"]: s for s in plan["settings"]}
    engraved = [b for b in built if not b["geometry"].is_empty]
    raster_ids = {_effective(plan, b["element"]) for b in engraved if _is_raster(b["element"])}
    for entry in built:
        element = entry["element"]
        effective = _effective(plan, element)
        status = _status(plan, names[effective], effective in raster_ids)
        rows.append({"id": element["id"], "name": element["name"], "type": element["type"], "settings_id": element["settings_id"],
                     "effective_settings_id": effective, "complete": status["ready"], "empty": entry["geometry"].is_empty,
                     "raster": _is_raster(element)})
        if not entry["geometry"].is_empty:
            sets.setdefault(effective, {"settings_id": effective, "name": names[effective]["name"], "elements": [], "state": status["state"],
                                        "needs": status["needs"], "missing": _need(names[effective], effective in raster_ids)})
            sets[effective]["elements"].append(element["id"])
    for entry in engraved:
        if _is_raster(entry["element"]):
            problems += [f"The picture “{entry['element']['name']}” cannot be engraved as a photo: {text}" for text in entry["problems"]]
    for item in sets.values():
        item["complete"] = not item["needs"]
        if item["needs"]:
            problems.append(f"The engraving settings “{item['name']}” still need " + "; ".join(item["needs"]) + ".")
    if not engraved:
        problems.append(f"There is nothing to engrave on the {side}")
    return {"ready": not problems, "problems": problems, "sets": sorted(sets.values(), key=lambda s: s["settings_id"]), "elements": rows,
            "empty": not engraved}


def _named(record) -> dict | None:
    if not isinstance(record, dict) or record.get("id") is None:
        return None
    return {"id": record["id"], "name": record.get("name") or record.get("label") or record.get("title") or f"#{record['id']}"}


def _setup_view(store: Store, plan: Mapping) -> dict:
    """The card's laser, lens and material with their names, and what is still missing (REQ-024)."""
    seen = card_settings.setup_view(store, _setup(plan))
    return {"set": plan["setup"]["material_id"] is not None, "device_id": plan["setup"]["device_id"], "lens_id": plan["setup"]["lens_id"],
            "material_id": plan["setup"]["material_id"], "device": _named(seen.get("device")), "lens": _named(seen.get("lens")),
            "material": _named(seen.get("material")), "complete": bool(seen.get("complete")), "missing": list(seen.get("missing") or [])}


def _view(store: Store, plan: dict, added=None) -> dict:
    card_size = size_mm(plan)
    card = shapely_box(0, 0, card_size["width"], card_size["height"])
    sides, review = {}, {}
    for side in SIDES:
        built = _side_elements(store, plan, side)
        sides[side] = {"elements": [_element_view(plan, built, i, card) for i in range(len(built))]}
        review[side] = _review(plan, side, built)
    setup = _setup_view(store, plan)
    raster_ids = _raster_sets(plan)
    settings = [{**copy.deepcopy(item), "status": _status(plan, item, item["id"] in raster_ids)} for item in plan["settings"]]
    out = {"id": plan["id"], "name": plan["name"], "size_mm": card_size, "preset": plan["preset"], "presets": PRESETS, "sides": sides,
           "settings": settings, "default_settings_id": plan["default_settings_id"], "review": review, "setup": setup,
           "can_undo": bool(plan["undo"]), "can_redo": bool(plan["redo"]), "updated_at": plan["updated_at"],
           "laser": setup["device"], "generation": generation(store), "qr": {"thresholds": card_qr.THRESHOLDS}}
    if added is not None:
        out["added"] = list(added)
    return out


def settings_choices(store: Store, plan_id: int) -> dict:
    """What the operator can choose for a set of this card: the measurements of its own laser, lens and material, by type."""
    return card_settings.choices(store, _setup(_work(store, plan_id)))


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
    paths, pictures = [], []
    for entry in _side_elements(store, plan, side):
        if entry["geometry"].is_empty:
            continue
        if _is_raster(entry["element"]):
            element = entry["element"]
            width, height = card_raster.bounds(element["width"], element["height"], element["rotation"])
            png = base64.b64encode(raster_png(store, plan["id"], element["id"])).decode("ascii")
            pictures.append(f'<image href="data:image/png;base64,{png}" x="{_fmt(element["x"] - width / 2)}" y="{_fmt(element["y"] - height / 2)}" '
                            f'width="{_fmt(width)}" height="{_fmt(height)}"/>')
        else:
            tint = f' fill="{entry["element"]["vector"]["fill"]}"' if entry["element"]["type"] == "vector" else ""
            paths.append(f'<path d="{path_d(entry["geometry"])}" fill-rule="evenodd"{tint}/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(card["width"])} {_fmt(card["height"])}">'
            f'<rect width="{_fmt(card["width"])}" height="{_fmt(card["height"])}" rx="3" fill="{CARD_FILL}"/>'
            f'<g fill="{ENGRAVED_FILL}">{"".join(paths)}</g>{"".join(pictures)}</svg>')


def _layer_parameters(settings: Mapping, *, image: bool) -> dict:
    keys = ["power", "frequency", "speed", "pulse_width", "line_interval", "passes"]
    values = {k: settings[k] for k in keys}
    if image:
        values.update({k: settings[k] for k in ("min_power", "global_passes", "dot_width")})
    elif settings["mode"] != "fill":
        values["line_interval"] = None
    return values


def export(store: Store, plan_id: int, side: str) -> tuple[bytes, str]:
    """One side as a LightBurn project (DEC-035): its shapes in the card's millimetres, one scan or cut layer for each set of engraving
    settings the side's shapes use, one image layer for each picture engraved as a raster photo (REQ-026), written as the settings give them
    (the fields of the source engraving too, REQ-023). Refused with the problems of the side's review when it is not ready."""
    plan = _work(store, plan_id)
    _side(plan, side)
    built = _side_elements(store, plan, side)
    review = _review(plan, side, built)
    if not review["ready"]:
        raise su.ValidationError("the " + side + " is not ready to export: " + "; ".join(review["problems"]))
    names = {s["id"]: s for s in plan["settings"]}
    engraved = [b for b in built if not b["geometry"].is_empty]
    shapes = [b for b in engraved if not _is_raster(b["element"])]
    pictures = [b for b in engraved if _is_raster(b["element"])]
    layers, regions = [], []
    for position, settings_id in enumerate(sorted({_effective(plan, b["element"]) for b in shapes}), start=1):
        s = names[settings_id]
        layer = {"index": position, "name": s["name"], "cut_type": "Scan" if s["mode"] == "fill" else "Cut", "regions": [],
                 "layer_keys": [f"s{settings_id}"], "prediction": None, "parameters": _layer_parameters(s, image=False)}
        scan = {k: s[k] for k in ("global_passes", "bidirectional", "cross_hatch", "scan_angle") if s.get(k) is not None}
        if scan:
            layer["lightburn_settings"] = scan
        layers.append(layer)
    for entry in shapes:
        loops = _rings(entry["geometry"])
        if loops:
            regions.append({"id": entry["element"]["id"], "layer_key": f"s{_effective(plan, entry['element'])}", "loops": loops, "strokes": []})
    for entry in pictures:
        element = entry["element"]
        s = names[_effective(plan, element)]
        width, height = card_raster.bounds(element["width"], element["height"], element["rotation"])
        pixels = card_raster.prepare(Path(element["image"]["file"]).read_bytes(), element["width"], element["height"], element["rotation"],
                                     float(grayscale.image_dpi(s["line_interval"])), _raster_params(element))
        stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in element["name"]).strip("-") or "picture"
        layers.append({"index": len(layers) + 1, "name": f"{s['name']} - {element['name']}", "cut_type": "Image", "regions": [], "layer_keys": [],
                       "prediction": None, "parameters": _layer_parameters(s, image=True),
                       "picture": {"x": element["x"] - width / 2, "y": element["y"] - height / 2, "width": width, "height": height,
                                   "pixels": pixels, "file": f"{stem}.png", "dither": s["dither"]}})
    own = _setup(plan)                                  # the file names the card's own laser, lens and material, not the workshop's current ones
    device = devices.brief(store, own["device_id"]) if _exists(store, "laser_device", own["device_id"]) else None
    lens = lenses.get_lens(store, own["lens_id"]) if _exists(store, "lens", own["lens_id"]) else None
    material = store.one("SELECT * FROM material_profile WHERE id=?", (own["material_id"],))
    data = pl.export_lbrn2({"mode": MODE, "name": f"{plan['name']} {side}", "layers": layers, "vector_document": {"regions": regions},
                            "size_mm": size_mm(plan), "export_mirror_y": True, "plan_identifier": "",
                            "experiment": {"label": f"Business card {side}", "test_name": plan["name"], "device": device or {}, "lens": lens or {},
                                           "material": dict(material) if material else {}}})
    store.audit("card_work_exported", plan_id=plan["id"], side=side)
    return data, f"{plan['name']} {side}"
