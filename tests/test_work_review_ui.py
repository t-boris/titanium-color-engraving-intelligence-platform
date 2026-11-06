"""The "Result" tab of a work, its marks in the list of works and its block in the report of a photograph (DEC-090, proposed): what the
file promised against what the engraving measured, the layers whose colour moved with a replacement offered, run in node over the small DOM
of the other screen tests with the server's real answers."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import GLUE, PAPER, TABLES, UI, by_rgb, colouring, job, lab, palette_ids, work    # noqa: F401  (fixtures)
from test_work_review import engrave, exported, moved
from titanium_platform import conversion as cv, work_errors

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context({});
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', {code: %(glue)s}, 'screens/lifecycle.js', 'screens/vector-review.js', {code: 'globalThis.VR = VectorReview;'}]);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const VR = ctx.VR, ran = [];
const run = async (op) => { ran.push(op); return true; };
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, payload, body):
    (tmp_path / "data.json").write_text(json.dumps(payload), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def reviewed(c, j):
    """The work after a file and an engraving of it whose first layer came out 9 L* darker; the pair."""
    plan = exported(c, j)
    first = plan["layers"][0]["lab"]
    pair = engrave(c, j, labs={0: [first[0] - 9, *first[1:]]})
    work_errors.after_acceptance(c["store"], pair)
    return pair


@node
def test_the_tab_shows_what_came_out_against_what_was_promised_with_both_pictures_and_the_causes_on_demand(work, job, tmp_path):
    c, j = work, job
    pair = reviewed(c, j)
    payload = c["client"].get(f"/api/vector/{j['id']}").json()
    out = run(tmp_path, {"job": payload}, """
  const view = VR.view(data.job, run);
  out.text = view.textContent;
  out.rows = view.querySelectorAll('button').filter((b) => (b.className || '').includes('vw-review-row')).map((b) => b.textContent);
  out.pictures = view.querySelectorAll('img').map((i) => i.getAttribute('src'));
  out.label = VR.tabLabel(data.job);
  await view.querySelectorAll('button').find((b) => (b.className || '').includes('vw-review-row')).dispatch('click');
  out.dialog = ctx.document.body.querySelector('.modal').textContent;
""")
    review = payload["reviews"][0]
    assert "Engraving result" in out["text"] and f"Matched {review['summary']['matched']} of {review['summary']['promised']} expected layers" in out["text"]
    assert len(out["rows"]) == review["summary"]["matched"] and out["rows"][0].find("ΔE") > 0                      # the worst layer first
    assert any("promised=true" in s for s in out["pictures"]) and any("promised=false" in s for s in out["pictures"])
    assert all(f"engraving={review['engraving_id']}" in s for s in out["pictures"]) and out["label"] == "Result"
    assert "Expected" in out["dialog"] and "Actual" in out["dialog"] and "ΔE" in out["dialog"]
    assert pair


@node
def test_a_work_with_nothing_to_compare_says_what_to_do_and_a_file_never_made_promises_nothing(work, job, tmp_path):
    payload = work["client"].get(f"/api/vector/{job['id']}").json()
    out = run(tmp_path, {"job": payload}, """
  const view = VR.view(data.job, run);
  out.text = view.textContent;
""")
    assert "No result photo has been accepted for this work yet" in out["text"] and "No file has been created from this work yet" in out["text"]


@node
def test_a_review_whose_promise_was_lost_says_so_instead_of_calling_it_another_file(work, job, tmp_path):
    c, j = work, job
    plan = exported(c, j)
    pair = engrave(c, j)
    del plan["exports"][-1]["promised"]
    cv._persist(c["store"], plan, plan["status"], plan["markers_enabled"])
    colouring(c, j, op="assign", mode="random")
    work_errors.after_acceptance(c["store"], pair)
    payload = c["client"].get(f"/api/vector/{j['id']}").json()
    listed = next(w for w in c["client"].get("/api/vector").json() if w["id"] == j["id"])
    out = run(tmp_path, {"job": payload, "listed": listed}, """
  out.text = VR.view(data.job, run).textContent;
  out.card = VR.cardLines(data.listed).map((l) => l.textContent).join(' ');
