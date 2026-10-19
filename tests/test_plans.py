import cv2
import numpy as np
import pytest

from titanium_platform import devices
from titanium_platform import lightburn as lb
from titanium_platform import photo
from titanium_platform import plans as pl
from titanium_platform import setup as su

JOB = {"pulse_width": 200, "line_interval": 0.025, "passes": 1}


@pytest.fixture
def laser(store):
    return devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")


@pytest.fixture
def setup(store, laser):
    return su.installed(store, laser["id"])


@pytest.fixture
def ready(store, laser):
    pl.save_marker_layer_settings(store, 20, 60, 300)
    return laser


def test_parse_numbers_accepts_decimal_comma_and_semicolons():
    assert pl.parse_numbers("10 20;30,5", "power") == [10, 20, 30.5]
    for bad in ("", "a b", "10 10"):
        with pytest.raises(su.ValidationError):
            pl.parse_numbers(bad, "power")


def test_grid_is_power_by_columns_frequency_by_rows_with_exact_size(setup):
    g = pl.build_grid(setup, [10, 20, 30], [40, 80], 900, 5, 4, 1, **JOB)
    assert (g["geometry"]["columns"], g["geometry"]["rows"]) == (3, 2)
    assert g["geometry"]["width"] == 3 * 5 + 2 * 1 and g["geometry"]["height"] == 2 * 4 + 1
    c = next(c for c in g["cells"] if c["id"] == "r2c3")
    assert (c["parameters"]["power"], c["parameters"]["frequency"], c["parameters"]["speed"]) == (30, 80, 900)
    assert c["parameters"] == {"power": 30, "frequency": 80, "speed": 900, **JOB}
    assert c["geometry"] == {"x": 12, "y": 5, "width": 5, "height": 4}


@pytest.mark.parametrize("kw", [dict(powers=[500], frequencies=[40]), dict(powers=[10], frequencies=[5000]), dict(powers=[10], frequencies=[40], speed=0),
                                dict(powers=[10], frequencies=[40], cell_w=0), dict(powers=[10], frequencies=[40], gap=-1)])
def test_grid_rejects_out_of_range_and_bad_geometry(setup, kw):
    args = dict(powers=[10], frequencies=[40], speed=900, cell_w=5, cell_h=4, gap=1)
    args.update(kw)
    with pytest.raises(su.ValidationError):
        pl.build_grid(setup, args.pop("powers"), args.pop("frequencies"), args.pop("speed"), args.pop("cell_w"), args.pop("cell_h"), args.pop("gap"), **JOB)


def test_a_plate_has_no_default_job_settings(setup):
    with pytest.raises(TypeError):
        pl.build_grid(setup, [10], [40], 900, 5, 4, 1)          # DEC-043: 200 ns is never filled in by the server


def test_plates_cannot_be_created_before_marker_layer_settings_exist(store, laser):
    with pytest.raises(su.ValidationError, match="marker layer"):
        pl.create_plate_series(store, laser["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)
    assert store.query("SELECT * FROM plate") == []


def test_series_creates_one_plate_and_plan_per_speed_with_markers_and_identifier(store, ready):
    out = pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900 1200", 5, 4, 1, **JOB)
    assert [o["speed"] for o in out] == [900, 1200] and len({o["experiment_id"] for o in out}) == 2
    plan = pl.get_plan(store, out[0]["plan_id"])
    assert plan["mode"] == pl.MODE_PLATE and plan["markers_enabled"] and plan["plan_identifier"] == out[0]["experiment_id"]
    assert len(plan["layers"]) == 4 and len(plan["markers"]["aruco"]) == 4
    assert store.one("SELECT COUNT(*) AS n FROM observation")["n"] == 0  # creating a plate never creates measurements


def test_series_is_atomic(store, ready):
    with pytest.raises(su.ValidationError):
        pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900 -5", 5, 4, 1, **JOB)
    assert store.query("SELECT * FROM plate") == [] and store.query("SELECT * FROM plan") == []


def test_plate_export_round_trips_through_the_lightburn_reader(store, ready):
    out = pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)[0]
    data = pl.export_lbrn2(pl.get_plan(store, out["plan_id"]))
    project = lb.parse_bytes(data)
    cells = {l.name: l for l in project.layers if l.index not in (pl.CLEAN_LAYER_INDEX, pl.PLATE_MARKER_LAYER_INDEX)}
    assert len(cells) == 4
    l = cells["r2c1"]
    assert (l.power, l.frequency_khz, l.speed, l.pulse_width, l.line_interval) == (10, 80, 900, 200, 0.025)
    dx, dy = pl.export_offset(pl.get_plan(store, out["plan_id"]))
    assert dx > 0 and dy > 0  # markers moved into the positive workspace
    assert l.regions[0].x == pytest.approx(0 + dx) and l.regions[0].y == pytest.approx(5 + dy) and l.regions[0].width == pytest.approx(5)
    assert project.identifier == out["experiment_id"]
    # the file stores centre and size with 5 decimals (0.01 micrometre), so allow that much rounding
    assert min(r.x for lay in project.layers for r in lay.regions) >= -1e-4
    assert min(r.y for lay in project.layers for r in lay.regions) >= -1e-4
    marker = project.layer(pl.PLATE_MARKER_LAYER_INDEX)
    assert (marker.power, marker.frequency_khz, marker.speed) == (20, 60, 300) and len(marker.regions) > 20


def _raster(plan, scale=20, pad=2):
    m = plan["markers"]["extent"]
    w, h = int((m["max_x"] - m["min_x"] + 2 * pad) * scale), int((m["max_y"] - m["min_y"] + 2 * pad) * scale)
    img = np.full((h, w), 255, np.uint8)
    rects = [r for a in plan["markers"]["aruco"] for r in a["rects"]] + plan["markers"]["qr"]["rects"]
    px = lambda v: int(round(v))  # rounding, not truncation: truncation leaves 1 px gaps between touching rows
    for r in rects:
        x0, y0 = px((r["x"] - m["min_x"] + pad) * scale), px((r["y"] - m["min_y"] + pad) * scale)
        x1, y1 = px((r["x"] + r["width"] - m["min_x"] + pad) * scale), px((r["y"] + r["height"] - m["min_y"] + pad) * scale)
        img[y0:y1, x0:x1] = 0
    return img


def test_exported_markers_are_detected_and_identifier_decoded_from_the_raster(store, ready):
    out = pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)[0]
    plan = pl.get_plan(store, out["plan_id"])
    img = _raster(plan)
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    _, ids, _ = det.detectMarkers(img)
    assert sorted(ids.ravel().tolist()) == [0, 1, 2, 3]
    assert photo.read_identifier(img) == out["experiment_id"]       # the product's reader: OpenCV's classic detector alone misses ~1 % of identifiers


