"""The review screen of a pair as stages with permanent manual tools (ux-photo-review-p0: REQ-001, REQ-002, DEC-001), run in node on the
small DOM of tests/ui_dom.js. The pairs are the real answers of the server (``ingest.get_pair`` with its derived ``review``), so the
screen is tested against what the server really says, not against a copy of it.

The DOM keeps no layout and no real focus order: what is asserted is what the screen builds (nodes, attributes, the order of the
stages, the requests it sends); what only a browser or a screen reader can show is listed in the report of the feature."""
import json
import shutil
import subprocess

import numpy as np
import pytest
from fastapi.testclient import TestClient

import synth
from test_ingest import edited_lbrn, make_pair, make_world
from test_pair_review import png_of
from test_supplied_settings import pair_without, plate_world
from test_vector_work import TABLES
from titanium_platform import ingest as ig
from titanium_platform import pair_review as pr
from titanium_platform.api.app import UI_DIR, create_app

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SCRIPTS = ["app.js", "photo-modes.js", "dialogs.js", "list.js", "filepick.js", "tasks.js", "screens/composition.js", "screens/corners.js",
           "screens/ingest-dialogs.js", "screens/ingest-tasks.js", "screens/ingest-stages.js", "screens/lifecycle.js", "screens/ingest-review.js"]
SETTINGS = {"x": {"param": "power", "first": 20, "last": 50}, "y": {"param": "speed", "first": 900, "last": 300},
            "fixed": {"frequency": 330, "pulse_width": 4, "line_interval": 0.003, "passes": 1}}
STAGE_NAMES = ["Files", "Alignment", "Review", "Acceptance"]
TOOL_NAMES = ["Work corners", "Align by detail", "Move and rotate layout", "Parameter matrix", "File layers", "Engraving tasks"]

SCRIPT = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
const went = [], reloads = [], __session = {};
load(ctx, %(ui)s, [...%(tables)s, 'app.js', {code: 'App.go = (route) => { __went.push(route); };'}, ...%(scripts)s.slice(1),
  {code: "globalThis.__review = IngestReview; globalThis.__stages = IngestStages; globalThis.sessionStorage = {getItem: () => null, setItem: () => {}};"}]);
