"""How a photo engraving is judged and what is concluded (feature photo-engraving-quality, DEC-001, REQ-003): the tone of a tonal profile,
the detail of a photograph against its picture, the findings with the settings that move them, on profiles shaped as the workshop's own."""
import cv2
import numpy as np
import pytest

from titanium_platform import photo_quality as pq


def profile(lightness, chroma=None, measured_by="grey ramp"):
    """A tonal profile with ``lightness`` from black (grey 0) to white (grey 1)."""
    greys = np.linspace(0, 1, len(lightness))
    chroma = chroma if chroma is not None else [0.0] * len(lightness)
    return {"measured_by": measured_by, "evidence": "clear", "rho": 0.9,
            "bins": [{"gray": round(float(g), 3), "L": float(l), "a": float(c), "b": 0.0, "n": 100} for g, l, c in zip(greys, lightness, chroma)]}


def codes(found):
    return [f["code"] for f in found]


def test_a_long_ordered_scale_tells_every_step_apart_and_needs_nothing():
    tone = pq.tone(profile(np.linspace(30, 80, 16)))
    assert tone["levels"] == 16 and tone["levels_share"] == 1.0 and tone["range_L"] == 50.0 and tone["reversals"] == []
    assert tone["shadows_blocked"] == 0 and tone["highlights_lost"] == 0 and tone["mid_darkness"] == pytest.approx(0.5, abs=0.02)
    assert tone["mean_L"] == pytest.approx(55, abs=0.1)
    assert codes(pq.findings(tone, None, "jarvis")) == ["good"]


def test_blocked_shadows_and_dark_midtones_point_at_less_power_and_the_dot_width_in_a_dot_kind():
    """Pair 118 (Jarvis 25 %, 0.01 mm): everything below grey 0.31 came out as black."""
    lightness = [30] * 6 + list(np.linspace(32, 78, 10))
    tone = pq.tone(profile(lightness))
    assert tone["shadows_blocked"] >= 0.3
    found = {f["code"]: f for f in pq.findings(tone, None, "jarvis")}
    assert "shadows_blocked" in found and found["shadows_blocked"]["value"] == tone["shadows_to"]
    assert [m["setting"] for m in found["shadows_blocked"]["moves"]] == ["power", "dot_width", "line_interval"]
    assert found["shadows_blocked"]["moves"][0]["direction"] == "down" and found["shadows_blocked"]["basis"] == "prior"
    grey = {f["code"]: f for f in pq.findings(tone, None, "grayscale")}
    assert [m["setting"] for m in grey["shadows_blocked"]["moves"]] == ["power"]                # grayscale: Max down


def test_a_scale_that_barely_marks_is_flat_and_reversed_and_asks_for_more_power():
    """Pairs 112 and 114: the dots barely marked; the lightness wanders by a few L* and turns back."""
    tone = pq.tone(profile([70, 74, 69, 73, 68, 72, 70, 74, 71, 73, 72, 75, 73, 74, 72, 74]))
    found = {f["code"]: f for f in pq.findings(tone, None, "atkinson")}
    assert {"flat", "reversed"} <= set(found)
    assert found["flat"]["moves"][0] == {"setting": "power", "direction": "up"}
    assert pq.score(tone) < 0.5


def test_lost_highlights_in_grayscale_ask_for_a_lower_min():
    tone = pq.tone(profile(list(np.linspace(30, 70, 11)) + [70] * 5))
    found = {f["code"]: f for f in pq.findings(tone, None, "grayscale")}
    assert found["highlights_lost"]["moves"] == [{"setting": "min_power", "direction": "down"}]


