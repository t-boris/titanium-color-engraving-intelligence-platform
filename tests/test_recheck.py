"""«Перепроверить все работы» (feature findings-you-can-manage-short-lists-re-check, REQ-004, DEC-089): a full backup first, every accepted
photograph measured again with the measurement as it is now, one analysis run at the end, a report kept after a restart; a stop between
photographs; no photograph changes while it runs."""
import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import test_supplied_settings as base
from test_remeasure import accepted, status
from titanium_platform import devices, findings as fd, ingest as ig, recheck as rc
from titanium_platform import setup as su
from titanium_platform.api.app import create_app


def world(store, photos=1):
    """A laser whose Q-Pulse default is set after its photographs were accepted: measuring again changes them."""
    w = base.plate_world(store, default_pulse_width=None)
    ids = [accepted(w) for _ in range(photos)]
    devices.update_device(store, w["device"]["id"], passport={**w["device"]["passport"], "default_pulse_width_ns": 200})
    return w, ids


def runs(store, trigger=None):
    return [r["trigger"] for r in store.query("SELECT trigger FROM analysis_run ORDER BY id") if trigger is None or r["trigger"] == trigger]


def test_a_recheck_backs_the_workshop_up_first_measures_every_photograph_again_and_draws_the_conclusions_once(store, tmp_path):
    w, (old,) = world(store)
    before = fd.run_analysis(store, "manual")

    done = rc.start(store, tmp_path / "backups", wait=True)

    assert done["status"] == "done" and done["phase"] == "done" and (done["total"], done["done"]) == (1, 1) and done["error"] is None
    photo, = done["photos"]
    assert photo["pair_id"] == old and photo["status"] == "replaced" and status(store, old) == "Deleted"
    assert status(store, photo["replaced_by"]) == "Accepted" and photo["layers"] > 0 and photo["max_delta_e"] is not None
    assert runs(store) == ["manual", "recheck"]                                   # one run for every photograph, not one each
    assert done["findings"]["before_run_id"] == before["id"] and done["findings"]["after_run_id"] == fd.get_run(store)["id"]
    copy = Path(done["backup_path"])
    assert copy.parent == tmp_path / "backups" and (copy / "manifest.json").is_file()
    with sqlite3.connect(f"file:{copy / 'titanium.sqlite'}?mode=ro", uri=True) as db:     # the backup holds the photographs as they were
        assert db.execute("SELECT status FROM pair WHERE id=?", (old,)).fetchone()[0] == "Accepted"
    assert rc.latest(store) == done
    assert [json.loads(r["detail_json"])["status"] for r in store.query("SELECT detail_json FROM audit WHERE action='recheck_finished'")] == ["done"]


def test_a_backup_that_cannot_be_made_stops_the_recheck_before_anything_changes(store):
    w, (old,) = world(store)

    done = rc.start(store, store.data_dir / "inside", wait=True)                  # a backup cannot be written inside the workshop

    assert done["status"] == "failed" and "the backup could not be made, so nothing was measured again" in done["error"]
    assert done["photos"] == [] and status(store, old) == "Accepted" and runs(store) == [] and done["backup_path"] is None
    assert not rc.running(store)


def test_a_photograph_that_does_not_come_out_whole_or_fails_does_not_stop_the_others(store, tmp_path, monkeypatch):
    w, (first, second, third) = world(store, photos=3)
    real = ig.remeasure_pair

    def remeasure(s, pair_id, on_accepted=None):
        if pair_id == first:
            return {"pair_id": pair_id, "status": "kept", "replaced_by": None, "reason": "the new measurement reads fewer layers than the accepted one",
                    "layers": []}
        if pair_id == second:
            raise RuntimeError("the photograph file is gone")
        return real(s, pair_id, on_accepted=on_accepted)
    monkeypatch.setattr(ig, "remeasure_pair", remeasure)

    done = rc.start(store, tmp_path / "backups", wait=True)

    assert [(p["pair_id"], p["status"]) for p in done["photos"]] == [(first, "kept"), (second, "failed"), (third, "replaced")]
    assert done["photos"][0]["reason"] == "the new measurement reads fewer layers than the accepted one"
    assert done["photos"][1]["reason"] == "RuntimeError: the photograph file is gone" and done["status"] == "done"
    assert status(store, first) == "Accepted" and status(store, third) == "Deleted" and runs(store, "recheck") == ["recheck"]


