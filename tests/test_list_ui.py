"""The compact list every long list of the app uses (feature findings-you-can-manage-short-lists-re-check, REQ-001, DEC-090): one line per
item, details under the row only when opened, filter chips with counts, search, sort, «showing N of M» and «Show more» by pages, row
actions that do not open the row, the server's pages. Run in node over the small DOM of the other screen tests."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = """
const {context, load} = require(%(dom)s);
const ctx = context({});
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js']);
const tick = () => new Promise((r) => setTimeout(r, 0));
const App = ctx.App;
const {h} = App;
const rows = (l) => l.el.querySelectorAll('.lst-main').map((r) => r.textContent);
const chips = (l) => l.el.querySelectorAll('.lst-chip').map((c) => c.textContent);
const count = (l) => l.el.querySelector('.lst-count').textContent;
const more = (l) => { const b = l.el.querySelector('.lst-foot').querySelector('button'); return b ? b.textContent : null; };
const ITEMS = Array.from({length: 45}, (_, i) => ({id: i + 1, kind: i %% 3 === 0 ? 'a' : 'b', name: 'item ' + (i + 1), size: (i * 7) %% 45}));
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, body) -> dict:
    script = tmp_path / "list.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "ui": json.dumps(str(UI) + "/"),
                                 "tables": json.dumps(TABLES), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@node
def test_a_long_list_shows_one_page_and_shows_more_on_request(tmp_path):
    out = run(tmp_path, """
  const l = App.list({items: ITEMS, row: (x) => h('span', {class: 'lst-text'}, x.name)});
  await l.ready;
  out.first = rows(l).length; out.count = count(l); out.more = more(l);
  await l.el.querySelector('.lst-foot').querySelector('button').dispatch('click'); await tick();
  out.second = rows(l).length; out.more2 = more(l);
  await l.el.querySelector('.lst-foot').querySelector('button').dispatch('click'); await tick();
  out.third = rows(l).length; out.more3 = more(l); out.count3 = count(l);
""")
    assert (out["first"], out["count"], out["more"]) == (20, "showing 20 of 45", "Show 20 more")
    assert (out["second"], out["more2"]) == (40, "Show 5 more")
    assert (out["third"], out["more3"], out["count3"]) == (45, None, "showing 45 of 45")


@node
def test_filter_chips_show_their_counts_and_narrow_the_list(tmp_path):
    out = run(tmp_path, """
  const l = App.list({items: ITEMS, row: (x) => x.name, search: (x) => x.name,
    filters: [{key: 'kind', label: 'Kind', options: [['a', 'First'], ['b', 'Second'], ['c', 'Empty']], test: (x, v) => x.kind === v}]});
  await l.ready;
  out.chips = chips(l);
  await l.el.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith('First')).dispatch('click'); await tick();
  out.after = count(l); out.pressed = l.el.querySelectorAll('.lst-chip').filter((c) => c.getAttribute('aria-pressed') === 'true').map((c) => c.textContent);
  const search = l.el.querySelector('.lst-search'); search.value = 'item 1'; await search.dispatch('input'); await tick(); await tick();
  out.searched = rows(l); out.chipsSearched = chips(l);
""")
    assert out["chips"] == ["All · 45", "First · 15", "Second · 30"]          # an option that would show nothing is not offered
    assert out["after"] == "showing 15 of 15" and out["pressed"] == ["First · 15"]
    # «item 1», «item 10», …, «item 19» among the first kind (ids 1, 4, 7, …): 1, 10, 13, 16, 19
    assert out["searched"] == ["item 1", "item 10", "item 13", "item 16", "item 19"]
    assert out["chipsSearched"] == ["All · 11", "First · 5", "Second · 6"]


@node
def test_the_sort_choice_reorders_and_the_first_sort_is_the_default(tmp_path):
    out = run(tmp_path, """
  const l = App.list({items: ITEMS.slice(0, 5), row: (x) => x.name,
    sorts: [['id', 'In order', (p, q) => p.id - q.id], ['size', 'By size', (p, q) => q.size - p.size]]});
  await l.ready;
  out.first = rows(l);
  const select = l.el.querySelector('select'); select.value = 'size'; await select.dispatch('change'); await tick();
  out.sorted = rows(l); out.state = l.state().sort;
""")
    assert out["first"] == ["item 1", "item 2", "item 3", "item 4", "item 5"]
    assert out["sorted"] == ["item 5", "item 4", "item 3", "item 2", "item 1"] and out["state"] == "size"


@node
def test_details_are_built_only_when_a_row_is_opened_and_one_row_is_open_at_a_time(tmp_path):
    out = run(tmp_path, """
  let built = 0;
  const pressed = [];
  const l = App.list({items: ITEMS.slice(0, 3), key: (x) => x.id, row: (x) => x.name,
    details: (x) => { built += 1; return h('p', {}, 'details ' + x.id); },
    actions: (x) => [App.btn('Hide', () => pressed.push(x.id))]});
  await l.ready;
  out.builtBefore = built;
  await l.el.querySelectorAll('.lst-main')[1].dispatch('click'); await tick();
  out.open1 = l.el.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  await l.el.querySelectorAll('.lst-main')[2].dispatch('click'); await tick();
  out.open2 = l.el.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  out.expanded = l.el.querySelectorAll('.lst-main').map((m) => m.getAttribute('aria-expanded'));
  await l.el.querySelectorAll('.lst-act')[0].querySelector('button').dispatch('click'); await tick();
  out.pressed = pressed; out.open3 = l.el.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  out.built = built;
""")
    assert out["builtBefore"] == 0
    assert out["open1"] == ["details 2"] and out["open2"] == ["details 3"]
    assert out["expanded"] == ["false", "false", "true"]
    assert out["pressed"] == [1] and out["open3"] == ["details 3"]            # an action does not open or close a row
    assert out["built"] == 2


