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

The colour of an entry is the colour its independent engravings agree on and its confidence says how far they do (REQ-045,
DEC-083, :mod:`agreement`): repeats that agree raise it, engravings that differ lower it, and an older colour is replaced by a later
redo. ``caution`` marks an entry the automatic modes must not choose: ``contradicted`` (its colour changes under the same settings,
no strict majority of its engravings agrees) or ``superseded`` (the same settings were measured on a better basis: against a chart
rather than against the clean titanium of the photograph, and that rather than as photographed). A cautioned entry stays in the
palette, so that a saved work keeps its id and the operator may still choose it by hand; only when no other entry is left the
automatic modes use the cautioned ones (:func:`choosable`, ``cautioned`` in the result), so a work can always be coloured. Among
entries inside the tolerance the more confident one is chosen before the faster one.

The regions of a vector work are areas, so only recipes that fill an area are colours of the palette. A Line-mode recipe
traces a path, the grey steps of an image layer belong to their picture and a recipe kept apart as text or line
(DEC-071) was measured for another task; colours of checks not accepted yet are left out because their masks may still
change. What was left out is counted, by reason, in ``left_out``.

A source colour (index, Lab, pixel count) is given a palette entry by one of three modes (DEC-074; DEC-089 of
vector-detail-and-colour-control, REQ-058, makes them give as many different entries as the palette has, so a work has as many
layers as it has colours, up to 29, and fewer only when the palette has fewer):

* ``closest``: each source colour its own entry, the one-to-one assignment with the least pixel-weighted cost, where a delta E
  within the tolerance costs the tolerance and then the more confident entry is cheaper, and among equally confident ones the faster:
  a colour no other wants takes the most confident, then fastest, entry within the tolerance, else the nearest (DEC-083, DEC-075). With more colours than entries every entry is used once and the other colours
  take their nearest;
* ``tonality``: the lightness order of the source colours is kept. Source colours sorted by L* get entries whose L* rises (a
  source colour its own entry), or, with more colours than entries, never falls and every entry is used by a run of neighbouring
  colours; chosen by dynamic programming to minimise the pixel-weighted delta E; among equal totals the faster;
* ``random``: entries drawn with a seeded generator, deterministic per seed; a new seed gives another variant. Each
  source colour gets its own entry while the palette has enough of them;
* ``contrast`` (vector-detail-and-colour-control I-6, its DEC-091): neighbours told apart. It starts from ``closest`` and then swaps the entries of
  two colours, or gives a colour an entry no colour uses, while that raises the mean delta E between the titanium colours of
  neighbouring source colours, weighted by the length of their shared border (``borders``), less twice the pixel-weighted mean delta E
  to the source colours (``CONTRAST_FIDELITY``); deterministic, each colour its own entry as in ``closest``;
* ``artistic`` (I-6, DEC-079 and DEC-092 of vector-detail-and-colour-control): the hues arranged anew for every seed within a chosen group of the
  palette (``subset``: all, warm, cool or bright colours), the lightness order of the source colours kept as ``tonality`` keeps it.
  Every source colour is given a target hue drawn by the seed from the hues of the group; among the entries in lightness order it takes
  the one nearest its own L* and the target hue (``ARTISTIC_HUE`` L* units per degree).

The entries of the operator's kept choices are not offered to the other colours while others remain. The modes ``fewer_layers``
(DEC-074) and ``most_colours`` (DEC-087) are gone: more layers is what every mode does now.

``keep`` holds the operator's own choices (source colour index -> entry id); every mode keeps them. Colours measured as
photographed (no chart, no clean titanium in their photograph) take part in the automatic modes only when asked
(``include_as_shot``, DEC-057, DEC-077); the operator may still keep one by hand. The work's cleaning layer comes first,
so a work holds at most 29 colours (DEC-073); with registration markers the vector job allows 28.

