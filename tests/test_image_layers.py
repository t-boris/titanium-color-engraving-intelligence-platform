"""Image layers (photo engraving, 3D slice): how they are read and how their tones come out (REQ-004, REQ-025)."""
import base64

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color, ingest as ig, lightburn as lb, profiles as pf
from titanium_platform.db import Store

# Layout of LightBurn 1.7 files: <CutSetting_Img type="Image"> with dither settings, <Bitmap> with the picture in Data.
def project(png: bytes, *, mode="stucki", extra_bitmap="", sub_layer="") -> bytes:
    data = base64.b64encode(png).decode()
    return (f'<LightBurnProject AppVersion="1.7.01"><CutSetting_Img type="Image"><index Value="0"/><name Value="C00"/>'
            f'<maxPower Value="25"/><speed Value="150"/><frequency Value="60000"/><dotWidth Value="0.05"/><useDotCorrection Value="1"/>'
            f'<interval Value="0.1016"/><ditherMode Value="{mode}"/><dpi Value="250"/>{sub_layer}</CutSetting_Img>'
            f'<Shape Type="Bitmap" CutIndex="0" W="40" H="30" Gamma="1" Contrast="0" Brightness="0" EnhanceAmount="0" '
            f'EnhanceRadius="0" EnhanceDenoise="0" File="/x/picture.png" SourceHash="0" Data="{data}"><XForm>1 0 0 1 30 20</XForm></Shape>'
            f'{extra_bitmap}</LightBurnProject>').encode()


def ramp_png(vertical=False, rows=60, cols=80) -> bytes:
    gray = np.linspace(0, 1, rows)[:, None] * np.ones((1, cols)) if vertical else np.linspace(0, 1, cols)[None, :] * np.ones((rows, 1))
    return cv2.imencode(".png", (gray * 255).astype(np.uint8))[1].tobytes()


def test_an_image_layer_is_described_by_what_the_file_says():
    layer = lb.parse_bytes(project(ramp_png())).layer(0)
    summary = layer.image_summary()
    assert summary["dither"] == "stucki" and summary["kind"] == "tonal" and summary["dpi"] == 250
    assert summary["dot_width_mm"] == 0.05 and summary["dot_correction"] is True and summary["line_interval_mm"] == pytest.approx(0.1016)
    assert summary["processing"] == [{"Gamma": "1", "Contrast": "0", "Brightness": "0", "EnhanceAmount": "0", "EnhanceRadius": "0", "EnhanceDenoise": "0"}]
    assert layer.regions[0].kind == "bitmap" and layer.regions[0].bitmap["png"]
    assert "bitmap" not in layer.as_dict()["regions"][0]                 # the picture is not part of the serialised layer


def test_a_3d_slice_layer_is_a_depth_engraving_with_its_cleanup_pass():
    sub = '<SubLayer type="Scan" index="1"><maxPower Value="20"/><speed Value="2000"/></SubLayer><cleanupPass Value="1"/><numPasses Value="300"/>'
    summary = lb.parse_bytes(project(ramp_png(), mode="3dslice", sub_layer=sub)).layer(0).image_summary()
    assert summary["kind"] == "depth" and summary["cleanup_pass"] is True and summary["passes"] == 300 and summary["sub_layers"] == 1


def test_an_object_of_the_same_picture_without_data_shares_the_first_ones_pixels():
    second = '<Shape Type="Bitmap" CutIndex="0" W="40" H="30" File="/x/picture.png" SourceHash="0"><XForm>1 0 0 1 90 20</XForm></Shape>'
    layer = lb.parse_bytes(project(ramp_png(), extra_bitmap=second)).layer(0)
    assert len(layer.regions) == 2 and layer.regions[1].bitmap["png"] == layer.regions[0].bitmap["png"]


def test_other_layers_have_no_image_summary():
    xml = b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="900"/><frequency Value="48000"/></CutSetting></LightBurnProject>'
    assert lb.parse_bytes(xml).layer(0).image_summary() is None


# -- tonal profile ----------------------------------------------------------------------------------------------
PX_PER_MM = 10.0


def photographed(layer_png: bytes, lightness_of, flip_rows=False, size=(500, 700)) -> np.ndarray:
    """Float RGB 'photograph' of the picture at 10 px/mm: bitmap centred at (30, 20) mm, 40 x 30 mm, L* from ``lightness_of(gray)``."""
    h, w = size
    gray = cv2.imdecode(np.frombuffer(layer_png, np.uint8), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
    if flip_rows:
        gray = gray[::-1]
    canvas = np.full((h, w), 0.6, np.float32)                                        # background of the table
    x0, y0, x1, y1 = int(10 * PX_PER_MM), int(5 * PX_PER_MM), int(50 * PX_PER_MM), int(35 * PX_PER_MM)
    canvas[y0:y1, x0:x1] = cv2.resize(gray, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    lab = np.dstack([lightness_of(canvas), np.zeros_like(canvas), np.zeros_like(canvas)]).astype(np.float32)
    return np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), 0, 1)


