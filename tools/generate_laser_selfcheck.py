"""Generate the prepared 100 mm titanium self-check LightBurn projects.

Run with the project's installed environment:
    PYTHONPATH=src ~/.titanium-platform-app/bin/python tools/generate_laser_selfcheck.py

The files use the job settings of the JPT MOPA M7 60 W laser and the marker-layer settings saved in the local
Titanium Platform database on 2026-10-14. This script does not change that database.
"""
from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import quoteattr

from titanium_platform import plans


OUT = Path(__file__).resolve().parents[1] / "artifacts" / "laser-selfcheck"
MARKER = (25.0, 60.0, 150.0)  # user-provided black-on-titanium recipe: power %, frequency kHz, speed mm/s
MARKER_PULSE = 200.0
MARKER_INTERVAL = 0.01
PULSE = 200.0                   # job pulse width of the self-check, ns
INTERVAL = 0.025                # job line interval of the self-check, mm
CLEAN = (20.0, 48.0, 2000.0)    # cleanup: power %, frequency kHz, speed mm/s
CLEAN_INTERVAL = 0.05            # user-specified cleaning hatch spacing, mm
CLEAN_NAME = "CLEAN-CROSSHATCH-P20-F48-V2000-PW200-I0.05"

# A small built-in bitmap alphabet keeps the labels independent of fonts installed in LightBurn.
FONT = {
    "A": "010/101/111/101/101", "B": "110/101/110/101/110", "C": "011/100/100/100/011",
    "D": "110/101/101/101/110", "E": "111/100/110/100/111", "F": "111/100/110/100/100",
    "G": "011/100/101/101/011", "H": "101/101/111/101/101", "I": "111/010/010/010/111",
    "J": "001/001/001/101/010", "K": "101/101/110/101/101", "L": "100/100/100/100/111",
    "M": "101/111/111/101/101", "N": "101/111/111/111/101", "O": "010/101/101/101/010",
    "P": "110/101/110/100/100", "Q": "010/101/101/111/011", "R": "110/101/110/101/101",
    "S": "011/100/010/001/110", "T": "111/010/010/010/010", "U": "101/101/101/101/111",
    "V": "101/101/101/101/010", "W": "101/101/111/111/101", "X": "101/101/010/101/101",
    "Y": "101/101/010/010/010", "Z": "111/001/010/100/111",
    "0": "111/101/101/101/111", "1": "010/110/010/010/111", "2": "110/001/010/100/111",
    "3": "110/001/010/001/110", "4": "101/101/111/001/001", "5": "111/100/110/001/110",
    "6": "011/100/110/101/010", "7": "111/001/010/010/010", "8": "010/101/010/101/010",
    "9": "010/101/011/001/110", "-": "000/000/111/000/000", ".": "000/000/000/000/010",
    "%": "101/001/010/100/101", "/": "001/001/010/100/100", ":": "000/010/000/010/000",
}


def text_shapes(text: str, x: float, y: float, size: float = 0.22, layer: int = 0) -> list[tuple]:
    result = []
    # Enlarge the compact source glyphs for legible marks at the 100 mm plate scale.
    size *= 1.5
    pitch = size * 1.35
    for ci, ch in enumerate(text.upper()):
        glyph = FONT.get(ch)
        if glyph is None:
            continue
        for ry, row in enumerate(glyph.split("/")):
            for rx, lit in enumerate(row):
                if lit == "1":
                    result.append((x + ci * pitch + rx * size, y + ry * size, size, size, layer))
    return result


def rects(items: list[tuple[float, float, float, float]], layer: int) -> list[tuple]:
    return [(x, y, w, h, layer) for x, y, w, h in items]


def lines(items: list[tuple[float, float, float, float]], layer: int) -> list[tuple]:
    """Individual LightBurn path strokes (x1, y1, x2, y2), not filled coupons."""
    return [("line", x1, y1, x2, y2, layer) for x1, y1, x2, y2 in items]


def line_shape(x1: float, y1: float, x2: float, y2: float, layer: int, shape_id: int) -> str:
    return (f'    <Shape Type="Path" CutIndex="{layer}" VertID="{shape_id * 2 - 1}" PrimID="{shape_id * 2}">\n'
            f'        <XForm>1 0 0 1 0 0</XForm>\n'
            f'        <VertList>V{x1:.5f} {y1:.5f}c0x1c1x1V{x2:.5f} {y2:.5f}c0x1c1x1</VertList>\n'
            f'        <PrimList>L0 1</PrimList>\n    </Shape>\n')


