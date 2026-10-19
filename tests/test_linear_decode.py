"""Colour is measured from a 16-bit linear decode; the 8-bit decode serves detection only (DEC-059).

The RAW development is mocked (no RAW file is shipped with the tests); everything else runs on synthetic charted images."""
import sys
import types

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color
from titanium_platform import photo as ph

REFERENCE_LINEAR = color.srgb_to_linear(ph.REFERENCE_SRGB / 255.0)


class FakeRaw:
    """What ``rawpy.imread`` gives: a context manager whose ``postprocess`` develops the RAW with the options it is given."""

    def __init__(self, rgb16: np.ndarray, calls: list):
        self.rgb16, self.calls = rgb16, calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def postprocess(self, **options):
        self.calls.append(options)
        return self.rgb16


def fake_rawpy(monkeypatch, rgb16: np.ndarray) -> list:
    calls: list = []
    module = types.SimpleNamespace(imread=lambda path: FakeRaw(rgb16, calls), ColorSpace=types.SimpleNamespace(sRGB="sRGB"))
    monkeypatch.setitem(sys.modules, "rawpy", module)
    return calls


# -- decode_linear -----------------------------------------------------------------------------------------------------------
def test_a_raw_is_developed_in_16_bits_without_a_tone_curve_or_brightening_and_read_as_linear_light(tmp_path, monkeypatch):
    rgb16 = np.array([[[0, 1000, 65535], [32768, 256, 7]]], np.uint16)
    calls = fake_rawpy(monkeypatch, rgb16)
    path = tmp_path / "shot.nef"
    path.write_bytes(b"raw")
    linear = ph.decode_linear(path)
    assert calls == [{"use_camera_wb": True, "no_auto_bright": True, "output_bps": 16, "gamma": (1, 1), "output_color": "sRGB"}]
    assert linear.dtype == np.float32 and np.allclose(linear, rgb16 / 65535.0)
    eight = ph.decode_image(path)                                   # the 8-bit decode for detection: the same RAW, BGR, top byte
    assert eight.dtype == np.uint8 and tuple(eight[0, 0]) == (255, 3, 0)


def test_a_raw_that_cannot_be_developed_is_refused_with_the_reason(tmp_path, monkeypatch):
    def broken(path):
        raise OSError("bad header")
    monkeypatch.setitem(sys.modules, "rawpy", types.SimpleNamespace(imread=broken, ColorSpace=types.SimpleNamespace(sRGB="sRGB")))
    path = tmp_path / "shot.cr2"
    path.write_bytes(b"x")
    with pytest.raises(ph.PhotoError, match="cannot decode RAW file: bad header"):
        ph.decode_linear(path)


def test_a_non_raw_test_image_is_linearised_from_srgb(tmp_path):
    rgb = np.array([[[0, 8, 64], [128, 200, 255]]], np.uint8)
    path = tmp_path / "test.png"
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    linear = ph.decode_linear(path, allow_non_raw=True)
    assert linear.dtype == np.float32 and np.allclose(linear, color.srgb_to_linear(rgb / 255.0), atol=1e-6)
    assert linear[0, 0, 1] == pytest.approx(8 / 255 / 12.92, rel=1e-5)                      # the linear segment of sRGB
    with pytest.raises(ph.PhotoError, match="RAW photograph is required"):
        ph.decode_linear(path)


# -- chart_patches_linear ------------------------------------------------------------------------------------------------------
def gridded(values: np.ndarray, cell: int = 40, origin=(30, 20), size=(260, 330)) -> tuple[np.ndarray, list]:
    """A float linear image with the 24 values on a 6 x 4 grid of ``cell`` px, and the grid's outline as a detector gives it."""
    image = np.full((*size, 3), 0.05, np.float32)
    x0, y0 = origin
    for index, value in enumerate(values):
        row, col = divmod(index, 6)
        image[y0 + row * cell:y0 + (row + 1) * cell, x0 + col * cell:x0 + (col + 1) * cell] = value
    box = [[x0, y0], [x0 + 6 * cell, y0], [x0 + 6 * cell, y0 + 4 * cell], [x0, y0 + 4 * cell]]
    return image, box


def test_the_24_patches_are_read_from_the_linear_image_inside_the_detected_outline():
    image, box = gridded(REFERENCE_LINEAR)
    patches = ph.chart_patches_linear(ph.Chart(True, box=box), image)
    assert np.allclose(patches, REFERENCE_LINEAR, atol=1e-6)


def test_a_chart_turned_half_round_is_read_in_the_reference_order():
    """The outline starts at the opposite corner, so the grey ramp is read first; the patches still come in reference order,
    also under a colour cast (the greys are then not exactly neutral, only the most neutral row)."""
    image, box = gridded(REFERENCE_LINEAR * np.array([0.85, 0.95, 1.1]) * 0.25)
    turned = box[2:] + box[:2]
    patches = ph.chart_patches_linear(ph.Chart(True, box=turned), image)
    assert np.allclose(patches, REFERENCE_LINEAR * np.array([0.85, 0.95, 1.1]) * 0.25, atol=1e-6)


def test_a_chart_partly_outside_the_photograph_is_refused():
    image, box = gridded(REFERENCE_LINEAR)
    outside = [[x + 200, y] for x, y in box]
    with pytest.raises(ph.PhotoError, match="partly outside"):
        ph.chart_patches_linear(ph.Chart(True, box=outside), image)


# -- the 3x3 matrix in linear light --------------------------------------------------------------------------------------------
def test_the_linear_fit_recovers_a_known_matrix_exactly():
    mixing = np.array([[0.80, 0.15, 0.05], [0.10, 0.70, 0.20], [0.05, 0.10, 0.90]])     # what the camera does to linear light
    camera = REFERENCE_LINEAR @ mixing.T
    corr = ph.fit_correction_linear(camera)
    assert np.allclose(corr.matrix, np.linalg.inv(mixing), atol=1e-9)
    assert corr.residual < 1e-6 and corr.grey_ramp["corrected"] == corr.grey_ramp["reference"]


# -- the grey ramp on a synthetic charted photograph ------------------------------------------------------------------------------
def test_the_grey_ramp_of_an_under_exposed_charted_photo_comes_out_at_the_reference_from_the_linear_decode():
    """Two stops under with a colour cast, as the operator's RAWs are. The old path read an 8-bit decode with a tone curve as
    sRGB and pressed the darks down; the linear decode puts all six grey patches back within 1 L* of the reference."""
    scene = synth.scene()
    linear = (color.srgb_to_linear(cv2.cvtColor(scene, cv2.COLOR_BGR2RGB) / 255.0) * np.array([0.85, 0.95, 1.1]) * 0.25).astype(np.float32)
    toned = (color.linear_to_srgb(np.clip(linear, 0, 1) ** 0.8) * 255).round().astype(np.uint8)     # a RAW developer's tone curve
    eight_bit = cv2.cvtColor(toned, cv2.COLOR_RGB2BGR)
    corrected, chart, corr = ph.correct(eight_bit, linear=linear)
    assert chart.detected and corrected is not None
    reference, measured = np.array(corr.grey_ramp["reference"]), np.array(corr.grey_ramp["corrected"])
    assert np.abs(measured - reference).max() < 1.0, corr.grey_ramp
    assert corr.residual < 1.5
    old = ph.fit_correction(chart.patches_rgb if chart.patches_rgb is not None else ph.detect_chart(eight_bit).patches_rgb)
    assert np.abs(np.array(old.grey_ramp["corrected"]) - reference).max() > 2 * np.abs(measured - reference).max()
