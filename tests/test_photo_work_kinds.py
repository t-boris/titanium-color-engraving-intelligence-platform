"""The kind of engraving of a photo work (0.21.0): «Какая гравировка?» shows the work's picture in every kind that colours titanium, a dot
kind fires every dot at one power taken on the scale (its colour the scale's at that power, the cleaned titanium between the dots), and
the work keeps its kind, the dots' power, its undo and its file."""
import json

import cv2
import numpy as np
import pytest

import synth
from test_grey_scales import app_world, picture_png  # noqa: F401  (the measured grey-ramp plate, four scales)
from titanium_platform import color, ingest as ig, lightburn, photo_modes, photo_work, plans, prediction_store as ps


def create(client, **fields):
    answer = client.post("/api/photo-works", data={"width_mm": 60, **fields}, files={"picture": ("girl.png", picture_png(), "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def settings(client, work, **changes):
    answer = client.post(f"/api/photo-works/{work['id']}/settings", json=changes)
    assert answer.status_code == 200, answer.text
    return answer.json()


def png(client, path) -> np.ndarray:
    answer = client.get(path)
    assert answer.status_code == 200 and answer.headers["content-type"] == "image/png", answer.text
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(answer.content, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def rgb(hex_colour: str) -> np.ndarray:
    return np.array([int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)], float)


def curve_of(client, work):
    plan = photo_work._work(client.app.state.store, work["id"])
    return ps.curve_for(client.app.state.store, photo_work.mode_of(plan), plan["width_mm"])[0]


def test_every_kind_that_colours_titanium_is_offered_with_the_works_picture_in_it(app_world):
    client = app_world["client"]
    work = create(client)
    assert work["kind"] == "grayscale" and work["dot_power"] is None
    offered = client.get(f"/api/photo-works/{work['id']}/kinds").json()
    keys = [k["key"] for k in offered["kinds"]]
    assert offered["kind"] == "grayscale" and keys == list(photo_work.KINDS) and "3dslice" not in keys
    assert set(keys) == {k for k, m in photo_modes.MODES.items() if m.family != photo_modes.DEPTH}
    grey = offered["kinds"][0]
    assert (grey["key"], grey["estimate"], grey["min_power"], grey["max_power"]) == ("grayscale", False, work["min_power"], work["max_power"])
    lo, hi = curve_of(client, work).span
    dots = [k for k in offered["kinds"] if k["key"] != "grayscale"]
    assert all(k["estimate"] and lo <= k["power"] <= hi and k["hex"].startswith("#") for k in dots)
    assert len({k["power"] for k in dots}) == 1                                                 # one power for every dot kind
    pictures = {k["key"]: png(client, k["picture"]) for k in offered["kinds"]}
    assert all(max(p.shape[:2]) == min(photo_work.TILE_PX, 240) for p in pictures.values())
    assert len({p.tobytes() for p in pictures.values()}) == len(pictures)                         # each kind looks its own way
    refused = client.get(f"/api/photo-works/{work['id']}/kinds/3dslice.png")
    assert refused.status_code == 404


def test_a_dot_kind_takes_the_power_whose_colour_stands_out_most_and_shows_its_dots_on_cleaned_titanium(app_world):
    client = app_world["client"]
    work = create(client)
    jarvis = settings(client, work, kind="jarvis")
    curve = curve_of(client, work)
    clean = ps.clean_titanium(client.app.state.store)
    assert jarvis["kind"] == "jarvis" and jarvis["dot_power"] == ps.dot_power(curve, clean)
    dots = jarvis["picture"]["dots"]
    assert jarvis["picture"]["estimate"] and dots["power"] == jarvis["dot_power"]
    assert dots["lab"] == pytest.approx(curve.lab_at(dots["power"]), abs=0.01) and dots["clean_lab"] == pytest.approx(clean, abs=0.01)
    assert 0.4 < dots["struck_share"] < 0.6                                                    # a ramp from white to black: half struck
    shown = png(client, jarvis["picture"]["preview"])
    look = shown[:, shown.shape[1] - 240:]                                                      # the right half: the dots on the titanium
    assert np.abs(look[:, :3].mean(axis=(0, 1)) - rgb(dots["clean_hex"])).max() <= 3           # white: no dot, the cleaned titanium
    assert np.abs(look[:, -3:].mean(axis=(0, 1)) - rgb(dots["hex"])).max() <= 3                # black: every dot, the scale's colour
    # far from both ends the colour lies between them, mixed as light mixes
    middle = color.srgb_to_linear(look[:, 110:130].mean(axis=(0, 1)) / 255)
    ends = color.srgb_to_linear(np.array([rgb(dots["clean_hex"]), rgb(dots["hex"])]) / 255)
    share = np.dot(middle - ends[0], ends[1] - ends[0]) / np.dot(ends[1] - ends[0], ends[1] - ends[0])
    assert 0.35 < share < 0.65
    assert client.get(f"/api/photo-works/{work['id']}").json()["picture"]["preview"] == jarvis["picture"]["preview"]


def test_the_dots_are_shown_dot_for_dot_in_two_colours_close_up(app_world):
    client = app_world["client"]
    work = create(client)
    refused = client.get(f"/api/photo-works/{work['id']}/closeup.png")
    assert refused.status_code == 422 and refused.json()["error"] == "a work in grayscale has no dots to show"
    dotted = settings(client, work, kind="dither")
    close = png(client, dotted["picture"]["closeup"])
    side = round(ps.CLOSEUP_MM / 25.4 * dotted["dpi"]) * ps.CLOSEUP_PX                      # 4 mm at the layer's DPI, each dot 3 px
    assert close.shape[:2] == (side, side)
    colours = {tuple(c) for c in close.reshape(-1, 3)}
    assert colours <= {tuple(rgb(dotted["picture"]["dots"]["hex"]).astype(int)), tuple(rgb(dotted["picture"]["dots"]["clean_hex"]).astype(int))}
    assert len(colours) == 2


def test_the_dots_power_is_chosen_inside_the_measured_powers_kept_through_other_kinds_and_undone(app_world):
    client = app_world["client"]
    work = create(client)
    lo, hi = curve_of(client, work).span
    settings(client, work, kind="atkinson")
    chosen = settings(client, work, dot_power=lo + 3)
    assert chosen["dot_power"] == lo + 3 and chosen["picture"]["dots"]["power"] == lo + 3
    for wrong in (hi + 5, "much", True, None):
        refused = client.post(f"/api/photo-works/{work['id']}/settings", json={"dot_power": wrong})
        assert refused.status_code == 422
        assert refused.json()["error"] == f"the dots' power must be a number inside the scale's measured powers {lo:g}..{hi:g} % at the work's width"
    refused = client.post(f"/api/photo-works/{work['id']}/settings", json={"kind": "3dslice"})
    assert refused.status_code == 422 and refused.json()["error"].startswith("the kind of engraving must be one of grayscale, threshold")
    stucki = settings(client, work, kind="stucki")
    assert stucki["dot_power"] == lo + 3                                                          # the power stays with the work
    back = settings(client, work, kind="grayscale")
    assert (back["min_power"], back["max_power"], back["picture"]["preview"]) == (work["min_power"], work["max_power"], work["picture"]["preview"])
    undone = client.post(f"/api/photo-works/{work['id']}/undo").json()
    assert (undone["kind"], undone["dot_power"]) == ("stucki", lo + 3)
    undone = client.post(f"/api/photo-works/{work['id']}/undo").json()
    assert (undone["kind"], undone["dot_power"]) == ("atkinson", lo + 3)
    undone = client.post(f"/api/photo-works/{work['id']}/undo").json()
    assert undone["kind"] == "atkinson" and undone["dot_power"] == ps.dot_power(curve_of(client, work), ps.clean_titanium(client.app.state.store))
    undone = client.post(f"/api/photo-works/{work['id']}/undo").json()
    assert (undone["kind"], undone["picture"]["preview"]) == ("grayscale", work["picture"]["preview"])


def test_the_file_of_a_dot_kind_cleans_first_then_engraves_the_picture_as_uploaded_in_that_kind_at_the_dots_power(app_world):
    client = app_world["client"]
    work = create(client, name="Точки")
    settings(client, work, by_colour=True, contours=True)                                       # grayscale's own settings wait for it
    dotted = settings(client, work, kind="jarvis")
    power = dotted["dot_power"]
    file = client.get(dotted["picture"]["file"])
    assert file.status_code == 200 and f"-jarvis-P{power:g}.lbrn2" in file.headers["content-disposition"]
    project = lightburn.parse_bytes(file.content)
    clean, layer = project.layer(0), project.layer(1)
    assert clean.name.startswith("CLEAN-CROSSHATCH-") and clean.burn_order < layer.burn_order
    summary = layer.image_summary()
    assert (layer.layer_type, summary["dither"], layer.power, summary["min_power"]) == ("Image", "jarvis", power, power)
    stored = cv2.imdecode(np.frombuffer(layer.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_UNCHANGED)[::-1]
    upload = cv2.imdecode(np.frombuffer(picture_png(), np.uint8), cv2.IMREAD_UNCHANGED)
    assert np.array_equal(stored, upload)                                                       # LightBurn makes the dots of the picture as it is
    thumb = png(client, f"/api/photo-works/{work['id']}/thumb.png")
    grey_thumb = png(client, f"/api/photo-works/{work['id']}/kinds/grayscale.png")
    assert thumb.shape == grey_thumb.shape and not np.array_equal(thumb, grey_thumb)


def test_a_work_saved_before_the_kinds_opens_in_grayscale_with_no_object_coloured(app_world):
    client = app_world["client"]
    store = client.app.state.store
    work = create(client)
    row = store.one("SELECT data_json FROM plan WHERE id=?", (work["id"],))
    data = {k: v for k, v in json.loads(row["data_json"]).items() if k not in ("kind", "dot_power", "colouring")}   # as 0.20.3 stored it
    store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(data), work["id"]))
    opened = client.get(f"/api/photo-works/{work['id']}").json()
    assert (opened["kind"], opened["dot_power"], opened["colouring"]) == ("grayscale", None, {})
    assert opened["picture"]["preview"] == work["picture"]["preview"]
    listed = next(w for w in client.get("/api/photo-works").json() if w["id"] == work["id"])
    assert listed["kind"] == "grayscale"
    assert settings(client, work, kind="halftone")["picture"]["dots"]["power"] > 0


def test_a_ramp_in_the_works_dot_kind_once_photographed_replaces_the_estimate_with_the_tones_it_measured(app_world):
    client, store = app_world["client"], app_world["client"].app.state.store
    work = create(client, name="Проба точек")
    dotted = settings(client, work, kind="jarvis")
    power, dots = dotted["dot_power"], dotted["picture"]["dots"]
    made = client.post(f"/api/photo-works/{work['id']}/width-ramp")
    assert made.status_code == 201, made.text
    plan = plans.get_plan(store, made.json()["plan_id"])
    (tile,) = [layer for layer in plan["layers"] if layer.get("ramp")]
    assert (tile["ramp"]["dither"], tile["ramp"]["width"], tile["parameters"]["min_power"], tile["parameters"]["power"]) == ("jarvis", 60, power, power)
    file = plans.export_lbrn2(plan)
    (layer,) = [layer for layer in lightburn.parse_bytes(file).layers if layer.layer_type == "Image"]
    assert (layer.image_summary()["dither"], layer.power) == ("jarvis", power)                   # LightBurn makes the dots of each step
    # photographed: each step lighter than the estimate says (real dots smaller than their share), so the measured tones are seen to win
    clean, dot = rgb(dots["clean_hex"]), rgb(dots["hex"])
    photo = synth.plate_photo(plan, {}, size=(1300, 2800),
                              step_rgb=lambda name, grey: tuple(int(v) for v in np.round(clean + (dot - clean) * 0.6 * (1 - grey))))
    pid = ig.create_pair(store, device_id=app_world["laser"]["id"], lens_id=app_world["lens"]["id"],
                         stand_id=store.one("SELECT id FROM capture_setup ORDER BY id LIMIT 1")["id"], lightburn_name="dots.lbrn2",
                         lightburn_bytes=file, photo_name="dots.png", context={"material_id": work["scale"]["material_id"]},
                         photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    assert ig.check_pair(store, pid)["problems"] == []
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)
    measured = client.get(f"/api/photo-works/{work['id']}").json()
    assert not measured["picture"]["estimate"] and measured["picture"]["dots"]["measured"]["tones"] >= 8
    look = png(client, measured["picture"]["preview"])[:, -240:]
    black = look[:, -3:].mean(axis=(0, 1))
    assert np.abs(black - (clean + (dot - clean) * 0.6)).max() <= 6                               # the black step as photographed, not the dots' colour
    offered = {k["key"]: k["estimate"] for k in client.get(f"/api/photo-works/{work['id']}/kinds").json()["kinds"]}
    assert offered["jarvis"] is False and offered["atkinson"] is True and offered["grayscale"] is False
    lo, hi = curve_of(client, work).span
    other = settings(client, work, dot_power=round(lo + 1, 1) if power > lo + 2 else round(hi - 1, 1))
    assert other["picture"]["estimate"]                                                           # measured at its power only
