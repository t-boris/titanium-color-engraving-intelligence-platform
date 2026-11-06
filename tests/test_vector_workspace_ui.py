"""The saved works and the one-screen workspace of a vector work (feature vector-detail-and-colour-control, 0.9.0, REQ-053, REQ-054, DEC-085):
the list with a thumbnail, the facts and the open, copy and delete actions of each work; the workspace as tabs on the left, the picture in
the middle and the editor's panel (also in tabs) on the right, without a scrolling page. Run in node over the small DOM of the other
screen tests, with the server's real answers."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_ai_colouring import ai_op, model    # noqa: F401  (the fake client of the model)
from test_vector_work import GLUE as WORK_GLUE, TABLES, UI, create, job, picture, routes_of, work    # noqa: F401  (fixtures)

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
CSS = (UI / "styles.css").read_text(encoding="utf-8")
ROUTER = (UI / "router.js").read_text(encoding="utf-8")
GLUE = WORK_GLUE + ("App.go = (route) => { location.hash = '#' + route; }; const __store = {}; globalThis.localStorage = {getItem: (k) => (k in __store ? __store[k] : null),"
                    "setItem: (k, v) => { __store[k] = String(v); }}; globalThis.__store = __store;")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', 'tasks.js', 'photo-modes.js', 'photo-quality.js', {code: %(glue)s}, 'screens/vector-split.js', 'screens/vector-photo.js', 'screens/lettering.js', 'screens/vector-editor.js',
  'screens/vector-colours.js', 'screens/lifecycle.js', 'screens/vector-review.js', 'screens/vector-workspace.js', 'screens/lab-source.js', 'screens/evidence-summary.js', 'screens/vector.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const has = (el, cls) => (el.className || '').split(' ').includes(cls);
(async () => {
  const out = {};
  const screen = async (query) => { const t = await ctx.__screens.vector.render({query}); await tick(); await tick(); return t; };
  const tree = await screen(data.query);
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, routes, query, body):
    (tmp_path / "data.json").write_text(json.dumps({"query": query, "routes": routes}), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body},
                      encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def works_routes(c, extra=None) -> dict:
    return {"/api/vector": {"status": 200, "json": c["client"].get("/api/vector").json()}, **(extra or {})}


# -- the list --------------------------------------------------------------------------------------------------------------------------
@node
def test_the_list_shows_each_work_with_its_thumbnail_and_facts_and_opens_copies_and_deletes_with_a_question(work, job, model, tmp_path):
    c, first = work, job
    model()
    second = create(c, name="Stained glass", n_colors=4, algorithm="tonal").json()
    ai_op(c, second, style="cubism")
    listed = c["client"].get("/api/vector").json()
    routes = works_routes(c, {f"/api/vector/{first['id']}/copy": {"status": 201, "json": {"id": 77}}, f"/api/plans/{second['id']}": {"status": 200, "json": {}}})
    out = run(tmp_path, routes, {}, f"""
  const cards = tree.querySelectorAll('article');
  out.cards = cards.map((a) => ({{text: a.textContent, img: a.querySelector('img').getAttribute('src'), link: a.querySelector('a').getAttribute('href'),
                                 buttons: a.querySelectorAll('button').map((b) => b.textContent)}}));
  out.heading = tree.querySelectorAll('h2')[0].textContent;
  out.create = byText(tree, 'button', 'New work') != null;
  const mine = cards.find((a) => a.textContent.includes({json.dumps(first['name'])}));
  await byText(mine, 'button', 'Open').dispatch('click');
  out.opened = ctx.location.hash;
  await byText(mine, 'button', 'Make a copy').dispatch('click'); await tick();
  out.copied = ctx.location.hash;
  out.copyPosts = ctx.requests.filter((r) => r.method === 'POST').map((r) => r.path);
  const other = cards.find((a) => a.textContent.includes('Stained glass'));
  await byText(other, 'button', 'Delete').dispatch('click');
  const dialog = ctx.document.body.querySelector('.modal');
  out.question = dialog.textContent;
  out.deletedBeforeAnswer = ctx.requests.filter((r) => r.method === 'DELETE').length;
  await byText(dialog, 'button', 'Delete').dispatch('click'); await tick();
  out.deleted = ctx.requests.filter((r) => r.method === 'DELETE').map((r) => r.path);
  out.rendered = ctx.__renders.length;
  await byText(tree, 'button', 'New work').dispatch('click');
  out.newWork = ctx.location.hash;
