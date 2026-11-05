"""Documents made before the UX P0 pass still open, edit and export (feature ux-validation-p0, REQ-003; research n50, protocol section 5 of
docs/validation/ux-p0-protocol.md).

Four kinds of document, each through the real HTTP API (FastAPI's TestClient over a real workshop directory):

* artwork, the colour engraving of a picture (``/api/discrete``, route ``/artwork``);
* photo, a continuous engraving in stripes (``/api/continuous``, route ``/photo``): ``band_count`` bands, tonal or along a colour path;
* photo-preview, the forecast of a LightBurn file made elsewhere (``/api/predictions/photo``, route ``/photo-preview``);
* the photo work of the photo-engraving section (``/api/photo-works``, route ``/photo-engraving``).

"Old" is defined by evidence, not by guesswork. ``tests/fixtures/legacy_0_38_1/`` holds what release 0.38.1 (commit c89b339, run from
``git archive``) stored and wrote: the key set of every stored plan and the two LightBurn files it made. The source files that write an
artwork, a stripes plan and a photo work (``conversion.py``, ``plans.py``, ``photo_work.py``) have no change since that release, so a
document made today is stored exactly as one made then; the one thing that differs is the record of the files handed out, which 0.38.1 did
not keep (a plan only became "Exported"). The tests below therefore make an old exported plan by the same endpoints and take the record out,
which is what 0.38.1 left in the database (the first test proves the two key sets).

A photo-preview keeps nothing, so it has no document to reopen or export: its "reopen" is drawing the kept upload again at other Min and Max
and its "export" is the picture it draws; both are checked, and the test says so. Nothing here needs a browser except the last test, which
runs the real route table in node."""
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import obs
from test_discrete import BLUE_LAB, RED_LAB, png as stripes_png, rgb_of
from test_continuous import gradient_png
from test_grey_scales import app_world, picture_png  # noqa: F401  (the measured grey-ramp plate, four scales; fixture)
from test_photo_works import create as new_photo_work
from test_vector_work import UI
from titanium_platform import conversion as cv, knowledge as kn, lightburn, plans as pl, setup as su
from titanium_platform.api.app import create_app

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
FIXTURES = Path(__file__).with_name("fixtures") / "legacy_0_38_1"
OLD = json.loads((FIXTURES / "stored_plans.json").read_text(encoding="utf-8"))
FAR = (90.0, -60.0, 70.0)                 # a colour no measured titanium colour comes near enough to
LIGHTNESS = {10: RED_LAB[0], 30: BLUE_LAB[0], 20: 55.0, 40: 75.0}      # power -> L* of the colour measured at it (see the fixture)


@pytest.fixture(scope="module")
def legacy(tmp_path_factory):
    """A laser and lens with four measured colours (red, blue and two greys of different lightness), as the conversion tests measure them."""
    app = create_app(tmp_path_factory.mktemp("legacy"))
    store = app.state.store
    w = obs.setup(store)
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *w["setup"], criteria_agreed=True)
    for power, base in ((10, RED_LAB), (30, BLUE_LAB), (20, (55.0, 5.0, 5.0)), (40, (75.0, -5.0, 5.0))):
        for dl in (-1.0, 1.0):
            obs.add(store, w, (base[0] + dl, base[1], base[2]), power=power)
    kn.refresh(store, *w["setup"])
    ids = {k["parameters"]["power"]: k["id"] for k in kn.list_for_setup(store, *w["setup"])}
    with TestClient(app) as client:
        yield {"client": client, "store": store, "ids": ids, "device": str(w["setup"][0]), "lens": str(w["setup"][1])}
    store.close()


# -- helpers ------------------------------------------------------------------------------------------------------------------------------
def artwork(L, name, colours, **extra) -> dict:
    answer = L["client"].post("/api/discrete", data={"device_id": L["device"], "lens_id": L["lens"], "name": name, "width_mm": 40, "threshold": 8,
                                                      **extra}, files={"image": ("a.png", stripes_png(colours), "image/png")})
    assert answer.status_code == 201, answer.text
    return answer.json()


def stripes(L, name, mode="tonal", bands=4, expect=201, **extra):
    answer = L["client"].post("/api/continuous", data={"device_id": L["device"], "lens_id": L["lens"], "name": name, "width_mm": 40, "mode": mode,
                                                        "bands": bands, **extra}, files={"image": ("g.png", gradient_png(), "image/png")})
    assert answer.status_code == expect, answer.text
    return answer.json()


