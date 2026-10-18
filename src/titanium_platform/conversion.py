"""Image -> EngravingPlan conversions: Discrete Color Engraving and Continuous Photo Engraving.

Shared pieces: eligible palette (validated/production knowledge with a full prediction), questioned-entry
rules (DEC-018), image quantisation into millimetre rectangles, and plan persistence. Plan generation never
changes a knowledge entry's stage or questioned flag (REQ-005). A plan uses the knowledge of one laser and one lens record
(DEC-063) and remembers that lens with its spot value (REQ-019).

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

from . import color, knowledge as kn, plans as pl, setup as su
from .db import Store, now

MAX_RASTER_PX = 160
MAX_COLORS = 16
ELIGIBLE_STAGES = ("validated", "production")
ST_DRAFT, ST_READY = "Draft", "Ready to export"
# LightBurn modes of a recipe (the layer type of the file it was measured from). A conversion fills areas, so it uses the
# filling modes; None is an entry recorded before the mode was kept, exported as a fill as it always was.
FILL_MODES = frozenset({None, "Scan", "Fill", "OffsetFill", "Offset Fill", "Scan+Cut"})
LINE_MODES = frozenset({"Cut"})
PICTURE_PX = 640           # the longer side of a banding picture: the working raster enlarged without smoothing


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


def eligible_palette(store: Store, device_id: int, lens_id: int | None, allowed_questioned=(), include_questioned_warning=False,
                     modes=FILL_MODES) -> list[dict]:
    """Validated/production knowledge of one laser and lens with all three estimates. Questioned entries only if allowed for this plan.

    Only recipes whose LightBurn mode is in ``modes`` (all when None): a line recipe never fills the area of a conversion.
    Each entry names its mode and the titanium stock (``material_id``) it was measured on, None when that is not one known stock.
    """
    out = []
    for k in kn.list_for_setup(store, device_id, lens_id):
        s = k["summary"]
        if k["stage"] not in ELIGIBLE_STAGES or not s or not s["available"]:
            continue
        if k["questioned"] and k["id"] not in allowed_questioned and not include_questioned_warning:
            continue
        mode = k["parameters"].get("layer_type")
        if modes is not None and mode not in modes:
            continue
        stocks = {g["material_id"] for g in s["context_groups"]}
        out.append({"id": k["id"], "key": k["parameters_key"], "stage": k["stage"], "questioned": k["questioned"], "parameters": k["parameters"],
                    "lab": s["lab"], "confidence": s["confidence"], "expected_delta_e": s["expected_delta_e"], "stability": s["stability"],
                    "observation_ids": s["observation_ids"], "doubt": k["doubt"], "mode": mode,
                    "material_id": stocks.pop() if len(stocks) == 1 else None})
    return out


def prediction_of(entry: dict) -> dict:
    return {"lab": entry["lab"], "confidence": entry["confidence"], "expected_delta_e": entry["expected_delta_e"], "stability": entry["stability"]}


def layer_from_entry(index: int, name: str, entry: dict, regions: list[dict], **extra) -> dict:
    return {"index": index, "name": name, "parameters": entry["parameters"], "regions": regions, "prediction": prediction_of(entry),
            "knowledge_id": entry["id"], "stage": entry["stage"], "questioned": entry["questioned"], **extra}


def save_plan(store: Store, plan_id: int | None, *, name: str, mode: str, status: str, device_id: int, lens_id: int | None,
              markers: bool, identifier: str, band_count: int | None, data: dict) -> int:
    row = (name, mode, status, device_id, lens_id, int(markers), identifier, band_count, json.dumps(data))
    if plan_id is None:
        return store.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,plan_identifier,band_count,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (*row, now())).lastrowid
    store.execute("UPDATE plan SET name=?,mode=?,status=?,device_id=?,lens_id=?,markers=?,plan_identifier=?,band_count=?,data_json=? WHERE id=?", (*row, plan_id))
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
    # a vector job keeps its status: it is ready whenever every region has its evidence, which markers do not change
    _persist(store, plan, ST_DRAFT if plan["status"] == ST_READY and plan["mode"] != pl.MODE_VECTOR else plan["status"], enabled)
    return pl.get_plan(store, plan_id)


def _persist(store: Store, plan: dict, status: str, markers_enabled: bool) -> None:
    data = {k: v for k, v in plan.items() if k not in ("id", "name", "mode", "status", "device_id", "lens_id", "legacy_profile_id", "plate_id",
                                                        "markers_enabled", "plan_identifier", "band_count", "created_at", "research_session_id")}
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


def _threshold(store: Store, device_id: int, lens_id: int | None, value) -> float:
    """The delta E threshold is always explicit: given for the plan or taken from the rules of its laser and lens, never invented."""
    if value is None:
        value = su.get_rules(store, device_id, lens_id)["delta_tolerance"]
    if value is None:
        raise ConversionError("set the delta E threshold for this plan (no tolerance is saved for this laser and lens)")
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


def _register_targets(store: Store, device_id: int, lens_id: int | None, plan_id: int, matches: list[dict]) -> None:
    """Every unreachable color becomes an Experiment Designer target of the plan's laser and lens; re-matching never
    duplicates one (DEC-009)."""
    for m in matches:
        if m["status"] == "unreachable":
            store.execute("INSERT OR IGNORE INTO target_color(device_id,lens_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (?,?,?,?,?,?)",
                          (device_id, lens_id, json.dumps(m["source_lab"]), plan_id, m["source_key"], now()))


def start_discrete(store: Store, device_id: int, lens_id: int | None, image_bytes: bytes, width_mm: float, name: str,
                   threshold=None, markers: bool = False, max_colors: int = MAX_COLORS) -> int:
    lens = su.lens_snapshot(su.resolve(store, device_id, lens_id))
    thr = _threshold(store, device_id, lens_id, threshold)
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
            "marker_layer": pl.marker_layer_settings(store) if markers else None, "lens": lens}
    with store.transaction():
        plan_id = save_plan(store, None, name=name.strip(), mode=pl.MODE_DISCRETE, status=ST_DRAFT, device_id=device_id, lens_id=lens_id, markers=markers,
                            identifier=identifier, band_count=None, data=data)
        return update_discrete(store, plan_id)


def update_discrete(store: Store, plan_id: int, threshold=None, replacements: dict | None = None, exclusions: list | None = None,
                    allowed_questioned: list | None = None) -> int:
    """Re-match after a change. Any change returns the plan to Draft: it must be finalised again."""
    plan = pl.get_plan(store, plan_id)
    if plan["mode"] != pl.MODE_DISCRETE:
        raise ConversionError("this is not a discrete color plan")
    partition = (plan["device_id"], plan["lens_id"])
    if threshold is not None:
        plan["threshold"] = _threshold(store, *partition, threshold)
    keys = {c["key"] for c in plan["source_colors"]}
    if exclusions is not None:
        if not set(exclusions) <= keys:
            raise ConversionError("unknown source color in the exclusions")
        plan["exclusions"] = sorted(exclusions)
    if allowed_questioned is not None:
        plan["allowed_questioned"] = sorted(set(int(x) for x in allowed_questioned))
    palette = eligible_palette(store, *partition, allowed_questioned=plan["allowed_questioned"])
    if replacements is not None:
        ids = {e["id"] for e in palette}
        if not set(replacements) <= keys or not set(replacements.values()) <= ids:
            raise ConversionError("a replacement must be a validated or production color from the eligible palette")
        plan["replacements"] = {k: int(v) for k, v in replacements.items()}
    # a replacement or allowance that is no longer eligible falls back to automatic matching
    plan["replacements"] = {k: v for k, v in plan["replacements"].items() if v in {e["id"] for e in palette}}
    plan["matches"] = compute_matches(plan["source_colors"], palette, plan["threshold"], plan["replacements"], plan["exclusions"])
    plan["layers"] = []
    plan["questioned_available"] = [e["id"] for e in eligible_palette(store, *partition, include_questioned_warning=True) if e["questioned"]]
    _persist(store, plan, ST_DRAFT, plan["markers_enabled"])
    _register_targets(store, *partition, plan_id, plan["matches"])
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
    palette = {e["id"]: e for e in eligible_palette(store, plan["device_id"], plan["lens_id"], allowed_questioned=plan["allowed_questioned"])}
    by_entry: dict[int, list[str]] = {}
    for m in active:
        by_entry.setdefault(m["knowledge_id"], []).append(m["source_key"])
    layers = []
    for n, (kid, keys) in enumerate(sorted(by_entry.items()), start=1):
        entry = palette[kid]
        mask = np.isin(labels, [key_index[k] for k in keys])
        layers.append(layer_from_entry(n, f"K{kid}", entry, mask_to_rects(mask, plan["px_mm"]), source_color_keys=keys))
    available = pl.MAX_LAYERS - 1  # color 00 remains reserved for the marker layer in engraving plans
    if len(layers) > available:
        raise ConversionError(f"{len(layers)} distinct colors need more LightBurn layers than the {available} available after registration")
    plan["layers"] = layers
    _persist(store, plan, ST_READY, plan["markers_enabled"])
    return pl.get_plan(store, plan_id)


# ======================================================================================================
# Continuous Photo Engraving: Tonal and Color-path on one transfer-function abstraction (DEC-007, proposed DEC-032)
# ======================================================================================================
MODE_FOR = {"tonal": pl.MODE_TONAL, "color_path": pl.MODE_COLOR_PATH}
MAX_BANDS = pl.MAX_LAYERS - 1  # one output color is reserved for registration when enabled


def build_transfer(mode: str, entries: list[dict], path_ids: list[int] | None = None) -> dict:
    """One abstraction: an ordered list of measured entries, each with a position in 0..1.

    Tonal: entries sorted by measured lightness, position = lightness normalised between the darkest and the
    brightest entry. Color-path: the operator's ordered trajectory, position = cumulative delta E along it.
    Parameters are never interpolated, so every band uses a parameter set that was measured.

    Each point stores a snapshot of its Lab at planning time. Analysis compares a result with the trajectory
    *as planned*; reading it from live knowledge would let the measurement under evaluation move the very
    trajectory it is compared with.
    """
    if mode == "tonal":
        if len({round(e["lab"][0], 6) for e in entries}) < 2:
            raise ConversionError("a Tonal curve needs at least two eligible colors with different lightness")
        ordered = sorted(entries, key=lambda e: (e["lab"][0], e["id"]))
        lo, hi = ordered[0]["lab"][0], ordered[-1]["lab"][0]
        points = [{"knowledge_id": e["id"], "position": (e["lab"][0] - lo) / (hi - lo), "lab": list(e["lab"])} for e in ordered]
    elif mode == "color_path":
        by_id = {e["id"]: e for e in entries}
        ids = list(path_ids or [])
        if len(ids) < 2 or len(set(ids)) != len(ids):
            raise ConversionError("a Color-path needs an ordered trajectory of at least two distinct eligible colors")
        if not set(ids) <= set(by_id):
            raise ConversionError("the trajectory uses a color that is not eligible (validated or production, and not questioned unless allowed)")
        steps = [color.delta_e(by_id[a]["lab"], by_id[b]["lab"]) for a, b in zip(ids, ids[1:])]
        total = sum(steps)
        if total <= 0:
            raise ConversionError("the trajectory colors are identical")
        cum = np.concatenate(([0.0], np.cumsum(steps))) / total
        points = [{"knowledge_id": i, "position": float(p), "lab": list(by_id[i]["lab"])} for i, p in zip(ids, cum)]
    else:
        raise ConversionError("mode must be 'tonal' or 'color_path'")
    return {"mode": mode, "points": points}


def band_entries(transfer: dict, n: int) -> list[int]:
    """Knowledge id for each band: the point nearest the band middle (i + 0.5) / n; ties go to the lower position."""
    pts = transfer["points"]
    # Distances are rounded before comparing: 0.5 - 1/3 and 2/3 - 0.5 differ in the last float digit, which would
    # otherwise decide a mathematical tie by rounding noise instead of by the documented lower-position rule.
    return [min(pts, key=lambda p: (round(abs(p["position"] - (i + 0.5) / n), 9), p["position"]))["knowledge_id"] for i in range(n)]


def quantize_luminance(img_rgb: np.ndarray, n: int) -> np.ndarray:
    """Band index per pixel from Lab lightness: u = L / 100, band = floor(u * n), last band includes u = 1."""
    lab = color.srgb8_to_lab(img_rgb.reshape(-1, 3).astype(float))
    u = np.clip(lab[:, 0] / 100.0, 0.0, 1.0)
    return np.minimum((u * n).astype(int), n - 1).reshape(img_rgb.shape[:2])


def _check_bands(n) -> int:
    if int(n) != n or n < 1:
        raise ConversionError("enter a positive whole number of bands")
    if n > MAX_BANDS:
        raise ConversionError(f"{int(n)} bands need more LightBurn layers than the {MAX_BANDS} available")
    return int(n)


def preview_continuous(store: Store, device_id: int, lens_id: int | None, mode: str, image_bytes: bytes, width_mm: float, n_bands: int,
                       path_ids: list[int] | None = None, allowed_questioned: list[int] | None = None) -> dict:
    """Compute the banding without saving anything. Returns the layers, warnings and per-band pixel share."""
    n = _check_bands(n_bands)
    allowed = [int(x) for x in (allowed_questioned or [])]
    if mode == "tonal":
        # Tonal may use questioned production entries with a warning and no confirmation (DEC-018)
        entries = eligible_palette(store, device_id, lens_id, include_questioned_warning=True)
    else:
        entries = eligible_palette(store, device_id, lens_id, allowed_questioned=allowed)
    transfer = build_transfer(mode, entries, path_ids)
    rgb, px_mm = raster(decode_image_bytes(image_bytes), width_mm)
    bands = quantize_luminance(rgb, n)
    chosen = band_entries(transfer, n)
    by_id = {e["id"]: e for e in entries}
    layers, counts = [], np.bincount(bands.ravel(), minlength=n)
    for i in range(n):
        regions = mask_to_rects(bands == i, px_mm)
        layers.append(layer_from_entry(i + 1, f"B{i + 1:02d}", by_id[chosen[i]], regions, band=i, pixels=int(counts[i]), share=float(counts[i] / bands.size)))
    warnings = []
    if mode == "tonal":
        used = sorted({l["knowledge_id"] for l in layers if l["questioned"]})
        if used:
            # every questioned entry the plan uses is listed with what put it in doubt and the observations behind it (DEC-018)
            entries = [{"knowledge_id": k, "lab": by_id[k]["lab"], "reason": (by_id[k]["doubt"] or {}).get("reason"),
                        "observation_ids": by_id[k]["observation_ids"]} for k in used]
            warnings.append({"type": "questioned_in_tonal", "knowledge_ids": used, "entries": entries,
                             "message": "This Tonal plan uses production parameter sets that are questioned. No confirmation is needed; review the observations behind them.",
                             "observation_ids": sorted({o for k in used for o in by_id[k]["observation_ids"]})})
    return {"transfer": transfer, "layers": layers, "warnings": warnings, "size_mm": {"width": float(width_mm), "height": rgb.shape[0] * px_mm}, "px_mm": px_mm,
            "distinct_entries": len(set(chosen)), "bands": n, "empty_bands": int((counts == 0).sum()), "band_map": bands}


def create_continuous(store: Store, device_id: int, lens_id: int | None, mode: str, image_bytes: bytes, width_mm: float, n_bands: int,
                      name: str, path_ids: list[int] | None = None, allowed_questioned: list[int] | None = None, markers: bool = False,
                      revision_of: int | None = None) -> int:
    """A new continuous plan; ``revision_of`` names the plan it revises, which stays as it was."""
    if not (name or "").strip():
        raise ConversionError("give the plan a name")
    if revision_of is not None and pl.get_plan(store, revision_of)["mode"] not in MODE_FOR.values():
        raise ConversionError("only a photo engraving plan can be revised as a photo engraving")
    lens = su.lens_snapshot(su.resolve(store, device_id, lens_id))
    p = preview_continuous(store, device_id, lens_id, mode, image_bytes, width_mm, n_bands, path_ids, allowed_questioned)
    identifier = pl.new_identifier("TCE-P")
    data = {"image_path": _store_image(store, image_bytes), "size_mm": p["size_mm"], "px_mm": p["px_mm"], "transfer": p["transfer"],
            "path_ids": list(path_ids or []), "allowed_questioned": sorted(int(x) for x in (allowed_questioned or [])), "warnings": p["warnings"],
            "layers": p["layers"], "markers": _plan_markers(identifier, markers, p["size_mm"]["width"], p["size_mm"]["height"], store),
            "marker_layer": pl.marker_layer_settings(store) if markers else None, "continuous_mode": mode, "lens": lens,
            "revision_of": revision_of}
    with store.transaction():
        return save_plan(store, None, name=name.strip(), mode=MODE_FOR[mode], status=ST_READY, device_id=device_id, lens_id=lens_id, markers=markers,
                         identifier=identifier, band_count=p["bands"], data=data)


# ======================================================================================================
# Banding picture (REQ-012: the operator sees the banding before export)
# ======================================================================================================
def picture_png(rgb: np.ndarray) -> bytes:
    """An RGB uint8 picture enlarged without smoothing to ``PICTURE_PX`` on its longer side (never reduced), as PNG."""
    h, w = rgb.shape[:2]
    scale = max(1, PICTURE_PX // max(h, w))
    big = cv2.resize(rgb, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
    return cv2.imencode(".png", cv2.cvtColor(big, cv2.COLOR_RGB2BGR))[1].tobytes()


def band_picture(band_map: np.ndarray, labs: list) -> np.ndarray:
    """Every pixel in the predicted colour of its band (``labs[i]`` for band i); a band without a colour stays black."""
    lut = np.array([color.lab_to_srgb8(lab) if lab is not None else (0, 0, 0) for lab in labs], np.uint8)
    return lut[band_map]


def _hatched(rgb: np.ndarray, mask: np.ndarray) -> None:
    """Red diagonal stripes over the masked pixels: a colour the plan cannot engrave yet."""
    yy, xx = np.indices(mask.shape)
    stripe = mask & (((xx + yy) // 3) % 2 == 0)
    rgb[stripe] = (211, 47, 47)


def plan_banding(store: Store, plan: dict) -> np.ndarray:
    """The banding picture of a stored plan as RGB: a continuous plan's bands in their predicted colours, recomputed from
    its stored image; a discrete plan's source colours in their matched titanium colours (unreachable ones hatched red,
    excluded ones white)."""
    if plan["mode"] in MODE_FOR.values():
        rgb, _ = raster(decode_image_bytes(Path(plan["image_path"]).read_bytes()), plan["size_mm"]["width"])
        by_band = {l["band"]: l["prediction"]["lab"] for l in plan["layers"]}
        return band_picture(quantize_luminance(rgb, plan["band_count"]), [by_band.get(i) for i in range(plan["band_count"])])
    if plan["mode"] == pl.MODE_DISCRETE:
        labels = np.load(plan["labels_path"])
        palette = {e["id"]: e for e in eligible_palette(store, plan["device_id"], plan["lens_id"], allowed_questioned=plan["allowed_questioned"])}
        planned = {k: l["prediction"]["lab"] for l in plan.get("layers", []) for k in l.get("source_color_keys", [])}
        out = np.full(labels.shape + (3,), 255, np.uint8)
        for i, m in enumerate(plan["matches"]):
            mask = labels == i
            lab = planned.get(m["source_key"]) or (palette[m["knowledge_id"]]["lab"] if m["knowledge_id"] in palette else None)
            if m["status"] in ("matched", "replaced") and lab is not None:
                out[mask] = color.lab_to_srgb8(lab)
            elif m["status"] == "unreachable":
                out[mask] = color.lab_to_srgb8(m["source_lab"])
                _hatched(out, mask)
        return out
    raise ConversionError("this plan has no banding picture: it is not a discrete or photo engraving")
