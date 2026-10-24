"""Transfer experiments (electron REQ-085): a colour of a connected release is checked on the own laser as an own one-cell plate with
the release's complete recipe, linked to the release and its observations; the own laser's limits are checked first and settings it
cannot take are refused; what the plate's photograph measures keeps the own laser, lens and titanium, is compared with the release's
colour by ΔE, and neither changes the author's observation nor counts up its independent engravings."""
import json

import cv2

import synth
from test_grey_scales import app_world  # noqa: F401
from test_lab_sources import lab, world  # noqa: F401
from titanium_platform import devices, ingest as ig, lightburn as lb, plans as pl
from titanium_platform import setup as su


def checked_colour(lab):  # noqa: F811
    palette = lab["client"].post("/api/labs/palette", json=lab["source"]).json()
    return max(palette["entries"], key=lambda e: e["engravings"])


def test_a_colour_of_a_release_is_checked_on_the_own_laser_and_compared_by_delta_e(lab):  # noqa: F811
    client, store = lab["client"], lab["store"]
    entry = checked_colour(lab)
    ask = {**lab["source"], "entry_id": entry["id"], "device_id": lab["laser"]["id"], "material_id": lab["titanium"]["id"]}
    assert client.post("/api/labs/transfers", json=ask).json()["error"].startswith("set the marker layer")
    pl.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    answer = client.post("/api/labs/transfers", json=ask)
    assert answer.status_code == 201, answer.text
    made = answer.json()
    transfer = made["transfer"]
    assert transfer["release_id"] == lab["first"]["release_id"] and transfer["entry_id"] == entry["id"] and transfer["observations"]
    assert transfer["source"]["lab"] == entry["lab"] and transfer["recipe"] == entry["recipe"] and made["cells"] == 1
    plan = pl.get_plan(store, made["plan_id"])
    data = client.get(f"/api/plans/{made['plan_id']}/export.lbrn2").content
    [cell] = [layer for layer in lb.parse_bytes(data).layers if layer.name == plan["layers"][0]["name"]]
    assert cell.power == entry["recipe"]["power"] and cell.speed == entry["recipe"]["speed"]          # the release's recipe, whole

    store.set_setting("allow_non_raw_photos", True)
    stand = su.save_capture_setup(store, "Own rig", "cam", "LED", "90", "ColorChecker Classic")
    photo = synth.plate_photo(plan, {plan["layers"][0]["cell_id"]: (150, 110, 60)})
    pair = ig.create_pair(store, device_id=lab["laser"]["id"], lens_id=None, stand_id=stand["id"], lightburn_name="transfer.lbrn2",
                          lightburn_bytes=data, photo_name="transfer.png", photo_bytes=cv2.imencode(".png", photo)[1].tobytes(),
                          context={"material_id": lab["titanium"]["id"]})
    assert ig.check_pair(store, pair)["problems"] == []
    ig.review_masks(store, pair)
    ig.accept_pair(store, pair)
    compared = client.get(f"/api/labs/transfers/{made['plan_id']}").json()
    [measured] = compared["measurements"]
    assert measured["device_id"] == lab["laser"]["id"] and measured["material_id"] == lab["titanium"]["id"] and measured["lens_id"] is None
    assert measured["delta_e"] > 0 and compared["mean_delta_e"] == measured["delta_e"]
    assert [t["plan_id"] for t in client.get("/api/labs/transfers", params={"release_id": lab["first"]["release_id"]}).json()] == [made["plan_id"]]
    after = {e["id"]: e for e in client.post("/api/labs/palette", json=lab["source"]).json()["entries"]}
    assert after[entry["id"]]["engravings"] == entry["engravings"] and after[entry["id"]]["lab"] == entry["lab"]   # the author's, as it was


def test_settings_the_own_laser_cannot_take_are_refused_and_nothing_is_made(lab):  # noqa: F811
    store = lab["store"]
    entry = checked_colour(lab)
    narrow = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="Shorter pulses", serial="OWN-3")
    passport = devices.brief(store, narrow["id"])["passport"]
    passport["pulse_steps"] = [s for s in passport["pulse_steps"] if s["pulse_width_ns"] < entry["recipe"]["pulse_width"]]
    store.execute("UPDATE laser_device SET data_json=? WHERE id=?", (json.dumps(passport), narrow["id"]))
    plans = store.one("SELECT COUNT(*) AS n FROM plan")["n"]
    refused = lab["client"].post("/api/labs/transfers", json={**lab["source"], "entry_id": entry["id"], "device_id": narrow["id"],
                                                                "material_id": lab["titanium"]["id"]})
    assert refused.status_code == 422 and "has settings this laser cannot take: pulse width" in refused.json()["error"]
    assert store.one("SELECT COUNT(*) AS n FROM plan")["n"] == plans
    unknown = lab["client"].post("/api/labs/transfers", json={**lab["source"], "entry_id": "nothing", "device_id": lab["laser"]["id"],
                                                                "material_id": lab["titanium"]["id"]})
    assert unknown.status_code == 422 and unknown.json()["error"] == "choose a colour of this release's palette to check on this laser"
