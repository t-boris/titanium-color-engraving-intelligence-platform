"""Engraving time of a recipe, estimated from its LightBurn settings (REQ-035, DEC-075).

A filled layer scans its area line by line: one pass over a square centimetre marks for ``100 / (speed x interval)``
seconds, and every piece of scan line adds a turnaround allowance. A recipe alone does not say how long its pieces are, so
its time per square centimetre takes ``10 / interval`` pieces of 10 mm; a file does say, and its time counts the pieces of
its own shapes (``of_project``, DEC-101): small shapes cut the lines short, and a work scaled down in LightBurn loses area
faster than pieces. Passes, global repeats and cross-hatch (a second set of lines at 90 degrees) multiply it. An Image layer is scanned the same way. A Line-mode
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

TURNAROUND_S = 0.001
"""Seconds added for every piece of scan line: the galvo's laser-on and laser-off delays and the jump to the next piece with
its settling, each a few hundred µs on the controllers LightBurn drives. Timed against real jobs (DEC-101, replacing the
0.3 ms default of DEC-075): the work Inna + Boris took about 3 h at 150 mm and 1.5-2 h scaled to 100 mm in LightBurn; counted
piece by piece from their files, 1 ms gives 2.9-3.3 h and 1.5-1.6 h, while 0.3 ms left the 100 mm at 1.2-1.4 h."""

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


def _scan(settings: dict) -> dict | None:
    """What the time of a filled recipe is made of: the seconds one pass marks a square centimetre in one direction (with,
    scanning one way, the jump back along every line), the line interval, the repeats (passes x global repeats) and the
    directions (two with cross-hatch). None when the speed or the line interval is not recorded."""
    speed, interval = _positive(settings.get("speed")), _positive(settings.get("line_interval"))
    if speed is None or interval is None:
        return None
    one_way = 0.0 if _flag(settings, "bidirectional", True) else 1 / jump_speed(settings)
    return {"s_per_cm2": CM_MM * CM_MM / interval * (1 / speed + one_way), "interval": interval,
            "repeats": _count(settings, "passes") * _count(settings, "global_passes"),
            "directions": 2 if _flag(settings, "cross_hatch", False) else 1}


def per_area(settings: dict) -> dict:
    """Seconds per square centimetre of a filled (or image) recipe: ``100 / (speed x interval)`` per pass and, scanning one
    way, the return jumps; plus the turnaround allowance of ``10 / interval`` pieces of 10 mm; times passes, global repeats
    and two with cross-hatch. None, with the reason, when the speed or the line interval is not recorded."""
    scan = _scan(settings)
    if scan is None:
        return _result("area", None, _missing(_positive(settings.get("speed")), _positive(settings.get("line_interval"))))
    one_pass = scan["s_per_cm2"] + CM_MM / scan["interval"] * TURNAROUND_S
    return _result("area", one_pass * scan["repeats"] * scan["directions"], _limits(settings))


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
    fills (``area_mm2``) or, in Line mode, the length of its paths (``length_mm``). A filled layer may also give
    ``scan_pieces``, the pieces of scan line of one pass over its shapes in every direction it scans (``scan_pieces()``):
    the turnaround allowance is then counted on them instead of on 10 mm pieces. A layer whose time is not known is
    listed with the reason and the job's total is then incomplete (``complete`` false): it counts only the known layers."""
    rows, total, complete = [], 0.0, True
    for layer in layers:
        parameters = layer.get("parameters") or {}
        time = of_recipe(parameters)
        if time["kind"] == "area":
            rate, amount = time["s_per_cm2"], layer.get("area_mm2")
            amount = None if amount is None else float(amount) / (CM_MM * CM_MM)
        else:
            rate, amount = time["s_per_cm"], layer.get("length_mm")
            amount = None if amount is None else float(amount) / CM_MM
        seconds = None if rate is None or amount is None else rate * amount
        scan = _scan(parameters) if seconds is not None and time["kind"] == "area" and layer.get("scan_pieces") is not None else None
        if scan is not None:
            seconds = scan["repeats"] * (scan["directions"] * scan["s_per_cm2"] * amount + float(layer["scan_pieces"]) * TURNAROUND_S)
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


def _shoelace(points) -> float:
    if len(points) < 3:
        return 0.0
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2


def _region_area(region) -> float:
    """The area a fill or picture scans over one shape, mm²: a rectangle or picture its rectangle, a closed path its inside less its
    holes; an open path fills nothing."""
    if region.kind in ("rect", "bitmap") or region.closed:
        if len(region.polygon) >= 3:
            return max(0.0, _shoelace(list(region.polygon)) - sum(_shoelace(list(hole)) for hole in region.holes))
        return region.width * region.height if region.kind in ("rect", "bitmap") else 0.0
    return 0.0


def _region_length(region) -> float:
    """The path a Line-mode layer traces over one shape, mm: its outline (closed) or polyline, holes included."""
    def length(points, closed):
        pts = list(points) + (list(points[:1]) if closed else [])
        return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    return length(region.polygon, region.closed or region.kind in ("rect", "bitmap")) + sum(length(h, True) for h in region.holes)


def _filled(region) -> bool:
    return region.kind in ("rect", "bitmap") or region.closed


def scan_pieces(regions, interval: float, angle_deg: float = 0.0) -> float:
    """The pieces of scan line a fill at ``interval`` makes over closed shapes, its lines at ``angle_deg`` (LightBurn's scan angle,
    0 = along x). A line enters and leaves a shape at two edges, and an edge is crossed by one line per interval of its extent across
    the lines, so the pieces are the summed extent of every edge (holes included) over twice the interval: exact on average, with no
    line drawn. A picture's rectangle gives its rows."""
    a = math.radians(angle_deg)
    nx, ny = -math.sin(a), math.cos(a)
    extent = 0.0
    for region in regions:
        if not _filled(region):
            continue
        for loop in [list(region.polygon)] + [list(hole) for hole in region.holes]:
            extent += sum(abs((x2 - x1) * nx + (y2 - y1) * ny) for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]))
    return extent / (2 * interval)


def of_project(project) -> dict:
    """The estimated time of a whole LightBurn file (REQ-060: how long every work takes): each layer whose output is on, over the area
    of its shapes (a picture: its whole rectangle, scanned line by line) with the pieces of scan line its shapes make (``scan_pieces``,
    DEC-101), or, in Line mode, the length of its paths; with the layer's own speed, interval, passes, global repeats, direction and
    cross-hatch. Travel between separate shapes is not counted (``estimate``)."""
    layers = []
    for layer in project.layers:
        if layer.output_off or not layer.regions:
            continue
        settings = {"speed": layer.speed, "line_interval": layer.line_interval, "passes": layer.passes, "global_passes": layer.global_passes,
                    "bidirectional": layer.bidirectional, "cross_hatch": layer.cross_hatch, "layer_type": layer.layer_type,
                    "source_settings": layer.source_settings}
        row = {"index": layer.index, "name": layer.name, "parameters": settings}
        if is_line(settings):
            row["length_mm"] = sum(_region_length(r) for r in layer.regions)
        else:
            row["area_mm2"] = sum(_region_area(r) for r in layer.regions)
            if layer.line_interval:
                angle = layer.scan_angle or 0.0
                row["scan_pieces"] = scan_pieces(layer.regions, layer.line_interval, angle) + (
                    scan_pieces(layer.regions, layer.line_interval, angle + 90) if layer.cross_hatch else 0.0)
        layers.append(row)
    return estimate(layers)
