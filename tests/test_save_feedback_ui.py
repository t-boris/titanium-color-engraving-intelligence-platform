"""Saving, errors, forms and background tasks (feature ux-save-feedback-p0, REQ-001..003). Run in node over the small DOM of the other screen
tests. The DOM here also refuses an assignment to the properties a real element has read-only (``label.control`` among them: a real browser
throws on it, the plain DOM would not), so a mistake of that kind fails here. Every scenario with answers that come late has its answers held
and released by the test, so the order is the test's, not luck's. What a layout engine, Electron or a screen reader would add is not claimed."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
SCRIPTS = ["app.js", "save-state.js", "forms.js", "terms.js", "dialogs.js", "list.js", "operations.js"]
READ_ONLY = ["control", "form", "labels", "list", "willValidate", "validationMessage", "parentElement", "nextSibling", "previousSibling",
             "lastElementChild", "firstElementChild", "childElementCount"]

HARNESS = """
const {context, load, El} = require(%(dom)s);
for (const name of %(readonly)s) {
  Object.defineProperty(El.prototype, name, {get() { return null; }, set() { throw new TypeError('Cannot set property ' + name + ' which has only a getter'); }, configurable: true});
}
const ctx = context(%(routes)s);
const went = [];
class FakeForm { constructor() { this.parts = []; } append(k, v) { this.parts.push([k, v]); } entries() { return this.parts[Symbol.iterator](); } }
class FakeXhr {
  constructor() { this.upload = {}; FakeXhr.all.push(this); }
  open(method, url) { this.method = method; this.url = url; }
  send(body) { this.body = body; }
  abort() { this.aborted = true; if (this.onabort) this.onabort(); }
  progress(loaded, total) { this.upload.onprogress({lengthComputable: true, loaded, total}); }
  finish(status, json) { this.status = status; this.response = json; this.onload(); }
}
FakeXhr.all = [];
ctx.XMLHttpRequest = FakeXhr; ctx.FormData = FakeForm;
const scripts = %(scripts)s;
load(ctx, %(ui)s, [...%(tables)s, scripts[0], {code: 'App.go = (route) => { __went.push(route); };'}, ...scripts.slice(1),
  {code: 'globalThis.SaveState = SaveState; globalThis.Forms = Forms; globalThis.Terms = Terms; globalThis.Operations = Operations;'}]);
ctx.__went = went;
const {App, SaveState, Forms, Terms, Operations, I18N} = ctx;
const doc = ctx.document, body = doc.body;
const {h} = App;
const tick = () => new Promise((r) => setTimeout(r, 0));
const wait = async (n = 8) => { for (let i = 0; i < n; i++) await tick(); };
const button = (root, label) => root.querySelectorAll('button').find((b) => b.textContent === label);
const spoken = () => body.querySelectorAll('.sr-only').map((p) => p.textContent);
const calls = [];
/** The server answers by path (a value, or a function of the request that gives {status, json}). */
function serve(answers) {
  ctx.fetch = async (url, opts = {}) => {
    const path = String(url).split('?')[0].replace(/^\\/api/, '');
    calls.push((opts.method || 'GET') + ' ' + path);
    const r = typeof answers[path] === 'function' ? answers[path](opts) : answers[path] || {status: 404, json: {error: path + ' not found', kind: 'not_found'}};
    return {ok: r.status < 300, status: r.status, headers: {get: () => 'application/json'}, json: async () => r.json};
  };
}
const until = async (test, n = 400) => { for (let i = 0; i < n && !test(); i++) await tick(); return test(); };
Operations.config.pollMs = 1;
/** A document whose requests are answered by the test: ``gates[i]`` is the i-th request, ``res(doc)`` or ``rej(error)`` answers it. */
function track(initial = {w: 1, v: 1}, extra = {}) {
  const gates = [], applied = [];
  const st = SaveState.create({label: 'Работа', confirmed: initial, names: {w: 'Ширина', v: 'Высота'},
    send: (request, edit) => new Promise((res, rej) => gates.push({request, edit, res, rej})),
    apply: (d, info) => applied.push({doc: d, local: info.local, reverted: info.reverted, failed: info.failed}), ...extra});
  body.append(st.view.el);
  return {st, gates, applied, line: () => st.view.el.querySelector('.save-line').textContent,
    box: () => st.view.el.querySelector('.save-error'), shown: () => !st.view.el.querySelector('.save-error').hidden};
}
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, body, routes=None, scripts=None):
    script = tmp_path / "feedback.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "readonly": json.dumps(READ_ONLY),
                                 "routes": json.dumps(routes or {}), "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES),
                                 "scripts": json.dumps(scripts or SCRIPTS), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


# -- REQ-001: the state of a document, tied to the change it answers ------------------------------------------------------------------
@node
def test_overlapping_changes_are_sent_in_order_and_only_the_last_answer_is_shown(tmp_path):
    out = run(tmp_path, """
  const t = track();
  const a = t.st.edit({w: 2}, {local: {w: 2}});
  const b = t.st.edit({w: 3}, {local: {w: 3}});
  await wait();
  out.start = {sent: t.gates.length, line: t.line(), status: t.st.status(), queued: t.st.snapshot().queued};
  t.gates[0].res({w: 2, v: 1}); await wait();
  out.first = {sent: t.gates.length, applied: t.applied.length, line: t.line(), status: t.st.status()};
  t.gates[1].res({w: 3, v: 1}); await wait();
  out.last = {applied: t.applied.map((x) => x.doc), line: t.line().replace(/ at \\d\\d:\\d\\d/, ''), status: t.st.status(), results: [await a, await b], order: t.gates.map((g) => g.request.w)};
""")
    assert out["start"] == {"sent": 1, "line": "Работа: Saving… · 1 more queued", "status": "saving", "queued": 1}       # the second waits for the first
    assert out["first"] == {"sent": 2, "applied": 0, "line": "Работа: Saving…", "status": "saving"}               # the answer to 2 does not show 3 as saved
    assert out["last"] == {"applied": [{"w": 3, "v": 1}], "line": "Работа: Saved", "status": "saved", "results": [None, None], "order": [2, 3]}


@node
def test_a_late_answer_never_marks_a_newer_change_saved_or_replaces_it(tmp_path):
    out = run(tmp_path, """
  const t = track();
  t.st.edit({w: 2}, {local: {w: 2}, calculates: true});
  await wait();
  const during = {status: t.st.status(), line: t.line()};
  t.st.edit({w: 3}, {local: {w: 3}, calculates: true});                                        // typed while the first one is still on its way
  await wait();
  t.gates[0].res({w: 2, v: 1}); await wait();
  const snap = t.st.snapshot();
  out.after_first = {during, status: snap.status, revision: snap.revision, acknowledged: snap.acknowledged, applied: t.applied.length, line: t.line()};
  t.gates[1].res({w: 3, v: 1}); await wait();
  const end = t.st.snapshot();
  out.after_last = {status: end.status, acknowledged: end.acknowledged, applied: t.applied.map((x) => x.doc)};
""")
    assert out["after_first"] == {"during": {"status": "calculating", "line": "Работа: Saving and calculating…"}, "status": "calculating", "revision": 2,
                                  "acknowledged": 1, "applied": 0, "line": "Работа: Saving and calculating…"}
    assert out["after_last"] == {"status": "saved", "acknowledged": 2, "applied": [{"w": 3, "v": 1}]}


@node
def test_a_failed_change_stays_in_its_place_with_the_typed_value_and_the_error_beside_the_work(tmp_path):
    out = run(tmp_path, """
  const t = track({w: 100, v: 1});
  const result = t.st.edit({w: 0}, {local: {w: 0}});
  await wait();
  t.gates[0].rej(Object.assign(new Error('the width of the picture must be 1..1000 mm'), {kind: 'invalid'})); await wait();
  out.failed = {result: (await result).message, status: t.st.status(), line: t.line(), shown: t.shown(), text: t.box().textContent, local: t.st.local(),
    alert: t.box().getAttribute('role'), redrawn: t.applied.map((x) => ({local: x.local, failed: x.failed})), confirmed: t.st.snapshot().confirmed};
  // the other field is saved: a success does not take the error away
  t.st.edit({v: 2}, {local: {v: 2}}); await wait();
  t.gates[1].res({w: 100, v: 2}); await wait();
  out.after_success = {status: t.st.status(), shown: t.shown(), local: t.st.local(), line: t.line()};
""")
    failed = out["failed"]
    assert failed["result"] == "the width of the picture must be 1..1000 mm" and failed["status"] == "failed" and failed["shown"]
    assert failed["line"] == "Работа: Not saved: the screen differs from the saved values" and failed["alert"] == "alert"
    assert failed["text"] == ("Could not save. the width of the picture must be 1..1000 mm"
                              "Entered but not saved — Ширина: 0 (saved: 100).Close")
    assert failed["local"] == {"w": 0} and failed["confirmed"] == {"w": 100, "v": 1}                          # what is typed and what is stored, apart
    assert failed["redrawn"] == [{"local": {"w": 0}, "failed": True}]                                         # the screen is drawn again with the typed value over it
    assert out["after_success"] == {"status": "failed", "shown": True, "local": {"w": 0}, "line": "Работа: Not saved: the screen differs from the saved values"}


@node
def test_failure_then_retry_then_a_new_edit_during_the_retry(tmp_path):
    out = run(tmp_path, """
  const t = track({w: 100, v: 1});
  t.st.edit({w: 70}, {local: {w: 70}}); await wait();
  t.gates[0].rej(new Error('no connection')); await wait();
  out.failed = {status: t.st.status(), buttons: ['Retry saving', 'Restore saved values', 'Show saved values'].map((l) => !button(t.st.view.el, l).hidden)};
  const retry = t.st.retry(); await wait();                                                                 // the retry is on its way ...
  out.retrying = {sent: t.gates.map((g) => g.request.w), line: t.line(), retryDisabled: button(t.st.view.el, 'Retry saving').disabled};
  t.st.edit({w: 75}, {local: {w: 75}}); await wait();                                                       // ... and the person types again
  t.gates[1].res({w: 70, v: 1}); await wait();
  out.after_retry = {status: t.st.status(), applied: t.applied.length, shown: t.shown(), local: t.st.local()};
  t.gates[2].res({w: 75, v: 1}); await wait();
  out.end = {status: t.st.status(), shown: t.shown(), applied: t.applied.map((x) => x.doc), order: t.gates.map((g) => g.request.w), retry: await retry,
    line: t.line().replace(/ at \\d\\d:\\d\\d/, '')};
""")
    assert out["failed"] == {"status": "failed", "buttons": [True, True, False]}                              # a change that can be repeated: repeat, or put back
    assert out["retrying"] == {"sent": [70, 70], "line": "Работа: Retrying save… Saving…", "retryDisabled": True}
    assert out["after_retry"] == {"status": "saving", "applied": 1, "shown": False, "local": {"w": 75}}    # the retry's answer is not the end: 75 is typed after it
    assert out["end"] == {"status": "saved", "shown": False, "applied": [{"w": 100, "v": 1}, {"w": 75, "v": 1}], "order": [70, 70, 75], "retry": None,
                          "line": "Работа: Saved"}


@node
def test_a_newer_change_of_the_same_field_covers_the_failure_and_nothing_old_is_sent_again(tmp_path):
    out = run(tmp_path, """
  const t = track();
  t.st.edit({w: 5}, {local: {w: 5}}); await wait();
  t.gates[0].rej(new Error('busy')); await wait();
  t.st.edit({w: 6}, {local: {w: 6}}); await wait();                                                         // corrected before any retry
  const during = {status: t.st.status(), shown: t.shown()};
  t.gates[1].res({w: 6, v: 1}); await wait();
  const sentBefore = t.gates.length;
  const again = await t.st.retry();
  out.end = {during, status: t.st.status(), shown: t.shown(), sent: [sentBefore, t.gates.length], again};
""")
    assert out["end"] == {"during": {"status": "saving", "shown": True}, "status": "saved", "shown": False, "sent": [2, 2], "again": None}


@node
def test_closing_the_error_hides_the_message_only_and_putting_back_shows_the_stored_value(tmp_path):
    out = run(tmp_path, """
  const t = track({w: 100, v: 1});
  t.st.edit({w: 0}, {local: {w: 0}}); await wait();
  t.gates[0].rej(new Error('refused')); await wait();
  await button(t.box(), 'Close').dispatch('click'); await wait();
  out.closed = {shown: t.shown(), status: t.st.status(), line: t.line(), local: t.st.local(), dismissed: t.st.dismissed()};
  await button(t.st.view.el, 'Restore saved values').dispatch('click'); await wait();
  out.reverted = {status: t.st.status(), line: t.line(), local: t.st.local(), last: t.applied[t.applied.length - 1], shown: t.shown()};
""")
    assert out["closed"] == {"shown": False, "status": "failed", "line": "Работа: Not saved: the screen differs from the saved values", "local": {"w": 0}, "dismissed": True}
    assert out["reverted"] == {"status": "saved", "line": "Работа: Saved", "local": {}, "shown": False,
                               "last": {"doc": {"w": 100, "v": 1}, "local": {}, "reverted": True, "failed": False}}


