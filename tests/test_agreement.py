"""The colour of a setting is the colour its engravings agree on, and its confidence rises with agreeing repeats and falls with differing
ones (REQ-045, DEC-083). Pure function tests: the operator's own cases, in the operator's words."""
import itertools

import pytest

from titanium_platform import agreement, color

YELLOW = [80.0, 0.0, 45.0]
BROWN = [30.0, 12.0, 14.0]          # dark brown, far from the yellow (ΔE about 60)
GREEN = [55.0, -40.0, 20.0]


def eng(lab, day):
    return {"lab": lab, "when": (f"2026-10-{day:02d}", day)}


def trust(*labs_days):
    return agreement.consensus([eng(lab, day) for lab, day in labs_days])


# -- the same colour repeating under the same settings is more confident --------------------------------------------------------
def test_each_further_engraving_that_agrees_raises_the_confidence():
    values = [trust(*[(BROWN, d) for d in range(1, n + 1)])["trust"] for n in range(1, 8)]
    assert values == sorted(values) and len(set(values)) == 7                       # strictly rising
    assert values[0] == pytest.approx(1 / 3) and values[1] == pytest.approx(0.5) and values[2] == pytest.approx(0.6)
    assert values[3] == pytest.approx(4 / 6)                                         # n / (n + 2), as the model always gave it


def test_one_engraving_has_no_assessed_confidence_but_a_rank_between_a_contradicted_colour_and_a_repeated_one():
    one = trust((BROWN, 1))
    assert one["confidence"] is None and one["contradicted"] is False and one["agreeing"] == 1 and one["differing"] == 0
    assert one["lab"] == BROWN and one["trust"] == pytest.approx(agreement.SINGLE)
    assert trust((YELLOW, 1), (BROWN, 2))["trust"] < agreement.SINGLE < trust((BROWN, 1), (BROWN, 2))["trust"]


def test_engravings_within_the_limit_agree_and_the_colour_is_their_mean():
    a, b = [60.0, 5.0, 20.0], [62.0, 5.0, 20.0]
    found = trust((a, 1), (b, 2))
    assert found["lab"] == pytest.approx([61.0, 5.0, 20.0]) and found["agreeing"] == 2 and found["differing"] == 0
    assert found["confidence"] == pytest.approx(0.5) and found["contradicted"] is False


def test_the_limit_is_inclusive_and_a_hair_beyond_it_is_a_difference():
    near = [50.0 + agreement.AGREEMENT_DE, 0.0, 0.0]
    assert trust(([50.0, 0.0, 0.0], 1), (near, 2))["agreeing"] == 2
    assert trust(([50.0, 0.0, 0.0], 1), ([near[0] + 0.01, 0.0, 0.0], 2))["agreeing"] == 1


# -- a colour that changes under the same settings is not confident ---------------------------------------------------------------------
def test_every_engraving_that_differs_lowers_the_confidence():
    base = trust((BROWN, 1), (BROWN, 2), (BROWN, 3))["trust"]
    one_off = trust((BROWN, 1), (BROWN, 2), (BROWN, 3), (YELLOW, 4))["trust"]
    two_off = trust((BROWN, 1), (BROWN, 2), (BROWN, 3), (YELLOW, 4), (GREEN, 5))["trust"]
    assert base > one_off > two_off
    assert trust((BROWN, 1), (BROWN, 2), (BROWN, 3), (YELLOW, 4))["lab"] == pytest.approx(BROWN)    # the outlier does not move the colour


def test_a_recipe_whose_colour_changes_is_contradicted_unless_a_strict_majority_agrees():
    assert trust((YELLOW, 1), (BROWN, 2))["contradicted"] is True                  # one against one
    assert trust((YELLOW, 1), (BROWN, 2), (GREEN, 3))["contradicted"] is True      # three different colours
    assert trust((YELLOW, 1), (YELLOW, 2), (BROWN, 3), (BROWN, 4))["contradicted"] is True   # two against two
    assert trust((YELLOW, 1), (BROWN, 2), (BROWN, 3))["contradicted"] is False     # two against one
    assert trust((BROWN, 1), (BROWN, 2))["contradicted"] is False
    assert trust((BROWN, 1))["contradicted"] is False                              # engraved once: not repeated, not contradicted


# -- yellow first, dark brown when redone: the new colour replaces the old --------------------------------------------------------------
def test_a_colour_that_was_yellow_and_is_redone_as_dark_brown_becomes_dark_brown():
    assert trust((YELLOW, 1))["lab"] == YELLOW
    redone = trust((YELLOW, 1), (BROWN, 2))
    assert redone["lab"] == BROWN and redone["agreeing"] == 1 and redone["differing"] == 1      # the newer one wins the tie
    assert redone["trust"] < agreement.SINGLE                                                   # but nobody can be sure yet
    settled = trust((YELLOW, 1), (BROWN, 2), (BROWN, 3))
    assert settled["lab"] == pytest.approx(BROWN) and settled["contradicted"] is False
    assert settled["trust"] > redone["trust"]                                                   # the repeat settles it
    four = trust((YELLOW, 1), (YELLOW, 2), (BROWN, 3), (BROWN, 4))
    assert four["lab"] == pytest.approx(BROWN)                                                  # an equal count: the newer pair replaces the older


def test_more_repeats_of_the_older_colour_keep_it_against_one_newer_difference():
    assert trust((YELLOW, 1), (YELLOW, 2), (YELLOW, 3), (BROWN, 4))["lab"] == pytest.approx(YELLOW)


def test_the_result_does_not_depend_on_the_order_the_engravings_are_listed_in():
    items = [(YELLOW, 1), (BROWN, 2), (BROWN, 3), (GREEN, 4)]
    first = trust(*items)
    for order in itertools.permutations(items):
        again = trust(*order)
        assert again["lab"] == pytest.approx(first["lab"]) and again["trust"] == pytest.approx(first["trust"])


def test_engravings_without_a_time_count_as_the_oldest():
    found = agreement.consensus([{"lab": YELLOW}, {"lab": BROWN, "when": ("2026-10-01", 1)}])
    assert found["lab"] == BROWN
    assert agreement.consensus([{"lab": BROWN}])["lab"] == BROWN


def test_the_agreed_colour_is_never_farther_from_its_members_than_the_limit_and_the_helpers_report_it():
    labs = [[50.0, 0.0, 0.0], [52.0, 1.0, 0.0], [54.0, 0.0, 1.0], [90.0, 0.0, 0.0]]
    found = agreement.consensus([eng(lab, i + 1) for i, lab in enumerate(labs)])
    assert found["members"] == [0, 1, 2] and found["agreeing"] == 3
    assert all(color.delta_e(labs[i], found["lab"]) <= agreement.AGREEMENT_DE for i in found["members"])
    assert agreement.shown(found) == {"engravings": 4, "agreeing": 3, "differing": 1, "contradicted": False, "limit": agreement.AGREEMENT_DE}
    assert agreement.trust({"confidence": None}) == agreement.SINGLE and agreement.trust({"confidence": 0.5}) == 0.5
    with pytest.raises(ValueError):
        agreement.consensus([])
