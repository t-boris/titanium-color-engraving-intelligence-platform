"""ux-accessible-layout-p0 (REQ-001, REQ-002): the keyboard and small-window behaviour of the screens, run in node over the small DOM of
``ui_dom.js`` (which keeps real focus: a removed node loses it). What a layout engine, a browser's focus ring or a screen reader would add is
not claimed here: those were looked at in a real browser by hand, and a screen reader was not run."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from titanium_platform.api.app import UI_DIR

from test_lettering_ui import FONT_WINDOW, FONTS, OPEN, editor_routes
from test_color_map_one_screen import colours, point, routes_of
from test_color_map_one_screen import run as run_map
from test_vector_editor_ui import TABLES, node, routes, run_editor, view, zone_routes

# -- BUG-016: the font family list is a listbox the keyboard can use -----------------------------------------------------------------
KEYS = FONT_WINDOW + """
  const stops = () => rowsOf().map((r) => [r, ...r.querySelectorAll('button, select')].filter((e) => e.getAttribute('tabindex') === '0')
    .map((e) => e.closest('.lt-font').getAttribute('data-family') + ':' + (e.getAttribute('data-ctl') || 'row'))).flat();
  const rowsOf = () => win().querySelectorAll('div').filter((d) => d.classList.contains('lt-font'));
  const picked = () => rowsOf().filter((r) => r.getAttribute('aria-selected') === 'true').map((r) => r.getAttribute('data-family'));
  const key = (el, k) => el.dispatch('keydown', {key: k});
  /** A click on a control inside a row, as a browser delivers it: the control's own handlers, and whether they stopped it going up to the
      row (the small DOM's dispatch bubbles whatever stopPropagation says, so the row's own click is not run here). */
  const press = async (el) => {
    let stopped = false;
    await Promise.all((el.listeners.click || []).map((fn) => fn({type: 'click', target: el, currentTarget: el, preventDefault() {}, stopPropagation() { stopped = true; }})));
    return stopped;
  };
  const focusOn = async (el) => { el.focus(); await el.dispatch('focusin'); };           // the small DOM's focus() does not tell its parents, a browser does
  const here = () => { const a = ctx.document.activeElement; return a && (a.getAttribute('data-family') || a.getAttribute('aria-label')); };
  const statusLine = () => win().querySelectorAll('p').find((p) => p.getAttribute('role') === 'status').textContent;
  const opener = () => byText(pane, 'button', 'Font: Arial Regular…');
  const openWithFocus = async () => { opener().focus(); await opener().dispatch('click'); await wait(5); };
"""


@node
def test_the_font_list_has_one_tab_stop_and_the_arrow_keys_home_and_end_move_it(tmp_path):
    out = run_editor(tmp_path, editor_routes(), OPEN + KEYS + """
  await openWithFocus();
  out.roles = [win().querySelectorAll('div').find((d) => d.getAttribute('role') === 'listbox').getAttribute('aria-label'), rowsOf().map((r) => r.getAttribute('role'))];
  out.first = stops();                                         // the chosen row, with its own controls, is the only tab stop of the list
  await focusOn(rowsOf()[0]);
  await key(rowsOf()[0], 'ArrowDown'); out.down = [here(), stops()];
  await key(ctx.document.activeElement, 'End'); out.end = [here(), stops()];
  await key(ctx.document.activeElement, 'ArrowDown'); out.past = here();                    // the list does not wrap
  await key(ctx.document.activeElement, 'Home'); out.home = [here(), stops()];
  await key(ctx.document.activeElement, 'ArrowUp'); out.top = here();
  await key(ctx.document.activeElement, 'PageDown'); out.page = here();
  out.picked = picked();                                       // moving the focus chooses nothing
""")
    assert out["roles"] == ["Fonts", ["option", "option", "option"]]
    assert out["first"] == ["Arial:row", "Arial:star", "Arial:style"]
    assert out["down"] == ["My Hand", ["My Hand:row", "My Hand:star", "My Hand:style", "My Hand:remove"]]
    assert out["end"] == ["Noto Sans Hebrew", ["Noto Sans Hebrew:row", "Noto Sans Hebrew:star", "Noto Sans Hebrew:download"]]
    assert out["past"] == "Noto Sans Hebrew" and out["home"][0] == "Arial" and out["top"] == "Arial" and out["page"] == "Noto Sans Hebrew"
    assert out["picked"] == ["Arial"]


@node
def test_enter_and_space_choose_the_row_and_the_choice_is_said_in_a_status_line(tmp_path):
    out = run_editor(tmp_path, editor_routes(), OPEN + KEYS + """
  await openWithFocus();
  await focusOn(rowsOf()[1]);
  await key(rowsOf()[1], 'Enter');
  out.enter = [picked(), here(), stops(), statusLine()];       // the redrawn row keeps the focus and the tab stop
  await focusOn(rowsOf()[0]);
  await key(rowsOf()[0], ' ');
  out.space = [picked(), here(), statusLine()];
  await key(rowsOf()[2], 'x');                                 // any other key is nobody's
  out.other = picked();
  await byText(win(), 'button', 'Select').dispatch('click'); await tick();
  out.ops = textOps();
""")
    assert out["enter"][:3] == [["My Hand"], "My Hand", ["My Hand:row", "My Hand:star", "My Hand:style", "My Hand:remove"]]
    assert out["enter"][3] == "Selected font My Hand, style Regular. Select confirms the choice."
    assert out["space"] == [["Arial"], "Arial", "Selected font Arial, style Regular. Select confirms the choice."]
    assert out["other"] == ["Arial"]
    assert out["ops"] == [{"op": "text_set", "id": "t1", "changes": {"font": {"face": "f1", "family": "Arial", "style": "Regular"}}}]


@node
def test_the_buttons_and_the_style_list_inside_a_row_do_not_take_the_choice(tmp_path):
    out = run_editor(tmp_path, editor_routes(), OPEN + KEYS + """
  await openWithFocus();
  const star = (family) => row(family).querySelector('button');
  const handStar = star('My Hand');
  await focusOn(handStar);
  await key(handStar, ' '); await key(handStar, 'Enter'); await key(handStar, 'ArrowDown');       // keys of a control inside a row are its own
  out.keys = [picked(), here()];
  out.stopped = [await press(handStar)];                                                         // a click on the star: favourite, not choice
  out.star = [picked(), here(), star('My Hand').getAttribute('aria-pressed'), stops()];
  const style = row('My Hand').querySelectorAll('select').find((s) => s.getAttribute('data-ctl') === 'style');
  await focusOn(style);
  out.stopped.push(await press(style));                                                           // a click that opens the list is not a click on the row
  style.value = 'o0'; await style.dispatch('change');                                             // a style: this family, this face, chosen
  out.style = [picked(), here(), row('My Hand').querySelector('img').getAttribute('src'), statusLine()];
  await byText(win(), 'button', 'Select').dispatch('click'); await tick();
  out.ops = textOps();
""")
    assert out["keys"] == [["Arial"], "My Hand: favorite"]
    assert out["stopped"] == [True, True]
    assert out["star"][:3] == [["Arial"], "My Hand: favorite", "true"] and out["star"][3] == ["My Hand:row", "My Hand:star", "My Hand:style", "My Hand:remove"]
    assert out["style"][:3] == [["My Hand"], "Style My Hand", "/api/fonts/preview.svg?face=o0&text=HOH&height=10"]
    assert out["style"][3] == "Selected font My Hand, style Thin. Select confirms the choice."
    assert out["ops"] == [{"op": "text_set", "id": "t1", "changes": {"font": {"face": "o0", "family": "My Hand", "style": "Thin"}}}]


@node
def test_a_search_and_a_cancel_keep_the_chosen_font_and_the_focus_goes_back_to_the_panel(tmp_path):
    out = run_editor(tmp_path, editor_routes(), OPEN + KEYS + """
  await openWithFocus();
  await focusOn(rowsOf()[1]); await key(rowsOf()[1], 'Enter');
  const search = win().querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Find font by name');
  search.focus(); search.value = 'noto'; await search.dispatch('input');
  out.found = [rowsOf().map((r) => r.getAttribute('data-family')), stops(), here(), picked()];     // the typed field keeps the focus; the chosen one is hidden, not lost
  search.value = ''; await search.dispatch('input');
  out.cleared = [picked(), stops()[0], here()];
  await byText(win(), 'button', 'Cancel').dispatch('click'); await tick();
  out.closed = [!ctx.document.body.querySelector('.modal'), ctx.document.activeElement === opener(), opener().textContent, textOps().length];
