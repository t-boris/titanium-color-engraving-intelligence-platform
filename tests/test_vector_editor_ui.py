"""REQ-043..REQ-049 (DEC-001, DEC-075..DEC-077): the colour editor of a photograph vector work. Static checks of the scripts and
the stylesheet, then the screen run in node over the small DOM of ui_dom.js with a job view shaped as the API contract
describes it (the editor is checked against the contract, not against one state of the server)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from titanium_platform.api.app import UI_DIR

SCRIPTS = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
EDITOR = (UI_DIR / "screens" / "vector-editor.js").read_text(encoding="utf-8")
COLOURS = (UI_DIR / "screens" / "vector-colours.js").read_text(encoding="utf-8")
VECTOR = (UI_DIR / "screens" / "vector.js").read_text(encoding="utf-8")
CSS = (UI_DIR / "styles.css").read_text(encoding="utf-8")


# -- static -------------------------------------------------------------------------------------------------------------------
def test_the_editor_is_loaded_after_the_helpers_and_before_the_colour_step_that_embeds_it():
    order = {s: i for i, s in enumerate(SCRIPTS)}
    assert order["/app.js"] < order["/dialogs.js"] < order["/screens/vector-editor.js"] < order["/screens/vector-colours.js"] < order["/screens/vector.js"]
    assert "const {chip, params, seconds, palette, de, BASIS} = VectorEditor;" in COLOURS and "VectorEditor.create(j, run)" in COLOURS


def test_no_colour_is_accepted_anywhere_any_more():
    """DEC-001: every colour is coloured from the start; neither an accept button nor an accept operation is left."""
    for path in UI_DIR.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"op:\s*'accept(_all)?'", text), path.name
    for name in ("vector.js", "vector-colours.js", "vector-editor.js", "vector-split.js"):
        text = (UI_DIR / "screens" / name).read_text(encoding="utf-8")
        assert "Принять" not in text and "unresolved" not in text and "proposed" not in text, name


def test_the_editor_sends_every_operation_of_the_contract_and_asks_the_server_for_the_reach_of_a_fill():
    for op in ("paint", "merge_titanium", "merge_colours", "merge_regions", "exclude_region", "include_region", "exclude_colour", "include_colour"):
        assert f"op: '{op}'" in EDITOR, op
    assert "undoRedo('undo')" in EDITOR and "undoRedo('redo')" in EDITOR and "act({op: kind})" in EDITOR
    assert "{op: 'paint', region: rid, scope: state.scope, entry_id: state.active}" in EDITOR and "op.similarity_de = state.similarity" in EDITOR
    assert "get(`/vector/${id}/reach?region=${encodeURIComponent(rid)}&similarity_de=${state.similarity}`)" in EDITOR
    assert "`${rid}|${state.similarity}|${j.document.version}`" in EDITOR and "}, 120);" in EDITOR      # debounced, cached per version
    assert "get(`/vector/${j.id}/neighbours`)" in EDITOR and "`${j.id}:${j.document.version}`" in EDITOR       # DEC-080: once per split version
    for op in ("settings", "assign", "restore", "set_colour"):
        assert f"op: '{op}'" in COLOURS, op


def test_undo_and_redo_answer_ctrl_z_and_ctrl_shift_z_only_while_the_editor_is_on_screen_and_no_field_has_the_focus():
    assert "document.addEventListener('keydown'" in EDITOR and "if (current) current.key(ev)" in EDITOR
    assert "(ev.ctrlKey || ev.metaKey)" in EDITOR and "ev.code === 'KeyZ'" in EDITOR and "z && !ev.shiftKey ? 'undo' : 'redo'" in EDITOR
    assert "if (!el.isConnected)" in EDITOR and "/^(INPUT|TEXTAREA|SELECT)$/" in EDITOR and "ev.key === 'Escape'" in EDITOR


def test_the_editor_fills_elements_through_app_fill_and_never_through_replaceChildren():
    assert ".replaceChildren(" not in EDITOR and ".replaceChildren(" not in COLOURS
    assert "const {h, fill, btn, get, pill, toast, num, labText} = App;" in EDITOR
    assert "innerHTML" not in EDITOR and "location.href" not in EDITOR and "window.open(" not in EDITOR


def test_every_label_of_the_editor_is_russian_and_present():
    labels = ("'Титан'", "'Исходные цвета'", "'Оригинал'", "'Вписать'", "'Кисть'", "'Пипетка'", "'Выделение'", "'Участок'",
              "'Весь исходный цвет'", "'Заливка похожих'", "'Похожесть, ΔE'", "'Авто'", "'Слить в один контур'", "'Исключить'",
              "'Вернуть'", "'Слои титана'", "'Слить в один'", "'Объединить исходные цвета'", "'вне допуска'",
              "'Показать далёкие от оригинала'", "'Отменить'", "'Повторить'", "'Активный цвет'", "'Палитра'")
    for label in labels:
        assert label in EDITOR, label
    assert "`Область ${rid} · исходный цвет № ${k + 1} · титан: `" in EDITOR and "`рецепт: ${params(e.parameters)}" in EDITOR
    assert "`Слоёв ${t.recipes ?? (j.layers || []).length} из ${j.layer_cap} · время слоёв цвета ${duration(t.seconds)} · средний ΔE ${num(t.mean_delta_e)}`" in EDITOR
    assert "h('summary', {}, 'Подробно по цветам')" in COLOURS


def test_the_picture_fills_the_card_beside_the_panel_and_the_panel_goes_below_it_on_a_narrow_screen():
    assert re.search(r"\.vw-editor \{display:grid;grid-template-columns:minmax\(0,1fr\) minmax\(260px,320px\)", CSS)
    narrow = re.search(r"@media \(max-width:900px\) \{(.*?)\n\}", CSS, re.S)
    assert narrow and ".vw-editor {grid-template-columns:minmax(0,1fr)}" in narrow.group(1)
    assert re.search(r"\.vw-details \.tw \{[^}]*overflow-x:auto", CSS) and re.search(r"\.vw-details \{min-width:0", CSS)
    assert re.search(r"\.vw-ed-svg path\.vw-hot \{[^}]*vector-effect:non-scaling-stroke", CSS)      # outlines are classes on the paths
    assert re.search(r"\.vw-swatch\.as-shot \{[^}]*dashed", CSS)


def test_the_screen_updates_in_place_after_an_operation_and_sends_operations_one_after_another():
    assert "const run = (op) => (queue = queue.then(() => send(op)));" in VECTOR
    assert "show(await post(`/vector/${j.id}/colouring`, op))" in VECTOR and "if (colours) colours.update(next);" in VECTOR
    assert "if (resplit) fill(split, VectorSplit.card(next, reload, smooth));" in VECTOR
    assert "j.export_blocked ? h('div', {class: 'alert warn'}, I18N.tr(j.export_blocked))" in VECTOR      # the reason stays beside the export


# -- the screen in node ----------------------------------------------------------------------------------------------------------
TABLES = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-tasks.js", "i18n-data.js", "i18n-findings.js",
          "i18n-palette.js", "i18n-gaps.js"]
GLUE = ("const __screens = {}, __renders = []; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { __renders.push(1); };"
        "globalThis.__screens = __screens; globalThis.__renders = __renders;")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'hardware.js', {code: %(glue)s}, 'screens/vector-split.js', 'screens/vector-editor.js',
  'screens/vector-colours.js', 'screens/vector.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const byLabel = (root, tag, label) => root.querySelectorAll(tag).find((el) => el.getAttribute('aria-label') === label);
(async () => {
  const out = {};
  const tree = await ctx.__screens.vector.render({query: {plan: String(data.id)}});
  await tick(); await tick();
  const svg = () => tree.querySelectorAll('svg').find((s) => (s.getAttribute('class') || '').split(' ').includes('vw-ed-svg'));
  const path = (id) => svg().querySelectorAll('path').find((p) => p.getAttribute('data-region') === id);
  const classed = (cls) => svg().querySelectorAll('path').filter((p) => p.classList.contains(cls)).map((p) => p.getAttribute('data-region')).sort();
  const posted = () => ctx.requests.filter((r) => r.method === 'POST').map((r) => JSON.parse(r.body));
  const section = (title) => tree.querySelectorAll('section').find((s) => (s.querySelector('h4') || {}).textContent === title);
  const swatch = (entry) => tree.querySelectorAll('button').find((b) => b.getAttribute('data-entry') === entry);
%(body)s
  out.renders = ctx.__renders.length;
  out.text = tree.textContent;
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" width="40mm" height="20mm">'
       + "".join(f'<path d="M{x0} {y0} L{x1} {y0} L{x1} {y1} L{x0} {y1} Z" fill="#000000" fill-rule="evenodd" stroke="#000000" stroke-width="0.01" '
                 f'data-region="{rid}" data-color="{k}"/>'
                 for rid, k, (x0, y0, x1, y1) in (("r1", 0, (0, 0, 10, 10)), ("r2", 0, (10, 0, 20, 10)), ("r3", 1, (20, 0, 30, 10)),
                                                  ("r4", 1, (30, 0, 40, 10)), ("r5", 2, (0, 10, 40, 20))))
       + "</svg>")


def entry(eid, srgb, lab, basis="chart", automatic=True, rate=0.5):
    return {"id": eid, "srgb": srgb, "lab": lab, "basis": basis, "automatic": automatic, "time_s_per_cm2": rate, "engravings": 2, "photographs": 1,
            "parameters": {"power": 10, "frequency": 30, "speed": 500, "pulse_width": 4, "line_interval": 0.02, "passes": 1},
            "mode": "Scan", "confidence": 0.8, "expected_delta_e": 1.5, "stability": {"assessed": True, "variance": 0.4}, "experiments": 1}


# entry ids are text on the server (12 hex characters); short ones here
PALETTE = [entry("e11", [205, 198, 182], [79.5, 0.3, 11.0]), entry("e12", [150, 60, 90], [42.0, 35.0, 5.0]),
           entry("e13", [120, 140, 60], [55.0, -20.0, 40.0]), entry("e14", [60, 70, 200], [35.0, 20.0, -60.0], basis="as-shot", automatic=False, rate=None)]


def layer(index, eid, regions, area_mm2):
    e = PALETTE[[p["id"] for p in PALETTE].index(eid)]
    return {"index": index, "name": f"C{index:02d} P10-F30-V500-I0.02", "entry_id": eid, "regions": regions, "region_count": len(regions),
            "pixels": int(area_mm2 * 100), "area_mm2": area_mm2, "srgb": e["srgb"], "lab": e["lab"], "time_s_per_cm2": e["time_s_per_cm2"]}


def view(version=1):
    """A photograph job as GET /api/vector/{id} returns it under the editor's contract: three source colours (the second outside
    the tolerance, the third excluded), five regions (r4 with a colour of its own), three layers."""
    totals = {"recipes": 3, "regions": 4, "mean_delta_e": 3.1, "within_tolerance": 1, "colours": 3, "seconds": 125}
    return {
        "id": 7, "name": "Тест", "strategy": "photo", "plan_identifier": "TCE-TEST", "lens": None, "markers_enabled": False,
        "experiment": {"device": {"name": "Laser"}, "material": {"name": "Grade 2 sheet"}},
        "document": {"version": version, "size_mm": {"width": 40, "height": 20}, "px_mm": 0.1, "image_px": {"width": 400, "height": 200},
                     "colours": 3, "regions": 5, "n_colors": 3, "min_area_mm2": 100, "tolerance_mm": 0.08, "faces": {"searched": False, "found": 0},
                     "important_regions": 0},
        "split": {"n_colors": 3, "detail": "medium", "tolerance_mm": 0.08, "faces": False, "manual": [], "removed": []},
        "areas": {"detected": [], "faces": 0, "search_failed": False},
        "colours": [
            {"index": 0, "lab": [80.0, 0.0, 10.0], "srgb": [210, 200, 180], "pixels": 20000, "status": "automatic", "entry_id": "e11",
             "how": "fastest_within_tolerance", "delta_e": 1.2, "nearest_delta_e": 1.2, "outside_tolerance": False, "regions": 2, "open_regions": 2},
            {"index": 1, "lab": [50.0, 30.0, 20.0], "srgb": [170, 90, 70], "pixels": 20000, "status": "hand", "entry_id": "e12", "how": "hand",
             "delta_e": 17.7, "nearest_delta_e": 17.7, "outside_tolerance": True, "regions": 2, "open_regions": 1},
            {"index": 2, "lab": [30.0, -10.0, -20.0], "srgb": [40, 80, 110], "pixels": 40000, "status": "excluded", "entry_id": None, "how": None,
             "delta_e": None, "nearest_delta_e": 20.0, "outside_tolerance": False, "regions": 1, "open_regions": 0}],
        "entries": {e["id"]: e for e in PALETTE[:3]},
        "colouring": {"mode": "closest", "seed": 0, "variant": 1, "regions": {"r4": "e13"}, "excluded_colours": [2], "excluded_regions": []},
        "settings": {"tolerance_de": 3, "max_time": None, "include_as_shot": False},
        "outside": {"colours": 1, "regions": 2, "share": 0.25, "indexes": [1]}, "missing": {"regions": 0},
        "totals": totals, "layers": [layer(1, "e11", ["r1", "r2"], 200), layer(2, "e12", ["r3"], 100), layer(3, "e13", ["r4"], 100)],
        "layer_cap": 29, "palette_size": 4, "undo": 2, "redo": 0,
        "ai": {"available": True, "styles": ["realistic", "artistic", "impressionism", "cubism"], "photo_allowed": False, "photo_px": 512, "max_text": 400},
        "variants": [{"number": 1, "mode": "closest", "seed": 0, "at": "2026-10-19T10:00:00", "totals": totals, "version": version},
                     {"number": 2, "mode": "random", "seed": 1, "at": "2026-10-19T10:05:00", "totals": totals, "version": version - 1}],
        "export_blocked": None, "exports": [],
        "time": {"seconds": 400, "complete": True, "layers": [{"index": i, "seconds": 100, "note": None} for i in range(4)]}}


# who borders whom in SVG above: r1-r2-r3-r4 side by side, r5 under all four (GET /api/vector/7/neighbours, editor DEC-080)
NEAR = {"version": 1, "neighbours": {"r1": ["r2", "r5"], "r2": ["r1", "r3", "r5"], "r3": ["r2", "r4", "r5"], "r4": ["r3", "r5"],
                                     "r5": ["r1", "r2", "r3", "r4"]}}


def routes(colouring_view=None) -> dict:
    j = view()
    return {"/api/vector/7": {"status": 200, "json": j}, "/api/vector/7/split.svg": {"status": 200, "text": SVG, "type": "image/svg+xml"},
            "/api/vector/7/palette": {"status": 200, "json": PALETTE}, "/api/vector/7/neighbours": {"status": 200, "json": NEAR},
            "/api/vector/7/colouring": {"status": 200, "json": colouring_view or j},
            "/api/vector/7/reach": {"status": 200, "json": {"region": "r3", "similarity_de": 8, "version": 1, "regions": ["r3", "r4"], "pixels": 200, "share": 0.25}}}


def run_editor(tmp_path, routes_, body):
    (tmp_path / "data.json").write_text(json.dumps({"id": 7, "routes": routes_}), encoding="utf-8")
    script = tmp_path / "editor.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI_DIR) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body},
                      encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    out = json.loads(run.stdout)
    assert not any(bad in out["text"] for bad in ("null", "undefined", "NaN", "[object", "без перевода", "Принять")), out["text"][:3000]
    return out


node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@node
def test_the_picture_is_painted_in_titanium_and_the_panel_shows_layers_colours_totals_and_history(tmp_path):
    out = run_editor(tmp_path, routes(), """
  out.fills = Object.fromEntries(svg().querySelectorAll('path').map((p) => [p.getAttribute('data-region'), p.getAttribute('fill')]));
  out.viewBox = svg().getAttribute('viewBox');
  out.undo = byText(tree, 'button', 'Отменить').disabled;
  out.redo = byText(tree, 'button', 'Повторить').disabled;
  out.palette = tree.querySelectorAll('button').filter((b) => b.getAttribute('data-entry')).map((b) => [b.getAttribute('data-entry'), b.className, b.getAttribute('title')]);
  out.details = tree.querySelectorAll('details').map((d) => d.querySelector('summary').textContent);
