"""The shared catalog of works (feature ux-work-catalog-p0, REQ-001, REQ-002): one list over the vector works and the photo engraving works.

The catalog is a READ MODEL. It owns no record, writes nothing and never opens a work's document or picture: every entry is made from
the plan row a work already is (``plan`` holds both kinds, so a work keeps its owner, its id and its editor) and from the few facts its
stored data keeps. Opening, renaming, copying and deleting a work stay the operations of its own kind (``/api/vector``,
``/api/photo-works``, ``DELETE /api/plans/{id}``); an entry only says where they are (``open`` and ``base``).

Identity
    ``key`` is ``<kind>-<plan id>`` (``vector-12``, ``photo-12``). The plan id is unique in the ``plan`` table, so the two kinds cannot
    collide today; the key still carries the kind so that an entry is never found by an id alone through the catalog's own routes, and so
    that two sources which did number their works apart would stay two entries (``merge``). A bare number is accepted by :func:`get_work`
    and is resolved to the one work that has it.

Type (what the operator filters by; each work has exactly one)
    ``vector``  a vector document without photo zones; ``mixed``  a vector document that has at least one photo zone (one document with its
    regions, its photo zones and its inscriptions: it is never listed twice); ``photo``  a photo engraving work (grayscale picture).
    Inscriptions alone do not make a work mixed; their number is shown beside the zones'.

State (the same words as the chain of an engraving, ux-engraving-lifecycle-p0; derived, nothing is stored for it)
    ``prepared``  nothing recorded after the work was made; ``exported``  a file of the work was handed out (a vector work records its
    exported files; a photo work records one only when it is pinned to a laboratory release, so an unpinned photo work stays ``prepared``
    until it is photographed); ``result``  a photograph of its engraving was added; ``checked``  one of those photographs was accepted.
    The rule is one function, :func:`state_of`, so the lifecycle can take it over.

Missing data (a work is never dropped from the list for lacking something)
    no readable data: listed with ``broken`` set (its name, kind and equipment still come from the row) so that it can be deleted;
    no size or no date: ``null`` and named in ``missing``; the date falls back to the creation time and sorts after every dated work;
    an equipment id that is not in its table: ``{"id": N, "name": null}``; no lens: ``null`` is the explicit "lens unknown" (DEC-063), not a
    gap; no material: ``null`` and named in ``missing``. The filters offer ``none`` (the id the equipment filters use for "has none") with
    the number of such works.

Search: every word of the query must occur, in any order and in any case, in the name, the laser, the lens, the material or ``№<id>``.
Counts: the count of a filter's value is what the list would show if that value were chosen with the search and the other filters as they are.
Order: a total order (the sort key, then the id and the kind), so the pages of one query neither skip a work nor repeat one.
"""
from __future__ import annotations

import json
import math
import re
import threading
import weakref
from collections import Counter
from urllib.parse import quote

from . import ingest as ig, plans as pl
from .db import Store

VECTOR, PHOTO = "vector", "photo"
MIXED = "mixed"
KIND_OF_MODE = {pl.MODE_VECTOR: VECTOR, pl.MODE_PHOTO_WORK: PHOTO}
TYPES = (VECTOR, MIXED, PHOTO)
STATES = ("prepared", "exported", "result", "checked")
SORTS = ("modified", "oldest", "name")
FILTERS = ("type", "laser", "lens", "material")
NONE = "none"                       # the value of an equipment filter for the works that have no such equipment
PAGE = 20                           # the size of a portion of the list
MAX_PAGE = 400                      # the most one request may ask for: a read that restores the portions already shown (as far as MAX_THROUGH)
MAX_THROUGH = 400                   # the most a request that must reach one work (``through``) is extended to
KEY = re.compile(r"^(vector|photo)-(\d+)$")

