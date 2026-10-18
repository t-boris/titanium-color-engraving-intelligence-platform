"""The predicted look of a photo engraving through the application (REQ-030, DEC-062): a synthetic photo engraving goes through
ingest and acceptance, then its LightBurn file is uploaded for a prediction, re-rendered at other Min and Max without a new upload,
and the cases that cannot be predicted are refused with the reason."""
import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import synth
from titanium_platform import color, devices, ingest as ig, prediction as pr, prediction_store as ps, setup as su
from titanium_platform.api.app import create_app
from titanium_platform.api.routes_prediction import PreviewCache


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    work = synth.picture_work()
    app = create_app(tmp_path_factory.mktemp("prediction"))
    store = app.state.store
    store.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    titanium = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    other = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0, surface="brushed")
    pid = ig.create_pair(store, device_id=laser["id"], lens_id=None, lightburn_name="portrait.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name="portrait.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                         context={"material_id": titanium["id"]})
    assert ig.check_pair(store, pid)["alignment"]["valid"]
    ig.review_masks(store, pid)
    ig.accept_pair(store, pid)
    with TestClient(app) as client:
        yield {"work": work, "store": store, "client": client, "laser": laser, "titanium": titanium, "other": other, "pair": pid}
    store.close()


def upload(world, data=None, name="portrait.lbrn2", material=None, **overrides):
    fields = {"device_id": world["laser"]["id"], "lens_id": "unknown", "material_id": (material or world["titanium"])["id"], **overrides}
    return world["client"].post("/api/predictions/photo", data=fields,
                                files={"lightburn": (name, world["work"]["lightburn"] if data is None else data, "application/xml")})


def lightburn(picture_png: bytes | None, mode: str) -> bytes:
    data = f' Data="{base64.b64encode(picture_png).decode()}"' if picture_png else ""
    return (f'<LightBurnProject AppVersion="1.7.01"><CutSetting_Img type="Image"><index Value="0"/><name Value="C00"/><minPower Value="5"/>'
            f'<maxPower Value="16"/><speed Value="128"/><frequency Value="60000"/><QPulseWidth Value="300"/><interval Value="0.0169"/>'
            f'<ditherMode Value="{mode}"/></CutSetting_Img><Shape Type="Bitmap" CutIndex="0" W="40" H="30" File="/x/p.png"{data}>'
            f'<XForm>1 0 0 1 30 20</XForm></Shape></LightBurnProject>').encode()


def test_the_accepted_photo_engraving_rendered_at_its_own_mode_reproduces_its_measured_bins(world):
    """REQ-030 AC7, second half: the picture through the curve of its own mode, binned by grey as the tonal profile bins the
    photograph, gives back every measured bin within 1 delta E."""
    store = world["store"]
    bins = ig.get_pair(store, world["pair"])["check"]["layers"][0]["tonal"]["bins"]
    (item,) = ps.prepare(store, world["work"]["lightburn"], world["laser"]["id"], None, world["titanium"]["id"])
    rendered = pr.render(item["picture"], 5.0, 16.0, item["curve"], item["adjustments"])
    which = np.clip(np.digitize(item["picture"], np.linspace(0, 1, ig.TONAL_BINS + 1)) - 1, 0, ig.TONAL_BINS - 1)
    errors = []
    for step in bins:
        selected = (which == int(step["gray"] * ig.TONAL_BINS)) & rendered["covered"]
        if selected.sum() >= 50:
            errors.append(color.delta_e(np.median(rendered["lab"][selected], axis=0), [step["L"], step["a"], step["b"]]))
    assert len(errors) >= len(bins) - 2 >= 12 and max(errors) < 1.0
    assert rendered["outside_share"] < 0.01                 # only the extreme greys lie beyond the outermost measured bins


def test_an_upload_returns_every_point_of_the_curve_with_where_it_was_measured(world):
    response = upload(world)
    assert response.status_code == 200
    body = response.json()
    (layer,) = body["layers"]
    assert body["cache_id"] and layer["refused"] is None and layer["dither"] == "grayscale"
    assert layer["settings"]["min_power"] == 5.0 and layer["settings"]["max_power"] == 16.0 and layer["settings"]["overridden"] == []
    assert layer["mode"] == {"device_id": world["laser"]["id"], "lens_id": None, "material_id": world["titanium"]["id"], "speed": 128.0,
                             "frequency": 60.0, "pulse_width": 300.0, "line_interval": 0.0169, "passes": 1, "global_passes": 1}
    points = layer["curve"]["points"]
    assert len(points) >= 14 and [p["power"] for p in points] == sorted(p["power"] for p in points)
    for p in points:
        (source,) = p["sources"]
        assert source["pair_id"] == world["pair"] and source["how"] == "tonal profile" and source["reference"] == "as photographed"
        assert p["grey"] == pytest.approx(source["gray"], abs=0.002)      # at its own Min and Max a point sits at its own grey
    assert layer["referenced"] is False and layer["reference"] == "as photographed"
    assert any(n.startswith("Camera-relative colours: they are as that camera saw them") for n in layer["notes"])
    assert layer["preview"] == f"/api/predictions/photo/{body['cache_id']}/0.png"