def stored(L, plan_id) -> tuple:
    """The row and the document exactly as the database keeps them."""
    row = L["store"].one("SELECT * FROM plan WHERE id=?", (plan_id,))
    return row, json.loads(row["data_json"])


def the_old_way(L, plan_id):
    """The plan as 0.38.1 left it after a file was handed out: status "Exported" and no record of the file (the release did not keep one)."""
    _, data = stored(L, plan_id)
    data.pop("exports", None)
    L["store"].execute("UPDATE plan SET status='Exported', data_json=? WHERE id=?", (json.dumps(data), plan_id))
    assert "exports" not in stored(L, plan_id)[1]


def files_of(answer) -> list:
    return [(f["number"], f["recorded"], f["downloadable"]) for f in answer["lifecycle"]["files"]]


def layers_of(file_bytes: bytes) -> list:
    """What a LightBurn file asks the laser to do: the settings and the area of every layer, in order."""
    project = lightburn.parse_bytes(file_bytes)
    return [((l.power, l.frequency_khz, l.speed), round(sum(r.width * r.height for r in l.regions), 3)) for l in project.layers]


def status_of(answer: dict, wanted: str) -> str:
    """The source key of the colour of the picture whose match has the status ``wanted`` (the matches are not listed in the picture's order)."""
    return next(m["source_key"] for m in answer["matches"] if m["status"] == wanted)


def statuses(answer: dict) -> list:
    return sorted(m["status"] for m in answer["matches"])


def refused(answer, status, *words):
    assert answer.status_code == status and all(w in answer.json()["error"] for w in words), (answer.status_code, answer.text)


# -- what was stored then is what is stored now ----------------------------------------------------------------------------------------
def test_a_plan_made_today_is_stored_with_the_keys_0_38_1_stored_and_an_export_only_adds_the_record_of_the_file(legacy):
    """The premise of every test below: there is nothing to migrate. Artwork, stripes and colour-path plans have the very key sets the
    release captured in ``fixtures/legacy_0_38_1/stored_plans.json``; handing out a file adds one key, ``exports``, and nothing else."""
    client = legacy["client"]
    art = artwork(legacy, "Keys", [rgb_of(RED_LAB), rgb_of(BLUE_LAB)])
    row, data = stored(legacy, art["id"])
    assert sorted(data) == OLD["artwork"]["draft_keys"] and row["mode"] == OLD["artwork"]["mode"] and row["status"] == "Draft"
    assert set(OLD["row_columns_compared"]) <= set(row.keys())
    assert client.post(f"/api/discrete/{art['id']}/finalize").status_code == 200
    assert sorted(stored(legacy, art["id"])[1]) == OLD["artwork"]["ready_keys"]
    assert client.get(f"/api/plans/{art['id']}/export.lbrn2").status_code == 200
    row, data = stored(legacy, art["id"])
    assert row["status"] == "Exported" and sorted(data) == sorted(OLD["artwork"]["exported_keys"] + ["exports"])
    assert [e["number"] for e in data["exports"]] == [1]

    for mode, kind, fields in (("tonal", "stripes", {}), ("color_path", "color_path", {"bands": 3, "path_ids": json.dumps([legacy["ids"][p] for p in (10, 20, 30)])})):
        made = stripes(legacy, "Keys " + kind, mode=mode, **fields)
        row, data = stored(legacy, made["id"])
        assert sorted(data) == OLD[kind]["ready_keys"] and (row["mode"], row["band_count"]) == (OLD[kind]["mode"], OLD[kind]["band_count"])
    exported = stripes(legacy, "Keys exported")
    assert client.get(f"/api/plans/{exported['id']}/export.lbrn2").status_code == 200
    assert sorted(stored(legacy, exported["id"])[1]) == sorted(OLD["stripes"]["exported_keys"] + ["exports"])



