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

from .. import devices, grayscale, plans, prediction, prediction_review, prediction_store, setup as su
from .common import MAX_IMAGE_BYTES, MAX_LIGHTBURN_BYTES, content_disposition, lens_param, read_upload, store_of

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
    setup = su.resolve(s, device_id, lens)
    if pulse_width is not None:                 # a width the laser does not offer is refused with its steps (REQ-017)
        devices.require_selectable(setup["device"]["passport"], pulse_width)
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
            layers.append({k: item[k] for k in ("index", "name", "dither", "settings", "refused", "measured_on")})
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


# -- grayscale scales and a picture engraved on one (REQ-059) ---------------------------------------------------------------------
def _scale_mode(request: Request, device_id: int, lens_id: str, material_id: int | None, speed: float, frequency: float,
                pulse_width: float | None, line_interval: float, passes: int, global_passes: int) -> prediction_store.Mode:
    lens = lens_param(lens_id)
    su.resolve(store_of(request), device_id, lens)
    return prediction_store.mode_of({"speed": speed, "frequency": frequency, "pulse_width": pulse_width, "line_interval": line_interval,
                                     "passes": passes, "global_passes": global_passes}, device_id, lens, material_id)


@router.get("/grey-scales")
def grey_scales(request: Request, device_id: int | None = None, lens_id: str | None = None, material_id: int | None = None):
    """Every measured grayscale scale (one per set of fixed settings), optionally of one laser, lens and titanium: its colour bar over the
    measured powers, what measured it, whether the engravings confirm each other and its time per square centimetre."""
    lens = lens_param(lens_id) if lens_id else None
    return {"scales": prediction_store.scales(store_of(request), device_id, lens, material_id)}


@router.get("/pairs/{pair_id}/prediction-review")
def prediction_review_of(pair_id: int, request: Request):
    """What the grey scale predicted for an accepted photo engraving before it was engraved and what its photograph measured, with the
    facts the prediction rested on (DEC-117)."""
    return prediction_review.review(store_of(request), pair_id)


@router.get("/prediction-reviews")
def prediction_reviews(request: Request):
    """Every accepted photo engraving's review together: the measure a change of the model has to lower (DEC-117)."""
    return prediction_review.summary(store_of(request))


@router.get("/grey-scales/scale")
def grey_scale(request: Request, device_id: int, lens_id: str, speed: float, frequency: float, line_interval: float,
               material_id: int | None = None, pulse_width: float | None = None, passes: int = 1, global_passes: int = 1,
               min_power: float | None = None, max_power: float | None = None, row_mm: float | None = None):
    """One scale in full at a size (rows ``row_mm`` long; by default the size most engravings measured): which grey makes which colour at
    Min..Max, the measured points with their sources, each engraving against the others and the fills of the same settings beside it."""
    mode = _scale_mode(request, device_id, lens_id, material_id, speed, frequency, pulse_width, line_interval, passes, global_passes)
    return prediction_store.scale(store_of(request), mode, min_power, max_power, row_mm)


def _picture_answer(store, cache_id: str, item: dict, min_power, max_power, width_mm: float) -> dict:
    """The kept picture at ``width_mm`` (its curve made for that size, DEC-107)."""
    low, high = prediction_store.check_power_range(item["settings"]["min_power"] if min_power is None else min_power,
                                                   item["settings"]["max_power"] if max_power is None else max_power)
    shown = prediction_store.engraved(item, low, high)
    info, _ = prediction_store.describe(shown, low, high)
    cols, rows = item["size"]
    height_mm = width_mm * rows / cols
    query = f"min_power={low:g}&max_power={high:g}&width_mm={width_mm:g}"
    return {**info, "cache_id": cache_id, "by_colour": item["by_colour"], "colour_match": shown.get("colour_match"),
            "contours_report": shown.get("contours_report"),
            "size_mm": {"width": width_mm, "height": round(height_mm, 2)}, "time": prediction_store.picture_time(item["mode"], width_mm, height_mm,
                                                                                           prediction_store.cleaning(store, item["mode"])),
            "dpi": grayscale.image_dpi(item["mode"].line_interval),
            "preview": f"/api/grey-scales/picture/{cache_id}.png?{query}", "file": f"/api/grey-scales/picture/{cache_id}.lbrn2?{query}"}


