"""Acting on a finding (feature act-on-findings): «Убрать измерение» takes one measured layer out of every calculation and holds through a
re-measure (REQ-001, DEC-001), «Считать с последней гравировки» counts a recipe from its newest engraving (REQ-002, DEC-003), every remedy
shows its effect first and recalculates once (REQ-004, DEC-004), and «Вернуть» undoes either (REQ-005)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import labworld  # noqa: E402
import obs  # noqa: E402
import test_remeasure as remeasure  # noqa: E402
import test_supplied_settings as base  # noqa: E402
from titanium_platform import (colormap, exclusions as ex, findings as fd, ingest as ig, knowledge as kn, lab_export, model,  # noqa: E402
                               plans as pl, recheck as rc, setup as su)
from titanium_platform.api.app import create_app  # noqa: E402
from titanium_platform.db import Store  # noqa: E402


def world(store):
    w = obs.setup(store)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    w["stock"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2")
    return w


def add(store, w, lab, **kw):
    return obs.add(store, w, lab, **{"material_id": w["stock"]["id"], "layer_type": "Scan", "power": 40, **kw})


def latest(store):
    return fd.findings_of(store, fd.get_run(store)["id"])["findings"]


def recipe(store, w):
    (s,) = model.knowledge_summaries(store, *w["setup"]).values()
    return s


def audits(store, action):
    return [json.loads(r["detail_json"]) for r in store.query("SELECT detail_json FROM audit WHERE action=? ORDER BY id", (action,))]


@pytest.fixture
def three(store):
    """One recipe engraved three times; the third lies far from the other two: an anomaly beyond the saved tolerance."""
    w = world(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=5, variance_threshold=4.0)
    w["good"] = [add(store, w, (50, 0, 0)), add(store, w, (51, 0, 0))]
    w["bad"] = add(store, w, (80, 0, 0))
    kn.refresh(store, *w["setup"])
    fd.run_analysis(store, "manual")
    return w


def test_an_anomaly_offers_to_take_the_measurement_out_to_measure_its_photograph_again_and_to_count_from_the_newest(store, three):
    anomaly = next(f for f in latest(store) if f["kind"] == "anomaly")
    pair = store.one("SELECT pair_id FROM observation WHERE id=?", (three["bad"],))["pair_id"]
    assert anomaly["remedies"] == [{"action": "exclude_measurement", "observation_id": three["bad"]},
                                   {"action": "remeasure", "pair_id": pair}, {"action": "count_from_latest"}]
    fd.run_analysis(store, "manual")                                          # an older run acts on nothing: the data moved on since
    assert fd.findings_of(store, anomaly["run_id"])["findings"][0]["remedies"] == []
    assert fd.get_finding(store, anomaly["id"])["remedies"] == []


def test_a_measurement_taken_out_leaves_the_recipe_the_colour_map_and_the_anomalies_and_returns_with_vernut(store, three):
    anomaly = next(f for f in latest(store) if f["kind"] == "anomaly")
    before = recipe(store, three)

    preview = fd.remedy(store, anomaly["id"], "exclude_measurement")
    assert preview["leaving"]["observation_ids"] == [three["bad"]] and preview["before"]["lab"] == pytest.approx(before["lab"], abs=0.01)
    assert preview["after"]["lab"] == pytest.approx([50.5, 0, 0], abs=0.01) and preview["after"]["engravings"] == 2
    assert ex.excluded_ids(store) == set()                                    # a preview changes nothing

    done = fd.remedy(store, anomaly["id"], "exclude_measurement", note="glare on the photo", confirm=True)
    assert ex.excluded_ids(store) == {three["bad"]}
    after = recipe(store, three)
    assert three["bad"] not in after["observation_ids"] and after["lab"] == pytest.approx(preview["after"]["lab"], abs=0.01)
    assert three["bad"] not in {r["id"] for r in colormap._rows(store)}
    assert done["run_id"] == fd.get_run(store)["id"] and fd.get_run(store)["trigger"] == "operator"
    assert not [f for f in latest(store) if f["kind"] == "anomaly"]
    assert audits(store, "exclusion_added")[-1]["note"] == "glare on the photo"
    pair = store.one("SELECT pair_id FROM observation WHERE id=?", (three["bad"],))["pair_id"]
    listed = ex.listing(store)
    assert listed["active"] == 1 and listed["exclusions"][0]["pair_id"] == pair and listed["exclusions"][0]["observations_out"] == 1

    back = ex.revoke(store, done["exclusion"]["id"])
    assert ex.excluded_ids(store) == set() and back["exclusion"]["active"] is False
    assert three["bad"] in recipe(store, three)["observation_ids"] and three["bad"] in {r["id"] for r in colormap._rows(store)}
    assert [f["kind"] for f in latest(store)].count("anomaly") == 1
    assert audits(store, "exclusion_revoked")[-1]["exclusion_id"] == done["exclusion"]["id"]
    assert ex.listing(store)["active"] == 0 and len(ex.listing(store, include_revoked=True)["exclusions"]) == 1
    with pytest.raises(su.ValidationError):
        ex.revoke(store, done["exclusion"]["id"])


def test_a_knowledge_entry_whose_evidence_the_operator_took_out_is_questioned_with_that_reason(store):
    w = world(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=5, variance_threshold=4.0, criteria_agreed=True)
    first = add(store, w, (50, 0, 0))
    add(store, w, (51, 0, 0))
    kn.refresh(store, *w["setup"])
    entry = store.one("SELECT * FROM knowledge")
    assert entry["stage"] == "validated" and not entry["questioned"]

    ex.exclude_measurement(store, first)

    doubt = json.loads(store.one("SELECT doubt_json FROM knowledge WHERE id=?", (entry["id"],))["doubt_json"])
    assert doubt["reason"].startswith("measurements the operator took out took away the evidence of this stage")
    assert doubt["observation_ids"] == [first]


def test_a_measurement_out_and_a_measurement_counted_toward_nothing_are_refused(store, three):
    ex.exclude_measurement(store, three["bad"])
    with pytest.raises(su.ValidationError, match="already taken out"):
        ex.exclude_measurement(store, three["bad"])
    witness = add(store, three, (90, 0, 0), model_eligible=0)
    with pytest.raises(su.ValidationError, match="counts toward no recipe"):
        ex.preview_measurement(store, witness)


@pytest.fixture
def disputed(store):
    """One recipe engraved three times, every engraving a different colour: contradicted and unstable."""
    w = world(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, variance_threshold=4.0)
    w["labs"] = [(50, 0, 0), (70, 0, 0), (60, 20, 0)]
    w["ids"] = [add(store, w, lab, engraving=f"e{i}") for i, lab in enumerate(w["labs"], 1)]
    kn.refresh(store, *w["setup"])
    fd.run_analysis(store, "manual")
    return w


def test_counting_from_the_newest_engraving_keeps_it_leaves_the_older_ones_and_lets_later_ones_count(store, disputed):
    unstable = next(f for f in latest(store) if f["subkind"] == "variance")
    assert {"action": "count_from_latest"} in unstable["remedies"]

    preview = fd.remedy(store, unstable["id"], "count_from_latest")
    assert preview["kept"]["engraving_id"] == "e3" and [e["engraving_id"] for e in preview["older"]] == ["e2", "e1"]
    assert preview["after"]["lab"] == pytest.approx([60, 20, 0], abs=0.01) and preview["before"]["contradicted"]

    done = fd.remedy(store, unstable["id"], "count_from_latest", confirm=True)
    s = recipe(store, disputed)
    assert s["engravings"] == 1 and s["lab"] == pytest.approx(preview["after"]["lab"], abs=0.01)
    assert ex.excluded_ids(store) == set(disputed["ids"][:2])
    kid = store.one("SELECT id FROM knowledge")["id"]
    assert kn.get(store, kid)["counted_from"]["kept_engraving_id"] == "e3" and done["exclusion"]["engraving_ids"] == ["e2", "e1"]

    add(store, disputed, (61, 20, 0), engraving="e4")                        # engraved later: counts
    add(store, disputed, (50, 0, 0), engraving="e1", rephoto=True)           # a new photograph of an old engraving: stays out
    s = recipe(store, disputed)
    assert s["engravings"] == 2 and s["lab"] == pytest.approx([60.5, 20, 0], abs=0.01)

    again = ex.count_from_latest(store, *disputed["setup"], s["key"])         # a second decision replaces the first
    assert again["exclusion"]["kept_engraving_id"] == "e4" and set(again["exclusion"]["engraving_ids"]) == {"e1", "e2", "e3"}
    assert ex.listing(store)["active"] == 1 and recipe(store, disputed)["engravings"] == 1

    ex.revoke(store, again["exclusion"]["id"])
    assert recipe(store, disputed)["engravings"] == 4 and kn.get(store, kid)["counted_from"] is None


def test_a_questioned_entry_offers_to_count_from_the_newest_and_to_confirm_it_and_a_gap_offers_nothing_new(store):
    w = world(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=4, variance_threshold=4.0, criteria_agreed=True)
    for lab in ((50, 0, 0), (51, 0, 0)):
        add(store, w, lab, power=30)
    kn.refresh(store, *w["setup"])
    kid = store.one("SELECT id FROM knowledge")["id"]
    kn.approve_for_production(store, kid, confirm=True)
    add(store, w, (70, 0, 0), power=30)                                        # a later engraving breaks the thresholds
    kn.refresh(store, *w["setup"])
    fd.run_analysis(store, "manual")

    questioned = next(f for f in latest(store) if f["subkind"] == "questioned")
    assert questioned["remedies"] == [{"action": "count_from_latest"}, {"action": "confirm_questioned", "knowledge_id": kid}]
    assert all(f["remedies"] == [] for f in latest(store) if f["kind"] in ("gap", "improvement"))
    with pytest.raises(su.ValidationError, match="offers no action"):
        fd.remedy(store, questioned["id"], "exclude_measurement")


def test_a_recipe_of_one_engraving_has_no_older_one_to_leave_out(store):
    w = world(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=5)
    add(store, w, (50, 0, 0), engraving="e1")
    add(store, w, (51, 0, 0), engraving="e1", rephoto=True)
    kn.refresh(store, *w["setup"])
    with pytest.raises(su.ValidationError, match="rests on one engraving"):
        ex.preview_latest(store, *w["setup"], recipe(store, w)["key"])


def layer(store, pair_id, name):
    return store.one("SELECT id, layer_index FROM observation WHERE pair_id=? AND evidence_json LIKE ?", (pair_id, f'%"layer_name": "{name}"%'))


def test_a_measurement_taken_out_stays_out_when_its_photograph_is_measured_again(store):
    w = base.plate_world(store, default_pulse_width=200)
    old = remeasure.accepted(w)
    taken = layer(store, old, "r1c1")
    ex.exclude_measurement(store, taken["id"])

    new = ig.remeasure_pair(store, old)["replaced_by"]

    again = layer(store, new, "r1c1")
    assert again["id"] != taken["id"] and again["id"] in ex.excluded_ids(store)
    assert layer(store, new, "r1c2")["id"] not in ex.excluded_ids(store)
    assert ex.of_pair(store, new)[again["layer_index"]]["active"] and ex.listing(store)["exclusions"][0]["pair_id"] == new


def test_measuring_an_old_photograph_again_does_not_make_its_engraving_the_newest(store):
    """A re-measure revises the measurement of the same photograph: the photograph keeps the date it was first accepted, so «Считать с
    последней гравировки» still keeps the engraving photographed last, and the colour map dates the re-measured layers as before."""
    w = base.plate_world(store, default_pulse_width=200)
    older, newer = remeasure.accepted(w), remeasure.accepted(w)
    store.execute("UPDATE pair SET accepted_at=? WHERE id=?", ("2026-10-20T10:00:00+00:00", older))
    again = ig.remeasure_pair(store, older)["replaced_by"]
    assert store.one("SELECT accepted_at FROM pair WHERE id=?", (again,))["accepted_at"] > "2026-10-20T10:00:00+00:00"

    setup = (w["device"]["id"], w["lens"]["id"])
    cell = layer(store, newer, "r1c2")
    key = next(model.observation_key(o["parameters"], o["context"], o["task"]) for o in model.eligible_observations(store, *setup) if o["id"] == cell["id"])
    p = ex.preview_latest(store, *setup, key)
    assert p["kept"]["pair_ids"] == [newer] and [e["pair_ids"] for e in p["older"]] == [[again]]
    assert p["older"][0]["when"] == "2026-10-20T10:00:00+00:00"
    dated = {pt["date"] for pt in colormap.collect(store)["points"] if pt["pair_id"] == again}
    assert dated == {"2026-10-20T10:00:00+00:00"}

    ex.count_from_latest(store, *setup, key)                                  # decided, then the old photograph is measured once more
    latest_again = ig.remeasure_pair(store, again)["replaced_by"]
    assert layer(store, latest_again, "r1c2")["id"] in ex.excluded_ids(store) and layer(store, newer, "r1c2")["id"] not in ex.excluded_ids(store)


def test_the_api_previews_decides_lists_returns_and_waits_for_a_recheck(tmp_path):
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = world(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=5, variance_threshold=4.0)
    for lab in ((50, 0, 0), (51, 0, 0)):
        add(store, w, lab)
    bad = add(store, w, (80, 0, 0))
    kn.refresh(store, *w["setup"])
    fid = next(f["id"] for f in fd.findings_of(store, fd.run_analysis(store, "manual")["id"])["findings"] if f["kind"] == "anomaly")
    with TestClient(app) as client:
        seen = client.post(f"/api/analysis/findings/{fid}/remedy", json={"action": "exclude_measurement"}).json()
        assert seen["leaving"]["observation_ids"] == [bad] and client.get("/api/exclusions").json()["active"] == 0
        assert client.post(f"/api/analysis/findings/{fid}/remedy", json={"action": "remeasure"}).status_code == 422

        lock = rc._lock(store)
        lock.acquire()
        try:
            busy = client.post(f"/api/analysis/findings/{fid}/remedy", json={"action": "exclude_measurement", "confirm": True})
            assert busy.status_code == 409 and busy.json()["kind"] == "busy"
        finally:
            lock.release()

        done = client.post(f"/api/analysis/findings/{fid}/remedy", json={"action": "exclude_measurement", "confirm": True}).json()
        listed = client.get("/api/exclusions").json()
        assert listed["active"] == 1 and listed["exclusions"][0]["id"] == done["exclusion"]["id"] and done["run_id"]
        back = client.post(f"/api/exclusions/{done['exclusion']['id']}/revoke").json()
        assert back["exclusion"]["active"] is False and client.get("/api/exclusions").json()["active"] == 0


def test_a_new_laboratory_release_leaves_out_what_the_operator_took_out(tmp_path):
    store = Store(tmp_path / "data")
    labworld.build(store, tmp_path / "data" / "files")
    for row in store.query("SELECT photo_path FROM pair"):
        Path(row["photo_path"]).write_bytes(b"\x89PNG\r\n\x1a\n")
    lab_export.set_public_info(store, {"name": "Open titanium lab", "author": "A. Author"})
    rows = store.query("SELECT o.* FROM observation o JOIN pair p ON p.id=o.pair_id WHERE p.status='Accepted' ORDER BY o.id")
    taken = next(r["id"] for r in rows if model.knowledge_key_of(r) is not None)
    before = lab_export.preview(store, None)["measurements"]
    whole = lab_export.export(store, tmp_path / "1.tcelab", None, "CC-BY-4.0")["counts"]["measurements"]

    ex.exclude_measurement(store, taken)

    assert lab_export.preview(store, None)["measurements"] == before - 1
    assert lab_export.export(store, tmp_path / "2.tcelab", None, "CC-BY-4.0")["counts"]["measurements"] == whole - 1
    store.close()
