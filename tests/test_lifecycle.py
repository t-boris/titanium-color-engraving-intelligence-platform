"""Feature ux-engraving-lifecycle-p0 (REQ-001..003): the life of the file of one work (prepared, file received, result added, checked), the
readiness of the file, the files a work handed out, the basis a comparison names, and what an accepted result did to the prediction.

The chain is read from what is already kept: the append-only export records of a work, its photographs and their reviews. These tests run
the real application (as ``test_work_review.py`` does) and move times by hand where the order of two things within a second matters."""
import json

import pytest
from fastapi.testclient import TestClient

from test_supplied_settings import JOB
from test_vector_work import PAPER, YELLOW, by_rgb, colouring, create, job, lab, palette_ids, picture, work    # noqa: F401  (fixtures)
from test_work_review import engrave, exported, moved
from titanium_platform import conversion as cv, lifecycle, plans as pl, vector_job, work_errors
from titanium_platform.api.app import create_app

EARLY, MID, LATE = "2026-01-01T10:00:00+00:00", "2026-01-02T10:00:00+00:00", "2026-01-03T10:00:00+00:00"


def chain_of(c, j) -> dict:
    return c["client"].get(f"/api/vector/{j['id']}").json()["lifecycle"]


def stamp(c, j, times: list[str]) -> None:
    """Set the time of each export of the work (oldest first): the order of an export and a photograph within one second is nobody's to read."""
    plan = pl.get_plan(c["store"], j["id"])
    for record, at in zip(plan["exports"], times):
        record["at"] = at
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])


def at(c, pair_id: int, when: str, status: str | None = None) -> None:
    c["store"].execute("UPDATE pair SET created_at=? WHERE id=?", (when, pair_id))
    if status:
        c["store"].execute("UPDATE pair SET status=? WHERE id=?", (status, pair_id))


def accept(c, j, **kw) -> int:
    pair = engrave(c, j, **kw)
    work_errors.after_acceptance(c["store"], pair)
    return pair


def edit(c, j):
    """Any edit of the colouring: a work edited since its file is no longer the file's work."""
    return colouring(c, j, op="assign", mode="random")


# -- REQ-001: the chain -------------------------------------------------------------------------------------------------------------------
def test_a_work_never_exported_is_prepared_and_says_what_its_file_would_be(work, job):
    c, j = work, job
    lc = chain_of(c, j)
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    assert lc["chain"]["stage"] == "prepared" and lc["files"] == [] and lc["unlinked"] == []
    assert [s["state"] for s in lc["chain"]["steps"]] == ["current", "todo", "todo", "todo"]
    ready = lc["readiness"]
    assert ready["kind"] == "photo" and ready["ready"] is (view["export_blocked"] is None) and ready["local_only"] is True
    assert ready["size_mm"] == view["document"]["size_mm"] and ready["seconds"] == view["time"]["seconds"] and ready["layer_cap"] == view["layer_cap"]
    assert ready["layers"] == len(view["layers"]) + len(view["zones"]) and ready["time_complete"] is bool(view["time"]["complete"])
    assert lc["chain"]["next"] == {"code": "download" if ready["ready"] else "fix"}


def test_the_file_received_stage_comes_from_the_export_and_an_edit_takes_the_work_back_to_prepared(work, job):
    c, j = work, job
    exported(c, j)
    lc = chain_of(c, j)
    assert lc["chain"]["stage"] == "file" and lc["chain"]["next"] == {"code": "add_result"} and lc["chain"]["file"] == 1
    (file,) = lc["files"]
    assert file["number"] == 1 and file["current"] is True and file["stage"] == "file" and file["promise"] == "saved"
    assert file["download_url"] == f"/api/vector/{j['id']}/exports/1" and file["downloadable"] is True
    assert c["client"].get(file["download_url"]).status_code == 200
    edit(c, j)
    after = chain_of(c, j)
    assert after["chain"]["stage"] == "prepared" and after["chain"]["edited_after"] == 1                 # the work is not the file's work any more
    assert after["files"][0]["current"] is False and after["files"][0]["stage"] == "file"             # the file keeps its own life


