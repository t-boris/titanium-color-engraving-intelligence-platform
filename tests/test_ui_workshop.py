"""The workshop screen (feature electron, REQ-080, REQ-081): the menu entry «Мастерская», the data folder and schema, the backup folder,
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
HELPERS = ["app.js", "dialogs.js"]
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
    assert nav[-1] == "/workshop" and "['/workshop', 'Мастерская']" in router and "workshop: 'workshop'" in router and len(icons) == len(nav)
    scripts = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
    order = {s: i for i, s in enumerate(scripts)}
    assert order["/i18n-workshop.js"] < order["/i18n-gaps.js"] < order["/dialogs.js"] < order["/screens/workshop.js"]
    screen = (UI_DIR / "screens" / "workshop.js").read_text(encoding="utf-8")
    assert "App.register({id: 'workshop'" in screen and "innerHTML" not in screen
    for route in ("'/workshop'", "'/workshop/backups'", "'/workshop/backups/inspect'", "'/workshop/restore'", "'/workshop/backup-dir'",
                  "'/workshop/recovery-copies'", "'/workshop/diagnostics'"):
        assert route in screen, route
    assert "confirm: word.value.trim()" in screen and "overwrite: true" in screen        # the word typed by the operator is what is sent


@node
def test_the_screen_shows_the_workshop_its_backups_and_the_recovery_copies_and_makes_a_backup(tmp_path):
    out = run(tmp_path, routes_of(), """
  const tree = await ctx.__screens.workshop.render({query: {}});
  await tick();
  out.facts = tree.querySelectorAll('dd').map((d) => d.textContent);
  out.rows = tree.querySelectorAll('tr').filter((tr) => tr.querySelectorAll('td').length).map((tr) => tr.querySelectorAll('td').map((td) => td.textContent));
  out.headings = tree.querySelectorAll('h3').map((x) => x.textContent);
  out.recovery = tree.textContent.includes('перед сменой схемы') && tree.textContent.includes('backups');
  await byText(tree, 'button', 'Сделать резервную копию').dispatch('click'); await tick();
  out.made = sent();
  out.result = tree.querySelectorAll('.alert.ok').map((p) => p.textContent);
  const dir = tree.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Папка резервных копий');
  dir.value = '/Volumes/Disk/titanium-backups';
  await byText(tree, 'button', 'Изменить').dispatch('click'); await tick();
  out.changed = sent().slice(-1);
""")
    assert out["facts"][:4] == ["/Users/me/.titanium-platform", "0.30.0", "схема 1", "titanium-platform (pid 4242)"] and out["facts"][4].startswith("120,0 ГБ из ")
    assert out["headings"] == ["Мастерская", "Резервные копии", "Копии перед сменой схемы", "Диагностика"]
    backup_row, copy_row = out["rows"]
    assert backup_row[:4] == ["2026-10-24 12:00", "52 МБ", "0.30.0 · схема 1", "312 файлов"] and backup_row[4] == BACKUP["path"]
    assert "Проверить" in backup_row[5] and "Восстановить…" in backup_row[5] and "Заменить открытую мастерскую…" in backup_row[5]
    assert copy_row == ["2026-10-24 10:00", "schema-before-2-20261024T100000Z.sqlite", "48 МБ", "перед сменой схемы"] and out["recovery"]
    assert out["made"][0] == ["POST", "/api/workshop/backups", {}]
    assert out["result"] == [f"Резервная копия записана: {BACKUP['path']} · файлов 2 · 52 МБ."]
    assert out["changed"] == [["PUT", "/api/workshop/backup-dir", {"path": "/Volumes/Disk/titanium-backups"}]]


@node
def test_restoring_goes_into_a_typed_folder_and_replacing_the_open_workshop_needs_the_typed_word(tmp_path):
    out = run(tmp_path, routes_of(), """
  const tree = await ctx.__screens.workshop.render({query: {}});
  await tick();
  await byText(tree, 'button', 'Проверить').dispatch('click'); await tick();
  out.inspected = [dialog().getAttribute('aria-label'), dialog().textContent.includes('Копия полная'), sent().slice(-1)[0]];
  byText(dialog(), 'button', 'Закрыть').dispatch('click'); await tick();
  await byText(tree, 'button', 'Восстановить…').dispatch('click'); await tick();
  const target = dialog().querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Папка для восстановления');
  target.value = '/Users/me/restored';
  await byText(dialog(), 'button', 'Восстановить').dispatch('click'); await tick();
  out.restored = sent().slice(-1)[0];
  out.closedAfterRestore = dialog() === null;
  await byText(tree, 'button', 'Заменить открытую мастерскую…').dispatch('click'); await tick();
  const replace = byText(dialog(), 'button', 'Заменить мастерскую');
  out.warning = dialog().querySelector('.alert.warn').textContent;
  out.disabledBefore = replace.disabled;
  const word = dialog().querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Слово подтверждения');
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
    assert out["inspected"] == ["Проверка резервной копии", True, ["POST", "/api/workshop/backups/inspect", {"path": BACKUP["path"], "verify": True}]]
    assert out["restored"] == ["POST", "/api/workshop/restore", {"path": BACKUP["path"], "target_dir": "/Users/me/restored"}] and out["closedAfterRestore"]
    assert "/Users/me/.titanium-platform будет заменена копией от 2026-10-24 12:00" in out["warning"]
    assert "отложена как /Users/me/.titanium-platform.replaced-<дата>" in out["warning"]
    assert out["disabledBefore"] is True and out["disabledWrong"] is True and out["sentWrong"] == 0 and out["disabledRight"] is False
    assert out["replaced"] == ["POST", "/api/workshop/restore", {"path": BACKUP["path"], "target_dir": "/Users/me/.titanium-platform", "overwrite": True, "confirm": "overwrite"}]
    assert "Перезапустите приложение" in out["after"]


@node
def test_the_diagnostics_button_says_what_is_and_is_not_included_and_posts_the_export(tmp_path):
    out = run(tmp_path, routes_of(), """
  const tree = await ctx.__screens.workshop.render({query: {}});
  await tick();
  const card = tree.querySelectorAll('.card').find((c) => c.querySelector('h3') && c.querySelector('h3').textContent === 'Диагностика');
  out.text = card.textContent;
  await byText(card, 'button', 'Экспорт диагностики').dispatch('click'); await tick();
  out.posted = sent().slice(-1)[0];
  out.result = card.querySelector('.alert.ok').textContent;
  out.link = card.querySelector('a') && card.querySelector('a').getAttribute('href');
""")
    assert "Не входят: фотографии, файлы работ, сама база и файлы выпусков." in out["text"] and "ключи и токены заменяются" in out["text"]
    assert out["posted"] == ["POST", "/api/workshop/diagnostics", {}]
    assert out["result"].startswith("Файл диагностики записан: /Volumes/Disk/titanium-backups/titanium-diagnostics-20261024T120500Z.zip (0,0 МБ; summary.json, logs/app.log, audit.jsonl).")
    assert out["link"] == "/api/workshop/diagnostics/titanium-diagnostics-20261024T120500Z.zip"
