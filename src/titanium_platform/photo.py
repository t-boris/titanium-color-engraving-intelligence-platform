"""Photograph pipeline: decode, reference-chart detection and correction, alignment, masks, sampling.

Assumptions that the requirements leave open (all recorded as proposed decisions or settings):

* The chart is a 24-patch ColorChecker Classic found with OpenCV's ``mcc`` detector (DEC-025). Detection is
  verified on OpenCV test images and synthetic renders only, never on a real rig photograph.
* Reference patch values are approximate published sRGB (D65) values and can be replaced per capture setup.
* Correction is a least-squares 3x3 matrix in linear RGB fitted on the 24 patches. White point, observing
  conditions and the exact calibration method are not fixed by the requirements.
* The mask edge exclusion is a fraction of the region's smaller side (``EDGE_FRACTION``); its size is not
  specified by the requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import color

RAW_EXTENSIONS = {".raw", ".nef", ".nrw", ".cr2", ".cr3", ".arw", ".dng", ".raf", ".rw2", ".orf", ".pef", ".srw"}
EDGE_FRACTION = 0.2
MIN_MASK_PIXELS = 25
MIN_CHART_AREA_PX = 400.0       # a real 24-patch chart outline is far larger than this
MIN_PATCH_SPREAD = 8.0          # mean per-channel standard deviation of the 24 patch colors (0..255)
MAX_CORRECTION_RESIDUAL = 12.0  # mean patch delta E after correction above which the correction is rejected

REFERENCE_SRGB = np.array([
    (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
    (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
    (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
    (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52)], dtype=float)


class PhotoError(ValueError):
    """The photograph cannot be used; the message is meant for the operator."""


def decode_image(path: str | Path, allow_non_raw: bool = False) -> np.ndarray:
    """Return an 8-bit BGR image. Real measurement requires RAW (DEC-003); ``allow_non_raw`` is for tests."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in RAW_EXTENSIONS:
        import rawpy  # imported lazily: only needed for real RAW files
        try:
            with rawpy.imread(str(path)) as raw:
                rgb16 = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16, output_color=rawpy.ColorSpace.sRGB)
        except Exception as exc:  # rawpy raises several unrelated error types
            raise PhotoError(f"cannot decode RAW file: {exc}") from exc
        return cv2.cvtColor((rgb16 >> 8).astype(np.uint8), cv2.COLOR_RGB2BGR)
    if not allow_non_raw:
        raise PhotoError("a RAW photograph is required for measurement")
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise PhotoError("cannot decode the image")
    return img


@dataclass
class Chart:
    detected: bool
    patches_rgb: np.ndarray | None = None  # (24, 3) sRGB 0..255 as photographed
    box: list | None = None
    reason: str = ""


def chart_detector():
    """A ColorChecker detector configured explicitly, never relying on OpenCV's defaults.

    In the opencv-contrib 5.0 Linux x86_64 wheel a new ``CCheckerDetector`` sometimes starts with an
    uninitialised chart type (measured on CI: 100 of 200 new detectors reported type 832 instead of MCC24 = 0),
    and then finds nothing, not even OpenCV's own test image. Setting the type and the DNN flag explicitly made
    detection succeed 30/30 there on both a real test image and our synthetic scene. The DNN path needs a model
    file this application does not ship, so it is switched off.
    """
    det = cv2.mcc.CCheckerDetector_create()
    det.setColorChartType(cv2.mcc.MCC24)
    det.setUseDnnModel(False)
    return det


def detect_chart(img_bgr: np.ndarray) -> Chart:
    det = chart_detector()
    try:
        found = det.process(img_bgr, 1)
    except cv2.error as exc:
        return Chart(False, reason=f"chart detector failed: {exc}")
    if not found:
        return Chart(False, reason="reference chart not detected")
    checker = det.getBestColorChecker()
    box = np.asarray(checker.getBox(), dtype=np.float32)
    patches = checker.getChartsRGB()[:, 1].reshape(24, 3).astype(float)  # column 1 = patch mean, RGB order
    # OpenCV's detector can report a chart on an image that has none (observed: an all-zero box and 24 identical
    # patches). Treat such output as "no chart" instead of trusting the boolean it returns.
    if not np.isfinite(box).all() or abs(cv2.contourArea(box.reshape(-1, 1, 2))) < MIN_CHART_AREA_PX:
        return Chart(False, reason="the detector returned a degenerate chart outline")
    if float(patches.std(axis=0).mean()) < MIN_PATCH_SPREAD:
        return Chart(False, reason="the detected patches are all the same color")
    # A chart seen upside down lists the grey ramp the wrong way round: patch 19 (white) must be brighter
    # than patch 24 (black). Reverse the patch order if it is not.
    if patches[18].sum() < patches[23].sum():
        patches = patches[::-1].copy()
    return Chart(True, patches, box.tolist())


