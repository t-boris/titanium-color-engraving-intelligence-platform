"""REQ-042, REQ-043 (DEC-073..DEC-077): a photograph becomes a vector work - split into gapless colour regions, coloured
with measured titanium colours (automatic modes, hand choices, colours beyond the tolerance), then one LightBurn file; its
colour editor (feature vector-work-colour-editor: REQ-043..REQ-049, DEC-001, DEC-075..DEC-077): the brush, merges, undo
and redo."""
import copy
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import obs
from titanium_platform import color, conversion as cv, engraving_time, faces, lightburn as lb, model, palette, plans as pl, row_length, segment as sg, setup as su
from titanium_platform import vector_job
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


def test_a_colour_measured_on_another_plate_of_the_same_material_is_a_colour_of_the_work(work):
    """Plates of one material are no difference (REQ-057, DEC-088): a red of another plate (other name, thickness and surface) of the same
    grade is in the palette and, being as exact, as confident (engraved twice, like the red of the work's own plate) and faster, is what the
    red of the picture takes; a red of another grade is not."""
    c = work
    plate = su.save_material(c["store"], "Big plate", grade="Grade 2", thickness_mm=3, surface="polished")["id"]
    for _ in range(2):
        obs.add(c["store"], c["w"], lab(RED), power=70, speed=4000, line_interval=0.02, material_id=plate, layer_type="Scan")
    fast_red = palette_ids(c)[(round(lab(RED)[0]), 4000)]
    j = create(c).json()
    assert by_rgb(j, RED)["entry_id"] == fast_red and fast_red in j["entries"]


def colouring(c, job, **op):
    r = c["client"].post(f"/api/vector/{job['id']}/colouring", json=op)
    assert r.status_code == 200, r.text
    return r.json()


def by_rgb(job, rgb):
    return next(col for col in job["colours"] if tuple(col["srgb"]) == rgb)


def palette_ids(c):
    entries = c["client"].get(f"/api/vector-palette?device_id={c['w']['setup'][0]}&lens_id={c['w']['setup'][1]}&material_id={c['ti']}").json()["entries"]
    return {(round(e["lab"][0]), e["parameters"]["speed"]): e["id"] for e in entries}


def document_of(c, j) -> dict:
    """The job's current split as stored."""
    return json.loads(Path(pl.get_plan(c["store"], j["id"])["document_path"]).read_text(encoding="utf-8"))


def regions_in(document, index) -> list[str]:
    """The regions of one source colour, in the document's order."""
    return [r["id"] for r in document["regions"] if r["color"] == index]


def refused(c, j, op, message):
    r = c["client"].post(f"/api/vector/{j['id']}/colouring", json=op)
    assert r.status_code == 422 and r.json()["error"] == message, (op, r.text)


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


def test_the_splitting_algorithm_is_chosen_when_the_work_is_made_and_when_it_is_split_again(work, job):
    """Feature vector-detail-and-colour-control, DEC-076, DEC-082: slic, tonal, planes or seeds; a level of detail is not an algorithm."""
    c, j = work, job
    assert j["split"]["algorithm"] == "slic" and j["document"]["algorithm"] == "slic"                  # the default
    made = create(work, algorithm="seeds").json()
    assert made["split"]["algorithm"] == "seeds" and made["document"]["algorithm"] == "seeds" and made["document"]["regions"] >= 6
    again = c["client"].post(f"/api/vector/{j['id']}/split", json={"n_colors": 5, "algorithm": "seeds"}).json()
    assert again["split"]["algorithm"] == "seeds" and again["document"]["algorithm"] == "seeds" and again["document"]["version"] == 2
    assert (again["undo"], again["redo"], len(again["variants"])) == (0, 0, 1)                         # a fresh start, as for any split
    for name in ("tonal", "planes"):                                                                    # the two new methods travel the same way
        got = c["client"].post(f"/api/vector/{j['id']}/split", json={"n_colors": 5, "algorithm": name}).json()
        assert got["split"]["algorithm"] == name and got["document"]["algorithm"] == name and got["document"]["regions"] >= 6
        assert create(work, algorithm=name).json()["document"]["algorithm"] == name
    ops = [h["op"] for h in pl.get_plan(c["store"], j["id"])["history"] if h["op"]["op"] == "split"]
    assert [o["algorithm"] for o in ops] == ["slic", "seeds", "tonal", "planes"]                        # the history says which made each
    back = c["client"].post(f"/api/vector/{j['id']}/split", json={"n_colors": 5}).json()                # none given: the default
    assert back["split"]["algorithm"] == "slic" and back["document"]["algorithm"] == "slic"
    message = "the splitting algorithm must be slic, tonal, planes or seeds"
    for body in ({"n_colors": 5, "algorithm": "lsc"}, {"n_colors": 5, "algorithm": "coarse"}):
        bad = c["client"].post(f"/api/vector/{j['id']}/split", json=body)
        assert bad.status_code == 422 and bad.json()["error"] == message, body
    bad = create(work, algorithm="lsc")
    assert bad.status_code == 422 and bad.json()["error"] == message
    assert c["client"].get(f"/api/vector/{j['id']}").json()["document"]["version"] == 5                 # a refusal changes nothing
    assert message == "the splitting algorithm must be " + sg._listed(sg.ALGORITHMS)                      # the message names what the module offers


def test_a_work_split_before_the_choice_reads_as_slic_and_keeps_working(work, job):
    c, j, store = work, job, work["store"]
    plan = pl.get_plan(store, j["id"])                                                                   # as release 0.6.1 and earlier stored it
    del plan["split"]["algorithm"]
    document = document_of(c, j)
    del document["algorithm"]
    Path(plan["document_path"]).write_text(json.dumps(document), encoding="utf-8")
    cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    assert view["split"]["algorithm"] == "slic" and view["document"]["algorithm"] == "slic"
    again = c["client"].post(f"/api/vector/{j['id']}/split", json={k: v for k, v in view["split"].items() if k != "algorithm"}).json()
    assert again["split"]["algorithm"] == "slic" and again["document"]["version"] == 2


def test_faces_found_once_can_be_removed_and_the_picture_split_without_them(work, monkeypatch):
    box = [[100.0, 40.0], [160.0, 40.0], [160.0, 110.0], [100.0, 110.0]]
    found = faces.FaceSearch(faces.face_areas(box, [[115.0, 65.0], [145.0, 65.0]], [[118.0, 95.0], [142.0, 95.0]], 0.9), 1)
    monkeypatch.setattr(faces, "important_areas", lambda img, **kw: found)
    j = create(work).json()
    assert j["document"]["faces"]["found"] == 1 and [a["kind"] for a in j["areas"]["detected"]] == ["face", "eye", "eye", "lips"]
    fine = j["document"]["important_regions"]
    r = work["client"].post(f"/api/vector/{j['id']}/split", json={"n_colors": 5, "removed": [1, 2, 3]}).json()
    assert [a["removed"] for a in r["areas"]["detected"]] == [False, True, True, True] and r["document"]["important_regions"] <= fine


def test_the_face_search_is_on_unless_the_form_says_no_whatever_fastapi_does_with_a_missing_flag(work):
    # FastAPI 0.148 reads a missing bool form field as false; the route reads the flag itself (left out: searched)
    c = work
    assert create(c).json()["document"]["faces"]["searched"] is True
    for value, searched in [("false", False), ("off", False), ("true", True), ("", True)]:
        r = create(c, faces=value)
        assert r.status_code == 201, r.text
        assert r.json()["document"]["faces"]["searched"] is searched, value
    bad = create(c, faces="maybe")
    assert bad.status_code == 422 and bad.json()["error"] == "face search must be true or false"


def test_a_job_with_markers_holds_28_colours_and_cleans_first(work):
    r = create(work, n_colors=29, markers="true")
    assert r.status_code == 422 and r.json()["error"] == "choose from 2 to 28 colours: the cleaning takes one LightBurn layer and the markers another"
    assert create(work, n_colors=28, markers="true").status_code == 201
    assert create(work, threshold="").status_code == 422          # no saved tolerance and none given: never invented (DEC-030)


# -- colouring -----------------------------------------------------------------------------------------------------------------
def test_each_colour_takes_the_fastest_measured_colour_within_the_tolerance_and_says_how_it_was_measured(work, job):
    ids, j = palette_ids(work), job
    paper = by_rgb(j, PAPER)
    slow_paper, fast_paper_id = ids[(round(lab(PAPER)[0]), 500)], ids[(round(lab(PAPER)[0]) - 2, 3000)]
    yellow = by_rgb(j, YELLOW)
    # the yellow is nearest to the paper too, and no two colours share a layer (DEC-089): the two paper recipes go to one each
    assert paper["status"] == "automatic" and paper["how"] == "fastest_within_tolerance" and {paper["entry_id"], yellow["entry_id"]} == {slow_paper, fast_paper_id}
    assert paper["delta_e"] <= 2.05
    red = by_rgb(j, RED)
    entry = j["entries"][red["entry_id"]]
    assert entry["basis"] == "chart" and entry["engravings"] == 2 and entry["photographs"] == 2 and entry["confidence"] == pytest.approx(0.5)
    assert entry["stability"]["assessed"] and entry["time_s_per_cm2"] == pytest.approx(
        engraving_time.per_area({"speed": 500, "line_interval": 0.02})["s_per_cm2"])
    assert j["entries"][paper["entry_id"]]["stability"]["assessed"] is False and j["entries"][paper["entry_id"]]["confidence"] is None
    assert all(e["id"] != ids.get((round(lab(RED)[0]), 4000)) for e in j["entries"].values())   # another titanium is not this palette


