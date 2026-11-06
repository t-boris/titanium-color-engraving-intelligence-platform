"""«Новая векторная работа» and the delta E tolerance (0.22.4): the tolerance is never invented, so the form shows at once whether the
rules of the chosen laser and lens hold one; with none it asks for it before anything is sent and saves the typed value to the rules
(«Запомнить», on by default); with one it names it and a typed value is for the work only. Run in node over the small DOM of the
other screen tests."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import GLUE, TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

FORM_DATA = "globalThis.FormData = class { constructor() { this.items = []; } append(k, v) { this.items.push([k, String(v)]); } };"
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', 'filepick.js', 'tasks.js', 'photo-modes.js', 'photo-quality.js', {code: %(glue)s}, 'screens/vector-split.js', 'screens/vector-photo.js', 'screens/lettering.js',
  'screens/vector-editor.js', 'screens/vector-colours.js', 'screens/lifecycle.js', 'screens/vector-review.js', 'screens/vector-workspace.js', 'screens/lab-source.js', 'screens/evidence-summary.js', 'screens/material-picker.js', 'screens/vector.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
(async () => {
  const out = {};
  const tree = await ctx.__screens.vector.render({query: {new: '1', classic: '1'}});
  await tick(); await tick();
  const field = tree.querySelectorAll('div').find((d) => d.classList.contains('f') && (d.querySelector('span') || {}).textContent === 'ΔE tolerance');
  const thr = field.querySelector('input');
  const remember = field.querySelectorAll('label').find((l) => l.classList.contains('row'));
  const sent = () => ctx.requests.filter((r) => r.method !== 'GET').map((r) => [r.method, r.path, typeof r.body === 'string' ? JSON.parse(r.body) : r.body.items]);
  out.shown = [thr.getAttribute('placeholder'), thr.getAttribute('aria-invalid'), field.textContent, remember.hidden];
  const stockOf = () => tree.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === 'Titanium').textContent;
  const labelled = (text) => tree.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === text);
  const strategy = labelled('Strategy').firstControl();
  out.stock = [stockOf()];
  strategy.value = 'fill'; await strategy.dispatch('change'); out.stock.push(stockOf());
  strategy.value = 'photo'; await strategy.dispatch('change'); await tick();
  tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file').files = [{name: 'Inna Portrait.jpg'}];
  labelled('Work name').firstControl().value = 'Inna Portrait';                  // the plan's name is required (conversion: «give the plan a name»)
  await byText(tree, 'button', 'Create work').dispatch('click'); await tick();
  out.empty = [labelled('ΔE tolerance').errorText(), sent(), thr.getAttribute('aria-invalid'), tree.querySelectorAll('p').find((p) => p.getAttribute('role') === 'alert').textContent];
  thr.value = '5'; await thr.dispatch('input');
  out.typed = thr.getAttribute('aria-invalid');
  await byText(tree, 'button', 'Create work').dispatch('click'); await tick(); await tick();
  out.created = sent();
  out.after = [thr.getAttribute('placeholder'), remember.hidden];
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def routes(tolerance) -> dict:
    ok = lambda body, status=200: {"status": status, "json": body}  # noqa: E731
    return {"/api/devices": ok([{"id": 1, "name": "JPT", "title": "JPT YDFLP-E-60", "lens": {"id": 2}}]),
            "/api/lenses": ok([{"id": 2, "kind": "F-Theta", "focal_length_mm": 174}]),
            "/api/materials": ok([{"id": 3, "name": "Small Plate", "grade": "Grade 5", "batch": "Chineese order"}]),
            "/api/vector-palette": ok({"entries": []}),
            "/api/rules": ok({"repeat_threshold": None, "delta_tolerance": tolerance, "variance_threshold": None, "criteria_agreed": False}),
            "/api/vector": ok({"id": 99}, 201)}


def run(tmp_path, tolerance) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes(tolerance)}), encoding="utf-8")
    script = tmp_path / "form.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE + FORM_DATA)}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@node
def test_with_no_tolerance_saved_the_form_asks_for_it_first_and_saves_the_typed_one_to_the_rules(tmp_path):
    out = run(tmp_path, None)
    placeholder, invalid, text, hidden = out["shown"]
    assert placeholder == "enter value" and invalid == "true" and hidden is False
    assert "No tolerance is saved for this laser and lens; enter one" in text and "5 still matches two engravings of the same recipe" in text
    assert "Remember for this laser and lens" in text
    assert out["empty"][:2] == ["Set a ΔE tolerance: none is saved for this laser and lens", []]          # said beside the box; nothing is sent
    assert "“ΔE tolerance”" in out["empty"][3] and "remain in the form" in out["empty"][3]
    assert out["typed"] == "false"
    (put, rules, body), (post, path, items), remembered = out["created"]
    assert (put, rules, body) == ("PUT", "/api/rules", {"device_id": 1, "lens_id": 2, "delta_tolerance": 5})
    assert (post, path) == ("POST", "/api/vector") and ["threshold", "5"] in items
    # ux-work-creation-p0: a made work leaves its laser, lens, titanium and (own) measurements as the choice the next new work starts from
    assert remembered == ["PUT", "/api/creation/context", {"device_id": 1, "lens_id": 2, "material_id": 3, "source": None}]
    assert out["after"] == ["from rules: 5", True]
    assert out["stock"][0].endswith("colors are measurements of this titanium grade from any plate")             # «Фото»: every plate of the grade
    assert out["stock"][1].endswith("recipes are limited to those measured on this stock")                         # a silhouette: this plate


@node
def test_with_a_tolerance_saved_the_form_names_it_and_sends_nothing_to_the_rules(tmp_path):
    out = run(tmp_path, 5.0)
    placeholder, invalid, text, hidden = out["shown"]
    assert placeholder == "from rules: 5" and invalid == "false" and hidden is True
    assert "leave empty for ΔE 5 from this laser and lens rules; an entered value applies only to this work" in text
    assert out["empty"][1][0][:2] == ["POST", "/api/vector"] and ["threshold", "5"] not in out["empty"][1][0][2]   # empty: the rules decide
    assert [r[:2] for r in out["created"] if r[1] != "/api/creation/context"] == [["POST", "/api/vector"], ["POST", "/api/vector"]]   # never the rules
    assert [r[:2] for r in out["created"] if r[1] == "/api/creation/context"] == [["PUT", "/api/creation/context"]] * 2          # each work is remembered


FIELDS = """
  const out = {};
  const tree = await ctx.__screens.vector.render({query: {new: '1', classic: '1'}});
  await tick(); await tick();
  const labelled = (text) => tree.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === text);
  const box = (text) => labelled(text).firstControl();
  const type = async (text, value) => { box(text).value = value; await box(text).dispatch('input'); };
  const sent = () => ctx.requests.filter((r) => r.method === 'POST').length;
  const create = async () => { await byText(tree, 'button', 'Create work').dispatch('click'); await tick(); await tick(); };
  tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file').files = [{name: 'Inna Portrait.jpg'}];
  await type('Work name', 'Inna Portrait');
  await type('ΔE tolerance', '5');
  out.names = ['Work width', 'Boundary smoothing', 'ΔE tolerance', 'Work name'].map((t) => [t, labelled(t).textContent.includes('required'), box(t).getAttribute('aria-labelledby') !== null]);
  // a wrong width, and a colour count outside the allowed 2..29: each says why beside its own box and keeps what was typed; nothing is sent
  await type('Work width', '0');
  const strategy = box('Strategy'); strategy.value = 'photo'; await strategy.dispatch('change'); await tick();
  await type('Number of colors', '40');
  await create();
  out.wrong = [sent(), labelled('Work width').errorText(), box('Work width').value, box('Work width').getAttribute('aria-invalid'),
    labelled('Number of colors').errorText(), box('Number of colors').value, box('Number of colors').getAttribute('aria-describedby').includes('error')];
  // the markers take a layer: 29 is then too many
  await type('Work width', '60'); await type('Number of colors', '29');
  const markers = tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'checkbox' && (i.parentNode.textContent || '').includes('Registration'));
  markers.checked = true; await markers.dispatch('change');
  await create();
  out.markers = [sent(), labelled('Number of colors').errorText()];
  // a silhouette work: the photograph's boxes are not read (a wrong colour count there does not stop it), the grey level is
  markers.checked = false; await markers.dispatch('change');
  await type('Number of colors', '99');
  strategy.value = 'fill'; await strategy.dispatch('change'); await tick();
  await type('Gray threshold', '300');
  await create();
  out.grey = [sent(), labelled('Gray threshold').errorText(), labelled('Number of colors').errorText()];
  await type('Gray threshold', '128');
  await create();
  out.created = [sent(), ctx.requests.filter((r) => r.method === 'POST').map((r) => r.body.items.filter(([k]) => ['grey_threshold', 'width_mm', 'name', 'n_colors'].includes(k)))[0]];
  console.log(JSON.stringify(out));
