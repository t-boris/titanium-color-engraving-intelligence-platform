"""A vector work nobody has photographed is not an experiment (REQ-044, DEC-082).

"Delete experiment" deletes the plan of the experiment, and for a vector work the plan is the work itself: its picture, its split and
every variant of its colouring. The operator lost a work that way, so such a work is not listed as an experiment (nor opened as one)
until a photograph of it exists, and the plan page of a vector work has no "delete test" button: the work is deleted in the section of
vector works, whose confirmation says what goes with it."""
import re
from pathlib import Path

import pytest

import synth
from test_experiments import plate, set_status, work_pair, world            # noqa: F401  (fixtures and helpers of the experiments tests)
from titanium_platform import conversion as cv, experiments, plans as pl

UI = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui" / "screens"
PLAN_JS = (UI / "plan.js").read_text(encoding="utf-8")


def vector_plan(w, name="Imma + Boris") -> int:
    """A saved vector work as the section of vector works stores it, with no photograph."""
    return cv.save_plan(w["store"], None, name=name, mode=pl.MODE_VECTOR, status=cv.ST_DRAFT, device_id=w["laser"]["id"], lens_id=None,
                        markers=False, identifier="vector-test", band_count=None, data={"strategy": "fill"})


def test_a_vector_work_without_a_photograph_is_not_listed_and_not_opened_as_an_experiment(world):
    work_id = vector_plan(world)
    assert experiments.list_experiments(world["store"]) == []
    with pytest.raises(KeyError):
        experiments.get_experiment(world["store"], experiments.plan_key(work_id))


def test_the_other_plates_are_still_experiments_beside_a_vector_work(world):
    work_id = vector_plan(world)
    out = plate(world)
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["plan_id"] == out["plan_id"] != work_id


def test_a_vector_work_with_a_photograph_is_an_experiment_again_and_loses_that_when_the_photograph_is_deleted(world):
    work_id = vector_plan(world)
    pair = work_pair(world, work_id, 3)
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["plan_id"] == work_id and experiment["checks"] == 1
    assert experiments.get_experiment(world["store"], experiments.plan_key(work_id))["plate"]["plan_id"] == work_id
    set_status(world["store"], pair, "Deleted")
    assert experiments.list_experiments(world["store"]) == []


def test_the_photograph_of_a_vector_work_keeps_its_check_in_the_experiment_even_when_the_work_has_other_checks(world):
    work_id = vector_plan(world)
    first, second = work_pair(world, work_id, 3), work_pair(world, work_id, 4)
    set_status(world["store"], first, "Accepted")
    (experiment,) = experiments.list_experiments(world["store"])
    assert experiment["checks"] == 2 and experiment["main_pair_id"] == second


def test_the_plan_page_of_a_vector_work_has_no_delete_test_button_and_no_link_to_an_experiment_before_a_photograph():
    assert "vector ? null : btn('Удалить тест'" in PLAN_JS
    assert re.search(r"const toExperiment = !restored \? \(vector && !p\.active_pairs \? null : link\('/experiment/plan-' \+ p\.id, 'К эксперименту'\)\)", PLAN_JS)
    assert PLAN_JS.count("btn('Удалить тест'") == 1                                   # the other plans keep it