""")
    assert out["heading"] == "Vector work" and out["create"] is True and len(out["cards"]) == 2
    by_name = {card["text"].split("Open")[0]: card for card in out["cards"]}
    for entry in listed:
        card = next(card for name, card in by_name.items() if name.startswith(entry["name"]))
        assert card["img"].startswith(f"/api/vector/{entry['id']}/thumb.png?v=") and card["link"] == f"#/vector?plan={entry['id']}"
        assert card["buttons"] == ["✎", "Open", "Make a copy", "Delete"]
        assert f"colors {entry['n_colours']} · regions {entry['regions']} · layers {entry['layers']}" in card["text"]
    assert any("Coloring: AI · Cubism" in card["text"] for card in out["cards"])
    assert any("Coloring: Closer to original" in card["text"] or "Coloring: Preserve tonality" in card["text"] for card in out["cards"])
    assert any("By tone" in card["text"] for card in out["cards"]) and any("Mosaic" in card["text"] for card in out["cards"])
    assert out["opened"] == f"#/vector?plan={first['id']}" and out["copied"] == "#/vector?plan=77" and out["copyPosts"] == [f"/api/vector/{first['id']}/copy"]
    assert "Delete work «Stained glass»?" in out["question"] or "Stained glass" in out["question"]
    assert "Make a copy" in out["question"] and "deleted permanently" in out["question"] and out["deletedBeforeAnswer"] == 0     # asked first
    assert out["deleted"] == [f"/api/plans/{second['id']}"] and out["rendered"] >= 1
    assert out["newWork"] == "#/vector?new=1"


@node
def test_without_works_the_list_offers_the_first_one(tmp_path):
    out = run(tmp_path, {"/api/vector": {"status": 200, "json": []}}, {}, """
  out.text = tree.textContent;
  await byText(tree, 'button', 'New work').dispatch('click');
  out.hash = ctx.location.hash;
""")
    assert "No works yet" in out["text"] and out["hash"] == "#/vector?new=1"


# -- the workspace ---------------------------------------------------------------------------------------------------------------------
@node
def test_the_workspace_has_tabs_that_switch_panels_and_remember_the_open_one_and_a_header_with_the_actions(work, job, tmp_path):
    c, j = work, job
    routes = routes_of(c, j)
    routes[f"/api/vector/{j['id']}/copy"] = {"status": 201, "json": {"id": 88}}
    out = run(tmp_path, routes, {"plan": str(j["id"])}, f"""
  const tabs = () => tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab' && b.getAttribute('id').startsWith('vw-tab-'));
  const state = () => tabs().map((b) => [b.textContent, b.getAttribute('aria-selected')]);
  const shown = () => tree.querySelectorAll('div').filter((d) => d.getAttribute('role') === 'tabpanel' && d.getAttribute('id').startsWith('vw-tab-panel-') && !d.hidden).map((d) => d.getAttribute('id'));
  out.root = tree.className;
  out.first = state(); out.firstShown = shown();
  await byText(tree, 'button', 'AI').dispatch('click');
  out.afterClick = state(); out.afterClickShown = shown(); out.saved = ctx.__store['vw.tab'];
  const list = tree.querySelectorAll('div').find((d) => d.getAttribute('role') === 'tablist' && d.getAttribute('aria-label') === 'Work sections');
  await list.dispatch('keydown', {{key: 'ArrowRight'}});
  out.afterArrow = shown();
  const again = await screen({{plan: {j['id']}}});                          // the screen is built again, as after "Split again"
  out.restored = again.querySelectorAll('div').filter((d) => d.getAttribute('role') === 'tabpanel' && d.getAttribute('id').startsWith('vw-tab-panel-') && !d.hidden).map((d) => d.getAttribute('id'));
  out.head = tree.querySelectorAll('header')[0].textContent;
  out.back = tree.querySelectorAll('a').find((a) => a.textContent === '← My works').getAttribute('href');
  await byText(tree, 'button', 'Make a copy').dispatch('click'); await tick();
  out.copied = ctx.location.hash;
  await byText(tree, 'button', 'LightBurn file').dispatch('click');
  out.afterFile = shown();
  const edTabs = tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab' && b.getAttribute('id').startsWith('vw-ed-tab-')).map((b) => b.textContent);
  out.editorTabs = edTabs;