@pytest.mark.parametrize("identifier", ["TCE-AFA45888", "TCE-BC594484", "TCE-18B867C4", "TCE-C3C69AE5"])
def test_an_identifier_the_classic_qr_detector_misses_is_still_read_from_the_exported_raster(identifier):
    """Found by a failing run of the test above (random identifier TCE-AFA45888): the code is valid and the ArUco-based detector reads it at
    every scale, so the product's reader, which falls back to it, must give the identifier back."""
    img = _raster({"markers": pl.marker_geometry(identifier, 11, 9)})
    assert photo.read_identifier(img) == identifier


def test_markers_lie_outside_the_grid(store, ready):
    out = pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900", 5, 4, 1, **JOB)[0]
    plan = pl.get_plan(store, out["plan_id"])
    g = out["geometry"]
    for a in plan["markers"]["aruco"]:
        outside_x = a["x"] + a["size"] <= 0 or a["x"] >= g["width"]
        outside_y = a["y"] + a["size"] <= 0 or a["y"] >= g["height"]
        assert outside_x and outside_y
    assert plan["markers"]["qr"]["y"] >= g["height"]


def _discrete_plan(n, with_prediction=True):
    layers = []
    for i in range(1, n + 1):
        pred = {"lab": [50, 1, 2], "confidence": 0.8, "expected_delta_e": 2.0, "stability": {"assessed": True, "variance": 0.5}} if with_prediction else None
        layers.append({"index": i, "name": f"band {i}", "parameters": {"power": 10 + i, "frequency": 40 + i, "speed": 900 + i, "pulse_width": 200, "line_interval": 0.025},
                       "regions": [{"x": i, "y": 0, "width": 1, "height": 5}], "prediction": pred})
    return {"layers": layers, "markers": None}


def test_export_respects_lightburn_output_palette_limit_and_keeps_each_layer_parameters():
    project = lb.parse_bytes(pl.export_lbrn2(_discrete_plan(29)))
    assert len(project.layers) == 29 and max(layer.index for layer in project.layers) == 29
    assert {(l.power, l.frequency_khz, l.speed) for l in project.layers} == {(10.0 + i, 40.0 + i, 900.0 + i) for i in range(1, 30)}
    with pytest.raises(su.ValidationError, match="output layers"):
        pl.export_lbrn2(_discrete_plan(30))


def test_export_refuses_incomplete_predictions_and_missing_parameters():
    plan = _discrete_plan(2)
    plan["layers"][0]["prediction"]["confidence"] = None
    with pytest.raises(su.ValidationError, match="incomplete prediction"):
        pl.export_lbrn2(plan)
    plan = _discrete_plan(2)
    plan["layers"][1]["parameters"]["speed"] = None
    with pytest.raises(su.ValidationError, match="lacks"):
        pl.export_lbrn2(plan)
    with pytest.raises(su.ValidationError):
        pl.export_lbrn2({"layers": [], "markers": None})


def test_export_refuses_more_layers_than_lightburn_has():
    with pytest.raises(su.ValidationError, match="exceed"):
        pl.export_lbrn2(_discrete_plan(300))
