"""The check finds a work by any picture at the scale of a ruler beside the plate, when its drawing and largest picture cannot (REQ-055)."""
import json

import cv2
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
    return ig.check_pair(store, pid)


@pytest.fixture(scope="module")
def with_ruler(tmp_path_factory):
    """C00 (a ring seal, the only layer whose output is on) cannot say which way the work lies; C01 and C02 are switched off."""
    store, laser, material = make_store(tmp_path_factory, "ruler")
    yield checked(store, laser, material, synth.pictures_work(with_chart=True), "ruler")
    store.close()


@pytest.fixture(scope="module")
def without_ruler(tmp_path_factory):
    store, laser, material = make_store(tmp_path_factory, "noruler")
    yield checked(store, laser, material, synth.pictures_work(with_chart=True, angle=()), "noruler")
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
