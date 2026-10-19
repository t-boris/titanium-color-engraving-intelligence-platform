"""REQ-042, REQ-043 (DEC-073..DEC-077): a photograph becomes a vector work - split into gapless colour regions, coloured
with measured titanium colours (automatic modes, hand choices, unresolved colours), then one LightBurn file."""
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import obs
from titanium_platform import color, engraving_time, faces, lightburn as lb, model, plans as pl, segment as sg, setup as su, vector_job
from titanium_platform.api.app import create_app

SVG = "{http://www.w3.org/2000/svg}"
PAPER, RED, YELLOW, BLUE, GREEN = (235, 230, 215), (200, 40, 40), (240, 200, 40), (30, 40, 200), (40, 150, 70)


def lab(rgb):
    return [float(v) for v in color.srgb8_to_lab(np.array(rgb, float))]


def picture() -> bytes:
    """A red ring (its hole is paper), a turned blue ellipse, a green band and a yellow disc on paper."""
    img = np.full((180, 240, 3), PAPER, np.uint8)
    cv2.circle(img, (60, 70), 45, RED, -1)
    cv2.circle(img, (60, 70), 18, PAPER, -1)
    cv2.ellipse(img, (170, 55), (50, 25), 25, 0, 360, BLUE, -1)
    cv2.rectangle(img, (0, 130), (240, 180), GREEN, -1)
    cv2.circle(img, (195, 150), 22, YELLOW, -1)
    return cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


@pytest.fixture
def work(tmp_path):
    """Measured colours of one laser, lens and titanium: paper twice (slow and exact, fast and 2 dE off), red, blue,
    green, and yellow measured only as photographed; a red of another titanium stock."""
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    pl.save_marker_layer_settings(store, 20, 60, 300)
    ti = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1, surface="brushed")["id"]
    other = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1, surface="brushed")["id"]
    for rgb, power in ((PAPER, 10), (RED, 20), (BLUE, 30), (GREEN, 40)):
        obs.add(store, w, lab(rgb), power=power, speed=500, line_interval=0.02, material_id=ti, layer_type="Scan")
    obs.add(store, w, lab(RED), power=20, speed=500, line_interval=0.02, material_id=ti, layer_type="Scan")    # red engraved twice
    fast_paper = lab(PAPER)
    fast_paper[0] -= 2
    obs.add(store, w, fast_paper, power=10, speed=3000, line_interval=0.02, material_id=ti, layer_type="Scan")
    obs.add(store, w, lab(YELLOW), power=60, speed=2000, line_interval=0.02, material_id=ti, layer_type="Scan", model_eligible=0)
    obs.add(store, w, lab(RED), power=70, speed=4000, line_interval=0.02, material_id=other, layer_type="Scan")
    with TestClient(app) as client:
        yield {"client": client, "store": store, "w": w, "ti": ti, "app": app}
    store.close()


def create(c, **extra):
    data = {"device_id": c["w"]["setup"][0], "lens_id": c["w"]["setup"][1], "material_id": c["ti"], "name": "Portrait", "width_mm": 60,
            "strategy": "photo", "n_colors": 5, "threshold": 6, "detail": "medium", **extra}
    return c["client"].post("/api/vector", data=data, files={"image": ("photo.png", picture(), "image/png")})


@pytest.fixture
def job(work):
    r = create(work)
    assert r.status_code == 201, r.text
    return r.json()


def colouring(c, job, **op):
    r = c["client"].post(f"/api/vector/{job['id']}/colouring", json=op)
    assert r.status_code == 200, r.text
    return r.json()


def by_rgb(job, rgb):
    return next(col for col in job["colours"] if tuple(col["srgb"]) == rgb)


def palette_ids(c):
    entries = c["client"].get(f"/api/vector-palette?device_id={c['w']['setup'][0]}&lens_id={c['w']['setup'][1]}&material_id={c['ti']}").json()["entries"]
    return {(round(e["lab"][0]), e["parameters"]["speed"]): e["id"] for e in entries}


