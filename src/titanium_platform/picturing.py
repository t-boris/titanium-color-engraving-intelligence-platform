"""Register the photograph of a work engraved from a picture to the picture stored in its LightBurn file (REQ-027, DEC-054).

A photo engraving has no outlines to match: its file holds one image object. The picture itself is the landmark. The
silhouettes of the picture (where its tones change) are looked for on the photograph, in all three channels of Lab
because the engraved colour often carries more of the picture than the lightness does.

1. the 8 orientations of the picture (four rotations, with and without mirror; a LightBurn file may be a mirror image
   of the photograph) and a grid of sizes and positions are scored by the correlation of the two edge maps at low
   resolution;
2. the best candidate of the two best orientations is refined with ECC (a homography) from coarse to fine;
3. the result is refused unless the match is clearly better than any other orientation;
4. the edges of the visible window (the inner edge of a frame that covers part of the picture) are found from the
   step of the median profile along each side, and the margins hidden by the frame are reported.

Nothing is guessed: a registration that is not supported by the data is refused with a reason in ``diagnostics`` and the
operator places four corners (REQ-013).
"""
from __future__ import annotations

import cv2
import numpy as np

from . import photo as ph
from .registration import Registration

WORK_LONG_SIDE = 1200      # photograph, working resolution
PICTURE = 512              # picture resolution used for the final correlation
MIN_ZNCC = 0.25            # correlation of the edge maps after refinement
MIN_MARGIN = 1.4           # the best orientation must beat the second by this factor
SCALES = (0.8, 0.9, 1.0, 1.1)
SHIFTS_ALONG = (-0.12, -0.06, 0.0, 0.06)
SHIFTS_ACROSS = (-0.05, 0.0, 0.05)
BAND = 0.15                # share of the picture inspected for the edge of the window, per side
FALLBACK_INSET = 0.06      # assumed hidden share per side when no edge of a window is found


