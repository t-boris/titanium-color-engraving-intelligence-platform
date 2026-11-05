"""The history of a knowledge entry a page at a time, and the photographs behind observation numbers (ux-growing-collections-p0, REQ-002)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from .. import knowledge, provenance
from .common import store_of

router = APIRouter(prefix="/api")


@router.get("/knowledge/{kid}/history")
def knowledge_history(kid: int, request: Request, type: str | None = None, order: str = "newest", offset: int = 0, limit: int = 20):
    """One page of the history of a knowledge entry: ``{items, total, all, counts}``. The newest events come first unless ``order=oldest``;
    ``type`` keeps one kind of event."""
    return knowledge.history_page(store_of(request), kid, event_type=type or "", newest_first=order != "oldest", offset=offset, limit=limit)


@router.get("/observations/refs")
def observation_refs(request: Request, ids: str = ""):
    """The photograph and layer of each observation number in ``ids`` (comma-separated, at most 200): ``[{id, pair_id, layer_name, ...}]``."""
    numbers = [int(part) for part in ids.split(",") if part.strip().isdigit()]
    return provenance.observation_refs(store_of(request), numbers)
