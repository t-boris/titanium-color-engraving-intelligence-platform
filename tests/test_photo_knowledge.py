"""What the workshop knows of photo engraving (feature photo-engraving-quality, REQ-003..REQ-005): the engravings judged from accepted
checks, the best of each kind, what a setting measurably does, one step darker, lighter, sharper or softer, and the experiments proposed.
The checks are written as an accepted check stores them (the layers' settings, image summary and tonal profile)."""
import json

import numpy as np
import pytest

from titanium_platform import devices, ingest as ig, lenses, photo_knowledge as pk, plans, setup as su
from titanium_platform.db import now

import test_photo_variations as tpv


@pytest.fixture
def world(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="PK-01")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    titanium = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)
    other = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0)
    return {"store": store, "laser": laser["id"], "lens": lens["id"], "titanium": titanium["id"], "other": other["id"]}


def tonal(lightness, measured_by="picture", powers=None):
    greys = np.linspace(0, 1, len(lightness))
    bins = [{"gray": round(float(g), 4), "L": float(l), "a": 0.0, "b": 0.0, "n": 100} for g, l in zip(greys, lightness)]
    if powers:
        for b in bins:
            b["power_pct"] = round(powers[0] + (powers[1] - powers[0]) * (1 - b["gray"]), 3)
    return {"bins": bins, "measured_by": measured_by, "evidence": "clear", "rho": 0.9}


def layer(name, dither, lightness, measured_by="picture", power=25.0, speed=125.0, interval=0.01, min_power=None, dot_width=None,
          detail=None, pulse=200.0):
    rep = {"index": 1, "name": name, "type": "Image", "power": power, "frequency_khz": 60.0, "speed": speed, "pulse_width": pulse,
           "line_interval": interval, "passes": 1, "global_passes": 1, "role": "test feature",
           "image": {"dither": dither, "min_power": min_power if dither == "grayscale" else power, "dot_width_mm": dot_width,
                     "dot_correction": dot_width is not None},
           "tonal": tonal(lightness, measured_by, (min_power, power) if dither == "grayscale" and measured_by == "grey ramp" else None)}
    if detail is not None:
        rep["quality"] = {"detail": {"kept": detail, "grain_L": 0.5}}
    return rep


def accepted(w, layers, material=None, plate_id=None, plan_id=None):
    """An accepted check of the laser and lens holding ``layers``, as accept_pair leaves it."""
    s = w["store"]
    with s.transaction():
        cur = s.execute(
            "INSERT INTO pair(status, device_id, lens_id, material_id, plate_id, plan_id, engraving_id, lightburn_name, lightburn_path, "
            "photo_name, photo_path, context_json, data_json, created_at, accepted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ig.ST_ACCEPTED, w["laser"], w["lens"], material or w["titanium"], plate_id, plan_id, f"E-{len(layers)}-{now()}", "x.lbrn2",
             "x.lbrn2", "x.png", "x.png", json.dumps({"material_id": material or w["titanium"]}),
             json.dumps({"check": {"layers": layers, "problems": [], "warnings": []}}), now(), now()))
    return cur.lastrowid


LINEAR = list(np.linspace(30, 80, 16))
BLOCKED = [30] * 6 + list(np.linspace(32, 78, 10))


def test_the_settings_of_a_layer_are_the_files_else_the_operators_and_a_dot_kind_fires_every_dot_at_its_power():
    rep = layer("A", "jarvis", LINEAR, dot_width=0.01, pulse=None)
    rep["supplied_settings"] = {"pulse_width": {"value": 250, "by": "operator"}}
    assert pk.settings_of(rep) == {"dither": "jarvis", "power": 25.0, "min_power": 25.0, "speed": 125.0, "frequency": 60.0, "pulse_width": 250.0,
                                   "line_interval": 0.01, "passes": 1, "global_passes": 1, "dot_width": 0.01}
    grey = pk.settings_of(layer("G", "grayscale", LINEAR, power=30, min_power=2))
    assert grey["min_power"] == 2 and grey["dot_width"] is None
    relief = layer("R", "3dslice", LINEAR)
    assert pk.settings_of(relief) is None