""")
    assert out["found"][0] == ["Noto Sans Hebrew"] and out["found"][1][0] == "Noto Sans Hebrew:row" and out["found"][2] == "Find font by name"
    assert out["found"][3] == []
    assert out["cleared"] == [["My Hand"], "My Hand:row", "Find font by name"]
    assert out["closed"] == [True, True, "Font: Arial Regular…", 0]            # nothing was sent, the old font is still shown, the focus is back on its button


@node
def test_the_next_portion_of_the_list_takes_the_focus_of_the_button_that_asked_for_it(tmp_path):
    many = [{"family": f"Face {n:03d}", "source": "mac", "kind": "sans", "scripts": ["latin"], "downloaded": True, "popularity": None,
             "faces": [{"id": f"m{n}", "style": "Regular", "weight": 400, "italic": False}], "regular": f"m{n}"} for n in range(70)]
    r = editor_routes()
    r["/api/fonts"]["json"] = {**FONTS, "families": FONTS["families"][:1] + many}
    out = run_editor(tmp_path, r, OPEN + KEYS + """
  await openWithFocus();
  out.before = rowsOf().length;
  const more = byText(win(), 'button', 'Show more (11)');
  more.focus(); await more.dispatch('click');
  out.after = [rowsOf().length, here(), stops()[0], !!win().querySelectorAll('button').find((b) => b.textContent.startsWith('Show more'))];
""")
    assert out["before"] == 60 and out["after"] == [71, "Face 059", "Face 059:row", False]


@node
def test_a_google_family_is_downloaded_only_when_it_is_asked_for_and_a_failed_download_chooses_nothing(tmp_path):
    r = editor_routes()
    r["/api/fonts/google/family"] = {"status": 502, "json": {"error": "no network", "kind": "network"}}
    out = run_editor(tmp_path, r, OPEN + KEYS + """
  await openWithFocus();
  await focusOn(rowsOf()[2]);
  out.idle = [asked(), stops()];                                                                  // focusing a row downloads nothing
  const get_ = row('Noto Sans Hebrew').querySelectorAll('button').find((b) => b.getAttribute('data-ctl') === 'download');
  out.button = get_.textContent;
  await focusOn(get_); out.stopped = await press(get_); await wait(10);                                  // the explicit button
  out.asked = asked();
  out.focus = [here(), picked()];
  await key(row('Noto Sans Hebrew'), 'Enter'); await wait(10);                                    // or choosing the row, as with a click
  out.again = [asked().length, picked(), statusLine()];
  out.toast = ctx.document.body.querySelectorAll('div').filter((d) => d.classList.contains('toast')).map((d) => d.className);
""")
    assert out["idle"] == [[], ["Noto Sans Hebrew:row", "Noto Sans Hebrew:star", "Noto Sans Hebrew:download"]]
    assert out["button"] == "Download (0.3 MB)" and out["asked"] == ["Noto Sans Hebrew"] and out["stopped"] is True
    assert out["focus"] == ["Noto Sans Hebrew", ["Arial"]]                  # the button was replaced by the note: the row keeps the focus; nothing chosen
    assert out["again"][1] == ["Arial"] and out["again"][0] == 2
    assert out["again"][2].startswith("Font Noto Sans Hebrew is not downloaded yet")
    assert out["toast"] and all("bad" in c for c in out["toast"])


# -- REQ-001 c2: what the gestures on the picture do, by buttons and numbers ------------------------------------------------------------
def with_texts(*texts, **routes_):
    """The editor's routes with ``texts`` as the work's inscriptions (and extra routes by path)."""
    r = editor_routes()
    j = r["/api/vector/7"]["json"]
    j["texts"] = list(texts)
    r.update({f"/x/{name}": {"status": 200, "json": {**j, "texts": view_texts}} for name, view_texts in routes_.items()})
    return r


TOOLS = OPEN + """
  const tool = (label) => pane.querySelectorAll('button').find((b) => b.getAttribute('aria-label') === label);
  const step = () => pane.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Move step, mm');
  const last = () => textOps().map((o) => o.changes);
"""


@node
def test_buttons_move_turn_and_size_the_chosen_inscription_as_the_drag_and_its_handles_do(tmp_path):
    from test_lettering_ui import text
    r = with_texts(text("t1", rotation=175.0, backing="rect", padding_mm=1.0, corner_mm=0.5, spacing_mm=0.2, x=20.0, y=10.0))
    out = run_editor(tmp_path, r, TOOLS + """
  await item(0).dispatch('click'); await tick();
  out.groups = ['Move inscription', 'Rotate inscription', 'Inscription size'].map((l) => !!group(l));
  await tool('Move right by one step').dispatch('click'); await tick();
  await tool('Move up by one step').dispatch('click'); await tick();
  step().value = '0.1'; await step().dispatch('change');
  await tool('Move left by one step').dispatch('click'); await tick();
  step().value = '5'; await step().dispatch('change');
  await tool('Move down by one step').dispatch('click'); await tick();
  await tool('Rotate clockwise by 15°').dispatch('click'); await tick();           // 175 + 15 comes round to -170, as a drag's turn does
  await tool('Rotate counterclockwise by 1°').dispatch('click'); await tick();
  await tool('Increase inscription by 10 %').dispatch('click'); await tick();
  await tool('Reduce inscription by 10 %').dispatch('click'); await tick();
  out.changes = last();
  out.names = pane.querySelectorAll('button').filter((b) => b.classList.contains('lt-tool')).map((b) => b.getAttribute('aria-label')).filter(Boolean).length;
""")
    assert out["groups"] == [True, True, True]
    assert out["changes"] == [{"x": 21.0, "y": 10.0}, {"x": 20.0, "y": 9.0}, {"x": 19.9, "y": 10.0}, {"x": 20.0, "y": 15.0}, {"rotation": -170.0},
                              {"rotation": 174.0},
                              # the size: about the frame's anchor (12, 7), the backing with it, as the square handle's drag does
                              {"height_mm": 4.4, "spacing_mm": 0.22, "x": 20.8, "y": 10.3, "padding_mm": 1.1, "corner_mm": 0.55},
                              {"height_mm": 3.636, "spacing_mm": 0.182, "x": 19.273, "y": 9.727, "padding_mm": 0.909, "corner_mm": 0.455}]
    assert out["names"] >= 10                                                       # every button names what it does


@node
def test_a_refused_change_leaves_the_inscription_where_it_was_and_says_why(tmp_path):
    from test_lettering_ui import text
    r = with_texts(text("t1"))
    r["/api/vector/7/colouring"] = {"status": 422, "json": {"error": "x must be at most 100000", "kind": "invalid"}}
    out = run_editor(tmp_path, r, TOOLS + """
  await item(0).dispatch('click'); await tick();
  await tool('Move right by one step').dispatch('click'); await wait(10);
  out.x = field('x, mm').value;
  out.toast = ctx.document.body.querySelectorAll('div').filter((d) => d.classList.contains('toast')).map((d) => d.className);
  out.ops = last();
""")
    assert out["x"] == "12" and out["ops"] == [{"x": 13.0, "y": 7.0}]              # the field still shows the work's x; the refusal is a message
    assert out["toast"] and all("bad" in c for c in out["toast"])


@node
def test_a_path_is_made_edited_and_cut_by_numbers_and_the_focus_stays_in_the_table(tmp_path):
    from test_lettering_ui import text
    flat = text("t1")                                                                 # no path yet
    three = text("t2", layout="path", points=[[0, 0], [10, 0], [20, 5]], x=5.0, y=15.0)
    two = text("t2", layout="path", points=[[0, 0], [20, 5]], x=5.0, y=15.0)
    r = with_texts(flat, three, after_cut=[flat, two])
    out = run_editor(tmp_path, r, TOOLS + """
  const coord = (n, axis) => pane.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === `Point ${n}: ${axis}, mm`);
  const act = (n, what) => pane.querySelectorAll('button').find((b) => b.getAttribute('aria-label') === `${what === 'Insert' ? 'Insert point after point' : 'Remove point'} ${n}`);
  await item(0).dispatch('click'); await tick();
  await byText(group('Layout'), 'button', 'Path').dispatch('click'); await tick();          // no points yet: a straight path of two is made
  await item(1).dispatch('click'); await tick();
  out.rows = pane.querySelectorAll('input').filter((i) => /^Point \\d+: /.test(i.getAttribute('aria-label') || '')).map((i) => [i.getAttribute('aria-label'), i.value]);
  out.groups = pane.querySelectorAll('div').filter((d) => d.getAttribute('role') === 'group' && /^Point \\d/.test(d.getAttribute('aria-label') || '')).map((d) => d.getAttribute('aria-label'));
  coord(2, 'x').value = '12.5'; await coord(2, 'x').dispatch('change'); await tick();
  await act(1, 'Insert').dispatch('click'); await tick();
  await act(3, 'Insert').dispatch('click'); await tick();
  await act(1, 'Remove').dispatch('click'); await tick();
  out.canCut = [act(1, 'Remove').disabled, act(3, 'Remove').disabled];
  data.routes['/api/vector/7/colouring'] = data.routes['/x/after_cut'];                                // the server's answer to a cut: two points
  coord(3, 'y').focus();
  await act(2, 'Remove').dispatch('click'); await tick(); await tick();
  out.after = [pane.querySelectorAll('input').filter((i) => /^Point \\d+: /.test(i.getAttribute('aria-label') || '')).length,
    ['1', '2'].map((n) => ['Insert', 'Remove'].map((w) => !!act(n, w) && act(n, w).disabled)), ctx.document.activeElement && ctx.document.activeElement.getAttribute('aria-label')];
  out.ops = last();
