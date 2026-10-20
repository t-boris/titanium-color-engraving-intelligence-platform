import json
import cv2
import numpy as np
from fastapi.testclient import TestClient
import pytest

from titanium_platform import capability_plates as cp, devices, lenses, lightburn, photo, plans
from titanium_platform import setup as su
from titanium_platform.api.app import create_app

JOB = {"pulse_width": 200}      # the pulse width of a test plate is always given (DEC-043)


def hardware(store):
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="CAP-01")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)   # the operator's C01 recipe (DEC-027)
    titanium = su.save_material(store, "Grade 2 sheet", batch="HEAT-17", grade="Grade 2")
    return laser, lens, titanium


def test_a_capability_plate_names_the_laser_and_the_installed_lens_and_snapshots_the_lens(store):
    """DEC-063: no hidden profile; REQ-019: the plate and its plan remember the lens with its spot value and basis."""
    laser, lens, titanium = hardware(store)
    devices.update_device(store, laser["id"], passport=laser["passport"] | {"m2": 1.3})
    made = cp.create(store, laser["id"], titanium["id"], "calibration", JOB)
    plate = store.one("SELECT device_id, lens_id, lens_json FROM plate WHERE id=?", (made["plate_id"],))
    assert (plate["device_id"], plate["lens_id"]) == (laser["id"], lens["id"])
    snapshot = json.loads(plate["lens_json"])
    assert snapshot["id"] == lens["id"] and snapshot["spot_basis"] == "calculated" and snapshot["spot_diameter_um"] > 0
    plan = plans.get_plan(store, made["plan_id"])
    assert (plan["device_id"], plan["lens_id"]) == (laser["id"], lens["id"]) and plan["lens"] == snapshot
    assert all(set(layer["parameters"]) == {"power", "frequency", "speed", "pulse_width", "line_interval", "passes"}
               for layer in plan["layers"])
    assert store.one("SELECT name FROM sqlite_master WHERE name='laser_profile'") is None


def test_generated_test_types_are_different_and_round_trip_as_clean_first_lightburn_plates(store):
    laser, lens, titanium = hardware(store)
    expected = {"compact_capability": (28, "Cut"), "text_readability": (9, "Scan"), "calibration": (24, "Scan"), "material_matrix": (25, "Cut"), "power_speed": (28, "Cut"), "frequency": (21, "Cut"),
                "pulse_cutoff": (28, "Cut"), "line_resolution": (10, "Cut"), "hatch_interval": (5, "Scan"),
                "offset_fill": (12, "OffsetFill"), "wobble": (9, "Scan")}
    for test_type, (count, layer_type) in expected.items():
        made = cp.create(store, laser["id"], titanium["id"], test_type, JOB)
        plan = plans.get_plan(store, made["plan_id"])
        file = plans.export_lbrn2(plan)
        assert b'MirrorY="True"' in file
        exported = lightburn.parse_bytes(file)

        assert plan["mode"] == plans.MODE_CAPABILITY and len(plan["layers"]) == count
        assert plan["experiment"]["device"]["id"] == laser["id"]
        assert plan["experiment"]["lens"]["id"] == lens["id"]
        assert plan["experiment"]["material"]["id"] == titanium["id"]
        assert made["summary"]["size_mm"]["width"] <= 100
        assert made["summary"]["size_mm"]["height"] <= 100
        assert exported.layer(0).name.startswith("CLEAN-")
        assert max(layer.index for layer in exported.layers) <= 29
        assert len(exported.layers) <= 30
        assert (exported.layer(0).power, exported.layer(0).frequency_khz, exported.layer(0).speed,
                exported.layer(0).pulse_width, exported.layer(0).line_interval,
                exported.layer(0).passes, exported.layer(0).global_passes,
                exported.layer(0).bidirectional, exported.layer(0).cross_hatch) == (20, 48, 2000, 200, 0.05, 1, 1, True, True)
        labels = exported.layer(1)
        assert (labels.name, labels.power, labels.frequency_khz, labels.speed, labels.pulse_width,
                labels.line_interval, labels.passes, labels.global_passes, labels.bidirectional) == (
                    "Markers and labels", 25, 60, 150, 200, 0.01, 1, 1, False)
        assert any(layer.layer_type == layer_type for layer in exported.layers[2:])
        assert exported.identifier == made["identifier"]
        # the reader knows every setting and shape this system writes: nothing to report on its own plates (REQ-036 AC3)
        assert all(layer.unknown_settings == [] and not layer.unsupported for layer in exported.layers), test_type