def test_registration_markers_changed_since_the_file_make_the_work_prepared_again(work, job):
    c, j = work, job
    exported(c, j)
    assert pl.get_plan(c["store"], j["id"])["exports"][0]["markers"] is False
    assert c["client"].put(f"/api/plans/{j['id']}/markers", json={"enabled": True}).status_code == 200      # a vector work keeps its status
    assert pl.get_plan(c["store"], j["id"])["status"] == vector_job.ST_EXPORTED
    assert chain_of(c, j)["chain"]["stage"] == "prepared"


def test_a_result_added_for_the_file_is_the_third_stage_and_accepting_it_the_fourth(work, job):
    c, j = work, job
    exported(c, j)
    pair = engrave(c, j)
    c["store"].execute("UPDATE pair SET status='Awaiting check' WHERE id=?", (pair,))
    lc = chain_of(c, j)
    assert lc["chain"]["stage"] == "result" and lc["chain"]["next"] == {"code": "check_result", "pair_id": pair}
    assert [s["state"] for s in lc["chain"]["steps"]] == ["done", "done", "current", "todo"]
    assert lc["files"][0]["results"][0]["pair_id"] == pair and lc["files"][0]["results"][0]["linked_by"] == "time"
    c["store"].execute("UPDATE pair SET status='Accepted' WHERE id=?", (pair,))
    work_errors.after_acceptance(c["store"], pair)
    lc = chain_of(c, j)
    assert lc["chain"]["stage"] == "verified" and lc["files"][0]["results"][0]["linked_by"] == "review"
    assert lc["chain"]["next"] == {"code": "compare", "pair_id": pair, "engraving_id": "eng-1"}
    c["store"].execute("UPDATE pair SET status='Deleted' WHERE id=?", (pair,))                              # a deleted photograph is no result
    assert chain_of(c, j)["chain"]["stage"] == "file"


def test_a_repeat_export_is_a_new_file_and_does_not_inherit_the_verification_of_the_first(work, job):
    c, j = work, job
    exported(c, j)
    accept(c, j)
    assert chain_of(c, j)["chain"]["stage"] == "verified"
    exported(c, j)                                                       # the same work again, nothing edited
    lc = chain_of(c, j)
    assert [f["number"] for f in lc["files"]] == [1, 2]
    assert lc["chain"]["stage"] == "file" and lc["chain"]["file"] == 2 and lc["chain"]["next"] == {"code": "add_result"}
    assert [(f["number"], f["stage"], f["current"]) for f in lc["files"]] == [(1, "verified", False), (2, "file", True)]
    assert lc["files"][1]["results"] == []                                # no result of the first file is counted for the second


def test_an_edit_after_a_verified_file_starts_again_from_prepared_and_the_files_keep_their_stages(work, job):
    c, j = work, job
    exported(c, j)
    accept(c, j)
    edit(c, j)
    lc = chain_of(c, j)
    assert lc["chain"]["stage"] == "prepared" and lc["chain"]["edited_after"] == 1
    assert lc["files"][0]["stage"] == "verified" and lc["files"][0]["current"] is False
    exported(c, j)                                                       # the edited work exported: a file of its own, nothing verified yet
    assert [(f["number"], f["stage"]) for f in chain_of(c, j)["files"]] == [(1, "verified"), (2, "file")]


def test_reopening_the_application_keeps_the_chain(work, job):
    c, j = work, job
    exported(c, j)
    accept(c, j)
    exported(c, j)
    before = chain_of(c, j)
    c["client"].close()
    reopened = TestClient(create_app(c["store"].data_dir))              # a new process over the same data directory
    lc = reopened.get(f"/api/vector/{j['id']}").json()["lifecycle"]
    assert lc == before and lc["chain"]["stage"] == "file" and lc["files"][0]["stage"] == "verified"
    assert reopened.get(f"/api/plans/{j['id']}/lifecycle").json() == before          # the standalone read model agrees with the work's answer
    assert reopened.get(f"/api/plans/{j['id']}").json()["lifecycle"]["chain"]["stage"] == "file"


