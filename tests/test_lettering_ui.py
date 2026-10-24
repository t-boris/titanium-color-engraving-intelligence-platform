"""Inscriptions on the screens (feature inscriptions-in-works, REQ-001..REQ-005): the «Надписи» tab of the vector editor and of a photo work,
the font window and the layer of inscriptions over the picture. Static checks of the shared module against the server's contract (its
fields, limits, choices, scripts and kinds), then the screens run in node over the small DOM of the other screen tests with inscriptions
shaped as the API sends them: each change of an inscription is one operation of its work, a drag on the picture moves, turns or sizes it
about its frame's anchor, a path is drawn with clicks, the font window lists, filters, previews and downloads fonts."""
import json
import re
import subprocess
from pathlib import Path

import pytest
from shapely.geometry import box

import test_photo_engraving_ui as photo_ui
from test_vector_editor_ui import PALETTE, node, routes, run_editor, view
from titanium_platform import fonts, lettering, prediction
from titanium_platform.api.app import UI_DIR

LETTERING = (UI_DIR / "screens" / "lettering.js").read_text(encoding="utf-8")
PHOTO = (UI_DIR / "screens" / "photo-engraving.js").read_text(encoding="utf-8")
SCRIPTS = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))

FRAME = {"anchor": [12.0, 7.0], "corners": [[10.0, 5.0], [14.0, 5.0], [14.0, 9.0], [10.0, 9.0]], "rotation": 0.0}
SHOWN = {"letters": "M10 5 L14 5 L14 9 L10 9 Z", "backing": "", "cut": "M9.7 4.7 L14.3 4.7 L14.3 9.3 L9.7 9.3 Z", "guide": None,
         "frame": FRAME, "missing": "", "clipped": False, "overflow": False, "area_mm2": 16.0, "backing_mm2": 0.0, "empty": False}
FONT = {"face": "f1", "family": "Arial", "style": "Regular"}


def text(tid, **over) -> dict:
    """An inscription as ``lettering.shown_row`` sends it: its fields, how it is drawn, its colours and why it cannot be engraved."""
    return {**lettering.DEFAULTS, "id": tid, "text": "HOH", "font": FONT, "height_mm": 4.0, "x": 12.0, "y": 7.0, "entry_id": "e14",
            "shown": SHOWN, "srgb": [60, 70, 200], "backing_srgb": None, "problem": None, **over}


def test_the_shown_inscription_of_these_tests_has_the_keys_the_server_sends():
    geom = {"letters": box(10, 5, 14, 9), "backing": None, "cut": box(9.7, 4.7, 14.3, 9.3), "guide": None, "frame": FRAME, "missing": [],
            "clipped": False, "overflow": False}
    assert set(lettering.shown(geom)) == set(SHOWN)
    assert set(text("t1")) == set(lettering.FIELDS) | {"id", "shown", "srgb", "backing_srgb", "problem"}


# -- static ------------------------------------------------------------------------------------------------------------------------
def test_the_module_is_loaded_before_the_screens_that_use_it_and_its_translations_with_the_tables():
    order = {s: i for i, s in enumerate(SCRIPTS)}
    assert order["/dialogs.js"] < order["/filepick.js"] < order["/screens/lettering.js"] < order["/screens/photo-panels.js"] < order["/screens/vector-editor.js"]
    assert order["/i18n-lettering.js"] < order["/i18n-gaps.js"] < order["/app.js"]


def test_the_panel_offers_every_field_of_an_inscription_within_the_servers_limits():
    numbers = dict(re.findall(r"number\('[^']+', '(\w+)', '[\d.]+'(?:, \{([^}]*)\})?\)", LETTERING))
    assert set(numbers) == set(lettering.NUMBERS)
    for key, extra in numbers.items():
        low, high, _ = lettering.NUMBERS[key]
        limits = dict(re.findall(r"(min|max): '(-?[\d.]+)'", extra))
        assert float(limits.get("min", low)) >= low and float(limits.get("max", high)) <= high, key
        assert not limits or float(limits.get("min", low)) == low, key            # the least the server takes, where it is set
    for name, values in (("LAYOUTS", lettering.LAYOUTS), ("ALIGNS", lettering.ALIGNS), ("LETTERS", lettering.LETTERS), ("BACKINGS", lettering.BACKINGS)):
        listed = re.search(rf"const {name} = \[(.*?)\];", LETTERING).group(1)
        assert re.findall(r"\['(\w+)', '", listed) == list(values), name
    for flag in lettering.FLAGS:
        assert f"flag('" in LETTERING and f"', '{flag}')" in LETTERING, flag
    for op in lettering.OPS:
        assert f"op: '{op}'" in LETTERING, op
    assert "swatches('Цвет букв', 'entry_id', false)" in LETTERING and "swatches('Цвет подложки', 'backing_entry_id', true)" in LETTERING


