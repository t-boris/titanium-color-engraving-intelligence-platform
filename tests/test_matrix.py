"""A parameter matrix (LightBurn Material Test) recognised from its photograph (REQ-031, DEC-061)."""
import json

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color
from titanium_platform import ingest as ig
from titanium_platform import lightburn as lb
from titanium_platform import matrix as mx
from titanium_platform import photo as ph
from titanium_platform import devices
from titanium_platform import setup as su
from titanium_platform.db import Store

needs_ocr = pytest.mark.skipif(not mx.ocr_available(), reason="tesseract is not installed")


def exposed(img_bgr):
    return ph.exposed_bgr(color.srgb_to_linear(ph.decoded_srgb(img_bgr)).astype(np.float32))


@pytest.fixture(scope="module")
def work():
    return synth.material_test(cols=6, rows=5)


# -- geometry ----------------------------------------------------------------------------------------------------------
def test_the_grid_of_a_turned_photograph_is_found_to_a_pixel_without_reading_any_label(work):
    img = exposed(work["photo"])
    chart = ph.detect_chart(img)
    det = mx.detect(img, chart.box if chart.detected else None, read_labels=False)
    assert len(det["grids"]) == 1
    grid = det["grids"][0]
    assert (grid["cols"], grid["rows"]) == (6, 5)
    H = np.array(grid["H"])
    err = max(np.linalg.norm(mx.to_px(H, [(c, r)])[0] - work["centres"][r][c]) for r in range(5) for c in range(6))
    assert err < 2.0


def test_the_chart_is_found_in_an_under_exposed_photograph_only_after_its_exposure_is_normalised():
    dark = synth.material_test(exposure=1 / 12)["photo"]
    linear = color.srgb_to_linear(ph.decoded_srgb(dark)).astype(np.float32)
    corrected, chart, corr = ph.correct(dark, linear=linear)
    assert chart.detected and corrected is not None and corr.residual < 6
    assert len(corr.grey_ramp["corrected"]) == 6


def test_a_matrix_cut_by_the_edge_of_the_photograph_is_not_offered():
    whole = synth.material_test()
    cut = whole["photo"][:, :whole["centres"][0][3][0].astype(int)]          # the right half of the grid is outside
    det = mx.detect(exposed(cut), None, read_labels=False)
    assert all(g["cols"] < 6 or g["corners_px"][1][0] < cut.shape[1] for g in det["grids"])
    assert not any(g["cols"] == 6 for g in det["grids"])


# -- reading the labels --------------------------------------------------------------------------------------------------
def test_an_evenly_spaced_sequence_is_recovered_from_misread_labels():
    labels = {0: ["1500"], 1: ["4389"], 2: ["1278"], 3: ["167"], 4: ["1056"], 5: ["944"], 6: ["833"], 7: ["122"], 8: ["611"],
              9: ["510", "500"]}
    fit = mx.fit_axis(labels)
    assert fit["a"] == pytest.approx(1500, abs=1) and fit["b"] == pytest.approx(-111.11, abs=0.2)
    assert mx._axis_values(fit, 0, 10)[1] == pytest.approx(1388.888889, abs=1e-3)
    assert mx._axis_values(fit, 0, 10)[-1] == 500.0


def test_a_lost_decimal_point_counts_only_half_and_zero_or_one_digit_readings_count_nothing():
    labels = {0: ["00100"], 1: ["0090"], 2: ["0.0080"], 3: ["0070"], 5: ["0"], 7: ["0.0030"], 8: ["0.0020"], 9: ["00"]}
    fit = mx.fit_axis(labels)
    assert fit["a"] == pytest.approx(0.010, abs=1e-6) and fit["b"] == pytest.approx(-0.001, abs=1e-6)
    assert 5 not in fit["inliers"] and 9 not in fit["inliers"]


def test_two_agreeing_labels_are_not_enough_when_the_axis_has_three_or_more_cells():
    assert mx.fit_axis({0: ["18"], 1: ["1950"], 2: [], 3: []}, need=3)["a"] is None
    assert mx.fit_axis({0: ["0.0050"], 1: ["0.0040"]}, need=2)["b"] == pytest.approx(-0.001)


