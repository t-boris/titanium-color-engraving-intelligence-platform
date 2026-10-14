"""Synthetic rig photographs for tests: a ColorChecker, a rasterised plan and a colour cast.

Nothing here is a real photograph; it exercises the pipeline logic, not the physical rig.
"""
from __future__ import annotations

import cv2
import numpy as np

from titanium_platform import color
from titanium_platform import photo as ph


def chart_image(patch: int = 60, gap: int = 6, border: int = 14) -> np.ndarray:
    cw, ch = 6 * patch + 5 * gap + 2 * border, 4 * patch + 3 * gap + 2 * border
    img = np.full((ch, cw, 3), 25, np.uint8)
    for i, (r, g, b) in enumerate(ph.REFERENCE_SRGB.astype(int)):
        row, col = divmod(i, 6)
        x, y = border + col * (patch + gap), border + row * (patch + gap)
        img[y:y + patch, x:x + patch] = (b, g, r)
    return img


def cast(img_bgr: np.ndarray, gains=(0.85, 0.95, 1.1), gamma: float = 1.0) -> np.ndarray:
    """Apply a per-channel gain in linear light (a simple colour cast of the lighting)."""
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB) / 255.0
    lin = color.srgb_to_linear(rgb) * np.array(gains)
    out = color.linear_to_srgb(np.clip(lin, 0, 1) ** gamma)
    return cv2.cvtColor((out * 255).round().astype(np.uint8), cv2.COLOR_RGB2BGR)


def scene(width: int = 1500, height: int = 1000, chart_at=(60, 40), work_rgb=(120, 70, 200), work_box=(560, 80, 860, 880)) -> np.ndarray:
    """Grey background, a chart in a corner and a flat-coloured 'work' rectangle."""
    img = np.full((height, width, 3), (150, 155, 150), np.uint8)
    c = chart_image()
    x, y = chart_at
    img[y:y + c.shape[0], x:x + c.shape[1]] = c
    x0, y0, x1, y1 = work_box
    r, g, b = work_rgb
    img[y0:y1, x0:x1] = (b, g, r)
    return img


def plate_photo(plan: dict, cell_rgb: dict[str, tuple[int, int, int]], scale: float = 20.0, size=(1500, 1900),
                origin=(520, 80), chart_at=(40, 40), gains=None, with_chart: bool = True) -> np.ndarray:
    """Render a plate from its plan: white sheet, grey cells coloured per ``cell_rgb``, ArUco markers, QR.

    ``plan`` is an EngravingPlan with markers. The plan's own geometry is used, so a photo made from a plan
    and a LightBurn file exported from the same plan agree exactly.
    """
    h, w = size
    img = np.full((h, w, 3), (150, 155, 150), np.uint8)
    ext = plan["markers"]["extent"]
    ox, oy = origin
    px = lambda v: int(round(v))
    sx = lambda x: px((x - ext["min_x"]) * scale + ox)
    sy = lambda y: px((y - ext["min_y"]) * scale + oy)
    img[sy(ext["min_y"]) - 30:sy(ext["max_y"]) + 30, sx(ext["min_x"]) - 30:sx(ext["max_x"]) + 30] = 255
    for layer in plan["layers"]:
        r, g, b = cell_rgb.get(layer["cell_id"], (128, 128, 128))
        for reg in layer["regions"]:
            img[sy(reg["y"]):sy(reg["y"] + reg["height"]), sx(reg["x"]):sx(reg["x"] + reg["width"])] = (b, g, r)
    rects = [r for a in plan["markers"]["aruco"] for r in a["rects"]] + plan["markers"]["qr"]["rects"]
    for r in rects:
        img[sy(r["y"]):sy(r["y"] + r["height"]), sx(r["x"]):sx(r["x"] + r["width"])] = 0
    if with_chart:
        c = chart_image()
        cx, cy = chart_at
        img[cy:cy + c.shape[0], cx:cx + c.shape[1]] = c
    return cast(img, gains) if gains else img
