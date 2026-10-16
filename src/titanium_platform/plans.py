"""EngravingPlan contract, calibration-plate series and the LightBurn (.lbrn2) writer.

EngravingPlan (REQ-012, DEC-008) is band oriented. Every layer carries its full parameter vector and, when
it is a prediction, the three mandatory estimates (REQ-002)::

    {"id", "name", "mode", "profile_id", "identifier", "markers": {enabled, geometry},
     "band_count", "layers": [{"index", "name", "parameters", "regions": [{x,y,width,height}],
                              "prediction": {lab, confidence, expected_delta_e, stability} | None,
                              "knowledge_id", "stage", "questioned"}]}

Markers (proposed DEC-027): four ArUco 4x4 corner markers (ids 0-3) and a QR code ``TCE1:<identifier>``,
both as filled rectangles on a dedicated marker layer that never produces observations.
"""
from __future__ import annotations

import itertools
import json
import re
import uuid
from xml.sax.saxutils import quoteattr

import cv2
import numpy as np

from . import characterization, lenses, profiles as pf
from .db import Store, now

MODE_PLATE = "Calibration plate"
MODE_CAPABILITY = "Laser capability test"
MODE_DISCRETE = "Discrete color engraving"
MODE_TONAL = "Tonal photo engraving"
MODE_COLOR_PATH = "Color-path photo engraving"
MODE_RESTORED = "Restored from file"
MARKER_LAYER_INDEX = 0
# LightBurn exposes 30 output colors (00..29); T1/T2 are non-output tool layers. Treat this as
# a count, not a maximum index, and reserve system layers before building any generated plate.
MAX_LAYERS = 30
ARUCO_IDS = (0, 1, 2, 3)
DEFAULT_MARKER = {"aruco_mm": 8.0, "qr_module_mm": 0.5, "margin_mm": 3.0}
CLEAN_LAYER_INDEX = 0
PLATE_MARKER_LAYER_INDEX = 1
CLEAN_PARAMETERS = {"power": 20.0, "frequency": 48.0, "speed": 2000.0, "pulse_width": 200.0, "line_interval": 0.05}
CLEAN_LAYER_NAME = "CLEAN-CROSSHATCH-P20-F48-V2000-PW200-I0.05"
SCAN_DEFAULTS = {"global_passes": 1, "bidirectional": True, "cross_hatch": False,
                 "scan_angle": 0.0, "angle_increment": 0.0}


def scan_settings(values: dict | None = None) -> dict:
    """Validate LightBurn scan controls that are distinct from the six process axes.

    `passes` in the six-axis vector is the sublayer pass count (`numPasses`); global passes are
    LightBurn's separate `globalRepeat` setting and never silently multiply that value.
    """
    raw = {**SCAN_DEFAULTS, **(values or {})}
    global_passes = raw["global_passes"]
    if int(global_passes) != global_passes or not 1 <= int(global_passes) <= 100:
        raise pf.ValidationError("global passes must be a whole number from 1 to 100")
    for key in ("bidirectional", "cross_hatch"):
        if not isinstance(raw[key], bool):
            raise pf.ValidationError(f"{key} must be true or false")
    return {"global_passes": int(global_passes), "bidirectional": raw["bidirectional"],
            "cross_hatch": raw["cross_hatch"], "scan_angle": pf._finite(raw["scan_angle"], "scan angle"),
            "angle_increment": pf._finite(raw["angle_increment"], "angle increment")}


def parse_numbers(text: str, name: str) -> list[float]:
    """Numbers separated by spaces or semicolons; a decimal comma is accepted (prototype 2.3)."""
    parts = [p for p in re.split(r"[;\s]+", (text or "").strip()) if p]
    if not parts:
        raise pf.ValidationError(f"{name}: enter at least one value")
    out: list[float] = []
    for p in parts:
        try:
            out.append(float(p.replace(",", ".")))
        except ValueError:
            raise pf.ValidationError(f"{name}: '{p}' is not a number") from None
    if len(set(out)) != len(out):
        raise pf.ValidationError(f"{name}: values must not repeat")
    return out


