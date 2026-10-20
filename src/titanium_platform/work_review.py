"""Work on the errors (DEC-090, proposed): what a vector work promised against what the engraved result measured.

Two comparisons close the loop between the preview the operator sees and the metal:

* a **review** sets the colour each layer of the exported file promised (kept with the export, see :func:`promised_layers`) beside
  the colour the photograph of the engraving measured for the layer of the same settings;
* a **drift** sets the colours a work's last file promised beside the titanium colours of the same recipes now, after new
  measurements, and proposes the closest measured colour for every source colour that moved.

Everything here is a pure function of dictionaries: no database and no work module, so :mod:`vector_job` can show the drift on the
work's screen and :mod:`work_errors` can store and refresh the conclusions. Layers are matched by their settings, never by their
index: the engraved file is not necessarily the one a work exported (LightBurn files are edited and renumbered).

Two numbers are assumptions of DEC-090, not measurements: ``VISIBLE_DE`` (the colour difference called visible) and ``IMPROVE_DE``
(the least gain that makes a replacement worth proposing). The photograph's own colour error (the chart's leave-one-out residual)
raises the first when it is larger, so a poor photograph never convicts a recipe.
"""
from __future__ import annotations

import math
import statistics

from . import color

SETTINGS = ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")
REQUIRED = ("power", "frequency", "speed", "line_interval")        # a layer without these cannot be recognised
MATCH_REL = 0.005                                                   # LightBurn rounds a setting to about four digits
VISIBLE_DE = 5.0                  # DEC-090 (assumed): a difference below this is not called an error; the chart's own error is about 3.6
IMPROVE_DE = 1.0                  # DEC-090 (assumed): a replacement must come this much closer to the source colour
HIGHLIGHT_L = 97.0                # at or above the chart's white square a colour is clipped, not measured
POOR_CHART_DE = 7.0               # a chart residual above this makes the whole photograph doubtful
HUE_MIN_CHROMA = 5.0              # below this a hue angle means nothing
SYSTEMATIC_DL = 3.0               # a median lightness shift of this size on most layers belongs to the photograph or the stock
SYSTEMATIC_SHARE = 0.75
KEPT_REVIEWS = 20


# -- recognising a recipe ---------------------------------------------------------------------------------------------------------
def settings_of(parameters: dict) -> dict:
    """The numbers that make one LightBurn layer what it is."""
    return {name: float(parameters[name]) for name in SETTINGS if parameters.get(name) is not None}


def closeness(a: dict, b: dict) -> float | None:
    """The largest relative difference between two layers' settings, or None when they cannot be the same recipe: a required setting is
    missing from one, or a setting both know differs by more than the rounding LightBurn does."""
    if any(name not in a or name not in b for name in REQUIRED):
        return None
    worst = 0.0
    for name in SETTINGS:
        if name in a and name in b:
            top = max(abs(a[name]), abs(b[name]))
            gap = 0.0 if top < 1e-9 else abs(a[name] - b[name]) / top
            if gap > MATCH_REL and abs(a[name] - b[name]) > 1e-6:
                return None
            worst = max(worst, gap)
    return worst


def match(promised: list[dict], engraved: list[dict]) -> list[tuple[int, int]]:
    """Pairs ``(promised index, engraved index)`` of layers with the same settings, each layer in at most one pair, the closest first."""
    found = []
    for i, p in enumerate(promised):
        for j, e in enumerate(engraved):
            gap = closeness(p["settings"], e["settings"])
            if gap is not None:
                found.append((gap, i, j))
    taken_p, taken_e, out = set(), set(), []
    for gap, i, j in sorted(found):
        if i not in taken_p and j not in taken_e:
            taken_p.add(i)
            taken_e.add(j)
            out.append((i, j))
    return sorted(out)


# -- what an export promises --------------------------------------------------------------------------------------------------------
def promised_layers(layers: list[dict]) -> list[dict]:
    """The colour each layer of a LightBurn file shows in the preview, kept with the export: its settings, the colour and how it was
    measured, its area and the regions it fills (a later recolouring of the work must not change what this file promised)."""
    return [{"index": layer["index"], "name": layer["name"], "entry_id": layer["entry_id"], "settings": settings_of(layer["parameters"]),
             "lab": [float(v) for v in layer["lab"]], "srgb": [int(v) for v in layer["srgb"]], "basis": layer.get("basis"),
             "area_mm2": float(layer.get("area_mm2") or 0.0), "region_ids": list(layer.get("region_ids") or [])} for layer in layers]