@node
def test_a_change_that_must_not_be_sent_twice_offers_the_stored_work_instead_of_a_retry(tmp_path):
    out = run(tmp_path, """
  let reads = 0;
  const t = track({w: 100}, {reload: async () => { reads += 1; }});
  t.st.edit({undo: true}, {calculates: true});                                                              // an undo: not repeatable, not absolute
  await wait();
  t.gates[0].rej(new Error('there is no earlier change')); await wait();
  const view = t.st.view.el;
  out.offered = {retry: !button(view, 'Retry saving').hidden, stored: !button(view, 'Show saved values').hidden, put_back: !button(view, 'Restore saved values').hidden};
  const before = t.gates.length;
  await t.st.retry();
  out.not_sent = t.gates.length === before;
  await button(view, 'Show saved values').dispatch('click'); await wait();
  out.shown = {reads, status: t.st.status(), last: t.applied[t.applied.length - 1].reverted};
""")
    assert out["offered"] == {"retry": False, "stored": True, "put_back": False} and out["not_sent"] is True
    assert out["shown"] == {"reads": 1, "status": "saved", "last": True}


@node
def test_a_failure_after_the_screen_is_gone_is_reported_to_the_task_panel(tmp_path):
    out = run(tmp_path, """
  const reported = [];
  const t = track({w: 100}, {onOrphanFailure: (f) => reported.push(f)});
  t.st.edit({w: 5}, {local: {w: 5}}); await wait();
  t.st.view.el.remove();                                                                                    // the person went to another section
  t.gates[0].rej(new Error('no connection')); await wait();
  out.reported = reported;
""")
    assert out["reported"] == [{"label": "Работа", "message": "no connection", "describe": "Ширина: 5 (saved: 100)", "retryable": True}]


# -- the photo work: the save state wired into the screen (BUG-002, BUG-011) ------------------------------------------------------------
def photo(tmp_path, body, **kwargs):
    from test_photo_engraving_ui import run as photo_run
    return photo_run(tmp_path, {"work": "7"}, """
  ctx.document.body.append(tree);
  const status = () => tree.querySelector('.save-line').textContent.replace(/ at \\d\\d:\\d\\d/, '');
  const failure = () => { const box = tree.querySelector('.save-error'); return box.hidden ? null : box.textContent; };
  const width = labelled(tree, 'Ширина на титане, мм');
  const failing = (test) => { const real = ctx.fetch; ctx.fetch = async (url, opts = {}) => {
    const path = String(url).split('?')[0];
    if (path.endsWith('/settings') && opts.body && test(JSON.parse(opts.body))) { requests.push({path, url: String(url), method: opts.method || 'GET', body: JSON.parse(opts.body)}); if (hold.length) await hold.shift(); throw new Error('network down'); }
    return real(url, opts); }; };
""" + body, **kwargs)


@node
def test_overlapping_width_changes_on_a_work_show_saving_until_the_last_answer(tmp_path):
    out = photo(tmp_path, """
  let first, second;
  hold.push(new Promise((r) => { first = r; })); hold.push(new Promise((r) => { second = r; }));
  width.value = '80'; width.dispatch('change'); await settle();
  width.value = '90'; width.dispatch('change'); await settle();
  out.start = {status: status(), sent: saves()};
  first(); await settle();
  out.after_first = {status: status(), sent: saves(), waiting: tree.textContent.includes('Считаем прогноз'), failure: failure()};
  second(); await settle();
  out.end = {status: status(), shown: shown(tree), width: width.value, failure: failure()};
""")
    assert out["start"] == {"status": "Работа: Saving and calculating… · 1 more queued", "sent": [{"width_mm": 80}]}
    assert out["after_first"] == {"status": "Работа: Saving and calculating…", "sent": [{"width_mm": 80}, {"width_mm": 90}], "waiting": True, "failure": None}
    assert out["end"] == {"status": "Работа: Saved", "shown": "/api/photo-works/7/preview.png?v=2", "width": "90", "failure": None}


@node
def test_a_work_change_that_fails_keeps_what_was_typed_and_a_later_edit_does_not_hide_the_error(tmp_path):
    out = photo(tmp_path, """
  failing((b) => b.width_mm === 70);
  width.value = '70'; await width.dispatch('change'); await settle();
  out.failed = {width: width.value, status: status(), failure: failure(), preview: shown(tree), waiting: tree.textContent.includes('Считаем прогноз')};
  const colour = input(tree, (i) => i.getAttribute('type') === 'checkbox');
  colour.checked = true; await colour.dispatch('change'); await settle();                                  // another field is saved
  out.later = {status: status(), failure: failure() !== null, width: width.value, saves: saves(), colour: colour.checked};
""")
    failed = out["failed"]
    assert failed["width"] == "70" and failed["status"] == "Работа: Not saved: the screen differs from the saved values" and failed["waiting"] is False
    assert failed["failure"] == ("Could not save. Cannot reach the local service. Is the application running?"
                                 "Entered but not saved — Ширина, мм: 70 (saved: 60).Close")
    assert failed["preview"] == "/api/photo-works/7/preview.png?v=0"                                          # the stored work is drawn again, not the empty wait
    assert out["later"] == {"status": "Работа: Not saved: the screen differs from the saved values", "failure": True, "width": "70", "colour": True,
                            "saves": [{"width_mm": 70}, {"by_colour": True}]}


@node
def test_a_work_change_failed_then_retried_then_edited_during_the_retry_ends_with_the_last_edit(tmp_path):
    out = photo(tmp_path, """
  let release; hold.push(Promise.resolve());                                  // the first request fails at once
  failing((b) => b.width_mm === 70 && !globalThis.__retry);
  width.value = '70'; await width.dispatch('change'); await settle();
  out.failed = {status: status(), width: width.value, failure: failure() !== null};
  globalThis.__retry = true;
  hold.push(new Promise((r) => { release = r; }));                            // the retry is held
  button(tree, 'Retry saving').dispatch('click'); await settle();
  out.retrying = {sent: saves(), status: status()};
  hold.push(Promise.resolve());
  width.value = '75'; width.dispatch('change'); await settle();               // typed while the retry is on its way
  release(); await settle(); await settle();
  out.end = {sent: saves(), status: status(), failure: failure(), width: width.value, shown: shown(tree)};
""")
    assert out["failed"] == {"status": "Работа: Not saved: the screen differs from the saved values", "width": "70", "failure": True}
    assert out["retrying"]["sent"] == [{"width_mm": 70}, {"width_mm": 70}] and "Retrying save" in out["retrying"]["status"]
    assert out["end"] == {"sent": [{"width_mm": 70}, {"width_mm": 70}, {"width_mm": 75}], "status": "Работа: Saved", "failure": None, "width": "75",
                          "shown": "/api/photo-works/7/preview.png?v=2"}


@node
def test_an_undo_that_fails_is_not_offered_again_and_the_work_can_be_read_from_the_server(tmp_path):
    out = photo(tmp_path, """
  const contours = tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Контуры');
  width.value = '80'; await width.dispatch('change'); await settle();        // something to undo
  const real = ctx.fetch;
  ctx.fetch = async (url, opts = {}) => (String(url).endsWith('/undo') ? {ok: false, status: 503, headers: {get: () => 'application/json'}, json: async () => ({error: 'busy'})} : real(url, opts));
  await button(tree, 'Отменить').dispatch('click'); await settle();
  const view = tree.querySelector('.save-state');
  out.failed = {status: status(), failure: failure() !== null, retry: !button(view, 'Retry saving').hidden, stored: !button(view, 'Show saved values').hidden};
  const reads = requests.filter((r) => r.path === '/api/photo-works/7' && r.method === 'GET').length;
  await button(view, 'Show saved values').dispatch('click'); await settle();
  out.read = {reads: requests.filter((r) => r.path === '/api/photo-works/7' && r.method === 'GET').length - reads, status: status(), failure: failure(), width: width.value};
""")
    assert out["failed"] == {"status": "Работа: Not saved", "failure": True, "retry": False, "stored": True}
    assert out["read"] == {"reads": 1, "status": "Работа: Saved", "failure": None, "width": "80"}


@node
def test_changes_that_fail_after_the_work_was_left_reach_the_task_panel(tmp_path):
    out = photo(tmp_path, """
  let release; hold.push(new Promise((r) => { release = r; }));
  failing((b) => b.width_mm === 70);
  width.value = '70'; width.dispatch('change'); await settle();
  tree.remove();                                                              // the person opens another section
  release(); await settle();
  out.panel = require('vm').runInContext('Operations.items()', ctx).map((o) => ({title: o.title, state: o.state, error: o.error, recover: o.recover.label}));
""")
    assert out["panel"] == [{"title": "Работа «Портрет»: изменения не сохранены", "state": "failed", "recover": "Открыть работу",
                             "error": "Cannot reach the local service. Is the application running? Ширина, мм: 70 (saved: 60)"}]


# -- REQ-002: operations that go on while the person is elsewhere ----------------------------------------------------------------------
@node
def test_an_upload_is_registered_by_the_transport_and_stays_in_the_panel_while_the_person_moves_on(tmp_path):
    out = run(tmp_path, """
  const app = h('div', {id: 'app'}); body.append(app);
  ctx.location.hash = '#/ingest';
  const fd = new FakeForm(); fd.append('photo', {name: 'IMG_1.dng'});
  const sent = App.formProgress('/pairs', fd, () => {});
  const xhr = FakeXhr.all[0];
  xhr.progress(40, 100);
  const op = () => Operations.items()[0];
  const row = () => body.querySelector('.ops-item');
  out.running = {title: op().title, stage: op().stage, progress: op().progress, details: op().details, button: body.querySelector('.ops-toggle').textContent,
    dock: !body.querySelector('.ops-dock').hidden, panel: body.querySelector('.ops-panel').hidden, where: op().context.route};
  app.replaceChildren(h('p', {}, 'another section'));                                       // the router redraws #app
  ctx.location.hash = '#/findings';
  out.moved = {dock: body.querySelector('.ops-dock').isConnected, inApp: app.contains(body.querySelector('.ops-dock')), state: op().state};
  await body.querySelector('.ops-toggle').dispatch('click');                              // the panel opens from anywhere
  out.opened = {panel: body.querySelector('.ops-panel').hidden, expanded: body.querySelector('.ops-toggle').getAttribute('aria-expanded'),
    row: row().textContent.includes('Uploading file to server: 40 %'), bar: row().querySelector('progress').getAttribute('value'), stop: !button(row(), 'Stop').hidden};
  xhr.progress(100, 100);
  const bar = row().querySelector('progress');
  out.last_byte = {stage: op().stage, value: bar.getAttribute('value'), stop: !button(row(), 'Stop').hidden};      // after the last byte it cannot be stopped
  xhr.finish(201, {id: 5}); await sent;
  out.done = {state: op().state, result: op().result, button: body.querySelector('.ops-toggle').textContent, badge: row().querySelector('.pill').textContent,
    where: row().textContent.includes('Started in')};
  out.spoken = spoken();
""")
    assert out["running"] == {"title": "Uploading engraving photograph", "stage": "Uploading file to server: 40 %", "progress": 40, "button": "Tasks — running: 1",
                              "details": [["File", "IMG_1.dng"], ["Address", "/pairs"]], "dock": True, "panel": True, "where": "/ingest"}
    assert out["moved"] == {"dock": True, "inApp": False, "state": "running"}
    assert out["opened"] == {"panel": False, "expanded": "true", "row": True, "bar": "40", "stop": True}
    assert out["last_byte"] == {"stage": "File uploaded; server is processing it", "value": None, "stop": False}
    assert out["done"] == {"state": "done", "result": "File uploaded", "button": "Tasks — finished: 1", "badge": "done", "where": True}
    # the start, the change of stage and the end: three messages for a hundred progress events, and never a clock
    assert out["spoken"] == ["Uploading engraving photograph: Uploading file to server", "Uploading engraving photograph: File uploaded; server is processing it",
                             "Uploading engraving photograph: File uploaded"]


