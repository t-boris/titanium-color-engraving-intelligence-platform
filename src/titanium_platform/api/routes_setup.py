"""Materials, capture setups, rules per laser and lens, and the marker layer (REQ-010, REQ-009, REQ-005)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import plans, setup as su
from .common import lens_param, refresh_after_change, store_of

router = APIRouter(prefix="/api")


class MaterialIn(BaseModel):
    name: str
    family: str | None = None
    batch: str | None = None
    grade: str | None = None
    thickness_mm: float | None = None
    surface: str | None = None


class SetupIn(BaseModel):
    name: str
    camera: str
    lighting: str
    angle: str
    reference_chart: str


class RulesIn(BaseModel):
    device_id: int
    lens_id: int | None            # required: null is the unknown lens, a partition of its own (DEC-063)
    repeat_threshold: int | None = None
    delta_tolerance: float | None = None
    variance_threshold: float | None = None
    criteria_agreed: bool | None = None


class MarkerLayerIn(BaseModel):
    power: float
    frequency: float
    speed: float
    pulse_width: float | None = None       # optional: an omitted setting is left to LightBurn, never filled in (DEC-043)
    line_interval: float | None = None
    passes: int | None = None


@router.get("/rules")
def get_rules(request: Request, device_id: int, lens_id: str):
    """The evaluation rules of one laser and lens; ``lens_id=unknown`` for the works whose lens is not known."""
    s = store_of(request)
    lens = lens_param(lens_id)
    su.resolve(s, device_id, lens)
    return su.get_rules(s, device_id, lens)


@router.put("/rules")
def save_rules(body: RulesIn, request: Request):
    s = store_of(request)
    rules = su.save_rules(s, **body.model_dump())
    refresh_after_change(s, body.device_id, body.lens_id)  # new thresholds can promote (or flag) existing knowledge
    return rules


@router.get("/materials")
def list_materials(request: Request):
    return su.list_materials(store_of(request))


@router.post("/materials", status_code=201)
def create_material(body: MaterialIn, request: Request):
    return su.save_material(store_of(request), **body.model_dump())


@router.put("/materials/{material_id}")
def update_material(material_id: int, body: MaterialIn, request: Request):
    return su.save_material(store_of(request), **body.model_dump(), material_id=material_id)


@router.get("/setups")
def list_setups(request: Request):
    return su.list_capture_setups(store_of(request))


@router.post("/setups", status_code=201)
def create_setup(body: SetupIn, request: Request):
    return su.save_capture_setup(store_of(request), **body.model_dump())


@router.put("/setups/{setup_id}")
def update_setup(setup_id: int, body: SetupIn, request: Request):
    return su.save_capture_setup(store_of(request), **body.model_dump(), setup_id=setup_id)


@router.delete("/setups/{setup_id}", status_code=204)
def delete_setup(setup_id: int, request: Request):
    su.delete_capture_setup(store_of(request), setup_id)


@router.get("/marker-layer")
def get_marker_layer(request: Request):
    return plans.marker_layer_settings(store_of(request))


@router.put("/marker-layer")
def put_marker_layer(body: MarkerLayerIn, request: Request):
    return plans.save_marker_layer_settings(store_of(request), body.power, body.frequency, body.speed, body.pulse_width,
                                            body.line_interval, body.passes)
