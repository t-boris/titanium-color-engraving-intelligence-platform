"""Experiments are derived from plates and checks, not stored (REQ-028, DEC-055)."""
import cv2
import numpy as np
import pytest

import synth
from titanium_platform import devices, experiments, ingest as ig, plans as pl, setup as su


@pytest.fixture
def world(store):
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    pl.save_marker_layer_settings(store, 20, 60, 300)
    return {"store": store, "laser": laser, "material": material}


def plate(w, power="10 20", speed="900"):
    return pl.create_plate_series(w["store"], w["laser"]["id"], power, "40 80", speed, 5, 4, 1, pulse_width=200, line_interval=0.025, passes=1)[0]


def work_pair(w, plan_id=None, seed=3, rephoto_of=None):
    data = synth.framed_work(seed=seed, blobs=8)
    return ig.create_pair(w["store"], device_id=w["laser"]["id"], lens_id=None, lightburn_name="work.lbrn2", lightburn_bytes=data["lightburn"],
                          photo_name=f"photo{seed}.png", photo_bytes=cv2.imencode(".png", data["photo"])[1].tobytes(),
                          plan_id=plan_id, rephoto_of=rephoto_of, context={"material_id": w["material"]["id"]})


def set_status(store, pair_id, status):
    store.execute("UPDATE pair SET status=? WHERE id=?", (status, pair_id))


def test_a_plate_without_photographs_is_an_experiment_waiting_for_a_photo(world):
    out = plate(world)
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["key"] == experiments.plan_key(out["plan_id"]) and experiment["status"] == "plate_ready"
    assert experiment["checks"] == 0 and experiment["main_pair_id"] is None and experiment["plan_id"] == out["plan_id"]


def test_all_checks_made_on_one_plate_belong_to_one_experiment(world):
    out = plate(world)
    first, second = work_pair(world, out["plan_id"], 3), work_pair(world, out["plan_id"], 4)
    set_status(world["store"], first, "Accepted")
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["checks"] == 2 and experiment["photos"] == 2 and experiment["status"] == "needs_review"
    assert experiment["main_pair_id"] == second                          # the latest photograph is the one shown first
    set_status(world["store"], second, "Accepted")
    assert experiments.list_experiments(world["store"])[0]["status"] == "accepted"


def test_a_finished_work_and_its_rephotograph_are_one_experiment_without_a_plate(world):
    first = work_pair(world, None, 3)
    set_status(world["store"], first, "Accepted")         # only an accepted check can be photographed again
    again = work_pair(world, None, 4, rephoto_of=first)
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["key"].startswith("eng-") and experiment["plan_id"] is None and experiment["kind"] == "Готовая работа"
    assert experiment["checks"] == 2 and experiment["main_pair_id"] == again


def test_two_different_works_are_two_experiments_most_recent_first(world):
    a, b = work_pair(world, None, 3), work_pair(world, None, 4)
    keys = [e["title"] for e in experiments.list_experiments(world["store"])]
    assert len(keys) == 2
    assert experiments.list_experiments(world["store"])[0]["main_pair_id"] == b


def test_deleted_checks_and_plates_are_not_part_of_any_experiment(world):
    out = plate(world)
    pair = work_pair(world, out["plan_id"], 3)
    set_status(world["store"], pair, "Deleted")
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["checks"] == 0 and experiment["status"] == "plate_ready"
    world["store"].execute("UPDATE plan SET status='Deleted' WHERE id=?", (out["plan_id"],))
    assert experiments.list_experiments(world["store"]) == []


def test_a_check_of_a_deleted_plate_stays_as_a_finished_work(world):
    out = plate(world)
    pair = work_pair(world, out["plan_id"], 3)
    world["store"].execute("UPDATE plan SET status='Deleted' WHERE id=?", (out["plan_id"],))
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["key"].startswith("eng-") and experiment["main_pair_id"] == pair


def test_the_detail_carries_the_plate_the_checks_and_the_conclusions(world):
    out = plate(world)
    pair = work_pair(world, out["plan_id"], 3)
    set_status(world["store"], pair, "Accepted")
    world["store"].execute("INSERT INTO capability_finding(pair_id,purpose,status,summary,parameters_json,evidence_json,next_test,created_at)"
                           " VALUES (?,?,?,?,?,?,?,?)", (pair, "color", "candidate", "Цвет читается", None, "{}", "Повторить", "2026-10-16T00:00:00+00:00"))
    detail = experiments.get_experiment(world["store"], experiments.plan_key(out["plan_id"]))
    assert detail["plate"]["plan_id"] == out["plan_id"] and detail["plate"]["layers"] > 0
    assert [p["id"] for p in detail["pairs"]] == [pair] and detail["pairs"][0]["status"] == "Accepted"
    assert [f["purpose"] for f in detail["findings"]] == ["color"]
    with pytest.raises(KeyError):
        experiments.get_experiment(world["store"], "plan-9999")


def test_the_app_serves_the_experiments_and_the_experiment_screen(tmp_path):
    from fastapi.testclient import TestClient
    from titanium_platform.api.app import create_app
    client = TestClient(create_app(tmp_path / "data"))
    assert client.get("/api/experiments").json() == []
    assert client.get("/api/experiments/plan-1").status_code == 404
    assert "experiment.js" in client.get("/").text
    assert client.get("/screens/experiment.js").status_code == 200