def _structure(lab: np.ndarray, sigma: float) -> np.ndarray:
    """Edge strength over the three Lab channels, each normalised by its own robust spread."""
    total = np.zeros(lab.shape[:2], np.float32)
    for c in range(3):
        ch = cv2.GaussianBlur(lab[:, :, c], (0, 0), sigma)
        spread = max(float(np.percentile(ch, 95) - np.percentile(ch, 5)), 1e-6)
        ch = ch / spread
        total += cv2.Sobel(ch, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(ch, cv2.CV_32F, 0, 1) ** 2
    return np.sqrt(total)


def _zncc(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def _picture_structure(gray: np.ndarray, size: int, sigma: float) -> np.ndarray:
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    return _structure(np.dstack([small, np.zeros_like(small), np.zeros_like(small)]), sigma)


def _warp_photo(lab: np.ndarray, m: np.ndarray, size: int) -> np.ndarray:
    """The photograph laid into picture space: picture pixel x takes the photo at m x."""
    return np.dstack([cv2.warpPerspective(lab[:, :, c], m, (size, size), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_AREA)
                      for c in range(3)])


def _candidates(width: int, height: int):
    side = float(min(width, height))
    for mirror in (False, True):
        for rotation in range(4):
            for scale in SCALES:
                for along in SHIFTS_ALONG:
                    for across in SHIFTS_ACROSS:
                        dx, dy = (across * width, along * height) if height >= width else (along * width, across * height)
                        cx, cy, half = width / 2 + dx, height / 2 + dy, side * scale / 2
                        quad = np.float32([[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half], [cx - half, cy + half]])
                        quad = quad[::-1] if mirror else quad
                        yield (mirror, rotation), np.roll(quad, -rotation, axis=0)


def _refine(lab: np.ndarray, gray: np.ndarray, m: np.ndarray) -> np.ndarray:
    """ECC homography from coarse to fine; ``m`` and the result map picture pixels (PICTURE units) to photo pixels."""
    for size, sigma in ((128, 1.0), (256, 1.4), (PICTURE, 1.8)):
        f = size / PICTURE
        m_n = m @ np.diag([1 / f, 1 / f, 1.0])
        template = _picture_structure(gray, size, sigma)
        moving = _structure(_warp_photo(lab, m_n, size), sigma)
        template, moving = template / max(template.max(), 1e-6), moving / max(moving.max(), 1e-6)
        warp = np.eye(3, dtype=np.float32)
        try:
            _, warp = cv2.findTransformECC(template, moving, warp, cv2.MOTION_HOMOGRAPHY,
                                           (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 120, 1e-6), None, 5)
        except cv2.error:
            continue
        m = m_n @ warp @ np.diag([f, f, 1.0])
    return m


def _hidden_margins(lab: np.ndarray, m: np.ndarray) -> dict:
    """Share of the picture covered on each side: outside the photograph, then the step of the frame's inner edge."""
    size = PICTURE
    lightness = cv2.warpPerspective(lab[:, :, 0], m, (size, size), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_AREA)
    valid = cv2.warpPerspective(np.ones(lab.shape[:2], np.float32), m, (size, size), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_AREA) > 0.98
    band = int(size * BAND)
    out = {}
    mid = slice(int(size * 0.15), int(size * 0.85))
    sides = {"left": (lightness[mid, :band], valid[mid, :band]), "right": (lightness[mid, ::-1][:, :band], valid[mid, ::-1][:, :band]),
             "top": (lightness[:band, mid].T, valid[:band, mid].T), "bottom": (lightness[::-1][:band, mid].T, valid[::-1][:band, mid].T)}
    for name, (values, ok) in sides.items():            # rows: along the side, columns: distance from the edge inwards
        columns = ok.mean(axis=0) > 0.9
        cover = int(np.argmax(columns)) if columns.any() else band
        profile = np.array([np.median(values[:, i][ok[:, i]]) if ok[:, i].any() else np.nan for i in range(band)], np.float32)
        start = max(cover, 2)
        usable = profile[start:]
        if len(usable) < 20 or not np.isfinite(usable).all():
            out[name] = {"share": cover / size, "edge_found": False}
            continue
        # the edge of the window is a step of the median level: compare the 6 pixels before with the 6 after
        jump = np.array([abs(float(np.mean(usable[i + 1:i + 7])) - float(np.mean(usable[i - 5:i + 1]))) for i in range(5, len(usable) - 6)])
        i = int(np.argmax(jump))
        spread = float(np.max(usable) - np.min(usable))
        significant = jump[i] >= max(2.0, 0.35 * spread)
        out[name] = {"share": (start + 5 + i + 1) / size if significant else cover / size, "edge_found": bool(significant)}
    return out


def register(img_bgr: np.ndarray, layers: list, diagnostics: dict | None = None) -> Registration | None:
    """Align the photograph to the picture of the largest image object of ``layers``; None when it is not supported."""
    diag = diagnostics if diagnostics is not None else {}

    def refuse(reason: str):
        diag["refused"] = reason
        return None

    bitmaps = [r for layer in layers for r in layer.regions if r.bitmap and r.bitmap.get("png")]
    if not bitmaps:
        return refuse("the file holds no picture to match")
    region = max(bitmaps, key=lambda r: r.width * r.height)
    from .ingest import _picture_gray                  # the same decoding as for the tonal profile
    gray = _picture_gray(region.bitmap["png"])
    if gray is None or float(np.ptp(gray)) < 0.05:
        return refuse("the picture of the file has no tones to match")

    h0, w0 = img_bgr.shape[:2]
    s = WORK_LONG_SIDE / max(h0, w0)
    small = cv2.resize(ph.decoded_srgb(img_bgr).astype(np.float32), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB)
    height, width = lab.shape[:2]
    corners = np.float32([[0, 0], [PICTURE, 0], [PICTURE, PICTURE], [0, PICTURE]])
    tmpl = _picture_structure(gray, 128, 1.0)

    corners_coarse = np.float32([[0, 0], [128, 0], [128, 128], [0, 128]])
    best_per_orientation: dict = {}
    for key, quad in _candidates(width, height):
        coarse = _warp_photo(lab, cv2.getPerspectiveTransform(corners_coarse, quad), 128)
        score = _zncc(tmpl, _structure(coarse, 1.0))
        if score > best_per_orientation.get(key, (-1, None))[0]:
            best_per_orientation[key] = (score, cv2.getPerspectiveTransform(corners, quad))
    ranked = sorted(best_per_orientation.items(), key=lambda kv: -kv[1][0])
    refined = []
    for key, (score, m) in ranked[:2]:
        mm = _refine(lab, gray, m)
        final = _zncc(_picture_structure(gray, PICTURE, 1.8), _structure(_warp_photo(lab, mm, PICTURE), 1.8))
        refined.append((final, key, mm))
    refined.sort(key=lambda r: -r[0])
    best, key, m = refined[0]
    second = refined[1][0] if len(refined) > 1 else 0.0
    diag["zncc"] = round(best, 3)
    diag["second_orientation_zncc"] = round(second, 3)
    if best < MIN_ZNCC:
        return refuse("the picture of the file does not match the photograph closely enough")
    if second > 0 and best < MIN_MARGIN * second:
        return refuse("the orientation of the picture is ambiguous: another orientation matches almost as well")

    # picture (PICTURE units) -> photo (original pixels) and -> file mm
    to_photo = np.diag([1 / s, 1 / s, 1.0]) @ m
    bm = region.bitmap
    a, b, c, d, e, f = bm["matrix"]
    local_to_mm = np.array([[a, c, e], [b, d, f], [0, 0, 1.0]])
    picture_to_local = np.array([[bm["w"] / PICTURE, 0, -bm["w"] / 2], [0, bm["h"] / PICTURE, -bm["h"] / 2], [0, 0, 1.0]])
    picture_to_mm = local_to_mm @ picture_to_local
    image_to_mm = picture_to_mm @ np.linalg.inv(to_photo)
    px_per_mm = float(np.sqrt(abs(np.linalg.det(np.linalg.inv(image_to_mm)[:2, :2]))))

    margins = _hidden_margins(lab, m)
    found = all(v["edge_found"] for v in margins.values())
    inset = {k: (v["share"] if v["edge_found"] else max(v["share"], FALLBACK_INSET)) for k, v in margins.items()}
    lo_x, hi_x, lo_y, hi_y = inset["left"] * PICTURE, PICTURE * (1 - inset["right"]), inset["top"] * PICTURE, PICTURE * (1 - inset["bottom"])
    window = cv2.perspectiveTransform(np.float32([[[lo_x, lo_y], [hi_x, lo_y], [hi_x, hi_y], [lo_x, hi_y]]]), to_photo)[0]
    size_mm = float(max(bm["w"], bm["h"]) * np.sqrt(abs(np.linalg.det(local_to_mm[:2, :2]))))
    details = {"zncc": round(best, 3), "second_orientation_zncc": round(second, 3), "px_per_mm": round(px_per_mm, 3),
               "orientation": {"mirror": bool(key[0]), "rotation_degrees": 90 * int(key[1])},
               "window_found": bool(found), "window_px": window.round(1).tolist(),
               "hidden_mm": {k: round(v * size_mm, 1) for k, v in inset.items()}, "hidden_share": {k: round(v, 4) for k, v in inset.items()}}
    reflected = bool(np.linalg.det(image_to_mm[:2, :2]) < 0)
    diag["details"] = details
    return Registration(image_to_mm, "picture", [], round(1.0 - best, 3), reflected, details=details)