@dataclass
class Correction:
    matrix: np.ndarray  # 3x3, applied to linear RGB
    residual: float     # mean patch delta E (CIE76) after correction


def fit_correction(patches_rgb: np.ndarray, reference_rgb: np.ndarray = REFERENCE_SRGB) -> Correction:
    src = color.srgb_to_linear(patches_rgb / 255.0)
    dst = color.srgb_to_linear(reference_rgb / 255.0)
    sol, *_ = np.linalg.lstsq(src, dst, rcond=None)
    matrix = sol.T
    corrected = np.clip(src @ matrix.T, 0, 1)
    lab_c = color.linear_rgb_to_lab(corrected)
    lab_r = color.linear_rgb_to_lab(dst)
    residual = float(np.mean(np.linalg.norm(lab_c - lab_r, axis=1)))
    return Correction(matrix, residual)


def apply_correction(img_bgr: np.ndarray, corr: Correction) -> np.ndarray:
    """Corrected image as float sRGB (RGB order), values 0..1."""
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float64) / 255.0
    lin = color.srgb_to_linear(rgb) @ corr.matrix.T
    return color.linear_to_srgb(np.clip(lin, 0, 1))


def correct(img_bgr: np.ndarray, reference_rgb: np.ndarray = REFERENCE_SRGB) -> tuple[np.ndarray | None, Chart, Correction | None]:
    """Detect the chart and correct the image. Without a detectable chart nothing is returned (REQ-009)."""
    chart = detect_chart(img_bgr)
    if not chart.detected:
        return None, chart, None
    corr = fit_correction(chart.patches_rgb, reference_rgb)
    if corr.residual > MAX_CORRECTION_RESIDUAL:
        chart.reason = f"chart correction residual {corr.residual:.1f} exceeds {MAX_CORRECTION_RESIDUAL:g}"
        return None, chart, corr
    return apply_correction(img_bgr, corr), chart, corr


