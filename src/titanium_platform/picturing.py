"""Register the photograph of a work engraved from a picture to the picture stored in its LightBurn file (REQ-027, DEC-054).

A photo engraving has no outlines to match: its file holds one image object. The picture itself is the landmark. The
silhouettes of the picture (where its tones change) are looked for on the photograph, in all three channels of Lab
because the engraved colour often carries more of the picture than the lightness does.

1. the edges of the picture, each with its direction, are searched in a small copy of the photograph over every pose
   (mirror, four right angles with small offsets, the picture's scale from 0.3 to 1.5 of the photograph, every
   shift) by the same direction-aware correlation as the element anchoring of vector works (``anchoring.global_search``);
   a LightBurn file may be a mirror image of the photograph;
2. the best pose of each of the best few orientations is refined with ECC (a homography) from coarse to fine;
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
REFINE_TOP = 4             # poses of the global search (best per orientation) refined with ECC; the coarse ranking is weak
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


def _picture_samples(gray: np.ndarray, picture_to_mm: np.ndarray, n: int = 4000) -> tuple[np.ndarray, np.ndarray]:
    """Edge samples of the picture (file mm) with their tangent directions: the landmarks the photograph is searched for."""
    size = gray.shape[0]
    g8 = (np.clip(gray, 0, 1) * 255).astype(np.uint8)
    edges = cv2.Canny(cv2.GaussianBlur(g8, (0, 0), 1.0), 40, 100)
    gx = cv2.Sobel(g8.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g8.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    ys, xs = np.nonzero(edges)
    if len(xs) == 0:
        return np.zeros((0, 2)), np.zeros((0, 2))
    pick = np.random.default_rng(0).choice(len(xs), min(len(xs), n), replace=False)
    ys, xs = ys[pick], xs[pick]
    tangent = np.column_stack([-gy[ys, xs], gx[ys, xs]])
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1), 1e-6)[:, None]
    points = np.c_[np.column_stack([xs, ys]).astype(float) * (PICTURE / size), np.ones(len(xs))] @ picture_to_mm.T
    tangent_mm = tangent @ picture_to_mm[:2, :2].T
    tangent_mm /= np.maximum(np.linalg.norm(tangent_mm, axis=1), 1e-6)[:, None]
    return points[:, :2], tangent_mm


MAX_PERSPECTIVE = 0.05     # opposite sides of the picture may differ by this share in the photograph (the camera is nearly frontal)


def _ecc(lab: np.ndarray, gray: np.ndarray, m: np.ndarray, size: int, sigma: float, motion: int) -> np.ndarray:
    """One ECC step at ``size``: ``m`` and the result map picture pixels (PICTURE units) to photo pixels."""
    f = size / PICTURE
    m_n = m @ np.diag([1 / f, 1 / f, 1.0])
    template = _picture_structure(gray, size, sigma)
    moving = _structure(_warp_photo(lab, m_n, size), sigma)
    template, moving = template / max(template.max(), 1e-6), moving / max(moving.max(), 1e-6)
    warp = np.eye(2, 3, dtype=np.float32) if motion == cv2.MOTION_AFFINE else np.eye(3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(template, moving, warp, motion,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-6), None, 5)
    except cv2.error:
        return m
    if warp.shape == (2, 3):
        warp = np.vstack([warp, [0, 0, 1]]).astype(np.float32)
    return m_n @ warp @ np.diag([f, f, 1.0])


def _perspective(m: np.ndarray) -> float:
    """How unequal opposite sides of the picture are in the photograph (0 for a parallel projection)."""
    q = cv2.perspectiveTransform(np.float32([[[0, 0], [PICTURE, 0], [PICTURE, PICTURE], [0, PICTURE]]]), m)[0]
    side = lambda i, j: float(np.linalg.norm(q[i] - q[j]))
    return max(abs(side(0, 1) - side(3, 2)) / max(side(0, 1), side(3, 2), 1e-6), abs(side(0, 3) - side(1, 2)) / max(side(0, 3), side(1, 2), 1e-6))


def _refine(lab: np.ndarray, gray: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Refine coarse to fine in two ways and keep the one that agrees better and stays nearly parallel.

    * a homography at every scale: exact when the whole picture is in the photograph;
    * an affine map first and a homography only at full resolution: the edge of a picture that is partly outside the
      photograph does not hold a homography at coarse scales, which then runs off into a perspective skew.
    """
    template = _picture_structure(gray, PICTURE, 1.8)
    score = lambda mm: _zncc(template, _structure(_warp_photo(lab, mm, PICTURE), 1.8))
    plain = m
    for size, sigma in ((128, 1.0), (256, 1.4), (PICTURE, 1.8)):
        plain = _ecc(lab, gray, plain, size, sigma, cv2.MOTION_HOMOGRAPHY)
    careful = m
    for size, sigma in ((128, 1.0), (256, 1.4), (PICTURE, 1.8)):
        careful = _ecc(lab, gray, careful, size, sigma, cv2.MOTION_AFFINE)
    careful_full = _ecc(lab, gray, careful, PICTURE, 1.8, cv2.MOTION_HOMOGRAPHY)
    options = [(score(c), c) for c in (plain, careful_full, careful) if _perspective(c) <= MAX_PERSPECTIVE]
    return max(options, key=lambda item: item[0])[1] if options else careful


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