def test_a_photograph_taken_before_any_file_of_the_work_belongs_to_no_file(work, job):
    c, j = work, job
    exported(c, j)
    pair = engrave(c, j)
    at(c, pair, EARLY, "Awaiting check")
    stamp(c, j, [MID])
    lc = chain_of(c, j)
    assert lc["files"][0]["results"] == [] and [u["pair_id"] for u in lc["unlinked"]] == [pair] and lc["chain"]["stage"] == "file"
    assert lc["chain"]["unlinked"] == 1


def test_a_pair_is_linked_to_the_newest_file_made_at_or_before_it_was_added(work, job):
    c, j = work, job
    exported(c, j)
    exported(c, j)
    exported(c, j)
    stamp(c, j, [EARLY, MID, LATE])
    first, second = engrave(c, j, engraving="eng-1"), engrave(c, j, engraving="eng-2")
    at(c, first, "2026-01-02T12:00:00+00:00", "Awaiting check")
    at(c, second, "2026-01-01T12:00:00+00:00", "Needs correction")
    files = {f["number"]: [r["pair_id"] for r in f["results"]] for f in chain_of(c, j)["files"]}
    assert files == {1: [second], 2: [first], 3: []}


def test_a_plan_exported_before_exports_were_recorded_has_one_unnumbered_file_whose_date_is_unknown(work, job):
    c, j = work, job
    plan = exported(c, j)
    plan["exports"] = []                                                 # the work as an older version stored it: exported, no record
    cv._persist(c["store"], plan, vector_job.ST_EXPORTED, plan["markers_enabled"])
    lc = chain_of(c, j)
    (file,) = lc["files"]
    assert file["number"] == lifecycle.LEGACY and file["recorded"] is False and file["at"] is None and file["downloadable"] is False
    assert lc["chain"]["stage"] == "file" and lc["chain"]["file"] == lifecycle.LEGACY


def plate(c) -> int:
    """A calibration plate of the works' laser: a plain plan, ready to export, that has never had an export record."""
    return pl.create_plate_series(c["store"], c["w"]["setup"][0], "10 20", "40 80", "900", 5, 4, 1, **JOB)[0]["plan_id"]


def test_a_plates_export_is_recorded_and_the_plate_walks_the_same_chain(work):
    c = work
    pid = plate(c)
    before = c["client"].get(f"/api/plans/{pid}").json()
    assert "exports" not in pl.get_plan(c["store"], pid)                  # an old plan: no key at all, and it reads as before
    lc = before["lifecycle"]
    assert lc["chain"]["stage"] == "prepared" and lc["files"] == [] and lc["readiness"]["kind"] == "plain" and lc["readiness"]["ready"] is True
    assert lc["readiness"]["local_only"] is True and lc["readiness"]["seconds"] == before["time"]["seconds"]
    assert c["client"].get(f"/api/plans/{pid}/export.lbrn2").status_code == 200
    plan = pl.get_plan(c["store"], pid)
    (record,) = plan["exports"]
    assert plan["status"] == "Exported" and record["number"] == 1 and record["name"].endswith(".lbrn2") and "path" not in record and record["markers"] is True
    after = c["client"].get(f"/api/plans/{pid}").json()["lifecycle"]
    (file,) = after["files"]
    assert after["chain"]["stage"] == "file" and file["current"] is True and file["downloadable"] is False and file["download_url"] is None
    assert after == c["client"].get(f"/api/plans/{pid}/lifecycle").json()
    assert c["client"].get(f"/api/plans/{pid}/export.lbrn2").status_code == 200       # a repeat is a record of its own
    assert [f["number"] for f in c["client"].get(f"/api/plans/{pid}/lifecycle").json()["files"]] == [1, 2]
    assert pl.get_plan(c["store"], pid)["status"] == "Exported"


