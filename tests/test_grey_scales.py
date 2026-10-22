"""Grey scales (REQ-059): the grey-ramp plate, its Image layers in LightBurn, each step measured at its power, and the scale it makes."""
import re
import struct
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import synth
from titanium_platform import engraving_time as et, capability_plates as cp, color, devices, grayscale, ingest as ig, lenses, lightburn, plans
from titanium_platform import prediction_store as ps, setup as su
from titanium_platform.api.app import create_app

SETTINGS = {"pulse_width": 300, "power": 40, "speed": 150, "frequency": 60, "line_interval": 0.0169}
SMALL = {"rows": {"axis": "line_interval", "values": [0.0169, 0.0254]}, "columns": {"axis": "speed", "values": [150, 250]}, "min_power": 2}
# a scale that passes gold, violet and blue: its lightness does not follow the grey, as on titanium
HUES = [(205, 190, 150), (210, 180, 110), (200, 160, 90), (180, 120, 110), (150, 90, 150), (110, 90, 170), (80, 110, 190), (70, 130, 200)]


@pytest.fixture
def world(store):
    store.set_setting("allow_non_raw_photos", True)              # tests use PNG renders; real use requires RAW
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="GREY-01")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    stand = su.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    titanium = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)
    return {"store": store, "laser": laser, "lens": lens, "stand": stand, "titanium": titanium}


def step_colour(grey: float) -> tuple[int, int, int]:
    return HUES[min(len(HUES) - 1, int((1 - grey) * len(HUES)))]