def cut_setting(index: int, name: str, power: float, frequency: float, speed: float,
                pulse: float | None = PULSE, interval: float | None = INTERVAL,
                *, angle: float = 0, cross_hatch: bool = False, passes: int = 1,
                global_passes: int = 1, bidirectional: bool = True,
                angle_increment: float = 0, cut_type: str = "Scan") -> str:
    result = plans._cut_setting(index, name, power, frequency, speed, pulse, interval,
                                cross_hatch=cross_hatch, angle=angle, passes=passes,
                                global_passes=global_passes, bidirectional=bidirectional,
                                angle_increment=angle_increment, cut_type=cut_type)
    # LightBurn parses this field as integer Hz and rejects Python-style exponent notation.
    generated = f'<frequency Value="{frequency * 1000:g}"/>'
    compatible = f'<frequency Value="{round(frequency * 1000)}"/>'
    return result.replace(generated, compatible)


def write_project(path: Path, identifier: str, canvas_w: float, canvas_h: float,
                  layers: list[dict], shapes: list[tuple], notes: str) -> dict:
    markers = plans.marker_geometry(identifier, canvas_w, canvas_h)
    dx, dy = -markers["extent"]["min_x"], -markers["extent"]["min_y"]
    if len(layers) + 2 > plans.MAX_LAYERS:
        raise ValueError(f"{len(layers) + 2} layers exceed LightBurn's {plans.MAX_LAYERS}-layer limit")
    width = markers["extent"]["max_x"] - markers["extent"]["min_x"]
    height = markers["extent"]["max_y"] - markers["extent"]["min_y"]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<LightBurnProject AppVersion="2.0.04" FormatVersion="1" MaterialHeight="0" MirrorX="False" MirrorY="False">\n',
        cut_setting(0, CLEAN_NAME, *CLEAN, pulse=PULSE, interval=CLEAN_INTERVAL,
                    angle=0, cross_hatch=True, passes=1, global_passes=1,
                    bidirectional=True, angle_increment=0),
        cut_setting(1, "Markers and labels", *MARKER, pulse=MARKER_PULSE, interval=MARKER_INTERVAL,
                    passes=1, global_passes=1, bidirectional=False),
    ]
    for layer in layers:
        out.append(cut_setting(layer["index"] + 1, layer["name"], layer["power"], layer["frequency"],
                               layer["speed"], layer.get("pulse", PULSE), layer.get("interval", INTERVAL),
                               angle=layer.get("angle", 0), cross_hatch=layer.get("cross_hatch", False),
                               passes=layer.get("passes", 1), global_passes=layer.get("global_passes", 1),
                               bidirectional=layer.get("bidirectional", True),
                               angle_increment=layer.get("angle_increment", 0),
                               cut_type=layer.get("cut_type", "Scan")))
    # Layer zero is reserved for full-area cleaning; source layer zero maps to annotations, and
    # source test layers shift by one to leave room for the cleanup layer.
    out.append(plans._rect(0, 0, width, height, 0))
    for shape_id, shape in enumerate(shapes, start=1):
        if shape[0] == "line":
            _, x1, y1, x2, y2, layer_index = shape
            out.append(line_shape(x1 + dx, y1 + dy, x2 + dx, y2 + dy,
                                  1 if layer_index == 0 else layer_index + 1, shape_id))
        else:
            x, y, w, h, layer_index = shape
            out.append(plans._rect(x + dx, y + dy, w, h, 1 if layer_index == 0 else layer_index + 1))
    for marker in markers["aruco"]:
        for r in marker["rects"]:
            out.append(plans._rect(r["x"] + dx, r["y"] + dy, r["width"], r["height"], 1))
    for r in markers["qr"]["rects"]:
        out.append(plans._rect(r["x"] + dx, r["y"] + dy, r["width"], r["height"], 1))
    note_text = (f"TCE1:{identifier}\nHardware: JPT YDFLP-E-60-M7-M-R 60 W, serial MC2BDJD71684; "
                 f"lens: F-Theta 174 mm; material: titanium (link the exact grade and batch in the experiment record).\n"
                 f"{notes}\nCanvas {canvas_w:g} x {canvas_h:g} mm; "
                 f"registered bounds {width:g} x {height:g} mm. First: full-area cross-hatched cleaning, "
                 f"20% / 48 kHz / 2000 mm/s / 200 ns / 0.05 mm; second: black marker/label layer "
                 f"25% / 60 kHz / 150 mm/s / 200 ns / 0.01 mm, one pass.")
    out.append(f'    <Notes ShowOnLoad="0" Notes={quoteattr(note_text)}/>\n</LightBurnProject>\n')
    path.write_bytes("".join(out).encode("utf-8"))
    return {"layers_including_cleaning_and_markers": len(layers) + 2, "shapes": len(out) - len(layers) - 5,
            "registered_bounds_mm": [round(width, 2), round(height, 2)], "identifier": identifier}