def test_the_font_window_names_every_script_kind_and_source_of_the_catalogue():
    for group, keys in (("SCRIPTS", fonts.SCRIPTS), ("KINDS", fonts.KINDS), ("SOURCES", fonts.SOURCES)):
        body = re.search(rf"const {group} = \{{(.*?)\}};", LETTERING, re.S).group(1)
        assert set(re.findall(r"(\w+): '", body)) == set(keys), group
    assert "`/api/fonts/preview.svg?face=${encodeURIComponent(faceId)}&text=${encodeURIComponent(sampleText())}&height=10`" in LETTERING
    for call in ("get('/fonts')", "post('/fonts/google/family', {family})", "post('/fonts/google/index')", "get('/fonts/google/status')",
                 "post('/fonts/google/download', {script: script.value, kind: kind.value || null})", "form('/fonts/own', fd)",
                 "del(`/fonts/own/${encodeURIComponent(x.id)}`)"):
        assert call in LETTERING, call
    letters = re.search(r"const LETTERS_OF = \[(.*?)\];", LETTERING, re.S).group(1)
    assert set(re.findall(r"\['(\w+)', /", letters)) == set(fonts.SCRIPTS) - {"latin"}     # the window opens on the script of the text
    assert "script.value = scriptOf(sample);" in LETTERING
    assert f"const AUTO_BYTES = 2 * 1024 * 1024;" in LETTERING and "App.filePick(ownInput, 'Добавить файл шрифта')" in LETTERING


def test_the_photo_work_lays_the_layer_over_its_look_with_the_previews_own_gap():
    assert f"const PREVIEW_GAP = {prediction.GAP};" in PHOTO
    assert "lettering.attach(el, cols, PREVIEW_GAP)" in PHOTO and "send(`${base}/texts`, op)" in PHOTO and "get(`${base}/palette`)" in PHOTO
    assert "preserveAspectRatio: 'xMidYMid meet'" in LETTERING          # as the preview is contained in its box (object-fit: contain)


# -- the vector editor in node -------------------------------------------------------------------------------------------------------
FONTS = {"families": [
    {"family": "Arial", "source": "mac", "kind": "sans", "scripts": ["latin", "cyrillic"], "downloaded": True, "popularity": None,
     "faces": [{"id": "f1", "style": "Regular", "weight": 400, "italic": False}, {"id": "f2", "style": "Bold", "weight": 700, "italic": False}],
     "regular": "f1"},
    {"family": "My Hand", "source": "own", "kind": "handwriting", "scripts": ["latin"], "downloaded": True, "popularity": None,
     "faces": [{"id": "o0", "style": "Thin", "weight": 100, "italic": False}, {"id": "o1", "style": "Regular", "weight": 400, "italic": False}],
     "regular": "o1"},
    {"family": "Noto Sans Hebrew", "source": "google", "kind": "sans", "scripts": ["latin", "hebrew"], "downloaded": False, "popularity": 120,
     "faces": [], "size": 300000}],
    "scripts": list(fonts.SCRIPTS), "kinds": list(fonts.KINDS), "sources": list(fonts.SOURCES),
    "google": {"listed": True, "fetched_at": "2026-10-23T09:00:00", "families": 1, "downloaded": 0,
               "download": {"running": False, "done": 0, "total": 0, "failed": [], "current": None, "error": None}}}


def editor_routes(**over) -> dict:
    j = view()
    j["texts"] = [text("t1"), text("t2", text="Шалом", layout="path", points=[[0, 0], [10, 0]], x=5.0, y=15.0, entry_id="e12",
                                   srgb=[150, 60, 90], problem="its font has no letters «Ж»: choose a font that has them")]
    j["text_defaults"] = lettering.DEFAULTS
    j["export_blocked"] = "inscription 2 cannot be engraved: its font has no letters «Ж»: choose a font that has them"
    j["layers"][2]["texts"] = ["t1"]
    j.update(over)
    out = routes(j)
    out["/api/vector/7"] = {"status": 200, "json": j}
    out["/api/fonts"] = {"status": 200, "json": FONTS}
    out["/api/fonts/google/family"] = {"status": 200, "json": {"faces": [{"face": "g0", "family": "Noto Sans Hebrew", "style": "Thin"},
                                                                         {"face": "g1", "family": "Noto Sans Hebrew", "style": "Regular"}]}}
    return out