def test_changing_min_and_max_re_renders_from_the_kept_upload_without_a_new_upload(world):
    store, client = world["store"], world["client"]
    rows = {table: store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in ("pair", "observation", "audit")}
    body = upload(world).json()
    preview = body["layers"][0]["preview"]
    own, wide = client.get(preview), client.get(preview, params={"min_power": 2, "max_power": 18})
    assert own.status_code == wide.status_code == 200 and own.headers["content-type"] == "image/png"
    a, b = (cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR) for r in (own, wide))
    side = (a.shape[1] - pr.GAP) // 2
    assert a.shape == b.shape == (256, 2 * 256 + pr.GAP, 3) and side == 256
    assert np.array_equal(a[:, :side], b[:, :side]) and not np.array_equal(a[:, -side:], b[:, -side:])   # same picture, other prediction
    info = client.get(preview[:-len(".png")], params={"min_power": 2, "max_power": 18}).json()
    assert info["power_range"] == [2.0, 18.0] and info["outside_share"] > 0.1 > body["layers"][0]["outside_share"]
    assert any("of the picture needs a power outside the measured span" in n for n in info["notes"])
    assert {table: store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in rows} == rows     # nothing stored


def test_min_above_max_is_refused_with_the_reason(world):
    preview = upload(world).json()["layers"][0]["preview"]
    response = world["client"].get(preview, params={"min_power": 12, "max_power": 8})
    assert response.status_code == 422 and "with Min not above Max" in response.json()["error"]


def test_a_preview_no_longer_kept_says_so_instead_of_drawing_anything(world):
    response = world["client"].get("/api/predictions/photo/0123456789abcdef/0.png")
    assert response.status_code == 404 and response.json()["error"] == "the preview is no longer kept: upload the LightBurn file again"


def test_a_dithered_layer_is_refused_with_its_reason(world):
    body = upload(world, lightburn(world["work"]["png"], "stucki"), name="dithered.lbrn2").json()
    (layer,) = body["layers"]
    assert body["cache_id"] is None and layer["dither"] == "stucki"
    assert layer["refused"].startswith("stucki mode is not predicted: it is a dithered mode")


def test_a_file_without_a_picture_is_refused(world):
    (layer,) = upload(world, lightburn(None, "grayscale"), name="empty.lbrn2").json()["layers"]
    assert layer["refused"] == "the layer has no picture: there is nothing to predict"
    scan = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="900"/>'
            b'<frequency Value="48000"/></CutSetting></LightBurnProject>')
    response = upload(world, scan, name="fills.lbrn2")
    assert response.status_code == 422 and response.json()["error"] == "the file has no image layer: there is no picture to predict"
    assert upload(world, b"not xml", name="broken.lbrn2").json()["error"].startswith("LightBurn file: not a LightBurn project")


def test_a_mode_or_titanium_nothing_was_measured_at_is_refused_and_says_so(world):
    (faster,) = upload(world, speed=500).json()["layers"]
    assert faster["refused"] == "no colour has been measured at this mode: there is nothing to predict from"
    assert faster["settings"]["speed"] == 500.0 and faster["settings"]["overridden"] == ["speed"]
    (other,) = upload(world, material=world["other"]).json()["layers"]
    assert other["refused"] == "no colour has been measured at this mode: there is nothing to predict from"


def test_the_share_outside_the_span_is_that_of_the_whole_picture_not_of_the_scaled_down_preview(world):
    """A 1600 px picture is shown at 800 px; thin black lines (too dark for the measured span) average away in the preview."""
    picture = np.full((1600, 1600), 128, np.uint8)
    picture[:, ::10] = 0                                                   # one column in ten: 10 % of the picture
    (layer,) = upload(world, lightburn(cv2.imencode(".png", picture)[1].tobytes(), "grayscale"), name="lines.lbrn2").json()["layers"]
    assert layer["picture"] == {"width": 1600, "height": 1600, "shown_width": 800, "shown_height": 800}
    assert layer["outside_share"] == pytest.approx(0.1)


def test_overridden_min_and_max_are_the_starting_point_of_the_preview(world):
    (layer,) = upload(world, min_power=7, max_power=12).json()["layers"]
    assert layer["power_range"] == [7.0, 12.0] and layer["settings"]["overridden"] == ["max_power", "min_power"]


def test_the_kept_uploads_are_bounded_by_number_size_and_age():
    picture = {"picture": np.zeros((10, 10), np.float32)}
    cache = PreviewCache(uploads=2, size=10 ** 6, seconds=60)
    first, second = cache.put({0: picture}), cache.put({0: picture})
    cache.get(first)                                       # used again: now the most recent
    third = cache.put({0: picture})
    assert len(cache) == 2 and cache.get(first) and cache.get(third)
    with pytest.raises(KeyError):
        cache.get(second)
    small = PreviewCache(uploads=5, size=500, seconds=60)  # 400 bytes each: a second upload pushes the first out
    one, two = small.put({0: picture}), small.put({0: picture})
    assert len(small) == 1 and small.get(two)
    with pytest.raises(KeyError):
        small.get(one)
    old = PreviewCache(uploads=5, size=10 ** 6, seconds=0)
    key = old.put({0: picture})
    with pytest.raises(KeyError):
        old.get(key)


def test_the_app_serves_the_photo_preview_screen(world):
    client = world["client"]
    assert "photo-preview.js" in client.get("/").text and client.get("/screens/photo-preview.js").status_code == 200
