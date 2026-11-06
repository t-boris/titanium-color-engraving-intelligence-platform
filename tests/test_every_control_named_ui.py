"""Every control of the screens has an accessible name, and every number box says its unit and the values it takes (feature ux-save-feedback-p0,
REQ-003, criteria c1 and c2). The real application is served on a free port with a small workshop built through the real code paths (a laser with a
lens, measured colours, vector works of every kind, a photo work, a proposal), the screens are built in node over the small DOM of the other screen
tests, their requests going to that server, and every input, select and textarea they draw is checked:

* it has a name by one of the four ways a browser takes it (aria-label, aria-labelledby, label[for], a wrapping label with text of its own);
* a number or range control says its unit («мм», «%», «без единицы» ...) in its name or its description, and, when it has an end of its own
  (``min``/``max``), says the permitted values too.

The screens that cannot be built here are listed with the reason; the real-browser sweep (headless Chrome over CDP, the browser's own
accessibility tree) covers what the small DOM cannot. Only what a real browser, Electron or a screen reader adds is not claimed here."""
import json
import re
from pathlib import Path

import cv2
import httpx

import obs
import synth
import test_grey_scales as gs
import test_vector_work as vw
from growing_ui import TABLES, UI, node, run_node, serving
from titanium_platform import capability_plates as cp, devices, ingest as ig, knowledge as kn, lenses, plans, setup as su

# the scripts of the page in its own order, less those the harness already loads and those that start the application
ALREADY = set(TABLES) | {"app.js", "forms.js", "terms.js", "dialogs.js", "list.js", "filepick.js", "router.js", "boot.js"}


def page_scripts():
    html = (UI / "index.html").read_text(encoding="utf-8")
    return [name for name in re.findall(r'<script src="/([^"]+)"', html) if name not in ALREADY]


AUDIT = r"""
const UNIT = /(мм|мкм|%|нс|кГц|Вт|нм|\bч\b|с\/см|\bс\b|°|ΔE|×|ячеек|мДж|Дж|без единицы|единица:|минут)/i;
const RANGE = /(допустимо|от \d|не меньше|больше|не больше|целое|\d\s*[–-]\s*\d|ограничен)/i;
const seen = {controls: 0, unnamed: [], numeric: 0, noUnit: [], noRange: []};
const audited = new WeakSet();                                  // a control seen on a tab is not counted again on the next
const walk = (node, fn) => { fn(node); for (const c of node.childNodes || []) if (c.nodeType === 1) walk(c, fn); };
const hiddenUp = (el) => { for (let p = el; p && p.nodeType === 1; p = p.parentNode) if (p.hasAttribute('hidden') || p.hidden === true || (p.style && p.style.display === 'none')) return true; return false; };
const ownText = (label) => {                                   // the text of a label less the controls inside it
  let text = '';
  const go = (n) => { for (const c of n.childNodes) { if (c.nodeType === 3) text += c.data; else if (c.nodeType === 1 && !['input', 'select', 'textarea', 'option', 'button'].includes(c.localName)
    && !(c.getAttribute('class') || '').split(' ').includes('sr-only')) go(c); } };
  go(label);
  return text.trim();
};
function audit(root, where) {
  const ids = new Map(), labels = [], controls = [];
  walk(doc.body, (n) => { if (n.getAttribute('id')) ids.set(n.getAttribute('id'), n); if (n.localName === 'label') labels.push(n); });
  walk(root, (n) => { if (['input', 'select', 'textarea'].includes(n.localName)) controls.push(n); });
  for (const el of controls) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (['hidden', 'button', 'submit', 'reset', 'image'].includes(type) || hiddenUp(el) || audited.has(el)) continue;
    audited.add(el);
    seen.controls += 1;
    let name = (el.getAttribute('aria-label') || '').trim();
    if (!name && el.getAttribute('aria-labelledby')) name = el.getAttribute('aria-labelledby').split(/\s+/).map((id) => ids.has(id) ? ids.get(id).textContent.trim() : '').join(' ').trim();
    if (!name && el.getAttribute('id')) { const l = labels.find((x) => x.getAttribute('for') === el.getAttribute('id')); if (l) name = ownText(l); }
    if (!name) for (let p = el.parentNode; p && p.nodeType === 1 && !name; p = p.parentNode) if (p.localName === 'label') name = ownText(p);
    const html = `${el.localName}${type ? '[' + type + ']' : ''}${el.getAttribute('placeholder') ? ' «' + el.getAttribute('placeholder') + '»' : ''}`;
    if (!name) { seen.unnamed.push(`${where}: ${html}`); continue; }
    const numeric = type === 'number' || type === 'range' || ['decimal', 'numeric'].includes(el.getAttribute('inputmode'));
    if (!numeric) continue;
    seen.numeric += 1;
    const description = (el.getAttribute('aria-describedby') || '').split(/\s+/).map((id) => ids.has(id) ? ids.get(id).textContent : '').join(' ');
    if (!UNIT.test(`${name} ${description}`)) seen.noUnit.push(`${where}: ${name}`);
    if ((el.getAttribute('min') != null || el.getAttribute('max') != null) && !RANGE.test(description)) seen.noRange.push(`${where}: ${name} [${el.getAttribute('min')}..${el.getAttribute('max')}]`);
  }
}
"""


