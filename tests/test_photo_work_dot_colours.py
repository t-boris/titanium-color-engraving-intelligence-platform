"""The colour of a dot kind's dots picked on the colour map (0.25.0, DEC-118). The map of the work's laser and lens tells each colour what it
gives the dots or why it cannot (another titanium, a step finer than 0.0085 mm, a cross-hatched fill, a tone of a dot engraving); a fill
makes every dot fire at its settings, its step the dots' pitch, in the look, the close-up, the time, the LightBurn file and the ramp of
the kind, at its colour at the work's width; a tone of a grey scale puts the dots on that scale at its power; a power on the scale, another
scale or undo puts them back. The violet fill below was engraved twice, in rows 40 and 80 mm long."""
import json
import math

import cv2
import numpy as np
import pytest

import obs
import synth
from test_grey_scales import app_world, picture_png  # noqa: F401  (the measured grey-ramp plate, four scales)
from titanium_platform import dot_colours as dc, ingest as ig, lightburn, plans, photo_work, prediction_store as ps, row_length, setup as su

ROWS = {"/violet-40.lbrn2": 40.0, "/violet-80.lbrn2": 80.0}
VIOLET_40, VIOLET_80 = [45.0, 15.0, -30.0], [55.0, 10.0, -20.0]
VIOLET = {"power": 20, "frequency": 60, "speed": 500, "pulse_width": 300, "line_interval": 0.02}


@pytest.fixture(scope="module")
def world(app_world):
    """The grey-ramp world with fills of its laser, lens and titanium beside the scales: the violet one at two row lengths, one too fine
    for dots, one cross-hatched, one on another titanium and one that is measured until a test deletes it."""
    store = app_world["client"].app.state.store
    stand = su.save_capture_setup(store, "Fill rig", "cam", "LED", "90", "ColorChecker Classic")
    w = {"device": app_world["laser"], "setup": (app_world["laser"]["id"], app_world["lens"]["id"]), "stand": stand, "n": 1000}
    titanium = app_world["titanium"]["id"]
    other = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0)["id"]

    def fill(lab, material_id=titanium, path=None, lightburn=None, **settings) -> int:
        observation = obs.add(store, w, lab, material_id=material_id, layer_type="Scan", lightburn=lightburn, **{**VIOLET, **settings})
        pair = store.one("SELECT pair_id FROM observation WHERE id=?", (observation,))["pair_id"]
        if path:
            store.execute("UPDATE pair SET lightburn_path=? WHERE id=?", (path, pair))
        return pair

    fill(VIOLET_40, path="/violet-40.lbrn2")
    fill(VIOLET_80, path="/violet-80.lbrn2")
    fill([60.0, 5.0, 25.0], speed=600, line_interval=0.005)
    fill([50.0, 0.0, 10.0], speed=700, lightburn={"cross_hatch": True})
    fill([40.0, 0.0, -10.0], material_id=other, speed=800)
    gone = fill([35.0, 20.0, -35.0], speed=900, path="/violet-40.lbrn2")
    patch = pytest.MonkeyPatch()
    real = row_length.of_file
    patch.setattr(row_length, "of_file", lambda path: {1: ROWS[path]} if path in ROWS else real(path))
    yield {**app_world, "store": store, "gone": gone}
    patch.undo()


