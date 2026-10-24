"""The brightness, contrast and gamma of a photo work's picture (0.27.0): its greys are toned before they become power or dots, so the
look, the close-up and the LightBurn file carry the same greys and LightBurn's own adjustments stay at their defaults. A dot kind always
takes the tone; grayscale takes it while the picture's own greys are engraved, and keeps it, unused, while the greys are chosen for the
picture's colours. The tone is one change of the work: it is undone and redone. The picture is a horizontal ramp from white to black."""
import cv2
import numpy as np
import pytest

from test_grey_scales import app_world, picture_png  # noqa: F401  (the measured grey-ramp plate, four scales)
from test_photo_work_dot_colours import create, refused, settings
from titanium_platform import lightburn, photo_state as st, prediction, prediction_store as ps

AS_IT_IS = {"brightness": 0.0, "contrast": 0.0, "gamma": 1.0}


def filed(client, work) -> np.ndarray:
    """The greys of the work's Image layer as its LightBurn file carries them (0..255)."""
    answer = client.get(f"/api/photo-works/{work['id']}/export.lbrn2")
    assert answer.status_code == 200, answer.text
    layer = lightburn.parse_bytes(answer.content).layer(1)
    attributes = layer.source_settings.get("bitmaps") or [{}]
    assert all(float(a.get(tag, default)) == default for a in attributes for tag, default in lightburn.BITMAP_DEFAULTS.items())   # LightBurn adds nothing
    grey = cv2.imdecode(np.frombuffer(layer.regions[0].bitmap["png"], np.uint8), cv2.IMREAD_GRAYSCALE)
    return grey.astype(float)


def test_a_picture_is_toned_once_from_its_own_greys_and_left_as_it_is_without_a_tone():
    upload = ps.decode_upload(picture_png())
    state = {**st.DEFAULTS, "kind": "jarvis", "by_colour": True, "min_power": 2.0, "max_power": 40.0}
    assert st.toned(upload, state) is upload and st.tone_used(state) is None
    lighter = {**state, "tone": {**AS_IT_IS, "brightness": 20.0}}
    toned = st.toned(upload, lighter)
    assert toned["picture"] == pytest.approx(np.clip(upload["picture"] + 0.2, 0, 1), abs=1e-6)
    assert toned["grey_full"] == pytest.approx(np.clip(upload["grey_full"] + 0.2, 0, 1), abs=1e-6)
    assert toned["alpha"] is upload["alpha"] and toned["bgr_full"] is upload["bgr_full"]                # only the greys change
    assert st.toned(toned, lighter) is toned and st.toned(upload, lighter) is toned                     # never toned twice, kept
    assert st.toned(toned, state) is upload                                                             # back to the picture itself
    darker = st.toned(toned, {**state, "tone": {**AS_IT_IS, "gamma": 2.0}})
    assert darker["grey_full"] == pytest.approx(upload["grey_full"] ** 2, abs=1e-6)                     # from the picture, not from the toned one
    by_colour = {**lighter, "kind": st.GRAYSCALE}
    assert st.tone_used(by_colour) is None and st.toned(upload, by_colour) is upload                    # greys chosen for the colours: no tone
    assert st.tone_used({**by_colour, "by_colour": False}) == {**AS_IT_IS, "brightness": 20.0}
    assert st.tone_of({"kind": "jarvis"}) == AS_IT_IS                                                   # a state made before the tone