""")
    assert out["ops"][0] == {"layout": "path", "rotation": 0, "x": 12.0, "y": 7.0, "points": [[0, 0], [24, 0]]}
    assert out["rows"] == [["Point 1: x, mm", "5"], ["Point 1: y, mm", "15"], ["Point 2: x, mm", "15"], ["Point 2: y, mm", "15"],
                           ["Point 3: x, mm", "25"], ["Point 3: y, mm", "20"]]
    assert out["groups"] == ["Point 1 (inscription position)", "Point 2", "Point 3"]
    assert out["ops"][1] == {"x": 5.0, "y": 15.0, "points": [[0, 0], [7.5, 0], [20, 5]]}                  # a point moved: relative to the first, unturned
    assert out["ops"][2] == {"x": 5.0, "y": 15.0, "points": [[0, 0], [5, 0], [10, 0], [20, 5]]}            # inserted halfway to the next
    assert out["ops"][3] == {"x": 5.0, "y": 15.0, "points": [[0, 0], [10, 0], [20, 5], [30, 10]]}          # after the last, further along the path
    assert out["ops"][4] == {"x": 15.0, "y": 15.0, "points": [[0, 0], [10, 5]]}                            # the first cut: the second is the place now
    assert out["canCut"] == [False, False]
    assert out["after"][0] == 4 and out["after"][1] == [[False, True], [False, True]]                       # two points stay: no more cutting
    assert out["after"][2] and out["after"][2].startswith("Point ")                                         # the focus did not fall out of the table


# -- REQ-001 c2: the picture of the vector editor and its regions without the pointer ------------------------------------------------
PICTURE = """
  ctx.document.body.append(tree);                                                  // on screen, as the app shows it
  const stage = () => tree.querySelectorAll('div').find((d) => d.classList.contains('vw-ed-stage'));
  const box = () => svg().getAttribute('viewBox');
  const regions = () => section('Области');
  const rows = () => regions().querySelectorAll('div').filter((d) => d.classList.contains('lst-row'));
  const rowOf = (rid) => rows().find((r) => r.getAttribute('data-key') === rid);
  const choose = (rid) => regions().querySelectorAll('button').find((b) => /^(Выбрать область|Снять выбор с области) /.test(b.getAttribute('aria-label') || '') && b.getAttribute('aria-label').endsWith(' ' + rid));
  const note = () => regions().querySelectorAll('p').find((p) => p.getAttribute('role') === 'status').textContent;
  const tab = (id) => tree.querySelectorAll('button').find((b) => b.getAttribute('id') === 'vw-ed-tab-' + id);
  const kb = (target, k, extra = {}) => { let prevented = false;
    return Promise.resolve(target.dispatch('keydown', {key: k, code: extra.code || k, target, preventDefault() { prevented = true; }, ...extra})).then(() => prevented); };
  /** A key the way the page's own listener sees it: on the document, with the node that had the focus as the target. */
  const onDocument = async (target, extra) => { let prevented = false;
    await ctx.document.dispatch('keydown', {target, preventDefault() { prevented = true; }, ...extra}); return prevented; };
"""


@node
def test_the_picture_takes_the_keyboard_arrows_pan_plus_and_minus_zoom_and_zero_fits(tmp_path):
    out = run_editor(tmp_path, routes(), PICTURE + """
  out.stage = [stage().getAttribute('tabindex'), stage().getAttribute('aria-label')];
  out.fit = box();
  out.fitPan = [await kb(stage(), 'ArrowRight'), box()];                          // the whole picture is in view: there is nothing to pan to
  out.zoomIn = [await kb(stage(), '+'), box()];                                    // the same view as the «Увеличить» button gives
  out.right = [await kb(stage(), 'ArrowRight'), box()];
  out.down = [await kb(stage(), 'ArrowDown'), box()];
  out.left = [await kb(stage(), 'ArrowLeft'), box()];
  out.up = [await kb(stage(), 'ArrowUp'), box()];
  out.minus = [await kb(stage(), '-'), box()];
  await kb(stage(), '='); await kb(stage(), 'ArrowRight');
  out.zero = [await kb(stage(), '0'), box()];
  out.other = [await kb(stage(), 'a'), await kb(stage(), 'ArrowRight', {ctrlKey: true}), box()];                  // not the picture's keys: left alone
  const inner = tree.querySelectorAll('button').find((b) => b.getAttribute('aria-label') === 'Увеличить');
  out.inner = [await kb(inner, 'ArrowRight'), box()];                                // a key of a control inside is that control's
  const pan = (word) => tree.querySelectorAll('button').find((b) => b.getAttribute('aria-label') === `Сдвинуть вид ${word}`);
  await kb(stage(), '+');
  const before = box(); const moved = [];
  for (const word of ['вправо', 'вниз', 'влево', 'вверх']) { await pan(word).dispatch('click'); moved.push(box()); }
  out.buttons = [before, moved, tree.querySelectorAll('button').filter((b) => (b.getAttribute('aria-label') || '').startsWith('Сдвинуть вид')).length];
  out.posted = posted().length;
""")
    assert out["stage"][0] == "0" and "arrow keys" in out["stage"][1] and "Source colors" in out["stage"][1]
    assert out["fit"] == "0 0 40 20" and out["fitPan"] == [True, "0 0 40 20"]
    assert out["zoomIn"] == [True, "6.6667 3.3333 26.6667 13.3333"]                  # the numbers the button gives (test_pipette_selection_...)
    assert out["right"][1] == "12 3.3333 26.6667 13.3333"                            # a fifth of the view (5.3333), held inside the picture
    assert out["down"][1] == "12 6 26.6667 13.3333"
    assert out["left"][1] == "6.6667 6 26.6667 13.3333" and out["up"][1] == "6.6667 3.3333 26.6667 13.3333"
    assert out["minus"][1] == "0 0 40 20"
    assert out["zero"] == [True, "0 0 40 20"]
    assert out["other"] == [False, False, "0 0 40 20"] and out["inner"] == [False, "0 0 40 20"]
    before, moved, count = out["buttons"]
    assert count == 4 and moved[0] != before and len(set(moved[:3])) == 3 and moved[3] == before          # four buttons: right, down, left, up come back
    assert out["posted"] == 0                                                        # a view is not a change of the work


@node
def test_every_region_is_a_line_the_keyboard_can_choose_and_the_choice_is_the_one_the_picture_shows(tmp_path):
    out = run_editor(tmp_path, routes(), PICTURE + """
  out.lines = rows().map((r) => r.getAttribute('data-key'));
  out.first = [rowOf('r4').textContent, rowOf('r5').textContent];
  out.empty = [note(), classed('vw-sel'), tree.querySelectorAll('button').find((b) => b.textContent === 'Выделение').getAttribute('aria-pressed')];
  await choose('r1').dispatch('click'); await tick();
  out.one = [classed('vw-sel'), note(), choose('r1').getAttribute('aria-label'), choose('r1').getAttribute('aria-pressed'),
    tree.querySelectorAll('button').find((b) => b.textContent === 'Выделение').getAttribute('aria-pressed'), section('Selection').textContent.includes('Selected regions: 1')];
  await choose('r2').dispatch('click'); await tick();
  out.two = [classed('vw-sel'), choose('r2').getAttribute('aria-pressed'), choose('r3').getAttribute('aria-pressed')];
  await choose('r1').dispatch('click'); await tick();                              // a second press takes the region out
  out.off = [classed('vw-sel'), choose('r1').getAttribute('aria-label')];
  await byText(regions(), 'button', 'Выбрать все').dispatch('click'); await tick();
  out.all = [classed('vw-sel').length, note()];
  await byText(regions(), 'button', 'Снять выбор со всех').dispatch('click'); await tick();
  out.none = [classed('vw-sel'), note()];
  await choose('r3').focus(); await choose('r3').dispatch('focusin');                // the keyboard outlines a line's region as the pointer does
  out.hot = classed('vw-hot');
  await rowOf('r3').dispatch('focusout', {relatedTarget: null});
  out.hotAfter = classed('vw-hot');
  out.posted = posted().length;
