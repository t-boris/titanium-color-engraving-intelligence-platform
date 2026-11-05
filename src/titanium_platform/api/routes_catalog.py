"""The shared catalog of works (feature ux-work-catalog-p0): one read-only list over the vector works and the photo engraving works, and one
work by its key. Opening, renaming, copying and deleting a work are the routes of its own kind (``/api/vector``, ``/api/photo-works``,
``DELETE /api/plans/{id}``); each entry names them (``open``, ``base``). See :mod:`titanium_platform.catalog`."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from .. import catalog
from .common import store_of

router = APIRouter(prefix="/api")


@router.get("/works")
def list_works(request: Request, q: str = "", type: str = "", laser: str = "", lens: str = "", material: str = "", sort: str = "modified",
               offset: int = Query(0, ge=0), limit: int = Query(catalog.PAGE, ge=1, le=catalog.MAX_PAGE), through: str | None = None):
    """A portion of the catalog for a search, the filters (type, laser, lens, material; ``none`` for a work that has none) and a sort
    (``modified``, ``oldest``, ``name``): its works, how many pass, the count each filter value would give, the values to offer and how
    many works there are. ``through`` (a work's key) grows the portion to whole pages up to that work, for a return to it."""
    return catalog.list_works(store_of(request), q=q, type=type, laser=laser, lens=lens, material=material, sort=sort,
                              offset=offset, limit=limit, through=through)


@router.get("/works/{key}")
def get_work(key: str, request: Request):
    """One work by its key (``vector-12``, ``photo-12``) or by its plan id; 404 when there is no such work."""
    return catalog.get_work(store_of(request), key)