def test_every_colour_is_coloured_from_the_start_and_one_beyond_the_tolerance_is_flagged_without_blocking_the_file(work, job):
    """Editor REQ-043, DEC-001: no acceptance step; the colour far from every measured one takes the nearest."""
    c, j = work, job
    yellow = by_rgb(j, YELLOW)
    assert yellow["status"] == "automatic" and yellow["how"] == "nearest" and yellow["delta_e"] > 6 and yellow["outside_tolerance"]
    assert j["entries"][yellow["entry_id"]]["basis"] != "as-shot"          # measured as photographed: out of the automatic choice
    assert all(col["status"] == "automatic" and col["entry_id"] for col in j["colours"])
    assert [col["index"] for col in j["colours"] if col["outside_tolerance"]] == [yellow["index"]]
    assert j["outside"] == {"colours": 1, "regions": 1, "share": pytest.approx(yellow["pixels"] / (60 * 45 / 0.0625)), "indexes": [yellow["index"]]}
    assert j["missing"] == {"regions": 0} and "unresolved" not in j and j["undo"] == 0 and j["redo"] == 0
    assert j["export_blocked"] is None and j["status"] == "Ready to export"
    assert c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").status_code == 200
    j = colouring(c, j, op="exclude_colour", colour=yellow["index"])
    assert by_rgb(j, YELLOW)["status"] == "excluded" and j["outside"]["colours"] == 0 and j["export_blocked"] is None
    for op in ({"op": "accept", "colour": yellow["index"]}, {"op": "accept_all"}):      # the acceptance step is gone
        bad = c["client"].post(f"/api/vector/{j['id']}/colouring", json=op)
        assert bad.status_code == 422 and bad.json()["error"] == f"unknown edit operation {op['op']!r}"


def test_the_file_is_blocked_only_by_a_colour_no_longer_measured_or_an_empty_palette(work, job, monkeypatch):
    c, j = work, job
    blue, region = by_rgb(j, BLUE), regions_in(document_of(c, j), by_rgb(j, RED)["index"])[0]
    gone = by_rgb(j, GREEN)["entry_id"]
    j = colouring(c, j, op="set_colour", colour=blue["index"], entry_id=gone)
    j = colouring(c, j, op="paint", scope="region", region=region, entry_id=gone)
    measured = vector_job._palette
    monkeypatch.setattr(vector_job, "_palette", lambda store, plan: [e for e in measured(store, plan) if e["id"] != gone])
    j = c["client"].get(f"/api/vector/{j['id']}").json()                               # the green recipe is no longer measured
    assert by_rgb(j, BLUE)["status"] == "missing" and by_rgb(j, GREEN)["status"] == "missing" and by_rgb(j, BLUE)["entry_id"] is None
    expected = by_rgb(j, BLUE)["open_regions"] + by_rgb(j, GREEN)["open_regions"] + 1
    assert j["missing"] == {"regions": expected} and j["export_blocked"] == (
        f"{expected} region(s) have a titanium colour that is no longer measured on this laser, lens and titanium stock: choose another before export")
    refused = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert refused.status_code == 422 and refused.json() == {"error": j["export_blocked"], "kind": "invalid"}
    bare = su.save_material(c["store"], "Bare sheet", grade="Grade 7", thickness_mm=1, surface="polished")["id"]
    empty = create(work, material_id=bare).json()                                      # nothing measured on titanium of this grade (DEC-088)
    assert empty["export_blocked"] == "no measured colour of this laser, lens and titanium stock fills an area" and empty["status"] == "Draft"
    assert {col["status"] for col in empty["colours"]} == {"missing"} and empty["palette_size"] == 0


def test_including_colours_measured_as_photographed_lets_the_automatic_choice_reach_them(work, job):
    j = colouring(work, job, op="settings", tolerance_de=6, include_as_shot=True)
    yellow = by_rgb(j, YELLOW)
    assert yellow["status"] == "automatic" and j["entries"][yellow["entry_id"]]["basis"] == "as-shot" and j["settings"]["include_as_shot"]
    j = colouring(work, j, op="settings", tolerance_de=6, max_time=5, include_as_shot=True)   # only the fast paper and the yellow
    assert j["settings"]["max_time"] == 5 and by_rgb(j, PAPER)["status"] == "automatic" and not by_rgb(j, PAPER)["outside_tolerance"]
    assert by_rgb(j, RED)["status"] == "automatic" and by_rgb(j, RED)["outside_tolerance"] and by_rgb(j, RED)["how"] == "nearest"
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
    j = colouring(c, j, op="assign", mode="closest")
    assert j["totals"]["recipes"] == j["variants"][0]["totals"]["recipes"] == len(j["colours"])        # a layer for each colour
    assert [v["mode"] for v in j["variants"]] == ["closest", "tonality", "random", "random", "closest"] and j["colouring"]["variant"] == 5
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
    assert by_rgb(j, BLUE)["status"] == "automatic"
    svg = ET.fromstring(c["client"].get(f"/api/vector/{j['id']}/split.svg").text)
    region = next(p.get("data-region") for p in svg.findall(f"{SVG}path") if p.get("data-color") == str(by_rgb(j, RED)["index"]))
    yellow_as_shot = ids[(round(lab(YELLOW)[0]), 2000)]
    j = colouring(c, j, op="paint", scope="region", region=region, entry_id=yellow_as_shot)  # measured as photographed, by hand
    assert j["colouring"]["regions"] == {region: yellow_as_shot} and j["entries"][yellow_as_shot]["automatic"] is False
    j = colouring(c, j, op="exclude_region", region=region)
    assert j["colouring"]["excluded_regions"] == [region]
    j = colouring(c, j, op="include_region", region=region)
    j = colouring(c, j, op="paint", scope="region", region=region, entry_id=None)
    assert j["colouring"]["regions"] == {}
    for op, message in [({"op": "paint", "scope": "region", "region": "r999", "entry_id": green_entry}, "there is no region"),
                        ({"op": "set_colour", "colour": 99, "entry_id": green_entry}, "no such source colour"),
                        ({"op": "set_colour", "colour": 0, "entry_id": "nope"}, "must be a measured colour")]:
        bad = c["client"].post(f"/api/vector/{j['id']}/colouring", json=op)
        assert bad.status_code == 422 and message in bad.json()["error"]
    plan = pl.get_plan(c["store"], j["id"])
    assert [h["op"]["op"] for h in plan["history"][1:4]] == ["set_colour", "assign", "set_colour"]


# -- the size of each layer (DEC-107) ----------------------------------------------------------------------------------------------
def test_each_layer_shows_the_colour_its_recipe_gives_at_the_length_of_the_layers_rows(work, monkeypatch):
    """One recipe engraved as a 5 mm patch came out blue and as a 50 mm strip green: given to the green band, which runs the work's whole
    60 mm width around the yellow disc (its rows about 53 mm long), its layer is green (measured at that length); given to the disc, about
    11 mm across, it lies between the two sizes. The preview, the delta E, the stored layers and the colours the file promises all use
    that colour."""
    c, store = work, work["store"]
    for rgb, mm in ((BLUE, 5), (GREEN, 50)):
        oid = obs.add(store, c["w"], lab(rgb), power=55, speed=700, line_interval=0.02, material_id=c["ti"], layer_type="Scan")
        store.execute("UPDATE pair SET lightburn_path=? WHERE id=(SELECT pair_id FROM observation WHERE id=?)", (f"/rows/{mm}", oid))
    read = row_length.of_file                                         # the pairs' files: one Scan layer whose rows are that long
    monkeypatch.setattr(row_length, "of_file", lambda path: {1: float(path[6:])} if str(path).startswith("/rows/") else read(path))
    entries = c["client"].get(f"/api/vector-palette?device_id={c['w']['setup'][0]}&lens_id={c['w']['setup'][1]}&material_id={c['ti']}").json()["entries"]
    (sized,) = [e for e in entries if e["parameters"]["speed"] == 700]
    assert [(z["row_mm"], z["engravings"]) for z in sized["sizes"]] == [(5.0, 1), (50.0, 1)]
    j = create(c).json()
    green, yellow = by_rgb(j, GREEN)["index"], by_rgb(j, YELLOW)["index"]

    j = colouring(c, j, op="set_colour", colour=green, entry_id=sized["id"])
    (band,) = [layer for layer in j["layers"] if layer["entry_id"] == sized["id"]]
    assert band["size"]["how"] == "measured" and band["size"]["from_mm"] == [50.0] and 48 < band["size"]["row_mm"] < 56, band["size"]
    assert color.delta_e(lab(tuple(band["srgb"])), lab(GREEN)) < 1.5 and by_rgb(j, GREEN)["delta_e"] < 1   # green, not blue and green pooled
    assert j["entries"][sized["id"]]["srgb"] == band["srgb"]                                               # the editor paints it so

    j = colouring(c, j, op="set_colour", colour=green, entry_id=None)
    j = colouring(c, j, op="set_colour", colour=yellow, entry_id=sized["id"])
    (disc,) = [layer for layer in j["layers"] if layer["entry_id"] == sized["id"]]
    assert disc["size"]["how"] == "between" and 7 < disc["size"]["row_mm"] < 13, disc["size"]
    between = palette.at_size(sized, disc["size"]["row_mm"])                                               # (its length rounded to 0.1 mm)
    assert color.delta_e(lab(tuple(disc["srgb"])), between["lab"]) < 1 and lab(BLUE)[0] < between["lab"][0] < lab(GREEN)[0]
    stored = next(layer for layer in pl.get_plan(store, j["id"])["layers"] if layer["entry_id"] == sized["id"])
    assert stored["srgb"] == disc["srgb"]                                                                  # the list's picture draws it
    assert c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").status_code == 200
    promised = next(layer for layer in pl.get_plan(store, j["id"])["exports"][-1]["promised"] if layer["entry_id"] == sized["id"])
    assert promised["srgb"] == disc["srgb"]                                                                # what the file promised


