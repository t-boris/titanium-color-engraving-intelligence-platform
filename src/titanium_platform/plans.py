"""EngravingPlan contract, calibration-plate series and the LightBurn (.lbrn2) writer.

EngravingPlan (REQ-012, DEC-008) is band oriented. Every layer carries its full parameter vector and, when
it is a prediction, the three mandatory estimates (REQ-002)::

    {"id", "name", "mode", "device_id", "lens_id", "identifier", "markers": {enabled, geometry},
     "band_count", "layers": [{"index", "name", "parameters", "regions": [{x,y,width,height}],
                              "prediction": {lab, confidence, expected_delta_e, stability} | None,
                              "knowledge_id", "stage", "questioned"}]}

Markers (proposed DEC-027): four ArUco 4x4 corner markers (ids 0-3) and a QR code ``TCE1:<identifier>``,
both as filled rectangles on a dedicated marker layer that never produces observations.
"""
from __future__ import annotations

import base64
import itertools
import json
import re
import uuid
from xml.sax.saxutils import escape, quoteattr

import cv2
import numpy as np

from . import grayscale, lenses, lightburn as lb, setup as su, tasks, vectorize
from .db import Store, now

MODE_PLATE = "Calibration plate"
MODE_CAPABILITY = "Laser capability test"
MODE_DISCRETE = "Discrete color engraving"
MODE_TONAL = "Tonal photo engraving"
MODE_COLOR_PATH = "Color-path photo engraving"
MODE_RESTORED = "Restored from file"
MODE_VECTOR = "Vector job"
MODE_PHOTO_WORK = "Photo engraving work"      # a picture engraved in grayscale mode on a measured scale (photo_work)
ST_RESTORED = "Restored"          # a plan restored from an imported file records a job; it is never exported
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
# LightBurn tags a knowledge recipe keeps as numbers and controls (model.parameters_key reads those, not the tags) and tags
# that belong to the job, not to the recipe: where the layer sits, what it is called, when it runs (DEC-051), the picture
# settings of image objects that lightburn.parse_bytes files under the layer, and whether it is shown and engraved: a job's
# layers are (a recipe measured on a hidden layer must not hide the job's, whose tools then skip it, BUG-004).
RECIPE_NUMBER_TAGS = ("maxPower", "speed", "frequency", "QPulseWidth", "interval", "numPasses", "passes", "globalRepeat",
                      "bidir", "crossHatch", "angle", "anglePerPass")
JOB_TAGS = ("index", "name", "priority", "bitmaps", *lb.LAYER_SWITCH_TAGS)


def clean_layer(passport: dict) -> dict:
    """The established clean-first recipe (``CLEAN_PARAMETERS``, cross-hatch, one pass) on one laser.

    As on capability plates, a frequency the laser does not reach is brought to the nearest end of its range and the pulse
    width to the nearest step it offers; the layer name states the values that are actually written.
    """
    rate = passport["repetition_rate_khz"]
    frequency = min(max(CLEAN_PARAMETERS["frequency"], float(rate["min"])), float(rate["max"]))
    pulse = min((float(step["pulse_width_ns"]) for step in passport["pulse_steps"]),
                key=lambda v: (abs(v - CLEAN_PARAMETERS["pulse_width"]), v))
    p = {**CLEAN_PARAMETERS, "frequency": frequency, "pulse_width": pulse}
    name = f"CLEAN-CROSSHATCH-P{p['power']:g}-F{frequency:g}-V{p['speed']:g}-PW{pulse:g}-I{p['line_interval']:g}"
    return {**p, "passes": 1, "interval": p["line_interval"], "global_passes": 1, "bidirectional": True, "cross_hatch": True,
            "angle": 0.0, "angle_increment": 0.0, "name": name}


def scan_settings(values: dict | None = None) -> dict:
    """Validate LightBurn scan controls that are distinct from the six process axes.

    `passes` in the six-axis vector is the sublayer pass count (`numPasses`); global passes are
    LightBurn's separate `globalRepeat` setting and never silently multiply that value.
    """
    raw = {**SCAN_DEFAULTS, **(values or {})}
    global_passes = raw["global_passes"]
    if int(global_passes) != global_passes or not 1 <= int(global_passes) <= 100:
        raise su.ValidationError("global passes must be a whole number from 1 to 100")
    for key in ("bidirectional", "cross_hatch"):
        if not isinstance(raw[key], bool):
            raise su.ValidationError(f"{key} must be true or false")
    return {"global_passes": int(global_passes), "bidirectional": raw["bidirectional"],
            "cross_hatch": raw["cross_hatch"], "scan_angle": su._finite(raw["scan_angle"], "scan angle"),
            "angle_increment": su._finite(raw["angle_increment"], "angle increment")}


