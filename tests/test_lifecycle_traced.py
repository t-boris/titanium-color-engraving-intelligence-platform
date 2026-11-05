"""Feature ux-engraving-lifecycle-p0 (REQ-001): the readiness of a traced work's file (what blocks it, as data the screen can link to a
region) and the file records of a traced work, which keep no promise. The photograph work's own chain is in ``test_lifecycle.py``."""
import itertools

import pytest

from test_vector_job import BLACK, GREEN, WHITE, by_colour, edit, job      # noqa: F401  (fixture)
from titanium_platform import conversion as cv, plans as pl, vector_job as vj


def lifecycle_of(c, j) -> dict:
    return c["client"].get(f"/api/vector/{j['id']}").json()["lifecycle"]


def test_a_traced_work_with_regions_that_lack_evidence_cannot_make_its_file_and_names_the_regions(job):
    c, j = job, job["job"]
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    ready = view["lifecycle"]["readiness"]
    assert ready["kind"] == "traced" and ready["ready"] is False and ready["reason"] == view["export_blocked"] and ready["local_only"] is True
    (blocker,) = ready["blockers"]
    assert blocker == {"code": "weak_regions", "count": len(view["weak"]), "ids": view["weak"], "target": {"kind": "region", "id": view["weak"][0]}}
    assert view["lifecycle"]["chain"]["stage"] == "prepared" and view["lifecycle"]["chain"]["next"] == {"code": "fix"}
    assert ready["size_mm"] == view["document"]["size_mm"] and ready["checks"]["colours"] is False and ready["checks"]["cleanup"] is True
    assert c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").status_code == 422             # the export itself still refuses


def test_resolving_every_region_makes_the_file_ready_with_its_size_time_and_layers(job):
    c, j = job, job["job"]
    j = edit(c, j, op="delete", region=by_colour(j, WHITE)[0]["id"])
    for letter in by_colour(j, BLACK):
        j = edit(c, j, op="set_task", region=letter["id"], task="line")
    j = edit(c, j, op="exclude", region=by_colour(j, GREEN)[0]["id"])
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    ready = view["lifecycle"]["readiness"]
    assert view["export_blocked"] is None and ready["ready"] is True and ready["blockers"] == [] and ready["reason"] is None
    assert ready["layers"] == len(view["layers"]) and ready["layer_cap"] == view["layer_cap"] and ready["checks"]["layers"]["ok"] is True
    assert ready["seconds"] > 0 and ready["time_complete"] is False                      # the lines of a traced work have no length here: the total says it is partial
    assert view["lifecycle"]["chain"]["next"] == {"code": "download"}


def test_a_traced_works_file_is_recorded_without_a_promise_and_walks_the_same_chain(job):
    c, j = job, job["job"]
    j = edit(c, j, op="delete", region=by_colour(j, WHITE)[0]["id"])
    for letter in by_colour(j, BLACK):
        j = edit(c, j, op="set_task", region=letter["id"], task="line")
    j = edit(c, j, op="exclude", region=by_colour(j, GREEN)[0]["id"])
    assert c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").status_code == 200
    lc = lifecycle_of(c, j)
    (file,) = lc["files"]
    assert file["number"] == 1 and file["current"] is True and file["promise"] == "none" and file["download_url"] == f"/api/vector/{j['id']}/exports/1"
    assert lc["chain"]["stage"] == "file"
    assert pl.get_plan(c["store"], j["id"])["exports"][0]["markers"] is True          # the record keeps the markers the file had
    j = edit(c, j, op="include", region=by_colour(j, GREEN)[0]["id"])
    assert lifecycle_of(c, j)["chain"]["stage"] == "prepared" and lifecycle_of(c, j)["chain"]["edited_after"] == 1


@pytest.mark.parametrize("weak,layers,cap", list(itertools.product(([], ["r1", "r2"]), (0, 3, 30), (28, 2))))
def test_the_blockers_are_empty_exactly_when_the_export_check_passes(weak, layers, cap):
    assessment = {"weak": weak, "layers": [{"index": n} for n in range(layers)]}
    try:
        vj.check_exportable(assessment, cap)
        passes = True
    except cv.ConversionError:
        passes = False
    found = vj.blockers_of(assessment, cap)
    assert (found == []) is passes
    assert [b["code"] for b in found] == (["weak_regions"] if weak else []) + (["nothing_to_engrave"] if not layers else ["too_many_layers"] if layers > cap else [])
    assert all("message" not in b and "reason" not in b for b in found)                 # data, not prose


STATE = {"by_id": {1: {}}, "zones": [], "missing_regions": [], "texts": [], "layers": [{}]}


@pytest.mark.parametrize("change", [
    {}, {"by_id": {}}, {"by_id": {}, "zones": [{}]}, {"missing_regions": ["a", "b"]}, {"texts": [{"problem": "the font is gone"}]},
    {"layers": []}, {"layers": [], "zones": [{}]}, {"layers": [{}] * 29}, {"layers": [{}] * 28, "zones": [{}]},
    {"zones": [{}], "rows": [{"problem": "its scale is not measured there", "number": 2}]}])
@pytest.mark.parametrize("markers", [False, True])
def test_the_photograph_blockers_are_empty_exactly_when_the_photograph_check_passes(change, markers):
    rows = change.pop("rows", None)
    state = {**STATE, **change}
    plan = {"markers_enabled": markers}
    message, found = vj._blocker_photo(plan, state, rows), vj._blockers_photo(plan, state, rows)
    assert (message is None) is (found == [])
    assert all(isinstance(b["code"], str) and b["target"] == {"kind": "tab", "tab": "colours"} for b in found)
    assert all("message" not in b for b in found)


def test_the_photograph_blockers_name_their_numbers():
    state = {**STATE, "by_id": {}, "missing_regions": [f"r{n}" for n in range(30)], "texts": [{"problem": None}, {"problem": "x"}], "layers": []}
    found = {b["code"]: b for b in vj._blockers_photo({"markers_enabled": False}, state, [{"problem": None, "number": 1}, {"problem": "y", "number": 2}])}
    assert set(found) == {"no_palette", "missing_colours", "text", "nothing_to_engrave", "zone"}
    assert found["missing_colours"]["count"] == 30 and len(found["missing_colours"]["ids"]) == vj.BLOCKER_IDS
    assert found["text"]["number"] == 2 and found["zone"]["number"] == 2
    assert found["text"]["problem"] == "x" and found["zone"]["problem"] == "y"               # the reason travels with the blocker, as the inscription and the zone state it
    over = vj._blockers_photo({"markers_enabled": True}, {**STATE, "layers": [{}] * 29}, None)
    assert over == [{"code": "too_many_layers", "count": 29, "cap": vj.photo_cap(True), "target": {"kind": "tab", "tab": "colours"}}]