def test_markers_and_labels_burn_with_the_operators_marker_layer_settings_never_a_default(store):
    """DEC-027: no system default for the marker and label layer; an unmarked plate needs none."""
    laser, _, titanium = hardware(store)
    store.execute("DELETE FROM setting WHERE key='marker_layer'")
    with pytest.raises(su.ValidationError, match="set the marker layer power, frequency and speed"):
        cp.create(store, laser["id"], titanium["id"], "calibration", JOB)
    with pytest.raises(su.ValidationError, match="set the marker layer"):
        cp.preview(store, laser["id"], titanium["id"], "text_readability", JOB)
    unmarked = cp.create(store, laser["id"], titanium["id"], "small_patches", {**JOB, "registration": "none", "max_width_mm": 6, "max_height_mm": 6})
    assert plans.get_plan(store, unmarked["plan_id"])["marker_layer"] is None
    plans.save_marker_layer_settings(store, 30, 70, 400)
    made = cp.create(store, laser["id"], titanium["id"], "calibration", JOB)
    plan = plans.get_plan(store, made["plan_id"])
    labels = lightburn.parse_bytes(plans.export_lbrn2(plan)).layer(1)
    assert (labels.name, labels.power, labels.frequency_khz, labels.speed, labels.pulse_width, labels.line_interval) == (
        "Markers and labels", 30, 70, 400, None, None)            # what the operator left out is not filled in
    assert plan["experiment"]["label_settings"]["power"] == 30
    plans.save_marker_layer_settings(store, 30, 7000, 400)
    with pytest.raises(su.ValidationError, match="not offered by this laser: frequency 7000 kHz is outside"):
        cp.create(store, laser["id"], titanium["id"], "calibration", JOB)
    plans.save_marker_layer_settings(store, 30, 70, 400, pulse_width=600)
    with pytest.raises(su.ValidationError, match="outside the range"):
        cp.create(store, laser["id"], titanium["id"], "calibration", JOB)


def test_every_plate_type_explains_purpose_method_and_findings():
    assert len(cp.PLATE_TYPES) == 12
    assert len({item["id"] for item in cp.PLATE_TYPES}) == 12
    assert all(item.get("purpose") and item.get("action") and item.get("finds") for item in cp.PLATE_TYPES)


def test_one_small_patch_exports_a_clean_first_content_sized_lightburn_coupon(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "small_patches",
                     {**JOB, "patch_size_mm": 3, "max_width_mm": 20, "max_height_mm": 20})
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    assert made["summary"]["size_mm"] == {"width": 19, "height": 19}
    assert made["summary"]["sample_area_mm2"] == 9
    assert made["summary"]["clean_area_mm2"] < 19 * 19 / 2
    assert len(project.layers) == 3
    assert project.layer(0).name.startswith("CLEAN-")
    assert len(project.layer(0).regions) == 6  # one sample, four fiducials, one QR
    assert project.layer(1).name == "Markers and labels"
    assert len(project.layer(2).regions) == 1
    assert project.layer(2).regions[0].width == pytest.approx(3)
    assert project.layer(2).regions[0].height == pytest.approx(3)
    assert project.layer(2).power == 20
    assert plan["experiment"]["material"]["id"] == titanium["id"]


def test_markerless_small_patch_can_be_only_six_millimeters_square(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "small_patches",
                     {**JOB, "patch_size_mm": 3, "registration": "none", "max_width_mm": 6, "max_height_mm": 6})
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    assert made["summary"]["size_mm"] == {"width": 6, "height": 6}
    assert made["summary"]["clean_area_mm2"] == pytest.approx(12.96)
    assert made["summary"]["registration"] == "none"
    assert not plan["markers_enabled"]
    assert len(project.layers) == 2
    assert len(project.layer(0).regions) == 1
    assert project.layer(0).regions[0].width == pytest.approx(3.6)
    assert project.layer(1).regions[0].width == pytest.approx(3)
    with pytest.raises(su.ValidationError, match="занимает 6.0"):
        cp.preview(store, laser["id"], titanium["id"], "small_patches",
                   {**JOB, "patch_size_mm": 3, "registration": "none", "max_width_mm": 5.9})


def test_four_small_patches_preserve_distinct_settings_and_reject_too_small_limit(store):
    laser, _, titanium = hardware(store)
    settings = {"patch_size_mm": 5, "patches": [{"power": n} for n in (10, 20, 50, 100)],
                "max_width_mm": 25, "max_height_mm": 25}
    made = cp.create(store, laser["id"], titanium["id"], "small_patches", {**JOB, **settings})
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    assert made["summary"]["size_mm"] == {"width": 22.8, "height": 22.8}
    assert made["summary"]["sample_area_mm2"] == 100
    assert made["summary"]["clean_area_mm2"] < 250
    assert len(project.layers) == 6
    assert [layer.power for layer in project.layers[2:]] == [10, 20, 50, 100]
    assert all(len(layer.regions) == 1 and layer.regions[0].width == pytest.approx(5)
               for layer in project.layers[2:])
    with pytest.raises(su.ValidationError, match="занимает 22.8"):
        cp.preview(store, laser["id"], titanium["id"], "small_patches",
                   {**JOB, **settings, "max_width_mm": 20})


