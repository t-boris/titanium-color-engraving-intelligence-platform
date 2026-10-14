"""Image -> EngravingPlan conversions: Discrete Color Engraving and Continuous Photo Engraving.

Shared pieces: eligible palette (validated/production knowledge with a full prediction), questioned-entry
rules (DEC-018), image quantisation into millimetre rectangles, and plan persistence. Plan generation never
changes a knowledge entry's stage or questioned flag (REQ-005).

Geometry assumption (not in the requirements): the work is rendered at a fixed raster of at most
``MAX_RASTER_PX`` pixels on its longer side; every pixel run becomes a rectangle in the LightBurn file, so a
plan describes the image at that resolution.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import cv2
import numpy as np
from sklearn.cluster import KMeans

from . import color, knowledge as kn, plans as pl, profiles as pf
from .db import Store, now

MAX_RASTER_PX = 160
MAX_COLORS = 16
ELIGIBLE_STAGES = ("validated", "production")
ST_DRAFT, ST_READY = "Draft", "Ready to export"


class ConversionError(ValueError):
    """The conversion cannot proceed; the message is meant for the operator."""


def decode_image_bytes(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ConversionError("the image could not be read")
    return img


def raster(img_bgr: np.ndarray, width_mm: float) -> tuple[np.ndarray, float]:
    """Resize to the working raster; returns (RGB uint8 image, millimetres per pixel)."""
    if not np.isfinite(width_mm) or width_mm <= 0:
        raise ConversionError("the work width must be a positive number of millimetres")
    h, w = img_bgr.shape[:2]
    scale = min(1.0, MAX_RASTER_PX / max(h, w))
    small = cv2.resize(img_bgr, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB), width_mm / small.shape[1]


def mask_to_rects(mask: np.ndarray, px_mm: float) -> list[dict]:
    """Greedy rectangles covering a boolean mask exactly: row runs merged with identical runs below."""
    rects, active = [], {}
    for y in range(mask.shape[0] + 1):
        runs = set()
        if y < mask.shape[0]:
            row = np.concatenate(([0], mask[y].astype(np.int8), [0]))
            edges = np.flatnonzero(np.diff(row))
            runs = {(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])}
        for run in list(active):
            if run not in runs:
                y0 = active.pop(run)
                rects.append({"x": run[0] * px_mm, "y": y0 * px_mm, "width": (run[1] - run[0]) * px_mm, "height": (y - y0) * px_mm})
        for run in runs:
            active.setdefault(run, y)
    return rects


def eligible_palette(store: Store, profile_id: int, allowed_questioned=(), include_questioned_warning=False) -> list[dict]:
    """Validated/production knowledge with all three estimates. Questioned entries only if allowed for this plan."""
    out = []
    for k in kn.list_for_profile(store, profile_id):
        s = k["summary"]
        if k["stage"] not in ELIGIBLE_STAGES or not s or not s["available"]:
            continue
        if k["questioned"] and k["id"] not in allowed_questioned and not include_questioned_warning:
            continue
        out.append({"id": k["id"], "key": k["parameters_key"], "stage": k["stage"], "questioned": k["questioned"], "parameters": k["parameters"],
                    "lab": s["lab"], "confidence": s["confidence"], "expected_delta_e": s["expected_delta_e"], "stability": s["stability"],
                    "observation_ids": s["observation_ids"], "doubt": k["doubt"]})
    return out


def prediction_of(entry: dict) -> dict:
    return {"lab": entry["lab"], "confidence": entry["confidence"], "expected_delta_e": entry["expected_delta_e"], "stability": entry["stability"]}


def layer_from_entry(index: int, name: str, entry: dict, regions: list[dict], **extra) -> dict:
    return {"index": index, "name": name, "parameters": entry["parameters"], "regions": regions, "prediction": prediction_of(entry),
            "knowledge_id": entry["id"], "stage": entry["stage"], "questioned": entry["questioned"], **extra}


def save_plan(store: Store, plan_id: int | None, *, name: str, mode: str, status: str, profile_id: int, markers: bool,
              identifier: str, band_count: int | None, data: dict) -> int:
    row = (name, mode, status, profile_id, int(markers), identifier, band_count, json.dumps(data))
    if plan_id is None:
        return store.execute("INSERT INTO plan(name,mode,status,profile_id,markers,plan_identifier,band_count,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (*row, now())).lastrowid
    store.execute("UPDATE plan SET name=?,mode=?,status=?,profile_id=?,markers=?,plan_identifier=?,band_count=?,data_json=? WHERE id=?", (*row, plan_id))
    return plan_id


def _store_image(store: Store, data: bytes) -> str:
    path = store.data_dir / "files" / f"image-{uuid.uuid4().hex[:12]}.bin"
    path.write_bytes(data)
    return str(path)


def _plan_markers(identifier: str, enabled: bool, width: float, height: float, store: Store) -> dict | None:
    if not enabled:
        return None
    if pl.marker_layer_settings(store) is None:
        raise ConversionError("set the marker layer power, frequency and speed before enabling registration markers")
    return pl.marker_geometry(identifier, width, height)


def set_markers(store: Store, plan_id: int, enabled: bool) -> dict:
    """Toggle registration markers; changing them invalidates a ready plan (prototype BP-46)."""
    plan = pl.get_plan(store, plan_id)
    if plan["mode"] == pl.MODE_PLATE:
        raise ConversionError("calibration plates always carry markers")
    g = plan.get("size_mm") or {}
    plan["markers"] = _plan_markers(plan["plan_identifier"], enabled, g.get("width", 0), g.get("height", 0), store) if g else None
    plan["marker_layer"] = pl.marker_layer_settings(store) if enabled else None
    _persist(store, plan, ST_DRAFT if plan["status"] == ST_READY else plan["status"], enabled)
    return pl.get_plan(store, plan_id)


def _persist(store: Store, plan: dict, status: str, markers_enabled: bool) -> None:
    data = {k: v for k, v in plan.items() if k not in ("id", "name", "mode", "status", "profile_id", "plate_id", "markers_enabled", "plan_identifier", "band_count", "created_at")}
    store.execute("UPDATE plan SET status=?, markers=?, data_json=? WHERE id=?", (status, int(markers_enabled), json.dumps(data), plan["id"]))


# ======================================================================================================
# Discrete Color Engraving (REQ-004, DEC-009, DEC-018, proposed DEC-030)
# ======================================================================================================
def _cluster(rgb: np.ndarray, max_colors: int):
    """Deterministic k-means in Lab. Returns (labels HxW, centers Lab, pixel counts), colors sorted by lightness."""
    lab = color.srgb8_to_lab(rgb.reshape(-1, 3).astype(float))
    unique = len(np.unique(np.round(lab, 1), axis=0))
    k = max(1, min(max_colors, unique))
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(lab)
    centers = km.cluster_centers_
    order = np.lexsort((centers[:, 2], centers[:, 1], -centers[:, 0]))
    remap = np.empty(k, int)
    remap[order] = np.arange(k)
    labels = remap[km.labels_].reshape(rgb.shape[:2])
    return labels, centers[order], np.bincount(labels.ravel(), minlength=k)


def _threshold(store: Store, profile_id: int, value) -> float:
    """The delta E threshold is always explicit: given for the plan or taken from the saved rules, never invented."""
    if value is None:
        value = pf.get_rules(store, profile_id)["delta_tolerance"]
    if value is None:
        raise ConversionError("set the delta E threshold for this plan (no tolerance is saved for the laser profile)")
    value = float(value)
    if not np.isfinite(value) or value < 0:
        raise ConversionError("enter a non-negative delta E threshold")
    return value


def compute_matches(source_colors: list[dict], palette: list[dict], threshold: float, replacements: dict, exclusions: list) -> list[dict]:
    by_id = {e["id"]: e for e in palette}
    out = []
    for c in source_colors:
        m = {"source_key": c["key"], "source_lab": c["lab"], "status": None, "knowledge_id": None, "distance": None, "match_error": None,
             "candidate_id": None}
        if c["key"] in exclusions:
            m["status"] = "excluded"
        elif c["key"] in replacements:
            e = by_id[replacements[c["key"]]]
            m.update(status="replaced", knowledge_id=e["id"], distance=color.delta_e(e["lab"], c["lab"]))
            m["match_error"] = m["distance"] + e["expected_delta_e"]
        elif not palette:
            m["status"] = "unreachable"
        else:
            e = min(palette, key=lambda p: (color.delta_e(p["lab"], c["lab"]), p["id"]))
            dist = color.delta_e(e["lab"], c["lab"])
            err = dist + e["expected_delta_e"]  # DEC-030: distance to the request plus the entry's own measured scatter
            m.update(distance=dist, match_error=err, candidate_id=e["id"])
            if err <= threshold:
                m.update(status="matched", knowledge_id=e["id"])
            else:
                m["status"] = "unreachable"
        out.append(m)
    return out


def _register_targets(store: Store, profile_id: int, plan_id: int, matches: list[dict]) -> None:
    """Every unreachable color becomes an Experiment Designer target; re-matching never duplicates one (DEC-009)."""
    for m in matches:
        if m["status"] == "unreachable":
            store.execute("INSERT OR IGNORE INTO target_color(profile_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,?,?)",
                          (profile_id, json.dumps(m["source_lab"]), plan_id, m["source_key"], now()))


def start_discrete(store: Store, profile_id: int, image_bytes: bytes, width_mm: float, name: str, threshold=None,
                   markers: bool = False, max_colors: int = MAX_COLORS) -> int:
    pf.get_profile(store, profile_id)
    thr = _threshold(store, profile_id, threshold)
    if not (name or "").strip():
        raise ConversionError("give the plan a name")
    if not 1 <= max_colors <= MAX_COLORS:
        raise ConversionError(f"the number of colors must be between 1 and {MAX_COLORS}")
    rgb, px_mm = raster(decode_image_bytes(image_bytes), width_mm)
    labels, centers, counts = _cluster(rgb, max_colors)
    h_mm = rgb.shape[0] * px_mm
    source = [{"key": f"c{i}", "lab": [float(v) for v in centers[i]], "pixels": int(counts[i]), "share": float(counts[i] / labels.size)} for i in range(len(centers))]
    identifier = pl.new_identifier("TCE-A")
    labels_path = store.data_dir / "files" / f"labels-{uuid.uuid4().hex[:12]}.npy"
    np.save(labels_path, labels.astype(np.int16))
    data = {"image_path": _store_image(store, image_bytes), "labels_path": str(labels_path), "size_mm": {"width": float(width_mm), "height": h_mm},
            "px_mm": px_mm, "threshold": thr, "source_colors": source, "replacements": {}, "exclusions": [], "allowed_questioned": [],
            "matches": [], "layers": [], "markers": _plan_markers(identifier, markers, float(width_mm), h_mm, store),
            "marker_layer": pl.marker_layer_settings(store) if markers else None}
    with store.transaction():
        plan_id = save_plan(store, None, name=name.strip(), mode=pl.MODE_DISCRETE, status=ST_DRAFT, profile_id=profile_id, markers=markers,
                            identifier=identifier, band_count=None, data=data)
        return update_discrete(store, plan_id)


def update_discrete(store: Store, plan_id: int, threshold=None, replacements: dict | None = None, exclusions: list | None = None,
                    allowed_questioned: list | None = None) -> int:
    """Re-match after a change. Any change returns the plan to Draft: it must be finalised again."""
    plan = pl.get_plan(store, plan_id)
    if plan["mode"] != pl.MODE_DISCRETE:
        raise ConversionError("this is not a discrete color plan")
    pid = plan["profile_id"]
    if threshold is not None:
        plan["threshold"] = _threshold(store, pid, threshold)
    keys = {c["key"] for c in plan["source_colors"]}
    if exclusions is not None:
        if not set(exclusions) <= keys:
            raise ConversionError("unknown source color in the exclusions")
        plan["exclusions"] = sorted(exclusions)
    if allowed_questioned is not None:
        plan["allowed_questioned"] = sorted(set(int(x) for x in allowed_questioned))
    palette = eligible_palette(store, pid, allowed_questioned=plan["allowed_questioned"])
    if replacements is not None:
        ids = {e["id"] for e in palette}
        if not set(replacements) <= keys or not set(replacements.values()) <= ids:
            raise ConversionError("a replacement must be a validated or production color from the eligible palette")
        plan["replacements"] = {k: int(v) for k, v in replacements.items()}
    # a replacement or allowance that is no longer eligible falls back to automatic matching
    plan["replacements"] = {k: v for k, v in plan["replacements"].items() if v in {e["id"] for e in palette}}
    plan["matches"] = compute_matches(plan["source_colors"], palette, plan["threshold"], plan["replacements"], plan["exclusions"])
    plan["layers"] = []
    plan["questioned_available"] = [e["id"] for e in eligible_palette(store, pid, include_questioned_warning=True) if e["questioned"]]
    _persist(store, plan, ST_DRAFT, plan["markers_enabled"])
    _register_targets(store, pid, plan_id, plan["matches"])
    return plan_id


def finalize_discrete(store: Store, plan_id: int) -> dict:
    plan = pl.get_plan(store, plan_id)
    if plan["mode"] != pl.MODE_DISCRETE:
        raise ConversionError("this is not a discrete color plan")
    unresolved = [m for m in plan["matches"] if m["status"] == "unreachable"]
    if unresolved:
        raise ConversionError(f"{len(unresolved)} unreachable color(s) must be replaced or excluded before the plan can be finalised")
    active = [m for m in plan["matches"] if m["status"] in ("matched", "replaced")]
    if not active:
        raise ConversionError("every color is excluded: there is nothing to engrave")
    labels = np.load(plan["labels_path"])
    key_index = {c["key"]: i for i, c in enumerate(plan["source_colors"])}
    palette = {e["id"]: e for e in eligible_palette(store, plan["profile_id"], allowed_questioned=plan["allowed_questioned"])}
    by_entry: dict[int, list[str]] = {}
    for m in active:
        by_entry.setdefault(m["knowledge_id"], []).append(m["source_key"])
    layers = []
    for n, (kid, keys) in enumerate(sorted(by_entry.items()), start=1):
        entry = palette[kid]
        mask = np.isin(labels, [key_index[k] for k in keys])
        layers.append(layer_from_entry(n, f"K{kid}", entry, mask_to_rects(mask, plan["px_mm"]), source_color_keys=keys))
    if len(layers) > pl.MAX_LAYERS:
        raise ConversionError(f"{len(layers)} distinct colors need more LightBurn layers than the {pl.MAX_LAYERS} available")
    plan["layers"] = layers
    _persist(store, plan, ST_READY, plan["markers_enabled"])
    return pl.get_plan(store, plan_id)