OPEN = """
  ctx.document.body.append(tree);                                                  // on screen, as the app shows it
  const tab = tree.querySelectorAll('button').find((b) => b.getAttribute('id') === 'vw-ed-tab-texts');
  await tab.dispatch('click'); await tick();
  const stage = tree.querySelectorAll('div').find((d) => d.classList.contains('vw-ed-stage'));
  const item = (n) => tree.querySelectorAll('button').filter((b) => b.classList.contains('lt-item'))[n];
  const field = (label) => byLabel(tree, 'input', label);
  const group = (label) => tree.querySelectorAll('div').find((d) => d.getAttribute('aria-label') === label);
  const textOps = () => posted().filter((op) => op.op && op.op.startsWith('text_'));
  const drawnText = (id) => svg().querySelectorAll('g').find((g) => g.getAttribute('data-text') === id);
  const handle = (kind) => svg().querySelectorAll('rect, circle').find((c) => c.getAttribute('data-handle') === kind);
  const pane = tree.querySelectorAll('div').find((d) => d.classList.contains('lt-pane'));
"""


@node
def test_the_tab_draws_the_inscriptions_cut_into_the_picture_and_each_change_is_an_operation_of_the_work(tmp_path):
    out = run_editor(tmp_path, editor_routes(), OPEN + """
  out.svgClass = svg().getAttribute('class');
  out.order = svg().childNodes.filter((c) => c.nodeType === 1).slice(-2).map((c) => c.getAttribute('class'));
  out.drawn = drawnText('t1').childNodes.map((p) => [p.getAttribute('class'), p.getAttribute('fill'), p.getAttribute('fill-rule')]);
  out.items = [0, 1].map((n) => item(n).textContent);
  await byText(pane, 'button', 'Добавить надпись').dispatch('click'); await tick();
  await item(0).dispatch('click'); await tick();
  out.picked = item(0).getAttribute('aria-pressed');
  out.marks = svg().querySelectorAll('g').find((g) => g.classList.contains('lt-marks')).querySelectorAll('polygon, rect, circle').map((m) => m.getAttribute('class') + ':' + (m.getAttribute('data-handle') || ''));
  out.height = field('Высота букв, мм').value;
  field('Высота букв, мм').value = '12'; await field('Высота букв, мм').dispatch('change'); await tick();
  await wait(5);
  out.swatches = group('Цвет букв').querySelectorAll('button').map((b) => b.getAttribute('data-entry') + ':' + b.getAttribute('aria-pressed'));
  out.backingSwatches = group('Цвет подложки').querySelectorAll('button').map((b) => b.getAttribute('aria-label').split(' ')[0]);
  await group('Цвет букв').querySelectorAll('button')[1].dispatch('click'); await tick();
  await byText(group('Расположение'), 'button', 'По кругу').dispatch('click'); await tick();
  out.hidden = tree.querySelectorAll('div').filter((d) => d.getAttribute('data-for')).map((d) => d.getAttribute('data-for') + ':' + d.hidden);
  await byText(pane, 'button', 'Копия').dispatch('click'); await tick();
  await byText(pane, 'button', 'Удалить').dispatch('click'); await tick();
  const ta = pane.querySelectorAll('textarea')[0];
  ta.value = 'HOH\\nвторая'; await ta.dispatch('change'); await tick();
  out.ops = textOps();
""")
    assert "show-texts" in out["svgClass"]
    assert out["order"] == ["lt-layer", "vw-outlines"]                       # over the regions, under the outlines that take no pointer
    assert out["drawn"] == [["lt-cut", "#e6e6e6", "evenodd"], ["lt-letters", "rgb(60,70,200)", "evenodd"]]   # the gap is clean titanium
    assert out["items"][0].startswith("№ 1HOH") and "Arial" in out["items"][0] and "не выгравировать" in out["items"][1]
    assert out["picked"] == "true" and out["height"] == "4"
    assert out["marks"] == ["lt-frame:", "lt-handle:rotate", "lt-handle:size"]
    assert out["swatches"] == ["e14:true", "e12:false", "e13:false", "e11:false"]                    # darkest first, its colour chosen
    assert out["backingSwatches"][0] == "Чистый"
    assert out["hidden"] == ["arc:true", "circle:true", "circle:true", "path:true", "curved:true", "backed:true", "backed:true"]
    assert out["ops"] == [{"op": "text_add", "text": {}}, {"op": "text_set", "id": "t1", "changes": {"height_mm": 12}},
                          {"op": "text_set", "id": "t1", "changes": {"entry_id": "e12"}}, {"op": "text_set", "id": "t1", "changes": {"layout": "circle"}},
                          {"op": "text_copy", "id": "t1"}, {"op": "text_delete", "id": "t1"},
                          {"op": "text_set", "id": "t1", "changes": {"text": "HOH\nвторая"}}]
    assert "Надпись 2 не выгравировать: В её шрифте нет букв «Ж»: выберите шрифт, в котором они есть" in out["text"]
    assert "надписей 1" in out["text"]                                       # the layer that engraves it says so among the layers


