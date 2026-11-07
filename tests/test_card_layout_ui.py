"""The columns of the business-card editor can be resized and hidden (``screens/card-layout.js``, ``card.css``, mounted by ``screens/card-work.js``).
The pure helpers (``parse``, ``clampWidths``, ``limits``) are checked as numbers, and ``mount`` is run in node over the small DOM of the other screen tests
with a fake localStorage and a fake window: the splitters (pointer and keyboard), the hide and show buttons, the memory of the layout, the re-clamping when the
window changes, and the clean-up. What node cannot show is the look and a real pointer in a real browser; the narrow window is CSS only (the splitters and
the buttons are display:none there, which the stylesheet tests below read from card.css and styles.css)."""
import json
import re
import subprocess
from pathlib import Path

from test_card_work_ui import node, run as run_screen
from test_vector_work import TABLES, UI

HARNESS = r"""
const {context, load, El} = require(__DOM__);
const ctx = context({});
load(ctx, __UI__, [...__TABLES__, 'app.js', 'screens/card-layout.js', {code: 'globalThis.CardLayout = CardLayout;'}]);
const App = ctx.App, doc = ctx.document, CL = ctx.CardLayout, h = App.h;
const KEY = CL.KEY;
/** A localStorage that remembers (and counts what it is asked); ``broken`` is one that refuses everything, as a blocked or full one does. */
const memory = (initial = {}) => {
  const data = {...initial}, calls = {get: 0, set: 0};
  return {data, calls, getItem(k) { calls.get += 1; return k in data ? data[k] : null; }, setItem(k, v) { calls.set += 1; data[k] = String(v); }};
};
const broken = () => ({getItem() { throw new Error('storage is blocked'); }, setItem() { throw new Error('storage is full'); }});
/** The window: it records its listeners and fires them on demand. */
const windowOf = () => {
  const l = {};
  return {l, addEventListener(t, f) { (l[t] = l[t] || []).push(f); }, removeEventListener(t, f) { l[t] = (l[t] || []).filter((x) => x !== f); },
    fire(t) { for (const f of [...(l[t] || [])]) f({type: t}); }, count: (t) => (l[t] || []).length};
};
/** A column as card-work.js builds it: a head with a title, and a body. */
const column = (cls, title) => {
  const head = h('div', {class: 'os-col-head'}, h('h3', {}, title));
  return {head, el: h('div', {class: 'os-col ' + cls}, head, h('div', {class: 'os-scroll'}, 'content of ' + title))};
};
/** The grid of the screen, in the document, ``size`` px wide (change ``body.size`` and fire the window's resize to move the window). */
const page = (size = 1600) => {
  const left = column('cw-left', 'Add'), centre = column('cw-centre', 'Card'), right = column('cw-right', 'Element');
  const body = h('div', {class: 'os-body cw-body'}, left.el, centre.el, right.el);
  body.size = size;
  body.getBoundingClientRect = () => ({left: 0, top: 0, width: body.size, height: 800});
  doc.body.append(body);
  return {body, left: left.el, centre: centre.el, right: right.el, leftHead: left.head, rightHead: right.head};
};
const mount = (p, extra = {}) => CL.mount(p.body, {left: p.left, right: p.right, storage: memory(), win: windowOf(), ...extra});
const vars = (body) => Object.fromEntries((body.getAttribute('style') || '').split(';').filter(Boolean).map((part) => part.split(':')));
const px = (body, side) => vars(body)[`--cw-${side}`];
const splitOf = (body, side) => body.querySelector(`.cw-split-${side}`);
const aria = (split) => ['aria-valuenow', 'aria-valuemin', 'aria-valuemax'].map((k) => split.getAttribute(k));
/** Press a key on a splitter; the number of times the screen asked the browser to leave the key alone comes back. */
const key = async (split, k, extra = {}) => { let prevented = 0; await split.dispatch('keydown', {key: k, preventDefault() { prevented += 1; }, ...extra}); return prevented; };
const saved = (storage) => (KEY in storage.data ? JSON.parse(storage.data[KEY]) : null);
(async () => {
  const out = {};
__BODY__
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, body: str) -> dict:
    """Run ``body`` in node against card-layout.js; it fills ``out`` (JSON)."""
    script = tmp_path / "card_layout_ui.js"
    code = HARNESS
    for token, value in (("__DOM__", json.dumps(str(Path(__file__).with_name("ui_dom.js")))), ("__UI__", json.dumps(str(UI) + "/")),
                         ("__TABLES__", json.dumps(TABLES)), ("__BODY__", body)):
        code = code.replace(token, value)
    script.write_text(code, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.stderr or done.stdout)[-4000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


DEFAULT = {"left": 280, "right": 420}
DEFAULT_LAYOUT = {**DEFAULT, "leftHidden": False, "rightHidden": False}


# -- the pure helpers -----------------------------------------------------------------------------------------------------------------------------------
@node
def test_the_figures_of_the_layout_are_the_ones_the_operator_asked_for(tmp_path):
    out = run(tmp_path, """
  out.constants = {split: CL.SPLIT, rail: CL.RAIL, centre: CL.CENTRE_MIN, key: CL.KEY, limits: CL.LIMITS, defaults: CL.DEFAULTS};
