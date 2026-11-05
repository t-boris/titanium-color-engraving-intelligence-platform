"""A photograph's pair as four stages (files, alignment, review, acceptance) and what stands in the way of accepting it
(feature ux-photo-review-p0: REQ-001, REQ-002, DEC-001).

``review_state(pair)`` is derived on every read from what the pair stores (``ingest.get_pair`` attaches it as ``pair["review"]``)
and is never stored, so it cannot disagree with the pair. The acceptance gate is here too: ``ingest.accept_pair`` takes its
refusal from ``refusal(pair)``, and the screen lists the same conditions as ``blockers``, each with the explanation the operator
reads and the manual tool that resolves it. A test runs both over the same pairs.

What is blocking and what is advisory is not decided here: a blocker is exactly a condition ``accept_pair`` has always refused
on (a problem the check found, a file that differs from the plate definition and is not confirmed, masks not reviewed, matrix
settings not confirmed, nothing measured, no colour basis); an advisory is a note the check already makes (``check.warnings``,
the lens notes, a layer not measured, a setting the file lacks) that does not stop acceptance.

UPSTREAM CHANGES THAT INVALIDATE A REVIEW (``INVALIDATED_BY``; each is tested in tests/test_pair_review.py)
  lightburn_file     ``replace_lightburn_file``: the check, the file confirmation, the mask review and the manual alignment are cleared;
                     the pair is "Awaiting check" again.
  alignment          ``check_pair`` with corners, an element anchor, a moved / rotated / scaled / mirrored overlay, "find again" or a
                     plain re-check: the check is recomputed, the mask review is cleared, the status follows the new check.
  supplied_settings  ``supply_setting`` (a setting given or taken back): the pair is checked again, so the same as above.
  matrix             ``update_matrix`` (a corrected matrix): the confirmation of its settings is cleared and the pair is checked again.
  plate_comparison   a check whose comparison with the plate definition differs from the one the operator confirmed removes that
                     confirmation (it covered other differences); ``refusal`` also refuses a confirmation that does not cover the
                     current differences.
Not invalidating: choosing an engraving task (it changes no measurement and is recorded with the observations), confirming the
file, confirming the matrix settings. An accepted pair is immutable; a correction of its alignment is a new pair
(``create_alignment_revision``) that starts with the masks unreviewed.
"""
from __future__ import annotations

import re

READY, ACCEPTED = "Ready to accept", "Accepted"       # the values of ingest.ST_READY and ingest.ST_ACCEPTED (a test compares them)
STAGES = ("files", "alignment", "review", "accept")
# The manual tools whose entry points stay visible through the whole review, with or without a warning (DEC-001), and the tools
# that exist only in the context of one condition.
MANUAL_TOOLS = ("corners", "anchor", "shift", "matrix", "layers", "tasks")
CONTEXT_TOOLS = ("check", "file", "file_confirm", "supplied", "masks", "restart")
INVALIDATED_BY = ("lightburn_file", "alignment", "supplied_settings", "matrix", "plate_comparison")
SYSTEM_ROLES = ("pre-test cleaning witness", "registration, QR and engraved labels")

# The refusals of ``accept_pair``, word for word (the operator and the tests know them).
NOT_READY = "run the check first; the pair is not ready to accept"
NO_BASIS = "the photograph has no usable color measurement basis"
FILE_DIFFERS = "the LightBurn file differs from the plate definition: correct the pair or confirm the file"
MASKS = "review the layer masks overlaid on the photograph before accepting"
MATRIX = "confirm the settings read from the matrix before accepting"
NO_LAYER = "no readable, comparable layer to accept"
PROBLEMS = "resolve the problems found by the check: "

