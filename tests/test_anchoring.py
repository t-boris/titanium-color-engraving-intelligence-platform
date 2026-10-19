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


def test_the_hidden_margin_is_reported_per_side_of_the_plate_in_millimetres(work, registered):
    """REQ-024: per side, not per corner: the synthetic frame hides 2 mm on every side. The frame-edge finder places the
    edge where the blurred dark run ends, which reads the margin about 0.6 mm short here: an estimate, within 1 mm."""
    _, result, _ = registered
    sides = result.details["hidden_side_mm"]
    assert set(sides) == {"top", "right", "bottom", "left"} == set(result.details["frame_sides"])
    assert all(abs(v - work["hide_mm"]) < 1.0 for v in sides.values()), sides
    assert max(sides.values()) - min(sides.values()) < 0.3                      # the same frame on every side reads the same


def test_a_side_margin_is_the_inward_distance_of_the_window_edge_from_the_plate_edge():
    plate = np.array([(10, 10), (160, 10), (160, 160), (10, 160)], float)
    h = np.diag([2.0, 2.0, 1.0])                                  # mm -> px, 2 px per mm
    window = np.array([(13, 11), (155, 11), (155, 157), (13, 157)], float) * 2
    assert anchoring.side_margins(h, plate, window) == {"top": 1.0, "right": 5.0, "bottom": 3.0, "left": 3.0}
    assert anchoring.side_margins(h, plate, plate * 2) == {"top": 0.0, "right": 0.0, "bottom": 0.0, "left": 0.0}


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
    assert result.details["hidden_side_mm"] == {"top": 0.0, "right": 0.0, "bottom": 0.0, "left": 0.0}    # the plate edge is the window


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


# -- REQ-038 AC4: every gate refuses on its own (the ambiguous orientation: test_a_drawing_whose_orientation_cannot_be_told_is_refused)
def few_anchor_work() -> dict:
    """Six distinctive shapes are seen; 62 small ones of the file left no visible mark. The photograph supports the
    drawing well enough to find it, but only six of its 68 elements can be anchors, fewer than the seven (a tenth) needed."""
    rng = np.random.default_rng(21)
    spots = [(35, 40), (90, 30), (140, 45), (40, 135), (95, 140), (135, 120)]
    seen = [(1 + i % 4, synth.cloud(x, y, 14, 30 + i, 160)) for i, (x, y) in enumerate(spots)]
    unseen = [(5, synth.cloud(rng.uniform(20, 150), rng.uniform(60, 110), 2.7, 200 + i, 40)) for i in range(62)]
    return synth.framed_work(style="none", extra=seen + unseen, unseen_layers=(5,))


def clustered_work() -> dict:
    """Sixteen small shapes in one corner are seen; four shapes spread over the rest of the plate left no visible mark."""
    rng = np.random.default_rng(11)
    seen = [(1 + i % 4, synth.cloud(22 + 9 * (i % 4) + rng.uniform(-1.5, 1.5), 22 + 9 * (i // 4) + rng.uniform(-1.5, 1.5),
                                    rng.uniform(2.8, 3.6), 100 + i, 60)) for i in range(16)]
    unseen = [(5, synth.cloud(x, y, 5, seed, 60)) for x, y, seed in ((135, 135, 7), (135, 35, 8), (35, 135, 9), (95, 95, 10))]
    return synth.framed_work(style="none", extra=seen + unseen, unseen_layers=(5,))


def bent_work(amplitude_mm: float) -> dict:
    """The usual framed work on a plate that is not flat: a smooth displacement of ``amplitude_mm`` every 60 mm."""
    work = synth.framed_work(seed=3, blobs=60)
    return dict(work, photo=synth.warped(work["photo"], amplitude_mm * 9.5, 60 * 9.5))     # framed_work: 9.5 px/mm


def refusal(work: dict) -> tuple[object, dict]:
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    diagnostics = {}
    return anchoring.register(work["photo"], layers, diagnostics), diagnostics


def test_too_few_anchors_refuse_the_registration_although_the_drawing_and_its_orientation_are_found():
    result, diagnostics = refusal(few_anchor_work())
    assert result is None and diagnostics["refused"] == "only 6 elements matched the photograph", diagnostics.get("refused")
    assert diagnostics["anchors"] == 6
    assert diagnostics["orientation"]["margin"] < anchoring.ORIENTATION_MARGIN       # the orientation was clear: not that gate


def test_when_no_pass_keeps_four_anchors_the_refusal_says_fewer_than_four_instead_of_zero(monkeypatch):
    # a pass needs four anchors to fit; below that no count is kept, and "only 0 elements" would understate it
    monkeypatch.setattr(anchoring, "_refine", lambda h, elements, dist, cap: (h, []))
    result, diagnostics = refusal(few_anchor_work())
    assert result is None and diagnostics["refused"] == "fewer than four elements matched the photograph", diagnostics.get("refused")


def test_anchors_concentrated_in_one_part_of_the_work_refuse_the_registration():
    result, diagnostics = refusal(clustered_work())
    assert result is None and diagnostics["refused"] == "the matched elements are concentrated in one part of the work"
    assert diagnostics["spread"] < anchoring.MIN_SPREAD
    # enough anchors that agree closely: only their distribution failed
    assert diagnostics["anchors"] >= 5 and diagnostics["inlier_fraction"] == 1.0
    assert diagnostics["residual_median_mm"] <= anchoring.MAX_RESIDUAL_MM[0]


def test_anchors_that_no_single_transform_fits_closely_refuse_the_registration():
    """A residual over 0.2 mm between the anchors and one transform: RANSAC keeps as inliers only the anchors within
    0.2 mm (the bound of the median residual), so on a bent plate the inlier gate is the one that refuses."""
    result, diagnostics = refusal(bent_work(0.4))
    assert result is None and diagnostics["refused"] == "the matched elements disagree about the position of the work"
    assert diagnostics["anchors"] >= 5


def test_the_residual_gate_refuses_anchors_that_fit_less_closely_than_its_bound(monkeypatch):
    """The median residual of the inliers cannot exceed the RANSAC bound of 0.2 mm, which equals the gate, so the gate
    itself is reached here only by lowering it (monkeypatched) under the 0.1 mm a slightly bent plate fits to."""
    accepted, diagnostics = refusal(bent_work(0.15))
    assert accepted is not None and 0.08 < diagnostics["residual_median_mm"] <= anchoring.MAX_RESIDUAL_MM[0], diagnostics
    monkeypatch.setattr(anchoring, "MAX_RESIDUAL_MM", (0.08, 0.6))
    result, diagnostics = refusal(bent_work(0.15))
    assert result is None and diagnostics["refused"].startswith("the outlines do not fit closely enough")
