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
