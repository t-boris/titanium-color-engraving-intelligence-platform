"""Insert observations directly (bypassing photography) for model and maturity tests."""
import json

from titanium_platform import profiles as pf
from titanium_platform.db import Store, now


def setup(store: Store) -> dict:
    profile = pf.create_profile(store, "MOPA", 200, 0.025, 1)
    stand = pf.save_capture_setup(store, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    return {"profile": profile, "stand": stand, "n": 0}


def add(store: Store, w: dict, lab, power=10, frequency=40, speed=900, engraving=None, rephoto=False,
        batch=None, focus=None, repeat_eligible=None, model_eligible=1) -> int:
    w["n"] += 1
    eng = engraving or f"e{w['n']}"
    p = pf.parameter_vector(w["profile"], power, frequency, speed)
    pair = store.execute(
        "INSERT INTO pair(status,profile_id,stand_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at)"
        " VALUES ('Accepted',?,?,?,'a.lbrn2','/x','p.raw','/y',?,'{}',?)",
        (w["profile"]["id"], w["stand"]["id"], eng, json.dumps({"batch": batch, "focus": focus}), now())).lastrowid
    rep = (0 if rephoto else 1) if repeat_eligible is None else repeat_eligible
    return store.execute(
        "INSERT INTO observation(pair_id,layer_index,profile_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
        "model_eligible,repeat_eligible,eligibility_reason,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (pair, 1, w["profile"]["id"], eng, json.dumps(list(lab)), json.dumps(p), "markers", json.dumps({"batch": batch, "focus": focus}),
         model_eligible, rep, "test", now())).lastrowid
