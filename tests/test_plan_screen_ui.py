"""The engraving plan of a vector work lists its photo zones (REQ-073, 0.22.2): each zone's Image layer after the colour layers, with its
kind, powers, settings, picture and regions, or why it cannot be engraved. The layers are a short list (DEC-090, REQ-005 of
findings-you-can-manage-short-lists-re-check): one line each, the parameters under a line on a click, a sort and pages of 20. Run in node over
the small DOM of the other screen tests, with answers shaped like the server's."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lifecycle_stub import file_record, lifecycle
from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
CSS = (UI / "styles.css").read_text(encoding="utf-8")

GLUE = ("const __screens = {}, __renders = []; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { __renders.push(1); };"
        "globalThis.__screens = __screens; globalThis.__renders = __renders;")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'photo-modes.js', 'photo-quality.js', {code: %(glue)s}, 'screens/photo-form.js', 'screens/vector-photo.js',
  'hardware.js', 'screens/lifecycle.js', 'screens/plan.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const saved = [];                                         // a link clicked to save a file: [its address, the name it is saved as]
ctx.document.createElement('a').constructor.prototype.click = function () { saved.push([this.getAttribute('href'), this.getAttribute('download')]); };
const open = () => tree.querySelectorAll('.lst-det').filter((d) => !d.hidden);
let tree;
(async () => {
  const out = {};
  tree = await ctx.__screens.plan.render({arg: '22', query: {}});
  await tick(); await tick();
  const card = tree.querySelectorAll('div').find((d) => (d.querySelector('h3') || {}).textContent === 'Layers and settings');
  const mains = () => card.querySelectorAll('.lst-main');
%(body)s
  const exportButton = tree.querySelectorAll('button').find((b) => b.textContent === 'Download LightBurn');
  out.export = exportButton ? exportButton.disabled : null;                 // none when the plan is not exported (a plan restored from a file)
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""
# each line, then each line opened in turn: what it says and the pictures under it
LINES = """
  out.rows = mains().map((m) => m.textContent);
  out.chips = card.querySelectorAll('img').map((im) => [im.getAttribute('src'), im.className]);
  out.details = []; out.pictures = [];
  for (let i = 0; i < mains().length; i++) {
    await mains()[i].dispatch('click'); await tick();
    out.details.push(open().map((d) => d.textContent).join(''));
    out.pictures.push(...open().flatMap((d) => d.querySelectorAll('img')).map((im) => [im.getAttribute('src'), im.getAttribute('alt'), im.className]));
  }
