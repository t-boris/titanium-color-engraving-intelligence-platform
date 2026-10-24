"""Important areas of a photograph: faces with their eyes and lips, and areas the operator marks (REQ-033, DEC-074).

Faces are found with OpenCV's YuNet detector (``cv2.FaceDetectorYN``) and the model file shipped in ``models/`` (its
source, licence and checksum are in ``models/README.md``). YuNet gives per face a box, both eyes, the nose tip and both
mouth corners. A photograph prepared for engraving is often turned, so the picture is searched upright and turned by 90,
180 and 270 degrees; a face found in several turns is kept once, from the turn that scored it highest (on an upside-down
face the upright search may still score, with its eyes where the mouth is).

An area is a dict in pixels of the searched image (x right, y down, from the image's top-left corner)::

    {"kind": "face" | "eye" | "lips" | "manual", "source": "detected" | "manual", "score": 0.9 | None,
     "polygon": [[x, y], ...]}                                                   # the face box, turned with the picture
    {..., "ellipse": {"center": [x, y], "axes": [a, b], "angle": degrees}}       # semi-axes; angle of the first axis

An eye, the lips or a marked area may carry ``"detail"`` (``DETAILS``, vector-detail-and-colour-control I-3): how finely the split divides it,
as a share of the picture's coarse superpixel; without it, ``fine``. A face is divided as a face (its DEC-094).

Eyes are ellipses around the eye landmarks, sized by the distance between the eyes; the lips are an ellipse spanning the
mouth corners whose height is proportional to the mouth width. Detection never raises: a missing model, an unusable
image or an OpenCV error gives no areas and the reason.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
KINDS = ("face", "eye", "lips", "manual")
FINE_KINDS = ("eye", "lips", "manual")         # divided finer than a face, each by its own detail
DETAILS = {"face": 0.6, "fine": 0.35, "finer": 0.2, "finest": 0.12}   # superpixel size of an area against the picture's coarse one
DEFAULT_DETAIL = "fine"
SOURCES = ("detected", "manual")
SCORE_THRESHOLD = 0.6          # OpenCV's demo keeps 0.9; turned and greyscale portraits score lower
NMS_THRESHOLD = 0.3
SAME_FACE_IOU = 0.3            # boxes of two turns overlapping more than this are one face
MAX_SIDE = 1600                # a larger picture is searched reduced; faces smaller than ~10 px are not wanted anyway
# Turned pictures searched, with the map of a point of the turned picture back to the picture (w, h: picture size).
TURNS = (
    (None, lambda x, y, w, h: (x, y)),
    (cv2.ROTATE_90_CLOCKWISE, lambda x, y, w, h: (y, h - x)),
    (cv2.ROTATE_180, lambda x, y, w, h: (w - x, h - y)),
    (cv2.ROTATE_90_COUNTERCLOCKWISE, lambda x, y, w, h: (w - y, x)),
)
EYE_AXES = (0.32, 0.20)        # semi-axes of an eye as fractions of the distance between the eyes
LIPS_AXES = (0.65, 0.34)       # semi-axes of the lips as fractions of the mouth width (corner to corner)


class FaceSearch(NamedTuple):
    """The areas found (faces, eyes, lips), the number of faces and, when the search could not run, why."""
    areas: list
    faces: int
    error: str | None = None

    @property
    def face_found(self) -> bool:
        return self.faces > 0


def _yunet(image_bgr: np.ndarray) -> np.ndarray:
    """YuNet's rows ``[x, y, w, h, right eye x, y, left eye x, y, nose x, y, right mouth x, y, left mouth x, y, score]``."""
    h, w = image_bgr.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), SCORE_THRESHOLD, NMS_THRESHOLD, 5000)
    _, faces = detector.detect(image_bgr)
    return np.zeros((0, 15), np.float32) if faces is None else faces


def _ellipse(center, axes, angle: float) -> dict:
    return {"center": [round(float(center[0]), 2), round(float(center[1]), 2)],
            "axes": [round(float(axes[0]), 2), round(float(axes[1]), 2)], "angle": round(float(angle), 2)}


def face_areas(box: list, eyes: list, mouth: list, score: float) -> list[dict]:
    """The face, its two eyes and its lips as areas: ``box`` is the face's four corners, ``eyes`` and ``mouth`` two
    points each (the subject's right first), all in picture pixels."""
    (ex0, ey0), (ex1, ey1) = eyes
    (mx0, my0), (mx1, my1) = mouth
    eye_distance = math.hypot(ex1 - ex0, ey1 - ey0)
    eye_angle = math.degrees(math.atan2(ey1 - ey0, ex1 - ex0))
    mouth_width = math.hypot(mx1 - mx0, my1 - my0)
    mouth_angle = math.degrees(math.atan2(my1 - my0, mx1 - mx0))
    score = round(float(score), 3)
    areas = [{"kind": "face", "source": "detected", "score": score,
              "polygon": [[round(float(x), 2), round(float(y), 2)] for x, y in box]}]
    if eye_distance > 0:
        axes = (EYE_AXES[0] * eye_distance, EYE_AXES[1] * eye_distance)
        areas += [{"kind": "eye", "source": "detected", "score": score, "ellipse": _ellipse(eye, axes, eye_angle)}
                  for eye in eyes]
    if mouth_width > 0:
        areas.append({"kind": "lips", "source": "detected", "score": score,
                      "ellipse": _ellipse(((mx0 + mx1) / 2, (my0 + my1) / 2),
                                          (LIPS_AXES[0] * mouth_width, LIPS_AXES[1] * mouth_width), mouth_angle)})
    return areas


