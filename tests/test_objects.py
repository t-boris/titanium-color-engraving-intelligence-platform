"""The objects of a picture of people for colouring it like a colouring book: parts, lips, eyes and background pieces."""
import cv2
import numpy as np
import pytest

from titanium_platform import color, objects, people

H, W = 200, 240
BACKGROUND, HAIR, BODY, FACE, CLOTHES, OTHER = (people.PARTS.index(p) for p in ("background", "hair", "body_skin", "face_skin", "clothes", "other"))
SKIN, RED, BLUE, YELLOW, BROWN, DARK = (225, 170, 140), (190, 40, 60), (40, 80, 200), (230, 200, 40), (110, 70, 40), (30, 30, 35)
FACE_ELLIPSE = ((120, 110), (60, 75))
LIPS_ELLIPSE = ((120, 140), (20, 7))
SPECK = (slice(152, 156), slice(118, 122))       # red, inside the lips ellipse of the detector but below the lips, apart from them
CHEEK = (slice(110, 114), slice(70, 74))         # red, on the cheek, outside the lips ellipse


def face_row(eyes=((95, 95), (145, 95)), mouth=((95, 140), (145, 140)), box=(60, 35, 120, 150), nose=(120, 120)):
    """One YuNet row: box x, y, w, h, the five landmarks (eyes, nose, mouth corners), the score."""
    return np.array([*box, *eyes[0], *eyes[1], *nose, *mouth[0], *mouth[1], 0.9], np.float32)


def detector(*rows):
    """A face detector that finds ``rows`` in the upright picture and nothing in its turned copies (searched after it)."""
    calls = []

    def detect(bgr):
        calls.append(bgr.shape)
        return np.array(rows, np.float32).reshape(-1, 15) if len(calls) % 4 == 1 else np.zeros((0, 15), np.float32)
    return detect


NO_FACE = detector()


def item_of(rgb, parts, alpha=None):
    """An item as ``decode_upload`` gives it, with the people model's scores already in it: one-hot scores whose largest is ``parts``."""
    lab = color.srgb8_to_lab(rgb.reshape(-1, 3)).reshape(rgb.shape)
    scores = np.eye(len(people.PARTS), dtype=np.float32)[cv2.resize(parts, (256, 256), interpolation=cv2.INTER_NEAREST)]
    alpha = np.ones(parts.shape, np.float32) if alpha is None else alpha.astype(np.float32)
    return {"picture": (lab[..., 0] / 100).astype(np.float32), "alpha": alpha, "lab": lab, "bgr_full": np.ascontiguousarray(rgb[..., ::-1]),
            "part_scores": scores}


