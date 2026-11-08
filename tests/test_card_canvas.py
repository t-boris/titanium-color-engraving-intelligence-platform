"""feature-2 (REQ-001, REQ-002): the card canvas, ``screens/card-canvas.js``. Its geometry is checked as numbers (resize about the opposite
handle on a rotated element, minimum size, aspect lock, rotation steps, snapping, hit order), then the component is run in node over the
small DOM of ui_dom.js: the drawing of a card side, the selection and its handles, simulated pointer sequences and their handler calls,
the keyboard, the wheel, and the clean-up of ``destroy()``."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_ui_files import nullable_children, offending_lines
from titanium_platform.api.app import UI_DIR

SCRIPTS = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
SOURCE = (UI_DIR / "screens" / "card-canvas.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = r"""
const {context, load} = require(%(dom)s);
const ctx = context({});
%(before)s
load(ctx, %(ui)s, [{code: 'const App = {}, I18N = {};'}, 'screens/card-canvas.js', {code: 'globalThis.CardCanvas = CardCanvas;'}]);
const CC = ctx.CardCanvas, M = CC.math, doc = ctx.document;
const PX = 10;                                                    // screen pixels per mm in these tests
const rectD = (x0, y0, x1, y1) => `M${x0} ${y0} L${x1} ${y0} L${x1} ${y1} L${x0} ${y1} Z`;
/** A view element as the server sends it: a rectangle of ink centred on (x, y). */
const el = (id, type, x, y, w, h, extra = {}) => ({id, type, name: id, x, y, width: w, height: h, rotation: 0, group: null, d: rectD(x - w / 2, y - h / 2, x + w / 2, y + h / 2),
  bounds: [x - w / 2, y - h / 2, x + w / 2, y + h / 2], empty: false, problems: [], warnings: [], ...extra});
const NAMES = ['onSelect', 'onMove', 'onResize', 'onRotate', 'onDelete', 'onDuplicate', 'onUndo', 'onRedo', 'onEscape'];
/** A canvas on a page, drawn at 10 px per mm with the picture's corner at (100, 50) on the screen. */
function mount(view, only) {
  const host = doc.createElement('div');
  doc.body.append(host);
  const calls = [];
  const handlers = {};
  for (const name of only || NAMES) handlers[name] = (...args) => calls.push([name, ...args]);
  const canvas = CC.create(host, handlers);
  const stage = host.children[0], svg = stage.querySelector('svg');
  const size = view.size_mm || {width: 85, height: 54};
  const rect = {left: 100, top: 50, width: (size.width + 20) * PX, height: (size.height + 20) * PX};
  svg.getBoundingClientRect = () => rect;
  stage.getBoundingClientRect = () => ({left: 100, top: 50, width: rect.width, height: rect.height});
  canvas.show(view);
  const at = (x, y) => ({clientX: rect.left + (x + 10) * PX, clientY: rect.top + (y + 10) * PX});
  const fire = (type, x, y, extra = {}) => stage.dispatch(type, {...at(x, y), button: 0, pointerId: 1, ...extra});
  const key = (name, extra = {}) => { const e = {key: name, prevented: false, preventDefault() { e.prevented = true; }, ...extra}; stage.dispatch('keydown', e); return e; };
  const drag = (from, to, extra = {}) => { fire('pointerdown', from[0], from[1], extra); fire('pointermove', to[0], to[1], extra); fire('pointerup', to[0], to[1], extra); };
  const click = (x, y, extra = {}) => { fire('pointerdown', x, y, extra); fire('pointerup', x, y, extra); };
  const q = (selector) => svg.querySelectorAll(selector);
  const group = (id) => q('g').find((g) => g.getAttribute('data-id') === id);
  const handles = () => q('[data-handle]').map((h) => h.getAttribute('data-handle'));
  const take = () => calls.splice(0, calls.length);
  return {host, canvas, stage, svg, calls, at, fire, key, drag, click, q, group, handles, take, rect};
}
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;
const out = {};
%(body)s
console.log(JSON.stringify(out));
"""


def run(tmp_path, body: str, before: str = "") -> dict:
    script = tmp_path / "canvas.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "ui": json.dumps(str(UI_DIR) + "/"), "body": body,
                                 "before": before}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout)


def flat(value):
    return [n for item in value for n in flat(item)] if isinstance(value, list) else [value]


def approx_all(got, want, eps=1e-6):
    """Numbers, or lists of them to any depth, equal within ``eps``."""
    assert flat(got) == pytest.approx(flat(want), abs=eps), (got, want)


# -- static --------------------------------------------------------------------------------------------------------------------------------
def test_the_canvas_follows_the_rules_every_ui_script_follows():
    assert not re.search("[" + chr(0x0400) + "-" + chr(0x04FF) + "]", SOURCE)                                    # no Cyrillic literal in the code
    assert offending_lines(SOURCE) == [] and nullable_children(SOURCE) == []
    assert not re.search(r"querySelectorAll\([^()]*\)\s*\.\s*(map|filter|find|findIndex|some|every|reduce|includes|slice|flatMap)\b", SOURCE)
    assert "innerHTML" not in SOURCE and "location.href" not in SOURCE and "window.open(" not in SOURCE
    assert not re.search(r"\.(className|style|dataset)\s*=[^=]", SOURCE)               # an SVG element's className is read-only; style goes through attributes
    assert "isPointInFill" not in SOURCE                                              # the same hit test in node and in the browser


def test_the_canvas_is_loaded_before_the_screen_that_hosts_it_once_both_are_in_index_html():
    if "/screens/card-canvas.js" not in SCRIPTS:
        pytest.skip("card-canvas.js is not in index.html yet (the lead adds it)")
    assert SCRIPTS.count("/screens/card-canvas.js") == 1
    if "/screens/card-work.js" in SCRIPTS:
        assert SCRIPTS.index("/screens/card-canvas.js") < SCRIPTS.index("/screens/card-work.js")


# -- geometry as numbers --------------------------------------------------------------------------------------------------------------------
@node
def test_the_box_and_its_handles_turn_clockwise_with_the_rotation(tmp_path):
    got = run(tmp_path, """
  const e = {x: 50, y: 30, width: 20, height: 10, rotation: 90};
  out.box = M.orientedBox(e);
  out.turned = M.handlePositions(e, 6);
  out.plain = M.handlePositions({x: 50, y: 30, width: 20, height: 10, rotation: 0}, 6);
  out.names = {card: M.handleNames({type: 'qr', width: 20, height: 20}, 10), free: M.handleNames({type: 'shape', width: 20, height: 20}, 10),
               tiny: M.handleNames({type: 'shape', width: 2, height: 20}, 10), thin: M.handleNames({type: 'frame', width: 20, height: 2}, 10)};
""")
    approx_all(got["box"], [[55, 20], [55, 40], [45, 40], [45, 20]])                  # the top-left corner went to the top right: clockwise
    approx_all(got["turned"]["rotate"], [61, 30])                                    # the handle that was above the box is now on its right
    approx_all(got["turned"]["e"], [50, 40])
    approx_all(got["turned"]["n"], [55, 30])
    approx_all(got["plain"]["nw"], [40, 25])
    approx_all(got["plain"]["se"], [60, 35])
    approx_all(got["plain"]["n"], [50, 25])
    approx_all(got["plain"]["rotate"], [50, 19])
    assert got["names"]["card"] == ["nw", "ne", "se", "sw", "rotate"]                # text, QR, icon, image: corners only
    assert got["names"]["free"] == ["nw", "ne", "se", "sw", "n", "s", "e", "w", "rotate"]
    assert got["names"]["tiny"] == ["nw", "ne", "se", "sw", "e", "w", "rotate"]       # a side shorter than four handles on screen offers no edge handle
    assert got["names"]["thin"] == ["nw", "ne", "se", "sw", "n", "s", "rotate"]


@node
def test_resize_on_a_plain_box_moves_the_dragged_side_and_keeps_the_opposite_one(tmp_path):
    got = run(tmp_path, """
  const e = {x: 50, y: 30, width: 20, height: 10, rotation: 0};
  out.free = M.resizeFromHandle(e, 'se', [80, 40], {});
  out.aspect = M.resizeFromHandle(e, 'se', [80, 40], {keepAspect: true});
  out.east = M.resizeFromHandle(e, 'e', [75, 99], {});
  out.eastAspect = M.resizeFromHandle(e, 'e', [75, 99], {keepAspect: true});
  out.north = M.resizeFromHandle(e, 'n', [0, 10], {});
  out.northwest = M.resizeFromHandle(e, 'nw', [30, 15], {});
  out.past = M.resizeFromHandle(e, 'se', [35, 20], {});
  out.pastAspect = M.resizeFromHandle(e, 'se', [35, 20], {keepAspect: true});
  out.custom = M.resizeFromHandle(e, 'se', [35, 20], {minMm: 2});
  out.unknown = M.resizeFromHandle(e, 'rotate', [35, 20], {});
  out.line = M.resizeFromHandle({x: 10, y: 10, width: 20, height: 0, rotation: 0}, 'e', [40, 10], {keepAspect: true});
