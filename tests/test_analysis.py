import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

import obs
from test_vector_work import TABLES, UI
from titanium_platform import analysis as an, color, conversion as cv, ingest as ig, knowledge as kn, plans as pl, setup as su
from titanium_platform.db import now

LIGHTNESS = {10: 20.0, 20: 40.0, 30: 60.0, 40: 80.0}


@pytest.fixture
def w(store):
    w = obs.setup(store)
    setup = w["setup"]
    su.save_rules(store, *setup, repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    su.save_rules(store, *setup, criteria_agreed=True)
    for power, l in LIGHTNESS.items():
        for dl in (-1.0, 1.0):
            obs.add(store, w, (l + dl, 0.0, 0.0), power=power)
    kn.refresh(store, *setup)
    w["ids"] = {k["parameters"]["power"]: k["id"] for k in kn.list_for_setup(store, *setup)}
    return w


def ramp() -> bytes:
    return cv2.imencode(".png", np.tile(np.linspace(0, 255, 100).astype(np.uint8), (20, 1)))[1].tobytes()


def accepted_pair(store, w, plan_id, measured: dict, alignment="markers", batch=None, focus=None) -> int:
    """An accepted pair for ``plan_id`` whose layers were measured as ``measured`` (layer index -> Lab)."""
    pair = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,plan_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at,accepted_at)"
        " VALUES ('Accepted',?,?,?,?,?,'a.lbrn2','/x','p.raw','/y',?,'{}',?,?)",
        (*w["setup"], w["stand"]["id"], plan_id, f"eng-{plan_id}", json.dumps({"batch": batch, "focus": focus}), now(), now())).lastrowid
    plan = pl.get_plan(store, plan_id)
    by_index = {l["index"]: l for l in plan["layers"]}
    for idx, lab in measured.items():
        store.execute(
            "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,repeat_eligible,"
            "eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,1,1,'t',?,?)",
            (pair, idx, *w["setup"], f"eng-{plan_id}", json.dumps(list(lab)), json.dumps(by_index[idx]["parameters"]), alignment,
             json.dumps({"batch": batch, "focus": focus}), json.dumps({"layer_name": by_index[idx]["name"]}), now()))
    return pair


def test_the_report_needs_an_accepted_pair(store, w):
    pid = cv.create_continuous(store, *w["setup"], "tonal", ramp(), 50, 4, "T")
    pending = store.execute("INSERT INTO pair(status,device_id,lens_id,stand_id,plan_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at)"
                            " VALUES ('Ready to accept',?,?,?,?,'x','a','/x','p','/y','{}','{}',?)", (*w["setup"], w["stand"]["id"], pid, now())).lastrowid
    with pytest.raises(ig.IngestError, match="accepted pair"):
        an.report_for_pair(store, pending)


def test_tonal_reports_brightness_and_contrast_from_hand_computed_values(store, w):
    plan_id = cv.create_continuous(store, *w["setup"], "tonal", ramp(), 50, 4, "T")
    # planned L per band: 20, 40, 60, 80 ; measured: 22, 38, 63, 75
    pair = accepted_pair(store, w, plan_id, {1: (22, 0, 0), 2: (38, 0, 0), 3: (63, 0, 0), 4: (75, 0, 0)})
    r = an.report_for_pair(store, pair)
    m = r["metrics"]
    assert m["kind"] == "brightness_contrast" and m["bands"] == 4
    assert m["planned_contrast"] == pytest.approx(60.0) and m["measured_contrast"] == pytest.approx(53.0)
    assert m["mean_abs_delta_l"] == pytest.approx((2 + 2 + 3 + 5) / 4) and m["monotonic"] is True
    assert [round(x["delta_l"], 6) for x in r["rows"]] == [2.0, -2.0, 3.0, -5.0]
    assert r["rows"][0]["planned_prediction"]["confidence"] is not None  # the plan's prediction is kept beside the measurement


