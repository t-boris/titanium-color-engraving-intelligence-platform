"""Laser devices: passport, pulse-width and cut-off table, source documents and the operating-point model (REQ-017).

A device describes one physical laser. Its passport holds what the manufacturer and the acceptance test say about it:
rated average power, repetition-rate range, the selectable pulse widths with the cut-off frequency of each, and
optional sections (test report, controller configuration, waveform key figures, open items). A laser profile version
may link to one device (DEC-035). Editing a device never touches stored measurements.

The model at the end turns a parameter set into the physical quantities that decide how much heat reaches the metal.
It is a passport model, not a measurement (DEC-036): average power rises in proportion to the repetition rate up
to the cut-off frequency of the selected pulse width and is flat above it, so the pulse energy is constant above
the cut-off and falls below it.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from pathlib import Path
from typing import Any

from . import profiles as pf
from .db import Store, now

DOCUMENT_KINDS = ("test_report", "cutoff_table", "waveform", "controller_config", "packing_list", "manual", "other")
DOCUMENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf", ".txt": "text/plain"}
MAX_DOCUMENT_BYTES = 30 * 1024 * 1024
MAX_SECTION_CHARS = 40000
STEP_TOLERANCE = 1e-6
CURVE_POINTS = 61
_UNSET = object()


# -- passport ------------------------------------------------------------------------------------------------
def _optional_positive(value: Any, name: str) -> float | None:
    return None if value in (None, "") else pf._finite(value, name, True)


def _section(value: Any, kinds: tuple[type, ...]) -> Any:
    if value is None:
        return None
    if not isinstance(value, kinds):
        raise pf.ValidationError("a passport section has the wrong type")
    if len(json.dumps(value, ensure_ascii=False)) > MAX_SECTION_CHARS:
        raise pf.ValidationError("a passport section is too large")
    return value


CONTROLLER_STATUSES = ("printed", "handwritten", "confirmed")   # printed screenshot / handwritten and unverified / confirmed by the operator
MAX_WAVEFORM_POINTS = 3000


def _scalar(value: Any) -> bool:
    if isinstance(value, bool) or isinstance(value, str):
        return True
    return isinstance(value, (int, float)) and math.isfinite(value)


def _controller(value: Any) -> dict | None:
    """Controller (EZCAD) settings as read from a document: tabs of fields, each value with how reliable it is (DEC-037)."""
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("tabs"), list):
        raise pf.ValidationError("the controller settings are not valid")
    tabs = []
    for tab in value["tabs"]:
        if not isinstance(tab, dict) or not str(tab.get("key") or "").strip() or not isinstance(tab.get("fields"), list):
            raise pf.ValidationError("the controller settings are not valid")
        fields = []
        for f in tab["fields"]:
            if (not isinstance(f, dict) or not str(f.get("key") or "").strip() or not _scalar(f.get("value"))
                    or f.get("status") not in CONTROLLER_STATUSES):
                raise pf.ValidationError("the controller settings are not valid")
            fields.append({"key": f["key"].strip(), "value": f["value"], "unit": _text(f.get("unit")), "status": f["status"]})
        tabs.append({"key": tab["key"].strip(), "fields": fields})
    return {"software": _text(value.get("software")), "source": _text(value.get("source")), "tabs": tabs}


def _test_report(value: Any) -> dict | None:
    """Acceptance-test results: one row per characteristic with its limits and the tested result."""
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("rows", []), list):
        raise pf.ValidationError("the test report is not valid")
    rows = []
    for r in value.get("rows", []):
        if not isinstance(r, dict) or not str(r.get("key") or "").strip():
            raise pf.ValidationError("the test report is not valid")
        cells = {k: r.get(k) for k in ("min", "typ", "max", "result")}
        if not all(c is None or _scalar(c) for c in cells.values()):
            raise pf.ValidationError("the test report is not valid")
        rows.append({"key": r["key"].strip(), "condition": _text(r.get("condition")), "unit": _text(r.get("unit")), **cells})
    return {"serial": _text(value.get("serial")), "part_number": _text(value.get("part_number")), "tested_on": _text(value.get("tested_on")),
            "source": _text(value.get("source")), "rows": rows}


def _waveforms(value: Any) -> list | None:
    """Digitised pulse shapes: time in ns and power in kW, flagged approximate (DEC-038)."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise pf.ValidationError("a passport section has the wrong type")
    out = []
    for w in value:
        t, p = (w.get("t_ns"), w.get("p_kw")) if isinstance(w, dict) else (None, None)
        if (not isinstance(t, list) or not isinstance(p, list) or len(t) != len(p) or not 2 <= len(t) <= MAX_WAVEFORM_POINTS
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in t + p)
                or any(b <= a for a, b in zip(t, t[1:]))):
            raise pf.ValidationError("a waveform is not valid")
        out.append({"title": _text(w.get("title")) or "waveform", "pulse_width_ns": _optional_positive(w.get("pulse_width_ns"), "pulse width"),
                    "frequency_khz": _optional_positive(w.get("frequency_khz"), "frequency"), "approximate": bool(w.get("approximate", True)),
                    "source": _text(w.get("source")), "note": _text(w.get("note")), "t_ns": [float(x) for x in t], "p_kw": [float(x) for x in p]})
    return out


