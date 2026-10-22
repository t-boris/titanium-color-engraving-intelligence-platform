"""Colouring a picture by its objects (``colouring``, 0.21.0) on a made-up scale whose colours are known: gold through brown to dark, then a
swing to blue and violet. Min 0 % and Max 50 %: grey 255 is 0 % power, grey 0 is 50 %."""
import numpy as np
import pytest
from scipy import stats

from titanium_platform import colouring, drawing, grayscale, prediction

LO, HI = 0.0, 50.0
# cream, straw, gold, brown, dark brown; then a jump to light blue, blue, violet, dark violet
SCALE = prediction.Curve(powers=np.array([0, 6, 12, 18, 24, 26, 32, 40, 50], float),
                         labs=np.array([(90, 2, 10), (82, 4, 30), (72, 8, 45), (58, 14, 30), (45, 10, 18),
                                        (70, -6, -28), (55, 4, -40), (42, 22, -38), (30, 14, -26)], float),
                         points=(), referenced=True, left_out=0)


def scale():
    return grayscale.usable_greys(SCALE, LO, HI)


def grey_at(power):
    greys, _ = scale()
    return int(np.argmin(np.abs(grayscale.grey_power(greys / 255, LO, HI) - power)))


def test_the_path_through_a_main_colour_stays_in_its_family_by_small_steps_lightness_one_way_on_each_side():
    greys, labs = scale()
    main = grey_at(12)                                                           # gold
    on = colouring.path_through(labs, main)
    way = labs[on]
    assert main in on and np.all(np.linalg.norm(np.diff(way, axis=0), axis=1) <= colouring.MAX_STEP + 1e-9)
    assert np.all(np.diff(way[:, 0]) <= drawing.PATH_RISE_L)                     # lightest first, never rising
    powers = grayscale.grey_power(greys[on] / 255, LO, HI)
    assert powers.max() < 25                                                     # the blues are another family: not reached from gold
    blue = colouring.path_through(labs, grey_at(32))
    assert grayscale.grey_power(greys[blue] / 255, LO, HI).min() > 24            # and the blue path keeps to the blues


def portrait(n=120):
    """A picture of two objects with their own light and dark: a face (a gradient) on the left, a background (another gradient) on the
    right; every pixel opaque."""
    lab = np.zeros((n, n, 3))
    ramp = np.linspace(80, 40, n)[:, None]
    lab[:, : n // 2, 0] = ramp
    lab[:, n // 2:, 0] = ramp[::-1] * 0.8
    labels = np.zeros((n, n), np.int32)
    labels[:, n // 2:] = 1
    objects = [{"id": 0, "kind": "face_skin", "piece": 0, "share": 0.5, "lab": [60, 0, 0]},
               {"id": 1, "kind": "background", "piece": 0, "share": 0.5, "lab": [48, 0, 0]}]
    return lab, np.ones((n, n), bool), labels, objects


def test_an_object_with_a_main_colour_keeps_its_drawing_in_that_colours_family_and_the_others_keep_theirs():
    lab, opaque, labels, objects = portrait()
    base = drawing.choose(lab, opaque, SCALE, LO, HI, 6.0)
    got = colouring.colour(lab, opaque, labels, objects, {"background": {"power": 32, "shift": 0}}, SCALE, LO, HI, 6.0, base)
    face, back = labels == 0, labels == 1
    assert np.array_equal(got["grey8"][face], base["grey8"][face])               # «Авто»: as the whole picture laid along one path
    powers = grayscale.grey_power(got["grey8"][back] / 255, LO, HI)
    assert powers.min() > 24                                                     # the background in the blues only
    middle = np.median(got["lab"][back], axis=0)
    (report,) = got["objects"]
    assert report["key"] == "background" and np.linalg.norm(middle - report["lab"]) < 6       # its middle tone on the main colour
    assert stats.spearmanr(lab[back][:, 0], got["lab"][back][:, 0])[0] > 0.9                   # its light and dark in order
    assert got["grey8"].shape == lab.shape[:2] and got["order"] is not None


def test_lighter_and_darker_move_the_objects_tones_along_its_path():
    lab, opaque, labels, objects = portrait()
    base = drawing.choose(lab, opaque, SCALE, LO, HI, 6.0)
    light = {s: colouring.colour(lab, opaque, labels, objects, {"face_skin": {"power": 12, "shift": s}}, SCALE, LO, HI, 6.0, base)["lab"][labels == 0][:, 0].mean()
             for s in (-1.0, 0.0, 1.0)}
    assert light[-1.0] < light[0.0] < light[1.0]


def test_candidates_are_the_scales_colours_apart_from_each_other_lightest_first():
    options = colouring.candidates(SCALE, LO, HI)
    labs = np.array([c["lab"] for c in options])
    assert len(options) >= 5 and np.all(np.diff(labs[:, 0]) <= 0)
    far = np.linalg.norm(labs[:, None] - labs[None], axis=-1)[np.triu_indices(len(labs), 1)]
    assert far.min() >= colouring.CANDIDATE_DE - 0.2                             # rounded to 0.1 in the answer
    assert all(LO <= c["power"] <= HI and c["hex"].startswith("#") for c in options)


OBJECTS = [{"id": 0, "kind": "background", "piece": 0, "share": 0.4, "lab": [45, 0, -10]},
           {"id": 1, "kind": "background", "piece": 1, "share": 0.2, "lab": [80, 0, 0]},
           {"id": 2, "kind": "face_skin", "piece": 0, "share": 0.25, "lab": [70, 12, 18]},
           {"id": 3, "kind": "lips", "piece": 0, "share": 0.02, "lab": [50, 30, 15]},
           {"id": 4, "kind": "hair", "piece": 0, "share": 0.13, "lab": [35, 8, 12]}]


def test_themes_give_every_object_a_main_colour_of_the_scale():
    options = colouring.candidates(SCALE, LO, HI)
    powers = {c["power"]: c for c in options}
    warm = colouring.theme("warm", OBJECTS, options)
    assert set(warm) == {"background", "background-1", "face_skin", "lips", "hair"}
    assert all(set(v) == {"power", "shift"} and v["power"] in powers for v in warm.values())
    lightest_warm = max((c for c in options if c["chroma"] >= colouring.COLOURED and 15 <= c["hue"] <= 110), key=lambda c: c["lab"][0])
    assert warm["face_skin"]["power"] == lightest_warm["power"]                  # the skin the lightest warm colour
    assert all(15 <= powers[v["power"]]["hue"] <= 110 for v in warm.values())
    cool = colouring.theme("cool", OBJECTS, options)
    assert cool["face_skin"] == warm["face_skin"] and all(160 <= powers[cool[k]["power"]]["hue"] <= 330 for k in ("background", "hair"))
    contrast = colouring.theme("contrast", OBJECTS, options)
    first, second = powers[contrast["background"]["power"]], powers[contrast["face_skin"]["power"]]
    assert np.linalg.norm(np.subtract(first["lab"], second["lab"])) > 30
    assert colouring.theme("random", OBJECTS, options, seed=3) == colouring.theme("random", OBJECTS, options, seed=3)
    assert any(colouring.theme("random", OBJECTS, options, seed=s) != colouring.theme("random", OBJECTS, options, seed=3) for s in range(4, 8))
    with pytest.raises(ValueError):
        colouring.theme("pastel", OBJECTS, options)
