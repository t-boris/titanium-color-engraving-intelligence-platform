"""The titanium colours of a vector work and how its source colours get them (REQ-034, DEC-073, DEC-074, DEC-075).

The palette of a vector work is every measured colour of the colour map (REQ-029) of its laser and lens on titanium of the
work's material, whatever the plate: the same family and grade (REQ-057, DEC-088 of vector-detail-and-colour-control, which
widens the work's own stock of DEC-073). It has one entry per recipe: the mean of its independent engravings (a re-photograph counts once, DEC-021), how it was measured
(against a reference chart, against the clean titanium of its photograph, or as photographed), how many independent
engravings and photographs gave it, its complete settings with the LightBurn mode, its engraving task and its estimated
engraving time per square centimetre. It is the exception of DEC-073 to the validated/production rule of REQ-004: a
measured colour that was never repeated is in it, and says so through its counts. Its stability, confidence and expected
colour error (REQ-002) come from the spread of its independent engravings as :func:`model.summarize` computes them for a
knowledge entry (the rig's re-photograph term is not part of them); with one engraving they are not assessed.

The regions of a vector work are areas, so only recipes that fill an area are colours of the palette. A Line-mode recipe
traces a path, the grey steps of an image layer belong to their picture and a recipe kept apart as text or line
(DEC-071) was measured for another task; colours of checks not accepted yet are left out because their masks may still
change. What was left out is counted, by reason, in ``left_out``.

A source colour (index, Lab, pixel count) is given a palette entry by one of three modes (DEC-074; DEC-089 of
vector-detail-and-colour-control, REQ-058, makes them give as many different entries as the palette has, so a work has as many
layers as it has colours, up to 29, and fewer only when the palette has fewer):

* ``closest``: each source colour its own entry, the one-to-one assignment with the least pixel-weighted cost, where a delta E
  within the tolerance costs the tolerance and then the faster entry is cheaper: a colour no other wants takes the fastest entry
  within the tolerance, else the nearest (DEC-075). With more colours than entries every entry is used once and the other colours
  take their nearest;
* ``tonality``: the lightness order of the source colours is kept. Source colours sorted by L* get entries whose L* rises (a
  source colour its own entry), or, with more colours than entries, never falls and every entry is used by a run of neighbouring
  colours; chosen by dynamic programming to minimise the pixel-weighted delta E; among equal totals the faster;
* ``random``: entries drawn with a seeded generator, deterministic per seed; a new seed gives another variant. Each
  source colour gets its own entry while the palette has enough of them.

The entries of the operator's kept choices are not offered to the other colours while others remain. The modes ``fewer_layers``
(DEC-074) and ``most_colours`` (DEC-087) are gone: more layers is what every mode does now.

``keep`` holds the operator's own choices (source colour index -> entry id); every mode keeps them. Colours measured as
photographed (no chart, no clean titanium in their photograph) take part in the automatic modes only when asked
(``include_as_shot``, DEC-057, DEC-077); the operator may still keep one by hand. The work's cleaning layer comes first,
so a work holds at most 29 colours (DEC-073); with registration markers the vector job allows 28.
"""
from __future__ import annotations

import hashlib
import math
import random
import re

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import color, colormap, model, setup as su, tasks
from .conversion import FILL_MODES, LINE_MODES
from .db import Store

MAX_COLOURS = 29                  # LightBurn's 30 output layers less the cleaning layer, which always comes first (DEC-073)
MODES = ("closest", "tonality", "random")


def _basis(point: dict) -> str:
    """How a colour was measured, as the colour map keys it: against a reference chart, against the clean titanium of its
    photograph, or as photographed."""
    if point["measurement"] == "calibrated":
        return "chart"
    return "clean" if point["referenced"] else "as-shot"


def _evidence(means: list, lab: list[float]) -> dict:
    """Stability, confidence and expected colour error of the mean colours of independent engravings (REQ-002), as
    :func:`model.summarize` gives them; not assessed with one engraving."""
    n = len(means)
    if n < 2:
        return {"stability": {"assessed": False, "variance": None, "max_deviation": None, "engravings": n},
                "confidence": None, "expected_delta_e": None}
    variance = float(np.var(np.asarray(means), axis=0, ddof=1).sum())
    return {"stability": {"assessed": True, "variance": variance, "max_deviation": max(color.delta_e(m, lab) for m in means),
                          "engravings": n},
            "confidence": n / (n + model.CONFIDENCE_K), "expected_delta_e": math.sqrt(variance)}