""")
    assert out["constants"] == {"split": 10, "rail": 36, "centre": 360, "key": "cw.layout.v1", "limits": {"left": [200, 520], "right": [280, 720]}, "defaults": DEFAULT}


@node
def test_clamp_widths_keeps_each_column_in_its_limits_and_the_card_at_360_px_when_the_container_allows_it(tmp_path):
    out = run(tmp_path, """
  const C = CL.clampWidths;
  out.plenty = C({left: 280, right: 420}, 1600);
  out.limits = [C({left: 50, right: 100}, 1600), C({left: 900, right: 2000}, 3000)];            // below the narrowest, above the widest
  out.rounded = C({left: 300.4, right: 300.6}, 1600);
  out.squeezed = C({left: 280, right: 420}, 1000);                                              // 80 px too much: both give up their share of what they can give
  out.squeezedCentre = 1000 - 2 * CL.SPLIT - out.squeezed.left - out.squeezed.right;
  out.fractional = C({left: 280, right: 420}, 1000.9);                                          // a container of 1000.9 px has 1000 whole pixels
  out.exactlyMinimums = C({left: 280, right: 420}, 860);                                        // the card gets exactly 360 with both at their narrowest
  out.tiny = [C({left: 520, right: 720}, 300), C({left: 280, right: 420}, 1), C({left: 200, right: 280}, 500)];     // never below the narrowest: the card gets less instead
  out.leftHidden = [C({left: 400, right: 400, leftHidden: true}, 900), C({left: 400, right: 400, leftHidden: true}, 700)];   // a hidden column takes 36 px and gives nothing
  out.bothHidden = C({left: 400, right: 400, leftHidden: true, rightHidden: true}, 200);
  out.unmeasured = [C({left: 400, right: 400}, 0), C({left: 400, right: 400}, NaN), C({left: 400, right: 400}), C({left: 400, right: 400}, -5)];
  out.garbage = [C(null, 1600), C(undefined, 1600), C({left: 'wide', right: NaN}, 1600), C({left: Infinity}, 1600)];
  const input = {left: 280, right: 420, leftHidden: false}; C(input, 500);
  out.input = input;
""")
    assert out["plenty"] == DEFAULT
    assert out["limits"] == [{"left": 200, "right": 280}, {"left": 520, "right": 720}]
    assert out["rounded"] == {"left": 300, "right": 301}
    assert out["squeezed"] == {"left": 251, "right": 369} and out["squeezedCentre"] == 360
    assert out["fractional"] == out["squeezed"]
    assert out["exactlyMinimums"] == {"left": 200, "right": 280}
    assert out["tiny"] == [{"left": 200, "right": 280}] * 3
    assert out["leftHidden"] == [{"left": 400, "right": 400}, {"left": 400, "right": 284}]
    assert out["bothHidden"] == {"left": 400, "right": 400}
    assert out["unmeasured"] == [{"left": 400, "right": 400}] * 4
    assert out["garbage"] == [DEFAULT] * 4
    assert out["input"] == {"left": 280, "right": 420, "leftHidden": False}               # the argument is left alone


@node
def test_limits_say_how_wide_a_column_can_be_made_now(tmp_path):
    out = run(tmp_path, """
  out.wide = [CL.limits('left', {left: 280, right: 420}, 1600), CL.limits('right', {left: 280, right: 420}, 1600)];
  out.tight = CL.limits('left', {left: 251, right: 369}, 1000);                                 // the other column and the card's 360 px leave 251
  out.rightRoom = CL.limits('right', {left: 280, right: 420}, 1100);
  out.otherHidden = CL.limits('right', {left: 280, right: 420, leftHidden: true}, 1100);       // the hidden one takes only its rail
  out.noRoom = CL.limits('left', {left: 280, right: 720}, 900);                                // never below the narrowest
  out.unmeasured = CL.limits('right', {}, 0);
""")
    assert out["wide"] == [{"min": 200, "max": 520}, {"min": 280, "max": 720}]
    assert out["tight"] == {"min": 200, "max": 251}
    assert out["rightRoom"] == {"min": 280, "max": 440}
    assert out["otherHidden"] == {"min": 280, "max": 684}
    assert out["noRoom"] == {"min": 200, "max": 200}
    assert out["unmeasured"] == {"min": 280, "max": 720}


@node
def test_parse_turns_anything_that_was_stored_into_a_valid_layout(tmp_path):
    out = run(tmp_path, """
  const P = CL.parse;
  out.missing = [P(null), P(undefined), P(''), P(0), P(7), P('7'), P('null')];
  out.garbage = [P('not json{'), P('[1,2]'), P('"wide"'), P('{"left": "wide", "right": null}'), P({left: NaN, right: Infinity})];
  out.outOfRange = P('{"left": 5000, "right": 1, "leftHidden": true, "rightHidden": "yes"}');
  out.rounded = P(JSON.stringify({left: 333.6, right: 444.4}));
  out.object = P({left: 300});
  out.flags = [P({leftHidden: 1, rightHidden: true}), P('{"leftHidden": "true"}')];
  out.roundTrip = P(JSON.stringify({left: 321, right: 654, leftHidden: true, rightHidden: false}));