# What a message of the check means for the screen: (pattern, code, stage, tools). The first match wins; a message that matches
# none is a ``check_problem`` of the review stage (re-run the check). tests/test_pair_review.py reads the messages out of
# ingest.py and fails for one that no rule knows, so a new message cannot reach the screen without a place.
PROBLEM_RULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (r"^LightBurn file:", "file_unreadable", "files", ("file",)),
    (r"^Photograph:", "photo_unreadable", "files", ("restart",)),
    (r"^experiment identifier .* is not known", "identifier_unknown", "files", ("file",)),
    (r"^experiment identifier .* deleted experiment", "identifier_deleted", "files", ("file",)),
    (r"^this (plate|plan) was made for a different laser", "other_laser", "files", ("restart",)),
    (r"^the matrix settings are incomplete", "matrix_incomplete", "files", ("matrix",)),
    (r"^pulse width .* is outside the range of this laser", "matrix_pulse_width", "files", ("matrix",)),
    (r"^A reference-chart candidate was detected|^Reference chart not detected", "no_chart", "files", ("restart",)),
    (r"^plate cells not found in the LightBurn file", "plate_cells_missing", "files", ("file",)),
    (r"^The LightBurn file differs from the plate definition", "file_unconfirmed", "files", ("file_confirm", "file")),
    (r"^Alignment: the adjustment lost too many", "alignment_lost", "alignment", ("shift", "corners")),
    (r"^Alignment:", "alignment_failed", "alignment", ("corners", "anchor")),
    (r"^No readable, comparable layer could be measured", "no_measured_layer", "review", ("layers", "corners")),
)
WARNING_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (r"adjusted by hand", "overlay_adjusted", ("shift",)),
    (r"manually placed detail|Only one distinctive detail|not confirmed by element anchors", "single_detail", ("anchor",)),
    (r"corners were corrected manually|Manual alignment was used|QR identifier is unreadable|QR identifier could not be verified",
     "manual_alignment", ("corners",)),
    (r"frame hides|edge of the frame was not found|picture of the file was matched|found by the pictures of layers",
     "frame_hides_edges", ("corners", "anchor")),
    (r"output switched off|output is switched off|stayed where the exported file had them|outside the standard output color range",
     "layers_not_measured", ("layers",)),
    (r"without reference-chart correction", "colour_relative", ("restart",)),
    (r"^this file belongs to", "other_work_file", ("file",)),
    (r"^the file is .* of the export", "file_resized", ("layers",)),
)
LENS_RULE = ("lens_differs", ("restart",))
FALLBACK_WARNING = ("warning", ("layers",))


def _signature(discrepancies) -> list[tuple]:
    return sorted((str(d.get("cell_id")), str(d.get("field")), repr(d.get("defined")), repr(d.get("from_file"))) for d in discrepancies or [])


def confirmation_covers(confirmation: dict | None, discrepancies: list | None) -> bool:
    """Whether the operator's file confirmation was given for these very differences (one without a copy of them, an old
    record, is taken to cover them: there is nothing to compare)."""
    if not discrepancies:
        return True
    if not confirmation:
        return False
    recorded = confirmation.get("discrepancies")
    return recorded is None or _signature(recorded) == _signature(discrepancies)


def _measured(check: dict) -> list[dict]:
    return [rep for rep in check.get("layers") or [] if rep.get("measured_lab") is not None]


def refusal(pair: dict) -> str | None:
    """Why ``accept_pair`` must refuse this pair (its message, word for word, in its order), or None when it may accept."""
    check = pair.get("check")
    if not check or pair.get("status") != READY:
        return NOT_READY
    if not check.get("color_measurement"):
        return NO_BASIS
    if check.get("problems"):
        return PROBLEMS + "; ".join(check["problems"])
    if check.get("discrepancies") and not confirmation_covers(pair.get("file_confirmation"), check["discrepancies"]):
        return FILE_DIFFERS
    if not pair.get("masks_reviewed"):
        return MASKS
    if pair.get("matrix") and not pair["matrix"].get("confirmed"):
        return MATRIX
    if not _measured(check):
        return NO_LAYER
    return None


def _blocker(code: str, stage: str, tools: tuple[str, ...], detail: str | None = None) -> dict:
    return {"code": code, "stage": stage, "tools": list(tools), "detail": detail}


def classify_problem(message: str) -> dict:
    for pattern, code, stage, tools in PROBLEM_RULES:
        if re.search(pattern, message):
            return _blocker(code, stage, tools, message)
    return _blocker("check_problem", "review", ("check",), message)


def classify_warning(message: str) -> dict:
    for pattern, code, tools in WARNING_RULES:
        if re.search(pattern, message):
            return {"code": code, "tools": list(tools), "detail": message}
    return {"code": FALLBACK_WARNING[0], "tools": list(FALLBACK_WARNING[1]), "detail": message}


