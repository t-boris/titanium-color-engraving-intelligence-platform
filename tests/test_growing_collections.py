"""The server side of the growing collections (feature ux-growing-collections-p0): the catalogue of titanium stock records read a page at a
time (REQ-001) with 20, 200 and 2000 records, the history of a knowledge entry read a page at a time and the photographs behind observation
numbers (REQ-002). The plain lists older screens read keep their shape."""
import json

import pytest
from fastapi.testclient import TestClient

import obs
from titanium_platform import knowledge as kn, material_catalogue as mc, provenance, setup as su
from titanium_platform.api.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as c:
        yield c


def fill(store, count: int) -> None:
    """``count`` stock records: grades cycle over four, every grade has many batches (sheets) of its own thickness."""
    grades = ("Grade 2", "Grade 5", "Ti-6Al-4V", None)
    with store.transaction():
        for i in range(count):
            su.save_material(store, f"Лист {i + 1}", batch=f"B-{i + 1:04d}", grade=grades[i % 4], thickness_mm=0.5 + (i % 5) * 0.5,
                             surface="шлифовка" if i % 2 else None, family="Titanium" if i % 7 else "Steel")


# -- the catalogue ----------------------------------------------------------------------------------------------------------------------
def test_the_plain_list_keeps_its_shape_and_order(client):
    for name in ("B", "A", "C"):
        client.post("/api/materials", json={"name": name})
    plain = client.get("/api/materials").json()
    assert [m["name"] for m in plain] == ["B", "A", "C"] and isinstance(plain, list)
    assert set(plain[0]) == {"id", "name", "family", "batch", "grade", "thickness_mm", "surface", "created_at"}     # no field was added to the old shape


@pytest.mark.parametrize("count", [20, 200, 2000])
def test_a_page_of_twenty_comes_out_of_a_catalogue_of_any_size(store, count):
    fill(store, count)
    first = mc.page(store, sort="newest", limit=20)
    assert (len(first["items"]), first["total"], first["all"]) == (20, count, count)
    assert first["items"][0]["name"] == f"Лист {count}"
    # consecutive pages are the whole catalogue, each record once, nothing skipped
    seen = []
    for offset in range(0, count, 20):
        seen += [m["id"] for m in mc.page(store, sort="id", offset=offset, limit=20)["items"]]
    assert seen == list(range(1, count + 1))


def test_search_finds_a_record_by_name_batch_grade_surface_and_thickness_whatever_the_case(store):
    fill(store, 200)
    assert [m["name"] for m in mc.page(store, search="b-0137")["items"]] == ["Лист 137"]
    assert mc.page(store, search="  GRADE   5 ")["total"] == 50                               # case and spacing do not matter; a «5» elsewhere does not match
    assert [m["name"] for m in mc.page(store, search="grade 5 b-0002")["items"]] == ["Лист 2"]   # the phrase runs over the fields in the order of a line
    assert mc.page(store, search="2.5 мм")["total"] == 40                                    # the thickness of a record is searched too
    assert mc.page(store, search="0137")["total"] == 1                                       # a part of a batch number
    nothing = mc.page(store, search="нет такого")
    assert (nothing["total"], nothing["all"]) == (0, 200)                                    # «nothing found» is told from «nothing added»


def test_the_grade_filter_lists_concrete_records_and_counts_what_each_option_would_show(store):
    fill(store, 40)
    page = mc.page(store, grade="grade 2", limit=100)
    assert page["total"] == 10 and {m["grade"] for m in page["items"]} == {"Grade 2"}
    assert len({m["batch"] for m in page["items"]}) == 10                                    # a grade has a record per batch or sheet
    options = dict(page["options"]["grades"])
    assert options["grade 2"] == "Grade 2" and options[mc.NO_GRADE] == "No grade"
    assert page["counts"]["grade"]["grade 2"] == 10 and page["counts"]["grade"][""] == 40     # counts ignore the filter they belong to
    narrowed = mc.page(store, family="steel", limit=100)
    assert narrowed["counts"]["grade"][""] == narrowed["total"] and narrowed["counts"]["family"][""] == 40
    assert mc.page(store, grade=mc.NO_GRADE, limit=100)["total"] == 10


