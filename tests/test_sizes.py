"""The size of an engraving (DEC-107): the row length of what a LightBurn file engraves, and the curve of a mode made for one size from
the measurements at that size, between two measured sizes or from the nearest one, saying which."""
import numpy as np
import pytest

from titanium_platform import grayscale, lightburn as lb, palette, plans, prediction, row_length


def rect(x, y, w, h):
    return lb.Region("rect", x, y, w, h, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)


def square_with_hole():
    outer = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
    return lb.Region("path", 0, 0, 20, 20, outer, True, [[(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]])


def layer(kind, regions, **settings):
    return lb.Layer(0, "C00", kind, 20.0, 60000.0, 150.0, None, 0.02, regions=regions, **settings)


def test_a_rectangle_is_as_long_as_it_is_wide_along_the_scan_and_shapes_on_one_row_add_up_unless_filled_one_by_one():
    assert row_length.of_regions([rect(0, 0, 10, 4)]) == pytest.approx(10.0, abs=0.01)
    assert row_length.of_regions([rect(0, 0, 10, 4)], angle_deg=90) == pytest.approx(4.0, abs=0.01)      # rows along y
    two = [rect(0, 0, 5, 5), rect(25, 0, 5, 5)]
    assert row_length.of_regions(two) == pytest.approx(10.0, abs=0.01)                  # one fill: the jump between them is not a row
    assert row_length.of_regions(two, together=False) == pytest.approx(5.0, abs=0.01)
    # a hole: rows through it mark 10 of 20 mm, the others 20: (10 x 10^2 + 10 x 20^2) / (10 x 10 + 10 x 20)
    assert row_length.of_regions([square_with_hole()]) == pytest.approx(5000 / 300, rel=0.01)
    assert row_length.of_regions([lb.Region("path", 0, 0, 10, 0, [(0, 0), (10, 0)], False)]) is None    # an open path fills nothing


def test_a_layer_is_measured_as_lightburn_scans_it():
    picture = lb.Region("bitmap", 3, 3, 150, 150, [(3, 3), (153, 3), (153, 153), (3, 153)], True, bitmap={"png": b"x"})
    small = lb.Region("bitmap", 0, 0, 10, 10, [(0, 0), (10, 0), (10, 10), (0, 10)], True, bitmap={"png": b"y"})
    assert row_length.of_layer(layer("Image", [small, picture])) == pytest.approx(150.0, abs=0.01)       # the largest picture
    two = [rect(0, 0, 5, 5), rect(25, 0, 5, 5)]
    assert row_length.of_layer(layer("Scan", two)) == pytest.approx(10.0, abs=0.01)
    one_by_one = layer("Scan", two, source_settings={"scanOpt": {"Value": "individual"}})
    flood = layer("Scan", two, source_settings={"floodFill": {"Value": "1"}})
    assert row_length.of_layer(one_by_one) == row_length.of_layer(flood) == pytest.approx(5.0, abs=0.01)
    assert row_length.of_layer(layer("Cut", two)) is None and row_length.of_layer(layer("Offset", two)) is None


def test_a_stored_file_is_read_once_per_version_and_a_missing_file_has_no_sizes(tmp_path):
    picture = (np.tile(np.linspace(0, 255, 64), (32, 1))).astype(np.uint8)
    path = tmp_path / "work.lbrn2"
    path.write_bytes(plans.export_picture(picture, 40.0, {"power": 30, "min_power": 1, "speed": 150, "frequency": 60, "pulse_width": 350,
                                                           "line_interval": 0.02, "passes": 1, "global_passes": 1}, "work", clean=None))
    found = row_length.of_file(str(path))
    assert list(found.values()) == [pytest.approx(40.0, abs=0.01)]
    assert row_length.of_file(str(path)) is found                                                        # kept
    assert row_length.of_file(str(tmp_path / "gone.lbrn2")) == {} and row_length.of_file(None) == {}


def points(row_mm, labs, powers=(5.0, 10.0, 20.0), pair=1):
    return [prediction.Point(p, lab, {"kind": "pair", "id": pair, "pair_id": pair, "row_mm": row_mm}, True) for p, lab in zip(powers, labs)]


SHORT = points(40.0, [(40.0, 10.0, -30.0), (50.0, 0.0, -10.0), (35.0, 0.0, 0.0)], pair=1)      # violet and blue in short rows
LONG = points(160.0, [(80.0, 2.0, 30.0), (60.0, 0.0, 10.0), (36.0, 0.0, 0.0)], pair=2)         # straw and gold in long ones


def test_a_curve_is_made_for_one_size_from_its_measurements_between_two_sizes_or_from_the_nearest_saying_which():
    at = prediction.curve_at(SHORT + LONG, 44.0)                                        # within 10 % of 40: measured there
    assert at.size == {"row_mm": 44.0, "measured_mm": [40.0, 160.0], "unknown_points": 0, "how": "measured", "from_mm": [40.0],
                       "engravings": 1}
    assert at.lab_at(5.0) == pytest.approx([40.0, 10.0, -30.0])
    mid = prediction.curve_at(SHORT + LONG, 80.0)                                       # halfway in the logarithm of the length
    assert (mid.size["how"], mid.size["from_mm"]) == ("between", [40.0, 160.0])
    assert mid.lab_at(5.0) == pytest.approx([60.0, 6.0, 0.0]) and mid.lab_at(20.0) == pytest.approx([35.5, 0.0, 0.0])
    assert {s["pair_id"] for s in mid.points[0]["sources"]} == {1, 2} and mid.points[0]["spread_de"] is None
    far = prediction.curve_at(SHORT + LONG, 400.0)                                      # never extrapolated
    assert (far.size["how"], far.size["from_mm"]) == ("outside", [160.0]) and far.lab_at(5.0) == pytest.approx([80.0, 2.0, 30.0])
    shown = prediction.curve_at(SHORT + LONG + points(170.0, [(81.0, 2.0, 30.0)] * 3, pair=3))   # no size asked: the one most engravings measured
    assert shown.size["row_mm"] == pytest.approx(164.9, abs=0.1) and shown.size["how"] == "measured"


def test_a_picture_between_two_sizes_is_not_said_to_rest_on_one_engraving():
    picture = np.tile(np.linspace(0.0, 1.0, 32), (8, 1))
    single = "only one engraving measured"
    assert any(single in n for n in prediction.render(picture, 5.0, 20.0, prediction.curve_at(SHORT + LONG, 40.0))["notes"])
    assert not any(single in n for n in prediction.render(picture, 5.0, 20.0, prediction.curve_at(SHORT + LONG, 80.0))["notes"])


def test_points_of_unknown_size_are_used_only_when_no_size_is_known_and_spans_that_do_not_meet_give_the_nearest():
    unknown = points(None, [(40.0, 10.0, -30.0), (50.0, 0.0, -10.0), (35.0, 0.0, 0.0)], pair=7)
    alone = prediction.curve_at(unknown, 100.0)
    assert alone.size["how"] == "unknown" and len(alone.points) == 3
    mixed = prediction.curve_at(unknown + LONG, 160.0)
    assert mixed.size["unknown_points"] == 3 and mixed.lab_at(5.0) == pytest.approx([80.0, 2.0, 30.0])
    apart = points(160.0, [(80.0, 2.0, 30.0), (60.0, 0.0, 10.0)], powers=(40.0, 50.0), pair=2)
    gap = prediction.curve_at(SHORT + apart, 70.0)
    assert (gap.size["how"], gap.size["from_mm"]) == ("outside", [40.0])
    with pytest.raises(prediction.PredictionError):
        prediction.curve_at([], 50.0)


def test_an_engraving_is_compared_only_with_others_at_its_size_or_around_it():
    other_size = grayscale.compare(LONG, SHORT)
    assert other_size["compared"] == 0 and other_size["size"]["how"] == "outside"
    same = grayscale.compare(points(42.0, [(41.0, 10.0, -30.0), (50.0, 0.0, -9.0), (35.0, 1.0, 0.0)], pair=5), SHORT)
    assert same["compared"] == 3 and same["median_de"] == pytest.approx(1.0, abs=0.01)
    between = grayscale.compare(points(80.0, [(60.0, 6.0, 0.0)], powers=(5.0,), pair=6), SHORT + LONG)
    assert between["compared"] == 1 and between["median_de"] == pytest.approx(0.0, abs=0.01) and between["size"]["how"] == "between"


def entry(name, lab, sizes=()):
    return {"id": name, "lab": list(lab), "srgb": None, "time_s_per_cm2": 1.0, "caution": None, "basis": "chart", "confidence": None,
            "sizes": [{"row_mm": mm, "engravings": 1, "lab": list(at)} for mm, at in sizes]}


GOLD, VIOLET = (75.0, 5.0, 40.0), (40.0, 25.0, -35.0)
SHIFTING = entry("x", (57.5, 15.0, 2.5), [(5.0, VIOLET), (50.0, GOLD)])      # violet in short rows, gold in long ones; its own colour pools both


def test_a_palette_colour_is_given_at_a_row_length_as_measured_between_two_sizes_or_from_the_nearest():
    assert palette.at_size(SHIFTING, 52.0)["lab"] == list(GOLD) and palette.at_size(SHIFTING, 52.0)["size"]["how"] == "measured"
    mid = palette.at_size(SHIFTING, (5.0 * 50.0) ** 0.5)                       # halfway in the logarithm of the length
    assert mid["size"]["how"] == "between" and mid["lab"] == pytest.approx([57.5, 15.0, 2.5])
    assert palette.at_size(SHIFTING, 2.0)["lab"] == list(VIOLET) and palette.at_size(SHIFTING, 2.0)["size"]["how"] == "outside"
    assert palette.at_size(SHIFTING, None)["size"]["how"] == "unknown" and palette.at_size(entry("y", GOLD), 30.0)["lab"] == list(GOLD)


def test_a_source_colour_takes_the_entry_whose_colour_at_the_length_of_its_rows_is_nearest():
    steady = entry("y", (70.0, 6.0, 33.0))                                    # a gold of unknown size, a little off
    source = [{"index": 0, "lab": list(GOLD), "pixels": 100}]

    def pick(size_of):
        return palette.assign(source, [SHIFTING, steady], "closest", tolerance_de=3, size_of=size_of)["colours"][0]
    assert pick(None)["entry_id"] == "y"                                        # pooled, the shifting recipe is far from gold
    long = pick(lambda index, e: 50.0)
    assert (long["entry_id"], long["delta_e"], long["size"]["how"]) == ("x", 0.0, "measured")
    assert pick(lambda index, e: 5.0)["entry_id"] == "y"                        # in short rows it gives violet
