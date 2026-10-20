"""The titanium colours of a vector work and the assignment of its source colours (REQ-034, REQ-035, DEC-073..DEC-075)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import palette
from .common import lens_param, store_of

router = APIRouter(prefix="/api")


class AssignIn(BaseModel):
    device_id: int
    lens_id: int | None                   # required: null is the unknown lens
    material_id: int
    source_colours: list                  # {"index", "lab", "pixels"} or [index, lab, pixels]
    mode: str
    tolerance_de: float | None = None     # None: the saved rule of the laser and lens
    seed: int = 0
    max_time: float | None = None         # seconds per square centimetre
    keep: dict[str, str] | None = None    # source colour index -> palette entry id
    include_as_shot: bool = False         # colours measured as photographed take part in the choice (DEC-077)


@router.get("/vector-palette")
def vector_palette(request: Request, device_id: int, lens_id: str, material_id: int, max_time_s_per_cm2: float | None = None):
    """Every measured colour of this laser, lens and titanium stock that fills an area, one entry per recipe, with how it
    was measured, its evidence, settings and estimated engraving time; what was left out is counted by reason."""
    return palette.vector_palette(store_of(request), device_id, lens_param(lens_id), material_id, max_time_s_per_cm2)


@router.post("/vector-palette/assign")
def assign_palette(body: AssignIn, request: Request):
    """Give each source colour a colour of the palette by a recolouring mode (closest, tonality, random),
    keeping the operator's own choices."""
    return palette.assign_for(store_of(request), body.device_id, body.lens_id, body.material_id, body.source_colours, body.mode,
                              tolerance_de=body.tolerance_de, seed=body.seed, max_time=body.max_time, keep=body.keep,
                              include_as_shot=body.include_as_shot)
