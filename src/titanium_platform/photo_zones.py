"""Photo zones of a vector work (REQ-073, DEC-114): regions of the split engraved as a photo engraving of the work's own picture instead
of flat titanium colours, so that a picture is part vectors and part photo engraving (a face in grayscale, the clothes and background in
colours).

A zone is kept in the work's colouring (``colouring["photo"]``, a list), so the editor's undo and redo, the copy of a work and its history
carry it like any other choice of the operator (editor DEC-077). It holds

* ``number``: 1, 2, ... in the order the zones were made; a number is not given again while the work keeps a higher one;
* ``regions``: the ids of the split's regions it covers;
* ``kind``: grayscale or one of LightBurn's dot kinds (:data:`KINDS`, as a photo work offers them);
* ``scale``: the titanium and the fixed settings of a measured grey scale (as a photo work keeps it); the laser and lens are the work's;
* ``min_power`` and ``max_power`` (grayscale: white and black) and ``dot_power`` (a dot kind fires every dot at it), or ``dot_recipe``: the
  dots' colour picked on the colour map (0.27.0, :mod:`dot_colours`, as a photo work's, DEC-118): they fire at its settings, its step their
  pitch, at its colour at the zone's width;
* ``tone``: the picture's brightness, contrast and gamma (0.27.0, ``photo_state.toned``), as a photo work's;
* ``by_colour``: the greys are chosen so that the titanium colours follow the picture's colours, as the vector colours follow it; off,
  the picture's own greys are engraved;
* how the greys are chosen (:data:`GREYS`, 0.23.0, DEC-116), as a photo work chooses them (:mod:`photo_state`): keeping the drawing, the
  default, the nearest colour or colouring the objects (``colour_choice``, DEC-108, DEC-109), the lost edges drawn in (``contours``), the
  main colours of the picture's objects (``colouring``) and the rules of its parts (``rules``); and the AI's last answers about them
  (:data:`ANSWERS`). A zone made before them reads them as :data:`DEFAULTS` (:func:`full`).

What a zone engraves is the work's original picture cut to the zone's box and made transparent outside its regions, rasterised from the
same smoothed borders the file's paths are written from (:func:`cut`); in the file it is one Image layer after the colour layers
(:func:`file_layer`). Its colours are those of its scale at rows as long as the zone is wide (DEC-107). A dot kind is shown from the scale
(each dot in the scale's colour at the dots' power, cleaned titanium between them) until that kind is photographed at that power.

The functions take the work's plan, its region loops in mm and the store; nothing here reads or writes the work itself (:mod:`vector_job`
does), and no work module is imported.
"""
from __future__ import annotations

import copy
import json
import math
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import cv2
import numpy as np

from . import (color, conversion as cv, dot_colours as dc, engraving_time, evidence_source as es, grayscale, photo_knowledge as pk, photo_modes,
               photo_state as st, prediction, prediction_store as ps, render_cache as rc)
from .db import Store
from .prediction import PredictionError

GRAYSCALE = st.GRAYSCALE
KINDS = st.KINDS                    # every kind of photo engraving that colours titanium, as a photo work offers them
GREYS = ("colour_choice", "contours", "rules", "colouring")
SETTINGS = ("kind", "scale", "min_power", "max_power", "dot_power", "dot_recipe", "by_colour", "tone", "tone_after_match", "sharpness", *GREYS)
# what the operator changes: the settings, the dots' colour picked on the colour map (``dot_colour``: a point's group) instead of the recipe
CHANGES = tuple(k for k in SETTINGS if k not in ("dot_recipe", "tone_after_match")) + ("dot_colour", "dot_settings")
# a change of the kind alone fills in the best measured engraving of the new kind (photo_knowledge.filled); with any of these it does not
FILLED_UNLESS = ("scale", "min_power", "max_power", "dot_colour", "dot_settings", "dot_power")
ANSWERS = ("ai", "ai_theme")
DEFAULTS = {k: st.DEFAULTS[k] for k in (*GREYS, "dot_recipe", "tone", "tone_after_match", "sharpness", *ANSWERS)}      # defaults for older zones
LASSO_SHARE = 0.5           # a region is inside a lasso (or an old zone, after a new split) when at least this share of it is
FILE_PX_PER_MM = 20.0       # the zone's picture in the file has this many pixels a mm (fewer when the layer's DPI is lower): its
                            # transparent edge follows the smoothed borders to 0.05 mm, and a zone of a whole 150 mm work stays under 9 Mpx