""")
    assert out["fills"] == {"r1": "rgb(205,198,182)", "r2": "rgb(205,198,182)", "r3": "rgb(150,60,90)", "r4": "rgb(120,140,60)", "r5": "#e6e6e6"}
    assert out["viewBox"] == "0 0 40 20" and out["undo"] is False and out["redo"] is True
    classes = {eid: cls for eid, cls, _ in out["palette"]}
    assert set(classes) == {"e11", "e12", "e13", "e14"} and "as-shot" in classes["e14"] and "not-auto" in classes["e14"] and "as-shot" not in classes["e11"]
    assert all(re.search(r"(ΔE [\d.]+ · )?([\d.]+ с/см²|не оценено)", title) for _, _, title in out["palette"])
    text = out["text"]
    for part in ("1. Цвета и разбиение", "2. Файл LightBurn", "Слоёв 3 из 29 · время слоёв цвета 2 мин 05 с · средний ΔE 3.10", "Слои титана",
                 "Исходные цвета", "вне допуска", "Показать далёкие от оригинала", "C01", "2.00 см² · областей 2 · 1 с", "№ 2", "ΔE 17.70",
                 "Дальше допуска ΔE 3: цветов 1, областей 2 (25.0 % площади)", "Палитра: 4", "сделан на разбиении № 0", "Авто"):
        assert part in text, part
    assert len(out["details"]) == 2 and out["details"][0].startswith("Важные области: лица, глаза, губы") and out["details"][1] == "Подробно по цветам"
    assert out["renders"] == 0


@node
def test_a_brush_click_paints_the_area_the_source_colour_or_the_fill_the_hover_outlined(tmp_path):
    out = run_editor(tmp_path, routes(), """
  svg().setAttribute('data-mark', 'first');
  await swatch('e14').dispatch('click');
  out.active = section('Активный цвет').textContent;
  await path('r1').dispatch('click'); await tick();
  await byText(tree, 'button', 'Весь исходный цвет').dispatch('click');
  await path('r1').dispatch('pointermove', {clientX: 5, clientY: 5});
  out.hotColour = classed('vw-hot');
  out.tip = tree.querySelectorAll('div').find((d) => d.className === 'vw-ed-tip').textContent;
  await path('r1').dispatch('click'); await tick();
  await byText(tree, 'button', 'Заливка похожих').dispatch('click');
  await path('r3').dispatch('pointermove', {clientX: 25, clientY: 5});
  out.hotBeforeReach = classed('vw-hot');
  await wait(200);
  out.hotFill = classed('vw-hot');
  out.tipFill = tree.querySelectorAll('div').find((d) => d.className === 'vw-ed-tip').textContent;
  await path('r3').dispatch('click'); await tick();
  await byText(tree, 'button', 'Авто').dispatch('click');
  await byText(tree, 'button', 'Участок').dispatch('click');
  await path('r2').dispatch('click'); await tick();
  out.posted = posted();
  out.reach = ctx.requests.filter((r) => r.path.endsWith('/reach')).map((r) => r.url);
  out.sameSvg = svg().getAttribute('data-mark') === 'first';
  out.svgFetches = ctx.requests.filter((r) => r.path.endsWith('/split.svg')).length;