def _entry(group: str, recipe: dict) -> dict:
    """One palette entry: the mean colour of a recipe's independent engravings and everything the screen shows about it."""
    first = recipe["points"][0]
    means = [np.mean(np.asarray(labs, float), axis=0) for labs in recipe["engravings"].values()]
    lab = [float(v) for v in np.mean(means, axis=0)]
    return {"id": hashlib.sha256(group.encode("utf-8")).hexdigest()[:12], "lab": lab, "srgb": color.lab_to_srgb8(lab).tolist(),
            **_evidence(means, lab), "basis": _basis(first), "measurement": first["measurement"], "approximate": first["approximate"],
            "referenced": first["referenced"], "engravings": len(recipe["engravings"]), "photographs": len(recipe["photographs"]),
            "experiments": recipe["experiments"], "observation_ids": sorted(recipe["observation_ids"]),
            "parameters": first["parameters"], "mode": first["parameters"].get("layer_type"), "task": first["task"],
            "time": first["time"], "time_s_per_cm2": first["time_s_per_cm2"], "missing_context": colormap.missing_context(recipe["points"])}


def _left_out(point: dict) -> str | None:
    """Why a colour of the partition is not a colour of an area, or None when it is."""
    mode = point["parameters"].get("layer_type")
    if point["provisional"]:
        return "provisional"
    if mode in LINE_MODES:
        return "line"
    if point.get("source") == "tonal" or mode == "Image":
        return "image"
    if mode not in FILL_MODES:
        return "other_mode"
    if point["task"]["kind"] not in tasks.AREA_TASKS:
        return "task"
    return None


PLATE = re.compile(r"\|ti:[^|]*\|")          # the titanium record inside the group key of a recipe (colormap._group)


def _same_material(store: Store, material_id: int) -> set[int]:
    """The titanium records that are the work's material: the same family and the same grade, whatever their names, sizes,
    thicknesses, batches or surfaces (DEC-088). Case and spacing do not matter; a record with no grade is only itself."""
    def norm(value) -> str:
        return " ".join((value or "").split()).casefold()
    rows = store.query("SELECT id, family, grade FROM material_profile")
    own = next(r for r in rows if r["id"] == material_id)
    if not norm(own["grade"]):
        return {material_id}
    return {r["id"] for r in rows if norm(r["family"]) == norm(own["family"]) and norm(r["grade"]) == norm(own["grade"])}


def _across_plates(points: list[dict], material_id: int) -> list[dict]:
    """Plates of one material are no difference (DEC-088): a recipe measured on several of them is one recipe, whose colour is the
    mean of all its independent engravings. Its points share one group, the one it has on the work's own plate when it was
    measured there, else the first by name, so that an entry keeps the id it had when only the work's own plate was used."""
    own, groups = f"|ti:{material_id}|", {}
    for point in points:
        groups.setdefault(PLATE.sub("|ti:*|", point["group"]), set()).add(point["group"])
    pick = {key: min(found, key=lambda g: (own not in g, g)) for key, found in groups.items()}
    return [{**point, "group": pick[PLATE.sub("|ti:*|", point["group"])]} for point in points]


