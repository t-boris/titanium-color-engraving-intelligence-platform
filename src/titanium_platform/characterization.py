"""What a laser is: a characterization derived from its stored data (REQ-018, DEC-040).

Nothing here is stored. Every read recomputes it from the passport, the unit's test report, the pulse waveforms and the
laser settings, so a value that the operator confirms or corrects changes the result at once. Each item says whether the
calculations use it: ``used`` (printed or confirmed), ``waiting`` (handwritten, unread or doubted: not used until the
operator confirms it), ``reference`` (shown, never used) or ``unknown`` (not given).
"""
from __future__ import annotations

import math
from typing import Any

UNREAD = "см. фото"                    # value of a setting that exists but could not be read from its photograph
NOTE_SUFFIX = ": рукописная пометка"   # a row that records a handwritten doubt next to the setting with the same name
POWER_PLAUSIBLE = (0.5, 1.5)           # a measured power outside this share of the rated power is not believed
USED, WAITING, REFERENCE, UNKNOWN = "used", "waiting", "reference", "unknown"


def _number(value: Any) -> float | None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return float(value) if ok else None


def setting(passport: dict, tab: str, key: str) -> dict | None:
    """One laser setting as {value, raw, unit, status, contested, state}, or None when it is not listed.

    ``used`` needs a number that is printed or confirmed and has no doubt written next to it. A confirmed value wins
    over a stale doubt row: the doubt only counts while the setting itself is not confirmed.
    """
    fields = {f["key"]: f for t in (passport.get("controller") or {}).get("tabs", []) if t["key"] == tab for f in t["fields"]}
    f = fields.get(key)
    if f is None:
        return None
    number = _number(f["value"])
    contested = (key + NOTE_SUFFIX) in fields and f["status"] != "confirmed"
    ok = number is not None and f["status"] in ("printed", "confirmed") and not contested
    return {"value": number, "raw": f["value"], "unit": f.get("unit"), "status": f["status"], "contested": contested, "state": USED if ok else WAITING}


def _settings_field(passport: dict) -> tuple[dict | None, list[str]]:
    """The work field of the laser settings when printed or confirmed, and the settings it still waits for."""
    waiting: list[str] = []
    size = setting(passport, "field", "Field Size")
    if size:
        if size["state"] == USED and size["value"] > 0:
            return {"width": size["value"], "height": size["value"], "source": "Field Size"}, []
        waiting.append("Field Size")
    w, h = setting(passport, "workspace", "Size Width"), setting(passport, "workspace", "Size Height")
    if w and h:
        if w["state"] == USED and h["state"] == USED and w["value"] > 0 and h["value"] > 0:
            return {"width": w["value"], "height": h["value"], "source": "Size Width / Size Height"}, []
        waiting += ["Size Width", "Size Height"]
    return None, waiting


def work_field(passport: dict, lens: dict | None = None) -> tuple[dict | None, list[str]]:
    """(the work field in mm, or None) and what it waits for. With a lens, the smaller of the lens and the settings field (REQ-019)."""
    sf, waiting = _settings_field(passport)
    lf = _number((lens or {}).get("field_mm"))
    if lf and sf:
        return {"width": min(lf, sf["width"]), "height": min(lf, sf["height"]), "source": "lens and laser settings",
                "settings_exceeds_lens": sf["width"] > lf or sf["height"] > lf}, []
    if lf:
        return {"width": lf, "height": lf, "source": "lens", "settings_exceeds_lens": False}, waiting
    return sf, waiting


def spot_estimate(passport: dict, lens: dict | None, rows: dict) -> dict:
    """The focused spot: the operator's measurement, else 4 x M2 x wavelength x focal length / (pi x beam diameter at the lens).

    Without M2 only a range is known (M2 = 1 is the physical lower bound; the manual's M2 limit is the upper one) and
    no number is used (REQ-019). Returns {value, low, high, basis, state, missing}.
    """
    measured = _number(passport.get("spot_diameter_um"))
    if measured:
        return {"value": measured, "low": None, "high": None, "basis": "measured", "state": USED, "missing": []}
    focal = _number((lens or {}).get("focal_length_mm"))
    beam = _number((rows.get("Output beam diameter") or {}).get("result")) or _number(passport.get("beam_diameter_mm"))
    wavelength = (_number((rows.get("Central emission wavelength") or {}).get("result")) or _number(passport.get("wavelength_nm")) or 0) / 1000.0
    missing = [k for k, ok in (("lens", focal), ("beam_diameter", beam), ("wavelength", wavelength)) if not ok]
    if missing:
        return {"value": None, "low": None, "high": None, "basis": None, "state": UNKNOWN, "missing": missing}
    per_m2 = 4 * wavelength * focal / (math.pi * beam * (_number(lens.get("expansion")) or 1.0))     # um for M2 = 1
    m2, m2_max = _number(passport.get("m2")), _number(passport.get("m2_max"))
    if m2:
        return {"value": per_m2 * m2, "low": None, "high": None, "basis": "calculated", "state": USED, "missing": []}
    return {"value": None, "low": per_m2, "high": per_m2 * m2_max if m2_max else None, "basis": "bound", "state": REFERENCE, "missing": ["m2"]}


