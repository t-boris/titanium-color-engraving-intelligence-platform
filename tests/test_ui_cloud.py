"""The cloud on the laboratories screen (feature electron, REQ-086, REQ-087, DEC-058): the «Облако» block of «Моя лаборатория» (sign-in in a new
window and the wait for the account, publishing with the same preview as a file, a pending publication continued or given up, the own cloud
laboratory with invitations and members), the «Каталог лабораторий» tab (cards, «Подключить» into the same progress bar, «Принять приглашение»),
«Проверить обновления» for the laboratories connected from the cloud with the differences view, and the cloud card of one such laboratory.
Run in node over the small DOM of the other screen tests with a fake server; everything the cloud sends reaches the screen as text only."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import GLUE, TABLES, UI
from titanium_platform.api.app import UI_DIR

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
HELPERS = ["app.js", "photo-modes.js", "dialogs.js", "hardware.js", "filepick.js", "tasks.js"]
SCRIPTS = ["screens/lab-source.js", "screens/vector-split.js", "screens/vector-photo.js", "screens/lettering.js", "screens/vector-editor.js",
           "screens/vector-colours.js", "screens/vector-review.js", "screens/vector-workspace.js", "screens/vector.js", "screens/photo-panels.js",
           "screens/labs-cloud.js", "screens/labs.js"]
WINDOW = "globalThis.__opened = []; window.open = (url) => { __opened.push(url); return {}; };"
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
const plain = ctx.fetch;
ctx.fetch = async (url, opts = {}) => {            // a route is {GET: ..., POST: ..., PUT: ..., DELETE: ...}; data.routes may be changed by the body
  const path = String(url).split('?')[0], r = data.routes[path], method = opts.method || 'GET';
  if (r && !('status' in r)) { ctx.requests.push({path, url: String(url), method, body: opts.body}); const a = r[method] || {status: 404, json: {error: 'none'}};
    return {ok: a.status < 300, status: a.status, headers: {get: () => 'application/json'}, json: async () => a.json}; }
  return plain(url, opts);
};
load(ctx, %(ui)s, [...%(tables)s, 'i18n-labs.js', 'i18n-cloud.js', ...%(helpers)s, {code: %(glue)s}, ...%(scripts)s]);
const tick = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const byRole = (root, role) => root.querySelectorAll('[role]').filter((el) => el.getAttribute('role') === role);
const sent = () => ctx.requests.filter((r) => r.method !== 'GET' && !r.path.endsWith('/updates/automatic'))
  .map((r) => [r.method, r.path, typeof r.body === 'string' ? JSON.parse(r.body) : r.body]);
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""
TERMS = [{"id": "CC-BY-4.0", "name": {"ru": "CC BY 4.0"}, "summary": {"ru": "с указанием авторства"}}]
OWN_LAB = {"public": {"name": "Open lab", "author": "A. Author", "lasers": {}}, "choices": {}, "exports": [], "withdrawals": [], "terms": TERMS}
PREVIEW = {"ready": True, "photographs": 12, "engravings": 3, "measurements": 40, "tone_profiles": 1, "setups": 1, "materials": 1,
           "public": {"name": "Open lab", "author": "A. Author", "lasers": {"1": {"public_name": "Fibre 60 W"}}}, "tokenised": {}, "never": ["photographs", "notes"]}
SIGNED_OUT = {"signed_in": False, "account": None, "signed_in_at": None, "api_url": "https://cloud.test", "switched_on": True, "lab": None, "releases": [],
              "invitations": [], "members": [], "publications": [], "pending": None}
ACCOUNT = {"id": "acc-1", "name": "Мастерская <b>Север</b>", "email": "north@example.org"}
SIGNED_IN = {**SIGNED_OUT, "signed_in": True, "account": ACCOUNT, "signed_in_at": "2026-10-24T10:00:00+00:00"}
RELEASE = {"id": "r-9", "lab_id": "lab-1", "number": 2, "content_sha256": "abcdef0123456789ffff", "byte_size": 2 * 1024 * 1024, "counts": {"measurements": 40, "equipment": 2},
           "terms": "CC-BY-4.0", "usage_terms": {"id": "CC-BY-4.0", "name": {"ru": "CC BY 4.0"}}, "created_at": "2026-10-23T09:00:00Z", "published_at": "2026-10-23T09:05:00Z"}
LAB = {"id": "lab-1", "name": "Лаборатория <b>Север</b>", "author": "Автор <i>Н</i>", "description": "<script>alert(1)</script>", "url": "https://north.example",
       "visibility": "public", "origin_lab_id": "o-1", "role": "member", "latest_release": RELEASE, "own": False, "connected": None}
DONE_JOB = {"id": "j-1", "kind": "connect", "cloud": {"lab_name": "Лаборатория <b>Север</b>"}, "phase": "done", "read": 2 * 1024 * 1024, "total": 2 * 1024 * 1024,
            "share": 1.0, "elapsed_s": 1.0, "error": None, "done": True,
            "result": {"unchanged": False, "release_id": "r-9", "source_id": 4, "current": {"release_id": "r-9", "content_sha256": "abcdef0123456789ffff", "release_number": 2}}}
DIFFERENCES = {"against": "0123456789abcdefffff", "added": {"measurements": 5}, "changed": {}, "removed": {"measurements": 1}, "withdrawn": 0}
SOURCE = {"id": 4, "origin_lab_id": "o-1", "name": "Лаборатория <b>Север</b>", "origin": "cloud", "url": "https://cloud.test/labs/lab-1", "status": "connected",
          "connected_at": "2026-10-20T10:00:00", "disconnected_at": None, "update_checks": "manual", "last_checked_at": None, "last_check": None, "kept": 1, "withdrawals": 0,
          "release_withdrawn": False, "current": {"release_id": "r-1", "release_number": 1, "created_at": "2026-10-20T09:00:00Z", "content_sha256": "0123456789abcdefffff",
                                                  "verified": True, "status": "kept", "terms": {"id": "CC-BY-4.0"}, "attribution": {"name": "Автор"}, "counts": {"measurements": 35}}}
CHECKED = {"source_id": 4, "name": "Лаборатория <b>Север</b>", "checked_at": "2026-10-24T12:00:00", "found": True, "lab_id": "lab-1", "current_release_id": "r-1",
           "current_release_number": 1, "latest": {"id": "r-9", "number": 2, "created_at": "2026-10-23T09:00:00Z", "counts": {"measurements": 40}, "byte_size": 2048}, "newer": True,
           "withdrawn_here": False}


def ok(body, status=200):
    return {"status": status, "json": body}


def run(tmp_path, routes, body) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes}), encoding="utf-8")
    script = tmp_path / "cloud.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "helpers": json.dumps(HELPERS), "scripts": json.dumps(SCRIPTS),
                                 "glue": json.dumps(GLUE + WINDOW), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def base_routes(**more) -> dict:
    return {"/api/labs/own": {"GET": ok(OWN_LAB)}, "/api/labs/sources": {"GET": ok([])}, "/api/cloud/own": {"GET": ok(SIGNED_OUT)},
            "/api/cloud/catalogue": {"GET": ok({"api_url": "https://cloud.test", "signed_in": False, "labs": []})}, "/api/cloud/updates/automatic": {"POST": ok([])}, **more}


def test_the_cloud_files_are_loaded_in_order_show_cloud_text_as_text_and_name_every_cloud_route():
    scripts = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
    order = {s: i for i, s in enumerate(scripts)}
    assert order["/i18n-lan.js"] < order["/i18n-cloud.js"] < order["/i18n-gaps.js"] < order["/app.js"]
    assert order["/screens/lab-source.js"] < order["/screens/labs-cloud.js"] < order["/screens/labs.js"]
    cloud = (UI_DIR / "screens" / "labs-cloud.js").read_text(encoding="utf-8")
    assert "innerHTML" not in cloud and "window.open(" in cloud and "'noopener'" in cloud
    for route in ("'/cloud/own'", "'/cloud/signin'", "'/cloud/signin/cancel'", "'/cloud/account'", "'/cloud/signout'", "'/cloud/publish'", "'/cloud/publish/retry'",
                  "'/cloud/publish/abandon'", "'/cloud/invitations'", "'/cloud/invitations/accept'", "/cloud/members/", "'/cloud/catalogue'", "/cloud/releases/",
                  "/connect`", "'/cloud/jobs'", "'/cloud/updates/check'", "'/cloud/updates/automatic'", "/cloud/sources/", "'/labs/own/preview'"):
        assert route in cloud, route
    network = (UI_DIR / "screens" / "network.js").read_text(encoding="utf-8")
    assert "'/cloud/settings'" in network and "['cloud', " in network


@node
def test_sign_in_opens_the_clouds_page_in_a_new_window_and_the_block_fills_in_when_the_account_arrives(tmp_path):
    url = "https://cloud.test/signin?state=st-1&challenge=ch&callback=cb"
    routes = base_routes(**{"/api/cloud/signin": {"POST": ok({"url": url, "state": "st-1", "providers": ["google"], "expires_in_s": 600}, 201)},
                           "/api/cloud/account": {"GET": ok({**SIGNED_OUT, "lab": None})}, "/api/cloud/signin/cancel": {"POST": ok(SIGNED_OUT)}})
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.labs.render({query: {}});
  ctx.document.body.append(tree);
  await tick();
  const own = tree.querySelector('.cloud-own');
  out.before = own.textContent;
  out.tabs = byRole(tree, 'tab').map((b) => b.textContent);
  await byText(own, 'button', 'Войти').dispatch('click'); await tick();
  out.opened = ctx.__opened.slice();
  out.waiting = own.querySelector('.cloud-signin-note').textContent;
  data.routes['/api/cloud/account'] = {GET: {status: 200, json: data.signedInAccount}};
  data.routes['/api/cloud/own'] = {GET: {status: 200, json: {...data.routes['/api/cloud/own'].GET.json, ...data.signedInAccount}}};
  await wait(1200);
  out.after = tree.querySelector('.cloud-own').textContent;
  out.sent = sent();
""".replace("data.signedInAccount", json.dumps({"signed_in": True, "account": ACCOUNT, "signed_in_at": "2026-10-24T10:00:00+00:00", "api_url": "https://cloud.test", "switched_on": True})))
    assert out["tabs"] == ["Моя лаборатория", "Подключённые лаборатории", "Каталог лабораторий"]
    assert "Вы не вошли в облако" in out["before"] and "Опубликовать в облаке" not in out["before"]
    assert out["opened"] == [url] and "Войдите в открывшемся окне браузера" in out["waiting"]
    assert out["sent"] == [["POST", "/api/cloud/signin", {}]]
    assert "Вы вошли как Мастерская <b>Север</b> · north@example.org" in out["after"] and "Опубликовать в облаке" in out["after"]   # the account arrived: the block is drawn again