""")
    assert got["free"] == pytest.approx({"x": 60, "y": 32.5, "width": 40, "height": 15})
    assert got["aspect"] == pytest.approx({"x": 59, "y": 34.5, "width": 38, "height": 19})       # the corner slides along its diagonal
    assert got["east"] == pytest.approx({"x": 57.5, "y": 30, "width": 35, "height": 10})
    assert got["eastAspect"] == pytest.approx({"x": 57.5, "y": 30, "width": 35, "height": 17.5})  # the other side grows about the axis
    assert got["north"] == pytest.approx({"x": 50, "y": 22.5, "width": 20, "height": 25})
    assert got["northwest"] == pytest.approx({"x": 45, "y": 25, "width": 30, "height": 20})
    assert got["past"] == pytest.approx({"x": 40.25, "y": 25.25, "width": 0.5, "height": 0.5})    # never smaller than 0.5 mm
    assert got["pastAspect"] == pytest.approx({"x": 40.5, "y": 25.25, "width": 1, "height": 0.5})  # the proportions hold at the minimum
    assert got["custom"]["width"] == 2 and got["custom"]["height"] == 2
    assert got["unknown"] == pytest.approx({"x": 50, "y": 30, "width": 20, "height": 10})
    assert got["line"]["width"] == pytest.approx(40) and got["line"]["height"] == 0              # from the fixed end at x 0 to the pointer; a line has no proportions to keep


@node
def test_resize_keeps_the_opposite_handle_where_it_was_on_a_rotated_element(tmp_path):
    got = run(tmp_path, """
  const rows = [];
  for (const rotation of [30, 90, -47, 180]) {
    const e = {x: 50, y: 30, width: 20, height: 10, rotation};
    for (const [handle, anchor] of [['se', 'nw'], ['nw', 'se'], ['ne', 'sw'], ['sw', 'ne'], ['e', 'w'], ['w', 'e'], ['n', 's'], ['s', 'n']]) {
      for (const p of [[70, 50], [20, 5], [60, 10], [35, 45], [50, 30]]) {
        for (const keepAspect of [false, true]) {
          const next = M.resizeFromHandle(e, handle, p, {keepAspect});
          rows.push({rotation, handle, keepAspect, before: M.handlePositions(e)[anchor], after: M.handlePositions({...next, rotation})[anchor],
            width: next.width, height: next.height});
        }
      }
    }
  }
  out.rows = rows;
  // dragging the corner of a box turned 90 degrees to where the unrotated corner would be moves it the same way
  out.turned = M.resizeFromHandle({x: 50, y: 30, width: 20, height: 10, rotation: 90}, 'se', [45, 60], {});
""")
    assert len(got["rows"]) == 4 * 8 * 5 * 2
    for row in got["rows"]:
        approx_all(row["after"], row["before"], 1e-9)                                  # the anchor does not move, whichever way it is pulled
        assert row["width"] >= 0.5 - 1e-12 and row["height"] >= 0.5 - 1e-12
    # the box turned 90 degrees clockwise lies along the card's y with its own width: its se corner is at (45, 40) and the anchor nw at (55, 20);
    # pulling the corner to (45, 60) makes the box's own width 40 (from y 20 to y 60) and leaves its height at 10
    assert got["turned"] == pytest.approx({"x": 50, "y": 40, "width": 40, "height": 10})


@node
def test_the_rotation_points_the_handle_at_the_pointer_in_whole_degrees_or_steps(tmp_path):
    got = run(tmp_path, """
  const e = {x: 50, y: 30, width: 20, height: 10, rotation: 12};
  out.dir = [[50, 20], [60, 30], [50, 40], [40, 30]].map((p) => M.rotationFromPoint(e, p, 0));
  out.free = M.rotationFromPoint(e, [58, 21], 1);
  out.steps = M.rotationFromPoint(e, [58, 21], 15);
  out.offset = M.rotationFromPoint(e, [60, 30], 0, 3);
  out.centre = M.rotationFromPoint(e, [50, 30], 15);
  out.range = [M.normalizeAngle(190), M.normalizeAngle(-190), M.normalizeAngle(360), M.normalizeAngle(-180), M.normalizeAngle(540), M.normalizeAngle(-0.0)];
""")
    approx_all(got["dir"], [0, 90, 180, -90])
    assert got["free"] == 42 and got["steps"] == 45
    assert got["offset"] == pytest.approx(87)
    assert got["centre"] == 12                                                        # the pointer on the centre leaves the rotation alone
    assert got["range"] == [-170, 170, 0, 180, 180, 0]


@node
def test_a_move_lands_on_the_grid_and_is_pulled_to_the_cards_edges_and_centre(tmp_path):
    got = run(tmp_path, """
  const size = {width: 85, height: 54};
  const e = {x: 20, y: 20, width: 10, height: 10, rotation: 0};
  out.grid = M.snapMove(e, 3.04, 1.26, size, true);
  out.alt = M.snapMove(e, 3.04, 1.26, size, false);
  out.centre = M.snapMove(e, 22.3, 0, size, true);
  out.left = M.snapMove({...e, x: 10}, -4.8, 5, size, true);
  out.right = M.snapMove({...e, x: 70}, 9.7, 5, size, true);
  out.top = M.snapMove(e, 5, -14.7, size, true);
  out.middle = M.snapMove({...e, y: 20}, 0, 6.8, size, true);
  out.beyond = M.snapMove(e, 23.2, 0, size, true);
  out.turned = M.snapMove({x: 20, y: 20, width: 10, height: 2, rotation: 90}, -18.6, 0, size, true);
""")
    assert got["grid"] == {"dx": pytest.approx(3.0), "dy": pytest.approx(1.3), "guides": []}
    assert got["alt"] == {"dx": 3.04, "dy": 1.26, "guides": []}                       # Alt: exactly where the pointer is
    assert got["centre"]["dx"] == pytest.approx(22.5) and got["centre"]["guides"] == [{"axis": "x", "at": 42.5}]
    assert got["left"]["dx"] == pytest.approx(-5) and {"axis": "x", "at": 0} in got["left"]["guides"]
    assert got["right"]["dx"] == pytest.approx(10) and {"axis": "x", "at": 85} in got["right"]["guides"]    # the right edge reaches 85
    assert got["top"]["dy"] == pytest.approx(-15) and {"axis": "y", "at": 0} in got["top"]["guides"]
    assert got["middle"]["dy"] == pytest.approx(7) and {"axis": "y", "at": 27} in got["middle"]["guides"]
    assert got["beyond"]["guides"] == [] and got["beyond"]["dx"] == pytest.approx(23.2)      # 0.7 mm from the centre line: out of reach
    assert got["turned"]["dx"] == pytest.approx(-19) and {"axis": "x", "at": 0} in got["turned"]["guides"]   # the box of a turned element is its upright hull


@node
def test_the_topmost_element_under_the_point_is_found_by_its_ink_or_its_box(tmp_path):
    got = run(tmp_path, """
  const a = el('a', 'shape', 25, 25, 20, 20), b = el('b', 'shape', 35, 35, 20, 20);
  const frame = el('frame', 'frame', 20, 20, 40, 40, {d: rectD(0, 0, 40, 40) + ' ' + rectD(10, 10, 30, 30)});
  const line = el('line', 'shape', 35, 80, 50, 0.4, {d: 'M10 80 L60 80', bounds: [10, 80, 60, 80]});
  const text = el('text', 'text', 20, 120, 30, 10, {d: rectD(12, 118, 14, 122)});
  const gone = el('gone', 'qr', 20, 150, 10, 10, {d: '', empty: true, bounds: null});
  const turned = el('turned', 'text', 100, 20, 30, 10, {rotation: 90, d: rectD(98, 5, 102, 35)});
  const hit = (list, p, tol = 0) => M.hitTest(list, p, tol);
  out.order = [hit([a, b], [30, 30]), hit([b, a], [30, 30]), hit([a, b], [16, 16]), hit([a, b], [52, 52]), hit([], [1, 1])];
  out.tolerance = [hit([a], [36, 25]), hit([a], [36, 25], 1.5), hit([a], [36, 25], 0.5)];
  out.frame = [hit([frame], [20, 20]), hit([frame], [5, 20]), hit([frame], [11, 20]), hit([frame], [11, 20], 1.2), hit([a, frame], [25, 25]), hit([frame, a], [25, 25])];
  out.thin = [hit([line], [30, 81.5]), hit([line], [30, 81.5], 2), hit([line], [30, 80])];
  out.box = [hit([text], [28, 123]), hit([text], [40, 123]), hit([text], [40, 123], 6), hit([turned], [100, 8]), hit([turned], [92, 20])];
  out.empty = [hit([gone], [22, 148]), hit([gone], [30, 150])];
  out.noInk = hit([{id: 'x', type: 'shape', x: 5, y: 5, width: 4, height: 4, rotation: 0}], [6, 6]);
