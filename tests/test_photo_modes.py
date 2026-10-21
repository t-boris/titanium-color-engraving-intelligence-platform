"""The kinds of photo engraving and the part of a picture each of them strikes (REQ-053, REQ-054, DEC-095)."""
import cv2
import numpy as np
import pytest

from test_image_layers import IMAGE_TO_MM, project, ramp_png
from titanium_platform import ingest as ig, lightburn as lb, photo_modes as pm

LIGHTBURN_MODES = ("grayscale", "threshold", "ordered", "atkinson", "dither", "stucki", "jarvis", "newsprint", "halftone", "sketch", "3dslice")


def test_every_mode_lightburn_offers_is_described_with_its_family_and_what_the_grey_level_controls():
    assert tuple(pm.MODES) == LIGHTBURN_MODES
    for key in LIGHTBURN_MODES:
        entry = pm.describe(key)
        assert entry["known"] and entry["label"] and entry["controls"] and entry["family"] in (pm.POWER, pm.DOTS, pm.EDGES, pm.DEPTH)
        assert entry["settings"] and entry["basis"] in ("documented", "inferred")
    assert pm.describe("grayscale")["binary"] is False and pm.describe("jarvis")["binary"] is True
    assert pm.describe("grayscale")["predicted_from"] == pm.CURVE and pm.describe("3dslice")["predicted_from"] == pm.NONE


def test_the_strings_lightburn_writes_for_a_mode_are_recognised_and_an_unknown_one_is_not_guessed():
    assert pm.mode("dithered").key == "dither" and pm.mode("Jarvis").key == "jarvis" and pm.mode("pass-through").key == "threshold"
    assert pm.describe("flux") == {"key": "flux", "known": False, "family": None}
    assert pm.describe(None)["known"] is False


def test_the_image_layer_summary_names_the_family_and_reads_the_tags_of_the_other_modes():
    extra = '<minPower Value="3"/><negative Value="1"/><passThrough Value="0"/><cellsPerInch Value="60"/><halftoneAngle Value="45"/>'
    data = project(ramp_png(), mode="halftone").replace(b'<maxPower Value="25"/>', b'<maxPower Value="25"/>' + extra.encode())
    layer = lb.parse_bytes(data).layer(0)
    summary = layer.image_summary()
    assert summary["family"] == "dots" and summary["min_power"] == 3 and summary["max_power"] == 25
    assert summary["negative"] is True and summary["pass_through"] is False and summary["cells_per_inch"] == 60 and summary["halftone_angle"] == 45
    assert layer.unknown_settings == []                                  # nothing the system now reads is reported as unknown


GREY = np.array([[0.0, 0.25, 0.5, 0.75, 1.0]])
OPAQUE = np.ones_like(GREY)


def test_grayscale_strikes_white_at_min_power_and_leaves_it_blank_only_when_min_is_zero():
    assert pm.coverage("grayscale", GREY, OPAQUE, min_power=3, max_power=27).tolist() == [[1, 1, 1, 1, 1]]
    assert pm.coverage("grayscale", GREY, OPAQUE, min_power=0, max_power=27).tolist() == [[1, 1, 1, 1, 0]]
    assert pm.coverage("grayscale", GREY, OPAQUE, min_power=0, max_power=0).tolist() == [[0, 0, 0, 0, 0]]


def test_a_dither_mode_strikes_in_proportion_to_the_darkness_and_never_strikes_white():
    cover = pm.coverage("jarvis", GREY, OPAQUE)
    assert cover[0].tolist() == pytest.approx([1.0, 0.75, 0.5, 0.25, 0.0])
    assert pm.struck("jarvis", GREY, OPAQUE).tolist() == [[True, True, True, True, False]]
    assert pm.coverage("threshold", GREY, OPAQUE).tolist() == [[1, 1, 0, 0, 0]]


def test_a_transparent_pixel_is_never_struck_in_any_mode_and_negative_swaps_light_and_dark():
    alpha = np.array([[0.0, 0.0, 1.0, 1.0, 1.0]])
    for key in LIGHTBURN_MODES:
        assert not pm.struck(key, GREY * 0, alpha, min_power=3)[0, :2].any(), key
    assert pm.coverage("jarvis", GREY, OPAQUE, negative=True)[0].tolist() == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])


def test_the_picture_adjustments_apply_before_the_mode():
    brighter = {"Brightness": "0.5"}
    assert pm.coverage("jarvis", GREY, OPAQUE, adjustments=brighter)[0, 0] < 1.0


