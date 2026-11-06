"""The brief evidence component (feature ux-evidence-summaries-p0, REQ-001), run in node over the small DOM of the other screen tests: the
independent signals of a colour in words on the first level, the applicability label above a forecast from the server's own level, the fold
that holds the figures, and the colour map's picked colour and found recipes built on them. A signal the data does not carry is not drawn."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import test_color_map_one_screen as cm  # noqa: E402

UI = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui"
COMPONENT = (UI / "screens" / "evidence-summary.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = """
const {context, load} = require(%(dom)s);
const ctx = context({});
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'screens/evidence-summary.js', {code: 'globalThis.EvidenceSummary = EvidenceSummary; globalThis.App = App;'}]);
const ES = ctx.EvidenceSummary, App = ctx.App;
const has = (el, cls) => (el.className || '').split(' ').includes(cls);
const out = {};
%(body)s
console.log(JSON.stringify(out));
"""


def component(tmp_path, body):
    script = tmp_path / "component.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(HERE / "ui_dom.js")), "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(cm.TABLES), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


AGREE3 = {"engravings": 3, "agreeing": 2, "differing": 1, "limit": 5}
SOURCES = [{"origin": "test"}, {"origin": "test"}, {"origin": "work"}]


@node
def test_a_repeated_calibrated_colour_shows_three_independent_signals_in_words(tmp_path):
    out = component(tmp_path, f"""
  const e = {{agreement: {json.dumps({"engravings": 3, "agreeing": 3, "differing": 0})}, measurement: 'calibrated', referenced: true, sources: {json.dumps(SOURCES)}}};
  const el = ES.summary(e);
  out.role = el.getAttribute('role'); out.label = el.getAttribute('aria-label');
  out.texts = el.children.map((c) => c.textContent); out.tones = el.children.map((c) => c.className);
  out.titles = el.children.map((c) => c.getAttribute('title'));
""")
    assert out["role"] == "group" and out["label"] == "Evidence summary"
    assert out["texts"] == ["verified by repetition", "reference chart corrected", "3 engravings: 2 tests, 1 work"]
    assert out["tones"] == ["pill ev-signal ev-repeat ok", "pill ev-signal ev-source ok", "pill ev-signal ev-basis"]
    assert out["titles"][0] == "Color agreement: all 3 agree" and all(out["titles"])             # the words carry the meaning, never the colour alone


@node
def test_a_single_unreferenced_camera_colour_and_a_doubtful_one_say_so(tmp_path):
    out = component(tmp_path, """
  const texts = (e) => ES.summary(e).children.map((c) => c.textContent);
  out.single = texts({agreement: {engravings: 1, agreeing: 1, differing: 0}, measurement: 'relative', referenced: false, origin: 'test'});
  out.doubtful = texts({agreement: %(agree)s, doubtful: true, measurement: 'calibrated', sources: [{origin: 'work'}]});
  out.contradicted = texts({agreement: {engravings: 2, agreeing: 2, differing: 0, contradicted: true}, measurement: 'calibrated'});
""" % {"agree": json.dumps(AGREE3)})
    assert out["single"] == ["one engraving, not repeated", "camera relative", "as photographed, unreferenced", "1 engraving: 1 test"]
    assert out["doubtful"][0] == "uncertain: engravings disagree" and out["doubtful"][-1] == "1 engraving: 1 work"
    assert out["contradicted"][0] == "uncertain: engravings disagree"


@node
def test_missing_data_draws_no_signal_instead_of_a_guess(tmp_path):
    out = component(tmp_path, """
  out.empty = ES.summary({}); out.none = ES.summary(null);
  const lead = ES.summary({}, {lead: 'L'});
  out.lead = lead && lead.textContent;
  out.noAgreement = ES.summary({measurement: 'calibrated'}).children.map((c) => c.textContent);
  out.unknownMeasure = ES.summary({agreement: {engravings: 2, agreeing: 2}, measurement: 'mystery'}).children.map((c) => c.textContent);
  out.count = ES.summary({engravings: 4}).children.map((c) => c.textContent);
  out.noSources = ES.summary({agreement: {engravings: 2, agreeing: 2}, sources: []}).children.map((c) => c.textContent);