""")
    assert out["lines"] == ["r1", "r2", "r3", "r4", "r5"]
    assert "исходный цвет № 2" in out["first"][0] and "титан" in out["first"][0] and "не гравируется" in out["first"][1]      # r5's colour is excluded
    assert out["empty"][0].startswith("Выбрано областей: 0") and out["empty"][1] == []
    assert out["one"] == [["r1"], out["one"][1], "Снять выбор с области r1", "true", "true", True] and out["one"][1].startswith("Выбрано областей: 1")
    assert out["two"] == [["r1", "r2"], "true", "false"]
    assert out["off"] == [["r2"], "Выбрать область r1"]
    assert out["all"][0] == 5 and out["all"][1].startswith("Выбрано областей: 5")
    assert out["none"] == [[], out["empty"][0]]
    assert out["hot"] == ["r3"] and out["hotAfter"] == []
    assert out["posted"] == 0                                                        # choosing changes nothing in the work


@node
def test_regions_chosen_from_the_list_are_merged_and_painted_from_the_selection_with_the_focus_going_there(tmp_path):
    out = run_editor(tmp_path, routes(), PICTURE + """
  await tab('colours').dispatch('click');                                           // a side tab, as a person arrives from the keyboard
  await choose('r1').dispatch('click'); await choose('r2').dispatch('click'); await tick();
  await byText(regions(), 'button', 'К действиям с выделением').dispatch('click'); await tick();
  const where = ctx.document.activeElement;
  out.focus = [where === section('Selection'), where && where.getAttribute('tabindex'),
    tab('brush').getAttribute('aria-selected')];
  await wait(5);
  await byText(section('Selection'), 'button', 'Merge regions').dispatch('click'); await tick();
  out.posted = posted();
""")
    assert out["focus"] == [True, "-1", "false"]                                     # the persistent inspector receives focus without changing tabs
    assert out["posted"] == [{"op": "merge_regions", "regions": ["r1", "r2"]}]


@node
def test_a_layer_and_a_source_colour_choose_their_regions_and_an_empty_or_stale_one_chooses_nothing(tmp_path):
    r = routes()
    j = r["/api/vector/7"]["json"]
    j["layers"][1]["regions"] = ["r3", "r99"]                                        # r99 is not on the picture (an older split)
    j["layers"][2]["regions"] = []                                                   # a layer with no region at all
    j["layers"][2]["region_count"] = 0
    out = run_editor(tmp_path, r, PICTURE + """
  const layers = tree.querySelectorAll('div').find((d) => d.classList.contains('vw-ed-layers'));
  const colours = tree.querySelectorAll('div').filter((d) => d.classList.contains('vw-ed-list')).find((d) => !d.classList.contains('vw-ed-layers'));
  const layerBtns = layers.querySelectorAll('button').filter((b) => b.textContent === 'Выбрать области');
  const colourBtns = colours.querySelectorAll('button').filter((b) => b.textContent === 'Выбрать области');
  out.counts = [layerBtns.length, colourBtns.length, layerBtns.map((b) => b.disabled), colourBtns.map((b) => b.disabled)];
  await tab('layers').dispatch('click');
  await layerBtns[0].dispatch('click'); await tick();
  out.layer1 = [classed('vw-sel'), ctx.document.activeElement === section('Selection')];
  await layerBtns[1].dispatch('click'); await tick();
  out.layer2 = classed('vw-sel');                                                  // the stale id is left out, the real one chosen
  out.layer3 = [layerBtns[2].disabled, classed('vw-sel')];                         // nothing to choose: the button is off (a browser sends no click to it)
  await colourBtns[1].dispatch('click'); await tick();
  out.colour = [classed('vw-sel'), tree.querySelectorAll('button').find((b) => b.textContent === 'Выделение').getAttribute('aria-pressed')];
  out.posted = posted().length;
""")
    assert out["counts"] == [3, 3, [False, False, True], [False, False, False]]
    assert out["layer1"] == [["r1", "r2"], True]
    assert out["layer2"] == ["r3"] and out["layer3"] == [True, ["r3"]]
    assert out["colour"] == [["r3", "r4"], "true"]
    assert out["posted"] == 0


@node
def test_the_regions_of_a_photo_zone_are_told_apart_in_the_list_and_a_space_on_a_button_is_not_taken_for_the_pan(tmp_path):
    out = run_editor(tmp_path, zone_routes(zoned=True), PICTURE + """
  out.zoned = [rowOf('r3').textContent, rowOf('r1').textContent];
  const space = (target) => onDocument(target, {key: ' ', code: 'Space'});
  const button = byText(tree, 'button', 'Вписать');
  out.space = [await space(button), await space(stage()), await space(tree.querySelectorAll('div').find((d) => d.getAttribute('role') === 'button' && d.classList.contains('lst-main')))];        // a button presses; the picture pans
  await ctx.document.dispatch('keyup', {code: 'Space'});
""")
    assert "фотозона 1" in out["zoned"][0] and "фотозона" not in out["zoned"][1]
    assert out["space"] == [False, True, False]            # on a button or a line of a list the browser presses it; elsewhere Space is «pan with the drag»


# -- REQ-001 c2: the important areas of the split, by numbers --------------------------------------------------------------------------
@node
def test_an_important_area_is_marked_reshaped_and_moved_by_numbers_and_sent_when_the_picture_is_split_again(tmp_path):
    r = routes()
    r["/api/vector/7/split"] = {"status": 200, "json": view()}
    out = run_editor(tmp_path, r, PICTURE + """
  const overlay = () => tree.querySelectorAll('svg').find((s) => s.getAttribute('class') === 'vw-areas');
  const num = (name) => tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === `Region: ${name}`);
  const set = async (name, v) => { num(name).value = v; await num(name).dispatch('change'); };
  const said = () => { const p = tree.querySelectorAll('p').find((q) => q.classList.contains('vw-area-note')); return [p.textContent, p.getAttribute('class'), p.getAttribute('role')]; };
  const add = () => byText(tree, 'button', 'Add region by coordinates');
  out.fields = ['Left, %', 'Top, %', 'Width, %', 'Height, %'].map((n) => num(n).value);
  await add().dispatch('click');
  out.rect = [overlay().querySelectorAll('polygon').map((p) => p.getAttribute('points')), said()];
  const shape = tree.querySelectorAll('select').find((x) => x.getAttribute('aria-label') === 'New region shape');
  shape.value = 'ellipse';
  await add().dispatch('click');
  out.ellipse = overlay().querySelectorAll('ellipse').map((e) => [e.getAttribute('cx'), e.getAttribute('cy'), e.getAttribute('rx'), e.getAttribute('ry')]);
  await set('Width, %', '90');                                                         // 25 + 90 is beyond the picture
  await add().dispatch('click');
  out.beyond = [overlay().querySelectorAll('polygon').length + overlay().querySelectorAll('ellipse').length, said()];
  await set('Width, %', '');
  await add().dispatch('click');
  out.empty = said();
  await set('Width, %', '0.1');                                                        // a fifth of a pixel
  await add().dispatch('click');
  out.tiny = [overlay().querySelectorAll('polygon').length + overlay().querySelectorAll('ellipse').length, said()[0]];
  await byText(tree, 'button', 'Boundary').dispatch('click');                             // the first row is the rectangle
  out.prefilled = ['Left, %', 'Top, %', 'Width, %', 'Height, %'].map((n) => num(n).value);
  const nudge = (word) => tree.querySelectorAll('button').find((b) => b.getAttribute('aria-label') === `Move boundary ${word} by 1%`);
  await nudge('right').dispatch('click'); await nudge('down').dispatch('click'); await nudge('left').dispatch('click'); await nudge('right').dispatch('click');
  out.moved = overlay().querySelectorAll('polygon').map((p) => p.getAttribute('points'));
  out.fieldsAfter = ['Left, %', 'Top, %', 'Width, %', 'Height, %'].map((n) => num(n).value);
  shape.value = 'rect';                                                                 // a boundary takes the shape the list says, as a dragged one does
  await set('Width, %', '20'); await set('Height, %', '10');
  await byText(tree, 'button', 'Set boundary by coordinates').dispatch('click');
  out.reshaped = overlay().querySelectorAll('polygon').map((p) => p.getAttribute('points'));
  out.pending = !tree.querySelectorAll('p').find((p) => p.textContent.startsWith('Region changes apply')).hidden;
  await byText(tree, 'button', 'Done').dispatch('click');
  out.noNudge = !nudge('right');
  await byText(tree, 'button', 'Split again').dispatch('click');
  await byText(ctx.document.body.querySelector('.modal'), 'button', 'Split again').dispatch('click'); await tick();
  out.posted = ctx.requests.filter((q) => q.path.endsWith('/split') && q.method === 'POST').map((q) => JSON.parse(q.body).manual);