@node
def test_a_signed_in_owner_publishes_after_the_same_preview_and_follows_the_job_to_its_end(tmp_path):
    running = {"id": "p-1", "kind": "publish", "cloud": {}, "phase": "uploading", "read": 512 * 1024, "total": 1024 * 1024, "share": 0.5, "elapsed_s": 1, "error": None, "result": None, "done": False}
    finished = {**running, "phase": "done", "read": 1024 * 1024, "done": True, "result": {"release": {**RELEASE, "number": 1}, "publication": {"state": "finalized"}}}
    routes = base_routes(**{"/api/cloud/own": {"GET": ok(SIGNED_IN)}, "/api/labs/own/preview": {"POST": ok(PREVIEW)}, "/api/cloud/publish": {"POST": ok(running, 202)},
                           "/api/cloud/jobs/p-1": {"GET": ok(finished)}, "/api/cloud/signout": {"POST": ok(SIGNED_OUT)}})
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.labs.render({query: {}});
  ctx.document.body.append(tree);
  await tick();
  const own = tree.querySelector('.cloud-own');
  out.account = [own.querySelector('.cloud-account').textContent, own.querySelector('.cloud-account').children.length];
  const publish = byText(own, 'button', 'Опубликовать в облаке');
  out.disabledBefore = publish.disabled;
  out.selects = own.querySelectorAll('select').map((s) => [s.getAttribute('aria-label'), s.value]);
  await byText(own, 'button', 'Подготовка публикации').dispatch('click'); await tick();
  out.preview = own.textContent;
  out.disabledAfter = publish.disabled;
  own.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Видимость').value = 'private';
  publish.dispatch('click'); await tick();                                        // not awaited: the job is still running
  out.progress = byRole(own, 'progressbar')[0].getAttribute('aria-valuenow');
  out.running = own.querySelector('.cloud-publish').textContent;
  await wait(400);
  out.finished = own.querySelector('.cloud-publish').textContent;
  out.sent = sent();
  out.renders = ctx.__renders.length;
  await byText(own, 'button', 'Выйти').dispatch('click'); await tick();
  const dialog = ctx.document.body.querySelector('.modal');
  out.dialog = dialog.textContent;
  await byText(dialog, 'button', 'Выйти').dispatch('click'); await tick();
  out.signedOut = sent().pop();