def new_identifier(prefix: str = "TCE") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# -- marker geometry ---------------------------------------------------------------------------------
def _runs(bitmap: np.ndarray, module: float, ox: float, oy: float) -> list[dict]:
    """Filled rectangles for the 0-valued (dark) modules, merged along rows."""
    rects = []
    for r, row in enumerate(bitmap):
        c = 0
        while c < len(row):
            if row[c] == 0:
                start = c
                while c < len(row) and row[c] == 0:
                    c += 1
                rects.append({"x": ox + start * module, "y": oy + r * module, "width": (c - start) * module, "height": module})
            else:
                c += 1
    return rects


def marker_geometry(identifier: str, width: float, height: float, size: dict | None = None) -> dict:
    """Marker rectangles for an image/grid area of ``width`` x ``height`` mm whose top-left is (0, 0).

    Markers sit *outside* that area. Returns the bounding extent so callers can offset the artwork.
    """
    s = {**DEFAULT_MARKER, **(size or {})}
    aruco_d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    a, margin = s["aruco_mm"], s["margin_mm"]
    corners = {0: (-margin - a, -margin - a), 1: (width + margin, -margin - a),
               2: (width + margin, height + margin), 3: (-margin - a, height + margin)}
    markers = []
    for mid in ARUCO_IDS:
        bits = cv2.aruco.generateImageMarker(aruco_d, mid, 6, borderBits=1)
        x, y = corners[mid]
        markers.append({"id": mid, "x": x, "y": y, "size": a, "rects": _runs(bits, a / 6, x, y)})
    qr = cv2.QRCodeEncoder.create().encode(f"TCE1:{identifier}")
    qm = s["qr_module_mm"]
    qr_size = qr.shape[0] * qm
    if s.get("qr_position") == "top-right":
        qx, qy = width - qr_size, -margin - a
    else:
        qx, qy = 0.0, height + margin + a + margin
    return {
        "identifier": identifier, "aruco": markers,
        "qr": {"x": qx, "y": qy, "size": qr_size, "module": qm, "modules": int(qr.shape[0]), "rects": _runs(qr, qm, qx, qy)},
        "extent": {"min_x": min(-margin - a, qx), "min_y": min(-margin - a, qy),
                   "max_x": max(width + margin + a, qx + qr_size),
                   "max_y": max(height + margin + a, qy + qr_size)},
        "settings": s,
    }


def marker_layer_settings(store: Store) -> dict | None:
    return store.get_setting("marker_layer")


def save_marker_layer_settings(store: Store, power: float, frequency: float, speed: float) -> dict:
    v = {"power": pf._finite(power, "power", True), "frequency": pf._finite(frequency, "frequency", True),
         "speed": pf._finite(speed, "speed", True)}
    store.set_setting("marker_layer", v)
    return v


# -- calibration plate series -------------------------------------------------------------------------------
OPERATING_POINT_KEYS = ("output_power_w", "pulse_energy_mj", "power_factor", "below_cutoff", "outside_controller_range", "areal_energy_j_cm2", "pulse_pitch_um")


def _add_operating_points(profile: dict, cells: list[dict]) -> None:
    """Passport-model figures per cell when the profile has a laser device (REQ-017, DEC-036).

    They are stored next to the parameter vector, never inside it: the vector that observations store is unchanged.
    """
    device = profile.get("device")
    if device is None:
        return
    from . import devices
    for cell in cells:
        p = cell["parameters"]
        op = devices.operating_point(device["passport"], p["power"], p["frequency"], p["speed"], p["pulse_width"], p["line_interval"], p["passes"], device.get("lens"))
        cell["operating_point"] = {k: op[k] for k in OPERATING_POINT_KEYS} | {"basis": op["basis"]}


def check_work_field(profile: dict, width: float, height: float) -> None:
    """A plate with its markers must fit the work field of the laser, when the field is printed or confirmed (REQ-018, DEC-040)."""
    device = profile.get("device")
    if device is None:
        return
    from . import characterization
    field, _ = characterization.work_field(device["passport"], device.get("lens"))
    if field is None:
        return
    ext = marker_geometry("TCE-00000000", width, height)["extent"]       # same identifier length as a real plate, so the same QR size
    need_w, need_h = ext["max_x"] - ext["min_x"], ext["max_y"] - ext["min_y"]
    if need_w > field["width"] or need_h > field["height"]:
        raise pf.ValidationError(f"the plate with its markers is {need_w:.0f} x {need_h:.0f} mm, larger than the work field {field['width']:g} x {field['height']:g} mm of the laser")


