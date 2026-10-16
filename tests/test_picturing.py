"""A photo engraving is registered to the picture stored in its file (REQ-027, DEC-054)."""
import cv2
import numpy as np
import pytest

import synth
from titanium_platform import color, ingest as ig, lightburn as lb, picturing, profiles as pf
from titanium_platform.db import Store


@pytest.fixture(scope="module")
def work():
    return synth.picture_work()


@pytest.fixture(scope="module")
def registered(work):
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    diagnostics = {}
    return layers, picturing.register(work["photo"], layers, diagnostics), diagnostics


def test_the_picture_is_found_on_the_photograph_mirrored_turned_and_in_perspective(work, registered):
    _, result, diagnostics = registered
    assert result is not None, diagnostics
    assert result.method == "picture" and result.reflected
    # the file's own millimetres of every photo point must come out as the true ones, to a millimetre
    grid = np.array([(x, y) for x in range(25, 146, 15) for y in range(25, 146, 15)], np.float32)
    px = cv2.perspectiveTransform(grid[None], work["mm_to_px"])[0]
    back = cv2.perspectiveTransform(px[None], result.image_to_mm.astype(np.float32))[0]
    assert np.linalg.norm(back - grid, axis=1).max() < 1.0


def test_the_orientation_beats_every_other_with_a_clear_margin(registered):
    _, result, _ = registered
    d = result.details
    assert d["orientation"]["mirror"] is True and d["zncc"] > picturing.MIN_MARGIN * d["second_orientation_zncc"]


def test_the_picture_is_not_skewed_in_perspective_beyond_what_the_camera_gives(work, registered):
    """A homography fitted where the edge of the picture is outside the photograph used to run off (right side 11% taller)."""
    _, result, _ = registered
    q = np.array(result.details["picture_quad_px"])
    side = lambda i, j: float(np.linalg.norm(q[i] - q[j]))
    assert abs(side(0, 1) - side(3, 2)) / side(0, 1) < 0.05 and abs(side(0, 3) - side(1, 2)) / side(0, 3) < 0.05
    truth = cv2.perspectiveTransform(np.float32([[(0, 0), (256, 0), (256, 256), (0, 256)]]), work["picture_to_px"])[0]
    assert min(np.linalg.norm(q - np.roll(truth[::-1], k, axis=0), axis=1).max() for k in range(4)) < 12 or \
        min(np.linalg.norm(q - np.roll(truth, k, axis=0), axis=1).max() for k in range(4)) < 12


def test_the_margins_hidden_by_the_frame_are_found_from_the_step_at_its_inner_edge(work, registered):
    _, result, _ = registered
    assert result.details["window_found"]
    # the file is a vertical mirror of the photograph: top and bottom of the picture swap their places in the margins asked for
    hidden = result.details["hidden_mm"]
    left, right, top, bottom = work["margins_mm"]
    assert hidden["left"] == pytest.approx(left, abs=1.5) and hidden["right"] == pytest.approx(right, abs=1.5)
    assert hidden["top"] == pytest.approx(top, abs=1.5) and hidden["bottom"] == pytest.approx(bottom, abs=1.5)


def test_the_window_polygon_lies_inside_the_picture_and_outside_the_frame_lip(work, registered):
    _, result, _ = registered
    window = np.array(result.details["window_px"], np.float32)
    truth_area = abs(cv2.contourArea(cv2.perspectiveTransform(np.float32([[(0, 0), (256, 0), (256, 256), (0, 256)]]), work["picture_to_px"])[0]))
    area = abs(cv2.contourArea(window))
    left, right, top, bottom = work["margins_mm"]
    expected = (150 - left - right) * (150 - top - bottom) / 150 ** 2
    assert area / truth_area == pytest.approx(expected, rel=0.12)


def test_a_file_without_a_picture_is_refused_with_a_reason(work):
    layers = [lb.parse_bytes(synth.framed_work(blobs=8)["lightburn"]).layers[1]]
    diagnostics = {}
    assert picturing.register(work["photo"], layers, diagnostics) is None
    assert "no picture" in diagnostics["refused"]


def test_a_photograph_of_something_else_is_refused(work):
    layers = [layer for layer in lb.parse_bytes(work["lightburn"]).layers if layer.regions]
    other = synth.framed_work(seed=9)["photo"]
    diagnostics = {}
    assert picturing.register(other, layers, diagnostics) is None
    assert "closely enough" in diagnostics["refused"] or "ambiguous" in diagnostics["refused"]


