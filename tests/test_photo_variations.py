"""Photo variations (feature photo-engraving-quality): one picture engraved several times, each copy at its own settings with a grey ramp
at the same settings under it; the picture stored once beside the plan; every copy and every ramp measured from one photograph."""
import base64
import json

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import (capability_plates as cp, capability_results, devices, ingest as ig, lenses, lightburn, photo_knowledge,
                               plans, setup as su)

BASE = {"power": 25, "speed": 125, "frequency": 60, "pulse_width": 200, "line_interval": 0.01}
EIGHT = [{"dither": "jarvis"}, {"dither": "atkinson"}, {"dither": "stucki"}, {"power": 20}, {"power": 30},
         {"line_interval": 0.0169}, {"dot_width": 0.01}, {"speed": 175}]


@pytest.fixture
def world(store):
    store.set_setting("allow_non_raw_photos", True)              # tests use PNG renders; real use requires RAW
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="PV-01")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    stand = su.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    titanium = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)
    return {"store": store, "laser": laser, "lens": lens, "stand": stand, "titanium": titanium}


def portrait(rows=300, cols=240, transparent=False) -> bytes:
    yy, xx = np.mgrid[0:rows, 0:cols]
    grey = (127 + 120 * np.sin(xx / 9.0) * np.cos(yy / 13.0)).astype(np.uint8)
    if not transparent:
        return cv2.imencode(".png", grey)[1].tobytes()
    alpha = np.zeros_like(grey)
    alpha[20:rows - 20, 30:cols - 30] = 255                      # a transparent border: the copy is trimmed to the opaque part
    return cv2.imencode(".png", np.dstack([grey, grey, grey, alpha]))[1].tobytes()


def make(world, variants=EIGHT, picture=None, **extra):
    supplied = {"picture_png": base64.b64encode(picture or portrait()).decode(), "variants": variants, "copy_mm": 16, "picture_name": "Yana",
                **extra}
    return cp.create(world["store"], world["laser"]["id"], world["titanium"]["id"], "photo_variations", {**BASE, "variations": supplied})


def test_each_copy_is_a_picture_layer_and_a_ramp_layer_at_the_same_settings_with_the_picture_stored_once(world):
    s = world["store"]
    made = make(world)
    plan = plans.get_plan(s, made["plan_id"])
    names = [layer["name"] for layer in plan["layers"]]
    assert names == [f"PV{n}-{part}" for n in range(1, 9) for part in ("PICTURE", "RAMP")]
    for picture, ramp in zip(plan["layers"][::2], plan["layers"][1::2]):
        assert picture["parameters"] == ramp["parameters"] and picture["picture"]["dither"] == ramp["ramp"]["dither"]
        assert picture["parameters"]["min_power"] == picture["parameters"]["power"]                # every dot at the layer's power
        assert ramp["ramp"]["width"] == picture["picture"]["width"]                                 # the same length of scan line
        assert "pixels" not in picture["picture"] and picture["picture"]["picture_key"] == "variation"
    by_copy = {layer["variation"]["copy"]: layer for layer in plan["layers"] if layer["variation"]["part"] == "picture"}
    assert [by_copy[n]["picture"]["dither"] for n in (1, 2, 3)] == ["jarvis", "atkinson", "stucki"]
    assert by_copy[4]["parameters"]["power"] == 20 and by_copy[6]["parameters"]["line_interval"] == 0.0169
    assert by_copy[7]["parameters"]["dot_width"] == 0.01 and "dot_width" not in by_copy[1]["parameters"]
    stored = cv2.imread(plan["pictures"]["variation"], cv2.IMREAD_UNCHANGED)
    assert stored.ndim == 2 and max(stored.shape) <= 16 * cp.VARIATION_PICTURE_PX_MM               # stored no finer than the file needs
    plate = json.loads(s.one("SELECT geometry_json FROM plate WHERE id=?", (made["plate_id"],))[0])
    assert "pictures" not in plate and "picture_png" not in json.dumps(plan["experiment"]["test_settings"])
    labels = [c["label"] for c in plate["variations"]["copies"]]
    assert labels == ["1 J P25 V125 F60 PW200 I.01", "2 A", "3 S", "4 J P20", "5 J P30", "6 J I.0169", "7 J D.01", "8 J V175"]
    assert plate["variations"]["picture"]["name"] == "Yana" and plate["variations"]["picture"]["size_px"] == [stored.shape[1], stored.shape[0]]