ctx.__went = went;
const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = async () => { for (let i = 0; i < 12; i++) await tick(); };
const pairs = data.pairs;
// draw a pair the way the page does: attached to the document, so focus can be read
const draw = async (name, mutate = null) => {
  const pair = JSON.parse(JSON.stringify(pairs[name]));
  if (mutate) mutate(pair);
  const tree = await ctx.__review.render(pair, async () => { reloads.push(name); });
  ctx.document.body.replaceChildren(tree);
  await settle();
  return tree;
};
const text = (el) => el.textContent.replace(/\\s+/g, ' ').trim();
const buttons = (t) => t.querySelectorAll('button');
const byText = (t, label) => buttons(t).find((b) => text(b) === label);
const withText = (t, part) => buttons(t).filter((b) => text(b).includes(part));
const visible = (el) => { for (let n = el; n && n.nodeType === 1; n = n.parentNode) if (n.hidden) return false; return true; };
const primaries = (t) => buttons(t).filter((b) => b.classList.contains('primary'));
const stageButtons = (t) => t.querySelectorAll('ol').find((o) => o.classList.contains('rv-steps')).querySelectorAll('button');
const toolButtons = (t) => t.querySelectorAll('nav').find((n) => n.getAttribute('aria-label') === 'Manual tools').querySelectorAll('button');
const panels = (t) => t.querySelectorAll('section').filter((s) => s.classList.contains('rv-panel'));
const shownStage = (t) => stageButtons(t).filter((b) => b.getAttribute('aria-current') === 'step').map((b) => b.getAttribute('aria-controls').replace('rv-panel-', ''));
const head = (t) => t.querySelectorAll('section').find((s) => s.classList.contains('rv-head'));
const region = (t, key) => t.querySelectorAll('div').find((d) => d.getAttribute('id') === 'rv-region-' + key);
const gone = (el) => el.dispatch('click');
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run_node(tmp_path, pairs: dict, routes: dict, body: str) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"pairs": pairs, "routes": routes}, default=str), encoding="utf-8")
    script = tmp_path / "review.js"
    script.write_text(SCRIPT % {"dom": json.dumps(str(UI_DIR.parents[2] / "tests" / "ui_dom.js")), "data": json.dumps(str(tmp_path / "data.json")),
                                "ui": json.dumps(str(UI_DIR) + "/"), "tables": json.dumps(TABLES), "scripts": json.dumps(SCRIPTS), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.fixture
def world(store):
    return make_world(store)


def as_json(store, pid: int) -> dict:
    return ig.get_pair(store, pid)


@pytest.fixture
def states(world):
    """One pair in each state the screen has to draw, as the server derives them."""
    store = world["store"]
    out, ids = {}, {}
    ids["fresh"] = make_pair(world)
    ids["blank"] = make_pair(world, photo=png_of(np.full((900, 1200, 3), 60, np.uint8)))
    ids["checked"] = make_pair(world)
    ids["ready"] = make_pair(world)
    ids["differs"] = make_pair(world, lbrn=edited_lbrn(world, power_for_r1c2=33))
    ids["done"] = make_pair(world)
    for name in ("blank", "checked", "ready", "differs", "done"):
        ig.check_pair(store, ids[name])
    ig.review_masks(store, ids["ready"])
    ig.review_masks(store, ids["done"])
    ig.accept_pair(store, ids["done"])
    for name, pid in ids.items():
        out[name] = as_json(store, pid)
    return out, ids, store


def routes_for(states, **extra) -> dict:
    out, ids, store = states
    pid = ids["ready"]
    base = {f"/api/pairs/{pid}/anchor-candidates": {"status": 200, "json": {"candidates": ig.anchor_candidates(store, pid)}},
            f"/api/pairs/{pid}/check": {"status": 200, "json": {"status": "Ready to accept", "check": {"problems": []}}}}
    return {**base, **extra}


# -- REQ-001: four stages ---------------------------------------------------------------------------------------------------------
def test_the_review_is_the_four_stages_in_order_and_opens_on_the_stage_the_server_names(tmp_path, states):
    pairs, ids, _ = states
    out = run_node(tmp_path, pairs, {}, """
  for (const name of Object.keys(pairs)) {
    const tree = await draw(name);
    out[name] = {names: stageButtons(tree).map((b) => text(b.querySelectorAll('span').find((s) => s.classList.contains('rv-name')))) , shown: shownStage(tree),
      visiblePanels: panels(tree).filter(visible).map((s) => s.getAttribute('id')), labelled: tree.querySelectorAll('nav').map((n) => n.getAttribute('aria-label')),
      states: stageButtons(tree).map((b) => b.getAttribute('class'))};
  }
""")
    expected = {"fresh": "files", "blank": "alignment", "checked": "review", "ready": "accept", "differs": "files"}
    for name, stage in expected.items():
        got = out[name]
        assert got["names"] == STAGE_NAMES, name
        assert got["shown"] == [stage] and got["visiblePanels"] == [f"rv-panel-{stage}"], (name, got)         # one stage in view, marked as the current step
        assert "Review stages" in got["labelled"] and "Manual tools" in got["labelled"]
    assert out["ready"]["states"][3].split()[-1] == "shown" and "current" in out["ready"]["states"][3]
    assert [s.split()[1] for s in out["checked"]["states"]] == ["done", "done", "current", "todo"]
    assert out["done"]["names"] == []                                        # an accepted pair has the read-only bar (below), not the buttons of the stages


def test_every_stage_shows_completeness_its_blockers_and_exactly_one_primary_action(tmp_path, states):
    pairs, _, _ = states
    out = run_node(tmp_path, pairs, {}, """
  const walk = async (name) => {
    const tree = await draw(name), seen = {};
    for (const [i, key] of ['files', 'alignment', 'review', 'accept'].entries()) {
      await stageButtons(tree)[i].dispatch('click');
      const top = head(tree);
      seen[key] = {primary: primaries(tree).map((b) => [text(b), b.disabled, visible(b)]), title: text(top.querySelector('h3')),
        pill: text(top.querySelectorAll('span').find((s) => s.classList.contains('pill'))), blockers: top.querySelectorAll('li').filter((l) => l.classList.contains('rv-blocker')).map(text),
        shown: shownStage(tree), reason: (() => { const row = top.querySelectorAll('div').filter((d) => d.classList.contains('row')).pop(); const note = row.querySelector('span'); return note ? text(note) : ''; })()};
    }
    return seen;
  };
  for (const name of ['fresh', 'checked', 'ready', 'differs']) out[name] = await walk(name);
""")
    for name, seen in out.items():
        for key, stage in seen.items():
            assert len(stage["primary"]) == 1 and stage["primary"][0][2], (name, key, stage["primary"])      # exactly one, and on the screen
            assert stage["shown"] == [key]
            assert stage["pill"].startswith("stages complete:")
    assert out["fresh"]["files"]["primary"][0][:2] == ["Review pair", False]
    assert out["checked"]["files"]["primary"][0][:2] == ["Next: alignment", False]
    assert out["checked"]["alignment"]["primary"][0][:2] == ["Next: review", False]
    assert out["checked"]["review"]["primary"][0][:2] == ["Masks reviewed: outlines cover the correct details", False]
    assert out["checked"]["accept"]["primary"][0][:2] == ["Accept observations", True]            # not acceptable: the masks are not reviewed
    assert any("Layer masks have not been reviewed" in b for b in out["checked"]["accept"]["blockers"])
    assert out["ready"]["accept"]["primary"][0][:2] == ["Accept observations", False] and out["ready"]["accept"]["blockers"] == []
    assert out["differs"]["files"]["primary"][0][:2] == ["Next: alignment", True]                  # blocked until the file is confirmed
    assert out["differs"]["files"]["reason"].startswith("Available once")


# -- REQ-001: the review stage ----------------------------------------------------------------------------------------------------
def test_the_review_stage_shows_the_photograph_with_contours_and_a_summary_and_keeps_layers_and_metrics_collapsed(tmp_path, states):
    pairs, ids, _ = states
    pid = ids["checked"]
    out = run_node(tmp_path, pairs, {}, """
  const tree = await draw('checked');
  const panel = panels(tree).find((s) => s.getAttribute('id') === 'rv-panel-review');
  const images = panel.querySelectorAll('img').map((i) => i.getAttribute('src').split('?')[0]);
  const more = panel.querySelectorAll('details').filter((d) => d.classList.contains('rv-more'));
  out.images = images; out.visible = visible(panel);
  out.summary = panel.querySelectorAll('div').filter((d) => d.classList.contains('alert')).map(text);
  out.more = more.map((d) => [text(d.querySelector('summary')), d.hasAttribute('open')]);
  out.controlsInPanel = panel.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'range').length;
  out.shiftCardInRegion = region(tree, 'shift').querySelectorAll('h3').map(text);
  out.shiftHidden = region(tree, 'shift').hidden;
  const folded = (el) => { for (let n = el; n && n !== panel; n = n.parentNode) if (n.localName === 'details') return true; return false; };
  out.layersListInPanel = panel.querySelectorAll('div').filter((d) => d.classList.contains('lst') && !folded(d)).length;
  out.inFolded = panel.querySelectorAll('h3').filter(folded).map(text);
""")
    assert out["images"] == [f"/api/pairs/{pid}/photo.png", f"/api/pairs/{pid}/vector-overlay.png"] and out["visible"]
    assert any("measured" in line and "of" in line for line in out["summary"])                      # the summary line
    assert out["more"] == [["Measured layers and metrics", False]]                                      # collapsed
    assert out["layersListInPanel"] == 0                                                              # the layers are in their tool, not on the stage
    assert out["controlsInPanel"] == 2                                                                # only the view controls (turn and zoom) stay with the photograph
    assert out["shiftCardInRegion"] == ["Move, rotate, and scale the whole layout"] and out["shiftHidden"] is True


# -- REQ-002 / DEC-001: the manual tools ------------------------------------------------------------------------------------------
def test_the_manual_tools_are_on_the_screen_at_every_stage_in_every_state_with_or_without_a_warning(tmp_path, states):
    pairs, _, _ = states
    out = run_node(tmp_path, pairs, {}, """
  for (const name of ['fresh', 'blank', 'checked', 'ready', 'differs']) {
    const tree = await draw(name), per = {};
    const bar = toolButtons(tree);
    const nav = bar[0].parentNode;
    for (const [i, key] of ['files', 'alignment', 'review', 'accept'].entries()) {
      await stageButtons(tree)[i].dispatch('click');
      per[key] = [bar.map(text), bar.every((b) => visible(b)), bar[0].parentNode === nav, toolButtons(tree)[0] === bar[0]];
    }
    out[name] = {per, expanded: bar.map((b) => b.getAttribute('aria-expanded')), controls: bar.map((b) => b.getAttribute('aria-controls')),
      advisories: head(tree).querySelectorAll('li').filter((l) => l.classList.contains('rv-advisory')).length};
  }
""")
    for name, got in out.items():
        for key, (names, shown, same_bar, same_button) in got["per"].items():
            assert names == TOOL_NAMES and shown and same_bar and same_button, (name, key)
        assert set(got["expanded"]) <= {"false", "true"} and len(set(got["controls"])) == 6
    assert out["ready"]["advisories"] == 0                       # nothing warned about this pair: the tools are all the same there


def test_each_tool_opens_its_region_moves_the_focus_there_and_closes_again(tmp_path, states):
    pairs, ids, _ = states
    out = run_node(tmp_path, pairs, {f"/api/pairs/{ids['ready']}/anchor-candidates": {"status": 200, "json": {"candidates": []}}}, """
  const tree = await draw('ready');
  const keys = ['corners', 'anchor', 'shift', 'matrix', 'layers', 'tasks'];
  out.closed = keys.map((k) => region(tree, k).hidden);
  out.steps = [];
  for (const [i, key] of keys.entries()) {
    const tool = toolButtons(tree)[i];
    await tool.dispatch('click'); await settle();
    out.steps.push([key, tool.getAttribute('aria-expanded'), region(tree, key).hidden, ctx.document.activeElement === region(tree, key),
      tool.getAttribute('aria-controls') === region(tree, key).getAttribute('id'), region(tree, key).getAttribute('role'), region(tree, key).getAttribute('aria-label')]);
  }
  out.allOpen = keys.map((k) => !region(tree, k).hidden);
  await toolButtons(tree)[2].dispatch('click');
  out.afterClose = [toolButtons(tree)[2].getAttribute('aria-expanded'), region(tree, 'shift').hidden];
  out.regionText = {layers: text(region(tree, 'layers').querySelector('h3')), tasks: text(region(tree, 'tasks').querySelector('h3')), matrix: text(region(tree, 'matrix').querySelector('h3')),
    corners: text(region(tree, 'corners').querySelector('h3'))};
""")
    assert out["closed"] == [True] * 6
    for key, expanded, hidden, focused, controls, role, label in out["steps"]:
        assert expanded == "true" and hidden is False and focused and controls and role == "region", key
    assert out["allOpen"] == [True] * 6 and out["afterClose"] == ["false", True]
    assert out["regionText"] == {"layers": "File layers", "tasks": "Engraving tasks", "matrix": "Parameter matrix", "corners": "Work corners on the photo"}


def test_workpiece_alignment_can_correct_an_alignment_automation_took_for_valid(tmp_path, states):
    """DEC-001: the pair is aligned and valid, nothing warned, and the details of the file are still offered where that alignment puts
    them; the operator's corners go to the server as an anchor, which the server takes before any automatic method."""
    pairs, ids, store = states
    pid = ids["ready"]
    assert pairs["ready"]["check"]["alignment"]["valid"] and pairs["ready"]["review"]["advisories"] == []
    out = run_node(tmp_path, pairs, routes_for(states), """
  const tree = await draw('ready');
  await byText(tree, 'Align by detail').dispatch('click'); await settle();
  const box = region(tree, 'anchor');
  const choose = box.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Candidate detail');
  out.requests = ctx.requests.filter((r) => r.path.endsWith('anchor-candidates')).map((r) => [r.method, r.path]);
  out.options = choose.options.map(text);
  out.intro = text(box.querySelector('p'));
  out.names = box.querySelectorAll('button').map(text).filter((t) => /^[0-9][.] detail corner /.test(t));
  const apply = byText(box, 'Align using selected detail');
  out.apply = [apply.disabled, apply.classList.contains('primary')];
  await apply.dispatch('click'); await settle();
  const sent = ctx.requests.filter((r) => r.method === 'POST' && r.path.endsWith('/check'));
  out.sent = sent.map((r) => JSON.parse(r.body));
  out.reloads = reloads.length;
""")
    assert out["requests"] == [["GET", f"/api/pairs/{pid}/anchor-candidates"]]
    assert len(out["options"]) == 4 and out["options"][0].endswith("mm²")
    assert out["intro"].startswith("Alignment was found automatically")
    assert out["names"] == [f"{i}. detail corner {i}" for i in (1, 2, 3, 4)]                    # the corners of a detail are not "top left" of the photograph
    assert out["apply"] == [False, False]                                                         # the tool's own action, not the stage's primary one
    assert len(out["sent"]) == 1 and set(out["sent"][0]) == {"anchor"}
    anchor = out["sent"][0]["anchor"]
    assert set(anchor) == {"layer_index", "region_index", "corners_fraction"} and len(anchor["corners_fraction"]) == 4
    assert out["reloads"] == 1                                                                    # the page is drawn again from the new state


def test_the_detail_tool_says_why_it_has_nothing_to_offer_and_what_to_use_instead(tmp_path, states):
    pairs, ids, _ = states
    pid = ids["ready"]
    out = run_node(tmp_path, pairs, {f"/api/pairs/{pid}/anchor-candidates": {"status": 422, "json": {"error": "check the photograph before choosing a detail", "kind": "invalid"}}}, """
  let tree = await draw('ready');
  await byText(tree, 'Align by detail').dispatch('click'); await settle();
  out.failed = [text(region(tree, 'anchor')), withText(region(tree, 'anchor'), 'Retry').length];
  ctx.fetch = async (url) => ({ok: true, status: 200, headers: {get: () => 'application/json'}, json: async () => ({candidates: []}), text: async () => '{}'});
  await byText(region(tree, 'anchor'), 'Retry').dispatch('click'); await settle();
  out.empty = text(region(tree, 'anchor'));
  tree = await draw('fresh');
  const before = ctx.requests.length;
  await byText(tree, 'Align by detail').dispatch('click'); await settle();
  out.unchecked = text(region(tree, 'anchor'));
  out.askedServer = ctx.requests.length - before;
""")
    assert "Could not retrieve file details" in out["failed"][0] and "check the photograph before choosing a detail" in out["failed"][0] and out["failed"][1] == 1   # translated, with a retry
    assert "has no details" in out["empty"] and "Work corners" in out["empty"]
    assert "after the first pair check" in out["unchecked"] and out["askedServer"] == 0               # no request that the server would refuse


def test_a_matrix_pair_has_its_matrix_tool_open_and_no_detail_tool(tmp_path):
    app = create_app(tmp_path / "data")
    app.state.store.set_setting("allow_non_raw_photos", True)
    with TestClient(app) as client:
        laser = client.post("/api/devices/from-template", json={"template": "jpt-ydflp-e-60-m7-m-r"}).json()
        material = client.post("/api/materials", json={"name": "Grade 2 sheet", "grade": "Grade 2", "thickness_mm": 1, "surface": "brushed"}).json()
        client.post("/api/setups", json={"name": "Rig", "camera": "cam", "lighting": "LED", "angle": "90", "reference_chart": "ColorChecker Classic"})
        photo = png_of(synth.material_test(cols=4, rows=3, x_values=[20.0, 30.0, 40.0, 50.0], y_values=[900.0, 600.0, 300.0])["photo"])
        pid = client.post("/api/matrix-pairs", data={"device_id": laser["id"], "lens_id": "unknown", "context": f'{{"material_id": {material["id"]}}}'},
                          files={"photo": ("matrix.png", photo, "image/png")}).json()["id"]
        client.post(f"/api/pairs/{pid}/check", json={})
        unconfirmed = client.get(f"/api/pairs/{pid}").json()
        confirmed = client.post(f"/api/pairs/{pid}/matrix", json={"edit": SETTINGS, "confirm": True}).json()
    app.state.store.close()
    out = run_node(tmp_path, {"unconfirmed": unconfirmed, "confirmed": confirmed}, {}, """
  for (const name of ['unconfirmed', 'confirmed']) {
    const tree = await draw(name), before = ctx.requests.length;
    await byText(tree, 'Align by detail').dispatch('click'); await settle();
    out[name] = {matrixOpen: !region(tree, 'matrix').hidden, expanded: toolButtons(tree)[3].getAttribute('aria-expanded'),
      matrixTitle: text(region(tree, 'matrix').querySelector('h3')), anchor: text(region(tree, 'anchor')), asked: ctx.requests.length - before,
      blockers: head(tree).querySelectorAll('li').filter((l) => l.classList.contains('rv-blocker')).map(text)};
  }
""")
    assert out["unconfirmed"]["matrixOpen"] and out["unconfirmed"]["expanded"] == "true"                    # the matrix settings wait for the operator: the tool is open
    assert any("The matrix settings have not been confirmed" in b and "Parameter matrix" in b for b in out["unconfirmed"]["blockers"])
    assert not out["confirmed"]["matrixOpen"] and out["confirmed"]["matrixTitle"] == "Parameter matrix"
    for name in ("unconfirmed", "confirmed"):
        assert "cannot be aligned by one detail" in out[name]["anchor"] and out[name]["asked"] == 0, name              # explained, and the server is not asked


# -- REQ-002: blockers and warnings with their tools ------------------------------------------------------------------------------
def test_a_blocker_is_explained_in_russian_and_links_to_the_tool_that_resolves_it(tmp_path, states):
    pairs, _, _ = states
    out = run_node(tmp_path, pairs, {}, """
  let tree = await draw('differs');
  const row = head(tree).querySelectorAll('li').find((l) => l.classList.contains('rv-blocker'));
  out.differs = {text: text(row), tools: row.querySelectorAll('button').map(text)};
  await byText(row, 'Confirm the file used').dispatch('click'); await settle();
  out.confirmDialog = ctx.document.body.querySelectorAll('h3').map(text).includes('Confirm the file used');
  ctx.document.body.querySelectorAll('button').find((b) => text(b) === 'Cancel').dispatch('click'); await settle();
  await byText(row, 'Correct pair').dispatch('click'); await settle();
  out.fixDialog = ctx.document.body.querySelectorAll('h3').map(text).includes('Correct pair');
  ctx.document.body.querySelectorAll('button').find((b) => text(b) === 'Cancel').dispatch('click'); await settle();

  tree = await draw('blank');
  const lost = head(tree).querySelectorAll('li').find((l) => l.classList.contains('rv-blocker'));
  out.blank = {text: text(lost), tools: lost.querySelectorAll('button').map(text), corners: toolButtons(tree)[0].getAttribute('aria-expanded'), anchor: toolButtons(tree)[1].getAttribute('aria-expanded')};
  await byText(lost, 'Align by detail').dispatch('click'); await settle();
  out.blankAfter = [toolButtons(tree)[1].getAttribute('aria-expanded'), ctx.document.activeElement === region(tree, 'anchor')];

  tree = await draw('checked');
  const masks = head(tree).querySelectorAll('li').find((l) => l.classList.contains('rv-blocker'));
  out.masks = {text: text(masks), tools: masks.querySelectorAll('button').map(text)};
  await byText(masks, 'Review layer masks').dispatch('click'); await settle();
  out.focusedPrimary = ctx.document.activeElement && text(ctx.document.activeElement);
""")
    assert "The file differs from the plate definition" in out["differs"]["text"]
    assert out["differs"]["tools"] == ["Confirm the file used", "Correct pair"]
    assert out["confirmDialog"] and out["fixDialog"]
    assert "The photograph is not aligned with the file" in out["blank"]["text"]
    assert out["blank"]["tools"] == ["Work corners", "Align by detail"]
    assert out["blank"]["corners"] == "true" and out["blank"]["anchor"] == "false"                  # the next step on a failed alignment is open from the start
    assert out["blankAfter"] == ["true", True]
    assert out["masks"]["tools"] == ["Review layer masks"] and "Layer masks have not been reviewed" in out["masks"]["text"]
    assert out["focusedPrimary"] == "Masks reviewed: outlines cover the correct details"


def test_a_later_stage_lists_what_is_unresolved_before_it_and_sends_the_operator_there(tmp_path, states):
    pairs, _, _ = states
    out = run_node(tmp_path, pairs, {}, """
  const tree = await draw('differs');
  await stageButtons(tree)[2].dispatch('click');
  out.review = {earlier: text(head(tree).querySelectorAll('div').find((d) => d.classList.contains('alert') && d.classList.contains('warn'))),
    primary: primaries(tree).map((b) => [text(b), b.disabled])};
  await stageButtons(tree)[3].dispatch('click');
  const row = head(tree).querySelectorAll('li').find((l) => l.classList.contains('rv-blocker'));
  out.accept = {text: text(row), primary: primaries(tree).map((b) => [text(b), b.disabled])};
  await byText(row, 'Confirm the file used').dispatch('click'); await settle();
  out.shownAfter = shownStage(tree);
  await withText(head(tree), 'Files')[0] && 0;
""")
    assert "An earlier stage has unresolved issues" in out["review"]["earlier"] and "Files" in out["review"]["earlier"]
    assert out["review"]["primary"][0][1] is True                                                   # nothing leads on from a stage with an earlier blocker
    assert "Stage: Files" in out["accept"]["text"] and out["accept"]["primary"] == [["Accept observations", True]]
    assert out["shownAfter"] == ["files"]                                                           # the tool of that blocker lives there


def test_a_warning_shows_what_needs_attention_with_the_tool_that_looks_into_it(tmp_path, states):
    pairs, ids, _ = states
    warned = json.loads(json.dumps(pairs["ready"]))
    warned["check"]["warnings"] = ["Alignment starts from one manually placed detail; review the other layer outlines before accepting measurements."]
    warned["check"]["layers"][2]["measured_lab"] = None
    warned["review"] = pr.review_state(warned)
    assert {a["code"] for a in warned["review"]["advisories"]} >= {"single_detail", "layers_skipped"} and warned["review"]["acceptable"]
    out = run_node(tmp_path, {"warned": warned}, {f"/api/pairs/{ids['ready']}/anchor-candidates": {"status": 200, "json": {"candidates": []}}}, """
  const tree = await draw('warned');
  const notes = head(tree).querySelectorAll('li').filter((l) => l.classList.contains('rv-advisory'));
  out.notes = notes.map((n) => [text(n.querySelector('div')), n.querySelectorAll('button').map(text)]);
  out.stillAcceptable = (await (async () => { await stageButtons(tree)[3].dispatch('click'); return primaries(tree).map((b) => b.disabled); })());
  await stageButtons(tree)[0].dispatch('click');
  await byText(notes[0], 'Align by detail').dispatch('click'); await settle();
  out.opened = toolButtons(tree)[1].getAttribute('aria-expanded');
""")
    by_tool = {tuple(tools): note for note, tools in out["notes"]}
    assert "Alignment starts from one manually placed detail" in by_tool[("Align by detail",)]           # the check's own sentence
    assert any(note.startswith("Unmeasured layers: 1") for note in by_tool.values()) and ("File layers",) in by_tool
    assert out["stillAcceptable"] == [False] and out["opened"] == "true"                                          # a warning does not block what the server allows


def test_a_setting_the_file_lacks_is_a_note_with_a_tool_that_opens_the_fields_for_it(tmp_path, store):
    w = plate_world(store)
    pid = pair_without(w, "QPulseWidth")
    ig.check_pair(store, pid)
    pair = ig.get_pair(store, pid)
    assert [a["code"] for a in pair["review"]["advisories"]].count("settings_missing") == 1
    out = run_node(tmp_path, {"lacking": pair}, {}, """
  const tree = await draw('lacking');
  const note = head(tree).querySelectorAll('li').find((l) => text(l).includes('Settings are missing from the file for'));
  out.note = text(note);
  const box = tree.querySelectorAll('details').find((d) => d.classList.contains('rv-more') && text(d.querySelector('summary')) === 'Enter missing layer settings');
  out.open = box.hasAttribute('open');
  await stageButtons(tree)[2].dispatch('click');
  await byText(head(tree), 'Enter missing settings').dispatch('click');
  out.after = [shownStage(tree), ctx.document.activeElement && ctx.document.activeElement.localName];
""")
    assert "r1c1" in out["note"] and out["open"] is True                                                   # open from the start: the pair lacks a setting
    assert out["after"] == [["files"], "summary"]


# -- REQ-001: going back keeps what was entered, and an in-flight change cannot leave an acceptance behind ------------------------------
def test_going_back_to_an_earlier_stage_keeps_what_was_typed_and_never_enables_acceptance(tmp_path, store):
    w = plate_world(store)
    pid = pair_without(w, "QPulseWidth")
    ig.check_pair(store, pid)
    pair = ig.get_pair(store, pid)
    out = run_node(tmp_path, {"lacking": pair}, {}, """
  const tree = await draw('lacking');
  const list = tree.querySelectorAll('div').find((d) => d.classList.contains('card') && d.querySelector('h3') && text(d.querySelector('h3')) === 'Settings missing from the LightBurn file');
  const numberField = () => list.querySelectorAll('input').find((i) => i.getAttribute('type') === 'number');
  if (!numberField()) { await list.querySelectorAll('.lst-main')[0].dispatch('click'); await settle(); }          // a single layer is open from the start
  const field = numberField();
  field.value = '150';
  const trail = [];
  for (const i of [1, 2, 3, 2, 1, 0]) {
    await stageButtons(tree)[i].dispatch('click');
    trail.push([i, shownStage(tree)[0], primaries(tree).map((b) => b.disabled), field.isConnected, field.value]);
  }
  out.trail = trail;
  out.acceptRequests = ctx.requests.filter((r) => r.path.endsWith('/accept')).length;
  out.sameField = list.querySelectorAll('input').find((i) => i.getAttribute('type') === 'number') === field;
""")
    assert [row[1] for row in out["trail"]] == ["alignment", "review", "accept", "review", "alignment", "files"]
    assert all(row[3] and row[4] == "150" for row in out["trail"]) and out["sameField"]               # the same node, with what was typed
    accept = out["trail"][2]
    assert accept[2] == [True]                                                                          # at the last stage the acceptance stays refused
    assert out["acceptRequests"] == 0


def test_while_the_pair_is_checked_again_nothing_on_the_page_can_accept_it(tmp_path, states):
    pairs, ids, _ = states
    pid = ids["ready"]
    out = run_node(tmp_path, pairs, {f"/api/pairs/{pid}/check": {"status": 200, "json": {"status": "Needs correction", "check": {"problems": ["Alignment: lost"]}}}}, """
  const tree = await draw('ready');
  out.before = primaries(tree).map((b) => [text(b), b.disabled]);
  let release = null;
  const original = ctx.fetch;
  ctx.fetch = (url, opts) => (String(url).endsWith('/check') ? new Promise((resolve) => { release = () => resolve(original(url, opts)); }) : original(url, opts));
  const again = byText(tree, 'Check again');
  const pending = again.dispatch('click');
  await settle();
  out.during = {primary: primaries(tree).map((b) => [text(b), b.disabled]), reason: text(head(tree)), again: again.disabled, status: text(tree.querySelectorAll('p').find((p) => (p.getAttribute('role') === 'status' && text(p).includes('Aligning'))))};
  release(); await pending; await settle();
  out.reloaded = reloads.length;
  // the page is drawn again from the new state of the pair: the check cleared the review of the masks
  const edited = (pair) => { pair.masks_reviewed = false; pair.status = 'Needs correction'; };
  const fresh = await draw('ready', (pair) => { edited(pair); pair.review.acceptable = false; pair.review.blockers = [{code: 'masks_unreviewed', stage: 'review', tools: ['masks'], detail: null}]; });
  await stageButtons(fresh)[3].dispatch('click');
  out.after = primaries(fresh).map((b) => [text(b), b.disabled]);
""")
    assert out["before"] == [["Accept observations", False]]
    assert out["during"]["primary"] == [["Accept observations", True]] and "Recalculation is in progress" in out["during"]["reason"] and out["during"]["again"] is True
    assert "Aligning photo and measuring layers" in out["during"]["status"] and out["reloaded"] == 1
    assert out["after"] == [["Accept observations", True]]


def test_a_failed_recheck_is_said_and_gives_the_page_back(tmp_path, states):
    pairs, ids, _ = states
    pid = ids["ready"]
    out = run_node(tmp_path, pairs, {f"/api/pairs/{pid}/check": {"status": 422, "json": {"error": "the photograph could not be read", "kind": "invalid"}}}, """
  const tree = await draw('ready');
  const again = byText(tree, 'Check again');
  await again.dispatch('click'); await settle();
  out.status = text(tree.querySelectorAll('p').find((p) => text(p).includes('Check failed')));
  out.primary = primaries(tree).map((b) => [text(b), b.disabled]);
  out.again = again.disabled; out.reloads = reloads.length;
  out.toast = ctx.document.body.querySelectorAll('div').filter((d) => d.classList.contains('toast')).map(text);
""")
    assert "Check failed" in out["status"] and out["primary"] == [["Accept observations", False]]      # the state did not change: neither does the page
    assert out["again"] is False and out["reloads"] == 0 and len(out["toast"]) == 1 and "photograph could not be read" in out["toast"][0] or "фотограф" in out["toast"][0]


# -- acceptance and rejection ------------------------------------------------------------------------------------------------------
def test_accepting_sends_one_request_hands_over_through_the_hook_and_a_refusal_is_shown_and_redrawn(tmp_path, states):
    pairs, ids, _ = states
    pid = ids["ready"]
    accepted = {"status": 200, "json": {"observations": [1, 2], "work_review": {"work": "Лист 3"}}}
    out = run_node(tmp_path, pairs, {f"/api/pairs/{pid}/accept": accepted}, """
  const tree = await draw('ready');
  const accept = primaries(tree)[0];
  await accept.dispatch('click'); await settle();
  out.ok = {requests: ctx.requests.filter((r) => r.path.endsWith('/accept')).map((r) => r.method), went: [...went],
    toast: ctx.document.body.querySelectorAll('div').filter((d) => d.classList.contains('toast')).map(text), disabled: accept.disabled};
""")
    assert out["ok"]["requests"] == ["POST"] and out["ok"]["went"] == [f"/analysis/{pid}"]
    assert any("Observations accepted. The conclusion was saved to “Лист 3”" in t for t in out["ok"]["toast"]) and out["ok"]["disabled"] is True
    refused = run_node(tmp_path, pairs, {f"/api/pairs/{pid}/accept": {"status": 422, "json": {"error": "review the layer masks overlaid on the photograph before accepting", "kind": "invalid"}}}, """
  const tree = await draw('ready');
  await primaries(tree)[0].dispatch('click'); await settle();
  out.went = [...went]; out.reloads = reloads.length;
  out.toast = ctx.document.body.querySelectorAll('div').filter((d) => d.classList.contains('toast')).map(text);
""")
    assert refused["went"] == [] and refused["reloads"] == 1                                         # nowhere to go; the page is drawn again from the server's state
    assert any("review the layer masks overlaid on the photograph before accepting" in t for t in refused["toast"])


def test_the_accept_stage_shows_the_provenance_the_measurement_rules_and_the_engraved_version_and_rejects_with_an_explanation(tmp_path, states):
    pairs, ids, _ = states
    pid = ids["ready"]
    out = run_node(tmp_path, pairs, {f"/api/pairs/{pid}": {"status": 200, "json": {}}}, """
  const tree = await draw('ready');
  const facts = tree.querySelectorAll('li').filter((l) => !l.classList.contains('rv-blocker')).map(text);
  out.facts = facts;
  out.links = tree.querySelectorAll('a').map((a) => [text(a), a.getAttribute('href')]);
  const reject = byText(tree, 'Reject result');
  out.rejectClass = reject.getAttribute('class');
  await reject.dispatch('click'); await settle();
  out.dialog = ctx.document.body.querySelectorAll('div').filter((d) => d.classList.contains('modal')).map(text);
  const confirm = ctx.document.body.querySelectorAll('button').find((b) => text(b) === 'Reject');
  await confirm.dispatch('click'); await settle();
  out.deleted = ctx.requests.filter((r) => r.method === 'DELETE').map((r) => r.path);
  out.went = [...went];
""")
    facts = " | ".join(out["facts"])
    pair = pairs["ready"]
    assert f"ID {pair['engraving_id'][:8]}" in facts and "LightBurn «plate.lbrn2», photo “plate.png”" in facts
    assert "Alignment: using markers" in facts and "calibrated against the reference chart in the photo" in facts and "measured layers: 6 of 6" in facts
    assert "auxiliary" in facts and "excluded from the knowledge model" in facts and "Operator-supplied settings: none" in facts
    assert any(href.startswith("#/experiment/") for _, href in out["links"])                         # the link to the engraved version's experiment
    assert "danger" in out["rejectClass"]
    assert out["dialog"] and "excluded from conclusions" in out["dialog"][0] and "engraving version" in out["dialog"][0]
    assert out["deleted"] == [f"/api/pairs/{pid}"] and out["went"] == ["/experiments"]


def test_an_accepted_pair_is_read_only_with_every_stage_done_its_provenance_and_the_route_to_a_correction(tmp_path, states):
    pairs, ids, _ = states
    out = run_node(tmp_path, pairs, {}, """
  const tree = await draw('done');
  out.bar = tree.querySelectorAll('ol')[0].querySelectorAll('li').map(text);
  out.current = tree.querySelectorAll('li').filter((l) => l.querySelector('span') && l.querySelector('span').getAttribute('aria-current') === 'step').length;
  out.tools = tree.querySelectorAll('nav').map((n) => n.getAttribute('aria-label'));
  out.buttons = buttons(tree).map(text);
  out.heading = tree.querySelectorAll('h3').map(text);
  out.note = text(tree.querySelectorAll('p').find((p) => text(p).includes('Manual tools')));
""")
    assert [item.split("done")[0][1:] for item in out["bar"]] == STAGE_NAMES and all(item.endswith("done") for item in out["bar"])
    assert out["tools"] == ["Review stages"] and out["buttons"] == ["Correct this photo’s alignment", "Delete pair"]
    assert out["heading"] == ["What was recorded on acceptance"] and "a new pair" in out["note"]


# -- the pages before a review, the hook, and the files ---------------------------------------------------------------------------------
def test_the_pages_before_a_review_show_the_stage_bar_for_reading_only(tmp_path):
    out = run_node(tmp_path, {}, {}, """
  const bar = ctx.__stages.upload();
  out.items = bar.querySelectorAll('li').map(text);
  out.buttons = bar.querySelectorAll('button').length;
  out.current = bar.querySelectorAll('span').filter((s) => s.getAttribute('aria-current') === 'step').map((s) => text(s));
  out.label = bar.getAttribute('aria-label');
""")
    assert [item[1:].split("upcoming")[0].split("current")[0] for item in out["items"]] == STAGE_NAMES
    assert out["buttons"] == 0 and len(out["current"]) == 1 and out["current"][0].startswith("1Files") and out["label"] == "Review stages"
    source = (UI_DIR / "screens" / "ingest.js").read_text(encoding="utf-8")
    assert source.count("IngestStages.upload()") == 2                                          # a new pair and a re-photograph


def test_acceptance_hands_over_in_one_named_place_the_next_feature_can_extend():
    review = (UI_DIR / "screens" / "ingest-review.js").read_text(encoding="utf-8")
    assert "HOOK(ux-engraving-lifecycle-p0)" in review and "async function afterAccepted(pair, outcome)" in review
    assert review.count("afterAccepted(pair,") == 2 and review.count("go('/analysis/' + pair.id)") == 1       # defined once, called once
    assert "return {render, matrixGrid, hiddenMargins};" in review                                          # the exports other screens rely on are as they were


def test_the_stage_script_is_loaded_after_what_it_uses_and_before_what_uses_it():
    import re
    scripts = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
    at = {name: scripts.index(name) for name in ("/app.js", "/screens/ingest-stages.js", "/screens/ingest-review.js", "/screens/ingest.js", "/screens/corners.js")}
    assert at["/app.js"] < at["/screens/ingest-stages.js"] < at["/screens/ingest-review.js"] < at["/screens/ingest.js"] and at["/screens/corners.js"] < at["/screens/ingest-review.js"]
    assert scripts.count("/screens/ingest-stages.js") == 1


def test_the_review_keeps_the_texts_and_expressions_other_tests_and_screens_depend_on():
    review = (UI_DIR / "screens" / "ingest-review.js").read_text(encoding="utf-8")
    for part in ("let corrected = pair.check?.chart?.usable === true, visibility = corrected ? 'normal' : 'lifted'", "await suppliedSettingsCard(pair, reload)",
                 "IngestTasks.card(pair, reload)", "IngestDialogs.layersTable(check.layers)", "h('h3', {}, 'File layers')", "I18N.name(pair.engraving_title)"):
        assert part in review, part
    stages = (UI_DIR / "screens" / "ingest-stages.js").read_text(encoding="utf-8")
    assert "accept stays disabled" not in stages and "review.acceptable" in stages                         # the accept button follows the server's verdict only


# -- ux-engraving-lifecycle-p0 REQ-002: accepting a result returns to the work it belongs to ---------------------------------------
def test_accepting_a_result_of_a_vector_work_returns_to_that_work_and_other_results_stay_on_the_analysis(tmp_path, states):
    pairs, ids, _ = states
    pid = ids["ready"]
    summary = {"summary": {"route": "/vector?plan=7&accepted=%d" % pid, "work": "Лев"}, "review": {"summary": {"beyond_layers": 2}}}
    routes = {**routes_for(states), f"/api/pairs/{pid}/accept": {"status": 200, "json": {"work_review": summary}}}
    other = {**routes_for(states), f"/api/pairs/{pid}/accept": {"status": 200, "json": {"work_review": None}}}
    script = """
  const tree = await draw('ready');
  await byText(tree, 'Accept observations').dispatch('click'); await settle();
  out.went = went.slice();
"""
    back = run_node(tmp_path, pairs, routes, script)
    elsewhere = run_node(tmp_path, pairs, other, script)
    assert back["went"] == ["/vector?plan=7&accepted=%d" % pid]
    assert elsewhere["went"] == ["/analysis/%d" % pid]
