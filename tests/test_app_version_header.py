"""The version of the application is shown in the header (REQ-057, DEC-099): one request to ``GET /api/version``, the value kept for the other screens, and
nothing shown, and no error, when the server does not answer. Run in node over the small DOM of the other screen tests."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI
from titanium_platform import __version__

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
CSS = (UI / "styles.css").read_text(encoding="utf-8")
ROUTER = (UI / "router.js").read_text(encoding="utf-8")

HARNESS = """
const fs = require('fs');
const {context, load, El} = require(%(dom)s);
const answers = %(answers)s;
const ctx = context(answers);
const root = new El('div'); root.setAttribute('id', 'app'); ctx.document.body.append(root);
ctx.document.getElementById = (id) => (id === 'app' ? root : null);
ctx.document.querySelectorAll = (s) => ctx.document.body.querySelectorAll(s);
load(ctx, %(ui)s, [...%(tables)s, 'app.js', {code: "App.register = App.register;"}, 'router.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const tags = () => root.querySelectorAll('span').filter((el) => (el.className || '').split(' ').includes('app-version'));
(async () => {
  const App = ctx.App;
  App.register({id: 'experiments', render: async () => ctx.document.createElement('div')});
  const out = {};
  await App.render(); for (let i = 0; i < 5; i++) await tick();
  out.first = tags().map((t) => [t.textContent, t.getAttribute('title')]);
  await App.render(); out.immediately = tags().map((t) => t.textContent);          // a second screen shows it at once, from memory
  for (let i = 0; i < 5; i++) await tick();
  out.asked = ctx.requests.filter((r) => r.path === '/api/version').length;
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, answers):
    script = tmp_path / "header.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "ui": json.dumps(str(UI) + "/"),
                                 "tables": json.dumps(TABLES), "answers": json.dumps(answers)}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@node
def test_the_header_shows_the_version_the_server_reports_and_asks_for_it_once(tmp_path):
    out = run(tmp_path, {"/api/version": {"status": 200, "json": {"version": "9.8.7", "data_dir": "/x"}}})
    assert out["first"] == [["v9.8.7", "Версия приложения"]] and out["immediately"] == ["v9.8.7"] and out["asked"] == 1


@node
def test_a_server_that_does_not_answer_leaves_the_header_without_a_version_and_without_an_error(tmp_path):
    out = run(tmp_path, {"/api/version": {"status": 500, "json": {"error": "boom"}}})
    assert out["first"] == [["", "Версия приложения"]]


def test_the_label_is_small_and_hidden_while_empty_and_the_header_keeps_its_height():
    assert re.search(r"\.app-version \{font-size:12px;", CSS) and ".app-version:empty {display:none}" in CSS
    assert "versionTag, h('span', {class: 'user-chip'" in ROUTER and "get('/version')" in ROUTER


def test_the_server_reports_the_version_the_package_has(tmp_path):
    from fastapi.testclient import TestClient
    from titanium_platform.api.app import create_app
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/version").json()["version"] == __version__