def build_grid(profile: dict, powers: list[float], frequencies: list[float], speed: float,
               cell_w: float, cell_h: float, gap: float, pulse_width: float = 200.0,
               line_interval: float = 0.025, passes: int = 1, lightburn_settings: dict | None = None) -> dict:
    for label, v in (("cell width", cell_w), ("cell height", cell_h)):
        if pf._finite(v, label, True) <= 0:
            raise pf.ValidationError(f"{label} must be positive")
    if pf._finite(gap, "gap") < 0:
        raise pf.ValidationError("gap must not be negative")
    problems = []
    for p, f in itertools.product(powers, frequencies):
        problems += pf.check_in_range(profile, p, f, speed)
    if problems:
        raise pf.ValidationError("; ".join(dict.fromkeys(problems)))
    cols, rows = len(powers), len(frequencies)
    check_work_field(profile, cols * cell_w + (cols - 1) * gap, rows * cell_h + (rows - 1) * gap)
    # A system-generated plate reserves C00 for cleaning and C01 for registration markers.
    if cols * rows + 2 > MAX_LAYERS:
        raise pf.ValidationError(f"{cols * rows} cells need more than the {MAX_LAYERS - 2} test layers available after cleaning and markers")
    cells = []
    for r, f in enumerate(frequencies):          # power by columns, frequency by rows (prototype BP-04)
        for c, p in enumerate(powers):
            cells.append({"id": f"r{r + 1}c{c + 1}", "row": r, "column": c,
                          "parameters": pf.parameter_vector(profile, p, f, speed, pulse_width, line_interval, passes),
                          "geometry": {"x": c * (cell_w + gap), "y": r * (cell_h + gap), "width": cell_w, "height": cell_h}})
    _add_operating_points(profile, cells)
    return {"cells": cells, "geometry": {"cell_width": cell_w, "cell_height": cell_h, "gap": gap, "columns": cols, "rows": rows,
                                         "width": cols * cell_w + (cols - 1) * gap, "height": rows * cell_h + (rows - 1) * gap},
            "lightburn_settings": scan_settings(lightburn_settings)}


def preview_series(profile: dict, powers_text: str, frequencies_text: str, speeds_text: str,
                   cell_w: float, cell_h: float, gap: float, pulse_width: float = 200.0,
                   line_interval: float = 0.025, passes: int = 1,
                   lightburn_settings: dict | None = None) -> list[dict]:
    powers, freqs = parse_numbers(powers_text, "power"), parse_numbers(frequencies_text, "frequency")
    return [{"speed": s, **build_grid(profile, powers, freqs, s, cell_w, cell_h, gap, pulse_width, line_interval, passes, lightburn_settings)}
            for s in parse_numbers(speeds_text, "speed")]


def _plate_layers(grid: dict) -> list[dict]:
    layers = []
    for i, cell in enumerate(grid["cells"], start=1):
        layers.append({"index": i, "name": cell["id"], "parameters": cell["parameters"], "regions": [cell["geometry"]], "cell_id": cell["id"],
                       "lightburn_settings": grid.get("lightburn_settings", scan_settings()),
                       "prediction": None, "knowledge_id": None, "stage": None, "questioned": False,
                       "operating_point": cell.get("operating_point")})
    return layers


