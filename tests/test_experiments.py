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
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
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


def test_cancelled_and_superseded_research_plates_are_history_not_experiments_waiting_for_a_photo(world):
    cancelled, superseded, kept = plate(world), plate(world), plate(world)
    world["store"].execute("UPDATE plan SET status='Cancelled' WHERE id=?", (cancelled["plan_id"],))
    world["store"].execute("UPDATE plan SET status='Superseded' WHERE id=?", (superseded["plan_id"],))
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["plan_id"] == kept["plan_id"] and experiment["status"] == "plate_ready"
    with pytest.raises(KeyError):
        experiments.get_experiment(world["store"], experiments.plan_key(cancelled["plan_id"]))


def test_a_plate_record_marked_deleted_is_not_an_experiment_and_an_empty_mark_is_no_mark(world):
    gone, kept = plate(world), plate(world)
    assert len(experiments.list_experiments(world["store"])) == 2          # NULL is no mark
    world["store"].execute("UPDATE plate SET status='Deleted' WHERE id=?", (gone["plate_id"],))
    assert [e["plan_id"] for e in experiments.list_experiments(world["store"])] == [kept["plan_id"]]


def test_the_experiments_of_one_laser_are_the_one_list_filtered_by_it(world):
    out = plate(world)
    finished = work_pair(world, None, 3)
    twin = devices.create_from_template(world["store"], "jpt-ydflp-e-60-m7-m-r")
    world["store"].execute("UPDATE pair SET device_id=? WHERE id=?", (twin["id"], finished))
    everything = experiments.list_experiments(world["store"])
    mine = experiments.list_experiments(world["store"], device_id=world["laser"]["id"])
    theirs = experiments.list_experiments(world["store"], device_id=twin["id"])
    assert [e["key"] for e in mine] == [experiments.plan_key(out["plan_id"])] and mine[0]["device_id"] == world["laser"]["id"]
    assert [e["main_pair_id"] for e in theirs] == [finished] and theirs[0]["key"].startswith("eng-")
    assert sorted(e["key"] for e in everything) == sorted(e["key"] for e in mine + theirs)


def test_a_finished_work_offers_its_lightburn_file_on_its_experiment(tmp_path):
    from fastapi.testclient import TestClient
    from titanium_platform.api.app import create_app
    app = create_app(tmp_path / "data")
    store = app.state.store
    store.set_setting("allow_non_raw_photos", True)
    w = {"store": store, "laser": devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r"),
         "material": su.save_material(store, "Grade 2 sheet", grade="Grade 2")}
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
    pid = work_pair(w, None, 3)
    with TestClient(app) as client:
        (summary,) = client.get("/api/experiments", params={"device_id": w["laser"]["id"]}).json()
        assert client.get("/api/experiments", params={"device_id": w["laser"]["id"] + 1}).json() == []
        detail = client.get("/api/experiments/" + summary["key"]).json()
        (check,) = detail["pairs"]
        assert check["lightburn_url"] == f"/api/pairs/{pid}/lightburn" and check["grayscale_image"] is False and check["tonal_image"] is False
        assert client.get(check["lightburn_url"]).content == synth.framed_work(seed=3, blobs=8)["lightburn"]
    store.close()


def test_the_app_serves_the_experiments_and_the_experiment_screen(tmp_path):
    from fastapi.testclient import TestClient
    from titanium_platform.api.app import create_app
    client = TestClient(create_app(tmp_path / "data"))
    assert client.get("/api/experiments").json() == []
    assert client.get("/api/experiments/plan-1").status_code == 404
    assert "experiment.js" in client.get("/").text
    assert client.get("/screens/experiment.js").status_code == 200


# -- REQ-041 AC2/AC3: what the experiment screen shows by itself, and every way into it (static checks of the scripts) ---------
def screen(name: str) -> str:
    from titanium_platform.api.app import UI_DIR
    return (UI_DIR / "screens" / name).read_text(encoding="utf-8")