def test_a_plain_plan_exported_before_records_were_kept_reads_as_one_unnumbered_file(work):
    c = work
    pid = plate(c)
    c["store"].execute("UPDATE plan SET status='Exported' WHERE id=?", (pid,))
    lc = c["client"].get(f"/api/plans/{pid}/lifecycle").json()
    (file,) = lc["files"]
    assert file["number"] == lifecycle.LEGACY and file["recorded"] is False and lc["chain"]["stage"] == "file"


def test_a_plain_plan_that_is_not_ready_says_why_with_a_code_and_not_prose(work):
    c = work
    pid = plate(c)
    c["store"].execute("UPDATE plan SET status='Superseded' WHERE id=?", (pid,))
    ready = c["client"].get(f"/api/plans/{pid}/lifecycle").json()["readiness"]
    assert ready["ready"] is False and ready["blockers"] == [{"code": "closed"}] and ready["reason"] is None
    c["store"].execute("UPDATE plan SET status='Draft' WHERE id=?", (pid,))
    assert c["client"].get(f"/api/plans/{pid}/lifecycle").json()["readiness"]["blockers"] == [{"code": "draft"}]
    assert c["client"].get("/api/plans/99999/lifecycle").status_code == 404


# -- REQ-003: the file an engraving is compared with ----------------------------------------------------------------------------------------
def review_of(c, j, engraving="eng-1") -> dict:
    return next(r for r in pl.get_plan(c["store"], j["id"])["reviews"] if r["engraving_id"] == engraving)


def test_a_review_names_the_file_it_was_compared_with_and_that_its_promise_was_saved_with_it(work, job):
    c, j = work, job
    exported(c, j)
    accept(c, j)
    review = review_of(c, j)
    assert review["basis"] == {"kind": "saved", "export_number": 1, "exported_at": review["basis"]["exported_at"], "document_version": 1, "ambiguous": []}
    assert review["basis"]["exported_at"] == pl.get_plan(c["store"], j["id"])["exports"][0]["at"]
    shown = c["client"].get(f"/api/vector/{j['id']}").json()
    assert shown["reviews"][0]["basis"]["kind"] == "saved"


def test_a_file_made_after_the_photograph_cannot_take_an_earlier_engraving(work, job):
    """Two files with the same layers tie on every engraving; the one made after the photograph was added cannot have been engraved."""
    c, j = work, job
    exported(c, j)
    exported(c, j)
    stamp(c, j, [EARLY, LATE])
    pair = engrave(c, j)
    at(c, pair, MID)
    work_errors.after_acceptance(c["store"], pair)
    review = review_of(c, j)
    assert review["export_number"] == 1 and review["basis"]["kind"] == "saved" and review["basis"]["ambiguous"] == []


def test_files_that_fit_equally_well_are_named_and_the_newest_made_before_the_photograph_is_chosen(work, job):
    c, j = work, job
    exported(c, j)
    exported(c, j)
    stamp(c, j, [EARLY, MID])
    pair = engrave(c, j)
    at(c, pair, LATE)
    work_errors.after_acceptance(c["store"], pair)
    review = review_of(c, j)
    assert review["export_number"] == 2 and review["basis"]["ambiguous"] == [1]
    assert c["client"].get(f"/api/pairs/{pair}/work-summary").json()["basis"]["ambiguous"] == [1]