IMAGE_TO_MM = np.diag([1 / PX_PER_MM, 1 / PX_PER_MM, 1.0])


def test_the_tonal_profile_follows_the_grey_levels_of_the_picture():
    png = ramp_png()
    layer = lb.parse_bytes(project(png)).layer(0)
    rgb = photographed(png, lambda g: 15 + 70 * g)                    # lighter where the picture is lighter
    profile = ig._tonal_profile(rgb, IMAGE_TO_MM, layer, rgb.shape[:2], None)
    assert profile["rho"] > 0.95 and profile["evidence"] == "clear" and len(profile["bins"]) >= 10
    levels = [b["L"] for b in profile["bins"]]
    assert levels == sorted(levels) and levels[0] < 25 and levels[-1] > 75
    assert profile["range_L"] == pytest.approx(70, abs=12)


def test_a_picture_that_looks_the_same_turned_over_is_not_reported_as_turned():
    png = ramp_png()
    layer = lb.parse_bytes(project(png)).layer(0)
    rgb = photographed(png, lambda g: 15 + 70 * g)
    assert ig._tonal_profile(rgb, IMAGE_TO_MM, layer, rgb.shape[:2], None)["vertical_flip"] is False


def test_a_darker_result_for_lighter_grey_is_reported_as_it_is():
    png = ramp_png()
    layer = lb.parse_bytes(project(png)).layer(0)
    rgb = photographed(png, lambda g: 85 - 70 * g)
    assert ig._tonal_profile(rgb, IMAGE_TO_MM, layer, rgb.shape[:2], None)["rho"] < -0.95


@pytest.mark.parametrize("flipped", [False, True])
def test_the_edge_of_the_picture_that_is_up_is_found_from_the_photograph(flipped):
    png = ramp_png(vertical=True)
    layer = lb.parse_bytes(project(png)).layer(0)
    rgb = photographed(png, lambda g: 15 + 70 * g, flip_rows=flipped)
    profile = ig._tonal_profile(rgb, IMAGE_TO_MM, layer, rgb.shape[:2], None)
    assert profile["vertical_flip"] is flipped and profile["rho"] > 0.95


def test_a_photograph_that_does_not_follow_the_picture_is_weak_evidence():
    png = ramp_png()
    layer = lb.parse_bytes(project(png)).layer(0)
    rng = np.random.default_rng(1)
    rgb = photographed(png, lambda g: 50 + 0 * g + rng.normal(0, 0.05, g.shape))
    profile = ig._tonal_profile(rgb, IMAGE_TO_MM, layer, rgb.shape[:2], None)
    assert profile is None or profile["evidence"] == "weak"


def test_nothing_is_reported_without_the_embedded_picture():
    layer = lb.parse_bytes(project(b"")).layer(0)
    rgb = np.full((500, 700, 3), .5, np.float32)
    assert ig._tonal_profile(rgb, IMAGE_TO_MM, layer, rgb.shape[:2], None) is None


def test_a_checked_pair_with_an_image_layer_reports_its_tones(tmp_path):
    png = ramp_png()
    # the work at 10 px/mm: file mm (10..50, 5..35) lands on px (400..800, 250..550) of a 900 x 1400 scene with a chart in the corner
    rgb = photographed(png, lambda g: 15 + 70 * g, size=(700, 700))
    scene = np.full((900, 1400, 3), (150, 155, 150), np.uint8)
    scene[200:900, 300:1000] = cv2.cvtColor((rgb * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    chart = synth.chart_image()
    scene[20:20 + chart.shape[0], 20:20 + chart.shape[1]] = chart
    corners = [(400, 250), (800, 250), (800, 550), (400, 550)]
    store = Store(tmp_path)
    store.set_setting("allow_non_raw_photos", True)
    profile = pf.create_profile(store, "MOPA", 200, 0.025, 1)
    material = pf.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    pid = ig.create_pair(store, profile_id=profile["id"], lightburn_name="photo.lbrn2", lightburn_bytes=project(png), photo_name="p.png",
                         photo_bytes=cv2.imencode(".png", scene)[1].tobytes(), context={"material_id": material["id"]})
    report = ig.check_pair(store, pid, corners_fraction=[(x / 1400, y / 900) for x, y in corners])
    layer = {rep["index"]: rep for rep in report["layers"]}[0]
    assert layer["image"]["dither"] == "stucki"
    assert layer["tonal"]["rho"] > 0.9 and layer["tonal"]["range_L"] > 40
    assert layer["measured_lab"] is not None                      # the single median tone is still reported, as before
    store.close()