# -- the review -----------------------------------------------------------------------------------------------------------------------
def difference(promised_lab, got_lab) -> dict:
    """How a measured colour differs from a promised one: the colour difference and the shifts of lightness, chroma and hue (the sign is
    measured minus promised; the hue is left out where either colour is nearly grey)."""
    pl_, pa, pb = (float(v) for v in promised_lab)
    gl, ga, gb = (float(v) for v in got_lab)
    pc, gc = math.hypot(pa, pb), math.hypot(ga, gb)
    hue = None
    if min(pc, gc) >= HUE_MIN_CHROMA:
        hue = (math.degrees(math.atan2(gb, ga)) - math.degrees(math.atan2(pb, pa)) + 180.0) % 360.0 - 180.0
    return {"delta_e": float(color.delta_e(promised_lab, got_lab)), "dL": gl - pl_, "dC": gc - pc, "dh": hue}


def causes_of(row: dict, promised_basis, got_basis, measurement) -> list[dict]:
    """What the measurements themselves say about a layer's difference; nothing is guessed, a layer with no cause found has none."""
    found = []
    if row["got_lab"][0] >= HIGHLIGHT_L:
        found.append({"code": "highlight", "L": row["got_lab"][0]})
    if promised_basis and got_basis and promised_basis != got_basis:
        found.append({"code": "basis", "promised": promised_basis, "got": got_basis})
    if measurement == "relative":
        found.append({"code": "relative_photo"})
    return found


def review(promise: list[dict], engraved: list[dict], *, chart_residual: float | None = None) -> dict:
    """Set each promised layer beside the engraved layer of the same settings.

    ``promise`` are :func:`promised_layers`; ``engraved`` are the layers the photograph measured: ``{layer_index, name, settings, lab,
    basis, measurement}``. A layer is **beyond** when its colour difference exceeds ``VISIBLE_DE`` or the photograph's chart residual,
    whichever is larger. The summary weighs the colour difference by the area each layer fills in the work."""
    limit = max(VISIBLE_DE, chart_residual or 0.0)
    pairs = match(promise, engraved)
    rows = []
    for i, j in pairs:
        p, e = promise[i], engraved[j]
        diff = difference(p["lab"], e["lab"])
        row = {"layer_index": e["layer_index"], "name": e["name"], "promised_index": p["index"], "promised_name": p["name"],
               "promised_lab": p["lab"], "promised_srgb": p["srgb"], "got_lab": [float(v) for v in e["lab"]],
               "got_srgb": [int(v) for v in color.lab_to_srgb8(e["lab"])], "area_mm2": p["area_mm2"], **diff,
               "beyond": diff["delta_e"] > limit}
        row["causes"] = causes_of(row, p.get("basis"), e.get("basis"), e.get("measurement"))
        rows.append(row)
    area = sum(r["area_mm2"] for r in rows)
    beyond_area = sum(r["area_mm2"] for r in rows if r["beyond"])
    notes = []
    if chart_residual is not None and chart_residual > POOR_CHART_DE:
        notes.append({"code": "poor_chart", "residual": chart_residual})
    median_dl = statistics.median([r["dL"] for r in rows]) if rows else None
    if len(rows) >= 4 and median_dl is not None and abs(median_dl) >= SYSTEMATIC_DL:
        same = sum(1 for r in rows if (r["dL"] > 0) == (median_dl > 0)) / len(rows)
        if same >= SYSTEMATIC_SHARE:
            notes.append({"code": "systematic", "dL": median_dl, "share": same})
    matched_p, matched_e = {i for i, _ in pairs}, {j for _, j in pairs}
    return {"limit": limit, "rows": rows,
            "not_engraved": [{"index": p["index"], "name": p["name"], "area_mm2": p["area_mm2"]} for i, p in enumerate(promise) if i not in matched_p],
            "unmatched": [{"layer_index": e["layer_index"], "name": e["name"]} for j, e in enumerate(engraved) if j not in matched_e],
            "notes": notes,
            "summary": {"promised": len(promise), "engraved": len(engraved), "matched": len(rows), "area_mm2": area, "beyond_area_mm2": beyond_area,
                        "area_share_beyond": (beyond_area / area) if area else None,
                        "mean_delta_e": (sum(r["delta_e"] * r["area_mm2"] for r in rows) / area) if area else
                        (statistics.mean([r["delta_e"] for r in rows]) if rows else None),
                        "median_dL": median_dl, "beyond_layers": sum(1 for r in rows if r["beyond"])}}