def test_small_patches_keep_each_complete_laser_setting_in_lightburn(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "small_patches", {**JOB, 
        "registration": "none", "patch_size_mm": 3,
        "patches": [
            {"power": 10, "frequency": 48, "speed": 500, "pulse_width": 200,
             "line_interval": 0.025, "passes": 1, "global_passes": 1},
            {"power": 50, "frequency": 60, "speed": 1500, "pulse_width": 250,
             "line_interval": 0.05, "passes": 3, "global_passes": 2},
        ]})
    project = lightburn.parse_bytes(plans.export_lbrn2(plans.get_plan(store, made["plan_id"])))
    assert len(project.layers) == 3
    assert [(x.power, x.frequency_khz, x.speed, x.pulse_width, x.line_interval,
             x.passes, x.global_passes) for x in project.layers[1:]] == [
                 (10, 48, 500, 200, 0.025, 1, 1),
                 (50, 60, 1500, 250, 0.05, 3, 2)]


def test_small_patches_split_into_two_independent_files_when_rectangular_limit_requires_it(store):
    laser, _, titanium = hardware(store)
    settings = {"patch_size_mm": 5, "patches": [{"power": n} for n in (10, 20, 50, 100)],
                "max_width_mm": 19, "max_height_mm": 23}
    previewed = cp.preview_small_patch_parts(store, laser["id"], titanium["id"], {**JOB, **settings})
    assert [p["sample_indexes"] for p in previewed] == [[1, 2], [3, 4]]
    assert all(p["prepared"]["experiment"]["summary"]["size_mm"] == {"width": 19, "height": 22.8}
               for p in previewed)
    made = cp.create_small_patch_parts(store, laser["id"], titanium["id"], {**JOB, **settings})
    assert len(made["parts"]) == 2
    assert made["parts"][0]["identifier"] != made["parts"][1]["identifier"]
    for index, part in enumerate(made["parts"], 1):
        plan = plans.get_plan(store, part["plan_id"])
        project = lightburn.parse_bytes(plans.export_lbrn2(plan))
        assert plan["experiment"]["series"] == {
            "identifier": made["series_identifier"], "part_index": index, "part_count": 2}
        assert part["sample_indexes"] == ([1, 2] if index == 1 else [3, 4])
        assert len(project.layers) == 4
        assert len(project.layer(0).regions) == 7
        assert [layer.power for layer in project.layers[2:]] == ([10, 20] if index == 1 else [50, 100])
    before = len(store.query("SELECT id FROM plan"))
    with pytest.raises(su.ValidationError, match="занимает"):
        cp.create_small_patch_parts(store, laser["id"], titanium["id"], {**JOB, **settings, "max_width_mm": 18})
    assert len(store.query("SELECT id FROM plan")) == before


def test_power_speed_test_probes_distinct_power_and_speed_values_as_vector_lines(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "power_speed", JOB)
    plan = plans.get_plan(store, made["plan_id"])
    exported = lightburn.parse_bytes(plans.export_lbrn2(plan))
    lines = [layer for layer in exported.layers if layer.layer_type == "Cut"]
    assert len(lines) == 28
    assert {layer.power for layer in lines} == {5, 20, 50, 100}
    assert {layer.speed for layer in lines} == {500, 1000, 1500, 3000, 5000, 7500, 10000}
    assert all(len(layer.regions) == 1 and layer.regions[0].height == 0 for layer in lines)


