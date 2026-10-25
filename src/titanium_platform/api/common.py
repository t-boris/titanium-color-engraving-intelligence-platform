"""Shared API plumbing: store access, error mapping, upload limits, response shaping."""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from .. import analysis, conversion, designer, ingest, knowledge, photo, prediction, recheck, render_cache, setup as su, vectorize
from ..db import ImmutableError, Store

MAX_LIGHTBURN_BYTES = 100 * 1024 * 1024
MAX_PHOTO_BYTES = 600 * 1024 * 1024
MAX_IMAGE_BYTES = 60 * 1024 * 1024

USER_ERRORS = (su.ValidationError, ingest.IngestError, conversion.ConversionError, designer.DesignerError,
               knowledge.KnowledgeError, photo.PhotoError, vectorize.VectorizeError, prediction.PredictionError)
IMAGE_SIGNATURES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF8", "image/gif"), (b"BM", "image/bmp"),
                    (b"II*\x00", "image/tiff"), (b"MM\x00*", "image/tiff"))


def image_media_type(data: bytes) -> str:
    """The media type of a stored image from its first bytes (images are stored without their name)."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return next((kind for magic, kind in IMAGE_SIGNATURES if data.startswith(magic)), "application/octet-stream")


def store_of(request: Request) -> Store:
    return request.app.state.store


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(su.ProtectedError)
    async def protected(_, exc):
        return JSONResponse({"error": str(exc), "kind": "protected"}, status_code=409)

    @app.exception_handler(ImmutableError)
    async def immutable(_, exc):
        return JSONResponse({"error": str(exc), "kind": "immutable"}, status_code=409)

    @app.exception_handler(recheck.Busy)
    async def busy(_, exc):
        return JSONResponse({"error": str(exc), "kind": "busy"}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse({"error": str(exc.args[0]) if exc.args else "not found", "kind": "not_found"}, status_code=404)

    for cls in USER_ERRORS:
        @app.exception_handler(cls)
        async def user_error(_, exc):
            return JSONResponse({"error": str(exc), "kind": "invalid"}, status_code=422)


async def read_upload(file: UploadFile | None, limit: int, label: str) -> tuple[str, bytes]:
    """Read an uploaded file, refusing a missing, empty or oversized one with a message the operator can act on."""
    if file is None or not file.filename:
        raise HTTPException(422, {"error": f"choose the {label} file", "kind": "invalid"})
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, {"error": f"the {label} file is larger than {limit // (1024 * 1024)} MB", "kind": "too_large"})
    if not data:
        raise HTTPException(422, {"error": f"the {label} file is empty", "kind": "invalid"})
    return file.filename, data


PICTURE_CACHE_CONTROL = "private, max-age=0, must-revalidate"


def picture_response(request: Request, picture: render_cache.Picture) -> Response:
    """A picture drawn from a photograph, with its cache key as ETag (BUG-001). The browser keeps the picture and asks again
    every time; when its copy is still the current one (``If-None-Match``) the answer is 304 with no body, without drawing."""
    etag = f'"{picture.key}"'
    headers = {"ETag": etag, "Cache-Control": PICTURE_CACHE_CONTROL}
    sent = [tag.strip() for tag in request.headers.get("if-none-match", "").split(",")]
    if any(tag == "*" or tag.removeprefix("W/") == etag for tag in sent):
        return Response(status_code=304, headers=headers)
    return Response(picture.png(), media_type="image/png", headers=headers)


def public_pair(pair: dict) -> dict:
    """A pair without server file paths."""
    return {k: v for k, v in pair.items() if k not in ("lightburn_path", "photo_path")}


def public_plan(plan: dict, with_regions: bool = False) -> dict:
    """A plan without server file paths; layer regions are summarised unless asked for (they can number thousands)."""
    out = {k: v for k, v in plan.items() if k not in ("image_path", "labels_path")}
    layers = []
    for layer in plan.get("layers", []):
        item = dict(layer)
        regions = item.pop("regions", [])
        item["region_count"] = len(regions)
        if with_regions:
            item["regions"] = regions
        layers.append(item)
    out["layers"] = layers
    if isinstance(out.get("evidence_source"), dict):        # a pinned work's kept palette is a server file
        out["evidence_source"] = {k: v for k, v in out["evidence_source"].items() if k != "palette_path"}
    markers = out.get("markers")
    if markers:  # the marker rectangles are file geometry; the UI needs only where they are
        out["markers"] = {"identifier": markers["identifier"], "extent": markers["extent"], "settings": markers["settings"],
                          "aruco": [{"id": a["id"], "x": a["x"], "y": a["y"], "size": a["size"]} for a in markers["aruco"]],
                          "qr": {k: markers["qr"][k] for k in ("x", "y", "size", "module", "modules")}}
    return out


def content_disposition(name: str, extension: str) -> str:
    """A ``Content-Disposition`` header that survives any plan name (RFC 6266 / RFC 5987).

    HTTP header values must be Latin-1, but plan names are typed in a Russian UI. The plain ``filename`` is an
    ASCII fallback (every other character becomes ``_``); ``filename*`` carries the real name as UTF-8, which
    current browsers prefer. Quotes, backslashes, control characters and path separators never reach the header.
    """
    from urllib.parse import quote

    cleaned = "".join(c for c in name if c.isprintable() and c not in '"\\/:*?<>|%').strip(" .") or "plan"
    ascii_name = "".join(c if c.isascii() and (c.isalnum() or c in "-_. ") else "_" for c in cleaned).strip(" .") or "plan"
    return f"attachment; filename=\"{ascii_name}{extension}\"; filename*=UTF-8''{quote(cleaned + extension, safe='')}"


def refresh_after_change(store: Store, device_id: int, lens_id: int | None) -> None:
    knowledge.refresh(store, device_id, lens_id)


def task_goals(goals: str | None) -> dict | None:
    """The goals of a plan's engraving task from a form field: a JSON object, or nothing (REQ-020)."""
    if goals in (None, ""):
        return None
    try:
        value = json.loads(goals)
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, dict):
        raise su.ValidationError("the task goals must be a JSON object")
    return value


def form_flag(value: str | None, default: bool, name: str) -> bool:
    """A yes/no form field read the same way under every FastAPI version: absent or empty gives ``default`` (a script may
    leave the field out; FastAPI 0.148 reads a missing ``bool`` field as false, like an unticked HTML checkbox), else
    true/false, 1/0, on/off or yes/no."""
    if value is None or not value.strip():
        return default
    text = value.strip().lower()
    if text in ("true", "1", "on", "yes"):
        return True
    if text in ("false", "0", "off", "no"):
        return False
    raise su.ValidationError(f"{name} must be true or false")


def lens_param(value: str | None) -> int | None:
    """A lens given in a form or a query: its record id, or ``unknown`` for a work whose lens is not known (DEC-063).
    It is never left out, so an unknown lens is always an explicit choice."""
    text = (value or "").strip()
    if text == "unknown":
        return None
    if not text.isdigit():
        raise su.ValidationError("choose the lens or mark it unknown")
    return int(text)