""")
    assert out["fields"] == ["25", "25", "50", "50"]
    assert out["rect"][0] == ["100,50 300,50 300,150 100,150"] and out["rect"][1][0].startswith("Region added: manually marked #1")
    assert out["ellipse"] == [["200", "100", "100", "50"]]                                 # 50 % of 400 × 200 across, centred at 25 % + 25 %
    assert out["beyond"][0] == 2 and "inside the image" in out["beyond"][1][0] and "bad" in out["beyond"][1][1]           # refused, nothing added
    assert "four region bounds" in out["empty"][0]
    assert out["tiny"][0] == 2 and "too small" in out["tiny"][1]
    assert out["prefilled"] == ["25", "25", "50", "50"]                                    # the row's own box
    assert out["moved"] == ["104,52 304,52 304,152 104,152"]                               # right, down, left, right: +4 px across and +2 px down
    assert out["fieldsAfter"] == ["26", "26", "50", "50"]                                   # the fields follow the boundary
    assert out["reshaped"] == ["104,52 184,52 184,72 104,72"]                              # left 26 %, top 26 %: 20 % × 10 % of the picture
    assert out["pending"] is True and out["noNudge"] is True                               # the move buttons are for an area being edited
    assert out["posted"] == [[{"polygon": [[104, 52], [184, 52], [184, 72], [104, 72]]}, {"ellipse": {"center": [200, 100], "axes": [100, 50], "angle": 0}}]]


@node
def test_the_keyboard_stays_on_the_control_when_the_areas_are_drawn_again(tmp_path):
    out = run_editor(tmp_path, routes(), PICTURE + """
  const num = (name) => tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === `Region: ${name}`);
  const here = () => { const a = ctx.document.activeElement; return a ? [a.localName, (a.textContent || '').trim(), a.getAttribute('data-focus')] : null; };
  const add = () => byText(tree, 'button', 'Add region by coordinates');
  const addButton = add();
  addButton.focus();
  await addButton.dispatch('click');                                                   // an area is added: the very same button keeps the keyboard
  out.add = [here(), add() === addButton];
  const border = () => tree.querySelectorAll('button').find((b) => b.getAttribute('data-focus') === 'manual0:border');
  border().focus();
  await border().dispatch('click');                                                    // the list is drawn again with «Done» where «Boundary» was
  out.border = here();
  await byText(tree, 'button', 'Done').dispatch('click');
  out.done = here();
  const remove = () => tree.querySelectorAll('button').find((b) => b.getAttribute('data-focus') === 'manual0:toggle');
  remove().focus();
  await remove().dispatch('click');                                                    // the control is gone with its row: the keyboard goes to the add button
  out.removed = [here(), !!remove()];
  const kind = () => tree.querySelectorAll('select').find((x) => x.getAttribute('data-focus') === 'manual0:kind');
  await add().dispatch('click');
  kind().focus();
  kind().value = 'face'; await kind().dispatch('change');
  out.kind = here();
""")
    assert out["add"] == [["button", "Add region by coordinates", None], True]
    assert out["border"] == ["button", "Done", "manual0:border"]
    assert out["done"] == ["button", "Boundary", "manual0:border"]
    assert out["removed"] == [["button", "Add region by coordinates", None], False]
    assert out["kind"][0] == "select" and out["kind"][2] == "manual0:kind"


# -- REQ-001 c2: the four corners of a photograph, by numbers ----------------------------------------------------------------------------
CORNERS = """
const {context, load, El} = require(%(dom)s);
Object.defineProperty(El.prototype, 'style', {get() { return this._style || (this._style = {}); }});         // the small DOM has no style object
const ctx = context({});
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'screens/corners.js', {code: 'globalThis.Corners = Corners;'}]);
const tick = () => new Promise((r) => setTimeout(r, 0));
(async () => {
  const out = {}, changes = [];
  const c = ctx.Corners.create('/api/pairs/1/photo.png', %(initial)s, (v) => changes.push(v));
  ctx.document.body.append(c.el);
  const input = (n, axis) => c.el.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === `Corner ${n}: ${axis === 'x' ? 'from left' : 'from top'}, %%`);
  const values = () => [1, 2, 3, 4].map((n) => [input(n, 'x').value, input(n, 'y').value, input(n, 'x').disabled]);
  const note = () => { const p = c.el.querySelectorAll('p').find((q) => q.getAttribute('aria-live') === 'polite' && q.getAttribute('role') === 'status'); return [p.textContent, p.getAttribute('class')]; };
  const status = () => c.el.querySelectorAll('p').find((q) => q.getAttribute('aria-live') === 'polite' && q.getAttribute('role') !== 'status').textContent;
  const set = async (n, axis, v) => { input(n, axis).value = v; await input(n, axis).dispatch('change'); };
  const dots = () => c.el.querySelectorAll('button').filter((b) => b.classList.contains('dot'));
%(body)s
  out.changes = changes.length;
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run_corners(tmp_path, initial, body):
    script = tmp_path / "corners.js"
    script.write_text(CORNERS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "ui": json.dumps(str(UI_DIR) + "/"),
                                 "tables": json.dumps(TABLES), "initial": json.dumps(initial), "body": body}, encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout)


@node
def test_the_four_corners_are_placed_checked_and_moved_by_numbers_in_order(tmp_path):
    out = run_corners(tmp_path, [], """
  out.start = [values(), status()];                                                      // only the first corner can be placed: they go in order
  await set(1, 'x', '10');
  out.half = [values()[0], note(), changes.length];                                       // one number is not a corner yet
  await set(1, 'y', '20');
  out.first = [values().map((v) => v[2]), note()[0], dots().length, dots()[0].style.left, dots()[0].style.top, status()];
  await set(2, 'x', '90'); await set(2, 'y', '20.5');
  await set(3, 'x', '90'); await set(3, 'y', '80');
  await set(4, 'x', '10'); await set(4, 'y', '80');
  out.all = [values(), status(), c.get()];
  await set(4, 'x', '120');                                                               // beyond the photograph: the corner stays
  out.beyond = [values()[3], note(), c.get()[3]];
  await set(4, 'y', '');                                                                  // a placed corner cannot lose a number
  out.cleared = [values()[3], note()[0], c.get()[3]];
  await set(1, 'x', '12.5');
  out.moved = [c.get()[0], dots()[0].style.left];
  dots()[1].focus(); await dots()[1].dispatch('keydown', {key: 'ArrowRight'});            // an arrow key on a point is seen in its numbers
  out.arrow = [values()[1], c.get()[1]];
  await c.el.querySelectorAll('button').find((b) => b.textContent === 'Reset corners').dispatch('click');
  out.reset = [values(), c.get()];
""")
    assert [v[:2] for v in out["start"][0]] == [["", ""]] * 4 and [v[2] for v in out["start"][0]] == [False, True, True, True]
    assert out["start"][1].startswith("Place corner 1 of 4")
    assert out["half"][0] == ["10", "", False] and "both coordinates" in out["half"][1][0] and out["half"][2] == 0
    assert out["first"][0] == [False, False, True, True] and "10 % from left, 20 % from top" in out["first"][1] and out["first"][2] == 1
    assert out["first"][3:5] == ["10%", "20%"] and out["first"][5].startswith("Place corner 2 of 4")
    assert [v[:2] for v in out["all"][0]] == [["10", "20"], ["90", "20.5"], ["90", "80"], ["10", "80"]]
    assert out["all"][1] == "Four corners are placed. Alignment can be applied."
    assert out["all"][2] == [[0.1, 0.2], [0.9, 0.205], [0.9, 0.8], [0.1, 0.8]]
    assert out["beyond"][0][:2] == ["10", "80"] and "from 0 to 100%" in out["beyond"][1][0] and "bad" in out["beyond"][1][1] and out["beyond"][2] == [0.1, 0.8]
    assert out["cleared"][0][:2] == ["10", "80"] and "both coordinates are required" in out["cleared"][1] and out["cleared"][2] == [0.1, 0.8]
    assert out["moved"] == [[0.125, 0.2], "12.5%"]
    assert out["arrow"][0][:2] == ["91", "20.5"] and out["arrow"][1][0] == pytest.approx(0.91)
    assert [v[:2] for v in out["reset"][0]] == [["", ""]] * 4 and out["reset"][1] is None


@node
def test_corners_already_on_the_photograph_fill_the_fields_and_a_move_in_the_fields_is_a_move_of_the_point(tmp_path):
    out = run_corners(tmp_path, [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]], """
  out.fields = values();
  await set(3, 'x', '95');
  out.after = [values()[2], c.get()[2], dots()[2].style.left];
  out.label = dots()[2].getAttribute('aria-label');
""")
    assert [v[:2] for v in out["fields"]] == [["10", "10"], ["90", "10"], ["90", "90"], ["10", "90"]] and not any(v[2] for v in out["fields"])
    assert out["after"][0][:2] == ["95", "90"] and out["after"][1] == [0.95, 0.9] and out["after"][2] == "95%"
    assert "Corner 3" in out["label"] and "95 %" in out["label"]                               # the point says where it is