""")
    assert "cannot be reconstructed, so no comparison is available" in out["text"] and "This is a different file" not in out["text"]
    assert "expected colors were not saved" in out["card"]


@node
def test_a_file_whose_layers_match_none_of_the_works_says_it_is_another_file_and_lists_both_sides(work, job, tmp_path):
    """REQ-047 crit. 2: layers that match nothing are listed on both sides, and a file that matches no layer says so."""
    c, j = work, job
    plan = exported(c, j)
    other = {n: {**p["settings"], "speed": p["settings"]["speed"] * 2} for n, p in enumerate(plan["exports"][-1]["promised"])}
    pair = engrave(c, j, settings=other)
    work_errors.after_acceptance(c["store"], pair)
    payload = c["client"].get(f"/api/vector/{j['id']}").json()
    listed = next(w for w in c["client"].get("/api/vector").json() if w["id"] == j["id"])
    report = c["client"].get(f"/api/pairs/{pair}/report").json()
    out = run(tmp_path, {"job": payload, "listed": listed, "report": report}, """
  const view = VR.view(data.job, run);
  out.text = view.textContent;
  out.alerts = view.querySelectorAll('div').filter((d) => (d.className || '').split(' ').includes('alert')).map((d) => d.textContent);
  out.sides = view.querySelectorAll('summary').map((s) => s.textContent);
  out.pictures = view.querySelectorAll('img').length;
  out.card = VR.cardLines(data.listed).map((l) => l.textContent);
  out.report = VR.reportCard(data.report.work_review).textContent;
""")
    n = len(plan["layers"])
    assert out["alerts"] == ["No engraved file layers matched this work’s file layers by settings. This is a different file (it was edited in "
                             "LightBurn or made from another work), so there is nothing to compare."]
    assert out["sides"] == [f"Expected but not found in the photo ({n})", f"In the photo but not in the work file ({n})"] and out["pictures"] == 0
    assert "Matched" not in out["text"]
    assert out["card"] == ["Photo IMG_1.DNG: layers did not match this work’s file"]
    assert "No layers in this file matched the work file by settings." in out["report"]


@node
def test_a_moved_layer_is_listed_with_the_replacement_and_the_button_sends_an_ordinary_edit(work, job, tmp_path):
    c, j = work, job
    ids = palette_ids(c)
    fast, exact = ids[(round(lab(PAPER)[0] - 2), 3000)], ids[(round(lab(PAPER)[0]), 500)]
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    exported(c, j)
    moved(c, j, fast)
    payload = c["client"].get(f"/api/vector/{j['id']}").json()
    proposal = next(p for p in payload["attention"]["layers"][0]["proposals"] if p["entry_id"])
    payload["attention"]["layers"][0]["proposals"].append({**proposal, "colour": 99})                       # a second replacement: "apply all" is offered
    out = run(tmp_path, {"job": payload}, """
  const view = VR.view(data.job, run);
  out.text = view.textContent;
  out.label = VR.tabLabel(data.job);
  await tick();
  out.idle = ran.slice();
  await byText(view, 'button', 'Replace').dispatch('click'); await tick();
  out.one = ran.splice(0);
  await view.querySelectorAll('button').find((b) => b.textContent.startsWith('Apply all replacements')).dispatch('click'); await tick(); await tick();
  out.all = ran.splice(0);
""")
    assert "differ from the expected colors" in out["text"] and out["label"] == "Result · ⚠ 1"
    assert out["idle"] == []                                                         # REQ-047 crit. 7: shown, nothing applied until pressed
    assert out["one"] == [{"op": "set_colour", "colour": proposal["colour"], "entry_id": exact}]
    assert [op["colour"] for op in out["all"]] == [proposal["colour"], 99] and all(op["entry_id"] == exact for op in out["all"])
    assert "The engraved file stays unchanged" in out["text"]


@node
def test_the_list_and_the_report_carry_the_conclusion(work, job, tmp_path):
    c, j = work, job
    pair = reviewed(c, j)
    listed = next(w for w in c["client"].get("/api/vector").json() if w["id"] == j["id"])
    report = c["client"].get(f"/api/pairs/{pair}/report").json()
    out = run(tmp_path, {"listed": listed, "report": report}, """
  out.lines = VR.cardLines(data.listed).map((p) => p.textContent);
  const card = VR.reportCard(data.report.work_review);
  out.card = card.textContent;
  out.link = card.querySelectorAll('a').map((a) => a.getAttribute('href'));
  out.none = VR.reportCard(null);
""")
    assert any("Engraving result (IMG_1.DNG)" in line for line in out["lines"])
    assert f"Finding for work “{job['name']}”" in out["card"] and out["link"] == [f"#/vector?plan={j['id']}"] and out["none"] is None


@node
def test_the_card_of_a_work_in_the_list_warns_of_the_layers_whose_colour_moved_and_says_nothing_when_none_did(work, job, tmp_path):
    """REQ-047 crit. 6: the counts kept after new measurements are shown in the list of works."""
    c, j = work, job
    fast = palette_ids(c)[(round(lab(PAPER)[0] - 2), 3000)]
    j = colouring(c, j, op="set_colour", colour=by_rgb(j, PAPER)["index"], entry_id=fast)
    exported(c, j)
    work_errors.after_change(c["store"], c["w"]["setup"][0], c["w"]["setup"][1])
    still = next(w for w in c["client"].get("/api/vector").json() if w["id"] == j["id"])
    moved(c, j, fast)
    work_errors.after_change(c["store"], c["w"]["setup"][0], c["w"]["setup"][1])
    listed = next(w for w in c["client"].get("/api/vector").json() if w["id"] == j["id"])
    out = run(tmp_path, {"listed": listed, "still": still}, """
  out.lines = VR.cardLines(data.listed).map((p) => [p.className, p.textContent]);
  out.still = VR.cardLines(data.still).map((p) => p.textContent);
