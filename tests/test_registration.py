from types import SimpleNamespace

import cv2
import numpy as np

from titanium_platform import plans, registration


def test_faint_reflected_markers_reject_an_old_marker_and_keep_file_millimetres():
    markers = {"extent": {"min_x": 0, "min_y": 0, "max_x": 67, "max_y": 51},
               "aruco": [{"id": i, "x": x, "y": y, "size": 4} for i, x, y in
                         [(0, 0, 0), (1, 63, 0), (2, 63, 47), (3, 0, 47)]]}
    image = np.full((840, 1000, 3), 125, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for marker in markers["aruco"]:
        # Vertical mirror: file marker 3 is upper-left in the photograph.
        x = 90 + marker["x"] * 12
        y = 90 + (47 - marker["y"]) * 12
        bits = cv2.flip(cv2.aruco.generateImageMarker(dictionary, marker["id"], 6, borderBits=1), 0)
        patch = cv2.resize(bits, (48, 48), interpolation=cv2.INTER_NEAREST)
        image[y:y+48, x:x+48] = np.where(patch[..., None] == 0, 40, 188)
    old = cv2.flip(cv2.aruco.generateImageMarker(dictionary, 2, 6, borderBits=1), 0)
    image[740:788, 846:894] = np.where(cv2.resize(old, (48, 48), interpolation=cv2.INTER_NEAREST)[..., None] == 0, 40, 188)

    result = registration.register_markers(image, markers)

    assert result is not None and result.reflected
    assert {item["id"] for item in result.matches} == {0, 1, 2, 3}
    assert result.residual_px < 8
    file_centers = np.float32([[[marker["x"] + 2, marker["y"] + 2]] for marker in markers["aruco"]])
    image_centers = cv2.perspectiveTransform(file_centers, np.linalg.inv(result.image_to_mm))[:, 0]
    assert np.allclose(image_centers[:, 0], [114, 870, 870, 114], atol=5)
    assert np.allclose(image_centers[:, 1], [678, 678, 114, 114], atol=5)


def test_two_reflected_markers_need_matching_engraved_qr_to_recover_full_plate():
    markers = plans.marker_geometry("TCE-TWO-MARKS", 55, 46,
                                    {"aruco_mm": 4, "margin_mm": .5, "qr_module_mm": .25,
                                     "qr_position": "top-right"})
    image = np.full((850, 950, 3), 150, np.uint8)
    scale = 12
    for part in (markers["aruco"][0], markers["aruco"][3], markers["qr"]):
        for rect in part["rects"]:
            x = int(round(110 + (rect["x"] - markers["extent"]["min_x"]) * scale))
            y = int(round(80 + (rect["y"] - markers["extent"]["min_y"]) * scale))
            w, h = int(round(rect["width"] * scale)), int(round(rect["height"] * scale))
            cv2.rectangle(image, (x, y), (x + w - 1, y + h - 1), (20, 20, 20), -1)
    image = cv2.flip(image, 0)

    result = registration.register_markers(image, markers, expected_identifier=markers["identifier"])

    assert result is not None and result.method == "two marker + QR" and result.reflected
    assert {item["id"] for item in result.matches} == {0, 3}
    assert result.residual_px < 10
    image_centers = cv2.perspectiveTransform(
        np.float32([[[marker["x"] + 2, marker["y"] + 2]] for marker in markers["aruco"]]),
        np.linalg.inv(result.image_to_mm))[:, 0]
    assert np.allclose(image_centers[:, 0], [134, 848, 848, 134], atol=12)
    candidates = registration._template_candidates(image, markers)
    assert registration._qr_verified_pair(image, markers, {m["id"]: m for m in markers["aruco"]},
                                          candidates, 0, 0, "another-plate") is None


def test_two_markers_and_qr_correct_camera_shear_across_the_plate():
    markers = plans.marker_geometry("TCE-SHEARED-PLATE", 55, 46,
                                    {"aruco_mm": 4, "margin_mm": .5, "qr_module_mm": .25,
                                     "qr_position": "top-right"})
    base = np.full((850, 950, 3), 150, np.uint8)
    scale = 12
    for part in (markers["aruco"][0], markers["aruco"][3], markers["qr"]):
        for rect in part["rects"]:
            x = int(round(110 + (rect["x"] - markers["extent"]["min_x"]) * scale))
            y = int(round(80 + (rect["y"] - markers["extent"]["min_y"]) * scale))
            w, h = int(round(rect["width"] * scale)), int(round(rect["height"] * scale))
            cv2.rectangle(base, (x, y), (x + w - 1, y + h - 1), (20, 20, 20), -1)
    mirrored = cv2.flip(base, 0)
    camera = np.float32([[1.02, 0, 0], [-.01, 1, 30]])
    image = cv2.warpAffine(mirrored, camera, (1000, 900), flags=cv2.INTER_NEAREST,
                           borderValue=(150, 150, 150))

    result = registration.register_markers(image, markers,
                                           expected_identifier=markers["identifier"])

    assert result is not None and result.reflected
    decoded, qr_points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    assert decoded == "TCE1:TCE-SHEARED-PLATE" and qr_points is not None
    qr = markers["qr"]
    file_center = np.float32([[[qr["x"] + qr["size"] / 2,
                                qr["y"] + qr["size"] / 2]]])
    predicted = cv2.perspectiveTransform(file_center, np.linalg.inv(result.image_to_mm))[0, 0]
    assert np.linalg.norm(predicted - qr_points[0].mean(axis=0)) < 8


def test_markerless_art_grows_from_individual_shapes_without_changing_dimensions():
    polygons = [
        [(0, 0), (8, 0), (4, 7)],
        [(23, 3), (33, 3), (34, 12), (27, 16), (22, 11)],
        [(4, 22), (17, 22), (17, 26), (9, 26), (9, 35), (4, 35)],
        [(30, 27), (39, 22), (43, 30), (36, 37), (29, 34)],
    ]
    mm_to_image = np.array([[10.2, 1.1, 120], [-.5, 10, 95], [0, 0, 1]], float)
    image = np.full((600, 800, 3), 205, np.uint8)
    layer = SimpleNamespace(name="art", regions=[])
    for polygon in polygons:
        points = np.float32(polygon)
        x, y, w, h = cv2.boundingRect(points)
        layer.regions.append(SimpleNamespace(polygon=polygon, width=w, height=h))
        projected = cv2.perspectiveTransform(points[None], mm_to_image)[0]
        cv2.fillPoly(image, [projected.astype(np.int32)], (40, 40, 40))

    result = registration.register_geometry(image, [layer])

    assert result is not None and result.method == "geometry" and len(result.matches) >= 3
    assert result.residual_px < 4
    for point in [(4, 3), (28, 9), (36, 30)]:
        wanted = cv2.perspectiveTransform(np.float32([[point]]), mm_to_image)[0, 0]
        found = cv2.perspectiveTransform(np.float32([[point]]), np.linalg.inv(result.image_to_mm))[0, 0]
        assert np.linalg.norm(found - wanted) < 8


def test_two_recognised_shapes_can_snap_a_shared_translation():
    polygons = [[(0, 0), (12, 0), (5, 9)],
                [(25, 4), (36, 4), (39, 10), (33, 17), (23, 14)]]
    actual = np.array([[8, 0, 150], [0, 8, 100], [0, 0, 1]], float)
    initial = np.array([[8, 0, 125], [0, 8, 85], [0, 0, 1]], float)
    image = np.full((450, 650, 3), 200, np.uint8)
    regions = []
    for polygon in polygons:
        pts = np.float32(polygon)
        projected = cv2.perspectiveTransform(pts[None], actual)[0]
        cv2.fillPoly(image, [projected.astype(np.int32)], (35, 35, 35))
        regions.append(SimpleNamespace(polygon=polygon, width=np.ptp(pts[:, 0]), height=np.ptp(pts[:, 1])))
    layer = SimpleNamespace(index=1, name="art", regions=regions)

    candidates = registration.snap_translations(image, [layer], np.linalg.inv(initial))

    assert any(np.linalg.norm(np.asarray(item["shift_px"]) - [25, 15]) < 6 and item["support_count"] >= 2
               for item in candidates)


def test_vector_pattern_snaps_a_layer_without_changing_its_file_dimensions():
    polygons = [[(0, 0), (3, 0), (3, 5), (0, 5)],
                [(6, 2), (10, 2), (10, 5), (6, 5)],
                [(2, 10), (7, 10), (7, 12), (2, 12)],
                [(9, 13), (12, 13), (12, 18), (9, 18)]]
    mm_to_image = np.array([[9., 0., 160.], [0., 9., 100.], [0., 0., 1.]])
    image = np.full((420, 550, 3), 170, np.uint8)
    shift = np.array([13, -11])
    regions = []
    for polygon in polygons:
        points = np.asarray(polygon, np.float32)
        pixels = cv2.perspectiveTransform(points[None], mm_to_image)[0] + shift
        cv2.fillPoly(image, [np.rint(pixels).astype(np.int32)], (30, 30, 30))
        regions.append(SimpleNamespace(polygon=polygon, width=np.ptp(points[:, 0]),
                                       height=np.ptp(points[:, 1]), closed=True, kind="rect"))
    layer = SimpleNamespace(index=5, name="test pattern", regions=regions)

    offsets = registration.snap_layer_translations(image, [layer], np.linalg.inv(mm_to_image))

    assert np.linalg.norm(np.asarray(offsets[5]["offset_px"]) - shift) <= 2
    assert offsets[5]["shape_match"] > offsets[5]["baseline_match"] + .08
    # The same source polygons are tested at their shifted photographic position.
    assert len(registration.match_closed_vectors(image, [layer], np.linalg.inv(mm_to_image),
                                                 layer_offsets_px=offsets)) == len(polygons)


def test_partly_cropped_right_marker_uses_its_visible_border():
    markers = plans.marker_geometry("TCE-CROPPED", 25, 20,
                                    {"aruco_mm": 4, "margin_mm": .5,
                                     "qr_module_mm": .25, "qr_position": "top-right"})
    marker = markers["aruco"][1]
    predicted = np.array([[15., 0., 130.], [0., 15., 110.], [0., 0., 1.]])
    actual = predicted.copy()
    actual[0, 2] += 11
    actual[1, 2] -= 9
    # Only the left 27 pixels of this 60-pixel fiducial fit in the photo.
    image = np.full((700, 550, 3), 175, np.uint8)
    for rect in marker["rects"]:
        x, y, w, h = rect["x"], rect["y"], rect["width"], rect["height"]
        polygon = np.float32([[(x, y), (x+w, y), (x+w, y+h), (x, y+h)]])
        pixels = cv2.perspectiveTransform(polygon, actual)[0]
        cv2.fillPoly(image, [np.rint(pixels).astype(np.int32)], (20, 20, 20))

    observed = registration._partial_marker_edge(
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32),
        marker, predicted, 0, 0, True)

    assert observed is not None
    assert abs(observed["left_px"] - 523.5) < 3
    assert abs(observed["top_px"] - 33.5) < 3
    assert abs(observed["bottom_px"] - 93.5) < 3