def test_material_test_matrix_varies_two_chosen_axes_and_keeps_other_settings_fixed(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "material_matrix", {**JOB, 
        "power": 30, "frequency": 48, "speed": 900, "pulse_width": 200,
        "line_interval": 0.025, "passes": 2, "global_passes": 1,
        "matrix": {"x_axis": "power", "y_axis": "speed", "x_min": 10, "x_max": 90, "x_count": 5,
                   "y_min": 500, "y_max": 9000, "y_count": 5, "geometry": "line"},
    })
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    matrix = [layer for layer in project.layers if layer.name.startswith("MATRIX-")]

    assert len(matrix) == 25 and len(project.layers) == 27
    assert {layer.power for layer in matrix} == {10, 30, 50, 70, 90}
    assert {layer.speed for layer in matrix} == {500, 2625, 4750, 6875, 9000}
    assert {layer.frequency_khz for layer in matrix} == {48}
    assert {layer.pulse_width for layer in matrix} == {200}
    assert {layer.line_interval for layer in matrix} == {None}  # line mode does not consume fill interval
    assert {layer.passes for layer in matrix} == {2}
    assert all(layer.layer_type == "Cut" and len(layer.regions) == 1 and layer.regions[0].height == 0 for layer in matrix)
    assert made["summary"]["size_mm"]["width"] <= 100 and made["summary"]["size_mm"]["height"] <= 100
    assert plan["experiment"]["test_settings"]["matrix"]["x_axis"] == "power"
    assert plan["experiment"]["test_settings"]["matrix"]["y_axis"] == "speed"
    assert made["summary"]["size_mm"]["width"] < 65 and made["summary"]["size_mm"]["height"] < 65
    assert plan["markers"]["settings"]["aruco_mm"] == 4.0
    assert plan["markers"]["qr"]["y"] < 0
    assert plan["markers"]["qr"]["x"] >= 0
    assert plan["markers"]["qr"]["x"] + plan["markers"]["qr"]["size"] < plan["markers"]["extent"]["max_x"]
    assert project.layer(0).regions[0].width == pytest.approx(made["summary"]["size_mm"]["width"])
    assert project.layer(0).regions[0].height == pytest.approx(made["summary"]["size_mm"]["height"])


def test_material_matrix_can_compare_speed_and_frequency_on_actual_letters(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "material_matrix", {**JOB, 
        "power": 60, "pulse_width": 200, "line_interval": 0.025,
        "matrix": {"x_axis": "speed", "y_axis": "frequency", "geometry": "text",
                   "x_min": 500, "x_max": 2333.33, "x_count": 3,
                   "y_min": 105, "y_max": 262.5, "y_count": 2},
    })
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    text_layers = [layer for layer in project.layers if layer.name.startswith("TEXT-MATRIX-")]
    assert len(text_layers) == 6 and len(project.layers) == 8
    assert {layer.speed for layer in text_layers} == {500, 1416.665, 2333.33}
    assert {layer.frequency_khz for layer in text_layers} == {105, 262.5}
    assert all(layer.layer_type == "Scan" and len(layer.regions) > 3 for layer in text_layers)
    assert all(len(layer["measurement_groups"]) == 3 for layer in plan["layers"])
    assert project.layer(0).name.startswith("CLEAN-")
    assert made["summary"]["size_mm"]["width"] < 60
    assert made["summary"]["size_mm"]["height"] < 50


def test_vector_letter_matrix_sweeps_speed_and_wobble_with_off_control(store):
    laser, _, titanium = hardware(store)
    settings = {
        "power": 60, "frequency": 262.5, "pulse_width": 200,
        "line_interval": 0.025, "passes": 1, "global_passes": 1,
        "matrix": {"x_axis": "speed", "y_axis": "wobble_size", "geometry": "vector_text",
                   "x_min": 500, "x_max": 2300, "x_count": 3,
                   "y_min": 0, "y_max": 0.08, "y_count": 3, "wobble_step": 0.02},
    }
    preview = cp.preview(store, laser["id"], titanium["id"], "material_matrix", {**JOB, **settings})
    assert preview["experiment"]["summary"]["size_mm"]["width"] < 100
    assert preview["experiment"]["summary"]["size_mm"]["height"] < 100
    made = cp.create(store, laser["id"], titanium["id"], "material_matrix", {**JOB, **settings})
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    layers = [layer for layer in project.layers if layer.name.startswith("TEXT-MATRIX-")]
    assert len(layers) == 9 and len(project.layers) == 11
    assert {layer.speed for layer in layers} == {500, 1400, 2300}
    assert {layer.power for layer in layers} == {60}
    assert {layer.frequency_khz for layer in layers} == {262.5}
    assert {layer.pulse_width for layer in layers} == {200}
    assert all(layer.layer_type == "Cut" and layer.line_interval is None for layer in layers)
    assert all(layer.passes == 1 and layer.global_passes == 1 for layer in layers)
    assert all(len(layer.regions) > 50 and all(r.kind == "path" and not r.closed for r in layer.regions) for layer in layers)
    assert {float(layer.source_settings["wobbleSize"]["Value"]) for layer in layers} == {0, 0.04, 0.08}
    assert all(layer.source_settings["wobbleEnable"]["Value"] ==
               ("0" if float(layer.source_settings["wobbleSize"]["Value"]) == 0 else "1") for layer in layers)
    assert all(float(layer.source_settings["wobbleStep"]["Value"]) == 0.02 for layer in layers)
    assert all(len(layer["measurement_groups"]) == 4 for layer in plan["layers"])
    def relative_strokes(layer):
        strokes = layer["regions"]
        origin_x, origin_y = strokes[0]["x1"], strokes[0]["y1"]
        return [(round(r["x1"] - origin_x, 5), round(r["y1"] - origin_y, 5),
                 round(r["x2"] - origin_x, 5), round(r["y2"] - origin_y, 5)) for r in strokes]
    assert all(relative_strokes(layer) == relative_strokes(plan["layers"][0]) for layer in plan["layers"])
    assert project.layer(0).name.startswith("CLEAN-")


