"""The engraving setup: the laser and lens of a work, its job settings, titanium stocks, capture setups and evaluation rules.

Comparable knowledge is partitioned by the physical laser and the lens record used for the work (DEC-042, DEC-063): an
unknown lens is its own partition and never equals a known one. Pulse width, line interval and passes are job settings
stored with every layer; within a partition the recipe key separates them (DEC-051). Laser profiles no longer exist: an
older database keeps them only as a read-only archive that nothing here reads.
"""
from __future__ import annotations

import json
import math
from typing import Any

from .db import Store, now

RULE_KEYS = ("repeat_threshold", "delta_tolerance", "variance_threshold")
RECORD_TABLES = ("plate", "plan", "pair", "observation", "knowledge", "target_color", "proposal", "research_session")   # name a laser and a lens


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


# -- the laser and the lens of a work ---------------------------------------------------------------------
def setup_key(device_id: int, lens_id: int | None) -> str:
    """The partition of comparable knowledge: one laser and one lens record (the lens is identified by its record, so
    later edits of the lens do not split knowledge); ``lens:unknown`` is a partition of its own."""
    return f"laser:{device_id}/lens:{'unknown' if lens_id is None else lens_id}"


def resolve(store: Store, device_id: int, lens_id: int | None) -> dict:
    """The laser and the lens of a work as the calculations use them; ``lens`` is None when the lens is unknown."""
    from . import devices, lenses
    device = devices.brief(store, device_id)
    lens = None if lens_id is None else lenses.get_lens(store, lens_id)
    return {"device_id": device_id, "lens_id": lens_id, "key": setup_key(device_id, lens_id), "device": device, "lens": lens}


def installed(store: Store, device_id: int) -> dict:
    """The setup of new work on a laser: the laser with the lens installed on it now (unknown when none is installed)."""
    from . import lenses
    lens = lenses.installed(store, device_id)
    return resolve(store, device_id, None if lens is None else lens["id"])


def lens_snapshot(setup: dict) -> dict | None:
    """What a plate, a plan or a photograph remembers about its lens: the configuration and the spot value with its basis
    (REQ-019); later edits or a replacement of the lens never change it."""
    from . import characterization, lenses
    if setup["lens"] is None:
        return None
    spot = characterization.characterize(setup["device"]["passport"], setup["lens"])
    return lenses.snapshot(setup["lens"], spot["spot_diameter_um"], spot["spot_basis"])


def job_settings(passport: dict, pulse_width: float, line_interval: float, passes: int) -> dict:
    """Pulse width, line interval and passes of a job, each required: nothing is filled in (DEC-043). A pulse width the
    laser does not offer is refused (DEC-035)."""
    from . import devices
    pw = _finite(pulse_width, "pulse width", True)
    interval = _finite(line_interval, "line interval", True)
    if passes is None or int(passes) != passes or passes < 1:
        raise ValidationError("passes must be a positive integer")
    devices.require_selectable(passport, pw)
    return {"pulse_width": pw, "line_interval": interval, "passes": int(passes)}


def parameter_vector(passport: dict, power: float, frequency: float, speed: float, pulse_width: float,
                     line_interval: float, passes: int) -> dict:
    """The full per-layer settings stored with every measurement."""
    return {"power": float(power), "frequency": float(frequency), "speed": float(speed),
            **job_settings(passport, pulse_width, line_interval, passes)}


def check_in_range(passport: dict, power: float | None, frequency: float | None) -> list[str]:
    """Power above 0 and up to 100 %, frequency within the laser's repetition-rate range (REQ-018). No speed limit of the
    scanner is known, so the speed is not checked."""
    problems = []
    rate = passport["repetition_rate_khz"]
    if power is not None and not 0 < power <= 100:
        problems.append(f"power {power:g} % is outside 0-100")
    if frequency is not None and not rate["min"] <= frequency <= rate["max"]:
        problems.append(f"frequency {frequency:g} kHz is outside {rate['min']:g}-{rate['max']:g}")
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


# -- capture setups (REQ-009, DEC-025): every photograph names the rig it was taken on ------------------------------
LEGACY_SETUP_NAME = "Photo capture (no rig)"    # stands in for the rig of pairs uploaded before every photograph had one
OBSERVERS = ("2°",)


def _capture_setup(row) -> dict:
    """A capture setup with its chart reference (the published values until the operator gives its own) and whether it
    is the placeholder of old pairs."""
    from . import photo
    d = dict(row)
    stored = d.pop("chart_reference_json", None)
    d["chart_reference"] = {**json.loads(stored), "published": False} if stored else photo.published_reference()
    d["legacy"] = d["name"] == LEGACY_SETUP_NAME
    return d


def get_capture_setup(store: Store, setup_id: int) -> dict:
    row = store.one("SELECT * FROM capture_setup WHERE id=?", (setup_id,))
    if row is None:
        raise KeyError(f"capture setup {setup_id} not found")
    return _capture_setup(row)


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
    return get_capture_setup(store, setup_id)


