"""Knowledge whose recipes come from a real-looking LightBurn file: mode, scan controls and every preserved setting.

``obs.add`` stores the six numbers only; the recipes here are read from LightBurn XML and turned into observation
parameters the way ingest does when a pair is accepted, so their recipe keys are the keys real data has.
"""
import json

from titanium_platform import lightburn as lb, setup as su
from titanium_platform.db import Store, now

# Fill with cross-hatch, angles, two passes, extra tags and a sub-layer; Line mode with wobble; Offset Fill one-way.
LIGHTBURN = b"""<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="1.7.08" FormatVersion="1" MirrorX="False" MirrorY="False">
    <CutSetting type="Scan">
        <index Value="3"/><name Value="Gold fill"/><minPower Value="10"/><maxPower Value="35"/><maxPower2 Value="35"/>
        <speed Value="1200"/><frequency Value="40000"/><QPulseWidth Value="200"/><interval Value="0.025"/><numPasses Value="2"/>
        <globalRepeat Value="1"/><bidir Value="1"/><crossHatch Value="1"/><angle Value="45"/><anglePerPass Value="10"/>
        <priority Value="5"/><tabCount Value="1"/><tabCountMax Value="1"/><floodFill Value="1"/>
        <SubLayer type="Scan" index="1"><maxPower Value="20"/><speed Value="2000"/><frequency Value="48000"/><interval Value="0.04"/></SubLayer>
    </CutSetting>
    <CutSetting type="Cut">
        <index Value="4"/><name Value="Outline"/><maxPower Value="60"/><maxPower2 Value="60"/><speed Value="300"/><frequency Value="60000"/>
        <QPulseWidth Value="100"/><interval Value="0.05"/><priority Value="2"/>
        <wobbleEnable Value="1"/><wobbleStep Value="0.05"/><wobbleSize Value="0.1"/>
    </CutSetting>
    <CutSetting type="OffsetFill">
        <index Value="7"/><name Value="Offset"/><maxPower Value="25"/><speed Value="800"/><frequency Value="30000"/><QPulseWidth Value="250"/>
        <interval Value="0.03"/><numPasses Value="1"/><bidir Value="0"/><priority Value="1"/>
    </CutSetting>
    <Shape Type="Rect" CutIndex="3" W="5" H="5"><XForm>1 0 0 1 2.5 2.5</XForm></Shape>
    <Shape Type="Rect" CutIndex="4" W="5" H="5"><XForm>1 0 0 1 8.5 2.5</XForm></Shape>
    <Shape Type="Rect" CutIndex="7" W="5" H="5"><XForm>1 0 0 1 14.5 2.5</XForm></Shape>
</LightBurnProject>
"""
NAMES = {"Gold fill": "Scan", "Outline": "Cut", "Offset": "OffsetFill"}


def parameters(layer: lb.Layer, passport: dict) -> dict:
    """The parameters an accepted observation of this layer stores (ingest.accept_pair)."""
    p = su.parameter_vector(passport, layer.power, layer.frequency_khz, layer.speed, layer.pulse_width, layer.line_interval, layer.passes)
    p.update({"layer_type": layer.layer_type, "global_passes": layer.global_passes, "bidirectional": layer.bidirectional,
              "cross_hatch": layer.cross_hatch, "scan_angle": layer.scan_angle, "angle_increment": layer.angle_increment,
              "source_settings": lb.recipe_settings(layer.source_settings)})
    return p


def recipes(passport: dict) -> dict[str, dict]:
    """Layer name -> observation parameters of the three recipes of ``LIGHTBURN``."""
    return {layer.name: parameters(layer, passport) for layer in lb.parse_bytes(LIGHTBURN).layers}


def add(store: Store, w: dict, params: dict, lab, material_id: int | None = None, spread: float = 1.0) -> None:
    """Two independent engravings of one recipe, ``spread`` apart in L around ``lab``, on one titanium stock."""
    device_id, lens_id = w["setup"]
    context = {"batch": None, "focus": None, "material_id": material_id}
    if material_id is not None:
        material = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
        context.update(titanium_name=material["name"], titanium_grade=material["grade"], titanium_thickness_mm=material["thickness_mm"],
                       titanium_surface=material["surface"])
    for dl in (-spread, spread):
        w["n"] += 1
        engraving = f"r{w['n']}"
        pair = store.execute(
            "INSERT INTO pair(status,device_id,lens_id,stand_id,material_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at)"
            " VALUES ('Accepted',?,?,?,?,?,'a.lbrn2','/x','p.raw','/y',?,'{}',?)",
            (device_id, lens_id, w["stand"]["id"], material_id, engraving, json.dumps(context), now())).lastrowid
        store.execute(
            "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
            "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pair, 1, device_id, lens_id, engraving, json.dumps([lab[0] + dl, lab[1], lab[2]]), json.dumps(params), "markers",
             json.dumps(context), 1, 1, "test", "{}", now()))