def main_matrix() -> dict:
    identifier = "TCE-SC-20261014-A1"
    layers: list[dict] = []
    shapes: list[tuple] = []
    shapes += text_shapes("POWER X SPEED - LINE RESPONSE", 4.0, 1.0, 0.24)
    shapes += text_shapes("TOP TO BOTTOM: V500 1000 1500 2000 3000 5000 7500 10000", 4.0, 4.0, 0.11)
    shapes += text_shapes("EACH GROUP: FIXED POWER / F48 KHZ / PW200 NS", 4.0, 6.4, 0.13)
    powers, speeds = (5, 10, 20, 30, 50, 75, 100), (500, 1000, 1500, 2000, 3000, 5000, 7500, 10000)
    y0, row_pitch, group_gap = 10.0, 0.72, 0.85
    x1, x2 = 17.0, 70.0
    for pi, power in enumerate(powers):
        group_y = y0 + pi * (len(speeds) * row_pitch + group_gap)
        shapes += text_shapes(f"P{power}", 4.0, group_y + 2.2, 0.16)
        for si, speed in enumerate(speeds):
            y = group_y + si * row_pitch
            shapes += text_shapes(f"{speed}", 10.5, y - 0.26, 0.08)
            index = len(layers) + 1
            layers.append({"index": index, "name": f"ENVELOPE-P{power}-F48-V{speed}-PW200",
                           "power": power, "frequency": 48, "speed": speed,
                           "pulse": 200, "interval": None, "cut_type": "Cut"})
            shapes += lines([(x1, y, x2, y)], index)

    path = OUT / "01_titanium_power_speed_envelope_100mm.lbrn2"
    info = write_project(path, identifier, 76.0, 56.0, layers, shapes,
        "Hardware/process-envelope test, not a titanium colour chart. JPT YDFLP-E-60-M7-M-R with "
        "F-Theta 174 mm. Seven power groups P5/10/20/30/50/75/100%; within every group the eight "
        "horizontal strokes run top-to-bottom at V500/1000/1500/2000/3000/5000/7500/10000 mm/s. "
        "Each Line is 53 mm long so higher commanded speeds have enough run-up distance. Fixed F48 kHz, "
        "Q-Pulse 200 ns and one pass. Compare the onset of a repeatable track and the highest speed that "
        "still produces a continuous mark. Values above the controller/galvo limit may be clamped or rejected. "
        "A photo does not measure optical watts; use a calibrated power meter for output power. The titanium "
        "track is a surface-response observation, not colour matching.")
    info["file"] = str(path.relative_to(OUT.parents[1]))
    info["test_layers"] = len(layers)
    return info


def frequency_range() -> dict:
    """Map titanium line response over the laser's stated repetition-rate range."""
    identifier = "TCE-SC-20261014-F1"
    frequencies = (1, 5, 10, 20, 30, 40, 48, 60, 80, 100, 150, 200, 300, 500, 800, 1200, 2000, 4000)
    layers: list[dict] = []
    shapes: list[tuple] = []
    shapes += text_shapes("REPETITION RATE RANGE - LINE RESPONSE", 4.0, 1.0, 0.22)
    shapes += text_shapes("FREQUENCY LABELS AT LEFT / FIXED P20 V2000 PW2NS", 4.0, 4.0, 0.14)
    x1, x2, y0, row_pitch = 14.0, 70.0, 10.5, 2.25
    for row, frequency in enumerate(frequencies):
        y = y0 + row * row_pitch
        shapes += text_shapes(f"F{frequency}", 5.0, y - 0.35, 0.12)
        index = len(layers) + 1
        layers.append({"index": index, "name": f"FREQUENCY-RANGE-P20-F{frequency}-V2000-PW2",
                       "power": 20, "frequency": frequency, "speed": 2000,
                       "pulse": 2, "interval": None, "cut_type": "Cut"})
        shapes += lines([(x1, y, x2, y)], index)
    path = OUT / "02_titanium_frequency_range_100mm.lbrn2"
    info = write_project(path, identifier, 76.0, 56.0, layers, shapes,
        "Repetition-rate response test for JPT YDFLP-E-60-M7-M-R with F-Theta 174 mm. "
        "Each row is one 56 mm LightBurn Line stroke, frequencies 1/5/10/20/30/40/48/60/80/100/150/200/300/500/800/1200/2000/4000 kHz. "
        "Fixed P20%, V2000 mm/s and the 2 ns pulse step; one pass. This spans the laser passport's "
        "stated 1-4000 kHz repetition range. Frequency also changes pulse energy and output response, "
        "so compare track continuity and width as a response curve; this is not a frequency-only power measurement.")
    info["file"] = str(path.relative_to(OUT.parents[1]))
    info["test_layers"] = len(layers)
    return info


