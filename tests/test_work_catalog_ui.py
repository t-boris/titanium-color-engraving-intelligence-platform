"""The screen of the shared catalog of works (feature ux-work-catalog-p0, REQ-001, REQ-002; I-2, I-4, I-6, I-8): the real application served on a free
port of this computer and ``screens/works.js`` run in node over the small DOM of the other screen tests, its requests going to that server, so
the first page, the search and filters, the gallery, the way back to a work, the row menu and its three operations are read through the real API.
Only what a real browser, Electron or a screen reader adds (layout, a real cursor, speech, the look of the cards) is not covered here."""
import json
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

from test_experiments import work_pair
from test_grey_scales import app_world                                          # noqa: F401  (a laser, lens and titanium with measured grey scales)
from test_photo_works import create as create_photo_work
from test_vector_photo_zones import colouring, create as create_vector_work, of_colour, world   # noqa: F401
from test_vector_work import RED, TABLES, UI
from test_inscriptions_vector import add as add_inscription
from test_work_catalog import add_photo, add_vector, equip
from titanium_platform.api.app import create_app

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

GLUE = ("const __screens = {}, __went = []; App.register = (d) => { __screens[d.id] = d; }; App.go = (route) => { __went.push(route); };"
        "globalThis.__screens = __screens; globalThis.__went = __went;"
        # the creation screen is another feature's file: the catalog only calls its one entry, which is recorded here
        "globalThis.__started = []; globalThis.Creation = {start: (options) => { __started.push(options); }};")

HARNESS = """
const {context, load, El} = require(__DOM__);
const ctx = context({});
const PORT = __PORT__;
const log = [];                                    // every request a screen made: {url, method, body}
const breaks = [];                                 // requests that fail as if the server did not answer
ctx.setInterval = () => 0;
ctx.fetch = async (url, opts = {}) => {
  const entry = {url: String(url), method: opts.method || 'GET', body: opts.body || null};
  log.push(entry);
  const broken = breaks.findIndex((m) => entry.url.includes(m));
  if (broken >= 0) { breaks.splice(broken, 1); throw new TypeError('fetch failed'); }
  const res = await fetch('http://127.0.0.1:' + PORT + entry.url, {method: entry.method, headers: opts.headers, body: opts.body});
  const raw = Buffer.from(await res.arrayBuffer());
  return {ok: res.ok, status: res.status, headers: {get: (k) => res.headers.get(k)}, json: async () => JSON.parse(raw.toString('utf8')),
    text: async () => raw.toString('utf8'), blob: async () => ({size: raw.length})};
};
const kept = {};
ctx.localStorage = {getItem: (k) => (k in kept ? kept[k] : null), setItem: (k, v) => { kept[k] = String(v); }};
const scrolled = [];
El.prototype.scrollIntoView = function (o) { scrolled.push(this); };
load(ctx, __UI__, [...__TABLES__, 'app.js', 'dialogs.js', 'list.js', {code: __GLUE__}, 'screens/works.js', {code: 'globalThis.Works = Works;'}]);
const App = ctx.App, doc = ctx.document, Works = ctx.Works, {h} = App;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
/** Wait until ``fn()`` is true (the requests of the screen take a few milliseconds); fail the test when it never is. */
const until = async (fn, what = 'a condition', ms = 8000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { if (fn()) return; } catch (_) { /* not drawn yet */ } await sleep(8); }
  throw new Error('timed out waiting for ' + what + '; requests: ' + log.map((x) => x.method + ' ' + x.url).slice(-6).join(' | '));
};
const main = doc.createElement('div'); main.setAttribute('id', 'main'); main.setAttribute('tabindex', '-1'); doc.body.append(main);
const asQuery = () => Object.fromEntries(new URLSearchParams(ctx.location.hash.includes('?') ? ctx.location.hash.split('?')[1] : ''));
/** The screen for an address (the part after «#/works?»), mounted where the router puts it. */
const open = async (query = {}) => {
  ctx.location.hash = '#/works' + (Object.keys(query).length ? '?' + new URLSearchParams(query).toString() : '');
  const s = Works.build(query);
  main.replaceChildren(s.el);
  await s.ready();
  return s;
};
const rowsOf = (s) => s.el.querySelectorAll('.lst-row');
const nameOf = (row) => row.querySelector('.works-name').textContent;
const names = (s) => rowsOf(s).map(nameOf);
const rowNamed = (s, name) => rowsOf(s).find((r) => nameOf(r) === name);
const count = (s) => s.el.querySelector('.lst-count').textContent;
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const chips = (s) => s.el.querySelectorAll('.lst-chip').map((c) => c.textContent);
const gets = (match = '/api/works?') => log.filter((x) => x.method === 'GET' && x.url.includes(match));
const posts = () => log.filter((x) => x.method === 'POST').map((x) => x.url + ' ' + x.body);
const deletes = () => log.filter((x) => x.method === 'DELETE').map((x) => x.url);
const info = (row) => {
  const pick = (cls) => { const e = row.querySelector('.' + cls); return e ? e.textContent : null; };
  const link = row.querySelector('.works-name'), img = row.querySelector('img');
  return {key: row.getAttribute('data-key'), name: link.textContent, href: link.getAttribute('href'), pills: row.querySelectorAll('.pill').map((p) => p.textContent),
    img: img ? img.getAttribute('src') : null, size: pick('works-size'), date: pick('works-date'), parts: pick('works-parts'), equipment: pick('works-equipment')};
};
const menuButton = (row) => row.querySelector('.works-menu-btn');
const item = (row, text) => row.querySelectorAll('.works-menu-item').find((b) => b.textContent === text);
/** Open the menu of a row and press one of its items. */
const choose = async (row, text) => { await menuButton(row).dispatch('click'); await item(row, text).dispatch('click'); };
const dialog = () => doc.body.querySelector('.modal');
const toasts = () => { const box = doc.body.querySelector('.toasts'); return box ? box.textContent : ''; };
const active = () => doc.activeElement;
(async () => {
  const out = {};
__BODY__
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


@contextmanager
def serving(data_dir=None, app=None):
    """The real application on a free port; ``(app, port)``. The server runs in a thread of this process, so the test writes the same store the
    screen reaches through the API. An ``app`` already running (its lifespan entered by a test client) is served as it is."""
    app = app or create_app(data_dir)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off" if data_dir is None else "on"))
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


@pytest.fixture
def served(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        yield {**equip(app), "app": app, "port": port, "tmp": tmp_path}


@pytest.fixture(scope="module")
def real(world, tmp_path_factory):
    """The grey-scale workshop of the other work tests, served on a free port: its works are real (a picture, a document, a thumbnail), so the
    owners' copy and delete can be run on them. Module-scoped: a test finds its works by a name of its own."""
    with serving(app=world["client"].app) as (app, port):
        yield {**world, "app": app, "port": port, "tmp": tmp_path_factory.mktemp("works_ui")}


