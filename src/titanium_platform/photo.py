"""Photograph pipeline: decode, reference-chart detection and correction, alignment, masks, sampling.

Assumptions that the requirements leave open (all recorded as proposed decisions or settings):

* The chart is a 24-patch ColorChecker Classic found with OpenCV's ``mcc`` detector (DEC-025). Detection is
  verified on OpenCV test images and synthetic renders only, never on a real rig photograph.
* Reference patch values are the published sRGB (D65) values of the chart by default; every capture setup carries its
  own reference (24 Lab values with their white point and observer) as an explicit setting (DEC-025), and the correction
  of a photograph aims at the reference of the setup it was taken on.
* Correction is a least-squares 3x3 matrix in linear RGB fitted on the 24 patches. The patches and the measured
  surface are taken from a 16-bit *linear* decode of the RAW (DEC-059): the 8-bit gamma-encoded decode read as sRGB
  under-read the dark tones up to threefold (chart black L* 13 instead of 21.7). The 8-bit decode serves detection,
  alignment and previews only. White point, observing conditions and the exact calibration method are not fixed by
  the requirements.
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
PUBLISHED_REFERENCE_SOURCE = "published ColorChecker Classic values (sRGB, D65), as CIELAB D65 / 2°"


def published_reference() -> dict:
    """The chart reference a capture setup has until the operator gives its own: the published patch values as Lab."""
    return {"source": PUBLISHED_REFERENCE_SOURCE, "white_point": "D65", "observer": "2°", "published": True,
            "patches_lab": [[round(float(v), 2) for v in lab] for lab in color.srgb8_to_lab(REFERENCE_SRGB)]}


def reference_linear(reference: dict | None = None) -> np.ndarray:
    """The 24 patch values a correction aims at, as linear sRGB: the published values, or a capture setup's own Lab values
    adapted from their white point."""
    if reference is None or reference.get("published"):
        return color.srgb_to_linear(REFERENCE_SRGB / 255.0)
    return color.lab_under_to_linear_rgb(np.asarray(reference["patches_lab"], float), reference["white_point"])


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


def decode_linear(path: str | Path, allow_non_raw: bool = False) -> np.ndarray:
    """The photograph as float32 linear RGB (RGB order, 0..1) for colour measurement: a RAW is developed in 16 bits
    without a tone curve (camera white balance, no brightness change); a non-RAW test image is linearised from sRGB."""
    path = Path(path)
    if path.suffix.lower() in RAW_EXTENSIONS:
        import rawpy
        try:
            with rawpy.imread(str(path)) as raw:
                rgb16 = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16, gamma=(1, 1),
                                        output_color=rawpy.ColorSpace.sRGB)
        except Exception as exc:
            raise PhotoError(f"cannot decode RAW file: {exc}") from exc
        return (rgb16.astype(np.float32) / 65535.0)
    return color.srgb_to_linear(decoded_srgb(decode_image(path, allow_non_raw))).astype(np.float32)


@dataclass
class Chart:
    detected: bool
    patches_rgb: np.ndarray | None = None  # (24, 3) sRGB 0..255 as photographed (8-bit decode)
    box: list | None = None
    reason: str = ""
    patches_linear: np.ndarray | None = None  # (24, 3) linear RGB 0..1 from the linear decode, same order


def chart_patches_linear(chart: Chart, linear_rgb: np.ndarray, inset: float = 0.2) -> np.ndarray:
    """The 24 patch means read from the linear image: a 6 x 4 grid inside the detected outline, the central part of every
    cell. The order follows the detected outline. An outline that starts at the opposite corner (a chart turned half
    round) reads the grey ramp first: the grey ramp is the most neutral row, so when the first row is more neutral than
    the last the order is turned round; then, like ``patches_rgb``, when the grey ramp runs the wrong way."""
    box = np.asarray(chart.box, np.float32).reshape(-1, 2)
    to_photo = cv2.getPerspectiveTransform(np.float32([[0, 0], [6, 0], [6, 4], [0, 4]]), box)
    height, width = linear_rgb.shape[:2]
    out = np.zeros((24, 3), np.float64)
    for index, (row, col) in enumerate((r, c) for r in range(4) for c in range(6)):
        cell = np.float32([[col + inset, row + inset], [col + 1 - inset, row + inset], [col + 1 - inset, row + 1 - inset], [col + inset, row + 1 - inset]])
        poly = cv2.perspectiveTransform(cell[None], to_photo)[0]
        mask = cv2.fillConvexPoly(np.zeros((height, width), np.uint8), np.round(poly).astype(np.int32), 1).astype(bool)
        out[index] = linear_rgb[mask].reshape(-1, 3).mean(axis=0) if mask.any() else np.nan
    if not np.isfinite(out).all():
        raise PhotoError("the reference chart lies partly outside the photograph")
    spread = lambda row: float(np.mean(np.ptp(row, axis=1) / np.maximum(row.mean(axis=1), 1e-9)))     # 0 for neutral patches
    if spread(out[:6]) < spread(out[18:]):
        out = out[::-1].copy()
    if out[18].sum() < out[23].sum():
        out = out[::-1].copy()
    return out


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
    grey_ramp: dict | None = None   # L* of the six grey patches: reference, corrected (how the tones come out)


def fit_correction_linear(patches_linear: np.ndarray, reference_rgb: np.ndarray = REFERENCE_SRGB,
                          target_linear: np.ndarray | None = None) -> Correction:
    """Least-squares 3x3 matrix from the photographed patches (linear RGB) to the reference (sRGB 0..255, or the linear
    patch values of a capture setup's reference when ``target_linear`` is given)."""
    src = np.clip(np.asarray(patches_linear, float), 0, None)
    dst = color.srgb_to_linear(reference_rgb / 255.0) if target_linear is None else np.asarray(target_linear, float)
    sol, *_ = np.linalg.lstsq(src, dst, rcond=None)
    matrix = sol.T
    corrected = np.clip(src @ matrix.T, 0, 1)
    lab_c = color.linear_rgb_to_lab(corrected)
    lab_r = color.linear_rgb_to_lab(dst)
    residual = float(np.mean(np.linalg.norm(lab_c - lab_r, axis=1)))
    ramp = {"reference": [round(float(v), 1) for v in lab_r[18:24, 0]], "corrected": [round(float(v), 1) for v in lab_c[18:24, 0]]}
    return Correction(matrix, residual, ramp)


def fit_correction(patches_rgb: np.ndarray, reference_rgb: np.ndarray = REFERENCE_SRGB,
                   target_linear: np.ndarray | None = None) -> Correction:
    """The fit from the 8-bit decode's patches (sRGB 0..255); kept for photographs without a linear decode."""
    return fit_correction_linear(color.srgb_to_linear(patches_rgb / 255.0), reference_rgb, target_linear)


def apply_correction(img_bgr: np.ndarray, corr: Correction, linear: np.ndarray | None = None) -> np.ndarray:
    """Corrected image as float sRGB (RGB order), values 0..1, from the linear decode when given."""
    lin = linear if linear is not None else color.srgb_to_linear(decoded_srgb(img_bgr))
    return color.linear_to_srgb(np.clip(lin @ corr.matrix.T, 0, 1))


def decoded_srgb(img_bgr: np.ndarray, linear: np.ndarray | None = None) -> np.ndarray:
    """The photograph as float sRGB (RGB order) before any reference-chart correction: encoded from the linear decode
    when given, else from the 8-bit decode."""
    if linear is not None:
        return color.linear_to_srgb(np.clip(linear, 0, 1))
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float64) / 255.0