# -- REQ-001 c2: the colour map, a circle at a time ------------------------------------------------------------------------------------
@node
def test_the_colour_map_picks_one_circle_at_a_time_by_two_buttons_and_says_which(tmp_path):
    out = run_map(tmp_path, routes_of(), """
  ctx.document.body.append(tree);
  const step = (which) => tree.querySelectorAll('button').find((b) => b.getAttribute('data-step') === which);
  const note = () => tree.querySelector('.cm-step-note').textContent;
  const detail = () => tree.querySelector('.cm-detail');
  out.names = [step('previous').getAttribute('aria-label'), step('next').getAttribute('aria-label')];
  out.start = [detail().hidden, note()];
  const seen = [];
  for (let i = 0; i < 4; i++) { await step('next').dispatch('click'); await tick(); seen.push([note(), detail().hidden, ctx.document.activeElement === step('next')]); }
  out.forward = seen;                                                                    // left to right by a*, and round again
  await step('previous').dispatch('click'); await tick();
  out.back = [note(), ctx.document.activeElement === step('previous')];
  out.picked = tree.querySelectorAll('circle').filter((c) => c.getAttribute('stroke') === '#ffffff').length;
  await tree.querySelectorAll('circle')[0].dispatch('click'); await tick();               // a click on a circle picks it and says nothing about steps
  out.clicked = note();
""")
    assert out["names"] == ["Previous color on map", "Next color on map"] and out["start"] == [True, ""]
    texts = [n for n, *_ in out["forward"]]
    assert [t.split(":")[0] for t in texts] == ["Color 1 of 3", "Color 2 of 3", "Color 3 of 3", "Color 1 of 3"]
    assert [t.split(": ")[1].split(" · ")[0] for t in texts] == ["Test 3", "Test 1", "Test 2", "Test 3"]
    assert all(hidden is False and held for _, hidden, held in out["forward"])           # the card of the colour opens; the focus stays on the button
    assert out["back"][0].startswith("Color 3 of 3: Test 2") and out["back"][1] is True and out["picked"] == 1
    assert out["clicked"] == ""


@node
def test_a_map_with_no_circle_in_view_offers_no_step(tmp_path):
    out = run_map(tmp_path, routes_of(), """
  ctx.sessionStorage.setItem('color-map', JSON.stringify({band: [95, 100]}));            // the lightness band shows no colour
  tree = await screen();
  out.steps = tree.querySelectorAll('button').filter((b) => b.getAttribute('data-step')).length;
  out.text = tree.querySelector('.cm-plot').textContent;
""")
    assert out["steps"] == 0 and "No colors match these conditions" in out["text"]


# -- REQ-002 c3: on a narrow screen the panel slides out to the selected object --------------------------------------------------------
SLIDE = PICTURE + """
  const panel = () => tree.querySelectorAll('aside').find((a) => a.classList.contains('vw-ed-panel'));
  const toggle = () => tree.querySelectorAll('button').find((b) => b.classList.contains('vw-ed-panel-toggle'));
  const closer = () => tree.querySelectorAll('button').find((b) => b.classList.contains('vw-ed-panel-close'));
  const state = () => [panel().classList.contains('is-open'), toggle().getAttribute('aria-expanded')];
  const here = () => { const a = ctx.document.activeElement; return a && (a.getAttribute('id') || a.className || a.localName); };
  const escape = (target) => ctx.document.dispatch('keydown', {key: 'Escape', code: 'Escape', target});
  const narrow = (on) => { ctx.matchMedia = () => ({matches: on}); };
"""


@node
def test_the_panel_slides_out_by_its_button_and_keeps_the_focus_and_the_selection_on_escape(tmp_path):
    out = run_editor(tmp_path, routes(), SLIDE + """
  narrow(true);
  out.start = [state(), toggle().getAttribute('aria-controls') === panel().getAttribute('id'), toggle().textContent];
  toggle().focus();
  await toggle().dispatch('click');
  out.open = [state(), here()];                                                          // the focus is on the panel's shown tab
  await byText(tree, 'button', 'Выделение').dispatch('click');
  await path('r1').dispatch('click');                                                    // the picture's click selects; the panel stays open
  out.selected = [classed('vw-sel'), state()];
  await escape(closer());                                                                // Esc from the panel: it shuts, the selection stays, the focus goes back
  out.escaped = [state(), here(), classed('vw-sel')];
  await toggle().dispatch('click');
  await closer().dispatch('click');
  out.closed = [state(), here()];
  await toggle().dispatch('click');
  await toggle().dispatch('click');                                                      // the button shuts it too
  out.again = state();
  await toggle().dispatch('click');
  await escape(stage());                                                                   // Esc from the picture: the panel first, the selection on the second press
  out.first = [state(), classed('vw-sel')];
  await escape(stage());
  out.second = [state(), classed('vw-sel')];
""")
    assert out["start"] == [[False, "false"], True, "Панель: кисть, слои, цвета, надписи"]
    assert out["open"] == [[True, "true"], "vw-ed-tab-brush"]
    assert out["selected"] == [["r1"], [True, "true"]]
    assert out["escaped"] == [[False, "false"], "btn vw-ed-panel-toggle", ["r1"]]
    assert out["closed"] == [[False, "false"], "btn vw-ed-panel-toggle"]
    assert out["again"] == [False, "false"]
    assert out["first"] == [[False, "false"], ["r1"]] and out["second"] == [[False, "false"], []]


@node
def test_a_region_chosen_on_the_picture_slides_the_panel_out_on_a_narrow_screen_only(tmp_path):
    out = run_editor(tmp_path, routes(), SLIDE + """
  await byText(tree, 'button', 'Выделение').dispatch('click');
  narrow(false);
  await path('r1').dispatch('click'); await tick();
  out.wide = [state(), classed('vw-sel')];                                               // a wide screen has the panel in a column already
  await path('r1').dispatch('click'); await tick();                                      // the same region again takes the selection off
  narrow(true);
  await path('r2').dispatch('click'); await tick();
  out.narrow = [state(), classed('vw-sel'), ctx.document.activeElement === section('Selection')];
  await closer().dispatch('click');
  await path('r2').dispatch('click', {shiftKey: true}); await tick();                    // the last region taken off: nothing selected, nothing to show
  out.empty = [state(), classed('vw-sel')];
  await path('r3').dispatch('click', {shiftKey: true}); await tick();
  out.again = [state(), classed('vw-sel')];
  await closer().dispatch('click');
  await byText(tree.querySelectorAll('div').find((d) => d.getAttribute('aria-label') === 'Инструмент'), 'button', 'Кисть').dispatch('click');
  await path('r1').dispatch('click'); await tick();                                      // the brush paints: nothing is selected, the panel stays shut
  out.brush = [state(), classed('vw-sel')];
""")
    assert out["wide"] == [[False, "false"], ["r1"]]
    assert out["narrow"] == [[True, "true"], ["r2"], True]
    assert out["empty"] == [[False, "false"], []]
    assert out["again"] == [[True, "true"], ["r3"]]
    assert out["brush"] == [[False, "false"], ["r3"]]


@node
def test_an_inscription_picked_on_the_picture_slides_the_panel_out_on_its_tab_on_a_narrow_screen(tmp_path):
    from test_lettering_ui import text
    out = run_editor(tmp_path, with_texts(text("t1")), OPEN + SLIDE.replace(PICTURE, "") + """
  const letters = () => drawnText('t1').querySelectorAll('path').find((p) => p.classList.contains('lt-letters'));
  narrow(true);
  await letters().dispatch('pointerdown', {clientX: 50, clientY: 50, button: 0});
  await stage.dispatch('pointerup', {clientX: 50, clientY: 50});
  out.picked = [state(), tab.getAttribute('aria-selected'), field('x, mm').value];
  await closer().dispatch('click');
  await letters().dispatch('pointerdown', {clientX: 50, clientY: 50, button: 0});          // the same inscription again, still chosen: the panel comes back
  await stage.dispatch('pointerup', {clientX: 50, clientY: 50});
  out.again = state();
  await closer().dispatch('click');
  await letters().dispatch('pointerdown', {clientX: 50, clientY: 50, button: 0});          // a drag moves it and does not slide the panel over the picture
  await stage.dispatch('pointermove', {clientX: 60, clientY: 55});
  await stage.dispatch('pointerup', {clientX: 60, clientY: 55});
  out.dragged = state();
  await stage.dispatch('pointerdown', {clientX: 2, clientY: 2, button: 0}); await stage.dispatch('pointerup', {clientX: 2, clientY: 2});
  narrow(false);
  await letters().dispatch('pointerdown', {clientX: 50, clientY: 50, button: 0});
  await stage.dispatch('pointerup', {clientX: 50, clientY: 50});
  out.wide = state();
""")
    assert out["picked"] == [[True, "true"], "true", "12"]
    assert out["again"] == [True, "true"] and out["dragged"] == [False, "false"]
    assert out["wide"] == [False, "false"]


