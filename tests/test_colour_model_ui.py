"""The colour model of one laser and lens and the knowledge page of one colour on one screen (REQ-044, DEC-080): the sets on the left, the
map of the selected set with its cautions in the middle, its tables in tabs on the right, the remembered choice, the empty states; the
knowledge page as two columns. The model and the RAW «Все слои» are short lists (REQ-005, DEC-090): one line each, a page of 20, search,
filters and sorts, the figures under a line on a click. Run in node over the small DOM of the other screen tests, with answers shaped like
the server's."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
CSS = (UI / "styles.css").read_text(encoding="utf-8")
COLOURS = (UI / "screens" / "colors.js").read_text(encoding="utf-8")
KNOWLEDGE = (UI / "screens" / "knowledge.js").read_text(encoding="utf-8")
GLUE = ("const __screens = {}, __renders = []; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { __renders.push(1); };"
        "globalThis.__screens = __screens; globalThis.__renders = __renders; const __store = {}; globalThis.__store = __store; globalThis.__broken = false;"
        "globalThis.localStorage = {getItem: (k) => { if (globalThis.__broken) throw new Error('no storage'); return k in __store ? __store[k] : null; },"
        "setItem: (k, v) => { if (globalThis.__broken) throw new Error('no storage'); __store[k] = String(v); }};")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
for (const name of ['createElement', 'createElementNS']) {              // the map and the swatches read and write element.style
  const make = ctx.document[name];
  ctx.document[name] = (...args) => { const el = make(...args); el.style = {}; return el; };
}
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', 'tasks.js', {code: %(glue)s}, 'screens/knowledge.js', 'screens/colors.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const has = (el, cls) => (el.className || '').split(' ').includes(cls);
const tabsOf = (root) => root.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'tab');
const shownPanels = (root) => root.querySelectorAll('div').filter((d) => d.getAttribute('role') === 'tabpanel' && !d.hidden).map((d) => d.getAttribute('id'));
(async () => {
  const out = {};
  const screen = async (ctxArg) => { const t = await ctx.__screens.colors.render({id: 'colors', query: {}, ...ctxArg}); await tick(); await tick(); return t; };
  const tree = await screen(data.arg);
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, routes, arg, body):
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes}), encoding="utf-8")
    script = tmp_path / "screen.js"
    text = HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                      "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}
    script.write_text(text.replace("data.arg", json.dumps(arg)), encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


# -- answers shaped like the server's -----------------------------------------------------------------------------------------------
def params(power=40.0, frequency=330.0, speed=833.0) -> dict:
    return {"power": power, "frequency": frequency, "speed": speed, "pulse_width": 4, "line_interval": 0.003, "passes": 1}


def layer(name, lab, role="test patch", **extra) -> dict:
    return {"name": name, "lab": lab, "role": role, "parameters": params(), "pixels": 1200, "delta_e_from_clean_witness": 7.5, "submeasurements": [],
            "notes": [], "relative_appearance": "тёмный на этом фото", **extra}


def pair(pair_id, provisional=False, layers=2, variants=1, findings=1, **extra) -> dict:
    samples = [layer(f"C0{i}", [20.0 + i, 1.0, -2.0 * i]) for i in range(layers)]
    if samples:
        samples[0]["submeasurements"] = [{"name": "sub1", "measured_lab": [30.0, 2.0, 3.0], "delta_e_from_clean_witness": 3.1, "pixels": 55}]
        samples[0]["notes"] = ["a note of the layer"]
    return {"pair_id": pair_id, "photo_name": f"IMG_{pair_id}.DNG", "lightburn_name": f"work{pair_id}.lbrn2", "provisional": provisional, "status": "Ready to accept",
            "masks_reviewed": False, "material": {"name": "Plate", "grade": "Grade 5", "batch": "B7"}, "warnings": ["a warning of the pair"], "samples": samples,
            "findings": [{"label": f"Finding {i}", "name": f"C0{i}", "lab": [10.0 + i, 0.5, 1.5], "parameters": params(), "delta_e": 4.2} for i in range(findings)],
            "color_variants": [{"name": f"V{i}", "lab": [50.0, 3.0, 9.0], "parameters": params(), "delta_e_from_clean_witness": 12.3, "settings_complete": i % 2 == 0}
                               for i in range(variants)], **extra}


def known(k, stage="measured", questioned=False) -> dict:
    return {"id": k, "stage": stage, "questioned": questioned, "parameters": params(30.0 + k, 300.0, 1000.0),
            "summary": {"lab": [40.0 + k, 2.0, -3.0], "independent_engravings": k, "available": k % 2 == 0, "confidence": 0.5, "expected_delta_e": 3.25,
                        "stability": {"assessed": True, "variance": 1.5}}}


def routes_for(samples=3, pairs=(), unstable=(), knowledge=4, lens=2) -> dict:
    model = {"samples": [{"lab": [30.0 + i, 5.0 * i, 4.0 - i], "engravings": 1 + i, "available": i % 2 == 0} for i in range(samples)],
             "camera_relative_sets": list(pairs), "unstable": [{"parameters": params(*u)} for u in unstable], "targets": [], "rules": {}}
    return {"/api/devices": {"status": 200, "json": [{"id": 1, "name": "Laser A", "title": "Laser A", "lens": {"id": lens, "name": "F-Theta", "focal_length_mm": 174}}]},
            "/api/lenses": {"status": 200, "json": [{"id": lens, "name": "F-Theta", "focal_length_mm": 174}]},
            "/api/color-model": {"status": 200, "json": model},
            "/api/knowledge": {"status": 200, "json": [known(k) for k in range(1, knowledge + 1)]}}


QUERY = {"device": "1", "lens": "2"}


# -- the model of one laser and lens ---------------------------------------------------------------------------------------------------
@node
def test_the_model_page_is_one_screen_with_the_sets_on_the_left_the_map_in_the_middle_and_the_model_on_the_right(tmp_path):
    out = run(tmp_path, routes_for(pairs=[pair(7, provisional=True), pair(5)]), {"query": QUERY}, """
  out.root = tree.className;
  out.head = tree.querySelectorAll('div').find((d) => has(d, 'os-head')).textContent;
  out.links = tree.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.sets = tree.querySelectorAll('button').filter((b) => has(b, 'lm-set')).map((b) => [b.children.map((c) => c.textContent).join(' | '), b.getAttribute('aria-pressed')]);
  out.columns = tree.querySelectorAll('section').map((s) => s.className);
  const centre = tree.querySelector('.lm-centre'), right = tree.querySelector('.lm-right');
  out.centre = centre.textContent; out.circles = centre.querySelectorAll('circle').length; out.plot = centre.querySelectorAll('svg').length;
  out.right = right.textContent; out.rows = right.querySelectorAll('div').filter((d) => has(d, 'lst-row')).length;
  out.knowledgeLinks = right.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.tabs = tabsOf(tree).length;
  out.selects = tree.querySelector('.lm-head').querySelectorAll('select').map((s) => s.getAttribute('aria-label'));
  await right.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  out.opened = right.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  await byText(tree, 'button', 'Целевой цвет').dispatch('click');
  out.dialog = ctx.document.body.querySelector('.modal').getAttribute('aria-label');