def screen(world, body) -> dict:
    """Run ``body`` in node against the served workshop; it fills ``out`` (JSON)."""
    script = world["tmp"] / "works_screen.js"
    code = HARNESS
    for token, value in (("__DOM__", json.dumps(str(Path(__file__).with_name("ui_dom.js")))), ("__UI__", json.dumps(str(UI) + "/")), ("__TABLES__", json.dumps(TABLES)),
                         ("__GLUE__", json.dumps(GLUE)), ("__PORT__", str(world["port"])), ("__BODY__", body)):
        code = code.replace(token, value)
    script.write_text(code, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, (done.stderr or done.stdout)[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def stamp(n: int) -> str:
    """A modification time that makes the n-th work newer than the (n-1)-th: the order of the catalog is then the order of the test."""
    return f"2026-{1 + n // 600:02d}-{1 + n // 24 % 25:02d}T{n % 24:02d}:{n // 24 % 60:02d}:00+00:00"


def seed(world, vectors=0, photos=0, mixed=0) -> dict:
    """Works with names that say what they are: ``V001``.., ``P001``.. and ``M001``..; the later the number, the newer the work."""
    made, n = {}, 0
    for kind, how_many in (("V", vectors), ("P", photos), ("M", mixed)):
        for i in range(1, how_many + 1):
            n += 1
            name = f"{kind}{i:03d}"
            if kind == "P":
                made[name] = add_photo(world, name, updated=stamp(n), laser=i % 2, lens=i % 2, material=i % 2)
            else:
                made[name] = add_vector(world, name, updated=stamp(n), zones=2 if kind == "M" else 0, texts=1 if kind == "M" else 0,
                                        laser=i % 2, lens=i % 2, material=i % 2)
    return made


# -- REQ-001: the first page, the search, the filters, the order --------------------------------------------------------------------------------
@node
def test_the_first_page_shows_at_most_twenty_works_with_thumbnail_name_type_size_state_and_date(served):
    made = seed(served, vectors=20, photos=15, mixed=10)
    out = screen(served, """
  const s = await open();
  out.rows = rowsOf(s).map(info);
  out.count = count(s);
  out.more = byText(s.el, 'button', 'Показать ещё 20') != null;
  out.first = gets()[0].url;
  out.gets = gets().length;
  out.heading = main.querySelector('h2').textContent;
  out.chips = chips(s);
""")
    assert len(out["rows"]) == 20 and out["count"] == "показано 20 из 45" and out["more"] and out["gets"] == 1 and out["heading"] == "Работы"
    assert "limit=20" in out["first"] and "offset=0" in out["first"]
    assert out["chips"] == ["Все · 45", "Векторные · 20", "Смешанные · 10", "Фотогравировка · 15"]
    newest = out["rows"][0]                                      # the newest work first: M010 (the last one made)
    assert newest["name"] == "M010" and newest["pills"] == ["Смешанная", "Подготовлена"] and newest["parts"] == "2 фотозоны · 1 надпись"
    assert newest["href"] == f"#/vector?plan={made['M010']}" and newest["img"].startswith(f"/api/vector/{made['M010']}/thumb.png?v=")
    assert newest["size"] == "60.0 × 40.0 мм" and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", newest["date"]) and newest["equipment"] == "Laser Alpha · F-Theta 175 · Sheet two"
    photo = next(r for r in out["rows"] if r["name"] == "P015")
    assert photo["href"] == f"#/photo-engraving?work={made['P015']}" and photo["pills"] == ["Фотогравировка", "Подготовлена"] and photo["size"] == "60.0 × 30.0 мм"
    assert photo["img"].startswith(f"/api/photo-works/{made['P015']}/thumb.png?v=") and photo["parts"] is None
    assert [r["name"] for r in out["rows"][:3]] == ["M010", "M009", "M008"]


@node
def test_show_more_adds_one_portion_at_a_time_and_a_work_is_never_listed_twice(served):
    seed(served, vectors=30, photos=15)
    out = screen(served, """
  const s = await open();
  const more = () => byText(s.el, 'button', 'Показать ещё 20') || s.el.querySelector('.lst-foot').querySelector('button');
  await more().dispatch('click'); await until(() => rowsOf(s).length === 40, 'forty rows');
  await more().dispatch('click'); await until(() => rowsOf(s).length === 45, 'all rows');
  out.names = names(s); out.count = count(s); out.more = s.el.querySelector('.lst-foot').querySelector('button');
  out.offsets = gets().map((x) => /offset=(\\d+)/.exec(x.url)[1]);
""")
    assert len(out["names"]) == 45 == len(set(out["names"])) and out["count"] == "показано 45 из 45" and out["more"] is None
    assert out["offsets"] == ["0", "20", "40"]


@node
def test_search_the_type_and_equipment_filters_and_the_order_narrow_one_list_with_counts_and_one_reset(served):
    seed(served, vectors=4, photos=3, mixed=2)
    laser_b = served["lasers"][1]["id"]
    out = screen(served, f"""
  const s = await open();
  out.start = {{count: count(s), chips: chips(s), selects: s.el.querySelectorAll('.lst-select').map((l) => l.textContent.split('\\n')[0])}};
  const laser = s.el.querySelectorAll('select').find((x) => x.parentNode.textContent.startsWith('Лазер'));
  out.laserOptions = laser.options.map((o) => o.textContent);
  await byText(s.el, 'button', 'Фотогравировка · 3').dispatch('click');
  await until(() => count(s) === 'показано 3 из 3', 'photo works');
  out.photo = {{names: names(s), url: gets().pop().url, address: ctx.location.hash}};
  await byText(s.el, 'button', 'Все · 9').dispatch('click');
  laser.value = {laser_b}; await laser.dispatch('change');
  await until(() => count(s) === 'показано 5 из 5', 'laser B works');
  out.laser = {{names: names(s), chips: chips(s), address: ctx.location.hash, lensOptions: s.el.querySelectorAll('select').find((x) => x.parentNode.textContent.startsWith('Линза')).options.map((o) => o.textContent)}};
  const search = s.el.querySelector('.lst-search'); search.value = 'v00'; await search.dispatch('input');
  await until(() => names(s).every((n) => n.startsWith('V')), 'search');
  out.searched = {{names: names(s), count: count(s), address: ctx.location.hash, chips: chips(s)}};
  const sort = s.el.querySelectorAll('select').find((x) => x.getAttribute('aria-label') === 'Порядок');
  out.sortOptions = sort.options.map((o) => o.textContent);
  sort.value = 'name'; await sort.dispatch('change');
  await until(() => names(s).join() === [...names(s)].sort().join() && gets().pop().url.includes('sort=name'), 'sorted by name');
  out.sorted = {{names: names(s), address: ctx.location.hash}};
  const reset = s.el.querySelector('.lst-reset'); out.resetShown = !reset.hidden;
  await reset.dispatch('click');
  await until(() => count(s) === 'показано 9 из 9', 'reset');
  out.reset = {{count: count(s), search: search.value, address: ctx.location.hash, state: s.list.state(), resetHidden: reset.hidden}};
""")
    assert out["start"]["count"] == "показано 9 из 9" and out["start"]["chips"] == ["Все · 9", "Векторные · 4", "Смешанные · 2", "Фотогравировка · 3"]
    assert out["laserOptions"] == ["любой · 9", "Laser Alpha · 4", "Laser Beta · 5"]
    assert sorted(out["photo"]["names"]) == ["P001", "P002", "P003"] and "type=photo" in out["photo"]["url"] and out["photo"]["address"] == "#/works?type=photo"
    assert out["laser"]["address"] == f"#/works?laser={laser_b}" and sorted(out["laser"]["names"]) == ["M001", "P001", "P003", "V001", "V003"]
    assert out["laser"]["chips"] == ["Все · 5", "Векторные · 2", "Смешанные · 1", "Фотогравировка · 2"]       # a count is what the chip would show with the laser as chosen
    assert out["laser"]["lensOptions"][0] == "любая · 5"
    assert sorted(out["searched"]["names"]) == ["V001", "V003"] and out["searched"]["count"] == "показано 2 из 2"
    assert out["searched"]["address"] == f"#/works?q=v00&laser={laser_b}"
    assert out["sortOptions"] == ["Сначала недавно изменённые", "Сначала давно изменённые", "По названию"]
    assert out["sorted"]["names"] == ["V001", "V003"] and out["sorted"]["address"] == f"#/works?q=v00&laser={laser_b}&sort=name"
    assert out["resetShown"] is True
    assert out["reset"] == {"count": "показано 9 из 9", "search": "", "address": "#/works?sort=name", "resetHidden": True,
                            "state": {"sort": "name", "filters": {"type": "", "laser": "", "lens": "", "material": ""}, "search": "", "shown": 20}}


@node
def test_a_work_with_no_laser_lens_or_material_is_found_by_the_none_choice(served):
    seed(served, vectors=2)
    add_photo(served, "Bare", updated=stamp(50), laser=0, lens=None, material=None)
    out = screen(served, """
  const s = await open();
  const lens = s.el.querySelectorAll('select').find((x) => x.parentNode.textContent.startsWith('Линза'));
  out.options = lens.options.map((o) => o.textContent);
  lens.value = 'none'; await lens.dispatch('change');
  await until(() => count(s) === 'показано 1 из 1', 'works with no lens');
  out.names = names(s); out.equipment = info(rowsOf(s)[0]).equipment; out.url = gets().pop().url;
""")
    assert out["options"][-1] == "линза не известна · 1" and out["names"] == ["Bare"] and "lens=none" in out["url"]
    assert out["equipment"] == "Laser Alpha · линза не известна · заготовка не указана"


@node
def test_nothing_found_and_an_empty_catalog_each_say_so_and_leave_a_way_out(served):
    out = screen(served, """
  const empty = await open();
  out.empty = {text: empty.el.querySelector('.lst-empty').textContent, hasReset: empty.el.querySelector('.lst-none') != null, count: count(empty)};
""")
    assert "Работ пока нет" in out["empty"]["text"] and "Новая работа" in out["empty"]["text"] and out["empty"]["hasReset"] is False
    seed(served, vectors=3)
    out = screen(served, """
  const s = await open();
  const search = s.el.querySelector('.lst-search'); search.value = 'такого нет'; await search.dispatch('input');
  await until(() => s.el.querySelector('.lst-none'), 'nothing found');
  out.none = s.el.querySelector('.lst-none').textContent;
  await byText(s.el.querySelector('.lst-none'), 'button', 'Сбросить поиск и фильтры').dispatch('click');
  await until(() => names(s).length === 3, 'the list again');
  out.after = names(s);
""")
    assert "Работ по этим условиям нет." in out["none"] and "такого нет" in out["none"] and sorted(out["after"]) == ["V001", "V002", "V003"]


@node
def test_a_failed_read_says_so_keeps_the_screen_and_the_retry_reads_again(served):
    seed(served, vectors=3)
    out = screen(served, """
  breaks.push('/api/works?');
  const s = await open();
  out.failure = s.el.querySelector('.lst-fail').textContent;
  out.rowsAfterFailure = rowsOf(s).length;
  out.stillHasToolbar = s.el.querySelector('.lst-search') != null && byText(main, 'button', 'Список') != null;
  await byText(s.el, 'button', 'Повторить').dispatch('click');
  await until(() => rowsOf(s).length === 3, 'the retry');
  out.failureAfter = s.el.querySelector('.lst-fail') != null;
""")
    assert out["failure"].startswith("Не удалось загрузить список") and out["rowsAfterFailure"] == 0 and out["stillHasToolbar"] and out["failureAfter"] is False


# -- the gallery: the same list, the same query -----------------------------------------------------------------------------------------------
@node
def test_the_gallery_is_the_same_list_with_the_same_query_and_is_remembered(served):
    seed(served, vectors=3, photos=2)
    out = screen(served, """
  const s = await open();
  const list = byText(s.el.parentNode, 'button', 'Список'), gallery = byText(s.el.parentNode, 'button', 'Галерея');
  const search = s.el.querySelector('.lst-search'); search.value = 'v0'; await search.dispatch('input');
  await until(() => names(s).length === 3, 'search');
  const before = rowsOf(s)[0], requestsBefore = log.length;
  out.listView = {gallery: s.el.classList.contains('works-gallery'), pressed: [list, gallery].map((b) => b.getAttribute('aria-pressed'))};
  await gallery.dispatch('click');
  out.galleryView = {gallery: s.el.classList.contains('works-gallery'), pressed: [list, gallery].map((b) => b.getAttribute('aria-pressed')), address: ctx.location.hash,
    sameRow: rowsOf(s)[0] === before, newRequests: log.length - requestsBefore, state: s.list.state(), names: names(s), stored: kept['works.view']};
  const again = await open({});                                   // a new visit with no address in the same browser
  out.remembered = again.el.classList.contains('works-gallery');
  const forced = await open({view: 'list'});                      // an address that says «list» wins over what was remembered
  out.forced = forced.el.classList.contains('works-gallery');
  const addressed = await open({view: 'gallery', q: 'p0'});
  out.addressed = {gallery: addressed.el.classList.contains('works-gallery'), names: names(addressed), search: addressed.el.querySelector('.lst-search').value};
  await byText(addressed.el.parentNode, 'button', 'Список').dispatch('click');
  out.back = {gallery: addressed.el.classList.contains('works-gallery'), address: ctx.location.hash, stored: kept['works.view']};
""")
    assert out["listView"] == {"gallery": False, "pressed": ["true", "false"]}
    assert out["galleryView"]["gallery"] is True and out["galleryView"]["pressed"] == ["false", "true"] and out["galleryView"]["address"] == "#/works?view=gallery&q=v0"
    assert out["galleryView"]["sameRow"] is True and out["galleryView"]["newRequests"] == 0 and out["galleryView"]["stored"] == "gallery"      # a view is a look, not a read
    assert out["galleryView"]["state"]["search"] == "v0" and len(out["galleryView"]["names"]) == 3
    assert out["remembered"] is True and out["forced"] is False
    assert out["addressed"] == {"gallery": True, "names": ["P002", "P001"], "search": "p0"}
    assert out["back"] == {"gallery": False, "address": "#/works?q=p0", "stored": "list"}


# -- coming back: view, search, filters, order and position --------------------------------------------------------------------------------------
@node
def test_the_address_carries_the_query_and_opening_it_again_restores_search_filters_order_and_view(served):
    seed(served, vectors=6, photos=6, mixed=3)
    laser_a = served["lasers"][0]["id"]
    out = screen(served, f"""
  const s = await open({{view: 'gallery', q: 'p', type: 'photo', laser: '{laser_a}', sort: 'name'}});
  out.state = s.list.state();
  out.gallery = s.el.classList.contains('works-gallery');
  out.names = names(s);
  out.search = s.el.querySelector('.lst-search').value;
  out.pressed = s.el.querySelectorAll('.lst-chip').filter((c) => c.getAttribute('aria-pressed') === 'true').map((c) => c.textContent);
  out.laserChosen = s.el.querySelectorAll('select').find((x) => x.parentNode.textContent.startsWith('Лазер')).value;
  out.sortChosen = s.el.querySelectorAll('select').find((x) => x.getAttribute('aria-label') === 'Порядок').value;
  out.firstUrl = gets()[0].url;
  out.address = ctx.location.hash;
  out.addressOfScreen = s.address();
""")
    assert out["state"]["search"] == "p" and out["state"]["sort"] == "name" and out["state"]["filters"] == {"type": "photo", "laser": str(laser_a), "lens": "", "material": ""}
    assert out["gallery"] is True and out["search"] == "p" and out["pressed"] == ["Фотогравировка · 3"] and out["laserChosen"] == str(laser_a) and out["sortChosen"] == "name"
    assert out["names"] == ["P002", "P004", "P006"] or out["names"] == sorted(out["names"])
    for part in ("q=p", "type=photo", f"laser={laser_a}", "sort=name"):
        assert part in out["firstUrl"], part
    assert out["address"] == "#" + out["addressOfScreen"] and out["address"].startswith("#/works?view=gallery&q=p&type=photo")


@node
def test_coming_back_from_a_work_far_down_the_list_shows_it_again_in_view_with_the_focus_on_it(served):
    made = seed(served, vectors=70)
    out = screen(served, """
  const s = await open();
  for (const want of [40, 60]) { await byText(s.el, 'button', 'Показать ещё 20').dispatch('click'); await until(() => rowsOf(s).length === want, want + ' rows'); }
  const row = rowsOf(s)[45], link = row.querySelector('.works-name');
  out.target = {key: row.getAttribute('data-key'), name: link.textContent, href: link.getAttribute('href')};
  await link.dispatch('click', {button: 0});                        // the person opens the work: the editor takes the screen
  out.leaving = ctx.location.hash;
  const back = asQuery();                                            // the browser's Back: the router renders the catalog for this address
  log.length = 0;
  const s2 = await open(back);
  await sleep(30);
  out.restored = {rows: rowsOf(s2).length, count: count(s2), firstGet: gets()[0].url, gets: gets().length, address: ctx.location.hash,
    focus: active() === rowsOf(s2)[45].querySelector('.works-name'), scrolled: scrolled.includes(rowsOf(s2)[45]), notice: main.querySelector('.works-notice').textContent};
  // an operation afterwards reads the list again and does not shrink it to the first page
  await choose(rowsOf(s2)[0], 'Переименовать…'); dialog().querySelector('input').value = 'Новое имя';
  await byText(dialog(), 'button', 'Сохранить').dispatch('click'); await until(() => names(s2).includes('Новое имя'), 'rename refreshed');
  out.afterRename = {rows: rowsOf(s2).length, count: count(s2), limit: gets().pop().url};
  // another search forgets the place
  const search = s2.el.querySelector('.lst-search'); search.value = 'v0'; await search.dispatch('input');
  await until(() => !asQuery().at && s2.list.state().search === 'v0', 'the place forgotten');
  out.afterSearch = ctx.location.hash;
""")
    assert out["target"]["name"] == "V025" and out["target"]["href"] == f"#/vector?plan={made['V025']}"          # the 46th newest of 70
    assert out["leaving"] == f"#/works?at=vector-{made['V025']}"
    restored = out["restored"]
    assert restored["rows"] == 60 and restored["count"] == "показано 60 из 70" and restored["gets"] == 1 and f"through=vector-{made['V025']}" in restored["firstGet"]
    assert restored["focus"] is True and restored["scrolled"] is True and restored["notice"] == "" and restored["address"] == out["leaving"]
    assert out["afterRename"]["rows"] == 60 and out["afterRename"]["count"] == "показано 60 из 70" and "limit=60" in out["afterRename"]["limit"]
    assert out["afterSearch"].startswith("#/works?q=v0") and "at=" not in out["afterSearch"]


@node
def test_a_work_that_is_gone_or_hidden_when_the_person_comes_back_is_said_and_the_list_starts_from_the_top(served):
    made = seed(served, vectors=30, photos=1)
    out = screen(served, f"""
  const gone = await open({{at: 'vector-999999'}});
  out.gone = {{rows: rowsOf(gone).length, notice: main.querySelector('.works-notice').textContent, address: ctx.location.hash, state: gone.state()}};
  const hidden = await open({{type: 'vector', at: 'photo-{made["P001"]}'}});
  const notice = main.querySelector('.works-notice');
  out.hidden = {{notice: notice.textContent, link: notice.querySelector('a').getAttribute('href'), type: hidden.list.state().filters.type, address: ctx.location.hash}};
  await byText(notice, 'button', 'Сбросить поиск и фильтры').dispatch('click');
  await until(() => count(hidden) === 'показано 20 из 31', 'reset');
  out.afterReset = {{notice: main.querySelector('.works-notice').textContent, count: count(hidden)}};
  const far = await open({{at: 'vector-{made["V001"]}'}});                  // the oldest of 31 works: beyond the first portion, inside what the server extends to
  await sleep(30);
  out.far = {{rows: rowsOf(far).length, focus: active() === rowsOf(far)[30].querySelector('.works-name'), notice: main.querySelector('.works-notice').textContent}};
  const requests = log.filter((x) => x.url.includes('/api/experiments') || x.url.includes('/api/pairs'));
  out.otherAreas = requests.length;
""")
    assert out["gone"]["rows"] == 20 and "больше не существует" in out["gone"]["notice"] and "Список показан с начала" in out["gone"]["notice"]
    assert out["gone"]["address"] == "#/works" and out["gone"]["state"]["at"] is None
    assert "не показана" in out["hidden"]["notice"] and out["hidden"]["link"] == f"#/photo-engraving?work={made['P001']}"
    assert out["hidden"]["type"] == "vector" and out["hidden"]["address"] == "#/works?type=vector"
    assert out["afterReset"] == {"notice": "", "count": "показано 20 из 31"}
    assert out["far"]["rows"] == 31                                               # whole portions up to the work (20 + 20), as many as there are
    assert out["far"]["focus"] is True and out["far"]["notice"] == "" and out["otherAreas"] == 0


# -- REQ-002: the menu, rename, copy, delete ----------------------------------------------------------------------------------------------------
@node
def test_the_row_menu_opens_with_the_keyboard_moves_closes_with_escape_and_only_one_is_open(served):
    seed(served, vectors=2)
    out = screen(served, """
  const s = await open();
  const [one, two] = rowsOf(s);
  const button = menuButton(one), popup = one.querySelector('.works-menu');
  out.label = button.getAttribute('aria-label'); out.closed = {hidden: popup.hidden, expanded: button.getAttribute('aria-expanded')};
  button.focus(); await button.dispatch('keydown', {key: 'ArrowDown'});
  out.opened = {hidden: popup.hidden, expanded: button.getAttribute('aria-expanded'), focus: active().textContent, items: one.querySelectorAll('.works-menu-item').map((b) => b.textContent)};
  await active().dispatch('keydown', {key: 'ArrowDown'}); out.down = active().textContent;
  await active().dispatch('keydown', {key: 'End'}); out.end = active().textContent;
  await active().dispatch('keydown', {key: 'ArrowDown'}); out.wrap = active().textContent;
  await active().dispatch('keydown', {key: 'ArrowUp'}); out.up = active().textContent;
  await menuButton(two).dispatch('click');                          // another row's menu: the first closes
  out.second = {firstHidden: popup.hidden, secondHidden: two.querySelector('.works-menu').hidden};
  await active().dispatch('keydown', {key: 'Escape'});
  out.escaped = {hidden: two.querySelector('.works-menu').hidden, focus: active() === menuButton(two), expanded: menuButton(two).getAttribute('aria-expanded')};
  await menuButton(one).dispatch('click');
  await doc.dispatch('click');                                      // a click anywhere else
  out.outside = {hidden: popup.hidden, expanded: menuButton(one).getAttribute('aria-expanded')};
""")
    assert out["label"] == "Действия с работой «V002»" and out["closed"] == {"hidden": True, "expanded": "false"}
    assert out["opened"] == {"hidden": False, "expanded": "true", "focus": "Переименовать…", "items": ["Переименовать…", "Сделать копию", "Удалить…"]}
    assert (out["down"], out["end"], out["wrap"], out["up"]) == ("Сделать копию", "Удалить…", "Переименовать…", "Удалить…")
    assert out["second"] == {"firstHidden": True, "secondHidden": False} and out["escaped"] == {"hidden": True, "focus": True, "expanded": "false"}
    assert out["outside"] == {"hidden": True, "expanded": "false"}


@node
def test_rename_goes_through_the_owners_route_keeps_the_place_and_refreshes_the_catalog(served):
    made = seed(served, vectors=2, photos=1)
    out = screen(served, """
  const s = await open();
  await choose(rowNamed(s, 'V001'), 'Переименовать…');
  const box = dialog(), input = box.querySelector('input');
  out.dialog = {title: box.querySelector('h3').textContent, value: input.value, label: input.getAttribute('aria-label')};
  input.value = '   '; await byText(box, 'button', 'Сохранить').dispatch('click');
  out.emptyRefused = {toast: toasts(), posts: posts().length, stillOpen: dialog() != null};
  input.value = 'V001'; await byText(box, 'button', 'Сохранить').dispatch('click');
  out.unchanged = {posts: posts().length, closed: dialog() == null};
  await choose(rowNamed(s, 'V001'), 'Переименовать…');
  const box2 = dialog(); box2.querySelector('input').value = ' Витраж ';
  const getsBefore = gets().length;
  await byText(box2, 'button', 'Сохранить').dispatch('click');
  await until(() => names(s).includes('Витраж'), 'renamed');
  out.renamed = {posts: posts(), closed: dialog() == null, names: names(s), refreshed: gets().length - getsBefore, toast: toasts(),
    focus: active() === menuButton(rowNamed(s, 'Витраж')), dated: info(rowNamed(s, 'Витраж')).date};
  await choose(rowNamed(s, 'P001'), 'Переименовать…');
  const box3 = dialog(); box3.querySelector('input').value = 'Портрет';
  await byText(box3, 'button', 'Сохранить').dispatch('click');
  await until(() => names(s).includes('Портрет'), 'photo work renamed');
  out.photo = posts().pop();
""")
    assert out["dialog"] == {"title": "Переименовать работу", "value": "V001", "label": "Название работы"}
    assert "Впишите название работы" in out["emptyRefused"]["toast"] and out["emptyRefused"]["posts"] == 0 and out["emptyRefused"]["stillOpen"]
    assert out["unchanged"] == {"posts": 0, "closed": True}
    assert out["renamed"]["posts"] == [f'/api/vector/{made["V001"]}/rename {{"name":"Витраж"}}'] and out["renamed"]["closed"] and out["renamed"]["refreshed"] >= 1
    assert "Витраж" in out["renamed"]["names"] and "V001" not in out["renamed"]["names"] and "Работа переименована" in out["renamed"]["toast"] and out["renamed"]["focus"] is True
    assert out["photo"] == f'/api/photo-works/{made["P001"]}/rename {{"name":"Портрет"}}'


@node
def test_rename_of_a_work_that_has_gone_says_so_closes_and_the_catalog_is_read_again(served):
    made = seed(served, vectors=2)
    out = screen(served, f"""
  const s = await open();
  await choose(rowNamed(s, 'V001'), 'Переименовать…');
  const box = dialog(); box.querySelector('input').value = 'Другое';
  await fetch('http://127.0.0.1:{served["port"]}/api/plans/{made["V001"]}', {{method: 'DELETE'}});          // deleted elsewhere meanwhile
  const getsBefore = gets().length;
  await byText(box, 'button', 'Сохранить').dispatch('click');
  await until(() => names(s).length === 1, 'refreshed');
  out.after = {{names: names(s), closed: dialog() == null, toast: toasts(), refreshed: gets().length - getsBefore}};
""")
    assert out["after"]["names"] == ["V002"] and out["after"]["closed"] is True and out["after"]["refreshed"] >= 1
    assert out["after"]["toast"] and "plan" not in out["after"]["toast"]                  # said in Russian, not as the server's English


@node
def test_copy_makes_a_work_next_to_the_first_and_a_failed_copy_still_refreshes_the_catalog(real):
    client = real["client"]
    vector = create_vector_work(real)
    client.post(f"/api/vector/{vector['id']}/rename", json={"name": "Копируемая векторная"})
    photo = create_photo_work(client, name="Копируемое фото")
    out = screen(real, f"""
  const s = await open({{q: 'Копируемая Копируемое'.split(' ')[0]}});
  const both = await open({{q: 'Копируем'}});
  out.start = names(both).sort();
  await choose(rowNamed(both, 'Копируемое фото'), 'Сделать копию');
  await until(() => names(both).length === 3, 'the copy of the photo work');
  out.copy = {{posts: posts(), names: names(both).sort(), toast: toasts(), focus: active() === menuButton(rowNamed(both, 'Копируемое фото'))}};
  await choose(rowNamed(both, 'Копируемая векторная'), 'Сделать копию');
  await until(() => names(both).length === 4, 'the copy of the vector work');
  out.vector = {{posts: posts().pop(), names: names(both).sort(), types: rowsOf(both).map((r) => info(r).pills[0]).sort()}};
  await fetch('http://127.0.0.1:{real["port"]}/api/plans/{vector["id"]}', {{method: 'DELETE'}});          // deleted elsewhere meanwhile
  const row = rowNamed(both, 'Копируемая векторная'), before = gets().length, postsBefore = posts().length;
  await choose(row, 'Сделать копию');
  await until(() => names(both).length === 3, 'the failed copy');
  out.failed = {{names: names(both).sort(), refreshed: gets().length - before, toast: toasts(), posts: posts().length - postsBefore}};
""")
    assert out["start"] == ["Копируемая векторная", "Копируемое фото"]
    assert out["copy"]["posts"] == [f'/api/photo-works/{photo["id"]}/copy {{}}'] and sum(1 for n in out["copy"]["names"] if n.startswith("Копируемое фото")) == 2
    assert "Копия создана" in out["copy"]["toast"] and out["copy"]["focus"] is True
    assert out["vector"]["posts"] == f'/api/vector/{vector["id"]}/copy {{}}' and sum(1 for n in out["vector"]["names"] if n.startswith("Копируемая векторная")) == 2
    assert out["vector"]["types"].count("Векторная") == 2 and out["vector"]["types"].count("Фотогравировка") == 2
    assert "Копируемая векторная" not in out["failed"]["names"] and len(out["failed"]["names"]) == 3 and out["failed"]["refreshed"] >= 1
    assert out["failed"]["posts"] == 1 and "plan" not in out["failed"]["toast"].split("Копия создана")[-1]


@node
def test_real_works_are_listed_as_what_they_are_and_a_mixed_work_is_one_row_with_its_zones_and_lettering(real):
    plain = create_vector_work(real)
    mixed = create_vector_work(real)
    colouring(real, mixed, op="photo_add", regions=of_colour(real, mixed, RED))
    add_inscription(real, mixed)
    for work, name in ((plain, "Подлинная простая"), (mixed, "Подлинная смешанная")):
        real["client"].post(f"/api/vector/{work['id']}/rename", json={"name": name})
    photo = create_photo_work(real["client"], name="Подлинное фото")
    out = screen(real, """
  const s = await open({q: 'Подлинн'});
  out.rows = rowsOf(s).map(info);
  const thumbs = [];
  for (const row of rowsOf(s)) { const src = info(row).img; const res = await fetch('http://127.0.0.1:' + PORT + src); thumbs.push([res.status, res.headers.get('content-type')]); }
  out.thumbs = thumbs;
  out.editors = [];
  for (const row of rowsOf(s)) {
    const href = info(row).href.slice(1), [path, query] = href.split('?');
    const id = new URLSearchParams(query).get('plan') || new URLSearchParams(query).get('work');
    const res = await fetch('http://127.0.0.1:' + PORT + (path === '/vector' ? '/api/vector/' : '/api/photo-works/') + id);
    out.editors.push([path, res.status]);
  }
""")
    by_name = {r["name"]: r for r in out["rows"]}
    assert sorted(by_name) == ["Подлинная простая", "Подлинная смешанная", "Подлинное фото"] and len(out["rows"]) == 3
    assert by_name["Подлинная смешанная"]["pills"][0] == "Смешанная" and by_name["Подлинная смешанная"]["parts"] == "1 фотозона · 1 надпись"
    assert by_name["Подлинная простая"]["pills"][0] == "Векторная" and by_name["Подлинная простая"]["parts"] is None
    assert by_name["Подлинное фото"]["pills"][0] == "Фотогравировка" and by_name["Подлинное фото"]["size"] == "60.0 × 30.0 мм"
    assert by_name["Подлинная смешанная"]["size"] == "60.0 × 45.0 мм"
    assert by_name["Подлинная простая"]["href"] == f"#/vector?plan={plain['id']}" and by_name["Подлинное фото"]["href"] == f"#/photo-engraving?work={photo['id']}"
    assert out["thumbs"] == [[200, "image/png"]] * 3 and sorted(out["editors"]) == [["/photo-engraving", 200], ["/vector", 200], ["/vector", 200]]


@node
def test_delete_asks_first_cancel_has_the_focus_and_one_confirmation_deletes_once_and_moves_the_focus_on(served):
    made = seed(served, vectors=3, photos=1)
    out = screen(served, """
  const s = await open();                                            // newest first: P001, V003, V002, V001
  await choose(rowNamed(s, 'V002'), 'Удалить…');
  const box = dialog();
  out.asked = {title: box.querySelector('h3').textContent, text: box.querySelector('p').textContent, focus: active().textContent, deletes: deletes().length,
    buttons: box.querySelectorAll('button').map((b) => b.textContent)};
  await active().dispatch('click');                                  // «Отмена», which has the focus: a quick Enter confirms nothing
  out.cancelled = {closed: dialog() == null, deletes: deletes().length, names: names(s), focus: active() === menuButton(rowNamed(s, 'V002'))};
  await choose(rowNamed(s, 'P001'), 'Удалить…');
  out.photoText = dialog().querySelector('p').textContent;
  await byText(dialog(), 'button', 'Отмена').dispatch('click');
  await choose(rowNamed(s, 'V002'), 'Удалить…');
  const confirm = byText(dialog(), 'button', 'Удалить'), getsBefore = gets().length;
  await Promise.all([confirm.dispatch('click'), confirm.dispatch('click')]);          // a double click
  await until(() => names(s).length === 3, 'deleted');
  await sleep(30);
  out.deleted = {deletes: deletes(), names: names(s), refreshed: gets().length - getsBefore, closed: dialog() == null, toast: toasts(),
    focus: active() === rowNamed(s, 'V001').querySelector('.works-name') || active() === rowNamed(s, 'V003').querySelector('.works-name'), count: count(s)};
""")
    assert out["asked"]["title"] == "Удалить работу «V002»?" and out["asked"]["focus"] == "Отмена" and out["asked"]["deletes"] == 0
    assert "вернуть работу будет нельзя" in out["asked"]["text"] and "сначала сделайте копию" in out["asked"]["text"]
    assert out["asked"]["buttons"] == ["×", "Отмена", "Удалить"]
    assert out["cancelled"] == {"closed": True, "deletes": 0, "names": ["P001", "V003", "V002", "V001"], "focus": True}
    assert out["photoText"].startswith("Исчезнут картинка и настройки работы") and "Исчезнут исходная картинка" not in out["photoText"]
    assert out["deleted"]["deletes"] == [f"/api/plans/{made['V002']}"] and out["deleted"]["names"] == ["P001", "V003", "V001"]
    assert out["deleted"]["refreshed"] >= 1 and out["deleted"]["closed"] and "Работа удалена" in out["deleted"]["toast"] and out["deleted"]["focus"] is True
    assert out["deleted"]["count"] == "показано 3 из 3"


@node
def test_a_work_with_photographs_cannot_be_deleted_here_and_the_catalog_says_why_and_reads_again(served):
    made = seed(served, vectors=2)
    work_pair(served, made["V001"], 3)                                  # a photograph of the engraving: the work is also an experiment now
    out = screen(served, """
  const s = await open();
  out.state = info(rowNamed(s, 'V001')).pills;
  await choose(rowNamed(s, 'V001'), 'Удалить…');
  out.warned = dialog().querySelector('p').textContent;
  const getsBefore = gets().length;
  await byText(dialog(), 'button', 'Удалить').dispatch('click');
  await until(() => dialog() == null && gets().length > getsBefore, 'refused and read again');
  out.after = {names: names(s), toast: toasts(), deletes: deletes(), refreshed: gets().length - getsBefore};
""")
    assert out["state"] == ["Векторная", "Результат добавлен"] and "У работы есть фотографии гравировки" in out["warned"]
    assert out["after"]["names"] == ["V002", "V001"] and out["after"]["toast"] and out["after"]["refreshed"] >= 1
    assert out["after"]["deletes"] == [f"/api/plans/{made['V001']}"]
    assert served["app"].state.store.one("SELECT COUNT(*) AS n FROM plan WHERE id=?", (made["V001"],))["n"] == 1


@node
def test_a_work_whose_data_cannot_be_read_is_listed_with_a_reason_and_offers_no_operation(served):
    made = seed(served, vectors=1)
    served["store"].execute("UPDATE plan SET data_json=? WHERE id=?", ("{not json", made["V001"]))
    out = screen(served, """
  const s = await open();
  const row = rowsOf(s)[0];
  out.row = {text: row.textContent, link: row.querySelector('a'), menu: menuButton(row), class: row.className};
""")
    assert "Данные работы не читаются" in out["row"]["text"] and out["row"]["link"] is None and out["row"]["menu"] is None and "works-broken" in out["row"]["class"]


# -- creating a work: one function ------------------------------------------------------------------------------------------------------------------
@node
def test_creating_a_work_goes_through_one_function_that_the_menu_calls(served):
    out = screen(served, """
  const s = await open();
  const create = byText(main, 'button', 'Новая работа ▾');
  await create.dispatch('click');
  out.items = main.querySelectorAll('.works-menu-item').filter((b) => b.textContent.startsWith('Векторная') || b.textContent.startsWith('Фотогравировка')).map((b) => b.textContent);
  await main.querySelectorAll('.works-menu-item').find((b) => b.textContent.startsWith('Векторная')).dispatch('click');
  await create.dispatch('click');
  await main.querySelectorAll('.works-menu-item').find((b) => b.textContent.startsWith('Фотогравировка')).dispatch('click');
  out.went = [...ctx.__went];
  out.started = ctx.__started.splice(0);
  Works.startCreation('vector'); out.direct = ctx.__started.pop();
  Works.startCreation('photo'); out.directPhoto = ctx.__started.pop();
  out.src = Works.startCreation.toString();
""")
    assert out["items"][0].startswith("Векторная работа") and out["items"][1].startswith("Фотогравировка")
    assert out["went"] == [] and out["started"] == [{"result": None}, {"result": "photo"}]     # both kinds go to the creation screen's one entry
    assert out["direct"] == {"result": None} and out["directPhoto"] == {"result": "photo"}
    assert "Creation.start(" in out["src"] and "App.go(" not in out["src"]


@node
def test_the_screen_is_registered_for_the_router_and_renders_the_same_catalog(served):
    seed(served, vectors=2)
    out = screen(served, """
  const def = ctx.__screens.works;
  const tree = await def.render({query: {}});
  main.replaceChildren(tree);
  out.registered = def != null;
  out.rows = rowsOf({el: tree}).length;
  out.requests = log.filter((x) => !x.url.startsWith('/api/works')).map((x) => x.url);
""")
    assert out["registered"] and out["rows"] == 2 and out["requests"] == []          # the catalog reads only the catalog


# -- the shell of the screen: navigation, registration, nothing of other areas ------------------------------------------------------------------------------
def test_the_catalog_is_registered_in_the_page_the_menu_and_the_routes_and_the_old_ways_stay():
    index = (UI / "index.html").read_text(encoding="utf-8")
    router = (UI / "router.js").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="(/[^"]+)"', index)
    assert '<link rel="stylesheet" href="/works.css">' in index and (UI / "works.css").is_file()
    assert scripts.index("/screens/works.js") > max(scripts.index(s) for s in ("/app.js", "/dialogs.js", "/list.js", "/screens/vector.js", "/screens/photo-engraving.js", "/screens/creation.js"))
    assert scripts.index("/screens/works.js") < scripts.index("/boot.js")
    nav = re.findall(r"\['(/[\w-]+)', '", router[router.index("const NAV"):router.index("const ROUTE_ID")])
    assert "['/works', 'Работы']" in router and "works: 'works'" in router
    assert nav[nav.index("/photo-engraving") + 1] == "/works"                        # next to the two kinds of work it lists
    assert {"/vector", "/photo-engraving"} <= set(nav) and "vector: 'vector'" in router and "'photo-engraving': 'photo-engraving'" in router     # the old ways stay
    icons = re.findall(r"^\s+'<", router[router.index("const ICONS"):router.index("function icon")], re.M)
    assert len(icons) == len(nav)


def test_the_screen_uses_the_shared_list_the_dialogs_and_the_owners_operations_and_nothing_of_experiments():
    source = (UI / "screens" / "works.js").read_text(encoding="utf-8")
    assert "App.list({" in source and "confirmBox(" in source and "modal(" in source
    assert "`${w.base}/${w.id}/rename`" in source and "`${w.base}/${w.id}/copy`" in source and "del('/plans/' + w.id)" in source
    assert "/experiments" not in source and "/pairs" not in source and "innerHTML" not in source
    assert not re.search(r"\b(new Date|toLocaleString)\b", source)                       # the date is the server's, not recomputed here
