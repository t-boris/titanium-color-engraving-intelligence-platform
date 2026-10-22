"""The parts of a picture (``people``) and the rules that give each part its own greys on a scale (``picture_rules``), REQ-062, DEC-105.
The rules run on a made-up scale whose colours are known: light grey, straw, violet, dark grey, blue, darker grey from 0 to 50 % power."""
import numpy as np
import pytest

from titanium_platform import grayscale, people, picture_rules as pr, prediction

POWERS = [0, 10, 20, 30, 40, 50]
LABS = [(80, 0, 0), (70, 5, 30), (50, 20, -40), (40, 0, 2), (55, -10, -30), (30, 1, 1)]
CURVE = prediction.Curve(powers=np.array(POWERS, float), labs=np.array(LABS, float), points=(), referenced=True, left_out=0)
LO, HI = 0.0, 50.0
FACE, CLOTHES = people.PARTS.index("face_skin"), people.PARTS.index("clothes")


def grey_of_power(power):
    return round(255 * (1 - (power - LO) / (HI - LO)))


def picture():
    """4 x 4: face skin on the left two columns (two lightnesses), clothes on the right two; every grey 128 as LightBurn sees it."""
    lab = np.zeros((4, 4, 3))
    lab[:, :2] = (75, 15, 20)
    lab[2:, :2] = (60, 15, 20)
    lab[:, 2:] = (50, 10, 10)
    parts = np.full((4, 4), FACE, np.uint8)
    parts[:, 2:] = CLOTHES
    return lab, np.full((4, 4), 128, np.uint8), parts


# -- the rules as given ----------------------------------------------------------------------------------------------------------------
def test_rules_are_checked_and_kept_as_plain_values():
    assert pr.check(None) == []
    assert pr.check([{"part": "clothes", "kind": "colour", "lab": [40, 40, -40], "extra": 1}, {"part": "hair", "kind": "neutral", "range": [20, 60]}]) == \
        [{"part": "clothes", "kind": "colour", "lab": [40.0, 40.0, -40.0]}, {"part": "hair", "kind": "neutral", "range": [20.0, 60.0]}]


@pytest.mark.parametrize("rules, message", [
    ("clothes", "the rules of the parts must be a list of at most 6"),
    (["clothes"], "each rule must name a part and what to do with it"),
    ([{"part": "dress", "kind": "even"}], "a rule must name one of the parts background, hair, body_skin, face_skin, clothes, other, each once"),
    ([{"part": "hair", "kind": "as_is"}, {"part": "hair", "kind": "photo"}], "a rule must name one of the parts background, hair, body_skin, face_skin, clothes, other, each once"),
    ([{"part": "hair", "kind": "glow"}], "a rule must be one of as_is, photo, neutral, colour, even"),
    ([{"part": "hair", "kind": "even", "lab": [120, 0, 0]}], "a target colour must be L*a*b*: L 0..100, a and b -128..128"),
    ([{"part": "hair", "kind": "colour", "lab": [50, True, 0]}], "a target colour must be L*a*b*: L 0..100, a and b -128..128"),
    ([{"part": "hair", "kind": "neutral", "range": [60, 20]}], "the lightness range of black and white must be two L* values, 0 <= from < to <= 100"),
])
def test_a_rule_that_cannot_be_applied_is_refused_with_the_reason(rules, message):
    with pytest.raises(pr.RuleError, match="^" + message.replace("*", r"\*").replace(".", r"\.") + "$"):
        pr.check(rules)


# -- the greys of each rule ------------------------------------------------------------------------------------------------------------
def test_without_rules_every_pixel_keeps_its_grey_and_a_part_without_a_rule_is_untouched():
    lab, base, parts = picture()
    assert np.array_equal(pr.greys(lab, base, parts, [], CURVE, LO, HI)["grey8"], base)
    done = pr.greys(lab, base, parts, [{"part": "hair", "kind": "even", "lab": [50, 20, -40]}], CURVE, LO, HI)
    assert np.array_equal(done["grey8"], base) and done["rules"] == [{"part": "hair", "kind": "even", "share": 0.0, "median_de": None}]


def test_one_even_tone_is_the_grey_whose_colour_is_nearest_the_target_inside_the_part_only():
    lab, base, parts = picture()
    done = pr.greys(lab, base, parts, [{"part": "clothes", "kind": "even", "lab": [50, 20, -40]}], CURVE, LO, HI)
    clothes = np.unique(done["grey8"][:, 2:])
    assert len(clothes) == 1 and abs(int(clothes[0]) - grey_of_power(20)) <= 2                       # violet is measured at 20 %
    assert np.array_equal(done["grey8"][:, :2], base[:, :2])
    assert done["rules"] == [{"part": "clothes", "kind": "even", "share": 0.5, "median_de": pytest.approx(0, abs=1.5)}]


def test_black_and_white_uses_only_the_greys_whose_colour_is_nearly_grey_and_keeps_light_and_dark():
    lab, base, parts = picture()
    table = grayscale.scale_of_greys(CURVE, LO, HI)
    neutral = pr.neutral_levels(table)
    assert len(neutral) >= pr.NEUTRAL_LEAST and all(np.hypot(*table["levels"][lv]["lab"][1:]) <= pr.NEUTRAL_CHROMA for lv in neutral)
    done = pr.greys(lab, base, parts, [{"part": "face_skin", "kind": "neutral"}], CURVE, LO, HI)
    face = done["grey8"][:, :2]
    assert set(np.unique(face)) <= set(neutral)
    light, dark = (table["levels"][int(face[row, 0])]["lab"][0] for row in (0, 3))
    assert light > dark                                                                               # the lighter rows stay lighter


def test_a_target_colour_keeps_the_parts_light_and_dark_around_it():
    lab, base, parts = picture()
    done = pr.greys(lab, base, parts, [{"part": "face_skin", "kind": "colour", "lab": [70, 5, 30]}], CURVE, LO, HI)
    table = grayscale.scale_of_greys(CURVE, LO, HI)
    light, dark = (table["levels"][int(done["grey8"][row, 0])]["lab"] for row in (0, 3))
    assert light[0] >= dark[0] and light[2] > 15                                                      # straw, lighter where the skin is lighter
    assert done["rules"][0]["share"] == 0.5 and done["rules"][0]["median_de"] is not None


# -- the parts -------------------------------------------------------------------------------------------------------------------------
def test_the_part_of_every_pixel_is_read_from_the_scores_at_any_size():
    scores = np.zeros((256, 256, 6), np.float32)
    scores[:, :128, FACE] = 1
    scores[:, 128:, CLOTHES] = 1
    parts = people.parts_at(scores, (100, 50))
    assert parts.shape == (50, 100) and parts.dtype == np.uint8
    assert set(np.unique(parts[:, :45])) == {FACE} and set(np.unique(parts[:, 55:])) == {CLOTHES}


def test_the_people_model_runs_on_any_picture_and_gives_six_scores_per_place():
    rng = np.random.default_rng(1)
    out = people.scores(rng.integers(0, 255, (300, 200, 3), dtype=np.uint8))
    assert out.shape == (256, 256, len(people.PARTS)) and out.dtype == np.float32 and np.isfinite(out).all()
