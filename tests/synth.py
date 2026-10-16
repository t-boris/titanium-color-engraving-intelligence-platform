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
                origin=(520, 80), chart_at=None, gains=None, with_chart: bool = True) -> np.ndarray:
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
        if chart_at is None:   # park the chart in the free strip left of the plate, never over a marker
            chart_at = (max(0, min(40, ox - c.shape[1] - 40)), 40)
        cx, cy = chart_at
        # the white sheet starts 30 px left of the leftmost marker; a chart drawn over a marker silently breaks detection
        assert cx + c.shape[1] <= ox - 30, f"the chart (right edge {cx + c.shape[1]} px) would cover the plate that starts at {ox - 30} px: move the origin right"
        img[cy:cy + c.shape[0], cx:cx + c.shape[1]] = c
    return cast(img, gains) if gains else img


# -- a framed finished work (REQ-024, DEC-048): a LightBurn file and a photograph that disagree like a real pair ----
def framed_work(seed: int = 3, hide_mm: float = 2.0, blobs: int = 45, layers: int = 12, size=(2000, 2700),
                px_per_mm: float = 9.5, rotate_deg: float = 1.2, mirror: bool = True, perspective=(2.0e-5, -1.5e-5),
                extra=(), concentric: bool = False, with_chart: bool = False, with_frame: bool = True, style: str = "regions") -> dict:
    """150 x 150 mm plate (file mm 10..160) with closed 'cloud' outlines on ``layers`` layers.

    The photograph shows the plate mirrored vertically, rotated, in perspective, inside a black frame that hides
    ``hide_mm`` of the plate on every side. ``extra`` adds (layer, polygon in mm) outlines; ``concentric`` replaces the
    clouds by nested squares, a drawing whose orientation cannot be told. Returns the LightBurn bytes, the photograph,
    the true file-mm -> pixel matrix and the outlines.
    """
    rng = np.random.default_rng(seed)
    palette = []
    for i in range(layers):
        hsv = np.uint8([[[int(180 * ((i * 0.381) % 1.0)), int(rng.uniform(120, 230)), int(rng.uniform(120, 235))]]])
        palette.append(tuple(int(v) for v in cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]))
    shapes: list[tuple[int, np.ndarray]] = []
    if concentric:
        for k in range(1, 13):
            half = 6.0 * k
            shapes.append((1 + k % layers, np.array([(85 - half, 85 - half), (85 + half, 85 - half),
                                                     (85 + half, 85 + half), (85 - half, 85 + half)], float)))
    elif style == "none":                # only what ``extra`` adds
        pass
    elif style == "clouds":              # overlapping outlines: many of them are painted over and cannot be seen
        theta = np.linspace(0, 2 * np.pi, 90, endpoint=False)
        for _ in range(blobs):
            centre, r0 = rng.uniform(22, 148, 2), rng.uniform(5, 15)
            r = r0 * (1 + sum(rng.uniform(0.02, 0.12) * np.cos(k * theta + rng.uniform(0, 6.28)) for k in range(2, 7)))
            shapes.append((int(rng.integers(1, layers + 1)), np.column_stack([centre[0] + r * np.cos(theta), centre[1] + r * np.sin(theta)])))
    else:                                 # touching regions, like a posterised picture: every outline is visible
        step = 0.25
        axis = 10 + (np.arange(int(150 / step)) + 0.5) * step
        gx, gy = np.meshgrid(axis, axis)
        seeds = rng.uniform(10, 160, (blobs, 2))
        label = np.argmin((gx[..., None] - seeds[:, 0]) ** 2 + (gy[..., None] - seeds[:, 1]) ** 2, axis=2)
        neighbours = {i: set() for i in range(blobs)}
        for a, b in ((label[:, :-1], label[:, 1:]), (label[:-1], label[1:])):
            for i, j in set(zip(a[a != b].tolist(), b[a != b].tolist())):
                neighbours[i].add(j); neighbours[j].add(i)
        layer_of: dict[int, int] = {}
        for i in sorted(neighbours, key=lambda k: -len(neighbours[k])):
            used = {layer_of[j] for j in neighbours[i] if j in layer_of}
            layer_of[i] = next((k for k in range(1, layers + 1) if k not in used), 1 + i % layers)
        for i in range(blobs):
            contours, _ = cv2.findContours((label == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if not contours:
                continue
            contour = max(contours, key=cv2.contourArea)
            approx = cv2.approxPolyDP(contour, 0.8, True).reshape(-1, 2)
            if len(approx) >= 3 and cv2.contourArea(approx.astype(np.float32)) * step ** 2 > 4:
                shapes.append((layer_of[i], 10 + (approx + 0.5) * step))
    shapes += [(int(layer), np.asarray(poly, float)) for layer, poly in extra]
    shapes.sort(key=lambda item: item[0])

    cut = "".join(f'<CutSetting type="Scan"><index Value="{i}"/><name Value="C{i:02d}"/><maxPower Value="50"/><speed Value="{1000 + 50 * i}"/>'
                  f'<frequency Value="48000"/><QPulseWidth Value="4"/><interval Value="0.005"/></CutSetting>' for i in range(layers + 1))
    body = '<Shape Type="Rect" CutIndex="0" W="150" H="150" Cr="0"><XForm>1 0 0 1 85 85</XForm></Shape>'
    for layer, poly in shapes:
        n = len(poly)
        verts = "".join(f"V{x:.5f} {y:.5f}c0x1c1x1" for x, y in poly)
        prims = "".join(f"L{i} {(i + 1) % n}" for i in range(n))
        body += (f'<Shape Type="Path" CutIndex="{layer}"><XForm>1 0 0 1 0 0</XForm><VertList>{verts}</VertList>'
                 f'<PrimList>{prims}</PrimList></Shape>')
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="2.1.04" DeviceName="JPT MOPA M7 60W">'
           f'{cut}{body}<Notes ShowOnLoad="0" Notes=""/></LightBurnProject>').encode()

    height, width = size
    th = np.deg2rad(rotate_deg)
    lin = px_per_mm * np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]]) @ np.diag([1, -1 if mirror else 1])
    affine = np.eye(3)
    affine[:2, :2] = lin
    affine[:2, 2] = -lin @ [85.0, 85.0]
    persp = np.array([[1, 0, 0], [0, 1, 0], [perspective[0], perspective[1], 1.0]])
    centre = np.array([[1, 0, 0.62 * width], [0, 1, 0.5 * height], [0, 0, 1.0]])
    mm_to_px = centre @ persp @ affine

    def project(poly):
        return cv2.perspectiveTransform(np.asarray(poly, np.float32)[None], mm_to_px)[0]

    work = np.full((height, width, 3), (150, 155, 150), np.uint8)       # the table, also where there is no frame
    cv2.fillConvexPoly(work, np.round(project([(10, 10), (160, 10), (160, 160), (10, 160)])).astype(np.int32), (190, 195, 200))
    for layer, poly in shapes:
        cv2.fillPoly(work, [np.round(project(poly)).astype(np.int32)], palette[(layer - 1) % layers], cv2.LINE_AA)
    img = np.full((height, width, 3), (150, 155, 150), np.uint8)
    if with_frame:
        cv2.fillConvexPoly(img, np.round(project([(0, 0), (170, 0), (170, 170), (0, 170)])).astype(np.int32), (14, 14, 14))
        aperture = np.zeros((height, width), np.uint8)
        a, b = 10 + hide_mm, 160 - hide_mm
        cv2.fillConvexPoly(aperture, np.round(project([(a, a), (b, a), (b, b), (a, b)])).astype(np.int32), 1)
        img[aperture > 0] = work[aperture > 0]
    else:
        img = work
    img = cv2.GaussianBlur(img, (0, 0), 1.0)
    img = np.clip(img.astype(np.int16) + rng.normal(0, 2, img.shape).astype(np.int16), 0, 255).astype(np.uint8)
    if with_chart:
        c = chart_image()
        img[1500:1500 + c.shape[0], 120:120 + c.shape[1]] = c
    return {"lightburn": xml, "photo": img, "mm_to_px": mm_to_px, "shapes": shapes, "palette": palette, "hide_mm": hide_mm}