""")
    assert out["empty"] is None and out["none"] is None and out["lead"] == "L"
    assert out["noAgreement"] == ["reference chart corrected"]                                 # nothing is said about repeats when the data has none
    assert out["unknownMeasure"] == ["verified by repetition"] and out["noSources"] == ["verified by repetition"]
    assert out["count"] == ["4 independent engravings"]


@node
def test_the_applicability_label_names_the_level_the_server_derived(tmp_path):
    out = component(tmp_path, """
  const one = (a) => { const el = ES.applicability(a); return el && {level: el.getAttribute('data-level'), role: el.getAttribute('role'), cls: el.className,
    pill: el.querySelector('.pill').className, text: el.querySelector('.pill').textContent, line: el.querySelector('.ev-applic-text').textContent,
    folds: el.querySelectorAll('details').length}; };
  out.here = one({level: 'measured_here', limits: [], size: {how: 'measured', row_mm: 62, measured_mm: [60], from_mm: [60]}});
  out.other = one({level: 'other_width', limits: ['other_width'], size: {how: 'between', row_mm: 90, measured_mm: [60, 120], from_mm: [60, 120]}});
  out.outside = one({level: 'other_width', limits: ['other_width'], size: {how: 'outside', row_mm: 300, measured_mm: [60, 120], from_mm: [120]}});
  out.ramp = one({level: 'test_scale_only', limits: ['test_scale_only'], size: {how: 'measured', row_mm: 60, measured_mm: [60], from_mm: [60]}});
  out.rampWide = one({level: 'test_scale_only', limits: ['test_scale_only', 'other_width'], size: {how: 'outside', row_mm: 300, measured_mm: [60], from_mm: [60]}});
  out.unknown = one({level: 'unknown', limits: ['unknown'], size: {how: 'unknown', row_mm: null, measured_mm: [], from_mm: []}});
  out.missing = [ES.applicability(null), ES.applicability(undefined), ES.applicability({}), ES.applicability({level: 'made-up'})];
""")
    assert out["here"]["text"] == "measured at this size" and out["here"]["pill"] == "pill ok" and "alert" not in out["here"]["cls"] and out["here"]["role"] == "note"
    assert out["other"]["text"] == "measured at another width" and out["other"]["pill"] == "pill warn" and "alert warn" in out["other"]["cls"]
    assert "between measurements at 60 mm and 120 mm" in out["other"]["line"] and out["other"]["folds"] == 1                  # the numbers are one fold away
    assert "Measured at 120 mm" not in out["outside"]["line"] and "measurements at 120 mm" in out["outside"]["line"]
    assert out["ramp"]["text"] == "test scale only" and "unverified" in out["ramp"]["line"]
    assert out["rampWide"]["level"] == "test_scale_only" and out["rampWide"]["folds"] == 1                              # the width limit is kept beside the ramp
    assert out["unknown"]["text"] == "measurement width unknown" and out["unknown"]["folds"] == 0
    assert out["missing"] == [None, None, None, None]                                                                   # a server that sent none draws none


@node
def test_a_whole_works_label_counts_layers_and_photo_zones_apart(tmp_path):
    out = component(tmp_path, """
  const el = ES.applicability({level: 'test_scale_only', limits: ['test_scale_only', 'other_width'],
    counts: {layers: 4, estimated_layers: 1, zones: 3, estimated_zones: 2, ramp_only_zones: 1}});
  out.line = el.querySelector('.ev-applic-text').textContent; out.fold = el.querySelector('details').textContent;
  const fine = ES.applicability({level: 'measured_here', limits: [], counts: {layers: 4, estimated_layers: 0, zones: 0, estimated_zones: 0, ramp_only_zones: 0}});
  out.fine = fine.querySelector('.ev-applic-text').textContent;
""")
    assert "1 photo zone is predicted using test scales only" in out["line"]
    assert "1 of 4 color layers and 2 photo zones" in out["fold"]
    assert out["fine"] == "Colors of 4 color layers were measured at this size. Photo zones are checked against their own scales."


@node
def test_the_fold_is_closed_unless_asked_and_holds_what_it_is_given(tmp_path):
    out = component(tmp_path, """
  const closed = ES.disclosure('Details', [App.h('p', {}, 'Lab 1'), App.h('p', {}, 'Lab 2')]);
  const open = ES.disclosure('Details', App.h('p', {}, 'x'), true);
  out.closed = [closed.hasAttribute('open'), closed.querySelector('summary').textContent, closed.querySelectorAll('p').length];
  out.open = open.hasAttribute('open');
