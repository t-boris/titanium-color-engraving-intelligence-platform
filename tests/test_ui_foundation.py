"""The shared UI foundation of the UX P0 pass: the compact list (feature ux-growing-collections-p0, REQ-003/004, BUG-012/013), the dialogs
(BUG-014, ux-accessible-layout-p0 REQ-001) and the skip link (BUG-015). Run in node over the small DOM of the other screen tests, which now
keeps real focus (a removed node loses it, as in a browser), so «the search keeps the cursor» is checked, not assumed. What a layout engine
or a screen reader would add is not claimed here."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = """
const {context, load, El} = require(%(dom)s);
const ctx = context(%(routes)s);
ctx.setInterval = () => 0;
const handlers = {};
ctx.addEventListener = (type, fn) => { handlers[type] = fn; };
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'router.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const App = ctx.App;
const doc = ctx.document;
const {h} = App;
const rows = (l) => l.el.querySelectorAll('.lst-main').map((r) => r.textContent);
const count = (l) => l.el.querySelector('.lst-count').textContent;
const wait = async (n = 4) => { for (let i = 0; i < n; i++) await tick(); };
const shell = new El('div'); shell.setAttribute('id', 'app'); doc.body.append(shell);
const mount = (l) => { shell.append(l.el); return l; };
const ITEMS = Array.from({length: 45}, (_, i) => ({id: i + 1, kind: i %% 3 === 0 ? 'a' : 'b', name: 'элемент ' + (i + 1)}));
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, body, routes=None):
    script = tmp_path / "foundation.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "ui": json.dumps(str(UI) + "/"),
                                 "tables": json.dumps(TABLES), "routes": json.dumps(routes or {}), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


# -- BUG-012: the search is the same field, and a redraw gives the focus back --------------------------------------------------------
@node
def test_typing_in_the_search_keeps_the_same_field_and_its_focus(tmp_path):
    out = run(tmp_path, """
  const l = mount(App.list({items: ITEMS, row: (x) => x.name, search: (x) => x.name}));
  await l.ready;
  const input = l.el.querySelector('.lst-search');
  input.focus();
  const same = [];
  for (const text of ['э', 'эл', 'элем', 'элемент 4']) {
    input.value = text; await input.dispatch('input'); await wait();
    same.push([l.el.querySelector('.lst-search') === input, doc.activeElement === input, input.value]);
  }
  out.same = same; out.rows = rows(l); out.count = count(l);
""")
    assert all(a and b for a, b, _ in out["same"]) and [v for *_, v in out["same"]] == ["э", "эл", "элем", "элемент 4"]
    assert out["count"] == "показано 7 из 7"


@node
def test_a_chip_row_and_an_opened_line_keep_the_focus_after_the_redraw(tmp_path):
    out = run(tmp_path, """
  const l = mount(App.list({items: ITEMS, key: (x) => x.id, row: (x) => x.name, details: (x) => h('p', {}, 'подробно ' + x.id),
    filters: [{key: 'kind', label: 'Вид', options: [['a', 'Первые'], ['b', 'Вторые']], test: (x, v) => x.kind === v}]}));
  await l.ready;
  const chip = l.el.querySelectorAll('.lst-chip').find((c) => c.getAttribute('data-value') === 'a');
  chip.focus(); await chip.dispatch('click'); await wait();
  const now = doc.activeElement;
  out.chip = [now && now.getAttribute('data-value'), now && now.getAttribute('aria-pressed')];
  const main = l.el.querySelectorAll('.lst-main')[1];
  main.focus(); await main.dispatch('click'); await wait();
  out.row = [doc.activeElement && doc.activeElement.parentNode.getAttribute('data-key'), doc.activeElement && doc.activeElement.getAttribute('aria-expanded')];
""")
    assert out["chip"] == ["a", "true"]
    assert out["row"] == ["4", "true"]                                                   # the second shown line of the first kind (id 4), now open