""")
    assert out["missing"] == [DEFAULT_LAYOUT] * 7
    assert out["garbage"] == [DEFAULT_LAYOUT] * 5
    assert out["outOfRange"] == {"left": 520, "right": 280, "leftHidden": True, "rightHidden": False}
    assert out["rounded"] == {"left": 334, "right": 444, "leftHidden": False, "rightHidden": False}
    assert out["object"] == {**DEFAULT_LAYOUT, "left": 300}
    assert out["flags"] == [{**DEFAULT_LAYOUT, "rightHidden": True}, DEFAULT_LAYOUT]       # only the value true is a hidden column
    assert out["roundTrip"] == {"left": 321, "right": 654, "leftHidden": True, "rightHidden": False}


# -- what mount draws -------------------------------------------------------------------------------------------------------------------------------------
@node
def test_mount_puts_a_splitter_between_the_columns_a_hide_button_in_each_side_head_and_a_rail_button_in_each_side_column(tmp_path):
    out = run(tmp_path, """
  const p = page(1600), layout = mount(p);
  const L = splitOf(p.body, 'left'), R = splitOf(p.body, 'right');
  out.order = p.body.children.map((c) => c.className);
  out.style = vars(p.body);
  out.splitters = [L, R].map((s) => ({role: s.getAttribute('role'), orientation: s.getAttribute('aria-orientation'), label: s.getAttribute('aria-label'), tabindex: s.getAttribute('tabindex'), values: aria(s)}));
  out.hide = [p.leftHead, p.rightHead].map((head) => { const b = head.querySelectorAll('button'); return {count: b.length, text: b[0].textContent, title: b[0].getAttribute('title'), type: b[0].getAttribute('type'), kids: head.children.map((c) => c.localName)}; });
  out.rails = [p.left, p.right].map((c) => { const r = c.children[0]; return {tag: r.localName, cls: r.className, label: r.getAttribute('aria-label'), title: r.getAttribute('title'), text: r.textContent, collapsed: c.classList.contains('cw-collapsed')}; });
  out.titles = [p.leftHead.querySelector('h3').textContent, p.rightHead.querySelector('h3').textContent];
  App.fill(p.rightHead.querySelector('h3'), 'Rectangle 1');                  // card-work.js replaces the title again and again: the button is not in it
  out.afterTitle = p.rightHead.children.map((c) => c.localName + ':' + c.textContent);
  out.centre = p.centre.children.map((c) => c.className);
  out.api = Object.keys(layout).sort();
  out.state = layout.state();
""")
    assert out["order"] == ["os-col cw-left", "cw-split cw-split-left", "os-col cw-centre", "cw-split cw-split-right", "os-col cw-right"]    # in place, so Tab meets them in place
    assert out["style"] == {"--cw-left": "280px", "--cw-right": "420px"}
    assert out["splitters"] == [
        {"role": "separator", "orientation": "vertical", "label": "Resize the left panel", "tabindex": "0", "values": ["280", "200", "520"]},
        {"role": "separator", "orientation": "vertical", "label": "Resize the right panel", "tabindex": "0", "values": ["420", "280", "720"]}]
    assert out["hide"] == [{"count": 1, "text": "Hide panel", "title": "Hide the left panel", "type": "button", "kids": ["h3", "button"]},
                           {"count": 1, "text": "Hide panel", "title": "Hide the right panel", "type": "button", "kids": ["h3", "button"]}]
    assert out["rails"] == [{"tag": "button", "cls": "btn btn-small cw-rail", "label": "Show the left panel", "title": "Show the left panel", "text": "»", "collapsed": False},
                            {"tag": "button", "cls": "btn btn-small cw-rail", "label": "Show the right panel", "title": "Show the right panel", "text": "«", "collapsed": False}]
    assert out["titles"] == ["Add", "Element"] and out["afterTitle"] == ["h3:Rectangle 1", "button:Hide panel"]
    assert out["centre"] == ["os-col-head", "os-scroll"]                                           # the centre is not touched
    assert out["api"] == ["destroy", "refresh", "state"] and out["state"] == DEFAULT_LAYOUT


@node
def test_the_hide_button_goes_into_the_head_that_is_given_and_by_default_into_the_first_head_of_the_column(tmp_path):
    out = run(tmp_path, """
  const p = page(1600), mine = h('div', {class: 'mine'}, 'my head');
  p.left.append(mine);
  mount(p, {leftHead: mine});
  out.given = [mine.querySelectorAll('button').length, p.leftHead.querySelectorAll('button').length, p.rightHead.querySelectorAll('button').length];
""")
    assert out["given"] == [1, 0, 1]


# -- the keyboard -----------------------------------------------------------------------------------------------------------------------------------------
@node
def test_arrows_move_the_splitter_by_16_px_and_by_64_with_shift_and_home_and_end_go_to_the_narrowest_and_the_widest(tmp_path):
    out = run(tmp_path, """
  const p = page(1600), storage = memory(), layout = mount(p, {storage});
  const L = splitOf(p.body, 'left');
  out.left = [];
  for (const [k, extra] of [['ArrowRight', {}], ['ArrowRight', {shiftKey: true}], ['ArrowLeft', {}], ['ArrowLeft', {shiftKey: true}], ['Home', {}], ['ArrowLeft', {}],
                            ['End', {}], ['ArrowRight', {}], ['Tab', {}], ['a', {}], ['ArrowLeft', {ctrlKey: true}], ['ArrowLeft', {metaKey: true}], ['ArrowLeft', {altKey: true}]]) {
    const prevented = await key(L, k, extra);
    out.left.push([k, px(p.body, 'left'), aria(L)[0], prevented]);
  }
  out.leftSaved = saved(storage);
  // the right column: the arrows move the splitter, so Left makes it wider
  const q = page(1600), other = memory();
  mount(q, {storage: other});
  const R = splitOf(q.body, 'right');
  out.right = [];
  for (const [k, extra] of [['ArrowLeft', {}], ['ArrowRight', {}], ['ArrowLeft', {shiftKey: true}], ['Home', {}], ['End', {}], ['ArrowRight', {shiftKey: true}], ['ArrowRight', {}]]) {
    const prevented = await key(R, k, extra);
    out.right.push([k, px(q.body, 'right'), aria(R)[0], prevented]);
  }
  out.rightSaved = saved(other);