""")
    assert got["order"] == ["b", "a", "a", None, None]                               # the last of the list is on top
    assert got["tolerance"] == [None, "a", None]                                     # 1 mm outside the edge: found with 1.5 mm of slack, not with 0.5
    assert got["frame"] == [None, "frame", None, "frame", "a", "a"]                  # the hollow middle of a frame is not the frame
    assert got["thin"] == [None, "line", "line"]                                     # a thin line is found within the tolerance
    assert got["box"] == ["text", None, "text", "turned", None]                      # text is taken anywhere in its (turned) box
    assert got["empty"] == ["gone", None]
    assert got["noInk"] == "x"


@node
def test_pointer_and_card_coordinates_convert_into_each_other(tmp_path):
    got = run(tmp_path, """
  const size = {width: 85, height: 54};
  const rect = {left: 100, top: 50, width: 1050, height: 740};
  const bare = {left: 100, top: 50, width: 850, height: 540};
  const wide = {left: 100, top: 50, width: 2100, height: 740};            // a box wider than the drawing: it is centred in it
  out.origin = M.pointToMm(200, 150, rect, size, null);
  out.corner = M.pointToMm(100, 50, rect, size, null);
  out.zoomGiven = M.pointToMm(300, 250, rect, size, 10);
  out.wide = M.pointToMm(100 + 525 + 100, 150, wide, size, null);
  out.back = M.mmToClient(12.5, 7.25, wide, size, null);
  out.round = [[3.3, 40.1], [-4, 60], [85, 54]].map(([x, y]) => M.pointToMm(...M.mmToClient(x, y, wide, size, null), wide, size, null));
  out.pad = [M.pointToMm(100, 50, bare, size, null, 0), M.pointToMm(950, 590, bare, size, null, 0)];
""")
    approx_all(got["origin"], [0, 0])
    approx_all(got["corner"], [-10, -10])                                            # the picture shows 10 mm around the card
    approx_all(got["zoomGiven"], [10, 10])
    approx_all(got["wide"], [0, 0])
    approx_all(got["back"], [100 + 525 + 225, 50 + 172.5], 1e-9)
    for have, want in zip(got["round"], [[3.3, 40.1], [-4, 60], [85, 54]]):
        approx_all(have, want, 1e-9)
    approx_all(got["pad"], [[0, 0], [85, 54]])                                       # without a margin the card fills its box


@node
def test_the_provisional_picture_maps_the_old_box_onto_the_new_one(tmp_path):
    got = run(tmp_path, """
  const e = {x: 50, y: 30, width: 20, height: 10, rotation: 30};
  const next = {x: 60, y: 35, width: 40, height: 15, rotation: 75};
  const [a, b, c, d, tx, ty] = M.previewMatrix(e, next);
  out.mapped = M.orientedBox(e).map(([x, y]) => [a * x + c * y + tx, b * x + d * y + ty]);
  out.target = M.orientedBox(next);
  out.move = M.previewMatrix(e, {x: 55, y: 28});
  out.same = M.previewMatrix(e, {});
  out.flat = M.previewMatrix({x: 1, y: 1, width: 0, height: 0, rotation: 0}, {width: 5});
  out.path = [M.parsePath('M0 0 L10 0 L10 10 Z M2 2 l2 0 l0 2 z'), M.parsePath('M0,0H10V10H0Z'), M.parsePath('M1e-1 2 3 4 5 6'), M.parsePath('')];
""")
    for have, want in zip(got["mapped"], got["target"]):
        approx_all(have, want, 1e-6)                                                  # each corner goes to the same corner of the new box
    approx_all(got["move"], [1, 0, 0, 1, 5, -2], 1e-9)                               # a move is a translation
    approx_all(got["same"], [1, 0, 0, 1, 0, 0], 1e-9)
    assert all(v == v for v in got["flat"])                                          # a box without width or height does not divide by zero
    assert got["path"][0] == [[[0, 0], [10, 0], [10, 10]], [[2, 2], [4, 2], [4, 4]]]
    assert got["path"][1] == [[[0, 0], [10, 0], [10, 10], [0, 10]]]
    assert got["path"][2] == [[[0.1, 2], [3, 4], [5, 6]]] and got["path"][3] == []   # pairs after M are lines


# -- the drawing ----------------------------------------------------------------------------------------------------------------------------
VIEW = """
const view = {size_mm: {width: 85, height: 54}, grid: true, selection: [], elements: [
  el('a', 'shape', 30, 20, 20, 10),
  el('b', 'text', 60, 20, 24, 8, {rotation: 20, warnings: [{code: 'qr_module', message: 'Module is smaller than 0.40 mm'}]}),
  el('c', 'qr', 20, 40, 10, 10, {d: '', empty: true, bounds: null, problems: ['nothing to engrave']}),
  el('g1', 'icon', 70, 45, 8, 8, {group: 'logo'}), el('g2', 'icon', 78, 45, 8, 8, {group: 'logo'})]};
"""


@node
def test_show_draws_the_card_to_scale_with_one_path_per_element_in_z_order(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  out.viewBox = t.svg.getAttribute('viewBox');
  out.card = t.q('rect').filter((r) => r.classList.contains('cc-card')).map((r) => [r.getAttribute('width'), r.getAttribute('height'), r.getAttribute('rx')]);
  out.order = t.q('g').filter((g) => g.classList.contains('cc-el')).map((g) => g.getAttribute('data-id'));
  out.ink = t.q('path').filter((p) => p.classList.contains('cc-ink')).map((p) => [p.getAttribute('d'), p.getAttribute('fill-rule'), p.getAttribute('fill')]);
  out.expected = view.elements.filter((e) => e.d).map((e) => e.d);
  out.texts = t.q('text').map((x) => x.textContent);
  out.grid = t.q('path').filter((p) => p.classList.contains('cc-grid-minor') || p.classList.contains('cc-grid-major')).map((p) => p.getAttribute('class'));
  const major = t.q('path').find((p) => p.classList.contains('cc-grid-major')).getAttribute('d');
  out.major = [major.includes('M10 0V54'), major.includes('M0 10H85'), major.includes('M80 0V54'), major.includes('M85 0V54')];
  out.clip = [t.q('clipPath').length, t.q('path').find((p) => p.classList.contains('cc-grid-major')).getAttribute('clip-path')];
  t.canvas.show({...view, size_mm: {width: 100, height: 60}, grid: false});
  out.big = [t.svg.getAttribute('viewBox'), t.q('path').filter((p) => p.classList.contains('cc-grid-major')).length, t.q('g').filter((g) => g.classList.contains('cc-el')).length,
             t.q('text').map((x) => x.textContent).pop()];
  const second = mount(view);
  out.styles = doc.body.querySelectorAll('style').length;
  out.label = t.stage.getAttribute('aria-label');
  out.focusable = [t.stage.getAttribute('tabindex'), t.stage.getAttribute('role')];
""")
    assert got["viewBox"] == "-10 -10 105 74"                                         # 1 unit is 1 mm; 10 mm of room around the 85 x 54 card
    assert got["card"] == [["85", "54", "3"]]
    assert got["order"] == ["a", "b", "c", "g1", "g2"]
    assert [row[0] for row in got["ink"]] == [d for d in got["expected"]] and len(got["ink"]) == 4          # the empty element has no ink
    assert all(row[1] == "evenodd" and row[2] == "currentColor" for row in got["ink"])
    assert "85 × 54 mm" in got["texts"] and {"0", "10", "50", "80"} <= set(got["texts"])             # the scale note and the ruler
    assert got["grid"] == ["cc-grid-minor", "cc-grid-major"]                          # a millimetre grid at 10 px per mm, with the 10 mm lines stronger
    assert got["major"] == [True, True, True, False]
    assert got["clip"][0] == 1 and got["clip"][1].startswith("url(#cc-clip-")
    assert got["big"] == ["-10 -10 120 80", 0, 5, "100 × 60 mm"]
    assert got["styles"] == 1                                                         # the style block is injected once for any number of canvases
    assert "Escape" in got["label"] and got["focusable"] == ["0", "group"]