# -- BUG-013: one page at a time, an old answer is dropped, a failure can be repeated --------------------------------------------------
SERVER = """
  const gates = [];
  const asked = [];
  let failNext = false;
  const l = mount(App.list({
    load: (q) => { asked.push(q); const all = ITEMS.filter((x) => !q.search || x.name.includes(q.search));
      const answer = {items: all.slice(q.offset, q.offset + q.limit), total: all.length, counts: {}};
      if (failNext && q.offset > 0) { failNext = false; return Promise.reject(new Error('сервер не ответил')); }
      return new Promise((resolve) => gates.push(() => resolve(answer))); },
    key: (x) => x.id, row: (x) => x.name, search: true}));
  gates.shift()(); await l.ready;
"""


@node
def test_a_second_click_on_show_more_while_one_is_on_its_way_asks_once(tmp_path):
    out = run(tmp_path, SERVER + """
  const button = () => l.el.querySelector('.lst-foot').querySelector('button');
  button().dispatch('click'); button().dispatch('click'); await wait();
  out.asked = asked.filter((q) => q.offset === 20).length; out.label = button().textContent; out.disabled = button().disabled;
  gates.shift()(); await wait();
  out.rows = rows(l).length; out.ids = new Set(l.el.querySelectorAll('.lst-row').map((r) => r.getAttribute('data-key'))).size;
""")
    assert out["asked"] == 1 and out["label"] == "Загружаем…" and out["disabled"] is True
    assert out["rows"] == 40 and out["ids"] == 40


@node
def test_a_late_page_of_an_old_search_does_not_join_the_new_list(tmp_path):
    out = run(tmp_path, SERVER + """
  l.el.querySelector('.lst-foot').querySelector('button').dispatch('click'); await wait();          // the page of the old list is on its way
  const input = l.el.querySelector('.lst-search'); input.value = 'элемент 4'; await input.dispatch('input'); await new Promise((r) => setTimeout(r, 300));
  const [late, fresh] = gates.splice(0, 2);                                                         // the new search was asked second
  fresh(); await wait(); late(); await wait();                                                      // the old answer arrives last
  out.rows = rows(l); out.count = count(l);
""")
    assert out["rows"] == [f"элемент {n}" for n in (4, 40, 41, 42, 43, 44, 45)] and out["count"] == "показано 7 из 7"


@node
def test_a_failed_page_keeps_the_rows_the_search_and_offers_a_retry(tmp_path):
    out = run(tmp_path, SERVER + """
  failNext = true;
  const input = l.el.querySelector('.lst-search'); input.value = 'элемент'; input.focus();
  l.el.querySelector('.lst-foot').querySelector('button').dispatch('click'); await wait();
  out.alert = l.el.querySelector('.lst-fail').textContent; out.rows = rows(l).length; out.count = count(l);
  out.search = [l.el.querySelector('.lst-search') === input, input.value];
  l.el.querySelector('.lst-retry').dispatch('click'); await wait(); gates.shift()(); await wait();
  out.after = [rows(l).length, l.el.querySelector('.lst-fail'), count(l)];
""")
    assert out["alert"].startswith("Не удалось загрузить список: сервер не ответил") and out["rows"] == 20 and out["count"] == "показано 20 из 45"
    assert out["search"] == [True, "элемент"]
    assert out["after"] == [40, None, "показано 40 из 45"]


@node
def test_a_first_read_that_fails_is_said_beside_the_list_with_a_retry(tmp_path):
    out = run(tmp_path, """
  let fail = true;
  const l = mount(App.list({load: async (q) => { if (fail) throw new Error('нет связи'); return {items: ITEMS.slice(0, 3), total: 3, counts: {}}; },
    key: (x) => x.id, row: (x) => x.name}));
  await l.ready;
  out.failed = [l.el.querySelector('.lst-fail').getAttribute('role'), l.el.querySelector('.lst-empty')];
  fail = false;
  l.el.querySelector('.lst-retry').dispatch('click'); await wait();
  out.after = [rows(l), l.el.querySelector('.lst-fail')];
""")
    assert out["failed"] == ["alert", None]                                               # an error is not «nothing found»
    assert out["after"] == [["элемент 1", "элемент 2", "элемент 3"], None]