""")
    assert out["root"].split() == ["os", "lm"]                                                           # the page frame; the section rail stays (DEC-081)
    assert "Карта цветов и подбор параметров" in out["head"] and "Данные разных лазеров и линз" in out["head"]
    assert ["← Карта цветов", "#/colors"] in out["links"] and ["Спланировать эксперимент", "#/designer?device=1&lens=2"] in out["links"]
    assert out["selects"] == ["Лазер", "Линза"] and out["dialog"] == "Целевой цвет"                         # the pickers and the target-colour dialog stay
    assert [name for name, _ in out["sets"]] == ["Калиброванные наблюдения | измеренных цветов 3 · в модели 4", "Предварительно · пара 7 | IMG_7.DNG · слоёв 2 · вариантов 1",
                                                 "пара 5 | IMG_5.DNG · слоёв 2 · вариантов 1"]
    assert [pressed for _, pressed in out["sets"]] == ["true", "false", "false"]                          # the calibrated observations come first
    assert out["columns"] == ["os-col lm-left", "os-col lm-centre", "os-col lm-right"]
    assert "Калиброванные наблюдения для прогноза" in out["centre"] and "Пунктир — наборы без оценок повторяемости" in out["centre"]
    assert out["plot"] == 1 and out["circles"] == 3                                                       # one map, a circle for every measured colour
    assert "Модель цветовых параметров" in out["right"] and out["rows"] == 4
    assert out["knowledgeLinks"] == [["Открыть", f"#/knowledge/{k}"] for k in (1, 2, 3, 4)]               # every line opens its entry's page
    assert "31.0 % · 300 кГц · 1000 мм/с · L 41.0 · a 2.0 · b -3.0Измерено" in out["right"]                   # one line: settings, colour, stage
    assert len(out["opened"]) == 1 and "31.0 % · 300 кГц · 1000 мм/с · Q-Pulse 4 нс · шаг 0.003 мм · 1 проход(а)" in out["opened"][0]
    assert "независимых 1" in out["opened"][0] and "уверенность —" in out["opened"][0] and "стабильность дисперсия 1.50" in out["opened"][0]
    assert out["tabs"] == 0                                                                               # the model is a single list, no tabs


@node
def test_a_raw_set_shows_its_map_cautions_and_three_tabs_and_every_old_table_is_still_there(tmp_path):
    out = run(tmp_path, routes_for(pairs=[pair(7, provisional=True, layers=2, variants=3, findings=2), pair(5, variants=0)]), {"query": QUERY}, """
  const sets = () => tree.querySelectorAll('button').filter((b) => has(b, 'lm-set'));
  await sets()[1].dispatch('click');
  const centre = tree.querySelector('.lm-centre'), right = tree.querySelector('.lm-right');
  out.pressed = sets().map((b) => b.getAttribute('aria-pressed'));
  out.centre = centre.textContent; out.circles = centre.querySelectorAll('circle').length;
  out.alerts = centre.querySelectorAll('div').filter((d) => has(d, 'alert')).map((d) => d.textContent);
  out.ingest = centre.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.tabs = tabsOf(right).map((b) => b.textContent);
  out.first = shownPanels(right);
  out.seen = right.textContent;
  await tabsOf(right)[1].dispatch('click');
  out.second = shownPanels(right);
  const variants = right.querySelectorAll('div').find((d) => d.getAttribute('id') === 'lm-tab-panel-variants');
  out.variants = variants.querySelectorAll('.lst-main').map((m) => m.textContent);
  await variants.querySelectorAll('.lst-main')[1].dispatch('click'); await tick();
  out.variantOpen = variants.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  out.variantLinks = variants.querySelectorAll('a').map((a) => a.getAttribute('href'));
  await tabsOf(right)[2].dispatch('click');
  const layers = right.querySelectorAll('div').find((d) => d.getAttribute('id') === 'lm-tab-panel-layers');
  out.layerRows = layers.querySelectorAll('.lst-main').map((m) => m.textContent);
  await layers.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  out.layerOpen = layers.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  out.parts = layers.querySelectorAll('div').filter((d) => has(d, 'lm-item')).map((d) => d.textContent);
  await sets()[2].dispatch('click');
  out.empty = right.textContent; out.pairTitle = tree.querySelector('.lm-centre').querySelector('h3').textContent;
  out.noIngest = tree.querySelector('.lm-centre').querySelectorAll('a').length;