def test_the_tone_lightens_or_darkens_the_dots_in_the_look_and_in_the_file_alike(app_world):  # noqa: F811
    client = app_world["client"]
    work = settings(client, create(client), kind="jarvis")
    assert (work["tone"], work["tone_used"]) == (AS_IT_IS, False)
    plain = filed(client, work)
    lighter = settings(client, work, tone={"brightness": 20})
    assert (lighter["tone"], lighter["tone_used"]) == ({**AS_IT_IS, "brightness": 20.0}, True)
    assert lighter["picture"]["preview"] != work["picture"]["preview"] and lighter["picture"]["closeup"] != work["picture"]["closeup"]
    assert lighter["picture"]["dots"]["struck_share"] < work["picture"]["dots"]["struck_share"]        # lighter: fewer dots
    mid = (plain > 5) & (plain < 190)
    assert mid.mean() > 0.5 and np.abs(filed(client, work)[mid] - (plain[mid] + 51)).max() <= 1
    darker = settings(client, work, tone={"brightness": 0, "gamma": 2})
    assert darker["picture"]["dots"]["struck_share"] > work["picture"]["dots"]["struck_share"]         # darker: more dots
    assert np.abs(filed(client, work) - np.round((plain / 255) ** 2 * 255)).max() <= 1
    spread = settings(client, work, tone={"gamma": 1, "contrast": 50})
    expected = np.round(prediction.adjust_grey(plain / 255, 1.0, 50.0, 0.0) * 255)
    assert spread["tone"] == {**AS_IT_IS, "contrast": 50.0} and np.abs(filed(client, work) - expected).max() <= 1
    tiles = lambda: {k["key"]: k["picture"] for k in client.get(f"/api/photo-works/{work['id']}/kinds").json()["kinds"]}   # noqa: E731
    spread_tiles = tiles()
    settings(client, work, tone={"contrast": 0})
    assert all(tiles()[key] != spread_tiles[key] for key in ("atkinson", "grayscale"))                 # the tiles show the tone too
    undone = client.post(f"/api/photo-works/{work['id']}/undo").json()
    assert undone["tone"] == {**AS_IT_IS, "contrast": 50.0}
    for _ in range(3):
        undone = client.post(f"/api/photo-works/{work['id']}/undo").json()
    assert undone["tone"] == AS_IT_IS and undone["picture"]["preview"] == work["picture"]["preview"]
    assert np.array_equal(filed(client, work), plain)


def test_grayscale_takes_the_tone_while_its_own_greys_are_engraved_and_keeps_it_while_they_are_chosen_for_colours(app_world):  # noqa: F811
    client = app_world["client"]
    work = create(client)
    assert (work["kind"], work["by_colour"]) == ("grayscale", False)
    plain = filed(client, work)
    lighter = settings(client, work, tone={"brightness": 20})
    mid = (plain > 5) & (plain < 190)
    assert lighter["tone_used"] and lighter["picture"]["preview"] != work["picture"]["preview"]
    assert np.abs(filed(client, work)[mid] - (plain[mid] + 51)).max() <= 1
    chosen = settings(client, work, tone={"brightness": 0}, by_colour=True)
    by_colour = filed(client, work)
    kept = settings(client, work, tone={"brightness": 20})
    assert kept["tone"]["brightness"] == 20.0 and not kept["tone_used"]                                 # kept, waiting
    assert kept["picture"]["preview"] == chosen["picture"]["preview"] and np.array_equal(filed(client, work), by_colour)


def test_a_tone_out_of_its_range_is_refused_and_changes_nothing(app_world):  # noqa: F811
    client = app_world["client"]
    work = settings(client, create(client), kind="jarvis", tone={"brightness": -10})
    for tone, message in (({"gamma": 0}, "the picture's gamma must be a number from 0.2 to 5"),
                          ({"brightness": 101}, "the picture's brightness must be a number from -100 to 100"),
                          ({"contrast": "more"}, "the picture's contrast must be a number from -100 to 100"),
                          ({"contrast": True}, "the picture's contrast must be a number from -100 to 100"),
                          ({"hue": 5}, "the tone of the picture is its brightness, contrast and gamma"),
                          ({}, "the tone of the picture is its brightness, contrast and gamma"),
                          (5, "the tone of the picture is its brightness, contrast and gamma")):
        assert refused(client, work, tone=tone) == message, tone
    assert client.get(f"/api/photo-works/{work['id']}").json()["tone"] == {**AS_IT_IS, "brightness": -10.0}
    assert settings(client, work, tone={"gamma": 0.456})["tone"] == {**AS_IT_IS, "brightness": -10.0, "gamma": 0.46}
