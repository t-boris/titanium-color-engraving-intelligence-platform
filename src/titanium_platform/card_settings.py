"""The engraving settings the workshop MEASURED for a business card's own laser, lens and material (feature
ready-engraving-settings-for-business-cards, REQ-001..005, 022..024; Q-001 A, Q-005 A, DEC-007..010).

A card is tied to one laser, one lens (or the unknown lens) and one material. This module lists what the workshop knows for exactly that
setup, by type of engraving, so that the editor can offer a CHOICE instead of a blank form:

* ``color``: the measured colours of the vector palette (``palette.vector_palette``): one recipe each, the mean of its independent
  engravings, with how it was measured. A recipe whose colour is contradicted or was superseded by a better measurement is left out.
* ``photo``: the engravings of photographs that show a picture (``photo_knowledge.engravings``), by image mode. An engraving that showed no
  picture, or that the operator marked bad, is never offered. These carry the settings of a raster picture (image mode, minimum power, dot
  width) that a traced vector does not use; ``unused`` says which.
* ``line_text``: the accepted capability-plate findings for lines or text whose settings are complete (``capability_results``). Their status
  stays what the plate says: a candidate, not a production recipe.
* ``deep``: deep engraving. Nothing in the workshop measures it yet, so it is always unknown and says what is missing.

Only results of EXACTLY the card's laser and lens, and of the card's titanium (the same family and grade, ``setup.same_titanium``, as the
vector palette defines "this material"), are listed. Nothing is predicted, nothing is taken from another laser, lens or material, not even
as the nearest, and no value is invented: an item carries only the settings its source HAS. Read-only: this module never writes.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Mapping

from . import capability_results, devices, lenses, palette, photo_knowledge as pk, photo_modes, setup as su
from .db import Store

TYPES = (("color", "Colour"), ("photo", "Photo"), ("line_text", "Lines and text"), ("deep", "Deep engraving"))
PROPOSAL_ORDER = ("line_text", "color", "photo")          # a new card's first set: lines and text first, then a colour, then a photo setting
SETTING_KEYS = ("mode", "power", "speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes", "bidirectional", "cross_hatch",
                "scan_angle", "min_power", "dither", "dot_width")
RASTER_ONLY = ("dither", "min_power", "dot_width")          # used by a picture engraved as a raster photo, not by a vector element
MAX_PHOTO_PER_KIND = 40
REASONS = {
    "setup": "Choose the laser and the material of this card first: settings are offered only for the card's own laser, lens and material.",
    "color": "No colour is measured yet for this laser, lens and material. Measure colours with a colour plate first.",
    "photo": "No photo engraving that shows a picture is measured yet for this laser, lens and material. Photograph a photo-engraving plate first.",
    "line_text": "No line or text setting is measured as a candidate yet for this laser, lens and material. Engrave and photograph a capability plate first.",
    "deep": "Deep engraving is not measured in the workshop yet, so its settings are unknown. Only a measurement can give them.",
    "failed": "The measured results could not be read just now.",
}


# -- the setup ------------------------------------------------------------------------------------------------------------------------
def _exists(store: Store, table: str, record_id) -> bool:
    return isinstance(record_id, int) and not isinstance(record_id, bool) and store.one(f"SELECT 1 FROM {table} WHERE id=?", (record_id,)) is not None


def setup_view(store: Store, setup: Mapping) -> dict:
    """The card's laser, lens and material with their names. ``complete`` needs the laser and the material; an unknown lens (``lens_id``
    None) is a valid, explicit state and not missing."""
    device_id, lens_id, material_id = setup.get("device_id"), setup.get("lens_id"), setup.get("material_id")
    device = lens = material = None
    missing = []
    if _exists(store, "laser_device", device_id):
        record = devices.brief(store, device_id)
        device = {"id": device_id, "name": record["title"] or record["name"]}
    else:
        missing.append("the laser")
    if lens_id is not None and _exists(store, "lens", lens_id):
        lens = {"id": lens_id, "name": lenses.get_lens(store, lens_id)["name"]}
    elif lens_id is not None:
        missing.append("the lens")
    if _exists(store, "material_profile", material_id):
        row = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
        material = {"id": material_id, "name": row["name"], "grade": row["grade"], "family": row["family"]}
    else:
        missing.append("the material")
    return {"device_id": device_id, "lens_id": lens_id, "material_id": material_id, "device": device, "lens": lens, "material": material,
            "complete": device is not None and material is not None and not (lens_id is not None and lens is None), "missing": missing}


def _origin(item: Mapping, setup: Mapping) -> dict:
    return {"kind": "choice", "choice_id": item["id"], "type": item["type"], "source": item["source"], "label": item["label"],
            "detail": item["detail"], "evidence": item["evidence"], "swatch": (item.get("swatch") or {}).get("srgb"),
            "setup": {k: setup.get(k) for k in ("device_id", "lens_id", "material_id")}}


def _item(setup: Mapping, kind: str, key: str, source: str, label: str, detail: str, evidence: Mapping, settings: Mapping, *,
          swatch: str | None = None) -> dict:
    kept = {k: v for k, v in settings.items() if k in SETTING_KEYS and v is not None}
    item = {"id": f"{kind}:{key}", "type": kind, "source": source, "label": label, "detail": detail, "evidence": dict(evidence), "settings": kept,
            "unused": [k for k in RASTER_ONLY if k in kept], "swatch": None if swatch is None else {"srgb": swatch}}
    item["origin"] = _origin(item, setup)
    return item


def _group(source: str, label: str, items: list[dict]) -> dict:
    return {"source": source, "label": label, "count": len(items), "items": items}


def _short(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _figures(settings: Mapping) -> str:
    bits = []
    for key, unit in (("power", "%"), ("speed", "mm/s"), ("frequency", "kHz"), ("pulse_width", "ns"), ("line_interval", "mm interval")):
        if settings.get(key) is not None:
            bits.append(f"{settings[key]:g} {unit}")
    return ", ".join(bits)


# -- colour ---------------------------------------------------------------------------------------------------------------------------
HUES = ((20.0, "Orange"), (65.0, "Gold / yellow"), (110.0, "Green"), (180.0, "Cyan"), (235.0, "Blue"), (285.0, "Violet"), (335.0, "Pink / red"))
BASIS_WORDS = {"chart": "against a reference chart", "clean": "against the clean titanium of its photograph", "as-shot": "as photographed"}


def _colour_word(lab) -> str:
    """A plain word for a measured colour (its hue in CIELAB), only to group the list; the numbers are the measurement."""
    lightness, a, b = (float(v) for v in lab)
    if math.hypot(a, b) < 10.0:
        return "Grey / silver" if lightness >= 45.0 else "Dark grey / black"
    hue = math.degrees(math.atan2(b, a)) % 360.0
    word = "Pink / red"                                 # below the first bound: the red end of the circle
    for bound, name in HUES:
        if hue >= bound:
            word = name
    return word


def _hex(srgb) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(v)))):02x}" for v in srgb)


def _rank(entry: Mapping) -> tuple:
    basis = {"chart": 2, "clean": 1, "as-shot": 0}.get(entry["basis"], 0)
    return (-basis, -entry["engravings"], entry["time_s_per_cm2"] if entry["time_s_per_cm2"] is not None else math.inf, entry["id"])


def _colours(store: Store, setup: Mapping) -> list[dict]:
    found = palette.vector_palette(store, setup["device_id"], setup["lens_id"], setup["material_id"])
    entries = [e for e in found["entries"] if not e["caution"] and e["parameters"].get("power") is not None]
    items, seen = [], set()
    for entry in sorted(entries, key=_rank):
        params = entry["parameters"]
        settings = {"mode": "fill", **{k: params.get(k) for k in SETTING_KEYS if k != "mode"}}
        same = (tuple(sorted(settings.items())), tuple(round(float(v), 1) for v in entry["lab"]))
        if same in seen:                                    # the same settings that gave the same colour, kept apart by the palette: one choice
            continue
        seen.add(same)
        word = _colour_word(entry["lab"])
        engravings = entry["engravings"]
        detail = (f"Measured {BASIS_WORDS.get(entry['basis'], entry['basis'])}; {engravings} independent engraving"
                  f"{'' if engravings == 1 else 's'}, {entry['photographs']} photograph{'' if entry['photographs'] == 1 else 's'}. {_figures(settings)}.")
        evidence = {"status": "repeated" if engravings > 1 else "single", "basis": entry["basis"], "engravings": engravings,
                    "photographs": entry["photographs"], "expected_delta_e": None if entry["expected_delta_e"] is None else round(entry["expected_delta_e"], 2), "time_s_per_cm2": None if entry["time_s_per_cm2"] is None else round(entry["time_s_per_cm2"], 1),
                    "lab": [round(float(v), 1) for v in entry["lab"]], "missing_context": entry["missing_context"], "colour": word}
        items.append(_item(setup, "color", entry["id"], "Colour map", f"{word} L* {float(entry['lab'][0]):.0f}", detail, evidence, settings,
                           swatch=_hex(entry["srgb"])))
    return items


# -- photo ----------------------------------------------------------------------------------------------------------------------------
def _usable_photo(engraving: Mapping) -> bool:
    """A measured engraving that shows a picture: judged, not failed, and not marked bad by the operator."""
    result = engraving.get("operator_results") or {}
    if result.get("bad") and not result.get("good"):
        return False
    return engraving["score"] is not None and bool(result.get("good") or not pk.failed(engraving))


def _photos(store: Store, setup: Mapping) -> list[dict]:
    plates = set(su.same_titanium(store, setup["material_id"]))
    items = [i for i in pk.photographs(store, setup["device_id"], setup["lens_id"]) if i["material_id"] in plates]
    out, per_kind = [], {}
    for engraving in pk.engravings(store, setup["device_id"], setup["lens_id"], None, None, items=items):
        if not _usable_photo(engraving):
            continue
        settings = engraving["settings"]
        kind = settings["dither"]
        per_kind[kind] = per_kind.get(kind, 0) + 1
        if per_kind[kind] > MAX_PHOTO_PER_KIND:
            continue
        mode = photo_modes.mode(kind)
        word = mode.label if mode is not None else kind
        verdicts = engraving.get("operator_results") or {}
        photos = len(engraving["photographs"])
        detail = (f"Measured on {photos} photograph{'' if photos == 1 else 's'} ({engraving['measured_by']}); picture score "
                  f"{engraving['score']:.2f}. {_figures(settings)}.")
        evidence = {"status": "operator-approved" if verdicts.get("good") else "measured", "score": engraving["score"],
                    "measured_by": engraving["measured_by"], "photographs": photos, "operator_results": verdicts,
                    "findings": [f.get("code") for f in engraving["findings"]], "image_mode": kind}
        fill = {"mode": "fill", **settings}
        label = word if settings.get("power") is None else f"{word}, {settings['power']:g} %"
        key = json.dumps({k: settings.get(k) for k in ("dither", *pk.KEYS)}, sort_keys=True)
        out.append(_item(setup, "photo", f"{kind}:{_short(key)}", "Photo engraving", label, detail, evidence, fill))
    return out


# -- lines and text -------------------------------------------------------------------------------------------------------------------
def _lines(store: Store, setup: Mapping) -> list[dict]:
    plates = set(su.same_titanium(store, setup["material_id"]))
    out, seen = [], set()
    for purpose in ("line", "text"):
        for finding in capability_results.findings_for_device(store, setup["device_id"], purpose):
            params = finding["parameters"]
            material = finding.get("material_id") or (finding.get("context") or {}).get("material_id")
            if not params or finding["lens_id"] != setup["lens_id"] or material not in plates:
                continue
            if any(params.get(k) is None for k in ("power", "speed", "frequency", "passes")):
                continue
            settings = {"mode": "line", **{k: params.get(k) for k in SETTING_KEYS if k != "mode"}}
            fingerprint = (purpose, tuple(settings.get(k) for k in SETTING_KEYS))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            word = "Line" if purpose == "line" else "Text"
            evidence = {"status": finding["status"], "purpose": purpose, "summary": finding["summary"], "next_test": finding["next_test"],
                        "plate_finding": finding["id"], "accepted_at": finding["accepted_at"]}
            out.append(_item(setup, "line_text", f"{purpose}:{finding['id']}", "Capability plate", f"{word} candidate",
                             f"{finding['summary']} {_figures(settings)}.", evidence, settings))
    return out


# -- the answer -----------------------------------------------------------------------------------------------------------------------
_BUILDERS = {"color": _colours, "photo": _photos, "line_text": _lines}


def _items_of(store: Store, setup: Mapping, kind: str) -> tuple[list[dict], str | None]:
    """The items of one type and, when there are none, why (never an exception: one source failing leaves the others usable)."""
    if kind == "deep":
        return [], REASONS["deep"]
    try:
        items = _BUILDERS[kind](store, setup)
    except (su.ValidationError, KeyError, ValueError):
        return [], REASONS["failed"]
    return items, None if items else REASONS[kind]


def _groups(kind: str, items: list[dict]) -> list[dict]:
    if kind == "color":
        by: dict[str, list[dict]] = {}
        for item in items:
            by.setdefault(item["evidence"]["colour"], []).append(item)
        return [_group("Colour map", word, found) for word, found in sorted(by.items(), key=lambda kv: -len(kv[1]))]
    if kind == "photo":
        by = {}
        for item in items:
            by.setdefault(item["evidence"]["image_mode"], []).append(item)
        return [_group("Photo engraving", (photo_modes.mode(k).label if photo_modes.mode(k) else k) + " image mode", found)
                for k, found in sorted(by.items(), key=lambda kv: -len(kv[1]))]
    return [_group("Capability plate", "Measured on a capability plate", items)]


def choices(store: Store, setup: Mapping) -> dict:
    """What can be chosen for a set of engraving settings of a card tied to ``setup``: always the four types in order, each known with its
    measured items grouped, or unknown with the reason. The items are listed without their ``origin`` (it repeats the item and is made by
    :func:`item_by_id` when a choice is applied), which halves the answer of a workshop with hundreds of measured colours."""
    view = setup_view(store, setup)
    types = []
    for kind, label in TYPES:
        if not view["complete"]:
            items, reason = [], REASONS["setup"]
        else:
            items, reason = _items_of(store, setup, kind)
        shown = [{k: v for k, v in item.items() if k != "origin"} for item in items]          # the origin is built when a choice is applied
        types.append({"type": kind, "label": label, "known": bool(items), "reason": None if items else reason,
                      "groups": _groups(kind, shown) if items else []})
    return {"setup": view, "types": types}


def item_by_id(store: Store, setup: Mapping, choice_id) -> dict | None:
    """The item with this id when it is offered for exactly this setup, else None (an id from another setup never resolves)."""
    if not isinstance(choice_id, str) or ":" not in choice_id or not setup_view(store, setup)["complete"]:
        return None
    kind = choice_id.split(":", 1)[0]
    if kind not in _BUILDERS:
        return None
    items, _ = _items_of(store, setup, kind)
    return next((i for i in items if i["id"] == choice_id), None)


def proposal(store: Store, setup: Mapping) -> dict | None:
    """The best known first set for a new card of this setup, or None when nothing is measured: lines and text, else a colour, else a
    photo setting (the first item of a type is its best: most trusted measurement first)."""
    if not setup_view(store, setup)["complete"]:
        return None
    for kind in PROPOSAL_ORDER:
        items, _ = _items_of(store, setup, kind)
        if items:
            return items[0]
    return None