def test_the_file_engraves_each_copy_in_its_kind_with_its_dot_width_and_the_same_picture(world):
    plan = plans.get_plan(world["store"], make(world)["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    images = [layer for layer in project.layers if layer.layer_type == "Image"]
    assert len(images) == 16
    kinds = [layer.image_summary()["dither"] for layer in images[::2]]
    assert kinds == ["jarvis", "atkinson", "stucki", "jarvis", "jarvis", "jarvis", "jarvis", "jarvis"]
    dot = {layer.name: layer.source_settings.get("dotWidth", {}).get("Value") for layer in images}
    assert dot["PV7-PICTURE"] == dot["PV7-RAMP"] == "0.01" and dot["PV1-PICTURE"] is None
    pictures = {region.bitmap["png"] for layer in images[::2] for region in layer.regions}
    assert len(pictures) == 1                                                                    # every copy engraves the same picture


def test_a_transparent_border_is_trimmed_and_the_copy_keeps_the_pictures_proportions(world):
    plan = plans.get_plan(world["store"], make(world, EIGHT[:2], picture=portrait(transparent=True))["plan_id"])
    box = plan["layers"][0]["picture"]
    assert box["height"] == 16 and box["width"] == pytest.approx(16 * 180 / 260, abs=0.01)    # 180 x 260 opaque pixels, the longer side 16 mm
    assert cv2.imread(plan["pictures"]["variation"], cv2.IMREAD_UNCHANGED).ndim == 2           # trimmed to its opaque part: nothing left to hide


def test_the_window_of_a_copy_holds_the_most_tones_of_the_picture_at_its_own_scale():
    """A dark lens with a sharp rim has the widest spread; the copies are cut where the most greys are, the skin's mid-tones included."""
    picture = np.full((400, 800), 40, np.uint8)
    picture[:, :400] = np.where(np.indices((400, 400)).sum(axis=0) % 40 < 20, 10, 120)      # dark, sharp, two tones only
    picture[:, 400:] = np.tile(np.linspace(0, 255, 400), (400, 1)).astype(np.uint8)          # every grey
    window = cp.variation_window(picture, px_per_mm=20, size_mm=10)                         # 200 x 200 pixels, as large as engraved
    assert window.shape == (200, 200) and len(np.unique(window // 16)) >= 8                  # half the gradient: 8 of its 16 steps
    transparent = np.dstack([picture] * 3 + [np.where(np.arange(800) < 600, 255, 0)[None, :].repeat(400, axis=0).astype(np.uint8)])
    assert (cp.variation_window(transparent, 20, 10)[..., 3] == 255).mean() >= cp.VARIATION_WINDOW_OPAQUE   # mostly where it engraves


@pytest.mark.parametrize("variants, extra, message", [
    (EIGHT[:1], {}, "от 2 до 12 копий"),
    (EIGHT + EIGHT[:5], {}, "от 2 до 12 копий"),
    ([{"dither": "jarvis"}, {"dither": "jarvis"}], {}, "одинаковыми настройками"),
    ([{"dither": "jarvis"}, {"gamma": 2}], {}, "неизвестные параметры: gamma"),
    ([{"dither": "jarvis"}, {"dither": "sketch"}], {}, "градации серого или один из видов точками"),
    ([{"dither": "jarvis"}, {"dot_width": 0.5}], {}, "поправка ширины точки"),
    ([{"dither": "grayscale", "min_power": 30}, {"dither": "jarvis"}], {}, "Min мощность"),
    ([{"dither": "jarvis"}, {"frequency": 5000}], {}, "копия 2: частота"),
    (EIGHT[:2], {"copy_mm": 60}, "размер копии"),
])
def test_copies_that_compare_nothing_or_that_the_laser_cannot_engrave_are_refused(world, variants, extra, message):
    with pytest.raises(su.ValidationError, match=message):
        make(world, variants, **extra)


def test_without_copies_the_plate_changes_one_setting_at_a_time_around_its_own_settings(world):
    s = world["store"]
    supplied = {"picture_png": base64.b64encode(portrait()).decode(), "dither": "grayscale", "min_power": 2, "copy_mm": 20}
    made = cp.create(s, world["laser"]["id"], world["titanium"]["id"], "photo_variations", {**BASE, "power": 30, "variations": supplied})
    plate = json.loads(s.one("SELECT geometry_json FROM plate WHERE id=?", (made["plate_id"],))[0])
    copies = [c["variant"] for c in plate["variations"]["copies"]]
    assert (copies[0]["dither"], copies[0]["min_power"], copies[0]["power"]) == ("grayscale", 2, 30)
    assert [c["label"].split(" ", 1)[1] for c in plate["variations"]["copies"][1:]] == ["G P2-24", "G P2-36", "G P5-30", "G I.015", "G I.0075", "G V88", "G V175"]


def test_a_picture_that_is_not_an_image_is_refused(world):
    with pytest.raises(su.ValidationError, match="картинка копий не прочитана"):
        make(world, EIGHT[:2], picture=b"not a picture")


def test_a_photographed_plate_measures_every_ramp_step_by_step_and_every_copy_against_its_picture(world):
    s = world["store"]
    plan = plans.get_plan(s, make(world)["plan_id"])
    picture = cv2.imread(plan["pictures"]["variation"], cv2.IMREAD_UNCHANGED).astype(np.float32) / 255.0
    darkness = {f"PV{n}": 0.3 + 0.08 * n for n in range(1, 9)}                                     # each copy darkens its greys its own way
    shade = lambda name, grey: (int(235 - 180 * darkness[name.split("-")[0]] * (1 - grey)),) * 3   # noqa: E731
    scale, origin = 20.0, (520, 80)
    photo = synth.plate_photo(plan, {}, scale=scale, origin=origin, size=(1500, 2500), step_rgb=shade)
    ext = plan["markers"]["extent"]
    for layer in plan["layers"]:
        if layer["variation"]["part"] != "picture":
            continue
        box = layer["picture"]
        x0, y0 = round((box["x"] - ext["min_x"]) * scale + origin[0]), round((box["y"] - ext["min_y"]) * scale + origin[1])
        w, h = round(box["width"] * scale), round(box["height"] * scale)
        grey = cv2.resize(picture, (w, h), interpolation=cv2.INTER_AREA)
        value = np.array([shade(layer["name"], g) for g in np.linspace(0, 1, 256)], np.uint8)[np.round(grey * 255).astype(int)]
        photo[y0:y0 + h, x0:x0 + w] = value
    pid = ig.create_pair(s, device_id=world["laser"]["id"], lens_id=world["lens"]["id"], stand_id=world["stand"]["id"],
                         lightburn_name="variations.lbrn2", lightburn_bytes=plans.export_lbrn2(plan), photo_name="variations.png",
                         context={"material_id": world["titanium"]["id"]}, photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    report = ig.check_pair(s, pid)
    assert report["problems"] == [], report["problems"]
    by_name = {rep["name"]: rep for rep in report["layers"]}
    for n in range(1, 9):
        ramp, copy = by_name[f"PV{n}-RAMP"]["tonal"], by_name[f"PV{n}-PICTURE"]["tonal"]
        assert ramp["measured_by"] == "grey ramp" and ramp["steps_missed"] == 0
        assert copy["evidence"] == "clear" and copy["rho"] > 0.9 and len(copy["bins"]) >= 12
        greys, lightness = [b["gray"] for b in ramp["bins"]], [b["L"] for b in ramp["bins"]]
        for b in copy["bins"]:                     # the copy and its ramp agree where the picture's blur leaves its greys as they are
            if 0.25 <= b["gray"] <= 0.75:
                assert b["L"] == pytest.approx(np.interp(b["gray"], greys, lightness), abs=4), (n, b)
    darkest = [min(by_name[f"PV{n}-RAMP"]["tonal"]["bins"], key=lambda b: b["gray"])["L"] for n in range(1, 9)]
    assert darkest == sorted(darkest, reverse=True)                                                # copy by copy as they were drawn
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)                                       # the plate's results page and its findings take the plate as any other
    report = capability_results.report_for_pair(s, pid)
    assert report is not None and report["test_type"] == "photo_variations"
    pair = ig.get_pair(s, pid)                                   # the copies judged as pictures on every read (DEC-001, DEC-003)
    found = pair["variations"]
    assert len(found["ranked"]) == 8 and found["best"] != 1 and found["best_label"].startswith(f"{found['best']} ")
    assert all(effect["mean_L"] < 0 for effect in found["effects"])          # every copy was drawn darker than the first
    best = next(c for c in found["ranked"] if c["copy"] == found["best"])
    assert best["score"] > next(c for c in found["ranked"] if c["copy"] == 1)["score"]
    assert found["next"]["step"] == 0.5 and found["next"]["centre"]["power"] in (20, 25, 30)
    quality = {rep["name"]: rep["photo_quality"] for rep in pair["check"]["layers"] if rep.get("photo_quality")}
    for n in range(1, 9):
        assert quality[f"PV{n}-RAMP"]["detail"] is None and quality[f"PV{n}-RAMP"]["findings"]
        assert quality[f"PV{n}-PICTURE"]["detail"]["kept"] == pytest.approx(1.0, abs=0.2), n      # the picture pasted as it is
    # the laboratory knows the best Jarvis now and proposes the next plate around it: the same picture, the changes halved (DEC-003)
    known = photo_knowledge.knowledge(s, world["laser"]["id"], world["lens"]["id"], world["titanium"]["id"])
    jarvis = next(k for k in known["kinds"] if k["kind"] == "jarvis")
    proposal = jarvis["proposal"]
    assert jarvis["status"] == "searching" and {k: proposal[k] for k in ("kind", "pair_id", "centre", "step", "best_label")} == {
        "kind": "next", "pair_id": pid, "centre": found["next"]["centre"], "step": 0.5, "best_label": found["best_label"]}
    assert jarvis["best"]["photographs"] == [pid]
    following = photo_knowledge.next_plate(s, pid)
    made = json.loads(s.one("SELECT geometry_json FROM plate WHERE id=?", (following["plate_id"],))["geometry_json"])
    geometry = made["variations"]
    # the proposal said what the plate finds out and how big it is: the change of each copy and the plate's size, as it was made
    assert len(proposal["copies"]) == len(geometry["copies"]) and proposal["copies"][0] == []
    assert all(len(c) == 1 and c[0]["to"] == geometry["copies"][n]["variant"][c[0]["setting"]] for n, c in enumerate(proposal["copies"][1:], 1)
               if c[0]["setting"] not in ("dither", "dot_width"))
    assert proposal["plate"]["size_mm"] == [round(made["width"], 1), round(made["height"], 1)]
    assert proposal["plate"]["copy_mm"] == [geometry["width_mm"], geometry["height_mm"]]
    assert geometry["step"] == 0.5 and geometry["copies"][0]["variant"] == {**found["next"]["centre"], **{
        k: v for k, v in geometry["copies"][0]["variant"].items() if k not in found["next"]["centre"]}}
    assert geometry["picture"]["sha256"] == json.loads(s.one("SELECT geometry_json FROM plate WHERE id=?", (plan["plate_id"],))[0])[
        "variations"]["picture"]["sha256"]
    assert geometry["follows"] == {"kind": "next", "pair_id": pid, "best_copy": found["best"]}


# -- from a photo work and a photo zone ---------------------------------------------------------------------------------------------
from test_grey_scales import app_world  # noqa: E402,F401  (a laser, lens and titanium with four measured grey scales)
from test_photo_work_kinds import create as create_work, settings  # noqa: E402
from test_vector_photo_zones import RED, colouring, create as create_job, of_colour, world as zone_world  # noqa: E402,F401
from titanium_platform import photo_quality as pq  # noqa: E402


def test_a_photo_work_orders_its_picture_at_its_own_settings_and_at_one_change_each(app_world):
    client, store = app_world["client"], app_world["client"].app.state.store
    work = create_work(client, name="Яна")
    dotted = settings(client, work, kind="jarvis", dot_width=0.02)
    answer = client.post(f"/api/photo-works/{work['id']}/variations")
    assert answer.status_code == 201, answer.text
    plan = plans.get_plan(store, answer.json()["plan_id"])
    copies = json.loads(store.one("SELECT geometry_json FROM plate WHERE id=?", (answer.json()["plate_id"],))[0])["variations"]
    centre = copies["copies"][0]["variant"]
    assert (centre["dither"], centre["power"], centre["dot_width"]) == ("jarvis", dotted["dot_power"], 0.02)
    assert [c["label"].split(" ", 1)[1] for c in copies["copies"][1:]] == [
        f"J P{pq._round('power', dotted['dot_power'] * 0.8):g}", f"J P{pq._round('power', dotted['dot_power'] * 1.2):g}",
        f"J V{round(centre['speed'] * 1.4)}", f"J I{centre['line_interval'] * 1.69:.4f}".replace("I0.", "I.").rstrip("0"), "J D0", "A", "S"]
    assert copies["picture"]["source"] == {"kind": "photo_work", "plan_id": work["id"]} and copies["picture"]["name"] == "Яна"
    # a window of the work's picture as large as the work engraves it (the work is 60 mm wide): 18 mm across, not the whole picture shrunk
    assert copies["copy_mm"] == pytest.approx(18, abs=0.1)
    file = plans.export_lbrn2(plan)
    images = [layer for layer in lightburn.parse_bytes(file).layers if layer.layer_type == "Image"]
    assert images[0].image_summary()["dot_width_mm"] == 0.02 and images[10].image_summary()["dot_width_mm"] is None


def test_a_grayscale_work_varies_max_min_the_line_interval_and_the_speed(app_world):
    client, store = app_world["client"], app_world["client"].app.state.store
    work = create_work(client)
    answer = client.post(f"/api/photo-works/{work['id']}/variations")
    assert answer.status_code == 201, answer.text
    plan = plans.get_plan(store, answer.json()["plan_id"])
    pictures = [layer for layer in plan["layers"] if layer["variation"]["part"] == "picture"]
    assert {layer["picture"]["dither"] for layer in pictures} == {"grayscale"}
    centre = pictures[0]["parameters"]
    assert (centre["min_power"], centre["power"]) == (work["min_power"], work["max_power"])
    changed = [{k for k in ("power", "min_power", "speed", "line_interval") if layer["parameters"][k] != centre[k]} for layer in pictures[1:]]
    assert changed == [{"power"}, {"power"}, {"min_power"}, {"line_interval"}, {"line_interval"}, {"speed"}, {"speed"}]


def test_a_photo_zone_orders_its_picture_as_the_works_file_engraves_it(zone_world):
    world = zone_world
    job = create_job(world)
    colouring(world, job, op="photo_add", regions=of_colour(world, job, RED))
    zone = colouring(world, job, op="photo_set", zone=1, kind="atkinson")["zones"][0]
    answer = world["client"].post(f"/api/vector/{job['id']}/photo/1/variations")
    assert answer.status_code == 201, answer.text
    store = world["store"]
    plan = plans.get_plan(store, answer.json()["plan_id"])
    copies = json.loads(store.one("SELECT geometry_json FROM plate WHERE id=?", (answer.json()["plate_id"],))[0])["variations"]
    assert copies["picture"]["source"] == {"kind": "photo_zone", "plan_id": job["id"], "zone": 1}
    assert copies["copies"][0]["variant"]["dither"] == "atkinson" and copies["copies"][0]["variant"]["power"] == zone["dot_power"]
    assert [c["variant"]["dither"] for c in copies["copies"]][-2:] == ["jarvis", "stucki"]
    assert world["client"].post(f"/api/vector/{job['id']}/photo/9/variations").status_code == 404


def test_the_next_plate_changes_each_setting_less_when_it_is_closer_to_the_best():
    centre = {"dither": "jarvis", "power": 25, "speed": 125, "line_interval": 0.01}
    first, closer = pq.variants_around(centre), pq.variants_around(centre, 0.5)
    assert first[:3] == [{}, {"power": 20}, {"power": 30}] and closer[:3] == [{}, {"power": 22.5}, {"power": 27.5}]
    assert {"dot_width": 0.01} in first and {"dot_width": None} in pq.variants_around({**centre, "dot_width": 0.02})
    top = pq.variants_around({**centre, "power": 95})
    assert {"power": 100} in top and all(v.get("power", 0) <= 100 for v in top)                     # never above full power
