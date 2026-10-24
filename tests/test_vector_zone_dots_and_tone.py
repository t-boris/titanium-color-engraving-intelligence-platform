"""A photo zone of a vector work in a dot kind takes its dots' colour from the colour map as a photo work does (0.27.0, DEC-118): a fill of
the work's laser, lens and titanium makes every dot of the zone's Image layer fire at its settings (its step the layer's DPI), at its
colour at the zone's width; a tone of a grey scale moves the zone to that scale and power; a power on the scale puts the dots back. And
the zone's picture takes the brightness, contrast and gamma of a photo work: its look and its layer in the file carry the same greys.
Every change is one step of the work's editor."""
import math

import cv2
import numpy as np
import pytest

import obs
from test_grey_scales import app_world  # noqa: F401  (a laser, lens and titanium with four measured grey scales)
from test_vector_photo_zones import RED, YELLOW, colouring, create, of_colour, refused, world, zone_grey  # noqa: F401
from titanium_platform import dot_colours as dc, lightburn as lb, photo_zones as pz, plans as pl, prediction_store as ps, row_length

AS_IT_IS = {"brightness": 0.0, "contrast": 0.0, "gamma": 1.0}
ROWS = {"/violet-10.lbrn2": 10.0, "/violet-100.lbrn2": 100.0}
VIOLET_10, VIOLET_100 = [45.0, 15.0, -30.0], [55.0, 10.0, -20.0]


def the_map(world, job, zone=1) -> dict:
    answer = world["client"].get("/api/colors", params={"dots": job["id"], "zone": zone})
    assert answer.status_code == 200, answer.text
    return answer.json()


def fill(found: dict, power) -> str:
    """The group of the measured fill at ``power`` (the five fills of the world: 500 mm/s, a step of 0.02 mm)."""
    (group,) = {p["group"] for p in found["points"] if p.get("source") != "tonal" and p["parameters"]["power"] == power}
    return group


def zone_layer(world, job) -> lb.Layer:
    project = lb.parse_bytes(world["client"].get(f"/api/vector/{job['id']}/export.lbrn2").content)
    return sorted(project.layers, key=lambda layer: layer.index)[-1]


def dotted_zone(world):
    job = create(world)
    colouring(world, job, op="photo_add", regions=of_colour(world, job, RED))
    return job, colouring(world, job, op="photo_set", zone=1, kind="jarvis")["zones"][0]


@pytest.fixture
def violet(world, monkeypatch):
    """A violet fill of the zones' laser, lens and titanium at 70 % (500 mm/s, a step of 0.02 mm) engraved twice, in rows 10 and 100 mm
    long; its two pairs, deleted after the test so the other tests of the module never see it."""
    store, pairs = world["store"], []
    for path, lab in zip(ROWS, (VIOLET_10, VIOLET_100)):
        observation = obs.add(store, world["w"], lab, power=70, speed=500, line_interval=0.02, material_id=world["titanium"]["id"], layer_type="Scan")
        pairs.append(store.one("SELECT pair_id FROM observation WHERE id=?", (observation,))["pair_id"])
        store.execute("UPDATE pair SET lightburn_path=? WHERE id=?", (path, pairs[-1]))
    real = row_length.of_file
    monkeypatch.setattr(row_length, "of_file", lambda path: {1: ROWS[path]} if path in ROWS else real(path))
    yield pairs
    store.execute(f"UPDATE pair SET status='Deleted' WHERE id IN ({','.join('?' * len(pairs))})", pairs)


def between(width_mm: float) -> list[float]:
    """The violet fill's colour in rows ``width_mm`` long between its two sizes, in the logarithm of the length (DEC-107)."""
    t = math.log(width_mm / 10.0) / math.log(100.0 / 10.0)
    return [(1 - t) * a + t * b for a, b in zip(VIOLET_10, VIOLET_100)]