# -- REQ-002: the style sheet's small-window rules. A declaration proves nothing about a layout (that was looked at in a browser); these
#    only keep a later edit from taking the rule back. -------------------------------------------------------------------------------------
CSS = (Path(UI_DIR) / "styles.css").read_text(encoding="utf-8")
BLOCK = CSS[CSS.index("ux-accessible-layout-p0 (REQ-002, DEC-001)"):]


def rule(selector, text=BLOCK):
    found = [m.group(1) for m in re.finditer(r"(?:^|\n|\s)" + re.escape(selector) + r"\s*\{([^}]*)\}", text)]
    assert found, selector
    return found


def test_a_control_height_is_a_minimum_so_text_at_200_percent_is_not_cut():
    assert any("height:auto" in body for body in rule("input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=hidden]),select:not([multiple]):not([size])"))
    # the base rule still gives the control its 44 px at normal text: only the fixed height went
    assert "min-height:44px" in CSS and "height:44px" in CSS


def test_no_grid_column_asks_for_more_than_its_container_at_320_px():
    for selector, width in ((".g2", 300), (".g3", 190), (".vw-works", 500), (".color-variant-grid", 220), (".vw-split-fields", 200), (".ge-scales", 300)):
        assert any(f"minmax(min({width}px,100%),1fr)" in body for body in rule(selector)), selector


def test_the_narrow_panel_is_off_screen_and_unreachable_until_it_is_opened():
    narrow = BLOCK[BLOCK.index("4) a narrow screen"):]
    closed = narrow[narrow.index(".vw-work .vw-ed-panel,.vw-ed-panel {"):]
    assert "position:fixed" in closed and "visibility:hidden" in closed and "translateX(100%)" in closed
    opened = narrow[narrow.index(".vw-work .vw-ed-panel.is-open"):]
    assert "visibility:visible" in opened.split("}")[0] and "transform:none" in opened.split("}")[0]
    # above 1100 px the panel is a column, and nothing of the slide-out shows
    assert ".vw-ed-panel-head,.vw-ed-panel-toggle {display:none}" in narrow.split("@media")[0]


def test_the_header_scrolls_away_on_a_narrow_screen_and_the_menu_opens_under_it():
    shell = BLOCK[BLOCK.index("1) the shell"):BLOCK.index("2) text at 200")]
    narrow = shell.split("@media (max-width:600px)")[0]
    assert ".app-header {position:relative" in narrow and ".sidebar {position:absolute;top:0;bottom:0}" in narrow
    # the wide screen keeps the sticky header and the fixed rail
    assert re.search(r"\.app-header \{position:sticky;top:0", CSS) and re.search(r"\.sidebar \{position:fixed;top:76px", CSS)


def test_a_dialogs_buttons_stay_at_its_foot_in_a_low_or_narrow_window_only():
    dialogs = BLOCK[BLOCK.index("8) dialogs"):]
    assert "@media (max-height:700px),(max-width:600px) {\n  .modal>.row:last-child {position:sticky" in dialogs
    assert ".modal>.row:last-child {position:sticky" not in dialogs.split("@media")[0]       # the wide, tall window keeps the plain row


# -- the file card keeps the keyboard where it was after a download (REQ-001) ------------------------------------------------------------
import test_lifecycle_ui as lcui                       # the harness and the answers of the lifecycle tests, used here as they are
from lifecycle_stub import lifecycle as lc_answer


@node
def test_the_keyboard_stays_on_download_lightburn_when_the_card_is_drawn_again_after_the_download(tmp_path):
    out = lcui.run(tmp_path, {"routes": lcui.DOWNLOAD, "ready": lc_answer("prepared")}, """
  const host = ctx.document.createElement('div'); ctx.document.body.append(host);
  const draw = () => { host.replaceChildren(LC.exportCard(data.ready, {path: '/vector/7/export.lbrn2', name: 'vector.lbrn2', reload: async () => { draw(); }})); };
  draw();
  const pressed = () => byText(host, 'button', 'Download LightBurn');
  const first = pressed(); first.focus();
  await first.dispatch('click'); await tick();
  const now = pressed();
  out.replaced = now !== first;
  out.onNew = ctx.document.activeElement === now;
  out.enabled = now.disabled === false;
  // a press made with the mouse, focus elsewhere: nothing is pulled to the button
  const other = ctx.document.createElement('button'); ctx.document.body.append(other); other.focus();
  await pressed().dispatch('click'); await tick();
  out.stays = ctx.document.activeElement === other;
""")
    assert out["replaced"] and out["onNew"] and out["enabled"]
    assert out["stays"]


@node
def test_the_keyboard_goes_to_the_cards_heading_when_the_download_button_is_gone_after_the_download(tmp_path):
    out = lcui.run(tmp_path, {"routes": lcui.DOWNLOAD, "ready": lc_answer("prepared")}, """
  const host = ctx.document.createElement('div'); ctx.document.body.append(host);
  // the screen draws the card again without a download button (here: only the heading is left), so the heading is the nearest place
  const bare = () => { const c = ctx.document.createElement('div'); c.className = 'lc-export'; const hd = ctx.document.createElement('h4'); hd.textContent = 'Файл LightBurn'; c.append(hd); return c; };
  host.append(LC.exportCard(data.ready, {path: '/vector/7/export.lbrn2', name: 'vector.lbrn2', reload: async () => { host.replaceChildren(bare()); }}));
  const btn = byText(host, 'button', 'Download LightBurn'); btn.focus();
  await btn.dispatch('click'); await tick();
  const active = ctx.document.activeElement;
  out.tag = active && active.tagName.toLowerCase(); out.tabindex = active && active.getAttribute('tabindex');
""")
    assert out["tag"] == "h4" and out["tabindex"] == "-1"


# -- the strip under a work's head is one fold on a narrow screen (REQ-002) ----------------------------------------------------------------
STRIP = """
  const {h, fill} = ctx.App;
  const boxes = (caution) => {
    const chain = h('div', {class: 'vw-chain'}), forecast = h('div', {}), preview = h('div', {class: 'small' + (caution ? ' alert warn' : ' muted')});
    fill(chain, LC.chain(data.ready));
    fill(forecast, h('div', {class: 'ev-applic alert warn'}, h('span', {class: 'pill warn'}, 'измерено при другой ширине')));
    fill(preview, 'Превью: для 5 из 5 слоёв использованы измерения другой ширины.');
    return {chain, forecast, preview};
  };
  const line = (strip) => strip.el.querySelector('summary').textContent;
"""


@node
def test_the_strip_is_open_on_a_wide_screen_and_folded_on_a_narrow_one_and_its_line_says_what_is_folded(tmp_path):
    out = lcui.run(tmp_path, {"ready": lc_answer("file")}, STRIP + """
  const wide = LC.strip(boxes(true));
  out.wide = [wide.el.open, wide.el.children[0].tagName.toLowerCase(), wide.el.children.length];
  let listener = null;
  ctx.matchMedia = (q) => ({media: q, matches: true, addEventListener: (_, fn) => { listener = fn; }});
  const narrow = LC.strip(boxes(true));
  out.narrow = [narrow.el.open, line(narrow), narrow.el.querySelector('summary').getAttribute('data-caution')];
  out.parts = narrow.el.children.length;                                          // the summary and the three boxes: nothing was dropped
  const calm = LC.strip({...boxes(false), forecast: h('div', {})});
  out.calm = [line(calm), calm.el.querySelector('summary').getAttribute('data-caution')];
  // the window grows past the breakpoint: the fold opens by itself, as nothing can be folded on a wide screen; and folds again when it shrinks
  let matches = true; ctx.matchMedia = (q) => ({media: q, get matches() { return matches; }, addEventListener: (_, fn) => { listener = fn; }});
  const live = LC.strip(boxes(true));
  const states = [live.el.open];
  matches = false; listener(); states.push(live.el.open);
  matches = true; listener(); states.push(live.el.open);
  out.states = states;
""")
    assert out["wide"] == [True, "summary", 4]
    assert out["narrow"][0] is False and out["parts"] == 4
    assert "current: File downloaded" in out["narrow"][1] and "prediction: измерено при другой ширине" in out["narrow"][1] and "caveat" in out["narrow"][1]
    assert out["narrow"][2] == "true"
    assert out["states"] == [False, True, False]
    assert "caveat" not in out["calm"][0] and out["calm"][1] is None