""")
    assert out["pressed"] == ["false", "true", "false"] and out["circles"] == 2
    assert "Предварительные RAW-наблюдения · пара 7" in out["centre"] and "IMG_7.DNG · work7.lbrn2 · Plate · Grade 5 · партия B7" in out["centre"]
    assert "Относительная карта a* × b*" in out["centre"]
    assert len(out["alerts"]) == 3 and "ещё не приняты: нужно проверить наложение масок; состояние пары — готова к принятию" in out["alerts"][0]
    assert "a warning of the pair" in out["alerts"][1] and "относительно данного RAW-снимка" in out["alerts"][2]      # no caution is hidden
    assert out["ingest"] == [["Открыть проверку слоёв и принять пару", "#/ingest?pair=7"]]
    assert out["tabs"] == ["Что видно (2)", "Варианты (3)", "Все слои (2)"] and out["first"] == ["lm-tab-panel-seen"] and out["second"] == ["lm-tab-panel-variants"]
    assert "Что видно в этой паре" in out["seen"] and "Finding 0 · C00" in out["seen"] and "ΔE от чистой поверхности 4.20" in out["seen"]
    assert len(out["variants"]) == 3 and "V0" in out["variants"][0] and "ΔE 12.3" in out["variants"][0] and "настройки неполные" in out["variants"][1]
    assert len(out["variantOpen"]) == 1 and "Отличие от очищенного фона на этом снимке" in out["variantOpen"][0]   # one line each, details on click
    assert out["variantLinks"] == ["#/analysis/7"]
    assert out["layerRows"] == ["C00 · тёмный на этом фотоΔE 7.5частей 1", "C01 · тёмный на этом фотоΔE 7.5"]          # one line per layer
    assert len(out["layerOpen"]) == 1 and "Тестовый участок" in out["layerOpen"][0] and "пикселей 1200" in out["layerOpen"][0]
    assert "a note of the layer" in out["layerOpen"][0] and "L 20.0 · a 1.0 · b 0.0" in out["layerOpen"][0]
    assert len(out["parts"]) == 1 and "C00 / sub1" in out["parts"][0] and "Часть слоя" in out["parts"][0]   # the measured part opens with its layer
    assert "Нет данных" in out["empty"] and out["pairTitle"] == "RAW-наблюдения · пара 5" and out["noIngest"] == 0


@node
def test_the_chosen_set_and_tab_are_remembered_and_a_stale_or_missing_memory_opens_the_first_set(tmp_path):
    out = run(tmp_path, routes_for(pairs=[pair(7), pair(5)]), {"query": QUERY}, """
  const active = (root) => root.querySelectorAll('button').filter((b) => has(b, 'lm-set') && b.getAttribute('aria-pressed') === 'true').map((b) => b.children[0].textContent);
  out.initial = active(tree); out.storedAtStart = {...ctx.__store};
  await tree.querySelectorAll('button').filter((b) => has(b, 'lm-set'))[2].dispatch('click');
  await tabsOf(tree)[1].dispatch('click');
  out.stored = {...ctx.__store};
  const again = await screen(data.arg);
  out.restored = active(again); out.restoredTab = shownPanels(again);
  ctx.__store['lm.set'] = 'pair-99';                                                                   // a set that no longer exists
  out.stale = active(await screen(data.arg));
  ctx.__broken = true;                                                                                 // a viewer whose browser keeps nothing
  const bare = await screen(data.arg);
  out.bare = active(bare);
  await bare.querySelectorAll('button').filter((b) => has(b, 'lm-set'))[1].dispatch('click');
  out.bareAfter = active(bare);
