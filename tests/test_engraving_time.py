"""Engraving time of a recipe from its settings (REQ-035, DEC-075): an estimate, labelled so."""
import pytest

from titanium_platform import engraving_time as et

TURN = et.TURNAROUND_S


def test_a_filled_recipe_takes_100_over_speed_times_interval_seconds_per_square_centimetre_plus_a_turnaround_per_line():
    t = et.per_area({"speed": 1000.0, "line_interval": 0.01, "passes": 1, "layer_type": "Scan"})
    # 100 / (1000 * 0.01) = 10 s of scanning; 10 mm / 0.01 mm = 1000 lines, each with its turnaround
    assert t["s_per_cm2"] == pytest.approx(10.0 + 1000 * TURN) and t["kind"] == "area" and t["estimate"] is True
    assert t["s_per_cm"] is None and t["note"] is None
    assert et.per_area({"speed": 500.0, "line_interval": 0.05})["s_per_cm2"] == pytest.approx(4.0 + 200 * TURN)


def test_cross_hatch_doubles_and_passes_and_global_repeats_multiply():
    one = et.per_area({"speed": 1000.0, "line_interval": 0.01, "passes": 1})["s_per_cm2"]
    assert et.per_area({"speed": 1000.0, "line_interval": 0.01, "passes": 1, "cross_hatch": True})["s_per_cm2"] == pytest.approx(2 * one)
    assert et.per_area({"speed": 1000.0, "line_interval": 0.01, "passes": 3})["s_per_cm2"] == pytest.approx(3 * one)
    assert et.per_area({"speed": 1000.0, "line_interval": 0.01, "passes": 2, "global_passes": 2, "cross_hatch": True})["s_per_cm2"] \
        == pytest.approx(8 * one)


def test_pulse_width_and_frequency_do_not_change_the_time():
    base = {"speed": 900.0, "line_interval": 0.02, "passes": 1, "layer_type": "Scan"}
    times = {et.per_area({**base, "pulse_width": q, "frequency": f, "power": p})["s_per_cm2"]
             for q, f, p in ((4.0, 300.0, 20.0), (200.0, 40.0, 90.0), (None, None, 50.0))}
    assert len(times) == 1


def test_scanning_one_way_adds_the_return_jump_of_every_line_at_the_recipes_jump_speed():
    both = et.per_area({"speed": 1000.0, "line_interval": 0.01, "bidirectional": True})["s_per_cm2"]
    one_way = et.per_area({"speed": 1000.0, "line_interval": 0.01, "bidirectional": False})["s_per_cm2"]
    assert one_way - both == pytest.approx(1000 * 10.0 / et.JUMP_SPEED_MM_S)          # 1000 lines of 10 mm back at the jump speed
    own = et.per_area({"speed": 1000.0, "line_interval": 0.01, "bidirectional": False,
                       "source_settings": {"JumpSpeed": {"Value": "2000"}, "OverrideGalvoTimings": {"Value": "1"}}})["s_per_cm2"]
    assert own - both == pytest.approx(1000 * 10.0 / 2000.0)


def test_settings_the_file_did_not_record_take_lightburns_defaults():
    plain = et.per_area({"speed": 1000.0, "line_interval": 0.01})["s_per_cm2"]
    assert plain == et.per_area({"speed": 1000.0, "line_interval": 0.01, "passes": 1, "global_passes": 1, "bidirectional": True,
                                 "cross_hatch": False})["s_per_cm2"]


def test_a_line_mode_recipe_has_a_time_per_centimetre_of_path():
    t = et.of_recipe({"layer_type": "Cut", "speed": 500.0, "passes": 2, "global_passes": 3, "line_interval": 0.005})
    assert t["kind"] == "length" and t["s_per_cm"] == pytest.approx(10 / 500 * 2 * 3) and t["s_per_cm2"] is None
    assert et.of_recipe({"layer_type": "Scan", "speed": 500.0, "line_interval": 0.05})["kind"] == "area"
    assert et.of_recipe({"layer_type": "Image", "speed": 500.0, "line_interval": 0.05})["kind"] == "area"   # a raster scans its area


def test_without_a_speed_or_a_line_interval_there_is_no_time_and_the_reason_is_given():
    no_speed = et.per_area({"line_interval": 0.01})
    assert no_speed["s_per_cm2"] is None and no_speed["note"] == "the speed of this recipe is not recorded: its engraving time is not known"
    no_interval = et.per_area({"speed": 1000.0, "line_interval": None})
    assert no_interval["s_per_cm2"] is None and "line interval" in no_interval["note"]
    assert et.per_length({"layer_type": "Cut"})["s_per_cm"] is None


def test_a_stored_observation_is_read_with_its_own_setting_names():
    """The parameters exactly as an accepted observation stores them (live database, 2026-10-18)."""
    stored = {"power": 57.8, "frequency": 300.0, "speed": 1778.0, "pulse_width": 9.0, "line_interval": 0.002, "passes": 1, "profile_id": 1,
              "layer_type": "Scan", "global_passes": 1, "bidirectional": False, "cross_hatch": False, "scan_angle": 0.0, "angle_increment": 0.0,
              "source_settings": {"maxPower": {"Value": "57.8"}, "speed": {"Value": "1778"}, "frequency": {"Value": "300000"},
                                  "QPulseWidth": {"Value": "9"}, "scanOpt": {"Value": "individual"}, "bidir": {"Value": "0"},
                                  "interval": {"Value": "0.002"}}}
    lines = 10 / 0.002
    assert et.of_recipe(stored)["s_per_cm2"] == pytest.approx(lines * (10 / 1778.0 + TURN + 10 / et.JUMP_SPEED_MM_S))


def test_sub_layers_are_named_as_not_counted():
    t = et.per_area({"speed": 1000.0, "line_interval": 0.03, "source_settings": {"SubLayer": {"type": "Scan", "speed": {"Value": "2000"}}}})
    assert t["s_per_cm2"] is not None and t["note"] == "the sub-layers of this recipe are not counted in its time"


def test_the_time_of_a_whole_job_sums_its_layers_and_says_when_one_is_unknown():
    fill = {"speed": 1000.0, "line_interval": 0.01}
    job = et.estimate([{"index": 1, "parameters": fill, "area_mm2": 250.0},
                       {"index": 2, "parameters": {"layer_type": "Cut", "speed": 100.0}, "length_mm": 50.0}])
    assert job["seconds"] == pytest.approx(2.5 * (10 + 1000 * TURN) + 5 * 0.1) and job["complete"] and job["estimate"]
    partial = et.estimate([{"index": 1, "parameters": fill, "area_mm2": 100.0}, {"index": 2, "parameters": {"line_interval": 0.01}, "area_mm2": 100.0},
                           {"index": 3, "parameters": fill}])
    assert not partial["complete"] and partial["seconds"] == pytest.approx(10 + 1000 * TURN)
    assert [row["note"] for row in partial["layers"]] == [None, "the speed of this recipe is not recorded: its engraving time is not known",
                                                          "how much this layer engraves is not given"]
