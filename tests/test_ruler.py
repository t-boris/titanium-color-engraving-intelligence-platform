"""The scale and the corner of a measuring angle read from a photograph (REQ-055, DEC-097)."""
import numpy as np
import pytest

import synth
from titanium_platform import ruler


@pytest.fixture(scope="module")
def work():
    return synth.pictures_work()


@pytest.fixture(scope="module")
def found(work):
    return ruler.find_scale(work["photo"])


def test_the_scale_is_read_from_the_millimetre_ticks_of_both_rulers(found):
    assert found["px_per_mm"] == pytest.approx(10.0, rel=0.01) and found["axes"] == ["horizontal", "vertical"]


def test_the_inner_corner_and_the_side_the_plate_lies_on_are_found(found, work):
    assert np.abs(np.array(found["corner_px"]) - work["corner_px"]).max() <= 6 and found["quadrant"] == [1, -1]


def test_a_ruler_with_half_millimetre_ticks_reads_as_twice_and_one_with_only_long_ticks_as_half(found):
    assert found["alternatives"] == pytest.approx([2 * found["px_per_mm"], found["px_per_mm"] / 2])


def test_one_ruler_gives_a_scale_but_no_corner():
    found = ruler.find_scale(synth.pictures_work(angle=("vertical",))["photo"])
    assert found["px_per_mm"] == pytest.approx(10.0, rel=0.01) and found["axes"] == ["vertical"] and "corner_px" not in found


def test_a_photograph_without_a_ruler_has_none_and_says_why(work):
    diagnostics = {}
    assert ruler.find_scale(synth.pictures_work(angle=())["photo"], diagnostics) is None
    assert diagnostics["refused"].startswith("no ruler")


def test_an_even_hatch_has_the_period_of_a_ruler_but_not_its_long_ticks_and_is_not_one():
    photo = np.full((1900, 2100, 3), 150, np.uint8)
    for y in range(0, 1900, 10):                                    # a line fill: every line like the others
        photo[y:y + 3] = 40
    assert ruler.find_scale(photo) is None


def test_a_rough_surface_is_not_a_ruler():
    rng = np.random.default_rng(3)
    photo = np.clip(rng.normal(130, 30, (1900, 2100, 3)), 0, 255).astype(np.uint8)
    assert ruler.find_scale(photo) is None
