"""Faces, eyes and lips as important areas of a photograph (REQ-033, DEC-074)."""
import hashlib
import math
import re

import cv2
import numpy as np
import pytest

from titanium_platform import faces


def picture(h=240, w=320):
    """A face-free picture: a gradient with a few shapes."""
    img = np.zeros((h, w, 3), np.uint8)
    img[...] = np.linspace(40, 220, w, dtype=np.uint8)[None, :, None]
    cv2.circle(img, (80, 120), 40, (200, 60, 50), -1)
    cv2.rectangle(img, (180, 60), (280, 180), (40, 90, 200), -1)
    return img


def row(box, eyes, nose, mouth, score):
    """One YuNet result row: box x, y, w, h, the five landmarks, the score."""
    return np.array([*box, *eyes[0], *eyes[1], *nose, *mouth[0], *mouth[1], score], np.float32)


UPRIGHT = row((100, 60, 120, 150), ((135, 110), (185, 110)), (160, 140), ((140, 170), (180, 170)), 0.9)


def test_the_yunet_model_ships_in_the_package_with_its_licence_and_loads():
    assert faces.MODEL.is_file() and faces.MODEL.parent.name == "models"
    data = faces.MODEL.read_bytes()
    readme = (faces.MODEL.parent / "README.md").read_text(encoding="utf-8")
    assert len(data) > 200_000 and not data.startswith(b"version https://git-lfs")       # the model, not an LFS pointer
    assert hashlib.sha256(data).hexdigest() in readme and str(len(data)) in readme
    assert re.search(r"Licence: MIT", readme) and "Shiqi Yu" in (faces.MODEL.parent / "LICENSE-face_detection_yunet").read_text()
    detector = cv2.FaceDetectorYN.create(str(faces.MODEL), "", (320, 240), faces.SCORE_THRESHOLD, faces.NMS_THRESHOLD, 5000)
    _, found = detector.detect(cv2.cvtColor(picture(), cv2.COLOR_RGB2BGR))
    assert found is None or len(found) == 0


def test_a_picture_without_a_face_gives_no_areas_and_says_that_no_face_was_found():
    search = faces.important_areas(picture())
    assert search.areas == [] and search.faces == 0 and not search.face_found and search.error is None


def test_landmarks_become_the_face_box_an_ellipse_around_each_eye_and_lips_spanning_the_mouth_corners():
    box = [(100, 60), (220, 60), (220, 210), (100, 210)]
    areas = faces.face_areas(box, [(135, 110), (185, 110)], [(140, 170), (180, 170)], 0.87)
    assert [a["kind"] for a in areas] == ["face", "eye", "eye", "lips"]
    assert all(a["source"] == "detected" and a["score"] == 0.87 for a in areas)
    assert areas[0]["polygon"] == [list(map(float, p)) for p in box]
    right, left = areas[1]["ellipse"], areas[2]["ellipse"]
    assert right["center"] == [135, 110] and left["center"] == [185, 110] and right["angle"] == 0
    assert right["axes"] == pytest.approx([faces.EYE_AXES[0] * 50, faces.EYE_AXES[1] * 50])     # sized by the eye distance
    lips = areas[3]["ellipse"]
    assert lips["center"] == [160, 170] and lips["angle"] == 0
    assert lips["axes"][0] > 20                                                    # spans both corners (20 px from the centre)
    assert lips["axes"][1] == pytest.approx(faces.LIPS_AXES[1] * 40)                # height proportional to the mouth width
    tilted = faces.face_areas(box, [(130, 100), (180, 130)], [(140, 170), (170, 188)], 0.8)
    assert tilted[1]["ellipse"]["angle"] == pytest.approx(math.degrees(math.atan2(30, 50)), abs=0.01)
    assert tilted[3]["ellipse"]["angle"] == pytest.approx(math.degrees(math.atan2(18, 30)), abs=0.01)