@node
def test_dragging_on_the_picture_moves_turns_and_sizes_an_inscription_about_its_anchor_and_escape_leaves_it(tmp_path):
    # the stage is 100 × 100 px, the work 40 × 20 mm: 2.5 px a mm, the picture 25 px from the top
    out = run_editor(tmp_path, editor_routes(), OPEN + """
  const letters = () => drawnText('t1').querySelectorAll('path').find((p) => p.classList.contains('lt-letters'));
  await letters().dispatch('pointerdown', {clientX: 50, clientY: 50, button: 0});
  await stage.dispatch('pointermove', {clientX: 60, clientY: 55});
  out.moving = drawnText('t1').getAttribute('transform');
  await stage.dispatch('pointerup', {clientX: 60, clientY: 55});
  await stage.dispatch('click', {clientX: 60, clientY: 55}); await tick();     // the end of a drag is not a click
  out.kept = item(0).getAttribute('aria-pressed');
  await handle('rotate').dispatch('pointerdown', {clientX: 30, clientY: 9.5, button: 0});
  await stage.dispatch('pointermove', {clientX: 63, clientY: 42.5});
  await stage.dispatch('pointerup', {clientX: 63, clientY: 42.5}); await tick();
  await handle('size').dispatch('pointerdown', {clientX: 35, clientY: 47.5, button: 0});
  await stage.dispatch('pointermove', {clientX: 40, clientY: 52.5});
  await stage.dispatch('pointerup', {clientX: 40, clientY: 52.5}); await tick();
  await letters().dispatch('pointerdown', {clientX: 50, clientY: 50, button: 0});
  await stage.dispatch('pointerup', {clientX: 51, clientY: 50}); await tick();   // a press without a move changes nothing
  await ctx.document.dispatch('keydown', {key: 'Escape', code: 'Escape', target: tree}); await tick();
  out.left = item(0).getAttribute('aria-pressed');
  out.marks = svg().querySelectorAll('polygon').length;
  out.ops = textOps();
""")
    assert out["moving"] == "translate(4 2)" and out["kept"] == "true"
    assert out["ops"] == [{"op": "text_set", "id": "t1", "changes": {"x": 16, "y": 9}},
                          {"op": "text_set", "id": "t1", "changes": {"rotation": 90, "x": 12, "y": 7}},
                          {"op": "text_set", "id": "t1", "changes": {"height_mm": 8, "spacing_mm": 0, "x": 12, "y": 7}}]
    assert out["left"] == "false" and out["marks"] == 0


@node
def test_a_path_is_drawn_with_clicks_on_the_picture_its_first_point_the_place_and_the_others_relative_to_it(tmp_path):
    out = run_editor(tmp_path, editor_routes(), OPEN + """
  await item(1).dispatch('click'); await tick();
  out.points = svg().querySelectorAll('circle').filter((c) => c.getAttribute('data-handle') === 'point').map((c) => [+c.getAttribute('cx'), +c.getAttribute('cy')]);
  await byText(pane, 'button', 'Нарисовать путь заново').dispatch('click'); await tick();
  for (const [x, y] of [[25, 50], [50, 50], [75, 62.5]]) await stage.dispatch('click', {clientX: x, clientY: y});
  out.drawing = svg().querySelectorAll('polyline').find((p) => p.classList.contains('lt-drawn')).getAttribute('points');
  await byText(pane, 'button', 'Готово').dispatch('click'); await tick();
  await byText(pane, 'button', 'Нарисовать путь заново').dispatch('click'); await tick();
  await stage.dispatch('click', {clientX: 25, clientY: 50});
  await ctx.document.dispatch('keydown', {key: 'Escape', code: 'Escape', target: tree}); await tick();
  out.dropped = svg().querySelectorAll('polyline').filter((p) => p.classList.contains('lt-drawn')).length;
  out.ops = textOps();
""")
    assert out["points"] == [[5, 15], [15, 15]]                                # the path's points in the work's mm
    assert out["drawing"] == "10,10 20,10 30,15"
    assert out["ops"] == [{"op": "text_set", "id": "t2", "changes": {"layout": "path", "rotation": 0, "x": 10, "y": 10, "points": [[0, 0], [10, 0], [20, 5]]}}]
    assert out["dropped"] == 0                                                 # Escape drops a path being drawn