def create(client, **fields):
    answer = client.post("/api/photo-works", data={"width_mm": 60, **fields}, files={"picture": ("girl.png", picture_png(), "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def settings(client, work, **changes):
    answer = client.post(f"/api/photo-works/{work['id']}/settings", json=changes)
    assert answer.status_code == 200, answer.text
    return answer.json()


def refused(client, work, **changes) -> str:
    answer = client.post(f"/api/photo-works/{work['id']}/settings", json=changes)
    assert answer.status_code == 422, answer.text
    return answer.json()["error"]


def the_map(client, work, **params) -> dict:
    answer = client.get("/api/colors", params={"dots": work["id"], **params})
    assert answer.status_code == 200, answer.text
    return answer.json()


def group(found: dict, speed, source=None) -> str:
    (point,) = {p["group"]: p for p in found["points"] if p["parameters"]["speed"] == speed and p.get("source") == source}.values()
    return point["group"]


def png(client, path) -> np.ndarray:
    answer = client.get(path)
    assert answer.status_code == 200 and answer.headers["content-type"] == "image/png", answer.text
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(answer.content, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def rgb(hex_colour: str) -> tuple:
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def between(width_mm: float) -> list[float]:
    """The violet fill's colour in rows ``width_mm`` long between its two sizes, in the logarithm of the length (DEC-107)."""
    t = math.log(width_mm / 40.0) / math.log(80.0 / 40.0)
    return [(1 - t) * a + t * b for a, b in zip(VIOLET_40, VIOLET_80)]


def test_the_map_of_the_works_laser_and_lens_tells_each_colour_what_it_gives_the_dots_or_why_not(world):
    client = world["client"]
    work = settings(client, create(client), kind="jarvis")
    found = the_map(client, work, setup="laser:999/lens:unknown")                 # the address may say another laser: the work's is shown
    dots = found["dots"]
    setup = su.setup_key(world["laser"]["id"], world["lens"]["id"])
    assert dots["setup"] == setup and {p["setup"] for p in found["points"]} == {setup} and dots["step_min_mm"] == dc.STEP_MIN_MM
    assert (dots["work"]["id"], dots["work"]["kind"], dots["work"]["width_mm"], dots["work"]["dot_recipe"]) == (work["id"], "jarvis", 60, None)
    choices = dots["groups"]
    assert choices[group(found, 500)] == {"fill": True}
    assert choices[group(found, 600)] == {"reason": "step"}
    assert choices[group(found, 700)] == {"reason": "cross_hatch"}
    assert choices[group(found, 800)] == {"reason": "titanium"}
    tones = {p["group"] for p in found["points"] if p.get("source") == "tonal"}
    assert tones and all("scale" in choices[g] or choices[g] == {"reason": "power"} for g in tones)
    assert set(dots["reasons"]) == set(dc.REASONS) and f"finer than {dc.STEP_MIN_MM:g} mm" in dc.REASONS["step"]
    assert "dots" not in client.get("/api/colors").json()                         # the map alone knows nothing of dots
    assert client.get("/api/colors", params={"dots": 99999}).status_code == 404


def test_a_fill_makes_every_dot_fire_at_its_settings_at_its_colour_at_the_works_width(world):
    client, store = world["client"], world["store"]
    work = create(client, name="Фиолетовые точки")
    dotted = settings(client, work, kind="jarvis")
    picked = settings(client, work, dot_colour=group(the_map(client, work), 500))
    recipe = picked["dot_recipe"]
    assert recipe["settings"] == {**VIOLET, "passes": 1, "global_passes": 1}
    assert recipe["size"] == {"row_mm": 60.0, "how": "between", "measured_mm": [40.0, 80.0], "from_mm": [40.0, 80.0]}
    assert recipe["lab"] == pytest.approx(between(60), abs=0.01) and (recipe["engravings"], recipe["missing"]) == (2, False)
    dots = picked["picture"]["dots"]
    assert (dots["source"], dots["power"], picked["picture"]["estimate"]) == ("map", 20.0, True) and dots["lab"] == pytest.approx(recipe["lab"])
    assert picked["dot_power"] == dotted["dot_power"]                             # the scale's power waits for «На шкалу»
    assert picked["dpi"] == 1270 and picked["picture"]["dpi"] == 1270             # the step of the fill is the dots' pitch
    plan = photo_work._work(store, work["id"])
    mode = photo_work.mode_of(plan)
    fired = dc.fired_at(mode, recipe)
    assert picked["time"] == ps.picture_time(fired, 60, 30, ps.cleaning(store, mode)) and picked["time"] != dotted["time"]
    # the close-up: the fill's colour and the cleaned titanium, dot for dot at the fill's step
    close = png(client, picked["picture"]["closeup"])
    assert close.shape[0] == round(ps.CLOSEUP_MM / 25.4 * 1270) * ps.CLOSEUP_PX
    assert {tuple(c) for c in close.reshape(-1, 3)} == {rgb(dots["hex"]), rgb(dots["clean_hex"])}
    # the file: the picture as uploaded in Jarvis at the fill's settings, Min = Max at its power
    file = client.get(picked["picture"]["file"])
    assert file.status_code == 200 and "-jarvis-P20.lbrn2" in file.headers["content-disposition"]
    layer = lightburn.parse_bytes(file.content).layer(1)
    summary = layer.image_summary()
    assert (summary["dither"], layer.power, summary["min_power"], layer.speed, layer.frequency_hz) == ("jarvis", 20, 20, 500, 60000)
    assert (layer.pulse_width, layer.line_interval, summary["dpi"]) == (300, 0.02, 1270)
    kinds = {k["key"]: k for k in client.get(f"/api/photo-works/{work['id']}/kinds").json()["kinds"]}
    assert (kinds["atkinson"]["power"], kinds["atkinson"]["hex"], kinds["atkinson"]["source"]) == (20.0, dots["hex"], "map")
    listed = next(w for w in client.get("/api/photo-works").json() if w["id"] == work["id"])
    assert listed["dot_recipe"]["entry"] == recipe["entry"] and listed["dpi"] == 1270


def test_the_dots_go_back_on_the_scale_by_undo_by_a_power_on_the_scale_and_by_another_scale(world):
    client = world["client"]
    work = create(client)
    dotted = settings(client, work, kind="atkinson")
    violet = group(the_map(client, work), 500)
    settings(client, work, dot_colour=violet)
    undone = client.post(f"/api/photo-works/{work['id']}/undo").json()
    assert undone["dot_recipe"] is None and undone["picture"]["dots"]["source"] == "scale" and undone["dpi"] == dotted["dpi"]
    redone = client.post(f"/api/photo-works/{work['id']}/redo").json()
    assert redone["dot_recipe"]["settings"]["speed"] == 500 and redone["picture"]["dots"]["source"] == "map"
    back = settings(client, work, dot_power=dotted["dot_power"])
    assert back["dot_recipe"] is None and back["picture"]["dots"]["power"] == dotted["dot_power"]
    settings(client, work, dot_colour=violet)
    scales = client.get("/api/grey-scales", params={"device_id": world["laser"]["id"]}).json()["scales"]
    other = next(sc["mode"] for sc in scales if not ps.Mode(**sc["mode"]).matches(work["scale"]))
    moved = settings(client, work, scale=other)
    assert moved["dot_recipe"] is None and moved["scale"]["speed"] == other["speed"]


def test_a_tone_of_a_grey_scale_puts_the_dots_on_that_scale_at_its_power(world):
    client = world["client"]
    work = settings(client, create(client), kind="stucki")
    found = the_map(client, work)
    choices = found["dots"]["groups"]
    tone = next(p for p in found["points"] if p.get("source") == "tonal" and "scale" in choices[p["group"]]
                and not ps.Mode(**choices[p["group"]]["scale"]).matches(work["scale"]))
    picked = settings(client, work, dot_colour=tone["group"])
    assert ps.Mode(**picked["scale"]).matches(tone["parameters"]) and picked["dot_power"] == tone["parameters"]["power"]
    assert picked["dot_recipe"] is None and picked["picture"]["dots"]["source"] == "scale" and picked["kind"] == "stucki"


def test_a_new_width_takes_the_fills_colour_there_and_a_fill_no_longer_measured_keeps_its_colour_marked(world):
    client, store = world["client"], world["store"]
    work = settings(client, create(client), kind="jarvis")
    found = the_map(client, work)
    picked = settings(client, work, dot_colour=group(found, 500))
    wider = settings(client, work, width_mm=80)
    assert wider["dot_recipe"]["lab"] == pytest.approx(VIOLET_80) and wider["dot_recipe"]["size"]["how"] == "measured"
    assert wider["dot_recipe"]["picked_at"] == picked["dot_recipe"]["picked_at"] and wider["picture"]["dots"]["lab"] == pytest.approx(VIOLET_80)
    assert client.post(f"/api/photo-works/{work['id']}/undo").json()["dot_recipe"]["lab"] == pytest.approx(between(60), abs=0.01)
    gone = settings(client, work, dot_colour=group(found, 900))
    store.execute("UPDATE pair SET status='Deleted' WHERE id=?", (world["gone"],))
    kept = settings(client, work, width_mm=45)
    assert kept["dot_recipe"]["missing"] and kept["dot_recipe"]["lab"] == gone["dot_recipe"]["lab"]       # its colour as it was picked
    assert kept["picture"]["dots"]["lab"] == pytest.approx(gone["dot_recipe"]["lab"]) and kept["picture"]["file"]
    assert client.get(kept["picture"]["file"]).status_code == 200


def test_a_colour_that_cannot_be_the_dots_is_refused_with_the_reason(world):
    client = world["client"]
    work = create(client)
    found = the_map(client, work)
    assert refused(client, work, dot_colour=group(found, 500)) == "the dots' colour is picked for a dot kind: choose one of them first"
    with_kind = settings(client, work, kind="jarvis", dot_colour=group(found, 500))                  # a kind and its dots' colour at once
    assert with_kind["kind"] == "jarvis" and with_kind["dot_recipe"]["settings"]["speed"] == 500
    assert refused(client, work, dot_colour=group(found, 600)) == f"this colour cannot be the dots' colour: {dc.REASONS['step']}"
    assert refused(client, work, dot_colour=group(found, 800)) == f"this colour cannot be the dots' colour: {dc.REASONS['titanium']}"
    assert refused(client, work, dot_colour="no such colour").startswith("this colour is not on the colour map")
    assert refused(client, work, dot_colour=7) == "pick a colour of the colour map for the dots"
    assert client.get(f"/api/photo-works/{work['id']}").json()["dot_recipe"]["settings"]["speed"] == 500     # refusals change nothing


def test_a_ramp_of_the_kind_at_the_fills_settings_once_photographed_replaces_the_estimate(world):
    client, store = world["client"], world["store"]
    work = settings(client, create(client, name="Проба фиолетовых точек"), kind="jarvis")
    picked = settings(client, work, dot_colour=group(the_map(client, work), 500))
    made = client.post(f"/api/photo-works/{work['id']}/width-ramp")
    assert made.status_code == 201, made.text
    plan = plans.get_plan(store, made.json()["plan_id"])
    (tile,) = [layer for layer in plan["layers"] if layer.get("ramp")]
    p = tile["parameters"]
    assert (tile["ramp"]["dither"], p["power"], p["min_power"], p["speed"], p["frequency"], p["line_interval"]) == ("jarvis", 20, 20, 500, 60, 0.02)
    file = plans.export_lbrn2(plan)
    dots = picked["picture"]["dots"]
    clean, dot = np.array(rgb(dots["clean_hex"]), float), np.array(rgb(dots["hex"]), float)
    photo = synth.plate_photo(plan, {}, size=(1300, 2800),
                              step_rgb=lambda name, grey: tuple(int(v) for v in np.round(clean + (dot - clean) * 0.6 * (1 - grey))))
    pid = ig.create_pair(store, device_id=world["laser"]["id"], lens_id=world["lens"]["id"],
                         stand_id=store.one("SELECT id FROM capture_setup ORDER BY id LIMIT 1")["id"], lightburn_name="violet-dots.lbrn2",
                         lightburn_bytes=file, photo_name="violet-dots.png", context={"material_id": work["scale"]["material_id"]},
                         photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    assert ig.check_pair(store, pid)["problems"] == []
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)
    measured = client.get(f"/api/photo-works/{work['id']}").json()
    assert not measured["picture"]["estimate"] and measured["picture"]["dots"]["measured"]["tones"] >= 8
    after = the_map(client, work)
    tones = [p for p in after["points"] if p["pair_id"] == pid]
    assert tones and {after["dots"]["groups"][p["group"]]["reason"] for p in tones} == {"dots"}          # dots mixed with titanium, not a dot
    on_scale = settings(client, work, dot_power=work["dot_power"])
    assert on_scale["picture"]["estimate"]                                                              # measured at the fill's settings only
    assert json.loads(store.one("SELECT data_json FROM plan WHERE id=?", (work["id"],))["data_json"])["dot_recipe"] is None


def test_an_open_work_is_dithered_once_and_again_only_when_its_look_changes(world, monkeypatch):
    client = world["client"]
    work = settings(client, create(client), kind="jarvis")
    drawn = []
    real = photo_work._dot_look
    monkeypatch.setattr(photo_work, "_dot_look", lambda *a, **k: drawn.append(1) or real(*a, **k))
    first = client.get(f"/api/photo-works/{work['id']}").json()
    again = client.get(f"/api/photo-works/{work['id']}").json()
    assert drawn == [] and again["picture"]["dots"] == first["picture"]["dots"] == work["picture"]["dots"]      # the look made by the save
    settings(client, work, dot_colour=group(the_map(client, work), 500))
    assert drawn == [1]