def test_a_non_monotonic_tonal_result_is_reported_as_such(store, w):
    plan_id = cv.create_continuous(store, *w["setup"], "tonal", ramp(), 50, 4, "T")
    pair = accepted_pair(store, w, plan_id, {1: (22, 0, 0), 2: (60, 0, 0), 3: (50, 0, 0), 4: (75, 0, 0)})
    assert an.report_for_pair(store, pair)["metrics"]["monotonic"] is False


def test_color_path_reports_delta_e_and_distance_from_the_trajectory(store, w):
    ids = [w["ids"][10], w["ids"][40]]   # a straight line in Lab from L=20 to L=80 (a=b=0)
    plan_id = cv.create_continuous(store, *w["setup"], "color_path", ramp(), 50, 2, "P", path_ids=ids)
    plan = pl.get_plan(store, plan_id)
    assert [l["parameters"]["power"] for l in plan["layers"]] == [10, 40]
    # band 1 planned (20,0,0) measured (23,4,0): dE 5, distance to the line (a=4) 4
    # band 2 planned (80,0,0) measured (80,0,3): dE 3, distance to the line 3
    pair = accepted_pair(store, w, plan_id, {1: (23, 4, 0), 2: (80, 0, 3)})
    m = an.report_for_pair(store, pair)["metrics"]
    assert m["kind"] == "delta_e_along_path"
    assert m["mean_delta_e"] == pytest.approx(4.0) and m["max_delta_e"] == pytest.approx(5.0)
    assert m["mean_path_distance"] == pytest.approx(3.5) and m["max_path_distance"] == pytest.approx(4.0)


def test_discrete_reports_color_deviation_and_classifies_only_with_a_saved_tolerance(store, w):
    rgb = tuple(int(v) for v in color.lab_to_srgb8((40, 0, 0)))
    png = cv2.imencode(".png", np.full((20, 40, 3), rgb[::-1], np.uint8))[1].tobytes()
    plan_id = cv.start_discrete(store, *w["setup"], png, 40, "D", threshold=10.0)
    cv.finalize_discrete(store, plan_id)
    planned = pl.get_plan(store, plan_id)["layers"][0]["prediction"]["lab"]
    pair = accepted_pair(store, w, plan_id, {1: (planned[0] + 4, planned[1] + 3, planned[2])})
    r = an.report_for_pair(store, pair)
    assert r["metrics"]["kind"] == "color_deviation" and r["metrics"]["max_delta_e"] == pytest.approx(5.0)
    assert r["rows"][0]["within_tolerance"] is True  # tolerance 6.0 saved in the fixture
    su.save_rules(store, *w["setup"], delta_tolerance=4.0)
    assert an.report_for_pair(store, pair)["rows"][0]["within_tolerance"] is False


def test_without_a_saved_tolerance_deviations_are_not_classified(store):
    w = obs.setup(store)
    plan_id = pl.create_plate_series  # noqa: F841 - not needed; build a plan row directly
    store.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,band_count,data_json,created_at) VALUES ('p',?,?,?,?,0,NULL,?,?)",
                  (pl.MODE_DISCRETE, "Ready to export", *w["setup"], json.dumps({"layers": [{"index": 1, "name": "K1", "parameters": su.parameter_vector(w["device"]["passport"], 10, 40, 900, 200, 0.025, 1),
                   "regions": [], "prediction": {"lab": [50, 0, 0], "confidence": .5, "expected_delta_e": 1.0, "stability": {"assessed": True}}}]}), now()))
    pair = accepted_pair(store, w, 1, {1: (52, 0, 0)})
    r = an.report_for_pair(store, pair)
    assert r["rows"][0]["delta_e"] == pytest.approx(2.0) and r["rows"][0]["within_tolerance"] is None
    assert any("no delta E tolerance" in x for x in r["limitations"])