@node
def test_a_picture_engraved_as_a_photo_is_drawn_as_its_bitmap_with_a_dotted_outline_and_stays_selectable_and_movable(tmp_path):
    got = run(tmp_path, VIEW + """
  const photo = el('p', 'image', 40, 30, 30, 20, {raster: {url: '/api/card-works/7/elements/p/raster.png?v=3', width_px: 300, height_px: 200, dpi: 254, dither: 'jarvis', given: true},
    image: {engrave: 'raster'}});
  const traced = el('t', 'image', 70, 30, 20, 20, {image: {engrave: 'vector'}, raster: null});
  const list = [view.elements[0], photo, traced];
  const t = mount({...view, elements: list, selection: ['p']});
  const g = t.group('p');
  const image = g.childNodes.find((n) => n.localName === 'image'), outline = g.childNodes.find((n) => n.localName === 'rect' && n.classList.contains('cc-raster-outline'));
  out.image = ['x', 'y', 'width', 'height', 'href', 'preserveAspectRatio', 'class'].map((k) => image.getAttribute(k));
  out.outline = ['x', 'y', 'width', 'height'].map((k) => outline.getAttribute(k));
  out.noInk = g.childNodes.filter((n) => n.localName === 'path').length;
  out.classes = [g.getAttribute('class').split(' ').includes('cc-el-raster'), g.getAttribute('class').split(' ').includes('cc-selected')];
  out.traced = [t.group('t').childNodes.map((n) => n.localName), t.group('t').getAttribute('class').includes('cc-el-raster')];
  out.order = t.q('g').filter((n) => n.classList.contains('cc-el')).map((n) => n.getAttribute('data-id'));
  out.title = g.childNodes.some((n) => n.localName === 'title');
  out.handles = t.handles();
  t.take();
  t.canvas.show({...view, elements: list, selection: []});
  t.click(40, 30);                                                       // anywhere in the picture's box picks it
  out.picked = t.take();
  t.canvas.show({...view, elements: list, selection: ['p']});
  t.drag([40, 30], [50, 30]);
  out.moved = t.take();
  t.canvas.show({...view, elements: list, selection: ['p']});
  t.fire('pointerdown', 40, 30); t.fire('pointermove', 45, 30);
  out.during = t.group('p').getAttribute('transform');                    // the bitmap goes with the pointer
  t.fire('pointerup', 45, 30); t.take();
  t.canvas.show({...view, elements: list, selection: ['p']});
  t.drag([55, 40], [65, 50]);                                            // the south-east corner of the picture (25..55 by 20..40)
  out.resized = t.take().map((c) => c[0]);
""")
    assert got["image"] == ["25", "20", "30", "20", "/api/card-works/7/elements/p/raster.png?v=3", "none", "cc-raster"]       # the bitmap lies on the picture's rectangle
    assert got["outline"] == ["25", "20", "30", "20"] and got["noInk"] == 0                                              # a dotted outline, and no filled path under the photo
    assert got["classes"] == [True, True]
    assert got["traced"] == [["path"], False]                                                                            # a traced picture is the same as before
    assert got["order"] == ["a", "p", "t"] and got["title"] is False                                                     # the z-order holds; a complete photo has no note
    assert got["handles"] == ["nw", "ne", "se", "sw", "rotate"]                                                          # a picture keeps its proportions: corners and rotation
    assert got["picked"] == [["onSelect", ["p"]]]
    assert got["moved"] == [["onMove", ["p"], 10, 0]]
    assert got["during"] == "matrix(1 0 0 1 5 0)"
    assert got["resized"] == ["onResize"]


@node
def test_a_photo_with_no_url_or_no_box_falls_back_to_its_path_and_a_plain_grey_preview_says_why(tmp_path):
    got = run(tmp_path, VIEW + """
  const bare = (id, raster, extra = {}) => el(id, 'image', 40, 30, 30, 20, {raster, ...extra});
  const list = [bare('nourl', {url: '', given: true}), bare('nobox', {url: '/x.png', given: true}, {bounds: null}), bare('plain', {url: '/y.png', given: false}), bare('empty', {url: '/z.png', given: true}, {d: ''})];
  const t = mount({...view, elements: list});
  const kinds = (id) => t.group(id).childNodes.map((n) => n.localName);
  out.kinds = Object.fromEntries(list.map((e) => [e.id, kinds(e.id)]));
  out.plain = t.group('plain').childNodes.find((n) => n.localName === 'title').textContent;
  out.escaped = t.group('plain').childNodes.find((n) => n.localName === 'image').getAttribute('href');
""")
    assert got["kinds"]["nourl"] == ["path"] and got["kinds"]["nobox"] == ["path"]                                      # without a url or a box the path is drawn, as before
    assert "image" not in got["kinds"]["nourl"] and "image" not in got["kinds"]["nobox"]
    assert got["kinds"]["plain"][:2] == ["image", "rect"] and "image" in got["kinds"]["empty"]
    assert got["plain"] == "Plain grey preview: the engraving settings give no line interval or image mode yet"
    assert got["escaped"] == "/y.png"


@node
def test_a_minor_grid_is_left_out_where_its_lines_would_be_too_close(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  t.rect.width = 105 * 5; t.rect.height = 74 * 5;                                  // 5 px per mm
  t.canvas.show(view);
  out.classes = t.q('path').filter((p) => p.classList.contains('cc-grid-minor') || p.classList.contains('cc-grid-major')).map((p) => p.getAttribute('class'));
  out.labels = t.q('text').map((x) => x.textContent);
""")
    assert got["classes"] == ["cc-grid-major"]
    assert "20" in got["labels"] and "10" in got["labels"]


@node
def test_warnings_empty_elements_and_problems_are_drawn_so_they_can_still_be_seen_and_picked(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  const classes = (id) => t.group(id).getAttribute('class').split(' ');
  out.classes = Object.fromEntries(['a', 'b', 'c'].map((id) => [id, classes(id)]));
  const warn = t.group('b').childNodes.find((n) => n.localName === 'rect' && n.classList.contains('cc-warn-box'));
  out.warn = ['x', 'y', 'width', 'height'].map((k) => Number(warn.getAttribute(k)));
  out.warnTitle = t.group('b').childNodes.find((n) => n.localName === 'title').textContent;
  out.noWarn = t.group('a').childNodes.map((n) => n.getAttribute('class'));
  const ghost = t.group('c').childNodes.find((n) => n.classList.contains('cc-ghost'));
  out.ghost = ghost.getAttribute('points');
  out.ghostTitle = t.group('c').childNodes.find((n) => n.localName === 'title').textContent;
  out.pick = [];
  t.click(20, 40); out.pick.push(t.take());                                       // an element without ink is picked in its box
  t.click(60, 20); out.pick.push(t.take());
""")
    assert "cc-has-warning" in got["classes"]["b"] and "cc-el-text" in got["classes"]["b"]
    assert "cc-empty" in got["classes"]["c"] and "cc-has-problems" in got["classes"]["c"] and "cc-el-qr" in got["classes"]["c"]
    assert not {"cc-has-warning", "cc-empty", "cc-has-problems"} & set(got["classes"]["a"]) and got["noWarn"] == ["cc-ink"]
    # the amber dashed outline is the geometry's bounds with a margin of 0.3 mm
    approx_all(got["warn"], [60 - 12 - 0.3, 20 - 4 - 0.3, 24.6, 8.6])
    assert got["warnTitle"] == "Module is smaller than 0.40 mm"
    assert got["ghost"] == "15,35 25,35 25,45 15,45" and got["ghostTitle"] == "nothing to engrave"
    assert got["pick"] == [[["onSelect", ["c"]]], [["onSelect", ["b"]]]]