PREVIEW_PX = ps.PREVIEW_SIDE
TILE_PX = 240               # the longer side of a zone's picture in one kind (the tiles of «Вид»)
KEEP_DECODED = 2            # decoded pictures kept in memory: the work open now and the one before

KEEP_CUTS = 2               # cut zones kept in memory: the tiles of every kind of a zone are drawn from one cut
_decoded: OrderedDict[str, dict] = OrderedDict()
_cuts: OrderedDict[str, dict] = OrderedDict()
_lock = threading.Lock()


class ZoneError(ValueError):
    """A zone operation that cannot be done; the message says why (the screen translates it)."""


# -- what a zone is -------------------------------------------------------------------------------------------------------------
def zones(colouring: Mapping | None) -> list[dict]:
    """The zones of a colouring (none for a work made before them)."""
    return list((colouring or {}).get("photo") or [])


def zone_of(colouring: Mapping | None) -> dict[str, int]:
    """Region id -> the number of the zone it is in."""
    return {rid: z["number"] for z in zones(colouring) for rid in z["regions"]}


def full(zone: Mapping) -> dict:
    """The zone with what one made before 0.23.0 lacks (:data:`DEFAULTS`); the stored zone is not changed."""
    return {**copy.deepcopy(DEFAULTS), **zone}


def find(colouring: Mapping, number) -> dict:
    zone = next((z for z in zones(colouring) if not isinstance(number, bool) and z["number"] == number), None)
    if zone is None:
        raise ZoneError(f"there is no photo zone {number!r}")
    return zone


def mode_of(plan: Mapping, zone: Mapping) -> ps.Mode:
    """The grey scale a zone is engraved on: the laser and lens of the work's source (its own, or its pinned laboratory release's), the
    zone's titanium and settings."""
    scale = zone["scale"]
    device_id, lens_id = es.setup_of(plan)
    return ps.mode_of({**{k: scale.get(k) for k in ps.SETTINGS}, "global_passes": scale.get("global_passes")}, device_id, lens_id,
                      scale.get("material_id"))


def fired(plan: Mapping, zone: Mapping) -> ps.Mode:
    """The settings the zone's layer fires at: its scale's, or in a dot kind with dots picked on the colour map that recipe's."""
    mode = mode_of(plan, zone)
    return st.fired_at(mode, zone) if dotted(zone) else mode


def layer_dpi(plan: Mapping, zone: Mapping) -> float | None:
    """The DPI of the zone's layer: its step's (:func:`fired`)."""
    step = fired(plan, zone).line_interval
    return grayscale.image_dpi(step) if step else None


def scale_data(mode: ps.Mode) -> dict:
    return {"material_id": mode.material_id, **{k: getattr(mode, k) for k in ps.SETTINGS}, "global_passes": mode.global_passes}


def dotted(zone: Mapping) -> bool:
    return zone["kind"] != GRAYSCALE


# -- where a zone lies ------------------------------------------------------------------------------------------------------------
def _bounds(loops: Mapping[str, list], region_ids) -> tuple[float, float, float, float]:
    points = np.concatenate([np.asarray(loop, np.float64) for rid in region_ids for loop in loops.get(rid, []) if len(loop)])
    return float(points[:, 0].min()), float(points[:, 1].min()), float(points[:, 0].max()), float(points[:, 1].max())


def width_of(loops: Mapping[str, list], region_ids) -> float:
    """How wide a zone is, mm: the length of its picture's rows, which sets its colours (DEC-107)."""
    x0, _, x1, _ = _bounds(loops, region_ids)
    return max(x1 - x0, 1.0)


def area_of(document: Mapping, region_ids) -> float:
    """The area a zone engraves, mm², from its regions' pixels as the colour layers count theirs."""
    inside = set(region_ids)
    return sum(r["pixels"] for r in document["regions"] if r["id"] in inside) * document["px_mm"] ** 2


# -- the default and the changes of a zone ----------------------------------------------------------------------------------------
def _engravings(curve: prediction.Curve) -> int:
    return len({prediction._engraving_of(src) for row in curve.points for src in row["sources"]})