@node
def test_the_header_entry_names_the_panel_counts_what_runs_and_opens_and_closes_it(tmp_path):
    out = run(tmp_path, """
  const entry = Operations.entry();
  body.append(entry);
  const read = () => [entry.textContent, entry.getAttribute('aria-expanded'), entry.getAttribute('aria-controls'), entry.getAttribute('data-state')];
  out.idle = read();
  const one = Operations.begin({kind: 'upload', title: 'Фото 1', stage: 'Загрузка'}), two = Operations.begin({kind: 'upload', title: 'Фото 2', stage: 'Загрузка'});
  out.running = read();
  two.succeed('Готово');
  out.oneLeft = read();
  one.fail('Нет связи');
  out.failed = read();
  await entry.dispatch('click');
  out.opened = [read()[1], body.querySelector('.ops-panel').hidden, body.querySelector('.ops-panel').getAttribute('id')];
  await entry.dispatch('click');
  out.closed = [read()[1], body.querySelector('.ops-panel').hidden];
  // the buttons of a screen that is gone are forgotten; the one of the screen now shown is painted too
  entry.remove();
  const next = Operations.entry();
  body.append(next);
  out.next = next.textContent;
""")
    assert out["idle"] == ["Tasks", "false", "ops-panel", "idle"]
    assert out["running"][0] == "Tasks: running 2" and out["running"][3] == "running"
    assert out["oneLeft"][0] == "Tasks: running 1"
    assert out["failed"][0] == "Tasks: need attention 1" and out["failed"][3] == "attention"
    assert out["opened"] == ["true", False, "ops-panel"] and out["closed"] == ["false", True]
    assert out["next"] == "Tasks: need attention 1"


@node
def test_a_result_goes_on_to_its_screen_when_the_person_is_still_there_and_to_the_panel_when_they_have_left(tmp_path):
    out = run(tmp_path, """
  const items = () => Operations.items().map((o) => [o.title, o.state, (o.open || {}).label, (o.open || {}).route]);
  const control = h('button', {type: 'button'}, 'Загрузить');
  body.append(control);
  ctx.location = ctx.location || {hash: '#/ingest'};
  ctx.location.hash = '#/ingest';
  // still on the screen: the route is gone to, nothing is put in the panel
  let end = App.landing(control);
  out.here = [end.stillHere(), end.go('/ingest?pair=5', {title: 'Пара загружена', message: 'Откройте проверку', openLabel: 'Открыть проверку'}), went.slice(), items()];
  // the address changed meanwhile: the person is not taken anywhere, the result waits in the panel with a button that opens it
  went.length = 0;
  end = App.landing(control);
  ctx.location.hash = '#/devices';
  out.gone = [end.stillHere(), end.go('/ingest?pair=6', {title: 'Пара загружена', message: 'Откройте проверку', openLabel: 'Открыть проверку'}), went.slice(), items()];
  // the control was taken off the page (another screen was drawn at the same address): the same
  ctx.location.hash = '#/ingest';
  const other = h('button', {type: 'button'}, 'Загрузить'); body.append(other);
  end = App.landing(other);
  other.remove();
  out.removed = [end.stillHere(), end.go('/ingest?pair=7', {title: 'Пара загружена', message: 'Откройте проверку'}), went.slice(), items().length];
  // a control that is not on any page (a test, a preview) is never «left»
  end = App.landing(null);
  out.nowhere = [end.stillHere()];
""")
    assert out["here"][:3] == [True, True, ["/ingest?pair=5"]] and out["here"][3] == []
    assert out["gone"][:3] == [False, False, []]
    assert out["gone"][3] == [["Пара загружена", "done", "Открыть проверку", "/ingest?pair=6"]]
    assert out["removed"][:3] == [False, False, []] and out["removed"][3] == 2
    assert out["nowhere"] == [True]


@node
def test_a_watched_number_box_refuses_a_wrong_text_beside_itself_keeps_it_and_applies_only_a_right_one(tmp_path):
    out = run(tmp_path, """
  const applied = [], typed = [];
  const box = h('input', {type: 'number', value: '50'});
  const note = Forms.watch(box, 'power', (v) => applied.push(v), {wrong: (text) => typed.push(text)});
  body.append(box, note);
  const state = () => [box.getAttribute('aria-invalid'), note.textContent, box.value, note.getAttribute('aria-live'), (box.getAttribute('aria-describedby') || '').includes(note.getAttribute('id'))];
  box.value = '150'; await box.dispatch('change');
  out.wrong = [state(), applied.slice(), typed.slice()];
  box.value = '0'; await box.dispatch('change');                                    // power 0 is outside too (the rule starts above 0)
  out.zero = [state()[0], applied.slice()];
  box.value = '12,5'; await box.dispatch('change');                                 // a comma is read as the decimal point
  out.right = [state()[0], state()[1], applied.slice()];
  box.value = '12abc'; await box.dispatch('change');
  out.letters = [state()[0], state()[2], applied.slice()];
""")
    assert out["wrong"][0][0] == "true" and "Entered: 150" in out["wrong"][0][1] and out["wrong"][0][2:] == ["150", "polite", True]
    assert out["wrong"][1:] == [[], ["150"]]                                         # nothing applied; the owner of the control is told what was typed
    assert out["zero"] == ["true", []]
    assert out["right"] == [None, "", [12.5]]
    assert out["letters"][0] == "true" and out["letters"][2] == [12.5]


@node
def test_the_goals_of_a_task_are_read_strictly_with_the_rule_beside_each_box_and_the_typed_text_kept(tmp_path):
    from titanium_platform import tasks
    out = run(tmp_path, """
  serve({'/tasks': {status: 200, json: %s}});
  const chooser = require('vm').runInContext('Tasks', ctx).chooser('text');
  body.append(chooser.el);
  await wait();
  const labelled = (text) => chooser.el.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === text);
  const said = (text) => labelled(text).errorText();
  const height = labelled('Letter height, mm').firstControl(), width = labelled('Line width, mm').firstControl();
  out.rules = [labelled('Letter height, mm').textContent.includes('allowed: greater than 0'), labelled('Letter height, mm').textContent.includes('unit: mm')];
  height.value = '-2'; width.value = '0.3x';
  out.checked = chooser.check();
  out.said = [said('Letter height, mm'), said('Line width, mm'), height.value, width.value, height.getAttribute('aria-invalid')];
  width.value = '0.3'; await width.dispatch('input');
  out.cleared = [said('Line width, mm'), width.getAttribute('aria-invalid')];
  height.value = '1,5'; await height.dispatch('input');
  out.right = [chooser.check(), chooser.body()];
""" % json.dumps(tasks.vocabulary()), scripts=SCRIPTS + ["tasks.js"])
    assert out["rules"] == [True, True]
    assert out["checked"] is False
    assert "Entered: -2" in out["said"][0] and out["said"][1].startswith("Enter a number") and out["said"][2:] == ["-2", "0.3x", "true"]
    assert out["cleared"] == ["", None]
    assert out["right"] == [True, {"task": "text", "task_goals": {"text_height_mm": 1.5, "line_width_mm": 0.3}}]


@node
def test_the_operating_point_form_refuses_wrong_numbers_beside_each_box_sends_nothing_and_sends_the_right_ones_as_typed(tmp_path):
    out = run(tmp_path, """
  const sent = [];
  serve({'/operating-point': (o) => { sent.push(JSON.parse(o.body)); return {status: 200, json: {problems: [], notes: [], output_power_w: 9, pulse_energy_mj: 0.1, areal_energy_j_cm2: 1, coverage_rate_mm2_s: 2}}; }});
  const results = [];
  const calc = require('vm').runInContext('DeviceCalc', ctx).calculator({id: 1, lens: {id: 2}, passport: {pulse_steps: [{pulse_width_ns: 100}, {pulse_width_ns: 200}]}}, (o) => results.push(o));
  body.append(calc);
  const labelled = (text) => calc.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === text);
  const box = (text) => labelled(text).firstControl();
  const press = async () => { await button(calc, 'Calculate').dispatch('click'); await wait(); };
  box('Power').value = '150'; box('Speed').value = '-5'; box('Layer passes').value = '1.5';
  await press();
  out.wrong = [sent.length, labelled('Power').errorText(), labelled('Speed').errorText(), labelled('Layer passes').errorText(), box('Power').value, box('Speed').value];
  box('Power').value = '30'; box('Speed').value = '900'; box('Layer passes').value = '2';
  await press();
  out.right = [sent.length, sent[0], results.length, labelled('Power').errorText()];
""", scripts=SCRIPTS + ["hardware.js", "screens/device-calc.js"])
    assert out["wrong"][0] == 0 and "Allowed" in out["wrong"][1] and "Entered: 150" in out["wrong"][1]
    assert "Entered: -5" in out["wrong"][2] and "whole number" in out["wrong"][3] and out["wrong"][4:] == ["150", "-5"]
    assert out["right"][:1] == [1] and out["right"][1]["power"] == 30 and out["right"][1]["speed"] == 900 and out["right"][1]["passes"] == 2
    assert out["right"][1]["pulse_width"] == 200 and out["right"][2:] == [1, ""]


@node
def test_closing_the_panel_does_not_stop_a_task_and_stopping_says_what_it_does_first(tmp_path):
    out = run(tmp_path, """
  const fd = new FakeForm(); fd.append('photo', {name: 'IMG_1.dng'});
  const sent = App.formProgress('/pairs/7/rephotos', fd, () => {}).catch((e) => e);
  const xhr = FakeXhr.all[0];
  xhr.progress(30, 100);
  Operations.open(true);
  Operations.open(false);                                                                    // closing the list
  out.closed = {aborted: !!xhr.aborted, state: Operations.items()[0].state};
  Operations.open(true);
  const dock = body.querySelector('.ops-dock');
  await button(body.querySelector('.ops-item'), 'Stop').dispatch('click');
  const dialog = body.querySelector('.modal');
  out.asked = {aborted: !!xhr.aborted, title: dialog.getAttribute('aria-label'), text: dialog.querySelector('p').textContent,
    buttons: dialog.querySelectorAll('button').map((b) => b.textContent), dockInert: dock.hasAttribute('inert'), toastsInert: body.querySelector('.toasts') ? body.querySelector('.toasts').hasAttribute('inert') : false};
  Operations.announce('проверка'); out.said_in_dialog = body.querySelector('.toasts').querySelectorAll('p').map((p) => p.textContent).includes('проверка');
  await button(dialog, 'Stop').dispatch('click'); await wait();
  const error = await sent;
  out.stopped = {aborted: !!xhr.aborted, kind: error.kind, state: Operations.items()[0].state, result: Operations.items()[0].result, dockInert: dock.hasAttribute('inert')};
""")
    assert out["closed"] == {"aborted": False, "state": "running"}
    assert out["asked"]["aborted"] is False and out["asked"]["title"] == "Stop: Uploading repeat photograph?"
    assert out["asked"]["text"] == ("The upload will stop before the server receives the entire file, so the photograph will not be added. "
                                    "You will need to choose the file again.")
    assert out["asked"]["buttons"] == ["×", "Cancel", "Stop"] and out["asked"]["dockInert"] is True and out["asked"]["toastsInert"] is False
    assert out["said_in_dialog"] is True                                                                   # the announcement area stays reachable
    assert out["stopped"] == {"aborted": True, "kind": "cancelled", "state": "cancelled", "result": "Upload stopped; the file was not added.", "dockInert": False}


RECHECK = """
  const photos = (n) => [{status: 'replaced'}, {status: 'kept'}, {status: 'failed'}].slice(0, n);
  const report = (extra) => ({id: 3, total: 3, done: 0, elapsed_s: 0, current: null, photos: [], phase: 'backup', status: 'running', error: null, ...extra});
  let step = 0, stops = 0;
  const steps = [report({phase: 'remeasure', done: 1, current: {title: 'Пластина А', pair_id: 4}, elapsed_s: 10}),
    report({phase: 'remeasure', done: 2, current: {title: 'Пластина Б', pair_id: 5}, elapsed_s: 20}),
    report({phase: 'analysis', done: 3, elapsed_s: 30, photos: photos(3)}),
    report({phase: 'done', status: 'done', done: 3, elapsed_s: 31, photos: photos(3)})];
  serve({'/recheck': () => ({status: 202, json: report({})}), '/recheck/3': () => ({status: 200, json: GATE ? GATE() : steps[Math.min(step++, steps.length - 1)]}),
    '/recheck/3/stop': () => { stops += 1; return {status: 200, json: {}}; }});
"""