def test_material_matrix_can_use_fill_patches_for_line_interval_and_pulse_axes(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "material_matrix", {**JOB, 
        "matrix": {"x_axis": "line_interval", "y_axis": "pulse_width", "x_min": 0.01, "x_max": 0.2,
                   "x_count": 4, "y_min": 50, "y_max": 500, "y_count": 5, "geometry": "fill"},
    })
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    matrix = [layer for layer in project.layers if layer.name.startswith("MATRIX-")]
    assert len(matrix) == 20 and all(layer.layer_type == "Scan" for layer in matrix)
    assert {layer.line_interval for layer in matrix} == {0.01, 0.0733, 0.1367, 0.2}
    assert {layer.pulse_width for layer in matrix} == {60, 100, 200, 250, 500}
    assert all(layer.regions[0].width == pytest.approx(5.1) and layer.regions[0].height == pytest.approx(5.1) for layer in matrix)


def test_material_matrix_can_sweep_frequency_and_pass_count_axes(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "material_matrix", {**JOB, 
        "matrix": {"x_axis": "frequency", "y_axis": "passes", "x_min": 24, "x_max": 96,
                   "x_count": 4, "y_min": 1, "y_max": 5, "y_count": 5, "geometry": "line"},
    })
    project = lightburn.parse_bytes(plans.export_lbrn2(plans.get_plan(store, made["plan_id"])))
    matrix = [layer for layer in project.layers if layer.name.startswith("MATRIX-")]
    assert len(matrix) == 20
    assert {layer.frequency_khz for layer in matrix} == {24, 48, 72, 96}
    assert {layer.passes for layer in matrix} == {1, 2, 3, 4, 5}
    assert {layer.power for layer in matrix} == {20}
    assert {layer.speed for layer in matrix} == {900}


def test_new_lightburn_export_preserves_fractional_speed_precision(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "material_matrix", {**JOB, 
        "matrix": {"x_axis": "speed", "y_axis": "frequency", "x_min": 500, "x_max": 6000,
                   "x_count": 4, "y_min": 105, "y_max": 420, "y_count": 3, "geometry": "fill"}})
    file = plans.export_lbrn2(plans.get_plan(store, made["plan_id"]))
    assert b'<speed Value="2333.3333"/>' in file
    assert b'<speed Value="4166.6667"/>' in file


def compact_registration(store) -> tuple[dict, np.ndarray]:
    """A material matrix preview and its compact registration (four ArUco markers and the QR) drawn at 30 px/mm."""
    laser, _, titanium = hardware(store)
    preview = cp.preview(store, laser["id"], titanium["id"], "material_matrix", JOB)
    markers = preview["markers"]
    extent = markers["extent"]
    scale, pad = 30, 2
    image = np.full((round((extent["max_y"] - extent["min_y"] + 2 * pad) * scale),
                     round((extent["max_x"] - extent["min_x"] + 2 * pad) * scale)), 255, np.uint8)
    rects = [r for marker in markers["aruco"] for r in marker["rects"]] + markers["qr"]["rects"]
    for r in rects:
        x0, y0 = round((r["x"] - extent["min_x"] + pad) * scale), round((r["y"] - extent["min_y"] + pad) * scale)
        x1, y1 = round((r["x"] + r["width"] - extent["min_x"] + pad) * scale), round((r["y"] + r["height"] - extent["min_y"] + pad) * scale)
        image[y0:y1, x0:x1] = 0
    return preview, image


def test_compact_registration_still_decodes_all_corners_and_qr(store):
    preview, image = compact_registration(store)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    _, ids, _ = detector.detectMarkers(image)
    assert sorted(ids.ravel().tolist()) == [0, 1, 2, 3]
    assert photo.read_identifier(image) == preview["identifier"]       # read as the photograph check reads it


# Identifiers (out of 1000 random ones) whose compact registration OpenCV's classic QR detector could not read as drawn
# above; the reader tries further views and the ArUco-based detector.
QR_THE_CLASSIC_DETECTOR_MISSED = ["TCE-000E05D0", "TCE-0F5E378F", "TCE-11CB4EA7", "TCE-328BF8AE", "TCE-5A091FD6",
                                  "TCE-5FE2FE3E", "TCE-839890CD", "TCE-AEFC1636", "TCE-F5EE8C72"]