def test_the_colour_map_of_a_zone_tells_each_colour_what_it_gives_its_dots(world):
    job, zone = dotted_zone(world)
    found = the_map(world, job)
    dots = found["dots"]
    work = dots["work"]
    assert (work["id"], work["zone"], work["kind"], work["dot_recipe"]) == (job["id"], 1, "jarvis", None)
    assert work["width_mm"] == pytest.approx(zone["width_mm"]) and work["material"]["id"] == world["titanium"]["id"]
    assert dots["groups"][fill(found, 30)] == {"fill": True} and set(dots["reasons"]) == set(dc.REASONS)
    assert {p["setup"] for p in found["points"]} == {dots["setup"]}
    assert world["client"].get("/api/colors", params={"dots": job["id"], "zone": 9}).status_code == 404


def test_a_fill_picked_on_the_map_makes_the_zones_dots_fire_at_its_settings_in_the_look_the_time_and_the_file(world):
    job, zone = dotted_zone(world)
    picked = colouring(world, job, op="photo_set", zone=1, dot_colour=fill(the_map(world, job), 30))["zones"][0]
    recipe = picked["dot_recipe"]
    assert recipe["settings"]["power"] == 30 and recipe["settings"]["speed"] == 500 and recipe["settings"]["line_interval"] == 0.02
    assert recipe["size"]["row_mm"] == round(picked["width_mm"], 1)
    assert picked["dots"]["source"] == "map" and picked["dots"]["power"] == 30.0 and picked["dot_power"] == zone["dot_power"]
    assert picked["picture"] != zone["picture"] and picked["name"].endswith("jarvis P30")
    view = world["client"].get(f"/api/vector/{job['id']}/photo/1").json()
    assert view["dpi"] == 1270 and view["picture"]["dpi"] == 1270 and view["picture"]["dots"]["source"] == "map"
    assert view["dot_recipe"]["entry"] == recipe["entry"]
    layer = zone_layer(world, job)
    summary = layer.image_summary()
    assert (summary["dither"], layer.power, summary["min_power"], layer.speed, layer.line_interval, summary["dpi"]) == ("jarvis", 30, 30, 500, 0.02, 1270)
    close = world["client"].get(view["picture"]["closeup"])
    assert close.status_code == 200
    shape = cv2.imdecode(np.frombuffer(close.content, np.uint8), cv2.IMREAD_COLOR).shape
    assert shape[0] == round(4.0 / 25.4 * 1270) * 3                                                   # dot for dot at the fill's step
    kinds = {k["key"]: k for k in world["client"].get(f"/api/vector/{job['id']}/photo/1/kinds").json()["kinds"]}
    assert (kinds["atkinson"]["source"], kinds["atkinson"]["power"], kinds["atkinson"]["hex"]) == ("map", 30.0, picked["dots"]["hex"])


def test_the_zones_dots_go_back_on_the_scale_by_a_power_by_undo_and_follow_a_new_width(world):
    job, zone = dotted_zone(world)
    colouring(world, job, op="photo_set", zone=1, dot_colour=fill(the_map(world, job), 30))
    back = colouring(world, job, op="photo_set", zone=1, dot_power=zone["dot_power"])["zones"][0]
    assert back["dot_recipe"] is None and back["dots"]["source"] == "scale"
    again = colouring(world, job, op="undo")["zones"][0]
    assert again["dot_recipe"]["settings"]["power"] == 30
    assert colouring(world, job, op="undo")["zones"][0]["dot_recipe"] is None
    colouring(world, job, op="redo")
    wider = colouring(world, job, op="photo_add", zone=1, regions=of_colour(world, job, YELLOW))["zones"][0]
    assert wider["width_mm"] != again["width_mm"] and wider["dot_recipe"]["size"]["row_mm"] == round(wider["width_mm"], 1)
    assert wider["dot_recipe"]["picked_at"] == again["dot_recipe"]["picked_at"]