def test_opening_an_experiment_shows_its_photograph_with_the_overlay_first_without_any_action():
    page = screen("experiment.js")
    layout = page[page.index("refreshAll();\n    const sub = "):]
    # rendered before the page is returned: the photograph column first (beside the title row), then the tabs with the result, the checks, the files
    order = [layout.index(part) for part in ("h('header', {class: 'os-head ep-head'}", "h('section', {class: 'os-col ep-photo-col', 'aria-label': 'Фото с наложением'}, photoTools, stage, caption)",
                                             "h('aside', {class: 'os-col ep-side'")]
    assert order == sorted(order)
    tabs = page[page.index("const items = ["):page.index("const box = App.tabs(")]
    parts = ("['result', 'Результат', result]", "['matrix', 'Матрица', matrixBox]", "['checks', `Проверки (${pairs.length})`, checks]",
             "['plate', 'Плата', plate]", "['work', 'Работа', files]", "['findings', `Выводы (${exp.findings.length})`, findings]")
    assert [tabs.index(part) for part in parts] == sorted(tabs.index(part) for part in parts)
    assert "function refreshAll() { showTools(); showPhoto(); showChecks(); showResult().catch(fail); }" in page
    # the overlay is on unless the operator switched it off; the brightness is lifted for the dark uncorrected RAW and left alone for the
    # corrected photograph unless the operator chose; contours draw the overlay
    assert "let contours = sessionStorage.getItem('experiment-contours') !== '0';" in page
    assert "let lifted = storedLift === null ? null : storedLift !== '0';" in page
    assert "const isLifted = (pair) => lifted === null ? !(pair && shownCorrected(pair)) : lifted;" in page
    assert "return contours && pair.alignment ? `${base}/overlay.png?${view}` : `${base}/photo.png?${view}`;" in page
    # the latest check (or the one asked for) is shown at once
    assert "pairs.find((p) => p.id === wanted) || pairs.find((p) => p.id === exp.main_pair_id) || pairs[pairs.length - 1]" in page


def test_the_experiment_screen_offers_check_selection_brightness_and_contours_and_holds_files_layers_and_conclusions():
    page = screen("experiment.js")
    assert "btn(`Проверка №${p.id}`, () => { current = p; refreshAll(); }, 'btn-small')" in page          # every check, selectable
    assert "btn(isLifted(current) ? 'Обычная яркость' : 'Поднять яркость'" in page
    assert "btn(contours ? 'Скрыть контуры' : 'Показать контуры'" in page
    for part in ("'Скачать .lbrn2'", "'Скачать файл LightBurn'", "`Измеренные слои · ${layers.length}`", "'Выводы по этому эксперименту'",
                 "IngestReview.hiddenMargins(check.alignment)"):
        assert part in page, part


def test_the_experiment_list_shows_the_material_conclusions_beside_the_experiments():
    page = screen("experiments.js")
    assert "findings = await get(`/devices/${selectedDevice.id}/findings`)" in page
    assert "finding.material_id === selectedMaterial?.id" in page
    assert "panel('Выводы для материала', latest.size, insightCards," in page
    assert "link(`/analysis/${finding.pair_id}`, `Измерения · проверка №${finding.pair_id}`)" in page


def test_every_plate_work_and_check_entry_point_links_to_its_experiment():
    experiment_of_pair = "'/experiment/' + (pair.plan_id && pair.plan_mode !== 'Restored from file' ? 'plan-' + pair.plan_id : 'eng-' + pair.engraving_id)"
    ingest = screen("ingest.js")
    assert experiment_of_pair in ingest and "backTo(pair)" in ingest and "backTo(source)" in ingest   # the pair review and its re-photograph
    assert "link('/experiment/' + (r.plan_id && !restored ? 'plan-' + r.plan_id : 'eng-' + r.engraving_id), 'К эксперименту')" in screen("analysis.js")
    plan = screen("plan.js")
    assert "link('/experiment/plan-' + p.id, 'К эксперименту')" in plan                                      # a plate
    assert "link('/experiment/eng-' + encodeURIComponent(work.engraving_id), 'К эксперименту')" in plan        # a work restored from its file
    assert "link('/experiment/' + encodeURIComponent(e.key), I18N.name(e.title))" in screen("experiment-cards.js")
    assert "link('/experiment/' + encodeURIComponent(p.experiment), p.title)" in screen("color-map.js")