def pulse_cutoff_response() -> dict:
    """Check each selectable pulsed Q-Pulse step around its listed cut-off frequency."""
    identifier = "TCE-SC-20261014-C1"
    cutoff_by_pulse = [(2, 1950), (4, 1350), (6, 975), (9, 600), (13, 412), (20, 252),
                       (30, 187), (45, 150), (60, 135), (80, 112), (100, 105), (150, 57),
                       (200, 48), (250, 46), (350, 40), (500, 40)]
    layers: list[dict] = []
    shapes: list[tuple] = []
    shapes += text_shapes("Q-PULSE STEPS / FREQUENCY KNEE", 4.0, 1.0, 0.24)
    shapes += text_shapes("EACH ROW: 0.8X / 1.0X / 1.2X OF LISTED KNEE", 4.0, 4.0, 0.13)
    x_positions, y0, row_pitch = (18.0, 36.0, 54.0), 9.0, 2.75
    for row, (pulse, cutoff) in enumerate(cutoff_by_pulse):
        y = y0 + row * row_pitch
        shapes += text_shapes(f"PW{pulse}", 3.5, y + 0.18, 0.11)
        for col, factor in enumerate((0.8, 1.0, 1.2)):
            frequency = round(cutoff * factor, 1)
            x = x_positions[col]
            index = len(layers) + 1
            layers.append({"index": index, "name": f"CUTOFF-PW{pulse}-F{frequency:g}-KNEE{factor:g}X",
                           "power": 20, "frequency": frequency, "speed": 900, "pulse": pulse,
                           "interval": None, "cut_type": "Cut"})
            shapes += text_shapes(f"{frequency:g}", x + 1.0, y - 0.42, 0.10)
            shapes += lines([(x, y + 1.0, x + 10.0, y + 1.0)], index)
    # The hardware has one CW/1 ns step with no pulse-width cut-off; include a same-condition reference.
    cw_y = y0 + len(cutoff_by_pulse) * row_pitch
    shapes += text_shapes("PW1 CW", 3.5, cw_y + 0.18, 0.11)
    index = len(layers) + 1
    layers.append({"index": index, "name": "CW-1NS-REFERENCE-F48", "power": 20,
                   "frequency": 48, "speed": 900, "pulse": 1, "interval": None, "cut_type": "Cut"})
    shapes += text_shapes("48 CW REF", 19.0, cw_y - 0.42, 0.10)
    shapes += lines([(18.0, cw_y + 1.0, 28.0, cw_y + 1.0)], index)

    path = OUT / "03_titanium_pulse_cutoff_response_100mm.lbrn2"
    info = write_project(path, identifier, 76.0, 57.0, layers, shapes,
        "Pulse-width capability check for JPT YDFLP-E-60-M7-M-R. Each non-CW pulse step (2..500 ns) "
        "has three 10 mm LightBurn Line strokes at 0.8x/1.0x/1.2x the model's listed cut-off frequency. "
        "The 1 ns CW setting is included as a reference at F48 kHz. Fixed P20%, V900 mm/s and one pass. "
        "Compare whether the titanium response changes near each listed knee; the cut-off values are the "
        "device passport model, while these lines are the physical check. This plate tests pulse/frequency "
        "behavior, not color.")
    info["file"] = str(path.relative_to(OUT.parents[1]))
    info["test_layers"] = len(layers)
    return info