def _kept_picture(request: Request, cache_id: str) -> dict:
    try:
        item = _cache(request).get(cache_id).get(0)
    except KeyError:
        item = None
    if item is None or "by_colour" not in item:
        raise KeyError("the preview is no longer kept: upload the picture again")
    return item


@router.post("/grey-scales/picture")
async def grey_picture(request: Request, device_id: int = Form(...), lens_id: str = Form(...), speed: float = Form(...),
                       frequency: float = Form(...), line_interval: float = Form(...), width_mm: float = Form(...),
                       material_id: int | None = Form(None), pulse_width: float | None = Form(None), passes: int = Form(1),
                       global_passes: int = Form(1), min_power: float | None = Form(None), max_power: float | None = Form(None),
                       by_colour: bool = Form(False), picture: UploadFile = File(None)):
    """A picture (PNG, JPEG ...) engraved on a scale: the picture beside its predicted look, at the scale's measured powers unless Min
    and Max are given, the time for its size and the link to its LightBurn file. With ``by_colour`` the picture's colours are wanted
    and the greys that come nearest to them on the scale are chosen. The upload is kept in memory only, as the LightBurn previews are."""
    name, data = await read_upload(picture, MAX_IMAGE_BYTES, "picture")
    mode = _scale_mode(request, device_id, lens_id, material_id, speed, frequency, pulse_width, line_interval, passes, global_passes)
    width = prediction_store.check_width(width_mm)
    item = prediction_store.picture_item(store_of(request), mode, prediction_store.decode_upload(data), name.rsplit(".", 1)[0], by_colour, width)
    cache_id = _cache(request).put({0: item})
    return _picture_answer(store_of(request), cache_id, item, min_power, max_power, width)


@router.get("/grey-scales/picture/{cache_id}.png")
def grey_picture_png(cache_id: str, request: Request, width_mm: float, min_power: float | None = None, max_power: float | None = None):
    item = prediction_store.at_width(store_of(request), _kept_picture(request, cache_id), width_mm)
    low, high = prediction_store.check_power_range(item["settings"]["min_power"] if min_power is None else min_power,
                                                   item["settings"]["max_power"] if max_power is None else max_power)
    shown = prediction_store.engraved(item, low, high)
    _, image = prediction_store.describe(shown, low, high)
    return Response(prediction.to_png(image), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/grey-scales/picture/{cache_id}.lbrn2")
def grey_picture_file(cache_id: str, request: Request, min_power: float, max_power: float, width_mm: float):
    """The LightBurn file of the picture: the cleaning, then one grayscale Image layer at the scale's settings and the chosen Min and Max,
    the picture at the chosen width (with ``by_colour`` the greys chosen keeping the drawing, DEC-108), the lost edges drawn in as the
    preview shows them."""
    width = prediction_store.check_width(width_mm)
    s = store_of(request)
    item = prediction_store.at_width(s, _kept_picture(request, cache_id), width)
    low, high = prediction_store.check_power_range(min_power, max_power)
    picture = prediction_store.picture_for_file(item, low, high, width)
    parameters = prediction_store.file_parameters(item["mode"], low, high)
    return Response(plans.export_picture(picture, width, parameters, item["name"], clean=prediction_store.cleaning(s, item["mode"])),
                    media_type="application/octet-stream",
                    headers={"Content-Disposition": content_disposition(f"{item['name']}-P{low:g}-{high:g}", ".lbrn2"), "Cache-Control": "no-store"})


@router.get("/grey-scales/picture/{cache_id}")
def grey_picture_info(cache_id: str, request: Request, width_mm: float, min_power: float | None = None, max_power: float | None = None):
    width = prediction_store.check_width(width_mm)
    s = store_of(request)
    return _picture_answer(s, cache_id, prediction_store.at_width(s, _kept_picture(request, cache_id), width), min_power, max_power, width)
