"""The check finds a work by any picture at the scale of a ruler beside the plate, when its drawing and largest picture cannot (REQ-055)."""
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import synth
from titanium_platform import devices, ingest as ig, setup as su
from titanium_platform.db import Store


def make_store(tmp_path_factory, name):
    store = Store(tmp_path_factory.mktemp(name))
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    material = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    su.save_capture_setup(store, "Rig", "camera on a stand", "LED 5600 K", "90", "ColorChecker Classic")
    return store, laser, material


def checked(store, laser, material, work, name):
    pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name=f"{name}.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name=f"{name}.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(), context={"material_id": material["id"]})
    return pid, ig.check_pair(store, pid)


@pytest.fixture(scope="module")
def ruler_pair(tmp_path_factory):
    """C00 (a ring seal, the only layer whose output is on) cannot say which way the work lies; C01 and C02 are switched off."""
    store, laser, material = make_store(tmp_path_factory, "ruler")
    pid, report = checked(store, laser, material, synth.pictures_work(with_chart=True), "ruler")
    yield store, pid, report
    store.close()


@pytest.fixture(scope="module")
def with_ruler(ruler_pair):
    return ruler_pair[2]


@pytest.fixture(scope="module")
def without_ruler(tmp_path_factory):
    store, laser, material = make_store(tmp_path_factory, "noruler")
    yield checked(store, laser, material, synth.pictures_work(with_chart=True, angle=()), "noruler")[1]
    store.close()


def test_the_ruler_and_the_pictures_of_layers_that_are_off_find_the_work(with_ruler):
    a = with_ruler["alignment"]
    assert a["valid"] and a["method"] == "picture at ruler scale", with_ruler["problems"]
    assert a["ruler"]["px_per_mm"] == pytest.approx(10.0, rel=0.01) and a["located"]["searched"] == "beside the measuring angle"
    assert a["located"]["tried"][0]["refused"] is None and a["reflected"]


def test_the_layer_that_is_on_is_measured_where_the_found_work_puts_it_and_those_that_are_off_are_not(with_ruler):
    layers = {rep["index"]: rep for rep in with_ruler["layers"]}
    assert layers[0]["measured_lab"] is not None and not layers[0].get("left_out")
    assert all(layers[i]["left_out"] == "output_off" and layers[i]["measured_lab"] is None for i in (1, 2))


def test_the_operator_is_told_how_the_work_was_found_and_that_the_pictures_of_layers_that_are_off_are_on_the_plate(with_ruler):
    warnings = " ".join(with_ruler["warnings"])
    assert "found by the pictures of layers C00, C01, C02 at the scale of the ruler beside the plate" in warnings
    assert "The pictures of layers C01, C02 are on the plate although their output is switched off" in warnings


def test_the_stored_check_can_be_saved(with_ruler):
    json.dumps(with_ruler)


def test_without_a_ruler_the_same_photograph_cannot_be_aligned_and_says_so(without_ruler):
    a = without_ruler["alignment"]
    assert not a["valid"] and "no reliable combination of LightBurn details" in a["error"]
    assert a["ruler"]["refused"].startswith("no ruler") and "located" not in a


OLD_NOTE = "output is switched off in LightBurn: this layer was not engraved and is not measured"
OLD_WARNING = "layers C01, C02, C03 have their output switched off in LightBurn: they were not engraved and are not measured"


def test_the_notes_and_warnings_of_layers_that_are_off_say_what_the_found_work_shows_not_that_they_were_not_engraved():
    layers = [SimpleNamespace(index=1, name="C01 portrait"), SimpleNamespace(index=2, name="C02 text"), SimpleNamespace(index=3, name="C03 seal")]
    report = {"layers": [{"index": i, "left_out": "output_off", "notes": [OLD_NOTE]} for i in (1, 2, 3)] + [{"index": 4, "notes": []}],
              "warnings": [OLD_WARNING, "another warning"]}
    ig._say_work_was_found_by_pictures(report, layers, ["C01 portrait", "C03 seal"])
    notes = {rep["index"]: rep["notes"] for rep in report["layers"]}
    assert notes[1] == notes[3] and "its picture is on the plate (engraved earlier)" in notes[1][0] and "not engraved" not in notes[1][0]
    assert notes[2] == ["output is switched off in LightBurn: it is not measured and its outline is drawn where the work found by pictures puts it"] and notes[4] == []
    assert report["warnings"] == ["another warning",
        "The pictures of layers C01, C03 are on the plate although their output is switched off in LightBurn (engraved earlier): they helped to find the work and are still not measured.",
        "Layers C02 have their output switched off in LightBurn and are not measured; their outlines are drawn where the work found by pictures puts them."]


def test_a_check_without_layers_that_are_off_is_left_as_it_was():
    report = {"layers": [{"index": 1, "notes": ["x"]}], "warnings": ["w"]}
    ig._say_work_was_found_by_pictures(report, [SimpleNamespace(index=1, name="C01")], ["C01"])
    assert report == {"layers": [{"index": 1, "notes": ["x"]}], "warnings": ["w"]}


def test_the_stored_check_of_a_work_found_by_pictures_carries_no_contradiction(with_ruler):
    assert not any("were not engraved" in w for w in with_ruler["warnings"])
    off = [rep for rep in with_ruler["layers"] if rep.get("left_out") == "output_off"]
    assert off and all("not engraved" not in note and "picture is on the plate" in note for rep in off for note in rep["notes"])


def drawn(store, pid, check, layer_index=None):
    """The overlay as the server draws it from ``check``, and how many pixels carry the colour of a layer that is on the plate but not measured."""
    row = ig._pair_row(store, pid)
    png = ig._draw_overlay(row["photo_path"], row["lightburn_path"], check, None, True, False, None, layer_index, "normal", False, 10000)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    return int(np.all(img == ig.NOT_MEASURED_COLOR, axis=2).sum())


def test_the_overlay_draws_the_layers_that_are_off_when_the_work_was_found_by_their_pictures(ruler_pair):
    store, pid, report = ruler_pair
    check = json.loads(ig._pair_row(store, pid)["data_json"])["check"]
    assert check["alignment"]["located"]
    with_them = drawn(store, pid, check)
    assert with_them > 1000                                                     # the frames of C01 and C02, a few pixels thick
    assert drawn(store, pid, check, layer_index=0) == 0                         # the layer that is on has the colour of its own
    assert drawn(store, pid, check, layer_index=1) > 0 and drawn(store, pid, check, layer_index=2) > 0


def test_the_overlay_leaves_them_out_when_the_pictures_of_layers_that_are_off_did_not_find_the_work(ruler_pair):
    store, pid, _ = ruler_pair
    check = json.loads(ig._pair_row(store, pid)["data_json"])["check"]
    without = {**check, "alignment": {k: v for k, v in check["alignment"].items() if k != "located"}}
    assert drawn(store, pid, without) == 0                                     # REQ-050 as before: a layer that is left out is not drawn
    behind = {**check, "layers": [{**rep, "left_out": "left_behind"} if rep.get("left_out") else rep for rep in check["layers"]]}
    assert drawn(store, pid, behind) == 0                                       # a layer left behind is never drawn where the work is not
