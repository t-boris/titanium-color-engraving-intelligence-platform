"""Source numbers behind a count (feature ux-growing-collections-p0, REQ-002): «Наблюдения-основания: 24» with a button instead of a line of
twenty-four numbers, every number a link, long lists fifty at a time, the photographs behind observation numbers asked of the real server for
the page that is shown, and a failed request leaving the numbers on the screen as plain text with a retry. The screen runs in node over a
small DOM; only a real browser and a screen reader can say how it looks and sounds."""
import pytest

import obs
from growing_ui import node, run_node, serving

pytestmark = node
FILES = ["screens/source-refs.js"]
EXPORTS = ("SourceRefs",)


@pytest.fixture
def server(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        yield app.state.store, port


def seen(store, count):
    """``count`` observations, each with a photograph and a layer of its own; the last number asked about is one nobody has."""
    w = obs.setup(store)
    return [obs.add(store, w, (50 + i % 20, 0, 0), evidence={"layer_name": f"C{i + 1:02d}"}) for i in range(count)]


def test_a_short_list_is_open_and_a_long_one_is_a_count_with_a_button(tmp_path):
    out = run_node(tmp_path, 0, FILES, """
      const href = (id) => '/analysis/' + id;
      const short = mount(ctx.SourceRefs.refs([3, 1, 2, 3], {href}));
      await until(() => qa(short, 'a').length === 2 + 1);
      out.short = {count: q(short, '.srefs-count').textContent, toggle: q(short, '.srefs-toggle') !== null, hidden: q(short, '.srefs-list').hidden,
        links: qa(short, 'a').map((a) => a.getAttribute('href'))};
      const none = mount(ctx.SourceRefs.refs([], {label: 'Фото'}));
      out.none = none.textContent;
      const long = mount(ctx.SourceRefs.refs(Array.from({length: 24}, (_, i) => i + 1), {href, label: 'Наблюдения-основания'}));
      const toggle = q(long, '.srefs-toggle'), list = q(long, '.srefs-list');
      out.closed = {count: q(long, '.srefs-count').textContent, expanded: toggle.getAttribute('aria-expanded'), controls: toggle.getAttribute('aria-controls') === list.getAttribute('id'),
        hidden: list.hidden, drawn: qa(long, 'a').length, caption: toggle.textContent, kind: toggle.localName, type: toggle.getAttribute('type'), name: list.getAttribute('aria-label')};
      await toggle.dispatch('click');
      await until(() => qa(long, 'a').length === 24);
      out.open = {expanded: toggle.getAttribute('aria-expanded'), hidden: list.hidden, caption: toggle.textContent, status: q(long, '.srefs-status').textContent,
        first: qa(long, 'a')[0].textContent, last: qa(long, 'a')[23].textContent, more: q(long, '.srefs-more') !== null};
      await toggle.dispatch('click');
      out.closedAgain = {expanded: toggle.getAttribute('aria-expanded'), hidden: list.hidden, caption: toggle.textContent, count: q(long, '.srefs-count').textContent};
    """, EXPORTS)
    assert out["short"] == {"count": "3", "toggle": False, "hidden": False, "links": ["#/analysis/3", "#/analysis/1", "#/analysis/2"]}   # repeats are one number
    assert out["none"] == "Фото: none"
    assert out["closed"] == {"count": "24", "expanded": "false", "controls": True, "hidden": True, "drawn": 0, "caption": "Show IDs", "kind": "button",
                             "type": "button", "name": "Наблюдения-основания"}
    assert out["open"] == {"expanded": "true", "hidden": False, "caption": "Hide IDs", "status": "showing 24 of 24", "first": "#1", "last": "#24", "more": False}
    assert out["closedAgain"] == {"expanded": "false", "hidden": True, "caption": "Show IDs", "count": "24"}


def test_a_long_list_is_shown_fifty_at_a_time_and_every_number_is_reached(tmp_path):
    out = run_node(tmp_path, 0, FILES, """
      const box = mount(ctx.SourceRefs.refs(Array.from({length: 120}, (_, i) => i + 1), {href: (id) => '/analysis/' + id, mark: ''}));
      await q(box, '.srefs-toggle').dispatch('click');
      await until(() => qa(box, 'a').length === 50);
      const steps = [];
      while (q(box, '.srefs-more')) {
        const more = q(box, '.srefs-more');
        steps.push([qa(box, 'a').length, more.textContent, q(box, '.srefs-status').textContent]);
        await more.dispatch('click');
        await until(() => qa(box, 'a').length > steps[steps.length - 1][0]);
        steps.push(['focus', doc.activeElement && doc.activeElement.textContent]);
      }
      out.steps = steps;
      out.all = qa(box, 'a').map((a) => a.textContent);
      out.status = q(box, '.srefs-status').textContent;
    """, EXPORTS)
    assert out["steps"] == [[50, "Show 50 more", "showing 50 of 120"], ["focus", "51"],      # the keyboard continues at the first new number
                            [100, "Show 20 more", "showing 100 of 120"], ["focus", "101"]]
    assert out["all"] == [str(i) for i in range(1, 121)] and out["status"] == "showing 120 of 120"                 # none dropped, none repeated


def test_observation_numbers_are_named_by_the_server_a_page_at_a_time(server, tmp_path):
    store, port = server
    ids = seen(store, 60) + [999999]                                                         # the last number is one nobody has
    out = run_node(tmp_path, port, FILES, f"""
      const ids = {ids};
      const box = mount(ctx.SourceRefs.observations(ids));
      out.before = requests('/observations/refs').length;                                    // collapsed: nothing is asked
      await q(box, '.srefs-toggle').dispatch('click');
      await until(() => qa(box, 'a').length === 50);
      out.first = {{asked: requests('/observations/refs').map((x) => x.url.split('ids=')[1].split(',').length), link: qa(box, 'a')[0].getAttribute('href'),
        title: qa(box, 'a')[0].getAttribute('title'), notes: qa(box, '.srefs-note').slice(0, 2).map((n) => n.textContent)}};
      await q(box, '.srefs-more').dispatch('click');
      await until(() => qa(box, 'li').length === 61);
      out.second = {{asked: requests('/observations/refs').map((x) => x.url.split('ids=')[1].split(',').length), links: qa(box, 'a').length,
        lastText: qa(box, 'li')[60].textContent, lastIsLink: qa(qa(box, 'li')[60], 'a').length, count: q(box, '.srefs-count').textContent}};
    """, EXPORTS)
    assert out["before"] == 0
    assert out["first"]["asked"] == [50]                                                      # one request for the page that is shown, not for all sixty-one
    assert out["first"]["link"].startswith("#/analysis/") and out["first"]["title"].startswith("#") and "p.raw" in out["first"]["title"]
    assert out["first"]["notes"] == [" p.raw · C01", " p.raw · C02"]
    assert out["second"]["asked"] == [50, 11] and out["second"]["links"] == 60 and out["second"]["count"] == "61"
    assert out["second"]["lastIsLink"] == 0 and "not found" in out["second"]["lastText"] and out["second"]["lastText"].startswith("#999999")   # kept, said, not a link


def test_a_failed_request_keeps_the_numbers_as_text_and_can_be_retried(server, tmp_path):
    store, port = server
    ids = seen(store, 8)
    out = run_node(tmp_path, port, FILES, f"""
      const ids = {ids};
      breakNext('/observations/refs');
      const box = mount(ctx.SourceRefs.observations(ids, {{short: 3}}));
      await q(box, '.srefs-toggle').dispatch('click');
      await until(() => q(box, '.srefs-fail') !== null);
      out.failed = {{alert: q(box, '.srefs-fail').getAttribute('role'), text: q(box, '.srefs-fail').textContent, links: qa(box, 'a').length,
        numbers: qa(box, 'li').map((li) => li.textContent), count: q(box, '.srefs-count').textContent}};
      await q(box, '.srefs-retry').dispatch('click');
      await until(() => q(box, '.srefs-fail') === null && qa(box, 'a').length === 8);
      out.retried = {{asked: requests('/observations/refs').length, links: qa(box, 'a').length, retry: q(box, '.srefs-retry') !== null}};
    """, EXPORTS)
    assert out["failed"]["alert"] == "alert" and "Cannot reach the local service" in out["failed"]["text"] and "Retry" in out["failed"]["text"]
    assert out["failed"]["links"] == 0 and out["failed"]["numbers"] == [f"#{i}" for i in ids] and out["failed"]["count"] == "8"   # every number is still on the screen
    assert out["retried"] == {"asked": 2, "links": 8, "retry": False}


def test_a_second_click_while_the_request_is_on_its_way_does_nothing(server, tmp_path):
    store, port = server
    ids = seen(store, 70)
    out = run_node(tmp_path, port, FILES, f"""
      const ids = {ids};
      const gate = hold('/observations/refs');
      const box = mount(ctx.SourceRefs.observations(ids));
      await q(box, '.srefs-toggle').dispatch('click');
      await until(() => gate.seen);
      const during = {{more: q(box, '.srefs-more').disabled, status: q(box, '.srefs-status').textContent, plain: qa(box, 'li').length, links: qa(box, 'a').length}};
      q(box, '.srefs-more').dispatch('click');                                              // a click on a disabled button: ignored
      await sleep(30);
      during.asked = requests('/observations/refs').length;
      gate.release();
      await until(() => qa(box, 'a').length === 50);
      out.during = during;
      out.after = {{asked: requests('/observations/refs').length, more: q(box, '.srefs-more').disabled}};
    """, EXPORTS)
    assert out["during"] == {"more": True, "status": "Loading…", "plain": 50, "links": 0, "asked": 1}                  # the numbers are there while the names are awaited
    assert out["after"]["asked"] == 1 and out["after"]["more"] is False