# -- the drift ----------------------------------------------------------------------------------------------------------------------------
def baseline_of(plan: dict) -> tuple[list[dict] | None, bool]:
    """What the work promised the last time a file was made from it, and whether that is only reconstructed.

    ``(None, False)`` for a work that was never exported (its preview is still live, nothing was promised). A file made before promises
    were kept is reconstructed from the work's own layers while its colouring and split are still the ones the file was made from;
    after that the promise is lost and nothing is claimed. Making another file renews the promise: the operator has then accepted the
    colours as they are."""
    exports = plan.get("exports") or []
    for export in reversed(exports):
        if export.get("promised"):
            return export["promised"], False
        break
    if exports and plan.get("layers") and exports[-1].get("colouring") == plan.get("colouring") and exports[-1].get("document_version") == plan.get("document_version"):
        return promised_layers(plan["layers"]), True
    return None, False


def drift(baseline: list[dict], colours: list[dict], by_id: dict, candidates: list[dict], used: set, approximate: bool = False) -> dict:
    """The layers of a work whose titanium colour is no longer the one its last file promised, and what could replace it.

    ``baseline`` are the layers of the last export (:func:`baseline_of`), ``colours`` and ``by_id`` the work's state now
    (:func:`vector_job._state`), ``candidates`` the palette entries the work may choose and ``used`` the entries its colouring uses
    now: a promised layer whose recipe the work no longer uses is settled and is not listed. A layer **drifted** when its recipe's
    colour moved by more than ``VISIBLE_DE``, or is not measured any more. For each source colour that uses a drifted layer the closest
    candidate is proposed when it comes ``IMPROVE_DE`` nearer to the source colour than the colour it has now; a colour chosen region by
    region is not proposed for (its brush strokes stay the operator's)."""
    total = sum(float(layer.get("area_mm2") or 0.0) for layer in baseline)
    by_entry: dict[str, list[dict]] = {}
    for c in colours:
        if c["entry_id"] is not None and c["status"] != "excluded":
            by_entry.setdefault(c["entry_id"], []).append(c)
    out = []
    for layer in baseline:
        if layer["entry_id"] not in used:
            continue
        entry = by_id.get(layer["entry_id"])
        if entry is None:
            moved, now_lab = None, None
        else:
            moved = float(color.delta_e(layer["lab"], entry["lab"]))
            now_lab = entry["lab"]
            if moved <= VISIBLE_DE:
                continue
        proposals = []
        for c in by_entry.get(layer["entry_id"], []):
            current = None if entry is None else float(color.delta_e(c["lab"], entry["lab"]))
            best = min(candidates, key=lambda e: color.delta_e(c["lab"], e["lab"]), default=None)
            best_de = None if best is None else float(color.delta_e(c["lab"], best["lab"]))
            better = best is not None and best["id"] != layer["entry_id"] and (current is None or best_de <= current - IMPROVE_DE)
            proposals.append({"colour": c["index"], "lab": c["lab"], "srgb": c["srgb"], "delta_e_now": current,
                              "entry_id": best["id"] if better else None, "entry_lab": best["lab"] if better else None,
                              "entry_srgb": best["srgb"] if better else None, "delta_e_proposed": best_de if better else None})
        out.append({"index": layer["index"], "name": layer["name"], "entry_id": layer["entry_id"], "was_lab": layer["lab"],
                    "was_srgb": layer["srgb"], "now_lab": now_lab, "now_srgb": None if entry is None else entry["srgb"], "delta_e": moved,
                    "missing": entry is None, "area_mm2": float(layer.get("area_mm2") or 0.0), "proposals": proposals})
    area = sum(d["area_mm2"] for d in out)
    return {"layers": out, "layers_total": len(baseline), "area_mm2": area, "area_share": (area / total) if total else 0.0,
            "visible_de": VISIBLE_DE, "approximate": approximate}


def attention_of(found: dict, checked_at: str) -> dict:
    """What the list of works keeps of a drift: counts only, so the list never opens a palette."""
    return {"layers": len(found["layers"]), "area_mm2": round(found["area_mm2"], 1), "area_share": round(found["area_share"], 4),
            "proposals": sum(1 for d in found["layers"] for p in d["proposals"] if p["entry_id"]), "checked_at": checked_at}


def newest_first(reviews: list[dict]) -> list[dict]:
    return sorted(reviews, key=lambda r: r["reviewed_at"], reverse=True)
