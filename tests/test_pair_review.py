"""The review of a photograph's pair as stages, blockers and manual tools (ux-photo-review-p0: REQ-001, REQ-002, DEC-001), and the
domain guarantees of its acceptance: no way back or change of an input leaves an obsolete acceptance state, and acceptance and
rejection keep their provenance, the measurement rules and the link to the engraved version (research n58)."""
import ast
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import synth
from test_ingest import edited_lbrn, make_pair, make_world
from test_supplied_settings import pair_without
from titanium_platform import ingest as ig
from titanium_platform import pair_review as pr
from titanium_platform.api.app import create_app

SOURCE = Path(ig.__file__).read_text(encoding="utf-8")
SETTINGS = {"x": {"param": "power", "first": 20, "last": 50}, "y": {"param": "speed", "first": 900, "last": 300},
            "fixed": {"frequency": 330, "pulse_width": 4, "line_interval": 0.003, "passes": 1}}


@pytest.fixture
def world(store):
    return make_world(store)


def checked(world, **kw):
    pid = make_pair(world, **kw)
    ig.check_pair(world["store"], pid)
    return pid


def ready(world):
    """A pair that may be accepted: checked, its masks reviewed."""
    pid = checked(world)
    ig.review_masks(world["store"], pid)
    return pid


def review(world, pid):
    return ig.get_pair(world["store"], pid)["review"]


def codes(state):
    return [b["code"] for b in state["blockers"]]


def refused(world, pid):
    """The message ``accept_pair`` refuses with, None when it accepted (then the pair is accepted: use on a pair not needed again)."""
    try:
        ig.accept_pair(world["store"], pid)
    except ig.IngestError as exc:
        return str(exc)
    return None


# -- REQ-001: the stages ------------------------------------------------------------------------------------------------------------
def test_the_stages_follow_the_pair_from_files_to_accepted_and_each_names_its_blockers(world):
    pid = make_pair(world)
    state = review(world, pid)
    assert state["stage"] == "files" and state["acceptable"] is False
    assert [(s["key"], s["state"]) for s in state["stages"]] == [("files", "current"), ("alignment", "todo"), ("review", "todo"), ("accept", "todo")]
    assert codes(state) == ["not_checked"] and state["blockers"][0]["tools"] == ["check"]

    ig.check_pair(world["store"], pid)
    state = review(world, pid)
    assert state["stage"] == "review" and codes(state) == ["masks_unreviewed"] and state["blockers"][0]["tools"] == ["masks"]
    assert [(s["key"], s["state"]) for s in state["stages"]] == [("files", "done"), ("alignment", "done"), ("review", "current"), ("accept", "todo")]
    assert state["stages"][2]["blockers"] == ["masks_unreviewed"] and state["acceptable"] is False

    ig.review_masks(world["store"], pid)
    state = review(world, pid)
    assert state["stage"] == "accept" and state["blockers"] == [] and state["acceptable"] is True

    ig.accept_pair(world["store"], pid)
    state = review(world, pid)
    assert state["stage"] == "accepted" and state["accepted"] and all(s["state"] == "done" for s in state["stages"]) and state["acceptable"] is False


def test_a_failed_alignment_is_the_alignment_stage_and_points_to_the_corners_and_the_detail(world):
    pid = make_pair(world, photo=png_of(np.full((900, 1200, 3), 60, np.uint8)))          # nothing of the plate can be found on it
    ig.check_pair(world["store"], pid)
    state = review(world, pid)
    assert state["stage"] == "alignment" and state["acceptable"] is False
    assert [(s["key"], s["state"]) for s in state["stages"]] == [("files", "done"), ("alignment", "current"), ("review", "todo"), ("accept", "todo")]
    problem = state["blockers"][0]
    assert problem["code"] == "alignment_failed" and problem["stage"] == "alignment" and problem["tools"] == ["corners", "anchor"]
    assert "registration markers" in problem["detail"]
    assert "layers_skipped" not in [a["code"] for a in state["advisories"]]            # nothing is measured without an alignment: not a second complaint
    assert state["tools"] == ["corners", "anchor", "shift", "matrix", "layers", "tasks"]
    with pytest.raises(ig.IngestError, match="not ready to accept"):
        ig.accept_pair(world["store"], pid)