The colour of a recipe depends on the size of what is engraved (DEC-107): on the length of its scan rows. An entry keeps the sizes its
engravings were made at (``sizes``: each with the colour the engravings of that size agree on) and :func:`at_size` gives its colour in rows
of a given length: measured there, between two measured sizes, the nearest one outside them (never extrapolated), saying which. The
entry's own colour is the one all its engravings agree on, whatever their size; a vector work shows each layer at the length of its own
rows and chooses for each source colour the entries by the colour they give in rows as long as that colour's regions (``size_of``).
"""
from __future__ import annotations

import hashlib
import math
import random
import re

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import agreement, color, colormap, colouring, model, prediction, setup as su, tasks
from .conversion import FILL_MODES, LINE_MODES
from .db import Store

ALGORITHM = "2"                   # default LightBurn path metadata no longer separates equivalent measurements
MAX_COLOURS = 29                  # LightBurn's 30 output layers less the cleaning layer, which always comes first (DEC-073)
MODES = ("closest", "tonality", "random", "contrast", "artistic")
SUBSETS = ("all", "warm", "cool", "bright")   # the groups of the palette Artistic draws from
CONTRAST_FIDELITY = 2.0           # what a delta E to the source colour costs Contrast against a delta E between neighbours: a move must
                                  # part neighbours twice as much as it strays (on spread palettes neighbours twice as apart, the source error doubled)
ARTISTIC_HUE = 0.2                # the L* units Artistic counts for each degree of hue between an entry and its target hue


def _basis(point: dict) -> str:
    """How a colour was measured, as the colour map keys it: against a reference chart, against the clean titanium of its
    photograph, or as photographed."""
    if point["measurement"] == "calibrated":
        return "chart"
    return "clean" if point["referenced"] else "as-shot"


def _evidence(found: dict) -> dict:
    """Stability, confidence and expected colour error of the independent engravings of a recipe (REQ-002), as
    :func:`model.summarize` gives them; the spread is over all engravings, so a disagreement shows; the confidence is the one of
    the agreed colour (:mod:`agreement`). Not assessed with one engraving."""
    means, n = found["means"], len(found["means"])
    if n < 2:
        return {"stability": {"assessed": False, "variance": None, "max_deviation": None, "engravings": n},
                "confidence": None, "expected_delta_e": None}
    variance = float(np.var(np.asarray(means), axis=0, ddof=1).sum())
    return {"stability": {"assessed": True, "variance": variance, "max_deviation": max(color.delta_e(m, found["lab"]) for m in means),
                          "engravings": n},
            "confidence": found["confidence"], "expected_delta_e": math.sqrt(variance)}


def entry_id(group: str) -> str:
    """The id of the palette entry of the recipe ``group``: the same while the recipe is measured (DEC-088)."""
    return hashlib.sha256(group.encode("utf-8")).hexdigest()[:12]


def _entry(group: str, recipe: dict) -> dict:
    """One palette entry: the mean colour of a recipe's independent engravings and everything the screen shows about it."""
    first = recipe["points"][0]
    found = colormap.agreed(recipe)
    lab = found["lab"]
    return {"id": entry_id(group), "lab": lab, "srgb": color.lab_to_srgb8(lab).tolist(),
            **_evidence(found), "agreement": agreement.shown(found), "caution": "contradicted" if found["contradicted"] else None,
            "basis": _basis(first), "measurement": first["measurement"], "approximate": first["approximate"],
            "referenced": first["referenced"], "engravings": len(recipe["engravings"]), "photographs": len(recipe["photographs"]),
            "experiments": recipe["experiments"], "observation_ids": sorted(recipe["observation_ids"]),
            "parameters": first["parameters"], "mode": first["parameters"].get("layer_type"), "task": first["task"],
            "fill_together": (first.get("preview_execution") or {}).get("together", True),
            "time": first["time"], "time_s_per_cm2": first["time_s_per_cm2"], "missing_context": colormap.missing_context(recipe["points"]),
            "doubtful": agreement.doubtful(found), "sources": colormap.sources_of(recipe, found), "sizes": _sizes(recipe)}


def _sizes(recipe: dict) -> list[dict]:
    """The sizes a recipe's engravings were made at (DEC-107), smallest first: its engravings grouped by the row length of their layer
    (``prediction.size_groups``), each size with the colour its engravings agree on. An engraving of unknown size is in none."""
    rows: dict = {}
    for point in recipe["points"]:
        if point.get("row_mm") is not None:
            rows.setdefault(point["engraving_id"], point["row_mm"])
    out = []
    for group in prediction.size_groups(recipe["engravings"], rows.get):
        found = colormap.agreed({**recipe, "engravings": {e: recipe["engravings"][e] for e in group["items"]}})
        out.append({"row_mm": group["row_mm"], "engravings": len(group["items"]), "lab": [float(v) for v in found["lab"]]})
    return out