# -- alignment -------------------------------------------------------------------------------------------
def detect_markers(img_bgr: np.ndarray) -> dict[int, np.ndarray]:
    """ArUco ids 0..3 -> 4x2 corner array (image pixels, order TL,TR,BR,BL as ArUco reports it)."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(gray)
    if ids is None:
        return {}
    return {int(i): c.reshape(4, 2) for i, c in zip(ids.ravel(), corners) if int(i) in (0, 1, 2, 3)}


def read_identifier(img_bgr: np.ndarray) -> str | None:
    text = cv2.QRCodeDetector().detectAndDecode(img_bgr)[0]
    return text[5:] if text.startswith("TCE1:") else None


def read_identifier_rectified(img_bgr: np.ndarray, image_to_mm: np.ndarray, area_mm: tuple[float, float, float, float],
                              px_per_mm: float = 20.0) -> str | None:
    """Read the QR identifier from a view rectified with the marker homography (more robust than the raw frame)."""
    x0, y0, w, h = area_mm
    scale = np.array([[px_per_mm, 0, -x0 * px_per_mm], [0, px_per_mm, -y0 * px_per_mm], [0, 0, 1]])
    size = (int(np.ceil(w * px_per_mm)), int(np.ceil(h * px_per_mm)))
    if size[0] < 10 or size[1] < 10 or size[0] * size[1] > 60_000_000:
        return None
    return read_identifier(cv2.warpPerspective(img_bgr, scale @ image_to_mm, size, borderValue=(255, 255, 255)))


def homography_from_markers(found: dict[int, np.ndarray], markers: dict, x_offset: float = 0.0, y_offset: float = 0.0) -> np.ndarray:
    """Homography image -> file mm from the four ArUco markers. Fails rather than guessing (REQ-003)."""
    missing = [i for i in (0, 1, 2, 3) if i not in found]
    if missing:
        raise PhotoError(f"registration markers not detected: {missing}")
    img_pts, plan_pts = [], []
    for m in markers["aruco"]:
        x, y, s = m["x"] + x_offset, m["y"] + y_offset, m["size"]
        plan_pts += [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]
        img_pts += found[m["id"]].tolist()
    h, _ = cv2.findHomography(np.array(img_pts, np.float32), np.array(plan_pts, np.float32), 0)
    if h is None:
        raise PhotoError("cannot compute the alignment from the markers")
    return h


def validate_corners(corners_px: list[tuple[float, float]]) -> None:
    """Four points, in order TL,TR,BR,BL, forming a convex quadrilateral with no degenerate corner."""
    if len(corners_px) != 4:
        raise PhotoError("exactly four corners are required")
    pts = np.array(corners_px, float)
    if not np.isfinite(pts).all():
        raise PhotoError("corners must be finite")
    signs = []
    for i in range(4):
        a, b, c = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        signs.append(cross)
    if min(abs(s) for s in signs) < 1e-6 or not (all(s > 0 for s in signs) or all(s < 0 for s in signs)):
        raise PhotoError("the four corners must form a convex quadrilateral in order top-left, top-right, bottom-right, bottom-left")


def homography_from_corners(corners_px: list[tuple[float, float]], area: tuple[float, float, float, float]) -> np.ndarray:
    """Homography image -> file mm from the four image corners of the work (TL,TR,BR,BL) and its area (x, y, w, h)."""
    validate_corners(corners_px)
    x, y, w, h = area
    dst = np.array([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], np.float32)
    return cv2.getPerspectiveTransform(np.array(corners_px, np.float32), dst)


# -- masks and sampling ----------------------------------------------------------------------------------
def _erode(mask_u8: np.ndarray, k: int) -> np.ndarray:
    """Erode by k pixels treating everything outside the image as empty.

    OpenCV's default border value for erosion is the maximum, which would leave an area that touches the
    frame un-eroded on that side. A region cut off by the frame has no valid pixels beyond it, so its edge
    is excluded like any other.
    """
    if k <= 0:
        return mask_u8
    return cv2.erode(mask_u8, np.ones((2 * k + 1, 2 * k + 1), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)


def region_mask(polygon_mm: list[tuple[float, float]], image_to_mm: np.ndarray, shape: tuple[int, int],
                edge_fraction: float = EDGE_FRACTION) -> np.ndarray:
    """Boolean mask in image pixels for a region given in file mm, with its edges excluded by erosion."""
    mm_to_image = np.linalg.inv(image_to_mm)
    pts = cv2.perspectiveTransform(np.array([polygon_mm], np.float32), mm_to_image.astype(np.float32))[0]
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 1)
    xs, ys = pts[:, 0], pts[:, 1]
    side = min(xs.max() - xs.min(), ys.max() - ys.min())
    return _erode(mask, int(round(side * edge_fraction))).astype(bool)


def layer_mask(polygons_mm: list[list[tuple[float, float]]], image_to_mm: np.ndarray, shape: tuple[int, int],
               edge_fraction: float = EDGE_FRACTION) -> np.ndarray:
    """Mask of a whole layer: the union of its shapes with the edge of each connected area excluded (DEC-028).

    A layer made of many touching shapes (a conversion plan stores one as hundreds of rectangles) is one
    area. Eroding every shape on its own would also cut away the seams between neighbouring shapes, so the
    shapes are merged first and each connected area is eroded by a fraction of its own smaller side.
    """
    if not polygons_mm:
        return np.zeros(shape, bool)
    mm_to_image = np.linalg.inv(image_to_mm).astype(np.float32)
    union = np.zeros(shape, np.uint8)
    for poly in polygons_mm:
        pts = cv2.perspectiveTransform(np.array([poly], np.float32), mm_to_image)[0]
        cv2.fillPoly(union, [np.round(pts).astype(np.int32)], 1)
    count, labels = cv2.connectedComponents(union, connectivity=8)
    out = np.zeros(shape, bool)
    for lab in range(1, count):
        area = labels == lab
        ys, xs = np.nonzero(area)
        side = min(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)
        out |= _erode(area.astype(np.uint8), int(round(side * edge_fraction))).astype(bool)
    return out


def sample_lab(corrected_rgb: np.ndarray, mask: np.ndarray) -> tuple[list[float], int]:
    """Median corrected colour inside the mask, as Lab. Raises when too few pixels remain."""
    n = int(mask.sum())
    if n < MIN_MASK_PIXELS:
        raise PhotoError(f"region is too small after excluding its edges ({n} pixels)")
    rgb = np.median(corrected_rgb[mask], axis=0) * 255.0
    return [float(v) for v in color.srgb8_to_lab(rgb)], n