def feature_resolution() -> dict:
    """Measure marked-track width and the smallest visibly separated line pitch."""
    identifier = "TCE-SC-20261014-R1"
    pitches_um = (20, 30, 40, 50, 60, 80, 100, 150, 200, 300)
    layers: list[dict] = []
    shapes: list[tuple] = []
    shapes += text_shapes("LINE WIDTH / MINIMUM RESOLVED PITCH", 4.0, 1.0, 0.22)
    shapes += text_shapes("P20 F48 V2000 PW200 / 5 PARALLEL LINES PER GROUP", 4.0, 4.0, 0.14)
    x0, y0, group_x, group_y = 15.0, 14.0, 11.0, 16.5
    for i, pitch_um in enumerate(pitches_um):
        row, column = divmod(i, 5)
        x, y = x0 + column * group_x, y0 + row * group_y
        shapes += text_shapes(f"PITCH{pitch_um}UM", x - 2.0, y - 2.0, 0.095)
        pitch = pitch_um / 1000.0
        index = len(layers) + 1
        layers.append({"index": index, "name": f"RESOLUTION-PITCH{pitch_um}UM-P20-F48-V2000-PW200",
                       "power": 20, "frequency": 48, "speed": 2000,
                       "pulse": 200, "interval": None, "cut_type": "Cut"})
        shapes += lines([(x, y + j * pitch, x + 7.0, y + j * pitch) for j in range(5)], index)
    path = OUT / "04_titanium_line_resolution_100mm.lbrn2"
    info = write_project(path, identifier, 76.0, 45.0, layers, shapes,
        "Titanium track-width/resolution proxy on JPT M7 60 W with F-Theta 174 mm. Ten groups have five "
        "parallel LightBurn Line strokes at centre-to-centre pitches 20/30/40/50/60/80/100/150/200/300 um. "
        "Fixed P20%, F48 kHz, V2000 mm/s, PW200 ns and one pass. Under a calibrated microscope, measure "
        "individual track width and note the smallest pitch at which adjacent tracks remain separated. "
        "This is a material/focus/threshold-dependent mark-width proxy, not the optical beam waist; exact "
        "spot diameter requires a beam profiler or a validated burn-threshold method.")
    info["file"] = str(path.relative_to(OUT.parents[1]))
    info["test_layers"] = len(layers)
    return info


def hatch_interval() -> dict:
    """A small secondary scan-system check of hatch density, not a laser power matrix."""
    identifier = "TCE-SC-20261014-H1"
    intervals = (0.01, 0.025, 0.05, 0.1, 0.2)
    layers: list[dict] = []
    shapes: list[tuple] = []
    shapes += text_shapes("SECONDARY HATCH INTERVAL CHECK", 4.0, 1.0, 0.22)
    shapes += text_shapes("ONLY LINE SPACING CHANGES / P20 F48 V2000 PW200", 4.0, 4.0, 0.13)
    x0, y, cw, gap = 7.0, 15.0, 10.0, 2.0
    for i, interval in enumerate(intervals):
        x = x0 + i * (cw + gap)
        index = len(layers) + 1
        layers.append({"index": index, "name": f"HATCH-I{interval:g}-P20-F48-V2000-PW200",
                       "power": 20, "frequency": 48, "speed": 2000, "pulse": 200,
                       "interval": interval, "passes": 1, "global_passes": 1,
                       "bidirectional": True, "cross_hatch": False, "angle": 0, "angle_increment": 0})
        shapes += text_shapes(f"I{interval:g}MM", x + 1.0, 11.0, 0.13)
        shapes += rects([(x, y, cw, 8.0)], index)
    path = OUT / "05_titanium_hatch_interval_100mm.lbrn2"
    info = write_project(path, identifier, 76.0, 35.0, layers, shapes,
        "Secondary LightBurn Fill-mode scan check. Five 10 x 8 mm patches vary only line interval "
        "0.01/0.025/0.05/0.10/0.20 mm. Fixed P20%, F48 kHz, V2000 mm/s, PW200 ns, one sublayer/global "
        "pass, bidirectional, no cross-hatch. This compares hatch overlap/texture and scan workload; it "
        "does not determine the laser source's power or pulse limits. Use the Line plates for those.")
    info["file"] = str(path.relative_to(OUT.parents[1]))
    info["test_layers"] = len(layers)
    return info


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"power_speed_envelope": main_matrix(), "frequency_range": frequency_range(),
                      "pulse_cutoff_response": pulse_cutoff_response(), "feature_resolution": feature_resolution(),
                      "hatch_interval": hatch_interval()}, indent=2))
