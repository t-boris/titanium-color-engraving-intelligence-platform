/* The experiment card and the experiment list (REQ-028, DEC-055): the same on the «Эксперименты» screen and on a laser's page.
   The list is short (DEC-090): a line per experiment, its card (thumbnail, kind, laser, titanium, tasks) opens under the line; search, state,
   task, order and pages of 20. There is no separate list of plates, engravings or photographs anywhere: each experiment opens whole. */
'use strict';
const ExperimentCards = (() => {
  const {h, link, pill} = App;
  const layers = (n) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'слой' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'слоя' : 'слоёв'}`;
  const STATES = [['needs_review', 'Нужна проверка'], ['plate_ready', 'Ждут фото'], ['accepted', 'Приняты']];
  const SHORT = {needs_review: 'к проверке', plate_ready: 'ждёт фото', accepted: 'принят'};
  const recent = (p, q) => String(q.last_activity || '').localeCompare(String(p.last_activity || ''));
  const SORTS = [['recent', 'Сначала недавние', recent],
    ['review', 'Сначала к проверке', (p, q) => (q.needs_review || 0) - (p.needs_review || 0) || recent(p, q)],
    ['title', 'По названию', (p, q) => I18N.name(p.title).localeCompare(I18N.name(q.title), 'ru')]];

  function card(e) {
    return h('article', {class: 'dashboard-item exp-card'},
      h('a', {class: 'exp-thumb-link', href: '#/experiment/' + encodeURIComponent(e.key), 'aria-label': `Открыть эксперимент ${I18N.name(e.title)}`},
        // a list thumbnail is small (BUG-001); experiments.LIST_THUMBNAIL_PX and `titanium-platform warm-cache` use this query
        e.main_pair_id ? h('img', {class: 'exp-thumb', loading: 'lazy', alt: '', src: `/api/pairs/${e.main_pair_id}/photo.png?visibility=lifted&size=480`})
          : h('div', {class: 'exp-thumb exp-thumb-empty'}, 'Плата')),
      h('div', {class: 'exp-card-body'},
        h('div', {class: 'dashboard-item-top'}, link('/experiment/' + encodeURIComponent(e.key), I18N.name(e.title)),
          pill(e.status_text, e.status === 'accepted' ? 'ok' : 'warn')),
        h('p', {class: 'dashboard-item-type'}, I18N.name(e.kind)),
        h('p', {class: 'dashboard-meta'}, [e.laser, e.lens, e.material].filter(Boolean).join(' · ') || 'Лазер не указан'),
        (e.tasks || []).length ? h('p', {class: 'dashboard-meta'}, 'Задачи: ' + e.tasks.map((k) => Tasks.name(k)).join(', ')) : null,
        h('div', {class: 'dashboard-item-foot'},
          h('span', {}, e.checks ? `${e.photos} фото · измерено ${layers(e.layers_measured)}${e.needs_review ? ` · ${e.needs_review} к проверке` : ''}` : 'Фото ещё нет'),
          h('span', {class: 'spacer'}), h('span', {class: 'muted small'}, (e.last_activity || '').slice(0, 10)))));
  }

  /** The experiments as a short list: a line each (title, state, last activity), the card under a line on a click, «Открыть» at its end.
      The search reads the title, kind, laser, lens and titanium; the filters are the state and the engraving task (only the tasks the
      experiments have). ``id`` keeps the choices for the session (each screen its own); ``empty`` is said when nothing passes. */
  function list(experiments, {id = null, empty = 'Экспериментов нет.'} = {}) {
    const order = Object.keys(TaskText.KIND);
    const rank = (k) => (order.includes(k) ? order.indexOf(k) : order.length);
    const tasks = [...new Set(experiments.flatMap((e) => e.tasks || []))].sort((a, b) => rank(a) - rank(b));
    return App.list({id, items: experiments, key: (e) => e.key, empty,
      search: (e) => [e.title, I18N.name(e.title), e.kind, I18N.name(e.kind), e.laser, e.lens, e.material].filter(Boolean).join(' '),
      filters: [{key: 'status', label: 'Состояние эксперимента', options: STATES, test: (e, v) => e.status === v},
        ...(tasks.length ? [{key: 'task', label: 'Задача', select: true, all: 'все задачи', options: tasks.map((k) => [k, Tasks.name(k)]),
          test: (e, v) => (e.tasks || []).includes(v)}] : [])],
      sorts: SORTS,
      row: (e) => [h('span', {class: 'lst-text'}, I18N.name(e.title)), pill(SHORT[e.status] || e.status_text, e.status === 'accepted' ? 'ok' : 'warn'),
        h('span', {class: 'muted small'}, (e.last_activity || '').slice(0, 10))],
      details: card,
      actions: (e) => [h('a', {class: 'btn btn-small', href: '#/experiment/' + encodeURIComponent(e.key)}, 'Открыть')]}).el;
  }

  return {card, list, layers};
})();
