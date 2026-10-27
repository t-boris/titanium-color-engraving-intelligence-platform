"""A configured Max is not the power reached by colour-matched pixels (Inna & Emmy / Luna 1, 2026-10-27)."""
import numpy as np
import pytest

from titanium_platform import drawing, prediction as pr, prediction_store as ps


def ramp_curve():
    # The dark branch ends near 13%; the second colour cycle brightens again. Drawing deliberately uses only the first branch.
    return pr.curve([pr.Point(p, (l, 10, 20), {"kind": "pair", "pair_id": 140, "id": 140, "how": "grey ramp"}, True)
                     for p, l in ((1, 80), (7, 53), (13, 38), (20, 72), (30, 45))])


def test_used_powers_reveal_when_colour_matching_never_reaches_the_configured_max():
    curve = ramp_curve()
    light = np.tile(np.linspace(20, 90, 256), (10, 1))
    lab = np.dstack([light, np.zeros_like(light), np.zeros_like(light)])
    alpha = np.ones_like(light)
    chosen = drawing.choose(lab, alpha > 0, curve, 1, 30, 10)
    item = {"picture": chosen["grey8"].astype(np.float32) / 255, "alpha": alpha, "adjustments": {}}
    usage = ps.power_usage(item, 1, 30)
    assert usage["range"][0] == 1 and 12.5 < usage["range"][1] < 14
    assert sum(b["share"] for b in usage["histogram"] if b["from"] >= 15) == 0
    assert sum(b["share"] for b in usage["histogram"]) == pytest.approx(1, abs=0.001)
    assert ps.prediction_evidence(curve) == {"ramp_only": True, "engravings": 1}


def test_usage_excludes_unengraved_pixels_and_reflects_adjustments():
    item = {"picture": np.array([[0, 1, .5]], np.float32), "alpha": np.array([[0, 1, 1]], np.float32),
            "adjustments": {"Brightness": -20}}
    usage = ps.power_usage(item, 1, 30)
    # A transparent black pixel must not claim that the laser uses Max.
    assert usage["range"] == pytest.approx([6.8, 21.24], abs=0.02)
    assert usage["range"][1] < 30


def test_observed_photo_profile_is_distinguished_from_a_test_ramp():
    curve = pr.curve([pr.Point(10, (50, 20, 30), {"kind": "pair", "id": 151, "how": "tonal profile"}, True)])
    assert ps.prediction_evidence(curve) == {"ramp_only": False, "engravings": 1}