def at_size(entry: dict, row_mm: float | None) -> dict:
    """The colour of a palette entry engraved in rows ``row_mm`` long (DEC-107), placed among the sizes its engravings were made at by
    ``prediction.place``: the colour of the size measured there, interpolated in the logarithm of the length between two, the nearest
    size's outside them (never extrapolated); the entry's own colour when none of its sizes is known or no length is given. ``size`` says
    which: the length, how, the measured sizes and the ones used."""
    sizes = entry.get("sizes") or []
    measured = [s["row_mm"] for s in sizes]
    where = prediction.place(measured, row_mm)
    if where["how"] == prediction.UNKNOWN:
        lab = list(entry["lab"])
    elif where["how"] == prediction.BETWEEN:
        a, b = (sizes[i]["lab"] for i in where["use"])
        lab = [(1 - where["t"]) * x + where["t"] * y for x, y in zip(a, b)]
    else:
        lab = list(sizes[where["use"][0]]["lab"])
    return {"lab": lab, "srgb": color.lab_to_srgb8(lab).tolist(),
            "size": {"row_mm": None if row_mm is None else round(float(row_mm), 1), "how": where["how"], "measured_mm": measured,
                     "from_mm": [measured[i] for i in where["use"]]}}


def left_out_reason(point: dict) -> str | None:
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


PLATE = colormap.PLATE          # the titanium record inside the group key of a recipe


BASIS = re.compile(r"\|(?:chart|clean|as-shot)(\|(?:provisional|accepted)\|task:[^|]*)$")   # how a colour was measured, in the group key
BASIS_RANK = {"chart": 2, "clean": 1, "as-shot": 0}                                      # a better basis replaces a worse one (DEC-083)


def _settings_of(group: str) -> str:
    """The settings of a recipe whatever the plate and the way its colour was measured: what the same engraving would be again."""
    return BASIS.sub(r"|*\1", PLATE.sub("|ti:*|", group))


def _supersede(built: list[tuple[str, dict]]) -> None:
    """Mark the entries whose settings were measured on a better basis too (``caution`` = ``superseded``, DEC-083): the better
    measurement replaces them in the automatic choice."""
    best: dict[str, dict] = {}
    for group, entry in built:
        key = entry.get("physical_key") or _settings_of(group)
        previous = best.get(key)
        rank = lambda e: (BASIS_RANK[e["basis"]], e.get("equivalent_id", e["id"]) == e["id"])
        if previous is None or rank(entry) > rank(previous):
            best[key] = entry
    for group, entry in built:
        chosen = best[entry.get("physical_key") or _settings_of(group)]
        if BASIS_RANK[entry["basis"]] < BASIS_RANK[chosen["basis"]]:
            entry["caution"] = "superseded"
            entry["replacement_id"] = chosen["id"]


def _across_plates(points: list[dict], material_id: int) -> list[dict]:
    """Plates of one material are no difference (DEC-088): a recipe measured on several of them is one recipe, whose colour is the
    mean of all its independent engravings. Its points share one group, the one it has on the work's own plate when it was
    measured there, else the first by name, so that an entry keeps the id it had when only the work's own plate was used."""
    own, groups = f"|ti:{material_id}|", {}
    for point in points:
        groups.setdefault(PLATE.sub("|ti:*|", point["group"]), set()).add(point["group"])
    pick = {key: min(found, key=lambda g: (own not in g, g)) for key, found in groups.items()}
    return [{**point, "original_group": point["group"], "group": pick[PLATE.sub("|ti:*|", point["group"])]} for point in points]


def pooled_ids(points: list[dict], material_id: int) -> dict[str, str]:
    """The id of the palette entry each recipe of the colour map's ``points`` (one plate each, on titanium of the work's material) is
    pooled into across the plates (:func:`_across_plates`), by the point's own group."""
    return {point["group"]: entry_id(pooled["group"]) for point, pooled in zip(points, _across_plates(points, material_id))}


