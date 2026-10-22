"""The engraving of a photo work checks its prediction (0.19.3): the work's file names the work, the photograph of its engraving is linked
to it by that name alone, is measured as a tonal profile and, accepted, counts in its scale; the work shows each grey engraved against
the colour the other engravings of those settings predict. The photographs are drawn from the scale itself (as predicted) or shifted
(as if the titanium came out lighter), so the expected answer is known."""
import cv2
import numpy as np

import synth
from test_grey_scales import app_world  # noqa: F401  (the measured grey-ramp plate, four scales; this module's own copy)
from titanium_platform import color, ingest as ig, lightburn, plans


def create(client, name="Портрет", width_mm=60):
    picture = cv2.imencode(".png", (synth.structured_picture(5) * 255).astype(np.uint8))[1].tobytes()
    answer = client.post("/api/photo-works", data={"width_mm": width_mm, "name": name}, files={"picture": ("portrait.png", picture, "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def scale_colours(client, work, lighter=0.0):
    """The colour each grey 0..255 is predicted to give at the work's scale, Min and Max (RGB 0..255), ``lighter`` added to L*."""
    params = {k: v for k, v in work["scale"].items() if v is not None} | {"min_power": work["min_power"], "max_power": work["max_power"]}
    levels = client.get("/api/grey-scales/scale", params=params).json()["greys"]["levels"]
    lab = np.array([[lv["lab"][0] + lighter, lv["lab"][1], lv["lab"][2]] for lv in sorted(levels, key=lambda lv: lv["level"])], np.float64)
    lut = np.clip(color.lab_to_srgb8(lab), 0, 255)
    return lambda grey: lut[grey]


def engrave(client, work, lighter=0.0):
    """Engrave the work's file and photograph it: a pair made from the file and the photograph alone (no work chosen), checked."""
    store = client.app.state.store
    data = client.get(f"/api/photo-works/{work['id']}/export.lbrn2").content
    photo = synth.engraved_picture(data, scale_colours(client, work, lighter))
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
    photo = synth.engraved_picture(data, lambda grey: np.clip(color.lab_to_srgb8(wavy(grey).reshape(-1, 3)).reshape(*np.shape(grey), 3), 0, 255))
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