def test_the_best_engraving_of_a_kind_takes_its_tone_from_a_ramp_and_its_detail_from_the_picture(world):
    w = world
    accepted(w, [layer("PV1-PICTURE", "jarvis", BLOCKED, detail=0.9), layer("PV1-RAMP", "jarvis", LINEAR, "grey ramp")])
    accepted(w, [layer("C1", "jarvis", BLOCKED, power=30)])
    accepted(w, [layer("C2", "atkinson", LINEAR, power=15)], material=w["other"])
    found = pk.engravings(w["store"], w["laser"], w["lens"], w["titanium"], "jarvis")
    assert [e["settings"]["power"] for e in found] == [25.0, 30.0]
    top = found[0]
    assert top["measured_by"] == "grey ramp" and top["detail"]["kept"] == 0.9 and top["score"] == pytest.approx(0.9, abs=0.01)
    assert top["findings"][0]["code"] == "good"
    best = pk.best(w["store"], w["laser"], w["lens"], w["titanium"], "atkinson")
    assert best["other_titanium"] and best["settings"]["power"] == 15.0          # measured only on another titanium: said so
    assert pk.best(w["store"], w["laser"], w["lens"], w["titanium"], "stucki") is None


def test_a_zone_that_cannot_write_the_dot_width_gets_the_best_engraving_without_it(world):
    w = world
    accepted(w, [layer("A", "jarvis", LINEAR, dot_width=0.01), layer("B", "jarvis", BLOCKED, power=20)])
    assert pk.best(w["store"], w["laser"], w["lens"], w["titanium"], "jarvis")["settings"]["dot_width"] == 0.01
    assert pk.best(w["store"], w["laser"], w["lens"], w["titanium"], "jarvis", dot_width=False)["settings"]["power"] == 20.0


def test_ramps_that_differ_in_one_setting_measure_its_effect_and_the_step_follows_it(world):
    w = world
    lighter = [v + 6 for v in LINEAR]                                          # half the power: 6 L* lighter
    accepted(w, [layer("PV1-RAMP", "jarvis", LINEAR, "grey ramp", power=24.0), layer("PV2-RAMP", "jarvis", lighter, "grey ramp", power=12.0),
                 layer("PV3-RAMP", "jarvis", LINEAR, "grey ramp", power=24.0, speed=250.0, interval=0.02)])  # two changes: compares nothing
    found = pk.effects(w["store"], w["laser"], w["lens"], w["titanium"], "jarvis")
    assert list(found) == ["power"] and found["power"]["mean_L"] == {"median": -6.0, "n": 1}
    step = pk.adjust(w["store"], w["laser"], w["lens"], w["titanium"], {"dither": "jarvis", "power": 24, "speed": 125, "line_interval": 0.01}, "darker")
    assert step["basis"] == "measured" and step["changed"] == [{"setting": "power", "from": 24.0, "to": 34.0}]      # 2^(3/6) = 1.41
    assert step["settings"]["min_power"] == 34.0 and step["evidence"]["photographs"]
    lighter_step = pk.adjust(w["store"], w["laser"], w["lens"], w["titanium"], {"dither": "jarvis", "power": 24}, "lighter")
    assert lighter_step["changed"][0]["to"] == 17.0