""")
    assert has_class(out["root"], "workspace") and has_class(out["root"], "vw-work")
    assert [name for name, _ in out["first"]] == ["Segmentation", "Document colors", "AI", "Variants", "Result", "File"]
    assert out["first"] == [["Segmentation", "false"], ["Document colors", "true"], ["AI", "false"], ["Variants", "false"], ["Result", "false"], ["File", "false"]] and out["firstShown"] == ["vw-tab-panel-colours"], (out["first"], out["firstShown"])
    assert out["afterClick"][2] == ["AI", "true"] and out["afterClickShown"] == ["vw-tab-panel-ai"] and out["saved"] == "ai"
    assert out["afterArrow"] == ["vw-tab-panel-variants"] and out["restored"] == ["vw-tab-panel-variants"]            # the arrow key moves on; a rebuilt screen keeps the tab
    assert "Vector work" in out["head"] and j["name"] in out["head"] and "Engraving plan" in out["head"] and "split #" in out["head"] and "layers " in out["head"]
    assert out["back"] == "#/vector" and out["copied"] == "#/vector?plan=88" and out["afterFile"] == ["vw-tab-panel-file"]
    assert out["editorTabs"] == ["Brush", "Layers", "Source colors", "Photo", "Lettering"]


def has_class(classes: str, name: str) -> bool:
    return name in classes.split()


@node
def test_the_colour_table_opens_in_a_window_and_the_ai_tab_says_when_the_library_is_missing(work, job, tmp_path):
    c, j = work, job
    routes = routes_of(c, j)
    view = routes[f"/api/vector/{j['id']}"]["json"]
    view["ai"] = {**view["ai"], "available": False, "missing": "library"}
    out = run(tmp_path, routes, {"plan": str(j["id"])}, """
  await byText(tree, 'button', 'Color details…').dispatch('click');
  const dialog = ctx.document.body.querySelector('.modal');
  out.window = dialog.textContent; out.wide = dialog.querySelectorAll('div').some((d) => has(d, 'vw-wide'));
  out.lines = dialog.querySelectorAll('.lst-main').length;
  await dialog.querySelector('.lst-main').dispatch('click'); await tick();                       // a colour's line opens its titanium colour
  out.opened = dialog.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  const ai = tree.querySelectorAll('div').find((d) => d.className === 'stack vw-ai');
  out.disabled = byText(ai, 'button', 'Color with AI').disabled;
  out.reason = ai.querySelectorAll('p').filter((p) => p.className === 'alert warn' && !p.hidden).map((p) => p.textContent);