""")
    assert "Загрузка" not in out["active"] and "не оценено" in out["active"] and "автоматика его не выбирает" in out["active"]
    assert out["hotColour"] == ["r1", "r2"] and out["hotBeforeReach"] == ["r3"] and out["hotFill"] == ["r3", "r4"]
    assert out["tip"].startswith("Область r1 · исходный цвет № 1 · титан: ΔE 1.16") and "рецепт: 10.0 % · 30.0 кГц · 500 мм/с" in out["tip"]
    assert "весь исходный цвет № 1, областей 2" in out["tip"] and "заливка похожих (ΔE 8), областей 2" in out["tipFill"]
    assert out["posted"] == [{"op": "paint", "region": "r1", "scope": "region", "entry_id": "e14"},
                             {"op": "paint", "region": "r1", "scope": "colour", "entry_id": "e14"},
                             {"op": "paint", "region": "r3", "scope": "fill", "entry_id": "e14", "similarity_de": 8},
                             {"op": "paint", "region": "r2", "scope": "region", "entry_id": None}]
    assert out["reach"] == ["/api/vector/7/reach?region=r3&similarity_de=8"]
    assert out["sameSvg"] and out["svgFetches"] == 1 and out["renders"] == 0            # recoloured in place, nothing re-rendered


@node
def test_pipette_selection_merges_history_far_outlines_views_zoom_and_pan(tmp_path):
    out = run_editor(tmp_path, routes(), """
  await path('r4').dispatch('click', {altKey: true});
  out.altPicked = tree.querySelectorAll('button').filter((b) => b.classList.contains('picked')).map((b) => b.getAttribute('data-entry'));
  await byText(tree, 'button', 'Пипетка').dispatch('click');
  await path('r3').dispatch('click');
  out.pipettePicked = tree.querySelectorAll('button').filter((b) => b.classList.contains('picked')).map((b) => b.getAttribute('data-entry'));
  await byText(tree, 'button', 'Выделение').dispatch('click');
  await path('r1').dispatch('click');
  await path('r2').dispatch('click', {shiftKey: true});
  out.selected = classed('vw-sel');
  out.selection = section('Выделение').textContent;
  await byText(section('Выделение'), 'button', 'Слить в один контур').dispatch('click'); await tick();
  await byText(section('Выделение'), 'button', 'Исключить').dispatch('click'); await tick();
  out.selectedAfter = classed('vw-sel');
  const layerBoxes = tree.querySelectorAll('input').filter((i) => (i.getAttribute('aria-label') || '').startsWith('Отметить слой'));
  for (const box of layerBoxes.slice(0, 2)) { box.checked = true; await box.dispatch('change'); }
  out.target = byLabel(tree, 'select', 'Каким цветом титана станут отмеченные слои').value;
  await byText(tree, 'button', 'Слить в один').dispatch('click'); await tick();
  out.layersChecked = tree.querySelectorAll('input').filter((i) => (i.getAttribute('aria-label') || '').startsWith('Отметить слой') && i.checked).length;
  const colourBoxes = tree.querySelectorAll('input').filter((i) => (i.getAttribute('aria-label') || '').startsWith('Отметить исходный цвет'));
  for (const box of colourBoxes.slice(0, 2)) { box.checked = true; await box.dispatch('change'); }
  await byText(tree, 'button', 'Объединить исходные цвета').dispatch('click'); await tick();
  await byText(tree, 'button', 'Отменить').dispatch('click'); await tick();
  await byText(tree, 'button', 'Повторить').dispatch('click'); await tick();        // nothing to redo: nothing is sent
  out.posted = posted();
  const far = section('Исходные цвета').querySelector('input');
  far.checked = true; await far.dispatch('change');
  out.far = [svg().getAttribute('class'), classed('vw-far')];
  await byText(tree, 'button', 'Оригинал').dispatch('click');
  out.original = [svg().getAttribute('class'), svg().querySelector('image').getAttribute('href')];
  await byText(tree, 'button', 'Исходные цвета').dispatch('click');
  out.source = path('r1').getAttribute('fill');
  await byText(tree, 'button', 'Титан').dispatch('click');
  await byText(tree, 'button', 'Кисть').dispatch('click');
  await byLabel(tree, 'button', 'Увеличить').dispatch('click');
  out.zoomed = svg().getAttribute('viewBox');
  await path('r1').dispatch('pointerdown', {clientX: 50, clientY: 50, button: 0});
  await path('r1').dispatch('pointermove', {clientX: 60, clientY: 50});
  await path('r1').dispatch('pointerup', {clientX: 60, clientY: 50});
  await path('r1').dispatch('click', {clientX: 60, clientY: 50});                    // the end of a drag is not a click
  out.panned = svg().getAttribute('viewBox');
  await path('r1').dispatch('wheel', {deltaY: -100, clientX: 50, clientY: 50});
  out.wheeled = svg().getAttribute('viewBox');
  await byText(tree, 'button', 'Вписать').dispatch('click');
  out.fit = svg().getAttribute('viewBox');
  out.postedAfterDrag = posted().length;