def test_a_pair_without_a_plan_reports_measurements_and_says_what_is_missing(store, w):
    pair = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at,accepted_at)"
        " VALUES ('Accepted',?,?,?,'e','a','/x','p','/y','{}','{}',?,?)", (*w["setup"], w["stand"]["id"], now(), now())).lastrowid
    store.execute("INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,repeat_eligible,"
                  "eligibility_reason,evidence_json,created_at) VALUES (?,1,?,?,'e',?,?,'manual','{}',1,1,'t','{}',?)",
                  (pair, *w["setup"], json.dumps([50, 0, 0]), json.dumps(su.parameter_vector(w["device"]["passport"], 10, 40, 900, 200, 0.025, 1)), now()))
    r = an.report_for_pair(store, pair)
    assert r["mode"] is None and r["rows"][0]["planned_lab"] is None and r["rows"][0]["delta_e"] is None
    text = " | ".join(r["limitations"])
    assert "no original plan" in text and "aligned manually" in text


def test_limitations_state_when_unknown_context_blocks_attribution(store, w):
    plan_id = cv.create_continuous(store, *w["setup"], "tonal", ramp(), 50, 4, "T")
    obs.add(store, w, (21, 0, 0), power=10, batch="B1", focus=0.0)   # one repeat with known context, the rest unknown
    pair = accepted_pair(store, w, plan_id, {1: (22, 0, 0)}, batch=None, focus=None)
    text = " | ".join(an.report_for_pair(store, pair)["limitations"])
    assert "cannot be attributed to material batch or focus" in text


def photograph(store, w, engraving: str, measured: dict, mode="reference_chart_corrected") -> int:
    """An accepted photograph of ``engraving`` whose layers were measured as ``measured`` (layer index -> Lab)."""
    pair = store.execute(
        "INSERT INTO pair(status,device_id,lens_id,stand_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,data_json,created_at,accepted_at)"
        " VALUES ('Accepted',?,?,?,?,'a.lbrn2','/x','p.raw','/y','{}','{}',?,?)", (*w["setup"], w["stand"]["id"], engraving, now(), now())).lastrowid
    parameters = json.dumps(su.parameter_vector(w["device"]["passport"], 10, 40, 900, 200, 0.025, 1))
    for idx, lab in measured.items():
        store.execute(
            "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,model_eligible,repeat_eligible,"
            "eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,'markers','{}',?,0,'t',?,?)",
            (pair, idx, *w["setup"], engraving, json.dumps(list(lab)), parameters, int(mode == "reference_chart_corrected"),
             json.dumps({"layer_name": f"C{idx:02d}", "role": "test feature", "color_measurement": {"mode": mode}}), now()))
    return pair


def test_the_report_of_a_rephotographed_engraving_gives_the_repeatability_of_the_rig(store, w):
    """REQ-009: the rig's repeatability, from chart-corrected photographs of the same engraving only."""
    photograph(store, w, "E", {1: (50, 0, 0), 2: (30, 10, 0)})
    again = photograph(store, w, "E", {1: (52, 0, 0), 2: (30, 10, 2)})
    photograph(store, w, "E", {1: (90, 0, 0), 2: (10, 0, 0)}, mode="raw_camera_relative")     # a view without a chart is never compared
    report = an.report_for_pair(store, again)
    assert len(report["photos"]) == 3
    assert report["rig_repeatability"] == {"assessed": True, "photos": 2, "layers": 2,
                                           "mean_delta_e": pytest.approx(1.0), "max_delta_e": pytest.approx(1.0)}
    single = photograph(store, w, "F", {1: (50, 0, 0)})
    assert an.report_for_pair(store, single)["rig_repeatability"] == {"assessed": False, "photos": 1, "layers": 0,
                                                                     "mean_delta_e": None, "max_delta_e": None}


def test_the_report_never_changes_stored_measurements(store, w):
    plan_id = cv.create_continuous(store, *w["setup"], "tonal", ramp(), 50, 4, "T")
    pair = accepted_pair(store, w, plan_id, {1: (22, 0, 0), 2: (38, 0, 0)})
    before = [tuple(r) for r in store.query("SELECT id, lab_json, parameters_json FROM observation ORDER BY id")]
    an.report_for_pair(store, pair)
    assert before == [tuple(r) for r in store.query("SELECT id, lab_json, parameters_json FROM observation ORDER BY id")]


