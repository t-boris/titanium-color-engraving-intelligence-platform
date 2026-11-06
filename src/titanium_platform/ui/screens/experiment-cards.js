/* The experiment card and list (REQ-028, DEC-055), shared by the experiments screen and a laser's page.
   The list is short (DEC-090): a line per experiment, its card (thumbnail, kind, laser, titanium, tasks) opens under the line; search, state,
   task, order and pages of 20. There is no separate list of plates, engravings or photographs anywhere: each experiment opens whole. */
'use strict';
const ExperimentCards = (() => {
  const {h, link, pill} = App;
  const layers = (n) => `${n} ${n === 1 ? 'layer' : 'layers'}`;
  const STATES = [['needs_review', 'Needs review'], ['plate_ready', 'Awaiting photo'], ['accepted', 'Accepted']];
  const SHORT = {needs_review: 'Needs review', plate_ready: 'Awaiting photo', accepted: 'Accepted'};
  const FULL = {needs_review: 'Review needed', plate_ready: 'Plate ready: awaiting photo', accepted: 'Accepted'};
  const recent = (p, q) => String(q.last_activity || '').localeCompare(String(p.last_activity || ''));
  const SORTS = [['recent', 'Most recent', recent],
    ['review', 'Needs review first', (p, q) => (q.needs_review || 0) - (p.needs_review || 0) || recent(p, q)],
    ['title', 'Title', (p, q) => I18N.name(p.title).localeCompare(I18N.name(q.title), 'en')]];

  function card(e) {
    return h('article', {class: 'dashboard-item exp-card'},
      h('a', {class: 'exp-thumb-link', href: '#/experiment/' + encodeURIComponent(e.key), 'aria-label': `Open experiment ${I18N.name(e.title)}`},
        // a list thumbnail is small (BUG-001); experiments.LIST_THUMBNAIL_PX and `titanium-platform warm-cache` use this query
        e.main_pair_id ? h('img', {class: 'exp-thumb', loading: 'lazy', alt: '', src: `/api/pairs/${e.main_pair_id}/photo.png?visibility=lifted&size=480`})
          : h('div', {class: 'exp-thumb exp-thumb-empty'}, 'Plate')),
      h('div', {class: 'exp-card-body'},
        h('div', {class: 'dashboard-item-top'}, link('/experiment/' + encodeURIComponent(e.key), I18N.name(e.title)),
          pill(FULL[e.status] || e.status_text, e.status === 'accepted' ? 'ok' : 'warn')),
        h('p', {class: 'dashboard-item-type'}, I18N.name(e.kind)),
        h('p', {class: 'dashboard-meta'}, [e.laser, e.lens, e.material].filter(Boolean).join(' · ') || 'Laser not specified'),
        (e.tasks || []).length ? h('p', {class: 'dashboard-meta'}, 'Tasks: ' + e.tasks.map((k) => Tasks.name(k)).join(', ')) : null,
        h('div', {class: 'dashboard-item-foot'},
          h('span', {}, e.checks ? `${e.photos} ${e.photos === 1 ? 'photo' : 'photos'} · ${layers(e.layers_measured)} measured${e.needs_review ? ` · ${e.needs_review} to review` : ''}` : 'No photos yet'),
          h('span', {class: 'spacer'}), h('span', {class: 'muted small'}, (e.last_activity || '').slice(0, 10)))));
  }

  /** The experiments as a short list: a line each, with its card and an Open action.
      The search reads the title, kind, laser, lens and titanium; the filters are the state and the engraving task (only the tasks the
      experiments have). ``id`` keeps the choices for the session (each screen its own); ``empty`` is said when nothing passes. */
  function list(experiments, {id = null, empty = 'No experiments yet.', noResults = empty} = {}) {
    const order = Object.keys(TaskText.KIND);
    const rank = (k) => (order.includes(k) ? order.indexOf(k) : order.length);
    const tasks = [...new Set(experiments.flatMap((e) => e.tasks || []))].sort((a, b) => rank(a) - rank(b));
    return App.list({id, items: experiments, key: (e) => e.key, empty, noResults,
      search: (e) => [e.title, I18N.name(e.title), e.kind, I18N.name(e.kind), e.laser, e.lens, e.material].filter(Boolean).join(' '),
      filters: [{key: 'status', label: 'Experiment status', options: STATES, test: (e, v) => e.status === v},
        ...(tasks.length ? [{key: 'task', label: 'Task', select: true, all: 'All tasks', options: tasks.map((k) => [k, Tasks.name(k)]),
          test: (e, v) => (e.tasks || []).includes(v)}] : [])],
      sorts: SORTS,
      row: (e) => [h('span', {class: 'lst-text'}, I18N.name(e.title)), pill(SHORT[e.status] || e.status_text, e.status === 'accepted' ? 'ok' : 'warn'),
        h('span', {class: 'muted small'}, (e.last_activity || '').slice(0, 10))],
      details: card,
      actions: (e) => [h('a', {class: 'btn btn-small', href: '#/experiment/' + encodeURIComponent(e.key)}, 'Open')]}).el;
  }

  return {card, list, layers};
})();