""")
    assert out["account"] == ["Мастерская <b>Север</b> · north@example.org", 0]                                           # the account's name is text
    assert out["disabledBefore"] is True and out["selects"] == [["Условия использования в облаке", "CC-BY-4.0"], ["Видимость", "public"]]
    assert "Фотографий12" in out["preview"].replace("\n", "") and "Выпуск можно записать." in out["preview"] and out["disabledAfter"] is False
    assert out["progress"] == "50" and "передача в облако · 0,5 МБ из 1,0 МБ (50 %)" in out["running"]
    assert "Опубликовано: выпуск № 1 · измерений: 40 · установок: 2." in out["finished"]
    assert out["sent"] == [["POST", "/api/labs/own/preview", {"selection": None}], ["POST", "/api/cloud/publish", {"terms": "CC-BY-4.0", "visibility": "private"}]]
    assert "Опубликованное останется в облаке" in out["dialog"] and out["signedOut"] == ["POST", "/api/cloud/signout", {}]


@node
def test_a_pending_publication_is_continued_or_given_up_and_the_own_laboratory_lists_invitations_and_members(tmp_path):
    pending = {"id": 3, "state": "uploading", "created_at": "2026-10-24T09:00:00", "error": "the cloud could not be reached: timed out", "release_number": 2}
    own = {**SIGNED_IN, "pending": pending, "publications": [pending], "lab": {"id": "lab-1", "name": "Open <b>lab</b>", "visibility": "private", "role": "owner", "origin_lab_id": "o-1"},
           "releases": [RELEASE], "members": [{"lab_id": "lab-1", "account_id": "acc-<b>2</b>", "via_invitation": "i-1", "created_at": "2026-10-22T10:00:00"}],
           "invitations": [{"id": "i-1", "lab_id": "lab-1", "created_at": "2026-10-21T10:00:00", "expires_at": "2026-10-28T10:00:00", "accepted_by": "acc-<b>2</b>", "accepted_at": "2026-10-22T10:00:00", "revoked_at": None},
                           {"id": "i-2", "lab_id": "lab-1", "created_at": "2026-10-23T10:00:00", "expires_at": "2026-10-30T10:00:00", "accepted_by": None, "accepted_at": None, "revoked_at": None}]}
    routes = base_routes(**{"/api/cloud/own": {"GET": ok(own)}, "/api/cloud/publish/abandon": {"POST": ok({**pending, "state": "failed"})},
                           "/api/cloud/invitations": {"POST": ok({"id": "i-3", "link": "https://cloud.test/invitations/tok-<b>3</b>", "expires_at": "2026-10-31T10:00:00"}, 201)},
                           "/api/cloud/invitations/i-2": {"DELETE": ok(None, 204)}, "/api/cloud/members/acc-%3Cb%3E2%3C%2Fb%3E": {"DELETE": ok(None, 204)}})
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.labs.render({query: {}});
  ctx.document.body.append(tree);
  await tick();
  const own = tree.querySelector('.cloud-own');
  out.pending = own.querySelector('.cloud-pending').textContent;
  out.buttons = own.querySelectorAll('button').map((b) => b.textContent);
  out.names = own.querySelectorAll('.lab-name').map((n) => [n.textContent, n.children.length]);
  out.accounts = own.querySelectorAll('.cloud-account').map((n) => [n.textContent, n.children.length]);
  await byText(own, 'button', 'Создать приглашение').dispatch('click'); await tick();
  out.link = [own.querySelector('.cloud-link').textContent, own.querySelector('.cloud-link').children.length];
  await byText(own, 'button', 'Исключить').dispatch('click'); await tick();
  await byText(ctx.document.body.querySelector('.modal'), 'button', 'Исключить').dispatch('click'); await tick();
  await byText(own, 'button', 'Отозвать').dispatch('click'); await tick();
  await byText(ctx.document.body.querySelector('.modal'), 'button', 'Отозвать').dispatch('click'); await tick();
  await byText(own, 'button', 'Отказаться').dispatch('click'); await tick();
  const dialog = ctx.document.body.querySelector('.modal');
  out.dialog = dialog.textContent;
  await byText(dialog, 'button', 'Отказаться').dispatch('click'); await tick();
  out.sent = sent();
""")
    assert "не завершена (передача: Облако недоступно: timed out" in out["pending"] and "один выпуск, не два" in out["pending"]
    assert "Продолжить публикацию" in out["buttons"] and "Отказаться" in out["buttons"] and "Опубликовать в облаке" not in out["buttons"]   # pending first
    assert out["names"] == [["Open <b>lab</b>", 0]] and out["accounts"] == [["Мастерская <b>Север</b> · north@example.org", 0], ["acc-<b>2</b>", 0], ["acc-<b>2</b>", 0]]
    assert out["link"] == ["https://cloud.test/invitations/tok-<b>3</b>", 0]
    assert "в облаке ничего не появится" in out["dialog"]
    assert out["sent"] == [["POST", "/api/cloud/invitations", {}], ["DELETE", "/api/cloud/members/acc-%3Cb%3E2%3C%2Fb%3E", None], ["DELETE", "/api/cloud/invitations/i-2", None],
                           ["POST", "/api/cloud/publish/abandon", {}]]


