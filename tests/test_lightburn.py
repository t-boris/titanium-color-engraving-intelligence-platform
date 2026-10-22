import base64

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
        <QPulseWidth Value="6"/><interval Value="0.003"/><wobbleStep Value="0.0500"/>
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
    assert p.layer(18).as_dict()["source_settings"]["wobbleStep"]["Value"] == "0.0500"


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
    assert path.closed is False  # three vertices alone do not make a filled vector
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


def test_regions_expose_their_outline_and_the_notes_identifier():
    p = lb.parse_bytes(SAMPLE)
    rect = p.layer(0).regions[0]
    assert rect.closed is True
    assert [tuple(round(v, 6) for v in pt) for pt in rect.polygon] == [(80, 83), (90, 83), (90, 87), (80, 87)]
    assert len(p.layer(0).regions[1].polygon) == 3  # the path's on-curve vertices
    assert p.identifier is None
    q = lb.parse_bytes(b'<LightBurnProject><Notes ShowOnLoad="0" Notes="TCE1:TCE-0A1B2C3D"/></LightBurnProject>')
    assert q.identifier == "TCE-0A1B2C3D"


# -- exact path geometry (REQ-023, DEC-048) ----------------------------------------------------------------
def _project(*shapes: str) -> lb.Project:
    body = "".join(shapes)
    return lb.parse_bytes(
        ('<LightBurnProject AppVersion="2.1.04"><CutSetting type="Scan"><index Value="0"/><name Value="C00"/>'
         '<maxPower Value="20"/><speed Value="900"/><frequency Value="48000"/></CutSetting>' + body +
         '</LightBurnProject>').encode())


def _path(verts: str, prims: str, xform: str = "1 0 0 1 0 0") -> str:
    return (f'<Shape Type="Path" CutIndex="0"><XForm>{xform}</XForm><VertList>{verts}</VertList>'
            f'<PrimList>{prims}</PrimList></Shape>')


