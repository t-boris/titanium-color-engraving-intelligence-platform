"""Laser profiles, material profiles, capture setups and evaluation rules (REQ-010, REQ-009, REQ-005).

A laser profile *version* is immutable once observations or plates reference it. Changing a profile
constant (pulse width, line interval, passes) creates a new version; data of different versions is never
merged silently (DEC-005). Axes are stored as a JSON list, so adding a variable axis later needs no
migration of stored parameter vectors (REQ-010).
"""
from __future__ import annotations

import json
import math
from typing import Any

from .db import Store, now

DEFAULT_AXES = [
    {"key": "power", "name": "Power", "unit": "%", "min": 1.0, "max": 100.0},
    {"key": "frequency", "name": "Frequency", "unit": "kHz", "min": 1.0, "max": 4000.0},
    {"key": "speed", "name": "Speed", "unit": "mm/s", "min": 1.0, "max": 10000.0},
]
CONSTANT_KEYS = ("pulse_width", "line_interval", "passes")
RULE_KEYS = ("repeat_threshold", "delta_tolerance", "variance_threshold")


class ValidationError(ValueError):
    """Invalid input; the message is meant for the operator."""


class ProtectedError(RuntimeError):
    """A record cannot be deleted because other records or measurements depend on it."""


def _finite(value: Any, name: str, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be a number") from None
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValidationError(f"{name} must be a finite {'positive ' if positive else ''}number")
    return number


def validate_axes(axes: list[dict]) -> list[dict]:
    if not isinstance(axes, list) or len(axes) < 3:
        raise ValidationError("a laser profile needs the power, frequency and speed axes")
    keys = [a.get("key") for a in axes]
    for required in ("power", "frequency", "speed"):
        if required not in keys:
            raise ValidationError(f"axis '{required}' is required")
    if len(set(keys)) != len(keys):
        raise ValidationError("axis keys must be unique")
    clean = []
    for a in axes:
        lo, hi = _finite(a.get("min"), f"{a.get('key')} min"), _finite(a.get("max"), f"{a.get('key')} max")
        if not lo < hi:
            raise ValidationError(f"axis '{a.get('key')}': min must be below max")
        if not str(a.get("unit", "")).strip():
            raise ValidationError(f"axis '{a.get('key')}' needs a unit")
        clean.append({"key": a["key"], "name": a.get("name") or a["key"], "unit": a["unit"], "min": lo, "max": hi})
    return clean


def _profile_dict(row) -> dict:
    d = dict(row)
    d["axes"] = json.loads(d.pop("axes_json"))
    d["constants"] = {"pulse_width": d.pop("pulse_width"), "line_interval": d.pop("line_interval"), "passes": d.pop("passes")}
    return d


def create_profile(store: Store, name: str, pulse_width: float, line_interval: float, passes: int,
                   axes: list[dict] | None = None, family: str | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValidationError("profile name is required")
    pw, li = _finite(pulse_width, "pulse width", True), _finite(line_interval, "line interval", True)
    if int(passes) != passes or passes < 1:
        raise ValidationError("passes must be a positive integer")
    clean = validate_axes(axes if axes is not None else [dict(a) for a in DEFAULT_AXES])
    family = family or name
    last = store.one("SELECT MAX(version) AS v FROM laser_profile WHERE family=?", (family,))["v"] or 0
    cur = store.execute(
        "INSERT INTO laser_profile(family,version,name,axes_json,pulse_width,line_interval,passes,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (family, last + 1, name, json.dumps(clean), pw, li, int(passes), now()))
    return get_profile(store, cur.lastrowid)


def get_profile(store: Store, profile_id: int) -> dict:
    row = store.one("SELECT * FROM laser_profile WHERE id=?", (profile_id,))
    if row is None:
        raise KeyError(f"laser profile {profile_id} not found")
    d = _profile_dict(row)
    d["linked"] = profile_links(store, profile_id)
    return d


def list_profiles(store: Store) -> list[dict]:
    return [get_profile(store, r["id"]) for r in store.query("SELECT id FROM laser_profile ORDER BY family, version")]


def profile_links(store: Store, profile_id: int) -> dict:
    c = lambda t: store.one(f"SELECT COUNT(*) AS n FROM {t} WHERE profile_id=?", (profile_id,))["n"]
    return {"observations": c("observation"), "plans": c("plan"), "plates": c("plate"), "pairs": c("pair")}


def update_profile(store: Store, profile_id: int, name: str | None = None, pulse_width: float | None = None,
                   line_interval: float | None = None, passes: int | None = None, confirm_new_version: bool = False) -> dict:
    """Rename in place; a changed constant needs confirmation and creates a new version."""
    cur = get_profile(store, profile_id)
    consts = cur["constants"]
    new = {"pulse_width": consts["pulse_width"] if pulse_width is None else _finite(pulse_width, "pulse width", True),
           "line_interval": consts["line_interval"] if line_interval is None else _finite(line_interval, "line interval", True),
           "passes": consts["passes"] if passes is None else passes}
    if int(new["passes"]) != new["passes"] or new["passes"] < 1:
        raise ValidationError("passes must be a positive integer")
    changed = {k: (consts[k], new[k]) for k in CONSTANT_KEYS if new[k] != consts[k]}
    if changed:
        if not confirm_new_version:
            raise ValidationError("changing a profile constant creates a new version; confirm to continue")
        return create_profile(store, name or cur["name"], new["pulse_width"], new["line_interval"], int(new["passes"]),
                              axes=cur["axes"], family=cur["family"])
    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("profile name is required")
        store.execute("UPDATE laser_profile SET name=? WHERE id=?", (name, profile_id))
    return get_profile(store, profile_id)


def delete_profile(store: Store, profile_id: int) -> None:
    links = get_profile(store, profile_id)["linked"]
    if any(links.values()):
        raise ProtectedError("this profile version is linked to stored records and keeps the measurement history: "
                             + ", ".join(f"{n} {k}" for k, n in links.items() if n))
    store.execute("DELETE FROM laser_profile WHERE id=?", (profile_id,))
    store.audit("laser_profile_deleted", id=profile_id)


def parameter_vector(profile: dict, power: float, frequency: float, speed: float) -> dict:
    """Full parameter vector: variable axes plus the profile constants (REQ-010)."""
    vec = {"power": power, "frequency": frequency, "speed": speed, **profile["constants"], "profile_id": profile["id"]}
    return vec


def check_in_range(profile: dict, power: float, frequency: float, speed: float) -> list[str]:
    problems = []
    for axis in profile["axes"]:
        value = {"power": power, "frequency": frequency, "speed": speed}.get(axis["key"])
        if value is not None and not axis["min"] <= value <= axis["max"]:
            problems.append(f"{axis['key']} {value:g} {axis['unit']} is outside {axis['min']:g}-{axis['max']:g}")
    return problems


# -- materials -----------------------------------------------------------------------------------
def save_material(store: Store, name: str, batch: str | None = None, material_id: int | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValidationError("material name is required")
    batch = (batch or "").strip() or None
    if material_id is None:
        cur = store.execute("INSERT INTO material_profile(name,family,batch,created_at) VALUES (?,?,?,?)", (name, "Titanium", batch, now()))
        material_id = cur.lastrowid
    else:
        store.execute("UPDATE material_profile SET name=?, batch=? WHERE id=?", (name, batch, material_id))
    return dict(store.one("SELECT * FROM material_profile WHERE id=?", (material_id,)))


def list_materials(store: Store) -> list[dict]:
    return [dict(r) for r in store.query("SELECT * FROM material_profile ORDER BY id")]


# -- capture setups ---------------------------------------------------------------------------------
def save_capture_setup(store: Store, name: str, camera: str, lighting: str, angle: str, reference_chart: str,
                       setup_id: int | None = None) -> dict:
    fields = {"name": name, "camera": camera, "lighting": lighting, "angle": str(angle), "reference_chart": reference_chart}
    for k, v in fields.items():
        if not str(v or "").strip():
            raise ValidationError(f"{k.replace('_', ' ')} is required")
    vals = [str(v).strip() for v in fields.values()]
    if setup_id is None:
        cur = store.execute("INSERT INTO capture_setup(name,camera,lighting,angle,reference_chart,created_at) VALUES (?,?,?,?,?,?)", (*vals, now()))
        setup_id = cur.lastrowid
    else:
        store.execute("UPDATE capture_setup SET name=?,camera=?,lighting=?,angle=?,reference_chart=? WHERE id=?", (*vals, setup_id))
    return dict(store.one("SELECT * FROM capture_setup WHERE id=?", (setup_id,)))


def list_capture_setups(store: Store) -> list[dict]:
    return [dict(r) for r in store.query("SELECT * FROM capture_setup ORDER BY id")]


def delete_capture_setup(store: Store, setup_id: int) -> None:
    n = store.one("SELECT COUNT(*) AS n FROM pair WHERE stand_id=?", (setup_id,))["n"]
    if n:
        raise ProtectedError(f"this capture setup is used by {n} stored pairs")
    store.execute("DELETE FROM capture_setup WHERE id=?", (setup_id,))


# -- evaluation rules ---------------------------------------------------------------------------------
def get_rules(store: Store, profile_id: int) -> dict:
    r = store.get_setting(f"rules:{profile_id}", {})
    return {"repeat_threshold": r.get("repeat_threshold"), "delta_tolerance": r.get("delta_tolerance"),
            "variance_threshold": r.get("variance_threshold"), "criteria_agreed": bool(r.get("criteria_agreed", False))}


def save_rules(store: Store, profile_id: int, repeat_threshold=None, delta_tolerance=None, variance_threshold=None,
               criteria_agreed: bool | None = None) -> dict:
    """Empty values stay unset (None). Typing numbers alone never agrees the criteria (prototype BP-24)."""
    get_profile(store, profile_id)
    cur = get_rules(store, profile_id)
    if repeat_threshold is not None:
        if int(repeat_threshold) != repeat_threshold or repeat_threshold < 1:
            raise ValidationError("repeat threshold must be a positive integer")
        cur["repeat_threshold"] = int(repeat_threshold)
    for key, label, value in (("delta_tolerance", "delta E tolerance", delta_tolerance), ("variance_threshold", "variance threshold", variance_threshold)):
        if value is not None:
            cur[key] = _finite(value, label)
            if cur[key] < 0:
                raise ValidationError(f"{label} must not be negative")
    if criteria_agreed is not None:
        if criteria_agreed and (cur["repeat_threshold"] is None or cur["delta_tolerance"] is None or cur["variance_threshold"] is None):
            raise ValidationError("set the repetition threshold, delta E tolerance and variance threshold before agreeing the criteria")
        cur["criteria_agreed"] = bool(criteria_agreed)
    store.set_setting(f"rules:{profile_id}", cur)
    return cur