# -- artwork (colour engraving) -----------------------------------------------------------------------------------------------------------
def test_artwork_with_colours_the_laser_cannot_reach_is_blocked_until_each_is_replaced_or_excluded_then_exports_and_reopens(legacy):
    """An unreachable colour blocks the plan: it stays a draft, cannot be finalised and has no file, and the refusals change nothing stored.
    Excluding the colour keeps it out of the file; replacing it by a measured colour engraves that colour instead."""
    client, ids = legacy["client"], legacy["ids"]
    art = artwork(legacy, "Blocked", [rgb_of(RED_LAB), rgb_of(FAR)])
    assert art["status"] == cv.ST_DRAFT and statuses(art) == ["matched", "unreachable"]
    assert art["lifecycle"]["readiness"]["ready"] is False and art["lifecycle"]["readiness"]["blockers"] == [{"code": "draft"}]
    assert art["lifecycle"]["readiness"]["checks"]["colours"] is False and files_of(art) == []
    before = stored(legacy, art["id"])
    refused(client.post(f"/api/discrete/{art['id']}/finalize"), 422, "1 unreachable color(s) must be replaced or excluded")
    refused(client.get(f"/api/plans/{art['id']}/export.lbrn2"), 422, "the plan is a draft")
    after = stored(legacy, art["id"])
    assert (after[0]["status"], after[1]) == (before[0]["status"], before[1])              # the refusals changed nothing
    key = status_of(art, "unreachable")

    excluded = client.patch(f"/api/discrete/{art['id']}", json={"exclusions": [key]}).json()
    assert statuses(excluded) == ["excluded", "matched"] and excluded["lifecycle"]["readiness"]["checks"]["colours"] is True
    ready = client.post(f"/api/discrete/{art['id']}/finalize")
    assert ready.status_code == 200 and ready.json()["status"] == cv.ST_READY and ready.json()["lifecycle"]["readiness"]["ready"] is True
    handed = client.get(f"/api/plans/{art['id']}/export.lbrn2")
    assert handed.status_code == 200 and handed.headers["content-type"].startswith("application/xml")
    assert [settings for settings, _ in layers_of(handed.content)] == [(10.0, 40.0, 900.0)]       # only the red: the excluded colour is not engraved

    reopened = client.get(f"/api/plans/{art['id']}").json()
    assert reopened["status"] == "Exported" and files_of(reopened) == [(1, True, False)] and reopened["lifecycle"]["chain"]["stage"] == "file"
    assert [p["status"] for p in client.get("/api/plans").json() if p["id"] == art["id"]] == ["Exported"]

    swapped = artwork(legacy, "Replaced", [rgb_of(RED_LAB), rgb_of(FAR)])
    key = status_of(swapped, "unreachable")
    refused(client.patch(f"/api/discrete/{swapped['id']}", json={"replacements": {key: 999999}}), 422)           # an unknown colour is no replacement
    replaced = client.patch(f"/api/discrete/{swapped['id']}", json={"replacements": {key: ids[30]}}).json()
    assert statuses(replaced) == ["matched", "replaced"]
    assert client.post(f"/api/discrete/{swapped['id']}/finalize").status_code == 200
    two = client.get(f"/api/plans/{swapped['id']}/export.lbrn2")
    assert sorted(settings[0] for settings, _ in layers_of(two.content)) == [10.0, 30.0]                # the replacement colour is in the file