_lock = threading.Lock()
_facts_memo: dict[tuple, dict] = {}
_FACTS_MEMO_SIZE = 6000
_listed: "weakref.WeakKeyDictionary[Store, tuple]" = weakref.WeakKeyDictionary()      # store -> (stamp, entries): the entries of an unchanged database


def key_of(kind: str, plan_id: int) -> str:
    return f"{kind}-{plan_id}"


def state_of(exports: int, checks: int, accepted: int) -> str:
    """The state of a work from the files handed out and the photographs of its engraving (see the module's note)."""
    if accepted:
        return "checked"
    if checks:
        return "result"
    return "exported" if exports else "prepared"


def _number(value) -> float | None:
    return round(float(value), 2) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _text(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _count(value) -> int:
    return len(value) if isinstance(value, (list, tuple)) else 0


def _vector_facts(data: dict) -> dict:
    size = data.get("size_mm") if isinstance(data.get("size_mm"), dict) else {}
    history = data.get("history") if isinstance(data.get("history"), list) else []
    last = history[-1] if history and isinstance(history[-1], dict) else {}
    colouring = data.get("colouring") if isinstance(data.get("colouring"), dict) else {}
    version = data.get("document_version")
    return {"width": _number(size.get("width")), "height": _number(size.get("height")), "updated": _text(last.get("at")),
            "zones": _count(colouring.get("photo")), "texts": _count(colouring.get("texts")), "exports": _count(data.get("exports")),
            "material_id": data.get("material_id"), "version": version if isinstance(version, int) else 0}


def _photo_facts(data: dict) -> dict:
    image = data.get("image_size") if isinstance(data.get("image_size"), (list, tuple)) else []
    width = _number(data.get("width_mm"))
    cols, rows = (image + [None, None])[:2]
    height = _number(width * rows / cols) if width is not None and _number(cols) and _number(rows) else None
    scale = data.get("scale") if isinstance(data.get("scale"), dict) else {}
    source = data.get("evidence_source") if isinstance(data.get("evidence_source"), dict) else {}
    return {"width": width, "height": height, "updated": _text(data.get("updated_at")), "zones": 0, "texts": _count(data.get("texts")),
            "exports": 1 if source.get("confirmed") else 0, "material_id": scale.get("material_id"), "version": 0}


BROKEN = {"width": None, "height": None, "updated": None, "zones": 0, "texts": 0, "exports": 0, "material_id": None, "version": 0, "broken": True}


def _facts(kind: str, row) -> dict:
    """What the work's stored data says of it, read once for each version of the data (a work's data is replaced whole when it changes)."""
    blob = row["data_json"] or ""
    token = (row["id"], kind, len(blob), hash(blob))
    with _lock:
        known = _facts_memo.get(token)
    if known is not None:
        return known
    try:
        data = json.loads(blob)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        made = {**(_vector_facts(data) if kind == VECTOR else _photo_facts(data)), "broken": False}
    except ValueError:
        made = BROKEN
    with _lock:
        if len(_facts_memo) >= _FACTS_MEMO_SIZE:
            _facts_memo.clear()
        _facts_memo[token] = made
    return made


def _equipment(store: Store) -> dict[str, dict]:
    return {"laser": {r["id"]: r["name"] for r in store.query("SELECT id, name FROM laser_device")},
            "lens": {r["id"]: r["name"] for r in store.query("SELECT id, name FROM lens")},
            "material": {r["id"]: r["name"] for r in store.query("SELECT id, name FROM material_profile")}}


def _photographs(store: Store) -> dict[int, tuple[int, int]]:
    """Plan id -> (photographs of its engraving in use, accepted ones)."""
    rows = store.query("SELECT plan_id, COUNT(*) AS n, SUM(CASE WHEN status=? THEN 1 ELSE 0 END) AS accepted FROM pair "
                       "WHERE plan_id IS NOT NULL AND status!=? GROUP BY plan_id", (ig.ST_ACCEPTED, ig.ST_DELETED))
    return {r["plan_id"]: (r["n"], r["accepted"] or 0) for r in rows}


def _reference(ident, names: dict) -> dict | None:
    return None if ident is None else {"id": ident, "name": names.get(ident)}


def _entry(kind: str, row, facts: dict, names: dict, photographs: dict) -> dict:
    """One work as the catalog lists it. ``names`` are the equipment tables, ``photographs`` the checks of every work."""
    plan_id = row["id"]
    updated = facts["updated"] or _text(row["created_at"])
    material = _reference(facts["material_id"] if isinstance(facts["material_id"], int) else None, names["material"])
    laser, lens = _reference(row["device_id"], names["laser"]), _reference(row["lens_id"], names["lens"])
    checks, accepted = photographs.get(plan_id, (0, 0))
    mixed = kind == VECTOR and facts["zones"] > 0
    stamp = quote(f"{facts['version']}-{updated or ''}", safe="")
    missing = [name for name, absent in (("size", facts["width"] is None or facts["height"] is None), ("date", updated is None),
                                         ("laser", laser is None), ("material", material is None)) if absent]
    return {"key": key_of(kind, plan_id), "id": plan_id, "kind": kind, "type": MIXED if mixed else kind, "name": _text(row["name"]) or f"Work #{plan_id}",
            "width_mm": facts["width"], "height_mm": facts["height"], "state": state_of(facts["exports"], checks, accepted),
            "created_at": row["created_at"], "updated_at": updated, "checks": checks, "zones": facts["zones"], "texts": facts["texts"],
            "laser": laser, "lens": lens, "material": material, "missing": missing, "broken": facts["broken"],
            "thumb": f"/api/vector/{plan_id}/thumb.png?v={stamp}" if kind == VECTOR else f"/api/photo-works/{plan_id}/thumb.png?v={stamp}",
            "open": f"/vector?plan={plan_id}" if kind == VECTOR else f"/photo-engraving?work={plan_id}",
            "base": "/vector" if kind == VECTOR else "/photo-works"}


def merge(*sources: list[dict]) -> list[dict]:
    """The entries of several sources as one list. A source that numbers its works apart from the others cannot take another's entry away:
    entries are told apart by their key (kind and id); the same key twice is one work and the first source's entry stays."""
    seen: dict[str, dict] = {}
    for source in sources:
        for entry in source:
            seen.setdefault(entry["key"], entry)
    return list(seen.values())


def _rows(store: Store, where: str = "", params: tuple = ()):
    return store.query("SELECT id, name, mode, device_id, lens_id, created_at, data_json FROM plan "
                       f"WHERE mode IN (?, ?) AND status!='Deleted'{where}", (pl.MODE_VECTOR, pl.MODE_PHOTO_WORK, *params))


def _build(store: Store, rows) -> list[dict]:
    names, photographs = _equipment(store), _photographs(store)
    by_kind: dict[str, list[dict]] = {VECTOR: [], PHOTO: []}
    for row in rows:
        kind = KIND_OF_MODE[row["mode"]]
        by_kind[kind].append(_entry(kind, row, _facts(kind, row), names, photographs))
    return merge(by_kind[VECTOR], by_kind[PHOTO])


def all_works(store: Store) -> list[dict]:
    """Every work of the workshop as an entry. The entries of an unchanged database are kept (``Store.stamp``), so paging and searching read
    nothing again; any write, by this connection or another, builds them anew."""
    stamp = store.stamp()
    with _lock:
        cached = _listed.get(store)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    entries = _build(store, _rows(store))
    with _lock:
        _listed[store] = (stamp, entries)
    return entries


def get_work(store: Store, key) -> dict:
    """One work by its key (``vector-12``) or by its plan id alone; KeyError when there is none of that kind (the API answers 404)."""
    text = str(key).strip()
    found = KEY.match(text)
    if found:
        kind, plan_id = found.group(1), int(found.group(2))
    elif text.isdigit():
        kind, plan_id = None, int(text)
    else:
        raise KeyError(f"plan {text} not found")
    rows = _rows(store, " AND id=?", (plan_id,))
    entries = _build(store, rows)
    if not entries or (kind is not None and entries[0]["kind"] != kind):
        raise KeyError(f"plan {plan_id} not found")
    return entries[0]


# -- the query ---------------------------------------------------------------------------------------------------------------------------
def _value(entry: dict, name: str) -> str:
    """The value of a work for a filter: its type, or the id of its equipment (``none`` when it has none)."""
    if name == "type":
        return entry["type"]
    reference = entry[name]
    return NONE if reference is None else str(reference["id"])


def _haystack(entry: dict) -> str:
    parts = [entry["name"], f"№{entry['id']}", *(entry[n]["name"] or "" for n in ("laser", "lens", "material") if entry[n])]
    return " ".join(parts).casefold()


def _sort_key(entry: dict, sort: str):
    if sort == "name":
        return (entry["name"].casefold(), entry["id"], entry["kind"])
    return (entry["updated_at"] or "", entry["id"], entry["kind"])


def _ordered(entries: list[dict], sort: str) -> list[dict]:
    if sort == "name":
        return sorted(entries, key=lambda e: _sort_key(e, "name"))
    dated = sorted((e for e in entries if e["updated_at"]), key=lambda e: _sort_key(e, sort), reverse=sort != "oldest")
    return dated + sorted((e for e in entries if not e["updated_at"]), key=lambda e: (e["id"], e["kind"]))      # a work with no date is last


def _facets(entries: list[dict]) -> dict:
    out: dict[str, list] = {"type": list(TYPES)}
    for name in ("laser", "lens", "material"):
        known = {e[name]["id"]: e[name]["name"] for e in entries if e[name] is not None}
        listed = [{"value": str(i), "name": known[i]} for i in sorted(known, key=lambda i: ((known[i] or "").casefold(), i))]
        if any(e[name] is None for e in entries):
            listed.append({"value": NONE, "name": None})
        out[name] = listed
    return out


def list_works(store: Store, *, q: str = "", type: str = "", laser: str = "", lens: str = "", material: str = "", sort: str = "modified",
               offset: int = 0, limit: int = PAGE, through: str | None = None) -> dict:
    """One portion of the catalog for a query: ``items`` (``offset`` ..), ``total`` (works that pass), ``counts`` (per filter: the works
    each value would show, ``""`` for all), ``facets`` (the values each filter offers) and ``all`` (works at all). ``through`` is the key of a
    work the portion must reach (the person came back to it): ``limit`` grows to whole portions up to it, as far as MAX_THROUGH."""
    sort = sort if sort in SORTS else "modified"
    chosen = {"type": type, "laser": laser, "lens": lens, "material": material}
    words = q.casefold().split()
    entries = all_works(store)

    def passes(entry: dict, haystack: str, skip: str | None) -> bool:
        return all(word in haystack for word in words) and all(not chosen[n] or n == skip or _value(entry, n) == chosen[n] for n in FILTERS)

    stacks = [(entry, _haystack(entry)) for entry in entries]
    shown = _ordered([entry for entry, hay in stacks if passes(entry, hay, None)], sort)
    counts: dict[str, dict[str, int]] = {}
    for name in FILTERS:
        tally = Counter(_value(entry, name) for entry, hay in stacks if passes(entry, hay, name))
        counts[name] = {"": sum(tally.values()), **tally}
    offset, limit = max(0, offset), max(1, min(limit, MAX_PAGE))
    if through:
        at = next((i for i, entry in enumerate(shown) if entry["key"] == through), None)
        end = None if at is None else -(-(at + 1) // PAGE) * PAGE            # the whole portions up to that work
        if end is not None and end <= MAX_THROUGH:
            limit = max(limit, end - offset)
    return {"items": shown[offset:offset + limit], "total": len(shown), "counts": counts, "facets": _facets(entries), "all": len(entries)}