""")
    assert out["initial"] == ["Калиброванные наблюдения"] and out["storedAtStart"]["lm.set"] == "calibrated"
    assert out["stored"]["lm.set"] == "pair-5" and out["stored"]["lm.tab"] == "variants"
    assert out["restored"] == ["пара 5"] and out["restoredTab"] == ["lm-tab-panel-variants"]
    assert out["stale"] == ["Калиброванные наблюдения"] and out["bare"] == ["Калиброванные наблюдения"] and out["bareAfter"] == ["пара 7"]


@node
def test_unstable_sets_stay_visible_and_a_page_with_only_raw_sets_opens_on_the_first_pair(tmp_path):
    out = run(tmp_path, routes_for(samples=0, pairs=[pair(7)], unstable=[(40.0, 330.0, 833.0)], knowledge=0), {"query": QUERY}, """
  out.alert = tree.querySelectorAll('div').filter((d) => has(d, 'lm-unstable')).map((d) => d.textContent);
  out.sets = tree.querySelectorAll('button').filter((b) => has(b, 'lm-set')).map((b) => b.getAttribute('aria-pressed'));
  out.tabs = tabsOf(tree).length; out.columns = tree.querySelectorAll('section').map((s) => s.className);
""")
    assert out["alert"] == ["Нестабильные наборы: 40/330/833"] and out["sets"] == ["true"] and out["tabs"] == 3
    assert out["columns"] == ["os-col lm-left", "os-col lm-centre", "os-col lm-right"]


@node
def test_the_empty_states_keep_their_words_and_their_links(tmp_path):
    none = run(tmp_path, {**routes_for(samples=0, pairs=[]), "/api/devices": {"status": 200, "json": []}}, {"query": QUERY}, """
  out.text = tree.textContent; out.hrefs = tree.querySelectorAll('a').map((a) => a.getAttribute('href')); out.root = tree.className;