def parse_numbers(text: str, name: str) -> list[float]:
    """Numbers separated by spaces or semicolons; a decimal comma is accepted (prototype 2.3)."""
    parts = [p for p in re.split(r"[;\s]+", (text or "").strip()) if p]
    if not parts:
        raise su.ValidationError(f"{name}: enter at least one value")
    out: list[float] = []
    for p in parts:
        try:
            out.append(float(p.replace(",", ".")))
        except ValueError:
            raise su.ValidationError(f"{name}: '{p}' is not a number") from None
    if len(set(out)) != len(out):
        raise su.ValidationError(f"{name}: values must not repeat")
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
    """The operator's marker-layer settings (DEC-027): power, frequency and speed, and the pulse width, line interval and
    passes when the operator gave them (``interval`` is the line interval, as a layer of a plan names it). None until set."""
    return store.get_setting("marker_layer")


def save_marker_layer_settings(store: Store, power: float, frequency: float, speed: float, pulse_width: float | None = None,
                               line_interval: float | None = None, passes: int | None = None) -> dict:
    v = {"power": su._finite(power, "power", True), "frequency": su._finite(frequency, "frequency", True),
         "speed": su._finite(speed, "speed", True)}
    if pulse_width is not None:
        v["pulse_width"] = su._finite(pulse_width, "pulse width", True)
    if line_interval is not None:
        v["interval"] = su._finite(line_interval, "line interval", True)
    if passes is not None:
        if int(passes) != passes or passes < 1:
            raise su.ValidationError("passes must be a positive integer")
        v["passes"] = int(passes)
    store.set_setting("marker_layer", v)
    return v


def marker_layer_for(store: Store, passport: dict) -> dict:
    """The operator's marker-layer settings for a plate of this laser; refused when unset or not offered by the laser.

    Registration markers and engraved labels burn with these settings, never with a default of the system (DEC-027): how a
    mark burns into titanium is the operator's knowledge."""
    from . import devices
    settings = marker_layer_settings(store)
    if settings is None:
        raise su.ValidationError("set the marker layer power, frequency and speed before creating plates (DEC-027)")
    problems = su.check_in_range(passport, settings["power"], settings["frequency"])
    if problems:
        raise su.ValidationError("the saved marker layer settings are not offered by this laser: " + "; ".join(problems))
    if settings.get("pulse_width") is not None:
        devices.require_selectable(passport, settings["pulse_width"])
    return dict(settings)


# -- calibration plate series -------------------------------------------------------------------------------
OPERATING_POINT_KEYS = ("output_power_w", "pulse_energy_mj", "power_factor", "below_cutoff", "outside_controller_range", "areal_energy_j_cm2", "pulse_pitch_um")


def _add_operating_points(setup: dict, cells: list[dict]) -> None:
    """Passport-model figures per cell for the laser and lens of the plate (REQ-017, DEC-036).

    They are stored next to the parameter vector, never inside it: the vector that observations store is unchanged.
    """
    from . import devices
    for cell in cells:
        p = cell["parameters"]
        op = devices.operating_point(setup["device"]["passport"], p["power"], p["frequency"], p["speed"], p["pulse_width"], p["line_interval"], p["passes"], setup["lens"])
        cell["operating_point"] = {k: op[k] for k in OPERATING_POINT_KEYS} | {"basis": op["basis"]}


def work_field_check(setup: dict, need_w: float, need_h: float) -> dict:
    """Whether a plate of ``need_w`` x ``need_h`` mm, markers included, fits the work field of the laser and its lens
    (REQ-018, DEC-040). A known field that is too small refuses the plate. An unknown field is never a successful fit:
    the result says that the placement was not checked."""
    from . import characterization
    field, waiting = characterization.work_field(setup["device"]["passport"], setup["lens"])
    need = {"width": round(need_w, 2), "height": round(need_h, 2)}
    if field is None:
        return {"checked": False, "needed_mm": need, "field_mm": None, "source": None, "waiting_for": waiting,
                "note": "the work field of the lens is unknown: the placement was not checked"}
    if need_w > field["width"] or need_h > field["height"]:
        raise su.ValidationError(f"the plate with its markers is {need_w:.0f} x {need_h:.0f} mm, larger than the work field {field['width']:g} x {field['height']:g} mm of the laser")
    return {"checked": True, "needed_mm": need, "field_mm": {"width": field["width"], "height": field["height"]},
            "source": field["source"], "waiting_for": [], "note": None}


def check_work_field(setup: dict, width: float, height: float) -> dict:
    """The work-field check of a grid plate of ``width`` x ``height`` mm with the markers around it."""
    ext = marker_geometry("TCE-00000000", width, height)["extent"]       # same identifier length as a real plate, so the same QR size
    return work_field_check(setup, ext["max_x"] - ext["min_x"], ext["max_y"] - ext["min_y"])


