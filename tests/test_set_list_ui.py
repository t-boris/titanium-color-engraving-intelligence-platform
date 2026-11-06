"""The sets of a laser and lens on the colour map as a compact list (feature ux-growing-collections-p0, REQ-002, REQ-003): a search and pages
of twenty instead of a button for every RAW pair, the set on the screen kept in view when the search or the page leaves it out, and a
reason with a way back when nothing matches. Run in node over a small DOM; the colour-map screen that places the list is not part of this
test, only the component it will call."""
from growing_ui import node, run_node

pytestmark = node
FILES = ["screens/set-list.js"]
EXPORTS = ("SetList",)
SETS = """const sets = Array.from({length: 50}, (_, i) => ({id: 'raw-' + (i + 1), title: 'Набор ' + (i + 1), note: i % 5 === 0 ? 'калибровка' : 'RAW · ' + (i + 1) + ' пар'}));
sets.unshift({id: 'cal', title: 'Откалиброванные наблюдения', note: 'по эталонной карте'});"""


def test_the_list_shows_twenty_sets_and_the_rest_by_an_explicit_button(tmp_path):
    out = run_node(tmp_path, 0, FILES, SETS + """
      let chosen = [];
      const list = ctx.SetList.list(sets, {selected: 'cal', onSelect: (id) => chosen.push(id)});
      const box = mount(list.el);
      await list.ready;
      out.first = {rows: lines(box).length, count: count(box), pressed: qa(box, '.lm-set').map((b) => b.getAttribute('aria-pressed')).filter((x) => x === 'true').length,
        firstTitle: qa(box, 'strong')[0].textContent, pin: q(box, '.lst-pin') !== null};
      await button(box, 'Show 20 more').dispatch('click');
      await button(box, 'Show 11 more').dispatch('click');
      out.all = {rows: lines(box).length, titles: qa(box, 'strong').map((s) => s.textContent).length, count: count(box)};
      await qa(box, '.lm-set')[3].dispatch('click');
      out.chosen = chosen;
    """, EXPORTS)
    assert out["first"] == {"rows": 20, "count": "showing 20 of 51", "pressed": 1, "firstTitle": "Откалиброванные наблюдения", "pin": False}
    assert out["all"] == {"rows": 51, "titles": 51, "count": "showing 51 of 51"}
    assert out["chosen"] == ["raw-3"]


def test_a_set_the_page_leaves_out_stays_in_view_and_a_search_finds_a_set(tmp_path):
    out = run_node(tmp_path, 0, FILES, SETS + """
      const list = ctx.SetList.list(sets, {selected: 'raw-44', onSelect: () => {}});
      const box = mount(list.el);
      await list.ready;
      out.beyond = {rows: rows(box).length, lines: lines(box).length, note: q(box, '.lst-pin-note').textContent.trim(), pinned: qa(q(box, '.lst-pin'), 'strong')[0].textContent,
        pressed: qa(q(box, '.lst-pin'), '.lm-set')[0].getAttribute('aria-pressed')};
      const search = q(box, '.lst-search');
      search.focus();
      search.value = 'набор 7';
      await search.dispatch('input');
      await until(() => count(box) === 'showing 1 of 1');
      out.found = {titles: qa(q(box, '.lst-rows'), 'strong').map((s) => s.textContent), focus: doc.activeElement === search,
        note: q(box, '.lst-pin-note').textContent.trim()};                           // raw-44 is not «Набор 7»: hidden by the search, said
      search.value = 'zzz';
      await search.dispatch('input');
      await until(() => q(box, '.lst-none') !== null);
      out.none = {text: q(box, '.lst-empty').textContent, conditions: qa(q(box, '.lst-none'), 'p')[1].textContent, rows: rows(box).length};
      await button(q(box, '.lst-none'), 'Clear search and filters').dispatch('click');
      await until(() => rows(box).length === 20);
      out.back = {rows: rows(box).length, search: search.value, count: count(box)};
    """, EXPORTS)
    assert (out["beyond"]["rows"], out["beyond"]["lines"]) == (20, 21) and out["beyond"]["pinned"] == "Набор 44" and out["beyond"]["pressed"] == "true"
    assert out["beyond"]["note"].startswith("The selected row is beyond the displayed portion of the list.")
    assert out["found"]["titles"] == ["Набор 7"] and out["found"]["focus"] is True                 # the search is typed in without losing the cursor
    assert out["found"]["note"].startswith("The selected row is hidden by the search or filters.")
    assert out["none"]["text"] == "Наборов с таким названием нет." and out["none"]["conditions"] == "Conditions: search “zzz”." and out["none"]["rows"] == 0
    assert out["back"] == {"rows": 20, "search": "", "count": "showing 20 of 51"}


def test_an_empty_collection_says_so(tmp_path):
    out = run_node(tmp_path, 0, FILES, """
      const list = ctx.SetList.list([], {selected: null, onSelect: () => {}});
      const box = mount(list.el);
      await list.ready;
      out.text = q(box, '.lst-empty').textContent;
    """, EXPORTS)
    assert out == {"text": "Наборов нет"}
