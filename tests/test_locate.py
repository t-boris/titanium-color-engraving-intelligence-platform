"""The work found by any one of its pictures at the scale of a ruler (REQ-055, DEC-097)."""
import numpy as np
import pytest

import synth
from titanium_platform import ingest as ig, lightburn as lb, picturing


@pytest.fixture(scope="module")
def work():
    return synth.pictures_work()


@pytest.fixture(scope="module")
def layers(work):
    return lb.parse_bytes(work["lightburn"]).layers


def centre_errors_mm(work, registration):
    """Where the registration puts the centre of each picture, against where the photograph has it, in mm."""
    back = np.linalg.inv(registration.image_to_mm)
    errors = []
    for x, y, w, h in work["layout"]:
        at = np.array([x + w / 2, y + h / 2, 1.0])
        truth, mine = work["mm_to_px"] @ at, back @ at
        errors.append(float(np.linalg.norm(truth[:2] / truth[2] - mine[:2] / mine[2])) / work["px_per_mm"])
    return errors


@pytest.fixture(scope="module")
def located(work, layers):
    diagnostics = {}
    registration = picturing.locate(work["photo"], layers, work["px_per_mm"], diagnostics)
    return registration, diagnostics


def test_the_pictures_agree_on_where_the_file_lies_whichever_layer_is_on(located, work):
    registration, diagnostics = located
    assert registration is not None, diagnostics
    assert registration.method == "picture at ruler scale" and registration.details["pictures_used"] == ["C00", "C01", "C02"]
    assert max(centre_errors_mm(work, registration)) < 0.6 and registration.details["residual_mm"] <= picturing.LOCATE_MAX_RESIDUAL_MM
    assert registration.details["orientation"] == {"mirror": True, "rotation_degrees": 0} and registration.reflected
    assert registration.details["px_per_mm"] == pytest.approx(work["px_per_mm"], rel=0.02)     # the perspective of the photograph changes it across the plate


def test_the_pictures_whose_output_is_off_are_searched_too(work, layers):
    """C01 and C02 are output-off in the file: the check empties their shapes, ``placed`` keeps them for the alignment."""
    report = {"layers": [{"index": l.index, "notes": [], "compatible": True} for l in layers], "warnings": []}
    project = lb.parse_bytes(work["lightburn"])
    ig._leave_out_layers(project, None, report)
    assert [bool(l.regions) for l in project.layers] == [True, False, False] and all(l.placed for l in project.layers)
    registration = picturing.locate(work["photo"], project.layers, work["px_per_mm"])
    assert registration is not None and registration.details["pictures_used"] == ["C00", "C01", "C02"]


def test_only_the_pictures_that_are_off_are_enough(work, layers):
    registration = picturing.locate(work["photo"], [l for l in layers if l.index in (1, 2)], work["px_per_mm"])
    assert registration is not None and max(centre_errors_mm(work, registration)) < 0.6


@pytest.mark.parametrize("factor", [0.97, 1.03])
def test_a_ruler_that_reads_a_few_per_cent_off_still_finds_the_work_and_the_fit_gives_the_true_scale(work, layers, factor):
    registration = picturing.locate(work["photo"], layers, work["px_per_mm"] * factor)
    assert registration is not None and registration.details["px_per_mm"] == pytest.approx(work["px_per_mm"], rel=0.02)


@pytest.mark.parametrize("scale", [5.0, 8.5, 12.0])
def test_a_scale_that_is_not_the_photographs_finds_nothing(work, layers, scale):
    diagnostics = {}
    assert picturing.locate(work["photo"], layers, scale, diagnostics) is None and diagnostics["refused"]


def test_a_scale_at_which_a_picture_would_be_longer_than_the_photograph_is_refused_at_once(work, layers):
    diagnostics = {}
    assert picturing.locate(work["photo"], layers, 20.0, diagnostics) is None
    assert diagnostics["refused"] == "a picture of the file would be longer than the photograph at this scale"


def test_a_lone_picture_that_looks_the_same_turned_is_not_believed(work, layers):
    """The ring seal is C00: concentric rings match in every orientation, so one of them alone cannot say which way the work lies."""
    diagnostics = {}
    assert picturing.locate(work["photo"], [l for l in layers if l.index == 0], work["px_per_mm"], diagnostics) is None
    assert diagnostics["refused"]


def test_the_side_of_the_angle_narrows_the_search_and_a_wrong_side_falls_back_to_the_whole_photograph(work, layers):
    right = {"corner_px": list(work["corner_px"]), "quadrant": [1, -1]}
    diagnostics = {}
    assert picturing.locate(work["photo"], layers, work["px_per_mm"], diagnostics, right) is not None
    assert diagnostics["searched"] == "beside the measuring angle"
    diagnostics = {}
    wrong = {"corner_px": [1800, 400], "quadrant": [1, -1]}                  # the plate would lie up and right of a point in its upper right
    assert picturing.locate(work["photo"], layers, work["px_per_mm"], diagnostics, wrong) is not None
    assert diagnostics["searched"] == "the whole photograph"


def test_a_file_without_a_picture_has_nothing_to_look_for(work):
    xml = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="900"/>'
           b'<frequency Value="48000"/></CutSetting><Shape Type="Rect" CutIndex="0" W="20" H="20"><XForm>1 0 0 1 50 50</XForm></Shape></LightBurnProject>')
    diagnostics = {}
    assert picturing.locate(work["photo"], lb.parse_bytes(xml).layers, 10.0, diagnostics) is None
    assert diagnostics["refused"] == "the file holds no picture to look for"