def test_small_label_pixels_snap_as_one_file_feature():
    rects = [{"x": 10 + col * .22, "y": 10 + row * .22,
              "width": .18, "height": .18}
             for row in range(4) for col in range(6)
             if (row + 2 * col) % 5 != 0]
    mm_to_image = np.array([[15., 0., 100.], [0., 15., 80.], [0., 0., 1.]])
    shift = np.array([13, -11])
    image = np.full((500, 500, 3), 170, np.uint8)
    for rect in rects:
        x, y, w, h = rect["x"], rect["y"], rect["width"], rect["height"]
        polygon = np.float32([[(x, y), (x+w, y), (x+w, y+h), (x, y+h)]])
        pixels = cv2.perspectiveTransform(polygon, mm_to_image)[0] + shift
        cv2.fillPoly(image, [np.rint(pixels).astype(np.int32)], (25, 25, 25))
    markers = {"extent": {"min_x": 0, "max_x": 50}, "aruco": []}

    result = registration.snap_marker_features(image, markers, rects,
                                               np.linalg.inv(mm_to_image), 0, 0)

    assert "label:0" in result
    assert np.linalg.norm(np.asarray(result["label:0"]["offset_px"]) - shift) < 3


def test_reflected_and_scaled_shapes_can_snap_the_shared_translation():
    polygons = [[(0, 0), (12, 0), (5, 9)],
                [(25, 4), (36, 4), (39, 10), (33, 17), (23, 14)]]
    actual = np.array([[-12, 0, 580], [0, 12, 100], [0, 0, 1]], float)
    initial = np.array([[-12, 0, 555], [0, 12, 85], [0, 0, 1]], float)
    image = np.full((450, 650, 3), 200, np.uint8)
    regions = []
    for polygon in polygons:
        pts = np.float32(polygon)
        projected = cv2.perspectiveTransform(pts[None], actual)[0]
        cv2.fillPoly(image, [projected.astype(np.int32)], (35, 35, 35))
        regions.append(SimpleNamespace(polygon=polygon, width=np.ptp(pts[:, 0]), height=np.ptp(pts[:, 1])))
    layer = SimpleNamespace(index=1, name="art", regions=regions)

    candidates = registration.snap_translations(image, [layer], np.linalg.inv(initial))

    assert any(np.linalg.norm(np.asarray(item["shift_px"]) - [25, 15]) < 6 and item["support_count"] >= 2
               for item in candidates)