def create_plates(store: Store, profile_id: int, series: list[dict], cell_w: float, cell_h: float, gap: float,
                  proposal_id: int | None = None) -> list[dict]:
    """One plate (and one EngravingPlan) per item of ``series`` = [{speed, powers, frequencies, proposed?}], atomically.

    Markers are mandatory (REQ-003). ``proposed`` is an optional set of (power, frequency) pairs the Experiment
    Designer actually chose; the other cells of the Cartesian grid are marked as intersections, not
    recommendations (prototype BP-53).
    """
    if marker_layer_settings(store) is None:
        raise pf.ValidationError("set the marker layer power, frequency and speed before creating plates (DEC-027)")
    profile = pf.get_profile(store, profile_id)
    lens = lenses.snapshot((profile.get("device") or {}).get("lens"), characterization.characterize((profile["device"] or {}).get("passport"), profile["device"].get("lens"))["spot_diameter_um"] if profile.get("device") else None)
    lens_json = json.dumps(lens) if lens else None   # DEC-041: the lens is remembered by the plate
    grids = []
    for item in series:
        grid = build_grid(profile, item["powers"], item["frequencies"], item["speed"], cell_w, cell_h, gap,
                          item.get("pulse_width", 200.0), item.get("line_interval", 0.025), item.get("passes", 1),
                          item.get("lightburn_settings"))
        chosen = item.get("proposed")  # None = every cell is wanted; else {(power, frequency): {"reason", "target_id"}}
        for cell in grid["cells"]:
            p = cell["parameters"]
            meta = None if chosen is None else chosen.get((p["power"], p["frequency"]))
            cell["proposed"] = chosen is None or meta is not None
            cell["reason"] = (meta or {}).get("reason")
            cell["target_id"] = (meta or {}).get("target_id")
        grids.append((item["speed"], grid))
    out = []
    with store.transaction():
        for speed, item in grids:
            ident = new_identifier()
            markers = marker_geometry(ident, item["geometry"]["width"], item["geometry"]["height"])
            plate_id = store.execute(
                "INSERT INTO plate(experiment_id,profile_id,speed,geometry_json,cells_json,proposal_id,lens_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (ident, profile_id, speed, json.dumps(item["geometry"]), json.dumps(item["cells"]), proposal_id, lens_json, now())).lastrowid
            process = item["cells"][0]["parameters"]
            plan_data = {"layers": _plate_layers(item), "markers": markers, "marker_layer": marker_layer_settings(store), "lens": lens,
                         "process_settings": {k: process[k] for k in ("pulse_width", "line_interval", "passes")},
                         "lightburn_settings": item["lightburn_settings"]}
            plan_id = store.execute(
                "INSERT INTO plan(name,mode,status,profile_id,plate_id,markers,plan_identifier,band_count,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"Plate {ident} (speed {speed:g})", MODE_PLATE, "Ready to export", profile_id, plate_id, 1, ident, None,
                 json.dumps(plan_data), now())).lastrowid
            out.append({"plate_id": plate_id, "plan_id": plan_id, "experiment_id": ident, "speed": speed,
                        "geometry": item["geometry"], "cells": len(item["cells"]),
                        "intersections": sum(1 for c in item["cells"] if not c["proposed"])})
    return out


def create_plate_series(store: Store, profile_id: int, powers_text: str, frequencies_text: str, speeds_text: str,
                        cell_w: float, cell_h: float, gap: float, proposal_id: int | None = None,
                        pulse_width: float = 200.0, line_interval: float = 0.025, passes: int = 1,
                        lightburn_settings: dict | None = None) -> list[dict]:
    """One plate per speed over the same power x frequency grid and per-run process settings."""
    powers, freqs = parse_numbers(powers_text, "power"), parse_numbers(frequencies_text, "frequency")
    series = [{"speed": s, "powers": powers, "frequencies": freqs, "pulse_width": pulse_width,
               "line_interval": line_interval, "passes": passes, "lightburn_settings": scan_settings(lightburn_settings)}
              for s in parse_numbers(speeds_text, "speed")]
    return create_plates(store, profile_id, series, cell_w, cell_h, gap, proposal_id)


def with_operating_points(store: Store, plan: dict) -> dict:
    """Fill in passport-model figures for layers that were stored without them (plans made before a device was linked).

    Computed at read time and never stored, so they follow the device's passport (REQ-017, DEC-036).
    """
    device = pf.get_profile(store, plan["profile_id"]).get("device")
    if device is None:
        return plan
    from . import devices
    for layer in plan.get("layers", []):
        p = layer.get("parameters") or {}
        if layer.get("operating_point") is None and all(k in p for k in ("power", "frequency", "speed")):
            try:
                op = devices.operating_point(device["passport"], p["power"], p["frequency"], p["speed"], p["pulse_width"], p["line_interval"], p["passes"], device.get("lens"))
            except pf.ValidationError:
                continue
            layer["operating_point"] = {k: op[k] for k in OPERATING_POINT_KEYS} | {"basis": op["basis"]}
    return plan


