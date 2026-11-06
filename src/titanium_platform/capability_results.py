"""Derived, reviewable findings for completed laser-capability plates.

Measurements remain the immutable observations written by ingestion. This module only summarizes the
photo-corrected Lab readings on demand; it does not store guessed process limits or color labels.
"""
from __future__ import annotations

import json

from . import color, capability_plates as cp
from .db import Store, now


def _setting_label(row: dict) -> str:
    p = row["parameters"]
    parts = [row["name"]]
    for key, unit in (("power", "%"), ("frequency", "kHz"), ("speed", "mm/s"), ("pulse_width", "ns")):
        if p.get(key) is not None:
            parts.append(f"{p[key]} {unit}")
    if p.get("line_interval") is not None and p.get("layer_type") != "Cut":
        parts.append(f"interval {p['line_interval']} mm")
    if p.get("passes") is not None:
        parts.append(f"{p['passes']} passes")
    wobble = p.get("source_settings") or {}
    if wobble.get("wobbleEnable", {}).get("Value") == "1":
        step = wobble.get("wobbleStep", {}).get("Value", "?")
        size = wobble.get("wobbleSize", {}).get("Value", "?")
        parts.append(f"Wobble: diameter {size} mm, interval {step} mm")
    elif wobble.get("wobbleEnable", {}).get("Value") == "0":
        parts.append("Wobble: off")
    return " · ".join(parts)


def _use_cases(rows: list[dict]) -> list[dict]:
    """Task-oriented conclusions; a line witness never becomes a proven text/color recipe."""
    lines = [r for r in rows if r["name"].startswith("LINE-P") and r.get("line_metrics")]
    reliable = [r for r in lines if r["line_metrics"].get("visible_line_count", 0) > 0 and
                r["line_metrics"].get("median_continuity_percent", 0) >= 90]
    ranked = sorted(reliable or lines, key=lambda r: (
        r["line_metrics"].get("visible_line_count", 0) > 0,
        r["line_metrics"].get("median_continuity_percent", 0),
        r["line_metrics"].get("median_contrast_Lstar") or 0), reverse=True)
    best = ranked[0] if ranked else None
    thin = min((r for r in reliable if r["line_metrics"].get("median_apparent_trace_width_mm") is not None),
               key=lambda r: (r["line_metrics"]["median_apparent_trace_width_mm"],
                              -(r["line_metrics"].get("median_contrast_Lstar") or 0)), default=None)
    text_seed = thin or best
    params = best["parameters"] if best else None
    complete = bool(params and all(params.get(key) is not None for key in
                                   ("power", "frequency", "speed", "pulse_width", "passes")))
    evidence = ({"layer_index": best["layer_index"], "name": best["name"],
                 "line_metrics": best["line_metrics"]} if best else {})
    label = _setting_label(best) if best else "not found"
    if reliable:
        line_summary = f"On this photo, line “{label}” is a preliminary candidate: continuity {best['line_metrics']['median_continuity_percent']:.0f}%."
        if not complete:
            line_summary += " Q-Pulse or another required setting is missing from the file, so these settings cannot yet be repeated exactly."
    elif best:
        m = best["line_metrics"]
        line_summary = (f"No continuous line is confirmed. Best measured area “{label}”: "
                        f"visible {m.get('visible_line_count', 0)}/{m.get('line_count', 0)}, "
                        f"continuity {m.get('median_continuity_percent', 0):.0f}%; this is not a production-ready recipe.")
    else:
        line_summary = "This photo has no comparable single-line measurements."
    line_next = (f"Check the actual Q-Pulse and repeat “{label}” 2–3 times on a small area; then compare neighboring power and speed values with other settings held constant."
                 if best else "Make a compact power-speed matrix of single lines.")
    return [
        {"purpose": "line", "status": "candidate" if reliable and complete else "incomplete_settings" if reliable else "insufficient",
         "summary": line_summary, "parameters": params if reliable and complete else None,
         "evidence": evidence, "next_test": line_next},
        {"purpose": "text", "status": "needs_text_test",
         "summary": "Character legibility has not been measured. Camera response and single-line visibility do not establish text quality."
                    + (f" For the next fine-stroke test, start with “{_setting_label(text_seed)}”"
                       f" (apparent width {text_seed['line_metrics']['median_apparent_trace_width_mm']:.3f} mm)." if thin else
                       f" For the next test, start with “{label}”." if best else "")
                    + (" Before repeating, determine the actual Q-Pulse; it is absent from the file." if text_seed and
                       text_seed["parameters"].get("pulse_width") is None else ""),
         "parameters": None, "evidence": {"layer_index": text_seed["layer_index"], "name": text_seed["name"],
                                         "parameters": text_seed["parameters"],
                                         "line_metrics": text_seed["line_metrics"]} if text_seed else {},
         "next_test": "Engrave short text at several sizes and stroke widths near the selected line settings; assess recognizable characters and fine-stroke integrity in repeat RAW photos."},
        {"purpose": "color", "status": "needs_color_test",
         "summary": "This plate cannot select the desired color: camera-relative values do not define reproducible titanium color.",
         "parameters": None, "evidence": {},
         "next_test": "Make a separate compact color matrix, photograph RAW with a reference chart, and repeat promising cells."},
        {"purpose": "image", "status": "needs_image_test",
         "summary": "Image settings are not confirmed: this plate does not evaluate halftones, detail, and fill uniformity together.",
         "parameters": None, "evidence": {},
         "next_test": "After selecting lines and color, engrave a small image fragment with fine details, fills, and halftones."},
    ]