@node
def test_a_recheck_is_followed_after_the_screen_that_started_it_is_gone_and_announced_by_stage(tmp_path):
    out = run(tmp_path, "const GATE = null;" + RECHECK + """
  ctx.location.hash = '#/findings';
  await App.post('/recheck', {});                                                              // the findings screen starts it and may leave at once
  const op = () => Operations.items()[0];
  out.started = {title: op().title, stage: op().stage, progress: op().progress, cancel: !!op().cancel, details: op().details, where: op().context.route};
  await until(() => op().state !== 'running');
  out.end = {state: op().state, result: op().result, progress: op().progress, polls: calls.filter((c) => c === 'GET /recheck/3').length};
  out.spoken = spoken();
""")
    assert out["started"] == {"title": "Rechecking all work", "stage": "Backing up the workshop", "progress": None, "cancel": True,
                              "details": [["Recheck ID", 3]], "where": "/findings"}
    assert out["end"]["state"] == "done" and out["end"]["progress"] is None and out["end"]["polls"] >= 3
    assert out["end"]["result"] == "Recheck finished: replaced 1, kept 1, failed 1. Findings recalculated."
    assert out["spoken"][0] == "Rechecking all work: Backing up the workshop"
    # one message for the photographs (their numbers change, the stage does not), one for the analysis, one for the end
    assert [m.split(": ", 1)[1].split(" ")[0] for m in out["spoken"][1:]] == ["Remeasuring", "Recalculating", "Recheck"]
    assert len(out["spoken"]) == 4


@node
def test_stopping_a_recheck_explains_the_backup_first_and_waits_for_the_server_to_confirm(tmp_path):
    out = run(tmp_path, "let gateState = 'running'; const GATE = () => (gateState === 'running' ? {id: 3, total: 3, done: 1, elapsed_s: 5, current: null, photos: [], phase: 'remeasure', status: 'running', error: null} : {id: 3, total: 3, done: 1, elapsed_s: 9, current: null, phase: 'cancelled', status: 'cancelled', error: null, photos: [{status: 'replaced'}]});" + RECHECK + """
  await App.post('/recheck', {});
  const op = Operations.items()[0];
  Operations.open(true);
  await button(body.querySelector('.ops-item'), 'Stop').dispatch('click');
  const dialog = body.querySelector('.modal');
  out.text = dialog.querySelector('p').textContent;
  out.before = {stops, calls: calls.filter((c) => c.endsWith('/stop')).length};
  await button(dialog, 'Stop').dispatch('click'); await wait();
  out.asked = {stops, stopping: op.stopping, state: op.state, stage: body.querySelector('.ops-stage').textContent, stop: body.querySelector('.ops-item').querySelectorAll('button').find((b) => b.textContent === 'Stop').disabled};
  gateState = 'cancelled';
  await until(() => op.state !== 'running');
  out.end = {state: op.state, result: op.result};
""")
    assert out["text"] == ("The recheck will stop after the current photograph. Already remeasured photographs remain replaced and "
                           "findings will use those measurements. The previous state can only be restored from the backup made at the start.")
    assert out["before"] == {"stops": 0, "calls": 0}
    assert out["asked"]["stops"] == 1 and out["asked"]["stopping"] is True and out["asked"]["state"] == "running" and out["asked"]["stop"] is True
    assert out["asked"]["stage"].endswith("(stop requested)")
    assert out["end"] == {"state": "cancelled", "result": "Recheck stopped: replaced 1, kept 0, failed 0. Findings use the measurements completed so far."}


@node
def test_the_connection_of_a_release_reports_failure_with_the_way_back_and_a_stop_leaves_nothing_connected(tmp_path):
    out = run(tmp_path, """
  const job = (extra) => ({id: 'j1', phase: 'checking', read: 5 * 1048576, total: 10 * 1048576, done: false, error: null, result: null, ...extra});
  let phase = {phase: 'building', read: 10 * 1048576}, started = 0;
  const broken = {phase: 'failed', done: true, error: {code: 'invalid', message: 'the release could not be connected: broken'}};
  serve({'/labs/files/tok/connect': () => ({status: 202, json: job({id: 'j' + (++started)})}), '/labs/jobs/j1': () => ({status: 200, json: job({id: 'j1', ...phase})}),
    '/labs/jobs/j2': () => ({status: 200, json: job({id: 'j2', ...broken})}),
    '/labs/jobs/j1/cancel': () => { phase = {phase: 'cancelled', done: true, error: {code: 'cancelled', message: 'the connection was cancelled: nothing was connected'}}; return {status: 200, json: job(phase)}; }});
  ctx.location.hash = '#/labs';
  await App.post('/labs/files/tok/connect', {});
  const op = Operations.items()[0];
  out.started = {title: op.title, stage: op.stage, progress: op.progress, where: op.context.route};
  Operations.open(true);
  await button(body.querySelector('.ops-item'), 'Stop').dispatch('click');
  out.effect = body.querySelector('.modal').querySelector('p').textContent;
  await button(body.querySelector('.modal'), 'Stop').dispatch('click');
  await until(() => op.state !== 'running');
  out.cancelled = {state: op.state, result: op.result};
  // a second release fails in the check
  await App.post('/labs/files/tok/connect', {});
  const failed = Operations.items()[0];
  await until(() => failed.state !== 'running');
  const row = body.querySelectorAll('.ops-item')[0];                   // the newest is on top
  ctx.location.hash = '#/network';
  const retry = button(row, 'Choose file again');
  out.failed = {state: failed.state, error: failed.error, retry: !retry.hidden, badge: row.querySelector('.pill').textContent, alert: row.querySelector('p.alert') !== null};
  await retry.dispatch('click');
  out.went = ctx.__went;
  out.spoken = spoken().slice(-3);
""")
    assert out["started"] == {"title": "Connecting laboratory release", "stage": "checking file · 5.0 MB of 10.0 MB", "progress": 50, "where": "/labs"}
    assert out["effect"] == ("Connection will stop. Nothing will be connected, the read file will be removed, and workshop data will remain unchanged.")
    assert out["cancelled"] == {"state": "cancelled", "result": "Connection stopped; nothing changed."}
    assert out["failed"]["state"] == "failed" and out["failed"]["retry"] is True and out["failed"]["badge"] == "failed" and out["failed"]["alert"] is True
    assert out["failed"]["error"] == "the release could not be connected: broken"
    assert out["went"] == ["/labs"]                                                                         # back where it was started, to choose the file again
    assert out["spoken"][-1].startswith("Connecting laboratory release: failed.")


@node
def test_a_check_that_the_server_answers_at_the_end_runs_in_the_panel_and_cannot_be_stopped(tmp_path):
    out = run(tmp_path, """
  let release;
  const held = new Promise((r) => { release = r; });
  ctx.fetch = async (url) => { calls.push(String(url)); await held; return {ok: true, status: 200, headers: {get: () => 'application/json'}, json: async () => ({status: 'Ready to accept'})}; };
  const done = App.post('/pairs/12/check', {});
  await wait();
  const op = Operations.items()[0];
  Operations.open(true);
  out.running = {title: op.title, details: op.details, stop: !button(body.querySelector('.ops-item'), 'Stop') || body.querySelector('.ops-item').querySelectorAll('button').find((b) => b.textContent === 'Stop').hidden};
  release(); await done; await wait();
  out.end = {state: op.state, result: op.result};
""")
    assert out["running"] == {"title": "Checking uploaded photograph", "details": [["Pair (photo and engraving)", "#12"]], "stop": True}
    assert out["end"] == {"state": "done", "result": "Check finished"}


@node
def test_a_server_that_stops_answering_is_waited_for_and_then_reported_not_forgotten(tmp_path):
    out = run(tmp_path, """
  const report = {id: 3, total: 3, done: 1, elapsed_s: 5, current: null, photos: [], phase: 'remeasure', status: 'running', error: null};
  let alive = true;
  serve({'/recheck': () => ({status: 202, json: report}), '/recheck/3': () => (alive ? {status: 200, json: report} : {status: 503, json: {error: 'down'}})});
  await App.post('/recheck', {});
  const op = Operations.items()[0];
  await wait(5);
  alive = false;
  await until(() => op.state !== 'running');
  out.end = {state: op.state, error: op.error, button: body.querySelector('.ops-toggle').textContent, attention: body.querySelector('.ops-dock').getAttribute('data-state')};
""")
    assert out["end"] == {"state": "failed", "error": "The task result is unknown because the service is not responding. Open the section to check the result.",
                          "button": "Tasks — need attention: 1", "attention": "attention"}


@node
def test_the_clock_of_a_task_is_for_the_eyes_only(tmp_path):
    out = run(tmp_path, """
  const sent = App.formProgress('/pairs', new FakeForm(), () => {});
  Operations.open(true);
  const clock = body.querySelector('.ops-item').querySelectorAll('span').find((s) => s.textContent.startsWith('Running'));
  out.clock = {hidden: clock.getAttribute('aria-hidden'), text: /^Running \\d+:\\d\\d$/.test(clock.textContent)};
  out.live = body.querySelector('.ops-panel').getAttribute('aria-live');
  FakeXhr.all[0].progress(50, 100); FakeXhr.all[0].finish(201, {});
  await sent;
  out.spoken = spoken().filter((m) => /\\d+:\\d\\d/.test(m));
""")
    assert out["clock"] == {"hidden": "true", "text": True} and out["live"] is None and out["spoken"] == []


# -- REQ-003: fields that say what they want and where they are wrong -----------------------------------------------------------------
@node
def test_a_field_made_the_old_way_is_drawn_exactly_as_before(tmp_path):
    out = run(tmp_path, """
  const input = h('input', {value: 'x'});
  const plain = App.field('Название', input);
  const helped = App.field('Название', h('input'), 'подсказка');
  const tree = (el) => ({tag: el.localName, cls: el.className, attrs: [...el.attrs.keys()].sort(), kids: el.childNodes.map((n) => (n.nodeType === 3 ? n.data : tree(n)))});
  out.plain = tree(plain);
  out.helped = tree(helped);
  out.input_attrs = [...input.attrs.keys()];
""")
    assert out["plain"] == {"tag": "label", "cls": "f", "attrs": ["class"],
                            "kids": [{"tag": "span", "cls": "", "attrs": [], "kids": ["Название"]}, {"tag": "input", "cls": "", "attrs": [], "kids": []}]}
    assert out["helped"]["kids"][2] == {"tag": "span", "cls": "small muted", "attrs": ["class"], "kids": ["подсказка"]}
    assert out["input_attrs"] == []                                                                         # nothing was added to a control that asked for nothing


@node
def test_a_field_names_its_control_by_the_label_and_describes_it_with_unit_range_and_error(tmp_path):
    out = run(tmp_path, """
  const input = h('input', {type: 'number', value: '0'});
  body.append(h('div', {}, 'x'));
  const el = App.field('Ширина картинки', input, 'на титане', {required: true, unit: 'мм', constraint: 'допустимо: from 1 to 1000'});
  body.append(el);
  const byId = (id) => body.querySelectorAll('[id]').find((n) => n.getAttribute('id') === id);
  const names = (attr) => (input.getAttribute(attr) || '').split(' ').filter(Boolean).map((id) => byId(id).textContent);
  out.draw = {text: el.textContent, labelledby: names('aria-labelledby'), describedby: names('aria-describedby'), required: input.getAttribute('aria-required'),
    unit: el.querySelector('.f-unit').getAttribute('aria-hidden')};
  el.setError('Allowed: from 1 to 1000 мм. Entered: 0');
  out.error = {describedby: names('aria-describedby'), invalid: input.getAttribute('aria-invalid'), value: input.value, cls: el.className, text: el.errorText(),
    beside: el.lastChild.className.includes('f-error')};
  el.setError('Другое сообщение');
  out.again = {errors: el.querySelectorAll('.f-error').length, describedby: names('aria-describedby').length};
  el.clearError();
  out.cleared = {describedby: names('aria-describedby'), invalid: input.getAttribute('aria-invalid'), value: input.value, cls: el.className, first: el.firstControl() === input};
""")
    assert out["draw"] == {"text": "Ширина картинкиrequiredмм" "unit: мм · допустимо: from 1 to 1000" "на титане", "labelledby": ["Ширина картинки"],
                           "describedby": ["unit: мм · допустимо: from 1 to 1000", "на титане"], "required": "true", "unit": "true"}
    assert out["error"] == {"describedby": ["unit: мм · допустимо: from 1 to 1000", "на титане", "Allowed: from 1 to 1000 мм. Entered: 0"], "invalid": "true",
                            "value": "0", "cls": "f has-error", "text": "Allowed: from 1 to 1000 мм. Entered: 0", "beside": True}
    assert out["again"] == {"errors": 1, "describedby": 3}
    assert out["cleared"] == {"describedby": ["unit: мм · допустимо: from 1 to 1000", "на титане"], "invalid": None, "value": "0", "cls": "f", "first": True}


