"""The shared catalog of works (feature ux-work-catalog-p0, REQ-001, REQ-002; I-1, I-3, I-5, I-7): one read-only list over the vector works and the
photo engraving works that creates no work, changes no owner and no id, and keeps a mixed work one document. Run on synthetic plan rows for the
rules (types, states, missing data, search, counts, order, 20 / 200 / 2000 works, the way back to a work) and on real works for the owners'
routes the catalog points to."""
import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from test_experiments import set_status, work_pair
from titanium_platform import catalog, conversion as cv, devices, experiments, lenses, plans as pl, setup as su
from titanium_platform.api.app import create_app

OLD, MID, NEW = "2026-10-01T10:00:00+00:00", "2026-10-15T10:00:00+00:00", "2026-10-30T10:00:00+00:00"


def equip(app) -> dict:
    """The equipment of a workshop for the works to refer to: two lasers, two lenses and two titanium stocks, and no works."""
    store = app.state.store
    store.set_setting("allow_non_raw_photos", True)
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")
    pl.save_marker_layer_settings(store, 20, 60, 300)
    lasers = [devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name=name, serial=serial) for name, serial in (("Laser Alpha", "A-1"), ("Laser Beta", "B-1"))]
    lens = [lenses.create_lens(store, name, 174, 170) for name in ("F-Theta 175", "F-Theta 254")]
    stock = [su.save_material(store, name, grade=grade, thickness_mm=1.0, surface="brushed") for name, grade in (("Sheet two", "Grade 2"), ("Sheet five", "Grade 5"))]
    return {"store": store, "laser": lasers[0], "lasers": lasers, "lens": lens, "stock": stock, "material": stock[0]}


@pytest.fixture
def shop(tmp_path):
    """A workshop with the equipment of :func:`equip` and no works."""
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        yield {"client": client, **equip(app)}
    app.state.store.close()


def add_vector(shop, name="Work", *, updated=OLD, zones=0, texts=0, exports=0, size=(60, 40), laser=0, lens=0, material=0, raw=None, status="Draft") -> int:
    """A vector work as the plan table holds it: the facts of its data the catalog reads, and nothing else."""
    data = raw if raw is not None else {"strategy": "photo", "size_mm": {"width": size[0], "height": size[1]}, "document_version": 2,
                                        "history": [{"version": 1, "op": {"op": "trace"}, "at": OLD}, {"version": 2, "op": {"op": "copy"}, "at": updated}] if updated else [],
                                        "colouring": {"photo": [{"number": n + 1} for n in range(zones)], "texts": [{"id": f"t{n}"} for n in range(texts)]},
                                        "exports": [{"number": n + 1} for n in range(exports)], "material_id": None if material is None else shop["stock"][material]["id"]}
    return cv.save_plan(shop["store"], None, name=name, mode=pl.MODE_VECTOR, status=status, device_id=shop["lasers"][laser]["id"],
                        lens_id=None if lens is None else shop["lens"][lens]["id"], markers=False, identifier=f"V-{name}-{updated}", band_count=None, data=data)


def add_photo(shop, name="Photo", *, updated=OLD, texts=0, size=(240, 120), width=60, laser=0, lens=0, material=0, confirmed=False, raw=None) -> int:
    data = raw if raw is not None else {"image_size": list(size), "width_mm": width, "updated_at": updated, "texts": [{"id": f"t{n}"} for n in range(texts)],
                                        "scale": {"material_id": None if material is None else shop["stock"][material]["id"]},
                                        "evidence_source": {"confirmed": {"name": "x.lbrn2"}} if confirmed else None}
    return cv.save_plan(shop["store"], None, name=name, mode=pl.MODE_PHOTO_WORK, status="Draft", device_id=shop["lasers"][laser]["id"],
                        lens_id=None if lens is None else shop["lens"][lens]["id"], markers=False, identifier=f"P-{name}-{updated}", band_count=None, data=data)


def listed(shop, **query) -> dict:
    answer = shop["client"].get("/api/works", params=query)
    assert answer.status_code == 200, answer.text
    return answer.json()


def names(answer) -> list[str]:
    return [item["name"] for item in answer["items"]]


