"""Photo engraving works (REQ-061, DEC-104): kept like vector works, each on its measured scale with Min, Max, width and colour choice."""
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from test_grey_scales import HUES, app_world, picture_png  # noqa: F401  (the measured grey-ramp plate, four scales)
from titanium_platform import lightburn, photo_work
from titanium_platform.api.app import create_app


def create(client, **fields):
    data = {"width_mm": 60, **fields}
    answer = client.post("/api/photo-works", data=data, files={"picture": ("girl.png", picture_png(), "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def scale_of(client, speed, line_interval):
    scales = client.get("/api/grey-scales").json()["scales"]
    return next(sc["mode"] for sc in scales if sc["mode"]["speed"] == speed and sc["mode"]["line_interval"] == line_interval)


def test_a_new_work_starts_on_the_best_measured_scale_at_its_measured_min_and_max_and_is_listed(app_world):
    client = app_world["client"]
    best = client.get("/api/grey-scales").json()["scales"][0]
    work = create(client)
    assert work["name"] == "girl" and work["image_name"] == "girl.png" and work["image_size"] == [240, 120]
    assert work["scale"] == best["mode"] and (work["min_power"], work["max_power"]) == (2.0, 40.0) and not work["by_colour"]
    assert (work["width_mm"], work["height_mm"]) == (60, 30) and work["time"]["seconds"] > 0
    shown = work["picture"]
    assert shown["power_range"] == [2.0, 40.0] and shown["size_mm"] == {"width": 60, "height": 30}
    png = client.get(shown["preview"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.headers["etag"]
    listed = client.get("/api/photo-works").json()
    assert listed[0]["id"] == work["id"] and listed[0]["name"] == "girl" and "picture" not in listed[0]
    thumb = client.get(f"/api/photo-works/{work['id']}/thumb.png")
    assert thumb.status_code == 200 and max(cv2.imdecode(np.frombuffer(thumb.content, np.uint8), cv2.IMREAD_COLOR).shape[:2]) == 240
    assert client.get(f"/api/photo-works/{work['id']}/thumb.png", headers={"If-None-Match": thumb.headers["etag"]}).status_code == 304
    original = client.get(f"/api/photo-works/{work['id']}/picture")
    assert original.content == picture_png() and original.headers["content-type"] == "image/png"
    # a work nobody photographed is the operator's work, not an experiment
    experiments = client.get("/api/experiments").json()
    assert not any((e.get("plan_id") or e.get("id")) in (work["id"], f"plan-{work['id']}") for e in experiments)


def test_another_scale_keeps_the_picture_and_takes_its_measured_span_and_every_change_is_saved(app_world):
    client = app_world["client"]
    work = create(client, name="  Портрет  ")
    assert work["name"] == "Портрет"
    other = scale_of(client, 250, 0.0254)
    moved = client.post(f"/api/photo-works/{work['id']}/settings", json={"scale": other}).json()
    assert moved["scale"] == other and moved["image_size"] == [240, 120] and moved["picture"]["power_range"] == [moved["min_power"], moved["max_power"]]
    assert moved["picture"]["preview"] != work["picture"]["preview"]
    changed = client.post(f"/api/photo-works/{work['id']}/settings", json={"min_power": 10, "max_power": 30, "width_mm": 100, "by_colour": True}).json()
    assert (changed["min_power"], changed["max_power"], changed["width_mm"], changed["height_mm"], changed["by_colour"]) == (10, 30, 100, 50, True)
    assert changed["picture"]["colour_match"]["greys_available"] > 0
    again = client.get(f"/api/photo-works/{work['id']}").json()
    assert (again["scale"], again["min_power"], again["max_power"], again["width_mm"], again["by_colour"]) == (other, 10, 30, 100, True)
    assert again["updated_at"] >= work["updated_at"]
    only_max = client.post(f"/api/photo-works/{work['id']}/settings", json={"max_power": 25}).json()
    assert (only_max["min_power"], only_max["max_power"]) == (10, 25)


@pytest.mark.parametrize("body, message", [
    ({}, "change the scale, Min and Max power, the width or the colour choice of the work"),
    ({"name": "x"}, "change the scale, Min and Max power, the width or the colour choice of the work"),
    ({"scale": {"speed": 999}}, "this scale is not measured: choose one of the measured scales"),
    ({"width_mm": 0}, "the width of the picture must be 1..1000 mm"),
    ({"width_mm": True}, "the width of the picture must be 1..1000 mm"),
    ({"by_colour": "yes"}, "the colour choice must be on or off"),
    ({"min_power": 50, "max_power": 20}, "Min power 50 % and Max power 20 % must lie within 0..100 % with Min not above Max"),
])
def test_a_change_that_cannot_be_made_is_refused_with_the_reason_and_the_work_stays_as_it_was(app_world, body, message):
    client = app_world["client"]
    work = create(client)
    refused = client.post(f"/api/photo-works/{work['id']}/settings", json=body)
    assert refused.status_code == 422 and refused.json()["error"] == message
    kept = client.get(f"/api/photo-works/{work['id']}").json()
    assert {k: kept[k] for k in ("scale", "min_power", "max_power", "width_mm", "by_colour")} == \
        {k: work[k] for k in ("scale", "min_power", "max_power", "width_mm", "by_colour")}


def test_the_file_is_one_grayscale_image_layer_with_the_works_settings_named_after_the_work(app_world):
    client = app_world["client"]
    work = create(client, name="Мотоцикл")
    client.post(f"/api/photo-works/{work['id']}/settings", json={"min_power": 10, "max_power": 30})
    file = client.get(work["picture"]["file"])
    assert file.status_code == 200 and "filename*=UTF-8''%D0%9C%D0%BE%D1%82%D0%BE%D1%86%D0%B8%D0%BA%D0%BB-P10-30.lbrn2" in file.headers["content-disposition"]
    layer = lightburn.parse_bytes(file.content).layer(0)
    mode = work["scale"]
    assert (layer.layer_type, layer.power, layer.image_summary()["min_power"]) == ("Image", 30, 10)
    assert (layer.speed, layer.line_interval, layer.frequency_khz) == (mode["speed"], mode["line_interval"], mode["frequency"])
    stored = cv2.imdecode(np.frombuffer(layer.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)
    assert stored.shape == (120, 240) and stored[0, 0] == 255 and stored[0, -1] == 0


def test_a_copy_is_a_work_of_its_own_rename_changes_the_name_only_and_delete_removes_the_work(app_world):
    client = app_world["client"]
    work = create(client, name="Inna")
    client.post(f"/api/photo-works/{work['id']}/settings", json={"min_power": 12, "max_power": 28, "by_colour": True})
    made = client.post(f"/api/photo-works/{work['id']}/copy", json={}).json()
    copy = client.get(f"/api/photo-works/{made['id']}").json()
    assert copy["name"] == "Inna (копия)" and copy["identifier"] != work["identifier"]
    assert (copy["min_power"], copy["max_power"], copy["by_colour"], copy["scale"]) == (12, 28, True, work["scale"])
    store = app_world["client"].app.state.store
    paths = [photo_work._work(store, i)["image_path"] for i in (work["id"], made["id"])]
    assert paths[0] != paths[1]
    assert client.post(f"/api/photo-works/{made['id']}/rename", json={"name": " Инна "}).json() == {"id": made["id"], "name": "Инна"}
    assert client.get(f"/api/photo-works/{made['id']}").json()["min_power"] == 12
    assert client.post(f"/api/photo-works/{made['id']}/rename", json={"name": " "}).status_code == 422
    assert client.delete(f"/api/plans/{made['id']}").status_code == 204
    assert made["id"] not in [w["id"] for w in client.get("/api/photo-works").json()]
    gone = client.get(f"/api/photo-works/{made['id']}")
    assert gone.status_code == 404 and gone.json()["error"] == f"plan {made['id']} not found"          # never photographed: removed
    assert client.get(f"/api/photo-works/{work['id']}").json()["name"] == "Inna"           # the first stays as it was


def test_a_work_whose_scale_is_no_longer_measured_opens_and_says_why_and_another_scale_can_be_chosen(app_world):
    client = app_world["client"]
    store = client.app.state.store
    work = create(client)
    row = store.one("SELECT data_json FROM plan WHERE id=?", (work["id"],))
    data = json.loads(row["data_json"])
    data["scale"]["speed"] = 999                        # as if its measurements were deleted
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), work["id"]))
    shown = client.get(f"/api/photo-works/{work['id']}").json()
    assert shown["picture"] is None and shown["problem"] == "no colour has been measured at this mode: there is nothing to predict from"
    assert client.get(f"/api/photo-works/{work['id']}/thumb.png").status_code == 200       # the picture as LightBurn sees it
    assert client.get(f"/api/photo-works/{work['id']}/export.lbrn2").status_code == 422
    back = client.post(f"/api/photo-works/{work['id']}/settings", json={"scale": scale_of(client, 150, 0.0169)}).json()
    assert back["picture"]["power_range"] == [2.0, 40.0]


def test_without_a_measured_scale_a_new_work_is_refused_with_the_way_to_measure_one(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        refused = client.post("/api/photo-works", data={"width_mm": 50}, files={"picture": ("p.png", picture_png(), "image/png")})
        assert refused.status_code == 422
        assert refused.json()["error"] == "no grayscale scale is measured yet: engrave the grey-scale plate and add its photograph first"
        not_a_picture = client.post("/api/photo-works", data={"width_mm": 50}, files={"picture": ("p.png", b"nothing", "image/png")})
        assert not_a_picture.status_code == 422
    app.state.store.close()