# -- REQ-004: nothing found is not an empty collection; the reset keeps the sort and the selection ----------------------------------------
@node
def test_nothing_found_offers_a_reset_that_clears_every_condition_and_keeps_the_sort(tmp_path):
    out = run(tmp_path, """
  const l = mount(App.list({items: ITEMS, key: (x) => x.id, row: (x) => x.name, search: (x) => x.name, empty: 'Пусто',
    filters: [{key: 'kind', label: 'Вид', options: [['a', 'Первые'], ['b', 'Вторые']], test: (x, v) => x.kind === v}],
    sorts: [['id', 'По порядку', (p, q) => p.id - q.id], ['back', 'С конца', (p, q) => q.id - p.id]], noResults: 'Таких нет.'}));
  await l.ready;
  const sort = l.el.querySelectorAll('select')[0]; sort.value = 'back'; await sort.dispatch('change'); await wait();
  await l.el.querySelectorAll('.lst-chip').find((c) => c.getAttribute('data-value') === 'a').dispatch('click'); await wait();
  const input = l.el.querySelector('.lst-search'); input.value = 'нет такого'; await input.dispatch('input'); await wait();
  out.none = [l.el.querySelector('.lst-empty').textContent, count(l), l.el.querySelector('.lst-none').textContent.includes('нет такого'), l.el.querySelector('.lst-reset').hidden];
  await l.el.querySelector('.lst-none').querySelector('button').dispatch('click'); await wait();
  out.reset = [count(l), l.state().sort, l.state().search, l.state().filters.kind, input.value, rows(l)[0], l.el.querySelector('.lst-reset').hidden];
""")
    assert out["none"] == ["Таких нет.", "показано 0 из 0", True, False]
    assert out["reset"] == ["показано 20 из 45", "back", "", "", "", "элемент 45", True]


@node
def test_an_empty_collection_is_told_apart_from_nothing_found(tmp_path):
    out = run(tmp_path, """
  const l = mount(App.list({items: [], row: (x) => x.name, search: (x) => x.name, empty: 'Материалов нет'}));
  await l.ready;
  out.text = l.el.querySelector('.lst-empty').textContent; out.reset = l.el.querySelector('.lst-none');
""")
    assert out["text"] == "Материалов нет" and out["reset"] is None


# -- REQ-003: the object in use stays findable ---------------------------------------------------------------------------------------------
PINNED = """
  let chosen = %(chosen)s;
  const l = mount(App.list({items: ITEMS, key: (x) => x.id, row: (x) => x.name, search: (x) => x.name, selected: () => chosen,
    filters: [{key: 'kind', label: 'Вид', options: [['a', 'Первые'], ['b', 'Вторые']], test: (x, v) => x.kind === v}],
    details: (x) => h('p', {}, 'подробно ' + x.id)}));
  await l.ready;
  const pin = () => l.el.querySelector('.lst-pin');
"""


@node
def test_a_selection_beyond_the_first_page_is_pinned_and_can_be_shown_in_the_list(tmp_path):
    out = run(tmp_path, PINNED % {"chosen": "30"} + """
  out.pinned = [pin().querySelector('.lst-pin-note').textContent, pin().querySelector('.lst-row').getAttribute('data-key')];
  await pin().querySelectorAll('button').find((b) => b.textContent === 'Показать в списке').dispatch('click'); await wait();
  out.after = [pin(), rows(l).length, count(l)];
""")
    assert out["pinned"][1] == "30" and out["pinned"][0].startswith("Выбранная строка вне показанной части списка")
    assert out["after"] == [None, 40, "показано 40 из 45"]