def best_scale(store: Store, plan: Mapping, width_mm: float) -> ps.Mode:
    """The scale a first zone takes: of the work's laser, lens and titanium, measured at the zone's width, the best measured as the list
    of scales orders them (chart-referenced colours, then more engravings, then more points)."""
    ranked = []
    device_id, lens_id = es.setup_of(plan)
    for mode in ps.scale_modes(store, device_id, lens_id, es.material_of(plan)):
        try:
            curve = ps.curve_for(store, mode, width_mm)[0]
        except PredictionError:
            continue
        ranked.append(((not curve.referenced, -_engravings(curve), -len(curve.points)), len(ranked), mode))
    if not ranked:
        raise ZoneError("no grey scale is measured on this laser, lens and titanium: engrave the grey-ramp plate (Фотогравировка → Шкалы серого) "
                        "to make a photo zone")
    return min(ranked)[2]


def new_zone(store: Store, plan: Mapping, colouring: Mapping, region_ids: list[str], width_mm: float) -> dict:
    """A zone of ``region_ids`` numbered after the others. It takes the photo engraving of the last zone made, so zones made one after another
    match; the first takes the best scale (:func:`best_scale`), grayscale over the span measured at its width and colours by the picture."""
    others = zones(colouring)
    number = 1 + max((z["number"] for z in others), default=0)
    if others:
        last = full(others[-1])
        zone = {"number": number, "regions": list(region_ids), **copy.deepcopy({k: last[k] for k in SETTINGS}),
                **copy.deepcopy({k: DEFAULTS[k] for k in ANSWERS})}
        return settle(store, plan, zone, width_mm)
    mode = best_scale(store, plan, width_mm)
    low, high = pk.default_span(store, mode, width_mm)
    return {"number": number, "regions": list(region_ids), "kind": GRAYSCALE, "scale": scale_data(mode), "min_power": low, "max_power": high,
            "dot_power": None, "by_colour": True, **copy.deepcopy(DEFAULTS)}


def settle(store: Store, plan: Mapping, zone: dict, width_mm: float) -> dict:
    """After its regions or scale changed: a dot kind's power falls back to the default when the scale is not measured there at the zone's
    width (as a photo work's does), and dots picked on the colour map take their colour at the zone's new width (``dot_colours.at_width``).
    A zone whose scale is no longer measured is kept as it is: the view says why it cannot be shown."""
    if dotted(zone):
        try:
            zone["dot_power"] = ps.dot_power_at(store, mode_of(plan, zone), width_mm, zone.get("dot_power"))
        except PredictionError:
            pass
    recipe = zone.get("dot_recipe")
    if recipe and recipe["size"] and recipe["size"]["row_mm"] != round(float(width_mm), 1):    # ``palette.at_size`` keeps the length to 0.1 mm
        zone["dot_recipe"] = dc.at_width(store, mode_of(plan, zone), recipe, width_mm)
    return zone


def _number(value, what: str) -> float:
    number = math.nan if isinstance(value, bool) else value
    try:
        number = float(number)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number):
        raise ZoneError(f"the {what} must be a number")
    return number