""")
    assert out["left"] == [["ArrowRight", "296px", "296", 1], ["ArrowRight", "360px", "360", 1], ["ArrowLeft", "344px", "344", 1], ["ArrowLeft", "280px", "280", 1],
                           ["Home", "200px", "200", 1], ["ArrowLeft", "200px", "200", 1], ["End", "520px", "520", 1], ["ArrowRight", "520px", "520", 1],
                           ["Tab", "520px", "520", 0], ["a", "520px", "520", 0], ["ArrowLeft", "520px", "520", 0], ["ArrowLeft", "520px", "520", 0], ["ArrowLeft", "520px", "520", 0]]
    assert out["leftSaved"] == {**DEFAULT_LAYOUT, "left": 520}
    assert out["right"] == [["ArrowLeft", "436px", "436", 1], ["ArrowRight", "420px", "420", 1], ["ArrowLeft", "484px", "484", 1], ["Home", "280px", "280", 1],
                            ["End", "720px", "720", 1], ["ArrowRight", "656px", "656", 1], ["ArrowRight", "640px", "640", 1]]
    assert out["rightSaved"] == {**DEFAULT_LAYOUT, "right": 640}


@node
def test_a_column_is_never_made_so_wide_that_the_card_gets_less_than_360_px(tmp_path):
    out = run(tmp_path, """
  const p = page(1000), layout = mount(p);                      // 1000 px: the asked 280 + 420 leave the card 280 px, so both are drawn narrower
  const L = splitOf(p.body, 'left'), R = splitOf(p.body, 'right');
  out.start = [vars(p.body), aria(L), aria(R)];
  await key(L, 'End');
  out.leftEnd = [px(p.body, 'left'), aria(L)];                  // nothing to give: the right column has the room
  await key(R, 'Home');                                         // the right column gives room back ...
  out.afterRightHome = [vars(p.body), aria(L), aria(R)];
  await key(L, 'End');                                          // ... and the left column takes it, to the last pixel
  out.afterLeftEnd = [vars(p.body), aria(L)];
  await key(R, 'End');
  out.rightEnd = [px(p.body, 'right'), aria(R)];
  out.centre = 1000 - 2 * CL.SPLIT - parseInt(px(p.body, 'left')) - parseInt(px(p.body, 'right'));
""")
    assert out["start"] == [{"--cw-left": "251px", "--cw-right": "369px"}, ["251", "200", "251"], ["369", "280", "369"]]
    assert out["leftEnd"] == ["251px", ["251", "200", "251"]]
    assert out["afterRightHome"] == [{"--cw-left": "251px", "--cw-right": "280px"}, ["251", "200", "340"], ["280", "280", "369"]]
    assert out["afterLeftEnd"] == [{"--cw-left": "340px", "--cw-right": "280px"}, ["340", "200", "340"]]
    assert out["rightEnd"] == ["280px", ["280", "280", "280"]] and out["centre"] == 360


# -- the pointer ------------------------------------------------------------------------------------------------------------------------------------------
@node
def test_dragging_a_splitter_follows_the_pointer_inside_the_limits_and_remembers_the_width_when_the_pointer_is_let_go(tmp_path):
    out = run(tmp_path, """
  const p = page(1600), storage = memory(), layout = mount(p, {storage});
  const L = splitOf(p.body, 'left'), R = splitOf(p.body, 'right');
  const captured = [];
  L.setPointerCapture = (id) => captured.push(id);
  let prevented = 0;
  await L.dispatch('pointerdown', {clientX: 300, pointerId: 5, button: 0, preventDefault() { prevented += 1; }});
  out.down = {body: p.body.className, split: L.className, captured: captured.slice(), prevented, focus: doc.activeElement === L, saved: saved(storage)};
  await L.dispatch('pointermove', {clientX: 340, pointerId: 5});
  out.move = [px(p.body, 'left'), aria(L)[0], saved(storage)];                  // follows the pointer, nothing is written while it moves
  await L.dispatch('pointermove', {clientX: 5000, pointerId: 5});
  out.far = px(p.body, 'left');
  await L.dispatch('pointermove', {clientX: -5000, pointerId: 5});
  out.near = px(p.body, 'left');
  await L.dispatch('pointermove', {clientX: 380, pointerId: 9});                 // another pointer is not this drag
  out.other = px(p.body, 'left');
  await L.dispatch('pointermove', {clientX: 380, pointerId: 5});
  out.again = px(p.body, 'left');
  await L.dispatch('pointerup', {pointerId: 5});
  out.up = {body: p.body.className, split: L.className, saved: saved(storage)};
  await L.dispatch('pointermove', {clientX: 900, pointerId: 5});                 // the drag is over
  out.after = px(p.body, 'left');
  // the right column grows when the pointer goes left
  await R.dispatch('pointerdown', {clientX: 1000, pointerId: 6});
  await R.dispatch('pointermove', {clientX: 960, pointerId: 6});
  out.right = [px(p.body, 'right'), aria(R)[0]];
  await R.dispatch('pointerup', {pointerId: 6});
  out.rightSaved = saved(storage);
  // a secondary button does not drag; a cancelled or lost drag ends without writing anything
  const writes = storage.calls.set;
  await L.dispatch('pointerdown', {clientX: 1, pointerId: 7, button: 2});
  out.secondary = [p.body.className, L.className];
  await L.dispatch('pointerdown', {clientX: 1, pointerId: 8, button: 0});
  await L.dispatch('pointercancel', {pointerId: 8});
  await L.dispatch('pointerdown', {clientX: 1, pointerId: 10, button: 0});
  await L.dispatch('lostpointercapture', {pointerId: 10});
  out.ended = [p.body.className, L.className, storage.calls.set - writes];
  await L.dispatch('pointermove', {clientX: 5, pointerId: 5});                    // a move with no drag changes nothing
  out.idle = px(p.body, 'left');