def _compatible_recipes(points: list[dict]) -> list[tuple[str, dict, str]]:
    """Share the colour evidence of equivalent area fills, keeping every existing palette id and the task records.

    Saving a generated file in LightBurn 2.2 adds fgPathAlgorithm=CutGantry. The old, omitted default and the explicit default must
    learn from one another. Calibration fills and the same fills in colour pictures also measure the same physical operation; the
    knowledge summaries keep their tasks, while the preview uses their colour evidence. The best available measurement basis wins.
    All other controls, unknown tags, layer types and titanium partitions stay in the key; text and lines were already excluded.
    Unlike changing model.parameters_key, this leaves saved colour choices, histories and published recipes addressable.
    """
    normalized, groups = [], {}
    for point in points:
        old = point["recipe"].split("|layer|", 1)[0]
        execution = point.get("preview_execution") or {}
        new = execution.get("key", old)
        key = point["recipe"].replace(old + "|", new + "|", 1)
        key = re.sub(r"\|task:[^|]+$", "|task:area", key)
        normalized.append({**point, "recipe": key})
        groups.setdefault(key, {})[point["group"]] = execution.get("default_path", False)
    recipes = colormap.by_recipe(normalized)
    out = []
    for key, names in groups.items():
        primary = min(names, key=lambda name: (names[name], name))
        recipe = recipes[key]
        rank = max(BASIS_RANK[_basis(p)] for p in recipe["points"])
        best = [p for p in recipe["points"] if BASIS_RANK[_basis(p)] == rank]
        recipe = colormap.by_recipe(best)[key]
        for group in names:
            # Keep the original group's settings first: exporting an old id repeats its own recipe.
            own = [p for p in recipe["points"] if p["group"] == group]
            others = [p for p in recipe["points"] if p["group"] != group]
            aliases = sorted({entry_id(p.get("original_group", p["group"])) for p in recipes[key]["points"]})
            out.append((group, {**recipe, "points": own + others, "aliases": aliases, "physical_key": BASIS.sub(r"|*\1", key)}, entry_id(primary)))
    return out