def _text_case(rows: list[dict]) -> dict:
    """Rank text coupons by photographed stroke contrast, without claiming legibility."""
    background = next((r["lab"][0] for r in rows if r["role"] == "pre-test cleaning witness"), None)
    scored = []
    if background is not None:
        for row in rows:
            if not row["name"].startswith(("TEXT-P", "TEXT-MATRIX-")):
                continue
            samples = [item for item in row["submeasurements"] if item.get("measured_lab")]
            if len(samples) < 3:
                continue
            contrasts = [abs(float(item["measured_lab"][0]) - background) for item in samples]
            scored.append((min(contrasts), row, contrasts))
    if not scored:
        return {"purpose": "text", "status": "insufficient",
                "summary": "Lettering or the clean background was not measured in the photo, so variants cannot yet be compared.",
                "parameters": None, "evidence": {},
                "next_test": "Retake a RAW photo of the same plate under even lighting and check element alignment."}
    score, best, contrasts = max(scored, key=lambda item: item[0])
    return {"purpose": "text", "status": "contrast_candidate",
            "summary": (f"In this photo, “{_setting_label(best)}” gives the highest minimum contrast across {len(contrasts)} text samples "
                        f"against the cleaned background: ΔL* {score:.1f}. This is a contrast candidate; letter legibility, "
                        "edge sharpness, and repeatability are not yet confirmed."),
            "parameters": None,
            "evidence": {"layer_index": best["layer_index"], "name": best["name"],
                         "parameters": best["parameters"], "contrast_by_size": contrasts,
                         "background_Lstar": background},
            "next_test": "Compare letters on the workpiece and RAW photo at 1:1 for gaps, edges, and repeatability; repeat the best legible option on a new small area."}


def _matrix_line_case(rows: list[dict]) -> dict | None:
    lines = [r for r in rows if r["name"].startswith("MATRIX-") and r.get("line_metrics")]
    if not lines:
        return None
    best = max(lines, key=lambda r: (r["line_metrics"].get("visible_line_count", 0) > 0,
                                     r["line_metrics"].get("median_continuity_percent", 0),
                                     r["line_metrics"].get("median_contrast_Lstar") or 0))
    metrics = best["line_metrics"]
    complete = all(best["parameters"].get(key) is not None for key in
                   ("power", "speed", "frequency", "pulse_width", "passes"))
    visible = metrics.get("visible_line_count", 0) > 0
    continuous = visible and metrics.get("median_continuity_percent", 0) >= 90
    return {"purpose": "line", "status": "candidate" if continuous and complete else "incomplete_settings" if continuous else "insufficient",
            "summary": (f"In the refinement matrix, “{_setting_label(best)}” has the strongest response: "
                        f"continuity {metrics.get('median_continuity_percent', 0):.0f}%. "
                        "This is a photo-based candidate; repeatability and line quality on the workpiece remain unconfirmed."),
            "parameters": best["parameters"] if continuous and complete else None,
            "evidence": {"layer_index": best["layer_index"], "name": best["name"],
                         "parameters": best["parameters"], "line_metrics": metrics},
            "next_test": "Repeat the selected line settings on a new small area and compare edges, contrast, and continuity."}