def test_another_scale_puts_the_zones_dots_from_the_map_back_on_a_scale_and_undo_and_redo_step_over_it(world):
    """photo-zone-dots REQ-001 crit. 5: another scale while the dots have a colour of the map clears the recipe; it is one step of the editor."""
    job, zone = dotted_zone(world)
    picked = colouring(world, job, op="photo_set", zone=1, dot_colour=fill(the_map(world, job), 30))["zones"][0]
    store = world["store"]
    plan = pl.get_plan(store, job["id"])
    other = next(m for m in ps.scale_modes(store, plan["device_id"], plan["lens_id"], plan["material_id"]) if pz.scale_data(m) != zone["scale"])
    moved = colouring(world, job, op="photo_set", zone=1, scale=pz.scale_data(other))["zones"][0]
    assert moved["scale"] == pz.scale_data(other) and moved["kind"] == "jarvis"
    assert moved["dot_recipe"] is None and moved["dots"]["source"] == "scale"
    layer = zone_layer(world, job)
    assert (layer.speed, layer.line_interval) == (other.speed, other.line_interval)                       # the file fires at the scale again
    undone = colouring(world, job, op="undo")["zones"][0]
    assert undone["scale"] == zone["scale"] and undone["dot_recipe"] == picked["dot_recipe"] and undone["dots"]["source"] == "map"
    redone = colouring(world, job, op="redo")["zones"][0]
    assert redone["scale"] == pz.scale_data(other) and redone["dot_recipe"] is None


def test_regions_taken_from_the_zone_take_the_fills_colour_at_the_new_width_and_a_fill_no_longer_measured_is_marked(world, violet):
    """photo-zone-dots REQ-001 crit. 6: regions added to or taken from the zone take the fill's colour again at the new width; a colour no
    longer measured keeps its colour as it was picked, marked missing."""
    job = create(world)
    red, yellow = of_colour(world, job, RED), of_colour(world, job, YELLOW)
    colouring(world, job, op="photo_add", regions=red + yellow)
    colouring(world, job, op="photo_set", zone=1, kind="jarvis")
    picked = colouring(world, job, op="photo_set", zone=1, dot_colour=fill(the_map(world, job), 70))["zones"][0]
    recipe = picked["dot_recipe"]
    assert recipe["size"]["how"] == "between" and recipe["size"]["measured_mm"] == [10.0, 100.0]
    assert recipe["lab"] == pytest.approx(between(picked["width_mm"]), abs=0.02)
    narrower = colouring(world, job, op="photo_remove", regions=yellow)["zones"][0]
    assert narrower["regions"] == red and narrower["width_mm"] < picked["width_mm"]
    kept = narrower["dot_recipe"]
    assert kept["size"]["row_mm"] == round(narrower["width_mm"], 1) and kept["lab"] == pytest.approx(between(narrower["width_mm"]), abs=0.02)
    assert kept["lab"] != recipe["lab"] and kept["picked_at"] == recipe["picked_at"] and not kept["missing"]
    assert narrower["dots"]["source"] == "map" and narrower["dots"]["lab"] == pytest.approx(kept["lab"])     # the look takes the new colour
    world["store"].execute(f"UPDATE pair SET status='Deleted' WHERE id IN ({','.join('?' * len(violet))})", violet)
    wider = colouring(world, job, op="photo_add", zone=1, regions=yellow)["zones"][0]
    gone = wider["dot_recipe"]
    assert wider["width_mm"] == picked["width_mm"] and gone["missing"] is True
    assert gone["lab"] == kept["lab"] and gone["size"] == kept["size"]                                       # its colour as it was last taken
    assert wider["dots"]["lab"] == pytest.approx(kept["lab"]) and zone_layer(world, job).power == 70        # still engraved at the fill