def test_measuring_the_engraving_again_after_a_later_export_keeps_the_file_it_was_compared_with(work, job, monkeypatch):
    """The first photograph is gone (measured again), so the time bound alone would let the later file take the engraving: the review pins its file."""
    c, j = work, job
    exported(c, j)
    exported(c, j)
    stamp(c, j, [EARLY, MID])
    first = engrave(c, j)
    at(c, first, "2026-01-01T12:00:00+00:00")
    work_errors.after_acceptance(c["store"], first)
    assert review_of(c, j)["export_number"] == 1
    c["store"].execute("UPDATE pair SET status='Deleted' WHERE id=?", (first,))
    second = engrave(c, j)                                                 # the same engraving, photographed after the second file was made
    at(c, second, LATE)
    assert work_errors._first_photographed(c["store"], "eng-1") == LATE
    work_errors.after_acceptance(c["store"], second)
    review = review_of(c, j)
    assert review["pair_id"] == second and review["export_number"] == 1 and review["basis"]["kind"] == "saved"


def test_a_file_made_before_promises_were_kept_is_a_reconstruction_and_the_review_never_calls_it_the_promise(work, job):
    c, j = work, job
    plan = exported(c, j)
    pair, second = engrave(c, j), engrave(c, j, engraving="eng-2")
    del plan["exports"][-1]["promised"]
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])
    work_errors.after_acceptance(c["store"], pair)
    review = review_of(c, j)
    assert review["basis"]["kind"] == "reconstructed" and review["basis"]["export_number"] == 1 and review["approximate"] is True
    lc = chain_of(c, j)
    assert lc["files"][0]["promise"] == "none"                                          # the file says no promise was saved with it
    assert c["client"].get(f"/api/pairs/{pair}/work-summary").json()["basis"]["kind"] == "reconstructed"
    edit(c, j)                                                                            # recoloured: the reconstruction cannot be made any more
    work_errors.after_acceptance(c["store"], second)
    lost = review_of(c, j, "eng-2")
    assert lost["basis"]["kind"] == "lost" and lost["promise_lost"] is True and lost["rows"] == []


def test_a_work_never_exported_is_compared_with_its_layers_as_they_are_and_says_so(work, job):
    c, j = work, job
    plan = exported(c, j)
    pair = engrave(c, j)
    plan["exports"] = []
    cv._persist(c["store"], plan, "Ready to export", plan["markers_enabled"])
    review = work_errors.review_pair(c["store"], pair)
    assert review["basis"] == {"kind": "reconstructed", "export_number": None, "exported_at": None, "document_version": None, "ambiguous": []}


def test_a_review_made_before_the_basis_was_named_gets_it_from_its_own_fields_and_is_not_rewritten(work, job):
    c, j = work, job
    plan = exported(c, j)
    pair = accept(c, j)
    plan = pl.get_plan(c["store"], j["id"])
    stored = plan["reviews"][0]
    del stored["basis"]
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])
    assert lifecycle.basis_of(plan, stored)["kind"] == "saved" and "basis" not in pl.get_plan(c["store"], j["id"])["reviews"][0]
    assert c["client"].get(f"/api/pairs/{pair}/work-summary").json()["basis"]["export_number"] == 1
    stored["promise_lost"], stored["approximate"] = True, False
    assert lifecycle.basis_of(plan, stored)["kind"] == "lost"
    stored["promise_lost"], stored["approximate"] = False, True
    assert lifecycle.basis_of(plan, stored)["kind"] == "reconstructed"


def test_new_measurements_move_the_current_prediction_and_never_rewrite_what_an_exported_file_promised(work, job):
    c, j = work, job
    ids = palette_ids(c)
    fast = ids[(round(lab(PAPER)[0] - 2), 3000)]
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    exported(c, j)
    promised = json.dumps(pl.get_plan(c["store"], j["id"])["exports"][0]["promised"], sort_keys=True)
    moved(c, j, fast)                                                                    # the palette is now 14 L* from what the file showed
    stored = json.dumps(pl.get_plan(c["store"], j["id"])["exports"][0]["promised"], sort_keys=True)
    pair = engrave(c, j)
    concluded = work_errors.after_acceptance(c["store"], pair)
    after = pl.get_plan(c["store"], j["id"])
    assert json.dumps(after["exports"][0]["promised"], sort_keys=True) == stored != promised          # nothing but the test's own edit touched the promise
    summary = concluded["summary"]
    assert summary["prediction"]["known"] is True and summary["prediction"]["after"]["layers"] >= 1
    assert summary["prediction"]["before"] is None or summary["prediction"]["after"]["layers"] >= summary["prediction"]["before"]["layers"]
    assert chain_of(c, j)["chain"]["stage"] == "verified"                                  # the file is still the file, drifted or not


