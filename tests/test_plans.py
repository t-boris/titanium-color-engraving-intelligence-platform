import cv2
import numpy as np
import pytest

from titanium_platform import lightburn as lb
from titanium_platform import plans as pl
from titanium_platform import profiles as pf


@pytest.fixture
def profile(store):
    return pf.create_profile(store, "MOPA", 200, 0.025, 1)


@pytest.fixture
def ready(store, profile):
    pl.save_marker_layer_settings(store, 20, 60, 300)
    return profile


def test_parse_numbers_accepts_decimal_comma_and_semicolons():
    assert pl.parse_numbers("10 20;30,5", "power") == [10, 20, 30.5]
    for bad in ("", "a b", "10 10"):
        with pytest.raises(pf.ValidationError):
            pl.parse_numbers(bad, "power")


def test_grid_is_power_by_columns_frequency_by_rows_with_exact_size(profile):
    g = pl.build_grid(profile, [10, 20, 30], [40, 80], 900, 5, 4, 1)
    assert (g["geometry"]["columns"], g["geometry"]["rows"]) == (3, 2)
    assert g["geometry"]["width"] == 3 * 5 + 2 * 1 and g["geometry"]["height"] == 2 * 4 + 1
    c = next(c for c in g["cells"] if c["id"] == "r2c3")
    assert (c["parameters"]["power"], c["parameters"]["frequency"], c["parameters"]["speed"]) == (30, 80, 900)
    assert c["parameters"]["pulse_width"] == 200 and c["parameters"]["profile_id"] == profile["id"]
    assert c["geometry"] == {"x": 12, "y": 5, "width": 5, "height": 4}


@pytest.mark.parametrize("kw", [dict(powers=[500], frequencies=[40]), dict(powers=[10], frequencies=[40], cell_w=0), dict(powers=[10], frequencies=[40], gap=-1)])
def test_grid_rejects_out_of_range_and_bad_geometry(profile, kw):
    args = dict(powers=[10], frequencies=[40], speed=900, cell_w=5, cell_h=4, gap=1)
    args.update(kw)
    with pytest.raises(pf.ValidationError):
        pl.build_grid(profile, args.pop("powers"), args.pop("frequencies"), args.pop("speed"), args.pop("cell_w"), args.pop("cell_h"), args.pop("gap"))


def test_plates_cannot_be_created_before_marker_layer_settings_exist(store, profile):
    with pytest.raises(pf.ValidationError, match="marker layer"):
        pl.create_plate_series(store, profile["id"], "10 20", "40 80", "900", 5, 4, 1)
    assert store.query("SELECT * FROM plate") == []


def test_series_creates_one_plate_and_plan_per_speed_with_markers_and_identifier(store, ready):
    out = pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900 1200", 5, 4, 1)
    assert [o["speed"] for o in out] == [900, 1200] and len({o["experiment_id"] for o in out}) == 2
    plan = pl.get_plan(store, out[0]["plan_id"])
    assert plan["mode"] == pl.MODE_PLATE and plan["markers_enabled"] and plan["plan_identifier"] == out[0]["experiment_id"]
    assert len(plan["layers"]) == 4 and len(plan["markers"]["aruco"]) == 4
    assert store.one("SELECT COUNT(*) AS n FROM observation")["n"] == 0  # creating a plate never creates measurements


def test_series_is_atomic(store, ready):
    with pytest.raises(pf.ValidationError):
        pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900 99999", 5, 4, 1)
    assert store.query("SELECT * FROM plate") == [] and store.query("SELECT * FROM plan") == []


def test_plate_export_round_trips_through_the_lightburn_reader(store, ready):
    out = pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900", 5, 4, 1)[0]
    data = pl.export_lbrn2(pl.get_plan(store, out["plan_id"]))
    project = lb.parse_bytes(data)
    cells = {l.name: l for l in project.layers if l.index != pl.MARKER_LAYER_INDEX}
    assert len(cells) == 4
    l = cells["r2c1"]
    assert (l.power, l.frequency_khz, l.speed, l.pulse_width, l.line_interval) == (10, 80, 900, 200, 0.025)
    assert l.regions[0].x == pytest.approx(0) and l.regions[0].y == pytest.approx(5) and l.regions[0].width == pytest.approx(5)
    marker = project.layer(pl.MARKER_LAYER_INDEX)
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
    out = pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900", 5, 4, 1)[0]
    plan = pl.get_plan(store, out["plan_id"])
    img = _raster(plan)
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    _, ids, _ = det.detectMarkers(img)
    assert sorted(ids.ravel().tolist()) == [0, 1, 2, 3]
    assert cv2.QRCodeDetector().detectAndDecode(img)[0] == f"TCE1:{out['experiment_id']}"


def test_markers_lie_outside_the_grid(store, ready):
    out = pl.create_plate_series(store, ready["id"], "10 20", "40 80", "900", 5, 4, 1)[0]
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


def test_32_band_export_has_32_layers_each_with_its_own_parameters():
    project = lb.parse_bytes(pl.export_lbrn2(_discrete_plan(32)))
    assert len(project.layers) == 32
    assert {(l.power, l.frequency_khz, l.speed) for l in project.layers} == {(10.0 + i, 40.0 + i, 900.0 + i) for i in range(1, 33)}


def test_export_refuses_incomplete_predictions_and_missing_parameters():
    plan = _discrete_plan(2)
    plan["layers"][0]["prediction"]["confidence"] = None
    with pytest.raises(pf.ValidationError, match="incomplete prediction"):
        pl.export_lbrn2(plan)
    plan = _discrete_plan(2)
    plan["layers"][1]["parameters"]["speed"] = None
    with pytest.raises(pf.ValidationError, match="lacks"):
        pl.export_lbrn2(plan)
    with pytest.raises(pf.ValidationError):
        pl.export_lbrn2({"layers": [], "markers": None})


def test_export_refuses_more_layers_than_lightburn_has():
    with pytest.raises(pf.ValidationError, match="exceed"):
        pl.export_lbrn2(_discrete_plan(300))