# -- the file -------------------------------------------------------------------------------------------------------------------
def regions_of(project) -> list[list]:
    return [[p.polygon] + p.holes for layer in project.layers if layer.index > 0 for p in layer.regions]


def test_the_file_cleans_first_has_one_layer_per_recipe_with_its_full_settings_and_gapless_closed_regions(work, job):
    c, j = work, job
    assert j["time"]["estimate"] and j["time"]["complete"] and j["time"]["layers"][0]["index"] == 0
    assert j["time"]["seconds"] == pytest.approx(sum(row["seconds"] for row in j["time"]["layers"]))
    r = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    project = lb.parse_bytes(r.content)
    layers = sorted(project.layers, key=lambda layer: layer.index)
    assert layers[0].index == 0 and layers[0].name.startswith("CLEAN-CROSSHATCH-") and layers[0].cross_hatch
    colour_layers = layers[1:]
    assert [layer.index for layer in colour_layers] == list(range(1, len(colour_layers) + 1)) and len(colour_layers) <= 29
    assert len(colour_layers) == len(j["layers"]) == 5                                   # paper, yellow, red, blue, green: a layer for each colour
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
    assert after["status"] == "Exported" and after["exports"][0]["variant"] == 1 and after["exports"][0]["layers"] == 5
    assert after["exports"][0]["seconds"] == pytest.approx(j["time"]["seconds"]) and "path" not in after["exports"][0]
    plan = pl.get_plan(c["store"], j["id"])
    assert plan["exports"][0]["colouring"]["assignment"] and "path" in plan["exports"][0]       # kept with the colouring it came from
    stored = c["client"].get(f"/api/vector/{j['id']}/exports/1")
    assert stored.status_code == 200 and stored.content == r.content
    assert c["client"].get(f"/api/plans/{j['id']}/export.lbrn2").status_code == 200          # the plan screen exports it the same way


def test_the_file_says_mirror_y_so_that_lightburn_shows_the_picture_upright_and_a_resaved_file_is_read_against_it(work, job):
    """The picture is laid out top-down; LightBurn's galvo canvas shows such a layout upside down unless the file says MirrorY, as for the
    plates (platform REQ-052, DEC-094). The operator had to flip every exported work by hand."""
    from titanium_platform import ingest
    c, j = work, job
    file = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").content
    assert b'MirrorX="False" MirrorY="True"' in file and lb.parse_bytes(file).mirror_y is True
    plan = pl.get_plan(c["store"], j["id"])
    assert plan["export_mirror_y"] is True and vector_job.EXPORT_MIRROR_Y is True
    resaved = lb.parse_bytes(file.replace(b'MirrorY="True"', b'MirrorY="False"'))                   # LightBurn rewrote the flag (and would reflect the shapes)
    assert ingest._normalize_project_to_plan(resaved, plan) == ["Y"]


def test_every_curved_edge_of_the_file_has_both_of_its_handles_so_that_no_sliver_swings_across_the_picture(work, job):
    """LightBurn reads a missing handle as the origin of the shape: a Bézier edge with one handle drew a long straight sliver from its
    corner towards the top-left, across the faces of the operator's picture (platform REQ-052, DEC-094)."""
    c, j = work, job
    assert j["smoothing_mm"] > 0                                                                   # a new work has smooth (Bézier) borders
    text = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").content.decode("utf-8")
    pattern = re.compile(r"V(-?[\d.]+) (-?[\d.]+)(c0x(?:-?[\d.]+c0y-?[\d.]+|1))(c1x(?:-?[\d.]+c1y-?[\d.]+|1))")
    curved = 0
    for verts, prims in re.findall(r"<VertList>(.*?)</VertList>\s*<PrimList>(.*?)</PrimList>", text, re.S):
        vertices = pattern.findall(verts)
        for kind, a, b in re.findall(r"([BL])(\d+) (\d+)", prims):
            if kind == "B":
                curved += 1
                assert vertices[int(a)][2] != "c0x1" and vertices[int(b)][3] != "c1x1"
    assert curved > 0


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
    state = {"by_id": {"e1": {}}, "missing_regions": [], "layers": [{}] * cap, "zones": []}
    assert vector_job._blocker_photo({"markers_enabled": markers}, state) is None
    state["layers"] = [{}] * (cap + 1)
    assert vector_job._blocker_photo({"markers_enabled": markers}, state) == f"{cap + 1} different recipes need more LightBurn layers than the {cap} available"
    state["by_id"] = {}
    assert vector_job._blocker_photo({"markers_enabled": markers}, state) == "no measured colour of this laser, lens and titanium stock fills an area"


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
    for bad in (work["client"].post(f"/api/vector/{traced['id']}/colouring", json={"op": "undo"}),
                work["client"].get(f"/api/vector/{traced['id']}/reach", params={"region": "r1", "similarity_de": 3}),
                work["client"].get(f"/api/vector/{traced['id']}/neighbours")):
        assert bad.status_code == 422 and bad.json()["error"] == "only a photograph split into colour regions is split and coloured this way"


# -- the colour editor (feature vector-work-colour-editor) ----------------------------------------------------------------------
def areas(c, j) -> dict[str, str]:
    """The regions of the test picture by what they show: the paper around everything and inside the ring, the ring, the
    ellipse, the band and the disc."""
    doc = document_of(c, j)
    pixels = {r["id"]: r["pixels"] for r in doc["regions"]}
    of = lambda rgb: regions_in(doc, by_rgb(j, rgb)["index"])          # noqa: E731
    paper, inner = sorted(of(PAPER), key=lambda r: -pixels[r])
    (ring,), (ellipse,), (band,), (disc,) = of(RED), of(BLUE), of(GREEN), of(YELLOW)
    return {"paper": paper, "inner": inner, "ring": ring, "ellipse": ellipse, "band": band, "disc": disc}


