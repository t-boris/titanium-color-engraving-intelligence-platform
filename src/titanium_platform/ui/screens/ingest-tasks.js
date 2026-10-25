/* Задачи гравировки на проверке пары (REQ-020): у каждого слоя — задача, выбранная для него, иначе задача всей работы,
   иначе задача его плана или платы, иначе та, что следует из режима LightBurn. Выбор не меняет измерений; при принятии
   задача записывается с каждым наблюдением. Рядом — метрики слоя со способом и основанием измерения. */
'use strict';
const IngestTasks = (() => {
  const {h, field, put, toast, fail} = App;
  let reopen = null;           // the layer whose task was just chosen: open again when the page is drawn after the change

  /** The card «Задачи гравировки» of a pair not yet accepted. The layers are a short list (findings-you-can-manage-short-lists-re-check,
      REQ-005): a line per layer with its task now, the choice for the layer and the metrics under the line. */
  function card(pair, reload) {
    const layers = (pair.check?.layers || []).filter((l) => l.regions > 0 || l.measured_lab);
    const run = async (body) => {
      try { await put(`/pairs/${pair.id}/tasks`, body); toast('Задача записана', 'ok'); reload(); } catch (e) { fail(e); }
    };
    const work = Tasks.select(pair.work_task || '', {empty: pair.plan_task ? `по плану: ${Tasks.name(pair.plan_task.kind)}` : 'по слоям LightBurn',
      aria: 'Задача всей работы', onChange: (value) => run({layer_index: null, task: value || null})});
    const chosen = pair.layer_tasks || {};
    const service = (l) => l.role && l.role !== 'test feature';
    const details = (l) => {
      const derived = l.task ? (l.task.basis === 'explicit' ? l.task.derived || l.task.kind : l.task.kind) : null;
      const choice = service(l) ? h('span', {class: 'muted small'}, 'служебный слой: задача по его роли')
        : Tasks.select(chosen[String(l.index)] || '', {empty: 'не выбрана для слоя', extra: [['layer', `по слою LightBurn: ${Tasks.name(derived)}`]],
          aria: `Задача слоя ${l.name}`, onChange: (value) => { reopen = {pair: pair.id, key: String(l.index)}; run({layer_index: l.index, task: value || null}); }});
      return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, field('Выбор для слоя', choice)),
        h('div', {class: 'stack small'}, h('strong', {}, 'Метрики: значение и основание'), Tasks.metrics(l.metrics) || h('span', {class: 'muted small'}, 'не измерен')));
    };
    const kinds = [...new Set(layers.map((l) => l.task && l.task.kind).filter(Boolean))];
    const list = App.list({id: `ingest-tasks:${pair.id}`, items: layers, key: (l) => l.index, empty: 'Слоёв нет', details,
      open: reopen && reopen.pair === pair.id ? reopen.key : null,
      row: (l) => [h('span', {class: 'lst-text', title: l.name}, l.name), Tasks.badge(l.task), l.measured_lab ? null : h('span', {class: 'muted small'}, 'не измерен')],
      search: (l) => l.name,
      filters: kinds.length > 1 ? [{key: 'task', label: 'Задача сейчас', options: kinds.map((k) => [k, Tasks.name(k)]), test: (l, v) => (l.task && l.task.kind) === v}] : [],
      sorts: [['order', 'По порядку', (a, b) => a.index - b.index]]});
    reopen = null;
    return h('div', {class: 'card stack'}, h('h3', {}, 'Задачи гравировки'),
      h('p', {class: 'muted small'}, 'Для чего делался каждый слой. Результаты разных задач не смешиваются: залитый текст и заливка с одинаковыми '
        + 'настройками остаются разными записями. Если задача не выбрана, слой берёт задачу работы, плана или своего режима LightBurn. '
        + 'Нажмите на слой, чтобы выбрать задачу для него и увидеть его метрики.'),
      h('div', {class: 'grid g3'}, field('Задача всей работы', work)),
      list.el);
  }
  return {card};
})();