FINDING_FIELDS = ("status", "summary", "parameters_json", "evidence_json", "next_test")


def save_findings(store: Store, pair_id: int) -> None:
    """Keep reviewable, purpose-specific findings next to immutable observations.

    A finding recalculated to another text keeps the version it replaces in ``capability_finding_history`` with the time it
    was in force (REQ-022): a later version never erases what an earlier one said. An unchanged finding is left as it is."""
    report = report_for_pair(store, pair_id)
    if report is None:
        return
    with store.transaction():
        for item in report["use_cases"]:
            values = (item["status"], item["summary"], json.dumps(item["parameters"]) if item["parameters"] else None,
                      json.dumps(item["evidence"]), item["next_test"])
            old = store.one("SELECT * FROM capability_finding WHERE pair_id=? AND purpose=?", (pair_id, item["purpose"]))
            if old is None:
                store.execute("INSERT INTO capability_finding(pair_id,purpose,status,summary,parameters_json,evidence_json,next_test,created_at) "
                              "VALUES (?,?,?,?,?,?,?,?)", (pair_id, item["purpose"], *values, now()))
            elif tuple(old[k] for k in FINDING_FIELDS) != values:
                store.execute("INSERT INTO capability_finding_history(finding_id,status,summary,parameters_json,evidence_json,next_test,"
                              "valid_from,replaced_at) VALUES (?,?,?,?,?,?,?,?)",
                              (old["id"], *(old[k] for k in FINDING_FIELDS), old["updated_at"] or old["created_at"], now()))
                store.execute("UPDATE capability_finding SET status=?,summary=?,parameters_json=?,evidence_json=?,next_test=?,updated_at=? "
                              "WHERE id=?", (*values, now(), old["id"]))


def finding_history(store: Store, finding_id: int) -> list[dict]:
    """The earlier versions of one capability finding, newest first, each with the time it was in force."""
    return [dict(r, parameters=json.loads(r["parameters_json"]) if r["parameters_json"] else None, evidence=json.loads(r["evidence_json"]))
            for r in store.query("SELECT * FROM capability_finding_history WHERE finding_id=? ORDER BY id DESC", (finding_id,))]


def backfill_findings(store: Store) -> None:
    """Recompute derived findings from accepted observations when the app starts."""
    rows = store.query(
        "SELECT p.id FROM pair p JOIN plate t ON t.id=p.plate_id "
        "WHERE p.status='Accepted' AND t.test_type='compact_capability'")
    for row in rows:
        save_findings(store, row["id"])


def findings_for_device(store: Store, device_id: int, purpose: str | None = None) -> list[dict]:
    if purpose is not None and purpose not in {"line", "text", "color", "image"}:
        raise ValueError("unknown engraving purpose")
    rows = store.query(
        "SELECT f.*,p.device_id,p.material_id,p.lens_id,p.engraving_id,p.accepted_at,p.hardware_json,p.context_json "
        "FROM capability_finding f JOIN pair p ON p.id=f.pair_id "
        "WHERE p.status='Accepted' AND p.device_id=? "
        "AND p.id=(SELECT MAX(p2.id) FROM pair p2 WHERE p2.engraving_id=p.engraving_id AND p2.status='Accepted') "
        + ("AND f.purpose=? " if purpose else "") + "ORDER BY p.accepted_at DESC,f.id DESC",
        (device_id, purpose) if purpose else (device_id,))
    return [dict(r, parameters=json.loads(r["parameters_json"]) if r["parameters_json"] else None,
                 evidence=json.loads(r["evidence_json"]), hardware=json.loads(r["hardware_json"] or "{}"),
                 context=json.loads(r["context_json"] or "{}")) for r in rows]