@node
def test_the_font_window_lists_filters_previews_downloads_and_chooses_a_face(tmp_path):
    out = run_editor(tmp_path, editor_routes(), OPEN + """
  await item(0).dispatch('click'); await tick();
  await byText(pane, 'button', 'Шрифт: Arial Regular…').dispatch('click'); await wait(5);
  const win = () => ctx.document.body.querySelector('.modal');
  const rows = () => win().querySelectorAll('div').filter((d) => d.classList.contains('lt-font')).map((d) => d.getAttribute('data-family'));
  const row = (family) => win().querySelectorAll('div').find((d) => d.classList.contains('lt-font') && d.getAttribute('data-family') === family);
  const choose = (label, value) => { const s = win().querySelectorAll('select').find((x) => x.getAttribute('aria-label') === label); s.value = value; return s.dispatch('change'); };
  out.all = rows();
  out.preview = row('Arial').querySelector('img').getAttribute('src');
  out.picked = row('Arial').getAttribute('aria-selected');
  out.count = win().querySelectorAll('p').find((p) => p.textContent.startsWith('Шрифтов:')).textContent;
  await choose('Письменность', 'hebrew');
  out.hebrew = rows();
  out.bulk = byText(win(), 'button', 'Скачать все Google: Иврит').disabled;
  await byText(row('Noto Sans Hebrew'), 'button', 'Скачать (0.3 МБ)').dispatch('click'); await wait(5);
  out.downloaded = row('Noto Sans Hebrew').querySelector('img').getAttribute('src');
  await choose('Письменность', '');
  await choose('Откуда шрифты', 'own');
  out.own = rows();
  out.remove = !!byText(row('My Hand'), 'button', 'Удалить');
  out.hand = row('My Hand').querySelector('img').getAttribute('src');
  await choose('Откуда шрифты', '');
  const search = win().querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Найти шрифт по названию');
  search.value = 'ari'; await search.dispatch('input');
  out.found = rows();
  search.value = ''; await search.dispatch('input');
  await choose('Начертание Arial', 'f2');
  await byText(win(), 'button', 'Выбрать').dispatch('click'); await tick();
  out.closed = !ctx.document.body.querySelector('.modal');
  out.google = ctx.requests.filter((r) => r.path === '/api/fonts/google/family').map((r) => JSON.parse(r.body));
  out.ops = textOps();
""")
    assert out["all"] == ["Arial", "My Hand", "Noto Sans Hebrew"] and out["picked"] == "true"
    assert out["preview"] == "/api/fonts/preview.svg?face=f1&text=HOH&height=10"          # the inscription's own text as the sample
    assert out["count"].startswith("Шрифтов: 3 из 3")
    assert out["hebrew"] == ["Noto Sans Hebrew"] and out["bulk"] is False
    assert out["google"] == [{"family": "Noto Sans Hebrew"}] and out["downloaded"] == "/api/fonts/preview.svg?face=g1&text=HOH&height=10"
    assert out["own"] == ["My Hand"] and out["remove"] and out["found"] == ["Arial"]
    assert out["hand"] == "/api/fonts/preview.svg?face=o1&text=HOH&height=10"              # a family opens on its regular face, not its thinnest
    assert out["closed"] and out["ops"] == [{"op": "text_set", "id": "t1", "changes": {"font": {"face": "f2", "family": "Arial", "style": "Bold"}}}]


