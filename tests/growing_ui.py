"""A helper for the UI tests of the growing collections (feature ux-growing-collections-p0): the real application served on a free port of this
computer and the screens run in node over the small DOM of the other screen tests, their requests going to that server. So a catalogue of 2000
records, the history of an entry or the photographs behind observation numbers are read through the real API, not through answers made up
for the test. Only what a real browser, Electron or a screen reader adds (layout, a real cursor, speech) is not covered."""
import json
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

from titanium_platform.api.app import create_app

UI = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui"
TABLES = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-tasks.js", "i18n-data.js", "i18n-findings.js",
          "i18n-palette.js", "i18n-lettering.js", "i18n-gaps.js"]

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

GLUE = ("const __screens = {}, __renders = []; App.register = (d) => { __screens[d.id] = d; }; App.render = () => { __renders.push(1); };"
        "globalThis.__screens = __screens; globalThis.__renders = __renders; App.go = (route) => { globalThis.__went = route; };")

HARNESS = """
const {context, load, El} = require(%(dom)s);
const ctx = context({});
const PORT = %(port)s;
const log = [];                                    // every request a screen made: {url, method, body}
const holds = [];                                  // requests kept back until a test lets them go
const breaks = [];                                 // requests that fail as if the server did not answer
const stubs = [];                                  // requests answered by the test instead of the server: {match, answer: {status, json}}
ctx.setInterval = () => 0;
for (const name of ['createElement', 'createElementNS']) {              // swatches and maps read and write element.style
  const make = ctx.document[name];
  ctx.document[name] = (...args) => { const el = make(...args); el.style = {}; return el; };
}
ctx.fetch = async (url, opts = {}) => {
  const entry = {url: String(url), method: opts.method || 'GET', body: opts.body || null};
  log.push(entry);
  const held = holds.find((x) => !x.used && entry.url.includes(x.match) && (!x.method || x.method === entry.method));
  if (held) { held.used = true; held.seen = true; await held.gate; }
  const canned = stubs.find((x) => entry.url.includes(x.match) && (!x.method || x.method === entry.method));
  if (canned) return {ok: canned.answer.status < 300, status: canned.answer.status, headers: {get: () => 'application/json'},
    json: async () => canned.answer.json, text: async () => JSON.stringify(canned.answer.json), blob: async () => ({})};
  const broken = breaks.findIndex((m) => entry.url.includes(m));
  if (broken >= 0) { breaks.splice(broken, 1); throw new TypeError('fetch failed'); }
  const res = await fetch('http://127.0.0.1:' + PORT + entry.url, {method: entry.method, headers: opts.headers, body: opts.body});
  const raw = Buffer.from(await res.arrayBuffer());
  return {ok: res.ok, status: res.status, headers: {get: (k) => res.headers.get(k)}, json: async () => JSON.parse(raw.toString('utf8')),
    text: async () => raw.toString('utf8'), blob: async () => ({size: raw.length})};
};
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'forms.js', 'terms.js', 'dialogs.js', 'list.js', 'filepick.js', {code: %(glue)s}, %(files)s]);
const App = ctx.App, doc = ctx.document, {h} = App;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** Wait until ``fn()`` is true (the requests of the screen take a few milliseconds); fail the test when it never is. */
const until = async (fn, what = 'a condition', ms = 8000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { if (fn()) return; } catch (_) { /* not drawn yet */ } await sleep(8); }
  throw new Error('timed out waiting for ' + what + '; requests: ' + log.map((x) => x.method + ' ' + x.url).slice(-6).join(' | '));
};
/** Keep the next request whose address holds ``match`` until ``release()``. */
const hold = (match, method) => { let release; const x = {match, method, used: false, seen: false, gate: new Promise((r) => { release = r; })}; holds.push(x); x.release = release; return x; };
const breakNext = (match) => breaks.push(match);
const stub = (match, answer, method) => stubs.push({match, answer, method});
const shell = new El('div'); shell.setAttribute('id', 'app'); doc.body.append(shell);
const mount = (node) => { shell.append(node); return node; };
const q = (root, sel) => root.querySelector(sel);
const qa = (root, sel) => root.querySelectorAll(sel);
const lines = (root) => qa(root, '.lst-row');                   // every line, the pinned one too
const rows = (root) => qa(q(root, '.lst-rows'), '.lst-row');    // the lines of the list itself
const texts = (root) => qa(root, '.lst-main').map((n) => n.textContent);
const count = (root) => q(root, '.lst-count').textContent;
const button = (root, text) => qa(root, 'button').find((b) => b.textContent === text) || null;
const requests = (match) => log.filter((x) => x.url.includes(match));
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


@contextmanager
def serving(data_dir):
    """The real application on a free port; ``(app, port)``. The server runs in a thread of this process, so the test reads and writes the
    same store the screens reach through the API."""
    app = create_app(data_dir)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        assert thread.is_alive() and time.time() < deadline, "the server did not start"
        time.sleep(0.02)
    try:
        yield app, server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(10)


def fill_materials(store, count: int) -> None:
    """``count`` stock records: grades cycle over four (the fourth has none); every grade has many batches (sheets), each of its own thickness."""
    from titanium_platform import setup as su
    grades = ("Grade 2", "Grade 5", "Ti-6Al-4V", None)
    with store.transaction():
        for i in range(count):
            su.save_material(store, f"Sheet {i + 1}", batch=f"B-{i + 1:04d}", grade=grades[i % 4], thickness_mm=0.5 + (i % 5) * 0.5,
                             surface="brushed" if i % 2 else None, family="Titanium" if i % 7 else "Steel")


def run_node(tmp_path, port, files, body, exports=()) -> dict:
    """Run ``body`` in node with the UI scripts ``files`` loaded after the common ones; it fills ``out`` (JSON) and may use the helpers above.
    ``exports`` are the names of the scripts' top-level constants (``const SourceRefs``) the body reaches as ``ctx.SourceRefs``; a script's
    constants are not properties of the context by themselves. ``port`` 0: the screen makes no request (a list of items in hand)."""
    script = tmp_path / "screen.js"
    expose = json.dumps({"code": "".join(f"globalThis.{name} = {name};" for name in exports)})
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES),
                                 "port": port, "glue": json.dumps(GLUE), "files": ", ".join([*(json.dumps(f) for f in files), expose]), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.stderr or done.stdout)[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])