@node
def test_numbers_are_read_strictly_and_a_wrong_value_is_refused_not_corrected(tmp_path):
    out = run(tmp_path, """
  const Q = Forms.QUANTITIES;
  const read = (text, q, o) => { const r = Forms.parse(text, q, o); return r.ok ? r.value : r.message; };
  out.power = ['', '0', '0.1', '100', '100.5', '-3', 'abc', '12abc', '0x10', 'Infinity', '1e1', '12,5'].map((t) => read(t, Q.power, {}));
  out.empty = [read('', Q.power, {}), read('  ', Q.power, {required: true})];
  out.passes = ['1', '2.5', '0', '3'].map((t) => read(t, Q.passes, {}));
  out.width = ['1', '1000', '1000.01', '0.99'].map((t) => read(t, Q.pictureWidth, {}));
  out.device = [read('60', Q.frequency, {min: 20, max: 48}), read('48', Q.frequency, {min: 20, max: 48}), read('20', Q.frequency, {min: 20, max: 48})];
  const bad = h('input', {type: 'number'}); bad.validity = {badInput: true};
  out.browser_bad_input = Forms.readNumber(bad, Q.power);
  out.words = ['power', 'pictureWidth', 'globalPasses', 'passes', 'focal', 'speed'].map((k) => Forms.constraint(Q[k]));
""")
    assert out["power"] == [None, "Allowed: greater than 0 and at most 100 %. Entered: 0", 0.1, 100, "Allowed: greater than 0 and at most 100 %. Entered: 100.5",
                            "Allowed: greater than 0 and at most 100 %. Entered: -3", "Enter a number, %. Entered: “abc”", "Enter a number, %. Entered: “12abc”",
                            "Enter a number, %. Entered: “0x10”", "Enter a number, %. Entered: “Infinity”", 10, 12.5]
    assert out["empty"] == [None, "Complete this field"]                                                      # an empty optional box is empty, not zero
    assert out["passes"] == [1, "Enter a whole number. Entered: 2.5", "Allowed: whole number, at least 1. Entered: 0", 3]
    assert out["width"] == [1, 1000, "Allowed: from 1 to 1000 mm. Entered: 1000.01", "Allowed: from 1 to 1000 mm. Entered: 0.99"]
    assert out["device"] == ["Allowed: from 20 to 48 kHz. Entered: 60", 48, 20]                              # a laser's own range narrows the general one
    assert out["browser_bad_input"] == {"ok": False, "message": "Enter a number, %"}
    assert out["words"] == ["greater than 0 and at most 100", "from 1 to 1000", "whole number, from 1 to 100", "whole number, at least 1", "from 20 to 1500", "greater than 0"]


FORM = """
  const f = Forms.create();
  const name = h('input'), power = Forms.numberInput(Forms.QUANTITIES.power), width = Forms.numberInput(Forms.QUANTITIES.pictureWidth);
  const box = h('div', {}, f.add('name', 'Название', name, {required: true}), f.add('power', 'Мощность', power, {quantity: 'power', required: true}),
    f.add('width', 'Ширина', width, {quantity: 'pictureWidth', help: 'на титане'}), f.error);
  body.append(box);
  const field = (label) => box.querySelectorAll('label').find((l) => l.firstChild.textContent === label);
"""


@node
def test_a_form_marks_every_bad_field_beside_its_input_keeps_the_typed_text_and_clears_a_mark_when_the_field_is_edited(tmp_path):
    out = run(tmp_path, FORM + """
  power.value = '150'; width.value = '12abc';
  out.values = f.collect();
  out.marks = {name: field('Название').errorText(), power: field('Мощность').errorText(), width: field('Ширина').errorText(),
    invalid: [name, power, width].map((i) => i.getAttribute('aria-invalid')), typed: [name.value, power.value, width.value],
    focus: doc.activeElement === name, form: f.error.textContent, shown: !f.error.hidden, role: f.error.getAttribute('role')};
  power.value = '50'; await power.dispatch('input');
  out.edited = {power: field('Мощность').errorText(), name: field('Название').errorText(), form: f.error.hidden};
  name.value = ' Лазер '; width.value = '';
  out.fixed = f.collect();
  out.after = {marks: [name, power, width].map((i) => i.getAttribute('aria-invalid')), form: f.error.hidden};
""")
    assert out["values"] is None
    assert out["marks"]["name"] == "Complete this field" and out["marks"]["power"] == "Allowed: greater than 0 and at most 100 %. Entered: 150"
    assert out["marks"]["width"] == "Enter a number, mm. Entered: “12abc”"
    assert out["marks"]["invalid"] == ["true", "true", "true"] and out["marks"]["typed"] == ["", "150", "12abc"] and out["marks"]["focus"] is True
    assert out["marks"]["form"] == "Not submitted: correct fields “Название”, “Мощность”, “Ширина”. Your entries remain in the form." and out["marks"]["role"] == "alert"
    assert out["edited"] == {"power": "", "name": "Complete this field", "form": True}
    assert out["fixed"] == {"name": "Лазер", "power": 50, "width": None} and out["after"] == {"marks": [None, None, None], "form": True}


@node
def test_what_the_server_says_goes_beside_the_field_it_names_else_it_stays_on_the_form_with_what_to_do(tmp_path):
    out = run(tmp_path, FORM + """
  name.value = 'Лазер'; power.value = '50';
  f.fail(Object.assign(new Error('Check the form fields'), {details: [{field: 'power', message: 'Value must be greater than 0'}, {field: 'passport', message: 'Complete this field'}]}));
  out.named = {power: field('Мощность').errorText(), name: field('Название').errorText(), form: f.error.textContent, focus: doc.activeElement === power, typed: [name.value, power.value]};
  f.clear();
  f.fail(Object.assign(new Error('Название уже занято'), {kind: 'invalid', status: 422}));
  out.refusal = {form: f.error.textContent, marks: [field('Название').errorText(), field('Мощность').errorText()], typed: [name.value, power.value]};
  f.fail(Object.assign(new Error('Cannot reach the local service. Is the application running?'), {kind: 'network'}));
  out.network = f.error.textContent;
""")
    assert out["named"] == {"power": "Value must be greater than 0", "name": "", "focus": True, "typed": ["Лазер", "50"],
                            "form": "The server rejected field “Мощность”: correct it and submit again. Also: Complete this field."}
    assert out["refusal"] == {"form": "The server rejected the data: Название уже занято. Your entries remain in the form; correct them and submit again.",
                              "marks": ["", ""], "typed": ["Лазер", "50"]}
    assert out["network"].startswith("Could not submit: Cannot reach the local service.") and out["network"].endswith("correct them and submit again.")


@node
def test_the_transport_keeps_which_fields_the_server_refused_and_a_refusal_without_fields_has_none(tmp_path):
    out = run(tmp_path, """
  serve({'/devices': () => ({status: 422, json: {detail: [
      {loc: ['body', 'power'], msg: 'Input should be greater than 0', type: 'greater_than', ctx: {gt: 0}},
      {loc: ['body', 'passport', 'rated_power_w'], msg: 'Field required', type: 'missing'},
      {loc: ['body', 'frequency'], msg: 'Input should be a valid number', type: 'float_parsing'},
      {loc: ['query', 'limit'], msg: 'x', type: 'less_than_equal', ctx: {le: 10}}]}}),
    '/pairs': () => ({status: 422, json: {error: 'the width of the picture must be 1..1000 mm', kind: 'invalid'}})});
  const e1 = await App.post('/devices', {}).catch((e) => e);
  const e2 = await App.post('/pairs', {}).catch((e) => e);
  out.list = {message: e1.message, status: e1.status, details: e1.details.map((d) => [d.field, d.path, d.message])};
  out.user = {message: e2.message, kind: e2.kind, details: e2.details === undefined};
""")
    assert out["list"] == {"message": "Check the form fields", "status": 422,
                           "details": [["power", "power", "Value must be greater than 0"], ["rated_power_w", "passport.rated_power_w", "Complete this field"],
                                       ["frequency", "frequency", "Enter a number"], ["limit", "limit", "Value must be at most 10"]]}
    assert out["user"] == {"message": "the width of the picture must be 1..1000 mm", "kind": "invalid", "details": True}


@node
def test_the_four_words_are_explained_through_the_task_with_the_number_in_the_details(tmp_path):
    out = run(tmp_path, """
  const note = Terms.note('pair', 12);
  body.append(note);
  out.say = ['pair', 'knowledge', 'stage', 'basis'].map((k) => Terms.say(k));
  out.note = {summary: note.querySelector('summary').textContent, paragraphs: note.querySelectorAll('p').map((p) => p.textContent), open: note.localName};
  out.without = Terms.note('basis').querySelectorAll('p').length;
  out.unknown = (() => { try { Terms.about('nonsense'); return null; } catch (e) { return e.message; } })();
""")
    assert out["say"] == ["photo and engraving (pair)", "record of tested settings (knowledge)", "how thoroughly the record has been checked (stage)", "what supports the result (evidence)"]
    assert out["note"]["summary"] == "What is a pair?" and out["note"]["open"] == "details"
    assert out["note"]["paragraphs"][0].startswith("A pair is an engraved plate and its photograph") and out["note"]["paragraphs"][1] == "Technical identifier: pair #12"
    assert out["without"] == 1 and out["unknown"] == "unknown term nonsense"