def test_a_step_moves_the_setting_with_the_largest_measured_effect_even_when_another_rests_on_more_photographs(world):
    w = world
    for _ in range(2):                                                         # half the power: 3 L* lighter, on two plates
        accepted(w, [layer("PV1-RAMP", "jarvis", LINEAR, "grey ramp", power=24.0), layer("PV2-RAMP", "jarvis", [v + 3 for v in LINEAR], "grey ramp", power=12.0)])
    accepted(w, [layer("PV1-RAMP", "jarvis", LINEAR, "grey ramp", power=24.0),   # twice the speed: 8 L* lighter, on one plate
                 layer("PV2-RAMP", "jarvis", [v + 8 for v in LINEAR], "grey ramp", power=24.0, speed=250.0)])
    found = pk.effects(w["store"], w["laser"], w["lens"], w["titanium"], "jarvis")
    assert found["power"]["mean_L"]["median"] == -3.0 and found["speed"]["mean_L"]["median"] == 8.0
    assert found["power"]["mean_L"]["n"] > found["speed"]["mean_L"]["n"]
    step = pk.adjust(w["store"], w["laser"], w["lens"], w["titanium"], {"dither": "jarvis", "power": 24, "speed": 125, "line_interval": 0.01}, "darker")
    assert step["basis"] == "measured" and [c["setting"] for c in step["changed"]] == ["speed"] and step["changed"][0]["to"] < 125


def test_without_a_measured_effect_a_step_follows_the_prior_and_says_so(world):
    w = world
    s, a = w["store"], (w["laser"], w["lens"], w["titanium"])
    dots = {"dither": "atkinson", "power": 20, "speed": 125, "line_interval": 0.01}
    assert pk.adjust(s, *a, dots, "darker") == {"direction": "darker", "settings": {**pk.adjust(s, *a, dots, "darker")["settings"]},
                                                 "changed": [{"setting": "power", "from": 20.0, "to": 23.0}], "basis": "prior", "evidence": None}
    assert pk.adjust(s, *a, dots, "sharper")["changed"] == [{"setting": "dot_width", "from": None, "to": 0.01}]
    assert pk.adjust(s, *a, dots, "softer")["changed"] == [{"setting": "power", "from": 20.0, "to": 22.0}]       # no correction to take off
    grey = {"dither": "grayscale", "power": 30, "min_power": 29.8, "speed": 150, "line_interval": 0.02}
    # Max cannot come down below Min: lighter lowers Min, never raises Max
    assert pk.adjust(s, *a, grey, "lighter", allowed=("power", "min_power"))["changed"] == [{"setting": "min_power", "from": 29.8, "to": 25.0}]
    assert pk.adjust(s, *a, grey, "darker", allowed=("power", "min_power"))["changed"] == [{"setting": "power", "from": 30.0, "to": 33.0}]
    with pytest.raises(su.ValidationError):
        pk.adjust(s, *a, dots, "brighter")


def test_a_grayscale_ramp_that_turns_back_gives_the_span_below_the_turn_as_the_best_grayscale(world):
    w = world
    turning = [62, 55, 48, 41] + list(np.linspace(36, 80, 12))
    accepted(w, [layer("GREY-1", "grayscale", turning, "grey ramp", power=30.0, min_power=0.0, speed=150, interval=0.0212)])
    best = pk.best(w["store"], w["laser"], w["lens"], w["titanium"], "grayscale")
    assert best["span_of"] == "GREY-1" and best["settings"]["min_power"] == 0.0 and best["settings"]["power"] == pytest.approx(22.0, abs=0.05)
    assert best["tone"]["reversals"] == []