def test_the_header_is_read_through_the_usual_misreadings():
    assert mx.parse_header("Imerval: 0.0030 mm Passes: 1\nFrequency. 330.0 KHz Q-Pulse: 4.00 ns") == \
        {"line_interval": 0.003, "passes": 1.0, "frequency": 330.0, "pulse_width": 4.0}
    assert mx.parse_header("Frequency: 60.0 KHz Q-Pulee: 300.00 rs.") == {"frequency": 60.0, "pulse_width": 300.0}
    assert mx.parse_header("Speed: 1800 mm/s Pasees: 1") == {"speed": 1800.0, "passes": 1.0}


def test_the_varying_settings_are_named_by_the_titles_or_by_what_the_header_does_not_list():
    fit_x = {"a": 25.0, "b": 2.5, "inliers": [0, 1, 2], "decimals": 1, "single": False}
    fit_y = {"a": 1500.0, "b": -100.0, "inliers": [0, 1, 2], "decimals": 0, "single": False}
    header = ["Interval: 0.0030 mm Passes: 1\nFrequency: 330.0 KHz Q-Pulse: 4.00 ns"]
    spec = mx.interpret(header, [], [], 3, 3, fit_x, fit_y, 0, 0)
    assert spec["x"]["param"] == "power" and spec["y"]["param"] == "speed" and spec["missing"] == []
    one_column = mx.interpret(["Speed: 1800 mm/s Passes: 1\nFrequency: 1950.0 KHz Interval: 0.0030 mm"], [], [], 1, 10,
                              {"a": 40.0, "b": 0.0, "inliers": [0], "single": True, "decimals": 1},
                              {"a": 10.0, "b": -1.0, "inliers": [0, 1, 2], "single": False, "decimals": 2}, 0, 0)
    assert one_column["x"]["param"] == "power" and one_column["x"]["values"] == [40.0]
    assert one_column["y"]["param"] == "pulse_width" and one_column["y"]["values"][0] == 10.0
    # two candidates for the rows (Q-pulse, interval): the usual range of the values decides
    ambiguous = mx.interpret(["Speed: 1800 mm/s Passes: 1 Frequency: 1950.0 KHz"], [], [], 1, 10,
                             {"a": 40.0, "b": 0.0, "inliers": [0], "single": True, "decimals": 1},
                             {"a": 10.0, "b": -1.0, "inliers": [0, 1, 2], "single": False, "decimals": 2}, 0, 0)
    assert ambiguous["y"]["param"] == "pulse_width" and ambiguous["missing"] == ["Interval is not known"]


@needs_ocr
def test_the_engraved_labels_of_a_synthetic_matrix_are_read(work):
    img = exposed(work["photo"])
    chart = ph.detect_chart(img)
    grid = mx.detect(img, chart.box if chart.detected else None)["grids"][0]
    spec = grid["spec"]
    assert spec["x"]["param"] == "power" and spec["x"]["values"] == pytest.approx(work["x_values"])
    assert spec["y"]["param"] == "speed" and spec["y"]["values"] == pytest.approx(work["y_values"])
    assert spec["fixed"]["frequency"] == 330.0 and spec["fixed"]["pulse_width"] == 4.0 and spec["fixed"]["passes"] == 1.0


# -- the generated file ------------------------------------------------------------------------------------------------
def spec_of(work, **fixed):
    return {"x": {"param": "power", "values": work["x_values"], "decimals": 1},
            "y": {"param": "speed", "values": work["y_values"], "decimals": 0},
            "fixed": {"frequency": 330.0, "pulse_width": 4.0, "line_interval": 0.003, "passes": 1.0, **fixed},
            "pitch_mm": 5.0, "cell_fraction": 0.86}