def test_a_replacement_of_a_current_colour_is_undone_by_one_undo_and_neither_touches_the_files_already_made(work, job):
    """The replacement the result tab offers is an ordinary edit of the work (the tab's «Отменить замену» sends one undo). It changes the
    work, not the file made before: that file's record, its saved promise and its place in the list of files stay as they were."""
    c, j = work, job
    ids = palette_ids(c)
    fast, exact = ids[(round(lab(PAPER)[0] - 2), 3000)], ids[(round(lab(PAPER)[0]), 500)]
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    exported(c, j)
    moved(c, j, fast)
    before = json.dumps(pl.get_plan(c["store"], j["id"])["exports"], sort_keys=True)
    colour = by_rgb(j, PAPER)["index"]
    replaced = colouring(c, j, op="set_colour", colour=colour, entry_id=exact)
    assert by_rgb(replaced, PAPER)["entry_id"] == exact and replaced["undo"] > j["undo"]
    assert chain_of(c, j)["chain"]["stage"] == "prepared" and chain_of(c, j)["chain"]["edited_after"] == 1       # the replacement is an edit after the file
    undone = colouring(c, j, op="undo")
    assert by_rgb(undone, PAPER)["entry_id"] == fast and undone["undo"] == j["undo"] and undone["redo"] == 1
    assert json.dumps(pl.get_plan(c["store"], j["id"])["exports"], sort_keys=True) == before          # the record of the file is what it was
    files = chain_of(c, j)["files"]
    assert [f["number"] for f in files] == [1] and files[0]["promise"] == "saved" and files[0]["current"] is False
    assert colouring(c, j, op="redo")["undo"] == replaced["undo"]                                       # and it can be done again


def test_the_summary_of_an_accepted_result_is_kept_in_the_review_and_told_again_when_the_work_is_opened(work, job):
    c, j = work, job
    exported(c, j)
    pair = engrave(c, j, labs={0: [lab(PAPER)[0] - 9, 0.0, 0.0]})
    concluded = work_errors.after_acceptance(c["store"], pair)
    summary = concluded["summary"]
    assert summary["plan_id"] == j["id"] and summary["pair_id"] == pair and summary["work"] == "Portrait"
    assert summary["result"]["promised"] == summary["result"]["engraved"] and summary["result"]["matched"] == summary["result"]["promised"]
    assert summary["route"] == f"/vector?plan={j['id']}&accepted={pair}"
    assert summary["next"] in ("replace", "compare")
    again = c["client"].get(f"/api/pairs/{pair}/work-summary")
    assert again.status_code == 200 and again.json() == summary
    c["store"].execute("UPDATE pair SET status='Needs correction' WHERE id=?", (pair,))
    assert c["client"].get(f"/api/pairs/{pair}/work-summary").status_code == 404           # only an accepted result has a summary
    assert c["client"].get("/api/pairs/99999/work-summary").status_code == 404


def test_a_remeasure_without_the_acceptance_keeps_what_the_first_acceptance_told(work, job):
    c, j = work, job
    exported(c, j)
    first = engrave(c, j)
    work_errors.after_acceptance(c["store"], first)
    kept = review_of(c, j)["prediction_change"]
    c["store"].execute("UPDATE pair SET status='Deleted' WHERE id=?", (first,))
    second = engrave(c, j, labs={0: [10.0, 0.0, 0.0]})
    work_errors.record(c["store"], second)                                  # what recheck does: the review is made again, the acceptance is not
    review = review_of(c, j)
    assert review["pair_id"] == second and review["prediction_change"] == kept