def blockers(pair: dict) -> list[dict]:
    """Every condition that stops the acceptance of the pair, in the order of the stages, each with the stage it belongs to and the
    tools that resolve it (the first is the main one). Empty exactly when ``refusal`` is None."""
    check = pair.get("check")
    if not check:
        return [_blocker("not_checked", "files", ("check",))]
    if refusal(pair) is None:
        return []                  # the screen never blocks what the server allows, nor allows what it blocks
    out = [classify_problem(message) for message in check.get("problems") or []]
    alignment = check.get("alignment") or {}
    if check.get("discrepancies") and not confirmation_covers(pair.get("file_confirmation"), check["discrepancies"]) \
            and not any(b["code"] == "file_unconfirmed" for b in out):
        out.append(_blocker("file_unconfirmed", "files", ("file_confirm", "file")))
    if pair.get("matrix") and not pair["matrix"].get("confirmed"):
        out.append(_blocker("matrix_unconfirmed", "files", ("matrix",)))
    if not check.get("color_measurement") and not any(b["code"] in ("no_chart", "photo_unreadable", "file_unreadable") for b in out):
        out.append(_blocker("no_colour_basis", "files", ("restart",)))
    if not alignment.get("valid") and not any(b["stage"] in ("files", "alignment") for b in out):
        out.append(_blocker("alignment_failed", "alignment", ("corners", "anchor")))
    if alignment.get("valid") and not pair.get("masks_reviewed"):
        out.append(_blocker("masks_unreviewed", "review", ("masks",)))
    if not _measured(check) and not any(b["code"] == "no_measured_layer" for b in out) and alignment.get("valid"):
        out.append(_blocker("no_measured_layer", "review", ("layers", "corners")))
    if not out and (pair.get("status") != READY or refusal(pair)):
        out.append(_blocker("not_ready", "review", ("check",), refusal(pair)))
    seen, unique = set(), []
    for item in sorted(out, key=lambda b: STAGES.index(b["stage"])):
        if (item["code"], item["detail"]) not in seen:
            seen.add((item["code"], item["detail"]))
            unique.append(item)
    return unique


def advisories(pair: dict) -> list[dict]:
    """Notes that do not stop acceptance, each with the tools that look into it: the warnings of the check (each mapped to the tool
    of the thing it warns about), the lens notes, layers not measured, settings the file lacks."""
    check = pair.get("check")
    if not check:
        return []
    out = [classify_warning(message) for message in check.get("warnings") or []]
    out += [{"code": LENS_RULE[0], "tools": list(LENS_RULE[1]), "detail": message} for message in (check.get("lens") or {}).get("warnings") or []]
    alignment = check.get("alignment") or {}
    offset = alignment.get("qr_offset_px") or [0, 0]
    if alignment.get("valid") and alignment.get("qr_used_as_anchor") is False and (offset[0] ** 2 + offset[1] ** 2) ** .5 > 10:
        out.append({"code": "qr_offset", "tools": ["corners"], "detail": None})
    layers = [rep for rep in check.get("layers") or [] if rep.get("regions")] if alignment.get("valid") else []     # no alignment: nothing is measured, and that is the blocker's news
    skipped = [rep["name"] for rep in layers if rep.get("measured_lab") is None]
    if skipped:
        out.append({"code": "layers_skipped", "tools": ["layers"], "detail": None, "count": len(skipped), "names": skipped[:5]})
    unfit = [rep["name"] for rep in layers if rep.get("measured_lab") is not None and not rep.get("compatible", True)
             and (rep.get("role") or "test feature") == "test feature"]          # cleaning and marker layers never feed the model anyway
    if unfit:
        out.append({"code": "layers_incomparable", "tools": ["layers", "supplied"], "detail": None, "count": len(unfit), "names": unfit[:5]})
    if not pair.get("matrix"):
        lacking = [rep["name"] for rep in layers if rep.get("missing_settings") and (rep.get("role") or "test feature") == "test feature"
                   and not all((rep.get("supplied_settings") or {}).get(s) for s in rep["missing_settings"])]
        if lacking:
            out.append({"code": "settings_missing", "tools": ["supplied"], "detail": None, "count": len(lacking), "names": lacking[:5]})
    return out


def review_state(pair: dict) -> dict:
    """The stages of the pair and what is left to do: ``stage`` (the one to work on: files, alignment, review, accept, or
    accepted), ``stages`` (key, state done / current / todo, the codes of its blockers), ``blockers``, ``advisories``,
    ``acceptable`` (the gate of ``accept_pair`` is clear) and ``tools`` (the manual tools, always listed)."""
    if pair.get("status") == ACCEPTED:
        return {"stage": "accepted", "accepted": True, "acceptable": False, "blockers": [], "advisories": [], "tools": list(MANUAL_TOOLS),
                "stages": [{"key": key, "state": "done", "blockers": []} for key in STAGES]}
    found = blockers(pair)
    check = pair.get("check")
    by_stage = {key: [b["code"] for b in found if b["stage"] == key] for key in STAGES}
    alignment = (check or {}).get("alignment") or {}
    done = {"files": bool(check) and not by_stage["files"],
            "alignment": bool(check) and bool(alignment.get("valid")) and not by_stage["alignment"],
            "review": bool(check) and bool(alignment.get("valid")) and bool(pair.get("masks_reviewed")) and not by_stage["review"],
            "accept": False}
    current = next((key for key in STAGES if not done[key]), "accept")
    return {"stage": current, "accepted": False, "acceptable": refusal(pair) is None, "blockers": found, "advisories": advisories(pair),
            "tools": list(MANUAL_TOOLS),
            "stages": [{"key": key, "state": "done" if done[key] else "current" if key == current else "todo", "blockers": by_stage[key]}
                       for key in STAGES]}