def test_an_artwork_plan_exported_by_0_38_1_reopens_with_one_unnumbered_file_and_exports_again_as_file_1(legacy):
    client = legacy["client"]
    art = artwork(legacy, "Old artwork", [rgb_of(RED_LAB), rgb_of(BLUE_LAB)])
    client.post(f"/api/discrete/{art['id']}/finalize")
    first = layers_of(client.get(f"/api/plans/{art['id']}/export.lbrn2").content)          # what the old release handed out
    the_old_way(legacy, art["id"])

    old = client.get(f"/api/plans/{art['id']}")
    assert old.status_code == 200 and old.json()["status"] == "Exported" and statuses(old.json()) == ["matched", "matched"]
    assert files_of(old.json()) == [(0, False, False)]                                       # one file, unnumbered, date unknown, not downloadable
    assert old.json()["lifecycle"]["chain"]["stage"] == "file" and old.json()["lifecycle"]["readiness"]["ready"] is True
    assert client.get(f"/api/discrete/{art['id']}/palette").status_code == 200                # what the artwork screen asks for
    assert client.get(f"/api/plans/{art['id']}/source-image").content == stripes_png([rgb_of(RED_LAB), rgb_of(BLUE_LAB)])
    assert client.get(f"/api/plans/{art['id']}/banding.png").headers["content-type"] == "image/png"

    again = client.get(f"/api/plans/{art['id']}/export.lbrn2")
    assert again.status_code == 200 and layers_of(again.content) == first                    # the same layers, settings and areas as before
    now = client.get(f"/api/plans/{art['id']}").json()
    assert now["status"] == "Exported" and files_of(now) == [(1, True, False)]                # from now on it is file 1, recorded

    # an old exported plan can also be corrected: the edit takes it back to a draft, and it is finalised and exported like a new one
    the_old_way(legacy, art["id"])
    blue = next(m for m in art["matches"] if m["knowledge_id"] == legacy["ids"][30])
    edited = client.patch(f"/api/discrete/{art['id']}", json={"exclusions": [blue["source_key"]]}).json()
    assert edited["status"] == cv.ST_DRAFT and edited["lifecycle"]["readiness"]["blockers"] == [{"code": "draft"}]
    assert client.post(f"/api/discrete/{art['id']}/finalize").status_code == 200
    final = client.get(f"/api/plans/{art['id']}/export.lbrn2")
    assert [settings for settings, _ in layers_of(final.content)] == [(10.0, 40.0, 900.0)]
    assert files_of(client.get(f"/api/plans/{art['id']}").json()) == [(1, True, False)]


# -- photo (continuous engraving in stripes) ---------------------------------------------------------------------------------------------
def test_a_stripes_photo_is_made_with_its_band_count_tiles_the_picture_exports_a_layer_per_band_and_reopens(legacy):
    client = legacy["client"]
    made = stripes(legacy, "Portrait", bands=4)
    assert made["status"] == cv.ST_READY and made["band_count"] == 4 and made["mode"] == pl.MODE_TONAL and len(made["layers"]) == 4
    plan = pl.get_plan(legacy["store"], made["id"])
    area = sum(r["width"] * r["height"] for layer in plan["layers"] for r in layer["regions"])
    assert area == pytest.approx(plan["size_mm"]["width"] * plan["size_mm"]["height"], rel=1e-6)           # the bands tile the whole picture
    assert [p["band_count"] for p in client.get("/api/plans").json() if p["id"] == made["id"]] == [4]

    handed = client.get(f"/api/plans/{made['id']}/export.lbrn2")
    exported = layers_of(handed.content)
    assert handed.status_code == 200 and len(exported) == made["band_count"]                   # one layer per band
    lightness = [LIGHTNESS[int(settings[0])] for settings, _ in exported]
    assert lightness == sorted(lightness) and len(set(lightness)) == 4                          # the four measured colours, darker band to lighter
    reopened = client.get(f"/api/plans/{made['id']}").json()
    assert reopened["status"] == "Exported" and reopened["band_count"] == 4 and files_of(reopened) == [(1, True, False)]
    assert layers_of(client.get(f"/api/plans/{made['id']}/export.lbrn2").content) == exported            # exporting again gives the same file
    assert files_of(client.get(f"/api/plans/{made['id']}").json()) == [(1, True, False), (2, True, False)]


def test_the_stripes_band_count_is_limited_by_the_layers_lightburn_has_and_the_limit_is_told(legacy):
    client = legacy["client"]
    limit = client.get("/api/continuous/limits").json()["max_bands"]
    assert limit == cv.MAX_BANDS == pl.MAX_LAYERS - 1
    biggest = stripes(legacy, "Most bands", bands=limit)
    assert biggest["band_count"] == limit and len(biggest["layers"]) == limit
    rows = legacy["store"].one("SELECT COUNT(*) AS n FROM plan")["n"]
    for bands in (0, -3, limit + 1):
        refused(client.post("/api/continuous", data={"device_id": legacy["device"], "lens_id": legacy["lens"], "name": "x", "width_mm": 40, "mode": "tonal",
                                                      "bands": bands}, files={"image": ("g.png", gradient_png(), "image/png")}), 422)
    assert legacy["store"].one("SELECT COUNT(*) AS n FROM plan")["n"] == rows                    # a refused band count makes no plan
    shown = client.post("/api/continuous/preview", data={"device_id": legacy["device"], "lens_id": legacy["lens"], "mode": "tonal", "width_mm": 40,
                                                          "bands": 5}, files={"image": ("g.png", gradient_png(), "image/png")}).json()
    assert len(shown["layers"]) == 5 and shown["banding_png"].startswith("data:image/png;base64,")
    assert legacy["store"].one("SELECT COUNT(*) AS n FROM plan")["n"] == rows                    # the preview keeps nothing