@pytest.mark.parametrize("identifier", QR_THE_CLASSIC_DETECTOR_MISSED)
def test_a_compact_registration_whose_qr_the_classic_detector_misses_is_still_read(store, monkeypatch, identifier):
    monkeypatch.setattr(plans, "new_identifier", lambda prefix="TCE": identifier)
    preview, image = compact_registration(store)
    assert preview["identifier"] == identifier
    assert photo.read_identifier(image) == identifier


def test_material_matrix_rejects_interval_axis_for_vector_lines_and_more_than_28_cells(store):
    laser, _, titanium = hardware(store)
    from titanium_platform.setup import ValidationError
    with pytest.raises(ValidationError, match="только на залитых"):
        cp.preview(store, laser["id"], titanium["id"], "material_matrix", {**JOB, 
            "matrix": {"x_axis": "line_interval", "y_axis": "speed", "geometry": "line"}})
    with pytest.raises(ValidationError, match="не более 28 ячеек"):
        cp.preview(store, laser["id"], titanium["id"], "material_matrix", {**JOB, 
            "matrix": {"x_axis": "power", "y_axis": "speed", "x_count": 7, "y_count": 5}})


def test_maximum_material_matrix_fits_registered_plate_within_100mm(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "material_matrix", {**JOB, 
        "matrix": {"x_axis": "power", "y_axis": "speed", "x_count": 7, "y_count": 4}})
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    assert len([layer for layer in project.layers if layer.name.startswith("MATRIX-")]) == 28
    assert len(project.layers) == 30 and max(layer.index for layer in project.layers) == 29
    assert made["summary"]["size_mm"]["width"] <= 100
    assert made["summary"]["size_mm"]["height"] <= 100


def test_offset_fill_probes_speed_and_line_interval_in_offsetfill_mode(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "offset_fill", JOB)
    project = lightburn.parse_bytes(plans.export_lbrn2(plans.get_plan(store, made["plan_id"])))
    layers = [layer for layer in project.layers if layer.layer_type == "OffsetFill"]
    assert len(layers) == 12
    assert {layer.speed for layer in layers} == {450, 900, 1800}
    assert {layer.line_interval for layer in layers} == {0.025, 0.05, 0.1, 0.2}
    assert all(layer.cross_hatch is False and layer.bidirectional is False for layer in layers)


def test_compact_coupon_contains_lines_resolution_hatch_wobble_and_text_with_recorded_parameters(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "compact_capability", JOB)
    plan = plans.get_plan(store, made["plan_id"])
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    layers = {layer.name: layer for layer in project.layers}

    assert made["summary"]["test_features"] == 28
    assert made["summary"]["visual_features"] == 41
    assert len(project.layers) == 30  # two system layers + 28 test-setting layers; never T1/T2
    assert made["summary"]["size_mm"]["width"] < 75
    assert made["summary"]["size_mm"]["height"] < 80
    assert len([n for n in layers if n.startswith("LINE-P") and "GAP" not in n]) == 16
    assert len([n for n in layers if n.startswith("LINE-GAP-")]) == 1
    assert len(layers["LINE-GAP-20-300UM"].regions) == 50
    assert len(plan["layers"][16]["measurement_groups"]) == 10
    frequency = [layer for name, layer in layers.items() if name.startswith("FREQUENCY-")]
    assert len(frequency) == 4
    assert {layer.pulse_width for layer in frequency} == {1.0}  # JPT M7 CW step isolates repetition-rate coverage
    assert len([n for n in layers if n.startswith("HATCH-")]) == 3
    assert len([n for n in layers if n.startswith("TEXT-")]) == 1
    assert len(plan["layers"][-1]["measurement_groups"]) == 5
    wobble = [layer for name, layer in layers.items() if name.startswith("WOBBLE-")]
    assert len(wobble) == 3
    assert {layer.source_settings["wobbleEnable"]["Value"] for layer in wobble} == {"1"}
    assert {float(layer.source_settings["wobbleStep"]["Value"]) for layer in wobble} == set(cp.WOBBLE_STEPS_MM)
    assert {float(layer.source_settings["wobbleSize"]["Value"]) for layer in wobble} == set(cp.WOBBLE_SIZES_MM)
    assert all(not layer.source_settings.get("wobbleEnable", {}).get("Value", "0") == "1"
               for name, layer in layers.items() if not name.startswith("WOBBLE-"))


def test_standalone_wobble_coupon_exports_step_and_size_to_lightburn(store):
    laser, _, titanium = hardware(store)
    made = cp.create(store, laser["id"], titanium["id"], "wobble", JOB)
    project = lightburn.parse_bytes(plans.export_lbrn2(plans.get_plan(store, made["plan_id"])))
    wobble = [layer for layer in project.layers if layer.name.startswith("WOBBLE-")]
    assert len(wobble) == 9
    assert all(layer.source_settings["wobbleEnable"]["Value"] == "1" for layer in wobble)


