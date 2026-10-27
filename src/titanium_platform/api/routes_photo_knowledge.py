"""What the workshop knows of photo engraving (feature photo-engraving-quality, REQ-003..REQ-005): the best measured settings of each kind
on a laser, lens and titanium with the measured effects of its settings and the experiment proposed; one step darker, lighter, sharper or
softer; the plate the laboratory proposes and the next plate of a photographed photo-variations plate."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import photo_knowledge, photo_results
from .common import store_of

router = APIRouter(prefix="/api")


class ResultMarkIn(BaseModel):
    source: dict
    aspect: str = 'photo'
    verdict: str
    note: str = ''


@router.post('/photo-results/mark')
def mark_photo_result(body: ResultMarkIn, request: Request):
    return photo_results.mark(store_of(request), body.source, body.verdict, body.note, body.aspect)


@router.get('/photo-results/work/{plan_id}')
def exported_photo_results(plan_id: int, request: Request, zone: int | None = None):
    return {'results': photo_results.for_work(store_of(request), plan_id, zone)}


@router.get("/photo-knowledge")
def photo_knowledge_of(request: Request, device_id: int, lens_id: int | None = None, material_id: int | None = None):
    """Every watched kind of photo engraving on the laser, lens and titanium (``photo_knowledge.knowledge``)."""
    return photo_knowledge.knowledge(store_of(request), device_id, lens_id, material_id)


@router.get("/photo-knowledge/everywhere")
def photo_knowledge_everywhere(request: Request):
    """The same on every laser, lens and titanium where a photo engraving was photographed (``photo_knowledge.everywhere``)."""
    return photo_knowledge.everywhere(store_of(request))


class AdjustIn(BaseModel):
    device_id: int
    lens_id: int | None = None
    material_id: int | None = None
    settings: dict
    direction: str
    allowed: list[str] | None = None        # the settings the owner can change (a grayscale work on its scale: Min and Max)


@router.post("/photo-knowledge/adjust")
def adjust_photo_engraving(body: AdjustIn, request: Request):
    """The settings one visible step darker, lighter, sharper or softer (``photo_knowledge.adjust``); nothing is changed."""
    return photo_knowledge.adjust(store_of(request), body.device_id, body.lens_id, body.material_id, body.settings, body.direction,
                                  None if body.allowed is None else tuple(body.allowed))


class ProposedIn(BaseModel):
    device_id: int
    lens_id: int | None = None
    material_id: int | None = None
    kind: str
    dot_width: bool = True                  # False: proposed to a photo zone, which writes no dot width correction


@router.post("/photo-knowledge/plate", status_code=201)
def make_proposed_plate(body: ProposedIn, request: Request):
    """The photo-variations plate the laboratory proposes for a kind (``photo_knowledge.proposed_plate``)."""
    return photo_knowledge.proposed_plate(store_of(request), body.device_id, body.lens_id, body.material_id, body.kind,
                                          dot_width=body.dot_width)


@router.post("/pairs/{pair_id}/next-variations", status_code=201)
def make_next_variations(pair_id: int, request: Request):
    """The next plate of a photographed photo-variations plate: centred on its best copy, the changes halved (DEC-003)."""
    return photo_knowledge.next_plate(store_of(request), pair_id)
