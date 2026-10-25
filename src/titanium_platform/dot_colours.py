"""The colour of a dot kind's dots picked on the colour map (0.25.0, DEC-118).

A dot kind's layer fires every dot at one set of settings (Min = Max), so any measured recipe of the work's laser, lens and titanium can
be its dots, not only a power of the work's grey scale. A point of the colour map (``colormap.collect``) is picked by its ``group``:

* a tone of a grey scale (a step of a grayscale image's tonal profile): the dots go onto that measured scale at that power, as the strip
  of the scale would put them (the owner changes its scale and its dots' power);
* a fill, one entry of the palette of the laser, lens and titanium (:func:`palette.vector_palette`, pooled over the plates of one grade,
  DEC-088): the dots fire at its settings, its power, speed, frequency, Q-pulse and passes, and its step is their pitch (the layer's DPI).

The dots are then a copy of the recipe kept by the owner (``dot_recipe``): its entry id, its settings and its colour at the owner's width
(``palette.at_size``, DEC-107), taken when it is picked and again when the width changes. The look, the close-up, the time and the file
read that copy, so opening a work does not gather the whole map; the settings never change (they are part of the entry's id). A later
measurement of the same recipe shows when it is picked again, and a photograph of the kind at those settings replaces the estimate.

Not every point can be the dots' colour (:data:`REASONS`): another titanium, a check not accepted yet, a line, a picture's own tone, a
cross-hatched fill (dots cannot cross), a tone of a dot engraving (dots mixed with titanium, not one dot) and a step finer than
:data:`STEP_MIN_MM`: there the dots overlap many times and the colour of the fill says little about them (operator, 2026-10-23).
"""
from __future__ import annotations

from typing import Mapping

import numpy as np

from . import color, colormap, palette, prediction, prediction_store as ps, setup as su
from .db import Store, now
from .prediction import PredictionError

STEP_MIN_MM = 0.0085            # the finest step a recipe may have to be the dots' colour: finer, the dots merge (the operator's choice)
SETTINGS = ("power", "speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes")
# why a point of the map cannot be the dots' colour
REASONS = {"titanium": "it was measured on another titanium than the work's",
           "provisional": "its check is not accepted yet",
           "line": "it is a line, not an area",
           "image": "it is a tone of a picture engraved in another way",
           "dots": "it is a tone of a dot engraving: dots mixed with titanium, not the colour of one dot",
           "mode": "its LightBurn mode fills no area",
           "task": "it was measured for text or a line",
           "cross_hatch": "it is cross-hatched: dots cannot cross",
           "step": "its step is finer than 0.0085 mm: there the dots merge",            # STEP_MIN_MM written out: a table of plain texts is translated
           "scale": "its grey scale is not measured on the work's titanium",
           "power": "its power lies outside the measured powers of its scale at the work's width"}


def _hex(lab) -> str:
    rgb = np.clip(color.lab_to_srgb8(np.asarray([lab], float)), 0, 255).round().astype(int)[0]
    return "#%02x%02x%02x" % tuple(rgb)


def _points(store: Store, mode: ps.Mode) -> list[dict]:
    """Every point of the colour map of the laser and lens of ``mode``."""
    return colormap.collect(store, setup=su.setup_key(mode.device_id, mode.lens_id))["points"]


def _tone(store: Store, mode: ps.Mode, width_mm: float, point: Mapping, scales: dict) -> dict:
    """What a grey scale's tone can give the dots: its measured scale on the work's titanium (``ps.measured_mode``, the scales of the
    laser, lens and titanium read once into ``scales``) and its power, or why not."""
    if point.get("image_mode") not in (None, prediction.PREDICTED_MODE):
        return {"reason": "dots"}
    params = point["parameters"]
    if (params.get("line_interval") or 0) < STEP_MIN_MM:
        return {"reason": "step"}
    if "modes" not in scales:
        scales["modes"] = ps.scale_modes(store, mode.device_id, mode.lens_id, mode.material_id)
    key = tuple(params.get(k) for k in ps.SETTINGS)
    if key not in scales:
        scale = next((m for m in scales["modes"] if m.matches(params)), None)
        try:
            scales[key] = None if scale is None else (scale, ps.curve_for(store, scale, width_mm)[0].span)
        except PredictionError:
            scales[key] = None
    if scales[key] is None:
        return {"reason": "scale"}
    scale, (lo, hi) = scales[key]
    power = float(params["power"])
    if not lo <= power <= hi:
        return {"reason": "power"}
    return {"scale": scale.as_dict(), "power": power}


def _fill(point: Mapping, ids: Mapping[str, str]) -> dict:
    """What a fill can give the dots: its palette entry, or why not."""
    reason = palette.left_out_reason(point)
    if reason is not None:
        return {"reason": {"other_mode": "mode"}.get(reason, reason)}
    params = point["parameters"]
    if params.get("cross_hatch"):
        return {"reason": "cross_hatch"}
    if (params.get("line_interval") or 0) < STEP_MIN_MM:
        return {"reason": "step"}
    return {"entry": ids[point["group"]]}