""")
    assert "original color, its titanium color" in out["window"] and "Change" in out["window"] and out["wide"] is True
    assert out["lines"] == len(view["colours"]) and "showing" in out["window"]                  # one line per source colour (DEC-090)
    (opened,) = out["opened"]
    assert opened.startswith("Original color") and "Titanium color" in opened and "Recipe" in opened
    assert out["disabled"] is True and len(out["reason"]) == 1 and "library" in out["reason"][0] and "OPENAI_API_KEY" not in out["reason"][0]


# -- the frame -------------------------------------------------------------------------------------------------------------------------
def test_the_workspace_takes_the_screen_without_a_scrolling_page_and_the_section_rail_stays():
    assert "main.querySelector('.workspace')" in ROUTER and "document.body.classList.toggle('is-workspace', workspace)" in ROUTER
    assert "document.body.classList.remove('is-workspace')" in ROUTER and "node.classList.contains('workspace')" in ROUTER
    assert re.search(r"body\.is-workspace \.main \{max-width:none", CSS) and "body.is-workspace .sidebar" not in CSS      # the rail stays (DEC-081)
    assert re.search(r"\.vw-work \{[^}]*height:calc\(100vh - 76px - 20px\)", CSS)                        # one screen high
    assert re.search(r"\.vw-work-body \{[^}]*grid-template-columns:minmax\(290px,330px\) minmax\(0,1fr\) minmax\(260px,320px\)", CSS)       # three columns
    assert re.search(r"\.vw-work \.vw-editor \{display:contents\}", CSS)                                  # the editor's picture and panel are columns of the frame
    assert re.search(r"\.vw-work \.vw-ed-stage \{flex:1;height:auto", CSS)
    assert re.search(r"\.vw-panels \{flex:1;min-height:0;overflow:auto", CSS) and re.search(r"\.vw-ed-panes \{flex:1;min-height:0;overflow:auto", CSS)   # only a long list scrolls
    narrow = re.search(r"@media \(max-width:1100px\) \{(.*?)\n\}", CSS[CSS.index("14) vector work"):], re.S)
    assert narrow and ".vw-work-body {grid-template-columns:minmax(0,1fr)}" in narrow.group(1) and ".vw-work {height:auto" in narrow.group(1)   # a phone scrolls as before


# -- renaming (REQ-055, DEC-086) ---------------------------------------------------------------------------------------------------------
VECTOR_JS = (UI / "screens" / "vector.js").read_text(encoding="utf-8")
def body(name: str) -> str:
    """The body the screen sends: compact JSON as the browser writes it."""
    return json.dumps({"name": name}, separators=(",", ":"), ensure_ascii=False)


PENCIL = "b.getAttribute('aria-label') && b.getAttribute('aria-label').startsWith('Rename work')"
DIALOG = "const dialog = () => ctx.document.body.querySelector('.modal');"
POSTS = "const posts = () => ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, r.body]);"
TOASTS = "const toasts = () => ctx.document.body.querySelectorAll('.toast').map((t) => [t.className, t.textContent]);"


@node
def test_the_pencil_on_a_card_opens_a_dialog_with_the_name_and_renames_in_place_with_one_request(work, job, tmp_path):
    c, j = work, job
    routes = works_routes(c, {f"/api/vector/{j['id']}/rename": {"status": 200, "json": {"id": j["id"], "name": "Imma + Boris"}}})
    out = run(tmp_path, routes, {}, f"""
  {DIALOG} {POSTS} {TOASTS}
  const card = tree.querySelectorAll('article')[0];
  const pencil = card.querySelectorAll('button').find((b) => {PENCIL});
  out.pencil = [pencil.textContent, pencil.getAttribute('title'), pencil.getAttribute('aria-label'), has(pencil, 'vw-rename')];
  out.beforeTitle = card.querySelector('h3').textContent;
  await pencil.dispatch('click');
  const first = dialog();
  out.dialog = [first.querySelector('h3').textContent, first.querySelector('input').value, first.querySelectorAll('button').map((b) => b.textContent)];
  out.fieldLabel = first.querySelector('label').textContent;
  first.querySelector('input').value = '  Imma + Boris  ';
  await byText(first, 'button', 'Save').dispatch('click'); await tick();
  out.posts = posts();
  out.title = card.querySelector('h3').textContent;
  out.labels = [pencil.getAttribute('aria-label'), card.querySelector('a').getAttribute('aria-label')];
  out.closed = dialog() == null;
  out.toasts = toasts();
  await pencil.dispatch('click');                                     // the next rename starts from the name it has now
  out.again = dialog().querySelector('input').value;