def test_the_order_puts_used_records_first_then_the_newest(store, tmp_path):
    fill(store, 6)
    # nothing used yet: the newest added first
    assert [m["id"] for m in mc.page(store, sort="recent")["items"]] == [6, 5, 4, 3, 2, 1]
    w = obs.setup(store)
    obs.add(store, w, (50, 0, 0), material_id=2)
    first = mc.page(store, sort="recent")["items"]
    assert [m["id"] for m in first][:2] == [2, 6] and first[0]["last_used_at"] and first[1]["last_used_at"] is None
    assert [m["name"] for m in mc.page(store, sort="name")["items"]] == [f"Лист {i}" for i in range(1, 7)]
    thick = [m["thickness_mm"] for m in mc.page(store, sort="thickness")["items"]]
    assert thick == sorted(thick)
    grades = [m["grade"] for m in mc.page(store, sort="grade")["items"]]
    assert grades[-1] is None and grades[:-1] == sorted(g for g in grades if g)                # records with no grade come last
    assert [m["id"] for m in mc.page(store, sort="no such order")["items"]] == [1, 2, 3, 4, 5, 6]


def test_a_record_counts_as_used_by_a_plate_a_session_a_vector_work_and_a_photo_work(store):
    fill(store, 5)
    w = obs.setup(store)
    with store.transaction():
        store.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,data_json,created_at) VALUES ('v','vector','Draft',?,?,0,?,?)",
                      (w["setup"][0], w["setup"][1], json.dumps({"material_id": 3}), "2026-11-01T10:00:00"))
        store.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,data_json,created_at) VALUES ('p','photo','Draft',?,?,0,?,?)",
                      (w["setup"][0], w["setup"][1], json.dumps({"scale": {"material_id": 4}}), "2026-11-02T10:00:00"))
    used = mc.last_used(store)
    assert used[3] == "2026-11-01T10:00:00" and used[4] == "2026-11-02T10:00:00" and 1 not in used
    assert [m["id"] for m in mc.page(store, sort="recent")["items"]][:2] == [4, 3]


def test_a_page_is_asked_over_the_api_and_one_record_by_its_number(client):
    store = client.app.state.store
    fill(store, 45)
    page = client.get("/api/materials", params={"limit": 20, "offset": 20, "sort": "id"}).json()
    assert [m["id"] for m in page["items"]] == list(range(21, 41)) and page["total"] == 45 and page["all"] == 45
    filtered = client.get("/api/materials", params={"limit": 5, "search": "b-0007"}).json()
    assert [m["name"] for m in filtered["items"]] == ["Лист 7"]
    as_list = client.get("/api/materials", params={"search": "b-0007"}).json()
    assert isinstance(as_list, list) and [m["name"] for m in as_list] == ["Лист 7"]              # without ``limit`` the answer is a list still
    assert len(client.get("/api/materials", params={"limit": 5000}).json()["items"]) == 45                 # the cap is 200 a page; here that is every record
    one_row = client.get("/api/materials", params={"limit": 0}).json()
    assert (one_row["limit"], len(one_row["items"])) == (1, 1)                                             # a page holds at least one record
    one = client.get("/api/materials/7").json()
    assert one["name"] == "Лист 7" and "last_used_at" in one
    gone = client.get("/api/materials/9999")
    assert gone.status_code == 404 and gone.json()["error"] == "titanium stock 9999 not found"


def test_a_page_never_exceeds_the_cap_and_a_negative_offset_is_the_start(store):
    fill(store, 260)
    big = mc.page(store, limit=100000, sort="id")
    assert len(big["items"]) == mc.PAGE_MAX and big["total"] == 260
    assert [m["id"] for m in mc.page(store, offset=-5, limit=3, sort="id")["items"]] == [1, 2, 3]
    assert len(mc.page(store, limit=None)["items"]) == 260


# -- the history of a knowledge entry ----------------------------------------------------------------------------------------------------
@pytest.fixture
def entry(store):
    """One knowledge entry with 45 events (so three pages of 20): created, then promoted and questioned in turn."""
    w = obs.setup(store)
    obs.add(store, w, (50, 0, 0))
    kn.refresh(store, *w["setup"])
    kid = kn.list_for_setup(store, *w["setup"])[0]["id"]
    with store.transaction():
        for i in range(44):
            kn._event(store, kid, "questioned" if i % 4 == 0 else "promoted", "measured", "candidate", f"event {i}", [i + 1, i + 2])
    return kid