"""

SETTINGS = {"speed": 150.0, "frequency": 60.0, "pulse_width": 350.0, "line_interval": 0.0212, "passes": 1, "global_passes": 1,
            "layer_type": "Image"}


def zone(number, index, kind, parameters, problem=None, regions=("r1", "r2"), **greys):
    name = None if parameters is None else f"C{index:02d} Photo {number} {kind} P{parameters['power']:g}"
    greys = {"by_colour": False, "colour_choice": "drawing", "contours": False, "rules": [], **greys}
    return {"number": number, "index": index, "kind": kind, "regions": list(regions), "name": name, "problem": problem, "parameters": parameters, **greys,
            "picture": None if problem else f"/api/vector/22/photo/{number}.png?v=k{number}", "width_mm": 50.0, "area_mm2": 2109.0}


def plan(zones, layers=True):
    layer = {"index": 2, "name": "C02 P50-F1950-V1800-I0.01", "cut_type": "Scan", "region_ids": ["r9"], "prediction": None, "stage": None,
             "parameters": {"power": 50.0, "frequency": 1950.0, "speed": 1800.0, "pulse_width": 2.0, "line_interval": 0.01, "passes": 1}}
    return {"id": 22, "name": "Inna + Boris", "mode": "Vector job", "status": "Ready to export", "strategy": "photo", "markers_enabled": True,
            "layers": [layer] if layers else [], "photo_zones": zones, "active_pairs": 0, "device_id": 1, "lens_id": 2, "plan_identifier": "TCE-A-22",
            "size_mm": {"width": 150.0, "height": 143.0}, "warnings": [], "exports": [], "experiment": None, "lifecycle": lifecycle()}


def run(tmp_path, body, steps=LINES, **more) -> dict:
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"routes": {"/api/plans/22": {"status": 200, "json": body}, **more}}), encoding="utf-8")
    script = tmp_path / "run.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(data)), "ui": json.dumps(str(UI) + "/"),
                                 "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": steps}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@node
def test_the_plan_of_a_vector_work_lists_each_photo_zone_as_its_image_layer_after_the_colours(tmp_path):
    out = run(tmp_path, plan([zone(1, 3, "grayscale", {**SETTINGS, "min_power": 2.0, "power": 29.0}, by_colour=True, colour_choice="nearest", contours=True),
                              zone(2, 4, "jarvis", {**SETTINGS, "min_power": 20.0, "power": 20.0}, regions=("r4",), by_colour=True),
                              zone(3, 5, "grayscale", None, problem="the width of the picture must be 1..1000 mm")]))
    assert out["rows"] == ["C02 P50-F1950-V1800-I0.01regions 1", "C03 Photo 1 grayscale P29Photo zone 1 · Grayscaleregions 2",
                           "C04 Photo 2 jarvis P20Photo zone 2 · Jarvisregions 1", "Photo zone 3Photo zone 3 · Grayscalecannot be engravedregions 2"]
    layer, gray, dots, bad = out["details"]
    assert layer.startswith("50.0 % · 1950.0 kHz · 1800 mm/s · Q-Pulse 2 ns · fill interval 0.0100 mm · 1 passes")
    assert "Predicted color—" in layer and layer.endswith("Regions1")                           # no prediction: said, not left out
    assert gray.startswith("Min 2.0 % – Max 29.0 % · 60.0 kHz · 150 mm/s · Q-Pulse 350 ns · line interval 0.0212 mm · 1 passes")
    assert gray.endswith("Image layer, “Grayscale” mode: the work image inside the zone and transparent outside; "
                         "grays matched to colors: nearest color · contours")                         # how its greys are chosen (0.23.0)
    assert dots.startswith("dots 20.0 % · 60.0 kHz") and dots.endswith("“Jarvis” mode: the work image inside the zone and transparent outside")
    assert bad == "the width of the picture must be 1..1000 mm"
    assert out["chips"] == [["/api/vector/22/photo/1.png?v=k1", "vw-ed-zone-chip"], ["/api/vector/22/photo/2.png?v=k2", "vw-ed-zone-chip"]]
    assert out["pictures"] == [["/api/vector/22/photo/1.png?v=k1", "Photo zone 1", "plan-zone-pic"], ["/api/vector/22/photo/2.png?v=k2", "Photo zone 2", "plan-zone-pic"]]
    assert out["export"] is False
    assert ".plan-zone-pic {" in CSS and ".vw-ed-zone-chip {" in CSS


@node
def test_a_work_engraved_only_as_photo_zones_still_has_its_layers_and_its_export(tmp_path):
    out = run(tmp_path, plan([zone(1, 2, "grayscale", {**SETTINGS, "min_power": 2.0, "power": 29.0})], layers=False))
    assert out["rows"] == ["C02 Photo 1 grayscale P29Photo zone 1 · Grayscaleregions 2"] and out["export"] is False


def layers(n):
    """``n`` colour layers, each with a prediction whose expected error grows with the layer and as many areas as its number."""
    out = []
    for i in range(1, n + 1):
        layer = plan([])["layers"][0]
        out.append({**layer, "index": i, "name": f"C{i:02d} P{i}", "region_ids": [f"r{i}-{k}" for k in range(i % 5 + 1)], "stage": "validated",
                    "prediction": {"lab": [50.0, 10.0, 10.0], "confidence": 0.8, "expected_delta_e": i / 10, "stability": {"assessed": False}}})
    return out


@node
def test_a_plan_of_many_layers_shows_one_page_sorts_them_and_opens_a_layer_only_when_clicked(tmp_path):
    """DEC-090: 24 layers show 20 lines and «Show 4 more»; the sort puts the largest expected error first; a line opens its parameters."""
    body = {**plan([]), "layers": layers(24)}
    out = run(tmp_path, body, """
  out.first = mains().map((m) => m.textContent.split('ΔE')[0]);
  out.count = card.querySelector('.lst-count').textContent;
  out.more = card.querySelector('.lst-foot').querySelector('button').textContent;
  out.search = !!card.querySelector('.lst-search');
  out.openBefore = open().length;
  const sort = card.querySelector('select'); sort.value = 'error'; await sort.dispatch('change'); await tick();
  out.sorted = mains().slice(0, 3).map((m) => m.textContent.split('ΔE')[0]);
  await mains()[0].dispatch('click'); await tick();
  out.opened = open().map((d) => d.textContent);
  out.terms = open().flatMap((d) => d.querySelectorAll('.terms-note')).map((n) => n.querySelector('summary').textContent);
  await card.querySelector('.lst-foot').querySelector('button').dispatch('click'); await tick();
  out.all = mains().length;