""")
    assert out["pencil"] == ["✎", "Rename", f"Rename work «{j['name']}»", True] and out["beforeTitle"] == j["name"]
    assert out["dialog"] == ["Rename work", j["name"], ["×", "Cancel", "Save"]] and "Name" in out["fieldLabel"]
    assert out["posts"] == [[f"/api/vector/{j['id']}/rename", body("Imma + Boris")]]                  # trimmed, one request
    assert out["title"] == "Imma + Boris" and out["labels"] == ["Rename work «Imma + Boris»", "Open work Imma + Boris"] and out["closed"] is True
    assert out["toasts"] == [["toast ok", "Work renamed ×"]] and out["again"] == "Imma + Boris"


@node
def test_a_blank_name_is_refused_before_any_request_and_the_name_as_it_is_or_cancel_close_the_dialog_without_one(work, job, tmp_path):
    c, j = work, job
    routes = works_routes(c, {f"/api/vector/{j['id']}/rename": {"status": 200, "json": {"id": j["id"], "name": "x"}}})
    out = run(tmp_path, routes, {}, f"""
  {DIALOG} {POSTS} {TOASTS}
  const card = tree.querySelectorAll('article')[0];
  const open = async () => {{ await card.querySelectorAll('button').find((b) => {PENCIL}).dispatch('click'); return dialog(); }};
  let d = await open();
  d.querySelector('input').value = '    ';
  await byText(d, 'button', 'Save').dispatch('click'); await tick();
  out.blank = [posts().length, dialog() != null, toasts().map((t) => t[0] + ' ' + t[1]), d.querySelector('input').getAttribute('aria-invalid'),
    d.querySelectorAll('span').filter((x) => x.classList.contains('f-error')).map((x) => x.textContent), d.querySelector('input').value];
  d.querySelector('input').value = ' ' + card.querySelector('h3').textContent + ' ';
  await byText(d, 'button', 'Save').dispatch('click'); await tick();
  out.same = [posts().length, dialog() == null];
  d = await open();
  d.querySelector('input').value = 'Something else';
  await byText(d, 'button', 'Cancel').dispatch('click'); await tick();
  out.cancel = [posts().length, dialog() == null, card.querySelector('h3').textContent];
""")
    # refused before any request, the reason beside the field (no toast), what was typed kept, the dialog open for another try
    assert out["blank"] == [0, True, [], "true", ["Enter a work name"], "    "]
    assert out["same"] == [0, True] and out["cancel"] == [0, True, j["name"]]


@node
def test_enter_saves_once_even_when_pressed_twice_and_an_input_method_composing_does_not_save(work, job, tmp_path):
    c, j = work, job
    routes = works_routes(c, {f"/api/vector/{j['id']}/rename": {"status": 200, "json": {"id": j["id"], "name": "Via Enter"}}})
    out = run(tmp_path, routes, {}, f"""
  {DIALOG} {POSTS}
  const card = tree.querySelectorAll('article')[0];
  await card.querySelectorAll('button').find((b) => {PENCIL}).dispatch('click');
  const input = dialog().querySelector('input');
  input.value = 'Via Enter';
  await input.dispatch('keydown', {{key: 'Enter', isComposing: true}}); await tick();
  out.composing = posts().length;
  await input.dispatch('keydown', {{key: 'a'}}); await tick();
  out.otherKey = posts().length;
  await Promise.all([input.dispatch('keydown', {{key: 'Enter'}}), input.dispatch('keydown', {{key: 'Enter'}})]); await tick(); await tick();
  out.posts = posts();
  out.title = card.querySelector('h3').textContent;
""")
    assert out["composing"] == 0 and out["otherKey"] == 0
    assert out["posts"] == [[f"/api/vector/{j['id']}/rename", body("Via Enter")]] and out["title"] == "Via Enter"


@node
def test_a_refused_rename_keeps_the_dialog_open_and_can_be_tried_again(work, job, tmp_path):
    c, j = work, job
    routes = works_routes(c, {f"/api/vector/{j['id']}/rename": {"status": 422, "json": {"error": "give the plan a name", "kind": "validation"}}})
    out = run(tmp_path, routes, {}, f"""
  {DIALOG} {POSTS} {TOASTS}
  const card = tree.querySelectorAll('article')[0];
  await card.querySelectorAll('button').find((b) => {PENCIL}).dispatch('click');
  const d = dialog();
  d.querySelector('input').value = 'Another';
  await byText(d, 'button', 'Save').dispatch('click'); await tick();
  await byText(d, 'button', 'Save').dispatch('click'); await tick();        // the failure did not lock the dialog
  out.posts = posts().length;
  out.open = dialog() != null;
  out.title = card.querySelector('h3').textContent;
  out.toasts = toasts().map((t) => t[0]);
  out.beside = [d.querySelectorAll('span').filter((x) => x.classList.contains('f-error')).length, d.querySelector('input').value, d.querySelector('input').getAttribute('aria-invalid') !== 'true'];
  out.said = d.querySelectorAll('p').filter((p) => p.getAttribute('role') === 'alert').map((p) => p.textContent);