def get_plan(store: Store, plan_id: int) -> dict:
    row = store.one("SELECT * FROM plan WHERE id=?", (plan_id,))
    if row is None:
        raise KeyError(f"plan {plan_id} not found")
    d = dict(row)
    # The integer column `markers` and the `markers` geometry inside data_json share a name: read the
    # column first so the geometry from the JSON is not lost.
    markers_enabled = bool(d.pop("markers"))
    d.update(json.loads(d.pop("data_json")))
    d["markers_enabled"] = markers_enabled
    return d


# -- LightBurn writer ----------------------------------------------------------------------------------------
def _rect(x: float, y: float, w: float, h: float, layer: int) -> str:
    cx, cy = x + w / 2, y + h / 2
    return (f'    <Shape Type="Rect" CutIndex="{layer}" W="{w:.5f}" H="{h:.5f}" Cr="0">\n'
            f'        <XForm>1 0 0 1 {cx:.5f} {cy:.5f}</XForm>\n    </Shape>\n')


def _line_path(x1: float, y1: float, x2: float, y2: float, layer: int) -> str:
    """A true LightBurn vector line, rather than a narrow filled rectangle."""
    return (f'    <Shape Type="Path" CutIndex="{layer}">\n'
            f'        <XForm>1 0 0 1 0 0</XForm>\n'
            f'        <VertList>V{x1:.5f} {y1:.5f}c0x1c1x1V{x2:.5f} {y2:.5f}c0x1c1x1</VertList>\n'
            f'        <PrimList>L0 1</PrimList>\n    </Shape>\n')


def _cut_setting(index: int, name: str, power: float, frequency_khz: float, speed: float, pulse_width: float | None,
                 interval: float | None, *, priority: int | None = None, cross_hatch: bool = False,
                 angle: float | None = None, passes: int | None = None, global_passes: int = 1,
                 bidirectional: bool = True, angle_increment: float = 0.0, cut_type: str = "Scan",
                 wobble_enabled: bool = False, wobble_step: float | None = None,
                 wobble_size: float | None = None) -> str:
    extra = ""
    if pulse_width is not None:
        extra += f'        <QPulseWidth Value="{pulse_width:.10g}"/>\n'
    if interval is not None:
        extra += f'        <interval Value="{interval:.10g}"/>\n'
    if passes is not None:
        extra += f'        <numPasses Value="{passes}"/>\n'
    extra += f'        <anglePerPass Value="{angle_increment:g}"/>\n'
    extra += f'        <bidir Value="{1 if bidirectional else 0}"/>\n'
    extra += f'        <crossHatch Value="{1 if cross_hatch else 0}"/>\n'
    if wobble_enabled or wobble_step is not None or wobble_size is not None:
        extra += f'        <wobbleEnable Value="{1 if wobble_enabled else 0}"/>\n'
        if wobble_step is not None:
            extra += f'        <wobbleStep Value="{wobble_step:g}"/>\n'
        if wobble_size is not None:
            extra += f'        <wobbleSize Value="{wobble_size:g}"/>\n'
    if angle is not None:
        extra += f'        <angle Value="{angle:g}"/>\n'
    priority = index if priority is None else priority
    return (f'    <CutSetting type="{cut_type}">\n        <index Value="{index}"/>\n        <name Value={quoteattr(name)[0:]}/>\n'
            f'        <maxPower Value="{power:.10g}"/>\n        <maxPower2 Value="{power:.10g}"/>\n        <speed Value="{speed:.10g}"/>\n'
            # LightBurn reads this as integer Hz; avoid exponent-form floats in generated XML.
            f'        <frequency Value="{round(frequency_khz * 1000)}"/>\n{extra}'
            f'        <priority Value="{priority}"/>\n        <globalRepeat Value="{global_passes}"/>\n'
            f'        <tabCount Value="1"/>\n        <tabCountMax Value="1"/>\n    </CutSetting>\n')


def export_offset(plan: dict) -> tuple[float, float]:
    """Shift that moves the markers (which lie at negative plan coordinates) into LightBurn's positive workspace."""
    markers = plan.get("markers")
    if markers and plan.get("markers_enabled", True):
        return -markers["extent"]["min_x"], -markers["extent"]["min_y"]
    return 0.0, 0.0


