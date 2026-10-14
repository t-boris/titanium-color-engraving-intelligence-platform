import pytest

from titanium_platform import lightburn as lb

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="2.0.04" DeviceName="JPT MOPA" FormatVersion="1">
    <Thumbnail Source="AAAA"/>
    <CutSetting type="Scan">
        <index Value="0"/><name Value="C00"/>
        <maxPower Value="24"/><speed Value="900"/><frequency Value="40000"/>
        <QPulseWidth Value="4"/><interval Value="0.025"/>
    </CutSetting>
    <CutSetting type="Scan">
        <index Value="18"/><name Value="C18"/>
        <maxPower Value="48.5"/><speed Value="1100"/><frequency Value="330000"/>
        <QPulseWidth Value="6"/><interval Value="0.003"/>
    </CutSetting>
    <CutSetting type="Scan">
        <index Value="19"/><name Value="broken"/>
        <maxPower Value="abc"/><speed Value="150"/>
    </CutSetting>
    <CutSetting_Img type="Image">
        <index Value="7"/><name Value="img"/>
        <maxPower Value="70"/><speed Value="800"/><frequency Value="48000"/>
    </CutSetting_Img>
    <Shape Type="Rect" CutIndex="0" W="10" H="4" Cr="0"><XForm>1 0 0 1 85 85</XForm></Shape>
    <Shape Type="Rect" CutIndex="18" W="2" H="2" Cr="0"><XForm>2 0 0 3 10 20</XForm></Shape>
    <Shape Type="Path" CutIndex="0" VertID="1" PrimID="2">
        <XForm>0.5 0 0 0.5 10 160</XForm>
        <VertList>V0 0c0x1c1x1V10 -4c0x1c1x1V4 8c0x1c1x1</VertList>
        <PrimList>L0 1L1 2</PrimList>
    </Shape>
    <Shape Type="Rect" CutIndex="99" W="1" H="1"><XForm>1 0 0 1 0 0</XForm></Shape>
    <Notes ShowOnLoad="0" Notes=""/>
</LightBurnProject>"""


def test_reads_layer_parameters_and_units():
    p = lb.parse_bytes(SAMPLE)
    assert (p.app_version, p.device_name) == ("2.0.04", "JPT MOPA")
    l0 = p.layer(0)
    assert (l0.power, l0.speed, l0.frequency_hz, l0.frequency_khz) == (24, 900, 40000, 40.0)
    assert (l0.pulse_width, l0.line_interval) == (4, 0.025)
    assert p.layer(18).power == 48.5 and p.layer(18).frequency_khz == 330.0
    assert p.layer(7).layer_type == "Image"


def test_unreadable_parameters_are_reported_not_guessed():
    broken = lb.parse_bytes(SAMPLE).layer(19)
    assert not broken.readable
    assert broken.power is None and broken.frequency_hz is None
    assert any("maxPower" in m for m in broken.unreadable)
    assert any("frequency" in m for m in broken.unreadable)
    assert broken.speed == 150


def test_missing_optional_constants_stay_none():
    img = lb.parse_bytes(SAMPLE).layer(7)
    assert img.readable and img.pulse_width is None and img.line_interval is None


def test_rect_geometry_applies_the_transform():
    r = lb.parse_bytes(SAMPLE).layer(0).regions[0]
    assert (r.kind, r.x, r.y, r.width, r.height) == ("rect", 80, 83, 10, 4)
    scaled = lb.parse_bytes(SAMPLE).layer(18).regions[0]
    # 2x2 rect centred on its origin, transform scale (2, 3) and translation (10, 20): x 8..12, y 17..23
    assert (scaled.x, scaled.y, scaled.width, scaled.height) == (
        pytest.approx(8), pytest.approx(17), pytest.approx(4), pytest.approx(6))


def test_path_geometry_is_a_bounding_box():
    path = lb.parse_bytes(SAMPLE).layer(0).regions[1]
    assert path.kind == "path"
    assert (path.x, path.width) == (pytest.approx(10), pytest.approx(5))
    assert (path.y, path.height) == (pytest.approx(158), pytest.approx(6))


def test_shapes_on_unknown_layers_are_ignored():
    p = lb.parse_bytes(SAMPLE)
    assert sum(len(l.regions) for l in p.layers) == 3


@pytest.mark.parametrize("data", [b"not xml", b"<Other/>", b""])
def test_rejects_non_lightburn_input(data):
    with pytest.raises(lb.LightBurnError):
        lb.parse_bytes(data)


def test_layer_without_index_is_an_error():
    with pytest.raises(lb.LightBurnError):
        lb.parse_bytes(b'<LightBurnProject><CutSetting type="Scan"><maxPower Value="1"/></CutSetting></LightBurnProject>')


def test_compare_with_profile_constants_dec_022():
    l0 = lb.parse_bytes(SAMPLE).layer(0)
    assert lb.compare_with_profile(l0, pulse_width=4, line_interval=0.025) == []
    diffs = lb.compare_with_profile(l0, pulse_width=200, line_interval=0.025)
    assert len(diffs) == 1 and "pulse width" in diffs[0]
    img = lb.parse_bytes(SAMPLE).layer(7)  # file records neither constant: not a difference
    assert lb.compare_with_profile(img, pulse_width=200, line_interval=0.025) == []