def side_insets(margins: dict) -> dict[str, float]:
    """The share of the picture hidden on each side: the measured one where the frame's edge was found, exactly
    ``FALLBACK_INSET`` where it was not (REQ-027): an assumption, reported as such, never a floor under a measurement."""
    return {k: (v["share"] if v["edge_found"] else FALLBACK_INSET) for k, v in margins.items()}


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

    bm = region.bitmap
    a, b, c, d, e, f = bm["matrix"]
    local_to_mm = np.array([[a, c, e], [b, d, f], [0, 0, 1.0]])
    picture_to_local = np.array([[bm["w"] / PICTURE, 0, -bm["w"] / 2], [0, bm["h"] / PICTURE, -bm["h"] / 2], [0, 0, 1.0]])
    picture_to_mm = local_to_mm @ picture_to_local

    h0, w0 = img_bgr.shape[:2]
    s = WORK_LONG_SIDE / max(h0, w0)
    small = cv2.resize(ph.decoded_srgb(img_bgr).astype(np.float32), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB)

    # 1. the start: the picture's edges searched over every pose, as the element anchoring searches outlines
    from . import anchoring
    points, tangents = _picture_samples(cv2.resize(gray, (PICTURE, PICTURE), interpolation=cv2.INTER_AREA), picture_to_mm)
    if len(points) < 100:
        return refuse("the picture of the file has no tones to match")
    corners_mm = np.c_[np.float32([[0, 0], [PICTURE, 0], [PICTURE, PICTURE], [0, PICTURE]]), np.ones(4)] @ picture_to_mm.T
    prep = anchoring.prepare(img_bgr, anchoring.COARSE_LONG_SIDE)
    poses = anchoring.global_search(prep, points, tangents, corners_mm[:, :2])
    diag["search"] = [{"mirror": p["mirror"], "rotation_degrees": 90 * p["k"], "score": round(p["score"], 3)} for p in poses]
    if not poses:
        return refuse("the picture of the file does not match the photograph closely enough")

    # 2. ECC refinement of the best pose of each of the best few orientations; the refined correlation decides
    template = _picture_structure(gray, PICTURE, 1.8)
    refined = []
    for pose in poses[:REFINE_TOP]:
        m = (np.diag([s / prep.scale, s / prep.scale, 1.0]) @ pose["h"] @ picture_to_mm).astype(np.float64)
        mm = _refine(lab, gray, m)
        final = _zncc(template, _structure(_warp_photo(lab, mm, PICTURE), 1.8))
        refined.append((final, (pose["mirror"], pose["k"]), mm))
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
    image_to_mm = picture_to_mm @ np.linalg.inv(to_photo)
    px_per_mm = float(np.sqrt(abs(np.linalg.det(np.linalg.inv(image_to_mm)[:2, :2]))))

    margins = _hidden_margins(lab, m)
    found = all(v["edge_found"] for v in margins.values())
    inset = side_insets(margins)
    lo_x, hi_x, lo_y, hi_y = inset["left"] * PICTURE, PICTURE * (1 - inset["right"]), inset["top"] * PICTURE, PICTURE * (1 - inset["bottom"])
    window = cv2.perspectiveTransform(np.float32([[[lo_x, lo_y], [hi_x, lo_y], [hi_x, hi_y], [lo_x, hi_y]]]), to_photo)[0]
    size_mm = float(max(bm["w"], bm["h"]) * np.sqrt(abs(np.linalg.det(local_to_mm[:2, :2]))))
    details = {"zncc": round(best, 3), "second_orientation_zncc": round(second, 3), "px_per_mm": round(px_per_mm, 3),
               "orientation": {"mirror": bool(key[0]), "rotation_degrees": 90 * int(key[1])},
               "picture_quad_px": cv2.perspectiveTransform(np.float32([[[0, 0], [PICTURE, 0], [PICTURE, PICTURE], [0, PICTURE]]]), to_photo)[0].round(1).tolist(),
               "window_found": bool(found), "window_px": window.round(1).tolist(),
               "frame_sides": {k: bool(v["edge_found"]) for k, v in margins.items()},
               "hidden_mm": {k: round(v * size_mm, 1) for k, v in inset.items()}, "hidden_share": {k: round(v, 4) for k, v in inset.items()}}
    reflected = bool(np.linalg.det(image_to_mm[:2, :2]) < 0)
    diag["details"] = details
    return Registration(image_to_mm, "picture", [], round(1.0 - best, 3), reflected, details=details)
