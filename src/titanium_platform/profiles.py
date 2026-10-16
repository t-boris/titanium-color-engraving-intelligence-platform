"""Laser/lens identities, material profiles, capture setups and evaluation rules.

An engraving profile identifies the physical laser and the particular lens used for a data series. All
six process settings are per test layer and live in the full observation vector; changing them never
creates a hardware-profile version. Power/frequency/speed bounds remain search limits, not saved settings.
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
_UNSET = object()   # "not given" for a field where None means "remove the link"
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
    # These nullable columns are retained only so older SQLite files migrate additively. They are
    # intentionally absent from the profile API: none of them is a profile setting.
    d.pop("pulse_width", None)
    d.pop("line_interval", None)
    d.pop("passes", None)
    return d


def _validate_hardware(store: Store, device_id: int | None, lens_id: int | None) -> None:
    if device_id is not None:
        from . import devices
        devices.get_passport(store, device_id)
    if lens_id is not None:
        from . import lenses
        lens = lenses.get_lens(store, lens_id)
        host = lens.get("installed_on")
        if host and host["id"] != device_id:
            raise ValidationError("the selected lens is installed on a different laser")


def create_profile(store: Store, name: str, pulse_width: float | None = None, line_interval: float | None = None,
                   passes: int | None = None, axes: list[dict] | None = None, family: str | None = None,
                   device_id: int | None = None, lens_id: int | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValidationError("profile name is required")
    if device_id is not None and lens_id is None:
        from . import lenses
        installed = lenses.installed(store, device_id)
        lens_id = installed["id"] if installed else None
    # Accept the old positional arguments during migration, but never use or persist them as profile
    # values. On pre-migration databases the legacy columns are NOT NULL, so harmless sentinels are
    # written there solely to satisfy the old schema.
    _validate_hardware(store, device_id, lens_id)
    clean = validate_axes(axes if axes is not None else [dict(a) for a in DEFAULT_AXES])
    family = family or (f"laser-{device_id}-lens-{lens_id}" if device_id is not None else name)
    last = store.one("SELECT MAX(version) AS v FROM laser_profile WHERE family=?", (family,))["v"] or 0
    cur = store.execute(
        "INSERT INTO laser_profile(family,version,name,axes_json,pulse_width,line_interval,passes,created_at,device_id,lens_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (family, last + 1, name, json.dumps(clean), 1, 0.05, 1, now(), device_id, lens_id))
    return get_profile(store, cur.lastrowid)


def get_profile(store: Store, profile_id: int) -> dict:
    row = store.one("SELECT * FROM laser_profile WHERE id=?", (profile_id,))
    if row is None:
        raise KeyError(f"laser profile {profile_id} not found")
    d = _profile_dict(row)
    d["linked"] = profile_links(store, profile_id)
    from . import devices
    d["device"] = devices.brief(store, d.get("device_id"))
    if d.get("lens_id") is not None:
        from . import lenses
        d["lens"] = lenses.get_lens(store, d["lens_id"])
    else:
        d["lens"] = None
    if d["device"] is not None:
        d["device"]["lens"] = d["lens"]
    return d


def list_profiles(store: Store) -> list[dict]:
    return [get_profile(store, r["id"]) for r in store.query("SELECT id FROM laser_profile ORDER BY family, version")]


def profile_links(store: Store, profile_id: int) -> dict:
    c = lambda t: store.one(f"SELECT COUNT(*) AS n FROM {t} WHERE profile_id=?", (profile_id,))["n"]
    return {"observations": c("observation"), "plans": c("plan"), "plates": c("plate"), "pairs": c("pair")}


def update_profile(store: Store, profile_id: int, name: str | None = None, pulse_width: float | None = None,
                   line_interval: float | None = None, passes: int | None = None, confirm_new_version: bool = False,
                   device_id: Any = _UNSET, lens_id: Any = _UNSET) -> dict:
    """Rename an identity or change its hardware pair while it has no linked experimental history.

    The legacy process-setting arguments are accepted for old clients but ignored. A profile linked to
    records cannot be retargeted to different hardware; create a new laser/lens identity instead.
    """
    cur = get_profile(store, profile_id)
    new_device = cur.get("device_id") if device_id is _UNSET else device_id
    new_lens = cur.get("lens_id") if lens_id is _UNSET else lens_id
    _validate_hardware(store, new_device, new_lens)
    pair_changed = new_device != cur.get("device_id") or new_lens != cur.get("lens_id")
    if pair_changed and any(cur["linked"].values()):
        raise ValidationError("this laser/lens identity has experimental history; create a new profile for the other hardware pair")
    if pair_changed:
        store.execute("UPDATE laser_profile SET device_id=?,lens_id=? WHERE id=?", (new_device, new_lens, profile_id))
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


def parameter_vector(profile: dict, power: float, frequency: float, speed: float, pulse_width: float = 200.0,
                     line_interval: float = 0.025, passes: int = 1) -> dict:
    """Full, per-layer process vector. Process settings are never read from the hardware profile."""
    pw = _finite(pulse_width, "pulse width", True)
    interval = _finite(line_interval, "line interval", True)
    if int(passes) != passes or passes < 1:
        raise ValidationError("passes must be a positive integer")
    if profile.get("device"):
        from . import devices
        devices.require_selectable(profile["device"]["passport"], pw)
    return {"power": float(power), "frequency": float(frequency), "speed": float(speed),
            "pulse_width": pw, "line_interval": interval, "passes": int(passes), "profile_id": profile["id"]}


def check_in_range(profile: dict, power: float, frequency: float, speed: float) -> list[str]:
    problems = []
    for axis in profile["axes"]:
        value = {"power": power, "frequency": frequency, "speed": speed}.get(axis["key"])
        if value is not None and not axis["min"] <= value <= axis["max"]:
            problems.append(f"{axis['key']} {value:g} {axis['unit']} is outside {axis['min']:g}-{axis['max']:g}")
    return problems


# -- materials -----------------------------------------------------------------------------------
def save_material(store: Store, name: str, batch: str | None = None, material_id: int | None = None,
                 grade: str | None = None, thickness_mm: float | None = None, surface: str | None = None,
                 family: str | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValidationError("material name is required")
    previous = store.one("SELECT family FROM material_profile WHERE id=?", (material_id,)) if material_id is not None else None
    family = (family if family is not None else previous["family"] if previous else "Titanium").strip()
    if not family:
        raise ValidationError("material family is required")
    batch = (batch or "").strip() or None
    grade = (grade or "").strip() or None
    surface = (surface or "").strip() or None
    thickness = None if thickness_mm in (None, "") else _finite(thickness_mm, "titanium thickness", True)
    if material_id is None:
        cur = store.execute("INSERT INTO material_profile(name,family,batch,grade,thickness_mm,surface,created_at) VALUES (?,?,?,?,?,?,?)",
                            (name, family, batch, grade, thickness, surface, now()))
        material_id = cur.lastrowid
    else:
        if store.one("SELECT id FROM material_profile WHERE id=?", (material_id,)) is None:
            raise KeyError(f"titanium stock {material_id} not found")
        store.execute("UPDATE material_profile SET name=?,family=?,batch=?,grade=?,thickness_mm=?,surface=? WHERE id=?",
                      (name, family, batch, grade, thickness, surface, material_id))
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