""")
    assert out["altPicked"] == ["e13"] and out["pipettePicked"] == ["e12"]                # r4's own colour, then r3's colour's
    assert out["selected"] == ["r1", "r2"] and "Выбрано областей: 2" in out["selection"] and out["selectedAfter"] == ["r1", "r2"]
    assert out["target"] == "e11" and out["layersChecked"] == 0
    assert out["posted"] == [{"op": "merge_regions", "regions": ["r1", "r2"]}, {"op": "exclude_region", "regions": ["r1", "r2"]},
                             {"op": "merge_titanium", "entries": ["e11", "e12"], "into": "e11"}, {"op": "merge_colours", "colours": [0, 1]}, {"op": "undo"}]
    assert out["far"] == ["vw-ed-svg show-far", ["r3", "r4"]]
    assert out["original"] == ["vw-ed-svg view-original show-far", "/api/plans/7/source-image"] and out["source"] == "rgb(210,200,180)"
    assert out["zoomed"] == "6.6667 3.3333 26.6667 13.3333" and out["panned"] == "4 3.3333 26.6667 13.3333"
    w = float(out["wheeled"].split()[2])
    assert w < 26.6667 and out["fit"] == "0 0 40 20" and out["postedAfterDrag"] == 5


@node
def test_the_merge_of_areas_is_offered_only_for_a_connected_selection_and_says_why_not(tmp_path):
    """Editor REQ-048, DEC-080: the button is enabled while the selected areas, two or more, are connected through shared borders."""
    out = run_editor(tmp_path, routes(), """
  const merge = () => byText(section('Выделение'), 'button', 'Слить в один контур');
  const shown = () => [merge().disabled, section('Выделение').textContent];
  await byText(tree, 'button', 'Выделение').dispatch('click');
  await path('r1').dispatch('click');
  out.one = shown();
  await path('r3').dispatch('click', {shiftKey: true});          // r1 and r3 do not border one another
  out.apart = shown();
  await path('r2').dispatch('click', {shiftKey: true});          // r2 joins them: a chain
  out.chain = shown();
  await path('r3').dispatch('click', {shiftKey: true});          // r3 out again: r1 and r2 border
  out.pair = shown();
  await path('r4').dispatch('click', {shiftKey: true});          // r4 is apart from both
  out.stray = shown();
  await path('r5').dispatch('click', {shiftKey: true});          // r5 borders every one
  out.all = shown();
  out.fetches = ctx.requests.filter((r) => r.path.endsWith('/neighbours')).length;
  out.posted = posted();