def reach(c, j, **params) -> dict:
    r = c["client"].get(f"/api/vector/{j['id']}/reach", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_brush_paints_one_region_or_its_whole_source_colour_and_includes_what_it_paints(work, job):
    """Editor REQ-045: scopes region and colour, painting an excluded area includes it, null is the automatic choice."""
    c, j = work, job
    a, paper = areas(c, j), by_rgb(j, PAPER)
    blue_e, green_e = by_rgb(j, BLUE)["entry_id"], by_rgb(j, GREEN)["entry_id"]
    j = colouring(c, j, op="exclude_region", region=a["inner"])
    j = colouring(c, j, op="paint", region=a["inner"], scope="region", entry_id=blue_e)
    assert j["colouring"]["regions"] == {a["inner"]: blue_e} and j["colouring"]["excluded_regions"] == []
    assert by_rgb(j, PAPER)["entry_id"] == paper["entry_id"] and by_rgb(j, PAPER)["status"] == "automatic"   # the rest of its colour keeps it
    j = colouring(c, j, op="exclude_colour", colour=paper["index"])
    j = colouring(c, j, op="exclude_region", region=a["paper"])
    j = colouring(c, j, op="paint", region=a["paper"], scope="colour", entry_id=green_e)
    assert by_rgb(j, PAPER)["status"] == "hand" and by_rgb(j, PAPER)["entry_id"] == green_e
    assert j["colouring"]["regions"] == {} and j["colouring"]["excluded_colours"] == [] and j["colouring"]["excluded_regions"] == []
    stored = next(layer for layer in pl.get_plan(c["store"], j["id"])["layers"] if layer["entry_id"] == green_e)
    assert {a["paper"], a["inner"], a["band"]} <= set(stored["region_ids"])                       # every area of the colour shows it
    j = colouring(c, j, op="paint", region=a["ring"], scope="region", entry_id=blue_e)
    j = colouring(c, j, op="paint", region=a["inner"], scope="region", entry_id=blue_e)
    j = colouring(c, j, op="paint", region=a["paper"], scope="colour", entry_id=None)            # the colour back to the automatic choice
    assert by_rgb(j, PAPER)["status"] == "automatic" and by_rgb(j, PAPER)["entry_id"] == paper["entry_id"]
    assert j["colouring"]["regions"] == {a["ring"]: blue_e}                                      # the own colours inside it cleared first
    j = colouring(c, j, op="paint", region=a["ring"], scope="region", entry_id=None)
    assert j["colouring"]["regions"] == {} and j["undo"] == 9
    assert [h["op"]["op"] for h in pl.get_plan(c["store"], j["id"])["history"][-3:]] == ["paint"] * 3


def test_painting_a_source_colour_includes_again_every_area_of_it_that_was_excluded(work, job):
    """Editor REQ-045, DEC-079: every area of the colour shows the colour afterwards, as the hover outline says."""
    c, j = work, job
    a, paper, green_e = areas(c, j), by_rgb(job, PAPER), by_rgb(job, GREEN)["entry_id"]
    mine = regions_in(document_of(c, j), paper["index"])
    assert len(mine) == 2 and a["ring"] not in mine
    j = colouring(c, j, op="exclude_region", regions=mine)                                      # both areas of the colour, one by one
    j = colouring(c, j, op="exclude_region", region=a["ring"])                                  # an area of another colour
    j = colouring(c, j, op="paint", region=mine[0], scope="colour", entry_id=None)              # automatic: exclusions stay as they are
    assert sorted(j["colouring"]["excluded_regions"]) == sorted(mine + [a["ring"]])
    j = colouring(c, j, op="paint", region=mine[0], scope="colour", entry_id=green_e)
    assert j["colouring"]["excluded_regions"] == [a["ring"]]                                    # the colour's own areas are in again
    stored = next(layer for layer in pl.get_plan(c["store"], j["id"])["layers"] if layer["entry_id"] == green_e)
    assert set(mine) <= set(stored["region_ids"]) and a["ring"] not in stored["region_ids"]
    j = colouring(c, j, op="undo")                                                              # one operation: undo brings them back out
    assert sorted(j["colouring"]["excluded_regions"]) == sorted(mine + [a["ring"]])


def test_a_fill_spreads_from_the_clicked_region_over_similar_neighbours_and_its_preview_is_what_it_paints(work, job):
    """Editor REQ-045: similarity to the clicked region's colour, never through excluded areas; the preview changes nothing."""
    c, j = work, job
    a, order = areas(c, j), [r["id"] for r in document_of(c, j)["regions"]]
    disc, paper, band = (by_rgb(j, rgb)["lab"] for rgb in (YELLOW, PAPER, GREEN))
    near = color.delta_e(disc, paper)
    assert color.delta_e(disc, band) > near + 0.5 and color.delta_e(paper, band) < near      # the band is like the paper, not the disc
    before = c["client"].get(f"/api/vector/{j['id']}").json()
    one = reach(c, j, region=a["disc"], similarity_de=0)
    assert one == {"region": a["disc"], "similarity_de": 0, "version": 1, "regions": [a["disc"]], "pixels": by_rgb(j, YELLOW)["pixels"],
                   "share": pytest.approx(by_rgb(j, YELLOW)["pixels"] / (60 * 45 / 0.0625))}
    assert reach(c, j, region=a["disc"], similarity_de=near + 0.25)["regions"] == sorted([a["paper"], a["disc"]], key=order.index)
    everything = reach(c, j, region=a["paper"], similarity_de="500")
    assert everything["regions"] == order and everything["share"] == pytest.approx(1.0)
    assert c["client"].get(f"/api/vector/{j['id']}").json() == before                           # a preview changes nothing
    j = colouring(c, j, op="exclude_region", region=a["ring"])
    walled = reach(c, j, region=a["paper"], similarity_de=500)["regions"]
    assert walled == [r for r in order if r not in (a["ring"], a["inner"])]                       # the inner paper lies behind the ring
    j = colouring(c, j, op="include_region", region=a["ring"])
    j = colouring(c, j, op="exclude_colour", colour=by_rgb(j, RED)["index"])
    assert reach(c, j, region=a["paper"], similarity_de=500)["regions"] == walled              # an area of an excluded colour is a wall
    j = colouring(c, j, op="exclude_region", region=a["band"])
    blue_e = by_rgb(j, BLUE)["entry_id"]
    preview = reach(c, j, region=a["paper"], similarity_de=500)["regions"]
    j = colouring(c, j, op="paint", region=a["paper"], scope="fill", entry_id=blue_e, similarity_de=500)
    assert sorted(j["colouring"]["regions"]) == sorted(preview) and set(j["colouring"]["regions"].values()) == {blue_e}
    assert j["colouring"]["excluded_regions"] == [a["band"]] and a["band"] not in preview
    assert reach(c, j, region=a["ring"], similarity_de=500)["regions"] == [r for r in order if r != a["band"]]   # the clicked one is no wall
    j = colouring(c, j, op="paint", region=a["band"], scope="fill", entry_id=blue_e, similarity_de=0)   # an excluded area painted is included
    assert j["colouring"]["excluded_regions"] == [] and j["colouring"]["regions"][a["band"]] == blue_e
    assert sorted(j["colouring"]["regions"]) == sorted(preview + [a["band"]])
    j = colouring(c, j, op="paint", region=a["paper"], scope="fill", entry_id=None, similarity_de=500)    # null: the fill's own colours go
    assert j["colouring"]["regions"] == {} and reach(c, j, region=a["paper"], similarity_de=500)["regions"] == sorted(
        preview + [a["band"]], key=order.index)


def test_merging_titanium_colours_leaves_one_layer_fewer_and_every_automatic_mode_keeps_it(work, job):
    """Editor REQ-046."""
    c, j = work, job
    a = areas(c, j)
    red_e, blue_e = by_rgb(j, RED)["entry_id"], by_rgb(j, BLUE)["entry_id"]
    j = colouring(c, j, op="paint", region=a["inner"], scope="region", entry_id=blue_e)
    layers = len(j["layers"])
    j = colouring(c, j, op="merge_titanium", entries=[red_e, blue_e], into=red_e)
    assert len(j["layers"]) == j["totals"]["recipes"] == layers - 1 and blue_e not in {layer["entry_id"] for layer in j["layers"]}
    assert by_rgb(j, BLUE)["entry_id"] == red_e and by_rgb(j, BLUE)["status"] == "hand" and j["colouring"]["regions"] == {a["inner"]: red_e}
    assert by_rgb(j, RED)["status"] == "automatic" and j["document"]["version"] == 1
    for mode in ("closest", "tonality", "random"):
        j = colouring(c, j, op="assign", mode=mode)
        assert by_rgb(j, BLUE)["entry_id"] == red_e and j["colouring"]["regions"] == {a["inner"]: red_e}, mode
    used = {col["entry_id"] for col in j["colours"] if col["entry_id"]} | set(j["colouring"]["regions"].values())
    other_e = next(e for e in sorted(used) if e != red_e)
    unused = next(e for e in palette_ids(c).values() if e not in used | {red_e})
    two = "choose two or more titanium colours of the colouring to merge"
    for op, message in [({"entries": [red_e], "into": red_e}, two), ({"entries": [], "into": red_e}, two), ({"entries": red_e, "into": red_e}, two),
                        ({"entries": [unused], "into": red_e}, two),
                        ({"entries": [other_e], "into": red_e}, two),                          # DEC-078: one colour merged into another target
                        ({"entries": [red_e, red_e], "into": red_e}, two),                      # the same colour twice is one colour
                        ({"entries": [other_e, unused], "into": red_e}, two),                   # a selected colour the colouring does not use
                        ({"entries": [red_e, other_e], "into": "nope"}, "the titanium colour must be a measured colour of this laser, lens and titanium stock")]:
        refused(c, j, {"op": "merge_titanium", **op}, message)
    layers = len(j["layers"])
    j = colouring(c, j, op="merge_titanium", entries=[red_e, other_e], into=unused)           # the target need not be one of the selected
    assert len(j["layers"]) == layers - 1 and {layer["entry_id"] for layer in j["layers"]} >= {unused}
    assert red_e not in {layer["entry_id"] for layer in j["layers"]} and other_e not in {layer["entry_id"] for layer in j["layers"]}


def test_merging_source_colours_makes_a_new_version_on_which_every_mode_and_brush_works(work, job):
    """Editor REQ-047: one colour under the number of the larger, the mean Lab, the other numbers kept, its choices kept."""
    c, j = work, job
    a, red, blue, paper = areas(c, j), by_rgb(j, RED), by_rgb(j, BLUE), by_rgb(j, PAPER)
    green_e = by_rgb(j, GREEN)["entry_id"]
    assert red["pixels"] > blue["pixels"]
    j = colouring(c, j, op="set_colour", colour=red["index"], entry_id=green_e)
    j = colouring(c, j, op="set_colour", colour=blue["index"], entry_id=paper["entry_id"])
    j = colouring(c, j, op="exclude_colour", colour=blue["index"])
    j = colouring(c, j, op="paint", region=a["ellipse"], scope="region", entry_id=green_e)
    j = colouring(c, j, op="merge_colours", colours=[blue["index"], red["index"]])
    assert j["document"]["version"] == 2 and j["document"]["colours"] == 4 and j["document"]["regions"] == job["document"]["regions"]
    merged = next(col for col in j["colours"] if col["index"] == red["index"])
    mean = np.average([red["lab"], blue["lab"]], axis=0, weights=[red["pixels"], blue["pixels"]])
    assert merged["lab"] == [round(float(v), 3) for v in mean] and merged["pixels"] == red["pixels"] + blue["pixels"]
    assert sorted(col["index"] for col in j["colours"]) == sorted({col["index"] for col in job["colours"]} - {blue["index"]})   # numbers stay
    assert merged["status"] == "hand" and merged["entry_id"] == green_e                                # the colour left keeps its choice
    assert j["colouring"]["excluded_colours"] == [] and j["colouring"]["regions"] == {a["ellipse"]: green_e}   # the other's dropped, areas kept
    svg = ET.fromstring(c["client"].get(f"/api/vector/{j['id']}/split.svg").text)
    assert {p.get("data-region") for p in svg.findall(f"{SVG}path") if p.get("data-color") == str(red["index"])} == {a["ring"], a["ellipse"]}
    last = pl.get_plan(c["store"], j["id"])["history"][-1]
    assert last["op"] == {"op": "merge_colours", "colours": [blue["index"], red["index"]], "keeper": red["index"]} and last["version"] == 2
    for mode in ("closest", "tonality", "random"):
        j = colouring(c, j, op="assign", mode=mode)
        assert next(col for col in j["colours"] if col["index"] == red["index"])["entry_id"] == green_e
    for scope in ("region", "fill", "colour"):
        j = colouring(c, j, op="paint", region=a["ellipse"], scope=scope, entry_id=paper["entry_id"], similarity_de=0)
    assert next(col for col in j["colours"] if col["index"] == red["index"])["entry_id"] == paper["entry_id"] and j["colouring"]["regions"] == {}
    j = colouring(c, j, op="merge_colours", colours=[by_rgb(j, YELLOW)["index"], paper["index"]], entry_id=green_e)
    kept = next(col for col in j["colours"] if col["index"] == paper["index"])
    assert j["document"]["version"] == 3 and kept["status"] == "hand" and kept["entry_id"] == green_e
    for op, message in [({"colours": [red["index"]]}, "choose two or more source colours to merge"),
                        ({"colours": [red["index"], red["index"]]}, "choose two or more source colours to merge"),
                        ({"colours": "all"}, "choose two or more source colours to merge"),
                        ({"colours": [red["index"], blue["index"]]}, "there is no such source colour"),
                        ({"colours": [red["index"], paper["index"]], "entry_id": "nope"},
                         "the titanium colour must be a measured colour of this laser, lens and titanium stock")]:
        refused(c, j, {"op": "merge_colours", **op}, message)


def test_merging_regions_makes_a_new_version_whose_lightburn_file_holds_the_merged_outline_without_gaps(work, job):
    """Editor REQ-048: the merged area keeps the id and choices of its largest member; the file reads back gapless."""
    c, j = work, job
    a = areas(c, j)
    green_e, blue_e = by_rgb(j, GREEN)["entry_id"], by_rgb(j, BLUE)["entry_id"]
    j = colouring(c, j, op="paint", region=a["inner"], scope="region", entry_id=blue_e)
    j = colouring(c, j, op="paint", region=a["ring"], scope="region", entry_id=green_e)
    j = colouring(c, j, op="exclude_region", region=a["inner"])
    before = document_of(c, j)
    j = colouring(c, j, op="merge_regions", regions=[a["inner"], a["ring"]])
    assert j["document"]["version"] == 2 and j["document"]["regions"] == job["document"]["regions"] - 1
    assert j["colouring"]["regions"] == {a["ring"]: green_e} and j["colouring"]["excluded_regions"] == []
    assert pl.get_plan(c["store"], j["id"])["history"][-1]["op"]["keeper"] == a["ring"]
    ring = next(r for r in document_of(c, j)["regions"] if r["id"] == a["ring"])
    assert len(ring["loops"]) == 1 and ring["pixels"] == sum(r["pixels"] for r in before["regions"] if r["id"] in (a["ring"], a["inner"]))
    j = colouring(c, j, op="merge_regions", regions=[a["paper"], a["band"], a["disc"]])
    assert j["document"]["version"] == 3 and j["export_blocked"] is None
    project = lb.parse_bytes(c["client"].get(f"/api/vector/{j['id']}/export.lbrn2").content)
    shapes = [p for layer in project.layers if layer.index > 0 for p in layer.regions]
    assert len(shapes) == j["document"]["regions"] == job["document"]["regions"] - 3 and all(p.closed for p in shapes)
    assert sorted(len(p.holes) for p in shapes) == sorted(len(r["loops"]) - 1 for r in document_of(c, j)["regions"])   # holes in place
    cov = sg.coverage(regions_of(project), 60, 45, 16)
    assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005
    for op, message in [({"regions": [a["ring"]]}, "choose two or more regions to merge"), ({"regions": a["ring"]}, "choose two or more regions to merge"),
                        ({"regions": [a["ring"], a["ellipse"]]}, "the regions to merge must border one another"),
                        ({"regions": [a["ring"], "r999"]}, "there is no region 'r999'")]:
        refused(c, j, {"op": "merge_regions", **op}, message)


def state_of(c, j) -> tuple:
    """What undo and redo bring back: the split version and its picture, the colours, the colouring, the totals, the settings."""
    v = c["client"].get(f"/api/vector/{j['id']}").json()
    return (v["document"]["version"], v["document"]["regions"], v["colours"], v["colouring"], v["totals"], v["settings"],
            c["client"].get(f"/api/vector/{j['id']}/split.svg").text)


def test_undo_and_redo_step_through_paints_and_merges_with_their_split_versions(work, job):
    """Editor REQ-049, DEC-077."""
    c, j = work, job
    a, blue_e, paper_e = areas(c, j), by_rgb(j, BLUE)["entry_id"], by_rgb(j, PAPER)["entry_id"]
    states = [state_of(c, j)]
    for step in ({"op": "paint", "region": a["paper"], "scope": "region", "entry_id": blue_e},
                 {"op": "merge_colours", "colours": [by_rgb(j, BLUE)["index"], by_rgb(j, RED)["index"]]},
                 {"op": "merge_regions", "regions": [a["ring"], a["inner"]]},
                 {"op": "paint", "region": a["ring"], "scope": "colour", "entry_id": paper_e}):
        j = colouring(c, j, **step)
        states.append(state_of(c, j))
    assert [s[0] for s in states] == [1, 1, 2, 3, 3] and len({s[6] for s in states}) == 3 and (j["undo"], j["redo"]) == (4, 0)
    for back in range(4):
        j = colouring(c, j, op="undo")
        assert state_of(c, j) == states[3 - back] and (j["undo"], j["redo"]) == (3 - back, back + 1)
    refused(c, j, {"op": "undo"}, "there is no earlier colouring to go back to")
    for forth in range(4):
        j = colouring(c, j, op="redo")
        assert state_of(c, j) == states[forth + 1]
    refused(c, j, {"op": "redo"}, "there is no undone change to redo")
    j = colouring(c, j, op="undo")
    j = colouring(c, j, op="paint", region=a["band"], scope="region", entry_id=paper_e)          # a new operation: nothing to redo
    assert (j["undo"], j["redo"]) == (4, 0)
    refused(c, j, {"op": "redo"}, "there is no undone change to redo")
    for _ in range(3):
        j = colouring(c, j, op="undo")
    assert state_of(c, j) == states[1]
    j = colouring(c, j, op="merge_regions", regions=[a["ring"], a["inner"]])
    assert j["document"]["version"] == 4                                                      # never a number used before
    plan = pl.get_plan(c["store"], j["id"])
    assert [h["version"] for h in plan["history"] if h.get("path")] == [1, 2, 3, 4]
    assert state_of(c, j)[6] not in {s[6] for s in states}                                     # each version's picture is its own


def test_undo_and_redo_cover_the_titanium_merge_among_the_four_kinds_of_operation_the_requirement_names(work, job):
    """Editor REQ-049, criterion 1: painting, merging titanium colours, merging source colours and merging areas, step by step."""
    c, j = work, job
    a, red, blue = areas(c, j), by_rgb(j, RED), by_rgb(j, BLUE)
    green_e = by_rgb(j, GREEN)["entry_id"]
    steps = ({"op": "paint", "region": a["ring"], "scope": "region", "entry_id": green_e},
             {"op": "merge_titanium", "entries": [blue["entry_id"], green_e], "into": green_e},
             {"op": "merge_colours", "colours": [blue["index"], red["index"]]},
             {"op": "merge_regions", "regions": [a["ring"], a["inner"]]})
    states, views = [state_of(c, j)], [j]
    for step in steps:
        j = colouring(c, j, **step)
        states.append(state_of(c, j))
        views.append(j)
    assert [s[0] for s in states] == [1, 1, 1, 2, 3] and (j["undo"], j["redo"]) == (4, 0)
    assert by_rgb(views[2], BLUE)["entry_id"] == green_e and by_rgb(views[2], BLUE)["status"] == "hand"      # the titanium merge took effect
    assert states[2][2] != states[1][2]                                                          # the colours show it (the view's colouring holds areas only)
    for back in range(4):
        j = colouring(c, j, op="undo")
        assert state_of(c, j) == states[3 - back] and (j["undo"], j["redo"]) == (3 - back, back + 1)
    for forth in range(4):
        j = colouring(c, j, op="redo")
        assert state_of(c, j) == states[forth + 1] and (j["undo"], j["redo"]) == (forth + 1, 3 - forth)
    assert [h["op"]["op"] for h in pl.get_plan(c["store"], j["id"])["history"] if h["op"]["op"] in ("paint", "merge_titanium", "merge_colours",
            "merge_regions")] == ["paint", "merge_titanium", "merge_colours", "merge_regions"]


def test_undo_brings_back_the_tolerance_and_the_filters_with_the_colouring(work, job):
    c, j = work, job
    first = (j["settings"], j["colours"], j["colouring"])
    j = colouring(c, j, op="settings", tolerance_de=12, max_time=50, include_as_shot=True)
    changed = (j["settings"], j["colours"], j["colouring"])
    assert j["settings"] == {"tolerance_de": 12, "max_time": 50, "include_as_shot": True} and changed != first
    j = colouring(c, j, op="undo")
    assert (j["settings"], j["colours"], j["colouring"]) == first
    j = colouring(c, j, op="redo")
    assert (j["settings"], j["colours"], j["colouring"]) == changed                              # the redone colouring too, not only the settings


def test_a_variant_is_restored_only_on_its_own_split_version(work, job):
    c, j = work, job
    j = colouring(c, j, op="assign", mode="tonality")
    assert [v["version"] for v in j["variants"]] == [1, 1]
    j = colouring(c, j, op="merge_colours", colours=[by_rgb(j, BLUE)["index"], by_rgb(j, RED)["index"]])
    refused(c, j, {"op": "restore", "variant": 1}, "this variant of the colouring belongs to another version of the split")
    j = colouring(c, j, op="assign", mode="closest")
    assert [v["version"] for v in j["variants"]] == [1, 1, 2] and j["colouring"]["variant"] == 3
    j = colouring(c, j, op="undo")
    j = colouring(c, j, op="undo")
    assert j["document"]["version"] == 1
    j = colouring(c, j, op="restore", variant=1)
    assert j["colouring"]["variant"] == 1 and j["redo"] == 0
    refused(c, j, {"op": "restore", "variant": 3}, "this variant of the colouring belongs to another version of the split")


def test_undo_steps_variants_and_accepted_colours_of_works_made_before_the_editor_still_work(work, job):
    """Editor REQ-043 (choices accepted earlier stay the operator's), REQ-049 (older undo entries still undo)."""
    c, j, store = work, job, work["store"]
    first = copy.deepcopy(pl.get_plan(store, j["id"])["colouring"])
    yellow, red_e = by_rgb(j, YELLOW), by_rgb(j, RED)["entry_id"]
    j = colouring(c, j, op="paint", region=areas(c, j)["paper"], scope="region", entry_id=by_rgb(j, BLUE)["entry_id"])
    plan = pl.get_plan(store, j["id"])                                                   # as release 0.5.1 stored a work
    plan["undo"], plan["unresolved"] = [first], {"colours": 0, "regions": 0, "share": 0.0, "indexes": []}
    plan["colouring"]["groups"][str(yellow["index"])] = {"entry_id": red_e, "by": "accepted"}
    del plan["redo"]
    for variant in plan["variants"]:
        del variant["version"]
    cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    assert (view["undo"], view["redo"]) == (1, 0) and [v["version"] for v in view["variants"]] == [1] and "unresolved" not in view
    assert by_rgb(view, YELLOW)["status"] == "accepted" and by_rgb(view, YELLOW)["how"] == "hand" and by_rgb(view, YELLOW)["entry_id"] == red_e
    j = colouring(c, view, op="assign", mode="random")
    assert by_rgb(j, YELLOW)["entry_id"] == red_e and by_rgb(j, YELLOW)["status"] == "accepted"
    j = colouring(c, j, op="undo")
    j = colouring(c, j, op="undo")
    assert j["colouring"]["regions"] == {} and j["redo"] == 2 and by_rgb(j, YELLOW)["status"] == "automatic"   # the bare colouring
    j = colouring(c, j, op="redo")
    assert j["colouring"]["regions"] != {} and by_rgb(j, YELLOW)["status"] == "accepted"
    j = colouring(c, j, op="restore", variant=1)
    stored = pl.get_plan(store, j["id"])
    assert "unresolved" not in stored and all(set(step) == {"colouring", "version", "threshold", "colour_settings"} for step in stored["undo"])


def test_splitting_again_is_a_fresh_start_without_undo_redo_or_variants(work, job):
    c, j = work, job
    a = areas(c, j)
    j = colouring(c, j, op="merge_regions", regions=[a["ring"], a["inner"]])
    j = colouring(c, j, op="assign", mode="random")
    j = colouring(c, j, op="undo")
    assert (j["undo"], j["redo"], len(j["variants"])) == (1, 1, 2)
    again = c["client"].post(f"/api/vector/{j['id']}/split", json={"n_colors": 5}).json()
    assert (again["undo"], again["redo"]) == (0, 0) and [(v["number"], v["version"]) for v in again["variants"]] == [(1, 3)]
    assert again["document"]["version"] == 3


def test_bad_editor_operations_are_refused_with_messages_the_screen_translates_and_change_nothing(work, job):
    c, j = work, job
    a, blue_e = areas(c, j), by_rgb(j, BLUE)["entry_id"]
    similarity, measured = "the similarity must be a non-negative delta E", "the titanium colour must be a measured colour of this laser, lens and titanium stock"
    paint = {"op": "paint", "region": a["paper"], "entry_id": None}
    for op, message in [({**paint, "scope": "lasso"}, "the scope must be region, colour or fill"), ({**paint, "scope": "fill"}, similarity),
                        ({**paint, "scope": "fill", "similarity_de": -1}, similarity), ({**paint, "scope": "fill", "similarity_de": True}, similarity),
                        ({**paint, "scope": "fill", "similarity_de": "a lot"}, similarity),
                        ({**paint, "scope": "region", "region": "r999"}, "there is no region 'r999'"),
                        ({**paint, "scope": "region", "entry_id": "nope"}, measured), ({**paint, "scope": "colour", "entry_id": ["x"]}, measured),
                        ({"op": "exclude_region", "regions": []}, "there is no region []"),
                        ({"op": "include_region", "regions": [a["paper"], "r999"]}, "there is no region 'r999'"),
                        ({"op": "redo"}, "there is no undone change to redo")]:
        refused(c, j, op, message)
    for params, message in [({"region": a["paper"], "similarity_de": "much"}, similarity), ({"region": a["paper"]}, similarity),
                            ({"region": a["paper"], "similarity_de": "-0.5"}, similarity), ({"similarity_de": 3}, "there is no region None"),
                            ({"region": "r999", "similarity_de": 3}, "there is no region 'r999'")]:
        r = c["client"].get(f"/api/vector/{j['id']}/reach", params=params)
        assert r.status_code == 422 and r.json() == {"error": message, "kind": "invalid"}, params
    assert c["client"].get(f"/api/vector/{j['id']}").json() == j                                  # nothing was recorded
    j = colouring(c, j, op="exclude_region", regions=[a["paper"], a["band"]])
    assert j["colouring"]["excluded_regions"] == sorted([a["paper"], a["band"]])
    j = colouring(c, j, op="include_region", regions=[a["band"], a["paper"]])
    assert j["colouring"]["excluded_regions"] == [] and j["undo"] == 2
    assert colouring(c, j, op="paint", region=a["paper"], scope="region", entry_id=blue_e)["colouring"]["regions"] == {a["paper"]: blue_e}


def neighbours(c, j) -> dict:
    r = c["client"].get(f"/api/vector/{j['id']}/neighbours")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_neighbours_of_a_split_are_the_relation_merging_uses_and_follow_its_version(work, job):
    """Editor REQ-048, DEC-080: the screen offers a merge only for a connected selection and learns who borders whom from the server."""
    c, j = work, job
    a, document = areas(c, j), document_of(c, j)
    got = neighbours(c, j)
    near = got["neighbours"]
    assert got["version"] == 1 and list(near) == [r["id"] for r in document["regions"]]            # every region, in the document's order
    assert near == {rid: sorted(others) for rid, others in sg.neighbours(document).items()}
    assert all(rid in near[other] for rid, others in near.items() for other in others)              # both ways
    assert a["inner"] in near[a["ring"]] and a["ellipse"] not in near[a["ring"]]                    # the ring borders its hole, not the ellipse
    before = c["client"].get(f"/api/vector/{j['id']}").json()
    assert neighbours(c, j) == got and c["client"].get(f"/api/vector/{j['id']}").json() == before    # reading changes nothing
    refused(c, j, {"op": "merge_regions", "regions": [a["ring"], a["ellipse"]]}, "the regions to merge must border one another")
    j = colouring(c, j, op="merge_regions", regions=[a["ring"], a["inner"]])                       # the ring keeps its id, the hole's paper goes
    merged = neighbours(c, j)
    assert merged["version"] == 2 and a["inner"] not in merged["neighbours"]
    assert merged["neighbours"][a["ring"]] == sorted((set(near[a["ring"]]) | set(near[a["inner"]])) - {a["ring"], a["inner"]})
    assert all(a["inner"] not in others for others in merged["neighbours"].values())
    j = colouring(c, j, op="undo")
    assert neighbours(c, j) == got                                                                  # the earlier version brings its relation back


# -- the screen, run in node over a small DOM with the server's real answers --------------------------------------------------
UI = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui"
TABLES = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-tasks.js", "i18n-data.js", "i18n-findings.js",
          "i18n-palette.js", "i18n-lettering.js", "i18n-gaps.js"]