@node
def test_the_selection_shows_the_oriented_box_with_handles_that_fit_the_element_type(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount({...view, selection: ['a']});
  const box = () => t.q('polygon').find((p) => p.classList.contains('cc-sel-box'));
  out.shape = [t.handles(), box().getAttribute('points')];
  const se = t.q('rect').find((r) => r.getAttribute('data-handle') === 'se');
  out.se = [se.getAttribute('x'), se.getAttribute('y'), se.getAttribute('width'), se.getAttribute('class')];
  const rotate = t.q('circle').find((r) => r.getAttribute('data-handle') === 'rotate');
  out.rotate = [rotate.getAttribute('cx'), rotate.getAttribute('cy')];
  out.stem = t.q('line').filter((l) => l.classList.contains('cc-stem')).map((l) => [l.getAttribute('y1'), l.getAttribute('y2')]);
  t.canvas.setSelection(['b']);
  out.text = [t.handles(), box().getAttribute('points'), t.group('b').getAttribute('class').includes('cc-selected'), t.group('a').getAttribute('class').includes('cc-selected')];
  const nw = t.q('rect').find((r) => r.getAttribute('data-handle') === 'nw');
  out.turned = [nw.getAttribute('transform'), nw.getAttribute('class')];
  t.canvas.setSelection(['a', 'b', 'nothing']);
  out.many = [t.handles(), t.q('polygon').filter((p) => p.classList.contains('cc-member')).length, t.q('rect').find((r) => r.classList.contains('cc-multi')).getAttribute('width'),
              t.canvas.getSelection(), t.stage.querySelector('div').textContent];
  t.canvas.setSelection([]);
  out.none = [t.handles(), t.q('polygon').filter((p) => p.classList.contains('cc-sel-box') || p.classList.contains('cc-member')).length, t.stage.querySelector('div').textContent];
  t.canvas.show({...view, selection: ['b']});
  out.live = t.stage.querySelector('div').textContent;
  t.canvas.show({...view, elements: view.elements.filter((e) => e.id !== 'b')});
  out.dropped = t.canvas.getSelection();
""")
    assert got["shape"][0] == ["nw", "ne", "se", "sw", "n", "s", "e", "w", "rotate"]    # a shape resizes freely: corners and edges
    assert got["shape"][1] == "20,15 40,15 40,25 20,25"
    assert got["se"][:3] == ["39.5", "24.5", "1"] and "cc-cur-nwse" in got["se"][3]     # a handle is 10 px on screen whatever the zoom: 1 mm here
    assert got["rotate"] == ["30", "12.4"]                                            # 26 px above the top edge (y 15)
    assert got["stem"] == [["15", "12.4"]]
    assert got["text"][0] == ["nw", "ne", "se", "sw", "rotate"]                        # text keeps its proportions: corners only
    assert got["text"][2:] == [True, False]
    box = [tuple(map(float, p.split(","))) for p in got["text"][1].split()]
    assert box[0] == pytest.approx((60 - 12 * 0.9396926 + 4 * 0.3420201, 20 - 12 * 0.3420201 - 4 * 0.9396926), abs=2e-3)    # turned by 20 degrees about (60, 20)
    assert got["turned"][0].startswith("rotate(20 ") and got["turned"][1].endswith("cc-cur-nwse")
    assert got["many"][0] == [] and got["many"][1] == 2 and got["many"][3] == ["a", "b"]                # several: a box that only moves, no handles
    assert got["many"][4] == "2 elements selected"
    assert got["none"] == [[], 0, ""]
    assert got["live"].startswith("b selected: 24 × 8 mm at 60, 20, rotation 20")
    assert got["dropped"] == []                                                      # a selected element that is gone from the view is dropped


# -- pointer gestures -----------------------------------------------------------------------------------------------------------------------
@node
def test_a_click_selects_shift_or_cmd_toggles_a_group_goes_together_and_empty_space_clears(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  const rows = {};
  t.click(30, 20); rows.select = t.take();
  t.click(30, 20); rows.again = t.take();                                          // already the only one selected: nothing to report
  t.click(60, 20, {shiftKey: true}); rows.add = t.take();
  t.click(30, 20, {metaKey: true}); rows.remove = t.take();
  t.click(30, 20, {ctrlKey: true}); rows.back = t.take();
  t.click(60, 20); rows.collapse = t.take();                                        // a plain click inside a selection of two selects only that one
  t.click(70, 45); rows.group = [t.take(), t.group('g1').getAttribute('class').includes('cc-selected'), t.group('g2').getAttribute('class').includes('cc-selected'), t.handles()];
  t.click(78, 45, {shiftKey: true}); rows.groupOff = t.take();                       // a shift click takes the whole group off
  t.click(78, 45, {shiftKey: true}); rows.groupOn = t.take();
  t.click(5, 5, {shiftKey: true}); rows.emptyShift = t.take();                      // shift on empty space keeps the selection
  t.click(5, 5); rows.empty = [t.take(), t.canvas.getSelection()];
  t.click(5, 5); rows.emptyAgain = t.take();
  t.fire('pointerdown', 30, 20, {button: 2}); t.fire('pointerup', 30, 20, {button: 2}); rows.rightButton = t.take();
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["select"] == [["onSelect", ["a"]]] and rows["again"] == []
    assert rows["add"] == [["onSelect", ["a", "b"]]]                                  # ids come in z-order
    assert rows["remove"] == [["onSelect", ["b"]]] and rows["back"] == [["onSelect", ["a", "b"]]]
    assert rows["collapse"] == [["onSelect", ["b"]]]
    assert rows["group"] == [[["onSelect", ["g1", "g2"]]], True, True, []]
    assert rows["groupOff"] == [["onSelect", []]] and rows["groupOn"] == [["onSelect", ["g1", "g2"]]]
    assert rows["emptyShift"] == [] and rows["empty"] == [[["onSelect", []]], []] and rows["emptyAgain"] == [] and rows["rightButton"] == []


@node
def test_a_double_click_picks_one_part_out_of_its_group_and_the_other_parts_stay_where_they_were(tmp_path):
    """feature-3 REQ-003: the parts of an imported artwork are a group, selected as a whole by a click; a double click takes the part under the pointer alone."""
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  const rows = {};
  t.click(70, 45); rows.group = t.take();
  t.fire('dblclick', 70, 45); rows.alone = [t.take(), t.canvas.getSelection(), t.group('g1').getAttribute('class').includes('cc-selected'), t.group('g2').getAttribute('class').includes('cc-selected')];
  t.fire('dblclick', 70, 45); rows.again = t.take();                                // already the only one selected: nothing to report
  t.fire('dblclick', 78, 45); rows.other = [t.take(), t.canvas.getSelection()];
  t.fire('dblclick', 5, 5); rows.empty = [t.take(), t.canvas.getSelection()];       // empty space changes nothing
  t.click(30, 20); t.take();
  t.fire('dblclick', 30, 20); rows.plain = t.take();                                // an element without a group: nothing new either
  t.click(70, 45); t.take();                                                         // a click on a member takes the whole group again
  t.drag([70, 45], [70, 43]); rows.moved = t.take();                                // and a drag moves it whole
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["group"] == [["onSelect", ["g1", "g2"]]]
    assert rows["alone"] == [[["onSelect", ["g1"]]], ["g1"], True, False] and rows["again"] == []
    assert rows["other"] == [[["onSelect", ["g2"]]], ["g2"]] and rows["empty"] == [[], ["g2"]] and rows["plain"] == []
    assert rows["moved"] == [["onMove", ["g1", "g2"], 0, -2]]


@node
def test_a_part_of_artwork_is_taken_on_its_ink_resizes_freely_and_may_become_a_hairline(tmp_path):
    got = run(tmp_path, """
  const part = el('p1', 'vector', 40, 30, 20, 10, {d: rectD(30, 25, 50, 35) + ' ' + rectD(34, 28, 46, 32)});     // a ring: hollow in the middle
  const thin = el('p2', 'vector', 70, 30, 0.2, 12);
  const under = el('under', 'shape', 40, 30, 10, 10);
  const t = mount({elements: [under, part, thin]});
  const rows = {};
  t.click(40, 30); rows.hollow = t.take();                                           // the middle of the ring: what lies beneath
  t.click(31, 30); rows.ink = t.take();                                              // its ink
  t.canvas.setSelection(['p1']);
  rows.handles = t.handles();                                                        // edges as well as corners: no fixed proportions
  t.canvas.setSelection(['p2']);
  const before = M.handlePositions(thin, 3);
  t.drag([70.1, 36], [70.1, 33]);                                                    // the bottom edge pulled up by 3 mm
  rows.thin = t.take();
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["hollow"] == [["onSelect", ["under"]]] and rows["ink"] == [["onSelect", ["p1"]]]
    assert {"n", "s", "e", "w", "nw", "ne", "sw", "se"} <= set(rows["handles"])
    assert rows["thin"] and rows["thin"][-1][0] == "onResize" and rows["thin"][-1][2]["width"] == pytest.approx(0.2, abs=0.01), "a hairline stays a hairline when it is stretched by its edge"


@node
def test_pressing_a_hollow_frame_in_its_middle_picks_what_lies_beneath(tmp_path):
    got = run(tmp_path, """
  const inner = el('inner', 'shape', 40, 30, 10, 10);
  const frame = el('frame', 'frame', 40, 30, 60, 40, {d: rectD(10, 10, 70, 50) + ' ' + rectD(13, 13, 67, 47)});
  const t = mount({elements: [inner, frame]});
  t.click(40, 30); out.middle = t.take();
  t.click(11.5, 30); out.edge = t.take();
  t.click(20, 20); out.hole = t.take();
""")
    assert got["middle"] == [["onSelect", ["inner"]]]                                 # the frame is above, yet its middle is not the frame
    assert got["edge"] == [["onSelect", ["frame"]]]
    assert got["hole"] == [["onSelect", []]]


@node
def test_dragging_a_selected_element_shows_it_moving_and_reports_the_move_when_the_pointer_is_released(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount({...view, selection: ['a']});
  const rows = {};
  t.fire('pointerdown', 30, 20); t.fire('pointermove', 45, 20);
  rows.during = [t.take(), t.group('a').getAttribute('transform'), t.group('b').getAttribute('transform')];
  const sel = t.q('polygon').find((p) => p.classList.contains('cc-sel-box')).getAttribute('points');
  rows.followed = sel;
  t.fire('pointerup', 45, 20);
  rows.after = [t.take(), t.group('a').getAttribute('transform')];
  rows.then = t.q('polygon').find((p) => p.classList.contains('cc-sel-box')).getAttribute('points');
  t.canvas.show({...view, selection: ['a']});                                       // the screen's answer redraws from the state
  rows.redrawn = t.group('a').getAttribute('transform');
  t.drag([30, 20], [30.2, 20.1]); rows.tiny = t.take();                              // under 3 px is a click, not a drag
  t.drag([30, 20], [33.04, 21.26]); rows.snap = t.take();
  t.canvas.show({...view, selection: ['a']});
  t.drag([30, 20], [33.04, 21.26], {altKey: true}); rows.alt = t.take();
  t.canvas.show({...view, selection: ['a']});
  t.drag([30, 20], [29, 20]); rows.centre = t.take();
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["during"] == [[], "matrix(1 0 0 1 15 0)", None]                       # nothing is reported before the release; only the dragged one moves
    assert rows["followed"] == "35,15 55,15 55,25 35,25"                              # the selection box goes with it
    assert rows["after"] == [[["onMove", ["a"], 15, 0]], "matrix(1 0 0 1 15 0)"]       # the picture stays where it was dropped until the screen answers
    assert rows["then"] == "35,15 55,15 55,25 35,25"
    assert rows["redrawn"] is None
    assert rows["tiny"] == []
    assert rows["snap"] == [["onMove", ["a"], 3.0, 1.3]]                               # 0.1 mm snap
    assert rows["alt"] == [["onMove", ["a"], 3.04, 1.26]]                              # Alt: none
    assert rows["centre"] == [["onMove", ["a"], -1, 0]]


@node
def test_a_drag_from_an_unselected_element_selects_it_first_and_a_group_or_selection_moves_together(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  const rows = {};
  t.drag([30, 20], [31, 24]); rows.fresh = t.take();                                // press, drag: select, then move
  t.canvas.show(view);
  t.drag([70, 45], [70, 43]); rows.group = t.take();                                // the other member of the group comes along
  rows.groupMoved = [t.group('g1').getAttribute('transform'), t.group('g2').getAttribute('transform')];
  t.canvas.show({...view, selection: ['a', 'b']});
  t.drag([60, 20], [62, 21]); rows.several = t.take();
  t.canvas.show({...view, selection: ['a']});
  t.drag([60, 20], [62, 21]); rows.other = t.take();                                // pressing another element replaces the selection
  t.canvas.show({...view, selection: ['a']});
  t.drag([60, 20], [62, 21], {shiftKey: true}); rows.addDrag = t.take();            // with shift it joins the selection
  t.canvas.show(view);
  t.drag([5, 5], [20, 20]); rows.empty = t.take();                                  // a drag on empty space does nothing
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["fresh"] == [["onSelect", ["a"]], ["onMove", ["a"], 1, 4]]
    assert rows["group"] == [["onSelect", ["g1", "g2"]], ["onMove", ["g1", "g2"], 0, -2]]
    assert rows["groupMoved"] == ["matrix(1 0 0 1 0 -2)", "matrix(1 0 0 1 0 -2)"]
    assert rows["several"] == [["onMove", ["a", "b"], 2, 1]]
    assert rows["other"] == [["onSelect", ["b"]], ["onMove", ["b"], 2, 1]]
    assert rows["addDrag"] == [["onSelect", ["a", "b"]], ["onMove", ["a", "b"], 2, 1]]
    assert rows["empty"] == []


@node
def test_the_cards_centre_line_pulls_a_dragged_element_and_is_drawn_while_it_does(tmp_path):
    got = run(tmp_path, """
  const t = mount({elements: [el('a', 'shape', 30, 20, 10, 10)], selection: ['a']});
  t.fire('pointerdown', 30, 20); t.fire('pointermove', 42.3, 20.3);
  const lines = () => t.q('line').filter((l) => l.classList.contains('cc-guide')).map((l) => [l.getAttribute('x1'), l.getAttribute('y1'), l.getAttribute('x2'), l.getAttribute('y2')]);
  out.during = lines();
  t.fire('pointerup', 42.3, 20.3);
  out.after = [lines(), t.take()];
""")
    assert got["during"] == [["42.5", "-10", "42.5", "64"]]
    assert got["after"] == [[], [["onMove", ["a"], 12.5, 0.3]]]                 # x pulled to the centre line, y on the 0.1 grid


@node
def test_escape_or_a_lost_pointer_ends_a_drag_without_reporting_it(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount({...view, selection: ['a']});
  const rows = {};
  t.fire('pointerdown', 30, 20); t.fire('pointermove', 45, 20);
  const e = t.key('Escape');
  rows.escape = [t.take(), t.group('a').getAttribute('transform'), t.canvas.getSelection(), e.prevented];
  t.fire('pointerup', 45, 20); rows.upIgnored = t.take();
  t.fire('pointerdown', 70, 45); t.fire('pointermove', 70, 40);                      // unselected element: selected on the press, gone back on cancel
  rows.pressed = t.canvas.getSelection();
  t.fire('pointercancel', 70, 40);
  rows.cancel = [t.take(), t.group('g1').getAttribute('transform'), t.canvas.getSelection()];
  t.fire('pointerdown', 30, 20); t.fire('pointermove', 45, 20); t.canvas.show({...view, selection: ['a']});
  rows.deferred = t.group('a').getAttribute('transform');                           // a screen update during the drag waits for its end
  t.fire('pointerup', 45, 20);
  rows.deferredEnd = [t.take(), t.group('a').getAttribute('transform')];
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["escape"] == [[], None, ["a"], True] and rows["upIgnored"] == []      # Escape stops the drag; the selection stays
    assert rows["pressed"] == ["g1", "g2"]
    assert rows["cancel"] == [[], None, ["a"]]
    assert rows["deferred"] == "matrix(1 0 0 1 15 0)"
    assert rows["deferredEnd"] == [[["onMove", ["a"], 15, 0]], "matrix(1 0 0 1 15 0)"]


@node
def test_a_corner_handle_resizes_about_the_opposite_corner_and_the_type_decides_the_proportions(tmp_path):
    got = run(tmp_path, """
  const view = {elements: [el('a', 'shape', 30, 20, 20, 10), el('t', 'text', 60, 20, 20, 10), el('q', 'qr', 20, 45, 10, 10)], selection: ['a']};
  const t = mount(view);
  const rows = {};
  t.fire('pointerdown', 40, 25); t.fire('pointermove', 50, 35);                      // the south-east corner of the shape
  rows.live = t.group('a').getAttribute('transform');
  t.fire('pointerup', 50, 35);
  rows.shape = t.take();
  t.canvas.show(view);
  t.drag([40, 25], [50, 35], {shiftKey: true}); rows.shapeShift = t.take();
  t.canvas.show({...view, selection: ['t']});
  t.drag([70, 25], [80, 35]); rows.text = t.take();                                  // text keeps its proportions without shift
  t.canvas.show({...view, selection: ['t']});
  t.drag([50, 15], [40, 5]); rows.northWest = t.take();
  t.canvas.show({...view, selection: ['q']});
  t.drag([25, 50], [15, 50]); rows.qr = t.take();
  t.canvas.show({...view, selection: ['a']});
  t.drag([40, 25], [20.2, 15.2]); rows.small = t.take();                              // below the minimum of 0.5 mm
  t.fire('pointerdown', 40, 25); t.fire('pointermove', 40.2, 25); t.fire('pointerup', 40.2, 25); rows.hardly = t.take();
  t.canvas.show({...view, selection: ['a']});
  t.fire('pointerdown', 40.5, 25.4); t.fire('pointermove', 50.5, 35.4); t.fire('pointerup', 50.5, 35.4); rows.grabbed = t.take();   // grabbed off the handle's centre
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["live"] == "matrix(1.5 0 0 2 -10 -15)"                                 # the picture is stretched about the fixed corner meanwhile
    box = rows["shape"][0][2]
    assert rows["shape"][0][:2] == ["onResize", "a"] and box == {"x": 35, "y": 25, "width": 30, "height": 20}
    shift = rows["shapeShift"][0][2]
    assert shift["width"] / shift["height"] == pytest.approx(2) and shift["x"] - shift["width"] / 2 == pytest.approx(20)
    text = rows["text"][0][2]
    assert text["width"] / text["height"] == pytest.approx(2) and (text["x"] - text["width"] / 2, text["y"] - text["height"] / 2) == pytest.approx((50, 15))
    nw = rows["northWest"][0][2]
    assert nw["width"] / nw["height"] == pytest.approx(2) and (nw["x"] + nw["width"] / 2, nw["y"] + nw["height"] / 2) == pytest.approx((70, 25))
    qr = rows["qr"][0][2]
    assert qr["width"] == pytest.approx(qr["height"]) and (qr["x"] - qr["width"] / 2, qr["y"] - qr["height"] / 2) == pytest.approx((15, 40))   # about the top-left corner
    assert rows["small"][0][2]["width"] == 0.5 and rows["small"][0][2]["height"] == 0.5
    assert rows["hardly"] == []
    assert rows["grabbed"][0][2] == {"x": 35, "y": 25, "width": 30, "height": 20}      # the handle keeps its place under the pointer: no jump


@node
def test_edge_handles_belong_to_shapes_and_frames_only(tmp_path):
    got = run(tmp_path, """
  const view = {elements: [el('a', 'frame', 30, 20, 20, 10), el('t', 'text', 60, 20, 20, 10)], selection: ['a']};
  const t = mount(view);
  const rows = {};
  t.drag([40, 20], [45, 99]); rows.east = t.take();
  t.canvas.show(view);
  t.drag([30, 15], [99, 12]); rows.north = t.take();
  t.canvas.show({...view, selection: ['t']});
  t.drag([70, 20], [75, 20]); rows.textEdge = t.take();                              // no east handle on text: the press moves it
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["east"] == [["onResize", "a", {"x": 32.5, "y": 20, "width": 25, "height": 10}]]
    assert rows["north"] == [["onResize", "a", {"x": 30, "y": 18.5, "width": 20, "height": 13}]]
    assert rows["textEdge"] == [["onMove", ["t"], 5, 0]]


@node
def test_a_rotated_element_resizes_about_the_opposite_corner_as_it_is_seen(tmp_path):
    got = run(tmp_path, """
  const e = el('a', 'shape', 40, 30, 20, 10, {rotation: 35});
  const t = mount({elements: [e], selection: ['a']});
  const se = M.handlePositions(e).se, nw = M.handlePositions(e).nw;
  const to = [se[0] + 6, se[1] + 2];
  t.drag(se, to);
  const call = t.take()[0];
  out.call = call;
  out.nw = [nw, M.handlePositions({...call[2], rotation: 35}).nw];
  out.moved = M.resizeFromHandle(e, 'se', to, {});
""")
    assert got["call"][0] == "onResize"
    approx_all(got["nw"][1], got["nw"][0], 0.011)                                      # rounded to 0.01 mm, the anchor is still where it was
    assert got["call"][2]["width"] == pytest.approx(got["moved"]["width"], abs=0.01)


@node
def test_the_rotate_handle_turns_the_element_in_degrees_or_steps_of_fifteen(tmp_path):
    got = run(tmp_path, """
  const view = {elements: [el('a', 'shape', 30, 20, 20, 10), el('b', 'text', 60, 20, 20, 10)], selection: ['a']};
  const t = mount(view);
  const rows = {};
  t.fire('pointerdown', 30, 12.4); t.fire('pointermove', 40, 20);
  rows.live = t.group('a').getAttribute('transform');
  t.fire('pointerup', 40, 20);
  rows.right = t.take();
  t.canvas.show(view);
  t.drag([30, 12.4], [38, 11]); rows.degrees = t.take();
  t.canvas.show(view);
  t.drag([30, 12.4], [38, 11], {shiftKey: true}); rows.steps = t.take();
  t.canvas.show(view);
  t.drag([30, 12.4], [30, 28]); rows.down = t.take();
  t.canvas.show(view);
  t.drag([30, 12.4], [20, 20]); rows.left = t.take();
  t.canvas.show(view);
  t.drag([30.5, 12.4], [30.8, 12.4]); rows.grab = t.take();                          // grabbed a little aside: no jump to the pointer's angle
  t.canvas.show({...view, selection: ['b']});
  t.drag([60, 12.4], [70, 20]); rows.text = t.take();
  t.canvas.show({...view, elements: [el('a', 'shape', 30, 20, 20, 10, {rotation: 90}), view.elements[1]], selection: ['a']});
  t.drag([30 + 5 + 2.6, 20], [30, 30]); rows.turned = t.take();                        // the handle of a box turned 90 degrees is on its right
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["live"].startswith("matrix(") and rows["right"] == [["onRotate", "a", 90]]
    assert rows["degrees"] == [["onRotate", "a", 42]] and rows["steps"] == [["onRotate", "a", 45]]
    assert rows["down"] == [["onRotate", "a", 180]] and rows["left"] == [["onRotate", "a", -90]]
    assert rows["grab"][0][2] <= 2                                                     # with the grab offset removed it is 2, not the 6 degrees of the pointer
    assert rows["text"] == [["onRotate", "b", 90]]
    assert rows["turned"] == [["onRotate", "a", 180]]


@node
def test_a_press_takes_the_focus_and_the_pointer_and_a_second_finger_or_a_lost_release_does_no_harm(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount({...view, selection: ['a']});
  const log = [];
  t.stage.setPointerCapture = (id) => log.push(['capture', id]);
  t.stage.releasePointerCapture = (id) => log.push(['release', id]);
  const rows = {};
  t.click(30, 20);
  rows.focus = [t.stage.focused === true, doc.activeElement === t.stage];
  rows.capture = log.splice(0);
  t.fire('pointermove', 40, 20);
  rows.idle = [t.take(), t.group('a').getAttribute('transform')];                   // moving over the canvas without a press does nothing
  t.fire('pointerdown', 30, 20, {pointerId: 1}); t.fire('pointerdown', 60, 20, {pointerId: 2});
  t.fire('pointermove', 45, 20, {pointerId: 2}); t.fire('pointerup', 45, 20, {pointerId: 2});
  rows.second = [t.take(), t.group('a').getAttribute('transform')];                 // the second finger is ignored
  t.fire('pointermove', 45, 20, {pointerId: 1}); t.fire('pointerup', 45, 20, {pointerId: 1});
  rows.first = t.take();
  t.canvas.show({...view, selection: ['a']});
  t.fire('pointerdown', 30, 20, {isPrimary: false}); t.fire('pointermove', 45, 20, {isPrimary: false}); t.fire('pointerup', 45, 20, {isPrimary: false});
  rows.secondary = t.take();
  t.fire('pointerdown', 30, 20); t.fire('pointermove', 40, 20);                      // the release never arrives
  t.fire('pointerdown', 30, 20); t.fire('pointermove', 31, 20); t.fire('pointerup', 31, 20);
  rows.recovered = [t.take(), t.group('a').getAttribute('transform')];
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["focus"] == [True, True]                                              # the keys work after a click
    assert rows["capture"] == [["capture", 1], ["release", 1]]
    assert rows["idle"] == [[], None]
    assert rows["second"] == [[], None] and rows["first"] == [["onMove", ["a"], 15, 0]]
    assert rows["secondary"] == []
    assert rows["recovered"] == [[["onMove", ["a"], 1, 0]], "matrix(1 0 0 1 1 0)"]    # the press that follows a lost release starts from a clean state


# -- keyboard and wheel ---------------------------------------------------------------------------------------------------------------------
@node
def test_the_keys_move_delete_duplicate_undo_redo_and_escape(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount({...view, selection: ['a', 'b']});
  const rows = {};
  const press = (name, extra) => { const e = t.key(name, extra); return [t.take(), e.prevented]; };
  rows.left = press('ArrowLeft'); rows.shiftDown = press('ArrowDown', {shiftKey: true}); rows.up = press('ArrowUp'); rows.right = press('ArrowRight');
  rows.moved = t.group('a').getAttribute('transform');
  t.canvas.show({...view, selection: ['a', 'b']});
  rows.del = press('Delete'); rows.backspace = press('Backspace');
  rows.dup = press('d', {ctrlKey: true}); rows.dupMeta = press('D', {metaKey: true});
  rows.undo = press('z', {ctrlKey: true}); rows.undoMeta = press('z', {metaKey: true}); rows.undoCode = press('\\u044f', {ctrlKey: true, code: 'KeyZ'});
  rows.redo = press('z', {ctrlKey: true, shiftKey: true}); rows.redoY = press('y', {ctrlKey: true}); rows.redoMeta = press('Z', {metaKey: true, shiftKey: true});
  rows.plain = press('d'); rows.other = press('q');
  rows.escape = press('Escape');
  rows.escapeAgain = press('Escape');
  rows.afterEscape = [t.canvas.getSelection(), t.q('polygon').filter((p) => p.classList.contains('cc-sel-box') || p.classList.contains('cc-member')).length];
  rows.nothing = [press('ArrowLeft'), press('Delete'), press('d', {ctrlKey: true})];
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["left"] == [[["onMove", ["a", "b"], -0.5, 0]], True]
    assert rows["shiftDown"] == [[["onMove", ["a", "b"], 0, 5]], True]
    assert rows["up"] == [[["onMove", ["a", "b"], 0, -0.5]], True] and rows["right"] == [[["onMove", ["a", "b"], 0.5, 0]], True]
    assert rows["moved"] == "matrix(1 0 0 1 0 4.5)"                                    # the nudges add up on the picture until the screen answers
    assert rows["del"] == [[["onDelete", ["a", "b"]]], True] and rows["backspace"] == [[["onDelete", ["a", "b"]]], True]
    assert rows["dup"] == [[["onDuplicate", ["a", "b"]]], True] and rows["dupMeta"] == [[["onDuplicate", ["a", "b"]]], True]
    assert rows["undo"][0] == [["onUndo"]] and rows["undoMeta"][0] == [["onUndo"]] and rows["undoCode"][0] == [["onUndo"]]   # the key code works on any layout
    assert rows["redo"][0] == [["onRedo"]] and rows["redoY"][0] == [["onRedo"]] and rows["redoMeta"][0] == [["onRedo"]]
    assert rows["plain"] == [[], False] and rows["other"] == [[], False]
    assert rows["escape"][0] == [["onSelect", []], ["onEscape"]]                       # Escape clears the selection and says so
    assert rows["escapeAgain"][0] == [["onEscape"]]
    assert rows["afterEscape"] == [[], 0]
    assert rows["nothing"][0] == [[], False] and rows["nothing"][1] == [[], False]    # arrows keep scrolling the page when nothing is selected
    assert rows["nothing"][2][0] == []                                                # Ctrl+D with nothing selected: no duplicate (the browser's bookmark is still held back)


@node
def test_missing_handlers_are_fine_and_the_screen_may_replace_them_later(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount({...view, selection: ['a']}, []);
  t.key('Delete'); t.key('z', {ctrlKey: true}); t.key('Escape'); t.click(30, 20); t.drag([30, 20], [40, 20]);
  out.ok = true;
  const t2 = mount({...view, selection: ['a']}, ['onMove']);
  t2.key('ArrowLeft'); t2.key('Delete');
  out.partial = t2.take();
""")
    assert got["ok"] and got["partial"] == [["onMove", ["a"], -0.5, 0]]


@node
def test_the_wheel_scrolls_the_page_unless_ctrl_or_cmd_is_held_and_then_zooms(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  const rows = {};
  const zooms = [];
  const wheel = (extra) => { const e = {deltaY: 100, prevented: false, preventDefault() { e.prevented = true; }, ...t.at(40, 30), ...extra}; t.stage.dispatch('wheel', e); return e.prevented; };
  const size = () => [t.svg.getAttribute('width'), t.svg.getAttribute('height')];
  rows.plain = [wheel({}), t.canvas.getZoom(), size()];
  rows.out = [wheel({ctrlKey: true}), t.canvas.getZoom() < 1];
  t.canvas.fit();
  rows.in = [wheel({ctrlKey: true, deltaY: -100}), t.canvas.getZoom() > 1];
  rows.meta = wheel({metaKey: true, deltaY: -100});
  t.canvas.setZoom(2); rows.two = [t.canvas.getZoom(), size()];
  t.canvas.setZoom(100); rows.max = t.canvas.getZoom();
  t.canvas.setZoom(0.01); rows.min = t.canvas.getZoom();
  t.canvas.setZoom(2); t.canvas.fit(); rows.fit = [t.canvas.getZoom(), size()];
  out.rows = rows;
""")
    rows = got["rows"]
    assert rows["plain"] == [False, 1, ["1050", "740"]]                               # the card and its margin fill the box at zoom 1
    assert rows["out"] == [True, True] and rows["in"] == [True, True] and rows["meta"] is True
    assert rows["two"] == [2, ["2100", "1480"]]
    assert rows["max"] == 16 and rows["min"] == 0.25
    assert rows["fit"] == [1, ["1050", "740"]]


@node
def test_the_zoom_keeps_the_millimetre_under_the_pointer_and_is_reported(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  const s = t.stage;
  s.scrollLeft = 0; s.scrollTop = 0;
  // the picture's box follows its size and the stage's scroll position, as in a browser
  t.svg.getBoundingClientRect = () => ({left: 100 - s.scrollLeft, top: 50 - s.scrollTop, width: Number(t.svg.getAttribute('width')), height: Number(t.svg.getAttribute('height'))});
  const pointer = t.at(20, 10);
  s.dispatch('wheel', {deltaY: -Math.log(2) / 0.0025, ctrlKey: true, preventDefault() {}, ...pointer});
  out.zoom = t.canvas.getZoom();
  out.size = [t.svg.getAttribute('width'), t.svg.getAttribute('height')];
  out.scroll = [s.scrollLeft, s.scrollTop];
  out.under = M.mmToClient(20, 10, t.svg.getBoundingClientRect(), {width: 85, height: 54}, null);
  out.pointer = [pointer.clientX, pointer.clientY];
  const seen = [];
  const host = doc.createElement('div');
  doc.body.append(host);
  const other = CC.create(host, {onZoom: (z) => seen.push(z)});
  other.setZoom(2); other.setZoom(2); other.fit();
  out.seen = seen;
""")
    assert got["zoom"] == pytest.approx(2) and got["size"] == ["2100", "1480"]
    assert got["scroll"] == pytest.approx([300, 200])                                  # the stage scrolled by what the zoom moved the point
    approx_all(got["under"], got["pointer"], 1e-6)                                    # the same millimetre is still under the pointer
    assert got["seen"] == [2, 1]                                                       # a change is reported once, not when the zoom stays


# -- clean-up -------------------------------------------------------------------------------------------------------------------------------
@node
def test_destroy_removes_every_listener_and_the_canvas_and_later_events_do_nothing(tmp_path):
    got = run(tmp_path, VIEW + """
  const proto = Object.getPrototypeOf(doc.createElement('div'));
  const added = [], removed = [];
  const add = proto.addEventListener, remove = proto.removeEventListener;
  proto.addEventListener = function (type, fn, opts) { added.push([this, type, fn]); return add.call(this, type, fn, opts); };
  proto.removeEventListener = function (type, fn, opts) { removed.push([this, type, fn]); return remove.call(this, type, fn, opts); };
  const t = mount({...view, selection: ['a']});
  const types = added.map(([, type]) => type).sort();
  t.canvas.destroy();
  out.types = types;
  out.balanced = added.every(([target, type, fn]) => removed.some(([r, rt, rf]) => r === target && rt === type && rf === fn));
  out.gone = [t.host.children.length, t.stage.parentNode === null];
  t.canvas.destroy();
  t.click(30, 20); t.drag([30, 20], [45, 20]); t.fire('dblclick', 70, 45); t.key('Delete'); t.key('z', {ctrlKey: true}); t.key('Escape');
  t.stage.dispatch('wheel', {ctrlKey: true, deltaY: -100, preventDefault() {}});
  t.canvas.show(view); t.canvas.setSelection(['a']); t.canvas.fit(); t.canvas.setZoom(2);
  out.calls = t.take();
""")
    assert got["types"] == ["dblclick", "keydown", "lostpointercapture", "pointercancel", "pointerdown", "pointermove", "pointerup", "wheel"]
    assert got["balanced"] is True
    assert got["gone"] == [0, True]
    assert got["calls"] == []                                                          # even a listener the page failed to remove does nothing


@node
def test_the_picture_is_laid_out_again_when_its_box_changes_and_the_observer_goes_with_the_canvas(tmp_path):
    got = run(tmp_path, VIEW + """
  const t = mount(view);
  out.first = [t.svg.getAttribute('width'), t.svg.getAttribute('height')];
  t.stage.getBoundingClientRect = () => ({left: 100, top: 50, width: 525, height: 900});
  seen.callback();
  out.second = [t.svg.getAttribute('width'), t.svg.getAttribute('height')];
  t.canvas.destroy();
  out.state = [seen.observed, seen.disconnected];
""", before="""
const seen = {observed: 0, disconnected: 0, callback: null};
ctx.ResizeObserver = class { constructor(fn) { seen.callback = fn; } observe() { seen.observed += 1; } disconnect() { seen.disconnected += 1; } };
""")
    assert got["first"] == ["1050", "740"]
    assert got["second"] == ["525", "370"]                                             # the card fits the new width
    assert got["state"] == [1, 1]


@node
def test_a_view_without_a_size_or_elements_still_draws_a_card(tmp_path):
    got = run(tmp_path, """
  const t = mount({});
  out.empty = [t.svg.getAttribute('viewBox'), t.q('g').filter((g) => g.classList.contains('cc-el')).length];
  t.canvas.show({size_mm: {width: 0, height: -3}, elements: [null, el('a', 'shape', 10, 10, 4, 4)]});
  out.bad = [t.svg.getAttribute('viewBox'), t.q('g').filter((g) => g.classList.contains('cc-el')).length];
  t.canvas.show({elements: [{id: 7, type: 'shape', x: 'x', y: null, width: 4}]});
  out.numbers = t.group('7') !== undefined;
  t.canvas.setSelection([7]);
  out.numeric = t.canvas.getSelection();
""")
    assert got["empty"] == ["-10 -10 105 74", 0]                                      # 85 x 54 until told otherwise
    assert got["bad"] == ["-10 -10 105 74", 1]                                        # a size that is not positive is ignored; a missing element too
    assert got["numbers"] is True and got["numeric"] == [7]                            # ids may be numbers; a broken number is 0