""")
    assert "Нет измеренных цветов" in none["text"] and none["hrefs"] == ["#/devices", "#/ingest"]
    empty = run(tmp_path, routes_for(samples=0, pairs=[], knowledge=0), {"query": QUERY}, """
  out.root = tree.className; out.text = tree.textContent; out.hrefs = tree.querySelectorAll('a').map((a) => a.getAttribute('href'));
  out.sets = tree.querySelectorAll('button').filter((b) => has(b, 'lm-set')).length;
""")
    assert empty["root"].split() == ["os", "lm"] and "Для этого лазера с этой линзой пока нет проверенных измерений" in empty["text"]
    assert "#/ingest" in empty["hrefs"] and "#/colors" in empty["hrefs"] and empty["sets"] == 0 and "Целевой цвет" in empty["text"]      # the header and the pickers stay


def many_known() -> list:
    """45 entries: every ninth in production, every other fifth validated, every seventh questioned (with its doubt), the odd ones
    of the fill task and the even ones of the text task, the expected error growing with the id and missing for every third; the
    last has no evidence yet (no summary)."""
    entries = []
    for k in range(1, 46):
        e = known(k, stage="production" if k % 9 == 0 else "validated" if k % 5 == 0 else "measured", questioned=k % 7 == 0)
        e["summary"].update(task={"kind": "fill" if k % 2 else "text", "basis": "explicit"}, expected_delta_e=k / 10, available=k % 3 != 0)
        e["doubt"] = {"reason": "a doubt", "observation_ids": [k]} if e["questioned"] else None
        entries.append(e)
    entries[-1]["summary"] = None
    return entries


LIST = """
  const right = tree.querySelector('.lm-right');
  const ids = () => right.querySelectorAll('.lst-act').map((a) => +a.querySelector('a').getAttribute('href').split('/').pop());
  const count = () => right.querySelector('.lst-count').textContent;
  const chips = () => right.querySelectorAll('.lst-chip').map((c) => c.textContent);
  const more = () => { const b = right.querySelector('.lst-foot').querySelector('button'); return b ? b.textContent : null; };
  const chip = async (text) => { await right.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith(text)).dispatch('click'); await tick(); };
  const choose = async (label, value) => {
    const s = right.querySelectorAll('label').find((l) => has(l, 'lst-select') && l.querySelector('span').textContent === label).querySelector('select');
    s.value = value; await s.dispatch('change'); await tick();
  };
  const opened = () => right.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
"""


@node
def test_the_model_shows_one_page_of_its_entries_with_the_stage_doubt_and_task_filters_the_sorts_and_the_search(tmp_path):
    out = run(tmp_path, {**routes_for(knowledge=0), "/api/knowledge": {"status": 200, "json": many_known()}}, {"query": QUERY}, LIST + """
  out.head = tree.querySelector('.lm-right').querySelector('.os-col-head').textContent;
  out.first = {rows: right.querySelectorAll('.lst-row').length, count: count(), more: more(), chips: chips(), ids: ids(),
    selects: right.querySelectorAll('label').filter((l) => has(l, 'lst-select')).map((l) => l.querySelector('span').textContent)};
  out.bare = right.querySelectorAll('.lst-main')[4].textContent;
  await chip('Производственное'); out.production = [count(), ids()];
  await chip('Все');
  await choose('Под вопросом', 'yes'); out.questioned = [count(), ids()];
  await right.querySelectorAll('.lst-main')[0].dispatch('click'); await tick(); out.doubt = opened();
  await choose('Под вопросом', ''); await choose('Задача', 'text'); out.text = [count(), more()];
  await choose('Задача', ''); await choose('Порядок', 'error'); out.error = ids().slice(0, 3);
  await choose('Порядок', 'light'); out.light = ids().slice(0, 2);
  await choose('Порядок', 'newest'); out.newest = ids().slice(0, 2);
  await right.querySelector('.lst-foot').querySelector('button').dispatch('click'); await tick(); out.second = [count(), more()];
  const search = right.querySelector('.lst-search'); search.value = '75.0 %'; await search.dispatch('input'); await tick(); await tick();
  out.searched = [count(), ids()];
