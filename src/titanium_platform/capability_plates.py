"""Generate hardware-linked titanium test plates from a laser passport.

The operator chooses the physical laser, titanium stock and a plate type. The plate is made for the lens installed on
that laser now; the plate and its plan name the laser and that lens record (DEC-063) and remember the lens with its spot
value (REQ-019). The job settings are the plate's own.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from typing import Any

import cv2
import numpy as np

from . import devices, grayscale, photo_modes, photo_quality, plans, setup as su, tasks
from .db import Store, now

PLATE_TYPES = [
    {"id": "small_patches", "name": "Small patches · 1–4 samples",
     "purpose": "Quickly test one setting or compare up to four fill settings using minimal material.",
     "action": "One to four 3–5 mm squares, spaced 0.8 mm apart, each with its own layer and full settings. Optional QR and four registration marks support automatic photo alignment. The squares and marks are cleaned locally first.",
     "finds": "Response, uniformity, and differences between selected fill settings on this stock. Lettering, lines, and depth require separate samples."},
    {"id": "compact_capability", "name": "Compact capability test",
     "purpose": "In one small test, assess basic line and fill response, minimum line spacing, Wobble, and text at different sizes.",
     "action": "28 test layers: 16 power-speed combinations, four reference frequencies, ten line-gap groups on one layer, three Wobble levels, three fill intervals, and five text sizes on one layer. Cleaning and registration bring the file to exactly 30 LightBurn output layers.",
     "finds": "A compact overview of line visibility, frequency range, track merging, Wobble and Scan interval effects, and response at five text sizes. Character legibility is not established by this measurement. Frequency uses CW when available in the datasheet. This is preliminary screening; full frequency and Wobble grids use separate compact plates."},
    {"id": "calibration", "name": "Calibration matrix",
     "purpose": "Establish the response of this titanium stock and find ranges where the laser leaves a visible mark.",
     "action": "24 filled cells: four reference power levels by six frequencies around the selected frequency. Speed, Q-Pulse, and fill interval stay fixed; cleaning and markers use two additional layers.",
     "finds": "Mark onset, power and frequency effects, and under- or over-processing regions. This is a response matrix, not a map of finished colors."},
    {"id": "material_matrix", "name": "Two-parameter matrix (Material Test)",
     "purpose": "Compare a controlled grid of two selected laser parameters on one titanium stock.",
     "action": "Up to 28 cells; axes may vary power, speed, frequency, Q-Pulse, line interval, passes, or Wobble diameter (0 = off). Geometry can be lines, fills, filled letters, or repeated single-line vector letters A8M B012 at 2 and 4 mm. Wobble uses a fixed step. Cleaning, markers, and cells share one LightBurn file with at most 30 output layers.",
     "finds": "Effects of the selected parameter pair on identical geometry, including an OFF control for Wobble. Photos give preliminary response; assess legibility, edges, and depth on the workpiece."},
    {"id": "text_readability", "name": "Compact lettering test",
     "purpose": "Compare settings on letters and digits rather than extrapolating from a single line.",
     "action": "Nine groups: three powers by three speeds, each with three identical A8M samples at 1, 1.5, and 2 mm. Other settings are fixed; cleaning comes first. The plate is about 52 × 49 mm including markers.",
     "finds": "Response of small and large characters to power and speed. RAW contrast is preliminary; assess final legibility and edge quality in the photo and on the workpiece."},
    {"id": "power_speed", "name": "Power and speed limits",
     "purpose": "Find power-speed combinations at which a line becomes visible and remains continuous.",
     "action": "28 long single vector lines: four powers by seven speeds, with frequency and pulse width fixed. This is the largest grid that fits in 30 layers including cleaning and markers.",
     "finds": "A lower mark threshold and approximate galvo speed range at the selected line length, not a measurement of the datasheet maximum speed."},
    {"id": "frequency", "name": "Frequency range",
     "purpose": "Check the effect of pulse repetition at fixed power, speed, and pulse width.",
     "action": "A separate line for each test frequency in the laser range; use CW when available in the datasheet to cover frequencies above cutoff.",
     "finds": "Frequencies producing stable, weak, or changing marks and a practical check of the stated repetition range on titanium."},
    {"id": "pulse_cutoff", "name": "Pulse width and cutoff frequency",
     "purpose": "Compare pulse width and datasheet cutoff frequency with the actual mark.",
     "action": "Test up to nine evenly selected pulse steps at 0.8×, 1×, and 1.2× cutoff, plus a CW control when available. The subset keeps the file within 30 LightBurn layers including cleaning and markers.",
     "finds": "Where mark strength changes near cutoff and how closely the laser follows its frequency table."},
    {"id": "line_resolution", "name": "Track width and resolution",
     "purpose": "Estimate the minimum spacing at which adjacent marks remain distinguishable on this stock.",
     "action": "Ten groups of five parallel vector lines with gaps from 20 to 300 µm.",
     "finds": "Where lines begin to merge and their apparent track width. This test does not directly measure optical spot diameter."},
    {"id": "hatch_interval", "name": "Fill interval",
     "purpose": "Choose a suitable hatch interval for filled areas.",
     "action": "Five small Scan-fill squares at intervals of 0.01, 0.025, 0.05, 0.1, and 0.2 mm.",
     "finds": "Surface coverage, gaps or excessive overlap, and how the mark changes as hatch density increases."},
    {"id": "offset_fill", "name": "Offset Fill",
     "purpose": "Assess contour-following fill and compare it with ordinary fill.",
     "action": "Twelve Offset Fill squares: three speeds by four fill intervals, with power, frequency, and Q-Pulse fixed.",
     "finds": "How speed and contour density affect continuity and uniformity in offset-filled shapes."},
    {"id": "wobble", "name": "Wobble: step and circle size",
     "purpose": "See how Wobble changes mark width and strength on the selected titanium grade.",
     "action": "Nine small filled samples: three Step values by three Size values. LightBurn Wobble is enabled only on these layers.",
     "finds": "Effects of circle spacing and diameter on the visible mark. This is apparent engraving width, not optical spot diameter."},
    {"id": "grey_scales", "name": "Gray scales (photo engraving, grayscale mode)",
     "purpose": "Measure which titanium colors correspond to image grays at fixed settings and find settings that produce distinguishable steps as power changes.",
     "action": "Up to 28 strips of 16 gray steps, white to black, with power between Min and Max. Each is a separate LightBurn Image layer. Rows and columns vary two of speed, line interval (DPI), frequency, pulse width, passes, and strip width (a step is 1/16 of the width). Cleaning and markers use two more layers.",
     "finds": "A measured gray-to-color scale for each strip and power, used for photo previews and comparison with work in the same mode. The first step is pure white and shows whether Min fires on white."},
    {"id": "fill_sizes", "name": "Fill size",
     "purpose": "Measure how fill color changes with size: the same settings on strips of different widths and scan-line lengths.",
     "action": "Up to 28 filled 4 mm-high Scan strips at constant power, each with one of 1–7 recipes and one of 1–5 widths from 3 to 300 mm. Scan lines run along the width. Cleaning and markers use two more layers.",
     "finds": "Each recipe’s color at each width, how it shifts with scan-line length, and where it stabilizes. The strip center is measured; edges are excluded."},
    {"id": "photo_variations", "name": "Photo engraving: one image × several settings",
     "purpose": "Find photo engraving settings for a selected mode (Jarvis, Atkinson, Stucki, grayscale, and others), comparing darkness, lightness, sharpness, and softness on this titanium.",
     "action": "Up to 12 copies of the same image side by side, each with its own mode, power, speed, frequency, pulse width, line interval, and dot-width adjustment, plus a gray scale with the same settings. Each copy and scale use two LightBurn Image layers; cleaning and markers use two more. By default copies vary one parameter around the best known settings.",
     "finds": "For each copy: tone, distinguishable scale steps, shadow and highlight retention, detail, and grain. Changing one parameter shows its effect on tone and sharpness; the best settings become defaults for that mode."},
]
for item in PLATE_TYPES:
    item["description"] = f"Purpose: {item['purpose']} Plate: {item['action']} Result: {item['finds']}"
TYPE_BY_ID = {item["id"]: item for item in PLATE_TYPES}

# The user's established clean-first recipe. Values are adapted only when a selected laser passport
# does not support the exact frequency or pulse step.
CLEAN_DEFAULTS = {"power": 20.0, "frequency": 48.0, "speed": 2000.0, "pulse_width": 200.0,
                  "line_interval": 0.05, "passes": 1}
LABEL_DEFAULTS = {"power": 25.0, "frequency": 60.0, "speed": 150.0, "pulse_width": 200.0,
                  "line_interval": 0.01, "passes": 1}
DEFAULT_TEST = {"power": 20.0, "frequency": 48.0, "speed": 900.0,          # the pulse width is never filled in (DEC-043)
                "line_interval": 0.025, "passes": 1, "global_passes": 1}
SPEEDS_MM_S = (500, 1000, 1500, 2000, 3000, 5000, 7500, 10000)
FREQUENCIES_KHZ = (1, 5, 10, 20, 30, 40, 48, 60, 80, 100, 150, 200, 300, 500, 800, 1200, 1600, 1950, 2000, 3000, 4000)
CALIBRATION_POWERS = (5, 20, 50, 100)
CALIBRATION_FREQUENCY_FACTORS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
HATCH_INTERVALS_MM = (0.01, 0.025, 0.05, 0.1, 0.2)
OFFSET_FILL_INTERVALS_MM = (0.025, 0.05, 0.1, 0.2)
LINE_SPACINGS_UM = (20, 30, 40, 50, 60, 80, 100, 150, 200, 300)
COMPACT_POWERS = (5, 20, 50, 100)
COMPACT_SPEEDS = (500, 1500, 5000, 10000)
COMPACT_FREQUENCY_POINTS = 4
COMPACT_WOBBLE_POINTS = ((0.025, 0.05), (0.05, 0.1), (0.1, 0.2))
COMPACT_HATCH_INTERVALS_MM = (0.025, 0.05, 0.2)
COMPACT_TEXT_HEIGHTS_MM = (0.8, 1.1, 1.5, 2.0, 2.5)
WOBBLE_STEPS_MM = (0.025, 0.05, 0.1)
WOBBLE_SIZES_MM = (0.05, 0.1, 0.2)
COMPACT_MARKER_SIZE = {"aruco_mm": 4.0, "qr_module_mm": 0.25, "margin_mm": 0.5,
                       "qr_position": "top-right"}
PLATE_DEFAULT_MM, PLATE_MAX_MM = 100.0, 300.0     # the size limit of a plate unless the operator sets one, and the largest one allowed
RECIPE_KEYS = frozenset({"power", "frequency", "speed", "pulse_width", "line_interval", "passes", "global_passes"})
MATRIX_AXES = {
    "power": {"label": "Power", "short": "P", "unit": "%", "default_min": 5, "default_max": 100},
    "speed": {"label": "Speed", "short": "V", "unit": "mm/s", "default_min": 500, "default_max": 10000},
    "frequency": {"label": "Frequency", "short": "F", "unit": "kHz", "default_min": 24, "default_max": 96},
    "pulse_width": {"label": "Q-Pulse", "short": "PW", "unit": "ns", "default_min": 2, "default_max": 500},
    "line_interval": {"label": "Line interval", "short": "I", "unit": "mm", "default_min": 0.01, "default_max": 0.2},
    "passes": {"label": "Passes", "short": "N", "unit": "", "default_min": 1, "default_max": 5},
    "wobble_size": {"label": "Wobble diameter", "short": "W", "unit": "mm", "default_min": 0, "default_max": 0.08},
}

# Each glyph is a set of open, single-stroke polylines in a 2.5 × 5 unit box.
# Keeping them as paths (rather than filling pixel rectangles) lets LightBurn apply wobble to
# the same centreline at every matrix setting.
VECTOR_GLYPHS = {
    "A": (((0, 5), (1.25, 0), (2.5, 5)), ((0.5, 3), (2, 3))),
    "8": (((0.4, 0), (2.1, 0), (2.5, 0.6), (2.5, 1.8), (1.25, 2.5), (0, 1.8), (0, 0.6), (0.4, 0)),
          ((1.25, 2.5), (2.5, 3.2), (2.5, 4.4), (2.1, 5), (0.4, 5), (0, 4.4), (0, 3.2), (1.25, 2.5))),
    "M": (((0, 5), (0, 0), (1.25, 2.5), (2.5, 0), (2.5, 5)),),
    "B": (((0, 5), (0, 0), (1.8, 0), (2.5, 0.7), (2.5, 1.7), (1.8, 2.5), (0, 2.5)),
          ((1.8, 2.5), (2.5, 3.3), (2.5, 4.3), (1.8, 5), (0, 5))),
    "0": (((0.5, 0), (2, 0), (2.5, 0.7), (2.5, 4.3), (2, 5), (0.5, 5), (0, 4.3), (0, 0.7), (0.5, 0)),),
    "1": (((0.3, 1), (1.25, 0), (1.25, 5)), ((0.3, 5), (2.3, 5))),
    "2": (((0, 0.8), (0.6, 0), (1.9, 0), (2.5, 0.8), (2.5, 1.8), (0, 5), (2.5, 5)),),
}

FONT = {
    "A": "010/101/111/101/101", "B": "110/101/110/101/110", "C": "011/100/100/100/011",
    "D": "110/101/101/101/110", "E": "111/100/110/100/111", "F": "111/100/110/100/100",
    "G": "011/100/101/101/011", "H": "101/101/111/101/101", "I": "111/010/010/010/111",
    "J": "001/001/001/101/010", "K": "101/101/110/101/101", "L": "100/100/100/100/111",
    "M": "101/111/111/101/101", "N": "101/111/111/111/101", "O": "010/101/101/101/010",
    "P": "110/101/110/100/100", "Q": "010/101/101/111/011", "R": "110/101/110/101/101",
    "S": "011/100/010/001/110", "T": "111/010/010/010/010", "U": "101/101/101/101/111",
    "V": "101/101/101/101/010", "W": "101/111/111/111/101", "X": "101/101/010/101/101",
    "Y": "101/101/010/010/010", "Z": "111/001/010/100/111",
    "0": "111/101/101/101/111", "1": "010/110/010/010/111", "2": "110/001/010/100/111",
    "3": "110/001/010/001/110", "4": "101/101/111/001/001", "5": "111/100/110/001/110",
    "6": "011/100/110/101/010", "7": "111/001/010/010/010", "8": "010/101/010/101/010",
    "9": "010/101/011/001/110", "-": "000/000/111/000/000", ".": "000/000/000/000/010",
    "/": "001/001/010/100/100", "%": "101/001/010/100/101", "+": "000/010/111/010/000",
}


def _text(text: str, x: float, y: float, pixel: float = 0.22) -> list[dict]:
    pixel *= 1.45
    pitch = pixel * 1.35
    out = []
    for ci, ch in enumerate(text.upper()):
        glyph = FONT.get(ch)
        if not glyph:
            continue
        for ry, row in enumerate(glyph.split("/")):
            for rx, on in enumerate(row):
                if on == "1":
                    out.append({"kind": "rect", "x": x + ci * pitch + rx * pixel, "y": y + ry * pixel,
                                "width": pixel, "height": pixel})
    return out


def _line(x1: float, y1: float, x2: float, y2: float) -> dict:
    return {"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "x": min(x1, x2), "y": min(y1, y2), "width": abs(x2 - x1), "height": abs(y2 - y1)}


def _vector_text(text: str, x: float, y: float, height: float) -> list[dict]:
    """Draw genuinely open vector centrelines, scaled to an exact glyph height in mm."""
    unit = height / 5
    regions = []
    cursor = x
    for char in text.upper():
        if char == " ":
            cursor += 2.1 * unit
            continue
        for stroke in VECTOR_GLYPHS.get(char, ()):
            for start, end in zip(stroke, stroke[1:]):
                regions.append(_line(cursor + start[0] * unit, y + start[1] * unit,
                                     cursor + end[0] * unit, y + end[1] * unit))
        cursor += 3.1 * unit
    return regions


def _rect(x: float, y: float, width: float, height: float) -> dict:
    return {"kind": "rect", "x": x, "y": y, "width": width, "height": height}


def _nearest(steps: list[dict], preferred: float) -> float:
    values = [float(step["pulse_width_ns"]) for step in steps]
    return min(values, key=lambda v: (abs(v - preferred), v))


def _evenly_spaced(items: list[dict], limit: int) -> list[dict]:
    """Choose deterministic, endpoint-preserving passport samples for a layer-limited plate."""
    if len(items) <= limit:
        return items
    if limit <= 1:
        return [items[len(items) // 2]]
    indexes = [round(i * (len(items) - 1) / (limit - 1)) for i in range(limit)]
    return [items[i] for i in indexes]


def _clamp(value: float, bounds: dict) -> float:
    return min(max(float(value), float(bounds["min"])), float(bounds["max"]))


def _process(values: dict) -> dict:
    return {k: values[k] for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")}


def _layer(index: int, name: str, p: dict, regions: list[dict], *, mode: str = "Cut",
           cross_hatch: bool = False, bidirectional: bool = True, line_interval: float | None = None,
           global_passes: int = 1, wobble_enabled: bool = False, wobble_step: float = 0.05,
           wobble_size: float = 0.1) -> dict:
    params = dict(p)
    if line_interval is not None:
        params["line_interval"] = line_interval
    return {"index": index, "name": name, "parameters": params, "regions": regions,
            "cell_id": name, "cut_type": mode,
            "lightburn_settings": {"global_passes": global_passes, "bidirectional": bidirectional,
                                   "cross_hatch": cross_hatch, "scan_angle": 0.0, "angle_increment": 0.0,
                                   "wobble_enabled": wobble_enabled, "wobble_step": wobble_step,
                                   "wobble_size": wobble_size},
            "prediction": None, "knowledge_id": None, "stage": None, "questioned": False}


def _passport_defaults(passport: dict, supplied: dict) -> tuple[dict, dict, dict]:
    repetition = passport["repetition_rate_khz"]
    steps = passport["pulse_steps"]
    values = {**DEFAULT_TEST, **supplied}
    values["power"] = su._finite(values["power"], "power")
    if not 0 < values["power"] <= 100:
        raise su.ValidationError("power must be greater than 0 and at most 100%")
    values["frequency"] = su._finite(values["frequency"], "frequency", True)
    if not repetition["min"] <= values["frequency"] <= repetition["max"]:
        raise su.ValidationError(f"frequency must be in the range {repetition['min']:g}–{repetition['max']:g} kHz for the selected laser")
    values["speed"] = su._finite(values["speed"], "speed", True)
    if values["speed"] > 10000:
        raise su.ValidationError("test speed must not exceed 10000 mm/s")
    if values.get("pulse_width") in (None, ""):
        raise su.ValidationError("select a pulse width supported by the laser")
    values["pulse_width"] = su._finite(values["pulse_width"], "pulse width", True)
    devices.require_selectable(passport, values["pulse_width"])        # refused when outside the laser's range (DEC-089)
    values["line_interval"] = su._finite(values["line_interval"], "line interval", True)
    if values["line_interval"] > 1:
        raise su.ValidationError("line interval must not exceed 1 mm")
    for key in ("passes", "global_passes"):
        n = values[key]
        if isinstance(n, bool) or int(n) != n or not 1 <= n <= 20:
            raise su.ValidationError(f"{key}: enter a whole number from 1 to 20")
        values[key] = int(n)
    clean = dict(CLEAN_DEFAULTS)
    clean["frequency"] = _clamp(clean["frequency"], repetition)
    clean["pulse_width"] = _nearest(steps, clean["pulse_width"])
    label = dict(LABEL_DEFAULTS)
    label["frequency"] = _clamp(label["frequency"], repetition)
    label["pulse_width"] = _nearest(steps, label["pulse_width"])
    return values, clean, label


def _calibration(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    powers = CALIBRATION_POWERS
    rate = passport["repetition_rate_khz"]
    lo, hi = max(rate["min"], values["frequency"] * 0.5), min(rate["max"], values["frequency"] * 2)
    freqs = sorted({round(max(lo, min(hi, values["frequency"] * factor)), 2)
                    for factor in CALIBRATION_FREQUENCY_FACTORS})
    cell, gap, x0, y0 = 5.0, 0.6, 13.0, 12.0
    labels = _text("CALIBRATION POWER X FREQUENCY", 4, 2, 0.22)
    layers = []
    cells = []
    idx = 1
    for row, frequency in enumerate(freqs):
        labels += _text(f"F{frequency:g}", 2.0, y0 + row * (cell + gap) + 2.0, 0.12)
        for col, power in enumerate(powers):
            x, y = x0 + col * (cell + gap), y0 + row * (cell + gap)
            name = f"P{power}-F{frequency:g}"
            layers.append(_layer(idx, name, _process(values | {"power": power, "frequency": frequency}),
                                 [_rect(x, y, cell, cell)], mode="Scan", cross_hatch=False,
                                 bidirectional=True, line_interval=values["line_interval"], global_passes=values["global_passes"]))
            labels += _text(f"{power}", x + 1.3, y + 2.1, 0.13)
            cells.append({"name": name, "power": power, "frequency": frequency, "speed": values["speed"], "x": x, "y": y, "width": cell, "height": cell})
            idx += 1
    width = x0 + len(powers) * cell + (len(powers) - 1) * gap + 4
    height = y0 + len(freqs) * cell + (len(freqs) - 1) * gap + 3
    return layers, labels, {"width": width, "height": height, "columns": len(powers), "rows": len(freqs), "cells": cells}


def _power_speed(values: dict) -> tuple[list[dict], list[dict], dict]:
    powers = COMPACT_POWERS
    speeds = (500, 1000, 1500, 3000, 5000, 7500, 10000)
    x1, x2, y0, row_pitch, gap = 18.0, 72.0, 12.0, 0.55, 0.8
    labels = _text("POWER X SPEED LINE TEST", 4, 1, 0.24)
    layers, cells = [], []
    for pi, power in enumerate(powers):
        top = y0 + pi * (len(speeds) * row_pitch + gap)
        labels += _text(f"P{power}", 3.5, top + 1.3, 0.14)
        for si, speed in enumerate(speeds):
            y = top + si * row_pitch
            labels += _text(f"{speed}", 10.5, y - 0.18, 0.075)
            name = f"P{power}-V{speed}"
            layers.append(_layer(len(layers) + 1, name, _process(values | {"power": power, "speed": speed}),
                                 [_line(x1, y, x2, y)], mode="Cut", global_passes=values["global_passes"]))
            cells.append({"name": name, "power": power, "speed": speed, "frequency": values["frequency"], "y": y})
    return layers, labels, {"width": 76.0, "height": y0 + len(powers) * (len(speeds) * row_pitch + gap), "columns": len(speeds), "rows": len(powers), "cells": cells}


def _frequency(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    rate = passport["repetition_rate_khz"]
    freqs = [f for f in FREQUENCIES_KHZ if rate["min"] <= f <= rate["max"]]
    if values["frequency"] not in freqs:
        freqs.append(values["frequency"])
    freqs = sorted(set(freqs))
    x1, x2, y0, row_pitch = 15.0, 71.0, 11.0, 2.15
    labels = _text("FREQUENCY RANGE LINE RESPONSE", 4, 1, 0.21)
    layers, cells = [], []
    for row, frequency in enumerate(freqs):
        y = y0 + row * row_pitch
        labels += _text(f"F{frequency:g}", 4, y - 0.3, 0.1)
        name = f"F{frequency:g}KHZ"
        layers.append(_layer(len(layers) + 1, name, _process(values | {"frequency": frequency}),
                             [_line(x1, y, x2, y)], mode="Cut", global_passes=values["global_passes"]))
        cells.append({"name": name, "frequency": frequency, "power": values["power"], "speed": values["speed"], "y": y})
    return layers, labels, {"width": 76.0, "height": y0 + len(freqs) * row_pitch + 2, "columns": 1, "rows": len(freqs), "cells": cells}


def _pulse_cutoff(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    rate = passport["repetition_rate_khz"]
    steps = [s for s in passport["pulse_steps"] if s["cutoff_khz"] is not None]
    if not steps:
        raise su.ValidationError("the laser datasheet has no pulse cutoff frequency table")
    steps = _evenly_spaced(steps, 9)
    factors = (0.8, 1.0, 1.2)
    labels = _text("Q-PULSE / FREQUENCY CUTOFF", 4, 1, 0.24)
    layers, cells = [], []
    x_positions, x2, y0, pitch = (21.0, 39.0, 57.0), 68.0, 11.0, 2.6
    for row, step in enumerate(steps):
        pulse, cutoff = float(step["pulse_width_ns"]), float(step["cutoff_khz"])
        y = y0 + row * pitch
        labels += _text(f"PW{pulse:g}", 3, y + 0.4, 0.11)
        for col, factor in enumerate(factors):
            frequency = round(max(rate["min"], min(rate["max"], cutoff * factor)), 1)
            name = f"PW{pulse:g}-F{frequency:g}"
            labels += _text(f"{frequency:g}", x_positions[col] + 1, y - 0.35, 0.09)
            params = _process(values | {"frequency": frequency, "pulse_width": pulse})
            layers.append(_layer(len(layers) + 1, name, params, [_line(x_positions[col], y + 1, x2 + col * 0, y + 1)],
                                 mode="Cut", global_passes=values["global_passes"]))
            cells.append({"name": name, "pulse_width": pulse, "cutoff_khz": cutoff, "frequency": frequency, "factor": factor})
    # A CW step has no pulse-width cutoff and makes a useful reference line.
    cw = next((float(s["pulse_width_ns"]) for s in passport["pulse_steps"] if s["cutoff_khz"] is None), None)
    if cw is not None:
        y = y0 + len(steps) * pitch
        labels += _text(f"CW PW{cw:g}", 3, y + 0.4, 0.11)
        layers.append(_layer(len(layers) + 1, f"CW-PW{cw:g}-REFERENCE", _process(values | {"pulse_width": cw}),
                             [_line(21, y + 1, 31, y + 1)], mode="Cut", global_passes=values["global_passes"]))
        cells.append({"name": f"CW-PW{cw:g}-REFERENCE", "pulse_width": cw, "frequency": values["frequency"], "reference": True})
    return layers, labels, {"width": 76.0, "height": y0 + (len(steps) + int(cw is not None)) * pitch + 2,
                            "columns": 3, "rows": len(steps), "cells": cells}


def _line_resolution(values: dict) -> tuple[list[dict], list[dict], dict]:
    x1, x2, y0, group_pitch = 20.0, 47.0, 12.0, 3.8
    labels = _text("LINE SEPARATION / RESOLUTION", 4, 1, 0.22)
    layers, cells = [], []
    for row, spacing_um in enumerate(LINE_SPACINGS_UM):
        center_y = y0 + row * group_pitch
        spacing = spacing_um / 1000.0
        regions = [_line(x1, center_y + (i - 2) * spacing, x2, center_y + (i - 2) * spacing) for i in range(5)]
        labels += _text(f"{spacing_um}UM", 4, center_y - 0.35, 0.11)
        name = f"GAP-{spacing_um}UM"
        layers.append(_layer(len(layers) + 1, name, _process(values), regions, mode="Cut",
                             global_passes=values["global_passes"]))
        cells.append({"name": name, "spacing_um": spacing_um, "lines": 5})
    return layers, labels, {"width": 52.0, "height": y0 + len(LINE_SPACINGS_UM) * group_pitch, "columns": 1,
                           "rows": len(LINE_SPACINGS_UM), "cells": cells}


def _hatch_interval(values: dict) -> tuple[list[dict], list[dict], dict]:
    side, gap, x0, y0 = 8.0, 3.0, 5.0, 12.0
    labels = _text("HATCH INTERVAL TEST", 4, 1, 0.22)
    layers, cells = [], []
    for col, interval in enumerate(HATCH_INTERVALS_MM):
        x = x0 + col * (side + gap)
        name = f"HATCH-I{interval:g}"
        labels += _text(f"{interval:g}MM", x, y0 - 2, 0.10)
        layers.append(_layer(len(layers) + 1, name, _process(values | {"line_interval": interval}),
                             [_rect(x, y0, side, side)], mode="Scan", line_interval=interval,
                             bidirectional=True, global_passes=values["global_passes"]))
        cells.append({"name": name, "line_interval": interval, "x": x, "y": y0, "width": side, "height": side})
    return layers, labels, {"width": x0 + len(HATCH_INTERVALS_MM) * side + (len(HATCH_INTERVALS_MM) - 1) * gap + 4,
                            "height": y0 + side + 3, "columns": len(HATCH_INTERVALS_MM), "rows": 1, "cells": cells}


def _offset_fill(values: dict) -> tuple[list[dict], list[dict], dict]:
    """Compare LightBurn's contour-following fill mode across speed and line-interval axes."""
    speeds = sorted({round(min(10000.0, max(100.0, values["speed"] * factor)), 1) for factor in (0.5, 1.0, 2.0)})
    side, x0, y0, pitch_x, pitch_y = 6.0, 13.0, 14.0, 8.0, 8.0
    labels = _text("OFFSET FILL SPEED X INTERVAL", 3, 1, 0.22)
    layers, cells = [], []
    for col, interval in enumerate(OFFSET_FILL_INTERVALS_MM):
        x = x0 + col * pitch_x
        labels += _text(f"I{interval:g}", x + 0.6, y0 - 2.2, 0.10)
    for row, speed in enumerate(speeds):
        y = y0 + row * pitch_y
        labels += _text(f"V{speed:g}", 3, y + 2.0, 0.11)
        for col, interval in enumerate(OFFSET_FILL_INTERVALS_MM):
            x = x0 + col * pitch_x
            name = f"OFFSET-V{speed:g}-I{interval:g}"
            params = _process(values | {"speed": speed, "line_interval": interval})
            layers.append(_layer(len(layers) + 1, name, params, [_rect(x, y, side, side)], mode="OffsetFill",
                                 cross_hatch=False, bidirectional=False, line_interval=interval,
                                 global_passes=values["global_passes"]))
            cells.append({"name": name, "speed": speed, "line_interval": interval, "power": values["power"],
                          "x": x, "y": y, "width": side, "height": side})
    width = x0 + (len(OFFSET_FILL_INTERVALS_MM) - 1) * pitch_x + side + 3
    height = y0 + (len(speeds) - 1) * pitch_y + side + 3
    return layers, labels, {"width": width, "height": height, "columns": len(OFFSET_FILL_INTERVALS_MM),
                            "rows": len(speeds), "cells": cells}