""")
    why = "не связаны общими границами"
    assert out["one"][0] is True and why not in out["one"][1] and "соседние по границе" in out["one"][1]
    assert out["apart"][0] is True and why in out["apart"][1] and "касания углом недостаточно" in out["apart"][1]
    assert out["chain"][0] is False and why not in out["chain"][1]
    assert out["pair"][0] is False and why not in out["pair"][1]
    assert out["stray"][0] is True and why in out["stray"][1]
    assert out["all"][0] is False and why not in out["all"][1]
    assert out["fetches"] == 1 and out["posted"] == [] and out["renders"] == 0                       # asked once for the split version


@node
def test_if_the_neighbours_cannot_be_read_the_merge_stays_offered_and_the_server_decides(tmp_path):
    r = routes()
    r["/api/vector/7/neighbours"] = {"status": 500, "json": {"error": "boom", "kind": "internal"}}
    out = run_editor(tmp_path, r, """
  await byText(tree, 'button', 'Выделение').dispatch('click');
  await path('r1').dispatch('click');
  await path('r3').dispatch('click', {shiftKey: true});
  const merge = byText(section('Выделение'), 'button', 'Слить в один контур');
  out.disabled = merge.disabled;
  out.selection = section('Выделение').textContent;
  await merge.dispatch('click'); await tick();
  out.posted = posted();