""")
    # the refusal of the server is said under the dialog's field, not in a toast; the name typed stays and a second try is sent
    assert out["posts"] == 2 and out["open"] is True and out["title"] == j["name"] and out["toasts"] == []
    assert out["beside"][1] == "Another" and "give the plan a name" in out["said"][0] and "remain in the form" in out["said"][0]


@node
def test_the_header_of_a_work_renames_it_and_keeps_its_pencil_when_the_screen_is_refreshed(work, job, tmp_path):
    c, j = work, job
    routes = routes_of(c, j)
    routes[f"/api/vector/{j['id']}/rename"] = {"status": 200, "json": {"id": j["id"], "name": "New name"}}
    routes[f"/api/vector/{j['id']}/colouring"] = {"status": 200, "json": {**routes[f"/api/vector/{j['id']}"]["json"], "name": "New name"}}    # the server's answer after the rename
    out = run(tmp_path, routes, {"plan": str(j["id"])}, f"""
  {DIALOG} {POSTS}
  const head = () => tree.querySelectorAll('header')[0];
  const pencils = () => head().querySelectorAll('button').filter((b) => {PENCIL});
  out.before = [head().querySelector('h2').textContent, pencils().length, pencils()[0].getAttribute('aria-label')];
  await pencils()[0].dispatch('click');
  const d = dialog();
  out.prefill = d.querySelector('input').value;
  d.querySelector('input').value = 'New name';
  await byText(d, 'button', 'Save').dispatch('click'); await tick(); await tick();
  out.after = [head().querySelector('h2').textContent, pencils().length, pencils()[0].getAttribute('aria-label')];
  out.posts = posts();
  await byText(tree, 'button', 'Random').dispatch('click'); await tick(); await tick();       // an operation: the screen shows the server's view again
  out.refreshed = [head().querySelector('h2').textContent, pencils().length, pencils()[0].getAttribute('aria-label'), head().querySelector('.sub').textContent.includes('split #')];
""")
    assert out["before"] == [j["name"], 1, f"Rename work «{j['name']}»"] and out["prefill"] == j["name"]
    assert out["after"] == ["New name", 1, "Rename work «New name»"] and out["posts"] == [[f"/api/vector/{j['id']}/rename", body("New name")]]
    assert out["refreshed"] == ["New name", 1, "Rename work «New name»", True]


def test_the_long_page_of_the_other_strategies_uses_the_same_pencil_and_the_title_follows_the_new_name():
    assert "VectorWorkspace.renameButton(j.id, j.name," in VECTOR_JS and "fill(heading, 'Vector work · ' + stored)" in VECTOR_JS
    assert "renamed: (name) => { shown = {...shown, name}; head.update(shown); }" in VECTOR_JS                          # the photo header keeps the stored name
    assert "return {list, header, frame, renameButton};" in (UI / "screens" / "vector-workspace.js").read_text(encoding="utf-8")
    assert re.search(r"\.vw-rename \{[^}]*flex:none", CSS) and re.search(r"\.vw-name-row \{[^}]*display:flex", CSS)


@node
def test_the_header_changes_the_size_of_the_work_by_one_side_the_other_following_the_picture(work, job, tmp_path):
    """Feature work-size-and-splitting-a-region-again, REQ-001: «Size…» opens two linked fields; the side typed last is sent, the head and the
    editor show the work the server answers with."""
    c, j = work, job
    routes = routes_of(c, j)
    view = routes[f"/api/vector/{j['id']}"]["json"]
    routes[f"/api/vector/{j['id']}/size"] = {"status": 200, "json": {**view, "size_mm": {"width": 120.0, "height": 90.0},
                                                                     "document": {**view["document"], "size_mm": {"width": 120.0, "height": 90.0}, "version": 2}}}
    out = run(tmp_path, routes, {"plan": str(j["id"])}, f"""
  {DIALOG} {POSTS} {TOASTS}
  const head = () => tree.querySelectorAll('header')[0];
  out.before = head().querySelector('.sub').textContent;
  await byText(head(), 'button', 'Size…').dispatch('click');
  const d = dialog();
  const inputs = () => d.querySelectorAll('input');
  out.prefill = inputs().map((i) => [d.querySelectorAll('span').find((x) => x.getAttribute('id') === i.getAttribute('aria-labelledby')).textContent, i.value]);
  inputs()[0].value = '30'; await inputs()[0].dispatch('input');
  out.linkedHeight = inputs()[1].value;
  inputs()[1].value = '90'; await inputs()[1].dispatch('input');
  out.linkedWidth = inputs()[0].value;
  out.text = d.textContent;
  await byText(d, 'button', 'Resize').dispatch('click'); await tick(); await tick(); await tick();
  out.posts = posts().map(([path, body]) => [path, JSON.parse(body)]);
  out.closed = dialog() == null;
  out.after = head().querySelector('.sub').textContent;
  out.toasts = toasts().map((t) => t[1]);
  await byText(head(), 'button', 'Size…').dispatch('click');
  const again = dialog();
  out.again = again.querySelectorAll('input').map((i) => i.value);
  await byText(again, 'button', 'Resize').dispatch('click'); await tick();      // the size as it is: closed without a request
  out.unchanged = [dialog() == null, posts().length];