""")
    assert out["first"][:3] == ["C01 P1", "C02 P2", "C03 P3"] and len(out["first"]) == 20
    assert out["count"] == "showing 20 of 24" and out["more"] == "Show 4 more" and out["search"] is True
    assert out["openBefore"] == 0                                                                   # nothing is open until a line is clicked
    assert out["sorted"] == ["C24 P24", "C23 P23", "C22 P22"]
    (opened,) = out["opened"]
    assert opened.startswith("50.0 % · 1950.0 kHz") and "Expected ΔE error2.40" in opened and "StageValidated" in opened
    assert "What is a stage?" in out["terms"]
    assert out["all"] == 24


# -- the path of the plan's file (ux-engraving-lifecycle-p0) ---------------------------------------------------------------------------
@node
def test_the_plan_screen_offers_one_download_with_the_readiness_and_the_files_made_before_and_downloads_under_the_plans_name(tmp_path):
    body = {**plan([zone(1, 3, "grayscale", {**SETTINGS, "min_power": 2.0, "power": 29.0})]),
            "lifecycle": lifecycle("file", files=[file_record(1)])}
    out = run(tmp_path, body, """
  const button = tree.querySelectorAll('button').find((b) => b.textContent === 'Download LightBurn');
  out.card = button.parentNode.parentNode.parentNode.textContent;
  out.chain = tree.querySelectorAll('ol').length;
  out.folds = tree.querySelectorAll('summary').map((s) => s.textContent);
  await button.dispatch('click'); await tick();
  out.requests = ctx.requests.map((r) => r.path).filter((p) => p.includes('export')); out.saved = saved; out.renders = ctx.__renders.length;
""", **{"/api/plans/22/export.lbrn2": {"status": 200, "text": "<xml/>", "type": "application/xml"}})
    assert "LightBurn file: ready to export" in out["card"] and "Open and run it in LightBurn when ready" in out["card"] and out["chain"] == 1
    assert "Previous files (1)" in out["folds"]
    assert out["requests"] == ["/api/plans/22/export.lbrn2"] and out["saved"] == [["blob:x", "Inna_Boris.lbrn2"]] and out["renders"] == 1
    assert "Export to LightBurn" not in out["card"]


@node
def test_a_plan_that_cannot_be_exported_says_what_is_missing_and_links_to_the_measurements_that_would_fill_it(tmp_path):
    blocked = lifecycle("prepared", ready=False, blockers=[{"code": "missing_colours", "count": 2}])
    out = run(tmp_path, {**plan([]), "lifecycle": blocked}, """
  const lc = tree.querySelectorAll('div').find((d) => (d.className || '') === 'card' && d.textContent.includes('LightBurn file:'));
  out.text = lc.textContent; out.links = lc.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
""")
    assert out["export"] is True and "LightBurn file: not ready" in out["text"] and "titanium color for 2 regions is no longer measured" in out["text"]
    assert out["links"] == [["Experiment goals", "#/designer?device=1&lens=2"]]


@node
def test_a_plan_restored_from_a_file_has_no_export_at_all_because_it_records_a_job_that_was_engraved(tmp_path):
    out = run(tmp_path, {**plan([]), "mode": "Restored from file", "restored": {"pair_id": 5}, "lifecycle": lifecycle("prepared", ready=False, blockers=[{"code": "restored"}])})
    assert out["export"] is None
