"""The history of a knowledge entry on its first page with an explicit «Show more» (feature ux-growing-collections-p0, REQ-002): the
compact list read from the real server a page at a time, the kind of event as a filter with counts, the order, the observations behind an
event as a count with a button, and a rollback that stays on its event. Run in node over a small DOM; the screen that places the list
(knowledge.js) is not part of this test, only the component it will call."""
import pytest

import obs
from growing_ui import node, run_node, serving
from titanium_platform import knowledge as kn

pytestmark = node
FILES = ["screens/source-refs.js", "screens/knowledge-history.js"]
EXPORTS = ("KnowledgeHistory",)
LABELS = """const labels = {STAGE: {measured: 'Measured', candidate: 'Candidate', repeated: 'Repeated', validated: 'Validated', production: 'Production'},
  EVENT: {created: 'created', promoted: 'promoted automatically', questioned: 'marked questionable', approved: 'approved for production',
  demoted: 'manually demoted', confirmed: 'flag removed', rollback: 'rollback'}};"""


@pytest.fixture
def entry(tmp_path):
    """An entry with 46 events: created, 44 promoted or questioned in turn (45 and the newest, 46, rest on thirty observations)."""
    with serving(tmp_path / "data") as (app, port):
        store = app.state.store
        w = obs.setup(store)
        obs.add(store, w, (50, 0, 0))
        kn.refresh(store, *w["setup"])
        kid = kn.list_for_setup(store, *w["setup"])[0]["id"]
        with store.transaction():
            for i in range(44):
                kn._event(store, kid, "questioned" if i % 4 == 0 else "promoted", "measured", "candidate", f"reason {i}", [i + 1, i + 2])
            kn._event(store, kid, "promoted", "candidate", "repeated", "latest reason", list(range(1, 31)))
        yield kid, port


def test_only_the_first_page_is_read_and_the_rest_comes_by_an_explicit_button(entry, tmp_path):
    kid, port = entry
    out = run_node(tmp_path, port, FILES, LABELS + f"""
      const history = ctx.KnowledgeHistory.list({kid}, {{labels, stage: 'candidate'}});
      const box = mount(history.el);
      await history.ready;
      const asked = () => requests('/history').map((x) => x.url.split('/history?')[1]);
      out.first = {{rows: lines(box).length, count: count(box), asked: asked(), whole: requests('/api/knowledge/{kid}').filter((x) => !x.url.includes('/history')).length,
        newest: lines(box)[0].querySelector('.lst-text').textContent, button: button(box, 'Show 20 more') !== null}};
      await button(box, 'Show 20 more').dispatch('click');
      await until(() => lines(box).length === 40);
      out.second = {{rows: lines(box).length, count: count(box), asked: asked()}};
      await button(box, 'Show 6 more').dispatch('click');
      await until(() => lines(box).length === 46);
      const keys = lines(box).map((l) => l.getAttribute('data-key'));
      out.third = {{rows: keys.length, distinct: new Set(keys).size, count: count(box), more: qa(box, 'button').some((b) => b.textContent.startsWith('Show more')),
        oldest: lines(box)[45].querySelector('.lst-text').textContent}};
    """, EXPORTS)
    assert out["first"]["rows"] == 20 and out["first"]["count"] == "showing 20 of 46"
    assert out["first"]["asked"] == ["offset=0&limit=20&order=newest"] and out["first"]["whole"] == 0     # the first page only; the whole entry is never read
    assert out["first"]["newest"] == "latest reason" and out["first"]["button"]
    assert out["second"]["rows"] == 40 and out["second"]["asked"][1] == "offset=20&limit=20&order=newest"
    assert (out["third"]["rows"], out["third"]["distinct"], out["third"]["count"], out["third"]["more"]) == (46, 46, "showing 46 of 46", False)   # every event once
    assert out["third"]["oldest"] != "latest reason"