# -- the quantities against the rules of the server, at their edges ---------------------------------------------------------------------
def _server_verdicts():
    """For each quantity: for each probe value, whether the server's own check accepts it (the places named in forms.js)."""
    import tempfile
    from titanium_platform import designer, devices, findings, ingest, lan, lenses, matrix, photo_state, plans, prediction_store, setup, tasks
    from titanium_platform.db import Store
    su = setup
    store = Store(tempfile.mkdtemp())
    from titanium_platform.prediction_store import PredictionError

    def accepts(call):
        try:
            return call() in (None, [], True) or call() is not None
        except (su.ValidationError, PredictionError, ValueError):
            return False

    passport = {"repetition_rate_khz": {"min": 1.0, "max": 4000.0}, "pulse_steps": [{"pulse_width_ns": 1.0, "cutoff_khz": None}, {"pulse_width_ns": 500.0, "cutoff_khz": 40.0}]}

    def past_the_check(call):
        """For a rule that sits at the head of a longer function: True when the call is refused later for another reason (a missing store)."""
        try:
            call()
        except (su.ValidationError, designer.DesignerError, PredictionError, ValueError):
            return False
        except Exception:                                                   # noqa: BLE001 - the rule under test passed; the rest of the function needs a real store
            return True
        return True

    def _proposal_size(v):
        return past_the_check(lambda: designer.propose(None, 1, None, 200.0, 0.025, 1, size=v))

    def _proposal_seed(v):
        return past_the_check(lambda: designer.propose(None, 1, None, 200.0, 0.025, 1, seed=v))

    def _grid_setup():
        return {"device": {"passport": passport}}

    def _grid(cell, gap):
        return past_the_check(lambda: plans.build_grid(_grid_setup(), [10], [80], 900, cell, cell, gap, 200, 0.025, 1))
    stub = {"rated_power_w": 60.0, "repetition_rate_khz": {"min": 1.0, "max": 4000.0}, "pulse_steps": [{"pulse_width_ns": 1.0, "cutoff_khz": None}]}
    def _overlay(**kw):
        try:
            ingest._overlay_override({}, **kw)
        except ingest.IngestError as e:                                    # past the range checks the call stops for want of an aligned photograph
            return "must be between" not in str(e)
        return True

    base_matrix = {"cols": 2, "rows": 2, "H": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                   "spec": {"x": {"param": "power", "values": None}, "y": {"param": "speed", "values": None}, "fixed": {}, "pitch_mm": 5.0}}

    def _matrix_edit(edit):
        try:
            matrix.apply_edit(base_matrix, edit)
        except ValueError:
            return False
        return True
    def _tone(name):
        def check(v):
            try:
                photo_state.tone_in({}, {name: v})
            except su.ValidationError:
                return False
            return True
        return check

    def _sharpness(v):
        return past_the_check(lambda: photo_state.change(None, {"tone": {}}, {"sharpness": v}, None, 100.0))
    import numpy as np
    from titanium_platform import colormap, conversion, vector_job, vectorize

    def accepts_with(*errors):
        def run(call):
            try:
                call()
            except errors:
                return False
            return True
        return run
    picture = np.zeros((4, 4, 3), np.uint8)

    def _smoothing(v):
        """vector_job.smooth reads the work first; the work is a stand-in, the rule is the one under test (a refusal is a ConversionError)."""
        from unittest import mock
        with mock.patch.object(vector_job, "_photo_job", return_value={}):
            return past_the_check_errors((conversion.ConversionError,), lambda: vector_job.smooth(None, 1, v))

    def _split_colours(v):
        document = {"regions": [{"id": "r1"}], "palette": []}
        return past_the_check_errors((conversion.ConversionError,), lambda: vector_job._split_region({"markers_enabled": False}, document, [], {"region": "r1", "colours": v}))

    def past_the_check_errors(errors, call):
        try:
            call()
        except errors:
            return False
        except Exception:                                                   # noqa: BLE001 - the rule under test passed; the rest needs a real work
            return True
        return True

    def _rule(**kw):
        import obs
        world = obs.setup(store)
        try:
            setup.save_rules(store, *world["setup"], **kw)
        except su.ValidationError:
            return False
        return True

    def _lookup(**kw):
        from pydantic import ValidationError
        from titanium_platform.api.routes_devices import ResultLookupIn
        body = {"power": 20.0, "frequency": 40.0, "speed": 900.0, "pulse_width": 200.0, "line_interval": 0.05, "passes": 1, **kw}
        try:
            ResultLookupIn(**body)
        except ValidationError:
            return False
        return True
    def _marker(**kw):
        body = {"power": 20.0, "frequency": 40.0, "speed": 900.0, **kw}
        try:
            plans.save_marker_layer_settings(store, **body)
        except (su.ValidationError, ValueError):
            return False
        return True
    from titanium_platform import model as colour_model

    def _search_target(**kw):
        lab = {"L": 40.0, "a": 5.0, "b": 15.0, **kw}
        try:
            colormap.search(store, [lab["L"], lab["a"], lab["b"]])
        except Exception:                                                   # noqa: BLE001 - any refusal of the search counts
            return False
        return True
    from titanium_platform import capability_plates as cp, lettering
    # a laser whose range of frequency is wide, so that only the rule of the quantity itself (positive) is left to judge
    wide = {"repetition_rate_khz": {"min": 0.0001, "max": 1e9}, "pulse_steps": passport["pulse_steps"]}
    plate_base = {"power": 20.0, "frequency": 48.0, "speed": 900.0, "pulse_width": 200.0, "line_interval": 0.025, "passes": 1, "global_passes": 1}

    def _plate(**kw):
        try:
            cp._passport_defaults(wide, {**plate_base, **kw})
        except su.ValidationError:
            return False
        return True

    def _plate_size(v):
        """capability_plates.preview judges the size before it builds anything: the builder is replaced by one that stops the call after the check."""
        from unittest import mock
        import obs
        world = obs.setup(store)
        material = setup.save_material(store, "plate stock")

        def stop(*_):
            raise RuntimeError("past the check")
        with mock.patch.dict(cp.BUILDERS, {"calibration": stop}):
            for axis in ("max_width_mm", "max_height_mm"):
                try:
                    cp.preview(store, world["device"]["id"], material["id"], "calibration", {**plate_base, axis: v})
                except su.ValidationError:
                    return False
                except RuntimeError:
                    continue
        return True

    def _axis(axis, companion, geometry="line"):
        """A value on an axis of the matrix is judged with a partner that lies inside (the lower end must lie below the upper)."""
        def check(v):
            low, high = (v, companion) if v < companion else (companion, v)
            other = "speed" if axis != "speed" else "power"
            return accepts_with(su.ValidationError)(lambda: cp._matrix_settings(
                {"matrix": {"x_axis": axis, "y_axis": other, "geometry": geometry, "x_min": low, "x_max": high}}, passport))
        return check

    def _matrix_key(**kw):
        return accepts_with(su.ValidationError)(lambda: cp._matrix_settings({"matrix": kw}, passport))
    grey_values = cp._passport_defaults(wide, {**plate_base, "speed": 150.0, "line_interval": 0.0169})[0]

    def _grey_power(v):
        low, high = (v, 50.0) if v < 50 else (50.0, v)
        return past_the_check_errors((su.ValidationError,), lambda: cp._grey_scales({**grey_values, "scales": {"min_power": low, "max_power": high}}, passport))

    def _copy_size(v):
        from unittest import mock
        with mock.patch.object(cp, "_variation_picture", return_value=np.zeros((20, 20, 3), np.uint8)):
            return past_the_check_errors((su.ValidationError,), lambda: cp._photo_variations({**grey_values, "variations": {"picture_png": "x", "copy_mm": v}}, passport))

    def _copy_min(v):
        return accepts_with(su.ValidationError)(lambda: cp._variant({"min_power": v}, {**grey_values, "dither": "grayscale"}, wide, 1))
    checks = {
        "platePower": lambda v: _plate(power=v), "plateSpeed": lambda v: _plate(speed=v), "plateInterval": lambda v: _plate(line_interval=v),
        "platePasses": lambda v: _plate(passes=v) and _plate(global_passes=v), "plateSize": _plate_size,
        "matrixPoints": lambda v: _matrix_key(x_count=v, y_count=2), "wobbleStep": lambda v: _matrix_key(wobble_step=v),
        "plateAxisPower": _axis("power", 50.0), "plateAxisSpeed": _axis("speed", 5000.0), "plateAxisInterval": _axis("line_interval", 0.3, "fill"),
        "plateAxisPasses": _axis("passes", 10.0), "plateAxisWobble": _axis("wobble_size", 0.3),
        "greyPower": _grey_power,
        "rampWidth": lambda v: accepts_with(su.ValidationError)(lambda: cp._grey_axis("columns", {"axis": "width", "values": [v]}, grey_values, wide)),
        "fillWidth": lambda v: accepts_with(su.ValidationError)(lambda: cp._fill_widths([v])),
        "copySize": _copy_size, "copyMinPower": _copy_min,
        **{key: (lambda name: lambda v: accepts_with(su.ValidationError)(lambda: lettering._number(v, name)))(name) for key, name in (
            ("letterHeight", "height_mm"), ("letterWidth", "width_pct"), ("letterSpacing", "spacing_mm"), ("lineSpacing", "line_pct"), ("letterRotation", "rotation"),
            ("letterBend", "bend"), ("circleRadius", "radius_mm"), ("circleStart", "start_deg"), ("pathOffset", "offset_pct"), ("letterGap", "gap_mm"),
            ("backingPadding", "padding_mm"), ("backingCorner", "corner_mm"), ("letterX", "x"), ("letterY", "y"))},
        "pathPoint": lambda v: accepts_with(su.ValidationError)(lambda: lettering._points([[v, 0]])),
        "dotWidth": lambda v: accepts_with(su.ValidationError)(lambda: photo_state.dot_width_in(v)),
        "predictL": lambda v: accepts_with(ValueError)(lambda: colour_model.predict_for_lab([], [v, 0, 0])),
        "predictAB": lambda v: accepts_with(ValueError)(lambda: colour_model.predict_for_lab([], [50, v, v])),
        "targetL": lambda v: _search_target(L=v), "targetAB": lambda v: _search_target(a=v, b=v),
        "searchTolerance": lambda v: accepts_with(su.ValidationError)(lambda: colormap.delta_tolerance(v)),
        "bandCount": lambda v: accepts_with(conversion.ConversionError)(lambda: conversion._check_bands(v)),
        "markerPower": lambda v: _marker(power=v), "markerFrequency": lambda v: _marker(frequency=v), "markerSpeed": lambda v: _marker(speed=v),
        "markerPulse": lambda v: _marker(pulse_width=v), "markerInterval": lambda v: _marker(line_interval=v), "markerPasses": lambda v: _marker(passes=v),
        "workWidth": lambda v: accepts_with(conversion.ConversionError)(lambda: conversion.raster(picture[:, :, ::-1].copy(), v)),
        "photoColours": lambda v: accepts_with(conversion.ConversionError)(lambda: vector_job._split_settings({"n_colors": v}, False, [])),
        "maxTime": lambda v: accepts_with(su.ValidationError)(lambda: colormap.time_limit(v)),
        "vectorTolerance": lambda v: accepts_with(vectorize.VectorizeError)(lambda: vectorize._number(v, "the tolerance")),
        "greyThreshold": lambda v: accepts_with(vectorize.VectorizeError)(lambda: vectorize._binarise(picture, v)),
        "deltaE": lambda v: accepts_with(conversion.ConversionError)(lambda: conversion._threshold(store, 1, None, v)),
        "toneBrightness": _tone("brightness"), "toneContrast": _tone("contrast"), "toneGamma": _tone("gamma"), "sharpness": _sharpness,
        "matrixCount": lambda v: _matrix_edit({"extent": {"cols": v, "rows": 1}}),
        "matrixShift": lambda v: float(v).is_integer() and _matrix_edit({"extent": {"col_shift": v}}),     # a fraction the server would cut off is refused by the form
        "matrixSetting": lambda v: _matrix_edit({"fixed": {"passes": v}}),
        "matrixPitch": lambda v: _matrix_edit({"pitch_mm": v}),
        "schemeRotation": lambda v: _overlay(rotation_degrees=v),
        "schemeScale": lambda v: _overlay(scale_factor=v / 100),
        "power": lambda v: not setup.check_in_range(passport, v, None),
        "photoPower": lambda v: accepts(lambda: prediction_store.check_power_range(v, 100)) and accepts(lambda: prediction_store.check_power_range(0, v)),
        "pictureWidth": lambda v: accepts(lambda: prediction_store.check_width(v)),
        "globalPasses": lambda v: accepts(lambda: plans.scan_settings({"global_passes": v})),
        "passes": lambda v: accepts(lambda: setup.job_settings(passport, 200.0, 0.05, v)),
        "speed": lambda v: accepts(lambda: su._finite(v, "speed", True)),
        "lineInterval": lambda v: accepts(lambda: setup.job_settings(passport, 200.0, v, 1)),
        "pulseWidth": lambda v: accepts(lambda: su._finite(v, "pulse width", True)),
        "frequency": lambda v: accepts(lambda: su._finite(v, "frequency", True)),
        "ratedPower": lambda v: accepts(lambda: devices.validate_passport({**stub, "rated_power_w": v})),
        "wavelength": lambda v: accepts(lambda: devices.validate_passport({**stub, "wavelength_nm": v})),
        "repetitionRate": lambda v: accepts(lambda: devices.validate_passport({**stub, "repetition_rate_khz": {"min": v, "max": v + 1000}})),
        "cutoff": lambda v: accepts(lambda: devices.validate_passport({**stub, "pulse_steps": [{"pulse_width_ns": 1.0, "cutoff_khz": v}]})),
        "m2": lambda v: accepts(lambda: devices.validate_passport({**stub, "m2": v})),
        "beamDiameter": lambda v: accepts(lambda: devices.validate_passport({**stub, "beam_diameter_mm": v})),
        "labL": lambda v: accepts(lambda: tasks.clean_goals("fill", {"target_lab": [v, 0, 0]})),
        "labAB": lambda v: accepts(lambda: tasks.clean_goals("fill", {"target_lab": [50, v, v]})),
        "lineWidth": lambda v: accepts(lambda: tasks.clean_goals("line", {"line_width_mm": v})),
        "textHeight": lambda v: accepts(lambda: tasks.clean_goals("text", {"text_height_mm": v})),
        "analysisInterval": lambda v: accepts(lambda: findings.set_interval(store, v)),
        "proposalSize": _proposal_size,
        "seed": _proposal_seed,
        "focus": lambda v: accepts(lambda: ingest.clean_context({"focus": v})),
        "thickness": lambda v: accepts(lambda: setup.save_material(store, "stock", thickness_mm=v)),
        "cellSize": lambda v: _grid(v, 1),
        "gap": lambda v: _grid(6, v),
        "lanPort": lambda v: accepts(lambda: lan.save_settings(store, {"port": v})),
        "focal": lambda v: accepts(lambda: lenses._clean("l", v, None, None, None)),
        "lensField": lambda v: accepts(lambda: lenses._clean("l", None, v, None, None)),
        "expansion": lambda v: accepts(lambda: lenses._clean("l", None, None, v, None)),
        "spot": lambda v: accepts(lambda: lenses._clean("l", None, None, None, None, v)),
        "density": lambda v: accepts_with(conversion.ConversionError)(lambda: vector_job._split_settings({"n_colors": 5, "density": v}, False, [])),
        "smoothing": _smoothing,
        "similarity": lambda v: accepts_with(conversion.ConversionError)(lambda: vector_job._similarity(v)),
        "splitColours": _split_colours,
        "repeatThreshold": lambda v: _rule(repeat_threshold=v),
        "deltaTolerance": lambda v: _rule(delta_tolerance=v),
        "varianceThreshold": lambda v: _rule(variance_threshold=v),
        "lookupPower": lambda v: _lookup(power=v), "lookupFrequency": lambda v: _lookup(frequency=v), "lookupSpeed": lambda v: _lookup(speed=v),
        "lookupPulse": lambda v: _lookup(pulse_width=v), "lookupInterval": lambda v: _lookup(line_interval=v), "lookupPasses": lambda v: _lookup(passes=v),
    }
    return checks