""")
    assert out["down"] == {"body": "os-body cw-body cw-dragging", "split": "cw-split cw-split-left cw-split-drag", "captured": [5], "prevented": 1, "focus": True, "saved": None}
    assert out["move"] == ["320px", "320", None]
    assert (out["far"], out["near"], out["other"], out["again"]) == ("520px", "200px", "200px", "360px")
    assert out["up"] == {"body": "os-body cw-body", "split": "cw-split cw-split-left", "saved": {**DEFAULT_LAYOUT, "left": 360}} and out["after"] == "360px"
    assert out["right"] == ["460px", "460"] and out["rightSaved"] == {**DEFAULT_LAYOUT, "left": 360, "right": 460}
    assert out["secondary"] == ["os-body cw-body", "cw-split cw-split-left"]
    assert out["ended"] == ["os-body cw-body", "cw-split cw-split-left", 0] and out["idle"] == "360px"


@node
def test_a_drag_stops_where_the_card_would_get_less_than_360_px(tmp_path):
    out = run(tmp_path, """
  const p = page(1600), layout = mount(p);
  const L = splitOf(p.body, 'left'), R = splitOf(p.body, 'right');
  await L.dispatch('pointerdown', {clientX: 0, pointerId: 1}); await L.dispatch('pointermove', {clientX: 5000, pointerId: 1}); await L.dispatch('pointerup', {pointerId: 1});
  await R.dispatch('pointerdown', {clientX: 1500, pointerId: 2}); await R.dispatch('pointermove', {clientX: -5000, pointerId: 2}); await R.dispatch('pointerup', {pointerId: 2});
  out.widths = [px(p.body, 'left'), px(p.body, 'right')];
  out.aria = [aria(L), aria(R)];
  out.centre = 1600 - 2 * CL.SPLIT - parseInt(px(p.body, 'left')) - parseInt(px(p.body, 'right'));
""")
    assert out["widths"] == ["520px", "700px"] and out["centre"] == 360
    assert out["aria"] == [["520", "200", "520"], ["700", "280", "700"]]


@node
def test_a_double_click_on_a_splitter_brings_its_column_back_to_the_default_width(tmp_path):
    out = run(tmp_path, """
  const p = page(1600), storage = memory(), layout = mount(p, {storage});
  const L = splitOf(p.body, 'left'), R = splitOf(p.body, 'right');
  await key(L, 'End'); await key(R, 'Home');
  out.changed = [px(p.body, 'left'), px(p.body, 'right')];
  await L.dispatch('dblclick');
  out.leftReset = [px(p.body, 'left'), px(p.body, 'right'), aria(L)[0]];                // only its own column
  await R.dispatch('dblclick');
  out.reset = [px(p.body, 'left'), px(p.body, 'right'), aria(R)[0], saved(storage)];
  // the default does not take the card below 360 px either
  const q = page(1000), other = memory();
  mount(q, {storage: other});
  await key(splitOf(q.body, 'right'), 'Home'); await key(splitOf(q.body, 'left'), 'End');
  await splitOf(q.body, 'left').dispatch('dblclick');
  out.narrow = [px(q.body, 'left')];
  await splitOf(q.body, 'right').dispatch('dblclick');
  out.narrow.push(px(q.body, 'right'));
""")
    assert out["changed"] == ["520px", "280px"]
    assert out["leftReset"] == ["280px", "280px", "280"]
    assert out["reset"] == ["280px", "420px", "420", DEFAULT_LAYOUT]
    assert out["narrow"] == ["280px", "340px"]                                              # 1000 - 20 - 360 - 280


# -- hide and show ----------------------------------------------------------------------------------------------------------------------------------------
@node
def test_hide_collapses_a_column_to_a_rail_show_brings_it_back_and_the_cursor_goes_to_the_button_that_takes_over(tmp_path):
    out = run(tmp_path, """
  const p = page(900), storage = memory(), layout = mount(p, {storage});          // 900 px: both columns are drawn narrower than asked (215 and 305)
  const L = splitOf(p.body, 'left'), R = splitOf(p.body, 'right');
  const hideOf = (head) => head.querySelector('.cw-hide'), railOf = (col) => col.querySelector('.cw-rail');
  const look = () => ({vars: vars(p.body), left: p.left.className, right: p.right.className, ls: L.className, rs: R.className,
    focus: doc.activeElement === railOf(p.left) ? 'rail-left' : doc.activeElement === railOf(p.right) ? 'rail-right' : doc.activeElement === hideOf(p.leftHead) ? 'hide-left'
      : doc.activeElement === hideOf(p.rightHead) ? 'hide-right' : null, saved: saved(storage)});
  out.start = look();
  await hideOf(p.leftHead).dispatch('click');
  out.leftHidden = look();                                                      // the right column takes the room: it is drawn as asked
  await railOf(p.left).dispatch('click');
  out.leftShown = look();
  await hideOf(p.rightHead).dispatch('click');
  out.rightHidden = look();
  await hideOf(p.leftHead).dispatch('click');
  out.bothHidden = look();
  await railOf(p.right).dispatch('click');
  out.rightShown = look();
  out.inDom = [p.left.parentNode === p.body, p.right.parentNode === p.body, p.body.children.length, !!p.left.querySelector('.os-scroll'), !!p.right.querySelector('.os-scroll'),
    p.left.querySelector('.os-scroll').textContent];
  // the width it had comes back
  const q = page(1600), other = memory();
  mount(q, {storage: other});
  for (let i = 0; i < 3; i++) await key(splitOf(q.body, 'left'), 'ArrowRight');
  await q.leftHead.querySelector('.cw-hide').dispatch('click');
  out.remembered = [px(q.body, 'left')];
  await q.left.querySelector('.cw-rail').dispatch('click');
  out.remembered.push(px(q.body, 'left'), saved(other));