# -- split ---------------------------------------------------------------------------------------------------------------------
def test_a_photograph_is_split_and_previewed_in_its_source_colours_before_any_export(work, job):
    j = job
    assert j["mode"] == pl.MODE_VECTOR and j["strategy"] == "photo" and j["plan_identifier"].startswith("TCE-A-")
    doc = j["document"]
    assert doc["colours"] == 5 and doc["n_colors"] == 5 and doc["regions"] >= 6 and doc["faces"] == {"searched": True, "found": 0, "error": None}
    assert doc["min_area_mm2"] == pytest.approx(60 * 45 / 3000) and doc["superpixels"] == vector_job.DETAIL["medium"][0]
    assert j["clean_layer"]["name"].startswith("CLEAN-CROSSHATCH-") and j["layer_cap"] == 29
    svg = work["client"].get(f"/api/vector/{j['id']}/split.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    paths = ET.fromstring(svg.text).findall(f"{SVG}path")
    assert len(paths) == doc["regions"] and all(p.get("data-region") and p.get("data-color") for p in paths)
    assert {p.get("fill") for p in paths} == {"#{:02x}{:02x}{:02x}".format(*rgb) for rgb in (PAPER, RED, YELLOW, BLUE, GREEN)}
    assert "arcs" not in json.dumps(j) and len(json.dumps(j)) < 40_000                 # the geometry goes once, as the SVG
    plan = pl.get_plan(work["store"], j["id"])
    assert len(plan["history"]) == 1 and plan["history"][0]["op"]["op"] == "split"


def test_the_split_settings_and_important_areas_are_used_when_the_picture_is_split_again(work, job, monkeypatch):
    c, j = work, job
    area = {"ellipse": {"center": [60, 70], "axes": [30, 30], "angle": 0}}
    r = c["client"].post(f"/api/vector/{j['id']}/split", json={"n_colors": 4, "detail": "fine", "tolerance_mm": 0.05, "faces": False,
                                                               "manual": [area]})
    again = r.json()
    assert r.status_code == 200 and again["document"]["version"] == 2 and again["document"]["colours"] == 4
    assert again["split"]["manual"][0]["kind"] == "manual" and again["document"]["important_regions"] >= 1
    assert again["document"]["faces"] == {"searched": False, "found": 0, "error": None}
    assert again["document"]["min_area_mm2"] == pytest.approx(60 * 45 / 7500) and again["variants"][0]["mode"] == "closest"
    for body, message in [({"n_colors": 30}, "choose from 2 to 29 colours"), ({"n_colors": 4, "detail": "huge"}, "coarse, medium or fine"),
                          ({"n_colors": 4, "tolerance_mm": -1}, "smoothing must be a non-negative"),
                          ({"n_colors": 4, "manual": [{"ellipse": {"center": [1, 2]}}]}, "an important area must be"),
                          ({"n_colors": 4, "removed": [0]}, "one of the areas found")]:
        bad = c["client"].post(f"/api/vector/{j['id']}/split", json=body)
        assert bad.status_code == 422 and message in bad.json()["error"], body
    assert c["client"].get(f"/api/vector/{j['id']}").json()["document"]["version"] == 2


def test_faces_found_once_can_be_removed_and_the_picture_split_without_them(work, monkeypatch):
    box = [[100.0, 40.0], [160.0, 40.0], [160.0, 110.0], [100.0, 110.0]]
    found = faces.FaceSearch(faces.face_areas(box, [[115.0, 65.0], [145.0, 65.0]], [[118.0, 95.0], [142.0, 95.0]], 0.9), 1)
    monkeypatch.setattr(faces, "important_areas", lambda img, **kw: found)
    j = create(work).json()
    assert j["document"]["faces"]["found"] == 1 and [a["kind"] for a in j["areas"]["detected"]] == ["face", "eye", "eye", "lips"]
    fine = j["document"]["important_regions"]
    r = work["client"].post(f"/api/vector/{j['id']}/split", json={"n_colors": 5, "removed": [1, 2, 3]}).json()
    assert [a["removed"] for a in r["areas"]["detected"]] == [False, True, True, True] and r["document"]["important_regions"] <= fine


def test_a_job_with_markers_holds_28_colours_and_cleans_first(work):
    r = create(work, n_colors=29, markers="true")
    assert r.status_code == 422 and r.json()["error"] == "choose from 2 to 28 colours: the cleaning takes one LightBurn layer and the markers another"
    assert create(work, n_colors=28, markers="true").status_code == 201
    assert create(work, threshold="").status_code == 422          # no saved tolerance and none given: never invented (DEC-030)


# -- colouring -----------------------------------------------------------------------------------------------------------------
def test_each_colour_takes_the_fastest_measured_colour_within_the_tolerance_and_says_how_it_was_measured(work, job):
    ids, j = palette_ids(work), job
    paper = by_rgb(j, PAPER)
    assert paper["status"] == "automatic" and paper["how"] == "fastest_within_tolerance" and paper["entry_id"] == ids[(round(lab(PAPER)[0]) - 2, 3000)]
    assert paper["delta_e"] == pytest.approx(2.0, abs=0.05)
    red = by_rgb(j, RED)
    entry = j["entries"][red["entry_id"]]
    assert entry["basis"] == "chart" and entry["engravings"] == 2 and entry["photographs"] == 2 and entry["confidence"] == pytest.approx(0.5)
    assert entry["stability"]["assessed"] and entry["time_s_per_cm2"] == pytest.approx(
        engraving_time.per_area({"speed": 500, "line_interval": 0.02})["s_per_cm2"])
    assert j["entries"][paper["entry_id"]]["stability"]["assessed"] is False and j["entries"][paper["entry_id"]]["confidence"] is None
    assert all(e["id"] != ids.get((round(lab(RED)[0]), 4000)) for e in j["entries"].values())   # another titanium is not this palette


def test_a_colour_without_a_measured_colour_in_tolerance_is_proposed_and_blocks_the_file_until_accepted(work, job):
    c, j = work, job
    yellow = by_rgb(j, YELLOW)
    assert yellow["status"] == "proposed" and yellow["how"] == "nearest" and yellow["delta_e"] > 6
    assert j["entries"][yellow["entry_id"]]["basis"] != "as-shot"          # measured as photographed: out of the automatic choice
    assert j["unresolved"] == {"colours": 1, "regions": 1, "share": pytest.approx(yellow["pixels"] / (60 * 45 / 0.0625)), "indexes": [yellow["index"]],
                               "missing_regions": 0}
    assert j["export_blocked"] == ("1 colour(s) in 1 region(s) have no titanium colour within the delta E tolerance: accept the proposed "
                                   "colour, choose another or exclude it before export") and j["status"] == "Draft"
    refused = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert refused.status_code == 422 and refused.json() == {"error": j["export_blocked"], "kind": "invalid"}
    j = colouring(c, j, op="accept", colour=yellow["index"])
    assert by_rgb(j, YELLOW)["status"] == "accepted" and j["export_blocked"] is None and j["status"] == "Ready to export"
    j = colouring(c, j, op="undo")
    assert by_rgb(j, YELLOW)["status"] == "proposed"
    j = colouring(c, j, op="exclude_colour", colour=yellow["index"])
    assert by_rgb(j, YELLOW)["status"] == "excluded" and j["export_blocked"] is None
    j = colouring(c, j, op="include_colour", colour=yellow["index"])
    j = colouring(c, j, op="accept_all")
    assert j["unresolved"]["colours"] == 0
    bad = c["client"].post(f"/api/vector/{j['id']}/colouring", json={"op": "accept_all"})
    assert bad.status_code == 422 and bad.json()["error"] == "there is no proposed titanium colour to accept"


def test_including_colours_measured_as_photographed_lets_the_automatic_choice_reach_them(work, job):
    j = colouring(work, job, op="settings", tolerance_de=6, include_as_shot=True)
    yellow = by_rgb(j, YELLOW)
    assert yellow["status"] == "automatic" and j["entries"][yellow["entry_id"]]["basis"] == "as-shot" and j["settings"]["include_as_shot"]
    j = colouring(work, j, op="settings", tolerance_de=6, max_time=5, include_as_shot=True)   # only the fast paper and the yellow
    assert j["settings"]["max_time"] == 5 and by_rgb(j, RED)["status"] == "proposed" and by_rgb(j, PAPER)["status"] == "automatic"
    assert all(j["entries"][col["entry_id"]]["time_s_per_cm2"] <= 5 for col in j["colours"])
    slow = work["client"].post(f"/api/vector/{j['id']}/colouring", json={"op": "settings", "tolerance_de": 6, "max_time": 0.001})
    assert slow.status_code == 422 and slow.json()["error"] == "no colour of the palette engraves within 0.001 s per square centimetre"


def test_every_recolouring_mode_gives_a_variant_that_can_be_restored_and_undone(work, job):
    c, j = work, job
    assert [v["number"] for v in j["variants"]] == [1] and j["colouring"]["variant"] == 1 and j["undo"] == 0
    j = colouring(c, j, op="assign", mode="tonality")
    order = sorted(j["colours"], key=lambda col: col["lab"][0])
    lights = [j["entries"][col["entry_id"]]["lab"][0] for col in order]
    assert lights == sorted(lights)                                                     # the lightness order is kept
    j = colouring(c, j, op="assign", mode="random")
    j = colouring(c, j, op="assign", mode="random")
    seeds = [v["seed"] for v in j["variants"] if v["mode"] == "random"]
    assert seeds == [1, 2]                                                              # each press: a new seed
    j = colouring(c, j, op="assign", mode="fewer_layers")
    assert j["totals"]["recipes"] <= j["variants"][0]["totals"]["recipes"]
    assert [v["mode"] for v in j["variants"]] == ["closest", "tonality", "random", "random", "fewer_layers"] and j["colouring"]["variant"] == 5
    random_two = j["variants"][3]
    j = colouring(c, j, op="restore", variant=random_two["number"])
    assert j["colouring"]["variant"] == 4 and j["totals"] == random_two["totals"]
    j = colouring(c, j, op="undo")
    assert j["colouring"]["variant"] == 5
    j = colouring(c, j, op="restore", variant=1)
    assert by_rgb(j, PAPER)["how"] == "fastest_within_tolerance"
    for op, message in [({"op": "assign", "mode": "best"}, "recolouring mode"), ({"op": "restore", "variant": 99}, "no such variant"),
                        ({"op": "fly"}, "unknown edit operation")]:
        bad = c["client"].post(f"/api/vector/{j['id']}/colouring", json=op)
        assert bad.status_code == 422 and message in bad.json()["error"]


def test_a_whole_colour_or_one_region_can_be_given_another_titanium_colour_by_hand(work, job):
    c, j, ids = work, job, palette_ids(work)
    blue = by_rgb(j, BLUE)
    green_entry = by_rgb(j, GREEN)["entry_id"]
    j = colouring(c, j, op="set_colour", colour=blue["index"], entry_id=green_entry)
    assert by_rgb(j, BLUE)["status"] == "hand" and by_rgb(j, BLUE)["entry_id"] == green_entry
    j = colouring(c, j, op="assign", mode="random")
    assert by_rgb(j, BLUE)["entry_id"] == green_entry                                   # every mode keeps the operator's choice
    j = colouring(c, j, op="set_colour", colour=blue["index"], entry_id=None)
    assert by_rgb(j, BLUE)["status"] in ("automatic", "proposed")
    svg = ET.fromstring(c["client"].get(f"/api/vector/{j['id']}/split.svg").text)
    region = next(p.get("data-region") for p in svg.findall(f"{SVG}path") if p.get("data-color") == str(by_rgb(j, RED)["index"]))
    yellow_as_shot = ids[(round(lab(YELLOW)[0]), 2000)]
    j = colouring(c, j, op="set_region", region=region, entry_id=yellow_as_shot)       # a colour measured as photographed, by hand
    assert j["colouring"]["regions"] == {region: yellow_as_shot} and j["entries"][yellow_as_shot]["automatic"] is False
    j = colouring(c, j, op="exclude_region", region=region)
    assert j["colouring"]["excluded_regions"] == [region]
    j = colouring(c, j, op="include_region", region=region)
    j = colouring(c, j, op="set_region", region=region, entry_id=None)
    assert j["colouring"]["regions"] == {}
    for op, message in [({"op": "set_region", "region": "r999", "entry_id": green_entry}, "there is no region"),
                        ({"op": "set_colour", "colour": 99, "entry_id": green_entry}, "no such source colour"),
                        ({"op": "set_colour", "colour": 0, "entry_id": "nope"}, "must be a measured colour")]:
        bad = c["client"].post(f"/api/vector/{j['id']}/colouring", json=op)
        assert bad.status_code == 422 and message in bad.json()["error"]
    plan = pl.get_plan(c["store"], j["id"])
    assert [h["op"]["op"] for h in plan["history"][1:4]] == ["set_colour", "assign", "set_colour"]


# -- the file -------------------------------------------------------------------------------------------------------------------
def regions_of(project) -> list[list]:
    return [[p.polygon] + p.holes for layer in project.layers if layer.index > 0 for p in layer.regions]


def test_the_file_cleans_first_has_one_layer_per_recipe_with_its_full_settings_and_gapless_closed_regions(work, job):
    c, j = work, job
    j = colouring(c, j, op="accept_all")
    assert j["time"]["estimate"] and j["time"]["complete"] and j["time"]["layers"][0]["index"] == 0
    assert j["time"]["seconds"] == pytest.approx(sum(row["seconds"] for row in j["time"]["layers"]))
    r = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    project = lb.parse_bytes(r.content)
    layers = sorted(project.layers, key=lambda layer: layer.index)
    assert layers[0].index == 0 and layers[0].name.startswith("CLEAN-CROSSHATCH-") and layers[0].cross_hatch
    colour_layers = layers[1:]
    assert [layer.index for layer in colour_layers] == list(range(1, len(colour_layers) + 1)) and len(colour_layers) <= 29
    assert len(colour_layers) == len(j["layers"]) == 4                                   # paper (and accepted yellow), red, blue, green
    for layer, planned in zip(colour_layers, j["layers"]):
        assert (layer.name, layer.power, layer.speed, layer.layer_type) == (planned["name"], planned["parameters"]["power"],
                                                                            planned["parameters"]["speed"], "Scan")
        assert layer.line_interval == pytest.approx(planned["parameters"]["line_interval"]) and layer.frequency_khz == planned["parameters"]["frequency"]
        assert all(region.kind == "path" and region.closed for region in layer.regions) and len(layer.regions) == planned["region_count"]
    assert max(len(p.holes) for layer in colour_layers for p in layer.regions) >= 1        # the ring keeps its hole
    cov = sg.coverage(regions_of(project), 60, 45, 16)
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005
    assert project.identifier == j["plan_identifier"] and "Lens: F-Theta 174" in project.notes and "Titanium: Grade 2 sheet" in project.notes
    after = c["client"].get(f"/api/vector/{j['id']}").json()
    assert after["status"] == "Exported" and after["exports"][0]["variant"] == 1 and after["exports"][0]["layers"] == 4
    assert after["exports"][0]["seconds"] == pytest.approx(j["time"]["seconds"]) and "path" not in after["exports"][0]
    plan = pl.get_plan(c["store"], j["id"])
    assert plan["exports"][0]["colouring"]["groups"] and "path" in plan["exports"][0]           # kept with the colouring it came from
    stored = c["client"].get(f"/api/vector/{j['id']}/exports/1")
    assert stored.status_code == 200 and stored.content == r.content
    assert c["client"].get(f"/api/plans/{j['id']}/export.lbrn2").status_code == 200          # the plan screen exports it the same way


def test_a_file_with_markers_puts_them_on_c01_and_the_colours_after(work, job):
    c, j = work, job
    c["client"].put(f"/api/plans/{j['id']}/markers", json={"enabled": True})
    j = colouring(c, j, op="exclude_colour", colour=by_rgb(j, YELLOW)["index"])
    assert j["layer_cap"] == 28 and [layer["index"] for layer in j["layers"]] == [2, 3, 4, 5]
    project = lb.parse_bytes(c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").content)
    names = {layer.index: layer.name for layer in project.layers}
    assert names[0].startswith("CLEAN-") and names[1] == "Markers" and sorted(names) == [0, 1, 2, 3, 4, 5]
    yellow_px = by_rgb(j, YELLOW)["pixels"] / (60 * 45 / 0.0625)
    dx, dy = pl.export_offset(pl.get_plan(c["store"], j["id"]))
    back = [[[(x - dx, y - dy) for x, y in loop] for loop in [p.polygon] + p.holes] for layer in project.layers if layer.index > 1 for p in layer.regions]
    cov = sg.coverage(back, 60, 45, 16)
    assert cov["uncovered"] == pytest.approx(yellow_px, abs=0.005) and cov["overlap"] < 0.005   # only the excluded disc is left


@pytest.mark.parametrize("markers, cap", [(False, 29), (True, 28)])
def test_more_recipes_than_the_output_layers_left_after_cleaning_and_markers_are_refused(markers, cap):
    state = {"unresolved": {"colours": 0, "regions": 0}, "missing_regions": [], "layers": [{}] * cap}
    assert vector_job._blocker_photo({"markers_enabled": markers}, state) is None
    state["layers"] = [{}] * (cap + 1)
    assert vector_job._blocker_photo({"markers_enabled": markers}, state) == f"{cap + 1} different recipes need more LightBurn layers than the {cap} available"


def test_a_full_recipe_with_its_lightburn_tags_is_written_from_the_observation(work):
    import recipes
    store, w, ti = work["store"], work["w"], work["ti"]
    gold = recipes.recipes(w["device"]["passport"])["Gold fill"]
    recipes.add(store, w, gold, lab(PAPER), material_id=ti, spread=0.2)       # an exact paper with sub-layers and every tag
    j = create(work).json()
    j = colouring(work, j, op="exclude_colour", colour=by_rgb(j, YELLOW)["index"])
    j = colouring(work, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=palette_ids(work)[(round(lab(PAPER)[0]), gold["speed"])])
    project = lb.parse_bytes(work["client"].get(f"/api/vector/{j['id']}/export.lbrn2").content)
    written = next(layer for layer in project.layers if layer.power == gold["power"] and layer.speed == gold["speed"])
    assert model.parameters_key(recipes.parameters(written, w["device"]["passport"])) == model.parameters_key(gold)


def test_the_old_tracing_strategies_still_make_jobs(work):
    for strategy in ("fill", "text", "line"):
        r = work["client"].post("/api/vector", data={"device_id": work["w"]["setup"][0], "lens_id": work["w"]["setup"][1], "material_id": work["ti"],
                                                     "name": "Old", "width_mm": 50, "strategy": strategy, "threshold": 8},
                                files={"image": ("a.png", picture(), "image/png")})
        assert r.status_code == 201 and r.json()["document"]["strategy"] == strategy and "svg" in r.json()
    traced = r.json()
    bad = work["client"].post(f"/api/vector/{traced['id']}/colouring", json={"op": "undo"})
    assert bad.status_code == 422 and bad.json()["error"] == "only a photograph split into colour regions is split and coloured this way"


# -- the screen, run in node over a small DOM with the server's real answers --------------------------------------------------
UI = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui"
TABLES = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-tasks.js", "i18n-data.js", "i18n-findings.js",
          "i18n-palette.js", "i18n-gaps.js"]
GLUE = ("const __screens = {}, __renders = []; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { __renders.push(1); };"
        "globalThis.__screens = __screens; globalThis.__renders = __renders;")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'hardware.js', {code: %(glue)s}, 'screens/vector-split.js', 'screens/vector-colours.js', 'screens/vector.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
(async () => {
  const out = {};
  const tree = await ctx.__screens.vector.render({query: {plan: String(data.id)}});
  await tick(); await tick();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run_screen(tmp_path, job, routes, body):
    (tmp_path / "data.json").write_text(json.dumps({"id": job["id"], "routes": routes}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body},
                      encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout)


def routes_of(c, j) -> dict:
    """The answers the screen asks for, taken from the real API."""
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    return {f"/api/vector/{j['id']}": {"status": 200, "json": view},
            f"/api/vector/{j['id']}/split.svg": {"status": 200, "text": c["client"].get(f"/api/vector/{j['id']}/split.svg").text, "type": "image/svg+xml"},
            f"/api/vector/{j['id']}/palette": {"status": 200, "json": c["client"].get(f"/api/vector/{j['id']}/palette").json()},
            f"/api/vector/{j['id']}/colouring": {"status": 200, "json": view}, f"/api/vector/{j['id']}/split": {"status": 200, "json": view}}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_screen_shows_the_three_steps_the_previews_side_by_side_and_a_short_unresolved_summary(work, job, tmp_path):
    out = run_screen(tmp_path, job, routes_of(work, job), """
  out.text = tree.textContent;
  const svgs = tree.querySelectorAll('svg');
  out.classes = svgs.map((s) => s.getAttribute('class'));
  const [split, titanium] = svgs.filter((s) => s.getAttribute('class') === 'vw-preview');
  out.split = split.querySelectorAll('path').map((p) => [p.getAttribute('data-color'), p.getAttribute('fill')]);
  out.titanium = titanium.querySelectorAll('path').map((p) => [p.getAttribute('data-color'), p.getAttribute('fill'), p.getAttribute('stroke')]);
  out.exportDisabled = byText(tree, 'button', 'Создать файл LightBurn').disabled;
  const toggle = byText(tree, 'button', 'показать');
  out.listHidden = toggle.parentNode.parentNode.querySelectorAll('div').find((d) => d.className === 'stack').hidden;
  await toggle.dispatch('click');
  out.listShown = !toggle.parentNode.parentNode.querySelectorAll('div').find((d) => d.className === 'stack').hidden && toggle.textContent === 'скрыть';
  out.links = tree.querySelectorAll('a').map((a) => a.getAttribute('href'));
""")
    text = out["text"]
    for part in ("1. Разбиение", "2. Цвета", "3. Файл LightBurn", "Оценка времени всей работы", "лицо не найдено",
                 "Не решено: цветов 1, областей 1", "Цветов без цвета титана в пределах допуска ΔE: 1 (областей: 1)", "самый быстрый в пределах допуска"):
        assert part in text, part
    assert not any(bad in text for bad in ("null", "undefined", "NaN", "без перевода", "[object")), text[:3000]
    assert out["classes"].count("vw-preview") == 2 and "vw-areas" in out["classes"]
    j = job
    yellow, paper = by_rgb(j, YELLOW)["index"], by_rgb(j, PAPER)["index"]
    assert {fill for colour, fill in out["split"] if colour == str(yellow)} == {"#{:02x}{:02x}{:02x}".format(*YELLOW)}
    assert all(fill.startswith("url(#vw-open-") and stroke == "#d32f2f" for colour, fill, stroke in out["titanium"] if colour == str(yellow))
    paper_rgb = "rgb({},{},{})".format(*j["entries"][by_rgb(j, PAPER)["entry_id"]]["srgb"])
    assert all(fill == paper_rgb for colour, fill, _ in out["titanium"] if colour == str(paper))
    assert out["exportDisabled"] and out["listHidden"] and out["listShown"]
    assert not any((href or "").startswith("/api") for href in out["links"])        # nothing on this screen navigates to the API


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_region_clicked_in_the_titanium_preview_gets_a_colour_picked_from_the_palette(work, job, tmp_path):
    out = run_screen(tmp_path, job, routes_of(work, job), """
  const titanium = tree.querySelectorAll('svg').filter((s) => s.getAttribute('class') === 'vw-preview')[1];
  const path = titanium.querySelectorAll('path')[0];
  out.region = path.getAttribute('data-region');
  await path.dispatch('click');
  const dialog = ctx.document.body.querySelectorAll('div').find((d) => d.className === 'modal');
  out.title = dialog.querySelector('h3').textContent;
  out.buttons = dialog.querySelectorAll('button').map((b) => b.textContent);
  await byText(dialog, 'button', 'Цвет этой области').dispatch('click');
  await tick();
  const picker = ctx.document.body.querySelectorAll('div').find((d) => d.className === 'modal');
  const swatches = picker.querySelectorAll('button').filter((b) => b.className.startsWith('vw-swatch'));
  out.swatches = swatches.length;
  out.asShot = swatches.filter((b) => b.className.includes('as-shot')).length;
  await swatches[1].dispatch('click');
  await byText(picker, 'button', 'Применить').dispatch('click');
  out.posted = ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, JSON.parse(r.body)]);
  out.renders = ctx.__renders.length;
""")
    assert out["title"] == f"Область {out['region']}" and {"Цвет этой области", "Цвет всей группы", "Исключить область"} <= set(out["buttons"])
    palette = work["client"].get(f"/api/vector/{job['id']}/palette").json()
    assert out["swatches"] == len(palette) and out["asShot"] == 1
    (path, body), = out["posted"]
    assert path == f"/api/vector/{job['id']}/colouring" and body["op"] == "set_region" and body["region"] == out["region"]
    assert body["entry_id"] in {e["id"] for e in palette} and out["renders"] == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_an_area_dragged_on_the_picture_is_sent_in_picture_pixels_when_split_again(work, job, tmp_path):
    out = run_screen(tmp_path, job, routes_of(work, job), """
  const overlay = tree.querySelectorAll('svg').find((s) => s.getAttribute('class') === 'vw-areas');
  await overlay.dispatch('pointerdown', {clientX: 10, clientY: 10});
  await overlay.dispatch('pointermove', {clientX: 50, clientY: 40});
  await overlay.dispatch('pointerup', {clientX: 50, clientY: 40});
  out.drawn = overlay.querySelectorAll('polygon').map((p) => p.getAttribute('class'));
  out.pending = tree.textContent.includes('Изменения областей применятся после');
  await byText(tree, 'button', 'Разбить заново').dispatch('click');
  out.posted = ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, JSON.parse(r.body)]);
""")
    assert out["drawn"] == ["vw-area manual"] and out["pending"]
    (path, body), = out["posted"]
    assert path == f"/api/vector/{job['id']}/split" and body["manual"] == [{"polygon": [[24, 18], [120, 18], [120, 72], [24, 72]]}]
    assert body["n_colors"] == 5 and body["detail"] == "medium" and body["faces"] is True and body["removed"] == []
    r = work["client"].post(f"/api/vector/{job['id']}/split", json=body)            # the server takes what the screen sends
    assert r.status_code == 200 and r.json()["split"]["manual"][0]["polygon"][0] == [24, 18]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_an_export_refused_by_the_server_is_shown_translated_and_the_file_is_fetched_not_opened(work, job, tmp_path):
    j = colouring(work, job, op="accept_all")
    routes = routes_of(work, j)
    routes[f"/api/vector/{j['id']}/export.lbrn2"] = {"status": 422, "json": {"error": "every region is excluded: there is nothing to engrave", "kind": "invalid"}}
    out = run_screen(tmp_path, j, routes, """
  const button = byText(tree, 'button', 'Создать файл LightBurn');
  out.disabled = button.disabled;
  await button.dispatch('click');
  out.toast = ctx.document.body.querySelectorAll('div').filter((d) => (d.className || '').startsWith('toast')).map((d) => d.textContent);
  out.requests = ctx.requests.map((r) => r.method + ' ' + r.path);
  out.reenabled = !button.disabled;
""")
    assert out["disabled"] is False and out["reenabled"]
    assert any("Все области исключены: гравировать нечего" in t for t in out["toast"]) and not any("every region" in t for t in out["toast"])
    assert f"GET /api/vector/{j['id']}/export.lbrn2" in out["requests"]