def _square(x: float, y: float, size: float) -> tuple[str, str]:
    pts = [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
    return "".join(f"V{a} {b}c0x1c1x1" for a, b in pts), "L0 1L1 2L2 3L3 0"


def _distance_to_polyline(point, polyline) -> float:
    import numpy as np
    a, b = np.asarray(polyline[:-1], float), np.asarray(polyline[1:], float)
    d = b - a
    t = np.clip(((np.asarray(point) - a) * d).sum(axis=1) / np.maximum((d * d).sum(axis=1), 1e-12), 0, 1)
    return float(np.linalg.norm(a + t[:, None] * d - point, axis=1).min())


def test_bezier_edge_is_flattened_within_tolerance_and_the_loop_is_closed():
    import numpy as np
    verts = "V0 0c0x0c0y10c1x1V20 20c0x1c1x10c1y20"          # P0 (0,0)  P1 (0,10)  P2 (10,20)  P3 (20,20)
    region = _project(_path(verts, "B0 1L1 0")).layer(0).regions[0]
    assert region.closed is True and len(region.polygon) > 8
    p0, p1, p2, p3 = map(np.array, [(0, 0), (0, 10), (10, 20), (20, 20)])
    curve = [(1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
             for t in np.linspace(0, 1, 400)]
    outline = region.polygon + region.polygon[:1]
    assert max(_distance_to_polyline(point, outline) for point in curve) < 0.02
    assert region.x == pytest.approx(0, abs=1e-6) and region.y == pytest.approx(0, abs=1e-6)


def test_path_that_mixes_line_and_bezier_edges_and_returns_to_its_start_is_closed():
    verts = "V0 0c0x1c1x1V10 0c0x1c1x1V10 10c0x10c0y12c1x1V0 10c0x1c1x1"
    region = _project(_path(verts, "L0 1L1 2B2 3L3 0")).layer(0).regions[0]
    assert region.closed is True
    open_region = _project(_path(verts, "L0 1L1 2B2 3")).layer(0).regions[0]
    assert open_region.closed is False


def test_flattening_is_measured_in_project_millimetres_after_the_xform():
    import numpy as np
    verts = "V0 0c0x0c0y10c1x1V20 20c0x1c1x10c1y20"
    small = _project(_path(verts, "B0 1L1 0", "1 0 0 1 0 0")).layer(0).regions[0]
    large = _project(_path(verts, "B0 1L1 0", "4 0 0 4 0 0")).layer(0).regions[0]
    assert len(large.polygon) > len(small.polygon)                 # a 4x curve needs more pieces for the same tolerance
    assert large.x + large.width == pytest.approx(80, abs=1e-6) and large.y + large.height == pytest.approx(80, abs=1e-6)


def test_two_disjoint_loops_in_one_path_are_two_regions():
    a_v, a_p = _square(0, 0, 10)
    b_v, b_p = _square(30, 0, 10)
    verts = a_v + b_v
    prims = a_p + "L4 5L5 6L6 7L7 4"
    layer = _project(_path(verts, prims)).layer(0)
    assert [(round(r.x), r.closed, r.holes) for r in layer.regions] == [(0, True, []), (30, True, [])]


def test_loop_inside_a_loop_is_a_hole_of_the_outer_region():
    outer_v, _ = _square(0, 0, 20)
    inner_v, _ = _square(5, 5, 10)
    verts = outer_v + inner_v
    layer = _project(_path(verts, "L0 1L1 2L2 3L3 0L4 5L5 6L6 7L7 4")).layer(0)
    assert len(layer.regions) == 1
    region = layer.regions[0]
    assert region.closed and len(region.holes) == 1
    assert min(x for x, _ in region.holes[0]) == pytest.approx(5) and max(x for x, _ in region.holes[0]) == pytest.approx(15)
    assert region.as_dict()["holes"][0][0] in ([5.0, 5.0], [15.0, 5.0], [15.0, 15.0], [5.0, 15.0])


def test_island_inside_a_hole_is_a_new_outer_region():
    v1, _ = _square(0, 0, 40)
    v2, _ = _square(5, 5, 30)
    v3, _ = _square(10, 10, 20)
    prims = "L0 1L1 2L2 3L3 0L4 5L5 6L6 7L7 4L8 9L9 10L10 11L11 8"
    layer = _project(_path(v1 + v2 + v3, prims)).layer(0)
    assert len(layer.regions) == 2
    assert [len(r.holes) for r in layer.regions] == [1, 0]


# -- complete capture of a file's settings (REQ-025) --------------------------------------------------------------
SUBLAYERS = b"""<LightBurnProject AppVersion="2.1.04">
  <CutSetting type="Scan"><index Value="0"/><name Value="Engrave"/>
    <maxPower Value="60"/><speed Value="900"/><frequency Value="48000"/><interval Value="0.02"/>
    <SubLayer type="Scan" index="1"><maxPower Value="20"/><speed Value="2000"/><frequency Value="48000"/><interval Value="0.04"/><subname Value="Clean"/></SubLayer>
    <SubLayer type="Scan" index="2"><maxPower Value="10"/><speed Value="3000"/></SubLayer>
  </CutSetting>
  <CutSetting type="Scan"><index Value="1"/><name Value="Plain"/><maxPower Value="25"/><speed Value="150"/><frequency Value="60000"/></CutSetting>
</LightBurnProject>"""


def test_sub_layers_keep_every_nested_setting_in_file_order():
    layers = lb.parse_bytes(SUBLAYERS)
    engrave, plain = layers.layer(0), layers.layer(1)
    subs = engrave.source_settings["SubLayer"]
    assert [s["index"] for s in subs] == ["1", "2"]
    assert subs[0]["maxPower"] == {"Value": "20"} and subs[0]["speed"] == {"Value": "2000"} and subs[0]["subname"] == {"Value": "Clean"}
    assert subs[1]["speed"] == {"Value": "3000"}
    assert "SubLayer" not in plain.source_settings and plain.source_settings["maxPower"] == {"Value": "25"}   # flat layers as before


def test_a_single_sub_layer_is_stored_as_one_mapping_and_two_differ_in_the_recipe_key():
    from titanium_platform import model
    one = SUBLAYERS.replace(b'<SubLayer type="Scan" index="2"><maxPower Value="10"/><speed Value="3000"/></SubLayer>', b"")
    a = lb.parse_bytes(one).layer(0)
    assert a.source_settings["SubLayer"]["speed"] == {"Value": "2000"}
    base = {"power": 60, "frequency": 48, "speed": 900, "pulse_width": 4, "line_interval": 0.02, "passes": 1}
    clean_faster = lb.parse_bytes(one.replace(b'<speed Value="2000"/>', b'<speed Value="2500"/>')).layer(0)
    assert (model.parameters_key({**base, "source_settings": a.source_settings}) !=
            model.parameters_key({**base, "source_settings": clean_faster.source_settings}))


GROUPED = b"""<LightBurnProject AppVersion="2.1.04">
  <CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="900"/><frequency Value="48000"/></CutSetting>
  <Shape Type="Group"><XForm>1 0 0 1 100 50</XForm><Children>
    <Shape Type="Rect" CutIndex="0" W="10" H="4" Cr="0"><XForm>1 0 0 1 5 2</XForm></Shape>
    <Shape Type="Group"><XForm>2 0 0 2 0 0</XForm><Children>
      <Shape Type="Rect" CutIndex="0" W="1" H="1" Cr="0"><XForm>1 0 0 1 3 3</XForm></Shape>
    </Children></Shape>
  </Children></Shape>
</LightBurnProject>"""


def test_group_transforms_are_applied_after_the_transform_of_the_shape_itself():
    regions = lb.parse_bytes(GROUPED).layer(0).regions
    assert len(regions) == 2
    outer, inner = regions
    assert (outer.x, outer.y, outer.width, outer.height) == pytest.approx((100, 50, 10, 4), abs=1e-9)     # centre (5,2) + (100,50), 10 x 4
    # (3,3) scaled by the inner group to (6,6), then moved by the outer group to (106,56); the 1 x 1 rectangle becomes 2 x 2
    assert (inner.x, inner.y, inner.width, inner.height) == pytest.approx((105, 55, 2, 2), abs=1e-9)


def test_shapes_that_are_not_read_are_counted_per_layer_not_dropped_silently():
    xml = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/>'
           b'<speed Value="900"/><frequency Value="48000"/></CutSetting>'
           b'<Shape Type="Text" CutIndex="0" Font="Arial" Str="2000" H="3.5" HasBackupPath="0"><XForm>1 0 0 1 11 10</XForm></Shape>'
           b'<Shape Type="Text" CutIndex="0" Font="Arial" Str="3000" H="3.5" HasBackupPath="0"><XForm>1 0 0 1 21 10</XForm></Shape>'
           b'<Shape Type="Barcode" CutIndex="0" Str="1"><XForm>1 0 0 1 5 5</XForm></Shape>'
           b'<Shape Type="Rect" CutIndex="0" W="2" H="2"><XForm>1 0 0 1 0 0</XForm></Shape></LightBurnProject>')
    layer = lb.parse_bytes(xml).layer(0)
    assert layer.unsupported == {"Text": 2, "Barcode": 1} and len(layer.regions) == 1
    assert layer.as_dict()["unsupported"] == {"Text": 2, "Barcode": 1}


def test_image_object_settings_become_part_of_the_layer_settings_without_the_pixels():
    xml = (b'<LightBurnProject><CutSetting_Img type="Image"><index Value="3"/><name Value="img"/><maxPower Value="70"/><speed Value="800"/>'
           b'<frequency Value="48000"/><dpi Value="318"/></CutSetting_Img>'
           b'<Shape Type="Bitmap" CutIndex="3" W="40" H="30" Gamma="1.2" Contrast="10" Brightness="-5" Data="AAAA" File="x.png" SourceHash="1">'
           b'<XForm>1 0 0 1 50 50</XForm></Shape></LightBurnProject>')
    layer = lb.parse_bytes(xml).layer(3)
    assert layer.source_settings["dpi"] == {"Value": "318"}
    assert layer.source_settings["bitmaps"] == [{"Gamma": "1.2", "Contrast": "10", "Brightness": "-5"}]
    assert len(layer.regions) == 1 and layer.regions[0].kind == "bitmap"


def test_the_run_order_of_a_layer_is_not_part_of_its_recipe():
    from titanium_platform import model
    base = {"power": 75, "frequency": 330, "speed": 1300, "pulse_width": 4, "line_interval": 0.005, "passes": 1}
    first = {"priority": {"Value": "3"}, "scanOpt": {"Value": "individual"}, "bidir": {"Value": "0"}}
    second = {**first, "priority": {"Value": "15"}}
    assert lb.recipe_settings(first) == {"scanOpt": {"Value": "individual"}, "bidir": {"Value": "0"}}
    assert (model.parameters_key({**base, "source_settings": lb.recipe_settings(first)}) ==
            model.parameters_key({**base, "source_settings": lb.recipe_settings(second)}))
    assert lb.recipe_settings(None) == {}


def test_an_ellipse_is_read_as_a_closed_outline_under_its_transform():
    import numpy as np
    xml = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="900"/>'
           b'<frequency Value="48000"/></CutSetting><Shape Type="Ellipse" CutIndex="0" Rx="6" Ry="3"><XForm>2 0 0 2 50 40</XForm></Shape>'
           b'</LightBurnProject>')
    layer = lb.parse_bytes(xml).layer(0)
    (region,) = layer.regions
    assert region.closed and not layer.unsupported
    assert (region.x, region.y, region.width, region.height) == pytest.approx((38, 34, 24, 12), abs=0.01)
    pts = np.array(region.polygon)
    area = abs(np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])) / 2
    assert area == pytest.approx(np.pi * 12 * 6, rel=0.002)