""")
    rest = {"left": "os-col cw-left", "right": "os-col cw-right", "ls": "cw-split cw-split-left", "rs": "cw-split cw-split-right"}
    assert out["start"] == {**rest, "vars": {"--cw-left": "215px", "--cw-right": "305px"}, "focus": None, "saved": None}
    assert out["leftHidden"] == {**rest, "left": "os-col cw-left cw-collapsed", "ls": "cw-split cw-split-left cw-split-off", "vars": {"--cw-left": "36px", "--cw-right": "420px"},
                                 "focus": "rail-left", "saved": {**DEFAULT_LAYOUT, "leftHidden": True}}
    assert out["leftShown"] == {**rest, "vars": {"--cw-left": "215px", "--cw-right": "305px"}, "focus": "hide-left", "saved": DEFAULT_LAYOUT}
    assert out["rightHidden"] == {**rest, "right": "os-col cw-right cw-collapsed", "rs": "cw-split cw-split-right cw-split-off", "vars": {"--cw-left": "280px", "--cw-right": "36px"},
                                  "focus": "rail-right", "saved": {**DEFAULT_LAYOUT, "rightHidden": True}}
    assert out["bothHidden"] == {**rest, "left": "os-col cw-left cw-collapsed", "right": "os-col cw-right cw-collapsed", "ls": "cw-split cw-split-left cw-split-off",
                                 "rs": "cw-split cw-split-right cw-split-off", "vars": {"--cw-left": "36px", "--cw-right": "36px"}, "focus": "rail-left",
                                 "saved": {**DEFAULT_LAYOUT, "leftHidden": True, "rightHidden": True}}
    assert out["rightShown"]["right"] == "os-col cw-right" and out["rightShown"]["focus"] == "hide-right" and out["rightShown"]["vars"] == {"--cw-left": "36px", "--cw-right": "420px"}
    assert out["inDom"] == [True, True, 5, True, True, "content of Add"]                      # the columns and what the screen put in them stay
    assert out["remembered"] == ["36px", "328px", {**DEFAULT_LAYOUT, "left": 328}]                # a hidden column is 36 px; shown again it is as wide as it was


# -- the memory -------------------------------------------------------------------------------------------------------------------------------------------
@node
def test_the_layout_is_remembered_between_visits_and_a_bad_stored_value_gives_the_default(tmp_path):
    out = run(tmp_path, """
  const storage = memory();
  const p = page(1600), layout = mount(p, {storage});
  out.written = storage.calls.set;                                              // looking at the screen writes nothing
  await key(splitOf(p.body, 'left'), 'ArrowRight');
  await key(splitOf(p.body, 'right'), 'ArrowLeft');
  await p.rightHead.querySelector('.cw-hide').dispatch('click');
  out.saved = saved(storage);
  layout.destroy();
  const next = page(1600), again = mount(next, {storage});                      // the next visit
  out.next = {vars: vars(next.body), right: next.right.className, left: aria(splitOf(next.body, 'left')), state: again.state()};
  await next.right.querySelector('.cw-rail').dispatch('click');
  out.shown = px(next.body, 'right');
  // a stored value that is not a layout, or is out of range
  const junk = memory({[KEY]: 'garbage{'}), a = page(1600);
  mount(a, {storage: junk});
  out.junk = [vars(a.body), junk.calls.set];
  const wild = memory({[KEY]: JSON.stringify({left: 9999, right: 1, leftHidden: 'yes', rightHidden: true})}), b = page(1600);
  mount(b, {storage: wild});
  out.wild = [vars(b.body), b.left.className, b.right.className];
""")
    assert out["written"] == 0
    assert out["saved"] == {"left": 296, "right": 436, "leftHidden": False, "rightHidden": True}
    assert out["next"] == {"vars": {"--cw-left": "296px", "--cw-right": "36px"}, "right": "os-col cw-right cw-collapsed", "left": ["296", "200", "520"],
                           "state": {"left": 296, "right": 436, "leftHidden": False, "rightHidden": True}}
    assert out["shown"] == "436px"
    assert out["junk"] == [{"--cw-left": "280px", "--cw-right": "420px"}, 0]
    assert out["wild"] == [{"--cw-left": "520px", "--cw-right": "36px"}, "os-col cw-left", "os-col cw-right cw-collapsed"]


@node
def test_storage_that_throws_or_is_missing_never_breaks_the_layout(tmp_path):
    out = run(tmp_path, """
  const use = async (p, note) => {                                              // the layout works whatever the memory does
    const L = splitOf(p.body, 'left');
    await key(L, 'ArrowRight'); await key(L, 'ArrowRight', {shiftKey: true});
    await p.rightHead.querySelector('.cw-hide').dispatch('click');
    await L.dispatch('pointerdown', {clientX: 0, pointerId: 1}); await L.dispatch('pointermove', {clientX: 4, pointerId: 1}); await L.dispatch('pointerup', {pointerId: 1});
    out[note] = vars(p.body);
  };
  const wide = (extra) => { const p = page(1600); CL.mount(p.body, {left: p.left, right: p.right, ...extra}); return p; };     // no window, and the storage as given
  // a storage that refuses every read and write
  await use(wide({storage: broken()}), 'broken');
  // no localStorage at all (node): the global is not there
  out.hasGlobal = typeof ctx.localStorage;
  await use(wide({}), 'missing');
  // a localStorage whose very access throws (blocked site data)
  let reads = 0;
  Object.defineProperty(ctx, 'localStorage', {get() { reads += 1; throw new Error('access denied'); }, configurable: true});
  await use(wide({}), 'denied');
  out.deniedReads = reads;
  // a storage that answers with something odd
  await use(wide({storage: {getItem: () => 42, setItem: () => { throw new Error('nope'); }}}), 'odd');
  // the global localStorage is used when no storage is given
  const real = memory({[KEY]: JSON.stringify({left: 333, right: 444, leftHidden: true})});
  Object.defineProperty(ctx, 'localStorage', {value: real, configurable: true, writable: true});
  const p = wide({});
  out.global = vars(p.body);
  await key(splitOf(p.body, 'right'), 'Home');
  out.globalSaved = saved(real);
