"""Element-anchored registration of an unmarked work, framed or not (REQ-024, DEC-048, DEC-049)."""
import cv2
import numpy as np
import pytest

import synth
from titanium_platform import anchoring
from titanium_platform import lightburn as lb


def circle(cx, cy, r, n=40):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)])


@pytest.fixture(scope="module")
def work():
    # one outline entirely inside the hidden 2 mm margin, one straddling the frame's inner edge
    return synth.framed_work(seed=3, blobs=60, extra=[(5, circle(11.0, 80.0, 0.7, 16)), (6, circle(16.0, 120.0, 5.5))])


@pytest.fixture(scope="module")
def registered(work):
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    diagnostics = {}
    result = anchoring.register(work["photo"], layers, diagnostics)
    return layers, result, diagnostics


def test_a_mirrored_rotated_framed_work_is_registered_within_a_fraction_of_a_millimetre(work, registered):
    _, result, diagnostics = registered
    assert result is not None, diagnostics
    assert result.method == "element anchors" and result.reflected
    grid = np.array([(x, y) for x in range(20, 151, 10) for y in range(20, 151, 10)], np.float32)
    px = cv2.perspectiveTransform(grid[None], work["mm_to_px"])[0]
    back = cv2.perspectiveTransform(px[None], result.image_to_mm.astype(np.float32))[0]
    assert np.linalg.norm(back - grid, axis=1).max() < 0.3


def test_the_orientation_is_decided_with_a_clear_margin(registered):
    _, result, diagnostics = registered
    orientation = result.details["orientation"]
    assert orientation["mirror"] is True and orientation["margin"] < anchoring.ORIENTATION_MARGIN
    assert diagnostics["anchors"] >= 20 and diagnostics["residual_median_mm"] < 0.1


def test_the_hidden_margin_of_the_plate_and_the_window_are_reported(work, registered):
    _, result, _ = registered
    hidden = result.details["plate_hidden_mm"]
    assert len(hidden) == 4 and all(1.5 < v < 3.6 for v in hidden)       # 2 mm per side, corner distance up to 2.8 mm
    window = np.array(result.details["window_px"], np.float32)
    a, b = 10 + work["hide_mm"], 160 - work["hide_mm"]
    truth = cv2.perspectiveTransform(np.float32([[(a, a), (b, a), (b, b), (a, b)]]), work["mm_to_px"])[0]
    # the file is a vertical mirror: the window corners are the same four points in another order
    assert max(min(np.linalg.norm(p - t) for t in truth) for p in window) < 12


def test_an_outline_under_the_frame_is_inferred_and_one_on_its_edge_is_partly_hidden(registered):
    layers, result, _ = registered
    elements = anchoring.elements_from_layers(layers)
    status = dict(zip(result.details["element_refs"], result.details["statuses"]))
    by_layer = {}
    for element in elements:
        by_layer.setdefault(element.layer_index, []).append(element)

    def status_near(layer, x, y):
        near = min(by_layer[layer], key=lambda e: np.linalg.norm(e.centroid - (x, y)))
        return status[(near.layer_index, near.region_index)]

    assert status_near(5, 11.0, 80.0) == "hidden"
    assert status_near(6, 16.0, 120.0) == "partly hidden"
    counts = result.details["counts"]
    assert counts["boundary"] == 1 and counts["anchor"] >= 20 and counts["confirmed"] > 0


def test_prediction_uncertainty_of_the_plate_corners_is_small(registered):
    _, result, _ = registered
    assert max(result.details["plate_uncertainty_mm"]) < 0.5


def accuracy_mm(work, result, lo=20, hi=151) -> float:
    grid = np.array([(x, y) for x in range(lo, hi, 10) for y in range(lo, hi, 10)], np.float32)
    px = cv2.perspectiveTransform(grid[None], work["mm_to_px"])[0]
    back = cv2.perspectiveTransform(px[None], result.image_to_mm.astype(np.float32))[0]
    return float(np.linalg.norm(back - grid, axis=1).max())


def test_a_photograph_without_a_frame_is_registered_and_nothing_is_hidden():
    plain = synth.framed_work(with_frame=False)
    layers = [layer for layer in lb.parse_bytes(plain["lightburn"]).layers if layer.regions]
    diagnostics = {}
    result = anchoring.register(plain["photo"], layers, diagnostics)
    assert result is not None, diagnostics
    assert accuracy_mm(plain, result) < 0.3
    assert result.details["window_found"] is False and not any(result.details["frame_sides"].values())
    assert result.details["counts"]["hidden"] == 0 and max(result.details["plate_hidden_mm"]) <= 0.5


