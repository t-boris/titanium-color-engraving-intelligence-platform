"""An accepted photograph is measured again with the measurement as it is now, and the new measurement replaces the old one only
when it is whole (DEC-088)."""
import pytest
from fastapi.testclient import TestClient

import test_supplied_settings as base
from titanium_platform import devices
from titanium_platform import ingest as ig
from titanium_platform import photo as ph
from titanium_platform.api.app import create_app


def accepted(w, tag="QPulseWidth"):
    pid = base.pair_without(w, tag)
    ig.check_pair(w["store"], pid)
    ig.review_masks(w["store"], pid)
    ig.accept_pair(w["store"], pid)
    return pid


def status(store, pair_id):
    return store.one("SELECT status FROM pair WHERE id=?", (pair_id,))["status"]


def test_a_default_set_after_the_measurement_is_applied_by_measuring_again(store):
    w = base.plate_world(store, default_pulse_width=None)
    old = accepted(w)
    before = base.observation_of(store, old, "r1c1")
    assert before["model_eligible"] == 0 and '"pulse_width": null' in before["parameters_json"]
    device = devices.update_device(store, w["device"]["id"], passport={**w["device"]["passport"], "default_pulse_width_ns": 200})
    result = ig.remeasure_pair(store, old)
    assert result["status"] == "replaced" and result["reason"] is None
    new = result["replaced_by"]
    assert status(store, old) == "Deleted" and status(store, new) == "Accepted"
    after = base.observation_of(store, new, "r1c1")
    assert after["model_eligible"] == 1 and '"pulse_width": 200' in after["parameters_json"]
    layer = next(item for item in result["layers"] if item["name"] == "r1c1")
    assert layer["pulse_width_before"] is None and layer["pulse_width_after"] == 200
    assert layer["model_eligible_before"] is False and layer["model_eligible_after"] is True and layer["delta_e"] is not None
    assert len(result["layers"]) == len(ig._observation_summary(store, new)) and device


def test_the_same_engraving_keeps_one_accepted_photograph_and_the_old_rows_stay_in_the_history(store):
    w = base.plate_world(store, default_pulse_width=200)
    old = accepted(w)
    count = store.one("SELECT COUNT(*) n FROM observation WHERE pair_id=?", (old,))["n"]
    result = ig.remeasure_pair(store, old)
    new = result["replaced_by"]
    assert store.one("SELECT COUNT(*) n FROM observation WHERE pair_id=?", (old,))["n"] == count          # immutable, kept for the audit
    assert store.one("SELECT COUNT(*) n FROM observation WHERE pair_id=?", (new,))["n"] == count
    rows = store.query("SELECT status FROM pair WHERE engraving_id=(SELECT engraving_id FROM pair WHERE id=?) AND status='Accepted'", (new,))
    assert len(rows) == 1
    assert store.one("SELECT repeat_eligible FROM observation WHERE pair_id=? LIMIT 1", (new,))["repeat_eligible"] == 1


def test_a_measurement_that_does_not_come_out_whole_leaves_the_old_one_untouched(store, monkeypatch):
    w = base.plate_world(store, default_pulse_width=200)
    old = accepted(w)

    def refuse(*_args, **_kwargs):
        raise ig.IngestError("resolve the problems found by the check: test")
    monkeypatch.setattr(ig, "accept_pair", refuse)
    result = ig.remeasure_pair(store, old)
    assert result["status"] == "kept" and "problems found" in result["reason"] and result["replaced_by"] is None
    assert status(store, old) == "Accepted"
    assert [row["status"] for row in store.query("SELECT status FROM pair WHERE id>?", (old,))] == ["Deleted"]      # the draft is dropped


def test_a_change_of_colour_basis_is_refused(store, monkeypatch):
    w = base.plate_world(store, default_pulse_width=200)
    old = accepted(w)
    real = ph.correct
    monkeypatch.setattr(ph, "correct", lambda *a, **k: (None, real(*a, **k)[1], None))             # the chart can no longer be used
    result = ig.remeasure_pair(store, old)
    assert result["status"] == "kept" and "colour basis" in result["reason"] and status(store, old) == "Accepted"


def test_a_pair_that_cannot_be_revised_is_kept_with_the_reason(store):
    w = base.plate_world(store, default_pulse_width=200)
    pid = base.pair_without(w, "QPulseWidth")                                                          # not accepted
    result = ig.remeasure_pair(store, pid)
    assert result["status"] == "kept" and "accepted" in result["reason"]


def test_the_api_measures_again_and_returns_the_layers_before_and_after(tmp_path):
    from titanium_platform.db import open_store
    store = open_store(tmp_path, "test")
    w = base.plate_world(store, default_pulse_width=200)
    old = accepted(w)
    with TestClient(create_app(tmp_path)) as client:
        out = client.post(f"/api/pairs/{old}/remeasure")
    assert out.status_code == 200
    body = out.json()
    assert body["status"] == "replaced" and body["replaced_by"] > old and body["layers"] and all("delta_e" in item for item in body["layers"])


def test_a_check_that_finds_problems_keeps_the_old_measurement_and_names_them(store, monkeypatch):
    w = base.plate_world(store, default_pulse_width=200)
    old = accepted(w)
    real = ig.check_pair
    problem = "pulse width 300 ns is not a selectable step of this laser; the steps are 1, 2"
    monkeypatch.setattr(ig, "check_pair", lambda *a, **k: {**real(*a, **k), "problems": [problem]})
    result = ig.remeasure_pair(store, old)
    assert result["status"] == "kept" and result["reason"] == "resolve the problems found by the check: " + problem
    assert status(store, old) == "Accepted" and [row["status"] for row in store.query("SELECT status FROM pair WHERE id>?", (old,))] == ["Deleted"]
