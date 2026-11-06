"""The workshop screen (feature electron, REQ-080, REQ-081): the menu entry «Workshop», the data folder and schema, the backup folder,
backups made, listed, checked and restored into another folder; replacing the open workshop is a separate choice behind a typed word;
the recovery copies made before a schema change are listed with their reason; the diagnostics export says what it holds and what it never
does. Run in node over the small DOM of the other screen tests with a fake server."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import GLUE, TABLES, UI
from titanium_platform.api.app import UI_DIR

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
HELPERS = ["app.js", "dialogs.js", "list.js"]
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
const plain = ctx.fetch;
ctx.fetch = async (url, opts = {}) => {
  const path = String(url).split('?')[0], r = data.routes[path];
  if (r && (r.GET || r.POST || r.PUT)) { ctx.requests.push({path, url: String(url), method: opts.method || 'GET', body: opts.body}); const a = r[opts.method || 'GET'] || {status: 404, json: {error: 'none'}};
    return {ok: a.status < 300, status: a.status, headers: {get: () => 'application/json'}, json: async () => a.json}; }
  return plain(url, opts);
};
load(ctx, %(ui)s, [...%(tables)s, 'i18n-workshop.js', ...%(helpers)s, {code: %(glue)s}, 'screens/workshop.js']);
const tick = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const sent = () => ctx.requests.filter((r) => r.method !== 'GET').map((r) => [r.method, r.path, typeof r.body === 'string' ? JSON.parse(r.body) : r.body]);
const dialog = () => ctx.document.body.querySelector('.modal');
// a line of a short list: the texts of its parts and the buttons at its end
const line = (r) => [r.querySelector('.lst-main').children.map((c) => c.textContent), r.querySelectorAll('button').map((b) => b.textContent)];
const card = (tree, title) => tree.querySelectorAll('.card').find((c) => c.querySelector('h3') && c.querySelector('h3').textContent === title);
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""

WORKSHOP = {"data_dir": "/Users/me/.titanium-platform", "app": "0.30.0", "schema": 1, "schema_known": 1, "lock": {"pid": 4242, "program": "titanium-platform"},
            "disk": {"free_bytes": 120 * 2**30, "total_bytes": 1000 * 2**30}, "backup_dir": None, "default_backup_dir": "/Users/me/.titanium-platform/backups"}
BACKUP = {"path": "/Volumes/Disk/titanium-backups/titanium-backup-20261024T120000Z", "complete": True, "problems": [],
          "manifest": {"kind": "titanium-workshop-backup", "version": 1, "app": "0.30.0", "schema": 1, "created_at": "2026-10-24T12:00:00+00:00",
                       "data_dir": "/Users/me/.titanium-platform", "bytes": 52 * 2**20, "files": 312}}
COPIES = [{"name": "schema-before-2-20261024T100000Z.sqlite", "path": "/Users/me/.titanium-platform/backups/schema-before-2-20261024T100000Z.sqlite",
           "bytes": 48 * 2**20, "modified_at": "2026-10-24T10:00:00+00:00", "kind": "schema"}]


def ok(body, status=200):
    return {"status": status, "json": body}


def run(tmp_path, routes, body) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes}), encoding="utf-8")
    script = tmp_path / "workshop.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "helpers": json.dumps(HELPERS), "glue": json.dumps(GLUE), "body": body},
                      encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def routes_of():
    return {"/api/workshop": ok(WORKSHOP), "/api/workshop/backups": {"GET": ok([BACKUP]), "POST": ok({**BACKUP["manifest"], "path": BACKUP["path"], "files": {"a": 1, "b": 2}}, 201)},
            "/api/workshop/recovery-copies": ok(COPIES), "/api/workshop/backups/inspect": {"POST": ok({**BACKUP, "complete": True})},
            "/api/workshop/backup-dir": {"PUT": ok({"backup_dir": "/Volumes/Disk/titanium-backups"})},
            "/api/workshop/restore": {"POST": ok({"path": "/Users/me/restored", "from": "/Users/me/.titanium-platform", "rebased": 12, "set_aside": None, "restart_needed": False})},
            "/api/workshop/diagnostics": {"POST": ok({"path": "/Volumes/Disk/titanium-backups/titanium-diagnostics-20261024T120500Z.zip", "name": "titanium-diagnostics-20261024T120500Z.zip",
                                                      "members": ["summary.json", "logs/app.log", "audit.jsonl"], "bytes": 20480,
                                                      "download": "/api/workshop/diagnostics/titanium-diagnostics-20261024T120500Z.zip"}, 201)}}


def test_the_menu_ends_with_the_workshop_with_an_icon_of_its_own_and_the_screen_uses_the_workshop_api_only_through_nodes():
    router = (UI_DIR / "router.js").read_text(encoding="utf-8")
    nav = re.findall(r"\['(/[\w-]+)', '", router[router.index("const NAV"):router.index("const ROUTE_ID")])
    icons = re.findall(r"^\s+'<", router[router.index("const ICONS"):router.index("function icon")], re.M)
    assert nav[-1] == "/workshop" and "['/workshop', 'Workshop']" in router and "workshop: 'workshop'" in router and len(icons) == len(nav)
    scripts = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
    order = {s: i for i, s in enumerate(scripts)}
    assert order["/i18n-workshop.js"] < order["/i18n-gaps.js"] < order["/dialogs.js"] < order["/screens/workshop.js"]
    screen = (UI_DIR / "screens" / "workshop.js").read_text(encoding="utf-8")
    assert "App.register({id: 'workshop'" in screen and "innerHTML" not in screen
    for route in ("'/workshop'", "'/workshop/backups'", "'/workshop/backups/inspect'", "'/workshop/restore'", "'/workshop/backup-dir'",
                  "'/workshop/recovery-copies'", "'/workshop/diagnostics'"):
        assert route in screen, route
    assert "confirm: v.word" in screen and "overwrite: true" in screen        # the word typed by the operator is what is sent


@node
def test_the_screen_shows_the_workshop_its_backups_and_the_recovery_copies_and_makes_a_backup(tmp_path):
    out = run(tmp_path, routes_of(), """
  const tree = await ctx.__screens.workshop.render({query: {}});
  await tick();
  out.facts = tree.querySelectorAll('dd').map((d) => d.textContent);
  out.rows = tree.querySelectorAll('.lst-row').map(line);
  out.headings = tree.querySelectorAll('h3').map((x) => x.textContent);
  out.recovery = tree.textContent.includes('before schema change') && tree.textContent.includes('backups');
  await byText(tree, 'button', 'Create backup').dispatch('click'); await tick();
  out.made = sent();
  out.result = tree.querySelectorAll('.alert.ok').map((p) => p.textContent);
  const dir = tree.querySelectorAll('label').find((l) => l.textContent.startsWith('Backup folder')).firstControl();
  dir.value = '/Volumes/Disk/titanium-backups';
  await byText(tree, 'button', 'Change').dispatch('click'); await tick();
  out.changed = sent().slice(-1);
