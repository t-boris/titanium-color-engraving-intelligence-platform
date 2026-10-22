"""The parts of a picture of people: background, hair, body skin, face skin, clothes and other things worn (REQ-062, DEC-105).

They come from the MediaPipe multiclass selfie segmentation model (``models/selfie_multiclass_256x256.onnx``, Apache 2.0), converted once
from TFLite to ONNX and run through OpenCV, as the face detector of :mod:`faces` is: no other library. The model sees a 256 x 256 copy of
the picture; its six scores per place are kept, so the part of every pixel can be read at any size (the preview and the LightBurn file's
own size) from one run. A picture without people is all background.
"""
from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np

PARTS = ("background", "hair", "body_skin", "face_skin", "clothes", "other")
MODEL = Path(__file__).with_name("models") / "selfie_multiclass_256x256.onnx"
SIDE = 256                          # the model's input: RGB 256 x 256, values 0..1

_lock = threading.Lock()            # one network, used by one request at a time
_net = None


def _model():
    global _net
    if _net is None:
        _net = cv2.dnn.readNetFromONNX(str(MODEL))
    return _net


def scores(bgr: np.ndarray) -> np.ndarray:
    """The model's score of each part (in the order of ``PARTS``) at each place of a 256 x 256 copy of the picture, float32 256 x 256 x 6."""
    rgb = cv2.cvtColor(np.ascontiguousarray(bgr[..., :3]), cv2.COLOR_BGR2RGB)
    x = cv2.resize(rgb, (SIDE, SIDE), interpolation=cv2.INTER_AREA).astype(np.float32)[None] / 255.0
    with _lock:
        net = _model()
        net.setInput(x)
        out = net.forward()
    return np.ascontiguousarray(out[0], np.float32)


def parts_at(part_scores: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """The part of every pixel (an index into ``PARTS``, uint8) of the picture at ``size`` = (columns, rows): the scores are stretched to
    that size and the largest wins, so the borders between parts follow the picture smoothly at any size."""
    up = cv2.resize(part_scores, size, interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(up.argmax(axis=-1).astype(np.uint8))