def _compact_interpretation(rows: list[dict]) -> tuple[list[str], list[str]]:
    """Separate what this one photograph measured from the checks needed before choosing a recipe."""
    signals: list[str] = []
    next_steps: list[str] = []
    line_rows = [r for r in rows if r["name"].startswith("LINE-P") and r["line_metrics"]]
    if line_rows:
        strong = [r for r in line_rows if r["line_metrics"].get("visible_line_count", 0) > 0
                  and r["line_metrics"].get("median_continuity_percent", 0) >= 90]
        if strong:
            examples = ", ".join(f"{r['parameters']['power']:g}% / {r['parameters']['speed']:g} mm/s" for r in strong)
            signals.append(f"Most continuous lines in this photo: {examples}. These are candidates for retesting, not production-ready engraving settings.")
        by_speed: dict[float, list[dict]] = {}
        for row in line_rows:
            by_speed.setdefault(row["parameters"]["speed"], []).append(row)
        contradictory = [speed for speed, group in by_speed.items()
                         if any(low["parameters"]["power"] < high["parameters"]["power"]
                                and low["line_metrics"].get("visible_line_count", 0) > 0
                                and high["line_metrics"].get("visible_line_count", 0) == 0
                                for low in group for high in group)]
        if contradictory:
            signals.append("The matrix has non-monotonic power results at speed "
                           + ", ".join(f"{speed:g}" for speed in sorted(contradictory))
                           + " mm/s. One photo does not establish a laser capability threshold.")
            next_steps.append("Retake a RAW photo of the same plate with light from another direction and compare the disputed lines in detail. No new titanium is needed.")
    gap = next((r["line_metrics"] for r in rows if r["name"].startswith("LINE-GAP-") and r["line_metrics"]), None)
    if gap and gap.get("groups"):
        full = [g for g in gap["groups"] if g["visible_line_count"] == g["line_count"]]
        partial = [g for g in gap["groups"] if 0 < g["visible_line_count"] < g["line_count"]]
        if full:
            first = min(full, key=lambda g: g["spacing_um"])
            previous = max((g for g in partial if g["spacing_um"] < first["spacing_um"]),
                           key=lambda g: g["spacing_um"], default=None)
            lead = (f"At {first['spacing_um']} µm the algorithm sees {first['visible_line_count']}/{first['line_count']} lines"
                    + (f", at {previous['spacing_um']} µm: {previous['visible_line_count']}/{previous['line_count']}" if previous else ""))
            signals.append(lead + ". This range needs refinement; separation between adjacent tracks has not been measured.")
            if previous:
                next_steps.append(f"Focus the next compact gap test between {previous['spacing_um']} and {first['spacing_um']} µm and measure contrast between adjacent lines.")
    wobble = [r for r in rows if r["name"].startswith("WOBBLE-")]
    if len(wobble) >= 2:
        low, high = min(wobble, key=lambda r: r["lab"][0]), max(wobble, key=lambda r: r["lab"][0])
        signals.append(f"Among Wobble areas, relative L* ranges from {low['lab'][0]:.1f} to {high['lab'][0]:.1f}; mark geometry and repeatability have not been measured.")
    hatches = [r for r in rows if r["name"].startswith("HATCH-")]
    if len(hatches) >= 2:
        hatches.sort(key=lambda r: r["parameters"].get("line_interval") or 0)
        signals.append("At fill intervals " + ", ".join(f"{r['parameters']['line_interval']:g} mm: L* {r['lab'][0]:.1f}" for r in hatches)
                       + ". Average lightness does not establish uniformity or the desired color.")
    frequencies = [r for r in rows if r["name"].startswith("FREQUENCY-") and r["line_metrics"]]
    if len(frequencies) >= 2:
        continuities = [r["line_metrics"].get("median_continuity_percent", 0) for r in frequencies]
        visible = sum(r["line_metrics"].get("visible_line_count", 0) > 0 for r in frequencies)
        strongest = max(frequencies, key=lambda r: (r["line_metrics"].get("visible_line_count", 0),
                                                     r["line_metrics"].get("median_continuity_percent", 0)))
        signals.append(f"Of {len(frequencies)} frequency lines in the photo, {visible} are clearly visible; "
                       f"continuity {min(continuities):.0f}–{max(continuities):.0f}%. "
                       f"The strongest response is at {strongest['parameters']['frequency']:g} kHz "
                       f"({strongest['line_metrics'].get('median_continuity_percent', 0):.0f}% continuity), "
                       "but these are not yet text settings.")
        if strongest["line_metrics"].get("median_continuity_percent", 0) < 90:
            next_steps.append("Do not fix a frequency for text yet: repeat the best frequency candidates on short fine lines and letters with power, speed, and Q-Pulse unchanged.")
    if line_rows:
        next_steps.append("After reviewing the photo, repeat selected line settings 2–3 times on a small plate. Record Q-Pulse and all Wobble settings explicitly; also compare width and background contrast.")
    return signals, next_steps