def test_the_generated_lightburn_file_holds_one_layer_per_cell_with_its_full_setting(work):
    spec = spec_of(work)
    project = lb.parse_bytes(mx.lightburn_bytes(spec, 6, 5))
    layers = {layer.index: layer for layer in project.layers}
    assert len(layers) == 30
    cell = layers[2 * 6 + 4]                          # row 2, column 4
    assert cell.power == pytest.approx(work["x_values"][4]) and cell.speed == pytest.approx(work["y_values"][2])
    assert cell.frequency_khz == pytest.approx(330.0) and cell.pulse_width == 4.0 and cell.line_interval == 0.003 and cell.passes == 1
    assert len(cell.regions) == 1 and cell.regions[0].kind == "rect"
    assert all(layer.unknown_settings == [] and not layer.unsupported for layer in project.layers)   # nothing to report (REQ-036 AC3)
    x, y = mx.cell_centre_mm(spec, 5, 4, 2)
    assert cell.regions[0].x + cell.regions[0].width / 2 == pytest.approx(x, abs=1e-3)
    assert cell.regions[0].y + cell.regions[0].height / 2 == pytest.approx(y, abs=1e-3)


def test_photo_pixels_map_onto_the_cells_of_the_generated_file(work):
    img = exposed(work["photo"])
    grid = mx.detect(img, None, read_labels=False)["grids"][0]
    record = {**grid, "spec": spec_of(work)}
    to_mm = mx.image_to_mm(record)
    for r, c in ((0, 0), (4, 5), (2, 3)):
        mm = mx.to_px(to_mm, [work["centres"][r][c]])[0]
        assert np.allclose(mm, mx.cell_centre_mm(record["spec"], 5, c, r), atol=0.15)


def test_an_edit_spaces_the_values_evenly_and_moves_or_resizes_the_grid(work):
    record = {"cols": 6, "rows": 5, "H": np.eye(3).tolist(), "spec": {**spec_of(work), "missing": []}, "confirmed": True}
    out = mx.apply_edit(record, {"y": {"param": "line_interval", "first": 0.01, "last": 0.002}, "fixed": {"speed": 1800},
                                 "extent": {"rows": 5, "cols": 6, "col_shift": 1, "row_shift": 0}})
    assert out["confirmed"] is False
    assert out["spec"]["y"]["values"] == pytest.approx([0.01, 0.008, 0.006, 0.004, 0.002])
    assert out["spec"]["fixed"]["speed"] == 1800.0 and "line_interval" not in out["spec"]["fixed"]
    assert mx.to_px(np.array(out["H"]), [(0, 0)])[0] == pytest.approx([1, 0])
    with pytest.raises(ValueError):
        mx.apply_edit(record, {"x": {"param": "colour"}})


# -- the whole path ------------------------------------------------------------------------------------------------------
@pytest.fixture
def world(tmp_path):
    store = Store(tmp_path)
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")   # every photograph names its rig (REQ-009)
    yield store, laser, material
    store.close()


def test_a_photographed_matrix_becomes_one_confirmed_observation_per_cell(world):
    store, laser, material = world
    work = synth.material_test(cols=4, rows=3, x_values=[20.0, 30.0, 40.0, 50.0], y_values=[900.0, 600.0, 300.0])
    photo = cv2.imencode(".png", work["photo"])[1].tobytes()
    pid = ig.create_matrix_pair(store, device_id=laser["id"], lens_id=None, photo_name="matrix.png", photo_bytes=photo,
                                context={"material_id": material["id"]})
    pair = ig.get_pair(store, pid)
    assert pair["matrix"]["cols"] == 4 and pair["matrix"]["rows"] == 3 and pair["matrix"]["confirmed"] is False
    assert pair["lightburn_name"].endswith(".lbrn2")
    # whatever was read, the operator states the settings that were engraved, and confirms them
    report = ig.update_matrix(store, pid, {"x": {"param": "power", "first": 20, "last": 50}, "y": {"param": "speed", "first": 900, "last": 300},
                                          "fixed": {"frequency": 330, "pulse_width": 4, "line_interval": 0.003, "passes": 1}}, confirm=True)
    assert report["alignment"]["method"] == "material test grid" and report["problems"] == []
    assert sum(1 for rep in report["layers"] if rep["measured_lab"] is not None) == 12
    cell = next(rep for rep in report["layers"] if rep["index"] == 1 * 4 + 2)
    assert cell["matrix_cell"]["power"] == 40.0 and cell["matrix_cell"]["speed"] == 600.0
    ig.review_masks(store, pid)
    ids = ig.accept_pair(store, pid)
    assert len(ids) == 12
    obs = store.one("SELECT parameters_json, evidence_json, model_eligible FROM observation WHERE layer_index=? AND pair_id=?", (6, pid))
    params, evidence = json.loads(obs["parameters_json"]), json.loads(obs["evidence_json"])
    assert params["power"] == pytest.approx(40.0) and params["speed"] == pytest.approx(600.0) and params["pulse_width"] == 4.0
    assert evidence["matrix_cell"]["col"] == 2 and evidence["matrix_cell"]["row"] == 1 and obs["model_eligible"] == 1