""")
    assert out["facts"][:4] == ["/Users/me/.titanium-platform", "0.30.0", "schema 1", "titanium-platform (pid 4242)"] and out["facts"][4].startswith("120.0 GB of ")
    assert out["headings"] == ["Workshop tasks", "Workshop", "Backups", "Copies before schema changes", "Diagnostics"]
    backup_row, copy_row = out["rows"]                                                                      # one line each
    assert backup_row == [["2026-10-24 12:00", "52 MB", "0.30.0 · schema 1", "312 files", BACKUP["path"]], ["Inspect", "Restore…", "Replace open workshop…"]]
    assert copy_row == [["2026-10-24 10:00", "schema-before-2-20261024T100000Z.sqlite", "48 MB", "before schema change"], []] and out["recovery"]
    assert out["made"][0] == ["POST", "/api/workshop/backups", {}]
    assert out["result"] == [f"Backup created: {BACKUP['path']} · files 2 · 52 MB."]
    assert out["changed"] == [["PUT", "/api/workshop/backup-dir", {"path": "/Volumes/Disk/titanium-backups"}]]


@node
def test_workshop_tasks_link_to_maintenance_and_keep_backup_keyboard_access(tmp_path):
    out = run(tmp_path, routes_of(), """
  const tree = await ctx.__screens.workshop.render({query: {}}); ctx.document.body.append(tree);
  const tasks = tree.querySelector('nav');
  out.links = tasks.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  await byText(tasks, 'button', 'Backups and restore').dispatch('click');
  out.focused = ctx.document.activeElement === tree.querySelector('.workshop-backups');
  out.details = tree.querySelectorAll('details').map((d) => [d.querySelector('summary').textContent, d.hasAttribute('open')]);
