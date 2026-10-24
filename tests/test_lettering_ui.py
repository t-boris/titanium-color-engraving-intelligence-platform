"""Inscriptions on the screens (feature inscriptions-in-works, REQ-001..REQ-005): the «Надписи» tab of the vector editor and of a photo work,
the font window and the layer of inscriptions over the picture. Static checks of the shared module against the server's contract (its
fields, limits, choices, scripts and kinds), then the screens run in node over the small DOM of the other screen tests with inscriptions
shaped as the API sends them: each change of an inscription is one operation of its work, a drag on the picture moves, turns or sizes it
about its frame's anchor, a path is drawn with clicks, the font window lists, filters, previews and downloads fonts."""
import copy
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
from shapely.geometry import box

import test_photo_engraving_ui as photo_ui
from test_vector_editor_ui import PALETTE, node, routes, run_editor, view
from titanium_platform import fonts, lettering, prediction
from titanium_platform.api.app import UI_DIR

LETTERING = (UI_DIR / "screens" / "lettering.js").read_text(encoding="utf-8")
PHOTO = (UI_DIR / "screens" / "photo-engraving.js").read_text(encoding="utf-8")
EDITOR = (UI_DIR / "screens" / "vector-editor.js").read_text(encoding="utf-8")
SCRIPTS = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))

FRAME = {"anchor": [12.0, 7.0], "corners": [[10.0, 5.0], [14.0, 5.0], [14.0, 9.0], [10.0, 9.0]], "rotation": 0.0}
SHOWN = {"letters": "M10 5 L14 5 L14 9 L10 9 Z", "backing": "", "cut": "M9.7 4.7 L14.3 4.7 L14.3 9.3 L9.7 9.3 Z", "guide": None,
         "frame": FRAME, "missing": "", "clipped": False, "overflow": False, "crowded": [], "area_mm2": 16.0, "backing_mm2": 0.0, "empty": False}
FONT = {"face": "f1", "family": "Arial", "style": "Regular"}


def text(tid, **over) -> dict:
    """An inscription as ``lettering.shown_row`` sends it: its fields, how it is drawn, its colours and why it cannot be engraved."""
    return {**lettering.DEFAULTS, "id": tid, "text": "HOH", "font": FONT, "height_mm": 4.0, "x": 12.0, "y": 7.0, "entry_id": "e14",
            "shown": SHOWN, "srgb": [60, 70, 200], "backing_srgb": None, "problem": None, **over}


def test_the_shown_inscription_of_these_tests_has_the_keys_the_server_sends():
    geom = {"letters": box(10, 5, 14, 9), "backing": None, "cut": box(9.7, 4.7, 14.3, 9.3), "guide": None, "frame": FRAME, "missing": [],
            "clipped": False, "overflow": False, "crowded": []}
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
    assert "colourPart('Цвет букв', 'entry_id', false)" in LETTERING and "colourPart('Цвет подложки', 'backing_entry_id', true)" in LETTERING
    assert "pick: tools.pick ? (title, lab, entryId, onPick) => tools.pick(j, title, lab, entryId, onPick) : null" in EDITOR


