"""The predicted look of a photo engraving (REQ-030): upload a LightBurn file, see each image layer rendered from the measured
curve of its mode, change Min and Max power without uploading again.

The uploaded file is kept only in memory, at preview resolution, for a short time and in a bounded number of uploads: nothing
of it is written to the database or to disk.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict

import numpy as np
from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from .. import prediction, prediction_store, setup as su
from .common import MAX_LIGHTBURN_BYTES, lens_param, read_upload, store_of

router = APIRouter(prefix="/api")

KEEP_SECONDS = 30 * 60        # an upload is re-rendered for half an hour after it was last used
KEEP_UPLOADS = 8              # and at most this many uploads ...
KEEP_BYTES = 64 * 1024 * 1024  # ... holding at most this many bytes of pictures


class PreviewCache:
    """Prepared uploads by id, the least recently used dropped first once too many, too large or too old."""

    def __init__(self, uploads: int = KEEP_UPLOADS, size: int = KEEP_BYTES, seconds: float = KEEP_SECONDS):
        self.uploads, self.size, self.seconds = uploads, size, seconds
        self._items: OrderedDict[str, tuple[float, int, dict]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, layers: dict[int, dict]) -> str:
        key = uuid.uuid4().hex
        weight = sum(v.nbytes for item in layers.values() for v in item.values() if isinstance(v, np.ndarray))
        with self._lock:
            self._items[key] = (time.monotonic(), weight, layers)
            self._evict()
        return key

    def get(self, key: str) -> dict[int, dict]:
        with self._lock:
            self._evict()
            if key not in self._items:
                raise KeyError("the preview is no longer kept: upload the LightBurn file again")
            _, weight, layers = self._items.pop(key)
            self._items[key] = (time.monotonic(), weight, layers)
            return layers

    def __len__(self) -> int:
        return len(self._items)

    def _evict(self) -> None:
        now = time.monotonic()
        for key in [k for k, (used, _, _) in self._items.items() if now - used > self.seconds]:
            del self._items[key]
        while len(self._items) > self.uploads or (len(self._items) > 1 and sum(w for _, w, _ in self._items.values()) > self.size):
            self._items.popitem(last=False)


def _cache(request: Request) -> PreviewCache:
    state = request.app.state
    if getattr(state, "photo_previews", None) is None:
        state.photo_previews = PreviewCache()
    return state.photo_previews


def _layer(request: Request, cache_id: str, layer: int) -> dict:
    layers = _cache(request).get(cache_id)
    if layer not in layers:
        raise KeyError(f"image layer {layer} cannot be rendered in this upload")
    return layers[layer]


@router.post("/predictions/photo")
async def predict_photo(request: Request, device_id: int = Form(...), lens_id: str = Form(...), material_id: int | None = Form(None),
                        min_power: float | None = Form(None), max_power: float | None = Form(None), speed: float | None = Form(None),
                        frequency: float | None = Form(None), pulse_width: float | None = Form(None),
                        line_interval: float | None = Form(None), passes: int | None = Form(None),
                        lightburn: UploadFile = File(None)):
    """Every image layer of the file: refused with the reason, or predicted from the curve of its mode on this laser, lens and
    titanium (the file's settings, or the overrides given). The answer carries the id to re-render it at other Min and Max."""
    name, data = await read_upload(lightburn, MAX_LIGHTBURN_BYTES, "LightBurn")
    s = store_of(request)
    lens = lens_param(lens_id)
    su.resolve(s, device_id, lens)
    if material_id is not None and s.one("SELECT id FROM material_profile WHERE id=?", (material_id,)) is None:
        raise KeyError(f"titanium {material_id} not found")
    overrides = {"min_power": min_power, "max_power": max_power, "speed": speed, "frequency": frequency, "pulse_width": pulse_width,
                 "line_interval": line_interval, "passes": passes}
    prepared = prediction_store.prepare(s, data, device_id, lens, material_id, overrides)
    renderable = {item["index"]: item for item in prepared if not item["refused"]}
    cache_id = _cache(request).put(renderable) if renderable else None
    layers = []
    for item in prepared:
        if item["refused"]:
            layers.append({k: item[k] for k in ("index", "name", "dither", "settings", "refused")})
            continue
        info, _ = prediction_store.describe(item)
        layers.append({**info, "preview": f"/api/predictions/photo/{cache_id}/{item['index']}.png"})
    return {"cache_id": cache_id, "file": name, "device_id": device_id, "lens_id": lens, "material_id": material_id, "layers": layers}


@router.get("/predictions/photo/{cache_id}/{layer}.png")
def photo_preview(cache_id: str, layer: int, request: Request, min_power: float | None = None, max_power: float | None = None):
    """The picture and its predicted look side by side at Min..Max power, from the kept upload: no new upload."""
    _, image = prediction_store.describe(_layer(request, cache_id, layer), min_power, max_power)
    return Response(prediction.to_png(image), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/predictions/photo/{cache_id}/{layer}")
def photo_prediction(cache_id: str, layer: int, request: Request, min_power: float | None = None, max_power: float | None = None):
    """The description of the prediction at Min..Max power: the curve with the grey of each point, the share outside the span, notes."""
    info, _ = prediction_store.describe(_layer(request, cache_id, layer), min_power, max_power)
    return {**info, "preview": f"/api/predictions/photo/{cache_id}/{layer}.png"}