""")
    assert out["head"] == "Модель цветовых параметров45"                                                  # the count of the whole model
    first = out["first"]
    assert first["rows"] == 20 and first["count"] == "показано 20 из 45" and first["more"] == "Показать ещё 20"     # one page, not 45 lines
    assert first["chips"] == ["Все · 45", "Измерено · 32", "Валидировано · 8", "Производственное · 5"]          # a stage with no entry is not offered
    assert first["selects"] == ["Под вопросом", "Задача", "Порядок"]
    assert first["ids"][:13] == [9, 18, 27, 36, 45, 5, 10, 15, 20, 25, 30, 35, 40]                           # the further an entry got, the higher
    assert out["bare"] == "75.0 % · 300 кГц · 1000 мм/сПроизводственное"                                     # an entry without evidence: no colour
    assert out["production"] == ["показано 5 из 5", [9, 18, 27, 36, 45]]
    assert out["questioned"] == ["показано 6 из 6", [35, 7, 14, 21, 28, 42]]
    assert len(out["doubt"]) == 1 and "Под вопросом. a doubt" in out["doubt"][0] and "Задача: Заливка" in out["doubt"][0]
    assert out["text"] == ["показано 20 из 22", "Показать ещё 2"]
    assert out["error"] == [1, 2, 4]                                                                          # no estimate of the error: last
    assert out["light"] == [44, 43] and out["newest"] == [45, 44]
    assert out["second"] == ["показано 40 из 45", "Показать ещё 5"]
    assert out["searched"] == ["показано 1 из 1", [45]]


@node
def test_the_raw_layers_are_one_page_with_the_role_filter_and_the_sorts(tmp_path):
    raw = pair(7, layers=26)
    for i, s in enumerate(raw["samples"]):
        s["delta_e_from_clean_witness"] = i * 0.5
    raw["samples"][24]["role"] = "registration, QR and engraved labels"
    raw["samples"][25]["role"] = "pre-test cleaning witness"
    del raw["samples"][25]["delta_e_from_clean_witness"]
    out = run(tmp_path, routes_for(samples=0, pairs=[raw], knowledge=0), {"query": QUERY}, LIST + """
  await tabsOf(right).find((b) => b.textContent.startsWith('Все слои')).dispatch('click');
  const layers = right.querySelectorAll('div').find((d) => d.getAttribute('id') === 'lm-tab-panel-layers');
  const rows = () => layers.querySelectorAll('.lst-main').map((m) => m.textContent);
  out.tab = tabsOf(right).map((b) => b.textContent)[2];
  out.first = {rows: rows().length, count: layers.querySelector('.lst-count').textContent, chips: layers.querySelectorAll('.lst-chip').map((c) => c.textContent)};
  await layers.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith('Свидетель чистки')).dispatch('click'); await tick();
  out.witness = rows();
  await layers.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith('Все')).dispatch('click'); await tick();
  const sort = layers.querySelector('select'); sort.value = 'contrast'; await sort.dispatch('change'); await tick();
  out.contrast = rows().slice(0, 2);
  sort.value = 'light'; await sort.dispatch('change'); await tick();
  out.light = rows()[0];