""")
    assert out["before"].startswith("60.0 × 45.0 mm") and out["prefill"] == [["Width", "60"], ["Height", "45"]]
    assert out["linkedHeight"] == "22.5" and out["linkedWidth"] == "120"
    assert "follows the image proportions" in out["text"] and "undo this change" in out["text"]
    assert out["posts"] == [[f"/api/vector/{j['id']}/size", {"height_mm": 90}]] and out["closed"] is True
    assert out["after"].startswith("120.0 × 90.0 mm") and "split #2" in out["after"]
    assert any("120.0 × 90.0 mm" in t for t in out["toasts"])
    assert out["again"] == ["120", "90"] and out["unchanged"] == [True, 1]


# -- ux-save-feedback-p0, REQ-003: the numbers of a vector work are checked beside their boxes ------------------------------------------------
@node
def test_a_wrong_size_is_said_beside_its_box_with_nothing_sent_and_what_was_typed_kept(work, job, tmp_path):
    c, j = work, job
    out = run(tmp_path, routes_of(c, j), {"plan": str(j["id"])}, f"""
  {DIALOG} {POSTS}
  await byText(tree.querySelectorAll('header')[0], 'button', 'Size…').dispatch('click');
  const d = dialog();
  const width = () => d.querySelectorAll('input')[0];
  const said = () => d.querySelectorAll('span').filter((x) => x.classList.contains('f-error')).map((x) => x.textContent);
  width().value = '-5'; await width().dispatch('input');
  await byText(d, 'button', 'Resize').dispatch('click'); await tick();
  out.negative = [posts().length, said(), width().value, width().getAttribute('aria-invalid'), dialog() != null];
  width().value = ''; await width().dispatch('input');
  await byText(d, 'button', 'Resize').dispatch('click'); await tick();
  out.empty = [posts().length, said()];
  width().value = '12abc'; await width().dispatch('input');
  await byText(d, 'button', 'Resize').dispatch('click'); await tick();
  out.letters = [posts().length, said()];
""")
    assert out["negative"][0] == 0 and "Allowed" in out["negative"][1][0] and "Entered: -5" in out["negative"][1][0]
    assert out["negative"][2:] == ["-5", "true", True]
    assert out["empty"] == [0, ["Complete this field"]]
    assert out["letters"][0] == 0 and len(out["letters"][1]) == 1


@node
def test_the_split_colours_the_colour_settings_and_the_ai_description_are_checked_before_anything_is_asked_or_sent(work, job, tmp_path):
    c, j = work, job
    out = run(tmp_path, routes_of(c, j), {"plan": str(j["id"])}, f"""
  {DIALOG} {POSTS}
  const said = (root) => root.querySelectorAll('span').filter((x) => x.classList.contains('f-error')).map((x) => x.textContent);
  const labelled = (text) => tree.querySelectorAll('label').find((l) => (l.querySelector('span') || {{}}).textContent === text);
  // the colours of the split: a wrong number is refused beside the box and the question about splitting again is not even asked
  const colours = labelled('Number of colors').firstControl();
  colours.value = '99'; await colours.dispatch('input');
  const before = ctx.requests.filter((r) => r.method === 'POST').length;
  await byText(tree, 'button', 'Split again').dispatch('click'); await tick();
  out.colours = [dialog() == null, ctx.requests.filter((r) => r.method === 'POST').length - before, said(labelled('Number of colors')), colours.value, colours.getAttribute('aria-invalid')];
  colours.value = '12'; await colours.dispatch('input');
  await byText(tree, 'button', 'Split again').dispatch('click'); await tick();
  out.asked = [dialog() != null, said(labelled('Number of colors'))];
  // the settings of the colours: the longest time must be above 0
  const time = labelled('Maximum time').firstControl();
  time.value = '0'; await time.dispatch('input');
  await byText(tree, 'button', 'Apply').dispatch('click'); await tick();
  out.time = [ctx.requests.filter((r) => r.method === 'POST' && r.path.endsWith('/edit')).length, said(labelled('Maximum time')), time.value];
  // the AI colouring with a description of its own: it must be there and short enough
  const style = tree.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'AI coloring style');
  style.value = 'custom'; await style.dispatch('change');
  const text = tree.querySelectorAll('input').find((i) => (i.getAttribute('placeholder') || '').startsWith('for example'));
  const go = byText(tree, 'button', 'Color with AI');
  const posted = () => ctx.requests.filter((r) => r.method === 'POST').length;
  const mark = posted();
  text.value = '   '; await text.dispatch('input'); await go.dispatch('click'); await tick();
  out.blankText = [posted() - mark, said(labelled('Custom description')), go.disabled];
  text.value = 'x'.repeat(401); await text.dispatch('input'); await go.dispatch('click'); await tick();
  out.longText = [posted() - mark, said(labelled('Custom description')), text.value.length];
