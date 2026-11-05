/* The history of colour knowledge on its first page with an explicit «Показать ещё» (ux-growing-collections-p0, REQ-002). The history of a knowledge entry
   as the compact list, read from the server a page at a time (GET /knowledge/:id/history): the newest events first, the kind of event as a
   filter with counts, the observations an event rests on under its line. Nothing is dropped: every event is reached by «Показать ещё», and
   a rollback stays on the line of the event it undoes. */
'use strict';
const KnowledgeHistory = (() => {
  const {h, btn, pill, get, post, confirmBox} = App;
  const SORTS = [['newest', 'Сначала новые'], ['oldest', 'Сначала старые']];
  const when = (at) => (at || '').slice(0, 16).replace('T', ' ');

  /** The history list of the entry ``kid``. ``opts``: ``stage`` (its stage now: a rollback from production says so), ``labels`` ({STAGE, EVENT}:
      the names of stages and events, as the knowledge screen has them), ``after`` (called after a rollback; the screen is drawn again). */
  function list(kid, opts) {
    const {STAGE, EVENT} = opts.labels;
    const stageName = (s) => (s ? STAGE[s] || s : '—');
    // an operator's own reason is shown as written; a reason the program wrote is translated
    const reasonOf = (e) => (e.type === 'demoted' ? I18N.known(e.reason) ?? e.reason : I18N.tr(e.reason));
    return App.list({
      id: 'kn.history.' + kid,
      load: async ({sort, filters, offset, limit}) => {
        const q = new URLSearchParams({offset, limit, order: sort === 'oldest' ? 'oldest' : 'newest'});
        if (filters.type) q.set('type', filters.type);
        const page = await get(`/knowledge/${kid}/history?` + q);
        return {items: page.items, total: page.total, counts: page.counts};
      },
      key: (e) => e.id,
      row: (e) => [h('span', {class: 'muted small'}, when(e.at)), pill(EVENT[e.type] || e.type),
        h('span', {class: 'small'}, `${stageName(e.from_stage)} → ${stageName(e.to_stage)}`),
        h('span', {class: 'lst-text small muted', title: reasonOf(e)}, reasonOf(e))],
      details: (e) => h('div', {class: 'stack small'}, h('p', {}, reasonOf(e)),
        SourceRefs.observations(e.observation_ids, {label: 'Наблюдения-основания события'})),
      actions: (e) => (e.from_stage && e.type !== 'rollback'
        ? [btn('Откатить переход', () => confirmBox('Откатить переход', 'Будет добавлено новое событие; стадия не повышается.', 'Откатить', async () => {
          await post(`/knowledge/${kid}/rollback`, {event_id: e.id, confirm_production: opts.stage === 'production'});
          if (opts.after) opts.after(); else App.render();
        }), 'btn-small')] : []),
      filters: [{key: 'type', label: 'Событие', select: true, options: Object.entries(EVENT)}],
      sorts: SORTS,
      empty: 'Истории нет', className: 'kn-history-list'});
  }

  return {list};
})();