def build_grid(setup: dict, powers: list[float], frequencies: list[float], speed: float,
               cell_w: float, cell_h: float, gap: float, pulse_width: float,
               line_interval: float, passes: int, lightburn_settings: dict | None = None) -> dict:
    """A power x frequency grid at one speed; the job settings are the plate's own and nothing is filled in (DEC-043)."""
    for label, v in (("cell width", cell_w), ("cell height", cell_h)):
        if su._finite(v, label, True) <= 0:
            raise su.ValidationError(f"{label} must be positive")
    if su._finite(gap, "gap") < 0:
        raise su.ValidationError("gap must not be negative")
    speed = su._finite(speed, "speed", True)
    problems = []
    for p, f in itertools.product(powers, frequencies):
        problems += su.check_in_range(setup["device"]["passport"], p, f)
    if problems:
        raise su.ValidationError("; ".join(dict.fromkeys(problems)))
    cols, rows = len(powers), len(frequencies)
    placement = check_work_field(setup, cols * cell_w + (cols - 1) * gap, rows * cell_h + (rows - 1) * gap)
    # A system-generated plate reserves C00 for cleaning and C01 for registration markers.
    if cols * rows + 2 > MAX_LAYERS:
        raise su.ValidationError(f"{cols * rows} cells need more than the {MAX_LAYERS - 2} test layers available after cleaning and markers")
    cells = []
    for r, f in enumerate(frequencies):          # power by columns, frequency by rows (prototype BP-04)
        for c, p in enumerate(powers):
            cells.append({"id": f"r{r + 1}c{c + 1}", "row": r, "column": c,
                          "parameters": su.parameter_vector(setup["device"]["passport"], p, f, speed, pulse_width, line_interval, passes),
                          "geometry": {"x": c * (cell_w + gap), "y": r * (cell_h + gap), "width": cell_w, "height": cell_h}})
    _add_operating_points(setup, cells)
    return {"cells": cells, "geometry": {"cell_width": cell_w, "cell_height": cell_h, "gap": gap, "columns": cols, "rows": rows,
                                         "width": cols * cell_w + (cols - 1) * gap, "height": rows * cell_h + (rows - 1) * gap},
            "lightburn_settings": scan_settings(lightburn_settings), "work_field": placement}


def preview_series(setup: dict, powers_text: str, frequencies_text: str, speeds_text: str,
                   cell_w: float, cell_h: float, gap: float, pulse_width: float,
                   line_interval: float, passes: int,
                   lightburn_settings: dict | None = None) -> list[dict]:
    powers, freqs = parse_numbers(powers_text, "power"), parse_numbers(frequencies_text, "frequency")
    return [{"speed": s, **build_grid(setup, powers, freqs, s, cell_w, cell_h, gap, pulse_width, line_interval, passes, lightburn_settings)}
            for s in parse_numbers(speeds_text, "speed")]


def _plate_layers(grid: dict) -> list[dict]:
    layers = []
    for i, cell in enumerate(grid["cells"], start=1):
        layers.append({"index": i, "name": cell["id"], "parameters": cell.get("recipe") or cell["parameters"], "regions": [cell["geometry"]],
                       "cell_id": cell["id"],
                       "lightburn_settings": grid.get("lightburn_settings", scan_settings()),
                       "prediction": None, "knowledge_id": None, "stage": None, "questioned": False,
                       "operating_point": cell.get("operating_point")})
    return layers