def test_detail_is_the_share_of_the_pictures_contrast_the_photograph_keeps_and_grain_what_it_adds():
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:400, 0:400]
    expected = (50 + 20 * np.sin(xx / 3.0) * np.cos(yy / 5.0)).astype(np.float32)          # features about 0.2–0.5 mm at 20 px/mm
    inside = np.ones(expected.shape, bool)
    sharp = pq.detail(expected.copy(), expected, inside, 20.0)
    assert sharp["kept"] == pytest.approx(1.0, abs=0.02) and sharp["grain_L"] < 0.1
    blurred = pq.detail(cv2.GaussianBlur(expected, (0, 0), 3), expected, inside, 20.0)
    assert blurred["kept"] < 0.6
    blotches = cv2.GaussianBlur(rng.normal(0, 1, expected.shape).astype(np.float32), (0, 0), 4)    # about 0.4 mm across
    grainy = pq.detail(expected + blotches * (6 / blotches.std()), expected, inside, 20.0)
    assert grainy["kept"] == pytest.approx(1.0, abs=0.1) and grainy["grain_L"] >= pq.GRAIN_L
    fine = pq.detail(expected + rng.normal(0, 4, expected.shape).astype(np.float32), expected, inside, 20.0)
    assert fine["grain_L"] < 0.5                           # pixel noise far finer than 0.4 mm is not grain a viewer sees
    assert "grainy" in {f["code"] for f in pq.findings(pq.tone(profile(np.linspace(30, 80, 16))), grainy, "jarvis")}
    found = {f["code"] for f in pq.findings(pq.tone(profile(np.linspace(30, 80, 16))), blurred, "jarvis")}
    assert "detail_lost" in found
    assert pq.detail(expected, expected, np.zeros(expected.shape, bool), 20.0) is None           # nothing inside: not measured


def test_the_copies_of_a_plate_are_ranked_and_each_change_says_what_it_did():
    centre = profile([30] * 5 + list(np.linspace(32, 78, 11)))               # blocked shadows
    lighter = profile(list(np.linspace(38, 80, 16)))                           # power down: lighter, every step told apart
    darker = profile([25] * 8 + list(np.linspace(27, 70, 8)))                  # power up: darker, more blocked
    copies = [{"copy": 1, "variant": {"dither": "jarvis", "power": 25.0, "speed": 125.0}, "ramp": centre, "picture": None, "detail": None},
              {"copy": 2, "variant": {"dither": "jarvis", "power": 20.0, "speed": 125.0}, "ramp": lighter, "picture": None, "detail": None},
              {"copy": 3, "variant": {"dither": "jarvis", "power": 30.0, "speed": 125.0}, "ramp": darker, "picture": None, "detail": None}]
    found = pq.compare(copies)
    assert [c["copy"] for c in found["ranked"]] == [2, 1, 3] and found["best"] == 2
    effect = {e["copy"]: e for e in found["effects"]}
    assert effect[2]["changed"] == [{"setting": "power", "from": 25.0, "to": 20.0}]
    assert effect[2]["mean_L"] > 0 and effect[3]["mean_L"] < 0                                 # lighter, darker
    assert effect[3]["shadows_blocked"] > 0 and effect[2]["shadows_blocked"] < 0
    assert found["next"] == {"centre": copies[1]["variant"], "step": 0.5}                    # around the best, half the change


def test_the_search_settles_when_the_centre_stays_the_best_at_small_changes():
    good, worse = profile(np.linspace(30, 80, 16)), profile([30] * 6 + list(np.linspace(32, 78, 10)))
    copies = [{"copy": 1, "variant": {"dither": "jarvis", "power": 25.0}, "ramp": good},
              {"copy": 2, "variant": {"dither": "jarvis", "power": 26.5}, "ramp": worse}]
    assert pq.compare(copies, 1.0)["next"] == {"centre": copies[0]["variant"], "step": 0.5} and not pq.compare(copies, 1.0)["settled"]
    settled = pq.compare(copies, 0.25)
    assert settled["settled"] and settled["next"] is None


def test_a_grayscale_ramp_whose_colour_turns_back_gives_the_span_that_keeps_its_tones_in_order():
    """Past some power the oxide turns lighter again (the workshop's grey-scale plates 108 and 113): the span stops before the turn."""
    lightness = [62, 55, 48, 41] + list(np.linspace(36, 80, 12))           # grey 0..0.2 (the strongest powers) turn back lighter
    tonal = profile(lightness)
    for b in tonal["bins"]:
        b["power_pct"] = round(30 * (1 - b["gray"]), 2)                      # Min 0 %, Max 30 %
    assert pq.tone(tonal)["reversals"]
    span = pq.ordered_span(tonal)
    assert span["min_power"] == 0.0 and span["max_power"] == pytest.approx(30 * (1 - 4 / 15), abs=0.02)   # up to the turn, not past it
    assert span["tone"]["reversals"] == [] and span["tone"]["levels"] == 12
    assert pq.ordered_span(profile(np.linspace(30, 80, 16))) is None         # no powers, nothing to cut