@node
def test_the_catalogue_shows_cards_connects_from_the_cloud_into_the_progress_bar_and_accepts_an_invitation(tmp_path):
    connected = {**LAB, "id": "lab-2", "name": "Connected lab", "origin_lab_id": "o-2", "latest_release": {**RELEASE, "id": "r-9", "lab_id": "lab-2"},
                 "connected": {"source_id": 4, "status": "connected", "origin": "cloud", "current_release_id": "r-1", "current_release_number": 1, "newer": True}}
    own = {**LAB, "id": "lab-3", "name": "Own lab", "origin_lab_id": "o-3", "own": True, "role": "owner", "latest_release": None}
    catalogue = {"api_url": "https://cloud.test", "signed_in": True, "labs": [LAB, connected, own]}
    routes = base_routes(**{"/api/cloud/catalogue": {"GET": ok(catalogue)}, "/api/cloud/own": {"GET": ok(SIGNED_IN)},
                           "/api/cloud/releases/r-9/connect": {"POST": ok(DONE_JOB, 202)}, "/api/labs/releases/r-9/differences": {"GET": ok(DIFFERENCES)},
                           "/api/cloud/invitations/accept": {"POST": ok({"lab": {**LAB, "role": "member"}, "member_since": "2026-10-24T10:00:00"})}})
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.labs.render({query: {tab: 'catalogue'}});
  ctx.document.body.append(tree);
  await tick();
  const panel = byRole(tree, 'tabpanel')[2];
  out.hidden = byRole(tree, 'tabpanel').map((p) => p.hidden);
  const cards = panel.querySelectorAll('.cloud-lab');
  out.cards = cards.map((c) => [c.querySelector('.lab-name').textContent, c.querySelector('.lab-name').children.length, c.querySelectorAll('.pill').map((p) => p.textContent),
    c.querySelectorAll('button').map((b) => b.textContent)]);
  out.first = cards[0].textContent;
  await byText(cards[1], 'button', 'Подключить выпуск № 2').dispatch('click'); await tick(); await tick();
  out.finished = cards[1].textContent;
  const dialog = ctx.document.body.querySelector('.modal');
  out.dialog = dialog ? dialog.textContent : null;
  const accept = panel.querySelector('.cloud-accept');
  accept.querySelector('input').value = 'https://cloud.test/invitations/tok-7';
  await byText(accept, 'button', 'Принять приглашение').dispatch('click'); await tick();
  out.sent = sent();
