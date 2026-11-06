"""Creating a work from its result (feature ux-work-creation-p0): the shared context strip and its change dialog, the three-step creation screen,
the gate with the starter test, the unfinished-task bar and the older forms that start from the shared context. Run in node over the small DOM
of the other screen tests, with a small in-memory server that answers the creation routes the way the real one does (the real routes are
tested in test_creation_drafts.py and test_creation_context.py)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SCRIPTS = [*TABLES, "app.js", "dialogs.js", "list.js", "hardware.js", "screens/material-picker.js", "context.js", "filepick.js", "tasks.js", "photo-modes.js", "photo-quality.js", "GLUE",
           "screens/vector-split.js", "screens/lab-source.js", "screens/plate-dialog.js", "screens/evidence-summary.js", "screens/photo-panels.js", "screens/photo-kind-step.js", "screens/creation.js",
           "EXPORT"]

HARNESS = r"""
const fs = require('fs');
const {context, load, El} = require(__DOM__);
Object.defineProperty(El.prototype, 'style', {get() { return this._style || (this._style = {}); }});
const ctx = context({});
const docKeys = [];                                                          // the document's key handlers, so a test can press Escape the way the browser would
const addOn = ctx.document.addEventListener ? ctx.document.addEventListener.bind(ctx.document) : null;
ctx.document.addEventListener = (type, fn, ...rest) => { if (type === 'keydown') docKeys.push(fn); if (addOn) addOn(type, fn, ...rest); };
ctx.__keys = docKeys;
const GLUE = `
  globalThis.__screens = {}; globalThis.__went = []; globalThis.__renders = [];
  App.register = (d) => { globalThis.__screens[d.id] = d; }; App.render = () => { globalThis.__renders.push(1); }; App.go = (r) => { globalThis.__went.push(r); };
  globalThis.FormData = class { constructor() { this.items = []; }
    append(k, v, name) { this.items.push([k, v !== null && typeof v === 'object' ? {file: name || v.name || 'blob', size: v.size} : String(v)]); } };`;
const EXPORT = 'globalThis.Creation = Creation; globalThis.WorkContext = WorkContext; globalThis.PlateDialog = PlateDialog;';
const SCRIPTS = __SCRIPTS__.map((s) => (s === 'GLUE' ? {code: GLUE} : s === 'EXPORT' ? {code: EXPORT} : s));

// -- the small server ------------------------------------------------------------------------------------------------------------------------
const clone = (x) => JSON.parse(JSON.stringify(x));
const S = {
  context: {device_id: 1, lens_id: 2, lens_basis: 'chosen', material_id: 3, capture_setup_id: null, source: null, stored: true, stale: [],
    device: {id: 1, name: 'JPT', title: 'JPT 60'}, lens: {id: 2, name: 'F-Theta', focal_length_mm: 174}, material: {id: 3, name: 'Plate', grade: 'Grade 5'}, capture_setup: null},
  devices: [{id: 1, name: 'JPT', title: 'JPT 60', lens: {id: 2}}, {id: 2, name: 'Mopa', title: 'Mopa 30', lens: null}],
  lenses: [{id: 2, kind: 'F-Theta', name: 'F-Theta', focal_length_mm: 174}],
  materials: [{id: 3, name: 'Plate', grade: 'Grade 5'}, {id: 4, name: 'Sheet', grade: 'Grade 2'}],
  drafts: [], seq: 1, readiness: {}, tolerance: 5, scales: [], vectorId: 99, photoId: 77, planId: 21,
  facts: {colour: {areas: 12, colours: 7}, photo: {levels: 180}, silhouette: {areas: 4}, lines: {strokes: 31}},
};
const routes = [];
const on = (spec, fn) => { const [method, pattern] = spec.split(' '); routes.unshift([method, new RegExp('^' + pattern.replace(/:\w+/g, '([^/]+)') + '$'), fn]); };
const reply = (status, body, headers = {}) => ({ok: status < 300, status, headers: {get: (k) => (k.toLowerCase() === 'content-type' ? 'application/json' : headers[k.toLowerCase()] ?? null)},
  json: async () => body, text: async () => JSON.stringify(body), blob: async () => ({size: 1})});
const refuse = (message, status = 422) => reply(status, {error: message, kind: 'validation'});
const picture = (facts) => ({ok: true, status: 200, headers: {get: (k) => (k.toLowerCase() === 'content-type' ? 'image/png' : k.toLowerCase() === 'x-preview-facts' ? JSON.stringify(facts) : null)},
  blob: async () => ({size: 10}), json: async () => ({})});
ctx.fetch = async (url, opts = {}) => {
  const [path, qs] = String(url).split('?'), method = opts.method || 'GET';
  const req = {method, path, query: new URLSearchParams(qs || ''), body: opts.body};
  req.form = opts.body && opts.body.items ? Object.fromEntries(opts.body.items) : null;
  req.json = typeof opts.body === 'string' ? JSON.parse(opts.body) : null;
  ctx.requests.push({path, url: String(url), method, body: opts.body, form: req.form, json: req.json});
  for (const [m, re, fn] of routes) { if (m !== method) continue; const hit = re.exec(path); if (hit) return fn(req, ...hit.slice(1)); }
  return reply(404, {error: path + ' not found', kind: 'not_found'});
};
const view = (d) => ({id: d.id, status: d.status, flow: d.flow, name: d.name, state: d.state, image: d.image, created_at: 't', updated_at: 't', work_kind: d.work_kind, work_id: d.work_id});
const open = () => S.drafts.filter((d) => d.status === 'open').slice().reverse();
const readyFor = (result) => S.readiness[result] || {result, ready: true, missing: [], context: S.context, measured: 3, starter_test: null};
on('GET /api/creation/context', () => reply(200, S.context));
on('PUT /api/creation/context', (req) => { S.context = {...S.context, ...req.json}; return reply(200, S.context); });
on('POST /api/creation/context/impact', (req) => reply(200, S.impact ? S.impact(req.json) : {changed: true, warnings: [], now: {}, after: {}}));
on('GET /api/creation/readiness', (req) => reply(200, readyFor(req.query.get('result'))));
on('POST /api/creation/starter-plate', (req) => reply(201, {plan_id: S.planId, name: 'Плата · ' + req.json.result}));
on('GET /api/creation/drafts', () => reply(200, open().map(view)));
const save = (draft, req) => {
  const f = req.form;
  if (f.state !== undefined) draft.state = JSON.parse(f.state);
  if (f.name !== undefined) draft.name = f.name;
  if (f.picture) draft.image = {name: f.picture.file, type: 'image/png', size: 5};
  return draft;
};
on('POST /api/creation/drafts', (req) => {
  if (S.refuseDraft) return refuse(S.refuseDraft);
  const draft = save({id: S.seq++, status: 'open', flow: req.form.flow, name: null, state: {}, image: null}, req);
  S.drafts.push(draft);
  return reply(201, view(draft));
});
on('PUT /api/creation/drafts/:id', (req, id) => {
  const draft = S.drafts.find((d) => d.id === +id);
  if (!draft) return refuse('unfinished task ' + id + ' not found', 404);
  if (S.refuseUpdate) return refuse(S.refuseUpdate);
  return reply(200, view(save(draft, req)));
});
on('GET /api/creation/drafts/:id/picture', () => picture({}));
on('GET /api/creation/drafts/:id/preview/:name', (req, id, name) => {
  const result = name.replace('.png', '');
  if (S.previewFails && S.previewFails.includes(result)) return refuse('the picture could not be drawn as ' + result);
  return picture(S.facts[result]);
});
on('POST /api/creation/drafts/:id/complete', async (req, id) => {
  if (S.refuseComplete) return refuse(S.refuseComplete, 500);
  const draft = S.drafts.find((d) => d.id === +id);
  Object.assign(draft, {status: 'completed', work_kind: req.json.work_kind, work_id: req.json.work_id, image: null});
  return reply(200, view(draft));
});
on('POST /api/creation/drafts/:id/discard', (req, id) => { const d = S.drafts.find((x) => x.id === +id); d.status = 'discarded'; d.image = null; return reply(200, view(d)); });
on('GET /api/devices', () => reply(200, S.devices));
on('GET /api/lenses', () => reply(200, S.lenses));
on('GET /api/materials', () => reply(200, S.materials));
on('GET /api/materials/:id', (req, id) => { const m = S.materials.find((x) => x.id === +id); return m ? reply(200, m) : reply(404, {error: 'not found'}); });   // the stock selector reads one record
on('GET /api/labs/choices', () => reply(200, S.labs || []));
on('GET /api/plate-types', () => reply(200, [{id: 'grey_scales', name: 'Шкалы серого'}, {id: 'calibration', name: 'Калибровка'}]));
on('GET /api/rules', () => reply(200, {delta_tolerance: S.tolerance}));
on('PUT /api/rules', (req) => { S.tolerance = req.json.delta_tolerance; return reply(200, {delta_tolerance: S.tolerance}); });
on('POST /api/vector', async () => { if (S.vectorHold) await S.vectorHold; return S.refuseVector ? refuse(S.refuseVector) : reply(201, {id: S.vectorId}); });
on('POST /api/photo-works', () => (S.refusePhoto ? refuse(S.refusePhoto) : reply(201, {id: S.photoId, created_at: 'T0'})));
// the question «Какая гравировка?» (PhotoKindStep) asks the made work for its kinds, saves the chosen one and deletes a work that is not kept
on('GET /api/photo-works/:id', (req, id) => (S.photoGone ? reply(404, {error: 'no such work', kind: 'not_found'}) : reply(200, {id: +id, created_at: S.photoStamp || 'T0'})));
on('GET /api/photo-works/:id/kinds', () => reply(200, S.kindsAnswer || {kind: 'grayscale', problem: null, kinds: ['grayscale', 'threshold', 'dither', 'sketch'].map((key) => ({
  key, family: key === 'grayscale' ? 'power' : key === 'sketch' ? 'edges' : 'dots', basis: 'documented', estimate: key !== 'grayscale', picture: `/api/photo-works/${S.photoId}/kinds/${key}.png`,
  ...(key === 'grayscale' ? {min_power: 12, max_power: 28} : {power: 12.5, hex: '#3355aa', clean_hex: '#bbbbbb'})}))}));