@node
def test_a_server_list_asks_for_one_page_with_the_chosen_sort_and_filters_and_appends_the_next(tmp_path):
    out = run(tmp_path, """
  const asked = [];
  const l = App.list({
    load: async (q) => { asked.push(q); const all = ITEMS.filter((x) => !q.filters.kind || x.kind === q.filters.kind);
      return {items: all.slice(q.offset, q.offset + q.limit), total: all.length, counts: {kind: {'': 45, a: 15, b: 30}}}; },
    row: (x) => x.name, initial: {sort: 'new', filters: {kind: 'b'}},
    sorts: [['important', 'Important first'], ['new', 'Newest first']],
    filters: [{key: 'kind', label: 'Kind', options: [['a', 'First'], ['b', 'Second']]}],
    onChange: (s) => asked.push({changed: s})});
  await l.ready;
  out.firstRows = rows(l).length; out.count = count(l); out.chips = chips(l);
  await l.el.querySelector('.lst-foot').querySelector('button').dispatch('click'); await tick();
  out.secondRows = rows(l).length;
  out.asked = asked;
""")
    assert out["firstRows"] == 20 and out["count"] == "showing 20 of 30"
    assert out["chips"] == ["All · 45", "First · 15", "Second · 30"]
    first, second, changed = out["asked"]
    assert first == {"sort": "new", "filters": {"kind": "b"}, "search": "", "offset": 0, "limit": 20}
    assert second == {"sort": "new", "filters": {"kind": "b"}, "search": "", "offset": 20, "limit": 20}
    assert changed == {"changed": {"sort": "new", "filters": {"kind": "b"}, "search": ""}}
    assert out["secondRows"] == 30


@node
def test_a_remembered_drop_down_choice_that_is_gone_stays_visible_and_all_clears_it(tmp_path):
    out = run(tmp_path, """
  const l = App.list({items: ITEMS, row: (x) => x.name, initial: {filters: {kind: 'c'}},
    filters: [{key: 'kind', label: 'Kind', select: true, options: [['a', 'First'], ['b', 'Second']], test: (x, v) => x.kind === v}]});
  await l.ready;
  const select = l.el.querySelector('select');
  out.options = select.querySelectorAll('option').map((o) => [o.textContent, o.selected]);
  out.count = count(l);
  select.value = ''; await select.dispatch('change'); await tick();
  out.after = count(l);
""")
    assert out["options"] == [["all · 45", False], ["First · 15", False], ["Second · 30", False], ["previous selection is unavailable", True]]
    assert out["count"] == "showing 0 of 0" and out["after"] == "showing 20 of 45"


@node
def test_a_field_or_link_in_a_line_works_by_itself_and_a_line_can_carry_its_own_class(tmp_path):
    out = run(tmp_path, """
  const l = App.list({items: ITEMS.slice(0, 2), key: (x) => x.id, rowClass: (x) => (x.id === 2 ? 'excluded' : ''),
    row: (x) => [h('input', {type: 'checkbox', class: 'box'}), h('a', {href: '#/x', class: 'go'}, 'link'), h('span', {class: 'lst-text'}, x.name)],
    details: (x) => h('p', {}, 'details ' + x.id)});
  await l.ready;
  await l.el.querySelectorAll('.box')[0].dispatch('click'); await tick();
  await l.el.querySelectorAll('.go')[0].dispatch('click'); await tick();
  out.openAfterControls = l.el.querySelectorAll('.lst-det').filter((d) => !d.hidden).length;
  await l.el.querySelectorAll('.lst-text')[0].dispatch('click'); await tick();
  out.openAfterText = l.el.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  out.classes = l.el.querySelectorAll('.lst-row').map((r) => r.className);
""")
    assert out["openAfterControls"] == 0 and out["openAfterText"] == ["details 1"]
    assert out["classes"] == ["lst-row open", "lst-row excluded"]


@node
def test_a_screen_can_open_a_line_and_gets_its_details_once_drawn(tmp_path):
    out = run(tmp_path, """
  const l = App.list({items: ITEMS.slice(0, 3), key: (x) => x.id, row: (x) => x.name, details: async (x) => h('p', {}, 'details ' + x.id)});
  await l.ready;
  const det = await l.open(2);
  out.text = det.textContent;
  out.open = l.el.querySelectorAll('.lst-det').filter((d) => !d.hidden).map((d) => d.textContent);
  out.again = (await l.open(2)).textContent;                                   // opening an open line keeps it open
  out.missing = await l.open(99);
""")
    assert out["text"] == "details 2" and out["open"] == ["details 2"] and out["again"] == "details 2" and out["missing"] is None