@node
def test_every_unit_and_range_on_a_form_is_the_rule_the_server_enforces_at_its_edges(tmp_path):
    out = run(tmp_path, """
  const probes = {};
  for (const [key, q] of Object.entries(Forms.QUANTITIES)) {
    const d = q.integer ? 1 : 0.01;
    const set = new Set([0, 1, 2, 3, 0.5]);
    for (const end of [q.min, q.max]) if (end != null) for (const v of [end - d, end, end + d]) set.add(+v.toFixed(4));
    probes[key] = [...set].sort((a, b) => a - b).map((v) => [v, Forms.parse(String(v), q, {}).ok]);
  }
  out.probes = probes;
  out.keys = Object.keys(Forms.QUANTITIES);
""")
    checks = _server_verdicts()
    assert set(out["keys"]) == set(checks), "a quantity without a server check is a limit nobody confirmed"
    for key, probes in out["probes"].items():
        for value, form_says in probes:
            server_says = bool(checks[key](value))
            assert form_says == server_says, f"{key} = {value}: the form says {form_says}, the server says {server_says}"


@node
def test_the_upload_form_speaks_its_stage_once_and_keeps_the_counters_for_the_eyes(tmp_path):
    out = run(tmp_path, """
  serve({'/pairs/9/check': () => ({status: 200, json: {status: 'Ready to accept'}})});
  const IngestUpload = require('vm').runInContext('IngestUpload', ctx);
  const rig = {status: 'Accepted', id: 4, hardware: {}, context: {}, lightburn_name: 'a.lbrn2'};
  const form = IngestUpload.rephoto(rig, []);
  body.append(form);
  const input = form.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file');
  input.files = [{name: 'IMG_1.dng'}];
  const live = form.querySelector('.upload-progress').querySelector('p');
  button(form, 'Добавить фотографию и проверить').dispatch('click'); await wait();
  const xhr = FakeXhr.all[0];
  const seen = [];
  for (const percent of [10, 55, 90]) { xhr.progress(percent, 100); seen.push(live.textContent); }
  out.uploading = {role: live.getAttribute('role'), live: live.getAttribute('aria-live'), texts: seen, spoken_text: live.childNodes.filter((n) => n.nodeType === 3).map((n) => n.data),
    hidden: live.querySelectorAll('span').map((s) => s.getAttribute('aria-hidden'))};
  xhr.finish(201, {id: 9}); await wait();
  out.checking = {text: live.textContent, spoken_text: live.childNodes.filter((n) => n.nodeType === 3).map((n) => n.data), hidden: live.querySelectorAll('span').map((s) => s.getAttribute('aria-hidden'))};
  out.panel = Operations.items().map((o) => [o.title, o.state]);
""", scripts=SCRIPTS + ["filepick.js", "screens/ingest-upload.js"])
    assert out["uploading"] == {"role": "status", "live": "polite", "texts": ["Загрузка фотографии: 10 %", "Загрузка фотографии: 55 %", "Загрузка фотографии: 90 %"],
                                "spoken_text": ["Загрузка фотографии: "], "hidden": ["true"]}                  # the words once; the number is not read each time
    assert out["checking"]["text"].endswith(" 0 с") and out["checking"]["hidden"] == ["true"]
    assert len(out["checking"]["spoken_text"]) == 1 and not any(c.isdigit() for c in out["checking"]["spoken_text"][0])
    # the upload and the check that follows it are both in the panel (the screen may be left during either)
    assert out["panel"] == [["Checking uploaded photograph", "done"], ["Uploading repeat photograph", "done"]]


# -- a form of the product moved to the form layer: the laser passport -------------------------------------------------------------------
DEVICE_FORMS = """
  const DeviceForms = require('vm').runInContext('DeviceForms', ctx);
  const finished = [];
  const labelled = (root, text) => root.querySelectorAll('label').find((l) => l.firstChild.textContent === text);
  const inputOf = (root, text) => labelled(root, text).firstControl();
  const post = () => calls.filter((c) => c.startsWith('POST') || c.startsWith('PATCH'));
"""


@node
def test_the_laser_form_refuses_what_is_not_a_number_and_a_step_it_cannot_read_and_keeps_every_typed_value(tmp_path):
    out = run(tmp_path, DEVICE_FORMS + """
  serve({'/devices': () => ({status: 201, json: {id: 5}})});
  const form = DeviceForms.createForm((id) => finished.push(id));
  body.append(form);
  await button(form, 'Create laser').dispatch('click'); await wait();
  out.empty = {posted: post(), marks: ['Name', 'Rated power', 'Repetition frequency from', 'Repetition frequency to', 'Pulse duration steps'].map((l) => labelled(form, l).errorText()),
    error: form.querySelector('.f-form-error').textContent, focus: doc.activeElement === inputOf(form, 'Name')};
  inputOf(form, 'Name').value = 'JPT';
  inputOf(form, 'Rated power').value = '6O';
  inputOf(form, 'Repetition frequency to').value = '4000';
  const steps = inputOf(form, 'Pulse duration steps');
  steps.value = '1 CW\\n20 252\\n5 xyz';
  await button(form, 'Create laser').dispatch('click'); await wait();
  out.typed = {posted: post(), power: labelled(form, 'Rated power').errorText(), steps: labelled(form, 'Pulse duration steps').errorText(),
    values: ['Name', 'Rated power', 'Repetition frequency to'].map((l) => inputOf(form, l).value), stepsText: steps.value,
    unit: labelled(form, 'Rated power').querySelector('.f-unit').textContent, hint: labelled(form, 'Rated power').textContent.includes('allowed: greater than 0')};
  inputOf(form, 'Rated power').value = '60';
  steps.value = '1 CW\\n20 252';
  await button(form, 'Create laser').dispatch('click'); await wait();
  out.sent = {posted: post(), finished};
""", scripts=SCRIPTS + ["screens/device-forms.js"])
    assert out["empty"]["posted"] == [] and out["empty"]["marks"] == ["Complete this field", "Complete this field", "", "Complete this field", ""]
    assert out["empty"]["error"].startswith("Not submitted: correct fields “Name”, “Rated power”, “Repetition frequency to”.") and out["empty"]["focus"] is True
    assert out["typed"]["posted"] == [] and out["typed"]["power"] == "Enter a number, W. Entered: “6O”"
    assert out["typed"]["steps"] == "Line 3: cutoff frequency. Enter a number, kHz. Entered: “xyz”"
    assert out["typed"]["values"] == ["JPT", "6O", "4000"] and out["typed"]["stepsText"] == "1 CW\n20 252\n5 xyz"        # nothing was corrected or dropped
    assert out["typed"]["unit"] == "W" and out["typed"]["hint"] is True
    assert out["sent"]["posted"] == ["POST /devices"] and out["sent"]["finished"] == [5]


@node
def test_a_refusal_of_the_laser_form_by_the_server_stays_on_the_form_with_the_next_step_not_in_a_toast(tmp_path):
    out = run(tmp_path, DEVICE_FORMS + """
  const sent = [];
  serve({'/devices': (opts) => { sent.push(JSON.parse(opts.body)); return sent.length === 1
    ? {status: 422, json: {error: 'maximum repetition rate must be above the minimum', kind: 'invalid'}} : {status: 201, json: {id: 6}}; }});
  const form = DeviceForms.createForm((id) => finished.push(id));
  body.append(form);
  inputOf(form, 'Name').value = 'JPT'; inputOf(form, 'Rated power').value = '60'; inputOf(form, 'Repetition frequency to').value = '1';
  await button(form, 'Create laser').dispatch('click'); await wait();
  out.refused = {error: form.querySelector('.f-form-error').textContent, shown: !form.querySelector('.f-form-error').hidden, toasts: body.querySelectorAll('.toast').length,
    values: ['Name', 'Rated power', 'Repetition frequency to'].map((l) => inputOf(form, l).value), finished: [...finished]};
  inputOf(form, 'Repetition frequency to').value = '4000'; await inputOf(form, 'Repetition frequency to').dispatch('input');
  out.edited = {hidden: form.querySelector('.f-form-error').hidden};
  await button(form, 'Create laser').dispatch('click'); await wait();
  out.second = {finished, passport: sent[1].passport, bodyKeys: Object.keys(sent[1])};
""", scripts=SCRIPTS + ["screens/device-forms.js"])
    assert out["refused"] == {"error": "The server rejected the data: maximum repetition rate must be above the minimum."
                                       " Your entries remain in the form; correct them and submit again.",
                              "shown": True, "toasts": 0, "values": ["JPT", "60", "1"], "finished": []}
    assert out["edited"] == {"hidden": True}
    assert out["second"]["finished"] == [6] and out["second"]["passport"]["repetition_rate_khz"] == {"min": 1, "max": 4000}
    assert out["second"]["passport"]["pulse_steps"] == [{"pulse_width_ns": 1, "cutoff_khz": None}, {"pulse_width_ns": 2, "cutoff_khz": 1950}]


@node
def test_the_passport_edit_form_refuses_a_value_outside_the_rule_and_sends_the_rest_as_it_was(tmp_path):
    out = run(tmp_path, DEVICE_FORMS + """
  const sent = [];
  serve({'/devices/3': (opts) => { sent.push(JSON.parse(opts.body)); return {status: 200, json: {id: 3}}; }});
  const device = {id: 3, serial: 'S1', description: 'd', passport: {m2: 1.3, m2_max: null, beam_diameter_mm: 7, default_pulse_width_ns: 200, open_items: ['a', 'b'],
    pulse_steps: [{pulse_width_ns: 1, cutoff_khz: null}, {pulse_width_ns: 2, cutoff_khz: 1950}], rated_power_w: 60}};
  const form = DeviceForms.editForm(device, (id) => finished.push(id));
  body.append(form);
  inputOf(form, 'Your laser’s M²').value = '-1';
  inputOf(form, 'Pulse duration steps').value = '';
  await button(form, 'Save specifications').dispatch('click'); await wait();
  out.refused = {sent: sent.length, m2: labelled(form, 'Your laser’s M²').errorText(), steps: labelled(form, 'Pulse duration steps').errorText(), m2Value: inputOf(form, 'Your laser’s M²').value};
  inputOf(form, 'Your laser’s M²').value = '1,4';
  inputOf(form, 'Pulse duration steps').value = '1 CW\\n2 1950';
  await button(form, 'Save specifications').dispatch('click'); await wait();
  out.sent = {finished, body: sent[0]};
""", scripts=SCRIPTS + ["screens/device-forms.js"])
    assert out["refused"] == {"sent": 0, "m2": "Allowed: greater than 0. Entered: -1", "steps": "Enter at least one step: pulse duration in ns and cutoff frequency in kHz (or CW)", "m2Value": "-1"}
    assert out["sent"]["finished"] == [3]
    assert out["sent"]["body"] == {"serial": "S1", "description": "d", "passport": {"m2": 1.4, "m2_max": None, "beam_diameter_mm": 7, "default_pulse_width_ns": 200,
                                                                                     "open_items": ["a", "b"], "rated_power_w": 60,
                                                                                     "pulse_steps": [{"pulse_width_ns": 1, "cutoff_khz": None}, {"pulse_width_ns": 2, "cutoff_khz": 1950}]}}


# -- the lens tab on the form layer: its quantities are the ones lenses.py bounds ----------------------------------------------------------
LENS_TAB = """
  const DeviceLens = require('vm').runInContext('DeviceLens', ctx);
  const lens = {id: 4, name: 'F-theta 254', focal_length_mm: null, field_mm: 110, expansion: 1, spot_diameter_um: null, note: null, installed_on: {id: 3, name: 'JPT'}};
  const device = {id: 3, passport: {m2: 1.3, beam_diameter_mm: 7}, lens, characterization: {items: [{key: 'spot_diameter', value: null, waiting_for: ['focal_length'], low: null}], work_field_mm: null}};
  const labelled = (root, text) => root.querySelectorAll('label').find((l) => l.firstChild && l.firstChild.textContent.startsWith(text));
  const inputOf = (root, text) => labelled(root, text).firstControl();
  const writes = () => calls.filter((c) => !c.startsWith('GET'));
  const refreshed = [];
"""


