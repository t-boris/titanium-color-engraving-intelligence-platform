"""Renaming a vector work (feature vector-detail-and-colour-control, 0.10.0, REQ-055, DEC-086): only the name changes. A rename is not an edit of
the document: no history entry, no document version, nothing to undo, the files exported earlier keep their names, and it writes one audit row."""
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from test_vector_list import copy_of, stored, thumb, traced, works    # noqa: F401  (helpers of the list tests)
from test_vector_work import PAPER, RED, by_rgb, colouring, create, job, work    # noqa: F401  (fixtures)
from titanium_platform import conversion as cv, plans as pl

UI = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui"


def rename(c, j, name, **kw):
    return c["client"].post(f"/api/vector/{j['id']}/rename", json={"name": name}, **kw)


def audit_rows(c) -> list[dict]:
    return [json.loads(r["detail_json"]) for r in c["store"].query("SELECT detail_json FROM audit WHERE action='vector_work_renamed' ORDER BY id")]


def view(c, j) -> dict:
    return c["client"].get(f"/api/vector/{j['id']}").json()


def test_a_rename_changes_the_name_everywhere_it_is_shown(work, job):
    c, j = work, job
    r = rename(c, j, "Imma + Boris")
    assert r.status_code == 200 and r.json() == {"id": j["id"], "name": "Imma + Boris"}
    assert view(c, j)["name"] == "Imma + Boris" and works(c)[0]["name"] == "Imma + Boris"
    assert next(p for p in c["client"].get("/api/plans").json() if p["id"] == j["id"])["name"] == "Imma + Boris"
    assert c["client"].get(f"/api/plans/{j['id']}").json()["name"] == "Imma + Boris" and stored(c, j)["name"] == "Imma + Boris"


def test_the_name_is_stripped_and_any_text_is_a_name(work, job):
    c, j = work, job
    assert rename(c, j, "   Витраж №1 — «тест»  ").json()["name"] == "Витраж №1 — «тест»"
    assert view(c, j)["name"] == "Витраж №1 — «тест»"
    long = "Длинное название " * 40
    assert rename(c, j, long).json()["name"] == long.strip() and view(c, j)["name"] == long.strip()          # no cap, as at creation
    other = create(c, name="Витраж №1 — «тест»").json()
    assert rename(c, other, long.strip()).status_code == 200 and [w["name"] for w in works(c)] == [long.strip()] * 2        # the same name twice is fine


def test_a_rename_is_not_an_edit_of_the_document(work, job):
    c, j = work, job
    colouring(c, j, op="assign", mode="random")
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, RED)["index"], entry_id=by_rgb(j, PAPER)["entry_id"])
    assert c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").status_code == 200
    before, listed, etag = view(c, j), works(c)[0], thumb(c, j).headers["etag"]
    assert before["undo"] >= 2 and before["exports"]
    assert rename(c, j, "Another name").status_code == 200
    after = view(c, j)
    assert after["name"] == "Another name" and after["history"] == before["history"] and len(after["history"]) == len(before["history"])
    assert (after["document"]["version"], after["undo"], after["redo"], after["exports"]) == (before["document"]["version"], before["undo"], before["redo"], before["exports"])
    assert {k: v for k, v in after.items() if k != "name"} == {k: v for k, v in before.items() if k != "name"}
    now = works(c)[0]
    assert now["updated_at"] == listed["updated_at"] and now["version"] == listed["version"] and {k: v for k, v in now.items() if k != "name"} == {k: v for k, v in listed.items() if k != "name"}
    assert thumb(c, j).headers["etag"] == etag                                                                 # the picture does not depend on the name
    again = colouring(c, j, op="undo")                                                                         # undo goes on with the colouring, the name stays
    assert again["name"] == "Another name" and again["undo"] == before["undo"] - 1 and again["redo"] == 1


def test_a_rename_writes_one_audit_row_and_naming_it_as_it_is_writes_nothing(work, job):
    c, j = work, job
    assert audit_rows(c) == []
    assert rename(c, j, "Portrait").status_code == 200 and rename(c, j, "  Portrait ").status_code == 200       # the name it already has
    assert audit_rows(c) == []
    assert rename(c, j, "Second").status_code == 200
    assert audit_rows(c) == [{"plan_id": j["id"], "old_name": "Portrait", "new_name": "Second"}]
    assert rename(c, j, "Third").status_code == 200
    assert audit_rows(c)[-1] == {"plan_id": j["id"], "old_name": "Second", "new_name": "Third"} and len(audit_rows(c)) == 2


