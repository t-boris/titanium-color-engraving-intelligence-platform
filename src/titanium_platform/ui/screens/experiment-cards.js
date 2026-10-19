/* Карточка эксперимента в списке (REQ-028, DEC-055): одна и та же на экране «Эксперименты» и на странице лазера.
   Отдельного списка плат, гравировок или фотографий нет нигде: каждый эксперимент открывается целиком. */
'use strict';
const ExperimentCards = (() => {
  const {h, link, pill} = App;
  const layers = (n) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'слой' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'слоя' : 'слоёв'}`;

  function card(e) {
    return h('article', {class: 'dashboard-item exp-card'},
      h('a', {class: 'exp-thumb-link', href: '#/experiment/' + encodeURIComponent(e.key), 'aria-label': `Открыть эксперимент ${I18N.name(e.title)}`},
        // a list thumbnail is small (BUG-001)
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

  /** Список экспериментов или пояснение, что их нет. */
  const list = (experiments, empty) => (experiments.length ? h('div', {class: 'dashboard-list'}, ...experiments.map(card))
    : h('p', {class: 'muted small'}, empty));

  return {card, list, layers};
})();