def _item(key, value, unit, basis, state, waiting_for=()) -> dict:
    return {"key": key, "value": value, "unit": unit, "basis": basis, "state": state, "waiting_for": list(waiting_for)}


def _effective_power(passport: dict, rows: dict) -> tuple[float, str]:
    """The unit's measured power when it is plausible, otherwise the rated power."""
    rated = passport["rated_power_w"]
    measured = _number((rows.get("Nominal average output power") or {}).get("result"))
    if measured is not None and POWER_PLAUSIBLE[0] * rated <= measured <= POWER_PLAUSIBLE[1] * rated:
        return measured, "measured"
    return rated, "rated"


def _frequency_range(passport: dict) -> tuple[float, float, list[str]]:
    """The laser's own range narrowed by Min PWM and Max PWM when those are printed or confirmed."""
    low, high = passport["repetition_rate_khz"]["min"], passport["repetition_rate_khz"]["max"]
    lo, hi = setting(passport, "laser_control", "Min PWM"), setting(passport, "laser_control", "Max PWM")
    waiting = [k for k, s in (("Min PWM", lo), ("Max PWM", hi)) if s and s["state"] == WAITING]
    f_low = max(low, lo["value"]) if lo and lo["state"] == USED else low
    f_high = min(high, hi["value"]) if hi and hi["state"] == USED else high
    if f_low >= f_high:                                   # contradictory settings are not used
        return low, high, ["Min PWM", "Max PWM"]
    return f_low, f_high, waiting


def characterize(passport: dict, lens: dict | None = None) -> dict:
    """The laser as the calculations see it, with what each number rests on; ``lens`` is the installed lens (REQ-019)."""
    rows = {r["key"]: r for r in (passport.get("test_report") or {}).get("rows", [])}
    power, basis = _effective_power(passport, rows)
    own = (passport["repetition_rate_khz"]["min"], passport["repetition_rate_khz"]["max"])
    f_low, f_high, waiting_pwm = _frequency_range(passport)
    field, waiting_field = work_field(passport, lens)
    spot = spot_estimate(passport, lens, rows)
    stated = _number(passport.get("max_pulse_energy_mj"))
    cutoffs = [s["cutoff_khz"] for s in passport["pulse_steps"] if s["cutoff_khz"] is not None]
    wavelength = _number((rows.get("Central emission wavelength") or {}).get("result"))
    peaks = [(max(w["p_kw"]), w["title"]) for w in passport.get("waveforms") or []]
    items = [
        _item("power", power, "W", basis, USED),
        _item("frequency_range", {"min": f_low, "max": f_high}, "kHz", "controller" if (f_low, f_high) != own else "laser", USED, waiting_pwm),
        _item("work_field", field, "mm", field["source"] if field else None, USED if field else (WAITING if waiting_field else UNKNOWN), waiting_field),
        _item("pulse_widths", [s["pulse_width_ns"] for s in passport["pulse_steps"]], "ns", "laser", USED),
        _item("max_pulse_energy", stated or (max(passport["rated_power_w"] / c for c in cutoffs) if cutoffs else None), "mJ",
              "passport" if stated else "calculated", USED if stated else REFERENCE),
        {**_item("spot_diameter", spot["value"], "um", spot["basis"], spot["state"], spot["missing"]), "low": spot["low"], "high": spot["high"]},
        _item("lens", ({"name": lens.get("name"), "focal_length_mm": lens.get("focal_length_mm"), "expansion": lens.get("expansion", 1.0)} if lens else None), "mm", "installed" if lens else None, USED if lens else UNKNOWN),
        _item("wavelength", wavelength or passport.get("wavelength_nm"), "nm", "measured" if wavelength else "nominal", REFERENCE),
        _item("peak_power", max(peaks)[0] if peaks else None, "kW", max(peaks)[1] if peaks else None, REFERENCE if peaks else UNKNOWN)]
    return {"effective_power_w": power, "power_basis": basis, "rated_power_w": passport["rated_power_w"],
            "frequency_range_khz": {"min": f_low, "max": f_high}, "work_field_mm": field, "max_pulse_energy_mj": stated,
            "spot_diameter_um": spot["value"], "spot_basis": spot["basis"], "spot_range_um": {"low": spot["low"], "high": spot["high"]}, "items": items}

