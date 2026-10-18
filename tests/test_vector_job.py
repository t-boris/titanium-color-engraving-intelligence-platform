"""REQ-021 / DEC-065: an image becomes a reviewed vector LightBurn job whose every region has evidence or is left out."""
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import obs
import recipes
from titanium_platform import color, knowledge as kn, lightburn as lb, model, plans as pl, setup as su
from titanium_platform.api.app import create_app

WHITE, RED, BLUE, GREEN, BLACK = (255, 255, 255), (200, 30, 30), (30, 30, 200), (30, 160, 30), (0, 0, 0)
PALETTE = [WHITE, RED, BLUE, GREEN, BLACK]


def lab(rgb):
    return [float(v) for v in color.srgb8_to_lab(np.array(rgb, float))]


def artwork() -> bytes:
    """Red and blue blocks, a green block nothing was measured for, and black text strokes, on white."""
    img = np.full((130, 200, 3), WHITE, np.uint8)
    img[10:60, 10:70], img[10:60, 80:140], img[10:60, 150:190] = RED, BLUE, GREEN
    cv2.putText(img, "TI", (20, 115), cv2.FONT_HERSHEY_SIMPLEX, 1.4, BLACK, 5)
    return cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


@pytest.fixture
def job(tmp_path):
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *w["setup"], criteria_agreed=True)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    stock = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1, surface="brushed")
    other = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1, surface="brushed")
    found = recipes.recipes(w["device"]["passport"])
    recipes.add(store, w, found["Gold fill"], lab(RED), material_id=stock["id"])      # a Scan recipe that engraves red
    recipes.add(store, w, found["Offset"], lab(BLUE), material_id=stock["id"])        # an Offset Fill recipe that engraves blue
    recipes.add(store, w, found["Outline"], (25.0, 0.0, 0.0), material_id=stock["id"])  # a Line recipe for strokes
    green = dict(found["Gold fill"], power=50.0)
    recipes.add(store, w, green, lab(GREEN), material_id=other["id"])                 # green exists, but on another titanium
    kn.refresh(store, *w["setup"])
    entries = {k["parameters"]["layer_type"] + ("-other" if k["parameters"]["power"] == 50.0 else ""): k for k in kn.list_for_setup(store, *w["setup"])}
    with TestClient(app) as client:
        r = client.post("/api/vector", data={"device_id": w["setup"][0], "lens_id": w["setup"][1], "material_id": stock["id"],
                                             "name": "Badge", "width_mm": 50, "strategy": "color", "palette": json.dumps(PALETTE),
                                             "threshold": 8, "markers": "true", "clean": "true"},
                        files={"image": ("badge.png", artwork(), "image/png")})
        assert r.status_code == 201, r.text
        yield {"client": client, "store": store, "w": w, "job": r.json(), "entries": entries, "stock": stock}
    store.close()


def by_colour(job, rgb):
    return [r for r in job["regions"] if tuple(r["srgb"]) == rgb]