def _choices(store: Store, mode: ps.Mode, width_mm: float, points: list[dict], only: str | None = None) -> dict[str, dict]:
    """Each group of ``points`` (or the group ``only``) with what it can give the dots (:func:`_tone`, :func:`_fill`) or why not."""
    plates = set(su.same_titanium(store, mode.material_id))
    ids = palette.pooled_ids([p for p in points if p["material_id"] in plates], mode.material_id)
    scales: dict = {}
    out: dict[str, dict] = {}
    for point in points:
        group = point["group"]
        if group in out or (only is not None and group != only):
            continue
        if point["material_id"] not in plates:
            out[group] = {"reason": "titanium"}
        elif point["provisional"]:
            out[group] = {"reason": "provisional"}
        elif point.get("source") == "tonal":
            out[group] = _tone(store, mode, width_mm, point, scales)
        else:
            out[group] = _fill(point, ids)
    return out


def options(store: Store, mode: ps.Mode, width_mm: float, points: list[dict]) -> dict:
    """For the colour map picking the dots of a picture on ``mode`` (its scale: laser, lens and titanium) at ``width_mm``: each group of
    the map's ``points`` of that laser and lens (any filter on them) with what it gives the dots (``scale`` and ``power`` for a tone,
    ``fill`` for a recipe whose settings the dots take) or ``reason``, and the reasons' texts."""
    groups = _choices(store, mode, width_mm, points)
    return {"step_min_mm": STEP_MIN_MM, "setup": su.setup_key(mode.device_id, mode.lens_id), "reasons": REASONS,
            "groups": {g: {"fill": True} if "entry" in found else found for g, found in groups.items()}}


def picked(store: Store, mode: ps.Mode, width_mm: float, group) -> dict:
    """The change a picked point of the map (its ``group``) makes to the dots of a picture on ``mode`` at ``width_mm``: ``scale`` and
    ``dot_power`` for a tone of a grey scale, ``dot_recipe`` (:func:`recipe`) for a fill; a point that cannot be the dots is refused."""
    if not isinstance(group, str) or not group:
        raise su.ValidationError("pick a colour of the colour map for the dots")
    points = _points(store, mode)
    found = _choices(store, mode, width_mm, points, only=group).get(group)
    if found is None:
        raise su.ValidationError("this colour is not on the colour map of the work's laser and lens: pick it again")
    if "reason" in found:
        raise su.ValidationError(f"this colour cannot be the dots' colour: {REASONS[found['reason']]}")
    if "scale" in found:
        return {"scale": found["scale"], "dot_power": found["power"]}
    entries = palette.vector_palette(store, mode.device_id, mode.lens_id, mode.material_id, points=points)["entries"]
    entry = next((e for e in entries if e["id"] == found["entry"]), None)
    if entry is None:
        raise su.ValidationError("this colour is no longer measured: pick it again")
    return {"dot_recipe": recipe(entry, width_mm)}


def recipe(entry: Mapping, width_mm: float) -> dict:
    """The copy of a palette entry the owner keeps as its dots: the id, the settings, the colour at ``width_mm`` (``palette.at_size``) and
    what it rests on."""
    params = entry["parameters"]
    at = palette.at_size(entry, width_mm)
    settings = {k: params.get(k) for k in SETTINGS}
    settings["passes"] = settings["passes"] or 1
    settings["global_passes"] = settings["global_passes"] or 1
    return {"entry": entry["id"], "settings": settings, "lab": [round(float(v), 2) for v in at["lab"]], "size": at["size"],
            "engravings": entry["engravings"], "photographs": entry["photographs"], "basis": entry["basis"], "picked_at": now(), "missing": False}


def at_width(store: Store, mode: ps.Mode, kept: Mapping, width_mm: float) -> dict:
    """The kept dots ``kept`` at another width: the colour of their entry there; when the entry is no longer measured, the copy as it was,
    marked ``missing``. Dots of a photo engraving (``source`` "photo", ``photo_knowledge.recipe``) keep their colour: it was measured on
    a picture, not on rows of one length."""
    if kept.get("source") == "photo":
        return dict(kept)
    entries = palette.vector_palette(store, mode.device_id, mode.lens_id, mode.material_id)["entries"]
    entry = next((e for e in entries if e["id"] == kept["entry"]), None)
    return {**kept, "missing": True} if entry is None else {**recipe(entry, width_mm), "picked_at": kept["picked_at"]}


def fired_at(mode: ps.Mode, kept: Mapping | None) -> ps.Mode:
    """The settings the dots fire at: the picture's scale ``mode``, or with ``kept`` dots of a recipe its settings on the scale's laser,
    lens and titanium (a grayscale mode: the key of their curve and of the layer's settings)."""
    if not kept:
        return mode
    s = kept["settings"]
    return ps.Mode(mode.device_id, mode.lens_id, mode.material_id, s["speed"], s["frequency"], s["pulse_width"], s["line_interval"],
                   s["passes"], s["global_passes"])


def dots(store: Store, kept: Mapping) -> dict:
    """The dots of a recipe as ``prediction_store.dots_at`` gives those of a scale: their power and colour, the cleaned titanium between
    them, and where they come from (``map``: a fill of the colour map; ``photo``: a photographed photo engraving)."""
    clean = ps.clean_titanium(store)
    return {"power": float(kept["settings"]["power"]), "lab": list(kept["lab"]), "hex": _hex(kept["lab"]),
            "clean_lab": [round(float(v), 2) for v in clean], "clean_hex": _hex(clean), "source": kept.get("source") or "map",
            "recipe": dict(kept)}
