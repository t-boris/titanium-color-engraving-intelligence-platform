"""The catalogue of titanium stock records: search, filters, order and pages (feature ux-growing-collections-p0, REQ-001).

A stock record is one concrete batch or sheet (DEC-088, DEC-110); the grade ("Grade 2") is what records of one titanium have in common. The
catalogue keeps that difference visible: a page lists concrete records, and the grade is a filter over them. The collection is read once per
request (the record is small and a workshop holds hundreds or a few thousand, not millions), searched and ordered here, and one page of it is
returned, so a screen never has to hold the whole list.
"""
from __future__ import annotations

from .db import Store
from .setup import _plain

SORTS = ("id", "recent", "name", "grade", "thickness", "newest")      # ``id`` is the order of the plain list that older screens read
PAGE_MAX = 200
NO_GRADE = "__none__"                      # the value of the filter «без марки»: records that name no grade
FILTERS = ("family", "grade")


def last_used(store: Store) -> dict[int, str]:
    """When each stock record was last used: by a plate, a photograph, a research session, a vector work or a photo work. A record that
    nothing used is absent. Works keep their stock inside their data (a vector work: ``material_id``; a photo work: ``scale.material_id``)."""
    rows = store.query(
        "SELECT material_id, MAX(at) AS at FROM ("
        " SELECT material_id, created_at AS at FROM plate WHERE material_id IS NOT NULL"
        " UNION ALL SELECT material_id, created_at FROM pair WHERE material_id IS NOT NULL AND status != 'Deleted'"
        " UNION ALL SELECT material_id, updated_at FROM research_session"
        " UNION ALL SELECT json_extract(data_json, '$.material_id'), created_at FROM plan WHERE json_extract(data_json, '$.material_id') IS NOT NULL"
        " UNION ALL SELECT json_extract(data_json, '$.scale.material_id'), created_at FROM plan WHERE json_extract(data_json, '$.scale.material_id') IS NOT NULL"
        ") WHERE material_id IS NOT NULL GROUP BY material_id")
    return {int(r["material_id"]): r["at"] for r in rows}


def get(store: Store, material_id: int) -> dict:
    """One stock record with the time it was last used; the same message as an update of a missing record gives."""
    row = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
    if row is None:
        raise KeyError(f"titanium stock {material_id} not found")
    return {**dict(row), "last_used_at": last_used(store).get(material_id)}


def _text(m: dict) -> str:
    """What a search looks in, in the order a line of the catalogue shows it (name, grade, batch, thickness) and then the rest, without case
    and spacing. The whole phrase typed is looked for in it, as the search of every list does (``list.js``): «grade 5» finds the sheets of
    Grade 5 and not every sheet of another grade with a «5» somewhere in it."""
    thickness = "" if m["thickness_mm"] is None else f"{m['thickness_mm']:g} мм"
    return _plain(" ".join(str(part or "") for part in (m["name"], m["grade"], m["batch"], thickness, m["family"], m["surface"])))


def _grade_of(m: dict) -> str:
    return _plain(m["grade"]) or NO_GRADE


def _family_of(m: dict) -> str:
    return _plain(m["family"])


def _order(sort: str):
    """The key and direction of an order; an unknown name gives the order of the plain list."""
    if sort == "recent":                    # used records first, the latest use first; the rest by the time they were added
        return (lambda m: (m["last_used_at"] or "", m["created_at"] or "", m["id"])), True
    if sort == "name":
        return (lambda m: (_plain(m["name"]), m["id"])), False
    if sort == "grade":                     # records of one grade together, then by batch; records with no grade last
        return (lambda m: (_grade_of(m) == NO_GRADE, _grade_of(m), _plain(m["batch"]), m["id"])), False
    if sort == "thickness":
        return (lambda m: (m["thickness_mm"] is None, m["thickness_mm"] or 0.0, m["id"])), False
    if sort == "newest":
        return (lambda m: m["id"]), True
    return (lambda m: m["id"]), False


def page(store: Store, *, search: str = "", family: str = "", grade: str = "", sort: str = "recent", offset: int = 0, limit: int | None = 20) -> dict:
    """One page of the catalogue: ``items`` (each record with ``last_used_at``), ``total`` (the records that match), ``all`` (the whole
    collection, so that «nothing matches» is told from «nothing was added»), ``counts`` and ``options`` of the family and grade filters (a
    count is what the filter would show with the other conditions as they are). ``limit`` None gives every match."""
    used = last_used(store)
    every = [{**dict(r), "last_used_at": used.get(r["id"])} for r in store.query("SELECT * FROM material_profile")]
    phrase = _plain(search)
    family_key, grade_key = _plain(family), _plain(grade)

    def passes(m: dict, skip: str | None = None) -> bool:
        return (phrase in _text(m) and (skip == "family" or not family_key or _family_of(m) == family_key)
                and (skip == "grade" or not grade_key or _grade_of(m) == grade_key))

    matched = [m for m in every if passes(m)]
    key, newest_first = _order(sort)
    matched.sort(key=key, reverse=newest_first)
    start = max(0, int(offset))
    size = None if limit is None else max(1, min(int(limit), PAGE_MAX))
    items = matched[start:] if size is None else matched[start:start + size]

    def tally(field: str, of) -> tuple[list[list[str]], dict[str, int]]:
        """The options of a filter (value and the name as first written) and the count each would show."""
        names: dict[str, str] = {}
        for m in every:
            value = of(m)
            if field == "grade" and value == NO_GRADE:
                names.setdefault(value, "без марки")
            elif value:
                names.setdefault(value, (m[field] or "").strip())
        counts = {value: sum(1 for m in every if passes(m, field) and of(m) == value) for value in names}
        counts[""] = sum(1 for m in every if passes(m, field))
        ordered = sorted(names, key=lambda v: (v == NO_GRADE, v))
        return [[v, names[v]] for v in ordered], counts

    families, family_counts = tally("family", _family_of)
    grades, grade_counts = tally("grade", _grade_of)
    return {"items": items, "total": len(matched), "all": len(every), "offset": start, "limit": size,
            "counts": {"family": family_counts, "grade": grade_counts}, "options": {"families": families, "grades": grades}}