def test_a_text_object_with_its_converted_outline_is_read_and_one_without_is_reported():
    # layout of LightBurn 1.7: the BackupPath carries the same XForm as the text, its vertices are local
    xml = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="900"/>'
           b'<frequency Value="48000"/></CutSetting>'
           b'<Shape Type="Text" CutIndex="0" Font="Arial" Str="A" H="3.5" HasBackupPath="1">'
           b'<BackupPath Type="Path" CutIndex="0"><XForm>1 0 0 1 20 30</XForm><VertList>V0 0c0x1c1x1V4 0c0x1c1x1V4 6c0x1c1x1V0 6c0x1c1x1</VertList>'
           b'<PrimList>L0 1L1 2L2 3L3 0</PrimList></BackupPath><XForm>1 0 0 1 20 30</XForm></Shape>'
           b'<Shape Type="Text" CutIndex="0" Font="Arial" Str="B" H="3.5" HasBackupPath="0"><XForm>1 0 0 1 40 30</XForm></Shape>'
           b'</LightBurnProject>')
    layer = lb.parse_bytes(xml).layer(0)
    assert len(layer.regions) == 1 and layer.unsupported == {"Text": 1}
    region = layer.regions[0]
    assert region.closed and (region.x, region.y, region.width, region.height) == pytest.approx((20, 30, 4, 6), abs=1e-9)