""")
    assert out["tab"] == "Все слои (26)"
    assert out["first"]["rows"] == 20 and out["first"]["count"] == "показано 20 из 26"
    assert out["first"]["chips"] == ["Все · 26", "Тестовый участок · 24", "Свидетель чистки · 1", "Метки и подписи · 1"]
    assert out["witness"] == ["C025 · тёмный на этом фотоСвидетель чистки"]                                   # the witness has no ΔE of its own
    assert out["contrast"] == ["C024 · тёмный на этом фотоМетки и подписиΔE 12.0", "C023 · тёмный на этом фотоΔE 11.5"]
    assert out["light"].startswith("C025 · ")                                                                 # L 45: the lightest layer


# -- the knowledge page ----------------------------------------------------------------------------------------------------------------
def knowledge_routes(stage="measured", questioned=False, history=None, ids=(480, 481), lens_id=2) -> dict:
    record = {"id": 5, "device_id": 1, "lens_id": lens_id, "stage": stage, "questioned": questioned, "parameters": {**params(), "pulse_width": 4},
              "doubt": {"reason": "a doubt", "observation_ids": [3, 4]} if questioned else None,
              "history": history if history is not None else [{"id": 1, "type": "created", "at": "2026-10-18T12:28:00", "from_stage": None, "to_stage": "measured", "reason": "first"}],
              "summary": {"lab": [42.3, 2.1, -16.1], "independent_engravings": 2, "confidence": 0.5, "expected_delta_e": 3.25, "available": True,
                          "stability": {"assessed": False}, "rig_repeatability": {"assessed": False}, "observation_ids": list(ids), "attribution_note": "an attribution note"}}
    return {"/api/knowledge/5": {"status": 200, "json": record}}


@node
def test_the_knowledge_page_is_two_columns_with_the_facts_and_decisions_on_the_left_and_the_history_and_evidence_on_the_right(tmp_path):
    history = [{"id": 1, "type": "created", "at": "2026-10-18T12:28:00", "from_stage": None, "to_stage": "measured", "reason": "first"},
               {"id": 2, "type": "promoted", "at": "2026-10-19T08:00:00", "from_stage": "measured", "to_stage": "candidate", "reason": "second"}]
    out = run(tmp_path, knowledge_routes(stage="validated", questioned=True, history=history, ids=(480, 481, 482)), {"id": "knowledge", "arg": 5}, """
  out.root = tree.className;
  out.links = tree.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.head = tree.querySelectorAll('div').find((d) => has(d, 'os-head')).textContent;
  out.alert = tree.querySelectorAll('div').filter((d) => has(d, 'kn-alert')).map((d) => d.textContent);
  const cols = tree.querySelectorAll('section');
  out.columns = cols.map((s) => s.className);
  out.facts = tree.querySelectorAll('dt').map((d) => d.textContent);
  out.factText = tree.querySelector('dl').textContent;
  out.buttons = tree.querySelectorAll('button').map((b) => b.textContent);
  out.history = cols[1].textContent; out.evidence = cols[2].textContent;
  out.rows = cols[1].querySelectorAll('tr').length;
  out.note = tree.querySelectorAll('div').filter((d) => has(d, 'alert') && !has(d, 'kn-alert')).map((d) => d.textContent);
""")
    assert out["root"].split() == ["os", "kn"] and "Знание о цвете" in out["head"] and "Валидировано" in out["head"]
    assert ["← К модели цвета", "#/colors?device=1&lens=2"] in out["links"] and ["Правила оценки", "#/setup?tab=rules&device=1&lens=2"] in out["links"]
    assert len(out["alert"]) == 1 and out["alert"][0].startswith("Под вопросом. a doubt") and any(n.startswith("an attribution note") for n in out["note"])
    assert out["columns"] == ["os-col", "os-col kn-history", "os-col kn-evidence"]
    assert out["facts"] == ["Стадия", "Цвет", "Параметры", "Независимых гравировок", "Уверенность", "Совпали по цвету", "Ожидаемая ошибка ΔE", "Стабильность", "Повторяемость стенда"]
    assert "L 42.3 · a 2.1 · b -16.1" in out["factText"] and "40.0 % · 330 кГц · 833 мм/с · импульс 4 · интервал 0.003 · проходов 1" in out["factText"]
    assert "не оценена: её дают только пересъёмки одной гравировки, скорректированные по эталонной карте" in out["factText"]
    assert "Утвердить для производства" in out["buttons"] and "Подтвердить запись" in out["buttons"]            # the operator's decisions stay on the page
    assert out["buttons"].count("Откатить переход") == 1                                                      # only a transition can be rolled back
    assert "История2" in out["history"] and out["rows"] == 3 and "повышено автоматически" in out["history"] and "Кандидат" in out["history"]
    assert "Наблюдения-основания3" in out["evidence"] and "480, 481, 482" in out["evidence"]


@node
def test_the_knowledge_page_of_a_production_colour_offers_the_manual_demotion_and_of_an_unknown_lens_links_back_to_it(tmp_path):
    out = run(tmp_path, knowledge_routes(stage="production", lens_id=None), {"id": "knowledge", "arg": 5}, """
  out.links = tree.querySelectorAll('a').map((a) => a.getAttribute('href'));
  out.buttons = tree.querySelectorAll('button').map((b) => b.textContent);