def edit(c, job, **op):
    r = c["client"].post(f"/api/vector/{job['id']}/edit", json=op)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_traced_job_assigns_measured_recipes_by_colour_and_marks_the_rest_weak(job):
    j, entries = job["job"], job["entries"]
    assert j["mode"] == pl.MODE_VECTOR and j["status"] == "Draft" and j["plan_identifier"].startswith("TCE-A-")
    assert j["lens"]["id"] == job["w"]["setup"][1] and j["material_id"] == job["stock"]["id"] and j["document"]["version"] == 1
    red, blue = by_colour(j, RED)[0], by_colour(j, BLUE)[0]
    assert (red["status"], red["knowledge_id"], red["mode"]) == ("matched", entries["Scan"]["id"], "Scan")
    assert (blue["status"], blue["knowledge_id"], blue["mode"]) == ("matched", entries["OffsetFill"]["id"], "OffsetFill")
    assert set(red["prediction"]) == {"lab", "confidence", "expected_delta_e", "stability"} and red["match_error"] <= 8    # REQ-002, DEC-030
    green = by_colour(j, GREEN)[0]
    assert green["status"] == "weak" and "threshold" in green["note"]           # the green recipe is on another stock: not evidence
    assert green["knowledge_id"] != entries["Scan-other"]["id"] and green["match_error"] > 8
    letters = by_colour(j, BLACK)
    assert len(letters) == 2 and all(r["status"] == "weak" and "threshold" in r["note"] for r in letters)
    assert set(j["weak"]) == {r["id"] for r in j["regions"] if r["status"] == "weak"} and "region(s) have no adequate evidence" in j["export_blocked"]
    assert j["svg"].count("url(#weak") == len(j["weak"])          # weak regions are hatched in the preview
    r = job["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert r.status_code == 422 and "no adequate evidence" in r.json()["error"]


def test_review_edits_persist_as_document_versions_and_the_weak_regions_are_resolved(job):
    c, j = job, job["job"]
    background = by_colour(j, WHITE)[0]
    j = edit(c, j, op="delete", region=background["id"])
    for letter in by_colour(j, BLACK):
        j = edit(c, j, op="set_task", region=letter["id"], task="line")
    green = by_colour(j, GREEN)[0]
    j = edit(c, j, op="to_designer", region=green["id"])
    j = edit(c, j, op="exclude", region=green["id"])
    assert j["status"] == "Ready to export" and j["weak"] == [] and j["export_blocked"] is None
    again = c["client"].get(f"/api/vector/{j['id']}").json()
    assert again["document"]["version"] == 4 and [h["op"]["op"] for h in again["history"]] == ["trace", "delete", "set_task", "set_task", "to_designer", "exclude"]
    assert all(r["task"] == "line" and r["status"] == "matched" and r["mode"] == "Cut" for r in by_colour(again, BLACK))
    assert not by_colour(again, WHITE) and by_colour(again, GREEN)[0]["status"] == "excluded"
    target = c["store"].one("SELECT * FROM target_color WHERE source_plan_id=?", (j["id"],))
    assert json.loads(target["lab_json"]) == pytest.approx(green["lab"]) and target["source_color_key"] == f"region:{green['id']}"
    reverted = edit(c, again, op="revert", version=1)
    assert reverted["document"]["version"] == 5 and by_colour(reverted, WHITE) and reverted["status"] == "Draft"


def test_the_export_holds_the_regions_as_paths_on_the_layers_of_their_recipes(job):
    c, j, entries = job, job["job"], job["entries"]
    j = edit(c, j, op="delete", region=by_colour(j, WHITE)[0]["id"])
    for letter in by_colour(j, BLACK):
        j = edit(c, j, op="set_task", region=letter["id"], task="line")
    j = edit(c, j, op="exclude", region=by_colour(j, GREEN)[0]["id"])
    r = c["client"].get(f"/api/plans/{j['id']}/export.lbrn2")
    assert r.status_code == 200
    project = lb.parse_bytes(r.content)
    layers = {layer.index: layer for layer in project.layers}
    assert layers[0].name.startswith("CLEAN-CROSSHATCH-") and layers[1].name == "Markers" and sorted(layers) == [0, 1, 2, 3, 4]
    plan = pl.get_plan(c["store"], j["id"])
    assert plan["status"] == "Exported" and [l["index"] for l in plan["layers"]] == [2, 3, 4]
    passport = c["w"]["device"]["passport"]
    for planned in plan["layers"]:
        layer = layers[planned["index"]]
        entry = next(e for e in entries.values() if e["id"] == planned["knowledge_id"])
        assert model.parameters_key(recipes.parameters(layer, passport)) == model.parameters_key(entry["parameters"])   # the full recipe
        assert all(region.kind == "path" and region.closed for region in layer.regions)
        assert len(layer.regions) == len(planned["region_ids"])
    cut = next(layer for layer in project.layers if layer.layer_type == "Cut")
    assert len(cut.regions) == 2                                   # the two letters, as outlines on the Line layer
    dx, dy = pl.export_offset(plan)
    red = next(layer for layer in project.layers if layer.layer_type == "Scan" and layer.index > 1).regions[0]
    assert (red.x - dx, red.y - dy, red.width, red.height) == pytest.approx((2.5, 2.5, 15.0, 12.5), abs=0.01)   # pixels 10..70 at 0.25 mm
    green_x = 150 * 0.25 + dx
    assert not any(region.x >= green_x - 0.01 and region.y - dy < 15.1 for layer in project.layers if layer.index > 1 for region in layer.regions)
    assert project.identifier == plan["plan_identifier"] and "Lens: F-Theta 174" in project.notes and "Titanium: Grade 2 sheet" in project.notes
    stored = c["client"].get(f"/api/vector/{j['id']}/exports/1")
    assert stored.status_code == 200 and stored.content == r.content
    listed = c["client"].get(f"/api/vector/{j['id']}").json()["exports"]
    assert [(e["number"], e["document_version"], e["layers"]) for e in listed] == [(1, 4, 3)] and "path" not in listed[0]


def test_settings_can_be_chosen_for_a_group_only_from_its_fitting_recipes(job):
    c, j, entries = job, job["job"], job["entries"]
    group = by_colour(j, GREEN)[0]["layer_key"]
    bad = c["client"].post(f"/api/vector/{j['id']}/edit", json={"op": "set_settings", "group": group, "knowledge_id": entries["Cut"]["id"]})
    assert bad.status_code == 422 and "LightBurn mode fits" in bad.json()["error"]       # a line recipe never fills an area
    other = c["client"].post(f"/api/vector/{j['id']}/edit", json={"op": "set_settings", "group": group, "knowledge_id": entries["Scan-other"]["id"]})
    assert other.status_code == 422                                                       # another titanium stock is not evidence
    j = edit(c, j, op="set_settings", group=group, knowledge_id=entries["Scan"]["id"])
    green = by_colour(j, GREEN)[0]
    assert green["status"] == "chosen" and green["knowledge_id"] == entries["Scan"]["id"] and green["match_error"] > 8
    j = edit(c, j, op="set_settings", group=group, knowledge_id=None)
    assert by_colour(j, GREEN)[0]["status"] == "weak"


def test_a_region_whose_task_needs_another_mode_than_its_group_is_weak_until_it_gets_a_group_of_its_own(job):
    c, j, entries = job, job["job"], job["entries"]
    small = min(by_colour(j, BLACK), key=lambda r: r["pixels"])
    j = edit(c, j, op="set_task", region=small["id"], task="line")
    row = next(r for r in j["regions"] if r["id"] == small["id"])
    assert row["status"] == "weak" and "settings group of its own" in row["note"]
    j = edit(c, j, op="set_layer", region=small["id"], layer_key="strokes")
    row = next(r for r in j["regions"] if r["id"] == small["id"])
    assert (row["status"], row["layer_key"], row["knowledge_id"]) == ("matched", "strokes", entries["Cut"]["id"])


def test_without_a_line_recipe_on_the_stock_a_line_is_weak_and_cannot_become_a_colour_target(job):
    c, w = job, job["w"]
    other = c["store"].one("SELECT id FROM material_profile WHERE name='Grade 5 sheet'")["id"]
    r = c["client"].post("/api/vector", data={"device_id": w["setup"][0], "lens_id": w["setup"][1], "material_id": other, "name": "Lines",
                                              "width_mm": 50, "strategy": "line", "threshold": 8},
                         files={"image": ("a.png", artwork(), "image/png")})
    j = r.json()
    assert r.status_code == 201 and j["regions"] and all(row["outline"] == "centre-line" and row["status"] == "weak" for row in j["regions"])
    assert "engraves a line (LightBurn Line mode)" in j["regions"][0]["note"]
    bad = c["client"].post(f"/api/vector/{j['id']}/edit", json={"op": "to_designer", "region": j["regions"][0]["id"]})
    assert bad.status_code == 422 and "line test plate" in bad.json()["error"]


@pytest.mark.parametrize("op,message", [({"op": "delete", "region": "r99"}, "there is no region"), ({"op": "merge", "regions": ["r1"]}, "two different"),
                                        ({"op": "fly"}, "unknown edit operation"), ({"op": "revert", "version": 9}, "no such version"),
                                        ({"op": "set_settings", "group": "nope", "knowledge_id": 1}, "no settings group")])
def test_invalid_edits_are_refused_and_change_nothing(job, op, message):
    c, j = job, job["job"]
    r = c["client"].post(f"/api/vector/{j['id']}/edit", json=op)
    assert r.status_code == 422 and message in r.json()["error"]
    after = c["client"].get(f"/api/vector/{j['id']}").json()
    assert after["document"]["version"] == 1 and len(after["history"]) == 1


def test_a_job_refuses_more_colours_than_lightburn_layers_and_requires_its_inputs(job):
    c, w = job, job["w"]
    form = {"device_id": w["setup"][0], "lens_id": w["setup"][1], "material_id": job["stock"]["id"], "name": "X", "width_mm": 50,
            "strategy": "color", "n_colors": 29, "threshold": 8, "clean": "true"}
    r = c["client"].post("/api/vector", data=form, files={"image": ("a.png", artwork(), "image/png")})
    assert r.status_code == 422 and "at most 28 colours" in r.json()["error"]
    r = c["client"].post("/api/vector", data={**form, "n_colors": 4, "strategy": "tonal"}, files={"image": ("a.png", artwork(), "image/png")})
    assert r.status_code == 422 and "strategy must be one of" in r.json()["error"]
    r = c["client"].post("/api/vector", data={**form, "n_colors": 4, "material_id": 999}, files={"image": ("a.png", artwork(), "image/png")})
    assert r.status_code == 422 and "titanium stock was not found" in r.json()["error"]


def test_the_palette_of_a_job_is_the_stock_s_recipes_in_every_lightburn_mode(job):
    w = job["w"]
    r = job["client"].get(f"/api/vector/palette?device_id={w['setup'][0]}&lens_id={w['setup'][1]}&material_id={job['stock']['id']}")
    assert sorted(e["mode"] for e in r.json()) == ["Cut", "OffsetFill", "Scan"] and all(len(e["srgb"]) == 3 for e in r.json())
