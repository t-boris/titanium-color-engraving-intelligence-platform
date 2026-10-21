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


# -- the time of a whole LightBurn file (REQ-060): every work says whether it takes minutes or hours ---------------------------
def project(layers_xml: str, shapes_xml: str) -> bytes:
    return f'<LightBurnProject AppVersion="1.7.01">{layers_xml}{shapes_xml}</LightBurnProject>'.encode()


def test_a_file_is_timed_layer_by_layer_over_the_area_it_fills_and_the_length_it_traces():
    from titanium_platform import lightburn as lb
    data = project('<CutSetting type="Scan"><index Value="0"/><name Value="C00"/><speed Value="500"/><interval Value="0.05"/></CutSetting>'
                   '<CutSetting type="Cut"><index Value="1"/><name Value="C01"/><speed Value="100"/><numPasses Value="2"/></CutSetting>'
                   '<CutSetting type="Scan"><index Value="2"/><name Value="C02"/><speed Value="500"/><interval Value="0.05"/>'
                   '<doOutput Value="0"/></CutSetting>',
                   '<Shape Type="Rect" CutIndex="0" W="20" H="10"><XForm>1 0 0 1 10 5</XForm></Shape>'
                   '<Shape Type="Rect" CutIndex="1" W="10" H="5"><XForm>1 0 0 1 30 5</XForm></Shape>'
                   '<Shape Type="Rect" CutIndex="2" W="50" H="50"><XForm>1 0 0 1 30 5</XForm></Shape>')
    t = et.of_project(lb.parse_bytes(data))
    fill = 2.0 * 4.0 + 10 / 0.05 * TURN                                   # 2 cm² at 500 mm/s, 0.05 mm: 200 pieces of 20 mm
    line = 3.0 * (10 / 100) * 2                                           # a 30 mm outline at 100 mm/s, two passes
    assert [r["name"] for r in t["layers"]] == ["C00", "C01"]             # the layer with its output off does not engrave
    assert t["seconds"] == pytest.approx(fill + line) and t["complete"]


def test_a_picture_is_timed_over_its_whole_rectangle_and_a_missing_speed_leaves_the_total_incomplete():
    import numpy as np
    from titanium_platform import lightburn as lb, plans
    data = plans.export_picture(np.zeros((200, 300), np.uint8), 30, {"power": 30, "min_power": 1, "speed": 150, "frequency": 60, "line_interval": 0.0169})
    t = et.of_project(lb.parse_bytes(data))
    assert t["seconds"] == pytest.approx(6.0 * 100 / (150 * 0.0169) + 20 / 0.0169 * TURN, rel=1e-6)    # 30 x 20 mm: 6 cm², a piece per row
    unknown = et.of_project(lb.parse_bytes(project('<CutSetting type="Scan"><index Value="0"/><name Value="C00"/></CutSetting>',
                                                   '<Shape Type="Rect" CutIndex="0" W="20" H="10"><XForm>1 0 0 1 10 5</XForm></Shape>')))
    assert not unknown["complete"] and unknown["layers"][0]["seconds"] is None and "speed" in unknown["layers"][0]["note"]


def test_the_pieces_of_scan_line_are_counted_from_the_shapes_so_small_shapes_cost_more_than_their_area():
    """DEC-101: every piece of scan line costs its turnaround; a line crosses a shape once per interval of each edge's extent."""
    from titanium_platform import lightburn as lb
    square = lb.Region("path", 0, 0, 10, 10, polygon=[(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)
    ring = lb.Region("path", 0, 0, 10, 10, polygon=[(0, 0), (10, 0), (10, 10), (0, 10)], closed=True,
                     holes=[[(4, 2), (6, 2), (6, 8), (4, 8)]])               # lines through the hole are cut in two
    assert et.scan_pieces([square], 0.01) == pytest.approx(1000)
    assert et.scan_pieces([ring], 0.01) == pytest.approx(1000 + 600)
    assert et.scan_pieces([square], 0.01, 45) == pytest.approx(1000 * 2 ** 0.5)        # lines at 45 degrees cross the diagonal
    open_line = lb.Region("path", 0, 0, 10, 0, polygon=[(0, 0), (10, 0)], closed=False)
    assert et.scan_pieces([open_line], 0.01) == 0                              # a fill does not fill an open path
    settings = {"speed": 1000.0, "line_interval": 0.01}
    hundred_small = [lb.Region("path", 0, 0, 1, 1, polygon=[(0, 0), (1, 0), (1, 1), (0, 1)], closed=True)] * 100
    big, small = (et.estimate([{"parameters": settings, "area_mm2": 100.0, "scan_pieces": et.scan_pieces(r, 0.01)}])["seconds"]
                  for r in ([square], hundred_small))
    assert big == pytest.approx(10.0 + 1000 * TURN) and small == pytest.approx(10.0 + 10000 * TURN)   # the same area, ten times the pieces
    crossed = et.estimate([{"parameters": {**settings, "cross_hatch": True, "passes": 2}, "area_mm2": 100.0, "scan_pieces": 2000}])
    assert crossed["seconds"] == pytest.approx(2 * (2 * 10.0 + 2000 * TURN))      # the pieces already count both directions


def test_the_turnaround_was_timed_against_the_workshop_s_own_jobs():
    """DEC-101: about 1 ms per piece made the file of a work engraved in 3 h at 150 mm and 1.5-2 h at 100 mm come out right."""
    assert TURN == pytest.approx(0.001)