""")
    assert out["colours"][:2] == [True, 0] and "Allowed" in out["colours"][2][0] and "Entered: 99" in out["colours"][2][0]
    assert out["colours"][3:] == ["99", "true"]
    assert out["asked"] == [True, []]
    assert out["time"][0] == 0 and "Entered: 0" in out["time"][1][0] and out["time"][2] == "0"
    assert out["blankText"] == [0, ["Describe the desired coloring"], False]
    assert out["longText"][0] == 0 and "400" in out["longText"][1][0] and out["longText"][2] == 401


@node
def test_the_tolerance_and_the_threshold_of_a_silhouette_work_are_checked_beside_their_boxes_and_a_refusal_stands_under_the_box(work, tmp_path):
    made = work["client"].post("/api/vector", data={"device_id": work["w"]["setup"][0], "lens_id": work["w"]["setup"][1], "material_id": work["ti"],
                                                    "name": "Old", "width_mm": 50, "strategy": "fill", "threshold": 8},
                               files={"image": ("a.png", picture(), "image/png")})
    assert made.status_code == 201, made.text
    j = made.json()
    routes = {f"/api/vector/{j['id']}": {"status": 200, "json": work["client"].get(f"/api/vector/{j['id']}").json()},
              f"/api/vector/{j['id']}/edit": {"status": 422, "json": {"error": "enter a non-negative delta E threshold", "kind": "validation"}}}
    out = run(tmp_path, routes, {"plan": str(j["id"])}, f"""
  {POSTS}
  const labelled = (text) => tree.querySelectorAll('label').find((l) => (l.querySelector('span') || {{}}).textContent === text);
  const said = (text) => labelled(text).errorText();
  const tol = labelled('Outline precision').firstControl(), thr = labelled('ΔE threshold').firstControl();
  tol.value = '-1'; await tol.dispatch('input');
  await byText(tree, 'button', 'Apply precision').dispatch('click'); await tick();
  out.tolerance = [posts().length, said('Outline precision'), tol.value, tol.getAttribute('aria-invalid')];
  thr.value = ''; await thr.dispatch('input');
  await byText(tree, 'button', 'Apply threshold').dispatch('click'); await tick();
  out.empty = [posts().length, said('ΔE threshold')];
  thr.value = '4'; await thr.dispatch('input');
  await byText(tree, 'button', 'Apply threshold').dispatch('click'); await tick(); await tick();
  out.refused = [posts().length, thr.value, thr.getAttribute('aria-invalid'), said('ΔE threshold')];
""")
    assert out["tolerance"][0] == 0 and "Entered: -1" in out["tolerance"][1] and out["tolerance"][2:] == ["-1", "true"]
    assert out["empty"] == [0, "Complete this field"]
    assert out["refused"][:3] == [1, "4", "true"] and out["refused"][3]                                      # sent once; the number stays, the refusal stands under it
