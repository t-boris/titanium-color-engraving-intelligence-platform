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
from test_vector_work import GLUE as WORK_GLUE, TABLES, UI, create, job, routes_of, work    # noqa: F401  (fixtures)

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
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'hardware.js', {code: %(glue)s}, 'screens/vector-split.js', 'screens/vector-editor.js',
  'screens/vector-colours.js', 'screens/vector-workspace.js', 'screens/vector.js']);
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
    second = create(c, name="Витраж", n_colors=4, algorithm="tonal").json()
    ai_op(c, second, style="cubism")
    listed = c["client"].get("/api/vector").json()
    routes = works_routes(c, {f"/api/vector/{first['id']}/copy": {"status": 201, "json": {"id": 77}}, f"/api/plans/{second['id']}": {"status": 200, "json": {}}})
    out = run(tmp_path, routes, {}, f"""
  const cards = tree.querySelectorAll('article');
  out.cards = cards.map((a) => ({{text: a.textContent, img: a.querySelector('img').getAttribute('src'), link: a.querySelector('a').getAttribute('href'),
                                 buttons: a.querySelectorAll('button').map((b) => b.textContent)}}));
  out.heading = tree.querySelectorAll('h2')[0].textContent;
  out.create = byText(tree, 'button', 'Новая работа') != null;
  const mine = cards.find((a) => a.textContent.includes({json.dumps(first['name'])}));
  await byText(mine, 'button', 'Открыть').dispatch('click');
  out.opened = ctx.location.hash;
  await byText(mine, 'button', 'Сделать копию').dispatch('click'); await tick();
  out.copied = ctx.location.hash;
  out.copyPosts = ctx.requests.filter((r) => r.method === 'POST').map((r) => r.path);
  const other = cards.find((a) => a.textContent.includes('Витраж'));
  await byText(other, 'button', 'Удалить').dispatch('click');
  const dialog = ctx.document.body.querySelector('.modal');
  out.question = dialog.textContent;
  out.deletedBeforeAnswer = ctx.requests.filter((r) => r.method === 'DELETE').length;
  await byText(dialog, 'button', 'Удалить').dispatch('click'); await tick();
  out.deleted = ctx.requests.filter((r) => r.method === 'DELETE').map((r) => r.path);
  out.rendered = ctx.__renders.length;
  await byText(tree, 'button', 'Новая работа').dispatch('click');
  out.newWork = ctx.location.hash;
""")
    assert out["heading"] == "Векторная работа" and out["create"] is True and len(out["cards"]) == 2
    by_name = {card["text"].split("Открыть")[0]: card for card in out["cards"]}
    for entry in listed:
        card = next(card for name, card in by_name.items() if name.startswith(entry["name"]))
        assert card["img"].startswith(f"/api/vector/{entry['id']}/thumb.png?v=") and card["link"] == f"#/vector?plan={entry['id']}"
        assert card["buttons"] == ["Открыть", "Сделать копию", "Удалить"]
        assert f"цветов {entry['n_colours']} · областей {entry['regions']} · слоёв {entry['layers']}" in card["text"]
    assert any("Раскраска: AI · Кубизм" in card["text"] for card in out["cards"])
    assert any("Раскраска: Ближе к оригиналу" in card["text"] or "Раскраска: Сохранить тональность" in card["text"] for card in out["cards"])
    assert any("По тонам" in card["text"] for card in out["cards"]) and any("Мозаика" in card["text"] for card in out["cards"])
    assert out["opened"] == f"#/vector?plan={first['id']}" and out["copied"] == "#/vector?plan=77" and out["copyPosts"] == [f"/api/vector/{first['id']}/copy"]
    assert "Удалить работу «Витраж»?" in out["question"] or "Витраж" in out["question"]
    assert "Сделать копию" in out["question"] and "вернуть работу будет нельзя" in out["question"] and out["deletedBeforeAnswer"] == 0     # asked first
    assert out["deleted"] == [f"/api/plans/{second['id']}"] and out["rendered"] >= 1
    assert out["newWork"] == "#/vector?new=1"


@node
def test_without_works_the_list_offers_the_first_one(tmp_path):
    out = run(tmp_path, {"/api/vector": {"status": 200, "json": []}}, {}, """
  out.text = tree.textContent;
  await byText(tree, 'button', 'Новая работа').dispatch('click');
  out.hash = ctx.location.hash;
""")
    assert "Работ пока нет" in out["text"] and out["hash"] == "#/vector?new=1"


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
  const list = tree.querySelectorAll('div').find((d) => d.getAttribute('role') === 'tablist' && d.getAttribute('aria-label') === 'Разделы работы');
  await list.dispatch('keydown', {{key: 'ArrowRight'}});
  out.afterArrow = shown();
  const again = await screen({{plan: {j['id']}}});                          // the screen is built again, as after "Разбить заново"
  out.restored = again.querySelectorAll('div').filter((d) => d.getAttribute('role') === 'tabpanel' && d.getAttribute('id').startsWith('vw-tab-panel-') && !d.hidden).map((d) => d.getAttribute('id'));
  out.head = tree.querySelectorAll('header')[0].textContent;
  out.back = tree.querySelectorAll('a').find((a) => a.textContent === '← Мои работы').getAttribute('href');
  await byText(tree, 'button', 'Сделать копию').dispatch('click'); await tick();
  out.copied = ctx.location.hash;
  await byText(tree, 'button', 'Файл LightBurn').dispatch('click');
  out.afterFile = shown();
  const edTabs = tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab' && b.getAttribute('id').startsWith('vw-ed-tab-')).map((b) => b.textContent);
  out.editorTabs = edTabs;