def test_the_plate_is_one_image_layer_per_tile_with_a_ramp_from_white_to_black(world):
    made = cp.create(world["store"], world["laser"]["id"], world["titanium"]["id"], "grey_scales", SETTINGS)
    plan = plans.get_plan(world["store"], made["plan_id"])
    tiles = [layer for layer in plan["layers"] if layer.get("ramp")]
    assert len(tiles) == 12 and made["summary"]["size_mm"]["width"] <= 100
    assert {(t["parameters"]["line_interval"], t["parameters"]["speed"]) for t in tiles} == {
        (i, v) for i in (0.0127, 0.0169, 0.0212, 0.0254) for v in (100.0, 150.0, 250.0)}
    project = lightburn.parse_bytes(plans.export_lbrn2(plan))
    images = [layer for layer in project.layers if layer.layer_type == "Image"]
    assert len(images) == 12 and all(layer.unknown_settings == [] and not layer.unsupported for layer in project.layers)
    first = next(layer for layer in images if layer.name == "GREY-I0.0169-V150")
    summary = first.image_summary()
    assert (first.power, first.speed, first.line_interval, summary["min_power"], summary["dpi"]) == (40, 150, 0.0169, 1, 1503)
    (region,) = first.regions
    grey = cv2.imdecode(np.frombuffer(region.bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)
    assert grey.ndim == 2 and grey[0, 0] == 255 and grey[0, -1] == 0          # white at the left, black at the right
    assert sorted(set(grey[0].tolist())) == [round(255 * g) for g in sorted(grayscale.ramp_greys())]


def test_settings_the_laser_cannot_engrave_and_too_many_tiles_are_refused(world):
    s, laser, ti = world["store"], world["laser"]["id"], world["titanium"]["id"]
    with pytest.raises(su.ValidationError, match="частота"):
        cp.preview(s, laser, ti, "grey_scales", {**SETTINGS, "scales": {"columns": {"axis": "frequency", "values": [5000]}}})
    with pytest.raises(su.ValidationError, match="не больше 7 строк и 4 столбцов"):
        cp.preview(s, laser, ti, "grey_scales", {**SETTINGS, "scales": {"rows": {"axis": "line_interval", "values": [0.01 + k / 1000 for k in range(8)]}}})
    with pytest.raises(su.ValidationError, match="разные параметры"):
        cp.preview(s, laser, ti, "grey_scales", {**SETTINGS, "scales": {"rows": {"axis": "speed", "values": [100, 200]}}})
    with pytest.raises(su.ValidationError, match="Min меньше Max"):
        cp.preview(s, laser, ti, "grey_scales", {**SETTINGS, "scales": {"min_power": 50}})


# -- the ramp width as an axis: how a colour depends on the length of the scan line -------------------------------------------------
WIDTHS = {"rows": {"axis": "width", "values": [20, 40, 70, 100, 140]}, "columns": {"axis": "speed", "values": [150]}, "min_power": 2}


def test_a_width_axis_gives_each_ramp_its_own_width_and_a_column_the_width_of_its_widest_ramp(world):
    """The same settings on ramps 20 to 140 mm wide: each ramp's 16 steps are a sixteenth of its width; the ramps start at their
    column's left edge."""
    made = cp.create(world["store"], world["laser"]["id"], world["titanium"]["id"], "grey_scales", {**SETTINGS, "scales": WIDTHS, "max_width_mm": 170})
    plan = plans.get_plan(world["store"], made["plan_id"])
    tiles = [layer for layer in plan["layers"] if layer.get("ramp")]
    assert [t["name"] for t in tiles] == ["GREY-W20-V150", "GREY-W40-V150", "GREY-W70-V150", "GREY-W100-V150", "GREY-W140-V150"]
    assert [t["ramp"]["width"] for t in tiles] == [20, 40, 70, 100, 140] and {t["ramp"]["x"] for t in tiles} == {cp.GREY_LABEL_WIDTH}
    assert all(t["parameters"] == {"power": 40, "min_power": 2, "speed": 150, "frequency": 60, "pulse_width": 300, "line_interval": 0.0169,
                                   "passes": 1} for t in tiles)
    assert made["summary"]["size_mm"]["width"] == pytest.approx(cp.GREY_LABEL_WIDTH + 140 + 1 + 9)       # labels, widest ramp, markers
    assert plan["experiment"]["test_settings"]["scales"] == {
        "rows": {"axis": "width", "values": [20, 40, 70, 100, 140]}, "columns": {"axis": "speed", "values": [150]},
        "min_power": 2, "max_power": 40, "steps": 16, "step_mm": 1.25, "dither": "grayscale"}
    images = [layer for layer in lightburn.parse_bytes(plans.export_lbrn2(plan)).layers if layer.layer_type == "Image"]
    for layer, wanted in zip(images, (20, 40, 70, 100, 140)):
        (region,) = layer.regions
        xs = [p[0] for p in region.polygon]
        grey = cv2.imdecode(np.frombuffer(region.bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)
        assert max(xs) - min(xs) == pytest.approx(wanted, abs=1e-3) and grey[0, 0] == 255 and grey[0, -1] == 0
    # widths on the columns: the next column starts after the widest ramp of the one before
    across = cp.preview(world["store"], world["laser"]["id"], world["titanium"]["id"], "grey_scales",
                        {**SETTINGS, "scales": {"rows": {"axis": "speed", "values": [100, 150]}, "columns": {"axis": "width", "values": [20, 40]}}})
    assert [(c["name"], c["x"], c["width"]) for c in across["geometry"]["cells"]] == [
        ("GREY-V100-W20", 9, 20), ("GREY-V100-W40", 31, 40), ("GREY-V150-W20", 9, 20), ("GREY-V150-W40", 31, 40)]
    assert across["geometry"]["width"] == 9 + 20 + 2 + 40 + 1


def test_a_ramp_too_narrow_for_its_steps_a_width_by_factors_and_a_plate_beyond_its_limit_are_refused(world):
    s, laser, ti = world["store"], world["laser"]["id"], world["titanium"]["id"]
    with pytest.raises(su.ValidationError, match="шириной 15 мм даёт ступень 0.9375 мм.*не меньше 16 мм"):
        cp.preview(s, laser, ti, "grey_scales", {**SETTINGS, "scales": {"rows": {"axis": "width", "values": [15, 40]}}})
    with pytest.raises(su.ValidationError, match="ширина полоски задаётся значениями в мм"):
        cp.preview(s, laser, ti, "grey_scales", {**SETTINGS, "scales": {"columns": {"axis": "width", "factors": [1, 2]}}})
    with pytest.raises(su.ValidationError, match="занимает 159.0 × 46.0 мм; заданный предел — 100 × 100 мм"):
        cp.preview(s, laser, ti, "grey_scales", {**SETTINGS, "scales": WIDTHS})


def test_a_photo_work_orders_one_ramp_of_its_own_width_at_its_own_settings(world):
    """How a photo work orders a ramp from code: its base settings, one width and one speed, its Min and Max."""
    base = {"power": 35, "speed": 300, "frequency": 60, "pulse_width": 300, "line_interval": 0.0169, "passes": 1}
    settings = {**base, "max_width_mm": 150, "scales": {"rows": {"axis": "width", "values": [100]}, "columns": {"axis": "speed", "values": [300]},
                                                        "min_power": 3, "max_power": 35}}
    s, laser, ti = world["store"], world["laser"]["id"], world["titanium"]["id"]
    assert cp.preview(s, laser, ti, "grey_scales", settings)["experiment"]["summary"]["layers"] == 1
    made = cp.create(s, laser, ti, "grey_scales", settings)
    (tile,) = [layer for layer in plans.get_plan(s, made["plan_id"])["layers"] if layer.get("ramp")]
    assert (tile["name"], tile["ramp"]["width"], tile["ramp"]["height"]) == ("GREY-W100-V300", 100, cp.GREY_TILE_HEIGHT)
    assert tile["parameters"] == {**base, "min_power": 3}
    (image,) = [layer for layer in lightburn.parse_bytes(plans.export_lbrn2(plans.get_plan(s, made["plan_id"]))).layers if layer.layer_type == "Image"]
    assert (image.power, image.image_summary()["min_power"], image.speed, image.line_interval) == (35, 3, 300, 0.0169)


def test_ramps_of_different_widths_are_each_measured_step_by_step(world):
    s = world["store"]
    scales = {"rows": {"axis": "width", "values": [20, 40]}, "columns": {"axis": "speed", "values": [150, 250]}, "min_power": 2}
    made = cp.create(s, world["laser"]["id"], world["titanium"]["id"], "grey_scales", {**SETTINGS, "scales": scales, "max_width_mm": 110})
    plan = plans.get_plan(s, made["plan_id"])
    photo = synth.plate_photo(plan, {}, size=(1300, 2700), step_rgb=lambda name, grey: step_colour(grey))
    pid = ig.create_pair(s, device_id=world["laser"]["id"], lens_id=world["lens"]["id"], stand_id=world["stand"]["id"],
                         lightburn_name="widths.lbrn2", lightburn_bytes=plans.export_lbrn2(plan), photo_name="widths.png",
                         context={"material_id": world["titanium"]["id"]}, photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    report = ig.check_pair(s, pid)
    assert report["problems"] == [], report["problems"]
    tiles = {rep["name"]: rep for rep in report["layers"] if rep["name"].startswith("GREY-")}
    assert set(tiles) == {"GREY-W20-V150", "GREY-W20-V250", "GREY-W40-V150", "GREY-W40-V250"}
    for name, tile in tiles.items():
        tonal = tile["tonal"]
        assert len(tonal["bins"]) == 16 and tonal["steps_missed"] == 0 and tonal["power_range"] == [2.0, 40.0], name
        for step in tonal["bins"]:
            drawn = color.srgb8_to_lab(np.array([step_colour(step["gray"])], np.float64))[0]
            assert color.delta_e([step["L"], step["a"], step["b"]], drawn) < 3, (name, step)
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    sizes = {sc["mode"]["speed"]: [size["row_mm"] for size in sc["sizes"]] for sc in ps.scales(s)
             if sc["mode"]["line_interval"] == SETTINGS["line_interval"] and sc["mode"]["speed"] in (150, 250)}
    assert set(sizes) == {150, 250}, sizes                                # each speed's scale knows both widths of its ramps as sizes (DEC-107);
    for found in sizes.values():                                          # the module's other plates may have measured these settings too
        assert all(any(abs(mm / width - 1) <= 0.1 for mm in found) for width in (20, 40)), sizes


def test_a_photographed_plate_gives_each_tile_a_scale_with_every_step_at_its_power(world):
    s = world["store"]
    made = cp.create(s, world["laser"]["id"], world["titanium"]["id"], "grey_scales", {**SETTINGS, "scales": SMALL})
    plan = plans.get_plan(s, made["plan_id"])
    photo = synth.plate_photo(plan, {}, size=(1300, 2800), step_rgb=lambda name, grey: step_colour(grey))
    pid = ig.create_pair(s, device_id=world["laser"]["id"], lens_id=world["lens"]["id"], stand_id=world["stand"]["id"],
                         lightburn_name="grey.lbrn2", lightburn_bytes=plans.export_lbrn2(plan), photo_name="grey.png",
                         context={"material_id": world["titanium"]["id"]}, photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    report = ig.check_pair(s, pid)
    assert report["problems"] == [], report["problems"]
    tile = next(rep for rep in report["layers"] if rep["name"] == "GREY-I0.0169-V150")
    tonal = tile["tonal"]
    assert tonal["measured_by"] == "grey ramp" and tonal["evidence"] == "clear" and tonal["steps_missed"] == 0
    assert len(tonal["bins"]) == 16 and tonal["power_range"] == [2.0, 40.0]
    white = max(tonal["bins"], key=lambda b: b["gray"])
    black = min(tonal["bins"], key=lambda b: b["gray"])
    assert (white["gray"], white["power_pct"], black["gray"], black["power_pct"]) == (1.0, 2.0, 0.0, 40.0)
    for step in tonal["bins"]:                                          # each step is the colour drawn there, not a blend of its neighbours
        drawn = color.srgb8_to_lab(np.array([step_colour(step["gray"])], np.float64))[0]
        assert color.delta_e([step["L"], step["a"], step["b"]], drawn) < 3, step
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)

    modes = ps.scale_modes(s, world["laser"]["id"])
    assert len(modes) == 4
    mode = ps.mode_of({"speed": 150, "frequency": 60, "pulse_width": 300, "line_interval": 0.0169, "passes": 1, "global_passes": 1},
                      world["laser"]["id"], world["lens"]["id"], world["titanium"]["id"])
    curve, basis = ps.curve_for(s, mode)
    assert curve.span == (2.0, 40.0) and len(curve.points) == 16 and curve.referenced
    assert all(src["how"] == "grey ramp" for row in curve.points for src in row["sources"])
    # what the photograph showed at each step comes back as the colour of that grey at the plate's Min and Max
    detail = ps.scale(s, mode, 2, 40)
    by_level = {row["level"]: row for row in detail["greys"]["levels"]}
    for grey in (1.0, 0.0):
        assert by_level[round(255 * grey)]["lab"] == pytest.approx(curve.lab_at(2 + 38 * (1 - grey)).tolist(), abs=0.01)
    hexes = [by_level[l]["hex"] for l in (255, 128, 0)]
    assert len(set(hexes)) == 3                                         # gold, violet and blue: one power, one colour each
    assert [sc["mode"]["line_interval"] for sc in ps.scales(s, world["laser"]["id"])] == [0.0169, 0.0169, 0.0254, 0.0254]


def saved_by_lightburn_2_2(plan) -> bytes:
    """The plate as LightBurn 2.2 saved the operator's: MirrorY rewritten with every XForm reflected over the work's height, and a picture
    placed twice stored once (the later Bitmap keeps only the first one's SourceHash, under its own file name)."""
    root = ET.fromstring(plans.export_lbrn2(plan))
    assert root.get("MirrorY") == "True"
    height = plan["markers"]["extent"]["max_y"] - plan["markers"]["extent"]["min_y"]
    root.set("MirrorY", "False")
    for shape in root.findall(".//Shape"):
        xform = shape.find("XForm")
        if xform is not None:
            a, b, c, d, e, f = (float(value) for value in xform.text.split())
            xform.text = " ".join(str(value) for value in (a, -b, c, -d, e, height - f))
    hashes: dict[str, int] = {}
    for shape in root.findall(".//Shape[@Type='Bitmap']"):
        data = shape.get("Data")
        stored = data in hashes
        shape.set("SourceHash", str(hashes.setdefault(data, len(hashes))))
        if stored:
            shape.set("Data", "")
    return ET.tostring(root)


def test_a_plate_saved_again_by_lightburn_is_measured_tile_by_tile_with_every_step(world):
    """The operator's plate came back from LightBurn 2.2 reflected in its axes and with each row's ramp stored once: three of the four tiles
    at 250 ns read "0 pixels" (what a picture strikes was laid mirrored about the plate's centre) and the 350 ns tiles had no picture (DEC-103)."""
    s = world["store"]
    made = cp.create(s, world["laser"]["id"], world["titanium"]["id"], "grey_scales", {**SETTINGS, "scales": SMALL})
    plan = plans.get_plan(s, made["plan_id"])
    saved = saved_by_lightburn_2_2(plan)
    assert saved.count(b'Data=""') == 2                                 # each row's two tiles hold one ramp
    photo = synth.plate_photo(plan, {}, size=(1300, 2800), step_rgb=lambda name, grey: step_colour(grey))
    pid = ig.create_pair(s, device_id=world["laser"]["id"], lens_id=world["lens"]["id"], stand_id=world["stand"]["id"],
                         lightburn_name="grey.lbrn2", lightburn_bytes=saved, photo_name="grey.png",
                         context={"material_id": world["titanium"]["id"]}, photo_bytes=cv2.imencode(".png", photo)[1].tobytes())

    report = ig.check_pair(s, pid)

    assert report["problems"] == [] and report["project"]["normalized_axes"] == ["Y"]
    tiles = [rep for rep in report["layers"] if rep["name"].startswith("GREY-")]
    assert len(tiles) == 4
    for tile in tiles:
        tonal = tile.get("tonal") or {}
        assert tile["pixels"] and len(tonal.get("bins", [])) == 16 and tonal["steps_missed"] == 0, (tile["name"], tile["notes"])
        for step in tonal["bins"]:
            drawn = color.srgb8_to_lab(np.array([step_colour(step["gray"])], np.float64))[0]
            assert color.delta_e([step["L"], step["a"], step["b"]], drawn) < 3, (tile["name"], step)


# -- the picture writer: a picture the operator can open in LightBurn and engrave in grayscale mode ------------------------------
MODE_A = {"power": 30, "min_power": 1, "speed": 150, "frequency": 60, "pulse_width": 300, "line_interval": 0.0169}


def portrait(rows=200, cols=300) -> np.ndarray:
    picture = np.tile(np.linspace(0, 255, cols, dtype=np.float32), (rows, 1)).astype(np.uint8)
    picture[:20] = 255                                                   # a white band along the top edge: which way is up
    return picture


def test_a_picture_is_written_as_one_grayscale_image_layer_with_the_settings_lightburn_reads():
    data = plans.export_picture(portrait(), 50, MODE_A, name="Girl on a bike", clean=None)
    project = lightburn.parse_bytes(data)
    (layer,) = project.layers
    summary = layer.image_summary()
    assert (layer.layer_type, layer.name, layer.power, layer.speed, layer.frequency_khz, layer.pulse_width, layer.line_interval) == (
        "Image", "C00", 30, 150, 60, 300, 0.0169)
    assert (summary["dither"], summary["min_power"], summary["dpi"]) == ("grayscale", 1, 1503)
    assert layer.unknown_settings == [] and not layer.unsupported and b'MirrorY="False"' in data
    # the tags of the operator's own photo files, in their order (Motorcycle: LightBurn 1.7.01)
    order = ["index", "name", "minPower", "maxPower", "maxPower2", "speed", "frequency", "QPulseWidth", "interval", "priority",
             "tabCount", "tabCountMax", "ditherMode", "dpi"]
    written = [tag for tag in re.findall(rb"<(\w+) Value=", data.split(b"</CutSetting_Img>")[0])]
    assert [t.decode() for t in written if t.decode() in order] == order
    (region,) = layer.regions
    xs, ys = [p[0] for p in region.polygon], [p[1] for p in region.polygon]
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((50, 50 * 200 / 300), abs=1e-3)


def test_the_picture_is_stored_as_lightburn_stores_it_and_reads_back_upright():
    picture = portrait()
    (region,) = lightburn.parse_bytes(plans.export_picture(picture, 50, MODE_A, clean=None)).layer(0).regions
    png = region.bitmap["png"]
    stored = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert np.array_equal(stored, picture[::-1])                        # bottom row first, like the operator's Motorcycle file
    shown, upright = ps._upright(stored.astype(np.float32) / 255, region.bitmap["matrix"])
    assert upright and np.array_equal((shown * 255).round().astype(np.uint8), picture)
    per_metre = struct.unpack(">I", png[png.index(b"pHYs") + 4:png.index(b"pHYs") + 8])[0]
    assert per_metre * 0.0254 == pytest.approx(300 / 50 * 25.4, abs=0.1)  # its own DPI: LightBurn sizes it by the header


def test_a_picture_finer_than_the_layer_is_reduced_to_the_layers_dpi_and_a_coarser_one_keeps_its_pixels():
    fine = lightburn.parse_bytes(plans.export_picture(np.full((1000, 4000), 128, np.uint8), 20, MODE_A, clean=None)).layer(0).regions[0]
    stored = cv2.imdecode(np.frombuffer(fine.bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)
    assert stored.shape == (round(5 / 25.4 * 1503), round(20 / 25.4 * 1503))
    with pytest.raises(su.ValidationError, match="needs min_power"):
        plans.export_picture(portrait(), 50, {k: v for k, v in MODE_A.items() if k != "min_power"}, clean=None)


# the cleaning of a laser that reaches 48 kHz and has a 200 ns step (``plans.clean_layer``)
CLEAN = plans.clean_layer({"repetition_rate_khz": {"min": 1, "max": 4000}, "pulse_steps": [{"pulse_width_ns": 200}, {"pulse_width_ns": 350}]})


def test_a_picture_file_cleans_the_pictures_rectangle_first_and_engraves_the_picture_after_it():
    project = lightburn.parse_bytes(plans.export_picture(portrait(), 50, MODE_A, name="Girl on a bike", clean=CLEAN))
    clean, image = project.layer(0), project.layer(1)
    assert (clean.layer_type, clean.name, clean.power, clean.speed, clean.line_interval, clean.cross_hatch) == (
        "Scan", "CLEAN-CROSSHATCH-P20-F48-V2000-PW200-I0.05", 20, 2000, 0.05, True)
    assert clean.burn_order < image.burn_order                                  # the titanium is cleaned before the picture
    assert (image.layer_type, image.name, image.power, image.image_summary()["min_power"]) == ("Image", "C01", 30, 1)
    (frame,), (picture,) = clean.regions, image.regions
    xs, ys = [p[0] for p in frame.polygon], [p[1] for p in frame.polygon]
    assert frame.kind == "rect" and (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((0, 50, 0, 50 * 200 / 300), abs=1e-3)
    assert [p for p in picture.polygon] == pytest.approx([p for p in frame.polygon], abs=1e-3)     # over the picture's rectangle
    mode = ps.Mode(device_id=1, lens_id=None, material_id=None, speed=150, frequency=60, pulse_width=300, line_interval=0.0169, passes=1)
    assert ps.picture_time(mode, 50, 50 * 200 / 300, CLEAN)["seconds"] == pytest.approx(et.of_project(project)["seconds"], rel=1e-6)


# -- through the application: the scales, a picture on one, its time and its file -------------------------------------------------
@pytest.fixture(scope="module")
def app_world(tmp_path_factory):
    app = create_app(tmp_path_factory.mktemp("grey"))
    s = app.state.store
    s.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(s, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="GREY-02")
    lens = lenses.create_lens(s, "F-Theta", 174, 170)
    lenses.install(s, laser["id"], lens["id"])
    plans.save_marker_layer_settings(s, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    stand = su.save_capture_setup(s, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    titanium = su.save_material(s, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)
    made = cp.create(s, laser["id"], titanium["id"], "grey_scales", {**SETTINGS, "scales": SMALL})
    plan = plans.get_plan(s, made["plan_id"])
    photo = synth.plate_photo(plan, {}, size=(1300, 2800), step_rgb=lambda name, grey: step_colour(grey))
    pid = ig.create_pair(s, device_id=laser["id"], lens_id=lens["id"], stand_id=stand["id"], lightburn_name="grey.lbrn2",
                         lightburn_bytes=plans.export_lbrn2(plan), photo_name="grey.png", context={"material_id": titanium["id"]},
                         photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    assert ig.check_pair(s, pid)["problems"] == []
    ig.review_masks(s, pid)
    ig.accept_pair(s, pid)
    with TestClient(app) as client:
        yield {"client": client, "laser": laser, "lens": lens, "titanium": titanium,
               "mode": {"device_id": laser["id"], "lens_id": str(lens["id"]), "material_id": titanium["id"], "speed": 150, "frequency": 60,
                        "pulse_width": 300, "line_interval": 0.0169}}
    s.close()


def picture_png(rows=120, cols=240) -> bytes:
    return cv2.imencode(".png", np.tile(np.linspace(255, 0, cols), (rows, 1)).astype(np.uint8))[1].tobytes()


def test_the_scales_list_each_measured_mode_with_its_colours_its_kind_and_its_time(app_world):
    client = app_world["client"]
    scales = client.get("/api/grey-scales", params={"device_id": app_world["laser"]["id"]}).json()["scales"]
    assert len(scales) == 4
    one = next(sc for sc in scales if sc["mode"]["line_interval"] == 0.0169 and sc["mode"]["speed"] == 150)
    assert one["span"] == [2.0, 40.0] and one["by_kind"] == {"grey ramp": 1} and one["reference"] == "chart"
    assert one["dpi"] == 1503 and one["time_s_per_cm2"] == pytest.approx(100 / (150 * 0.0169) + 10 / 0.0169 * et.TURNAROUND_S, rel=1e-6)
    assert len({bar["hex"] for bar in one["bar"]}) > 4 and not one["confirmation"]["confirmed"]       # one plate confirms nothing yet
    detail = client.get("/api/grey-scales/scale", params={**app_world["mode"], "min_power": 2, "max_power": 40}).json()
    assert len(detail["greys"]["levels"]) == 256 and detail["greys"]["measured_levels"] == 256
    assert detail["curve"]["points"][0]["sources"][0]["how"] == "grey ramp"
    assert client.get("/api/grey-scales", params={"device_id": 999}).json()["scales"] == []


def test_a_picture_on_a_scale_is_predicted_timed_and_written_for_lightburn_at_the_chosen_min_and_max(app_world):
    client = app_world["client"]
    answer = client.post("/api/grey-scales/picture", data={**app_world["mode"], "width_mm": 60},
                         files={"picture": ("girl.png", picture_png(), "image/png")}).json()
    assert answer["power_range"] == [2.0, 40.0] and answer["size_mm"] == {"width": 60.0, "height": 30.0}
    # 18 cm² marked, one piece of scan line per row of the 30 mm high picture (DEC-101), after the cleaning: 18 cm² cross-hatched at
    # 2000 mm/s and 0.05 mm, a piece per row in both directions
    picture = 18 * 100 / (150 * 0.0169) + 30 / 0.0169 * et.TURNAROUND_S
    cleaning = 2 * 18 * 100 / (2000 * 0.05) + (30 + 60) / 0.05 * et.TURNAROUND_S
    assert answer["time"]["seconds"] == pytest.approx(picture + cleaning, rel=1e-6)
    png = client.get(answer["preview"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    narrower = client.get(f"/api/grey-scales/picture/{answer['cache_id']}", params={"width_mm": 60, "min_power": 10, "max_power": 30}).json()
    assert narrower["power_range"] == [10.0, 30.0] and narrower["file"].endswith("min_power=10&max_power=30&width_mm=60")
    file = client.get(narrower["file"])
    assert 'filename="girl-P10-30.lbrn2"' in file.headers["content-disposition"]
    project = lightburn.parse_bytes(file.content)
    assert project.layer(0).name.startswith("CLEAN-CROSSHATCH-") and et.of_project(project)["seconds"] == pytest.approx(answer["time"]["seconds"])
    layer = project.layer(1)
    assert (layer.layer_type, layer.power, layer.image_summary()["min_power"], layer.speed, layer.line_interval) == ("Image", 30, 10, 150, 0.0169)
    stored = cv2.imdecode(np.frombuffer(layer.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)
    assert stored.shape == (120, 240) and stored[0, 0] == 255 and stored[0, -1] == 0          # its own pixels: coarser than 1503 dpi


def test_a_file_refused_on_a_titanium_where_its_mode_is_not_measured_says_where_it_is_measured(app_world):
    client, mode = app_world["client"], app_world["mode"]
    other = su.save_material(client.app.state.store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0)
    data = plans.export_picture(portrait(), 50, {**MODE_A, "pulse_width": 300, "min_power": 2, "power": 40}, clean=CLEAN)
    fields = {"device_id": mode["device_id"], "lens_id": mode["lens_id"]}
    files = {"lightburn": ("girl.lbrn2", data, "application/octet-stream")}
    (refused,) = client.post("/api/predictions/photo", data={**fields, "material_id": other["id"]}, files=files).json()["layers"]
    assert refused["refused"].startswith("no colour has been measured at this mode")
    assert refused["measured_on"] == [{"device_id": mode["device_id"], "lens_id": int(mode["lens_id"]), "material_id": mode["material_id"]}]
    (shown,) = client.post("/api/predictions/photo", data={**fields, "material_id": mode["material_id"]}, files=files).json()["layers"]
    assert shown.get("refused") is None and shown["index"] == 1                                # the picture of a cleaned file is on C01


def test_a_colour_picture_gets_the_greys_whose_colours_come_nearest_on_the_scale(app_world):
    client = app_world["client"]
    wanted = np.zeros((40, 80, 3), np.uint8)
    wanted[:, :40] = HUES[0][::-1]                    # BGR: the colour of the white step
    wanted[:, 40:] = HUES[5][::-1]                    # and a violet of the dark half
    answer = client.post("/api/grey-scales/picture", data={**app_world["mode"], "width_mm": 20, "by_colour": "true"},
                         files={"picture": ("two.png", cv2.imencode(".png", wanted)[1].tobytes(), "image/png")}).json()
    assert answer["by_colour"] and answer["colour_match"]["median_de"] < 3 and answer["colour_match"]["greys_used"] == 2
    layer = lightburn.parse_bytes(client.get(answer["file"]).content).layer(1)
    stored = cv2.imdecode(np.frombuffer(layer.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)
    left, right = int(np.median(stored[:, :10])), int(np.median(stored[:, -10:]))
    assert left > 230 and 30 < right < 160           # white-ish where gold is wanted, a darker grey where violet is


def test_a_mode_nothing_was_measured_at_and_an_expired_upload_are_refused_with_the_reason(app_world):
    client = app_world["client"]
    refused = client.post("/api/grey-scales/picture", data={**app_world["mode"], "speed": 999, "width_mm": 20},
                          files={"picture": ("p.png", picture_png(), "image/png")})
    assert refused.status_code == 422 and "no colour has been measured at this mode" in refused.json()["error"]
    gone = client.get("/api/grey-scales/picture/missing", params={"width_mm": 20})
    assert gone.status_code == 404 and gone.json()["error"] == "the preview is no longer kept: upload the picture again"
    not_a_picture = client.post("/api/grey-scales/picture", data={**app_world["mode"], "width_mm": 20},
                                files={"picture": ("p.png", b"not a picture", "image/png")})
    assert not_a_picture.status_code == 422


def test_a_plate_and_its_plan_page_say_how_long_the_plate_engraves(world):
    from titanium_platform import experiments
    made = cp.create(world["store"], world["laser"]["id"], world["titanium"]["id"], "grey_scales", {**SETTINGS, "scales": SMALL})
    detail = experiments.get_experiment(world["store"], experiments.plan_key(made["plan_id"]))
    time = detail["time"]
    tiles = [row for row in time["layers"] if row["name"].startswith("GREY-")]
    assert len(tiles) == 4 and time["complete"] and time["seconds"] > sum(row["seconds"] for row in tiles) > 0
    tile = next(row for row in tiles if row["name"] == "GREY-I0.0169-V150")
    ramp = next(layer["ramp"] for layer in plans.get_plan(world["store"], made["plan_id"])["layers"] if layer["name"] == tile["name"])
    area_cm2 = ramp["width"] * ramp["height"] / 100                     # the picture's whole rectangle is scanned, row by row
    assert tile["seconds"] == pytest.approx(area_cm2 * 100 / (150 * 0.0169) + ramp["height"] / 0.0169 * et.TURNAROUND_S, rel=1e-3)
