"""A photographed parameter matrix through the application (REQ-031, DEC-061): several matrices in one photograph, unusual
settings, the correction route, a re-photograph of an accepted matrix, and the names the server stores."""
import re

import cv2
import pytest
from fastapi.testclient import TestClient

import synth
from titanium_platform import ingest as ig
from titanium_platform import lightburn as lb
from titanium_platform import matrix as mx
from titanium_platform.api.app import UI_DIR, create_app

SETTINGS = {"x": {"param": "power", "first": 20, "last": 50}, "y": {"param": "speed", "first": 900, "last": 300},
            "fixed": {"frequency": 330, "pulse_width": 4, "line_interval": 0.003, "passes": 1}}


def png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path / "data")
    store = app.state.store
    store.set_setting("allow_non_raw_photos", True)          # tests upload PNG renders; real use requires RAW
    with TestClient(app) as client:
        laser = client.post("/api/devices/from-template", json={"template": "jpt-ydflp-e-60-m7-m-r"}).json()
        material = client.post("/api/materials", json={"name": "Grade 2 sheet", "grade": "Grade 2", "thickness_mm": 1, "surface": "brushed"}).json()
        client.post("/api/setups", json={"name": "Rig", "camera": "cam", "lighting": "LED", "angle": "90", "reference_chart": "ColorChecker Classic"})
        yield {"client": client, "store": store, "laser": laser, "material": material}
    store.close()


def upload(app, photo: bytes, name: str = "matrix.png"):
    return app["client"].post("/api/matrix-pairs", data={"device_id": app["laser"]["id"], "lens_id": "unknown",
                                                          "context": f'{{"material_id": {app["material"]["id"]}}}'},
                              files={"photo": (name, photo, "image/png")})


def test_a_photograph_with_two_complete_matrices_offers_both_and_the_second_becomes_its_own_experiment_over_http(app):
    client = app["client"]
    made = upload(app, png(synth.two_material_tests()["photo"]))
    assert made.status_code == 201, made.text
    first = made.json()
    m = first["matrix"]
    assert (m["cols"], m["rows"]) == (4, 3) and m["grids_in_photo"] == 2
    assert [(o["cols"], o["rows"], o["created_pair_id"]) for o in m["others"]] == [(3, 3, None)]
    second = client.post(f"/api/pairs/{first['id']}/matrix/others/0")
    assert second.status_code == 201, second.text
    other = second.json()
    assert other["id"] != first["id"] and (other["matrix"]["cols"], other["matrix"]["rows"]) == (3, 3)
    assert other["engraving_id"] != first["engraving_id"]                           # its own experiment, its own engraving
    assert client.get(f"/api/pairs/{first['id']}").json()["matrix"]["others"][0]["created_pair_id"] == other["id"]
    again = client.post(f"/api/pairs/{first['id']}/matrix/others/0")
    assert again.status_code == 422 and f"experiment №{other['id']}" in again.json()["error"]
    layers = lb.parse_bytes(client.get(f"/api/pairs/{other['id']}/lightburn").content).layers
    assert len(layers) == 9                                                         # one layer per cell of the second matrix


def test_a_setting_outside_the_usual_range_is_flagged_and_the_review_lists_it(app):
    spec = {"x": {"param": "power", "values": [20.0, 30.0]}, "y": {"param": "speed", "values": [5.0, 900.0]},
            "fixed": {"frequency": 4500.0, "pulse_width": 4.0, "line_interval": 0.003, "passes": 1.0}}
    assert mx.unusual(spec) == ["speed", "frequency"]                              # valid, but not what a marking laser is set to
    pair = upload(app, png(synth.material_test(cols=4, rows=3, x_values=[20.0, 30.0, 40.0, 50.0], y_values=[900.0, 600.0, 300.0])["photo"])).json()
    edited = app["client"].post(f"/api/pairs/{pair['id']}/matrix", json={"edit": {**SETTINGS, "y": {"param": "speed", "first": 5, "last": 300}}}).json()
    assert edited["matrix"]["spec"]["unusual"] == ["speed"]
    review = (UI_DIR / "screens" / "ingest-review.js").read_text(encoding="utf-8")
    assert "s.unusual && s.unusual.length" in review and "s.unusual.map(paramName)" in review


def test_correcting_a_matrix_over_http_regenerates_its_file_and_checks_the_photograph_again(app):
    client = app["client"]
    pair = upload(app, png(synth.material_test(cols=4, rows=3, x_values=[20.0, 30.0, 40.0, 50.0], y_values=[900.0, 600.0, 300.0])["photo"])).json()
    response = client.post(f"/api/pairs/{pair['id']}/matrix", json={"edit": SETTINGS})
    assert response.status_code == 200, response.text
    corrected = response.json()
    layers = lb.parse_bytes(client.get(f"/api/pairs/{pair['id']}/lightburn").content).layers
    assert sorted({layer.power for layer in layers}) == [20, 30, 40, 50] and sorted({layer.speed for layer in layers}) == [300, 600, 900]
    assert {layer.frequency_khz for layer in layers} == {330} and {layer.pulse_width for layer in layers} == {4}
    check = corrected["check"]                                                      # the photograph was checked against the new file
    assert check["alignment"]["method"] == "material test grid" and check["problems"] == []
    cell = next(rep for rep in check["layers"] if rep["index"] == 1 * 4 + 2)
    assert (cell["matrix_cell"]["power"], cell["matrix_cell"]["speed"]) == (40.0, 600.0) and cell["measured_lab"] is not None
    # the server keeps the generated names in English; the screens show them in Russian (I18N.name, test_ui_gaps)
    assert corrected["engraving_title"].startswith("Material test: Power x Speed · 330 kHz 4 ns · ")
    assert all(re.fullmatch(r"Power \d+(\.\d+)? x Speed \d+(\.\d+)?", rep["name"]) for rep in check["layers"]), [r["name"] for r in check["layers"]]


def test_a_rephotograph_of_an_accepted_matrix_keeps_the_confirmed_settings(app):
    store = app["store"]
    work = synth.material_test(cols=4, rows=3, x_values=[20.0, 30.0, 40.0, 50.0], y_values=[900.0, 600.0, 300.0])
    pid = upload(app, png(work["photo"])).json()["id"]
    ig.update_matrix(store, pid, SETTINGS, confirm=True)
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)
    source = ig.get_pair(store, pid)["matrix"]
    again = synth.material_test(cols=4, rows=3, x_values=[20.0, 30.0, 40.0, 50.0], y_values=[900.0, 600.0, 300.0], rotate_deg=-0.6, seed=9)
    rid = ig.create_rephoto(store, pid, photo_name="again.png", photo_bytes=png(again["photo"]))
    matrix = ig.get_pair(store, rid)["matrix"]
    assert matrix["confirmed"] is True
    for key in ("x", "y"):
        assert (matrix["spec"][key]["param"], matrix["spec"][key]["values"]) == (source["spec"][key]["param"], source["spec"][key]["values"])
    assert matrix["spec"]["fixed"] == source["spec"]["fixed"]
    report = ig.check_pair(store, rid)
    assert report["problems"] == [] and sum(rep["measured_lab"] is not None for rep in report["layers"]) == 12