def last_capture_setup(store: Store) -> int | None:
    """The rig of the photograph uploaded last ('as last time'); None before the first one."""
    row = store.one("SELECT p.stand_id FROM pair p JOIN capture_setup c ON c.id=p.stand_id WHERE c.name!=? ORDER BY p.id DESC LIMIT 1",
                    (LEGACY_SETUP_NAME,))
    return None if row is None else row["stand_id"]


def list_capture_setups(store: Store) -> list[dict]:
    last = last_capture_setup(store)
    return [_capture_setup(r) | {"last_used": r["id"] == last} for r in store.query("SELECT * FROM capture_setup ORDER BY id")]


def capture_setup_for_photo(store: Store, setup_id: int | None, keep: int | None = None) -> int:
    """The capture setup of a new photograph: the one chosen, else the one used last, else the only one there is. The
    placeholder of old pairs is no rig and is refused; ``keep`` is a setup the photograph already has (the same
    photograph aligned again)."""
    if setup_id is not None and setup_id == keep:
        return setup_id
    if setup_id is None:
        setup_id = last_capture_setup(store)
    if setup_id is None:
        real = store.query("SELECT id FROM capture_setup WHERE name!=? ORDER BY id", (LEGACY_SETUP_NAME,))
        if not real:
            raise ValidationError("add the capture setup (rig) of your photographs on the Settings screen before uploading one")
        if len(real) > 1:
            raise ValidationError("select a capture setup (rig) for this photograph")
        setup_id = real[0]["id"]
    if get_capture_setup(store, setup_id)["legacy"]:
        raise ValidationError("the placeholder capture setup describes only pairs uploaded before every photograph had a rig; choose the rig of this photograph")
    return setup_id


def save_chart_reference(store: Store, setup_id: int, patches_lab, white_point: str, observer: str, source: str) -> dict:
    """The reference values of a setup's chart (DEC-025): 24 Lab triples in chart order, their white point and observer, and
    where the values come from."""
    from . import color
    get_capture_setup(store, setup_id)
    if white_point not in color.WHITE_POINTS:
        raise ValidationError(f"the white point must be one of {', '.join(color.WHITE_POINTS)}")
    if observer not in OBSERVERS:
        raise ValidationError("only the 2° standard observer is supported")
    if not str(source or "").strip():
        raise ValidationError("say where the reference values come from")
    try:
        patches = [[float(v) for v in lab] for lab in patches_lab]
    except (TypeError, ValueError):
        raise ValidationError("the reference values must be 24 Lab triples") from None
    if len(patches) != 24 or any(len(lab) != 3 or not color.valid_lab(lab) for lab in patches):
        raise ValidationError("the reference values must be 24 Lab triples (L 0-100, a and b -128 to 127)")
    stored = {"source": str(source).strip(), "white_point": white_point, "observer": observer, "patches_lab": patches}
    store.execute("UPDATE capture_setup SET chart_reference_json=? WHERE id=?", (json.dumps(stored), setup_id))
    store.audit("chart_reference_saved", setup_id=setup_id, white_point=white_point, source=stored["source"])
    return get_capture_setup(store, setup_id)


def reset_chart_reference(store: Store, setup_id: int) -> dict:
    """Back to the published values of the chart."""
    get_capture_setup(store, setup_id)
    store.execute("UPDATE capture_setup SET chart_reference_json=NULL WHERE id=?", (setup_id,))
    store.audit("chart_reference_reset", setup_id=setup_id)
    return get_capture_setup(store, setup_id)


def delete_capture_setup(store: Store, setup_id: int) -> None:
    n = store.one("SELECT COUNT(*) AS n FROM pair WHERE stand_id=?", (setup_id,))["n"]
    if n:
        raise ProtectedError(f"this capture setup is used by {n} stored pairs")
    store.execute("DELETE FROM capture_setup WHERE id=?", (setup_id,))


# -- evaluation rules, one set per laser and lens ---------------------------------------------------------------
def get_rules(store: Store, device_id: int, lens_id: int | None) -> dict:
    r = store.get_setting(f"rules:{setup_key(device_id, lens_id)}", {})
    return {"repeat_threshold": r.get("repeat_threshold"), "delta_tolerance": r.get("delta_tolerance"),
            "variance_threshold": r.get("variance_threshold"), "criteria_agreed": bool(r.get("criteria_agreed", False))}


def save_rules(store: Store, device_id: int, lens_id: int | None, repeat_threshold=None, delta_tolerance=None,
               variance_threshold=None, criteria_agreed: bool | None = None) -> dict:
    """Empty values stay unset (None). Typing numbers alone never agrees the criteria (prototype BP-24)."""
    resolve(store, device_id, lens_id)
    cur = get_rules(store, device_id, lens_id)
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
    store.set_setting(f"rules:{setup_key(device_id, lens_id)}", cur)
    return cur