""")
    assert out["links"] == [["Connect a tablet or manage external services", "#/network"],
                            ["Connect or manage laboratories", "#/labs"], ["Materials and capture resources", "#/setup"]]
    assert out["focused"] is True
    assert ["Diagnostics", False] in out["details"] and ["Database recovery copies", False] in out["details"]


@node
def test_restoring_goes_into_a_typed_folder_and_replacing_the_open_workshop_needs_the_typed_word(tmp_path):
    out = run(tmp_path, routes_of(), """
  const tree = await ctx.__screens.workshop.render({query: {}});
  await tick();
  await byText(tree, 'button', 'Inspect').dispatch('click'); await tick();
  out.inspected = [dialog().getAttribute('aria-label'), dialog().textContent.includes('The backup is complete'), sent().slice(-1)[0]];
  byText(dialog(), 'button', 'Close').dispatch('click'); await tick();
  await byText(tree, 'button', 'Restore…').dispatch('click'); await tick();
  const target = dialog().querySelectorAll('label').find((l) => l.textContent.startsWith('Restore folder')).firstControl();
  target.value = '/Users/me/restored';
  await byText(dialog(), 'button', 'Restore').dispatch('click'); await tick();
  out.restored = sent().slice(-1)[0];
  out.closedAfterRestore = dialog() === null;
  await byText(tree, 'button', 'Replace open workshop…').dispatch('click'); await tick();
  const replace = byText(dialog(), 'button', 'Replace workshop');
  out.warning = dialog().querySelector('.alert.warn').textContent;
  out.disabledBefore = replace.disabled;
  const word = dialog().querySelectorAll('input')[0];
  word.value = 'yes'; await word.dispatch('input');
  out.disabledWrong = replace.disabled;
  const before = sent().length;
  await replace.dispatch('click'); await tick();
  out.sentWrong = sent().length - before;
  word.value = 'overwrite'; await word.dispatch('input');
  out.disabledRight = replace.disabled;
  await replace.dispatch('click'); await tick();
  out.replaced = sent().slice(-1)[0];
  out.after = dialog().textContent;
""")
    assert out["inspected"] == ["Inspect backup", True, ["POST", "/api/workshop/backups/inspect", {"path": BACKUP["path"], "verify": True}]]
    assert out["restored"] == ["POST", "/api/workshop/restore", {"path": BACKUP["path"], "target_dir": "/Users/me/restored"}] and out["closedAfterRestore"]
    assert "The open workshop /Users/me/.titanium-platform will be replaced by the backup from 2026-10-24 12:00" in out["warning"]
    assert "moved to /Users/me/.titanium-platform.replaced-<date>" in out["warning"]
    assert out["disabledBefore"] is True and out["disabledWrong"] is True and out["sentWrong"] == 0 and out["disabledRight"] is False
    assert out["replaced"] == ["POST", "/api/workshop/restore", {"path": BACKUP["path"], "target_dir": "/Users/me/.titanium-platform", "overwrite": True, "confirm": "overwrite"}]
    assert "Restart the application" in out["after"]


@node
def test_the_diagnostics_button_says_what_is_and_is_not_included_and_posts_the_export(tmp_path):
    out = run(tmp_path, routes_of(), """
  const tree = await ctx.__screens.workshop.render({query: {}});
  await tick();
  const card = tree.querySelectorAll('.card').find((c) => c.querySelector('h3') && c.querySelector('h3').textContent === 'Diagnostics');
  out.text = card.textContent;
  await byText(card, 'button', 'Export diagnostics').dispatch('click'); await tick();
  out.posted = sent().slice(-1)[0];
  out.result = card.querySelector('.alert.ok').textContent;
  out.link = card.querySelector('a') && card.querySelector('a').getAttribute('href');
