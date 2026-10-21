"""A work that mixes a vector fill with a photo engraving whose picture has a hole where the fill is (REQ-053, DEC-095)."""
import json

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color, devices, ingest as ig, lightburn as lb, setup as su
from titanium_platform.db import Store
from titanium_platform import composition

HOLE = (80, 40, 170, 110)       # picture pixels (256 across): in the upper part, so a picture read upside down puts the fill under the picture


@pytest.fixture(scope="module")
def work():
    return synth.picture_work(fill_hole=HOLE, with_chart=True)


@pytest.fixture(scope="module")
def report(tmp_path_factory, work):
    """One pair, checked once: every test below reads its report."""
    store = Store(tmp_path_factory.mktemp("mixed"))
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")
    pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name="mixed.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name="mixed.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                         context={"material_id": material["id"]})
    out = ig.check_pair(store, pid)
    yield out
    store.close()


def layers_of(report):
    return {rep["index"]: rep for rep in report["layers"]}


def test_the_check_aligns_by_the_picture_even_though_part_of_it_is_cut_out(report):
    assert report["alignment"]["valid"] and report["alignment"]["method"] == "picture", report["problems"]


def test_the_fill_under_the_hole_of_the_picture_is_measured_in_its_own_colour_not_called_engraved_again(report, work):
    fill = layers_of(report)[1]
    assert fill["measured_lab"] is not None and (fill.get("covered_by_later_layers_percent") or 0) < 10, fill["notes"]
    assert color.delta_e(fill["measured_lab"], work["fill_lab"]) < 12
    assert not fill.get("covered_by")


def test_the_picture_is_sampled_where_it_strikes_and_not_in_the_hole(report, work):
    picture = layers_of(report)[0]
    assert picture["tonal"] is not None and picture["measured_lab"][2] > -3          # the fill's b* is -12: it is not in the picture's sample
    assert picture["spread"]["L"] >= 0


def test_every_measured_layer_comes_with_the_spread_of_its_colour(report):
    for rep in report["layers"]:
        if rep["measured_lab"]:
            assert set(rep["spread"]) == {"L", "chroma", "L_range"} and rep["spread"]["L"] >= 0 and len(rep["spread"]["L_range"]) == 2


def test_the_report_says_the_work_is_a_mix_with_the_picture_cut_out_where_the_fill_is(report):
    c = report["composition"]
    assert c["mixed"] and not c["picture_over_fills"] and c["share"]["both"] < 5
    kinds = {e["index"]: e["kind"] for e in c["layers"]}
    assert kinds == {0: "photo", 1: "fill"}
    picture = next(e for e in c["layers"] if e["index"] == 0)
    assert picture["mode"] == "grayscale" and picture["family"] == "power" and 60 < picture["opaque_percent"] < 100
    json.dumps(report)                                                       # the report stays storable


def test_the_same_fill_under_the_opaque_part_of_the_picture_is_engraved_again():
    """The fill under an opaque part of the picture is covered (the hole is not where the fill is): composition over the file alone."""
    hole = synth.picture_work(fill_hole=(80, 40, 170, 110))["lightburn"]
    layers = lb.parse_bytes(hole).layers
    assert composition.compose(layers, {0: False})["picture_over_fills"] is False
    assert composition.compose(layers, {0: True})["picture_over_fills"] is True       # the picture upside down covers the fill


def test_a_cleaning_rectangle_is_not_a_colour_of_the_work():
    xml = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="2000"/>'
           b'<frequency Value="48000"/></CutSetting><Shape Type="Rect" CutIndex="0" W="100" H="100"><XForm>1 0 0 1 50 50</XForm></Shape>'
           b'<CutSetting type="Scan"><index Value="1"/><name Value="C01"/><priority Value="1"/><maxPower Value="20"/><speed Value="900"/>'
           b'<frequency Value="48000"/></CutSetting><Shape Type="Rect" CutIndex="1" W="20" H="20"><XForm>1 0 0 1 50 50</XForm></Shape></LightBurnProject>')
    c = composition.compose(lb.parse_bytes(xml).layers)
    assert c["cleaning_layer"] == 0 and {e["index"]: e["kind"] for e in c["layers"]} == {0: "cleaning", 1: "fill"}
    assert c["share"] == {"fill_only": 100.0, "photo_only": 0.0, "both": 0.0} and not c["mixed"]


def test_a_layer_with_its_output_switched_off_marks_nothing_in_the_composition():
    xml = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><doOutput Value="0"/><maxPower Value="20"/>'
           b'<speed Value="900"/><frequency Value="48000"/></CutSetting><Shape Type="Rect" CutIndex="0" W="20" H="20"><XForm>1 0 0 1 50 50</XForm></Shape>'
           b'<CutSetting type="Cut"><index Value="1"/><name Value="C01"/><maxPower Value="20"/><speed Value="30"/></CutSetting>'
           b'<Shape Type="Rect" CutIndex="1" W="20" H="20"><XForm>1 0 0 1 50 50</XForm></Shape></LightBurnProject>')
    c = composition.compose(lb.parse_bytes(xml).layers)
    assert c["layers"][0]["engraves"] is False and c["layers"][0]["visible_percent"] == 0.0 and c["marked_mm2"] == 0.0
    assert [item["kind"] for item in c["lines"]] == ["line"]