def test_the_laboratory_proposes_the_next_plate_of_a_search_and_a_plate_for_a_kind_never_photographed(world):
    w = world
    s = w["store"]
    s.set_setting("allow_non_raw_photos", True)
    made = tpv.make({"store": s, "laser": {"id": w["laser"]}, "titanium": {"id": w["titanium"]}}, variants=None)
    plate = s.one("SELECT geometry_json FROM plate WHERE id=?", (made["plate_id"],))
    copies = json.loads(plate["geometry_json"])["variations"]["copies"]
    layers = []
    for c in copies:                                       # copy 2 (power 20 %) keeps every tone; the others block the shadows
        good = c["copy"] == 2
        layers += [layer(c["picture_layer"], c["variant"]["dither"], LINEAR if good else BLOCKED, power=c["variant"]["power"], detail=0.95),
                   layer(c["ramp_layer"], c["variant"]["dither"], LINEAR if good else BLOCKED, "grey ramp", power=c["variant"]["power"])]
    for rep in layers:                                     # the copies' settings as the plate wrote them
        c = next(c for c in copies if rep["name"] in (c["picture_layer"], c["ramp_layer"]))
        rep.update(speed=c["variant"]["speed"], line_interval=c["variant"]["line_interval"], frequency_khz=c["variant"]["frequency"],
                   pulse_width=c["variant"]["pulse_width"])
        rep["image"]["dot_width_mm"], rep["image"]["dot_correction"] = c["variant"].get("dot_width"), c["variant"].get("dot_width") is not None
    pair_id = accepted(w, layers, plate_id=made["plate_id"], plan_id=made["plan_id"])
    known = pk.knowledge(s, w["laser"], w["lens"], w["titanium"])
    jarvis = next(k for k in known["kinds"] if k["kind"] == "jarvis")
    assert jarvis["status"] == "searching" and jarvis["proposal"]["kind"] == "next" and jarvis["proposal"]["step"] == 0.5
    assert jarvis["proposal"]["centre"]["power"] == 20.0 and jarvis["best"]["settings"]["power"] == 20.0
    assert jarvis["effects"]["power"]["mean_L"]["n"] >= 1
    stucki = next(k for k in known["kinds"] if k["kind"] == "stucki")
    assert stucki["status"] == "measured"                  # a copy of the plate was engraved in Stucki
    following = pk.next_plate(s, pair_id)
    geometry = json.loads(s.one("SELECT geometry_json FROM plate WHERE id=?", (following["plate_id"],))["geometry_json"])["variations"]
    assert geometry["step"] == 0.5 and geometry["copies"][0]["variant"]["power"] == 20.0
    assert [c["variant"]["power"] for c in geometry["copies"][1:3]] == [18.0, 22.0]          # ±10 %: half the first plate's changes
    assert geometry["picture"]["sha256"] == json.loads(plate["geometry_json"])["variations"]["picture"]["sha256"]
    grey = next(k for k in known["kinds"] if k["kind"] == "grayscale")
    assert grey["status"] == "unmeasured" and grey["proposal"] is None      # grayscale starts from the grey-scale plate, not from dots
    with pytest.raises(su.ValidationError):
        pk.proposed_plate(s, w["laser"], w["lens"], w["titanium"], "grayscale")
    around = pk.proposed_plate(s, w["laser"], w["lens"], w["titanium"], "stucki")          # one copy only: a plate of its own around it
    copies = json.loads(s.one("SELECT geometry_json FROM plate WHERE id=?", (around["plate_id"],))["geometry_json"])["variations"]["copies"]
    assert copies[0]["variant"]["dither"] == "stucki" and copies[0]["variant"]["power"] == 25.0


# -- the best settings filled in when a kind is chosen, and a step darker or lighter applied (REQ-004) ------------------------------
from test_grey_scales import app_world  # noqa: E402,F401  (a laser, lens and titanium with four measured grey scales)
from test_photo_work_kinds import create as create_work, settings as change_work  # noqa: E402
from test_vector_photo_zones import RED, colouring, create as create_job, of_colour, world as zone_world  # noqa: E402,F401
from titanium_platform import photo_quality as pq  # noqa: E402

JARVIS = {"power": 22.0, "speed": 180.0, "frequency": 60.0, "pulse_width": 250.0, "line_interval": 0.012, "passes": 1, "global_passes": 1}


def photographed_jarvis(app_world):
    """An accepted photograph of a Jarvis engraving on the world's laser, lens and titanium, at settings no grey scale has."""
    s = app_world["client"].app.state.store
    w = {"store": s, "laser": app_world["laser"]["id"], "lens": app_world["lens"]["id"], "titanium": app_world["titanium"]["id"]}
    return accepted(w, [layer("C20 Photo jarvis", "jarvis", LINEAR, power=JARVIS["power"], speed=JARVIS["speed"],
                              interval=JARVIS["line_interval"], pulse=JARVIS["pulse_width"], dot_width=0.02, detail=0.9)])