""")
    expected = {"--cw-left": "364px", "--cw-right": "36px"}                  # 280 + 16 + 64 by the keys, 4 px more by the pointer; the right column hidden
    assert out["broken"] == out["missing"] == out["denied"] == out["odd"] == expected
    assert out["hasGlobal"] == "undefined" and out["deniedReads"] > 0                       # the throwing accessor was really reached
    assert out["global"] == {"--cw-left": "36px", "--cw-right": "444px"}
    assert out["globalSaved"] == {"left": 333, "right": 280, "leftHidden": True, "rightHidden": False}


# -- the window -------------------------------------------------------------------------------------------------------------------------------------------
@node
def test_a_resize_of_the_window_shows_what_fits_and_the_asked_widths_come_back_when_the_window_grows(tmp_path):
    out = run(tmp_path, """
  const win = windowOf(), p = page(1600), layout = mount(p, {win});
  const L = splitOf(p.body, 'left'), R = splitOf(p.body, 'right');
  out.listening = win.count('resize');
  p.body.size = 900; win.fire('resize');
  out.small = [vars(p.body), aria(L), aria(R)];
  p.body.size = 700; win.fire('resize');
  out.tiny = [vars(p.body), aria(L), aria(R)];
  p.body.size = 1600; win.fire('resize');
  out.back = [vars(p.body), aria(L), aria(R)];
  p.body.size = 900; layout.refresh();
  out.refreshed = vars(p.body);
  out.state = layout.state();
""")
    assert out["listening"] == 1
    assert out["small"] == [{"--cw-left": "215px", "--cw-right": "305px"}, ["215", "200", "215"], ["305", "280", "305"]]
    assert out["tiny"] == [{"--cw-left": "200px", "--cw-right": "280px"}, ["200", "200", "200"], ["280", "280", "280"]]          # the narrowest: the card gets what is left
    assert out["back"] == [{"--cw-left": "280px", "--cw-right": "420px"}, ["280", "200", "520"], ["420", "280", "720"]]
    assert out["refreshed"] == {"--cw-left": "215px", "--cw-right": "305px"}
    assert out["state"] == {"left": 215, "right": 305, "leftHidden": False, "rightHidden": False}


@node
def test_a_resize_observer_on_the_grid_does_the_same_and_is_disconnected_on_destroy(tmp_path):
    out = run(tmp_path, """
  const made = [];
  ctx.ResizeObserver = class { constructor(cb) { this.cb = cb; this.observed = []; this.disconnected = false; made.push(this); } observe(el) { this.observed.push(el); } disconnect() { this.disconnected = true; } };
  const p = page(1600), layout = mount(p);
  out.observer = [made.length, made[0].observed[0] === p.body];
  p.body.size = 900; made[0].cb([]);
  out.small = vars(p.body);
  layout.destroy();
  out.disconnected = made[0].disconnected;
""")
    assert out["observer"] == [1, True] and out["small"] == {"--cw-left": "215px", "--cw-right": "305px"} and out["disconnected"] is True


@node
def test_destroy_takes_the_splitters_and_buttons_away_and_a_screen_that_left_the_page_stops_listening(tmp_path):
    out = run(tmp_path, """
  const win = windowOf(), p = page(1600), layout = mount(p, {win});
  await p.leftHead.querySelector('.cw-hide').dispatch('click');
  layout.destroy();
  out.destroyed = {resize: win.count('resize'), splitters: p.body.querySelectorAll('.cw-split').length, hide: p.body.querySelectorAll('.cw-hide').length, rails: p.body.querySelectorAll('.cw-rail').length,
    style: p.body.getAttribute('style'), kids: p.body.children.map((c) => c.className), collapsed: p.left.classList.contains('cw-collapsed'), head: p.left.children.map((c) => c.className)};
  layout.destroy();                                                             // twice is harmless
  p.body.size = 800; win.fire('resize'); layout.refresh();
  out.afterwards = p.body.getAttribute('style');
  // the screen was left without anyone calling destroy: the first resize notices
  const w2 = windowOf(), q = page(1600);
  mount(q, {win: w2});
  out.before = w2.count('resize');
  q.body.remove();
  w2.fire('resize');
  out.gone = [w2.count('resize'), q.body.querySelectorAll('.cw-split').length];
