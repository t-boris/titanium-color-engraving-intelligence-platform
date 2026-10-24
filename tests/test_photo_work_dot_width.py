"""The dot width correction of a photo work's dot kind (K2 of 0.21.0): LightBurn shrinks each dot of a dithered picture by the width the
laser's dot really has (``dotWidth`` in mm with ``useDotCorrection``, as the operator's own files carry them). The work keeps it with its
dot settings and its undo, its file and its «Проба этого вида» are engraved with it, and the tones measured at one dot width are not
taken for another."""
import json

import cv2
import numpy as np
import pytest

import synth
from test_grey_scales import app_world, picture_png  # noqa: F401  (the measured grey-ramp plate, four scales)
from test_photo_work_kinds import create, rgb, settings
from titanium_platform import ingest as ig, lightburn, plans, photo_state

PARAMETERS = {"power": 30, "min_power": 30, "speed": 1000, "frequency": 60, "pulse_width": 200, "line_interval": 0.0254, "passes": 1}


def image_layer(data: bytes) -> lightburn.Layer:
    (layer,) = [layer for layer in lightburn.parse_bytes(data).layers if layer.layer_type == "Image"]
    return layer


def test_the_image_layer_carries_the_dot_width_as_lightburn_writes_it_and_reads_back():
    picture = np.tile(np.linspace(255, 0, 40), (20, 1)).astype(np.uint8)
    data = plans.export_picture(picture, 20, {**PARAMETERS, "dot_width": 0.02}, clean=None, dither="jarvis")
    layer = image_layer(data)
    summary = layer.image_summary()
    assert (summary["dither"], summary["dot_width_mm"], summary["dot_correction"]) == ("jarvis", 0.02, True)
    assert layer.unknown_settings == []
    text = data.decode()
    # the order of the operator's files of LightBurn 1.7 and 2.1: the dot width and its switch just before the line interval
    assert text.index('<dotWidth Value="0.02"/>') < text.index('<useDotCorrection Value="1"/>') < text.index('<interval Value="0.0254"/>')
    plain = image_layer(plans.export_picture(picture, 20, PARAMETERS, clean=None, dither="jarvis")).image_summary()
    assert (plain["dot_width_mm"], plain["dot_correction"]) == (None, None)                       # nothing written, nothing read


def test_a_dot_kind_corrects_the_dot_width_in_its_file_keeps_it_through_other_kinds_and_undo(app_world):
    client = app_world["client"]
    work = create(client, name="Ширина точки")
    assert work["dot_width"] is None
    dotted = settings(client, work, kind="jarvis")
    corrected = settings(client, work, dot_width=0.0204)
    assert corrected["dot_width"] == 0.02 and corrected["picture"]["preview"]                     # kept to a thousandth of a mm, as LightBurn shows it
    summary = image_layer(client.get(corrected["picture"]["file"]).content).image_summary()
    assert (summary["dither"], summary["dot_width_mm"], summary["dot_correction"]) == ("jarvis", 0.02, True)
    for wrong in (0, -0.01, 0.5, "much", True):
        refused = client.post(f"/api/photo-works/{work['id']}/settings", json={"dot_width": wrong})
        assert refused.status_code == 422
        assert refused.json()["error"] == "the dot width correction is a width of the laser's dot from 0.001 to 0.2 mm, or none to switch it off"
    grey = settings(client, work, kind="grayscale")
    assert grey["dot_width"] == 0.02                                                              # kept with the work, used by the dot kinds
    summary = image_layer(client.get(grey["picture"]["file"]).content).image_summary()
    assert (summary["dither"], summary["dot_width_mm"], summary["dot_correction"]) == ("grayscale", None, None)
    assert settings(client, work, kind="stucki")["dot_width"] == 0.02
    off = settings(client, work, dot_width=None)
    assert off["dot_width"] is None
    summary = image_layer(client.get(off["picture"]["file"]).content).image_summary()
    assert (summary["dither"], summary["dot_width_mm"], summary["dot_correction"]) == ("stucki", None, None)
    steps = [client.post(f"/api/photo-works/{work['id']}/undo").json() for _ in range(4)]
    assert [(s["kind"], s["dot_width"]) for s in steps] == [("stucki", 0.02), ("grayscale", 0.02), ("jarvis", 0.02), ("jarvis", None)]
    assert steps[-1]["dot_power"] == dotted["dot_power"]
    assert client.post(f"/api/photo-works/{work['id']}/redo").json()["dot_width"] == 0.02