def test_the_trajectory_is_the_one_planned_not_one_moved_by_the_result_being_judged(store, w):
    """Regression: the path used to be read from live knowledge, which already contained the measurement."""
    ids = [w["ids"][10], w["ids"][40]]
    plan_id = cv.create_continuous(store, *w["setup"], "color_path", ramp(), 50, 2, "P", path_ids=ids)
    stored = [p["lab"] for p in pl.get_plan(store, plan_id)["transfer"]["points"]]
    assert stored == [pytest.approx([20, 0, 0]), pytest.approx([80, 0, 0])]
    pair = accepted_pair(store, w, plan_id, {1: (23, 4, 0), 2: (80, 0, 3)})
    kn.refresh(store, *w["setup"])
    live = kn.get(store, w["ids"][10])["summary"]["lab"]
    assert live != pytest.approx([20, 0, 0])  # live knowledge has moved because of the new observation ...
    m = an.report_for_pair(store, pair)["metrics"]
    assert m["max_path_distance"] == pytest.approx(4.0)  # ... but the report still measures against the plan
    assert pl.get_plan(store, plan_id)["transfer"]["points"][0]["lab"] == pytest.approx([20, 0, 0])


# -- the analysis screen in node over the small DOM, with the report the server builds ------------------------------------------
SCREEN = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'tasks.js', 'screens/vector-review.js', {code: %(glue)s}, 'screens/analysis.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
(async () => {
  const out = {};
  const screen = async () => { const t = await ctx.__screens.analysis.render({arg: String(data.id), query: {}}); for (let i = 0; i < 4; i++) await tick(); return t; };
  const tree = await screen();
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""
SCREEN_GLUE = ("const __screens = {}, __session = {}; App.register = (d) => { __screens[d.id] = d; }; App.render = () => {};"
               "globalThis.sessionStorage = {getItem: (k) => (k in __session ? __session[k] : null), setItem: (k, v) => { __session[k] = String(v); }};"
               "globalThis.__screens = __screens;")


def run_screen(tmp_path, pair_id, report, body, routes=None) -> dict:
    routes = {f"/api/pairs/{pair_id}/report": {"status": 200, "json": report}, **(routes or {})}
    (tmp_path / "data.json").write_text(json.dumps({"id": pair_id, "routes": routes}), encoding="utf-8")
    script = tmp_path / "analysis.js"
    script.write_text(SCREEN % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(SCREEN_GLUE), "body": body},
                      encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_measured_elements_are_a_short_list_out_of_tolerance_and_largest_delta_e_first_with_the_measurements_under_a_line(store, w, tmp_path):
    """findings-you-can-manage-short-lists-re-check REQ-005: a plate of 25 bands is a page of 20 lines (colour, name, ΔE to the planned
    colour, «вне допуска»), the ones out of the saved tolerance (6.0) first, then the largest ΔE; the measurements and the settings of a
    band open under its line; a chip keeps only those out of tolerance; «По порядку» puts them back in band order."""
    plan_id = cv.create_continuous(store, *w["setup"], "tonal", ramp(), 50, 25, "T")
    layers = pl.get_plan(store, plan_id)["layers"]
    off = {l["index"]: (l["index"] * 7 % 25) / 5 for l in layers} | {9: 8.0, 16: 7.0}          # ΔE of each band; 9 and 16 out of tolerance
    pair = accepted_pair(store, w, plan_id, {l["index"]: (l["prediction"]["lab"][0] + off[l["index"]], 0, 0) for l in layers})
    out = run_screen(tmp_path, pair, an.report_for_pair(store, pair), """
  const panel = tree.querySelectorAll('section').find((s) => s.querySelector('h3') && s.querySelector('h3').textContent === 'Измеренные элементы');
  const list = panel.querySelector('.lst');
  const names = () => list.querySelectorAll('.lst-text').map((x) => x.textContent);
  out.names = names();
  out.count = list.querySelector('.lst-count').textContent;
  out.more = list.querySelector('.lst-foot').querySelector('button').textContent;
  out.first = list.querySelectorAll('.lst-main')[0].textContent;
  out.third = list.querySelectorAll('.lst-main')[2].textContent;
  out.chips = list.querySelectorAll('.lst-chip').map((c) => c.textContent);
  out.tiles = tree.querySelectorAll('button').filter((b) => (b.className || '').includes('analysis-module')).length;
  await list.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  out.open = list.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  await list.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith('Вне допуска')).dispatch('click'); await tick();
  out.outside = names();
  await list.querySelectorAll('.lst-chip')[0].dispatch('click'); await tick();
  const order = list.querySelector('select'); order.value = 'order'; await order.dispatch('change'); await tick();
  out.ordered = names().slice(0, 3);
""")
    assert len(out["names"]) == 20 and out["count"] == "показано 20 из 25" and out["more"] == "Показать ещё 5" and out["tiles"] == 0
    # out of tolerance first (B09 ΔE 8, B16 ΔE 7), then the largest ΔE: B07 4.8, B14 4.6, B21 4.4, B03 4.2
    assert out["names"][:6] == ["B09", "B16", "B07", "B14", "B21", "B03"]
    assert "ΔE 8.0" in out["first"] and "вне допуска" in out["first"] and "ΔE 4.8" in out["third"] and "вне допуска" not in out["third"]
    assert out["chips"] == ["Все · 25", "Вне допуска · 2", "Без замечаний · 23"]                   # no element went unmeasured: no chip for it
    assert len(out["open"]) == 1 and "Плановый цвет" in out["open"][0] and "ΔE 8.0" in out["open"][0] and "Прочитанные параметры слоя" in out["open"][0]
    assert out["outside"] == ["B09", "B16"] and out["ordered"] == ["B01", "B02", "B03"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_layer_the_operator_took_out_says_so_on_its_line_and_gives_it_back(store, w, tmp_path):
    """act-on-findings REQ-001: the photo page marks a measured layer the operator took out of every calculation, says why under its line
    and offers «Вернуть», which undoes the decision."""
    from titanium_platform import exclusions
    plan_id = cv.create_continuous(store, *w["setup"], "tonal", ramp(), 50, 3, "T")
    layers = pl.get_plan(store, plan_id)["layers"]
    pair = accepted_pair(store, w, plan_id, {l["index"]: (l["prediction"]["lab"][0], 0, 0) for l in layers})
    second = next(r for r in an.report_for_pair(store, pair)["rows"] if r["name"] == "B02")
    x = exclusions.exclude_measurement(store, second["observation_id"], note="блик")["exclusion"]
    report = an.report_for_pair(store, pair)
    assert [r["taken_out"]["id"] if r["taken_out"] else None for r in sorted(report["rows"], key=lambda r: r["layer_index"])] == [None, x["id"], None]
    out = run_screen(tmp_path, pair, report, """
  const panel = tree.querySelectorAll('section').find((s) => s.querySelector('h3') && s.querySelector('h3').textContent === 'Измеренные элементы');
  const list = panel.querySelector('.lst');
  const line = list.querySelectorAll('.lst-row').find((r) => r.querySelector('.lst-text').textContent === 'B02');
  out.cls = line.className;
  out.main = line.querySelector('.lst-main').textContent;
  out.buttons = list.querySelectorAll('.lst-act').map((a) => a.querySelectorAll('button').map((b) => b.textContent)).filter((b) => b.length);
  await line.querySelector('.lst-main').dispatch('click'); await tick();
  out.open = list.querySelectorAll('.lst-det').find((d) => !d.hidden).querySelector('p').textContent;
  await line.querySelector('.lst-act').querySelector('button').dispatch('click'); await tick(); await tick();
  out.sent = ctx.requests.filter((r) => r.path === '/api/exclusions/%(id)s/revoke').map((r) => r.method);
""" % {"id": x["id"]}, routes={f"/api/exclusions/{x['id']}/revoke": {"status": 200, "json": {"exclusion": {"id": x["id"]}, "run_id": 9}}})
    assert "excluded" in out["cls"] and out["main"].endswith("убрано из расчёта оператором")
    assert out["buttons"] == [["Вернуть"]]                                          # only the taken-out line has an action
    assert out["open"].startswith("Убрано из расчёта оператором ") and "(«блик»): этот слой не считается в рецепте" in out["open"]
    assert out["sent"] == ["POST"]
