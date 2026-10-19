"""Engraving time of a recipe, estimated from its LightBurn settings (REQ-035, DEC-075).

A filled layer scans its area line by line. A square centimetre is ``10 / interval`` lines of 10 mm, so one pass over it
takes ``100 / (speed x interval)`` seconds, plus a turnaround allowance at the end of every line. Passes, global repeats
and cross-hatch (a second set of lines at 90 degrees) multiply it. An Image layer is scanned the same way. A Line-mode
layer traces its paths once per pass: a centimetre takes ``10 / speed`` seconds, times passes and global repeats. Pulse
width and frequency set the energy of a pulse, not the time of a scan, and never enter (DEC-075).

With bi-directional fill off the laser fires in one direction only and, as LightBurn documents for its fill settings,
moves back to the start of each line without firing. On a galvo that move is a jump at the jump speed, so a one-way
recipe adds ``10 mm / jump speed`` per line. Not counted: travel between separate shapes (it depends on the drawing, not
on the recipe), the extra time of Flood Fill or of shapes filled one by one, and sub-layers (their settings are kept with
the recipe but how LightBurn runs them is not established here); a recipe with sub-layers says so.

The settings are read exactly as the stored observations carry them (``speed`` in mm/s, ``line_interval`` in mm,
``passes``, ``global_passes``, ``bidirectional``, ``cross_hatch``, ``layer_type`` and the file's own tags in
``source_settings``). A setting the file did not record takes LightBurn's default, as the reader does: one pass, one
global repeat, bi-directional on, cross-hatch off. Every value is an estimate and says so.
"""
from __future__ import annotations

import math
from typing import Iterable

from . import tasks

CM_MM = 10.0                  # millimetres in a centimetre

TURNAROUND_S = 0.0003
"""Seconds added at the end of every scan line: the galvo's laser-off delay, the short jump to the next line with its
settling and the laser-on delay, each of the order of 100 µs on the controllers LightBurn drives. An engineering default
until it is timed against a real job (DEC-075)."""

JUMP_SPEED_MM_S = 4000.0
"""The speed of a move without firing when the recipe does not set its own (``JumpSpeed`` of a layer that overrides the
galvo timings): the value every such override in the workshop's stored LightBurn files carries. An engineering default
until timed against a real job."""


def _value(raw):
    return raw.get("Value") if isinstance(raw, dict) else raw


def _positive(raw) -> float | None:
    try:
        number = float(_value(raw))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _count(settings: dict, key: str) -> int:
    """A pass or repeat count; LightBurn's default of one when the file did not record it."""
    number = _positive(settings.get(key))
    return 1 if number is None else max(1, round(number))


def _flag(settings: dict, key: str, default: bool) -> bool:
    value = settings.get(key)
    return default if value is None else bool(value)


def _source(settings: dict) -> dict:
    return settings.get("source_settings") or {}


def jump_speed(settings: dict) -> float:
    """The jump speed of a recipe in mm/s: its own when the layer sets one, else the default."""
    return _positive(_source(settings).get("JumpSpeed")) or JUMP_SPEED_MM_S


def is_line(settings: dict) -> bool:
    """A Line-mode recipe traces paths: its time is per centimetre of path, not per square centimetre (DEC-071)."""
    return tasks.derive(settings.get("layer_type"))["kind"] == "line"


def _result(kind: str, seconds: float | None, note: str | None) -> dict:
    return {"kind": kind, "s_per_cm2": seconds if kind == "area" else None, "s_per_cm": seconds if kind == "length" else None,
            "estimate": True, "note": note}


def _missing(speed: float | None, interval: float | None = 1.0) -> str | None:
    """Why a recipe has no time: a setting the time is made of is not recorded."""
    note = None
    if speed is None:
        note = "the speed of this recipe is not recorded: its engraving time is not known"
    elif interval is None:
        note = "the line interval of this recipe is not recorded: its engraving time is not known"
    return note


def _limits(settings: dict) -> str | None:
    """What a known time leaves out of the recipe's own settings."""
    note = None
    if _source(settings).get("SubLayer"):
        note = "the sub-layers of this recipe are not counted in its time"
    return note


def per_area(settings: dict) -> dict:
    """Seconds per square centimetre of a filled (or image) recipe: ``100 / (speed x interval)`` per pass, plus the
    turnaround allowance per line and, scanning one way, the return jump per line; times passes, global repeats and two
    with cross-hatch. None, with the reason, when the speed or the line interval is not recorded."""
    speed, interval = _positive(settings.get("speed")), _positive(settings.get("line_interval"))
    if speed is None or interval is None:
        return _result("area", None, _missing(speed, interval))
    lines = CM_MM / interval
    one_pass = lines * (CM_MM / speed + TURNAROUND_S)
    if not _flag(settings, "bidirectional", True):
        one_pass += lines * CM_MM / jump_speed(settings)
    factor = _count(settings, "passes") * _count(settings, "global_passes") * (2 if _flag(settings, "cross_hatch", False) else 1)
    return _result("area", one_pass * factor, _limits(settings))


def per_length(settings: dict) -> dict:
    """Seconds per centimetre of path of a Line-mode recipe: ``10 / speed`` times passes and global repeats. None, with
    the reason, when the speed is not recorded."""
    speed = _positive(settings.get("speed"))
    if speed is None:
        return _result("length", None, _missing(speed))
    return _result("length", CM_MM / speed * _count(settings, "passes") * _count(settings, "global_passes"), _limits(settings))


def of_recipe(settings: dict) -> dict:
    """The time of a recipe in the unit that fits its LightBurn mode: per centimetre of path for Line mode, else per
    square centimetre."""
    return per_length(settings) if is_line(settings) else per_area(settings)


def estimate(layers: Iterable[dict]) -> dict:
    """The estimated time of a whole job. Each layer gives its recipe ``parameters`` and how much it engraves: the area it
    fills (``area_mm2``) or, in Line mode, the length of its paths (``length_mm``). A layer whose time is not known is
    listed with the reason and the job's total is then incomplete (``complete`` false): it counts only the known layers."""
    rows, total, complete = [], 0.0, True
    for layer in layers:
        time = of_recipe(layer.get("parameters") or {})
        if time["kind"] == "area":
            rate, amount = time["s_per_cm2"], layer.get("area_mm2")
            amount = None if amount is None else float(amount) / (CM_MM * CM_MM)
        else:
            rate, amount = time["s_per_cm"], layer.get("length_mm")
            amount = None if amount is None else float(amount) / CM_MM
        seconds = None if rate is None or amount is None else rate * amount
        note = time["note"]
        if rate is not None and amount is None:
            note = "how much this layer engraves is not given"
        if seconds is None:
            complete = False
        else:
            total += seconds
        rows.append({"index": layer.get("index"), "name": layer.get("name"), "kind": time["kind"], "seconds": seconds,
                     "estimate": True, "note": note})
    return {"seconds": total, "complete": complete, "estimate": True, "layers": rows}
