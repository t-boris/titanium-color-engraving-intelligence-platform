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


def lab_d65_to_d50(lab):
    """Lab of D65 white as the same colours given for D50 white (Bradford), the way chart values are often published."""
    xyz = color._lab_to_xyz(np.asarray(lab, float), color.WHITE_POINTS["D65"])
    b = color._BRADFORD
    gain = (b @ color.WHITE_POINTS["D50"]) / (b @ color.WHITE_POINTS["D65"])
    t = (xyz @ (np.linalg.inv(b) @ np.diag(gain) @ b).T) / color.WHITE_POINTS["D50"]
    f = np.where(t > 216 / 24389, np.cbrt(t), (24389 / 27 * t + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=-1)


def test_a_capture_setups_reference_steers_the_correction_and_its_white_point_is_honoured():
    """DEC-025: the published values by default; the same values given for D50 correct the same; other values correct
    toward themselves."""
    published = ph.published_reference()
    assert np.allclose(ph.reference_linear(published), color.srgb_to_linear(ph.REFERENCE_SRGB / 255), atol=1e-12)
    d50 = {"patches_lab": lab_d65_to_d50(published["patches_lab"]).tolist(), "white_point": "D50", "observer": "2°", "source": "t"}
    assert np.allclose(ph.reference_linear(d50), ph.reference_linear(published), atol=2e-4)
    img = synth.cast(synth.scene())
    base, _, _ = ph.correct(img)
    same, _, _ = ph.correct(img, reference=d50)
    assert np.abs(same - base).max() < 2e-3
    darker = color.linear_rgb_to_lab(color.srgb_to_linear(ph.REFERENCE_SRGB / 255) * 0.8).tolist()
    toward, _, corr = ph.correct(img, reference={"patches_lab": darker, "white_point": "D65", "observer": "2°", "source": "t"})
    assert corr.residual < 4.0
    work = lambda rgb: color.linear_rgb_to_lab(color.srgb_to_linear(np.median(rgb[300:600, 600:800].reshape(-1, 3), axis=0)))
    assert work(toward)[0] < work(base)[0] - 3                # the work is measured darker, as the reference says


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


def test_a_degenerate_detector_result_is_not_treated_as_a_chart(monkeypatch):
    """OpenCV once reported a chart on a photo without one: all-zero box, 24 identical patches."""
    class FakeChecker:
        def getBox(self):
            return np.zeros((4, 2), np.float32)

        def getChartsRGB(self):
            return np.tile(np.array([[770, 100.0, 1, 99, 101]]), (72, 1))

    class FakeDetector:
        def setColorChartType(self, t):
            pass

        def setUseDnnModel(self, flag):
            pass

        def process(self, img, nc):
            return True

        def getBestColorChecker(self):
            return FakeChecker()

    monkeypatch.setattr(cv2.mcc, "CCheckerDetector_create", lambda: FakeDetector())
    chart = ph.detect_chart(np.zeros((100, 100, 3), np.uint8))
    assert not chart.detected and "degenerate" in chart.reason
    corrected, chart2, corr = ph.correct(np.zeros((100, 100, 3), np.uint8))
    assert corrected is None and not chart2.detected


def test_uniform_patches_with_a_real_looking_box_are_still_rejected(monkeypatch):
    class FakeChecker:
        def getBox(self):
            return np.array([[0, 0], [600, 0], [600, 400], [0, 400]], np.float32)

        def getChartsRGB(self):
            return np.tile(np.array([[770, 100.0, 1, 99, 101]]), (72, 1))

    class FakeDetector:
        def setColorChartType(self, t):
            pass

        def setUseDnnModel(self, flag):
            pass

        def process(self, img, nc):
            return True

        def getBestColorChecker(self):
            return FakeChecker()

    monkeypatch.setattr(cv2.mcc, "CCheckerDetector_create", lambda: FakeDetector())
    chart = ph.detect_chart(np.zeros((100, 100, 3), np.uint8))
    assert not chart.detected and "same color" in chart.reason


def test_the_chart_detector_is_configured_explicitly_not_by_opencv_defaults(monkeypatch):
    """Regression: on Linux x86_64 a new detector sometimes starts with chart type 832 and finds nothing.

    The detector must always be told it looks for a 24-patch ColorChecker without the DNN path.
    """
    calls = {}

    class Recorder:
        def setColorChartType(self, t):
            calls["type"] = t

        def setUseDnnModel(self, flag):
            calls["dnn"] = flag

    monkeypatch.setattr(cv2.mcc, "CCheckerDetector_create", lambda: Recorder())
    ph.chart_detector()
    assert calls == {"type": cv2.mcc.MCC24, "dnn": False}


def test_the_real_detector_reports_the_configuration_it_was_given():
    det = ph.chart_detector()
    assert int(det.getColorChartType()) == int(cv2.mcc.MCC24) and det.getUseDnnModel() is False