def changed(store: Store, plan: Mapping, zone: Mapping, changes: Mapping, width_mm: float) -> dict:
    """The zone with the operator's ``changes`` of its photo engraving (any of :data:`CHANGES`), checked; the zone is not changed. A new
    scale brings Min and Max to its span at the zone's width; a dot kind's power must lie in the scale's measured powers there; how the
    greys are chosen (:data:`GREYS`) and the tone are checked as a photo work's (``photo_state.change``). The dots' colour picked on the
    colour map (``dot_colour``, ``dot_colours.picked``, as a photo work's): a tone of a grey scale moves the zone to that scale at that
    power, a fill keeps its recipe (``dot_recipe``); another scale or a power on the scale puts the dots back on the scale. The settings the
    dots fire at (``dot_settings``, ``photo_knowledge.dots_at``: a step darker or lighter). A change of the kind alone fills in the best
    measured engraving of the new kind on the zone's titanium (``photo_knowledge.filled``, feature photo-engraving-quality REQ-004)."""
    unknown = sorted(set(changes) - set(CHANGES))
    if unknown:
        raise ZoneError(f"a photo zone has no setting {unknown[0]!r}")
    out = full(copy.deepcopy(dict(zone)))
    if "kind" in changes:
        if changes["kind"] not in KINDS:
            raise ZoneError(f"there is no kind of photo engraving {changes['kind']!r}")
        out["kind"] = changes["kind"]
    recipe = None
    if "dot_colour" in changes:
        if not dotted(out):
            raise ZoneError("the dots' colour is picked for a dot kind: choose one of them first")
        picked = dc.picked(store, mode_of(plan, out), width_mm, changes["dot_colour"])
        recipe = picked.pop("dot_recipe", None)
        changes = {**{k: v for k, v in changes.items() if k != "dot_colour"}, **picked}
    if "dot_settings" in changes:
        if not dotted(out) or not isinstance(changes["dot_settings"], Mapping):
            raise ZoneError("the dots' settings are given for a dot kind: choose one of them first")
        found = pk.dots_at(store, mode_of(plan, out), out["kind"], changes["dot_settings"], width_mm, zone.get("dot_recipe") if dotted(zone) else None)
        recipe = found["dot_recipe"]
        changes = {**{k: v for k, v in changes.items() if k != "dot_settings"}, **({"dot_power": found["dot_power"]} if recipe is None else {})}
    if "kind" in changes and changes["kind"] != zone.get("kind") and not set(FILLED_UNLESS) & set(changes):
        filled = pk.filled(store, mode_of(plan, out), changes["kind"], dot_width=False)    # a zone writes no dot width
        if filled is not None and "scale" in filled:            # grayscale: its best scale and the span of its tones in order
            changes = {**changes, "scale": scale_data(filled["scale"]), "min_power": filled["min_power"], "max_power": filled["max_power"]}
        elif filled is not None:                                # a dot kind: the dots of its best photographed engraving
            recipe = filled["dot_recipe"]
    if "scale" in changes or ("dot_power" in changes and changes["dot_power"] is not None):
        out["dot_recipe"] = None
    if "scale" in changes:
        wanted = changes["scale"]
        if not isinstance(wanted, Mapping):
            raise ZoneError("the scale must name the titanium and settings of a measured scale")
        device_id, lens_id = es.setup_of(plan)
        mode = ps.measured_mode(store, {**wanted, "device_id": device_id, "lens_id": lens_id})
        out["scale"] = scale_data(mode)
        try:
            out["min_power"], out["max_power"] = pk.default_span(store, mode, width_mm)
        except PredictionError as exc:
            raise ZoneError(str(exc)) from None
    if "min_power" in changes or "max_power" in changes:
        low = _number(changes.get("min_power", out["min_power"]), "Min power")
        high = _number(changes.get("max_power", out["max_power"]), "Max power")
        try:
            out["min_power"], out["max_power"] = ps.check_power_range(low, high)
        except PredictionError as exc:
            raise ZoneError(str(exc)) from None
    if "by_colour" in changes:
        if not isinstance(changes["by_colour"], bool):
            raise ZoneError("«colours by the picture» must be on or off")
        out["by_colour"] = changes["by_colour"]
    greys = {k: changes[k] for k in (*GREYS, "tone", "sharpness") if k in changes}
    if greys:
        st.change(store, out, greys, mode_of(plan, out), width_mm)
    if "dot_power" in changes and changes["dot_power"] is not None:
        power = _number(changes["dot_power"], "dots' power")
        try:
            lo, hi = ps.curve_for(store, mode_of(plan, out), width_mm)[0].span
        except PredictionError as exc:
            raise ZoneError(str(exc)) from None
        if not lo <= power <= hi:
            raise ZoneError(f"the dots' power {power:g} % lies outside the measured powers {lo:g}..{hi:g} % of the scale at this width: choose it inside them")
        out["dot_power"] = power
    if recipe is not None:
        out["dot_recipe"] = recipe
    return settle(store, plan, out, width_mm)


# -- the regions of a lasso, and of an old zone on a new split ---------------------------------------------------------------------
def labels(document: Mapping, loops: Mapping[str, list]) -> np.ndarray:
    """The split as a raster of the working picture's pixels: the index of the region (in the document's order) whose shape covers each
    pixel centre, -1 where none does. ``loops``: region id -> its closed loops in mm (the regions tile the picture, so a hole is left as
    it is and the region inside it fills it, whichever is drawn first)."""
    cols, rows = document["image_px"]["width"], document["image_px"]["height"]
    out = np.full((rows, cols), -1, np.int32)
    k = 1.0 / document["px_mm"]
    for index, region in enumerate(document["regions"]):
        polygons = [_fixed(loop, k) for loop in loops.get(region["id"], []) if len(loop) >= 3]
        if polygons:
            cv2.fillPoly(out, polygons, index, shift=4)
    return out


def _fixed(loop, k: float, origin=(0.0, 0.0)) -> np.ndarray:
    """A loop in mm as fillPoly's points with 4 fractional bits, a pixel's centre at its index (a mm ``x`` lies at ``x * k - 0.5``)."""
    return np.round(((np.asarray(loop, np.float64) - origin) * k - 0.5) * 16).astype(np.int32)