def export_lbrn2(plan: dict) -> bytes:
    """Write a plan as a LightBurn project: one layer per band/colour with its own power, frequency, speed.

    Refuses a plan whose layers lack parameters or, for predictions, any of the three estimates (REQ-002).
    Plan coordinates are shifted by :func:`export_offset`; the offset is the same for every shape.
    """
    x_offset, y_offset = export_offset(plan)
    is_plate = plan.get("mode") in (MODE_PLATE, MODE_CAPABILITY)
    layers = plan["layers"]
    if not layers:
        raise pf.ValidationError("the plan has no layers to export")
    has_markers = bool(plan.get("markers") and plan.get("markers_enabled", True))
    reserved = (1 + int(has_markers)) if is_plate else int(has_markers)
    file_indices = [layer["index"] + (int(has_markers) if is_plate else 0) for layer in layers]
    system_indices = ([CLEAN_LAYER_INDEX] if is_plate else []) + ([PLATE_MARKER_LAYER_INDEX if is_plate else MARKER_LAYER_INDEX] if has_markers else [])
    actual_indices = system_indices + file_indices
    if len(layers) + reserved > MAX_LAYERS or any(i < 0 or i >= MAX_LAYERS for i in actual_indices):
        raise pf.ValidationError(f"the engraving would exceed LightBurn's {MAX_LAYERS} output layers (colors 00–29); T1/T2 are not output layers")
    if len(set(actual_indices)) != len(actual_indices):
        raise pf.ValidationError("the LightBurn layer indices overlap; every output operation needs its own color layer")
    # Generated capability plates use a top-down geometric layout. LightBurn's galvo canvas
    # otherwise displays their QR and vector glyphs upside down. Keep the flag on the plan so
    # historical files retain the exact orientation with which they were originally exported.
    mirror_y = "True" if plan.get("export_mirror_y", False) else "False"
    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="2.0.04" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="{mirror_y}">\n']
    shapes = []
    if is_plate:
        cleaning = plan.get("clean_layer") or {**CLEAN_PARAMETERS, "interval": CLEAN_PARAMETERS["line_interval"],
                                                "global_passes": 1, "bidirectional": True, "cross_hatch": True,
                                                "angle": 0, "angle_increment": 0}
        cleaning_scan = scan_settings({"global_passes": cleaning.get("global_passes", 1),
                                       "bidirectional": cleaning.get("bidirectional", True),
                                       "cross_hatch": cleaning.get("cross_hatch", True), "scan_angle": cleaning.get("angle", 0),
                                       "angle_increment": cleaning.get("angle_increment", 0)})
        out.append(_cut_setting(CLEAN_LAYER_INDEX, cleaning.get("name", CLEAN_LAYER_NAME), cleaning["power"], cleaning["frequency"],
                                cleaning["speed"], cleaning.get("pulse_width"), cleaning.get("interval", cleaning.get("line_interval")),
                                priority=0, cross_hatch=cleaning_scan["cross_hatch"], angle=cleaning_scan["scan_angle"],
                                passes=cleaning.get("passes", 1), global_passes=cleaning_scan["global_passes"],
                                bidirectional=cleaning_scan["bidirectional"], angle_increment=cleaning_scan["angle_increment"]))
    for layer in layers:
        p = layer["parameters"]
        if any(k not in p or p[k] is None for k in ("power", "frequency", "speed")):
            raise pf.ValidationError(f"layer {layer['name']} lacks power, frequency or speed")
        pred = layer.get("prediction")
        if pred is not None and any(pred.get(k) is None for k in ("confidence", "expected_delta_e", "stability")):
            raise pf.ValidationError(f"layer {layer['name']} has an incomplete prediction (confidence, expected error and stability are required)")
        file_index = layer["index"] + (int(has_markers) if is_plate else 0)
        settings = scan_settings(layer.get("lightburn_settings") or plan.get("lightburn_settings"))
        layer_settings = layer.get("lightburn_settings") or plan.get("lightburn_settings") or {}
        cut_type = layer.get("cut_type", "Scan")
        out.append(_cut_setting(file_index, layer["name"], p["power"], p["frequency"], p["speed"], p.get("pulse_width"),
                                None if cut_type == "Cut" else p.get("line_interval"),
                                priority=file_index if is_plate else None, passes=p.get("passes"),
                                global_passes=settings["global_passes"], bidirectional=settings["bidirectional"],
                                cross_hatch=settings["cross_hatch"], angle=settings["scan_angle"],
                                angle_increment=settings["angle_increment"], cut_type=cut_type,
                                wobble_enabled=bool(layer_settings.get("wobble_enabled", False)),
                                wobble_step=layer_settings.get("wobble_step"),
                                wobble_size=layer_settings.get("wobble_size")))
        for r in layer["regions"]:
            if r.get("kind") == "line":
                shapes.append(_line_path(r["x1"] + x_offset, r["y1"] + y_offset,
                                         r["x2"] + x_offset, r["y2"] + y_offset, file_index))
            else:
                shapes.append(_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], file_index))
    markers = plan.get("markers")
    if markers and plan.get("markers_enabled", True):
        ml = plan.get("marker_layer")
        if not ml:
            raise pf.ValidationError("marker layer power, frequency and speed are not set (DEC-027)")
        marker_index = PLATE_MARKER_LAYER_INDEX if is_plate else MARKER_LAYER_INDEX
        marker_settings = scan_settings({"global_passes": ml.get("global_passes", 1),
                                         "bidirectional": ml.get("bidirectional", True),
                                         "cross_hatch": ml.get("cross_hatch", False), "scan_angle": ml.get("angle", 0),
                                         "angle_increment": ml.get("angle_increment", 0)})
        out.append(_cut_setting(marker_index, ml.get("name", "Markers"), ml["power"], ml["frequency"], ml["speed"],
                                ml.get("pulse_width"), ml.get("interval"), passes=ml.get("passes"),
                                priority=marker_index if is_plate else None,
                                global_passes=marker_settings["global_passes"], bidirectional=marker_settings["bidirectional"],
                                cross_hatch=marker_settings["cross_hatch"], angle=marker_settings["scan_angle"],
                                angle_increment=marker_settings["angle_increment"]))
        for m in markers["aruco"]:
            shapes += [_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], marker_index) for r in m["rects"]]
        shapes += [_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], marker_index) for r in markers["qr"]["rects"]]
        shapes += [_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], marker_index)
                   for r in plan.get("marker_labels", [])]
    if is_plate:
        if plan.get("clean_regions") is not None:
            cleaning_shapes = [_rect(r["x"] + x_offset, r["y"] + y_offset,
                                     r["width"], r["height"], CLEAN_LAYER_INDEX)
                               for r in plan["clean_regions"]]
            shapes[0:0] = cleaning_shapes
        elif markers and plan.get("markers_enabled", True):
            width = markers["extent"]["max_x"] - markers["extent"]["min_x"]
            height = markers["extent"]["max_y"] - markers["extent"]["min_y"]
            shapes.insert(0, _rect(0, 0, width, height, CLEAN_LAYER_INDEX))
        else:
            all_regions = [r for layer in layers for r in layer["regions"]]
            x0, y0 = min(r["x"] for r in all_regions), min(r["y"] for r in all_regions)
            x1 = max(r["x"] + r["width"] for r in all_regions)
            y1 = max(r["y"] + r["height"] for r in all_regions)
            shapes.insert(0, _rect(x0 + x_offset, y0 + y_offset, x1 - x0, y1 - y0, CLEAN_LAYER_INDEX))
    out += shapes
    ident = plan.get("plan_identifier") or (markers or {}).get("identifier") or ""
    experiment = plan.get("experiment") or {}
    if experiment:
        device = experiment.get("device") or {}
        lens = experiment.get("lens") or {}
        material = experiment.get("material") or {}
        stock = " · ".join(str(material.get(k)) for k in ("grade", "batch") if material.get(k))
        notes_text = "\n".join(filter(None, [f"TCE1:{ident}" if ident else None,
            f"Test: {experiment.get('test_name') or plan.get('name')}",
            f"Laser: {device.get('name') or ''} {device.get('model') or ''} · S/N {device.get('serial') or ''}".strip(" ·"),
            f"Lens: {lens.get('name') or ''} {lens.get('focal_length_mm') or ''} mm".strip(" ·"),
            f"Titanium: {material.get('name') or ''}" + (f" · {stock}" if stock else "")]))
    else:
        notes_text = f"TCE1:{ident}" if ident else ""
    notes = quoteattr(notes_text)
    out.append(f'    <Notes ShowOnLoad="0" Notes={notes}/>\n</LightBurnProject>\n')
    return "".join(out).encode("utf-8")
