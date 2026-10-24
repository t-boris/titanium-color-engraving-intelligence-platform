"""The fonts of the inscriptions (feature inscriptions-in-works, REQ-001, DEC-001): the catalogue of this computer's fonts, the operator's
own and Google Fonts, the text drawn in one font for the font window, the operator's font files added and removed, Google families
downloaded one at a time or many in the background. An inscription itself is an operation of its work (``/api/vector/{id}/colouring``,
``/api/photo-works/{id}/settings``)."""
from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import Response

from .. import fonts, lettering
from .common import read_upload, store_of

router = APIRouter(prefix="/api/fonts")
PREVIEW_CACHE = "private, max-age=86400"       # a face's id changes with its file, the text is in the address


@router.get("")
def list_fonts(request: Request):
    """Every family of every source with its faces, kinds and scripts, and the Google families not downloaded yet (fonts.families)."""
    return fonts.families(store_of(request).data_dir)


@router.get("/preview.svg")
def preview(request: Request, face: str, text: str = "", height: float = 10.0):
    """``text`` (the sample when empty) in the face ``face`` as the file would get it; a letter the font lacks is drawn red."""
    height = min(max(float(height), 1.0), 100.0)
    svg = lettering.preview_svg(store_of(request).data_dir, face, text, height)
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": PREVIEW_CACHE})


@router.post("/own", status_code=201)
async def add_own(request: Request, font: UploadFile = File(None)):
    """Add a font file (TTF, OTF, TTC) to the operator's fonts; its faces."""
    name, data = await read_upload(font, fonts.MAX_OWN_BYTES, "font")
    return {"faces": fonts.add_own(store_of(request).data_dir, name, data)}


@router.delete("/own/{face_id}")
def remove_own(face_id: str, request: Request):
    """Take away the operator's font file of this face."""
    fonts.remove_own(store_of(request).data_dir, face_id)
    return {"removed": face_id}


@router.post("/google/index")
def google_index(request: Request):
    """Fetch the list of Google's families again."""
    index = fonts.google_index(store_of(request).data_dir, refresh=True)
    return {"families": len(index["families"]), "fetched_at": index["fetched_at"]}


@router.post("/google/family")
def google_family(request: Request, body: dict):
    """Download one Google family (``family``) unless it is here; its faces."""
    return {"faces": fonts.google_faces(store_of(request).data_dir, body.get("family"))}


@router.post("/google/download")
def google_download(request: Request, body: dict):
    """Download many Google families in the background: ``families``, or every family of a ``script`` and/or ``kind``; the progress."""
    return fonts.start_download(store_of(request).data_dir, body)


@router.get("/google/status")
def google_status():
    return fonts.download_status()