def vector_palette(store: Store, device_id: int, lens_id: int | None, material_id: int, max_time_s_per_cm2: float | None = None) -> dict:
    """Every measured colour of one laser and lens on titanium of the work's material (the same family and grade, see
    :func:`_same_material`) that fills an area, one entry per recipe, lightest first (``material_id`` is the work's own record: it
    must exist and its recipes keep their ids, see :func:`_across_plates`); with ``max_time_s_per_cm2`` only recipes no slower than
    that per square centimetre. ``left_out`` counts the recipes of the partition that are not in it, by reason. A colour measured
    without a titanium record is in no palette."""
    su.resolve(store, device_id, lens_id)
    if store.one("SELECT id FROM material_profile WHERE id=?", (material_id,)) is None:
        raise su.ValidationError("the selected titanium stock was not found; choose it again")
    limit = colormap.time_limit(max_time_s_per_cm2)
    left_out: dict[str, set] = {reason: set() for reason in ("line", "image", "other_mode", "task", "provisional", "slower")}
    area = []
    plates = _same_material(store, material_id)
    on_plates = [p for p in colormap.collect(store, setup=su.setup_key(device_id, lens_id))["points"] if p["material_id"] in plates]
    for point in _across_plates(on_plates, material_id):
        reason = _left_out(point)
        if reason is None:
            area.append(point)
        else:
            left_out[reason].add(point["group"])
    entries = []
    for group, recipe in colormap.by_recipe(area).items():
        entry = _entry(group, recipe)
        if limit is not None and (entry["time_s_per_cm2"] is None or entry["time_s_per_cm2"] > limit):
            left_out["slower"].add(group)
        else:
            entries.append(entry)
    entries.sort(key=lambda e: (-e["lab"][0], e["id"]))
    return {"device_id": device_id, "lens_id": lens_id, "material_id": material_id, "max_time_s_per_cm2": limit,
            "max_colours": MAX_COLOURS, "entries": entries, "left_out": {reason: len(groups) for reason, groups in left_out.items()}}


# -- assignment ------------------------------------------------------------------------------------------------------------------
def _source(item) -> dict:
    """A source colour as (index, Lab, pixel count), given as a mapping or a sequence of three."""
    try:
        index, lab, pixels = (item["index"], item["lab"], item.get("pixels", 0)) if isinstance(item, dict) else item
        index, lab, pixels = int(index), [float(v) for v in lab], float(pixels)
    except (KeyError, TypeError, ValueError):
        index, lab, pixels = None, None, math.nan
    if index is None or not color.valid_lab(lab) or not math.isfinite(pixels) or pixels < 0:
        raise su.ValidationError("each source colour needs its index, a Lab colour and a pixel count")
    return {"index": index, "lab": lab, "pixels": pixels}


def _time(entry: dict) -> float:
    """The time per square centimetre of an entry for ordering: an unknown time counts as the slowest."""
    return math.inf if entry.get("time_s_per_cm2") is None else entry["time_s_per_cm2"]


def _kept(keep: dict | None, indexes: set[int], by_id: dict) -> dict[int, str]:
    """The operator's choices by source colour index (a JSON object's keys arrive as text), each of a given colour and an
    entry of the palette."""
    out = {}
    for index, entry_id in (keep or {}).items():
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = None
        if index not in indexes:
            raise su.ValidationError("a kept choice names a source colour that is not given")
        if entry_id not in by_id:
            raise su.ValidationError("a kept choice names a colour that is not in the palette of this laser, lens and titanium stock")
        out[index] = entry_id
    return out


def _pool(kept: dict[int, str], candidates: list[dict]) -> list[dict]:
    """The entries the free colours choose from: the ones the operator kept are theirs while others remain (DEC-087, DEC-089)."""
    taken = set(kept.values())
    return [e for e in candidates if e["id"] not in taken] or candidates


def _closest(free: list[dict], kept: dict[int, str], candidates: list[dict], distance, tolerance: float) -> dict[int, tuple[dict, str]]:
    """Each colour its own entry as far as the palette reaches (DEC-089): the one-to-one assignment of the least pixel-weighted cost.
    A delta E within the tolerance costs the tolerance, and then the faster entry is cheaper, so a colour that has no rival takes
    the fastest entry within the tolerance, else the nearest (DEC-075). With more colours than entries every entry is used once
    and the other colours take their nearest."""
    pool, order = _pool(kept, candidates), sorted(free, key=lambda s: s["index"])
    slowest = max((_time(e) for e in pool if math.isfinite(_time(e))), default=1.0) or 1.0
    unit = [min(_time(e) / slowest, 1.0) for e in pool]                      # an unknown time counts as the slowest
    cost = np.array([[max(s["pixels"], 1.0) * (max(distance(s, e), tolerance) + 1e-6 * u + 1e-9 * distance(s, e))
                      for e, u in zip(pool, unit)] for s in order])
    n, m = len(order), len(pool)
    if n <= m:
        picks = dict(zip(*linear_sum_assignment(cost)))
    else:                                                                    # one column per colour for the entries beyond the first use
        extra = np.repeat(cost.min(axis=1, keepdims=True) + float(cost.max()) * n + 1.0, n, axis=1)
        picks = {r: c if c < m else int(cost[r].argmin()) for r, c in zip(*linear_sum_assignment(np.hstack([cost, extra])))}
    return {order[r]["index"]: (pool[c], "fastest_within_tolerance" if distance(order[r], pool[c]) <= tolerance else "nearest")
            for r, c in picks.items()}