EXPOSED_WHITE = 0.85            # the 99.5th percentile of luminance is brought here for detection (never for measurement)


def exposed_bgr(linear: np.ndarray) -> np.ndarray:
    """An 8-bit rendering of the linear decode with its exposure normalised: an under-exposed photograph (the operator's are
    1.5–4 stops under) hides the chart's dark frame and patches from the detector and the cells from the matrix finder.
    Geometry only: colours are always read from ``linear``."""
    lum = np.asarray(linear, np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    gain = EXPOSED_WHITE / max(float(np.percentile(lum, 99.5)), 1e-4)
    srgb = color.linear_to_srgb(np.clip(linear * gain, 0, 1))
    return cv2.cvtColor((srgb * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)


def correct(img_bgr: np.ndarray, reference_rgb: np.ndarray = REFERENCE_SRGB,
            linear: np.ndarray | None = None, reference: dict | None = None) -> tuple[np.ndarray | None, Chart, Correction | None]:
    """Detect the chart and correct the image, from the linear decode when given, toward ``reference`` (a capture setup's
    chart reference; the published values when None). The chart is looked for on the exposure-normalised rendering of the
    linear decode first, then on the 8-bit decode. Without a detectable chart nothing is returned (REQ-009)."""
    target = None if reference is None or reference.get("published") else reference_linear(reference)
    chart = detect_chart(exposed_bgr(linear)) if linear is not None else Chart(False, reason="reference chart not detected")
    if not chart.detected:
        chart = detect_chart(img_bgr)
    if not chart.detected:
        return None, chart, None
    if linear is not None:
        try:
            chart.patches_linear = chart_patches_linear(chart, linear)
        except PhotoError as exc:
            chart.reason = str(exc)
            return None, chart, None
        corr = fit_correction_linear(chart.patches_linear, reference_rgb, target)
    else:
        corr = fit_correction(chart.patches_rgb, reference_rgb, target)
    if corr.residual > MAX_CORRECTION_RESIDUAL:
        chart.reason = f"chart correction residual {corr.residual:.1f} exceeds {MAX_CORRECTION_RESIDUAL:g}"
        return None, chart, corr
    return apply_correction(img_bgr, corr, linear), chart, corr


# -- alignment -------------------------------------------------------------------------------------------
def detect_markers(img_bgr: np.ndarray) -> dict[int, np.ndarray]:
    """ArUco ids 0..3 -> 4x2 corner array (image pixels, order TL,TR,BR,BL as ArUco reports it)."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(gray)
    if ids is None:
        return {}
    return {int(i): c.reshape(4, 2) for i, c in zip(ids.ravel(), corners) if int(i) in (0, 1, 2, 3)}


def detect_marker_candidates(img_bgr: np.ndarray) -> list[dict[int, np.ndarray]]:
    """Detect ArUco markers in all eight image orientations and map corners back to source pixels.

    Photos of engraved plates may be mirrored or rotated. The QR identifier is checked after rectification,
    so testing these orientation candidates does not silently accept a different plate.
    """
    h, w = img_bgr.shape[:2]
    transforms = [
        ("identity", np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float64), lambda: img_bgr),
        ("flip_x", np.array([[-1, 0, w - 1], [0, 1, 0], [0, 0, 1]], np.float64), lambda: cv2.flip(img_bgr, 1)),
        ("flip_y", np.array([[1, 0, 0], [0, -1, h - 1], [0, 0, 1]], np.float64), lambda: cv2.flip(img_bgr, 0)),
        ("rotate_180", np.array([[-1, 0, w - 1], [0, -1, h - 1], [0, 0, 1]], np.float64), lambda: cv2.rotate(img_bgr, cv2.ROTATE_180)),
        ("rotate_90_cw", np.array([[0, -1, h - 1], [1, 0, 0], [0, 0, 1]], np.float64), lambda: cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)),
        ("rotate_90_ccw", np.array([[0, 1, 0], [-1, 0, w - 1], [0, 0, 1]], np.float64), lambda: cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)),
        ("transpose", np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1]], np.float64), lambda: cv2.transpose(img_bgr)),
        ("anti_transpose", np.array([[0, -1, h - 1], [-1, 0, w - 1], [0, 0, 1]], np.float64), lambda: cv2.flip(cv2.transpose(img_bgr), -1)),
    ]
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    candidates, seen = [], set()
    for _, source_to_view, make_view in transforms:
        view = make_view()
        corners, ids, _ = detector.detectMarkers(cv2.cvtColor(view, cv2.COLOR_BGR2GRAY))
        if ids is None:
            continue
        view_to_source = np.linalg.inv(source_to_view)
        found = {}
        for marker_id, corner in zip(ids.ravel(), corners):
            marker_id = int(marker_id)
            if marker_id not in (0, 1, 2, 3):
                continue
            source_corner = cv2.perspectiveTransform(corner.astype(np.float32), view_to_source.astype(np.float64))[0]
            found[marker_id] = source_corner
        key = tuple(sorted((marker_id, tuple(np.round(points, 1).ravel())) for marker_id, points in found.items()))
        if found and key not in seen:
            candidates.append(found)
            seen.add(key)
    return sorted(candidates, key=lambda found: -len(found))


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
    """Homography image -> file mm from at least three ArUco markers, never from an underconstrained pair."""
    marker_ids = {m["id"] for m in markers["aruco"]}
    usable = [m for m in markers["aruco"] if m["id"] in found]
    if len(usable) < 3:
        missing = sorted(marker_ids - set(found))
        raise PhotoError(f"fewer than three registration markers detected; missing {missing}")
    img_pts, plan_pts = [], []
    for m in usable:
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
               edge_fraction: float = EDGE_FRACTION, holes_mm: list[list[list[tuple[float, float]]]] | None = None) -> np.ndarray:
    """Mask of a whole layer: the union of its shapes with the edge of each connected area excluded (DEC-028).

    A layer made of many touching shapes (a conversion plan stores one as hundreds of rectangles) is one
    area. Eroding every shape on its own would also cut away the seams between neighbouring shapes, so the
    shapes are merged first and each connected area is eroded by a fraction of its own smaller side.
    ``holes_mm[i]`` lists the loops inside ``polygons_mm[i]`` that are not filled (REQ-023); a hole never
    removes pixels that another shape of the layer fills.
    """
    if not polygons_mm:
        return np.zeros(shape, bool)
    mm_to_image = np.linalg.inv(image_to_mm).astype(np.float32)
    union = np.zeros(shape, np.uint8)

    def to_pixels(poly):
        return np.round(cv2.perspectiveTransform(np.array([poly], np.float32), mm_to_image)[0]).astype(np.int32)

    for k, poly in enumerate(polygons_mm):
        pts = to_pixels(poly)
        holes = holes_mm[k] if holes_mm is not None and holes_mm[k] else None
        if not holes:
            cv2.fillPoly(union, [pts], 1)
            continue
        x0, y0 = np.maximum(pts.min(axis=0) - 1, 0)
        x1, y1 = np.minimum(pts.max(axis=0) + 2, (shape[1], shape[0]))
        if x1 <= x0 or y1 <= y0:
            continue
        window = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(window, [pts], 1, offset=(-int(x0), -int(y0)))
        for hole in holes:
            cv2.fillPoly(window, [to_pixels(hole)], 0, offset=(-int(x0), -int(y0)))
        union[y0:y1, x0:x1] |= window
    if edge_fraction <= 0:
        return union.astype(bool)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(union, connectivity=8)
    out = np.zeros(shape, bool)
    for lab in range(1, count):
        x, y, width, height, _ = stats[lab]
        area = (labels[y:y+height, x:x+width] == lab).astype(np.uint8)
        side = min(width, height)
        out[y:y+height, x:x+width] |= _erode(area, int(round(side * edge_fraction))).astype(bool)
    return out


def sample_lab(corrected_rgb: np.ndarray, mask: np.ndarray) -> tuple[list[float], int]:
    """Median corrected colour inside the mask, as Lab. Raises when too few pixels remain."""
    n = int(mask.sum())
    if n < MIN_MASK_PIXELS:
        raise PhotoError(f"region is too small after excluding its edges ({n} pixels)")
    rgb = np.median(corrected_rgb[mask], axis=0) * 255.0
    return [float(v) for v in color.srgb8_to_lab(rgb)], n