def test_a_radially_symmetric_picture_cannot_be_oriented_and_is_refused():
    n = 256
    yy, xx = np.mgrid[0:n, 0:n]
    rings = (0.5 + 0.5 * np.cos(np.hypot(xx - n / 2, yy - n / 2) / 7.0)).astype(np.float32)
    import base64
    data = base64.b64encode(cv2.imencode(".png", (rings * 255).astype(np.uint8))[1].tobytes()).decode()
    xml = ('<LightBurnProject><CutSetting_Img type="Image"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="100"/>'
           '<frequency Value="60000"/><ditherMode Value="grayscale"/></CutSetting_Img><Shape Type="Bitmap" CutIndex="0" W="150" H="150" '
           f'File="/x/r.png" Data="{data}"><XForm>1 0 0 1 85 85</XForm></Shape></LightBurnProject>').encode()
    # a photograph of exactly this picture, so that only the orientation is in question
    base = synth.picture_work()
    colour = cv2.cvtColor(np.dstack([8 + 30 * rings, 1.5 - 3 * rings, 7 * rings]).astype(np.float32), cv2.COLOR_Lab2RGB)
    plate = cv2.warpPerspective(cv2.cvtColor(colour, cv2.COLOR_RGB2BGR), base["picture_to_px"], base["photo"].shape[1::-1])
    photo = base["photo"].copy()
    mask = cv2.warpPerspective(np.full((n, n), 255, np.uint8), base["picture_to_px"], base["photo"].shape[1::-1]) > 127
    photo[mask] = (plate[mask] * 255).astype(np.uint8)
    layers = [layer for layer in lb.parse_bytes(xml).layers if layer.regions]
    diagnostics = {}
    assert picturing.register(photo, layers, diagnostics) is None
    assert "ambiguous" in diagnostics["refused"]


# -- through the pair check -------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def checked(tmp_path_factory, work):
    store = Store(tmp_path_factory.mktemp("picture"))
    store.set_setting("allow_non_raw_photos", True)
    profile = pf.create_profile(store, "MOPA", 200, 0.025, 1)
    material = pf.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")
    pid = ig.create_pair(store, profile_id=profile["id"], lightburn_name="portrait.lbrn2", lightburn_bytes=work["lightburn"],
                         photo_name="portrait.png", photo_bytes=cv2.imencode(".png", work["photo"])[1].tobytes(),
                         context={"material_id": material["id"]})
    yield store, pid, ig.check_pair(store, pid)
    store.close()


def test_the_pair_check_aligns_by_the_picture_and_reports_what_the_frame_hides(checked):
    _, _, report = checked
    a = report["alignment"]
    assert a["valid"] and a["method"] == "picture" and not report["problems"]
    assert set(a["hidden_mm"]) == {"left", "right", "top", "bottom"} and len(a["window_px"]) == 4
    assert any("The picture of the file was matched" in w for w in report["warnings"])


def test_the_tonal_profile_follows_grey_to_power_to_colour(checked):
    _, _, report = checked
    t = report["layers"][0]["tonal"]
    assert t["rho"] > 0.8 and t["rho_b"] > 0.6 and t["rho_a"] < -0.5 and t["evidence"] == "clear" and t["vertical_flip"] is False
    assert t["power_range"] == [5.0, 16.0]
    powers = [b["power_pct"] for b in t["bins"]]
    assert powers == sorted(powers, reverse=True)                 # lighter grey = less power
    assert t["bins"][-1]["L"] > t["bins"][0]["L"] + 10 and t["bins"][-1]["b"] > t["bins"][0]["b"] + 2


def test_the_frame_is_not_part_of_the_measured_colour(checked, work):
    _, _, report = checked
    lab = report["layers"][0]["measured_lab"]
    lip = color.srgb8_to_lab(np.array([168.0, 170.0, 175.0]))
    assert lab is not None and lab[0] < 40 and color.delta_e(lab, lip) > 30       # an engraved tone (L* 8..38 here), not the bright lip (L* about 70)


def test_the_overview_shows_where_the_silhouettes_of_the_picture_were_found(checked):
    store, pid, _ = checked
    png = ig.overlay_png(store, pid, corrected=False)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    green = (img[..., 1] > 240) & (img[..., 0] < 20) & (img[..., 2] < 20)
    cyan = (img[..., 0] > 240) & (img[..., 1] > 240) & (img[..., 2] < 20)
    assert green.sum() > 800 and cyan.sum() > 200          # silhouettes of the picture, and the outline of the visible window