# -- which pixels of the photograph an image layer strikes: the picture, not the rectangle of its bitmap ----------
def holed_png(transparent_top=True, rows=60, cols=80) -> bytes:
    """A mid-grey picture whose first half of the rows (or its second half) is fully transparent."""
    bgra = np.full((rows, cols, 4), 255, np.uint8)
    bgra[..., :3] = 100
    if transparent_top:
        bgra[:rows // 2, :, 3] = 0
    else:
        bgra[rows // 2:, :, 3] = 0
    return cv2.imencode(".png", bgra)[1].tobytes()


def test_the_transparent_part_of_a_picture_is_not_struck_and_the_orientation_decides_which_part_that_is():
    layer = lb.parse_bytes(project(holed_png(), mode="grayscale")).layer(0)
    shape = (500, 700)
    for flip, upper_struck in ((False, False), (True, True)):
        mask = ig._struck_mask(layer, IMAGE_TO_MM, shape, flip)
        upper, lower = mask[60:190, 120:480], mask[210:340, 120:480]            # 10 px per mm: the bitmap spans y 5..35, x 10..50 mm
        assert bool(upper.mean() > 0.95) is upper_struck and bool(lower.mean() > 0.95) is (not upper_struck)
        assert mask[:30].sum() == 0 and mask[:, :60].sum() == 0                  # nothing outside the bitmap


def fill_and_picture(png: bytes) -> bytes:
    """A work of two layers: a Scan fill under the lower half of the bitmap (priority 0), the Image layer burned last (priority 8)."""
    xml = project(png, mode="grayscale").decode()
    xml = xml.replace('<CutSetting_Img type="Image"><index Value="0"/>', '<CutSetting_Img type="Image"><index Value="1"/><priority Value="8"/>')
    xml = xml.replace('CutIndex="0" W="40"', 'CutIndex="1" W="40"')
    fill = ('<CutSetting type="Scan"><index Value="0"/><name Value="C00"/><priority Value="1"/><maxPower Value="20"/><speed Value="900"/>'
            '<frequency Value="48000"/></CutSetting><Shape Type="Rect" CutIndex="0" W="30" H="12"><XForm>1 0 0 1 30 28</XForm></Shape>')
    return xml.replace("<LightBurnProject AppVersion=\"1.7.01\">", "<LightBurnProject AppVersion=\"1.7.01\">" + fill, 1).encode()


def test_a_fill_under_the_transparent_part_of_the_picture_is_not_engraved_again_but_one_under_the_opaque_part_is():
    layers = lb.parse_bytes(fill_and_picture(holed_png(transparent_top=True))).layers          # lower half opaque, fill sits in the lower half
    fill = next(layer for layer in layers if layer.layer_type == "Scan")
    covered = ig._covered_by_later_layers(fill, layers, IMAGE_TO_MM, {}, (500, 700), set(), {1: False})
    assert covered is not None and covered[250:350, 150:450].all()
    layers = lb.parse_bytes(fill_and_picture(holed_png(transparent_top=False))).layers         # the lower half is transparent now
    fill = next(layer for layer in layers if layer.layer_type == "Scan")
    covered = ig._covered_by_later_layers(fill, layers, IMAGE_TO_MM, {}, (500, 700), set(), {1: False})
    assert covered is None or not covered[250:350, 150:450].any()


def test_a_plain_frame_on_an_image_layer_strikes_nothing():
    layers = lb.parse_bytes(fill_and_picture(holed_png(transparent_top=False))).layers
    image = next(layer for layer in layers if layer.layer_type == "Image")
    frame = lb.Region("rect", 10, 5, 40, 30, polygon=[(10, 5), (50, 5), (50, 35), (10, 35)], closed=True)
    image.regions.append(frame)
    fill = next(layer for layer in layers if layer.layer_type == "Scan")
    covered = ig._covered_by_later_layers(fill, layers, IMAGE_TO_MM, {}, (500, 700), set(), {1: False})
    assert covered is None or not covered[250:350, 150:450].any()


# -- the Russian table in the UI says the same as the catalogue ---------------------------------------------------
def ui_table() -> dict:
    """{key: (family, predict)} read from the first line of each entry of ui/photo-modes.js."""
    import re
    from pathlib import Path
    source = (Path(pm.__file__).parent / "ui" / "photo-modes.js").read_text(encoding="utf-8")
    return {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(r"^    '?(\w+)'?: \{label: '[^']+', family: '(\w+)', predict: '(\w+)',", source, re.M)}


def test_the_russian_table_of_the_ui_has_every_mode_of_the_catalogue_with_the_same_family_and_the_same_prediction():
    table = ui_table()
    assert tuple(table) == tuple(pm.MODES)
    for key, mode in pm.MODES.items():
        assert table[key] == (mode.family, mode.predicted_from), key


def test_only_the_modes_with_tones_to_measure_are_predicted():
    predicted = {key for key, mode in pm.MODES.items() if mode.predicted_from != pm.NONE}
    assert predicted == {"grayscale", "ordered", "atkinson", "dither", "stucki", "jarvis", "newsprint", "halftone"}