def test_a_stripes_photo_along_a_colour_path_keeps_the_operators_order_and_a_revision_leaves_the_plan_it_revises_alone(legacy):
    client, ids = legacy["client"], legacy["ids"]
    order = [ids[40], ids[10], ids[30]]                                                         # not sorted by lightness on purpose
    path = stripes(legacy, "Path", mode="color_path", bands=3, path_ids=json.dumps(order))
    assert path["mode"] == pl.MODE_COLOR_PATH and path["band_count"] == 3 and len(path["layers"]) == 3
    assert [p["knowledge_id"] for p in pl.get_plan(legacy["store"], path["id"])["transfer"]["points"]] == order
    assert len(layers_of(client.get(f"/api/plans/{path['id']}/export.lbrn2").content)) == 3

    original = stored(legacy, path["id"])
    revision = stripes(legacy, "Path, again", mode="color_path", bands=5, path_ids=json.dumps(order), revision_of=path["id"])
    assert revision["id"] != path["id"] and revision["band_count"] == 5 and stored(legacy, revision["id"])[1]["revision_of"] == path["id"]
    kept = stored(legacy, path["id"])
    assert (kept[0]["status"], kept[0]["band_count"], kept[1]) == (original[0]["status"], 3, original[1])        # the revised plan is unchanged
    assert client.get(f"/api/plans/{path['id']}").json()["status"] == "Exported"
    refused(client.post("/api/continuous", data={"device_id": legacy["device"], "lens_id": legacy["lens"], "name": "x", "width_mm": 40, "mode": "tonal",
                                                  "bands": 4, "revision_of": 987654}, files={"image": ("g.png", gradient_png(), "image/png")}), 404)


def test_a_stripes_photo_exported_by_0_38_1_reopens_with_its_band_count_and_exports_again(legacy):
    client = legacy["client"]
    made = stripes(legacy, "Old stripes", bands=6)
    first = layers_of(client.get(f"/api/plans/{made['id']}/export.lbrn2").content)
    the_old_way(legacy, made["id"])
    old = client.get(f"/api/plans/{made['id']}").json()
    assert old["status"] == "Exported" and old["band_count"] == 6 and len(old["layers"]) == 6 and files_of(old) == [(0, False, False)]
    assert client.get(f"/api/plans/{made['id']}/banding.png").status_code == 200
    assert layers_of(client.get(f"/api/plans/{made['id']}/export.lbrn2").content) == first
    assert files_of(client.get(f"/api/plans/{made['id']}").json()) == [(1, True, False)]


# -- photo-preview (the forecast of a LightBurn file made elsewhere) ------------------------------------------------------------------
def forecast(world, name):
    data = {"device_id": world["laser"]["id"], "lens_id": str(world["lens"]["id"]), "material_id": world["titanium"]["id"]}
    return world["client"].post("/api/predictions/photo", data=data, files={"lightburn": (name, (FIXTURES / name).read_bytes(), "application/xml")})


