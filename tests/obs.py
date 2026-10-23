"""Insert observations directly (bypassing photography) for model and maturity tests."""
import json

from titanium_platform import devices, lenses, tasks
from titanium_platform import setup as su
from titanium_platform.db import Store, now

_SAME = object()


def setup(store: Store, lens: bool = True) -> dict:
    """A laser with a lens installed on it and a capture rig. ``setup`` is the (device_id, lens_id) partition the
    observations below belong to by default."""
    device = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    lens_row = lenses.create_lens(store, "F-Theta 174", 174, 170) if lens else None
    if lens_row is not None:
        lenses.install(store, device["id"], lens_row["id"])
    stand = su.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    return {"device": device, "lens": lens_row, "setup": (device["id"], None if lens_row is None else lens_row["id"]),
            "stand": stand, "n": 0}


def add(store: Store, w: dict, lab, power=10, frequency=40, speed=900, engraving=None, rephoto=False,
        batch=None, focus=None, repeat_eligible=None, model_eligible=1, material_id=None,
        pulse_width=200, line_interval=0.025, passes=1, lens_id=_SAME, evidence=None, layer_type=None, task_kind=None, lightburn=None) -> int:
    w["n"] += 1
    eng = engraving or f"e{w['n']}"
    device_id = w["setup"][0]
    lens = w["setup"][1] if lens_id is _SAME else lens_id
    p = su.parameter_vector(w["device"]["passport"], power, frequency, speed, pulse_width, line_interval, passes)
    if layer_type is not None:                 # the LightBurn mode of the layer, as an imported file records it
        p["layer_type"] = layer_type
    p.update(lightburn or {})                  # other settings of the layer an imported file records (cross_hatch ...)
    context = {"batch": batch, "focus": focus, "material_id": material_id}
    if material_id is not None:
        material = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
        context.update(titanium_name=material["name"], titanium_grade=material["grade"],
                       titanium_thickness_mm=material["thickness_mm"], titanium_surface=material["surface"])
    pair = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,material_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at)"
        " VALUES ('Accepted',?,?,?,?,?,'a.lbrn2','/x','p.raw','/y',?,'{}',?)",
        (device_id, lens, w["stand"]["id"], material_id, eng, json.dumps(context), now())).lastrowid
    rep = (0 if rephoto else 1) if repeat_eligible is None else repeat_eligible
    evidence = dict(evidence or {})
    if task_kind is not None:                  # a task the operator stated for the layer, accepted with it (REQ-020)
        evidence["task"] = {**tasks.explicit(task_kind, "operator"), "mode": layer_type}
    return store.execute(
        "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
        "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at,task_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pair, 1, device_id, lens, eng, json.dumps(list(lab)), json.dumps(p), "markers", json.dumps(context),
         model_eligible, rep, "test", json.dumps(evidence), now(), task_kind)).lastrowid