def test_a_stop_takes_effect_between_photographs_and_the_conclusions_are_still_drawn(store, tmp_path, monkeypatch):
    w, (first, second) = world(store, photos=2)
    real = ig.remeasure_pair
    holder = {}

    def remeasure(s, pair_id, on_accepted=None):
        rc.stop(s, holder["id"])                                                 # the operator presses «Остановить» during the first
        return real(s, pair_id, on_accepted=on_accepted)
    monkeypatch.setattr(ig, "remeasure_pair", remeasure)
    real_save = rc._save

    def save(s, recheck_id, report):
        holder.setdefault("id", recheck_id)
        real_save(s, recheck_id, report)
    monkeypatch.setattr(rc, "_save", save)

    done = rc.start(store, tmp_path / "backups", wait=True)

    assert done["status"] == "cancelled" and [p["pair_id"] for p in done["photos"]] == [first]
    assert status(store, second) == "Accepted" and runs(store) == ["recheck"] and done["findings"]["after_run_id"] is not None


def test_a_recheck_the_application_did_not_finish_reads_as_interrupted_and_the_next_one_closes_it(store, tmp_path):
    w, _ = world(store)
    left = store.execute("INSERT INTO recheck_run(started_at,status,report_json) VALUES (?,?,?)",
                         ("2026-10-25T10:00:00+00:00", "running", json.dumps({"phase": "remeasure", "total": 1, "done": 0, "photos": []}))).lastrowid

    assert rc.latest(store)["status"] == "interrupted"
    rc.start(store, tmp_path / "backups", wait=True)
    assert store.one("SELECT status FROM recheck_run WHERE id=?", (left,))["status"] == "interrupted"


def test_while_a_recheck_runs_no_photograph_is_accepted_measured_again_or_deleted_and_no_second_one_starts(tmp_path):
    app = create_app(tmp_path / "data")
    store = app.state.store
    lock = rc._lock(store)
    lock.acquire()
    try:
        with TestClient(app) as client:
            for method, url in (("post", "/api/pairs/1/accept"), ("post", "/api/pairs/1/remeasure"), ("delete", "/api/pairs/1"), ("post", "/api/recheck")):
                answer = getattr(client, method)(url)
                assert answer.status_code == 409 and answer.json()["kind"] == "busy", url
            assert client.get("/api/recheck/preview").json()["running"] is True
    finally:
        lock.release()


def test_the_api_previews_starts_and_follows_a_recheck_and_keeps_its_report(tmp_path):
    app = create_app(tmp_path / "data")
    store = app.state.store
    w, (old,) = world(store)
    store.set_setting("backup_dir", str(tmp_path / "kept-backups"))
    with TestClient(app) as client:
        assert client.get("/api/recheck/latest").json() is None
        preview = client.get("/api/recheck/preview").json()
        assert (preview["photos"], preview["estimate_s"], preview["backup_dir"]) == (1, rc.SECONDS_PER_PHOTO, str(tmp_path / "kept-backups"))
        assert preview["backup_bytes"] > 0 and preview["free_bytes"] > 0 and preview["running"] is False
        started = client.post("/api/recheck")
        assert started.status_code == 202
        rid = started.json()["id"]
        deadline = time.monotonic() + 120
        while (now := client.get(f"/api/recheck/{rid}").json())["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert now["status"] == "done" and now["photos"][0]["status"] == "replaced"
        assert client.get("/api/recheck/latest").json()["id"] == rid
        assert client.post(f"/api/recheck/{rid}/stop").json()["status"] == "done"          # a finished one stays as it ended
        assert client.get("/api/recheck/999").status_code == 404
        assert client.get("/api/analysis/runs").json()[0]["trigger"] == "recheck"


def test_a_run_before_the_stable_anomaly_key_compares_with_today_by_photograph_and_layer(store):
    w = base.plate_world(store, default_pulse_width=200)
    su.save_rules(store, w["device"]["id"], w["lens"]["id"], delta_tolerance=10.0)
    pair = accepted(w)
    observation = store.one("SELECT id, layer_index FROM observation WHERE pair_id=? ORDER BY id LIMIT 1", (pair,))
    old_run = store.execute("INSERT INTO analysis_run(at,trigger,summary_json) VALUES ('2026-10-24T10:00:00+00:00','manual','{}')").lastrowid
    new_run = store.execute("INSERT INTO analysis_run(at,trigger,summary_json) VALUES ('2026-10-25T10:00:00+00:00','recheck','{}')").lastrowid
    data = json.dumps({"statement": "s", "subkind": "observation", "samples": {"photographs": 4}, "compares": {"delta_e": 19.0}})
    for run_id, key in ((old_run, f"anomaly:observation:{observation['id']}"), (new_run, f"anomaly:photo:{pair}:{observation['layer_index']}")):
        store.execute("INSERT INTO finding(run_id,key,kind,data_json) VALUES (?,?,?,?)", (run_id, key, "anomaly", data))

    diff = fd.compare_runs(store, old_run, new_run)

    assert diff["counts"] == {"appeared": 0, "gone": 0, "changed": 0} and (diff["before"], diff["after"]) == (1, 1)