""")
    assert "Photos, work files, the database and release files are excluded." in out["text"] and "key-like values and tokens are redacted" in out["text"]
    assert out["posted"] == ["POST", "/api/workshop/diagnostics", {}]
    assert out["result"].startswith("Diagnostics file saved: /Volumes/Disk/titanium-backups/titanium-diagnostics-20261024T120500Z.zip (0.0 MB; summary.json, logs/app.log, audit.jsonl).")
    assert out["link"] == "/api/workshop/diagnostics/titanium-diagnostics-20261024T120500Z.zip"


@node
def test_the_recovery_copies_and_the_backups_show_ten_lines_the_newest_first_and_the_rest_on_request(tmp_path):
    copies = [{**COPIES[0], "name": f"{'schema-before' if i % 3 else 'titanium-before'}-{i}.sqlite", "path": f"/Users/me/.titanium-platform/backups/copy-{i}.sqlite",
               "bytes": (i % 7 + 1) * 2**20, "modified_at": f"2026-09-{i:02d}T10:00:00+00:00", "kind": "schema" if i % 3 else "release"} for i in range(1, 26)]
    backups = [{**BACKUP, "path": f"/Volumes/Disk/titanium-backups/titanium-backup-{i:02d}", "complete": i != 5,
                "manifest": {**BACKUP["manifest"], "created_at": f"2026-10-{i:02d}T12:00:00+00:00"}} for i in range(1, 13)]
    routes = {**routes_of(), "/api/workshop/recovery-copies": ok(copies[::-1]), "/api/workshop/backups": {"GET": ok(backups[::-1])}}
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.workshop.render({query: {}});
  await tick();
  const copies = card(tree, 'Copies before schema changes'), backups = card(tree, 'Backups');
  const names = () => copies.querySelectorAll('.lst-row').map((r) => line(r)[0][1]);
  out.first = names(); out.count = copies.querySelector('.lst-count').textContent; out.more = copies.querySelector('.lst-foot').textContent;
  out.chips = copies.querySelectorAll('.lst-chip').map((c) => c.textContent);
  out.backups = [backups.querySelectorAll('.lst-row').length, backups.querySelector('.lst-count').textContent, backups.querySelector('.lst-foot').textContent,
    line(backups.querySelectorAll('.lst-row')[7])[0]];
  await copies.querySelector('.lst-foot').querySelector('button').dispatch('click'); await tick();
  out.second = names().length;
  await copies.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith('before version update')).dispatch('click'); await tick();
  out.release = names();
  const order = copies.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Порядок');
  order.value = 'size'; await order.dispatch('change'); await tick();
  out.largest = copies.querySelectorAll('.lst-row').map((r) => line(r)[0][2]).slice(0, 3);
  await copies.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  out.details = copies.querySelector('.lst-det').hidden ? null : copies.querySelectorAll('dd').map((d) => d.textContent)[0];
""")
    assert out["first"] == [f"{'schema-before' if i % 3 else 'titanium-before'}-{i}.sqlite" for i in range(25, 15, -1)]   # ten, the newest first
    assert out["count"] == "показано 10 из 25" and out["more"] == "Показать ещё 10" and out["second"] == 20
    assert out["chips"] == ["Все · 25", "before schema change · 17", "before version update · 8"]
    assert out["release"] == [f"titanium-before-{i}.sqlite" for i in (24, 21, 18, 15, 12, 9, 6, 3)]
    assert out["largest"] == ["7.0 MB", "6.0 MB", "5.0 MB"]
    assert out["details"] == "/Users/me/.titanium-platform/backups/copy-6.sqlite"                                        # the full path under the line
    lines, count, more, partial = out["backups"]
    assert (lines, count, more) == (10, "показано 10 из 12", "Показать ещё 2")
    assert partial == ["2026-10-05 12:00", "52 MB", "0.30.0 · schema 1", "312 files", "incomplete", "/Volumes/Disk/titanium-backups/titanium-backup-05"]
