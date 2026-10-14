import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color
from titanium_platform import photo as ph


def test_chart_is_detected_and_a_colour_cast_is_corrected():
    img = synth.cast(synth.scene())
    corrected, chart, corr = ph.correct(img)
    assert chart.detected and corr is not None and corr.residual < 4.0
    # a flat patch of known colour is recovered close to its true value after correction
    work = corrected[300:600, 600:800]
    got = np.median(work.reshape(-1, 3), axis=0) * 255
    assert np.allclose(got, (120, 70, 200), atol=14)
    raw_med = np.median(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)[300:600, 600:800].reshape(-1, 3), axis=0)
    assert np.abs(raw_med - (120, 70, 200)).max() > np.abs(got - (120, 70, 200)).max()  # the cast made it worse before correction


def test_no_chart_means_no_corrected_image():
    img = np.full((600, 800, 3), 140, np.uint8)
    corrected, chart, corr = ph.correct(img)
    assert corrected is None and corr is None and not chart.detected and "not detected" in chart.reason


def test_a_chart_with_a_large_correction_residual_is_rejected(monkeypatch):
    img = synth.scene()
    monkeypatch.setattr(ph, "MAX_CORRECTION_RESIDUAL", 0.0)
    corrected, chart, corr = ph.correct(synth.cast(img, gains=(0.5, 1.2, 0.9), gamma=1.6))
    assert corrected is None and chart.detected and "residual" in chart.reason


def test_non_raw_photographs_are_refused_for_measurement(tmp_path):
    p = tmp_path / "x.jpg"
    cv2.imwrite(str(p), synth.scene())
    with pytest.raises(ph.PhotoError, match="RAW"):
        ph.decode_image(p)
    assert ph.decode_image(p, allow_non_raw=True).shape[2] == 3


def test_corrupt_raw_files_fail_with_a_clear_error(tmp_path):
    p = tmp_path / "broken.nef"
    p.write_bytes(b"not a raw file")
    with pytest.raises(ph.PhotoError, match="cannot decode RAW"):
        ph.decode_image(p)


@pytest.mark.parametrize("pts,ok", [
    ([(0, 0), (10, 0), (10, 10), (0, 10)], True),
    ([(0, 0), (10, 0), (0, 10), (10, 10)], False),   # self-crossing order
    ([(0, 0), (10, 0), (20, 0), (0, 10)], False),    # collinear corner
    ([(0, 0), (10, 0), (10, 10)], False),
    ([(0, 0), (10, 0), (10, float("nan")), (0, 10)], False),
])
def test_corner_validation(pts, ok):
    if ok:
        ph.validate_corners(pts)
    else:
        with pytest.raises(ph.PhotoError):
            ph.validate_corners(pts)


def test_manual_corner_alignment_maps_image_pixels_to_file_mm():
    corners = [(100, 50), (500, 50), (500, 250), (100, 250)]   # a 400x200 px work
    h = ph.homography_from_corners(corners, (10, 20, 80, 40))  # 80x40 mm at (10, 20)
    p = cv2.perspectiveTransform(np.array([[[300, 150]]], np.float32), h)[0, 0]
    assert p == pytest.approx([50, 40], abs=1e-3)


def test_mask_excludes_the_region_edges():
    h = np.eye(3)
    poly = [(10, 10), (110, 10), (110, 60), (10, 60)]
    mask = ph.region_mask(poly, h, (100, 200))
    ys, xs = np.nonzero(mask)
    assert xs.min() > 10 and xs.max() < 110 and ys.min() > 10 and ys.max() < 60
    # EDGE_FRACTION of the shorter side (50 px) is removed on every edge: 10 px. fillPoly includes the
    # boundary pixels, so the region is 101x51 px and the eroded mask is 81x31 = 2511 px.
    k = round(50 * ph.EDGE_FRACTION)
    assert mask.sum() == (101 - 2 * k) * (51 - 2 * k)


def test_sampling_ignores_a_bright_edge_and_rejects_tiny_regions():
    img = np.full((100, 200, 3), 0.2)
    img[10:60, 10:110] = (0.5, 0.4, 0.3)
    img[10:13, 10:110] = 1.0  # bright edge line that the mask must exclude
    mask = ph.region_mask([(10, 10), (110, 10), (110, 60), (10, 60)], np.eye(3), (100, 200))
    lab, n = ph.sample_lab(img, mask)
    assert lab == pytest.approx(list(color.srgb8_to_lab(np.array([127.5, 102, 76.5]))), abs=0.5) and n > 1000
    tiny = ph.region_mask([(10, 10), (14, 10), (14, 14), (10, 14)], np.eye(3), (100, 200))
    with pytest.raises(ph.PhotoError, match="too small"):
        ph.sample_lab(img, tiny)


def test_color_roundtrip_and_delta_e():
    lab = color.srgb8_to_lab(np.array([120, 70, 200]))
    assert color.lab_to_srgb8(lab).tolist() == [120, 70, 200]
    assert color.delta_e([50, 0, 0], [53, 4, 0]) == pytest.approx(5.0)
    assert color.valid_lab([50, 0, 0]) and not color.valid_lab([101, 0, 0]) and not color.valid_lab([50, float("nan"), 0])