def test_the_font_window_names_every_script_kind_and_source_of_the_catalogue():
    for group, keys in (("SCRIPTS", fonts.SCRIPTS), ("KINDS", fonts.KINDS), ("SOURCES", fonts.SOURCES)):
        body = re.search(rf"const {group} = \{{(.*?)\}};", LETTERING, re.S).group(1)
        assert set(re.findall(r"(\w+): '", body)) == set(keys), group
    assert "`/api/fonts/preview.svg?face=${encodeURIComponent(faceId)}&text=${encodeURIComponent(sampleText())}&height=10`" in LETTERING
    for call in ("get('/fonts')", "post('/fonts/google/family', {family})", "post('/fonts/google/index')", "get('/fonts/google/status')",
                 "post('/fonts/google/download', {script: script.value || null, kind: kind.value || null})", "form('/fonts/own', fd)",
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
  out.colour = group('Цвет букв').querySelectorAll('span').filter((x) => x.getAttribute('data-entry')).map((x) => x.getAttribute('data-entry'));
  out.backingButtons = group('Цвет подложки').querySelectorAll('button').map((b) => b.textContent || b.getAttribute('aria-label'));
  await byText(group('Цвет букв'), 'button', 'Выбрать…').dispatch('click'); await tick(); await tick();
  const dialog = ctx.document.body.querySelector('.modal');
  await dialog.querySelectorAll('button').find((b) => b.getAttribute('data-entry') === 'e12').dispatch('click');
  await byText(dialog, 'button', 'Применить').dispatch('click'); await tick(); await tick();
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
    assert out["colour"] == ["e14"]                                                                  # the colour chosen, then «Выбрать…»
    assert out["backingButtons"] == ["Чистый титан", "Выбрать…"]
    assert out["hidden"] == ["arc:true", "circle:true", "circle:true", "path:true", "curved:true", "backed:true", "backed:true"]
    assert out["ops"] == [{"op": "text_add", "text": {}}, {"op": "text_set", "id": "t1", "changes": {"height_mm": 12}},
                          {"op": "text_set", "id": "t1", "changes": {"entry_id": "e12"}}, {"op": "text_set", "id": "t1", "changes": {"layout": "circle"}},
                          {"op": "text_copy", "id": "t1"}, {"op": "text_delete", "id": "t1"},
                          {"op": "text_set", "id": "t1", "changes": {"text": "HOH\nвторая"}}]
    assert "Надпись 2 не выгравировать: В её шрифте нет букв «Ж»: выберите шрифт, в котором они есть" in out["text"]
    assert "надписей 1" in out["text"]                                       # the layer that engraves it says so among the layers


@node
def test_the_colours_of_an_inscription_are_chosen_in_the_editors_window_and_a_backing_may_stay_clean_titanium(tmp_path):
    out = run_editor(tmp_path, editor_routes(), OPEN + """
  await item(0).dispatch('click'); await tick(); await wait(5);
  const choose = async (label, entry) => {
    await byText(group(label), 'button', 'Выбрать…').dispatch('click'); await tick(); await tick();
    const dialog = ctx.document.body.querySelector('.modal');
    const swatch = (id) => dialog.querySelectorAll('button').find((b) => b.getAttribute('data-entry') === id);
    const seen = {text: dialog.textContent, letters: swatch('e14').getAttribute('title'), now: dialog.textContent.includes('Сейчас:')};
    await swatch(entry).dispatch('click');
    await byText(dialog, 'button', 'Применить').dispatch('click'); await tick(); await tick();
    return seen;
  };
  out.letters = await choose('Цвет букв', 'e13');
  out.backing = await choose('Цвет подложки', 'e11');
  await group('Цвет подложки').querySelectorAll('button').find((b) => b.getAttribute('aria-label') === 'Чистый титан').dispatch('click'); await tick();
  out.ops = textOps();
""")
    assert "Цвет букв надписи № 1 (ΔE — до цвета букв)" in out["letters"]["text"] and out["letters"]["now"] is True
    assert "Цвет подложки надписи № 1 (ΔE — до цвета букв)" in out["backing"]["text"] and out["backing"]["now"] is False   # clean titanium now
    assert "ΔE 0.00" in out["letters"]["letters"] and "ΔE 0.00" in out["backing"]["letters"]          # ΔE to the letters' colour (e14)
    assert "«Откуда» — из каких тестов и работ цвет известен" in out["letters"]["text"]                # the editor's window, as it is
    assert out["ops"] == [{"op": "text_set", "id": "t1", "changes": {"entry_id": "e13"}},
                          {"op": "text_set", "id": "t1", "changes": {"backing_entry_id": "e11"}},
                          {"op": "text_set", "id": "t1", "changes": {"backing_entry_id": None}}]


def answered(base: dict, **fields) -> dict:
    """The work as the server answers a change of t1: its fields changed and t1 laid out again (another outline, a guide on a curve)."""
    out = copy.deepcopy(base)
    shown = {**SHOWN, "letters": "M20 5 L30 5 L30 9 L20 9 Z", "cut": "M19.7 4.7 L30.3 4.7 L30.3 9.3 L19.7 9.3 Z",
             "backing": "M18 3 L32 3 L32 11 L18 11 Z", "guide": [[18.0, 9.0], [25.0, 7.0], [32.0, 9.0]], "area_mm2": 40.0, "backing_mm2": 72.0}
    out["texts"][0] = {**out["texts"][0], **fields, "backing_srgb": [205, 198, 182], "shown": shown}
    return out


@node
def test_every_field_of_the_panel_sends_its_change_and_the_picture_shows_the_answer_at_once(tmp_path):
    """inscriptions-in-works REQ-003 c2: the stretch, spacing, line spacing, rotation, place, the layout's parameters (bend, radius, start
    angle, inside, offset along the path, reversed path), the alignment, the letters on a curve, the gap and the backing (its shape and
    margin, its corners) each send their change as one operation of the work, and the picture draws the inscription as the server answers
    at once: its new outline, its backing and the curve it is laid on."""
    r = editor_routes()
    base = r["/api/vector/7"]["json"]
    base["texts"][0]["points"] = [[0.0, 0.0], [10.0, 0.0]]
    fields = {"backing": "rect", "backing_entry_id": "e11", "width_pct": 150.0}
    r["/api/vector/7/colouring"] = {"status": 200, "json": answered(base, layout="circle", **fields)}
    r["/x/arc"] = {"status": 200, "json": answered(base, layout="arc", **fields)}
    r["/x/path"] = {"status": 200, "json": answered(base, layout="path", **fields)}
    out = run_editor(tmp_path, r, OPEN + """
  await item(0).dispatch('click'); await tick(); await wait(5);
  const painted = () => drawnText('t1').childNodes.map((p) => [p.getAttribute('class'), p.getAttribute('d'), p.getAttribute('fill')]);
  const guide = () => (svg().querySelectorAll('polyline').find((p) => p.classList.contains('lt-guide')) || {getAttribute: () => null}).getAttribute('points');
  const settle = async () => { await tick(); await tick(); await tick(); };
  const set = async (label, value) => { const f = field(label); f.value = value; await f.dispatch('change'); await settle(); };
  const press = async (label, name) => { await byText(group(label), 'button', name).dispatch('click'); await settle(); };
  const tick_ = async (label) => { const f = field(label); f.checked = true; await f.dispatch('change'); await settle(); };
  const visible = () => tree.querySelectorAll('div').filter((d) => d.getAttribute('data-for') && !d.hidden).map((d) => d.getAttribute('data-for'));
  out.before = [painted(), guide(), visible()];
  await set('Ширина, %', '150');
  out.after = [painted(), guide(), visible(), field('Ширина, %').value];
  for (const [label, value] of [['Интервал между буквами, мм', '0.5'], ['Между строками, %', '120'], ['Поворот, °', '30'], ['x, мм', '20'],
    ['y, мм', '10'], ['Радиус круга, мм', '15'], ['Где на круге, °', '90'], ['Зазор вокруг букв, мм', '0.5'], ['Поле подложки, мм', '2'],
    ['Скругление углов, мм', '1']]) await set(label, value);
  await tick_('Внутри круга (читается против часовой)');
  await press('Выравнивание', 'Справа');
  await press('Буквы на кривой', 'Гнутся по кривой');
  await press('Подложка', 'Овал');
  data.routes['/api/vector/7/colouring'] = data.routes['/x/arc'];
  await press('Расположение', 'Дугой');
  out.arc = visible();
  await set('Изгиб, %', '-30');
  data.routes['/api/vector/7/colouring'] = data.routes['/x/path'];
  await press('Расположение', 'По пути');
  out.path = visible();
  await set('Место на пути, %', '25');
  await tick_('Путь в обратную сторону');
  out.ops = textOps();
""")
    assert out["before"] == [[["lt-cut", SHOWN["cut"], "#e6e6e6"], ["lt-letters", SHOWN["letters"], "rgb(60,70,200)"],
                              ["lt-outline", SHOWN["letters"], "none"]], None, []]
    shown = answered(view() | {"texts": [text("t1")]})["texts"][0]["shown"]
    assert out["after"] == [[["lt-cut", shown["cut"], "#e6e6e6"], ["lt-backing", shown["backing"], "rgb(205,198,182)"],
                             ["lt-letters", shown["letters"], "rgb(60,70,200)"], ["lt-outline", shown["letters"], "none"]],   # as answered
                            "18,9 25,7 32,9", ["circle", "circle", "curved", "backed", "backed"], "150"]
    assert out["arc"] == ["arc", "curved", "backed", "backed"] and out["path"] == ["path", "curved", "backed", "backed"]
    change = lambda **c: {"op": "text_set", "id": "t1", "changes": c}          # noqa: E731
    assert out["ops"] == [change(width_pct=150), change(spacing_mm=0.5), change(line_pct=120), change(rotation=30), change(x=20), change(y=10),
                          change(radius_mm=15), change(start_deg=90), change(gap_mm=0.5), change(padding_mm=2), change(corner_mm=1),
                          change(inside=True), change(align="right"), change(letters="bent"), change(backing="oval"),
                          change(layout="arc"), change(bend=-30), change(layout="path"), change(offset_pct=25), change(flip=True)]


@node
def test_the_operator_reads_why_an_inscription_blocks_the_file_and_that_one_beyond_the_edge_is_cut_there(tmp_path):
    """inscriptions-in-works REQ-004 c5: the message that blocks the file names the inscription and why (its font is gone, its colour no
    longer measured), in Russian, beside the export and in the tab; the chosen inscription says so too, and one that runs off the work is
    said to be cut off at its edge."""
    gone = "the font 'Gone Sans' is not on this computer any more: choose another font"
    unmeasured = "its titanium colour is no longer measured on this laser, lens and titanium stock: choose another"
    r = editor_routes()
    j = r["/api/vector/7"]["json"]
    j["texts"] = [text("t1", problem=gone, shown={**SHOWN, "clipped": True}), text("t2", problem=unmeasured, srgb=None)]
    j["export_blocked"] = f"inscription 1 cannot be engraved: {gone}"
    out = run_editor(tmp_path, r, OPEN + """
  const alerts = () => pane.querySelectorAll('p').filter((p) => p.classList.contains('alert')).map((p) => [p.className, p.textContent]);
  out.list = alerts();
  out.pills = [0, 1].map((n) => item(n).querySelectorAll('span').filter((s) => s.classList.contains('pill')).map((s) => s.textContent));
  await item(0).dispatch('click'); await tick();
  out.first = alerts();
  await item(1).dispatch('click'); await tick();
  out.second = alerts();
""")
    blocked = "Надпись 1 не выгравировать: Шрифта 'Gone Sans' больше нет на этом компьютере: выберите другой шрифт"
    assert out["list"] == [["alert warn small", blocked]]
    assert out["text"].count(blocked) == 2                                          # in the tab and beside the export
    assert out["pills"] == [["не выгравировать"], ["не выгравировать"]]                  # each one in the list
    assert out["first"] == [["alert warn small", blocked], ["alert bad", "Шрифта 'Gone Sans' больше нет на этом компьютере: выберите другой шрифт"],
                            ["alert warn", "Часть надписи выходит за край работы: там она обрезана."]]
    assert out["second"] == [["alert warn small", blocked],
                             ["alert bad", "Её цвет титана больше не измерен на этом лазере, линзе и партии титана: выберите другой"]]


@node
def test_a_new_inscription_takes_the_font_of_the_one_chosen_or_changed_last(tmp_path):
    routes_ = editor_routes()
    routes_["/api/vector/7"]["json"]["texts"][1]["font"] = HEBREW = {"face": "g1", "family": "Noto Sans Hebrew", "style": "Regular"}
    out = run_editor(tmp_path, routes_, OPEN + """
  const added = () => textOps().filter((op) => op.op === 'text_add').map((op) => op.text);
  const add = async () => { await byText(pane, 'button', 'Добавить надпись').dispatch('click'); await tick(); };
  const escape = async () => { await ctx.document.dispatch('keydown', {key: 'Escape', code: 'Escape', target: tree}); await tick(); };
  await add();                                                      // none chosen yet: the server takes the work's last font
  await escape();                                                   // (the answer here is the same work: the last one in it is chosen)
  await item(0).dispatch('click'); await tick();
  await escape();                                                   // left, but chosen last
  await add();                                                      // then the harness's answer chooses its last inscription, t2
  await escape();
  await add();
  out.added = added();
""")
    assert out["added"] == [{}, {"font": FONT}, {"font": HEBREW}]


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
def test_a_path_ends_with_enter_or_a_double_click_and_is_drawn_freehand_by_a_drag(tmp_path):
    # the stage is 100 × 100 px, the work 40 × 20 mm: 2.5 px a mm, the picture 25 px from the top
    out = run_editor(tmp_path, editor_routes(), OPEN + """
  await item(1).dispatch('click'); await tick();
  const again = () => byText(pane, 'button', 'Нарисовать путь заново');
  const line = () => svg().querySelectorAll('polyline').find((p) => p.classList.contains('lt-drawn'));
  await again().dispatch('click'); await tick();
  for (const [x, y] of [[25, 50], [50, 50]]) await stage.dispatch('click', {clientX: x, clientY: y, detail: 1});
  await ctx.document.dispatch('keydown', {key: 'Enter', code: 'Enter'}); await tick();
  out.afterEnter = textOps().length;
  await ctx.document.dispatch('keydown', {key: 'Enter', code: 'Enter'}); await tick();      // the drawing is over: Enter does nothing more
  out.afterSecondEnter = textOps().length;
  await again().dispatch('click'); await tick();
  await stage.dispatch('click', {clientX: 25, clientY: 50, detail: 1});
  await stage.dispatch('click', {clientX: 75, clientY: 62.5, detail: 1});
  await stage.dispatch('click', {clientX: 75, clientY: 62.5, detail: 2}); await tick();     // the second click of a double click ends it
  await again().dispatch('click'); await tick();
  await stage.dispatch('pointerdown', {clientX: 25, clientY: 50, button: 0});                // freehand: press, drag an L with a tremor, release
  for (let x = 26; x <= 50; x += 1) await stage.dispatch('pointermove', {clientX: x, clientY: 50 + (x % 2) * 0.2});
  for (let y = 51; y <= 75; y += 1) await stage.dispatch('pointermove', {clientX: 50, clientY: y});
  out.stroke = line().getAttribute('points').split(' ').length;
  await stage.dispatch('pointerup', {clientX: 50, clientY: 75});
  await stage.dispatch('click', {clientX: 50, clientY: 75, detail: 1});                     // the end of the drag is not a point
  out.simplified = line().getAttribute('points');
  await stage.dispatch('click', {clientX: 75, clientY: 75, detail: 1});                     // clicks go on adding points
  await ctx.document.dispatch('keydown', {key: 'Enter', code: 'Enter'}); await tick();
  await again().dispatch('click'); await tick();
  await stage.dispatch('click', {clientX: 25, clientY: 50, detail: 1});
  const ta = pane.querySelectorAll('textarea')[0];
  await ctx.document.dispatch('keydown', {key: 'Enter', code: 'Enter', target: ta}); await tick();   // Enter in the text is a new line
  out.stillDrawing = !!line();
  await ctx.document.dispatch('keydown', {key: 'Escape', code: 'Escape', target: tree}); await tick();
  out.ops = textOps();
""")
    path = lambda pts: {"op": "text_set", "id": "t2", "changes": {"layout": "path", "rotation": 0, "x": 10, "y": 10, "points": pts}}   # noqa: E731
    assert out["afterEnter"] == 1 and out["afterSecondEnter"] == 1
    assert out["stroke"] > 40 and out["simplified"] == "10,10 20,10 20,20"                    # the tremor (0.08 mm) is gone, the corner kept
    assert out["stillDrawing"] is True
    assert out["ops"] == [path([[0, 0], [10, 0]]), path([[0, 0], [20, 5]]), path([[0, 0], [10, 0], [10, 10], [20, 10]])]


def test_a_freehand_path_is_simplified_within_the_servers_limit_of_points():
    assert re.search(r"const MAX_POINTS = (\d+);", LETTERING).group(1) == str(lettering.MAX_POINTS)
    assert "ev.detail >= 2" in LETTERING and "document.addEventListener('keydown', pathKey)" in LETTERING
    assert "document.removeEventListener('keydown', pathKey)" in LETTERING


@node
def test_letters_crowding_on_a_bend_of_a_path_are_warned_about_by_their_line(tmp_path):
    r = editor_routes()
    r["/api/vector/7"]["json"]["texts"][1]["shown"] = {**SHOWN, "crowded": [1, 2]}
    out = run_editor(tmp_path, r, OPEN + """
  await item(1).dispatch('click'); await tick();
  out.alerts = pane.querySelectorAll('p').filter((p) => p.classList.contains('alert')).map((p) => p.textContent);
""")
    assert any("строки 1, 2" in a and "изгиб" in a for a in out["alerts"]), out["alerts"]


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


FONT_WINDOW = """
  await item(0).dispatch('click'); await tick();
  const openFonts = async () => { await byText(pane, 'button', 'Шрифт: Arial Regular…').dispatch('click'); await wait(5); };
  const win = () => ctx.document.body.querySelector('.modal');
  const rows = () => win().querySelectorAll('div').filter((d) => d.classList.contains('lt-font')).map((d) => d.getAttribute('data-family'));
  const row = (family) => win().querySelectorAll('div').find((d) => d.classList.contains('lt-font') && d.getAttribute('data-family') === family);
  const choose = (label, value) => { const s = win().querySelectorAll('select').find((x) => x.getAttribute('aria-label') === label); s.value = value; return s.dispatch('change'); };
  const asked = () => ctx.requests.filter((r) => r.path === '/api/fonts/google/family').map((r) => JSON.parse(r.body).family);
"""
BIG = {"family": "Big Serif", "source": "google", "kind": "serif", "scripts": ["latin"], "downloaded": False, "popularity": 300, "faces": [],
       "size": 5 * 1024 * 1024}


@node
def test_a_google_family_seen_in_the_list_is_downloaded_by_itself_and_a_large_one_waits_for_its_button(tmp_path):
    """inscriptions-in-works REQ-001 c2: a Google family not downloaded yet is downloaded when its row comes into view (up to 2 MB; a
    larger one by its button), and then shows the text in its font."""
    r = editor_routes()
    r["/api/fonts"]["json"] = {**FONTS, "families": FONTS["families"] + [BIG]}
    out = run_editor(tmp_path, r, OPEN + FONT_WINDOW + """
  const watched = [];                         // the rows the window waits to see (a browser tells it when they scroll into view)
  ctx.IntersectionObserver = class { constructor(seen) { this.seen = seen; ctx.__observer = this; } observe(el) { watched.push(el); } unobserve() {} disconnect() {} };
  await openFonts();
  out.watched = watched.map((el) => el.getAttribute('data-family'));
  out.before = asked();
  await ctx.__observer.seen(watched.map((el) => ({isIntersecting: true, target: el}))); await wait(10);
  out.after = asked();
  out.noto = row('Noto Sans Hebrew').querySelector('img').getAttribute('src');
  out.big = row('Big Serif').querySelectorAll('button').map((b) => b.textContent).filter((t) => t.startsWith('Скачать'));
""")
    assert out["watched"] == ["Noto Sans Hebrew", "Big Serif"]                    # the families without their files
    assert out["before"] == []                                                     # nothing is downloaded before it is seen
    assert out["after"] == ["Noto Sans Hebrew"]                                    # seen: the small one downloaded at once
    assert out["noto"] == "/api/fonts/preview.svg?face=g1&text=HOH&height=10"      # and drawn in its regular face
    assert out["big"] == ["Скачать (5.0 МБ)"]                                      # the large one waits for its button


@node
def test_a_google_family_chosen_before_it_is_downloaded_is_downloaded_and_chosen(tmp_path):
    """inscriptions-in-works REQ-001 c2: «downloaded when it is chosen»: a click on the row of a family not downloaded yet, even one too large
    to come by itself, downloads it and chooses it once it is here; «Выбрать» gives the inscription that font."""
    r = editor_routes()
    r["/api/fonts"]["json"] = {**FONTS, "families": FONTS["families"] + [BIG]}
    r["/api/fonts/google/family"]["json"] = {"faces": [{"face": "b0", "family": "Big Serif", "style": "Regular"},
                                                       {"face": "b1", "family": "Big Serif", "style": "Bold"}]}
    out = run_editor(tmp_path, r, OPEN + FONT_WINDOW + """
  await openFonts();
  out.before = [asked(), row('Big Serif').getAttribute('aria-selected')];
  await row('Big Serif').dispatch('click'); await wait(10);
  out.after = [asked(), row('Big Serif').getAttribute('aria-selected'), row('Arial').getAttribute('aria-selected')];
  out.drawn = row('Big Serif').querySelector('img').getAttribute('src');
  await row('Big Serif').dispatch('click'); await wait(10);
  out.again = asked();                                    // a family already here is only chosen
  await byText(win(), 'button', 'Выбрать').dispatch('click'); await tick();
  out.ops = textOps();
""")
    assert out["before"] == [[], "false"]
    assert out["after"] == [["Big Serif"], "true", "false"]                       # downloaded and chosen in place of Arial
    assert out["drawn"] == "/api/fonts/preview.svg?face=b0&text=HOH&height=10"
    assert out["again"] == ["Big Serif"]
    assert out["ops"] == [{"op": "text_set", "id": "t1", "changes": {"font": {"face": "b0", "family": "Big Serif", "style": "Regular"}}}]


@node
def test_a_bulk_download_of_a_script_and_a_kind_shows_its_progress_until_it_ends(tmp_path):
    """inscriptions-in-works REQ-001 c2: every Google family of a script, narrowed to a category, is downloaded in the background; the
    window shows how many are done until it ends and then lists them downloaded."""
    status = lambda done, running=True, failed=(): {"running": running, "done": done, "total": 3, "failed": list(failed),   # noqa: E731
                                                    "current": "Noto Sans Hebrew" if running else None, "error": None}
    r = editor_routes()
    r["/api/fonts/google/download"] = {"status": 200, "json": status(0)}
    r["/api/fonts/google/status"] = {"status": 200, "json": status(1)}
    r["/x/fonts-after"] = {"status": 200, "json": {**FONTS, "google": {**FONTS["google"], "downloaded": 2, "download": status(3, False, ["Gamma"])}}}
    r["/x/status-after"] = {"status": 200, "json": status(3, False, ["Gamma"])}
    out = run_editor(tmp_path, r, OPEN + FONT_WINDOW + """
  const every = ctx.setInterval;
  ctx.setInterval = (fn, ms) => every(fn, ms === 1000 ? 15 : ms);        // the window asks for the progress every second: here sooner
  const polls = () => ctx.requests.filter((x) => x.path === '/api/fonts/google/status').length;
  await openFonts();
  await choose('Письменность', 'hebrew'); await choose('Вид шрифта', 'sans');
  const bulk = () => win().querySelectorAll('button').find((b) => b.textContent.startsWith('Скачать все Google'));
  out.label = bulk().textContent;
  await bulk().dispatch('click'); await tick();
  out.started = [win().textContent.includes('скачано 0 из 3…'), bulk().disabled];
  out.sent = ctx.requests.filter((x) => x.path === '/api/fonts/google/download').map((x) => JSON.parse(x.body));
  await wait(60);
  out.running = [win().textContent.includes('скачано 1 из 3…'), bulk().disabled];
  data.routes['/api/fonts/google/status'] = data.routes['/x/status-after'];
  data.routes['/api/fonts'] = data.routes['/x/fonts-after'];
  await wait(60);
  out.ended = [win().textContent.includes('скачано 3 из 3, не скачались: 1'), bulk().disabled];
  const before = polls();
  await wait(60);
  out.stopped = polls() === before;                                        // no more asking once it ended
  ctx.setInterval = every;
""")
    assert out["label"] == "Скачать все Google: Иврит, без засечек"
    assert out["sent"] == [{"script": "hebrew", "kind": "sans"}]
    assert out["started"] == [True, True] and out["running"] == [True, True]            # its progress shown, no second one meanwhile
    assert out["ended"] == [True, False] and out["stopped"] is True


@node
def test_a_bulk_download_by_a_category_alone_is_offered_in_the_font_window(tmp_path):
    """inscriptions-in-works REQ-001 c2: a bulk download by category, with any script; with neither chosen there is nothing to download."""
    out = run_editor(tmp_path, editor_routes(), OPEN + FONT_WINDOW + """
  await openFonts();
  const bulk = () => win().querySelectorAll('button').find((b) => b.textContent.startsWith('Скачать все Google'));
  await choose('Письменность', ''); await choose('Вид шрифта', '');
  out.none = [bulk().textContent, bulk().disabled];
  await choose('Вид шрифта', 'handwriting');
  out.label = bulk().textContent;
  out.disabled = bulk().disabled;
  await bulk().dispatch('click'); await tick();
  out.sent = ctx.requests.filter((x) => x.path === '/api/fonts/google/download').map((x) => JSON.parse(x.body));
""")
    assert out["none"] == ["Скачать все Google выбранной письменности или вида", True]
    assert out["label"] == "Скачать все Google: рукописные" and out["disabled"] is False
    assert out["sent"] == [{"script": None, "kind": "handwriting"}]


@node
def test_the_kind_filter_narrows_the_list_and_favourites_stay_marked_when_the_window_opens_again(tmp_path):
    """inscriptions-in-works REQ-001 c3: the filter by kind (serif, sans serif, handwriting ...) and the favourites, which this browser
    keeps: a star marks a family, «Избранные» lists the marked ones, and the next window shows them marked still."""
    out = run_editor(tmp_path, editor_routes(), OPEN + FONT_WINDOW + """
  const kept = new Map();                     // the browser's storage of this screen
  ctx.localStorage = {getItem: (k) => (kept.has(k) ? kept.get(k) : null), setItem: (k, v) => { kept.set(k, String(v)); }};
  const star = (family) => row(family).querySelectorAll('button').find((b) => b.classList.contains('lt-star'));
  await openFonts();
  const offered = (label) => win().querySelectorAll('select').find((x) => x.getAttribute('aria-label') === label).querySelectorAll('option')
    .map((o) => [o.value, o.textContent]);
  out.offered = {scripts: offered('Письменность'), kinds: offered('Вид шрифта')};
  out.kinds = {};
  for (const kind of ['handwriting', 'sans', 'serif', '']) { await choose('Вид шрифта', kind); out.kinds[kind || 'any'] = rows(); }
  await star('My Hand').dispatch('click');
  out.marked = ['My Hand', 'Arial'].map((f) => [star(f).getAttribute('aria-pressed'), star(f).textContent]);
  out.kept = kept.get('lt.fav');
  await choose('Откуда шрифты', 'fav');
  out.favourites = rows();
  await byText(win(), 'button', 'Отмена').dispatch('click'); await tick();
  out.closed = !win();
  await openFonts();
  out.again = ['My Hand', 'Arial'].map((f) => star(f).getAttribute('aria-pressed'));
  await star('My Hand').dispatch('click');
  out.unmarked = [star('My Hand').getAttribute('aria-pressed'), kept.get('lt.fav')];
""")
    scripts = dict(out["offered"]["scripts"])
    assert list(scripts)[1:] == list(fonts.SCRIPTS)                                 # every script the catalogue tells apart
    assert {k: scripts[k] for k in ("latin", "cyrillic", "hebrew", "arabic", "greek")} == {
        "latin": "Латиница", "cyrillic": "Кириллица", "hebrew": "Иврит", "arabic": "Арабский", "greek": "Греческий"}
    assert [k for k, _ in out["offered"]["kinds"]][1:] == list(fonts.KINDS)
    assert dict(out["offered"]["kinds"])["serif"] == "С засечками" and dict(out["offered"]["kinds"])["monospace"] == "Моноширинные"
    assert out["kinds"] == {"handwriting": ["My Hand"], "sans": ["Arial", "Noto Sans Hebrew"], "serif": [],
                            "any": ["Arial", "My Hand", "Noto Sans Hebrew"]}
    assert out["marked"] == [["true", "★"], ["false", "☆"]] and json.loads(out["kept"]) == ["My Hand"]
    assert out["favourites"] == ["My Hand"]
    assert out["closed"] and out["again"] == ["true", "false"]                     # still marked in the next window
    assert out["unmarked"] == ["false", "[]"]


@node
def test_an_inscription_without_text_shows_the_sample_in_every_font(tmp_path):
    """inscriptions-in-works REQ-001 c4: while the inscription's text is empty, each font draws the sample (the server's own sample)."""
    r = editor_routes()
    r["/api/vector/7"]["json"]["texts"][0]["text"] = ""
    out = run_editor(tmp_path, r, OPEN + FONT_WINDOW + """
  await openFonts();
  out.sample = win().querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Образец текста').value;
  out.previews = ['Arial', 'My Hand'].map((f) => row(f).querySelector('img').getAttribute('src'));
""")
    assert re.search(r"const SAMPLE = '([^']+)';", LETTERING).group(1) == lettering.SAMPLE == out["sample"]
    sample = quote(lettering.SAMPLE, safe="-_.!~*'()")                                # as encodeURIComponent writes it
    assert out["previews"] == [f"/api/fonts/preview.svg?face=f1&text={sample}&height=10", f"/api/fonts/preview.svg?face=o1&text={sample}&height=10"]


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


@node
def test_a_path_on_a_photo_work_is_drawn_freehand_and_ends_with_enter(tmp_path):
    # 100 × 100 px shows 122 × 30 mm of the preview: 100/122 px a mm, the strip 37.7 px from the top; a V drawn by a drag
    out = run_photo(tmp_path, """
  ctx.document.body.append(tree);
  const over = () => tree.querySelectorAll('svg').find((s) => (s.getAttribute('class') || '').startsWith('lt-over'));
  await tree.querySelectorAll('button').find((b) => b.getAttribute('id') === 'ge-tab-texts').dispatch('click'); await settle();
  await tree.querySelectorAll('button').find((b) => b.classList.contains('lt-item')).dispatch('click'); await settle();
  await tree.querySelectorAll('button').find((b) => b.textContent === 'Нарисовать путь').dispatch('click'); await settle();
  await over().dispatch('pointerdown', {clientX: 70, clientY: 45, button: 0});
  for (let i = 1; i <= 20; i++) await over().dispatch('pointermove', {clientX: 70 + i, clientY: 45 + (i <= 10 ? i : 20 - i)});
  await over().dispatch('pointerup', {clientX: 90, clientY: 45});
  await over().dispatch('click', {clientX: 90, clientY: 45, detail: 1}); await settle();     // the end of the stroke is not a point
  await press({key: 'Enter', code: 'Enter'}); await settle();
  out.sent = requests.filter((r) => r.path.endsWith('/texts')).map((r) => r.body);
""")
    s = 100 / 122
    (sent,) = out["sent"]
    assert sent["op"] == "text_set" and sent["changes"]["layout"] == "path"
    assert sent["changes"]["points"] == [[0, 0], [pytest.approx(10 / s, abs=2e-3), pytest.approx(10 / s, abs=2e-3)], [pytest.approx(20 / s, abs=2e-3), 0]]


@node
def test_typing_makes_one_step_of_undo_per_pause_and_ctrl_shift_z_redoes_it(tmp_path):
    out = run_photo(tmp_path, """
  ctx.document.body.append(tree);
  await tree.querySelectorAll('button').find((b) => b.getAttribute('id') === 'ge-tab-texts').dispatch('click'); await settle();
  await tree.querySelectorAll('button').find((b) => b.classList.contains('lt-item')).dispatch('click'); await settle();
  const ta = () => tree.querySelectorAll('textarea').find((t) => t.classList.contains('lt-text'));
  const sent = () => requests.filter((r) => r.path.endsWith('/texts')).map((r) => r.body.changes.text);
  const type = async (text) => { for (let n = 4; n <= text.length; n++) { ta().value = text.slice(0, n); await ta().dispatch('input'); await wait(60); } };
  await type('HOH 2026');                                           // a letter every 60 ms: one pause at the end
  out.whileTyping = sent();
  await wait(800); await settle();
  out.afterPause = sent();
  await type('HOH 2026!');
  await wait(800); await settle();
  out.typed = [sent(), ta().value];
  await press({key: 'z', code: 'KeyZ', ctrlKey: true}); await settle();
  out.undone = [ta().value, requests.filter((r) => r.path.endsWith('/undo')).length];
  await press({key: 'z', code: 'KeyZ', ctrlKey: true, shiftKey: true}); await settle();
  out.redone = [ta().value, requests.filter((r) => r.path.endsWith('/redo')).length];
""")
    assert out["whileTyping"] == []
    assert out["afterPause"] == ["HOH 2026"]                                       # five letters typed, one change
    assert out["typed"] == [["HOH 2026", "HOH 2026!"], "HOH 2026!"]
    assert out["undone"] == ["HOH 2026", 1] and out["redone"] == ["HOH 2026!", 1]   # one step back is the last pause's typing


@node
def test_a_photo_works_inscription_takes_its_colours_in_the_editors_window_over_the_works_own_palette(tmp_path):
    # the photo work passes the editor's window (vector-colours.js, pickFrom) over its own measured colours (/photo-works/{id}/palette)
    out = run_photo(tmp_path, """
  ctx.document.body.append(tree);
  await tree.querySelectorAll('button').find((b) => b.getAttribute('id') === 'ge-tab-texts').dispatch('click'); await settle();
  await tree.querySelectorAll('button').find((b) => b.classList.contains('lt-item')).dispatch('click'); await settle();
  const group = (label) => tree.querySelectorAll('div').find((d) => d.getAttribute('aria-label') === label);
  out.letters = group('Цвет букв').querySelectorAll('button').map((b) => b.textContent);
  await group('Цвет букв').querySelectorAll('button').find((b) => b.textContent === 'Выбрать…').dispatch('click'); await settle();
  const dialog = ctx.document.body.querySelector('.modal');
  out.text = dialog.textContent;
  out.swatches = dialog.querySelectorAll('button').map((b) => b.getAttribute('data-entry')).filter(Boolean);
  await dialog.querySelectorAll('button').find((b) => b.getAttribute('data-entry') === 'e13').dispatch('click');
  await dialog.querySelectorAll('button').find((b) => b.textContent === 'Применить').dispatch('click'); await settle();
  out.ops = requests.filter((r) => r.path.endsWith('/texts')).map((r) => r.body);
""")
    assert out["letters"] == ["Выбрать…"]                                                  # no squares to click in the tab any more
    assert "Цвет букв надписи № 1 (ΔE — до цвета букв)" in out["text"] and "«Откуда» — из каких тестов и работ цвет известен" in out["text"]
    assert sorted(set(out["swatches"])) == sorted(e["id"] for e in PALETTE)
    assert out["ops"] == [{"op": "text_set", "id": "t1", "changes": {"entry_id": "e13"}}]