GLUE = ("const __screens = {}, __renders = []; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { __renders.push(1); };"
        "globalThis.__screens = __screens; globalThis.__renders = __renders;")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'hardware.js', 'photo-modes.js', {code: %(glue)s}, 'screens/vector-split.js', 'screens/vector-photo.js', 'screens/lettering.js', 'screens/vector-editor.js',
  'screens/vector-colours.js', 'screens/vector-review.js', 'screens/vector-workspace.js', 'screens/vector.js']);
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
            f"/api/vector/{j['id']}/neighbours": {"status": 200, "json": c["client"].get(f"/api/vector/{j['id']}/neighbours").json()},
            f"/api/vector/{j['id']}/colouring": {"status": 200, "json": view}, f"/api/vector/{j['id']}/split": {"status": 200, "json": view}}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_screen_shows_the_two_sections_and_one_large_picture_painted_in_titanium_colours(work, job, tmp_path):
    """REQ-043, REQ-044: every colour is painted from the start (no acceptance step), on one large picture beside the editor's panel.
    The split is part of the colours' section, not a card of its own (operator, 2026-10-19); the variants and the file stay."""
    routes = routes_of(work, job)
    out = run_screen(tmp_path, job, routes, """
  out.text = tree.textContent;
  const svgs = tree.querySelectorAll('svg');
  out.classes = svgs.map((s) => s.getAttribute('class'));
  const picture = svgs.find((s) => (s.getAttribute('class') || '').split(' ').includes('vw-ed-svg'));
  out.titanium = picture.querySelectorAll('path').map((p) => [p.getAttribute('data-color'), p.getAttribute('fill'), p.getAttribute('stroke')]);
  out.exportDisabled = byText(tree, 'button', 'Создать файл LightBurn').disabled;
  out.links = tree.querySelectorAll('a').map((a) => a.getAttribute('href'));
  out.tabs = tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab' && b.getAttribute('id').startsWith('vw-tab-')).map((b) => b.textContent);
  const screen = tree;                                            // the screen is the workspace itself
  out.inScreen = ['Алгоритм разбиения', 'Число цветов', 'Разбить заново', 'Слои титана', 'Исходные цвета', 'Подробно по цветам…', 'Варианты раскраски', 'Раскрасить с помощью AI',
                  'Создать файл LightBurn', '← Мои работы', 'Сделать копию']
    .filter((t) => !screen.textContent.includes(t) && !screen.querySelectorAll('select, input, button').some((c) => c.getAttribute('aria-label') === t));
  out.pictures = screen.querySelectorAll('svg').map((s) => s.getAttribute('class'));
""")
    text = out["text"]
    assert out["tabs"] == ["Разбиение", "Цвета", "AI", "Варианты", "Результат", "Файл"] and out["inScreen"] == []          # one screen: tabs, the picture, the panel
    assert not any(old in text for old in ("1. Разбиение", "2. Цвета", "3. Файл LightBurn"))
    assert "vw-ed-svg" in out["pictures"] and "vw-areas" in out["pictures"]
    for part in ("Файл LightBurn", "Оценка времени всей работы", "лицо не найдено", "Слои титана", "Исходные цвета",
                 "Подробно по цветам…", "самый быстрый цвет в пределах допуска", "Алгоритм Мозаика", "Важные области: лица, глаза, губы"):
        assert part in text, part
    assert not any(bad in text for bad in ("null", "undefined", "NaN", "без перевода", "[object", "Принять")), text[:3000]
    assert sum("vw-ed-svg" in (c or "").split() for c in out["classes"]) == 1 and "vw-areas" in out["classes"]
    view = routes[f"/api/vector/{job['id']}"]["json"]
    for rgb in (YELLOW, PAPER):                                                          # the far yellow is painted too, not hatched
        colour = by_rgb(view, rgb)
        painted = "rgb({},{},{})".format(*view["entries"][str(colour["entry_id"])]["srgb"])
        assert all(fill == stroke == painted for index, fill, stroke in out["titanium"] if index == str(colour["index"])), rgb
    assert out["exportDisabled"] is bool(view["export_blocked"])
    assert not any((href or "").startswith("/api") for href in out["links"])        # nothing on this screen navigates to the API


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_region_clicked_with_the_brush_is_painted_with_the_colour_picked_from_the_palette(work, job, tmp_path):
    out = run_screen(tmp_path, job, routes_of(work, job), """
  const picture = tree.querySelectorAll('svg').find((s) => (s.getAttribute('class') || '').split(' ').includes('vw-ed-svg'));
  const swatches = tree.querySelectorAll('button').filter((b) => b.getAttribute('data-entry'));
  out.swatches = swatches.length;
  out.asShot = swatches.filter((b) => b.className.includes('as-shot')).length;
  await swatches[1].dispatch('click');
  out.entry = swatches[1].getAttribute('data-entry');
  const path = picture.querySelectorAll('path')[0];
  out.region = path.getAttribute('data-region');
  await path.dispatch('click');
  await tick(); await tick();
  out.posted = ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, JSON.parse(r.body)]);
  out.renders = ctx.__renders.length;
""")
    palette = work["client"].get(f"/api/vector/{job['id']}/palette").json()
    assert out["swatches"] == len(palette) and out["asShot"] == 1
    (path, body), = out["posted"]
    assert path == f"/api/vector/{job['id']}/colouring"
    assert body == {"op": "paint", "region": out["region"], "scope": "region", "entry_id": body["entry_id"]} and str(body["entry_id"]) == out["entry"]
    assert body["entry_id"] in {e["id"] for e in palette}                              # the palette's own id, sent as the server gave it
    assert out["renders"] == 0                                                           # the picture is recoloured in place


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
def test_the_four_algorithms_are_chosen_on_the_screen_each_with_what_it_looks_like_and_costs_and_travel_with_split_again(work, job, tmp_path):
    """DEC-076, DEC-082 of vector-detail-and-colour-control: a choice before splitting again, each described, a level of detail not among them."""
    out = run_screen(tmp_path, job, routes_of(work, job), """
  const select = tree.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Алгоритм разбиения');
  out.options = select.options.map((o) => [o.value, o.textContent]);
  out.selected = select.value;
  const hint = () => tree.querySelectorAll('p').find((p) => p.className === 'toolbar-hint').textContent;
  out.hints = {};
  for (const [value] of out.options) { select.value = value; await select.dispatch('change'); out.hints[value] = hint(); }
  out.detail = tree.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Детальность').options.map((o) => o.value);
  select.value = 'planes'; await select.dispatch('change');
  await byText(tree, 'button', 'Разбить заново').dispatch('click');
  out.posted = ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, JSON.parse(r.body)]);
""")
    assert out["options"] == [["slic", "Мозаика"], ["tonal", "По тонам"], ["planes", "Крупные плоскости"], ["seeds", "SEEDS"]] and out["selected"] == "slic"
    hints = out["hints"]
    assert len(set(hints.values())) == 4 and all(hints[k].startswith(name + ": ") for k, name in (("slic", "Мозаика"), ("tonal", "По тонам"),
                                                                                                   ("planes", "Крупные плоскости"), ("seeds", "SEEDS")))
    assert "лица" in hints["slic"] and "светотени" in hints["tonal"] and "дольше остальных" in hints["tonal"]                  # what it looks like, what it costs
    assert "на 40 % меньше" in hints["planes"] and "быстрее" in hints["seeds"] and "Близок к «Мозаике»" in hints["seeds"]
    assert out["detail"] == ["coarse", "medium", "fine"]                              # detail levels are not offered as algorithms
    (path, body), = out["posted"]
    assert path == f"/api/vector/{job['id']}/split" and body["algorithm"] == "planes" and body["n_colors"] == 5
    r = work["client"].post(f"/api/vector/{job['id']}/split", json=body)               # the server takes what the screen sends
    assert r.status_code == 200 and r.json()["document"]["algorithm"] == "planes"