def build_workshop(app, port):
    """A small workshop through the real code paths: what the screens read is what the real routes answer."""
    s = app.state.store
    s.set_setting("allow_non_raw_photos", True)
    laser = devices.create_from_template(s, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="AUDIT-01")
    lens = lenses.create_lens(s, "F-Theta", 174, 170)
    lenses.install(s, laser["id"], lens["id"])
    plans.save_marker_layer_settings(s, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    stand = su.save_capture_setup(s, "Rig", "cam", "LED", "90", "ColorChecker Classic")
    ti = su.save_material(s, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)
    su.save_rules(s, laser["id"], lens["id"], repeat_threshold=2, delta_tolerance=6.0, variance_threshold=5.0)
    w = {"device": laser, "lens": lens, "setup": (laser["id"], lens["id"]), "stand": stand, "n": 0}
    for rgb, power in ((vw.PAPER, 10), (vw.RED, 20), (vw.BLUE, 30), (vw.GREEN, 40)):
        obs.add(s, w, vw.lab(rgb), power=power, speed=500, line_interval=0.02, material_id=ti["id"], layer_type="Scan")
    kn.refresh(s, *w["setup"])
    ids = {"device": laser["id"], "lens": lens["id"], "material": ti["id"]}
    # a grey plate, photographed and accepted (the analysis screen), and a second left in review (the ingest review screen)
    made = cp.create(s, laser["id"], ti["id"], "grey_scales", {**gs.SETTINGS, "scales": gs.SMALL})
    plan = plans.get_plan(s, made["plan_id"])
    photo = synth.plate_photo(plan, {}, size=(1300, 2800), step_rgb=lambda name, grey: gs.step_colour(grey))
    accepted = ig.create_pair(s, device_id=laser["id"], lens_id=lens["id"], stand_id=stand["id"], lightburn_name="grey.lbrn2", lightburn_bytes=plans.export_lbrn2(plan),
                              photo_name="grey.png", context={"material_id": ti["id"]}, photo_bytes=cv2.imencode(".png", photo)[1].tobytes())
    ig.check_pair(s, accepted)
    ig.review_masks(s, accepted)
    ig.accept_pair(s, accepted)
    made2 = cp.create(s, laser["id"], ti["id"], "grey_scales", {**gs.SETTINGS, "scales": gs.SMALL})
    plan2 = plans.get_plan(s, made2["plan_id"])
    photo2 = synth.plate_photo(plan2, {}, size=(1300, 2800), step_rgb=lambda name, grey: gs.step_colour(grey))
    pending = ig.create_pair(s, device_id=laser["id"], lens_id=lens["id"], stand_id=stand["id"], lightburn_name="grey2.lbrn2", lightburn_bytes=plans.export_lbrn2(plan2),
                             photo_name="grey2.png", context={"material_id": ti["id"]}, photo_bytes=cv2.imencode(".png", photo2)[1].tobytes())
    ig.check_pair(s, pending)
    ids.update({"plan": made["plan_id"], "accepted_pair": accepted, "pending_pair": pending})
    base = {"device_id": laser["id"], "lens_id": lens["id"], "material_id": ti["id"], "width_mm": 60}
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as c:
        def make(name, **fields):
            r = c.post("/api/vector", data={**base, "name": name, **fields}, files={"image": ("p.png", vw.picture(), "image/png")})
            assert r.status_code == 201, r.text
            return r.json()["id"]
        ids["vector_photo"] = make("Portrait", strategy="photo", n_colors=5, threshold=6, detail="medium")
        ids["vector_fill"] = make("Silhouette", strategy="fill", threshold=8)
        ids["vector_line"] = make("Lines", strategy="line", threshold=8)
        ids["vector_zoned"] = make("Zoned", strategy="photo", n_colors=5, threshold=6, detail="medium", faces="false")
        document = json.loads(Path(plans.get_plan(s, ids["vector_zoned"])["document_path"]).read_text(encoding="utf-8"))
        red = min(document["palette"], key=lambda q: sum((a - b) ** 2 for a, b in zip(q["srgb"], vw.RED)))["index"]
        regions = [region["id"] for region in document["regions"] if region["color"] == red] or [document["regions"][0]["id"]]
        zone = c.post(f"/api/vector/{ids['vector_zoned']}/colouring", json={"op": "photo_add", "regions": regions})
        ids["zone"] = zone.json()["zones"][0]["number"] if zone.status_code == 200 else 1
        r = c.post("/api/photo-works", data={"width_mm": 60, "name": "Girl"}, files={"picture": ("girl.png", vw.picture(), "image/png")})
        ids["photo_work"] = r.json().get("id") if r.status_code < 300 else None
        r = c.post("/api/designer/propose", json={"device_id": laser["id"], "lens_id": lens["id"], "pulse_width": 200, "line_interval": 0.025, "passes": 1,
                                                  "seed": 1, "size": 4})
        ids["proposal"] = r.json().get("id") if r.status_code < 300 else None
        r = c.post("/api/research/sessions", json={"device_id": laser["id"], "material_id": ti["id"], "goal": "text", "target": "legible black text 1 mm high"})
        ids["research"] = r.json().get("id") if r.status_code < 300 else None
    return ids


SCREENS = r"""
// what a browser has and the small DOM does not: element.dataset and element.style, the storage of the page, the frame timer, File
for (const name of ['dataset', 'style']) {
  Object.defineProperty(El.prototype, name, {get() { return this['_' + name] || (this['_' + name] = {}); }, set(v) { this['_' + name] = v; }, configurable: true});
}
Object.defineProperty(El.prototype, 'files', {get() { return this._files || (this._files = []); }, set(v) { this._files = v; }, configurable: true});
const unhandled = [];
process.on('unhandledRejection', (e) => unhandled.push(String(e && e.message || e).slice(0, 160)));
const storage = () => { const m = new Map(); return {getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k)}; };
ctx.sessionStorage = storage(); ctx.localStorage = storage();
ctx.requestAnimationFrame = (fn) => setTimeout(fn, 0); ctx.cancelAnimationFrame = (id) => clearTimeout(id);
ctx.File = class File {}; ctx.FormData = class FormData { append() {} }; ctx.matchMedia = () => ({matches: false, addEventListener() {}, removeEventListener() {}});
// [screen id, what the router gives it: the first part of the address, the second, the query]
const at = (id, arg, query = {}) => [id, {id, arg, query, path: '/' + id + (arg ? '/' + arg : '')}];
const screens = [
  at('vector', null, {new: '1', classic: '1'}), at('vector', null, {plan: IDS.vector_photo}), at('vector', null, {plan: IDS.vector_fill}), at('vector', null, {plan: IDS.vector_line}),
  at('vector', null, {plan: IDS.vector_zoned}), at('vector-zone', null, {work: IDS.vector_zoned, zone: IDS.zone}),
  at('photo-engraving', null, {work: IDS.photo_work}), at('photo-engraving', null, {scales: '1'}), at('photo-engraving'),
  at('photo-preview', null, {work: IDS.photo_work}), at('photo-preview'), at('photo'), at('artwork'), at('new'), at('works'), at('workshop'),
  at('experiments'), at('experiment', 'plan-' + IDS.plan), at('plan', IDS.plan), at('plan', IDS.plan2), at('analysis', IDS.accepted_pair),
  at('ingest'), at('ingest', null, {pair: IDS.pending_pair}), at('ingest', null, {pair: IDS.accepted_pair}),
  at('designer', null, {device: IDS.device, lens: IDS.lens}), at('devices'), at('devices', IDS.device), at('devices', IDS.device, {tab: 'lens'}),
  at('setup'), at('setup', null, {tab: 'rigs'}), at('setup', null, {tab: 'rules'}), at('setup', null, {tab: 'markers'}),
  at('network'), at('labs'), at('colors'), at('findings'), at('research'), at('research', IDS.research),
];
const unbuilt = [];
// The buttons that open a dialog (their words say so: a window, a form to fill) are pressed, the dialog is audited and closed. A button that
// destroys or sends something is never pressed.
const OPENS = /…$|^(Новая работа|Создать плату|Размер|Выбрать настройки|Целевой цвет|Подробно)/;
const NEVER = /Удал|Сброс|Убрать|Очист|Отмен|Закрыть|Принять|Подтверд|Отправ|Сохран|Запуст|Скачать|Выход/;
const dialogs = [];
async function openDialogs(tree, where) {
  const opened = new Set();
  for (const button of qa(tree, 'button')) {
    const text = button.textContent.trim();
    if (!text || opened.has(text) || !OPENS.test(text) || NEVER.test(text) || button.disabled || hiddenUp(button)) continue;
    opened.add(text);
    const before = qa(doc.body, '.modal-bg').length;
    try { await button.dispatch('click'); } catch (e) { continue; }
    await sleep(120);
    const windows = qa(doc.body, '.modal-bg');
    if (windows.length > before) {
      const win = windows[windows.length - 1];
      dialogs.push(where + ' > ' + text);
      audit(win, where + ' > ' + text);
      win.remove();
      for (const part of doc.body.childNodes) if (part.nodeType === 1 && part.removeAttribute) part.removeAttribute('inert');
    }
  }
}
const label = (id, arg, query) => id + (arg ? '/' + arg : '') + (Object.keys(query).length ? '?' + Object.entries(query).map(([k, v]) => k + '=' + v).join('&') : '');
for (const [id, route] of screens) {
  const where = label(id, route.arg, route.query);
  const screen = ctx.__screens[id];
  if (!screen) { unbuilt.push(where + ': no such screen'); continue; }
  try {
    const tree = await screen.render(route);
    mount(tree);
    await sleep(150);
    audit(tree, where);
    for (const [index, tab] of qa(tree, '[role]').filter((n) => n.getAttribute('role') === 'tab').entries()) {                  // every tab of the screen, one after the other
      try { await tab.dispatch('click'); } catch (e) { /* a tab that cannot be pressed here is left */ }
      await sleep(100);
      audit(tree, where + ' [tab ' + (index + 1) + ']');
    }
    await openDialogs(tree, where);
    tree.remove();
  } catch (e) { unbuilt.push(where + ': ' + String(e && e.message || e).slice(0, 140)); }
}
// the dialog that makes a plate, once for every type of plate (each type draws its own card)
const plateTypes = await App.get('/plate-types');
const lasers = await App.get('/devices');
for (const kind of plateTypes) {
  try {
    const dialog = await ctx.PlateDialog.open(lasers, null, null, {type: kind.id});
    await sleep(60);
    audit(dialog.el, 'plate dialog [' + kind.id + ']');
    dialog.close();
  } catch (e) { unbuilt.push('plate dialog ' + kind.id + ': ' + String(e && e.message || e).slice(0, 140)); }
}
out.seen = seen;
out.unbuilt = unbuilt;
out.unhandled = unhandled;
out.dialogs = dialogs;
"""


@node
def test_every_control_of_the_screens_has_a_name_and_every_number_box_its_unit_and_its_permitted_values(tmp_path):
    with serving(tmp_path / "shop") as (app, port):
        ids = build_workshop(app, port)
        out = run_node(tmp_path, port, page_scripts(), f"const IDS = {json.dumps(ids)};\n{AUDIT}\n{SCREENS}", ("PlateDialog",))
    seen = out["seen"]
    assert len(out["dialogs"]) >= 10, f"only {len(out['dialogs'])} dialogs were opened: {out['dialogs']}"
    assert seen["controls"] > 150, f"the screens drew only {seen['controls']} controls: the audit has too little to look at"
    assert seen["unnamed"] == [], "controls without an accessible name:\n" + "\n".join(seen["unnamed"])
    assert seen["noUnit"] == [], "number controls that say no unit:\n" + "\n".join(seen["noUnit"])
    assert seen["noRange"] == [], "number controls with an end of their own that do not say the permitted values:\n" + "\n".join(seen["noRange"])
    # a screen that could not be built here is not checked here: the list is short and each has its reason (they are checked in the real browser)
    assert out["unbuilt"] == [], "screens that could not be built:\n" + "\n".join(out["unbuilt"])