def _bounds(points) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _iou(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def important_areas(image_rgb, *, detect: Callable[[np.ndarray], np.ndarray] | None = None) -> FaceSearch:
    """Faces, eyes and lips of an RGB uint8 picture; ``detect`` replaces YuNet (it takes a BGR picture and gives YuNet's
    rows). Never raises: a failed search gives no areas and the reason."""
    try:
        img = np.asarray(image_rgb)
        if img.ndim != 3 or img.shape[2] != 3 or img.dtype != np.uint8 or not img.size:
            return FaceSearch([], 0, "the picture must be an RGB array of 8-bit channels")
        h, w = img.shape[:2]
        scale = min(1.0, MAX_SIDE / max(h, w))
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        if scale < 1:
            bgr = cv2.resize(bgr, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
        sh, sw = bgr.shape[:2]
        found = []
        for turn, (code, back) in enumerate(TURNS):
            for row in (detect or _yunet)(bgr if code is None else cv2.rotate(bgr, code)):
                row = [float(v) for v in row[:15]]
                if not all(math.isfinite(v) for v in row) or row[14] < SCORE_THRESHOLD:
                    continue
                x, y, bw, bh = row[:4]
                corners = [(x, y), (x + bw, y), (x + bw, y + bh), (x, y + bh)]
                points = [back(px, py, sw, sh) for px, py in corners + list(zip(row[4:14:2], row[5:14:2]))]
                points = [(px / scale, py / scale) for px, py in points]
                found.append((-row[14], turn, points))
        kept = []
        for score, _, points in sorted(found, key=lambda f: (f[0], f[1], _bounds(f[2][:4]))):
            box = _bounds(points[:4])
            if all(_iou(box, _bounds(k[1][:4])) <= SAME_FACE_IOU for k in kept):
                kept.append((-score, points))
        areas = [a for score, points in kept for a in face_areas(points[:4], points[4:6], points[7:9], score)]
        return FaceSearch(areas, len(kept))
    except Exception as exc:          # a broken model or OpenCV build must not stop the split (REQ-033)
        return FaceSearch([], 0, f"face detection failed: {exc}")


# -- areas given by the operator ------------------------------------------------------------------------------------
def _point(value, name: str) -> list[float]:
    try:
        x, y = (float(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a point [x, y]") from None
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(f"{name} must be a point of finite numbers")
    return [x, y]


def check_area(area) -> dict:
    """A normalised copy of an important area (see the module docstring), or ValueError with the reason.

    An area without ``kind`` or ``source`` is one the operator marked; a detected area handed back (to keep it while
    others are removed) keeps its kind, source and score.
    """
    if not isinstance(area, Mapping):
        raise ValueError("an important area must be an object with an ellipse or a polygon")
    kind, source, score = area.get("kind", "manual"), area.get("source", "manual"), area.get("score")
    if kind not in KINDS:
        raise ValueError(f"the kind of an important area must be one of {', '.join(KINDS)}")
    if source not in SOURCES:
        raise ValueError(f"the source of an important area must be one of {', '.join(SOURCES)}")
    if score is not None:
        try:
            score = float(score)
        except (TypeError, ValueError):
            raise ValueError("the score of an important area must be a number") from None
        if not math.isfinite(score):
            raise ValueError("the score of an important area must be a finite number")
    out = {"kind": kind, "source": source, "score": score}
    detail = area.get("detail")
    if detail is not None:
        if kind not in FINE_KINDS:
            raise ValueError("only an eye, the lips or a marked area takes a detail of its own")
        if detail not in DETAILS:
            raise ValueError(f"the detail of an important area must be one of {', '.join(DETAILS)}")
        out["detail"] = detail
    if ("polygon" in area) == ("ellipse" in area):
        raise ValueError("an important area is either an ellipse or a polygon")
    if "polygon" in area:
        points = area["polygon"]
        if not isinstance(points, (list, tuple)) or len(points) < 3:
            raise ValueError("a polygon needs at least three points")
        out["polygon"] = [_point(p, "a polygon corner") for p in points]
        return out
    ellipse = area["ellipse"]
    if not isinstance(ellipse, Mapping):
        raise ValueError("an ellipse needs a center, two semi-axes and an angle")
    axes = _point(ellipse.get("axes"), "the semi-axes")
    if min(axes) <= 0:
        raise ValueError("the semi-axes of an ellipse must be positive")
    try:
        angle = float(ellipse.get("angle", 0.0))
    except (TypeError, ValueError):
        raise ValueError("the angle of an ellipse must be a number") from None
    if not math.isfinite(angle):
        raise ValueError("the angle of an ellipse must be a finite number")
    out["ellipse"] = {"center": _point(ellipse.get("center"), "the center"), "axes": axes, "angle": angle}
    return out


def area_mask(area: dict, shape: tuple[int, int]) -> np.ndarray:
    """Pixels of a ``shape`` (height, width) picture in the area (from :func:`check_area`), drawn by OpenCV, so pixels the
    outline crosses count too."""
    mask = np.zeros(shape, np.uint8)
    fixed = 16                                      # 4 fractional bits; area coordinates have pixel centres at +0.5
    if "polygon" in area:
        points = np.round((np.asarray(area["polygon"], float) - 0.5) * fixed).astype(np.int32)
        cv2.fillPoly(mask, [points], 1, cv2.LINE_8, 4)
    else:
        e = area["ellipse"]
        center = tuple(int(round((c - 0.5) * fixed)) for c in e["center"])
        axes = tuple(int(round(a * fixed)) for a in e["axes"])
        cv2.ellipse(mask, center, axes, e["angle"], 0, 360, 1, -1, cv2.LINE_8, 4)
    return mask.astype(bool)