""")
    share = math.floor(listed["attention"]["area_share"] * 100 + 0.5)                                    # as Math.round rounds it
    assert listed["attention"]["layers"] == 1 and still["attention"]["layers"] == 0
    assert out["lines"] == [["small vw-bad", f"⚠ 1 layer colors differ from the file’s expected colors ({share} % of area)"]]
    assert out["still"] == []


UPLOAD = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', 'filepick.js', 'tasks.js', 'screens/material-picker.js', 'screens/ingest-upload.js', {code: 'globalThis.IU = IngestUpload;'}]);
(async () => {
  const out = {};
  const tree = await ctx.IU.render({query: data.query}, data.lists, []);
  for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 0));
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""
LISTS = {"devices": [{"id": 1, "name": "Laser A", "title": "Laser A", "lens": None}, {"id": 5, "name": "Laser B", "title": "Laser B", "lens": None}],
         "lenses": [{"id": 2, "name": "F-theta 160", "focal_length_mm": 160}, {"id": 3, "name": "F-theta 254", "focal_length_mm": 254}]}


def upload_form(tmp_path, query, plan, body):
    stock = {"/api/materials/1": {"status": 200, "json": {"id": 1, "name": "Ti sheet", "grade": "Grade 2"}},            # the stock selector reads the one record it shows
             "/api/materials/4": {"status": 200, "json": {"id": 4, "name": "Ti rod", "grade": "Grade 5"}}}
    data = {"query": query, "lists": LISTS, "routes": {**stock, **({"/api/plans/22": {"status": 200, "json": plan}} if plan else {})}}
    (tmp_path / "upload.json").write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "upload.js"
    script.write_text(UPLOAD % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "upload.json")),
                                "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


FORM_BODY = """
  out.banner = tree.querySelectorAll('div').filter((d) => (d.className || '').split(' ').includes('alert')).map((d) => d.textContent);
  out.links = tree.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  const selects = tree.querySelectorAll('select');
  out.laser = selects.find((s) => s.getAttribute('aria-label') === 'Laser').value;
  out.lens = selects.find((s) => s.getAttribute('aria-label') === 'Lens').value;
  out.titanium = tree.querySelectorAll('.matpick').find((p) => p.getAttribute('aria-label') === 'Titanium / sheet / batch used').value;      // the stock selector, named by its visible label
"""


@node
def test_the_link_on_the_result_tab_opens_the_upload_form_for_this_work_with_its_laser_lens_and_titanium(work, job, tmp_path):
    payload = work["client"].get(f"/api/vector/{job['id']}").json()
    out = run(tmp_path, {"job": payload}, """
  out.hrefs = VR.view(data.job, run).querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
""")
    assert ["Upload a photo for this work", f"#/ingest?plan={job['id']}&material={payload['material_id']}"] in out["hrefs"]
    reviewed(work, job)
    payload = work["client"].get(f"/api/vector/{job['id']}").json()
    out = run(tmp_path, {"job": payload}, """
  out.hrefs = VR.view(data.job, run).querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
""")
    assert out["hrefs"].count(["Upload a photo for this work", f"#/ingest?plan={job['id']}&material={payload['material_id']}"]) == 1


@node
def test_the_upload_form_opened_for_a_work_names_it_and_takes_its_laser_lens_and_titanium(tmp_path):
    plan = {"id": 22, "name": "Inna + Boris", "mode": "Vector job", "device_id": 5, "lens_id": 3, "material_id": 4}
    out = upload_form(tmp_path, {"plan": "22", "material": "4"}, plan, FORM_BODY)
    assert any("Photo for work «Inna + Boris»" in text for text in out["banner"]), out["banner"]
    assert ["«Inna + Boris»", "#/vector?plan=22"] in out["links"]
    assert (out["laser"], out["lens"], out["titanium"]) == ("5", "3", "4")


@node
def test_the_upload_form_without_a_work_or_for_a_plate_says_nothing_about_a_work(tmp_path):
    out = upload_form(tmp_path, {}, None, FORM_BODY)
    assert out["banner"] == [] and not any(href.startswith("#/vector") for _, href in out["links"])
    plate = {"id": 22, "name": "Plate", "mode": "Laser capability test", "device_id": 5, "lens_id": 3}
    out = upload_form(tmp_path, {"plan": "22"}, plate, FORM_BODY)
    assert out["banner"] == [] and (out["laser"], out["lens"]) == ("5", "3")