""")
    assert out["destroyed"] == {"resize": 0, "splitters": 0, "hide": 0, "rails": 0, "style": None, "kids": ["os-col cw-left", "os-col cw-centre", "os-col cw-right"],
                                "collapsed": False, "head": ["os-col-head", "os-scroll"]}
    assert out["afterwards"] is None
    assert out["before"] == 1 and out["gone"] == [0, 0]


# -- the stylesheet: the narrow window is CSS only ----------------------------------------------------------------------------------------------------------
CSS = (UI / "card.css").read_text(encoding="utf-8")
STYLES = (UI / "styles.css").read_text(encoding="utf-8")
_start = CSS.index("/* ==== resizable and hideable side columns")
_end = CSS.index("\n}\n", CSS.index("@media (prefers-reduced-motion:reduce)", _start)) + 3
SECTION = CSS[_start:_end]                                                            # this section only: the rest of the file is the editor's own


def test_the_grid_is_made_of_the_two_widths_and_two_splitter_columns_and_the_stacking_rules_are_still_there():
    assert ".cw .os-body {grid-template-columns:var(--cw-left,280px) 10px minmax(0,1fr) 10px var(--cw-right,420px);column-gap:0}" in CSS     # the defaults are those of the script
    assert "minmax(300px,360px)" not in CSS and "minmax(230px,280px)" not in CSS
    assert "@media (max-width:1000px) {\n  .cw .os-body {grid-template-columns:minmax(0,1fr) !important}" in CSS
    assert re.search(r"@media \(max-width:\d+px\) \{[^@]*\n  \.os-body \{grid-template-columns:minmax\(0,1fr\) !important\}", STYLES)


def test_splitters_and_buttons_are_hidden_where_the_columns_are_stacked_and_only_there_the_collapsed_look_exists():
    """styles.css stacks every ``.os-body`` below 1100 px (card.css repeats it at 1000 px), so the wide-only rules must be the exact opposite of that breakpoint."""
    stacked = re.search(r"@media \(max-width:(\d+)px\) \{[^@]*\n  \.os-body \{grid-template-columns:minmax\(0,1fr\) !important\}", STYLES).group(1)
    gate = f"@media not all and (max-width:{stacked}px)"
    assert gate in SECTION
    before, wide = SECTION[:SECTION.index(gate)], SECTION[SECTION.index(gate):]
    assert ".cw .cw-split,.cw .cw-hide,.cw .cw-rail {display:none}" in before
    for rule in (".cw .cw-split {display:block", ".cw .cw-hide {display:inline-flex", ".cw .cw-collapsed>:not(.cw-rail) {display:none !important}", ".cw .cw-collapsed>.cw-rail {display:inline-flex"):
        assert rule in wide and rule not in before, rule
    assert "cw-collapsed" not in before and "display:block" not in before


def test_the_splitter_is_a_ten_pixel_target_with_a_visible_focus_ring_and_the_colours_of_the_app():
    assert "cursor:col-resize" in SECTION and "touch-action:none" in SECTION and "user-select:none" in SECTION
    assert ".cw .cw-split:focus-visible {outline:2px solid var(--accent)" in SECTION
    assert "background:var(--line-2)" in SECTION and ".cw .cw-split:hover::before" in SECTION and "var(--accent)" in SECTION          # the themes redefine these variables
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", SECTION)                                  # no colour of its own: dark and light themes both follow the variables
    assert ".cw .cw-split-off {visibility:hidden" in SECTION                                 # a hidden column's splitter keeps its grid cell


# -- the screen ------------------------------------------------------------------------------------------------------------------------------------------
@node
def test_the_card_screen_mounts_the_layout_remembers_it_between_visits_and_takes_it_away_when_the_screen_goes(tmp_path):
    out = run_screen(tmp_path, r"""
  El.prototype.getBoundingClientRect = function () { return {left: 0, top: 0, width: 1600, height: 900}; };      // a wide window
  const KEY = 'cw.layout.v1';
  const store = {data: {}, getItem(k) { return k in this.data ? this.data[k] : null; }, setItem(k, v) { this.data[k] = String(v); }};
  ctx.localStorage = store;
  srv.seed('front', 'text', 1);
  await open();
  let body = root.querySelector('.cw-body');
  out.order = body.children.map((c) => c.className);
  out.style = body.getAttribute('style');
  const headOf = (col) => root.querySelector(col).querySelector('.os-col-head');
  out.heads = [headOf('.cw-left'), headOf('.cw-right')].map((head) => head.children.map((c) => c.localName + ':' + c.textContent));
  const id = lastShow().elements[0].id;
  canvas().handlers.onSelect([id]);                                                                    // the screen fills the title of the right column again
  out.selectedHead = headOf('.cw-right').children.map((c) => c.localName + ':' + c.textContent);
  // hide the right column: its contents stay in the DOM and keep being filled
  await root.querySelector('.cw-right').querySelector('.cw-hide').dispatch('click');
  out.hidden = [root.querySelector('.cw-right').className, body.getAttribute('style'), JSON.parse(store.data[KEY])];
  canvas().handlers.onSelect([]);
  const emptyTitle = rightTitle();
  canvas().handlers.onSelect([id]);
  out.stillFilled = [rightTitle() !== emptyTitle, !!root.querySelector('.cw-right').querySelector('.os-scroll'), !!root.querySelector('.cw-inspector')];
  // the next visit
  await open();
  body = root.querySelector('.cw-body');
  out.revisit = [root.querySelector('.cw-right').className, root.querySelector('.cw-left').className, body.getAttribute('style')];
  // the screen goes: the first key it sees afterwards disposes it, layout included
  root.remove();
  await doc.dispatch('keydown', {key: 'x'});
  out.disposed = [body.querySelectorAll('.cw-split').length, body.querySelectorAll('.cw-hide').length, canvas().destroyed];
""")
    assert out["order"] == ["os-col cw-left", "cw-split cw-split-left", "os-col cw-centre", "cw-split cw-split-right", "os-col cw-right"]
    assert out["style"] == "--cw-left:280px;--cw-right:420px"
    assert out["heads"][0] == ["h3:Add", "button:Hide panel"] and out["heads"][1][1] == "button:Hide panel" and out["heads"][1][0].startswith("h3:")
    assert out["selectedHead"][1] == "button:Hide panel" and out["selectedHead"][0] != out["heads"][1][0]
    assert out["hidden"] == ["os-col cw-right cw-collapsed", "--cw-left:280px;--cw-right:36px", {"left": 280, "right": 420, "leftHidden": False, "rightHidden": True}]
    assert out["stillFilled"] == [True, True, True]
    assert out["revisit"] == ["os-col cw-right cw-collapsed", "os-col cw-left", "--cw-left:280px;--cw-right:36px"]
    assert out["disposed"] == [0, 0, True]