def validate_passport(raw: Any) -> dict:
    """The normalised passport; raises ValidationError with a message for the operator."""
    if not isinstance(raw, dict):
        raise pf.ValidationError("the passport must be an object")
    rated = pf._finite(raw.get("rated_power_w"), "rated power", True)
    rate = raw.get("repetition_rate_khz")
    if not isinstance(rate, dict):
        raise pf.ValidationError("the repetition rate range must be an object")
    lo = pf._finite(rate.get("min"), "minimum repetition rate", True)
    hi = pf._finite(rate.get("max"), "maximum repetition rate", True)
    if not lo < hi:
        raise pf.ValidationError("maximum repetition rate must be above the minimum")
    raw_steps = raw.get("pulse_steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise pf.ValidationError("the pulse width table needs at least one step")
    steps = []
    for item in raw_steps:
        item = item if isinstance(item, dict) else {}
        cutoff = item.get("cutoff_khz")
        steps.append({"pulse_width_ns": pf._finite(item.get("pulse_width_ns"), "pulse width", True),
                      "cutoff_khz": None if cutoff in (None, "") else pf._finite(cutoff, "cut-off frequency", True)})
    steps.sort(key=lambda s: s["pulse_width_ns"])
    if len({s["pulse_width_ns"] for s in steps}) != len(steps):
        raise pf.ValidationError("pulse widths must not repeat")
    open_items = raw.get("open_items") or []
    if not isinstance(open_items, list) or not all(isinstance(t, str) for t in open_items):
        raise pf.ValidationError("a passport section has the wrong type")
    return {"rated_power_w": rated, "wavelength_nm": _optional_positive(raw.get("wavelength_nm"), "wavelength"),
            "max_pulse_energy_mj": _optional_positive(raw.get("max_pulse_energy_mj"), "maximum pulse energy"),
            "spot_diameter_um": _optional_positive(raw.get("spot_diameter_um"), "spot diameter"),
            "repetition_rate_khz": {"min": lo, "max": hi}, "pulse_steps": steps,
            "test_report": _test_report(raw.get("test_report")), "controller": _controller(raw.get("controller")),
            "waveforms": _waveforms(raw.get("waveforms")), "open_items": [t.strip() for t in open_items if t.strip()]}


def step_for(passport: dict, pulse_width: float) -> dict | None:
    for step in passport["pulse_steps"]:
        if abs(step["pulse_width_ns"] - pulse_width) <= STEP_TOLERANCE:
            return step
    return None


def require_selectable(passport: dict, pulse_width: float) -> dict:
    """The step for ``pulse_width``; a width the laser does not offer is refused (the laser would ignore it)."""
    step = step_for(passport, pulse_width)
    if step is None:
        steps = ", ".join(f"{s['pulse_width_ns']:g}" for s in passport["pulse_steps"])
        raise pf.ValidationError(f"pulse width {pulse_width:g} ns is not a selectable step of this laser; the steps are {steps}")
    return step


# -- catalogue template: the manufacturer's table for the JPT YDFLP-E-60-M7-M-R (pulse width ns, cut-off kHz; None = CW) ---------
JPT_60_M7_STEPS = [(1, None), (2, 1950), (4, 1350), (6, 975), (9, 600), (13, 412), (20, 252), (30, 187), (45, 150), (60, 135),
                   (80, 112), (100, 105), (150, 57), (200, 48), (250, 46), (350, 40), (500, 40)]
TEMPLATES = {
    "jpt-ydflp-e-60-m7-m-r": {
        "name": "JPT YDFLP-E-60-M7-M-R", "manufacturer": "JPT", "model": "YDFLP-E-60-M7-M-R",
        "description": ("JPT pulsed MOPA ytterbium fiber laser, 60 W average power, 1064 nm, repetition rate 1-4000 kHz. "
                        "The pulse width is one of 16 fixed steps from 2 to 500 ns plus a CW setting; a value that is not a step is "
                        "ignored by the laser, which keeps the last valid one. Below the cut-off frequency of the chosen pulse width "
                        "the output power falls in proportion to the repetition rate (manufacturer's table and Fig. 3)."),
        "passport": {
            "rated_power_w": 60, "wavelength_nm": 1064, "max_pulse_energy_mj": 1.5,
            "repetition_rate_khz": {"min": 1, "max": 4000},
            "pulse_steps": [{"pulse_width_ns": w, "cutoff_khz": c} for w, c in JPT_60_M7_STEPS],
        },
    },
}


# -- devices ---------------------------------------------------------------------------------------------------
def _row(store: Store, device_id: int):
    row = store.one("SELECT * FROM laser_device WHERE id=?", (device_id,))
    if row is None:
        raise KeyError(f"laser device {device_id} not found")
    return row


def get_passport(store: Store, device_id: int) -> dict:
    return json.loads(_row(store, device_id)["data_json"])


def brief(store: Store, device_id: int | None) -> dict | None:
    """What a laser profile carries about its device: identity and passport, without documents."""
    if device_id is None:
        return None
    row = _row(store, device_id)
    return {"id": row["id"], "name": row["name"], "manufacturer": row["manufacturer"], "model": row["model"], "serial": row["serial"],
            "passport": json.loads(row["data_json"])}


def linked_profiles(store: Store, device_id: int) -> list[dict]:
    return [{"id": r["id"], "name": r["name"], "version": r["version"], "pulse_width": r["pulse_width"]}
            for r in store.query("SELECT id,name,version,pulse_width FROM laser_profile WHERE device_id=? ORDER BY family, version", (device_id,))]


def _document_public(row) -> dict:
    return {k: row[k] for k in ("id", "device_id", "kind", "title", "filename", "media_type", "size", "created_at")}


def _public(store: Store, row) -> dict:
    d = dict(row)
    d["passport"] = json.loads(d.pop("data_json"))
    d["documents"] = [_document_public(r) for r in store.query("SELECT * FROM device_document WHERE device_id=? ORDER BY id", (d["id"],))]
    d["profiles"] = linked_profiles(store, d["id"])
    return d


def _text(value: Any) -> str | None:
    return (str(value).strip() or None) if value is not None else None



def create_device(store: Store, name: str, passport: Any, manufacturer: str | None = None, model: str | None = None,
                  serial: str | None = None, description: str | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise pf.ValidationError("device name is required")
    data = validate_passport(passport)
    stamp = now()
    cur = store.execute(
        "INSERT INTO laser_device(name,manufacturer,model,serial,description,data_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (name, _text(manufacturer), _text(model), _text(serial), _text(description), json.dumps(data), stamp, stamp))
    return get_device(store, cur.lastrowid)


def get_device(store: Store, device_id: int) -> dict:
    return _public(store, _row(store, device_id))


def list_devices(store: Store) -> list[dict]:
    return [_public(store, r) for r in store.query("SELECT * FROM laser_device ORDER BY id")]


def update_device(store: Store, device_id: int, name: Any = _UNSET, manufacturer: Any = _UNSET, model: Any = _UNSET, serial: Any = _UNSET,
                  description: Any = _UNSET, passport: Any = _UNSET) -> dict:
    row = _row(store, device_id)
    values = {"name": row["name"], "manufacturer": row["manufacturer"], "model": row["model"], "serial": row["serial"],
              "description": row["description"], "data_json": row["data_json"]}
    for key, new in (("name", name), ("manufacturer", manufacturer), ("model", model), ("serial", serial), ("description", description)):
        if new is not _UNSET:
            values[key] = _text(new)
    if not values["name"]:
        raise pf.ValidationError("device name is required")
    if passport is not _UNSET:
        data = validate_passport(passport)
        for profile in linked_profiles(store, device_id):   # a linked profile must keep a selectable pulse width
            require_selectable(data, profile["pulse_width"])
        values["data_json"] = json.dumps(data)
    store.execute("UPDATE laser_device SET name=?,manufacturer=?,model=?,serial=?,description=?,data_json=?,updated_at=? WHERE id=?",
                  (values["name"], values["manufacturer"], values["model"], values["serial"], values["description"], values["data_json"], now(), device_id))
    return get_device(store, device_id)


def delete_device(store: Store, device_id: int) -> None:
    _row(store, device_id)
    linked = len(linked_profiles(store, device_id))
    if linked:
        raise pf.ProtectedError(f"this laser is linked to {linked} laser profile versions; unlink them first")
    paths = [r["path"] for r in store.query("SELECT path FROM device_document WHERE device_id=?", (device_id,))]
    with store.transaction():
        store.execute("DELETE FROM device_document WHERE device_id=?", (device_id,))
        store.execute("DELETE FROM laser_device WHERE id=?", (device_id,))
    for path in paths:
        Path(path).unlink(missing_ok=True)
    store.audit("laser_device_deleted", id=device_id)


def list_templates() -> list[dict]:
    return [{"key": k, "name": t["name"], "manufacturer": t["manufacturer"], "model": t["model"], "description": t["description"]} for k, t in TEMPLATES.items()]


def create_from_template(store: Store, key: str, name: str | None = None, serial: str | None = None) -> dict:
    template = TEMPLATES.get(key)
    if template is None:
        raise pf.ValidationError("the laser template is not known")
    return create_device(store, (name or "").strip() or template["name"], json.loads(json.dumps(template["passport"])), template["manufacturer"],
                         template["model"], serial, template["description"])



# -- source documents ---------------------------------------------------------------------------------------------
def _content_matches(extension: str, data: bytes) -> bool:
    if extension in (".jpg", ".jpeg"):
        return data[:2] == b"\xff\xd8"
    if extension == ".png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if extension == ".pdf":
        return data[:5] == b"%PDF-"
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def add_document(store: Store, device_id: int, kind: str, title: str | None, filename: str, data: bytes) -> dict:
    """Attach a source document unchanged (DEC-037); the original bytes are what is stored."""
    _row(store, device_id)
    if kind not in DOCUMENT_KINDS:
        raise pf.ValidationError("the document kind is not recognised")
    extension = Path(filename or "").suffix.lower()
    if extension not in DOCUMENT_TYPES:
        raise pf.ValidationError("the document must be a JPG, PNG, PDF or TXT file")
    if not data:
        raise pf.ValidationError("the document is empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise pf.ValidationError(f"the document is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB")
    if not _content_matches(extension, data):
        raise pf.ValidationError("the document content does not match its file type")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "document"
    path = store.data_dir / "files" / f"device{device_id}-{uuid.uuid4().hex[:12]}-{safe}"
    path.write_bytes(data)
    try:
        cur = store.execute("INSERT INTO device_document(device_id,kind,title,filename,path,media_type,size,created_at) VALUES (?,?,?,?,?,?,?,?)",
                            (device_id, kind, (title or "").strip() or Path(filename).stem, Path(filename).name, str(path), DOCUMENT_TYPES[extension], len(data), now()))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return _document_public(store.one("SELECT * FROM device_document WHERE id=?", (cur.lastrowid,)))


def get_document(store: Store, device_id: int, document_id: int) -> dict:
    row = store.one("SELECT * FROM device_document WHERE id=? AND device_id=?", (document_id, device_id))
    if row is None:
        raise KeyError(f"document {document_id} not found")
    return dict(row)


def delete_document(store: Store, device_id: int, document_id: int) -> None:
    doc = get_document(store, device_id, document_id)
    store.execute("DELETE FROM device_document WHERE id=?", (document_id,))
    Path(doc["path"]).unlink(missing_ok=True)



# -- operating-point model (DEC-036) ------------------------------------------------------------------------------------
def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def operating_point(passport: dict, power: float, frequency: float, speed: float, pulse_width: float, line_interval: float, passes: int = 1) -> dict:
    """Passport-model figures for one parameter set. Nothing here is measured."""
    power = pf._finite(power, "power", True)
    if power > 100:
        raise pf.ValidationError("power must not exceed 100 %")
    freq, speed = pf._finite(frequency, "frequency", True), pf._finite(speed, "speed", True)
    interval = pf._finite(line_interval, "line interval", True)
    if int(passes) != passes or passes < 1:
        raise pf.ValidationError("passes must be a positive integer")
    step = require_selectable(passport, pulse_width)
    cutoff = step["cutoff_khz"]
    cw = cutoff is None
    problems, notes = [], []
    rate = passport["repetition_rate_khz"]
    if not rate["min"] <= freq <= rate["max"]:
        problems.append(f"frequency {freq:g} kHz is outside the repetition rate range {rate['min']:g}-{rate['max']:g} kHz of this laser")
    factor = 1.0 if cw or freq >= cutoff else freq / cutoff
    below = factor < 1.0
    if below:
        notes.append(f"frequency {freq:g} kHz is below the cut-off frequency {cutoff:g} kHz of the {pulse_width:g} ns step: the output power is {factor * 100:.0f} % of the power set")
    output = passport["rated_power_w"] * power / 100 * factor
    per_pass = output / (speed * interval) * 100          # W / (mm/s x mm) = J/mm2, x100 = J/cm2
    pitch = energy = density = fluence = overlap = None
    if cw:
        notes.append("CW setting: the laser does not pulse, so pulse energy and pulse pitch are not defined")
    else:
        energy = output / freq                            # W / kHz = mJ
        pitch = speed / freq                              # (mm/s) / kHz = um
        density = 1 / (pitch / 1000 * interval) * passes
        spot = passport.get("spot_diameter_um")
        if spot:
            fluence = energy / 1000 / (math.pi * (spot * 1e-4 / 2) ** 2)
            overlap = max(0.0, 1 - pitch / spot)
        else:
            notes.append("spot diameter is not set for this laser: fluence and pulse overlap are not calculated")
    return {"basis": "passport model", "pulse_width_ns": pulse_width, "cw": cw, "cutoff_khz": cutoff, "set_power_pct": power, "frequency_khz": freq,
            "speed_mm_s": speed, "line_interval_mm": interval, "passes": int(passes), "power_factor": _round(factor), "below_cutoff": below,
            "output_power_w": _round(output), "pulse_energy_mj": _round(energy), "pulse_pitch_um": _round(pitch), "pulses_per_mm2": _round(density),
            "areal_energy_j_cm2": _round(per_pass * passes), "coverage_rate_mm2_s": _round(speed * interval / passes),
            "fluence_j_cm2": _round(fluence), "pulse_overlap": _round(overlap), "problems": problems, "notes": notes}


def waveform_stats(w: dict, rated_power_w: float) -> dict:
    """Peak, pulse energy (integral of the positive part, kW x ns = uJ) and the passport's energy for the same frequency."""
    t, p = w["t_ns"], w["p_kw"]
    peak = max(range(len(p)), key=lambda i: p[i])
    energy_mj = sum((max(p[i], 0) + max(p[i + 1], 0)) / 2 * (t[i + 1] - t[i]) for i in range(len(t) - 1)) / 1000
    passport = rated_power_w / w["frequency_khz"] if w.get("frequency_khz") else None
    return {"peak_kw": _round(p[peak], 3), "peak_t_ns": _round(t[peak], 3), "energy_mj": _round(energy_mj),
            "passport_energy_mj": _round(passport), "ratio": _round(energy_mj / passport, 3) if passport else None}


def log_space(low: float, high: float, count: int) -> list[float]:
    return [low * (high / low) ** (i / (count - 1)) for i in range(count)]


def charts(passport: dict) -> dict:
    """Series for the device charts, computed from the passport alone (REQ-017): nothing is typed twice."""
    rated, lo, hi = passport["rated_power_w"], passport["repetition_rate_khz"]["min"], passport["repetition_rate_khz"]["max"]
    pulsed = [s for s in passport["pulse_steps"] if s["cutoff_khz"] is not None]
    cutoff = [{"pulse_width_ns": s["pulse_width_ns"], "cutoff_khz": s["cutoff_khz"], "max_pulse_energy_mj": _round(rated / s["cutoff_khz"])} for s in pulsed]
    curves = []
    for s in pulsed:
        knee = s["cutoff_khz"]
        freqs = sorted(set(log_space(lo, hi, CURVE_POINTS)) | ({knee} if lo <= knee <= hi else set()))
        points = []
        for f in freqs:
            power = rated * min(1.0, f / knee)
            points.append({"frequency_khz": _round(f), "power_w": _round(power), "pulse_energy_mj": _round(power / f)})
        curves.append({"pulse_width_ns": s["pulse_width_ns"], "cutoff_khz": knee, "points": points})
    waveforms = [w | {"stats": waveform_stats(w, rated)} for w in passport.get("waveforms") or []]
    return {"rated_power_w": rated, "repetition_rate_khz": {"min": lo, "max": hi}, "stated_max_pulse_energy_mj": passport.get("max_pulse_energy_mj"),
            "cw_steps": [s["pulse_width_ns"] for s in passport["pulse_steps"] if s["cutoff_khz"] is None], "cutoff": cutoff, "curves": curves,
            "waveforms": waveforms}