def vector_palette(store: Store, device_id: int, lens_id: int | None, material_id: int, max_time_s_per_cm2: float | None = None,
                   points: list[dict] | None = None) -> dict:
    """Every measured colour of one laser and lens on titanium of the work's material (the same family and grade, see
    :func:`setup.same_titanium`) that fills an area, one entry per recipe, lightest first (``material_id`` is the work's own record: it
    must exist and its recipes keep their ids, see :func:`_across_plates`); with ``max_time_s_per_cm2`` only recipes no slower than
    that per square centimetre. ``left_out`` counts the recipes of the partition that are not in it, by reason. A colour measured
    without a titanium record is in no palette. ``points`` are the colour map's points of this laser and lens when the caller has
    gathered them already (``colormap.collect`` of the laser and lens, unfiltered)."""
    su.resolve(store, device_id, lens_id)
    if store.one("SELECT id FROM material_profile WHERE id=?", (material_id,)) is None:
        raise su.ValidationError("the selected titanium stock was not found; choose it again")
    limit = colormap.time_limit(max_time_s_per_cm2)
    left_out: dict[str, set] = {reason: set() for reason in ("line", "image", "other_mode", "task", "provisional", "slower")}
    area = []
    plates = set(su.same_titanium(store, material_id))
    if points is None:
        points = colormap.collect(store, setup=su.setup_key(device_id, lens_id))["points"]
    on_plates = [p for p in points if p["material_id"] in plates]
    for point in _across_plates(on_plates, material_id):
        reason = left_out_reason(point)
        if reason is None:
            area.append(point)
        else:
            left_out[reason].add(point["group"])
    built = [(group, {**_entry(group, recipe), "equivalent_id": primary, "aliases": recipe["aliases"], "physical_key": recipe["physical_key"]})
             for group, recipe, primary in _compatible_recipes(area)]
    _supersede(built)
    entries = []
    for group, entry in built:
        if limit is not None and (entry["time_s_per_cm2"] is None or entry["time_s_per_cm2"] > limit):
            left_out["slower"].add(group)
        else:
            entries.append(entry)
    entries.sort(key=lambda e: (-e["lab"][0], e["id"]))
    return {"device_id": device_id, "lens_id": lens_id, "material_id": material_id, "max_time_s_per_cm2": limit,
            "max_colours": MAX_COLOURS, "entries": entries, "left_out": {reason: len(groups) for reason, groups in left_out.items()},
            "cautions": {reason: sum(e["caution"] == reason for e in entries) for reason in ("contradicted", "superseded")}}


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
    the more confident entry within the tolerance, then the faster (DEC-083, DEC-075), else the nearest. With more colours than
    entries every entry is used once and the other colours take their nearest."""
    pool, order = _pool(kept, candidates), sorted(free, key=lambda s: s["index"])
    slowest = max((_time(e) for e in pool if math.isfinite(_time(e))), default=1.0) or 1.0
    unit = [min(_time(e) / slowest, 1.0) for e in pool]                      # an unknown time counts as the slowest
    doubt = [1.0 - agreement.trust(e) for e in pool]                         # 0 = sure; a colour engraved once is 2/3, a contradicted one more
    cost = np.array([[max(s["pixels"], 1.0) * (max(distance(s, e), tolerance) + 1e-3 * d + 1e-6 * u + 1e-9 * distance(s, e))
                      for e, u, d in zip(pool, unit, doubt)] for s in order])
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


def _contrast(sources: list[dict], kept: dict[int, str], by_id: dict, candidates: list[dict], distance, tolerance: float, colour_of,
              borders) -> dict[int, tuple[dict, str]]:
    """Closest first, then better told apart from its neighbours (see the module): a pass over the free colours in index order gives a colour
    the unused entry (while there are no more colours than entries) or swaps it with another colour's entry, whichever raises the score
    most, and passes repeat until none does. The score is the border-weighted mean delta E between neighbouring colours (each as it is
    engraved at its own size, ``colour_of``) less ``CONTRAST_FIDELITY`` times the pixel-weighted mean delta E to the sources."""
    free = sorted((s for s in sources if s["index"] not in kept), key=lambda s: s["index"])
    start = _closest(free, kept, candidates, distance, tolerance)
    pool = _pool(kept, candidates)
    at, known = {s["index"] for s in free}, {s["index"] for s in sources}
    weight: dict[tuple[int, int], float] = {}
    for a, b, share in borders or ():
        if a != b and a in known and b in known and (a in at or b in at):
            weight[(a, b)] = weight[(b, a)] = weight.get((a, b), 0.0) + float(share)
    if not weight or not free:
        return {i: (e, "contrast") for i, (e, _) in start.items()}
    total_w = sum(weight.values()) / 2
    total_p = sum(max(s["pixels"], 1.0) for s in free)
    near = {i: [(j, w) for (x, j), w in weight.items() if x == i] for i in at}
    by_index = {s["index"]: s for s in sources}
    ids = [e["id"] for e in pool]
    lab = {s["index"]: np.array([colour_of(s, e) for e in pool], float) for s in free}
    fixed = {k: np.asarray(colour_of(by_index[k], by_id[e]), float) for k, e in kept.items()}
    fid = {s["index"]: np.array([max(s["pixels"], 1.0) * distance(s, e) for e in pool]) / total_p for s in free}
    cur = {i: ids.index(e["id"]) for i, (e, _) in start.items()}

    def colour(j: int, entry: int | None = None) -> np.ndarray:
        return fixed[j] if j in fixed else lab[j][cur[j] if entry is None else entry]

    def part(i: int, e: int, skip: int | None = None) -> float:
        """What colour ``i`` with entry ``e`` adds to the score, the border with ``skip`` left out."""
        apart = sum(w * float(np.linalg.norm(lab[i][e] - colour(j))) for j, w in near[i] if j != skip)
        return apart / total_w - CONTRAST_FIDELITY * fid[i][e]

    for _ in range(100):                                                   # a bound only: each move raises the score
        moved = False
        for i in at:
            used = set(cur.values())
            best, move = 1e-9, None
            if len(free) <= len(pool):
                here = part(i, cur[i])
                for e in range(len(pool)):
                    gain = part(i, e) - here if e not in used else 0.0
                    if gain > best:
                        best, move = gain, ("give", e)
            for j in at:
                if j == i or cur[j] == cur[i]:
                    continue
                w = weight.get((i, j), 0.0)
                now = part(i, cur[i], j) + part(j, cur[j], i) + w * float(np.linalg.norm(lab[i][cur[i]] - lab[j][cur[j]])) / total_w
                then = part(i, cur[j], j) + part(j, cur[i], i) + w * float(np.linalg.norm(lab[i][cur[j]] - lab[j][cur[i]])) / total_w
                if then - now > best:
                    best, move = then - now, ("swap", j)
            if move is not None:
                if move[0] == "give":
                    cur[i] = move[1]
                else:
                    cur[i], cur[move[1]] = cur[move[1]], cur[i]
                moved = True
        if not moved:
            break
    return {i: (pool[e], "contrast") for i, e in cur.items()}


def _hue(lab) -> tuple[float, float]:
    """The chroma and the hue (degrees) of a Lab colour."""
    return math.hypot(lab[1], lab[2]), math.degrees(math.atan2(lab[2], lab[1])) % 360.0


def subset_of(candidates: list[dict], subset: str) -> list[dict]:
    """The entries of a group of the palette Artistic draws from: all of them; the warm ones (red to yellow) or the cool ones (green-blue to
    violet), coloured enough to have a hue, as the colouring of a photo work names them (:mod:`colouring`); or the bright ones: the
    more chromatic half of the coloured entries."""
    if subset == "all":
        return list(candidates)
    hued = [(e, *_hue(e["lab"])) for e in candidates]
    coloured = [(e, c, h) for e, c, h in hued if c >= colouring.COLOURED]
    if subset == "bright":
        floor = float(np.median([c for _, c, _ in coloured])) if coloured else math.inf
        return [e for e, c, _ in coloured if c >= floor]
    low, high = colouring.WARM_HUE if subset == "warm" else colouring.COOL_HUE
    return [e for e, _, h in coloured if low <= h <= high]


def _artistic(sources: list[dict], kept: dict[int, str], by_id: dict, candidates: list[dict], colour_of, seed: int) -> tuple[dict, bool]:
    """The lightness order kept as in ``tonality`` (DEC-079), each colour drawn to a target hue the seed gives it among the hues of the
    group, so that every seed arranges the hues anew; the second value says whether the order was kept (the kept choices may break it)."""
    rng = random.Random(seed)
    hues = sorted(h for c, h in (_hue(e["lab"]) for e in candidates) if c >= colouring.COLOURED)
    target = {s["index"]: rng.choice(hues) for s in sorted(sources, key=lambda s: s["index"])} if hues else {}

    def cost(s, e) -> float:
        looks = colour_of(s, e)
        chroma, hue = _hue(looks)
        gap = 90.0 if not hues or chroma < colouring.COLOURED else min(abs(hue - target[s["index"]]), 360.0 - abs(hue - target[s["index"]]))
        return abs(s["lab"][0] - looks[0]) + ARTISTIC_HUE * gap

    chosen, order_kept = _tonality(sources, kept, by_id, candidates, cost)
    return {i: (e, "artistic") for i, (e, _) in chosen.items()}, order_kept


def automatic(entry: dict, limit: float | None, include_as_shot: bool) -> bool:
    """Whether the automatic modes may choose an entry: not cautioned (its colour changes under the same settings, or a better
    measurement of them exists, DEC-083), no slower than ``limit`` seconds per square centimetre (an unknown time is slower than
    any limit) and, unless included, not measured as photographed (DEC-077)."""
    if entry.get("caution") or entry.get("equivalent_id", entry["id"]) != entry["id"]:
        return False
    if limit is not None and (entry.get("time_s_per_cm2") is None or entry["time_s_per_cm2"] > limit):
        return False
    return include_as_shot or entry.get("basis") != "as-shot"


def choosable(entries, limit: float | None, include_as_shot: bool) -> tuple[list[dict], bool]:
    """The entries the automatic modes choose from, and whether they are the cautioned ones: when no entry is free of caution (every
    colour of the titanium changed under its settings, or was replaced) the cautioned ones that pass the other limits are used, so that a
    work can still be coloured; the screen marks each of them (DEC-083)."""
    entries = [e for e in entries if e.get("equivalent_id", e["id"]) == e["id"]]
    free = [e for e in entries if automatic(e, limit, include_as_shot)]
    if free:
        return free, False
    cautioned = [e for e in entries if automatic({**e, "caution": None}, limit, include_as_shot)]
    return cautioned, bool(cautioned)


def assign(source_colours, palette: list[dict], mode: str, *, tolerance_de: float, seed: int = 0, max_time: float | None = None,
           keep: dict | None = None, include_as_shot: bool = False, size_of=None, borders=None, subset: str = "all") -> dict:
    """Give each source colour an entry of ``palette`` by ``mode`` (see the module). ``max_time`` leaves slower entries (and
    those with no time per area) out of the automatic choice, and so do colours measured as photographed unless
    ``include_as_shot``; ``keep`` holds the operator's choices, which every mode keeps. ``size_of(index, entry)`` gives the row length
    (mm) a source colour is engraved at with an entry (DEC-107): its distance to the entry is then to the entry's colour at that length
    (:func:`at_size`); without it, to the entry's own colour. ``borders`` (``[a, b, share]`` per pair of source colours that touch, the
    share of the border length) is what ``contrast`` tells apart; ``subset`` the group of the palette ``artistic`` draws from.
    Each colour lists its entry, its delta E to the source, whether that is within the tolerance and the entry's time per
    square centimetre; the totals give the number of distinct recipes and the pixel-weighted mean delta E."""
    if mode not in MODES:
        raise su.ValidationError("the recolouring mode must be closest, tonality, random, contrast or artistic")
    if subset not in SUBSETS:
        raise su.ValidationError("the group of colours must be all, warm, cool or bright")
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
    candidates, cautioned = choosable(by_id.values(), limit, include_as_shot)
    free = [s for s in sources if s["index"] not in kept]
    if free and not candidates:
        if limit is not None and any(automatic(e, None, include_as_shot) for e in by_id.values()):
            raise su.ValidationError(f"no colour of the palette engraves within {limit:g} s per square centimetre")
        raise su.ValidationError("every colour of the palette was measured as photographed: include such colours to colour automatically")
    cache: dict[tuple[int, str], float] = {}
    seen: dict[tuple[int, str], dict] = {}

    def looks(s, e) -> dict:
        """The entry as this source colour would be engraved with it: at the row length of its regions, or as measured."""
        key = (s["index"], e["id"])
        if key not in seen:
            seen[key] = {"lab": e["lab"], "srgb": e.get("srgb"), "size": None} if size_of is None else at_size(e, size_of(s["index"], e))
        return seen[key]

    def distance(s, e):
        key = (s["index"], e["id"])
        if key not in cache:
            cache[key] = color.delta_e(s["lab"], looks(s, e)["lab"])
        return cache[key]

    order_kept = None
    if mode == "artistic" and free:
        candidates = subset_of(candidates, subset)
        if not candidates:
            raise su.ValidationError(f"no measured colour of this palette is {subset}: choose another group of colours")
    if mode == "closest":
        chosen = _closest(free, kept, candidates, distance, tolerance) if free else {}
    elif mode == "tonality":
        chosen, order_kept = _tonality(sources, kept, by_id, candidates, distance) if free else ({}, True)
    elif mode == "contrast":
        chosen = _contrast(sources, kept, by_id, candidates, distance, tolerance, lambda s, e: looks(s, e)["lab"], borders) if free else {}
    elif mode == "artistic":
        chosen, order_kept = _artistic(sources, kept, by_id, candidates, lambda s, e: looks(s, e)["lab"], seed) if free else ({}, True)
    else:
        chosen = _random(free, kept, candidates, seed) if free else {}
    chosen.update({index: (by_id[entry_id], "kept") for index, entry_id in kept.items()})

    colours, distances = [], []
    for s in sorted(sources, key=lambda s: s["index"]):
        entry, how = chosen[s["index"]]
        distances.append(distance(s, entry))
        shown = looks(s, entry)
        colours.append({"index": s["index"], "lab": s["lab"], "pixels": s["pixels"], "entry_id": entry["id"], "entry_lab": shown["lab"],
                        "srgb": shown["srgb"], "delta_e": round(distances[-1], 2), "within_tolerance": distances[-1] <= tolerance,
                        "time_s_per_cm2": entry.get("time_s_per_cm2"), "how": how, **({"size": shown["size"]} if size_of else {})})
    weights = np.array([c["pixels"] for c in colours], float)
    if weights.sum() <= 0:
        weights = np.ones(len(colours))
    times = [c["time_s_per_cm2"] for c in colours]
    totals = {"recipes": len({c["entry_id"] for c in colours}), "colours": len(colours),
              "within_tolerance": sum(c["within_tolerance"] for c in colours),
              "mean_delta_e": round(float(np.average(distances, weights=weights)), 2),
              "mean_time_s_per_cm2": None if None in times else float(np.average(times, weights=weights))}
    out = {"mode": mode, "tolerance_de": tolerance, "max_time_s_per_cm2": limit, "include_as_shot": include_as_shot, "cautioned": cautioned,
           "keep": {str(k): v for k, v in kept.items()}, "colours": colours, "totals": totals}
    if mode in ("random", "artistic"):
        out["seed"] = seed
    if mode == "artistic":
        out["subset"] = subset
    if mode in ("tonality", "artistic"):
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