def test_the_start_form_sends_the_algorithm_with_the_other_photograph_fields():
    screen = (UI / "screens" / "vector.js").read_text(encoding="utf-8")
    assert "const algorithm = VectorSplit.picker('slic');" in screen and "field('Алгоритм разбиения', algorithm.select)" in screen
    assert "fd.append('algorithm', algorithm.select.value)" in screen


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_an_export_refused_by_the_server_is_shown_translated_and_the_file_is_fetched_not_opened(work, job, tmp_path):
    j = job
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


def test_the_area_overlay_does_not_paint_the_chart_background_over_the_picture():
    """Regression (walkthrough of 0.5.0): ``svg[role=img]`` gives charts an opaque plot background; the area overlay is such
    an svg and hid the picture it is drawn on. A rule as specific as the chart rule and later in the file must clear it."""
    css = (UI / "styles.css").read_text(encoding="utf-8")
    chart, overlay = css.index("svg[role=img] {"), css.index(".vw-stage>svg.vw-areas {")
    rule = css[overlay:css.index("}", overlay)]
    assert overlay > chart and "background:none" in rule and "box-shadow:none" in rule


# -- the smoothness of the borders: a live slider (REQ-052, DEC-083) --------------------------------------------------------------
def smoothing(c, j, mm):
    return c["client"].post(f"/api/vector/{j['id']}/smoothing", json={"mm": mm})