def test_choosing_a_kind_fills_in_its_best_photographed_engraving_and_a_step_darker_is_applied(app_world):
    client = app_world["client"]
    pid = photographed_jarvis(app_world)
    work = create_work(client, name="Яна")
    jarvis = change_work(client, work, kind="jarvis")
    recipe = jarvis["dot_recipe"]
    assert recipe["source"] == "photo" and recipe["settings"] == JARVIS and recipe["lab"] == [30.0, 0.0, 0.0] and recipe["size"] is None
    assert recipe["photo"]["pair_id"] == pid and recipe["photo"]["findings"] == ["good"] and jarvis["dot_width"] == 0.02
    assert jarvis["picture"] is not None and jarvis["picture"]["dots"]["source"] == "photo"
    wider = change_work(client, work, width_mm=80)                      # its colour was measured on a picture: no width changes it
    assert wider["dot_recipe"]["lab"] == recipe["lab"] and not wider["dot_recipe"]["missing"]
    # one step darker: no effect measured yet, the prior of the process (the dots' power up 15 %), applied as the dots' settings
    mode = {"device_id": app_world["laser"]["id"], "lens_id": app_world["lens"]["id"], "material_id": app_world["titanium"]["id"]}
    step = client.post("/api/photo-knowledge/adjust", json={**mode, "settings": {**recipe["settings"], "dither": "jarvis", "dot_width": 0.02},
                                                           "direction": "darker"})
    assert step.status_code == 200, step.text
    darker = pq._round("power", 22 * 1.15)
    assert step.json()["basis"] == "prior" and step.json()["changed"] == [{"setting": "power", "from": 22.0, "to": darker}]
    applied = change_work(client, work, dot_settings=step.json()["settings"])
    assert applied["dot_recipe"]["settings"]["power"] == darker and applied["dot_recipe"]["basis"] == "estimate"
    assert applied["dot_recipe"]["lab"] == recipe["lab"]                # the colour of the dots kept until these settings are photographed
    # the scale's own settings at a power it measured put the dots back on the scale
    scale = {k: applied["scale"][k] for k in ("speed", "frequency", "pulse_width", "line_interval", "passes", "global_passes")}
    on_scale = change_work(client, work, dot_settings={**scale, "power": 10})
    assert on_scale["dot_recipe"] is None and on_scale["dot_power"] == 10
    assert client.post(f"/api/photo-works/{work['id']}/undo").status_code == 200
    assert client.get(f"/api/photo-works/{work['id']}").json()["dot_recipe"]["settings"]["power"] == darker
    # back to grayscale: the best photographed grey scale and the span of its tones in order (its oxide turns back past 29.87 %)
    grey = change_work(client, work, kind="grayscale")
    assert (grey["min_power"], grey["max_power"]) == (2.0, 29.87)
    # a kind never photographed keeps what the work had
    kept = change_work(client, work, kind="atkinson")
    assert kept["dot_recipe"] is None and kept["dot_power"] is not None
    # what the laboratory says on the work: Jarvis at its best, the steps from there with the change each makes, the experiment proposed
    change_work(client, work, kind="jarvis")
    advice = client.get(f"/api/photo-works/{work['id']}/advice")
    assert advice.status_code == 200, advice.text
    said = advice.json()
    assert said["kind"] == "jarvis" and said["at_best"] and said["best"]["source"] == {"pair_id": pid, "layer": "C20 Photo jarvis"}
    assert said["steps"]["darker"]["apply"] == {"dot_settings": {**JARVIS, "power": darker}}
    assert said["steps"]["sharper"]["apply"] == {"dot_width": 0.025} and said["steps"]["softer"]["apply"] == {"dot_width": 0.015}
    assert said["status"] == "measured" and said["proposal"]["kind"] == "around" and said["proposal"]["centre"]["power"] == 22.0
    grey = client.get(f"/api/photo-works/{change_work(client, work, kind='grayscale')['id']}/advice").json()
    assert grey["kind"] == "grayscale" and set(grey["steps"]["darker"]["apply"]) == {"min_power", "max_power"}


