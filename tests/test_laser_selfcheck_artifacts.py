"""The ready-to-open LightBurn capability plates carry their settings and fit the 100 mm field."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from titanium_platform import lightburn as lb


ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "laser-selfcheck"
EXPECTED_FILES = {
    "01_titanium_power_speed_envelope_100mm.lbrn2",
    "02_titanium_frequency_range_100mm.lbrn2",
    "03_titanium_pulse_cutoff_response_100mm.lbrn2",
    "04_titanium_line_resolution_100mm.lbrn2",
    "05_titanium_hatch_interval_100mm.lbrn2",
}
FILES = [ROOT / name for name in sorted(EXPECTED_FILES)]


def test_all_current_capability_plates_exist():
    assert all(path.is_file() for path in FILES)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_ready_projects_start_with_cleaning_and_fit_100mm(path):
    raw = path.read_bytes()
    project = lb.parse_bytes(raw)
    root = ET.fromstring(raw)
    assert all(setting.find("frequency").get("Value", "").isdigit()
               for setting in root.iter("CutSetting"))
    layers = {layer.index: layer for layer in project.layers}
    clean = layers[0]
    assert clean.name == "CLEAN-CROSSHATCH-P20-F48-V2000-PW200-I0.05"
    assert clean.layer_type == "Scan"
    assert (clean.power, clean.frequency_khz, clean.speed) == (20, 48, 2000)
    assert (clean.pulse_width, clean.line_interval, clean.passes, clean.global_passes) == (200, 0.05, 1, 1)
    assert clean.bidirectional is True and clean.cross_hatch is True
    assert clean.scan_angle == 0 and clean.angle_increment == 0
    marker = layers[1]
    assert marker.name == "Markers and labels"
    assert (marker.power, marker.frequency_khz, marker.speed) == (25, 60, 150)
    assert (marker.pulse_width, marker.line_interval, marker.passes, marker.global_passes) == (200, 0.01, 1, 1)
    assert marker.bidirectional is False and marker.cross_hatch is False
    assert all(layer.readable for layer in project.layers)
    assert "TCE1:" in project.notes

    clean_shapes = [s for s in root.iter("Shape") if s.get("CutIndex") == "0"]
    assert len(clean_shapes) == 1 and clean_shapes[0].get("Type") == "Rect"
    non_clean_regions = [region for layer in project.layers if layer.index != 0 for region in layer.regions]
    min_x = min(r.x for r in non_clean_regions)
    min_y = min(r.y for r in non_clean_regions)
    max_x = max(r.x + r.width for r in non_clean_regions)
    max_y = max(r.y + r.height for r in non_clean_regions)
    assert min_x >= -1e-4 and min_y >= -1e-4
    assert max_x <= 100 and max_y <= 100
    clean_region = clean.regions[0]
    assert clean_region.x <= min_x + 1e-4 and clean_region.y <= min_y + 1e-4
    assert clean_region.x + clean_region.width >= max_x - 1e-4
    assert clean_region.y + clean_region.height >= max_y - 1e-4


def test_power_speed_plate_uses_long_line_strokes_and_spans_the_requested_envelope():
    project = lb.parse_file(str(ROOT / "01_titanium_power_speed_envelope_100mm.lbrn2"))
    test_layers = project.layers[2:]
    assert len(test_layers) == 56
    assert all(layer.name.startswith("ENVELOPE-") for layer in test_layers)
    assert all(layer.layer_type == "Cut" and len(layer.regions) == 1 for layer in test_layers)
    assert {round(layer.power) for layer in test_layers} == {5, 10, 20, 30, 50, 75, 100}
    assert {round(layer.speed) for layer in test_layers} == {500, 1000, 1500, 2000, 3000, 5000, 7500, 10000}
    assert {layer.frequency_khz for layer in test_layers} == {48}
    assert {layer.pulse_width for layer in test_layers} == {200}
    assert all(region.width == pytest.approx(53.0) for layer in test_layers for region in layer.regions)


def test_frequency_plate_spans_laser_repetition_range_at_a_fixed_short_pulse():
    project = lb.parse_file(str(ROOT / "02_titanium_frequency_range_100mm.lbrn2"))
    layers = project.layers[2:]
    assert len(layers) == 18
    assert {round(layer.frequency_khz) for layer in layers} == {
        1, 5, 10, 20, 30, 40, 48, 60, 80, 100, 150, 200, 300, 500, 800, 1200, 2000, 4000
    }
    assert all(layer.layer_type == "Cut" and len(layer.regions) == 1 for layer in layers)
    assert all((layer.power, layer.speed, layer.pulse_width) == (20, 2000, 2) for layer in layers)
    assert all(region.width == pytest.approx(56.0) for layer in layers for region in layer.regions)


def test_each_pulse_step_is_checked_around_its_frequency_knee_with_a_cw_reference():
    project = lb.parse_file(str(ROOT / "03_titanium_pulse_cutoff_response_100mm.lbrn2"))
    cutoff = {2: 1950, 4: 1350, 6: 975, 9: 600, 13: 412, 20: 252, 30: 187, 45: 150,
              60: 135, 80: 112, 100: 105, 150: 57, 200: 48, 250: 46, 350: 40, 500: 40}
    layers = project.layers[2:]
    assert len(layers) == 49
    assert all(layer.layer_type == "Cut" and len(layer.regions) == 1 for layer in layers)
    assert all((layer.power, layer.speed) == (20, 900) for layer in layers)
    assert {layer.pulse_width for layer in layers} == {*cutoff, 1}
    for pulse, knee in cutoff.items():
        actual = sorted(layer.frequency_khz for layer in layers if layer.pulse_width == pulse)
        assert actual == pytest.approx(sorted((0.8 * knee, knee, 1.2 * knee)))
    cw = next(layer for layer in layers if layer.pulse_width == 1)
    assert cw.frequency_khz == 48 and "CW" in cw.name and "REFERENCE" in cw.name


def test_resolution_plate_encodes_ten_line_pitches_not_fill_coupons():
    project = lb.parse_file(str(ROOT / "04_titanium_line_resolution_100mm.lbrn2"))
    layers = project.layers[2:]
    pitches_um = (20, 30, 40, 50, 60, 80, 100, 150, 200, 300)
    assert len(layers) == len(pitches_um)
    assert all(layer.layer_type == "Cut" and len(layer.regions) == 5 for layer in layers)
    assert all((layer.power, layer.frequency_khz, layer.speed, layer.pulse_width) == (20, 48, 2000, 200)
               for layer in layers)
    for layer, pitch_um in zip(layers, pitches_um):
        assert f"PITCH{pitch_um}UM" in layer.name
        ys = sorted(region.y for region in layer.regions)
        assert [b - a for a, b in zip(ys, ys[1:])] == pytest.approx([pitch_um / 1000] * 4)
        assert all(region.width == pytest.approx(7.0) for region in layer.regions)


def test_hatch_plate_is_small_and_varies_only_fill_interval():
    project = lb.parse_file(str(ROOT / "05_titanium_hatch_interval_100mm.lbrn2"))
    layers = project.layers[2:]
    assert len(layers) == 5
    assert {layer.line_interval for layer in layers} == {0.01, 0.025, 0.05, 0.1, 0.2}
    assert all(layer.layer_type == "Scan" and len(layer.regions) == 1 for layer in layers)
    assert all((layer.power, layer.frequency_khz, layer.speed, layer.pulse_width) == (20, 48, 2000, 200)
               for layer in layers)
    assert all(layer.passes == layer.global_passes == 1 and layer.cross_hatch is False for layer in layers)