def inside(document: Mapping, raster: np.ndarray, mask: np.ndarray, share: float = LASSO_SHARE) -> list[str]:
    """The regions of ``document`` (``raster`` from :func:`labels`) of which at least ``share`` lies in ``mask``, in the document's order."""
    n = len(document["regions"])
    known = raster >= 0
    total = np.bincount(raster[known], minlength=n)
    within = np.bincount(raster[known & mask], minlength=n)
    return [r["id"] for i, r in enumerate(document["regions"]) if total[i] and within[i] >= share * total[i]]


def lasso(document: Mapping, raster: np.ndarray, points) -> list[str]:
    """The regions a lasso drawn through ``points`` (mm, at least three) encloses: at least half of each."""
    try:
        polygon = np.asarray(points, np.float64)
    except (TypeError, ValueError):
        polygon = np.zeros((0, 2))
    if polygon.ndim != 2 or polygon.shape[0] < 3 or polygon.shape[1] != 2 or not np.all(np.isfinite(polygon)):
        raise ZoneError("a lasso needs three points or more, each x and y in mm")
    mask = np.zeros(raster.shape, np.uint8)
    cv2.fillPoly(mask, [_fixed(polygon, 1.0 / document["px_mm"])], 1, shift=4)
    return inside(document, raster, mask.astype(bool))


def carried(old: Mapping, old_raster: np.ndarray, new: Mapping, new_raster: np.ndarray, colouring_zones: list[dict]) -> list[dict]:
    """The zones of a split carried over to a new split of the same picture: each takes the new regions at least half inside it; a zone left
    without a region is dropped."""
    index = {r["id"]: i for i, r in enumerate(old["regions"])}
    out = []
    for zone in colouring_zones:
        mask = np.isin(old_raster, [index[r] for r in zone["regions"] if r in index])
        regions = inside(new, new_raster, mask) if old_raster.shape == new_raster.shape else []
        if regions:
            out.append({**copy.deepcopy(zone), "regions": regions})
    return out


# -- the picture of a zone --------------------------------------------------------------------------------------------------------
def _source(plan: Mapping) -> dict:
    """The work's picture as the vector work reads it (``conversion.decode_image_bytes``, so it lies exactly under the split): its colour
    and its grey by luminance, as LightBurn converts a colour picture for an Image layer; from memory when it was decoded lately."""
    path = plan["image_path"]
    key = json.dumps(rc.file_stamp(path), sort_keys=True)
    with _lock:
        if key in _decoded:
            _decoded.move_to_end(key)
            return _decoded[key]
    try:
        bgr = cv.decode_image_bytes(Path(path).read_bytes())
    except OSError:
        raise KeyError("the stored source image is missing") from None
    found = {"bgr": bgr, "grey": cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0}
    with _lock:
        _decoded[key] = found
        _decoded.move_to_end(key)
        while len(_decoded) > KEEP_DECODED:
            _decoded.popitem(last=False)
    return found