def test_a_face_found_only_in_the_turned_picture_is_mapped_back_onto_the_picture():
    img = picture(200, 300)
    img[:10, :10] = (255, 0, 255)              # a mark in the top-left corner shows how the detector's picture is turned
    calls = []

    def detect(bgr):
        calls.append(bgr.shape[:2])
        h, w = bgr.shape[:2]
        if (bgr[-5, -5] == (255, 0, 255)).all():     # turned by 180 degrees: the face is upright here
            return UPRIGHT[None, :]
        return np.zeros((0, 15), np.float32)

    search = faces.important_areas(img, detect=detect)
    assert calls == [(200, 300), (300, 200), (200, 300), (300, 200)]             # upright and turned by 90, 180, 270
    assert search.faces == 1 and search.error is None
    face, right_eye, _, lips = search.areas
    assert sorted(map(tuple, face["polygon"])) == sorted([(300 - 100, 200 - 60), (300 - 220, 200 - 60),
                                                          (300 - 220, 200 - 210), (300 - 100, 200 - 210)])
    assert right_eye["ellipse"]["center"] == [300 - 135, 200 - 110]
    assert lips["ellipse"]["center"] == [300 - 160, 200 - 170]


def test_a_face_found_in_several_turns_is_kept_once_from_the_turn_that_scored_it_highest():
    img = picture(300, 300)
    turned = []

    def detect(bgr):
        turned.append(len(turned))
        score = {0: 0.7, 1: 0.65, 2: 0.95, 3: 0.4}[turned[-1]]                    # the last is below the threshold
        return row((100, 60, 120, 150), ((135, 110), (185, 110)), (160, 140), ((140, 170), (180, 170)), score)[None, :]

    search = faces.important_areas(img, detect=detect)
    assert search.faces == 1 and {a["score"] for a in search.areas} == {0.95}
    assert search.areas[1]["ellipse"]["center"] == [300 - 135, 300 - 110]          # the 180-degree turn's landmarks


def test_detector_failures_never_raise_to_the_caller():
    def broken(bgr):
        raise cv2.error("model cannot be read")

    search = faces.important_areas(picture(), detect=broken)
    assert search.areas == [] and search.faces == 0 and "model cannot be read" in search.error
    assert faces.important_areas(np.zeros((10, 10), np.uint8)).error                  # not an RGB picture
    assert faces.important_areas("not a picture").error


def test_areas_marked_by_hand_are_checked_and_normalised():
    ellipse = faces.check_area({"ellipse": {"center": [10, 20], "axes": [5, 3]}})
    assert ellipse == {"kind": "manual", "source": "manual", "score": None,
                       "ellipse": {"center": [10.0, 20.0], "axes": [5.0, 3.0], "angle": 0.0}}
    kept = faces.check_area({"kind": "eye", "source": "detected", "score": 0.9, "polygon": [[0, 0], [4, 0], [4, 4]]})
    assert kept["kind"] == "eye" and kept["source"] == "detected" and kept["polygon"][2] == [4.0, 4.0]
    for bad in ({}, {"polygon": [[0, 0], [1, 1]]}, {"ellipse": {"center": [0, 0], "axes": [0, 3]}},
                {"ellipse": {"center": [0, 0], "axes": [1, 1]}, "polygon": [[0, 0], [1, 0], [0, 1]]},
                {"kind": "nose", "polygon": [[0, 0], [1, 0], [0, 1]]}, {"source": "guess", "polygon": [[0, 0], [1, 0], [0, 1]]},
                {"ellipse": {"center": [0, float("nan")], "axes": [1, 1]}}, "ellipse"):
        with pytest.raises(ValueError):
            faces.check_area(bad)


def test_an_area_covers_the_pixels_inside_it_and_on_its_outline():
    ellipse = faces.check_area({"ellipse": {"center": [50, 40], "axes": [20, 10], "angle": 30}})
    mask = faces.area_mask(ellipse, (80, 100))
    assert math.pi * 20 * 10 <= mask.sum() <= math.pi * 21 * 11
    assert mask[40, 50] and mask[40 + 9, 50 + 16] and not mask[40, 50 + 18]            # the long axis turned 30 degrees, y down
    square = faces.area_mask(faces.check_area({"polygon": [[10, 10], [30, 10], [30, 20], [10, 20]]}), (80, 100))
    assert 200 <= square.sum() <= 21 * 11 and square[15, 20] and not square[25, 20]