def test_markerless_blank_photo_never_fabricates_alignment():
    layer = SimpleNamespace(name="art", regions=[SimpleNamespace(
        polygon=polygon, width=10, height=10) for polygon in
        [[(0, 0), (10, 0), (5, 10)], [(20, 0), (30, 0), (25, 10)], [(0, 20), (10, 20), (5, 30)]]])
    assert registration.register_geometry(np.full((500, 500, 3), 180, np.uint8), [layer]) is None


def test_ambiguous_art_offers_a_single_detail_to_place_manually():
    image = np.full((450, 600, 3), 190, np.uint8)
    cv2.rectangle(image, (100, 120), (220, 220), (30, 30, 30), -1)
    layer = SimpleNamespace(index=8, name="outline", regions=[SimpleNamespace(
        polygon=[(0, 0), (12, 0), (12, 10), (0, 10)], width=12, height=10)])

    assert registration.register_geometry(image, [layer]) is None
    suggestions = registration.suggest_element_anchors(image, [layer])

    assert suggestions and suggestions[0]["layer_index"] == 8
    assert suggestions[0]["region_index"] == 0
    assert all(0 <= coordinate <= 1 for point in suggestions[0]["corners_fraction"] for coordinate in point)


def test_anchor_suggestions_use_full_resolution_coordinates_and_skip_tiny_rectangles():
    image = np.full((2000, 2500, 3), 180, np.uint8)
    cv2.rectangle(image, (800, 500), (1100, 750), (20, 20, 20), -1)
    cv2.rectangle(image, (100, 100), (130, 125), (20, 20, 20), -1)
    layer = SimpleNamespace(index=8, name="rectangle", regions=[SimpleNamespace(
        polygon=[(0, 0), (12, 0), (12, 10), (0, 10)], width=12, height=10)])

    suggestions = registration.suggest_element_anchors(image, [layer])

    assert suggestions
    center = suggestions[0]["center_px"]
    assert np.linalg.norm(np.array(center) - [950, 625]) < 10
    points = np.array(suggestions[0]["corners_fraction"]) * [2500, 2000]
    assert np.ptp(points[:, 0]) > 200 and np.ptp(points[:, 1]) > 150