@node
def test_the_strips_line_follows_the_boxes_after_the_screen_fills_them_again(tmp_path):
    out = lcui.run(tmp_path, {"ready": lc_answer("file"), "verified": lc_answer("verified")}, STRIP + """
  const b = boxes(false);
  const strip = LC.strip(b);
  out.first = line(strip);
  fill(b.chain, LC.chain(data.verified));
  strip.sync();
  out.second = line(strip);
""")
    assert "current: File downloaded" in out["first"] and "current: Verified" in out["second"]


def test_the_strips_summary_is_hidden_on_a_wide_screen_and_shown_as_a_touch_sized_line_on_a_narrow_one():
    fold = BLOCK[BLOCK.index("12) "):] if "12) " in BLOCK else CSS[CSS.index("12) ux-accessible-layout-p0, final pass"):]
    assert ".lc-strip>.lc-strip-sum {display:none}" in fold.split("@media")[0]
    narrow = fold[fold.index("@media (max-width:600px)"):]
    assert ".lc-strip>.lc-strip-sum {display:block;min-height:44px" in narrow


@node
def test_on_a_phone_the_picture_is_scrolled_up_when_a_choice_opens_the_panel_and_on_a_wider_window_it_is_left_where_it_is(tmp_path):
    out = run_editor(tmp_path, routes(), SLIDE + """
  const scrolled = [];
  stage().scrollIntoView = (o) => scrolled.push(o && o.block);
  await byText(tree, 'button', 'Выделение').dispatch('click');
  ctx.matchMedia = (q) => ({matches: q.includes('1100')});                                // a tablet: the panel slides in from the side, the picture stays
  await path('r1').dispatch('click');
  out.tablet = [state()[0], scrolled.slice()];
  await closer().dispatch('click');
  ctx.matchMedia = () => ({matches: true});                                               // a phone: the panel is a sheet over the lower part
  await path('r2').dispatch('click');
  out.phone = [state()[0], scrolled.slice()];
""")
    assert out["tablet"] == [True, []]
    assert out["phone"] == [True, ["start"]]


def test_the_panel_is_a_sheet_from_the_bottom_with_the_picture_kept_above_it_at_480_px_and_less():
    sheet = CSS[CSS.index("13) ux-accessible-layout-p0, final pass"):]
    narrow = sheet[sheet.index("@media (max-width:480px)"):]
    assert "top:auto;left:0;right:0;width:100%;max-height:60vh;max-height:60dvh" in narrow and "translateY(100%)" in narrow
    assert "html:has(.vw-ed-panel.is-open) {scroll-padding-top:8px;scroll-padding-bottom:60dvh}" in narrow
    assert "body:has(.vw-ed-panel.is-open) .vw-ed-stage {height:34dvh" in narrow
    # the forced-colours border moves to the sheet's top edge
    assert "border-top:2px solid CanvasText" in sheet


# -- what the fixed bar and the dialog's foot must not cover, the catalogue's placeholder, the material picker (REQ-001, REQ-002) --------------
def test_the_unfinished_task_bar_tells_the_stylesheet_its_height_and_the_page_and_the_keyboard_keep_clear_of_it():
    creation = (UI_DIR / "screens" / "creation.js").read_text(encoding="utf-8")
    assert "new ResizeObserver" in creation and "'--creation-bar-h'" in creation and "barHeight.observe(bar)" in creation and "barHeight.disconnect()" in creation
    tail = CSS[CSS.index("17) ux-accessible-layout-p0, final pass"):]
    assert "html body.has-creation-bar {padding-bottom:calc(var(--creation-bar-h,92px) + 8px)}" in tail      # beats creation.css (body.has-creation-bar, 92px)
    assert "html:has(body.has-creation-bar) {scroll-padding-bottom:calc(var(--creation-bar-h,92px) + 8px)}" in tail


def test_a_dialog_keeps_the_height_of_its_foot_free_when_the_browser_scrolls_a_control_into_view():
    tail = CSS[CSS.index("16) ux-accessible-layout-p0, final pass"):]
    assert "@media (max-height:700px),(max-width:600px) {\n  .modal {scroll-padding-bottom:6em}" in tail                 # the same condition as the foot's own stickiness


def test_the_catalogues_placeholder_thumbnail_does_not_take_the_empty_state_cards_padding_and_frame():
    assert ".works-thumb.empty {padding:0" in CSS and ".works-thumb.empty::before {content:none}" in CSS
    assert ".works-name {min-height:24px}" in CSS


def test_the_material_picker_asks_for_the_dialogs_own_width_not_for_80_percent_of_the_window():
    assert ".matpick-body {min-width:min(560px,100%)}" in CSS and ".matpick-body p>a {display:inline-block;padding-block:4px}" in CSS


def test_a_field_with_the_required_tag_wraps_the_tag_under_its_name_instead_of_asking_for_both_widths_side_by_side():
    tail = CSS[CSS.index("18) ux-accessible-layout-p0, final pass"):]
    assert "label.f:has(>.f-required) {display:flex;flex-direction:row;flex-wrap:wrap" in tail
    assert "label.f:has(>.f-required)>* {flex:1 1 100%;min-width:0}" in tail                  # the control and the hints are a line each, and may shrink
    assert "label.f:has(>.f-required)>span:first-child,label.f:has(>.f-required)>.f-required {flex:0 1 auto}" in tail


def test_a_photo_scale_power_row_wraps_its_name_and_its_row_instead_of_asking_for_the_names_width_on_one_line():
    tail = CSS[CSS.index("19) ux-accessible-layout-p0, final pass"):]
    assert ".ge-power {flex-wrap:wrap}" in tail and ".ge-power>.small {white-space:normal;flex:0 1 auto;min-width:0" in tail
    assert ".ge-tone .ge-power {grid-template-columns:minmax(0,1fr) auto}" in tail
    assert ".ge-power input[type=number] {width:6.2em}" in tail                          # 5 em cut the last digit of «29.87» once the spinner took its width


# -- the task panel stands at the end of the page, so the keyboard goes into it and back (REQ-001) ---------------------------------------------
from test_save_feedback_ui import run as run_tasks


@node
def test_the_header_button_takes_the_keyboard_into_the_task_panel_and_escape_and_the_close_button_bring_it_back(tmp_path):
    out = run_tasks(tmp_path, """
  const entry = Operations.entry();
  body.append(entry);
  Operations.begin({kind: 'upload', title: 'Фото 1', stage: 'Загрузка'});
  const panel = () => body.querySelector('.ops-panel');
  const where = () => { const a = doc.activeElement; return a && (a.getAttribute('aria-label') || a.textContent); };
  entry.focus();
  await entry.dispatch('click');
  out.opened = [panel().hidden, where()];                                           // the panel's own first control, not the page's
  await panel().dispatch('keydown', {key: 'Escape'});
  out.escaped = [panel().hidden, where()];                                          // the button that opened it
  await entry.dispatch('click');
  await panel().querySelectorAll('button').find((b) => b.getAttribute('aria-label') === 'Close task list').dispatch('click');
  out.closed = [panel().hidden, where()];
  await entry.dispatch('click');
  await entry.dispatch('click');                                                    // the header button shuts it too, and keeps the keyboard
  out.toggled = [panel().hidden, where()];
  // when the button that opened it is gone (the screen was drawn again), the panel's own button takes the keyboard
  await entry.dispatch('click');
  entry.remove();
  await panel().dispatch('keydown', {key: 'Escape'});
  out.orphan = [panel().hidden, where()];
""")
    assert out["opened"] == [False, "Close task list"]
    assert out["escaped"] == [True, "Tasks: running 1"] and out["closed"] == [True, "Tasks: running 1"] and out["toggled"] == [True, "Tasks: running 1"]
    assert out["orphan"][0] is True and out["orphan"][1].startswith("Tasks — ")


def test_the_task_panel_and_the_notices_stand_above_the_unfinished_task_bar_and_the_list_keeps_below_the_top_of_the_window():
    tail = CSS[CSS.index("21) ux-accessible-layout-p0, final pass"):]
    assert "body.has-creation-bar .ops-dock,body.has-creation-bar .toasts {bottom:calc(var(--creation-bar-h,92px) + 12px)}" in tail
    assert "body.has-creation-bar .ops-panel {max-height:min(60vh,520px,calc(100vh - var(--creation-bar-h,92px) - 120px))}" in tail


def test_a_rows_name_wraps_and_a_row_puts_its_actions_on_a_line_of_their_own_instead_of_leaving_its_text_no_width():
    names = CSS[CSS.index("20) ux-accessible-layout-p0, final pass"):]
    assert ".lst-main>strong {flex:0 1 auto;min-width:0;max-width:100%;white-space:normal;overflow-wrap:anywhere}" in names
    rows = CSS[CSS.index("22) ux-accessible-layout-p0, final pass"):]
    assert ".lst-row {flex-wrap:wrap}" in rows and ".lst-main {flex:1 1 10em}" in rows