def test_api_creates_a_hardware_and_titanium_linked_plan_that_downloads_from_the_plan_page(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        laser = client.post("/api/devices/from-template", json={
            "template": "jpt-ydflp-e-60-m7-m-r", "name": "JPT M7", "serial": "API-CAP-1"}).json()
        lens = client.post("/api/lenses", json={"name": "F-Theta", "focal_length_mm": 174, "field_mm": 170}).json()
        client.put(f"/api/devices/{laser['id']}/lens", json={"lens_id": lens["id"]})
        client.put("/api/marker-layer", json={"power": 25, "frequency": 60, "speed": 150, "pulse_width": 200, "line_interval": 0.01, "passes": 1})
        titanium = client.post("/api/materials", json={"name": "Grade 2", "grade": "Grade 2", "batch": "API-17"}).json()
        created = client.post("/api/capability-plates", json={"device_id": laser["id"], "material_id": titanium["id"], "pulse_width": 200, "test_type": "pulse_cutoff"})
        assert created.status_code == 201
        plan = client.get(f"/api/plans/{created.json()['plan_id']}").json()
        assert plan["experiment"]["device"]["serial"] == "API-CAP-1"
        assert plan["experiment"]["lens"]["name"] == "F-Theta"
        assert plan["experiment"]["material"]["batch"] == "API-17"
        assert plan["test_type"] == "pulse_cutoff"
        download = client.get(f"/api/plans/{plan['id']}/export.lbrn2")
        assert download.status_code == 200 and b"CLEAN-CROSSHATCH" in download.content
        listed = client.get("/api/plans").json()
        assert listed[0]["experiment"]["material"]["batch"] == "API-17"


def test_api_accepts_material_test_axis_choices_and_returns_ready_lbrn2(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        laser = client.post("/api/devices/from-template", json={
            "template": "jpt-ydflp-e-60-m7-m-r", "name": "JPT M7", "serial": "API-MATRIX"}).json()
        lens = client.post("/api/lenses", json={"name": "F-Theta", "focal_length_mm": 174, "field_mm": 170}).json()
        client.put(f"/api/devices/{laser['id']}/lens", json={"lens_id": lens["id"]})
        client.put("/api/marker-layer", json={"power": 25, "frequency": 60, "speed": 150, "pulse_width": 200, "line_interval": 0.01, "passes": 1})
        titanium = client.post("/api/materials", json={"name": "Grade 2", "grade": "Grade 2", "batch": "MATRIX-1"}).json()
        created = client.post("/api/capability-plates", json={"device_id": laser["id"], "material_id": titanium["id"], "pulse_width": 200,
            "test_type": "material_matrix", "matrix": {"x_axis": "power", "y_axis": "frequency", "x_min": 10,
                "x_max": 90, "x_count": 4, "y_min": 24, "y_max": 96, "y_count": 5, "geometry": "line"}})
        assert created.status_code == 201
        body = created.json()
        plan = client.get(f"/api/plans/{body['plan_id']}").json()
        assert body["summary"]["layers"] == 20
        assert plan["experiment"]["test_settings"]["matrix"]["x_axis"] == "power"
        download = client.get(f"/api/plans/{body['plan_id']}/export.lbrn2")
        project = lightburn.parse_bytes(download.content)
        assert len(project.layers) == 22 and max(x.index for x in project.layers) == 21
        assert project.layer(0).name.startswith("CLEAN-")


def test_api_previews_small_coupon_without_creating_plan_then_exports_it(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        laser = client.post("/api/devices/from-template", json={
            "template": "jpt-ydflp-e-60-m7-m-r", "name": "JPT M7", "serial": "API-PATCH"}).json()
        lens = client.post("/api/lenses", json={"name": "F-Theta", "focal_length_mm": 174, "field_mm": 170}).json()
        client.put(f"/api/devices/{laser['id']}/lens", json={"lens_id": lens["id"]})
        client.put("/api/marker-layer", json={"power": 25, "frequency": 60, "speed": 150, "pulse_width": 200, "line_interval": 0.01, "passes": 1})
        titanium = client.post("/api/materials", json={"name": "Grade 2", "grade": "Grade 2", "batch": "PATCH-1"}).json()
        request = {"device_id": laser["id"], "material_id": titanium["id"], "pulse_width": 200, "test_type": "small_patches",
                   "patch_size_mm": 3, "patches": [{"power": 10}, {"power": 50}],
                   "max_width_mm": 25, "max_height_mm": 25}
        before = len(client.get("/api/plans").json())
        preview = client.post("/api/capability-plates/preview", json=request)
        assert preview.status_code == 200
        assert preview.json()["summary"]["size_mm"]["width"] <= 25
        assert preview.json()["output_layers"] == 4
        assert len(client.get("/api/plans").json()) == before
        created = client.post("/api/capability-plates", json=request)
        assert created.status_code == 201
        project = lightburn.parse_bytes(client.get(f"/api/plans/{created.json()['plan_id']}/export.lbrn2").content)
        assert len(project.layers) == 4
        assert [layer.power for layer in project.layers[2:]] == [10, 50]


def test_api_returns_each_split_lightburn_file_and_previewed_size(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        laser = client.post("/api/devices/from-template", json={
            "template": "jpt-ydflp-e-60-m7-m-r", "name": "JPT M7", "serial": "API-SPLIT"}).json()
        lens = client.post("/api/lenses", json={"name": "F-Theta", "focal_length_mm": 174, "field_mm": 170}).json()
        client.put(f"/api/devices/{laser['id']}/lens", json={"lens_id": lens["id"]})
        client.put("/api/marker-layer", json={"power": 25, "frequency": 60, "speed": 150, "pulse_width": 200, "line_interval": 0.01, "passes": 1})
        titanium = client.post("/api/materials", json={"name": "Grade 2", "grade": "Grade 2", "batch": "SPLIT-1"}).json()
        request = {"device_id": laser["id"], "material_id": titanium["id"], "pulse_width": 200, "test_type": "small_patches",
                   "patch_size_mm": 5, "patches": [{"power": n} for n in (10, 20, 50, 100)],
                   "max_width_mm": 19, "max_height_mm": 23}
        preview = client.post("/api/capability-plates/preview", json=request)
        assert preview.status_code == 200
        assert [p["sample_indexes"] for p in preview.json()["parts"]] == [[1, 2], [3, 4]]
        created = client.post("/api/capability-plates", json=request)
        assert created.status_code == 201
        parts = created.json()["parts"]
        assert len(parts) == 2
        for part in parts:
            downloaded = client.get(part["download_url"])
            assert downloaded.status_code == 200
            assert b"CLEAN-CROSSHATCH" in downloaded.content
            assert part["summary"]["size_mm"] == {"width": 19, "height": 22.8}


def test_api_exports_minimal_markerless_coupon_requested_by_ui(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        laser = client.post("/api/devices/from-template", json={
            "template": "jpt-ydflp-e-60-m7-m-r", "name": "JPT M7", "serial": "API-MINI"}).json()
        lens = client.post("/api/lenses", json={"name": "F-Theta", "focal_length_mm": 174, "field_mm": 170}).json()
        client.put(f"/api/devices/{laser['id']}/lens", json={"lens_id": lens["id"]})
        client.put("/api/marker-layer", json={"power": 25, "frequency": 60, "speed": 150, "pulse_width": 200, "line_interval": 0.01, "passes": 1})
        titanium = client.post("/api/materials", json={"name": "Grade 2", "grade": "Grade 2"}).json()
        request = {"device_id": laser["id"], "material_id": titanium["id"], "pulse_width": 200, "test_type": "small_patches",
                   "patch_size_mm": 3, "patches": [{}], "registration": "none",
                   "max_width_mm": 6, "max_height_mm": 6}
        preview = client.post("/api/capability-plates/preview", json=request)
        assert preview.status_code == 200
        assert preview.json()["summary"]["size_mm"] == {"width": 6, "height": 6}
        assert preview.json()["output_layers"] == 2
        created = client.post("/api/capability-plates", json=request)
        assert created.status_code == 201
        assert len(created.json()["parts"]) == 1
        project = lightburn.parse_bytes(client.get(created.json()["parts"][0]["download_url"]).content)
        assert len(project.layers) == 2
        assert project.layer(0).name.startswith("CLEAN-")


def test_a_capability_plate_has_no_default_pulse_width(store):
    """DEC-043: the pulse width of a test plate is the operator's (or the AI's) explicit choice, never filled in."""
    laser, _, titanium = hardware(store)
    with pytest.raises(su.ValidationError, match="выберите длительность импульса"):
        cp.preview(store, laser["id"], titanium["id"], "calibration")
    assert "pulse_width" not in cp.DEFAULT_TEST


def test_the_lightburn_notes_name_a_lens_whose_focal_length_is_unknown(store):
    laser, _, titanium = hardware(store)
    unmarked = lenses.create_lens(store, "Unmarked F-theta")
    lenses.install(store, laser["id"], unmarked["id"])
    made = cp.create(store, laser["id"], titanium["id"], "calibration", JOB)
    notes = plans.export_lbrn2(plans.get_plan(store, made["plan_id"])).decode("utf-8")
    assert "Lens: Unmarked F-theta, focal length unknown" in notes and "Lens: Unmarked F-theta  mm" not in notes