def test_the_kind_of_event_filters_with_counts_and_the_order_can_be_turned(entry, tmp_path):
    kid, port = entry
    out = run_node(tmp_path, port, FILES, LABELS + f"""
      const history = ctx.KnowledgeHistory.list({kid}, {{labels}});
      const box = mount(history.el);
      await history.ready;
      const kind = qa(box, 'label').find((l) => l.textContent.startsWith('Event')).querySelector('select');
      out.options = kind.options.map((o) => o.textContent);
      kind.value = 'questioned';
      await kind.dispatch('change');
      await until(() => count(box) === 'showing 11 of 11');
      out.filtered = {{rows: lines(box).length, pills: [...new Set(lines(box).map((l) => qa(l, '.pill')[0].textContent))], asked: requests('/history').pop().url.split('?')[1]}};
      kind.value = '';
      await kind.dispatch('change');
      await until(() => lines(box).length === 20);
      const order = qa(box, 'select').find((s) => s.getAttribute('aria-label') === 'Sort order');
      order.value = 'oldest';
      await order.dispatch('change');
      await until(() => requests('/history').pop().url.includes('order=oldest') && qa(lines(box)[0], '.pill')[0].textContent === 'created');
      out.oldest = {{first: qa(lines(box)[0], '.pill')[0].textContent, rollback: qa(lines(box)[0], 'button').map((b) => b.textContent),
        next: qa(lines(box)[1], 'button').map((b) => b.textContent)}};
    """, EXPORTS)
    assert out["options"][0] == "all · 46" and "marked questionable · 11" in out["options"] and "promoted automatically · 34" in out["options"]
    assert out["filtered"]["rows"] == 11 and out["filtered"]["pills"] == ["marked questionable"] and "type=questioned" in out["filtered"]["asked"]
    assert out["oldest"]["first"] == "created" and out["oldest"]["rollback"] == []                      # the first event has no earlier stage to return to
    assert out["oldest"]["next"] == ["Roll back transition"]


def test_the_observations_behind_an_event_are_a_count_with_a_button_and_a_rollback_stays_on_its_event(entry, tmp_path):
    kid, port = entry
    out = run_node(tmp_path, port, FILES, LABELS + f"""
      stub('/rollback', {{status: 200, json: {{}}}});
      let after = 0;
      const history = ctx.KnowledgeHistory.list({kid}, {{labels, stage: 'production', after: () => {{ after += 1; }}}});
      const box = mount(history.el);
      await history.ready;
      const newest = lines(box)[0];
      await newest.querySelector('.lst-main').dispatch('click');                              // the details of the newest event: thirty observations behind it
      await until(() => qa(box, '.srefs-count').length === 1);
      const refs = q(box, '.srefs');
      out.details = {{count: q(refs, '.srefs-count').textContent, label: q(refs, '.srefs-label').textContent, toggle: q(refs, '.srefs-toggle').textContent,
        drawn: qa(refs, 'a').length, reason: qa(box, 'p')[0] ? qa(box, 'p').map((p) => p.textContent)[0] : null}};
      await button(newest, 'Roll back transition').dispatch('click');
      const ok = button(doc.body, 'Roll back');
      out.dialog = {{title: q(doc.body, '.modal').getAttribute('aria-label'), focusedFirst: doc.activeElement && doc.activeElement.textContent}};
      await ok.dispatch('click');
      const sent = requests('/rollback');
      out.rollback = {{count: sent.length, method: sent[0].method, body: JSON.parse(sent[0].body), after}};
    """, EXPORTS)
    assert out["details"]["count"] == "30" and out["details"]["label"] == "Observations supporting this event: " and out["details"]["toggle"] == "Show IDs"
    assert out["details"]["drawn"] == 0 and out["details"]["reason"] == "latest reason"            # thirty numbers are not printed until asked for
    assert out["dialog"] == {"title": "Roll back transition", "focusedFirst": "Cancel"}                      # a quick Enter never confirms
    assert out["rollback"]["count"] == 1 and out["rollback"]["method"] == "POST" and out["rollback"]["after"] == 1
    assert out["rollback"]["body"]["confirm_production"] is True and isinstance(out["rollback"]["body"]["event_id"], int)