def test_a_black_silhouette_touching_the_frame_does_not_move_the_frame_edge():
    # the whole left and bottom edge of the plate is engraved black, as dark as the frame around it
    silhouette = np.array([(10, 90), (60, 90), (60, 150), (90, 150), (90, 160), (10, 160)], float)
    work = synth.framed_work(seed=5, blobs=60, extra=[(7, silhouette)], dark_layers=(7,))
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    diagnostics = {}
    result = anchoring.register(work["photo"], layers, diagnostics)
    assert result is not None, diagnostics
    assert accuracy_mm(work, result) < 0.4          # a quarter of the plate has no anchors under the silhouette
    assert all(result.details["frame_sides"].values())
    assert all(1.5 < v < 3.6 for v in result.details["plate_hidden_mm"])      # 2 mm per side, as without the silhouette


def test_a_drawing_of_parallel_strokes_is_registered_in_the_right_orientation():
    work = synth.framed_work(seed=6, blobs=30, style="strokes")
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    diagnostics = {}
    result = anchoring.register(work["photo"], layers, diagnostics)
    assert result is not None, diagnostics
    assert result.reflected and accuracy_mm(work, result) < 0.3


def test_a_registration_from_another_route_is_confirmed_by_the_elements_or_refused(work):
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    right = np.linalg.inv(work["mm_to_px"])
    diagnostics = {}
    confirmed = anchoring.confirm(work["photo"], layers, right, diagnostics)
    assert confirmed is not None, diagnostics
    assert confirmed.method == "element anchors" and accuracy_mm(work, confirmed) < 0.3
    assert confirmed.details["orientation"]["margin"] is None and diagnostics["anchors"] >= 20
    flip = np.array([[-1, 0, 170], [0, 1, 0], [0, 0, 1]], float)                # the same work mirrored in x
    diagnostics = {}
    assert anchoring.confirm(work["photo"], layers, np.linalg.inv(work["mm_to_px"] @ flip), diagnostics) is None
    assert diagnostics["refused"]


def test_a_drawing_whose_orientation_cannot_be_told_is_refused():
    work = synth.framed_work(concentric=True)
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    diagnostics = {}
    assert anchoring.register(work["photo"], layers, diagnostics) is None
    assert "orientation" in diagnostics["refused"]


def test_a_file_with_too_few_outlines_is_refused():
    work = synth.framed_work(blobs=4)
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    diagnostics = {}
    assert anchoring.register(work["photo"], layers, diagnostics) is None
    assert "too few" in diagnostics["refused"]


def test_the_enclosing_rectangle_is_the_plate_boundary_and_never_an_anchor(registered):
    layers, _, _ = registered
    elements = anchoring.elements_from_layers(layers)
    boundary = [e for e in elements if e.boundary]
    assert len(boundary) == 1 and boundary[0].layer_index == 0
    corners = anchoring.plate_rectangle(elements)
    assert np.allclose(corners, [[10, 10], [160, 10], [160, 160], [10, 160]], atol=0.7)


def test_a_loop_inside_a_loop_is_outlined_as_part_of_its_element():
    verts = "".join(f"V{x} {y}c0x1c1x1" for x, y in [(0, 0), (40, 0), (40, 40), (0, 40), (10, 10), (30, 10), (30, 30), (10, 30)])
    xml = ('<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/>'
           '<speed Value="900"/><frequency Value="48000"/></CutSetting><Shape Type="Path" CutIndex="0"><XForm>1 0 0 1 0 0</XForm>'
           f'<VertList>{verts}</VertList><PrimList>L0 1L1 2L2 3L3 0L4 5L5 6L6 7L7 4</PrimList></Shape></LightBurnProject>').encode()
    layers = lb.parse_bytes(xml).layers
    (element,) = anchoring.elements_from_layers(layers)
    assert np.isclose(element.area, 1600)
    assert abs(len(element.points) - 240 / anchoring.SAMPLE_STEP_MM) < 6      # outer loop 160 mm + hole 80 mm


def test_the_outer_ring_is_predicted_from_the_rest_within_a_fraction_of_a_millimetre(registered):
    _, result, _ = registered
    held = result.details["extrapolation_mm"]
    assert held is not None and held["median"] is not None and held["median"] < 0.3 and held["found"] >= 3


def test_overlapping_outlines_that_are_painted_over_are_still_registered_or_refused_never_wrong():
    clouds = synth.framed_work(seed=8, blobs=70, style="clouds")
    layers = [layer for layer in lb.parse_bytes(clouds["lightburn"]).layers if layer.regions]
    diagnostics = {}
    result = anchoring.register(clouds["photo"], layers, diagnostics)
    if result is None:
        assert diagnostics["refused"]
        return
    grid = np.array([(x, y) for x in range(30, 141, 10) for y in range(30, 141, 10)], np.float32)
    px = cv2.perspectiveTransform(grid[None], clouds["mm_to_px"])[0]
    back = cv2.perspectiveTransform(px[None], result.image_to_mm.astype(np.float32))[0]
    assert np.linalg.norm(back - grid, axis=1).max() < 0.5
