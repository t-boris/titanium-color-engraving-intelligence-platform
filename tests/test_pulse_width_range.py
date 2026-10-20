"""Any pulse width within the laser's range is accepted; the cut-off frequency between table steps is interpolated (DEC-089)."""
import math

import pytest

import test_supplied_settings as base
from titanium_platform import devices as dv
from titanium_platform import ingest as ig
from titanium_platform import setup as su

TEMPLATE = "jpt-ydflp-e-60-m7-m-r"
TABLE = dict(dv.JPT_60_M7_STEPS)           # width ns -> cut-off kHz (None = CW)


@pytest.fixture
def passport(store):
    return dv.create_from_template(store, TEMPLATE)["passport"]


def test_a_width_the_table_does_not_list_is_accepted_and_its_cut_off_lies_between_its_neighbours(passport):
    point = dv.operating_point(passport, 50, 80, 900, 300, 0.025)
    assert point["pulse_width_ns"] == 300 and point["cutoff_interpolated"] is True
    assert TABLE[350] < point["cutoff_khz"] < TABLE[250]                      # the cut-off falls as the width grows
    share = math.log(300 / 250) / math.log(350 / 250)
    assert point["cutoff_khz"] == pytest.approx(math.exp(math.log(TABLE[250]) + share * (math.log(TABLE[350]) - math.log(TABLE[250]))))


def test_a_width_of_the_table_keeps_its_own_cut_off(passport):
    point = dv.operating_point(passport, 50, 80, 900, 200, 0.025)
    assert point["cutoff_khz"] == TABLE[200] and point["cutoff_interpolated"] is False


def test_next_to_the_cw_step_the_cut_off_of_the_pulsed_neighbour_is_used(passport):
    assert TABLE[1] is None
    point = dv.cutoff_for(passport, 1.5)
    assert point["cutoff_khz"] == TABLE[2] and point["between"] == [1, 2]


def test_the_note_says_when_the_cut_off_is_an_estimate(passport):
    point = dv.operating_point(passport, 50, 20, 900, 300, 0.025)              # below the cut-off of every pulsed width
    assert point["below_cutoff"] is True
    assert any("interpolated between the 250 and 350 ns steps" in note for note in point["notes"])


@pytest.mark.parametrize("width", [0.5, 600])
def test_a_width_outside_the_range_is_refused_with_the_range(passport, width):
    with pytest.raises(su.ValidationError, match=r"outside the range of this laser \(1-500 ns\)"):
        dv.operating_point(passport, 50, 80, 900, width, 0.025)


def test_a_supplied_300_ns_is_accepted_and_the_layer_reaches_the_model(store):
    w = base.plate_world(store, default_pulse_width=None)
    pid = base.pair_without(w, "QPulseWidth")
    index = base.cell(ig.check_pair(store, pid))["index"]
    ig.supply_setting(store, pid, index, "pulse_width", 300)
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)
    row = base.observation_of(store, pid, "r1c1")
    assert row["model_eligible"] == 1 and '"pulse_width": 300' in row["parameters_json"]
