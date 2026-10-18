import json
import sqlite3

import pytest

from titanium_platform.db import ImmutableError, now


def _device(store):
    store.execute("INSERT INTO laser_device(name,data_json,created_at,updated_at) VALUES ('JPT','{}',?,?)", (now(), now()))
    return store.one("SELECT id FROM laser_device")["id"]


def _pair(store, device_id):
    store.execute(
        "INSERT INTO capture_setup(name,camera,lighting,angle,reference_chart,created_at) VALUES ('s','c','l','a','x',?)", (now(),))
    stand = store.one("SELECT id FROM capture_setup")["id"]
    store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at)"
        " VALUES ('accepted',?,NULL,?,'e1','a.lbrn2','/x','p.raw','/y','{}','{}',?)", (device_id, stand, now()))
    return store.one("SELECT id FROM pair")["id"]


def _observation(store, device_id, pair_id):
    store.execute(
        "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
        "model_eligible,repeat_eligible,eligibility_reason,created_at) VALUES (?,?,?,NULL,?,?,?,?,?,1,0,'ok',?)",
        (pair_id, 0, device_id, "e1", json.dumps([50, 1, 2]), "{}", "markers", "{}", now()))
    return store.one("SELECT id FROM observation")["id"]


def test_observation_update_and_delete_are_rejected_by_the_database(store):
    device_id = _device(store)
    oid = _observation(store, device_id, _pair(store, device_id))
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        store.execute("UPDATE observation SET lab_json='[1,2,3]' WHERE id=?", (oid,))
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        store.execute("DELETE FROM observation WHERE id=?", (oid,))
    assert json.loads(store.one("SELECT lab_json FROM observation")["lab_json"]) == [50, 1, 2]


def test_update_attempt_is_rejected_and_logged(store):
    with pytest.raises(ImmutableError):
        store.update_observation(7, lab_json="[0,0,0]")
    row = store.one("SELECT action, detail_json FROM audit")
    assert row["action"] == "observation_update_rejected"
    assert json.loads(row["detail_json"]) == {"observation_id": 7, "fields": ["lab_json"]}


def test_transaction_rolls_back_on_error(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.set_setting("a", 1)
            raise RuntimeError("boom")
    assert store.get_setting("a") is None
    with store.transaction():
        store.set_setting("a", 2)
    assert store.get_setting("a") == 2


def test_settings_round_trip_and_default(store):
    assert store.get_setting("missing", 5) == 5
    store.set_setting("k", {"x": [1, 2]})
    store.set_setting("k", {"x": [3]})
    assert store.get_setting("k") == {"x": [3]}