def test_a_photo_zone_takes_the_best_dots_of_a_kind_without_a_dot_width(zone_world):
    world = zone_world
    pid = photographed_jarvis(world)
    job = create_job(world)
    colouring(world, job, op="photo_add", regions=of_colour(world, job, RED))
    zone = colouring(world, job, op="photo_set", zone=1, kind="jarvis")["zones"][0]
    assert zone["dot_recipe"] is None or zone["dot_recipe"]["photo"]["pair_id"] != pid      # the engraving corrects the dot width: a zone cannot
    s = world["store"]
    w = {"store": s, "laser": world["laser"]["id"], "lens": world["lens"]["id"], "titanium": world["titanium"]["id"]}
    plain = accepted(w, [layer("C21 Photo jarvis", "jarvis", LINEAR, power=18.0, speed=180.0, interval=0.012, pulse=250.0)])
    colouring(world, job, op="photo_set", zone=1, kind="atkinson")
    zone = colouring(world, job, op="photo_set", zone=1, kind="jarvis")["zones"][0]
    assert zone["dot_recipe"]["source"] == "photo" and zone["dot_recipe"]["photo"]["pair_id"] == plain
    assert zone["dot_recipe"]["settings"]["power"] == 18.0 and zone["problem"] is None
    lighter = colouring(world, job, op="photo_set", zone=1, dot_settings={**zone["dot_recipe"]["settings"], "power": 16})["zones"][0]
    assert lighter["dot_recipe"]["settings"]["power"] == 16 and lighter["dot_recipe"]["basis"] == "estimate"
    said = world["client"].get(f"/api/vector/{job['id']}/photo/1/advice")
    assert said.status_code == 200, said.text
    steps = said.json()["steps"]
    assert all("dot_width" not in (step.get("apply") or {}) for step in steps.values())          # a zone writes no dot width
    assert steps["darker"]["apply"]["dot_settings"]["power"] > 16


def test_a_grayscale_work_past_its_scales_turn_gets_no_step_and_takes_back_the_span_in_order(app_world):
    """The scales of ``app_world`` turn lighter again past 29.87 %: a work engraved to 40 % has its darkest greys lighter than its middle."""
    client = app_world["client"]
    work = create_work(client, name="Past the turn")
    inside = client.get(f"/api/photo-works/{work['id']}/advice").json()
    assert inside["turn"]["past"] is False and inside["turn"]["max_power"] == 29.87
    assert inside["steps"]["darker"]["changed"][0]["to"] <= 29.87                     # a step never goes past the turn
    change_work(client, work, min_power=2, max_power=40)
    past = client.get(f"/api/photo-works/{work['id']}/advice").json()
    assert past["turn"]["past"] and all("refused" in step for step in past["steps"].values())
    taken = change_work(client, work, **past["take"])
    assert taken["max_power"] <= 29.87 and not client.get(f"/api/photo-works/{work['id']}/advice").json()["turn"]["past"]


def test_the_findings_screen_reads_what_is_known_on_every_laser_and_titanium_photographed(world):
    w = world
    accepted(w, [layer("C1", "jarvis", BLOCKED, power=30)])
    accepted(w, [layer("C2", "atkinson", LINEAR, power=15)], material=w["other"])
    known = pk.everywhere(w["store"])
    assert [(k["setup"], k["titanium"]) for k in known] == [("JPT M7 · F-Theta", "Grade 5 sheet · Grade 5"), ("JPT M7 · F-Theta", "Grade 2 sheet · Grade 2")]
    jarvis = {k["kind"]: k for k in known[0]["kinds"]}["jarvis"]
    assert jarvis["status"] == "measured" and jarvis["best"]["settings"]["power"] == 30
    # no variations plate was photographed: the plate proposed says what it changes, but has no picture to be engraved from yet
    assert jarvis["proposal"]["copies"][0] == [] and jarvis["proposal"]["copies"][1] == [{"setting": "power", "from": 30.0, "to": 24.0}]
    assert jarvis["proposal"]["plate"] is None
    assert {k["kind"]: k for k in known[1]["kinds"]}["atkinson"]["best"]["settings"]["power"] == 15