@node
def test_a_filter_that_excludes_the_selection_says_so_and_does_not_clear_it(tmp_path):
    out = run(tmp_path, PINNED % {"chosen": "2"} + """
  out.inView = pin();                                                                            // the 2nd item is on the first page
  await l.el.querySelectorAll('.lst-chip').find((c) => c.getAttribute('data-value') === 'a').dispatch('click'); await wait();
  out.pinned = [pin().querySelector('.lst-pin-note').textContent, pin().querySelector('.lst-row').getAttribute('data-key'), chosen];
  await pin().querySelectorAll('button').find((b) => b.textContent === 'Сбросить поиск и фильтры').dispatch('click'); await wait();
  out.after = [pin(), count(l), chosen];
""")
    assert out["inView"] is None
    assert out["pinned"][0].startswith("Выбранная строка скрыта: она не подходит под поиск или фильтры") and out["pinned"][1:] == ["2", 2]
    assert out["after"] == [None, "показано 20 из 45", 2]


@node
def test_opening_a_line_that_is_not_shown_never_ends_in_a_silent_null(tmp_path):
    out = run(tmp_path, PINNED % {"chosen": "null"} + """
  const far = await l.open(33);                                                                  // beyond the page: the list grows to it
  out.far = [far && far.textContent, rows(l).length, pin()];
  await l.el.querySelectorAll('.lst-chip').find((c) => c.getAttribute('data-value') === 'a').dispatch('click'); await wait();
  const hidden = await l.open(2);                                                                // hidden by the filter: pinned with the reason
  out.hidden = [hidden && hidden.textContent, pin().querySelector('.lst-pin-note').textContent];
  const gone = await l.open(999);
  out.gone = [gone, pin().querySelector('.lst-pin-note').textContent];
""")
    assert out["far"] == ["подробно 33", 40, None]
    assert out["hidden"][0] == "подробно 2" and out["hidden"][1].startswith("Выбранная строка скрыта")
    assert out["gone"][0] is None and out["gone"][1].startswith("Выбранный объект недоступен")


@node
def test_a_server_list_asks_the_screen_for_a_selection_it_has_not_loaded(tmp_path):
    out = run(tmp_path, """
  const fetched = [];
  const l = mount(App.list({load: async (q) => ({items: ITEMS.slice(q.offset, q.offset + q.limit), total: 45, counts: {}}), key: (x) => x.id, row: (x) => x.name,
    selected: () => 41, selectedItem: async (key) => { fetched.push(key); return ITEMS[40]; }}));
  await l.ready; await wait();
  out.pin = [l.el.querySelector('.lst-pin').querySelector('.lst-row').getAttribute('data-key'), [...fetched]];
  await l.el.querySelector('.lst-count').dispatch('click'); out.redraw = fetched.length;           // a redraw does not ask again
  await l.refresh(); out.again = fetched.length;                                                  // a refresh does: the object may have been saved
""")
    assert out["pin"] == ["41", ["41"]] and out["redraw"] == 1 and out["again"] == 2


# -- BUG-014: dialogs ---------------------------------------------------------------------------------------------------------------------
@node
def test_a_confirmation_starts_on_cancel_keeps_tab_inside_and_gives_the_focus_back(tmp_path):
    out = run(tmp_path, """
  const opener = h('button', {type: 'button'}, 'Удалить'); shell.append(opener); opener.focus();
  let ran = 0;
  const m = App.confirmBox('Удалить работу?', 'Это нельзя отменить.', 'Удалить', async () => { ran += 1; });
  const names = () => doc.activeElement && doc.activeElement.textContent;
  out.start = names(); out.inert = shell.hasAttribute('inert');
  const buttons = m.el.querySelectorAll('button');                                  // ×, Отмена, Удалить: the browser moves between them itself
  const close = buttons[0], last = buttons[buttons.length - 1];
  last.focus(); await doc.dispatch('keydown', {key: 'Tab', shiftKey: false}); out.forward = names();      // Tab from the last wraps to the first
  close.focus(); await doc.dispatch('keydown', {key: 'Tab', shiftKey: true}); out.backward = names();     // Shift+Tab from the first wraps to the last
  opener.focus(); await doc.dispatch('keydown', {key: 'Tab', shiftKey: false}); out.fromBehind = names();  // focus that got behind the dialog is pulled back in
  await doc.dispatch('keydown', {key: 'Escape'});
  out.closed = [doc.body.querySelector('.modal'), ran, shell.hasAttribute('inert'), doc.activeElement === opener];
""")
    assert out["start"] == "Отмена" and out["inert"] is True
    assert (out["forward"], out["backward"], out["fromBehind"]) == ("×", "Удалить", "×")
    assert out["closed"] == [None, 0, False, True]                              # Escape never confirms