def create_plates(store: Store, device_id: int, series: list[dict], cell_w: float, cell_h: float, gap: float,
                  proposal_id: int | None = None) -> list[dict]:
    """One plate (and one EngravingPlan) per item of ``series`` = [{speed, powers, frequencies, pulse_width, line_interval,
    passes, proposed?, recipe?, data?}] on the laser with the lens installed on it now, atomically. ``recipe`` is a complete recipe its
    cells are engraved with (every setting of it is written, :func:`is_recipe`; its six numbers are the cell's), ``data`` more of the
    plan's own record (a transfer experiment's source, feature electron REQ-085).

    Markers are mandatory (REQ-003). ``proposed`` is an optional set of (power, frequency) pairs the Experiment
    Designer actually chose; the other cells of the Cartesian grid are marked as intersections, not
    recommendations (prototype BP-53).
    """
    if marker_layer_settings(store) is None:
        raise su.ValidationError("set the marker layer power, frequency and speed before creating plates (DEC-027)")
    setup = su.installed(store, device_id)
    marker_layer = marker_layer_for(store, setup["device"]["passport"])     # offered by this laser, its pulse width a step (REQ-017)
    lens = su.lens_snapshot(setup)
    lens_json = json.dumps(lens) if lens else None   # DEC-041: the lens is remembered by the plate
    grids = []
    for item in series:
        grid = build_grid(setup, item["powers"], item["frequencies"], item["speed"], cell_w, cell_h, gap,
                          item["pulse_width"], item["line_interval"], item["passes"], item.get("lightburn_settings"))
        chosen = item.get("proposed")  # None = every cell is wanted; else {(power, frequency): {"reason", "target_id"}}
        for cell in grid["cells"]:
            p = cell["parameters"]
            meta = None if chosen is None else chosen.get((p["power"], p["frequency"]))
            cell["proposed"] = chosen is None or meta is not None
            cell["reason"] = (meta or {}).get("reason")
            cell["target_id"] = (meta or {}).get("target_id")
            if item.get("recipe") is not None:
                cell["recipe"] = {**item["recipe"], **{k: p[k] for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")}}
        grids.append((item["speed"], grid, item.get("data") or {}))
    out = []
    with store.transaction():
        for speed, item, extra in grids:
            ident = new_identifier()
            markers = marker_geometry(ident, item["geometry"]["width"], item["geometry"]["height"])
            plate_id = store.execute(
                "INSERT INTO plate(experiment_id,device_id,lens_id,speed,geometry_json,cells_json,proposal_id,lens_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (ident, device_id, setup["lens_id"], speed, json.dumps(item["geometry"]), json.dumps(item["cells"]), proposal_id, lens_json, now())).lastrowid
            process = item["cells"][0]["parameters"]
            plan_data = {"layers": _plate_layers(item), "markers": markers, "marker_layer": marker_layer, "lens": lens,
                         "process_settings": {k: process[k] for k in ("pulse_width", "line_interval", "passes")},
                         "lightburn_settings": item["lightburn_settings"], "work_field": item["work_field"],
                         # its cells are filled areas measured for their colour; Fill mode says so by itself (REQ-020)
                         "engraving_task": tasks.plan_task("fill", basis=tasks.DERIVED), **extra}
            plan_id = store.execute(
                "INSERT INTO plan(name,mode,status,device_id,lens_id,plate_id,markers,plan_identifier,band_count,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"Plate {ident} (speed {speed:g})", MODE_PLATE, "Ready to export", device_id, setup["lens_id"], plate_id, 1, ident, None,
                 json.dumps(plan_data), now())).lastrowid
            out.append({"plate_id": plate_id, "plan_id": plan_id, "experiment_id": ident, "speed": speed,
                        "geometry": item["geometry"], "cells": len(item["cells"]),
                        "intersections": sum(1 for c in item["cells"] if not c["proposed"]),
                        "work_field": item["work_field"]})     # an unknown field says the placement was not checked (REQ-018)
    return out


def create_plate_series(store: Store, device_id: int, powers_text: str, frequencies_text: str, speeds_text: str,
                        cell_w: float, cell_h: float, gap: float, *, pulse_width: float, line_interval: float, passes: int,
                        proposal_id: int | None = None, lightburn_settings: dict | None = None) -> list[dict]:
    """One plate per speed over the same power x frequency grid and per-run process settings."""
    powers, freqs = parse_numbers(powers_text, "power"), parse_numbers(frequencies_text, "frequency")
    series = [{"speed": s, "powers": powers, "frequencies": freqs, "pulse_width": pulse_width,
               "line_interval": line_interval, "passes": passes, "lightburn_settings": scan_settings(lightburn_settings)}
              for s in parse_numbers(speeds_text, "speed")]
    return create_plates(store, device_id, series, cell_w, cell_h, gap, proposal_id)


def with_operating_points(store: Store, plan: dict) -> dict:
    """Fill in passport-model figures for layers that were stored without them (plans made before a device was linked).

    Computed at read time and never stored, so they follow the device's passport and the plan's lens (REQ-017, DEC-036).
    A layer whose settings are incomplete gets none: an unknown setting is never filled in (REQ-016).
    """
    setup = su.resolve(store, plan["device_id"], plan["lens_id"])
    from . import devices
    keys = ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")
    for layer in plan.get("layers", []):
        p = layer.get("parameters") or {}
        if layer.get("operating_point") is None and all(p.get(k) is not None for k in keys):
            try:
                op = devices.operating_point(setup["device"]["passport"], *(p[k] for k in keys), setup["lens"])
            except su.ValidationError:       # a setting the laser does not offer: no figures
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
def _plan_picture(plan: dict, key: str) -> np.ndarray:
    """A picture a plate keeps as a file of the workshop (``plan["pictures"]``, a photo-variations plate's copies): grey, or BGRA."""
    path = (plan.get("pictures") or {}).get(key)
    picture = cv2.imread(str(path), cv2.IMREAD_UNCHANGED) if path else None
    if picture is None:
        raise su.ValidationError(f"the picture of this plate ({key}) is missing from the workshop's files")
    return picture


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


IMAGE_DITHER = "grayscale"


def _clean_setting(cleaning: dict) -> str:
    """The cleaning layer C00 (``clean_layer``), run first: its recipe with its scan controls."""
    scan = scan_settings({"global_passes": cleaning.get("global_passes", 1), "bidirectional": cleaning.get("bidirectional", True),
                          "cross_hatch": cleaning.get("cross_hatch", True), "scan_angle": cleaning.get("angle", 0),
                          "angle_increment": cleaning.get("angle_increment", 0)})
    return _cut_setting(CLEAN_LAYER_INDEX, cleaning.get("name", CLEAN_LAYER_NAME), cleaning["power"], cleaning["frequency"],
                        cleaning["speed"], cleaning.get("pulse_width"), cleaning.get("interval", cleaning.get("line_interval")),
                        priority=0, cross_hatch=scan["cross_hatch"], angle=scan["scan_angle"], passes=cleaning.get("passes", 1),
                        global_passes=scan["global_passes"], bidirectional=scan["bidirectional"], angle_increment=scan["angle_increment"])


def _image_setting(index: int, name: str, p: dict, *, priority: int, dither: str = IMAGE_DITHER) -> str:
    """An Image layer as LightBurn writes one (the operator's own files of LightBurn 1.7.01 and 2.1.04, in their order): ``CutSetting_Img``
    with Min and Max power, speed, frequency (integer Hz), Q-pulse, the line interval, the image mode and the DPI LightBurn links
    to that interval. ``maxPower2`` repeats Max, as on every other layer this writer makes. With ``dot_width`` (mm, a dot kind's) LightBurn
    corrects the dot width of its dithering: ``dotWidth`` and ``useDotCorrection`` just before the interval, as those files carry them."""
    interval = float(p["line_interval"])
    dot_width = p.get("dot_width")
    tags = [("minPower", f"{float(p['min_power']):.10g}"), ("maxPower", f"{float(p['power']):.10g}"), ("maxPower2", f"{float(p['power']):.10g}"),
            ("speed", f"{float(p['speed']):.10g}"), ("frequency", str(round(float(p["frequency"]) * 1000))),
            ("QPulseWidth", None if p.get("pulse_width") is None else f"{float(p['pulse_width']):.10g}"),
            ("dotWidth", None if dot_width is None else f"{float(dot_width):.10g}"), ("useDotCorrection", None if dot_width is None else "1"),
            ("interval", f"{interval:.10g}"),
            ("numPasses", str(int(p.get("passes") or 1))), ("globalRepeat", str(int(p.get("global_passes") or 1))), ("priority", str(priority)),
            ("tabCount", "1"), ("tabCountMax", "1"), ("ditherMode", dither), ("dpi", str(grayscale.image_dpi(interval)))]
    body = "".join(f'        <{tag} Value="{value}"/>\n' for tag, value in tags if value is not None)
    return (f'    <CutSetting_Img type="Image">\n        <index Value="{index}"/>\n        <name Value={quoteattr(name)}/>\n'
            f'{body}    </CutSetting_Img>\n')


def _bitmap(x: float, y: float, w: float, h: float, picture: np.ndarray, dpi: float, layer: int, file_name: str, *,
            mirror_y: bool = False) -> str:
    """A picture object filling the rectangle (x, y, w, h) mm: the PNG at ``dpi`` with that DPI in its header, W and H the size it has at
    that DPI and the transform scaling it to the rectangle (1 when the picture was drawn for it), as the operator's files store it.
    ``picture`` is upright. LightBurn lays row 0 of a stored picture at the smallest y of its object (its y points up: the operator's
    Motorcycle file holds its picture upside down under a positive transform), so it is stored bottom row first; in a project with
    ``mirror_y`` (laid out top-down, MirrorY=True) the smallest y is shown at the top and it is stored as it is (DEC-114)."""
    rows, cols = picture.shape[:2]
    native_w, native_h = cols / dpi * grayscale.MM_PER_INCH, rows / dpi * grayscale.MM_PER_INCH
    stored = picture if mirror_y else picture[::-1]
    data = base64.b64encode(grayscale.png_with_dpi(np.ascontiguousarray(stored), dpi)).decode("ascii")
    return (f'    <Shape Type="Bitmap" CutIndex="{layer}" W="{native_w:.5f}" H="{native_h:.5f}" Gamma="1" Contrast="0" Brightness="0" '
            f'EnhanceAmount="0" EnhanceRadius="0" EnhanceDenoise="0" File={quoteattr(file_name)} SourceHash="0" Data="{data}">\n'
            f'        <XForm>{w / native_w:.8f} 0 0 {h / native_h:.8f} {x + w / 2:.5f} {y + h / 2:.5f}</XForm>\n    </Shape>\n')


def export_picture(picture: np.ndarray, width_mm: float, parameters: dict, name: str = "picture", identifier: str | None = None, *,
                   clean: dict | None, dither: str = IMAGE_DITHER, vectors: list[dict] = ()) -> bytes:
    """A LightBurn project of one picture engraved in the image mode ``dither`` (grayscale unless another kind is given: LightBurn makes
    the dots of a dot kind itself) with ``parameters`` (power = Max, ``min_power``, speed, frequency
    in kHz, pulse width, line interval, passes): the picture ``width_mm`` wide at the layer's DPI, its top-left corner at the origin,
    no mirroring and no markers. With ``clean`` (the laser's ``clean_layer``) the titanium under the picture is cleaned first, as on
    the plates its scale was measured on: C00 cleans the picture's rectangle and the Image layer C01 engraves the picture after it;
    without, the Image layer is C00, like the operator's own photo files. The picture keeps its own pixels, as in those files
    (LightBurn resamples it to the layer's DPI when it engraves); only a picture finer than that DPI is reduced to it, so the file does
    not carry pixels the laser never uses. With an ``identifier`` (a photo work's) the Notes carry ``TCE1:<identifier>``, as a plan's
    file does, so that the photograph of the engraving is linked to it. ``vectors`` are filled layers engraved after the picture (an
    inscription's letters, feature inscriptions-in-works): each its ``index`` (after the picture's), ``name``, recipe ``parameters`` and
    ``shapes`` (closed loops in the picture's mm, y down, outline then holes); the project's y points up, so they are written reflected
    over the picture's height, as the picture is stored bottom row first. A BGRA ``picture`` leaves its transparent pixels alone."""
    width = float(width_mm)
    if not np.isfinite(width) or width <= 0:
        raise su.ValidationError("the width of the picture must be a positive number of millimetres")
    for key in ("power", "min_power", "speed", "frequency", "line_interval"):
        if parameters.get(key) is None:
            raise su.ValidationError(f"the picture layer needs {key}")
    rows, cols = picture.shape[:2]
    height = width * rows / cols
    dpi = grayscale.image_dpi(parameters["line_interval"])
    own_dpi = cols / width * grayscale.MM_PER_INCH
    if own_dpi > dpi:
        target = (max(1, round(width / grayscale.MM_PER_INCH * dpi)), max(1, round(height / grayscale.MM_PER_INCH * dpi)))
        picture, own_dpi = cv2.resize(picture, target, interpolation=cv2.INTER_AREA), target[0] / width * grayscale.MM_PER_INCH
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "picture"
    index = 0 if clean is None else CLEAN_LAYER_INDEX + 1
    cleaning = "" if clean is None else _clean_setting(clean)
    frame = "" if clean is None else _rect(0.0, 0.0, width, height, CLEAN_LAYER_INDEX)
    settings, paths = [], []
    for layer in vectors:
        if not index < layer["index"] < MAX_LAYERS:
            raise su.ValidationError(f"the engraving would exceed LightBurn's {MAX_LAYERS} output layers (colors 00–29); T1/T2 are not output layers")
        settings.append(_recipe_setting(layer["index"], layer["name"], layer["parameters"]))
        regions = [{"loops": [[[x, height - y] for x, y in loop] for loop in shape], "strokes": [], "layer_key": "v"} for shape in layer["shapes"]]
        paths += vectorize.to_lbrn2_shapes({"regions": regions}, {"v": layer["index"]})
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="2.0.04" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="False">\n'
            + cleaning + _image_setting(index, f"C{index:02d}", parameters, priority=index, dither=dither) + "".join(settings) + frame
            + _bitmap(0.0, 0.0, width, height, picture, own_dpi, index, f"{stem}.png") + "".join(paths)
            + f'    <Notes ShowOnLoad="0" Notes={quoteattr(f"TCE1:{identifier}" if identifier else "")}/>\n</LightBurnProject>\n').encode("utf-8")


def is_recipe(parameters: dict) -> bool:
    """Parameters of a knowledge entry measured from a LightBurn file carry its mode and preserved settings; plate cells and
    legacy entries carry only the six numbers."""
    return parameters.get("layer_type") is not None or bool(parameters.get("source_settings"))


def _setting_xml(tag: str, value, indent: str) -> str:
    """One preserved setting as lightburn.parse_bytes stores it: a dict of attributes and nested settings (a sub-layer), a
    list of repeated elements in file order, or an element's text. Parsing the output gives the same data back."""
    if isinstance(value, list):
        return "".join(_setting_xml(tag, item, indent) for item in value)
    if not isinstance(value, dict):
        return f"{indent}<{tag}>{escape(str(value))}</{tag}>\n"
    attributes = "".join(f" {name}={quoteattr(str(v))}" for name, v in value.items() if not isinstance(v, (dict, list)))
    children = "".join(_setting_xml(name, v, indent + "    ") for name, v in value.items() if isinstance(v, (dict, list)))
    return f"{indent}<{tag}{attributes}>\n{children}{indent}</{tag}>\n" if children else f"{indent}<{tag}{attributes}/>\n"


def _recipe_setting(index: int, name: str, p: dict) -> str:
    """A layer written with its knowledge recipe in full (REQ-012): the LightBurn mode, the six numbers, the scan controls
    and every other setting the measured file had, sub-layers included. Only the colour index, the name, the run order
    (priority, DEC-051) and the Show and Output switches are the job's, so the layer read back is shown and engraved and has the
    recipe key of the entry it came from."""
    mode = p.get("layer_type") or "Scan"
    if mode == "Image":
        raise su.ValidationError(f"layer {name} uses a recipe measured on an image layer: LightBurn does not engrave vector shapes with it")
    fields = [("maxPower", f"{float(p['power']):.10g}"), ("speed", f"{float(p['speed']):.10g}"),
              ("frequency", str(round(float(p["frequency"]) * 1000))),
              ("QPulseWidth", None if p.get("pulse_width") is None else f"{float(p['pulse_width']):.10g}"),
              ("interval", None if p.get("line_interval") is None else f"{float(p['line_interval']):.10g}"),
              ("numPasses", None if p.get("passes") is None else str(int(p["passes"]))),
              ("globalRepeat", str(int(p.get("global_passes") or 1))),
              ("bidir", "0" if p.get("bidirectional") is False else "1"), ("crossHatch", "1" if p.get("cross_hatch") else "0"),
              ("angle", f"{float(p.get('scan_angle') or 0.0):g}"), ("anglePerPass", f"{float(p.get('angle_increment') or 0.0):g}")]
    body = "".join(f'        <{tag} Value="{value}"/>\n' for tag, value in fields if value is not None)
    body += "".join(_setting_xml(tag, value, "        ") for tag, value in (p.get("source_settings") or {}).items()
                    if tag not in RECIPE_NUMBER_TAGS and tag not in JOB_TAGS)
    return (f'    <CutSetting type={quoteattr(mode)}>\n        <index Value="{index}"/>\n        <name Value={quoteattr(name)}/>\n'
            f'{body}        <priority Value="{index}"/>\n    </CutSetting>\n')


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

    A layer that carries a knowledge recipe is written with every setting of that recipe (REQ-012); plate cells keep their
    own scan settings. A plate always cleans first on C00; another plan cleans first when it has a ``clean_layer``
    (DEC-056): the cleaning takes C00, the markers C01, and the plan's own layers keep the indices it gave them. A plan
    with a ``vector_document`` (REQ-021) gets its regions as Path shapes on the layer of their settings group.
    """
    x_offset, y_offset = export_offset(plan)
    is_plate = plan.get("mode") in (MODE_PLATE, MODE_CAPABILITY)
    layers = plan["layers"]
    if not layers:
        raise su.ValidationError("the plan has no layers to export")
    has_markers = bool(plan.get("markers") and plan.get("markers_enabled", True))
    has_clean = is_plate or plan.get("clean_layer") is not None
    marker_index = PLATE_MARKER_LAYER_INDEX if has_clean else MARKER_LAYER_INDEX
    file_indices = [layer["index"] + (int(has_markers) if is_plate else 0) for layer in layers]
    system_indices = ([CLEAN_LAYER_INDEX] if has_clean else []) + ([marker_index] if has_markers else [])
    actual_indices = system_indices + file_indices
    if len(layers) + len(system_indices) > MAX_LAYERS or any(i < 0 or i >= MAX_LAYERS for i in actual_indices):
        raise su.ValidationError(f"the engraving would exceed LightBurn's {MAX_LAYERS} output layers (colors 00–29); T1/T2 are not output layers")
    if len(set(actual_indices)) != len(actual_indices):
        raise su.ValidationError("the LightBurn layer indices overlap; every output operation needs its own color layer")
    # Generated capability plates use a top-down geometric layout. LightBurn's galvo canvas
    # otherwise displays their QR and vector glyphs upside down. Keep the flag on the plan so
    # historical files retain the exact orientation with which they were originally exported.
    mirror_y = "True" if plan.get("export_mirror_y", False) else "False"
    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="2.0.04" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="{mirror_y}">\n']
    shapes = []
    if has_clean:
        out.append(_clean_setting(plan.get("clean_layer") or {**CLEAN_PARAMETERS, "interval": CLEAN_PARAMETERS["line_interval"],
                                                              "global_passes": 1, "bidirectional": True, "cross_hatch": True,
                                                              "angle": 0, "angle_increment": 0}))
    for layer, file_index in zip(layers, file_indices):
        p = layer["parameters"]
        if any(k not in p or p[k] is None for k in ("power", "frequency", "speed")):
            raise su.ValidationError(f"layer {layer['name']} lacks power, frequency or speed")
        pred = layer.get("prediction")
        if pred is not None and any(pred.get(k) is None for k in ("confidence", "expected_delta_e", "stability")):
            raise su.ValidationError(f"layer {layer['name']} has an incomplete prediction (confidence, expected error and stability are required)")
        if layer.get("cut_type") == "Image":
            # a grey-ramp tile (REQ-059) or a photo zone of a vector work (REQ-073): the layer engraves its picture, placed on its rectangle
            placed = layer.get("ramp") or layer.get("picture")
            if p.get("min_power") is None or p.get("line_interval") is None or not placed:
                raise su.ValidationError(f"layer {layer['name']} is an image layer without Min power, line interval or its picture")
            out.append(_image_setting(file_index, layer["name"], p, priority=file_index, dither=placed.get("dither") or IMAGE_DITHER))
            dpi = grayscale.image_dpi(p["line_interval"])
            if layer.get("ramp"):
                pixels, own_dpi = grayscale.ramp_picture(placed, dpi), dpi
            else:                                    # the zone's own pixels, at its own DPI (no finer than the layer's)
                pixels = placed["pixels"] if placed.get("pixels") is not None else _plan_picture(plan, placed["picture_key"])
                own_dpi = pixels.shape[1] / placed["width"] * grayscale.MM_PER_INCH
            shapes.append(_bitmap(placed["x"] + x_offset, placed["y"] + y_offset, placed["width"], placed["height"], pixels, own_dpi,
                                  file_index, f"{layer['name']}.png" if layer.get("ramp") else placed["file"], mirror_y=mirror_y == "True"))
            continue
        if is_recipe(p):
            out.append(_recipe_setting(file_index, layer["name"], p))
        else:
            settings = scan_settings(layer.get("lightburn_settings") or plan.get("lightburn_settings"))
            layer_settings = layer.get("lightburn_settings") or plan.get("lightburn_settings") or {}
            cut_type = layer.get("cut_type", "Scan")
            out.append(_cut_setting(file_index, layer["name"], p["power"], p["frequency"], p["speed"], p.get("pulse_width"),
                                    None if cut_type == "Cut" else p.get("line_interval"),
                                    priority=file_index, passes=p.get("passes"),
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
    document = plan.get("vector_document")
    if document is not None:
        groups = {key: file_index for layer, file_index in zip(layers, file_indices) for key in layer.get("layer_keys", [])}
        shapes += vectorize.to_lbrn2_shapes(document, groups, offset=(x_offset, y_offset))
    markers = plan.get("markers")
    if has_markers:
        ml = plan.get("marker_layer")
        if not ml:
            raise su.ValidationError("marker layer power, frequency and speed are not set (DEC-027)")
        marker_settings = scan_settings({"global_passes": ml.get("global_passes", 1),
                                         "bidirectional": ml.get("bidirectional", True),
                                         "cross_hatch": ml.get("cross_hatch", False), "scan_angle": ml.get("angle", 0),
                                         "angle_increment": ml.get("angle_increment", 0)})
        out.append(_cut_setting(marker_index, ml.get("name", "Markers"), ml["power"], ml["frequency"], ml["speed"],
                                ml.get("pulse_width"), ml.get("interval"), passes=ml.get("passes"),
                                priority=marker_index,
                                global_passes=marker_settings["global_passes"], bidirectional=marker_settings["bidirectional"],
                                cross_hatch=marker_settings["cross_hatch"], angle=marker_settings["scan_angle"],
                                angle_increment=marker_settings["angle_increment"]))
        for m in markers["aruco"]:
            shapes += [_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], marker_index) for r in m["rects"]]
        shapes += [_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], marker_index) for r in markers["qr"]["rects"]]
        shapes += [_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], marker_index)
                   for r in plan.get("marker_labels", [])]
    if has_clean:
        if plan.get("clean_regions") is not None:
            cleaning_shapes = [_rect(r["x"] + x_offset, r["y"] + y_offset,
                                     r["width"], r["height"], CLEAN_LAYER_INDEX)
                               for r in plan["clean_regions"]]
            shapes[0:0] = cleaning_shapes
        elif has_markers:
            width = markers["extent"]["max_x"] - markers["extent"]["min_x"]
            height = markers["extent"]["max_y"] - markers["extent"]["min_y"]
            shapes.insert(0, _rect(0, 0, width, height, CLEAN_LAYER_INDEX))
        else:
            boxes = [(r["x"], r["y"], r["x"] + r["width"], r["y"] + r["height"]) for layer in layers for r in layer["regions"] if "width" in r]
            if not boxes and plan.get("size_mm"):            # a vector job: its work area
                boxes = [(0.0, 0.0, plan["size_mm"]["width"], plan["size_mm"]["height"])]
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
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
            f"{experiment.get('label') or 'Test'}: {experiment.get('test_name') or plan.get('name')}",
            f"Laser: {device.get('name') or ''} {device.get('model') or ''} · S/N {device.get('serial') or ''}".strip(" ·"),
            f"Lens: {lenses.label(lens)}" if lens.get("name") else "Lens: unknown",
            f"Titanium: {material.get('name') or ''}" + (f" · {stock}" if stock else "")]))
    else:
        notes_text = f"TCE1:{ident}" if ident else ""
    notes = quoteattr(notes_text)
    out.append(f'    <Notes ShowOnLoad="0" Notes={notes}/>\n</LightBurnProject>\n')
    return "".join(out).encode("utf-8")