def _monotone(sources: list[dict], options: list[dict], allowed, distance, strict: bool = False) -> list[int] | None:
    """Dynamic programming over sources sorted by L* and options sorted by L*: the option index of each source such that the
    indexes never decrease (``strict``: always rise, so no two sources share an option), with the least pixel-weighted delta E and,
    among equal totals, the least pixel-weighted time. None when ``allowed`` leaves no such assignment."""
    n, m = len(sources), len(options)

    def rank(cell):                                                        # totals equal within rounding are a tie
        return round(cell[0], 9), cell[1]

    best: list[list[tuple | None]] = [[None] * m for _ in range(n)]       # (delta E total, time total, previous option)
    for i, s in enumerate(sources):
        weight = max(s["pixels"], 1.0)
        run = None                                                         # the best cell of the previous row up to option j
        for j, option in enumerate(options):
            before = j - 1 if strict else j
            if i and before >= 0 and best[i - 1][before] is not None and (run is None or rank(best[i - 1][before]) < rank(run)):
                run = (*best[i - 1][before][:2], before)
            if not allowed(s, option) or (i and run is None):
                continue
            base = run if i else (0.0, 0.0, None)
            best[i][j] = (base[0] + weight * distance(s, option), base[1] + weight * _time(option), base[2])
    last = [j for j in range(m) if best[n - 1][j] is not None]
    if not last:
        return None
    j = min(last, key=lambda k: rank(best[n - 1][k]))
    out = []
    for i in range(n - 1, -1, -1):
        out.append(j)
        j = best[i][j][2]
    return out[::-1]


def _tonality(sources: list[dict], kept: dict[int, str], by_id: dict, candidates: list[dict], distance) -> tuple[dict, bool]:
    """Keep the lightness order of the source colours, each colour its own entry as far as the palette reaches (DEC-089). Kept
    choices stay where the operator put them; when they themselves break the order, the order is kept among the other colours
    only (the second value is then False)."""
    if not kept:
        return _spread(sources, kept, candidates, distance), True
    taken = set(kept.values())
    options = sorted({e["id"]: e for e in candidates + [by_id[i] for i in kept.values()]}.values(),
                     key=lambda e: (e["lab"][0], _time(e), e["id"]))
    usable = {e["id"] for e in candidates} - taken or {e["id"] for e in candidates}

    def allowed(s, option):
        return option["id"] == kept[s["index"]] if s["index"] in kept else option["id"] in usable

    def place(order):
        return _monotone(order, options, allowed, distance, strict=True) or _monotone(order, options, allowed, distance)

    order = sorted(sources, key=lambda s: (s["lab"][0], s["index"]))
    chosen, kept_order = place(order), True
    if chosen is None:
        order, kept_order = [s for s in order if s["index"] not in kept], False
        chosen = place(order) if order else []
    return {s["index"]: (options[j], "tonality") for s, j in zip(order, chosen) if s["index"] not in kept}, kept_order


def _random(free: list[dict], kept: dict[int, str], candidates: list[dict], seed: int) -> dict[int, tuple[dict, str]]:
    """Entries drawn with a generator seeded by ``seed``: the same seed gives the same variant. Each colour gets its own
    entry while there are enough of them, else every entry is used."""
    rng = random.Random(seed)
    pool = sorted(_pool(kept, candidates), key=lambda e: e["id"])
    order = sorted(free, key=lambda s: s["index"])
    if len(pool) >= len(order):
        picks = rng.sample(pool, len(order))
    else:
        picks = rng.sample(pool, len(pool)) + [rng.choice(pool) for _ in order[len(pool):]]
        rng.shuffle(picks)
    return {s["index"]: (e, "random") for s, e in zip(order, picks)}