def test_a_work_and_its_steps_saved_before_the_dot_width_open_without_the_correction(app_world):
    client, store = app_world["client"], app_world["client"].app.state.store
    work = create(client)
    settings(client, work, kind="atkinson")
    row = store.one("SELECT data_json FROM plan WHERE id=?", (work["id"],))
    data = json.loads(row["data_json"])
    data.pop("dot_width")
    for step in data["undo"]:
        step.pop("dot_width", None)
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), work["id"]))
    opened = client.get(f"/api/photo-works/{work['id']}").json()
    assert (opened["kind"], opened["dot_width"]) == ("atkinson", None)
    settings(client, work, dot_width=0.03)
    client.post(f"/api/photo-works/{work['id']}/undo")
    assert client.post(f"/api/photo-works/{work['id']}/undo").json()["dot_width"] is None


def test_the_ramp_of_the_kind_is_engraved_at_the_works_dot_width_and_its_tones_count_only_at_that_width(app_world):
    client, store = app_world["client"], app_world["client"].app.state.store
    work = create(client, name="Проба ширины точки")
    dotted = settings(client, work, kind="jarvis")
    corrected = settings(client, work, dot_width=0.025)
    dots = corrected["picture"]["dots"]
    made = client.post(f"/api/photo-works/{work['id']}/width-ramp")
    assert made.status_code == 201, made.text
    plan = plans.get_plan(store, made.json()["plan_id"])
    (tile,) = [layer for layer in plan["layers"] if layer.get("ramp")]
    assert (tile["ramp"]["dither"], tile["parameters"]["power"], tile["parameters"]["dot_width"]) == ("jarvis", dotted["dot_power"], 0.025)
    file = plans.export_lbrn2(plan)
    summary = image_layer(file).image_summary()
    assert (summary["dither"], summary["dot_width_mm"], summary["dot_correction"]) == ("jarvis", 0.025, True)
    clean, dot = rgb(dots["clean_hex"]), rgb(dots["hex"])
    photo = synth.plate_photo(plan, {}, size=(1300, 2800),
                              step_rgb=lambda name, grey: tuple(int(v) for v in np.round(clean + (dot - clean) * 0.6 * (1 - grey))))
    pid = ig.create_pair(store, device_id=app_world["laser"]["id"], lens_id=app_world["lens"]["id"],
                         stand_id=store.one("SELECT id FROM capture_setup ORDER BY id LIMIT 1")["id"], lightburn_name="dot-width.lbrn2",
                         lightburn_bytes=file, photo_name="dot-width.png", context={"material_id": work["scale"]["material_id"]},
                         photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    assert ig.check_pair(store, pid)["problems"] == []
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)
    measured = client.get(f"/api/photo-works/{work['id']}").json()
    assert not measured["picture"]["estimate"] and measured["picture"]["dots"]["measured"]["tones"] >= 8
    assert settings(client, work, dot_width=0.03)["picture"]["estimate"]                          # measured at 0.025 mm only
    assert settings(client, work, dot_width=None)["picture"]["estimate"]
    assert not settings(client, work, dot_width=0.025)["picture"]["estimate"]


def test_only_a_dot_kind_is_measured_at_a_dot_width():
    state = {"kind": "grayscale", "dot_width": 0.02, "dot_power": None, "dot_recipe": None}
    assert photo_state.dot_width_used(state) is None
    assert photo_state.dot_width_used({**state, "kind": "jarvis", "dot_power": 20}) == 0.02
    assert photo_state.dot_width_used({**state, "kind": "jarvis", "dot_power": 20, "dot_width": None}) is None
    assert photo_state.dot_width_used({"kind": "jarvis", "dot_power": 20}) is None                 # a photo zone has no dot width