def portrait(*, lips=True, glasses=False, grey=False):
    """A face (face skin) on a blue background with red lips, a red speck under them and one on the cheek; with ``glasses`` the
    subject's right eye (on the left) is behind a dark lens of the part "other"."""
    rgb = np.empty((H, W, 3), np.uint8)
    rgb[:] = BLUE
    parts = np.full((H, W), BACKGROUND, np.uint8)
    cv2.ellipse(parts, *FACE_ELLIPSE, 0, 0, 360, FACE, -1)
    cv2.ellipse(rgb, *FACE_ELLIPSE, 0, 0, 360, SKIN, -1)
    if lips:
        cv2.ellipse(rgb, *LIPS_ELLIPSE, 0, 0, 360, RED, -1)
        rgb[SPECK] = RED
        rgb[CHEEK] = RED
    if glasses:
        parts[80:111, 72:119] = OTHER
        rgb[80:111, 72:119] = DARK
    if grey:
        rgb[:] = cv2.cvtColor(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
    return item_of(rgb, parts)


def by_kind(found):
    return {(o["kind"], o["piece"]): o for o in found["objects"]}


def test_the_parts_become_objects_in_the_order_of_kinds_whose_shares_cover_the_opaque_picture():
    rgb, parts = np.empty((H, W, 3), np.uint8), np.empty((H, W), np.uint8)
    for (x0, x1), part, colour in zip(((0, 40), (40, 80), (80, 120), (120, 160), (160, 200), (200, 240)),
                                      (BACKGROUND, HAIR, BODY, FACE, CLOTHES, OTHER), (BLUE, BROWN, SKIN, (235, 190, 160), DARK, YELLOW)):
        rgb[:, x0:x1], parts[:, x0:x1] = colour, part
    found = objects.find(item_of(rgb, parts), detect=NO_FACE)
    kinds = [o["kind"] for o in found["objects"]]
    assert kinds == ["background", "hair", "face_skin", "body_skin", "clothes", "other"]          # the order of KINDS, not of PARTS
    assert [o["id"] for o in found["objects"]] == list(range(6)) and all(o["piece"] == 0 for o in found["objects"])
    assert sum(o["share"] for o in found["objects"]) == pytest.approx(1.0, abs=1e-3)
    assert all(o["share"] == pytest.approx(1 / 6, abs=0.01) for o in found["objects"])
    labels = found["labels"]
    assert labels.dtype == np.int32 and labels.shape == (H, W) and labels.min() == 0
    hair = by_kind(found)[("hair", 0)]
    assert labels[100, 60] == hair["id"] and hair["box"][1] == 0 and hair["box"][3] == H and abs(hair["box"][0] - 40) <= 1 and abs(hair["box"][2] - 80) <= 1
    assert np.allclose(hair["lab"], color.srgb8_to_lab(np.array([BROWN]))[0], atol=2)            # a border column may join it
    assert np.allclose([int(hair["hex"][i:i + 2], 16) for i in (1, 3, 5)], BROWN, atol=6)


def test_the_background_splits_into_pieces_by_colour_the_largest_first():
    rgb = np.empty((H, W, 3), np.uint8)
    rgb[:, :140], rgb[:, 140:] = BLUE, YELLOW                        # the blue side is the larger
    parts = np.full((H, W), BACKGROUND, np.uint8)
    cv2.ellipse(parts, *FACE_ELLIPSE, 0, 0, 360, FACE, -1)
    cv2.ellipse(rgb, *FACE_ELLIPSE, 0, 0, 360, SKIN, -1)
    found = objects.find(item_of(rgb, parts), detect=NO_FACE)
    pieces = [o for o in found["objects"] if o["kind"] == "background"]
    assert [(o["id"], o["piece"]) for o in pieces] == [(0, 0), (1, 1)]
    blue, yellow = (color.srgb8_to_lab(np.array([c]))[0] for c in (BLUE, YELLOW))
    assert np.allclose(pieces[0]["lab"], blue, atol=2) and np.allclose(pieces[1]["lab"], yellow, atol=2)
    assert found["labels"][100, 10] == 0 and found["labels"][100, 230] == 1 and found["labels"][110, 120] == by_kind(found)[("face_skin", 0)]["id"]

    rgb[:] = BLUE                                                    # one colour: one piece
    cv2.ellipse(rgb, *FACE_ELLIPSE, 0, 0, 360, SKIN, -1)
    one = objects.find(item_of(rgb, parts), detect=NO_FACE)
    assert [o["piece"] for o in one["objects"] if o["kind"] == "background"] == [0]


def test_the_lips_are_the_red_of_the_mouth_and_not_a_red_speck_under_them_or_on_the_cheek():
    item = portrait()
    found = objects.find(item, detect=detector(face_row()))
    assert found["faces"] == 1 and found["notes"] == [] and found["face_error"] is None
    objs = by_kind(found)
    lips, skin = objs[("lips", 0)], objs[("face_skin", 0)]
    labels = found["labels"]
    painted = np.zeros((H, W), np.uint8)
    cv2.ellipse(painted, *LIPS_ELLIPSE, 0, 0, 360, 1, -1)
    got = labels == lips["id"]
    assert (got & (painted > 0)).sum() >= 0.9 * painted.sum() and (got & (painted == 0)).sum() <= 0.1 * painted.sum()
    assert (labels[SPECK] == skin["id"]).all() and (labels[CHEEK] == skin["id"]).all()
    assert lips["box"][0] >= 98 and lips["box"][2] <= 143 and lips["box"][1] >= 131 and lips["box"][3] <= 150
    assert lips["lab"][1] > 40                                      # red


def test_lips_of_a_grey_picture_cannot_be_told_from_the_skin_and_the_note_says_so():
    found = objects.find(portrait(grey=True), detect=detector(face_row()))
    assert "lips" not in [o["kind"] for o in found["objects"]] and found["notes"] == ["The lips could not be told from the skin by their colour."]


def test_an_eye_is_an_object_where_it_is_visible_and_an_eye_behind_glasses_stays_other():
    found = objects.find(portrait(glasses=True), detect=detector(face_row()))
    objs = by_kind(found)
    eyes, other = objs[("eyes", 0)], objs[("other", 0)]
    labels = found["labels"]
    assert labels[95, 145] == eyes["id"] and labels[95, 95] == other["id"]
    assert eyes["box"][0] >= 128 and eyes["box"][2] <= 162                 # only the subject's left eye
    assert "1 eye is behind glasses or something else worn: they stay in the part 'other'." in found["notes"]
    both = objects.find(portrait(), detect=detector(face_row()))
    assert by_kind(both)[("eyes", 0)]["box"][0] <= 80 and both["labels"][95, 95] == both["labels"][95, 145]


def test_without_a_face_there_are_no_lips_or_eyes_and_the_note_says_why():
    found = objects.find(portrait(), detect=NO_FACE)
    assert found["faces"] == 0 and [o["kind"] for o in found["objects"]] == ["background", "face_skin"]
    assert found["notes"] == ["No face was found, so there are no lips or eyes."]

    def broken(bgr):
        raise RuntimeError("no model")
    failed = objects.find(portrait(), detect=broken)
    assert failed["faces"] == 0 and failed["notes"] == ["The face search could not run, so there are no lips or eyes."] and "no model" in failed["face_error"]


def test_transparent_pixels_belong_to_no_object_and_shares_are_of_the_opaque_picture():
    item = portrait()
    item["alpha"][:, :60] = 0.0
    item["alpha"][:, 60:70] = 0.4                                    # less than half opaque: empty
    found = objects.find(item, detect=detector(face_row()))
    labels = found["labels"]
    assert (labels[:, :70] == -1).all() and (labels[:, 70:] >= 0).all()
    assert sum(o["share"] for o in found["objects"]) == pytest.approx(1.0, abs=1e-3)
    background = by_kind(found)[("background", 0)]
    assert background["share"] == pytest.approx((labels == background["id"]).sum() / labels[:, 70:].size, abs=1e-4)
    assert background["box"][0] >= 70
    shown = objects.overlay(item, found)
    grey = np.round(np.clip(item["picture"], 0, 1) * 255)
    assert shown.shape == (H, W, 3) and shown.dtype == np.uint8
    assert (shown[:, :70] == grey[:, :70, None]).all() and not (shown[:, 80:] == grey[:, 80:, None]).all()


def test_an_object_under_half_a_percent_joins_its_neighbour_and_tiny_lips_are_dropped():
    rgb = portrait(lips=False)["bgr_full"][..., ::-1].copy()
    cv2.ellipse(rgb, (120, 140), (5, 2), 0, 0, 360, RED, -1)         # lips of a small mouth
    parts = np.full((H, W), BACKGROUND, np.uint8)
    cv2.ellipse(parts, *FACE_ELLIPSE, 0, 0, 360, FACE, -1)
    parts[:30, :] = HAIR
    rgb[:30, :] = BROWN
    parts[10:20, 100:110] = CLOTHES                                   # 100 px: 0.2 % of the picture, inside the hair
    rgb[10:20, 100:110] = DARK
    small_mouth = face_row(mouth=((114, 140), (126, 140)))            # a mouth 12 px wide: its lips are under 0.5 %
    found = objects.find(item_of(rgb, parts), detect=detector(small_mouth))
    kinds = [o["kind"] for o in found["objects"]]
    assert "clothes" not in kinds and "lips" not in kinds
    objs = by_kind(found)
    assert (found["labels"][12:18, 102:108] == objs[("hair", 0)]["id"]).all()
    assert found["labels"][140, 120] == objs[("face_skin", 0)]["id"]
    assert "The lips are too small to be an object." in found["notes"]


def test_the_same_picture_always_gives_the_same_objects_and_ids():
    first = objects.find(portrait(glasses=True), detect=detector(face_row()))
    second = objects.find(portrait(glasses=True), detect=detector(face_row()))
    assert np.array_equal(first["labels"], second["labels"]) and first["objects"] == second["objects"]
    keys = [(objects.KINDS.index(o["kind"]), o["piece"]) for o in first["objects"]]
    assert keys == sorted(keys) and [o["id"] for o in first["objects"]] == list(range(len(keys)))
    assert set(np.unique(first["labels"])) == set(range(len(keys)))


def test_the_people_model_runs_once_when_the_item_has_no_scores_yet(monkeypatch):
    item = portrait(lips=False)
    scores = item.pop("part_scores")
    calls = []

    def model(bgr):
        calls.append(bgr.shape)
        return scores
    monkeypatch.setattr(people, "scores", model)
    objects.find(item, detect=NO_FACE)
    objects.find(item, detect=NO_FACE)
    assert calls == [(H, W, 3)] and item["part_scores"] is scores
