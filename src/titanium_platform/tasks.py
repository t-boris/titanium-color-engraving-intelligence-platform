"""Engraving tasks (REQ-020): what a job, a layer or a measured record was meant to do, and what can be measured about it.

One table holds the vocabulary. A task kind is a key of ``TASKS``; a new kind is a new row and never changes the meaning of a
record that names an existing one (REQ-020 AC8).

Every layer has a task. It is *explicit* when the operator stated it (on the upload or the review of a photograph, or when
making the plan or plate the layer belongs to) and *derived* otherwise: from the layer's LightBurn mode (a Line layer is a
line, a Fill / Offset Fill layer a filled region, an Image layer a tonal image), or from its role (the cleaning layer
cleans). An observation stores the task it was accepted with (``task_kind`` and ``evidence.task``); one accepted before
tasks existed has none and reads as derived from its layer settings.

Results of unlike tasks are never one summary (REQ-020 AC5), and existing records keep their meaning: a knowledge key gains
the task only when the task is explicit and differs from the one its LightBurn mode implies (``key_suffix``). So a filled
text and a filled area of the same Fill recipe stay apart, while every record without a stated task, or with the task its
mode implies anyway, keeps exactly the key it had (the approach of DEC-051).

A photograph measures some qualities and not others. ``quality_metrics`` reports each measured value with its method and
its basis (chart-corrected, against the clean titanium of the same photograph, as photographed, or the photo scale from the
registration with its uncertainty), and names what the task needs but a photograph cannot give, with the reason, instead of
inferring it from the settings.
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import setup as su

EXPLICIT, DERIVED = "explicit", "derived"
LAYER_DEFAULT = "layer"            # the operator's choice for a layer: the task its LightBurn mode implies, over the work's
WITNESS = "pre-test cleaning witness"
TONAL_DITHER = "grayscale"
TRACE_SAMPLING_MM = 0.025          # the step of the profile across a line in ingest._line_metrics

# key: name, what it is for, the metrics a photograph measures for it, the metrics it needs that a photograph cannot give,
# the application-guide goal that serves it, the goals a plan of it may record and the LightBurn layer modes that imply it
# when nobody stated a task (a mode no row names, or none recorded, is read as a fill)
TASKS: dict[str, dict] = {
    "text": {"name": "Text", "objective": "legible letters and digits of a chosen size",
             "metrics": ("lab", "lightness", "contrast", "line_continuity", "line_visibility", "apparent_trace_width"),
             "unavailable": ("text_legibility", "line_width_um", "dimensional_accuracy"), "guide_goal": "text",
             "goals": ("text_height_mm", "line_width_mm", "legibility_note")},
    "line": {"name": "Vector lines", "objective": "a continuous stroke and separable neighbouring lines",
             "metrics": ("lab", "lightness", "contrast", "line_continuity", "line_visibility", "apparent_trace_width"),
             "unavailable": ("line_width_um", "dimensional_accuracy"), "guide_goal": "line", "goals": ("line_width_mm",),
             "lightburn_modes": ("Cut",)},
    "fill": {"name": "Filled vector regions", "objective": "an even area of one colour",
             "metrics": ("lab", "lightness", "chroma"), "unavailable": ("dimensional_accuracy",), "guide_goal": "color",
             "goals": ("target_lab",), "lightburn_modes": ("Scan", "Fill", "OffsetFill", "Offset Fill", "Scan+Cut")},
    "tonal_image": {"name": "Tonal image", "objective": "grey levels of a picture as lightness on titanium",
                    "metrics": ("lab", "lightness", "tonal_profile"), "unavailable": (), "guide_goal": "image",
                    "goals": ("tonal_note",), "lightburn_modes": ("Image",)},
    "color_image": {"name": "Colour image", "objective": "the colours of a picture as oxide colours",
                    "metrics": ("lab", "lightness", "chroma"), "unavailable": (), "guide_goal": "color", "goals": ("target_lab",)},
    "mark": {"name": "Black or light marking", "objective": "a dark or light contrasting mark of repeatable look",
             "metrics": ("lab", "lightness", "contrast"), "unavailable": ("dimensional_accuracy",), "guide_goal": "black_mark",
             "goals": ("target_lab",)},
    "cleaning": {"name": "Cleaning", "objective": "a clean surface without an unwanted trace",
                 "metrics": ("lab", "lightness"), "unavailable": (), "guide_goal": "cleaning", "goals": ()},
    "deep": {"name": "Deep engraving", "objective": "depth in millimetres and the walls after engraving and cleaning cycles",
             "metrics": ("lab",), "unavailable": ("depth",), "guide_goal": "deep", "goals": ()},
    "relief": {"name": "3D relief", "objective": "a layered relief, its geometry and texture",
               "metrics": ("lab",), "unavailable": ("relief_height",), "guide_goal": "relief_3d", "goals": ()},
    "cutting": {"name": "Cutting", "objective": "a cut through the part, its kerf and edge",
                "metrics": (), "unavailable": ("cut_through", "kerf_width"), "guide_goal": "cutting", "goals": ()},
}
# a goal of the application guide asks for this task (the guide's own vocabulary predates the task table)
GOAL_TASK = {"text": "text", "line": "line", "black_mark": "mark", "white_mark": "mark", "color": "fill", "cleaning": "cleaning",
             "image": "tonal_image", "deep": "deep", "relief_3d": "relief", "cutting": "cutting"}
# a capability plate tests one task, or mixes them layer by layer (None)
TEST_TYPE_TASK = {"small_patches": "fill", "calibration": "fill", "hatch_interval": "fill", "offset_fill": "fill", "wobble": "fill",
                  "text_readability": "text", "power_speed": "line", "frequency": "line", "pulse_cutoff": "line",
                  "line_resolution": "line", "compact_capability": None, "material_matrix": None}
MATRIX_GEOMETRY_TASK = {"line": "line", "fill": "fill", "text": "text", "vector_text": "text"}
# the main task of a vector job by its tracing strategy, and the task of a traced region by its own (vectorize.TASKS): a colour,
# fill or tonal region is a filled area judged by its colour or lightness
VECTOR_STRATEGY_TASK = {"color": "color_image", "fill": "fill", "text": "text", "line": "line"}
VECTOR_REGION_TASK = {"color": "fill", "fill": "fill", "tonal": "fill", "text": "text", "line": "line"}
CONVERSION_TASK = {"discrete": "color_image", "tonal": "tonal_image", "color_path": "color_image"}
# recipes an area conversion may fill with: measured as areas, never as text or lines
AREA_TASKS = frozenset({"fill", "color_image", "tonal_image", "mark"})

# What a photograph cannot measure, and why; reported as unavailable, never inferred from the settings.
UNAVAILABLE = {
    "line_width_um": {"note": "line width in micrometres needs a calibrated image scale or an independent measurement; "
                              "the apparent trace width is only the visible mark at the scale of the registration"},
    "text_legibility": {"note": "text legibility is not measured from a photograph: it needs a reading test of the engraved characters"},
    "dimensional_accuracy": {"note": "dimensional accuracy needs a calibrated image scale or an independent measurement: "
                                     "the registration fits the file geometry to the photograph"},
    "depth": {"note": "depth needs a physical measurement such as a depth gauge or a profilometer; a surface photograph does not show it"},
    "relief_height": {"note": "relief height needs a height map or profilometry; a surface photograph does not show it"},
    "cut_through": {"note": "a cut through the part needs a physical check of the part; a surface photograph does not show it"},
    "kerf_width": {"note": "kerf width needs a calibrated image scale or an independent measurement"},
}
METRICS = ("lab", "lightness", "chroma", "tonal_profile", "contrast", "line_continuity", "line_visibility", "apparent_trace_width")
BASES = ("chart", "clean", "as_shot", "registration_scale")
METHODS = ("layer_mask_median", "grey_to_lightness_bins", "line_profile_peak", "line_profile_stations", "line_profile_threshold",
           "clean_witness_difference")


def vocabulary() -> list[dict]:
    """The task table as data, with the LightBurn modes each task is derived from."""
    return [{"key": key, "name": t["name"], "objective": t["objective"], "metrics": list(t["metrics"]),
             "unavailable": [{"metric": m, **UNAVAILABLE[m]} for m in t["unavailable"]], "guide_goal": t["guide_goal"],
             "goals": list(t["goals"]), "lightburn_modes": list(t.get("lightburn_modes", ()))} for key, t in TASKS.items()]


def _mode_task(layer_type: str | None) -> str:
    return next((key for key, t in TASKS.items() if layer_type in t.get("lightburn_modes", ())), "fill")


def require(kind) -> str:
    if kind not in TASKS:
        raise su.ValidationError(f"unknown engraving task: {kind}")
    return kind


def optional(kind) -> str | None:
    """A task chosen in a form: empty means none chosen (the layer's own task applies)."""
    return None if kind in (None, "") else require(kind)


def _value(settings: dict | None, tag: str):
    value = (settings or {}).get(tag)
    return value.get("Value") if isinstance(value, dict) else value


def derive(layer_type: str | None, source_settings: dict | None = None, role: str | None = None) -> dict:
    """The task a layer implies by itself: its role (the cleaning layer cleans) or its LightBurn mode. An Image layer is a
    tonal image whatever its image mode; a mode other than grayscale is named. A layer whose mode was not recorded (rows of
    the first versions) was a fill, as conversions have always read it."""
    task = {"kind": _mode_task(layer_type), "basis": DERIVED, "source": "layer", "mode": layer_type}
    if role == WITNESS:
        task.update(kind="cleaning", source="role")
    elif task["kind"] == "tonal_image":
        mode = _value(source_settings, "ditherMode")
        if mode is not None and mode != TONAL_DITHER:
            task["image_mode"] = mode
    return task


def derive_from_parameters(parameters: dict, role: str | None = None) -> dict:
    return derive(parameters.get("layer_type"), parameters.get("source_settings"), role)


def explicit(kind: str, source: str) -> dict:
    return {"kind": require(kind), "basis": EXPLICIT, "source": source}


def key_suffix(task: dict | None, parameters: dict) -> str:
    """What a task adds to a recipe key: nothing, unless it was stated and differs from what the LightBurn mode implies."""
    if not task or task.get("basis") != EXPLICIT:
        return ""
    return "" if task["kind"] == derive_from_parameters(parameters)["kind"] else f"|task:{task['kind']}"


def _row_value(row, key: str):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def of_observation(row) -> dict:
    """The task of an observation row: the one it was accepted with, else derived from its layer (REQ-020 AC8)."""
    evidence = json.loads(_row_value(row, "evidence_json") or "{}")
    kind, stored = _row_value(row, "task_kind"), evidence.get("task")
    if kind is not None and kind in TASKS and isinstance(stored, dict):
        return {**stored, "kind": kind}
    return derive_from_parameters(json.loads(_row_value(row, "parameters_json") or "{}"), evidence.get("role"))


def effective(layer_type: str | None, source_settings: dict | None, role: str | None, *, operator: str | None = None,
              work: str | None = None, plan: str | None = None) -> dict:
    """The task of one layer of a photographed job, by precedence: the operator's choice for this layer, the task the operator
    gave the whole work, the task of the plan or plate layer it was made from, else the layer's own (derived). Service layers
    (cleaning, registration and labels) keep their own task."""
    derived = derive(layer_type, source_settings, role)
    if role not in (None, "test feature") or operator == LAYER_DEFAULT:
        return derived
    for kind, source in ((operator, "operator"), (work, "work"), (plan, "plan")):
        if kind in TASKS:
            return {**explicit(kind, source), "mode": layer_type, "derived": derived["kind"]}
    return derived


# -- plans ---------------------------------------------------------------------------------------------------------------------
def clean_goals(kind: str, goals: dict | None) -> dict:
    """The goals a plan of ``kind`` may record (REQ-020 AC1): a target colour, a tonal behaviour, a line width, a text height
    and legibility notes, and a free note for any task. Values that do not apply to the task are dropped."""
    goals = dict(goals or {})
    allowed = set(TASKS[require(kind)]["goals"]) | {"note"}
    out: dict = {}
    for key in allowed:
        value = goals.get(key)
        if value in (None, "", []):
            continue
        if key == "target_lab":
            try:
                lab = [float(v) for v in value]
            except (TypeError, ValueError):
                raise su.ValidationError("the target colour must be three numbers L, a, b") from None
            if len(lab) != 3 or not all(math.isfinite(v) for v in lab) or not 0 <= lab[0] <= 100:
                raise su.ValidationError("the target colour must be three numbers L, a, b")
            out[key] = lab
        elif key in ("line_width_mm", "text_height_mm"):
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = math.nan
            if not math.isfinite(number) or number <= 0:
                raise su.ValidationError("the line width and the text height must be positive numbers of millimetres")
            out[key] = number
        else:
            text = str(value).strip()
            if len(text) > 500:
                raise su.ValidationError("a task note must not exceed 500 characters")
            out[key] = text
    return out


def plan_task(kind: str, goals: dict | None = None, basis: str = EXPLICIT) -> dict:
    """The task a plan records: its kind, its goals and whether the operator chose it or it followed from the plan's mode."""
    return {"kind": require(kind), "goals": clean_goals(kind, goals), "basis": basis}


def chosen_or_default(kind: str | None, default: str, goals: dict | None = None) -> dict:
    """The task of a new plan: the operator's choice, else the default of its mode (recorded as derived)."""
    return plan_task(kind, goals) if kind not in (None, "") else plan_task(default, goals, DERIVED)


def plate_layer_task(name: str | None, cut_type: str | None) -> str:
    """The task of one layer of a system plate: its letters are text (filled or single-line), every other layer is what its
    LightBurn mode implies."""
    if (name or "").upper().startswith("TEXT"):
        return "text"
    return derive(cut_type)["kind"]


def plate_task(test_type: str | None, research_goal: str | None = None, matrix_geometry: str | None = None) -> str:
    """The main task of a capability plate: the goal it was made for, else what its test type examines."""
    if research_goal in GOAL_TASK:
        return GOAL_TASK[research_goal]
    if test_type == "material_matrix" and matrix_geometry in MATRIX_GEOMETRY_TASK:
        return MATRIX_GEOMETRY_TASK[matrix_geometry]
    return TEST_TYPE_TASK.get(test_type) or "line"


def layer_task_of_regions(region_kinds: list[str]) -> str | None:
    """The task of an output layer of a vector job: the task its regions share, None when it mixes tasks (it is then
    measured as its LightBurn mode implies, and the mixture is named)."""
    kinds = {VECTOR_REGION_TASK.get(kind, kind) for kind in region_kinds}
    return kinds.pop() if len(kinds) == 1 else None


PLATE_MODES = ("Calibration plate", "Laser capability test")


def plan_layer_task(plan: dict | None, name: str | None, index: int | None) -> str | None:
    """The task a plan states for the layer of this name (else this index): the layer's own when the plan gave it one (a
    plate's cells, a vector job's output layers), else the plan's when the operator chose it. None: the plan states none, and
    the layer keeps the task of its LightBurn mode."""
    if not plan:
        return None
    layers = plan.get("layers") or []
    layer = next((l for l in layers if name and l.get("name") == name), None) or \
        next((l for l in layers if index is not None and l.get("index") == index), None)
    if layer is not None and "task" in layer:
        return layer["task"]            # None: a mixed layer of a vector job keeps its own task
    if plan.get("mode") in PLATE_MODES:
        return None                     # a plate states its tasks per cell; its cleaning and markers are its own
    task = plan.get("engraving_task") or {}
    return task.get("kind") if task.get("basis") == EXPLICIT else None


# -- metrics -------------------------------------------------------------------------------------------------------------------
def photo_scale(alignment: dict | None) -> dict | None:
    """The scale of a registered photograph: pixels per millimetre at the work and its uncertainty in millimetres (the
    registration residual at that scale, else the sampling step of a line profile)."""
    h = (alignment or {}).get("image_to_mm")
    if not h:
        return None
    try:
        mm_to_image = np.linalg.inv(np.asarray(h, float))
    except np.linalg.LinAlgError:
        return None
    px_per_mm = float(np.sqrt(abs(np.linalg.det(mm_to_image[:2, :2] / mm_to_image[2, 2]))))
    if not math.isfinite(px_per_mm) or px_per_mm <= 0:
        return None
    residual = alignment.get("residual_px")
    uncertainty = residual / px_per_mm if isinstance(residual, (int, float)) and math.isfinite(residual) else None
    return {"px_per_mm": round(px_per_mm, 3), "residual_px": residual,
            "uncertainty_mm": round(max(uncertainty or 0.0, TRACE_SAMPLING_MM), 4), "sampling_mm": TRACE_SAMPLING_MM}


def _colour_basis(mode: str | None, against_clean) -> str:
    if mode == "reference_chart_corrected":
        return "chart"
    return "clean" if against_clean is not None else "as_shot"


def quality_metrics(kind: str | None, *, lab=None, against_clean=None, mode: str | None = None, line_metrics: dict | None = None,
                    tonal: dict | None = None, clean_lab=None, scale: dict | None = None) -> list[dict]:
    """The quality metrics of one measured layer for its task, each with its method and basis, followed by the metrics the
    task needs that a photograph cannot give (``available`` false, with the reason)."""
    task = TASKS.get(kind or "fill", TASKS["fill"])
    wanted = task["metrics"]
    out: list[dict] = []
    colour_basis = _colour_basis(mode, against_clean)
    shown = against_clean if colour_basis == "clean" else lab
    photo_basis = "chart" if mode == "reference_chart_corrected" else "as_shot"

    def add(metric, value, unit, method, basis, **extra):
        if metric in wanted and value is not None:
            out.append({"metric": metric, "value": value, "unit": unit, "method": method, "basis": basis, "available": True, **extra})

    if shown is not None:
        shown = [round(float(v), 2) for v in shown]
        add("lab", shown, "Lab", "layer_mask_median", colour_basis)
        add("lightness", shown[0], "L*", "layer_mask_median", colour_basis)
        add("chroma", round(math.hypot(shown[1], shown[2]), 2), "C*", "layer_mask_median", colour_basis)
    if tonal and tonal.get("bins"):
        add("tonal_profile", {"rho": tonal.get("rho"), "range_L": tonal.get("range_L"), "bins": len(tonal["bins"]),
                              "evidence": tonal.get("evidence")}, "L* by grey", "grey_to_lightness_bins", colour_basis)
    if line_metrics:
        add("contrast", line_metrics.get("median_contrast_Lstar"), "ΔL*", "line_profile_peak", photo_basis)
        add("line_continuity", line_metrics.get("median_continuity_percent"), "%", "line_profile_stations", photo_basis)
        add("line_visibility", [line_metrics.get("visible_line_count"), line_metrics.get("line_count")], "lines",
            "line_profile_stations", photo_basis)
        width = line_metrics.get("median_apparent_trace_width_mm")
        if scale is not None:
            add("apparent_trace_width", width, "mm", "line_profile_threshold", "registration_scale", scale=scale)
    elif lab is not None and clean_lab is not None:
        add("contrast", round(abs(float(lab[0]) - float(clean_lab[0])), 2), "ΔL*", "clean_witness_difference", photo_basis)
    out += [{"metric": metric, "available": False, **UNAVAILABLE[metric]} for metric in task["unavailable"]]
    return out