@node
def test_the_rig_form_and_its_chart_reference_say_what_is_wrong_beside_the_box_and_keep_what_was_typed(tmp_path):
    out = run(tmp_path, """
  const SetupForms = require('vm').runInContext('SetupForms', ctx);
  const labelled = (root, text) => root.querySelectorAll('label').find((l) => l.firstChild && l.firstChild.textContent.startsWith(text));
  const inputOf = (root, text) => labelled(root, text).firstControl();
  const writes = () => calls.filter((c) => !c.startsWith('GET'));
  const rig = {id: 5, name: 'Rig', camera: 'cam', lighting: 'LED', angle: '90', reference_chart: 'ColorChecker Classic', legacy: false, last_used: false,
    chart_reference: {published: true, source: 'ColorChecker', white_point: 'D50', observer: '2°', patches_lab: [[1, 2, 3]]}};
  serve({'/setups/5': (opts) => ({status: 400, json: {error: 'camera is required', kind: 'invalid'}}),
         '/setups/5/chart-reference': () => ({status: 400, json: {error: 'the white point must be one of D65, D50', kind: 'invalid'}})});
  const tab = SetupForms.rigsTab([rig], () => {});
  body.append(tab);
  const card = tab.querySelectorAll('.card')[0];
  inputOf(card, 'Camera').value = '   ';
  await button(card, 'Save setup').dispatch('click'); await wait();
  out.empty = {writes: writes(), camera: labelled(card, 'Camera').errorText(), form: card.querySelectorAll('.f-form-error').pop().textContent};
  inputOf(card, 'Camera').value = 'Sony A7';
  await button(card, 'Save setup').dispatch('click'); await wait();
  out.refused = {writes: writes(), form: card.querySelectorAll('.f-form-error').pop().textContent, kept: inputOf(card, 'Camera').value, toasts: body.querySelectorAll('.toast').length};
  // the chart reference: a list of 24 triples, L from 0 to 100, a and b from -128 to 127
  const details = card.querySelector('details');
  const values = details.querySelector('textarea');
  values.value = '[[50, 0, 0]]';
  await button(details, 'Save reference values').dispatch('click'); await wait();
  out.short = {writes: writes().filter((c) => c.includes('chart')), message: labelled(details, 'Reference Lab values').errorText(), kept: values.value};
  values.value = JSON.stringify(Array.from({length: 24}, (_, i) => [i === 3 ? 120 : 50, 0, 0]));
  await button(details, 'Save reference values').dispatch('click'); await wait();
  out.range = labelled(details, 'Reference Lab values').errorText();
""", scripts=SCRIPTS + ["screens/setup-forms.js"])
    assert out["empty"]["writes"] == [] and out["empty"]["camera"] == "Complete this field" and "“Camera”" in out["empty"]["form"]
    assert out["refused"]["writes"] == ["PUT /setups/5"] and out["refused"]["kept"] == "Sony A7" and out["refused"]["toasts"] == 0
    assert "remain in the form" in out["refused"]["form"]                                       # said above the buttons, not in a toast that goes away
    assert out["short"]["writes"] == [] and out["short"]["message"] == "Exactly 24 [L, a, b] triples are required. Current: 1" and out["short"]["kept"] == "[[50, 0, 0]]"
    assert out["range"] == "Triple 4: L must be 0–100 and a and b must be -128–127. Entered: [120, 0, 0]"


@node
def test_the_controller_row_form_says_what_is_wrong_beside_the_box_and_keeps_what_was_typed(tmp_path):
    out = run(tmp_path, """
  const ControllerRows = require('vm').runInContext('ControllerRows', ctx);
  const labelled = (root, text) => root.querySelectorAll('label').find((l) => l.firstChild && l.firstChild.textContent.startsWith(text));
  const inputOf = (root, text) => labelled(root, text).firstControl();
  const fields = [{key: 'Power', value: 20, unit: '%', status: 'confirmed'}];
  let changed = 0;
  const form = ControllerRows.addForm(fields, {change: () => { changed += 1; }});
  body.append(form);
  await button(form, '+ Add').dispatch('click'); await wait();
  out.empty = {key: labelled(form, 'Setting name').errorText(), value: labelled(form, 'Value').errorText(), changed, toasts: body.querySelectorAll('.toast').length,
    form: form.querySelector('.f-form-error').textContent};
  inputOf(form, 'Setting name').value = ' Power ';
  inputOf(form, 'Value').value = '35,5';
  await button(form, '+ Add').dispatch('click'); await wait();
  out.twice = {key: labelled(form, 'Setting name').errorText(), value: labelled(form, 'Value').errorText(), kept: [inputOf(form, 'Setting name').value, inputOf(form, 'Value').value], changed};
  inputOf(form, 'Setting name').value = 'Speed';
  await button(form, '+ Add').dispatch('click'); await wait();
  out.added = {fields, changed};
""", scripts=SCRIPTS + ["screens/glossary-controller.js", "screens/controller-rows.js"])
    assert out["empty"]["key"] == "Enter a setting name" and out["empty"]["value"] == "Enter a setting value" and out["empty"]["changed"] == 0 and out["empty"]["toasts"] == 0
    assert "“Setting name”" in out["empty"]["form"]
    assert out["twice"]["key"] == "This setting already exists in this section" and out["twice"]["value"] == "" and out["twice"]["kept"] == [" Power ", "35,5"] and out["twice"]["changed"] == 0
    assert out["added"]["fields"][1] == {"key": "Speed", "value": 35.5, "unit": None, "status": "confirmed"} and out["added"]["changed"] == 1


@node
def test_legacy_unread_controller_value_is_not_changed_by_an_empty_edit(tmp_path):
    out = run(tmp_path, """
  const ControllerRows = require('vm').runInContext('ControllerRows', ctx);
  const field = {key: 'Power', value: ControllerRows.UNREAD, status: 'handwritten'};
  let changed = 0;
  const row = ControllerRows.row(field, [field], {help: false, change: () => changed++});
  const input = row[1];
  out.before = [input.value, input.getAttribute('placeholder'), field.value === ControllerRows.UNREAD];
  await input.dispatch('change');
  out.after = [input.value, field.value === ControllerRows.UNREAD, changed];
""", scripts=SCRIPTS + ["screens/glossary-controller.js", "screens/controller-rows.js"])
    assert out["before"] == ["", "Not read from photo", True]
    assert out["after"] == ["", True, 0]


@node
def test_the_lens_form_refuses_a_focal_length_outside_the_servers_bounds_and_keeps_what_was_typed(tmp_path):
    out = run(tmp_path, LENS_TAB + """
  const created = [];
  serve({'/lenses': (opts) => opts.method === 'POST' ? (created.push(JSON.parse(opts.body)), {status: 201, json: {id: 9}}) : {status: 200, json: [lens]},
         '/devices/3/lens': () => ({status: 200, json: {}})});
  const tab = await DeviceLens.card(device, (id) => refreshed.push(id));
  body.append(tab);
  const newLens = [...tab.querySelectorAll('.card')].pop();
  inputOf(newLens, 'Name').value = 'F-theta 163';
  inputOf(newLens, 'Focal length').value = '19,9';
  inputOf(newLens, 'Lens field').value = '600';
  inputOf(newLens, 'Beam expander').value = '0';
  await button(newLens, 'Add and install').dispatch('click'); await wait();
  out.refused = {writes: writes(), focal: labelled(newLens, 'Focal length').errorText(), fieldMm: labelled(newLens, 'Lens field').errorText(),
    expansion: labelled(newLens, 'Beam expander').errorText(), name: labelled(newLens, 'Name').errorText(),
    kept: ['Name', 'Focal length', 'Lens field', 'Beam expander'].map((l) => inputOf(newLens, l).value),
    unit: labelled(newLens, 'Focal length').textContent, form: newLens.querySelector('.f-form-error').textContent};
  inputOf(newLens, 'Focal length').value = '254';
  inputOf(newLens, 'Lens field').value = '110';
  inputOf(newLens, 'Beam expander').value = '';
  await button(newLens, 'Add and install').dispatch('click'); await wait();
  out.sent = {created, writes: writes(), refreshed};
""", scripts=SCRIPTS + ["hardware.js", "screens/device-lens.js"])
    assert out["refused"]["writes"] == [] and out["refused"]["name"] == ""
    assert out["refused"]["focal"] == "Allowed: from 20 to 1500 mm. Entered: 19.9"
    assert out["refused"]["fieldMm"] == "Allowed: from 1 to 500 mm. Entered: 600"
    assert out["refused"]["expansion"] == "Allowed: from 0.2 to 20 ×. Entered: 0"
    assert out["refused"]["kept"] == ["F-theta 163", "19,9", "600", "0"]                       # nothing was corrected
    assert "allowed: from 20 to 1500" in out["refused"]["unit"]
    assert out["refused"]["form"] == "Not submitted: correct fields “Focal length”, “Lens field”, “Beam expander”. Your entries remain in the form."
    assert out["sent"]["created"] == [{"name": "F-theta 163", "focal_length_mm": 254, "field_mm": 110, "expansion": 1, "note": None}]
    assert out["sent"]["writes"] == ["POST /lenses", "PUT /devices/3/lens"] and out["sent"]["refreshed"] == [3]


@node
def test_the_spot_form_and_the_focal_dialog_say_what_is_wrong_beside_the_box_and_do_not_close_on_a_refusal(tmp_path):
    out = run(tmp_path, LENS_TAB + """
  const patched = [];
  let focalRefusals = 0;
  serve({'/lenses': {status: 200, json: [lens]}, '/lenses/4': (opts) => { const sent = JSON.parse(opts.body); patched.push(sent);
      return 'focal_length_mm' in sent && focalRefusals++ === 0 ? {status: 422, json: {error: 'focal length must be between 20 and 1500 mm', kind: 'invalid'}} : {status: 200, json: lens}; },
    '/devices/3': () => ({status: 200, json: {}})});
  const tab = await DeviceLens.card(device, (id) => refreshed.push(id));
  body.append(tab);
  // the spot form: a measured spot outside 1..2000 µm is refused beside its box; M² of zero as well
  inputOf(tab, 'Or spot diameter').value = '2500';
  inputOf(tab, 'Your laser’s M²').value = '0';
  await button(tab, 'Save').dispatch('click'); await wait();
  out.spot = {writes: writes(), spot: labelled(tab, 'Or spot diameter').errorText(), m2: labelled(tab, 'Your laser’s M²').errorText(), kept: [inputOf(tab, 'Or spot diameter').value, inputOf(tab, 'Your laser’s M²').value]};
  inputOf(tab, 'Or spot diameter').value = '40';
  inputOf(tab, 'Your laser’s M²').value = '1,3';
  await button(tab, 'Save').dispatch('click'); await wait();
  out.spotSaved = {writes: writes(), refreshed: [...refreshed]};
  // the focal dialog (opened from the list of lenses): empty and then a value the server refuses
  await button(tab, 'Enter focal length').dispatch('click'); await wait();
  const dialog = body.querySelector('.modal');
  await button(dialog, 'Save').dispatch('click'); await wait();
  out.dialogEmpty = {open: !!body.querySelector('.modal'), error: labelled(dialog, 'Focal length').errorText(), patched: patched.length};
  inputOf(dialog, 'Focal length').value = '25';
  await button(dialog, 'Save').dispatch('click'); await wait();
  out.dialogRefused = {open: !!body.querySelector('.modal'), form: dialog.querySelector('.f-form-error').textContent, typed: inputOf(dialog, 'Focal length').value, patched: patched.length};
  await button(dialog, 'Save').dispatch('click'); await wait();
  out.dialogSaved = {open: !!body.querySelector('.modal'), patched, refreshed: [...refreshed]};
""", scripts=SCRIPTS + ["hardware.js", "screens/device-lens.js"])
    assert out["spot"] == {"writes": [], "spot": "Allowed: from 1 to 2000 µm. Entered: 2500", "m2": "Allowed: greater than 0. Entered: 0", "kept": ["2500", "0"]}
    assert out["spotSaved"]["writes"] == ["PATCH /lenses/4"] and out["spotSaved"]["refreshed"] == [3]          # M² is unchanged (1,3 is 1.3): only the spot is written
    assert out["dialogEmpty"] == {"open": True, "error": "Complete this field", "patched": 1}                # the spot saved one lens patch before
    assert out["dialogRefused"]["open"] is True and out["dialogRefused"]["typed"] == "25" and out["dialogRefused"]["patched"] == 2
    assert out["dialogRefused"]["form"].startswith("The server rejected the data: ") and "20" in out["dialogRefused"]["form"]
    assert out["dialogSaved"]["open"] is False and out["dialogSaved"]["patched"][-1] == {"focal_length_mm": 25} and out["dialogSaved"]["refreshed"] == [3, 3]