# -- the photo work in node --------------------------------------------------------------------------------------------------------------
TEXTS_ROUTE = """
  if (path === `/api/photo-works/${work.id}/palette`) return answer(data.palette);
  if (path === `/api/photo-works/${work.id}/texts`) {
    remember();
    if (body.op === 'text_set') work = {...work, texts: work.texts.map((t) => (t.id === body.id ? {...t, ...body.changes} : t))};
    version++;
    return answer(view());
  }
"""
PHOTO_HARNESS = photo_ui.HARNESS
for old, new in (("  if (path === `/api/photo-works/${work.id}/undo`)", TEXTS_ROUTE + "  if (path === `/api/photo-works/${work.id}/undo`)"),
                 ("dpi: 1000, notes: [],", "dpi: 1000, notes: [], picture: {width: 240, height: 120, shown_width: 240, shown_height: 120},")):
    assert PHOTO_HARNESS.count(old) == 1, old
    PHOTO_HARNESS = PHOTO_HARNESS.replace(old, new)


def run_photo(tmp_path, body):
    work = {**photo_ui.WORK, "width_mm": 60, "height_mm": 30, "texts": [text("t1", x=30.0, y=15.0)], "text_defaults": lettering.DEFAULTS,
            "text_layers": [{"index": 2, "name": "C02 P10-F30-V500-I0.02", "entry_id": "e14", "area_mm2": 16.0, "srgb": [60, 70, 200], "texts": ["t1"]}],
            "export_blocked": None}
    data = {"scales": [photo_ui.scale(150, [1, 30])], "scale": photo_ui.scale_answer(), "work": work, "kinds": photo_ui.KINDS,
            "works": [photo_ui.listed(work)], "parts": photo_ui.PARTS, "ai_rules": photo_ui.AI_RULES, "engravings": [], "objects": photo_ui.OBJECTS,
            "themes": photo_ui.THEMES, "palette": PALETTE}
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(PHOTO_HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                       "ui": json.dumps(str(photo_ui.UI) + "/"), "tables": json.dumps(photo_ui.TABLES), "scripts": json.dumps(photo_ui.SCRIPTS),
                                       "glue": json.dumps(photo_ui.GLUE), "query": json.dumps({"work": "7"}), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


@node
def test_a_photo_work_lays_its_inscriptions_over_the_look_and_a_drag_there_moves_one(tmp_path):
    # the preview is 240 + 8 + 240 px: the look starts 62 mm into it (60 mm of picture, 2 mm of gap); 100 × 100 px shows 122 × 30 mm
    out = run_photo(tmp_path, """
  ctx.document.body.append(tree);
  const over = () => tree.querySelectorAll('svg').find((s) => (s.getAttribute('class') || '').startsWith('lt-over'));
  out.closed = over().getAttribute('class');
  out.viewBox = over().getAttribute('viewBox');
  out.inStage = over().parentNode.classList.contains('pp-stage');
  await tree.querySelectorAll('button').find((b) => b.getAttribute('id') === 'ge-tab-texts').dispatch('click'); await settle();
  out.open = over().getAttribute('class');
  const item = tree.querySelectorAll('button').find((b) => b.classList.contains('lt-item'));
  await item.dispatch('click'); await settle();
  out.layers = tree.querySelectorAll('div').filter((d) => d.classList.contains('vw-ed-item')).map((d) => d.textContent);
  const hit = over().querySelectorAll('path').find((p) => p.classList.contains('lt-hit'));
  out.drawnHere = over().querySelectorAll('path').map((p) => p.getAttribute('class'));
  await hit.dispatch('pointerdown', {clientX: 75, clientY: 50, button: 0});
  await over().dispatch('pointermove', {clientX: 85, clientY: 55});
  await over().dispatch('pointerup', {clientX: 85, clientY: 55}); await settle();
  out.sent = requests.filter((r) => r.path.endsWith('/texts')).map((r) => r.body);
  out.x = tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'x, мм').value;
  await press({key: 'z', code: 'KeyZ', ctrlKey: true}); await settle();
  out.undone = tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'x, мм').value;
""")
    s = 100 / 122
    assert out["closed"] == "lt-over" and out["open"] == "lt-over open" and out["inStage"]
    assert out["viewBox"] == "-62 0 122 30"
    assert out["drawnHere"] == ["lt-hit", "lt-outline"]               # the look draws the inscription: the layer only takes the pointer
    assert any(row.startswith("C02") and "надписей 1" in row for row in out["layers"])
    (sent,) = out["sent"]
    assert sent["op"] == "text_set" and sent["id"] == "t1"
    assert sent["changes"] == {"x": pytest.approx(30 + 10 / s, abs=2e-3), "y": pytest.approx(15 + 5 / s, abs=2e-3)}
    assert float(out["x"]) == pytest.approx(30 + 10 / s, abs=2e-3) and out["undone"] == "30"