def test_the_settings_of_a_matrix_cell_are_an_operator_confirmed_reconstruction_never_file_evidence(world):
    """REQ-036 AC8, DEC-072: the generated LightBurn file only records what the photograph and the operator said, so the
    observation names its settings a reconstruction confirmed by the operator, with when, and never "file"."""
    store, laser, material = world
    work = synth.material_test(cols=3, rows=2, x_values=[20.0, 30.0, 40.0], y_values=[900.0, 300.0])
    pid = ig.create_matrix_pair(store, device_id=laser["id"], lens_id=None, photo_name="m.png",
                                photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(), context={"material_id": material["id"]})
    complete = {"x": {"param": "power", "first": 20, "last": 40}, "y": {"param": "speed", "first": 900, "last": 300},
                "fixed": {"frequency": 330, "pulse_width": 4, "line_interval": 0.003, "passes": 1}}
    ig.update_matrix(store, pid, complete)
    assert ig.get_pair(store, pid)["matrix"].get("confirmed_at") is None
    ig.confirm_matrix(store, pid)
    confirmed_at = ig.get_pair(store, pid)["matrix"]["confirmed_at"]
    assert confirmed_at
    ig.update_matrix(store, pid, complete)                     # a correction withdraws the confirmation and its time
    assert ig.get_pair(store, pid)["matrix"]["confirmed_at"] is None
    ig.update_matrix(store, pid, complete, confirm=True)
    confirmed_at = ig.get_pair(store, pid)["matrix"]["confirmed_at"]
    assert confirmed_at
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)
    rows = store.query("SELECT evidence_json FROM observation WHERE pair_id=?", (pid,))
    assert len(rows) == 6
    for row in rows:
        evidence = json.loads(row["evidence_json"])
        assert set(evidence["settings_provenance"].values()) == {"reconstruction"}, evidence["settings_provenance"]
        assert evidence["reconstruction"] == {"from": "photographed parameter matrix", "confirmed_by": "operator", "confirmed_at": confirmed_at}


def test_an_unconfirmed_or_incomplete_matrix_is_never_accepted(world):
    store, laser, material = world
    work = synth.material_test(cols=3, rows=3, x_values=[20.0, 30.0, 40.0], y_values=[900.0, 600.0, 300.0])
    pid = ig.create_matrix_pair(store, device_id=laser["id"], lens_id=None, photo_name="m.png",
                                photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(), context={"material_id": material["id"]})
    ig.update_matrix(store, pid, {"fixed": {"frequency": None}})
    with pytest.raises(ig.IngestError, match="incomplete"):
        ig.confirm_matrix(store, pid)
    report = ig.update_matrix(store, pid, {"x": {"param": "power", "first": 20, "last": 40}, "y": {"param": "speed", "first": 900, "last": 300},
                                          "fixed": {"frequency": 330, "pulse_width": 4, "line_interval": 0.003, "passes": 1}})
    assert report["problems"] == []
    ig.review_masks(store, pid)
    with pytest.raises(ig.IngestError, match="confirm the settings"):
        ig.accept_pair(store, pid)


def test_a_photograph_without_a_matrix_is_refused_with_a_reason(world):
    store, laser, material = world
    with pytest.raises(ig.IngestError, match="no parameter matrix"):
        ig.create_matrix_pair(store, device_id=laser["id"], lens_id=None, photo_name="empty.png",
                              photo_bytes=cv2.imencode(".png", synth.scene())[1].tobytes(), context={"material_id": material["id"]})