def report_for_pair(store: Store, pair_id: int) -> dict | None:
    """Return a conservative response summary for an accepted capability-test pair, if applicable."""
    pair = store.one("SELECT * FROM pair WHERE id=?", (pair_id,))
    if pair is None or pair["status"] != "Accepted":
        return None
    plate_id = pair["plate_id"]
    plate = store.one("SELECT * FROM plate WHERE id=?", (plate_id,)) if plate_id else None
    if plate is None and pair["plan_id"]:
        plate = store.one("SELECT t.* FROM plate t JOIN plan p ON p.plate_id=t.id WHERE p.id=?", (pair["plan_id"],))
    if plate is None or plate["test_type"] not in cp.TYPE_BY_ID:
        return None

    obs = store.query("SELECT layer_index,lab_json,parameters_json,evidence_json FROM observation WHERE pair_id=? ORDER BY layer_index", (pair_id,))
    rows = []
    for r in obs:
        evidence = json.loads(r["evidence_json"] or "{}")
        rows.append({"layer_index": r["layer_index"], "name": evidence.get("layer_name") or f"Layer {r['layer_index']}",
                     "lab": json.loads(r["lab_json"]), "parameters": json.loads(r["parameters_json"]),
                     "role": evidence.get("role", "test feature"), "submeasurements": evidence.get("submeasurements", []),
                     "line_metrics": evidence.get("line_metrics")})
    test_rows = [row for row in rows if row["role"] == "test feature"]
    operation_rows = [row for row in rows if row["role"] != "test feature"]

    device = store.one("SELECT name,manufacturer,model,serial FROM laser_device WHERE id=?", (pair["device_id"],))
    lens = json.loads(plate["lens_json"]) if plate["lens_json"] else None
    context = json.loads(pair["context_json"] or "{}")
    lightness_range = None
    if len(test_rows) >= 2:
        farthest = max(((color.delta_e(a["lab"], b["lab"]), a, b) for i, a in enumerate(test_rows) for b in test_rows[i + 1:]), key=lambda x: x[0])
        spread, row_a, row_b = farthest
        lightness = [r["lab"][0] for r in test_rows]
        lightness_range = [float(min(lightness)), float(max(lightness))]
        finding = (f"Most different measured areas: “{row_a['name']}” and “{row_b['name']}” "
                   f"(ΔE {spread:.1f}); measured L* range: {min(lightness):.1f}–{max(lightness):.1f}.")
        extrema = {"delta_e": float(spread), "first": _setting_label(row_a), "second": _setting_label(row_b)}
    elif test_rows:
        finding = "One area was measured; responses across settings cannot yet be compared."
        extrema = None
    else:
        finding = "The accepted pair has no measured test areas; only cleaning, markers, or technical results were retained."
        extrema = None

    limits = ["Lab is used only as a numerical signal of differences between areas in this photo, not to select an engraving color. Comparison within one plate alone does not establish the visible-mark threshold or actual output power."]
    measurement_modes = {json.loads(r["evidence_json"] or "{}").get("color_measurement", {}).get("mode") for r in obs}
    measurement_modes.discard(None)
    if "raw_camera_relative" in measurement_modes:
        limits.append("Values come from RAW without a reference chart: they are camera-relative measurements retained for this plate and excluded from standard color recommendations.")
    test_type = plate["test_type"]
    line_grid = [r for r in test_rows if r["name"].startswith("LINE-P") and r["line_metrics"]]
    visible_lines = sum(r["line_metrics"]["visible_line_count"] for r in line_grid)
    line_response = {"tested": len(line_grid), "visible": visible_lines,
                     "candidates": [_setting_label(r) for r in line_grid if r["line_metrics"]["visible_line_count"]]}
    gap_metrics = next((r["line_metrics"] for r in test_rows if r["name"].startswith("LINE-GAP-") and r["line_metrics"]), None)
    gap = {key: value for key, value in gap_metrics.items() if key != "lines"} if gap_metrics else None
    if test_type == "compact_capability" and line_grid:
        finding = (f"The photo shows {visible_lines} of {len(line_grid)} test single lines; "
                   f"the gap group shows {gap['visible_line_count']} of {gap['line_count']} lines."
                   if gap else f"The photo shows {visible_lines} of {len(line_grid)} test single lines.")
        limits.append("Visibility is determined by contrast with the surroundings in this photo; a mark not being detected does not prove the laser left no physical mark.")
    matrix_line = _matrix_line_case(test_rows) if test_type == "material_matrix" else None
    text_matrix = test_type == "material_matrix" and any(r["name"].startswith("TEXT-MATRIX-") for r in test_rows)
    use_cases = (_use_cases(test_rows) if test_type == "compact_capability" else
                 [_text_case(rows)] if test_type == "text_readability" or text_matrix else
                 [matrix_line] if matrix_line else [])
    signals, next_steps = _compact_interpretation(test_rows) if test_type == "compact_capability" else ([], [])
    if any(r["parameters"].get("pulse_width") is None for r in rows):
        limits.append("Q-Pulse is absent from some LightBurn layers; it remains unknown and is not substituted from the plate definition.")
    incomplete_wobble = []
    for row in test_rows:
        settings = row["parameters"].get("source_settings") or {}
        if settings.get("wobbleEnable", {}).get("Value") == "1" and (
            "wobbleStep" not in settings or "wobbleSize" not in settings
        ):
            incomplete_wobble.append(row["name"])
    if incomplete_wobble:
        limits.append("Enabled Wobble layers are missing interval or size: " + ", ".join(incomplete_wobble)
                      + ". A layer name does not replace actual file settings.")
    if test_type == "line_resolution":
        limits.append("The average measurement of a line group does not establish the smallest distinguishable gap or measure optical spot diameter.")
    elif test_type in ("hatch_interval", "offset_fill", "fill_sizes"):
        limits.append("An area average does not assess spatial fill uniformity; that requires analyzing the pixel distribution within each cell.")
    elif test_type == "power_speed":
        limits.append("A line’s average signal cannot confirm its continuity or the datasheet maximum speed.")

    return {"pair_id": pair_id, "plate_id": plate["id"], "test_type": test_type,
            "test_name": cp.TYPE_BY_ID[test_type]["name"], "test_description": cp.TYPE_BY_ID[test_type]["description"],
            "device": None if device is None else dict(device), "device_id": pair["device_id"],
            "lens": lens, "material": {"name": context.get("titanium_name"), "grade": context.get("titanium_grade"),
                                        "batch": context.get("batch")},
            "measurement_modes": sorted(measurement_modes),
            "accepted_at": pair["accepted_at"], "measured_features": len(test_rows), "operation_measurements": len(operation_rows),
            "finding": finding, "lightness_range": lightness_range, "max_separation": extrema,
            "line_response": line_response, "gap_response": gap,
            "signals": signals, "next_steps": next_steps, "use_cases": use_cases,
            "limitations": limits, "rows": rows, "operation_rows": operation_rows}


def for_device(store: Store, device_id: int) -> list[dict]:
    """Accepted capability-test reports for one physical laser, preserving each plate's lens identity."""
    rows = store.query(
        "SELECT DISTINCT pa.id FROM pair pa "
        "JOIN plan p ON p.id=pa.plan_id OR p.plate_id=pa.plate_id "
        "JOIN plate t ON t.id=COALESCE(pa.plate_id,p.plate_id) "
        "WHERE pa.status='Accepted' AND pa.device_id=? AND t.test_type IS NOT NULL "
        "AND pa.id=(SELECT MAX(pa2.id) FROM pair pa2 WHERE pa2.engraving_id=pa.engraving_id AND pa2.status='Accepted') "
        "ORDER BY pa.accepted_at DESC,pa.id DESC", (device_id,))
    return [report for r in rows if (report := report_for_pair(store, r["id"])) is not None]