def test_the_history_is_read_a_page_at_a_time_newest_first_and_nothing_is_lost(store, entry):
    first = kn.history_page(store, entry, limit=20)
    assert (first["total"], first["all"], len(first["items"])) == (45, 45, 20)
    ids = [e["id"] for e in first["items"]]
    assert ids == sorted(ids, reverse=True)
    seen = []
    for offset in (0, 20, 40):
        seen += [e["id"] for e in kn.history_page(store, entry, offset=offset, limit=20)["items"]]
    every = [e["id"] for e in kn.get(store, entry)["history"]]
    assert seen == every[::-1] and len(set(seen)) == 45                                       # the same events, once each, in the order of pages
    oldest = kn.history_page(store, entry, newest_first=False, limit=3)["items"]
    assert [e["type"] for e in oldest][0] == "created" and all(isinstance(e["observation_ids"], list) for e in oldest)


def test_the_history_can_be_narrowed_to_one_kind_of_event_with_counts(store, entry):
    page = kn.history_page(store, entry, event_type="questioned", limit=100)
    assert page["total"] == 11 and {e["type"] for e in page["items"]} == {"questioned"} and page["all"] == 45
    assert page["counts"]["type"]["questioned"] == 11 and page["counts"]["type"][""] == 45 and page["counts"]["type"]["promoted"] == 33


def obs_setup(store, kid):
    row = store.one("SELECT device_id, lens_id FROM knowledge WHERE id=?", (kid,))
    return row["device_id"], row["lens_id"]


def test_an_entry_reports_the_size_of_its_history_and_can_leave_the_events_out(store, entry):
    whole = kn.get(store, entry)
    assert whole["history_total"] == 45 and len(whole["history"]) == 45
    none = kn.get(store, entry, history_limit=0)
    assert none["history_total"] == 45 and none["history"] == []
    newest = kn.get(store, entry, history_limit=3)
    assert [e["id"] for e in newest["history"]] == [e["id"] for e in whole["history"][-3:]]
    listed = kn.list_for_setup(store, *obs_setup(store, entry), history_limit=0)
    assert listed[0]["history"] == [] and listed[0]["history_total"] == 45


def test_the_history_routes(client):
    store = client.app.state.store
    w = obs.setup(store)
    obs.add(store, w, (50, 0, 0))
    kn.refresh(store, *w["setup"])
    kid = kn.list_for_setup(store, *w["setup"])[0]["id"]
    page = client.get(f"/api/knowledge/{kid}/history", params={"limit": 20}).json()
    assert page["total"] == 1 and page["items"][0]["type"] == "created"
    assert client.get(f"/api/knowledge/{kid}", params={"history_limit": 0}).json()["history_total"] == 1
    lens = "unknown" if w["setup"][1] is None else w["setup"][1]
    listed = client.get("/api/knowledge", params={"device_id": w["setup"][0], "lens_id": lens, "history_limit": 0}).json()
    assert listed[0]["history"] == [] and listed[0]["history_total"] == 1
    missing = client.get("/api/knowledge/999/history")
    assert missing.status_code == 404


# -- the photographs behind observation numbers ----------------------------------------------------------------------------------------
def test_observation_numbers_resolve_to_their_photographs_in_order_and_none_is_dropped(store):
    w = obs.setup(store)
    a = obs.add(store, w, (50, 0, 0), evidence={"layer_name": "C01"})
    b = obs.add(store, w, (51, 0, 0))
    refs = provenance.observation_refs(store, [b, 9999, a, b])
    assert [r["id"] for r in refs] == [b, 9999, a]                                           # the order asked, without repeats, the unknown one kept
    assert refs[0]["pair_id"] and refs[0]["photo_name"] == "p.raw" and refs[0]["status"] == "Accepted"
    assert refs[1]["pair_id"] is None
    assert refs[2]["layer_name"] == "C01"
    assert provenance.observation_refs(store, []) == []


def test_the_observation_route_reads_a_list_of_numbers_and_ignores_junk(client):
    store = client.app.state.store
    w = obs.setup(store)
    a = obs.add(store, w, (50, 0, 0))
    got = client.get("/api/observations/refs", params={"ids": f"{a}, x, ,{a}"}).json()
    assert [r["id"] for r in got] == [a] and got[0]["pair_id"]
    assert client.get("/api/observations/refs").json() == []
    many = client.get("/api/observations/refs", params={"ids": ",".join(str(i) for i in range(1, 500))}).json()
    assert len(many) == provenance.REFS_MAX
