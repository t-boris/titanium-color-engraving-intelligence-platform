"""Lenses: a replaceable lens that sets the focused spot and the usable field (REQ-019, DEC-041).

A lens is its own record. At most one lens is installed on a laser and a lens sits on at most one laser. A plate stores a
snapshot of the lens it was made for, so editing or replacing a lens later never changes what a stored plate means.
Records of work name the lens by its record (DEC-063): an edit of the lens does not split their knowledge. A lens may stay
incomplete: an unknown focal length leaves the spot and what depends on it unavailable (REQ-019).
The spot diameter is derived from the installed lens in :mod:`characterization`; this module only keeps the records.
"""
from __future__ import annotations

from typing import Any

from . import setup as su
from .db import Store, now

FOCAL_RANGE_MM = (20.0, 1500.0)
FIELD_RANGE_MM = (1.0, 500.0)
EXPANSION_RANGE = (0.2, 20.0)
_UNSET = object()


def _bounded(value: Any, name: str, lo: float, hi: float) -> float:
    number = su._finite(value, name, True)
    if not lo <= number <= hi:
        raise su.ValidationError(f"{name} must be between {lo:g} and {hi:g}")   # name is one of: focal length, lens field, beam expansion
    return number


def _row(store: Store, lens_id: int):
    row = store.one("SELECT * FROM lens WHERE id=?", (lens_id,))
    if row is None:
        raise KeyError(f"lens {lens_id} not found")
    return row


def _public(store: Store, row) -> dict:
    d = dict(row)
    host = store.one("SELECT id, name, serial FROM laser_device WHERE lens_id=?", (d["id"],))
    d["installed_on"] = None if host is None else {"id": host["id"], "name": host["name"], "serial": host["serial"]}
    return d


def _clean(name: Any, focal: Any, field: Any, expansion: Any, note: Any) -> tuple:
    name = str(name or "").strip()
    if not name:
        raise su.ValidationError("lens name is required")
    focal = None if focal in (None, "") else _bounded(focal, "focal length", *FOCAL_RANGE_MM)
    field = None if field in (None, "") else _bounded(field, "lens field", *FIELD_RANGE_MM)
    expansion = 1.0 if expansion in (None, "") else _bounded(expansion, "beam expansion", *EXPANSION_RANGE)
    return name, focal, field, expansion, (str(note).strip() or None) if note is not None else None


def create_lens(store: Store, name: str, focal_length_mm: Any = None, field_mm: Any = None, expansion: Any = 1.0, note: str | None = None) -> dict:
    values = _clean(name, focal_length_mm, field_mm, expansion, note)
    cur = store.execute("INSERT INTO lens(name,focal_length_mm,field_mm,expansion,note,created_at) VALUES (?,?,?,?,?,?)", (*values, now()))
    return get_lens(store, cur.lastrowid)


def get_lens(store: Store, lens_id: int) -> dict:
    return _public(store, _row(store, lens_id))


def list_lenses(store: Store) -> list[dict]:
    return [_public(store, r) for r in store.query("SELECT * FROM lens ORDER BY id")]


def update_lens(store: Store, lens_id: int, name: Any = _UNSET, focal_length_mm: Any = _UNSET, field_mm: Any = _UNSET,
                expansion: Any = _UNSET, note: Any = _UNSET) -> dict:
    row = _row(store, lens_id)
    cur = {"name": row["name"], "focal_length_mm": row["focal_length_mm"], "field_mm": row["field_mm"], "expansion": row["expansion"], "note": row["note"]}
    for key, new in (("name", name), ("focal_length_mm", focal_length_mm), ("field_mm", field_mm), ("expansion", expansion), ("note", note)):
        if new is not _UNSET:
            cur[key] = new
    values = _clean(cur["name"], cur["focal_length_mm"], cur["field_mm"], cur["expansion"], cur["note"])
    store.execute("UPDATE lens SET name=?, focal_length_mm=?, field_mm=?, expansion=?, note=? WHERE id=?", (*values, lens_id))
    return get_lens(store, lens_id)


def delete_lens(store: Store, lens_id: int) -> None:
    lens = get_lens(store, lens_id)
    if lens["installed_on"]:
        raise su.ProtectedError("this lens is installed on a laser; remove it from the laser first")
    used = sum(store.one(f"SELECT COUNT(*) AS n FROM {table} WHERE lens_id=?", (lens_id,))["n"] for table in su.RECORD_TABLES)
    if used:
        raise su.ProtectedError(f"this lens is named by {used} stored records of work and keeps their history")
    store.execute("DELETE FROM lens WHERE id=?", (lens_id,))
    store.audit("lens_deleted", id=lens_id)


def install(store: Store, device_id: int, lens_id: int | None) -> None:
    """Install a lens on a laser, or take the lens off with ``None``. A lens cannot sit on two lasers at once."""
    if store.one("SELECT id FROM laser_device WHERE id=?", (device_id,)) is None:
        raise KeyError(f"laser device {device_id} not found")
    if lens_id is not None:
        _row(store, lens_id)
        other = store.one("SELECT name FROM laser_device WHERE lens_id=? AND id<>?", (lens_id, device_id))
        if other is not None:
            raise su.ValidationError(f"this lens is already installed on another laser ({other['name']}); remove it there first")
    store.execute("UPDATE laser_device SET lens_id=?, updated_at=? WHERE id=?", (lens_id, now(), device_id))
    store.audit("lens_installed", device_id=device_id, lens_id=lens_id)


def installed(store: Store, device_id: int) -> dict | None:
    row = store.one("SELECT lens_id FROM laser_device WHERE id=?", (device_id,))
    return None if row is None or row["lens_id"] is None else get_lens(store, row["lens_id"])


def label(lens: dict) -> str:
    """A lens as server text names it: the name with the focal length, or that the focal length is unknown."""
    if lens.get("focal_length_mm") is None:
        return f"{lens['name']}, focal length unknown"
    return f"{lens['name']}, {lens['focal_length_mm']:g} mm"


def snapshot(lens: dict | None, spot_diameter_um: float | None = None, spot_basis: str | None = None) -> dict | None:
    """What a plate remembers about its lens, with the spot value and its basis; independent of later edits of the lens record."""
    if not lens:
        return None
    return {"id": lens["id"], "name": lens["name"], "focal_length_mm": lens["focal_length_mm"], "field_mm": lens["field_mm"],
            "expansion": lens["expansion"], "spot_diameter_um": spot_diameter_um, "spot_basis": spot_basis if spot_diameter_um else None,
            "taken_at": now()}