def _resample(image: np.ndarray, matrix: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return cv2.warpAffine(image, matrix, size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


def box_of(loops: Mapping[str, list], region_ids, layer_dpi: float | None) -> tuple[dict, float, tuple[int, int]]:
    """Where the zone's picture lies, mm (``x``, ``y``, ``width``, ``height``: its regions' bounds, a part of a pixel larger), its pixels a mm
    and its size in pixels (columns, rows)."""
    k = FILE_PX_PER_MM if not layer_dpi else min(FILE_PX_PER_MM, float(layer_dpi) / grayscale.MM_PER_INCH)
    x0, y0, x1, y1 = _bounds(loops, region_ids)
    cols, rows = max(1, math.ceil((x1 - x0) * k - 1e-9)), max(1, math.ceil((y1 - y0) * k - 1e-9))
    return {"x": x0, "y": y0, "width": cols / k, "height": rows / k}, k, (cols, rows)


def cut(plan: Mapping, loops: Mapping[str, list], zone: Mapping, layer_dpi: float | None) -> dict:
    """:func:`_cut`, from memory when the same zone of the same picture and split was cut lately (do not change what it returns)."""
    known = json.dumps([rc.file_stamp(plan["image_path"]), rc.file_stamp(plan["document_path"]), plan.get("smoothing_mm", 0.0),
                        list(zone["regions"]), layer_dpi], sort_keys=True, default=str)
    with _lock:
        if known in _cuts:
            _cuts.move_to_end(known)
            return _cuts[known]
    found = _cut(plan, loops, zone, layer_dpi)
    with _lock:
        _cuts[known] = found
        while len(_cuts) > KEEP_CUTS:
            _cuts.popitem(last=False)
    return found


def _cut(plan: Mapping, loops: Mapping[str, list], zone: Mapping, layer_dpi: float | None) -> dict:
    """The zone's picture as a photo work's upload is (``prediction_store.decode_upload``): the work's picture over the zone's box, opaque
    inside the zone's regions (``loops``: region id -> closed loops in mm, smoothed as the file's paths) and transparent outside, at full size
    (``grey_full``, ``alpha_full``, ``bgr_full``: what the file is made from) and at preview size; with the box in mm (``box``, :func:`box_of`)
    and the full size's pixels a mm."""
    source = _source(plan)
    rows, cols = source["grey"].shape
    size = plan["size_mm"]
    sx, sy = size["width"] / cols, size["height"] / rows                       # mm per pixel of the picture
    box, k, (out_cols, out_rows) = box_of(loops, zone["regions"], layer_dpi)
    x0, y0 = box["x"], box["y"]
    # a pixel (j, i) of the zone's picture has its centre at x0 + (j + 0.5) / k mm, which is u = x / sx - 0.5 in the picture's pixels
    matrix = np.array([[1 / (k * sx), 0, (x0 + 0.5 / k) / sx - 0.5], [0, 1 / (k * sy), (y0 + 0.5 / k) / sy - 0.5]])
    bgr, grey = source["bgr"], source["grey"]
    if 1 / (k * sx) > 1.5:                                                     # finer than the layer takes: average it down first
        step = int(1 / (k * sx))
        bgr = cv2.resize(bgr, (max(1, cols // step), max(1, rows // step)), interpolation=cv2.INTER_AREA)
        grey = cv2.resize(grey, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_AREA)
        matrix = np.array([[matrix[0, 0] * bgr.shape[1] / cols, 0, (matrix[0, 2] + 0.5) * bgr.shape[1] / cols - 0.5],
                           [0, matrix[1, 1] * bgr.shape[0] / rows, (matrix[1, 2] + 0.5) * bgr.shape[0] / rows - 0.5]])
    bgr_full = _resample(bgr, matrix, (out_cols, out_rows))
    grey_full = np.clip(_resample(grey, matrix, (out_cols, out_rows)), 0.0, 1.0)
    mask = np.zeros((out_rows, out_cols), np.uint8)
    for rid in zone["regions"]:              # outer boundary and holes in one call: a hole stays as it is (another region of the zone fills it)
        polygons = [_fixed(loop, k, (x0, y0)) for loop in loops.get(rid, []) if len(loop) >= 3]
        if polygons:
            cv2.fillPoly(mask, polygons, 1, shift=4)
    alpha_full = mask.astype(np.float32)
    scale = min(1.0, PREVIEW_PX / max(out_rows, out_cols))
    small = (max(1, round(out_cols * scale)), max(1, round(out_rows * scale)))
    fit = (lambda a: a) if scale >= 1 else (lambda a: cv2.resize(a, small, interpolation=cv2.INTER_AREA))
    preview_bgr = fit(bgr_full)
    lab = color.srgb8_to_lab(preview_bgr[..., ::-1].reshape(-1, 3).astype(np.float64)).reshape(preview_bgr.shape[:2] + (3,))
    return {"box": box, "px_per_mm": k,
            "grey_full": grey_full, "alpha_full": alpha_full, "bgr_full": np.ascontiguousarray(bgr_full),
            "picture": np.ascontiguousarray(fit(grey_full)), "alpha": np.ascontiguousarray(np.clip(fit(alpha_full), 0.0, 1.0)), "lab": lab,
            "size": [out_cols, out_rows]}


def _reduced(found: Mapping, px: int) -> dict:
    """The preview of a cut with its longer side at most ``px``."""
    rows, cols = found["picture"].shape
    scale = min(1.0, px / max(rows, cols))
    if scale >= 1:
        return dict(found)
    size = (max(1, round(cols * scale)), max(1, round(rows * scale)))
    shrink = lambda a: cv2.resize(a, size, interpolation=cv2.INTER_AREA)        # noqa: E731
    return {**found, "picture": shrink(found["picture"]), "alpha": shrink(found["alpha"]), "lab": shrink(found["lab"].astype(np.float32)).astype(np.float64)}


def curve(store: Store, plan: Mapping, zone: Mapping, width_mm: float) -> tuple[prediction.Curve, dict]:
    """The zone's scale at its width (DEC-107); PredictionError when it is not measured (any more)."""
    return ps.curve_for(store, mode_of(plan, zone), width_mm)


def measured_dots(store: Store, plan: Mapping, zone: Mapping, kind: str, power: float, width_mm: float) -> prediction.Curve | None:
    """The tones of a dot kind at ``power`` on the zone's settings (or at the recipe its dots were picked on the colour map from) as
    photographs of that kind measured them, or None until it was."""
    if kind not in ps.photographed_kinds(store):
        return None
    try:
        return ps.curve_for(store, st.kind_mode(mode_of(plan, zone), {**zone, "kind": kind, "dot_power": power}), width_mm)[0]
    except PredictionError:
        return None


def _rgba(rgb8: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    return np.dstack([rgb8, np.where(np.asarray(alpha) >= photo_modes.ALPHA_MIN, 255, 0).astype(np.uint8)])


def look(store: Store, plan: Mapping, zone: Mapping, found: Mapping, scale_curve: prediction.Curve, *, kind: str | None = None,
         px: int | None = None) -> tuple[np.ndarray, dict]:
    """The zone (:func:`full`) as it will come out on the titanium, RGBA uint8 (transparent outside it), at preview size or with the longer
    side ``px``, in its own kind or in ``kind``; with what is said about it. Grayscale on the scale at Min..Max with the greys the zone
    engraves (``photo_state.engraved``: chosen for the picture's colours with ``by_colour``, its parts' rules, its contours), hatched where no
    power was measured; a dot kind from its measured tones, else estimated from the dots' colour (the scale's or the recipe's picked on the
    colour map, ``prediction_store.dot_look``). Both in the zone's tone. The objects and the people model's scores the greys need are found
    once and kept with the cut ``found``."""
    kind = kind or zone["kind"]
    shown = _reduced(found, px) if px else found
    width = found["box"]["width"]
    mode = mode_of(plan, zone)
    if kind == GRAYSCALE:
        state = {**zone, "kind": GRAYSCALE}
        engraved = st.engraved(st.item(store, mode, shown, state, f"zone {zone['number']}", width), state)
        info, rgb8 = ps.predicted(engraved, *ps.check_power_range(zone["min_power"], zone["max_power"]))
        return _rgba(rgb8, shown["alpha"]), {"outside_share": info["outside_share"], "notes": info["notes"],
                                             "colour_match": engraved.get("colour_match"), "rules_report": engraved.get("rules_report"),
                                             "contours_report": engraved.get("contours_report")}
    power = ps.dot_power_at(store, mode, width, zone.get("dot_power"))
    measured = measured_dots(store, plan, zone, kind, power, width)
    state = {**zone, "kind": kind, "dot_power": power}
    rgb8, dots = st.dot_look(store, mode, st.toned(shown, state)["picture"], shown["alpha"], state, width, scale_curve, measured)
    return _rgba(rgb8, shown["alpha"]), {"dots": dots, "estimate": measured is None, "notes": [] if measured is None else dots["measured"]["notes"]}


def digest(curve_: prediction.Curve | None) -> str | None:
    return None if curve_ is None else rc.text_digest(json.dumps(curve_.as_dict(), sort_keys=True, default=str))


def key(plan: Mapping, zone: Mapping, scale_curve: prediction.Curve | None, measured: prediction.Curve | None, *, kind: str | None = None,
        px: int | None = None) -> str:
    """The key of a picture of the zone (:func:`full`): everything it is drawn from (the picture, the split and its smoothing, the zone's
    regions, scale and the settings of its kind, the tone it is drawn in, the scale's measured points and, for a dot kind, its measured
    tones). A dot kind does not draw from Min, Max and how the greys are chosen, nor grayscale from the dots' power and colour: changing one
    leaves the tiles of the other kinds as they are; the objects' colours count while the objects are coloured."""
    engraving = kind or zone["kind"]
    objects = zone["colour_choice"] == "objects"
    drawn_by = (("min_power", "max_power", "by_colour", "colour_choice", "contours", "rules", *(("colouring",) if objects else ()))
                if engraving == GRAYSCALE else ("dot_power", "dot_recipe"))
    return rc.key_of({"kind": "vector-photo-zone", "image": rc.file_stamp(plan["image_path"]), "document": rc.file_stamp(plan["document_path"]),
                      "smoothing_mm": plan.get("smoothing_mm", 0.0), "size": plan["size_mm"],
                      "zone": {k: zone[k] for k in ("regions", "scale", *drawn_by)}, "engraving": engraving, "px": px,
                      "tone": st.tone_used({**zone, "kind": engraving}), "sharpness": zone.get("sharpness", 0.0),
                      "curve": digest(scale_curve), "dots_curve": digest(measured)})


def side_by_side(grey: np.ndarray, rgb8: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """The zone's picture (left) beside its look (right, ``prediction.side_by_side``), RGBA uint8: both transparent outside the zone."""
    both = prediction.side_by_side(grey, rgb8)
    opaque = np.where(np.asarray(alpha) >= photo_modes.ALPHA_MIN, 255, 0).astype(np.uint8)
    return np.dstack([both, np.hstack([opaque, np.zeros((opaque.shape[0], prediction.GAP), np.uint8), opaque])])


def to_png(rgba: np.ndarray) -> bytes:
    return cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))[1].tobytes()


# -- the file and the time ----------------------------------------------------------------------------------------------------------
def layer_name(index: int, zone: Mapping, parameters: Mapping) -> str:
    power = (f"P{float(parameters['min_power']):g}-{float(parameters['power']):g}" if zone["kind"] == GRAYSCALE
             else f"P{float(parameters['power']):g}")
    return f"C{index:02d} Photo {zone['number']} {zone['kind']} {power}"


def parameters(store: Store, plan: Mapping, zone: Mapping, width_mm: float) -> dict:
    """The settings of the zone's Image layer: the scale's, with Min and Max (grayscale) or every dot at the dots' power (Min = Max), or at
    the settings and power of the recipe its dots were picked on the colour map from."""
    mode = mode_of(plan, zone)
    if zone["kind"] == GRAYSCALE:
        low, high = ps.check_power_range(zone["min_power"], zone["max_power"])
    elif zone.get("dot_recipe"):
        low = high = float(zone["dot_recipe"]["settings"]["power"])
    else:
        low = high = ps.dot_power_at(store, mode, width_mm, zone.get("dot_power"))
    return {**ps.file_parameters(fired(plan, zone), low, high), "layer_type": "Image", "dither": zone["kind"]}


def file_layer(store: Store, plan: Mapping, zone: Mapping, found: Mapping, index: int) -> dict:
    """The zone (:func:`full`) as a layer of the work's file (``plans.export_lbrn2``): an Image layer in the zone's kind with its scale's
    settings and its picture placed on its box, BGRA, transparent outside the zone (DEC-114). Grayscale engraves the greys the preview shows
    (``photo_state.item``: chosen for the picture's colours with ``by_colour``, its parts' rules, its contours); a dot kind the picture's own
    greys, and LightBurn makes the dots. Both in the zone's tone, at the DPI of the settings the layer fires at."""
    width = found["box"]["width"]
    p = parameters(store, plan, zone, width)
    item = st.item(store, mode_of(plan, zone), found, zone, f"zone {zone['number']}", width)
    pixels = ps.picture_for_file(item, p["min_power"], p["power"], width, None if dotted(zone) else zone["rules"], transparent=True,
                                 fired=fired(plan, zone))
    return {"index": index, "name": layer_name(index, zone, p), "cut_type": "Image", "parameters": p, "prediction": None, "regions": [],
            "layer_keys": [], "zone": zone["number"],
            "picture": {**found["box"], "pixels": pixels, "dither": zone["kind"], "file": f"photo-zone-{zone['number']}.png"}}


def time_layer(plan: Mapping, zone: Mapping, document: Mapping, loops: Mapping[str, list], index: int, p: Mapping) -> dict:
    """The zone for ``engraving_time.estimate``: its area scanned at its settings, its scan lines broken where the zone's outline is
    (``engraving_time.scan_pieces`` over its regions)."""
    shapes = [SimpleNamespace(kind="path", closed=True, polygon=region[0], holes=region[1:]) for rid in zone["regions"]
              for region in [loops.get(rid) or []] if region]
    return {"index": index, "name": layer_name(index, zone, p), "parameters": dict(p), "area_mm2": area_of(document, zone["regions"]),
            "scan_pieces": engraving_time.scan_pieces(shapes, float(p["line_interval"])) if p.get("line_interval") else None}