"""


def run_fields(tmp_path) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes(5)}), encoding="utf-8")
    script = tmp_path / "fields.js"
    script.write_text((HARNESS.split("(async () => {")[0] + "(async () => {" + FIELDS + "})().catch((e) => { console.error(e.stack); process.exit(1); });") % {
        "dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")), "ui": json.dumps(str(UI) + "/"),
        "tables": json.dumps(TABLES), "glue": json.dumps(GLUE + FORM_DATA)}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@node
def test_each_box_of_the_start_form_is_named_says_why_it_is_wrong_beside_itself_and_keeps_what_was_typed(tmp_path):
    out = run_fields(tmp_path)
    assert all(named for _, _, named in out["names"]) and [t for t, required, _ in out["names"] if not required] == ["ΔE tolerance"]   # required unless the rules hold the tolerance
    sent, width_error, width_kept, width_invalid, colours_error, colours_kept, colours_described = out["wrong"]
    assert sent == 0 and "Entered: 0" in width_error and width_kept == "0" and width_invalid == "true"       # the width must be above 0 (conversion.raster)
    assert "Allowed" in colours_error and "29" in colours_error and "Entered: 40" in colours_error and colours_kept == "40" and colours_described
    assert out["markers"][0] == 0 and "28" in out["markers"][1]                                              # the markers take one of the 30 layers
    assert out["grey"][0] == 0 and "255" in out["grey"][1] and out["grey"][2] == ""                          # the grey level is 0..255; the hidden colour box is not read
    count, kept = out["created"]
    assert count == 1 and ["grey_threshold", "128"] in kept and ["width_mm", "60"] in kept and ["name", "Inna Portrait"] in kept
    assert not [pair for pair in kept if pair[0] == "n_colors"]                                              # a silhouette work has no colour count