""")
    assert out["disabled"] is False and "Не удалось проверить, какие области соседние" in out["selection"]
    assert out["posted"] == [{"op": "merge_regions", "regions": ["r1", "r3"]}]


@node
def test_a_merge_that_makes_a_new_split_version_loads_its_picture_and_keeps_the_view_and_the_selection(tmp_path):
    out = run_editor(tmp_path, routes(colouring_view=view(version=2)), """
  await byLabel(tree, 'button', 'Увеличить').dispatch('click');
  await byText(tree, 'button', 'Выделение').dispatch('click');
  await path('r1').dispatch('click');
  await path('r2').dispatch('click', {shiftKey: true});
  svg().setAttribute('data-mark', 'first');
  await byText(section('Выделение'), 'button', 'Слить в один контур').dispatch('click'); await tick(); await tick();
  out.fresh = svg().getAttribute('data-mark') !== 'first' && tree.querySelectorAll('svg').filter((s) => (s.getAttribute('class') || '').includes('vw-ed-svg')).length === 1;
  out.viewBox = svg().getAttribute('viewBox');
  out.selected = classed('vw-sel');
  out.fills = svg().querySelectorAll('path').map((p) => p.getAttribute('fill'));
  out.svgFetches = ctx.requests.filter((r) => r.path.endsWith('/split.svg')).length;
  out.nearFetches = ctx.requests.filter((r) => r.path.endsWith('/neighbours')).length;