def everything(store) -> str:
    """Every row of every table, as one digest: whatever a read leaves unchanged leaves it unchanged."""
    digest = hashlib.sha256()
    for table in sorted(r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")):
        for row in store.query(f"SELECT * FROM {table} ORDER BY 1"):
            digest.update(repr(tuple(row)).encode())
    return digest.hexdigest()


# -- what an entry says ---------------------------------------------------------------------------------------------------------------------
def test_the_catalog_lists_both_kinds_as_one_list_newest_first_with_what_the_row_shows(shop):
    traced = add_vector(shop, "Traced", updated=OLD, zones=0)
    mixed = add_vector(shop, "Mixed", updated=MID, zones=2, texts=1, exports=1, size=(100.456, 50), laser=1, lens=1, material=1)
    photo = add_photo(shop, "Girl", updated=NEW, size=(240, 120), width=60)
    answer = listed(shop)
    assert [item["id"] for item in answer["items"]] == [photo, mixed, traced] and answer["total"] == answer["all"] == 3
    girl, both, plain = answer["items"]
    assert (girl["kind"], girl["type"], girl["key"], girl["open"], girl["base"]) == ("photo", "photo", f"photo-{photo}", f"/photo-engraving?work={photo}", "/photo-works")
    assert (girl["width_mm"], girl["height_mm"], girl["updated_at"]) == (60, 30, NEW)
    assert girl["thumb"].startswith(f"/api/photo-works/{photo}/thumb.png?v=")
    assert (both["kind"], both["type"], both["key"], both["open"], both["base"]) == ("vector", "mixed", f"vector-{mixed}", f"/vector?plan={mixed}", "/vector")
    assert (both["zones"], both["texts"], both["width_mm"], both["height_mm"], both["state"]) == (2, 1, 100.46, 50, "exported")
    assert both["thumb"].startswith(f"/api/vector/{mixed}/thumb.png?v=2-2026-10-15")
    assert (both["laser"], both["lens"], both["material"]) == ({"id": shop["lasers"][1]["id"], "name": "Laser Beta"}, {"id": shop["lens"][1]["id"], "name": "F-Theta 254"},
                                                              {"id": shop["stock"][1]["id"], "name": "Sheet five"})
    assert (plain["type"], plain["zones"], plain["state"], plain["missing"], plain["broken"]) == ("vector", 0, "prepared", [], False)


def test_a_mixed_work_is_one_entry_with_its_zones_and_inscriptions_and_a_photo_work_with_lettering_stays_a_photo_work(shop):
    mixed = add_vector(shop, "Mixed", zones=3, texts=2)
    lettered = add_photo(shop, "Lettered", texts=2)
    inscribed = add_vector(shop, "Text only", zones=0, texts=2)
    answer = listed(shop)
    assert sorted(item["id"] for item in answer["items"]) == sorted([mixed, lettered, inscribed]) and answer["total"] == 3          # none is listed twice
    by_id = {item["id"]: item for item in answer["items"]}
    assert (by_id[mixed]["type"], by_id[mixed]["zones"], by_id[mixed]["texts"]) == ("mixed", 3, 2)
    assert (by_id[lettered]["type"], by_id[lettered]["texts"]) == ("photo", 2)
    assert by_id[inscribed]["type"] == "vector"                                  # inscriptions alone do not make a work mixed
    assert listed(shop, type="mixed")["total"] == 1 and listed(shop, type="photo")["total"] == 1 and listed(shop, type="vector")["total"] == 1


def test_a_deleted_work_and_other_plans_are_not_works(shop):
    kept = add_vector(shop, "Kept")
    gone = add_vector(shop, "Gone")
    cv.save_plan(shop["store"], None, name="A plate", mode=pl.MODE_PLATE, status="Draft", device_id=shop["lasers"][0]["id"], lens_id=None,
                 markers=False, identifier="PLATE-1", band_count=None, data={})
    assert shop["client"].delete(f"/api/plans/{gone}").status_code == 204
    answer = listed(shop)
    assert [item["id"] for item in answer["items"]] == [kept] and answer["all"] == 1


# -- the catalog creates nothing and changes no owner or id ---------------------------------------------------------------------------------
def test_listing_searching_and_opening_an_entry_change_nothing_and_create_no_work(shop):
    add_vector(shop, "Mixed", zones=1, texts=1)
    add_photo(shop, "Photo")
    add_vector(shop, "Broken", raw={})
    before = everything(shop["store"])
    rows = shop["store"].one("SELECT COUNT(*) AS n FROM plan")["n"]
    for query in ({}, {"q": "mixed"}, {"type": "photo"}, {"sort": "name", "offset": 1, "limit": 1}, {"laser": "none"}, {"through": "photo-2"}):
        assert shop["client"].get("/api/works", params=query).status_code == 200
    for item in listed(shop)["items"]:
        assert shop["client"].get(f"/api/works/{item['key']}").json() == item
    assert everything(shop["store"]) == before and shop["store"].one("SELECT COUNT(*) AS n FROM plan")["n"] == rows == 3


def test_a_work_keeps_its_id_and_owner_the_entries_ids_are_the_plan_ids_of_their_modes(shop):
    ids = [add_vector(shop, "V1"), add_photo(shop, "P1"), add_vector(shop, "V2"), add_photo(shop, "P2")]
    rows = {r["id"]: r["mode"] for r in shop["store"].query("SELECT id, mode FROM plan")}
    answer = listed(shop)
    assert sorted(item["id"] for item in answer["items"]) == sorted(ids)
    for item in answer["items"]:
        assert rows[item["id"]] == (pl.MODE_VECTOR if item["kind"] == "vector" else pl.MODE_PHOTO_WORK)
    assert len({item["key"] for item in answer["items"]}) == len(ids) and len({item["id"] for item in answer["items"]}) == len(ids)


# -- identity: ids of two kinds ------------------------------------------------------------------------------------------------------------
def test_two_sources_that_number_their_works_apart_stay_two_entries_and_the_same_key_twice_is_one():
    def entry(kind, plan_id, name):
        return {"key": catalog.key_of(kind, plan_id), "id": plan_id, "kind": kind, "name": name}
    merged = catalog.merge([entry("vector", 5, "vector five"), entry("vector", 6, "vector six")], [entry("photo", 5, "photo five"), entry("vector", 5, "the same key again")])
    assert [e["name"] for e in merged] == ["vector five", "vector six", "photo five"]              # id 5 of two kinds: two works; vector-5 twice: one
    assert len({e["key"] for e in merged}) == 3


def test_a_key_finds_only_a_work_of_its_own_kind_and_a_bare_id_finds_the_one_work_that_has_it(shop):
    vector, photo = add_vector(shop, "V"), add_photo(shop, "P")
    client = shop["client"]
    assert client.get(f"/api/works/vector-{vector}").json()["id"] == vector and client.get(f"/api/works/photo-{photo}").json()["id"] == photo
    wrong = client.get(f"/api/works/photo-{vector}")                                           # the id exists, but not as a photo work
    assert wrong.status_code == 404 and wrong.json()["error"] == f"plan {vector} not found"
    assert client.get(f"/api/works/{photo}").json()["key"] == f"photo-{photo}" and client.get(f"/api/works/{vector}").json()["key"] == f"vector-{vector}"
    for key in ("vector-999", "nonsense", "vector-", "plate-1"):
        missing = client.get(f"/api/works/{key}")
        assert missing.status_code == 404 and missing.json()["kind"] == "not_found" and missing.json()["error"].endswith("not found"), key


# -- missing data ----------------------------------------------------------------------------------------------------------------------------
def test_a_work_with_missing_data_stays_in_the_list_and_says_what_is_missing(shop):
    nameless = add_vector(shop, "  ")
    no_size = add_vector(shop, "No size", raw={"strategy": "photo", "history": [{"at": MID}], "material_id": shop["stock"][0]["id"]})
    no_date = add_photo(shop, "No date", raw={"image_size": [100, 50], "width_mm": 40, "scale": {"material_id": shop["stock"][0]["id"]}})
    no_material = add_photo(shop, "No material", updated=MID, material=None, lens=None)
    unknown_material = add_vector(shop, "Gone material", raw={"strategy": "photo", "size_mm": {"width": 10, "height": 10}, "history": [{"at": MID}], "material_id": 9999})
    junk = add_photo(shop, "Junk sizes", raw={"image_size": [0, "x"], "width_mm": "wide", "updated_at": 5, "scale": []})
    by_id = {item["id"]: item for item in listed(shop)["items"]}
    assert by_id[nameless]["name"] == f"Work #{nameless}"
    assert (by_id[no_size]["width_mm"], by_id[no_size]["height_mm"], by_id[no_size]["missing"]) == (None, None, ["size"])
    assert by_id[no_size]["updated_at"] == MID
    assert by_id[no_date]["updated_at"] == by_id[no_date]["created_at"] and by_id[no_date]["missing"] == []     # the creation time stands in for the date
    assert (by_id[no_material]["material"], by_id[no_material]["lens"], by_id[no_material]["missing"]) == (None, None, ["material"])   # no lens is "unknown", not a gap
    assert by_id[unknown_material]["material"] == {"id": 9999, "name": None} and by_id[unknown_material]["missing"] == []
    assert (by_id[junk]["width_mm"], by_id[junk]["height_mm"]) == (None, None) and "size" in by_id[junk]["missing"] and by_id[junk]["updated_at"] == by_id[junk]["created_at"]
    assert listed(shop)["total"] == 6


def test_a_work_whose_data_cannot_be_read_is_listed_as_broken_instead_of_stopping_the_list(shop):
    good = add_vector(shop, "Good")
    bad = cv.save_plan(shop["store"], None, name="Damaged", mode=pl.MODE_VECTOR, status="Draft", device_id=shop["lasers"][0]["id"], lens_id=None, markers=False,
                       identifier="V-bad", band_count=None, data={})
    shop["store"].execute("UPDATE plan SET data_json=? WHERE id=?", ("{not json", bad))
    listing = {item["id"]: item for item in listed(shop)["items"]}
    assert listing[bad]["broken"] is True and listing[bad]["name"] == "Damaged" and listing[bad]["width_mm"] is None and listing[good]["broken"] is False
    assert listing[bad]["laser"]["name"] == "Laser Alpha"                                           # the row's own columns still speak
    assert listed(shop)["total"] == 2 and shop["client"].get(f"/api/works/vector-{bad}").json()["broken"] is True


def test_the_operations_of_a_work_that_is_gone_answer_not_found_in_the_words_the_screen_translates(shop):
    gone = add_photo(shop, "Gone")
    shop["store"].execute("DELETE FROM plan WHERE id=?", (gone,))
    client = shop["client"]
    for answer in (client.post(f"/api/photo-works/{gone}/rename", json={"name": "x"}), client.post(f"/api/photo-works/{gone}/copy", json={}),
                   client.delete(f"/api/plans/{gone}")):
        assert answer.status_code == 404 and answer.json()["error"] == f"plan {gone} not found", answer.text


def test_a_work_with_no_date_is_last_whichever_way_the_dates_are_sorted(shop):
    dated_old, dated_new = add_vector(shop, "Old", updated=OLD), add_vector(shop, "New", updated=NEW)
    shop["store"].execute("UPDATE plan SET created_at='' WHERE id=?", (dated_old,))       # a row without a creation time either
    undated = add_vector(shop, "Undated", updated=None)
    shop["store"].execute("UPDATE plan SET created_at='' WHERE id=?", (undated,))
    for sort, expected in (("modified", ["New", "Old", "Undated"]), ("oldest", ["Old", "New", "Undated"])):
        assert names(listed(shop, sort=sort)) == expected, sort


# -- state -----------------------------------------------------------------------------------------------------------------------------------
def test_the_state_follows_the_files_handed_out_and_the_photographs_of_the_engraving():
    assert [catalog.state_of(*args) for args in ((0, 0, 0), (2, 0, 0), (0, 1, 0), (2, 3, 0), (0, 1, 1), (1, 2, 2))] == [
        "prepared", "exported", "result", "result", "checked", "checked"]


def test_a_photographed_work_says_so_and_goes_back_when_the_photograph_is_deleted(shop):
    prepared = add_vector(shop, "Prepared")
    exported = add_vector(shop, "Exported", exports=1)
    pinned = add_photo(shop, "Pinned", confirmed=True)
    photographed = add_vector(shop, "Photographed")
    accepted = add_photo(shop, "Accepted")
    first = work_pair(shop, photographed, 3)
    second = work_pair(shop, accepted, 4)
    set_status(shop["store"], second, "Accepted")
    states = {item["name"]: (item["state"], item["checks"]) for item in listed(shop)["items"]}
    assert states == {"Prepared": ("prepared", 0), "Exported": ("exported", 0), "Pinned": ("exported", 0), "Photographed": ("result", 1), "Accepted": ("checked", 1)}
    set_status(shop["store"], first, "Deleted")
    assert {item["name"]: item["state"] for item in listed(shop)["items"]}["Photographed"] == "prepared"
    assert prepared and exported and pinned


# -- search ------------------------------------------------------------------------------------------------------------------------------------
def test_search_finds_every_word_in_any_order_and_case_in_the_name_the_equipment_and_the_number(shop):
    portrait = add_vector(shop, "Anna portrait", laser=0, lens=0, material=0)
    landscape = add_photo(shop, "Landscape", laser=1, lens=1, material=1)
    nameless = add_vector(shop, "Other", laser=1, lens=None, material=0)
    for query, expected in (("portrait", ["Anna portrait"]), ("PORTRAIT anna", ["Anna portrait"]), ("anna   portrait", ["Anna portrait"]), ("beta", ["Other", "Landscape"]),
                            ("f-theta 254", ["Landscape"]), ("sheet five", ["Landscape"]), ("sheet five beta", ["Landscape"]), ("sheet", ["Other", "Landscape", "Anna portrait"]), (f"№{landscape}", ["Landscape"]), ("portrait landscape", []),
                            ("no match", []), ("", ["Other", "Landscape", "Anna portrait"])):
        assert sorted(names(listed(shop, q=query, sort="name"))) == sorted(expected), query
    assert portrait and nameless


# -- filters and counts ------------------------------------------------------------------------------------------------------------------------
def build_mixed_shop(shop):
    add_vector(shop, "v-a0", laser=0, lens=0, material=0, updated="2026-10-01T00:00:00+00:00")
    add_vector(shop, "v-a1", laser=0, lens=1, material=0, updated="2026-10-02T00:00:00+00:00")
    add_vector(shop, "m-b0", laser=1, lens=0, material=1, zones=1, updated="2026-10-03T00:00:00+00:00")
    add_photo(shop, "p-a0", laser=0, lens=0, material=0, updated="2026-10-04T00:00:00+00:00")
    add_photo(shop, "p-b1", laser=1, lens=1, material=1, updated="2026-10-05T00:00:00+00:00")
    add_photo(shop, "p-none", laser=1, lens=None, material=None, updated="2026-10-06T00:00:00+00:00")


def test_the_filters_narrow_the_list_together_and_a_value_none_finds_the_works_that_have_none(shop):
    build_mixed_shop(shop)
    laser_a, laser_b = (str(x["id"]) for x in shop["lasers"])
    lens_0, material_1 = str(shop["lens"][0]["id"]), str(shop["stock"][1]["id"])
    assert sorted(names(listed(shop, laser=laser_a))) == ["p-a0", "v-a0", "v-a1"]
    assert sorted(names(listed(shop, laser=laser_b, type="photo"))) == ["p-b1", "p-none"]
    assert sorted(names(listed(shop, lens=lens_0))) == ["m-b0", "p-a0", "v-a0"]
    assert names(listed(shop, lens="none")) == ["p-none"] and names(listed(shop, material="none")) == ["p-none"]
    assert sorted(names(listed(shop, material=material_1, laser=laser_b))) == ["m-b0", "p-b1"]
    assert names(listed(shop, type="mixed", q="b0")) == ["m-b0"]
    assert listed(shop, type="vector", laser=laser_b)["total"] == 0 and listed(shop, laser="99999")["total"] == 0
    assert listed(shop, type="not-a-type")["total"] == 0


def test_the_count_of_a_value_is_what_choosing_it_would_show_with_the_search_and_the_other_filters_as_they_are(shop):
    build_mixed_shop(shop)
    laser_a, laser_b = (str(x["id"]) for x in shop["lasers"])
    nothing = listed(shop)
    assert nothing["counts"]["type"] == {"": 6, "vector": 2, "mixed": 1, "photo": 3} and nothing["counts"]["laser"] == {"": 6, laser_a: 3, laser_b: 3}
    assert nothing["counts"]["lens"]["none"] == 1 and nothing["counts"]["material"]["none"] == 1
    narrowed = listed(shop, type="photo", laser=laser_a)
    assert narrowed["total"] == 1
    assert narrowed["counts"]["type"] == {"": 3, "vector": 2, "photo": 1}                    # the type counts ignore the type filter, keep the laser
    assert narrowed["counts"]["laser"] == {"": 3, laser_a: 1, laser_b: 2}                      # the laser counts ignore the laser filter, keep the type
    searched = listed(shop, q="b")                                                           # "b": m-b0, p-b1, and the names that hold a "b"
    for name in ("type", "laser", "lens", "material"):
        assert narrowed["counts"][name][""] == sum(v for k, v in narrowed["counts"][name].items() if k != ""), name
    assert searched["counts"]["type"][""] == searched["total"]


def test_the_facets_offer_the_equipment_the_works_use_by_name_and_none_when_a_work_has_none(shop):
    build_mixed_shop(shop)
    facets = listed(shop, type="photo")["facets"]                                              # the offer does not shrink with the filters
    assert facets["type"] == ["vector", "mixed", "photo", "card"]
    assert [f["name"] for f in facets["laser"]] == ["Laser Alpha", "Laser Beta"]
    assert facets["lens"][-1] == {"value": "none", "name": None} and [f["name"] for f in facets["lens"][:-1]] == ["F-Theta 175", "F-Theta 254"]
    assert facets["material"][-1] == {"value": "none", "name": None}
    assert listed(shop, laser=str(shop["lasers"][0]["id"]))["facets"] == listed(shop)["facets"] == facets


# -- order and pages ----------------------------------------------------------------------------------------------------------------------------
def test_sorting_by_change_both_ways_and_by_name(shop):
    for name, when in (("b", NEW), ("a", OLD), ("c", MID)):
        add_vector(shop, name, updated=when)
    assert names(listed(shop)) == ["b", "c", "a"] and names(listed(shop, sort="oldest")) == ["a", "c", "b"] and names(listed(shop, sort="name")) == ["a", "b", "c"]
    assert names(listed(shop, sort="no-such-sort")) == ["b", "c", "a"]                         # an unknown sort is the default one


def test_works_that_changed_at_the_same_moment_keep_one_order_so_the_pages_skip_and_repeat_none(shop):
    for n in range(45):
        (add_vector if n % 2 else add_photo)(shop, f"Same {n:02d}", updated=MID)
    seen = []
    for sort in ("modified", "oldest", "name"):
        keys = []
        for offset in (0, 20, 40):
            page = listed(shop, sort=sort, offset=offset, limit=20)
            assert page["total"] == 45
            keys += [item["key"] for item in page["items"]]
        assert len(keys) == 45 and len(set(keys)) == 45, sort
        seen.append(keys)
    assert seen[0] == list(reversed(seen[1]))                                     # one total order, read both ways
    assert len(listed(shop, offset=40, limit=20)["items"]) == 5 and listed(shop, offset=45)["items"] == []


@pytest.mark.parametrize("count", [20, 200, 2000])
def test_a_collection_of_any_size_is_paged_without_gaps_or_repeats_and_its_counts_add_up(shop, count):
    store = shop["store"]
    with store.transaction():
        for n in range(count):
            body = {"strategy": "photo", "size_mm": {"width": 50, "height": 30}, "document_version": 1, "history": [{"at": f"2026-10-{1 + n % 28:02d}T{n % 24:02d}:00:00+00:00"}],
                    "colouring": {"photo": [{"number": 1}] if n % 7 == 0 else []}, "exports": [], "material_id": shop["stock"][n % 2]["id"]}
            photo = {"image_size": [200, 100], "width_mm": 50, "updated_at": f"2026-10-{1 + n % 28:02d}T{n % 24:02d}:30:00+00:00", "texts": [], "scale": {"material_id": shop["stock"][n % 2]["id"]}}
            cv.save_plan(store, None, name=f"Work {n}", mode=pl.MODE_VECTOR if n % 3 else pl.MODE_PHOTO_WORK, status="Draft", device_id=shop["lasers"][n % 2]["id"],
                         lens_id=None if n % 5 == 0 else shop["lens"][n % 2]["id"], markers=False, identifier=f"W-{n}", band_count=None, data=body if n % 3 else photo)
    first = listed(shop)
    assert len(first["items"]) == min(20, count) and first["total"] == first["all"] == count                 # the first portion is at most 20
    keys, offset = [], 0
    while offset < count:
        page = listed(shop, offset=offset, limit=20)
        keys += [item["key"] for item in page["items"]]
        offset += 20
    assert len(keys) == count and len(set(keys)) == count
    assert keys == [item["key"] for item in sorted(catalog.all_works(store), key=lambda e: (e["updated_at"], e["id"], e["kind"]), reverse=True)]
    assert first["counts"]["type"][""] == count == sum(v for k, v in first["counts"]["type"].items() if k != "")
    for name in ("laser", "lens", "material"):
        assert first["counts"][name][""] == count == sum(v for k, v in first["counts"][name].items() if k != ""), name
    chosen = listed(shop, type="mixed", laser=str(shop["lasers"][0]["id"]))
    every = [e for e in catalog.all_works(store) if e["type"] == "mixed" and e["laser"]["id"] == shop["lasers"][0]["id"]]
    assert chosen["total"] == len(every) == chosen["counts"]["type"]["mixed"]
    searched = listed(shop, q="work 1 alpha")                                  # every word, anywhere in the name, the number or the equipment
    wanted = [e for e in catalog.all_works(store) if all(w in f"{e['name']} №{e['id']} {e['laser']['name']} {(e['lens'] or {}).get('name') or ''} "
                                                        f"{e['material']['name']}".lower() for w in ("work", "1", "alpha"))]
    assert searched["total"] == len(wanted) > 0 and all(e["laser"]["name"] == "Laser Alpha" for e in searched["items"])


def test_a_large_collection_answers_a_query_in_well_under_a_second(shop):
    """Measured, not promised: 2000 works, first read cold, then a search and a page from the kept entries."""
    store = shop["store"]
    with store.transaction():
        for n in range(2000):
            add_vector(shop, f"Work {n}", updated=f"2026-10-{1 + n % 28:02d}T{n % 24:02d}:00:00+00:00")
    started = time.perf_counter()
    cold = listed(shop)
    cold_s = time.perf_counter() - started
    started = time.perf_counter()
    warm = listed(shop, q="work 19", offset=20)
    warm_s = time.perf_counter() - started
    assert cold["total"] == 2000 and warm["total"] > 0
    assert cold_s < 2.0 and warm_s < 1.0, (cold_s, warm_s)


def test_a_write_by_the_workshop_is_seen_by_the_next_read(shop):
    work = add_vector(shop, "Before")
    assert names(listed(shop)) == ["Before"]
    assert shop["client"].post(f"/api/vector/{work}/rename", json={"name": "After"}).json()["name"] == "After"
    assert names(listed(shop)) == ["After"] and listed(shop, q="before")["total"] == 0
    add_photo(shop, "Second", updated=NEW)
    assert names(listed(shop)) == ["Second", "After"]


# -- the way back to a work -----------------------------------------------------------------------------------------------------------------------
def test_through_extends_the_portion_to_whole_pages_up_to_the_work_the_person_comes_back_to(shop):
    ids = []
    for n in range(70):
        ids.append(add_vector(shop, f"W{n:02d}", updated=f"2026-10-{1 + n // 24:02d}T{n % 24:02d}:00:00+00:00"))
    order = [item["key"] for item in listed(shop, limit=100)["items"]]
    assert len(order) == 70
    near, far = order[5], order[57]
    assert len(listed(shop, through=near)["items"]) == 20
    reached = listed(shop, through=far)
    assert len(reached["items"]) == 60 and reached["items"][57]["key"] == far and reached["total"] == 70            # 58th work: three whole portions
    assert [i["key"] for i in reached["items"]] == order[:60]
    assert len(listed(shop, through="vector-99999")["items"]) == 20 and len(listed(shop, through="garbage")["items"]) == 20      # a work that is gone changes nothing
    assert len(listed(shop, through=far, q="w0")["items"]) == 10 and listed(shop, through=far, q="w0")["total"] == 10          # outside the search: nothing extra
    assert len(listed(shop, offset=20, limit=20, through=far)["items"]) == 40                                      # a later portion is extended too


def test_through_stops_at_the_most_a_request_may_grow_to(shop):
    with shop["store"].transaction():
        for n in range(catalog.MAX_THROUGH + 40):
            add_vector(shop, f"W{n:03d}", updated=f"2026-{1 + n // 28:02d}-{1 + n % 28:02d}T10:00:00+00:00")
    far = [e["key"] for e in sorted(catalog.all_works(shop["store"]), key=lambda e: (e["updated_at"], e["id"], e["kind"]), reverse=True)][catalog.MAX_THROUGH + 5]
    assert len(listed(shop, through=far)["items"]) == 20                                                  # too far: the person is shown the first portion


def test_the_portion_asked_for_is_bounded(shop):
    add_vector(shop, "One")
    assert shop["client"].get("/api/works", params={"limit": 0}).status_code == 422
    assert shop["client"].get("/api/works", params={"limit": catalog.MAX_PAGE + 1}).status_code == 422
    assert shop["client"].get("/api/works", params={"offset": -1}).status_code == 422
    assert shop["client"].get("/api/works", params={"limit": catalog.MAX_PAGE}).status_code == 200


# -- the owners' operations the catalog points to, on real works --------------------------------------------------------------------------------
from test_grey_scales import app_world                                                    # noqa: E402,F401  (a laser, lens and titanium with four measured grey scales)
from test_inscriptions_vector import add as add_inscription                             # noqa: E402
from test_photo_works import create as create_photo_work                                  # noqa: E402
from test_vector_photo_zones import colouring, create as create_vector_work, of_colour, world   # noqa: E402,F401  (the grey-scale world with measured colours)
from test_vector_work import RED                                                          # noqa: E402


def test_real_works_each_open_rename_copy_and_delete_through_their_own_routes_and_a_mixed_one_stays_one_document(world):
    client = world["client"]
    plain = create_vector_work(world)
    mixed = create_vector_work(world)
    colouring(world, mixed, op="photo_add", regions=of_colour(world, mixed, RED))
    add_inscription(world, mixed)
    photo = create_photo_work(client, name="Girl")
    assert client.post(f"/api/vector/{mixed['id']}/rename", json={"name": "Mixed portrait"}).status_code == 200
    plan_rows = world["store"].one("SELECT COUNT(*) AS n FROM plan")["n"]
    entries = {item["id"]: item for item in client.get("/api/works", params={"limit": 100}).json()["items"]}
    assert {plain["id"], mixed["id"], photo["id"]} <= set(entries)
    one, two, girl = entries[plain["id"]], entries[mixed["id"]], entries[photo["id"]]
    assert (one["type"], two["type"], girl["type"]) == ("vector", "mixed", "photo")
    assert (two["zones"], two["texts"], two["name"]) == (1, 1, "Mixed portrait") and sum(1 for e in entries.values() if e["name"] == "Mixed portrait") == 1
    for item in (one, two, girl):
        assert (item["width_mm"], item["height_mm"]) == ((60, 45) if item["kind"] == "vector" else (60, 30))
        thumb = client.get(item["thumb"])
        assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/png", item["key"]
        opened = client.get(f"/api{item['base']}/{item['id']}")                                         # what the editor behind "open" loads
        assert opened.status_code == 200 and opened.json()["id"] == item["id"], item["key"]
    assert one["open"] == f"/vector?plan={plain['id']}" and girl["open"] == f"/photo-engraving?work={photo['id']}"
    assert (one["laser"]["name"], one["material"]["name"], girl["laser"]["id"], girl["material"]["id"]) == (
        world["laser"]["name"], world["titanium"]["name"], world["laser"]["id"], world["titanium"]["id"])

    # rename: only the name moves (not the date: a rename is no edit), through the owner's route
    stamp = one["updated_at"]
    assert client.post(f"/api{one['base']}/{one['id']}/rename", json={"name": "Renamed"}).json() == {"id": one["id"], "name": "Renamed"}
    assert client.post(f"/api{girl['base']}/{girl['id']}/rename", json={"name": "Renamed girl"}).json()["name"] == "Renamed girl"
    assert client.get(f"/api/works/{one['key']}").json()["name"] == "Renamed" and client.get(f"/api/works/{one['key']}").json()["updated_at"] == stamp
    assert client.get(f"/api/works/{girl['key']}").json()["name"] == "Renamed girl"
    assert client.post(f"/api{one['base']}/{one['id']}/rename", json={"name": " "}).status_code == 422             # refused by the owner; the catalog shows the old name
    assert client.get(f"/api/works/{one['key']}").json()["name"] == "Renamed"

    # copy: a work of its own next to the first, which stays as it was
    for item in (one, girl):
        made = client.post(f"/api{item['base']}/{item['id']}/copy", json={})
        assert made.status_code == 201
        copy = client.get(f"/api/works/{item['kind']}-{made.json()['id']}").json()
        assert copy["id"] != item["id"] and copy["kind"] == item["kind"] and copy["name"].endswith("(copy)")
        assert client.get(f"/api/works/{item['key']}").json()["id"] == item["id"]
    assert world["store"].one("SELECT COUNT(*) AS n FROM plan")["n"] == plan_rows + 2

    # an exported vector work says so; deleting through the shared route takes the work out of the catalog and its thumbnails with it
    assert client.get(f"/api/vector/{plain['id']}/export.lbrn2").status_code == 200
    assert client.get(f"/api/works/{one['key']}").json()["state"] == "exported"
    for item in (one, two, girl):
        assert client.delete(f"/api/plans/{item['id']}").status_code == 204
        assert client.get(f"/api/works/{item['key']}").status_code == 404
        assert item["id"] not in {e["id"] for e in client.get("/api/works", params={"limit": 100}).json()["items"]}


# -- works and experiments: one owner, two views --------------------------------------------------------------------------------------------------
def experiment_plan_ids(store) -> set[int]:
    return {e["plan_id"] for e in experiments.list_experiments(store)}


@pytest.mark.parametrize("make", [add_vector, add_photo], ids=["vector work", "photo work"])
def test_a_photographed_work_is_also_an_experiment_and_deleting_its_check_leaves_the_work_alone(shop, make):
    client, store = shop["client"], shop["store"]
    work = make(shop, "Engraved")
    other = make(shop, "Untouched")
    key = f"{'vector' if make is add_vector else 'photo'}-{work}"
    assert experiment_plan_ids(store) == set() and listed(shop)["total"] == 2                               # no photograph, no experiment
    owner_before = dict(store.one("SELECT id, name, mode, device_id, lens_id, plan_identifier FROM plan WHERE id=?", (work,)))
    pair = work_pair(shop, work, 3)
    assert experiment_plan_ids(store) == {work}                                                           # the photograph exposes the work in Experiments
    entry = client.get(f"/api/works/{key}").json()
    assert (entry["id"], entry["state"], entry["checks"]) == (work, "result", 1) and listed(shop)["total"] == 2      # ... and the work is one entry still
    assert client.delete(f"/api/plans/{work}").status_code == 409                                         # the shared delete refuses a work with a photograph
    assert client.get(f"/api/works/{key}").status_code == 200
    assert client.delete(f"/api/pairs/{pair}").status_code == 204                                         # delete the check
    assert experiment_plan_ids(store) == set()                                                            # the experiment leaves with its last photograph ...
    again = client.get(f"/api/works/{key}").json()
    assert (again["id"], again["name"], again["state"], again["checks"]) == (work, "Engraved", "prepared", 0)    # ... the work does not
    assert dict(store.one("SELECT id, name, mode, device_id, lens_id, plan_identifier FROM plan WHERE id=?", (work,))) == owner_before
    assert other in {e["id"] for e in listed(shop)["items"]}
    assert client.delete(f"/api/plans/{work}").status_code == 204 and client.get(f"/api/works/{key}").status_code == 404     # only now the work can be deleted


def test_an_experiment_check_is_deleted_only_through_its_own_routes_never_by_the_catalog():
    """The catalog's screen reaches no experiment route: a check is deleted where it is shown, a work where it is listed."""
    from pathlib import Path
    ui = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui" / "screens"
    source = (ui / "works.js").read_text(encoding="utf-8")
    assert "/experiments" not in source and "/pairs" not in source and "del('/plans/'" in source