def test_a_new_photograph_work_starts_smooth_and_the_slider_changes_only_the_drawing_of_the_borders(work, job):
    c, j = work, job
    assert j["smoothing_mm"] == vector_job.SMOOTHING_MM == 0.5 and j["smoothing_max_mm"] == vector_job.SMOOTHING_MAX_MM
    j = colouring(c, j, op="paint", region=areas(c, j)["paper"], scope="region", entry_id=by_rgb(j, BLUE)["entry_id"])
    before = c["client"].get(f"/api/vector/{j['id']}").json()
    svg_smooth = c["client"].get(f"/api/vector/{j['id']}/split.svg").text
    assert " C" in svg_smooth
    r = smoothing(c, j, 0)
    assert r.status_code == 200 and r.json()["smoothing_mm"] == 0
    after = r.json()
    keep = ("document", "colours", "layers", "split", "undo", "redo", "variants", "history", "missing", "export_blocked")
    assert {k: after[k] for k in keep} == {k: before[k] for k in keep}                           # no region, colour, undo step or history entry
    traced = c["client"].get(f"/api/vector/{j['id']}/split.svg").text
    assert " C" not in traced and traced != svg_smooth and len(traced) > len(svg_smooth)             # every traced point, against few curves
    assert smoothing(c, j, 1.25).json()["smoothing_mm"] == 1.25
    assert c["client"].get(f"/api/vector/{j['id']}/split.svg").text not in (traced, svg_smooth)
    assert smoothing(c, j, 0.5).status_code == 200
    assert c["client"].get(f"/api/vector/{j['id']}/split.svg").text == svg_smooth                  # back to the same picture, whatever the order
    assert pl.get_plan(work["store"], j["id"])["smoothing_mm"] == 0.5