def test_a_text_outline_inside_a_group_is_moved_by_the_group_once():
    xml = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="900"/>'
           b'<frequency Value="48000"/></CutSetting><Shape Type="Group"><XForm>1 0 0 1 100 50</XForm><Children>'
           b'<Shape Type="Text" CutIndex="0" Str="A" HasBackupPath="1"><BackupPath Type="Path" CutIndex="0"><XForm>1 0 0 1 20 30</XForm>'
           b'<VertList>V0 0c0x1c1x1V4 0c0x1c1x1V4 6c0x1c1x1</VertList><PrimList>L0 1L1 2L2 0</PrimList></BackupPath>'
           b'<XForm>1 0 0 1 20 30</XForm></Shape></Children></Shape></LightBurnProject>')
    (region,) = lb.parse_bytes(xml).layer(0).regions
    assert (region.x, region.y) == pytest.approx((120, 80), abs=1e-9)


def test_every_shape_without_an_outline_and_every_setting_unknown_to_the_reader_is_reported_on_its_layer():
    """REQ-036 AC3: a flat ellipse, an empty path, a rectangle without a size and a shape type the reader does not know have
    no outline to measure, so each is counted on its layer; a setting the reader does not know is kept with the recipe and named."""
    xml = (b'<LightBurnProject><CutSetting type="Scan"><index Value="0"/><name Value="C00"/><maxPower Value="20"/><speed Value="900"/>'
           b'<frequency Value="48000"/><tabCount Value="1"/><rampLength Value="2"/><perfMode Value="1"/></CutSetting>'
           b'<Shape Type="Ellipse" CutIndex="0" Rx="0" Ry="3"><XForm>1 0 0 1 10 10</XForm></Shape>'
           b'<Shape Type="Path" CutIndex="0"><XForm>1 0 0 1 0 0</XForm><VertList></VertList><PrimList></PrimList></Shape>'
           b'<Shape Type="Rect" CutIndex="0" H="2"><XForm>1 0 0 1 0 0</XForm></Shape>'
           b'<Shape Type="Polygon" CutIndex="0" N="6"><XForm>1 0 0 1 5 5</XForm></Shape>'
           b'<Shape Type="Rect" CutIndex="0" W="2" H="2"><XForm>1 0 0 1 0 0</XForm></Shape></LightBurnProject>')
    layer = lb.parse_bytes(xml).layer(0)
    assert len(layer.regions) == 1
    assert layer.unsupported == {"Ellipse": 1, "Path": 1, "Rect": 1, "Polygon": 1}
    assert layer.unknown_settings == ["perfMode", "rampLength"]
    assert layer.source_settings["rampLength"] == {"Value": "2"}            # kept, so it still separates recipes
    assert layer.as_dict()["unknown_settings"] == ["perfMode", "rampLength"]