def test_files_made_by_0_38_1_are_forecast_drawn_again_at_other_min_and_max_and_keep_nothing(app_world):
    """Create = uploading the file; reopen = drawing the kept upload again at other Min and Max without a new upload; export = the picture that
    is drawn (PNG, the picture beside its predicted look). A forecast stores no document: the tables do not change."""
    client, store = app_world["client"], app_world["client"].app.state.store
    tables = ("pair", "observation", "audit", "plan")
    rows = {table: store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in tables}
    for name in ("photo_work.lbrn2", "picture.lbrn2"):                  # the photo work's file and the file of a picture on a scale, both written by 0.38.1
        answer = forecast(app_world, name)
        assert answer.status_code == 200, (name, answer.text)
        body = answer.json()
        (layer,) = body["layers"]
        assert layer["refused"] is None and layer["dither"] == "grayscale" and body["file"] == name
        assert layer["settings"]["overridden"] == [] and layer["mode"]["speed"] == 150.0 and layer["mode"]["line_interval"] == 0.0169
        assert layer["power_range"] == [2.0, 29.87] and layer["outside_share"] == 0.0               # the file's own Min and Max, inside the measured span
        own = client.get(layer["preview"])
        wide = client.get(layer["preview"], params={"min_power": 2, "max_power": 40})
        assert own.status_code == wide.status_code == 200 and own.headers["content-type"] == "image/png" and own.content != wide.content
        a = cv2.imdecode(np.frombuffer(own.content, np.uint8), cv2.IMREAD_COLOR)
        assert a.shape[0] > 0 and a.shape[1] > a.shape[0]                                          # picture and prediction side by side
        again = client.get(layer["preview"][:-len(".png")], params={"min_power": 2, "max_power": 40}).json()
        assert again["power_range"] == [2.0, 40.0]
    assert {table: store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in tables} == rows
    gone = client.get("/api/predictions/photo/0123456789abcdef/1.png")
    assert gone.status_code == 404 and "no longer kept" in gone.json()["error"]


def test_the_file_0_38_1_made_for_a_photo_work_is_forecast_as_the_file_made_today_is(app_world):
    """The file of 0.38.1 and the file the same work gives today predict the same: the same layer settings, curve and look. (Only the identifier
    of the work inside the file's note differs.)"""
    client = app_world["client"]
    old = forecast(app_world, "photo_work.lbrn2").json()["layers"][0]
    work = new_photo_work(client)
    today = client.get(f"/api/photo-works/{work['id']}/export.lbrn2").content
    data = {"device_id": app_world["laser"]["id"], "lens_id": str(app_world["lens"]["id"]), "material_id": app_world["titanium"]["id"]}
    now = client.post("/api/predictions/photo", data=data, files={"lightburn": ("today.lbrn2", today, "application/xml")}).json()["layers"][0]
    for key in ("settings", "mode", "span", "power_range", "outside_share", "curve", "dither"):
        assert old[key] == now[key], key
    assert client.get(old["preview"]).content == client.get(now["preview"]).content                 # the very picture


# -- the photo work of the photo-engraving section -----------------------------------------------------------------------------------------
def test_a_photo_work_is_stored_as_0_38_1_stored_it_reopens_and_exports_through_its_own_routes(app_world):
    client, store = app_world["client"], app_world["client"].app.state.store
    work = new_photo_work(client, name="Old route")
    row = store.one("SELECT * FROM plan WHERE id=?", (work["id"],))
    assert sorted(json.loads(row["data_json"])) == OLD["photo_work"]["keys"] and (row["mode"], row["status"]) == (OLD["photo_work"]["mode"], OLD["photo_work"]["status"])
    shown = client.get(f"/api/photo-works/{work['id']}").json()
    assert shown["name"] == "Old route" and shown["width_mm"] == 60 and shown["picture"]["preview"]
    assert client.get(f"/api/photo-works/{work['id']}/picture").content == picture_png()
    handed = client.get(f"/api/photo-works/{work['id']}/export.lbrn2")
    assert handed.status_code == 200
    project = lightburn.parse_bytes(handed.content)
    region = project.layer(1).regions[0]
    assert (round(region.width, 3), round(region.height, 3)) == (60.0, 30.0) and region.bitmap["png"]
    # the older address of every plan, /api/plans/{id}, still answers for it, without the file records a photo work does not keep
    generic = client.get(f"/api/plans/{work['id']}")
    assert generic.status_code == 200 and "lifecycle" not in generic.json() and generic.json()["mode"] == pl.MODE_PHOTO_WORK
    assert [w["id"] for w in client.get("/api/photo-works").json()].count(work["id"]) == 1
    reopened = TestClient(create_app(store.data_dir))                                              # the application started again over the same data
    assert reopened.get(f"/api/photo-works/{work['id']}/export.lbrn2").content == handed.content
    reopened.close()