""")
    assert out["fresh"] and out["svgFetches"] == 2 and out["viewBox"] == "6.6667 3.3333 26.6667 13.3333" and out["selected"] == ["r1", "r2"]
    assert out["nearFetches"] == 2                                                              # once per split version, as the picture
    assert "#000000" not in out["fills"] and "разбиение № 2" in out["text"] and out["renders"] == 0


@node
def test_a_refused_operation_is_shown_translated_and_the_picture_stays_as_it_was(tmp_path):
    r = routes()
    r["/api/vector/7/colouring"] = {"status": 422, "json": {"error": "there is no such source colour", "kind": "invalid"}}
    out = run_editor(tmp_path, r, """
  await path('r1').dispatch('click'); await tick();
  out.toasts = ctx.document.body.querySelectorAll('div').filter((d) => (d.className || '').startsWith('toast')).map((d) => d.textContent);
  out.fill = path('r1').getAttribute('fill');
  out.busy = tree.querySelectorAll('div').find((d) => (d.className || '').startsWith('vw-editor')).className;
""")
    assert any("Такого исходного цвета нет" in t for t in out["toasts"]) and not any("no such" in t for t in out["toasts"])
    assert out["fill"] == "rgb(205,198,182)" and out["busy"] == "vw-editor" and out["renders"] == 0


def test_the_contract_view_used_here_has_every_field_the_editor_reads():
    """The fields of the job view the editor reads are the ones of the API contract; a rename on the server shows up here."""
    j = view()
    for field in ("colours", "entries", "colouring", "settings", "outside", "totals", "layers", "layer_cap", "palette_size", "undo", "redo",
                  "variants", "document", "export_blocked"):
        assert field in j and f"j.{field}" in EDITOR + COLOURS + VECTOR, field
    for field in ("index", "lab", "srgb", "status", "entry_id", "delta_e", "outside_tolerance", "regions"):
        assert field in j["colours"][0] and f"c.{field}" in EDITOR, field