@pytest.mark.parametrize("name", ["", "   ", "\t\n", 7, ["x"], False, None])
def test_a_rename_needs_a_real_name(work, job, name):
    c, j = work, job
    r = rename(c, j, name)
    assert r.status_code == 422 and r.json()["error"] == "give the plan a name"
    assert view(c, j)["name"] == "Portrait" and audit_rows(c) == []


@pytest.mark.parametrize("send", [lambda c, url: c.post(url), lambda c, url: c.post(url, json={}), lambda c, url: c.post(url, json={"title": "x"})])
def test_a_rename_without_a_name_in_the_body_is_refused_the_same_way(work, job, send):
    r = send(work["client"], f"/api/vector/{job['id']}/rename")
    assert r.status_code == 422 and r.json()["error"] == "give the plan a name" and view(work, job)["name"] == "Portrait"


def test_the_message_of_a_refused_rename_is_translated_in_the_interface():
    assert "/^give the plan a name/i" in (UI / "i18n-more.js").read_text(encoding="utf-8")


def test_an_unknown_or_deleted_work_is_not_found_and_a_plan_of_another_kind_is_refused(work, job):
    c, j = work, job
    r = c["client"].post("/api/vector/9999/rename", json={"name": "x"})
    assert r.status_code == 404
    assert c["client"].delete(f"/api/plans/{j['id']}").status_code == 204
    assert rename(c, j, "Gone").status_code == 404 and audit_rows(c) == []
    plate = cv.save_plan(c["store"], None, name="A plate", mode=pl.MODE_PLATE, status="Draft", device_id=c["w"]["setup"][0], lens_id=c["w"]["setup"][1],
                         markers=False, identifier="PLATE-3", band_count=None, data={})
    r = c["client"].post(f"/api/vector/{plate}/rename", json={"name": "Renamed plate"})
    assert r.status_code == 422 and r.json()["error"] == "this is not a vector job" and stored(c, {"id": plate})["name"] == "A plate"


def test_a_traced_work_is_renamed_too(work):
    c = work
    old = traced(c, "Lines", "line")
    assert rename(c, old, "Lines, thin").status_code == 200
    assert view(c, old)["name"] == "Lines, thin" and works(c)[0]["name"] == "Lines, thin" and len(view(c, old)["history"]) == len(old["history"])


def test_a_file_exported_before_keeps_its_name_and_the_next_one_gets_the_new_name(work, job):
    c, j = work, job
    first = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert first.status_code == 200 and quote("Portrait") in first.headers["content-disposition"]
    assert rename(c, j, "Новое имя").status_code == 200
    assert [e["name"] for e in view(c, j)["exports"]] == ["Portrait.lbrn2"]                                  # the saved file is as it was saved
    assert c["client"].get(f"/api/vector/{j['id']}/exports/1").content == first.content
    second = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert second.status_code == 200 and quote("Новое имя") in second.headers["content-disposition"]
    assert [e["name"] for e in view(c, j)["exports"]] == ["Portrait.lbrn2", "Новое имя.lbrn2"]
    assert c["client"].get(f"/api/vector/{j['id']}/exports/1").headers["content-disposition"].count(quote("Portrait")) >= 1


def test_a_copy_made_after_a_rename_is_named_after_the_new_name_and_renaming_a_copy_leaves_the_original(work, job):
    c, j = work, job
    assert rename(c, j, "Imma").status_code == 200
    copy = copy_of(c, j)
    assert copy["name"] == "Imma (копия)"
    assert rename(c, copy, "Imma, blue").status_code == 200
    assert view(c, copy)["name"] == "Imma, blue" and view(c, j)["name"] == "Imma"
    assert [w["name"] for w in works(c)] == ["Imma, blue", "Imma"]
    assert rename(c, j, "Imma, red").status_code == 200 and view(c, copy)["name"] == "Imma, blue"