""")
    assert "#/colors?device=1&lens=unknown" in out["links"] and "#/setup?tab=rules&device=1&lens=unknown" in out["links"]
    assert "Понизить вручную" in out["buttons"] and "Утвердить для производства" not in out["buttons"]


@node
def test_a_recipe_counted_from_its_newest_engraving_says_from_which_and_offers_to_undo_it(tmp_path):
    """act-on-findings REQ-002: the knowledge page of a recipe the operator counts from its newest engraving names that engraving, how many
    older ones do not count, and offers to undo the decision."""
    routes = knowledge_routes()
    record = routes["/api/knowledge/5"]["json"]
    record["counted_from"] = {"id": 6, "kind": "older_engravings", "engraving_ids": ["e1", "e2"], "note": "старые до чистки линзы",
                              "created_at": "2026-10-25T12:00:00+00:00",
                              "kept": {"engraving_id": "e3", "title": "Big Plate", "pair_ids": [140], "when": "2026-10-24T09:00:00+00:00", "lab": [40, 2, -16]}}
    out = run(tmp_path, {**routes, "/api/exclusions/6/revoke": {"status": 200, "json": {"exclusion": {"id": 6}, "run_id": 70}}},
              {"id": "knowledge", "arg": 5}, """
  out.line = tree.querySelectorAll('div').filter((d) => has(d, 'alert') && d.textContent.startsWith('Считается')).map((d) => d.textContent);
  ctx.document.body.append(tree);
  await tree.querySelectorAll('button').find((b) => b.textContent === 'Отменить «с последней гравировки»').dispatch('click'); await tick();
  const modal = ctx.document.body.querySelector('.modal');
  out.text = modal.querySelector('p').textContent;
  await modal.querySelectorAll('button').find((b) => b.textContent === 'Отменить «с последней гравировки»').dispatch('click'); await tick(); await tick();
  out.sent = ctx.requests.filter((r) => r.path === '/api/exclusions/6/revoke').map((r) => r.method);
""")
    assert out["line"] == ["Считается с гравировки «Big Plate» от 24.10.2026 (фото № 140); старых не считается: 2. "
                           "Решение оператора от 25.10.2026: «старые до чистки линзы»."]
    assert out["text"].startswith("Старые гравировки этого рецепта снова будут считаться") and out["sent"] == ["POST"]


# -- the frame ---------------------------------------------------------------------------------------------------------------------------
def test_the_model_and_knowledge_pages_are_built_on_the_shared_one_screen_frame():
    assert "'os lm'" in COLOURS and "'os-head lm-head'" in COLOURS and "'os-body lm-body'" in COLOURS and "App.tabs(view.tabs" in COLOURS
    assert "'os kn'" in KNOWLEDGE and "'os-body kn-body'" in KNOWLEDGE and "class: 'os-scroll'" in KNOWLEDGE
    assert "PAIR_STATUS[set.status]" in COLOURS and "'lm.set'" in COLOURS and "'lm.tab'" in COLOURS               # translation and the remembered choice
    for old in ("class: 'toolbar'", "class: 'card stack'", "table(["):
        assert old not in COLOURS, old                                                                       # no long page of cards and wide tables any more


def test_the_columns_of_the_model_page_scroll_inside_and_the_page_stacks_on_a_narrow_screen():
    assert re.search(r"\.lm-body \{grid-template-columns:minmax\(220px,270px\) minmax\(0,1fr\) minmax\(400px,500px\)\}", CSS)
    assert re.search(r"\.lm-stage \{flex:1;min-height:0;display:flex;flex-direction:column", CSS) and re.search(r"\.lm-plot svg \{flex:1;min-width:0;min-height:0\}", CSS)
    assert re.search(r"\.lm-alerts \{[^}]*max-height:42%;overflow:auto", CSS) and re.search(r"\.kn-body \{grid-template-columns:minmax\(340px,480px\) minmax\(0,1fr\)\}", CSS)
    narrow = re.search(r"@media \(max-width:1100px\) \{\s*\.lm-head \{(.*?)\n\}", CSS[CSS.index("16) модель цвета"):], re.S)
    assert narrow and "flex-wrap:wrap" in narrow.group(1) and ".lm-plot {flex:none" in narrow.group(1)       # a phone scrolls the page as before