def _compact_capability(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """Use no more than 28 test settings so clean + registration stay inside colors 00..29."""
    layers: list[dict] = []
    labels = _text("COMPACT LASER CAPABILITY", 2.0, 0.8, 0.14)
    cells: list[dict] = []
    index = 1

    # Sixteen short vector strokes span four powers and four speeds. Broader detailed sweeps have
    # their own plate types; this coupon preserves the full speed span without consuming 56 slots.
    x0, y0, x_pitch, y_pitch, line_length = 7.0, 5.0, 3.6, 1.8, 2.6
    for col, speed in enumerate(COMPACT_SPEEDS):
        labels += _text(f"{speed}", x0 + col * x_pitch - 0.1, 2.6, 0.065)
    for row, power in enumerate(COMPACT_POWERS):
        y = y0 + row * y_pitch
        labels += _text(f"P{power}", 1.2, y - 0.22, 0.07)
        for col, speed in enumerate(COMPACT_SPEEDS):
            x = x0 + col * x_pitch
            name = f"LINE-P{power}-V{speed}"
            params = _process(values | {"power": power, "speed": speed})
            layer = _layer(index, name, params, [_line(x, y, x + line_length, y)], mode="Cut", global_passes=values["global_passes"])
            layers.append(layer)
            cells.append({"name": name, "parameters": params, "x": x, "y": y - 0.02, "width": line_length, "height": 0.04})
            index += 1

    # Ten five-line groups share the same laser settings and therefore one LightBurn output layer.
    line_y0, line_group_pitch, line_x1, line_x2 = 19.5, 1.43, 7.0, 31.0
    gap_regions, gap_groups = [], []
    for row, spacing_um in enumerate(LINE_SPACINGS_UM):
        center = line_y0 + row * line_group_pitch
        spacing = spacing_um / 1000.0
        start = len(gap_regions)
        gap_regions.extend(_line(line_x1, center + (i - 2) * spacing, line_x2, center + (i - 2) * spacing) for i in range(5))
        name = f"LINE-GAP-{spacing_um}UM"
        labels += _text(f"{spacing_um}UM", 1.0, center - 0.22, 0.06)
        gap_groups.append({"name": name, "region_start": start, "region_count": 5, "spacing_um": spacing_um})
    gap_name = "LINE-GAP-20-300UM"
    gap_params = _process(values)
    gap_layer = _layer(index, gap_name, gap_params, gap_regions, mode="Cut", global_passes=values["global_passes"])
    gap_layer["measurement_groups"] = gap_groups
    layers.append(gap_layer)
    cells.append({"name": gap_name, "parameters": gap_params, "x": line_x1, "y": line_y0 - 0.16,
                  "width": line_x2 - line_x1, "height": (len(LINE_SPACINGS_UM) - 1) * line_group_pitch + 0.32,
                  "features": gap_groups})
    index += 1

    # A compact diagonal of small / medium / large Step and Size settings. The dedicated wobble plate
    # retains the full 3 x 3 factorial when a first pass shows that wobble needs investigation.
    wobble_x, wobble_y, wobble_side, wobble_pitch = 39.0, 5.0, 3.0, 4.6
    for col, (step, size) in enumerate(COMPACT_WOBBLE_POINTS):
        x, y = wobble_x + col * wobble_pitch, wobble_y + col * wobble_pitch
        name = f"WOBBLE-S{step:g}-D{size:g}"
        labels += _text(f"S{step:g}D{size:g}", x, y - 1.15, 0.075)
        params = _process(values)
        layers.append(_layer(index, name, params, [_rect(x, y, wobble_side, wobble_side)], mode="Scan",
                             line_interval=values["line_interval"], global_passes=values["global_passes"],
                             wobble_enabled=True, wobble_step=step, wobble_size=size))
        cells.append({"name": name, "parameters": params, "wobble_step": step, "wobble_size": size,
                      "x": x, "y": y, "width": wobble_side, "height": wobble_side})
        index += 1

    # Three representative hatch intervals: tighter than baseline, baseline-adjacent and coarse.
    hatch_side, hatch_y, hatch_x, hatch_pitch = 3.0, 23.0, 38.0, 3.8
    for col, interval in enumerate(COMPACT_HATCH_INTERVALS_MM):
        x = hatch_x + col * hatch_pitch
        name = f"HATCH-I{interval:g}"
        labels += _text(f"I{interval:g}", x, hatch_y - 1.15, 0.075)
        params = _process(values | {"line_interval": interval})
        layers.append(_layer(index, name, params, [_rect(x, hatch_y, hatch_side, hatch_side)], mode="Scan",
                             line_interval=interval, global_passes=values["global_passes"]))
        cells.append({"name": name, "parameters": params, "x": x, "y": hatch_y, "width": hatch_side, "height": hatch_side})
        index += 1

    # Four logarithmically distributed rates include the requested baseline. CW isolates repetition
    # rate from pulse-width cutoff; the complete frequency plate contains every supported test value.
    rate = passport["repetition_rate_khz"]
    lo, hi = float(rate["min"]), float(rate["max"])
    if hi > lo:
        mid = math.sqrt(lo * hi)
        candidates = [lo, float(values["frequency"]), mid, hi]
        frequencies = sorted({round(max(lo, min(hi, f)), 2) for f in candidates})
        if len(frequencies) < COMPACT_FREQUENCY_POINTS:
            for fraction in (1 / 3, 2 / 3):
                frequencies.append(round(math.exp(math.log(lo) + fraction * (math.log(hi) - math.log(lo))), 2))
                frequencies = sorted(set(frequencies))
                if len(frequencies) >= COMPACT_FREQUENCY_POINTS:
                    break
        if len(frequencies) > COMPACT_FREQUENCY_POINTS:
            inner = sorted(frequencies[1:-1], key=lambda f: abs(math.log(f) - math.log(values["frequency"])))
            keep = {frequencies[0], frequencies[-1], values["frequency"]}
            for f in inner:
                if len(keep) >= COMPACT_FREQUENCY_POINTS:
                    break
                keep.add(f)
            frequencies = sorted(keep)
    else:
        frequencies = [lo]
    cw = next((float(step["pulse_width_ns"]) for step in passport["pulse_steps"] if step["cutoff_khz"] is None), values["pulse_width"])
    frequency_x1, frequency_x2, frequency_y0, frequency_pitch = 40.0, 55.0, 27.5, 3.9
    for row, frequency in enumerate(frequencies):
        y = frequency_y0 + row * frequency_pitch
        name = f"FREQUENCY-F{frequency:g}-CW{cw:g}"
        labels += _text(f"F{frequency:g}", 34.0, y - 0.2, 0.055)
        params = _process(values | {"frequency": frequency, "pulse_width": cw})
        layers.append(_layer(index, name, params, [_line(frequency_x1, y, frequency_x2, y)], mode="Cut",
                             global_passes=values["global_passes"]))
        cells.append({"name": name, "parameters": params, "x": frequency_x1, "y": y - 0.02,
                      "width": frequency_x2 - frequency_x1, "height": 0.04})
        index += 1

    # All five glyph heights share one parameter set, so they belong to one real output layer.
    text_y, text_pitch = 37.5, 5.0
    text_params = _process({**values, **LABEL_DEFAULTS})
    text_regions, text_groups = [], []
    for col, glyph_height in enumerate(COMPACT_TEXT_HEIGHTS_MM):
        x = 3.0 + col * text_pitch
        start = len(text_regions)
        pixel = glyph_height / (5 * 1.45)
        text_regions.extend(_text("A8", x, text_y, pixel))
        text_groups.append({"name": f"TEXT-H{glyph_height:g}MM", "region_start": start,
                            "region_count": len(text_regions) - start, "glyph_height_mm": glyph_height})
        labels += _text(f"H{glyph_height:g}", x, text_y + glyph_height + 0.35, 0.07)
    text_name = "TEXT-H0.8-2.5MM"
    text_layer = _layer(index, text_name, text_params, text_regions, mode="Scan",
                        line_interval=LABEL_DEFAULTS["line_interval"], global_passes=1)
    text_layer["measurement_groups"] = text_groups
    layers.append(text_layer)
    cells.append({"name": text_name, "parameters": text_params, "x": 3.0, "y": text_y,
                  "width": 22.5, "height": 5.85, "features": text_groups})

    feature_count = 16 + len(gap_groups) + len(COMPACT_WOBBLE_POINTS) + len(COMPACT_HATCH_INTERVALS_MM) + len(frequencies) + len(text_groups)
    return layers, labels, {"width": 58.0, "height": 42.0, "columns": 4, "rows": 4,
                            "cells": cells, "feature_count": feature_count}


def _text_readability(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """A small, repeatable text coupon centered on an observed or user-selected setting."""
    power = float(values["power"])
    speed = float(values["speed"])
    spread = float(values.get("text_spread", 0.2))
    if not math.isfinite(spread) or not 0.04 <= spread <= 0.4:
        raise su.ValidationError("lettering test spread must be from 4% to 40%")
    powers = sorted({round(max(1.0, min(100.0, power * factor)), 2) for factor in (1 - spread, 1, 1 + spread)})
    speeds = sorted({round(max(1.0, min(10000.0, speed * factor)), 1) for factor in (1 - spread * 1.25, 1, 1 + spread * 1.25)})
    if len(powers) < 3 or len(speeds) < 3:
        raise su.ValidationError("for the three-point lettering test use power 2–83% and speed 2–8000 mm/s")
    labels = _text("TEXT POWER X SPEED", 2.0, 1.0, 0.14)
    layers, cells = [], []
    x0, y0, pitch_x, pitch_y = 5.0, 10.0, 16.0, 12.0
    heights = (1.0, 1.5, 2.0)
    for col, setting_power in enumerate(powers):
        labels += _text(f"P{setting_power:g}", x0 + col * pitch_x, 7.0, 0.08)
    for row, setting_speed in enumerate(speeds):
        y = y0 + row * pitch_y
        labels += _text(f"V{setting_speed:g}", 0.5, y + 4.0, 0.055)
        for col, setting_power in enumerate(powers):
            x = x0 + col * pitch_x
            params = _process(values | {"power": setting_power, "speed": setting_speed})
            regions, groups = [], []
            for height_index, height in enumerate(heights):
                first = len(regions)
                glyphs = _text("A8M", x + 1.0, y + 0.5 + height_index * 3.4, height / (5 * 1.45))
                regions.extend(glyphs)
                groups.append({"name": f"TEXT-H{height:g}MM", "region_start": first,
                               "region_count": len(glyphs), "glyph_height_mm": height})
            name = f"TEXT-P{setting_power:g}-V{setting_speed:g}"
            layer = _layer(len(layers) + 1, name, params, regions, mode="Scan",
                           line_interval=values["line_interval"], global_passes=values["global_passes"])
            layer["measurement_groups"] = groups
            layers.append(layer)
            cells.append({"name": name, "parameters": params, "x": x, "y": y,
                          "width": 13.0, "height": 10.0, "features": groups})
    return layers, labels, {"width": 54.0, "height": 47.0, "columns": 3, "rows": 3,
                            "cells": cells, "feature_count": len(cells) * len(heights)}


def _wobble(values: dict) -> tuple[list[dict], list[dict], dict]:
    side, x0, y0, pitch = 5.0, 5.0, 12.0, 8.0
    labels = _text("WOBBLE STEP X CIRCLE DIAMETER", 3.0, 1.0, 0.18)
    layers, cells = [], []
    for row, step in enumerate(WOBBLE_STEPS_MM):
        for col, size in enumerate(WOBBLE_SIZES_MM):
            x, y = x0 + col * pitch, y0 + row * pitch
            name = f"WOBBLE-S{step:g}-D{size:g}"
            labels += _text(f"S{step:g}D{size:g}", x, y - 1.8, 0.09)
            params = _process(values)
            layers.append(_layer(len(layers) + 1, name, params, [_rect(x, y, side, side)], mode="Scan",
                                 line_interval=values["line_interval"], global_passes=values["global_passes"],
                                 wobble_enabled=True, wobble_step=step, wobble_size=size))
            cells.append({"name": name, "wobble_step": step, "wobble_size": size,
                          "power": values["power"], "frequency": values["frequency"], "speed": values["speed"],
                          "x": x, "y": y, "width": side, "height": side})
    return layers, labels, {"width": 5 + 2 * pitch + side + 3, "height": y0 + 2 * pitch + side + 3,
                            "columns": 3, "rows": 3, "cells": cells}


def _small_patches(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """A true content-sized coupon; marker/QR overhead is included by preview()."""
    try:
        side = float(values.get("patch_size_mm", 3.0))
    except (TypeError, ValueError):
        raise su.ValidationError("square size must be a number from 3 to 5 mm") from None
    if not math.isfinite(side) or not 3 <= side <= 5:
        raise su.ValidationError("square size must be from 3 to 5 mm")
    registration = values.get("registration", "full")
    if registration not in {"full", "none"}:
        raise su.ValidationError("small plate registration must be full or none")
    patch_specs = values.get("patches")
    if patch_specs is None:
        patch_specs = [{}]
    if not isinstance(patch_specs, list) or not 1 <= len(patch_specs) <= 4 or any(not isinstance(p, dict) for p in patch_specs):
        raise su.ValidationError("provide one to four squares with settings")
    gap, pad = 0.8, 1.5
    max_width = float(values.get("max_width_mm", PLATE_DEFAULT_MM))
    max_height = float(values.get("max_height_mm", PLATE_DEFAULT_MM))
    minimum_canvas = 10.0 if registration == "full" else 0.0
    marker_overhead = 9.0 if registration == "full" else 0.0
    layouts = []
    for candidate_columns in range(1, len(patch_specs) + 1):
        candidate_rows = math.ceil(len(patch_specs) / candidate_columns)
        cw = max(minimum_canvas, candidate_columns * side + (candidate_columns - 1) * gap + 2 * pad) + marker_overhead
        ch = max(minimum_canvas, candidate_rows * side + (candidate_rows - 1) * gap + 2 * pad) + marker_overhead
        fits = cw <= max_width + 1e-6 and ch <= max_height + 1e-6
        layouts.append((not fits, cw * ch, abs(cw - ch), candidate_columns, candidate_rows))
    _, _, _, columns, rows = min(layouts)
    content_w = columns * side + (columns - 1) * gap
    content_h = rows * side + (rows - 1) * gap
    width, height = max(minimum_canvas, content_w + 2 * pad), max(minimum_canvas, content_h + 2 * pad)
    x0, y0 = (width - content_w) / 2, (height - content_h) / 2
    layers, cells = [], []
    for i, spec in enumerate(patch_specs):
        unknown = set(spec) - RECIPE_KEYS
        if unknown:
            raise su.ValidationError(f"square {i + 1}: unknown settings: {', '.join(sorted(unknown))}")
        selected, _, _ = _passport_defaults(passport, {**values, **spec})
        x = x0 + (i % columns) * (side + gap)
        y = y0 + (i // columns) * (side + gap)
        name = f"PATCH-{i + 1:02d}-P{selected['power']:g}-V{selected['speed']:g}"
        params = _process(selected)
        layers.append(_layer(i + 1, name, params, [_rect(x, y, side, side)], mode="Scan",
                             line_interval=selected["line_interval"], global_passes=selected["global_passes"]))
        cells.append({"name": name, "parameters": params, "x": x, "y": y,
                      "width": side, "height": side, "patch_index": i + 1})
    return layers, [], {"width": width, "height": height, "columns": columns, "rows": rows,
                        "cells": cells, "sample_area_mm2": round(len(cells) * side * side, 2)}


def _matrix_axis_values(axis: str, lower: float, upper: float, count: int, passport: dict) -> list[float]:
    """Return a bounded, unique sweep. Pulse and pass axes use supported discrete values."""
    if axis == "pulse_width":
        domain = sorted({float(step["pulse_width_ns"]) for step in passport["pulse_steps"]
                        if lower <= float(step["pulse_width_ns"]) <= upper})
        if len(domain) < count:
            raise su.ValidationError(f"only {len(domain)} Q-Pulse steps are available in the selected range; reduce the number of points or expand the range")
        return [float(item["value"]) for item in _evenly_spaced([{"value": v} for v in domain], count)]
    if axis == "passes":
        low, high = int(lower), int(upper)
        if lower != low or upper != high or high - low + 1 < count:
            raise su.ValidationError("the passes axis must use whole-number bounds and contain enough distinct values")
        return [float(round(low + i * (high - low) / (count - 1))) for i in range(count)]
    return [round(lower + i * (upper - lower) / (count - 1), 4) for i in range(count)]


def _material_matrix(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """A Material-Test-style 5x5 response matrix. Every cell owns one real output layer."""
    settings = _matrix_settings(values, passport)
    x_axis, y_axis = settings["x_axis"], settings["y_axis"]
    x_meta, y_meta = MATRIX_AXES[x_axis], MATRIX_AXES[y_axis]
    x_values = _matrix_axis_values(x_axis, settings["x_min"], settings["x_max"], settings["x_count"], passport)
    y_values = _matrix_axis_values(y_axis, settings["y_min"], settings["y_max"], settings["y_count"], passport)
    mark = settings["geometry"]
    columns, rows = len(x_values), len(y_values)
    gap, x0, y0 = 0.5, 5.0, 10.0
    # Compact cells and place the QR in the top registration band. Four small corner marks still
    # give the photo enough points for perspective alignment without stacking a QR footer below it.
    cell_w, cell_h = ((21.0, 15.5) if mark == "vector_text" else
                      (13.0, 10.5) if mark == "text" else (8.5, 7.5))
    if min(cell_w, cell_h) < 4.0:
        raise su.ValidationError("choose fewer points on each axis so labels and samples remain distinguishable")
    labels = _text(f"{x_meta['short']} X {y_meta['short']} MATERIAL TEST", 2.0, 1.0, 0.18)
    layers, cells = [], []
    for col, x_value in enumerate(x_values):
        x = x0 + col * (cell_w + gap)
        labels += _text(f"{x_value:g}", x + 2.5, 9.0, 0.10)
    for row, y_value in enumerate(y_values):
        y = y0 + row * (cell_h + gap)
        labels += _text(f"{y_value:g}", 1.0, y + 3.0, 0.10)
        for col, x_value in enumerate(x_values):
            x = x0 + col * (cell_w + gap)
            params = {**values, x_axis: x_value, y_axis: y_value}
            params.pop("matrix", None)
            params = _process(params)
            name = f"MATRIX-{x_meta['short']}{x_value:g}-{y_meta['short']}{y_value:g}"
            groups = []
            if mark == "vector_text":
                region = []
                baseline = y + 0.7
                for height, repeat in ((2.0, 1), (2.0, 2), (4.0, 1), (4.0, 2)):
                    first = len(region)
                    glyphs = _vector_text("A8M B012", x + 0.8, baseline, height)
                    region.extend(glyphs)
                    groups.append({"name": f"TEXT-H{height:g}MM-R{repeat}", "region_start": first,
                                   "region_count": len(glyphs), "glyph_height_mm": height, "repeat": repeat})
                    baseline += height + 0.65
                mode, interval = "Cut", params["line_interval"]
            elif mark == "text":
                region = []
                for height_index, glyph_height in enumerate((0.9, 1.3, 1.7)):
                    first = len(region)
                    glyphs = _text("A8M", x + 0.9, y + 0.5 + height_index * 3.1,
                                   glyph_height / (5 * 1.45))
                    region.extend(glyphs)
                    groups.append({"name": f"TEXT-H{glyph_height:g}MM", "region_start": first,
                                   "region_count": len(glyphs), "glyph_height_mm": glyph_height})
                mode, interval = "Scan", params["line_interval"]
            elif mark == "fill":
                side = min(5.6, cell_w * 0.68, cell_h * 0.68)
                region = [_rect(x + (cell_w - side) / 2, y + (cell_h - side) / 2, side, side)]
                mode, interval = "Scan", params["line_interval"]
            else:
                line_length = min(7.4, cell_w * 0.82, cell_h * 0.78)
                region = [_line(x + (cell_w - line_length) / 2, y + cell_h / 2,
                                x + (cell_w + line_length) / 2, y + cell_h / 2)]
                mode, interval = "Cut", params["line_interval"]
            if mark in ("text", "vector_text"):
                name = f"TEXT-MATRIX-{x_meta['short']}{x_value:g}-{y_meta['short']}{y_value:g}"
            wobble_size = (float(x_value) if x_axis == "wobble_size" else
                           float(y_value) if y_axis == "wobble_size" else 0.0)
            layer = _layer(len(layers) + 1, name, params, region, mode=mode,
                           line_interval=interval, global_passes=values["global_passes"],
                           wobble_enabled=wobble_size > 0, wobble_step=settings["wobble_step"],
                           wobble_size=wobble_size)
            if groups:
                layer["measurement_groups"] = groups
            layers.append(layer)
            cells.append({"name": name, "parameters": params,
                          "x": x if mark in ("text", "vector_text") else region[0]["x"],
                          "y": y if mark in ("text", "vector_text") else region[0]["y"],
                          "width": cell_w if mark in ("text", "vector_text") else region[0]["width"],
                          "height": cell_h if mark in ("text", "vector_text") else region[0]["height"],
                          "x_axis": x_axis, "y_axis": y_axis, "x_value": x_value, "y_value": y_value,
                          "geometry_type": mark, "wobble_enabled": wobble_size > 0,
                          "wobble_step": settings["wobble_step"] if wobble_size > 0 else None,
                          "wobble_size": wobble_size, "features": groups})
    width = x0 + columns * cell_w + (columns - 1) * gap + 2.0
    height = y0 + rows * cell_h + (rows - 1) * gap + 2.0
    return layers, labels, {"width": width, "height": height, "columns": columns, "rows": rows,
                            "feature_count": len(cells) * (4 if mark == "vector_text" else 3 if mark == "text" else 1),
                            "cells": cells, "matrix": {**settings, "x_values": x_values, "y_values": y_values}}


def _matrix_settings(values: dict, passport: dict) -> dict:
    supplied = values.get("matrix") or {}
    x_axis = supplied.get("x_axis", "power")
    y_axis = supplied.get("y_axis", "speed")
    if x_axis not in MATRIX_AXES or y_axis not in MATRIX_AXES or x_axis == y_axis:
        raise su.ValidationError("choose two different axes from power, speed, frequency, Q-Pulse, line interval, passes, and Wobble")
    geometry = supplied.get("geometry", "line")
    if geometry not in ("line", "fill", "text", "vector_text"):
        raise su.ValidationError("matrix geometry must be a line, fill, filled text, or vector text")
    if "line_interval" in (x_axis, y_axis) and geometry in ("line", "vector_text"):
        raise su.ValidationError("line interval is tested only on filled areas; choose fill or another axis")
    if "wobble_size" in (x_axis, y_axis) and geometry not in ("line", "vector_text"):
        raise su.ValidationError("Wobble is tested on a vector line or single-line vector text")
    repetition = passport["repetition_rate_khz"]
    pulse_values = [float(step["pulse_width_ns"]) for step in passport["pulse_steps"]]
    domain = {"power": (1.0, 100.0), "frequency": (float(repetition["min"]), float(repetition["max"])),
              "speed": (1.0, 10000.0), "pulse_width": (min(pulse_values), max(pulse_values)),
              "line_interval": (0.001, 1.0), "passes": (1.0, 20.0), "wobble_size": (0.0, 1.0)}
    defaults = {key: (float(MATRIX_AXES[key]["default_min"]), float(MATRIX_AXES[key]["default_max"])) for key in MATRIX_AXES}
    defaults["frequency"] = (max(domain["frequency"][0], defaults["frequency"][0]),
                              min(domain["frequency"][1], defaults["frequency"][1]))
    defaults["pulse_width"] = (min(pulse_values), max(pulse_values))
    try:
        wobble_step = float(supplied.get("wobble_step", 0.02))
    except (TypeError, ValueError):
        raise su.ValidationError("Wobble step must be a number") from None
    if not math.isfinite(wobble_step) or not 0.001 <= wobble_step <= 1:
        raise su.ValidationError("Wobble step must be from 0.001 to 1 mm")
    out = {"x_axis": x_axis, "y_axis": y_axis, "geometry": geometry, "wobble_step": wobble_step}
    for prefix, axis in (("x", x_axis), ("y", y_axis)):
        low_default, high_default = defaults[axis]
        try:
            low = float(supplied.get(f"{prefix}_min", low_default))
            high = float(supplied.get(f"{prefix}_max", high_default))
            count = int(supplied.get(f"{prefix}_count", 5))
        except (TypeError, ValueError):
            raise su.ValidationError("matrix bounds and point counts must be numbers") from None
        if not math.isfinite(low) or not math.isfinite(high) or low >= high:
            raise su.ValidationError("each axis minimum must be strictly below its maximum")
        if low < domain[axis][0] or high > domain[axis][1]:
            raise su.ValidationError(f"the {MATRIX_AXES[axis]['label']} axis exceeds the laser’s supported range: {domain[axis][0]:g}–{domain[axis][1]:g} {MATRIX_AXES[axis]['unit']}")
        if not 2 <= count <= 7:
            raise su.ValidationError("provide 2 to 7 points per axis")
        if axis == "passes" and (low != round(low) or high != round(high)):
            raise su.ValidationError("passes axis bounds must be whole numbers")
        out.update({f"{prefix}_min": low, f"{prefix}_max": high, f"{prefix}_count": count})
    if out["x_count"] * out["y_count"] > 28:
        raise su.ValidationError("the grid can have at most 28 cells; cleaning and registration need two more output layers")
    return out


GREY_AXES = ("speed", "line_interval", "frequency", "pulse_width", "passes", "width")
# the ramp's own width in mm: the length of its scan lines, so the plate measures how a colour depends on the size of what is engraved
GREY_WIDTH_AXIS = {"label": "Ramp width", "short": "W", "unit": "mm"}
GREY_DEFAULTS = {"rows": {"axis": "line_interval", "values": [0.0127, 0.0169, 0.0212, 0.0254]},     # 2000, 1500, 1200, 1000 dpi
                 "columns": {"axis": "speed", "factors": [2 / 3, 1.0, 5 / 3]}, "min_power": 1.0}
GREY_MAX_ROWS, GREY_MAX_COLUMNS = 7, 4
GREY_LABEL_WIDTH, GREY_GAP, GREY_TILE_HEIGHT, GREY_ROW_PITCH, GREY_TOP = 9.0, 2.0, 4.0, 6.5, 6.0
GREY_MAX_STEP = 2.5                    # mm: a step wider than this only makes the plate longer
GREY_MIN_STEP = 1.0                    # mm: a narrower step leaves too few photograph pixels once its edges are left out


def _grey_meta(key: str) -> dict:
    """The label metadata of a grey-plate axis: a laser setting's from ``MATRIX_AXES``, or the ramp width's."""
    return GREY_WIDTH_AXIS if key == "width" else MATRIX_AXES[key]


def _grey_axis(name: str, axis: dict, base: dict, passport: dict) -> tuple[str, list[float]]:
    """One axis of the grey-ramp plate: a setting from ``GREY_AXES`` and its values, each one the laser can engrave (a ramp width:
    one whose steps are wide enough to measure)."""
    key = axis.get("axis")
    if key not in GREY_AXES:
        raise su.ValidationError(f"{name}: choose speed, line interval, frequency, pulse width, passes, or strip width")
    raw = axis.get("values")
    if raw is None and axis.get("factors"):
        if key == "width":
            raise su.ValidationError(f"{name}: strip width values are in mm")
        raw = [round(base[key] * f, 4) for f in axis["factors"]]
    try:
        values = [float(v) for v in (raw or [])]
    except (TypeError, ValueError):
        raise su.ValidationError(f"{name}: values must be numbers") from None
    if not values or len(set(values)) != len(values) or not all(math.isfinite(v) and v > 0 for v in values):
        raise su.ValidationError(f"{name}: values must be distinct positive numbers")
    rate = passport["repetition_rate_khz"]
    for v in values:
        if key == "speed" and v > 10000:
            raise su.ValidationError("test speed must not exceed 10000 mm/s")
        if key == "line_interval" and not 0.001 <= v <= 1:
            raise su.ValidationError("image-layer line interval must be from 0.001 to 1 mm")
        if key == "frequency" and not rate["min"] <= v <= rate["max"]:
            raise su.ValidationError(f"frequency must be in the range {rate['min']:g}–{rate['max']:g} kHz for the selected laser")
        if key == "pulse_width":
            devices.require_selectable(passport, v)
        if key == "passes" and (int(v) != v or not 1 <= v <= 20):
            raise su.ValidationError("passes: enter whole numbers from 1 to 20")
        if key == "width" and v / grayscale.RAMP_STEPS < GREY_MIN_STEP:
            raise su.ValidationError(f"a {v:g} mm strip produces a {v / grayscale.RAMP_STEPS:g} mm step; a step narrower than {GREY_MIN_STEP:g} mm "
                                     f"cannot be measured in the photo: use a width of at least {grayscale.RAMP_STEPS * GREY_MIN_STEP:g} mm")
    return key, [int(v) if key == "passes" else v for v in values]


def _grey_scales(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """Grey ramps in grayscale mode (REQ-059): one Image layer per tile, a 16-step ramp from white to black, so each step is one power
    between the plate's Min and Max; rows and columns change two of the fixed settings, or one setting and the ramp's width. The ramp
    runs left to right, so the plate's vertical mirror (``export_mirror_y``) cannot reverse it.

    Without a width axis every ramp has the width that fits the plate's limit (at most 2.5 mm a step). With one, each ramp is as wide as
    its width value; a column is as wide as its widest ramp and its ramps start at its left edge.

    With ``scales.dither`` a dot kind of LightBurn (0.21.0), the ramps are engraved in that kind at the plate's one power: LightBurn
    makes the dots of each step, so each step is one share of dots at that power and the photograph measures the kind's tonal profile;
    with ``scales.dot_width`` (mm) LightBurn corrects the width of those dots, and the profile is measured at that dot width."""
    supplied = values.get("scales") or {}
    dither = supplied.get("dither") or plans.IMAGE_DITHER
    kind = photo_modes.mode(dither)
    if kind is None or kind.family not in (photo_modes.POWER, photo_modes.DOTS, photo_modes.EDGES) or kind.key != dither:
        raise su.ValidationError("strips must use grayscale or a LightBurn dot mode")
    rows_key, row_values = _grey_axis("rows", supplied.get("rows") or GREY_DEFAULTS["rows"], values, passport)
    cols_key, col_values = _grey_axis("columns", supplied.get("columns") or GREY_DEFAULTS["columns"], values, passport)
    if rows_key == cols_key:
        raise su.ValidationError("rows and columns must vary different parameters")
    if len(row_values) > GREY_MAX_ROWS or len(col_values) > GREY_MAX_COLUMNS:
        raise su.ValidationError(f"at most {GREY_MAX_ROWS} rows and {GREY_MAX_COLUMNS} columns: 28 strips and two auxiliary layers fill all 30 LightBurn layers")
    try:
        low = float(supplied.get("min_power", GREY_DEFAULTS["min_power"]))
        high = float(supplied.get("max_power", values["power"]))
    except (TypeError, ValueError):
        raise su.ValidationError("Min and Max power must be numbers") from None
    dot_width = supplied.get("dot_width")
    if dot_width is not None:
        lo, hi = photo_modes.DOT_WIDTH_MM
        if dither == plans.IMAGE_DITHER or isinstance(dot_width, bool) or not isinstance(dot_width, (int, float)) \
                or not lo <= dot_width <= hi:
            raise su.ValidationError(f"dot-width adjustment applies only to dot modes and must be from {lo:g} to {hi:g} mm")
        dot_width = float(dot_width)
    if dither != plans.IMAGE_DITHER:
        low = high = float(values["power"])            # every dot fires at the layer's power
        if not 0 < high <= 100:
            raise su.ValidationError("dot power must be greater than 0 and at most 100%")
    elif not (math.isfinite(low) and math.isfinite(high) and 0 <= low < high <= 100):
        raise su.ValidationError("Min and Max power must be from 0 to 100%, with Min below Max")
    columns = len(col_values)
    if "width" in (rows_key, cols_key):
        tile_w = None                  # each ramp has its own width; the plate's size limit is checked on the whole plate
    else:
        width_limit = values.get("max_width_mm", PLATE_DEFAULT_MM) - 2 * (COMPACT_MARKER_SIZE["aruco_mm"] + COMPACT_MARKER_SIZE["margin_mm"])
        tile_w = min(grayscale.RAMP_STEPS * GREY_MAX_STEP, (width_limit - GREY_LABEL_WIDTH - 1 - (columns - 1) * GREY_GAP) / columns)
        if tile_w / grayscale.RAMP_STEPS < GREY_MIN_STEP:
            raise su.ValidationError("strips do not fit the plate width: reduce columns or increase the width limit")
        tile_w = math.floor(tile_w / grayscale.RAMP_STEPS * 10) / 10 * grayscale.RAMP_STEPS      # steps of whole tenths of a millimetre

    def ramp_width(r_value: float, c_value: float) -> float:
        return r_value if rows_key == "width" else c_value if cols_key == "width" else tile_w

    column_widths = [max(ramp_width(r_value, c_value) for r_value in row_values) for c_value in col_values]
    column_x = [GREY_LABEL_WIDTH + sum(column_widths[:col]) + col * GREY_GAP for col in range(columns)]
    r_meta, c_meta = _grey_meta(rows_key), _grey_meta(cols_key)
    labels = _text(f"GREY {r_meta['short']} X {c_meta['short']} P{low:g}-{high:g}" if dither == plans.IMAGE_DITHER
                   else f"{dither} {r_meta['short']} X {c_meta['short']} P{high:g}", 1.0, 0.8, 0.14)
    greys = grayscale.ramp_greys()
    layers, cells = [], []
    for col, c_value in enumerate(col_values):
        labels += _text(f"{c_meta['short']}{c_value:g}", column_x[col], GREY_TOP - 1.6, 0.10)
    for row, r_value in enumerate(row_values):
        y = GREY_TOP + row * GREY_ROW_PITCH
        labels += _text(f"{r_meta['short']}{r_value:g}", 0.6, y + 1.4, 0.10)
        for col, c_value in enumerate(col_values):
            x, tile = column_x[col], ramp_width(r_value, c_value)
            params = _process({**values, rows_key: r_value, cols_key: c_value, "power": high})
            params["min_power"] = low
            if dot_width is not None:
                params["dot_width"] = dot_width
            name = f"GREY-{r_meta['short']}{r_value:g}-{c_meta['short']}{c_value:g}"
            ramp = {"x": x, "y": y, "width": tile, "height": GREY_TILE_HEIGHT, "greys": greys, "dither": dither}
            layer = _layer(len(layers) + 1, name, params, [_rect(x, y, tile, GREY_TILE_HEIGHT)], mode="Image",
                           line_interval=params["line_interval"], global_passes=values["global_passes"])
            layer["ramp"] = ramp
            layers.append(layer)
            cells.append({"name": name, "parameters": params, "x": x, "y": y, "width": tile, "height": GREY_TILE_HEIGHT,
                          "row_axis": rows_key, "row_value": r_value, "column_axis": cols_key, "column_value": c_value,
                          "min_power": low, "max_power": high, "steps": len(greys)})
    width = GREY_LABEL_WIDTH + sum(column_widths) + (columns - 1) * GREY_GAP + 1.0
    height = GREY_TOP + (len(row_values) - 1) * GREY_ROW_PITCH + GREY_TILE_HEIGHT + 1.0
    narrowest = min(cell["width"] for cell in cells)       # step_mm: the narrowest step, every step when the ramps share one width
    return layers, labels, {"width": width, "height": height, "columns": columns, "rows": len(row_values), "cells": cells,
                            "feature_count": len(cells) * len(greys),
                            "sample_area_mm2": round(sum(cell["width"] for cell in cells) * GREY_TILE_HEIGHT, 2),
                            "scales": {"rows": {"axis": rows_key, "values": row_values}, "columns": {"axis": cols_key, "values": col_values},
                                       "min_power": low, "max_power": high, "steps": len(greys), "step_mm": round(narrowest / len(greys), 3),
                                       "dither": dither, **({"dot_width": dot_width} if dot_width is not None else {})}}


FILL_DEFAULT_WIDTHS_MM = (5.0, 20.0, 50.0, 100.0)
FILL_MAX_RECIPES, FILL_MAX_WIDTHS, FILL_MAX_STRIPS = 7, 5, 28
FILL_MIN_WIDTH, FILL_STRIP_HEIGHT, FILL_GAP = 3.0, 4.0, 2.0
FILL_TOP = 3.0                         # mm: below the QR, which reaches 1.75 mm into the top of the plate
FILL_MIN_PLATE_WIDTH = 10.0            # mm: the QR fits in the top band between the two upper markers, as on a small-patch plate
FILL_LABEL_PIXEL = 0.10
FILL_LABEL_AXES = ("power", "speed", "frequency", "pulse_width", "line_interval", "passes")


def _fill_widths(raw) -> list[float]:
    """The strip widths of a fill-size plate: 1–5 different widths of 3–300 mm."""
    if raw is None:
        raw = FILL_DEFAULT_WIDTHS_MM
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= FILL_MAX_WIDTHS:
        raise su.ValidationError(f"provide one to {FILL_MAX_WIDTHS} strip widths")
    try:
        widths = [float(w) for w in raw]
    except (TypeError, ValueError):
        raise su.ValidationError("strip widths must be numbers") from None
    if len(set(widths)) != len(widths) or not all(math.isfinite(w) and FILL_MIN_WIDTH <= w <= PLATE_MAX_MM for w in widths):
        raise su.ValidationError(f"strip widths must be distinct and from {FILL_MIN_WIDTH:g} to {PLATE_MAX_MM:g} mm")
    return widths


def _fill_recipe_labels(recipes: list[dict]) -> list[str]:
    """A short label per recipe: the settings in which the recipes differ (P40 V150), one recipe's power and speed, else R1, R2 ..."""
    differ = [key for key in FILL_LABEL_AXES if len({recipe[key] for recipe in recipes}) > 1]
    if not differ and len(recipes) == 1:
        differ = ["power", "speed"]
    if not differ:
        return [f"R{n}" for n in range(1, len(recipes) + 1)]
    return [" ".join(f"{MATRIX_AXES[key]['short']}{recipe[key]:g}" for key in differ) for recipe in recipes]


def _fill_sizes(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """Flat fills of chosen recipes at several widths: one Scan strip 4 mm high per recipe and width, each its own layer at constant
    power. The scan lines run along the strip, so its width is the length of a line; the strips are stacked, recipe by recipe, and
    start at the right of their labels."""
    specs = values.get("recipes")
    if specs is None:
        specs = [{}]
    if not isinstance(specs, list) or not 1 <= len(specs) <= FILL_MAX_RECIPES or any(not isinstance(r, dict) for r in specs):
        raise su.ValidationError(f"provide one to {FILL_MAX_RECIPES} fill recipes")
    widths = _fill_widths(values.get("widths_mm"))
    if len(specs) * len(widths) > FILL_MAX_STRIPS:
        raise su.ValidationError(f"at most {FILL_MAX_STRIPS} strips (recipes × widths); {len(specs) * len(widths)} were requested: "
                                 "cleaning and markers use two additional LightBurn layers")
    recipes = []
    for i, spec in enumerate(specs):
        unknown = set(spec) - RECIPE_KEYS
        if unknown:
            raise su.ValidationError(f"recipe {i + 1}: unknown settings: {', '.join(sorted(unknown))}")
        selected, _, _ = _passport_defaults(passport, {**values, **spec})
        recipes.append({**_process(selected), "global_passes": selected["global_passes"]})
    short = _fill_recipe_labels(recipes)
    texts = [f"{short[r]} W{w:g}" for r in range(len(recipes)) for w in widths]
    char_pitch = FILL_LABEL_PIXEL * 1.45 * 1.35              # the pitch of _text's characters
    x0 = math.ceil((0.6 + max(len(t) for t in texts) * char_pitch + 1.0) * 10) / 10
    layers, labels, cells = [], [], []
    for r, recipe in enumerate(recipes):
        params = _process(recipe)
        for w in widths:
            y = FILL_TOP + len(layers) * (FILL_STRIP_HEIGHT + FILL_GAP)
            name = f"FILL-R{r + 1}-W{w:g}"
            labels += _text(texts[len(layers)], 0.6, y + 1.6, FILL_LABEL_PIXEL)
            layers.append(_layer(len(layers) + 1, name, params, [_rect(x0, y, w, FILL_STRIP_HEIGHT)], mode="Scan",
                                 line_interval=recipe["line_interval"], global_passes=recipe["global_passes"]))
            cells.append({"name": name, "parameters": params, "x": x0, "y": y, "width": w, "height": FILL_STRIP_HEIGHT,
                          "recipe_index": r + 1})
    width = max(FILL_MIN_PLATE_WIDTH, x0 + max(widths) + 1.0)
    height = FILL_TOP + len(cells) * FILL_STRIP_HEIGHT + (len(cells) - 1) * FILL_GAP + 1.0
    return layers, labels, {"width": width, "height": height, "columns": 1, "rows": len(cells), "cells": cells,
                            "sample_area_mm2": round(sum(c["width"] for c in cells) * FILL_STRIP_HEIGHT, 2),
                            "fills": {"recipes": recipes, "widths_mm": widths, "strip_height_mm": FILL_STRIP_HEIGHT}}


VARIATION_MAX, VARIATION_MIN = 12, 2
VARIATION_COPY_MM = (8.0, 40.0)       # the longer side of a copy: smaller leaves too few photograph pixels, larger takes too long
VARIATION_DEFAULT_COPY_MM = 18.0
VARIATION_GAP, VARIATION_LABEL_H, VARIATION_RAMP_GAP, VARIATION_TOP = 3.0, 1.8, 0.8, 3.0
VARIATION_WINDOW_OPAQUE = 0.8        # the share of a copy's window the picture must cover; the rest is left as it is
VARIATION_PICTURE_PX_MM = 20.0        # as a photo zone's picture in a file: LightBurn resamples it to the layer's DPI and dithers that
VARIATION_KEYS = frozenset({"dither", "power", "min_power", "speed", "frequency", "pulse_width", "line_interval", "passes", "dot_width"})
MODE_LETTER = {"grayscale": "G", "jarvis": "J", "atkinson": "A", "stucki": "S", "dither": "FS", "ordered": "O", "newsprint": "N",
               "halftone": "H", "sketch": "SK", "threshold": "T"}
VARIATION_SHORT = (("power", "P"), ("speed", "V"), ("frequency", "F"), ("pulse_width", "PW"), ("line_interval", "I"), ("dot_width", "D"),
                   ("passes", "N"))


def _variation_picture(raw) -> np.ndarray:
    """The picture every copy engraves, from PNG or JPEG bytes (or their base64): 8-bit grey, or grey with its opacity (BGRA) when it has
    transparent parts, trimmed to its opaque part."""
    data = raw
    if isinstance(raw, str):
        try:
            data = base64.b64decode(raw, validate=True)
        except ValueError:
            raise su.ValidationError("copy image could not be read: expected PNG or JPEG") from None
    found = None if not isinstance(data, (bytes, bytearray)) else photo_modes.decode_picture(bytes(data))
    if found is None:
        raise su.ValidationError("copy image could not be read: expected PNG or JPEG")
    grey, alpha = found
    opaque = alpha >= photo_modes.ALPHA_MIN
    if not opaque.any():
        raise su.ValidationError("the image has no opaque area to engrave")
    rows, cols = np.nonzero(opaque.any(axis=1))[0], np.nonzero(opaque.any(axis=0))[0]
    grey, alpha = grey[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1], alpha[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    if grey.shape[0] < 16 or grey.shape[1] < 16:
        raise su.ValidationError("the image is too small: at least 16 × 16 pixels are required")
    g8 = np.round(np.clip(grey, 0, 1) * 255).astype(np.uint8)
    if (alpha >= photo_modes.ALPHA_MIN).all():
        return g8
    a8 = np.where(alpha >= photo_modes.ALPHA_MIN, 255, 0).astype(np.uint8)
    return np.dstack([g8, g8, g8, a8])


def variation_window(picture: np.ndarray, px_per_mm: float, size_mm: float = VARIATION_DEFAULT_COPY_MM) -> np.ndarray:
    """The part of a picture (grey, or BGRA) that a copy engraves at the picture's own scale: a square ``size_mm`` across (all of it when it
    is smaller), placed where the picture is mostly opaque (``VARIATION_WINDOW_OPAQUE``) and has the most tone: the most of its 16 grey
    steps present (each on at least 1 % of the window), then the widest spread; so the copies show its detail as large as the work
    engraves it, from shadows to highlights (a zone of a portrait: the edge of the glasses and the skin, not only the dark lens)."""
    rows, cols = picture.shape[:2]
    side = max(16, round(size_mm * px_per_mm))
    if rows <= side and cols <= side:
        return picture
    h, w = min(rows, side), min(cols, side)
    grey = (picture if picture.ndim == 2 else cv2.cvtColor(picture[..., :3], cv2.COLOR_BGR2GRAY)).astype(np.float32)
    opaque = np.ones(grey.shape, np.float32) if picture.ndim == 2 or picture.shape[2] < 4 else (picture[..., 3] >= 128).astype(np.float32)
    best, at = None, (0, 0)
    step_y, step_x = max(1, (rows - h) // 16), max(1, (cols - w) // 16)
    for y in range(0, rows - h + 1, step_y):
        for x in range(0, cols - w + 1, step_x):
            cover = opaque[y:y + h, x:x + w]
            share = float(cover.mean())
            if share < VARIATION_WINDOW_OPAQUE:
                continue
            inside = grey[y:y + h, x:x + w][cover > 0]
            steps = np.bincount(np.clip(inside / 16, 0, 15).astype(np.int64), minlength=16) / inside.size
            tone = (int((steps >= 0.01).sum()), float(inside.std()))
            if best is None or tone > best:
                best, at = tone, (y, x)
    if best is None:                                     # nowhere opaque enough: the middle
        at = ((rows - h) // 2, (cols - w) // 2)
    y, x = at
    return np.ascontiguousarray(picture[y:y + h, x:x + w])


def variation_label(variant: dict, centre: dict | None) -> str:
    """The short engraved label of a copy: its kind's letter and the settings in which it differs from the centre (all of them for the
    centre itself), as ``J P25 V125 I.01``; grayscale power is Min and Max, as ``G P2-30``."""
    parts = [MODE_LETTER.get(variant["dither"], variant["dither"][:2].upper())]
    grey = variant["dither"] == plans.IMAGE_DITHER
    for key, short in VARIATION_SHORT:
        value = variant.get(key)
        if grey and key == "power":
            same = centre is not None and variant is not centre and (centre.get("min_power"), centre.get("power")) == (variant["min_power"], value)
            if not same:
                parts.append(f"P{variant['min_power']:g}-{value:g}")
            continue
        if centre is not None and variant is not centre and centre.get(key) == value:
            continue
        if value is None:
            if key == "dot_width" and centre is not None and centre.get(key) is not None:
                parts.append(short + "0")                 # the centre corrects the dot width, this copy does not
            continue
        if key == "passes" and value == 1:
            continue
        text = f"{value:g}"
        parts.append(short + (text[1:] if text.startswith("0.") else text))
    return " ".join(parts)


def _variant(raw, values: dict, passport: dict, n: int) -> dict:
    """One copy's settings: the plate's settings with the copy's own over them, each one the laser can engrave."""
    if not isinstance(raw, dict):
        raise su.ValidationError(f"copy {n}: settings must be an object")
    unknown = set(raw) - VARIATION_KEYS
    if unknown:
        raise su.ValidationError(f"copy {n}: unknown settings: {', '.join(sorted(unknown))}")
    dither = str(raw.get("dither") or values.get("dither") or "jarvis").lower()
    kind = photo_modes.mode(dither)
    if kind is None or kind.key != dither or kind.family not in (photo_modes.POWER, photo_modes.DOTS):
        raise su.ValidationError(f"copy {n}: choose grayscale or a LightBurn dot mode")
    merged = {**{k: values[k] for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes", "global_passes")},
              **{k: v for k, v in raw.items() if k not in ("dither", "dot_width", "min_power")}}
    try:
        checked, _, _ = _passport_defaults(passport, merged)
    except su.ValidationError as exc:
        raise su.ValidationError(f"copy {n}: {exc}") from None
    out = {"dither": dither, **_process(checked)}
    if kind.family == photo_modes.POWER:
        low = raw.get("min_power", values.get("min_power", 0.0))
        try:
            low = float(low)
        except (TypeError, ValueError):
            raise su.ValidationError(f"copy {n}: Min power must be a number") from None
        if not (math.isfinite(low) and 0 <= low < out["power"]):
            raise su.ValidationError(f"copy {n}: Min power must be at least 0 and below Max")
        out["min_power"] = low
    else:
        out["min_power"] = out["power"]                  # every dot fires at the layer's power
        dot_width = raw["dot_width"] if "dot_width" in raw else values.get("dot_width")      # None: the correction off
        if dot_width is not None:
            lo, hi = photo_modes.DOT_WIDTH_MM
            if isinstance(dot_width, bool) or not isinstance(dot_width, (int, float)) or not lo <= dot_width <= hi:
                raise su.ValidationError(f"copy {n}: dot-width adjustment must be from {lo:g} to {hi:g} mm")
            out["dot_width"] = float(dot_width)
    return out


def variation_grid(width: float, height: float, count: int, max_width_mm: float = PLATE_DEFAULT_MM) -> dict:
    """The grid of a photo-variations plate of ``count`` copies ``width`` × ``height`` mm, each with its label and ramp: its columns, rows,
    the height of one copy's cell and the plate's width and height."""
    columns = max(1, min(count, int((max_width_mm - 2 * (COMPACT_MARKER_SIZE["aruco_mm"] + COMPACT_MARKER_SIZE["margin_mm"]) + VARIATION_GAP)
                                    // (width + VARIATION_GAP))))
    rows = (count + columns - 1) // columns
    cell_h = VARIATION_LABEL_H + height + VARIATION_RAMP_GAP + GREY_TILE_HEIGHT
    return {"columns": columns, "rows": rows, "cell_h": cell_h, "width": 1.0 + columns * width + (columns - 1) * VARIATION_GAP + 1.0,
            "height": VARIATION_TOP + rows * cell_h + (rows - 1) * VARIATION_GAP + 1.0}


def _photo_variations(values: dict, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """One picture engraved several times, each copy at its own settings (feature photo-engraving-quality): the copies stand in a grid,
    each with its label above it and, under it, a grey ramp at the same settings and the same width (one row length), so the photograph
    measures each copy's tone exactly (the ramp) and its detail and grain (the picture). A copy and its ramp are two Image layers; the
    picture is stored once (``geometry["pictures"]``) and every copy's layer names it."""
    supplied = values.get("variations") or {}
    picture = _variation_picture(supplied.get("picture_png"))
    # the centre: the plate's settings with the kind, Min power and dot width the variations give (the plate dialog gives them there)
    centre_values = {**values, **{k: supplied[k] for k in ("dither", "min_power", "dot_width") if k in supplied}}
    specs = supplied.get("variants")
    try:
        step = float(supplied.get("step", 1.0))           # the share of the first changes the copies make (DEC-003: halved plate by plate)
    except (TypeError, ValueError):
        step = math.nan
    if not (math.isfinite(step) and 0.05 <= step <= 1.0):
        raise su.ValidationError("copy variation step must be a number from 0.05 to 1")
    if specs is None:                                     # one change at a time around the centre (photo_quality.variants_around)
        specs = photo_quality.variants_around({"dither": str(centre_values.get("dither") or "jarvis").lower(),
                                               **{k: centre_values.get(k) for k in ("power", "min_power", "speed", "line_interval", "dot_width")}},
                                              step)
    if not isinstance(specs, list) or not VARIATION_MIN <= len(specs) <= VARIATION_MAX:
        raise su.ValidationError(f"provide {VARIATION_MIN} to {VARIATION_MAX} copies; each copy and scale use two LightBurn layers")
    variants = [_variant(raw, centre_values, passport, n) for n, raw in enumerate(specs, 1)]
    keys = [json.dumps(v, sort_keys=True) for v in variants]
    if len(set(keys)) != len(keys):
        raise su.ValidationError("identical settings cannot be compared; change one copy")
    try:
        copy_mm = float(supplied.get("copy_mm", VARIATION_DEFAULT_COPY_MM))
    except (TypeError, ValueError):
        raise su.ValidationError("copy size must be a number") from None
    lo, hi = VARIATION_COPY_MM
    if not (math.isfinite(copy_mm) and lo <= copy_mm <= hi):
        raise su.ValidationError(f"copy size (long side) must be from {lo:g} to {hi:g} mm")
    rows_px, cols_px = picture.shape[:2]
    width = copy_mm if cols_px >= rows_px else round(copy_mm * cols_px / rows_px, 2)
    height = copy_mm if rows_px > cols_px else round(copy_mm * rows_px / cols_px, 2)
    limit_px = round(copy_mm * VARIATION_PICTURE_PX_MM)
    if max(rows_px, cols_px) > limit_px:
        scale = limit_px / max(rows_px, cols_px)
        picture = cv2.resize(picture, (max(1, round(cols_px * scale)), max(1, round(rows_px * scale))), interpolation=cv2.INTER_AREA)
        if picture.ndim == 3:
            picture[..., 3] = np.where(picture[..., 3] >= 128, 255, 0)
    steps = max(6, min(grayscale.RAMP_STEPS, int(width / GREY_MIN_STEP)))
    greys = grayscale.ramp_greys(steps)
    centre = variants[0]                                  # the first copy: its label names every setting, the others what they change
    grid = variation_grid(width, height, len(variants), values.get("max_width_mm", PLATE_DEFAULT_MM))
    columns, rows, cell_h = grid["columns"], grid["rows"], grid["cell_h"]
    labels = _text("PHOTO VARIATIONS", 1.0, 0.6, 0.12)
    layers, cells, copies = [], [], []
    for n, variant in enumerate(variants, 1):
        col, row = (n - 1) % columns, (n - 1) // columns
        x, y = 1.0 + col * (width + VARIATION_GAP), VARIATION_TOP + row * (cell_h + VARIATION_GAP)
        label = f"{n} " + variation_label(variant, centre)
        labels += _text(label, x, y + 0.3, 0.10)
        params = {k: variant[k] for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")}
        params["min_power"] = variant["min_power"]
        if variant.get("dot_width") is not None:
            params["dot_width"] = variant["dot_width"]
        top = y + VARIATION_LABEL_H
        ramp_y = top + height + VARIATION_RAMP_GAP
        pic_name, ramp_name = f"PV{n}-PICTURE", f"PV{n}-RAMP"
        pic_layer = _layer(len(layers) + 1, pic_name, params, [_rect(x, top, width, height)], mode="Image",
                           line_interval=params["line_interval"], global_passes=values["global_passes"])
        pic_layer["picture"] = {"x": x, "y": top, "width": width, "height": height, "dither": variant["dither"], "file": f"{pic_name}.png",
                                "picture_key": "variation"}
        pic_layer["variation"] = {"copy": n, "part": "picture"}
        layers.append(pic_layer)
        ramp = {"x": x, "y": ramp_y, "width": width, "height": GREY_TILE_HEIGHT, "greys": greys, "dither": variant["dither"]}
        ramp_layer = _layer(len(layers) + 1, ramp_name, params, [_rect(x, ramp_y, width, GREY_TILE_HEIGHT)], mode="Image",
                            line_interval=params["line_interval"], global_passes=values["global_passes"])
        ramp_layer["ramp"] = ramp
        ramp_layer["variation"] = {"copy": n, "part": "ramp"}
        layers.append(ramp_layer)
        for name, part, ry, rh in ((pic_name, "picture", top, height), (ramp_name, "ramp", ramp_y, GREY_TILE_HEIGHT)):
            cells.append({"name": name, "parameters": params, "x": x, "y": ry, "width": width, "height": rh, "copy": n, "part": part,
                          "dither": variant["dither"], "min_power": variant["min_power"], "max_power": variant["power"]})
        copies.append({"copy": n, "label": label, "variant": variant, "picture_layer": pic_name, "ramp_layer": ramp_name,
                       "x": x, "y": top, "width": width, "height": height, "ramp": {"y": ramp_y, "height": GREY_TILE_HEIGHT, "steps": steps}})
    plate_w, plate_h = grid["width"], grid["height"]
    png = cv2.imencode(".png", picture)[1].tobytes()
    meta = {"name": str(supplied.get("picture_name") or "picture")[:120], "size_px": [int(picture.shape[1]), int(picture.shape[0])],
            "sha256": hashlib.sha256(png).hexdigest(), "transparent": picture.ndim == 3, "source": supplied.get("source")}
    return layers, labels, {"width": plate_w, "height": plate_h, "columns": columns, "rows": rows, "cells": cells,
                            "feature_count": len(variants) * (1 + steps),
                            "sample_area_mm2": round(len(variants) * width * (height + GREY_TILE_HEIGHT), 2),
                            "variations": {"copies": copies, "copy_mm": copy_mm, "width_mm": width, "height_mm": height,
                                           "picture": meta, "ramp_steps": steps, "step": step, "follows": supplied.get("follows")},
                            "pictures": {"variation": png}}


BUILDERS = {"small_patches": _small_patches, "compact_capability": _compact_capability, "text_readability": _text_readability, "calibration": _calibration, "power_speed": _power_speed, "frequency": _frequency,
            "pulse_cutoff": _pulse_cutoff, "line_resolution": _line_resolution, "hatch_interval": _hatch_interval,
            "offset_fill": _offset_fill, "wobble": _wobble, "material_matrix": _material_matrix, "grey_scales": _grey_scales,
            "fill_sizes": _fill_sizes, "photo_variations": _photo_variations}


def preview(store: Store, device_id: int, material_id: int, test_type: str, settings: dict | None = None) -> dict:
    """Build a test plate without saving a plate or plan."""
    if test_type not in BUILDERS:
        raise su.ValidationError("select an experiment plate type")
    device = devices.get_device(store, device_id)
    lens = device.get("lens")
    if not lens:
        raise su.ValidationError("first select the lens installed on this laser")
    material_row = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
    if material_row is None:
        raise su.ValidationError("select material with an actual grade or batch")
    if material_row["family"] != "Titanium":
        raise su.ValidationError("no cleaning recipe is set for this material; titanium cleaning cannot be used")
    values, clean, _ = _passport_defaults(device["passport"], settings or {})
    limits = {}
    for axis in ("width", "height"):
        try:
            limit = float((settings or {}).get(f"max_{axis}_mm", PLATE_DEFAULT_MM))
        except (TypeError, ValueError):
            raise su.ValidationError(f"maximum plate dimensions must be numbers from 1 to {PLATE_MAX_MM:g} mm") from None
        if not math.isfinite(limit) or not 1 <= limit <= PLATE_MAX_MM:
            raise su.ValidationError(f"maximum plate dimensions must be from 1 to {PLATE_MAX_MM:g} mm")
        limits[axis] = limit
        values[f"max_{axis}_mm"] = limit
    if test_type == "frequency":
        # The CW step lets the sweep reach the full repetition-rate range without crossing a pulse cutoff.
        cw = next((s for s in device["passport"]["pulse_steps"] if s["cutoff_khz"] is None), None)
        if cw:
            values["pulse_width"] = float(cw["pulse_width_ns"])
    if test_type in ("small_patches", "frequency", "pulse_cutoff", "calibration", "compact_capability", "material_matrix", "text_readability",
                     "grey_scales", "fill_sizes", "photo_variations"):
        layers, label_regions, geometry = BUILDERS[test_type](values, device["passport"])
    else:
        layers, label_regions, geometry = BUILDERS[test_type](values)
    if test_type == "material_matrix":
        values["matrix"] = geometry["matrix"]
    if test_type == "grey_scales":
        values["scales"] = geometry["scales"]
    if test_type == "fill_sizes":
        values["recipes"], values["widths_mm"] = geometry["fills"]["recipes"], geometry["fills"]["widths_mm"]
    pictures = geometry.pop("pictures", None)            # stored once beside the plan, never in the plate's geometry
    if test_type == "photo_variations":
        values["variations"] = {k: v for k, v in values["variations"].items() if k != "picture_png"} | {
            "variants": [c["variant"] for c in geometry["variations"]["copies"]], "picture": geometry["variations"]["picture"]}
    # REQ-020: every cell states its task (letters are text, the rest what their LightBurn mode implies), and the plate
    # records the task it was made for: the operator's choice, else its research goal, else what its test type examines
    for layer in layers:
        layer["task"] = tasks.plate_layer_task(layer["name"], layer.get("cut_type"))
    engraving_task = tasks.chosen_or_default(
        values.get("task"), tasks.plate_task(test_type, values.get("research_goal"), (values.get("matrix") or {}).get("geometry")),
        values.get("task_goals"))
    ident = plans.new_identifier("TCE")
    marked = test_type != "small_patches" or values.get("registration", "full") == "full"
    markers = plans.marker_geometry(ident, geometry["width"], geometry["height"], COMPACT_MARKER_SIZE) if marked else None
    total_w = markers["extent"]["max_x"] - markers["extent"]["min_x"] if markers else geometry["width"]
    total_h = markers["extent"]["max_y"] - markers["extent"]["min_y"] if markers else geometry["height"]
    clean_regions = None
    if test_type == "small_patches":
        # Cleaning is still first, but the laser need not raster over the empty space
        # separating tiny samples and registration marks.
        apron = 0.3
        clean_regions = [_rect(c["x"] - apron, c["y"] - apron,
                               c["width"] + 2 * apron, c["height"] + 2 * apron)
                         for c in geometry["cells"]]
        if markers:
            clean_regions += [_rect(m["x"], m["y"], m["size"], m["size"])
                              for m in markers["aruco"]]
            qr = markers["qr"]
            clean_regions.append(_rect(qr["x"], qr["y"], qr["size"], qr["size"]))
    if total_w > limits["width"] + 1e-6 or total_h > limits["height"] + 1e-6:
        raise su.ValidationError(f"this plate with markers occupies {total_w:.1f} × {total_h:.1f} mm; the specified limit is {limits['width']:g} × {limits['height']:g} mm")
    # the work field of the laser and its lens (the smaller of the lens field and the confirmed settings field); an
    # unknown field is reported as not checked, never as a fit (REQ-018)
    placement = plans.work_field_check({"device": device, "lens": lens}, total_w, total_h)
    if len(layers) + 1 + int(marked) > plans.MAX_LAYERS:
        raise su.ValidationError("this test has too many LightBurn layers")
    # C01, the system layer of the markers and the engraved labels, burns with the operator's marker-layer settings
    # (DEC-027); an unmarked plate has no such layer.
    marker_layer = (plans.marker_layer_for(store, device["passport"]) | {
        "name": "Markers and labels", "global_passes": 1, "bidirectional": False, "cross_hatch": False, "angle": 0.0,
        "angle_increment": 0.0}) if marked else None
    series = ({"identifier": values.get("series_identifier"), "part_index": values.get("part_index"),
               "part_count": values.get("part_count")}) if values.get("series_identifier") else None
    title = TYPE_BY_ID[test_type]["name"]
    if series:
        title += f" · part {series['part_index']}/{series['part_count']}"
    experiment = {"test_type": test_type, "test_name": title, "test_description": TYPE_BY_ID[test_type]["description"],
                  "device": {k: device.get(k) for k in ("id", "name", "manufacturer", "model", "serial", "title")},
                  "lens": {k: lens.get(k) for k in ("id", "name", "focal_length_mm", "field_mm", "expansion")},
                  "material": {k: material_row[k] for k in ("id", "name", "family", "grade", "batch", "thickness_mm", "surface")},
                  "test_settings": values, "cleanup_settings": clean, "label_settings": marker_layer, "series": series,
                  "research_goal": values.get("research_goal"), "source_pair_id": values.get("source_pair_id"),
                  "engraving_task": engraving_task,
                  "summary": {"layers": len(layers), "test_features": len(geometry["cells"]),
                              "visual_features": geometry.get("feature_count", len(geometry["cells"])),
                              "size_mm": {"width": round(total_w, 2), "height": round(total_h, 2)},
                              "limit_mm": limits, "work_field": placement, "registration": "full" if marked else "none",
                              "sample_area_mm2": geometry.get("sample_area_mm2"),
                              "clean_area_mm2": round(sum(r["width"] * r["height"] for r in clean_regions), 2)
                              if clean_regions is not None else round(total_w * total_h, 2)}}
    return {"device": device, "lens": lens, "material": dict(material_row), "identifier": ident,
            "layers": layers, "label_regions": label_regions, "geometry": geometry, "markers": markers,
            "clean_layer": clean | {"interval": clean["line_interval"], "global_passes": 1, "bidirectional": True,
                                    "cross_hatch": True, "angle": 0.0, "angle_increment": 0.0},
            "marker_layer": marker_layer, "clean_regions": clean_regions, "experiment": experiment,
            "values": values, "label_regions_count": len(label_regions), "pictures": pictures}


def _persist_prepared(store: Store, result: dict, device_id: int, material_id: int, test_type: str,
                      research_session_id: int | None = None, supersede_plan_id: int | None = None) -> dict:
    """Persist a prevalidated plate inside the caller's transaction."""
    device, lens = result["device"], result["lens"]
    ident, geometry, layers = result["identifier"], result["geometry"], result["layers"]
    title = result["experiment"]["test_name"]
    lens_snapshot = su.lens_snapshot({"device": device, "lens": lens})
    cells = geometry["cells"]
    if supersede_plan_id is not None:
        if research_session_id is None:
            raise su.ValidationError("a study is required to replace a plate")
        changed = store.execute(
            "UPDATE plan SET status='Superseded' WHERE id=? AND research_session_id=? "
            "AND status IN ('Ready to export','Exported') "
            "AND NOT EXISTS (SELECT 1 FROM pair WHERE plan_id=? AND status!='Deleted')",
            (supersede_plan_id, research_session_id, supersede_plan_id))
        if changed.rowcount != 1:
            raise su.ProtectedError("the plate has changed or has a linked photo; replacement canceled")
    plate_id = store.execute(
        "INSERT INTO plate(experiment_id,device_id,lens_id,speed,geometry_json,cells_json,proposal_id,lens_json,material_id,test_type,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ident, device["id"], lens["id"], result["values"]["speed"], json.dumps(geometry), json.dumps(cells), None,
         json.dumps(lens_snapshot) if lens_snapshot else None, material_id, test_type, now())).lastrowid
    plan_data = {"layers": layers, "markers": result["markers"], "marker_labels": result["label_regions"],
                 "clean_regions": result["clean_regions"], "lens": lens_snapshot,
                 "marker_layer": result["marker_layer"], "clean_layer": result["clean_layer"],
                 "export_mirror_y": True,
                 "experiment": result["experiment"], "test_type": test_type,
                 "engraving_task": result["experiment"]["engraving_task"],
                 "process_settings": {k: result["values"][k] for k in ("pulse_width", "line_interval", "passes")},
                 "lightburn_settings": {"global_passes": result["values"]["global_passes"], "bidirectional": True,
                                        "cross_hatch": False, "scan_angle": 0.0, "angle_increment": 0.0}}
    if result.get("pictures"):                          # a picture the plate engraves (photo_variations): a file of the workshop
        folder = store.data_dir / "files"
        folder.mkdir(parents=True, exist_ok=True)
        plan_data["pictures"] = {}
        for key, png in result["pictures"].items():
            path = folder / f"plate-{ident}-{key}.png"
            path.write_bytes(png)
            plan_data["pictures"][key] = str(path)
    plan_id = store.execute(
        "INSERT INTO plan(name,mode,status,device_id,lens_id,plate_id,markers,plan_identifier,band_count,data_json,created_at,research_session_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"{title} · {ident}", plans.MODE_CAPABILITY, "Ready to export", device["id"], lens["id"], plate_id,
         int(bool(result["markers"])), ident, len(layers), json.dumps(plan_data), now(), research_session_id)).lastrowid
    if supersede_plan_id is not None:
        store.audit("research_plate_superseded", session_id=research_session_id,
                    old_plan_id=supersede_plan_id, new_plan_id=plan_id)
    store.audit("capability_plate_created", plan_id=plan_id, plate_id=plate_id, device_id=device_id, lens_id=lens["id"],
                material_id=material_id, test_type=test_type, identifier=ident)
    return {"plan_id": plan_id, "plate_id": plate_id, "identifier": ident, "name": f"{title} · {ident}",
            "test_type": test_type, "summary": result["experiment"]["summary"], "experiment": result["experiment"]}


def create(store: Store, device_id: int, material_id: int, test_type: str, settings: dict | None = None,
           *, research_session_id: int | None = None, supersede_plan_id: int | None = None) -> dict:
    result = preview(store, device_id, material_id, test_type, settings)
    with store.transaction():
        return _persist_prepared(store, result, device_id, material_id, test_type,
                                 research_session_id, supersede_plan_id)


def create_variations(store: Store, device_id: int, material_id: int, picture: np.ndarray, px_per_mm: float, centre: dict, name: str,
                      source: dict, *, step: float = 1.0) -> dict:
    """A photo-variations plate of a photo engraving: the part of its file's picture with the most tone, at the scale it is engraved at
    (:func:`variation_window`), engraved at ``centre`` (the engraving's own settings) and at one change of a setting each
    (``photo_quality.variants_around``)."""
    window = variation_window(picture, px_per_mm)
    rows, cols = window.shape[:2]
    copy_mm = round(max(rows, cols) / px_per_mm, 2)
    lo, hi = VARIATION_COPY_MM
    if copy_mm < lo:
        raise su.ValidationError(f"the engraving is smaller than {lo:g} mm: too small to compare its copies")
    keys = ("power", "min_power", "speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes", "dither", "dot_width")
    settings = {k: centre[k] for k in keys if centre.get(k) is not None}
    settings["variations"] = {"picture_png": cv2.imencode(".png", window)[1].tobytes(), "copy_mm": min(hi, copy_mm), "picture_name": name,
                              "variants": photo_quality.variants_around(settings, step), "step": step, "source": source}
    return create(store, device_id, material_id, "photo_variations", settings)


def preview_small_patch_parts(store: Store, device_id: int, material_id: int, settings: dict) -> list[dict]:
    """Partition 1–4 samples into the fewest independent marked files that fit the limits."""
    patches = settings.get("patches")
    if patches is None:
        patches = [{}]
    if not isinstance(patches, list) or not 1 <= len(patches) <= 4:
        raise su.ValidationError("provide one to four squares with settings")
    prepared = []
    cursor = 0
    while cursor < len(patches):
        last_size_error = None
        for end in range(len(patches), cursor, -1):
            candidate = {**settings, "patches": patches[cursor:end]}
            try:
                part = preview(store, device_id, material_id, "small_patches", candidate)
            except su.ValidationError as exc:
                if str(exc).startswith("this plate with markers occupies"):
                    last_size_error = exc
                    continue
                raise
            prepared.append((cursor, end, part))
            cursor = end
            break
        else:
            raise last_size_error or su.ValidationError("even one square does not fit the requested size")
    return [{"sample_indexes": list(range(start + 1, end + 1)), "prepared": part,
             "settings": {**settings, "patches": patches[start:end]}}
            for start, end, part in prepared]


def create_small_patch_parts(store: Store, device_id: int, material_id: int, settings: dict) -> dict:
    parts = preview_small_patch_parts(store, device_id, material_id, settings)
    series_identifier = plans.new_identifier("TCE") if len(parts) > 1 else None
    prepared = []
    for index, part in enumerate(parts, 1):
        part_settings = {**part["settings"], "series_identifier": series_identifier,
                         "part_index": index, "part_count": len(parts)}
        prepared.append((part, preview(store, device_id, material_id, "small_patches", part_settings)))
    with store.transaction():
        created = [(_persist_prepared(store, plate, device_id, material_id, "small_patches"),
                    part["sample_indexes"]) for part, plate in prepared]
    return {"series_identifier": series_identifier,
            "parts": [{**record, "sample_indexes": indexes,
                       "download_url": f"/api/plans/{record['plan_id']}/export.lbrn2"}
                      for record, indexes in created]}