def test_a_path_without_its_own_lists_takes_the_ones_its_ids_name():
    """LightBurn writes a vertex or primitive list once and later paths name it by VertID / PrimID: in a saved work 222 of 574 paths
    carried no PrimList of their own and were read as open lines with no area."""
    verts, prims = _square(0, 0, 10)
    other, _ = _square(20, 0, 4)
    project = _project(
        f'<Shape Type="Path" CutIndex="0" VertID="0" PrimID="0"><XForm>1 0 0 1 0 0</XForm><VertList>{verts}</VertList>'
        f'<PrimList>{prims}</PrimList></Shape>',
        f'<Shape Type="Path" CutIndex="0" VertID="1" PrimID="0"><XForm>1 0 0 1 0 0</XForm><VertList>{other}</VertList></Shape>',
        '<Shape Type="Path" CutIndex="0" VertID="0" PrimID="0"><XForm>1 0 0 1 0 30</XForm></Shape>')
    regions = project.layer(0).regions
    assert [r.closed for r in regions] == [True, True, True]
    assert [(round(r.x), round(r.y), round(r.width), round(r.height)) for r in regions] == [(0, 0, 10, 10), (20, 0, 4, 4), (0, 30, 10, 10)]


def test_a_picture_stored_once_is_read_for_every_bitmap_that_names_it():
    """LightBurn 2.2 stores a picture placed twice once: the later Bitmap carries no Data, only the SourceHash of the first, under its own
    file name (the grey-ramp plate saved by the operator held each row's ramp once for its two tiles, GREY-...-PW250.png and -PW350.png,
    and the second tile was read with no picture, DEC-103)."""
    ramp = base64.b64encode(b"ramp of the first row").decode()
    project = _project(
        f'<Shape Type="Bitmap" CutIndex="0" W="38" H="4" Data="{ramp}" File="GREY-PW250.png" SourceHash="3"><XForm>1 0 0 -1 20 10</XForm></Shape>',
        '<Shape Type="Bitmap" CutIndex="0" W="38" H="4" Data="" File="GREY-PW350.png" SourceHash="3"><XForm>1 0 0 -1 60 10</XForm></Shape>',
        '<Shape Type="Bitmap" CutIndex="0" W="38" H="4" Data="" File="other.png" SourceHash="5"><XForm>1 0 0 -1 20 20</XForm></Shape>')
    # a hash no Bitmap of the file stores names no picture, as before
    assert [r.bitmap["png"] for r in project.layer(0).regions] == [b"ramp of the first row", b"ramp of the first row", None]


def test_a_file_lightburn_reflected_keeps_each_picture_and_hole_on_its_shape():
    """LightBurn rewrote MirrorY and reflected every XForm: the outlines are reflected back to the plan's axes, and a picture's own matrix
    and a shape's holes go with them. Before, what a picture strikes landed mirrored about the work's centre and missed its tile (DEC-103)."""
    outer, _ = _square(60, 0, 20)
    hole, _ = _square(63, 2, 2)
    data = ('<LightBurnProject AppVersion="2.2.00" MirrorX="False" MirrorY="False"><CutSetting type="Image"><index Value="0"/>'
            '<name Value="C00"/><maxPower Value="30"/><speed Value="150"/><frequency Value="60000"/></CutSetting>'
            '<Shape Type="Bitmap" CutIndex="0" W="40" H="10" Data="" SourceHash="0"><XForm>1 0 0 -1 30 5</XForm></Shape>'
            f'<Shape Type="Path" CutIndex="0"><XForm>1 0 0 1 0 0</XForm><VertList>{outer}{hole}</VertList>'
            '<PrimList>L0 1L1 2L2 3L3 0L4 5L5 6L6 7L7 4</PrimList></Shape></LightBurnProject>')
    project = lb.parse_bytes(data.encode())

    assert lb.normalize_saved_orientation(project, mirror_x=False, mirror_y=True) == ["Y"]

    picture, shape = project.layer(0).regions
    assert (picture.y, picture.height) == pytest.approx((10, 10))                      # y -> 20 - y over the work's 0..20
    corners = [lb._apply(picture.bitmap["matrix"], sx * 20, sy * 5) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    assert sorted(corners) == pytest.approx(sorted(picture.polygon))                  # the picture lies on its reflected rectangle
    (inside,) = shape.holes
    assert (min(y for _, y in inside), max(y for _, y in inside)) == pytest.approx((16, 18))