def _spread(free: list[dict], kept: dict[int, str], candidates: list[dict], distance) -> dict[int, tuple[dict, str]]:
    """Different entries for different source colours as far as the palette reaches, keeping the lightness order: the free source
    colours sorted by L* take entries sorted by L*, each source its own entry (the order strictly rises) when there are not more
    sources than entries, else every entry takes a run of neighbouring sources. The least pixel-weighted delta E, then the least
    pixel-weighted time."""
    order = sorted(free, key=lambda s: (s["lab"][0], s["index"]))
    options = sorted(_pool(kept, candidates), key=lambda e: (e["lab"][0], _time(e), e["id"]))
    n, m = len(order), len(options)

    def cell(i: int, j: int) -> tuple[float, float]:
        weight = max(order[i]["pixels"], 1.0)
        return weight * distance(order[i], options[j]), weight * _time(options[j])

    def total(before, i: int, j: int, came: int | None):
        step = cell(i, j)
        return (step[0] + (before[0] if before else 0.0), step[1] + (before[1] if before else 0.0), came)

    best: list[list[tuple | None]] = [[None] * m for _ in range(n)]       # (delta E total, time total, option of the source before)
    if n <= m:
        for i in range(n):
            run = None                                                     # the best total of the previous row below option j
            for j in range(m):
                if i == 0:
                    best[0][j] = total(None, 0, j, None)
                    continue
                if j and best[i - 1][j - 1] is not None and (run is None or best[i - 1][j - 1][:2] < run[:2]):
                    run = (*best[i - 1][j - 1][:2], j - 1)
                if run is not None:
                    best[i][j] = total(run, i, j, run[2])
        j = min((k for k in range(m) if best[n - 1][k] is not None), key=lambda k: best[n - 1][k][:2])
    else:
        best[0][0] = total(None, 0, 0, None)
        for i in range(1, n):
            for k in range(min(i, m - 1) + 1):
                ways = [(best[i - 1][p], p) for p in (k, k - 1) if p >= 0 and best[i - 1][p] is not None]
                if ways:
                    before, p = min(ways, key=lambda w: w[0][:2])
                    best[i][k] = total(before, i, k, p)
        j = m - 1
    picks = []
    for i in range(n - 1, -1, -1):
        picks.append(j)
        j = best[i][j][2]
    return {s["index"]: (options[k], "tonality") for s, k in zip(order, reversed(picks))}


def automatic(entry: dict, limit: float | None, include_as_shot: bool) -> bool:
    """Whether the automatic modes may choose an entry: no slower than ``limit`` seconds per square centimetre (an unknown
    time is slower than any limit) and, unless included, not measured as photographed (DEC-077)."""
    if limit is not None and (entry.get("time_s_per_cm2") is None or entry["time_s_per_cm2"] > limit):
        return False
    return include_as_shot or entry.get("basis") != "as-shot"