def png_of(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def test_the_manual_tools_are_listed_with_or_without_a_warning_a_problem_or_a_check(world):
    """DEC-001: the entry points do not depend on what automation found."""
    every = ["corners", "anchor", "shift", "matrix", "layers", "tasks"]
    pid = make_pair(world)
    assert review(world, pid)["tools"] == every                              # not checked yet
    ig.check_pair(world["store"], pid)
    clean = review(world, pid)
    assert clean["tools"] == every and clean["advisories"] == []             # automation found nothing to warn about, the tools are still there
    broken = make_pair(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ig.check_pair(world["store"], broken)
    assert review(world, broken)["tools"] == every
    ig.review_masks(world["store"], pid)
    ig.accept_pair(world["store"], pid)
    assert review(world, pid)["tools"] == every


def test_a_file_that_differs_from_the_plate_is_blocking_in_files_with_the_confirmation_as_its_tool(world):
    pid = checked(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    state = review(world, pid)
    differs = next(b for b in state["blockers"] if b["code"] == "file_unconfirmed")
    assert differs["stage"] == "files" and differs["tools"] == ["file_confirm", "file"] and "differs from the plate definition" in differs["detail"]
    assert state["stage"] == "files" and state["acceptable"] is False
    ig.confirm_file(world["store"], pid, "I engraved with this exact file")
    assert codes(review(world, pid)) == ["masks_unreviewed"]


def test_a_layer_not_measured_and_a_lens_note_are_advisories_with_their_tools(world):
    pid = checked(world)
    pair = ig.get_pair(world["store"], pid)
    pair["check"]["layers"][2]["measured_lab"] = None
    pair["check"]["lens"] = {"warnings": ["this plate has no record of its lens"]}
    pair["check"]["warnings"] = ["Alignment starts from one manually placed detail; review the other layer outlines before accepting measurements."]
    notes = {a["code"]: a for a in pr.review_state(pair)["advisories"]}
    assert notes["layers_skipped"]["tools"] == ["layers"] and notes["layers_skipped"]["count"] == 1
    assert notes["lens_differs"]["tools"] == ["restart"]
    assert notes["single_detail"]["tools"] == ["anchor"]
    assert all(a["tools"] for a in notes.values())                           # every note has a tool to look into it with


# -- the known messages of the check all have a place on the screen -------------------------------------------------------------------
def _text(node):
    """The literal text of a string expression (f-string fields as «X»), None when it is not a plain string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left), _text(node.right)
        return None if left is None or right is None else left + right
    return None


def _messages(target: str) -> list[str]:
    """The literal messages ``<target>.append(...)`` receives in ingest.py (``problems`` or ``report["warnings"]``)."""
    out = []
    tree = ast.parse(SOURCE)
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) and function.name == "layer_report":
            function.body = []                         # its ``problems`` are the notes of one layer, not problems of the check
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append" and node.args:
            if ast.unparse(node.func.value) in {"problems": ("problems",), "warnings": ('report["warnings"]', "report['warnings']")}[target]:
                text = _text(node.args[0])
                if text:
                    out.append(text)
    return out


def test_every_problem_the_check_can_raise_is_classified_by_a_rule():
    problems = _messages("problems")
    assert len(problems) >= 12, problems
    unknown = [m for m in problems if pr.classify_problem(m)["code"] == "check_problem"]
    assert unknown == [], f"a new message of the check needs a rule in pair_review.PROBLEM_RULES: {unknown}"
    assert pr.classify_problem("pulse width 700 ns is outside the range of this laser (2-500 ns)")["tools"] == ["matrix"]


def test_every_warning_the_check_can_raise_is_classified_by_a_rule():
    warnings = _messages("warnings")
    assert len(warnings) >= 15, warnings
    unknown = [m for m in warnings if pr.classify_warning(m)["code"] == pr.FALLBACK_WARNING[0]]
    assert unknown == [], f"a new warning of the check needs a rule in pair_review.WARNING_RULES: {unknown}"


def test_each_problem_class_names_a_tool_that_exists():
    tools = set(pr.MANUAL_TOOLS) | set(pr.CONTEXT_TOOLS)
    for _, code, stage, used in pr.PROBLEM_RULES:
        assert stage in pr.STAGES and used and set(used) <= tools, code
    for _, code, used in pr.WARNING_RULES:
        assert used and set(used) <= tools, code
    assert pr.READY == ig.ST_READY and pr.ACCEPTED == ig.ST_ACCEPTED


# -- one gate: the blockers the screen lists and the refusal of accept_pair -------------------------------------------------------------
def test_the_blockers_are_empty_exactly_when_accept_pair_would_accept(world):
    store = world["store"]
    cases = {}
    cases["unchecked"] = make_pair(world)
    cases["masks"] = checked(world)
    cases["differs"] = checked(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    cases["good"] = ready(world)
    for name, pid in cases.items():
        state = review(world, pid)
        message = pr.refusal(ig.get_pair(store, pid))
        assert (message is None) == (state["blockers"] == []) == state["acceptable"], (name, state["blockers"], message)
        assert refused(world, pid) == message, name
    assert cases["good"] and ig.get_pair(store, cases["good"])["status"] == ig.ST_ACCEPTED


def test_the_refusals_of_accept_pair_read_as_they_always_did(world):
    store = world["store"]
    pid = make_pair(world)
    with pytest.raises(ig.IngestError, match="run the check first; the pair is not ready to accept"):
        ig.accept_pair(store, pid)
    ig.check_pair(store, pid)
    with pytest.raises(ig.IngestError, match="review the layer masks overlaid on the photograph before accepting"):
        ig.accept_pair(store, pid)
    bad = checked(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    with pytest.raises(ig.IngestError, match="not ready to accept"):
        ig.accept_pair(store, bad)
    pair = ig.get_pair(store, pid)
    pair["check"]["problems"] = ["Alignment: x"]
    assert pr.refusal({**pair, "status": ig.ST_READY}) == "resolve the problems found by the check: Alignment: x"
    pair["check"]["problems"] = []
    pair["check"]["color_measurement"] = None
    assert pr.refusal(pair) == pr.NO_BASIS
    pair["check"]["color_measurement"] = {"mode": "reference_chart_corrected"}
    pair["check"]["layers"] = [{**rep, "measured_lab": None} for rep in pair["check"]["layers"]]
    pair["masks_reviewed"] = True
    assert pr.refusal(pair) == pr.NO_LAYER
    assert "no_measured_layer" in [b["code"] for b in pr.blockers(pair)]


# -- the domain guarantee: no way back and no changed input leaves an obsolete acceptance state ---------------------------------------
def test_a_new_check_from_any_earlier_stage_takes_the_review_back_to_the_masks(world):
    """Going back to the files or the alignment and checking again (a plain re-check, "find again", corners, a moved overlay)
    clears the mask review: an accepted-looking pair cannot be accepted until the masks are reviewed on the new result."""
    store = world["store"]
    for label, again in {
        "re-check": lambda pid: ig.check_pair(store, pid),
        "find again": lambda pid: ig.check_pair(store, pid, reset_alignment=True),
        "moved overlay": lambda pid: ig.check_pair(store, pid, translation_fraction=[.002, -.002]),
        "rotated overlay": lambda pid: ig.check_pair(store, pid, rotation_degrees=.3),
    }.items():
        pid = ready(world)
        assert review(world, pid)["acceptable"] is True, label
        again(pid)
        state = review(world, pid)
        assert state["acceptable"] is False and "masks_unreviewed" in codes(state) and state["stage"] == "review", (label, state["blockers"])
        assert ig.get_pair(store, pid)["masks_reviewed"] is False
        with pytest.raises(ig.IngestError, match="review the layer masks"):
            ig.accept_pair(store, pid)
        assert store.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pid,))["n"] == 0
        ig.review_masks(store, pid)
        assert review(world, pid)["acceptable"] is True, label


def test_replacing_the_lightburn_file_takes_the_pair_back_to_the_start(world):
    store = world["store"]
    pid = ready(world)
    ig.replace_lightburn_file(store, pid, "other.lbrn2", world["lbrn"])
    state = review(world, pid)
    assert state["stage"] == "files" and codes(state) == ["not_checked"] and state["acceptable"] is False
    pair = ig.get_pair(store, pid)
    assert pair["check"] is None and pair["masks_reviewed"] is False and pair["file_confirmation"] is None and pair["status"] == ig.ST_PENDING
    with pytest.raises(ig.IngestError, match="run the check first"):
        ig.accept_pair(store, pid)


def test_a_setting_given_or_taken_back_clears_the_mask_review(world):
    from test_supplied_settings import plate_world
    w = plate_world(world["store"])
    pid = pair_without(w, "QPulseWidth")
    first = ig.check_pair(w["store"], pid)
    layer = next(rep for rep in first["layers"] if rep["name"] == "r1c1")
    state = ig.get_pair(w["store"], pid)["review"]
    lacking = next(a for a in state["advisories"] if a["code"] == "settings_missing")
    assert lacking["tools"] == ["supplied"] and "r1c1" in lacking["names"] and "settings_missing" not in codes(state)    # advisory, not blocking
    ig.review_masks(w["store"], pid)
    assert ig.get_pair(w["store"], pid)["masks_reviewed"] is True
    ig.supply_setting(w["store"], pid, layer["index"], "pulse_width", 200)
    assert ig.get_pair(w["store"], pid)["masks_reviewed"] is False
    assert "masks_unreviewed" in codes(ig.get_pair(w["store"], pid)["review"])
    ig.review_masks(w["store"], pid)
    ig.supply_setting(w["store"], pid, layer["index"], "pulse_width", None)
    assert ig.get_pair(w["store"], pid)["masks_reviewed"] is False


def test_choosing_a_task_or_confirming_the_file_does_not_pretend_to_change_the_measurement(world):
    store = world["store"]
    pid = ready(world)
    ig.set_task(store, pid, None, "fill")
    assert ig.get_pair(store, pid)["masks_reviewed"] is True and review(world, pid)["acceptable"] is True      # it changes no measurement
    bad = checked(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ig.review_masks(store, bad)
    ig.confirm_file(store, bad, "used")
    assert ig.get_pair(store, bad)["masks_reviewed"] is True and review(world, bad)["acceptable"] is True


def test_a_confirmation_given_for_other_differences_than_the_current_ones_does_not_count(world):
    store = world["store"]
    pid = checked(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ig.confirm_file(store, pid, "used")
    ig.review_masks(store, pid)
    assert review(world, pid)["acceptable"] is True
    # the differences found now are not those the operator confirmed
    pair = ig.get_pair(store, pid)
    pair["file_confirmation"]["discrepancies"] = [{"cell_id": "r1c2", "field": "power", "defined": 20, "from_file": 25}]
    ig._save(store, pid, pair)
    state = review(world, pid)
    assert state["acceptable"] is False and "file_unconfirmed" in codes(state) and state["blockers"][0]["stage"] == "files"
    with pytest.raises(ig.IngestError, match="differs from the plate definition"):
        ig.accept_pair(store, pid)
    # a new check asks again instead of carrying the old confirmation along
    report = ig.check_pair(store, pid)
    assert ig.get_pair(store, pid)["file_confirmation"] is None
    assert any("differs from the plate definition" in p for p in report["problems"])
    # while the same differences keep their confirmation through a re-check
    again = checked(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ig.confirm_file(store, again, "used")
    ig.check_pair(store, again)
    assert ig.get_pair(store, again)["file_confirmation"] is not None
    assert pr.confirmation_covers({"discrepancies": None}, [{"cell_id": "x"}]) and not pr.confirmation_covers(None, [{"cell_id": "x"}])
    assert pr.confirmation_covers(None, [])


def test_a_corrected_matrix_must_be_confirmed_and_reviewed_again(tmp_path):
    app = create_app(tmp_path / "data")
    store = app.state.store
    store.set_setting("allow_non_raw_photos", True)
    with TestClient(app) as client:
        laser = client.post("/api/devices/from-template", json={"template": "jpt-ydflp-e-60-m7-m-r"}).json()
        material = client.post("/api/materials", json={"name": "Grade 2 sheet", "grade": "Grade 2", "thickness_mm": 1, "surface": "brushed"}).json()
        client.post("/api/setups", json={"name": "Rig", "camera": "cam", "lighting": "LED", "angle": "90", "reference_chart": "ColorChecker Classic"})
        photo = png_of(synth.material_test(cols=4, rows=3, x_values=[20.0, 30.0, 40.0, 50.0], y_values=[900.0, 600.0, 300.0])["photo"])
        made = client.post("/api/matrix-pairs", data={"device_id": laser["id"], "lens_id": "unknown", "context": f'{{"material_id": {material["id"]}}}'},
                           files={"photo": ("matrix.png", photo, "image/png")})
        assert made.status_code == 201, made.text
        pid = made.json()["id"]
        client.post(f"/api/pairs/{pid}/check", json={})
        edited = client.post(f"/api/pairs/{pid}/matrix", json={"edit": SETTINGS, "confirm": True}).json()
        assert edited["matrix"]["confirmed"] and edited["check"]["problems"] == []
        assert edited["review"]["blockers"][0]["code"] == "masks_unreviewed"
        client.post(f"/api/pairs/{pid}/review-masks")
        assert client.get(f"/api/pairs/{pid}").json()["review"]["acceptable"] is True
        # the matrix is edited after it was confirmed and its masks reviewed: both are gone
        again = client.post(f"/api/pairs/{pid}/matrix", json={"edit": {**SETTINGS, "fixed": {**SETTINGS["fixed"], "passes": 2}}}).json()
        assert again["matrix"]["confirmed"] is False and again["masks_reviewed"] is False
        found = [b["code"] for b in again["review"]["blockers"]]
        assert "matrix_unconfirmed" in found and "masks_unreviewed" in found and again["review"]["acceptable"] is False
        unconfirmed = next(b for b in again["review"]["blockers"] if b["code"] == "matrix_unconfirmed")
        assert unconfirmed["stage"] == "files" and unconfirmed["tools"] == ["matrix"]
        assert client.post(f"/api/pairs/{pid}/accept").status_code == 422
        assert client.get(f"/api/pairs/{pid}/anchor-candidates").json() == {"candidates": []}        # a matrix is aligned by its grid
    store.close()


# -- REQ-002: workpiece alignment can correct an alignment automation took for valid -------------------------------------------------
def test_the_details_of_the_file_are_offered_where_a_valid_alignment_puts_them(world):
    store = world["store"]
    pid = checked(world)
    pair = ig.get_pair(store, pid)
    assert pair["check"]["alignment"]["valid"] and pair["check"]["alignment"]["method"] == "markers"       # automation considers it valid
    found = ig.anchor_candidates(store, pid)
    assert {c["element"] for c in found} == {"r1c1 #1", "r1c2 #1", "r2c1 #1", "r2c2 #1"}          # the test cells; cleaning and markers are system layers
    for item in found:
        assert len(item["corners_fraction"]) == 4 and all(0 <= v <= 1 for p in item["corners_fraction"] for v in p)
        assert item["basis"] == "current alignment" and item["area_mm2"] > 0
    assert found == sorted(found, key=lambda c: -c["area_mm2"])


def test_a_detail_placed_by_hand_corrects_an_alignment_automation_took_for_valid_and_survives_a_re_check(world):
    store = world["store"]
    pid = checked(world)
    automatic = np.asarray(ig.get_pair(store, pid)["check"]["alignment"]["image_to_mm"])
    cell = ig.anchor_candidates(store, pid)[0]
    dx = .004                                               # the operator finds the whole drawing a little to the right of the plate
    moved = [[x + dx, y] for x, y in cell["corners_fraction"]]
    report = ig.check_pair(store, pid, anchor={"layer_index": cell["layer_index"], "region_index": cell["region_index"], "corners_fraction": moved})
    assert report["alignment"]["valid"] and report["alignment"]["method"] == "element anchor"          # not "markers": the hand decides
    after = np.asarray(report["alignment"]["image_to_mm"])
    width, height = report["image_size"]
    centre = np.array([[[width / 2, height / 2]]], np.float64)
    shift_px = cv2.perspectiveTransform(cv2.perspectiveTransform(centre, after), np.linalg.inv(automatic))[0, 0] - centre[0, 0]
    assert abs(abs(shift_px[0]) - dx * width) < 1.5, shift_px              # the drawing moved by what the operator moved
    assert ig.get_pair(store, pid)["masks_reviewed"] is False
    assert ig.check_pair(store, pid)["alignment"]["method"] == "element anchor"                       # kept by a plain re-check
    assert ig.check_pair(store, pid, reset_alignment=True)["alignment"]["method"] == "markers"       # "find again" returns to the automatic one


def test_without_an_alignment_the_candidates_are_the_ones_the_check_found_on_the_photograph(world):
    store = world["store"]
    pid = checked(world)
    pair = ig.get_pair(store, pid)
    size = pair["check"]["image_size"]
    tiny = [[.1, .1], [.101, .1], [.101, .101], [.1, .101]]
    big = [[.2, .2], [.4, .2], [.4, .4], [.2, .4]]
    pair["check"]["alignment"].pop("image_to_mm")
    pair["check"]["alignment"]["suggestions"] = [{"layer_index": 1, "region_index": 0, "element": "a", "shape_score": .1, "corners_fraction": tiny},
                                                 {"layer_index": 1, "region_index": 1, "element": "b", "shape_score": .1, "corners_fraction": big}]
    ig._save(store, pid, pair)
    assert size and [c["element"] for c in ig.anchor_candidates(store, pid)] == ["b"]            # too small to grab: left out


def test_the_candidates_route_and_the_review_travel_with_the_pair_over_http(tmp_path):
    app = create_app(tmp_path / "data")
    w = make_world(app.state.store)
    pid = checked(w)
    with TestClient(app) as client:
        pair = client.get(f"/api/pairs/{pid}").json()
        assert pair["review"]["stage"] == "review" and pair["review"]["tools"][1] == "anchor" and "photo_path" not in pair
        found = client.get(f"/api/pairs/{pid}/anchor-candidates").json()["candidates"]
        assert len(found) == 4
        assert client.get("/api/pairs/9999/anchor-candidates").status_code == 404
        assert client.post(f"/api/pairs/{pid}/accept").status_code == 422
        assert client.post(f"/api/pairs/{pid}/review-masks").status_code == 200
        done = client.post(f"/api/pairs/{pid}/accept").json()
        assert done["pair"]["review"]["stage"] == "accepted" and client.get(f"/api/pairs/{pid}/anchor-candidates").status_code == 422
    app.state.store.close()


# -- acceptance and rejection keep what they must ------------------------------------------------------------------------------------
def test_acceptance_after_going_back_keeps_the_provenance_the_measurement_rules_and_the_engraved_version(world):
    store = world["store"]
    pid = checked(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ig.confirm_file(store, pid, "I engraved with this exact file")
    ig.review_masks(store, pid)
    ig.check_pair(store, pid)                                    # back to the check from a later stage: the review is asked for again
    assert review(world, pid)["acceptable"] is False
    ig.review_masks(store, pid)
    pair = ig.get_pair(store, pid)
    assert pair["file_confirmation"]["text"] and review(world, pid)["acceptable"] is True
    ids = ig.accept_pair(store, pid)
    assert len(ids) == 6
    rows = store.query("SELECT * FROM observation WHERE pair_id=? ORDER BY layer_index", (pid,))
    assert {r["engraving_id"] for r in rows} == {pair["engraving_id"]}                      # the link to the engraved version
    assert {r["alignment_method"] for r in rows} == {pair["check"]["alignment"]["method"]}
    system = [r for r in rows if r["layer_index"] in (-1, 0)]
    assert system and not any(r["model_eligible"] for r in system)                          # cleaning and markers never feed the model (DEC-027)
    cell = next(r for r in rows if r["layer_index"] == 2)
    evidence = json.loads(cell["evidence_json"])
    assert evidence["file_confirmation"]["text"].startswith("I engraved") and evidence["discrepancies"][0]["from_file"] == 33
    assert evidence["color_measurement"]["mode"] == "reference_chart_corrected" and evidence["lightburn_file"] == "plate.lbrn2"
    assert set(evidence["settings_provenance"].values()) <= {"file", "operator", "laser default", None} and evidence["task"]["kind"]
    assert cell["model_eligible"] == 1
    audit = store.one("SELECT detail_json FROM audit WHERE action='pair_accepted'")
    assert json.loads(audit["detail_json"]) == {"pair_id": pid, "observations": 6}


def test_a_pair_taken_back_after_acceptance_review_cannot_be_accepted_twice(world):
    store = world["store"]
    pid = ready(world)
    ig.accept_pair(store, pid)
    for action in (lambda: ig.accept_pair(store, pid), lambda: ig.check_pair(store, pid), lambda: ig.review_masks(store, pid),
                   lambda: ig.set_task(store, pid, None, "fill"), lambda: ig.replace_lightburn_file(store, pid, "x.lbrn2", world["lbrn"])):
        with pytest.raises(ig.IngestError, match="immutable"):
            action()
    assert store.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pid,))["n"] == 6
    revision = ig.create_alignment_revision(store, pid)                      # a correction of an accepted alignment is a new pair
    state = review(world, revision)
    assert state["acceptable"] is False and codes(state) == ["masks_unreviewed"]
    assert ig.get_pair(store, pid)["status"] == ig.ST_ACCEPTED               # the accepted one stays until the correction is accepted


def test_a_rejected_pair_writes_no_observation_and_keeps_its_provenance_in_the_audit(world):
    store = world["store"]
    pid = checked(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ig.confirm_file(store, pid, "I engraved with this exact file")
    pair = ig.get_pair(store, pid)
    ig.delete_pair(store, pid)
    kept = json.loads(store.one("SELECT data_json FROM pair WHERE id=?", (pid,))["data_json"])         # the record of the pair stays; only the uploaded files go
    assert kept["check"]["color_measurement"] == pair["check"]["color_measurement"] and kept["file_confirmation"]["text"].startswith("I engraved")
    assert kept["check"]["discrepancies"] == pair["check"]["discrepancies"]
    assert store.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pid,))["n"] == 0
    assert store.one("SELECT status FROM pair WHERE id=?", (pid,))["status"] == ig.ST_DELETED
    detail = json.loads(store.one("SELECT detail_json FROM audit WHERE action='pair_deleted'")["detail_json"])
    assert detail["pair_id"] == pid and detail["previous_status"] == ig.ST_READY and detail["observations"] == 0
    assert detail["engraving_id"] == pair["engraving_id"] and detail["lightburn_file"] == "plate.lbrn2" and detail["photo_file"] == "plate.png"


def test_rejecting_an_accepted_pair_keeps_its_observations_in_the_audit_history(world):
    store = world["store"]
    pid = ready(world)
    ig.accept_pair(store, pid)
    ig.delete_pair(store, pid)
    assert store.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pid,))["n"] == 6       # the immutable record stays (DEC-047)
    detail = json.loads(store.one("SELECT detail_json FROM audit WHERE action='pair_deleted'")["detail_json"])
    assert detail["previous_status"] == ig.ST_ACCEPTED and detail["observations"] == 6 and detail["engraving_id"]