# -- the old addresses of the screens -------------------------------------------------------------------------------------------------------
ADDRESSES = [
    # (address, screen that must draw it, the section of the menu that is marked as current)
    ("#/artwork", "artwork", "/vector"), ("#/artwork?plan=12", "artwork", "/vector"), ("#/artwork?id=12", "artwork", "/vector"),
    ("#/photo", "photo", "/photo-engraving"), ("#/photo?plan=12", "photo", "/photo-engraving"),
    ("#/photo-preview", "photo-preview", "/photo-engraving"), ("#/photo-preview?pair=3", "photo-preview", "/photo-engraving"),
    ("#/photo-preview?work=7", "photo-preview", "/photo-engraving"),
    ("#/photo-engraving", "photo-engraving", "/photo-engraving"), ("#/photo-engraving?work=7", "photo-engraving", "/photo-engraving"),
    ("#/photo-engraving?scales=1", "photo-engraving", "/photo-engraving"),
    ("#/vector", "vector", "/vector"), ("#/vector?plan=5", "vector", "/vector"), ("#/vector?new=1", "vector", "/vector"),
    ("#/vector?new=1&classic=1", "vector", "/vector"), ("#/vector-zone?work=5", "vector-zone", "/vector"), ("#/new", "new", "/vector"),
    ("#/plans/9", "plan", "/experiments"), ("#/knowledge", "colors", "/colors"), ("#/knowledge/3", "colors", "/colors"),
    ("#/experiments", "experiments", "/experiments"), ("#/works", "works", "/works"), ("#/nonsense", "experiments", "/nonsense"),
    ("", "experiments", "/experiments"),
]

ROUTES = """
const fs = require('fs');
const {context, load, El} = require(%(dom)s);
const ctx = context({});
const root = new El('div'); root.setAttribute('id', 'app'); ctx.document.body.append(root);
ctx.document.getElementById = (id) => (id === 'app' ? root : null);
ctx.document.querySelectorAll = (s) => ctx.document.body.querySelectorAll(s);
const html = fs.readFileSync(%(ui)s + 'index.html', 'utf8');
const scripts = [...html.matchAll(/<script src="\\/([^"]+)"/g)].map((m) => m[1]).filter((s) => s !== 'boot.js');
load(ctx, %(ui)s, scripts);                                   // every script of the page, as the browser loads them (boot.js only starts the router)
(async () => {
  const App = ctx.App, drawn = [];
  for (const [id, screen] of App.screens) screen.render = async (route) => { drawn.push({id, arg: route.arg, query: route.query}); return ctx.document.createElement('div'); };
  const out = {screens: [...App.screens.keys()], routes: []};
  for (const address of %(addresses)s) {
    drawn.length = 0;
    ctx.location.hash = address;
    await App.render();
    const current = root.querySelectorAll('a').filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.getAttribute('href').slice(1));
    const error = root.querySelectorAll('div').some((d) => (d.className || '').split(' ').includes('bad'));
    out.routes.push({address, drawn: drawn.map((d) => d.id), query: drawn.length ? drawn[0].query : null, arg: drawn.length ? drawn[0].arg : null, current, error});
  }
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


@node
def test_every_old_address_of_a_screen_is_still_drawn_by_the_screen_it_always_belonged_to(tmp_path):
    """The route table of the real page: the scripts of ``index.html`` are loaded in node, each screen is replaced by a recorder, and each old
    address is opened. The right screen must draw it, with the number or the query it carries, and the menu must mark the section it belongs to.
    (The screens themselves are exercised by their own tests; whether a browser follows the address and the back button is for a real browser.)"""
    script = tmp_path / "routes.js"
    script.write_text(ROUTES % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "ui": json.dumps(str(UI) + "/"),
                                "addresses": json.dumps([a for a, _, _ in ADDRESSES])}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout)
    assert {"artwork", "photo", "photo-preview", "photo-engraving", "vector", "vector-zone", "plan", "new", "colors", "works", "experiments"} <= set(out["screens"])
    for got, (address, screen, section) in zip(out["routes"], ADDRESSES):
        assert got["drawn"] == [screen] and not got["error"], (address, got)
        assert got["current"] == ([section] if section in {"/vector", "/photo-engraving", "/experiments", "/colors", "/works"} else []), (address, got)
    by_address = {r["address"]: r for r in out["routes"]}
    assert by_address["#/artwork?plan=12"]["query"] == {"plan": "12"} and by_address["#/plans/9"]["arg"] == "9"
    assert by_address["#/photo-engraving?work=7"]["query"] == {"work": "7"} and by_address["#/vector?new=1&classic=1"]["query"] == {"new": "1", "classic": "1"}
