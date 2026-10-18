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

    ``plan`` is an EngravingPlan, a plate or any plan with rectangular regions: ``cell_rgb`` is keyed by a layer's cell id,
    else by its name. Without markers the sheet is the extent of the regions (cleaning areas included) and nothing else is
    drawn. The plan's own geometry is used, so a photo made from a plan and a LightBurn file exported from the same plan
    agree exactly.
    """
    h, w = size
    img = np.full((h, w, 3), (150, 155, 150), np.uint8)
    markers = plan.get("markers")
    ext = markers["extent"] if markers else extent(plan)
    ox, oy = origin
    px = lambda v: int(round(v))
    sx = lambda x: px((x - ext["min_x"]) * scale + ox)
    sy = lambda y: px((y - ext["min_y"]) * scale + oy)
    img[sy(ext["min_y"]) - 30:sy(ext["max_y"]) + 30, sx(ext["min_x"]) - 30:sx(ext["max_x"]) + 30] = 255
    for layer in plan["layers"]:
        r, g, b = cell_rgb.get(layer.get("cell_id", layer["name"]), (128, 128, 128))
        for reg in layer["regions"]:
            img[sy(reg["y"]):sy(reg["y"] + reg["height"]), sx(reg["x"]):sx(reg["x"] + reg["width"])] = (b, g, r)
    rects = [r for a in markers["aruco"] for r in a["rects"]] + markers["qr"]["rects"] if markers else []
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


def extent(plan: dict) -> dict:
    """The extent of an unmarked plan in its own millimetres: every region and cleaning area."""
    regions = [r for layer in plan["layers"] for r in layer["regions"]] + list(plan.get("clean_regions") or [])
    return {"min_x": min(r["x"] for r in regions), "min_y": min(r["y"] for r in regions),
            "max_x": max(r["x"] + r["width"] for r in regions), "max_y": max(r["y"] + r["height"] for r in regions)}


def work_corners(plan: dict, scale: float = 20.0, origin=(520, 80)) -> list[tuple[float, float]]:
    """The four corners (TL, TR, BR, BL) of an unmarked plan's extent in a ``plate_photo`` of it, in photo pixels."""
    ext = extent(plan)
    ox, oy = origin
    width, height = (ext["max_x"] - ext["min_x"]) * scale, (ext["max_y"] - ext["min_y"]) * scale
    return [(ox, oy), (ox + width, oy), (ox + width, oy + height), (ox, oy + height)]