def test_a_failed_page_keeps_the_events_already_shown_and_offers_a_retry(entry, tmp_path):
    kid, port = entry
    out = run_node(tmp_path, port, FILES, LABELS + f"""
      const history = ctx.KnowledgeHistory.list({kid}, {{labels}});
      const box = mount(history.el);
      await history.ready;
      breakNext('/history');
      await button(box, 'Show 20 more').dispatch('click');
      await until(() => q(box, '.lst-fail') !== null);
      out.failed = {{rows: lines(box).length, alert: q(box, '.lst-fail').getAttribute('role'), text: q(box, '.lst-fail').textContent}};
      await q(box, '.lst-retry').dispatch('click');
      await until(() => lines(box).length === 40 && q(box, '.lst-fail') === null);
      out.retried = {{rows: lines(box).length, count: count(box)}};
    """, EXPORTS)
    assert out["failed"]["rows"] == 20 and out["failed"]["alert"] == "alert" and "Cannot reach the local service" in out["failed"]["text"]
    assert out["retried"] == {"rows": 40, "count": "showing 40 of 46"}


def test_an_entry_without_events_says_so(tmp_path):
    out = run_node(tmp_path, 0, FILES, LABELS + """
      stub('/history', {status: 200, json: {items: [], total: 0, all: 0, offset: 0, limit: 20, counts: {type: {'': 0}}}});
      const history = ctx.KnowledgeHistory.list(7, {labels});
      const box = mount(history.el);
      await history.ready;
      out.text = q(box, '.lst-empty').textContent;
      out.rows = lines(box).length;
    """, EXPORTS)
    assert out == {"text": "No history yet", "rows": 0}


def test_the_knowledge_page_reads_the_first_page_of_the_history_and_counts_the_observations_behind_the_colour(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        store = app.state.store
        w = obs.setup(store)
        for i in range(12):
            obs.add(store, w, (50 + i * 0.1, 0, 0))
        kn.refresh(store, *w["setup"])
        kid = kn.list_for_setup(store, *w["setup"])[0]["id"]
        with store.transaction():
            for i in range(44):
                kn._event(store, kid, "questioned" if i % 4 == 0 else "promoted", "measured", "candidate", f"reason {i}", [i + 1])
        behind = len(kn.get(store, kid)["summary"]["observation_ids"])
        out = run_node(tmp_path, port, ["hardware.js", "tasks.js", "screens/evidence-summary.js", *FILES, "screens/knowledge.js"], LABELS.replace("const labels", "const unused") + f"""
          const tree = mount(await ctx.KnowledgeView.render({kid}));
          const history = q(tree, '.kn-history'), evidence = q(tree, '.kn-evidence');
          out.history = {{rows: rows(history).length, count: count(history), head: q(history, '.os-col-head').textContent, more: button(history, 'Show 20 more') !== null,
            entry: requests('/api/knowledge/{kid}').filter((x) => !x.url.includes('/history')).map((x) => x.url),
            pages: requests('/history').map((x) => x.url.split('?')[1])}};
          out.evidence = {{head: q(evidence, '.os-col-head').textContent, count: q(evidence, '.srefs-count').textContent, drawn: qa(evidence, 'a').length,
            toggle: q(evidence, '.srefs-toggle') !== null, text: q(evidence, '.os-scroll').textContent}};
          out.terms = qa(tree, '.terms-note').map((n) => [q(n, 'summary').textContent, n.textContent.includes('Technical identifier: knowledge #')]);
          await button(history, 'Show 20 more').dispatch('click');
          await until(() => rows(history).length === 40);
          out.second = {{count: count(history), pages: requests('/history').length}};
        """, ("KnowledgeView",))
    assert out["history"]["rows"] == 20 and out["history"]["count"] == "showing 20 of 45" and out["history"]["more"]
    assert out["history"]["head"] == "History45"                                                         # the size of the history is told without reading it all
    assert out["history"]["entry"] == [f"/api/knowledge/{kid}?history_limit=0"]                         # the entry comes without its events
    assert out["history"]["pages"] == ["offset=0&limit=20&order=newest"]
    assert behind > 5 and out["evidence"]["count"] == str(behind) and out["evidence"]["drawn"] == 0 and out["evidence"]["toggle"]    # a count, the numbers on request
    assert out["evidence"]["head"] == f"Supporting observations{behind}" and out["evidence"]["text"].startswith("Observation IDs: ")
    assert out["second"] == {"count": "showing 40 of 45", "pages": 2}
    assert out["terms"] == [["What is a knowledge record?", True], ["What is a stage?", False], ["What is evidence?", False]]
