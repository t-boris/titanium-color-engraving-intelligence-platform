"""What the operator reviews before export (REQ-012, REQ-004): the banding picture, a revised photo plan, questioned entries."""
import base64
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import obs
from test_continuous import LIGHTNESS, gradient_png
from test_discrete import BLUE_LAB, RED_LAB, png, rgb_of
from titanium_platform import color, conversion as cv, knowledge as kn, plans as pl, setup as su
from titanium_platform.api.app import create_app


@pytest.fixture
def api(tmp_path):
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *w["setup"], criteria_agreed=True)
    for power, lightness in LIGHTNESS.items():
        for dl in (-1.0, 1.0):
            obs.add(store, w, (lightness + dl, 0.0, 0.0), power=power)
    kn.refresh(store, *w["setup"])
    w["ids"] = {k["parameters"]["power"]: k["id"] for k in kn.list_for_setup(store, *w["setup"])}
    with TestClient(app) as client:
        yield {"client": client, "store": store, "w": w}
    store.close()


def form(w, **extra):
    return {"device_id": w["setup"][0], "lens_id": w["setup"][1], "mode": "tonal", "width_mm": 40, **extra}


def decode(data: bytes) -> np.ndarray:
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def picture_of(preview: dict) -> np.ndarray:
    head, data = preview["banding_png"].split(",", 1)
    assert head == "data:image/png;base64"
    return decode(base64.b64decode(data))


def colours(img: np.ndarray) -> set:
    return {tuple(int(v) for v in px) for px in img.reshape(-1, 3)}


def test_the_preview_paints_every_band_in_its_predicted_colour_and_changes_with_n(api):
    c, w = api["client"], api["w"]
    previews = {}
    for n in (2, 4):
        r = c.post("/api/continuous/preview", data=form(w, bands=n), files={"image": ("g.png", gradient_png(), "image/png")})
        assert r.status_code == 200, r.text
        previews[n] = r.json()
        img = picture_of(previews[n])
        expected = {tuple(int(v) for v in color.lab_to_srgb8(l["prediction"]["lab"])) for l in previews[n]["layers"] if l["pixels"]}
        assert colours(img) == expected and max(img.shape[:2]) >= 400                 # enlarged without smoothing: only band colours
        left, right = img[:, 0], img[:, -1]
        assert (left == left[0]).all() and tuple(left[0]) == tuple(color.lab_to_srgb8(previews[n]["layers"][0]["prediction"]["lab"]))
        assert tuple(right[0]) == tuple(color.lab_to_srgb8(previews[n]["layers"][-1]["prediction"]["lab"]))    # dark left, light right
    assert len(colours(picture_of(previews[2]))) == 2 and len(colours(picture_of(previews[4]))) == 4


def test_a_created_plan_shows_the_same_banding_and_keeps_its_source_image(api):
    c, w = api["client"], api["w"]
    preview = c.post("/api/continuous/preview", data=form(w, bands=4), files={"image": ("g.png", gradient_png(), "image/png")}).json()
    plan = c.post("/api/continuous", data=form(w, bands=4, name="Portrait"), files={"image": ("g.png", gradient_png(), "image/png")}).json()
    picture = c.get(f"/api/plans/{plan['id']}/banding.png")
    assert picture.headers["content-type"] == "image/png" and (decode(picture.content) == picture_of(preview)).all()
    source = c.get(f"/api/plans/{plan['id']}/source-image")
    assert source.content == gradient_png() and source.headers["content-type"] == "image/png"


def test_the_band_limit_is_lightburns_palette_less_the_marker_layer(api):
    c, w = api["client"], api["w"]
    assert c.get("/api/continuous/limits").json() == {"max_bands": 29}
    r = c.post("/api/continuous/preview", data=form(w, bands=30), files={"image": ("g.png", gradient_png(), "image/png")})
    assert r.status_code == 422 and "29 available" in r.json()["error"]


def test_a_revised_photo_plan_is_a_new_plan_and_the_old_one_stays(api):
    c, w = api["client"], api["w"]
    first = c.post("/api/continuous", data=form(w, bands=4, name="A"), files={"image": ("g.png", gradient_png(), "image/png")}).json()
    path = [w["ids"][40], w["ids"][10]]
    second = c.post("/api/continuous", data=form(w, bands=8, name="A (2)", mode="color_path", path_ids=json.dumps(path), revision_of=first["id"]),
                    files={"image": ("g.png", c.get(f"/api/plans/{first['id']}/source-image").content, "image/png")}).json()
    assert second["id"] != first["id"] and second["revision_of"] == first["id"] and second["band_count"] == 8 and second["path_ids"] == path
    again = c.get(f"/api/plans/{first['id']}").json()
    assert (again["band_count"], again["continuous_mode"], again["status"]) == (4, "tonal", "Ready to export")
    pl.save_marker_layer_settings(api["store"], 20, 60, 300)
    plate = pl.create_plate_series(api["store"], w["setup"][0], "10", "40", "900", 5, 4, 1, pulse_width=200, line_interval=0.025, passes=1)[0]
    r = c.post("/api/continuous", data=form(w, bands=4, name="B", revision_of=plate["plan_id"]), files={"image": ("g.png", gradient_png(), "image/png")})
    assert r.status_code == 422 and "only a photo engraving plan" in r.json()["error"]


def test_the_tonal_warning_lists_every_questioned_entry_with_its_reason_and_observations(api):
    store, w = api["store"], api["w"]
    for power in (20, 30):
        kn.approve_for_production(store, w["ids"][power], True)
        obs.add(store, w, (95, 0, 0), power=power)
    kn.refresh(store, *w["setup"])
    p = cv.preview_continuous(store, *w["setup"], "tonal", gradient_png(), 40, 8)
    warning = p["warnings"][0]
    assert warning["knowledge_ids"] == sorted([w["ids"][20], w["ids"][30]])
    assert [e["knowledge_id"] for e in warning["entries"]] == warning["knowledge_ids"]
    assert all(e["reason"] and "exceeds" in e["reason"] and e["observation_ids"] and len(e["lab"]) == 3 for e in warning["entries"])


def test_a_discrete_plan_shows_matched_colours_and_hatches_the_unreachable_ones(store):
    w = obs.setup(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *w["setup"], criteria_agreed=True)
    for power, base in ((10, RED_LAB), (30, BLUE_LAB)):
        for dl in (-1.0, 1.0):
            obs.add(store, w, (base[0] + dl, base[1], base[2]), power=power)
    kn.refresh(store, *w["setup"])
    pid = cv.start_discrete(store, *w["setup"], png([rgb_of(RED_LAB), rgb_of((90.0, -60.0, 70.0))]), 40, "A", threshold=8.0)
    img = cv.plan_banding(store, pl.get_plan(store, pid))
    red = next(e for e in cv.eligible_palette(store, *w["setup"]) if e["parameters"]["power"] == 10)
    found = colours(img)
    assert tuple(int(v) for v in color.lab_to_srgb8(red["lab"])) in found and (211, 47, 47) in found      # matched colour; red stripes
    pl.save_marker_layer_settings(store, 20, 60, 300)
    plate = pl.create_plate_series(store, w["setup"][0], "10", "40", "900", 5, 4, 1, pulse_width=200, line_interval=0.025, passes=1)[0]
    with pytest.raises(cv.ConversionError, match="no banding picture"):
        cv.plan_banding(store, pl.get_plan(store, plate["plan_id"]))