def test_one_asymmetric_detail_can_define_the_initial_file_to_photo_transform():
    polygon = [(0, 0), (12, 1), (15, 7), (9, 15), (2, 11), (-2, 5)]
    mm_to_image = np.array([[12, 1.2, 180], [-.4, 11.7, 140], [0, 0, 1]], float)
    image = np.full((500, 600, 3), 200, np.uint8)
    projected = cv2.perspectiveTransform(np.float32(polygon)[None], mm_to_image)[0]
    cv2.fillPoly(image, [projected.astype(np.int32)], (40, 40, 40))
    layer = SimpleNamespace(name="distinctive", regions=[SimpleNamespace(
        polygon=polygon, width=17, height=15)])

    result = registration.register_geometry(image, [layer])

    assert result is not None and result.method == "single distinctive detail"
    assert len(result.matches) == 1 and result.residual_px < 3
    for point in [(0, 0), (9, 15)]:
        wanted = cv2.perspectiveTransform(np.float32([[point]]), mm_to_image)[0, 0]
        found = cv2.perspectiveTransform(np.float32([[point]]), np.linalg.inv(result.image_to_mm))[0, 0]
        assert np.linalg.norm(wanted - found) < 5


def test_closed_vectors_are_checked_individually_even_on_one_layer():
    image = np.full((420, 600, 3), 190, np.uint8)
    regions = []
    for x in (10, 30, 50):
        polygon = [(x, 10), (x + 8, 10), (x + 8, 18), (x, 18)]
        regions.append(SimpleNamespace(kind="rect", closed=True, polygon=polygon, width=8, height=8))
    for polygon in (regions[0].polygon, regions[2].polygon):
        points = cv2.perspectiveTransform(np.float32(polygon)[None],
                                          np.array([[6, 0, 40], [0, 6, 60], [0, 0, 1]], float))[0]
        cv2.fillPoly(image, [np.rint(points).astype(np.int32)], (30, 30, 30))
    layer = SimpleNamespace(index=7, name="three squares", regions=regions)
    image_to_mm = np.linalg.inv(np.array([[6, 0, 40], [0, 6, 60], [0, 0, 1]], float))

    matches = registration.match_closed_vectors(image, [layer], image_to_mm)

    assert [item["region_index"] for item in matches] == [0, 1, 2]
    assert [item["status"] for item in matches] == ["found", "uncertain", "found"]
    assert all(item["size_mm"] == [8, 8] for item in matches)