def test_the_slider_never_resets_the_colouring_and_undo_goes_on_where_it_was(work, job):
    c, j = work, job
    j = colouring(c, j, op="paint", region=areas(c, j)["paper"], scope="region", entry_id=by_rgb(j, BLUE)["entry_id"])
    state = (j["undo"], j["redo"], j["document"]["version"], [v["number"] for v in j["variants"]])
    for mm in (0, 2, 0.35):
        j = smoothing(c, j, mm).json()
    assert (j["undo"], j["redo"], j["document"]["version"], [v["number"] for v in j["variants"]]) == state
    j = colouring(c, j, op="undo")
    assert j["undo"] == 0 and j["redo"] == 1 and j["smoothing_mm"] == 0.35                        # undo returns the colours, not the slider
    j = colouring(c, j, op="redo")
    assert j["smoothing_mm"] == 0.35 and by_rgb(j, BLUE)["regions"] >= 1


@pytest.mark.parametrize("bad", [-0.1, 2.01, 5, "wide", None, True, float("nan"), [1]])
def test_a_smoothing_outside_the_slider_is_refused_and_changes_nothing(work, job, bad):
    c, j = work, job
    r = c["client"].post(f"/api/vector/{j['id']}/smoothing", content=json.dumps({"mm": bad}), headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["error"] == "the smoothing must be a number of millimetres from 0 to 2"
    assert c["client"].get(f"/api/vector/{j['id']}").json()["smoothing_mm"] == vector_job.SMOOTHING_MM


def test_a_work_made_before_the_slider_has_its_borders_as_traced_until_it_is_moved(work, job):
    c, j, store = work, job, work["store"]
    plan = pl.get_plan(store, j["id"])
    del plan["smoothing_mm"]                                                                       # as release 0.7.0 and earlier stored it
    cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    assert view["smoothing_mm"] == 0 and " C" not in c["client"].get(f"/api/vector/{j['id']}/split.svg").text
    assert smoothing(c, view, 0.8).json()["smoothing_mm"] == 0.8 and " C" in c["client"].get(f"/api/vector/{j['id']}/split.svg").text


def test_the_file_is_written_at_the_smoothness_the_preview_shows_and_the_export_says_so(work, job):
    c, j = work, job
    for number, mm in ((1, 0), (2, 1.0)):
        smoothing(c, j, mm)
        r = c["client"].get(f"/api/vector/{j['id']}/export.lbrn2")
        assert r.status_code == 200
        prims = re.findall(r"<PrimList>([^<]*)</PrimList>", r.text)
        assert prims and ("B" in "".join(prims)) is (mm > 0)                                      # curves exactly when the work is smooth
        project = lb.parse_bytes(r.content)
        dx, dy = pl.export_offset(pl.get_plan(c["store"], j["id"]))
        regions = [p for layer in project.layers if layer.index > 0 for p in layer.regions]
        assert regions and all(p.closed and p.kind == "path" for p in regions)
        back = [[[(x - dx, y - dy) for x, y in loop] for loop in [p.polygon] + p.holes] for p in regions]
        cov = sg.coverage(back, 60, 45, 16)
        assert cov["uncovered"] < 0.005 and cov["overlap"] < 0.005                                # smooth borders still tile the picture
        assert pl.get_plan(work["store"], j["id"])["exports"][-1]["smoothing_mm"] == mm
        assert c["client"].get(f"/api/vector/{j['id']}").json()["exports"][-1]["number"] == number


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_slider_sends_the_last_position_once_and_the_editor_redraws_the_borders_for_it(work, job, tmp_path):
    j = job
    routes = routes_of(work, j)
    moved = {**routes[f"/api/vector/{j['id']}"]["json"], "smoothing_mm": 1.2}
    routes[f"/api/vector/{j['id']}/smoothing"] = {"status": 200, "json": moved}
    out = run_screen(tmp_path, j, routes, """
  const slider = tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Гладкость линий, мм');
  out.initial = [slider.getAttribute('type'), slider.getAttribute('min'), slider.getAttribute('max'), slider.getAttribute('step'), slider.value];
  const readout = tree.querySelectorAll('output').find((o) => o.className === 'vw-slider-value');
  out.readoutBefore = readout.textContent;
  const geometryBefore = ctx.requests.filter((r) => r.path.endsWith('/split.svg')).length;
  for (const v of ['0.3', '0.6', '0.9', '1.2']) { slider.value = v; await slider.dispatch('input'); }
  out.readoutDuring = readout.textContent;
  await new Promise((r) => setTimeout(r, 400));
  await tick(); await tick();
  out.posted = ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, JSON.parse(r.body)]);
  out.geometry = ctx.requests.filter((r) => r.path.endsWith('/split.svg')).length - geometryBefore;
  out.renders = ctx.__renders.length;
  out.stillThere = tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Гладкость линий, мм') === slider;
  out.readoutAfter = readout.textContent;
""")
    assert out["initial"] == ["range", "0", "2", "0.05", "0.5"] and out["readoutBefore"].replace(",", ".") == "0.50 мм"
    assert out["readoutDuring"].replace(",", ".") == "1.20 мм"                                                         # the number follows the finger at once
    assert out["posted"] == [[f"/api/vector/{j['id']}/smoothing", {"mm": 1.2}]]                    # one request, with the last position
    assert out["geometry"] == 1 and out["renders"] == 0                                            # the borders are fetched again, nothing else redrawn
    assert out["stillThere"] and out["readoutAfter"].replace(",", ".") == "1.20 мм"                                   # the slider is the same element, still in the hand


def test_the_editor_and_the_slider_are_wired_to_the_smoothness_of_the_work():
    editor = (UI / "screens" / "vector-editor.js").read_text(encoding="utf-8")
    assert "const geometryKey = (j) => `${j.document.version}:${j.smoothing_mm || 0}`;" in editor and "loadedVersion !== geometryKey(j)" in editor
    split_js = (UI / "screens" / "vector-split.js").read_text(encoding="utf-8")
    assert "type: 'range'" in split_js and "'aria-label': 'Гладкость линий, мм'" in split_js and "max: String(j.smoothing_max_mm || 2)" in split_js


def test_a_work_can_be_made_when_every_measured_colour_of_the_titanium_changed_under_its_settings(tmp_path):
    """REQ-045, DEC-083: contradicted colours are not taken by the automatic choice, but when nothing else exists the work is still coloured with
    them (never refused), and every one of its colours says so."""
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    ti = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1, surface="brushed")["id"]
    obs.add(store, w, lab(RED), power=20, speed=500, line_interval=0.02, material_id=ti, layer_type="Scan")
    obs.add(store, w, lab(BLUE), power=20, speed=500, line_interval=0.02, material_id=ti, layer_type="Scan")    # the same settings, another colour
    with TestClient(app) as client:
        r = create({"client": client, "store": store, "w": w, "ti": ti, "app": app})
        assert r.status_code == 201, r.text
        j = r.json()
        assert j["entries"] and {e["caution"] for e in j["entries"].values()} == {"contradicted"} and not any(e["automatic"] for e in j["entries"].values())
        assert all(c["entry_id"] in j["entries"] for c in j["colours"] if c["status"] == "automatic")
    store.close()