""")
    assert out["closed"] == [False, "Details", 2] and out["open"] is True


# -- on the colour map ------------------------------------------------------------------------------------------------------------------
@node
def test_the_picked_colour_shows_its_signals_and_keeps_the_figures_in_a_closed_fold(tmp_path):
    world = cm.colours([cm.TRUSTED, cm.ONCE, cm.DOUBT])
    world["recipes"] = cm.RECIPES
    out = cm.run(tmp_path, cm.routes_of(world), """
  const middle = tree.querySelector('.os-body').children[1];
  const detail = middle.querySelectorAll('div').find((d) => has(d, 'cm-detail'));
  const circles = middle.querySelectorAll('circle').filter((c) => c.getAttribute('stroke') !== '#ffd166');
  const read = async (title) => {
    await circles.find((c) => c.querySelector('title').textContent.startsWith(title)).dispatch('click'); await tick();
    const fold = detail.querySelectorAll('details').find((d) => has(d, 'ev-more'));
    const first = detail.children.filter((c) => c !== fold);
    return {signals: detail.querySelectorAll('.ev-signal').map((p) => p.textContent), foldOpen: fold.hasAttribute('open'), foldTitle: fold.querySelector('summary').textContent,
      foldHasLab: fold.textContent.includes('L '), outsideText: first.map((c) => c.textContent).join('|'), buttons: detail.querySelectorAll('button').map((b) => b.textContent)};
  };
  out.three = await read('Test 1'); out.once = await read('Test 2'); out.doubt = await read('Test 3');
""")
    three, once, doubt = out["three"], out["once"], out["doubt"]
    assert three["signals"] == ["verified by repetition", "reference chart corrected", "3 engravings: 2 tests, 1 work"]
    assert once["signals"][0] == "one engraving, not repeated" and once["signals"][-1] == "1 engraving: 1 test"
    assert doubt["signals"][0] == "uncertain: engravings disagree" and doubt["signals"][1] == "reference chart corrected"
    for read in (three, once, doubt):
        assert read["foldOpen"] is False and read["foldTitle"] == "Details: Lab color, confidence, sources" and read["foldHasLab"]
        assert "Confidence" not in read["outsideText"] and "How we know" not in read["outsideText"]            # the figures are not on the first level
        assert "Find this color among all" in read["buttons"]                                                          # the actions stay


@node
def test_a_found_recipe_shows_its_signals_with_the_figures_folded(tmp_path):
    match = {**cm.SEARCH["matches"][0], **cm.TRUSTED, "id": "p1", "distance": 0.4, "within_tolerance": True, "repeats": 3, "sources": cm.RECIPES["g-three"]["sources"]}
    routes = {"/api/colors": {"status": 200, "json": cm.colours([cm.TRUSTED])}, "/api/colors/search": {"status": 200, "json": {**cm.SEARCH, "matches": [match]}}}
    out = cm.run(tmp_path, routes, """
  const [, middle, right] = tree.querySelector('.os-body').children;
  await middle.querySelectorAll('circle')[0].dispatch('click');
  await byText(middle.querySelectorAll('div').find((d) => has(d, 'cm-detail')), 'button', 'Find this color among all').dispatch('click'); await tick(); await tick();
  const card = right.querySelectorAll('article')[0];
  const fold = card.querySelectorAll('details').find((d) => has(d, 'ev-more'));
  out.signals = card.querySelectorAll('.ev-signal').map((p) => p.textContent); out.open = fold.hasAttribute('open'); out.title = fold.querySelector('summary').textContent;
  out.inFold = fold.textContent.includes('Confidence: 0.50 (2 of 3 agree)'); out.outside = card.children.filter((c) => c !== fold).map((c) => c.textContent).join('|');
""")
    assert out["signals"] == ["verified by repetition", "reference chart corrected", "3 engravings: 2 tests, 1 work"]
    assert out["open"] is False and out["title"] == "Details: confidence, sources, repeatability" and out["inFold"] is True
    assert "Confidence" not in out["outside"] and "ΔE 0.4" in out["outside"]


def test_the_component_is_registered_before_the_screens_that_use_it_and_reads_only_the_shared_helpers():
    page = (UI / "index.html").read_text(encoding="utf-8")
    assert page.index("/screens/evidence-summary.js") < page.index("/screens/knowledge.js") < page.index("/screens/color-map.js") < page.index("/screens/colors.js")
    assert page.index("/app.js") < page.index("/screens/evidence-summary.js") and page.index("/screens/evidence-summary.js") < page.index("/screens/findings.js")
    assert "const {h, pill, steadiness, STEADY, agreed, originText} = App;" in COMPONENT