""")
    assert has_class(out["root"], "workspace") and has_class(out["root"], "vw-work")
    assert [name for name, _ in out["first"]] == ["Разбиение", "Цвета", "AI", "Варианты", "Файл"]
    assert out["first"] == [["Разбиение", "false"], ["Цвета", "true"], ["AI", "false"], ["Варианты", "false"], ["Файл", "false"]] and out["firstShown"] == ["vw-tab-panel-colours"], (out["first"], out["firstShown"])
    assert out["afterClick"][2] == ["AI", "true"] and out["afterClickShown"] == ["vw-tab-panel-ai"] and out["saved"] == "ai"
    assert out["afterArrow"] == ["vw-tab-panel-variants"] and out["restored"] == ["vw-tab-panel-variants"]            # the arrow key moves on; a rebuilt screen keeps the tab
    assert j["name"] in out["head"] and "План гравировки" in out["head"] and "разбиение № " in out["head"] and "слоёв " in out["head"]
    assert out["back"] == "#/vector" and out["copied"] == "#/vector?plan=88" and out["afterFile"] == ["vw-tab-panel-file"]
    assert out["editorTabs"] == ["Кисть", "Слои", "Цвета"]


def has_class(classes: str, name: str) -> bool:
    return name in classes.split()


@node
def test_the_colour_table_opens_in_a_window_and_the_ai_tab_says_when_the_library_is_missing(work, job, tmp_path):
    c, j = work, job
    routes = routes_of(c, j)
    view = routes[f"/api/vector/{j['id']}"]["json"]
    view["ai"] = {**view["ai"], "available": False, "missing": "library"}
    out = run(tmp_path, routes, {"plan": str(j["id"])}, """
  await byText(tree, 'button', 'Подробно по цветам…').dispatch('click');
  const dialog = ctx.document.body.querySelector('.modal');
  out.window = dialog.textContent; out.wide = dialog.querySelectorAll('div').some((d) => has(d, 'vw-wide'));
  const ai = tree.querySelectorAll('div').find((d) => d.className === 'stack vw-ai');
  out.disabled = byText(ai, 'button', 'Раскрасить с помощью AI').disabled;
  out.reason = ai.querySelectorAll('p').filter((p) => p.className === 'alert warn' && !p.hidden).map((p) => p.textContent);
""")
    assert "Исходный цвет" in out["window"] and "Цвет титана" in out["window"] and out["wide"] is True
    assert out["disabled"] is True and len(out["reason"]) == 1 and "библиотека" in out["reason"][0] and "OPENAI_API_KEY" not in out["reason"][0]


# -- the frame -------------------------------------------------------------------------------------------------------------------------
def test_the_workspace_takes_the_screen_without_a_scrolling_page_and_the_router_switches_the_side_menu_off_for_it():
    assert "main.querySelector('.workspace')" in ROUTER and "document.body.classList.toggle('is-workspace', workspace)" in ROUTER
    assert "document.body.classList.remove('is-workspace')" in ROUTER and "node.classList.contains('workspace')" in ROUTER
    assert re.search(r"body\.is-workspace \.app-layout \{grid-template-columns:minmax\(0,1fr\)\}", CSS)
    assert re.search(r"body\.is-workspace \.sidebar \{display:none;position:fixed", CSS) and re.search(r"body\.is-workspace \.mobile-menu \{display:inline-flex\}", CSS)
    assert re.search(r"\.vw-work \{[^}]*height:calc\(100vh - 76px - 20px\)", CSS)                        # one screen high
    assert re.search(r"\.vw-work-body \{[^}]*grid-template-columns:minmax\(290px,330px\) minmax\(0,1fr\) minmax\(260px,320px\)", CSS)       # three columns
    assert re.search(r"\.vw-work \.vw-editor \{display:contents\}", CSS)                                  # the editor's picture and panel are columns of the frame
    assert re.search(r"\.vw-work \.vw-ed-stage \{flex:1;height:auto", CSS)
    assert re.search(r"\.vw-panels \{flex:1;min-height:0;overflow:auto", CSS) and re.search(r"\.vw-ed-panes \{flex:1;min-height:0;overflow:auto", CSS)   # only a long list scrolls
    narrow = re.search(r"@media \(max-width:1100px\) \{(.*?)\n\}", CSS[CSS.index("14) векторная работа"):], re.S)
    assert narrow and ".vw-work-body {grid-template-columns:minmax(0,1fr)}" in narrow.group(1) and ".vw-work {height:auto" in narrow.group(1)   # a phone scrolls as before