on('POST /api/photo-works/:id/settings', (req) => (S.refuseKind ? refuse(S.refuseKind) : reply(200, {id: S.photoId, kind: req.json.kind})));
on('DELETE /api/plans/:id', (req, id) => { S.deleted = (S.deleted || []).concat(+id); return reply(200, {}); });
on('GET /api/grey-scales', () => reply(200, {scales: S.scales}));

load(ctx, __UI__, SCRIPTS);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const settle = async () => { for (let i = 0; i < 12; i++) await wait(0); };
const body = ctx.document.body;
const button = (root, text) => root.querySelectorAll('button').find((b) => b.textContent === text);
// a box is named by its aria-label or, in a field, by the label of the field (the unit and the permitted values are read after the name, not in it)
const labelled = (root, label) => root.querySelectorAll('[aria-label]').find((el) => el.getAttribute('aria-label') === label)
  || (root.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === label.replace(/, мм$/, '')) || {firstControl: () => undefined}).firstControl();
const dialog = () => body.querySelector('.modal');
const sent = (method, path) => ctx.requests.filter((r) => r.method === method && r.path === path);
const alerts = (root) => root.querySelectorAll('[role]').filter((a) => a.getAttribute('role') === 'alert' && !a.hidden).map((a) => a.textContent);
const heading = (root) => root.querySelector('h2').textContent;
/** The words a field says beside its box when it is wrong (ux-save-feedback-p0, REQ-003): found by the label of the field. */
const fieldError = (root, text) => (root.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === text) || {errorText: () => undefined}).errorText();
/** Open the creation screen on ``query`` and put it in the page, as the router does. */
async function screen(query = {}) {
  const tree = await ctx.__screens.new.render({query});
  body.append(tree);
  await settle();
  return tree;
}
/** Step 1 filled in: a picture, a name and a width. */
async function fillPicture(tree, {name = 'Портрет', width = '80', file = 'portrait.png'} = {}) {
  const input = tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file');
  input.files = [{name: file, size: 2048}];
  await input.dispatch('change');
  labelled(tree, 'Название работы').value = name;
  labelled(tree, 'Ширина на титане, мм').value = width;
  return input;
}
const tiles = (tree) => tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'radio');
/** A photograph asks «Какая гравировка?» before it is kept (BUG-003): the button of step 3 opens the question, its last button keeps the work. */
const FORWARD = 'Дальше: какая гравировка →';
let pending = null;                                                          // the click that opened the question stays unanswered until the person answers it
const ask = async (tree) => { pending = button(tree, FORWARD).dispatch('click'); await settle(); };
const kinds = () => dialog().querySelectorAll('.ge-kind');
const kindNames = () => kinds().map((k) => k.querySelector('strong').textContent);
const keep = () => dialog().querySelectorAll('button').filter((b) => b.textContent.startsWith('Create in'))[0];
const dialogButton = (text) => dialog().querySelectorAll('button').find((b) => b.textContent === text);
/** Choose a stock record the way a person does: the selector's own dialog opens above the box, the row of the record is chosen there (the titanium is no longer a drop-down). */
const chooseStock = async (box, name) => {
  await button(labelled(box, 'Stock'), 'Choose…').dispatch('click'); await settle();
  const inner = body.querySelectorAll('.modal').pop();
  await button(inner.querySelectorAll('.lst-row').find((r) => r.textContent.includes(name)), 'Choose').dispatch('click');
  return settle();
};
(async () => {
  const out = {};
__BODY__
  console.log(JSON.stringify(out));
  process.exit(0);                                                          // the toasts' timers need not run out
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, body: str, timeout: int = 120) -> dict:
    script = tmp_path / "creation.js"
    script.write_text(HARNESS.replace("__DOM__", json.dumps(str(Path(__file__).with_name("ui_dom.js")))).replace("__UI__", json.dumps(str(UI) + "/"))
                      .replace("__SCRIPTS__", json.dumps(SCRIPTS)).replace("__BODY__", body), encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=timeout)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


# -- REQ-003: image, size, then the result; going back keeps everything --------------------------------------------------------------------
@node
def test_the_first_step_asks_for_picture_name_and_size_and_a_missing_picture_or_size_stops_it_with_nothing_saved(tmp_path):
    out = run(tmp_path, """
  const tree = await screen();
  out.head = heading(tree);
  out.steps = tree.querySelector('ol').querySelectorAll('li').map((li) => [li.textContent, li.getAttribute('aria-current')]);
  out.context = tree.querySelector('.work-context').textContent;
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.noPicture = fieldError(tree, 'Картинка');
  await fillPicture(tree, {width: '0'});
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.noSize = [fieldError(tree, 'Ширина на титане'), labelled(tree, 'Ширина на титане, мм').value, labelled(tree, 'Ширина на титане, мм').getAttribute('aria-invalid')];
  out.posts = sent('POST', '/api/creation/drafts').length;
  out.classic = tree.querySelectorAll('a').map((a) => a.getAttribute('href')).filter((h) => h.includes('classic'));
""")
    assert out["head"] == "Новая работа · шаг 1 из 3: Картинка и размер"
    assert out["steps"] == [["1. Картинка и размер", "step"], ["2. Что получится", None], ["3. Настройки и создание", None]]
    for word in ("Laser", "JPT 60", "F-Theta", "Plate", "Grade 5", "This workshop’s measurements"):
        assert word in out["context"]
    assert out["noPicture"] == "Выберите картинку (PNG, JPEG, TIFF)"                          # each wrong box says why beside itself and keeps what was typed
    assert out["noSize"] == ["Allowed: greater than 0 mm. Entered: 0", "0", "true"]
    assert out["posts"] == 0                                                    # a task is made only when the picture and the size are there
    assert out["classic"] == ["#/vector?new=1&classic=1"]                       # text and a layer task of its own stay in the one-page form


@node
def test_the_second_step_shows_the_persons_own_picture_as_four_comparable_tiles_with_what_each_makes_and_what_it_needs(tmp_path):
    out = run(tmp_path, """
  S.readiness.photo = {result: 'photo', ready: false, missing: ['measurements'], context: S.context, measured: 0, starter_test: {result: 'photo', needs_rig: false, becomes: 'measured_scale', test_type: 'grey_scales'}};
  S.readiness.lines = {result: 'lines', ready: false, missing: ['laser'], context: S.context, measured: null, starter_test: null};
  const tree = await screen();
  await fillPicture(tree);
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.head = heading(tree);
  out.tiles = tiles(tree).map((t) => [t.querySelector('strong').textContent, t.getAttribute('aria-checked'), t.querySelector('img').getAttribute('alt'), t.textContent]);
  out.previews = ctx.requests.filter((r) => r.path.includes('/preview/')).map((r) => r.url);
  out.fileSent = sent('POST', '/api/creation/drafts')[0].form;
  out.next = button(tree, 'Дальше →').disabled;
""")
    assert out["head"] == "Новая работа · шаг 2 из 3: Что получится"
    assert [t[0] for t in out["tiles"]] == ["Цветные области", "Фотогравировка", "Силуэт", "Линии"]
    assert all(t[1] == "false" for t in out["tiles"]) and out["next"] is True            # nothing is chosen for the person
    assert "областей: 12" in out["tiles"][0][2] and "цветов: 7" in out["tiles"][0][2]       # the picture's own look, with what was found in it
    assert "градаций серого в картинке: 180" in out["tiles"][1][2] and "линий: 31" in out["tiles"][3][2]
    assert "Файл LightBurn: слой на каждый использованный цвет заливки" in out["tiles"][0][3]         # export suitability stays visible
    assert "нужны измерения" in out["tiles"][1][3] and "не хватает: лазер" in out["tiles"][3][3] and "можно создать" in out["tiles"][0][3]
    assert sorted(out["previews"]) == sorted(f"/api/creation/drafts/1/preview/{r}.png?width_mm=80" for r in ("colour", "photo", "silhouette", "lines"))
    assert out["fileSent"]["flow"] == "new" and out["fileSent"]["picture"] == {"file": "portrait.png", "size": 2048} and out["fileSent"]["name"] == "Портрет"
    assert json.loads(out["fileSent"]["state"])["width_mm"] == "80"


@node
def test_a_tile_that_cannot_be_drawn_says_so_and_the_others_still_work_and_choosing_a_tile_keeps_the_keyboard_on_it(tmp_path):
    out = run(tmp_path, """
  S.previewFails = ['lines'];
  const tree = await screen();
  await fillPicture(tree);
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  const all = tiles(tree);
  out.failed = all[3].textContent;
  out.drawn = all.slice(0, 3).map((t) => t.querySelector('img') !== null);
  all[2].focus();
  await all[2].dispatch('click'); await settle();
  out.focusStays = ctx.document.activeElement === all[2];
  out.same = tiles(tree)[2] === all[2];
  out.checked = tiles(tree).map((t) => t.getAttribute('aria-checked'));
  out.next = button(tree, 'Дальше →').disabled;
""")
    assert "Не удалось нарисовать: the picture could not be drawn as lines" in out["failed"] and "можно создать" in out["failed"]
    assert out["drawn"] == [True, True, True]
    assert out["focusStays"] is True and out["same"] is True                       # the tile is updated in place, never replaced under the keyboard
    assert out["checked"] == ["false", "false", "true", "false"] and out["next"] is False


@node
def test_going_back_keeps_the_picture_the_name_the_size_the_result_and_every_setting_and_the_task_holds_them_all(tmp_path):
    out = run(tmp_path, """
  const tree = await screen();
  const file = await fillPicture(tree, {name: 'Портрет Инны', width: '72'});
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  await tiles(tree)[0].dispatch('click'); await settle();
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.third = heading(tree);
  const colours = tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'number' && i.getAttribute('max') === '29');
  colours.value = '7'; await colours.dispatch('input');
  const detail = labelled(tree, 'Детальность'); detail.value = 'fine'; await detail.dispatch('change');
  await button(tree, '← Назад').dispatch('click'); await settle();
  out.second = [heading(tree), tiles(tree).map((t) => t.getAttribute('aria-checked'))];
  await button(tree, '← Назад').dispatch('click'); await settle();
  out.first = [heading(tree), labelled(tree, 'Название работы').value, labelled(tree, 'Ширина на титане, мм').value,
    tree.querySelector('.file-name').textContent, file.files[0].name];
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.again = [tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'number' && i.getAttribute('max') === '29').value, labelled(tree, 'Детальность').value];
  await wait(700); await settle();
  out.saved = JSON.parse(sent('PUT', '/api/creation/drafts/1').pop().form.state);
  out.pictures = ctx.requests.filter((r) => r.form && r.form.picture).length;
""")
    assert out["third"] == "Новая работа · шаг 3 из 3: Настройки и создание"
    assert out["second"] == ["Новая работа · шаг 2 из 3: Что получится", ["true", "false", "false", "false"]]
    assert out["first"][:3] == ["Новая работа · шаг 1 из 3: Картинка и размер", "Портрет Инны", "72"] and out["first"][4] == "portrait.png"
    assert "portrait.png" in out["first"][3]
    assert out["again"] == ["7", "fine"]
    assert out["saved"]["result"] == "colour" and out["saved"]["width_mm"] == "72" and out["saved"]["name"] == "Портрет Инны"
    assert out["saved"]["method"]["colours"] == "7" and out["saved"]["method"]["detail"] == "fine"
    assert out["pictures"] == 1                                                    # the picture travels once; going back and forth never sends it again


@node
def test_the_algorithm_delta_e_smoothing_and_time_are_in_the_advanced_settings_of_the_chosen_method_and_a_photo_work_has_none(tmp_path):
    out = run(tmp_path, """
  const tree = await screen();
  await fillPicture(tree);
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  const pick = async (i) => { await tiles(tree)[i].dispatch('click'); await button(tree, 'Дальше →').dispatch('click'); await settle(); };
  await pick(0);
  const adv = tree.querySelector('details');
  out.colour = [adv.querySelector('summary').textContent, adv.getAttribute('open'), adv.textContent.includes('Допуск ΔE'), adv.textContent.includes('Сглаживание границ'),
    adv.textContent.includes('Алгоритм разбиения'), adv.textContent.includes('Наибольшее время гравировки')];
  out.outside = tree.querySelector('.card').textContent.replace(adv.textContent, '').includes('Допуск ΔE');
  await button(tree, '← Назад').dispatch('click'); await settle();
  await pick(2);
  out.silhouette = [tree.querySelector('details').textContent.includes('Порог серого'), tree.querySelector('details').textContent.includes('Точность контура'),
    tree.querySelector('details').textContent.includes('Алгоритм разбиения')];
  await button(tree, '← Назад').dispatch('click'); await settle();
  await pick(1);
  out.photo = [tree.querySelector('details'), tree.textContent.includes('Шкала — лучшая из измеренных')];
  S.tolerance = null;
""")
    assert out["colour"][0] == "Дополнительно: алгоритм, допуск ΔE, сглаживание, время" and out["colour"][1] is None
    assert out["colour"][2:] == [True, True, True, True] and out["outside"] is False
    assert out["silhouette"] == [True, True, False]
    assert out["photo"] == [None, True]


@node
def test_the_result_tiles_are_one_tab_stop_and_answer_the_arrow_keys_like_radio_buttons_and_the_choice_is_saved(tmp_path):
    out = run(tmp_path, """
  const tree = await screen();
  await fillPicture(tree);
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  const stops = () => tiles(tree).map((t) => t.getAttribute('tabindex'));
  const checked = () => tiles(tree).map((t) => t.getAttribute('aria-checked'));
  out.start = [stops(), checked()];
  tiles(tree)[0].focus();
  await tiles(tree)[0].dispatch('keydown', {key: 'ArrowRight'});
  out.right = [stops(), checked(), ctx.document.activeElement === tiles(tree)[1], button(tree, 'Дальше →').disabled];
  await tiles(tree)[1].dispatch('keydown', {key: 'End'});
  out.end = [checked(), ctx.document.activeElement === tiles(tree)[3]];
  await tiles(tree)[3].dispatch('keydown', {key: 'ArrowDown'});
  out.wrap = checked();
  await tiles(tree)[0].dispatch('keydown', {key: 'ArrowUp'});
  out.wrapBack = checked();
  await tiles(tree)[3].dispatch('keydown', {key: 'Home'});
  out.home = checked();
  await tiles(tree)[0].dispatch('keydown', {key: 'a'});
  out.other = checked();
  await wait(700); await settle();
  out.saved = JSON.parse(sent('PUT', '/api/creation/drafts/1').pop().form.state).result;
""")
    assert out["start"] == [["0", "-1", "-1", "-1"], ["false"] * 4]                      # nothing is chosen for the person; one tab stop on the group
    assert out["right"] == [["-1", "0", "-1", "-1"], ["false", "true", "false", "false"], True, False]
    assert out["end"] == [["false", "false", "false", "true"], True]
    assert out["wrap"] == ["true", "false", "false", "false"] and out["wrapBack"] == ["false", "false", "false", "true"]
    assert out["home"] == ["true", "false", "false", "false"] and out["other"] == out["home"]
    assert out["saved"] == "colour"


@node
def test_every_step_puts_the_keyboard_on_its_heading_going_forward_and_back_and_a_failed_step_keeps_it_where_it_was(tmp_path):
    out = run(tmp_path, """
  const tree = await screen();
  out.first = ctx.document.activeElement && ctx.document.activeElement.textContent;
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.refused = [ctx.document.activeElement === button(tree, 'Дальше →') || ctx.document.activeElement === null, heading(tree)];
  await fillPicture(tree);
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.second = [ctx.document.activeElement && ctx.document.activeElement.textContent, heading(tree)];
  await tiles(tree)[3].dispatch('click');
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.third = [ctx.document.activeElement && ctx.document.activeElement.textContent, heading(tree)];
  await button(tree, '← Назад').dispatch('click'); await settle();
  out.back = [ctx.document.activeElement && ctx.document.activeElement.textContent, heading(tree)];
""")
    assert out["first"] == "Новая работа · шаг 1 из 3: Картинка и размер"
    assert out["refused"][1].startswith("Новая работа · шаг 1 из 3")
    assert out["second"][0] == out["second"][1] and out["third"][0] == out["third"][1] and out["back"][0] == out["back"][1]
    assert out["third"][1].endswith("Настройки и создание") and out["back"][1].endswith("Что получится")


# -- REQ-001: the shared context -----------------------------------------------------------------------------------------------------------
@node
def test_the_change_dialog_shows_what_becomes_unavailable_before_the_person_confirms_and_nothing_is_saved_until_then(tmp_path):
    out = run(tmp_path, """
  S.impact = (c) => ({changed: true, now: {}, after: {}, warnings: [
    {code: 'fewer', result: 'colour', now: 9, after: 2}, {code: 'none_left', result: 'photo', now: 1, after: 0}, {code: 'titanium_differs'}, {code: 'lens_unknown'}]});
  const tree = await screen();
  await button(tree, 'Change…').dispatch('click'); await settle();
  const box = dialog();
  out.title = box.querySelector('h3').textContent;
  out.firstAsk = sent('POST', '/api/creation/context/impact').length;
  const laser = labelled(box, 'Laser'); laser.value = '2'; await laser.dispatch('change'); await settle();
  await chooseStock(box, 'Sheet');
  out.warnings = box.querySelectorAll('li').map((li) => li.textContent);
  out.asked = sent('POST', '/api/creation/context/impact').pop().json;
  out.savedBefore = sent('PUT', '/api/creation/context').length;
  out.live = box.querySelectorAll('[aria-live]').length;
  out.stripBefore = tree.querySelector('.work-context').textContent.includes('JPT 60');
  await button(box, 'Apply').dispatch('click'); await settle();
  out.put = sent('PUT', '/api/creation/context').map((r) => r.json);
  out.closed = dialog() === null;
  out.focus = ctx.document.activeElement && ctx.document.activeElement.textContent;
""")
    assert out["title"] == "New work context"
    assert out["warnings"] == ["Measured fill colors (color regions): 9 available before; 2 for the selected setup.",
                               "Measured grey scales (photo engraving): 1 available before; none for the selected setup.",
                               "The titanium grade is different. Recipes and colors measured on the previous grade do not apply to this one.",
                               "The lens is unknown. Knowledge from different lenses is kept separate, so measurements from other lenses will not be included."]
    assert out["asked"]["device_id"] == 2 and out["asked"]["material_id"] == 4
    assert out["savedBefore"] == 0 and out["stripBefore"] is True                    # the warnings come first; nothing is saved by looking
    assert out["live"] >= 1
    assert out["put"] == [{"device_id": 2, "lens_id": None, "material_id": 4, "source": None}]
    assert out["closed"] is True and out["focus"] == "Change…"                    # the keyboard returns to the button that opened the dialog


@node
def test_cancelling_the_change_dialog_saves_nothing_and_a_late_answer_for_an_earlier_choice_is_dropped(tmp_path):
    out = run(tmp_path, """
  let release;
  const slow = new Promise((r) => { release = r; });
  S.impact = null;
  on('POST /api/creation/context/impact', async (req) => {
    if (req.json.material_id === 4) { await slow; return reply(200, {changed: true, warnings: [{code: 'titanium_differs'}], now: {}, after: {}}); }
    return reply(200, {changed: true, warnings: [{code: 'lens_unknown'}], now: {}, after: {}});
  });
  const tree = await screen();
  await button(tree, 'Change…').dispatch('click'); await settle();
  const box = dialog();
  await chooseStock(box, 'Sheet');                                                                // the slow answer is for this choice
  await chooseStock(box, 'Plate');                                                                // ... and this one is the newer
  release(); await settle();
  out.shown = box.querySelectorAll('li').map((li) => li.textContent);
  await button(box, 'Cancel').dispatch('click'); await settle();
  out.put = sent('PUT', '/api/creation/context').length;
  out.closed = dialog() === null;
  out.stripSame = tree.querySelector('.work-context').textContent.includes('Grade 5');
  await button(tree, 'Change…').dispatch('click'); await button(tree, 'Change…').dispatch('click'); await settle();
  out.dialogs = body.querySelectorAll('.modal').length;
""")
    assert out["shown"] == ["The lens is unknown. Knowledge from different lenses is kept separate, so measurements from other lenses will not be included."]
    assert out["put"] == 0 and out["closed"] is True and out["stripSame"] is True
    assert out["dialogs"] == 1                                                      # a second click while the dialog is open opens no second one


@node
def test_a_change_the_server_refuses_is_told_in_the_dialog_and_the_dialog_stays_open(tmp_path):
    out = run(tmp_path, """
  on('PUT /api/creation/context', () => refuse('the selected lens was not found; choose it again'));
  const tree = await screen();
  await button(tree, 'Change…').dispatch('click'); await settle();
  const box = dialog();
  await button(box, 'Apply').dispatch('click'); await settle();
  out.open = dialog() !== null;
  out.toast = body.querySelector('.toasts') ? body.querySelector('.toasts').textContent : '';
  out.strip = tree.querySelector('.work-context').textContent.includes('JPT 60');
""")
    assert out["open"] is True and "the selected lens was not found; choose it again" in out["toast"] and out["strip"] is True


@node
def test_a_context_that_lost_a_record_says_which_one_and_a_change_in_the_screen_reloads_what_each_result_needs(tmp_path):
    out = run(tmp_path, """
  S.context = {...S.context, stale: ['lens'], lens: null, lens_id: null, lens_basis: 'unknown'};
  const tree = await screen();
  out.note = tree.querySelector('.work-context').textContent;
  await fillPicture(tree);
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  const before = sent('GET', '/api/creation/readiness').length;
  await button(tree, 'Change…').dispatch('click'); await settle();
  await button(dialog(), 'Apply').dispatch('click'); await settle();
  out.reloaded = sent('GET', '/api/creation/readiness').length - before;
  out.focus = ctx.document.activeElement && ctx.document.activeElement.textContent;
""")
    assert "The previous selection is no longer available (lens); the current selection is shown." in out["note"] and "Unknown" in out["note"]
    assert out["reloaded"] == 4                                                     # all four results are asked again for the new context
    assert out["focus"] == "Change…"


@node
def test_an_opened_works_own_context_is_read_only_and_names_its_release_and_the_shared_choice_cannot_change_it(tmp_path):
    out = run(tmp_path, """
  const own = ctx.WorkContext.own({device: {title: 'Mopa 30'}, lens: {name: 'F-Theta', focal_length_mm: 100}, material: {name: 'Sheet', grade: 'Grade 2', batch: 'B7'},
    source: {kind: 'release', lab_name: 'Север', release_created_at: '2026-10-20T00:00:00Z', content_sha256: 'abcdef0123456789'}});
  body.append(own);
  out.text = own.textContent;
  out.buttons = own.querySelectorAll('button').length;
  const shared = await ctx.__screens.new.render({query: {}});
  out.sharedText = shared.querySelector('.work-context').textContent;
  const workshop = ctx.WorkContext.own({device: {name: 'JPT'}, lens: null, material: null, source: null});
  out.plain = workshop.textContent;
""")
    for word in ("Mopa 30", "F-Theta", "Sheet", "Grade 2", "batch B7", "Север", "выпуск от 2026-10-20", "Recorded with this work. The shared selection for new work does not change it."):
        assert word in out["text"]
    assert out["buttons"] == 0                                                      # nothing here can change the work's own context
    assert "JPT 60" in out["sharedText"] and "Mopa 30" not in out["sharedText"]
    assert out["plain"].startswith("This work’s settings") and "LensUnknownStockNot selectedMeasurementsThis workshop’s measurements" in out["plain"]


# -- REQ-002: missing setup and measurements, the gate and the starter test ---------------------------------------------------------------------
async_gate = """
  const tree = await screen();
  await fillPicture(tree);
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  await tiles(tree)[__TILE__].dispatch('click');
  await button(tree, 'Дальше →').dispatch('click'); await settle();
"""


@node
def test_without_measurements_the_screen_names_a_concrete_starter_test_and_the_result_it_unlocks_and_creates_no_work(tmp_path):
    out = run(tmp_path, """
  S.readiness.photo = {result: 'photo', ready: false, missing: ['measurements'], context: S.context, measured: 0,
    starter_test: {result: 'photo', needs_rig: true, becomes: 'measured_scale', device_id: 1, material_id: 3, test_type: 'grey_scales', guide: null}};
""" + async_gate.replace("__TILE__", "1") + """
  const gate = labelled(tree, 'Чего не хватает');
  out.gate = gate.textContent;
  out.links = gate.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  out.create = button(tree, FORWARD).disabled;
  await button(tree, FORWARD).dispatch('click'); await settle();
  out.works = [sent('POST', '/api/photo-works').length, sent('POST', '/api/vector').length, sent('POST', '/api/creation/drafts/1/complete').length];
  await button(tree, 'Создать тест «Шкалы серого»…').dispatch('click'); await settle();
  out.dialog = dialog() && dialog().querySelector('h3').textContent;
  await wait(700); await settle();
  out.waiting = JSON.parse(sent('PUT', '/api/creation/drafts/1').pop().form.state).waiting;
""")
    assert "пока не хватает" in out["gate"] and "Нужны измерения" in out["gate"] and "Нужна измеренная шкала серого этого лазера, линзы и титана." in out["gate"]
    assert "Начальный тест: Шкалы серого" in out["gate"]
    assert "Когда измерения теста будут приняты, появится измеренная шкала серого, и фотогравировка станет доступна." in out["gate"]
    assert ["Добавить установку съёмки", "#/setup?tab=rigs"] in out["links"]                  # a photography setup is missing: the way to add it
    assert "Введённое сохранено в задаче" in out["gate"]
    assert out["create"] is True and out["works"] == [0, 0, 0]                              # nothing is created while the gate is closed
    assert out["dialog"] == "Создать экспериментальную плату"
    assert out["waiting"] == {"for": "starter_test", "result": "photo"}                     # the task remembers what the person went to do


@node
def test_a_vector_starter_test_is_made_by_the_experiment_guide_and_a_refusal_leaves_the_screen_as_it_was(tmp_path):
    out = run(tmp_path, """
  S.readiness.silhouette = {result: 'silhouette', ready: false, missing: ['measurements'], context: S.context, measured: 0,
    starter_test: {result: 'silhouette', needs_rig: false, becomes: 'validated_recipes', device_id: 1, material_id: 3, test_type: 'calibration', task: 'fill',
      guide: {status: 'needs_test', message: 'Нет рецептов заливки', next_step: 'Создайте калибровочную плату', pending_plan_id: null}}};
""" + async_gate.replace("__TILE__", "2") + """
  out.card = labelled(tree, 'Чего не хватает').textContent;
  on('POST /api/creation/starter-plate', () => refuse('no plate is proposed for this task yet'));
  await button(tree, 'Создать начальный тест').dispatch('click'); await settle();
  out.refused = [body.querySelector('.toasts').textContent.includes('no plate is proposed') || body.querySelector('.toasts').textContent.length > 0, button(tree, 'Создать начальный тест').disabled];
  on('POST /api/creation/starter-plate', (req) => reply(201, {plan_id: 31, name: 'Плата заливки'}));
  await button(tree, 'Создать начальный тест').dispatch('click'); await settle();
  out.made = labelled(tree, 'Чего не хватает').textContent;
  out.link = tree.querySelectorAll('a').filter((a) => a.textContent === 'Открыть тест').map((a) => a.getAttribute('href'));
  out.posts = sent('POST', '/api/creation/starter-plate').map((r) => r.json);
  out.works = sent('POST', '/api/vector').length;
""")
    assert "Начальный тест: Калибровка — Нет рецептов заливки" in out["card"] and "Создайте калибровочную плату" in out["card"]
    assert "Когда измерения теста будут приняты, они попадут в измеренные цвета этого лазера, линзы и титана." in out["card"]
    assert "может понадобиться повторить тест" in out["card"]                              # honest: a recipe enters a work when it is validated
    assert out["refused"][1] is False                                                       # the button is usable again after a refusal
    assert "Тест создан: Плата заливки." in out["made"] and out["link"] == ["#/experiment/plan-31"]
    assert out["posts"] == [{"result": "silhouette"}, {"result": "silhouette"}] and out["works"] == 0


@node
def test_a_missing_laser_titanium_or_lens_is_a_gate_with_a_way_to_add_it_and_the_task_remembers_it_waits_for_equipment(tmp_path):
    out = run(tmp_path, """
  S.readiness.lines = {result: 'lines', ready: false, missing: ['titanium', 'lens'], context: S.context, measured: null, starter_test: null};
""" + async_gate.replace("__TILE__", "3") + """
  const gate = labelled(tree, 'Чего не хватает');
  out.items = gate.querySelectorAll('li').map((li) => [li.textContent, li.querySelector('a').getAttribute('href')]);
  out.create = button(tree, 'Создать работу').disabled;
  await wait(700); await settle();
  out.waiting = JSON.parse(sent('PUT', '/api/creation/drafts/1').pop().form.state).waiting;
  out.kept = [labelled(tree, 'Название работы') === undefined, tree.querySelector('img') !== null];
""")
    assert out["items"] == [["Не добавлена заготовка титана. Добавить заготовку", "#/setup"],
                            ["На выбранном лазере нет линзы: тест гравируется через неё. Установить линзу", "#/devices"]]
    assert out["create"] is True
    assert out["waiting"] == {"for": "equipment", "result": "lines"}


@node
def test_a_readiness_check_that_fails_is_told_and_does_not_open_the_gate(tmp_path):
    out = run(tmp_path, """
  const tree = await screen();
  await fillPicture(tree);
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  await tiles(tree)[0].dispatch('click');
  on('GET /api/creation/readiness', () => refuse('workshop is busy', 500));
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.alerts = alerts(tree);
  out.create = button(tree, 'Создать работу').disabled;
""")
    assert len(out["alerts"]) == 1 and out["alerts"][0].startswith("Не удалось проверить, чего не хватает: workshop is busy") and out["create"] is True


# -- REQ-002 + DEC-001: the unfinished task survives a restart ------------------------------------------------------------------------------
@node
def test_a_restart_finds_the_task_where_it_was_left_with_picture_name_size_result_and_settings_and_says_the_missing_part_is_added(tmp_path):
    out = run(tmp_path, """
  S.drafts.push({id: 5, status: 'open', flow: 'new', name: 'Портрет Инны', image: {name: 'portrait.png', type: 'image/png', size: 5},
    state: {v: 1, step: 'method', result: 'silhouette', name: 'Портрет Инны', width_mm: '72', waiting: {for: 'starter_test', result: 'silhouette'},
      method: {tolerance: '0.2', grey: '120', clean: false, markers: true}}});
  S.seq = 6;
  const tree = await screen({draft: '5'});
  out.head = heading(tree);
  out.thumb = tree.querySelectorAll('img').map((i) => i.getAttribute('src'));
  out.summary = tree.querySelector('.card').textContent;
  out.note = tree.querySelectorAll('p').filter((p) => p.getAttribute('role') === 'status').map((p) => p.textContent);
  out.focus = ctx.document.activeElement && ctx.document.activeElement.textContent;
  out.method = tree.querySelector('details').querySelectorAll('input').map((i) => [i.getAttribute('type'), i.value, i.checked]);
  out.picturesSent = ctx.requests.filter((r) => r.form && r.form.picture).length;
  out.create = button(tree, 'Создать работу').disabled;
  await button(tree, '← Назад').dispatch('click'); await settle();
  await button(tree, '← Назад').dispatch('click'); await settle();
  out.back = [labelled(tree, 'Название работы').value, labelled(tree, 'Ширина на титане, мм').value, tree.querySelector('.file-name').textContent,
    tree.querySelectorAll('img').filter((i) => i.parentNode.localName === 'figure').map((i) => i.getAttribute('alt'))];
""")
    assert out["head"] == "Новая работа · шаг 3 из 3: Настройки и создание"
    assert out["thumb"][0] == "/api/creation/drafts/5/picture?v=0"                        # the picture comes from the workshop, not from the person again
    assert "Портрет Инны" in out["summary"] and "Силуэт · ширина 72 мм" in out["summary"]
    assert "Недостающее добавлено: можно создавать работу. Картинка, название и настройки остались как были." in out["note"]
    assert out["focus"] == out["head"]                                                    # the keyboard returns to the heading of the step
    assert ["number", "0.2", False] in out["method"] and ["number", "120", False] in out["method"]
    assert out["picturesSent"] == 0 and out["create"] is False
    assert out["back"][:2] == ["Портрет Инны", "72"] and "portrait.png" in out["back"][2] and out["back"][3] == ["Картинка задачи: portrait.png"]


@node
def test_a_task_without_its_picture_starts_at_the_first_step_and_a_finished_or_unknown_task_is_not_offered(tmp_path):
    out = run(tmp_path, """
  S.drafts.push({id: 1, status: 'open', flow: 'new', name: 'Без картинки', image: null, state: {v: 1, step: 'result', result: 'colour', name: 'Без картинки', width_mm: '50'}});
  S.drafts.push({id: 2, status: 'completed', flow: 'new', name: 'Готовая', image: null, state: {}});
  S.seq = 3;
  const first = await screen({draft: '1'});
  out.noPicture = [heading(first), labelled(first, 'Название работы').value, labelled(first, 'Ширина на титане, мм').value];
  first.remove();
  const done = await screen({draft: '2'});
  out.done = [heading(done), done.textContent.includes('Эта задача уже закончена или отменена')];
  done.remove();
  const unknown = await screen({draft: '44'});
  out.unknown = unknown.textContent.includes('Эта задача уже закончена или отменена');
""")
    assert out["noPicture"] == ["Новая работа · шаг 1 из 3: Картинка и размер", "Без картинки", "50"]
    assert out["done"] == ["Новая работа · шаг 1 из 3: Картинка и размер", True] and out["unknown"] is True


@node
def test_other_open_tasks_are_offered_on_a_new_creation_and_each_can_be_resumed_or_cancelled_after_a_confirmation(tmp_path):
    out = run(tmp_path, """
  S.drafts.push({id: 1, status: 'open', flow: 'new', name: 'Первая', image: {name: 'a.png'}, state: {step: 'result', result: 'lines'}});
  S.drafts.push({id: 2, status: 'open', flow: 'new', name: 'Вторая', image: {name: 'b.png'}, state: {}});
  S.seq = 3;
  const tree = await screen();
  const list = labelled(tree, 'Незавершённые задачи');
  out.list = list.textContent;
  await list.querySelectorAll('button').filter((b) => b.textContent === 'Продолжить')[0].dispatch('click');
  out.went = [...ctx.__went];
  await list.querySelectorAll('button').filter((b) => b.textContent === 'Отменить задачу')[0].dispatch('click'); await settle();
  out.confirm = dialog().querySelector('h3').textContent;
  out.discardedBefore = sent('POST', '/api/creation/drafts/2/discard').length;
  await button(dialog(), 'Cancel').dispatch('click'); await settle();
  out.discardedAfterCancel = ctx.requests.filter((r) => r.path.endsWith('/discard')).length;
  await list.querySelectorAll('button').filter((b) => b.textContent === 'Отменить задачу')[0].dispatch('click'); await settle();
  await button(dialog(), 'Отменить задачу').dispatch('click'); await settle();
  out.discarded = ctx.requests.filter((r) => r.path.endsWith('/discard')).map((r) => r.path);
  out.open = open().map((d) => d.id);
""")
    assert "Незавершённые задачи: 2" in out["list"] and "Вторая" in out["list"] and "Первая" in out["list"]
    assert out["went"] == ["/new?draft=2"]                                                  # the newest first
    assert out["confirm"] == "Отменить задачу «Вторая»?" and out["discardedAfterCancel"] == 0
    assert out["discarded"] == ["/api/creation/drafts/2/discard"] and out["open"] == [1]


@node
def test_a_task_that_cannot_be_saved_is_told_beside_the_form_and_the_form_keeps_what_was_typed(tmp_path):
    out = run(tmp_path, """
  S.refuseDraft = 'the picture is empty';
  const tree = await screen();
  await fillPicture(tree, {name: 'Портрет'});
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.alerts = alerts(tree);
  out.step = heading(tree);
  out.kept = [labelled(tree, 'Название работы').value, labelled(tree, 'Ширина на титане, мм').value];
  S.refuseDraft = null;
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  out.later = heading(tree);
  S.refuseUpdate = 'the picture of this unfinished task is not kept';
  const name = labelled(tree, 'Название работы');
  await button(tree, '← Назад').dispatch('click'); await settle();
  labelled(tree, 'Название работы').value = 'Другое'; await labelled(tree, 'Название работы').dispatch('input');
  await wait(700); await settle();
  out.note = tree.querySelectorAll('p').filter((p) => p.getAttribute('role') === 'status').map((p) => p.textContent);
""")
    assert out["alerts"] == ["Could not submit: the picture is empty. Your entries remain in the form; correct them and submit again."] and out["step"].startswith("Новая работа · шаг 1 из 3")
    assert out["kept"] == ["Портрет", "80"] and out["later"].startswith("Новая работа · шаг 2 из 3")
    assert any(n.startswith("Задача не сохранена: the picture of this unfinished task is not kept") for n in out["note"])


# -- creating the work, completing the task ---------------------------------------------------------------------------------------------------
create_path = """
  const tree = await screen();
  await fillPicture(tree, {name: 'Портрет Инны', width: '72'});
  await button(tree, 'Дальше →').dispatch('click'); await settle();
  await tiles(tree)[__TILE__].dispatch('click');
  await button(tree, 'Дальше →').dispatch('click'); await settle();
"""


@node
def test_creating_a_vector_work_sends_the_context_and_the_settings_then_closes_the_task_and_opens_the_work(tmp_path):
    out = run(tmp_path, create_path.replace("__TILE__", "0") + """
  const colours = tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'number' && i.getAttribute('max') === '29');
  colours.value = '9';
  await button(tree, 'Создать работу').dispatch('click'); await settle();
  const order = ctx.requests.filter((r) => ['POST', 'GET'].includes(r.method) && /vector$|complete$|picture$/.test(r.path)).map((r) => r.method + ' ' + r.path);
  out.order = order;
  out.fields = Object.fromEntries(sent('POST', '/api/vector')[0].body.items);
  out.complete = sent('POST', '/api/creation/drafts/1/complete')[0].json;
  out.went = [...ctx.__went];
  out.open = open().length;
  out.bar = ctx.document.body.querySelector('.creation-bar').hidden;
""")
    assert out["order"] == ["GET /api/creation/drafts/1/picture", "POST /api/vector", "POST /api/creation/drafts/1/complete"]       # the work first, then the task
    f = out["fields"]
    assert (f["device_id"], f["lens_id"], f["material_id"], f["name"], f["width_mm"], f["strategy"]) == ("1", "2", "3", "Портрет Инны", "72", "photo")
    assert f["n_colors"] == "9" and f["algorithm"] == "slic" and f["detail"] == "medium" and f["image"] == {"file": "portrait.png", "size": 10}
    assert "threshold" not in f                                                             # the delta E tolerance comes from the rules unless the person types one
    assert out["complete"] == {"work_kind": "vector", "work_id": 99} and out["went"] == ["/vector?plan=99"] and out["open"] == 0


@node
def test_silhouette_and_lines_use_the_trace_settings_and_a_photo_work_is_made_on_the_scale_of_the_shared_laser_lens_and_titanium(tmp_path):
    out = run(tmp_path, create_path.replace("__TILE__", "2") + """
  const grey = tree.querySelectorAll('input').find((i) => i.getAttribute('placeholder') === 'авто (Оцу)');
  grey.value = '110';
  await button(tree, 'Создать работу').dispatch('click'); await settle();
  out.silhouette = Object.fromEntries(sent('POST', '/api/vector')[0].body.items);
""")
    s = out["silhouette"]
    assert s["strategy"] == "fill" and s["grey_threshold"] == "110" and s["clean"] == "true" and "n_colors" not in s
    out = run(tmp_path, create_path.replace("__TILE__", "3") + """
  await button(tree, 'Создать работу').dispatch('click'); await settle();
  out.lines = Object.fromEntries(sent('POST', '/api/vector')[0].body.items);
""")
    assert out["lines"]["strategy"] == "line"
    scales = [{"mode": {"device_id": 2, "lens_id": 2, "material_id": 3, "key": "other laser"}}, {"mode": {"device_id": 1, "lens_id": 2, "material_id": 3, "key": "mine"}}]
    out = run(tmp_path, f"S.scales = {json.dumps(scales)};" + create_path.replace("__TILE__", "1") + """
  await ask(tree);
  await keep().dispatch('click'); await settle(); await pending;
  out.photo = Object.fromEntries(sent('POST', '/api/photo-works')[0].body.items);
  out.scalesAsked = sent('GET', '/api/grey-scales')[0].url;
  out.went = [...ctx.__went];
  out.complete = sent('POST', '/api/creation/drafts/1/complete')[0].json;
""")
    assert json.loads(out["photo"]["scale"])["key"] == "mine"                              # the scale of the context's own laser, not the first one listed
    assert out["photo"]["name"] == "Портрет Инны" and out["photo"]["width_mm"] == "72" and "source" not in out["photo"]
    assert out["scalesAsked"] == "/api/grey-scales?device_id=1&lens_id=2&material_id=3&row_mm=72"
    assert out["went"] == ["/photo-engraving?work=77"] and out["complete"] == {"work_kind": "photo", "work_id": 77}


@node
def test_a_photo_work_without_a_scale_of_the_context_is_not_made_on_another_laser(tmp_path):
    out = run(tmp_path, "S.scales = [{mode: {device_id: 2, lens_id: 2, material_id: 3}}];" + create_path.replace("__TILE__", "1") + """
  await button(tree, FORWARD).dispatch('click'); await settle();
  out.alerts = alerts(tree);
  out.posts = sent('POST', '/api/photo-works').length;
  out.completed = sent('POST', '/api/creation/drafts/1/complete').length;
  out.open = open().length;
  out.dialog = dialog() !== null;
  out.again = button(tree, FORWARD).disabled;
""")
    assert out["alerts"][0].startswith("Для выбранных лазера, линзы и титана нет измеренной шкалы серого")
    assert out["posts"] == 0 and out["completed"] == 0 and out["open"] == 1 and out["again"] is False and out["dialog"] is False   # no work, so no question either


@node
def test_a_lab_release_in_the_context_is_sent_as_the_source_of_a_photo_work_and_a_colour_work(tmp_path):
    release = {"release_id": "r-1", "laser": "L1", "lens": "N1", "material": "M1", "label": "Север"}
    out = run(tmp_path, f"S.context.source = {json.dumps(release)};" + create_path.replace("__TILE__", "1") + """
  await ask(tree);
  out.photo = Object.fromEntries(sent('POST', '/api/photo-works')[0].body.items);
""")
    assert json.loads(out["photo"]["source"]) == {"release_id": "r-1", "laser": "L1", "lens": "N1", "material": "M1", "device_id": 1, "lens_id": 2}
    assert "scale" not in out["photo"]
    out = run(tmp_path, f"S.context.source = {json.dumps(release)};" + create_path.replace("__TILE__", "0") + """
  await button(tree, 'Создать работу').dispatch('click'); await settle();
  out.vector = Object.fromEntries(sent('POST', '/api/vector')[0].body.items);
""")
    assert json.loads(out["vector"]["source"]) == {"release_id": "r-1", "laser": "L1", "lens": "N1", "material": "M1"}      # the label is for people, not for the server


@node
def test_a_work_the_server_refuses_leaves_the_task_open_and_the_form_as_it_was_and_a_repeated_click_makes_one_work(tmp_path):
    out = run(tmp_path, "S.refuseVector = 'the image could not be read';" + create_path.replace("__TILE__", "0") + """
  await button(tree, 'Создать работу').dispatch('click'); await settle();
  out.alerts = alerts(tree);
  out.completed = sent('POST', '/api/creation/drafts/1/complete').length;
  out.open = open().map((d) => d.id);
  out.enabled = !button(tree, 'Создать работу').disabled;
  out.went = [...ctx.__went];
  S.refuseVector = null;
  let release; S.vectorHold = new Promise((r) => { release = r; });
  const make = button(tree, 'Создать работу');
  const one = make.dispatch('click'); const two = make.dispatch('click');
  release(); await one; await two; await settle();
  out.posts = sent('POST', '/api/vector').length;
  out.completedTwice = sent('POST', '/api/creation/drafts/1/complete').length;
""")
    assert out["alerts"] == ["Could not submit: the image could not be read. Your entries remain in the form; correct them and submit again."]
    assert out["completed"] == 0 and out["open"] == [1] and out["enabled"] is True and out["went"] == []
    assert out["posts"] == 2 and out["completedTwice"] == 1                                 # one refused, one made; the second click while busy sent nothing


@node
def test_when_the_task_cannot_be_closed_the_work_still_exists_and_opens_and_the_person_is_told_to_cancel_the_leftover_task(tmp_path):
    out = run(tmp_path, "S.refuseComplete = 'database is locked';" + create_path.replace("__TILE__", "0") + """
  await button(tree, 'Создать работу').dispatch('click'); await settle();
  out.went = [...ctx.__went];
  out.toast = body.querySelector('.toasts').textContent;
  out.posts = sent('POST', '/api/vector').length;
""")
    assert out["went"] == ["/vector?plan=99"] and out["posts"] == 1
    assert "Работа создана, но задача осталась в списке незавершённых: отмените её" in out["toast"]


# -- BUG-003 inside the wizard: a photograph asks «Какая гравировка?» before the work is kept ------------------------------------------------
photo_path = "S.scales = [{mode: {device_id: 1, lens_id: 2, material_id: 3, key: 'mine'}}];" + create_path.replace("__TILE__", "1")


@node
def test_a_photograph_asks_which_kind_of_engraving_before_it_is_kept_with_the_persons_picture_in_every_kind(tmp_path):
    out = run(tmp_path, photo_path + """
  out.label = button(tree, FORWARD).textContent;
  out.line = tree.textContent.includes('Вид гравировки: Grayscale');
  await ask(tree);
  out.title = dialog().querySelector('h3').textContent;
  out.names = kindNames();
  out.pictures = kinds().map((k) => k.querySelector('img').getAttribute('src'));
  out.alts = kinds().map((k) => k.querySelector('img').getAttribute('alt'));
  out.marked = kinds().map((k) => k.getAttribute('aria-pressed'));
  out.keepLabel = keep().textContent;
  out.before = [sent('POST', '/api/photo-works').length, sent('GET', '/api/photo-works/77/kinds').length, sent('POST', '/api/creation/drafts/1/complete').length, [...ctx.__went]];
  await kinds()[2].dispatch('click'); await settle();
  out.after = [kinds().map((k) => k.getAttribute('aria-pressed')), keep().textContent];
  await keep().dispatch('click'); await settle(); await pending;
  const order = ctx.requests.map((r) => r.method + ' ' + r.path);
  out.saved = sent('POST', '/api/photo-works/77/settings').map((r) => r.json);
  out.order = [order.indexOf('POST /api/photo-works/77/settings') < order.indexOf('POST /api/creation/drafts/1/complete'), order.indexOf('POST /api/photo-works') < order.indexOf('GET /api/photo-works/77/kinds')];
  out.complete = sent('POST', '/api/creation/drafts/1/complete')[0].json;
  out.went = [...ctx.__went];
  out.deleted = S.deleted || [];
  out.dialogGone = dialog() === null;
""")
    assert out["label"] == "Дальше: какая гравировка →" and out["line"] is True                       # the button says what comes next; the kind is told on the step
    assert out["title"] == "Новая работа · какая гравировка?" and len(out["names"]) == 4
    assert out["pictures"] == [f"/api/photo-works/77/kinds/{k}.png" for k in ("grayscale", "threshold", "dither", "sketch")]
    assert all(alt.startswith("Картинка в виде «") for alt in out["alts"])
    assert out["marked"] == ["true", "false", "false", "false"] and out["keepLabel"] == f"Create in “{out['names'][0]}”"       # grayscale is the start
    assert out["before"] == [1, 1, 0, []]                       # the work exists to show the kinds, but is not kept: no task closed, no screen left
    assert out["after"] == [["false", "false", "true", "false"], f"Create in “{out['names'][2]}”"]
    assert out["saved"] == [{"kind": "dither"}] and out["order"] == [True, True]                  # the chosen kind reaches the work before the task is closed
    assert out["complete"] == {"work_kind": "photo", "work_id": 77} and out["went"] == ["/photo-engraving?work=77"]
    assert out["deleted"] == [] and out["dialogGone"] is True


@node
def test_a_photograph_kept_in_grayscale_saves_no_kind_and_is_closed_and_opened(tmp_path):
    out = run(tmp_path, photo_path + """
  await ask(tree);
  await keep().dispatch('click'); await settle(); await pending;
  out.saved = sent('POST', '/api/photo-works/77/settings').length;
  out.complete = sent('POST', '/api/creation/drafts/1/complete')[0].json;
  out.went = [...ctx.__went];
""")
    assert out["saved"] == 0 and out["complete"] == {"work_kind": "photo", "work_id": 77} and out["went"] == ["/photo-engraving?work=77"]


@node
def test_going_back_from_the_question_deletes_the_work_keeps_the_picture_and_settings_and_remembers_the_marked_kind_for_the_next_time(tmp_path):
    out = run(tmp_path, photo_path + """
  const forward = button(tree, FORWARD);
  await ask(tree);
  out.names = kindNames();
  await kinds()[3].dispatch('click'); await settle();
  await dialogButton('← Back').dispatch('click'); await settle(); await pending;
  out.back = [S.deleted || [], sent('POST', '/api/creation/drafts/1/complete').length, [...ctx.__went], dialog() === null, open().map((d) => d.id)];
  out.form = [heading(tree), labelled(tree, 'Название работы') === undefined, tree.textContent.includes('Портрет Инны'), tree.textContent.includes('ширина 72 мм')];
  out.enabled = !button(tree, FORWARD).disabled;
  out.focus = ctx.document.activeElement === button(tree, FORWARD);
  out.line = tree.textContent.includes('Вид гравировки: ' + out.names[3]);
  out.saved = JSON.parse(sent('PUT', '/api/creation/drafts/1').pop().form.state);
  await ask(tree);
  out.again = [sent('POST', '/api/photo-works').length, kinds().map((k) => k.getAttribute('aria-pressed')), keep().textContent];
  await keep().dispatch('click'); await settle(); await pending;
  out.kept = [sent('POST', '/api/photo-works/77/settings').map((r) => r.json), (S.deleted || []).length, [...ctx.__went]];
""")
    assert out["back"] == [[77], 0, [], True, [1]]                       # the work is deleted, nothing is closed, the task stays open
    assert out["form"][0] == "Новая работа · шаг 3 из 3: Настройки и создание" and out["form"][2] is True and out["form"][3] is True
    assert out["line"] is True                                              # the step names the kind the person marked
    assert out["enabled"] is True and out["focus"] is True                  # the keyboard returns to the button that opened the question
    assert out["saved"]["kind"] == "sketch" and out["saved"]["hold"] is None and out["saved"]["width_mm"] == "72" and out["saved"]["name"] == "Портрет Инны"
    assert out["again"][0] == 2 and out["again"][1] == ["false", "false", "false", "true"]               # a new work for the new question, the same kind marked
    assert out["kept"] == [[{"kind": "sketch"}], 1, ["/photo-engraving?work=77"]]


@node
def test_leaving_the_question_by_the_cross_or_escape_leaves_no_work_and_the_form_as_it_was(tmp_path):
    out = run(tmp_path, photo_path + """
  await ask(tree);
  await dialog().querySelectorAll('button').find((b) => b.getAttribute('aria-label') === 'Close').dispatch('click'); await settle(); await pending;
  out.cross = [S.deleted || [], sent('POST', '/api/creation/drafts/1/complete').length, dialog() === null, !button(tree, FORWARD).disabled, [...ctx.__went]];
  await ask(tree);
  await Promise.all(ctx.__keys.map((fn) => fn({key: 'Escape', type: 'keydown', target: body, preventDefault() {}}))); await settle(); await pending;
  out.escape = [S.deleted, dialog() === null, !button(tree, FORWARD).disabled, sent('POST', '/api/photo-works').length];
  out.hold = JSON.parse(sent('PUT', '/api/creation/drafts/1').pop().form.state).hold;
""")
    assert out["cross"] == [[77], 0, True, True, []]
    assert out["escape"] == [[77, 77], True, True, 2] and out["hold"] is None


@node
def test_a_kind_that_cannot_be_saved_is_told_keeps_the_question_open_and_the_work_unkept_and_a_retry_keeps_it(tmp_path):
    out = run(tmp_path, "S.refuseKind = 'the kind could not be saved';" + photo_path + """
  await ask(tree);
  await kinds()[1].dispatch('click'); await settle();
  await keep().dispatch('click'); await settle();
  out.refused = [dialog() !== null, sent('POST', '/api/creation/drafts/1/complete').length, S.deleted || [], [...ctx.__went], body.querySelector('.toasts').textContent];
  out.hold = JSON.parse(sent('PUT', '/api/creation/drafts/1').pop().form.state).hold;
  S.refuseKind = null;
  await keep().dispatch('click'); await settle(); await pending;
  out.kept = [sent('POST', '/api/photo-works/77/settings').length, sent('POST', '/api/creation/drafts/1/complete')[0].json, [...ctx.__went], S.deleted || []];
""")
    assert out["refused"][0] is True and out["refused"][1] == 0 and out["refused"][2] == [] and out["refused"][3] == []
    assert "the kind could not be saved" in out["refused"][4]
    assert out["hold"] == {"id": 77, "created_at": "T0"}                  # still not kept, so the task still points at the work made for the question
    assert out["kept"] == [2, {"work_kind": "photo", "work_id": 77}, ["/photo-engraving?work=77"], []]


@node
def test_the_task_points_at_the_work_made_for_the_question_until_it_is_kept_and_then_no_longer(tmp_path):
    out = run(tmp_path, photo_path + """
  await ask(tree);
  const states = () => sent('PUT', '/api/creation/drafts/1').map((r) => JSON.parse(r.form.state).hold);
  out.during = states().pop();
  await keep().dispatch('click'); await settle(); await pending;
  const all = states();
  out.after = all.pop();
  const order = ctx.requests.map((r) => r.method + ' ' + r.path);
  out.beforeComplete = order.lastIndexOf('PUT /api/creation/drafts/1') < order.indexOf('POST /api/creation/drafts/1/complete');
""")
    assert out["during"] == {"id": 77, "created_at": "T0"} and out["after"] is None and out["beforeComplete"] is True


@node
def test_a_window_closed_in_the_question_gets_its_leftover_work_deleted_when_the_task_is_opened_again_but_only_that_very_work(tmp_path):
    draft = """
  S.scales = [{mode: {device_id: 1, lens_id: 2, material_id: 3, key: 'mine'}}];
  S.drafts.push({id: 5, status: 'open', flow: 'new', name: 'Портрет Инны', image: {name: 'portrait.png', type: 'image/png', size: 5},
    state: {v: 1, step: 'method', result: 'photo', name: 'Портрет Инны', width_mm: '72', kind: 'dither', hold: {id: 77, created_at: 'T0'}}});
  S.seq = 6;
"""
    out = run(tmp_path, draft + """
  const tree = await screen({draft: '5'});
  await wait(700); await settle();                                      // the task is saved a moment after the change
  out.deleted = S.deleted || [];
  out.note = tree.querySelectorAll('p').filter((p) => p.getAttribute('role') === 'status').map((p) => p.textContent);
  out.saved = JSON.parse(sent('PUT', '/api/creation/drafts/5').pop().form.state);
  await ask(tree);
  out.line = tree.textContent.includes('Вид гравировки: ' + kindNames()[2]);
  out.marked = kinds().map((k) => k.getAttribute('aria-pressed'));
""")
    assert out["deleted"] == [77] and any("не было закончено" in n for n in out["note"])
    assert out["saved"]["hold"] is None and out["saved"]["kind"] == "dither" and out["line"] is True
    assert out["marked"] == ["false", "false", "true", "false"]            # the kind the person had marked is marked again
    other = run(tmp_path, "S.photoStamp = 'T9';" + draft + """
  const tree = await screen({draft: '5'});
  await wait(700); await settle();
  out.deleted = S.deleted || [];
  out.note = tree.querySelectorAll('p').filter((p) => p.getAttribute('role') === 'status').map((p) => p.textContent);
  out.hold = JSON.parse(sent('PUT', '/api/creation/drafts/5').pop().form.state).hold;
""")
    assert other["deleted"] == [] and not any("не было закончено" in n for n in other["note"]) and other["hold"] is None    # another work now has that number: it is not touched
    gone = run(tmp_path, "S.photoGone = true;" + draft + """
  const tree = await screen({draft: '5'});
  await settle();
  out.deleted = S.deleted || [];
  out.alerts = alerts(tree);
  out.head = heading(tree);
""")
    assert gone["deleted"] == [] and gone["alerts"] == [] and gone["head"] == "Новая работа · шаг 3 из 3: Настройки и создание"


@node
def test_a_delta_e_tolerance_the_rules_do_not_hold_is_asked_for_before_anything_is_sent_and_saved_once_when_typed(tmp_path):
    out = run(tmp_path, "S.tolerance = null;" + create_path.replace("__TILE__", "0") + """
  out.open = tree.querySelector('details').getAttribute('open');
  out.hint = tree.querySelector('details').textContent;
  await button(tree, 'Создать работу').dispatch('click'); await settle();
  out.alerts = [fieldError(tree, 'Допуск ΔE')];                                       // beside the box, not above the buttons only
  out.nothing = [sent('POST', '/api/vector').length, sent('PUT', '/api/rules').length];
  const thr = tree.querySelectorAll('input').find((i) => (i.getAttribute('placeholder') || '').includes('задайте'));
  thr.value = '4'; await thr.dispatch('input');
  await button(tree, 'Создать работу').dispatch('click'); await settle();
  out.rules = sent('PUT', '/api/rules').map((r) => r.json);
  out.created = Object.fromEntries(sent('POST', '/api/vector')[0].body.items).threshold;
""")
    assert out["open"] is not None                                                          # the block that must be filled is open, not hidden
    assert "допуск не сохранён — задайте его" in out["hint"]
    assert out["alerts"] == ["Задайте допуск ΔE: для этого лазера с линзой он не сохранён"] and out["nothing"] == [0, 0]
    assert out["rules"] == [{"device_id": 1, "lens_id": 2, "delta_tolerance": 4}] and out["created"] == "4"


@node
def test_cancelling_the_task_from_the_screen_asks_first_deletes_nothing_made_and_leaves_no_half_made_work(tmp_path):
    out = run(tmp_path, create_path.replace("__TILE__", "0") + """
  await button(tree, 'Отменить задачу').dispatch('click'); await settle();
  out.asked = dialog().querySelector('h3').textContent + ' / ' + dialog().textContent.includes('Созданные работы не затрагиваются');
  await button(dialog(), 'Cancel').dispatch('click'); await settle();
  out.after = [sent('POST', '/api/creation/drafts/1/discard').length, open().length];
  await button(tree, 'Отменить задачу').dispatch('click'); await settle();
  await button(dialog(), 'Отменить задачу').dispatch('click'); await settle();
  out.discarded = [sent('POST', '/api/creation/drafts/1/discard').length, open().length, [...ctx.__went]];
  out.works = [sent('POST', '/api/vector').length, sent('POST', '/api/photo-works').length, ctx.requests.filter((r) => r.method === 'DELETE').length];
""")
    assert out["asked"] == "Отменить задачу «Портрет Инны»? / true"
    assert out["after"] == [0, 1] and out["discarded"] == [1, 0, ["/vector"]] and out["works"] == [0, 0, 0]


# -- the bar of an unfinished task ------------------------------------------------------------------------------------------------------------
@node
def test_the_bar_offers_the_unfinished_task_on_any_screen_hides_on_the_creation_screen_and_follows_discard_and_completion(tmp_path):
    out = run(tmp_path, """
  const bar = body.querySelector('.creation-bar');
  await ctx.Creation.refreshBar(); await settle();
  out.none = [bar.hidden, body.classList.contains('has-creation-bar')];
  S.drafts.push({id: 3, status: 'open', flow: 'new', name: 'Портрет', image: {name: 'p.png'}, state: {step: 'method', result: 'photo', waiting: {for: 'starter_test', result: 'photo'}}});
  S.readiness.photo = {result: 'photo', ready: false, missing: ['measurements'], context: S.context, measured: 0, starter_test: {}};
  S.seq = 4;
  await ctx.Creation.refreshBar(); await settle();
  out.shown = [bar.hidden, bar.textContent, bar.getAttribute('aria-label'), body.classList.contains('has-creation-bar')];
  S.readiness.photo = undefined;
  await ctx.Creation.refreshBar(); await settle();
  out.ready = bar.textContent;
  ctx.location.hash = '#/new';
  await ctx.Creation.refreshBar(); await settle();
  out.onWizard = bar.hidden;
  ctx.location.hash = '#/vector?new=1';
  await ctx.Creation.refreshBar(); await settle();
  out.onVectorNew = bar.hidden;
  ctx.location.hash = '#/devices';
  await ctx.Creation.refreshBar(); await settle();
  await button(bar, 'Продолжить').dispatch('click');
  out.went = [...ctx.__went];
  await button(bar, 'Отменить задачу').dispatch('click'); await settle();
  await button(dialog(), 'Отменить задачу').dispatch('click'); await settle();
  out.afterDiscard = [bar.hidden, body.classList.contains('has-creation-bar')];
""")
    assert out["none"] == [True, False]
    assert out["shown"][0] is False and "Не закончена работа «Портрет»." in out["shown"][1] and "Ждёт стартовый тест и приём его измерений." in out["shown"][1]
    assert out["shown"][2] == "Незавершённая работа" and out["shown"][3] is True
    assert "Недостающее добавлено: можно продолжить." in out["ready"]
    assert out["onWizard"] is True and out["onVectorNew"] is True                            # the screen itself needs no reminder of itself
    assert out["went"] == ["/new?draft=3"] and out["afterDiscard"] == [True, False]


@node
def test_the_bar_says_how_many_tasks_are_open_and_a_failed_list_leaves_it_hidden_instead_of_breaking_the_page(tmp_path):
    out = run(tmp_path, """
  const bar = body.querySelector('.creation-bar');
  S.drafts.push({id: 1, status: 'open', flow: 'new', name: 'Первая', image: {name: 'a.png'}, state: {}});
  S.drafts.push({id: 2, status: 'open', flow: 'new', name: null, image: {name: 'second.png'}, state: {}});
  await ctx.Creation.refreshBar(); await settle();
  out.two = bar.textContent;
  on('GET /api/creation/drafts', () => refuse('workshop is busy', 500));
  await ctx.Creation.refreshBar(); await settle();
  out.failed = bar.hidden;
""")
    assert "Не закончена работа «second»." in out["two"] and "Всего незавершённых: 2" in out["two"] and out["failed"] is True


@node
def test_one_entry_starts_creation_from_anywhere_with_a_result_or_a_task_to_resume(tmp_path):
    out = run(tmp_path, """
  ctx.Creation.start(); ctx.Creation.start({result: 'photo'}); ctx.Creation.start({draft: 4}); ctx.Creation.start({draft: 4, result: 'lines'});
  out.went = [...ctx.__went];
  const tree = await screen({result: 'lines'});
  await settle();
  out.preselected = 'lines';
""")
    assert out["went"] == ["/new", "/new?result=photo", "/new?draft=4", "/new?draft=4&result=lines"]


# -- the older forms and the shared context ---------------------------------------------------------------------------------------------------
@node
def test_the_older_forms_start_from_the_shared_context_the_address_wins_and_a_context_that_cannot_be_read_changes_nothing(tmp_path):
    out = run(tmp_path, """
  out.shared = await ctx.App.contextStart({});
  out.address = await ctx.App.contextStart({device: '2', lens: 'unknown'});
  out.addressNoLens = (await ctx.App.contextStart({device: '2'})).lens;
  S.context.lens_id = null;
  out.unknownLens = (await ctx.App.contextStart({})).lens;
  on('GET /api/creation/context', () => refuse('workshop is busy', 500));
  out.unreadable = await ctx.App.contextStart({});
  out.remembered = await ctx.App.rememberContext({device: 1, lens: 'unknown', material: 4, source: null, label: null});
  on('PUT /api/creation/context', () => refuse('the selected laser was not found; choose it again'));
  out.refused = await ctx.App.rememberContext({device: 9, lens: 2, material: 3});
  out.put = sent('PUT', '/api/creation/context').map((r) => r.json);
""")
    assert out["shared"]["device"] == 1 and out["shared"]["lens"] == 2 and out["shared"]["material"] == 3
    assert out["address"]["device"] == "2" and out["address"]["lens"] == "unknown" and out["address"]["material"] == 3     # the address names the laser and lens only
    assert out["addressNoLens"] is None                                                       # a laser from the address takes its installed lens, not the shared lens
    assert out["unknownLens"] == "unknown"
    assert out["unreadable"]["device"] is None and out["unreadable"]["context"] is None
    assert out["refused"] is None                                                             # the work is made already: a refusal says nothing
    assert out["put"][0] == {"device_id": 1, "lens_id": None, "material_id": 4, "source": None} and out["put"][1] == {"device_id": 9, "lens_id": 2, "material_id": 3}
    assert "source" not in out["put"][1]                                                      # not named: the shared source is left as it is


@node
def test_a_form_without_a_titanium_remembers_the_laser_and_lens_only(tmp_path):
    out = run(tmp_path, """
  await ctx.App.rememberContext({device: 2, lens: 2});
  out.put = sent('PUT', '/api/creation/context').map((r) => r.json);
""")
    assert out["put"] == [{"device_id": 2, "lens_id": 2}]


@node
def test_an_older_form_hands_over_to_the_creation_screen_only_when_the_server_says_the_result_cannot_be_made(tmp_path):
    out = run(tmp_path, """
  out.ready = [await ctx.App.handOverToCreation('photo'), [...ctx.__went]];
  S.readiness.photo = {result: 'photo', ready: false, missing: ['measurements'], context: S.context, measured: 0, starter_test: {}};
  out.notReady = [await ctx.App.handOverToCreation('photo'), [...ctx.__went]];
  on('GET /api/creation/readiness', () => reply(200, {}));
  out.odd = [await ctx.App.handOverToCreation('photo'), ctx.__went.length];
  on('GET /api/creation/readiness', () => refuse('workshop is busy', 500));
  out.failed = [await ctx.App.handOverToCreation('photo'), ctx.__went.length];
""")
    assert out["ready"] == [False, []] and out["notReady"] == [True, ["/new?result=photo"]]
    assert out["odd"] == [False, 1] and out["failed"] == [False, 1]                           # an answer the form cannot read never blocks it


@node
def test_the_measured_scale_of_the_context_is_the_one_of_its_own_laser_lens_and_titanium(tmp_path):
    scales = [{"mode": {"device_id": 1, "lens_id": 2, "material_id": 4, "key": "other titanium"}}, {"mode": {"device_id": 1, "lens_id": 2, "material_id": 3, "key": "mine"}}]
    out = run(tmp_path, f"S.scales = {json.dumps(scales)};" + """
  out.mine = await ctx.App.contextScale(S.context, 60);
  out.none = await ctx.App.contextScale({...S.context, device_id: 2}, 60);
  out.asked = ctx.requests.filter((r) => r.path === '/api/grey-scales').map((r) => r.url);
  S.context.lens_id = null;
  out.unknown = ctx.requests.length && await ctx.App.contextScale({...S.context, lens_id: null}, 60);
  out.unknownAsked = ctx.requests.filter((r) => r.path === '/api/grey-scales').pop().url;
""")
    assert out["mine"]["key"] == "mine" and out["none"] is None
    assert out["asked"][0] == "/api/grey-scales?device_id=1&lens_id=2&material_id=3&row_mm=60"
    assert out["unknown"] is None and out["unknownAsked"] == "/api/grey-scales?device_id=1&lens_id=unknown&material_id=3&row_mm=60"


@node
def test_a_photo_works_own_laser_lens_titanium_and_source_are_written_in_one_line(tmp_path):
    out = run(tmp_path, """
  out.line = await ctx.App.workContextText({scale: {device_id: 2, lens_id: 2}, material: {name: 'Sheet', grade: 'Grade 2', batch: 'B7'}, source: null});
  out.release = await ctx.App.workContextText({scale: {device_id: 1, lens_id: null}, material: null, source: {kind: 'release', lab_name: 'Север'}});
  on('GET /api/devices', () => refuse('workshop is busy', 500));
  out.unreadable = await ctx.App.workContextText({scale: {device_id: 1, lens_id: 2}, material: null, source: null});
""")
    assert out["line"] == "Laser: Mopa 30 · lens: F-Theta · 174 mm · stock: Sheet · Grade 2 · batch B7 · measurements: this workshop"
    assert out["release"] == "Laser: JPT 60 · lens: Unknown · stock: not specified · measurements: laboratory Север"
    assert out["unreadable"] == ""                                                            # no lists, no line: the work screen stays as it was


@node
def test_a_new_test_plate_starts_on_the_shared_laser_and_titanium_unless_the_caller_names_others_and_remembers_where_it_was_made(tmp_path):
    out = run(tmp_path, """
  on('POST /api/capability-plates', () => reply(201, {plan_id: 9, name: 'Плата', summary: {layers: 4, work_field: {checked: true}}}));
  const devices = [{id: 1, name: 'JPT', title: 'JPT 60', lens: {id: 2}, passport: {pulse_steps: [{pulse_width_ns: 200, cutoff_khz: 100}], repetition_rate_khz: {min: 1, max: 4000}}},
    {id: 2, name: 'Mopa', title: 'Mopa 30', lens: {id: 5}, passport: {pulse_steps: [{pulse_width_ns: 200, cutoff_khz: 100}], repetition_rate_khz: {min: 1, max: 4000}}}];
  const materials = [{id: 3, family: 'Titanium', name: 'Plate', grade: 'Grade 5'}, {id: 4, family: 'Titanium', name: 'Sheet', grade: 'Grade 2'}];
  S.context = {...S.context, device_id: 2, material_id: 4};
  let box = await ctx.PlateDialog.open(devices, materials, null, {type: 'grey_scales'}); await settle();
  out.shared = [labelled(box.el, 'Лазер').value, labelled(box.el, 'Заготовка').value];
  box.close();
  box = await ctx.PlateDialog.open(devices, materials, null, {type: 'grey_scales', device: 1, material: 3}); await settle();
  out.named = [labelled(box.el, 'Лазер').value, labelled(box.el, 'Заготовка').value];
  await button(box.el, 'Создать плату').dispatch('click'); await settle();
  out.put = sent('PUT', '/api/creation/context').map((r) => r.json);
""")
    assert out["shared"] == ["2", "4"] and out["named"] == ["1", "3"]
    assert out["put"] == [{"device_id": 1, "lens_id": 2, "material_id": 3}]