@node
def test_only_the_dialog_on_top_answers_escape_and_the_one_below_is_inert_until_then(tmp_path):
    out = run(tmp_path, """
  const first = App.modal('Первое', h('input', {}), [{label: 'ОК', run: (m) => m.close()}]);
  const second = App.modal('Второе', h('p', {}, 'вложенное'), [{label: 'Закрыть', run: (m) => m.close()}]);
  out.under = first.el.parentNode.hasAttribute('inert');
  await doc.dispatch('keydown', {key: 'Escape'});
  out.afterOne = [doc.body.querySelectorAll('.modal').length, first.el.parentNode.hasAttribute('inert'), shell.hasAttribute('inert')];
  await doc.dispatch('keydown', {key: 'Escape'});
  out.afterTwo = [doc.body.querySelectorAll('.modal').length, shell.hasAttribute('inert')];
""")
    assert out["under"] is True and out["afterOne"] == [1, False, True] and out["afterTwo"] == [0, False]


@node
def test_when_the_opener_is_gone_the_focus_goes_to_the_main_area(tmp_path):
    out = run(tmp_path, """
  const main = h('main', {id: 'main', tabindex: '-1'}); shell.append(main);
  const opener = h('button', {type: 'button'}, 'Открыть'); main.append(opener); opener.focus();
  const m = App.modal('Окно', h('p', {}, 'текст'), [{label: 'Закрыть', run: (d) => d.close()}]);
  opener.remove();
  m.close();
  out.focus = doc.activeElement && doc.activeElement.getAttribute('id');
""")
    assert out["focus"] == "main"


# -- BUG-015: the skip link --------------------------------------------------------------------------------------------------------------
@node
def test_the_skip_link_moves_the_focus_to_the_content_and_leaves_the_address_alone(tmp_path):
    out = run(tmp_path, """
  const root = shell;
  App.register({id: 'experiments', render: async () => h('div', {}, 'экран')});
  App.register({id: 'findings', render: async () => h('div', {}, 'выводы')});
  ctx.location.hash = '#/findings/7?tab=x';
  App.start(); await wait(6);
  out.afterRender = [doc.activeElement && doc.activeElement.getAttribute('id'), ctx.location.hash];       // a new screen starts at its content
  doc.activeElement.blur();
  const skip = h('a', {class: 'skip', href: '#main'}, 'Перейти к содержимому'); doc.body.append(skip);
  let stopped = false;
  await doc.dispatch('click', {target: skip, preventDefault() { stopped = true; }}); await wait();
  out.skip = [stopped, doc.activeElement && doc.activeElement.getAttribute('id'), ctx.location.hash];
  ctx.location.hash = '#main'; await handlers.hashchange(); await wait();
  out.hashchange = [ctx.location.hash, doc.activeElement && doc.activeElement.getAttribute('id'), root.textContent.includes('выводы')];
""")
    assert out["afterRender"] == ["main", "#/findings/7?tab=x"]
    assert out["skip"] == [True, "main", "#/findings/7?tab=x"]
    assert out["hashchange"] == ["#/findings/7?tab=x", "main", True]             # the route, its argument and its query survive; the screen is the same
