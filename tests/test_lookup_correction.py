"""A colour is looked up among the 24 squares as photographed and takes the numbers the nearest squares have (DEC-087).

Synthetic charts: the camera mixes the channels, lifts the blacks (a flare no 3x3 matrix without an offset can undo) and bends one
square away from the rest, as a real photograph does."""
import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color
from titanium_platform import photo as ph

REFERENCE_LINEAR = color.srgb_to_linear(ph.REFERENCE_SRGB / 255.0)
REFERENCE_LAB = color.linear_rgb_to_lab(REFERENCE_LINEAR)
MIXING = np.array([[0.80, 0.15, 0.05], [0.10, 0.70, 0.20], [0.05, 0.10, 0.90]])


def camera(gain=0.3, lift=0.012, bent=None):
    """The 24 squares as the camera records them (linear RGB): mixed, under-exposed, with a lifted black and an optional bent square."""
    seen = REFERENCE_LINEAR @ MIXING.T * gain + lift
    if bent is not None:
        seen[bent[0]] += bent[1]
    return seen


def ramp_error(corr):
    return float(np.abs(np.array(corr.grey_ramp["corrected"]) - np.array(corr.grey_ramp["reference"])).max())


def test_the_look_up_brings_the_grey_ramp_back_where_a_matrix_without_an_offset_cannot():
    seen = camera()
    matrix, lookup = ph.fit_correction_linear(seen), ph.fit_lookup(seen)
    assert ramp_error(matrix) > 3 and ramp_error(lookup) < 1.0, (matrix.grey_ramp, lookup.grey_ramp)
    assert lookup.method == "lookup" and matrix.method == "matrix"


def test_the_residual_is_the_error_on_a_square_the_fit_did_not_see():
    seen = camera(bent=(7, [0.02, -0.01, 0.015]))
    lookup = ph.fit_lookup(seen)
    fitted = np.linalg.norm(ph._lookup_lab(lookup, seen) - REFERENCE_LAB, axis=1).mean()
    assert lookup.residual > fitted > 0 or fitted < 0.5          # honest: never smaller than what the fit reproduces
    assert lookup.residual >= fitted - 1e-9


def test_a_square_that_differs_from_the_rest_is_reproduced_by_its_own_numbers():
    seen = camera(bent=(13, [0.03, -0.02, 0.01]))
    lookup = ph.fit_lookup(seen)
    base = color.linear_rgb_to_lab(np.clip(seen @ lookup.matrix.T + lookup.offset, 0, 1))
    own = ph._lookup_lab(lookup, seen[13:14])[0]
    assert np.linalg.norm(base[13] - REFERENCE_LAB[13]) > 1.0                       # the smooth map alone misses it
    assert np.linalg.norm(own - REFERENCE_LAB[13]) < 0.5                            # the nearest squares carry the miss


def test_far_from_every_square_only_the_smooth_map_counts():
    seen = camera(bent=(13, [0.03, -0.02, 0.01]))
    lookup = ph.fit_lookup(seen)
    far = np.array([[0.9, 0.05, 0.9]])                                              # a saturated purple no square resembles
    base = color.linear_rgb_to_lab(np.clip(far @ lookup.matrix.T + lookup.offset, 0, 1))[0]
    assert np.linalg.norm(ph._lookup_lab(lookup, far)[0] - base) < 1.5


def test_the_picture_map_agrees_with_the_map_of_a_single_colour():
    lookup = ph.fit_lookup(camera(bent=(4, [0.01, 0.02, -0.01])))
    rng = np.random.default_rng(3)
    colours = (rng.random((3000, 3)) ** 2.2 * 0.6).astype(np.float32)               # photographed colours, mostly dark as real ones
    through = color.linear_rgb_to_lab(np.clip(ph._through_lut(lookup, colours), 0, 1))
    direct = ph._lookup_lab(lookup, colours)
    differences = np.linalg.norm(through - direct, axis=1)
    assert differences.mean() < 0.5 and np.percentile(differences, 95) < 1.5, (differences.mean(), np.percentile(differences, 95))


def test_a_charted_photograph_is_corrected_by_the_look_up_and_the_matrix_stays_selectable(monkeypatch):
    scene = synth.scene()
    linear = (color.srgb_to_linear(cv2.cvtColor(scene, cv2.COLOR_BGR2RGB) / 255.0) * np.array([0.85, 0.95, 1.1]) * 0.25).astype(np.float32)
    toned = (color.linear_to_srgb(np.clip(linear, 0, 1) ** 0.8) * 255).round().astype(np.uint8)
    eight_bit = cv2.cvtColor(toned, cv2.COLOR_RGB2BGR)
    corrected, chart, corr = ph.correct(eight_bit, linear=linear)
    assert chart.detected and corrected is not None and corr.method == "lookup" and ramp_error(corr) < 1.0
    assert corrected.shape == linear.shape and 0 <= corrected.min() and corrected.max() <= 1
    monkeypatch.setattr(ph, "CALIBRATION", "matrix")
    _, _, old = ph.correct(eight_bit, linear=linear)
    assert old.method == "matrix"


def test_squares_that_are_not_a_chart_are_still_refused():
    shuffled = camera()[np.random.default_rng(1).permutation(24)]
    assert ph.fit_lookup(shuffled).residual > ph.MAX_CORRECTION_RESIDUAL


def test_the_screens_open_on_the_picture_the_numbers_come_from():
    """The check screen starts on the chart-corrected photograph when the chart is usable, and neither screen lifts a corrected photograph
    unless the operator asks (a lift on top of the correction was the 'brightening' the operator saw)."""
    from pathlib import Path
    screens = Path(ph.__file__).parent / "ui" / "screens"
    review, experiment = (screens / "ingest-review.js").read_text(encoding="utf-8"), (screens / "experiment.js").read_text(encoding="utf-8")
    assert "let corrected = pair.check?.chart?.usable === true, visibility = corrected ? 'normal' : 'lifted'" in review
    assert "const isLifted = (pair) => lifted === null ? !(pair && shownCorrected(pair)) : lifted;" in experiment