def assign(source_colours, palette: list[dict], mode: str, *, tolerance_de: float, seed: int = 0, max_time: float | None = None,
           keep: dict | None = None, include_as_shot: bool = False) -> dict:
    """Give each source colour an entry of ``palette`` by ``mode`` (see the module). ``max_time`` leaves slower entries (and
    those with no time per area) out of the automatic choice, and so do colours measured as photographed unless
    ``include_as_shot``; ``keep`` holds the operator's choices, which every mode keeps.
    Each colour lists its entry, its delta E to the source, whether that is within the tolerance and the entry's time per
    square centimetre; the totals give the number of distinct recipes and the pixel-weighted mean delta E."""
    if mode not in MODES:
        raise su.ValidationError("the recolouring mode must be closest, tonality or random")
    sources = [_source(item) for item in source_colours or []]
    if not sources:
        raise su.ValidationError("give the source colours to recolour")
    if len(sources) > MAX_COLOURS:
        raise su.ValidationError(f"at most {MAX_COLOURS} colours: the cleaning layer comes first and LightBurn has 30 layers")
    if len({s["index"] for s in sources}) != len(sources):
        raise su.ValidationError("two source colours have the same index")
    tolerance = colormap.delta_tolerance(tolerance_de)
    limit = colormap.time_limit(max_time)
    by_id = {e["id"]: e for e in palette}
    if not by_id:
        raise su.ValidationError("no measured colour of this laser, lens and titanium stock fills an area")
    kept = _kept(keep, {s["index"] for s in sources}, by_id)
    candidates = [e for e in by_id.values() if automatic(e, limit, include_as_shot)]
    free = [s for s in sources if s["index"] not in kept]
    if free and not candidates:
        if limit is not None and any(automatic(e, None, include_as_shot) for e in by_id.values()):
            raise su.ValidationError(f"no colour of the palette engraves within {limit:g} s per square centimetre")
        raise su.ValidationError("every colour of the palette was measured as photographed: include such colours to colour automatically")
    cache: dict[tuple[int, str], float] = {}

    def distance(s, e):
        key = (s["index"], e["id"])
        if key not in cache:
            cache[key] = color.delta_e(s["lab"], e["lab"])
        return cache[key]

    order_kept = None
    if mode == "closest":
        chosen = _closest(free, kept, candidates, distance, tolerance) if free else {}
    elif mode == "tonality":
        chosen, order_kept = _tonality(sources, kept, by_id, candidates, distance) if free else ({}, True)
    else:
        chosen = _random(free, kept, candidates, seed) if free else {}
    chosen.update({index: (by_id[entry_id], "kept") for index, entry_id in kept.items()})

    colours, distances = [], []
    for s in sorted(sources, key=lambda s: s["index"]):
        entry, how = chosen[s["index"]]
        distances.append(distance(s, entry))
        colours.append({"index": s["index"], "lab": s["lab"], "pixels": s["pixels"], "entry_id": entry["id"], "entry_lab": entry["lab"],
                        "srgb": entry.get("srgb"), "delta_e": round(distances[-1], 2), "within_tolerance": distances[-1] <= tolerance,
                        "time_s_per_cm2": entry.get("time_s_per_cm2"), "how": how})
    weights = np.array([c["pixels"] for c in colours], float)
    if weights.sum() <= 0:
        weights = np.ones(len(colours))
    times = [c["time_s_per_cm2"] for c in colours]
    totals = {"recipes": len({c["entry_id"] for c in colours}), "colours": len(colours),
              "within_tolerance": sum(c["within_tolerance"] for c in colours),
              "mean_delta_e": round(float(np.average(distances, weights=weights)), 2),
              "mean_time_s_per_cm2": None if None in times else float(np.average(times, weights=weights))}
    out = {"mode": mode, "tolerance_de": tolerance, "max_time_s_per_cm2": limit, "include_as_shot": include_as_shot,
           "keep": {str(k): v for k, v in kept.items()}, "colours": colours, "totals": totals}
    if mode == "random":
        out["seed"] = seed
    if mode == "tonality":
        out["lightness_order"] = "kept" if order_kept else "broken_by_kept_choices"
    return out


def tolerance_for(store: Store, device_id: int, lens_id: int | None, value) -> float:
    """The delta E tolerance of an assignment: the one given, else the saved rule of the laser and lens; never invented."""
    if value is None:
        value = su.get_rules(store, device_id, lens_id)["delta_tolerance"]
    if value is None:
        raise su.ValidationError("set the delta E tolerance: none is saved for this laser and lens")
    return colormap.delta_tolerance(value)


def assign_for(store: Store, device_id: int, lens_id: int | None, material_id: int, source_colours, mode: str, *,
               tolerance_de=None, seed: int = 0, max_time: float | None = None, keep: dict | None = None,
               include_as_shot: bool = False) -> dict:
    """An assignment against the palette of one laser, lens and titanium stock (see :func:`assign`)."""
    palette = vector_palette(store, device_id, lens_id, material_id)
    return assign(source_colours, palette["entries"], mode, tolerance_de=tolerance_for(store, device_id, lens_id, tolerance_de),
                  seed=seed, max_time=max_time, keep=keep, include_as_shot=include_as_shot)