def test_a_tone_of_a_grey_scale_moves_the_zone_to_that_scale_and_a_grayscale_zone_cannot_pick_dots(world):
    job, zone = dotted_zone(world)
    found = the_map(world, job)
    choices = found["dots"]["groups"]
    tone = next(p for p in found["points"] if p.get("source") == "tonal" and "scale" in choices[p["group"]]
                and p["parameters"]["speed"] != zone["scale"]["speed"])
    moved = colouring(world, job, op="photo_set", zone=1, dot_colour=tone["group"])["zones"][0]
    assert moved["scale"]["speed"] == tone["parameters"]["speed"] and moved["dot_power"] == tone["parameters"]["power"]
    assert moved["dot_recipe"] is None and moved["dots"]["source"] == "scale"
    colouring(world, job, op="photo_set", zone=1, kind="grayscale")
    refused(world, job, {"op": "photo_set", "zone": 1, "dot_colour": fill(found, 30)}, "the dots' colour is picked for a dot kind: choose one of them first")
    refused(world, job, {"op": "photo_set", "zone": 1, "dot_recipe": {}}, "a photo zone has no setting 'dot_recipe'")


def test_the_zones_tone_is_in_its_look_and_its_layer_and_is_undone(world):
    job, zone = dotted_zone(world)
    plain = zone_grey(world, job)
    lighter = colouring(world, job, op="photo_set", zone=1, tone={"brightness": 20})["zones"][0]
    assert (lighter["tone"], lighter["tone_used"]) == ({**AS_IT_IS, "brightness": 20.0}, True) and lighter["picture"] != zone["picture"]
    toned = zone_grey(world, job)
    inside = (plain[..., 3] > 0) & (plain[..., 0] > 5) & (plain[..., 0] < 190)
    assert inside.sum() > 100 and np.abs(toned[..., 0][inside].astype(int) - plain[..., 0][inside].astype(int) - 51).max() <= 1
    assert np.array_equal(toned[..., 3], plain[..., 3])                                                # the same place, only lighter
    view = world["client"].get(f"/api/vector/{job['id']}/photo/1").json()
    assert view["tone"] == lighter["tone"] and view["picture"]["preview"]
    refused(world, job, {"op": "photo_set", "zone": 1, "tone": {"gamma": 9}}, "the picture's gamma must be a number from 0.2 to 5")
    added = colouring(world, job, op="photo_add", regions=of_colour(world, job, YELLOW))["zones"]
    assert [z["tone"]["brightness"] for z in added] == [20.0, 20.0]                                    # the next zone follows the last
    colouring(world, job, op="undo")
    undone = colouring(world, job, op="undo")["zones"][0]
    assert undone["tone"] == AS_IT_IS and undone["picture"] == zone["picture"] and np.array_equal(zone_grey(world, job), plain)


def test_a_tone_change_of_a_zone_that_was_undone_is_redone_with_its_look_and_its_layer(world):
    """photo-zone-dots REQ-002 crit. 6: each change of the tone is undone and redone."""
    job, zone = dotted_zone(world)
    plain = zone_grey(world, job)
    darker = colouring(world, job, op="photo_set", zone=1, tone={"contrast": 30, "gamma": 1.5})["zones"][0]
    toned = zone_grey(world, job)
    assert darker["tone_used"] and not np.array_equal(toned, plain)
    undone = colouring(world, job, op="undo")["zones"][0]
    assert undone["tone"] == AS_IT_IS and not undone["tone_used"] and np.array_equal(zone_grey(world, job), plain)
    redone = colouring(world, job, op="redo")["zones"][0]
    assert redone["tone"] == {**AS_IT_IS, "contrast": 30.0, "gamma": 1.5} and redone["tone_used"] and redone["picture"] == darker["picture"]
    assert np.array_equal(zone_grey(world, job), toned)
    view = world["client"].get(f"/api/vector/{job['id']}/photo/1").json()
    assert view["tone"] == redone["tone"] and view["work"]["redo"] == 0
