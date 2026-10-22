"""The engraving of a photo work checks its prediction (0.19.3): the work's file names the work, the photograph of its engraving is linked
to it by that name alone, is measured as a tonal profile and, accepted, counts in its scale; the work shows each grey engraved against
the colour the other engravings of those settings predict. The photographs are drawn from the scale itself (as predicted) or shifted
(as if the titanium came out lighter), so the expected answer is known. An engraving is compared with the others at its own size
(DEC-107): the works are made as wide as the ramps of the scale were, unless a test is about another width."""
import cv2
import numpy as np

import synth
from test_grey_scales import app_world, step_colour  # noqa: F401  (the measured grey-ramp plate, four scales; this module's own copy)
from titanium_platform import color, ingest as ig, lightburn, plans


PICTURE_PX = 720          # the picture's width in the photograph, whatever its width on the titanium: the camera is moved to frame it


def ramp_width(client):
    """The row length the grey ramps of the plate were measured at (the smallest size any scale was measured at)."""
    return min(size["row_mm"] for sc in client.get("/api/grey-scales").json()["scales"] for size in sc["sizes"])


def create(client, name="Портрет", width_mm=None):
    width_mm = ramp_width(client) if width_mm is None else width_mm
    picture = cv2.imencode(".png", (synth.structured_picture(5) * 255).astype(np.uint8))[1].tobytes()
    answer = client.post("/api/photo-works", data={"width_mm": width_mm, "name": name}, files={"picture": ("portrait.png", picture, "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def scale_colours(client, work, lighter=0.0):
    """The colour each grey 0..255 gives at the work's scale, Min and Max (RGB 0..255), ``lighter`` added to L*: the titanium of these
    tests gives at every size the colours its grey ramps measured."""
    params = {k: v for k, v in work["scale"].items() if v is not None} | {"min_power": work["min_power"], "max_power": work["max_power"],
                                                                           "row_mm": ramp_width(client)}
    levels = client.get("/api/grey-scales/scale", params=params).json()["greys"]["levels"]
    lab = np.array([[lv["lab"][0] + lighter, lv["lab"][1], lv["lab"][2]] for lv in sorted(levels, key=lambda lv: lv["level"])], np.float64)
    lut = np.clip(color.lab_to_srgb8(lab), 0, 255)
    return lambda grey: lut[grey]


def engrave(client, work, lighter=0.0):
    """Engrave the work's file and photograph it: a pair made from the file and the photograph alone (no work chosen), checked."""
    store = client.app.state.store
    data = client.get(f"/api/photo-works/{work['id']}/export.lbrn2").content
    photo = synth.engraved_picture(data, scale_colours(client, work, lighter), px_per_mm=PICTURE_PX / work["width_mm"])
    device = store.one("SELECT device_id, lens_id FROM pair ORDER BY id LIMIT 1")
    stand = store.one("SELECT id FROM capture_setup ORDER BY id LIMIT 1")["id"]
    pid = ig.create_pair(store, device_id=device["device_id"], lens_id=device["lens_id"], stand_id=stand, lightburn_name=f"{work['name']}.lbrn2",
                         lightburn_bytes=data, photo_name=f"{work['name']}.png", context={"material_id": work["scale"]["material_id"]},
                         photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    report = ig.check_pair(store, pid)
    return pid, report, data


def accept(client, pid):
    store = client.app.state.store
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)


def test_the_file_of_a_work_names_it_and_its_photograph_is_linked_measured_and_checked_against_the_scale(app_world):
    client = app_world["client"]
    work = create(client)
    pid, report, data = engrave(client, work)
    assert lightburn.parse_bytes(data).identifier == work["identifier"]
    assert report["problems"] == [], report["problems"]
    store = client.app.state.store
    assert store.one("SELECT plan_id FROM pair WHERE id=?", (pid,))["plan_id"] == work["id"]       # found by the name in its file
    (layer,) = [rep for rep in report["layers"] if rep.get("tonal")]
    assert layer["tonal"]["evidence"] == "clear" and layer["tonal"]["power_range"] == [work["min_power"], work["max_power"]]

    (waiting,) = client.get(f"/api/photo-works/{work['id']}/engravings").json()
    assert (waiting["pair_id"], waiting["same_scale"], waiting["check"]) == (pid, True, None) and waiting["status"] != "Accepted"
    before = next(sc for sc in client.get("/api/grey-scales").json()["scales"] if sc["mode"] == work["scale"])
    accept(client, pid)

    (done,) = client.get(f"/api/photo-works/{work['id']}/engravings").json()
    check = done["check"]
    assert done["status"] == "Accepted" and check["reason"] is None and check["others"] == 1 and check["referenced"]
    assert check["compared"] >= 12 and check["confirmed"] and check["median_de"] <= 3, check            # engraved as predicted
    band = check["bands"][0]
    assert set(band) >= {"gray", "power", "lab", "predicted", "de", "hex", "predicted_hex"} and band["hex"].startswith("#")
    shown = client.get(f"/api/pairs/{pid}/report")                                                      # its analysis page opens
    assert shown.status_code == 200 and shown.json()["mode"] == plans.MODE_PHOTO_WORK, shown.text[:300]
    after = next(sc for sc in client.get("/api/grey-scales").json()["scales"] if sc["mode"] == work["scale"])
    assert after["engravings"] == before["engravings"] + 1                                               # it counts in its scale
    assert after["confirmation"]["engravings"] == before["confirmation"]["engravings"] + 1

    lighter = client.post(f"/api/photo-works/{work['id']}/copy", json={"name": "Портрет светлее"}).json()
    lighter = client.get(f"/api/photo-works/{lighter['id']}").json()
    pid2, report2, _ = engrave(client, lighter, lighter=12.0)
    assert report2["problems"] == [] and store.one("SELECT plan_id FROM pair WHERE id=?", (pid2,))["plan_id"] == lighter["id"]
    accept(client, pid2)
    (off,) = client.get(f"/api/photo-works/{lighter['id']}/engravings").json()
    assert not off["check"]["confirmed"] and off["check"]["median_de"] > 6, off["check"]                # the titanium came out lighter
    assert all(b["lab"][0] > b["predicted"][0] for b in off["check"]["bands"])
    assert len(client.get(f"/api/photo-works/{work['id']}/engravings").json()) == 1                     # each work has its own photographs


def test_an_engraving_wider_than_the_scale_was_measured_is_not_checked_against_another_size_until_one_was_engraved_at_its_own(app_world):
    client = app_world["client"]
    ramp = ramp_width(client)
    work = create(client, name="Шире", width_mm=round(ramp * 2.5, 1))
    shown = client.get(f"/api/photo-works/{work['id']}").json()["picture"]
    assert shown["scale_size"]["how"] == "outside" and shown["scale_size"]["measured_mm"] == [ramp]       # predicted from the ramps, and said
    assert any("were not measured at this mode" in note for note in shown["notes"]), shown["notes"]
    pid, _, _ = engrave(client, work)
    accept(client, pid)
    (done,) = client.get(f"/api/photo-works/{work['id']}/engravings").json()
    check = done["check"]
    assert done["row_mm"] == work["width_mm"] and check["row_mm"] == work["width_mm"]
    assert (check["reason"], check["compared"], check["confirmed"]) == ("other_size", 0, False), check     # not a failed confirmation
    assert check["size"]["how"] == "outside" and check["size"]["measured_mm"] == [ramp]
    assert client.get(f"/api/photo-works/{work['id']}").json()["picture"]["scale_size"]["how"] == "measured"   # its own size now

    again = client.post(f"/api/photo-works/{work['id']}/copy", json={"name": "Шире ещё раз"}).json()
    again = client.get(f"/api/photo-works/{again['id']}").json()
    pid2, _, _ = engrave(client, again)
    accept(client, pid2)
    (second,) = client.get(f"/api/photo-works/{again['id']}/engravings").json()
    assert second["check"]["reason"] is None and second["check"]["others"] == 1                         # the first at its width, ...
    assert second["check"]["size"]["how"] == "measured" and second["check"]["confirmed"], second["check"]  # ... not the ramps


def test_a_ramp_as_wide_as_the_work_is_ordered_from_it_and_once_measured_the_work_is_predicted_at_its_own_width(app_world):
    client, store = app_world["client"], app_world["client"].app.state.store
    work = create(client, name="Проба ширины", width_mm=round(ramp_width(client) * 2, 1))
    before = client.get(f"/api/photo-works/{work['id']}").json()["picture"]["scale_size"]
    assert before["how"] in ("outside", "between"), before                  # not measured at its width (between: another test's width)
    made = client.post(f"/api/photo-works/{work['id']}/width-ramp")
    assert made.status_code == 201, made.text
    plan = plans.get_plan(store, made.json()["plan_id"])
    (tile,) = [layer for layer in plan["layers"] if layer.get("ramp")]
    mode = work["scale"]
    assert tile["ramp"]["width"] == work["width_mm"]                                             # one ramp, the work's width ...
    assert {k: tile["parameters"][k] for k in ("speed", "frequency", "pulse_width", "line_interval", "min_power", "power")} == {
        "speed": mode["speed"], "frequency": mode["frequency"], "pulse_width": mode["pulse_width"], "line_interval": mode["line_interval"],
        "min_power": work["min_power"], "power": work["max_power"]}                                 # ... at its scale, Min and Max
    photo = synth.plate_photo(plan, {}, size=(1300, 2800), step_rgb=lambda name, grey: step_colour(grey))
    pid = ig.create_pair(store, device_id=app_world["laser"]["id"], lens_id=app_world["lens"]["id"],
                         stand_id=store.one("SELECT id FROM capture_setup ORDER BY id LIMIT 1")["id"], lightburn_name="ramp.lbrn2",
                         lightburn_bytes=plans.export_lbrn2(plan), photo_name="ramp.png", context={"material_id": mode["material_id"]},
                         photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    assert ig.check_pair(store, pid)["problems"] == []
    accept(client, pid)
    size = client.get(f"/api/photo-works/{work['id']}").json()["picture"]["scale_size"]
    assert (size["how"], size["from_mm"]) == ("measured", [work["width_mm"]]), size              # its own width is measured now

    store.execute("UPDATE plan SET lens_id=NULL WHERE id=?", (work["id"],))                       # a work of a lens not on the laser now
    refused = client.post(f"/api/photo-works/{work['id']}/width-ramp")
    assert refused.status_code == 422 and "another lens" in refused.text


def test_a_work_without_photographs_has_no_engravings_and_its_file_still_opens_in_lightburn_terms(app_world):
    client = app_world["client"]
    work = create(client, name="Без фото")
    assert client.get(f"/api/photo-works/{work['id']}/engravings").json() == []
    project = lightburn.parse_bytes(client.get(f"/api/photo-works/{work['id']}/export.lbrn2").content)
    assert project.identifier == work["identifier"] and plans.MODE_PHOTO_WORK


def wavy(grey):
    """Colours that do not darken step by step, as a real titanium scale (gold, violet, blue ...): lightness rises and falls along the
    greys, so the order of lightness says nothing about which edge of the picture is up."""
    t = np.asarray(grey, np.float64) / 255.0
    return np.stack([58 + 20 * np.sin(3 * np.pi * t), 14 * np.cos(2 * np.pi * t), 18 * np.sin(2 * np.pi * t + 1)], axis=-1)


def test_a_picture_matched_on_the_photograph_is_read_as_matched_even_when_its_colours_do_not_darken_step_by_step(app_world):
    client = app_world["client"]
    work = create(client, name="Волны")
    store = client.app.state.store
    data = client.get(f"/api/photo-works/{work['id']}/export.lbrn2").content
    photo = synth.engraved_picture(data, lambda grey: np.clip(color.lab_to_srgb8(wavy(grey).reshape(-1, 3)).reshape(*np.shape(grey), 3), 0, 255),
                                   px_per_mm=PICTURE_PX / work["width_mm"])
    device = store.one("SELECT device_id, lens_id FROM pair ORDER BY id LIMIT 1")
    pid = ig.create_pair(store, device_id=device["device_id"], lens_id=device["lens_id"], stand_id=None, lightburn_name="Волны.lbrn2",
                         lightburn_bytes=data, photo_name="waves.png", context={"material_id": work["scale"]["material_id"]},
                         photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    report = ig.check_pair(store, pid)
    (t,) = [rep["tonal"] for rep in report["layers"] if rep.get("tonal")]
    expected = wavy(np.array([b["gray"] for b in t["bins"]]) * 255)
    measured = np.array([[b["L"], b["a"], b["b"]] for b in t["bins"]])
    de = np.linalg.norm(measured - expected, axis=1)
    assert report["alignment"]["method"] == "picture" and abs(t["rho"]) < 0.5                    # lightness does not follow the grey
    assert t["vertical_flip"] is False and t["evidence"] == "clear"
    assert np.median(de) < 2.5 and de.max() < 7, np.round(de, 1)                                  # each grey measured where it was engraved
