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

from . import profiles as pf
from .db import Store, now

MODE_PLATE = "Calibration plate"
MODE_DISCRETE = "Discrete color engraving"
MODE_TONAL = "Tonal photo engraving"
MODE_COLOR_PATH = "Color-path photo engraving"
MODE_RESTORED = "Restored from file"
MARKER_LAYER_INDEX = 0
MAX_LAYERS = 255  # LightBurn layer indices 0..255; index 0 is the marker layer here
ARUCO_IDS = (0, 1, 2, 3)
DEFAULT_MARKER = {"aruco_mm": 8.0, "qr_module_mm": 0.5, "margin_mm": 3.0}


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
    qx, qy = 0.0, height + margin + a + margin
    return {
        "identifier": identifier, "aruco": markers,
        "qr": {"x": qx, "y": qy, "size": qr_size, "module": qm, "modules": int(qr.shape[0]), "rects": _runs(qr, qm, qx, qy)},
        "extent": {"min_x": -margin - a, "min_y": -margin - a, "max_x": width + margin + a, "max_y": qy + qr_size},
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
def build_grid(profile: dict, powers: list[float], frequencies: list[float], speed: float,
               cell_w: float, cell_h: float, gap: float) -> dict:
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
    if cols * rows + 1 > MAX_LAYERS + 1:
        raise pf.ValidationError(f"{cols * rows} cells need more LightBurn layers than the {MAX_LAYERS} available")
    cells = []
    for r, f in enumerate(frequencies):          # power by columns, frequency by rows (prototype BP-04)
        for c, p in enumerate(powers):
            cells.append({"id": f"r{r + 1}c{c + 1}", "row": r, "column": c,
                          "parameters": pf.parameter_vector(profile, p, f, speed),
                          "geometry": {"x": c * (cell_w + gap), "y": r * (cell_h + gap), "width": cell_w, "height": cell_h}})
    return {"cells": cells, "geometry": {"cell_width": cell_w, "cell_height": cell_h, "gap": gap, "columns": cols, "rows": rows,
                                         "width": cols * cell_w + (cols - 1) * gap, "height": rows * cell_h + (rows - 1) * gap}}


def preview_series(profile: dict, powers_text: str, frequencies_text: str, speeds_text: str,
                   cell_w: float, cell_h: float, gap: float) -> list[dict]:
    powers, freqs = parse_numbers(powers_text, "power"), parse_numbers(frequencies_text, "frequency")
    return [{"speed": s, **build_grid(profile, powers, freqs, s, cell_w, cell_h, gap)} for s in parse_numbers(speeds_text, "speed")]


def _plate_layers(grid: dict) -> list[dict]:
    layers = []
    for i, cell in enumerate(grid["cells"], start=1):
        layers.append({"index": i, "name": cell["id"], "parameters": cell["parameters"], "regions": [cell["geometry"]], "cell_id": cell["id"],
                       "prediction": None, "knowledge_id": None, "stage": None, "questioned": False})
    return layers


def create_plate_series(store: Store, profile_id: int, powers_text: str, frequencies_text: str, speeds_text: str,
                        cell_w: float, cell_h: float, gap: float, proposal_id: int | None = None) -> list[dict]:
    """One plate (and one EngravingPlan) per speed, in one transaction. Markers are mandatory (REQ-003)."""
    if marker_layer_settings(store) is None:
        raise pf.ValidationError("set the marker layer power, frequency and speed before creating plates (DEC-027)")
    profile = pf.get_profile(store, profile_id)
    series = preview_series(profile, powers_text, frequencies_text, speeds_text, cell_w, cell_h, gap)
    out = []
    with store.transaction():
        for item in series:
            ident = new_identifier()
            markers = marker_geometry(ident, item["geometry"]["width"], item["geometry"]["height"])
            plate_id = store.execute(
                "INSERT INTO plate(experiment_id,profile_id,speed,geometry_json,cells_json,proposal_id,created_at) VALUES (?,?,?,?,?,?,?)",
                (ident, profile_id, item["speed"], json.dumps(item["geometry"]), json.dumps(item["cells"]), proposal_id, now())).lastrowid
            plan_data = {"layers": _plate_layers(item), "markers": markers, "marker_layer": marker_layer_settings(store)}
            plan_id = store.execute(
                "INSERT INTO plan(name,mode,status,profile_id,plate_id,markers,plan_identifier,band_count,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"Plate {ident} (speed {item['speed']:g})", MODE_PLATE, "Ready to export", profile_id, plate_id, 1, ident, None,
                 json.dumps(plan_data), now())).lastrowid
            out.append({"plate_id": plate_id, "plan_id": plan_id, "experiment_id": ident, "speed": item["speed"],
                        "geometry": item["geometry"], "cells": len(item["cells"])})
    return out


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