""")
    assert out["hidden"] == [True, True, False]
    assert out["cards"][0] == ["Лаборатория <b>Север</b>", 0, ["открытая"], ["Подключить"]]
    assert out["cards"][1][2] == ["открытая", "подключена", "есть новый выпуск"] and out["cards"][1][3] == ["Подключить выпуск № 2", "Открыть"]
    assert out["cards"][2] == ["Own lab", 0, ["открытая", "ваша лаборатория"], []]
    assert "Автор <i>Н</i>" in out["first"] and "<script>alert(1)</script>" in out["first"] and "№ 2 от 2026-10-23 · abcdef012345" in out["first"]
    assert "измерений: 40 · установок: 2" in out["first"] and "CC BY 4.0" in out["first"] and "2,0 МБ" in out["first"]
    assert "Лаборатория подключена" in out["finished"]
    assert out["dialog"] and "Различия выпуска abcdef012345" in out["dialog"] and "Против выпуска 0123456789ab" in out["dialog"]       # the existing differences view
    assert out["sent"] == [["POST", "/api/cloud/releases/r-9/connect", {}], ["POST", "/api/cloud/invitations/accept", {"link": "https://cloud.test/invitations/tok-7"}]]


@node
def test_connected_cloud_laboratories_are_checked_for_updates_by_the_button_and_one_laboratory_chooses_automatic_checks(tmp_path):
    card = {**SOURCE, "lab": {"name": "Лаборатория <b>Север</b>", "description": "d", "url": None}, "releases": [], "withdrawal_list": []}
    routes = base_routes(**{"/api/labs/sources": {"GET": ok([SOURCE, {**SOURCE, "id": 5, "name": "From file", "origin": "file", "url": None}])},
                           "/api/cloud/updates/check": {"POST": ok([CHECKED])}, "/api/cloud/updates/automatic": {"POST": ok([{**CHECKED, "source_id": 4}])},
                           "/api/cloud/releases/r-9/connect": {"POST": ok(DONE_JOB, 202)}, "/api/labs/releases/r-9/differences": {"GET": ok(DIFFERENCES)},
                           "/api/labs/sources/4": {"GET": ok(card)}, "/api/labs/choices": {"GET": ok([])}, "/api/labs/transfers": {"GET": ok([])},
                           "/api/cloud/sources/4": {"PUT": ok({**SOURCE, "update_checks": "auto"})}})
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.labs.render({query: {tab: 'sources'}});
  ctx.document.body.append(tree);
  await tick();
  const panel = byRole(tree, 'tabpanel')[1];
  out.auto = panel.querySelector('.cloud-auto').textContent;
  const updates = panel.querySelector('.cloud-updates-card');
  out.card = updates.textContent;
  await byText(updates, 'button', 'Проверить обновления').dispatch('click'); await tick();
  out.checked = updates.querySelector('.cloud-updates').textContent;
  await byText(updates.querySelector('.cloud-updates'), 'button', 'Подключить').dispatch('click'); await tick(); await tick();
  out.dialog = ctx.document.body.querySelector('.modal').textContent;
  const one = await ctx.__screens.labs.render({query: {source: '4'}});
  await tick();
  const cloud = one.querySelector('.cloud-source');
  out.one = cloud.textContent;
  const mode = cloud.querySelector('select');
  out.mode = mode.value;
  mode.value = 'auto'; await mode.dispatch('change'); await tick();
  out.sent = sent();
  out.automatic = ctx.requests.filter((r) => r.path.endsWith('/updates/automatic')).length;
""")
    assert "В облаке вышел новый выпуск лаборатории «Лаборатория <b>Север</b>»: № 2 от 2026-10-23." in out["auto"]
    assert "Лабораторий, подключённых из облака: 1" in out["card"]
    assert "Лаборатория <b>Север</b> — новый выпуск № 2 от 2026-10-23 · измерений: 40" in out["checked"]
    assert "Различия выпуска abcdef012345" in out["dialog"]
    assert "Лаборатория подключена из облака: https://cloud.test/labs/lab-1" in out["one"] and "Обновления ещё не проверялись" in out["one"] and out["mode"] == "manual"
    assert out["sent"] == [["POST", "/api/cloud/updates/check", {}], ["POST", "/api/cloud/releases/r-9/connect", {}], ["PUT", "/api/cloud/sources/4", {"update_checks": "auto"}]]
    assert out["automatic"] == 2                                                                                        # asked when the list is drawn, and again after the connection


@node
def test_with_the_cloud_switched_off_or_unreachable_the_rest_of_the_screen_still_works(tmp_path):
    routes = base_routes(**{"/api/cloud/own": {"GET": ok({**SIGNED_OUT, "switched_on": False})},
                           "/api/cloud/catalogue": {"GET": ok({"error": "the cloud of laboratories is switched off in the network settings of this workshop", "kind": "invalid"}, 422)}})
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.labs.render({query: {}});
  await tick();
  out.own = tree.querySelector('.cloud-own').textContent;
  out.catalogue = byRole(tree, 'tabpanel')[2].textContent;
  out.publicForm = tree.querySelectorAll('h3').map((x) => x.textContent);
""")
    assert "Облако выключено в настройках сети" in out["own"] and "Войти" not in out["own"]
    assert "Облако лабораторий выключено в настройках сети этой мастерской" in out["catalogue"]
    assert "Публичные сведения" in out["publicForm"] and "Публикация" in out["publicForm"] and "Отзыв опубликованного" in out["publicForm"]