# -- a framed finished work (REQ-024, DEC-048): a LightBurn file and a photograph that disagree like a real pair ----
def framed_work(seed: int = 3, hide_mm: float = 2.0, blobs: int = 45, layers: int = 12, size=(2000, 2700),
                px_per_mm: float = 9.5, rotate_deg: float = 1.2, mirror: bool = True, perspective=(2.0e-5, -1.5e-5),
                extra=(), concentric: bool = False, with_chart: bool = False, with_frame: bool = True, style: str = "regions",
                dark_layers=(), inset: float = 0.0) -> dict:
    """150 x 150 mm plate (file mm 10..160) with closed 'cloud' outlines on ``layers`` layers.

    The photograph shows the plate mirrored vertically, rotated, in perspective, inside a black frame that hides
    ``hide_mm`` of the plate on every side. ``extra`` adds (layer, polygon in mm) outlines; ``concentric`` replaces the
    clouds by nested squares, a drawing whose orientation cannot be told; ``dark_layers`` are engraved black, as dark
    as the frame; ``inset`` (mm) keeps the tiled regions away from the plate edge so that a ring of the cleaned plate
    stays visible. Returns the LightBurn bytes, the photograph, the true file-mm -> pixel matrix and the outlines.
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
    elif style == "strokes":             # rows of parallel slanted strokes of uneven length, like a low-poly lion's mane
        for row in range(blobs):
            y = 14 + row * 136 / blobs
            x = 12.0 + rng.uniform(0, 6)
            while x < 150:
                length = rng.uniform(4, 16)
                if x + length > 156:
                    break
                shapes.append((1 + (row * 3 + int(x)) % layers,
                               np.array([(x, y), (x + length, y), (x + length + 2.5, y + 3.2), (x + 2.5, y + 3.2)], float)))
                x += length + rng.uniform(1.5, 5)
    elif style == "clouds":              # overlapping outlines: many of them are painted over and cannot be seen
        theta = np.linspace(0, 2 * np.pi, 90, endpoint=False)
        for _ in range(blobs):
            centre, r0 = rng.uniform(22, 148, 2), rng.uniform(5, 15)
            r = r0 * (1 + sum(rng.uniform(0.02, 0.12) * np.cos(k * theta + rng.uniform(0, 6.28)) for k in range(2, 7)))
            shapes.append((int(rng.integers(1, layers + 1)), np.column_stack([centre[0] + r * np.cos(theta), centre[1] + r * np.sin(theta)])))
    else:                                 # touching regions, like a posterised picture: every outline is visible
        step = 0.25
        axis = 10 + inset + (np.arange(int((150 - 2 * inset) / step)) + 0.5) * step      # ``inset`` leaves a ring of clean plate
        gx, gy = np.meshgrid(axis, axis)
        seeds = rng.uniform(10 + inset, 160 - inset, (blobs, 2))
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
                shapes.append((layer_of[i], 10 + inset + (approx + 0.5) * step))
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
        colour = (12, 12, 12) if layer in dark_layers else palette[(layer - 1) % layers]      # black engraving, as dark as a frame
        cv2.fillPoly(work, [np.round(project(poly)).astype(np.int32)], colour, cv2.LINE_AA)
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


# -- a work engraved from a picture, photographed in a frame (REQ-027, DEC-054) -------------------------------------
def picture_work(seed: int = 4, margins_mm=(3.0, 7.0, 4.0, 3.0), size=(1900, 1500), px_per_mm: float = 9.0, rotate_deg: float = 1.5,
                 mirror: bool = True, perspective=(1.5e-5, -1.0e-5), min_power: float = 5.0, max_power: float = 16.0,
                 tonal: bool = True, with_chart: bool = False) -> dict:
    """A 150 x 150 mm grayscale-mode engraving (file mm 10..160) as a LightBurn file and a photograph.

    The picture is smoothed noise with a few shapes. The metal takes the colour of its grey level: darker grey = more power =
    darker, less coloured; lighter grey = less power = lighter and browner (as in the operator's work). A frame hides
    ``margins_mm`` (left, right, top, bottom). The photograph is mirrored vertically (the file's y is up), turned and in perspective.
    """
    import base64
    rng = np.random.default_rng(seed)
    n = 256
    base = cv2.resize(rng.random((16, 16)).astype(np.float32), (n, n), interpolation=cv2.INTER_CUBIC)
    base = cv2.GaussianBlur(base, (0, 0), 2.0)
    for _ in range(14):
        cx, cy, r = rng.integers(20, n - 20, 2).tolist() + [int(rng.integers(8, 40))]
        cv2.circle(base, (cx, cy), r, float(rng.random()), -1)
    base = cv2.GaussianBlur(base, (0, 0), 1.2)
    gray = (base - base.min()) / (base.max() - base.min())
    png = cv2.imencode(".png", (gray * 255).astype(np.uint8))[1].tobytes()
    data = base64.b64encode(png).decode()
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="1.7.01" DeviceName="JPT MOPA M7 60W">'
           f'<CutSetting_Img type="Image"><index Value="0"/><name Value="C00"/><minPower Value="{min_power}"/><maxPower Value="{max_power}"/>'
           f'<maxPower2 Value="20"/><speed Value="128"/><frequency Value="60000"/><QPulseWidth Value="300"/><interval Value="0.0169"/>'
           f'<ditherMode Value="grayscale"/><dpi Value="1503"/></CutSetting_Img>'
           f'<Shape Type="Bitmap" CutIndex="0" W="150" H="150" Gamma="1" Contrast="0" Brightness="0" EnhanceAmount="0" EnhanceRadius="0" '
           f'EnhanceDenoise="0" File="/x/portrait.png" SourceHash="0" Data="{data}"><XForm>1 0 0 1 85 85</XForm></Shape>'
           f'<Notes ShowOnLoad="0" Notes=""/></LightBurnProject>').encode()

    # the colour the metal takes at each grey level (Lab, camera-relative and dark like the real photographs)
    lightness = (8 + 30 * gray) if tonal else np.full_like(gray, 20)
    lab = np.dstack([lightness, 1.5 - 3.0 * gray, 7.0 * gray]).astype(np.float32)
    colour = cv2.cvtColor(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB), cv2.COLOR_RGB2BGR)
    height, width = size
    th = np.deg2rad(rotate_deg)
    lin = px_per_mm * np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]]) @ np.diag([1, -1 if mirror else 1])
    affine = np.eye(3)
    affine[:2, :2] = lin
    affine[:2, 2] = -lin @ [85.0, 85.0]
    persp = np.array([[1, 0, 0], [0, 1, 0], [perspective[0], perspective[1], 1.0]])
    mm_to_px = np.array([[1, 0, 0.5 * width], [0, 1, 0.5 * height], [0, 0, 1.0]]) @ persp @ affine
    step = 150.0 / n
    picture_to_px = mm_to_px @ np.array([[step, 0, 10.0], [0, step, 10.0], [0, 0, 1.0]])
    img = np.full((height, width, 3), (150, 155, 150), np.uint8)
    plate = cv2.warpPerspective(np.full((n, n), 255, np.uint8), picture_to_px, (width, height)) > 127
    img[plate] = (175, 170, 168)                                     # the bright brushed lip of the frame
    left, right, top, bottom = (m / step for m in margins_mm)
    window = np.zeros((n, n), np.uint8)
    window[int(round(top)):n - int(round(bottom)), int(round(left)):n - int(round(right))] = 255
    inside = cv2.warpPerspective(window, picture_to_px, (width, height)) > 127
    engraved = cv2.warpPerspective(colour, picture_to_px, (width, height), flags=cv2.INTER_LINEAR)
    img[inside] = (engraved[inside] * 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 1.0)
    img = np.clip(img.astype(np.int16) + rng.normal(0, 1.5, img.shape).astype(np.int16), 0, 255).astype(np.uint8)
    if with_chart:
        c = chart_image()
        img[40:40 + c.shape[0], 30:30 + c.shape[1]] = c
    return {"lightburn": xml, "photo": img, "picture_to_px": picture_to_px, "mm_to_px": mm_to_px, "gray": gray, "png": png,
            "margins_mm": margins_mm, "picture_size": n}


# -- a photographed LightBurn Material Test (REQ-031) -----------------------------------------------------------------
def material_test(cols: int = 6, rows: int = 5, pitch: int = 90, gap: int = 12, x_values=None, y_values=None,
                  x_title: str = "Power (%)", y_title: str = "Speed (mm/s)",
                  header=("Interval: 0.0030 mm  Passes: 1", "Frequency: 330.0 KHz  Q-Pulse: 4.00 ns"),
                  rotate_deg: float = 1.0, exposure: float = 1.0, size=(1500, 1300), seed: int = 2) -> dict:
    """A plate with a grid of filled squares, its row labels left of it, its column labels under it (rotated, reading
    upwards), the fixed settings above it and the axis titles, as LightBurn's Material Test prints them; a reference
    chart beside it. ``exposure`` < 1 darkens the whole photograph in linear light (an under-exposed shot). Returns the
    photograph, the true cell centres (photo px, [row][col]) and the values."""
    x_values = list(x_values or np.linspace(25, 50, cols).round(1))
    y_values = list(y_values or np.linspace(1500, 300, rows).round(0))
    rng = np.random.default_rng(seed)
    height, width = size
    plate = np.full((height, width, 3), (178, 182, 186), np.uint8)
    x0, y0 = 330, 230
    font = cv2.FONT_HERSHEY_SIMPLEX
    dark = (40, 40, 44)
    for k, line in enumerate(header):
        (tw, th), _ = cv2.getTextSize(line, font, 0.9, 2)
        cv2.putText(plate, line, (x0 + (cols * pitch - tw) // 2, y0 - 95 + 40 * k), font, 0.9, dark, 2, cv2.LINE_AA)
    centres = []
    for r in range(rows):
        row = []
        for c in range(cols):
            hue = int(180 * ((0.13 * c + 0.21 * r) % 1.0))
            colour = cv2.cvtColor(np.uint8([[[hue, int(60 + 30 * c), int(200 - 15 * r)]]]), cv2.COLOR_HSV2BGR)[0, 0]
            cx, cy = x0 + c * pitch + pitch // 2, y0 + r * pitch + pitch // 2
            half = (pitch - gap) // 2
            cv2.rectangle(plate, (cx - half, cy - half), (cx + half, cy + half), tuple(int(v) for v in colour), -1)
            row.append((cx, cy))
        centres.append(row)
        label = f"{y_values[r]:g}" if float(y_values[r]).is_integer() else f"{y_values[r]}"
        (tw, th), _ = cv2.getTextSize(label, font, 1.0, 2)
        cv2.putText(plate, label, (x0 - 14 - tw, y0 + r * pitch + pitch // 2 + th // 2), font, 1.0, dark, 2, cv2.LINE_AA)
    for c in range(cols):
        label = f"{x_values[c]:.1f}"
        (tw, th), _ = cv2.getTextSize(label, font, 1.0, 2)
        strip = np.full((th + 14, tw + 10, 3), (178, 182, 186), np.uint8)
        cv2.putText(strip, label, (5, th + 5), font, 1.0, dark, 2, cv2.LINE_AA)
        strip = cv2.rotate(strip, cv2.ROTATE_90_COUNTERCLOCKWISE)            # reads upwards, as LightBurn prints it
        sx, sy = x0 + c * pitch + pitch // 2 - strip.shape[1] // 2, y0 + rows * pitch + 10
        plate[sy:sy + strip.shape[0], sx:sx + strip.shape[1]] = strip
    (tw, th), _ = cv2.getTextSize(x_title, font, 0.9, 2)
    cv2.putText(plate, x_title, (x0 + (cols * pitch - tw) // 2, y0 + rows * pitch + 150), font, 0.9, dark, 2, cv2.LINE_AA)
    (tw, th), _ = cv2.getTextSize(y_title, font, 0.8, 2)
    strip = np.full((th + 14, tw + 10, 3), (178, 182, 186), np.uint8)
    cv2.putText(strip, y_title, (5, th + 5), font, 0.8, dark, 2, cv2.LINE_AA)
    strip = cv2.rotate(strip, cv2.ROTATE_90_COUNTERCLOCKWISE)
    plate[y0 + (rows * pitch - strip.shape[0]) // 2:y0 + (rows * pitch - strip.shape[0]) // 2 + strip.shape[0], x0 - 165 - strip.shape[1]:x0 - 165] = strip
    chart = chart_image()
    plate[height - chart.shape[0] - 30:height - 30, width - chart.shape[1] - 30:width - 30] = chart
    # turn the whole photograph a little about the grid's centre, blur, noise, exposure
    centre = (x0 + cols * pitch / 2, y0 + rows * pitch / 2)
    turn = cv2.getRotationMatrix2D(centre, rotate_deg, 1.0)
    img = cv2.warpAffine(plate, turn, (width, height), flags=cv2.INTER_LINEAR, borderValue=(178, 182, 186))
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    img = np.clip(img.astype(np.int16) + rng.normal(0, 1.5, img.shape).astype(np.int16), 0, 255).astype(np.uint8)
    if exposure != 1.0:
        lin = color.srgb_to_linear(img / 255.0) * exposure
        img = (color.linear_to_srgb(np.clip(lin, 0, 1)) * 255).round().astype(np.uint8)
    pts = np.array([[p for p in row] for row in centres], float).reshape(-1, 2)
    turned = (np.c_[pts, np.ones(len(pts))] @ turn.T).reshape(rows, cols, 2)
    return {"photo": img, "centres": turned, "x_values": x_values, "y_values": y_values, "cols": cols, "rows": rows, "pitch": pitch}