def _cut_setting(index: int, name: str, power: float, frequency_khz: float, speed: float, pulse_width: float | None,
                 interval: float | None) -> str:
    extra = ""
    if pulse_width is not None:
        extra += f'        <QPulseWidth Value="{pulse_width:g}"/>\n'
    if interval is not None:
        extra += f'        <interval Value="{interval:g}"/>\n'
    return (f'    <CutSetting type="Scan">\n        <index Value="{index}"/>\n        <name Value={quoteattr(name)[0:]}/>\n'
            f'        <maxPower Value="{power:g}"/>\n        <maxPower2 Value="{power:g}"/>\n        <speed Value="{speed:g}"/>\n'
            f'        <frequency Value="{frequency_khz * 1000:g}"/>\n{extra}'
            f'        <priority Value="{index}"/>\n    </CutSetting>\n')


def export_lbrn2(plan: dict, x_offset: float = 0.0, y_offset: float = 0.0) -> bytes:
    """Write a plan as a LightBurn project: one layer per band/colour with its own power, frequency, speed.

    Refuses a plan whose layers lack parameters or, for predictions, any of the three estimates (REQ-002).
    """
    layers = plan["layers"]
    if not layers:
        raise pf.ValidationError("the plan has no layers to export")
    if len(layers) + 1 > MAX_LAYERS + 1:
        raise pf.ValidationError(f"{len(layers)} layers exceed the {MAX_LAYERS} LightBurn layers available")
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="2.0.04" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="False">\n']
    shapes = []
    for layer in layers:
        p = layer["parameters"]
        if any(k not in p or p[k] is None for k in ("power", "frequency", "speed")):
            raise pf.ValidationError(f"layer {layer['name']} lacks power, frequency or speed")
        pred = layer.get("prediction")
        if pred is not None and any(pred.get(k) is None for k in ("confidence", "expected_delta_e", "stability")):
            raise pf.ValidationError(f"layer {layer['name']} has an incomplete prediction (confidence, expected error and stability are required)")
        out.append(_cut_setting(layer["index"], layer["name"], p["power"], p["frequency"], p["speed"], p.get("pulse_width"), p.get("line_interval")))
        for r in layer["regions"]:
            shapes.append(_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], layer["index"]))
    markers = plan.get("markers")
    if markers and plan.get("markers_enabled", True):
        ml = plan.get("marker_layer")
        if not ml:
            raise pf.ValidationError("marker layer power, frequency and speed are not set (DEC-027)")
        out.append(_cut_setting(MARKER_LAYER_INDEX, "Markers", ml["power"], ml["frequency"], ml["speed"], None, None))
        for m in markers["aruco"]:
            shapes += [_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], MARKER_LAYER_INDEX) for r in m["rects"]]
        shapes += [_rect(r["x"] + x_offset, r["y"] + y_offset, r["width"], r["height"], MARKER_LAYER_INDEX) for r in markers["qr"]["rects"]]
    out += shapes
    out.append('    <Notes ShowOnLoad="0" Notes=""/>\n</LightBurnProject>\n')
    return "".join(out).encode("utf-8")
