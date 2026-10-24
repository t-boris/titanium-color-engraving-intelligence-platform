"""What the colour map, the palettes and the tonal curves of a store give, reduced to plain numbers and keys (electron REQ-083): the golden
record of the local results (``test_evidence_golden``) and the comparison of a workshop with its published release (``test_lab_parity``)."""
from __future__ import annotations

import math

import numpy as np

from titanium_platform import colormap, palette, prediction, prediction_store as ps
from titanium_platform.prediction import PredictionError

DIGITS = 9


def plain(value):
    """``value`` with every float rounded to ``DIGITS`` places and numpy values made Python ones, so two results compare as JSON."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if not math.isfinite(f) else round(f, DIGITS)
    if isinstance(value, np.integer):
        return int(value)
    return value


POINT_KEYS = ("pair_id", "layer_index", "measurement", "approximate", "referenced", "provisional", "lab", "display_lab", "row_mm",
              "origin", "engraving_id", "trust", "confidence", "caution", "doubtful", "time_s_per_cm2")
ENTRY_KEYS = ("lab", "basis", "measurement", "approximate", "referenced", "engravings", "photographs", "caution", "confidence",
              "expected_delta_e", "stability", "agreement", "doubtful", "parameters", "mode", "time_s_per_cm2", "missing_context", "sizes")


def colour_map(store) -> dict:
    data = colormap.collect(store)
    colormap.annotate(data["points"])
    points = [{"id": str(p["id"]), "task": p["task"]["kind"], **{k: p.get(k) for k in POINT_KEYS}} for p in data["points"]]
    return plain({"nominal_clean": data["nominal_clean"], "counts": data["counts"], "points": points})


def vector_palette(store, device_id, lens_id, material_id) -> dict:
    found = palette.vector_palette(store, device_id, lens_id, material_id)
    return plain({"left_out": found["left_out"], "cautions": found["cautions"],
                  "entries": [{"observations": e["observation_ids"], **{k: e.get(k) for k in ENTRY_KEYS}} for e in found["entries"]]})


def curve(store, mode: ps.Mode, row_mm=None) -> dict:
    try:
        made, basis = ps.curve_for(store, mode, row_mm)
    except PredictionError as exc:
        return {"error": str(exc)}
    rows = [{"power": r["power"], "lab": r["lab"], "engravings": r.get("engravings"), "spread_de": r.get("spread_de"),
             "pairs": sorted({s["pair_id"] for s in r["sources"]})} for r in made.points]
    return plain({"span": list(made.span), "referenced": made.referenced, "axis": made.axis, "size": dict(made.size or {}),
                  "reference": basis["reference"], "sizes": basis["sizes"], "points": rows})


def scales(store) -> list:
    out = []
    for item in ps.scales(store):
        out.append({k: item[k] for k in ("span", "points", "engravings", "by_kind", "reference", "referenced", "bar", "confirmation",
                                          "fills", "time_s_per_cm2", "size", "sizes")})
    return plain(out)
